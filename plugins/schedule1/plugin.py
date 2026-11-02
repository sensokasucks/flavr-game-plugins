"""
Schedule I plugin: chatters become customers in the streamer's game.

Chatters type !customer (or join on their own, see the ``auto_join`` setting). Each one gets a
customer NPC in Schedule I that carries their name; when that customer texts an order or a deal
goes through, Core says so in chat. Talks to the FridgeSchedule1 MelonLoader mod (or its mock
server) through bridge.py; who has which customer lives in roster.py's table.

Settings live under ``schedule1:`` in config.yaml (defaults in plugin.json). Chat commands are in
commands.json. Stats overlay / points commands / paid events are later steps
(/mnt/project-files/schedule1/SCHEDULE1_PLUGIN_DESIGN.md in the project, not built yet).

The background loop (_loop) runs every ``poll_sec`` seconds while the plugin is on:
  - every ``sync_sec`` (or straight away after a join / leave / unlock): read the game's customers,
    drop hidden or red-flagged chatters, hand waiting chatters free customers, send the names and
    the lists for the mod's in-game phone app (board());
  - every pass: read new game events (orders, deals, unlocks, phone app buttons) and act on them.
Stream alerts (follows, subs, raids, ...) reach _on_alert from Core's event bus; with
``alerts_in_game`` on they pop up on the in-game phone too.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from core.avatar_store import parse_hide
from core.models import ExecuteRequest, Platform
from core.plugin_api import BasePlugin

from .bridge import Bridge, BridgeError
from .roster import Roster, clean_name, desired_names, person_key, plan_assignments

log = logging.getLogger("plugins.schedule1")

RED_FLAG_REFRESH_SEC = 30     # how often the red-flag list is re-read from Core's database
BOARD_TOP = 5                 # top spenders listed in the phone app
# Alert kinds sent to the game when ``alert_kinds`` is empty: every kind in core/alerts.py KINDS
# except "flag" (custom chat flags are a moderation tool, not a celebration).
ALERT_KINDS_SKIPPED_BY_DEFAULT = {"flag"}


def alert_kinds(setting: Any) -> set[str]:
    """``alert_kinds`` as a set of lower-case kinds; accepts a list or "follow, raid" text. Empty = all."""
    if isinstance(setting, str):
        setting = setting.split(",")
    return {str(k).strip().lower() for k in (setting or []) if str(k).strip()}


def money(amount: Any) -> str:
    """In-game dollars as chat text: 240 -> "$240", 12.5 -> "$12.50"."""
    try:
        v = float(amount or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"${v:,.0f}" if v.is_integer() else f"${v:,.2f}"


def order_text(ev: dict) -> str:
    """ "3x OG Kush" from a mod event's qty + products (product display names from the game)."""
    products = [str(p) for p in (ev.get("products") or []) if p]
    what = ", ".join(products[:3]) or "product"
    qty = int(ev.get("qty") or 0)
    return f"{qty}x {what}" if qty > 0 else what


