"""Incremental journal processing, shared by /players, /story and /fun-stats.

All three used to re-scan the entire journal (from WORLD_EPOCH to now) on
every cache miss. That was fine while the log was small, but journald's
--since filtering turns out to be effectively instant regardless of total
log depth (it's time-indexed, not a linear scan) -- the slowness was
entirely self-inflicted by asking for everything every time. This mirrors
the pattern main.py's update_playtime() already used successfully: persist
a "processed up to" cursor plus whatever running state each consumer needs,
and only ever ask journalctl for lines newer than that cursor.
"""
import json
import random
import re
import subprocess
from datetime import datetime
from pathlib import Path

# The 1.16.5 world started at this point; ignore anything before it (old 1.20.1 era).
WORLD_EPOCH = datetime.fromisoformat("2026-07-04T18:03:00+09:00")

JOURNAL_TIMEOUT = 60  # seconds -- generous safety margin, bounded queries are normally instant

TS_RE = re.compile(r"^(\S+)\s")
JOIN_RE = re.compile(r": (\w[\w]*) joined the game$")
LEFT_RE = re.compile(r": (\w[\w]*) left the game$")
LOST_RE = re.compile(r": (\w[\w]*) lost connection")
RESTART_RE = re.compile(r"Starting minecraft server version")

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
ADVANCEMENT_RE = re.compile(r": (\w[\w]*) has made the advancement \[(.+)\]$")
FELL_RE = re.compile(r": (\w[\w]*) fell from a high place$")
LEGEND_RE = re.compile(r"legend", re.I)

RECONNECT_GRACE_SECONDS = 600

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

QUIET_HEADLINES = ["조용했던 하루", "평온하게 지나간 하루", "별일 없이 흘러간 하루"]
STEADY_HEADLINES = ["잔잔하지만 알찼던 하루", "소소한 이야기가 있었던 하루", "무난하게 흘러간 하루"]
BUSY_HEADLINES = ["다사다난했던 하루!", "정신없이 바빴던 하루!", "이런저런 일이 많았던 하루!", "쉴 틈 없던 하루!"]
WILD_HEADLINES = ["전설이 쓰여진 날!!", "역사에 남을 하루!!", "다들 미쳐 날뛴 하루!!", "서버가 들썩인 하루!!"]


def _classify_advancement(name: str) -> str:
    for pattern, template in ADVANCEMENT_TEMPLATES:
        if pattern.search(name):
            return template
    return "🏆 {name}가 값진 업적 '" + name + "'을(를) 달성하며 이름을 알렸다!"


def headline(day_key: str, events: list[str]) -> str:
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


def parse_line(line: str):
    m = TS_RE.match(line)
    if not m:
        return None
    try:
        ts = datetime.fromisoformat(m.group(1))
    except ValueError:
        return None
    return ts, line


