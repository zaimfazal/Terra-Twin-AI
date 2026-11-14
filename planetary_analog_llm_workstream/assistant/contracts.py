"""Typed contracts shared by retrieval, evidence assembly, generation and API.

These models mirror the platform's core data entities described in PRD
Section 23.3. They are read-only from the assistant's point of view. Any
field whose value is not present in a trusted platform record must be
``None``; ``0`` is a real supplied value and must never be used for missing
data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceClassification(str, Enum):
    """PRD Section 13 / Table 5 evidence classes."""

    DIRECTLY_OBSERVED = "directly_observed"
    DERIVED = "derived"
    PROXY_BASED = "proxy_based"
    LITERATURE_SUPPORTED = "literature_supported"
    UNAVAILABLE = "unavailable"


class DataProvenanceMode(str, Enum):
    PLATFORM = "platform"
    FIXTURE_TEST_ONLY = "fixture_test_only"
    NONE = "none"


class GenerationMode(str, Enum):
    MODEL = "model"
    EVIDENCE_ONLY_FALLBACK = "evidence_only_fallback"


class Coordinates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float | None = None
    longitude: float | None = None
    crs: str | None = None


class TargetRecord(BaseModel):
    """Planetary reference target. Supplied by the platform catalogue."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    name: str
    planet: Literal["Moon", "Mars", "Earth", "other"]
    reference_type: str | None = None
    mission_profiles: list[str] = Field(default_factory=list)
    is_fixture: bool = False


class DatasetProvenance(BaseModel):
    """Dataset/source metadata required by PRD Section 15.1.

    Unavailable values remain ``None``. No field is inferred from a filename
    or URL by the assistant.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str
    dataset_name: str
    organization: str | None = None
    instrument_or_mission: str | None = None
    version: str | None = None
    spatial_resolution: str | None = None
    temporal_resolution: str | None = None
    acquisition_date: str | None = None
    crs: str | None = None
    units: str | None = None
    processing_methodology: str | None = None
    known_limitations: str | None = None
    url: str | None = None
    doi: str | None = None
    licence: str | None = None
    is_fixture: bool = False


class SuppliedScore(BaseModel):
    """A score-like value exactly as supplied by a trusted record.

    ``value_text`` preserves the supplied representation. The assistant must
    never recalculate, round, re-rank or otherwise modify ``value``.
    """

    model_config = ConfigDict(extra="forbid")

    metric: Literal[
        "overall_similarity",
        "dimension_similarity",
        "data_coverage",
        "data_confidence",
        "other_supplied_metric",
    ]
    dimension: str | None = None
    value: float | None = None
    value_text: str | None = None
    scale: str | None = None
    source_record_id: str | None = None
    is_missing: bool = False
    missing_reason: str | None = None


class EvidenceItem(BaseModel):
    """One feature measurement / derived result / proxy / missing entry."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    candidate_id: str | None = None
    target_id: str | None = None
    mission_profile: str | None = None
    dimension: str
    feature: str
    value: float | str | None = None
    value_text: str | None = None
    unit: str | None = None
    evidence_classification: EvidenceClassification
    dataset_source_id: str | None = None
    source_record_id: str | None = None
    observed_at: str | None = None
    spatial_resolution: str | None = None
    temporal_coverage: str | None = None
    method: str | None = None
    note: str | None = None
    missing_reason: str | None = None
    contradiction_group: str | None = None
    related_evidence_ids: list[str] = Field(default_factory=list)
    is_fixture: bool = False

    @property
    def is_missing(self) -> bool:
        return self.evidence_classification == EvidenceClassification.UNAVAILABLE or (
            self.value is None and self.value_text is None
        )


class ContradictionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contradiction_id: str
    topic: str
    evidence_ids: list[str]
    description: str
    documented_differences: list[str] = Field(default_factory=list)
    resolution_status: Literal["unresolved", "resolved", "unknown"] = "unresolved"


class CandidateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    name: str | None = None
    planet: Literal["Earth"] = "Earth"
    region_name: str | None = None
    coordinates: Coordinates | None = None
    area_km2: float | None = None
    target_id: str | None = None
    mission_profiles: list[str] = Field(default_factory=list)
    eligibility_stage: str | None = None
    is_fixture: bool = False


class ReportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    candidate_id: str
    target_id: str | None = None
    target_name: str | None = None
    mission_profile: str | None = None
    comparison_scale: str | None = None
    generated_at: str | None = None
    overall_similarity: SuppliedScore | None = None
    dimension_scores: list[SuppliedScore] = Field(default_factory=list)
    data_coverage: SuppliedScore | None = None
    data_confidence: SuppliedScore | None = None
    strong_match_evidence_ids: list[str] = Field(default_factory=list)
    weak_match_evidence_ids: list[str] = Field(default_factory=list)
    contradiction_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_ids: list[str] = Field(default_factory=list)
    dataset_source_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance_notes: list[str] = Field(default_factory=list)
    is_fixture: bool = False


class SourceMetadata(BaseModel):
    """A document/source record from the assistant corpus.

    ``untrusted`` is always true for retrieved document text. Metadata is
    stored (not model-generated) and can be cited by source_id.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    organization: str | None = None
    url: str | None = None
    doi: str | None = None
    publication_date: str | None = None
    licence: str | None = None
    content_hash: str
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    document_type: str
    page: int | None = None
    section: str | None = None
    status: Literal["processed", "partial", "failed", "quarantined"] = "processed"
    untrusted: bool = True
    security_flags: list[str] = Field(default_factory=list)
    is_fixture: bool = False


class RetrievedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    organization: str | None = None
    url: str | None = None
    doi: str | None = None
    publication_date: str | None = None
    licence: str | None = None
    page: int | None = None
    section: str | None = None
    snippet: str
    rank: float | None = None
    untrusted: bool = True
    security_flags: list[str] = Field(default_factory=list)
    is_fixture: bool = False


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    organization: str | None = None
    url: str | None = None
    doi: str | None = None
    publication_date: str | None = None
    licence: str | None = None
    page: int | None = None
    section: str | None = None
    text: str
    content_hash: str
    document_type: str
    security_flags: list[str] = Field(default_factory=list)
    is_fixture: bool = False


class EvidencePack(BaseModel):
    """Typed, self-contained evidence bundle sent to the model."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    question: str
    data_provenance_mode: DataProvenanceMode
    candidate: CandidateRecord | None = None
    target: TargetRecord | None = None
    mission_profile: str | None = None
    report: ReportRecord | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    missing_evidence: list[EvidenceItem] = Field(default_factory=list)
    contradictions: list[ContradictionRecord] = Field(default_factory=list)
    scores: list[SuppliedScore] = Field(default_factory=list)
    dataset_sources: list[DatasetProvenance] = Field(default_factory=list)
    documents: list[RetrievedDocument] = Field(default_factory=list)
    document_sources: list[SourceMetadata] = Field(default_factory=list)
    engine_strong_match_evidence_ids: list[str] = Field(default_factory=list)
    engine_weak_match_evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    security_flags: list[str] = Field(default_factory=list)
    lookup_notes: list[str] = Field(default_factory=list)

    @property
    def allowed_evidence_ids(self) -> set[str]:
        return {item.evidence_id for item in self.evidence} | {
            item.evidence_id for item in self.missing_evidence
        }

    @property
    def allowed_source_ids(self) -> set[str]:
        return {s.source_id for s in self.dataset_sources} | {
            s.source_id for s in self.document_sources
        }


# ---------------------------------------------------------------------------
# Model draft: the *only* fields the LLM may propose. IDs, classifications
# and scores are assigned/verified server-side.
# ---------------------------------------------------------------------------


class ModelClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence_classification: EvidenceClassification | None = None
    is_background: bool = False


class ModelMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    dimension: str | None = None


class ModelDraft(BaseModel):
    """Schema requested from the local model. No score fields are allowed."""

    model_config = ConfigDict(extra="forbid")

    answer_summary: str
    claims: list[ModelClaim] = Field(default_factory=list)
    planetary_target: str | None = None
    earth_candidate_id: str | None = None
    strong_matches: list[ModelMatch] = Field(default_factory=list)
    weak_matches: list[ModelMatch] = Field(default_factory=list)
    contradictory_evidence: list[ModelMatch] = Field(default_factory=list)
    missing_evidence: list[ModelMatch] = Field(default_factory=list)
    analogy_limitations: list[str] = Field(default_factory=list)
    mission_applications: list[str] = Field(default_factory=list)
    suggested_experiments: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False


# ---------------------------------------------------------------------------
# Validated response contract
# ---------------------------------------------------------------------------


