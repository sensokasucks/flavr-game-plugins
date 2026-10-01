"""
Factorio game integration.

Talks to the standalone Fridge Factorio Stats bridge (default :3847).
That process owns RCON + Wiretap + overlay files; Core:
  - health-checks GET /stats
  - lists overlay URLs in Admin → Integrations
  - POSTs /api/metrics (power_level 0–15) so Chat Dynamos in-game generate electricity

Enable with factorio.enabled=true and keep the Node bridge running.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin

import httpx

from core.models import ExecuteRequest, MetricsSnapshot
from games.base import BaseGameIntegration

log = logging.getLogger("games.factorio")

OVERLAY_PAGES = (
    ("Full stats overlay", "overlay.html", "Power, research, kills, deaths, evolution, alerts"),
    ("Power", "power.html", "Production / consumption"),
    ("Research", "research.html", "Current tech + progress"),
    ("Kills", "kills.html", "Biters down"),
    ("Deaths", "deaths.html", "Player deaths"),
    ("Evolution", "evolution.html", "Evolution factor"),
    ("Combat", "combat.html", "Kills + deaths"),
    ("Alerts", "alerts.html", "Factory alerts"),
)


class FactorioIntegration(BaseGameIntegration):
    name = "factorio"

    def __init__(self, config: dict):
        super().__init__(config)
        fx = config.get("factorio") or {}
        self.enabled = bool(fx.get("enabled", False))
        self.bridge_url = str(fx.get("bridge_url") or "http://127.0.0.1:3847").rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self.last_stats: dict = {}
        self.core_url = str((config.get("core") or {}).get("public_url") or "http://127.0.0.1:3850").rstrip("/")
        self._market = None

    def overlay_catalog(self) -> list[dict]:
        base = self.bridge_url
        pages = [
            {"name": title, "url": urljoin(base + "/", path), "notes": notes}
            for title, path, notes in OVERLAY_PAGES
        ]
        pages.append({
            "name": "Factorio market tape",
            "url": "http://127.0.0.1:3850/overlay/market-factorio.html",
            "notes": "FACTORIO ticker + vault drain",
        })
        return pages

    async def start(self) -> None:
        if not self.enabled:
            log.info("Factorio integration disabled in config")
            return
        # X-Fridge-Core: the mods / bridge only accept calls that carry it
        # (a browser page cannot add custom headers cross-origin without a preflight).
        self._client = httpx.AsyncClient(timeout=4.0, headers={"X-Fridge-Core": "1"})
        log.info("Factorio integration ready (bridge=%s)", self.bridge_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def execute(self, req: ExecuteRequest) -> dict:
        if not self.enabled:
            return {"success": False, "error": "factorio integration disabled"}
        return {
            "success": False,
            "error": "Factorio chat commands are not sent into the factory yet — Chat Dynamo uses metrics only",
            "command": req.command_name,
        }

    def attach_market(self, tape) -> None:
        self._market = tape

    def _market_cfg(self) -> dict:
        live = getattr(self, "config", None) or self.config
        fx = (live or {}).get("factorio") or {}
        return dict(fx.get("market") or {})

    @staticmethod
    def _symbols(raw) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            return [s.strip().upper() for s in raw.split(",") if s.strip()]
        return [str(s).strip().upper() for s in raw if str(s).strip()]

    def _boost(self) -> dict:
        cfg = self._market_cfg()
        symbols = self._symbols(cfg.get("dynamo_symbols") or ["FACTORIO"])
        tape = self._market
        if tape is None or not hasattr(tape, "stock_factor"):
            return {"factor": 1.0, "symbols": symbols, "raw": 1.0}
        return tape.stock_factor(
            symbols,
            lo=float(cfg.get("dynamo_min_factor", 0.25) or 0.25),
            hi=float(cfg.get("dynamo_max_factor", 3.0) or 3.0),
        )

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        if not self.enabled or not self._client:
            return
        cfg = self._market_cfg()
        boost = self._boost()
        try:
            await self._client.post(
                f"{self.bridge_url}/api/metrics",
                json={
                    "viewers": snap.viewers,
                    "cpm": snap.cpm,
                    "commands": snap.command_rate,
                    "powerLevel": snap.power_level,
                    "pwrFactor": boost.get("factor", 1.0),
                    "pwrSymbols": [s.get("symbol") if isinstance(s, dict) else s for s in (boost.get("symbols") or [])],
                    "vaultSymbols": self._symbols(cfg.get("vault_symbol") or "FACTORIO"),
                    "chestSymbols": self._symbols(cfg.get("chest_symbol") or "FACTORIO"),
                    "vaultFlushMj": float(cfg.get("vault_flush_mj", 25) or 25),
                    "chestFlushItems": int(cfg.get("chest_flush_items", 20) or 20),
                },
            )
        except Exception:
            pass
        if cfg.get("power_drain") and self._market and snap.power_level:
            bps = float(cfg.get("power_drain_bps") or 0)
            frac = -(bps / 10_000.0) * (snap.power_level / 15.0)
            for sym in self._symbols(cfg.get("dynamo_symbols") or ["FACTORIO"]):
                self._market.apply_return(sym, frac, reason="power_drain")

    async def fetch_stats(self) -> dict:
        if not self._client:
            return {}
        try:
            r = await self._client.get(f"{self.bridge_url}/stats")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    self.last_stats = data
                    return data
        except Exception:
            pass
        return {}

    async def health(self) -> bool:
        if not self.enabled or not self._client:
            return False
        try:
            r = await self._client.get(f"{self.bridge_url}/stats")
            if r.status_code == 200:
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if isinstance(data, dict):
                    self.last_stats = data
                return True
            return False
        except Exception:
            return False
