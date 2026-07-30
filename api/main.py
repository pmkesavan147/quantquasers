"""FastAPI app.

Track 1's routes are mounted if present. The import is guarded so this
server runs before their track has landed — the trading half must not be
blocked on the sentiment half existing.

    uvicorn api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes_trading import router as trading_router

app = FastAPI(
    title="QuantQuasers",
    description=(
        "Sentiment-driven paper trading across three desks. "
        "Educational analysis only — not investment advice, and not issued by "
        "a SEBI-registered Research Analyst or Investment Adviser."
    ),
    version="0.1.0",
)

# Track 3 shipped Vite, not Next.js — 5173 is the dev server, 4173 is
# `vite preview`. 3000 stays allowed so a Next.js port change needs no redeploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
        "http://localhost:3000", "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trading_router)

try:  # Track 1, when it lands
    from api.routes_sentiment import router as sentiment_router

    app.include_router(sentiment_router)
    SENTIMENT_ROUTES = True
except ImportError:
    SENTIMENT_ROUTES = False


@app.on_event("startup")
def _warm_model() -> None:
    """One throwaway generation at boot.

    A cold local model takes ~10s on its first call and an AI Studio client
    pays TLS setup once. Paying either during startup beats paying it while a
    judge watches the onboarding spinner. Failure here is ignored by design —
    `gemma.client` never raises, it downgrades.
    """
    import os

    if os.getenv("GEMMA_WARM", "1") != "1":
        return
    from gemma.client import warm

    warm()


@app.get("/")
def root() -> dict:
    from gemma.client import status as gemma_status

    return {
        "service": "quantquasers",
        "sentiment_routes_mounted": SENTIMENT_ROUTES,
        "gemma": gemma_status(),
        "docs": "/docs",
    }
