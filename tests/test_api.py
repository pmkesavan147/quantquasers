"""The frozen API surface. Track 3 builds against these shapes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import state
from api.main import app


@pytest.fixture(autouse=True)
def paper_engine(tmp_path, monkeypatch):
    """A fresh journal per test, and the gate definitively shut."""
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    # An isolated journal per test. Without this the API tests share the
    # repo-root DB and contaminate each other's books.
    monkeypatch.setattr(
        "trading.journal.store.DEFAULT_DB", tmp_path / "j.sqlite3"
    )
    state.reset()
    yield
    state.reset()


@pytest.fixture
def client():
    return TestClient(app)


def test_health_reports_a_shut_gate(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "paper"
    assert body["gate_armed"] is False
    assert body["gate_shut_because"]
    assert "SEBI" in body["disclaimer"]
    assert set(body["desks"]) == {"day", "swing", "long_term"}


def test_desks_returns_three_desks_summing_to_one_hundred(client):
    r = client.get("/api/desks")
    assert r.status_code == 200
    desks = r.json()
    assert len(desks) == 3
    assert sum(d["allocation_pct"] for d in desks) == 100
    assert {d["name"] for d in desks} == {"day", "swing", "long_term"}


def test_propose_is_read_only(client):
    """Proposing must not journal or fill — the UI polls this."""
    before = client.get("/api/journal?limit=1000").json()
    r = client.post("/api/orders/propose", json={"desk": "swing"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    after = client.get("/api/journal?limit=1000").json()
    assert len(after) == len(before)


def test_execute_fills_and_journals(client):
    r = client.post("/api/orders/execute", json={"desk": "swing"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "paper"
    assert body["fills"], "expected at least one paper fill from fixtures"
    assert all(f["costs"] > 0 for f in body["fills"])

    fills = client.get("/api/journal?kind=fill&limit=100").json()
    assert len(fills) == len(body["fills"])


def test_execute_reports_the_refusals_not_just_the_fills(client):
    body = client.post("/api/orders/execute", json={"desk": "day"}).json()
    reasons = {s["symbol"]: s["reason"] for s in body["skipped"]}
    assert reasons["RELIANCE"].startswith("sentiment_below_threshold")
    assert reasons["ADANIPORTS"] == "blocked_event:promoter_pledge"
    assert reasons["SOMEMICRO"].startswith("mandate_blocked")


def test_unknown_desk_is_404(client):
    r = client.post("/api/orders/execute", json={"desk": "options"})
    assert r.status_code == 404


def test_portfolio_shape(client):
    client.post("/api/orders/execute", json={"desk": "long_term"})
    p = client.get("/api/portfolio").json()
    assert p["mode"] == "paper"
    assert p["deployed"] <= p["capital"]
    assert len(p["desks"]) == 3
    assert isinstance(p["positions"], list)


def test_pause_blocks_new_fills_and_resume_restores(client):
    assert client.post("/api/control/pause").json()["halted"] is True
    body = client.post("/api/orders/execute", json={"desk": "swing"}).json()
    assert body["fills"] == []
    assert all("halted" in v["rule"] for v in body["vetoed"])

    assert client.post("/api/control/resume").json()["halted"] is False
    body2 = client.post("/api/orders/execute", json={"desk": "swing"}).json()
    assert body2["fills"]


def test_journal_filters_by_kind(client):
    client.post("/api/orders/execute", json={"desk": "swing"})
    verdicts = client.get("/api/journal?kind=verdict&limit=100").json()
    assert verdicts and all(e["kind"] == "verdict" for e in verdicts)


def test_at_parameter_drives_the_square_off_rule(client):
    """A day entry at 15:20 must not fill."""
    body = client.post(
        "/api/orders/execute",
        json={"desk": "day", "at": "2026-07-30T15:20:00"},
    ).json()
    buys = [f for f in body["fills"] if f["side"] == "BUY"]
    assert buys == []


def test_mandate_forbidding_day_trading_blocks_the_day_desk(client):
    body = client.post(
        "/api/orders/execute",
        json={"desk": "day", "day_trading_allowed": False,
              "at": "2026-07-30T10:30:00"},
    ).json()
    assert body["fills"] == []
    reasons = {s["reason"] for s in body["skipped"]}
    assert "mandate_forbids_intraday" in reasons


def test_openapi_documents_the_frozen_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for route in (
        "/api/orders/propose", "/api/orders/execute", "/api/desks",
        "/api/portfolio", "/api/journal", "/api/health",
        "/api/control/pause", "/api/control/resume",
    ):
        assert route in paths, f"{route} missing from the frozen contract"
