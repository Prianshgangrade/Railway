"""ASGI entrypoint for deployment.
Run with: gunicorn -k uvicorn.workers.UvicornWorker -w 1 asgi:app
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path (robust on Render/monorepos)
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.index.fastapi_app import app  # noqa: E402


if __name__ == "__main__":  # Local debug helper
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
