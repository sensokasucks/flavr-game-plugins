"""
Sumotori Dreams plugin: chat builds the arena and bets on who wins.

Sumotori Dreams Classic (Steam 1604240) has no mod loader, log or API. What it does have is
arena script files (.smo) that it reloads by itself whenever the file changes (arena.py has the
details). So this plugin needs no game-side mod at all:

  - Arena: chatters buy pieces with points (!arena crate, !arena wall ...). Each piece lands on a
    random spot. With the ``apply`` setting on "next_round" (default) pieces wait for the next
    arena, which the streamer starts with "Next arena" on the plugin page (or which starts by
    itself when a round result is set, ``new_arena_after_result``). With "now" the file is
    rewritten at once. In the game the streamer loads the file once: Select Arena > Load Mod.
  - Bets: the streamer opens a round, chat types !bet red 100, bets close after
    ``bet_window_sec`` (or when the streamer locks them), then the streamer presses who won.
    The game can't tell us, so the result always comes from the page (or anything calling
    POST /api/sumotori/round). Payout maths is in bets.py.
  - Scoreboard: wins per side and the current streak since the streamer last pressed
    "Reset score", for the overlay (overlay/sumotori.html polls GET /api/sumotori/state) and !score.

Settings live under ``sumotori:`` in config.yaml (defaults in plugin.json). Chat commands are in
commands.json; they all reach execute(). Data (pieces bought, rounds, bets) is in the plugin's own
database, data/plugins/sumotori/sumotori.db, so a Core restart keeps an open round's bets.

Plan and research notes: /mnt/project-files/sumotori/SUMOTORI_PLUGIN_IDEAS.md in the project.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any, Optional

from core.models import ExecuteRequest, Platform
from core.plugin_api import BasePlugin

from . import arena
from .bets import SIDES, parse_amount, parse_side, payouts, streak

log = logging.getLogger("plugins.sumotori")

TICK_SEC = 1.0                # how often the loop checks whether open bets should close
SOURCE = "sumotori"           # points ledger "source" for everything this plugin spends or pays

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS pieces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arena_no INTEGER NOT NULL,          -- the arena this piece is (or will be) in; kv "arena_no" = now
    piece TEXT NOT NULL,                -- a key of arena.PIECES
    x REAL NOT NULL, z REAL NOT NULL,   -- spot on the floor (arena.pick_spot)
    uid INTEGER, user_key TEXT, who TEXT, platform TEXT,
    cost INTEGER NOT NULL DEFAULT 0,    -- points paid (refunded when the streamer clears the queue)
    status TEXT NOT NULL DEFAULT 'live',  -- live | refunded
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL,                -- open | locked | settled | cancelled
    opened_at REAL NOT NULL,
    locks_at REAL,                      -- time.time() when bets close by themselves (NULL = streamer locks)
    settled_at REAL,
    winner TEXT                         -- "a" / "b" once settled
);
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    uid INTEGER, user_key TEXT NOT NULL, who TEXT, platform TEXT,
    side TEXT NOT NULL,                 -- "a" / "b"
    amount INTEGER NOT NULL,
    paid INTEGER NOT NULL DEFAULT 0,    -- points handed back at settle / cancel
    created_at REAL NOT NULL
);
"""


def user_key(platform: str, user_id: str, username: str) -> str:
    """One chatter on one platform: "twitch:123" (or "kick:zack" when there's no id)."""
    return f"{platform}:{user_id or (username or '').lower().lstrip('@')}"


def plat_of(req: ExecuteRequest) -> str:
    return req.platform.value if hasattr(req.platform, "value") else str(req.platform)


def shown_name(user) -> str:
    return (getattr(user, "display_name", "") or getattr(user, "username", "") or "someone").strip()


