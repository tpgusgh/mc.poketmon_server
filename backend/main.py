import json
import os
import random
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import nbtlib
from fastapi import Cookie, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import auth
import backups
import battles
import contact
import factions
import rcon
import welcome_gift

app = FastAPI(title="Pixelmon Server1 Player Status")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://hi.mieung.kr"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(auth.router)
app.include_router(battles.router)
app.include_router(factions.router)
app.include_router(contact.router)
app.include_router(backups.router)

JOIN_RE = re.compile(r": (\w[\w]*) joined the game$")
LEFT_RE = re.compile(r": (\w[\w]*) left the game$")
LOST_RE = re.compile(r": (\w[\w]*) lost connection")
RESTART_RE = re.compile(r"Starting minecraft server version")

TS_RE = re.compile(r"^(\S+)\s")

# The 1.16.5 world started at this point; ignore anything before it (old 1.20.1 era).
WORLD_EPOCH = datetime.fromisoformat("2026-07-04T18:03:00+09:00")

PLAYTIME_STATE_FILE = Path(__file__).parent / "playtime_state.json"

WORLD_DIR = Path("/home/hyunho/mcserver/world")
POKEMON_DIR = WORLD_DIR / "data" / "pokemon"
USERCACHE_FILE = Path("/home/hyunho/mcserver/usercache.json")

# Full National Dex Korean name table (1025 species), fetched from PokeAPI's
# GraphQL endpoint (language_id=3 = Korean) and cached to disk. This is the
# authoritative source — hand-typed names were found to be ~11% wrong.
POKEMON_NAMES_FILE = Path(__file__).parent / "pokemon_names_ko.json"
with open(POKEMON_NAMES_FILE, encoding="utf-8") as f:
    POKEMON_NAMES_KO: dict[int, str] = {int(k): v for k, v in json.load(f).items()}

# National Dex numbers of legendary / mythical Pokemon (Gen 1-9). Only the
# numbers matter here; display names come from POKEMON_NAMES_KO above.
LEGENDARY_DEX_NUMBERS = {
    144, 145, 146, 150, 151,
    243, 244, 245, 249, 250, 251,
    377, 378, 379, 380, 381,
    382, 383, 384, 385, 386,
    480, 481, 482, 483, 484,
    485, 486, 487, 488, 489,
    490, 491, 492, 493, 494,
    638, 639, 640, 641, 642,
    643, 644, 645, 646, 647,
    648, 649, 716, 717, 718,
    719, 720, 721, 772, 773,
    785, 786, 787, 788,
    789, 790, 791, 792, 800,
    801, 802, 807, 808, 809,
    888, 889, 890, 891, 892,
    893, 894, 895, 896, 897,
    898, 905,  # 905 = Enamorus, added after the original hand-typed list
}

BALL_NAMES_KO = {
    "poke_ball": "몬스터볼", "great_ball": "슈퍼볼", "ultra_ball": "하이퍼볼",
    "master_ball": "마스터볼", "premier_ball": "프리미어볼", "repeat_ball": "리피트볼",
    "timer_ball": "타이머볼", "nest_ball": "네스트볼", "net_ball": "네트볼",
    "dive_ball": "다이브볼", "dusk_ball": "다크볼", "quick_ball": "퀵볼",
    "heal_ball": "힐볼", "luxury_ball": "럭셔리볼", "love_ball": "러브볼",
    "friend_ball": "프렌드볼", "moon_ball": "문볼", "level_ball": "레벨볼",
    "lure_ball": "루어볼", "fast_ball": "스피드볼", "heavy_ball": "헤비볼",
    "dream_ball": "드림볼", "beast_ball": "비스트볼", "safari_ball": "사파리볼",
    "sport_ball": "코치볼", "cherish_ball": "프레셔스볼", "park_ball": "파크볼",
}


def _parse_line(line: str):
    m = TS_RE.match(line)
    if not m:
        return None
    try:
        ts = datetime.fromisoformat(m.group(1))
    except ValueError:
        return None
    return ts, line


# Full unbounded journal scans (used by /players, /story, /fun-stats) get slower every
# day as the log grows, and the frontend polls several of them every 15s. Cache the
# unbounded result briefly so a poll round (or several concurrent visitors) triggers at
# most one subprocess call instead of one per endpoint.
_JOURNAL_CACHE: dict = {"ts": 0.0, "lines": []}
_JOURNAL_CACHE_TTL = 12  # seconds


