# QuantQuasers

Reads the Indian market's news flow with **Gemma**, ranks stocks against a
user's declared trading mandate, and routes the survivors to three automated
desks — **day**, **swing**, **long-term** — trading on paper behind a live gate
that is never armed.

> **STATUS: PAPER.** No real orders. Educational analysis only. Not investment
> advice. Not issued by a SEBI-registered Research Analyst or Investment Adviser.

## The design principle

> **Gemma classifies and explains. It never decides and never counts.**

Sentiment, event tags and written explanations come from the model. Every number
that reaches a screen or an order — volatility, drawdown, position size, P&L —
comes from deterministic Python. `trading/` provably never imports `gemma/`.

## Three tracks, one dev each

| Track | Doc | Owns | Status |
|---|---|---|---|
| 1 · Sentiment & Selection | [TRACK-1-SENTIMENT.md](TRACK-1-SENTIMENT.md) | Gemma scoring, quant metrics, mandate guard, ranker | spec |
| 2 · Trade Automation | [TRACK-2-TRADING.md](TRACK-2-TRADING.md) | Desks, risk manager, capital allocation, paper + Kite execution, journal | **built · 151 tests** |
| 3 · Frontend & UX | [TRACK-3-FRONTEND.md](TRACK-3-FRONTEND.md) | Next.js app, onboarding, dashboard, audit trail | spec |

Each doc repeats the shared contract in §0 so any dev can work standalone.

## Running what exists

```bash
pip install -r requirements.txt
pytest -q                                              # 151 passed
python -m trading.engine.core --all --at 10:30         # all three desks trade
python -m trading.engine.core --desk day  --at 15:20   # intraday square-off
uvicorn api.main:app --reload                          # API + /docs on :8000
```

`core/contracts.py` and `fixtures/` are in place, so **Tracks 1 and 3 are
unblocked now.** Track 3 can build every screen against
`POST /api/orders/execute` today — it returns real fills, real vetoes, and the
sentiment refusals with their triggering numbers.

### Onboarding: capital in, desk split out

Desk allocations are **not** static config. The user declares their capital and
their appetite; a hand-written rubric in `trading/allocation.py` derives the
risk band, and the day / swing / long-term split follows from it. Gemma's read
of the survey free text may move the band **one notch at most**, and only above
a 0.70 confidence floor — a model never sets an equity allocation.

```bash
POST /api/account          # create: capital + horizons + appetite → split, engine rebuilt
POST /api/account/preview  # same maths, changes nothing — for the onboarding slider
GET  /api/account          # current profile + allocation, or defaults if unset
```

Opting out of intraday removes the day desk and the rest renormalise to absorb
its share — the desk stays visible at 0% and `enabled: false` so the UI can say
*"day desk — off, you opted out"* instead of silently dropping it. A SIP
(`sip_amount` + `sip_frequency`) deploys on schedule regardless of sentiment:
sentiment picks *which* stocks, never *whether* to invest.

Track 1: `QuantMetrics.move_1d_pct` / `move_5d_pct` / `move_20d_pct` are
optional fields the lag guard reads. Populate them when convenient; the guard
is a no-op until you do.

## Critical path

**Track 1 must push `core/contracts.py` and `fixtures/*.json` within the first
hour.** Both other tracks are blocked until it lands, and unblocked completely
once it does — Track 2 tests desks against the fixtures, Track 3 builds every
screen against them and swaps to the live API at hour 10.

| Hour | Gate |
|---|---|
| 1 | Contracts + fixtures pushed |
| 6 | End-to-end on fixtures: survey → candidates → paper fill → journal → UI |
| 10 | Live API swapped in |
| 11 | Full demo rehearsal, offline |

## Stack

FastAPI · SQLAlchemy (SQLite dev, Postgres-swappable) · Ollama `gemma3:4b` with
Google AI Studio fallback · yfinance · Kite Connect · Next.js + TypeScript +
Tailwind + shadcn/ui
