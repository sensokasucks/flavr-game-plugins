package com.fridge.minecraft.server;

import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.object.builder.v1.block.FabricBlockSettings;
import net.fabricmc.fabric.api.object.builder.v1.block.entity.FabricBlockEntityTypeBuilder;
import net.minecraft.block.Block;
import net.minecraft.block.Blocks;
import net.minecraft.block.entity.BlockEntityType;
import net.fabricmc.fabric.api.itemgroup.v1.FabricItemGroup;
import net.minecraft.item.BlockItem;
import net.minecraft.item.Item;
import net.minecraft.item.ItemGroup;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.text.Text;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.command.ServerCommandSource;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.util.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import team.reborn.energy.api.EnergyStorage;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.Executors;

/**
 * Server-side (or integrated) Fabric mod.
 *
 * - HTTP API for the Stream Core (execute commands + push metrics)
 * - Chat Dynamo  → RF energy (Team Reborn Energy) + redstone fallback
 * - Chat Kinetic → rotational force for Create (see ChatKineticBlockEntity notes)
 */
public class FridgeServerMod implements ModInitializer {
    public static final Logger LOGGER = LoggerFactory.getLogger("fridge-minecraft-server");
    public static final int PORT = Integer.getInteger("fridge.server.port", 3853);

    // ----- blocks -----
    public static final Block CHAT_DYNAMO = new ChatDynamoBlock(
        FabricBlockSettings.copyOf(Blocks.REDSTONE_BLOCK).strength(2.5f)
    );
    public static final Block CHAT_KINETIC = new ChatKineticBlock(
        FabricBlockSettings.copyOf(Blocks.IRON_BLOCK).strength(3.0f)
    );
    public static final Block DIVIDEND_VAULT = new DividendVaultBlock(
        FabricBlockSettings.copyOf(Blocks.GOLD_BLOCK).strength(3.0f)
    );
    public static final Block DIVIDEND_CHEST = new DividendChestBlock(
        FabricBlockSettings.copyOf(Blocks.CHEST).strength(2.5f)
    );

    public static final Item CHAT_DYNAMO_ITEM = new BlockItem(CHAT_DYNAMO, new Item.Settings());
    public static final Item CHAT_KINETIC_ITEM = new BlockItem(CHAT_KINETIC, new Item.Settings());
    public static final Item DIVIDEND_VAULT_ITEM = new BlockItem(DIVIDEND_VAULT, new Item.Settings());
    public static final Item DIVIDEND_CHEST_ITEM = new BlockItem(DIVIDEND_CHEST, new Item.Settings());

    public static final ItemGroup FRIDGE_TAB = FabricItemGroup.builder()
        .icon(() -> new ItemStack(CHAT_DYNAMO_ITEM))
        .displayName(Text.translatable("itemGroup.fridge_minecraft.fridge"))
        .entries((context, entries) -> {
            entries.add(CHAT_DYNAMO_ITEM);
            entries.add(CHAT_KINETIC_ITEM);
            entries.add(DIVIDEND_VAULT_ITEM);
            entries.add(DIVIDEND_CHEST_ITEM);
        })
        .build();

    // ----- block entities -----
    public static BlockEntityType<ChatDynamoBlockEntity> CHAT_DYNAMO_BLOCK_ENTITY;
    public static BlockEntityType<ChatKineticBlockEntity> CHAT_KINETIC_BLOCK_ENTITY;
    public static BlockEntityType<DividendVaultBlockEntity> DIVIDEND_VAULT_BLOCK_ENTITY;
    public static BlockEntityType<DividendChestBlockEntity> DIVIDEND_CHEST_BLOCK_ENTITY;

    // Shared metrics written by the HTTP handler
    public static volatile int currentPowerLevel = 0;
    public static volatile int viewers = 0;
    public static volatile int cpm = 0;
    public static volatile int commandRate = 0;
    /** Chat Dynamo multiplier from Fridge Market prices (1.0 = base). */
    public static volatile double stockFactor = 1.0;
    public static volatile long pendingVaultRf = 0;
    public static volatile long lifetimeVaultRf = 0;
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

