"""Pixelmon's own passive Zygarde Cell/Core spawner (while holding a Zygarde
Cube) turned out to never actually fire in practice on this server -- see
ZygardeCellsListener in the Pixelmon jar, which re-registers cube holders
every 5s but apparently never places a block regardless. This replaces it
with an equivalent RCON-driven version: every player currently online and
holding a Zygarde Cube gets a nearby Cell (95%) or Core (5%) placed on
naturally valid ground every so often, using Pixelmon's own
"pixelmon:zygarde_spawnable" block tag so it lands on the same surfaces
(grass, logs, leaves) the real feature would have used.
"""
import asyncio
import random
import re

import rcon

CUBE_ITEM = "pixelmon:zygarde_cube"
CELL_BLOCK = "pixelmon:zygarde_cell"
CORE_BLOCK = "pixelmon:zygarde_core"
CORE_CHANCE = 0.05

CHECK_INTERVAL_SECONDS = 15
# No cooldown between attempts, so worst case (nothing found) this many RCON
# round trips fire every single cycle, forever, for each cube holder -- keep
# it modest. A miss just means it tries again with fresh random spots next
# cycle rather than giving up.
CANDIDATE_ATTEMPTS = 4
MIN_RADIUS = 4
MAX_RADIUS = 16
# Terrain isn't flat, so a single fixed height guess relative to the player
# misses valid ground the moment the search radius crosses a hill or dip --
# scan a small vertical band at each (dx, dz) candidate instead.
Y_OFFSETS = range(-2, 3)


def _online_player_names() -> list[str]:
    try:
        result = rcon.rcon_command("list")
    except Exception:
        return []
    m = re.search(r":\s*(.*)$", result.strip())
    if not m or not m.group(1).strip():
        return []
    return [name.strip() for name in m.group(1).split(",") if name.strip()]


def _is_holding_cube(player_name: str) -> bool:
    """True only if the cube is actually in a hand (mainhand or offhand),
    not just tucked away somewhere in the inventory."""
    try:
        mainhand = rcon.rcon_command(f"data get entity {player_name} SelectedItem")
        offhand = rcon.rcon_command(f"data get entity {player_name} Inventory[{{Slot:-106b}}]")
    except Exception:
        return False
    return (
        _result_has_item(mainhand, player_name)
        or _result_has_item(offhand, player_name)
    )


def _result_has_item(result: str, player_name: str) -> bool:
    return result.strip().startswith(player_name) and CUBE_ITEM in result


def _random_offset() -> tuple[int, int]:
    while True:
        dx = random.randint(-MAX_RADIUS, MAX_RADIUS)
        dz = random.randint(-MAX_RADIUS, MAX_RADIUS)
        if max(abs(dx), abs(dz)) >= MIN_RADIUS:
            return dx, dz


def _try_spawn_near(player_name: str) -> bool:
    block = CORE_BLOCK if random.random() < CORE_CHANCE else CELL_BLOCK
    for _ in range(CANDIDATE_ATTEMPTS):
        dx, dz = _random_offset()
        for dy in Y_OFFSETS:
            cmd = (
                f"execute at {player_name} positioned ~{dx} ~{dy} ~{dz} "
                f"if block ~ ~ ~ #pixelmon:zygarde_spawnable run setblock ~ ~1 ~ {block}"
            )
            try:
                result = rcon.rcon_command(cmd)
            except Exception:
                return False
            if result.strip().startswith("Changed the block"):
                return True
    return False


async def zygarde_spawn_loop() -> None:
    while True:
        try:
            for name in _online_player_names():
                if _is_holding_cube(name):
                    _try_spawn_near(name)
        except Exception:
            pass
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
