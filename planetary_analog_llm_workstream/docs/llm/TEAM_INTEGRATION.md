# Team integration architecture

Status: **design accepted, not yet merged**. The Python assistant is developed in
`zaimfazal/Terra-Twin-AI`. The team application
(`FM9447/TerraTwin---space-apps`) is inspected here as a **read-only reference**
cloned to a sibling directory (`../TerraTwin-team-reference`). It is never nested
inside this repository and no file in it is modified by this workstream.

This document describes how the assistant connects to the team's existing
Node/Express + MongoDB application **without replacing it** and **without a
second database**.

---

## 1. What the team application actually is (audited 2026-11-15)

| Area | Finding |
|---|---|
| Backend runtime | Node.js + Express, ES modules, port `8000` default (`backend/src/config/env.js`). |
| API prefix | `server.js` mounts the router at `/api`. |
| Database | MongoDB Atlas via Mongoose. `MONGODB_URI` lives only in the team backend environment. Defaults to `mongodb://localhost:27017/terratwin` when unset. |
| Maps | 2dsphere index on `Analog.location`; GeoJSON `[longitude, latitude]`. |
| Frontend | React 18 + Vite + Tailwind. |
| Frontend data source | **Imports local modules** (`src/data/nasaDataCatalog.js`, `src/data/imageSimilarityEngine.js`). The current UI does **not** call the Node API. |

### Implemented Express routes (verified in `backend/src/routes/`)

| Method | Path | Controller | Data source |
|---|---|---|---|
| GET | `/api/health` | inline in `routes/index.js` | Mongoose counts |
| GET | `/api/targets` | `targetController.getTargets` | MongoDB, falls back to `NASA_PLANETARY_TARGETS` |
| GET | `/api/mission-profiles` | `targetController.getMissionProfiles` | in-memory `NASA_PRD_MISSION_PROFILES` |
| GET | `/api/nasa-datasets` | `datasetController.getDatasets` | MongoDB, falls back to `NASA_DATASET_SOURCES` |
| GET | `/api/analog` | `analogController.getAllAnalogs` | MongoDB sorted by `similarity_score` desc, falls back to `NASA_EARTH_ANALOGS` |
| GET | `/api/analog/:id` | `analogController.getAnalogById` | MongoDB `findOne({id})`, falls back to catalog, else 404 |
| POST | `/api/analog/search` | `analogController.searchAnalogs` | in-memory `similarityEngine.calculateAnalogDiscoveries` |
| GET | `/api/analog/nearby` | `analogController.getNearbyAnalogs` | MongoDB `$near` (real geospatial query) |
| POST | `/api/analog/within-polygon` | `analogController.getWithinPolygon` | MongoDB `$geoWithin` |
| POST | `/api/analog/image-match` | `imageController.matchImage` | in-memory heuristic `imageSimilarityEngine` |

Route ordering caveat: `GET /api/analog/:id` is registered after the literal
routes, so `/nearby` resolves correctly. Any new literal route added under
`/api/analog` must be registered before `/:id`.

### Response shapes (verified)

```text
GET /api/analog              -> { count, analogs: Analog[] }
GET /api/analog/:id          -> Analog | 404 { error, message }
GET /api/analog/nearby       -> { source, query_origin, count, results: Analog[] }
POST /api/analog/within-polygon -> { source, count, results: Analog[] }
GET /api/targets             -> { count, targets: PlanetaryTarget[] }
GET /api/nasa-datasets       -> { authority, strict_nasa_compliance, count, datasets: NasaDataset[] }
POST /api/analog/search      -> similarityEngine result object (not a candidate document)
POST /api/analog/image-match -> { status, query_features_used, matches }
```

### Model fields available to the assistant

`Analog` (`backend/src/models/Analog.js`):
`id, name, country, elevation (String), image, primary_planet_analog,
target_match_id, nasa_datasets_used[], similarity_score (default 0),
data_coverage (default 100), data_confidence (default 95), morphology,
scientific_breakdown{why_analog, breakdown_limits, field_test_utility},
metrics{roughness, relief, slope, aridity, thermal, rockiness, volcanic, access},
location{type:'Point', coordinates:[lon, lat]}, timestamps`.

`PlanetaryTarget`:
`id, name, planet, coordinates{lat, lon}, elevation (String), mission_profile,
nasa_primary_source, image, description, scientific_targets[],
criteria_signature{roughness, relief, slope, aridity, thermal, rockiness,
volcanic, access}` — every criterion defaults to `50`.

`NasaDataset`:
`key, id, name, provider, instrument, spatial_resolution, coverage,
parameters[], url, doi`.

### Critical provenance caveats (must not be hidden)

1. **`similarity_score`, `data_coverage`, `data_confidence` are schema fields,
   not independently verified measurements.** A missing score is stored as `0`,
   coverage as `100`, confidence as `95` by schema default. A `0` therefore does
   **not** mean "no similarity" and `100` does **not** mean "fully covered".
