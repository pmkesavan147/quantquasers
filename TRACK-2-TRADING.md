# Track 2 — Trade Automation (Kite Connect)

**Owner:** 1 dev · **Budget:** 12 hours · **Language:** Python 3.13

You own the floor. Candidates come in from Track 1, orders go out through one
risk manager to a broker that is paper today and Kite-capable tomorrow.

> **STATUS AT DEMO: PAPER. The live gate ships locked and is never armed.**

---

## 0. Shared contract (identical in all three track docs)

### Product

**QuantQuasers** reads the Indian market's news flow with Gemma, ranks stocks
against a user's declared trading mandate, and routes the survivors to three
automated desks — **day**, **swing**, **long-term** — that trade on paper
behind a live gate that is never armed.

### The one design principle everything hangs off

> **Gemma classifies and explains. It never decides and never counts.**

Sentiment scores, event tags and written explanations come from Gemma.
Every number that reaches a screen or an order — volatility, drawdown,
position size, P&L — comes from deterministic Python. If a judge asks
"could the model have made that number up?", the answer must be *no, structurally*.

For your track this is stronger still: **no module under `trading/` may import
anything under `gemma/`.** Enforce it with a test (§8).

### System flow

```
News RSS ─────► Gemma scorer ──────► SymbolSentiment ──┐
                                                        │
Survey ───────► Gemma profiler ────► RiskProfile ───────┤
                                                        ▼
yfinance ─────► QuantMetrics (pandas) ──────► Ranker + Mandate Guard
                                                        │  (deterministic)
                                                        ▼
                                              Candidate[] per horizon
                                                        ▼
                        day desk · swing desk · long-term desk
                                                        ▼
                                    RISK MANAGER (single CRO, no LLM)
                                                        ▼
                                    Broker: paper │ kite (gated, never armed)
                                                        ▼
                                        Append-only journal ──► FastAPI ──► Next.js
```

### Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI + Uvicorn |
| DB | SQLAlchemy · SQLite dev, `DATABASE_URL` swaps to Postgres |
| LLM | Gemma via Ollama (`gemma3:4b`) primary, Google AI Studio (`gemma-3-27b-it`) fallback |
| Market data | yfinance (`.NS` suffix), Kite Connect for quotes |
| Frontend | Next.js App Router + TypeScript + Tailwind + shadcn/ui |
| Broker | Kite Connect (`kiteconnect`), paper-first |

### Repo layout

```
quantquasers/
├── core/contracts.py        ← Track 1 ships this in hour 1. Frozen after.
├── ingest/ gemma/ select/   ← Track 1
├── trading/                 ← YOU
├── api/                     ← routes_sentiment.py (T1) · routes_trading.py (T2)
├── fixtures/                ← Track 1 ships in hour 1. Build against these.
├── web/                     ← Track 3 (Next.js)
└── tests/
```

### Frozen API surface

```
POST /api/profile                  → RiskProfile
GET  /api/sentiment/{symbol}       → SymbolSentiment
GET  /api/sentiment/feed?limit=50  → HeadlineScore[]
GET  /api/quant/{symbol}           → QuantMetrics
POST /api/candidates               → Candidate[]        body: {profile, horizon}
POST /api/orders/propose           → ProposedOrder[]    body: {candidates, desk}
POST /api/orders/execute           → Fill[]             paper unless gate armed
GET  /api/desks                    → DeskState[]
GET  /api/portfolio                → PortfolioState
GET  /api/journal?kind=&limit=     → JournalEntry[]
POST /api/control/pause|resume     → {halted, reason}
GET  /api/health                   → {ollama, kite, db, gate_armed, mode}
```

### Integration checkpoints

| Hour | Gate |
|---|---|
| **1** | `core/contracts.py` + `fixtures/*.json` pushed. Tracks 2 & 3 unblock. |
| **6** | End-to-end on fixtures: survey → candidates → paper fill → journal → UI |
| **10** | Fixtures swapped for live API on all screens |
| **11** | Full demo rehearsal, offline |

### Non-negotiables

1. No buy/sell recommendations to a user, no target prices.
2. `PAPER` badge visible on every screen that shows an order or a position.
3. Disclaimer footer everywhere.
4. The live gate ships **locked**. Nobody arms it during the hackathon.

---

## 1. Prior art — read this first

`C:\Pokemons\Trade Automation` is a mature working implementation of exactly
this architecture. **Port from it, don't reinvent it.** Files worth reading in
order:

