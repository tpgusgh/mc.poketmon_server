"""Simple username/password accounts, each claiming exactly one Minecraft
player identity.

Microsoft/Xbox OAuth login didn't pan out (no Azure app ever got wired up),
so this replaces it with plain registration: pick a username/password and
claim which Minecraft player you are from the roster. Once claimed, nobody
else can register as that player. If someone else wrongly claims your name,
anyone can file a dispute against that claim (no login needed to file one --
you can't register under your own name to prove who you are if it's already
taken by an impostor); the admin (kimhyunhoking) reviews disputes and can
strip the bogus claim, freeing the player up again.
"""
import hashlib
import json
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException, Response

import rcon

router = APIRouter()

ADMIN_UUID = "3bbd52c7-65d2-43f7-8d61-344607722b25"  # kimhyunhoking, per ops.json

FACTIONS = ("valor", "mystic", "instinct", "harmony")
FACTION_INFO = {
    "valor": {"name": "발로", "color": "#dc2626"},
    "mystic": {"name": "미스틱", "color": "#2563eb"},
    "instinct": {"name": "인스팅트", "color": "#eab308"},
    "harmony": {"name": "하모니", "color": "#ec4899"},
}

ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"
SESSIONS_FILE = Path(__file__).parent / "sessions.json"
DISPUTES_FILE = Path(__file__).parent / "account_disputes.json"

SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days
COOKIE_DOMAIN = ".mieung.kr"

# Login brute-force protection: lock out a username after too many failures
# in a short window. In-memory (resets on API restart) -- this is a
# hobby-scale deterrent, not a durable audit log.
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60

USERCACHE_FILES = [
    Path("/home/hyunho/mcserver/usercache.json"),
    Path("/home/hyunho/mcserver2/usercache.json"),
]

# Bans only apply to the live server (mcserver) -- RCON isn't enabled on the
# mcserver2 staging box, and there's no reason to ban anyone there anyway.
BANNED_PLAYERS_FILE = Path("/home/hyunho/mcserver/banned-players.json")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _load_accounts() -> dict:
    return _load_json(ACCOUNTS_FILE, {"accounts": []})


def _save_accounts(data: dict) -> None:
    _save_json(ACCOUNTS_FILE, data)


def _load_sessions() -> dict:
    return _load_json(SESSIONS_FILE, {})


def _save_sessions(sessions: dict) -> None:
    _save_json(SESSIONS_FILE, sessions)


def _load_disputes() -> dict:
    return _load_json(DISPUTES_FILE, {"next_id": 1, "disputes": []})


def _save_disputes(data: dict) -> None:
    _save_json(DISPUTES_FILE, data)


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), 200_000
    ).hex()
    return digest, salt_hex


def _all_known_players() -> dict[str, str]:
    """uuid -> current name, merged from both servers' usercache files."""
    players: dict[str, str] = {}
    for path in USERCACHE_FILES:
        for entry in _load_json(path, []):
            players[entry["uuid"]] = entry["name"]
    return players


def get_all_known_players() -> dict[str, str]:
    """Public wrapper of _all_known_players(), for cross-module uuid->name lookups."""
    return _all_known_players()


def _find_account(accounts: dict, **kwargs) -> dict | None:
    for a in accounts["accounts"]:
        if all(a.get(k) == v for k, v in kwargs.items()):
            return a
    return None


def _purge_sessions_for_account(account_id: str) -> None:
    sessions = _load_sessions()
    remaining = {t: s for t, s in sessions.items() if s.get("account_id") != account_id}
    if len(remaining) != len(sessions):
        _save_sessions(remaining)


def _check_login_rate_limit(username: str) -> None:
    now = time.time()
    attempts = [t for t in _LOGIN_ATTEMPTS.get(username, []) if now - t < LOGIN_LOCKOUT_SECONDS]
    _LOGIN_ATTEMPTS[username] = attempts
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(429, "로그인 시도가 너무 많습니다. 15분 후 다시 시도해주세요")


