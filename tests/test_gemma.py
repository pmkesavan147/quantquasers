"""The model layer, tested without a model.

What matters here is the failure behaviour: no backend, a truncated response, a
response wrapped in prose. Each must produce a valid contract object with
`model="fallback"`, because that is the difference between a degraded demo and a
dead one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.contracts import Horizon
from gemma import client, scorers
from gemma.client import extract_json


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """A private cache and a forced stub backend for every test in this file."""
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path / "gemma")
    monkeypatch.setenv("GEMMA_BACKEND", "stub")
    monkeypatch.setattr(client, "_resolved", None)
    yield
    monkeypatch.setattr(client, "_resolved", None)


# ── JSON extraction ──────────────────────────────────────────────────────
def test_plain_json_parses():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_json_inside_markdown_fences_parses():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_prose_before_and_after_json_parses():
    text = 'Sure! Here you go:\n{"a": 1, "b": "x"}\nHope that helps.'
    assert extract_json(text) == {"a": 1, "b": "x"}


def test_nested_objects_parse():
    assert extract_json('{"a": {"b": [1, 2]}}')["a"]["b"] == [1, 2]


def test_a_brace_inside_a_string_does_not_end_the_object():
    assert extract_json('{"a": "not } the end", "b": 2}')["b"] == 2


def test_an_escaped_quote_does_not_end_the_string():
    assert extract_json(r'{"a": "she said \"hi\"", "b": 3}')["b"] == 3


@pytest.mark.parametrize("bad", ["", "no json here", '{"a": 1', "}{"])
def test_unparseable_responses_raise_rather_than_guess(bad):
    with pytest.raises(ValueError):
        extract_json(bad)


# ── the stub path ────────────────────────────────────────────────────────
def test_generate_returns_empty_with_no_backend():
    assert client.generate("anything") == ""
    assert client.last_model() == "fallback"


def test_status_reports_the_stub_honestly():
    s = client.status()
    assert s["backend"] == "stub"
    assert s["model"] == "fallback"


def test_a_cached_response_is_replayed_and_keeps_its_own_model_name():
    client.cache_put("sys", "prompt", 0.0, "gemma-4-26b-a4b-it", '{"ok": true}')
    assert client.generate("prompt", system="sys") == '{"ok": true}'
    # Not relabelled with the local backend's name — the cache says who wrote it.
    assert client.last_model() == "gemma-4-26b-a4b-it"


def test_the_cache_key_ignores_the_backend_so_a_gpu_box_can_fill_it():
    key_a = client.cache_key_for("sys", "prompt", 0.0)
    client._resolved = "studio"
    assert client.cache_key_for("sys", "prompt", 0.0) == key_a


def test_different_temperatures_are_different_cache_entries():
    assert client.cache_key_for("s", "p", 0.0) != client.cache_key_for("s", "p", 0.5)


# ── headline scoring falls back deterministically ─────────────────────────
def test_a_negative_headline_scores_negative_without_a_model():
    s = scorers.score_headline(
        "Company X hit with SEBI penalty over disclosure lapses",
        "Company X", symbol="TESTCO", id="h1",
    )
    assert s.sentiment < 0
    assert s.label == "negative"
    assert s.model == "fallback"
    assert s.event_type == "regulatory"


def test_a_positive_headline_scores_positive_without_a_model():
    s = scorers.score_headline(
        "Company X bags large order win from state utility",
        "Company X", symbol="TESTCO", id="h2",
    )
    assert s.sentiment > 0
    assert s.label == "positive"
    assert s.event_type == "order_win"


def test_an_unreadable_headline_is_neutral_and_immaterial():
    s = scorers.score_headline("Company X in the news", "Company X",
                               symbol="TESTCO", id="h3")
    assert s.label == "neutral"
    assert s.materiality == 1


def test_scores_stay_inside_the_contract_bounds():
    s = scorers.score_headline(
        "Fraud probe, insolvency, ban and recall hit Company X",
        "Company X", symbol="TESTCO", id="h4",
    )
    assert -1.0 <= s.sentiment <= 1.0
    assert 1 <= s.materiality <= 5


def test_the_published_timestamp_is_preserved():
    when = datetime(2026, 7, 29, 9, 15)
    s = scorers.score_headline("X wins order", "X", symbol="TESTCO", id="h5",
                              published_at=when)
    assert s.published_at == when


# ── profiling and prose degrade, never crash ──────────────────────────────
BEHAVIOUR_Q = "Think of the last time something you held dropped hard. What did you actually do?"
GOAL_Q = "What would make you say this worked — and by when?"

LONG_ANSWERS = {
    BEHAVIOUR_Q: "I added more over the next two months and did not sell anything",
    GOAL_Q: "beating my FD over three years without watching a screen",
}


def test_no_free_text_means_no_second_opinion():
    horizon, confidence, why = scorers.profile_user(
        rubric_score=5, rubric_band="balanced", mcq={}, free_text={}
    )
    assert horizon is None
    assert confidence == 0.0
    assert "rubric" in why.lower()


def test_a_one_word_answer_is_treated_as_no_signal():
    """A model handed nine words still answers confidently, and that confidence
    is what moves someone's risk band."""
    horizon, confidence, why = scorers.profile_user(
        rubric_score=5, rubric_band="balanced", mcq={},
        free_text={BEHAVIOUR_Q: "sold"},
    )
    assert horizon is None
    assert confidence == 0.0
    assert "too little" in why.lower()


