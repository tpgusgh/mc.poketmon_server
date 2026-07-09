# factionbuff

A tiny server-side-only Forge mod for Minecraft 1.16.5 + Forge 36.2.34 + Pixelmon 9.1.13.

It hooks Pixelmon's `ExperienceGainEvent` and multiplies battle EXP for
players whose name appears in a plain text file
(`/home/hyunho/player-status-api/faction_boosted_players.txt`, one
`playerName:multiplier` per line). That file is written by the website's
FastAPI backend (`factions.py`) based on which in-game "faction" is
currently ranked #1 (1.5x) or #2 (1.2x) on the faction leaderboard, so the
buff always matches the live standings without needing a server restart.

## Why this exists

The goal was an exact, real EXP multiplier tied to a web-tracked faction
ranking -- not a held-item workaround (Pixelmon's "Lucky Egg" gives a fixed
+50% and has to be manually equipped). Pixelmon exposes `ExperienceGainEvent`
as a cancelable/mutable Forge event (`getExperience()` / `setExperience(int)`),
which makes an exact multiplier straightforward from inside the JVM.

## Building

There's no Gradle/ForgeGradle project here -- it's compiled directly with
`javac` against the classes already present in a running Forge+Pixelmon
server, which sidesteps needing to download Minecraft's decompiled/mapped
sources just to build one small class.

1. Gather a classpath from a real server install:
   ```bash
   CP=$(find /path/to/mcserver/libraries -name "*.jar" | tr '\n' ':')
   CP="$CP/path/to/mcserver/forge-1.16.5-36.2.34.jar"
   CP="$CP:/path/to/mcserver/minecraft_server.1.16.5.jar"
   CP="$CP:/path/to/mcserver/mods/Pixelmon-1.16.5-9.1.13-universal.jar"
   ```
2. Minecraft's own vanilla classes (like `ServerPlayerEntity`) are obfuscated
   on disk (no official Mojang mapping is available outside of a full
   ForgeGradle project), so a **compile-only stub** is needed for the one
   vanilla method this mod calls (`ServerPlayerEntity.getGameProfile()`).
   The real class is loaded by Forge's own remapping classloader at runtime,
   so the stub is only for `javac` and must never be bundled into the mod jar:
   ```java
   // stub-src/net/minecraft/entity/player/ServerPlayerEntity.java
   package net.minecraft.entity.player;
   import com.mojang.authlib.GameProfile;
   public class ServerPlayerEntity {
       public GameProfile getGameProfile() { return null; }
   }
   ```
   ```bash
   javac -cp "$CP" -d stub-out stub-src/net/minecraft/entity/player/ServerPlayerEntity.java
   ```
3. Compile the mod with the stub classes placed first on the classpath:
   ```bash
   javac -cp "stub-out:$CP" -d out src/main/java/com/mieung/factionbuff/FactionBuffMod.java
   ```
4. Package the jar (note: only the compiled mod class + resources, never the stub):
   ```bash
   cp -r src/main/resources/* out/
   jar cf factionbuff-1.1.0.jar -C out .
   ```

## Deploying safely

Always test on a staging server (a second copy of the modpack) before
touching production -- boot it and confirm you see `Done (...)!` with no
exceptions, and that `mod:factionbuff` shows up in the "Datapacks found" log
line, before copying the jar into the live server's `mods/` folder and
restarting.
