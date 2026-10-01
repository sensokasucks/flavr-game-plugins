package com.fridge.minecraft.server;

import net.fabricmc.fabric.api.transfer.v1.transaction.Transaction;
import net.minecraft.block.BlockState;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import team.reborn.energy.api.EnergyStorage;
import team.reborn.energy.api.EnergyStorageUtil;
import team.reborn.energy.api.base.SimpleEnergyStorage;

/**
 * Sink: machines / dynamos push RF in. Each tick we delete stored energy
 * and add it to the global pending vault pool Core polls.
 */
public class DividendVaultBlockEntity extends BlockEntity {

    public static final long CAPACITY = 100_000L;

    /** Accept FE in; also allow extract so the vault can feed machines. */
    public final SimpleEnergyStorage energyStorage = new SimpleEnergyStorage(
            CAPACITY, Long.MAX_VALUE, Long.MAX_VALUE
    ) {
        @Override
        protected void onFinalCommit() {
            markDirty();
        }
    };

    public DividendVaultBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeServerMod.DIVIDEND_VAULT_BLOCK_ENTITY, pos, state);
    }

    public void tick() {
        if (world == null || world.isClient) return;
        if (PowerIo.redstoneOff(world, pos)) return;

        for (Direction dir : Direction.values()) {
            if (energyStorage.amount >= CAPACITY) break;
            EnergyStorage source = EnergyStorage.SIDED.find(world, pos.offset(dir), dir.getOpposite());
            if (source == null || source == energyStorage || !source.supportsExtraction()) continue;
            EnergyStorageUtil.move(source, energyStorage, CAPACITY - energyStorage.amount, null);
        }

        CreateCompat.harvestToFe(world, pos, energyStorage, CAPACITY - energyStorage.amount);

        long have = energyStorage.amount;
        if (have > 0) {
            // Bank half for dividends, keep half available to extract (output FE)
            long bank = (have + 1) / 2;
            try (Transaction tx = Transaction.openOuter()) {
                long taken = energyStorage.extract(bank, tx);
                tx.commit();
                FridgeServerMod.pendingVaultRf += taken;
                FridgeServerMod.lifetimeVaultRf += taken;
            }
        }

        for (Direction dir : Direction.values()) {
            if (energyStorage.amount <= 0) break;
            EnergyStorage target = EnergyStorage.SIDED.find(world, pos.offset(dir), dir.getOpposite());
            if (target == null || target == energyStorage || !target.supportsInsertion()) continue;
            EnergyStorageUtil.move(energyStorage, target, energyStorage.amount, null);
        }
    }
}
