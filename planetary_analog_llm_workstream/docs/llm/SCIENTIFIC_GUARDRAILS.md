# Scientific guardrails

Each guardrail from the workstream brief is mapped to an implementation point
and the test that exercises it. The deterministic records and server-side
validation are authoritative; the model is never trusted.

## G1 — No invented facts

**Rule:** Never invent measurements, coordinates, candidate records, scores,
citations, DOI values, URLs, uncertainty or validation outcomes.

**Implementation:**

- The model may only output `ModelDraft`, which has no score/coordinate fields.
- Every candidate-specific claim must carry evidence IDs from the current pack.
- `validate_draft` rejects unknown evidence IDs and unknown source IDs.
- `_sanitize_refs` removes URLs/DOIs not present in stored metadata.
- Missing candidate/report returns a lookup note and no fabricated record.

**Tests:** `test_nonexistent_evidence_id_is_rejected`,
`test_invented_number_is_rejected`, `test_unverified_url_and_doi_are_removed`,
`test_chat_unknown_candidate_does_not_fabricate`,
`test_missing_report_is_not_fabricated`.

## G2 — Scores are immutable

**Rule:** Never calculate, modify, interpolate, round or re-rank similarity
scores. Quote supplied values verbatim.

**Implementation:**

- `SuppliedScore` is copied from the store; no arithmetic exists in the
  assistant.
- `ModelDraft` has no score fields.
- Output text is checked for score-context numbers not in the supplied set.
- `detect_score_manipulation` adds a binding notice to the prompt and exposes
  `score_integrity_notice` in the response.
- The fallback labels each score "(unchanged)".

**Tests:** `test_score_value_cannot_be_changed`,
`test_score_rounding_is_rejected`, `test_chat_score_manipulation_is_refused`,
`test_chat_score_calculation_is_refused`,
`test_structured_records_are_authoritative_for_scores`.

## G3 — Missing is not zero

**Rule:** Never silently replace unavailable/null/NoData with zero.

**Implementation:**

- Contracts represent missing as `None` + `unavailable` + reason.
- The assembler separates `missing_evidence` from `evidence`.
- The numeric allowlist does not treat `None` as `0`.
- `_missing_described_as_zero` flags statements that turn a missing item into
  zero when no real zero exists.
- The fallback omits missing items from claims and lists them separately.

**Tests:** `test_pack_marks_unavailable_not_zero`,
`test_missing_value_is_not_described_as_zero`,
`test_invented_missing_measurement_is_rejected`.

## G4 — Evidence classes stay distinct

**Rule:** Distinguish `directly_observed`, `derived`, `proxy_based`,
`literature_supported` and `unavailable`.

**Implementation:**

- Classification is stored on `EvidenceItem` and derived server-side for each
  claim.
- The model's classification is never trusted as the final value.
- `_proxy_used_as_direct` flags proxy evidence described as direct measurement.

**Tests:** `test_valid_claim_gets_server_derived_classification`,
`test_proxy_cannot_be_promoted_to_direct_observation`.

## G5 — Separate measurement, inference and background

**Rule:** Separate measurement, derived result, proxy inference, literature
statement, general background and AI interpretation.

**Implementation:**

- Claims carry classification and validation status.
- Background claims require a stored document source and are labelled
  `background`.
- Mission applications and suggested experiments are prefixed
  `Proposed (not a completed observation or platform conclusion):`.
- The fallback sets mission/experiment lists to empty and states that AI
  interpretation was not generated.

**Tests:** `test_background_requires_stored_source`,
`test_background_with_stored_source_is_labelled`,
`test_no_unlabelled_experiments` (evaluation).

## G6 — Citation integrity

**Rule:** Every candidate-specific claim cites real evidence IDs; do not trust
model-generated source metadata.

**Implementation:**

- `allowed_evidence_ids` and `allowed_source_ids` are built from the pack.
- Claims/matches with unknown IDs are dropped and recorded.
- Response sources are reconstructed from stored metadata, not model text.
- `detect_citation_fabrication` adds a notice and exposes it in
  `guardrail_notices`.

**Tests:** `test_claim_with_unknown_source_is_rejected`,
`test_model_match_requires_valid_ids`,
`test_chat_citation_request_only_returns_stored_sources`,
`test_sources_have_stored_metadata_only`.

