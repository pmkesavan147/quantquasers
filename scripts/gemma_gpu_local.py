"""Run Gemma 4 on a real GPU — for the second laptop, not the demo machine.

Two modes, both producing exactly what `gemma/client.py` expects:

    # 1. Pre-score everything into the shared cache, then copy the folder over
    python -m scripts.gemma_gpu_local --warm
    #    -> data/cache/gemma/*.json  (copy this directory to the demo laptop)

    # 2. Serve the model on the LAN and point the demo machine at it
    python -m scripts.gemma_gpu_local --serve --host 0.0.0.0 --port 8077
    #    on the demo laptop:  set GEMMA_REMOTE_URL=http://<gpu-laptop-ip>:8077

Model IDs (verified on Hugging Face):

    google/gemma-4-E2B-it            ~2B effective, runs on 8GB VRAM
    google/gemma-4-E4B-it            default here, comfortable on 12-16GB
    google/gemma-4-12B-it            needs ~24GB in bf16
    google/gemma-4-26B-A4B-it        MoE, A100/H100 territory in bf16
    unsloth/gemma-4-E4B-it-unsloth-bnb-4bit   4-bit, if Unsloth is installed

Install on the GPU box (CUDA 12.x wheels):

    pip install "torch>=2.4" --index-url https://download.pytorch.org/whl/cu124
    pip install transformers accelerate bitsandbytes
    # optional, faster:  pip install unsloth

The prompts, the system strings and the JSON contract are imported from the same
modules the API uses, so a response produced here is indistinguishable from one
produced by AI Studio. That is the point: swap the compute, keep the behaviour.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "google/gemma-4-E4B-it"

_model = None
_tokenizer = None
_model_id = DEFAULT_MODEL


def load(model_id: str = DEFAULT_MODEL, four_bit: bool = False):
    """Load once. Prefers Unsloth when installed, plain transformers otherwise."""
    global _model, _tokenizer, _model_id
    if _model is not None:
        return _model, _tokenizer

    _model_id = model_id
    print(f"loading {model_id} (4bit={four_bit}) ...", flush=True)

    try:
        from unsloth import FastModel

        _model, _tokenizer = FastModel.from_pretrained(
            model_name=model_id, max_seq_length=2048, load_in_4bit=four_bit
        )
        FastModel.for_inference(_model)
        print("loaded via unsloth", flush=True)
        return _model, _tokenizer
    except ImportError:
        pass

    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    kwargs: dict = {"device_map": "auto", "dtype": torch.bfloat16}
    if four_bit:
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
        )
        kwargs.pop("dtype")

    # Gemma 4 is natively multimodal, so the checkpoint ships a *processor*
    # rather than a plain tokenizer. Message content must be a list of typed
    # parts even for text-only prompts, and the chat template needs
    # return_dict=True to hand back tensors instead of a rendered string.
    _tokenizer = AutoProcessor.from_pretrained(model_id)
    _model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
    _model.eval()
    print(f"loaded via transformers on {_model.device}", flush=True)
    return _model, _tokenizer


def generate(prompt: str, system: str = "", temperature: float = 0.0,
             max_new_tokens: int = 400) -> str:
    model, tok = load(_model_id)
    import torch

    text = f"{system.strip()}\n\n{prompt}" if system else prompt
    messages = [{"role": "user", "content": [{"type": "text", "text": text}]}]
    inputs = tok.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)

    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=temperature > 0,
            pad_token_id=getattr(tok, "eos_token_id", None)
            or getattr(getattr(tok, "tokenizer", None), "eos_token_id", None),
        )

    prompt_len = inputs["input_ids"].shape[-1]
    return tok.decode(out[0][prompt_len:], skip_special_tokens=True).strip()


# ── mode 1: fill the shared cache ────────────────────────────────────────
def warm_cache(limit: int | None = None, model_id: str = DEFAULT_MODEL,
               four_bit: bool = False) -> None:
    """Score every headline and profile the demo will need, into the cache.

    Writes with the same key function the app reads with — hash of
    (namespace, system, prompt, temperature) — so the demo laptop replays these
    answers with no GPU, no API key and no network.
    """
    load(model_id, four_bit)

    from gemma import client
    from gemma.scorers import (
        CLASSIFIER_SYSTEM,
        EVENT_TYPES,
        HEADLINE_PROMPT,
        _HeadlineOut,
    )
    from ingest.news import headlines_for
    from selection.universe import company_name, universe

    symbols = sorted(universe())[: limit or len(universe())]
    written = 0

    for i, symbol in enumerate(symbols, 1):
        for h in headlines_for(symbol, company_name(symbol)):
            # The cache key is the *unaugmented* prompt, exactly as
            # gemma/scorers.py passes it. The JSON instruction is appended only
            # for the model's benefit.
            prompt = HEADLINE_PROMPT.format(
                title=h.title,
                company=company_name(symbol),
                events=", ".join(EVENT_TYPES),
            )
            if client.cached_response(CLASSIFIER_SYSTEM, prompt, 0.0) is not None:
                continue

            reply = generate(
                prompt + client.json_instruction(_HeadlineOut),
                system=CLASSIFIER_SYSTEM,
                temperature=0.0,
                max_new_tokens=220,
            )
            client.cache_put(CLASSIFIER_SYSTEM, prompt, 0.0, _model_id, reply)
            written += 1
            print(f"[{i:>3}/{len(symbols)}] {symbol:12} {h.title[:58]:60} "
                  f"-> {reply[:60].replace(chr(10), ' ')}", flush=True)

    print(f"\nwrote {written} new responses to {client.CACHE_DIR}")
    print("copy that directory to the demo machine's data/cache/gemma/")


# ── mode 2: serve on the LAN ─────────────────────────────────────────────
def serve(host: str = "0.0.0.0", port: int = 8077,
          model_id: str = DEFAULT_MODEL, four_bit: bool = False) -> None:
    """A two-endpoint HTTP server: GET /health, POST /generate.

    Deliberately stdlib-only — no FastAPI on the GPU box, nothing else to
    install, nothing else to go wrong ten minutes before a demo.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    load(model_id, four_bit)

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/health":
                self._json(200, {"ok": True, "model": _model_id})
            else:
                self._json(404, {"error": "try /health or POST /generate"})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/generate":
                self._json(404, {"error": "POST /generate"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                req = json.loads(self.rfile.read(length) or b"{}")
                started = datetime.now()
                text = generate(
                    req.get("prompt", ""),
                    system=req.get("system", ""),
                    temperature=float(req.get("temperature", 0.0)),
                    max_new_tokens=int(req.get("max_new_tokens", 400)),
                )
                took = (datetime.now() - started).total_seconds()
                print(f"generated {len(text)} chars in {took:.1f}s", flush=True)
                self._json(200, {"text": text, "model": _model_id,
                                 "seconds": round(took, 2)})
            except Exception as exc:  # a bad request must not kill the server
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def log_message(self, *_args):
            pass  # own logging above; the default access log is noise

    print(f"serving {_model_id} on http://{host}:{port}")
    print(f"on the demo laptop: set GEMMA_REMOTE_URL=http://<this-ip>:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--4bit", dest="four_bit", action="store_true",
                    help="bitsandbytes 4-bit — needed under ~12GB VRAM")
    ap.add_argument("--warm", action="store_true", help="fill the shared cache")
    ap.add_argument("--serve", action="store_true", help="serve on the LAN")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N symbols, for a quick check")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8077)
    ap.add_argument("--ask", default=None, help="one-shot prompt, then exit")
    args = ap.parse_args()

    if args.ask:
        load(args.model, args.four_bit)
        print(generate(args.ask))
    elif args.warm:
        warm_cache(args.limit, args.model, args.four_bit)
    elif args.serve:
        serve(args.host, args.port, args.model, args.four_bit)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
