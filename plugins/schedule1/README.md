# Schedule I (Stream Core plugin)

Chatters become customers in Schedule I: `!customer` puts their name on a customer in your game, and chat
hears when they text an order and when the deal goes through. `!topcustomers` shows who spent the most.
The streamer's page is **Games → Schedule I customers** in the dashboard.

Needs the FridgeSchedule1 MelonLoader mod in the game: setup, build and a mock you can try without the game
are in [fridge-schedule1/README.md](../../fridge-schedule1/README.md).

Files: `plugin.py` (loop, chat commands, announcements), `roster.py` (who has which customer, own database),
`bridge.py` (talks to the mod), `routes.py` + `pages/` (dashboard page), `commands.json`, `tests/`.
