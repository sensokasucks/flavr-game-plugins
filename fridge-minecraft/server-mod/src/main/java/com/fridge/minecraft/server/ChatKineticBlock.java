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
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import net.minecraft.world.BlockView;
import net.minecraft.world.World;
import org.jetbrains.annotations.Nullable;

/**
 * Chat Kinetic Source (Create-compatible rotational force)
 * -------------------------------------------------------
 * A second block that turns the same stream metrics into rotational
 * force for the Create mod.
 *
 * When Create is present this block acts as a kinetic source:
 *   - Generated speed (RPM) scales with powerLevel
 *   - Stress capacity (SU) also scales with powerLevel
 *
 * Implementation notes (see ChatKineticBlockEntity):
 *   - Extends Create’s GeneratingKineticBlockEntity when the Create
 *     dependency is on the classpath.
 *   - The code below is written so the mod still compiles without Create;
 *     the kinetic behaviour is activated only when Create classes are found.
 *
 * Right-click shows current RPM / SU estimate.
 */
public class ChatKineticBlock extends Block implements BlockEntityProvider {

    public ChatKineticBlock(Settings settings) {
        super(settings);
    }

    @Override
    public @Nullable BlockEntity createBlockEntity(BlockPos pos, BlockState state) {
        return new ChatKineticBlockEntity(pos, state);
    }

    @Override
    public <T extends BlockEntity> BlockEntityTicker<T> getTicker(World world, BlockState state, BlockEntityType<T> type) {
        // Kinetic network is driven by Create; we only need a light tick for UI data
        return world.isClient ? null : (w, p, s, be) -> {
            if (be instanceof ChatKineticBlockEntity kinetic) {
                kinetic.serverTick();
            }
        };
    }

    @Override
    public boolean emitsRedstonePower(BlockState state) {
        return true;
    }

    @Override
    public int getWeakRedstonePower(BlockState state, BlockView world, BlockPos pos, Direction direction) {
        if (world.getBlockEntity(pos) instanceof ChatKineticBlockEntity be) return be.level();
        return FridgeServerMod.currentPowerLevel;
    }

    @Override
    public int getStrongRedstonePower(BlockState state, BlockView world, BlockPos pos, Direction direction) {
        return getWeakRedstonePower(state, world, pos, direction);
    }

    @Override
    public ActionResult onUse(BlockState state, World world, BlockPos pos, PlayerEntity player, BlockHitResult hit) {
        if (world.isClient) return ActionResult.SUCCESS;
        if (!(world.getBlockEntity(pos) instanceof ChatKineticBlockEntity be)) return ActionResult.SUCCESS;
        if (player.isSneaking()) {
            be.drainRate = ChatDynamoBlockEntity.cycleDrain(be.drainRate);
            be.markDirty();
            world.updateNeighbors(pos, this);
        }
        player.sendMessage(Text.literal(String.format(
            "§bChat Kinetic §7drain §e%d/15 §7→ §e%.0f RPM §7Core FE/t §e%d  sneak = drain rate",
            be.drainRate,
            be.currentRpm(),
            be.orderedRf
        )), false);
        return ActionResult.SUCCESS;
    }
}
