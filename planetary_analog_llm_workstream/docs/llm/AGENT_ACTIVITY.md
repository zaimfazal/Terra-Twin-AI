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

## Session 2026-11-14 — model download and inference verification

Append the exact pull/inference outcomes and files changed after the run. See
`EXPERIMENT_LOG.md` for commands, model digest, latency and evaluation counts.
