package com.fridge.minecraft.neoforge.blockentity;

import com.fridge.minecraft.neoforge.DeviceIndex;
import com.fridge.minecraft.neoforge.FridgeNeoMod;
import com.fridge.minecraft.neoforge.PowerState;
import com.simibubi.create.content.kinetics.base.KineticBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.block.state.BlockState;
import net.neoforged.neoforge.energy.EnergyStorage;

public class DividendVaultBlockEntity extends KineticBlockEntity {
    public final EnergyStorage energy = new EnergyStorage(100_000, Integer.MAX_VALUE, Integer.MAX_VALUE);

    public DividendVaultBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeNeoMod.DIVIDEND_VAULT_BE.get(), pos, state);
    }

    @Override
    public void onLoad() {
        super.onLoad();
        DeviceIndex.track(this);
    }

    @Override
    public void tick() {
        super.tick();
        if (level == null || level.isClientSide) return;
        if (PowerState.redstoneOff(level, worldPosition)) return;
        int have = energy.getEnergyStored();
        if (have > 0) {
            int bank = (have + 1) / 2;
            int taken = energy.extractEnergy(bank, false);
            PowerState.pendingVaultFe += taken;
            PowerState.lifetimeVaultFe += taken;
        }
        float rpm = Math.abs(getSpeed());
        if (rpm > 0.01f) {
            long fromSu = (long) Math.floor(rpm * 8);
            PowerState.pendingVaultFe += fromSu;
            PowerState.lifetimeVaultFe += fromSu;
        }
    }
}
