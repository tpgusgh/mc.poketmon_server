"""Playerdata (Minecraft inventory) snapshots + admin restore.

`~/mcserver/backup_playerdata.sh` copies `world/playerdata/` into a
timestamped folder here every time minecraft.service (re)starts
(`ExecStartPre`), keeping the last 7. Since the server restarts nightly at
6am, this gives roughly a week of daily rollback points -- e.g. if someone
loses their inventory falling into the void, the admin can restore it from
the last restart's snapshot.

Restoring only touches the on-disk .dat file, so it's only safe to do while
that player is offline (otherwise the live server would just overwrite it
again whenever they next log out).
"""
import shutil
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException

import auth

router = APIRouter()

BACKUP_ROOT = Path("/home/hyunho/mcserver/playerdata_backups")
PLAYERDATA_DIR = Path("/home/hyunho/mcserver/world/playerdata")


def _require_admin(session: str | None) -> dict:
    player = auth.get_session_player(session)
    if not player:
        raise HTTPException(401, "로그인이 필요합니다")
    if player["uuid"] != auth.ADMIN_UUID:
        raise HTTPException(403, "관리자만 접근할 수 있습니다")
    return player


def _list_snapshots() -> list[str]:
    if not BACKUP_ROOT.exists():
        return []
    return sorted((p.name for p in BACKUP_ROOT.iterdir() if p.is_dir()), reverse=True)


@router.get("/admin/playerdata-backups")
def list_backups(session: str | None = Cookie(default=None)):
    _require_admin(session)
    return {"snapshots": _list_snapshots()}


@router.get("/admin/playerdata-backups/{snapshot}/players")
def list_backup_players(snapshot: str, session: str | None = Cookie(default=None)):
    _require_admin(session)
    snapshot_dir = BACKUP_ROOT / snapshot
    if not snapshot_dir.is_dir():
        raise HTTPException(404, "존재하지 않는 스냅샷입니다")

    names = auth.get_all_known_players()
    online_names = set()
    try:
        from main import get_online_player_names  # deferred: avoids a circular import at module load time

        online_names = get_online_player_names()
    except Exception:
        pass

    players = []
    for dat_file in snapshot_dir.glob("*.dat"):
        player_uuid = dat_file.stem
        player_name = names.get(player_uuid, player_uuid)
        players.append(
            {
                "uuid": player_uuid,
                "name": player_name,
                "online": player_name in online_names,
            }
        )
    players.sort(key=lambda p: p["name"].lower())
    return {"players": players}


@router.post("/admin/playerdata-backups/restore")
def restore_backup(payload: dict, session: str | None = Cookie(default=None)):
    _require_admin(session)
    snapshot = payload.get("snapshot")
    player_uuid = payload.get("player_uuid")
    if not snapshot or not player_uuid:
        raise HTTPException(400, "snapshot과 player_uuid가 필요합니다")

    src = BACKUP_ROOT / snapshot / f"{player_uuid}.dat"
    if not src.exists():
        raise HTTPException(404, "해당 스냅샷에 이 플레이어의 데이터가 없습니다")

    names = auth.get_all_known_players()
    player_name = names.get(player_uuid, player_uuid)
    try:
        from main import get_online_player_names

        if player_name in get_online_player_names():
            raise HTTPException(400, "이 플레이어가 지금 게임에 접속 중이라 복구할 수 없습니다. 접속 종료 후 다시 시도해주세요")
    except HTTPException:
        raise
    except Exception:
        pass

    dest = PLAYERDATA_DIR / f"{player_uuid}.dat"
    shutil.copy2(src, dest)
    return {"ok": True}
