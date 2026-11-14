"""Run the assistant evaluation questions and record exact results.

Default mode forces the deterministic evidence-only fallback by pointing at an
unused local port. ``--use-model`` requires a healthy Ollama endpoint; it fails
loudly rather than silently evaluating the fallback.

Usage:
    python scripts/run_evaluation.py
    python scripts/run_evaluation.py --use-model --ollama-url http://127.0.0.1:11434
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant.config import Settings  # noqa: E402
from assistant.contracts import ChatRequest  # noqa: E402
from assistant.service import AssistantService  # noqa: E402


def load_questions(path: Path) -> list[dict]:
    questions = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            questions.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return questions


def full_text(answer) -> str:
    parts = [answer.answer_summary]
    parts.extend(claim.claim for claim in answer.claims)
    parts.extend(statement.statement for statement in answer.strong_matches)
    parts.extend(statement.statement for statement in answer.weak_matches)
    parts.extend(item.description for item in answer.contradictory_evidence)
    parts.extend(answer.analogy_limitations)
    parts.extend(answer.mission_applications)
    parts.extend(answer.suggested_experiments)
    parts.extend(answer.uncertainties)
    parts.extend(statement.statement for statement in answer.background)
    parts.extend(answer.guardrail_notices)
    return "\n".join(parts)


def claim_text(answer) -> str:
    return "\n".join(claim.claim for claim in answer.claims)


def evaluate_check(
    spec: dict,
    *,
    answer,
    pack,
    corpus_text: str,
    claims_text: str,
) -> tuple[bool, str]:
    name = spec.get("check")
    value = spec.get("value")
    equals = spec.get("equals")

    if name == "candidate":
        actual = answer.earth_candidate_id
        return actual == equals, f"candidate={actual!r}, expected {equals!r}"

    if name == "insufficient":
        return (
            answer.insufficient_evidence is equals,
            f"insufficient_evidence={answer.insufficient_evidence!r}",
        )

    if name == "min_claims":
        return len(answer.claims) >= value, f"claims={len(answer.claims)}, min {value}"

    if name == "max_claims":
        return len(answer.claims) <= value, f"claims={len(answer.claims)}, max {value}"

    if name == "has_classification":
        found = any(
            equals in {c.value for c in claim.evidence_classifications}
            for claim in answer.claims
        )
        return found, f"classification {equals!r} present={found}"

    if name == "strong_matches_min":
        return len(answer.strong_matches) >= value, (
            f"strong_matches={len(answer.strong_matches)}, min {value}"
        )

    if name == "missing_ids_include":
        present = {item.evidence_id for item in answer.missing_evidence}
        missing = [eid for eid in equals if eid not in present]
        return not missing, f"missing evidence IDs absent from response: {missing}"

    if name == "missing_reasons_present":
        bad = [
            item.evidence_id
            for item in answer.missing_evidence
            if not (item.reason and item.reason.strip())
        ]
        return not bad, f"missing-evidence entries without reason: {bad}"

    if name == "contradictions_min":
        return len(answer.contradictory_evidence) >= value, (
            f"contradictions={len(answer.contradictory_evidence)}, min {value}"
        )

    if name == "contradiction_ids_include":
        present = {
            eid
            for item in answer.contradictory_evidence
            for eid in item.evidence_ids
        }
        missing = [eid for eid in equals if eid not in present]
        return not missing, f"contradiction IDs absent: {missing}"

    if name == "contradiction_unresolved":
        bad = [
            item.contradiction_id
            for item in answer.contradictory_evidence
            if item.resolution_status != "unresolved"
        ]
        return not bad, f"contradictions not preserved as unresolved: {bad}"

    if name == "limitations_contains_any":
        low = "\n".join(answer.analogy_limitations).lower()
        found = [term for term in equals if term.lower() in low]
        return bool(found), f"limitation terms found={found}"

    if name == "uncertainties_contain_any":
        low = "\n".join(answer.uncertainties).lower()
        found = [term for term in equals if term.lower() in low]
        return bool(found), f"uncertainty terms found={found}"

    if name == "text_contains_any":
        low = full_text(answer).lower()
        found = [term for term in equals if term.lower() in low]
        return bool(found), f"text terms found={found}"

    if name == "answer_contains":
        found = equals in answer.answer_summary
        return found, f"answer_summary contains {equals!r}={found}"

    if name == "answer_forbid_any":
        low = full_text(answer).lower()
        hits = [term for term in equals if term.lower() in low]
        return not hits, f"forbidden text present: {hits}"

    if name == "claim_text_forbid_any":
        low = claims_text.lower()
        hits = [term for term in equals if term.lower() in low]
        return not hits, f"forbidden claim text present: {hits}"

    if name == "claim_contains_any":
        low = claims_text.lower()
        found = [term for term in equals if term.lower() in low]
        return bool(found), f"claim terms found={found}"

    if name == "claims_forbid_any":
        low = claims_text.lower()
        hits = [term for term in equals if term.lower() in low]
        return not hits, f"forbidden claim text present: {hits}"

    if name == "score_text":
        metric = spec["metric"]
        values = [
            item.value_text
            for item in answer.supplied_scores
            if item.metric == metric
        ]
        return equals in values, f"{metric} value_text={values!r}, expected {equals!r}"

    if name == "score_notice_present":
        present = bool(answer.score_integrity_notice)
        return present is equals, f"score_integrity_notice present={present}"

    if name == "guardrail_notice_contains":
        low = "\n".join(answer.guardrail_notices).lower()
        found = equals.lower() in low
        return found, f"guardrail notices={answer.guardrail_notices!r}"

    if name == "source_present":
        found = any(source.source_id == equals for source in answer.sources)
        return found, f"source {equals!r} present={found}"

    if name == "sources_have_urls":
        found = any(source.url for source in answer.sources)
        return found is equals, f"any source URL present={found}"

    if name == "all_sources_stored":
        allowed = pack.allowed_source_ids
        bad = [s.source_id for s in answer.sources if s.source_id not in allowed]
        return not bad, f"unstored source IDs: {bad}"

    if name == "source_metadata_nonempty":
        matches = [s for s in answer.sources if s.source_id == equals]
        good = bool(matches) and all(s.title for s in matches)
        return good, f"stored metadata for {equals!r} present={good}"

    if name == "background_min":
        return len(answer.background) >= value, (
            f"background={len(answer.background)}, min {value}"
        )

    if name == "background_sources_stored":
        allowed = pack.allowed_source_ids
        bad = [
            sid
            for item in answer.background
            for sid in item.source_ids
            if sid not in allowed
        ]
        return not bad, f"background source IDs not stored: {bad}"

    if name == "provenance":
        actual = answer.data_provenance_mode.value
        return actual == equals, f"data_provenance_mode={actual!r}, expected {equals!r}"

    if name == "generation_mode_valid":
        allowed = {"model", "evidence_only_fallback"}
        actual = answer.generation_mode.value
        return actual in allowed, f"generation_mode={actual!r}"

    if name == "target_planet":
        actual = pack.target.planet if pack.target else None
        return actual == equals, f"target planet={actual!r}, expected {equals!r}"

    if name == "evidence_ids_valid":
        actual = answer.validation.evidence_ids_valid
        return actual is equals, f"evidence_ids_valid={actual!r}"

    if name == "claim_ids_subset":
        allowed = pack.allowed_evidence_ids
        bad = [
            eid
            for claim in answer.claims
            for eid in claim.evidence_ids
            if eid not in allowed
        ]
        return not bad, f"claim evidence IDs not in pack: {bad}"

    if name == "match_ids_subset":
        allowed = pack.allowed_evidence_ids
        bad = [
            eid
            for statement in answer.strong_matches + answer.weak_matches
            for eid in statement.evidence_ids
            if eid not in allowed
        ]
        return not bad, f"match evidence IDs not in pack: {bad}"

    if name == "zero_evidence_present":
        found = any(
            equals in claim.evidence_ids and "0.0" in claim.claim
            for claim in answer.claims
        )
        return found, f"claim for {equals!r} quoting 0.0 present={found}"

    if name == "no_missing_as_zero":
        missing_ids = {item.evidence_id for item in answer.missing_evidence}
        offending = [
            claim.claim
            for claim in answer.claims
            if missing_ids.intersection(claim.evidence_ids)
            and "zero" in claim.claim.lower()
        ]
        return not offending, f"claims turning unavailable evidence into zero: {offending}"

    if name == "selftest_scores_unchanged":
        actual = [score.model_dump(mode="json") for score in answer.supplied_scores]
        expected = [score.model_dump(mode="json") for score in pack.scores]
        return actual == expected, "supplied scores differ from the evidence pack"

    if name == "no_unlabelled_experiments":
        bad = [
            item
            for item in answer.suggested_experiments
            if not item.lower().startswith("proposed")
        ]
        return not bad, f"unlabelled suggested experiments: {bad}"

    if name == "no_overclaim_flags":
        flags = answer.validation.overclaim_flags
        return not flags, f"overclaim flags={flags}"

    if name == "overclaim_absent":
        flags = answer.validation.overclaim_flags
        return equals not in flags, f"overclaim flags={flags}"

    if name == "numeric_claims_valid":
        actual = answer.validation.numeric_claims_valid
        return actual is equals, f"numeric_claims_valid={actual!r}"

    if name == "sources_valid":
        actual = answer.validation.sources_valid
        return actual is equals, f"sources_valid={actual!r}"

    if name == "documents_retrieved_min":
        count = len(pack.documents)
        return count >= value, f"documents retrieved={count}, min {value}"

    if name == "pack_security_flags_min":
        count = len(pack.security_flags)
        return count >= value, f"pack security_flags={pack.security_flags}"

    raise ValueError(f"unknown check: {name}")


def invariant_failures(answer, pack) -> list[str]:
    failures: list[str] = []
    allowed_sources = pack.allowed_source_ids
    allowed_evidence = pack.allowed_evidence_ids

    if [s.model_dump(mode="json") for s in answer.supplied_scores] != [
        s.model_dump(mode="json") for s in pack.scores
    ]:
        failures.append("supplied_scores are not identical to the evidence pack")

    for claim in answer.claims:
        bad = [eid for eid in claim.evidence_ids if eid not in allowed_evidence]
        if bad:
            failures.append(f"claim references unknown evidence IDs: {bad}")

    bad_sources = [s.source_id for s in answer.sources if s.source_id not in allowed_sources]
    if bad_sources:
        failures.append(f"response cites unknown source IDs: {bad_sources}")

    if [i.evidence_id for i in answer.missing_evidence] != [
        i.evidence_id for i in pack.missing_evidence
    ]:
        failures.append("missing-evidence list does not match the pack")

    if [c.contradiction_id for c in answer.contradictory_evidence] != [
        c.contradiction_id for c in pack.contradictions
    ]:
        failures.append("contradiction list does not match the pack")

    if answer.data_provenance_mode != pack.data_provenance_mode:
        failures.append("data provenance mode does not match the pack")

    if answer.validation.evidence_ids_valid and answer.validation.rejected_evidence_ids:
        failures.append("validation reports valid IDs while also rejecting IDs")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions",
        type=Path,
        default=ROOT / "evaluation" / "questions.jsonl",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=ROOT / "evaluation" / "results",
    )
    parser.add_argument(
        "--use-model",
        action="store_true",
        help="Evaluate real local Ollama inference instead of the fallback.",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:11434",
        help="Ollama base URL used with --use-model.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the configured Ollama model name.",
    )
    args = parser.parse_args(argv)

    questions = load_questions(args.questions)
    if len(questions) < 20:
        raise SystemExit(f"expected at least 20 evaluation questions, found {len(questions)}")

    workdir = Path(tempfile.mkdtemp(prefix="assistant-eval-"))
    base_url = args.ollama_url if args.use_model else "http://127.0.0.1:9"
    settings = Settings(
        db_path=workdir / "assistant-eval.db",
        corpus_dir=ROOT / "corpus",
        fixture_records_path=ROOT / "fixtures" / "test_only_platform_records.json",
        structured_backend="fixture",
        allow_fixture_data=True,
        auto_ingest_corpus=True,
        ollama_base_url=base_url,
        ollama_timeout_s=900.0 if args.use_model else 0.5,
        ollama_health_timeout_s=3.0 if args.use_model else 0.2,
        **({"ollama_model": args.model} if args.model else {}),
    )

    service = AssistantService(settings)
    try:
        if args.use_model:
            health = service.generator.health()
            if not health.get("available"):
                raise SystemExit(
                    "refusing to evaluate: --use-model requested but Ollama is not "
                    f"available at {base_url}: {health.get('error')}"
                )
            print(
                f"model mode: model={health.get('configured_model')} "
                f"present={health.get('configured_model_present')}"
            )
        else:
            print("model mode: deterministic evidence-only fallback (no inference)")

        results = []
        for question in questions:
            fixture = question.get("ingest_fixture")
            if fixture:
                service.store.ingest_path(ROOT / fixture, ROOT / fixture)

            request = ChatRequest(
                question=question["question"],
                candidate_id=question.get("candidate_id"),
                target=question.get("target"),
                mission_profile=question.get("mission_profile"),
                include_background=question.get("include_background", True),
                max_sources=question.get("max_sources", 5),
            )
            pack = service.assembler.assemble(
                question=request.question,
                candidate_id=request.candidate_id,
                target=request.target,
                mission_profile=request.mission_profile,
                include_background=request.include_background,
                max_sources=request.max_sources,
            )
            answer = service.chat(request)

            checks = []
            for spec in question.get("checks", []):
                try:
                    passed, detail = evaluate_check(
                        spec,
                        answer=answer,
                        pack=pack,
                        corpus_text=full_text(answer),
                        claims_text=claim_text(answer),
                    )
                except Exception as exc:  # noqa: BLE001 - record, do not abort the suite
                    passed, detail = False, f"check raised {type(exc).__name__}: {exc}"
                checks.append(
                    {
                        "check": spec.get("check"),
                        "spec": spec,
                        "passed": passed,
                        "detail": detail,
                    }
                )

            invariants = invariant_failures(answer, pack)
            failed = [c for c in checks if not c["passed"]]
            passed = not failed and not invariants
            results.append(
                {
                    "id": question["id"],
                    "category": question["category"],
                    "question": question["question"],
                    "expected_behavior": question.get("expected_behavior"),
                    "passed": passed,
                    "failed_checks": failed,
                    "invariant_failures": invariants,
                    "generation_mode": answer.generation_mode.value,
                    "insufficient_evidence": answer.insufficient_evidence,
                    "candidate": answer.earth_candidate_id,
                    "provenance": answer.data_provenance_mode.value,
                    "validation": answer.validation.model_dump(mode="json"),
                    "answer_summary": answer.answer_summary,
                }
            )
            print(
                f"{question['id']} {'PASS' if passed else 'FAIL'} "
                f"[{question['category']}] mode={answer.generation_mode.value}"
            )
            if not passed:
                for item in failed:
                    print(f"    - {item['check']}: {item['detail']}")
                for item in invariants:
                    print(f"    - invariant: {item}")

        passed_count = sum(1 for item in results if item["passed"])
        total = len(results)
        report = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "mode": "model" if args.use_model else "evidence_only_fallback",
            "ollama_url": base_url if args.use_model else None,
            "model_health": service.generator.health() if args.use_model else None,
            "questions_total": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "results": results,
        }

        args.results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = args.results_dir / f"eval-{stamp}-{report['mode']}.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        (args.results_dir / "latest.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

        print(f"\n{passed_count}/{total} questions passed")
        print(f"results saved to {out}")
        return 0 if passed_count == total else 1
    finally:
        service.store.close()


if __name__ == "__main__":
    raise SystemExit(main())
