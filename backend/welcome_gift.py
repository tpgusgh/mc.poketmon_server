import json
from pathlib import Path

import auth
import rcon

WELCOMED_FILE = Path(__file__).parent / "welcomed_players.json"
GIFT_ITEM = "pixelmon:ultra_ball"
GIFT_COUNT = 10


def _load_welcomed() -> set[str]:
    if WELCOMED_FILE.exists():
        with open(WELCOMED_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    # First run: seed with everyone who has ever connected before this
    # feature existed, so existing players aren't retroactively gifted.
    seeded = set(auth.get_all_known_players().values())
    _save_welcomed(seeded)
    return seeded


def _save_welcomed(names: set[str]) -> None:
    with open(WELCOMED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(names), f, indent=2, ensure_ascii=False)
    WELCOMED_FILE.chmod(0o600)


def check_and_welcome(online_names: set[str]) -> None:
    """Gives first-time joiners a starter pack of Ultra Balls (하이퍼볼) via RCON."""
    welcomed = _load_welcomed()
    new_names = online_names - welcomed
    if not new_names:
        return
    for name in new_names:
        try:
            rcon.rcon_command(f"give {name} {GIFT_ITEM} {GIFT_COUNT}")
            rcon.tellraw(
                name,
                f"🎁 서버에 처음 오신 것을 환영합니다! 하이퍼볼 {GIFT_COUNT}개를 선물로 드렸어요.",
                color="gold",
                bold=True,
            )
        except Exception:
            continue
        welcomed.add(name)
    _save_welcomed(welcomed)