def _record_failed_login(username: str) -> None:
    _LOGIN_ATTEMPTS.setdefault(username, []).append(time.time())


def _clear_login_attempts(username: str) -> None:
    _LOGIN_ATTEMPTS.pop(username, None)


def get_notif_seen_at(account_id: str) -> float:
    accounts = _load_accounts()
    account = _find_account(accounts, id=account_id)
    return account.get("notif_seen_at", 0) if account else 0


def set_notif_seen_at(account_id: str) -> None:
    accounts = _load_accounts()
    account = _find_account(accounts, id=account_id)
    if account:
        account["notif_seen_at"] = time.time()
        _save_accounts(accounts)


def _issue_session(account: dict) -> str:
    token = secrets.token_urlsafe(32)
    sessions = _load_sessions()
    sessions[token] = {
        "uuid": account.get("player_uuid"),
        "name": account.get("player_name") or account["username"],
        "account_id": account["id"],
        "expires_at": time.time() + SESSION_TTL_SECONDS,
    }
    _save_sessions(sessions)
    return token


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "session",
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        domain=COOKIE_DOMAIN,
    )


def get_session_player(session_token: str | None) -> dict | None:
    """Returns {"uuid":, "name":, "account_id":} for a valid session, else None.
    "uuid" may be None if the account's player claim was removed (dispute) and
    they haven't picked a new one yet."""
    if not session_token:
        return None
    sessions = _load_sessions()
    entry = sessions.get(session_token)
    if not entry:
        return None
    if time.time() > entry["expires_at"]:
        sessions.pop(session_token, None)
        _save_sessions(sessions)
        return None
    return {"uuid": entry["uuid"], "name": entry["name"], "account_id": entry["account_id"]}


def list_accounts_with_faction() -> list[dict]:
    """All claimed accounts with a chosen faction, for faction ranking/buff logic."""
    accounts = _load_accounts()
    return [
        {"id": a["id"], "uuid": a["player_uuid"], "name": a["player_name"], "faction": a["faction"]}
        for a in accounts["accounts"]
        if a.get("player_uuid") and a.get("faction") in FACTIONS
    ]


def list_claimed_players_with_optional_faction() -> list[dict]:
    """Every claimed account, faction included if set (else None) -- for the
    admin's faction management tool, which needs to also set a faction for
    players who haven't picked one yet."""
    accounts = _load_accounts()
    return [
        {
            "id": a["id"],
            "uuid": a["player_uuid"],
            "name": a["player_name"],
            "faction": a["faction"] if a.get("faction") in FACTIONS else None,
        }
        for a in accounts["accounts"]
        if a.get("player_uuid")
    ]


def list_claimed_players(exclude_uuid: str | None = None) -> list[dict]:
    """Every account that has claimed a Minecraft player, regardless of whether
    they're currently logged into the website (for the battle-challenge picker,
    where "available" means "actually online in-game right now", not "logged
    into the site")."""
    accounts = _load_accounts()
    result = []
    for a in accounts["accounts"]:
        if not a.get("player_uuid"):
            continue
        if exclude_uuid and a["player_uuid"] == exclude_uuid:
            continue
        result.append({"uuid": a["player_uuid"], "name": a["player_name"]})
    return result


@router.get("/players/roster")
def players_roster():
    accounts = _load_accounts()
    all_players = _all_known_players()
    claims = {a["player_uuid"]: a["username"] for a in accounts["accounts"] if a.get("player_uuid")}
    roster = [
        {
            "uuid": uuid,
            "name": name,
            "claimed": uuid in claims,
            "claimed_by": claims.get(uuid),
        }
        for uuid, name in all_players.items()
    ]
    roster.sort(key=lambda p: p["name"].lower())
    return {"players": roster}