def test_an_unreachable_model_yields_no_horizon_and_zero_confidence():
    horizon, confidence, _ = scorers.profile_user(
        rubric_score=5, rubric_band="balanced", mcq={},
        free_text={BEHAVIOUR_Q: "I sold everything the same morning and stayed out for months"},
    )
    assert horizon is None
    assert confidence == 0.0


def test_the_prompt_labels_each_answer_with_its_question():
    """Unlabelled answers lose the distinction between what someone DID and
    what they WANT, which is most of the signal."""
    block, chars = scorers._format_free_text(LONG_ANSWERS)
    assert BEHAVIOUR_Q in block
    assert GOAL_Q in block
    assert chars > scorers.MIN_FREE_TEXT_CHARS


def test_a_parsed_model_answer_is_returned_from_cache():
    """The cache is the only way to exercise the parse path with no backend."""
    from gemma.scorers import PROFILE_PROMPT, PROFILER_SYSTEM

    block, _ = scorers._format_free_text(LONG_ANSWERS)
    prompt = PROFILE_PROMPT.format(
        rubric_score=5, rubric_band="balanced", mcq={}, free_text=block,
    )
    client.cache_put(
        PROFILER_SYSTEM, prompt, 0.0, "gemma-4-26b-a4b-it",
        '{"trader_type": "long_term", "confidence": 0.82, '
        '"reasoning": "They added over two months and sold nothing."}',
    )
    horizon, confidence, why = scorers.profile_user(
        rubric_score=5, rubric_band="balanced", mcq={}, free_text=LONG_ANSWERS,
    )
    assert horizon == Horizon.LONG
    assert confidence == 0.82
    assert "months" in why


def test_a_nonsense_trader_type_is_rejected_not_coerced():
    from gemma.scorers import PROFILE_PROMPT, PROFILER_SYSTEM

    answers = {BEHAVIOUR_Q: "I scalp the open every single day and never hold overnight"}
    block, _ = scorers._format_free_text(answers)
    prompt = PROFILE_PROMPT.format(
        rubric_score=5, rubric_band="balanced", mcq={}, free_text=block,
    )
    client.cache_put(
        PROFILER_SYSTEM, prompt, 0.0, "gemma-4-26b-a4b-it",
        '{"trader_type": "intraday", "confidence": 0.95, "reasoning": "r"}',
    )
    horizon, confidence, _ = scorers.profile_user(
        rubric_score=5, rubric_band="balanced", mcq={}, free_text=answers,
    )
    # "intraday" is Track 1's old vocabulary and is not a Horizon.
    assert horizon is None
    assert confidence == 0.0


def test_the_templated_explanation_still_carries_every_number():
    text = scorers.explain_candidate(
        symbol="TESTCO", horizon="day", sentiment=-0.42, n_articles=6,
        confidence=0.71, events=["regulatory"], adtv_cr=12.3,
        annual_vol=38.5, dist_52w_high_pct=-14.2,
        verdict="OUTSIDE_MANDATE", reasons=["Under surveillance."],
    )
    assert "-0.42" in text
    assert "12.3" in text
    assert "38.5" in text
    assert "Refused" in text


def test_the_fallback_personality_report_is_not_empty_and_disclaims():
    text = scorers.personality_report(band="balanced", rubric_score=5)
    assert len(text) > 120
    assert "not investment advice" in text.lower()


def test_recent_headlines_are_scored_with_a_real_timestamp_default():
    before = datetime.now() - timedelta(seconds=5)
    s = scorers.score_headline("X wins order", "X", symbol="T", id="h6")
    assert s.published_at >= before
