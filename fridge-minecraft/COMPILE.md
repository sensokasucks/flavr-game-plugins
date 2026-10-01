# Compile the Fridge Minecraft jars

Target: **Minecraft 1.21.1 + Fabric**.  
Output: two jars you drop in `.minecraft/mods/` (and optionally copy into `jars/` in this folder).

| Jar | Built from | HTTP port |
|-----|------------|-----------|
| `fridge-minecraft-client-1.0.0.jar` | `client-mod/` (complete Gradle project) | 3852 |
| `fridge-minecraft-server-1.0.0.jar` | `server-mod/` (sources + extra Gradle setup) | 3853 |

Windows steps below. On Linux/macOS use `./gradlew` instead of `gradlew.bat`.

---

## 0. What you need first

1. **JDK 21** (not 17, not 22+ as the primary JDK).
   - Download Temurin 21: https://adoptium.net/temurin/releases/?version=21
   - Install the **JDK**, not just the JRE.
   - During setup, enable **“Set JAVA_HOME”** and **“Add to PATH”** if those boxes exist.
2. Confirm in a **new** Command Prompt or PowerShell:

   ```bat
   java -version
   ```

   You want something like `openjdk version "21.x.x"`.
3. First Gradle run needs the internet (downloads Gradle 9.5.1, Minecraft mappings, Fabric Loom). Later rebuilds work offline if the cache is warm.
4. Close Minecraft / the launcher while you copy jars into `mods`.

---

## 1. Client mod (stats, port 3852)

This project already has `gradlew.bat`, `build.gradle`, and sources.

1. Open Command Prompt.
2. Go to the client project (adjust the path if your workshop folder lives somewhere else):

   ```bat
   cd /d C:\path\to\fridge-minecraft\client-mod
   ```

3. Build:

   ```bat
   gradlew.bat build
   ```

   First run can take several minutes. Success ends with `BUILD SUCCESSFUL`.
4. Find the jar:

   ```
   client-mod\build\libs\fridge-minecraft-client-1.0.0.jar
   ```

   Ignore `-sources.jar` if Loom also writes one. You want the plain remapped jar (usually the one **without** `-sources` or `-dev`).
5. Copy it to:

   ```
   %appdata%\.minecraft\mods\fridge-minecraft-client-1.0.0.jar
   ```

   and, if you keep a workshop copy:

   ```
   ..\jars\fridge-minecraft-client-1.0.0.jar
   ```

That is the only jar required for the overlay stats (`health`, deaths, inventory / `!inv`).

---

## 2. Server mod (commands + Chat Dynamo, port 3853)

`server-mod/` currently ships **Java sources + `fabric.mod.json`**, not a finished Gradle project. You attach those sources to a 1.21.1 Fabric Loom project once, then `build` the same way as the client.

### 2a. Create a Fabric 1.21.1 Gradle shell

1. Download the official example for 1.21.1:  
   https://github.com/FabricMC/fabric-example-mod/tree/1.21.1  
   (Use **Code → Download ZIP**, or clone that branch.)
2. Unpack it into a **temporary** folder, e.g. `C:\temp\fabric-example-mod`.
3. Copy these Gradle files from the example **into** `fridge-minecraft\server-mod\`:
   - `gradlew` / `gradlew.bat`
   - `gradle\wrapper\` (the whole folder)
   - `build.gradle`
   - `settings.gradle`
   - `gradle.properties`
4. Do **not** overwrite `server-mod\src`. Keep the Fridge sources that are already there.

### 2b. Point Gradle at Fridge

Edit `server-mod\gradle.properties` so it matches the client (same MC / mappings / loader):

```properties
minecraft_version=1.21.1
yarn_mappings=1.21.1+build.3
loader_version=0.16.14
loom_version=1.10-SNAPSHOT

mod_version=1.0.0
maven_group=com.fridge
archives_base_name=fridge-minecraft-server

fabric_api_version=0.116.0+1.21.1
```

In `settings.gradle` set:

```gradle
rootProject.name = 'fridge-minecraft-server'
```

In `build.gradle`:

- Keep the Fabric Loom + Minecraft / Yarn / Loader / Fabric API lines from the example (or copy the client `build.gradle`).
- Add Team Reborn Energy so Chat Dynamo compiles:

```gradle
repositories {
    maven { url = "https://maven.fabricmc.net/" }
    maven { url = "https://maven.terraformersmc.com/" }
}

