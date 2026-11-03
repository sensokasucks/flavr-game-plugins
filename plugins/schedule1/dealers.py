"""
Dealers sponsored by chatters: a chatter backs one of the streamer's dealers (Benji, Molly, Brad,
Jane, Wei, Leo) with points and follows how it sells, like owning a team.

  !sponsor                       who backs which dealer, and the lowest bid
  !sponsor <dealer> <points>     back a dealer: at least ``dealer_min_bid`` and more than its current
                                 sponsor paid. The old sponsor gets their points back
                                 (``dealer_refund_outbid``) and is told. One dealer per chatter.
  !sponsor leave                 stop backing your dealer (no refund)
  !topdealers                    sponsors whose dealers sold the most

While backed, the dealer shows as "Benji (zackfan99)" on the streamer's screen (first name kept, so
the story still makes sense), chat hears its sales (added up, one line per ``dealer_announce_sec``),
robberies and "out of stock", and the sponsor earns ``dealer_kickback_per_100`` Core points per $100
the dealer takes in. Settings: plugin.json group "Dealer sponsors" (dealer_enabled off by default,
dealer_subs_only).

Game side (fridge-schedule1/mod/Crew.cs): GET /crew "dealers": [{"id", "first", "last", "cash",
"stock", "customers"}] (recruited dealers only); POST /crewnames {"dealers": {id: {"first", "last"}}}
(names come off while the game saves, like workers); events "dealer_sale" {"id", "amount", "deals"},
"dealer_robbed" {"id", "cash", "items"}, "dealer_empty" {"id"}. Host only in co-op.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .bridge import BridgeError
from .feature import Feature, fmt_money, match_name, who_of
from .roster import clean_name

log = logging.getLogger("plugins.schedule1")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sponsors (
    key          TEXT PRIMARY KEY,          -- roster.person_key() of the chatter
    platform     TEXT NOT NULL,
    user_id      TEXT NOT NULL DEFAULT '',
    username     TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    dealer_id    TEXT UNIQUE,               -- the dealer they back now (game NPC id), NULL = none
    bid          INTEGER NOT NULL DEFAULT 0, -- points paid for the dealer they back now
    since        REAL,
    sales        REAL NOT NULL DEFAULT 0,   -- in-game $ their dealers took in while backed, all time
    kickback     INTEGER NOT NULL DEFAULT 0  -- Core points earned from it, all time
);
"""


def dealer_label(first: str, sponsor: str) -> dict[str, str]:
    """The name a backed dealer shows: own first name, the sponsor in brackets as the last name."""
    return {"first": first, "last": f"({sponsor})"}


def kickback_points(amount: float, per_100: float, carry: float) -> tuple[int, float]:
    """(whole points to pay now, fraction carried to the next sale) for ``amount`` in-game $ at
    ``per_100`` points per $100."""
    total = carry + max(0.0, amount) * max(0.0, per_100) / 100.0
    whole = int(total)
    return whole, total - whole


