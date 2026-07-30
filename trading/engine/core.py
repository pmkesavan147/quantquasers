"""The engine — orchestration only.

Order of operations, per desk:

    exits proposed  ->  entries proposed  ->  RISK MANAGER  ->  broker  ->  journal

Every step writes to the journal. Nothing is stored anywhere else: desk books
are rebuilt by replaying journaled fills, so the ledger cannot disagree with
the book.

CLI:
    python -m trading.engine.core --desk swing --fixtures fixtures
    python -m trading.engine.core --all --simulate-day
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from core.contracts import Candidate, SymbolSentiment
from trading.config import DeskConfig, RiskLimits, load_desks
from trading.desks import Skip, open_positions, propose_entries, propose_exits
from trading.execution.broker import InsufficientFunds, NotFilled
from trading.execution.gate import build_broker, resolve_mode
from trading.execution.quotes import MockQuoteSource, QuoteSource
from trading.journal.store import Journal
from trading.models import DeskState, Fill, PortfolioState, Position, ProposedOrder
from trading.risk.manager import PortfolioState as RiskState
from trading.risk.manager import RiskManager

ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class DeskRun:
    desk: str
    proposals: list[ProposedOrder] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    vetoed: list[tuple[str, str]] = field(default_factory=list)   # (symbol, rule)
    resized: list[tuple[str, str]] = field(default_factory=list)
    skips: list[Skip] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.desk}: {len(self.fills)} filled, {len(self.vetoed)} vetoed, "
            f"{len(self.resized)} resized, {len(self.skips)} skipped, "
            f"{len(self.errors)} errored"
        )


class Engine:
    def __init__(
        self,
        quotes: QuoteSource,
        journal: Journal | None = None,
        limits: RiskLimits | None = None,
        desks: dict[str, DeskConfig] | None = None,
    ):
        self.quotes = quotes
        self.journal = journal or Journal()
        self.limits = limits or RiskLimits.load()
        self.desks = desks or load_desks()
        self.risk = RiskManager(self.limits, self.journal)
        self.mode, self.gate_reasons = resolve_mode()

        # One broker per desk — each desk owns a separate book, replayed from
        # its own fills in the shared journal.
        self.brokers = {}
        for name, cfg in self.desks.items():
            broker = build_broker(name, quotes, cfg.capital(self.limits))
            broker.restore_from_journal(self.journal)
            self.brokers[name] = broker

    # ── P&L ──────────────────────────────────────────────────────────────
    def realised_today(self, desk: str | None = None) -> float:
        total = 0.0
        for e in self.journal.for_day(date.today(), kind="fill"):
            f = e["payload"]
            if desk is not None and f.get("desk") != desk:
                continue
            total += float(f.get("realised") or 0.0)
        return total

    def day_pnl(self, desk: str | None = None) -> float:
        """Realised today plus total unrealised.

        Deliberately conservative: unrealised here is measured from average
        cost, not from yesterday's close, so for multi-day positions it is
        cumulative rather than same-day. That makes the kill switch fire
        EARLIER than a strict same-day figure would, which is the right
        direction for a safety limit to be wrong in.
        """
        names = [desk] if desk else list(self.desks)
        unreal = sum(self.brokers[n].unrealised() for n in names)
        return self.realised_today(desk) + unreal

    def orders_today(self) -> int:
        return self.journal.count_today("fill")

    def _risk_state(self, desk: DeskConfig) -> RiskState:
        """Firm-wide exposure plus this desk's own, as the CRO needs both."""
        positions: dict[str, int] = {}
        position_value: dict[str, float] = {}
        for name, broker in self.brokers.items():
            for sym, qty in broker.positions().items():
                positions[sym] = positions.get(sym, 0) + qty
                position_value[sym] = (
                    position_value.get(sym, 0.0) + qty * broker.avg_price(sym)
                )
        return RiskState(
            positions=positions,
            position_value=position_value,
            day_pnl=self.day_pnl(),
            orders_today=self.orders_today(),
            desk_deployed=self.brokers[desk.name].deployed(),
        )

    # ── the run ──────────────────────────────────────────────────────────
    def run_desk(
        self,
        name: str,
        candidates: list[Candidate],
        sentiments: dict[str, SymbolSentiment] | None = None,
        now: datetime | None = None,
        day_trading_allowed: bool = True,
    ) -> DeskRun:
        desk = self.desks[name]
        now = now or datetime.now()
        run = DeskRun(desk=name)

        if not desk.enabled:
            self.journal.append("note", {"desk": name, "event": "disabled"})
            return run

        broker = self.brokers[name]
        sentiments = sentiments or {c.symbol: c.sentiment for c in candidates}

        # Exits first — freeing a slot on a reversal outranks filling one.
        exits = propose_exits(desk, broker, sentiments, self.quotes, now)
        exiting = {o.symbol for o in exits}

        entries, skips = propose_entries(
            desk, candidates, broker, self.limits, self.quotes, now,
            day_trading_allowed=day_trading_allowed, exiting=exiting,
        )
        run.skips = skips
        for s in skips:
            self.journal.append(
                "skip", {"desk": name, "symbol": s.symbol, "reason": s.reason}
            )

        run.proposals = exits + entries

        for order in run.proposals:
            self.journal.append("proposal", order.model_dump(mode="json"))

            quote = self.quotes.ltp(order.symbol) or 0.0
            verdict = self.risk.evaluate(
                order, self._risk_state(desk), quote, desk=desk, now=now
            )

            if verdict.decision == "veto":
                run.vetoed.append((order.symbol, verdict.rule_fired or "veto"))
                continue
            if verdict.decision == "resize":
                run.resized.append((order.symbol, verdict.rule_fired or "resize"))

            try:
                fill = broker.place(order, verdict.final_qty)
            except (InsufficientFunds, NotFilled, RuntimeError) as e:
                run.errors.append((order.symbol, str(e)))
                self.journal.append(
                    "alert",
                    {"desk": name, "symbol": order.symbol,
                     "event": "fill_failed", "error": str(e)},
                )
                continue

            run.fills.append(fill)
            self.journal.append("fill", fill.model_dump(mode="json"))

        return run

    def run_all(
        self,
        candidates_by_horizon: dict[str, list[Candidate]],
        now: datetime | None = None,
        day_trading_allowed: bool = True,
    ) -> list[DeskRun]:
        return [
            self.run_desk(
                name,
                candidates_by_horizon.get(cfg.horizon.value, []),
                now=now,
                day_trading_allowed=day_trading_allowed,
            )
            for name, cfg in self.desks.items()
        ]

    # ── reads for the API ────────────────────────────────────────────────
    def desk_state(self, name: str) -> DeskState:
        desk, broker = self.desks[name], self.brokers[name]
        return DeskState(
            name=name,
            horizon=desk.horizon.value,
            enabled=desk.enabled,
            product=desk.product,
            allocation_pct=desk.allocation_pct,
            capital=round(desk.capital(self.limits), 2),
            deployed=round(broker.deployed(), 2),
            cash=round(broker.cash(), 2),
            open_positions=len(broker.positions()),
            max_positions=desk.max_positions,
            unrealised_pnl=round(broker.unrealised(), 2),
            realised_pnl_today=round(self.realised_today(name), 2),
        )

    def portfolio(self) -> PortfolioState:
        positions: list[Position] = []
        for name, cfg in self.desks.items():
            positions.extend(open_positions(cfg, self.brokers[name]))
        desks = [self.desk_state(n) for n in self.desks]
        return PortfolioState(
            mode=self.mode,
            halted=self.risk.halted,
            halt_reason=self.risk.halt_reason,
            capital=self.limits.max_capital,
            deployed=round(sum(d.deployed for d in desks), 2),
            cash=round(sum(d.cash for d in desks), 2),
            unrealised_pnl=round(sum(d.unrealised_pnl for d in desks), 2),
            realised_pnl_today=round(sum(d.realised_pnl_today for d in desks), 2),
            day_pnl=round(self.day_pnl(), 2),
            orders_today=self.orders_today(),
            positions=positions,
            desks=desks,
        )


