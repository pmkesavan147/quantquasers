"""Selection — deterministic, no LLM anywhere in this package.

Named `selection`, not `select`, because `select` is a Python standard library
module and shadowing it breaks `socket`/`asyncio` internals in ways that are
miserable to debug.

    universe.py   the curated symbol list and its cap buckets
    quant.py      OHLCV -> QuantMetrics (pure pandas)
    sentiment.py  HeadlineScore[] -> SymbolSentiment (weighted in Python)
    mandate.py    the refusal engine — seven rules, each with its number
    ranker.py     composite score per horizon
    pipeline.py   news + prices -> Candidate[], which is what Track 2 consumes
"""
