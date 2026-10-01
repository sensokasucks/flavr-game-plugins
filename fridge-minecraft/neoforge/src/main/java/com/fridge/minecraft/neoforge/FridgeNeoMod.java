package com.fridge.minecraft.neoforge;

import com.fridge.minecraft.neoforge.block.ChatDynamoBlock;
import com.fridge.minecraft.neoforge.block.ChatKineticBlock;
import com.fridge.minecraft.neoforge.block.DividendChestBlock;
import com.fridge.minecraft.neoforge.block.DividendVaultBlock;
import com.fridge.minecraft.neoforge.blockentity.ChatDynamoBlockEntity;
import com.fridge.minecraft.neoforge.blockentity.ChatKineticBlockEntity;
import com.fridge.minecraft.neoforge.blockentity.DividendChestBlockEntity;
import com.fridge.minecraft.neoforge.blockentity.DividendVaultBlockEntity;
import com.mojang.brigadier.arguments.IntegerArgumentType;
import com.simibubi.create.api.stress.BlockStressValues;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import net.minecraft.core.registries.Registries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.CreativeModeTab;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.fml.common.Mod;
import net.neoforged.fml.event.lifecycle.FMLCommonSetupEvent;
import net.neoforged.neoforge.capabilities.Capabilities;
import net.neoforged.neoforge.capabilities.RegisterCapabilitiesEvent;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.RegisterCommandsEvent;
import net.neoforged.neoforge.event.server.ServerStartedEvent;
import net.neoforged.neoforge.event.server.ServerStoppedEvent;
import net.neoforged.neoforge.registries.DeferredBlock;
import net.neoforged.neoforge.registries.DeferredHolder;
import net.neoforged.neoforge.registries.DeferredItem;
import net.neoforged.neoforge.registries.DeferredRegister;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.Executors;
import java.util.function.Supplier;

@Mod(FridgeNeoMod.MODID)
public class FridgeNeoMod {
    public static final String MODID = "fridge_minecraft";
    public static final Logger LOGGER = LoggerFactory.getLogger("fridge-minecraft-neoforge");
    public static final int PORT = Integer.getInteger("fridge.server.port", 3853);

    public static final DeferredRegister.Blocks BLOCKS = DeferredRegister.createBlocks(MODID);
    public static final DeferredRegister.Items ITEMS = DeferredRegister.createItems(MODID);
    public static final DeferredRegister<BlockEntityType<?>> BLOCK_ENTITIES =
            DeferredRegister.create(Registries.BLOCK_ENTITY_TYPE, MODID);
    public static final DeferredRegister<CreativeModeTab> TABS =
            DeferredRegister.create(Registries.CREATIVE_MODE_TAB, MODID);

    public static final DeferredBlock<Block> CHAT_DYNAMO = BLOCKS.register("chat_dynamo",
            () -> new ChatDynamoBlock(BlockBehaviour.Properties.ofFullCopy(Blocks.REDSTONE_BLOCK).strength(2.5f)));
    public static final DeferredBlock<Block> CHAT_KINETIC = BLOCKS.register("chat_kinetic",
            () -> new ChatKineticBlock(BlockBehaviour.Properties.ofFullCopy(Blocks.IRON_BLOCK).strength(3.0f)));
    public static final DeferredBlock<Block> DIVIDEND_VAULT = BLOCKS.register("dividend_vault",
            () -> new DividendVaultBlock(BlockBehaviour.Properties.ofFullCopy(Blocks.GOLD_BLOCK).strength(3.0f)));
    public static final DeferredBlock<Block> DIVIDEND_CHEST = BLOCKS.register("dividend_chest",
            () -> new DividendChestBlock(BlockBehaviour.Properties.ofFullCopy(Blocks.CHEST).strength(2.5f)));

    public static final DeferredItem<BlockItem> CHAT_DYNAMO_ITEM = ITEMS.registerSimpleBlockItem(CHAT_DYNAMO);
    public static final DeferredItem<BlockItem> CHAT_KINETIC_ITEM = ITEMS.registerSimpleBlockItem(CHAT_KINETIC);
    public static final DeferredItem<BlockItem> DIVIDEND_VAULT_ITEM = ITEMS.registerSimpleBlockItem(DIVIDEND_VAULT);
    public static final DeferredItem<BlockItem> DIVIDEND_CHEST_ITEM = ITEMS.registerSimpleBlockItem(DIVIDEND_CHEST);

