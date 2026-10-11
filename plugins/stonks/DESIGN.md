# Gamer Stonks — design

Stream Core plugin (`plugins/stonks`, a *feature* plugin): a **points stock market** chat can trade, mods can list, games can price, and admins can shock with events. It was Stream Core's built-in "Fridge Market" until October 2026; this file was `docs/MARKET.md` in flavr-leftovers. Where this design still says "Core" for market code, read "the Gamer Stonks plugin".

Status: **tape, game vaults and chat trading (`!buy` / `!sell` / `!tickers` / `!portfolio`) ship**. Minecraft Dividend Dynamo + Smelt Chest and Factorio vaults flush through `POST /api/market/dividend` / poll. This is not OpenTTD Chat Fund — see [Relationship to OpenTTD](#relationship-to-openttd-chat-fund).

## Goals

1. Viewers spend Fridge points to **buy** holdings and **sell** them back for points at the live price.
2. Mods / admins can **list, halt, and delist** tickers from chat or the admin hub.
3. Game integrations get a **narrow hook** to list instruments, push price signals, fire **named game events**, and pay **dividends**.
4. Each active game can list the **streamer as a company**. In-game death (and other events) move that ticker.
5. The streamer can feed an in-game **dividend vault** (power / items / cash). The vault eats the input and pays holders.
6. Admin hub manages the **core book** and **per-game books**, plus **market events**.
7. Events keep the tape interesting without needing a real order book.

Chat should feel like it has skin in the run: cheer the vault filling, groan on a death dip, pile into the streamer ticker before a boss.

Non-goals for v1: shorting, limit orders, options, multi-currency, dividends paid in *game* items, or replacing OpenTTD `!invest` cash injection.

## Where it lives

A plugin, not part of Core. Core keeps points (the store), chat, permissions and the dashboard;
Gamer Stonks keeps the tickers, shares, the price loop and its own page.

```
adapters ── ChatEvent ──► Stream Core ── Store (points ledger)
                            │
                            ├─ commands.json: buy / sell / tickers / portfolio
                            │    handler "core", special market_* ──► Gamer Stonks execute()
                            └─ plugins/
                                 ├─ stonks (provides "market")
                                 │    tape.py      MarketTape: tickers, prices, history
                                 │    holdings.py  shares, in data/plugins/stonks/stonks.db
                                 │    routes.py    /api/market/*, /api/admin/market/*
                                 └─ minecraft, factorio ... ── ctx.service("market")
                                 │
                    game mods ── POST /api/market/signal
                                 POST /api/market/dividend
```

Both POSTs are for games only (`ctx.require_game`): a request from a browser (`Origin` or `Sec-Fetch-Site` header) gets 403,
even from a `127.0.0.1` page. In LAN mode a bridge on another device sends the admin token as
`X-Admin-Token` (or `?token=`); bridges on the same PC send nothing extra.

| Piece | Path |
|-------|------|
| Tape (tickers, prices) | `tape.py` |
| Shares + dividends | `holdings.py` (own database `data/plugins/stonks/stonks.db`) |
| Start / stop, price loop, chat commands, signals, dividends | `plugin.py` |
| Routes | `routes.py` |
| Chat commands | Core's `config/commands.json` (group `market`, `handler: core`, `special: market_*`) and this plugin's `commands.json`; Core hands them over through the manifest's `specials` |
| Dashboard page | `pages/` (**Games → Gamer Stonks**, `#plg-stonks-main`; old `#market` links land here) |
| Public snapshot | `GET /api/market/state`, `GET /api/market/history` |
| Ingest (games only) | `POST /api/market/signal`, `POST /api/market/dividend` |
| Overlays | `overlay/market.html` (tape), `market-board.html` (grid), `market-chart.html`, `market-cycle.html`, served at `/overlay/...` |
| Settings | `stonks:` in `config.yaml` (anything not set there comes from the old `market:` block) |

Opt-in: `stonks.enabled` defaults **false** (Settings → Plugins). Command group `market` follows the plugin (`command_group.aliases`).

Moving in from the built-in market (first start): the `market:` settings fill in `stonks:`, `data/market_tickers.json` is copied to `data/plugins/stonks/tickers.json`, and Core's old `market_holdings` table is copied into the plugin's database once (Core's copy is left alone).

Game mods already talk to Core (Factorio bridge `:3847`, Minecraft server-mod `:3853`). They should **not** implement a second ledger. They emit a signal; the plugin applies the rule.

## Relationship to OpenTTD Chat Fund

OpenTTD `!invest` is a **one-way subsidy**: debit points, inject map cash via FridgeChatFund. Viewers do not own a sellable share.

Fridge Market is a **points-in / points-out book**. Holdings never touch the OpenTTD bank.

They coexist:

- Keep `!invest` / `!quote` / `!companies` on group `openttd`.
- Market uses **different tokens** so the router does not fight (`!buy`, `!sell`, `!tickers`, `!ticker`, `!portfolio`).
- The OpenTTD plugin (`plugins/openttd/`) may list the host company *and* AI companies on the market. That listing is a price feed + death/bankruptcy signals, not a second Chat Fund.

## Currency and units

- Cash side = existing `users.points` + `points_ledger` (`source=market` or `source=dividend`).
- Share side = integer **milli-shares** internally (display as whole shares). Avoids float dust.
- Price = points per share, stored as integer **milli-points** (display 2 decimals).
- Buy sizing is **points first** (`!buy PWR 50` spends 50 points). Optional share sizing later (`!buy PWR 10s`).
- Sell sizing is **shares first** (`!sell PWR 3`, `!sell PWR all`). Optional `!sell PWR 50p` (sell enough to raise ~50 points).
- Dividends are **points**, paid pro-rata to current holders of that symbol.

House is the counterparty for trades. No viewer-to-viewer matching in v1.

## Instruments

Each ticker:

| Field | Notes |
|-------|-------|
| `id` | Stable slug (`pwr`, `fridge`, `ottd-1`) |
| `symbol` | Short tape code, unique, `A-Z0-9.` max 8 (`PWR`, `FACT`, `STEVE`) |
| `name` | Display name |
| `book` | `core` or `game:<id>` (`game:factorio`, `game:minecraft`, …) |
| `source` | `admin`, `game`, or `streamer` |
| `role` | `plain` / `streamer` / `temp` |
| `status` | `listed` / `halted` / `delisted` |
| `price` | Current mid |
| `base_price` | Anchor the model mean-reverts toward |
| `min_price` / `max_price` | Hard clamp |
| `game_factor` | Multiplier last pushed by a game (default 1.0) |
| `event_factor` | Multiplier from active events (default 1.0) |
| `listed_at` / `updated_at` | |
| `notes` | Admin blurb |
| `personality` | `blue_chip` / `growth` / `meme` / `sleepy` / `volatile` / `custom` |
| `noise_bps` / `revert_bps` / `drift_bps_per_hour` / `jump_p` / `jump_bps` | Per-ticker walk; 0 jump = off |
| `walk` | `on` / `off` |
| `feed` | `walk` / `game` / `steam` / `manual` |
| `steam_appid` / `steam_mode` / `steam_weight` / `steam_baseline` | Official CCU peg |

Delist does **not** wipe holdings. Trading stops; admin can force-liquidate at last price or leave bags frozen until relist.

When a game stops: tickers in `game:<id>` go **halted** (price frozen, no buy/sell, vault payouts queue or drop — see dividends). They do not auto-cashout.

## Streamer company (per game)

The streamer is a listing on each active game book, not a special wallet.

When a game integration starts and `market.list_streamer` is on:

1. Core (or the game via `broker.ensure_streamer()`) lists one instrument:
   - `role=streamer`, `source=streamer`
   - `book=game:<id>`
   - symbol from that game’s config (`factorio.market.streamer_symbol`, fallback `market.streamer_symbol`)
2. That symbol is the default target for `player_death`, vault dividends, and “the run” overlays.
3. One streamer ticker per game book. The core-book house ticker `FRG` stays the “stream itself” stock (raids, subs, dead air) and is *not* killed by a Factorio death unless a rule says so.

Suggested defaults:

| Game | Symbol | Name |
|------|--------|------|
| Factorio | `FACT` | Streamer factories |
| Minecraft | `STEVE` | Streamer (rename to IGN in config) |
| OpenTTD | `HOST` | Host company |
| Granvir | `GV` | Streamer |
| Core (always) | `FRG` | Fridge / the stream |

Admin can rename symbols. Chat still uses `!buy FACT 40`.

### Death dip

Games already know deaths (Factorio `deaths` on the stats overlay, Minecraft client HP). On a **rising death count** or an explicit death event:

```
broker.signal(
    name="player_death",
    book="game:factorio",
    symbol="FACT",          # optional; default = streamer ticker for that book
    payload={"player": "Sensoka", "deaths": 4},
)
```

Default built-in action (also expressible as a JSON rule, so it can be turned off):

- `add_pct` −8% on the streamer ticker (`market.death_return`)
- cooldown `market.death_cooldown_sec` so a lava loop does not nuke the floor
- announce: `FACT -8% — Sensoka died`
- overlay flash + tape goes red

Respawn does **not** auto-rebound. Recovery is vault dividends, kills, research, or chat buying the dip.

Optional extra rules (starter pack, disabled until the streamer likes them):

- `player_death` also +noise for 30s (panic)
- 3 deaths in 2 minutes → short halt on that ticker (“funeral”)
- `boss_kill` / `biter_wave_cleared` → partial rebound

## Dividend vault (in-game sink)

Opposite of Chat Dynamo.

| | Chat Dynamo | Dividend vault |
|--|-------------|----------------|
| Direction | Stream → game | Game → stream |
| Input | viewers / CPM / commands | power, items, cash the streamer feeds |
| Output | electricity / RF / RPM | points to holders of the streamer ticker |

The streamer *chooses* to sacrifice factory surplus. Chat yells at them to feed the vault instead of expanding.

### Flow

```
In-game vault block eats input
        │  joules / items / pounds
        ▼
Game mod or bridge tallies a payout unit
        │
        ▼
POST /api/market/dividend  { symbol, work, unit, reason }
        │
        ▼
MarketEngine
  points = clamp(work * points_per_unit, 0, remaining hourly cap)
  pay pro-rata to holders of symbol
  ledger source=dividend
  announce + overlay
```

`work` is whatever the game can measure honestly:

| Game | Vault idea | Unit |
|------|------------|------|
| Factorio | `fridge-dividend-vault` electric-energy-interface that only **consumes**. Streamer wires surplus steam/solar into it. | MJ |
| Minecraft | Block + hopper / chest that deletes items (or drains RF if a dynamo-adjacent BE). | item-count or RF |
| OpenTTD | Game Script “Chat Treasury” that `ChangeBankBalance` **down** on the host company when the streamer clicks fund / auto-tithe. | pounds |
| Granvir | Later; same POST body once the plugin can meter something. |

Core does not need to understand MJ vs RF. Each game config has `points_per_unit`. Factorio might be `0.02` points per MJ; Minecraft `1` point per 8 cobble, etc.

### Who pays the points?

Dividends are stream points, not factory items.

| `market.dividend.source` | Meaning |
|--------------------------|---------|
| `mint` (default) | Print points, hard **hourly cap** (`hourly_cap_points`) |
| `fees` | Pay from accumulated market fees this session; stop when the pot is empty |
| `treasury` | Debit a configured user (`treasury_user_id`, usually the streamer) |

`mint` is the fun stream default. Cap it. `fees` is the “sustainable” mode. `treasury` is if the streamer wants to personally fund bagholders.

### Payout rules

- Only `listed` tickers. Halted books: queue up to one tick of work or drop (config `on_halt: queue|drop`, default `queue` with a small cap).
- Pro-rata by milli-shares. Dust below `min_payout` goes to the largest holder (or is burned — default burn, so we do not invent pennies).
- Same user holding 40% of `FACT` gets 40% of that payout.
- Announce once per payout, not per holder: `FACT dividend 80 pts from the vault (2.0 / share)`. Whisper-level per-user totals live on `!portfolio`.
- Vault can also nudge price: small `add_pct` on payout (`dividend_price_bump`, default +1%) so feeding the machine is visible on the tape, not only in balances.

### Anti-farm

- Hourly cap across all vaults combined (and optional per-symbol cap)
- Minimum work before a flush (do not POST every tick)
- Game must verify the entity exists and actually consumed energy/items — Core trusts the local bridge, which is loopback-only
- No payout if the symbol has zero holders (work still “burned” in-game; streamer wasted the steam)

## Game hooks

Games never touch market SQL. They call a broker Core injects at start, or POST the same payloads to loopback HTTP (for mods that cannot import Python).

```python
class MarketBroker:
    async def list(self, *, book: str, symbol: str, name: str,
                   base_price: float, source_id: str,
                   role: str = "plain",
                   min_price=1, max_price=None) -> dict: ...

    async def ensure_streamer(self, *, book: str, source_id: str,
                              symbol: str, name: str,
                              base_price: float) -> dict: ...

    async def delist(self, symbol: str, *, source_id: str) -> None: ...

    async def set_factor(self, symbol: str, factor: float, *, source_id: str) -> None: ...

    async def apply_return(self, symbol: str, frac: float, *, source_id: str, reason: str) -> None: ...

    async def signal(self, *, name: str, book: str, source_id: str,
                     symbol: str | None = None, payload: dict | None = None) -> dict: ...

    async def dividend(self, *, symbol: str, source_id: str,
                       points: int | None = None,
                       work: float | None = None, unit: str | None = None,
                       reason: str = "vault") -> dict: ...

    async def snapshot(self, book: str | None = None) -> dict: ...
```

`source_id` is the game id. A game may mutate only instruments on `book=game:<id>`. It cannot overwrite an admin `core` ticker. `ensure_streamer` is the one exception that upserts `role=streamer` on that book.

Optional on `BaseGameIntegration`:

```python
async def on_market_start(self, broker: MarketBroker) -> None:
    """List streamer ticker + any extra game stocks."""

async def on_market_tick(self, broker: MarketBroker, snap: dict) -> None:
    """Sparse factor updates (power, company value). Not every frame."""
```

HTTP ingest (token = `points.admin_token` or a dedicated `market.ingest_token`, loopback only):

```
POST /api/market/signal
{ "name": "player_death", "game": "factorio", "symbol": "FACT",
  "payload": { "player": "Sensoka", "deaths": 4 } }

POST /api/market/dividend
{ "game": "factorio", "symbol": "FACT", "work": 2500, "unit": "mj",
  "reason": "vault" }
```

### Standard signal names

Games and `market_events.json` share this vocabulary. Unknown names still log and can match a custom rule.

| Signal | Typical source | Default Core behavior |
|--------|----------------|------------------------|
| `player_death` | MC / Factorio death | Streamer ticker `death_return` |
| `player_respawn` | MC | none (optional noise) |
| `boss_kill` | MC / GV | Streamer ticker +% |
| `player_kill` | MC / Factorio biters | small +% or `KILL` ticker |
| `research_done` | Factorio | `SCI` +% |
| `biter_wave` | Factorio | `FACT` −% / `PWR` −% |
| `factory_blackout` | Factorio power = 0 | halt `PWR` briefly |
| `vault_payout` | any vault flush | already handled by `dividend()`; signal is for overlay |
| `company_bankrupt` | OpenTTD | halt that `OTTD.*` |
| `year_recession` | OpenTTD | book-wide −% |
| `milestone` | any | announce + small bump |

A game plugin can invent `nuked_the_spawn`. Admin writes a rule with `trigger.type=game.signal` + `name=nuked_the_spawn`. No Core change.

### Suggested listings (slice 4+)

| Game | Symbol | Signal / factor |
|------|--------|-----------------|
| Factorio | `FACT` | streamer company; death / vault |
| Factorio | `PWR` | factory power / Chat Dynamo |
| Factorio | `SCI` | research |
| Minecraft | `STEVE` | streamer; death / vault |
| Minecraft | `HP` | health factor |
| Minecraft | `KILL` | session kills |
| OpenTTD | `HOST` | host company + treasury tithe |
| OpenTTD | `OTTD.<id>` | `company_price()` |
| Core | `FRG` | raids / subs / dead air |

Games should **push sparse signals**, not rewrite price every frame.

## Chat commands

Group `market`, bind `market`. Prefix is whatever Core uses (`!`).

| Command | Who | Effect |
|---------|-----|--------|
| `!tickers` / `!market` | public | Open books + last / Δ |
| `!ticker <sym>` | public | One quote + your position |
| `!buy <sym> <points>` | public | Debit points, credit shares |
| `!sell <sym> <shares\|all>` | public | Debit shares, credit points |
| `!portfolio` / `!bags` | public | Positions + unrealized Δ + dividends today |
| `!ipo <sym> <name> [price]` | mod | List on the `core` book |
| `!delist <sym>` | mod | Status → delisted |
| `!halt <sym>` / `!unhalt <sym>` | mod | Freeze / resume one ticker |
| `!shock <sym\|all> <+/-pct>` | admin | Manual event, logged |
| `!dividend <sym> <points>` | admin | Manual payout (test / charity) |

OpenTTD tokens stay untouched.

Guards: `min_trade_points`, `max_trade_points`, per-user `trade_cooldown_sec`, cannot sell more than held, cannot buy a halted/delisted/missing symbol, game-book symbols only trade while that game is running (otherwise halted).

## Pricing model (v1)

Tick every `market.tick_sec` (default 5s):

```
flow      = impact from net buy/sell points since last tick
noise     = small gaussian, capped
raw       = price * (1 + flow + noise) * game_factor * steam_factor * viewer_factor * event_factor
price     = clamp(lerp(raw, base_price, revert_bps), min_price, max_price)
```

Then decay `event_factor` toward 1.0 so shocks fade without a second admin click.

Trade impact (applied immediately on fill):

```
impact_frac = sign * min(cap, points_spent * impact_bps_per_point / 10_000)
```

Circuit breaker: if a tick would move more than `circuit_breaker_pct` from the session open (or last halt resume), halt that symbol for `halt_sec`.

**No order book.** Fill at mid ± spread. `fee_bps` on buy and sell.

Death dips and vault bumps use `apply_return` / `add_pct` and still respect the clamp + breaker.

## Admin Market desk

The current **Market** tab is vault wiring (Dynamo symbols, RF/XP flush, grant shares). That stays as a **Vaults** sub-panel. The desk itself becomes a book manager — create tickers, give each one a personality, optionally pin it to a live feed.

Four sub-panels on one tab (same pattern as Credits: cards, hot-apply, no Core restart for tape edits):

| Sub-panel | Job |
|-----------|-----|
| **Book** | List / create / edit / halt / delist tickers |
| **Feeds** | Steam CCU + game hooks + last sample |
| **Events** | Rules, fire-now, cooldown, last log |
| **Vaults** | Existing Minecraft / Factorio machines + grant shares |

Status strip at the top: enabled, listed count, last event, Steam poll health, vault hour used.

Integrations tab keeps a small Market card (overlay URLs, test death, test dividend). Do not duplicate the book table there.

### Book — create and manage tickers

Filter chips: All / Core / Factorio / Minecraft / OpenTTD / Granvir / Steam / Halted.

Table columns: symbol, name, book, feed, personality, price, Δ session, holders, status. Streamer-role rows stay pinned at the top of their book.

**New ticker** form (also the edit drawer):

| Field | Rules |
|-------|--------|
| Symbol | `A-Z0-9.` max 8, unique. Locked after first trade so overlays and holdings do not break. Rename = delist + new symbol. |
| Name | Display only |
| Book | `core` or `game:<id>` |
| Role | `plain` / `streamer` / `temp` |
| Status | listed / halted / delisted |
| Base price | Mean-revert anchor |
| Price | Set now (admin override, logged as `admin_set`) |
| Min / max | Hard clamp |
| Notes | Optional blurb |

Buttons per row: Edit, Halt / Resume, Shock ±%, Reset to base, Delist. Delist does not wipe holdings.

`POST /api/admin/market/tickers` create. `PATCH /api/admin/market/tickers/{sym}` edit. Seed listings (`FRG`, `FACT`, …) are editable the same way; `source=game` fields that games own (`game_factor`) stay read-only in the form.

### Personality — realistic random walk

Global `market.noise_bps` is the fallback. Each ticker can override so the tape is not one blob moving in lockstep.

Per ticker:

| Field | Meaning |
|-------|---------|
| `personality` | Preset id, or `custom` |
| `noise_bps` | Tick-to-tick σ (higher = jumpy) |
| `revert_bps` | Pull toward `base_price` |
| `drift_bps_per_hour` | Slow bias. +8 ≈ mild bull, −8 mild bear |
| `jump_p` | Chance per tick of a larger shock (0 = off) |
| `jump_bps` | Size of that shock (σ of the jump) |
| `walk` | `on` / `off`. Off = only feeds + events move it |

Presets (admin dropdown, writes the sliders):

| Preset | Feel |
|--------|------|
| `blue_chip` | Low noise, strong revert (house `FRG`) |
| `growth` | Medium noise, small +drift |
| `meme` | High noise, jumps on, weak revert |
| `sleepy` | Almost flat — good for a Steam-pegged name |
| `volatile` | High noise, no jumps, weak revert |
| `custom` | Whatever the sliders say |

Tick path becomes:

```
noise  = N(0, noise_bps / 1e4)
jump   = N(0, jump_bps / 1e4)   if rand() < jump_p else 0
drift  = drift_bps_per_hour / 1e4 * tick_sec / 3600
raw    = price * (1 + noise + jump + drift + flow) * game_factor * steam_factor * event_factor
price  = clamp(lerp(raw, base_price, revert_bps), min, max)
```

Admin **Shock ±%** is a one-shot `apply_return` (bypasses cooldown). A “Roll news” button on the Events panel fires the existing `random` / flash-crash rules.

Do not simulate a full order book. Personality + jumps is enough for a stream tape to look alive when chat is quiet.

### Feeds — Steam charts and friends

Yes — a ticker can track **Steam concurrent players**. Use Valve’s own endpoint, not steamcharts.com (no official API; scraping that site will break).

```
GET https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={id}
→ { "response": { "player_count": 123456, "result": 1 } }
```

No Steam Web API key required for CCU. Optional extra (also keyless) for the display name:

```
GET https://store.steampowered.com/api/appdetails?appids={id}
```

What we will **not** do: scrape SteamDB / steamcharts.com HTML, pull store *price* as the stock price (it barely moves), or hit Steam every tick.

#### How a Steam ticker is wired

On the ticker form:

| Field | Example |
|-------|---------|
| Feed | `walk` / `game` / `steam` / `manual` |
| Steam App ID | `427520` (Factorio), `730` (CS2), `1245620` (Elden Ring) |
| Peg mode | `delta` or `ratio` |
| Baseline CCU | Snapshot when you click **Set baseline** (ratio mode) |
| Steam weight | 0–1, how hard CCU pushes vs the random walk |

Peg modes:

- **delta** (default) — each successful poll applies `apply_return(pct_change_in_ccu * weight)`. A 10% CCU drop with weight 0.5 moves the stock −5%. Feels like a live chart.
- **ratio** — `steam_factor = lerp(1, ccu / baseline, weight)`. Price stays pinned to “how busy is this game vs the day you listed it.” Better for a long-running “Factorio Inc” name.

Poll loop (Core, not the overlay):

- One shared worker, default every **10 minutes** per distinct App ID
- Cap: 20 Steam-backed tickers
- Cache last CCU + ts on the instrument
- HTTP fail / `result != 1`: keep last factor, mark feed `stale` in the admin row (do not invent a crash)
- Loopback-only Core already; this is the one outbound call the market makes

Admin Feeds panel: App ID, last CCU, last poll, stale flag, **Poll now**, **Set baseline**. Search-by-name is out of scope (type the App ID; SteamDB / store URL is fine reference).

Game feeds stay as they are (`game_factor` from Factorio power, OpenTTD company value, death signals). `manual` means walk off + no feed — admin shocks only.

A ticker can have **walk + steam** at the same time (weight < 1). That is the “realistic market that still reacts to Factorio being on sale this weekend” look.

### Concurrent players → price

Two different “concurrent” numbers, two jobs:

| Source | What it is | Default target |
|--------|------------|----------------|
| **Steam CCU** | Players in that *game* worldwide (`GetNumberOfCurrentPlayers`) | Tickers with `feed=steam` (`FACT` → Factorio App ID `427520`) |
| **Stream viewers** | People in *this* chat (Core `metrics.total_viewers`) | House ticker `FRG`, optional core-book bias |

Do not point `FRG` at Steam’s global online count. That number is tens of millions and has nothing to do with the stream.

#### Steam CCU math (per ticker)

Raw `ccu / baseline` is a bad peg. CS2 swinging 80k players would floor a stock; a 400-player indie would never move. Use a **log band**, then damp:

```
log_now  = log(max(ccu, 1))
log_base = log(max(baseline, 1))
raw      = (log_now - log_base) / max(log_span, 0.15)
steam_factor = 1 + weight * clamp(raw, -band, +band)
```

Defaults: `weight=0.45`, `band=0.25` (CCU alone cannot push more than ±25%), `log_span=log(2)` so a **2× player count** is a full-band move.

Between Steam polls (10 min) `steam_factor` is **held**. The random walk still ticks, so the chart is not a 10-minute staircase.

Delta mode (admin option) is the same formula but `baseline` is the **previous poll**, not the listing-day snapshot. Better for “sale week / patch day” spikes. Ratio mode is better for a name you want pegged for months.

Admin **Set baseline** stores current CCU so you can reset after a patch or a dead hour.

#### Stream viewers math (house tape)

Same shape, different input:

```
viewer_factor = 1 + weight * clamp(
    (log(viewers+1) - log(viewer_baseline+1)) / log(2),
    -band, +band
)
```

`viewer_baseline` defaults to `metrics.maxViewersForFull` (already in config, default 500) or a snapshot when you enable the feed. Apply to `FRG` by default. Optional `market.viewer_targets: [FRG]` or `book:core`.

A raid that triples viewers lifts `FRG` without waiting for a raid event rule. The raid rule can still add a one-shot banner on top.

#### What does *not* use CCU

- Death dips, vault dividends, chat buy/sell impact — those stay event / flow.
- In-game company value (OpenTTD) stays `game_factor`.
- Steam **store price** / review score — not used. CCU is the live number.

#### Defaults if you say nothing

- `FACT` / `PWR` can take Factorio CCU (`427520`) at weight 0.45, sleepy walk.
- `STEVE` does **not** auto-bind Minecraft CCU unless you type an App ID (which Minecraft?).
- `FRG` takes stream viewers, not Steam.
- Caps stay on so a Steam outage or a 10× sale spike cannot print or wipe the book.

### Events + Vaults

Unchanged from the earlier spec. Vault cards already in the tab stay. Events get Fire now + enable toggles. Cooldown fields stay on each rule (`cooldown_sec` 0 = off).

### Admin API (desk)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/admin/market` | Book + vaults + steam health (already started) |
| POST | `/api/admin/market/tickers` | Create |
| PATCH | `/api/admin/market/tickers/{sym}` | Edit personality / feed / price |
| POST | `/api/admin/market/tickers/{sym}/halt` | Halt / resume |
| POST | `/api/admin/market/tickers/{sym}/shock` | `{ "pct": -8 }` |
| DELETE | `/api/admin/market/tickers/{sym}` | Delist |
| POST | `/api/admin/market/steam/poll` | Force CCU refresh |
| POST | `/api/admin/market/steam/baseline` | Snapshot current CCU as baseline |

Ticker definitions persist in SQLite (`market_instruments` plus personality / feed columns). Preset ids are just starting values for those columns.

## Market events

A rule is JSON, not code:

```json
{
  "id": "raid-bull",
  "enabled": true,
  "label": "Raid rally",
  "trigger": { "type": "alert", "kind": "raid", "min_viewers": 5 },
  "cooldown_sec": 180,
  "actions": [
    { "type": "mult", "target": "all", "factor": 1.08, "decay_sec": 120 },
    { "type": "announce", "text": "Raid rally — tape is green" }
  ]
}
```

Streamer death as a rule (the engine also has a built-in fallback if this file omits it):

```json
{
  "id": "streamer-death",
  "enabled": true,
  "label": "Streamer down",
  "trigger": { "type": "game.signal", "name": "player_death" },
  "cooldown_sec": 20,
  "cooldown_scope": "symbol",
  "actions": [
    { "type": "add_pct", "target": "streamer", "pct": -8 },
    { "type": "announce", "text": "{symbol} {pct}% — {payload.player} died" }
  ]
}
```

`target: streamer` means “the `role=streamer` ticker on the signal’s book”.

### Optional cooldowns

Every rule and every raw `game.signal` can set `cooldown_sec`. **Omit it or set `0` for no cooldown.** Spawn-camp deaths should keep a cooldown.

| Field | Default | Meaning |
|-------|---------|---------|
| `cooldown_sec` | `market.death_cooldown_sec` (20) for `player_death`; `market.signal_cooldown_sec` (15) for other signals; `0` = off | Seconds before the same key can fire again |
| `cooldown_scope` | `symbol` | `symbol` — FACT death does not block STEVE; `book` — one shot per game; `global` — one shot for that trigger name across the whole market |

Blocked signals are logged (`retry_in`) and do **not** move price. Admin “Fire now” bypasses cooldown. Manual `!shock` bypasses cooldown.

### Triggers

| Type | Why it is fun |
|------|----------------|
| `manual` | Admin “Fire” button |
| `interval` | Heartbeat news every N minutes |
| `clock` | Top of hour / “closing bell” |
| `random` | Poisson “breaking news” so dead chat still has a tape |
| `alert.raid` | Raid size scales the shock |
| `alert.sub` / `gift_bomb` | Sub bomb melt-up |
| `metrics.cpm` | Chat on fire → volatility up |
| `metrics.power` | Chat Dynamo / viewer power crosses a band |
| `metrics.viewers` | Milestone (100, 500) |
| `flow` | N buys in 30s on one symbol (squeeze) |
| `game.signal` | Named in-game event (`player_death`, `research_done`, …) |
| `dividend` | After a vault flush (price bump + banner) |
| `circuit` | Auto-halt after a limit move |

Skip for v1: weather APIs, sports scores, scraping steamcharts.com / SteamDB. Steam CCU uses Valve’s official player-count endpoint only.

### Actions

| Type | Effect |
|------|--------|
| `mult` | Multiply `event_factor` on `all`, one `book`, `streamer`, or one `symbol` |
| `add_pct` | One-shot return |
| `halt` / `resume` | Trading freeze |
| `list_temp` | Spawn a ticker that auto-delists after `ttl_sec` (raid IPO) |
| `noise` | Raise tick noise for a window |
| `announce` | Chat reply + overlay flash |
| `fee` | Temporarily change `fee_bps` |
| `dividend` | Pay N points (or `work` mapped through config) to holders of `target` |

Decay is mandatory on `mult`.

### Starter pack (all optional, death + vault on by default)

1. **Opening bell** — clock, unhalt, +2%.
2. **Closing bell** — clock, halt 30s, announce session winners + dividends paid.
3. **Raid rally** — raid alert, +6–12% scaled by viewers, temp ticker `RAID`.
4. **Gift squeeze** — gift bomb, +8% on `FRG`.
5. **Dead air** — CPM floor, −3% drift.
6. **Chat on fire** — CPM spike, noise up, small green bias.
7. **Flash crash** — rare random −12% then +7% recover.
8. **Circuit halt** — built-in.
9. **Streamer down** — `player_death` → streamer ticker `death_return`.
10. **Funeral** — 3 deaths / 2 min → short halt on that ticker.
11. **Boss tax / rebound** — `boss_kill` → streamer ticker +6%.
12. **Research boom** — Factorio `research_done` → `SCI` +10%.
13. **Biter scare** — `biter_wave` → `FACT`/`PWR` −5%.
14. **Recession year** — OpenTTD `year_recession` → `OTTD.*` −8%.
15. **Vault flush** — `dividend` trigger → +1% on that symbol + banner.

## Persistence

What ships: shares in the plugin's own SQLite file `data/plugins/stonks/stonks.db` (table `holdings`:
`user_id`, `symbol`, `milli_shares`, plus `meta`), and the ticker list in
`data/plugins/stonks/tickers.json`. Points stay in Core's `data/stream_core.db`; buying, selling
and dividends go through Core's store. Price history is kept in memory.

Planned (not built): trades, ticks, event log, dividends and fee pot tables. Event *definitions*
would live in a `market_events.json`.

Open: merging two users on Core's Users page doesn't move their shares (it didn't before the move either).

## Overlays

Transparent Webpage sources. They poll `/api/market/state` + `/api/market/history` while Gamer Stonks is on (they answer 503 while it is off).

| Source | URL | Use |
|--------|-----|-----|
| Live ticker | `/overlay/market.html` | Thin scrolling tape for the top or bottom of the layout |
| Board | `/overlay/market-board.html` | Quote cards + sparklines |
| Chart | `/overlay/market-chart.html` | TV-style line graph (hero or grid) |
| Cycle | `/overlay/market-cycle.html` | Playlist — one line chart at a time |

Query flags:

| Flag | Where | Effect |
|------|-------|--------|
| `?symbols=FACT,FRG` | all | Limit tickers |
| `?symbol=FACT` | chart | Hero symbol |
| `?book=factorio` | all | One game book |
| `?speed=80` | ticker | Scroll pixels / sec |
| `?layout=hero\|grid\|row` | chart | One big graph vs cards |
| `?dwell=8` | cycle | Seconds on each symbol |
| `?points=120` | chart | History depth |
| `?bare=1` | board/chart | No stage chrome |
| `?solid=1` | board/chart | Opaque background |

No CDN. Canvas charts only. Gold / green / red to match the other Fridge overlays.

## Implementation slices

| Slice | Ship |
|-------|------|
| **0** | This doc + preview tape + ticker/board/chart overlays + cooldown gate |
| **1** | Engine, schema, buy/sell/list/halt, chat commands, house `FRG` |
| **2** | Admin Market **desk**: ticker CRUD, personalities, shock, halt |
| **2b** | Steam CCU feed (GetNumberOfCurrentPlayers, 10 min poll) |
| **3** | Event engine + starter rules (including death / raid / bells) |
| **4** | `MarketBroker` + `ensure_streamer` + HTTP `/signal` + one game death feed |
| **5** | Dividend engine + one vault block (Factorio consumer **or** Minecraft sink) |
| **6** | Second game + OpenTTD host ticker + raid IPO + holdings merge |

Do not start slice 4 until 1–2 feel good on a live stream. A wrong death hook is louder than a missing one.

Vault blocks live in the game projects in [flavr-game-plugins](https://github.com/sensokasucks/flavr-game-plugins) (`fridge-factorio-stats` mod, `fridge-minecraft` server-mod), not in Core. They only POST work.

## Open decisions (defaults)

1. **Buy unit** — points spent.
2. **Game unload** — halt, no auto-sell.
3. **First game hook** — Factorio streamer ticker + death (stats already have `deaths`). Vault block is slice 5.
4. **House ticker `FRG`** — yes, core book, base 10.
5. **Shorting** — no.
6. **Dividend source** — `mint` + hourly cap.
7. **Death rebound** — none; chat and vault have to buy the dip.

## Anti-abuse recap

- Fees on both sides
- Size caps + cooldown
- Impact + circuit breaker
- Halted game books
- Death cooldown
- Dividend hourly cap + min work flush
- Loopback ingest + admin token
- Mod list rights, admin shock / manual dividend
- Full trade + dividend log
- Points debit is the same `adjust_points` path (no second wallet)
