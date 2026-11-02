"""Schedule I plugin: name rules, who gets which customer, and a full run against the mock mod.

The end-to-end tests start fridge-schedule1/mock/mock_server.py on a free port, so the plugin, its
HTTP client (bridge.py) and the mock are checked against each other. The real C# mod can only be
tried on a PC with the game (checklists/schedule1.md).

Needs a Stream Core checkout (see conftest.py). From this repo's folder:

    python -m pytest plugins/schedule1 -q
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import socket
import tempfile
import threading
import unittest
from pathlib import Path

import httpx

from core import plugin_manifest
from core.config import DEFAULTS
from core.event_bus import EventBus
from core.models import ChatUser, ExecuteRequest, Platform
from core.plugins import PluginManager
from core.store import Store

from plugins.schedule1.roster import clean_name, desired_names, person_key, plan_assignments, plan_rotation

REPO = Path(__file__).resolve().parents[3]
TOKEN = "tok-schedule1-123456789"


def load_mock():
    """fridge-schedule1/mock/mock_server.py as a module (it isn't a package)."""
    path = REPO / "fridge-schedule1" / "mock" / "mock_server.py"
    spec = importlib.util.spec_from_file_location("schedule1_mock", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- pure helpers

class NameTests(unittest.TestCase):
    def test_display_name_when_the_font_can_show_it(self):
        self.assertEqual(clean_name("ZackFan99", "zackfan99"), "ZackFan99")
        self.assertEqual(clean_name("Mr. O'Neil-Smith", "oneil"), "Mr. O'Neil-Smith")

    def test_falls_back_to_username(self):
        self.assertEqual(clean_name("ザック", "zack_jp"), "zack_jp")
        self.assertEqual(clean_name("🔥fire🔥", "🔥fire_guy"), "fire_guy")

    def test_length_cap(self):
        self.assertEqual(clean_name("a" * 50, "x", max_len=10), "a" * 10)

    def test_person_key(self):
        self.assertEqual(person_key("Twitch", "123", "Zack"), "twitch:123")
        self.assertEqual(person_key("kick", "", "@Zack"), "kick:zack")


class PlanTests(unittest.TestCase):
    CUSTOMERS = [
        {"id": "a_locked", "unlocked": False, "first": "Al", "last": "Locked"},
        {"id": "b_met", "unlocked": True, "first": "Bea", "last": "Met"},
        {"id": "c_met", "unlocked": True, "first": "Cy", "last": "Met"},
    ]

    def person(self, key, joined, npc=None, name=None):
        return {"key": key, "joined_at": joined, "npc_id": npc, "username": name or key, "display_name": name or key}

    def test_met_customers_first_and_first_come_first_served(self):
        people = [self.person("t:2", 2), self.person("t:1", 1), self.person("t:3", 3)]
        self.assertEqual(plan_assignments(self.CUSTOMERS, people),
                         [("t:1", "b_met"), ("t:2", "c_met"), ("t:3", "a_locked")])

    def test_without_prefer_unlocked_order_is_by_id(self):
        people = [self.person("t:1", 1)]
        self.assertEqual(plan_assignments(self.CUSTOMERS, people, prefer_unlocked=False), [("t:1", "a_locked")])

    def test_keeps_existing_and_respects_max(self):
        people = [self.person("t:1", 1, npc="b_met"), self.person("t:2", 2), self.person("t:3", 3)]
        self.assertEqual(plan_assignments(self.CUSTOMERS, people, max_named=2), [("t:2", "c_met")])

    def test_rotation_rules(self):
        # a: 2 deals on the customer, assigned at t=100; b: 0 deals, assigned at t=0; c waits
        a = dict(self.person("t:a", 1, npc="b_met"), shift_deals=2, assigned_at=100, is_sub=0)
        b = dict(self.person("t:b", 2, npc="c_met"), shift_deals=0, assigned_at=0, is_sub=1)
        c = self.person("t:c", 3)
        people = [a, b, c]
        self.assertEqual(plan_rotation(people), [])                                  # both triggers off
        self.assertEqual(plan_rotation(people, after_deals=2), ["t:a"])
        self.assertEqual(plan_rotation(people, after_min=1, now=130), ["t:b"])       # only b has 60 s in
        # both due, one waiting: the longest-serving one goes; subs can be kept on
        self.assertEqual(plan_rotation(people, after_min=1, now=1000), ["t:b"])
        self.assertEqual(plan_rotation(people, after_min=1, now=1000, keep_subs=True), ["t:a"])
        # nobody waiting: nobody rotates
        self.assertEqual(plan_rotation([a, b], after_deals=1, after_min=1, now=1000), [])

    def test_desired_names_only_for_customers_in_game(self):
        people = [self.person("t:1", 1, npc="b_met", name="zackfan99"),
                  self.person("t:2", 2, npc="gone_npc", name="other")]
        self.assertEqual(desired_names(self.CUSTOMERS, people), {"b_met": {"first": "zackfan99", "last": ""}})
        self.assertEqual(desired_names(self.CUSTOMERS, people, name_style="chatter_last"),
                         {"b_met": {"first": "zackfan99", "last": "Met"}})


# ---------------------------------------------------------------- against the mock mod

class MockModTests(unittest.TestCase):
    def setUp(self):
        plugin_manifest.reset_cache()
        self.addCleanup(plugin_manifest.reset_cache)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "data").mkdir()

        self.mock = load_mock()
        self.world = self.mock.World(seed=1)
        self.port = free_port()
        self.server = self.mock.make_server(self.world, self.port, token="s3cret")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg["points"]["admin_token"] = TOKEN
        self.cfg["schedule1"]["enabled"] = True
        self.cfg["schedule1"]["bridge_url"] = f"http://127.0.0.1:{self.port}"
        self.cfg["schedule1"]["bridge_token"] = "s3cret"

    def manager(self, store, bus):
        mgr = PluginManager(get_config=lambda: self.cfg, games={}, store=store, bus=bus, root=self.root)
        mgr.load_all()
        return mgr

    async def started(self):
        """A running plugin with its background loop stopped, so the test drives tick() itself."""
        store = Store(self.root / "data" / "stream_core.db", {"enabled": True})
        bus = EventBus()
        replies: list[str] = []

        async def on_reply(r):
            replies.append(r.message)
        bus.on_reply(on_reply)
        mgr = self.manager(store, bus)
        await mgr.start_enabled()
        plugin = mgr.games["schedule1"]
        plugin._running = False
        plugin._task.cancel()
        plugin._running = True        # handlers stay live; only the loop is gone
        return mgr, plugin, replies, store

    @staticmethod
    def req(user: ChatUser, text: str) -> ExecuteRequest:
        parts = text.split()
        return ExecuteRequest(command_name=parts[0][1:], template="", args=parts[1:], user=user,
                              platform=user.platform, original_message=text)

    def test_manifest_and_defaults(self):
        m = plugin_manifest.find("schedule1")
        self.assertEqual(m.error, "")
        self.assertFalse(DEFAULTS["schedule1"]["enabled"])
        self.assertEqual(DEFAULTS["schedule1"]["bridge_url"], "http://127.0.0.1:3857")
        for f in m.get("settings"):
            self.assertIn(f["key"], DEFAULTS["schedule1"], f["key"])

    def test_customers_orders_and_deals(self):
        async def go():
            mgr, plugin, replies, _store = await self.started()
            zack = ChatUser(platform=Platform.TWITCH, id="1", username="zackfan99", display_name="ZackFan99")
            bea = ChatUser(platform=Platform.KICK, id="2", username="bea", display_name="Bea")

            out = await plugin.execute(self.req(zack, "!customer"))
            self.assertIn("customer list (#1)", out["reply"])
            await plugin.execute(self.req(bea, "!customer"))
            await plugin.tick()

            # both got a customer the streamer has already met, and the mock shows their names
            names = {c["id"]: c["shown"] for c in self.world.snapshot()["customers"]}
            self.assertEqual(names["austin_steiner"], "ZackFan99")   # met customers, sorted by id
            self.assertEqual(names["beth_penn"], "Bea")
            self.assertIn("ZackFan99 is now one of the streamer's customers in Schedule I.", replies)
            self.assertIn("already a customer", (await plugin.execute(self.req(zack, "!customer")))["reply"])

            # an order and its deal are said in chat, and the deal is counted
            replies.clear()
            self.world.order("austin_steiner", deal_after=0)
            self.world.step()
            await plugin.tick()
            self.assertTrue(any(r.startswith("ZackFan99 wants") for r in replies), replies)
            self.assertTrue(any(r.startswith("ZackFan99 bought") and "(deal #1)" in r for r in replies), replies)
            top = (await plugin.execute(self.req(bea, "!topcustomers")))["reply"]
            self.assertIn("1. ZackFan99", top)

            # leaving puts the customer's own name back
            await plugin.execute(self.req(zack, "!customer leave"))
            await plugin.tick()
            names = {c["id"]: c["shown"] for c in self.world.snapshot()["customers"]}
            self.assertEqual(names["austin_steiner"], "Austin Steiner")
            await mgr.stop_all()

        asyncio.run(go())

    def test_phone_app_board_and_buttons(self):
        """The phone app's lists reach the mod; its Swap / Remove buttons come back as events."""
        async def go():
            self.cfg["schedule1"]["max_named"] = 1      # one customer, so the second chatter waits
            mgr, plugin, _replies, _store = await self.started()
            zack = ChatUser(platform=Platform.TWITCH, id="1", username="zackfan99", display_name="ZackFan99")
            bea = ChatUser(platform=Platform.KICK, id="2", username="bea", display_name="Bea")
            await plugin.execute(self.req(zack, "!customer"))
            await plugin.execute(self.req(bea, "!customer"))
            await plugin.tick()
            board = self.world.board
            self.assertEqual([(r["name"], r["customer"]) for r in board["named"]], [("ZackFan99", "Austin Steiner")])
            self.assertEqual([r["name"] for r in board["waiting"]], ["Bea"])

            # Swap: Zack goes to the back of the line, Bea gets the customer
            self.world.app_button("app_swap", "twitch:1")
            await plugin.tick()                 # reads the event, wakes the sync
            await plugin.tick()                 # sync sends the new names and board
            self.assertEqual([r["name"] for r in self.world.board["named"]], ["Bea"])
            self.assertEqual([r["name"] for r in self.world.board["waiting"]], ["ZackFan99"])

            # Remove: Bea is off the list; Zack, next in line, gets a customer again
            self.world.app_button("app_remove", "kick:2")
            await plugin.tick()
            await plugin.tick()
            self.assertIsNone(await plugin.roster.get("kick:2"))
            self.assertEqual([r["name"] for r in self.world.board["named"]], ["ZackFan99"])

            # Swap with nobody waiting changes nothing and says so on the phone
            self.world.app_button("app_swap", "twitch:1")
            await plugin.tick()
            self.assertIn("Nobody is waiting", self.world.notices[-1]["text"])
            self.assertTrue((await plugin.roster.get("twitch:1"))["npc_id"])
            await mgr.stop_all()

        asyncio.run(go())

    def test_shift_rotation(self):
        """A chatter's customer passes to the next waiting chatter after a deal / after some minutes."""
        async def go():
            self.cfg["schedule1"]["max_named"] = 1
            self.cfg["schedule1"]["rotate_after_deals"] = 1
            mgr, plugin, replies, _store = await self.started()
            zack = ChatUser(platform=Platform.TWITCH, id="1", username="zackfan99", display_name="ZackFan99")
            bea = ChatUser(platform=Platform.KICK, id="2", username="bea", display_name="Bea")
            await plugin.execute(self.req(zack, "!customer"))
            await plugin.execute(self.req(bea, "!customer"))
            await plugin.tick()
            self.assertEqual((await plugin.roster.get("twitch:1"))["npc_id"], "austin_steiner")

            # Zack's customer makes a deal: his shift ends, Bea takes over, totals stay with Zack
            replies.clear()
            self.world.order("austin_steiner", deal_after=0)
            self.world.step()
            await plugin.tick()                 # deal recorded, sync woken
            await plugin.tick()                 # rotation
            self.assertEqual((await plugin.roster.get("kick:2"))["npc_id"], "austin_steiner")
            zack_row = await plugin.roster.get("twitch:1")
            self.assertIsNone(zack_row["npc_id"])
            self.assertEqual(zack_row["deals"], 1)
            self.assertIn("ZackFan99's shift is over, Bea takes over Austin Steiner.", replies)
            names = {c["id"]: c["shown"] for c in self.world.snapshot()["customers"]}
            self.assertEqual(names["austin_steiner"], "Bea")

            # by time: Bea has been on for 10 minutes -> Zack's turn again
            self.cfg["schedule1"]["rotate_after_deals"] = 0
            self.cfg["schedule1"]["rotate_after_min"] = 5
            await plugin.roster.db.execute("UPDATE people SET assigned_at = assigned_at - 600 WHERE key = 'kick:2'")
            plugin._wake.set()
            await plugin.tick()
            self.assertEqual((await plugin.roster.get("twitch:1"))["npc_id"], "austin_steiner")

            # subscribers keep theirs when rotate_keep_subs is on
            self.cfg["schedule1"]["rotate_keep_subs"] = True
            zack_sub = ChatUser(platform=Platform.TWITCH, id="1", username="zackfan99", display_name="ZackFan99",
                                is_subscriber=True)
            await plugin.execute(self.req(zack_sub, "!customer"))
            await plugin.roster.db.execute("UPDATE people SET assigned_at = assigned_at - 600 WHERE key = 'twitch:1'")
            plugin._wake.set()
            await plugin.tick()
            self.assertEqual((await plugin.roster.get("twitch:1"))["npc_id"], "austin_steiner")
            await mgr.stop_all()

        asyncio.run(go())

    def test_stream_alerts_on_the_phone(self):
        from core.alerts import build_alert

        async def go():
            self.cfg["avatars"]["hide"] = ["twitch:sneaky"]
            mgr, plugin, _replies, _store = await self.started()
            zack = ChatUser(platform=Platform.TWITCH, id="1", username="zackfan99", display_name="ZackFan99")
            await plugin.execute(self.req(zack, "!customer"))
            await plugin.tick()

            sub = build_alert(kind="subscribe", username="zackfan99", display_name="ZackFan99", platform="twitch")
            await plugin._on_alert(sub)
            self.assertEqual(self.world.notices, [])          # off by default

            self.cfg["schedule1"]["alerts_in_game"] = True
            await plugin._on_alert(sub)
            self.assertEqual(self.world.notices[-1],
                             {"title": "New subscriber", "text": "ZackFan99 subscribed! (your customer Austin Steiner)"})
            await plugin._on_alert(build_alert(kind="follow", username="newbie", platform="kick"))
            self.assertEqual(self.world.notices[-1]["text"], "newbie followed!")
            await plugin._on_alert(build_alert(kind="flag", username="newbie", platform="kick"))
            self.assertEqual(len(self.world.notices), 2)       # "flag" is left out unless picked

            # only the picked kinds; hidden chatters never show up in the game
            self.cfg["schedule1"]["alert_kinds"] = "raid, subscribe"
            await plugin._on_alert(build_alert(kind="follow", username="other", platform="kick"))
            await plugin._on_alert(build_alert(kind="raid", username="sneaky", platform="twitch"))
            self.assertEqual(len(self.world.notices), 2)
            await plugin._on_alert(build_alert(kind="raid", username="bigstreamer", platform="twitch", viewers=50))
            self.assertEqual(self.world.notices[-1]["text"], "bigstreamer raided with 50 viewers!")
            await mgr.stop_all()

        asyncio.run(go())

    def test_hidden_chatters_never_get_a_name(self):
        async def go():
            self.cfg["avatars"]["hide"] = ["twitch:sneaky"]
            mgr, plugin, replies, _store = await self.started()
            sneaky = ChatUser(platform=Platform.TWITCH, id="9", username="sneaky")
            out = await plugin.execute(self.req(sneaky, "!customer"))
            self.assertNotIn("reply", out)
            await plugin.tick()
            self.assertEqual(self.world.names, {})
            # someone put on the hide list after joining is taken off at the next sync
            ok = ChatUser(platform=Platform.TWITCH, id="10", username="laterhidden")
            await plugin.execute(self.req(ok, "!customer"))
            await plugin.tick()
            self.assertEqual(len(self.world.names), 1)
            self.cfg["avatars"]["hide"].append("laterhidden")
            plugin._wake.set()
            await plugin.tick()
            self.assertEqual(self.world.names, {})
            await mgr.stop_all()

        asyncio.run(go())

    def test_auto_join_subs(self):
        from core.models import ChatEvent

        async def go():
            self.cfg["schedule1"]["auto_join"] = "subs"
            mgr, plugin, _replies, _store = await self.started()
            sub = ChatUser(platform=Platform.YOUTUBE, id="m1", username="member", is_subscriber=True)
            pleb = ChatUser(platform=Platform.YOUTUBE, id="p1", username="pleb")
            for u in (sub, pleb):
                await plugin._on_chat(ChatEvent(platform=u.platform, user=u, message="hi"))
            keys = [r["key"] for r in await plugin.roster.all()]
            self.assertEqual(keys, ["youtube:m1"])
            await mgr.stop_all()

        asyncio.run(go())

    def test_mod_rules_and_offline(self):
        async def go():
            base = f"http://127.0.0.1:{self.port}"
            async with httpx.AsyncClient() as c:
                # web pages and calls without Core's header or the right token are refused
                ok = {"X-Fridge-Core": "1", "X-Fridge-Token": "s3cret"}
                self.assertEqual((await c.get(base + "/customers", headers=ok)).status_code, 200)
                self.assertEqual((await c.get(base + "/customers", headers={**ok, "Origin": "http://evil"})).status_code, 403)
                self.assertEqual((await c.get(base + "/customers", headers={"X-Fridge-Core": "1"})).status_code, 403)
                self.assertEqual((await c.post(base + "/names", json={"names": {}})).status_code, 403)

            # with the mod gone the plugin reports it instead of crashing
            self.cfg["schedule1"]["bridge_url"] = f"http://127.0.0.1:{free_port()}"
            mgr, plugin, _replies, _store = await self.started()
            await plugin.tick()
            self.assertFalse(plugin.connected)
            self.assertIn("can't reach", plugin.status()["error"])
            await mgr.stop_all()

        asyncio.run(go())

    def test_page_routes(self):
        from api.server import CoreState, create_app

        async def go():
            mgr, plugin, _replies, _store = await self.started()
            state = CoreState()
            state.config = self.cfg
            state.games = mgr.games
            state.plugins = mgr
            app = create_app(state)
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            admin = {"X-Admin-Token": TOKEN}
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:3850") as c:
                self.assertEqual((await c.get("/api/schedule1/customers")).status_code, 401)
                r = await c.post("/api/schedule1/customers/add", json={"platform": "youtube", "username": "@Viewer"},
                                 headers=admin)
                self.assertEqual(r.status_code, 200, r.text)
                await plugin.tick()
                data = (await c.get("/api/schedule1/customers", headers=admin)).json()
                self.assertTrue(data["connected"])
                self.assertEqual(data["people"][0]["name"], "Viewer")
                self.assertTrue(data["people"][0]["in_game"])
                r = await c.post("/api/schedule1/customers/remove", json={"key": data["people"][0]["key"]}, headers=admin)
                self.assertTrue(r.json()["ok"])
                self.assertEqual((await c.post("/api/schedule1/customers/add", json={"platform": "myspace", "username": "x"},
                                               headers=admin)).status_code, 400)
                self.assertEqual((await c.get("/plugin-pages/schedule1/index.html")).status_code, 200)
            await mgr.stop_all()

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
