"""Sumotori Dreams plugin: arena file text, bet maths, and a full run inside a real PluginManager + Store.

The game itself can't run in the cloud, so the arena file is only checked as text here; whether
Sumotori Dreams Classic accepts it is on checklists/sumotori.md for Sen's PC.

Needs a Stream Core checkout (see conftest.py). From this repo's folder:

    python -m pytest plugins/sumotori -q
"""

from __future__ import annotations

import asyncio
import copy
import random
import tempfile
import unittest
from pathlib import Path

from core import plugin_manifest
from core.config import DEFAULTS
from core.event_bus import EventBus
from core.models import ChatUser, ExecuteRequest, Platform
from core.plugins import PluginManager
from core.store import Store

from plugins.sumotori import arena
from plugins.sumotori.bets import parse_amount, parse_side, payouts, streak

TOKEN = "tok-sumotori-123456789"
OPTS = {"tex": 0, "fixed": 1, "loose": 0, "brk": 1, "floor_y": -7}


# ---------------------------------------------------------------- arena text

class ArenaTests(unittest.TestCase):
    def test_builtin_base_has_four_men_and_a_floor(self):
        text = arena.build_smo(None, [], OPTS)
        self.assertEqual(text.count("man("), 4)
        self.assertIn("addbox(vec(24,2,24),vec(0,-8,0),0,1);", text)
        self.assertTrue(text.endswith("\r\n"))
        self.assertNotIn("{", text)

    def test_piece_sums_are_worked_out(self):
        lines = arena.piece_lines("crates", -3, 2.5, OPTS)
        self.assertEqual(lines[0], "addbox(vec(1.5,1.5,1.5),vec(-3,1,2.5),0,0);")       # -7+8 = 1
        self.assertEqual(lines[1], "addbox(vec(1.5,1.5,1.5),vec(-1,4,2.5),0,0);")       # -3+2, -7+11
        self.assertEqual(lines[4], "addbox(vec(1.5,1.5,1.5),vec(-3,13,0.5),0,0);")      # 2.5-2
        for piece in arena.PIECES:
            for line in arena.piece_lines(piece, 1, 1, OPTS):
                self.assertNotRegex(line, r"\d[+]\d|\{", (piece, line))

    def test_breakable_wall_sets_breakability_after_its_box(self):
        lines = arena.piece_lines("breakwall", 0, 4, dict(OPTS, brk=0.4))
        self.assertTrue(lines[0].startswith("addbox("))
        self.assertEqual(lines[1], "breakability(0.4);")

    def test_custom_base_kept_as_is_and_pieces_after_it(self):
        base = "addbox(vec(10,1,10),vec(0,-3,0),2,1);\r\nman(vec(0,0,0),vec(1,0,0),2);\r\n\r\n"
        text = arena.build_smo(base, [{"piece": "wall", "x": 2, "z": -2}, {"piece": "nope", "x": 0, "z": 0}], OPTS)
        lines = text.split("\r\n")
        self.assertEqual(lines[0], "addbox(vec(10,1,10),vec(0,-3,0),2,1);")
        self.assertEqual(lines[2], "addbox(vec(1,3,8),vec(2,-5.5,-2),0,1);")
        self.assertEqual(len([ln for ln in lines if ln]), 3)        # unknown piece skipped, blank lines trimmed

    def test_spots_stay_on_the_floor_and_off_the_middle(self):
        rng = random.Random(4)
        for _ in range(200):
            x, z = arena.pick_spot(rng, 6)
            self.assertTrue(-6 <= x <= 6 and -6 <= z <= 6)
            self.assertTrue(abs(x) >= 1.5 or abs(z) >= 1.5)

    def test_write_is_whole_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "stream.smo"
            arena.write_smo(p, "a\r\n")
            arena.write_smo(p, "b\r\n")
            self.assertEqual(p.read_bytes(), b"b\r\n")
            self.assertEqual([f.name for f in p.parent.iterdir()], ["stream.smo"])


# ---------------------------------------------------------------- bet maths

