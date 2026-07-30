# Track 1 — Sentiment & Stock Selection

**Owner:** 1 dev · **Budget:** 12 hours · **Language:** Python 3.13

You own the brain. News in, ranked candidates out. Tracks 2 and 3 are both
blocked on you for the first hour — read §0 first and ship it before anything
else.

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

> **Why SQLite, not Postgres, in a 12-hour build:** same SQLAlchemy models, one
> env var to switch. Nobody loses an hour to docker-compose at 3am.

### Repo layout

```
quantquasers/
├── core/contracts.py        ← Track 1 ships this in hour 1. Frozen after.
├── ingest/                  ← Track 1
├── gemma/                   ← Track 1
├── select/                  ← Track 1
├── trading/                 ← Track 2
├── api/                     ← routes_sentiment.py (T1) · routes_trading.py (T2)
├── fixtures/                ← Track 1 ships in hour 1. Tracks 2+3 build on it.
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

1. No buy/sell recommendations to a user, no target prices. Verdict vocabulary
   is `SUITABLE / STRETCH / OUTSIDE_MANDATE`.
2. `PAPER` badge visible on every screen that shows an order or a position.
3. Disclaimer footer everywhere: *"Educational analysis only. Not investment
   advice. Not issued by a SEBI-registered Research Analyst or Investment
   Adviser."*
4. The live gate ships **locked**. Nobody arms it during the hackathon.

---

## 1. What you own

```
core/contracts.py       every Pydantic model in the system
ingest/news.py          Google News RSS → Headline[]
ingest/prices.py        yfinance → OHLCV, cached to parquet
gemma/client.py         Ollama primary + AI Studio fallback, one interface
gemma/scorers.py        score_headline() · profile_user() · explain_candidate()
select/quant.py         OHLCV → QuantMetrics (pure pandas, NO LLM)
select/mandate.py       the refusal engine (pure rules, NO LLM)
select/ranker.py        composite score per horizon (deterministic)
api/routes_sentiment.py FastAPI routes
fixtures/               the thing that unblocks your teammates
data/universe.csv       ~40 NSE symbols, hand-curated
```

## 2. `core/contracts.py` — ship this in hour 1

Everything the other two tracks import. Once pushed, changes require telling
both other devs in person.

```python
from enum import Enum
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class Horizon(str, Enum):
    DAY = "day"; SWING = "swing"; LONG = "long_term"

CapBucket = Literal["large", "mid", "small", "micro"]

EventType = Literal[
    "earnings", "order_win", "regulatory", "promoter_pledge", "fundraise",
    "litigation", "management_change", "analyst_view", "macro", "other",
]

# ── sentiment ────────────────────────────────────────────────────────────
class HeadlineScore(BaseModel):
    id: str
    symbol: str
    title: str
    source: str
    url: str
    published_at: datetime
    sentiment: float = Field(ge=-1, le=1)
    label: Literal["positive", "neutral", "negative"]
    event_type: EventType
    materiality: int = Field(ge=1, le=5)
    rationale: str
    model: str                       # "gemma3:4b" | "gemma-3-27b-it" | "fallback"

class SymbolSentiment(BaseModel):
    symbol: str
    as_of: datetime
    score: float = Field(ge=-1, le=1)   # computed in Python, not by Gemma
    confidence: float = Field(ge=0, le=1)
    n_articles: int
    top_events: list[EventType]
    drivers: list[HeadlineScore]        # audit trail — every claim traceable

# ── user ─────────────────────────────────────────────────────────────────
class RiskProfile(BaseModel):
    capital: float
    horizons: list[Horizon]
    allowed_caps: list[CapBucket]
    max_drawdown_pct: float
    experience: Literal["new", "1-3y", "3y+"]
    day_trading: bool
    uses_leverage: bool
    trader_type: Horizon | None = None    # Gemma's read
    confidence: float = 0.0               # Gemma's confidence in that read

# ── quant (deterministic) ────────────────────────────────────────────────
class QuantMetrics(BaseModel):
    symbol: str
    name: str
    cap_bucket: CapBucket
    mcap_cr: float
    ltp: float
    annual_vol: float          # %
    beta: float                # vs ^NSEI
    max_drawdown_1y: float     # %, positive number
    adtv_cr: float             # 30d avg daily traded value, ₹ crore
    atr_pct: float
    rsi14: float
    sma20: float; sma50: float; sma200: float
    dist_52w_high_pct: float
    asm_gsm_flag: bool

