"""Vercel's entrypoint. One function, the whole ASGI app behind it.

`vercel.json` builds only this file and routes every path to it, so the app runs
as a single serverless function rather than Vercel treating each module under
`api/` as its own endpoint.

Deployed instances differ from a laptop in three ways, all of them environment
rather than code:

* `SNAPSHOT=1` — prices and headlines come from `data/snapshot/`, because a
  serverless request cannot wait on yfinance for 40 symbols.
* `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` — the journal lives in Postgres,
  because the filesystem is wiped between invocations and the portfolio is
  derived by replaying that journal.
* `GEMMA_CACHE_DIR=data/snapshot/gemma` — model answers replay from the
  committed cache instead of costing an API call per headline per request.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The function's working directory is the deployment root, but the root is not
# guaranteed to be on sys.path — without this, `import api.main` fails at cold
# start with a ModuleNotFoundError that says nothing useful.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.main import app  # noqa: E402

__all__ = ["app"]
