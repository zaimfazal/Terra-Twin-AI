# LLM workstream task tracker

Status values: `done`, `partial`, `blocked`, `not started`.

| ID | Task | Status | Dependency / notes |
|---|---|---|---|
| LLM-001 | Inspect PRD, repository and platform contracts | done | No platform backend/API/database exists in this repository |
| LLM-002 | Typed evidence-pack and response schemas | done | `assistant/contracts.py`; extra fields forbidden |
| LLM-003 | Structured candidate/report adapter | partial | JSON export + fixture implemented; Postgres contract awaiting backend owner |
| LLM-004 | Document ingestion and source metadata | done | MD/TXT/JSON/CSV/PDF; sidecar/front-matter metadata; hashes; 9 docs ingested |
| LLM-005 | SQLite FTS5 retrieval | done | 38 chunks; health reports FTS5 availability |
| LLM-006 | Local Ollama model selection and test | done | Ollama 0.40.16; qwen3:4b-instruct-2507-q4_K_M; Apache-2.0; results in EXPERIMENT_LOG |
| LLM-007 | Evidence assembly and citation validation | done | Unknown IDs/sources rejected; numeric allowlist; contradictions/missing preserved |
| LLM-008 | Grounded generation and fallback | done | JSON-schema request; strict parse; deterministic evidence-only fallback |
| LLM-009 | FastAPI routes | done | 4 additive routes under `/api/assistant`; no auth/frontend |
| LLM-010 | Evaluation suite and limitations | done | 26 questions; fallback 26/26; model mode recorded separately |
| LLM-011 | Scientific guardrail tests | done | 71 pytest tests; see SCIENTIFIC_GUARDRAILS.md |
| LLM-012 | Documentation set | done | 12 required docs under `docs/llm/` |
| LLM-013 | Real platform integration | blocked | Needs read-only export/API/views and ID/null/ordering confirmation |
| LLM-014 | Multi-candidate comparison | not started | Requires a new pack design; do not rank |
| LLM-015 | Optional local embeddings | not started | Only if FTS5 misses become a measured problem |
| LLM-016 | Production auth/rate limiting | not started | Owned by platform/backend, not this workstream |
| LLM-017 | Team repository audit and integration design | done | `TEAM_INTEGRATION.md`; read-only sibling clone |
| LLM-018 | Repository cleanup and `.gitignore` | done | Untracked pycache/runtime DBs; artifacts preserved on disk |
| LLM-019 | Team backend read-only HTTP adapter | not started | `assistant/adapters/team_backend.py`; `TERRATWIN_BACKEND_URL`; mocked tests |
| LLM-020 | Natural-language query parser | not started | Deterministic rules; unsupported fields become warnings |
| LLM-021 | Place search contracts | not started | `assistant/places/contracts.py`; provenance + missing fields |
| LLM-022 | Place search service and API | not started | `POST /api/assistant/places/search` |
| LLM-023 | NASA Image Library provider | not started | `/search`, `/asset/{id}`, `/metadata/{id}`; URL/domain validation |
| LLM-024 | NASA GIBS Earth imagery provider | not started | Earth only; layer/date validation |
| LLM-025 | PDS planetary image provider | not started | LROC/HiRISE; missing-preview handling |
| LLM-026 | Cross-planetary image orchestration | not started | Group earth/moon/mars; dedupe; limitations |
| LLM-027 | Image retrieval API | not started | `POST /api/assistant/images/search` |
| LLM-028 | Provider and SSRF test suite | not started | Mocked HTTP only; no live NASA dependency |
| LLM-029 | Team handover documentation | not started | `HANDOVER.md` maintained per milestone |

## Next dependency

The critical dependency is a **read-only platform data contract**: real
candidate, report, evidence, contradiction and dataset-source records with
stable IDs, explicit null/NoData semantics, verbatim score text and
deterministic report ordering. Until that exists, all integration testing is
fixture-based and every response is labelled accordingly.
