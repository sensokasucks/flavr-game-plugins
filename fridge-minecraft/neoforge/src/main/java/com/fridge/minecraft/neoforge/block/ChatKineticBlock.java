package com.fridge.minecraft.neoforge.block;

import com.fridge.minecraft.neoforge.FridgeNeoMod;
import com.fridge.minecraft.neoforge.PowerState;
import com.fridge.minecraft.neoforge.blockentity.ChatKineticBlockEntity;
import com.simibubi.create.content.kinetics.base.RotatedPillarKineticBlock;
import com.simibubi.create.foundation.block.IBE;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.chat.Component;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.LevelReader;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

public class ChatKineticBlock extends RotatedPillarKineticBlock implements IBE<ChatKineticBlockEntity> {
    public ChatKineticBlock(Properties properties) {
        super(properties);
    }

    @Override
    public boolean hasShaftTowards(LevelReader world, BlockPos pos, BlockState state, Direction face) {
        return face.getAxis() == state.getValue(AXIS);
    }

    @Override
    public Direction.Axis getRotationAxis(BlockState state) {
        return state.getValue(AXIS);
    }

    @Override
    public Class<ChatKineticBlockEntity> getBlockEntityClass() {
        return ChatKineticBlockEntity.class;
    }

    @Override
    public BlockEntityType<? extends ChatKineticBlockEntity> getBlockEntityType() {
        return FridgeNeoMod.CHAT_KINETIC_BE.get();
    }

    @Override
    protected InteractionResult useWithoutItem(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
        if (level.isClientSide) return InteractionResult.SUCCESS;
        if (!(level.getBlockEntity(pos) instanceof ChatKineticBlockEntity be)) return InteractionResult.SUCCESS;
        if (player.isShiftKeyDown()) {
            be.drainRate = PowerState.cycleDrain(be.drainRate);
            be.setChanged();
            be.updateGeneratedRotation();
        }
        player.displayClientMessage(Component.literal(String.format(
                "§bChat Kinetic §7drain §e%d/15 §7→ §e%.0f RPM §7Core FE/t §e%d",
                be.drainRate, be.getGeneratedSpeed(), be.orderedRf
        )), false);
        return InteractionResult.SUCCESS;
    }
}
