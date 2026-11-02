# Checklist — Schedule I

Home: `fridge-schedule1/` (MelonLoader `mod/`, `mock/mock_server.py`). Core side: python plugin `plugins/schedule1/`
(plugin.py, roster.py, bridge.py, routes.py, pages/). Plugin rules: [plugins.md](https://github.com/sensokasucks/flavr-leftovers/blob/main/checklists/plugins.md) (in flavr-leftovers).

## Must keep

- [ ] HTTP **:3857**. `GET /health`, `GET /customers`, `POST /names`, `GET /events?after=N`. Same field names in
      `mod/BridgeServer.cs` + `mod/Shared.cs`, `mock/mock_server.py` and `plugins/schedule1/bridge.py`.
- [ ] Bridge refuses browser `Origin`, needs `X-Fridge-Core: 1`, checks `X-Fridge-Token` when set. No CORS headers.
- [ ] Core opt-in: `schedule1.enabled` default **false**; `schedule1.bridge_url` default `http://127.0.0.1:3857`.
- [ ] Hidden (`avatars.hide`) and red-flagged chatters never get a name; a hidden custom flag removes them at once.
- [ ] Renames are local only (no save writes, nothing sent to co-op players). Customers' own names come back on leave.
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

## Drop risks

- Letting a web page call `/names` (no Origin check) or exposing the port beyond loopback.
- Writing chatter names into the save file.

## After-change verify

- [ ] `python -m pytest plugins/schedule1 -q` passes (runs the plugin against the mock).