class Dealers(Feature):
    def __init__(self, plugin):
        super().__init__(plugin)
        self._sent: Optional[dict] = None
        self._sent_boot = ""
        self._carry: dict[str, float] = {}               # person key -> kickback fraction not paid yet
        self._sales: dict[str, list] = {}                # dealer id -> [amount, deals] not said yet
        self._said_at: dict[str, float] = {}

    async def setup(self) -> None:
        await self.p.ctx.db.script(SCHEMA)

    def on(self) -> bool:
        return bool(self.s().get("dealer_enabled"))

    def dealers(self) -> list[dict]:
        return list(self.p.crew.get("dealers") or [])

    async def rows(self) -> list[dict]:
        return await self.p.ctx.db.fetchall("SELECT * FROM sponsors WHERE dealer_id IS NOT NULL ORDER BY since")

    async def row(self, key: str) -> Optional[dict]:
        return await self.p.ctx.db.fetchone("SELECT * FROM sponsors WHERE key = ?", (key,))

    async def by_dealer(self, dealer_id: str) -> Optional[dict]:
        return await self.p.ctx.db.fetchone("SELECT * FROM sponsors WHERE dealer_id = ?", (dealer_id,))

    async def listing(self) -> str:
        ds = self.dealers()
        if not ds:
            return "The streamer has no dealers yet."
        backed = {r["dealer_id"]: r for r in await self.rows()}
        low = int(self.num("dealer_min_bid", 500, 0))
        parts = []
        for d in ds:
            r = backed.get(d["id"])
            parts.append(f"{d['first']} ({clean_name(r['display_name'], r['username'])}, {r['bid']})" if r
                         else f"{d['first']} (free, {low}+)")
        return "Dealers: " + " | ".join(parts)

    # ---- chat

    async def execute(self, name: str, req) -> Optional[dict]:
        if name not in ("sponsor", "topdealers") or req.user is None:
            return None
        db = self.p.ctx.db
        if name == "topdealers":
            top = await db.fetchall("SELECT * FROM sponsors WHERE sales > 0 ORDER BY sales DESC LIMIT 3")
            if not top:
                return {"success": True, "reply": "No sponsored dealer has sold anything yet."}
            return {"success": True, "reply": "Best sponsors: " + " | ".join(
                f"{i}. {clean_name(r['display_name'], r['username'])} {fmt_money(r['sales'])} ({r['kickback']} pts)"
                for i, r in enumerate(top, 1))}
        u = req.user
        plat, key, who = who_of(req)
        mine = await self.row(key)
        arg = (req.args[0].lower() if req.args else "")
        if arg in ("leave", "stop", "quit"):
            if not mine or not mine["dealer_id"]:
                return {"success": True, "reply": f"@{who} you don't back a dealer."}
            await db.execute("UPDATE sponsors SET dealer_id = NULL, bid = 0 WHERE key = ?", (key,))
            return {"success": True, "reply": f"@{who} you stopped backing your dealer."}
        if not self.on():
            return {"success": True, "reply": "Dealer sponsors are switched off."}
        if self.p.is_hidden(plat, u.id, u.username, u.display_name) or not who:
            return {"success": True}
        if (why := self.ready()) or (why := self.host_only()):
            return {"success": True, "reply": f"@{who} {why}."}
        p = self.p._prefix()
        if not req.args:
            return {"success": True, "reply": f"@{who} {await self.listing()} · {p}sponsor <dealer> <points>"}
        d = match_name(req.args[0], self.dealers())
        if d is None:
            return {"success": True, "reply": f"@{who} no dealer called {req.args[0]}. {await self.listing()}"}
        if self.s().get("dealer_subs_only") and not getattr(u, "is_subscriber", False):
            return {"success": True, "reply": f"@{who} only subscribers / members can back a dealer."}
        if mine and mine["dealer_id"]:
            cur = next((x for x in self.dealers() if x["id"] == mine["dealer_id"]), None)
            return {"success": True, "reply": f"@{who} you already back {cur['first'] if cur else 'a dealer'} "
                                              f"({p}sponsor leave first)."}
        try:
            bid = int(req.args[1]) if len(req.args) > 1 else 0
        except ValueError:
            bid = 0
        old = await self.by_dealer(d["id"])
        need = max(int(self.num("dealer_min_bid", 500, 0)), (old["bid"] + 1) if old else 0)
        if bid < need:
            return {"success": True, "reply": f"@{who} backing {d['first']} takes at least {need} points "
                                              f"({p}sponsor {d['first'].lower()} {need})."}
        paid, _uid, msg = await self.charge(req, bid, f"!sponsor {d['first']} (Schedule I)")
        if not paid:
            return {"success": True, "reply": f"@{who} {msg}."}
        if old:
            await db.execute("UPDATE sponsors SET dealer_id = NULL, bid = 0 WHERE key = ?", (old["key"],))
            if self.s().get("dealer_refund_outbid", True):
                await self.give(old["platform"], old["user_id"], old["username"], old["display_name"], old["bid"],
                                f"outbid on {d['first']} (Schedule I)")
            await self.p._say(old["platform"], f"@{clean_name(old['display_name'], old['username'])} {who} outbid you on "
                                               f"{d['first']}" + (f"; your {old['bid']} points are back." if
                                                                   self.s().get("dealer_refund_outbid", True) else "."))
        if mine:
            await db.execute("UPDATE sponsors SET dealer_id = ?, bid = ?, since = ?, display_name = ? WHERE key = ?",
                             (d["id"], bid, time.time(), u.display_name or u.username, key))
        else:
            await db.execute("INSERT INTO sponsors (key, platform, user_id, username, display_name, dealer_id, bid, since)"
                             " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (key, plat, str(u.id or ""), u.username.lower(), u.display_name or u.username, d["id"], bid,
                              time.time()))
        self.p._wake.set()
        return {"success": True, "reply": f"@{who} you back {d['first']} now ({bid} points). You earn points from "
                                          f"every sale."}

    # ---- loop: names

    async def tick(self) -> None:
        if self.p.bridge is None:
            return
        if not self.on():
            if self._sent:
                await self._send({})
            return
        if self.p.role == "client" or not self.p.crew.get("loaded"):
            return
        db = self.p.ctx.db
        ds = {d["id"]: d for d in self.dealers()}
        names = {}
        for r in await self.rows():
            if self.p.is_hidden(r["platform"], r["user_id"], r["username"], r["display_name"]):
                await db.execute("UPDATE sponsors SET dealer_id = NULL, bid = 0 WHERE key = ?", (r["key"],))
                continue
            d = ds.get(r["dealer_id"])
            who = clean_name(r["display_name"], r["username"], int(self.s().get("max_name_len") or 24))
            if d and who:
                names[d["id"]] = dealer_label(str(d.get("first") or ""), who)
        await self._send(names)
        await self._flush_sales()

    async def _send(self, names: dict) -> None:
        boot = str(self.p._boot or "")
        if names == self._sent and boot == self._sent_boot:
            return
        try:
            await self.p.bridge.crew_names(dealers=names)
        except BridgeError as exc:
            log.info("Schedule I: dealer names not sent: %s", exc)
            return
        self._sent, self._sent_boot = names, boot

    # ---- the mod's events

    async def handle_event(self, ev: dict) -> bool:
        kind = ev.get("type")
        if kind not in ("dealer_sale", "dealer_robbed", "dealer_empty"):
            return False
        did = str(ev.get("id") or "")
        r = await self.by_dealer(did)
        if r is None or not self.on():
            return True
        d = next((x for x in self.dealers() if x["id"] == did), {"first": "Their dealer"})
        who = clean_name(r["display_name"], r["username"])
        if kind == "dealer_sale":
            amount = max(0.0, float(ev.get("amount") or 0))
            pts, self._carry[r["key"]] = kickback_points(amount, self.num("dealer_kickback_per_100", 10, 0),
                                                         self._carry.get(r["key"], 0.0))
            await self.p.ctx.db.execute("UPDATE sponsors SET sales = sales + ?, kickback = kickback + ? WHERE key = ?",
                                        (amount, pts, r["key"]))
            if pts:
                await self.give(r["platform"], r["user_id"], r["username"], r["display_name"], pts,
                                f"{d['first']}'s sales (Schedule I)")
            got = self._sales.setdefault(did, [0.0, 0])
            got[0] += amount
            got[1] += max(1, int(ev.get("deals") or 1))
        elif kind == "dealer_robbed":
            lost = [fmt_money(ev.get("cash"))] if float(ev.get("cash") or 0) > 0 else []
            if int(ev.get("items") or 0) > 0:
                lost.append(f"{int(ev['items'])} items")
            await self.p._say(r["platform"], f"🚨 {who}'s dealer {d['first']} got robbed" +
                              (f": lost {' and '.join(lost)}." if lost else "!"))
        else:
            await self.p._say(r["platform"], f"📦 {who}'s dealer {d['first']} is out of stock. Time to restock!")
        return True

    async def _flush_sales(self) -> None:
        if not self._sales:
            return
        if not self.s().get("dealer_announce_sales", True):
            self._sales.clear()
            return
        every = self.num("dealer_announce_sec", 120, 0)
        now = time.monotonic()
        for did in list(self._sales):
            if now - self._said_at.get(did, -1e9) < every:
                continue
            amount, deals = self._sales.pop(did)
            r = await self.by_dealer(did)
            d = next((x for x in self.dealers() if x["id"] == did), None)
            if not r or not d:
                continue
            self._said_at[did] = now
            who = clean_name(r["display_name"], r["username"])
            await self.p._say(r["platform"], f"💵 {who}'s dealer {d['first']} sold {deals} deal{'s' if deals != 1 else ''} "
                                             f"for {fmt_money(amount)}.")

    async def snapshot(self) -> list[dict]:
        backed = {r["dealer_id"]: r for r in await self.rows()}
        out = []
        for d in self.dealers():
            r = backed.get(d["id"])
            out.append({"id": d["id"], "dealer": f"{d.get('first', '')} {d.get('last', '')}".strip(),
                        "sponsor": clean_name(r["display_name"], r["username"]) if r else "",
                        "bid": r["bid"] if r else 0, "sales": r["sales"] if r else 0,
                        "cash": d.get("cash") or 0, "stock": d.get("stock") or 0})
        return out
