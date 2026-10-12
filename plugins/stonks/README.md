# Gamer Stonks

A points stock market for the stream, as a Stream Core plugin. Tickers for the games you play,
for you and for your chatters; prices that wander, follow how many people play a game on Steam
and react to game events (a death dips the streamer's ticker); chat buys and sells shares with
channel points; holders get dividends when a game's vault flushes. Overlays show the tape.

It used to be built into Stream Core as "the Fridge Market". Same overlay and API addresses,
same chat commands.

## Install

1. Copy this `stonks` folder into Stream Core's `fridge-stream-core\plugins\`
   (you end up with `fridge-stream-core\plugins\stonks\plugin.json`), or point Core at this
   repo's `plugins` folder with `STREAM_CORE_PLUGINS_DIR`.
2. Restart Stream Core. **Gamer Stonks** shows under **Settings → Plugins** (under *Features*).
3. Tick **Enabled**, save, restart Core again.
4. Open **Games → Gamer Stonks** in the dashboard.

The first time it starts it brings over what the built-in market had: your `market:` settings,
your tickers (`data/market_tickers.json`) and every viewer's shares. Nothing is deleted from Core.

## In chat

| Command | Does |
|---------|------|
| `!buy SYMBOL 50` (`!long`) | spend 50 points on shares at the live price |
| `!sell SYMBOL 2`, `!sell SYMBOL all` (`!short`) | sell shares back for points |
| `!tickers` (`!stocks`, `!market`) | list prices |
| `!portfolio` (`!shares`, `!holdings`) | your shares |

They are in the *market* command group (Settings → Command groups) and do nothing while the
plugin is off.

## Overlays (OBS Browser sources)

| Overlay | Address |
|---------|---------|
| Ticker tape | `http://127.0.0.1:3850/overlay/market.html` |
| Board (cards + sparklines) | `http://127.0.0.1:3850/overlay/market-board.html` |
| Chart | `http://127.0.0.1:3850/overlay/market-chart.html?symbol=FRG` |
| Chart playlist | `http://127.0.0.1:3850/overlay/market-cycle.html?symbols=FRG,MINECRAF&dwell=8` |

They are also listed in Core's **Sources & overlays** address builder.

## For games and developers

- Other plugins get the tape with `ctx.service("market")` (add `"after": ["market"]` to their
  `plugin.json`). Games list their tickers with `market_books` and their own knobs with a
  `market` block in `plugin.json`; each such game gets a tab on the Gamer Stonks page.
- Game bridges post to `POST /api/market/signal` and `POST /api/market/dividend` (games only:
  web pages get 403).
- Design and pricing model: [DESIGN.md](DESIGN.md). Contract: [checklists/stonks.md](../../checklists/stonks.md).
- Tests: `python -m pytest plugins/stonks -q` from the repo folder.
