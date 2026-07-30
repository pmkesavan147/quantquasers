"""OHLCV in, `QuantMetrics` out. Pure pandas, no LLM, no network.

`metrics_from_frames()` takes DataFrames so it can be tested with synthetic
prices; `fetch()` is the thin wrapper that goes to `ingest.prices` and falls
back to the fixtures when a symbol has no price history at all.

`adtv_cr` drives the intraday liquidity refusal, so it is computed the boring
way: mean of Close × Volume over the last 30 sessions, divided by 1e7 to get ₹
crore. Getting this wrong makes the refusal engine lie.
"""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from core.contracts import QuantMetrics
from ingest.prices import INDEX_SYMBOL, history
from selection.universe import row as universe_row

ADTV_WINDOW = 30
TRADING_DAYS = 252


def _rsi14(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    last_gain, last_loss = float(gain.iloc[-1]), float(loss.iloc[-1])
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0
    rs = last_gain / last_loss
    return round(100 - (100 / (1 + rs)), 2)


def _atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """True range, not the naive high-minus-low: gaps are most of the range on
    Indian mid-caps and ignoring them understates day-trade viability."""
    if len(df) < period + 1:
        return 0.0
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.rolling(period).mean().iloc[-1])
    last = float(df["Close"].iloc[-1])
    return round(atr / last * 100, 2) if last else 0.0


def _max_drawdown_pct(close: pd.Series) -> float:
    if close.empty:
        return 0.0
    running_max = close.cummax()
    drawdown = (close / running_max - 1.0).min()
    return round(abs(float(drawdown)) * 100, 2)


def _beta(returns: pd.Series, market: pd.Series) -> float:
    joined = pd.concat([returns, market], axis=1, join="inner").dropna()
    if len(joined) < 30:
        return 1.0
    r, m = joined.iloc[:, 0], joined.iloc[:, 1]
    var = float(m.var())
    if var == 0:
        return 1.0
    return round(float(r.cov(m)) / var, 2)


def _sma(close: pd.Series, window: int) -> float:
    if len(close) < window:
        return round(float(close.mean()), 2)
    return round(float(close.rolling(window).mean().iloc[-1]), 2)


def _move_pct(close: pd.Series, days: int) -> float | None:
    if len(close) <= days:
        return None
    past = float(close.iloc[-1 - days])
    if past == 0:
        return None
    return round((float(close.iloc[-1]) / past - 1.0) * 100, 2)


def metrics_from_frames(
    symbol: str,
    df: pd.DataFrame,
    index_df: pd.DataFrame | None = None,
) -> QuantMetrics:
    """Every field of `QuantMetrics` from a single price frame. No I/O."""
    info = universe_row(symbol)
    close = df["Close"].astype(float)
    returns = close.pct_change().dropna()

    annual_vol = (
        round(float(returns.std()) * math.sqrt(TRADING_DAYS) * 100, 2)
        if len(returns) > 1
        else 0.0
    )

    beta = 1.0
    if index_df is not None and not index_df.empty:
        beta = _beta(returns, index_df["Close"].astype(float).pct_change().dropna())

    tail = df.tail(ADTV_WINDOW)
    adtv_cr = round(
        float((tail["Close"].astype(float) * tail["Volume"].astype(float)).mean()) / 1e7,
        2,
    )

    high_52w = float(close.tail(TRADING_DAYS).max())
    ltp = float(close.iloc[-1])
    dist_52w = round((ltp / high_52w - 1.0) * 100, 2) if high_52w else 0.0

    return QuantMetrics(
        symbol=symbol.upper(),
        name=info.name if info else symbol,
        cap_bucket=info.cap_bucket if info else "small",
        mcap_cr=info.mcap_cr if info else 0.0,
        ltp=round(ltp, 2),
        annual_vol=annual_vol,
        beta=beta,
        max_drawdown_1y=_max_drawdown_pct(close),
        adtv_cr=adtv_cr,
        atr_pct=_atr_pct(df),
        rsi14=_rsi14(close),
        sma20=_sma(close, 20),
        sma50=_sma(close, 50),
        sma200=_sma(close, 200),
        dist_52w_high_pct=dist_52w,
        asm_gsm_flag=info.asm_gsm_flag if info else False,
        move_1d_pct=_move_pct(close, 1),
        move_5d_pct=_move_pct(close, 5),
        move_20d_pct=_move_pct(close, 20),
    )


_index_cache: pd.DataFrame | None = None


def _index_history(allow_network: bool) -> pd.DataFrame:
    global _index_cache
    if _index_cache is None:
        _index_cache = history(INDEX_SYMBOL, allow_network=allow_network)
    return _index_cache


def fetch(symbol: str, *, allow_network: bool = True) -> QuantMetrics | None:
    """Live metrics for one symbol, or None when there is no price history.

    None is a real answer: it means the pipeline should fall back to committed
    fixture metrics rather than invent numbers for a symbol Yahoo cannot price.
    """
    df = history(symbol, allow_network=allow_network)
    if df.empty or len(df) < 25:
        return None
    return metrics_from_frames(symbol, df, _index_history(allow_network))


def as_of(symbol: str, *, allow_network: bool = True) -> datetime | None:
    df = history(symbol, allow_network=allow_network)
    if df.empty:
        return None
    last = df.index[-1]
    return last.to_pydatetime() if hasattr(last, "to_pydatetime") else None
