# Checklist — Minecraft

Home: `fridge-minecraft/` (Fabric `client-mod` + `server-mod`, NeoForge `neoforge/`). Core side: plugin `fridge-stream-core/plugins/minecraft/` (`plugin.py`, `plugin.json`, `commands.json`, `overlay/`). Plugin rules: [plugins.md](plugins.md).

## Must keep

- [ ] Integration is **opt-in**. `minecraft.enabled` defaults **false** in `config.yaml`, `config.example.yaml`, and the plugin's `plugin.json` `config_defaults` (Core forces `enabled: false` for every plugin default).
- [ ] Ports: client stats **3852**, server commands / dynamo / market **3853**.
- [ ] Every mod HTTP handler (except `/api/health`) starts with `rejectUntrusted(ex)`: loopback `Host`, no `Origin`, header `X-Fridge-Core: 1`. Core's `plugins/minecraft/plugin.py` httpx client sends that header. No `Access-Control-Allow-Origin: *`.
- [ ] Folder is mods-only. Chat, permissions, commands, metrics, overlay live in Stream Core. Do not resurrect the old Node bridge.
- [ ] `jars/` is for pre-built Fabric jars the user adds. Jars are gitignored.
- [ ] `BUILD.bat` / `build.sh` + `COMPILE.md` remain the build path. README still documents the non-build install path.
- [ ] Target: Minecraft **1.21.1**. Fabric API required for Fabric jars.
- [ ] Client stats: health, hunger, XP/level, armor, effects, death counter, optional inventory snapshot.
- [ ] Server executes commands Core forwards (`!spawn`, `!give`, `!heal`, quantity, permission tiers).
- [ ] **Chat Dynamo** + **Chat Kinetic** exist. Power 0–15 from Core metrics. Market factor applied (see [market.md](market.md)). Chat Kinetic uses the same power + stock factor — no extra RPM→FE.
- [ ] Blocks: `fridge_minecraft:chat_dynamo`, `chat_kinetic`, `dividend_vault`, `dividend_chest`. Old `xsplit_*` ids are gone; worlds need blocks replaced after rebrand.
- [ ] Dividend Chest: 54-slot hopper chest, any item, ItemHandler cap so hoppers / Create funnels can insert.
- [ ] Command group `minecraft` binds to enabled **and** running.
- [ ] Admin → Settings → Game plugins has a Minecraft card and Market a Minecraft sub-page (both from `plugin.json`). Admin → Integrations has a Minecraft sub-panel (health, commands Fill/Dry, metrics push, overlay URLs).
- [ ] Stats overlay modules still include inventory when the client mod is up (`overlay.show_inventory_seconds`).

### NeoForge (`fridge-minecraft/neoforge`)

- [ ] Separate loader. Do not tell people to drop this jar into a Fabric instance.
- [ ] Same Core HTTP on `127.0.0.1:3853` (`/api/metrics`, `/api/execute`, `/api/market`).
- [ ] Create 6 required. Kinetic / Dynamo are real Create generators.
- [ ] `/api/devices` + paid `drainRate`. Drain default **80 bps**. Sneak-click sets drain 0–15.
- [ ] No free FE — Core must authorize output. Machines off when ticker is below Market **Off below factor**.
- [ ] Rebuild the NeoForge jar after changing drain / devices / chest cap.

## Drop risks

- Flipping `minecraft.enabled` default to true “to make demos easier”.
- Config save wiping `minecraft.market.*`.
- Re-adding a Node bridge next to Stream Core.
- Fabric-only notes that forget NeoForge (or the reverse).

## After-change verify

- [ ] Example config still has `minecraft.enabled: false` and `client_mod_url` / `server_mod_url` on 3852 / 3853.
- [ ] README feature list still mentions Dynamo, Kinetic, vault, chest.
- [ ] Integrations catalog still includes Minecraft.
