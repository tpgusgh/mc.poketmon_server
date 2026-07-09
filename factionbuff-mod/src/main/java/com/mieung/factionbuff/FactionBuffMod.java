package com.mieung.factionbuff;

import com.pixelmonmod.pixelmon.api.events.ExperienceGainEvent;
import net.minecraft.entity.player.ServerPlayerEntity;
import net.minecraft.util.text.ITextComponent;
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
 * Server-side only -- clients don't need this mod to join.
 */
@Mod("factionbuff")
public class FactionBuffMod {

    private static final Path MULTIPLIER_FILE =
            Paths.get("/home/hyunho/player-status-api/faction_boosted_players.txt");
    private static final Path PLAYER_FACTIONS_FILE =
            Paths.get("/home/hyunho/player-status-api/player_factions.txt");

    private static final Map<String, String> FACTION_DISPLAY_NAME = new HashMap<>();
    private static final Map<String, String> FACTION_COLOR = new HashMap<>();

    static {
        FACTION_DISPLAY_NAME.put("valor", "발로");
        FACTION_DISPLAY_NAME.put("mystic", "미스틱");
        FACTION_DISPLAY_NAME.put("instinct", "인스팅트");
        FACTION_DISPLAY_NAME.put("harmony", "하모니");

        FACTION_COLOR.put("valor", "red");
        FACTION_COLOR.put("mystic", "blue");
        FACTION_COLOR.put("instinct", "yellow");
        FACTION_COLOR.put("harmony", "light_purple");
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
        float multiplier = getMultiplier(owner.getGameProfile().getName());
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
        String color = FACTION_COLOR.getOrDefault(faction, "white");

        String json = "{\"text\":\"[" + escapeJson(factionName) + "] \",\"color\":\"" + color + "\","
                + "\"extra\":[{\"text\":\"" + escapeJson(event.getUsername()) + ": "
                + escapeJson(event.getMessage()) + "\",\"color\":\"white\"}]}";

        ITextComponent component = ITextComponent.Serializer.fromJson(json);
        if (component != null) {
            event.setComponent(component);
        }
    }

    private static String escapeJson(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
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
