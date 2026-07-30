"""Test-wide safety rails.

Once a real `GOOGLE_API_KEY` exists in `.env`, any test that forgets to stub the
model layer will quietly call Gemma for real: slow, non-deterministic, and it
burns free-tier quota that the demo needs. Same for the network — a test that
reaches yfinance passes at a desk and fails on a plane.

Both are forced off here for every test. A test that genuinely wants a live
backend has to say so by setting the env var itself, which is the point: it
becomes a visible choice rather than an accident.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True, scope="session")
def _no_live_calls_by_default():
    import os

    os.environ.setdefault("GEMMA_BACKEND", "stub")
    os.environ["OFFLINE"] = "1"
    # Snapshot mode is environment-driven and would otherwise leak into tests on
    # a machine where SNAPSHOT is exported for a local deployment rehearsal.
    os.environ.setdefault("SNAPSHOT", "0")
    yield
