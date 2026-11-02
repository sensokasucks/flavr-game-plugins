#!/usr/bin/env python3
"""Dev stand-in for the FridgeSchedule1 MelonLoader mod. Same port and routes, no game needed.

Lets you test Stream Core's Schedule I plugin (plugins/schedule1) without Schedule I:

  GET  /customers            every customer, its own name and whether you've met them
  POST /names                names Core wants on customers (anything not listed gets its own name back)
  GET  /events?after=<seq>   orders ("contract"), finished deals ("deal") and new customers ("unlocked")
                             (the real mod also sends "app_remove" / "app_swap" from its phone app buttons;
                             World.app_button() fakes those for tests)
  POST /board                the lists Core wants in the phone app (kept in World.board, printed)
  POST /notify               a stream alert for the phone (kept in World.notices, printed)

Fake world: 16 customers, 6 already met. Every ``--every`` seconds (default 15) a met customer
texts an order, and the deal goes through a few seconds later; now and then you meet someone new.
Started by "START Schedule1 Mock.bat" (repo root) or "START Mock.bat" in this folder.

Same safety rules as the real mod (fridge-schedule1/mod/BridgeServer.cs): loopback only, requests
need ``X-Fridge-Core: 1``, anything with a browser ``Origin`` header is refused, and with
``--token`` set, ``X-Fridge-Token`` must match. Keep routes and field names in sync with
BridgeServer.cs and plugins/schedule1/bridge.py.
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Loopback only, and the same port as the real mod (Core's schedule1.bridge_url default).
HOST = "127.0.0.1"
PORT = 3857
MAX_EVENTS = 500       # events kept for GET /events (the real mod keeps the same number)

# (id, first, last) in the game's own id style. The first MET_AT_START count as already met.
CUSTOMERS = [
    ("kyle_cooley", "Kyle", "Cooley"), ("austin_steiner", "Austin", "Steiner"),
    ("beth_penn", "Beth", "Penn"), ("chloe_bowers", "Chloe", "Bowers"),
    ("jessi_waters", "Jessi", "Waters"), ("mick_lubbin", "Mick", "Lubbin"),
    ("ludwig_meyer", "Ludwig", "Meyer"), ("donna_martin", "Donna", "Martin"),
    ("geraldine_poon", "Geraldine", "Poon"), ("kathy_henderson", "Kathy", "Henderson"),
    ("peter_file", "Peter", "File"), ("sam_thompson", "Sam", "Thompson"),
    ("jeremy_wilkinson", "Jeremy", "Wilkinson"), ("charles_rowland", "Charles", "Rowland"),
    ("jerry_montero", "Jerry", "Montero"), ("doris_lubbin", "Doris", "Lubbin"),
]
MET_AT_START = 6
PRODUCTS = ["OG Kush", "Sour Diesel", "Green Crack", "Granddaddy Purple", "Meth", "Cocaine"]


class World:
    """The fake game. Thread-safe: the HTTP threads and the ticker thread share it."""

    def __init__(self, seed: int | None = None):
        self.lock = threading.Lock()
        self.rand = random.Random(seed)
        self.boot = uuid.uuid4().hex[:12]
        self.customers = [
            {"id": cid, "first": f, "last": l, "unlocked": i < MET_AT_START}
            for i, (cid, f, l) in enumerate(CUSTOMERS)
        ]
        self.names: dict[str, dict] = {}     # id -> {"first", "last"} Core asked for
        self.events: list[dict] = []
        self.seq = 0
        self.pending: list[tuple[float, dict]] = []   # (due time, deal event) for orders in flight
        self.board: dict = {"named": [], "waiting": [], "top": []}   # last POST /board
        self.notices: list[dict] = []                 # every POST /notify, oldest first

    def shown(self, cust: dict) -> str:
        """The name the game would show now (Core's name, else the customer's own)."""
        n = self.names.get(cust["id"])
        return f"{n['first']} {n['last']}".strip() if n else f"{cust['first']} {cust['last']}"

    def add_event(self, ev: dict) -> dict:
        self.seq += 1
        ev = {"seq": self.seq, "time": time.time(), **ev}
        self.events.append(ev)
        del self.events[:-MAX_EVENTS]
        return ev

    def snapshot(self) -> dict:
        with self.lock:
            return {"loaded": True, "boot": self.boot, "source": "mock",
                    "customers": [dict(c, shown=self.shown(c)) for c in self.customers]}

    def set_names(self, names: dict) -> dict:
        """POST /names: replace the whole set; unknown ids are reported back."""
        with self.lock:
            known = {c["id"] for c in self.customers}
            self.names = {k: {"first": str(v.get("first") or ""), "last": str(v.get("last") or "")}
                          for k, v in (names or {}).items() if k in known and isinstance(v, dict)}
            missing = [k for k in (names or {}) if k not in known]
        return {"success": True, "applied": len(self.names), "missing": missing}

    def events_after(self, after: int) -> dict:
        with self.lock:
            return {"boot": self.boot, "last": self.seq, "events": [e for e in self.events if e["seq"] > after]}

    def set_board(self, board: dict) -> dict:
        """POST /board: same three lists as BridgeServer.Rows reads."""
        with self.lock:
            self.board = {k: [r for r in (board.get(k) or []) if isinstance(r, dict)] for k in ("named", "waiting", "top")}
        return {"success": True}

    def notify(self, body: dict) -> tuple[int, dict]:
        """POST /notify: an alert the real mod would pop up on the phone."""
        text = str(body.get("text") or "")
        if not text:
            return 400, {"success": False, "error": "text is empty"}
        with self.lock:
            self.notices.append({"title": str(body.get("title") or ""), "text": text})
        return 200, {"success": True}

    # ---- the fake game's activity (also called straight from tests)

    def app_button(self, kind: str, key: str) -> dict:
        """The streamer pressed Remove ("app_remove") or Swap ("app_swap") in the phone app."""
        with self.lock:
            return self.add_event({"type": kind, "key": key})

    def order(self, cid: str | None = None, deal_after: float = 5.0) -> dict:
        """A met customer texts an order; its deal event follows ``deal_after`` seconds later."""
        with self.lock:
            met = [c for c in self.customers if c["unlocked"]]
            cust = next((c for c in self.customers if c["id"] == cid), None) if cid else self.rand.choice(met)
            qty = self.rand.randint(1, 8)
            product = self.rand.choice(PRODUCTS)
            payment = float(qty * self.rand.choice([25, 35, 40, 60]))
            base = {"id": cust["id"], "name": self.shown(cust), "qty": qty, "products": [product], "payment": payment}
            ev = self.add_event({"type": "contract", **base})
            self.pending.append((time.time() + deal_after, {"type": "deal", **base}))
            return ev

    def unlock_one(self) -> dict | None:
        with self.lock:
            locked = [c for c in self.customers if not c["unlocked"]]
            if not locked:
                return None
            cust = locked[0]
            cust["unlocked"] = True
            return self.add_event({"type": "unlocked", "id": cust["id"], "name": self.shown(cust)})

    def step(self, now: float | None = None) -> None:
        """Turn due orders into deals."""
        now = time.time() if now is None else now
        with self.lock:
            due = [ev for t, ev in self.pending if t <= now]
            self.pending = [(t, ev) for t, ev in self.pending if t > now]
            for ev in due:
                self.add_event(ev)


def make_handler(world: World, token: str = ""):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FridgeSchedule1Mock/0.1"

        def log_message(self, fmt, *args):   # quiet; the ticker prints what matters
            pass

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self) -> bool:
            # same rules as BridgeServer.Allowed(): no web pages, Core's header, token when set
            if self.headers.get("Origin"):
                self._send(403, {"success": False, "error": "web pages may not call this"})
                return False
            if self.headers.get("X-Fridge-Core") != "1":
                self._send(403, {"success": False, "error": "missing X-Fridge-Core header"})
                return False
            if token and self.headers.get("X-Fridge-Token") != token:
                self._send(403, {"success": False, "error": "wrong token"})
                return False
            return True

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/health", "/ping"):
                self._send(200, {"ok": True, "source": "mock"})
                return
            if not self._allowed():
                return
            if url.path == "/customers":
                self._send(200, world.snapshot())
            elif url.path == "/events":
                try:
                    after = int((parse_qs(url.query).get("after") or ["0"])[0])
                except ValueError:
                    after = 0
                self._send(200, world.events_after(after))
            else:
                self._send(404, {"success": False, "error": "not found"})

        def do_POST(self):
            if not self._allowed():
                return
            path = urlparse(self.path).path
            if path not in ("/names", "/board", "/notify"):
                self._send(404, {"success": False, "error": "not found"})
                return
            length = min(int(self.headers.get("Content-Length") or 0), 256 * 1024)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._send(400, {"success": False, "error": "bad JSON"})
                return
            if path == "/board":
                result = world.set_board(body)
                b = world.board
                print(f"phone app: {len(b['named'])} named, {len(b['waiting'])} waiting")
                self._send(200, result)
            elif path == "/notify":
                code, result = world.notify(body)
                if code == 200:
                    print(f"phone pop-up: {body.get('title')}: {body.get('text')}")
                self._send(code, result)
            else:
                result = world.set_names(body.get("names") or {})
                print(f"names: {len(world.names)} customer(s) renamed")
                self._send(200, result)

    return Handler


def make_server(world: World, port: int = PORT, token: str = "") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), make_handler(world, token))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--token", default="", help="same as schedule1.bridge_token in Core (optional)")
    ap.add_argument("--every", type=float, default=15.0, help="seconds between fake orders")
    args = ap.parse_args()

    world = World()
    server = make_server(world, args.port, args.token)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Schedule I mock mod on http://{HOST}:{args.port}/  (Ctrl+C to stop)")
    next_order = time.time() + args.every
    try:
        while True:
            time.sleep(0.5)
            world.step()
            if time.time() >= next_order:
                next_order = time.time() + args.every
                ev = world.order()
                print(f"order: {ev['name']} wants {ev['qty']}x {ev['products'][0]} for ${ev['payment']:.0f}")
                if world.rand.random() < 0.2 and (u := world.unlock_one()):
                    print(f"met a new customer: {u['name']}")
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
