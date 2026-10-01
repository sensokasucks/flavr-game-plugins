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
import net.minecraft.world.World;
import org.jetbrains.annotations.Nullable;

/**
 * Eats TRE energy pushed into it and banks RF for Stream Core
 * to pay as dividends to holders of the configured ticker (default STEVE).
 */
public class DividendVaultBlock extends Block implements BlockEntityProvider {

    public DividendVaultBlock(Settings settings) {
        super(settings);
    }

    @Override
    public @Nullable BlockEntity createBlockEntity(BlockPos pos, BlockState state) {
        return new DividendVaultBlockEntity(pos, state);
    }

    @Override
    public <T extends BlockEntity> BlockEntityTicker<T> getTicker(World world, BlockState state, BlockEntityType<T> type) {
        return world.isClient ? null : (w, p, s, be) -> {
            if (be instanceof DividendVaultBlockEntity vault) {
                vault.tick();
            }
        };
    }

    @Override
    public ActionResult onUse(BlockState state, World world, BlockPos pos, PlayerEntity player, BlockHitResult hit) {
        if (!world.isClient) {
            player.sendMessage(Text.literal(String.format(
                "§6Dividend Vault §7pending §e%d RF §7— ticker is set in Stream Core Admin",
                FridgeServerMod.pendingVaultRf
            )), false);
        }
        return ActionResult.SUCCESS;
    }
}