dependencies {
    minecraft "com.mojang:minecraft:${project.minecraft_version}"
    mappings "net.fabricmc:yarn:${project.yarn_mappings}:v2"
    modImplementation "net.fabricmc:fabric-loader:${project.loader_version}"
    modImplementation "net.fabricmc.fabric-api:fabric-api:${project.fabric_api_version}"

    // Shade Energy into the jar so players do not need a second Energy jar
    modImplementation include("teamreborn:energy:4.1.0")
}
```

If `4.1.0` fails resolution, check the current artifact on  
https://github.com/TechReborn/Energy and bump the version.

Optional: Create kinetic block. The kinetic entity is a placeholder unless you add the Create Fabric port and change `ChatKineticBlockEntity` as noted in that class. The dynamo + command HTTP API do not need Create.

### 2c. Build

```bat
cd /d C:\path\to\fridge-minecraft\server-mod
gradlew.bat build
```

Jar lands at:

```
server-mod\build\libs\fridge-minecraft-server-1.0.0.jar
```

Copy it next to the client jar:

```
%appdata%\.minecraft\mods\fridge-minecraft-server-1.0.0.jar
..\jars\fridge-minecraft-server-1.0.0.jar
```

---

## 3. Install into Minecraft

1. Install the **Fabric Loader** for 1.21.1 (https://fabricmc.net/use/installer/) and create / use a 1.21.1 Fabric profile.
2. Put **Fabric API** for 1.21.1 in `mods` if it is not already there:  
   https://modrinth.com/mod/fabric-api
3. Put **both** Fridge jars in the same `mods` folder.
   - Singleplayer / integrated server: `%appdata%\.minecraft\mods\`
   - Dedicated server: `<server>\mods\` (server jar is required there; client jar is optional on a dedicated server).
4. Delete any leftover `xsplit-minecraft-*.jar` so Fabric does not load the old ids.
5. Launch the Fabric 1.21.1 profile once and check the log for:
   - `Fridge Minecraft Client Stats` (client)
   - `Fridge Minecraft Server Interactions` (logical server / singleplayer)

### If the build fails

| Symptom | Fix |
|---------|-----|
| `JAVA_HOME is not set` / wrong version | Install JDK 21, reopen the terminal, `echo %JAVA_HOME%` |
| `Unsupported class file major version` | Gradle is using an older JDK. Point `JAVA_HOME` at JDK 21 |
| Loom cannot download Minecraft | Need network; also accept the Mojang EULA on first official launch if mappings fetch is blocked |
| `package team.reborn.energy does not exist` | Energy dep missing or wrong version — see §2b |
| `FabricBlockSettings` / registry errors | Example mod branch is not **1.21.1**. Recopy Gradle files from that branch |
| Two mods with the same id | Remove old `xsplit-*` or duplicate Fridge jars |

---

## 4. After the jars load

1. Start Minecraft with both mods.
2. Start Stream Core (`START Stream Core.bat` or `python main.py` in `fridge-stream-core`).
3. In `fridge-stream-core/config/config.yaml`:

   ```yaml
   minecraft:
     enabled: true
     player_name: "YourInGameName"
     client_mod_url: "http://127.0.0.1:3852"
     server_mod_url: "http://127.0.0.1:3853"
   ```

4. Overlay: `http://127.0.0.1:3850/overlay/overlay.html`  
   Commands (`!spawn`, `!give`, `!inv`, …) live in Stream Core `config/commands.json`.

In-game blocks after the server jar is loaded:

```
/give @s fridge_minecraft:chat_dynamo
/give @s fridge_minecraft:chat_kinetic
```

Worlds that still have the old `xsplit_*` block ids need those blocks placed again.

---

## 5. Rebuild later

Once Gradle exists in both folders, a rebuild is only:

```bat
cd client-mod
gradlew.bat build

cd ..\server-mod
gradlew.bat build
```

Copy the new jars over the old ones in `mods` and in `jars/`.
