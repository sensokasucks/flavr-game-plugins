# Checklist — Schedule I

Home: `fridge-schedule1/` (MelonLoader `mod/`, `mock/mock_server.py`). Core side: python plugin `plugins/schedule1/`
(plugin.py, roster.py, bridge.py, routes.py, pages/). Plugin rules: [plugins.md](https://github.com/sensokasucks/flavr-leftovers/blob/main/checklists/plugins.md) (in flavr-leftovers).

## Must keep

- [ ] HTTP **:3857**. `GET /health`, `GET /customers`, `POST /names`, `GET /events?after=N`, `POST /board`,
      `POST /notify`, `POST /mug`, `POST /remote` (phone app events `app_remove` / `app_swap`, mug answers
      `mug_result` / `mug_outcome` and co-op `remote_join` / `remote_leave` ride on `/events`). Same field names in
      `mod/BridgeServer.cs` + `mod/Shared.cs`, `mock/mock_server.py` and `plugins/schedule1/bridge.py`.
- [ ] Bridge refuses browser `Origin`, needs `X-Fridge-Core: 1`, checks `X-Fridge-Token` when set. No CORS headers.
- [ ] Core opt-in: `schedule1.enabled` default **false**; `schedule1.bridge_url` default `http://127.0.0.1:3857`.
- [ ] Hidden (`avatars.hide`) and red-flagged chatters never get a name; a hidden custom flag removes them at once.
- [ ] Renames never reach the save. Customers' own names come back on leave.
- [ ] Co-op: the host's mod decides; it shares names / lists through Steam lobby data (`mod/LobbySync.cs`, each value
      under 8 KB). A guest's Core never sends `/names` or `/board` (the mod answers 409) and forwards joins with
      platform + user id; hide lists / red flags are checked on both sides. Chat lines go to the chat a chatter came
      from (`origin`). Only the host gets Remove / Swap in the Chat app.
- [ ] `!mug`: `mug_enabled` default **false**. Price is the `mug_cost` setting (commands.json `cost` stays 0: Core's
      cost field only gates). Refund + chat line when the game refuses or doesn't answer within 30 s. Goons run on
      the host only; their own names come back when the mugging ends.
- [ ] Settings: everything but `bridge_url` / `bridge_token` is `"page": true` (Schedule I page, Settings tab).
- [ ] Regulars live in their own DLL (`regulars/`, FridgeRegulars.dll) so leaving it out turns them off. Their ids
      `fridge_regular_01`..`10` are save data: never rename. Save names stay neutral ("Regular N"). README warns that
      a save that met them needs the DLL, and co-op players need it too.
- [ ] Shift rotation (`rotate_after_deals`, `rotate_after_min`, `rotate_keep_subs`) defaults off; only moves
      chatters while someone waits; keeps their deals / spent. New `people` columns go in SCHEMA and ADDED_COLUMNS.
- [ ] Stream alerts in the game are phone pop-ups (NotificationsManager), never text messages (conversations are saved).
      `alerts_in_game` default **false**; hidden / red-flagged chatters never appear in alerts either.
- [ ] Game objects only touched on the main thread (`Core.OnUpdate`); the HTTP thread only uses `Shared`.
- [ ] Every game call in `CustomerWatcher` sits in try/catch: a game update gives log warnings, not a crash.
- [ ] `START Schedule1 Mock.bat` / `fridge-schedule1/START Mock.bat` run without the game.

## Check on the PC with the game (not testable in the cloud)

- [ ] `dotnet build -c Release` works against the installed game + S1API.
- [ ] MelonLoader log shows `listening on http://127.0.0.1:3857/`.
- [ ] After loading a save, Core's Status page says customers carry chatter names.
- [ ] The new name shows in the phone's Contacts and Messages, and in dialogue. (If Messages keeps the old
      name until the save is reloaded, note it: the game may cache conversation titles.)
- [ ] A customer's order text gives a "wants ..." line in chat; handing it over gives "bought ...".
- [ ] Product names read like the game's ("OG Kush"), not ids.
- [ ] `!customer leave` puts the customer's own name back without reloading.
- [ ] Loading another save from the menu keeps the names (the mod re-applies them).
- [ ] Console says "N customers found (M met)" with N matching the save (not just the met ones).
- [ ] Phone shows the **Chat** app; its four tabs fill in; Remove (twice) and Swap change who has which customer.
- [ ] With **Show stream alerts on the in-game phone** ticked, an Alerts-page test alert pops up on the phone and in the feed.
- [ ] `!mug` (enabled, with points): goons come out of a nearby building, are called "<chatter>'s crew", and the
      outcome line arrives; with a knocked-out player it refunds.
- [ ] Regulars: `FridgeRegulars` loads, "N customers found" grows by 10, each Regular walks between home and its
      hangouts (not standing at the Northtown fallback spot), can be approached for a sample, and takes a chatter name.
- [ ] Co-op with two players: the guest sees the host's chatter names and Chat app lists; a guest chatter's
      `!customer` gets a customer; a guest chatter's `!mug` hits the guest's player. Note whether order / deal
      lines fire on the guest, the host, or both.

## Drop risks

- Letting a web page call `/names` (no Origin check) or exposing the port beyond loopback.
- Writing chatter names into the save file.

## After-change verify

- [ ] `python -m pytest plugins/schedule1 -q` passes (runs the plugin against the mock).