    public static final Supplier<BlockEntityType<ChatDynamoBlockEntity>> CHAT_DYNAMO_BE =
            BLOCK_ENTITIES.register("chat_dynamo", () -> BlockEntityType.Builder.of(ChatDynamoBlockEntity::new, CHAT_DYNAMO.get()).build(null));
    public static final Supplier<BlockEntityType<ChatKineticBlockEntity>> CHAT_KINETIC_BE =
            BLOCK_ENTITIES.register("chat_kinetic", () -> BlockEntityType.Builder.of(ChatKineticBlockEntity::new, CHAT_KINETIC.get()).build(null));
    public static final Supplier<BlockEntityType<DividendVaultBlockEntity>> DIVIDEND_VAULT_BE =
            BLOCK_ENTITIES.register("dividend_vault", () -> BlockEntityType.Builder.of(DividendVaultBlockEntity::new, DIVIDEND_VAULT.get()).build(null));
    public static final Supplier<BlockEntityType<DividendChestBlockEntity>> DIVIDEND_CHEST_BE =
            BLOCK_ENTITIES.register("dividend_chest", () -> BlockEntityType.Builder.of(DividendChestBlockEntity::new, DIVIDEND_CHEST.get()).build(null));

    public static final DeferredHolder<CreativeModeTab, CreativeModeTab> TAB = TABS.register("fridge", () ->
            CreativeModeTab.builder()
                    .title(Component.translatable("itemGroup.fridge_minecraft.fridge"))
                    .icon(() -> new ItemStack(CHAT_DYNAMO_ITEM.get()))
                    .displayItems((params, out) -> {
                        out.accept(CHAT_DYNAMO_ITEM.get());
                        out.accept(CHAT_KINETIC_ITEM.get());
                        out.accept(DIVIDEND_VAULT_ITEM.get());
                        out.accept(DIVIDEND_CHEST_ITEM.get());
                    })
                    .build());

    private static MinecraftServer serverInstance;
    private static HttpServer http;

    public FridgeNeoMod(IEventBus modBus) {
        BLOCKS.register(modBus);
        ITEMS.register(modBus);
        BLOCK_ENTITIES.register(modBus);
        TABS.register(modBus);
        modBus.addListener(this::commonSetup);
        modBus.addListener(this::registerCaps);
        NeoForge.EVENT_BUS.addListener(this::onCommands);
        NeoForge.EVENT_BUS.addListener(this::onStarted);
        NeoForge.EVENT_BUS.addListener(this::onStopped);
    }

    private void commonSetup(FMLCommonSetupEvent event) {
        event.enqueueWork(() -> {
            BlockStressValues.CAPACITIES.register(CHAT_KINETIC.get(), () -> 4096d);
            BlockStressValues.CAPACITIES.register(CHAT_DYNAMO.get(), () -> 2048d);
            BlockStressValues.IMPACTS.register(DIVIDEND_VAULT.get(), () -> 8d);
        });
        LOGGER.info("Fridge NeoForge blocks + Create stress values registered");
    }

    private void registerCaps(RegisterCapabilitiesEvent event) {
        event.registerBlockEntity(Capabilities.EnergyStorage.BLOCK, CHAT_DYNAMO_BE.get(), (be, side) -> be.energy);
        event.registerBlockEntity(Capabilities.EnergyStorage.BLOCK, CHAT_KINETIC_BE.get(), (be, side) -> be.energy);
        event.registerBlockEntity(Capabilities.EnergyStorage.BLOCK, DIVIDEND_VAULT_BE.get(), (be, side) -> be.energy);
        event.registerBlockEntity(
                Capabilities.ItemHandler.BLOCK,
                DIVIDEND_CHEST_BE.get(),
                (be, side) -> be.handler(side)
        );
        event.registerBlock(
                Capabilities.ItemHandler.BLOCK,
                (level, pos, state, be, side) -> {
                    if (be instanceof DividendChestBlockEntity chest) return chest.handler(side);
                    return null;
                },
                DIVIDEND_CHEST.get()
        );
    }