class BetMathTests(unittest.TestCase):
    def test_side_words(self):
        self.assertEqual(parse_side("RED", "Red", "Blue"), "a")
        self.assertEqual(parse_side("2", "Red", "Blue"), "b")
        self.assertEqual(parse_side("sen", "Sen", "Bot"), "a")
        self.assertIsNone(parse_side("green", "Red", "Blue"))

    def test_amounts(self):
        self.assertEqual(parse_amount("all", 750), 750)
        self.assertEqual(parse_amount("half", 751), 375)
        self.assertEqual(parse_amount("1.5k", 0), 1500)
        self.assertEqual(parse_amount("1,000", 0), 1000)
        self.assertIsNone(parse_amount("-5", 100))
        self.assertIsNone(parse_amount("lots", 100))
        self.assertIsNone(parse_amount("nan", 100))

    def test_pool_split_by_stake_and_pays_whole_pot(self):
        bets = [{"id": 1, "side": "a", "amount": 100}, {"id": 2, "side": "a", "amount": 200},
                {"id": 3, "side": "b", "amount": 301}]
        pay, refunded = payouts(bets, "a")
        self.assertFalse(refunded)
        self.assertEqual(sum(pay.values()), 601)
        self.assertEqual(pay[1], 200)
        self.assertEqual(pay[2], 401)            # 400 + the 1 point left over from rounding
        self.assertNotIn(3, pay)

    def test_pool_one_sided_refunds(self):
        bets = [{"id": 1, "side": "a", "amount": 100}, {"id": 2, "side": "a", "amount": 50}]
        self.assertEqual(payouts(bets, "b"), ({1: 100, 2: 50}, True))
        self.assertEqual(payouts(bets, "a"), ({1: 100, 2: 50}, True))

    def test_double(self):
        bets = [{"id": 1, "side": "a", "amount": 100}, {"id": 2, "side": "b", "amount": 50}]
        self.assertEqual(payouts(bets, "b", "double"), ({2: 100}, False))

    def test_streak(self):
        self.assertEqual(streak([]), (None, 0))
        self.assertEqual(streak(["a", "b", "b", "b"]), ("b", 3))


# ---------------------------------------------------------------- inside Core

