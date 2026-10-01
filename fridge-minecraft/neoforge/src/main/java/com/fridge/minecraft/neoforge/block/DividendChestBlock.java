package com.fridge.minecraft.neoforge.block;

import com.fridge.minecraft.neoforge.FridgeNeoMod;
import com.fridge.minecraft.neoforge.PowerState;
import com.fridge.minecraft.neoforge.blockentity.DividendChestBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.EntityBlock;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.entity.BlockEntityTicker;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.Containers;
import net.minecraft.world.phys.BlockHitResult;
import org.jetbrains.annotations.Nullable;

public class DividendChestBlock extends Block implements EntityBlock {
    public DividendChestBlock(Properties properties) {
        super(properties);
    }

    @Override
    public BlockEntity newBlockEntity(BlockPos pos, BlockState state) {
        return new DividendChestBlockEntity(pos, state);
    }

    @Override
    public <T extends BlockEntity> BlockEntityTicker<T> getTicker(Level level, BlockState state, BlockEntityType<T> type) {
        return level.isClientSide ? null : (lvl, pos, st, be) -> {
            if (be instanceof DividendChestBlockEntity chest) chest.tick();
        };
    }

    @Override
    protected void onRemove(BlockState state, Level level, BlockPos pos, BlockState newState, boolean movedByPiston) {
        if (!state.is(newState.getBlock())) {
            if (level.getBlockEntity(pos) instanceof DividendChestBlockEntity chest) {
                Containers.dropContents(level, pos, chest);
            }
            super.onRemove(state, level, pos, newState, movedByPiston);
        }
    }

    @Override
    protected InteractionResult useWithoutItem(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
        if (level.isClientSide) return InteractionResult.SUCCESS;
        if (level.getBlockEntity(pos) instanceof DividendChestBlockEntity chest) {
            if (player.isShiftKeyDown()) {
                chest.drainRate = PowerState.cycleDrain(chest.drainRate);
                chest.setChanged();
                player.displayClientMessage(Component.literal("§6Dividend Chest §7burn §e" + chest.drainRate + "/15"), true);
                return InteractionResult.SUCCESS;
            }
            player.openMenu(chest);
        }
        return InteractionResult.SUCCESS;
    }
}
