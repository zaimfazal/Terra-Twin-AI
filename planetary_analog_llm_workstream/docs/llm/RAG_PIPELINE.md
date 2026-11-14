# RAG pipeline

## Overview

The pipeline is deliberately split into deterministic retrieval and constrained
generation. Retrieval never depends on a model. Generation never retrieves.

```
documents -> load -> sanitise -> chunk -> hash -> SQLite/FTS5
records   -> typed read-only adapter ----------------------+
                                                          v
question -> structured lookup + FTS5 search -> evidence pack -> prompt
          -> Ollama JSON generation -> parse -> validate -> answer/fallback
```

## 1. Ingestion

Supported formats: Markdown (`.md`, `.markdown`), plain text (`.txt`), JSON
(`.json`), CSV (`.csv`) and PDF (`.pdf`, requires PyMuPDF).

### Metadata

Metadata is taken only from:

1. a sidecar `<file>.meta.json` (or `<stem>.meta.json`);
2. YAML front matter for Markdown/text;
3. an embedded `_metadata` object for JSON;
4. PDF document metadata (title only, when present).

Allowed fields: `title`, `organization`, `url`, `doi`, `publication_date`,
`licence`, `document_type`, `is_fixture`.

Missing metadata stays `None`. A filename stem is used as a transparent title
fallback and the source is marked `partial`; no author, DOI, date or URL is
inferred. Plain `.txt` without metadata is also `partial`. PDFs without a
sidecar are `partial`.

### Hashing and IDs

- Raw bytes are SHA-256 hashed (`content_hash`).
- `source_id = "SRC-DOC-" + sha256(relative_path)[:12]`, so re-ingesting the
  same path is deterministic and idempotent.
- Re-ingestion updates text/metadata and replaces chunks for that source.

### Chunking

- Markdown is split by headings; the heading becomes `section`.
- Plain text is split near 4,000 characters on paragraph boundaries.
- JSON arrays become one chunk per record; CSV becomes one chunk per row.
- PDFs become one chunk per non-empty page, with the 1-based page number.

### Untrusted-content sanitisation

Instruction-like text in documents is detected and replaced with
`[UNTRUSTED INSTRUCTION REDACTED BY ASSISTANT]`. The document remains
retrievable as data. Detected flags include:

- ignore/disregard previous instructions;
- reveal API keys, passwords, credentials or the system prompt;
- bypass evidence/safety/validation checks;
- fabricate a score or citation;
- role override ("you are now ...");
- mentions of "system prompt".

A document with any flag is marked `quarantined` (or keeps `partial`) and its
flags are attached to every retrieved chunk. The prompt repeats the trust rule
independently, so sanitisation is defence in depth, not the only defence.

## 2. Storage

SQLite database with:

- `sources` — verified metadata, hash, status, flags, fixture marker;
- `chunks` — text, section, page, flags;
- `chunks_fts` — FTS5 index over `title`, `section`, `text` (porter/unicode61);
- `feedback` — usefulness/factual flags and optional comment.

If FTS5 is unavailable, retrieval raises a clear error and health reports
`fts5_available=false`; there is no silent fallback to a different ranking.

### Query

`DocumentStore.search(query, limit)`:

1. builds a safe FTS5 query from alphanumeric tokens;
2. ranks by BM25 with deterministic tie-breaking;
3. excludes sources whose status is `failed`;
4. returns metadata, snippet and security flags with every hit.

No embeddings, vector store or external search service is used. This is the
MVP baseline required by the brief. Adding local embeddings later must not
change ID or score handling.

## 3. Evidence-pack assembly

Order is fixed and testable:

1. Extract explicit `candidate_id` / `report_id` from the request or question.
2. Look up the candidate and/or report in the read-only adapter.
3. If a candidate has no explicit report, take the adapter's first stored
   report (documented deterministic order, not assistant ranking).
4. Resolve the planetary target from the request, report or candidate.
5. Load candidate evidence; split into present and unavailable (`is_missing`).
6. Append evidence IDs listed by the report that are not attached to the
   candidate (defensive).
7. Preserve contradictions only when all their evidence IDs are in the pack.
8. Load dataset source metadata referenced by evidence/report.
9. Copy supplied scores verbatim.
10. If background is enabled, run FTS5 over the question plus target and
    candidate names; attach verified document source metadata.
11. Add provenance warnings, limitations and lookup notes.

The pack is self-contained. Every ID the model may cite is in the pack.

## 4. Prompt assembly

`build_user_prompt` contains, in order:

1. server notices (binding constraints, e.g. score immutability);
2. prior conversation context, explicitly labelled untrusted and non-evidence;
3. the question;
4. the structured evidence pack as JSON;
5. document excerpts inside `<untrusted_documents>`;
6. the `ModelDraft` JSON schema;
7. a final instruction to use only pack IDs and no URLs/DOIs.

The structured pack contains no raw document text; raw text appears only in the
delimited untrusted block.

## 5. Generation

`OllamaClient` posts to `/api/chat` with:

- `stream: false`;
- `format`: the `ModelDraft` JSON schema;
- `temperature` (default 0.0), `num_ctx` (default 8192), `num_predict` (1200),
  `seed` 42;
- `think: false` for non-thinking Qwen3 variants.

If the local server rejects a schema in `format` (older Ollama), it retries
with `format: "json"`. If the configured model is missing, it tries the
configured fallback model. If neither is installed, it raises
`ModelUnavailable` and the deterministic fallback is used.

## 6. Validation and fallback

`parse_draft` rejects non-JSON, fenced/non-JSON text, non-object JSON and
schema violations. `validate_draft` then:

- rejects claims with unknown evidence IDs or no evidence IDs;
- rejects claims with unknown source IDs;
- rejects claims containing numbers not present verbatim in the pack;
- removes unverified URLs/DOIs and flags the response;
- flags proxy-as-direct, missing-as-zero and overclaim language;
- derives classifications from stored evidence, never from the model;
- keeps engine strong/weak labels authoritative;
- preserves stored contradictions and missing entries;
- resolves candidate and target identity server-side;
- prepends the exact insufficient-evidence sentence when required;
- prepends the fixture warning in fixture mode.

If parsing or validation raises, an evidence-only answer is returned. If the
model is unavailable, the same fallback is used. Fallback never interprets,
calculates or proposes experiments.

## 7. Failure modes and current behaviour

| Failure | Behaviour |
|---|---|
| Ollama down / model missing | `generation_mode=evidence_only_fallback`, reason recorded |
| Model returns prose | Fallback, `schema_valid=false` |
| Model invents evidence ID | Claim dropped, `evidence_ids_valid=false` |
| Model invents number/score | Claim dropped or flagged, mismatch recorded |
| Model cites fake URL/DOI | Reference removed, `sources_valid=false` |
| Retrieved document has injection | Sanitised at ingestion, flagged in pack/prompt/response |
| Candidate/report not found | No fabrication; lookup note + insufficient-evidence sentence |
| FTS5 unavailable | Explicit error; health reports false |

## 8. Retrieval limitations

FTS5 is lexical. Synonyms, paraphrases and cross-language questions may miss
relevant background. Structured evidence is unaffected because it is looked up
by ID, not by search. Do not treat retrieved background as candidate-specific
evidence; the response labels it as background.