# ── fixtures + CLI ───────────────────────────────────────────────────────
def load_fixture_candidates(
    dir_: Path, rebase_to: datetime | None = None
) -> dict[str, list[Candidate]]:
    """Track 1 ships these. Until their API is live, the engine runs on them.

    Fixture timestamps are rebased so the newest headline in the file becomes
    `rebase_to`, with every other timestamp shifted by the same delta. Without
    this, committed fixtures fail the freshness gate the day after they're
    written and every entry gets rejected as `sentiment_stale` — which looks
    like a bug in the rules rather than stale test data.
    """
    out: dict[str, list[Candidate]] = {}
    for horizon, fname in (
        ("day", "candidates_day.json"),
        ("swing", "candidates_swing.json"),
        ("long_term", "candidates_long.json"),
    ):
        path = dir_ / fname
        if not path.exists():
            out[horizon] = []
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        cands = [Candidate.model_validate(r) for r in raw]
        if rebase_to is not None:
            cands = _rebase(cands, rebase_to)
        out[horizon] = cands
    return out


def _rebase(cands: list[Candidate], to: datetime) -> list[Candidate]:
    stamps = [c.sentiment.as_of for c in cands]
    stamps += [h.published_at for c in cands for h in c.sentiment.drivers]
    if not stamps:
        return cands
    newest = max(stamps)
    if (newest.tzinfo is None) != (to.tzinfo is None):
        to = to.replace(tzinfo=newest.tzinfo)
    delta = to - newest
    for c in cands:
        c.sentiment.as_of = c.sentiment.as_of + delta
        for h in c.sentiment.drivers:
            h.published_at = h.published_at + delta
    return cands


