# Agent activity log

Entries record work sessions, decisions, commands, exact outcomes, blockers and
next dependencies. No secrets are recorded.

---

## Session 2026-11-14 — resumed implementation and verification

### Start state

- Assistant package, fixture, corpus, tests and six test modules existed.
- `tests/test_generation.py` had been written but not run.
- Evaluation had 20 questions and no runner.
- Required documentation was incomplete; four files were placeholders.
- Ollama was not installed; no model inference had been tested.

### Work performed

1. Ran `tests/test_generation.py`: 7/8 passed. One assertion expected the word
   "malformed" but the parser correctly returned "no JSON object found in model
   output". Updated the test to assert the specific parser message. Result:
   8/8 passed.
2. Extended the corpus of evaluation questions from 20 to 26, adding:
   background, missing-vs-zero, evidence classification, dataset provenance,
   missing report and Moon-target comparison. Added machine-checkable `checks`.
3. Wrote `scripts/run_evaluation.py` with invariant checks and per-question
   checks, deterministic fallback mode and a loud `--use-model` mode.
4. First evaluation run: 25/26. Q12 failed because
   `detect_citation_fabrication` did not match the plural "citations".
   Fixed the regex to accept singular/plural citations, references, DOIs,
   papers and sources; also fixed the loader's analogous pattern.
   Added a regression test. Rerun: 26/26. Final rerun after negation handling:
   `evaluation/results/eval-20261114T132816Z-evidence_only_fallback.json`.
5. Closed additional gaps found while evaluating:
   - added "calculate" to score-manipulation verbs;
   - surfaced citation and injection notices in `guardrail_notices`;
   - rejected foreground claims that cite unknown source IDs;
   - added a transparent lookup note when a question names multiple candidate
     IDs (one candidate pack per answer; no comparison/ranking).
6. Added tests for unknown source rejection, calculate/citation detection,
   citation guardrail notice, and multi-candidate limitation.
7. Ran full pytest: **70 passed in 7.71s**.
8. Added negation-aware overclaim handling and a regression test, because a
   correct model sentence such as "does not prove" or "not a direct
   measurement" was being falsely flagged. Reran full pytest:
   **71 passed in 7.40s**.
8. Ran `ruff check .`: **All checks passed!** (12 safe autofixes applied:
   import sorting and unused imports; one unused variable was given a real
   validation use).
9. Verified environment: Ollama **0.40.16** installed; GTX 1650 4 GB;
   7.8 GiB RAM; i5-11320H. Verified `qwen3:4b-instruct-2507-q4_K_M` exists in
   the Ollama library (2.5 GB, 256K context) and the Hugging Face model card
   declares Apache-2.0. Started `ollama pull`.
10. Wrote all required documentation files.

### Files changed in this session

- `tests/test_generation.py` — parser error assertion.
- `assistant/evidence/validation.py` — calculate verb, plural citation regex,
  unknown source rejection.
- `assistant/ingestion/loaders.py` — plural citation regex.
- `assistant/contracts.py` — `guardrail_notices` response field.
- `assistant/service.py` — populate citation/injection notices.
- `assistant/evidence/assembler.py` — multi-candidate lookup note.
- `evaluation/questions.jsonl` — 26 questions with checks.
- `evaluation/results/` — recorded failed and passing runs.
- `scripts/run_evaluation.py` — new evaluation runner.
- `tests/test_validation.py`, `tests/test_api.py`, `tests/test_evidence.py` —
  regression tests.
- `docs/llm/ARCHITECTURE.md`, `RAG_PIPELINE.md`, `MODEL_SELECTION.md`,
  `PROMPT_DESIGN.md`, `EVIDENCE_SCHEMA.md`, `API_CONTRACT.md`,
  `SCIENTIFIC_GUARDRAILS.md`, `EVALUATION.md`, `KNOWN_LIMITATIONS.md`,
  `TASKS.md`, `AGENT_ACTIVITY.md` — documentation.
- `docs/llm/EXPERIMENT_LOG.md` — run log.

### Decisions

- Keep fixture data test-only and gated by `ASSISTANT_ALLOW_FIXTURE_DATA`.
- Default evaluation is the deterministic fallback; model mode must fail loudly
  if unavailable, never silently substitute.