class ValidationStatus(str, Enum):
    VALIDATED = "validated"
    FLAGGED_NUMERIC_MISMATCH = "flagged_numeric_mismatch"
    FLAGGED_OVERCLAIM = "flagged_overclaim"
    FLAGGED_UNTRUSTED_INSTRUCTION = "flagged_untrusted_instruction"
    REJECTED_INVALID_EVIDENCE = "rejected_invalid_evidence"
    REJECTED_INVALID_SOURCE = "rejected_invalid_source"


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_classification: EvidenceClassification | None = None
    evidence_classifications: list[EvidenceClassification] = Field(default_factory=list)
    is_background: bool = False
    validation_status: ValidationStatus = ValidationStatus.VALIDATED
    validation_notes: list[str] = Field(default_factory=list)


class MatchStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    dimension: str | None = None
    validation_status: ValidationStatus = ValidationStatus.VALIDATED
    validation_notes: list[str] = Field(default_factory=list)


class MissingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    dimension: str
    feature: str
    reason: str | None = None
    evidence_classification: EvidenceClassification = EvidenceClassification.UNAVAILABLE


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contradiction_id: str
    topic: str
    evidence_ids: list[str]
    description: str
    documented_differences: list[str] = Field(default_factory=list)
    resolution_status: Literal["unresolved", "resolved", "unknown"] = "unresolved"


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    organization: str | None = None
    url: str | None = None
    doi: str | None = None
    page: int | None = None
    section: str | None = None
    licence: str | None = None
    source_kind: Literal["dataset", "document"]
    is_fixture: bool = False


class BackgroundStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    source_ids: list[str] = Field(default_factory=list)
    label: Literal["background"] = "background"


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_valid: bool
    evidence_ids_valid: bool
    sources_valid: bool
    numeric_claims_valid: bool
    score_immutability_valid: bool = True
    rejected_claim_count: int = 0
    rejected_evidence_ids: list[str] = Field(default_factory=list)
    rejected_source_ids: list[str] = Field(default_factory=list)
    numeric_mismatches: list[str] = Field(default_factory=list)
    overclaim_flags: list[str] = Field(default_factory=list)
    untrusted_instruction_flags: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AssistantAnswer(BaseModel):
    """Public response contract (PRD Section 18 + workstream prompt)."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer_summary: str
    planetary_target: str | None = None
    earth_candidate_id: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    strong_matches: list[MatchStatement] = Field(default_factory=list)
    weak_matches: list[MatchStatement] = Field(default_factory=list)
    contradictory_evidence: list[Contradiction] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    analogy_limitations: list[str] = Field(default_factory=list)
    mission_applications: list[str] = Field(default_factory=list)
    suggested_experiments: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    insufficient_evidence: bool = False
    background: list[BackgroundStatement] = Field(default_factory=list)
    supplied_scores: list[SuppliedScore] = Field(default_factory=list)
    data_provenance_mode: DataProvenanceMode = DataProvenanceMode.NONE
    generation_mode: GenerationMode = GenerationMode.EVIDENCE_ONLY_FALLBACK
    validation: ValidationReport
    score_integrity_notice: str | None = None
    guardrail_notices: list[str] = Field(default_factory=list)
    response_id: str = ""
    pack_id: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    disclaimer: str = (
        "The assistant explains supplied platform records. It does not create, "
        "recalculate or rank scientific scores. Similarity, data coverage and data "
        "confidence are separate metrics."
    )


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    candidate_id: str | None = None
    target: str | None = None
    mission_profile: str | None = None
    conversation_context: list[str] = Field(default_factory=list)
    include_background: bool = True
    max_sources: int = Field(default=5, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()


class ExplainReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str | None = None
    report: ReportRecord | None = None
    question: str | None = Field(default=None, max_length=4000)
    include_background: bool = True

    @field_validator("report")
    @classmethod
    def _fixture_report_must_be_marked(cls, value: ReportRecord | None) -> ReportRecord | None:
        if value is not None and not value.is_fixture:
            # A caller-supplied report cannot be authenticated as a platform
            # record by this service, so it is accepted only as an explicitly
            # marked test fixture. Real reports must be looked up by ID.
            raise ValueError(
                "Caller-supplied reports are accepted only when is_fixture=true. "
                "Use report_id for platform records."
            )
        return value


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str | None = None
    question_hash: str | None = None
    useful: bool
    factual: bool | None = None
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackRecord(FeedbackRequest):
    feedback_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: Literal["ok"] = "ok"
    retrieval: dict[str, Any]
    inference: dict[str, Any]
    model: dict[str, Any]
    data_mode: DataProvenanceMode
    fts5_available: bool
    message: str | None = None
