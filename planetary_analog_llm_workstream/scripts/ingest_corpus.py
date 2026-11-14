"""Ingest the assistant documentation corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant.config import Settings  # noqa: E402
from assistant.ingestion.store import DocumentStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest assistant corpus into SQLite FTS5")
    parser.add_argument("--corpus", default=None, help="directory to ingest")
    parser.add_argument("--db", default=None, help="SQLite database path")
    args = parser.parse_args()

    settings = Settings()
    store = DocumentStore(args.db or settings.db_path)
    try:
        result = store.ingest_directory(args.corpus or settings.corpus_dir)
        print(json.dumps({**result, "stats": store.stats()}, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
