"""The live gate — triple-locked.

Live trading requires ALL THREE of:

  1. LIVE_TRADING=true in the environment
  2. a live.lock file created by hand in the repo root
  3. an interactive LIVE-CONFIRM typed at the prompt

Anything less resolves to paper. A fresh checkout has no env flag and no
lock file, so the default state of this repo is paper and cannot be
otherwise by accident.

STATUS FOR THE HACKATHON: the gate ships LOCKED and is never armed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent.parent
LOCK_FILE = ROOT / "live.lock"


def resolve_mode(
    confirm: Callable[[], bool] | None = None,
    lock_file: Path = LOCK_FILE,
) -> tuple[str, list[str]]:
    """("live", []) only when all three locks are open, else
    ("paper", [reasons the gate stayed shut])."""
    missing: list[str] = []

    if os.getenv("LIVE_TRADING", "").strip().lower() != "true":
        missing.append("LIVE_TRADING env is not 'true'")
    if not lock_file.exists():
        missing.append("live.lock file not present")

    if missing:
        return "paper", missing

    # Locks 1 and 2 open — the human still has to say it out loud.
    if confirm is None or not confirm():
        missing.append("interactive LIVE-CONFIRM not received")
        return "paper", missing

    return "live", []


def gate_armed() -> bool:
    """What GET /api/health reports and the UI's PAPER badge reads."""
    return resolve_mode()[0] == "live"


def build_broker(desk: str, quotes, starting_cash: float,
                 confirm: Callable[[], bool] | None = None):
    """The only place a broker is constructed. Desks never choose."""
    from trading.execution.paper import PaperBroker

    mode, _reasons = resolve_mode(confirm)
    if mode == "live":
        from trading.execution.kite import KiteBroker, load_kite

        return KiteBroker(load_kite(), quotes, desk=desk)
    return PaperBroker(quotes, starting_cash=starting_cash, desk=desk)
