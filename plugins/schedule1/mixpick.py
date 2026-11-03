"""
Chat picks the next mixing ingredient: the "Let chat pick" button on Schedule I's mixing station.

The streamer puts a product in a mixing station and presses "Let chat pick" (fridge-schedule1/mod/
MixPicker.cs). The mod sends event "mixpick" {"product", "carried": [ingredient names on the player],
"all": [every mixing ingredient in the game]}. Chat then votes ``!1`` ``!2`` ... for
``mixpick_vote_sec`` seconds; the winner shows on the station screen ("Chat picked Gasoline") and the
streamer puts it in. Nothing is put in for them, so a vote can't waste stock.

The vote itself is a MixVote from mixvote.py (the "chat names the new mix" vote) with no idea phase:
the options are the ingredients. That keeps one set of vote rules for both, and the board on the
overlays looks the same (only its id and title differ). Settings (plugin.json group "Chat picks the
ingredient"): mixpick_enabled, mixpick_vote_sec, mixpick_options (how many ingredients to vote on),
mixpick_from ("carried" = only ingredients the streamer has on them, falling back to all when they
carry none; "all" = any ingredient, for when the streamer will go and buy it), mixpick_auto_place (the
mod moves the winner from the streamer's inventory into the station's ingredient slot; sent as "place"
with state "done").

The state goes to the mod with POST /mixpick {"state", "ends_in", "options": [{"name", "votes"}],
"winner", "place", "msg"}; state names ("off", "vote", "done", "stopped") must match MixPicker.cs. Works for a
co-op guest too: each player picks for their own station.
"""

from __future__ import annotations

import random
import re
import time
from typing import Optional

from .bridge import BridgeError
from .feature import Feature
from .mixvote import MixVote
from .roster import person_key

BOARD_ID = "schedule1_mixpick"
BOARD_TITLE = "🧪 Pick the next ingredient"
BOARD_HOLD_SEC = 10            # the finished board stays on the overlays this long


def pick_options(carried: list[str], every: list[str], source: str, n: int, rand: random.Random) -> list[str]:
    """The ingredients chat votes on: from ``carried`` (or ``every`` when ``source`` is "all" or the
    streamer carries none), duplicates dropped, at most ``n`` picked at random, in a stable A-Z order
    so !1 !2 don't jump around."""
    pool = [str(x).strip() for x in (carried if source != "all" and carried else every) if str(x).strip()]
    seen: dict[str, str] = {}
    for x in pool:
        seen.setdefault(x.lower(), x)
    names = list(seen.values())
    if len(names) > n:
        names = rand.sample(names, n)
    return sorted(names, key=str.lower)


class MixPick(Feature):
    """One ingredient vote at a time; the mod's button starts and stops it."""

    def __init__(self, plugin):
        super().__init__(plugin)
        self.vote: Optional[MixVote] = None
        self.product = ""
        self._sent: Optional[dict] = None
        self._clear_at = 0.0
        self.rand = random.Random()

    async def handle_event(self, ev: dict) -> bool:
        kind = ev.get("type")
        if kind == "mixpick":
            await self.start(ev)
            return True
        if kind == "mixpick_stop":
            if self.vote is not None and self.vote.phase == "vote":
                self.vote.stop()
                await self.p._announce("🧪 The streamer stopped the ingredient vote.")
                await self.push(force=True)
            return True
        return False

    async def start(self, ev: dict) -> None:
        s = self.s()
        if not s.get("mixpick_enabled", True):
            await self.p.bridge.mixpick({"state": "off", "msg": "Chat picking is off in Stream Core "
                                                                "(Games > Schedule I > Settings)"})
            return
        if self.p.mix is not None and self.p.mix.phase in ("suggest", "vote"):
            await self.p.bridge.mixpick({"state": "off", "msg": "Chat is still naming a mix. Try again after that vote."})
            return
        opts = pick_options([str(x) for x in ev.get("carried") or []], [str(x) for x in ev.get("all") or []],
                            str(s.get("mixpick_from") or "carried"), int(self.num("mixpick_options", 6, 2)), self.rand)
        if len(opts) < 2:
            await self.p.bridge.mixpick({"state": "off", "msg": "Not enough ingredients to vote on. Carry a few, "
                                                                "or set 'Ingredients to vote on' to all."})
            return
        now = time.time()
        self.product = str(ev.get("product") or "")
        self.vote = MixVote(game_names=opts, taken=[], effects=[], value="", now=now, suggest_sec=0,
                            vote_sec=self.num("mixpick_vote_sec", 30, 5), options=len(opts), keep_game_name=False)
        self._sent = None
        p = self.p._prefix()
        what = f" for {self.product}" if self.product else ""
        await self.p._announce(f"🧪 Chat picks the next ingredient{what} ({round(self.vote.ends_at - now)} s): "
                               + " · ".join(f"{p}{i + 1} {o}" for i, o in enumerate(self.vote.options)))
        await self.push(force=True)

    async def on_chat(self, event) -> None:
        """"!2" / "!vote 2" while the vote is open (same rule as the name vote)."""
        v = self.vote
        if v is None or v.phase != "vote":
            return
        text = str(getattr(event, "message", "") or "").strip()
        m = re.fullmatch(re.escape(self.p._prefix()) + r"(?:vote\s+)?(\d)", text, flags=re.IGNORECASE)
        u = getattr(event, "user", None)
        if m and u is not None:
            plat = u.platform.value if hasattr(u.platform, "value") else str(u.platform)
            v.vote(person_key(plat, u.id, u.username), int(m.group(1)) - 1)

    def mod_state(self, now: float) -> dict:
        v = self.vote
        c = v.counts()
        return {"state": v.phase, "ends_in": max(0, round(v.ends_at - now)),
                "options": [{"name": o, "votes": c[i]} for i, o in enumerate(v.options)], "winner": v.winner,
                "place": bool(self.s().get("mixpick_auto_place", False))}

    def board(self) -> dict:
        b = self.vote.board(self.p._prefix())
        b["id"], b["title"] = BOARD_ID, BOARD_TITLE
        if self.vote.phase == "done":
            b["footer"] = f"Chat picked {self.vote.winner}"
        return b

    async def push(self, force: bool = False) -> None:
        """Send the vote's state to the mod and the overlays when it changed (or ``force``)."""
        v = self.vote
        now = time.time()
        state = self.mod_state(now)
        if force or state != self._sent:
            if self.p.ctx.broadcast is not None:
                await self.p.ctx.broadcast({"type": "board", "data": {**self.board(), "ts": now}})
            await self.p.bridge.mixpick(state)   # BridgeError: plugin.tick catches it, the next pass sends again
            self._sent = state
        if v.phase in ("done", "stopped"):
            self.vote = None
            self._clear_at = now + BOARD_HOLD_SEC

    async def tick(self) -> None:
        if self.vote is None:
            if self._clear_at and time.time() >= self._clear_at:
                self._clear_at = 0.0
                if self.p.ctx.broadcast is not None:
                    await self.p.ctx.broadcast({"type": "board_clear", "data": {"id": BOARD_ID}})
            return
        if self.vote.tick(time.time()) == "done":
            n = self.vote.winner_votes()
            await self.p._announce(f"🧪 Chat picked {self.vote.winner}" + (f" ({n} vote{'s' if n != 1 else ''})!" if n else
                                                                         " (nobody voted, first on the list)!"))
        try:
            await self.push()
        except BridgeError:
            pass                                  # the mod is away; the next pass tries again
