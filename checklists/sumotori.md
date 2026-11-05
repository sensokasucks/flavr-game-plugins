# Checklist — Sumotori Dreams

Core side only: python plugin `plugins/sumotori/` (plugin.py, arena.py, bets.py, routes.py, pages/, overlay/).
No game mod: the game reloads the `.smo` arena file Core writes. Plugin rules:
[plugins.md](https://github.com/sensokasucks/flavr-leftovers/blob/main/checklists/plugins.md) (in flavr-leftovers).

## Must keep

- [ ] Core opt-in: `sumotori.enabled` default **false**.
- [ ] The arena file is written whole (temp file + rename) so the game never reloads half a file. ASCII, CRLF.
- [ ] Only `addbox`, `breakability` and `man` lines are ever generated; no comments (comment syntax unknown).
      Sums like `-7+8` are worked out before writing (`arena._fold_sums`).
- [ ] Piece keys are the same in `arena.PIECES`, plugin.json `config_defaults.prices`, the `prices` help text and
      the README (a test checks the first two).
- [ ] Points: commands.json `cost` stays 0; the plugin charges with `store.spend_points` (never negative) and refunds
      with `adjust_points`, ledger source `sumotori`. Refused bets / pieces cost nothing.
- [ ] Pool payout always pays out the whole pot; one-sided pools refund everyone. Call off refunds every bet.
- [ ] Results come only from the streamer (page / `POST /api/sumotori/round`, admin token). The game is never read.
- [ ] `GET /api/sumotori/state` is public and holds only what chat already sees (names, sides, pools, pieces).
- [ ] One menu entry (Live › Games › Sumotori Dreams) with Round / Arena file / Settings tabs; settings except
      `arena_file` are `"page": true`.

## Try on the PC (not done yet)

- [ ] Load Mod exists in the Steam Classic build and accepts the built-in arena.
- [ ] Reload behaviour when the file changes (restarts the round or not).
- [ ] fixed_flag / loose_flag guess (1 / 0), floor_y -7, pieces land on the floor.
- [ ] breakability value range for breakwall.