| File | Take |
|---|---|
| `trading_bot/models.py` | `ProposedOrder` / `RiskVerdict` / `JournalEntry` — copy verbatim |
| `trading_bot/risk/manager.py` | The whole gauntlet. Your `evaluate()` is this, plus intraday rules. |
| `trading_bot/execution/broker.py` | `Broker` Protocol — `place / positions / cash` |
| `trading_bot/execution/{paper,kite,gate}.py` | The two implementations and the chooser |
| `trading_bot/desks.yaml` | Desk config shape |
| `backtester/engine/costs.py` | **Indian cost model — reuse, do not re-derive STT/GST rates** |
| `trading_bot/journal/store.py` | Append-only ledger |
| `README.md` | The compliance posture and graduation criteria |

Your one structural change: their desks are strategies (`buy_hold`, `momentum`,
`sma_cross`). **Yours are horizons** — day, swing, long-term — each fed by
Track 1's ranker for that horizon.

## 2. What you own

```
trading/models.py               ProposedOrder · RiskVerdict · Fill · JournalEntry
trading/config.py               RiskLimits per desk, loaded frozen
trading/desks.yaml              three desks, allocations, params
trading/desks.py                Desk → proposes orders from Candidate[]
trading/sentiment_rules.py      entry gate · conviction sizing · exit triggers (§3.5)
trading/risk/manager.py         THE CRO — every order passes through
trading/execution/broker.py     Protocol
trading/execution/paper.py      simulated fills with the real cost model
trading/execution/kite.py       Kite Connect adapter
trading/execution/gate.py       triple-lock chooser — ships LOCKED
trading/execution/costs.py      STT/GST/stamp/slippage (port from reference)
trading/journal/store.py        append-only SQLite ledger
trading/engine/core.py          run_desk() — the orchestration
api/routes_trading.py           FastAPI routes
```

## 3. The three desks

```yaml
# trading/desks.yaml
desks:
  day:
    horizon: day
    allocation_pct: 20
    enabled: true
    product: MIS                    # intraday margin
    params:
      max_positions: 3
      entry_window: ["09:30", "14:30"]
      square_off: "15:15"           # hard exit, no overnight carry
      stop_loss_pct: 1.0
      target_pct: 2.0
  swing:
    horizon: swing
    allocation_pct: 30
    enabled: true
    product: CNC
    params:
      max_positions: 5
      min_hold_days: 2
      max_hold_days: 15
      stop_loss_pct: 5.0
      target_pct: 12.0
  long_term:
    horizon: long_term
    allocation_pct: 50
    enabled: true
    product: CNC
    params:
      max_positions: 10
      rebalance_every_days: 21
      stop_loss_pct: null           # no stop; thesis-driven exit only
```

Allocations sum to 100. Each desk gets `MAX_CAPITAL * allocation_pct / 100`
and cannot spend beyond it — enforced in the risk manager, not the desk.

Allocation caps are enforced in the risk manager, not the desk. Everything
about *which* stock and *how much* is §3.5.

## 3.5 Sentiment → order — the core of this track

`composite_score` from Track 1 blends sentiment with momentum and liquidity, so
a high score does **not** imply positive sentiment. Ranking on it alone will buy
stocks with bad news. Sentiment gets its own gate, its own sizing, and its own
exit.

### Entry gate — all conditions, per desk

```yaml
# extends each desk's params in desks.yaml
day:
  entry:
    min_sentiment: 0.30        # SymbolSentiment.score
    min_confidence: 0.60
    min_articles: 3
    max_sentiment_age_hours: 6
    max_prior_move_pct: 3.0    # lag guard, today's move
swing:
  entry:
    min_sentiment: 0.20
    min_confidence: 0.50
    min_articles: 4
    max_sentiment_age_hours: 48
    max_prior_move_pct: 8.0    # over 5 sessions
long_term:
  entry:
    min_sentiment: 0.10
    min_confidence: 0.40
    min_articles: 5
    max_sentiment_age_hours: 168
    max_prior_move_pct: 15.0   # over 20 sessions
```

Shorter horizon ⇒ stricter thresholds and fresher news, because there's less
time for a weak signal to be right.

Plus a hard event block, all desks:
```python
BLOCKED_EVENTS = {"promoter_pledge", "litigation", "regulatory"}
```
If any driver headline inside the freshness window carries one of these, no
entry — whatever the score says. A positive aggregate sentiment sitting on top
of a pledge-increase headline is exactly the case where the average lies.

**The lag guard** answers the standard objection to sentiment trading: by the
time news is measurable, price has often already moved. If the stock has already
run more than `max_prior_move_pct` in the direction sentiment implies, skip it —
the signal is priced in. Journal the skip with reason `sentiment_already_priced`.
Being able to show that skip is a strong answer to a sharp judge.

### Conviction sizing

```python
conviction = clip(sentiment.score, 0.0, 1.0) * sentiment.confidence   # 0..1
slot_value = desk_capital / desk.params.max_positions
order_value = slot_value * (0.5 + 0.5 * conviction)     # 50%..100% of a slot
qty = int(order_value / ltp)
```