class Schedule1Customers(BasePlugin):
    """Core side of Schedule I: the customer list, name sync with the mod, order/deal announcements."""

    name = "schedule1"

    def __init__(self, config: dict, ctx=None):
        super().__init__(config, ctx)
        self.roster: Optional[Roster] = None
        self.bridge: Optional[Bridge] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._wake = asyncio.Event()          # set by joins / leaves / unlocks: sync now, don't wait
        self._next_sync = 0.0
        self._customers: list[dict] = []      # last GET /customers list
        self._loaded = False                  # a save is loaded in the game
        self._boot: Optional[str] = None      # mod session id of the events we follow
        self._after = 0                       # last event number handled
        self._sent: Optional[dict] = None     # names last sent to POST /names
        self._sent_boot: Optional[str] = None
        self._board_sent: Optional[dict] = None   # board last sent to POST /board
        self._board_boot: Optional[str] = None
        self._red: set[tuple[str, str]] = set()   # (platform, user id or lower name) red-flagged
        self._red_at = 0.0
        self._flagged_now: set[str] = set()   # person keys hidden by a custom flag this session
        self.connected = False
        self.last_error = ""

    # ------------------------------------------------------------------ settings

    def _s(self) -> dict:
        """This plugin's live config block (``schedule1:``)."""
        return (self.config or {}).get("schedule1") or {}

    def _num(self, key: str, default: float, lo: float) -> float:
        try:
            return max(lo, float(self._s().get(key, default)))
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Open the table, connect to the mod, start the loop. Core calls this when the plugin is enabled."""
        s = self._s()
        self.enabled = bool(s.get("enabled"))
        self.roster = Roster(self.ctx.db)
        await self.roster.setup()
        self.bridge = Bridge(s.get("bridge_url") or "http://127.0.0.1:3857", str(s.get("bridge_token") or ""))
        bus = getattr(self.ctx, "bus", None)
        if bus is not None:
            bus.on_chat(self._on_chat)       # the event bus has no "off": handlers check _running
            bus.on_flag(self._on_flag_event)
            bus.on_alert(self._on_alert)
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="schedule1-customers")
        log.info("Schedule I customers started (mod at %s)", self.bridge.base_url)

    async def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self.bridge is not None:
            await self.bridge.close()
            self.bridge = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Schedule I loop")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._num("poll_sec", 2, 0.5))
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> None:
        """One pass of the loop: sync names when due (or woken), then read new events."""
        if self.bridge is None or self.roster is None:
            return
        now = time.monotonic()
        try:
            if self._wake.is_set() or now >= self._next_sync:
                self._wake.clear()
                self._next_sync = now + self._num("sync_sec", 10, 2)
                await self.sync()
            await self.poll_events()
            self.connected, self.last_error = True, ""
        except BridgeError as exc:
            if self.connected or not self.last_error:
                log.info("Schedule I: %s", exc)
            self.connected, self.last_error = False, str(exc)
            self._sent = None                 # re-send names and board once the mod is back
            self._board_sent = None

    # ------------------------------------------------------------------ hidden chatters

    async def _refresh_red_flags(self) -> None:
        """Re-read Core's red-flag list every RED_FLAG_REFRESH_SEC (nobody is hidden while red flags are off)."""
        if time.monotonic() - self._red_at < RED_FLAG_REFRESH_SEC:
            return
        self._red_at = time.monotonic()
        red: set[tuple[str, str]] = set()
        store = getattr(self.ctx, "store", None)
        if (self.config.get("red_flags") or {}).get("enabled", True) and store is not None \
                and hasattr(store, "list_red_flagged_sync"):
            rows = await asyncio.to_thread(store.list_red_flagged_sync)
            for r in rows:
                plat = str(r.get("platform") or "")
                if r.get("platform_user_id"):
                    red.add((plat, str(r["platform_user_id"])))
                for n in (r.get("username"), r.get("display_name")):
                    if n:
                        red.add((plat, str(n).lower()))
        self._red = red

    def is_hidden(self, platform: str, user_id: str, username: str, display_name: str = "") -> bool:
        """Never put this chatter's name in the game: on the picture hide list
        (``avatars.hide``, shared with Stream Rooms) or red-flagged."""
        plat = str(platform or "").lower()
        if person_key(plat, user_id, username) in self._flagged_now:
            return True
        names = {str(n or "").lower().lstrip("@") for n in (username, display_name) if n}
        for p, n in parse_hide((self.config.get("avatars") or {}).get("hide") or []):
            if (not p or p == plat) and n in names:
                return True
        if user_id and (plat, str(user_id)) in self._red:
            return True
        return any((plat, n) in self._red for n in names)

    def _row_hidden(self, row: dict) -> bool:
        return self.is_hidden(row["platform"], row.get("user_id") or "", row["username"], row.get("display_name") or "")

    # ------------------------------------------------------------------ sync with the game

    async def sync(self) -> None:
        """Read the game's customers, give waiting chatters free ones, send the names when they changed."""
        data = await self.bridge.customers()
        self._loaded = bool(data.get("loaded"))
        self._customers = [c for c in (data.get("customers") or []) if isinstance(c, dict) and c.get("id")]
        await self._refresh_red_flags()
        gone = await self.roster.remove_where(lambda r: not self._row_hidden(r))
        if gone:
            log.info("Schedule I: took %d hidden / red-flagged chatter(s) off the customer list", len(gone))
        if not self._loaded:
            return                            # main menu: nothing to name yet
        s = self._s()
        people = await self.roster.all()
        pairs = plan_assignments(self._customers, people,
                                 prefer_unlocked=bool(s.get("prefer_unlocked", True)),
                                 max_named=int(s.get("max_named") or 0))
        if pairs:
            await self.roster.assign(pairs)
            people = await self.roster.all()
            await self._announce_new(pairs, people)
        names = desired_names(self._customers, people,
                              name_style=str(s.get("name_style") or "chatter"),
                              max_len=int(s.get("max_name_len") or 24))
        boot = str(data.get("boot") or "")
        if names != self._sent or boot != self._sent_boot:
            await self.bridge.set_names(names)
            self._sent, self._sent_boot = names, boot
        board = await self.board(people)
        if board != self._board_sent or boot != self._board_boot:
            await self.bridge.set_board(board)
            self._board_sent, self._board_boot = board, boot

    async def board(self, people: list[dict]) -> dict:
        """The in-game phone app's lists (POST /board; read by the mod's BridgeServer.Rows / ChatApp.cs).

        named = chatters on a customer that's in this save, waiting = the list in order,
        top = best spenders. Hidden / red-flagged chatters were already removed by sync().
        """
        by_id = {c["id"]: c for c in self._customers}

        def row(r: dict, cust: Optional[dict] = None) -> dict:
            return {"key": r["key"], "name": clean_name(r["display_name"], r["username"]),
                    "platform": r["platform"],
                    "customer": f"{cust.get('first', '')} {cust.get('last', '')}".strip() if cust else "",
                    "deals": int(r["deals"] or 0), "spent": float(r["spent"] or 0)}

        named = [row(r, by_id[r["npc_id"]]) for r in people if r["npc_id"] in by_id]
        waiting = [row(r) for r in people if not r["npc_id"]]
        top = [row(r, by_id.get(r["npc_id"] or "")) for r in await self.roster.top(BOARD_TOP)]
        return {"named": named, "waiting": waiting, "top": top}

    async def _announce_new(self, pairs: list[tuple[str, str]], people: list[dict]) -> None:
        """'zackfan99 is now a customer' in chat, on the chatter's own platform (``announce_new``)."""
        if not self._s().get("announce_new", True):
            return
        rows = {p["key"]: p for p in people}
        for key, _npc in pairs:
            row = rows.get(key)
            if row:
                who = clean_name(row["display_name"], row["username"])
                await self._say(row["platform"], f"{who} is now one of the streamer's customers in Schedule I.")

    async def poll_events(self) -> None:
        """Handle the mod's new events. A new mod session (boot) starts from its latest event, not its history."""
        data = await self.bridge.events(self._after)
        boot = str(data.get("boot") or "")
        last = int(data.get("last") or 0)
        if boot != self._boot:
            # first contact, or the game restarted: skip what happened before we were listening
            self._boot, self._after = boot, last
            self._wake.set()
            return
        for ev in data.get("events") or []:
            seq = int(ev.get("seq") or 0)
            if seq <= self._after:
                continue
            self._after = seq
            try:
                await self.handle_event(ev)
            except Exception:
                log.exception("Schedule I event %s", ev)

    async def handle_event(self, ev: dict) -> None:
        """One game event: "contract" (a customer texted an order), "deal" (it went through), "unlocked",
        or a phone app button: "app_remove" / "app_swap" with the chatter's ``key`` (mod ChatApp.cs)."""
        kind = str(ev.get("type") or "")
        npc = str(ev.get("id") or "")
        s = self._s()
        if kind == "unlocked":
            self._wake.set()                  # prefer_unlocked may move a waiting chatter onto them
            return
        if kind in ("app_remove", "app_swap"):
            await self._app_button(kind, str(ev.get("key") or ""))
            return
        if kind == "deal":
            row = await self.roster.record_deal(npc, float(ev.get("payment") or 0))
        else:
            row = await self.roster.by_npc(npc)
        if not row or self._row_hidden(row):
            return
        who = clean_name(row["display_name"], row["username"])
        if self.ctx.broadcast is not None:
            # for overlays that want to show it (none ships yet)
            await self.ctx.broadcast({"type": "schedule1", "event": kind, "chatter": who,
                                      "platform": row["platform"], "qty": ev.get("qty"),
                                      "products": ev.get("products") or [], "payment": ev.get("payment")})
        if kind == "contract" and s.get("announce_orders", True):
            await self._say(row["platform"], f"{who} wants {order_text(ev)} for {money(ev.get('payment'))}.")
        elif kind == "deal" and s.get("announce_deals", True):
            await self._say(row["platform"], f"{who} bought {order_text(ev)} for {money(ev.get('payment'))} "
                                             f"(deal #{row['deals']}).")

    async def _app_button(self, kind: str, key: str) -> None:
        """The streamer pressed Remove or Swap on a chatter in the in-game phone app.

        Remove = off the list (like !customer leave). Swap = back of the waiting list, so the next
        waiting chatter gets the customer; with nobody waiting it does nothing and says so on the phone.
        Either way the next sync sends the new names and board.
        """
        row = await self.roster.get(key)
        if not row:
            return
        who = clean_name(row["display_name"], row["username"])
        if kind == "app_remove":
            await self.roster.leave(key)
            log.info("Schedule I: %s removed from the phone app", who)
        else:
            if (await self.roster.counts())["waiting"] == 0:
                await self.bridge.notify("Chat customers", f"Nobody is waiting, so {who} keeps their customer.")
                return
            await self.roster.requeue(key)
            log.info("Schedule I: %s swapped to the back of the line from the phone app", who)
        self._wake.set()

    async def _on_alert(self, payload: dict) -> None:
        """A stream alert (follow, sub, raid, ...; Core's Alerts page test buttons too) -> phone pop-up.

        Only with ``alerts_in_game`` on, only the kinds in ``alert_kinds`` (empty = all but "flag"),
        never for hidden / red-flagged chatters, and only while a save is loaded. When the alerter
        carries a customer, the pop-up says which one.
        """
        s = self._s()
        if not self._running or self.bridge is None or not s.get("alerts_in_game") or not self._loaded:
            return
        kind = str(payload.get("kind") or "").lower()
        wanted = alert_kinds(s.get("alert_kinds"))
        if (wanted and kind not in wanted) or (not wanted and kind in ALERT_KINDS_SKIPPED_BY_DEFAULT):
            return
        plat = str(payload.get("platform") or "").lower()
        username = str(payload.get("username") or "")
        shown = str(payload.get("display_name") or "")
        if self.is_hidden(plat, "", username, shown):
            return
        text = str(payload.get("headline") or "").strip()
        if not text:
            return
        safe = clean_name(shown, username)      # names the game's font can't draw become the username
        if shown and safe and safe != shown:
            text = text.replace(shown, safe)
        row = await self.roster.find_name(plat, username) or await self.roster.find_name(plat, shown)
        cust = next((c for c in self._customers if row and c["id"] == row["npc_id"]), None)
        if cust:
            own = f"{cust.get('first', '')} {cust.get('last', '')}".strip()
            text = f"{text} (your customer {own})"
        try:
            await self.bridge.notify(str(payload.get("title") or "Stream alert"), text)
        except BridgeError as exc:
            log.info("Schedule I: alert not shown in the game: %s", exc)

    async def _say(self, platform: str, text: str) -> None:
        try:
            plat = Platform(str(platform).lower())
        except ValueError:
            return
        await self.ctx.reply(plat, text)

    # ------------------------------------------------------------------ chat

    async def _on_chat(self, event) -> None:
        """``auto_join`` setting: "subs" puts subscribers / members on the list when they chat, "everyone" anyone."""
        if not self._running or self.roster is None:
            return
        mode = str(self._s().get("auto_join") or "off")
        u = getattr(event, "user", None)
        if mode == "off" or u is None or (mode == "subs" and not u.is_subscriber):
            return
        plat = u.platform.value if hasattr(u.platform, "value") else str(u.platform)
        if self.is_hidden(plat, u.id, u.username, u.display_name):
            return
        if await self.roster.get(person_key(plat, u.id, u.username)):
            return
        _row, new = await self.roster.join(plat, u.id, u.username, u.display_name)
        if new:
            self._wake.set()

    async def _on_flag_event(self, payload: dict) -> None:
        """A custom flag marked someone hidden: take them off the list now, not at the next red-flag refresh."""
        if not self._running or not payload.get("hidden"):
            return
        u = payload.get("user") or {}
        key = person_key(payload.get("platform") or "", u.get("id") or "", u.get("username") or "")
        self._flagged_now.add(key)
        if self.roster is not None and await self.roster.leave(key):
            self._wake.set()

    async def execute(self, req: ExecuteRequest) -> dict:
        """Chat commands from commands.json: !customer [leave], !topcustomers."""
        if self.roster is None:
            return {"success": False, "error": "Schedule I plugin not started"}
        name = (req.command_name or "").lower()
        u = req.user
        if name == "topcustomers":
            top = await self.roster.top(3)
            if not top:
                return {"success": True, "reply": "No customer has bought anything yet."}
            parts = [f"{i}. {clean_name(r['display_name'], r['username'])} {money(r['spent'])} ({r['deals']} deals)"
                     for i, r in enumerate(top, 1)]
            return {"success": True, "reply": "Best customers: " + " | ".join(parts)}
        if name != "customer" or u is None:
            return {"success": False, "error": f"unknown Schedule I command {name}"}

        plat = req.platform.value if hasattr(req.platform, "value") else str(req.platform)
        key = person_key(plat, u.id, u.username)
        who = clean_name(u.display_name, u.username)
        arg = (req.args[0].lower() if req.args else "")
        if arg in ("leave", "quit", "stop", "remove"):
            if await self.roster.leave(key):
                self._wake.set()
                return {"success": True, "reply": f"@{who} you're off the customer list."}
            return {"success": True, "reply": f"@{who} you weren't on the customer list."}
        if self.is_hidden(plat, u.id, u.username, u.display_name):
            return {"success": True}          # say nothing to hidden chatters
        if not who:
            return {"success": True, "reply": "That name can't be shown in the game, sorry."}
        row, new = await self.roster.join(plat, u.id, u.username, u.display_name)
        if row["npc_id"]:
            return {"success": True, "reply": f"@{who} you're already a customer: {row['deals']} deals, "
                                              f"{money(row['spent'])} spent. (!customer leave to stop)"}
        if new:
            self._wake.set()
        place = await self.roster.position(key)
        if new:
            return {"success": True, "reply": f"@{who} you're on the customer list (#{place}). "
                                              f"Your name shows up on a customer in the game soon."}
        return {"success": True, "reply": f"@{who} you're #{place} on the waiting list for a customer."}

    # ------------------------------------------------------------------ dashboard

    async def health(self) -> bool:
        return self.connected

    def status(self) -> dict:
        if not self.connected:
            detail = "waiting for the Schedule I mod"
        elif not self._loaded:
            detail = "game on the main menu"
        else:
            named = len(self._sent or {})
            detail = f"{named} customer(s) carry chatter names"
        return {"detail": detail, "bridge_url": self.bridge.base_url if self.bridge else "", "error": self.last_error}

    async def snapshot(self) -> dict:
        """Everything the Schedule I page shows (routes.py GET /api/schedule1/customers)."""
        by_id = {c["id"]: c for c in self._customers}
        people = []
        for r in await self.roster.all():
            cust = by_id.get(r["npc_id"] or "")
            people.append({
                "key": r["key"], "platform": r["platform"], "username": r["username"],
                "display_name": r["display_name"], "name": clean_name(r["display_name"], r["username"]),
                "npc_id": r["npc_id"], "customer": f"{cust.get('first', '')} {cust.get('last', '')}".strip() if cust else "",
                "in_game": bool(cust), "deals": r["deals"], "spent": r["spent"], "joined_at": r["joined_at"],
            })
        return {"connected": self.connected, "loaded": self._loaded, "error": self.last_error,
                "customers_in_game": len(self._customers), "named": len(self._sent or {}),
                "people": people}

    async def add_person(self, platform: str, username: str) -> dict:
        """Streamer adds someone by hand from the page (no account id known, so keyed by name)."""
        plat = str(platform or "").lower()
        if plat not in {p.value for p in Platform}:
            raise ValueError("platform must be twitch, youtube or kick")
        username = str(username or "").strip().lstrip("@")
        if not username:
            raise ValueError("name is empty")
        row, _new = await self.roster.join(plat, "", username, username)
        self._wake.set()
        return row

    async def remove_person(self, key: str) -> bool:
        gone = await self.roster.leave(key)
        if gone:
            self._wake.set()
        return gone

    @classmethod
    def routes(cls, router, get_running):
        from .routes import add_routes
        add_routes(router, get_running)
