package net.minecraft.entity.player;

import com.mojang.authlib.GameProfile;

/**
 * Compile-only stub. func_146103_bH() is the real SRG name of PlayerEntity's
 * no-arg GameProfile getter (confirmed via Pixelmon's own compiled bytecode
 * call sites against the server's real SRG-named runtime jar) -- the
 * server's actual runtime class is used when the mod runs; this stub only
 * exists so javac can resolve the symbol at compile time. Never bundle this
 * stub into the mod jar.
 */
public class ServerPlayerEntity {
    public GameProfile func_146103_bH() {
        return null;
    }
}
