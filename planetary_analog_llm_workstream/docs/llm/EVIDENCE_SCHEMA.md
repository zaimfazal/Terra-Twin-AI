# Evidence schema

All schemas are Pydantic v2 models in `assistant/contracts.py`. Extra fields are
forbidden on records and responses. Missing values are `None`; `0` is a real
supplied value.

## Evidence classes

`EvidenceClassification`:

| Value | Meaning | Assistant rule |
|---|---|---|
| `directly_observed` | Instrument/sample measurement of the feature | May describe as observed, with its source and limitations |
| `derived` | Calculated/indexed from observations | Must say it is derived; do not present as a raw measurement |
| `proxy_based` | Indicator used to infer another property | Must say proxy; never "directly measured" or "proves" |
| `literature_supported` | Statement supported by a publication/report | Attribute to the stored source; not a new measurement |
| `unavailable` | No usable measurement exists | Must remain unavailable; never zero |

An item with `value=None` and `value_text=None` is also treated as missing even
if the classification is inconsistent.

## Structured records

### `Coordinates`

`latitude`, `longitude`, `crs` — all nullable. The assistant never infers or
converts coordinates.

### `TargetRecord`

`target_id`, `name`, `planet` (`Moon`/`Mars`/`Earth`/`other`),
`reference_type`, `mission_profiles`, `is_fixture`.

### `CandidateRecord`

`candidate_id`, `name`, `planet` (Earth), `region_name`, `coordinates`,
`area_km2`, `target_id`, `mission_profiles`, `eligibility_stage`, `is_fixture`.

### `DatasetProvenance`

`source_id`, `dataset_name`, `organization`, `instrument_or_mission`, `version`,
`spatial_resolution`, `temporal_resolution`, `acquisition_date`, `crs`, `units`,
`processing_methodology`, `known_limitations`, `url`, `doi`, `licence`,
`is_fixture`.

Only stored fields are returned. No field is inferred from a filename or URL.

### `SuppliedScore`

`metric` (`overall_similarity`, `dimension_similarity`, `data_coverage`,
`data_confidence`, `other_supplied_metric`), `dimension`, `value`,
`value_text`, `scale`, `source_record_id`, `is_missing`, `missing_reason`.

`value_text` preserves the supplied representation. The assistant copies these
values; it never recalculates, rounds or re-ranks them.

### `EvidenceItem`

`evidence_id`, `candidate_id`, `target_id`, `mission_profile`, `dimension`,
`feature`, `value`, `value_text`, `unit`, `evidence_classification`,
`dataset_source_id`, `source_record_id`, `observed_at`, `spatial_resolution`,
`temporal_coverage`, `method`, `note`, `missing_reason`,
`contradiction_group`, `related_evidence_ids`, `is_fixture`.

### `ContradictionRecord`

`contradiction_id`, `topic`, `evidence_ids`, `description`,
`documented_differences`, `resolution_status` (`unresolved`/`resolved`/
`unknown`).

Contradictions are preserved even if the model omits them. The assistant does
not choose a winner unless the stored record marks a resolution.

### `ReportRecord`

`report_id`, `candidate_id`, `target_id`, `target_name`, `mission_profile`,
`comparison_scale`, `generated_at`, `overall_similarity`,
`dimension_scores`, `data_coverage`, `data_confidence`,
`strong_match_evidence_ids`, `weak_match_evidence_ids`,
`contradiction_evidence_ids`, `missing_evidence_ids`, `dataset_source_ids`,
`limitations`, `provenance_notes`, `is_fixture`.

## Evidence pack

`EvidencePack` is the complete, self-contained model input:

- `pack_id`, `generated_at`, `question`, `data_provenance_mode`;
- `candidate`, `target`, `mission_profile`, `report`;
- `evidence`, `missing_evidence`;
- `contradictions`;
- `scores`;
- `dataset_sources`, `documents`, `document_sources`;
- engine strong/weak match IDs;
- `limitations`, `security_flags`, `lookup_notes`.

Derived helpers:

- `allowed_evidence_ids` = present + missing evidence IDs;
- `allowed_source_ids` = dataset + document source IDs.

## Model draft

`ModelDraft` is the only output requested from the model. It contains **no
score, coverage, confidence, rank or eligibility fields**. See
`PROMPT_DESIGN.md`.

## Public response

`AssistantAnswer`:

- `question`, `answer_summary`, `planetary_target`, `earth_candidate_id`;
- `claims`, `strong_matches`, `weak_matches`;
- `contradictory_evidence`, `missing_evidence`;
- `analogy_limitations`, `mission_applications`, `suggested_experiments`,
  `uncertainties`;
- `sources`, `background`;
- `insufficient_evidence`;
- `supplied_scores` (verbatim);
- `data_provenance_mode`, `generation_mode`;
- `validation` (`ValidationReport`);
- `score_integrity_notice`, `guardrail_notices`;
- `response_id`, `pack_id`, `model`, `prompt_version`, `disclaimer`.

### `ValidationReport`

- `schema_valid`
- `evidence_ids_valid`
- `sources_valid`
- `numeric_claims_valid`
- `score_immutability_valid`
- `rejected_claim_count`
- `rejected_evidence_ids`
- `rejected_source_ids`
- `numeric_mismatches`
- `overclaim_flags`
- `untrusted_instruction_flags`
- `errors`

A false flag means the public answer was reduced or flagged; rejected evidence
IDs are never silently shown as validated.

## Missing versus zero

Example from the test fixture:

- `EV-C1-010` mineral abundance: `value=null`, `unavailable` — not zero.
- `EV-C1-011` subsurface water ice: `value=null`, `unavailable` — not zero.
- `EV-C1-012` mapped surface-water extent: `value=0.0`, `km2`,
  `directly_observed` — a real supplied zero.

Validation flags any statement that turns a missing item into zero and rejects
claims that quote a number not present verbatim in the pack.

## Source references

`SourceReference` contains only stored metadata: `source_id`, `title`,
`organization`, `url`, `doi`, `page`, `section`, `licence`, `source_kind`
(`dataset`/`document`), `is_fixture`.

Model-generated URLs/DOIs are removed and the response is marked
`sources_valid=false`. Page numbers exist only where the loader read them from
a PDF; they are never invented.
