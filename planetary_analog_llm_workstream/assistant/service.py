"""Assistant service: wiring, use cases and graceful degradation.

Model, retrieval, evidence assembly, validation and routing remain separate
modules. This service composes them; it does not implement science.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from assistant.adapters.base import AdapterUnavailable
from assistant.adapters.json_records import JsonRecordAdapter
from assistant.config import Settings
from assistant.config import settings as default_settings
from assistant.contracts import (
    AssistantAnswer,
    ChatRequest,
    DataProvenanceMode,
    ExplainReportRequest,
    FeedbackRecord,
    HealthResponse,
    ReportRecord,
)
from assistant.evidence.assembler import EvidenceAssembler
from assistant.evidence.validation import (
    detect_citation_fabrication,
    detect_score_manipulation,
)
from assistant.images.contracts import ImageSearchRequest, ImageSearchResponse
from assistant.images.orchestrator import ImageRetrievalService
from assistant.ingestion.store import DocumentStore
from assistant.llm.generation import GroundedGenerator
from assistant.llm.ollama import ollama_health_payload
from assistant.llm.prompt import PROMPT_VERSION
from assistant.places.contracts import PlaceSearchRequest, PlaceSearchResponse
from assistant.places.service import PlaceSearchService


class AssistantService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: DocumentStore | None = None,
        adapter=None,
        generator: GroundedGenerator | None = None,
        image_service: ImageRetrievalService | None = None,
    ):
        self.settings = settings or default_settings
        if not self.settings.allow_fixture_data and self.settings.structured_backend == "fixture":
            raise AdapterUnavailable(
                "fixture backend selected while ASSISTANT_ALLOW_FIXTURE_DATA=false"
            )

        if adapter is None:
            adapter = self._build_adapter()
        self.adapter = adapter
        self.store = store or DocumentStore(self.settings.db_path)
        self.generator = generator or GroundedGenerator(self.settings)
        self.assembler = EvidenceAssembler(self.adapter, self.store, self.settings)
        self.place_search = PlaceSearchService(self.adapter)
        self._image_service = image_service

        if self.settings.auto_ingest_corpus:
            corpus = Path(self.settings.corpus_dir)
            if corpus.exists():
                self.store.ingest_directory(corpus)

    def _build_adapter(self):
        backend = self.settings.structured_backend
        if backend == "fixture":
            return JsonRecordAdapter(
                self.settings.fixture_records_path,
                allow_fixture=self.settings.allow_fixture_data,
            )
        if backend == "json_export":
            if not self.settings.platform_export_path:
                raise AdapterUnavailable(
                    "ASSISTANT_PLATFORM_EXPORT_PATH is required for the json_export backend"
                )
            return JsonRecordAdapter(
                self.settings.platform_export_path,
                allow_fixture=self.settings.allow_fixture_data,
            )
        if backend == "postgres":
            # Implemented against the proposed read-only views once the backend
            # owner supplies a database. See docs/llm/API_CONTRACT.md.
            raise AdapterUnavailable(
                "The postgres adapter is a proposed contract awaiting the platform "
                "backend owner. No platform database exists in this repository."
            )
        if backend == "team_backend":
            from assistant.adapters.team_backend import TeamBackendAdapter

            return TeamBackendAdapter(
                self.settings.team_backend_url,
                timeout_s=self.settings.team_backend_timeout_s,
                max_retries=self.settings.team_backend_max_retries,
            )
        raise AdapterUnavailable(f"unknown structured backend: {backend}")

    # ------------------------------------------------------------------
    # Use cases
    # ------------------------------------------------------------------
    def chat(self, request: ChatRequest) -> AssistantAnswer:
        pack = self.assembler.assemble(
            question=request.question,
            candidate_id=request.candidate_id,
            target=request.target,
            mission_profile=request.mission_profile,
            include_background=request.include_background,
            max_sources=request.max_sources,
        )
        score_notice = detect_score_manipulation(request.question)
        citation_notice = detect_citation_fabrication(request.question)
        notices = [n for n in (score_notice, citation_notice) if n]
        answer = self.generator.generate(
            pack,
            conversation_context=request.conversation_context,
            notices=notices,
            score_notice=score_notice,
        ).answer
        guardrails = [citation_notice] if citation_notice else []
        if pack.security_flags:
            guardrails.append(
                "Retrieved document content contained instruction-like text and was "
                "sanitised: "
                + ", ".join(pack.security_flags)
                + ". It was treated as data only."
            )
        answer.guardrail_notices = guardrails
        return self._finalize(answer, pack.pack_id)

    def explain_report(self, request: ExplainReportRequest) -> AssistantAnswer:
        question = request.question or (
            f"Explain Analog Intelligence Report {request.report_id or '(supplied report)'} "
            "in plain language without changing any stored value."
        )
        report: ReportRecord | None = None
        candidate_id = None
        if request.report is not None:
            report = request.report
            candidate_id = report.candidate_id
        elif request.report_id:
            report = self.adapter.get_report(request.report_id)
            if report is not None:
                candidate_id = report.candidate_id
        pack = self.assembler.assemble(
            question=question,
            candidate_id=candidate_id,
            report=report,
            report_id=request.report_id,
            include_background=request.include_background,
        )
        notice = (
            "This is an explanation of a stored report. The report itself is not "
            "edited or regenerated; all supplied values are returned unchanged."
        )
        answer = self.generator.generate(
            pack,
            notices=[notice],
        ).answer
        return self._finalize(answer, pack.pack_id)

    def _finalize(self, answer: AssistantAnswer, pack_id: str) -> AssistantAnswer:
        answer.response_id = "RESP-" + uuid.uuid4().hex[:16]
        answer.pack_id = pack_id
        if not answer.prompt_version:
            answer.prompt_version = PROMPT_VERSION
        return answer

    def search_places(self, request: PlaceSearchRequest) -> PlaceSearchResponse:
        return self.place_search.search(request)

    def search_images(self, request: ImageSearchRequest) -> ImageSearchResponse:
        if self._image_service is None:
            self._image_service = ImageRetrievalService(
                self.adapter,
                timeout_s=self.settings.image_provider_timeout_s,
            )
        return self._image_service.search(request)

    def close(self) -> None:
        """Release the store and any provider HTTP clients this service owns."""
        if self._image_service is not None:
            self._image_service.close()
            self._image_service = None
        close_adapter = getattr(self.adapter, "close", None)
        if callable(close_adapter):
            close_adapter()
        self.store.close()

    # ------------------------------------------------------------------
    # Health and feedback
    # ------------------------------------------------------------------
    def health(self) -> HealthResponse:
        stats = self.store.stats()
        inference = ollama_health_payload(self.generator.client)
        mode = DataProvenanceMode(self.adapter.data_provenance_mode)
        return HealthResponse(
            retrieval={
                "backend": "sqlite_fts5",
                "db_path": str(self.store.path),
                **stats,
            },
            inference=inference,
            model={
                "configured": self.settings.ollama_model,
                "fallback": self.settings.ollama_fallback_model,
                "context_length": self.settings.ollama_num_ctx,
                "temperature": self.settings.ollama_temperature,
                "prompt_version": PROMPT_VERSION,
                "local_only": True,
            },
            data_mode=mode,
            fts5_available=self.store.fts5_available,
            message=(
                "Structured data is synthetic test-only fixture data; not platform output."
                if mode == DataProvenanceMode.FIXTURE_TEST_ONLY
                else None
            ),
        )

    def feedback(
        self,
        *,
        response_id: str | None,
        question_hash: str | None,
        useful: bool,
        factual: bool | None,
        comment: str | None,
    ) -> FeedbackRecord:
        return self.store.add_feedback(
            response_id=response_id,
            question_hash=question_hash,
            useful=useful,
            factual=factual,
            comment=comment,
        )

    @staticmethod
    def hash_question(question: str) -> str:
        return hashlib.sha256(question.encode("utf-8")).hexdigest()