@router.post("/auth/register")
def register(payload: dict, response: Response):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    player_uuid = payload.get("player_uuid")
    faction = payload.get("faction")

    if len(username) < 3:
        raise HTTPException(400, "아이디는 3자 이상이어야 합니다")
    if len(password) < 4:
        raise HTTPException(400, "비밀번호는 4자 이상이어야 합니다")
    if faction not in FACTIONS:
        raise HTTPException(400, "진영을 선택해주세요")

    accounts = _load_accounts()
    if _find_account(accounts, username=username):
        raise HTTPException(400, "이미 사용 중인 아이디입니다")

    all_players = _all_known_players()
    if player_uuid not in all_players:
        raise HTTPException(400, "존재하지 않는 플레이어입니다")
    if any(a.get("player_uuid") == player_uuid for a in accounts["accounts"]):
        raise HTTPException(400, "이미 다른 계정이 선택한 플레이어입니다. 본인 계정이 맞다면 이의제기를 이용해주세요")

    account = {
        "id": secrets.token_hex(8),
        "username": username,
        "player_uuid": player_uuid,
        "player_name": all_players[player_uuid],
        "faction": faction,
        "created_at": time.time(),
    }
    account["password_hash"], account["password_salt"] = _hash_password(password)
    accounts["accounts"].append(account)
    _save_accounts(accounts)

    token = _issue_session(account)
    _set_session_cookie(response, token)
    return {
        "uuid": account["player_uuid"],
        "name": account["player_name"],
        "is_admin": account["player_uuid"] == ADMIN_UUID,
        "faction": faction,
    }


@router.post("/auth/login")
def login(payload: dict, response: Response):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    _check_login_rate_limit(username)

    accounts = _load_accounts()
    account = _find_account(accounts, username=username)
    if not account:
        _record_failed_login(username)
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    digest, _ = _hash_password(password, account["password_salt"])
    if not secrets.compare_digest(digest, account["password_hash"]):
        _record_failed_login(username)
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")

    _clear_login_attempts(username)
    token = _issue_session(account)
    _set_session_cookie(response, token)
    return {
        "uuid": account.get("player_uuid"),
        "name": account.get("player_name") or account["username"],
        "is_admin": account.get("player_uuid") == ADMIN_UUID,
        "needs_player_selection": account.get("player_uuid") is None,
        "faction": account.get("faction"),
    }


@router.get("/auth/me")
def me(session: str | None = Cookie(default=None)):
    player = get_session_player(session)
    if not player:
        raise HTTPException(401, "Not logged in")
    accounts = _load_accounts()
    account = _find_account(accounts, id=player["account_id"])
    faction = account.get("faction") if account else None
    return {
        "uuid": player["uuid"],
        "name": player["name"],
        "is_admin": player["uuid"] == ADMIN_UUID,
        "needs_player_selection": player["uuid"] is None,
        "faction": faction,
        "needs_faction_selection": player["uuid"] is not None and faction not in FACTIONS,
    }


@router.post("/auth/logout")
def logout(response: Response, session: str | None = Cookie(default=None)):
    if session:
        sessions = _load_sessions()
        sessions.pop(session, None)
        _save_sessions(sessions)
    response.delete_cookie("session", domain=COOKIE_DOMAIN)
    return {"ok": True}


@router.post("/auth/claim-player")
def claim_player(payload: dict, session: str | None = Cookie(default=None)):
    """For accounts whose claim was removed by a dispute -- lets them pick a
    (still available) player again without re-registering."""
    player = get_session_player(session)
    if not player:
        raise HTTPException(401, "로그인이 필요합니다")

    player_uuid = payload.get("player_uuid")
    all_players = _all_known_players()
    if player_uuid not in all_players:
        raise HTTPException(400, "존재하지 않는 플레이어입니다")

    accounts = _load_accounts()
    if any(a.get("player_uuid") == player_uuid for a in accounts["accounts"]):
        raise HTTPException(400, "이미 다른 계정이 선택한 플레이어입니다")

    account = _find_account(accounts, id=player["account_id"])
    if not account:
        raise HTTPException(404, "계정을 찾을 수 없습니다")

    account["player_uuid"] = player_uuid
    account["player_name"] = all_players[player_uuid]
    _save_accounts(accounts)

    # Refresh this session (and drop any other stale sessions for the account).
    _purge_sessions_for_account(account["id"])
    token = _issue_session(account)
    response = Response()
    _set_session_cookie(response, token)
    return {
        "uuid": account["player_uuid"],
        "name": account["player_name"],
        "is_admin": account["player_uuid"] == ADMIN_UUID,
    }


