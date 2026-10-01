# Pre-built Fabric jars

Drop the compiled mod jars here after building on your PC.  
Non-tech installers only need these two files (plus Fabric API).

## Expected files

| File | Source | Notes |
|------|--------|--------|
| `fridge-minecraft-client-1.0.0.jar` | `client-mod/build/libs/` | Stats HTTP on port **3852** |
| `fridge-minecraft-server-1.0.0.jar` | `server-mod/build/libs/` | Commands + Chat Dynamo / Kinetic on port **3853** |

Version suffix may differ if you change `mod_version` in Gradle.  
Any `fridge-minecraft-client-*.jar` / `fridge-minecraft-server-*.jar` is fine — just keep both present.

## Install into Minecraft

1. Copy **both** jars into your `.minecraft/mods/` folder (or the dedicated server `mods/` folder).
2. Also install **Fabric API** for 1.21.1 if it is not already there.
3. Server jar shades Team Reborn Energy (`include` in Gradle) — no separate Energy jar required.
4. Remove any old `xsplit-minecraft-*.jar` files so Fabric does not load both.

## Minecraft version

Target: **1.21.1** (Fabric).  
Other 1.21.x builds usually work after a version bump + recompile.

## Rebuild

From `fridge-minecraft/`:

- Windows: **`BUILD.bat`**
- Linux / macOS: **`./build.sh`**

That refreshes the jars in this folder. Details: [../COMPILE.md](../COMPILE.md).
