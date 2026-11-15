# Cross-planetary image retrieval

Additive capability for the existing assistant. It retrieves images and image
products from three NASA providers and groups them under Earth, Moon and Mars.

The assistant does **not** perform image matching, visual similarity scoring,
geological interpretation or ranking. It retrieves provider records, validates
their URLs, preserves supplied metadata and states what is unavailable.

---

## 1. Hard separation of concepts

The response never merges these into one number:

| Concept | Where it lives |
|---|---|
| Image relevance (keyword match) | `relevance_explanation` prose only |
| Visual resemblance | **not computed at all** |
| Geological analogy | platform candidate/target records, not images |
| Environmental analogy | platform candidate/target records, not images |
| Scientific similarity score | platform-supplied only; never derived from an image |
| Mission usefulness | narrative in stored records, not scored here |

`ImageSearchResponse` and `ImageRecord` contain no score, confidence or
similarity field. This is asserted by a test.

The team's existing `POST /api/analog/image-match` (frontend
`imageSimilarityEngine.js`) is a **heuristic 5-D Euclidean comparison over a few
predefined sample profiles**. It is not a trained computer-vision model. It is
never called by this service and its scores are never presented as scientific
measurements. The API notice repeats this disclosure.

---

## 2. Providers

### 2.1 NASA Image and Video Library (`nasa_image_library`)

- `GET https://images-api.nasa.gov/search` — keyword search, `media_type=image`.
- `GET https://images-api.nasa.gov/asset/{nasa_id}` — asset list; the first
  non-derivative original is preferred over `~thumb`/`~small`/`~medium`
  variants.
- `GET https://images-api.nasa.gov/metadata/{nasa_id}` — **not called**; the
  search record is the metadata source, so nothing is invented to fill it.

Fields preserved: NASA ID, title, description, thumbnail URL, asset URL, record
URL, `date_created` (typed as `creation`, **not** acquisition), center /
secondary creator as attribution.

Fields deliberately left `null`: mission, instrument, coordinates, per-item
licence. The provider search record does not supply them, and they are **not**
inferred from the title or description.

### 2.2 NASA GIBS (`gibs`)

- Earth **only**. Moon and Mars requests never reach GIBS.
- `https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi`, WMS 1.1.1,
  EPSG:4326.
- Layer must be in `SUPPORTED_LAYERS`; unknown layers are refused with a
  limitation and recorded in `rejected_assets`.
- Dates must be `YYYY-MM-DD` **and** a real calendar date.
- Bounding box is built from the candidate's stored coordinates only. With no
  coordinates the provider returns a limitation instead of inventing a location.

Provenance notes state that the `TIME` value is the requested layer date, not a
verified acquisition timestamp, and that the WMS URL is validated but not
fetched, so its HTTP status/content-type are unverified until a browser loads it.

### 2.3 NASA PDS (`pds`)

- Moon and Mars only, via the PDS Geosciences Node ODE REST interface
  (`https://oderest.rsl.wustl.edu/live2/`).
- Parsing is **defensive and unverified against the live service**. A response
  shape that is not recognised yields zero records plus a limitation. No product
  is fabricated.
- The query parameters (`query=products`, `target`, `results`, `output=JSON`)
  follow the documented ODE REST style but their exact live behaviour has not
  been exercised.
- Products without a browse image are returned in `missing_previews` with the
  validated product link and a reason, instead of being dropped silently.

---

## 3. Validation and SSRF protection

`assistant/images/validation.py`:

- HTTPS only.
- Host must be in the provider's allowlist (`PROVIDER_HOSTS`).
- No embedded credentials, no non-default port.
- No IP literal hosts, no `localhost`, `.local`, `.internal`, `.localhost`,
  `.home.arpa`.
- Redirects are not followed; a 3xx becomes a provider error.
- `validate_content_type` accepts `image/*` (and JSON only where explicitly
  allowed) for provider responses.
