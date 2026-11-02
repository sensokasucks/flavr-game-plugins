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
The build copies `FridgeSchedule1.dll` into the game's `Mods` folder by itself.

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
| `GET /events?after=N` | `{"boot", "last", "events": [...]}`; `type` is `contract` (order texted), `deal` (went through) or `unlocked` (met someone new), with `id`, `name`, `qty`, `products`, `payment` |

`boot` changes every time the game starts (event numbers start again at 1).
Code: `mod/Core.cs` (start, main-thread loop), `mod/CustomerWatcher.cs` (game side), `mod/BridgeServer.cs` (HTTP),
`mod/Shared.cs` (what the two threads share).
