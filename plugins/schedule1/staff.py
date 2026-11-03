"""
Staff named after chatters: the streamer's botanists, chemists, packagers and cleaners carry chatter
names, and chat hears what "their" worker got done.

Chat: ``!staff`` joins the staff list (or says which worker you are and what it did this stream),
``!staff leave`` stops, ``!topstaff`` lists the busiest. Workers are handed out first come, first
served like customers (roster.py), but from their own list in the ``staff`` table, because a save
has only a handful of workers. Settings (``schedule1:``, plugin.json group "Staff"):

  staff_enabled        off by default
  staff_who            "subs" (subscribers / members only, the default) or "everyone"
  staff_one_job        a chatter is a customer or a worker, not both (default on)
  staff_announce       chat hears what workers did (default on)
  staff_announce_sec   at most one line per worker this often (seconds); jobs in between are added up
  staff_rotate_after_min  0 = off; with someone waiting, a worker changes hands after this many minutes

Game side: the mod's GET /crew lists the workers ("staff": [{"id", "first", "last", "type",
"property", "shown"}]); POST /crewnames {"staff": {id: {"first", "last"}}} puts the names on them
(fridge-schedule1/mod/Crew.cs, which also takes the names off while the game saves, so they never
reach the save file); event "staff_job" {"id", "job"} says one job ended ("harvested a plant").
Host only: in a friend's co-op game the host's workers aren't ours to name.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Optional

from .bridge import BridgeError
from .feature import Feature, who_of
from .roster import clean_name

log = logging.getLogger("plugins.schedule1")

SCHEMA = """
CREATE TABLE IF NOT EXISTS staff (
    key          TEXT PRIMARY KEY,          -- roster.person_key(): "<platform>:<user id or username>"
    platform     TEXT NOT NULL,
    user_id      TEXT NOT NULL DEFAULT '',
    username     TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    joined_at    REAL NOT NULL,             -- unix seconds; the waiting order
    emp_id       TEXT UNIQUE,               -- the worker's game id (mod GET /crew "staff" id), NULL = waiting
    assigned_at  REAL,
    jobs         INTEGER NOT NULL DEFAULT 0, -- jobs done by their workers, all time
    is_sub       INTEGER NOT NULL DEFAULT 0
);
"""

# The mod's worker types (Crew.cs TypeName) as chat words.
TYPE_WORDS = {"botanist": "botanist", "packager": "packager", "handler": "packager",
              "chemist": "chemist", "cleaner": "cleaner"}


def plan_staff(workers: list[dict], people: list[dict]) -> list[tuple[str, str]]:
    """Give waiting chatters a free worker: [(person key, worker id)], first come first served,
    workers in id order so the choice is the same every sync. ``people`` are staff table rows."""
    taken = {p["emp_id"] for p in people if p.get("emp_id")}
    free = sorted((w for w in workers if w.get("id") and w["id"] not in taken), key=lambda w: str(w["id"]))
    waiting = sorted((p for p in people if not p.get("emp_id")), key=lambda p: (p.get("joined_at") or 0, p["key"]))
    return [(p["key"], w["id"]) for p, w in zip(waiting, free)]


def staff_names(workers: list[dict], people: list[dict], name_style: str = "chatter",
                max_len: int = 24) -> dict[str, dict[str, str]]:
    """POST /crewnames "staff": {worker id: {"first", "last"}} for workers in the game now.
    ``name_style`` is the customers' setting: "chatter_last" keeps the worker's own last name."""
    by_id = {w["id"]: w for w in workers if w.get("id")}
    out: dict[str, dict[str, str]] = {}
    for p in people:
        w = by_id.get(p.get("emp_id") or "")
        first = clean_name(p.get("display_name") or "", p.get("username") or "", max_len) if w else ""
        if w and first:
            out[w["id"]] = {"first": first, "last": str(w.get("last") or "") if name_style == "chatter_last" else ""}
    return out


def job_summary(jobs: Counter) -> str:
    """ "harvested a plant x3, started a mix" from counted job words (most first)."""
    return ", ".join(f"{j} x{n}" if n > 1 else j for j, n in jobs.most_common(4))


class StaffRoster:
    """The staff table (same database as roster.Roster; ``db`` is ctx.db)."""

    def __init__(self, db):
        self.db = db

    async def setup(self) -> None:
        await self.db.script(SCHEMA)

    async def get(self, key: str) -> Optional[dict]:
        return await self.db.fetchone("SELECT * FROM staff WHERE key = ?", (key,))

    async def all(self) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM staff ORDER BY emp_id IS NULL, joined_at, key")

    async def by_emp(self, emp_id: str) -> Optional[dict]:
        return await self.db.fetchone("SELECT * FROM staff WHERE emp_id = ?", (emp_id,))

    async def join(self, platform: str, user_id: str, username: str, display_name: str, is_sub: bool,
                   key: str) -> tuple[dict, bool]:
        row = await self.get(key)
        if row:
            await self.db.execute("UPDATE staff SET display_name = ?, is_sub = ? WHERE key = ?",
                                  (display_name or row["display_name"], int(bool(is_sub)), key))
            return await self.get(key), False
        await self.db.execute(
            "INSERT INTO staff (key, platform, user_id, username, display_name, joined_at, is_sub)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, platform, str(user_id or ""), username.lower(), display_name or username, time.time(), int(bool(is_sub))))
        return await self.get(key), True

    async def leave(self, key: str) -> bool:
        before = await self.get(key)
        await self.db.execute("DELETE FROM staff WHERE key = ?", (key,))
        return before is not None

    async def assign(self, pairs: list[tuple[str, str]]) -> None:
        now = time.time()
        for key, emp in pairs:
            await self.db.execute("UPDATE staff SET emp_id = ?, assigned_at = ? WHERE key = ? AND emp_id IS NULL",
                                  (emp, now, key))

    async def release(self, key: str, requeue: bool = False) -> None:
        """Off their worker (fired, or a shift ended). ``requeue`` = back of the line as of now."""
        if requeue:
            await self.db.execute("UPDATE staff SET emp_id = NULL, assigned_at = NULL, joined_at = ? WHERE key = ?",
                                  (time.time(), key))
        else:
            await self.db.execute("UPDATE staff SET emp_id = NULL, assigned_at = NULL WHERE key = ?", (key,))

    async def add_jobs(self, key: str, n: int) -> None:
        await self.db.execute("UPDATE staff SET jobs = jobs + ? WHERE key = ?", (int(n), key))

    async def top(self, n: int = 3) -> list[dict]:
        return await self.db.fetchall("SELECT * FROM staff WHERE jobs > 0 ORDER BY jobs DESC LIMIT ?", (int(n),))

    async def remove_where(self, keep) -> list[dict]:
        gone = [r for r in await self.all() if not keep(r)]
        for r in gone:
            await self.db.execute("DELETE FROM staff WHERE key = ?", (r["key"],))
        return gone


class Staff(Feature):
    """!staff / !topstaff, handing out workers, sending their names, and the "what they did" lines."""

    def __init__(self, plugin):
        super().__init__(plugin)
        self.roster: Optional[StaffRoster] = None
        self._sent: Optional[dict] = None       # last "staff" names sent (POST /crewnames)
        self._sent_boot = ""
        # person key -> (Counter of job words not yet said in chat, time.monotonic() of the last line)
        self._pending: dict[str, Counter] = {}
        self._said_at: dict[str, float] = {}
        self.session_jobs: Counter = Counter()  # person key -> jobs since Stream Core started (!staff)

    async def setup(self) -> None:
        self.roster = StaffRoster(self.p.ctx.db)
        await self.roster.setup()

    def on(self) -> bool:
        return bool(self.s().get("staff_enabled"))

    # ---- chat commands

    async def execute(self, name: str, req) -> Optional[dict]:
        if name not in ("staff", "topstaff") or req.user is None:
            return None
        if name == "topstaff":
            top = await self.roster.top(3)
            if not top:
                return {"success": True, "reply": "No chatter-worker has done a job yet."}
            return {"success": True, "reply": "Busiest staff: " + " | ".join(
                f"{i}. {clean_name(r['display_name'], r['username'])} ({r['jobs']} jobs)" for i, r in enumerate(top, 1))}
        u = req.user
        plat, key, who = who_of(req)
        arg = (req.args[0].lower() if req.args else "")
        if arg in ("leave", "quit", "stop", "remove"):
            gone = await self.roster.leave(key)
            self.p._wake.set()
            return {"success": True, "reply": f"@{who} you're off the staff list." if gone
                    else f"@{who} you weren't on the staff list."}
        if not self.on():
            return {"success": True, "reply": "Chatter staff is switched off."}
        if (why := self.host_only()):
            return {"success": True, "reply": f"@{who} {why}."}
        if self.p.is_hidden(plat, u.id, u.username, u.display_name):
            return {"success": True}
        if not who:
            return {"success": True, "reply": "That name can't be shown in the game, sorry."}
        is_sub = bool(getattr(u, "is_subscriber", False))
        row = await self.roster.get(key)
        if row is None:
            if str(self.s().get("staff_who") or "subs") == "subs" and not is_sub:
                return {"success": True, "reply": f"@{who} only subscribers / members can be staff."}
            if self.s().get("staff_one_job", True) and await self.p.roster.get(key):
                return {"success": True, "reply": f"@{who} you're already on the customer list "
                                                  f"(!customer leave first to be staff instead)."}
        row, new = await self.roster.join(plat, u.id, u.username, u.display_name, is_sub, key)
        self.p._wake.set()
        if row["emp_id"]:
            w = self.worker(row["emp_id"])
            done = self.session_jobs.get(key, 0)
            return {"success": True, "reply": f"@{who} you're the streamer's {self.type_word(w)}"
                                              f"{' at ' + w['property'] if w and w.get('property') else ''}: "
                                              f"{done} job{'s' if done != 1 else ''} this stream, {row['jobs']} in all."
                                              " (!staff leave to stop)"}
        waiting = [r for r in await self.roster.all() if not r["emp_id"]]
        place = next((i for i, r in enumerate(waiting, 1) if r["key"] == key), 0)
        return {"success": True, "reply": (f"@{who} you're on the staff list (#{place}). Your name goes on the "
                                           "next free worker." if new else
                                           f"@{who} you're #{place} on the staff waiting list.")}

    # ---- helpers
    def worker(self, emp_id: str) -> Optional[dict]:
        return next((w for w in self.p.crew.get("staff") or [] if w["id"] == emp_id), None)

    @staticmethod
    def type_word(w: Optional[dict]) -> str:
        return TYPE_WORDS.get(str((w or {}).get("type") or "").lower(), "worker")

    # ---- loop

    async def tick(self) -> None:
        if self.roster is None or self.p.bridge is None:
            return
        crew = self.p.crew
        if not self.on():
            if self._sent:                       # switched off: give everyone their own name back
                await self._send({})
            return
        if self.p.role == "client" or not crew.get("loaded"):
            return
        workers = crew.get("staff") or []
        # hidden / red-flagged chatters lose their worker straight away
        await self.roster.remove_where(lambda r: not self.p.is_hidden(r["platform"], r["user_id"], r["username"],
                                                                     r["display_name"]))
        people = await self.roster.all()
        present = {w["id"] for w in workers}
        for r in people:
            if r["emp_id"] and r["emp_id"] not in present:
                # the worker was fired (or is gone from this save): back on the list
                await self.roster.release(r["key"])
                await self.p._say_to(r, f"{clean_name(r['display_name'], r['username'])}'s worker left the "
                                        f"streamer's staff; back on the staff waiting list.")
        people = await self.roster.all()
        mins = self.num("staff_rotate_after_min", 0, 0)
        if mins > 0 and any(not r["emp_id"] for r in people):
            now = time.time()
            due = sorted((r for r in people if r["emp_id"] and r["assigned_at"] and now - r["assigned_at"] >= mins * 60),
                         key=lambda r: r["assigned_at"])
            for r in due[:sum(1 for x in people if not x["emp_id"])]:
                await self.roster.release(r["key"], requeue=True)
            if due:
                people = await self.roster.all()
        pairs = plan_staff(workers, people)
        if pairs:
            await self.roster.assign(pairs)
            people = await self.roster.all()
            if self.s().get("announce_new", True):
                rows = {r["key"]: r for r in people}
                for key, emp in pairs:
                    r, w = rows.get(key), self.worker(emp)
                    if r:
                        await self.p._say_to(r, f"{clean_name(r['display_name'], r['username'])} is now the streamer's "
                                                f"{self.type_word(w)}{' at ' + w['property'] if w and w.get('property') else ''}.")
        s = self.s()
        names = staff_names(workers, people, str(s.get("name_style") or "chatter"), int(s.get("max_name_len") or 24))
        await self._send(names)
        await self._flush_jobs()

    async def _send(self, names: dict) -> None:
        boot = str(self.p._boot or "")
        if names == self._sent and boot == self._sent_boot:
            return
        try:
            await self.p.bridge.crew_names(staff=names)
        except BridgeError as exc:
            log.info("Schedule I: staff names not sent: %s", exc)
            return
        self._sent, self._sent_boot = names, boot

    # ---- jobs

    async def handle_event(self, ev: dict) -> bool:
        if ev.get("type") != "staff_job":
            return False
        row = await self.roster.by_emp(str(ev.get("id") or ""))
        if row is None:
            return True                           # a worker without a chatter name: nothing to say
        await self.roster.add_jobs(row["key"], 1)
        self.session_jobs[row["key"]] += 1
        job = str(ev.get("job") or "finished a job")
        self._pending.setdefault(row["key"], Counter())[job] += 1
        return True

    async def _flush_jobs(self) -> None:
        """Say what each chatter's worker did, at most once per ``staff_announce_sec`` per chatter."""
        if not self._pending:
            return
        if not self.s().get("staff_announce", True):
            self._pending.clear()
            return
        every = self.num("staff_announce_sec", 120, 0)
        now = time.monotonic()
        for key in list(self._pending):
            if now - self._said_at.get(key, -1e9) < every:
                continue
            jobs = self._pending.pop(key)
            row = await self.roster.get(key)
            if not row or not row["emp_id"] or self.p.is_hidden(row["platform"], row["user_id"], row["username"],
                                                                 row["display_name"]):
                continue
            self._said_at[key] = now
            who = clean_name(row["display_name"], row["username"])
            await self.p._say_to(row, f"{who} (the streamer's {self.type_word(self.worker(row['emp_id']))}): "
                                      f"{job_summary(jobs)}.")

    # ---- page
    async def snapshot(self) -> list[dict]:
        out = []
        for r in await self.roster.all():
            w = self.worker(r["emp_id"] or "") if r["emp_id"] else None
            out.append({"key": r["key"], "platform": r["platform"], "name": clean_name(r["display_name"], r["username"]),
                        "worker": f"{w.get('first', '')} {w.get('last', '')}".strip() if w else "",
                        "type": self.type_word(w) if w else "", "property": (w or {}).get("property") or "",
                        "jobs": r["jobs"], "session_jobs": self.session_jobs.get(r["key"], 0)})
        return out