@router.post("/auth/set-faction")
def set_faction(payload: dict, session: str | None = Cookie(default=None)):
    """For accounts created before the faction system existed -- lets them
    pick one once, without needing to re-register."""
    player = get_session_player(session)
    if not player:
        raise HTTPException(401, "로그인이 필요합니다")

    faction = payload.get("faction")
    if faction not in FACTIONS:
        raise HTTPException(400, "올바른 진영을 선택해주세요")

    accounts = _load_accounts()
    account = _find_account(accounts, id=player["account_id"])
    if not account:
        raise HTTPException(404, "계정을 찾을 수 없습니다")
    if account.get("faction") in FACTIONS:
        raise HTTPException(400, "이미 진영을 선택했습니다")

    account["faction"] = faction
    _save_accounts(accounts)
    return {"faction": faction}


@router.post("/disputes")
def file_dispute(payload: dict):
    """Anyone can flag a claimed player as wrongly claimed -- no login required,
    since being locked out of registering under your own name is exactly the
    scenario this exists for."""
    player_uuid = payload.get("player_uuid")
    note = (payload.get("note") or "").strip()[:500]

    accounts = _load_accounts()
    account = _find_account(accounts, player_uuid=player_uuid)
    if not account:
        raise HTTPException(400, "아무도 선택하지 않은 플레이어입니다")

    disputes = _load_disputes()
    for d in disputes["disputes"]:
        if d["status"] == "open" and d["player_uuid"] == player_uuid:
            raise HTTPException(400, "이미 접수된 이의제기가 있습니다")

    dispute = {
        "id": disputes["next_id"],
        "player_uuid": player_uuid,
        "player_name": account["player_name"],
        "claimed_by_account_id": account["id"],
        "claimed_by_username": account["username"],
        "note": note,
        "status": "open",
        "created_at": time.time(),
        "resolved_at": None,
    }
    disputes["next_id"] += 1
    disputes["disputes"].append(dispute)
    _save_disputes(disputes)
    return dispute


def _require_admin(session: str | None) -> dict:
    player = get_session_player(session)
    if not player:
        raise HTTPException(401, "로그인이 필요합니다")
    if player["uuid"] != ADMIN_UUID:
        raise HTTPException(403, "관리자만 접근할 수 있습니다")
    return player


@router.get("/admin/players-factions")
def admin_players_factions(session: str | None = Cookie(default=None)):
    """All claimed players, faction included if set (else null) -- for the
    admin's force-change-faction tool, which also handles players who
    haven't picked a faction yet."""
    _require_admin(session)
    players = list_claimed_players_with_optional_faction()
    players.sort(key=lambda p: p["name"].lower())
    return {"players": players}


@router.post("/admin/set-player-faction")
def admin_set_player_faction(payload: dict, session: str | None = Cookie(default=None)):
    """Force-overrides a player's faction, bypassing the normal one-time-only
    restriction. Admin-only."""
    _require_admin(session)
    player_uuid = payload.get("player_uuid")
    faction = payload.get("faction")
    if faction not in FACTIONS:
        raise HTTPException(400, "올바른 진영을 선택해주세요")

    accounts = _load_accounts()
    account = _find_account(accounts, player_uuid=player_uuid)
    if not account:
        raise HTTPException(404, "해당 플레이어를 선택한 계정이 없습니다")

    account["faction"] = faction
    _save_accounts(accounts)
    return {"uuid": player_uuid, "name": account["player_name"], "faction": faction}


