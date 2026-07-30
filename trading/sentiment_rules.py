"""Sentiment -> order. The core of Track 2.

Three pure functions over plain data. No network, no LLM, no I/O — so the
whole entry/sizing/exit policy is testable in milliseconds and provably
free of model influence.

Why this module exists at all: Track 1's `composite_score` blends sentiment
with momentum and liquidity, so a high score does NOT imply positive
sentiment. Ranking on it alone buys stocks with bad news. Sentiment
therefore gets its own gate, its own sizing, and its own exit.
"""

from __future__ import annotations

from datetime import datetime

from core.contracts import Candidate, SymbolSentiment
from trading.config import DeskConfig
from trading.models import Position

# Material adverse events. Present in a fresh driver headline => no entry and
# immediate exit, whatever the aggregate score says. This is the case where
# the average lies: mildly positive coverage sitting on top of a pledge
# increase nets out to "fine" and is not fine.
BLOCKED_EVENTS: frozenset[str] = frozenset(
    {"promoter_pledge", "litigation", "regulatory"}
)

# A STRETCH mandate verdict is a warning, not a refusal — it enters, but at
# half conviction. Only OUTSIDE_MANDATE is a hard no.
STRETCH_CONVICTION_MULTIPLIER = 0.5


def _age_hours(as_of: datetime, now: datetime) -> float:
    """Tolerates one side being tz-aware and the other naive."""
    a, n = as_of, now
    if (a.tzinfo is None) != (n.tzinfo is None):
        a = a.replace(tzinfo=None)
        n = n.replace(tzinfo=None)
    return max(0.0, (n - a).total_seconds() / 3600)


def _fresh_blocked_event(
    sent: SymbolSentiment, now: datetime, window_hours: float
) -> str | None:
    """The first blocked event type found inside the freshness window."""
    for h in sent.drivers:
        if h.event_type in BLOCKED_EVENTS and _age_hours(h.published_at, now) <= window_hours:
            return h.event_type
    return None


def _prior_move(cand: Candidate, desk: DeskConfig) -> float | None:
    """The realised move the lag guard measures against, per desk horizon.

    None when Track 1 hasn't populated the field — the guard then degrades
    to a no-op rather than blocking every entry.
    """
    return getattr(cand.quant, desk.entry.prior_move_field, None)


# ── 1. entry gate ────────────────────────────────────────────────────────
def entry_allowed(
    cand: Candidate,
    desk: DeskConfig,
    now: datetime,
    day_trading_allowed: bool = True,
) -> tuple[bool, str | None]:
    """(ok, reason_if_not). Reason strings are journaled and rendered in the UI."""
    sent = cand.sentiment
    e = desk.entry

    if cand.horizon != desk.horizon:
        return False, "wrong_horizon"

    # The mandate guard outranks every signal. STRETCH passes (at reduced
    # size); only a hard block stops the order.
    if cand.verdict.level == "OUTSIDE_MANDATE":
        codes = ",".join(r.code for r in cand.verdict.reasons if r.severity == "block")
        return False, f"mandate_blocked:{codes}" if codes else "mandate_blocked"

    # The user's own mandate on leverage. Independent of the firm-level
    # ALLOW_INTRADAY switch the risk manager enforces — two gates.
    if desk.product == "MIS" and not day_trading_allowed:
        return False, "mandate_forbids_intraday"

    # Stale news is an absence of information, not a signal.
    age = _age_hours(sent.as_of, now)
    if age > e.max_sentiment_age_hours:
        return False, f"sentiment_stale:{age:.1f}h"

    blocked = _fresh_blocked_event(sent, now, e.max_sentiment_age_hours)
    if blocked:
        return False, f"blocked_event:{blocked}"

    if sent.score < e.min_sentiment:
        return False, f"sentiment_below_threshold:{sent.score:+.2f}"

    if sent.confidence < e.min_confidence:
        return False, f"confidence_below_threshold:{sent.confidence:.2f}"

    if sent.n_articles < e.min_articles:
        return False, f"insufficient_coverage:{sent.n_articles}"

    # Lag guard — the standard objection to sentiment trading is that by the
    # time news is measurable, price has moved. If it already ran in the
    # direction the news implies, the signal is priced in.
    move = _prior_move(cand, desk)
    if move is not None and move >= e.max_prior_move_pct:
        return False, f"sentiment_already_priced:{move:+.1f}%"

    if desk.entry_window is not None:
        start, end = desk.entry_window
        if not (start <= now.time() <= end):
            return False, "outside_entry_window"

    return True, None


