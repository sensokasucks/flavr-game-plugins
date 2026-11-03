"""Schedule I plugin: staff, cash drops, the ingredient vote, suppliers and dealer sponsors.

Pure helpers first, then full runs against the mock mod (fridge-schedule1/mock/mock_server.py), the
same way test_schedule1.py does for customers. The real C# mod can only be tried in the game
(checklists/schedule1.md).

    python -m pytest plugins/schedule1 -q
"""

from __future__ import annotations

import asyncio
import copy
import random
import tempfile
import threading
import unittest
from collections import Counter
from pathlib import Path

from core import plugin_manifest
from core.config import DEFAULTS
from core.event_bus import EventBus
from core.models import ChatEvent, ChatUser, ExecuteRequest, Platform
from core.plugins import PluginManager
from core.store import Store

from plugins.schedule1.dealers import dealer_label, kickback_points
from plugins.schedule1.drops import clean_note, drop_amount
from plugins.schedule1.feature import alert_dollars, match_name
from plugins.schedule1.mixpick import have_list, pick_options
from plugins.schedule1.staff import job_summary, plan_staff, staff_names
from plugins.schedule1.suppliers import tab_points
from plugins.schedule1.tests.test_schedule1 import TOKEN, free_port, load_mock


class HelperTests(unittest.TestCase):
    def test_alert_dollars(self):
        self.assertEqual(alert_dollars({"kind": "bits", "amount": 500, "currency": "bits"}), 5.0)
        self.assertEqual(alert_dollars({"kind": "kicks", "amount": 100, "currency": "KICKs"}), 1.0)
        self.assertEqual(alert_dollars({"kind": "gift", "qty": 3}), 15.0)
        self.assertEqual(alert_dollars({"kind": "superchat", "amount": 4.99, "currency": "USD"}), 4.99)
        self.assertEqual(alert_dollars({"kind": "follow"}), 0.0)

    def test_drop_amount_caps(self):
        self.assertEqual(drop_amount(5, 100, 2000, None), 500)
        self.assertEqual(drop_amount(50, 100, 2000, None), 2000)          # per-drop cap
        self.assertEqual(drop_amount(5, 100, 2000, 300), 300)             # what's left of the stream cap
        self.assertEqual(drop_amount(5, 100, 0, None), 500)               # 0 = no cap

    def test_clean_note(self):
        self.assertEqual(clean_note("hi <b>there</b>\nfriend"), "hi ‹b›there‹/b› friend")
        self.assertEqual(clean_note("one two three four", 9), "one two…")

    def test_match_name(self):
        rows = [{"id": "benji_coleman", "first": "Benji"}, {"id": "brad_crosby", "first": "Brad"}]
        self.assertEqual(match_name("benji", rows)["id"], "benji_coleman")
        self.assertEqual(match_name("BRA", rows)["id"], "brad_crosby")
        self.assertIsNone(match_name("b", rows))                         # two match: ask again
        self.assertIsNone(match_name("zed", rows))

    def test_staff_plan_and_names(self):
        workers = [{"id": "w2", "last": "Diaz"}, {"id": "w1", "last": "Miller"}]
        people = [{"key": "t:2", "joined_at": 2, "emp_id": None, "display_name": "Bea", "username": "bea"},
                  {"key": "t:1", "joined_at": 1, "emp_id": None, "display_name": "Zack", "username": "zack"},
                  {"key": "t:3", "joined_at": 3, "emp_id": None, "display_name": "Cy", "username": "cy"}]
        self.assertEqual(plan_staff(workers, people), [("t:1", "w1"), ("t:2", "w2")])   # first come, ids in order
        people[1]["emp_id"] = "w1"
        self.assertEqual(staff_names(workers, people), {"w1": {"first": "Zack", "last": ""}})
        self.assertEqual(staff_names(workers, people, "chatter_last")["w1"]["last"], "Miller")
        self.assertEqual(job_summary(Counter({"harvested a plant": 3, "watered a plant": 1})),
                         "harvested a plant x3, watered a plant")

    def test_have_list(self):
        ev = {"carried": ["Cuke"], "nearby": ["Cuke", "Banana"], "owned": ["Cuke", "Banana", "Iodine"]}
        self.assertEqual(have_list(ev, "carried"), ["Cuke"])
        self.assertEqual(have_list(ev, "nearby"), ["Cuke", "Banana"])
        self.assertEqual(have_list(ev, "owned"), ["Cuke", "Banana", "Iodine"])
        self.assertEqual(have_list({"carried": ["Cuke"]}, "owned"), ["Cuke"])   # older mod: only "carried"

    def test_pick_options(self):
        r = random.Random(1)
        self.assertEqual(pick_options(["Cuke", "cuke", "Banana"], ["X"], "carried", 6, r), ["Banana", "Cuke"])
        self.assertEqual(pick_options([], ["Gasoline", "Addy"], "carried", 6, r), ["Addy", "Gasoline"])  # carries none
        self.assertEqual(pick_options(["Cuke"], ["Gasoline", "Addy"], "all", 6, r), ["Addy", "Gasoline"])
        self.assertEqual(len(pick_options([], [str(i) for i in range(20)], "all", 4, r)), 4)

    def test_tab_points(self):
        self.assertEqual(tab_points(1000, 0.2, 500), (200.0, 1000))
        self.assertEqual(tab_points(1000, 0.2, 50), (50.0, 250))         # only what's owed; the rest stays
        self.assertEqual(tab_points(1000, 0.2, 0), (0.0, 0))

    def test_dealer_helpers(self):
        self.assertEqual(dealer_label("Benji", "zack"), {"first": "Benji", "last": "(zack)"})
        self.assertEqual(kickback_points(250, 10, 0.0), (25, 0.0))
        pts, carry = kickback_points(15, 10, 0.0)
        self.assertEqual((pts, round(carry, 2)), (1, 0.5))


