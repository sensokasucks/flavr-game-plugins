"""
Suppliers on your phone: chatters spend points so one of the streamer's suppliers (Albert Hoover for
seeds, Shirley Watts for pseudo, Salvador Moreno for coca, ...) does something for the streamer, and
the supplier "says" so in a phone pop-up.

  !tab <supplier> <points>   pays toward what the streamer owes that supplier: ``supplier_tab_rate``
                             in-game $ per point; points for any part the streamer didn't owe come back
  !supply <supplier>         ``supplier_supply_cost`` points: the supplier leaves ``supplier_supply_qty``
                             of one of their goods at a dead drop "from" the chatter (map marker,
                             chat hears when it's picked up)
  !tab / !supply alone       lists the suppliers the streamer has met and what is owed

Settings (plugin.json group "Suppliers"): supplier_enabled (off), supplier_tab_rate,
supplier_supply_cost, supplier_supply_qty, supplier_cooldown_sec (one supplier request per this many
seconds for the whole chat). Suppliers keep their own names (they're story characters); the chatter
is named in the pop-up, which isn't saved (texts are, so nothing goes in the phone's Messages).

Game side (fridge-schedule1/mod/Drops.cs): GET /crew "suppliers": [{"id", "first", "last", "unlocked",
"debt"}]; POST /supplier {"id", "action": "pay" | "deliver", "supplier", "by", "amount", "qty"} answered
by event "supplier_result" {"req", "ok", "msg", "paid", "debt", "where", "what"}; a delivery's pick-up
is "drop_taken" {"drop": the same id}. Host only in co-op.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .bridge import BridgeError
from .feature import Feature, fmt_money, match_name, who_of

log = logging.getLogger("plugins.schedule1")
ANSWER_SEC = 30


def tab_points(points: int, rate: float, debt: float) -> tuple[float, int]:
    """(in-game $ to pay, points it uses) for ``points`` offered at ``rate`` $ per point toward
    ``debt``. Never pays more than is owed; the points for the rest stay with the chatter."""
    if points <= 0 or rate <= 0 or debt <= 0:
        return 0.0, 0
    pay = min(points * rate, debt)
    used = min(points, int(-(-pay // rate)))           # round up: a part-point still costs a point
    return round(pay, 2), used


class Suppliers(Feature):
    def __init__(self, plugin):
        super().__init__(plugin)
        self._ready_at = 0.0
        # request id -> {"action", "who", "platform", "uid", "cost", "supplier", "at", "answered", "what"}
        self.pending: dict[int, dict] = {}
        self._seq = 0

    def on(self) -> bool:
        return bool(self.s().get("supplier_enabled"))

    def met(self) -> list[dict]:
        return [x for x in self.p.crew.get("suppliers") or [] if x.get("unlocked")]

    def listing(self) -> str:
        rows = self.met()
        if not rows:
            return "The streamer hasn't met any suppliers yet."
        return "Suppliers: " + " | ".join(
            f"{r.get('first')} (owed {fmt_money(r.get('debt'))})" if float(r.get("debt") or 0) > 0 else str(r.get("first"))
            for r in rows)

    async def execute(self, name: str, req) -> Optional[dict]:
        if name not in ("tab", "supply") or req.user is None:
            return None
        u = req.user
        plat, _key, who = who_of(req)
        if not self.on():
            return {"success": True, "reply": "Supplier commands are switched off."}
        if self.p.is_hidden(plat, u.id, u.username, u.display_name) or not who:
            return {"success": True}
        if (why := self.ready()) or (why := self.host_only()):
            return {"success": True, "reply": f"@{who} {why}."}
        p = self.p._prefix()
        if not req.args:
            usage = f"{p}tab <supplier> <points>" if name == "tab" else f"{p}supply <supplier>"
            return {"success": True, "reply": f"@{who} {usage}. {self.listing()}"}
        sup = match_name(req.args[0], self.met())
        if sup is None:
            return {"success": True, "reply": f"@{who} no supplier called {req.args[0]}. {self.listing()}"}
        wait = self._ready_at - time.monotonic()
        if wait > 0:
            return {"success": True, "reply": f"@{who} the suppliers are busy, try again in {int(wait) + 1}s."}

        if name == "tab":
            try:
                offered = int(req.args[1]) if len(req.args) > 1 else 0
            except ValueError:
                offered = 0
            if offered <= 0:
                return {"success": True, "reply": f"@{who} {p}tab {sup['first'].lower()} <points>, e.g. {p}tab "
                                                  f"{sup['first'].lower()} 500 ({fmt_money(self.num('supplier_tab_rate', 0.2, 0) * 500)})"}
            pay, used = tab_points(offered, self.num("supplier_tab_rate", 0.2, 0), float(sup.get("debt") or 0))
            if used <= 0:
                return {"success": True, "reply": f"@{who} the streamer doesn't owe {sup['first']} anything."}
            paid, uid, msg = await self.charge(req, used, f"!tab {sup['first']} (Schedule I)")
            if not paid:
                return {"success": True, "reply": f"@{who} {msg}."}
            return await self._send(req, "pay", sup, uid, used, amount=pay)

        cost = int(self.num("supplier_supply_cost", 750, 0))
        paid, uid, msg = await self.charge(req, cost, f"!supply {sup['first']} (Schedule I)")
        if not paid:
            return {"success": True, "reply": f"@{who} {msg}."}
        return await self._send(req, "deliver", sup, uid, cost, qty=int(self.num("supplier_supply_qty", 5, 1)))

    async def _send(self, req, action: str, sup: dict, uid, cost: int, amount: float = 0, qty: int = 0) -> dict:
        plat, _key, who = who_of(req)
        self._seq += 1
        rid = int(time.time() * 1000) * 10 + self._seq % 10
        self.pending[rid] = {"action": action, "who": who, "platform": plat, "uid": uid, "cost": cost,
                             "supplier": sup["first"], "at": time.monotonic(), "answered": False, "what": ""}
        try:
            await self.p.bridge.supplier(rid, action, sup["id"], who, amount=amount, qty=qty)
        except BridgeError as exc:
            self.pending.pop(rid, None)
            await self.refund(uid, cost, "supplier refund (Schedule I)")
            return {"success": True, "reply": f"@{who} the game didn't answer ({exc.__class__.__name__}). Points refunded."}
        self._ready_at = time.monotonic() + self.num("supplier_cooldown_sec", 300, 0)
        if action == "pay":
            return {"success": True, "reply": f"@{who} paid {cost} points: {fmt_money(amount)} goes to {sup['first']}."}
        return {"success": True, "reply": f"@{who} paid {cost} points: {sup['first']} is preparing a drop."}

    async def handle_event(self, ev: dict) -> bool:
        kind = ev.get("type")
        if kind == "supplier_result":
            r = self.pending.get(int(ev.get("req") or 0))
            if r is None:
                return True
            r["answered"] = True
            if not ev.get("ok"):
                await self._failed(int(ev["req"]), str(ev.get("msg") or "the game refused"))
                return True
            self.p.crew_wake = True               # debts changed: read them again
            if r["action"] == "pay":
                self.pending.pop(int(ev["req"]), None)
                left = float(ev.get("debt") or 0)
                await self.p._say(r["platform"], f"💸 {r['who']} paid {fmt_money(ev.get('paid'))} of the streamer's "
                                                 f"tab with {r['supplier']}" + (f" ({fmt_money(left)} still owed)." if left > 0
                                                                                 else ". All paid off!"))
            else:
                r["what"] = str(ev.get("what") or "a delivery")
                await self.p._say(r["platform"], f"📦 {r['supplier']} left {r['what']} from {r['who']} at "
                                                 f"{ev.get('where') or 'a dead drop'}.")
            return True
        if kind == "drop_taken":
            r = self.pending.get(int(ev.get("drop") or 0))
            if r is None:
                return False                      # a cash drop (drops.py)
            self.pending.pop(int(ev["drop"]), None)
            await self.p._say(r["platform"], f"📦 The streamer picked up {r['who']}'s delivery from {r['supplier']}.")
            return True
        return False

    async def _failed(self, rid: int, why: str) -> None:
        r = self.pending.pop(rid, None)
        if r is None:
            return
        await self.refund(r["uid"], r["cost"], "supplier refund (Schedule I)")
        self._ready_at = 0.0
        await self.p._say(r["platform"], f"@{r['who']} {r['supplier']} couldn't do it: {why}. Points refunded.")

    async def tick(self) -> None:
        now = time.monotonic()
        for rid, r in list(self.pending.items()):
            if not r["answered"] and now - r["at"] > ANSWER_SEC:
                await self._failed(rid, "the game didn't answer")
