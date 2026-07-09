"""Valor/Mystic/Instinct-style faction leaderboard.

Each account picks a faction at registration. A faction's rank is the
average battle ranking score across its members (unranked members count as
the starting score, so a faction isn't penalized just for having newer
players). The #1 faction gets a real, exact 1.5x battle-EXP multiplier and
#2 gets 1.2x, in-game -- not a held-item workaround -- via a small companion
Forge mod (`~/mcserver/mods/factionbuff-1.0.0.jar`) that hooks Pixelmon's
ExperienceGainEvent directly. This module's only link to that mod is the
plain text file it writes out (`name:multiplier` per line); the mod just
reads it.
"""
from pathlib import Path

from fastapi import APIRouter

import auth
import battles

router = APIRouter()

BOOSTED_PLAYERS_FILE = Path("/home/hyunho/player-status-api/faction_boosted_players.txt")
PLAYER_FACTIONS_FILE = Path("/home/hyunho/player-status-api/player_factions.txt")

# rank index (0 = 1st place) -> EXP multiplier for that faction's members
TIER_MULTIPLIERS = {0: 1.5, 1: 1.2}


def get_faction_ranking() -> list[dict]:
    members = auth.list_accounts_with_faction()
    scores = battles.get_ranking_scores()

    by_faction: dict[str, list[dict]] = {f: [] for f in auth.FACTIONS}
    for m in members:
        score = scores.get(m["uuid"], {}).get("score", battles.STARTING_SCORE)
        by_faction[m["faction"]].append({"uuid": m["uuid"], "name": m["name"], "score": score})

    rows = []
    for faction in auth.FACTIONS:
        roster = by_faction[faction]
        avg = sum(m["score"] for m in roster) / len(roster) if roster else battles.STARTING_SCORE
        info = auth.FACTION_INFO[faction]
        rows.append(
            {
                "faction": faction,
                "name": info["name"],
                "color": info["color"],
                "member_count": len(roster),
                "avg_score": round(avg, 1),
            }
        )
    rows.sort(key=lambda r: r["avg_score"], reverse=True)
    return rows


def _write_boosted_players(boosted: list[dict]) -> None:
    """boosted: [{"faction":, "multiplier":}, ...]"""
    faction_multiplier = {b["faction"]: b["multiplier"] for b in boosted}
    members = auth.list_accounts_with_faction()
    lines = [
        f"{m['name']}:{faction_multiplier[m['faction']]}"
        for m in members
        if m["faction"] in faction_multiplier
    ]
    BOOSTED_PLAYERS_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))


def _write_player_factions() -> None:
    """name:faction per line, for the mod's chat coloring (every player with
    a chosen faction, not just the boosted ones)."""
    members = auth.list_accounts_with_faction()
    lines = [f"{m['name']}:{m['faction']}" for m in members]
    PLAYER_FACTIONS_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))


def get_faction_ranking_and_sync() -> tuple[list[dict], list[dict]]:
    """Computes the ranking and (re)writes the boosted-players + player-faction
    files the Forge mod reads -- called on every /factions/ranking request so
    the in-game buff/chat colors always match current data, no restart needed."""
    ranking = get_faction_ranking()
    boosted = [
        {"faction": ranking[rank]["faction"], "multiplier": multiplier}
        for rank, multiplier in sorted(TIER_MULTIPLIERS.items())
        if rank < len(ranking)
    ]
    _write_boosted_players(boosted)
    _write_player_factions()
    return ranking, boosted


@router.get("/factions/ranking")
def factions_ranking():
    ranking, boosted = get_faction_ranking_and_sync()
    return {"ranking": ranking, "boosted": boosted}


@router.get("/factions/info")
def factions_info():
    return {
        "factions": [
            {"faction": f, "name": auth.FACTION_INFO[f]["name"], "color": auth.FACTION_INFO[f]["color"]}
            for f in auth.FACTIONS
        ]
    }
