# LLM assistant architecture

## Status

Implemented as a standalone, additive workstream package. It is **not** wired
into a platform backend because this repository contains no platform backend,
database, candidate store or report API. The structured-record layer is a
typed read-only adapter with a synthetic test-only fixture and a proposed
platform contract (see `API_CONTRACT.md`).

Verified in this repository:

- 125 automated tests pass.
- 26 evaluation questions pass in deterministic evidence-only fallback mode.
- SQLite FTS5 is available and 9 corpus documents ingest as `processed`.
- Ollama 0.40.16 runs `qwen3:4b-instruct-2507-q4_K_M` locally; real inference
  and model-mode evaluation results are recorded in `EXPERIMENT_LOG.md`.
- A read-only team-backend adapter, natural-language place retrieval and
  cross-planetary NASA image retrieval are implemented with mocked tests only;
  no live MongoDB or Node backend has been exercised.

## Responsibility boundary

The assistant **explains** existing records. The deterministic scientific
engine and verified platform records are the only source of measurements,
coordinates, evidence classifications, similarity, data coverage, data
confidence, eligibility and ranking.

The assistant does **not**:

- ingest or process Earth/Moon/Mars rasters;
- extract features or discover candidates;
- calculate, change, round, interpolate or re-rank scores;
- assign confidence, coverage or eligibility;
- write to scientific records;
- browse the web or call external tools at inference time;
- authenticate users or serve a frontend.

## Components

| Module | Responsibility |
|---|---|
| `assistant/contracts.py` | Pydantic contracts for records, evidence packs, model drafts, validated answers, requests |
| `assistant/config.py` | `ASSISTANT_*` environment settings; local-only defaults |
| `assistant/adapters/base.py` | `StructuredPlatformAdapter` protocol and `AdapterUnavailable` |
| `assistant/adapters/json_records.py` | Read-only JSON export/fixture adapter; refuses unmarked data |
| `assistant/adapters/team_backend.py` | Read-only HTTP client for the team Node/Express API; no write verbs |
| `assistant/adapters/team_records.py` | Normalised team records with provenance and `missing_fields` |
| `assistant/retrieval/query_parser.py` | Deterministic place-query parser; no invented thresholds |
| `assistant/places/contracts.py` | Place-search request/response contracts |
| `assistant/places/service.py` | Filtering, match explanations, provenance, limitations |
| `assistant/images/contracts.py` | Image records with no score field; group/source contracts |
| `assistant/images/validation.py` | HTTPS/host/IP/credential checks against provider allowlists |
| `assistant/images/providers/*.py` | NASA Image Library, GIBS (Earth only) and PDS providers |
| `assistant/images/orchestrator.py` | Keyword queries, provider isolation, dedupe, grouping |
| `assistant/ingestion/loaders.py` | Markdown/TXT/JSON/CSV/PDF loading, metadata, hashing, injection sanitisation |
| `assistant/ingestion/store.py` | SQLite schema, FTS5 index, source metadata, feedback |
| `assistant/evidence/assembler.py` | Deterministic evidence-pack assembly and lookups |
| `assistant/evidence/validation.py` | Server-side ID, numeric, source, proxy, missing-as-zero and overclaim validation |
| `assistant/llm/prompt.py` | Versioned prompt construction; untrusted-document delimiter |
| `assistant/llm/ollama.py` | Local Ollama health and structured generation adapter |
| `assistant/llm/fallback.py` | Deterministic evidence-only answer when inference is unavailable/rejected |
| `assistant/llm/generation.py` | Generation orchestration, parse/validate, fallback |
| `assistant/service.py` | Use cases: chat, explain report, place search, image search, health, feedback, close |
| `assistant/api.py` | Minimal additive FastAPI routes |
| `scripts/run_evaluation.py` | Evaluation harness and result recorder |

## Request flow

```
POST /api/assistant/chat
  -> AssistantService.chat
     -> EvidenceAssembler.assemble
        -> adapter.get_candidate / get_report / get_evidence / get_contradictions
        -> DocumentStore.search (SQLite FTS5)
     -> detect score-manipulation / citation-fabrication requests
     -> GroundedGenerator.generate
        -> build_user_prompt (structured pack + delimited untrusted excerpts)
        -> OllamaClient.generate (JSON-schema constrained)
        -> parse_draft
        -> validate_draft (IDs, sources, numbers, classifications, guardrails)
        -> AssistantAnswer OR build_evidence_only_answer
     -> attach guardrail notices and response ID
  -> AssistantAnswer JSON
```

The evidence pack is built **before** the model call. The model cannot request
records, query the database, call tools or add sources.

Place and image retrieval do not call the model at all:

```
POST /api/assistant/places/search
  -> parse_place_query (deterministic)
  -> TeamBackendAdapter.list_analogs / find_target (read-only HTTP)
  -> PlaceSearchService filters documented fields
  -> results with match_explanations, missing_fields, unavailable_fields

POST /api/assistant/images/search
  -> TeamBackendAdapter.get_analog / find_target (read-only HTTP)
  -> keyword query per planet
  -> NASA Image Library (+ GIBS for Earth, + PDS for Moon/Mars)
  -> URL/host validation, dedupe, grouping
  -> earth/moon/mars records, sources, missing_previews, rejected_assets
```

## Trust boundaries

1. **Structured records** are trusted for measurements, scores, IDs and
   classifications. They are read-only.
2. **Retrieved document text** is untrusted data. It is sanitised on ingestion,
   delimited in the prompt, and never treated as instructions.
3. **User question and conversation context** are untrusted. They cannot change
   system rules and are not evidence.
4. **Model output** is untrusted. Every candidate-specific claim must cite an
   evidence ID from the current pack; every source ID and number is checked
   server-side.

## Data provenance modes

| Mode | Meaning |
|---|---|
| `platform` | Records came from a platform export/API marked as real |
| `fixture_test_only` | Synthetic test records; never present as measurements |
| `none` | No structured record was resolved for the request |

Fixture mode is guarded by `ASSISTANT_ALLOW_FIXTURE_DATA`. Setting it to
`false` makes the service refuse a fixture backend at construction time.

## Hardware and runtime

Measured on the development machine:

- CPU: 11th Gen Intel Core i5-11320H @ 3.20 GHz
- RAM: 8,362,713,088 bytes (~7.8 GiB)
- GPU: NVIDIA GeForce GTX 1650, 4,293,918,720 bytes reported (~4 GiB)
- OS/runtime: Windows, Python 3.12, Ollama 0.40.16

The default model is chosen to fit 4 GiB VRAM / 8 GiB RAM with an 8K working
context (`ASSISTANT_OLLAMA_NUM_CTX=8192`), not the model's full 256K context.

## Deployment notes

- Run `python scripts/ingest_corpus.py` to build the local index.
- Run `python scripts/run_assistant.py` for the API.
- The database is local SQLite and rebuildable from `corpus/`.
- No secrets are required. Ollama is contacted over loopback HTTP only.
- The package has no dependency on a paid API, hosted inference, embeddings
  service or vector database.

## Known architectural gaps

- The team backend adapter is implemented but never exercised against a live
  MongoDB/Node deployment; all tests use mocked HTTP.
- `postgres` still raises `AdapterUnavailable` until the backend owner supplies
  read-only views.
- PDS ODE parsing is defensive; the live response shape is unverified.
- One candidate evidence pack per answer (no cross-candidate comparison).
- No embeddings or semantic retrieval; FTS5 + structured lookup only.
- No streaming, auth, rate limiting or multi-tenant isolation.
- Model evaluation results depend on local hardware; see `EVALUATION.md`.
