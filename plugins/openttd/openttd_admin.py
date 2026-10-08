"""
Minimal OpenTTD Admin Port client (asyncio).

Speaks the documented admin protocol enough to:
  - log in
  - subscribe to date / companies / economy
  - run rcon
  - send a Game Script JSON blob (for FridgeChatFund)

Does not require pyOpenTTDAdmin. Compatible with vanilla and JGRPP.
Default port: 3977.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from typing import Callable, Optional

log = logging.getLogger("plugins.openttd.admin")

# Client → server
ADMIN_JOIN = 0
ADMIN_QUIT = 1
ADMIN_UPDATE_FREQUENCY = 2
ADMIN_POLL = 3
ADMIN_CHAT = 4
ADMIN_RCON = 5
ADMIN_GAMESCRIPT = 8

# Server → client
SERVER_FULL = 100
SERVER_BANNED = 101
SERVER_ERROR = 102
SERVER_PROTOCOL = 103
SERVER_WELCOME = 104
SERVER_NEWGAME = 105
SERVER_SHUTDOWN = 106
SERVER_DATE = 107
SERVER_CLIENT_JOIN = 108
SERVER_CLIENT_INFO = 109
SERVER_CLIENT_UPDATE = 110
SERVER_CLIENT_QUIT = 111
SERVER_CLIENT_ERROR = 112
SERVER_COMPANY_NEW = 113
SERVER_COMPANY_INFO = 114
SERVER_COMPANY_UPDATE = 115
SERVER_COMPANY_REMOVE = 116
SERVER_COMPANY_ECONOMY = 117
SERVER_COMPANY_STATS = 118
SERVER_CHAT = 119
SERVER_RCON = 120
SERVER_CONSOLE = 121
SERVER_GAMESCRIPT = 124
SERVER_RCON_END = 125

UPDATE_DATE = 0
UPDATE_CLIENT_INFO = 1
UPDATE_COMPANY_INFO = 2
UPDATE_COMPANY_ECONOMY = 3
UPDATE_COMPANY_STATS = 4
UPDATE_CHAT = 5

FREQ_POLL = 0x01
FREQ_DAILY = 0x02
FREQ_WEEKLY = 0x04
FREQ_MONTHLY = 0x08
FREQ_AUTOMATIC = 0x40


def _pack_str(s: str) -> bytes:
    return (s or "").encode("utf-8", errors="replace") + b"\x00"


def _read_str(buf: bytes, offset: int) -> tuple[str, int]:
    end = buf.find(b"\x00", offset)
    if end < 0:
        return buf[offset:].decode("utf-8", errors="replace"), len(buf)
    return buf[offset:end].decode("utf-8", errors="replace"), end + 1


def _build(ptype: int, payload: bytes) -> bytes:
    size = 3 + len(payload)
    return struct.pack("<HB", size, ptype) + payload


class AdminClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3977,
        password: str = "",
        name: str = "FridgeStreamCore",
        on_update: Optional[Callable[[str, dict], None]] = None,
    ):
        self.host = host
        self.port = int(port)
        self.password = password or ""
        self.name = name or "FridgeStreamCore"
        self.on_update = on_update
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.welcome: dict = {}
        self.date_raw: int = 0
        self.companies: dict[int, dict] = {}
        self._rcon_buf: list[str] = []
        self._rcon_fut: Optional[asyncio.Future] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def snapshot(self) -> dict:
        return {
            "connected": self.connected,
            "host": self.host,
            "port": self.port,
            "welcome": dict(self.welcome),
            "date_raw": self.date_raw,
            "date": _format_date(self.date_raw),
            "companies": [dict(c) for c in sorted(self.companies.values(), key=lambda x: x.get("id", 0))],
        }

    async def start(self) -> None:
        await self._connect()
        self._task = asyncio.create_task(self._read_loop(), name="openttd-admin-read")

    async def stop(self) -> None:
        self.connected = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self.writer:
            try:
                self.writer.write(_build(ADMIN_QUIT, b""))
                await self.writer.drain()
            except Exception:
                pass
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.writer = None
        self.reader = None

    async def _connect(self) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=5.0,
        )
        payload = _pack_str(self.password) + _pack_str(self.name) + _pack_str("1")
        self.writer.write(_build(ADMIN_JOIN, payload))
        await self.writer.drain()
        # First packets should be protocol + welcome
        for _ in range(8):
            pkt = await asyncio.wait_for(self._read_packet(), timeout=5.0)
            if pkt is None:
                break
            self._dispatch(*pkt)
            if pkt[0] == SERVER_WELCOME:
                break
        if not self.welcome:
            raise RuntimeError("Admin Port login failed (no welcome). Check admin password / port.")
        self.connected = True
        await self._subscribe()
        log.info("OpenTTD Admin Port connected %s:%s map=%s", self.host, self.port, self.welcome.get("map"))

    async def _subscribe(self) -> None:
        async def sub(kind: int, freq: int) -> None:
            self.writer.write(_build(ADMIN_UPDATE_FREQUENCY, struct.pack("<HH", kind, freq)))
            await self.writer.drain()

        await sub(UPDATE_DATE, FREQ_DAILY | FREQ_POLL)
        await sub(UPDATE_COMPANY_INFO, FREQ_AUTOMATIC | FREQ_POLL)
        await sub(UPDATE_COMPANY_ECONOMY, FREQ_WEEKLY | FREQ_POLL)
        await sub(UPDATE_COMPANY_STATS, FREQ_WEEKLY | FREQ_POLL)
        await self.poll(UPDATE_DATE, 0)
        await self.poll(UPDATE_COMPANY_INFO, 0xFFFFFFFF)
        await self.poll(UPDATE_COMPANY_ECONOMY, 0xFFFFFFFF)

    async def poll(self, kind: int, extra: int = 0xFFFFFFFF) -> None:
        if not self.writer:
            return
        self.writer.write(_build(ADMIN_POLL, struct.pack("<BI", kind, extra & 0xFFFFFFFF)))
        await self.writer.drain()

    async def rcon(self, command: str, timeout: float = 4.0) -> str:
        if not self.writer or not self.connected:
            raise RuntimeError("Admin Port not connected")
        async with self._lock:
            loop = asyncio.get_running_loop()
            self._rcon_buf = []
            fut: asyncio.Future = loop.create_future()
            self._rcon_fut = fut
            self.writer.write(_build(ADMIN_RCON, _pack_str(command)))
            await self.writer.drain()
            try:
                await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                text = "\n".join(self._rcon_buf)
                self._rcon_fut = None
                return text
            return "\n".join(self._rcon_buf)

    async def say(self, message: str) -> None:
        msg = (message or "").replace('"', "'")[:400]
        try:
            await self.rcon(f'say "{msg}"')
        except Exception as exc:
            log.warning("openttd say failed: %s", exc)

    async def send_gamescript(self, payload: dict) -> None:
        if not self.writer or not self.connected:
            raise RuntimeError("Admin Port not connected")
        blob = json.dumps(payload, separators=(",", ":"))
        self.writer.write(_build(ADMIN_GAMESCRIPT, _pack_str(blob)))
        await self.writer.drain()

    async def _read_loop(self) -> None:
        try:
            while self.connected and self.reader:
                pkt = await self._read_packet()
                if pkt is None:
                    break
                self._dispatch(*pkt)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("OpenTTD Admin Port read loop ended")
            self.connected = False

    async def _read_packet(self) -> Optional[tuple[int, bytes]]:
        assert self.reader
        header = await self.reader.readexactly(3)
        size, ptype = struct.unpack_from("<HB", header)
        rest = size - 3
        payload = b""
        if rest > 0:
            payload = await self.reader.readexactly(rest)
        return ptype, payload

    def _dispatch(self, ptype: int, payload: bytes) -> None:
        if ptype == SERVER_WELCOME:
            name, off = _read_str(payload, 0)
            version, off = _read_str(payload, off)
            dedicated = payload[off] if off < len(payload) else 0
            off += 1
            map_name, off = _read_str(payload, off)
            self.welcome = {"server": name, "version": version, "dedicated": bool(dedicated), "map": map_name}
            self._emit("welcome", self.welcome)
        elif ptype == SERVER_DATE:
            if len(payload) >= 4:
                self.date_raw = struct.unpack_from("<I", payload)[0]
                self._emit("date", {"date_raw": self.date_raw, "date": _format_date(self.date_raw)})
        elif ptype in (SERVER_COMPANY_INFO, SERVER_COMPANY_NEW, SERVER_COMPANY_UPDATE):
            self._parse_company_info(payload)
        elif ptype == SERVER_COMPANY_ECONOMY:
            self._parse_economy(payload)
        elif ptype == SERVER_COMPANY_STATS:
            self._parse_stats(payload)
        elif ptype == SERVER_COMPANY_REMOVE:
            if payload:
                cid = payload[0]
                self.companies.pop(cid, None)
                self._emit("company_remove", {"id": cid})
        elif ptype == SERVER_RCON:
            # uint16 colour + string
            off = 2 if len(payload) >= 2 else 0
            msg, _ = _read_str(payload, off)
            if msg:
                self._rcon_buf.append(msg)
        elif ptype == SERVER_RCON_END:
            if self._rcon_fut and not self._rcon_fut.done():
                self._rcon_fut.set_result(True)
            self._rcon_fut = None
        elif ptype == SERVER_SHUTDOWN:
            self.connected = False
            self._emit("shutdown", {})
        elif ptype == SERVER_NEWGAME:
            self.companies.clear()
            self._emit("newgame", {})
        elif ptype == SERVER_ERROR:
            log.warning("Admin Port server error packet")

    def _parse_company_info(self, payload: bytes) -> None:
        if not payload:
            return
        cid = payload[0]
        name, off = _read_str(payload, 1)
        president, off = _read_str(payload, off)
        colour = payload[off] if off < len(payload) else 0
        off += 1
        passworded = payload[off] if off < len(payload) else 0
        off += 1
        year = 0
        if off + 4 <= len(payload):
            year = struct.unpack_from("<I", payload, off)[0]
            off += 4
        is_ai = payload[off] if off < len(payload) else 0
        rec = self.companies.setdefault(cid, {"id": cid})
        rec.update({
            "id": cid,
            "name": name or rec.get("name") or f"Company {cid}",
            "president": president,
            "colour": colour,
            "passworded": bool(passworded),
            "inaugurated": year,
            "ai": bool(is_ai),
        })
        self._emit("company", rec)

    def _parse_economy(self, payload: bytes) -> None:
        if not payload:
            return
        cid = payload[0]
        off = 1
        money = loan = income = 0
        # money/loan are int64 on modern protocol
        if off + 8 <= len(payload):
            money = struct.unpack_from("<q", payload, off)[0]
            off += 8
        if off + 8 <= len(payload):
            loan = struct.unpack_from("<q", payload, off)[0]
            off += 8
        if off + 8 <= len(payload):
            income = struct.unpack_from("<q", payload, off)[0]
        rec = self.companies.setdefault(cid, {"id": cid, "name": f"Company {cid}"})
        rec["money"] = money
        rec["loan"] = loan
        rec["income"] = income
        rec["value"] = money - loan
        self._emit("economy", rec)

    def _parse_stats(self, payload: bytes) -> None:
        if len(payload) < 9:
            return
        cid = payload[0]
        # 4 uint16 vehicle counts typically
        trains, road, ships, air = struct.unpack_from("<HHHH", payload, 1)
        rec = self.companies.setdefault(cid, {"id": cid, "name": f"Company {cid}"})
        rec["vehicles"] = {"trains": trains, "road": road, "ships": ships, "air": air}
        rec["vehicle_total"] = trains + road + ships + air
        self._emit("stats", rec)

    def _emit(self, kind: str, data: dict) -> None:
        if self.on_update:
            try:
                self.on_update(kind, data)
            except Exception:
                log.exception("openttd on_update")


def _format_date(raw: int) -> str:
    """OpenTTD date is days since 0000-01-01 with 365-day years (approx)."""
    if not raw:
        return ""
    year = raw // 365
    doy = raw % 365
    month = min(12, doy // 30 + 1)
    day = (doy % 30) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"
