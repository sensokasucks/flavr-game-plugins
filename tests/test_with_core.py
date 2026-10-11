"""The four games loaded by a real Stream Core: manifests, defaults, commands, old URLs.

Needs a Stream Core checkout (see conftest.py). From this repo's folder:

    python -m pytest -q
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core import plugin_manifest
from core.command_router import CommandRouter
from core.config import DEFAULTS
from core.permissions import PermissionManager
from core.plugins import PluginManager

BUNDLED = ("factorio", "granvir", "minecraft", "openttd")


class BundledPluginTests(unittest.TestCase):
    """The four games that used to be built in, from the real plugins/ folder."""

    def setUp(self):
        plugin_manifest.reset_cache()
        self.addCleanup(plugin_manifest.reset_cache)

    def test_all_four_install_cleanly(self):
        found = {m.id: m for m in plugin_manifest.discover(force=True)}
        for pid in BUNDLED:
            self.assertIn(pid, found)
            self.assertEqual(found[pid].error, "", pid)
        mgr = PluginManager(get_config=lambda: DEFAULTS, games={})
        mgr.load_all()
        for pid in BUNDLED:
            self.assertEqual(mgr.loaded[pid].error, "", pid)

    def test_config_defaults_kept(self):
        # same defaults as when the games were built in, and all off
        for pid in BUNDLED:
            self.assertFalse(DEFAULTS[pid]["enabled"], pid)
        self.assertEqual(DEFAULTS["minecraft"]["server_mod_url"], "http://127.0.0.1:3853")
        self.assertEqual(DEFAULTS["granvir"]["bridge_url"], "http://127.0.0.1:3855")
        self.assertEqual(DEFAULTS["command_groups"]["minecraft"]["bind"], "minecraft")
        self.assertFalse(DEFAULTS["command_groups"]["openttd"]["always"])

    def test_manifest_fields_reference_real_defaults(self):
        for pid in BUNDLED:
            m = plugin_manifest.find(pid)
            fields = list(m.get("settings") or []) + list((m.get("market") or {}).get("fields") or [])
            for f in fields:
                cur = DEFAULTS[pid]
                for part in str(f["key"]).split("."):
                    self.assertIn(part, cur, f"{pid}: {f['key']}")
                    cur = cur[part]

    def test_plugin_commands_merge_under_the_users_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "commands.json"
            # the user's file renamed !spawn's alias and dropped nothing else
            path.write_text(json.dumps({
                "spawn": {"group": "minecraft", "aliases": ["mob"], "template": "summon {entity}"},
                "points": {"group": "points"},
            }), encoding="utf-8")
            router = CommandRouter(
                commands_path=path,
                permission_manager=PermissionManager(DEFAULTS),
                default_commands=plugin_manifest.default_commands,
            )
            cmds = router.commands
            self.assertEqual(cmds["spawn"].aliases, ["mob"])          # the file wins
            self.assertIn("points", cmds)
            plugin_only = set(plugin_manifest.default_commands()) - {"spawn"}
            self.assertTrue(plugin_only)
            for name in plugin_only:
                self.assertIn(name, cmds)                                # plugin defaults fill the rest

    def test_old_urls_still_answer(self):
        from fastapi.testclient import TestClient

        from api.server import CoreState, create_app

        state = CoreState()
        state.config = DEFAULTS
        state.games = {}
        mgr = PluginManager(get_config=lambda: state.config, games=state.games)
        mgr.load_all()
        state.plugins = mgr
        app = create_app(state)
        with TestClient(app, base_url="http://127.0.0.1:3850") as client:
            self.assertEqual(client.get("/api/stats").json(), {})
            ottd = client.get("/api/openttd/state")
            self.assertEqual(ottd.status_code, 200)
            for page in ("openttd.html", "openttd-ticker.html", "market-openttd.html",
                         "market-minecraft.html", "market-factorio.html", "overlay.html"):
                self.assertEqual(client.get("/overlay/" + page).status_code, 200, page)
            self.assertEqual(client.get("/overlay/nope-not-here.html").status_code, 404)

    def test_factorio_dividend_defaults(self):
        mgr = PluginManager(get_config=lambda: DEFAULTS, games={})
        mgr.load_all()
        # Gamer Stonks reaches the hook through ctx.plugins.class_hook
        hook = mgr.directory.class_hook("factorio", "dividend_defaults")
        self.assertEqual(hook({"unit": "items"}, {})["symbol"], "FACT")
        self.assertEqual(hook({}, {})["symbol"], "PWR")
        self.assertIsNone(mgr.directory.class_hook("granvir", "dividend_defaults"))