2. `criteria_signature` and `metrics` are **0–100 heuristic indices** produced by
   the team's `similarityEngine.js`, not physical measurements in SI units.
3. The catalogue fallback records (`NASA_EARTH_ANALOGS`) use
   `coordinates: {lat, lon}`, while MongoDB documents use
   `location.coordinates: [lon, lat]`. Any consumer must accept both.
4. `POST /api/analog/search` never reads MongoDB — it scores the in-memory
   8-record catalogue. It returns score objects, not `Analog` documents.
5. `POST /api/analog/image-match` is a **heuristic 5-D Euclidean feature
   comparison** over predefined sample profiles. It is not a trained computer
   vision model and its scores must be labelled as a demonstration.
6. `image` fields in the catalogue point at Unsplash photos, not NASA imagery.
7. No natural-language search, no image-provider retrieval and no assistant
   routes exist in the team backend today.

---

## 2. Target arrangement

```text
Browser (React)
   |  fetch('/api/assistant/...')
   v
Team Node/Express API  ──(optional gateway/proxy)──►  Terra Twin Python FastAPI
   |                                                        |
   |  read-only HTTP                                        |  read-only HTTP
   v                                                        v
MongoDB Atlas                                  NASA Image Library / GIBS / PDS
   ^
   └── only the Node backend holds MONGODB_URI
```

- The Node backend remains the owner of MongoDB. The Python assistant has **no
  database driver and no connection string**.
- The assistant reaches the team API through one configurable base URL. It uses
  only `GET` requests (plus no state-changing verbs) and never writes records.
- The assistant never calls MongoDB directly, never seeds data and never
  recalculates scientific values.

### Development arrangement

| Service | Port | Command |
|---|---|---|
| Team Node backend | `8000` | `npm run dev` (or `node server.js`) in `backend/` |
| Python assistant | `8100` | `uvicorn assistant.asgi:app --port 8100` in `planetary_analog_llm_workstream/` |
| Team frontend | `5173` | `npm run dev` in `frontend/` |

Start order: MongoDB reachable → Node backend → assistant → frontend.

### Production arrangement

- Node backend and Python assistant deploy as separate services.
- The browser talks only to the Node backend (same origin), which proxies or
  server-side calls the assistant. This keeps CORS and credentials simple and
  prevents the assistant from being exposed publicly with no auth.
- `TERRATWIN_BACKEND_URL` points at the deployed Node backend's internal URL.
- The assistant service holds no MongoDB credential and no user data.

---

## 3. Environment configuration

Assistant (`.env.example`, all optional, no secrets required):

```dotenv
ASSISTANT_STRUCTURED_BACKEND=team_backend
TERRATWIN_BACKEND_URL=http://localhost:8000
ASSISTANT_TEAM_BACKEND_TIMEOUT_S=10
ASSISTANT_LLM_PROVIDER=ollama
ASSISTANT_OLLAMA_BASE_URL=http://127.0.0.1:11434
ASSISTANT_OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M
# Optional hosted inference; never required.
# ASSISTANT_LLM_PROVIDER=groq
# GROQ_API_KEY=...
# GROQ_MODEL=...
```

Rules:

- `MONGODB_URI` is **never** present in the assistant `.env.example`, source or
  tests. It belongs only to the Node backend.
- `GROQ_API_KEY` is optional and server-side only.
- No credential is ever returned in an API response or logged.

Team backend (unchanged, reference only):

```dotenv
PORT=8000
MONGODB_URI=<team-owned Atlas connection string>   # never copied here
CORS_ORIGIN=*
NODE_ENV=development
```

---

## 4. Read-only adapter contract

Implemented in `assistant/adapters/team_backend.py` (Phase 1).

```text
class TeamBackendAdapter:
    data_provenance_mode = "team_backend_read_only"
    backend_name = "terratwin_express"

    health() -> dict
    list_analogs() -> list[AnalogRecord]           # GET /api/analog
    get_analog(analog_id) -> AnalogRecord | None   # GET /api/analog/:id
    list_targets() -> list[TargetRecord]           # GET /api/targets
    get_target(id_or_name) -> TargetRecord | None
    list_datasets() -> list[DatasetRecord]         # GET /api/nasa-datasets
    list_analogs_near(lat, lon, max_km) -> list   # GET /api/analog/nearby
    analogs_within_polygon(coords) -> list         # POST /api/analog/within-polygon
```

Adapter rules:

- `httpx` client with explicit connect/read timeouts and a bounded retry policy
  for idempotent `GET`s only.
- Accept both coordinate shapes and normalise to
  `latitude`/`longitude` **without inventing values**; if neither is present the
  coordinates stay `None`.
- Preserve `similarity_score`, `data_coverage`, `data_confidence` byte-for-byte
  as supplied (including `null`), tagged with provenance
  `platform_heuristic_index (unverified)`.
- Never cast a missing metric to `0`. Missing → `None` + `missing_fields`.
- On network failure, timeout or non-2xx: raise `AdapterUnavailable`; the API
  returns an explicit error/empty result, never fabricated candidates.
