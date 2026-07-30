"""The append-only ledger, on whichever store this deployment has.

    open_journal()   -> Supabase Postgres when configured, else SQLite

Both classes expose the same methods and return the same shapes, so callers
never branch on which one they got. The choice is environment, not behaviour: a
laptop has a filesystem and gets SQLite; Vercel does not and gets Postgres.
"""

from __future__ import annotations

from pathlib import Path

from trading.journal.store import DEFAULT_DB, Journal
from trading.journal.supabase import supabase_config

__all__ = ["Journal", "DEFAULT_DB", "open_journal", "backend_name", "supabase_config"]


def open_journal(db_path: Path | str | None = None):
    """The journal this environment should use.

    An explicit `db_path` always wins — tests pass a tmp file and must not be
    silently redirected at a production database because an env var is set.
    """
    if db_path is not None:
        return Journal(db_path)

    if supabase_config():
        from trading.journal.supabase import SupabaseJournal

        return SupabaseJournal()

    return Journal()


def backend_name() -> str:
    """'supabase' or 'sqlite' — surfaced in /api/health so it is never a guess
    which store a running instance is writing to."""
    return "supabase" if supabase_config() else "sqlite"
