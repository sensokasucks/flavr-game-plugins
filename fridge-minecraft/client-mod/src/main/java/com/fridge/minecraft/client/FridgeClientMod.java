package com.fridge.minecraft.client;

import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.effect.StatusEffectInstance;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.util.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executors;

/**
 * Client-side Fabric mod.
 * Starts a tiny HTTP server on localhost:3852 that Fridge Stream Core polls.
 * Tracks deaths and can temporarily flag "show inventory".
 */
public class FridgeClientMod implements ClientModInitializer {
    public static final Logger LOGGER = LoggerFactory.getLogger("fridge-minecraft-client");
    public static final int PORT = Integer.getInteger("fridge.client.port", 3852);

    private static int deathCount = 0;
    private static long showInventoryUntil = 0;
    private static boolean wasDead = false;

    @Override
    public void onInitializeClient() {
        LOGGER.info("Fridge Minecraft Client Stats starting on port {}", PORT);
        startHttpServer();

        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            ClientPlayerEntity player = client.player;
            if (player == null) return;

            // simple death detection
            if (player.isDead() || player.getHealth() <= 0) {
                if (!wasDead) {
                    deathCount++;
                    wasDead = true;
                    LOGGER.info("Death recorded. Total: {}", deathCount);
                }
            } else {
                wasDead = false;
            }
        });
    }

    private void startHttpServer() {
        try {
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
            server.createContext("/api/stats", this::handleStats);
            server.createContext("/api/inventory", this::handleInventory);
            server.createContext("/api/show_inventory", this::handleShowInventory);
            server.setExecutor(Executors.newFixedThreadPool(2));
            server.start();
            LOGGER.info("HTTP API listening on http://127.0.0.1:{}", PORT);
        } catch (IOException e) {
            LOGGER.error("Failed to start HTTP server", e);
        }
    }

    private void handleStats(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        if (!"GET".equals(ex.getRequestMethod())) {
            ex.sendResponseHeaders(405, -1);
            return;
        }
        MinecraftClient mc = MinecraftClient.getInstance();
        ClientPlayerEntity p = mc.player;
        String json;
        if (p == null) {
            json = "{\"online\":false}";
        } else {
            List<String> effects = new ArrayList<>();
            for (StatusEffectInstance inst : p.getStatusEffects()) {
                Identifier id = Registries.STATUS_EFFECT.getId(inst.getEffectType().value());
                String name = id != null ? id.getPath() : "unknown";
                int secs = inst.getDuration() / 20;
                effects.add(String.format("{\"name\":\"%s\",\"duration\":%d,\"amplifier\":%d}", name, secs, inst.getAmplifier()));
            }
            float xpProgress = p.experienceProgress;
            json = String.format(
                "{\"online\":true,\"health\":%.2f,\"maxHealth\":%.2f,\"food\":%d,\"saturation\":%.2f," +
                "\"level\":%d,\"xpProgress\":%.3f,\"deaths\":%d,\"armor\":%d,\"effects\":[%s]}",
                p.getHealth(), p.getMaxHealth(), p.getHungerManager().getFoodLevel(),
                p.getHungerManager().getSaturationLevel(), p.experienceLevel, xpProgress,
                deathCount, p.getArmor(), String.join(",", effects)
            );
        }
        respond(ex, 200, json);
    }

    private void handleInventory(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        MinecraftClient mc = MinecraftClient.getInstance();
        ClientPlayerEntity p = mc.player;
        if (p == null) {
            respond(ex, 200, "{\"slots\":[]}");
            return;
        }
        StringBuilder sb = new StringBuilder("{\"slots\":[");
        boolean first = true;
        // main inventory 0-35 + armor 36-39 + offhand 40
        for (int i = 0; i < p.getInventory().size(); i++) {
            ItemStack stack = p.getInventory().getStack(i);
            if (!first) sb.append(',');
            first = false;
            if (stack.isEmpty()) {
                sb.append("null");
            } else {
                Identifier id = Registries.ITEM.getId(stack.getItem());
                sb.append(String.format("{\"id\":\"%s\",\"count\":%d}", id.toString(), stack.getCount()));
            }
        }
        sb.append("]}");
        respond(ex, 200, sb.toString());
    }

    private void handleShowInventory(HttpExchange ex) throws IOException {
        if (rejectUntrusted(ex)) return;
        // POST /api/show_inventory?seconds=12
        String query = ex.getRequestURI().getQuery();
        int seconds = 12;
        if (query != null && query.contains("seconds=")) {
            try {
                seconds = Integer.parseInt(query.replaceAll(".*seconds=(\\d+).*", "$1"));
            } catch (Exception ignored) {}
        }
        showInventoryUntil = System.currentTimeMillis() + seconds * 1000L;
        respond(ex, 200, "{\"ok\":true,\"seconds\":" + seconds + "}");
    }

    private void respond(HttpExchange ex, int code, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(code, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    /** Called by overlay logic if needed (currently unused, bridge polls). */
    public static boolean shouldShowInventory() {
        return System.currentTimeMillis() < showInventoryUntil;
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