- The adapter is read-only: only `GET` and the two documented read-only `POST`
  geospatial queries are issued.

---

## 5. Additive endpoint contracts requested from the team

These are **proposals**. Nothing in the team repository is modified.

### 5.1 `POST /api/analog/feature-search` (future, larger catalogues)

The current 8-record catalogue is small enough for read-only client-side
filtering of documented fields. Beyond a few hundred records, filtering must move
server-side:

```json
{
  "filters": {
    "country": ["Chile"],
    "primary_planet_analog": ["Mars"],
    "terrain_terms": ["volcanic", "arid"],
    "metrics": {
      "roughness": {"min": 60, "max": 100},
      "aridity": {"gte": 90}
    },
    "bbox": {"min_lon": -80, "min_lat": -30, "max_lon": -60, "max_lat": -10}
  },
  "limit": 25,
  "cursor": null
}
```

Response: `{ count, results: Analog[], applied_filters, ignored_filters,
provenance }`. The team owns the implementation; the assistant owns the typed
request/response contract and must degrade gracefully if the endpoint is absent
(HTTP 404 → fall back to `/api/analog` + documented client-side filtering).

### 5.2 Gateway routes the team may add (optional)

```text
POST /api/assistant/places/search   -> proxy to Python /api/assistant/places/search
POST /api/assistant/images/search   -> proxy to Python /api/assistant/images/search
```

The Python service itself already exposes these paths; the gateway is only for
same-origin deployment.

---

## 6. Assistant routes (implemented in this workstream)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/assistant/chat` | Grounded explanation of one candidate/report |
| POST | `/api/assistant/explain-report` | Explain an existing report |
| GET | `/api/assistant/health` | Adapter/model/retrieval health |
| POST | `/api/assistant/feedback` | Store optional feedback |
| POST | `/api/assistant/places/search` | Natural-language place retrieval (Phase 2–3) |
| POST | `/api/assistant/images/search` | Cross-planetary image retrieval (Phase 4–7) |

All routes are additive under `/api/assistant`. No existing route is changed.

---

## 7. Error handling and degradation

| Failure | Behaviour |
|---|---|
| Backend unreachable | `503` with `backend_unavailable`; no candidates returned |
| Backend 404 for an ID | `404`; no fallback invention |
| Backend returns zero records | `200` with `results: []` and an explicit "no matching records" limitation |
| Unsupported filter field | Field listed in `unsupported_fields`; not treated as a negative match |
| Missing metric | `null` + `missing_fields` entry; never `0` |
| Model unavailable | Deterministic evidence-only fallback labelled `evidence_only_fallback` |
| NASA provider timeout/rate limit | Provider listed in `limitations`; other providers still returned |
| Invalid/untrusted image URL | Dropped and recorded in `rejected_assets`; never shown as NASA imagery |

---

## 8. Frontend integration contract (for the team, not implemented here)

Minimal, non-redesigning additions:

1. Parametric/place search panel calls `POST /api/assistant/places/search` with
   `{question, target_id, max_results}` and renders the returned candidates,
   matched fields, provenance and limitations.
2. A cross-planetary image panel calls `POST /api/assistant/images/search` and
   renders `earth`, `moon`, `mars` groups plus `sources`, `missing_previews` and
   `limitations`.
3. The existing PhotoMatcher stays as-is and is labelled "heuristic visual
   demonstration". Its scores must never be displayed as scientific similarity.
4. No frontend redesign is owned by this workstream. The team decides layout.

---

## 9. Deployment checklist

- [ ] Team backend deployed with MongoDB Atlas reachable.
- [ ] Assistant deployed with `TERRATWIN_BACKEND_URL` pointing at the backend.
- [ ] Assistant has no `MONGODB_URI`.
- [ ] `ASSISTANT_STRUCTURED_BACKEND=team_backend` in production.
- [ ] Outbound egress from the assistant is limited to the team backend plus
      `images-api.nasa.gov`, `images-assets.nasa.gov`, `images.nasa.gov`,
      `gibs.earthdata.nasa.gov` and the PDS hosts in
      `assistant/images/validation.py`.
- [ ] Ollama present, or `LLM_PROVIDER=groq` with a server-side key, or fallback
      mode accepted.
- [ ] Node gateway routes added if the assistant is not publicly exposed.
- [ ] Existing team tests still pass; no team route changed.
- [ ] `docs/llm/HANDOVER.md` read by the integrating engineer.

---

## 10. Known unknowns (must be verified against live data before merge)

1. Whether MongoDB records exactly match the catalogue records field-by-field.
2. Whether `location.coordinates` is populated for every seeded analog, and the
   value of `elevation` (String, with units embedded) across records.
3. Whether `similarity_score` in Mongo is computed or seeded verbatim.
4. Whether the team will accept the additive `feature-search` contract.
5. Live response headers/timeouts of the deployed backend.