- One candidate evidence pack per answer; explicitly state the limitation
  rather than inventing a comparison.
- Do not implement a Postgres adapter or multi-candidate ranking without the
  backend owner's contract.

### Blockers

- No real platform records/API/database. Integration remains a proposed
  contract.
- Model download and inference are recorded in the experiment log; any
  incomplete step is stated there, not claimed as passed.

### Next dependency

Read-only platform export/views and confirmation of ID formats, null semantics,
verbatim score representation and deterministic report ordering.

---

## Session 2026-11-14 - model download and inference verification

Append the exact pull/inference outcomes and files changed after the run. See
`EXPERIMENT_LOG.md` for commands, model digest, latency and evaluation counts.

---

## Session 2026-11-15 — model evaluation results, Phase 0 audit, cleanup

### Start state

- Model-mode evaluation had finished but its result was not recorded in docs.
- `.pyc` files, runtime SQLite databases, temp DBs and PID/log files were
  tracked in Git.
- No branch or commit existed for the place/image retrieval work.
- The team repository had never been inspected.

### Work performed

1. Inspected the model evaluation result files. Recorded the verified outcome:
   **21/26 passed, 5 fallback** (Q22–Q26 fell back when the host slept).
   Model-mode failures: Q02 `text_contains_any`, Q08 `lend_as_direct_ice`,
   Q10 `numeric_claims_valid`, Q17 `global_novelty`, Q21 `background_min`.
   No result was re-run or rewritten. `latest.json` kept as the 173743Z copy.
2. Cloned `FM9447/TerraTwin---space-apps` to
   `C:\Users\Zaim\Desktop\TerraTwin-team-reference` as a read-only sibling
   reference (shallow clone, single commit `202480b`).
3. Audited team models, routes, controllers, engines, seed script, middleware
   and frontend data layer. Verified all ten route paths and their response
   shapes. Found that the frontend imports local data modules and does not call
   the Node API, that `POST /api/analog/search` scores an in-memory catalogue,
   and that `POST /api/analog/image-match` is a heuristic 5-D matcher.
4. Recorded provenance caveats: Mongoose schema defaults
   (`similarity_score: 0`, `data_coverage: 100`, `data_confidence: 95`) are not
   measurements; metrics are 0–100 heuristic indices; catalogue coordinates use
   `{lat, lon}` while MongoDB uses GeoJSON `[lon, lat]`.
5. Created branch `feat/place-and-image-retrieval`.
6. Added `.gitignore`; untracked 26 `.pyc` files, `data/assistant.db`,
   `data/smoke.db` and `evaluation/_tmp_debug.db`; preserved all source, corpus,
   fixtures, evaluation questions and model result JSONs. Generated logs and PIDs
   are now ignored and left on disk.
7. Wrote `docs/llm/TEAM_INTEGRATION.md` and `docs/llm/ROADMAP.md`.

### Files changed in this session

- `.gitignore` — new.
- `docs/llm/TEAM_INTEGRATION.md` — new.
- `docs/llm/ROADMAP.md` — new.
- `docs/llm/EXPERIMENT_LOG.md` — Runs 9 and 10 recorded.
- `docs/llm/ARCHITECTURE.md` — 73 tests, real inference wording.
- `docs/llm/AGENT_ACTIVITY.md`, `TASKS.md`, `HANDOVER.md` — updated.
- `evaluation/results/eval-20261114T173740Z-model.json` — added.
- `evaluation/results/eval-20261114T173743Z-model.json` — added.
- `evaluation/results/latest.json`, `model-eval-console.log` — updated.

