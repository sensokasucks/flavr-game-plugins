# FridgeSchedule1

MelonLoader mod for **Schedule I** that lets your chatters become customers in your game.
Stream Core's Schedule I plugin ([plugins/schedule1](../plugins/schedule1/)) does the chat side.

```
chat: !customer ──► Stream Core (plugins/schedule1) ──HTTP :3857──► FridgeSchedule1 mod ──► customer NPCs
chat: "ZackFan99 bought 3x OG Kush for $120" ◄──────── orders / deals ◄────────┘
                                         mock/mock_server.py (stand-in, no game needed)
```

What happens:

- A chatter types `!customer` (or joins on their own if **Join without !customer** is set on Core's
  Schedule I card). They go on a list, first come, first served.
- Each one gets a customer in your game. Customers you've already met go first, so the new name
  shows up in your phone's contacts straight away. With more chatters than customers, the rest wait.
- When that customer texts you an order, and when the deal goes through, Core says it in chat on the
  chatter's own platform. `!topcustomers` lists who spent the most.
- `!customer leave` (or **Remove** on Core's **Games → Schedule I customers** page) gives the customer
  its own name back.
- Chatters on the picture hide list or red-flagged in Core never get a name, and lose theirs if they
  get flagged later.

Renaming is only on your PC: co-op friends see the normal names, and nothing is written into your save.

## Regulars: ten extra customers

`FridgeRegulars.dll` (built from `regulars/`, next to `FridgeSchedule1.dll` in `Mods`) adds ten customers,
"Regular 1" to "Regular 10", so a busy chat has more customers to carry names. Each lives in a different
building across the map, spends the day at two hangouts, has its own look and tastes, and becomes a
customer like anyone else: walk up and offer a sample. Once met they join the chatter-name pool.

Read this before loading a save you care about with them:

- They are real NPCs, so **the save keeps them** (under their neutral names; chatter names are still
  only on screen). That save then expects `FridgeRegulars.dll`; removing it later leaves those
  customers missing or broken. Back up the save first
  (`%USERPROFILE%\AppData\LocalLow\TVGS\Schedule I\Saves`).
- In co-op **every player needs `FridgeRegulars.dll`** too.
- To not have them at all, leave `FridgeRegulars.dll` out of `Mods` (before a save has met them).

**Only put chatter names on the extra regulars** (Settings tab, Joining box, off by default): only the ten
Regulars carry chatter names; everyone else waits. Switching it on moves chatters off normal customers onto
free Regulars (first in line first) or back to waiting. With more than ten chatters, pair it with **Shifts** so
the names take turns. The mod marks them with `"regular": true` in `GET /customers`.

## !mug: chat sends goons after you

Off by default; switch it on in the **Mugging** box on the Schedule I page (Games). A chatter pays the
price in Core points and cartel goons come out of the building nearest your player and attack. On your
screen they're called "zackfan99's crew". Chat hears when they're coming and how it ended (you fought them
off, they knocked you out, or they gave up after 3 minutes). One mugging per cooldown for the whole chat.
If the game can't do it (no save loaded, you're already knocked out or arrested, no goons free) or doesn't
answer within 30 s, the points go back and chat is told why.

## Chat names your new mixes

When a mixing station makes a mix nobody has made before, the game asks you to name it. The mod adds a
**Let chat name it** button under the game's Confirm button. Press it and:

1. Chat suggests names for 30 s with `!mixname Blue Dream` (one idea each; the same idea from more chatters
   counts as more backers). Names keep to letters, numbers, spaces and `' & . -`; names already in your save
   and words on the **Words never allowed in a name** list are refused.
2. Chat votes for 30 s with `!1`, `!2` ... (or `!vote 2`) on up to four names: the best-backed ideas, filled up
   with the game's own ideas (one of the game's is always there unless you switch that off).