- A URL that fails validation is dropped and recorded in `rejected_assets`; it is
  never returned as NASA imagery.

No URL produced by a language model is fetched. Queries are built only from
stored candidate/target fields or explicit caller keywords.

---

## 4. Orchestration

`assistant/images/orchestrator.py`:

1. Resolve `candidate_id` through the read-only team adapter. If absent, record a
   limitation and continue without candidate fields.
2. Resolve the target from the request or the candidate's `target_match_id`.
   Unresolved targets produce a limitation.
3. Build keywords from `feature_keywords`, else the candidate's name, country and
   morphology, plus the target's name and `scientific_targets`.
4. Query NASA Image Library per requested planet. Earth additionally queries
   GIBS; Moon and Mars additionally query PDS.
5. A provider failure (timeout, transport error, rate limit, unrecognised shape)
   becomes a limitation. Other providers still return results.
6. Deduplicate by image ID and by normalised asset URL.
7. Group into `earth`, `moon`, `mars`; cap each at `max_per_planet`.
8. Return `sources`, `missing_previews`, `rejected_assets`, `limitations`,
   `providers_used`, `resolved_target_id`, `resolved_candidate_id` and the fixed
   separation notice.

---

## 5. API

`POST /api/assistant/images/search`

```json
{
  "target": "Jezero Crater",
  "candidate_id": "earth_atacama",
  "planets": ["earth", "moon", "mars"],
  "image_types": [],
  "feature_keywords": [],
  "max_per_planet": 5
}
```

Response:

```json
{
  "earth": [], "moon": [], "mars": [],
  "sources": [],
  "missing_previews": [],
  "rejected_assets": [],
  "limitations": [],
  "providers_used": [],
  "resolved_target_id": null,
  "resolved_candidate_id": null,
  "data_provenance_mode": "platform",
  "notice": "Image relevance and visual resemblance are not geological evidence ..."
}
```

`image_types` filters on `photograph`, `satellite_image`, `browse_image`,
`visualization`, `product`.

---

## 6. Failure behaviour

| Failure | Behaviour |
|---|---|
| Provider timeout / transport error | Limitation; other providers continue |
| HTTP 429 | Limitation including `retry-after` when supplied |
| Unrecognised response shape | Zero records from that provider + explicit limitation |
| Missing browse/preview | `missing_previews` entry with product link and reason |
| Invalid or untrusted asset URL | `rejected_assets` entry; never surfaced as NASA imagery |
| No coordinates for GIBS | Limitation; coordinates are never invented |
| Unknown candidate / target | Limitation; no substitute record created |
| Missing metadata | Field stays `null`; never filled from another field |

---

## 7. Tests

`tests/test_images.py` (20 tests, all mocked, no live NASA dependency):

- URL validation: scheme, credentials, port, localhost, private host, IP literal,
  lookalike domain, `file://`.
- Content-type validation.
- NASA Image Library success, empty result, untrusted asset host, missing
  thumbnail, timeout, HTTP 429 with `retry-after`.
- GIBS valid WMS request, unsupported layer, invalid date format, missing
  coordinates.
- PDS product with browse, product without browse, unrecognised response shape.
- Orchestration: grouping, dedupe by ID and by URL, provider-failure isolation,
  rate limiting, planet selection, image-type filtering, unknown candidate, and
  absence of any score field.

---

## 8. Known limitations

1. PDS ODE live response shape is unverified; the parser is defensive and may
   return zero records on a real response.
2. NASA Image Library does not state per-item licence or instrument in the search
   record; these remain unavailable.
3. GIBS WMS URLs are built and validated but not fetched server-side, so image
   retrieval status/content-type is only confirmed by the browser.
4. Provider rate limits and quotas are not modelled beyond surfacing HTTP 429.
5. No caching or persistence of provider records; every request re-queries.
6. Image relevance is keyword-based only. No visual or geological assessment is
   performed or claimed.