@router.get("/admin/account-disputes")
def admin_account_disputes(session: str | None = Cookie(default=None)):
    _require_admin(session)
    disputes = _load_disputes()
    return {"disputes": [d for d in disputes["disputes"] if d["status"] == "open"]}


@router.post("/admin/account-disputes/resolve")
def admin_resolve_dispute(payload: dict, session: str | None = Cookie(default=None)):
    _require_admin(session)
    dispute_id = payload.get("dispute_id")
    action = payload.get("action")  # "remove_claim" or "dismiss"
    if action not in ("remove_claim", "dismiss"):
        raise HTTPException(400, "action은 'remove_claim' 또는 'dismiss'여야 합니다")

    disputes = _load_disputes()
    dispute = next((d for d in disputes["disputes"] if d["id"] == dispute_id), None)
    if not dispute:
        raise HTTPException(404, "존재하지 않는 이의제기입니다")
    if dispute["status"] != "open":
        raise HTTPException(400, "이미 처리된 이의제기입니다")

    if action == "remove_claim":
        accounts = _load_accounts()
        account = _find_account(accounts, id=dispute["claimed_by_account_id"])
        if account:
            account["player_uuid"] = None
            account["player_name"] = None
            _save_accounts(accounts)
            _purge_sessions_for_account(account["id"])

    dispute["status"] = "resolved"
    dispute["resolved_at"] = time.time()
    _save_disputes(disputes)
    return dispute


def _sanitize_reason(reason: str) -> str:
    """Strip control characters (newlines etc.) so a ban reason can't be
    used to smuggle extra lines into the RCON command string."""
    return "".join(ch for ch in reason if ch.isprintable()).strip()[:100]


@router.get("/admin/banned-players")
def admin_banned_players(session: str | None = Cookie(default=None)):
    """Every known player, flagged with their current ban entry (if any).
    Bans only apply to the live server -- see BANNED_PLAYERS_FILE."""
    _require_admin(session)
    banned = _load_json(BANNED_PLAYERS_FILE, [])
    banned_by_uuid = {b["uuid"]: b for b in banned if b.get("uuid")}

    all_players = _all_known_players()
    players = [
        {
            "uuid": uuid,
            "name": name,
            "banned": uuid in banned_by_uuid,
            "reason": banned_by_uuid.get(uuid, {}).get("reason"),
        }
        for uuid, name in all_players.items()
    ]
    players.sort(key=lambda p: p["name"].lower())
    return {"players": players}


@router.post("/admin/ban")
def admin_ban_player(payload: dict, session: str | None = Cookie(default=None)):
    _require_admin(session)
    player_uuid = payload.get("player_uuid")
    reason = _sanitize_reason(payload.get("reason") or "")

    all_players = _all_known_players()
    name = all_players.get(player_uuid)
    if not name:
        raise HTTPException(400, "존재하지 않는 플레이어입니다")
    if player_uuid == ADMIN_UUID:
        raise HTTPException(400, "관리자 계정은 밴할 수 없습니다")

    command = f"ban {name} {reason}".strip()
    try:
        rcon.rcon_command(command)
    except (ConnectionError, OSError, PermissionError) as e:
        raise HTTPException(502, f"서버에 밴 명령을 전달하지 못했습니다: {e}")

    return {"uuid": player_uuid, "name": name, "banned": True}


@router.post("/admin/unban")
def admin_unban_player(payload: dict, session: str | None = Cookie(default=None)):
    _require_admin(session)
    player_uuid = payload.get("player_uuid")

    all_players = _all_known_players()
    name = all_players.get(player_uuid)
    if not name:
        raise HTTPException(400, "존재하지 않는 플레이어입니다")

    try:
        rcon.rcon_command(f"pardon {name}")
    except (ConnectionError, OSError, PermissionError) as e:
        raise HTTPException(502, f"서버에 밴 해제 명령을 전달하지 못했습니다: {e}")

    return {"uuid": player_uuid, "name": name, "banned": False}