    public static String cycleDividendSymbol(boolean vault) {
        if (dividendSymbols.isEmpty()) dividendSymbols.add("MINECRAF");
        String cur = vault ? vaultSymbol : chestSymbol;
        int idx = dividendSymbols.indexOf(cur);
        String next = dividendSymbols.get((idx + 1) % dividendSymbols.size());
        if (vault) vaultSymbol = next;
        else chestSymbol = next;
        return next;
    }

    private static MinecraftServer serverInstance;

    @Override
    public void onInitialize() {
        LOGGER.info("Fridge Minecraft Server Interactions starting");

        // Register blocks + items
        Identifier dynamoId = Identifier.of("fridge_minecraft", "chat_dynamo");
        Identifier kineticId = Identifier.of("fridge_minecraft", "chat_kinetic");
        Identifier vaultId = Identifier.of("fridge_minecraft", "dividend_vault");
        Identifier chestId = Identifier.of("fridge_minecraft", "dividend_chest");

        Registry.register(Registries.BLOCK, dynamoId, CHAT_DYNAMO);
        Registry.register(Registries.ITEM, dynamoId, CHAT_DYNAMO_ITEM);

        Registry.register(Registries.BLOCK, kineticId, CHAT_KINETIC);
        Registry.register(Registries.ITEM, kineticId, CHAT_KINETIC_ITEM);

        Registry.register(Registries.BLOCK, vaultId, DIVIDEND_VAULT);
        Registry.register(Registries.ITEM, vaultId, DIVIDEND_VAULT_ITEM);

        Registry.register(Registries.BLOCK, chestId, DIVIDEND_CHEST);
        Registry.register(Registries.ITEM, chestId, DIVIDEND_CHEST_ITEM);

        Registry.register(
            Registries.ITEM_GROUP,
            Identifier.of("fridge_minecraft", "fridge"),
            FRIDGE_TAB
        );

        // Block entities
        CHAT_DYNAMO_BLOCK_ENTITY = Registry.register(
            Registries.BLOCK_ENTITY_TYPE,
            dynamoId,
            FabricBlockEntityTypeBuilder.create(ChatDynamoBlockEntity::new, CHAT_DYNAMO).build()
        );
        CHAT_KINETIC_BLOCK_ENTITY = Registry.register(
            Registries.BLOCK_ENTITY_TYPE,
            kineticId,
            FabricBlockEntityTypeBuilder.create(ChatKineticBlockEntity::new, CHAT_KINETIC).build()
        );
        DIVIDEND_VAULT_BLOCK_ENTITY = Registry.register(
            Registries.BLOCK_ENTITY_TYPE,
            vaultId,
            FabricBlockEntityTypeBuilder.create(DividendVaultBlockEntity::new, DIVIDEND_VAULT).build()
        );
        DIVIDEND_CHEST_BLOCK_ENTITY = Registry.register(
            Registries.BLOCK_ENTITY_TYPE,
            chestId,
            FabricBlockEntityTypeBuilder.create(DividendChestBlockEntity::new, DIVIDEND_CHEST).build()
        );

        // Expose energy storage to the world (TRE sided lookup)
        EnergyStorage.SIDED.registerForBlockEntity(
            (be, direction) -> be.energyStorage,
            CHAT_DYNAMO_BLOCK_ENTITY
        );
        EnergyStorage.SIDED.registerForBlockEntity(
            (be, direction) -> be.energyStorage,
            CHAT_KINETIC_BLOCK_ENTITY
        );
        EnergyStorage.SIDED.registerForBlockEntity(
            (be, direction) -> be.energyStorage,
            DIVIDEND_VAULT_BLOCK_ENTITY
        );
        // Create funnels / belts / hoppers-from-other-mods use Fabric Transfer
        net.fabricmc.fabric.api.transfer.v1.item.ItemStorage.SIDED.registerForBlockEntity(
            (be, direction) -> net.fabricmc.fabric.api.transfer.v1.item.InventoryStorage.of(be, direction),
            DIVIDEND_CHEST_BLOCK_ENTITY
        );

        net.fabricmc.fabric.api.event.lifecycle.v1.ServerBlockEntityEvents.BLOCK_ENTITY_LOAD.register((be, world) -> DeviceIndex.track(be));
        net.fabricmc.fabric.api.event.lifecycle.v1.ServerBlockEntityEvents.BLOCK_ENTITY_UNLOAD.register((be, world) -> DeviceIndex.drop(be));

        net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> {
            dispatcher.register(
                net.minecraft.server.command.CommandManager.literal("fridgepower")
                    .requires(src -> src.hasPermissionLevel(2))
                    .then(net.minecraft.server.command.CommandManager.argument(
                            "level",
                            com.mojang.brigadier.arguments.IntegerArgumentType.integer(0, 15)
                    ).executes(ctx -> {
                        currentPowerLevel = com.mojang.brigadier.arguments.IntegerArgumentType.getInteger(ctx, "level");
                        ctx.getSource().sendFeedback(
                            () -> Text.literal("Fridge power level set to " + currentPowerLevel + "/15"),
                            true
                        );
                        return currentPowerLevel;
                    }))
            );
        });

