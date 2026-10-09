"""The default public Minecraft commands only pass listed ids into the game command."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]       # fridge-stream-core/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from core.command_router import CommandRouter
from core.models import ChatEvent, ChatUser, Platform
from core.permissions import PermissionManager

COMMANDS = Path(__file__).resolve().parents[1] / "commands.json"


def _router(tmp_path):
    path = tmp_path / "commands.json"
    path.write_text(COMMANDS.read_text(encoding="utf-8"), encoding="utf-8")
    r = CommandRouter(path, PermissionManager({"permissions": {"admin": [], "mod": []}}), default_player="Steve")
    r.set_enabled_groups({"core", "minecraft"})
    return r


def _run(router, text):
    ev = ChatEvent(platform=Platform.KICK, user=ChatUser(platform=Platform.KICK, id="1", username="viewer"),
                   message=text)
    assert router.parse_message(ev)
    return router.try_execute(ev)


def test_every_public_command_with_a_chat_argument_has_an_allow_list():
    data = json.loads(COMMANDS.read_text(encoding="utf-8"))
    for name, cmd in data.items():
        if cmd.get("permission", "public") == "public" and "{arg1}" in (cmd.get("template") or ""):
            assert cmd.get("allowedValues"), name


@pytest.mark.parametrize("text", [
    "!give netherite_sword[enchantments={levels:{sharpness:255}}]",
    "!give command_block",
    "!give tnt 64",
    "!spawn wither",
    "!spawn ender_dragon",
    "!summon tnt",
    "!effect instant_damage",
])
def test_dangerous_values_refused(tmp_path, text):
    req, reason = _run(_router(tmp_path), text)
    assert req is None
    assert "invalid value" in reason


def test_listed_values_still_work(tmp_path):
    r = _router(tmp_path)
    req, _ = _run(r, "!give diamond 5")
    assert req.template == "give Steve diamond 5"
    req, _ = _run(r, "!spawn creeper")
    assert "summon creeper" in req.template
    req, _ = _run(r, "!effect speed 45")
    assert req.template == "effect give Steve speed 45 1 true"
