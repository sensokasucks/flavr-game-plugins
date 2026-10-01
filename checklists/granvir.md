# Checklist — Granvir

Home: `fridge-granvir-stats/` (BepInEx `plugin/`, `overlay/`, `mock/mock_server.py`). Core slot: `games/granvir.py`.

## Must keep

- [ ] HTTP **:3855**. `GET /stats`, `GET /health` / `GET /ping`, `POST /command`.
- [ ] Overlays: `/overlay.html`, `/health.html`, `/heat.html`, `/campaign.html`, `/squad.html`.
- [ ] Core opt-in: `granvir.enabled` default **false**. `granvir.bridge_url` default `http://127.0.0.1:3855`.
- [ ] **Host-only writes.** Clients do not need the plugin. `HostOnlyWrites = true` by default.
- [ ] Never mutate shared campaign / depot / part state from a client.
- [ ] `mock/mock_server.py` + `START Granvir Mock.bat` / package `START Mock.bat` still run without the game.
- [ ] Plugin degrades to empty fields on rename (reflection probe) instead of crashing.
- [ ] Admin → Integrations shows Granvir when the slot exists; health ping hits :3855.

## Drop risks

- Shipping client-side writes “so party members can trigger commands”.
- Pointing Core at a non-loopback URL in the example config.

## After-change verify

- [ ] Mock still serves `/stats` and the overlay pages.
- [ ] README co-op table still says host-only.
- [ ] Example / DEFAULTS still have Granvir off if that key is present.