def _base_prices(cands: dict[str, list[Candidate]]) -> dict[str, float]:
    return {c.symbol: c.quant.ltp for lst in cands.values() for c in lst}


def main(argv: list[str] | None = None) -> int:
    # The Windows console defaults to cp1252, which cannot encode ₹ and
    # crashes on the first fill line. Demo machines are Windows.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="QuantQuasers trading engine")
    ap.add_argument("--desk", help="run one desk (day | swing | long_term)")
    ap.add_argument("--all", action="store_true", help="run every enabled desk")
    ap.add_argument("--fixtures", default="fixtures", help="fixture directory")
    ap.add_argument("--db", default=None, help="journal path (default repo root)")
    ap.add_argument("--at", default=None, help="pretend it is HH:MM (e.g. 15:20)")
    args = ap.parse_args(argv)

    now = datetime.now()
    if args.at:
        hh, mm = args.at.split(":")
        now = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)

    cands = load_fixture_candidates(ROOT / args.fixtures, rebase_to=now)
    total = sum(len(v) for v in cands.values())
    if total == 0:
        print(f"no candidates found in {args.fixtures}/ — Track 1 owes you fixtures")
        return 1

    journal = Journal(args.db) if args.db else Journal()
    engine = Engine(MockQuoteSource(_base_prices(cands)), journal=journal)

    print(f"mode={engine.mode}  gate_armed={engine.mode == 'live'}")
    if engine.gate_reasons:
        print("gate shut because: " + "; ".join(engine.gate_reasons))
    print(f"as of {now:%Y-%m-%d %H:%M}\n")

    runs = (
        engine.run_all(cands, now=now)
        if args.all or not args.desk
        else [engine.run_desk(args.desk, cands.get(
            engine.desks[args.desk].horizon.value, []), now=now)]
    )

    for r in runs:
        print(r.summary())
        for f in r.fills:
            print(f"    FILL  {f.side:4} {f.qty:>5} {f.symbol:<12} "
                  f"@ ₹{f.price:>10,.2f}  costs ₹{f.costs:>8,.2f}  {f.reason}")
        for sym, rule in r.vetoed:
            print(f"    VETO  {sym:<12} {rule}")
        for sym, rule in r.resized:
            print(f"    RESIZE {sym:<11} {rule}")
        for s in r.skips:
            print(f"    skip  {s.symbol:<12} {s.reason}")
        for sym, err in r.errors:
            print(f"    ERROR {sym:<12} {err}")
        print()

    p = engine.portfolio()
    print(f"firm: deployed ₹{p.deployed:,.0f} / ₹{p.capital:,.0f}  "
          f"cash ₹{p.cash:,.0f}  unrealised ₹{p.unrealised_pnl:,.0f}  "
          f"realised today ₹{p.realised_pnl_today:,.0f}  "
          f"orders today {p.orders_today}")
    if p.halted:
        print(f"HALTED: {p.halt_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
