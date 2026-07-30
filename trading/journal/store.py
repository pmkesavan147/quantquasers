"""Append-only journal — the source of truth for every decision.

Exposes append and read. There is deliberately no update and no delete;
history is immutable. Portfolio state is DERIVED by replaying this ledger,
never stored alongside it, so the book cannot disagree with the record.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from trading.models import JournalEntry

ROOT = Path(__file__).resolve().parent.parent.parent


def _default_db() -> Path:
    """Where the SQLite ledger lives.

    On Vercel the deployment directory is read-only and only /tmp is writable,
    so a repo-relative path there fails on the first write — with a 500 that
    looks like a code bug rather than a missing database. /tmp is wiped between
    invocations, which is exactly why a deployed instance should be configured
    with Supabase instead; this only keeps it from crashing if it is not.
    """
    override = os.getenv("JOURNAL_DB")
    if override:
        return Path(override)
    if os.getenv("VERCEL"):
        return Path("/tmp/quantquasers.sqlite3")
    return ROOT / "quantquasers.sqlite3"


DEFAULT_DB = _default_db()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_ts ON journal(ts);
CREATE INDEX IF NOT EXISTS idx_journal_kind ON journal(kind);
"""


class Journal:
    def __init__(self, db_path: Path | str | None = None):
        # Resolved at call time, not at import time: a default argument would
        # bind DEFAULT_DB permanently and make the path impossible to
        # override in tests.
        self.path = Path(db_path) if db_path else DEFAULT_DB
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def append(self, kind: str, payload: dict,
               ts: datetime | None = None) -> JournalEntry:
        entry = JournalEntry(ts=ts or datetime.now(), kind=kind, payload=payload)
        self.conn.execute(
            "INSERT INTO journal (ts, kind, payload) VALUES (?,?,?)",
            (
                entry.ts.isoformat(timespec="seconds"),
                entry.kind,
                json.dumps(entry.payload, default=str),
            ),
        )
        self.conn.commit()
        return entry

    def _rows(self, rows) -> list[dict]:
        return [
            {"ts": r["ts"], "kind": r["kind"], "payload": json.loads(r["payload"])}
            for r in rows
        ]

    def recent(self, n: int = 50, kind: str | None = None) -> list[dict]:
        q = "SELECT ts, kind, payload FROM journal"
        args: tuple = ()
        if kind:
            q += " WHERE kind=?"
            args = (kind,)
        q += " ORDER BY id DESC LIMIT ?"
        return self._rows(self.conn.execute(q, args + (n,)).fetchall())

    def all_of(self, kind: str) -> list[dict]:
        """Chronological. Used for journal replay."""
        rows = self.conn.execute(
            "SELECT ts, kind, payload FROM journal WHERE kind=? ORDER BY id", (kind,)
        ).fetchall()
        return self._rows(rows)

    def for_day(self, day: date, kind: str | None = None) -> list[dict]:
        q = "SELECT ts, kind, payload FROM journal WHERE ts >= ? AND ts < ?"
        args: list = [day.isoformat(), day.isoformat() + "T23:59:59"]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        rows = self.conn.execute(q + " ORDER BY id", args).fetchall()
        return self._rows(rows)

    def count_today(self, kind: str, today: date | None = None) -> int:
        return len(self.for_day(today or date.today(), kind))

    def paper_trading_days(self) -> int:
        """Distinct days with at least one paper fill — keeps the graduation
        criteria honest rather than self-reported."""
        rows = self.conn.execute(
            "SELECT DISTINCT substr(ts,1,10) FROM journal "
            "WHERE kind='fill' AND payload LIKE '%\"mode\": \"paper\"%'"
        ).fetchall()
        return len(rows)

    def close(self):
        self.conn.close()
