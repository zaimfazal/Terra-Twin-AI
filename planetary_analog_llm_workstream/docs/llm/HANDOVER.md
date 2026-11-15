# Handover — Terra Twin AI workstream

Updated: 2026-11-15. Read this first if you are a different coding agent
continuing this workstream.

## Current state

| Item | Value |
|---|---|
| Repository | `https://github.com/zaimfazal/Terra-Twin-AI` |
| Local root | `C:\Users\Zaim\Desktop\Terra Twin` |
| Python workstream | `planetary_analog_llm_workstream/` |
| Active branch | `feat/team-integration-place-image-groq` |
| Baseline before this branch | `250685e` (pushed) |
| Phase 0 audit | `7dc8b58` — branch starts here effectively |
| Groq provider | `e96f07a` — `feat: add optional Groq hosted inference provider` |
| Groq tests | `0b332f1` — `test: add mocked Groq provider and fallback tests` |
| Docs milestone | `c215ff1` — `docs: complete provider and retrieval documentation` |
| Pushed | see the "Pushed" row after `git log`; the branch is pushed when `git ls-remote` shows this SHA |

Verify before trusting this table:

```powershell
cd "C:\Users\Zaim\Desktop\Terra Twin"
git status --short --branch
git log -8 --oneline
```

## Current verified results (2026-11-15, this working tree)

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest -p no:warnings` (with plugin autoload disabled) | **154 passed** |
| Lint | `python -m ruff check .` | **All checks passed!** |
| Evaluation (fallback) | `python scripts/run_evaluation.py` | **26/26 passed**, `eval-20261115T112417Z-evidence_only_fallback.json` (latest copy in `latest.json`) |
| Live Groq inference | — | **not tested**: no `GROQ_API_KEY` present, no `.env` file |
| Live Ollama inference | — | last verified 2026-11-14 (`EXPERIMENT_LOG.md` Runs 8–10) |

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is required on this machine: a globally
installed `logfire` pytest plugin fails with an `_ExtendedAttributes`
ImportError. It is an environment issue, not a project dependency.

## What is implemented

### 1. Scientific research assistant (complete)

Pydantic contracts, read-only JSON/fixture and team backend adapters, document
ingestion, SQLite FTS5, evidence-pack assembly, missing-evidence and
contradiction handling, evidence-ID/source/numerical validation, score
immutability, prompt-injection handling, deterministic evidence-only fallback,
FastAPI routes, automated evaluation. See `ARCHITECTURE.md`.

### 2. Place retrieval (complete, mocked backend)

`assistant/retrieval/query_parser.py`, `assistant/places/contracts.py`,
`assistant/places/service.py`; route `POST /api/assistant/places/search`.
Filters only documented fields; missing metrics exclude and are reported, never
zeroed; order preserved; no ranking. Documented in `PLACE_RETRIEVAL.md`.

### 3. Image retrieval (complete, mocked providers)

`assistant/images/` with NASA Image and Video Library, GIBS (Earth only) and PDS
(Moon/Mars only); URL/SSRF validation, dedupe, attribution, missing previews,
provider isolation. Route `POST /api/assistant/images/search`. No score field
exists. Documented in `IMAGE_RETRIEVAL.md` and `IMAGES.md`.

### 4. Inference providers (complete; Groq mocked only)

| File | Purpose |
|---|---|
| `assistant/llm/types.py` | Shared `ModelResponse` / `ModelUnavailable` |
| `assistant/llm/ollama.py` | Local default provider, unchanged behaviour |
| `assistant/llm/groq.py` | Optional hosted Groq provider (OpenAI-compatible) |
| `assistant/llm/provider.py` | `build_llm_client`, `provider_health_payload` |
| `assistant/llm/generation.py` | Provider-neutral generate → parse → validate → fallback |

- `ASSISTANT_LLM_PROVIDER=ollama` (default) or `groq`.
- Groq reads `GROQ_API_KEY` (a `SecretStr`), `GROQ_MODEL`
  (default `openai/gpt-oss-120b`), `GROQ_BASE_URL`, `GROQ_TIMEOUT_S`.
- Structured output uses `response_format: json_schema` (best-effort, because
  `ModelDraft` has optional fields); a model that rejects `json_schema` is
  retried once in JSON-object mode. Validation is always server-side.
- Records the model ID the provider actually returned, plus token usage, and
  sets `model_provider` on the answer.
- 401/403/429/404, timeout, network failure, missing key, malformed envelope and
  invalid content all raise `ModelUnavailable` → deterministic fallback.
- The API key is never logged, returned, serialised or included in `repr`.

Configuration and secret handling: `PROVIDER_CONFIGURATION.md`.
Provider comparison and licence notes: `MODEL_SELECTION.md`.

## Remaining work (in priority order)

1. **Push the branch.** `git push -u origin feat/team-integration-place-image-groq`.
   Do not force-push. Never push to `FM9447/TerraTwin---space-apps`.
2. **Live Groq smoke test** (blocked on credentials). When a key is supplied:
   set `GROQ_API_KEY` in the environment or an untracked `.env`, then run one
   small `GroundedGenerator.generate` request, record the actual model ID,
   token usage and latency in `EXPERIMENT_LOG.md`, and verify the returned
   evidence IDs pass validation. Do not claim this before it happens.
3. **Live team backend verification.** No Node/MongoDB backend has been
   exercised; all adapter, place and image tests use mocked HTTP. Run a
   read-only smoke test against the deployed backend and record exact outcomes.
4. **PDS ODE live shape** remains unverified; the parser is defensive.
5. **GIBS** WMS URLs are validated but not fetched server-side.
6. **Node gateway patch** is owned by the team repository (read-only here). The
   design and the browser-to-Groq boundary are in `TEAM_INTEGRATION.md`.
7. Optional: re-run a model-backed evaluation after any prompt change, and keep
   model-mode and fallback results distinct.

## Blockers

- No `GROQ_API_KEY` in this environment → no live hosted inference test.
- No local MongoDB/Atlas URI and no running Node backend → mocked integration
  tests only. `MONGODB_URI` must never enter this repository.
- The "step-by-step project guide" PDF was never found in either repository.
  Only `planetary_analog_llm_workstream/reference/planetary_analog_discovery_prd.docx`
  and the root `_prd.txt` exist. Do not invent its contents.
- The team repository is a read-only sibling clone. Do not modify it, nest it or
  add it as a submodule.

## Non-negotiable guardrails

- Never invent measurements, coordinates, candidates, sources, DOIs, image
  records, dates, model IDs or scores.
- Never change, round, rescale or re-rank a supplied score.
- Missing is not zero; unsupported is not a negative match.
- Preserve evidence classes, contradictions and provenance.
- Exact insufficient-evidence sentence:
  `The available evidence does not establish this.`
- Never claim visual similarity proves geological equivalence.
- Never put MongoDB credentials or provider keys in this repository, a response
  or a log.
- Keep Ollama the default; Groq optional and never required.
- Existing response validation is the final gate for every provider.

## Files added or changed on this branch (cumulative)

Added:

- `assistant/adapters/team_records.py`, `assistant/adapters/team_backend.py`
- `assistant/retrieval/query_parser.py`
- `assistant/places/contracts.py`, `assistant/places/service.py`
- `assistant/images/contracts.py`, `validation.py`, `orchestrator.py`,
  `providers/{base,nasa_library,gibs,pds}.py`
- `assistant/llm/types.py`, `assistant/llm/groq.py`, `assistant/llm/provider.py`
- `tests/test_team_backend_adapter.py`, `tests/test_place_search.py`,
  `tests/test_images.py`, `tests/test_groq_provider.py`
- `docs/llm/{TEAM_INTEGRATION,ROADMAP,IMAGES,IMPLEMENTATION_ROADMAP,PLACE_RETRIEVAL,IMAGE_RETRIEVAL,PROVIDER_CONFIGURATION}.md`
- `.gitignore`, `.env.example`

Modified:

- `assistant/config.py` (team backend + provider settings, `SecretStr` key)
- `assistant/contracts.py` (`model_provider`)
- `assistant/llm/generation.py` (provider selection, metadata, generic health)
- `assistant/llm/ollama.py` (uses shared types; health reports provider)
- `assistant/service.py` (provider-aware health, structured backend status)
- `assistant/api.py` (place/image routes, lifespan close)
- `scripts/run_evaluation.py` (`--provider`)
- `README.md`, and the docs set: `ARCHITECTURE`, `API_CONTRACT`,
  `MODEL_SELECTION`, `TASKS`, `KNOWN_LIMITATIONS`, `EVALUATION`,
  `EXPERIMENT_LOG`, `HANDOVER`, `AGENT_ACTIVITY`

## Exact commands to resume

```powershell
cd "C:\Users\Zaim\Desktop\Terra Twin"
git status --short --branch
git log -8 --oneline

cd planetary_analog_llm_workstream
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -p no:warnings
python -m ruff check .
python scripts/run_evaluation.py
```

Optional model-backed evaluation:

```powershell
# local, verified previously
python scripts/run_evaluation.py --use-model --ollama-url http://127.0.0.1:11434

# hosted, requires GROQ_API_KEY set server-side
python scripts/run_evaluation.py --use-model --provider groq
```

## Commit discipline

Commit each completed, tested milestone on the existing feature branch. Run the
tests and Ruff first, inspect `git diff`, check for secrets, and update
`HANDOVER.md` and `AGENT_ACTIVITY.md`. Never reset, clean or discard uncommitted
work; never force-push.
