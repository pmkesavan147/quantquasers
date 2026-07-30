"""The survey → `RiskProfile` mapping.

This is where the three tracks used to disagree, so the tests are about the
contract: every option value the UI can send must land on a valid field, and a
half-answered survey must still produce a usable profile rather than a 500.
"""

from __future__ import annotations

import pytest

from core.contracts import Horizon, RiskProfile
from gemma import client
from gemma.quiz import QUESTIONS, QUESTION_BY_ID, summarise, to_profile
from trading.allocation import allocate, risk_band


@pytest.fixture(autouse=True)
def no_model(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMMA_BACKEND", "stub")
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path / "gemma")
    monkeypatch.setattr(client, "_resolved", None)


FULL = {
    "capital": 300_000,
    "horizons": ["day", "swing", "long_term"],
    "day_trading": True,
    "drawdown": "30",
    "experience": "3y+",
    "allowed_caps": ["large", "mid", "small"],
    "uses_leverage": True,
    "sip_amount": 10_000,
    "sip_frequency": "monthly",
    "open_reaction": "I held through it and added a little the next month",
    "open_rhythm": "I look on weekends, I would act on results or a big fall",
    "open_goal": "Beat my FD returns over three years",
}


# ── the question set is a contract with the frontend ──────────────────────
def test_every_question_has_a_unique_id():
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == len(set(ids))


def test_choice_questions_carry_backend_enum_values():
    """The regression that broke integration: the UI sent 'years+', the backend
    wanted 'long_term'."""
    assert {o.value for o in QUESTION_BY_ID["horizons"].options} == {
        "day", "swing", "long_term"
    }
    assert {o.value for o in QUESTION_BY_ID["experience"].options} == {
        "new", "1-3y", "3y+"
    }
    assert {o.value for o in QUESTION_BY_ID["allowed_caps"].options} == {
        "large", "mid", "small", "micro"
    }


def test_every_option_value_is_accepted_by_to_profile():
    for value in (o.value for o in QUESTION_BY_ID["experience"].options):
        profile, _ = to_profile({**FULL, "experience": value}, use_gemma=False)
        assert profile.experience == value
    for value in (o.value for o in QUESTION_BY_ID["drawdown"].options):
        profile, _ = to_profile({**FULL, "drawdown": value}, use_gemma=False)
        assert profile.max_drawdown_pct == float(value)


def test_the_written_questions_ask_for_evidence_not_opinion():
    """The three text questions are the only input a model sees about the user.

    They ask what someone DID, how much attention they have, and what "worked"
    means with a date on it. The version this replaced asked how they felt about
    the market, which produced predictions we do not use.
    """
    from gemma.quiz import FREE_TEXT_IDS

    assert FREE_TEXT_IDS == ("open_reaction", "open_rhythm", "open_goal")
    for qid in FREE_TEXT_IDS:
        q = QUESTION_BY_ID[qid]
        assert q.kind == "text"
        assert q.required is False, "nobody should be blocked on a text box"
        assert q.placeholder, f"{qid} needs an example answer to model the depth"
        assert q.help, f"{qid} needs to say why it is being asked"


def test_free_text_is_keyed_by_question_so_the_model_knows_which_is_which():
    from gemma.quiz import free_text_from

    mapped = free_text_from(FULL)
    assert set(mapped) == {
        QUESTION_BY_ID[qid].text for qid in ("open_reaction", "open_rhythm", "open_goal")
    }
    assert mapped[QUESTION_BY_ID["open_reaction"].text].startswith("I held through")


def test_unanswered_text_questions_are_omitted_not_sent_as_empty():
    from gemma.quiz import free_text_from

    mapped = free_text_from({**FULL, "open_rhythm": "   "})
    assert QUESTION_BY_ID["open_rhythm"].text not in mapped


def test_skipping_every_text_question_is_a_valid_survey():
    answers = {k: v for k, v in FULL.items() if not k.startswith("open_")}
    profile, read = to_profile(answers, use_gemma=True)
    assert isinstance(profile, RiskProfile)
    assert read["trader_type"] is None
    assert read["moved_band"] is False


def test_the_capital_slider_stops_at_the_engines_ceiling():
    """Offering more on the slider than the risk manager will size to is a lie."""
    from trading.config import RiskLimits

    assert QUESTION_BY_ID["capital"].max == RiskLimits().max_capital


# ── mapping ──────────────────────────────────────────────────────────────
def test_a_full_survey_maps_onto_every_profile_field():
    profile, _ = to_profile(FULL, use_gemma=False)
    assert profile.capital == 300_000
    assert profile.horizons == [Horizon.DAY, Horizon.SWING, Horizon.LONG]
    assert profile.max_drawdown_pct == 30.0
    assert profile.experience == "3y+"
    assert profile.allowed_caps == ["large", "mid", "small"]
    assert profile.uses_leverage is True
    assert (profile.sip_amount, profile.sip_frequency) == (10_000, "monthly")


def test_an_empty_survey_still_produces_a_valid_profile():
    profile, _ = to_profile({}, use_gemma=False)
    assert isinstance(profile, RiskProfile)
    assert profile.capital > 0
    assert profile.horizons


