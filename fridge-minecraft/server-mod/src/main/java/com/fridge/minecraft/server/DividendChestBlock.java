package com.fridge.minecraft.server;

import net.minecraft.block.Block;
import net.minecraft.block.BlockEntityProvider;
import net.minecraft.block.BlockState;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.block.entity.BlockEntityTicker;
import net.minecraft.block.entity.BlockEntityType;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.text.Text;
import net.minecraft.util.ActionResult;
import net.minecraft.util.ItemScatterer;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.World;
import org.jetbrains.annotations.Nullable;

/**
 * Hopper-fed chest that deletes smeltable items and banks their furnace
 * XP as dividend work for Stream Core.
 */
public class DividendChestBlock extends Block implements BlockEntityProvider {

    public DividendChestBlock(Settings settings) {
        super(settings);
    }

    @Override
    public @Nullable BlockEntity createBlockEntity(BlockPos pos, BlockState state) {
        return new DividendChestBlockEntity(pos, state);
    }

    @Override
    public <T extends BlockEntity> BlockEntityTicker<T> getTicker(World world, BlockState state, BlockEntityType<T> type) {
        return world.isClient ? null : (w, p, s, be) -> {
            if (be instanceof DividendChestBlockEntity chest) {
                chest.tick();
            }
        };
    }

    @Override
    public ActionResult onUse(BlockState state, World world, BlockPos pos, PlayerEntity player, BlockHitResult hit) {
        if (world.isClient) return ActionResult.SUCCESS;
        if (world.getBlockEntity(pos) instanceof DividendChestBlockEntity chest) {
            if (player.isSneaking()) {
                chest.drainRate = ChatDynamoBlockEntity.cycleDrain(chest.drainRate);
                chest.markDirty();
                player.sendMessage(Text.literal("§6Dividend Chest §7burn rate §e" + chest.drainRate + "/15 §7(Core decides what to eat)"), true);
                return ActionResult.SUCCESS;
            }
            player.openHandledScreen(chest);
            player.sendMessage(Text.literal(String.format(
                "§6Dividend Chest §7burn §e%d/15 §7— hopper / Create insert like a normal chest",
                chest.drainRate
            )), true);
        }
        return ActionResult.SUCCESS;
    }

    @Override
    public void onStateReplaced(BlockState state, World world, BlockPos pos, BlockState newState, boolean moved) {
        if (!state.isOf(newState.getBlock())) {
            BlockEntity be = world.getBlockEntity(pos);
            if (be instanceof DividendChestBlockEntity chest) {
                ItemScatterer.spawn(world, pos, chest);
            }
            super.onStateReplaced(state, world, pos, newState, moved);
        }
    }
}
