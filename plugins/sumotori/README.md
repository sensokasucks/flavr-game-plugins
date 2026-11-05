# Sumotori Dreams (Stream Core plugin)

Chat builds your [Sumotori Dreams Classic](https://store.steampowered.com/app/1604240/Sumotori_Dreams_Classic/)
arena with points and bets on who wins each round. There's a scoreboard overlay too.

**No game mod is needed.** Sumotori Dreams loads arena script files (`.smo`) through **Select Arena → Load Mod** and
reloads the file by itself when it changes ([developer's modding page](https://www.gravitysensation.com/sumotori/modding.htm)).
Stream Core writes that file.

> First version, not tried against the real game yet. See "Check on your PC first" below.

## Install

1. Copy this `sumotori` folder into `fridge-stream-core\plugins\`, restart Core.
2. Settings → Plugins → Sumotori Dreams → tick **Enabled** → **Save & apply** → restart Core.
3. Open **Live › Games › Sumotori Dreams**, go to the **Arena file** tab and copy the path.
4. In the game: **Select Arena → Load Mod**, pick that file. Leave it loaded while you stream.

## Chat commands

| Command | What it does |
|---------|--------------|
| `!arena` | Lists the pieces for sale and their prices |
| `!arena crate` | Buys a piece; it lands on a random spot in the next arena (or straight away with "now") |
| `!bet red 100` / `!bet blue all` / `!bet 100 red` | Bets points while bets are open; `half`, `all` and `1k` work |
| `!score` | The score and streak |

Pieces: `crate`, `bigcrate`, `crates` (a shower of five), `wall`, `breakwall`, `pillars`, `step`. Prices are on the
Settings tab (0 = not for sale).

## Running a round

On the **Round** tab (also fine from the phone remote): **Open bets** → chat bets → bets close by themselves after the
set time (or press **Close bets**) → fight → press **Red won** or **Blue won**. That pays the bets, counts the win and
loads the next arena with everything chat bought. **Call off** gives every bet back. The result buttons work with
no bets running too, as a plain scoreboard.

The game can't tell Stream Core who won, so the result always comes from you.

## Overlay

`http://127.0.0.1:3850/overlay/sumotori.html` as a Browser source (transparent, about 420 × 300). It shows the
score, streak, open bets with both pools, and the next arena's pieces. Options: `?hide=bets,queue,streak`,
`?solid=1` for a dark panel.

## Check on your PC first

The cloud couldn't run the game, so these are guesses until tried:

- Does the Steam "Classic" build still have **Load Mod**? If not, the bets and scoreboard still work; the arena part doesn't.
- Does the game restart the round when the file changes? If yes, keep **When bought pieces show up** on `next_round`.
- `addbox`'s last number: we guessed 1 = stays put, 0 = can move. If walls fall over or crates hang in the air,
  swap **fixed_flag** and **loose_flag** (Settings tab, "Fine-tuning the file").
- If pieces land off the floor or inside it, change **Pieces land this far from the middle** and **Height of the floor's top**,
  or point **Start from this arena** at an arena file you know works.

## Files

`plugin.py` (commands, rounds, arena writes), `arena.py` (piece list and .smo text), `bets.py` (payout maths),
`routes.py` (`/api/sumotori/...`), `pages/` (dashboard page), `overlay/sumotori.html`, `tests/`.
Data: `data/plugins/sumotori/sumotori.db` and, by default, `data/plugins/sumotori/stream.smo`.
