# Image retrieval

Route: `POST /api/assistant/images/search`
Implementation: `assistant/images/` (`contracts.py`, `validation.py`,
`orchestrator.py`, `providers/`)
Companion document: `IMAGES.md` (provider-level detail and contracts)

The service retrieves **existing NASA imagery** for an Earth candidate and/or a
Moon or Mars target. It is a metadata/keyword search, not computer vision.

## Hard separation of concepts

| Concept | Field? | Meaning |
|---|---|---|
| Image relevance | none | keyword match only; no relevance score exists |
| Visual resemblance | none | never computed |
| Geological analogy | none | never asserted from an image |
| Environmental analogy | none | never asserted from an image |
| Scientific similarity | separate platform metric, never image-derived | unchanged by this service |
| Mission usefulness | none | never inferred |

The image contracts contain **no score, confidence or similarity field**. No
sentence in a response may claim that visual similarity establishes geological
equivalence.

## Providers

| Provider | Planets | Endpoint | Notes |
|---|---|---|---|
| NASA Image and Video Library | Earth, Moon, Mars | `images-api.nasa.gov/search`, `/asset/{nasa_id}` | description search does not support `q` |
| NASA GIBS | **Earth only** | `gibs.earthdata.nasa.gov/wms/1.1.1/.../GetMap` | WMS URL built and validated, not fetched server-side |
| NASA PDS (Geosciences ODE) | **Moon, Mars only** | PDS ODE REST search | defensive parsing; live shape unverified |

GIBS is never used for Moon or Mars. PDS is never used for Earth.

### NASA Image and Video Library

- Search terms come from target, candidate and supplied feature keywords.
- Original assets are preferred over derivatives.
- Returned metadata: NASA ID, title, description snippet, image URLs, record
  date, centre/organization.
- Fields the API does not supply stay `null`: instrument, mission, coordinates,
  licence. They are **not** inferred from the title or filename.
- Attribution: NASA as the source, with the item's `nasa_id` and source URL, so
  the frontend can link the original record.

### NASA GIBS

- WMS 1.1.1 `GetMap`, `EPSG:4326`.
- Layer must be in the documented allowlist; date must match `YYYY-MM-DD` and be
  a real calendar date.
- Coordinates come only from stored candidate records.
- Provenance notes state that the requested date is not necessarily the
  acquisition date, and that the URL is not fetched server-side (so the
  rendered image's HTTP status/content type is unverified by the assistant).

### NASA PDS

- Products without a browse image are returned in `missing_previews`, never as
  synthetic image records.
- Unrecognised ODE shapes yield zero records plus an explicit limitation, rather
  than an exception or invented products.
- The live ODE response shape has **not** been verified; the parser is
  deliberately defensive. See `KNOWN_LIMITATIONS.md` L25.

## Validation and SSRF protection

Before any record is returned:

- scheme must be `https`;
- host must be on the provider allowlist;
- URLs containing credentials are rejected;
- redirects are not followed;
- private/loopback/link-local addresses are refused.

Rejected assets are recorded in `rejected_assets` and never displayed as NASA
imagery. Duplicate images are removed by NASA/provider ID and by normalised
asset URL.

## Orchestration

```
ImageSearchRequest
  -> resolve target / candidate through the read-only team adapter
  -> per-planet keyword query (earth / moon / mars, order preserved)
  -> NASA Image Library (+ GIBS for Earth, + PDS for Moon/Mars)
  -> URL/host validation, dedupe
  -> grouped response + sources + missing_previews + rejected_assets + limitations
```

Provider failure is isolated: a timeout or 429 from one provider is reported in
`limitations` while other providers still answer. `max_per_planet` is bounded.

## Response

`earth`, `moon`, `mars` groups of `ImageRecord`, plus `sources`,
`missing_previews`, `rejected_assets`, `limitations`, `providers_used`,
`resolved_target_id`, `resolved_candidate_id`, `data_provenance_mode`, and a
fixed `notice` restating that image matching is keyword-based.

Each `ImageRecord` carries provider, provider image ID, title, description,
thumbnail/original URLs, source page, attribution text, collection date and
provenance notes. Missing metadata remains `null`.

## Live verification status

| Item | Status |
|---|---|
| NASA Image Library request/response parsing | verified against mocked shapes only |
| GIBS WMS construction and validation | verified; image **not** fetched |
| PDS ODE parsing | defensive; live shape **unverified** |
| End-to-end retrieval against live NASA services | **not performed** in this environment |

No live NASA response is claimed anywhere in this repository. All provider
tests use fabricated HTTP responses.

## Tests

`tests/test_images.py` (23 tests) covers provider parsing, original-over-
derivative selection, GIBS Earth-only routing, PDS missing previews, URL/SSRF
rejection, dedupe, provider isolation, attribution completeness, injection
content preserved as data, and a places → images end-to-end flow.

## Limitations

- Relevance is keyword-only; no image is analysed, embedded or classified.
- Instrument/licence/coordinates may be `null` because the source API omits them.
- GIBS imagery may not correspond to the requested date.
- PDS may return zero records if its live shape differs from the defensive
  parser's expectations.
- No image is stored or re-hosted; only validated provider URLs are returned.
