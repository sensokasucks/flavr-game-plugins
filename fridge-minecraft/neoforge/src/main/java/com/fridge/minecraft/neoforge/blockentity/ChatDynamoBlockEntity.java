package com.fridge.minecraft.neoforge.blockentity;

import com.fridge.minecraft.neoforge.DeviceIndex;
import com.fridge.minecraft.neoforge.FridgeNeoMod;
import com.fridge.minecraft.neoforge.PowerState;
import com.simibubi.create.content.kinetics.base.GeneratingKineticBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.HolderLookup;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.world.level.block.state.BlockState;
import net.neoforged.neoforge.capabilities.Capabilities;
import net.neoforged.neoforge.energy.EnergyStorage;
import net.neoforged.neoforge.energy.IEnergyStorage;

public class ChatDynamoBlockEntity extends GeneratingKineticBlockEntity {
    public static final int MAX_FE_PER_TICK = 2400;
    public static final float MAX_RPM = 64f;
    public int drainRate = 8;
    public volatile long orderedRf = 0;
    public final EnergyStorage energy = new EnergyStorage(50_000, Integer.MAX_VALUE, Integer.MAX_VALUE);

    public ChatDynamoBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeNeoMod.CHAT_DYNAMO_BE.get(), pos, state);
    }

    public int level() {
        return orderedRf > 0 ? Math.max(1, drainRate) : 0;
    }

    public int generationPerTick() {
        return (int) Math.max(0, orderedRf);
    }

    @Override
    public void onLoad() {
        super.onLoad();
        DeviceIndex.track(this);
    }

    @Override
    public void initialize() {
        super.initialize();
        if (!hasSource() || getGeneratedSpeed() > getTheoreticalSpeed()) {
            updateGeneratedRotation();
        }
    }

    @Override
    public void tick() {
        super.tick();
        if (level == null || level.isClientSide) return;
        if (PowerState.redstoneOff(level, worldPosition)) {
            if (getTheoreticalSpeed() != 0) updateGeneratedRotation();
            return;
        }
        if (getTheoreticalSpeed() != getGeneratedSpeed()) updateGeneratedRotation();
        int gen = generationPerTick();
        if (gen > 0) energy.receiveEnergy(gen, false);
        pushEnergy();
    }

    private void pushEnergy() {
        if (energy.getEnergyStored() <= 0) return;
        for (Direction dir : Direction.values()) {
            if (energy.getEnergyStored() <= 0) break;
            IEnergyStorage target = level.getCapability(Capabilities.EnergyStorage.BLOCK, worldPosition.relative(dir), dir.getOpposite());
            if (target == null || !target.canReceive()) continue;
                int avail = energy.getEnergyStored();
            int accepted = target.receiveEnergy(avail, false);
            if (accepted > 0) energy.extractEnergy(accepted, false);
        }
    }

    @Override
    public float getGeneratedSpeed() {
        if (level != null && PowerState.redstoneOff(level, worldPosition)) return 0f;
        if (orderedRf <= 0 || drainRate <= 0) return 0f;
        return (MAX_RPM * drainRate) / 15f;
    }

    @Override
    protected void write(CompoundTag tag, HolderLookup.Provider registries, boolean clientPacket) {
        super.write(tag, registries, clientPacket);
        tag.putInt("drainRate", drainRate);
        tag.putInt("energy", energy.getEnergyStored());
    }

    @Override
    protected void read(CompoundTag tag, HolderLookup.Provider registries, boolean clientPacket) {
        super.read(tag, registries, clientPacket);
        if (tag.contains("drainRate")) drainRate = Math.max(0, Math.min(15, tag.getInt("drainRate")));
        else if (tag.contains("manualLevel")) {
            int legacy = tag.getInt("manualLevel");
            drainRate = legacy < 0 ? 8 : Math.max(0, Math.min(15, legacy));
        }
    }
}
