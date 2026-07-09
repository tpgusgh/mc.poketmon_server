"""Player -> admin inquiries. Simple inbox, no reply mechanism -- the admin
reads it here and follows up in-game/elsewhere."""
import json
import time
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException

from auth import ADMIN_UUID, get_session_player

router = APIRouter()

INQUIRIES_FILE = Path(__file__).parent / "inquiries.json"


def _load() -> dict:
    if not INQUIRIES_FILE.exists():
        return {"next_id": 1, "inquiries": []}
    try:
        return json.loads(INQUIRIES_FILE.read_text())
    except json.JSONDecodeError:
        return {"next_id": 1, "inquiries": []}


def _save(data: dict) -> None:
    INQUIRIES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


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


@router.post("/contact")
def submit_inquiry(payload: dict, session: str | None = Cookie(default=None)):
    player = _require_player(session)
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "문의 내용을 입력해주세요")
    if len(message) > 2000:
        raise HTTPException(400, "문의 내용이 너무 깁니다 (2000자 이하)")

    data = _load()
    inquiry = {
        "id": data["next_id"],
        "player_uuid": player["uuid"],
        "player_name": player["name"],
        "message": message,
        "status": "open",
        "created_at": time.time(),
        "resolved_at": None,
    }
    data["next_id"] += 1
    data["inquiries"].append(inquiry)
    _save(data)
    return inquiry


@router.get("/admin/inquiries")
def list_inquiries(session: str | None = Cookie(default=None)):
    _require_admin(session)
    data = _load()
    return {"inquiries": sorted(data["inquiries"], key=lambda i: i["created_at"], reverse=True)}


@router.post("/admin/inquiries/resolve")
def resolve_inquiry(payload: dict, session: str | None = Cookie(default=None)):
    _require_admin(session)
    inquiry_id = payload.get("inquiry_id")

    data = _load()
    inquiry = next((i for i in data["inquiries"] if i["id"] == inquiry_id), None)
    if not inquiry:
        raise HTTPException(404, "존재하지 않는 문의입니다")

    inquiry["status"] = "resolved"
    inquiry["resolved_at"] = time.time()
    _save(data)
    return inquiry
