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
        "/api/account", "/api/account/preview",
    ):
        assert route in paths, f"{route} missing from the frozen contract"


# ── onboarding ───────────────────────────────────────────────────────────
CONSERVATIVE = {
    "capital": 200_000,
    "horizons": ["long_term"],
    "day_trading": False,
    "allowed_caps": ["large"],
    "max_drawdown_pct": 10,
    "experience": "new",
}


def test_account_is_unconfigured_until_created(client):
    body = client.get("/api/account").json()
    assert body["configured"] is False
    assert body["default_capital"] > 0


def test_creating_an_account_derives_the_split_from_the_declared_capital(client):
    body = client.post("/api/account", json={"capital": 300_000}).json()
    assert body["capital"] == 300_000
    assert round(sum(body["allocation_pct"].values()), 2) == 100
    assert round(sum(body["allocation_rupees"].values()), 2) == 300_000
    assert len(body["desks"]) == 3


def test_capital_flows_into_the_engine_limits_and_health(client):
    client.post("/api/account", json={"capital": 250_000})
    health = client.get("/api/health").json()
    assert health["account_configured"] is True
    assert health["capital"] == 250_000
    assert health["risk_band"] in {"conservative", "balanced", "aggressive"}
    assert client.get("/api/portfolio").json()["capital"] == 250_000


def test_opting_out_of_intraday_switches_the_day_desk_off_but_keeps_it_visible(client):
    body = client.post("/api/account", json=CONSERVATIVE).json()
    assert body["risk_band"] == "conservative"
    assert "day" in body["desks_off"]
    assert "day" not in body["allocation_pct"]

    day = next(d for d in client.get("/api/desks").json() if d["name"] == "day")
    assert day["enabled"] is False
    assert day["allocation_pct"] == 0


def test_a_conservative_account_cannot_trade_the_day_desk(client):
    client.post("/api/account", json=CONSERVATIVE)
    body = client.post(
        "/api/orders/execute",
        json={"desk": "day", "at": "2026-07-30T10:30:00"},
    ).json()
    assert body["fills"] == []


def test_get_account_echoes_the_profile_after_creation(client):
    client.post("/api/account", json={"capital": 400_000, "sip_amount": 10_000,
                                     "sip_frequency": "monthly"})
    body = client.get("/api/account").json()
    assert body["configured"] is True
    assert body["profile"]["capital"] == 400_000
    assert body["sip"] == {
        "amount": 10_000, "frequency": "monthly",
        "target_desk": "long_term", "note": body["sip"]["note"],
    }


def test_a_sip_amount_without_a_frequency_is_rejected(client):
    r = client.post("/api/account", json={"capital": 100_000,
                                          "sip_amount": 5_000})
    assert r.status_code == 422


def test_non_positive_capital_is_rejected(client):
    assert client.post("/api/account", json={"capital": 0}).status_code == 422


def test_preview_changes_nothing(client):
    r = client.post("/api/account/preview", json={"capital": 900_000})
    assert r.status_code == 200
    assert r.json()["capital"] == 900_000
    # Still unconfigured — preview is for the onboarding slider only.
    assert client.get("/api/account").json()["configured"] is False


def test_account_creation_is_journaled(client):
    client.post("/api/account", json={"capital": 123_456})
    notes = client.get("/api/journal?kind=note&limit=100").json()
    created = [n for n in notes if n["payload"]["event"] == "account_created"]
    assert created and created[0]["payload"]["capital"] == 123_456
