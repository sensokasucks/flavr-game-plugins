"""
Gamer Stonks tape: the tickers, their prices and history, Steam player counts, chatter
listings and the signal cooldowns. The plugin (plugin.py) owns one tape; overlays read it
through /api/market/state and /api/market/history.

Moved here from Stream Core's core/market.py (2026-10). Behaviour is unchanged.

An instrument (ticker) is a plain dict keyed by symbol: symbol, name, book ("core" or
"game:<plugin id>"), role ("streamer" sorts first), status (listed / hidden / delisted),
feed (walk / steam / chatter), price, open, high, low, base_price, min_price, max_price,
plus steam_* and chatter_* fields. Only the listing fields (listing_records) are saved
to data/plugins/stonks/tickers.json; live prices and history are in memory only.

Price units are display numbers (1 share at price 10 costs 10 points). Fractions passed
to apply_return are relative moves: 0.05 = +5 %. "bps" = basis points (1 bp = 0.01 %).
Other plugins get this object through ctx.service("market"); keep method names stable.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("plugins.stonks.tape")


def _clean_symbol(raw: str) -> str:
    """Uppercase, keep A-Z / 0-9 / dot, max 8 characters ("minecraft" -> "MINECRAF")."""
    sym = "".join(ch for ch in str(raw or "").upper() if ch.isalnum() or ch == ".")
    return sym[:8]

# Steam Web API: current player count for one App ID (no API key needed).
STEAM_CCU_URL = (
    "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
)


def _now() -> float:
    return time.time()


class CooldownGate:
    """
    Optional per-key cooldown.

    Keys are tuples like ("rule:streamer-death", "FACT") or
    ("signal:player_death", "book:factorio"). cooldown_sec <= 0 means
    "no cooldown" (always allowed).
    """

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    @staticmethod
    def key(*parts: Any) -> str:
        return "|".join(str(p) for p in parts if p is not None and str(p) != "")

    def remaining(self, key: str, cooldown_sec: float | None) -> float:
        cd = float(cooldown_sec or 0)
        if cd <= 0:
            return 0.0
        last = self._last.get(key, 0.0)
        left = cd - (_now() - last)
        return left if left > 0 else 0.0

    def allow(self, key: str, cooldown_sec: float | None) -> bool:
        return self.remaining(key, cooldown_sec) <= 0

    def touch(self, key: str) -> None:
        self._last[key] = _now()

    def try_acquire(self, key: str, cooldown_sec: float | None) -> bool:
        """Allowed? Then start the cooldown now. Returns whether it was allowed."""
        if not self.allow(key, cooldown_sec):
            return False
        self.touch(key)
        return True

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._last.clear()
        else:
            self._last.pop(key, None)


def _walk(price: float, *, noise_bps: float, revert: float, base: float,
          lo: float, hi: float) -> float:
    """One random-walk step: Gaussian noise of noise_bps, pulled back toward ``base`` by
    ``revert`` (a fraction of the gap per tick), clamped to lo..hi."""
    shock = random.gauss(0, noise_bps / 10_000.0)
    nxt = price * (1.0 + shock) + (base - price) * revert
    return max(lo, min(hi, nxt))


class MarketTape:
    """In-memory book + history used by /api/market/* and the overlays."""

    def __init__(self, section: dict | None = None, listings_path: Path | str | None = None,
                 books: list[dict] | None = None):
        """section: the plugin's own settings block (stonks: in config.yaml).
        books: preview listings games ask for (their plugin.json "market_books")."""
        cfg = section or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.tick_sec = float(cfg.get("tick_sec", 5) or 5)
        self.noise_bps = float(cfg.get("noise_bps", 18) or 18)
        # revert_bps is stored as a fraction (15 bps -> 0.0015 of the gap closed per tick).
        self.revert = float(cfg.get("revert_bps", 15) or 15) / 10_000.0
        self.history_len = int(cfg.get("history_len", 180) or 180)
        self.steam_weight = float(cfg.get("steam_weight", 0.45) or 0.45)
        self.steam_band = float(cfg.get("steam_band", 0.25) or 0.25)
        self.steam_poll_sec = float(cfg.get("steam_poll_sec", 1800) or 1800)
        self.chatter_points_scale = float(cfg.get("chatter_points_scale", 10) or 10)
        self.chatter_streak_bonus = float(cfg.get("chatter_streak_bonus", 0.05) or 0.05)
        self.trade_impact = bool(cfg.get("trade_impact", True))
        self.trade_impact_bps_per_100 = float(cfg.get("trade_impact_bps_per_100", 40) or 0)
        self.cooldowns = CooldownGate()
        self.last_event: Optional[dict] = None
        self.last_dividend: Optional[dict] = None
        self._instruments: dict[str, dict] = {}
        self._history: dict[str, list[dict]] = {}
        self.listings_path = Path(listings_path) if listings_path else None
        self._seed_preview(books or [])
        self.load_listings()

    def configure(self, section: dict) -> None:
        """Apply a saved settings block (GamerStonks.apply_config after a dashboard save)."""
        cfg = section or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.tick_sec = float(cfg.get("tick_sec", self.tick_sec) or self.tick_sec)
        self.noise_bps = float(cfg.get("noise_bps", self.noise_bps) or self.noise_bps)
        if "steam_poll_sec" in cfg:
            self.steam_poll_sec = float(cfg.get("steam_poll_sec") or 1800)
        if "chatter_points_scale" in cfg:
            self.chatter_points_scale = float(cfg.get("chatter_points_scale") or 10)
        if "chatter_streak_bonus" in cfg:
            self.chatter_streak_bonus = float(cfg.get("chatter_streak_bonus") or 0.05)
        if "trade_impact" in cfg:
            self.trade_impact = bool(cfg.get("trade_impact"))
        if "trade_impact_bps_per_100" in cfg:
            self.trade_impact_bps_per_100 = float(cfg.get("trade_impact_bps_per_100") or 0)

    def _seed_preview(self, books: list[dict]) -> None:
        """Always-on preview listings so OBS sources are not empty."""
        # FRG (the streamer's ticker) is always listed; Steam-linked game books follow
        # player counts, the rest random-walk.
        seeds = [("FRG", "Fridge", "core", "streamer", 10.0, None)]
        # Game books come from the installed game plugins (plugin.json "market_books")
        for row in books:
            price = float(row.get("price") or 10.0)
            seeds.append((
                str(row["symbol"]), str(row.get("name") or row["symbol"]), str(row.get("book")),
                str(row.get("role") or "plain"), price, row.get("steam_appid"),
            ))
        for sym, name, book, role, price, appid in seeds:
            self.upsert(
                symbol=sym,
                name=name,
                book=book,
                role=role,
                price=price,
                base_price=price,
                steam_appid=appid,
                feed="steam" if appid else "walk",
            )

    def upsert(
        self,
        *,
        symbol: str,
        name: str,
        book: str,
        role: str = "plain",
        price: float = 10.0,
        base_price: float | None = None,
        min_price: float = 0.5,
        max_price: float = 500.0,
        status: str = "listed",
        feed: str | None = None,
        steam_appid: int | None = None,
        steam_mode: str | None = None,
        chatter_user_id: int | None = None,
        chatter_link_points: bool | None = None,
        chatter_streak_bonus: float | None = None,
        chatter_points_scale: float | None = None,
        persist: bool = False,
    ) -> dict:
        """Create or update a ticker and return its live dict.

        An existing ticker keeps its current price (``price`` only seeds new ones);
        min_price / max_price are reset to the arguments on every call.
        ``persist=True`` also rewrites tickers.json.
        """
        sym = _clean_symbol(symbol)
        if not sym:
            raise ValueError("symbol required (A-Z, 0-9, dot, max 8)")
        now = _now()
        inst = self._instruments.get(sym) or {}
        appid = steam_appid if steam_appid is not None else inst.get("steam_appid")
        try:
            appid = int(appid) if appid not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            appid = None
        feed = (feed or inst.get("feed") or ("steam" if appid else "walk")).lower()
        inst.update({
            "symbol": sym,
            "name": name,
            "book": book or inst.get("book") or "core",
            "role": role,
            "status": status,
            "feed": feed,
            "steam_appid": appid,
            "steam_mode": (steam_mode or inst.get("steam_mode") or "ratio"),
            "steam_weight": float(inst.get("steam_weight") or self.steam_weight),
            "steam_baseline": inst.get("steam_baseline"),
            "steam_ccu": inst.get("steam_ccu"),
            "steam_factor": float(inst.get("steam_factor") or 1.0),
            "steam_stale": bool(inst.get("steam_stale", False)),
            "chatter_user_id": int(chatter_user_id) if chatter_user_id else inst.get("chatter_user_id"),
            "chatter_link_points": (
                bool(chatter_link_points)
                if chatter_link_points is not None
                else bool(inst.get("chatter_link_points", False))
            ),
            "chatter_streak_bonus": float(
                chatter_streak_bonus
                if chatter_streak_bonus is not None
                else inst.get("chatter_streak_bonus") or self.chatter_streak_bonus
            ),
            "chatter_points_scale": float(
                chatter_points_scale
                if chatter_points_scale is not None
                else inst.get("chatter_points_scale") or self.chatter_points_scale
            ),
            "chatter_listed_points": inst.get("chatter_listed_points"),
            "chatter_streak": int(inst.get("chatter_streak") or 0),
            "price": float(inst.get("price", price)),
            "open": float(inst.get("open", price)),
            "base_price": float(base_price if base_price is not None else inst.get("base_price", price)),
            "min_price": float(min_price),
            "max_price": float(max_price),
            "updated_at": now,
        })
        if "high" not in inst:
            inst["high"] = inst["price"]
            inst["low"] = inst["price"]
        self._instruments[sym] = inst
        self._history.setdefault(sym, [])
        if not self._history[sym]:
            self._push_tick(sym, inst["price"], now)
        if persist:
            self.save_listings()
        return inst

    def listing_records(self) -> list[dict]:
        """The fields saved to tickers.json (no live price / history)."""
        out = []
        for inst in self._instruments.values():
            out.append({
                "symbol": inst["symbol"],
                "name": inst.get("name"),
                "book": inst.get("book"),
                "role": inst.get("role"),
                "status": inst.get("status"),
                "feed": inst.get("feed"),
                "base_price": inst.get("base_price"),
                "min_price": inst.get("min_price"),
                "max_price": inst.get("max_price"),
                "steam_appid": inst.get("steam_appid"),
                "steam_mode": inst.get("steam_mode"),
                "steam_weight": inst.get("steam_weight"),
                "steam_baseline": inst.get("steam_baseline"),
                "chatter_user_id": inst.get("chatter_user_id"),
                "chatter_link_points": inst.get("chatter_link_points"),
                "chatter_streak_bonus": inst.get("chatter_streak_bonus"),
                "chatter_points_scale": inst.get("chatter_points_scale"),
                "chatter_listed_points": inst.get("chatter_listed_points"),
                "chatter_streak": inst.get("chatter_streak"),
            })
        return out

    def save_listings(self) -> None:
        if not self.listings_path:
            return
        self.listings_path.parent.mkdir(parents=True, exist_ok=True)
        self.listings_path.write_text(
            json.dumps(self.listing_records(), indent=2),
            encoding="utf-8",
        )

    def load_listings(self) -> None:
        """Re-list everything from tickers.json; new tickers start at their base price."""
        path = self.listings_path
        if not path or not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("market listings unreadable: %s", path)
            return
        if not isinstance(raw, list):
            return
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                self.upsert(
                    symbol=str(row.get("symbol") or ""),
                    name=str(row.get("name") or row.get("symbol") or ""),
                    book=str(row.get("book") or "core"),
                    role=str(row.get("role") or "plain"),
                    price=float(row.get("base_price") or row.get("price") or 10),
                    base_price=float(row.get("base_price") or 10),
                    min_price=float(row.get("min_price") or 0.5),
                    max_price=float(row.get("max_price") or 500),
                    status=str(row.get("status") or "listed"),
                    feed=row.get("feed"),
                    steam_appid=row.get("steam_appid"),
                    steam_mode=row.get("steam_mode"),
                    chatter_user_id=row.get("chatter_user_id"),
                    chatter_link_points=row.get("chatter_link_points"),
                    chatter_streak_bonus=row.get("chatter_streak_bonus"),
                    chatter_points_scale=row.get("chatter_points_scale"),
                )
                inst = self.quote(str(row.get("symbol") or ""))
                if inst and row.get("chatter_listed_points") is not None:
                    inst["chatter_listed_points"] = int(row["chatter_listed_points"])
                inst = self.quote(str(row.get("symbol") or ""))
                if inst and row.get("steam_baseline"):
                    inst["steam_baseline"] = int(row["steam_baseline"])
                if inst and row.get("steam_weight"):
                    inst["steam_weight"] = float(row["steam_weight"])
            except Exception:
                log.warning("skip listing row %s", row)

    def delist(self, symbol: str, *, persist: bool = True) -> bool:
        inst = self.quote(symbol)
        if not inst:
            return False
        inst["status"] = "delisted"
        if persist:
            self.save_listings()
        return True

    def apply_trade_impact(self, symbol: str, points: float, *, side: str) -> Optional[dict]:
        """Buys push the price up, sells down: trade_impact_bps_per_100 bps per 100 points."""
        if not self.trade_impact or not points:
            return None
        bps = self.trade_impact_bps_per_100
        frac = (float(points) / 100.0) * (bps / 10_000.0)
        if side == "sell":
            frac = -frac
        return self.apply_return(symbol, frac, reason=f"trade:{side}")

    def apply_steam_ccu(self, appid: int, ccu: int) -> list[dict]:
        """Peg every ticker with this App ID. First sample sets baseline only."""
        # Each doubling of players vs the baseline moves the factor by steam_weight
        # (capped at +/- steam_band doublings). "delta" mode compares with the previous
        # sample instead of the first one.
        touched = []
        for inst in self._instruments.values():
            if inst.get("steam_appid") != int(appid):
                continue
            if inst.get("status") != "listed":
                continue
            inst["steam_ccu"] = int(ccu)
            inst["steam_stale"] = False
            inst["steam_polled_at"] = _now()
            if not inst.get("steam_baseline"):
                inst["steam_baseline"] = int(ccu)
                inst["steam_factor"] = 1.0
                touched.append(inst)
                continue
            weight = float(inst.get("steam_weight") or self.steam_weight)
            band = self.steam_band
            mode = str(inst.get("steam_mode") or "ratio")
            prev = int(inst.get("steam_prev_ccu") or inst["steam_baseline"])
            base = int(inst["steam_baseline"]) if mode != "delta" else max(prev, 1)
            log_now = math.log(max(int(ccu), 1))
            log_base = math.log(max(base, 1))
            raw = (log_now - log_base) / math.log(2)
            factor = 1.0 + weight * max(-band, min(band, raw))
            old = float(inst.get("steam_factor") or 1.0)
            inst["steam_factor"] = factor
            inst["steam_prev_ccu"] = int(ccu)
            if old > 0 and abs(factor - old) > 0.0001:
                self.apply_return(inst["symbol"], (factor / old) - 1.0, reason="steam_ccu")
            touched.append(inst)
        if touched:
            self.save_listings()
        return touched

    def mark_steam_stale(self, appid: int) -> None:
        for inst in self._instruments.values():
            if inst.get("steam_appid") == int(appid):
                inst["steam_stale"] = True

    def steam_appids(self) -> list[int]:
        """App IDs of listed Steam tickers (at most 20 per poll)."""
        ids = []
        for inst in self._instruments.values():
            if inst.get("status") != "listed":
                continue
            appid = inst.get("steam_appid")
            if appid and int(appid) not in ids:
                ids.append(int(appid))
        return ids[:20]

    async def poll_steam(self) -> dict:
        """Fetch player counts for every Steam ticker; failures mark the ticker stale."""
        appids = self.steam_appids()
        if not appids:
            return {"ok": True, "polled": 0}
        try:
            import httpx
        except ImportError:
            return {"ok": False, "error": "httpx missing"}
        ok = 0
        errors = []
        async with httpx.AsyncClient(timeout=8.0) as client:
            for appid in appids:
                try:
                    r = await client.get(STEAM_CCU_URL, params={"appid": appid})
                    data = r.json() if r.status_code < 400 else {}
                    resp = data.get("response") or {}
                    if int(resp.get("result") or 0) != 1:
                        self.mark_steam_stale(appid)
                        errors.append({"appid": appid, "error": "no result"})
                        continue
                    self.apply_steam_ccu(appid, int(resp.get("player_count") or 0))
                    ok += 1
                except Exception as exc:
                    self.mark_steam_stale(appid)
                    errors.append({"appid": appid, "error": str(exc)})
                    log.warning("steam CCU appid=%s failed: %s", appid, exc)
        return {"ok": True, "polled": ok, "appids": appids, "errors": errors}

    async def tick_chatter(self, store) -> dict:
        """Peg chatter listings to channel points + consecutive-stream bonus."""
        # price = points / chatter_points_scale, times (1 + streak bonus per extra stream).
        # With chatter_link_points the link works both ways: the chatter's points are set
        # to match the price (store.set_points).
        if store is None:
            return {"ok": False, "updated": 0}
        updated = 0
        for inst in list(self._instruments.values()):
            if inst.get("status") != "listed":
                continue
            if (inst.get("feed") or "") != "chatter" and not inst.get("chatter_user_id"):
                continue
            uid = int(inst.get("chatter_user_id") or 0)
            if uid <= 0:
                continue
            user = await store.get_user(uid)
            if not user:
                continue
            points = int(user.get("points") or 0)
            if inst.get("chatter_listed_points") is None:
                inst["chatter_listed_points"] = points
            streak = await store.chatter_streak(uid)
            inst["chatter_streak"] = streak
            bonus = float(inst.get("chatter_streak_bonus") or self.chatter_streak_bonus)
            scale = float(inst.get("chatter_points_scale") or self.chatter_points_scale) or 10.0
            linked = bool(inst.get("chatter_link_points"))
            raw_pts = points if linked else int(inst.get("chatter_listed_points") or points)
            mul = 1.0 + bonus * max(0, streak - 1)
            price = max(inst.get("min_price", 0.5), (raw_pts / scale) * mul)
            price = min(float(inst.get("max_price") or 500), price)
            inst["price"] = price
            inst["updated_at"] = _now()
            if linked:
                target_pts = int(round(price * scale / mul)) if mul else int(round(price * scale))
                target_pts = max(0, target_pts)
                if target_pts != points and hasattr(store, "set_points"):
                    await store.set_points(uid, target_pts, "stock-link", "market")
            updated += 1
        if updated:
            self.save_listings()
        return {"ok": True, "updated": updated}

    def _push_tick(self, symbol: str, price: float, ts: float) -> None:
        """Append a {t: unix seconds, p: price} point; keep the newest history_len."""
        row = {"t": ts, "p": round(price, 4)}
        buf = self._history.setdefault(symbol, [])
        buf.append(row)
        if len(buf) > self.history_len:
            del buf[: len(buf) - self.history_len]

    def tick(self) -> dict:
        """Random-walk every listed ticker once (GamerStonks._loop, every tick_sec seconds)."""
        now = _now()
        for inst in self._instruments.values():
            if inst.get("status") != "listed":
                continue
            nxt = _walk(
                float(inst["price"]),
                noise_bps=self.noise_bps,
                revert=self.revert,
                base=float(inst["base_price"]),
                lo=float(inst["min_price"]),
                hi=float(inst["max_price"]),
            )
            inst["price"] = nxt
            inst["high"] = max(float(inst.get("high", nxt)), nxt)
            inst["low"] = min(float(inst.get("low", nxt)), nxt)
            inst["updated_at"] = now
            self._push_tick(inst["symbol"], nxt, now)
        return self.snapshot()

    def apply_return(self, symbol: str, frac: float, *, reason: str = "") -> Optional[dict]:
        """Move one price by ``frac`` (0.05 = +5 %), clamped to its min/max; sets last_event.

        Returns the ticker dict, or None for an unknown symbol.
        """
        inst = self._instruments.get(symbol.upper())
        if not inst:
            return None
        nxt = float(inst["price"]) * (1.0 + float(frac))
        nxt = max(float(inst["min_price"]), min(float(inst["max_price"]), nxt))
        inst["price"] = nxt
        inst["high"] = max(float(inst.get("high", nxt)), nxt)
        inst["low"] = min(float(inst.get("low", nxt)), nxt)
        inst["updated_at"] = _now()
        self._push_tick(inst["symbol"], nxt, inst["updated_at"])
        self.last_event = {
            "ts": inst["updated_at"],
            "symbol": inst["symbol"],
            "reason": reason,
            "pct": round(float(frac) * 100.0, 2),
        }
        return inst

    def try_signal(
        self,
        *,
        name: str,
        symbol: str | None,
        cooldown_sec: float | None,
        book: str | None = None,
        scope: str = "symbol",
    ) -> dict:
        """
        scope:
          symbol — cooldown is per ticker (spawn camp on FACT does not block STEVE)
          book   — one shot per game book
          global — one shot across the whole market
        cooldown_sec 0 / None / omitted → always allowed.
        """
        sym = (symbol or "").upper() or None
        if scope == "global":
            key = CooldownGate.key("signal", name)
        elif scope == "book":
            key = CooldownGate.key("signal", name, "book", book or "")
        else:
            key = CooldownGate.key("signal", name, "sym", sym or "*")
        wait = self.cooldowns.remaining(key, cooldown_sec)
        if wait > 0:
            return {"ok": False, "blocked": True, "retry_in": round(wait, 2), "key": key}
        self.cooldowns.touch(key)
        return {"ok": True, "blocked": False, "key": key}

    def snapshot(self, book: str | None = None, symbols: list[str] | None = None, *, include_hidden: bool = False) -> dict:
        """Overlay payload (/api/market/state): listed tickers with delta / pct vs open.

        ``book`` matches "game:minecraft" or just "minecraft". Hidden and delisted
        tickers are left out unless include_hidden.
        """
        want = {s.upper() for s in (symbols or []) if s}
        items = []
        for inst in self._instruments.values():
            status = inst.get("status") or "listed"
            if not include_hidden and status in ("hidden", "delisted"):
                continue
            if book and inst["book"] != book and not inst["book"].endswith(":" + book):
                continue
            if want and inst["symbol"] not in want:
                continue
            price = float(inst["price"])
            open_ = float(inst.get("open") or price)
            delta = price - open_
            pct = (delta / open_ * 100.0) if open_ else 0.0
            items.append({
                **inst,
                "price": round(price, 4),
                "open": round(open_, 4),
                "high": round(float(inst.get("high", price)), 4),
                "low": round(float(inst.get("low", price)), 4),
                "delta": round(delta, 4),
                "pct": round(pct, 2),
            })
        items.sort(key=lambda r: (0 if r.get("role") == "streamer" else 1, r["symbol"]))
        return {
            "enabled": self.enabled,
            "preview": not self.enabled,
            "ts": _now(),
            "tick_sec": self.tick_sec,
            "instruments": items,
            "last_event": self.last_event,
            "last_dividend": self.last_dividend,
        }

    def quote(self, symbol: str) -> Optional[dict]:
        """The live ticker dict (not a copy), or None."""
        return self._instruments.get((symbol or "").upper())

    def stock_factor(
        self,
        symbols: list[str] | None,
        *,
        lo: float = 0.25,
        hi: float = 3.0,
    ) -> dict:
        """
        Mean of price/base across symbols. Used by Chat Dynamo so a hot
        tape makes more RF without rewriting power_level.
        """
        vals = []
        used = []
        for raw in symbols or []:
            inst = self.quote(str(raw))
            if not inst:
                continue
            price = float(inst.get("price") or 0)
            base = float(inst.get("base_price") or inst.get("open") or 0) or 1.0
            f = price / base if base else 1.0
            vals.append(f)
            used.append({
                "symbol": inst["symbol"],
                "price": round(price, 4),
                "base": round(base, 4),
                "factor": round(f, 4),
            })
        raw = sum(vals) / len(vals) if vals else 1.0
        clamped = max(float(lo), min(float(hi), raw))
        return {
            "factor": round(clamped, 4),
            "raw": round(raw, 4),
            "symbols": used,
        }

    def history(self, symbol: str, points: int = 120) -> dict:
        """Newest ``points`` history samples for the chart overlays."""
        sym = symbol.upper()
        buf = list(self._history.get(sym) or [])
        if points > 0:
            buf = buf[-int(points):]
        inst = self._instruments.get(sym)
        return {
            "symbol": sym,
            "name": (inst or {}).get("name", sym),
            "points": buf,
            "last": (inst or {}).get("price"),
        }