def fetch_journal_lines_since(since: datetime) -> list[str]:
    cmd = [
        "journalctl", "-u", "minecraft.service", "--no-pager", "-o", "short-iso",
        "--since", since.strftime("%Y-%m-%d %H:%M:%S"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=JOURNAL_TIMEOUT)
    return result.stdout.splitlines()


STATE_FILE = Path(__file__).parent / "journal_state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "last_processed": WORLD_EPOCH.isoformat(),
        "player_status": {},
        "death_counts": {},
        "fall_counts": {},
        "achievement_counts": {},
        "seen_players": [],
        "story_fell_counts_by_day": {},
        "story_events": [],
    }


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _apply_line(ts: datetime, line: str, state: dict) -> None:
    day_key = ts.strftime("%Y-%m-%d")
    time_prefix = f"[{ts.strftime('%H:%M')}] "
    player_status = state["player_status"]
    seen_players = state["seen_players"]  # list, order doesn't matter but JSON has no set type

    if RESTART_RE.search(line):
        for info in player_status.values():
            if info["online"]:
                info["online"] = False
                info["last_seen"] = ts.isoformat()
        return

    m = JOIN_RE.search(line)
    if m:
        name = m.group(1)
        info = player_status.setdefault(name, {"online": False, "since": None, "last_seen": None})
        is_quick_reconnect = (
            info["last_seen"] is not None
            and info["since"] is not None
            and (ts - datetime.fromisoformat(info["last_seen"])).total_seconds() <= RECONNECT_GRACE_SECONDS
        )
        info["online"] = True
        if not is_quick_reconnect:
            info["since"] = ts.isoformat()

        if name not in seen_players:
            seen_players.append(name)
            state["story_events"].append(
                {"ts": ts.isoformat(), "sentence": f"{time_prefix}🚪 새로운 도전자 등장! **{name}**가(이) 처음으로 이 세계에 발을 들였다"}
            )
        return

    m = LEFT_RE.search(line) or LOST_RE.search(line)
    if m:
        name = m.group(1)
        info = player_status.setdefault(name, {"online": False, "since": None, "last_seen": None})
        if info["online"]:
            info["online"] = False
            info["last_seen"] = ts.isoformat()
        return

    m = DEATH_RE.search(line)
    if m:
        name = m.group(1)
        state["death_counts"][name] = state["death_counts"].get(name, 0) + 1
        # Falls through deliberately -- "fell from a high place" also matches
        # nothing else here since DEATH_RE doesn't cover it; handled below.

    m = FELL_ANY_RE.search(line)
    if m:
        name = m.group(1)
        state["fall_counts"][name] = state["fall_counts"].get(name, 0) + 1

        key = f"{day_key}|{name}"
        count = state["story_fell_counts_by_day"].get(key, 0) + 1
        state["story_fell_counts_by_day"][key] = count
        if count == 1:
            state["story_events"].append(
                {"ts": ts.isoformat(), "sentence": f"{time_prefix}😱 쿵! **{name}**가 높은 곳에서 떨어지고 말았다"}
            )
        elif count == 2:
            state["story_events"].append(
                {"ts": ts.isoformat(), "sentence": f"{time_prefix}😵 또다시... **{name}**가 높은 곳에서 굴러떨어졌다. 이쯤되면 고소공포증 훈련이 필요할지도"}
            )
        return

    m = ADVANCEMENT_RE.search(line)
    if m:
        name, advancement = m.group(1), m.group(2)
        state["achievement_counts"][name] = state["achievement_counts"].get(name, 0) + 1
        # The legendary-catch-skip (superseded by the precise catch-event
        # system past its bootstrap time) is applied at read time in
        # get_story_events(), since it depends on legendary_bootstrap_time
        # which isn't known here.
        template = _classify_advancement(advancement)
        sentence = template.replace("{name}", f"**{name}**")
        state["story_events"].append(
            {"ts": ts.isoformat(), "sentence": f"{time_prefix}{sentence}", "advancement": advancement}
        )
        return


def update() -> dict:
    """Processes any journal lines newer than the last checkpoint and
    persists the result. Safe to call often -- if there's nothing new,
    it's just one cheap journalctl invocation."""
    state = _load_state()
    last_processed = datetime.fromisoformat(state["last_processed"])
    lines = fetch_journal_lines_since(last_processed)
    newest_ts = last_processed

    for raw in lines:
        parsed = parse_line(raw)
        if not parsed:
            continue
        ts, line = parsed
        if ts < WORLD_EPOCH or ts <= last_processed:
            continue
        newest_ts = max(newest_ts, ts)
        _apply_line(ts, line, state)

    state["last_processed"] = newest_ts.isoformat()
    _save_state(state)
    return state


def get_player_status() -> list[dict]:
    from datetime import timezone

    state = update()
    now = datetime.now(timezone.utc)
    players = []
    for name, info in sorted(state["player_status"].items()):
        if info["online"] and info["since"]:
            since = datetime.fromisoformat(info["since"])
            hours = round((now - since).total_seconds() / 3600, 1)
            players.append({"name": name, "status": "online", "since": info["since"], "hours_connected": hours})
        else:
            last_seen = info["last_seen"]
            hours_ago = round((now - datetime.fromisoformat(last_seen)).total_seconds() / 3600, 1) if last_seen else None
            players.append({"name": name, "status": "offline", "last_seen": last_seen, "hours_since_last_seen": hours_ago})
    return players


def get_fun_dashboard_counts() -> dict:
    state = update()
    death_counts = dict(state["death_counts"])
    for name, count in state["fall_counts"].items():
        death_counts[name] = death_counts.get(name, 0) + count
    return {
        "death_counts": death_counts,
        "achievement_counts": dict(state["achievement_counts"]),
    }


def get_story_events(legendary_bootstrap_time: datetime | None) -> list[tuple[datetime, str]]:
    """Returns (timestamp, sentence) pairs derived from the journal, skipping
    generic legendary-catch advancement lines once the precise catch-event
    system (in main.py, based on NBT ownership diffing) takes over."""
    state = update()
    events = []
    for e in state["story_events"]:
        ts = datetime.fromisoformat(e["ts"])
        if ts < WORLD_EPOCH:
            continue
        advancement = e.get("advancement")
        if advancement and LEGEND_RE.search(advancement) and legendary_bootstrap_time and ts >= legendary_bootstrap_time:
            continue
        events.append((ts, e["sentence"]))
    return events
