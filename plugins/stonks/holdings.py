"""
Who owns which shares, kept in the plugin's own database (data/plugins/stonks/stonks.db).

Shares are stored as milli-shares (1000 = one share). Points stay in Stream Core: buying,
selling and dividends go through Core's store (ctx.store).

The first time Gamer Stonks starts, it copies the holdings Stream Core used to keep itself
(table market_holdings in data/stream_core.db) so nobody loses shares in the move.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("plugins.stonks.holdings")

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    user_id      INTEGER NOT NULL,
    symbol       TEXT NOT NULL,
    milli_shares INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings(symbol);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Holdings:
    """Share holdings per (user_id, symbol). user_id is Core's points user id."""

    def __init__(self, db, store: Any = None):
        self.db = db              # core.plugin_db.PluginDB
        self.store = store        # core.store.Store (points)

    async def setup(self, core_db: Optional[Path] = None) -> int:
        """Create the tables; copy Core's old holdings once. Returns rows copied."""
        await self.db.script(SCHEMA)
        done = await self.db.fetchone("SELECT value FROM meta WHERE key = 'core_holdings_copied'")
        if done:
            return 0
        rows = _read_core_holdings(core_db) if core_db else []
        if rows:
            await self.db.executemany(
                "INSERT INTO holdings (user_id, symbol, milli_shares) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, symbol) DO UPDATE SET milli_shares = holdings.milli_shares + excluded.milli_shares",
                rows,
            )
            log.info("Gamer Stonks: copied %d holdings from Stream Core's database", len(rows))
        await self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('core_holdings_copied', ?)", (str(len(rows)),))
        return len(rows)

    async def adjust(self, user_id: int, symbol: str, milli_delta: int) -> int:
        """Add (or take, negative) milli-shares; never below zero. Returns the new amount."""
        sym = symbol.upper().strip()

        def go(conn: sqlite3.Connection) -> int:
            row = conn.execute("SELECT milli_shares FROM holdings WHERE user_id = ? AND symbol = ?",
                               (int(user_id), sym)).fetchone()
            nxt = max(0, (int(row[0]) if row else 0) + int(milli_delta))
            conn.execute(
                "INSERT INTO holdings (user_id, symbol, milli_shares) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, symbol) DO UPDATE SET milli_shares = excluded.milli_shares",
                (int(user_id), sym, nxt),
            )
            return nxt
        return await self.db.transaction(go)

    async def for_user(self, user_id: int) -> list[dict]:
        """One user's non-zero holdings (for !portfolio and !sell)."""
        return await self.db.fetchall(
            "SELECT user_id, symbol, milli_shares FROM holdings WHERE user_id = ? AND milli_shares > 0 ORDER BY symbol",
            (int(user_id),),
        )

    async def list(self, symbol: Optional[str] = None) -> list[dict]:
        """Every non-zero holding, or only those of ``symbol`` (largest first)."""
        if symbol:
            return await self.db.fetchall(
                "SELECT user_id, symbol, milli_shares FROM holdings WHERE symbol = ? AND milli_shares > 0 "
                "ORDER BY milli_shares DESC",
                (symbol.upper(),),
            )
        return await self.db.fetchall(
            "SELECT user_id, symbol, milli_shares FROM holdings WHERE milli_shares > 0 ORDER BY symbol, milli_shares DESC"
        )

    async def pay_dividend(self, symbol: str, total_points: int, reason: str = "vault") -> dict:
        """Split total_points across the holders of symbol by shares. Dust is burned."""
        sym = symbol.upper().strip()
        total = int(max(0, total_points))
        holders = await self.list(sym)
        pool = sum(int(h["milli_shares"]) for h in holders)
        out = {"symbol": sym, "total": total, "holders": 0, "paid": [], "burned": total, "reason": reason}
        if total <= 0 or pool <= 0 or self.store is None:
            return out
        remaining = total
        for h in holders:
            # Round each payout down; the leftover "dust" is not paid to anyone.
            cut = (total * int(h["milli_shares"])) // pool
            if cut <= 0:
                continue
            res = await self.store.adjust_points(int(h["user_id"]), cut, reason or f"dividend {sym}", "dividend")
            out["paid"].append({"user_id": int(h["user_id"]), "points": cut, "balance": res.get("balance")})
            remaining -= cut
        out["holders"] = len(out["paid"])
        out["burned"] = max(0, remaining)
        return out


def _read_core_holdings(path: Path) -> list[tuple]:
    """Rows of Stream Core's old market_holdings table (read-only; empty when there is none)."""
    if not path or not Path(path).is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return []
    try:
        found = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'market_holdings'").fetchone()
        if not found:
            return []
        return [(int(u), str(s).upper(), int(m)) for u, s, m in conn.execute(
            "SELECT user_id, symbol, milli_shares FROM market_holdings WHERE milli_shares > 0")]
    except sqlite3.Error as exc:
        log.warning("Gamer Stonks: couldn't read Stream Core's old holdings: %s", exc)
        return []
    finally:
        conn.close()
