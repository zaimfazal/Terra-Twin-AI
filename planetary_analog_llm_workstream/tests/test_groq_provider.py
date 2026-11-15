"""Mocked tests for the optional Groq hosted-inference provider.

No live Groq API key is used or required. Every HTTP response is fabricated.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from assistant.config import Settings
from assistant.contracts import ModelClaim, ModelDraft
from assistant.llm.generation import GroundedGenerator
from assistant.llm.groq import GroqClient
from assistant.llm.types import ModelUnavailable
from assistant.service import AssistantService

# Deliberately not shaped like a real Groq key, so secret scanners do not flag it.
API_KEY = "test-only-not-a-real-key"
MODEL = "openai/gpt-oss-120b"
CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS_URL = "https://api.groq.com/openai/v1/models"


@pytest.fixture()
def groq_settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(
        update={
            "llm_provider": "groq",
            "groq_api_key": SecretStr(API_KEY),
            "groq_model": MODEL,
            "groq_timeout_s": 5.0,
            "groq_health_timeout_s": 1.0,
        }
    )


def _response(
    status_code: int = 200,
    *,
    payload: dict | None = None,
    headers: dict | None = None,
    text: str | None = None,
    url: str = CHAT_URL,
    method: str = "POST",
) -> httpx.Response:
    request = httpx.Request(method, url)
    if text is not None:
        return httpx.Response(status_code, text=text, headers=headers, request=request)
    return httpx.Response(status_code, json=payload, headers=headers, request=request)


def _completion(
    content: str,
    *,
    model: str = MODEL,
    usage: dict | None = None,
) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage
        if usage is not None
        else {"prompt_tokens": 120, "completion_tokens": 48, "total_tokens": 168},
    }


def _draft_json() -> str:
    draft = ModelDraft(
        answer_summary="The stored mean slope is 8.4 deg and it is directly observed.",
        planetary_target="Jezero Crater",
        earth_candidate_id="CAND-001",
        claims=[
            ModelClaim(
                claim="The stored mean slope is 8.4 deg.",
                evidence_ids=["EV-C1-001"],
            )
        ],
    )
    return draft.model_dump_json()


def _patch_post(monkeypatch, handler):
    calls: list[dict] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "json": json, "timeout": timeout})
        return handler(len(calls), json)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


# ---------------------------------------------------------------------------
# Successful generation
# ---------------------------------------------------------------------------
def test_groq_generates_and_records_model_usage(monkeypatch, groq_settings):
    calls = _patch_post(monkeypatch, lambda n, payload: _response(payload=_completion("{}")))
    client = GroqClient(groq_settings)
    response = client.generate(
        system_prompt="system rules",
        user_prompt="question",
        json_schema={"type": "object", "properties": {}},
    )

    assert response.content == "{}"
    assert response.model == MODEL
    assert response.provider == "groq"
    assert response.prompt_eval_count == 120
    assert response.eval_count == 48
    assert response.total_tokens == 168
    assert response.done_reason == "stop"
    assert calls[0]["url"] == CHAT_URL


def test_groq_requests_openai_compatible_structured_output(monkeypatch, groq_settings):
    schema = {"type": "object", "properties": {"answer_summary": {"type": "string"}}}
    calls = _patch_post(monkeypatch, lambda n, payload: _response(payload=_completion("{}")))
    client = GroqClient(groq_settings)
    client.generate(system_prompt="system rules", user_prompt="question", json_schema=schema)

    body = calls[0]["json"]
    assert body["model"] == MODEL
    assert body["messages"][0] == {"role": "system", "content": "system rules"}
    assert body["messages"][1] == {"role": "user", "content": "question"}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert body["response_format"]["json_schema"]["strict"] is False
    # The key travels in the header only, never in the body.
    assert API_KEY not in json.dumps(body)


def test_groq_output_is_validated_and_scores_are_immutable(monkeypatch, groq_settings, pack):
    _patch_post(monkeypatch, lambda n, payload: _response(payload=_completion(_draft_json())))
    generator = GroundedGenerator(groq_settings)
    outcome = generator.generate(pack)

    assert outcome.answer.generation_mode.value == "model"
    assert outcome.answer.model == MODEL
    assert outcome.answer.model_provider == "groq"
    assert outcome.provider == "groq"
    assert outcome.eval_count == 48
    assert outcome.answer.claims[0].validation_status.value == "validated"
    assert outcome.answer.validation.evidence_ids_valid is True
    assert [s.model_dump(mode="json") for s in outcome.answer.supplied_scores] == [
        s.model_dump(mode="json") for s in pack.scores
    ]


def test_groq_reports_actual_model_returned_by_provider(monkeypatch, groq_settings):
    _patch_post(
        monkeypatch,
        lambda n, payload: _response(payload=_completion("{}", model="openai/gpt-oss-20b")),
    )
    response = GroqClient(groq_settings).generate(
        system_prompt="s", user_prompt="u", json_schema={"type": "object"}
    )
    assert response.model == "openai/gpt-oss-20b"


# ---------------------------------------------------------------------------
# Malformed or invalid output
# ---------------------------------------------------------------------------
def test_groq_malformed_json_falls_back(monkeypatch, groq_settings, pack):
    _patch_post(
        monkeypatch,
        lambda n, payload: _response(payload=_completion("I think the answer is 42.")),
    )
    outcome = GroundedGenerator(groq_settings).generate(pack)

    assert outcome.answer.generation_mode.value == "evidence_only_fallback"
    assert outcome.answer.validation.schema_valid is False
    assert "JSON" in (outcome.error or "")
    assert outcome.answer.supplied_scores[0].value_text == "62.4"
    assert outcome.model == MODEL


def test_groq_invalid_response_structure_falls_back(monkeypatch, groq_settings, pack):
    _patch_post(
        monkeypatch,
        lambda n, payload: _response(
            payload=_completion('{"answer_summary": "x", "overall_similarity": 95}')
        ),
    )
    outcome = GroundedGenerator(groq_settings).generate(pack)
    assert outcome.answer.generation_mode.value == "evidence_only_fallback"
    assert outcome.answer.validation.schema_valid is False


def test_groq_unknown_evidence_ids_are_rejected(monkeypatch, groq_settings, pack):
    draft = ModelDraft(
        answer_summary="A claim with a fabricated ID.",
        earth_candidate_id="CAND-001",
        claims=[ModelClaim(claim="The slope is 8.4 deg.", evidence_ids=["EV-FAKE"])],
    )
    _patch_post(
        monkeypatch,
        lambda n, payload: _response(payload=_completion(draft.model_dump_json())),
    )
    outcome = GroundedGenerator(groq_settings).generate(pack)
    assert outcome.answer.claims == []
    assert outcome.answer.validation.evidence_ids_valid is False
    assert outcome.answer.insufficient_evidence is True


def test_groq_response_without_choices_is_unavailable(monkeypatch, groq_settings):
    _patch_post(monkeypatch, lambda n, payload: _response(payload={"model": MODEL}))
    with pytest.raises(ModelUnavailable, match="malformed"):
        GroqClient(groq_settings).generate(
            system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )


def test_groq_empty_content_is_unavailable(monkeypatch, groq_settings):
    _patch_post(monkeypatch, lambda n, payload: _response(payload=_completion("   ")))
    with pytest.raises(ModelUnavailable, match="empty"):
        GroqClient(groq_settings).generate(
            system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )


def test_groq_non_json_envelope_is_unavailable(monkeypatch, groq_settings):
    _patch_post(monkeypatch, lambda n, payload: _response(text="<html>bad gateway</html>"))
    with pytest.raises(ModelUnavailable, match="non-JSON"):
        GroqClient(groq_settings).generate(
            system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )


# ---------------------------------------------------------------------------
# HTTP and transport failures
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "headers", "fragment"),
    [
        (401, None, "401"),
        (403, None, "403"),
        (429, {"retry-after": "7"}, "rate limit"),
        (404, None, "not available"),
    ],
)
def test_groq_http_errors_are_distinct(monkeypatch, groq_settings, status, headers, fragment):
    _patch_post(
        monkeypatch,
        lambda n, payload: _response(status, text="provider error", headers=headers),
    )
    with pytest.raises(ModelUnavailable) as excinfo:
        GroqClient(groq_settings).generate(
            system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )
    message = str(excinfo.value)
    assert fragment in message
    assert API_KEY not in message
    if status == 429:
        assert "7 s" in message
    if status == 404:
        assert MODEL in message


def test_groq_timeout_is_reported(monkeypatch, groq_settings):
    def raise_timeout(*args, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "post", raise_timeout)
    with pytest.raises(ModelUnavailable, match="timed out"):
        GroqClient(groq_settings).generate(
            system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )


def test_groq_network_failure_is_reported(monkeypatch, groq_settings):
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", raise_connect_error)
    with pytest.raises(ModelUnavailable, match="unreachable"):
        GroqClient(groq_settings).generate(
            system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )


def test_groq_provider_failure_falls_back_to_evidence_only(monkeypatch, groq_settings, pack):
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", raise_connect_error)
    outcome = GroundedGenerator(groq_settings).generate(pack)

    assert outcome.answer.generation_mode.value == "evidence_only_fallback"
    assert outcome.model is None
    assert outcome.provider == "groq"
    assert "unreachable" in (outcome.error or "")
    assert outcome.answer.claims
    assert [s.model_dump(mode="json") for s in outcome.answer.supplied_scores] == [
        s.model_dump(mode="json") for s in pack.scores
    ]


def test_groq_json_schema_rejection_retries_json_object(monkeypatch, groq_settings):
    def handler(n, payload):
        if n == 1:
            return _response(400, text="response_format json_schema is not supported")
        return _response(payload=_completion("{}"))

    calls = _patch_post(monkeypatch, handler)
    response = GroqClient(groq_settings).generate(
        system_prompt="s", user_prompt="u", json_schema={"type": "object"}
    )
    assert response.content == "{}"
    assert calls[0]["json"]["response_format"]["type"] == "json_schema"
    assert calls[1]["json"]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------
def test_groq_missing_api_key_is_unavailable_without_network(monkeypatch, test_settings):
    settings = test_settings.model_copy(
        update={"llm_provider": "groq", "groq_api_key": None, "groq_model": MODEL}
    )
    calls = _patch_post(monkeypatch, lambda n, payload: _response(payload=_completion("{}")))
    with pytest.raises(ModelUnavailable, match="GROQ_API_KEY"):
        GroqClient(settings).generate(
            system_prompt="s", user_prompt="u", json_schema={"type": "object"}
        )
    assert calls == []


def test_groq_missing_api_key_falls_back(monkeypatch, test_settings, pack):
    settings = test_settings.model_copy(
        update={"llm_provider": "groq", "groq_api_key": None, "groq_model": MODEL}
    )
    _patch_post(monkeypatch, lambda n, payload: _response(payload=_completion("{}")))
    outcome = GroundedGenerator(settings).generate(pack)
    assert outcome.answer.generation_mode.value == "evidence_only_fallback"
    assert "GROQ_API_KEY" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Health reporting
# ---------------------------------------------------------------------------
def _patch_get(monkeypatch, handler):
    calls: list[dict] = []

    def fake_get(url, *, headers=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "timeout": timeout})
        return handler(len(calls))

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_groq_health_without_key_is_not_available(monkeypatch, test_settings):
    settings = test_settings.model_copy(update={"llm_provider": "groq", "groq_api_key": None})
    calls = _patch_get(monkeypatch, lambda n: _response(payload={"data": []}, method="GET"))
    health = GroqClient(settings).health()
    assert health["configured"] is False
    assert health["available"] is False
    assert health["reachable"] is False
    assert "GROQ_API_KEY" in health["error"]
    assert calls == []


def test_groq_health_configured_but_unreachable_is_not_available(monkeypatch, groq_settings):
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", raise_connect_error)
    health = GroqClient(groq_settings).health()
    assert health["configured"] is True
    assert health["available"] is False
    assert health["reachable"] is False


def test_groq_health_rejected_key_is_not_available(monkeypatch, groq_settings):
    _patch_get(monkeypatch, lambda n: _response(401, text="unauthorized", method="GET"))
    health = GroqClient(groq_settings).health()
    assert health["reachable"] is True
    assert health["authenticated"] is False
    assert health["available"] is False
    assert "401" in health["error"]


def test_groq_health_available_only_after_successful_probe(monkeypatch, groq_settings):
    _patch_get(
        monkeypatch,
        lambda n: _response(
            payload={"data": [{"id": MODEL}, {"id": "other-model"}]}, method="GET"
        ),
    )
    health = GroqClient(groq_settings).health()
    assert health["available"] is True
    assert health["authenticated"] is True
    assert health["configured_model_present"] is True
    assert MODEL in health["installed_models"]
    assert health["base_url"] == "https://api.groq.com/openai/v1"
    assert health["mode"] == "hosted_groq"


def test_groq_health_reports_absent_configured_model(monkeypatch, groq_settings):
    _patch_get(monkeypatch, lambda n: _response(payload={"data": [{"id": "other"}]}, method="GET"))
    health = GroqClient(groq_settings).health()
    assert health["available"] is True
    assert health["configured_model_present"] is False


# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------
def test_groq_health_and_repr_never_contain_the_key(monkeypatch, groq_settings):
    _patch_get(monkeypatch, lambda n: _response(401, text="unauthorized", method="GET"))
    client = GroqClient(groq_settings)
    health = client.health()
    assert API_KEY not in json.dumps(health)
    assert API_KEY not in repr(client)
    assert API_KEY not in str(groq_settings.groq_api_key)


def test_groq_key_not_written_to_logs(monkeypatch, groq_settings, caplog):
    _patch_post(monkeypatch, lambda n, payload: _response(401, text="unauthorized"))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ModelUnavailable):
            GroqClient(groq_settings).generate(
                system_prompt="s", user_prompt="u", json_schema={"type": "object"}
            )
    assert API_KEY not in caplog.text


def test_service_health_reports_groq_without_exposing_the_key(monkeypatch, groq_settings):
    _patch_get(monkeypatch, lambda n: _response(payload={"data": [{"id": MODEL}]}, method="GET"))
    service = AssistantService(groq_settings)
    try:
        health = service.health()
        payload = health.model_dump(mode="json")
        assert payload["inference"]["provider"] == "groq"
        assert payload["inference"]["available"] is True
        assert payload["model"]["provider"] == "groq"
        assert payload["model"]["configured"] == MODEL
        assert payload["model"]["local_only"] is False
        assert payload["retrieval"]["structured_backend"] == "fixture"
        assert API_KEY not in json.dumps(payload)
    finally:
        service.close()


def test_service_health_groq_configured_but_unreachable(monkeypatch, groq_settings):
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", raise_connect_error)
    service = AssistantService(groq_settings)
    try:
        health = service.health()
        assert health.inference["configured"] is True
        assert health.inference["available"] is False
        assert health.model["configured"] == MODEL
    finally:
        service.close()