Floor at half a slot so a marginal signal takes a small position rather than
none; ceiling at one slot so conviction can never breach the allocation. The
risk manager's 10% per-position cap still sits underneath and can resize —
sizing is a desk *preference*, the cap is a *limit*.

### Exit — four triggers, first to fire wins

| # | Trigger | Condition |
|---|---|---|
| 1 | `sentiment_reversal` | score falls below `exit_sentiment` (day `0.0`, swing `-0.10`, long `-0.20`) |
| 2 | `blocked_event` | a `BLOCKED_EVENTS` headline appears for a held symbol |
| 3 | `stop_loss` / `target` | desk price params |
| 4 | `time_exit` | `square_off` (day) · `max_hold_days` (swing) · `rebalance` (long) |

Write the trigger name into the `ProposedOrder.reason` and the journal. The
distribution of exit reasons across a session is the most interesting artefact
this system produces — *"6 exits, 4 of them on sentiment reversal before the
stop was hit"* is a real result. Price-only exits are not.

Exit thresholds sit **below** entry thresholds deliberately (enter at +0.30,
exit at 0.0 for the day desk). Equal thresholds cause churn — the position
flip-flops on noise around a single number.

### Staleness: no new entries, but do not force-exit

If `now - sentiment.as_of` exceeds the desk's window, the desk proposes **no new
entries** and holds existing positions. Stale data is an absence of information,
not a sell signal — force-exiting on it would make a Wi-Fi outage into a
liquidation event. Journal an `alert` so the UI can show *"day desk idle —
sentiment stale by 9h."*

### Re-scoring cadence

| Desk | Re-pull sentiment | Why |
|---|---|---|
| day | every 15 min during market hours | intraday reversal must be catchable |
| swing | once pre-open, once at 14:00 | no need for tick-level news |
| long_term | daily pre-open | thesis-level changes only |

Poll `GET /api/sentiment/{symbol}` for held symbols on the desk's cadence. No
new contract is needed — `SymbolSentiment.drivers[].event_type` and `.as_of`
already carry everything the exit logic reads.

### Where this lives

`trading/sentiment_rules.py` — pure functions, no network, no LLM:

```python
def entry_allowed(cand: Candidate, desk: DeskConfig, now: datetime
                  ) -> tuple[bool, str | None]:      # (ok, reason_if_not)

def conviction_qty(cand: Candidate, desk: DeskConfig, ltp: float) -> int

def exit_trigger(pos: Position, sent: SymbolSentiment, desk: DeskConfig,
                 ltp: float, now: datetime) -> str | None
```

Three pure functions over plain data. Unit-testable in milliseconds against
Track 1's fixtures, which means you can build and prove this whole section
before their live API exists.

## 4. The risk manager — one CRO, below every desk

Port `trading_bot/risk/manager.py` wholesale, then add the intraday rules.
Limits are frozen at construction; **there is no method to relax them at
runtime**, and that is a feature you should say out loud in the pitch.

The gauntlet, in order:

| # | Rule | Action |
|---|---|---|
| 0 | Engine halted | veto |
| 1 | Day P&L ≤ −2% of capital | **halt** + veto (needs manual resume) |
| 2 | `orders_today ≥ 10` | veto — runaway backstop |
| 3 | Symbol not in `allowlist.txt` | veto |
| 4 | No valid quote | veto |
| 5 | Desk allocation exhausted | veto |
| 6 | SELL > held qty | resize to held (CNC — no shorting) |
| 7 | BUY beyond 10% per-position cap | resize |
| 8 | BUY beyond total capital cap | resize |
| **9** | **`desk == day` and now > square_off** | **veto — no new intraday entries** |
| **10** | **`desk == day` and product != MIS** | veto — config error |
| **11** | **`uses_leverage == False` and product == MIS** | veto — mandate says no leverage |

Rules 9–11 are your additions for the day desk. Every verdict is journaled with
`rule_fired`. The UI renders that string — a vetoed order that shows *why* is
worth more in a demo than ten successful fills.

## 5. Execution — paper now, Kite gated

```python
# trading/execution/broker.py
class Broker(Protocol):
    mode: str                                          # "paper" | "kite"
    def place(self, order: ProposedOrder, qty: int) -> Fill: ...
    def positions(self) -> dict[str, int]: ...
    def cash(self) -> float: ...
```

**`paper.py`** — fills at the last quote plus modelled slippage, charges the
full itemised Indian cost stack, appends a `fill` journal entry, replays the
book from the journal on restart. Paper P&L that ignores costs is a lie; the
reference repo measured 0.80pp CAGR of cost drag and you should be able to show
the same honesty.

