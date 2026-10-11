"""Gamer Stonks: the tape, trading, dividends, moving in from Core's old market, and its routes.

Needs a Stream Core checkout (see conftest.py). From this repo's folder:

    python -m pytest plugins/stonks -q
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import plugin_manifest
from core.config import DEFAULTS
from core.cooldown import CooldownGate
from core.models import ChatUser, ExecuteRequest, Platform
from core.plugins import PluginManager
from core.store import Store

from plugins.stonks.tape import MarketTape

TOKEN = "tok-stonks-123456789"
PAGE = {"origin": "http://127.0.0.1:3850"}


# ---------------------------------------------------------------- the tape (ported from Core)

class TapeTests(unittest.TestCase):
    def test_cooldown_zero_always_allows(self):
        g = CooldownGate()
        self.assertTrue(g.try_acquire("death|FACT", 0))
        self.assertTrue(g.try_acquire("death|FACT", 0))
        self.assertTrue(g.try_acquire("death|FACT", None))

    def test_cooldown_blocks_same_key(self):
        g = CooldownGate()
        self.assertTrue(g.try_acquire("death|FACT", 30))
        self.assertFalse(g.try_acquire("death|FACT", 30))
        self.assertGreater(g.remaining("death|FACT", 30), 0)
        self.assertTrue(g.try_acquire("death|STEVE", 30))

    def test_signal_scope_and_death_dip(self):
        tape = MarketTape({})
        tape.upsert(symbol="FACTORIO", name="Factorio", book="game:factorio")
        self.assertTrue(tape.try_signal(name="player_death", symbol="FACTORIO", cooldown_sec=20, scope="symbol")["ok"])
        again = tape.try_signal(name="player_death", symbol="FACTORIO", cooldown_sec=20, scope="symbol")
        self.assertTrue(again["blocked"])
        self.assertTrue(tape.try_signal(name="player_death", symbol="MINECRAF", cooldown_sec=20, scope="symbol")["ok"])
        before = tape.snapshot(symbols=["FACTORIO"])["instruments"][0]["price"]
        tape.apply_return("FACTORIO", -0.08, reason="player_death")
        after = tape.snapshot(symbols=["FACTORIO"])["instruments"][0]["price"]
        self.assertLess(after, before)
        self.assertTrue(tape.history("FACTORIO", points=10)["points"])

    def test_add_ticker_with_steam_appid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "listings.json"
            tape = MarketTape({}, listings_path=path)
            tape.upsert(symbol="ER", name="Elden Ring", book="core", price=10,
                        steam_appid=1245620, feed="steam", persist=True)
            self.assertEqual(tape.quote("ER")["steam_appid"], 1245620)
            tape.apply_steam_ccu(1245620, 80000)
            self.assertEqual(tape.quote("ER")["steam_baseline"], 80000)
            tape.apply_steam_ccu(1245620, 160000)
            self.assertGreater(tape.quote("ER")["steam_factor"], 1)
            self.assertEqual(MarketTape({}, listings_path=path).quote("ER")["steam_appid"], 1245620)

    def test_game_books_seed_listings(self):
        tape = MarketTape({}, books=[{"book": "game:minecraft", "symbol": "MINECRAF", "name": "Minecraft", "price": 10}])
        self.assertEqual(tape.quote("MINECRAF")["book"], "game:minecraft")


# ---------------------------------------------------------------- the plugin inside Core

class PluginTests(unittest.TestCase):
    def setUp(self):
        plugin_manifest.reset_cache()
        self.addCleanup(plugin_manifest.reset_cache)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "data").mkdir()
        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg["stonks"]["enabled"] = True
        self.cfg["stonks"]["tick_sec"] = 3600          # no price walk during a test
        self.cfg["points"]["admin_token"] = TOKEN

    def core_db_with_old_holdings(self, rows):
        """Core's database as it was before the move: a market_holdings table."""
        path = self.root / "data" / "stream_core.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE market_holdings (user_id INTEGER, symbol TEXT, milli_shares INTEGER, "
                         "updated_at REAL, PRIMARY KEY (user_id, symbol))")
            conn.executemany("INSERT INTO market_holdings VALUES (?, ?, ?, 0)", rows)
        return path

    def manager(self, store):
        mgr = PluginManager(get_config=lambda: self.cfg, games={}, store=store, root=self.root)
        mgr.load_all()
        return mgr

    def test_manifest_is_clean(self):
        m = plugin_manifest.find("stonks")
        self.assertEqual(m.error, "")
        self.assertEqual(m.category, "feature")
        self.assertEqual(m.provides, ["market"])
        self.assertEqual(plugin_manifest.moved_sections(), {"market": "stonks"})
        self.assertEqual(plugin_manifest.special_owners()["market_buy"], "stonks")
        self.assertEqual(plugin_manifest.group_defaults()["market"]["bind"], "stonks")

    def test_trading_dividend_and_move_in(self):
        db = self.core_db_with_old_holdings([(1, "FRG", 2000)])
        (self.root / "data" / "market_tickers.json").write_text(json.dumps(
            {"instruments": [{"symbol": "ER", "name": "Elden Ring", "book": "core", "price": 10}]}))

        async def go():
            store = Store(db, {"enabled": True})
            old_holder = await store.get_or_create_user("twitch", "o1", "oldtimer", "oldtimer")
            self.assertEqual(old_holder, 1)
            mgr = self.manager(store)
            await mgr.start_enabled()
            stonks = mgr.games["stonks"]
            self.assertIs(mgr.directory.service("market"), stonks.tape)
            # the old holder kept their shares, and the old tickers file came along
            self.assertEqual(await stonks.holdings.for_user(1),
                             [{"user_id": 1, "symbol": "FRG", "milli_shares": 2000}])
            self.assertTrue((self.root / "data" / "plugins" / "stonks" / "tickers.json").is_file())

            viewer = ChatUser(platform=Platform.KICK, id="v1", username="viewer")
            uid = await store.get_or_create_user("kick", "v1", "viewer", "viewer")
            await store.adjust_points(uid, 100)

            def req(text, special):
                return ExecuteRequest(command_name=text.split()[0][1:], template="", args=text.split()[1:],
                                      special=special, user=viewer, platform=Platform.KICK,
                                      original_message=text)

            out = await stonks.execute(req("!buy FRG 40", "market_buy"))
            self.assertIn("bought", out["reply"])
            self.assertEqual((await store.get_user(uid))["points"], 60)
            out = await stonks.execute(req("!buy FRG 500", "market_buy"))
            self.assertIn("need 500 points", out["reply"])
            self.assertIn("FRG", (await stonks.execute(req("!portfolio", "market_portfolio")))["reply"])
            self.assertIn("Tickers:", (await stonks.execute(req("!tickers", "market_tickers")))["reply"])

            # a vault flush pays holders by shares
            paid = await stonks.dividend({"game": "factorio", "symbol": "FRG", "work": 0, "points": 50})
            self.assertEqual(paid["payout"]["holders"], 2)

            out = await stonks.execute(req("!sell FRG all", "market_sell"))
            self.assertIn("sold", out["reply"])
            self.assertEqual(await stonks.holdings.for_user(uid), [])
            await mgr.stop_all()

            # a second start doesn't copy the old holdings again
            mgr = self.manager(store)
            await mgr.start_enabled()
            self.assertEqual((await mgr.games["stonks"].holdings.for_user(1))[0]["milli_shares"], 2000)
            await mgr.stop_all()

        asyncio.run(go())

    def test_routes(self):
        import httpx

        from api.server import CoreState, create_app

        async def go():
            store = Store(self.root / "data" / "stream_core.db", {"enabled": True})
            mgr = self.manager(store)
            state = CoreState()
            state.config = self.cfg
            state.games = mgr.games
            state.plugins = mgr
            app = create_app(state)
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:3850") as c:
                # installed but off: the addresses answer, with a reason
                self.assertEqual((await c.get("/api/market/state")).status_code, 503)
                await mgr.start_enabled()
                self.assertTrue((await c.get("/api/market/state")).json()["instruments"])
                self.assertEqual((await c.get("/api/market/history?symbol=FRG")).status_code, 200)
                # games may signal; web pages may not
                sig = {"name": "player_death", "symbol": "FRG"}
                self.assertEqual((await c.post("/api/market/signal", json=sig)).status_code, 200)
                self.assertEqual((await c.post("/api/market/signal", json=sig, headers=PAGE)).status_code, 403)
                self.assertEqual((await c.post("/api/market/dividend", json={"symbol": "FRG", "points": 5},
                                               headers=PAGE)).status_code, 403)
                # the Gamer Stonks page needs the admin token
                self.assertEqual((await c.get("/api/admin/market")).status_code, 401)
                r = await c.get("/api/admin/market", headers={"X-Admin-Token": TOKEN})
                self.assertEqual(r.status_code, 200, r.text)
                # the overlays answer at their old addresses
                for page in ("market.html", "market-board.html", "market-chart.html", "market-cycle.html"):
                    self.assertEqual((await c.get("/overlay/" + page)).status_code, 200, page)
                # and the dashboard page is served
                self.assertEqual((await c.get("/plugin-pages/stonks/index.html")).status_code, 200)
            await mgr.stop_all()

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
