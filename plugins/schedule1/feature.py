"""
Shared base for the Schedule I plugin's extra features (staff, cash drops, ingredient vote, suppliers,
dealer sponsors), so plugin.py only needs a few hook lines for all of them.

plugin.py (Schedule1Customers) makes one of each Feature subclass in __init__ (``self.features``) and calls:

  setup()            once from start(), after the customer table is open (make tables here)
  tick()             every loop pass from tick(), after the customer sync and event poll
  handle_event(ev)   for every mod event (GET /events) before the customer code; True = "mine, done"
  execute(name, req) for every chat command before the customer commands; a dict = the answer,
                     None = "not mine"
  on_chat(event)     every chat line (votes are read here)
  on_alert(payload)  every stream alert from Core's event bus (paid ones become cash drops)

A feature reaches the rest of the plugin through ``self.p`` (the plugin): its bridge (HTTP client for
the mod), settings (``self.s()``), the hide list / red flags (``p.is_hidden``), chat lines (``p._say``,
``p._announce``), Core's points (``self.store()``) and the latest GET /crew answer (``p.crew``, kept
fresh by CrewSync in this file).

Helpers at the bottom (fmt_money, alert_dollars, who_of) do no I/O; the tests use them directly.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Optional

from .bridge import BridgeError
from .roster import clean_name, person_key

log = logging.getLogger("plugins.schedule1")


class Feature:
    """Hook points with "do nothing" defaults; subclasses fill in what they need."""

    def __init__(self, plugin):
        self.p = plugin

    # ---- settings and Core services
    def s(self) -> dict:
        """The plugin's live ``schedule1:`` settings block (changes on the page apply at once)."""
        return self.p._s()

    def num(self, key: str, default: float, lo: float = 0.0) -> float:
        """A number setting, never below ``lo``; ``default`` when it isn't a number."""
        return self.p._num(key, default, lo)

    def store(self):
        """Core's store (points, users), or None in odd test setups."""
        return getattr(self.p.ctx, "store", None)

    def host_only(self) -> Optional[str]:
        """Text for chat when this game is a co-op guest (the host's game owns staff, dealers and
        dead drops), else None. The mod's GET /customers "role" sets ``p.role``."""
        if self.p.role == "client":
            return "only the co-op host's chat can do that in Schedule I"
        return None

    def ready(self) -> Optional[str]:
        """Why the game can't do it right now ("" -> None when it can)."""
        if not self.p.connected or not self.p._loaded:
            return "the game isn't running"
        return None

    # ---- hooks (plugin.py calls these)
    async def setup(self) -> None:
        pass

    async def tick(self) -> None:
        pass

    async def handle_event(self, ev: dict) -> bool:
        return False

    async def execute(self, name: str, req) -> Optional[dict]:
        return None

    async def on_chat(self, event) -> None:
        pass

    async def on_alert(self, payload: dict) -> None:
        pass

    # ---- points
    async def charge(self, req, cost: int, why: str) -> tuple[bool, Optional[int], str]:
        """Take ``cost`` points from the chatter behind ``req``. (paid, Core user id, reply when not paid).
        cost 0 = free (paid True, uid None)."""
        if cost <= 0:
            return True, None, ""
        store = self.store()
        if store is None:
            return False, None, "points are not available"
        u = req.user
        plat = plat_of(req)
        uid = await store.get_or_create_user(plat, u.id, u.username, u.display_name)
        paid, balance = await store.spend_points(uid, cost, 1, why, "schedule1")
        if not paid:
            return False, uid, f"that costs {cost} points, you have {balance}"
        return True, uid, ""

    async def refund(self, uid: Optional[int], points: int, why: str) -> None:
        """Give points back (a request the game refused, an outbid sponsor)."""
        store = self.store()
        if uid is not None and points > 0 and store is not None:
            await store.adjust_points(uid, int(points), why, "schedule1")

    async def give(self, platform: str, user_id: str, username: str, display_name: str, points: int,
                   why: str) -> None:
        """Pay points to a chatter (a dealer sponsor's kickback)."""
        store = self.store()
        if store is None or points <= 0:
            return
        uid = await store.get_or_create_user(platform, user_id, username, display_name)
        await store.adjust_points(uid, int(points), why, "schedule1")