**`costs.py`** — port from `backtester/engine/costs.py`. It already itemises
STT, exchange transaction charge, SEBI turnover fee, stamp duty, GST and
brokerage, with the delivery-vs-intraday split. Do not re-derive these rates
from memory; if you must confirm them, check Zerodha's published brokerage
calculator and note the date you checked.

**`kite.py`** — real `kiteconnect` adapter:
```
login_url() → user logs in → request_token → generate_session(api_secret)
→ access_token cached in kite_token.json (expires daily, ~08:00 IST)
```
Implement `quote()`, `positions()`, `margins()` and `place_order()`. Wire
`quote()` in for real prices even in paper mode — that's a genuine Kite
integration you can demo without risking a rupee. Free Kite Personal tier gives
EOD closes; live ticks need the paid data add-on. Say which tier you're on
rather than implying live ticks you don't have.

**`gate.py`** — the triple lock, all three required:
1. `TRADING_MODE=live` in env
2. a `live.lock` file present on disk
3. an interactive `LIVE-CONFIRM` typed at the prompt

Missing any one ⇒ paper broker returned. `GET /api/health` reports
`gate_armed: false` and the UI renders the `PAPER` badge from it. Write a test
asserting the gate returns paper when env says live but the lock file is absent.

## 6. Journal — append-only, single source of truth

One SQLite table, typed payloads:
```python
class JournalEntry(BaseModel):
    ts: datetime
    kind: Literal["proposal", "verdict", "fill", "alert", "auth", "note"]
    payload: dict
```
Never update, never delete. Portfolio state is *derived* by replaying the
journal, not stored separately — so the ledger can't disagree with the book.
`GET /api/journal` is Track 3's audit-trail screen.

## 7. Hour plan

| Hrs | Work |
|---|---|
| 0.0–0.5 | Read the reference repo. Scaffold `trading/`. |
| 0.5–1.0 | Wait on `core/contracts.py`; meanwhile port `models.py` + journal |
| 1.0–2.5 | `journal/store.py` + `risk/manager.py` (port + rules 9–11) |
| 2.5–3.5 | `costs.py` + `paper.py`, replay-from-journal working |
| 3.5–5.0 | **`sentiment_rules.py` (§3.5) + its tests** — the core of your track |
| 5.0–6.0 | `desks.yaml` + `desks.py` + `engine/core.py` — all three desks run on fixtures |
| 6.0–7.0 | **Checkpoint 6h:** fixture candidates → orders → verdicts → paper fills → journal |
| 7.0–8.5 | `kite.py` + `gate.py`, gate tests |
| 8.5–10.0 | `api/routes_trading.py` |
| 10.0–12.0 | Integration, seed a plausible journal for the demo, rehearse |

**Cut list if behind, in order:** Kite live order path → keep `quote()` only ·
day desk square-off scheduler → manual trigger button · long-term rebalance →
skip · re-scoring cadence → single manual "re-score" button.

**Not on the cut list:** the sentiment entry gate and the sentiment exit
trigger. Without those two you have a momentum bot with a news widget bolted on,
which is the thing every other team will have built.

## 8. Verification

```bash
pytest tests/test_sentiment_rules.py   # entry gate, conviction sizing, exits
pytest tests/test_risk.py              # every rule fires, none can be relaxed
pytest tests/test_gate.py              # locked gate returns paper under all env combos
pytest tests/test_isolation.py         # import-graph: trading/ never imports gemma/
python -m trading.engine.core --desk swing --simulate
curl localhost:8000/api/health         # gate_armed must be false
```

Cases `test_sentiment_rules.py` must cover — all runnable against Track 1's
fixtures, no backend needed:

- high `composite_score` + **negative** sentiment ⇒ no entry
- positive sentiment + `promoter_pledge` driver ⇒ no entry, reason `blocked_event`
- sentiment `+0.9` conf `1.0` ⇒ full slot; `+0.3` conf `0.5` ⇒ ~57% of a slot
- held position, sentiment falls `+0.4 → -0.15` ⇒ swing exit `sentiment_reversal`
- sentiment `as_of` 9h old on the day desk ⇒ no new entry, **position retained**
- stock already `+5%` today, day desk ⇒ skip, reason `sentiment_already_priced`

The isolation test is short and worth writing early — it's the thing that lets
you tell a judge "the model provably cannot place an order":

```python
def test_trading_never_imports_gemma():
    for path in Path("trading").rglob("*.py"):
        src = path.read_text()
        assert "gemma" not in src, f"{path} imports the LLM layer"
```

Then the demo checks: a day-desk order at 15:20 must be **vetoed** with
`rule_fired="day_square_off_window"`, and the P&L report must show itemised
costs, not just gross.
