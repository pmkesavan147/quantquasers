"""Test factories — build valid contract objects without touching the network.

Keeps the tests readable: each test states only the field it cares about.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.contracts import (
    Candidate,
    HeadlineScore,
    MandateVerdict,
    QuantMetrics,
    Reason,
    SymbolSentiment,
)
from trading.models import Position

NOW = datetime(2026, 7, 30, 10, 30)


def headline(
    symbol: str = "TATAMOTORS",
    event_type: str = "earnings",
    sentiment: float = 0.6,
    age_hours: float = 1.0,
    now: datetime = NOW,
    materiality: int = 4,
) -> HeadlineScore:
    return HeadlineScore(
        id=f"{symbol}-{event_type}-{age_hours}",
        symbol=symbol,
        title=f"{symbol} {event_type} headline",
        source="Test Wire",
        url="https://example.com/x",
        published_at=now - timedelta(hours=age_hours),
        sentiment=sentiment,
        label="positive" if sentiment > 0.1 else ("negative" if sentiment < -0.1 else "neutral"),
        event_type=event_type,
        materiality=materiality,
        rationale="test",
        model="gemma3:4b",
    )


def sentiment(
    symbol: str = "TATAMOTORS",
    score: float = 0.60,
    confidence: float = 0.75,
    n_articles: int = 10,
    age_hours: float = 1.0,
    now: datetime = NOW,
    drivers: list[HeadlineScore] | None = None,
) -> SymbolSentiment:
    return SymbolSentiment(
        symbol=symbol,
        as_of=now - timedelta(hours=age_hours),
        score=score,
        confidence=confidence,
        n_articles=n_articles,
        top_events=[],
        drivers=drivers if drivers is not None else [headline(symbol, now=now)],
    )


def quant(
    symbol: str = "TATAMOTORS",
    ltp: float = 1000.0,
    cap_bucket: str = "large",
    adtv_cr: float = 400.0,
    move_1d_pct: float | None = 1.0,
    move_5d_pct: float | None = 2.0,
    move_20d_pct: float | None = 4.0,
    asm_gsm_flag: bool = False,
) -> QuantMetrics:
    return QuantMetrics(
        symbol=symbol,
        name=symbol.title(),
        cap_bucket=cap_bucket,
        mcap_cr=250_000.0,
        ltp=ltp,
        annual_vol=25.0,
        beta=1.0,
        max_drawdown_1y=15.0,
        adtv_cr=adtv_cr,
        atr_pct=2.0,
        rsi14=58.0,
        sma20=ltp * 0.98,
        sma50=ltp * 0.95,
        sma200=ltp * 0.90,
        dist_52w_high_pct=-5.0,
        asm_gsm_flag=asm_gsm_flag,
        move_1d_pct=move_1d_pct,
        move_5d_pct=move_5d_pct,
        move_20d_pct=move_20d_pct,
    )


def candidate(
    symbol: str = "TATAMOTORS",
    horizon: str = "day",
    composite_score: float = 75.0,
    level: str = "SUITABLE",
    sent: SymbolSentiment | None = None,
    q: QuantMetrics | None = None,
    block_codes: tuple[str, ...] = (),
) -> Candidate:
    reasons = [
        Reason(code=c, severity="block", text="blocked", metric="m",
               value=1.0, threshold=0.0)
        for c in block_codes
    ]
    return Candidate(
        symbol=symbol,
        horizon=horizon,
        composite_score=composite_score,
        sentiment=sent or sentiment(symbol),
        quant=q or quant(symbol),
        verdict=MandateVerdict(level=level, reasons=reasons),
        explanation="test",
    )


def position(
    symbol: str = "TATAMOTORS",
    desk: str = "swing",
    qty: int = 10,
    avg_price: float = 1000.0,
    held_days: int = 5,
    now: datetime = NOW,
) -> Position:
    return Position(
        desk=desk,
        symbol=symbol,
        qty=qty,
        avg_price=avg_price,
        opened_at=now - timedelta(days=held_days),
        product="CNC",
    )
