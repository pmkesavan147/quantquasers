# Demo runbook

Two terminals, six minutes, no network required after the rehearsal step.

## Before you leave the house

```bash
pip install -r requirements.txt
cp .env.example .env                    # paste GOOGLE_API_KEY
python -m scripts.check_gemma           # must print "OK — a model answered"
python -m scripts.build_universe        # live market caps into data/universe.csv
python -m scripts.warm_cache --with-gemma
```

That last command fetches prices and headlines for all 40 symbols and scores
every headline through Gemma, writing the answers to `data/cache/`. After it
finishes, the entire demo runs from disk.

Rehearse the failure case too:

```bash
OFFLINE=1 pytest -q                     # 260 passed
OFFLINE=1 uvicorn api.main:app          # then click through the whole UI
```

If the venue Wi-Fi dies mid-demo, nothing changes: prices and headlines come
from the cache, model answers replay from the cache, and if you wiped the cache
the keyword fallback still fills every contract — the UI just shows
`keyword fallback` in the header and halves its confidence numbers.

## Terminal 1 — API

```bash
cd quantquasers
uvicorn api.main:app --reload            # add OFFLINE=1 to force cache-only
```

## Terminal 2 — UI

```bash
cd quantquasers/sentiment-portfolio
npm run dev                              # http://localhost:5173
```

## The six-minute path

1. **Onboarding** (`/`) — 11 questions. Put ₹2,50,000 in, tick all three
   horizons, say **yes** to intraday, allow large + mid caps, and write two
   sentences in the free-text boxes. Those two boxes are the only place a model
   touches your profile.

2. **Persona** (`/persona`) — the band, the rubric score out of 11, the split in
   rupees, and what Gemma read. Say the line out loud: *the rubric decides, the
   model gets one notch and only above 70% confidence.*

3. **Floor** (`/dashboard`) — pick the **Swing** desk → **Scan the news**. Point
   at a `refused` row and expand it: the reason carries the metric, the value and
   the threshold. Then **Run the desk** → fills, costs, and refusals side by side.

4. **Sentiment** (`/insights`) — expand a symbol. Real headlines, one sentiment
   each, the event tag, the materiality, and which model scored it. The symbol
   score is Python; the model never saw the set.

5. **Audit** (`/journal`) — filter to `verdict`. Every proposal, approval, resize
   and refusal, in order, append-only. Positions are rebuilt by replaying this.

6. **Kill switch** — hit it on the floor, run a desk again, watch every order get
   vetoed with `halted`, then resume.

## The three questions judges ask

**"Is this actually placing orders?"**
No. Live trading needs three independent locks: `LIVE_TRADING=true`, a
`live.lock` file in the repo root, and an interactive `LIVE-CONFIRM` typed at the
prompt. The header shows `paper` and `gate shut` on every screen, and
`/api/health` lists exactly why the gate is shut.

**"What stops the LLM from making up a position size?"**
It never sees one. `gemma/` returns labels and prose; `selection/` and `trading/`
compute every number. `tests/test_isolation.py` fails the build if `trading/`
imports `gemma/`. Gemma's one influence on money is a single-notch shift of the
risk band, gated at 0.70 confidence.

**"Where do the numbers come from?"**
Prices from yfinance (1 year daily, cached to parquet), headlines from Google
News RSS, market caps from a committed snapshot. Every response carries its
provenance: `quant_source` says live vs fixture, `headline_source` says rss vs
cache vs fixture, `headline_models` says which model scored the news.

## If something breaks

| Symptom | Cause | Fix |
|---|---|---|
| UI shows "Cannot reach the API" | uvicorn not running | start terminal 1 |
| Header says `keyword fallback` | no key, no GPU, no Ollama | fine to demo; or fix `GOOGLE_API_KEY` |
| Candidate list is empty | no price history and no fixture for those symbols | `python -m scripts.warm_cache` |
| Sentiment confidence looks low | thin coverage, disagreeing headlines, or fallback scoring | that is the intended behaviour — say so |
| `TATAMOTORS` prices look stale | demerged; Yahoo serves it as `TMPV` | already aliased in `ingest/prices.py` |
| Everything is slow on first call | cold model | `python -m scripts.check_gemma` warms it |