class MoreHooksMockTests(unittest.TestCase):
    """The five features against the mock mod; the test drives tick() itself (no background loop)."""

    def setUp(self):
        plugin_manifest.reset_cache()
        self.addCleanup(plugin_manifest.reset_cache)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "data").mkdir()
        self.mock = load_mock()
        self.world = self.mock.World(seed=1)
        port = free_port()
        self.server = self.mock.make_server(self.world, port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg["points"]["admin_token"] = TOKEN
        self.cfg["twitch"]["enabled"] = True
        self.cfg["schedule1"].update(enabled=True, bridge_url=f"http://127.0.0.1:{port}")

    async def started(self):
        store = Store(self.root / "data" / "stream_core.db", {"enabled": True})
        self.bus = EventBus()
        replies: list[str] = []

        async def on_reply(r):
            replies.append(r.message)
        self.bus.on_reply(on_reply)
        mgr = PluginManager(get_config=lambda: self.cfg, games={}, store=store, bus=self.bus, root=self.root)
        mgr.load_all()
        await mgr.start_enabled()
        plugin = mgr.games["schedule1"]
        plugin._running = False
        plugin._task.cancel()
        plugin._running = True
        await plugin.tick()                       # connected, event stream known
        return mgr, plugin, replies, store

    @staticmethod
    def req(user: ChatUser, text: str) -> ExecuteRequest:
        parts = text.split()
        return ExecuteRequest(command_name=parts[0][1:], template="", args=parts[1:], user=user,
                              platform=user.platform, original_message=text)

    @staticmethod
    def user(uid: str, name: str, sub: bool = False, plat=Platform.TWITCH) -> ChatUser:
        return ChatUser(platform=plat, id=uid, username=name.lower(), display_name=name, is_subscriber=sub)

    async def points(self, store, user: ChatUser, n: int) -> int:
        uid = await store.get_or_create_user(user.platform.value, user.id, user.username, user.display_name)
        if n:
            await store.adjust_points(uid, n, "test", "test")
        return uid

    def test_manifest_lists_every_setting(self):
        m = plugin_manifest.find("schedule1")
        self.assertEqual(m.error, "")
        for f in m.get("settings"):
            self.assertIn(f["key"], DEFAULTS["schedule1"], f["key"])
        for key in ("staff_enabled", "drop_enabled", "supplier_enabled", "dealer_enabled"):
            self.assertFalse(DEFAULTS["schedule1"][key], key)            # all off until the streamer ticks them

    def test_staff(self):
        async def go():
            mgr, plugin, replies, _store = await self.started()
            zack, bea = self.user("1", "ZackFan99", sub=True), self.user("2", "Bea")
            self.assertIn("switched off", (await plugin.execute(self.req(zack, "!staff")))["reply"])
            self.cfg["schedule1"]["staff_enabled"] = True
            self.assertIn("only subscribers", (await plugin.execute(self.req(bea, "!staff")))["reply"])
            self.assertIn("staff list (#1)", (await plugin.execute(self.req(zack, "!staff")))["reply"])
            await plugin.tick()                   # crew read, worker handed out, name sent
            self.assertEqual(self.world.staff_names, {"emp_botanist_1": {"first": "ZackFan99", "last": ""}})
            self.assertIn("ZackFan99 is now the streamer's botanist at Barn.", replies)
            self.assertIn("botanist at Barn", (await plugin.execute(self.req(zack, "!staff")))["reply"])

            # jobs are added up into one line per worker
            replies.clear()
            self.world.staff_job("emp_botanist_1", "harvested a plant")
            self.world.staff_job("emp_botanist_1", "harvested a plant")
            self.world.staff_job("emp_chemist_1", "started a mix")      # nobody's worker: nothing said
            await plugin.tick()
            self.assertIn("ZackFan99 (the streamer's botanist): harvested a plant x2.", replies)
            self.assertIn("1. ZackFan99 (2 jobs)", (await plugin.execute(self.req(bea, "!topstaff")))["reply"])

            # a customer can't also be staff (staff_one_job)
            cy = self.user("3", "Cy", sub=True)
            await plugin.execute(self.req(cy, "!customer"))
            self.assertIn("already on the customer list", (await plugin.execute(self.req(cy, "!staff")))["reply"])

            # fired: back on the list; leaving gives the worker its own name back
            self.world.staff = [w for w in self.world.staff if w["id"] != "emp_botanist_1"]
            plugin.crew_wake = True
            await plugin.tick()
            self.assertTrue(any("worker left the streamer's staff" in r for r in replies), replies)
            self.assertEqual(plugin.staff.worker("emp_chemist_1")["first"], "Rosa")
            await plugin.tick()                   # handed the next free worker
            self.assertEqual(self.world.staff_names, {"emp_chemist_1": {"first": "ZackFan99", "last": ""}})
            await plugin.execute(self.req(zack, "!staff leave"))
            await plugin.tick()
            self.assertEqual(self.world.staff_names, {})
            await mgr.stop_all()

        asyncio.run(go())

    def test_cash_drops(self):
        async def go():
            mgr, plugin, replies, store = await self.started()
            self.cfg["schedule1"].update(drop_enabled=True, drop_cost=100, drop_cash=200, drop_cooldown_sec=60)
            # a 500-bit cheer: $5 -> $500 in a dead drop, with the cheer's message as the note
            await self.bus.publish_alert({"kind": "bits", "amount": 500, "currency": "bits", "platform": "twitch",
                                          "username": "zackfan99", "display_name": "ZackFan99",
                                          "message": "buy seeds <b>now</b>"})
            self.assertEqual(self.world.drops[-1]["cash"], 500)
            self.assertEqual(self.world.drops[-1]["note"], "buy seeds ‹b›now‹/b›")
            self.assertEqual(self.world.drops[-1]["by"], "ZackFan99")
            await plugin.tick()
            self.assertIn("💰 ZackFan99's $500 is waiting for the streamer at the dead drop behind the motel.", replies)
            self.world.take_drop(self.world.drops[-1]["id"])
            await plugin.tick()
            self.assertIn("💰 The streamer picked up ZackFan99's $500!", replies)

            # follows carry no money; a hidden viewer's drop comes without name or note
            await self.bus.publish_alert({"kind": "follow", "platform": "twitch", "username": "x"})
            self.assertEqual(len(self.world.drops), 1)
            self.cfg["avatars"]["hide"] = ["twitch:badguy"]
            await self.bus.publish_alert({"kind": "donation", "amount": 2, "currency": "USD", "platform": "twitch",
                                          "username": "badguy", "display_name": "BadGuy", "message": "rude words"})
            self.assertEqual((self.world.drops[-1]["by"], self.world.drops[-1]["note"]), ("a viewer", ""))

            # !drop for points; refused by the game = refunded
            zack = self.user("1", "ZackFan99")
            self.assertIn("costs 100 points", (await plugin.execute(self.req(zack, "!drop")))["reply"])
            await self.points(store, zack, 150)
            out = await plugin.execute(self.req(zack, "!drop good luck"))
            self.assertIn("$200 is on its way", out["reply"])
            self.assertEqual(self.world.drops[-1]["note"], "good luck")
            self.assertIn("try again in", (await plugin.execute(self.req(zack, "!drop")))["reply"])
            plugin.drops._ready_at = 0
            self.world.drop_refusal = "every dead drop is full"
            await plugin.execute(self.req(zack, "!drop"))   # paid 100 of the 50 left? no: 50 < 100
            uid = await self.points(store, zack, 100)
            before = (await store.get_user(uid))["points"] if hasattr(store, "get_user") else None
            await plugin.execute(self.req(zack, "!drop"))
            await plugin.tick()
            self.assertTrue(any("every dead drop is full. Points refunded." in r for r in replies), replies)
            if before is not None:
                self.assertEqual((await store.get_user(uid))["points"], before)
            await mgr.stop_all()

        asyncio.run(go())

    def test_ingredient_vote(self):
        async def go():
            mgr, plugin, replies, _store = await self.started()
            self.world.mixpick_button(carried=["Cuke", "Banana", "Gasoline"])
            await plugin.tick()
            self.assertTrue(any("Chat picks the next ingredient for OG Kush" in r and "!1 Banana" in r for r in replies),
                            replies)
            self.assertEqual(self.world.mixpicks[-1]["state"], "vote")
            for uid, vote in (("1", "!3"), ("2", "!3"), ("3", "!1")):
                u = self.user(uid, f"u{uid}")
                await self.bus.publish_chat(ChatEvent(platform=Platform.TWITCH, user=u, message=vote))
            plugin.mixpick.vote.ends_at = 0       # time's up
            await plugin.tick()
            self.assertIn("🧪 Chat picked Gasoline (2 votes)!", replies)
            self.assertEqual((self.world.mixpicks[-1]["state"], self.world.mixpicks[-1]["winner"]), ("done", "Gasoline"))
            self.assertFalse(self.world.mixpicks[-1]["place"])     # mixpick_auto_place is off by default
            self.assertEqual(self.world.mixpicks[-1]["take_from"], "carried")

            # switched off: the mod is told why
            self.cfg["schedule1"]["mixpick_enabled"] = False
            self.world.mixpick_button()
            await plugin.tick()
            self.assertEqual(self.world.mixpicks[-1]["state"], "off")
            await mgr.stop_all()

        asyncio.run(go())

    def test_suppliers(self):
        async def go():
            mgr, plugin, replies, store = await self.started()
            self.cfg["schedule1"].update(supplier_enabled=True, supplier_tab_rate=0.2, supplier_supply_cost=100,
                                         supplier_cooldown_sec=0)
            await plugin.tick()                   # crew (suppliers) read
            zack = self.user("1", "ZackFan99")
            self.assertIn("Albert (owed $300)", (await plugin.execute(self.req(zack, "!tab")))["reply"])
            uid = await self.points(store, zack, 5000)
            out = await plugin.execute(self.req(zack, "!tab alb 5000"))     # $1000 offered, $300 owed
            self.assertIn("paid 1500 points: $300 goes to Albert", out["reply"])
            await plugin.tick()
            self.assertIn("💸 ZackFan99 paid $300 of the streamer's tab with Albert. All paid off!", replies)
            self.assertIn("doesn't owe Albert", (await plugin.execute(self.req(zack, "!tab albert 100")))["reply"])

            out = await plugin.execute(self.req(zack, "!supply albert"))
            self.assertIn("preparing a drop", out["reply"])
            await plugin.tick()
            self.assertIn("📦 Albert left 5x OG Kush Seed from ZackFan99 at the dead drop under the bridge.", replies)
            self.world.take_drop(self.world.supplier_requests[-1]["id"])
            await plugin.tick()
            self.assertIn("📦 The streamer picked up ZackFan99's delivery from Albert.", replies)
            self.assertIn("no supplier called zed", (await plugin.execute(self.req(zack, "!supply zed")))["reply"])
            await mgr.stop_all()

        asyncio.run(go())

    def test_dealer_sponsors(self):
        async def go():
            mgr, plugin, replies, store = await self.started()
            self.cfg["schedule1"].update(dealer_enabled=True, dealer_min_bid=500, dealer_kickback_per_100=10,
                                         dealer_announce_sec=0)
            await plugin.tick()
            zack, bea = self.user("1", "ZackFan99"), self.user("2", "Bea", plat=Platform.KICK)
            self.assertIn("Benji (free, 500+)", (await plugin.execute(self.req(zack, "!sponsor")))["reply"])
            self.assertIn("at least 500", (await plugin.execute(self.req(zack, "!sponsor benji 100")))["reply"])
            await self.points(store, zack, 1000)
            self.assertIn("you back Benji now", (await plugin.execute(self.req(zack, "!sponsor benji 600")))["reply"])
            await plugin.tick()
            self.assertEqual(self.world.dealer_names, {"benji_coleman": {"first": "Benji", "last": "(ZackFan99)"}})

            # sales: chat line and kickback points for the sponsor
            self.world.dealer_sale("benji_coleman", 250, deals=2)
            await plugin.tick()
            self.assertIn("💵 ZackFan99's dealer Benji sold 2 deals for $250.", replies)
            self.world.dealer_robbed("benji_coleman", 120, items=3)
            self.world.dealer_empty("benji_coleman")
            await plugin.tick()
            self.assertIn("🚨 ZackFan99's dealer Benji got robbed: lost $120 and 3 items.", replies)
            self.assertIn("📦 ZackFan99's dealer Benji is out of stock. Time to restock!", replies)
            self.assertIn("1. ZackFan99 $250 (25 pts)", (await plugin.execute(self.req(bea, "!topdealers")))["reply"])

            # outbid: Bea takes Benji, Zack gets his 600 back
            await self.points(store, bea, 1000)
            self.assertIn("at least 601", (await plugin.execute(self.req(bea, "!sponsor benji 600")))["reply"])
            await plugin.execute(self.req(bea, "!sponsor benji 700"))
            self.assertTrue(any("Bea outbid you on Benji; your 600 points are back." in r for r in replies), replies)
            await plugin.tick()
            self.assertEqual(self.world.dealer_names["benji_coleman"]["last"], "(Bea)")
            # switched off: dealers get their own names back
            self.cfg["schedule1"]["dealer_enabled"] = False
            await plugin.tick()
            self.assertEqual(self.world.dealer_names, {})
            await mgr.stop_all()

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
