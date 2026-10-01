# Building the Server Mod

## Dependencies

### Required for RF energy (Chat Dynamo)
```gradle
// build.gradle
repositories {
    maven { url = "https://maven.fabricmc.net/" }
    // Team Reborn Energy – check https://github.com/TechReborn/Energy for the latest
    maven { url = "https://maven.terraformersmc.com/" }
}

dependencies {
    // Fabric API already present from the example mod
    modImplementation include("teamreborn:energy:4.1.0")   // adjust version to your MC
}
```

### Optional – Create kinetic block
Add the Create Fabric port as a dependency and change
`ChatKineticBlockEntity` to extend `GeneratingKineticBlockEntity`
as documented inside that class.

## Steps

1. Start from the official Fabric example mod for 1.21.1.
2. Copy all sources under `src/main/java/com/fridge/minecraft/server/` and the `fabric.mod.json`.
3. Add the Team Reborn Energy dependency (above).
4. `./gradlew build`
5. Drop the resulting jar into the server (or singleplayer) mods folder together with Fabric API and the Energy API jar (or let `include` shade it).

## In-game

| Block | ID | What it does |
|-------|----|--------------|
| **Chat Dynamo** | `fridge_minecraft:chat_dynamo` | RF + redstone; RF also × market stock factor |
| **Chat Kinetic Source** | `fridge_minecraft:chat_kinetic` | Intended Create kinetic source. RPM & SU scale with the same metrics. |
| **Dividend Dynamo** | `fridge_minecraft:dividend_vault` | Eats RF pushed into it; Core flushes as dividends |
| **Smelt Chest** | `fridge_minecraft:dividend_chest` | Hopper inventory; smeltables → furnace XP → dividends |

Both scale from the same `powerLevel` (0–15) that Fridge Stream Core calculates from viewers + CPM + commands.

### Default generation curve

- powerLevel 0  → 0 RF/t  /  0 RPM
- powerLevel 15 → **2400 RF/t**  /  **128 RPM** + **4096 SU**

Change the constants in:
- `ChatDynamoBlockEntity.MAX_RF_PER_TICK`
- `ChatKineticBlockEntity.MAX_RPM` / `MAX_SU`

## Give commands

```
/give @s fridge_minecraft:chat_dynamo
/give @s fridge_minecraft:chat_kinetic
/give @s fridge_minecraft:dividend_vault
/give @s fridge_minecraft:dividend_chest
```
