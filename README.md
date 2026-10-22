# FlaVR game plugins

Optional games for **[FlaVR Stream Core](https://github.com/sensokasucks/flavr-leftovers)**:
chat commands, overlays, market tickers and stream-power hooks for Minecraft, Factorio, Granvir
and OpenTTD, plus **Gamer Stonks**, the points stock market. Stream Core runs fine without any of
them; install only what you use.

| Game | Core plugin | Game side | Ports |
|------|-------------|-----------|-------|
| Minecraft | [plugins/minecraft](plugins/minecraft/) | [fridge-minecraft](fridge-minecraft/): Fabric client + server mods, NeoForge | 3852 / 3853 |
| Factorio | [plugins/factorio](plugins/factorio/) | [fridge-factorio-stats](fridge-factorio-stats/): Lua mod, Node bridge, overlays, Chat Dynamo | 3847 |
| Granvir | [plugins/granvir](plugins/granvir/) (just a `plugin.json`) | [fridge-granvir-stats](fridge-granvir-stats/): BepInEx plugin, overlays, mock bridge (`START Granvir Mock.bat`) | 3855 |
| OpenTTD | [plugins/openttd](plugins/openttd/) (Admin Port client, Chat Fund, FridgeChatFund game script) | the OpenTTD / JGRPP server itself | 3977 (Admin Port) |

| Feature | Core plugin | |
|---------|-------------|-|
| Gamer Stonks | [plugins/stonks](plugins/stonks/) | Points stock market: tickers, `!buy` / `!sell`, dividends from game vaults, ticker overlays. Was built into Core as the Fridge Market. |

## Installing a game or Gamer Stonks

1. Download this repo (green **Code → Download ZIP**, or the games pack zip from **Releases**).
2. Copy the game's folder from `plugins/` into Stream Core's `fridge-stream-core\plugins\`
   (you end up with `fridge-stream-core\plugins\minecraft\plugin.json`).
3. Restart Stream Core. It gets a card under **Settings → Plugins**.
4. Tick **Enabled**, **Save & apply**, restart Core again.
5. Set up the game side (mod, bridge or server) from its folder's README.

Minecraft's and Factorio's market parts (Chat Dynamo boost, power drain, death dips, vault
dividends, the market overlays) need **Gamer Stonks** installed and enabled too. Without it the
games still work, just with the dynamo at 1x and no payouts.

Removing a game: untick it, delete its folder from `fridge-stream-core\plugins\`, restart Core.
Its settings stay in `config.yaml` in case you put it back.

**Keeping games up to date with git:** clone this repo next to flavr-leftovers and start Core with
`STREAM_CORE_PLUGINS_DIR` set to this repo's `plugins` folder; `git pull` here then updates every game.

## For developers

- Plugin format and Core's plugin API: [docs/PLUGINS.md](https://github.com/sensokasucks/flavr-leftovers/blob/main/fridge-stream-core/docs/PLUGINS.md) in flavr-leftovers.
- Feature contracts per game: [checklists/](checklists/).
- Tests run against a Stream Core checkout. With flavr-leftovers cloned next to this repo (or
  `STREAM_CORE_DIR` pointing at its `fridge-stream-core` folder): `python -m pytest -q`.
- Tests run automatically on every pull request and every push to main (GitHub Actions, `.github/workflows/tests.yml`),
  against the current `main` of flavr-leftovers, on Windows + Python 3.10 (like Sen's PC) and Linux + Python 3.12 / 3.13.
- Games pack zip for a release: `python tools/pack_games.py` (writes `dist/StreamCore-games-pack-<date>.zip`,
  unzips straight into `fridge-stream-core`).

These folders moved here from flavr-leftovers on 2026-10-09 with their git history.

## License

Copyright (C) 2026 Sensoka (sensokasucks).

This project is free software under the [GNU General Public License v3.0](LICENSE) (GPL-3.0). You can use it for free, including on monetized streams and other commercial use, change it, and share it. If you pass it on to anyone, changed or not, free or paid, you must give them the full source code under the same GPL-3.0 terms.