    private void onCommands(RegisterCommandsEvent event) {
        event.getDispatcher().register(
                net.minecraft.commands.Commands.literal("fridgepower")
                        .requires(s -> s.hasPermission(2))
                        .then(net.minecraft.commands.Commands.argument("level", IntegerArgumentType.integer(0, 15))
                                .executes(ctx -> {
                                    PowerState.currentPowerLevel = IntegerArgumentType.getInteger(ctx, "level");
                                    ctx.getSource().sendSuccess(() -> Component.literal("Fridge power level " + PowerState.currentPowerLevel + "/15"), true);
                                    return PowerState.currentPowerLevel;
                                }))
        );
    }

    private void onStarted(ServerStartedEvent event) {
        serverInstance = event.getServer();
        startHttp();
    }

    private void onStopped(ServerStoppedEvent event) {
        serverInstance = null;
        if (http != null) {
            http.stop(0);
            http = null;
        }
    }

    private void startHttp() {
        try {
            http = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
            http.createContext("/api/execute", this::handleExecute);
            http.createContext("/api/metrics", this::handleMetrics);
            http.createContext("/api/market", this::handleMarket);
            http.createContext("/api/market/ack", this::handleMarketAck);
            http.createContext("/api/devices", this::handleDevices);
            http.createContext("/api/devices/control", this::handleDeviceControl);
            http.createContext("/api/health", ex -> respond(ex, 200, "{\"ok\":true}"));
            http.setExecutor(Executors.newFixedThreadPool(2));
            http.start();
            LOGGER.info("HTTP API http://127.0.0.1:{}", PORT);
        } catch (IOException e) {
            LOGGER.error("HTTP bind failed", e);
        }
    }

    private void handleExecute(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if (!"POST".equals(ex.getRequestMethod())) { ex.sendResponseHeaders(405, -1); return; }
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        String command = extractString(body, "command");
        String playerName = extractString(body, "player");
        if (command == null || command.isBlank()) { respond(ex, 400, "{\"success\":false}"); return; }
        if (serverInstance == null) { respond(ex, 503, "{\"success\":false}"); return; }
        serverInstance.execute(() -> {
            try {
                var source = serverInstance.createCommandSourceStack().withPermission(4).withSuppressedOutput();
                if (playerName != null) {
                    ServerPlayer p = serverInstance.getPlayerList().getPlayerByName(playerName);
                    if (p != null) source = p.createCommandSourceStack().withPermission(4).withSuppressedOutput();
                }
                serverInstance.getCommands().performPrefixedCommand(source, command);
            } catch (Exception e) {
                LOGGER.error("command failed {}", command, e);
            }
        });
        respond(ex, 200, "{\"success\":true}");
    }

    private void handleMetrics(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if ("POST".equals(ex.getRequestMethod())) {
            String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            PowerState.currentPowerLevel = extractInt(body, "powerLevel", PowerState.currentPowerLevel);
            PowerState.viewers = extractInt(body, "viewers", PowerState.viewers);
            PowerState.cpm = extractInt(body, "cpm", PowerState.cpm);
            PowerState.commandRate = extractInt(body, "commands", PowerState.commandRate);
            PowerState.stockFactor = extractDouble(body, "stockFactor", PowerState.stockFactor);
            PowerState.chestDefaultValue = (float) extractDouble(body, "chestDefaultValue", PowerState.chestDefaultValue);
            if (body.contains("\"chestUseSmeltXp\":true")) PowerState.chestUseSmeltXp = true;
            if (body.contains("\"chestUseSmeltXp\":false")) PowerState.chestUseSmeltXp = false;
            String values = extractString(body, "chestValues");
            if (values != null && !values.isBlank()) {
                PowerState.chestItemValues.clear();
                for (String part : values.split(",")) {
                    int colon = part.lastIndexOf(':');
                    if (colon <= 0) continue;
                    try {
                        PowerState.chestItemValues.put(
                                part.substring(0, colon).trim().toLowerCase(java.util.Locale.ROOT),
                                Float.parseFloat(part.substring(colon + 1).trim())
                        );
                    } catch (NumberFormatException ignored) {}
                }
            }
            String div = extractString(body, "dividendSymbols");
            if (div != null && !div.isBlank()) {
                PowerState.dividendSymbols.clear();
                for (String part : div.split(",")) {
                    String s = part.trim().toUpperCase(java.util.Locale.ROOT);
                    if (!s.isEmpty() && !PowerState.dividendSymbols.contains(s)) {
                        PowerState.dividendSymbols.add(s);
                    }
                }
            }
            respond(ex, 200, "{\"ok\":true,\"powerLevel\":" + PowerState.currentPowerLevel + "}");
        } else {
            respond(ex, 200, String.format(Locale.US,
                    "{\"viewers\":%d,\"cpm\":%d,\"commands\":%d,\"powerLevel\":%d}",
                    PowerState.viewers, PowerState.cpm, PowerState.commandRate, PowerState.currentPowerLevel));
        }
    }

