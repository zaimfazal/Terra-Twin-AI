# Implementation roadmap — place and image retrieval

Scope: extend the existing Python LLM workstream with (a) natural-language place
retrieval over the team's real candidate records and (b) cross-planetary NASA
image retrieval. No rebuild, no second database, no scientific-engine changes.

Branch: `feat/place-and-image-retrieval`
Reference audit: `TEAM_INTEGRATION.md`

---

## Phase 0 — audit and baseline (done)

- [x] Audit personal repository: Python 3.12, FastAPI, Pydantic, SQLite FTS5,
      Ollama + Qwen3-4B, deterministic fallback, 73 pytest tests, 26-question
      evaluation.
- [x] Clone team repository read-only to `../TerraTwin-team-reference`.
- [x] Inspect models, routes, controllers, engines, seeding, frontend data layer.
- [x] Record exact routes, response shapes, field lists and provenance caveats.
- [x] Record that the team frontend does not yet call the Node API.
- [x] Record that no place-search or NASA-image-provider retrieval exists.
- [x] Repository cleanup: `.gitignore`, untrack `__pycache__`, runtime DBs and
      generated logs; preserve source, corpus, fixtures, evaluation questions and
      model result records.
- [x] Model evaluation recorded honestly: 21/26 passed, 5 fallback.

Verification: `git status`, pytest 73 passed, Ruff clean (from prior milestones).

---

## Phase 1 — team backend read-only adapter

Files:

- `assistant/adapters/team_backend.py` — `TeamBackendAdapter`
- `assistant/adapters/records.py` — normalised `AnalogRecord`, `TargetRecord`,
  `DatasetRecord` with `provenance` and `missing_fields`
- `assistant/config.py` — `team_backend_url`, `team_backend_timeout_s`,
  `structured_backend = "team_backend"`
- `assistant/service.py` — construct the adapter from settings
- `tests/test_team_backend_adapter.py` — mocked `httpx` transport

Requirements:

- Only `GET /api/health`, `/api/analog`, `/api/analog/:id`, `/api/targets`,
  `/api/nasa-datasets`, `/api/mission-profiles`, plus read-only
  `/api/analog/nearby` and `/api/analog/within-polygon`.
- Strict timeouts; bounded idempotent retries; `AdapterUnavailable` on failure.
- Preserve scores/coverage/confidence verbatim; never default a missing metric
  to zero; normalise both `coordinates{lat,lon}` and
  `location.coordinates[lon,lat]`.
- Tag platform values as `platform_heuristic_index (unverified)`.
- No MongoDB driver, no connection string, no write verb.

Exit criteria: mocked tests pass; adapter is never exercised against a live
database in the ordinary suite.

---

## Phase 2 — natural-language place retrieval

Files:

- `assistant/retrieval/query_parser.py` — deterministic, rule-based parser
  (no model call required; optional model assist stays behind the existing
  provider abstraction).
- `assistant/retrieval/places.py` — typed search service.
- `assistant/places/contracts.py` — `CandidateSearchFilters`, `PlaceSearchRequest`,
  `PlaceSearchResult`, `PlaceSearchResponse`, `MatchExplanation`,
  `UnavailableFieldWarning`.
- `assistant/api.py` — `POST /api/assistant/places/search`.
- `tests/test_place_search.py`.

Parsed dimensions: planetary reference, planetary target name, Earth location,
country/region, terrain type, landform, geology, elevation range, slope,
roughness, local relief, aridity, thermal, vegetation, water/ice indicators,
volcanic characteristics, mission profile, exploration purpose.

Semantics:

- Only emit filters backed by real fields; unsupported requests (e.g.
  mineralogy) produce `unavailable_fields` warnings, not negative matches.
- Missing ≠ zero; null ≠ negative match; unsupported ≠ dissimilar.
- `similarity_score`/`coverage`/`confidence` echoed unchanged.
- Every result carries provenance and a match explanation listing the actual
  matched fields.
- Empty backend → empty result, no fabrication.

