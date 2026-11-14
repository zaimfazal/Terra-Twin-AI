"""Read-only structured platform adapter contract.

No adapter in this package can write scientific records. Score, coverage and
confidence values are returned verbatim from stored records.
"""

from __future__ import annotations

from typing import Protocol

from assistant.contracts import (
    CandidateRecord,
    ContradictionRecord,
    DatasetProvenance,
    EvidenceItem,
    ReportRecord,
    TargetRecord,
)


class StructuredPlatformAdapter(Protocol):
    """Contract expected from the platform/backend owner (see API_CONTRACT.md)."""

    data_provenance_mode: str
    backend_name: str

    def get_candidate(self, candidate_id: str) -> CandidateRecord | None: ...

    def list_candidates(self, limit: int = 50) -> list[CandidateRecord]: ...

    def get_target(self, target_id_or_name: str) -> TargetRecord | None: ...

    def get_report(self, report_id: str) -> ReportRecord | None: ...

    def get_reports_for_candidate(self, candidate_id: str) -> list[ReportRecord]: ...

    def get_evidence_for_candidate(self, candidate_id: str) -> list[EvidenceItem]: ...

    def get_evidence(self, evidence_ids: list[str]) -> list[EvidenceItem]: ...

    def get_contradictions(self, candidate_id: str) -> list[ContradictionRecord]: ...

    def get_dataset_sources(self, source_ids: list[str]) -> list[DatasetProvenance]: ...

    def health(self) -> dict: ...


class AdapterUnavailable(RuntimeError):
    """Raised when a configured backend cannot be reached or is not configured."""
