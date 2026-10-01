package com.fridge.minecraft.neoforge.block;

import com.fridge.minecraft.neoforge.FridgeNeoMod;
import com.fridge.minecraft.neoforge.PowerState;
import com.fridge.minecraft.neoforge.blockentity.DividendVaultBlockEntity;
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

public class DividendVaultBlock extends RotatedPillarKineticBlock implements IBE<DividendVaultBlockEntity> {
    public DividendVaultBlock(Properties properties) {
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
    public Class<DividendVaultBlockEntity> getBlockEntityClass() {
        return DividendVaultBlockEntity.class;
    }

    @Override
    public BlockEntityType<? extends DividendVaultBlockEntity> getBlockEntityType() {
        return FridgeNeoMod.DIVIDEND_VAULT_BE.get();
    }

    @Override
    protected InteractionResult useWithoutItem(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
        if (!level.isClientSide) {
            player.displayClientMessage(Component.literal(
                    "§6Dividend Vault §7pending §e" + PowerState.pendingVaultFe + " FE §7— ticker is set in Stream Core"
            ), false);
        }
        return InteractionResult.SUCCESS;
    }
}