Exit criteria: parser and search unit tests, missing-field tests, score
immutability tests, empty-result test.

---

## Phase 3 — connect to current candidate and target data

- Wire `TeamBackendAdapter` into `AssistantService` for place search.
- Resolve target by ID or name through `GET /api/targets`.
- Use real analog coordinates for geographic filters; never invent coordinates.
- Add an end-to-end mocked test: question → filters → candidates → explanation.

---

## Phase 4 — NASA Image and Video Library

Files:

- `assistant/images/providers/nasa_images.py`
- `assistant/images/contracts.py` (started here, finalised in Phase 7)

Endpoints: `GET https://images-api.nasa.gov/search`,
`/asset/{nasa_id}`, `/metadata/{nasa_id}`.

Retrieve and preserve: NASA ID, title, description, source URL, image URL,
date, instrument, mission, attribution. Missing fields stay `null`. Validate
content-type and host allowlist.

---

## Phase 5 — NASA GIBS (Earth only)

- WMS/WMTS request construction from real candidate coordinates.
- Validate layer names against a documented allowlist and validate dates.
- Preserve layer + date provenance.
- Refuse Moon/Mars use; return `limitations` instead.

---

## Phase 6 — NASA PDS planetary products

- Documented PDS search/product metadata only.
- Prefer LRO/LROC, MRO/HiRISE, available surface products.
- If no browse/preview product exists: return the verified archive/product link
  plus `missing_previews` entry explaining no preview was available.

---

## Phase 7 — cross-planetary orchestration and API

Files:

- `assistant/images/orchestrator.py`
- `assistant/api.py` — `POST /api/assistant/images/search`

Steps: resolve target → resolve candidate IDs → coordinates/keywords → provider
searches → metadata/asset retrieval → URL validation → dedupe → group
`earth`/`moon`/`mars` → pass verified metadata to the LLM → explain context,
documented similarities, differences, limitations.

Response: `{earth, moon, mars, sources, missing_previews, limitations, rejected_assets}`.

Hard separation: image relevance, visual resemblance, geological analogy,
environmental analogy, scientific similarity score, mission usefulness.

---

## Phase 8 — scientific guardrails and end-to-end tests

- Provider mocks: success, empty, invalid asset, missing thumbnail, valid GIBS
  layer, unsupported layer, PDS product, missing browse product, duplicates,
  invalid URL, timeout, rate limit.
- SSRF: refuse non-allowlisted hosts, private IPs, `file://`, redirects to
  unexpected hosts.
- Score immutability and provenance-mode tests across all new routes.
- Fixture isolation: no fixture record appears as a production finding.
- Visual-vs-scientific similarity separation tests.

---

## Phase 9 — documentation and team handover

- Complete `TEAM_INTEGRATION.md`, `HANDOVER.md`, `AGENT_ACTIVITY.md`,
  `TASKS.md`, `EXPERIMENT_LOG.md`, `API_CONTRACT.md`.
- Record which modules transfer, dependencies, routes, env vars, deployment,
  tests, and known limitations.
- Never copy files into the team repository; the team opens the PR.

---

## Out of scope (explicit)

Raster/DEM processing, feature extraction, similarity/coverage/confidence
calculation, ranking, seeding, frontend redesign, model training, a second
database, MongoDB credentials in the assistant.

---

## Commit plan

1. `chore: audit integration repositories and clean generated artifacts`
2. `docs: add team integration architecture and implementation roadmap`
3. `feat: add team backend read-only adapter`
4. `feat: implement natural language candidate search contracts`
5. `feat: implement feature-based place retrieval`
6. `test: add place retrieval tests`
7. `feat: add NASA image library retrieval`
8. `feat: add NASA GIBS Earth imagery retrieval`
9. `feat: add PDS planetary image product retrieval`
10. `feat: implement cross-planetary image orchestration`
11. `feat: add image retrieval API endpoints`
12. `test: add provider and image validation tests`
13. `docs: complete implementation and team handover`
