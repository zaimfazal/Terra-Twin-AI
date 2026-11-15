# API contract

## Status

The four assistant routes below are implemented and tested. The structured
platform adapter is a **proposed contract awaiting the platform backend owner**
because this repository contains no platform database, candidate store or
report API.

## Implemented assistant routes

All routes are additive under `/api/assistant`. No auth, frontend, discovery,
scoring or ranking endpoints are added.

### `POST /api/assistant/chat`

Request (`ChatRequest`):

```json
{
  "question": "Why is CAND-001 a potential analog for Jezero Crater?",
  "candidate_id": "CAND-001",
  "target": null,
  "mission_profile": null,
  "conversation_context": [],
  "include_background": true,
  "max_sources": 5
}
```

- `question`: 1–4,000 characters, non-blank.
- `candidate_id`: optional explicit ID; otherwise a `CAND-*` token in the
  question is used.
- `target`: optional target ID or name.
- `conversation_context`: optional prior turns; labelled untrusted and never
  treated as evidence.
- `include_background`: enables FTS5 document retrieval.
- `max_sources`: 1–10.

Response: `AssistantAnswer` (see `EVIDENCE_SCHEMA.md`). Example fields from a
fixture/fallback run:

```json
{
  "question": "Explain REPORT-001",
  "answer_summary": "TEST-ONLY FIXTURE DATA: ... Supplied overall similarity: 62.4 (unchanged). ... Reason: local model unavailable",
  "planetary_target": "Jezero Crater",
  "earth_candidate_id": "CAND-001",
  "insufficient_evidence": false,
  "data_provenance_mode": "fixture_test_only",
  "generation_mode": "evidence_only_fallback",
  "supplied_scores": [
    {"metric": "overall_similarity", "value_text": "62.4", "value": 62.4}
  ],
  "validation": {"schema_valid": true, "evidence_ids_valid": true, "sources_valid": true},
  "response_id": "RESP-...",
  "pack_id": "PACK-..."
}
```

### `POST /api/assistant/explain-report`

Request (`ExplainReportRequest`):

```json
{"report_id": "REPORT-001", "question": null, "include_background": true}
```

- `report_id` looks up a stored report.
- `report` accepts a caller-supplied report **only** when `is_fixture=true`;
  otherwise HTTP 422. Real reports must be looked up by ID.

Response: `AssistantAnswer`. Supplied scores are returned unchanged.

### `GET /api/assistant/health`

Response (`HealthResponse`):

```json
{
  "app": "ok",
  "retrieval": {
    "backend": "sqlite_fts5",
    "db_path": "...",
    "sources": 9,
    "failed_sources": 0,
    "chunks": 38,
    "fts5_available": true
  },
  "inference": {
    "available": true,
    "base_url": "http://127.0.0.1:11434",
    "configured_model": "qwen3:4b-instruct-2507-q4_K_M",
    "configured_model_present": true,
    "fallback_model": "qwen2.5:3b-instruct-q4_K_M",
    "fallback_model_present": false,
    "installed_models": ["qwen3:4b-instruct-2507-q4_K_M"],
    "mode": "local_ollama"
  },
  "model": {
    "configured": "qwen3:4b-instruct-2507-q4_K_M",
    "fallback": "qwen2.5:3b-instruct-q4_K_M",
    "context_length": 8192,
    "temperature": 0.0,
    "prompt_version": "assistant-rag-v1.1.0",
    "local_only": true
  },
  "data_mode": "fixture_test_only",
  "fts5_available": true,
  "message": "Structured data is synthetic test-only fixture data; not platform output."
}
```

### `POST /api/assistant/feedback`

Request (`FeedbackRequest`): `response_id` or `question_hash` is required;
`useful` is required; `factual` and `comment` are optional.

Response (`FeedbackRecord`): stored feedback with `feedback_id` and timestamp.
Feedback never modifies scientific records.

## Error behaviour

| Condition | Result |
|---|---|
| Blank/invalid request | HTTP 422 (Pydantic) |
| Caller-supplied non-fixture report | HTTP 422 |
| Structured adapter unavailable/not configured | HTTP 503 with `state=structured_adapter_unavailable` |
| Inference unavailable | HTTP 200 with `generation_mode=evidence_only_fallback` |
| Unknown candidate/report | HTTP 200, no fabrication, insufficient-evidence state |

## Proposed platform adapter contract

`assistant/adapters/base.py` defines `StructuredPlatformAdapter`. A backend
owner can satisfy it with a read-only export, a read-only API client or
read-only SQL views.

