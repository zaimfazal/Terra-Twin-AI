"""Minimal FastAPI routes for the assistant workstream.

These routes are additive. No auth, frontend, discovery, scoring or ranking
logic is implemented here. Existing team routes are not modified or replaced.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from assistant.adapters.base import AdapterUnavailable
from assistant.config import Settings
from assistant.config import settings as default_settings
from assistant.contracts import (
    AssistantAnswer,
    ChatRequest,
    ExplainReportRequest,
    FeedbackRecord,
    FeedbackRequest,
    HealthResponse,
)
from assistant.places.contracts import PlaceSearchRequest, PlaceSearchResponse
from assistant.service import AssistantService


def create_app(
    settings: Settings | None = None,
    *,
    service: AssistantService | None = None,
) -> FastAPI:
    service = service or AssistantService(settings or default_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        service.store.close()

    app = FastAPI(
        title="Planetary Analog Discovery — AI Scientific Research Assistant",
        version="0.1.0",
        description=(
            "Evidence-grounded interpretation of existing platform records. "
            "The assistant cannot create or modify scientific scores."
        ),
        lifespan=lifespan,
    )
    app.state.service = service

    @app.exception_handler(AdapterUnavailable)
    async def adapter_unavailable_handler(request: Request, exc: AdapterUnavailable):
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "state": "structured_adapter_unavailable",
                "hint": "See docs/llm/API_CONTRACT.md for the proposed platform contract.",
            },
        )

    @app.post("/api/assistant/chat", response_model=AssistantAnswer)
    def chat(request: ChatRequest) -> AssistantAnswer:
        return service.chat(request)

    @app.post("/api/assistant/explain-report", response_model=AssistantAnswer)
    def explain_report(request: ExplainReportRequest) -> AssistantAnswer:
        return service.explain_report(request)

    @app.get("/api/assistant/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return service.health()

    @app.post("/api/assistant/places/search", response_model=PlaceSearchResponse)
    def places_search(request: PlaceSearchRequest) -> PlaceSearchResponse:
        return service.search_places(request)

    @app.post("/api/assistant/feedback", response_model=FeedbackRecord)
    def feedback(request: FeedbackRequest) -> FeedbackRecord:
        if not request.response_id and not request.question_hash:
            raise HTTPException(
                status_code=422,
                detail="feedback must reference a response_id or question_hash",
            )
        return service.feedback(
            response_id=request.response_id,
            question_hash=request.question_hash,
            useful=request.useful,
            factual=request.factual,
            comment=request.comment,
        )

    return app