# ── mandate ──────────────────────────────────────────────────────────────
class Reason(BaseModel):
    code: str                                  # "R2"
    severity: Literal["block", "warn"]
    text: str                                  # human sentence
    metric: str                                # "adtv_cr"
    value: float
    threshold: float

class MandateVerdict(BaseModel):
    level: Literal["SUITABLE", "STRETCH", "OUTSIDE_MANDATE"]
    reasons: list[Reason]

# ── output ───────────────────────────────────────────────────────────────
class Candidate(BaseModel):
    symbol: str
    horizon: Horizon
    composite_score: float = Field(ge=0, le=100)
    sentiment: SymbolSentiment
    quant: QuantMetrics
    verdict: MandateVerdict
    explanation: str                           # Gemma-written prose
```

Track 2's order/journal models live in `trading/models.py` and are theirs.

## 3. `fixtures/` — also hour 1, also blocking

Hand-write or generate five files. They must validate against the contracts
above. Track 3 builds every screen against these; Track 2 tests desks against
them.

```
fixtures/sentiment_feed.json      30 HeadlineScore
fixtures/candidates_day.json      8 Candidate, incl. 2 OUTSIDE_MANDATE
fixtures/candidates_swing.json    8 Candidate
fixtures/candidates_long.json     8 Candidate
fixtures/profile_conservative.json
fixtures/profile_aggressive.json
```

Include at least one micro-cap with `day_trading=true` producing
`OUTSIDE_MANDATE` with two blocking reasons — that's the demo's money shot and
Track 3 needs to design the card for it.

## 4. `gemma/client.py` — one interface, two backends

Ollama's Python client takes a JSON Schema in `format=`, which constrains
decoding. This is the single most important reliability decision in the track —
a 4B model free-forming JSON will fail during your demo.

```python
import ollama
from pydantic import BaseModel

_client = ollama.Client()

def generate(prompt: str, schema: type[BaseModel] | None = None,
             system: str = "") -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    resp = _client.chat(
        model="gemma3:4b",
        messages=msgs,
        format=schema.model_json_schema() if schema else None,
        options={"temperature": 0, "num_predict": 300},
        keep_alive="30m",              # keep the model warm between calls
    )
    return resp.message.content
