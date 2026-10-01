"""
Chat Fund ledger for OpenTTD.

Points stay in Stream Core's user table. This module records:
  - session subsidies per company (who funded whom)
  - pending Game Script cash injections
  - a simple price tick from company value

Does NOT use vanilla 25% share slots. Chat owns Fridge units in SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


def company_price(company: dict) -> int:
    """
    Points-facing price unit derived from in-game numbers.
    Cash is discounted so dumping points cannot infinitely pump the ticker.
    """
    money = int(company.get("money") or 0)
    loan = int(company.get("loan") or 0)
    vehicles = int(company.get("vehicle_total") or 0)
    income = int(company.get("income") or 0)
    equity = money - loan
    # 1 point-tick ≈ £10k of discounted equity + a vehicle premium
    raw = max(1, (equity // 4 + income // 2) // 10_000 + vehicles * 5)
    return int(raw)


class OpenTTDMarket:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ottd_investments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    platform TEXT NOT NULL,
                    username TEXT NOT NULL,
                    user_id INTEGER,
                    company_id INTEGER NOT NULL,
                    company_name TEXT,
                    points INTEGER NOT NULL,
                    pounds INTEGER NOT NULL,
                    injected INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ottd_pending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    payload TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def record_invest(
        self,
        *,
        platform: str,
        username: str,
        user_id: Optional[int],
        company_id: int,
        company_name: str,
        points: int,
        pounds: int,
        injected: bool,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ottd_investments
                    (ts, platform, username, user_id, company_id, company_name, points, pounds, injected)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    time.time(),
                    platform,
                    username,
                    user_id,
                    company_id,
                    company_name,
                    points,
                    pounds,
                    1 if injected else 0,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def queue_injection(self, payload: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ottd_pending (ts, payload, done) VALUES (?,?,0)",
                (time.time(), json.dumps(payload)),
            )
            conn.commit()

    def pending(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, payload FROM ottd_pending WHERE done=0 ORDER BY id"
            ).fetchall()
        out = []
        for row in rows:
            try:
                data = json.loads(row["payload"])
            except Exception:
                data = {}
            data["_id"] = row["id"]
            out.append(data)
        return out

    def mark_done(self, row_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE ottd_pending SET done=1 WHERE id=?", (row_id,))
            conn.commit()

    def funded_totals(self) -> dict[int, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT company_id, company_name,
                       SUM(points) AS points, SUM(pounds) AS pounds, COUNT(*) AS hits
                FROM ottd_investments
                GROUP BY company_id
                """
            ).fetchall()
        out = {}
        for row in rows:
            out[int(row["company_id"])] = {
                "company_id": int(row["company_id"]),
                "company_name": row["company_name"],
                "points": int(row["points"] or 0),
                "pounds": int(row["pounds"] or 0),
                "hits": int(row["hits"] or 0),
            }
        return out

    def recent(self, limit: int = 12) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, platform, username, company_id, company_name, points, pounds, injected
                FROM ottd_investments ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
