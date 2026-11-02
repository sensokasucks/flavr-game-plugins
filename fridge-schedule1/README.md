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

## !mug: chat sends goons after you

Off by default; switch it on in the **Mugging** box on the Schedule I page (Games). A chatter pays the
price in Core points and cartel goons come out of the building nearest your player and attack. On your
screen they're called "zackfan99's crew". Chat hears when they're coming and how it ended (you fought them
off, they knocked you out, or they gave up after 3 minutes). One mugging per cooldown for the whole chat.
If the game can't do it (no save loaded, you're already knocked out or arrested, no goons free) or doesn't
answer within 30 s, the points go back and chat is told why.

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

## The Chat app on your phone

The mod adds a **Chat** app (purple speech bubble) to the in-game phone:

- **Customers**: which chatter carries which customer, with their deals and money spent.
  **Remove** (press twice) takes a chatter off the list, like `!customer leave`.
  **Swap** sends them to the back of the waiting list so the next chatter gets the customer
  (with nobody waiting it does nothing and tells you).
- **Waiting**: the waiting list in order.
- **Top**: the five chatter-customers who spent the most.
- **Feed**: chatter-customers' orders and deals, and stream alerts.

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
16 customers, 6 already met, an order every 15 seconds and its deal a few seconds later.
Point Core at it (the default Mod URL already does), type `!customer` in chat, and watch the
mock's window and Core's chat replies. `python mock\mock_server.py --help` lists the options
(`--every 5` for faster orders, `--token` to test the token).

## HTTP (for developers)

Everything except `/health` needs `X-Fridge-Core: 1`, refuses requests with a browser `Origin` header,
and checks `X-Fridge-Token` when a Token is set.

| | |
|-|-|
| `GET /health` | `{"ok": true}` |
| `GET /customers` | `{"loaded", "boot", "customers": [{"id", "first", "last", "shown", "unlocked"}]}`; `first`/`last` are the customer's own name, `shown` what the game shows now |
| `POST /names` | `{"names": {"kyle_cooley": {"first": "zackfan99", "last": ""}}}`, the full set: customers not listed get their own name back |
| `GET /events?after=N` | `{"boot", "last", "events": [...]}`; `type` is `contract` (order texted), `deal` (went through) or `unlocked` (met someone new), with `id`, `name`, `qty`, `products`, `payment`; or `app_remove` / `app_swap` with `key` (phone app buttons) |
| `POST /board` | `{"named", "waiting", "top"}`, rows `{"key", "name", "platform", "customer", "deals", "spent"}`: what the phone app lists |
| `POST /notify` | `{"title", "text"}`: a stream alert to pop up on the phone |
| `POST /mug` | `{"id", "by", "goons"}`: !mug; answered by events `mug_result` (`mug`, `ok`, `msg`) and later `mug_outcome` (`mug`, `outcome`: `won` / `lost` / `left`) |
| `POST /remote` | `{"type": "join" / "leave", "platform", "user_id", "username", "display_name", "is_sub"}`: co-op guest only, passed to the host (whose Core gets `remote_join` / `remote_leave` events) |

`GET /customers` also has `role` (`host`, or `client` when this game is a guest in a friend's lobby) and
`board` (the Chat app's lists; the host's on a client). On a client `POST /names` and `/board` answer 409.
Co-op data between the mods travels as Steam lobby data (`fs1.names`, `fs1.board`, `fs1.res` from the host,
`fs1.req` member data from each guest), see `mod/LobbySync.cs`.

`boot` changes every time the game starts (event numbers start again at 1).
Code: `mod/Core.cs` (start, main-thread loop), `mod/CustomerWatcher.cs` (game side), `mod/BridgeServer.cs` (HTTP),
`mod/Shared.cs` (what the two threads share), `mod/ChatApp.cs` (the phone app), `mod/Mugger.cs` (!mug),
`mod/LobbySync.cs` (co-op sharing).
