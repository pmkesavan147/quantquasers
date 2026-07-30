"""Env-driven configuration and desk config loading.

Risk limits are read once at startup and handed to the RiskManager as
frozen values. There is deliberately no code path that turns a limit off.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from core.contracts import Horizon

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DESKS_FILE = ROOT / "trading" / "desks.yaml"
ALLOWLIST_FILE = ROOT / "trading" / "allowlist.txt"


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _b(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes"}


def _parse_time(raw: str | None) -> time | None:
    if not raw:
        return None
    hh, mm = raw.split(":")
    return time(int(hh), int(mm))


# ── risk limits ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RiskLimits:
    max_capital: float = field(default_factory=lambda: _f("MAX_CAPITAL", 100_000))
    max_position_pct: float = field(default_factory=lambda: _f("MAX_POSITION_PCT", 10))
    daily_loss_limit_pct: float = field(
        default_factory=lambda: _f("DAILY_LOSS_LIMIT_PCT", 2)
    )
    max_orders_per_day: int = field(
        default_factory=lambda: int(_f("MAX_ORDERS_PER_DAY", 10))
    )
    # Firm-level intraday switch. Independent of the user's mandate, which
    # the desk checks separately — two gates, defence in depth.
    allow_intraday: bool = field(default_factory=lambda: _b("ALLOW_INTRADAY", True))
    allowlist: tuple[str, ...] = ()

    @staticmethod
    def load(allowlist_path: Path | None = None) -> "RiskLimits":
        path = allowlist_path or ALLOWLIST_FILE
        symbols: tuple[str, ...] = ()
        if path.exists():
            symbols = tuple(
                line.strip().upper()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
        return RiskLimits(allowlist=symbols)


# ── desk config ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EntryRules:
    min_sentiment: float
    min_confidence: float
    min_articles: int
    max_sentiment_age_hours: float
    max_prior_move_pct: float
    prior_move_field: str


@dataclass(frozen=True)
class DeskConfig:
    name: str
    horizon: Horizon
    allocation_pct: float
    enabled: bool
    product: str                      # "MIS" | "CNC"
    max_positions: int
    entry: EntryRules
    exit_sentiment: float
    stop_loss_pct: float | None
    target_pct: float | None
    entry_window: tuple[time, time] | None
    square_off: time | None
    min_hold_days: int | None
    max_hold_days: int | None
    rebalance_every_days: int | None

    def capital(self, limits: RiskLimits) -> float:
        return limits.max_capital * self.allocation_pct / 100

    def slot_value(self, limits: RiskLimits) -> float:
        return self.capital(limits) / max(1, self.max_positions)


def load_desks(path: Path | None = None) -> dict[str, DeskConfig]:
    raw = yaml.safe_load((path or DESKS_FILE).read_text(encoding="utf-8"))
    out: dict[str, DeskConfig] = {}
    for name, d in raw["desks"].items():
        e = d["entry"]
        window = d.get("entry_window")
        out[name] = DeskConfig(
            name=name,
            horizon=Horizon(d["horizon"]),
            allocation_pct=float(d["allocation_pct"]),
            enabled=bool(d["enabled"]),
            product=d["product"],
            max_positions=int(d["max_positions"]),
            entry=EntryRules(
                min_sentiment=float(e["min_sentiment"]),
                min_confidence=float(e["min_confidence"]),
                min_articles=int(e["min_articles"]),
                max_sentiment_age_hours=float(e["max_sentiment_age_hours"]),
                max_prior_move_pct=float(e["max_prior_move_pct"]),
                prior_move_field=e.get("prior_move_field", "move_1d_pct"),
            ),
            exit_sentiment=float(d["exit_sentiment"]),
            stop_loss_pct=d.get("stop_loss_pct"),
            target_pct=d.get("target_pct"),
            entry_window=(
                (_parse_time(window[0]), _parse_time(window[1])) if window else None
            ),
            square_off=_parse_time(d.get("square_off")),
            min_hold_days=d.get("min_hold_days"),
            max_hold_days=d.get("max_hold_days"),
            rebalance_every_days=d.get("rebalance_every_days"),
        )

    total = sum(x.allocation_pct for x in out.values())
    if abs(total - 100) > 0.01:
        raise ValueError(f"desk allocations must sum to 100, got {total}")
    return out
