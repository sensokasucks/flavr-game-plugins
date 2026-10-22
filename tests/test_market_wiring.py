"""Minecraft and Factorio find Gamer Stonks inside a real Stream Core (Gamer Stonks part 3).

Before this, Core never handed the games a market, so in a live Core the dynamo factor,
the power drain, the death dips and the Minecraft vault payouts silently did nothing.
These tests start each game together with Gamer Stonks through Core's own PluginManager
(no attach_market) and check that the effects reach the tape and the holders.
The game's mod / bridge is faked with an httpx MockTransport.

Needs a Stream Core checkout (see conftest.py). From this repo's folder:

    python -m pytest tests/test_market_wiring.py -q
"""

from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from core import plugin_manifest
from core.config import DEFAULTS
from core.models import MetricsSnapshot
from core.plugins import PluginManager
from core.store import Store


def fake_game(answers: dict, posts: list) -> httpx.AsyncClient:
    """An HTTP client whose calls never leave the test: GETs answer from ``answers``
    (path -> JSON), POSTs are recorded in ``posts`` as (path, body) and answer {}."""
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append((request.url.path, json.loads(request.content or b"{}")))
            return httpx.Response(200, json={})
        return httpx.Response(200, json=answers.get(request.url.path, {}))
    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


class MarketWiringTests(unittest.TestCase):
    def setUp(self):
        plugin_manifest.reset_cache()
        self.addCleanup(plugin_manifest.reset_cache)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "data").mkdir()
        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg["stonks"]["enabled"] = True
        self.cfg["stonks"]["tick_sec"] = 3600          # no random price walk during a test
        self.cfg["stonks"]["dividend_price_bump"] = 0  # so only the effect under test moves prices

    async def start(self, *games: str, stonks: bool = True):
        """A Core plugin manager with ``games`` (and Gamer Stonks unless stonks=False) started."""
        self.cfg["stonks"]["enabled"] = stonks
        for game in games:
            self.cfg[game]["enabled"] = True
        store = Store(self.root / "data" / "stream_core.db", {"enabled": True})
        mgr = PluginManager(get_config=lambda: self.cfg, games={}, store=store, root=self.root)
        mgr.load_all()
        await mgr.start_enabled()
        return mgr, store

    def test_games_start_after_gamer_stonks(self):
        order = [m.id for m in plugin_manifest.start_order(plugin_manifest.discover(force=True))]
        for game in ("minecraft", "factorio"):
            self.assertLess(order.index("stonks"), order.index(game), game)

    def test_minecraft_vault_pays_holders(self):
        async def go():
            mgr, store = await self.start("minecraft")
            mc, stonks = mgr.games["minecraft"], mgr.games["stonks"]
            self.assertIs(mc._market, stonks.tape)
            uid = await store.get_or_create_user("twitch", "h1", "holder", "holder")
            await stonks.holdings.adjust(uid, "MINECRAF", 1000)
            posts: list = []
            await mc._client.aclose()
            mc._client = fake_game({
                # 5000 RF pending; default vault_rf_per_point 200 -> 25 points
                "/api/market": {"pendingRf": 5000, "pendingXp": 0, "vaultSymbol": "MINECRAF"},
                "/api/devices": {"devices": []},
            }, posts)
            await mc.on_metrics(MetricsSnapshot(power_level=5))
            self.assertEqual((await store.get_user(uid))["points"], 25)
            acks = [body for path, body in posts if path == "/api/market/ack"]
            self.assertEqual(acks, [{"rf": 5000.0, "xp": 0.0}])
            self.assertEqual(stonks.tape.last_dividend["game"], "minecraft")
            await mgr.stop_all()
        asyncio.run(go())

    def test_minecraft_keeps_vault_work_without_gamer_stonks(self):
        async def go():
            mgr, _store = await self.start("minecraft", stonks=False)
            mc = mgr.games["minecraft"]
            self.assertIsNone(mc._market)
            posts: list = []
            await mc._client.aclose()
            mc._client = fake_game({"/api/market": {"pendingRf": 5000}, "/api/devices": {"devices": []}}, posts)
            await mc.on_metrics(MetricsSnapshot())
            self.assertFalse([p for p, _ in posts if p == "/api/market/ack"])
            self.assertEqual(mc.stock_boost()["factor"], 1.0)
            await mgr.stop_all()
        asyncio.run(go())

    def test_minecraft_death_dips_ticker(self):
        async def go():
            mgr, _store = await self.start("minecraft")
            mc, tape = mgr.games["minecraft"], mgr.games["stonks"].tape
            before = tape.quote("MINECRAF")["price"]
            posts: list = []
            await mc._client.aclose()
            mc._client = fake_game({"/api/stats": {"deaths": 1}, "/api/devices": {"devices": []}}, posts)
            await mc.on_metrics(MetricsSnapshot())           # first reading only remembers the count
            mc._client = fake_game({"/api/stats": {"deaths": 2}, "/api/devices": {"devices": []}}, posts)
            await mc.on_metrics(MetricsSnapshot())
            self.assertLess(tape.quote("MINECRAF")["price"], before)
            await mgr.stop_all()
        asyncio.run(go())

    def test_factorio_dynamo_factor_and_power_drain(self):
        async def go():
            self.cfg["factorio"]["market"]["power_drain"] = True
            mgr, _store = await self.start("factorio")
            fx, tape = mgr.games["factorio"], mgr.games["stonks"].tape
            self.assertIs(fx._market, tape)
            tape.apply_return("FACTORIO", 0.5, reason="test")
            hot = tape.quote("FACTORIO")["price"]
            posts: list = []
            await fx._client.aclose()
            fx._client = fake_game({}, posts)
            await fx.on_metrics(MetricsSnapshot(power_level=15))
            sent = [body for path, body in posts if path == "/api/metrics"][0]
            self.assertGreater(sent["pwrFactor"], 1.0)
            self.assertEqual(sent["pwrSymbols"], ["FACTORIO"])
            self.assertLess(tape.quote("FACTORIO")["price"], hot)   # the drain moved it down
            await mgr.stop_all()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
