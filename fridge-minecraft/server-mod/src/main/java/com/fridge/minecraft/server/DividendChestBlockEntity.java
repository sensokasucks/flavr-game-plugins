package com.fridge.minecraft.server;

import net.minecraft.block.BlockState;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.entity.player.PlayerInventory;
import net.minecraft.inventory.Inventories;
import net.minecraft.inventory.SidedInventory;
import net.minecraft.item.ItemStack;
import net.minecraft.nbt.NbtCompound;
import net.minecraft.recipe.RecipeEntry;
import net.minecraft.recipe.RecipeType;
import net.minecraft.recipe.SmeltingRecipe;
import net.minecraft.recipe.input.SingleStackRecipeInput;
import net.minecraft.registry.Registries;
import net.minecraft.registry.RegistryWrapper;
import net.minecraft.screen.GenericContainerScreenHandler;
import net.minecraft.screen.NamedScreenHandlerFactory;
import net.minecraft.screen.ScreenHandler;
import net.minecraft.text.Text;
import net.minecraft.util.collection.DefaultedList;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import org.jetbrains.annotations.Nullable;

import java.util.Optional;

/**
 * Double-chest inventory. Hoppers / sided inserts work on every face.
 * Any item is accepted; work units come from Admin item values, then
 * furnace XP, then the default value.
 */
public class DividendChestBlockEntity extends BlockEntity implements SidedInventory, NamedScreenHandlerFactory {

    public static final int SIZE = 54;
    /** How aggressively Core may burn this chest (0 = storage only). */
    public int drainRate = 8;
    private final DefaultedList<ItemStack> items = DefaultedList.ofSize(SIZE, ItemStack.EMPTY);
    private static final int[] SLOTS;

    static {
        SLOTS = new int[SIZE];
        for (int i = 0; i < SIZE; i++) SLOTS[i] = i;
    }

    public DividendChestBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeServerMod.DIVIDEND_CHEST_BLOCK_ENTITY, pos, state);
    }

    public void tick() {
        // Inventory only. Core reads items via /api/devices and posts burns.
    }

    private float valueFor(ItemStack stack) {
        // Kept for debug / admin inspect; Core owns valuation.
        String id = Registries.ITEM.getId(stack.getItem()).toString().toLowerCase();
        Float listed = FridgeServerMod.chestItemValues.get(id);
        if (listed != null) return listed;
        if (FridgeServerMod.chestUseSmeltXp && world != null) {
            try {
                SingleStackRecipeInput probe = new SingleStackRecipeInput(stack.copyWithCount(1));
                Optional<RecipeEntry<SmeltingRecipe>> rec =
                        world.getRecipeManager().getFirstMatch(RecipeType.SMELTING, probe, world);
                if (rec.isPresent()) {
                    float xp = rec.get().value().getExperience();
                    if (xp > 0) return xp;
                }
            } catch (Throwable ignored) {}
        }
        return FridgeServerMod.chestDefaultValue;
    }

    @Override
    public Text getDisplayName() {
        return Text.literal("Dividend Chest");
    }

    @Override
    public ScreenHandler createMenu(int syncId, PlayerInventory inv, PlayerEntity player) {
        return GenericContainerScreenHandler.createGeneric9x6(syncId, inv, this);
    }

    @Override
    protected void writeNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup registryLookup) {
        super.writeNbt(nbt, registryLookup);
        Inventories.writeNbt(nbt, items, registryLookup);
        nbt.putInt("drainRate", drainRate);
    }

    @Override
    protected void readNbt(NbtCompound nbt, RegistryWrapper.WrapperLookup registryLookup) {
        super.readNbt(nbt, registryLookup);
        Inventories.readNbt(nbt, items, registryLookup);
        if (nbt.contains("drainRate")) drainRate = Math.max(0, Math.min(15, nbt.getInt("drainRate")));
    }

    @Override
    public int[] getAvailableSlots(Direction side) {
        return SLOTS;
    }

    @Override
    public boolean canInsert(int slot, ItemStack stack, @Nullable Direction dir) {
        return true;
    }

    @Override
    public boolean canExtract(int slot, ItemStack stack, Direction dir) {
        return true;
    }

    @Override
    public int size() {
        return SIZE;
    }

    @Override
    public boolean isEmpty() {
        for (ItemStack s : items) if (!s.isEmpty()) return false;
        return true;
    }

    @Override
    public ItemStack getStack(int slot) {
        return items.get(slot);
    }

    @Override
    public ItemStack removeStack(int slot, int amount) {
        return Inventories.splitStack(items, slot, amount);
    }

    @Override
    public ItemStack removeStack(int slot) {
        return Inventories.removeStack(items, slot);
    }

    @Override
    public void setStack(int slot, ItemStack stack) {
        items.set(slot, stack);
        if (stack.getCount() > getMaxCountPerStack()) {
            stack.setCount(getMaxCountPerStack());
        }
        markDirty();
    }

    @Override
    public boolean canPlayerUse(PlayerEntity player) {
        return true;
    }

    @Override
    public void clear() {
        items.clear();
    }
}
