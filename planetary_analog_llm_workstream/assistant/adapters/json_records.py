"""Read-only JSON record adapter.

Supports two explicitly different payloads:

* ``_fixture_only: true`` - synthetic development/evaluation records. Every
  record exposed to the caller is marked ``is_fixture`` and the service labels
  responses ``fixture_test_only``. This is **not** platform output.
* a platform-owned export without that marker - treated as platform data.

The export format is a proposed contract because the backend does not yet
exist in this repository (see docs/llm/API_CONTRACT.md).
"""

from __future__ import annotations

import json
from pathlib import Path

from assistant.adapters.base import AdapterUnavailable
from assistant.contracts import (
    CandidateRecord,
    ContradictionRecord,
    DatasetProvenance,
    EvidenceItem,
    ReportRecord,
    TargetRecord,
)


class JsonRecordAdapter:
    def __init__(self, path: str | Path, *, allow_fixture: bool = True):
        self.path = Path(path)
        if not self.path.exists():
            raise AdapterUnavailable(f"structured records file not found: {self.path}")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.fixture_only = bool(payload.get("_fixture_only", False))
        self.fixture_warning = payload.get("_warning")
        if self.fixture_only and not allow_fixture:
            raise AdapterUnavailable(
                "fixture records are disabled (ASSISTANT_ALLOW_FIXTURE_DATA=false)"
            )

        self.backend_name = "json_records"
        self.data_provenance_mode = "fixture_test_only" if self.fixture_only else "platform"
        self.candidates = [
            CandidateRecord.model_validate(x) for x in payload.get("candidates", [])
        ]
        self.targets = [TargetRecord.model_validate(x) for x in payload.get("targets", [])]
        self.reports = [ReportRecord.model_validate(x) for x in payload.get("reports", [])]
        self.evidence = [EvidenceItem.model_validate(x) for x in payload.get("evidence", [])]
        self.contradictions = [
            ContradictionRecord.model_validate(x) for x in payload.get("contradictions", [])
        ]
        self.dataset_sources = [
            DatasetProvenance.model_validate(x) for x in payload.get("dataset_sources", [])
        ]

        # Fixture payloads must mark every record, so a fixture value can never
        # be silently presented as a platform record.
        if self.fixture_only:
            for collection in (
                self.candidates,
                self.targets,
                self.reports,
                self.evidence,
                self.dataset_sources,
            ):
                for item in collection:
                    object.__setattr__(item, "is_fixture", True)

        self._candidates = {c.candidate_id: c for c in self.candidates}
        self._targets = {t.target_id: t for t in self.targets}
        self._reports = {r.report_id: r for r in self.reports}
        self._evidence = {e.evidence_id: e for e in self.evidence}
        self._dataset_sources = {s.source_id: s for s in self.dataset_sources}

    def get_candidate(self, candidate_id: str) -> CandidateRecord | None:
        return self._candidates.get(candidate_id)

    def list_candidates(self, limit: int = 50) -> list[CandidateRecord]:
        return self.candidates[: max(0, limit)]

    def get_target(self, target_id_or_name: str) -> TargetRecord | None:
        if target_id_or_name in self._targets:
            return self._targets[target_id_or_name]
        needle = target_id_or_name.strip().casefold()
        for target in self.targets:
            if target.name.casefold() == needle or target.target_id.casefold() == needle:
                return target
        return None

    def get_report(self, report_id: str) -> ReportRecord | None:
        return self._reports.get(report_id)

    def get_reports_for_candidate(self, candidate_id: str) -> list[ReportRecord]:
        return [r for r in self.reports if r.candidate_id == candidate_id]

    def get_evidence_for_candidate(self, candidate_id: str) -> list[EvidenceItem]:
        return [e for e in self.evidence if e.candidate_id == candidate_id]

    def get_evidence(self, evidence_ids: list[str]) -> list[EvidenceItem]:
        seen: set[str] = set()
        result: list[EvidenceItem] = []
        for evidence_id in evidence_ids:
            item = self._evidence.get(evidence_id)
            if item and item.evidence_id not in seen:
                seen.add(item.evidence_id)
                result.append(item)
        return result

    def get_contradictions(self, candidate_id: str) -> list[ContradictionRecord]:
        allowed = {
            e.evidence_id for e in self.evidence if e.candidate_id == candidate_id
        }
        return [
            c
            for c in self.contradictions
            if set(c.evidence_ids).issubset(allowed) and allowed
        ]

    def get_dataset_sources(self, source_ids: list[str]) -> list[DatasetProvenance]:
        return [
            self._dataset_sources[sid]
            for sid in source_ids
            if sid in self._dataset_sources
        ]

    def health(self) -> dict:
        return {
            "backend": self.backend_name,
            "data_provenance_mode": self.data_provenance_mode,
            "candidates": len(self.candidates),
            "reports": len(self.reports),
            "evidence_items": len(self.evidence),
            "fixture_only": self.fixture_only,
            "fixture_warning": self.fixture_warning,
        }
