# Fridge Factorio Stats

Semi-realtime Factorio overlay for **XSplit Broadcaster** (also works in OBS Browser Source).

Shows:
- **Power production / consumption** (accurate when using Wiretap mod)
- **Research progress** + queue
- **Kill count** (enemies killed by your force)
- **Death count** (player deaths this map)
- **Evolution factor**
- **Live in-game alerts** (biter attacks, turret fire, low power, etc.)
- **Chat Dynamo** — in-game generator driven by Stream Core power level 0–15 (same idea as Minecraft)

---

## Architecture

```
Stream Core ──POST /api/metrics──► Node Bridge ──RCON /fridge-power──► Chat Dynamo
Factorio    ──RCON /fridge-stats─► Node Bridge ──WebSocket──────────► Overlay
                 └── Wiretap JSON ─┘
```

1. **Factorio mod** (`fridge-factorio-stats`) – stats export + Chat Dynamo entity.
2. **Node bridge** – polls RCON, watches Wiretap, receives Core metrics, sets dynamo output.
3. **Overlay** – transparent HTML/CSS/JS Webpage sources.
4. **Stream Core** – enable `factorio.enabled` so live `power_level` is pushed to the bridge.

---

## Quick Start

### 1. Enable RCON in Factorio

Edit `%APPDATA%\Factorio\config\config.ini` (or create the section if missing):

```ini
[other]
local-rcon-socket=127.0.0.1:25575
local-rcon-password=factorio
```

Restart Factorio after saving.

> Use a stronger password if the machine is shared. The bridge reads the password from the environment or the default `factorio`.

### 2. Install the Factorio mod

Copy the whole `mod/` folder into your Factorio mods directory and rename it (or zip it) so Factorio sees:

```
%APPDATA%\Factorio\mods\fridge-factorio-stats_1.1.0\
  ├── info.json
  └── control.lua
```

Or zip the contents of `mod/` as `fridge-factorio-stats_1.1.0.zip`.

Enable the mod in the Factorio mods menu and start / load a game.

If you still have `xsplit-factorio-stats_1.0.0` installed, disable or delete that folder so Factorio only loads the Fridge mod. `/xsplit-stats` remains an alias.

### 3. (Strongly recommended) Install Wiretap for accurate power

1. Download **Wiretap – Stats Exporter** (`hmph-wiretap`) from the Factorio mod portal.
2. Enable it. It writes `%APPDATA%\Factorio\script-output\wiretap\stats.json` every few seconds with full electric-network production & consumption numbers.
3. The bridge automatically detects and merges that file.

Without Wiretap the overlay still works but power numbers are only approximate.

### 4. Run the bridge

```bash
cd server
npm install
npm start
```

You should see:

```
=== Fridge Factorio Stats Bridge ===
HTTP/WS listening on http://localhost:3847
Overlay URL for XSplit: http://localhost:3847/overlay.html
…
[RCON] Connected to 127.0.0.1:25575
```

Environment variables you can override:

| Variable          | Default                          | Meaning                    |
|-------------------|----------------------------------|----------------------------|
| `RCON_HOST`       | `127.0.0.1`                      | Factorio RCON host         |
| `RCON_PORT`       | `25575`                          | Factorio RCON port         |
| `RCON_PASSWORD`   | `factorio`                        | RCON password              |
| `PORT`            | `3847`                           | HTTP + WebSocket port      |
| `BIND_HOST`       | `127.0.0.1`                      | Listen address. Set `0.0.0.0` only if another PC must reach the overlay |
| `WIRETAP_PATH`    | `%APPDATA%\…\wiretap\stats.json` | Path to Wiretap JSON       |

`POST /api/metrics` only accepts Stream Core (header `X-Fridge-Core: 1`, no browser `Origin`, loopback `Host`), so web pages cannot change the Dynamo power level. WebSockets from foreign web pages are refused.

### 5. Add sources in XSplit

You can use the **full combined overlay** or any **individual stat** as its own Webpage source.

#### Full overlay (everything in one panel)
```
http://localhost:3847/overlay.html
```
Suggested size: ~420 × 400 px

#### Individual stream sources (place each wherever you want)

| Stat            | URL                                          | Suggested size   |
|-----------------|----------------------------------------------|------------------|
| **Power**       | `http://localhost:3847/power.html`           | 280 × 160 px     |
| **Research**    | `http://localhost:3847/research.html`        | 280 × 160 px     |
| **Kills**       | `http://localhost:3847/kills.html`           | 200 × 120 px     |
| **Deaths**      | `http://localhost:3847/deaths.html`          | 200 × 120 px     |
| **Evolution**   | `http://localhost:3847/evolution.html`       | 200 × 120 px     |
| **Combat**      | `http://localhost:3847/combat.html`          | 280 × 150 px     |
| **Alerts**      | `http://localhost:3847/alerts.html`          | 320 × 220 px     |

