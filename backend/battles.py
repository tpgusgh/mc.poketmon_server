"""Player-vs-player battle challenges + ELO-ish ranking.

Flow: A challenges B (both must be logged in) -> B accepts -> both play the
match in-game -> each player self-reports their own outcome ("I won" / "I
lost"), since Pixelmon logs nothing about PvP results anywhere the server can
read.

- If both report and their claims agree (one says "I won", the other says
  "I lost", pointing at the same winner) -> applied immediately.
- If both report and disagree (both claim victory, or both claim defeat) ->
  sent to the admin to decide.
- If only one player has reported once the report window expires -> that
  lone report's implied winner is applied as-is (silence forfeits your say,
  but an honest "I lost" report from the other side still wins them the
  match -- silence never overrides an actual claim).
- If neither reports before the window expires -> sent to the admin.

The admin (kimhyunhoking) is the sole tie-breaker for anything that isn't a
clean, uncontested self-report.
"""
import json
import random
import time
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException

import rcon
from auth import ADMIN_UUID, get_notif_seen_at, get_session_player, list_claimed_players, set_notif_seen_at

router = APIRouter()

BATTLES_FILE = Path(__file__).parent / "battles.json"
RANKING_FILE = Path(__file__).parent / "battle_ranking.json"

STARTING_SCORE = 1000
WIN_RANGE = (14, 17)
LOSE_RANGE = (12, 15)

BATTLE_ARENA_COORDS = "1347 64 -7457"  # where both battlers are teleported once a challenge is accepted

REPORT_TIMEOUT_SECONDS = 30 * 60  # 30 minutes after acceptance to self-report
CHALLENGE_EXPIRY_SECONDS = 60 * 60  # pending challenges expire 1 hour after being sent
DAILY_BATTLE_LIMIT_PER_OPPONENT = 3  # same two players can only actually battle 3x/day


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_battles() -> dict:
    if not BATTLES_FILE.exists():
        return {"next_id": 1, "challenges": []}
    try:
        return json.loads(BATTLES_FILE.read_text())
    except json.JSONDecodeError:
        return {"next_id": 1, "challenges": []}


