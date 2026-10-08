import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]       # fridge-stream-core/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.minecraft.plugin import MinecraftIntegration, plan_chest_burns, plan_machine_rf
from core.market import MarketTape


def test_stock_boost_uses_listed_minecraft_ticker():
    tape = MarketTape({})
    mc = MinecraftIntegration({"minecraft": {"enabled": True, "market": {"dynamo_symbols": ["NOPE"]}}})
    mc.attach_market(tape)
    boost = mc.stock_boost()
    used = {row["symbol"] for row in boost["symbols"]}
    assert "MINECRAF" in used or "STEVE" in used
    assert boost["factor"] > 0


def test_stock_boost_follows_hot_price():
    tape = MarketTape({})
    tape.apply_return("MINECRAF", 0.5, reason="test")
    mc = MinecraftIntegration({"minecraft": {"enabled": True}})
    mc.attach_market(tape)
    boost = mc.stock_boost()
    assert boost["factor"] > 1.0


def test_plan_machine_rf_off_below_threshold():
    assert plan_machine_rf(15, 0.4, off_below=0.5, max_rf=2400) == 0
    assert plan_machine_rf(0, 2.0, off_below=0.5, max_rf=2400) == 0
    assert plan_machine_rf(15, 1.0, off_below=0.5, lo=0.25, hi=3, max_rf=2400) == 2400
    assert plan_machine_rf(8, 1.0, off_below=0.5, max_rf=2400) == int(2400 * 8 / 15)


def test_plan_chest_storage_only_when_drain_zero():
    items = [{"slot": 0, "id": "minecraft:iron_ingot", "count": 16}]
    consume, work = plan_chest_burns(items, 0, {"minecraft:iron_ingot": 0.7}, 0.05)
    assert consume == []
    assert work == 0
    consume, work = plan_chest_burns(items, 15, {"minecraft:iron_ingot": 0.7}, 0.05)
    assert consume == [{"slot": 0, "count": 16}]
    assert work == 0.7 * 16
