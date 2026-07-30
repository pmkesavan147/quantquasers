# QuantQuasers

Reads the Indian market's news flow with **Gemma 4**, ranks stocks against a
user's declared trading mandate, and routes the survivors to three automated
desks — **day**, **swing**, **long-term** — trading on paper behind a live gate
that is never armed.

> **STATUS: PAPER.** No real orders. Educational analysis only. Not investment
> advice. Not issued by a SEBI-registered Research Analyst or Investment Adviser.

## The design principle

> **Gemma classifies and explains. It never decides and never counts.**

Sentiment labels, event tags and written explanations come from the model. Every
number that reaches a screen or an order — volatility, drawdown, position size,
the desk split, P&L — comes from deterministic Python. `trading/` provably never
imports `gemma/`, and the browser computes nothing.

## What runs end to end

```
survey ─▶ rubric (0–11) ─▶ risk band ─▶ desk split ─▶ capital per desk
                  ▲
          Gemma reads the free text: ±1 notch, above 0.70 confidence only

news ─▶ Gemma scores each headline ─▶ Python weights them (materiality × recency)
     ─▶ quant metrics from yfinance ─▶ mandate refusal engine (7 rules)
     ─▶ composite score per horizon ─▶ desk ─▶ risk manager ─▶ paper fill
     ─▶ append-only journal ─▶ UI
```

| Piece | Lives in | Notes |
|---|---|---|
| Contracts | `core/contracts.py` | one vocabulary for all three tracks |
| Model layer | `gemma/` | AI Studio · LAN GPU · Ollama · deterministic stub |
| Ingest | `ingest/` | Google News RSS, yfinance; cache-then-fixture |
| Selection | `selection/` | quant, refusal engine, ranker, pipeline |
| Trading | `trading/` | desks, risk manager, paper broker, journal |
| API | `api/` | `routes_sentiment.py` + `routes_trading.py` |
| UI | `sentiment-portfolio/` | Vite + React + Tailwind, no mock data |

## Quickstart

```bash
pip install -r requirements-dev.txt   # requirements.txt is the lean runtime set
cp .env.example .env                 # then paste GOOGLE_API_KEY (free tier)

pytest -q                            # 266 passed, offline, no model needed
python -m scripts.check_gemma        # proves a model answers before you demo
python -m scripts.build_universe     # refresh data/universe.csv market caps
python -m scripts.warm_cache         # pre-fetch prices + headlines
uvicorn api.main:app --reload        # API + /docs on :8000
```

```bash
cd sentiment-portfolio
npm install
cp .env.example .env                 # VITE_API_BASE=http://127.0.0.1:8000
npm run dev                          # UI on :5173
```

CLI, no browser needed:

```bash
python -m trading.engine.core --all --at 10:30        # all three desks trade
python -m trading.engine.core --desk day --at 15:20   # intraday square-off
```

## Gemma: four backends, one call signature

`gemma/client.py` resolves in this order and never raises — it downgrades.

| Backend | When | Notes |
|---|---|---|
| **AI Studio** | `GOOGLE_API_KEY` set | `gemma-4-26b-a4b-it`, free tier. The default. |
| **Remote GPU** | `GEMMA_REMOTE_URL` set | a second laptop running `scripts/gemma_gpu_local.py --serve` |
| **Ollama** | daemon answers | `ollama pull gemma3:4b` |
| **Stub** | nothing else | deterministic keyword classifier; rows are labelled `model="fallback"` and confidence is halved |

Responses are cached to `data/cache/gemma/` keyed by **prompt**, not by model, so
a cache built on a GPU machine replays byte-for-byte on the demo laptop. Rehearse
once, then run the whole demo with `OFFLINE=1` and no network at all.

### Running the model on a GPU box

```bash
# on the GPU laptop
pip install "torch>=2.4" --index-url https://download.pytorch.org/whl/cu124
pip install transformers accelerate bitsandbytes

python -m scripts.gemma_gpu_local --ask "reply OK"          # smoke test
python -m scripts.gemma_gpu_local --warm                    # fill the shared cache
python -m scripts.gemma_gpu_local --serve --port 8077       # or serve on the LAN
```

Then either copy `data/cache/gemma/` to the demo machine, or set
`GEMMA_REMOTE_URL=http://<gpu-laptop-ip>:8077` there. Model IDs, VRAM notes and
the 4-bit path are documented at the top of that script.

## Onboarding: capital in, desk split out

Desk allocations are **not** static config. The user declares capital and
appetite; the rubric in `trading/allocation.py` derives the band, and the day /
swing / long-term split follows from it.

```
GET  /api/quiz             the questions, with backend enum values
POST /api/quiz/submit      answers → profile, band, split, Gemma's read, account
POST /api/persona/report   the prose read (slowest call, so it is separate)
POST /api/account          same thing without the survey
GET  /api/account          current profile and allocation
```

