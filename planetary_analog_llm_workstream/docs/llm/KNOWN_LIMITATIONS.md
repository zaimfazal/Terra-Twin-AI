# Known limitations

Recorded only where observed in this repository. Each entry states impact and
next action.

## Data and integration

### L1 — No real platform records or APIs

- **Affected:** all structured retrieval.
- **Observed:** the repository contains no platform backend, database,
  candidate store or report API. Only synthetic fixtures exist.
- **Impact:** no end-to-end test against real scientific records; scores and
  evidence are fixture values, not measurements.
- **Workaround:** `JsonRecordAdapter` reads a platform export; responses are
  labelled `fixture_test_only` for the fixture.
- **Next action:** backend owner supplies the read-only contract in
  `API_CONTRACT.md`.

### L2 — Postgres adapter is not implemented

- **Affected:** `AssistantService._build_adapter`.
- **Observed:** `structured_backend="postgres"` raises `AdapterUnavailable`.
- **Impact:** production database integration is unavailable.
- **Next action:** implement against owner-confirmed read-only views.

### L3 — Single-candidate evidence pack

- **Affected:** comparison questions.
- **Observed:** `EvidencePack` holds one candidate. A question naming two
  candidates resolves the first and adds a lookup note stating that no
  cross-candidate comparison or ranking was performed.
- **Impact:** Q14 cannot perform a true two-candidate comparison.
- **Next action:** design a multi-candidate pack with explicit, separate score
  blocks; do not rank.

### L4 — Corpus is small and internal

- **Affected:** background retrieval.
- **Observed:** 9 documents, 38 chunks, written for this workstream.
- **Impact:** FTS5 coverage of scientific literature is narrow; absence from
  the corpus is not evidence of absence.
- **Next action:** ingest licensed sources with verified metadata and hashes.

## Retrieval

### L5 — Lexical retrieval only

- **Affected:** `DocumentStore.search`.
- **Observed:** FTS5 keyword matching; no embeddings or semantic search.
- **Impact:** paraphrases and synonyms can miss relevant background.
- **Workaround:** structured evidence is fetched by ID, not by search.
- **Next action:** optional local embeddings, evaluated against the same
  guardrail suite.

### L6 — FTS5 dependency

- **Affected:** document retrieval.
- **Observed:** SQLite must be built with FTS5. Health reports availability.
- **Impact:** if unavailable, background retrieval fails explicitly.
- **Next action:** document the deployment requirement; fail fast at startup.

### L7 — No page numbers for non-PDF sources

- **Affected:** source references.
- **Observed:** `page` is populated only from PDF page iteration.
- **Impact:** Markdown/JSON/CSV citations have section but no page.
- **Next action:** none unless page-level provenance is required; never invent
  page numbers.

## Model and generation

### L8 — Small local model

- **Affected:** model-mode answers.
- **Observed:** 4B parameters at Q4_K_M.
- **Impact:** weaker instruction following and synthesis than larger models;
  more likely to need the fallback.
- **Mitigation:** strict schema, validation, low temperature, fixed seed,
  evidence-only fallback.
- **Next action:** evaluate larger models only if hardware allows.

### L9 - Context is capped below the model maximum

- **Affected:** prompt size.
- **Observed:** `num_ctx=8192` while the model supports 256K. The first real
  prompt was 9,593 tokens and Ollama rejected it with
  `request (9593 tokens) exceeds the available context size (8192 tokens)`.
- **Impact:** evidence packs must fit the working window; a 16K context loaded
  at 5.4 GB and ran mostly on CPU (403 s per answer), so raising it is not free.
- **Mitigation:** compact evidence projection and a 26,000-character prompt
  budget test; the fixture prompt measured 24,386 characters.
- **Next action:** enforce a token-level budget before generation and fail with
  a clear, evidence-preserving error instead of truncating.

### L10 - Model latency and hardware variance

- **Affected:** response time.
- **Observed:** on the development machine (GTX 1650 4 GB, 8 GB RAM, Ollama
  0.40.16) answers took **203-301 s** at 8K context and **403 s** at 16K. The
  8K model load reported 4.2 GB and about 45% CPU / 55% GPU.
- **Impact:** slow responses on CPU-only or low-VRAM machines; the evaluation
  suite is correspondingly slow.
- **Mitigation:** 600 s default timeout, configurable; deterministic fallback
  when inference is unavailable or times out.
- **Next action:** benchmark on target hardware; consider a smaller model or
  prefix caching for interactive use.

### L11 — Model output may be malformed

- **Affected:** generation.
- **Observed:** tested with a stub returning prose and schema-invalid JSON.
- **Impact:** response falls back to retrieval-only.
- **Next action:** keep parser strict; never repair by inventing fields.

### L12 — Prompt injection defence is pattern-based

- **Affected:** ingestion and output scanning.
- **Observed:** known patterns are redacted/flagged.
- **Impact:** novel or obfuscated instructions may not be detected.
- **Mitigation:** documents are delimited and the model has no tools or secrets.
- **Next action:** adversarial red-team set; do not claim complete protection.

## Validation

### L13 — Numeric validation is allowlist-based

- **Affected:** `numeric_mismatches`.
- **Observed:** numbers with recognised units and score-context numbers are
  checked against the pack; unitless numbers outside score context may pass.
- **Impact:** a false statement using only stored numbers can pass.
- **Next action:** add semantic claim verification or human review.

### L14 — Pattern-based overclaim detection

- **Affected:** `OVERCLAIM_PATTERNS`.
- **Observed:** fixed regexes for known overclaims.
- **Impact:** paraphrased overclaims may be missed.
- **Next action:** expand patterns from evaluation failures; consider a
  classifier only if it remains local and testable.

### L15 — No independent scientific verification

- **Affected:** all answers.
- **Observed:** the assistant explains supplied records; it does not verify the
  science or the deterministic engine.
- **Impact:** wrong source records produce wrong explanations.
- **Next action:** human scientific review for mission decisions.

## API and operations

### L16 — No auth, rate limiting or multi-tenancy

- **Affected:** FastAPI routes.
- **Observed:** routes are additive and unauthenticated.
- **Impact:** not production-ready as exposed.
- **Next action:** place behind the platform's existing auth/gateway.

### L17 — No streaming

- **Affected:** chat/explain routes.
- **Observed:** responses are returned after full validation.
- **Impact:** higher perceived latency.
- **Next action:** stream only after validation, or stream status events.

### L18 — SQLite single-writer

- **Affected:** ingestion/feedback.
- **Observed:** local SQLite file.
- **Impact:** concurrent ingestion and high write volume are limited.
- **Next action:** keep retrieval read-mostly; rebuild offline.

### L19 — No automated corpus refresh

- **Affected:** ingestion.
- **Observed:** explicit script/auto-ingest on startup.
- **Impact:** corpus can become stale.
- **Next action:** scheduled ingestion with hash/version checks.

## Evaluation

### L20 — Synthetic fixture only

- **Affected:** evaluation.
- **Observed:** 2 candidates, 2 reports, 16 evidence items, all synthetic.
- **Impact:** results demonstrate guardrail behaviour, not Mars science.
- **Next action:** run against real exports when available.

### L21 — Model-mode results are machine-specific

- **Affected:** reproducibility.
- **Observed:** results depend on Ollama version, model digest, GPU/CPU and
  context settings.
- **Impact:** another machine may differ.
- **Next action:** record runtime, model digest and hardware with every run.
