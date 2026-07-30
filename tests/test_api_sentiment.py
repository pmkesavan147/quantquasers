"""Track 1's routes, offline and with no model. This is exactly the demo's
worst case, so it is the case the tests pin down.

Everything runs with `offline=True` and `GEMMA_BACKEND=stub`: prices come from
the parquet cache or the fixtures, headlines from the cache or
`data/headlines.json`, and scoring from the keyword fallback. If these pass on a
plane, they pass at the venue.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import state
from api.main import app
from gemma import client as gemma_client

FULL_ANSWERS = {
    "capital": 250_000,
    "horizons": ["day", "swing", "long_term"],
    "day_trading": True,
    "drawdown": "30",
    "experience": "1-3y",
    "allowed_caps": ["large", "mid"],
    "uses_leverage": False,
    "sip_amount": 5_000,
    "sip_frequency": "monthly",
    "open_reaction": "I held on and bought a little more the following month",
    "open_rhythm": "I check on weekends and act only on results",
    "open_goal": "Beat FD returns over three years",
}


@pytest.fixture(autouse=True)
def paper_and_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.setenv("GEMMA_BACKEND", "stub")
    monkeypatch.setenv("GEMMA_WARM", "0")
    monkeypatch.setattr(gemma_client, "CACHE_DIR", tmp_path / "gemma")
    monkeypatch.setattr(gemma_client, "_resolved", None)
    monkeypatch.setattr("trading.journal.store.DEFAULT_DB", tmp_path / "j.sqlite3")
    state.reset()
    yield
    state.reset()


@pytest.fixture
def client():
    return TestClient(app)


# ── the survey ───────────────────────────────────────────────────────────
def test_the_quiz_is_served_from_the_backend_not_hardcoded_in_the_ui(client):
    body = client.get("/api/quiz").json()
    ids = {q["id"] for q in body["questions"]}
    assert {"capital", "horizons", "allowed_caps", "sip_amount"} <= ids


def test_submitting_the_quiz_creates_the_account_in_one_call(client):
    r = client.post("/api/quiz/submit", json={"answers": FULL_ANSWERS})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert body["profile"]["capital"] == 250_000
    assert round(sum(body["allocation_pct"].values()), 2) == 100
    assert len(body["account"]["desks"]) == 3

    health = client.get("/api/health").json()
    assert health["account_configured"] is True
    assert health["capital"] == 250_000


def test_submitting_with_create_account_false_changes_nothing(client):
    r = client.post(
        "/api/quiz/submit",
        json={"answers": FULL_ANSWERS, "create_account": False},
    )
    assert r.json()["created"] is False
    assert client.get("/api/account").json()["configured"] is False


def test_declining_intraday_switches_the_day_desk_off_end_to_end(client):
    answers = {**FULL_ANSWERS, "day_trading": False, "horizons": ["swing", "long_term"]}
    body = client.post("/api/quiz/submit", json={"answers": answers}).json()
    assert "day" not in body["allocation_pct"]

    day = next(d for d in client.get("/api/desks").json() if d["name"] == "day")
    assert day["enabled"] is False


def test_the_model_status_is_reported_so_nobody_claims_gemma_wrote_it(client):
    body = client.post("/api/quiz/submit", json={"answers": FULL_ANSWERS}).json()
    assert body["model"]["backend"] == "stub"
    assert body["model"]["model"] == "fallback"


def test_the_persona_report_is_prose_and_disclaims(client):
    client.post("/api/quiz/submit", json={"answers": FULL_ANSWERS})
    body = client.post("/api/persona/report",
                       json={"answers": FULL_ANSWERS}).json()
    assert len(body["report"]) > 100
    assert "not investment advice" in body["report"].lower()


# ── the news read ────────────────────────────────────────────────────────
def test_market_sentiment_works_offline_and_labels_its_provenance(client):
    body = client.get("/api/sentiment/market?limit=3&offline=true").json()
    assert len(body["symbols"]) == 3
    assert set(body["mood"]) == {"score", "confidence", "symbols", "articles"}
    assert body["provenance"]["headline_source"]


def test_every_sentiment_score_is_inside_the_contract_bounds(client):
    body = client.get("/api/sentiment/market?limit=5&offline=true").json()
    for row in body["symbols"]:
        assert -1.0 <= row["score"] <= 1.0
        assert 0.0 <= row["confidence"] <= 1.0


def test_one_symbol_returns_the_headlines_that_produced_the_score(client):
    body = client.get("/api/sentiment/RELIANCE?offline=true").json()
    assert body["symbol"] == "RELIANCE"
    assert body["sentiment"]["n_articles"] == len(body["headlines"])
    assert all("title" in h and "origin" in h for h in body["headlines"])


def test_an_unknown_symbol_is_404_not_an_empty_score(client):
    assert client.get("/api/sentiment/NOTREAL?offline=true").status_code == 404


def test_requesting_an_unknown_symbol_list_is_404(client):
    r = client.post("/api/candidates",
                    json={"horizon": "swing", "symbols": ["NOTREAL"]})
    assert r.status_code == 404
    assert "universe.csv" in r.json()["detail"]


# ── candidates ───────────────────────────────────────────────────────────
def test_candidates_are_ranked_and_carry_their_provenance(client):
    r = client.post(
        "/api/candidates",
        json={"horizon": "swing", "limit": 4, "offline": True, "explain": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"]

    # Ranking is (verdict tier, then score) — SUITABLE before STRETCH before
    # OUTSIDE_MANDATE, descending by score inside each tier.
    tiers = ["SUITABLE", "STRETCH", "OUTSIDE_MANDATE"]
    seen = [tiers.index(c["verdict"]["level"]) for c in body["candidates"]]
    assert seen == sorted(seen)
    for tier in tiers:
        scores = [c["composite_score"] for c in body["candidates"]
                  if c["verdict"]["level"] == tier]
        assert scores == sorted(scores, reverse=True), tier

    assert {"live", "snapshot", "fixture", "none"} == set(body["report"]["quant_source"])


def test_refusals_are_returned_with_their_numbers_never_filtered(client):
    """SOMEMICRO is the synthetic micro-cap; it must come back refused, not
    hidden, with a metric and a threshold on every blocking reason."""
    r = client.post(
        "/api/candidates",
        json={
            "horizon": "day",
            "symbols": ["RELIANCE", "SOMEMICRO"],
            "offline": True,
            "explain": False,
            "profile": {
                "capital": 200_000, "horizons": ["day"],
                "allowed_caps": ["large"], "max_drawdown_pct": 20,
                "experience": "new", "day_trading": True, "uses_leverage": False,
            },
        },
    )
    body = r.json()
    refused = [c for c in body["candidates"]
               if c["verdict"]["level"] == "OUTSIDE_MANDATE"]
    assert refused, "the micro-cap must be returned, refused"
    blocks = [x for x in refused[0]["verdict"]["reasons"]
              if x["severity"] == "block"]
    assert len(blocks) >= 2
    assert all(b["metric"] and b["threshold"] is not None for b in blocks)


def test_every_candidate_carries_an_explanation_even_with_no_model(client):
    body = client.post(
        "/api/candidates",
        json={"horizon": "long_term", "limit": 3, "offline": True},
    ).json()
    assert all(c["explanation"] for c in body["candidates"])


def test_candidates_to_desk_proposes_orders_without_placing_them(client):
    client.post("/api/quiz/submit", json={"answers": FULL_ANSWERS})
    before = client.get("/api/journal?limit=1000").json()

    r = client.post(
        "/api/candidates/to-desk",
        json={"horizon": "swing", "limit": 4, "offline": True, "explain": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert "proposed_orders" in body and "refused" in body

    after = client.get("/api/journal?limit=1000").json()
    assert len(after) == len(before), "proposing must not journal"


def test_refused_candidates_never_reach_the_desk(client):
    client.post("/api/quiz/submit", json={"answers": FULL_ANSWERS})
    body = client.post(
        "/api/candidates/to-desk",
        json={
            "horizon": "day",
            "symbols": ["RELIANCE", "SOMEMICRO"],
            "offline": True,
            "explain": False,
        },
    ).json()
    proposed = {o["symbol"] for o in body["proposed_orders"]}
    refused = {r["symbol"] for r in body["refused"]}
    assert not (proposed & refused)


# ── introspection ────────────────────────────────────────────────────────
def test_the_universe_is_published_with_its_caveats(client):
    body = client.get("/api/universe").json()
    assert body["count"] >= 30
    assert "micro" in body["buckets"]
    assert "not an official SEBI bucket" in body["note"]


def test_gemma_status_is_exposed_for_the_ui_badge(client):
    body = client.get("/api/gemma/status").json()
    assert body["backend"] in {"studio", "remote", "ollama", "stub"}


def test_the_openapi_document_lists_the_track_one_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for route in (
        "/api/quiz", "/api/quiz/submit", "/api/persona/report",
        "/api/sentiment/market", "/api/candidates", "/api/candidates/to-desk",
        "/api/universe", "/api/gemma/status",
    ):
        assert route in paths, f"{route} missing"
