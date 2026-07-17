"""Reads the plain "timestamp|player|npc" log the factionbuff mod appends to
every time a player beats an NPC trainer (see NPCEvent.EndBattle in
FactionBuffMod.java) and serves it as a Champion Hall of Fame leaderboard."""
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

WINS_FILE = Path("/home/hyunho/player-status-api/npc_trainer_wins.log")


def _read_wins() -> list[dict]:
    if not WINS_FILE.exists():
        return []
    wins = []
    with open(WINS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            ts, player, npc = parts
            wins.append({"timestamp": ts, "player": player, "npc": npc})
    return wins


@router.get("/champion-wins")
def champion_wins():
    wins = _read_wins()
    wins.sort(key=lambda w: w["timestamp"], reverse=True)

    counts: dict[str, int] = {}
    for w in wins:
        counts[w["player"]] = counts.get(w["player"], 0) + 1
    leaderboard = [{"name": name, "wins": count} for name, count in counts.items()]
    leaderboard.sort(key=lambda r: r["wins"], reverse=True)

    return {"recent": wins[:50], "leaderboard": leaderboard}
