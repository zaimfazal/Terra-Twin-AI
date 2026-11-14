"""Run the assistant API locally (uvicorn)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from assistant.api import create_app  # noqa: E402
from assistant.config import Settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evidence-grounded assistant API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    app = create_app(Settings())
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
