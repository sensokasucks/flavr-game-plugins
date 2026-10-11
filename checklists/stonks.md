# Checklist — Gamer Stonks (points market plugin)

Home: `plugins/stonks/`. Design: `plugins/stonks/DESIGN.md`. Dashboard: **Games → Gamer Stonks** (`#plg-stonks-main`).
Was Stream Core's built-in Fridge Market (`core/market.py`) until October 2026.

## Must keep

- [ ] A *feature* plugin, opt-in: `stonks.enabled` default **false**. `provides: ["market"]`; command group `stonks` with alias `market`, so commands.json entries with `"group": "market"` follow the plugin.
- [ ] Settings live under `stonks:`; `config_moved_from: ["market"]` fills in anything not set from the old `market:` block.
- [ ] Chat commands stay `handler: core` with `special: market_buy | market_sell | market_tickers | market_portfolio`; the manifest's `specials` hands them to `execute`. Users never have to edit their `commands.json`.
- [ ] One share book: the plugin's `holdings` table. Games emit signals / flushes; they don't keep a second book. Points only move through Core's store (`spend_points` for buys, so two quick `!buy` can't go below zero).
- [ ] First start copies Core's old `market_holdings` once (read-only, `meta.core_holdings_copied`) and `data/market_tickers.json` once. Core's copies are never changed.
- [ ] Not OpenTTD Chat Fund. `!invest` stays a one-way cash injection on group `openttd`.
- [ ] Same addresses as the built-in market: `GET /api/market/state`, `GET /api/market/history`, `POST /api/market/signal`, `POST /api/market/dividend`, `/api/admin/market/...`, `/overlay/market*.html`. While the plugin is off they answer 503.
- [ ] The two POSTs are games only (`ctx.require_game`): 403 for browser requests, admin token needed from another device. The page's test payout uses `/api/admin/market/dividend` (admin token).
- [ ] Steam CCU via `GetNumberOfCurrentPlayers` only — **no steamcharts scrape**. Interval `stonks.steam_poll_sec` (default 1800).
- [ ] Per-signal cooldowns (`symbol` / `book` / `global`); the death dip must not be spawn-campable when the cooldown is > 0.
- [ ] Chatter tickers (`feed: chatter`): price from channel points, optional live link, streak bonus.
- [ ] Game tabs on the page come from each game's `plugin.json` `market` block, saved with `PUT /api/admin/plugins/{id}/settings`, applied live. Game listings are seeded from `market_books`; the plugin itself seeds `FRG`.
- [ ] Default Minecraft ticker `MINECRAF`, default Factorio ticker `FACTORIO`. Don't resurrect `STEVE` / `PWR` / `FACT` as defaults without updating the game's `config_defaults` too.

## Game hooks (Minecraft, Factorio)

- [ ] Games reach the tape through `ctx.service("market")` with `"after": ["market"]`, and cope with `None` (Gamer Stonks not installed or off).
- [ ] Dividend defaults for bridges that send no symbol come from the game's `dividend_defaults` class hook (`ctx.plugins.class_hook`).
- [ ] Chat Dynamo factor = stream power × average `price/base` of the game's `dynamo_symbols`, clamped.

## Drop risks

- Putting market code back into Core instead of this plugin.
- Breaking the old addresses (OBS sources and bridges use them).
- Dropping `specials` or the `market` alias, which silences `!buy` for everyone whose commands.json says `"group": "market"`.

## After-change verify

- [ ] `python -m pytest plugins/stonks -q` passes against Core main.
- [ ] Gamer Stonks page: Listings, Settings, each game tab, Investors (shows holders), Tape preview.
- [ ] `!buy FRG 20`, `!portfolio`, `!sell FRG all` through Integrations → command tester (not dry run).