```python
class StructuredPlatformAdapter(Protocol):
    data_provenance_mode: str   # "platform" for real records
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
```

Requirements:

1. **Read-only.** No method may create, update or delete scientific records.
2. **Verbatim values.** Scores/coverage/confidence must be returned exactly as
   stored, including `value_text` and scale.
3. **Explicit missingness.** Missing values are `None` with an
   `unavailable` classification and a reason; never `0`.
4. **Stable IDs.** Candidate, report, evidence, contradiction and dataset IDs
   must be stable and globally unique within the platform.
5. **Provenance.** Every evidence item should reference a dataset source and
   record; every source should carry URL/DOI/licence when available.
6. **Ordering.** `get_reports_for_candidate` must return a deterministic order;
   the assistant takes the first and does not rank.

### JSON export shape

`JsonRecordAdapter` accepts:

```json
{
  "_fixture_only": false,
  "candidates": [],
  "targets": [],
  "reports": [],
  "evidence": [],
  "contradictions": [],
  "dataset_sources": []
}
```

An export with `_fixture_only: true` (or records with `is_fixture: true`) is
accepted only when `ASSISTANT_ALLOW_FIXTURE_DATA=true`, and every response is
labelled `fixture_test_only`. A production export must omit that marker.

### Proposed read-only SQL views

For a Postgres implementation, the backend owner supplies views with the same
field names as the Pydantic models:

- `assistant_candidates`
- `assistant_targets`
- `assistant_reports`
- `assistant_report_scores`
- `assistant_evidence`
- `assistant_contradictions`
- `assistant_dataset_sources`

No view may be writable by the assistant role. The assistant needs only
`SELECT`. The adapter is intentionally unimplemented until the owner confirms
names, types, null semantics and ID stability.

## Team backend adapter (`team_backend`)

`ASSISTANT_STRUCTURED_BACKEND=team_backend` selects
`assistant.adapters.team_backend.TeamBackendAdapter`, which calls the team's
Node/Express API at `TERRATWIN_BACKEND_URL` (default `http://localhost:8000`).
It is read-only, holds no database credential and never synthesises reports or
evidence.

Consumed endpoints: `GET /api/health`, `/api/analog`, `/api/analog/{id}`,
`/api/targets`, `/api/mission-profiles`, `/api/nasa-datasets`,
`/api/analog/nearby`, and the read-only `POST /api/analog/within-polygon`.

## `POST /api/assistant/places/search`

Natural-language candidate retrieval over the team's Analog records.

Request (`PlaceSearchRequest`, `assistant/places/contracts.py`):

```json
{
  "question": "Find arid environments with volcanic terrain similar to Mars",
  "target": null,
  "planetary_reference": null,
  "filters": null,
  "max_results": 10,
  "offset": 0
}
```

- `question` or `filters` is required.
- `filters` may add explicit `text_terms`, `countries`, `primary_planet_analogs`,
  `target_ids`, `dataset_terms`, `metrics`, `bounding_box`, or `radius`.
- Numeric ranges are applied only to the documented 0-100 platform indices
  (`roughness`, `relief`, `slope`, `aridity`, `thermal`, `rockiness`, `volcanic`,
  `access`). Numeric elevation is unavailable because the team schema stores
  elevation as display text.

Response (`PlaceSearchResponse`) includes `interpreted_filters`, `results`
with `match_explanations`, `unavailable_fields`, `missing_information`,
`limitations`, `data_provenance_mode`, `backend`, and
`ordering: "backend_order_preserved"`.

Semantics:

- A missing metric excludes a candidate from that filter and is reported under
  `missing_information`; it is never treated as zero or as dissimilarity.
- Scores, coverage and confidence are echoed verbatim and never re-ranked.
- Unsupported dimensions (mineralogy, vegetation, numeric elevation,
  temperature, candidate mission profile) are returned as `unavailable_fields`.
- An empty result is returned explicitly; nothing is fabricated.
- Qualitative terrain terms may match a documented heuristic index when the text
  does not mention the term; a limitation states this and labels the index as
  unverified.

## Integration questions for the backend owner

1. What are the real candidate/report/evidence/target identifier formats?
2. Which fields are nullable, and how is `NoData` represented?
3. Are similarity, coverage and confidence stored as numbers, strings or both?
4. Which report is canonical when a candidate has several?
5. What is the stable ordering for multiple reports?
6. Which dataset metadata is authoritative: catalogue table, STAC, or export?
7. Is there an existing auth/rate-limit layer the assistant must sit behind?
8. Can the assistant read a replica/snapshot instead of the primary database?
