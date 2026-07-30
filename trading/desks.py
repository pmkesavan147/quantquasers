"""Desks — one per horizon. Deliberately thin.

A desk turns Track 1's Candidate[] into ProposedOrder[]. It decides WHAT to
propose; it never decides whether the order is allowed (risk manager) or
where it goes (gate). All the interesting judgement lives in
sentiment_rules.py, which is pure and tested.

Exits are proposed before entries, always: freeing a slot on a reversal is
more urgent than filling one on a new signal, and it keeps max_positions
honest within a single run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.contracts import Candidate, SymbolSentiment
from trading.config import DeskConfig, RiskLimits
from trading.execution.quotes import QuoteSource
from trading.models import Position, ProposedOrder
from trading.sentiment_rules import conviction, conviction_qty, entry_allowed, exit_trigger


@dataclass
class Skip:
    """A candidate the desk declined, and why. Journaled and shown in the UI —
    the refusals are as interesting as the fills."""

    symbol: str
    reason: str


def open_positions(desk: DeskConfig, broker) -> list[Position]:
    return [
        Position(
            desk=desk.name,
            symbol=sym,
            qty=qty,
            avg_price=broker.avg_price(sym),
            opened_at=broker.opened_at(sym),
            product=desk.product,
        )
        for sym, qty in broker.positions().items()
    ]


# ── exits ────────────────────────────────────────────────────────────────
def propose_exits(
    desk: DeskConfig,
    broker,
    sentiments: dict[str, SymbolSentiment],
    quotes: QuoteSource,
    now: datetime,
) -> list[ProposedOrder]:
    orders: list[ProposedOrder] = []
    for pos in open_positions(desk, broker):
        ltp = quotes.ltp(pos.symbol)
        if ltp is None:
            continue
        trigger = exit_trigger(
            pos, sentiments.get(pos.symbol), desk, ltp, now
        )
        if trigger is None:
            continue
        orders.append(
            ProposedOrder(
                desk=desk.name,
                symbol=pos.symbol,
                side="SELL",
                qty=pos.qty,
                product=desk.product,
                reason=f"exit:{trigger} pnl={pos.pnl_pct(ltp):+.2f}% held={pos.held_days(now)}d",
            )
        )
    return orders


# ── entries ──────────────────────────────────────────────────────────────
def propose_entries(
    desk: DeskConfig,
    candidates: list[Candidate],
    broker,
    limits: RiskLimits,
    quotes: QuoteSource,
    now: datetime,
    day_trading_allowed: bool = True,
    exiting: set[str] | None = None,
) -> tuple[list[ProposedOrder], list[Skip]]:
    exiting = exiting or set()
    held = set(broker.positions())
    free_slots = desk.max_positions - len(held - exiting)

    orders: list[ProposedOrder] = []
    skips: list[Skip] = []

    # Best signal first, but the gate decides — ranking never overrides it.
    ranked = sorted(candidates, key=lambda c: c.composite_score, reverse=True)

    for cand in ranked:
        if cand.symbol in held:
            skips.append(Skip(cand.symbol, "already_held"))
            continue

        ok, why = entry_allowed(cand, desk, now, day_trading_allowed)
        if not ok:
            skips.append(Skip(cand.symbol, why or "rejected"))
            continue

        if free_slots <= 0:
            skips.append(Skip(cand.symbol, "no_free_slot"))
            continue

        ltp = quotes.ltp(cand.symbol) or cand.quant.ltp
        qty = conviction_qty(cand, desk, ltp, desk.slot_value(limits))
        if qty <= 0:
            skips.append(Skip(cand.symbol, "size_rounds_to_zero"))
            continue

        orders.append(
            ProposedOrder(
                desk=desk.name,
                symbol=cand.symbol,
                side="BUY",
                qty=qty,
                product=desk.product,
                reason=(
                    f"entry: sentiment {cand.sentiment.score:+.2f} "
                    f"conf {cand.sentiment.confidence:.2f} "
                    f"({cand.sentiment.n_articles} articles) "
                    f"conviction {conviction(cand):.2f} "
                    f"score {cand.composite_score:.0f} "
                    f"[{cand.verdict.level}]"
                ),
            )
        )
        free_slots -= 1

    return orders, skips
