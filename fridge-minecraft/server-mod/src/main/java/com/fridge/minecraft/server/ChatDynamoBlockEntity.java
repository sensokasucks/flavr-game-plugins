package com.fridge.minecraft.server;

import net.minecraft.block.BlockState;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.nbt.NbtCompound;
import net.minecraft.registry.RegistryWrapper;
import net.minecraft.util.math.BlockPos;
import team.reborn.energy.api.base.SimpleEnergyStorage;

/**
 * Energy buffer only. Stream Core decides how much FE to mint each pulse.
 * Sneak-click drainRate (0–15) is how hard this block asks Core to
 * debit the market — it does not generate free power.
 */
public class ChatDynamoBlockEntity extends BlockEntity {

    public static long MAX_RF_PER_TICK = 2400L;
    public static final long CAPACITY = 50_000L;

    /** 0 = idle. 15 = full drain request. */
    public int drainRate = 8;
    /** Last FE/t Core authorized. 0 until Core posts an order. */
    public volatile long orderedRf = 0;

    public final SimpleEnergyStorage energyStorage = new SimpleEnergyStorage(
            CAPACITY, Long.MAX_VALUE, Long.MAX_VALUE
    ) {
        @Override
        protected void onFinalCommit() {
            markDirty();
        }
    };

    public ChatDynamoBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeServerMod.CHAT_DYNAMO_BLOCK_ENTITY, pos, state);
    }

    public int level() {
        return orderedRf > 0 ? Math.max(1, drainRate) : 0;
    }

    public long generationPerTick() {
        return Math.max(0, orderedRf);
    }

    public void tick() {
        if (world == null || world.isClient) return;
        if (PowerIo.redstoneOff(world, pos)) return;
        PowerIo.generateAndPush(world, pos, energyStorage, CAPACITY, generationPerTick());
    }

    public static int cycleDrain(int current) {
        if (current < 0) return 8;
        if (current >= 15) return 0;
        return current + 1;
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