All sources share the same live WebSocket feed from the bridge — add as many as you like, they stay in sync.

1. In XSplit → **Add source** → **Webpage**
2. Paste one of the URLs above
3. Set the size (or crop) to fit your layout
4. Transparent background is already handled

You can also open any URL in a browser to preview.

---

## Chat Dynamo (in-game power)

Same metric as Minecraft’s Chat Dynamo: Stream Core maps viewers + chat rate + commands onto **power level 0–15**.

| Level | Output (default max 6 MW) |
|-------|---------------------------|
| 0 | 0 W |
| 8 | 3.2 MW |
| 15 | 6 MW |

1. Enable `factorio.enabled: true` in Stream Core and start the Node bridge.
2. In Factorio, craft **Chat Dynamo** (20 iron plate + 10 copper plate + 5 iron gear) or run `/fridge-give-dynamo`.
3. Place it and connect a power pole. Output updates a few seconds after Core posts metrics.

Startup setting **Chat Dynamo max output (MW)** changes the level-15 cap (restart required).  
RCON: `/fridge-power 12` sets the level by hand for testing.

PWR price multiplies dynamo output: `watts = levelWatts × clamp(PWR / base, 0.25, 3)`.

### Power Vault + Item Vault (dividends)

Feed factory surplus; Stream Core pays chat investors.

| Block | Eats | Pays |
|-------|------|------|
| **Power Vault** (blue) | Electricity up to the dynamo MW cap | `factorio.market.vault_symbol` (default `PWR`) |
| **Item Vault** (gold chest) | Items you drop in | `factorio.market.chest_symbol` (default `FACT`) |

Pick tickers in Stream Core **Admin → Market → Factorio tickers**. Comma lists on the dynamo average into the watt boost; comma lists on a vault split that flush.

Work flushes to `POST /api/market/dividend` at the configured MJ / item thresholds. Rates: 0.02 pts/MJ, 1 pt/item, hourly cap 500. No holders → work is burned.

---

## What each source shows

| Source      | Data                                                                 |
|-------------|----------------------------------------------------------------------|
| **Power**   | Production + consumption (Wiretap), load bar, accumulator charge    |
| **Research**| Current tech name, progress bar, queue / researched count           |
| **Kills**   | Total enemies killed by your force                                   |
| **Deaths**  | Player deaths this map                                               |
| **Evolution**| Enemy evolution factor                                              |
| **Combat**  | Kills + Deaths + Evolution in one card                               |
| **Alerts**  | Live list of in-game alerts (biter attacks, turret engaged, etc.)   |
| **Full**    | All of the above in a single panel                                   |

Updates arrive roughly every 2 seconds (RCON poll) and immediately when Wiretap writes a new file.

---

## Troubleshooting

| Symptom                        | Fix                                                                 |
|--------------------------------|---------------------------------------------------------------------|
| Status stays “CONNECTING…”     | Is the Node bridge running? Is the port free?                      |
| RCON never connects            | Check `config.ini`, password, and that a game is actually loaded   |
| Power shows “install Wiretap”  | Install & enable `hmph-wiretap`, then restart the bridge            |
| No alerts appear               | Alerts only show while they are active in-game                     |
| Deaths stay at 0               | The mod must be loaded *before* any deaths occur (or die once)     |
| Overlay looks cut off          | Increase the Webpage source size in XSplit                         |
| Chat Dynamo stays at 0 W       | Enable `factorio.enabled` in Stream Core, restart the bridge, place the entity |

---

## File layout

```
fridge-factorio-stats/
├── mod/                  ← Factorio mod
│   ├── info.json
│   ├── data.lua              ← Chat Dynamo prototype
│   ├── settings.lua
│   ├── locale/en/locale.cfg
│   └── control.lua
├── server/               ← Node bridge
│   ├── package.json
│   └── server.js
├── overlay/              ← XSplit Webpage sources
│   ├── overlay.html      ← full combined panel
│   ├── power.html
│   ├── research.html
│   ├── kills.html
│   ├── deaths.html
│   ├── evolution.html
│   ├── combat.html
│   ├── alerts.html
│   ├── overlay.css
│   └── widget.js         ← shared live-update logic
└── README.md
```

---

## Notes / Limitations

- **Power accuracy** relies on the excellent Wiretap mod. The built-in approximation only counts max prototype production of generators and is not reliable for live demand.
- **Kill counts** are total entities killed *by* the player force on the primary surface (nauvis by default). Very large kill tables are trimmed in the file export.
- **Alerts** come from `player.get_alerts()`. The exact set of alert types depends on the Factorio version and active mods.
- The bridge is local-only by design. Do not expose port 3847 to the internet without authentication.

Enjoy the stream!  
— Sensoka's Workshop
