"""Run one real local-model generation and record the exact result.

Fails with exit code 2 if Ollama or the configured model is unavailable. It
never substitutes the deterministic fallback for a model run.

Usage:
    python scripts/smoke_model.py
    python scripts/smoke_model.py --candidate CAND-001 --question "..."
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant.config import Settings  # noqa: E402
from assistant.service import AssistantService  # noqa: E402

DEFAULT_QUESTION = (
    "Which scientific dimensions have the strongest evidence for CAND-001, "
    "and what remains unavailable?"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--candidate", default="CAND-001")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--results-dir", type=Path, default=ROOT / "evaluation" / "results"
    )
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="assistant-model-smoke-"))
    settings = Settings(
        db_path=workdir / "smoke.db",
        corpus_dir=ROOT / "corpus",
        fixture_records_path=ROOT / "fixtures" / "test_only_platform_records.json",
        structured_backend="fixture",
        allow_fixture_data=True,
        auto_ingest_corpus=True,
        ollama_base_url=args.ollama_url,
        ollama_timeout_s=600.0,
        ollama_health_timeout_s=5.0,
        **({"ollama_model": args.model} if args.model else {}),
    )
    service = AssistantService(settings)
    try:
        health = service.generator.health()
        print(json.dumps({"health": health}, indent=2))
        if not health.get("available") or not health.get("configured_model_present"):
            print(
                "refusing to run: Ollama/model is not available; no fallback result "
                "will be reported as a model run",
                file=sys.stderr,
            )
            return 2

        pack = service.assembler.assemble(
            question=args.question,
            candidate_id=args.candidate,
        )
        started = time.perf_counter()
        outcome = service.generator.generate(pack)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        answer = outcome.answer
        record = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "question": args.question,
            "candidate_id": args.candidate,
            "ollama": {
                "base_url": health.get("base_url"),
                "configured_model": health.get("configured_model"),
                "installed_models": health.get("installed_models"),
            },
            "elapsed_ms": elapsed_ms,
            "generation_mode": answer.generation_mode.value,
            "model": outcome.model,
            "prompt_eval_count": outcome.prompt_eval_count,
            "eval_count": outcome.eval_count,
            "error": outcome.error,
            "validation": answer.validation.model_dump(mode="json"),
            "claim_count": len(answer.claims),
            "claim_evidence_ids": [
                eid for claim in answer.claims for eid in claim.evidence_ids
            ],
            "missing_evidence_ids": [
                item.evidence_id for item in answer.missing_evidence
            ],
            "supplied_scores": [
                score.model_dump(mode="json") for score in answer.supplied_scores
            ],
            "answer_summary": answer.answer_summary,
            "raw_model_output": outcome.raw_output,
        }

        args.results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = args.results_dir / f"model-smoke-{stamp}.json"
        out.write_text(json.dumps(record, indent=2), encoding="utf-8")

        print(
            json.dumps(
                {
                    "elapsed_ms": elapsed_ms,
                    "generation_mode": record["generation_mode"],
                    "model": record["model"],
                    "error": record["error"],
                    "claim_count": record["claim_count"],
                    "validation": record["validation"],
                    "answer_summary": record["answer_summary"],
                    "saved_to": str(out),
                },
                indent=2,
            )
        )
        return 0 if answer.generation_mode.value == "model" else 1
    finally:
        service.store.close()


if __name__ == "__main__":
    raise SystemExit(main())
