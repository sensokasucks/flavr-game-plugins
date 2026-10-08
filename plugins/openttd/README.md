# OpenTTD plugin (Stream Core 0.15)

Modular game slot: Admin Port + Chat Fund + optional Game Script cash injection.

## What chat can do

| Command | Who | Effect |
|---------|-----|--------|
| `!companies` / `!tickers` | public | List companies + cash + chat-funded totals |
| `!quote <id\|name>` | public | One company snapshot |
| `!invest <id\|name> <points>` | public | Spend points, announce in-game, inject cash if GS loaded |
| `!ottdfund` | public | Session Chat Fund totals |
| `!ottdsay <text>` | mod | `say` on the server |
| `!ottdpause` / `!ottdunpause` | mod | Pause the map |

Points come from Core’s existing SQLite ledger. Cash on the map comes from **FridgeChatFund** (`gamescript/FridgeChatFund` in this folder).

Vanilla share buttons are **not** used. JGRPP `allow_shares` should stay off on the stream server so viewers who also play cannot run the 25% loop.

## Server setup

1. Dedicated or listen server (JGRPP or vanilla 14+).
2. In `openttd.cfg` / secrets:
   - `admin_password` (required — Admin Port will not listen without it)
   - `server_admin_port = 3977`
3. Copy `gamescript/FridgeChatFund` (in this folder) into the OpenTTD `game/` folder and select it as the Game Script.
4. Core `config.yaml`:

```yaml
openttd:
  enabled: true
  host: "127.0.0.1"
  admin_port: 3977
  admin_password: "same-as-server"
  pounds_per_point: 1000
  min_invest_points: 10
  max_invest_points: 5000
  use_gamescript: true
```

5. Enable points (`points.enabled: true`) or `!invest` records a pledge with no debit.

## Overlays

- http://127.0.0.1:3850/overlay/openttd.html
- http://127.0.0.1:3850/overlay/openttd-ticker.html

## Not in this slice

Per-viewer AI companies / JGR share buys. Slot limit is 15 and two chat-owned companies recreate the share exploit. Next module can add a single Chat Fund holding AI if you want a named color on the map.
