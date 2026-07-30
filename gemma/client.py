"""One call signature, three backends, and a disk cache in front of all of them.

    generate(prompt, schema=..., system=...) -> str

Backends, in the order `auto` tries them:

1. **Google AI Studio** — Gemma 4 (`gemma-4-26b-a4b-it`), free tier. Chosen
   when `GOOGLE_API_KEY` (or `AI_STUDIO_KEY`) is set.
2. **Remote** — a GPU box on the LAN running `scripts/gemma_gpu_local.py
   --serve`. Chosen when `GEMMA_REMOTE_URL` is set.
3. **Ollama** — a local `gemma3:4b`-class model, when the daemon answers.
4. **Stub** — a deterministic keyword scorer that runs with no model at all.

The stub is not a nicety. A demo that dies because venue Wi-Fi dropped is a
demo that scores zero, so every path degrades instead of raising, and every
response carries the backend that produced it (see `last_model()`).

Caching is by hash of (system, prompt, temperature) into `data/cache/gemma/`.
Rehearse once, and the rehearsed run replays instantly and identically — which
also means a judge asking "run it again" gets the same answer, as they should
from a system whose numbers are deterministic.

The key deliberately excludes the backend and the model, so a cache built on a
GPU machine replays byte-for-byte on the laptop running the demo. The model that
produced each entry is recorded inside the file. Set `GEMMA_CACHE_NAMESPACE`
when you want a clean slate after switching models.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

try:  # .env is how the API key arrives; load it before reading any of this
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is in requirements.txt
    pass

Backend = Literal["studio", "ollama", "remote", "stub"]

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.getenv("GEMMA_CACHE_DIR", ROOT / "data" / "cache" / "gemma"))

# gemma-4-31b-it, not the 26b MoE. Both are Gemma 4 on AI Studio, but the MoE
# thinks until it hits max_output_tokens on anything longer than a headline: the
# investor-profiling prompt burned 1597, 2497 and 2997 thinking tokens at
# budgets of 1600, 2500 and 3000 and returned an empty string every time, only
# answering at 6000 (86 s — past a serverless timeout). The dense 31b answers
# the same prompt in 739 thinking tokens and 23 s. Cache keys exclude the model,
# so the headline cache built on the 26b still replays unchanged.
STUDIO_MODEL = os.getenv("GEMMA_STUDIO_MODEL", "gemma-4-31b-it")
OLLAMA_MODEL = os.getenv("GEMMA_OLLAMA_MODEL", "gemma3:4b")
REMOTE_URL = os.getenv("GEMMA_REMOTE_URL", "").rstrip("/")
REMOTE_TIMEOUT = float(os.getenv("GEMMA_REMOTE_TIMEOUT_S", "120"))
CACHE_NAMESPACE = os.getenv("GEMMA_CACHE_NAMESPACE", "shared")

# Gemma 4 thinks before it answers, and those thinking tokens come out of
# max_output_tokens. At 400 the model spends the entire budget reasoning and
# returns an empty response with finish_reason=MAX_TOKENS — which looks exactly
# like a broken API key from the outside. Measured: ~400-550 thinking tokens for
# a one-headline classification, so the budget has to clear that with room for
# the answer. `thinking_config` cannot fix this; the API rejects it for Gemma.
MAX_TOKENS = int(os.getenv("GEMMA_MAX_TOKENS", "1600"))

# One retry at a bigger budget when the first attempt came back empty *because*
# it ran out of tokens. Capped rather than unbounded: a serverless request that
# waits three minutes for a model has already failed the user, and the rubric
# answer underneath is a good one.
MAX_TOKENS_CEILING = int(os.getenv("GEMMA_MAX_TOKENS_CEILING", "3200"))

_lock = threading.Lock()
_resolved: Backend | None = None
_studio_client = None
_last_model = "none"
_last_error = ""


def _api_key() -> str | None:
    return (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("AI_STUDIO_KEY")
        or None
    )


# ── backend resolution ───────────────────────────────────────────────────
def _try_studio() -> bool:
    global _studio_client
    key = _api_key()
    if not key:
        return False
    try:
        from google import genai

        _studio_client = genai.Client(api_key=key)
        return True
    except Exception:
        _studio_client = None
        return False


def _try_ollama() -> bool:
    try:
        import ollama

        ollama.Client(timeout=2).list()
        return True
    except Exception:
        return False


def _try_remote() -> bool:
    if not REMOTE_URL:
        return False
    try:
        import urllib.request

        with urllib.request.urlopen(f"{REMOTE_URL}/health", timeout=4) as resp:
            return resp.status == 200
    except Exception:
        return False


def resolve_backend(force: bool = False) -> Backend:
    """Which backend this process will use. Sticky — resolved once."""
    global _resolved
    with _lock:
        if _resolved is not None and not force:
            return _resolved

        want = os.getenv("GEMMA_BACKEND", "auto").lower()
        if want in ("studio", "ollama", "remote", "stub"):
            # An explicit choice is honoured even if unreachable, so a
            # misconfiguration is loud rather than silently downgraded.
            if want == "studio":
                _try_studio()
            _resolved = want  # type: ignore[assignment]
        elif _try_studio():
            _resolved = "studio"
        elif _try_remote():
            _resolved = "remote"
        elif _try_ollama():
            _resolved = "ollama"
        else:
            _resolved = "stub"
        return _resolved


def model_name(backend: Backend | None = None) -> str:
    b = backend or resolve_backend()
    return {
        "studio": STUDIO_MODEL,
        "ollama": OLLAMA_MODEL,
        "remote": os.getenv("GEMMA_REMOTE_MODEL", "gemma-4-gpu"),
        "stub": "fallback",
    }[b]


def last_model() -> str:
    """The model that answered the most recent call — 'fallback' if none did.

    Written into every `HeadlineScore.model`, so the UI can be honest about
    which rows a model actually touched.
    """
    return _last_model


def last_error() -> str:
    """Why the most recent call produced nothing — "" when it produced text.

    Without this, a truncated response, an expired key and a dropped connection
    all reach the UI as the same silent fallback, and the first thing anyone
    asks when they see "rubric used alone" is which one it was.
    """
    return _last_error


def status() -> dict:
    b = resolve_backend()
    return {
        "backend": b,
        "model": model_name(b),
        "api_key_present": _api_key() is not None,
        "cache_dir": str(CACHE_DIR),
        "cached_responses": len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.exists() else 0,
        "last_model": _last_model,
        "last_error": _last_error,
    }


# ── cache ────────────────────────────────────────────────────────────────
def _cache_key(system: str, prompt: str, temp: float) -> str:
    blob = json.dumps([CACHE_NAMESPACE, system, prompt, temp], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _cache_read(key: str) -> tuple[str, str] | None:
    """`(response, model_that_produced_it)`.

    The model comes out of the file rather than from the current config, so a
    cache built on the GPU box does not get relabelled with the local model's
    name. What the UI shows stays true.
    """
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
        return blob["response"], blob.get("model", "cache")
    except Exception:
        return None


def _cache_write(key: str, model: str, prompt: str, response: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(
            json.dumps({"model": model, "prompt": prompt, "response": response},
                       indent=1),
            encoding="utf-8",
        )
    except OSError:
        pass  # a read-only disk must not break generation


# ── generation ───────────────────────────────────────────────────────────
def json_instruction(schema: type[BaseModel]) -> str:
    """The exact suffix appended when a backend cannot constrain decoding.

    Public because `scripts/gemma_gpu_local.py` must send a byte-identical
    prompt for its pre-scored answers to be usable here.
    """
    return (
        "\n\nReply with ONE JSON object and nothing else — no prose, no "
        "markdown fences. Keys and types exactly:\n"
        + json.dumps(_schema_hint(schema), indent=2)
    )


def _truncated(resp) -> bool:
    """True when the model stopped because it ran out of tokens.

    That is the one empty response a bigger budget can fix. An empty response
    from a safety block or an empty prompt cannot be, and retrying it just costs
    the user another 25 seconds.
    """
    for candidate in getattr(resp, "candidates", None) or []:
        if "MAX_TOKENS" in str(getattr(candidate, "finish_reason", "")):
            return True
    return False


def _studio_generate(prompt: str, schema: type[BaseModel] | None,
                     system: str, temperature: float,
                     max_tokens: int | None = None) -> str:
    from google.genai import types

    # Gemma models on the Gemini API do not take a system_instruction, so the
    # system prompt is prepended. JSON mode is likewise not guaranteed for the
    # open models — ask for JSON in words, then parse defensively upstream.
    # `thinking_config` is not an option either: the API rejects it for Gemma
    # with "Thinking budget is not supported for this model", so the only lever
    # over thinking tokens is the total budget.
    full = f"{system.strip()}\n\n{prompt}" if system else prompt
    if schema is not None:
        full += json_instruction(schema)

    global _last_error
    budget = max_tokens or MAX_TOKENS
    while True:
        resp = _studio_client.models.generate_content(  # type: ignore[union-attr]
            model=STUDIO_MODEL,
            contents=full,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=budget,
            ),
        )
        text = (resp.text or "").strip()
        if text:
            _last_error = ""  # a retry that worked is not an error
            return text

        if not _truncated(resp):
            _last_error = "model returned an empty response"
            return ""

        thoughts = getattr(resp.usage_metadata, "thoughts_token_count", None)
        _last_error = (
            f"{STUDIO_MODEL} spent its whole {budget}-token budget thinking"
            + (f" ({thoughts} thinking tokens)" if thoughts else "")
        )
        if budget >= MAX_TOKENS_CEILING:
            return ""
        budget = min(budget * 2, MAX_TOKENS_CEILING)


def _ollama_generate(prompt: str, schema: type[BaseModel] | None,
                     system: str, temperature: float,
                     max_tokens: int | None = None) -> str:
    import ollama

    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    resp = ollama.Client().chat(
        model=OLLAMA_MODEL,
        messages=msgs,
        # Ollama constrains decoding to the schema, which is the single most
        # reliable way to get JSON out of a 4B model.
        format=schema.model_json_schema() if schema else None,
        options={"temperature": temperature,
                 "num_predict": max_tokens or MAX_TOKENS},
        keep_alive="30m",
    )
    return (resp.message.content or "").strip()


def _remote_generate(prompt: str, schema: type[BaseModel] | None,
                     system: str, temperature: float,
                     max_tokens: int | None = None) -> str:
    """Ask a GPU box on the LAN — see `scripts/gemma_gpu_local.py --serve`."""
    import urllib.request

    body = json.dumps(
        {
            "prompt": prompt,
            "system": system,
            "temperature": temperature,
            "schema": _schema_hint(schema) if schema else None,
            "max_tokens": max_tokens or MAX_TOKENS,
        }
    ).encode()
    req = urllib.request.Request(
        f"{REMOTE_URL}/generate", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as resp:
        return (json.load(resp).get("text") or "").strip()


def _schema_hint(schema: type[BaseModel]) -> dict:
    """A compact {field: type} sketch — the full JSON Schema wastes tokens."""
    out = {}
    for name, field in schema.model_fields.items():
        ann = field.annotation
        out[name] = getattr(ann, "__name__", str(ann))
    return out


def generate(
    prompt: str,
    schema: type[BaseModel] | None = None,
    system: str = "",
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> str:
    """Raw text from whichever backend is live. Never raises.

    Returns "" when no model could answer; callers must have a deterministic
    fallback for that case, which is why every scorer here does. When it does
    return "", `last_error()` says why.
    """
    global _last_model, _last_error
    backend = resolve_backend()
    model = model_name(backend)

    key = _cache_key(system, prompt, temperature)
    cached = _cache_read(key)
    if cached is not None:
        response, cached_model = cached
        _last_model = cached_model
        _last_error = ""
        return response

    if backend == "stub":
        _last_model = "fallback"
        _last_error = "no model backend available (no API key, no local daemon)"
        return ""

    backends = {
        "studio": _studio_generate,
        "ollama": _ollama_generate,
        "remote": _remote_generate,
    }
    _last_error = ""
    try:
        text = backends[backend](prompt, schema, system, temperature, max_tokens)
    except Exception as exc:
        _last_model = "fallback"
        _last_error = f"{type(exc).__name__}: {exc}"[:300]
        return ""

    _last_model = model if text else "fallback"
    if text:
        _cache_write(key, model, prompt, text)
    return text


def cache_key_for(system: str, prompt: str, temperature: float = 0.0) -> str:
    """The key `generate()` would use. For cache-filling tools."""
    return _cache_key(system, prompt, temperature)


def cached_response(
    system: str, prompt: str, temperature: float = 0.0
) -> tuple[str, str] | None:
    return _cache_read(_cache_key(system, prompt, temperature))


def cache_put(
    system: str, prompt: str, temperature: float, model: str, response: str
) -> str:
    """Insert a response produced elsewhere — a GPU box, a batch job.

    Returns the key it was written under. Prompts must match byte-for-byte, so
    build them with the same module constants the app uses.
    """
    key = _cache_key(system, prompt, temperature)
    _cache_write(key, model, prompt, response)
    return key


def warm() -> dict:
    """One tiny call at startup. The first cold call to a local model is ~10s;
    paying that during FastAPI boot is better than during the demo."""
    backend = resolve_backend()
    if backend == "stub":
        return {"backend": backend, "warm": False, "reply": ""}
    reply = generate("Reply with the single word: OK", temperature=0.0)
    return {"backend": backend, "warm": bool(reply), "reply": reply[:40]}


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response.

    Models wrap JSON in fences, prefix it with "Here you go:", or trail a
    sentence after it. Raises ValueError when there is nothing usable — callers
    catch that and fall back.
    """
    if not text:
        raise ValueError("empty response")

    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in response: {text[:120]!r}")

    # Scan for the matching brace instead of a greedy regex, so a trailing
    # sentence containing "}" cannot swallow the parse.
    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise ValueError(f"unbalanced JSON in response: {text[:120]!r}")