def _fetch_journal_lines(since: datetime | None = None) -> list[str]:
    cmd = ["journalctl", "-u", "minecraft.service", "--no-pager", "-o", "short-iso"]
    if since is not None:
        cmd += ["--since", since.strftime("%Y-%m-%d %H:%M:%S")]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.splitlines()

    now = time.monotonic()
    if now - _JOURNAL_CACHE["ts"] < _JOURNAL_CACHE_TTL:
        return _JOURNAL_CACHE["lines"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    lines = result.stdout.splitlines()
    _JOURNAL_CACHE["ts"] = now
    _JOURNAL_CACHE["lines"] = lines
    return lines


RECONNECT_GRACE_SECONDS = 600


def get_player_status():
    lines = _fetch_journal_lines()

    state: dict[str, dict] = {}

    for raw in lines:
        parsed = _parse_line(raw)
        if not parsed:
            continue
        ts, line = parsed
        if ts < WORLD_EPOCH:
            continue

        if RESTART_RE.search(line):
            for name, info in state.items():
                if info["online"]:
                    info["online"] = False
                    info["last_seen"] = ts
            continue

        m = JOIN_RE.search(line)
        if m:
            name = m.group(1)
            state.setdefault(name, {"online": False, "since": None, "last_seen": None})
            info = state[name]
            # A quick reconnect (server restart, brief network blip) within
            # the grace window continues the same displayed session instead
            # of resetting "connected since" back to right now.
            is_quick_reconnect = (
                info["last_seen"] is not None
                and info["since"] is not None
                and (ts - info["last_seen"]).total_seconds() <= RECONNECT_GRACE_SECONDS
            )
            info["online"] = True
            if not is_quick_reconnect:
                info["since"] = ts
            continue

        m = LEFT_RE.search(line) or LOST_RE.search(line)
        if m:
            name = m.group(1)
            state.setdefault(name, {"online": False, "since": None, "last_seen": None})
            if state[name]["online"]:
                state[name]["online"] = False
                state[name]["last_seen"] = ts
            continue

    now = datetime.now(timezone.utc)
    players = []
    for name, info in sorted(state.items()):
        if info["online"] and info["since"]:
            delta = now - info["since"]
            hours = round(delta.total_seconds() / 3600, 1)
            players.append(
                {
                    "name": name,
                    "status": "online",
                    "since": info["since"].isoformat(),
                    "hours_connected": hours,
                }
            )
        else:
            last_seen = info["last_seen"].isoformat() if info["last_seen"] else None
            hours_ago = (
                round((now - info["last_seen"]).total_seconds() / 3600, 1)
                if info["last_seen"]
                else None
            )
            players.append(
                {
                    "name": name,
                    "status": "offline",
                    "last_seen": last_seen,
                    "hours_since_last_seen": hours_ago,
                }
            )
    return players


def get_online_player_names() -> set[str]:
    return {p["name"] for p in get_player_status() if p["status"] == "online"}


def get_server_active() -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "minecraft.service"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() == "active"


def _status_for_ratio(ratio: float) -> str:
    if ratio >= 0.9:
        return "critical"
    if ratio >= 0.7:
        return "warning"
    return "good"


def get_server_health() -> dict:
    cores = os.cpu_count() or 1
    load1, load5, load15 = os.getloadavg()
    cpu_ratio = load1 / cores

    mem_total = mem_available = None
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                mem_available = int(line.split()[1]) * 1024
    mem_used = mem_total - mem_available
    mem_ratio = mem_used / mem_total

    mc_mem_bytes = None
    try:
        result = subprocess.run(
            ["systemctl", "show", "minecraft.service", "-p", "MemoryCurrent", "--value"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw = result.stdout.strip()
        if raw.isdigit():
            mc_mem_bytes = int(raw)
    except Exception:
        pass

    return {
        "cpu": {
            "cores": cores,
            "load1": round(load1, 2),
            "load5": round(load5, 2),
            "load15": round(load15, 2),
            "ratio": round(cpu_ratio, 3),
            "status": _status_for_ratio(cpu_ratio),
        },
        "memory": {
            "used_gb": round(mem_used / 1024**3, 2),
            "total_gb": round(mem_total / 1024**3, 2),
            "ratio": round(mem_ratio, 3),
            "status": _status_for_ratio(mem_ratio),
        },
        "minecraft_memory_gb": round(mc_mem_bytes / 1024**3, 2) if mc_mem_bytes else None,
    }


# ---------------------------------------------------------------------------
# Legendary Pokemon roster (parsed directly from Pixelmon's .pk/.comp NBT files)
# ---------------------------------------------------------------------------


USERCACHE_FILES = [
    USERCACHE_FILE,
    Path("/home/hyunho/mcserver2/usercache.json"),
]
NAME_CACHE_FILE = Path(__file__).parent / "name_cache.json"


def _load_usercache() -> dict[str, str]:
    names: dict[str, str] = {}
    for path in USERCACHE_FILES:
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            continue
        for entry in entries:
            names.setdefault(entry["uuid"], entry["name"])

    if NAME_CACHE_FILE.exists():
        try:
            with open(NAME_CACHE_FILE, encoding="utf-8") as f:
                names.update({**json.load(f), **names})
        except Exception:
            pass

    return names


def _resolve_unknown_names(uuids: set[str], known: dict[str, str]) -> dict[str, str]:
    """Falls back to the Mojang API for UUIDs not found in either usercache,
    and persists the result so we don't re-query on every request."""
    missing = [u for u in uuids if u not in known]
    if not missing:
        return known

    cache = {}
    if NAME_CACHE_FILE.exists():
        try:
            with open(NAME_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    updated = False
    for uuid in missing:
        if uuid in cache:
            continue
        try:
            resp = subprocess.run(
                ["curl", "-s", "--max-time", "5", f"https://api.mojang.com/user/profile/{uuid.replace('-', '')}"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            data = json.loads(resp.stdout)
            cache[uuid] = data.get("name", uuid)
        except Exception:
            cache[uuid] = uuid
        updated = True

    if updated:
        with open(NAME_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)

    known = dict(known)
    known.update(cache)
    return known


def _ball_display(ball_id) -> str:
    if not ball_id:
        return "알 수 없는 볼"
    key = str(ball_id).lower()
    if key in BALL_NAMES_KO:
        return BALL_NAMES_KO[key]
    return str(ball_id).replace("_", " ").title()


def _pokemon_uuid_str(slot) -> str | None:
    tag = slot.get("UUID")
    if tag is None:
        return None
    try:
        return "-".join(str(int(x)) for x in tag)
    except TypeError:
        return str(tag)


def _species_display(ndex: int) -> str:
    return POKEMON_NAMES_KO.get(ndex, f"포켓몬 #{ndex}")


def _extract_pokemon_from_slot(slot, location: str) -> dict | None:
    try:
        ndex = int(slot.get("ndex"))
    except (TypeError, ValueError):
        return None
    return {
        "uuid": _pokemon_uuid_str(slot),
        "ndex": ndex,
        "species": _species_display(ndex),
        "is_legendary": ndex in LEGENDARY_DEX_NUMBERS,
        "ball": _ball_display(slot.get("CaughtBall")),
        "level": int(slot.get("Level", 0)),
        "location": location,
    }


def _iter_all_players_pokemon():
    """Yields (player_name, pokemon_dict) for every Pokemon currently owned by
    any known player, scanning both party (.pk) and PC boxes (.comp)."""
    if not POKEMON_DIR.exists():
        return

    names = _load_usercache()
    pk_uuids = {p.stem for p in POKEMON_DIR.glob("*.pk")}
    names = _resolve_unknown_names(pk_uuids, names)

    for pk_file in sorted(POKEMON_DIR.glob("*.pk")):
        player_uuid = pk_file.stem
        player_name = names.get(player_uuid, player_uuid)
        if player_name == player_uuid:
            continue  # couldn't resolve a nickname, skip this player entirely

        try:
            party_nbt = nbtlib.File.load(pk_file, gzipped=False)
        except Exception:
            continue

        for i in range(6):
            slot = party_nbt.get(f"party{i}")
            if slot is None:
                continue
            found = _extract_pokemon_from_slot(slot, "party")
            if found:
                yield player_name, found

        comp_file = POKEMON_DIR / f"{player_uuid}.comp"
        if comp_file.exists():
            try:
                comp_nbt = nbtlib.File.load(comp_file, gzipped=False)
            except Exception:
                comp_nbt = None
            if comp_nbt is not None:
                for box_key in comp_nbt.keys():
                    if not box_key.startswith("BoxNumber"):
                        continue
                    box = comp_nbt[box_key]
                    for slot_key in box.keys():
                        if not slot_key.startswith("pc"):
                            continue
                        found = _extract_pokemon_from_slot(box[slot_key], "pc")
                        if found:
                            yield player_name, found


def get_legendaries():
    by_player: dict[str, list] = {}
    for player_name, mon in _iter_all_players_pokemon():
        if not mon["is_legendary"]:
            continue
        by_player.setdefault(player_name, []).append(mon)
    return [{"name": name, "legendaries": mons} for name, mons in by_player.items()]


def get_party_status():
    """Returns each player's current active party (6 slots), with species,
    level and HP — not the PC boxes, just what they're carrying around."""
    names = _load_usercache()
    if not POKEMON_DIR.exists():
        return []

    pk_uuids = {p.stem for p in POKEMON_DIR.glob("*.pk")}
    names = _resolve_unknown_names(pk_uuids, names)
    faction_map = {a["uuid"]: a["faction"] for a in auth.list_accounts_with_faction()}

    result = []
    for pk_file in sorted(POKEMON_DIR.glob("*.pk")):
        player_uuid = pk_file.stem
        player_name = names.get(player_uuid, player_uuid)
        if player_name == player_uuid:
            continue  # couldn't resolve a nickname, skip this player entirely

        try:
            party_nbt = nbtlib.File.load(pk_file, gzipped=False)
        except Exception:
            continue

        party = []
        for i in range(6):
            slot = party_nbt.get(f"party{i}")
            if slot is None:
                continue
            try:
                ndex = int(slot.get("ndex"))
            except (TypeError, ValueError):
                continue
            hp = int(slot.get("Health", 0))
            max_hp = int(slot.get("StatsHP", 0))
            party.append(
                {
                    "species": _species_display(ndex),
                    "level": int(slot.get("Level", 0)),
                    "hp": hp,
                    "max_hp": max_hp,
                    "fainted": hp <= 0,
                }
            )

        if party:
            faction = faction_map.get(player_uuid)
            faction_info = auth.FACTION_INFO.get(faction)
            result.append(
                {
                    "name": player_name,
                    "party": party,
                    "faction": faction,
                    "faction_name": faction_info["name"] if faction_info else None,
                    "faction_color": faction_info["color"] if faction_info else None,
                }
            )

    return result


# ---------------------------------------------------------------------------
# Legendary catch / trade events, detected by diffing pokemon ownership
# between polls (persisted so events survive across requests and restarts)
# ---------------------------------------------------------------------------

POKEMON_EVENTS_STATE_FILE = Path(__file__).parent / "pokemon_events_state.json"

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _looks_like_uuid(name: str) -> bool:
    return bool(UUID_RE.match(name or ""))


def _load_pokemon_events_state() -> dict:
    if POKEMON_EVENTS_STATE_FILE.exists():
        with open(POKEMON_EVENTS_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"bootstrapped": False, "owners": {}, "events": []}


def _save_pokemon_events_state(state: dict):
    with open(POKEMON_EVENTS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def update_legendary_events() -> tuple[list, datetime | None]:
    """Compares the current legendary ownership snapshot against the last known
    one. New pokemon UUIDs are 'catches'; UUIDs that moved to a different
    player are 'trades'. Returns the full persisted event list (newest last)."""
    state = _load_pokemon_events_state()
    if state.get("bootstrapped") and not state.get("bootstrap_time"):
        # Migrating a state file saved before bootstrap_time was tracked.
        state["bootstrap_time"] = datetime.now(WORLD_EPOCH.tzinfo).isoformat()
        _save_pokemon_events_state(state)
    previous_owners: dict[str, dict] = state["owners"]
    current_owners: dict[str, dict] = {}

    # Track ALL pokemon (needed to detect trades of non-legendaries too), but
    # we'll only ever emit "catch" events for legendaries further down.
    for player_name, mon in _iter_all_players_pokemon():
        if not mon.get("uuid"):
            continue
        current_owners[mon["uuid"]] = {
            "owner": player_name,
            "species": mon["species"],
            "ball": mon["ball"],
            "level": mon["level"],
            "is_legendary": mon["is_legendary"],
        }

    now_iso = datetime.now(WORLD_EPOCH.tzinfo).isoformat()

    if not state.get("bootstrapped"):
        # First run ever: just record the baseline, no history to compare against.
        # (Avoids attributing every pre-existing legendary a "caught just now" event.)
        state["owners"] = current_owners
        state["bootstrapped"] = True
        state["bootstrap_time"] = now_iso
        _save_pokemon_events_state(state)
        return state["events"], datetime.fromisoformat(now_iso)

    events = state["events"]
    for pk_uuid, info in current_owners.items():
        prev = previous_owners.get(pk_uuid)
        if prev is None:
            if not info["is_legendary"]:
                continue  # don't spam the story with every common catch
            if _looks_like_uuid(info["owner"]):
                continue  # unresolved nickname — skip rather than show a raw UUID
            events.append(
                {
                    "type": "catch",
                    "timestamp": now_iso,
                    "player": info["owner"],
                    "species": info["species"],
                    "ball": info["ball"],
                    "level": info["level"],
                }
            )
        elif prev["owner"] != info["owner"]:
            if _looks_like_uuid(prev["owner"]) or _looks_like_uuid(info["owner"]):
                continue  # unresolved nickname on either side — skip
            events.append(
                {
                    "type": "trade",
                    "timestamp": now_iso,
                    "from": prev["owner"],
                    "to": info["owner"],
                    "species": info["species"],
                    "ball": info["ball"],
                    "level": info["level"],
                }
            )

    state["owners"] = current_owners
    state["events"] = events
    _save_pokemon_events_state(state)
    bootstrap_time = (
        datetime.fromisoformat(state["bootstrap_time"]) if state.get("bootstrap_time") else None
    )
    return events, bootstrap_time


# ---------------------------------------------------------------------------
# Accumulated playtime tracking (persistent across journal log rotation)
# ---------------------------------------------------------------------------


def _load_playtime_state() -> dict:
    if PLAYTIME_STATE_FILE.exists():
        with open(PLAYTIME_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "last_processed": WORLD_EPOCH.isoformat(),
        "totals_seconds": {},
        "open_sessions": {},
    }


def _save_playtime_state(state: dict):
    with open(PLAYTIME_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def update_playtime() -> dict:
    """Incrementally scan new journal lines since the last run and accumulate
    total connected seconds per player into a persistent JSON file, so totals
    survive systemd journal rotation."""
    state = _load_playtime_state()
    last_processed = datetime.fromisoformat(state["last_processed"])
    open_sessions = {
        name: datetime.fromisoformat(ts) for name, ts in state["open_sessions"].items()
    }
    totals = dict(state["totals_seconds"])

    lines = _fetch_journal_lines(since=last_processed)
    newest_ts = last_processed

    for raw in lines:
        parsed = _parse_line(raw)
        if not parsed:
            continue
        ts, line = parsed
        if ts < WORLD_EPOCH or ts <= last_processed:
            continue
        newest_ts = max(newest_ts, ts)

        if RESTART_RE.search(line):
            for name, since in list(open_sessions.items()):
                totals[name] = totals.get(name, 0) + (ts - since).total_seconds()
                del open_sessions[name]
            continue

        m = JOIN_RE.search(line)
        if m:
            name = m.group(1)
            open_sessions[name] = ts
            continue

        m = LEFT_RE.search(line) or LOST_RE.search(line)
        if m:
            name = m.group(1)
            if name in open_sessions:
                totals[name] = totals.get(name, 0) + (ts - open_sessions[name]).total_seconds()
                del open_sessions[name]
            continue

    state["last_processed"] = newest_ts.isoformat()
    state["totals_seconds"] = totals
    state["open_sessions"] = {name: ts.isoformat() for name, ts in open_sessions.items()}
    _save_playtime_state(state)
    return state


def get_leaderboard():
    state = update_playtime()
    now = datetime.now(timezone.utc)
    totals = dict(state["totals_seconds"])
    open_sessions = {
        name: datetime.fromisoformat(ts) for name, ts in state["open_sessions"].items()
    }

    # Add in-progress session time so the leaderboard reflects "right now".
    live_totals = dict(totals)
    for name, since in open_sessions.items():
        live_totals[name] = live_totals.get(name, 0) + (now - since).total_seconds()

    board = [
        {
            "name": name,
            "total_hours": round(seconds / 3600, 1),
            "online": name in open_sessions,
        }
        for name, seconds in live_totals.items()
    ]
    board.sort(key=lambda p: p["total_hours"], reverse=True)
    return board


# ---------------------------------------------------------------------------
# Fun / gag dashboards: deaths, falls, disconnects, achievement counts.
# All scan the full journal once and count occurrences per player.
# ---------------------------------------------------------------------------

DEATH_RE = re.compile(
    r": (\w[\w]*) (was slain by .+|drowned|blew up|hit the ground too hard|"
    r"tried to swim in lava.*|walked into a cactus.*|burned to death|"
    r"starved to death|was shot by .+|was frozen to death.*|"
    r"discovered the floor was lava|suffocated in a wall|"
    r"was squashed by a falling anvil|was impaled on a stalagmite|"
    r"was killed .+|didn.t want to live in the same world as .+|"
    r"experienced kinetic energy.*|fell out of the world|"
    r"went up in flames|was struck by lightning|withered away.*|"
    r"was doomed to fall.*|was pricked to death|died.*)$"
)
FELL_ANY_RE = re.compile(r": (\w[\w]*) fell from a high place$")
ADVANCEMENT_COUNT_RE = re.compile(r": (\w[\w]*) has made the advancement \[")


def _count_per_player(pattern: re.Pattern) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw in _fetch_journal_lines():
        parsed = _parse_line(raw)
        if not parsed:
            continue
        ts, line = parsed
        if ts < WORLD_EPOCH:
            continue
        m = pattern.search(line)
        if m:
            name = m.group(1)
            counts[name] = counts.get(name, 0) + 1
    return counts


def get_fun_dashboards():
    death_counts = _count_per_player(DEATH_RE)
    fall_counts = _count_per_player(FELL_ANY_RE)
    for name, count in fall_counts.items():
        death_counts[name] = death_counts.get(name, 0) + count
    achievements = _count_per_player(ADVANCEMENT_COUNT_RE)

    legendary_counts: dict[str, int] = {}
    for entry in get_legendaries():
        legendary_counts[entry["name"]] = len(entry["legendaries"])

    def _board(counts: dict[str, int], label: str):
        rows = [{"name": name, "value": count} for name, count in counts.items()]
        rows.sort(key=lambda r: r["value"], reverse=True)
        return {"label": label, "rows": rows}

    return {
        "deaths": _board(death_counts, "바보같은 죽음(낙사 포함)"),
        "achievements": _board(achievements, "업적 달성 개수"),
        "legendary_count": _board(legendary_counts, "전설 포켓몬 보유 수"),
    }


# ---------------------------------------------------------------------------
# Story: turns the raw log into a readable day-by-day narrative
# ---------------------------------------------------------------------------

ADVANCEMENT_RE = re.compile(r": (\w[\w]*) has made the advancement \[(.+)\]$")
FELL_RE = re.compile(r": (\w[\w]*) fell from a high place$")

LEGEND_RE = re.compile(r"legend", re.I)

ADVANCEMENT_TEMPLATES = [
    (re.compile(r"starter", re.I), "🌅 드디어! {name}의 모험이 막을 올렸다 — 떨리는 손으로 첫 스타터 포켓몬을 선택했다"),
    (LEGEND_RE, "⚡ 믿을 수 없는 순간! {name}가 전설의 포켓몬을 포획하는 데 성공했다!!"),
    (re.compile(r"different color", re.I), "✨ 행운의 여신이 미소지었다 — {name}가 반짝이는 샤이니 포켓몬을 낚아챘다!"),
    (re.compile(r"pretty in pink", re.I), "💗 눈앞에 나타난 핑크빛 포켓몬, {name}는 놓치지 않았다"),
    (re.compile(r"diamond", re.I), "💎 곡괭이질 끝에 반짝이는 보석이! {name}가 마침내 다이아몬드를 캐냈다"),
    (re.compile(r"four tries|fist pump", re.I), "😤 몇 번의 실패에도 포기란 없었다 — {name}가 기어이 두 번째 포켓몬을 손에 넣었다"),
    (re.compile(r"sweet dreams", re.I), "🛏️ 길고 긴 하루의 끝, {name}가 아늑한 잠자리를 마련했다"),
    (re.compile(r"stone age", re.I), "🪨 {name}가 돌 도구를 손에 쥐며 문명의 첫 발을 내디뎠다"),
    (re.compile(r"hot stuff", re.I), "🔥 뜨거운 열기가 감도는 그곳 — {name}가 네더의 불길 속으로 첫 발을 들였다"),
    (re.compile(r"final frontier", re.I), "🌌 우주의 끝자락, 엔드 차원! {name}가 마침내 그곳에 도달했다"),
    (re.compile(r"iron pick|acquire hardware", re.I), "⛏️ {name}가 반짝이는 철 장비로 완전 무장을 마쳤다"),
    (re.compile(r"round one knock out", re.I), "🥊 압도적인 실력! {name}가 첫 배틀에서 상대를 단숨에 쓰러뜨렸다"),
    (re.compile(r"mystery", re.I), "❓ {name}의 눈앞에 정체를 알 수 없는 신비로운 존재가 나타났다..."),
    (re.compile(r"grindstone", re.I), "📈 {name}의 성장은 멈추지 않는다 — 꾸준함이 실력이 되고 있다"),
]


def _classify_advancement(name: str) -> str:
    for pattern, template in ADVANCEMENT_TEMPLATES:
        if pattern.search(name):
            return template
    return "🏆 {name}가 값진 업적 '" + name + "'을(를) 달성하며 이름을 알렸다!"


QUIET_HEADLINES = ["조용했던 하루", "평온하게 지나간 하루", "별일 없이 흘러간 하루"]
STEADY_HEADLINES = ["잔잔하지만 알찼던 하루", "소소한 이야기가 있었던 하루", "무난하게 흘러간 하루"]
BUSY_HEADLINES = ["다사다난했던 하루!", "정신없이 바빴던 하루!", "이런저런 일이 많았던 하루!", "쉴 틈 없던 하루!"]
WILD_HEADLINES = ["전설이 쓰여진 날!!", "역사에 남을 하루!!", "다들 미쳐 날뛴 하루!!", "서버가 들썩인 하루!!"]


def _headline(day_key: str, events: list[str]) -> str:
    count = len(events)
    if count <= 2:
        pool = list(QUIET_HEADLINES)
    elif count <= 6:
        pool = list(STEADY_HEADLINES)
    elif count <= 12:
        pool = list(BUSY_HEADLINES)
    else:
        pool = list(WILD_HEADLINES)

    if any("포획하는 데 성공했다" in e for e in events):
        pool.append("전설과 함께한 하루")
    if any("배틀 승부!" in e for e in events):
        pool.append("배틀의 열기가 뜨거웠던 하루")
    if any("거래 성사!" in e for e in events):
        pool.append("활발한 거래가 오간 하루")
    if any("처음으로 이 세계에 발을 들였다" in e for e in events):
        pool.append("새로운 얼굴이 등장한 하루")

    return random.Random(day_key).choice(pool)


def get_story():
    lines = _fetch_journal_lines()
    seen_players: set[str] = set()
    fell_counts: dict[tuple, int] = {}
    timeline: list[tuple[datetime, str]] = []

    legendary_events, legendary_bootstrap_time = update_legendary_events()

    for raw in lines:
        parsed = _parse_line(raw)
        if not parsed:
            continue
        ts, line = parsed
        if ts < WORLD_EPOCH:
            continue

        time_prefix = f"[{ts.strftime('%H:%M')}] "
        day_key = ts.strftime("%Y-%m-%d")

        m = JOIN_RE.search(line)
        if m:
            name = m.group(1)
            if name not in seen_players:
                seen_players.add(name)
                timeline.append((ts, f"{time_prefix}🚪 새로운 도전자 등장! **{name}**가(이) 처음으로 이 세계에 발을 들였다"))
            continue

        m = ADVANCEMENT_RE.search(line)
        if m:
            name, advancement = m.group(1), m.group(2)
            if LEGEND_RE.search(advancement) and legendary_bootstrap_time and ts >= legendary_bootstrap_time:
                # From the bootstrap point onward, the precise catch-event
                # system below covers this more accurately (every catch, not
                # just the first ever) — skip the generic achievement line.
                continue
            template = _classify_advancement(advancement)
            sentence = template.replace("{name}", f"**{name}**")
            timeline.append((ts, f"{time_prefix}{sentence}"))
            continue

        m = FELL_RE.search(line)
        if m:
            name = m.group(1)
            key = (day_key, name)
            count = fell_counts.get(key, 0) + 1
            fell_counts[key] = count
            if count == 1:
                timeline.append((ts, f"{time_prefix}😱 쿵! **{name}**가 높은 곳에서 떨어지고 말았다"))
            elif count == 2:
                timeline.append((ts, f"{time_prefix}😵 또다시... **{name}**가 높은 곳에서 굴러떨어졌다. 이쯤되면 고소공포증 훈련이 필요할지도"))
            # 3번째부터는 반복이라 생략
            continue

    for event in legendary_events:
        ts = datetime.fromisoformat(event["timestamp"])
        if ts < WORLD_EPOCH:
            continue
        time_prefix = f"[{ts.strftime('%H:%M')}] "
        if event["type"] == "catch":
            sentence = (
                f"{time_prefix}⚡ 믿을 수 없는 순간! **{event['player']}**가 "
                f"{event['ball']}로 {event['species']}(을)를 포획하는 데 성공했다!! (Lv.{event['level']})"
            )
        else:  # trade
            sentence = (
                f"{time_prefix}🔄 거래 성사! **{event['from']}**가(이) **{event['to']}**에게 "
                f"{event['species']}(을)를 넘겨줬다"
            )
        timeline.append((ts, sentence))

    for c in battles.get_resolved_battles():
        ts = datetime.fromisoformat(c["resolved_at"])
        if ts < WORLD_EPOCH:
            continue
        winner_name = c["challenger_name"] if c["resolved_winner"] == c["challenger_uuid"] else c["opponent_name"]
        loser_name = c["opponent_name"] if c["resolved_winner"] == c["challenger_uuid"] else c["challenger_name"]
        time_prefix = f"[{ts.strftime('%H:%M')}] "
        sentence = f"{time_prefix}⚔️ 배틀 승부! **{winner_name}**가(이) **{loser_name}**를 상대로 승리를 거뒀다!"
        timeline.append((ts, sentence))

    timeline.sort(key=lambda pair: pair[0])

    days: dict[str, list[str]] = {}
    for ts, sentence in timeline:
        days.setdefault(ts.strftime("%Y-%m-%d"), []).append(sentence)

    story = [
        {"date": day, "headline": _headline(day, events), "events": events}
        for day, events in sorted(days.items())
        if events
    ]
    return story


@app.get("/")
def root():
    return {"message": "Pixelmon Server1 player status API. See /players, /leaderboard and /story"}


@app.get("/players")
def players():
    player_list = get_player_status()
    online_names = {p["name"] for p in player_list if p["status"] == "online"}
    welcome_gift.check_and_welcome(online_names)
    return {
        "server_online": get_server_active(),
        "players": player_list,
    }


@app.get("/leaderboard")
def leaderboard():
    return {
        "server_online": get_server_active(),
        "leaderboard": get_leaderboard(),
    }


@app.get("/story")
def story():
    return {"story": get_story()}


@app.get("/legendaries")
def legendaries():
    return {"players": get_legendaries()}


@app.get("/party")
def party():
    return {"players": get_party_status()}


@app.get("/fun-stats")
def fun_stats():
    return get_fun_dashboards()


@app.get("/server-health")
def server_health():
    return get_server_health()


@app.post("/admin/announce")
def admin_announce(payload: dict, session: str | None = Cookie(default=None)):
    player = auth.get_session_player(session)
    if not player:
        raise HTTPException(401, "로그인이 필요합니다")
    if player["uuid"] != auth.ADMIN_UUID:
        raise HTTPException(403, "관리자만 접근할 수 있습니다")

    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "공지 내용을 입력해주세요")
    if len(message) > 500:
        raise HTTPException(400, "공지 내용이 너무 깁니다 (500자 이하)")

    try:
        rcon.tellraw("@a", f"📢 [공지] {message}", color="aqua", bold=True)
    except Exception:
        raise HTTPException(502, "게임 서버에 메시지를 보내지 못했습니다 (RCON 연결을 확인해주세요)")

    return {"ok": True}
