package com.fridge.minecraft.server;

import net.minecraft.block.BlockState;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.nbt.NbtCompound;
import net.minecraft.registry.RegistryWrapper;
import net.minecraft.util.math.BlockPos;
import team.reborn.energy.api.base.SimpleEnergyStorage;

public class ChatKineticBlockEntity extends BlockEntity {

    public static float MAX_RPM = 128f;
    public static float MAX_SU = 4096f;
    public static final long CAPACITY = 50_000L;

    public int drainRate = 8;
    public volatile long orderedRf = 0;

    public final SimpleEnergyStorage energyStorage = new SimpleEnergyStorage(
            CAPACITY, Long.MAX_VALUE, Long.MAX_VALUE
    ) {
        @Override
        protected void onFinalCommit() {
            markDirty();
        }
    };

    public ChatKineticBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeServerMod.CHAT_KINETIC_BLOCK_ENTITY, pos, state);
    }

    public int level() {
        return orderedRf > 0 ? Math.max(1, drainRate) : 0;
    }

    public static float rpmForLevel(int level) {
        if (level <= 0) return 0f;
        return (MAX_RPM * level) / 15f;
    }

    public static float suForLevel(int level) {
        if (level <= 0) return 0f;
        return (MAX_SU * level) / 15f;
    }

    public float currentRpm() {
        if (orderedRf <= 0) return 0f;
        return rpmForLevel(Math.max(1, drainRate));
    }

    public void serverTick() {
        if (world == null || world.isClient) return;
        if (PowerIo.redstoneOff(world, pos)) return;
        PowerIo.generateAndPush(world, pos, energyStorage, CAPACITY, Math.max(0, orderedRf));
    }

    @Override
    protected void writeNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup lookup) {
        super.writeNbt(nbt, lookup);
        nbt.putLong("energy", energyStorage.amount);
        nbt.putInt("drainRate", drainRate);
    }

    @Override
    protected void readNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup lookup) {
        super.readNbt(nbt, lookup);
        if (nbt.contains("energy")) energyStorage.amount = Math.max(0, nbt.getLong("energy"));
        if (nbt.contains("drainRate")) drainRate = Math.max(0, Math.min(15, nbt.getInt("drainRate")));
        else if (nbt.contains("manualLevel")) {
            int legacy = nbt.getInt("manualLevel");
            drainRate = legacy < 0 ? 8 : Math.max(0, Math.min(15, legacy));
        }
    }
}
