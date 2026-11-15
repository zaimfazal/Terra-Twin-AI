# Handover — quota-loss recovery guide

Updated: 2026-11-15. Read this first if you are a different coding agent
continuing this workstream.

## Current state

| Item | Value |
|---|---|
| Repository | `https://github.com/zaimfazal/Terra-Twin-AI` |
| Local root | `C:\Users\Zaim\Desktop\Terra Twin` |
| Branch | `feat/place-and-image-retrieval` |
| Baseline commit | `38d9f62` (merge, `main`) |
| Milestone 1 | `325297d5eb05521cf81afc5149f25310d60108e3` — audit + cleanup |
| Milestone 2 | `30ea632` — integration architecture + roadmap |
| Milestone 3 | `279ac49` — evaluation record + handover |
| Milestone 4 | `5db9a9a` — Phase 1 adapter |
| Milestone 5 | `b5e9396` — Phase 2–3 place retrieval |
| Milestone 6 | `fe87f0f` — Phase 4–7 image retrieval |
| Milestone 7 | `306fac7` — image documentation |
| Milestone 8 | Phase 8 tests — verify with `git log -1` |
| Pushed | no (report status before assuming a remote copy exists) |

## Completed

1. Existing assistant workstream: contracts, adapters, ingestion, SQLite FTS5,
   evidence assembly/validation, deterministic fallback, prompts, Ollama,
   FastAPI routes, 26-question evaluation, documentation.
2. Model evaluation recorded honestly: **21/26 passed in model mode, 5 fallback**
   (Q22–Q26 when the host slept). Model failures Q02, Q08, Q10, Q17, Q21. Not a
   clean model pass; do not re-label it.
3. Phase 0 audit of both repositories, with exact team routes, response shapes,
   model fields and provenance caveats in `TEAM_INTEGRATION.md`.
4. Repository cleanup: `.gitignore` added; `__pycache__`, runtime DBs and temp DBs
   untracked; model evaluation JSONs and console record preserved.
5. Roadmap with phases 1–9 and exit criteria in `ROADMAP.md`.
6. **Phase 1 done**: `assistant/adapters/team_backend.py` and
   `assistant/adapters/team_records.py`, wired through
   `ASSISTANT_STRUCTURED_BACKEND=team_backend`. 13 mocked adapter tests.
7. **Phase 2–3 done**: deterministic place parser, typed contracts, place search
   service and `POST /api/assistant/places/search`, wired to the adapter.
   15 place tests. Full suite: **102 passed**; Ruff clean.
8. **Phase 4–7 done**: NASA Image Library, GIBS (Earth only) and PDS providers,
   URL/SSRF validation, grouping orchestrator and
   `POST /api/assistant/images/search`. 20 mocked image tests.
9. **Phase 8 done**: attribution/identity completeness, injection-as-data, and an
   end-to-end mocked places → images test. Full suite: **125 passed**;
   Ruff clean.

## Files created in this branch

- `.gitignore`
- `planetary_analog_llm_workstream/.env.example`
- `planetary_analog_llm_workstream/assistant/adapters/team_records.py`
- `planetary_analog_llm_workstream/assistant/adapters/team_backend.py`
- `planetary_analog_llm_workstream/tests/test_team_backend_adapter.py`
- `planetary_analog_llm_workstream/assistant/places/contracts.py`
- `planetary_analog_llm_workstream/assistant/places/service.py`
- `planetary_analog_llm_workstream/assistant/retrieval/query_parser.py`
- `planetary_analog_llm_workstream/tests/test_place_search.py`
- `planetary_analog_llm_workstream/assistant/images/contracts.py`
- `planetary_analog_llm_workstream/assistant/images/validation.py`
- `planetary_analog_llm_workstream/assistant/images/orchestrator.py`
- `planetary_analog_llm_workstream/assistant/images/providers/{base,nasa_library,gibs,pds}.py`
- `planetary_analog_llm_workstream/tests/test_images.py`
- `planetary_analog_llm_workstream/docs/llm/IMAGES.md`
- `planetary_analog_llm_workstream/docs/llm/TEAM_INTEGRATION.md`
- `planetary_analog_llm_workstream/docs/llm/ROADMAP.md`
- `planetary_analog_llm_workstream/docs/llm/HANDOVER.md` (this file)

