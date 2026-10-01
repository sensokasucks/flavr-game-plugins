package com.fridge.minecraft.neoforge.block;

import com.fridge.minecraft.neoforge.FridgeNeoMod;
import com.fridge.minecraft.neoforge.PowerState;
import com.fridge.minecraft.neoforge.blockentity.ChatDynamoBlockEntity;
import com.simibubi.create.content.kinetics.base.RotatedPillarKineticBlock;
import com.simibubi.create.foundation.block.IBE;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.chat.Component;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.LevelReader;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

public class ChatDynamoBlock extends RotatedPillarKineticBlock implements IBE<ChatDynamoBlockEntity> {
    public ChatDynamoBlock(Properties properties) {
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
    public Class<ChatDynamoBlockEntity> getBlockEntityClass() {
        return ChatDynamoBlockEntity.class;
    }

    @Override
    public BlockEntityType<? extends ChatDynamoBlockEntity> getBlockEntityType() {
        return FridgeNeoMod.CHAT_DYNAMO_BE.get();
    }

    @Override
    public boolean isSignalSource(BlockState state) {
        return true;
    }

    @Override
    public int getSignal(BlockState state, BlockGetter level, BlockPos pos, Direction dir) {
        if (level.getBlockEntity(pos) instanceof ChatDynamoBlockEntity be) return be.level();
        return PowerState.currentPowerLevel;
    }

    @Override
    protected InteractionResult useWithoutItem(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
        if (level.isClientSide) return InteractionResult.SUCCESS;
        if (!(level.getBlockEntity(pos) instanceof ChatDynamoBlockEntity be)) return InteractionResult.SUCCESS;
        if (player.isShiftKeyDown()) {
            be.drainRate = PowerState.cycleDrain(be.drainRate);
            be.setChanged();
            be.updateGeneratedRotation();
        }
        player.displayClientMessage(Component.literal(String.format(
                "§aChat Dynamo §7drain §e%d/15 §7→ Core FE/t §e%d §7RPM §e%.0f  sneak = drain (no free power)",
                be.drainRate, be.generationPerTick(), be.getGeneratedSpeed()
        )), false);
        return InteractionResult.SUCCESS;
    }
}
