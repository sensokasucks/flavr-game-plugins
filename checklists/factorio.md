# Checklist — Factorio

Home: `fridge-factorio-stats/` (Lua `mod/`, Node `server/`, `overlay/`). Core slot: `games/factorio.py`.

## Must keep

- [ ] Bridge listens on `127.0.0.1` (`BIND_HOST` override). `POST /api/metrics` uses `requireCore` (Core sends `X-Fridge-Core: 1`); bridge → Core dividend POST sends it too.
- [ ] Bridge port **3847**. Overlay `http://localhost:3847/overlay.html` plus split sources: power, research, kills, deaths, evolution, combat, alerts.
- [ ] Core slot opt-in: `factorio.enabled` default **false**. `factorio.bridge_url` default `http://127.0.0.1:3847`.
- [ ] Health check hits bridge `GET /stats`.
- [ ] Core POSTs metrics (`power_level` 0–15) to bridge `POST /api/metrics`.
- [ ] Chat Dynamo entity `fridge-chat-dynamo` scales 0 → startup max MW (default 6 MW at level 15). RCON `/fridge-power <0-15>`. Craft or `/fridge-give-dynamo`.
- [ ] Power numbers prefer Wiretap (`hmph-wiretap`). Overlay still works without it (approximate power).
- [ ] Power Vault + Item Vault flush to Core `POST /api/market/dividend`. Thresholds `vault_flush_mj` / `chest_flush_items` hot-saved from Admin → Market.
- [ ] Dynamo / vault / chest tickers live in `factorio.market.*`. Defaults: symbol `FACTORIO` only.
- [ ] Command group `factorio` binds to the integration running (stats/overlay; factory chat commands are not required).
- [ ] Admin → Status + Integrations show Factorio with overlay URLs.
- [ ] Rebrand: `/xsplit-stats` may stay as an alias; new installs use `fridge-factorio-stats`.

## Drop risks

- Core slot that health-checks but never POSTs `power_level` (Dynamo stuck at 0).
- Changing default tickers back to `PWR, FACT` in code only.
- Moving overlay onto :3850 and leaving the Factorio README / Sources list on :3847.

## After-change verify

- [ ] Split overlay files still exist under `fridge-factorio-stats/overlay/`.
- [ ] Example config `factorio.market` keys match what `games/factorio.py` reads.
- [ ] Sources list still mentions :3847.
