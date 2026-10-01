package com.fridge.minecraft.server;

import net.minecraft.block.entity.BlockEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.util.math.BlockPos;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Live Fridge blocks. The mod only exposes these; Stream Core decides
 * generation, burns, symbols, and market drain.
 */
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
        if (be == null || be.getWorld() == null) return null;
        String dim = be.getWorld().getRegistryKey().getValue().toString();
        BlockPos p = be.getPos();
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
            if (be == null || be.isRemoved() || be.getWorld() == null) {
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
        int drain = drainRate(be);
        long energy = energy(be);
        long cap = capacity(be);
        boolean off = be.getWorld() != null && be.getWorld().isReceivingRedstonePower(be.getPos());
        sb.append("{\"id\":\"").append(esc(id)).append('"');
        sb.append(",\"kind\":\"").append(kind(be)).append('"');
        sb.append(",\"drainRate\":").append(drain);
        sb.append(",\"energy\":").append(energy);
        sb.append(",\"capacity\":").append(cap);
        sb.append(",\"orderedRf\":").append(orderedRf(be));
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
        for (int i = 0; i < chest.size(); i++) {
            ItemStack stack = chest.getStack(i);
            if (stack.isEmpty()) continue;
            if (!first) sb.append(',');
            first = false;
            String itemId = Registries.ITEM.getId(stack.getItem()).toString().toLowerCase(Locale.ROOT);
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
        if (be instanceof ChatDynamoBlockEntity d) return d.energyStorage.amount;
        if (be instanceof ChatKineticBlockEntity k) return k.energyStorage.amount;
        if (be instanceof DividendVaultBlockEntity v) return v.energyStorage.amount;
        return 0;
    }

    public static long capacity(BlockEntity be) {
        if (be instanceof ChatDynamoBlockEntity) return ChatDynamoBlockEntity.CAPACITY;
        if (be instanceof ChatKineticBlockEntity) return ChatKineticBlockEntity.CAPACITY;
        if (be instanceof DividendVaultBlockEntity) return DividendVaultBlockEntity.CAPACITY;
        return 0;
    }

    public static long orderedRf(BlockEntity be) {
        if (be instanceof ChatDynamoBlockEntity d) return d.orderedRf;
        if (be instanceof ChatKineticBlockEntity k) return k.orderedRf;
        return 0;
    }

    public static void applyOrder(String id, long generateRf, List<int[]> consume) {
        BlockEntity be = LIVE.get(id);
        if (be == null || be.isRemoved()) return;
        if (be.getWorld() instanceof ServerWorld sw) {
            sw.getServer().execute(() -> applyOnThread(be, generateRf, consume));
        } else {
            applyOnThread(be, generateRf, consume);
        }
    }

    private static void applyOnThread(BlockEntity be, long generateRf, List<int[]> consume) {
        if (be instanceof ChatDynamoBlockEntity d) {
            d.orderedRf = Math.max(0, generateRf);
            d.markDirty();
        } else if (be instanceof ChatKineticBlockEntity k) {
            k.orderedRf = Math.max(0, generateRf);
            k.markDirty();
        } else if (be instanceof DividendChestBlockEntity chest && consume != null) {
            for (int[] pair : consume) {
                if (pair == null || pair.length < 2) continue;
                int slot = pair[0];
                int count = pair[1];
                if (slot < 0 || slot >= chest.size() || count <= 0) continue;
                chest.removeStack(slot, count);
            }
            chest.markDirty();
        }
    }

    static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    static List<int[]> parseConsume(String jsonChunk) {
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
