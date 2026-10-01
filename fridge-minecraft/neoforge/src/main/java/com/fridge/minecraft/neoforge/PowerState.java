package com.fridge.minecraft.neoforge;

public final class PowerState {
    public static volatile int currentPowerLevel = 0;
    public static volatile int viewers = 0;
    public static volatile int cpm = 0;
    public static volatile int commandRate = 0;
    public static volatile double stockFactor = 1.0;
    public static volatile long pendingVaultFe = 0;
    public static volatile long lifetimeVaultFe = 0;
    public static volatile double pendingChestXp = 0;
    public static volatile double lifetimeChestXp = 0;
    public static volatile float chestDefaultValue = 0.05f;
    public static volatile boolean chestUseSmeltXp = true;
    public static final java.util.concurrent.ConcurrentHashMap<String, Float> chestItemValues =
            new java.util.concurrent.ConcurrentHashMap<>();
    public static volatile String vaultSymbol = "MINECRAF";
    public static volatile String chestSymbol = "MINECRAF";
    public static final java.util.concurrent.CopyOnWriteArrayList<String> dividendSymbols =
            new java.util.concurrent.CopyOnWriteArrayList<>(java.util.List.of("MINECRAF"));

    private PowerState() {}

    public static boolean redstoneOff(net.minecraft.world.level.Level level, net.minecraft.core.BlockPos pos) {
        return level != null && level.hasNeighborSignal(pos);
    }

    public static String cycleDividendSymbol(boolean vault) {
        if (dividendSymbols.isEmpty()) dividendSymbols.add("MINECRAF");
        String cur = vault ? vaultSymbol : chestSymbol;
        int idx = dividendSymbols.indexOf(cur);
        String next = dividendSymbols.get((idx + 1) % dividendSymbols.size());
        if (vault) vaultSymbol = next;
        else chestSymbol = next;
        return next;
    }

    public static int clamp(int level) {
        return Math.max(0, Math.min(15, level));
    }

    public static int effective(int manual) {
        return manual >= 0 ? clamp(manual) : clamp(currentPowerLevel);
    }

    public static int cycleManual(int current) {
        return cycleDrain(current);
    }

    public static int cycleDrain(int current) {
        if (current < 0) return 8;
        if (current >= 15) return 0;
        return current + 1;
    }

    public static double stockMul() {
        double f = stockFactor;
        if (f < 0.25) return 0.25;
        if (f > 3.0) return 3.0;
        return f;
    }
}
