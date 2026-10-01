package com.fridge.minecraft.neoforge.blockentity;

import com.fridge.minecraft.neoforge.DeviceIndex;
import com.fridge.minecraft.neoforge.FridgeNeoMod;
import com.fridge.minecraft.neoforge.PowerState;
import net.neoforged.neoforge.items.IItemHandler;
import net.neoforged.neoforge.items.wrapper.InvWrapper;
import net.neoforged.neoforge.items.wrapper.SidedInvWrapper;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.HolderLookup;
import net.minecraft.core.NonNullList;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.world.ContainerHelper;
import net.minecraft.world.MenuProvider;
import net.minecraft.world.WorldlyContainer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ChestMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.RecipeType;
import net.minecraft.world.item.crafting.SingleRecipeInput;
import net.minecraft.world.item.crafting.SmeltingRecipe;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import org.jetbrains.annotations.Nullable;

public class DividendChestBlockEntity extends BlockEntity implements WorldlyContainer, MenuProvider {
    public static final int SIZE = 54;
    public int drainRate = 8;
    private static final int[] SLOTS = new int[SIZE];
    private final NonNullList<ItemStack> items = NonNullList.withSize(SIZE, ItemStack.EMPTY);
    public IItemHandler handler(Direction side) {
        if (side == null) return new InvWrapper(this);
        return new SidedInvWrapper(this, side);
    }

    static {
        for (int i = 0; i < SIZE; i++) SLOTS[i] = i;
    }

    public DividendChestBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeNeoMod.DIVIDEND_CHEST_BE.get(), pos, state);
    }

    @Override
    public void onLoad() {
        super.onLoad();
        DeviceIndex.track(this);
    }

    @Override
    public void setRemoved() {
        DeviceIndex.drop(this);
        super.setRemoved();
    }

    public void tick() {
        // Inventory only. Core burns via /api/devices/control.
    }

    private float valueFor(ItemStack stack) {
        String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().toLowerCase();
        Float listed = PowerState.chestItemValues.get(id);
        if (listed != null) return listed;
        if (PowerState.chestUseSmeltXp && level != null) {
            try {
                var rec = level.getRecipeManager().getRecipeFor(
                        RecipeType.SMELTING, new SingleRecipeInput(stack.copyWithCount(1)), level);
                if (rec.isPresent() && rec.get().value() instanceof SmeltingRecipe smelt) {
                    float xp = smelt.getExperience();
                    if (xp > 0) return xp;
                }
            } catch (Throwable ignored) {}
        }
        return PowerState.chestDefaultValue;
    }

    @Override
    public Component getDisplayName() {
        return Component.literal("Dividend Chest");
    }

    @Override
    public AbstractContainerMenu createMenu(int id, Inventory inv, Player player) {
        return ChestMenu.sixRows(id, inv, this);
    }

    @Override
    protected void saveAdditional(CompoundTag tag, HolderLookup.Provider registries) {
        super.saveAdditional(tag, registries);
        ContainerHelper.saveAllItems(tag, items, registries);
        tag.putInt("drainRate", drainRate);
    }

    @Override
    protected void loadAdditional(CompoundTag tag, HolderLookup.Provider registries) {
        super.loadAdditional(tag, registries);
        ContainerHelper.loadAllItems(tag, items, registries);
        if (tag.contains("drainRate")) drainRate = Math.max(0, Math.min(15, tag.getInt("drainRate")));
    }

    @Override
    public int[] getSlotsForFace(Direction side) {
        return SLOTS;
    }

    @Override
    public boolean canPlaceItemThroughFace(int slot, ItemStack stack, @Nullable Direction dir) {
        return true;
    }

    @Override
    public boolean canTakeItemThroughFace(int slot, ItemStack stack, Direction dir) {
        return true;
    }

    @Override
    public int getContainerSize() {
        return SIZE;
    }

    @Override
    public boolean isEmpty() {
        for (ItemStack s : items) if (!s.isEmpty()) return false;
        return true;
    }

    @Override
    public ItemStack getItem(int slot) {
        return items.get(slot);
    }

    @Override
    public ItemStack removeItem(int slot, int amount) {
        return ContainerHelper.removeItem(items, slot, amount);
    }

    @Override
    public ItemStack removeItemNoUpdate(int slot) {
        return ContainerHelper.takeItem(items, slot);
    }

    @Override
    public void setItem(int slot, ItemStack stack) {
        items.set(slot, stack);
        setChanged();
    }

    @Override
    public boolean stillValid(Player player) {
        return true;
    }

    @Override
    public void clearContent() {
        items.clear();
    }
}
