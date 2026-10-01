"""
OpenTTD game integration for Fridge Stream Core.

Talks to a dedicated / listen server over the Admin Port (default TCP 3977).
Works on vanilla and JGRPP.

Chat effects the map by:
  1. Spending Core points (!invest)
  2. Announcing via rcon say
  3. Asking FridgeChatFund (Game Script) to ChangeBankBalance

Chat does NOT own vanilla 25% share slots. Those stay off.
A later holding-AI IPO can sit on top of this module.

Enable with openttd.enabled=true and set admin_password to the
server's network.admin_password.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from core.models import ExecuteRequest, MetricsSnapshot
from games.base import BaseGameIntegration
from games.openttd_admin import AdminClient
from games.openttd_market import OpenTTDMarket, company_price

log = logging.getLogger("games.openttd")

ROOT = Path(__file__).resolve().parent.parent


class OpenTTDIntegration(BaseGameIntegration):
    name = "openttd"

    def __init__(self, config: dict, store=None):
        super().__init__(config)
        ot = config.get("openttd") or {}
        self.enabled = bool(ot.get("enabled", False))
        self.host = str(ot.get("host") or "127.0.0.1")
        self.port = int(ot.get("admin_port") or 3977)
        self.password = str(ot.get("admin_password") or "")
        self.admin_name = str(ot.get("name") or "FridgeStreamCore")
        self.pounds_per_point = int(ot.get("pounds_per_point") or 1000)
        self.min_invest = int(ot.get("min_invest_points") or 10)
        self.max_invest = int(ot.get("max_invest_points") or 5000)
        self.host_company_id = ot.get("host_company_id")
        self.allow_host_invest = bool(ot.get("allow_host_invest", True))
        self.use_gamescript = bool(ot.get("use_gamescript", True))
        self.client: Optional[AdminClient] = None
        self.store = store
        self.market = OpenTTDMarket(ROOT / "data" / "stream_core.db")
        self.last_error = ""

    def overlay_catalog(self) -> list[dict]:
        core = self.config.get("core") or {}
        host = core.get("host") or "127.0.0.1"
        port = int(core.get("port") or 3850)
        base = f"http://{host}:{port}/overlay"
        return [
            {
                "name": "OpenTTD companies",
                "url": f"{base}/openttd.html",
                "notes": "Date, companies, cash, chat-funded totals",
            },
            {
                "name": "OpenTTD ticker",
                "url": f"{base}/openttd-ticker.html",
                "notes": "Thin tape for the bottom of the stream",
            },
            {
                "name": "OpenTTD market",
                "url": f"{base}/market-openttd.html",
                "notes": "HOST / OpenTTD listing",
            },
        ]

    async def start(self) -> None:
        if not self.enabled:
            log.info("OpenTTD integration disabled in config")
            return
        if not self.password:
            log.warning("openttd.admin_password is empty — Admin Port will not accept the login")
        self.client = AdminClient(
            host=self.host,
            port=self.port,
            password=self.password,
            name=self.admin_name,
            on_update=self._on_admin_update,
        )
        try:
            await self.client.start()
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("OpenTTD Admin Port not reachable yet: %s", exc)
        log.info("OpenTTD integration ready (admin=%s:%s)", self.host, self.port)

    async def stop(self) -> None:
        if self.client:
            await self.client.stop()
            self.client = None

    def _on_admin_update(self, kind: str, data: dict) -> None:
        if kind == "company_remove":
            log.info("OpenTTD company removed: %s", data.get("id"))

    async def health(self) -> bool:
        return bool(self.enabled and self.client and self.client.connected)

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        return

    def snapshot(self) -> dict:
        raw = self.client.snapshot() if self.client else {
            "connected": False,
            "companies": [],
            "date": "",
            "welcome": {},
        }
        funded = self.market.funded_totals()
        companies = []
        for c in raw.get("companies") or []:
            cid = int(c.get("id") or 0)
            fund = funded.get(cid) or {}
            companies.append({
                **c,
                "price": company_price(c),
                "chat_points": fund.get("points", 0),
                "chat_pounds": fund.get("pounds", 0),
                "chat_hits": fund.get("hits", 0),
            })
        return {
            "connected": bool(raw.get("connected")),
            "error": self.last_error,
            "date": raw.get("date") or "",
            "welcome": raw.get("welcome") or {},
            "companies": companies,
            "recent": self.market.recent(10),
            "pounds_per_point": self.pounds_per_point,
        }

    async def execute(self, req: ExecuteRequest) -> dict:
        if not self.enabled:
            return {"success": False, "error": "openttd integration disabled"}
        name = (req.command_name or "").lower()
        args = list(req.args or [])
        user = req.user.username if req.user else "chat"
        platform = req.platform.value if req.platform else "unknown"
        display = ""
        if req.user:
            display = req.user.display_name or req.user.username

        handlers = {
            "companies": self._cmd_companies,
            "tickers": self._cmd_companies,
            "quote": self._cmd_quote,
            "invest": self._cmd_invest,
            "ottdfund": self._cmd_fund,
            "ottdsay": self._cmd_say,
            "ottdpause": self._cmd_pause,
            "ottdunpause": self._cmd_unpause,
        }
        fn = handlers.get(name)
        if not fn:
            return {"success": False, "error": f"unknown openttd command {name}"}
        try:
            return await fn(args, user=user, platform=platform, display=display, req=req)
        except Exception as exc:
            log.exception("openttd command %s", name)
            return {"success": False, "error": str(exc), "reply": str(exc)}

    def _companies(self) -> list[dict]:
        if not self.client:
            return []
        return list(self.client.companies.values())

    def _find_company(self, token: str) -> Optional[dict]:
        token = (token or "").strip()
        if not token:
            return None
        companies = self._companies()
        if token.isdigit():
            cid = int(token)
            for c in companies:
                if int(c.get("id", -1)) == cid:
                    return c
        low = token.lower()
        hits = [c for c in companies if low in str(c.get("name") or "").lower()]
        if len(hits) == 1:
            return hits[0]
        return hits[0] if hits else None

    async def _cmd_companies(self, args, **kw) -> dict:
        companies = self._companies()
        if not companies:
            text = "OpenTTD: no companies yet (is the Admin Port connected?)."
            return {"success": True, "reply": text}
        bits = []
        funded = self.market.funded_totals()
        for c in sorted(companies, key=lambda x: x.get("id", 0)):
            cid = int(c.get("id", 0))
            money = int(c.get("money") or 0)
            fund = funded.get(cid)
            extra = f" chat£{fund['pounds']:,}" if fund else ""
            bits.append(f"#{cid} {c.get('name') or '?'} £{money:,}{extra}")
        date = self.client.snapshot().get("date") if self.client else ""
        text = ("Date " + date + " | " if date else "") + " | ".join(bits[:8])
        return {"success": True, "reply": text, "companies": [c.get("id") for c in companies]}

    async def _cmd_quote(self, args, **kw) -> dict:
        if not args:
            return {"success": False, "error": "usage", "reply": "Usage: !quote <company id or name>"}
        c = self._find_company(args[0])
        if not c:
            return {"success": False, "reply": f"No company matching '{args[0]}'."}
        funded = self.market.funded_totals().get(int(c["id"])) or {}
        text = (
            f"#{c['id']} {c.get('name')}  cash £{int(c.get('money') or 0):,}  "
            f"loan £{int(c.get('loan') or 0):,}  vehicles {c.get('vehicle_total') or 0}  "
            f"tick {company_price(c)}  chat funded £{int(funded.get('pounds') or 0):,}"
        )
        return {"success": True, "reply": text}

    async def _cmd_fund(self, args, **kw) -> dict:
        totals = self.market.funded_totals()
        if not totals:
            return {"success": True, "reply": "Chat Fund is empty. !invest <id> <points> to seed a company."}
        parts = [
            f"#{v['company_id']} {v.get('company_name') or '?'} £{v['pounds']:,} ({v['points']} pts)"
            for v in totals.values()
        ]
        return {"success": True, "reply": "Chat Fund: " + " | ".join(parts[:6])}

    async def _cmd_say(self, args, **kw) -> dict:
        msg = " ".join(args).strip()
        if not msg:
            return {"success": False, "reply": "Usage: !ottdsay <message>"}
        if not self.client or not self.client.connected:
            return {"success": False, "reply": "Admin Port offline."}
        who = kw.get("display") or kw.get("user") or "chat"
        await self.client.say(f"[Fridge] {who}: {msg}")
        return {"success": True, "reply": "Sent to OpenTTD chat."}

    async def _cmd_pause(self, args, **kw) -> dict:
        if not self.client or not self.client.connected:
            return {"success": False, "reply": "Admin Port offline."}
        await self.client.rcon("pause")
        return {"success": True, "reply": "OpenTTD paused."}

    async def _cmd_unpause(self, args, **kw) -> dict:
        if not self.client or not self.client.connected:
            return {"success": False, "reply": "Admin Port offline."}
        await self.client.rcon("unpause")
        return {"success": True, "reply": "OpenTTD unpaused."}

    async def _cmd_invest(self, args, **kw) -> dict:
        if len(args) < 2:
            return {
                "success": False,
                "reply": f"Usage: !invest <company> <points>  ({self.pounds_per_point} £ per point, min {self.min_invest})",
            }
        c = self._find_company(args[0])
        if not c:
            return {"success": False, "reply": f"No company matching '{args[0]}'."}
        try:
            points = int(re.sub(r"[^0-9]", "", args[1]) or "0")
        except ValueError:
            points = 0
        if points < self.min_invest:
            return {"success": False, "reply": f"Minimum invest is {self.min_invest} points."}
        if points > self.max_invest:
            return {"success": False, "reply": f"Max invest per command is {self.max_invest} points."}

        cid = int(c["id"])
        if self.host_company_id is not None and not self.allow_host_invest:
            try:
                if cid == int(self.host_company_id):
                    return {"success": False, "reply": "Host company is not open for chat funding."}
            except (TypeError, ValueError):
                pass

        pounds = points * self.pounds_per_point
        user = kw.get("user") or "chat"
        platform = kw.get("platform") or "unknown"
        display = kw.get("display") or user
        req: ExecuteRequest = kw.get("req")

        spent_uid = None
        if self.store and req and req.user:
            uid = await self.store.get_or_create_user(
                platform, req.user.id, req.user.username, req.user.display_name or ""
            )
            spent_uid = uid
            # current balance
            bal_row = await self.store.get_user(uid)
            bal = int((bal_row or {}).get("points") or 0)
            if bal < points:
                return {"success": False, "reply": f"@{display} you have {bal} points, need {points}."}
            await self.store.adjust_points(uid, -points, reason=f"ottd invest #{cid}", source="openttd")
        elif self.store:
            log.info("invest without store user binding — recording only")

        injected = False
        payload = {
            "action": "invest",
            "company": cid,
            "pounds": pounds,
            "from": display,
            "points": points,
        }
        if self.use_gamescript and self.client and self.client.connected:
            try:
                await self.client.send_gamescript(payload)
                injected = True
            except Exception as exc:
                log.warning("gamescript inject failed: %s", exc)
                self.market.queue_injection(payload)
        else:
            self.market.queue_injection(payload)

        self.market.record_invest(
            platform=platform,
            username=user,
            user_id=spent_uid,
            company_id=cid,
            company_name=str(c.get("name") or ""),
            points=points,
            pounds=pounds,
            injected=injected,
        )
        if self.client and self.client.connected:
            note = "funded" if injected else "pledged"
            await self.client.say(
                f"[Fridge] {display} {note} £{pounds:,} into #{cid} {c.get('name')}"
            )
        status = "in-game cash sent" if injected else "queued until FridgeChatFund GS is loaded"
        text = f"@{display} invested {points} pts (£{pounds:,}) in #{cid} {c.get('name')} — {status}."
        return {"success": True, "reply": text, "points": points, "pounds": pounds, "company": cid}