# ── 2. conviction sizing ─────────────────────────────────────────────────
def conviction(cand: Candidate) -> float:
    """0..1. Sentiment strength scaled by how much we trust it."""
    score = min(1.0, max(0.0, cand.sentiment.score))
    c = score * cand.sentiment.confidence
    if cand.verdict.level == "STRETCH":
        c *= STRETCH_CONVICTION_MULTIPLIER
    return c


def conviction_qty(cand: Candidate, desk: DeskConfig, ltp: float,
                   slot_value: float) -> int:
    """Half a slot at zero conviction, a full slot at maximum.

    Floor at 50% so a marginal signal takes a small position rather than
    none; ceiling at 100% so conviction can never breach the desk's
    allocation. The risk manager's per-position cap still sits underneath
    and may resize — this is a preference, not a limit.
    """
    if ltp <= 0 or slot_value <= 0:
        return 0
    order_value = slot_value * (0.5 + 0.5 * conviction(cand))
    qty = int(order_value // ltp)

    # Conviction scales size; it must never turn an affordable entry into no
    # entry. On a high-priced share a half-slot can round to zero while the
    # full slot comfortably covers one — take the one. Without this the desk
    # silently excludes every stock priced above slot_value/2, which skews
    # the book toward cheap shares for no stated reason.
    if qty == 0 and slot_value >= ltp:
        qty = 1
    return qty


# ── 3. exit triggers ─────────────────────────────────────────────────────
def exit_trigger(
    pos: Position,
    sent: SymbolSentiment | None,
    desk: DeskConfig,
    ltp: float,
    now: datetime,
) -> str | None:
    """First trigger to fire wins. Returns the trigger name, or None to hold.

    Precedence is deliberate:
      square_off   mechanical — the broker will force it anyway
      blocked_event material adverse news, get out
      stop_loss    capital protection
      sentiment_reversal  the thesis is gone
      target       profit taking
      time_exit    housekeeping

    `min_hold_days` suppresses only the discretionary exits (reversal,
    target). It never suppresses a stop, a blocked event, or a square-off.
    """
    # 1. Intraday square-off. Mechanical, outranks everything.
    if desk.square_off is not None and now.time() >= desk.square_off:
        return "square_off"

    # 2. Material adverse news.
    if sent is not None:
        blocked = _fresh_blocked_event(sent, now, desk.entry.max_sentiment_age_hours)
        if blocked:
            return f"blocked_event:{blocked}"

    pnl = pos.pnl_pct(ltp)

    # 3. Price stop.
    if desk.stop_loss_pct is not None and pnl <= -desk.stop_loss_pct:
        return "stop_loss"

    held = pos.held_days(now)
    min_hold = desk.min_hold_days or 0
    discretionary_ok = held >= min_hold

    # 4. Sentiment reversal — the exit that makes this a sentiment system.
    #    Stale sentiment does NOT trigger it: an absence of news is not a
    #    sell signal, and force-exiting on it would turn a Wi-Fi outage into
    #    a liquidation event.
    if sent is not None and discretionary_ok:
        fresh = _age_hours(sent.as_of, now) <= desk.entry.max_sentiment_age_hours
        if fresh and sent.score < desk.exit_sentiment:
            return "sentiment_reversal"

    # 5. Target.
    if desk.target_pct is not None and discretionary_ok and pnl >= desk.target_pct:
        return "target"

    # 6. Time.
    if desk.max_hold_days is not None and held >= desk.max_hold_days:
        return "max_hold"
    if desk.rebalance_every_days is not None and held >= desk.rebalance_every_days:
        return "rebalance"

    return None
