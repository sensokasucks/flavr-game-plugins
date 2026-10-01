package com.fridge.minecraft.server;

import net.minecraft.block.Block;
import net.minecraft.block.BlockEntityProvider;
import net.minecraft.block.BlockState;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.block.entity.BlockEntityTicker;
import net.minecraft.block.entity.BlockEntityType;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.text.Text;
import net.minecraft.util.ActionResult;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import net.minecraft.world.BlockView;
import net.minecraft.world.World;
import org.jetbrains.annotations.Nullable;

/**
 * Chat Dynamo
 * ------------
 * Primary output: RF-compatible energy (Team Reborn Energy / TRE).
 * Generation rate scales with stream metrics (viewers + CPM + commands)
 * pushed by Fridge Stream Core.  powerLevel 0–15 → 0 … MAX_RF_PER_TICK.
 *
 * Secondary output: still emits redstone signal strength = powerLevel
 * so simple redstone contraptions keep working without any energy mod.
 *
 * Right-click to see current generation rate and metrics.
 *
 * Requires: teamreborn:energy (see BUILD.md)
 */
public class ChatDynamoBlock extends Block implements BlockEntityProvider {

    public ChatDynamoBlock(Settings settings) {
        super(settings);
    }

    @Override
    public @Nullable BlockEntity createBlockEntity(BlockPos pos, BlockState state) {
        return new ChatDynamoBlockEntity(pos, state);
    }

    @Override
    public <T extends BlockEntity> BlockEntityTicker<T> getTicker(World world, BlockState state, BlockEntityType<T> type) {
        return world.isClient ? null : (w, p, s, be) -> {
            if (be instanceof ChatDynamoBlockEntity dynamo) {
                dynamo.tick();
            }
        };
    }

    // ----- redstone (kept as secondary / fallback output) -----

    @Override
    public boolean emitsRedstonePower(BlockState state) {
        return true;
    }

    @Override
    public int getWeakRedstonePower(BlockState state, BlockView world, BlockPos pos, Direction direction) {
        if (world.getBlockEntity(pos) instanceof ChatDynamoBlockEntity be) return be.level();
        return FridgeServerMod.currentPowerLevel;
    }

    @Override
    public int getStrongRedstonePower(BlockState state, BlockView world, BlockPos pos, Direction direction) {
        return getWeakRedstonePower(state, world, pos, direction);
    }

    @Override
    public ActionResult onUse(BlockState state, World world, BlockPos pos, PlayerEntity player, BlockHitResult hit) {
        if (world.isClient) return ActionResult.SUCCESS;
        if (!(world.getBlockEntity(pos) instanceof ChatDynamoBlockEntity be)) return ActionResult.SUCCESS;
        if (player.isSneaking()) {
            be.drainRate = ChatDynamoBlockEntity.cycleDrain(be.drainRate);
            be.markDirty();
            world.updateNeighbors(pos, this);
        }
        player.sendMessage(Text.literal(String.format(
            "§aChat Dynamo §7drain §e%d/15 §7→ Core allows §e%d FE/t §7stored §e%d§7/%d  sneak = drain rate (no free power)",
            be.drainRate,
            be.generationPerTick(),
            be.energyStorage.amount,
            ChatDynamoBlockEntity.CAPACITY
        )), false);
        return ActionResult.SUCCESS;
    }

    public static void notifyNeighbors(World world, BlockPos pos) {
        if (world instanceof ServerWorld sw) {
            sw.updateNeighbors(pos, FridgeServerMod.CHAT_DYNAMO);
        }
    }
}
