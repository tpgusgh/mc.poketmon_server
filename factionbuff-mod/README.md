# factionbuff

A tiny server-side-only Forge mod for Minecraft 1.16.5 + Forge 36.2.34 + Pixelmon 9.1.13.

It does two things, both driven by plain text files the website's FastAPI
backend writes so neither needs a server restart when standings change:

1. Hooks Pixelmon's `ExperienceGainEvent` and multiplies battle EXP for
   players whose name appears in
   `/home/hyunho/player-status-api/faction_boosted_players.txt` (one
   `playerName:multiplier` per line) -- written by `factions.py` based on
   which in-game "faction" is currently ranked #1 (1.5x) or #2 (1.2x) on the
   faction leaderboard.
2. Hooks Forge's `ServerChatEvent` and recolors chat with a `[진영이름] `
   prefix in that faction's color, reading
   `/home/hyunho/player-status-api/player_factions.txt` (one
   `playerName:factionKey` per line).

## Why this exists

The goal was an exact, real EXP multiplier tied to a web-tracked faction
ranking -- not a held-item workaround (Pixelmon's "Lucky Egg" gives a fixed
+50% and has to be manually equipped). Pixelmon exposes `ExperienceGainEvent`
as a cancelable/mutable Forge event (`getExperience()` / `setExperience(int)`),
which makes an exact multiplier straightforward from inside the JVM.

## Building -- and the SRG naming trap (read this before touching vanilla APIs)

There's no Gradle/ForgeGradle project here -- it's compiled directly with
`javac` against the classes already present in a running Forge+Pixelmon
server, which sidesteps needing to download Minecraft's decompiled/mapped
sources just to build one small class.

**Important, learned the hard way:** this server's runtime vanilla classes
are **SRG-named** (e.g. `func_230529_a_`), not friendly MCP names like
`append` or `mergeStyle`, and not obfuscated single-letter names either.
There is no live remapping classloader translating friendly names to real
ones for third-party mods here -- whatever method name you write in source
must be the literal name that exists in the loaded class. A prior version of
this mod guessed MCP-style names for two vanilla calls
(`ServerPlayerEntity.getGameProfile()` and
`ITextComponent.Serializer.fromJson(String)`) that don't actually exist under
those names at runtime. The EXP-multiplier hook failed silently (Pixelmon's
event bus swallows exceptions per-listener); the chat hook did not fail
silently -- `ServerChatEvent` runs on Forge's raw `EventBus` with no such
protection, so a `NoSuchMethodError` there **crashed the entire server** the
first time a player chatted after it was deployed.

**Never guess a vanilla method name.** Verify it first by extracting real
constant-pool references from bytecode that's already known to work:

- The ground-truth class file is
  `libraries/net/minecraft/server/<version>/server-<version>-srg.jar` inside
  the server install -- this is what Forge actually loads.
- Other already-running, already-proven mods (Pixelmon itself, FTB
  Essentials) call these same vanilla APIs successfully. Extracting their
  compiled `.class` files' constant pool (`Methodref`/`InterfaceMethodref`
  entries: declaring class + name + descriptor) shows you the exact real
  name and signature they call -- copy that, don't guess a "nicer" name.
- Enum constants (like `TextFormatting.RED`) are never SRG-renamed and are
  safe to reference by their normal name.

Confirmed via this method for the current version:
- `PlayerEntity.func_146103_bH()` → `GameProfile` (the real no-arg
  GameProfile getter; `getGameProfile()` does not exist).
- `IFormattableTextComponent.func_230529_a_(ITextComponent)` →
  `IFormattableTextComponent` (append a sibling component).
- `IFormattableTextComponent.func_240699_a_(TextFormatting)` →
  `IFormattableTextComponent` (mergeStyle with a single color).
- `StringTextComponent(String)` constructor.
- There is no static `ITextComponent.Serializer.fromJson(String)` -- the
  real deserializer is an *instance* method
  (`deserialize(JsonElement, Type, JsonDeserializationContext)`) meant to be
  driven by Gson, not called directly.

### Build steps

1. Gather a classpath from a real server install (must include the
   `-srg.jar` mentioned above, plus Pixelmon and Forge's own jars):
   ```bash
   CP=$(find /path/to/mcserver/libraries -name "*.jar" | tr '\n' ':')
   CP="$CP/path/to/mcserver/forge-1.16.5-36.2.34.jar"
   CP="$CP:/path/to/mcserver/minecraft_server.1.16.5.jar"
   CP="$CP:/path/to/mcserver/mods/Pixelmon-1.16.5-9.1.13-universal.jar"
   ```
2. Vanilla classes are obfuscated on disk in some of the bundled jars, and
   `javac` (unlike the JVM at runtime) also outright refuses to read a few of
   the real SRG class files here (`bad RuntimeInvisibleParameterAnnotations
   attribute`), so **compile-only stubs** stand in for every vanilla
   type/method this mod touches, using the exact verified SRG names above.
   The real classes are what actually load at runtime; stubs are only for
   `javac` and must never be bundled into the mod jar. See `stub-src/` next
   to this README for the current set (`ServerPlayerEntity`, `ITextComponent`,
   `IFormattableTextComponent`, `StringTextComponent`, `TextFormatting`).
   ```bash
   javac -cp "$CP" -d stub-out $(find stub-src -name "*.java")
   ```
3. Compile the mod with the stub classes placed first on the classpath:
   ```bash
   javac -cp "stub-out:$CP" -d out src/main/java/com/mieung/factionbuff/FactionBuffMod.java
   ```
4. Package the jar (note: only the compiled mod class + resources, never the stub):
   ```bash
   cp -r src/main/resources/* out/
   jar cf factionbuff-1.2.1.jar -C out .
   ```

## Deploying safely

Always test on a staging server (a second copy of the modpack) before
touching production -- boot it and confirm you see `Done (...)!` with no
exceptions, and that `mod:factionbuff` shows up in the "Datapacks found" log
line. **A clean boot is not enough for anything that hooks a player-triggered
event (chat, EXP gain, etc.)** -- have an actual player trigger that event on
staging (join and chat, gain battle EXP, ...) before promoting to production.
