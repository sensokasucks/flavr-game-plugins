# Checklist — OpenTTD

Home: `games/openttd.py`, `games/openttd_admin.py`, `games/openttd_market.py`, `games/OPENTTD.md`, GS `gamescripts/FridgeChatFund`.

## Must keep

- [ ] Opt-in: `openttd.enabled` default **false**. Admin Port default **3977**.
- [ ] Works with vanilla and JGRPP via Admin Port. `admin_password` required.
- [ ] Commands (group `openttd`):
  - `!companies` / `!tickers` (public)
  - `!quote <id|name>` (public)
  - `!invest <id|name> <points>` (public)
  - `!ottdfund` (public)
  - `!ottdsay` (mod)
  - `!ottdpause` / `!ottdunpause` (mod)
- [ ] Chat Fund ledger is Core SQLite. Points debit via `store`. Map cash via FridgeChatFund `ChangeBankBalance`.
- [ ] **Do not** use vanilla / JGR 25% share slots. Trunk removed them (#10709). JGR `allow_shares` stays off on the stream server.
- [ ] No NewGRF / GS hack to restore shares. That path is closed.
- [ ] Overlays: `/overlay/openttd.html`, `/overlay/openttd-ticker.html`. API `GET /api/openttd/state`.
- [ ] Fridge Market may list the host / AI companies as a **price feed**. That listing is not a second Chat Fund and must not buy the 25% slots.
- [ ] Token split from Market: keep `!invest` / `!quote` / `!companies` on group `openttd`.
- [ ] `use_gamescript: true` by default so FridgeChatFund injects cash. Without GS, announce-only is acceptable; do not silently start clicking share buttons instead.
- [ ] Docs: `games/OPENTTD.md` stays accurate.

## Drop risks

- “Just use JGR allow_shares, it is easier than the GS.”
- Reusing `!tickers` for Fridge Market in a way that shadows the OpenTTD command without a priority rule.
- Putting Chat Fund balances in a new sqlite file.

## After-change verify

- [ ] Example config still has the `openttd:` block (host, admin_port, pounds_per_point, min/max invest, use_gamescript).
- [ ] FridgeChatFund folder still ships under `gamescripts/`.
- [ ] Admin Integrations / Sources still mention the OpenTTD overlays.
