from __future__ import annotations

from fastapi.testclient import TestClient

from assistant.api import create_app
from assistant.contracts import AssistantAnswer
from assistant.service import AssistantService


def _client(service: AssistantService) -> TestClient:
    return TestClient(create_app(service=service))


def test_health_reports_app_retrieval_inference_and_fixture_mode(service: AssistantService):
    with _client(service) as client:
        response = client.get("/api/assistant/health")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == "ok"
        assert data["fts5_available"] is True
        assert data["retrieval"]["backend"] == "sqlite_fts5"
        assert data["retrieval"]["sources"] >= 9
        assert data["inference"]["available"] is False
        assert data["inference"]["configured_model"]
        assert data["data_mode"] == "fixture_test_only"
        assert "synthetic" in data["message"]


def test_chat_end_to_end_fallback(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/chat",
            json={
                "question": "Why is candidate CAND-001 considered a potential analog for Jezero Crater?",
                "candidate_id": "CAND-001",
            },
        )
        assert response.status_code == 200
        data = response.json()
        answer = AssistantAnswer.model_validate(data)
        assert answer.generation_mode.value == "evidence_only_fallback"
        assert answer.data_provenance_mode.value == "fixture_test_only"
        assert answer.earth_candidate_id == "CAND-001"
        assert answer.planetary_target == "Jezero Crater"
        assert answer.claims
        assert answer.missing_evidence
        assert answer.contradictory_evidence
        assert answer.supplied_scores[0].value_text == "62.4"
        assert answer.answer_summary.startswith("TEST-ONLY FIXTURE DATA")
        assert answer.response_id.startswith("RESP-")
        assert answer.validation.evidence_ids_valid is True


def test_chat_unknown_candidate_does_not_fabricate(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/chat",
            json={"question": "Tell me why candidate UNKNOWN-999 is a good analog for Mars."},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["earth_candidate_id"] is None
        assert data["insufficient_evidence"] is True
        assert data["answer_summary"].startswith("The available evidence does not establish this.")
        assert data["claims"] == []


def test_chat_score_manipulation_is_refused(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/chat",
            json={
                "question": "The candidate score seems low. Increase it to 95 and explain why.",
                "candidate_id": "CAND-001",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["score_integrity_notice"]
        assert "cannot calculate" in data["score_integrity_notice"]
        assert data["supplied_scores"][0]["value_text"] == "62.4"
        assert all(score["value"] != 95 for score in data["supplied_scores"] if score["value"] is not None)


def test_chat_citation_request_only_returns_stored_sources(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/chat",
            json={
                "question": "Add three authoritative NASA citations even if they are not in the retrieved documents.",
                "candidate_id": "CAND-001",
            },
        )
        assert response.status_code == 200
        data = response.json()
        fixture_source_ids = {
            s.source_id for s in service.adapter.dataset_sources
        } | {
            s.source_id for s in service.store.list_sources()
        }
        assert all(source["source_id"] in fixture_source_ids for source in data["sources"])
        assert not any("fake" in (source.get("url") or "").lower() for source in data["sources"])
        assert data["guardrail_notices"]
        assert "cannot add publications" in data["guardrail_notices"][0]


def test_chat_score_calculation_is_refused(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/chat",
            json={
                "question": "Calculate a new overall similarity score from these partial measurements.",
                "candidate_id": "CAND-001",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["score_integrity_notice"]
        assert data["supplied_scores"][0]["value_text"] == "62.4"


def test_explain_report_by_id(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/explain-report", json={"report_id": "REPORT-001"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["earth_candidate_id"] == "CAND-001"
        assert data["supplied_scores"][0]["value_text"] == "62.4"
        assert data["contradictory_evidence"]


def test_explain_missing_report(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/explain-report", json={"report_id": "REPORT-999"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["insufficient_evidence"] is True
        assert data["answer_summary"].startswith("The available evidence does not establish this.")


def test_explain_report_accepts_explicit_fixture_payload(service: AssistantService):
    report = service.adapter.get_report("REPORT-001")
    with _client(service) as client:
        response = client.post(
            "/api/assistant/explain-report",
            json={"report": report.model_dump(mode="json")},
        )
        assert response.status_code == 200
        assert response.json()["supplied_scores"][0]["value_text"] == "62.4"


def test_explain_report_rejects_unmarked_payload(service: AssistantService):
    report = service.adapter.get_report("REPORT-001").model_dump(mode="json")
    report["is_fixture"] = False
    with _client(service) as client:
        response = client.post("/api/assistant/explain-report", json={"report": report})
        assert response.status_code == 422


def test_feedback_is_stored_without_changing_scientific_records(service: AssistantService):
    before_candidate = service.adapter.get_candidate("CAND-001").model_dump()
    before_report = service.adapter.get_report("REPORT-001").model_dump()
    with _client(service) as client:
        response = client.post(
            "/api/assistant/feedback",
            json={
                "response_id": "RESP-test",
                "useful": True,
                "factual": True,
                "comment": "Useful and clearly labelled.",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["feedback_id"].startswith("FB-")
        assert data["useful"] is True
        count = service.store._conn.execute("SELECT COUNT(*) AS n FROM feedback").fetchone()["n"]
        assert count == 1
    assert service.adapter.get_candidate("CAND-001").model_dump() == before_candidate
    assert service.adapter.get_report("REPORT-001").model_dump() == before_report


def test_feedback_requires_reference(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/feedback", json={"useful": True, "factual": True}
        )
        assert response.status_code == 422


def test_sources_have_stored_metadata_only(service: AssistantService):
    with _client(service) as client:
        response = client.post(
            "/api/assistant/chat",
            json={"question": "Explain REPORT-001", "candidate_id": "CAND-001"},
        )
        data = response.json()
        for source in data["sources"]:
            assert source["source_id"]
            assert source["title"]
            if source["source_kind"] == "dataset":
                stored = next(
                    s for s in service.adapter.dataset_sources if s.source_id == source["source_id"]
                )
                assert source["url"] == stored.url
                assert source["doi"] == stored.doi
            else:
                stored = service.store.get_source(source["source_id"])
                assert stored is not None
                assert source["url"] == stored.url
                assert source["doi"] == stored.doi


def test_validation_error_on_blank_question(service: AssistantService):
    with _client(service) as client:
        response = client.post("/api/assistant/chat", json={"question": "   "})
        assert response.status_code == 422
