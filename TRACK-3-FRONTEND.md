# Track 3 — Frontend & UX

**Owner:** 1 dev · **Budget:** 12 hours · **Stack:** Next.js + TypeScript

You own everything the judges actually see. The other two tracks can be perfect
and still lose if this screen doesn't land in the first ten seconds.

You are **not blocked** on the backend after hour 1 — Track 1 ships fixtures,
you build against those, and swap to the live API at hour 10.

---

## 0. Shared contract (identical in all three track docs)

### Product

**QuantQuasers** reads the Indian market's news flow with Gemma, ranks stocks
against a user's declared trading mandate, and routes the survivors to three
automated desks — **day**, **swing**, **long-term** — that trade on paper
behind a live gate that is never armed.

### The one design principle everything hangs off

> **Gemma classifies and explains. It never decides and never counts.**

For your track this has a direct UI consequence: every number on screen is
traceable to a source, and every Gemma-written sentence is visibly labelled as
model output. Build that distinction into the visual language.

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
| LLM | Gemma via Ollama (`gemma3:4b`) primary, Google AI Studio fallback |
| Market data | yfinance (`.NS` suffix), Kite Connect for quotes |
| Frontend | Next.js App Router + TypeScript + Tailwind + shadcn/ui |
| Broker | Kite Connect (`kiteconnect`), paper-first |

### Repo layout