    private void handleDevices(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        respond(ex, 200, DeviceIndex.snapshotJson());
    }

    private void handleDeviceControl(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if (!"POST".equals(ex.getRequestMethod())) { ex.sendResponseHeaders(405, -1); return; }
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        int applied = 0;
        int idx = 0;
        while (true) {
            int idKey = body.indexOf("\"id\"", idx);
            if (idKey < 0) break;
            String id = extractString(body.substring(idKey), "id");
            int nextId = body.indexOf("\"id\"", idKey + 4);
            String chunk = nextId < 0 ? body.substring(idKey) : body.substring(idKey, nextId);
            long rf = (long) extractDouble(chunk, "generateRf", -1);
            if (rf < 0) rf = (long) extractDouble(chunk, "generate_rf", 0);
            long rpmAuth = (long) extractDouble(chunk, "generateRpm", 0);
            if (rf <= 0 && rpmAuth > 0) rf = rpmAuth;
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
        respond(ex, 200, String.format(Locale.US,
                "{\"pendingRf\":%d,\"lifetimeRf\":%d,\"pendingXp\":%.4f,\"lifetimeXp\":%.4f,\"stockFactor\":%.4f,\"powerLevel\":%d,\"vaultSymbol\":\"%s\",\"chestSymbol\":\"%s\"}",
                PowerState.pendingVaultFe, PowerState.lifetimeVaultFe,
                PowerState.pendingChestXp, PowerState.lifetimeChestXp,
                PowerState.stockFactor, PowerState.currentPowerLevel,
                PowerState.vaultSymbol, PowerState.chestSymbol));
    }

    private void handleMarketAck(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if (!"POST".equals(ex.getRequestMethod())) { ex.sendResponseHeaders(405, -1); return; }
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        long rf = (long) extractDouble(body, "rf", 0);
        double xp = extractDouble(body, "xp", 0);
        if (rf > 0) PowerState.pendingVaultFe = Math.max(0, PowerState.pendingVaultFe - rf);
        if (xp > 0) PowerState.pendingChestXp = Math.max(0, PowerState.pendingChestXp - xp);
        respond(ex, 200, "{\"ok\":true}");
    }

    private static void respond(HttpExchange ex, int code, String json) throws IOException {
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(code, bytes.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(bytes); }
    }

    private static String extractString(String json, String key) {
        String needle = "\"" + key + "\"";
        int idx = json.indexOf(needle);
        if (idx < 0) return null;
        int start = json.indexOf('"', json.indexOf(':', idx) + 1);
        if (start < 0) return null;
        int end = json.indexOf('"', start + 1);
        return end < 0 ? null : json.substring(start + 1, end);
    }

    private static int extractInt(String json, String key, int fallback) {
        return (int) extractDouble(json, key, fallback);
    }

    private static double extractDouble(String json, String key, double fallback) {
        String needle = "\"" + key + "\"";
        int idx = json.indexOf(needle);
        if (idx < 0) return fallback;
        int i = json.indexOf(':', idx) + 1;
        while (i < json.length() && Character.isWhitespace(json.charAt(i))) i++;
        int j = i;
        while (j < json.length()) {
            char c = json.charAt(j);
            if ((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') j++;
            else break;
        }
        try { return Double.parseDouble(json.substring(i, j)); } catch (Exception e) { return fallback; }
    }

    public static ResourceLocation id(String path) {
        return ResourceLocation.fromNamespaceAndPath(MODID, path);
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
