"""
Who is (or wants to be) a customer in Schedule I, kept in the plugin's own database
(data/plugins/schedule1/schedule1.db).

One row per chatter in the ``people`` table. ``npc_id`` is the game's customer id
("kyle_cooley") the chatter's name is shown on, or NULL while they wait for a free customer.
Rows also count each chatter's deals and money spent (in-game dollars) for !customer and
!topcustomers.

The pure helpers at the top (clean_name, person_key, plan_assignments, plan_rotation,
desired_names) do no I/O, so the tests and plugin.py share them. plugin.py's sync loop calls
plan_rotation (shifts that are over go to the back of the line), then plan_assignments, then sends
desired_names(...) to the game mod's POST /names.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    key          TEXT PRIMARY KEY,          -- person_key(): "<platform>:<user id or username>"
    platform     TEXT NOT NULL,
    user_id      TEXT NOT NULL DEFAULT '',
    username     TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    joined_at    REAL NOT NULL,             -- unix seconds; waiting order is first come, first served
    npc_id       TEXT UNIQUE,               -- game customer id, NULL = waiting
    assigned_at  REAL,
    deals        INTEGER NOT NULL DEFAULT 0,
    spent        REAL NOT NULL DEFAULT 0,   -- in-game dollars paid in completed deals
    last_deal_at REAL,
    shift_deals  INTEGER NOT NULL DEFAULT 0, -- deals on the current customer (rotate_after_deals)
    is_sub       INTEGER NOT NULL DEFAULT 0  -- subscriber / member when last seen (rotate_keep_subs)
);
"""

# Columns added after the first release; setup() adds them to older databases. Keep in sync with SCHEMA.
ADDED_COLUMNS = [
    "ALTER TABLE people ADD COLUMN shift_deals INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE people ADD COLUMN is_sub INTEGER NOT NULL DEFAULT 0",
]

# Letters, digits and a few safe marks. The game's font may not have emoji or other scripts,
# so a display name with anything else falls back to the plain username.
_SAFE = re.compile(r"^[A-Za-z0-9 _.\-']+$")


def person_key(platform: str, user_id: str = "", username: str = "") -> str:
    """Stable id for a chatter: platform + account id (or username when the platform gave no id)."""
    plat = str(platform or "").lower().strip()
    who = str(user_id or "").strip() or str(username or "").lower().strip().lstrip("@")
    return f"{plat}:{who}"


def clean_name(display_name: str, username: str, max_len: int = 24) -> str:
    """The name shown in the game: display name when the font can show it, else username.

    max_len is the ``max_name_len`` setting (characters). Empty result means "no usable name".
    """
    max_len = max(3, int(max_len or 24))
    for cand in (display_name, username):
        s = " ".join(str(cand or "").split())
        if s and _SAFE.match(s):
            return s[:max_len].strip()
    # last resort: keep only the safe characters of the username
    s = re.sub(r"[^A-Za-z0-9_]", "", str(username or ""))
    return s[:max_len]


def plan_assignments(
    customers: Iterable[dict],
    people: Iterable[dict],
    *,
    prefer_unlocked: bool = True,
    max_named: int = 0,
) -> list[tuple[str, str]]:
    """Give waiting chatters a free customer. Returns [(person key, npc id), ...] to store.

    customers: the mod's GET /customers list ({"id", "unlocked", ...}).
    people: rows from the people table (npc_id None = waiting), any order.
    prefer_unlocked (setting): customers the streamer has already met get names first, so a new
      name shows up in the phone's contacts right away.
    max_named (setting): most customers carrying a chatter name at once, 0 = no limit.
    Chatters keep the customer they already have; waiting chatters go first come, first served.
    """
    people = list(people)
    taken = {p["npc_id"] for p in people if p.get("npc_id")}
    named = len(taken)
    free = [c for c in customers if c.get("id") and c["id"] not in taken]
    # unlocked first (when preferred), then by id so the choice is the same every sync
    free.sort(key=lambda c: (not c.get("unlocked") if prefer_unlocked else False, str(c["id"])))
    waiting = sorted((p for p in people if not p.get("npc_id")), key=lambda p: (p.get("joined_at") or 0, p["key"]))
    out: list[tuple[str, str]] = []
    for person, cust in zip(waiting, free):
        if max_named and named >= max_named:
            break
        out.append((person["key"], cust["id"]))
        named += 1
    return out