def test_explicitly_declining_intraday_beats_ticking_the_day_horizon():
    profile, _ = to_profile(
        {**FULL, "horizons": ["day", "swing"], "day_trading": False},
        use_gemma=False,
    )
    assert profile.day_trading is False
    assert "day" not in allocate(profile)


def test_omitting_the_consent_question_infers_it_from_the_horizons():
    answers = {k: v for k, v in FULL.items() if k != "day_trading"}
    with_day, _ = to_profile(answers, use_gemma=False)
    assert with_day.day_trading is True

    without_day, _ = to_profile({**answers, "horizons": ["long_term"]},
                                use_gemma=False)
    assert without_day.day_trading is False


def test_garbage_values_are_dropped_not_propagated():
    profile, _ = to_profile(
        {
            "capital": "not a number",
            "horizons": ["intraday", "hybrid"],       # Track 1's old vocabulary
            "allowed_caps": ["nano", "large"],
            "drawdown": "lots",
            "experience": "guru",
        },
        use_gemma=False,
    )
    assert profile.capital > 0
    assert profile.horizons == [Horizon.DAY, Horizon.SWING, Horizon.LONG]
    assert profile.allowed_caps == ["large"]
    assert profile.experience == "1-3y"


def test_a_sip_amount_without_a_frequency_defaults_to_monthly():
    profile, _ = to_profile({**FULL, "sip_frequency": "none"}, use_gemma=False)
    assert profile.sip_frequency == "monthly"


def test_no_sip_amount_forces_the_frequency_to_none():
    profile, _ = to_profile({**FULL, "sip_amount": 0}, use_gemma=False)
    assert profile.sip_frequency == "none"


def test_a_single_horizon_string_is_accepted_as_well_as_a_list():
    profile, _ = to_profile({**FULL, "horizons": "long_term"}, use_gemma=False)
    assert profile.horizons == [Horizon.LONG]


# ── the rubric stays in charge ────────────────────────────────────────────
def test_a_cautious_survey_lands_conservative():
    profile, _ = to_profile(
        {
            "capital": 100_000, "horizons": ["long_term"], "day_trading": False,
            "drawdown": "10", "experience": "new", "allowed_caps": ["large"],
            "uses_leverage": False,
        },
        use_gemma=False,
    )
    assert risk_band(profile) == "conservative"


def test_an_aggressive_survey_lands_aggressive():
    profile, _ = to_profile(
        {
            "capital": 500_000, "horizons": ["day", "swing", "long_term"],
            "day_trading": True, "drawdown": "40", "experience": "3y+",
            "allowed_caps": ["large", "mid", "small", "micro"],
            "uses_leverage": True,
        },
        use_gemma=False,
    )
    assert risk_band(profile) == "aggressive"


def test_no_model_means_no_gemma_influence_at_all():
    profile, read = to_profile(FULL, use_gemma=True)
    assert profile.trader_type is None
    assert profile.confidence == 0.0
    assert read["moved_band"] is False
    assert read["rubric_band"] == read["band_after"]


def test_a_confident_cached_read_can_move_the_band_one_notch():
    from gemma.quiz import free_text_from
    from gemma.scorers import PROFILE_PROMPT, PROFILER_SYSTEM, _format_free_text
    from trading.allocation import rubric_score

    answers = {
        "capital": 200_000, "horizons": ["swing"], "day_trading": False,
        "drawdown": "20", "experience": "1-3y", "allowed_caps": ["large"],
        "uses_leverage": False,
        "open_reaction": "I closed it the same morning, I cannot hold something falling overnight",
        "open_rhythm": "I watch the screen most of the day and act within minutes",
    }
    profile_before, _ = to_profile(answers, use_gemma=False)
    band_before = risk_band(profile_before)

    block, _ = _format_free_text(free_text_from(answers))
    prompt = PROFILE_PROMPT.format(
        rubric_score=rubric_score(profile_before),
        rubric_band=band_before,
        mcq={
            "horizons": ["swing"], "day_trading": False, "drawdown_pct": 20.0,
            "experience": "1-3y", "allowed_caps": ["large"],
            "uses_leverage": False,
        },
        free_text=block,
    )
    client.cache_put(
        PROFILER_SYSTEM, prompt, 0.0, "gemma-4-26b-a4b-it",
        '{"trader_type": "day", "confidence": 0.9, "reasoning": "Hourly checks."}',
    )

    profile_after, read = to_profile(answers, use_gemma=True)
    assert profile_after.trader_type == Horizon.DAY
    assert read["moved_band"] is True
    bands = ["conservative", "balanced", "aggressive"]
    assert bands.index(read["band_after"]) == bands.index(band_before) + 1


# ── the payload the persona screen renders ────────────────────────────────
def test_summarise_carries_the_band_the_split_and_the_model_read():
    profile, read = to_profile(FULL, use_gemma=False)
    payload = summarise(profile, read)
    assert payload["risk_band"] in {"conservative", "balanced", "aggressive"}
    assert round(sum(payload["allocation_pct"].values()), 2) == 100
    assert payload["gemma"]["rubric_score"] == payload["rubric_score"]
    assert payload["profile"]["capital"] == 300_000