3. The winner goes into the name box and Confirm is pressed for you. With **Name the mix as soon as the vote
   ends** off, it's only typed in and you press Confirm (or change it).

The countdown, the ideas and the vote show under the button, and on stream as a poll-style board (the same
place Core's `!poll` shows up). Press the button again, type your own name and press Confirm, or leave with
Esc, and chat's vote stops. Times, number of names and the other options are in the **Chat names new mixes**
box on the Schedule I page (Games). The name is a normal product name, so it is saved like any mix you name.
Works for co-op guests too: each player names their own mixes with their own chat.

## Your crew: staff, cash drops, suppliers, dealers, ingredient vote

Five more ways chat plays along. Each has its own box on the Schedule I page (Games) in Stream Core and
all but the ingredient vote start switched off. Staff, cash drops, suppliers and dealer sponsors change the
host's world, so in co-op only the host's chat can use them; the ingredient vote works for everyone.

- **Staff named after chatters** (`!staff`, `!staff leave`, `!topstaff`). Your botanists, chemists, packagers
  and cleaners carry the names of chatters who typed `!staff` (subscribers only by default), and chat hears
  what they got done ("Dave (zackfan99) harvested a plant x3, watered a plant x5"), at most one line per
  worker every two minutes. Names come off while the game saves, so they never reach your save file.
- **Donations as cash drops**. Bits, Super Chats, tips, gifted subs and KICKs put in-game cash
  (100 in-game $ per real $1 by default, with a cap per drop and per stream) into an empty dead drop near you.
  You get a pop-up with the donor's message, the drop gets a map marker ("Cash drop from zackfan99"), and chat
  hears when you pick it up. `!drop <note>` does the same for points.
- **Chat picks the next ingredient**. The mixing station gets a **Let chat pick** button under Begin. Chat votes
  `!1` `!2` ... for 30 s on up to six ingredients (the ones you carry, or any); the winner shows on the screen
  and you put it in yourself. With **Put chat's pick in the station for me** ticked, the mod moves it from your
  inventory into the station for you (as many as there is product); you still press Begin.
- **Suppliers** (`!tab albert 500`, `!supply albert`). `!tab` pays part of what you owe a supplier you've met
  (0.2 in-game $ per point; points for more than you owe come back). `!supply` has the supplier leave five of
  their goods at a dead drop "from" the chatter, with a marker. The supplier says so in a pop-up; nothing goes
  into the phone's Messages (messages are saved).
- **Dealers sponsored by chatters** (`!sponsor benji 800`, `!topdealers`). A chatter backs one of your recruited
  dealers with points (a higher bid takes over; the outbid sponsor gets their points back). The dealer shows as
  "Benji (zackfan99)", chat hears their sales, robberies and when they run out of product, and the sponsor earns
  10 points per $100 the dealer sells.

## Co-op: everyone has the mod

Every player in the lobby runs the mod (and their own Stream Core, if they stream). The **host's** game
decides: its Core assigns customers, and its mod shares the chatter names and the Chat app's lists with the
other players through Steam lobby data, so everyone sees the same names.

- A friend's chatters can still type `!customer`: the friend's Core passes the join to the host's list
  (through the friend's mod). Hide lists and red flags are checked on both sides.
- Chat lines about a chatter go to the chat they came from: the friend's chat hears about the friend's chatters.
- On a friend's game the Chat app shows the host's lists without Remove / Swap (only the host edits them);
  the Feed and stream alert pop-ups stay each player's own.
- `!mug` from a friend's chat hits the friend's player: the host's mod sends the goons. Points and cooldown
  stay in the friend's Core, which refunds if the host's game refuses.
- Playing alone counts as hosting.

## Shifts: sharing customers when the waiting list is long

Off by default. On Core's Schedule I card:

- **Shift ends after this many deals**: when someone is waiting, a chatter whose customer has made that
  many deals goes to the back of the line and the chatter waiting longest takes the customer over.
- **Shift ends after (minutes)**: the same by time, for customers who rarely order.
- **Subscribers / members keep their customer**: shifts never end for subs.

0 turns a trigger off; both can be on. Nobody is moved while nobody is waiting. Deals and money spent stay
with the chatter for `!topcustomers`. Chat hears "zackfan99's shift is over, bea takes over Kyle Cooley."

## When will they turn up?

Every named customer has a status, worked out by the mod from the game's own data
(`mod/CustomerStatus.cs`). It shows on the Schedule I page ("When they turn up"), in the phone's Chat app,
and in the chatter's `!customer` reply:

- **not met yet: walk up and offer a sample (lives in Westville)**
- **texted you an order, waiting for your reply**
- **deal set for 16:30-18:00 at the Docks**
- **next order expected tomorrow around 18:00 (in about 20 in-game hours)**: from the customer's own order
  days and order time. "Expected", because the game still decides on the day (relationship, addiction).
- **buys from your dealer Benji**

**Newly named customers text you an order soon** (Settings tab, Joining box, on by default): when a chatter's
name lands on a customer you've already met, that customer texts you an order a few seconds later and chat
hears "zackfan99 just texted the streamer for an order". The game's rules still apply: nothing happens if they
already have a deal, an open order, a dealer, or just finished a deal, or if you're knocked out or arrested.
In co-op only the host's setting counts.

**Find** (phone app and the page): puts a marker on that customer on your phone's map and keeps it on them
until you press **Stop** (the "Finding ..." bar at the top of the Chat app's Customers tab), walk within 5 m of
them, or 10 real minutes pass (`FindMinutes` in `UserData\MelonPreferences.cfg`). The phone list also says how
far away they are ("230 m north-east").

## The Chat app on your phone

The mod adds a **Chat** app (purple speech bubble) to the in-game phone:

- **Customers**: which chatter carries which customer, with their deals and money spent.
  **Remove** (press twice) takes a chatter off the list, like `!customer leave`.
  **Swap** sends them to the back of the waiting list so the next chatter gets the customer
  (with nobody waiting it does nothing and tells you).
- **Waiting**: the waiting list in order.
- **Top**: the five chatter-customers who spent the most.
- **Feed**: chatter-customers' orders and deals, and stream alerts.

**Alerts tab**: every stream alert also stays in the Chat app's **Alerts** tab (last 50, newest on top) so you
can read it after the pop-up is gone. Unread ones have a dot and the tab says "Alerts (3)"; tap a card or
**Mark all read**. Cards use Stream Core's alert look: `plugins/schedule1/alert_style.py` reads Core's
`overlay/alerts.css` and your `alerts-custom.css` (Admin → Alert test) and maps the accent per kind
(`--alert-accent`, `border-color`), the text colour (`color`, `.name { color }`), a plain `background-color`,
`font-weight` and `--alert-muted` (the viewer's message); the "card" skin uses `--alert-card-bg`. Fonts,
sizes, gradients, shadows and animations can't be shown in the game and are left out. The kind's picture from
Core's alert page (PNG / JPG; GIFs and videos aren't shown) or the sticker / gift image sits on the card.
Sounds are not played (the game's pop-up already makes its own). Alerts stay each player's own in co-op.

**Stream alerts on the phone**: tick **Show stream alerts on the in-game phone** on Core's Schedule I card.
Follows, subs, raids, tips and the rest pop up like a phone notification and go into the feed. If the
person has a customer, it says which one. **Which alerts** picks kinds (empty = all except chat flags).
The test buttons on Core's Alerts page work too, which is the quickest way to try it. Alerts are pop-ups,
not text messages, because the game saves text conversations and chatter names must stay out of the save.

## Install (on the PC with the game)

1. **MelonLoader** 0.7.2 or newer (not 0.7.1, it breaks Schedule I mods). Use the MelonLoader installer
   on `Schedule I.exe`, start the game once and quit (MelonLoader builds its `Il2CppAssemblies` folder).
2. **S1API** ("S1API_Forked" on Thunderstore / Nexus, source github.com/ifBars/S1API): put its files in the
   game folder as its page says (`Mods\S1API.Il2Cpp.MelonLoader.dll` plus `Plugins\S1APILoader...`).
3. **FridgeSchedule1.dll** into the game's `Mods` folder (build it, below).
4. Stream Core: copy `plugins/schedule1` into `fridge-stream-core\plugins\`, restart Core, tick **Enabled**
   on its card under **Settings → Plugins**, **Save & apply**, restart Core.
5. Start the game and load a save. Core's Status page says how many customers carry chatter names.

This is for the game's normal Steam build (IL2CPP). The Mono beta branch isn't supported yet.

## Build

Needs the .NET SDK (6 or newer) on the PC that has the game and steps 1-2 done:

```
cd fridge-schedule1\mod
dotnet build -c Release
```

If the game isn't in the default Steam folder add `-p:GameDir="D:\SteamLibrary\steamapps\common\Schedule I"`.
The build copies `FridgeSchedule1.dll` into the game's `Mods` folder by itself. The Regulars (optional,
see above) build the same way from `fridge-schedule1\regulars` and copy `FridgeRegulars.dll`.
The game must be closed while the DLLs are copied.

## Settings

MelonLoader writes them to `UserData\MelonPreferences.cfg` under `[FridgeSchedule1]` after the first start:

| Setting | Default | |
|---------|---------|-|
| `BindAddress` | `127.0.0.1` | Keep it on loopback. |
| `Port` | `3857` | Must match **Mod URL** on Core's Schedule I card. |
| `Token` | empty | Optional. Put the same text in **Mod token** on Core's card. |

Core's side (Settings → Plugins → Schedule I): who joins on their own, whether met customers go first,
the most named customers at once, "zackfan99" or "zackfan99 Cooley" style names, which chat messages to
send, and how often to check.

## Try it without the game

`START Schedule1 Mock.bat` (repo root) or `START Mock.bat` here starts a fake mod on port 3857:
18 customers (2 of them Regulars), 6 already met, an order every 15 seconds and its deal a few seconds later.
Point Core at it (the default Mod URL already does), type `!customer` in chat, and watch the
mock's window and Core's chat replies. `python mock\mock_server.py --help` lists the options
(`--every 5` for faster orders, `--token` to test the token).

## HTTP (for developers)

Everything except `/health` needs `X-Fridge-Core: 1`, refuses requests with a browser `Origin` header,
and checks `X-Fridge-Token` when a Token is set.

| | |
|-|-|
| `GET /health` | `{"ok": true}` |
| `GET /customers` | `{"loaded", "boot", "customers": [{"id", "first", "last", "shown", "unlocked", "status", "status_text"}]}`; `first`/`last` are the customer's own name, `shown` what the game shows now, `status` one of `locked` / `deal` / `offer` / `dealer` / `waiting` with `status_text` in words |
| `POST /names` | `{"names": {"kyle_cooley": {"first": "zackfan99", "last": ""}}}`, the full set: customers not listed get their own name back |
| `GET /events?after=N` | `{"boot", "last", "events": [...]}`; `type` is `contract` (order texted), `deal` (went through) or `unlocked` (met someone new), with `id`, `name`, `qty`, `products`, `payment`; or `app_remove` / `app_swap` with `key` (phone app buttons) |
| `POST /board` | `{"named", "waiting", "top"}`, rows `{"key", "name", "platform", "customer", "deals", "spent"}`: what the phone app lists |
| `POST /notify` | `{"title", "text"}` plus, for a stream alert, `kind`, `message`, `amount`, `label`, `accent`, `bg`, `text_color`, `muted` (`#RRGGBBAA`), `bold`, `image`: pop-up, and a card in the Alerts tab (no `kind` or `system` = Feed note) |
| `POST /mug` | `{"id", "by", "goons"}`: !mug; answered by events `mug_result` (`mug`, `ok`, `msg`) and later `mug_outcome` (`mug`, `outcome`: `won` / `lost` / `left`) |
| `POST /nudge` | `{"npc"}`: newly named, met customer texts an order (host only); answered by event `nudge_result` (`npc`, `ok`, `msg`) |
| `POST /find` | `{"npc", "by"}`: map marker on that customer for this player, labelled `by` |
| `POST /mixvote` | `{"state", "ends_in", "options": [{"name", "votes"}], "winner", "ranked", "confirm", "msg"}`: chat's vote on a new mix's name (`off` / `suggest` / `vote` / `done` / `stopped`); the naming screen's button sends events `mix_vote` (`game_names`, `taken`, `effects`, `value`, `current`) and `mix_vote_stop` (`reason`: `button` / `closed`) |
| `GET /crew` | `{"loaded", "boot", "staff": [{"id", "first", "last", "type", "property", "shown"}], "dealers": [{"id", "first", "last", "cash", "stock", "customers", "shown"}], "suppliers": [{"id", "first", "last", "unlocked", "debt"}]}` |
| `POST /crewnames` | `{"staff": {id: {"first", "last"}}, "dealers": {...}}`: a list that's sent replaces that list (anyone not in it gets their own name back); a list left out stays as it was. Events `staff_job` (`id`, `job`), `dealer_sale` (`id`, `amount`, `deals`), `dealer_robbed` (`id`, `cash`, `items`), `dealer_empty` (`id`) |
| `POST /drop` | `{"id", "by", "note", "cash", "label"}`: cash in a dead drop; answered by event `drop_result` (`drop`, `ok`, `msg`, `where`) and later `drop_taken` (`drop`) |
| `POST /supplier` | `{"id", "action": "pay" / "deliver", "supplier", "by", "amount", "qty"}`; answered by event `supplier_result` (`req`, `ok`, `msg`, `paid`, `debt`, `where`, `what`), a delivery later by `drop_taken` |
| `POST /mixpick` | `{"state", "ends_in", "options": [{"name", "votes"}], "winner", "msg"}`: chat's ingredient vote (`off` / `vote` / `done` / `stopped`); the station's button sends events `mixpick` (`product`, `carried`, `all`) and `mixpick_stop` (`reason`) |
| `POST /remote` | `{"type": "join" / "leave", "platform", "user_id", "username", "display_name", "is_sub"}`: co-op guest only, passed to the host (whose Core gets `remote_join` / `remote_leave` events) |

`GET /customers` also has `role` (`host`, or `client` when this game is a guest in a friend's lobby) and
`board` (the Chat app's lists; the host's on a client). On a client `POST /names`, `/board`, `/crewnames`, `/drop` and `/supplier` answer 409.
Co-op data between the mods travels as Steam lobby data (`fs1.names`, `fs1.board`, `fs1.res` from the host,
`fs1.req` member data from each guest), see `mod/LobbySync.cs`.

`boot` changes every time the game starts (event numbers start again at 1).
Code: `mod/Core.cs` (start, main-thread loop), `mod/CustomerWatcher.cs` (game side), `mod/BridgeServer.cs` (HTTP),
`mod/Shared.cs` (what the two threads share), `mod/ChatApp.cs` (the phone app), `mod/Mugger.cs` (!mug),
`mod/LobbySync.cs` (co-op sharing), `mod/MixNamer.cs` (the naming screen's "Let chat name it" button),
`mod/Crew.cs` (workers, dealers, suppliers; `RobPatch`), `mod/NpcNames.cs`, `mod/Drops.cs` (cash drops, supplier jobs),
`mod/MixPicker.cs` (the mixing station's "Let chat pick" button), `mod/CrewShared.cs` + `mod/BridgeServer.Crew.cs`.
