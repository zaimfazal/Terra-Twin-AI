from __future__ import annotations

from pathlib import Path

import pytest

from assistant.adapters.json_records import JsonRecordAdapter
from assistant.config import WORKSTREAM_ROOT, Settings
from assistant.contracts import ModelClaim, ModelDraft
from assistant.evidence.assembler import EvidenceAssembler
from assistant.ingestion.store import DocumentStore
from assistant.service import AssistantService


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "assistant.db",
        corpus_dir=WORKSTREAM_ROOT / "corpus",
        fixture_records_path=WORKSTREAM_ROOT / "fixtures" / "test_only_platform_records.json",
        structured_backend="fixture",
        allow_fixture_data=True,
        auto_ingest_corpus=True,
        ollama_base_url="http://127.0.0.1:9",
        ollama_health_timeout_s=0.2,
        ollama_timeout_s=0.5,
    )


@pytest.fixture()
def adapter(test_settings: Settings) -> JsonRecordAdapter:
    return JsonRecordAdapter(test_settings.fixture_records_path)


@pytest.fixture()
def store(test_settings: Settings) -> DocumentStore:
    document_store = DocumentStore(test_settings.db_path)
    document_store.ingest_directory(test_settings.corpus_dir)
    yield document_store
    document_store.close()


@pytest.fixture()
def assembler(adapter, store, test_settings) -> EvidenceAssembler:
    return EvidenceAssembler(adapter, store, test_settings)


@pytest.fixture()
def pack(assembler):
    return assembler.assemble(
        question="Why is CAND-001 a potential analog for Jezero Crater?",
        candidate_id="CAND-001",
    )


@pytest.fixture()
def service(test_settings: Settings) -> AssistantService:
    svc = AssistantService(test_settings)
    yield svc
    svc.store.close()


def make_draft(**overrides) -> ModelDraft:
    base = {
        "answer_summary": "The stored record describes a terrain and thermal comparison.",
        "planetary_target": "Jezero Crater",
        "earth_candidate_id": "CAND-001",
        "claims": [
            ModelClaim(
                claim="The stored mean slope is 8.4 deg.",
                evidence_ids=["EV-C1-001"],
            )
        ],
    }
    base.update(overrides)
    return ModelDraft(**base)