## Files modified in this branch

- `docs/llm/ARCHITECTURE.md` (73 tests, real-inference wording)
- `docs/llm/EXPERIMENT_LOG.md` (Runs 9 and 10 recorded)
- `docs/llm/AGENT_ACTIVITY.md` (2026-11-15 session)
- `docs/llm/TASKS.md` (LLM-017 … LLM-029)
- `docs/llm/HANDOVER.md` (this file)
- `planetary_analog_llm_workstream/assistant/config.py` (team backend settings)
- `planetary_analog_llm_workstream/assistant/service.py` (adapter factory, image
  service, close)
- `planetary_analog_llm_workstream/assistant/api.py` (places + images routes,
  lifespan close)
- `planetary_analog_llm_workstream/README.md` (config table)
- `evaluation/results/latest.json`, `model-eval-console.log`

## Files removed from Git tracking (kept on disk)

- 26 `.pyc` files under `assistant/**/__pycache__` and `tests/__pycache__`
- `planetary_analog_llm_workstream/data/assistant.db`
- `planetary_analog_llm_workstream/data/smoke.db`
- `planetary_analog_llm_workstream/evaluation/_tmp_debug.db`

Generated logs and PID files remain on disk and are ignored.

## Commands executed (verified)

```powershell
git config --get user.name   # zaimfazal
git checkout -b feat/place-and-image-retrieval

$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -p no:warnings
# 122 passed (after Phase 4-7)

python -m ruff check .
# All checks passed!
```

The `PYTEST_DISABLE_PLUGIN_AUTOLOAD` flag is required on this machine because a
globally installed `logfire` pytest plugin fails to import.

## Pending tasks (in order)

1. **Phase 9 (remainder)** — refresh `ARCHITECTURE.md` test count and routes,
   add the gateway notes to `TEAM_INTEGRATION.md`, and record the session in
   `AGENT_ACTIVITY.md`.
2. Push branch to the personal repository if authenticated; otherwise report
   unpushed commits by SHA.
3. Verify the PDS ODE live response shape when network access is available.
   Until then the parser stays defensive and the limitation stays documented.
4. Optional: run one read-only smoke test against the deployed team backend and
   record exact outcomes (never claim it before it happens).

## Blockers

- No live MongoDB or Node backend locally (team app requires an Atlas URI), so
  all integration tests must use mocked HTTP. Do not claim live verification.
- The "step-by-step project guide" PDF was never found. Only
  `planetary_analog_llm_workstream/reference/planetary_analog_discovery_prd.docx`
  and root `_prd.txt` exist. Do not invent its contents.
- Team repository is read-only and must stay a sibling clone at
  `C:\Users\Zaim\Desktop\TerraTwin-team-reference`; never nest it or add it as a
  submodule.

## Non-negotiable guardrails

- Never invent measurements, coordinates, candidates, sources, DOIs, image
  records, dates or scores.
- Never change, round or re-rank a supplied score.
- Missing is not zero; unsupported is not a negative match.
- Preserve evidence classes and contradictions.
- Exact insufficient-evidence sentence:
  `The available evidence does not establish this.`
- Never claim visual similarity proves geological equivalence.
- Never put MongoDB credentials in this repository or in a response.
- Keep Ollama the default; Groq optional and never required.
- Do not modify the team repository or push to `FM9447/TerraTwin---space-apps`.

## Exact command to resume

```powershell
cd "C:\Users\Zaim\Desktop\Terra Twin"
git status
git log -3 --oneline
cd planetary_analog_llm_workstream
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -p no:warnings
```

Then open `docs/llm/ROADMAP.md` at Phase 1 and start there. Commit every
completed milestone with tests and Ruff run first.
