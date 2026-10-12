"""
Gamer Stonks: a points stock market for the stream (formerly Stream Core's built-in Fridge Market).

Tickers for the games you play, for you, and for chatters; prices that wander, follow Steam
player counts and react to game events; chat buys and sells with channel points and holders get
dividends when a game's vault flushes. Overlays: market.html, market-board.html,
market-chart.html, market-cycle.html (same addresses as before).

What lives where:
  tape.py      the tickers and prices (MarketTape)
  holdings.py  who owns which shares (this plugin's own database)
  plugin.py    start / stop, the price loop, chat commands, routes
  pages/       the Gamer Stonks page in the dashboard

Other plugins reach the tape with ctx.service("market") (put "after": ["market"] in their
plugin.json so it is running first). Games list their tickers with "market_books" and their
own settings with a "market" block in their plugin.json; the Gamer Stonks page shows both.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from typing import Any, Optional

from core.models import ExecuteRequest
from core.plugin_api import BasePlugin

from .holdings import Holdings
from .tape import MarketTape

log = logging.getLogger("plugins.stonks")

SPECIALS = ("market_buy", "market_sell", "market_tickers", "market_portfolio")
# Command names → what they do, for commands that don't carry a "special"
BY_NAME = {"buy": "market_buy", "sell": "market_sell", "tickers": "market_tickers", "portfolio": "market_portfolio"}


class GamerStonks(BasePlugin):
    name = "stonks"

    def __init__(self, config: dict, ctx=None):
        super().__init__(config, ctx)
        self.tape: Optional[MarketTape] = None
        self.holdings: Optional[Holdings] = None
        self._task: Optional[asyncio.Task] = None
        self._steam_poll_at = 0.0

    # ------------------------------------------------------------------
    # Life cycle
    # ------------------------------------------------------------------

    def _books(self) -> list[dict]:
        """Preview listings the installed games ask for (plugin.json "market_books")."""
        out: list[dict] = []
        plugins = self.ctx.plugins if self.ctx else None
        if plugins is None:
            return out
        for pid in plugins.ids():
            for row in (plugins.manifest(pid) or {}).get("market_books") or []:
                if isinstance(row, dict) and row.get("symbol"):
                    out.append({"book": f"game:{pid}", **row})
        return out

    async def start(self) -> None:
        ctx = self.ctx
        ctx.data_dir.mkdir(parents=True, exist_ok=True)
        listings = ctx.data_dir / "tickers.json"
        old = ctx.root / "data" / "market_tickers.json"     # where Stream Core kept them
        if not listings.exists() and old.is_file():
            shutil.copyfile(old, listings)
            log.info("Gamer Stonks: copied the tickers Stream Core had listed")
        self.tape = MarketTape(ctx.section, listings_path=listings, books=self._books())
        self.tape.enabled = True
        self.holdings = Holdings(ctx.db, ctx.store)
        await self.holdings.setup(getattr(ctx.store, "path", None))
        self._task = asyncio.create_task(self._loop(), name="gamer-stonks")
        log.info("Gamer Stonks started (%d tickers)", len(self.tape.snapshot(include_hidden=True)["instruments"]))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self.tape is not None:
            self.tape.save_listings()

    def apply_config(self, config: dict) -> None:
        if self.tape is not None:
            self.tape.configure(self.ctx.section)
            self.tape.enabled = True

    def service(self, name: str) -> Any:
        return self.tape if name == "market" else None

    async def _loop(self) -> None:
        """Walk the prices so overlay charts have a series; Steam and chatter listings follow."""
        while True:
            await asyncio.sleep(max(1.0, float(self.tape.tick_sec or 5)))
            try:
                self.tape.tick()
                now = time.time()
                if now - self._steam_poll_at >= float(self.tape.steam_poll_sec or 1800):
                    self._steam_poll_at = now
                    await self.tape.poll_steam()
                if self.ctx.store is not None:
                    await self.tape.tick_chatter(self.ctx.store)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Gamer Stonks tick failed")

    def status(self) -> dict:
        if self.tape is None:
            return {}
        snap = self.tape.snapshot()
        return {"detail": f"{len(snap['instruments'])} tickers listed"}

    # ------------------------------------------------------------------
    # Chat commands (!buy / !sell / !tickers / !portfolio)
    # ------------------------------------------------------------------

    async def execute(self, req: ExecuteRequest) -> dict:
        special = (req.special or BY_NAME.get(req.command_name) or "").lower()
        if special not in SPECIALS:
            return {"success": False, "error": f"Gamer Stonks has no command {req.command_name}"}
        text = await self.trade(req, special)
        return {"success": True, "reply": text}

    async def trade(self, req: ExecuteRequest, special: str) -> str:
        tape, store, hold = self.tape, self.ctx.store, self.holdings
        user = req.user
        name = (user.username if user else "") or "someone"
        if special == "market_tickers":
            bits = [f"{it['symbol']} {it['price']:.2f}" for it in tape.snapshot()["instruments"][:8]]
            return "Tickers: " + (", ".join(bits) if bits else "none listed")
        if store is None or user is None:
            return "Gamer Stonks can't reach points right now."
        uid = await store.get_or_create_user(req.platform.value, user.id, user.username, user.display_name)
        if special == "market_portfolio":
            holds = await hold.for_user(uid)
            if not holds:
                return f"@{name}: no shares yet. Try !buy FRG 20"
            bits = []
            for h in holds:
                px = (tape.quote(h["symbol"]) or {}).get("price", 0)
                bits.append(f"{h['symbol']} {h['milli_shares'] / 1000:.2f}sh @ {float(px):.2f}")
            return f"@{name}: " + ", ".join(bits)
        parts = (req.original_message or "").split()
        if len(parts) < 2:
            return "Usage: !buy SYMBOL POINTS   or   !sell SYMBOL QTY|all"
        symbol = parts[1].upper()
        inst = tape.quote(symbol)
        if not inst or inst.get("status") != "listed":
            return f"{symbol} is not listed (or is hidden)."
        price = float(inst.get("price") or 0) or 1.0
        if special == "market_buy":
            if len(parts) < 3:
                return "Usage: !buy SYMBOL POINTS"
            try:
                spend = int(float(parts[2]))
            except ValueError:
                return "Points must be a number."
            if spend <= 0:
                return "Spend at least 1 point."
            # check-and-take in one step, so two quick !buy can't go below zero
            bought, bal = await store.spend_points(uid, spend, 1, f"buy {symbol}", "market")
            if not bought:
                return f"@{name}: need {spend} points, have {bal}."
            shares = spend / price
            nxt = await hold.adjust(uid, symbol, int(round(shares * 1000)))
            tape.apply_trade_impact(symbol, spend, side="buy")
            return f"@{name}: bought {shares:.3f} {symbol} @ {price:.2f} ({nxt / 1000:.3f} sh)"
        raw = parts[2] if len(parts) > 2 else "all"
        have = {h["symbol"]: h["milli_shares"] for h in await hold.for_user(uid)}.get(symbol, 0)
        if have <= 0:
            return f"@{name}: no {symbol} shares."
        if raw.lower() == "all":
            sell_milli = have
        else:
            try:
                sell_milli = int(round(float(raw) * 1000))
            except ValueError:
                return "Qty must be a number or all."
        sell_milli = max(0, min(have, sell_milli))
        credit = int(round((sell_milli / 1000.0) * price))
        await hold.adjust(uid, symbol, -sell_milli)
        if credit:
            await store.adjust_points(uid, credit, f"sell {symbol}", "market")
        tape.apply_trade_impact(symbol, credit, side="sell")
        return f"@{name}: sold {sell_milli / 1000:.3f} {symbol} for {credit} pts"

    # ------------------------------------------------------------------
    # Game hooks (signals and dividends from bridges)
    # ------------------------------------------------------------------

    def signal(self, payload: dict) -> dict:
        cfg = self.ctx.section
        tape = self.tape
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("name required")
        symbol = payload.get("symbol")
        book = payload.get("book") or payload.get("game")
        cooldown = payload.get("cooldown_sec")
        if cooldown is None:
            cooldown = cfg.get("death_cooldown_sec", 20) if name == "player_death" else cfg.get("signal_cooldown_sec", 15)
        scope = str(payload.get("scope") or cfg.get("signal_cooldown_scope") or "symbol")
        gate = tape.try_signal(name=name, symbol=symbol, cooldown_sec=cooldown, book=book, scope=scope)
        if not gate.get("ok"):
            return {**gate, "applied": False}
        frac = payload.get("pct")
        if frac is None and name == "player_death":
            frac = float(cfg.get("death_return", -0.08) or -0.08)
        elif frac is not None:
            frac = float(frac) / 100.0 if abs(float(frac)) > 1 else float(frac)
        applied = None
        if frac is not None and symbol:
            applied = tape.apply_return(str(symbol), float(frac), reason=name)
        return {**gate, "applied": bool(applied), "instrument": applied, "last_event": tape.last_event}

    async def dividend(self, body: dict) -> dict:
        """A game's vault flushed: work x points_per_unit becomes points for the symbol's holders."""
        cfg = self.ctx.section
        tape = self.tape
        symbol = str(body.get("symbol") or "").upper().strip()
        # Older Factorio bridges send no game name; the plugin that owns the book fills the gaps
        game = str(body.get("game") or body.get("book") or "factorio").strip()
        if game.startswith("game:"):
            game = game[5:]
        hints: dict = {}
        hook = self.ctx.plugins.class_hook(game, "dividend_defaults") if self.ctx.plugins else None
        if hook is not None:
            try:
                hints = hook(body, cfg) or {}
            except Exception:
                log.exception("Plugin %s dividend_defaults failed", game)
        if not symbol:
            symbol = str(hints.get("symbol") or "").upper().strip()
            if not symbol:
                raise ValueError("symbol required")
        work = float(body.get("work") or 0)
        unit = str(body.get("unit") or "mj").lower()
        reason = str(body.get("reason") or "vault")
        rates = cfg.get("points_per_unit") or {}
        if isinstance(hints.get("rates"), dict):
            rates = hints["rates"]
        per = body.get("points")
        if per is None:
            default_rate = 0.02 if unit in ("mj", "joule", "j") else 1.0
            per = work * float(rates.get(unit, rates.get("mj" if unit == "joule" else unit, default_rate)))
        points = min(int(max(0, round(float(per)))), int(cfg.get("hourly_cap_points") or 500))
        paid = {"holders": 0, "paid": [], "burned": points, "total": points}
        if points > 0:
            paid = await self.holdings.pay_dividend(symbol, points, f"{reason}:{unit}")
        bump = float(cfg.get("dividend_price_bump", 0.01) or 0)
        applied = tape.apply_return(symbol, bump, reason=f"dividend:{reason}") if bump else None
        event = {"ts": time.time(), "symbol": symbol, "game": game, "unit": unit, "work": work, "points": points,
                 "holders": paid.get("holders", 0), "burned": paid.get("burned", points), "reason": reason}
        tape.last_dividend = event
        tape.last_event = {"ts": event["ts"], "symbol": symbol, "reason": f"dividend {points} pts",
                           "pct": round(bump * 100.0, 2)}
        return {"ok": True, "dividend": event, "instrument": applied, "payout": paid}

    # ------------------------------------------------------------------
    # Routes (same addresses Stream Core used, so overlays and bridges keep working)
    # ------------------------------------------------------------------

    @classmethod
    def routes(cls, router, get_running):
        from .routes import add_routes
        add_routes(router, get_running)