class SumotoriDreams(BasePlugin):
    """Core side of Sumotori Dreams: arena file writer, bets, scoreboard."""

    name = "sumotori"

    def __init__(self, config: dict, ctx=None):
        super().__init__(config, ctx)
        self.db = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()          # one change to rounds / pieces at a time
        self._cooldown: dict[str, float] = {}   # user_key -> time.monotonic() when they may buy again
        self.rng = random.Random()
        self.last_write = 0.0                # time.time() of the last arena file write
        self.last_error = ""

    # ------------------------------------------------------------------ settings

    def _s(self) -> dict:
        """This plugin's live config block (``sumotori:``)."""
        return (self.config or {}).get("sumotori") or {}

    def _num(self, key: str, default: float, lo: float = 0) -> float:
        try:
            return max(lo, float(self._s().get(key, default)))
        except (TypeError, ValueError):
            return default

    def side_name(self, side: str) -> str:
        """ "a" -> the ``side_a`` setting ("Red" by default), "b" -> ``side_b``."""
        key, default = ("side_a", "Red") if side == "a" else ("side_b", "Blue")
        return str(self._s().get(key) or default).strip() or default

    def prices(self) -> dict[str, int]:
        """Piece -> price in points from the ``prices`` setting; pieces at 0 (or unknown) are left out."""
        out = {}
        for k, v in (self._s().get("prices") or {}).items():
            try:
                price = int(float(v))
            except (TypeError, ValueError):
                continue
            if k in arena.PIECES and price > 0:
                out[k] = price
        return out

    def smo_opts(self) -> dict:
        """Numbers the .smo snippets need (arena.py docstring)."""
        return {"tex": self._num("texture", 0, -1000), "fixed": self._num("fixed_flag", 1, -1000),
                "loose": self._num("loose_flag", 0, -1000), "brk": self._num("break_strength", 1, -1000),
                "floor_y": self._num("floor_y", -7, -1000)}

    def arena_path(self) -> Path:
        """Where the arena file goes: the ``arena_file`` setting (a folder gets stream.smo inside it),
        else data/plugins/sumotori/stream.smo next to Core."""
        raw = str(self._s().get("arena_file") or "").strip().strip('"')
        if raw:
            p = Path(raw).expanduser()
            return p / "stream.smo" if (p.is_dir() or raw.endswith(("/", "\\"))) else p
        return Path(self.ctx.data_dir) / "stream.smo"

    def _prefix(self) -> str:
        return str(((self.config or {}).get("core") or {}).get("command_prefix") or "!")

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Open the database, write the current arena so the file exists, start the loop.
        Core calls this when the plugin is enabled."""
        self.enabled = bool(self._s().get("enabled"))
        self.db = self.ctx.db
        await self.db.script(SCHEMA)
        await self.rewrite()
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="sumotori")
        log.info("Sumotori Dreams started (arena file %s)", self.arena_path())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Sumotori loop")
            await asyncio.sleep(TICK_SEC)

    async def tick(self, now: Optional[float] = None) -> None:
        """Close open bets whose time is up (``bet_window_sec``)."""
        now = time.time() if now is None else now
        rnd = await self.current_round()
        if rnd and rnd["state"] == "open" and rnd["locks_at"] and now >= rnd["locks_at"]:
            await self.lock_round()

    # ------------------------------------------------------------------ small db helpers

    async def _kv(self, key: str, default: str = "") -> str:
        row = await self.db.fetchone("SELECT value FROM kv WHERE key = ?", (key,))
        return row["value"] if row else default

    async def _set_kv(self, key: str, value: Any) -> None:
        await self.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    async def arena_no(self) -> int:
        """The arena in the game now (counts up with every "Next arena")."""
        return int(await self._kv("arena_no", "1") or 1)

    async def _pieces(self, arena_no: int) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM pieces WHERE arena_no = ? AND status = 'live' ORDER BY id",
                                      (arena_no,))

    async def current_round(self) -> Optional[dict]:
        """The newest round that isn't settled or cancelled, or None."""
        return await self.db.fetchone("SELECT * FROM rounds WHERE state IN ('open', 'locked') ORDER BY id DESC LIMIT 1")

    # ------------------------------------------------------------------ chat

    async def _say(self, platform: str, text: str) -> None:
        try:
            plat = Platform(str(platform).lower())
        except ValueError:
            return
        await self.ctx.reply(plat, text)

    async def _announce(self, text: str) -> None:
        """Say ``text`` in every chat Core is set to read (twitch / kick / youtube with enabled on)."""
        if not self._s().get("announce", True):
            return
        cfg = self.config or {}
        for p in Platform:
            if (cfg.get(p.value) or {}).get("enabled"):
                await self.ctx.reply(p, text)

    async def execute(self, req: ExecuteRequest) -> dict:
        """Core calls this for this plugin's chat commands (commands.json): !arena, !bet, !score."""
        name = (req.command_name or "").lower()
        if req.user is None:
            return {"success": False, "error": "no chatter"}
        if name == "arena":
            return await self.buy_piece(req)
        if name == "bet":
            return await self.place_bet(req)
        if name == "score":
            return {"success": True, "reply": await self.score_line()}
        return {"success": False, "error": f"unknown command {name}"}

    async def _uid(self, req: ExecuteRequest) -> Optional[int]:
        store = getattr(self.ctx, "store", None)
        if store is None:
            return None
        u = req.user
        return await store.get_or_create_user(plat_of(req), u.id, u.username, u.display_name)

    async def _balance(self, uid: int) -> int:
        user = await self.ctx.store.get_user(uid)
        return int((user or {}).get("points") or 0)

    async def _refund(self, uid: Optional[int], points: int, reason: str) -> None:
        if uid and points > 0 and getattr(self.ctx, "store", None) is not None:
            await self.ctx.store.adjust_points(uid, int(points), reason, SOURCE)

    # ------------------------------------------------------------------ arena

    def _apply_now(self) -> bool:
        return str(self._s().get("apply") or "next_round") == "now"

    async def buy_piece(self, req: ExecuteRequest) -> dict:
        """!arena <piece>: pay its price, the piece goes in the next arena (or this one with apply = now).
        !arena alone lists what's for sale. Limits: ``max_pieces`` per arena, ``per_user_max`` per
        chatter per arena, ``piece_cooldown_sec`` per chatter."""
        s, u = self._s(), req.user
        who, plat = shown_name(u), plat_of(req)
        p = self._prefix()
        if not s.get("pieces_enabled", True):
            return {"success": True, "reply": "Building the arena is switched off right now."}
        prices = self.prices()
        if not prices:
            return {"success": True, "reply": "Nothing is for sale for the arena right now."}
        want = (req.args[0].lower().lstrip("!") if req.args else "")
        if want not in prices:
            menu = ", ".join(f"{k} {v}" for k, v in sorted(prices.items(), key=lambda kv: kv[1]))
            pre = f"@{who} there's no '{want}'. " if want else ""
            return {"success": True, "reply": f"{pre}Arena pieces ({p}arena <piece>): {menu} points."}
        key = user_key(plat, u.id, u.username)
        wait = self._cooldown.get(key, 0) - time.monotonic()
        if wait > 0:
            return {"success": True, "reply": f"@{who} you can add another piece in {int(wait) + 1}s."}
        async with self._lock:
            target = await self.arena_no() + (0 if self._apply_now() else 1)
            pieces = await self._pieces(target)
            max_pieces = int(self._num("max_pieces", 8, 1))
            if len(pieces) >= max_pieces:
                return {"success": True, "reply": f"@{who} the arena is full ({max_pieces} pieces). Wait for the next one."}
            per_user = int(self._num("per_user_max", 2, 0))
            if per_user and sum(1 for x in pieces if x["user_key"] == key) >= per_user:
                return {"success": True, "reply": f"@{who} you already have {per_user} pieces in this arena."}
            cost = prices[want]
            uid = await self._uid(req)
            if uid is None:
                return {"success": False, "error": "points are not available"}
            paid, balance = await self.ctx.store.spend_points(uid, cost, 1, f"!arena {want} (Sumotori Dreams)", SOURCE)
            if not paid:
                return {"success": True, "reply": f"@{who} {arena.PIECES[want][0]} costs {cost} points, you have {balance}."}
            x, z = arena.pick_spot(self.rng, self._num("arena_half", 9, 1.5))
            await self.db.execute(
                "INSERT INTO pieces (arena_no, piece, x, z, uid, user_key, who, platform, cost, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (target, want, x, z, uid, key, who, plat, cost, time.time()))
            self._cooldown[key] = time.monotonic() + self._num("piece_cooldown_sec", 30)
            if self._apply_now():
                await self.rewrite()
        when = "It's in the arena now!" if self._apply_now() else "It goes in the next arena."
        self.ctx.activity(f"{who} bought {arena.PIECES[want][0]} for the arena")
        return {"success": True, "reply": f"@{who} bought {arena.PIECES[want][0]} for {cost} points. {when}"}

    async def rewrite(self) -> bool:
        """Write the arena file for the current arena (base + its pieces). The game reloads it by itself.
        Returns False (and keeps the reason in last_error) when the file can't be read or written."""
        opts = self.smo_opts()
        base = None
        base_file = str(self._s().get("base_file") or "").strip().strip('"')
        try:
            if base_file:
                base = Path(base_file).expanduser().read_text(encoding="utf-8", errors="replace")
            pieces = await self._pieces(await self.arena_no())
            arena.write_smo(self.arena_path(), arena.build_smo(base, pieces, opts))
        except OSError as exc:
            self.last_error = f"Couldn't write the arena file: {exc}"
            log.warning("Sumotori: %s", self.last_error)
            self.ctx.activity(self.last_error, "error")
            return False
        self.last_write = time.time()
        self.last_error = ""
        return True

    async def next_arena(self) -> dict:
        """Start the next arena: everything chat queued goes in, last arena's pieces go away.
        Called by the page's "Next arena" button and, with ``new_arena_after_result``, by settle_round()."""
        async with self._lock:
            no = await self.arena_no() + 1
            await self._set_kv("arena_no", no)
            pieces = await self._pieces(no)
            ok = await self.rewrite()
        if pieces:
            names = ", ".join(f"{arena.PIECES[x['piece']][0]} from {x['who']}" for x in pieces[:5])
            more = f" and {len(pieces) - 5} more" if len(pieces) > 5 else ""
            await self._announce(f"New Sumotori arena: {names}{more}.")
        return {"ok": ok, "arena_no": no, "pieces": len(pieces), "error": self.last_error}

    async def clear_queue(self) -> dict:
        """Take every piece out of the next arena (with apply = now: out of this one too, and rewrite).
        Buyers get their points back when ``refund_on_clear`` is on."""
        refund = bool(self._s().get("refund_on_clear", True))
        async with self._lock:
            cur = await self.arena_no()
            first = cur if self._apply_now() else cur + 1
            rows = await self.db.fetchall("SELECT * FROM pieces WHERE arena_no >= ? AND status = 'live'", (first,))
            await self.db.execute("UPDATE pieces SET status = 'refunded' WHERE arena_no >= ? AND status = 'live'", (first,))
            if refund:
                for r in rows:
                    await self._refund(r["uid"], r["cost"], f"!arena {r['piece']} refund (Sumotori Dreams)")
            if self._apply_now():
                await self.rewrite()
        return {"ok": True, "cleared": len(rows), "refunded": refund}

    # ------------------------------------------------------------------ bets

    async def open_round(self) -> dict:
        """Open bets for a new round. Refused while one is still open or locked (settle or cancel it first)."""
        if not self._s().get("bets_enabled", True):
            return {"ok": False, "error": "Bets are switched off in the settings."}
        async with self._lock:
            if await self.current_round():
                return {"ok": False, "error": "A round is still running. Pick a winner or cancel it first."}
            window = self._num("bet_window_sec", 60)
            now = time.time()
            rid = await self.db.execute("INSERT INTO rounds (state, opened_at, locks_at) VALUES ('open', ?, ?)",
                                        (now, now + window if window > 0 else None))
        a, b = self.side_name("a"), self.side_name("b")
        p = self._prefix()
        secs = f" You have {int(window)}s." if window > 0 else ""
        await self._announce(f"Bets are open! {p}bet {a.lower()} <points> or {p}bet {b.lower()} <points>.{secs}")
        return {"ok": True, "round": rid}

    async def lock_round(self) -> dict:
        """No more bets for the round running now (the timer does this too)."""
        async with self._lock:
            rnd = await self.current_round()
            if not rnd or rnd["state"] != "open":
                return {"ok": False, "error": "No open bets to close."}
            await self.db.execute("UPDATE rounds SET state = 'locked' WHERE id = ?", (rnd["id"],))
            pools = await self._pools(rnd["id"])
        a, b = self.side_name("a"), self.side_name("b")
        await self._announce(f"Bets are closed: {a} {pools['a']:,} points, {b} {pools['b']:,} points.")
        return {"ok": True}

    async def place_bet(self, req: ExecuteRequest) -> dict:
        """!bet <side> <points>: while bets are open. One side per chatter per round; betting again on
        the same side adds to it. ``bet_min`` / ``bet_max`` (0 = no limit) are per chatter per round."""
        u = req.user
        who, plat = shown_name(u), plat_of(req)
        a, b = self.side_name("a"), self.side_name("b")
        p = self._prefix()
        usage = f"@{who} type {p}bet {a.lower()} <points> or {p}bet {b.lower()} <points>"
        if not self._s().get("bets_enabled", True):
            return {"success": True, "reply": "Bets are switched off right now."}
        if len(req.args) < 2:
            return {"success": True, "reply": usage + "."}
        # "!bet 100 red" works too: whichever word is a side
        side = parse_side(req.args[0], a, b)
        amount_word = req.args[1]
        if side is None:
            side, amount_word = parse_side(req.args[1], a, b), req.args[0]
        if side is None:
            return {"success": True, "reply": usage + "."}
        key = user_key(plat, u.id, u.username)
        async with self._lock:
            rnd = await self.current_round()
            if not rnd or rnd["state"] != "open":
                return {"success": True, "reply": f"@{who} bets aren't open right now."}
            mine = await self.db.fetchall("SELECT side, amount FROM bets WHERE round_id = ? AND user_key = ?",
                                          (rnd["id"], key))
            if mine and mine[0]["side"] != side:
                return {"success": True, "reply": f"@{who} you already bet on {self.side_name(mine[0]['side'])}."}
            uid = await self._uid(req)
            if uid is None:
                return {"success": False, "error": "points are not available"}
            balance = await self._balance(uid)
            amount = parse_amount(amount_word, balance)
            if amount is None:
                return {"success": True, "reply": usage + "."}
            already = sum(int(m["amount"]) for m in mine)
            lo, hi = int(self._num("bet_min", 10)), int(self._num("bet_max", 0))
            if hi and already + amount > hi:
                amount = hi - already
                if amount <= 0:
                    return {"success": True, "reply": f"@{who} the most you can bet in a round is {hi:,}."}
            if already + amount < lo:
                return {"success": True, "reply": f"@{who} the smallest bet is {lo:,} points."}
            paid, balance = await self.ctx.store.spend_points(uid, amount, 1, f"!bet {self.side_name(side)} (Sumotori Dreams)", SOURCE)
            if not paid:
                return {"success": True, "reply": f"@{who} you have {balance:,} points."}
            await self.db.execute(
                "INSERT INTO bets (round_id, uid, user_key, who, platform, side, amount, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (rnd["id"], uid, key, who, plat, side, amount, time.time()))
        total = already + amount
        return {"success": True, "reply": f"@{who} {total:,} points on {self.side_name(side)}."}

    async def _pools(self, round_id: int) -> dict:
        rows = await self.db.fetchall("SELECT side, SUM(amount) AS pts, COUNT(DISTINCT user_key) AS n "
                                      "FROM bets WHERE round_id = ? GROUP BY side", (round_id,))
        out = {"a": 0, "b": 0, "a_n": 0, "b_n": 0}
        for r in rows:
            if r["side"] in SIDES:
                out[r["side"]] = int(r["pts"] or 0)
                out[r["side"] + "_n"] = int(r["n"] or 0)
        return out

    async def settle_round(self, winner: str) -> dict:
        """The streamer says who won ("a" / "b"). Pays the bets (bets.payouts), counts the win for the
        scoreboard, then (settings) starts the next arena and opens the next round's bets.
        Works without any bets too, as a plain scoreboard button."""
        if winner not in SIDES:
            return {"ok": False, "error": "winner must be a or b"}
        style = "double" if str(self._s().get("payout") or "pool") == "double" else "pool"
        async with self._lock:
            rnd = await self.current_round()
            now = time.time()
            if rnd is None:          # no bets running: still count it on the scoreboard
                rid = await self.db.execute("INSERT INTO rounds (state, opened_at, settled_at, winner) "
                                            "VALUES ('settled', ?, ?, ?)", (now, now, winner))
                bets = []
            else:
                rid = rnd["id"]
                bets = await self.db.fetchall("SELECT * FROM bets WHERE round_id = ?", (rid,))
                await self.db.execute("UPDATE rounds SET state = 'settled', settled_at = ?, winner = ? WHERE id = ?",
                                      (now, winner, rid))
            pay, refunded = payouts(bets, winner, style)
            by_id = {int(b_["id"]): b_ for b_ in bets}
            for bid, pts in pay.items():
                bet = by_id[bid]
                await self.db.execute("UPDATE bets SET paid = ? WHERE id = ?", (pts, bid))
                why = "refund, no contest" if refunded else f"won on {self.side_name(winner)}"
                await self._refund(bet["uid"], pts, f"!bet {why} (Sumotori Dreams)")
        # chat line: who won, and the biggest winners (profit per chatter, not per bet row)
        name = self.side_name(winner)
        if not bets:
            line = f"{name} wins!"
        elif refunded:
            line = f"{name} wins! Only one side had bets, so everyone got their points back."
        else:
            profit: dict[str, int] = {}
            for bet in bets:
                profit[bet["who"]] = profit.get(bet["who"], 0) + pay.get(int(bet["id"]), 0) - int(bet["amount"])
            winners = sorted(((w, pts) for w, pts in profit.items() if pts > 0), key=lambda t: -t[1])
            top = ", ".join(f"{w} +{pts:,}" for w, pts in winners[:3])
            paid = sum(pay.values())
            line = f"{name} wins! {paid:,} points paid out." + (f" Top: {top}." if top else " Nobody backed them.")
        await self._announce(line)
        self.ctx.activity(f"Round result: {name} won")
        if self._s().get("new_arena_after_result", True) and not self._apply_now():
            await self.next_arena()
        if self._s().get("auto_open", False) and self._s().get("bets_enabled", True):
            await self.open_round()
        return {"ok": True, "round": rid, "paid": sum(pay.values()), "refunded": refunded}

    async def cancel_round(self) -> dict:
        """Call the round off: every bet's points go back. Nothing is counted on the scoreboard."""
        async with self._lock:
            rnd = await self.current_round()
            if not rnd:
                return {"ok": False, "error": "No round running."}
            bets = await self.db.fetchall("SELECT * FROM bets WHERE round_id = ?", (rnd["id"],))
            await self.db.execute("UPDATE rounds SET state = 'cancelled', settled_at = ? WHERE id = ?",
                                  (time.time(), rnd["id"]))
            for bet in bets:
                await self.db.execute("UPDATE bets SET paid = amount WHERE id = ?", (bet["id"],))
                await self._refund(bet["uid"], bet["amount"], "!bet refund, round called off (Sumotori Dreams)")
        if bets:
            await self._announce("Round called off. Everyone got their points back.")
        return {"ok": True, "refunded": len(bets)}

    # ------------------------------------------------------------------ scoreboard

    async def reset_score(self) -> dict:
        """Start counting wins from zero (rounds before now stay in the database)."""
        await self._set_kv("score_since", time.time())
        return {"ok": True}

    async def score(self) -> dict:
        """Wins per side and the current streak since the last "Reset score"."""
        since = float(await self._kv("score_since", "0") or 0)
        rows = await self.db.fetchall("SELECT winner FROM rounds WHERE state = 'settled' AND settled_at >= ? "
                                      "ORDER BY settled_at, id", (since,))
        winners = [r["winner"] for r in rows if r["winner"] in SIDES]
        side, run = streak(winners)
        return {"a": winners.count("a"), "b": winners.count("b"), "rounds": len(winners),
                "streak_side": side, "streak": run, "last": winners[-10:]}

    async def score_line(self) -> str:
        sc = await self.score()
        a, b = self.side_name("a"), self.side_name("b")
        line = f"Sumotori score: {a} {sc['a']} - {sc['b']} {b}."
        if sc["streak"] >= 2:
            line += f" {self.side_name(sc['streak_side'])} has won {sc['streak']} in a row."
        return line

    # ------------------------------------------------------------------ for the page and overlay

    async def state(self, admin: bool = False) -> dict:
        """What the overlay (public) and the plugin page (admin) show. GET /api/sumotori/state and
        /api/sumotori/admin in routes.py. The public part only holds what chat already sees."""
        no = await self.arena_no()
        upcoming = no if self._apply_now() else no + 1
        rnd = await self.current_round()
        out: dict[str, Any] = {
            "sides": {"a": self.side_name("a"), "b": self.side_name("b")},
            "score": await self.score(),
            "arena_no": no,
            "apply": "now" if self._apply_now() else "next_round",
            "arena": [{"piece": x["piece"], "name": arena.PIECES.get(x["piece"], (x["piece"],))[0], "who": x["who"]}
                      for x in await self._pieces(no)],
            "queue": [{"piece": x["piece"], "name": arena.PIECES.get(x["piece"], (x["piece"],))[0], "who": x["who"]}
                      for x in (await self._pieces(upcoming) if upcoming != no else [])],
            "round": None,
            "now": time.time(),
        }
        if rnd:
            bets = await self.db.fetchall("SELECT who, side, SUM(amount) AS amount FROM bets WHERE round_id = ? "
                                          "GROUP BY user_key, side ORDER BY amount DESC", (rnd["id"],))
            out["round"] = {"id": rnd["id"], "state": rnd["state"], "locks_at": rnd["locks_at"],
                            "pools": await self._pools(rnd["id"]),
                            "top": [{"who": r["who"], "side": r["side"], "amount": int(r["amount"])} for r in bets[:5]]}
        if admin:
            out.update({"arena_file": str(self.arena_path()), "last_write": self.last_write,
                        "error": self.last_error, "prices": self.prices(),
                        "bets_enabled": bool(self._s().get("bets_enabled", True)),
                        "pieces_enabled": bool(self._s().get("pieces_enabled", True))})
            try:
                out["file_text"] = self.arena_path().read_text(encoding="ascii", errors="replace")[:20000]
            except OSError:
                out["file_text"] = ""
        return out

    def status(self) -> dict:
        """Extra fields on Core's Status page."""
        return {"detail": f"arena file {self.arena_path()}", "error": self.last_error}

    def overlay_catalog(self) -> list[dict]:
        """The scoreboard overlay on Core (:3850), for Overlay links."""
        base = (self.ctx.core_url() if self.ctx else "http://127.0.0.1:3850") + "/overlay"
        return [{"name": "Sumotori scoreboard", "url": f"{base}/sumotori.html",
                 "notes": "Score, streak, open bets and the next arena's pieces. Transparent Browser source."}]

    @classmethod
    def routes(cls, router, get_running):
        from .routes import add_routes
        add_routes(router, get_running)
