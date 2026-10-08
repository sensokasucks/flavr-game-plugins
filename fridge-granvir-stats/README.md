# Fridge Granvir Stats

Local stats + overlay bridge for **Granvir** (Unity / Mono, Mirror co-op).

Stream Core talks to this the same way it talks to Fridge Factorio Stats:

```
Granvir (host) ──BepInEx plugin──► HTTP :3855 ──► Stream Core + overlays
                       ▲
              mock/mock_server.py   (dev stand-in, no game required)
```

Default URL: `http://127.0.0.1:3855`

- `GET /stats` — JSON snapshot
- `GET /health` / `GET /ping` — liveness
- `POST /command` — host-only actions (stub until game types are hooked)
- Overlay pages: `/overlay.html`, `/health.html`, `/heat.html`, `/campaign.html`, `/squad.html`

## Co-op rules

Granvir already fights multiplayer desync. This plugin is written around that:

| Role | What it does |
|------|----------------|
| **Host** (streamer) | Runs the plugin. Serves `/stats`. May run `/command` writes. |
| **Clients** | Do not need the plugin. If they install it, keep `HostOnlyWrites = true` (default). |

Never mutate shared campaign / depot / part state from a client. Reads are local-HUD only until Harmony hooks land.

## Path A — develop without the game

```bat
cd fridge-granvir-stats
python mock\mock_server.py
```

Then in Stream Core `config.yaml`:

```yaml
granvir:
  enabled: true
  bridge_url: "http://127.0.0.1:3855"
```

Restart Core. Admin → Integrations should show Granvir healthy. Webpage sources can use the overlay URLs above.

## Path B — BepInEx plugin (in-game)

1. Confirm the game is **Unity Mono** (`Granvir_Data/Managed/Assembly-CSharp.dll` exists).
2. Install **BepInEx 5** (x64 Mono) into the Granvir install folder. Run once so `BepInEx/config` appears.
3. Build `plugin/FridgeGranvirStats.csproj` in Visual Studio / `dotnet build` after pointing HintPaths at:
   - `BepInEx/core/BepInEx.dll`
   - `BepInEx/core/0Harmony.dll`
   - `Granvir_Data/Managed/UnityEngine.CoreModule.dll`
4. Copy the built `FridgeGranvirStats.dll` to `BepInEx/plugins/FridgeGranvirStats/`.
5. Copy the `overlay/` folder next to the DLL as `www/` **or** leave overlays served by the mock / a static file host — the plugin also serves `www/` from its own folder when present.
6. Launch Granvir as **lobby host**. Check `BepInEx/LogOutput.log` for `FridgeGranvirStats listening on http://127.0.0.1:3855/`.

Config file after first launch: `BepInEx/config/fridge.granvir.stats.cfg`.

### First types to hunt in dnSpy

Open `Assembly-CSharp.dll`. Search these names / fragments:

| Hunt | Why |
|------|-----|
| `NetworkServer`, `NetworkClient`, `NetworkManager` | Mirror host vs client |
| `Granvir`, `Mech`, `Pilot`, `PlayerController` | local machine |
| `Health`, `Durability`, `Vitality`, `Integrity` | HP bar |
| `Heat`, `Generator`, `Cooling` | heat bar |
| `Campaign`, `Mission`, `RestArea`, `Region` | between-mission layer |
| `Credits`, `Depot`, `Supply` | resources |
| `PartCodex`, `PartInventory` | codex / equipped count |
| `Kill`, `Ace` | combat counters |

`plugin/GameProbe.cs` tries these names by reflection so a patch-day rename degrades to empty fields instead of a crash. Replace the heuristics with real field paths once you have them.

## `/stats` JSON

```json
{
  "ok": true,
  "source": "plugin",
  "plugin_version": "0.1.0",
  "game_version": "",
  "ts": 1690000000,
  "online": true,
  "is_host": true,
  "phase": "mission",
  "campaign": {
    "name": "",
    "region": "",
    "hours_left": null,
    "credits": null,
    "threat": null
  },
  "squad": {
    "count": 1,
    "max": 10,
    "players": [{"name": "Host", "alive": true}]
  },
  "pilot": {
    "name": "",
    "alive": true,
    "health": 80,
    "health_max": 100,
    "heat": 12,
    "heat_max": 100,
    "ammo": null,
    "kills": 0,
    "deaths": 0
  },
  "parts": {
    "equipped": 0,
    "depot": 0,
    "codex_found": 0,
    "codex_total": 0
  },
  "notes": []
}
```

`phase`: `menu` | `rest` | `mission` | `sandbox` | `unknown`

## Stream Core

Opt-in slot in `fridge-stream-core`:

- `fridge-stream-core/plugins/granvir/plugin.json` (http plugin: Core's built-in client talks to this bridge)
- Admin → Config → Granvir
- Command group `granvir` (active only when the integration is running)

Chat commands stay off until a host-safe action exists in the plugin. `POST /command` is accepted and logged; the mock never mutates a real lobby.

## Ports

| Port | Owner |
|------|--------|
| 3855 | This bridge (plugin or mock) |
| 3850 | Stream Core |

Bind loopback only.
