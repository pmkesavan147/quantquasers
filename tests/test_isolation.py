"""The model provably cannot place an order.

This is the shortest, highest-value test in the repo: it converts
"Gemma doesn't decide trades" from a claim into a property enforced by CI.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRADING = ROOT / "trading"
SELECTION = ROOT / "selection"

# Anything that talks to a model, or could.
FORBIDDEN_MODULES = ("gemma", "ollama", "google.generativeai", "google.genai",
                     "openai", "anthropic", "transformers", "unsloth")

# The only module in `selection/` allowed near a model: it orchestrates the
# pipeline, so it calls the scorers. Everything else must be pure arithmetic.
SELECTION_ORCHESTRATOR = "pipeline.py"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_trading_never_imports_the_llm_layer():
    offenders: list[str] = []
    for path in sorted(TRADING.rglob("*.py")):
        for mod in _imported_modules(path):
            root = mod.split(".")[0]
            if root in FORBIDDEN_MODULES or mod in FORBIDDEN_MODULES:
                offenders.append(f"{path.relative_to(ROOT)} imports {mod}")
    assert not offenders, "the trading layer must stay model-free:\n" + "\n".join(offenders)


def test_risk_manager_and_rules_are_free_of_llm_imports_specifically():
    for name in ("risk/manager.py", "sentiment_rules.py", "desks.py"):
        mods = _imported_modules(TRADING / name)
        assert not any(m.split(".")[0] in FORBIDDEN_MODULES for m in mods)


def test_the_scoring_maths_never_imports_the_llm_layer():
    """`selection/` computes; only its orchestrator may speak to a model.

    This is what stops a model from setting a composite score, a cap bucket or a
    mandate verdict — the three places where an invented number would look most
    authoritative.
    """
    offenders: list[str] = []
    for path in sorted(SELECTION.rglob("*.py")):
        if path.name == SELECTION_ORCHESTRATOR:
            continue
        for mod in _imported_modules(path):
            if mod.split(".")[0] in FORBIDDEN_MODULES or mod in FORBIDDEN_MODULES:
                offenders.append(f"{path.relative_to(ROOT)} imports {mod}")
    assert not offenders, "the scoring maths must stay model-free:\n" + "\n".join(
        offenders
    )


def test_the_refusal_engine_does_no_io_at_all():
    """A mandate verdict must be reproducible from its inputs alone."""
    mods = {m.split(".")[0] for m in _imported_modules(SELECTION / "mandate.py")}
    for banned in ("requests", "httpx", "urllib", "sqlite3", "socket", "os",
                   "yfinance", "feedparser", "pandas"):
        assert banned not in mods, f"mandate.py must not import {banned}"


def test_sentiment_rules_does_no_io():
    """Pure functions: no network, no filesystem, no clock of its own."""
    mods = _imported_modules(TRADING / "sentiment_rules.py")
    for banned in ("requests", "httpx", "urllib", "sqlite3", "socket", "os"):
        assert banned not in {m.split(".")[0] for m in mods}