class CrewSync(Feature):
    """Keeps ``p.crew`` (the mod's GET /crew: staff, dealers, suppliers) fresh for the other features.

    Read every ``sync_sec`` while staff, dealer sponsors or suppliers are switched on, and right away
    after ``p.crew_wake`` is set. A mod from before these features answers 404: then it's asked again
    only every few minutes, and the rest of the plugin keeps working (BridgeError is swallowed here).
    """

    OLD_MOD_RETRY_SEC = 300

    def __init__(self, plugin):
        super().__init__(plugin)
        self._next = 0.0
        self.supported = True

    def wanted(self) -> bool:
        s = self.s()
        return bool(s.get("staff_enabled") or s.get("dealer_enabled") or s.get("supplier_enabled"))

    async def tick(self) -> None:
        if not self.wanted() or self.p.bridge is None:
            return
        now = time.monotonic()
        if now < self._next and not self.p.crew_wake:
            return
        self.p.crew_wake = False
        try:
            data = await self.p.bridge.crew()
            self.supported = True
            self._next = now + self.num("sync_sec", 10, 2)
        except BridgeError as exc:
            if "404" in str(exc):
                if self.supported:
                    log.info("Schedule I: this mod version has no staff / dealers / suppliers yet (update FridgeSchedule1.dll)")
                self.supported = False
                self._next = now + self.OLD_MOD_RETRY_SEC
            else:
                self._next = now + self.num("sync_sec", 10, 2)
            return
        self.p.crew = {
            "loaded": bool(data.get("loaded")),
            "staff": [x for x in data.get("staff") or [] if isinstance(x, dict) and x.get("id")],
            "dealers": [x for x in data.get("dealers") or [] if isinstance(x, dict) and x.get("id")],
            "suppliers": [x for x in data.get("suppliers") or [] if isinstance(x, dict) and x.get("id")],
        }


# ---------------------------------------------------------------- pure helpers

def plat_of(req) -> str:
    """"twitch" / "youtube" / "kick" from an ExecuteRequest."""
    return req.platform.value if hasattr(req.platform, "value") else str(req.platform)


def who_of(req) -> tuple[str, str, str]:
    """(platform, person key, name for chat / the game) of the chatter behind ``req``."""
    u = req.user
    plat = plat_of(req)
    return plat, person_key(plat, u.id, u.username), clean_name(u.display_name, u.username)


def fmt_money(amount: Any) -> str:
    """In-game dollars as chat text: 240 -> "$240", 12.5 -> "$12.50" (same as plugin.money)."""
    try:
        v = float(amount or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"${v:,.0f}" if v.is_integer() else f"${v:,.2f}"


# Real-money worth of one unit of these alert currencies, in US dollars (approximate on purpose: the
# point is "a bigger tip makes a bigger drop", not exact exchange rates). Other currency codes count
# 1:1 like dollars.
CURRENCY_DOLLARS = {"bits": 0.01, "kicks": 0.01}
GIFT_SUB_DOLLARS = 5.0         # one gifted sub, for "gift" alerts (they carry a qty, not an amount)


def alert_dollars(payload: dict) -> float:
    """Roughly how many real dollars a stream alert is worth (Core's core/alerts.py payload fields
    ``kind``, ``amount``, ``currency``, ``qty``). 0 for alerts that carry no money (follows, raids...)."""
    kind = str(payload.get("kind") or "").lower()
    if kind == "gift":
        try:
            return max(0.0, float(payload.get("qty") or 1)) * GIFT_SUB_DOLLARS
        except (TypeError, ValueError):
            return GIFT_SUB_DOLLARS
    try:
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0 or not math.isfinite(amount):
        return 0.0
    cur = str(payload.get("currency") or "USD").strip().lower()
    return amount * CURRENCY_DOLLARS.get(cur, 1.0)


def kinds_setting(value: Any, default: set[str]) -> set[str]:
    """A list-or-"a, b" setting as lower-case words; empty = ``default``."""
    if isinstance(value, str):
        value = value.split(",")
    got = {str(k).strip().lower() for k in (value or []) if str(k).strip()}
    return got or set(default)


def match_name(text: str, rows: list[dict], fields: tuple[str, ...] = ("first", "id")) -> Optional[dict]:
    """The row whose first name or id starts with ``text`` ("benji", "alb" -> Albert), ignoring case.
    An exact match wins over a prefix; None when nothing or more than one row matches the prefix."""
    t = str(text or "").strip().lower().lstrip("@")
    if not t:
        return None
    exact = [r for r in rows if any(str(r.get(f) or "").lower() == t for f in fields)]
    if exact:
        return exact[0]
    pref = [r for r in rows if any(str(r.get(f) or "").lower().startswith(t) for f in fields)]
    return pref[0] if len(pref) == 1 else None
