# Planetary Analog Discovery — LLM Workstream Starter

This package is ONLY for the AI Scientific Research Assistant workstream. It is not the full planetary discovery application starter.

## Use this package

1. Extract this folder.
2. Put the folder into the team's existing repository, or copy its contents into a dedicated LLM branch/worktree.
3. Keep the original team `AGENTS.md`, shared API schemas, and scientific-engine contracts if they already exist. Do not overwrite shared files blindly.
4. Ensure the PRD is available at `reference/planetary_analog_discovery_prd.docx` (included here).
5. Open the repository root in OpenCode.
6. Read `AGENTS.md` and then paste/run `prompts/LLM_IMPLEMENTATION_PROMPT.md`.
7. Use `prompts/RAG_SYSTEM_PROMPT.txt` as the application assistant's initial system prompt; the coding agent should refine it only with documented tests.

## Scope

Implement only the LLM subsystem: knowledge ingestion, structured scientific evidence retrieval, evidence assembly/validation, local-model adapter, grounded generation, FastAPI integration endpoints, and evaluation.

Do not implement Earth/Moon/Mars raster processing, global discovery, scientific feature extraction, similarity scoring, candidate ranking, frontend, maps, authentication, or the full platform backend. Integrate with the team's actual interfaces. If those interfaces do not exist, propose and document a minimal adapter contract instead of fabricating records.

## Zero-cost approach

Default to local inference through Ollama and an appropriately sized open-weight model. Model weights, runtime, and licence must be checked and documented. Do not require paid APIs or cloud inference. Keep retrieval usable without embeddings; SQLite FTS5 plus structured queries is the MVP baseline.

## Implementation status

The assistant workstream is implemented as a standalone package. It currently
uses a **synthetic test-only fixture** because this repository has no platform
backend, database, candidate store or report API. Every fixture response is
labelled `data_provenance_mode=fixture_test_only`.

Verified on 2026-11-15:

- 154 pytest tests pass (125 baseline plus 29 mocked Groq provider tests).
- 26/26 evaluation questions pass in deterministic fallback mode.
- SQLite FTS5 ingests 9 corpus documents / 38 chunks with no failures.
- Ollama 0.40.16 is installed; `qwen3:4b-instruct-2507-q4_K_M` (ID
  `0edcdef34593`, 2.5 GB) is pulled, and real local inference is recorded in
  `docs/llm/EXPERIMENT_LOG.md`.
- Optional hosted Groq inference is implemented and covered by mocked HTTP
  tests. **No live Groq request has been made** because no API key was
  available. Ollama remains the default provider.

## Run locally

```powershell
cd planetary_analog_llm_workstream
python scripts/ingest_corpus.py
python scripts/run_assistant.py --host 127.0.0.1 --port 8000
```

Routes:

- `POST /api/assistant/chat`
- `POST /api/assistant/explain-report`
- `GET  /api/assistant/health`
- `POST /api/assistant/feedback`
- `POST /api/assistant/places/search` (natural-language place retrieval)
- `POST /api/assistant/images/search` (NASA Image Library / GIBS / PDS)

## Test and evaluate

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'   # required on this machine
python -m pytest -p no:warnings
python -m ruff check .
python scripts/run_evaluation.py
```

Model mode (requires Ollama and the configured model):

```powershell
python scripts/run_evaluation.py --use-model --ollama-url http://127.0.0.1:11434
```

## Configuration

Inference provider: `ASSISTANT_LLM_PROVIDER=ollama` (default) or `groq`
(optional hosted provider). Groq additionally reads `GROQ_API_KEY`,
`GROQ_MODEL`, `GROQ_BASE_URL` and `GROQ_TIMEOUT_S` from the server
environment. The key is never returned or logged. See
`docs/llm/PROVIDER_CONFIGURATION.md`.

All other settings are environment-overridable with `ASSISTANT_`:

| Variable | Default |
|---|---|
| `ASSISTANT_DB_PATH` | `data/assistant.db` |
| `ASSISTANT_STRUCTURED_BACKEND` | `fixture` (`fixture`, `json_export`, `postgres`, `team_backend`) |
| `TERRATWIN_BACKEND_URL` | `http://localhost:8000` (team Node/Express read-only API) |
| `ASSISTANT_TEAM_BACKEND_TIMEOUT_S` | `10` |
| `ASSISTANT_ALLOW_FIXTURE_DATA` | `true` (set `false` outside development) |
| `ASSISTANT_LLM_PROVIDER` | `ollama` (`ollama`, `groq`) |
| `GROQ_API_KEY` | unset (optional; server-side only) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` |
| `GROQ_TIMEOUT_S` | `60` |
| `ASSISTANT_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` |
| `ASSISTANT_OLLAMA_MODEL` | `qwen3:4b-instruct-2507-q4_K_M` |
| `ASSISTANT_OLLAMA_FALLBACK_MODEL` | `qwen2.5:3b-instruct-q4_K_M` |
| `ASSISTANT_OLLAMA_NUM_CTX` | `8192` |
| `ASSISTANT_OLLAMA_TEMPERATURE` | `0.0` |

## Documentation

See `docs/llm/` for architecture, RAG pipeline, model selection, prompt design,
evidence schema, API contract, scientific guardrails, evaluation, known
limitations, experiment log, task tracker and activity log.
