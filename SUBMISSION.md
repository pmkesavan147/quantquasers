# QuantQuasers

**Track:** Gemma
**Team:** QuantQuasers

---

## Problem

Retail investors in India get sentiment as a vibe — a red or green arrow, a
headline, a Telegram tip — with no way to see whether the news is material, or
whether the stock is even suitable for them. The tools that do screen stocks
never say *no*: they surface picks, not refusals, so a first-year trader with
₹50,000 gets shown the same illiquid micro-cap as a professional. Meanwhile
every "AI trading" product asks a language model to output a position size,
which is precisely the thing language models should not be doing.

---

## Solution

QuantQuasers reads the Indian market's news flow with Gemma, ranks stocks
against the user's own declared mandate, and routes the survivors to three
automated paper-trading desks — intraday, swing, and long-term. A user answers
an 11-question survey; a hand-written rubric scores it 0–11 and derives their
risk band, and the split of their capital across the three desks follows from
that band. Gemma reads their free-text answers as a *second opinion* and may
shift the band by one notch, never further. Then, per desk: real headlines are
fetched per symbol, Gemma classifies each one in isolation (sentiment, event
type, materiality), Python aggregates those into a symbol score weighted by
materiality and recency, quant metrics come from a year of price data, and a
seven-rule mandate engine issues a verdict. Refused stocks are **returned, not
hidden** — struck through with the metric, the value, and the threshold each one
crossed. Surviving candidates become orders, sized by a risk manager, filled on
paper with a full Indian cost stack, and written to an append-only journal that
the portfolio is *derived* from by replay. The live-trading gate needs three
independent locks and is never armed.

---

## How Gemma Is Used

- **Model variant:** `gemma-4-31b-it` (Gemma 4, dense 31B) via Google AI Studio,
  with the committed headline cache built on `gemma-4-26b-a4b-it` (26B MoE) —
  cache keys are the prompt, not the model, so both replay together. Local
  fallbacks wired: `google/gemma-4-E4B-it` on a GPU box, `gemma3:4b` on Ollama.
- **How it's used:** Base model, zero-shot, three jobs — (1) per-headline
  classification into a strict JSON contract, one headline per call; (2) reading
  the user's free-text survey answers to name a trading horizon with a
  confidence; (3) writing plain-English explanations of a screening result.
  Deterministic keyword fallback behind all three, so the system degrades
  instead of failing.
- **Why this Gemma variant:** it is free on AI Studio's tier (a hackathon demo
  cannot be metered), and the open weights mean the exact same prompts run on a
  laptop GPU or on Ollama with no code change — which is what our offline
  fallback depends on. We started on the 26b MoE for its 4B-class latency and
  moved to the dense 31b when we measured what its thinking tokens do to a long
  prompt: they are drawn from `max_output_tokens`, so the profiling prompt came
  back empty at 1600, 2500 and 3000 tokens and only answered at 6000 (86 s). The
  31b answers it in 739 thinking tokens and 23 s.
- **Customization:** No fine-tuning. The engineering went into the *contract*:
  system prompts that forbid price speculation and advice; a JSON schema
  appended to every structured call plus a brace-matching parser that survives
  markdown fences and prose; clamping and enum-normalisation of model output
  (the live model returns `materiality: 6` on a 1–5 scale and capitalises
  `event_type` — we clamp rather than discard); and a token budget of 1600
  because Gemma 4's thinking tokens are drawn from `max_output_tokens` and a
  smaller budget returns an empty string. Every response is cached by prompt
  hash, so a demo replays identically and offline.

**The design principle everything hangs off:**

> **Gemma classifies and explains. It never decides and never counts.**

Every number that reaches a screen or an order — volatility, drawdown, position
size, the desk split, P&L — is deterministic Python. A test in CI fails the
build if the trading layer so much as imports the model layer.

---

## Architecture

```
 Browser (React + Vite, Vercel)
        │  typed API client — computes nothing
        ▼
 FastAPI  (single Vercel Python function)
        ├── gemma/      → Gemma 4 on AI Studio   [classify · read · explain]
        │                 ↳ GPU / Ollama / deterministic stub fallbacks
        │                 ↳ disk cache keyed by prompt
        ├── ingest/     → Google News RSS · yfinance (1y OHLCV)
        ├── selection/  → quant metrics · 7-rule refusal engine · ranker
        │                 (pure Python, provably model-free)
        ├── trading/    → 3 desks · risk manager · paper broker · cost model
        └── journal     → Supabase Postgres, append-only
                          (RLS deny-by-default; UPDATE/DELETE blocked by trigger)
                          portfolio is DERIVED by replaying this ledger
```

**Tech stack:** Python 3.13 · FastAPI · Pydantic · pandas · Supabase Postgres ·
Google AI Studio (Gemma 4) · Transformers/Unsloth + Ollama for local inference ·
yfinance · Google News RSS · React 18 + TypeScript + Vite + Tailwind + Recharts ·
deployed on Vercel (two projects from one repo).

---

## Results / Demo

- **The refusal engine is the result.** Ask for a micro-cap intraday and you get
  `OUTSIDE_MANDATE` with four blocking reasons, each carrying its number —
  "ADTV ₹1.8 crore is below the ₹5 crore intraday floor", "under NSE
  surveillance", and so on. Nothing is silently filtered.
- **Live Gemma output, verified:** *"Sun Pharma receives USFDA observations for
  its Halol facility"* → sentiment **−0.70**, event `regulatory`, materiality
  **4/5**. Survey read: `long_term` at **0.90** confidence, quoting the user's
  own words back at them.
- **Honest confidence.** Sentiment confidence falls with thin coverage, with
  disagreement between headlines, and by half when no model was reachable —
  every row is labelled with the model that scored it.
- **276 tests**, all passing offline with no model and no network.
- **Real data:** 39 NSE symbols with a year of live price history, 312 real
  headlines, 302 of them scored by Gemma 4.
- **Latency:** a full news scan → ranked candidates in **~140 ms** on the
  deployed instance (snapshot replay), vs minutes if fetched live.
- **Demo video:** [link]
- **Live demo:** https://sentiment-portfolio.vercel.app
- **Screenshots:** onboarding → persona → trading floor → sentiment → audit trail

---

## Links

- **GitHub repo:** https://github.com/pmkesavan147/quantquasers
- **Live demo (UI):** https://sentiment-portfolio.vercel.app
- **API + interactive docs:** https://quantquasers-api.vercel.app/docs
- **Dataset(s) used:** No training dataset — the system reads live public data:
  Google News RSS (headlines) and Yahoo Finance via `yfinance` (OHLCV). The
  traded universe (`data/universe.csv`, 40 NSE symbols) is hand-curated by us.
- **License for this project:** Apache 2.0

> **Status: paper trading.** No real orders are placed. Educational analysis
> only — not investment advice, and not issued by a SEBI-registered Research
> Analyst or Investment Adviser.

---

## Acknowledgments

- **Google DeepMind** for Gemma 4, and Google AI Studio for free-tier access
  that made a live demo possible without a GPU.
- **Yahoo Finance** via the `yfinance` library, and **Google News RSS**, for
  market data and headlines.
- **Supabase** for the Postgres instance holding the append-only journal, and
  **Vercel** for hosting both the API and the UI.
- **FastAPI**, **Pydantic**, **pandas**, **React**, **Vite**, **Tailwind CSS**,
  **Recharts**, and **Ollama** — the open-source projects this is built on.
- The **GDG hackathon organisers and mentors** for the problem framing and the
  room to build.
- Team QuantQuasers: [names] — Track 1 sentiment & selection, Track 2 trade
  automation, Track 3 frontend & UX.
