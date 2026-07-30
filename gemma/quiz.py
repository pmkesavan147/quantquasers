"""The onboarding survey: questions in, a `RiskProfile` out.

Wording is Track 1's. What changed is where the answers go — every one of them
now lands on a field of `core.contracts.RiskProfile`, which is what
`trading/allocation.py` scores and what `POST /api/account` accepts. There is
exactly one rubric in this system (0–11, in `trading/allocation.py`) and this
module feeds it rather than keeping a second score of its own.

The two free-text questions are the only place a model is involved, and only as
a second opinion on the horizon.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from core.contracts import Horizon, RiskProfile
from gemma.scorers import personality_report, profile_user
from trading.allocation import allocate, risk_band, rubric_score

QuestionKind = Literal["single", "multi", "number", "slider", "text", "boolean"]


class Option(BaseModel):
    value: str
    label: str


class Question(BaseModel):
    id: str
    text: str
    kind: QuestionKind
    options: list[Option] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None
    placeholder: str | None = None
    # False for the questions a demo can skip; the frontend still shows them.
    required: bool = True
    help: str | None = None


def _opts(pairs: list[tuple[str, str]]) -> list[Option]:
    return [Option(value=v, label=l) for v, l in pairs]


# Capital ceiling matches trading/config.py's max_capital — the risk manager
# will not size beyond it, so offering more on the slider would be a lie.
CAPITAL_MIN, CAPITAL_MAX = 10_000.0, 500_000.0

QUESTIONS: list[Question] = [
    Question(
        id="capital",
        text="How much capital are you putting to work?",
        kind="slider",
        min=CAPITAL_MIN, max=CAPITAL_MAX, step=5_000, unit="₹",
        help="Every desk's limit is a share of this number. Paper money either way.",
    ),
    Question(
        id="horizons",
        text="Which of these do you actually want to trade?",
        kind="multi",
        options=_opts([
            ("day", "Intraday — minutes to hours, squared off the same day"),
            ("swing", "Swing — days to weeks"),
            ("long_term", "Long-term — months to years"),
        ]),
        help="Pick more than one and capital is split across them.",
    ),
    Question(
        id="day_trading",
        text="Do you want intraday trading switched on at all?",
        kind="boolean",
        help="Answering no removes the intraday desk entirely, even if you "
             "picked it above.",
    ),
    Question(
        id="drawdown",
        text="Your portfolio drops in a month. At what point would you stop "
             "sleeping?",
        kind="single",
        options=_opts([
            ("10", "Down 10% — that already hurts"),
            ("20", "Down 20% — uncomfortable but survivable"),
            ("30", "Down 30% — it happens"),
            ("40", "Down 40% — I would be buying"),
        ]),
        help="The one question phrased in money you could actually lose, so it "
             "carries the most weight in the rubric.",
    ),
    Question(
        id="experience",
        text="How would you describe your trading experience?",
        kind="single",
        options=_opts([
            ("new", "New to this"),
            ("1-3y", "One to three years"),
            ("3y+", "Three years or more, active"),
        ]),
    ),
    Question(
        id="allowed_caps",
        text="Which sizes of company are you willing to hold?",
        kind="multi",
        options=_opts([
            ("large", "Large-cap — the top 100 by market cap"),
            ("mid", "Mid-cap — ranks 101 to 250"),
            ("small", "Small-cap — 251 and below"),
            ("micro", "Micro-cap — under ₹500 crore, thin and volatile"),
        ]),
        help="Anything you leave out becomes a hard refusal, not a warning.",
    ),
    Question(
        id="uses_leverage",
        text="Do you use leverage or margin?",
        kind="boolean",
    ),
    Question(
        id="sip_amount",
        text="Do you want a recurring investment (SIP) alongside this?",
        kind="slider",
        min=0, max=50_000, step=1_000, unit="₹",
        required=False,
        help="A SIP deploys on schedule regardless of sentiment. Sentiment "
             "picks which stocks it buys, never whether it invests.",
    ),
    Question(
        id="sip_frequency",
        text="How often should the SIP run?",
        kind="single",
        options=_opts([
            ("none", "Not using a SIP"),
            ("weekly", "Weekly"),
            ("monthly", "Monthly"),
        ]),
        required=False,
    ),
    # ── the written questions ────────────────────────────────────────────
    # These three are the only input a model sees, so they are written to
    # elicit evidence rather than opinion. "How do you feel about the market?"
    # — the question this replaced — produced market predictions we do not use
    # and told us nothing about the person. What predicts behaviour is what
    # someone did last time, and how much attention they actually have.
    Question(
        id="open_reaction",
        text="Think of the last time something you held dropped hard. What did "
             "you actually do?",
        kind="text",
        required=False,
        placeholder="e.g. I sold half the next morning and regretted it, or: I "
                    "didn't open the app for a week, or: I've never held "
                    "through a fall like that.",
        help="What you did last time, not what you would like to do next time. "
             "This answer carries the most weight.",
    ),
    Question(
        id="open_rhythm",
        text="Realistically, when in your week would you look at this — and "
             "what would make you act?",
        kind="text",
        required=False,
        placeholder="e.g. I check between meetings but I can't watch a screen; "
                    "I'd only act on results or a big fall.",
        help="Attention is the constraint most people underestimate. Intraday "
             "needs hours; long-term needs almost none.",
    ),
    Question(
        id="open_goal",
        text="What would make you say this worked — and by when?",
        kind="text",
        required=False,
        placeholder="e.g. Beating my FD by a few points over three years, "
                    "without losing sleep.",
        help="A number and a date, if you have one. 'By when' tells us more "
             "than 'how much'.",
    ),
]

# Answers to these are the only text Gemma ever reads about the user. Ordered
# by how much the profiler weighs them.
FREE_TEXT_IDS = ("open_reaction", "open_rhythm", "open_goal")

QUESTION_BY_ID = {q.id: q for q in QUESTIONS}

DRAWDOWN_DEFAULT = 25.0


# ── answers → profile ────────────────────────────────────────────────────
def _as_list(value: Any, allowed: set[str], default: list[str]) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return default
    kept = [v for v in value if v in allowed]
    return kept or default


def to_profile(answers: dict, *, use_gemma: bool = True) -> tuple[RiskProfile, dict]:
    """Build the profile, then ask Gemma for a second opinion on the horizon.

    Returns `(profile, gemma_read)`. `gemma_read` is diagnostics for the UI —
    what the model said, how confident it was, and whether that was enough to
    count. The allocation code applies its own floor; nothing here decides.
    """
    horizons_raw = _as_list(
        answers.get("horizons"), {"day", "swing", "long_term"},
        ["day", "swing", "long_term"],
    )
    caps = _as_list(
        answers.get("allowed_caps"), {"large", "mid", "small", "micro"},
        ["large", "mid", "small"],
    )

    try:
        drawdown = float(answers.get("drawdown", DRAWDOWN_DEFAULT))
    except (TypeError, ValueError):
        drawdown = DRAWDOWN_DEFAULT
    drawdown = max(1.0, min(100.0, drawdown))

    experience = answers.get("experience")
    if experience not in ("new", "1-3y", "3y+"):
        experience = "1-3y"

    try:
        capital = float(answers.get("capital") or CAPITAL_MAX)
    except (TypeError, ValueError):
        capital = CAPITAL_MAX
    capital = max(1.0, capital)

    try:
        sip_amount = max(0.0, float(answers.get("sip_amount") or 0.0))
    except (TypeError, ValueError):
        sip_amount = 0.0
    sip_frequency = answers.get("sip_frequency")
    if sip_frequency not in ("none", "weekly", "monthly"):
        sip_frequency = "monthly" if sip_amount > 0 else "none"
    if sip_amount > 0 and sip_frequency == "none":
        sip_frequency = "monthly"
    if sip_amount == 0:
        sip_frequency = "none"

    # Explicit consent governs. Someone who ticked "intraday" and then said no
    # to day trading gets no intraday desk — the stricter answer wins.
    day_trading = bool(answers.get("day_trading", "day" in horizons_raw))

    profile = RiskProfile(
        capital=capital,
        horizons=[Horizon(h) for h in horizons_raw],
        allowed_caps=caps,  # type: ignore[arg-type]
        max_drawdown_pct=drawdown,
        experience=experience,  # type: ignore[arg-type]
        day_trading=day_trading,
        uses_leverage=bool(answers.get("uses_leverage", False)),
        sip_amount=sip_amount,
        sip_frequency=sip_frequency,  # type: ignore[arg-type]
    )

    score = rubric_score(profile)
    band_before = risk_band(profile)

    gemma_read: dict = {
        "trader_type": None,
        "confidence": 0.0,
        "reasoning": "Free text not read.",
        "rubric_score": score,
        "rubric_band": band_before,
        "band_after": band_before,
        "moved_band": False,
    }

    if use_gemma:
        mcq = {
            "horizons": horizons_raw, "day_trading": day_trading,
            "drawdown_pct": drawdown, "experience": experience,
            "allowed_caps": caps, "uses_leverage": profile.uses_leverage,
        }
        trader_type, confidence, reasoning = profile_user(
            rubric_score=score,
            rubric_band=band_before,
            mcq=mcq,
            free_text=free_text_from(answers),
        )
        if trader_type is not None:
            profile = profile.model_copy(
                update={"trader_type": trader_type, "confidence": confidence}
            )
        band_after = risk_band(profile)
        gemma_read.update(
            trader_type=trader_type.value if trader_type else None,
            confidence=confidence,
            reasoning=reasoning,
            band_after=band_after,
            moved_band=band_after != band_before,
        )

    return profile, gemma_read


def free_text_from(answers: dict) -> dict[str, str]:
    """`{question text: answer}` for the written questions that were answered.

    Keyed by the question rather than the field id so the model knows which
    answer describes past behaviour and which describes intent — that
    distinction is most of the signal.
    """
    out: dict[str, str] = {}
    for qid in FREE_TEXT_IDS:
        answer = str(answers.get(qid) or "").strip()
        if answer:
            out[QUESTION_BY_ID[qid].text] = answer
    return out


def report_for(profile: RiskProfile, answers: dict) -> str:
    return personality_report(
        band=risk_band(profile),
        rubric_score=rubric_score(profile),
        free_text=free_text_from(answers),
    )


def summarise(profile: RiskProfile, gemma_read: dict) -> dict:
    """One payload the persona screen can render without a second round trip."""
    return {
        "profile": profile.model_dump(mode="json"),
        "risk_band": risk_band(profile),
        "rubric_score": rubric_score(profile),
        "allocation_pct": allocate(profile),
        "gemma": gemma_read,
    }
