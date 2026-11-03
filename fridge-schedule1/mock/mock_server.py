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
  POST /mug                  !mug: answers with a "mug_result" event at once (World.mug_refusal refuses);
                             World.mug_end() fakes the "mug_outcome"
  POST /nudge                order nudge: "nudge_result" event at once (ok for met customers)
  POST /find                 map marker request (kept in World.finds)
  POST /mixvote              chat's vote on a new mix's name (kept in World.mixvotes; at "done" the mock
                             "names" the mix with the first ranked name it hasn't got yet, World.products).
                             World.mix_button() fakes the naming screen's "Let chat name it" button
                             ("mix_vote" event), World.mix_stop() pressing it again / closing the screen
  GET /customers entries carry "status" / "status_text" like the mod's CustomerStatus.cs (simplified)
  POST /remote               co-op client join / leave (kept in World.remote_requests); World.role = "client"
                             makes the mock act as a guest in a friend's game
  GET  /crew                 3 workers, 2 recruited dealers, 2 met suppliers (like the mod's Crew.cs / Drops.cs)
  POST /crewnames            names on workers / dealers (World.staff_names / World.dealer_names)
  POST /drop                 cash in a dead drop: "drop_result" at once (World.drop_refusal refuses);
                             World.take_drop() fakes the pick-up ("drop_taken")
  POST /supplier             !tab / !supply: "supplier_result" at once (pays debt, or "delivers" to a drop)
  POST /mixpick              chat's ingredient vote (kept in World.mixpicks); World.mixpick_button() fakes the
                             mixing station's "Let chat pick" button, World.mixpick_stop() pressing it again
  World.staff_job(), dealer_sale(), dealer_robbed(), dealer_empty() fake the crew's game events

Fake world: 18 customers (2 of them Regulars), 6 already met. Every ``--every`` seconds (default 15) a met customer
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
    # two of FridgeRegulars' ten (ids as in regulars/Regulars.cs), not met yet
    ("fridge_regular_01", "Regular", "1"), ("fridge_regular_02", "Regular", "2"),
]
MET_AT_START = 6
PRODUCTS = ["OG Kush", "Sour Diesel", "Green Crack", "Granddaddy Purple", "Meth", "Cocaine"]
# The crew (ids and fields as the mod's GET /crew): workers, recruited dealers, suppliers.
STAFF = [("emp_botanist_1", "Dave", "Miller", "botanist", "Barn"),
         ("emp_chemist_1", "Rosa", "Diaz", "chemist", "Barn"),
         ("emp_packager_1", "Tom", "Ng", "packager", "Bungalow")]
DEALERS = [("benji_coleman", "Benji", "Coleman"), ("molly_presley", "Molly", "Presley")]
SUPPLIERS = [("albert_hoover", "Albert", "Hoover", 300.0, ["OG Kush Seed", "Sour Diesel Seed"]),
             ("shirley_watts", "Shirley", "Watts", 0.0, ["Pseudo"])]
INGREDIENTS = ["Addy", "Banana", "Battery", "Chili", "Cuke", "Donut", "Energy Drink", "Flu Medicine", "Gasoline",
               "Horse Semen", "Iodine", "Mega Bean", "Motor Oil", "Mouth Wash", "Paracetamol", "Viagra"]


class World:
    """The fake game. Thread-safe: the HTTP threads and the ticker thread share it."""

    def __init__(self, seed: int | None = None):
        self.lock = threading.Lock()
        self.rand = random.Random(seed)
        self.boot = uuid.uuid4().hex[:12]
        self.customers = [
            {"id": cid, "first": f, "last": l, "unlocked": i < MET_AT_START,
             "regular": cid.startswith("fridge_regular_")}      # like the mod's CustomerInfo.regular
            for i, (cid, f, l) in enumerate(CUSTOMERS)
        ]
        self.names: dict[str, dict] = {}     # id -> {"first", "last"} Core asked for
        self.events: list[dict] = []
        self.seq = 0
        self.pending: list[tuple[float, dict]] = []   # (due time, deal event) for orders in flight
        self.board: dict = {"named": [], "waiting": [], "top": []}   # last POST /board
        self.notices: list[dict] = []                 # every POST /notify, oldest first ({"title", "text"})
        self.alert_cards: list[dict] = []             # stream alerts as the mod's Alerts tab gets them
        # co-op: "host" like a game hosting / played alone, "client" like a guest in a friend's game
        # (then the board is the host's, set by tests, and /names + /board answer 409 like the real mod)
        self.role = "host"
        self.mugs: list[dict] = []                    # every POST /mug
        self.mug_refusal = ""                         # set to refuse the next muggings with this text
        self.remote_requests: list[dict] = []         # every POST /remote (client joins / leaves)
        self.nudges: list[str] = []                   # npc ids from POST /nudge
        self.finds: list[dict] = []                   # every POST /find
        self.mixvotes: list[dict] = []                # every POST /mixvote (the vote's state as the mod gets it)
        self.products: list[str] = ["OG Kush", "Sour Diesel"]   # product names "in the save"
        # crew (GET /crew) and what Core asked for
        self.staff = [{"id": i, "first": f, "last": l, "type": t, "property": prop} for i, f, l, t, prop in STAFF]
        self.dealers = [{"id": i, "first": f, "last": l, "cash": 0.0, "stock": 20, "customers": 3} for i, f, l in DEALERS]
        self.suppliers = [{"id": i, "first": f, "last": l, "unlocked": True, "debt": d, "goods": g}
                          for i, f, l, d, g in SUPPLIERS]
        self.staff_names: dict[str, dict] = {}        # last POST /crewnames "staff"
        self.dealer_names: dict[str, dict] = {}       # last POST /crewnames "dealers"
        self.drops: list[dict] = []                   # every POST /drop (and supplier deliveries), with "where"
        self.drop_refusal = ""                        # set to refuse the next drops with this text
        self.supplier_requests: list[dict] = []       # every POST /supplier
        self.mixpicks: list[dict] = []                # every POST /mixpick

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
            return {"loaded": True, "boot": self.boot, "source": "mock", "role": self.role, "board": self.board,
                    "customers": [dict(c, shown=self.shown(c), **self.status(c)) for c in self.customers]}

    @staticmethod
    def status(cust: dict) -> dict:
        """Like the mod's CustomerStatus.Describe, simplified: met customers always "waiting"."""
        if not cust["unlocked"]:
            return {"status": "locked", "status_text": "not met yet: walk up and offer a sample"}
        return {"status": "waiting", "status_text": "next order expected today around 18:00 (in about 3 in-game hours)"}

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
            if body.get("kind") and body.get("kind") != "system":
                # what the real mod keeps in its Alerts tab: the whole body, look included
                self.alert_cards.append(dict(body))
        return 200, {"success": True}

    def mug(self, body: dict) -> dict:
        """POST /mug: like the real mod, answer with a "mug_result" event (goons sent, or why not)."""
        with self.lock:
            self.mugs.append(body)
            ok = not self.mug_refusal
            self.add_event({"type": "mug_result", "mug": int(body.get("id") or 0), "ok": ok,
                            "msg": "" if ok else self.mug_refusal})
        return {"success": True, "role": self.role}

    def remote(self, body: dict) -> tuple[int, dict]:
        """POST /remote: a co-op client's join / leave for the host (kept for tests)."""
        if body.get("type") not in ("join", "leave"):
            return 400, {"success": False, "error": "type must be join or leave"}
        with self.lock:
            self.remote_requests.append(body)
        return 200, {"success": True, "role": self.role}

    def nudge(self, body: dict) -> dict:
        """POST /nudge: answer with "nudge_result" at once (the real mod waits a few seconds)."""
        npc = str(body.get("npc") or "")
        with self.lock:
            self.nudges.append(npc)
            cust = next((c for c in self.customers if c["id"] == npc), None)
            ok = bool(cust and cust["unlocked"])
            self.add_event({"type": "nudge_result", "npc": npc, "ok": ok,
                            "msg": "" if ok else "not met yet" if cust else "customer not in this save"})
        return {"success": True, "role": self.role}

    def find(self, body: dict) -> dict:
        """POST /find: the real mod puts a map marker on the customer; the mock only remembers it."""
        with self.lock:
            self.finds.append(body)
        return {"success": True, "role": self.role}

    def mixvote(self, body: dict) -> dict:
        """POST /mixvote: like MixNamer.cs at state "done", use the first ranked name not taken yet."""
        with self.lock:
            self.mixvotes.append(body)
            if body.get("state") == "done":
                for name in body.get("ranked") or []:
                    if name and name not in self.products:
                        self.products.append(name)
                        break
        return {"success": True}

    # ---- crew, drops, suppliers, ingredient vote (the mod's Crew.cs, Drops.cs, MixPicker.cs)

    def crew(self) -> dict:
        """GET /crew: own names in "first" / "last", the name on screen in "shown"."""
        def shown(x: dict, names: dict) -> str:
            n = names.get(x["id"])
            return f"{n['first']} {n['last']}".strip() if n else f"{x['first']} {x['last']}"
        with self.lock:
            return {"loaded": True, "boot": self.boot,
                    "staff": [dict(x, shown=shown(x, self.staff_names)) for x in self.staff],
                    "dealers": [dict(x, shown=shown(x, self.dealer_names)) for x in self.dealers],
                    "suppliers": [{k: v for k, v in x.items() if k != "goods"} for x in self.suppliers]}

    def crew_names(self, body: dict) -> dict:
        """POST /crewnames: a list that's sent replaces that list; one left out stays as it was."""
        with self.lock:
            if isinstance(body.get("staff"), dict):
                self.staff_names = {k: dict(v) for k, v in body["staff"].items() if isinstance(v, dict)}
            if isinstance(body.get("dealers"), dict):
                self.dealer_names = {k: dict(v) for k, v in body["dealers"].items() if isinstance(v, dict)}
        return {"success": True}

    def drop(self, body: dict) -> dict:
        """POST /drop: answer "drop_result" at once (the real mod picks a dead drop and fills it)."""
        with self.lock:
            ok = not self.drop_refusal
            where = "the dead drop behind the motel"
            if ok:
                self.drops.append(dict(body, where=where))
            self.add_event({"type": "drop_result", "drop": int(body.get("id") or 0), "ok": ok,
                            "msg": "" if ok else self.drop_refusal, "where": where if ok else ""})
        return {"success": True}

    def supplier(self, body: dict) -> dict:
        """POST /supplier: "pay" lowers the debt (never below 0), "deliver" fills a drop with goods."""
        with self.lock:
            self.supplier_requests.append(body)
            sup = next((x for x in self.suppliers if x["id"] == body.get("supplier")), None)
            ev = {"type": "supplier_result", "req": int(body.get("id") or 0), "ok": False, "msg": "", "paid": 0,
                  "debt": 0, "where": "", "what": ""}
            if sup is None or not sup["unlocked"]:
                ev["msg"] = "the streamer hasn't met that supplier"
            elif body.get("action") == "pay":
                paid = min(float(body.get("amount") or 0), sup["debt"])
                if paid <= 0:
                    ev["msg"] = "nothing is owed"
                else:
                    sup["debt"] -= paid
                    ev.update(ok=True, paid=paid, debt=sup["debt"])
            elif body.get("action") == "deliver":
                what = f"{int(body.get('qty') or 1)}x {sup['goods'][0]}"
                self.drops.append({"id": int(body.get("id") or 0), "by": body.get("by"), "what": what,
                                   "where": "the dead drop under the bridge"})
                ev.update(ok=True, where="the dead drop under the bridge", what=what)
            else:
                ev["msg"] = "action must be pay or deliver"
            self.add_event(ev)
        return {"success": True}

    def mixpick(self, body: dict) -> dict:
        with self.lock:
            self.mixpicks.append(body)
        return {"success": True}

    def take_drop(self, drop_id: int) -> dict:
        """The streamer emptied a drop (cash drop or supplier delivery)."""
        with self.lock:
            return self.add_event({"type": "drop_taken", "drop": int(drop_id)})

    def mixpick_button(self, carried: list[str] | None = None, product: str = "OG Kush") -> dict:
        """The streamer pressed "Let chat pick" on a mixing station (fields as MixPicker.cs sends)."""
        with self.lock:
            have = carried if carried is not None else ["Cuke", "Banana", "Gasoline"]
            # "nearby" / "owned": in storage near the station / at any owned property (IngredientSources.cs)
            return self.add_event({"type": "mixpick", "product": product, "carried": have,
                                   "nearby": ["Iodine"], "owned": ["Iodine", "Mega Bean"],
                                   "all": list(INGREDIENTS)})

    def mixpick_stop(self) -> dict:
        with self.lock:
            return self.add_event({"type": "mixpick_stop"})

    def staff_job(self, emp_id: str, job: str = "harvested a plant") -> dict:
        with self.lock:
            return self.add_event({"type": "staff_job", "id": emp_id, "job": job})

    def dealer_sale(self, dealer_id: str, amount: float, deals: int = 1) -> dict:
        with self.lock:
            return self.add_event({"type": "dealer_sale", "id": dealer_id, "amount": float(amount), "deals": deals})

    def dealer_robbed(self, dealer_id: str, cash: float, items: int = 0) -> dict:
        with self.lock:
            return self.add_event({"type": "dealer_robbed", "id": dealer_id, "cash": float(cash), "items": items})

    def dealer_empty(self, dealer_id: str) -> dict:
        with self.lock:
            return self.add_event({"type": "dealer_empty", "id": dealer_id})

    # ---- the fake game's activity (also called straight from tests)

    def mix_button(self, game_names: list[str] | None = None) -> dict:
        """The streamer pressed "Let chat name it" on the naming screen (fields as MixNamer.cs sends)."""
        with self.lock:
            return self.add_event({"type": "mix_vote", "game_names": game_names or ["Hazy Kush", "Cosmic Dream", "Zesty Cake"],
                                   "taken": list(self.products), "effects": ["Energizing", "Munchies"],
                                   "value": "$64", "current": (game_names or ["Hazy Kush"])[0]})

    def mix_stop(self, reason: str = "button") -> dict:
        """The streamer stopped chat's vote: "button" (pressed it again) or "closed" (left the screen)."""
        with self.lock:
            return self.add_event({"type": "mix_vote_stop", "reason": reason})


    def mug_end(self, mug_id: int, outcome: str) -> dict:
        """How a mugging ended: "won" (streamer beat the goons), "lost" or "left"."""
        with self.lock:
            return self.add_event({"type": "mug_outcome", "mug": int(mug_id), "outcome": outcome})

    def remote_event(self, kind: str, **fields) -> dict:
        """Host: a co-op friend's chatter joined / left in the friend's chat ("remote_join" / "remote_leave")."""
        with self.lock:
            return self.add_event({"type": kind, **fields})

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
            elif url.path == "/crew":
                self._send(200, world.crew())
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
            if path not in ("/names", "/board", "/notify", "/mug", "/remote", "/nudge", "/find", "/mixvote",
                            "/crewnames", "/drop", "/supplier", "/mixpick"):
                self._send(404, {"success": False, "error": "not found"})
                return
            if path in ("/names", "/board", "/crewnames") and world.role == "client":
                self._send(409, {"success": False, "error": "this game is a co-op client: the host decides names"})
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
            elif path == "/mug":
                print(f"mugging asked by {body.get('by')} ({body.get('goons')} goons)")
                self._send(200, world.mug(body))
            elif path == "/nudge":
                print(f"order nudge for {body.get('npc')}")
                self._send(200, world.nudge(body))
            elif path == "/mixvote":
                print(f"mix name vote: {body.get('state')} {[o.get('name') for o in body.get('options') or []]}")
                self._send(200, world.mixvote(body))
            elif path == "/crewnames":
                print(f"crew names: staff {list((body.get('staff') or {}).keys())} dealers {list((body.get('dealers') or {}).keys())}")
                self._send(200, world.crew_names(body))
            elif path == "/drop":
                print(f"cash drop: ${body.get('cash')} from {body.get('by')} ({body.get('note')!r})")
                self._send(200, world.drop(body))
            elif path == "/supplier":
                print(f"supplier {body.get('supplier')}: {body.get('action')} for {body.get('by')}")
                self._send(200, world.supplier(body))
            elif path == "/mixpick":
                print(f"ingredient vote: {body.get('state')} {[o.get('name') for o in body.get('options') or []]}")
                self._send(200, world.mixpick(body))
            elif path == "/find":
                print(f"map marker on {body.get('npc')} ({body.get('by')})")
                self._send(200, world.find(body))
            elif path == "/remote":
                code, result = world.remote(body)
                print(f"co-op {body.get('type')}: {body.get('username')} ({body.get('platform')})")
                self._send(code, result)
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
