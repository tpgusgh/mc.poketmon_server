package com.mieung.factionbuff;

import com.pixelmonmod.pixelmon.api.events.ExperienceGainEvent;
import net.minecraft.entity.player.ServerPlayerEntity;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import net.minecraftforge.fml.ExtensionPoint;
import net.minecraftforge.fml.ModLoadingContext;
import net.minecraftforge.fml.common.Mod;
import org.apache.commons.lang3.tuple.Pair;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

/**
 * Reads the per-player EXP multiplier the website's API writes (one
 * "name:multiplier" line per boosted player, e.g. the #1 faction gets 1.5x
 * and #2 gets 1.2x) and applies it on battle EXP gain. The file is re-read
 * on every gain (cheap: a handful of names, infrequent event) so faction
 * rotations picked up by the web app apply without a server restart.
 *
 * Server-side only -- clients don't need this mod to join.
 */
@Mod("factionbuff")
public class FactionBuffMod {

    private static final Path STATE_FILE =
            Paths.get("/home/hyunho/player-status-api/faction_boosted_players.txt");

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

    private float getMultiplier(String playerName) {
        try {
            if (!Files.exists(STATE_FILE)) {
                return 1.0f;
            }
            List<String> lines = Files.readAllLines(STATE_FILE);
            for (String line : lines) {
                String trimmed = line.trim();
                int sep = trimmed.lastIndexOf(':');
                if (sep < 0) {
                    continue;
                }
                String name = trimmed.substring(0, sep);
                if (name.equalsIgnoreCase(playerName.trim())) {
                    return Float.parseFloat(trimmed.substring(sep + 1));
                }
            }
        } catch (IOException | NumberFormatException e) {
            return 1.0f;
        }
        return 1.0f;
    }
}
