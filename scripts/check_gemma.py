"""Prove the model path works before you need it on stage.

    python -m scripts.check_gemma

Prints which backend resolved, sends one real headline through the classifier,
and one survey through the profiler. Exit code 0 means a model answered; 1 means
you are running on the keyword fallback — which still works, but says
`model="fallback"` on every row it touches.
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gemma import client
from gemma.scorers import profile_user, score_headline

HEADLINE = "Sun Pharma receives USFDA observations for its Halol facility"


def main() -> int:
    status = client.status()
    print("backend        :", status["backend"])
    print("model          :", status["model"])
    print("api key present:", status["api_key_present"])
    print("cached          :", status["cached_responses"], "responses")
    print("cache dir      :", status["cache_dir"])

    if status["backend"] == "stub":
        print(
            "\nNo model reachable. Set GOOGLE_API_KEY in .env (free key at\n"
            "https://aistudio.google.com/apikey), or point GEMMA_REMOTE_URL at a\n"
            "GPU box running scripts/gemma_gpu_local.py --serve, or install\n"
            "Ollama and `ollama pull gemma3:4b`."
        )
        return 1

    print("\nwarming up ...", client.warm())

    print(f"\nheadline: {HEADLINE}")
    scored = score_headline(HEADLINE, "Sun Pharmaceutical", symbol="SUNPHARMA",
                            id="check-1", source="check")
    print(f"  sentiment  : {scored.sentiment:+.2f} ({scored.label})")
    print(f"  event      : {scored.event_type}  materiality {scored.materiality}/5")
    print(f"  rationale  : {scored.rationale}")
    print(f"  scored by  : {scored.model}")

    horizon, confidence, why = profile_user(
        rubric_score=6,
        rubric_band="balanced",
        mcq={"horizons": ["swing", "long_term"], "day_trading": False},
        free_text={
            "Think of the last time something you held dropped hard. What did "
            "you actually do?":
                "I bought more over the following month and never sold any of it",
            "What would make you say this worked — and by when?":
                "beating my FD over three or four years without watching screens",
        },
    )
    print("\nsurvey read:")
    print(f"  trader type: {horizon.value if horizon else 'no read'}")
    print(f"  confidence : {confidence:.2f}")
    print(f"  reasoning  : {why}")

    if scored.model == "fallback" and horizon is None:
        print("\nThe backend resolved but every call fell back — check the key/quota.")
        return 1

    print("\nOK — a model answered. Responses are cached, so this run is now "
          "reproducible offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