```
quantquasers/
├── core/contracts.py        ← Track 1, hour 1. Your TS types mirror this.
├── ingest/ gemma/ select/   ← Track 1
├── trading/                 ← Track 2
├── api/                     ← FastAPI
├── fixtures/                ← Track 1, hour 1. You build against these.
├── web/                     ← YOU
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
| **1** | `core/contracts.py` + `fixtures/*.json` pushed. You unblock. |
| **6** | End-to-end on fixtures: survey → candidates → paper fill → journal → UI |
| **10** | Fixtures swapped for live API on all screens |
| **11** | Full demo rehearsal, offline |

### Non-negotiables

1. No buy/sell recommendations, no target prices. Verdict vocabulary is
   `SUITABLE / STRETCH / OUTSIDE_MANDATE`.
2. `PAPER` badge visible on every screen showing an order or position, driven
   by `health.gate_armed`.
3. Disclaimer footer everywhere: *"Educational analysis only. Not investment
   advice. Not issued by a SEBI-registered Research Analyst or Investment
   Adviser."*
4. The live gate ships locked.

---

## 1. Setup

```bash
npx create-next-app@latest web --typescript --tailwind --app --eslint
cd web && npx shadcn@latest init
npm i @tanstack/react-query recharts zod lucide-react
```

`web/lib/types.ts` mirrors `core/contracts.py` by hand — it's ~80 lines and
faster than wiring a codegen step in a 12-hour build.

`web/lib/api.ts` reads `NEXT_PUBLIC_API_MODE`:
- `fixtures` → import from `fixtures/*.json`
- `live` → fetch `http://localhost:8000`

One env var flips the whole app. This is what makes hour 10 a five-minute
change instead of a rewrite.

## 2. Screens

### A. Mandate setup — the onboarding wizard
4 steps, one question per screen, progress bar.
1. Capital + experience
2. Horizons (multi-select: day / swing / long-term) — day-trading toggle here
3. Market caps allowed (large / mid / small / micro) as four cards with plain
   descriptions of what each means
4. Max drawdown tolerance — a slider, live-previewing "on ₹5,00,000 that's
   ₹1,00,000 down"

That preview is the highest-value 20 minutes of UX in the build: it makes an
abstract percentage concrete, which is the whole point of a mandate.

Post to `/api/profile`, store in localStorage.

### B. Dashboard — the main screen
- Three horizon tabs: **Day · Swing · Long-term**
- Ranked candidate cards for the active horizon
- Sentiment feed rail on the right — live headlines with their Gemma label
- Header: portfolio value, day P&L, `PAPER` badge, pause/resume control

**The candidate card** is your most-used component:
```
┌────────────────────────────────────────────────┐
│ TATAMOTORS              Auto · Large      ● 78 │
│ ₹1,042.30    +1.4%                             │
│ ────────────────────────────────────────────── │
│ Sentiment  ▓▓▓▓▓▓▓░░░  +0.62   12 articles     │
│ Vol 28.4%   ADTV ₹412cr   DD -18.2%            │
│ ────────────────────────────────────────────── │
│ ✓ SUITABLE                                     │
└────────────────────────────────────────────────┘
```
And the refusal variant — **design this one first, it's the demo's hero**:
```
┌────────────────────────────────────────────────┐
│ SOMEMICRO               Micro cap         ─ ─  │
│ ────────────────────────────────────────────── │
│ ⛔ OUTSIDE YOUR MANDATE                        │
│                                                │
│ R2  Liquidity too thin for intraday            │
│     ADTV ₹1.8cr  ·  minimum ₹5cr               │
│ R3  Day trading blocked on micro caps          │
│     you enabled day trading in your mandate    │
└────────────────────────────────────────────────┘
```
Show the numbers. A refusal without its triggering value reads as arbitrary;
with the value it reads as a system that actually measured something.

### C. Symbol detail
Price chart with SMA overlays · quant metrics grid · sentiment timeline
(scatter of headline scores over time) · the headline table with source links,
event-type chips and materiality · Gemma's written explanation in a visibly
distinct block (subtle border + "Generated by Gemma 3" label).

**Every headline links to its source.** That's the anti-hallucination story
made visible, and it costs you one `<a>` tag.

### D. Desks & portfolio
Three desk cards: allocation, deployed, open positions, P&L, enabled toggle.
Positions table with entry, LTP, unrealised P&L, and which desk owns it.
Costs shown itemised, not netted away.

### E. Journal — the audit trail
Reverse-chronological feed of `JournalEntry`, filterable by kind. Verdicts
render the `rule_fired` string prominently. A vetoed order is more interesting
than a filled one — style it so.

## 3. Design direction

Avoid the default AI-dashboard look: no purple gradient hero, no glassmorphism,
no three-column card grid of rounded boxes with emoji icons. This is a trading
terminal — the reference points are Bloomberg, a Kite order window, a
well-typeset financial report.

- **Dark, dense, high-contrast.** Near-black background, one accent, semantic
  colour used *only* for meaning.
- **Semantic colour discipline:** green = positive/suitable, amber = stretch,
  red = blocked/loss. Never decorative. If green appears on something that
  isn't good, you've broken the language.
- **Tabular numerals** everywhere numbers appear in a column
  (`font-variant-numeric: tabular-nums`). Misaligned digits in a finance UI
  read as amateur instantly.
- **Indian number formatting:** `₹4,12,300` (lakh/crore grouping), not
  `₹412,300`. Use `Intl.NumberFormat('en-IN')`. Judges are Indian; this is a
  five-line detail that signals you know your market.
- **Typography:** one geometric sans for UI, one mono for numbers. Inter +
  JetBrains Mono is fine and free.
- **Density over whitespace.** A trader's screen should feel information-rich.
  Resist the urge to make it airy.

## 4. Hour plan

| Hrs | Work |
|---|---|
| 0.0–1.0 | Scaffold, Tailwind, shadcn, layout shell, dark theme tokens |
| 1.0–2.0 | `types.ts` + `api.ts` fixture layer (needs Track 1's hour-1 push) |
| 2.0–3.5 | Onboarding wizard, all 4 steps |
| 3.5–5.5 | Dashboard + candidate card + **refusal card** |
| 5.5–7.0 | **Checkpoint 6h:** full click-through on fixtures |
| 7.0–8.5 | Symbol detail + charts |
| 8.5–10.0 | Desks/portfolio + journal |
| 10.0–11.0 | Swap `API_MODE=live`, fix contract mismatches |
| 11.0–12.0 | Polish, empty/loading/error states, rehearse |

**Cut list if behind, in order:** journal screen → collapse into dashboard rail ·
symbol detail charts → metrics grid only · onboarding wizard → three preset
mandate buttons (conservative / balanced / aggressive).

That last cut is worth pre-building regardless: three preset buttons make the
live demo faster than filling a form on stage.

## 5. Demo choreography

You're driving the screen, so you own the story. Three beats, ~90 seconds:

1. **Mandate** — pick "aggressive, day trading on, micro caps allowed" in two
   clicks.
2. **The refusal** — dashboard loads, a micro-cap is ranked but struck through
   with `⛔ OUTSIDE YOUR MANDATE`, two numbered reasons. Say the line: *"it
   found the opportunity and then refused it, because the user said they'd day
   trade and this stock can't be exited without moving the price."*
3. **The trade** — a SUITABLE large-cap goes to the swing desk, the risk manager
   resizes it to the 10% cap, the journal shows the verdict with `rule_fired`.

Ending on the audit trail, not on a P&L number, is the right call for a judged
demo — it's the part nobody else will have.

## 6. Verification

- Every screen renders correctly with `API_MODE=fixtures` and no backend running
- Every screen has a loading skeleton and an error state — a judge *will* watch
  something fail to load
- `PAPER` badge visible on dashboard, desks and journal, driven by
  `health.gate_armed`
- Disclaimer footer present on every route
- Test at 1366×768 — the projector at the venue is not your monitor
- Full click-through with the laptop's Wi-Fi off
