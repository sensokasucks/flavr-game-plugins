package com.fridge.minecraft.neoforge;

import com.fridge.minecraft.neoforge.blockentity.ChatDynamoBlockEntity;
import com.fridge.minecraft.neoforge.blockentity.ChatKineticBlockEntity;
import com.fridge.minecraft.neoforge.blockentity.DividendChestBlockEntity;
import com.fridge.minecraft.neoforge.blockentity.DividendVaultBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.entity.BlockEntity;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Placed Fridge blocks. Core decides FE mint and item burns. */
public final class DeviceIndex {
    private static final ConcurrentHashMap<String, BlockEntity> LIVE = new ConcurrentHashMap<>();

    private DeviceIndex() {}

    public static String kind(BlockEntity be) {
        if (be instanceof ChatDynamoBlockEntity) return "dynamo";
        if (be instanceof ChatKineticBlockEntity) return "kinetic";
        if (be instanceof DividendVaultBlockEntity) return "vault";
        if (be instanceof DividendChestBlockEntity) return "chest";
        return "unknown";
    }

    public static String id(BlockEntity be) {
        if (be == null || be.getLevel() == null) return null;
        String dim = be.getLevel().dimension().location().toString();
        BlockPos p = be.getBlockPos();
        return kind(be) + "@" + dim + ":" + p.getX() + "," + p.getY() + "," + p.getZ();
    }

    public static void track(BlockEntity be) {
        String id = id(be);
        if (id != null && !"unknown".equals(kind(be))) LIVE.put(id, be);
    }

    public static void drop(BlockEntity be) {
        String id = id(be);
        if (id != null) LIVE.remove(id);
    }

    public static String snapshotJson() {
        StringBuilder sb = new StringBuilder(256);
        sb.append("{\"devices\":[");
        boolean first = true;
        for (Map.Entry<String, BlockEntity> e : LIVE.entrySet()) {
            BlockEntity be = e.getValue();
            if (be == null || be.isRemoved() || be.getLevel() == null) {
                LIVE.remove(e.getKey(), be);
                continue;
            }
            if (!first) sb.append(',');
            first = false;
            appendDevice(sb, e.getKey(), be);
        }
        sb.append("]}");
        return sb.toString();
    }

    private static void appendDevice(StringBuilder sb, String id, BlockEntity be) {
        sb.append("{\"id\":\"").append(esc(id)).append('"');
        sb.append(",\"kind\":\"").append(kind(be)).append('"');
        sb.append(",\"drainRate\":").append(drainRate(be));
        sb.append(",\"energy\":").append(energy(be));
        sb.append(",\"capacity\":").append(capacity(be));
        sb.append(",\"orderedRf\":").append(orderedRf(be));
        sb.append(",\"rpm\":").append(rpm(be));
        boolean off = be.getLevel() != null && be.getLevel().hasNeighborSignal(be.getBlockPos());
        sb.append(",\"redstoneOff\":").append(off);
        if (be instanceof DividendChestBlockEntity chest) {
            sb.append(",\"items\":");
            appendItems(sb, chest);
        }
        sb.append('}');
    }

    private static void appendItems(StringBuilder sb, DividendChestBlockEntity chest) {
        sb.append('[');
        boolean first = true;
        for (int i = 0; i < chest.getContainerSize(); i++) {
            ItemStack stack = chest.getItem(i);
            if (stack.isEmpty()) continue;
            if (!first) sb.append(',');
            first = false;
            String itemId = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().toLowerCase(Locale.ROOT);
            sb.append("{\"slot\":").append(i)
                    .append(",\"id\":\"").append(esc(itemId)).append('"')
                    .append(",\"count\":").append(stack.getCount())
                    .append('}');
        }
        sb.append(']');
    }

    public static int drainRate(BlockEntity be) {
        if (be instanceof ChatDynamoBlockEntity d) return Math.max(0, d.drainRate);
        if (be instanceof ChatKineticBlockEntity k) return Math.max(0, k.drainRate);
        if (be instanceof DividendChestBlockEntity c) return Math.max(0, c.drainRate);
        return 0;
    }

    public static long energy(BlockEntity be) {
        if (be instanceof ChatDynamoBlockEntity d) return d.energy.getEnergyStored();
        if (be instanceof ChatKineticBlockEntity k) return k.energy.getEnergyStored();
        if (be instanceof DividendVaultBlockEntity v) return v.energy.getEnergyStored();
        return 0;
    }

    public static long capacity(BlockEntity be) {
        return 50_000;
    }

    public static long orderedRf(BlockEntity be) {
        if (be instanceof ChatDynamoBlockEntity d) return d.orderedRf;
        if (be instanceof ChatKineticBlockEntity k) return k.orderedRf;
        return 0;
    }

    public static float rpm(BlockEntity be) {
        if (be instanceof ChatKineticBlockEntity k) return k.getGeneratedSpeed();
        if (be instanceof ChatDynamoBlockEntity d) return d.getGeneratedSpeed();
        if (be instanceof DividendVaultBlockEntity v) return Math.abs(v.getSpeed());
        return 0f;
    }

    public static void applyOrder(String id, long generateRf, List<int[]> consume) {
        BlockEntity be = LIVE.get(id);
        if (be == null || be.isRemoved()) return;
        if (be.getLevel() instanceof ServerLevel sl) {
            sl.getServer().execute(() -> applyOnThread(be, generateRf, consume));
        } else {
            applyOnThread(be, generateRf, consume);
        }
    }

    private static void applyOnThread(BlockEntity be, long generateRf, List<int[]> consume) {
        if (be instanceof ChatDynamoBlockEntity d) {
            d.orderedRf = Math.max(0, generateRf);
            d.setChanged();
            d.updateGeneratedRotation();
        } else if (be instanceof ChatKineticBlockEntity k) {
            k.orderedRf = Math.max(0, generateRf);
            k.setChanged();
            k.updateGeneratedRotation();
        } else if (be instanceof DividendChestBlockEntity chest && consume != null) {
            for (int[] pair : consume) {
                if (pair == null || pair.length < 2) continue;
                int slot = pair[0];
                int count = pair[1];
                if (slot < 0 || slot >= chest.getContainerSize() || count <= 0) continue;
                chest.removeItem(slot, count);
            }
            chest.setChanged();
        }
    }

    static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    public static List<int[]> parseConsume(String jsonChunk) {
        List<int[]> out = new ArrayList<>();
        int idx = 0;
        while (true) {
            int slotAt = jsonChunk.indexOf("\"slot\"", idx);
            if (slotAt < 0) break;
            int slot = readIntAfterColon(jsonChunk, slotAt);
            int countAt = jsonChunk.indexOf("\"count\"", slotAt);
            int count = countAt > 0 ? readIntAfterColon(jsonChunk, countAt) : 0;
            if (slot >= 0 && count > 0) out.add(new int[]{slot, count});
            idx = slotAt + 6;
        }
        return out;
    }

    static int readIntAfterColon(String json, int keyAt) {
        int colon = json.indexOf(':', keyAt);
        if (colon < 0) return 0;
        int i = colon + 1;
        while (i < json.length() && !Character.isDigit(json.charAt(i)) && json.charAt(i) != '-') i++;
        int j = i;
        while (j < json.length() && (Character.isDigit(json.charAt(j)) || json.charAt(j) == '-')) j++;
        try {
            return Integer.parseInt(json.substring(i, j));
        } catch (Exception e) {
            return 0;
        }
    }
}