        // Capture server instance
        net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents.SERVER_STARTED.register(server -> {
            serverInstance = server;
            startHttpServer();
        });
        net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents.SERVER_STOPPED.register(server -> {
            serverInstance = null;
        });
    }

    private void startHttpServer() {
        try {
            HttpServer http = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
            http.createContext("/api/execute", this::handleExecute);
            http.createContext("/api/metrics", this::handleMetrics);
            http.createContext("/api/market", this::handleMarket);
            http.createContext("/api/market/ack", this::handleMarketAck);
            http.createContext("/api/devices", this::handleDevices);
            http.createContext("/api/devices/control", this::handleDeviceControl);
            http.createContext("/api/health", ex -> respond(ex, 200, "{\"ok\":true}"));
            http.setExecutor(Executors.newFixedThreadPool(2));
            http.start();
            LOGGER.info("HTTP API listening on http://127.0.0.1:{}", PORT);
        } catch (IOException e) {
            LOGGER.error("Failed to start HTTP server", e);
        }
    }

    private void handleExecute(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if (!"POST".equals(ex.getRequestMethod())) {
            ex.sendResponseHeaders(405, -1);
            return;
        }
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        String command = extractJsonString(body, "command");
        String playerName = extractJsonString(body, "player");

        if (command == null || command.isBlank()) {
            respond(ex, 400, "{\"success\":false,\"error\":\"missing command\"}");
            return;
        }
        if (serverInstance == null) {
            respond(ex, 503, "{\"success\":false,\"error\":\"server not ready\"}");
            return;
        }

        serverInstance.execute(() -> {
            try {
                ServerCommandSource source = serverInstance.getCommandSource().withLevel(4).withSilent();
                ServerPlayerEntity player = null;
                if (playerName != null) {
                    player = serverInstance.getPlayerManager().getPlayer(playerName);
                }
                if (player != null) {
                    source = player.getCommandSource().withLevel(4).withSilent();
                }
                serverInstance.getCommandManager().executeWithPrefix(source, command);
                LOGGER.info("Executed: {}", command);
            } catch (Exception e) {
                LOGGER.error("Command failed: {}", command, e);
            }
        });

        respond(ex, 200, "{\"success\":true}");
    }

    private void handleMetrics(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if ("POST".equals(ex.getRequestMethod())) {
            String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            currentPowerLevel = extractJsonInt(body, "powerLevel", currentPowerLevel);
            viewers = extractJsonInt(body, "viewers", viewers);
            cpm = extractJsonInt(body, "cpm", cpm);
            commandRate = extractJsonInt(body, "commands", commandRate);
            stockFactor = extractJsonDouble(body, "stockFactor", stockFactor);
            String div = extractJsonString(body, "dividendSymbols");
            if (div != null && !div.isBlank()) {
                dividendSymbols.clear();
                for (String part : div.split(",")) {
                    String s = part.trim().toUpperCase(Locale.ROOT);
                    if (!s.isEmpty() && !dividendSymbols.contains(s)) dividendSymbols.add(s);
                }
                if (dividendSymbols.isEmpty()) dividendSymbols.add("MINECRAF");
            }
            chestDefaultValue = (float) extractJsonDouble(body, "chestDefaultValue", chestDefaultValue);
            String smelt = extractJsonString(body, "chestUseSmeltXp");
            if (smelt != null) chestUseSmeltXp = !"false".equalsIgnoreCase(smelt);
            if (body.contains("\"chestUseSmeltXp\":true")) chestUseSmeltXp = true;
            if (body.contains("\"chestUseSmeltXp\":false")) chestUseSmeltXp = false;
            String values = extractJsonString(body, "chestValues");
            if (values != null && !values.isBlank()) {
                chestItemValues.clear();
                for (String part : values.split(",")) {
                    int colon = part.lastIndexOf(':');
                    if (colon <= 0) continue;
                    try {
                        chestItemValues.put(
                            part.substring(0, colon).trim().toLowerCase(Locale.ROOT),
                            Float.parseFloat(part.substring(colon + 1).trim())
                        );
                    } catch (NumberFormatException ignored) {}
                }
            }
            respond(ex, 200, "{\"ok\":true,\"powerLevel\":" + currentPowerLevel + "}");
        } else {
            String json = String.format(
                "{\"viewers\":%d,\"cpm\":%d,\"commands\":%d,\"powerLevel\":%d,\"rfPerTick\":%d}",
                viewers, cpm, commandRate, currentPowerLevel,
                currentPowerLevel <= 0 ? 0 : (ChatDynamoBlockEntity.MAX_RF_PER_TICK * currentPowerLevel) / 15
            );
            respond(ex, 200, json);
        }
    }

    // ---------- tiny JSON helpers ----------
    private static String extractJsonString(String json, String key) {
        String needle = "\"" + key + "\"";
        int idx = json.indexOf(needle);
        if (idx < 0) return null;
        int colon = json.indexOf(':', idx);
        int startQuote = json.indexOf('"', colon + 1);
        if (startQuote < 0) return null;
        int endQuote = json.indexOf('"', startQuote + 1);
        if (endQuote < 0) return null;
        return json.substring(startQuote + 1, endQuote);
    }

    private static int extractJsonInt(String json, String key, int fallback) {
        String needle = "\"" + key + "\"";
        int idx = json.indexOf(needle);
        if (idx < 0) return fallback;
        int colon = json.indexOf(':', idx);
        int i = colon + 1;
        while (i < json.length() && Character.isWhitespace(json.charAt(i))) i++;
        int j = i;
        while (j < json.length() && (Character.isDigit(json.charAt(j)) || json.charAt(j) == '-')) j++;
        try {
            return Integer.parseInt(json.substring(i, j));
        } catch (Exception e) {
            return fallback;
        }
    }

    private void handleDevices(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        respond(ex, 200, DeviceIndex.snapshotJson());
    }

    private void handleDeviceControl(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if (!"POST".equals(ex.getRequestMethod())) {
            ex.sendResponseHeaders(405, -1);
            return;
        }
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        int applied = 0;
        int idx = 0;
        while (true) {
            int idKey = body.indexOf("\"id\"", idx);
            if (idKey < 0) break;
            String id = extractJsonString(body.substring(idKey), "id");
            int nextId = body.indexOf("\"id\"", idKey + 4);
            String chunk = nextId < 0 ? body.substring(idKey) : body.substring(idKey, nextId);
            long rf = (long) extractJsonDouble(chunk, "generateRf", -1);
            if (rf < 0) rf = (long) extractJsonDouble(chunk, "generate_rf", 0);
            if (id != null && !id.isBlank()) {
                DeviceIndex.applyOrder(id, Math.max(0, rf), DeviceIndex.parseConsume(chunk));
                applied++;
            }
            idx = idKey + 4;
        }
        respond(ex, 200, "{\"ok\":true,\"applied\":" + applied + "}");
    }

    private void handleMarket(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if (!"GET".equals(ex.getRequestMethod()) && !"POST".equals(ex.getRequestMethod())) {
            ex.sendResponseHeaders(405, -1);
            return;
        }
        String json = String.format(
            Locale.US,
            "{\"pendingRf\":%d,\"lifetimeRf\":%d,\"pendingXp\":%.4f,\"lifetimeXp\":%.4f,\"stockFactor\":%.4f,\"powerLevel\":%d,\"vaultSymbol\":\"%s\",\"chestSymbol\":\"%s\"}",
            pendingVaultRf, lifetimeVaultRf, pendingChestXp, lifetimeChestXp, stockFactor, currentPowerLevel,
            vaultSymbol, chestSymbol
        );
        respond(ex, 200, json);
    }

    private void handleMarketAck(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if (!"POST".equals(ex.getRequestMethod())) {
            ex.sendResponseHeaders(405, -1);
            return;
        }
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        long rf = (long) extractJsonDouble(body, "rf", 0);
        double xp = extractJsonDouble(body, "xp", 0);
        if (rf > 0) pendingVaultRf = Math.max(0, pendingVaultRf - rf);
        if (xp > 0) pendingChestXp = Math.max(0, pendingChestXp - xp);
        respond(ex, 200, "{\"ok\":true,\"pendingRf\":" + pendingVaultRf + "}");
    }

    private static double extractJsonDouble(String json, String key, double fallback) {
        String needle = "\"" + key + "\"";
        int idx = json.indexOf(needle);
        if (idx < 0) return fallback;
        int colon = json.indexOf(':', idx);
        int i = colon + 1;
        while (i < json.length() && Character.isWhitespace(json.charAt(i))) i++;
        int j = i;
        while (j < json.length()) {
            char c = json.charAt(j);
            if ((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') {
                j++;
            } else break;
        }
        try {
            return Double.parseDouble(json.substring(i, j));
        } catch (Exception e) {
            return fallback;
        }
    }

    private void respond(HttpExchange ex, int code, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(code, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }
    /**
     * Only Stream Core may call this API. Browsers can reach 127.0.0.1 too, so
     * refuse anything with an Origin header, a non-loopback Host (DNS
     * rebinding), or without the X-Fridge-Core header Core sends. A web page
     * cannot add that header cross-origin without a CORS preflight, which this
     * server never approves.
     */
    static boolean rejectUntrusted(HttpExchange ex) throws IOException {
        com.sun.net.httpserver.Headers h = ex.getRequestHeaders();
        String host = h.getFirst("Host");
        String name = host == null ? "" : host.trim().toLowerCase(java.util.Locale.ROOT);
        if (name.startsWith("[")) {
            int end = name.indexOf(']');
            if (end > 0) name = name.substring(0, end + 1);
        } else {
            int colon = name.indexOf(':');
            if (colon >= 0) name = name.substring(0, colon);
        }
        boolean loopback = name.equals("127.0.0.1") || name.equals("localhost") || name.equals("[::1]");
        boolean ok = loopback && h.getFirst("Origin") == null && "1".equals(h.getFirst("X-Fridge-Core"));
        if (ok) return false;
        LOGGER.warn("Refused {} {} (host={}, origin={}) - only Stream Core may call this API",
                ex.getRequestMethod(), ex.getRequestURI().getPath(), host, h.getFirst("Origin"));
        byte[] bytes = "{\"success\":false,\"error\":\"forbidden\"}".getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(403, bytes.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(bytes); }
        return true;
    }
}