Opting out of intraday removes the day desk and the rest renormalise to absorb
its share — the desk stays visible at 0% with `enabled: false`, so the UI says
*"day desk — off, you opted out"* rather than silently dropping it. A SIP
(`sip_amount` + `sip_frequency`) deploys on schedule regardless of sentiment:
sentiment picks *which* stocks, never *whether* to invest.

## Selection: the refusal engine is the point

```
POST /api/candidates          ranked candidates for one desk, refusals included
POST /api/candidates/to-desk  same, plus the orders the desk would place
GET  /api/sentiment/market    per-symbol scores and one market-mood number
GET  /api/sentiment/{symbol}  the headlines behind a score, with who scored them
GET  /api/universe           the traded universe and its caveats
```

Seven rules, in `selection/mandate.py`. Any block ⇒ `OUTSIDE_MANDATE`, any warn
⇒ `STRETCH`, else `SUITABLE`. Every reason carries the metric, the value and the
threshold it crossed, and refused candidates are **returned, never filtered** —
the UI strikes them through and shows the numbers.

| Code | Condition | Result |
|---|---|---|
| R1 | cap bucket outside the mandate | block |
| R2 | intraday and ADTV < ₹5 crore | block |
| R3 | intraday and small/micro-cap | block |
| R4 | under NSE ASM/GSM surveillance | block |
| R5 | 1-year drawdown worse than the user's limit | warn |
| R6 | volatility > 45% and the user is new | warn |
| R7 | day horizon and ATR < 1% | warn |

Cap buckets approximate SEBI's rank-based classification using absolute market
cap; `micro` (< ₹500 crore) is our own extension, not an official SEBI bucket.
ASM/GSM flags in `data/universe.csv` are a hand-maintained snapshot, not a live
feed. `SOMEMICRO` is synthetic on purpose — the micro-cap refusal demo should not
libel a real company.

## Honesty features

Every payload says where its numbers came from, because demoing fixture data as
live is the one dishonesty this project cannot afford.

* `report.quant_source` — how many symbols were priced live vs from fixtures
* `report.headline_source` — `rss` / `cache` / `fixture` counts
* `report.headline_models` — which model scored the news, `fallback` included
* `GET /api/gemma/status` — backend, model, cached response count
* `GET /api/health` — mode, gate state (and why it is shut), quote source

## Deployed

| | URL |
|---|---|
| UI | https://sentiment-portfolio.vercel.app |
| API | https://quantquasers-api.vercel.app · [`/docs`](https://quantquasers-api.vercel.app/docs) |

Two Vercel projects from this one repo: the UI is rooted at
`sentiment-portfolio/`, the API is the whole Python app behind a single function
(`api/index.py`, wired in `vercel.json`).

Serverless changes two things, both by environment rather than by code:

* **Data.** `SNAPSHOT=1` — a request cannot wait on yfinance for 40 symbols, so
  the deployed build serves `data/snapshot/` and reports `quant_source:
  snapshot` instead of `live`. Refresh it with
  `python -m scripts.build_snapshot`.
* **The journal.** The filesystem is wiped between invocations, and the
  portfolio is *derived* by replaying the journal — so a deployed instance keeps
  it in Supabase Postgres. RLS is on with no policies (only the service role key
  reaches the table) and an UPDATE/DELETE trigger makes append-only something
  the database enforces.

Environment variables on the API project:

| Variable | Purpose | Without it |
|---|---|---|
| `SUPABASE_URL` | the ledger's home | falls back to `/tmp` SQLite, wiped between requests |
| `SUPABASE_SERVICE_ROLE_KEY` | the only key that can read or write the ledger | as above |
| `GOOGLE_API_KEY` | Gemma 4 on AI Studio | keyword fallback, every row labelled `model="fallback"` |
| `SNAPSHOT` | force snapshot mode | on automatically when `VERCEL` is set |
| `CORS_ORIGINS` | extra origins, comma-separated | `*.vercel.app` and localhost are already allowed |

`GET /api/health` reports which journal backend and which data source the
running instance actually has, so none of the above is ever a guess.

## Three tracks

| Track | Doc | Owns | Status |
|---|---|---|---|
| 1 · Sentiment & Selection | [TRACK-1-SENTIMENT.md](TRACK-1-SENTIMENT.md) | Gemma scoring, quant metrics, mandate guard, ranker | **built** |
| 2 · Trade Automation | [TRACK-2-TRADING.md](TRACK-2-TRADING.md) | Desks, risk manager, capital allocation, paper + Kite execution, journal | **built** |
| 3 · Frontend & UX | [TRACK-3-FRONTEND.md](TRACK-3-FRONTEND.md) | Onboarding, floor, sentiment, audit trail | **built** |

[REVIEW.md](REVIEW.md) records what the three tracks disagreed about at merge
time and how it was resolved. [RUNBOOK.md](RUNBOOK.md) is the demo script.

## Stack

FastAPI · SQLite (append-only journal) · Gemma 4 via Google AI Studio, with a
GPU/Ollama/offline fallback · yfinance · Google News RSS · Kite Connect (quotes
only, gate shut) · Vite + React + TypeScript + Tailwind + Recharts
