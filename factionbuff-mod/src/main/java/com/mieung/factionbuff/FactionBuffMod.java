package com.mieung.factionbuff;

import com.pixelmonmod.pixelmon.api.events.ExperienceGainEvent;
import net.minecraft.entity.player.ServerPlayerEntity;
import net.minecraft.util.text.IFormattableTextComponent;
import net.minecraft.util.text.ITextComponent;
import net.minecraft.util.text.StringTextComponent;
import net.minecraft.util.text.TextFormatting;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.ServerChatEvent;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import net.minecraftforge.fml.ExtensionPoint;
import net.minecraftforge.fml.ModLoadingContext;
import net.minecraftforge.fml.common.Mod;
import org.apache.commons.lang3.tuple.Pair;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Two things, both driven by plain text files the website's API writes so
 * neither needs a server restart when faction standings/membership change:
 *
 * 1. Reads the per-player EXP multiplier (one "name:multiplier" line per
 *    boosted player, e.g. the #1 faction gets 1.5x and #2 gets 1.2x) and
 *    applies it on battle EXP gain.
 * 2. Reads each player's chosen faction (one "name:factionKey" line) and
 *    recolors their chat messages with a "[진영이름] " prefix in that
 *    faction's color, name+message in white.
 *
 * Note on method names: this project has no ForgeGradle/MCP mapping setup,
 * so it's compiled directly against the server's own SRG-named runtime jar
 * (libraries/net/minecraft/server/.../server-*-srg.jar). Any vanilla method
 * beyond simple/likely-unobfuscated ones must be called by its real SRG name
 * (funcXXXXX_x), verified ahead of time by extracting real call sites from
 * Pixelmon/FTB Essentials' own compiled bytecode (never guessed from MCP-era
 * naming conventions -- a prior guess here crashed the whole server the
 * first time a player chatted).
 *
 * Server-side only -- clients don't need this mod to join.
 */
@Mod("factionbuff")
public class FactionBuffMod {

    private static final Path MULTIPLIER_FILE =
            Paths.get("/home/hyunho/player-status-api/faction_boosted_players.txt");
    private static final Path PLAYER_FACTIONS_FILE =
            Paths.get("/home/hyunho/player-status-api/player_factions.txt");

    private static final Map<String, String> FACTION_DISPLAY_NAME = new HashMap<>();
    private static final Map<String, TextFormatting> FACTION_COLOR = new HashMap<>();

    static {
        FACTION_DISPLAY_NAME.put("valor", "발로");
        FACTION_DISPLAY_NAME.put("mystic", "미스틱");
        FACTION_DISPLAY_NAME.put("instinct", "인스팅트");
        FACTION_DISPLAY_NAME.put("harmony", "하모니");

        FACTION_COLOR.put("valor", TextFormatting.RED);
        FACTION_COLOR.put("mystic", TextFormatting.BLUE);
        FACTION_COLOR.put("instinct", TextFormatting.YELLOW);
        FACTION_COLOR.put("harmony", TextFormatting.LIGHT_PURPLE);
    }

    public FactionBuffMod() {
        MinecraftForge.EVENT_BUS.register(this);
        ModLoadingContext.get().registerExtensionPoint(
                ExtensionPoint.DISPLAYTEST, () -> Pair.of(() -> "ANY", (remote, isServer) -> true));
    }

    @SubscribeEvent
    public void onExperienceGain(ExperienceGainEvent event) {
        if (!event.pokemon.hasOwner()) {
            return;
        }
        ServerPlayerEntity owner = event.pokemon.getPlayerOwner();
        if (owner == null) {
            return;
        }
        // func_146103_bH() is PlayerEntity's real (SRG) no-arg GameProfile
        // getter -- confirmed via Pixelmon's own compiled call sites.
        float multiplier = getMultiplier(owner.func_146103_bH().getName());
        if (multiplier != 1.0f) {
            event.setExperience(Math.round(event.getExperience() * multiplier));
        }
    }

    @SubscribeEvent
    public void onServerChat(ServerChatEvent event) {
        String faction = lookupValue(PLAYER_FACTIONS_FILE, event.getUsername());
        if (faction == null) {
            return;
        }
        String factionName = FACTION_DISPLAY_NAME.getOrDefault(faction, faction);
        TextFormatting color = FACTION_COLOR.getOrDefault(faction, TextFormatting.WHITE);

        // func_240699_a_ = mergeStyle(TextFormatting), func_230529_a_ = append(ITextComponent).
        // Both verified against the real SRG-named IFormattableTextComponent
        // interface and against FTB Essentials' own compiled usage of them.
        IFormattableTextComponent prefix = new StringTextComponent("[" + factionName + "] ")
                .func_240699_a_(color);
        IFormattableTextComponent body = new StringTextComponent(event.getUsername() + ": " + event.getMessage())
                .func_240699_a_(TextFormatting.WHITE);
        ITextComponent component = prefix.func_230529_a_(body);

        event.setComponent(component);
    }

    private float getMultiplier(String playerName) {
        String value = lookupValue(MULTIPLIER_FILE, playerName);
        if (value == null) {
            return 1.0f;
        }
        try {
            return Float.parseFloat(value);
        } catch (NumberFormatException e) {
            return 1.0f;
        }
    }

    /** Reads "name:value" lines from a file and returns the value for a matching name. */
    private static String lookupValue(Path file, String playerName) {
        try {
            if (!Files.exists(file)) {
                return null;
            }
            List<String> lines = Files.readAllLines(file);
            for (String line : lines) {
                String trimmed = line.trim();
                int sep = trimmed.lastIndexOf(':');
                if (sep < 0) {
                    continue;
                }
                String name = trimmed.substring(0, sep);
                if (name.equalsIgnoreCase(playerName.trim())) {
                    return trimmed.substring(sep + 1);
                }
            }
        } catch (IOException e) {
            return null;
        }
        return null;
    }
}
