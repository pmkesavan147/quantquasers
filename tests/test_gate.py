"""The live gate stays shut. Every combination that is not all-three-locks
must resolve to paper."""

from __future__ import annotations

import itertools

import pytest

from trading.execution.gate import build_broker, resolve_mode
from trading.execution.paper import PaperBroker
from trading.execution.quotes import MockQuoteSource


@pytest.fixture
def lock(tmp_path):
    """A lock file path that does not exist unless a test creates it."""
    return tmp_path / "live.lock"


def test_fresh_checkout_is_paper(monkeypatch, lock):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    mode, reasons = resolve_mode(lock_file=lock)
    assert mode == "paper"
    assert len(reasons) == 2          # no env flag, no lock file


def test_env_flag_alone_is_not_enough(monkeypatch, lock):
    monkeypatch.setenv("LIVE_TRADING", "true")
    mode, reasons = resolve_mode(lock_file=lock)
    assert mode == "paper"
    assert reasons == ["live.lock file not present"]


def test_lock_file_alone_is_not_enough(monkeypatch, lock):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    lock.write_text("armed")
    mode, reasons = resolve_mode(lock_file=lock)
    assert mode == "paper"
    assert reasons == ["LIVE_TRADING env is not 'true'"]


def test_two_locks_without_confirmation_is_still_paper(monkeypatch, lock):
    monkeypatch.setenv("LIVE_TRADING", "true")
    lock.write_text("armed")
    mode, reasons = resolve_mode(confirm=None, lock_file=lock)
    assert mode == "paper"
    assert reasons == ["interactive LIVE-CONFIRM not received"]


def test_declined_confirmation_is_paper(monkeypatch, lock):
    monkeypatch.setenv("LIVE_TRADING", "true")
    lock.write_text("armed")
    mode, _ = resolve_mode(confirm=lambda: False, lock_file=lock)
    assert mode == "paper"


def test_all_three_locks_open_is_the_only_path_to_live(monkeypatch, lock):
    monkeypatch.setenv("LIVE_TRADING", "true")
    lock.write_text("armed")
    mode, reasons = resolve_mode(confirm=lambda: True, lock_file=lock)
    assert mode == "live" and reasons == []


def test_every_combination_except_all_three_is_paper(monkeypatch, lock):
    """Exhaustive: 2 x 2 x 2 = 8 combinations, exactly one may be live."""
    live_count = 0
    for env, has_lock, confirmed in itertools.product([False, True], repeat=3):
        if env:
            monkeypatch.setenv("LIVE_TRADING", "true")
        else:
            monkeypatch.delenv("LIVE_TRADING", raising=False)
        if has_lock:
            lock.write_text("armed")
        elif lock.exists():
            lock.unlink()
        mode, _ = resolve_mode(
            confirm=(lambda: True) if confirmed else None, lock_file=lock
        )
        if mode == "live":
            live_count += 1
            assert (env, has_lock, confirmed) == (True, True, True)
    assert live_count == 1


def test_truthy_lookalikes_do_not_open_the_env_lock(monkeypatch, lock):
    lock.write_text("armed")
    for value in ("1", "yes", "TRUE ", "True!", "on", ""):
        monkeypatch.setenv("LIVE_TRADING", value)
        mode, _ = resolve_mode(confirm=lambda: True, lock_file=lock)
        if value.strip().lower() == "true":
            assert mode == "live"
        else:
            assert mode == "paper", f"{value!r} should not arm the gate"


def test_build_broker_returns_paper_by_default(monkeypatch):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    broker = build_broker("swing", MockQuoteSource({"TCS": 3000}), 30_000)
    assert isinstance(broker, PaperBroker)
    assert broker.mode == "paper"
