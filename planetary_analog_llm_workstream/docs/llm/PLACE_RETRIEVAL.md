# Place (candidate) retrieval

Route: `POST /api/assistant/places/search`
Implementation: `assistant/retrieval/query_parser.py`,
`assistant/places/contracts.py`, `assistant/places/service.py`
Backend: the team's read-only Express API (`TeamBackendAdapter`)

Place retrieval answers "which existing Analog records match this description?".
It does **not** ask the language model anything. The query is parsed with
deterministic rules, filters are applied to fields that exist in the team's
`Analog` records, and supplied values are echoed verbatim.

## What it does not do

- No new scientific score, coverage, confidence or ranking is calculated.
- No candidate, coordinate, measurement, dataset or target is invented.
- No LLM interpretation is added to the result list.
- Backend order is preserved (`ordering: "backend_order_preserved"`), so the
  response is a filter result, not a "best match" list.

## Request

```json
{
  "question": "Find arid volcanic terrain in Iceland above 60 roughness",
  "target": null,
  "planetary_reference": null,
  "filters": null,
  "max_results": 10,
  "offset": 0
}
```

`question` or `filters` is required. `max_results` is 1–50. `offset` pages the
filtered list. `planetary_reference` is one of `Earth`, `Moon`, `Mars`.

### Explicit filters

`CandidateSearchFilters` (all optional):

| Field | Type | Applied to |
|---|---|---|
| `text_terms` | `list[str]` | candidate ID, name, country, morphology, planet analog, target ID, breakdown values, dataset names |
| `countries` | `list[str]` | `country` |
| `primary_planet_analogs` | `list[str]` | `primaryPlanetAnalog` |
| `target_ids` | `list[str]` | `targetMatchId` |
| `dataset_terms` | `list[str]` | `nasaDatasetsUsed` names |
| `metrics` | `dict[metric, {minimum, maximum}]` | documented 0–100 platform indices only |
| `bounding_box` | `{min_latitude, max_latitude, min_longitude, max_longitude}` | stored coordinates |
| `radius` | `{latitude, longitude, radius_km}` | stored coordinates, haversine, max 20,000 km |

### Metrics that can be filtered numerically

`roughness`, `relief`, `slope`, `aridity`, `thermal`, `rockiness`, `volcanic`,
`access` — each a **0–100 heuristic platform index** from the team's
similarity engine, not a physical measurement and not a percentage.

Numerals are only turned into a range when the user states them explicitly
("roughness above 60", "slope between 20 and 40"). Adjectives never become
numeric thresholds. A range carries `unit="platform_index_0_100"`.

Numeric ranges are clause-scoped: a number attached to one dimension is not
applied to another. Ranges with `minimum > maximum` are rejected by validation.

### Text matching

Text terms are matched case-insensitively as substrings against the record
fields listed above. A small, documented synonym table (`TEXT_SYNONYM_GROUPS`)
expands common terrain words (for example arid/dry/desert). There are no
embeddings and no semantic similarity.

Qualitative terms that also have a documented index (`arid`→`aridity`,
`volcanic`→`volcanic`, `rough`→`roughness`) fall back to that index **only when
the record text does not mention the term**. The fallback is labelled in the
response and the index is explicitly marked unverified.

## Response

```json
{
  "question": "...",
  "interpreted_filters": { "...": "..." },
  "planetary_reference": null,
  "resolved_target_id": null,
  "resolved_target_name": null,
  "results": [
    {
      "candidate_id": "ANL-001",
      "name": "Example site",
      "country": "Iceland",
      "primary_planet_analog": "Mars",
      "latitude": 64.1,
      "longitude": -21.9,
      "elevation_text": "120 m",
      "morphology": "...",
      "metrics": {"roughness": 72},
      "metric_provenance": "unverified_heuristic_index_0_100",
      "similarity_score": 71,
      "data_coverage": 100,
      "data_confidence": 95,
      "score_provenance": "team_supplied_not_recomputed",
      "match_explanations": [
        {"field": "country", "kind": "categorical", "requested": "Iceland", "matched_value": "Iceland"}
      ],
      "missing_fields": [],
      "source_reference": "/api/analog/ANL-001",
      "is_fixture": false
    }
  ],
  "total_matched": 1,
  "returned": 1,
  "limit": 10,
  "offset": 0,
  "data_provenance_mode": "team_backend_read_only",
  "backend": "terratwin_express",
  "ordering": "backend_order_preserved",
  "unavailable_fields": [],
  "missing_information": [],
  "limitations": []
}
```

Scores, coverage and confidence are echoed with their original JSON number
type. They are never rounded, rescaled or recomputed.

## Missing fields and unsupported dimensions

Two different situations are reported separately:

- `unavailable_fields` — the request asks for a dimension the records cannot
  support. Nothing is silently ignored. Examples: numeric elevation
  (`elevation` is display text with embedded units), mineralogy, vegetation,
  numeric surface temperature in kelvin, candidate mission-profile suitability.
- `missing_information` — a candidate lacked a value required by an applied
  filter, so it was excluded from that filter. A missing metric is never
  treated as `0`, as "dissimilar", or as a negative scientific match.

A candidate that cannot be evaluated against an active numeric filter is
excluded from the result set, not ranked lower.

## Target resolution

`target` (request field or a target name/ID in the question) is resolved
through the read-only team API. Resolution requires an exact ID or a unique
name fragment. Ambiguous or unknown targets are **not** guessed: no target
filter is applied and a limitation explains that the target could not be
resolved.

If coordinates are missing from a record, geographic filters exclude it and
record the absence in `missing_information`; coordinates are never fabricated.

## Failure behaviour

| Condition | Result |
|---|---|
| Team backend unreachable | HTTP 503 `backend_unavailable` |
| Backend returns zero records | HTTP 200, `results: []`, explicit limitation |
| Unknown target | HTTP 200, unresolved target plus limitation |
| Unsupported dimension | Listed in `unavailable_fields` |
| Missing metric | Excluded from that filter, listed in `missing_information` |

## Tests

`tests/test_place_search.py` (15 tests) and the Phase 8 end-to-end test cover:

- explicit and parsed filters, clause-scoped ranges;
- missing metrics excluded rather than zeroed;
- unsupported dimensions reported;
- score types preserved verbatim;
- backend order preserved, no ranking;
- ambiguous target handling;
- empty results returned explicitly;
- places → images flow with a mocked backend.

All backend responses are mocked. **No live Node/MongoDB backend has been
exercised**; see `KNOWN_LIMITATIONS.md` L22.