### Commands and exact outcomes

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -p no:warnings
# 73 passed in 7.66s
python -m ruff check .
# All checks passed!
git checkout -b feat/place-and-image-retrieval
git commit -m "chore: audit integration repositories and clean generated artifacts"
# 325297d5eb05521cf81afc5149f25310d60108e3
git commit -m "docs: add team integration architecture and implementation roadmap"
# 30ea632
```

### Decisions

- Treat team schema fields as unverified platform values, never as measurements.
- Add a dedicated place/search contract rather than converting heuristic metrics
  into verified `EvidenceItem` measurements.
- Keep Mongo access exclusively in the Node backend; the assistant uses one
  configurable read-only HTTP base URL.
- Document additive team endpoints; do not modify the team repository.
- Do not claim visual similarity as geological equivalence anywhere in the new
  image contracts.

### Blockers

- No live MongoDB/Node backend locally; the team app needs an Atlas URI. All
  adapter work will be tested with mocked HTTP responses only.
- Exact live response shapes beyond code inspection remain unverified.

### Next dependency

Phase 1: implement `assistant/adapters/team_backend.py` with strict timeouts,
response normalisation, verbatim score preservation and mocked tests.

---

## Session 2026-11-15 — Phases 1–7 implementation

### Start state

- Branch `feat/place-and-image-retrieval` at `279ac49`.
- No team backend adapter, no place retrieval, no image retrieval.
- 73 tests passing.

### Work performed

1. **Phase 1** — added `assistant/adapters/team_records.py` (normalised
   read-only records) and `assistant/adapters/team_backend.py` (httpx client for
   the audited Express routes only). Scores keep their original JSON number type;
   missing metrics stay missing; both coordinate shapes are supported; redirects,
   credentials and invalid base URLs are refused; reports and evidence are not
   synthesised. 13 mocked tests.
2. **Phase 2** — added `assistant/retrieval/query_parser.py` (deterministic,
   clause-scoped numeric parsing) and `assistant/places/contracts.py`.
3. **Phase 3** — added `assistant/places/service.py` and
   `POST /api/assistant/places/search`. Unsupported dimensions produce
   `unavailable_fields`; missing metrics exclude a candidate and are reported,
   never treated as zero. 15 tests.
4. **Phase 4–7** — added `assistant/images/`: contracts, URL/SSRF validation,
   NASA Image Library, GIBS (Earth only), PDS (defensive ODE parsing),
   orchestrator and `POST /api/assistant/images/search`. 20 mocked tests.
5. Added `AssistantService.close()` and switched the FastAPI lifespan to it so
   provider HTTP clients and the SQLite store are released.
6. Wrote `docs/llm/IMAGES.md`; updated `API_CONTRACT.md`, `README.md`,
   `TASKS.md` and `HANDOVER.md`.

### Files changed in this session

- `assistant/adapters/team_records.py`, `assistant/adapters/team_backend.py`
- `assistant/places/contracts.py`, `assistant/places/service.py`
- `assistant/retrieval/query_parser.py`
- `assistant/images/contracts.py`, `validation.py`, `orchestrator.py`
- `assistant/images/providers/{base,nasa_library,gibs,pds}.py`
- `assistant/config.py`, `assistant/service.py`, `assistant/api.py`
- `.env.example`, `README.md`
- `tests/test_team_backend_adapter.py`, `tests/test_place_search.py`,
  `tests/test_images.py`
- `docs/llm/{IMAGES.md,API_CONTRACT.md,TASKS.md,HANDOVER.md}`

### Commands and exact outcomes

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -p no:warnings
# 122 passed
python -m ruff check .
# All checks passed!
```

### Decisions

- Place retrieval uses a dedicated contract with provenance and
  `missing_fields`; team metrics are never promoted to `EvidenceItem`
  measurements.
- Qualitative terrain terms fall back to documented 0–100 heuristic indices only
  when the supplied text does not mention the term, with an explicit limitation.
- Numeric ranges are created only from explicitly stated numbers; adjectives
  never become thresholds.
- Image relevance, visual resemblance, geological analogy, environmental
  analogy, scientific similarity and mission usefulness stay separate. The image
  contracts contain no score field at all.
- GIBS is Earth-only and is never used for Moon or Mars; PDS is Moon/Mars-only.
- The GIBS WMS URL is validated but not fetched server-side; the limitation is
  stated in the record and in the docs.
- PDS parsing is defensive because the live ODE response shape is unverified.

### Blockers

- No live MongoDB/Node backend, so all integration tests use mocked HTTP.
- Live PDS ODE and GIBS response shapes remain unverified.
- NASA Image Library does not supply per-item licence or instrument.

### Next dependency

Phase 8 remainder: adversarial metadata, attribution completeness and an
end-to-end mocked places → images test. Then Phase 9 documentation and push.