def plan_rotation(
    people: Iterable[dict],
    *,
    after_deals: int = 0,
    after_min: float = 0,
    keep_subs: bool = False,
    now: Optional[float] = None,
) -> list[str]:
    """Chatters whose shift on a customer is over. Returns person keys, longest-serving first.

    after_deals (setting rotate_after_deals): shift ends after this many deals on the customer.
    after_min (setting rotate_after_min): shift ends after this many minutes on the customer.
    0 turns a trigger off; with both off nobody rotates. keep_subs (rotate_keep_subs): subscribers /
    members keep their customer. Only as many shifts end as there are chatters waiting, so a
    customer never goes back to its own name just because a shift ran out.
    """
    people = list(people)
    waiting = sum(1 for p in people if not p.get("npc_id"))
    if waiting == 0 or (after_deals <= 0 and after_min <= 0):
        return []
    now = time.time() if now is None else now
    due = []
    for p in people:
        if not p.get("npc_id") or (keep_subs and p.get("is_sub")):
            continue
        by_deals = after_deals > 0 and int(p.get("shift_deals") or 0) >= after_deals
        assigned = p.get("assigned_at")       # None on very old rows: never due by time
        by_time = after_min > 0 and assigned is not None and now - float(assigned) >= after_min * 60
        if by_deals or by_time:
            due.append(p)
    due.sort(key=lambda p: (p.get("assigned_at") or 0, p["key"]))
    return [p["key"] for p in due[:waiting]]


def desired_names(
    customers: Iterable[dict],
    people: Iterable[dict],
    *,
    name_style: str = "chatter",
    max_len: int = 24,
) -> dict[str, dict[str, str]]:
    """The body for the mod's POST /names: {npc id: {"first": ..., "last": ...}}.

    Only customers present in the game right now are listed; the mod puts every other
    customer's own name back. name_style (setting): "chatter" = the chatter's name alone,
    "chatter_last" = chatter's name + the customer's own last name ("zackfan99 Cooley").
    """
    by_id = {c["id"]: c for c in customers if c.get("id")}
    out: dict[str, dict[str, str]] = {}
    for p in people:
        cust = by_id.get(p.get("npc_id") or "")
        if not cust:
            continue
        first = clean_name(p.get("display_name") or "", p.get("username") or "", max_len)
        if not first:
            continue
        last = str(cust.get("last") or "") if name_style == "chatter_last" else ""
        out[cust["id"]] = {"first": first, "last": last}
    return out