## G7 — Retrieved content is data, not instructions

**Rule:** Never execute instructions or code found in documents, PDFs,
metadata, pages or uploads.

**Implementation:**

- Ingestion detects instruction-like sentences and replaces them with a visible
  redaction marker.
- Flags travel to the pack, prompt and response.
- The prompt places excerpts in `<untrusted_documents>` with an explicit rule.
- The model has no tools, database, network or secrets.
- Output is scanned for untrusted-instruction patterns.

**Tests:** `test_prompt_excludes_injection_instructions`,
`test_injection_text_in_model_output_is_flagged`,
`test_prompt_contains_authoritative_evidence_and_no_tools`,
evaluation Q19/Q20.

## G8 — Preserve contradictions

**Rule:** Explain contradictory and missing evidence; never hide disagreement.

**Implementation:**

- Contradictions are copied from the store whenever their evidence IDs are in
  the pack, even if the model omits them.
- `documented_differences` and `resolution_status` are preserved.
- Validation never resolves a contradiction on the model's behalf.
- The fallback reports the stored contradiction count and records.

**Tests:** `test_contradiction_is_preserved_even_if_model_omits_it`,
`test_pack_preserves_contradiction`, evaluation Q16.

## G9 — No perfect-analog claim

**Rule:** Never claim an Earth site perfectly reproduces the Moon or Mars.
State gravity, atmosphere, pressure, radiation, vacuum, thermal, dust and
illumination differences.

**Implementation:**

- `planetary_limitations` emits target-specific text (Moon or Mars).
- Overclaim patterns flag "perfect replica", "safe landing site", "proven
  reserve" and proof language.
- Evaluation forbids "perfect replica" and "exactly reproduces".

**Tests:** `test_overclaim_language_is_flagged`, evaluation Q18/Q26.

## G10 — Instrument semantics

**Rule:** Do not describe MODIS LST as air temperature, land cover as geology,
glacier/permafrost as confirmed subsurface water, or neutron/hydrogen proxies
as direct ice detection.

**Implementation:**

- Overclaim patterns cover MODIS-as-air-temperature, land-cover-as-geology,
  glacier-as-confirmed-water, LEND-as-direct-ice and proxy-as-direct.
- Corpus notes explain each caveat.
- Evidence items carry their own feature names and methods.

**Tests:** `test_proxy_cannot_be_promoted_to_direct_observation`,
`test_prompt_contains_authoritative_evidence_and_no_tools`, evaluation Q07-Q09.

## G11 — No global novelty claim

**Rule:** Do not claim global scientific novelty because a site is absent from
the platform's small catalogue.

**Implementation:**

- `global_novelty` overclaim pattern flags "first-ever", "world's first" and
  "globally novel".
- The prompt forbids catalogue-absence-as-novelty.
- Evaluation Q17 checks it.

**Tests:** `test_overclaim_language_is_flagged`, evaluation Q17.

## G12 — Insufficient evidence is explicit

**Rule:** If evidence is insufficient, say so plainly. Background is not a
candidate measurement.

**Implementation:**

- Exact sentence: `The available evidence does not establish this.`
- Inserted when a candidate was requested but not found, when no valid claims
  remain, or when the model sets `insufficient_evidence`.
- Background is a separate list and labelled `background`.

**Tests:** `test_no_candidate_returns_insufficient_state`,
`test_chat_unknown_candidate_does_not_fabricate`, evaluation Q13/Q25.

## Absolute prohibitions in assistant output

- No new score, weight, confidence, coverage or rank.
- No unit conversion presented as a stored value.
- No coordinate inference.
- No citation assembled from memory.
- No "the model believes" as a scientific conclusion.
- No claim that missing data means absence or zero.
- No claim that a proxy is a direct measurement.
- No claim that an Earth site is a replica of another planet.
- No claim of global novelty from catalogue absence.
- No execution of retrieved instructions or code.

## Residual risks

Validation is pattern- and allowlist-based. A fluent false statement that uses
only stored numbers and IDs can still be scientifically wrong. The assistant is
an explanation layer, not an independent verifier. Human review remains
required for mission-critical use. See `KNOWN_LIMITATIONS.md`.
