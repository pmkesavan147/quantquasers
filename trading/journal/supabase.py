"""The same append-only journal, on Supabase Postgres over HTTP.

Serverless has no filesystem worth the name: Vercel wipes it between
invocations, so a SQLite journal there loses every position on the next cold
start — and this system *derives* the book by replaying the journal, so losing
it means losing the portfolio. A deployed instance keeps the ledger in Postgres.

It talks to PostgREST rather than opening a Postgres socket, for two reasons
that both matter on Vercel:

* **Connections.** Every serverless invocation is its own process. Postgres
  sockets do not pool across them, and a burst of cold starts exhausts the
  connection limit. HTTP has no such problem.
* **Bundle size.** `psycopg[binary]` is tens of megabytes against a 250 MB
  function limit that pandas and yfinance are already eating into.

`SupabaseJournal` is interface-identical to `store.Journal` on purpose: same
methods, same return shapes, same immutability. `trading.journal.open_journal()`
picks between them, so nothing upstream knows which one it got.

The table has RLS enabled with no policies, so the anon key cannot touch it —
only the service role key, which lives in the backend environment and never
reaches a browser. UPDATE and DELETE are rejected by a database trigger, so the
append-only claim is enforced by Postgres rather than by convention.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime

from trading.models import JournalEntry

TABLE = "journal"
TIMEOUT_S = float(os.getenv("JOURNAL_HTTP_TIMEOUT_S", "10"))


def supabase_config() -> tuple[str, str] | None:
    """`(url, service_key)` when this deployment is Postgres-backed, else None.

    The service role key is required rather than the anon key: RLS is on with
    no policies, which is what stops a leaked publishable key from reading
    somebody's trade history.
    """
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
        or ""
    )
    if url and key:
        return url, key
    return None


class SupabaseJournal:
    """Append-only ledger in Supabase Postgres. Same surface as `store.Journal`."""

    def __init__(self, url: str | None = None, key: str | None = None):
        import httpx

        config = supabase_config()
        self.url = (url or (config[0] if config else "")).rstrip("/")
        self.key = key or (config[1] if config else "")
        if not self.url or not self.key:
            raise RuntimeError(
                "No Supabase config. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY, or leave them unset to use the "
                "SQLite journal."
            )

        self.endpoint = f"{self.url}/rest/v1/{TABLE}"
        self.client = httpx.Client(
            timeout=TIMEOUT_S,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            },
        )

    # ── writes ───────────────────────────────────────────────────────────
    def append(self, kind: str, payload: dict,
               ts: datetime | None = None) -> JournalEntry:
        entry = JournalEntry(ts=ts or datetime.now(), kind=kind, payload=payload)
        resp = self.client.post(
            self.endpoint,
            headers={"Prefer": "return=minimal"},
            content=json.dumps(
                {
                    "ts": entry.ts.isoformat(timespec="seconds"),
                    "kind": entry.kind,
                    # json.dumps first with default=str so datetimes and enums
                    # inside the payload survive, then back to a dict for the
                    # JSONB column.
                    "payload": json.loads(json.dumps(entry.payload, default=str)),
                }
            ),
        )
        resp.raise_for_status()
        return entry

    # ── reads ────────────────────────────────────────────────────────────
    def _get(self, params: dict) -> list[dict]:
        resp = self.client.get(
            self.endpoint, params={"select": "ts,kind,payload", **params}
        )
        resp.raise_for_status()
        return [
            {
                "ts": row["ts"],
                "kind": row["kind"],
                # JSONB comes back decoded; SQLite hands back a string. Both
                # journals must return identical dicts.
                "payload": row["payload"]
                if isinstance(row["payload"], dict)
                else json.loads(row["payload"]),
            }
            for row in resp.json()
        ]

    def recent(self, n: int = 50, kind: str | None = None) -> list[dict]:
        params: dict = {"order": "id.desc", "limit": n}
        if kind:
            params["kind"] = f"eq.{kind}"
        return self._get(params)

    def all_of(self, kind: str) -> list[dict]:
        """Chronological. Used for journal replay."""
        return self._get({"kind": f"eq.{kind}", "order": "id.asc"})

    def for_day(self, day: date, kind: str | None = None) -> list[dict]:
        params: dict = {
            # Timestamps are stored as ISO strings, so a lexicographic range is
            # a date range — the same trick the SQLite journal uses.
            "ts": [f"gte.{day.isoformat()}", f"lt.{day.isoformat()}T23:59:59"],
            "order": "id.asc",
        }
        if kind:
            params["kind"] = f"eq.{kind}"
        return self._get(params)

    def count_today(self, kind: str, today: date | None = None) -> int:
        return len(self.for_day(today or date.today(), kind))

    def paper_trading_days(self) -> int:
        """Distinct days with at least one paper fill — keeps the graduation
        criteria honest rather than self-reported.

        Counted client-side because PostgREST has no DISTINCT. At demo volumes
        that is a few hundred rows; if this ever grows, it becomes an RPC.
        """
        fills = self._get({"kind": "eq.fill", "order": "id.asc"})
        return len(
            {
                row["ts"][:10]
                for row in fills
                if row["payload"].get("mode") == "paper"
            }
        )

    def close(self):
        self.client.close()
