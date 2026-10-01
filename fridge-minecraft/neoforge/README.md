# Fridge Minecraft — NeoForge 21.1.248

Minecraft **1.21.1** / NeoForge **21.1.248**. Official **Create 6** is required.

This is a separate loader from `client-mod` / `server-mod` (Fabric). Do not put this jar in a Fabric instance.

## What it does

- Same Stream Core HTTP bridge on `127.0.0.1:3853` (`/api/metrics`, `/api/execute`, `/api/market`)
- **Chat Kinetic** and **Chat Dynamo** are real Create generators (`GeneratingKineticBlockEntity`)
- Shafts / cogwheels on the block **axis** will spin
- Stress capacity: Kinetic 4096 SU @ 1 RPM, Dynamo 2048
- Both also expose **Forge Energy**
- Dividend Vault eats FE + incoming Create RPM for market dividends
- Sneak-click sets **drain 0–15** (how hard that block pulls Fridge Market). No free FE — Core must authorize output.
- Core turns machines off when the ticker is below Admin → Market **Off below factor**.
- Dividend Chest is a normal inventory (`ItemHandler` capability) so Create funnels can insert.

## Build

JDK 21, internet on first run.

```
cd fridge-minecraft\neoforge
BUILD.bat
```

Jar: `build\libs\fridge-minecraft-neoforge-1.0.0.jar`

## Install

1. NeoForge 21.1.248 profile (MC 1.21.1)
2. Create 6.0.x for 1.21.1
3. This jar in `mods`
4. Enable `minecraft.enabled` in Stream Core if you want live metrics

## In world

- Creative tab **Fridge**
- Place Kinetic or Dynamo, sneak-click until level 8+, put a shaft on the axis
- `/fridgepower 15` if sneak-click is a pain
