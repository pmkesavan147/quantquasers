# Integration review — what I pulled, what was wrong, what I changed

Reviewed at the point where Track 1 (`origin/main`) and Track 3
(`origin/feature-branch`) were merged into `main` alongside the built Track 2.
Findings are ordered by how badly they hurt the final demo.

## Verdict in one line

Three tracks had built three different products. Track 2 had a working
sentiment-gated trading floor with 151 tests; Track 1 had a Colab notebook that
cannot run on this machine and none of the pipeline it owns; Track 3 had a
good-looking UI wired entirely to random numbers, with its own second
allocation engine that contradicted the backend's. Nothing connected to
anything.

---

## Blocking: three incompatible domain models

| Concept | Track 1 | Track 2 | Track 3 |
|---|---|---|---|
| What gets allocated | — | desks: `day` / `swing` / `long_term` | asset classes: `equity` / `bonds` / `intraday` / `cash` |
| Trader type vocabulary | `long_term` / `swing` / `intraday` / `hybrid` | `Horizon` = `day` / `swing` / `long_term` | same as Track 1 |
| Who computes the split | — | Python rubric in `trading/allocation.py` | a **second** engine in TypeScript, in the browser |
| Universe | — | NSE symbols from fixtures | `AAPL`, `TSLA`, `NVDA`, `USD/INR`, `GOLD` |

`core/contracts.py` was the agreed contract and only Track 2 built against it.

**Fixed by** making `core/contracts.py` authoritative everywhere:
`intraday`/`hybrid` are gone, `Horizon` is the only trader-type vocabulary, and
bonds/cash — which this system never trades — are gone with them. The frontend
now renders desks.

## Blocking: Track 1 shipped ~5% of what it owns

`Task 1` (no extension, so not importable, and line 1 is `!pip install`) is an
investor-personality quiz for a Colab cell. Missing entirely: news ingest,
headline scoring, quant metrics, the mandate refusal engine, the ranker, and
`api/routes_sentiment.py` — i.e. everything that turns news into a `Candidate`.
Track 2 was running on committed fixtures because there was no producer.

**Fixed by** building `ingest/`, `gemma/`, `selection/` and
`api/routes_sentiment.py` to the Track 1 spec, and folding the quiz into
`gemma/quiz.py` where it maps onto `RiskProfile` instead of a private dict.

## Blocking: the model path could not run here

`Task 1` loads `unsloth/gemma-4-E4B-it-unsloth-bnb-4bit` with 4-bit
quantisation. That needs CUDA; this machine has no NVIDIA GPU and no Ollama.
The demo would have died on `import unsloth`.

**Fixed by** a provider layer (`gemma/client.py`) with one call signature and
three backends — Google AI Studio (`gemma-4-26b-a4b-it`, free tier), local
Ollama if present, and a deterministic offline stub. Every response is cached to
disk by prompt hash, so a rehearsed demo is reproducible and instant, and venue
Wi-Fi failing is survivable. The GPU path lives on in
`scripts/gemma_gpu_local.py` for the other laptop, and returns the identical
JSON contract.

## Serious: the browser was making up the numbers

`sentiment-portfolio/src/lib/allocation.ts` moved asset-class weights directly
from sentiment scores, client-side. That breaks the project's one design
principle — *Gemma classifies and explains; it never decides and never counts* —
and it disagreed with `trading/allocation.py`, so the same profile produced two
different portfolios depending on which layer you asked.

`services/mockApi.ts` was worse for a demo: `Math.random()` jitter on every
call, `Date.now()` timestamps, invented tickers, and a keyword bag-of-words
"LLM". Refreshing the dashboard changed the portfolio for no reason.

**Fixed by** deleting both files. The frontend now has one typed client
(`src/services/api.ts`) and renders only numbers the backend computed.

## Serious: no error, empty or loading states in the UI

Every page assumed data was present (`if (!persona) return null`), and the store
had no error field — a failed call left a spinner forever. There was also no
`.env` handling, so the API base URL was nowhere.

**Fixed by** a client that surfaces status codes, and per-page error/empty
states.

## Moderate

- **`select/` as a package name shadows the Python stdlib `select` module.**
  The spec named it that; I used `selection/` instead. A stdlib shadow that only
  bites inside `socket`/`asyncio` internals is exactly the bug you do not want
  to debug during a hackathon.
- **`Task 1` scored the quiz into `risk_score` 0–1**, while
  `trading/allocation.py` scores 0–11 and bands from it. Two rubrics, two
  answers. The 0–11 rubric wins; the quiz now feeds it inputs rather than
  computing a parallel score.
- **Gemma's `trader_type` was being trusted outright** in Track 1's script.
  Contract says advisory: it may move the band one notch, above a 0.70
  confidence floor. Enforced in `trading/allocation.py`, which the quiz output
  now flows through.
- **Fonts loaded from the Google Fonts CDN** in `index.html`, while the plan
  calls for an offline demo rehearsal. Left as-is but flagged: the stack
  degrades to system fonts, it does not break.
- **`package.json` has a `lint` script but no ESLint dependency.** Removed the
  script rather than shipping a command that always fails.
- **`tsconfig.tsbuildinfo` was committed.** Build artifact; now gitignored.
- **Track 3's `RebalanceEvent.feedback` was UI-only state** — thumbs up/down
  vanished on reload. Now written to the append-only journal, which is where
  auditable events belong.

## Not changed, deliberately

- Track 3's design system (palette, `Space Grotesk`/`IBM Plex Mono`, tabular
  numerals, `prefers-reduced-motion` handling, the `light:` Tailwind variant).
  It is good work; only the data layer under it was wrong.
- Track 1's quiz *questions*. The wording is better than anything I would have
  written under time pressure; the scoring and plumbing around them changed.
- Track 2's journal-replay architecture and the triple-locked live gate.
