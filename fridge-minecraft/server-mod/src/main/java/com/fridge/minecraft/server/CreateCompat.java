package com.fridge.minecraft.server;

import net.fabricmc.fabric.api.transfer.v1.transaction.Transaction;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import net.minecraft.world.World;
import team.reborn.energy.api.base.SimpleEnergyStorage;

import java.lang.reflect.Method;

/**
 * Optional Create bridge. Compiles without Create on the classpath.
 *
 * Official Create Fabric stops at 1.20.1; 1.21.1 ports use the same
 * {@code com.simibubi.create...KineticBlockEntity} class names.
 * When that class exists we read adjacent shaft speed and convert
 * |RPM| into FE (and the reverse: spend FE to report a generated RPM
 * on our own kinetic block).
 *
 * Conversion (configurable):
 *   1 RPM-tick → {@link #fePerRpm} FE
 */
public final class CreateCompat {

    public static long fePerRpm = 8L;
    public static boolean present;

    private static Class<?> kineticBeClass;
    private static Method getSpeed;

    static {
        present = FabricLoader.getInstance().isModLoaded("create")
                || FabricLoader.getInstance().isModLoaded("create-fly");
        try {
            kineticBeClass = Class.forName("com.simibubi.create.content.kinetics.base.KineticBlockEntity");
            getSpeed = kineticBeClass.getMethod("getSpeed");
            present = true;
        } catch (Throwable ignored) {
            // Create not on the classpath — FE-only mode.
        }
    }

    private CreateCompat() {}

    public static float speedOf(BlockEntity be) {
        if (kineticBeClass == null || be == null) return 0f;
        if (!kineticBeClass.isInstance(be)) return 0f;
        try {
            Object v = getSpeed.invoke(be);
            if (v instanceof Number n) return n.floatValue();
        } catch (Throwable ignored) {}
        return 0f;
    }

    /** Harvest rotation from adjacent Create kinetics into an FE buffer. */
    public static long harvestToFe(World world, BlockPos pos, SimpleEnergyStorage buffer, long maxFe) {
        if (world == null || maxFe <= 0) return 0;
        long gained = 0;
        for (Direction dir : Direction.values()) {
            if (gained >= maxFe) break;
            BlockEntity be = world.getBlockEntity(pos.offset(dir));
            float rpm = Math.abs(speedOf(be));
            if (rpm < 0.01f) continue;
            long add = Math.min(maxFe - gained, (long) Math.floor(rpm * fePerRpm));
            if (add <= 0) continue;
            try (Transaction tx = Transaction.openOuter()) {
                long inserted = buffer.insert(add, tx);
                tx.commit();
                gained += inserted;
            }
        }
        return gained;
    }

    public static long rpmToFe(float rpm) {
        if (rpm <= 0) return 0;
        return (long) Math.floor(Math.abs(rpm) * fePerRpm);
    }

    public static float feToRpm(long fe) {
        if (fe <= 0 || fePerRpm <= 0) return 0f;
        return (float) fe / (float) fePerRpm;
    }
}
