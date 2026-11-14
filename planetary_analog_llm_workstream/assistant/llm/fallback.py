"""Deterministic evidence-only fallback.

Used when local inference is unavailable, returns malformed output, or fails
validation. It never generates scientific interpretation, proposals or new
numbers. It reports stored values verbatim and clearly labels the state.
"""

from __future__ import annotations

from assistant.contracts import (
    AssistantAnswer,
    BackgroundStatement,
    Claim,
    Contradiction,
    DataProvenanceMode,
    EvidencePack,
    GenerationMode,
    MissingEvidence,
    SourceReference,
    ValidationReport,
    ValidationStatus,
)
from assistant.evidence.validation import (
    INSUFFICIENT_EVIDENCE_SENTENCE,
    engine_label_matches,
    planetary_limitations,
)


def _display_value(item) -> str:
    value = item.value_text if item.value_text is not None else item.value
    if item.unit:
        return f"{value} {item.unit}"
    return str(value)


def build_evidence_only_answer(
    pack: EvidencePack,
    *,
    reason: str,
    schema_valid: bool = True,
    error: str | None = None,
    score_notice: str | None = None,
) -> AssistantAnswer:
    candidate = pack.candidate
    report = pack.report
    claims: list[Claim] = []
    for item in pack.evidence:
        if item.is_missing:
            continue
        claims.append(
            Claim(
                claim=(
                    f"Stored evidence {item.evidence_id} records {item.feature} = "
                    f"{_display_value(item)} "
                    f"(evidence classification: {item.evidence_classification.value})."
                ),
                evidence_ids=[item.evidence_id],
                evidence_classification=item.evidence_classification,
                evidence_classifications=[item.evidence_classification],
                validation_status=ValidationStatus.VALIDATED,
                validation_notes=["quoted verbatim from the structured evidence pack"],
            )
        )

    missing = [
        MissingEvidence(
            evidence_id=item.evidence_id,
            dimension=item.dimension,
            feature=item.feature,
            reason=item.missing_reason or item.note,
        )
        for item in pack.missing_evidence
    ]

    contradictions = [
        Contradiction(
            contradiction_id=c.contradiction_id,
            topic=c.topic,
            evidence_ids=c.evidence_ids,
            description=c.description,
            documented_differences=c.documented_differences,
            resolution_status=c.resolution_status,
        )
        for c in pack.contradictions
    ]

    sources: list[SourceReference] = []
    seen: set[str] = set()
    for source in pack.dataset_sources:
        if source.source_id in seen:
            continue
        seen.add(source.source_id)
        sources.append(
            SourceReference(
                source_id=source.source_id,
                title=source.dataset_name,
                organization=source.organization,
                url=source.url,
                doi=source.doi,
                licence=source.licence,
                source_kind="dataset",
                is_fixture=source.is_fixture,
            )
        )
    for source in pack.document_sources:
        if source.source_id in seen:
            continue
        seen.add(source.source_id)
        sources.append(
            SourceReference(
                source_id=source.source_id,
                title=source.title,
                organization=source.organization,
                url=source.url,
                doi=source.doi,
                page=source.page,
                section=source.section,
                licence=source.licence,
                source_kind="document",
                is_fixture=source.is_fixture,
            )
        )

    background = [
        BackgroundStatement(
            statement=(
                f"Retrieved background document (not candidate-specific evidence): "
                f"{source.title}."
            ),
            source_ids=[source.source_id],
        )
        for source in pack.document_sources
    ]

    insufficient = False
    parts: list[str] = []
    if candidate is None:
        requested = bool(pack.lookup_notes)
        if requested:
            insufficient = True
            parts.append(INSUFFICIENT_EVIDENCE_SENTENCE)
        parts.append(
            "No stored candidate record was supplied in this evidence pack, so the "
            "available evidence does not establish a candidate-specific analogy."
        )
    else:
        parts.append(
            f"Evidence-only summary for {candidate.candidate_id}"
            + (f" ({candidate.name})" if candidate.name else "")
            + "."
        )
        if report is not None:
            if report.overall_similarity is not None:
                score = report.overall_similarity
                text = score.value_text if score.value_text is not None else score.value
                parts.append(f"Supplied overall similarity: {text} (unchanged).")
            if report.data_coverage is not None:
                cov = report.data_coverage
                text = cov.value_text if cov.value_text is not None else cov.value
                parts.append(f"Supplied data coverage: {text} (unchanged).")
            if report.data_confidence is not None:
                conf = report.data_confidence
                text = conf.value_text if conf.value_text is not None else conf.value
                parts.append(f"Supplied data confidence: {text} (unchanged).")
        parts.append(
            f"{len(pack.evidence)} available evidence item(s); "
            f"{len(pack.missing_evidence)} unavailable field(s); "
            f"{len(pack.contradictions)} stored contradiction(s)."
        )
        if not claims:
            insufficient = True
            parts.append(INSUFFICIENT_EVIDENCE_SENTENCE)

    parts.append(
        "AI interpretation was not generated. This is a retrieval-only fallback, not "
        "a scientific conclusion."
    )
    if reason:
        parts.append(f"Reason: {reason}")

    summary = " ".join(parts)
    if pack.data_provenance_mode == DataProvenanceMode.FIXTURE_TEST_ONLY:
        summary = "TEST-ONLY FIXTURE DATA: these synthetic values are not platform measurements. " + summary

    uncertainties = list(pack.lookup_notes)
    uncertainties.append(
        "Local model inference is unavailable or its output was rejected; no "
        "interpretation, experiment design or mission recommendation was generated."
    )
    if pack.data_provenance_mode == DataProvenanceMode.FIXTURE_TEST_ONLY:
        uncertainties.insert(
            0,
            "All structured values in this response come from synthetic test-only "
            "fixtures, not the scientific engine.",
        )

    report_obj = ValidationReport(
        schema_valid=schema_valid,
        evidence_ids_valid=True,
        sources_valid=True,
        numeric_claims_valid=True,
        score_immutability_valid=True,
        rejected_claim_count=0,
        errors=[error] if error else [],
    )

    return AssistantAnswer(
        question=pack.question,
        answer_summary=summary,
        planetary_target=pack.target.name if pack.target else None,
        earth_candidate_id=candidate.candidate_id if candidate else None,
        claims=claims,
        strong_matches=engine_label_matches(pack, "strong"),
        weak_matches=engine_label_matches(pack, "weak"),
        contradictory_evidence=contradictions,
        missing_evidence=missing,
        analogy_limitations=list(
            dict.fromkeys(planetary_limitations(pack) + pack.limitations)
        ),
        mission_applications=[],
        suggested_experiments=[],
        uncertainties=list(dict.fromkeys(uncertainties)),
        sources=sources,
        insufficient_evidence=insufficient,
        background=background,
        supplied_scores=list(pack.scores),
        data_provenance_mode=pack.data_provenance_mode,
        generation_mode=GenerationMode.EVIDENCE_ONLY_FALLBACK,
        validation=report_obj,
        score_integrity_notice=score_notice,
    )