```

Rules:
- **One headline per call.** A 4B model degrades sharply on batched JSON. Four
  output fields per call is where it's reliable.
- `temperature=0` always. Reproducible demos.
- Wrap every call in try/except returning a `neutral` fallback with
  `model="fallback"`. One bad generation must never take the app down.
- `AI_STUDIO_KEY` env var present → route to `gemma-3-27b-it` instead. Same
  function signature, so nothing downstream changes.
- Pre-warm on FastAPI startup with a one-token call. First cold call is ~10s.

## 5. `gemma/scorers.py`

**`score_headline(title, company) -> HeadlineScore`**
Schema-constrained to `{sentiment, label, event_type, materiality, rationale}`.
System prompt: *"You are a financial news classifier for Indian equities. Judge
only the headline given. Do not speculate about price."*

**`profile_user(answers) -> (Horizon, confidence)`**
A hand-written rubric computes a risk score from the structured answers first.
Gemma reads answers + rubric score and returns `{trader_type, confidence}`.
If Gemma disagrees sharply with the rubric, keep the rubric and set confidence
low. The rubric is the authority; Gemma is a second opinion.

**`explain_candidate(quant, sentiment, verdict) -> str`**
Numbers are injected into the prompt **pre-formatted as strings** so the model
copies rather than computes. Explicit instruction: no price targets, no
buy/sell language, 3 sentences max.

**Aggregation is Python, not Gemma:**
```python
weight = materiality * exp(-age_days / 3)     # 3-day recency half-life-ish
score  = sum(w * s) / sum(w)
confidence = min(1.0, n_articles / 8) * (1 - stdev(scores) / 2)
```
Disagreement across headlines lowers confidence. That's the honest behaviour.

## 6. `select/quant.py` — pure pandas, no LLM

`fetch(symbol) -> QuantMetrics` from 1y daily yfinance data:

- `annual_vol` = `returns.std() * sqrt(252) * 100`
- `beta` vs `^NSEI` = `cov(r, m) / var(m)`
- `max_drawdown_1y` from the cumulative-max series
- `adtv_cr` = `mean(Close * Volume)` over 30d ÷ 1e7 — **this drives the
  liquidity refusal, get it right**
- `atr_pct`, `rsi14`, `sma20/50/200`, `dist_52w_high_pct`
- `cap_bucket` and `asm_gsm_flag` from `data/universe.csv`

Cap buckets follow SEBI convention: rank 1–100 `large`, 101–250 `mid`, 251+
`small`. `micro` is our own extension for mcap < ₹500 Cr — say so in the README
rather than implying it's official.

Every call try/except with a parquet cache fallback. yfinance rate-limits.

## 7. `select/mandate.py` — the refusal engine

Pure functions over plain data. No network, no LLM, unit-testable in
milliseconds. This is what a markets-literate judge will poke at.

| Code | Condition | Result |
|---|---|---|
| R1 | `cap_bucket not in profile.allowed_caps` | block |
| R2 | `day_trading and adtv_cr < 5` | block — impact cost |
| R3 | `day_trading and cap_bucket in {small, micro}` | block |
| R4 | `asm_gsm_flag` | block — under surveillance |
| R5 | `max_drawdown_1y > profile.max_drawdown_pct` | warn |
| R6 | `annual_vol > 45 and experience == "new"` | warn |
| R7 | `horizon == DAY and atr_pct < 1.0` | warn — too little range to day-trade |

Any block ⇒ `OUTSIDE_MANDATE`. Else any warn ⇒ `STRETCH`. Else `SUITABLE`.
Every `Reason` carries the metric name, the actual value, and the threshold it
crossed — the UI renders these as numbers, which is what makes the refusal
credible rather than decorative.

## 8. `select/ranker.py` — composite score per horizon

Deterministic weights, different per horizon. Tune the numbers, keep the shape:

| Component | Day | Swing | Long |
|---|---|---|---|
| Sentiment score | 0.40 | 0.35 | 0.20 |
| Momentum (RSI, SMA state) | 0.20 | 0.35 | 0.15 |
| Liquidity (ADTV) | 0.30 | 0.10 | 0.05 |
| Volatility (higher better) | 0.10 | 0.10 | — |
| Trend (SMA200) | — | 0.10 | 0.35 |
| Drawdown (lower better) | — | — | 0.25 |

Normalise each to 0–100, weight, sum. Multiply by `sentiment.confidence` so
thin news coverage can't produce a top-ranked pick. `OUTSIDE_MANDATE` candidates
are still returned — the UI shows them struck through with the reason. **Never
silently filter; showing the refusal is the point.**

## 9. Hour plan

| Hrs | Work |
|---|---|
| 0.0–1.0 | **`contracts.py` + `fixtures/` pushed.** Nothing else matters until this lands. |
| 1.0–2.0 | Ollama install, `ollama pull gemma3:4b`, verify schema-constrained call returns valid JSON |
| 2.0–3.0 | `ingest/news.py` + disk cache |
| 3.0–4.5 | `gemma/scorers.py`, sanity-check on ~20 real headlines |
| 4.5–6.0 | `select/quant.py` + `data/universe.csv` (~40 symbols, all 4 buckets, 3 ASM-flagged) |
| 6.0–7.5 | `select/mandate.py` + tests for all 7 rules |
| 7.5–8.5 | `select/ranker.py` |
| 8.5–10.0 | `api/routes_sentiment.py` |
| 10.0–12.0 | Integration with Tracks 2 & 3, pre-cache demo symbols, tune weights |

**Cut list if behind, in order:** `explain_candidate` prose → templated string ·
RSI/ATR → keep vol and ADTV only · live news → committed fixtures.

## 10. News source

Google News RSS. No API key, no rate limit, returns Indian outlets:

```
https://news.google.com/rss/search?q={company}+stock+NSE&hl=en-IN&gl=IN&ceid=IN:en
```

`feedparser`, 10 most recent, keep `title / source / published / link`. Cache to
`data/cache/{symbol}_news.json` and serve the cache on any network failure —
venue Wi-Fi is not to be trusted.

## 11. Verification

```bash
ollama run gemma3:4b "reply OK"                     # model alive
pytest tests/test_mandate.py                        # all 7 rules fire
python -c "from select.quant import fetch; print(fetch('RELIANCE.NS'))"
python -c "from gemma.scorers import score_headline; \
  print(score_headline('Company X hit with SEBI penalty', 'X'))"   # → negative
```

Then the one that matters: a micro-cap symbol with `day_trading=True` must
return `OUTSIDE_MANDATE` with **≥2 reasons, each carrying its number.**
Finally, disconnect from the network and confirm every demo symbol still
resolves from cache.