def _save_battles(data: dict) -> None:
    BATTLES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _load_ranking() -> dict:
    if not RANKING_FILE.exists():
        return {}
    try:
        return json.loads(RANKING_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def _save_ranking(ranking: dict) -> None:
    RANKING_FILE.write_text(json.dumps(ranking, ensure_ascii=False, indent=2))


def _require_player(session: str | None) -> dict:
    player = get_session_player(session)
    if not player:
        raise HTTPException(401, "로그인이 필요합니다")
    if not player["uuid"]:
        raise HTTPException(400, "플레이어를 먼저 선택해주세요")
    return player


def _require_admin(session: str | None) -> dict:
    player = _require_player(session)
    if player["uuid"] != ADMIN_UUID:
        raise HTTPException(403, "관리자만 접근할 수 있습니다")
    return player


def _find_challenge(data: dict, challenge_id: int) -> dict:
    for c in data["challenges"]:
        if c["id"] == challenge_id:
            return c
    raise HTTPException(404, "존재하지 않는 배틀입니다")


def _apply_result(challenge: dict, winner_uuid: str) -> None:
    loser_uuid = (
        challenge["opponent_uuid"]
        if winner_uuid == challenge["challenger_uuid"]
        else challenge["challenger_uuid"]
    )
    winner_name = (
        challenge["challenger_name"]
        if winner_uuid == challenge["challenger_uuid"]
        else challenge["opponent_name"]
    )
    loser_name = (
        challenge["opponent_name"]
        if winner_uuid == challenge["challenger_uuid"]
        else challenge["challenger_name"]
    )

    win_delta = random.randint(*WIN_RANGE)
    lose_delta = -random.randint(*LOSE_RANGE)

    ranking = _load_ranking()
    ranking.setdefault(winner_uuid, {"name": winner_name, "score": STARTING_SCORE})
    ranking.setdefault(loser_uuid, {"name": loser_name, "score": STARTING_SCORE})
    ranking[winner_uuid]["name"] = winner_name
    ranking[loser_uuid]["name"] = loser_name
    ranking[winner_uuid]["score"] += win_delta
    ranking[loser_uuid]["score"] += lose_delta
    _save_ranking(ranking)

    challenge["status"] = "resolved"
    challenge["resolved_winner"] = winner_uuid
    challenge["resolved_at"] = _now_iso()
    challenge["winner_delta"] = win_delta
    challenge["loser_delta"] = lose_delta


def _implied_winner(challenge: dict, reporter_uuid: str, result: str) -> str:
    if result == "win":
        return reporter_uuid
    return (
        challenge["opponent_uuid"]
        if reporter_uuid == challenge["challenger_uuid"]
        else challenge["challenger_uuid"]
    )


def _process_accepted(challenge: dict) -> bool:
    """Advances an 'accepted' challenge based on self-reports + timeout.
    Returns True if it changed (caller should persist)."""
    if challenge["status"] != "accepted":
        return False

    reports = challenge["reports"]
    if len(reports) == 2:
        implied = {
            uuid: _implied_winner(challenge, uuid, result)
            for uuid, result in reports.items()
        }
        distinct_winners = set(implied.values())
        if len(distinct_winners) == 1:
            _apply_result(challenge, distinct_winners.pop())
        else:
            challenge["status"] = "disputed"
            challenge["dispute_reason"] = "mismatch"
        return True

    accepted_at = datetime.fromisoformat(challenge["accepted_at"]).timestamp()
    if time.time() - accepted_at < REPORT_TIMEOUT_SECONDS:
        return False

    if len(reports) == 1:
        reporter_uuid, result = next(iter(reports.items()))
        _apply_result(challenge, _implied_winner(challenge, reporter_uuid, result))
    else:
        challenge["status"] = "disputed"
        challenge["dispute_reason"] = "no_reports"
    return True


def _process_pending(challenge: dict) -> bool:
    """Expires a 'pending' challenge 1 hour after it was sent if nobody responded."""
    if challenge["status"] != "pending":
        return False
    created_at = datetime.fromisoformat(challenge["created_at"]).timestamp()
    if time.time() - created_at < CHALLENGE_EXPIRY_SECONDS:
        return False
    challenge["status"] = "expired"
    return True


def _load_battles_processed() -> dict:
    data = _load_battles()
    changed = False
    for c in data["challenges"]:
        if _process_pending(c):
            changed = True
        if _process_accepted(c):
            changed = True
    if changed:
        _save_battles(data)
    return data


def get_resolved_battles() -> list[dict]:
    """Resolved battles, for the server story to weave into its timeline."""
    data = _load_battles_processed()
    return [c for c in data["challenges"] if c["status"] == "resolved"]


def get_ranking_scores() -> dict:
    """uuid -> {"name":, "score":}, for the faction leaderboard to aggregate."""
    return _load_ranking()


def _battles_today_between(data: dict, uuid_a: str, uuid_b: str) -> int:
    """Counts battles between this pair that actually got underway today
    (accepted, still disputed, or resolved) -- pending requests that were
    declined/cancelled/expired never happened, so they don't count."""
    today = date.today().isoformat()
    count = 0
    for c in data["challenges"]:
        if c["status"] not in ("accepted", "disputed", "resolved"):
            continue
        if {c["challenger_uuid"], c["opponent_uuid"]} != {uuid_a, uuid_b}:
            continue
        ts = c.get("accepted_at") or c["created_at"]
        if datetime.fromisoformat(ts).date().isoformat() == today:
            count += 1
    return count


def _game_online_claimed_players(exclude_uuid: str | None = None) -> list[dict]:
    """Claimed players who are actually connected to the Minecraft server right
    now -- being logged into the website isn't what "available to challenge"
    means here."""
    from main import get_online_player_names  # deferred: avoids a circular import at module load time

    online_names = get_online_player_names()
    return [p for p in list_claimed_players(exclude_uuid=exclude_uuid) if p["name"] in online_names]


@router.get("/battle/online-players")
def online_players(session: str | None = Cookie(default=None)):
    me = _require_player(session)
    return {"players": _game_online_claimed_players(exclude_uuid=me["uuid"])}


@router.post("/battle/challenge")
def challenge(payload: dict, session: str | None = Cookie(default=None)):
    me = _require_player(session)

    from main import get_online_player_names  # deferred: avoids a circular import at module load time

    if me["name"] not in get_online_player_names():
        raise HTTPException(400, "본인도 게임에 접속 중이어야 배틀을 신청할 수 있습니다")

    opponent_uuid = payload.get("opponent_uuid")
    opponent = next(
        (p for p in _game_online_claimed_players() if p["uuid"] == opponent_uuid), None
    )
    if not opponent:
        raise HTTPException(400, "상대방이 게임에 접속 중이 아닙니다")
    if opponent["uuid"] == me["uuid"]:
        raise HTTPException(400, "자기 자신에게는 신청할 수 없습니다")

    data = _load_battles_processed()
    # Prevent duplicate open challenges between the same two players.
    for c in data["challenges"]:
        if c["status"] in ("pending", "accepted") and {
            c["challenger_uuid"],
            c["opponent_uuid"],
        } == {me["uuid"], opponent["uuid"]}:
            raise HTTPException(400, "이미 진행 중인 배틀 신청이 있습니다")

    if _battles_today_between(data, me["uuid"], opponent["uuid"]) >= DAILY_BATTLE_LIMIT_PER_OPPONENT:
        raise HTTPException(
            400, f"같은 상대와는 하루에 최대 {DAILY_BATTLE_LIMIT_PER_OPPONENT}번까지만 배틀할 수 있습니다"
        )

    new_challenge = {
        "id": data["next_id"],
        "challenger_uuid": me["uuid"],
        "challenger_name": me["name"],
        "opponent_uuid": opponent["uuid"],
        "opponent_name": opponent["name"],
        "status": "pending",
        "created_at": _now_iso(),
        "accepted_at": None,
        "reports": {},
        "dispute_reason": None,
        "resolved_winner": None,
        "resolved_at": None,
    }
    data["next_id"] += 1
    data["challenges"].append(new_challenge)
    _save_battles(data)

    try:
        rcon.tellraw(
            "@a",
            f"⚔️ {me['name']}님이 {opponent['name']}님에게 배틀을 신청했습니다! "
            f"웹사이트(hi.mieung.kr)에서 수락해주세요.",
        )
    except Exception:
        pass  # best-effort -- a notification failure shouldn't block the challenge itself

    return new_challenge


@router.get("/battle/incoming")
def incoming(session: str | None = Cookie(default=None)):
    me = _require_player(session)
    data = _load_battles_processed()
    return {
        "challenges": [
            c
            for c in data["challenges"]
            if c["opponent_uuid"] == me["uuid"] and c["status"] == "pending"
        ]
    }


@router.get("/battle/outgoing")
def outgoing(session: str | None = Cookie(default=None)):
    me = _require_player(session)
    data = _load_battles_processed()
    return {
        "challenges": [
            c
            for c in data["challenges"]
            if c["challenger_uuid"] == me["uuid"] and c["status"] == "pending"
        ]
    }


@router.post("/battle/cancel")
def cancel(payload: dict, session: str | None = Cookie(default=None)):
    me = _require_player(session)
    challenge_id = payload.get("challenge_id")

    data = _load_battles_processed()
    c = _find_challenge(data, challenge_id)
    if c["challenger_uuid"] != me["uuid"]:
        raise HTTPException(403, "본인이 신청한 배틀만 취소할 수 있습니다")
    if c["status"] != "pending":
        raise HTTPException(400, "취소할 수 있는 상태가 아닙니다")

    c["status"] = "cancelled"
    _save_battles(data)
    return c


@router.post("/battle/respond")
def respond(payload: dict, session: str | None = Cookie(default=None)):
    me = _require_player(session)
    challenge_id = payload.get("challenge_id")
    accept = payload.get("accept")

    data = _load_battles_processed()
    c = _find_challenge(data, challenge_id)
    if c["opponent_uuid"] != me["uuid"]:
        raise HTTPException(403, "이 배틀 신청에 응답할 권한이 없습니다")
    if c["status"] != "pending":
        raise HTTPException(400, "이미 처리된 신청입니다")

    if accept:
        c["status"] = "accepted"
        c["accepted_at"] = _now_iso()
        try:
            # Run via RCON (server console), not a player-triggered command,
            # so this isn't blocked by the vanilla op-only permission on /tp.
            rcon.rcon_command(f"tp {c['challenger_name']} {BATTLE_ARENA_COORDS}")
            rcon.rcon_command(f"tp {c['opponent_name']} {BATTLE_ARENA_COORDS}")
        except Exception:
            pass  # best-effort -- a teleport failure shouldn't block accepting the challenge
        try:
            rcon.tellraw_component(
                "@a",
                {
                    "text": f"⚔️ {c['challenger_name']}님과 {c['opponent_name']}님의 배틀이 시작됐습니다! ",
                    "color": "aqua",
                    "bold": True,
                    "extra": [
                        {
                            "text": "[관전하러가기]",
                            "color": "green",
                            "bold": True,
                            "clickEvent": {
                                "action": "run_command",
                                "value": f"/tpa {c['opponent_name']}",
                            },
                            "hoverEvent": {
                                "action": "show_text",
                                "contents": f"{c['opponent_name']}님에게 텔레포트 요청을 보냅니다 (상대가 수락해야 이동함)",
                            },
                        }
                    ],
                },
            )
        except Exception:
            pass  # best-effort -- a notification failure shouldn't block the response itself
    else:
        c["status"] = "declined"
    _save_battles(data)
    return c


@router.get("/battle/active")
def active(session: str | None = Cookie(default=None)):
    """Accepted battles the caller is part of, awaiting self-reports."""
    me = _require_player(session)
    data = _load_battles_processed()
    mine = [
        c
        for c in data["challenges"]
        if c["status"] == "accepted"
        and me["uuid"] in (c["challenger_uuid"], c["opponent_uuid"])
    ]
    for c in mine:
        c["i_reported"] = me["uuid"] in c["reports"]
    return {"challenges": mine}


@router.post("/battle/report")
def report(payload: dict, session: str | None = Cookie(default=None)):
    me = _require_player(session)
    challenge_id = payload.get("challenge_id")
    result = payload.get("result")
    if result not in ("win", "lose"):
        raise HTTPException(400, "result는 'win' 또는 'lose'여야 합니다")

    data = _load_battles_processed()
    c = _find_challenge(data, challenge_id)
    if me["uuid"] not in (c["challenger_uuid"], c["opponent_uuid"]):
        raise HTTPException(403, "이 배틀에 참여하지 않았습니다")
    if c["status"] != "accepted":
        raise HTTPException(400, "결과를 보고할 수 있는 상태가 아닙니다")

    c["reports"][me["uuid"]] = result
    _process_accepted(c)
    _save_battles(data)
    return c


@router.get("/battle/ranking")
def ranking():
    ranking_data = _load_ranking()
    rows = [
        {
            "uuid": p["uuid"],
            "name": p["name"],
            "score": ranking_data.get(p["uuid"], {}).get("score", STARTING_SCORE),
        }
        for p in list_claimed_players()
    ]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return {"ranking": rows}


@router.get("/battle/notifications")
def notifications(session: str | None = Cookie(default=None)):
    """Unread-notification feed: incoming challenges (always "unread" until
    accepted/declined/expired) plus resolved battle results the player hasn't
    seen yet (tracked via a per-account timestamp)."""
    me = _require_player(session)
    data = _load_battles_processed()

    incoming = [
        c
        for c in data["challenges"]
        if c["opponent_uuid"] == me["uuid"] and c["status"] == "pending"
    ]

    seen_at = get_notif_seen_at(me["account_id"])
    resolved_unseen = [
        c
        for c in data["challenges"]
        if c["status"] == "resolved"
        and me["uuid"] in (c["challenger_uuid"], c["opponent_uuid"])
        and datetime.fromisoformat(c["resolved_at"]).timestamp() > seen_at
    ]

    return {
        "incoming": incoming,
        "resolved_unseen": resolved_unseen,
        "count": len(incoming) + len(resolved_unseen),
    }


@router.post("/battle/notifications/ack")
def ack_notifications(session: str | None = Cookie(default=None)):
    """Marks resolved-battle notifications as seen. Incoming challenges aren't
    ack'd here -- they clear naturally once accepted/declined/cancelled."""
    me = _require_player(session)
    set_notif_seen_at(me["account_id"])
    return {"ok": True}


@router.get("/admin/disputes")
def admin_disputes(session: str | None = Cookie(default=None)):
    _require_admin(session)
    data = _load_battles_processed()
    return {"disputes": [c for c in data["challenges"] if c["status"] == "disputed"]}


@router.post("/admin/resolve")
def admin_resolve(payload: dict, session: str | None = Cookie(default=None)):
    _require_admin(session)
    challenge_id = payload.get("challenge_id")
    winner_uuid = payload.get("winner_uuid")

    data = _load_battles_processed()
    c = _find_challenge(data, challenge_id)
    if c["status"] != "disputed":
        raise HTTPException(400, "판정이 필요한 상태가 아닙니다")
    if winner_uuid not in (c["challenger_uuid"], c["opponent_uuid"]):
        raise HTTPException(400, "승자는 두 참가자 중 한 명이어야 합니다")

    _apply_result(c, winner_uuid)
    _save_battles(data)
    return c
