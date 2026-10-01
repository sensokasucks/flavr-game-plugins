package com.fridge.minecraft.server;

import net.fabricmc.fabric.api.transfer.v1.transaction.Transaction;
import net.minecraft.nbt.NbtCompound;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import net.minecraft.world.World;
import team.reborn.energy.api.EnergyStorage;
import team.reborn.energy.api.EnergyStorageUtil;
import team.reborn.energy.api.base.SimpleEnergyStorage;

/** Shared FE push/pull + per-block level override. */
public final class PowerIo {

    private PowerIo() {}

    /** -1 = follow Stream Core global level. */
    public static int clampLevel(int level) {
        if (level < 0) return -1;
        return Math.min(15, level);
    }

    public static int effectiveLevel(int manualLevel) {
        if (manualLevel >= 0) return Math.min(15, manualLevel);
        return Math.max(0, Math.min(15, FridgeServerMod.currentPowerLevel));
    }

    public static boolean redstoneOff(World world, BlockPos pos) {
        return world != null && world.isReceivingRedstonePower(pos);
    }

    public static int cycleManual(int current) {
        if (current < 0) return 8;
        if (current >= 15) return -1;
        return current + 1;
    }

    public static void generateAndPush(
            World world,
            BlockPos pos,
            SimpleEnergyStorage buffer,
            long capacity,
            long generate
    ) {
        if (world == null || world.isClient) return;
        if (generate > 0) {
            try (Transaction tx = Transaction.openOuter()) {
                buffer.insert(generate, tx);
                tx.commit();
            }
        }
        CreateCompat.harvestToFe(world, pos, buffer, capacity - buffer.amount);

        // Push first so generators actually feed cables / machines
        for (Direction dir : Direction.values()) {
            if (buffer.amount <= 0) break;
            EnergyStorage target = EnergyStorage.SIDED.find(world, pos.offset(dir), dir.getOpposite());
            if (target == null || target == buffer || !target.supportsInsertion()) continue;
            EnergyStorageUtil.move(buffer, target, buffer.amount, null);
        }

        for (Direction dir : Direction.values()) {
            if (buffer.amount >= capacity) break;
            EnergyStorage source = EnergyStorage.SIDED.find(world, pos.offset(dir), dir.getOpposite());
            if (source == null || source == buffer || !source.supportsExtraction()) continue;
            EnergyStorageUtil.move(source, buffer, capacity - buffer.amount, null);
        }
    }

    public static void writeEnergy(NbtCompound nbt, SimpleEnergyStorage buffer, int manualLevel) {
        nbt.putLong("energy", buffer.amount);
        nbt.putInt("manualLevel", manualLevel);
    }

    public static int readEnergy(NbtCompound nbt, SimpleEnergyStorage buffer) {
        if (nbt.contains("energy")) {
            buffer.amount = Math.max(0, nbt.getLong("energy"));
        }
        return nbt.contains("manualLevel") ? nbt.getInt("manualLevel") : -1;
    }
}