class Roster:
    """The people table. ``db`` is ctx.db (core.plugin_db.PluginDB); every call is async."""

    def __init__(self, db):
        self.db = db

    async def setup(self) -> None:
        await self.db.script(SCHEMA)
        for sql in ADDED_COLUMNS:
            try:
                await self.db.execute(sql)
            except Exception:
                pass                          # the column is already there

    async def get(self, key: str) -> Optional[dict]:
        return await self.db.fetchone("SELECT * FROM people WHERE key = ?", (key,))

    async def all(self) -> list[dict]:
        """Everyone, named customers first, then the waiting list in order."""
        return await self.db.fetchall(
            "SELECT * FROM people ORDER BY npc_id IS NULL, joined_at, key"
        )

    async def join(self, platform: str, user_id: str, username: str, display_name: str,
                   is_sub: Optional[bool] = None) -> tuple[dict, bool]:
        """Add a chatter to the waiting list. Returns (row, True) when new, (existing row, False) otherwise.

        An existing row only gets its display name and subscriber flag refreshed (people rename
        themselves, subs lapse). is_sub None = unknown (added by hand on the page): left as it was.
        """
        key = person_key(platform, user_id, username)
        row = await self.get(key)
        if row:
            sub = row["is_sub"] if is_sub is None else int(bool(is_sub))
            if (display_name and display_name != row["display_name"]) or sub != row["is_sub"]:
                await self.db.execute("UPDATE people SET display_name = ?, username = ?, is_sub = ? WHERE key = ?",
                                      (display_name or row["display_name"], username.lower(), sub, key))
                row = await self.get(key)
            return row, False
        await self.db.execute(
            "INSERT INTO people (key, platform, user_id, username, display_name, joined_at, is_sub)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, platform.lower(), str(user_id or ""), username.lower(), display_name or username, time.time(),
             int(bool(is_sub))),
        )
        return await self.get(key), True

    async def leave(self, key: str) -> bool:
        """Remove a chatter (their customer gets its own name back on the next sync)."""
        before = await self.get(key)
        await self.db.execute("DELETE FROM people WHERE key = ?", (key,))
        return before is not None

    async def requeue(self, key: str) -> bool:
        """Back of the waiting list: drop their customer (the next waiting chatter gets it on the
        next sync) and join again as of now. Deals and money spent are kept. The phone app's Swap
        and shift rotation (plan_rotation) both use this."""
        before = await self.get(key)
        if not before:
            return False
        await self.db.execute("UPDATE people SET npc_id = NULL, assigned_at = NULL, shift_deals = 0, joined_at = ?"
                              " WHERE key = ?", (time.time(), key))
        return True

    async def find_name(self, platform: str, name: str) -> Optional[dict]:
        """A row by platform + username or display name (stream alerts carry no account id)."""
        n = str(name or "").lower().lstrip("@")
        if not n:
            return None
        return await self.db.fetchone(
            "SELECT * FROM people WHERE platform = ? AND (username = ? OR LOWER(display_name) = ?)",
            (str(platform or "").lower(), n, n),
        )

    async def assign(self, pairs: list[tuple[str, str]]) -> None:
        """Store plan_assignments() results."""
        now = time.time()
        for key, npc_id in pairs:
            await self.db.execute("UPDATE people SET npc_id = ?, assigned_at = ?, shift_deals = 0"
                                  " WHERE key = ? AND npc_id IS NULL", (npc_id, now, key))

    async def by_npc(self, npc_id: str) -> Optional[dict]:
        return await self.db.fetchone("SELECT * FROM people WHERE npc_id = ?", (npc_id,))

    async def record_deal(self, npc_id: str, payment: float) -> Optional[dict]:
        """Count a completed deal for whoever carries this customer's name; returns their updated row."""
        row = await self.by_npc(npc_id)
        if not row:
            return None
        await self.db.execute(
            "UPDATE people SET deals = deals + 1, shift_deals = shift_deals + 1, spent = spent + ?, last_deal_at = ?"
            " WHERE key = ?",
            (max(0.0, float(payment or 0)), time.time(), row["key"]),
        )
        return await self.get(row["key"])

    async def position(self, key: str) -> int:
        """1-based place on the waiting list, 0 when not waiting."""
        row = await self.get(key)
        if not row or row["npc_id"]:
            return 0
        ahead = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM people WHERE npc_id IS NULL AND (joined_at < ? OR (joined_at = ? AND key < ?))",
            (row["joined_at"], row["joined_at"], key),
        )
        return int(ahead["n"]) + 1

    async def top(self, n: int = 3) -> list[dict]:
        """Best customers by money spent (only chatters with at least one deal)."""
        return await self.db.fetchall(
            "SELECT * FROM people WHERE deals > 0 ORDER BY spent DESC, deals DESC LIMIT ?", (int(n),)
        )

    async def counts(self) -> dict[str, int]:
        row = await self.db.fetchone(
            "SELECT SUM(npc_id IS NOT NULL) AS named, SUM(npc_id IS NULL) AS waiting FROM people"
        )
        return {"named": int(row["named"] or 0), "waiting": int(row["waiting"] or 0)}

    async def remove_where(self, keep: Any) -> list[dict]:
        """Delete every row for which keep(row) is False (used for hidden / red-flagged chatters)."""
        gone = [r for r in await self.all() if not keep(r)]
        for r in gone:
            await self.db.execute("DELETE FROM people WHERE key = ?", (r["key"],))
        return gone
