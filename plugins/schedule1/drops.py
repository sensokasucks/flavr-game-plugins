"""
Cash drops: a donation (bits, Super Chat, tips, gifted subs, KICKs ...) or a points command ``!drop``
puts in-game cash into one of Schedule I's dead drops, with a note from the donor. The streamer gets a
phone pop-up and a map marker, and chat hears when the cash is picked up.

Flow:
  1. plugin.py's event bus handler -> on_alert (paid alert kinds in ``drop_kinds``) or chat ``!drop``
     -> ``request()`` works out the amount and sends POST /drop {"id", "by", "note", "cash", "label"}.
  2. The mod (fridge-schedule1/mod/Drops.cs) picks an empty dead drop away from the player, puts a
     cash item in it, marks it on the phone map and answers with event "drop_result" {"drop", "ok",
     "msg", "where"}; a refused ``!drop`` gets its points back.
  3. When the drop is emptied the mod sends "drop_taken" {"drop"} and chat hears it.

Amounts (settings, plugin.json group "Cash drops"):
  drop_per_dollar   in-game $ per real $1 of the alert (feature.alert_dollars: 100 bits = $1,
                    100 KICKs = $1, a gifted sub = $5, other currencies 1:1)
  drop_min_dollars  smaller alerts make no drop
  drop_max          most in-game $ in one drop
  drop_stream_max   most in-game $ dropped since Stream Core started (0 = no limit)
  drop_cost / drop_cash / drop_cooldown_sec   the !drop command (0 cost = command off)
The note is the alert's own message (or !drop's words), at most ``drop_note_len`` characters, never
from hidden / red-flagged viewers (their drop still comes, "from a viewer"). Host only in co-op.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .bridge import BridgeError
from .feature import Feature, alert_dollars, fmt_money, kinds_setting, who_of
from .roster import clean_name

log = logging.getLogger("plugins.schedule1")

# Alert kinds that carry money; the default for ``drop_kinds`` (charity goes to the charity, so it's left out).
PAID_KINDS = {"bits", "superchat", "donation", "supersticker", "kicks", "gift", "powerup", "celebration"}
ANSWER_SEC = 30                # no "drop_result" by then: the !drop is refunded


def drop_amount(dollars: float, per_dollar: float, cap: float, left: Optional[float]) -> float:
    """In-game cash for ``dollars`` real dollars: ``per_dollar`` each, at most ``cap`` and at most
    ``left`` (what the stream's limit still allows; None = no limit). Whole dollars."""
    cash = max(0.0, dollars) * max(0.0, per_dollar)
    if cap > 0:
        cash = min(cash, cap)
    if left is not None:
        cash = min(cash, max(0.0, left))
    return float(int(cash))


def clean_note(text: str, max_len: int = 100) -> str:
    """The donor's message as a one-line note: no line breaks, no rich-text tags (the phone draws
    tags), cut at a word to ``max_len`` characters."""
    t = " ".join(str(text or "").replace("<", "‹").replace(">", "›").split())
    if len(t) > max_len:
        cut = t[:max_len]
        t = (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip() + "…"
    return t


class Drops(Feature):
    """Paid alerts and !drop -> POST /drop; the mod's answers -> chat lines and refunds."""

    def __init__(self, plugin):
        super().__init__(plugin)
        self.dropped = 0.0                 # in-game $ dropped since Stream Core started (drop_stream_max)
        self._ready_at = 0.0               # time.monotonic() when !drop may be used again
        # drop id -> {"by", "platform", "cash", "uid", "cost", "at", "answered"}
        self.pending: dict[int, dict] = {}
        self._seq = 0

    def on(self) -> bool:
        return bool(self.s().get("drop_enabled"))

    def _new_id(self) -> int:
        self._seq += 1
        return int(time.time() * 1000) * 10 + self._seq % 10

    def _left(self) -> Optional[float]:
        cap = self.num("drop_stream_max", 10000, 0)
        return None if cap <= 0 else cap - self.dropped

    async def request(self, by: str, platform: str, cash: float, note: str, uid=None, cost: int = 0) -> Optional[str]:
        """Send one drop to the game. None when asked, else why not (nothing was sent then)."""
        if cash <= 0:
            return "the stream's cash drop limit is used up"
        if (why := self.ready()) or (why := self.host_only()):
            return why
        drop_id = self._new_id()
        self.pending[drop_id] = {"by": by, "platform": platform, "cash": cash, "uid": uid, "cost": cost,
                                 "at": time.monotonic(), "answered": False}
        self.dropped += cash
        try:
            await self.p.bridge.drop(drop_id, by, cash, note, label="Cash drop")
        except BridgeError as exc:
            self.pending.pop(drop_id, None)
            self.dropped -= cash
            return f"the game didn't answer ({exc.__class__.__name__})"
        return None

    # ---- paid alerts

    async def on_alert(self, payload: dict) -> None:
        # Alerts page test buttons make drops too, so the streamer can try it without a real tip.
        if not self.on() or self.p.bridge is None:
            return
        kind = str(payload.get("kind") or "").lower()
        if kind not in kinds_setting(self.s().get("drop_kinds"), PAID_KINDS):
            return
        dollars = alert_dollars(payload)
        if dollars < self.num("drop_min_dollars", 1, 0) or dollars <= 0:
            return
        cash = drop_amount(dollars, self.num("drop_per_dollar", 100, 0), self.num("drop_max", 2000, 0), self._left())
        plat = str(payload.get("platform") or "").lower()
        user, shown = str(payload.get("username") or ""), str(payload.get("display_name") or "")
        hidden = self.p.is_hidden(plat, "", user, shown)
        by = "a viewer" if hidden else (clean_name(shown, user) or "a viewer")
        note = "" if hidden else clean_note(payload.get("message") or "", int(self.num("drop_note_len", 100, 0)))
        why = await self.request(by, plat, cash, note)
        if why:
            log.info("Schedule I: no cash drop for %s's %s: %s", by, kind, why)

    # ---- !drop

    async def execute(self, name: str, req) -> Optional[dict]:
        if name != "drop" or req.user is None:
            return None
        u = req.user
        plat, _key, who = who_of(req)
        cost = int(self.num("drop_cost", 500, 0))
        if not self.on() or cost <= 0:
            return {"success": True, "reply": "Cash drops for points are switched off."}
        if self.p.is_hidden(plat, u.id, u.username, u.display_name) or not who:
            return {"success": True}
        if (why := self.ready()) or (why := self.host_only()):
            return {"success": True, "reply": f"@{who} {why}."}
        wait = self._ready_at - time.monotonic()
        if wait > 0:
            return {"success": True, "reply": f"@{who} the last drop was just now, try again in {int(wait) + 1}s."}
        cash = drop_amount(1, self.num("drop_cash", 200, 0), self.num("drop_max", 2000, 0), self._left())
        if cash <= 0:
            return {"success": True, "reply": f"@{who} the stream's cash drop limit is used up."}
        paid, uid, msg = await self.charge(req, cost, "!drop (Schedule I)")
        if not paid:
            return {"success": True, "reply": f"@{who} {msg}."}
        note = clean_note(" ".join(req.args or []), int(self.num("drop_note_len", 100, 0)))
        why = await self.request(who, plat, cash, note, uid=uid, cost=cost)
        if why:
            await self.refund(uid, cost, "!drop refund (Schedule I)")
            return {"success": True, "reply": f"@{who} no drop: {why}. Points refunded."}
        self._ready_at = time.monotonic() + self.num("drop_cooldown_sec", 300, 0)
        return {"success": True, "reply": f"@{who} paid {cost} points: {fmt_money(cash)} is on its way to a dead drop."}

    # ---- the mod's answers

    async def handle_event(self, ev: dict) -> bool:
        kind = ev.get("type")
        if kind not in ("drop_result", "drop_taken"):
            return False
        drop = self.pending.get(int(ev.get("drop") or 0))
        if drop is None:
            return False                          # another feature's drop (a supplier delivery)
        say = self.s().get("drop_announce", True)
        if kind == "drop_result":
            drop["answered"] = True
            if ev.get("ok"):
                if say:
                    await self.p._say(drop["platform"], f"💰 {drop['by']}'s {fmt_money(drop['cash'])} is waiting "
                                                        f"for the streamer at {ev.get('where') or 'a dead drop'}.")
            else:
                await self._failed(int(ev["drop"]), str(ev.get("msg") or "the game refused"))
            return True
        self.pending.pop(int(ev["drop"]), None)
        if say:
            await self.p._say(drop["platform"], f"💰 The streamer picked up {drop['by']}'s {fmt_money(drop['cash'])}!")
        return True

    async def _failed(self, drop_id: int, why: str) -> None:
        drop = self.pending.pop(drop_id, None)
        if drop is None:
            return
        self.dropped -= drop["cash"]
        if drop["uid"] is not None:
            await self.refund(drop["uid"], drop["cost"], "!drop refund (Schedule I)")
            self._ready_at = 0.0
            await self.p._say(drop["platform"], f"@{drop['by']} no drop: {why}. Points refunded.")
        else:
            log.info("Schedule I: cash drop for %s failed: %s", drop["by"], why)

    async def tick(self) -> None:
        now = time.monotonic()
        for drop_id, d in list(self.pending.items()):
            if not d["answered"] and now - d["at"] > ANSWER_SEC:
                await self._failed(drop_id, "the game didn't answer")
