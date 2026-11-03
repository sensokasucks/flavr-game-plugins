# Schedule I (Stream Core plugin)

Chatters become customers in Schedule I: `!customer` puts their name on a customer in your game, and chat
hears when they text an order and when the deal goes through. `!topcustomers` shows who spent the most.
When you make a new mix, the **Let chat name it** button on the game's naming screen lets chat suggest
(`!mixname <name>`) and vote (`!1` `!2` ...) on its name.
Also (each switched on in its own box on the page): workers named after chatters (`!staff`, `!topstaff`),
donations as cash in a dead drop (`!drop` for points), chat picking the next mixing ingredient (**Let chat pick**
on the mixing station), supplier favours (`!tab`, `!supply`) and dealer sponsors (`!sponsor`, `!topdealers`).
The streamer's page is **Games → Schedule I customers** in the dashboard.

Needs the FridgeSchedule1 MelonLoader mod in the game: setup, build and a mock you can try without the game
are in [fridge-schedule1/README.md](../../fridge-schedule1/README.md).

Files: `plugin.py` (loop, chat commands, announcements), `roster.py` (who has which customer, own database),
`bridge.py` (talks to the mod), `mixvote.py` (chat names a new mix), `feature.py` (shared bits + the crew list),
`staff.py`, `drops.py`, `mixpick.py`, `suppliers.py`, `dealers.py` (one file per feature), `routes.py` + `pages/` (dashboard page), `commands.json`, `tests/`.