class PluginRunTests(unittest.TestCase):
    def setUp(self):
        plugin_manifest.reset_cache()
        self.addCleanup(plugin_manifest.reset_cache)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "data").mkdir()
        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg["points"]["admin_token"] = TOKEN
        self.cfg["sumotori"]["enabled"] = True
        self.cfg["sumotori"]["arena_file"] = str(self.root / "game" / "mods" / "stream.smo")
        self.cfg["twitch"]["enabled"] = True

    async def started(self):
        store = Store(self.root / "data" / "stream_core.db", {"enabled": True})
        bus = EventBus()
        replies: list[str] = []

        async def on_reply(r):
            replies.append(r.message)
        bus.on_reply(on_reply)
        mgr = PluginManager(get_config=lambda: self.cfg, games={}, store=store, bus=bus, root=self.root)
        mgr.load_all()
        await mgr.start_enabled()
        plugin = mgr.games["sumotori"]
        plugin._running = False
        plugin._task.cancel()                 # the test calls tick() itself
        return mgr, plugin, replies, store

    @staticmethod
    def req(user: ChatUser, text: str) -> ExecuteRequest:
        parts = text.split()
        return ExecuteRequest(command_name=parts[0][1:], template="", args=parts[1:], user=user,
                              platform=user.platform, original_message=text)

    async def chatter(self, store, uid_name: str, points: int) -> ChatUser:
        u = ChatUser(platform=Platform.TWITCH, id=uid_name, username=uid_name, display_name=uid_name.title())
        uid = await store.get_or_create_user("twitch", u.id, u.username, u.display_name)
        await store.adjust_points(uid, points, "test", "test")
        return u

    async def points(self, store, user: ChatUser) -> int:
        uid = await store.get_or_create_user("twitch", user.id, user.username, user.display_name)
        return int((await store.get_user(uid))["points"])

    def test_manifest_and_defaults(self):
        m = plugin_manifest.find("sumotori")
        self.assertEqual(m.error, "")
        self.assertFalse(DEFAULTS["sumotori"]["enabled"])
        for f in m.get("settings"):
            self.assertIn(f["key"], DEFAULTS["sumotori"], f["key"])
        self.assertEqual(set(DEFAULTS["sumotori"]["prices"]), set(arena.PIECES))

    def test_pieces_wait_for_next_arena(self):
        async def go():
            mgr, plugin, replies, store = await self.started()
            path = self.root / "game" / "mods" / "stream.smo"
            self.assertTrue(path.is_file())                       # written at start
            plain = path.read_text()
            zack = await self.chatter(store, "zack", 1000)

            menu = (await plugin.execute(self.req(zack, "!arena")))["reply"]
            self.assertIn("crate 200", menu)
            out = await plugin.execute(self.req(zack, "!arena crate"))
            self.assertIn("next arena", out["reply"])
            self.assertEqual(await self.points(store, zack), 800)
            self.assertEqual(path.read_text(), plain)             # not in the game yet
            self.assertIn("you can add another", (await plugin.execute(self.req(zack, "!arena wall")))["reply"])

            res = await plugin.next_arena()
            self.assertEqual(res["pieces"], 1)
            self.assertEqual(path.read_text().count("addbox"), 2)  # floor + crate
            self.assertTrue(any("New Sumotori arena: a crate from Zack" in r for r in replies), replies)

            # the next arena after that is plain again
            await plugin.next_arena()
            self.assertEqual(path.read_text(), plain)
            await mgr.stop_all()

        asyncio.run(go())

    def test_now_mode_limits_and_clear_refunds(self):
        async def go():
            self.cfg["sumotori"].update(apply="now", piece_cooldown_sec=0, per_user_max=2, max_pieces=3)
            mgr, plugin, _replies, store = await self.started()
            path = self.root / "game" / "mods" / "stream.smo"
            zack = await self.chatter(store, "zack", 2000)
            bea = await self.chatter(store, "bea", 100)
            await plugin.execute(self.req(zack, "!arena wall"))
            self.assertIn("addbox(vec(1,3,8)", path.read_text())   # straight in
            await plugin.execute(self.req(zack, "!arena crate"))
            self.assertIn("already have 2", (await plugin.execute(self.req(zack, "!arena step")))["reply"])
            self.assertIn("you have 100", (await plugin.execute(self.req(bea, "!arena crate")))["reply"])
            self.assertEqual(await self.points(store, zack), 1500)
            res = await plugin.clear_queue()
            self.assertEqual(res["cleared"], 2)
            self.assertEqual(await self.points(store, zack), 2000)
            self.assertEqual(path.read_text().count("addbox"), 1)
            await mgr.stop_all()

        asyncio.run(go())

    def test_bets_round_trip(self):
        async def go():
            self.cfg["sumotori"].update(bet_window_sec=30, bet_max=500)
            mgr, plugin, replies, store = await self.started()
            zack = await self.chatter(store, "zack", 1000)
            bea = await self.chatter(store, "bea", 1000)
            cy = await self.chatter(store, "cy", 1000)

            self.assertIn("aren't open", (await plugin.execute(self.req(zack, "!bet red 100")))["reply"])
            self.assertTrue((await plugin.open_round())["ok"])
            self.assertFalse((await plugin.open_round())["ok"])          # one at a time
            self.assertTrue(any(r.startswith("Bets are open!") for r in replies))

            self.assertIn("100 points on Red", (await plugin.execute(self.req(zack, "!bet red 100")))["reply"])
            self.assertIn("300 points on Red", (await plugin.execute(self.req(zack, "!bet 200 red")))["reply"])
            self.assertIn("already bet on Red", (await plugin.execute(self.req(zack, "!bet blue 5")))["reply"])
            self.assertIn("500 points on Blue", (await plugin.execute(self.req(bea, "!bet blue all")))["reply"])  # capped
            self.assertIn("100 points on Red", (await plugin.execute(self.req(cy, "!bet 1 100")))["reply"])
            dee = await self.chatter(store, "dee", 1000)
            self.assertIn("smallest bet", (await plugin.execute(self.req(dee, "!bet red 1")))["reply"])
            self.assertEqual(await self.points(store, dee), 1000)       # refused bets cost nothing

            # the timer closes bets
            rnd = await plugin.current_round()
            await plugin.tick(now=rnd["locks_at"] + 1)
            self.assertEqual((await plugin.current_round())["state"], "locked")
            self.assertIn("aren't open", (await plugin.execute(self.req(bea, "!bet blue 10")))["reply"])

            st = await plugin.state()
            self.assertEqual(st["round"]["pools"], {"a": 400, "b": 500, "a_n": 2, "b_n": 1})

            res = await plugin.settle_round("a")
            self.assertEqual(res["paid"], 900)
            self.assertEqual(await self.points(store, zack), 700 + 675)  # 300 of 400 on Red: 3/4 of 900
            self.assertEqual(await self.points(store, cy), 900 + 225)
            self.assertEqual(await self.points(store, bea), 500)
            self.assertTrue(any(r.startswith("Red wins! 900 points paid out. Top: Zack +375") for r in replies), replies)
            self.assertIn("Red 1 - 0 Blue", (await plugin.execute(self.req(bea, "!score")))["reply"])
            self.assertIsNone(await plugin.current_round())
            await mgr.stop_all()

        asyncio.run(go())

    def test_cancel_refunds_and_scoreboard_without_bets(self):
        async def go():
            mgr, plugin, _replies, store = await self.started()
            zack = await self.chatter(store, "zack", 1000)
            await plugin.open_round()
            await plugin.execute(self.req(zack, "!bet blue 400"))
            self.assertEqual(await self.points(store, zack), 600)
            await plugin.cancel_round()
            self.assertEqual(await self.points(store, zack), 1000)
            # results with no bets still count; reset starts from zero
            await plugin.settle_round("b")
            await plugin.settle_round("b")
            sc = await plugin.score()
            self.assertEqual((sc["a"], sc["b"], sc["streak_side"], sc["streak"]), (0, 2, "b", 2))
            await plugin.reset_score()
            self.assertEqual((await plugin.score())["rounds"], 0)
            await mgr.stop_all()

        asyncio.run(go())

    def test_routes(self):
        from fastapi import APIRouter, FastAPI
        from fastapi.testclient import TestClient
        from plugins.sumotori.plugin import SumotoriDreams

        async def go():
            mgr, plugin, _r, _s = await self.started()
            return mgr, plugin

        loop = asyncio.new_event_loop()
        mgr, plugin = loop.run_until_complete(go())
        app = FastAPI()
        router = APIRouter()
        holder = {"inst": None}
        SumotoriDreams.routes(router, lambda: holder["inst"])
        app.include_router(router)
        client = TestClient(app)
        self.assertEqual(client.get("/api/sumotori/state").status_code, 503)    # plugin off
        holder["inst"] = plugin
        # TestClient runs the app on its own loop; the plugin's database calls are thread-based, so that's fine
        self.assertEqual(client.get("/api/sumotori/state").json()["sides"], {"a": "Red", "b": "Blue"})
        self.assertNotIn("arena_file", client.get("/api/sumotori/state").json())
        self.assertEqual(client.get("/api/sumotori/admin").status_code, 401)
        h = {"X-Admin-Token": TOKEN}
        self.assertIn("arena_file", client.get("/api/sumotori/admin", headers=h).json())
        self.assertTrue(client.post("/api/sumotori/round", json={"action": "win_a"}, headers=h).json()["ok"])
        self.assertEqual(client.get("/api/sumotori/state").json()["score"]["a"], 1)
        self.assertEqual(client.post("/api/sumotori/round", json={"action": "x"}, headers=h).status_code, 400)
        loop.run_until_complete(mgr.stop_all())
        loop.close()


if __name__ == "__main__":
    unittest.main()
