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

| Track | Doc | Owns |
|---|---|---|
| 1 · Sentiment & Selection | [TRACK-1-SENTIMENT.md](TRACK-1-SENTIMENT.md) | Gemma scoring, quant metrics, mandate guard, ranker |
| 2 · Trade Automation | [TRACK-2-TRADING.md](TRACK-2-TRADING.md) | Desks, risk manager, paper + Kite execution, journal |
| 3 · Frontend & UX | [TRACK-3-FRONTEND.md](TRACK-3-FRONTEND.md) | Next.js app, onboarding, dashboard, audit trail |

Each doc repeats the shared contract in §0 so any dev can work standalone.

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
