"""OpenTTD Chat Fund helpers — no live server required."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]       # fridge-stream-core/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.openttd.openttd_market import OpenTTDMarket, company_price
from core.config import DEFAULTS


class PriceTests(unittest.TestCase):
    def test_price_positive(self):
        p = company_price({"money": 500_000, "loan": 100_000, "income": 20_000, "vehicle_total": 8})
        self.assertGreaterEqual(p, 1)

    def test_cash_is_discounted(self):
        rich = company_price({"money": 10_000_000, "loan": 0, "income": 0, "vehicle_total": 0})
        poor = company_price({"money": 10_000, "loan": 0, "income": 0, "vehicle_total": 0})
        self.assertGreater(rich, poor)


class LedgerTests(unittest.TestCase):
    def test_record_and_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = OpenTTDMarket(Path(tmp) / "t.db")
            market.record_invest(
                platform="kick",
                username="sensoka",
                user_id=1,
                company_id=2,
                company_name="Red Rails",
                points=50,
                pounds=50_000,
                injected=True,
            )
            totals = market.funded_totals()
            self.assertEqual(totals[2]["pounds"], 50_000)
            self.assertEqual(totals[2]["hits"], 1)
            rec = market.recent(1)
            self.assertEqual(rec[0]["username"], "sensoka")


class DefaultsTests(unittest.TestCase):
    def test_openttd_default_off(self):
        self.assertFalse(DEFAULTS["openttd"]["enabled"])
        self.assertEqual(DEFAULTS["openttd"]["admin_port"], 3977)


if __name__ == "__main__":
    unittest.main()
