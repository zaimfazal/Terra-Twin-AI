"""Configuration for the assistant workstream.

All values are environment-overridable with the ``ASSISTANT_`` prefix. No
secrets are required. Local inference is optional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKSTREAM_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASSISTANT_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # Storage
    db_path: Path = Field(default=WORKSTREAM_ROOT / "data" / "assistant.db")
    corpus_dir: Path = Field(default=WORKSTREAM_ROOT / "corpus")
    fixture_records_path: Path = Field(
        default=WORKSTREAM_ROOT / "fixtures" / "test_only_platform_records.json"
    )
    feedback_path: Path | None = None

    # Structured platform adapter.
    # fixture: synthetic records marked test-only (development/evaluation only)
    # json_export: a read-only export produced by the platform owner
    # postgres: read-only SQL views described in docs/llm/API_CONTRACT.md
    # team_backend: read-only HTTP client for the team Node/Express API
    structured_backend: Literal[
        "fixture", "json_export", "postgres", "team_backend"
    ] = "fixture"
    platform_export_path: Path | None = None
    postgres_dsn: str | None = None

    # Team backend (Node/Express). The Node service owns MongoDB; this URL is
    # the only integration point and no database credential is stored here.
    team_backend_url: str = Field(
        default="http://localhost:8000",
        validation_alias="TERRATWIN_BACKEND_URL",
    )
    team_backend_timeout_s: float = 10.0
    team_backend_max_retries: int = 1

    # Refuse fixture data in production-like deployments. When false, startup
    # fails if the configured backend would return unverified fixture records.
    allow_fixture_data: bool = True

    # Local inference (Ollama). Verified default target: see MODEL_SELECTION.md.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    ollama_fallback_model: str = "qwen2.5:3b-instruct-q4_K_M"
    ollama_timeout_s: float = 600.0
    ollama_health_timeout_s: float = 3.0
    ollama_num_ctx: int = 8192
    ollama_temperature: float = 0.0
    ollama_num_predict: int = 1200
    require_model: bool = False

    # Retrieval
    max_documents: int = 5
    max_document_chars: int = 1800
    max_evidence_items: int = 60
    max_context_chars: int = 24000

    # Ingestion
    auto_ingest_corpus: bool = True

    # Output guard
    min_claim_evidence_ids: int = 1


settings = Settings()
