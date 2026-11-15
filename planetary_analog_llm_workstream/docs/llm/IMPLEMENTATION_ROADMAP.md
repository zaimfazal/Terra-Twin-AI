# Implementation roadmap — team-integrated assistant

Branch: `feat/team-integration-place-image-groq`
Baseline: `250685e` (continues `feat/place-and-image-retrieval`)
Reference audit: `TEAM_INTEGRATION.md`

Scope: complete the Python LLM workstream for integration into the team's
Node/Express + React + MongoDB application. No rebuild, no second database, no
scientific-engine changes, no edits to the team repository.

Status values: `done`, `partial`, `blocked`, `not started`.

---

## Phase 0 — audit and integration contract (done)

- [x] Read personal `AGENTS.md`, package docs, assistant modules, tests,
      evaluation and `docs/llm/`.
- [x] Read team backend config, models, controllers, routes, both engines,
      frontend data layer and the reserved `model/` directory.
- [x] Record exact routes, response shapes, field lists, provenance caveats and
      engine defaults in `TEAM_INTEGRATION.md`.
- [x] Confirm no real credentials are tracked in either repository.
- [x] Confirm the step-by-step project guide PDF is absent from both
      repositories; do not invent its contents.
- [x] Write this roadmap.

Exit criteria: integration contract documented with no invented APIs. **Met.**

---

## Phase 1 — read-only team Express adapter (done)

- [x] `assistant/adapters/team_records.py`, `team_backend.py`.
- [x] Only documented GET routes plus the read-only within-polygon POST.
- [x] Strict timeouts, bounded idempotent retries, `AdapterUnavailable`.
- [x] Both coordinate shapes; scores preserved verbatim; missing ≠ zero.
- [x] Refuse redirects, non-JSON, credentials in the base URL.
- [x] 13 mocked tests.

Exit criteria: adapter cannot write and cannot invent records. **Met.**

---

## Phase 2 — natural-language place retrieval (done)

- [x] `assistant/retrieval/query_parser.py` — rule-based, clause-scoped.
- [x] `assistant/places/contracts.py` — typed filters, match explanations,
      unavailable fields, provenance mode.
- [x] `assistant/places/service.py` — documented-field filtering only.
- [x] `POST /api/assistant/places/search`.
- [x] Missing metric excludes and is reported; never zero, never "dissimilar".
- [x] Scores echoed, order preserved, no re-ranking.
- [x] 15 tests.

Exit criteria: honest filtering with explicit unavailable dimensions. **Met.**

---

## Phase 3 — connect to real candidates and targets (done)

- [x] Adapter wired through `ASSISTANT_STRUCTURED_BACKEND=team_backend`.
- [x] Target resolution by ID or unique name fragment; ambiguous ⇒ unresolved.
- [x] Real coordinates used for geographic filters; never invented.
- [x] End-to-end mocked place → images test.

Exit criteria: no fabricated identifiers. **Met.**

---

## Phase 4 — NASA Image and Video Library (done)

- [x] `/search` and `/asset/{nasa_id}`; original preferred over derivatives.
- [x] NASA ID, title, description, URLs, record date, centre attribution.
- [x] Mission/instrument/coordinates/licence stay `null` when not supplied.
- [x] Timeout, 429 and missing-thumbnail handling.

Exit criteria: verified-shape parsing with mocked responses. **Met** (live
endpoint not called).

---

## Phase 5 — NASA GIBS Earth imagery (done)

- [x] WMS 1.1.1 EPSG:4326 GetMap construction.
- [x] Supported-layer allowlist; `YYYY-MM-DD` + calendar validation.
- [x] Earth only; never Moon or Mars.
- [x] Coordinates from stored candidate records only.
- [x] Provenance notes: requested date ≠ acquisition; URL not fetched server-side.

Exit criteria: valid Earth configuration, no unsupported layers. **Met.**

---

## Phase 6 — PDS planetary products (done)

- [x] Defensive ODE REST parsing for Moon and Mars.
- [x] Products without browse images returned in `missing_previews`.
- [x] Unrecognised shapes yield zero records plus a limitation.
- [x] Live response shape explicitly marked unverified.

Exit criteria: no fabricated products. **Met**; live compatibility unverified.

---

## Phase 7 — cross-planetary orchestration and API (done)

- [x] Grouping under `earth`/`moon`/`mars`.
- [x] Dedupe by image ID and normalised asset URL.
- [x] Per-provider failure isolation and rate-limit reporting.
- [x] `POST /api/assistant/images/search`.
- [x] No score field anywhere in the image contracts.

Exit criteria: every returned image maps to a provider record. **Met.**

---

## Phase 8 — Groq hosted inference (not started)

- [ ] `assistant/llm/groq.py` behind the existing provider abstraction.
- [ ] `LLM_PROVIDER` / `GROQ_API_KEY` / `GROQ_MODEL` settings, server-side only.
- [ ] Structured JSON output, schema validation, timeout and 429 handling.
- [ ] Provider/model metadata recorded in the answer.
- [ ] Deterministic evidence-only fallback when the provider fails.
- [ ] Mocked tests: valid, malformed, timeout, 429, invalid key, no credential leak.
- [ ] Ollama remains the local default; Groq optional.

Exit criteria: the deployed site can run without a laptop-hosted Ollama, and the
fallback path still works.

---

## Phase 9 — verification and live smoke tests (partial)

- [x] Full suite: 125 passed (baseline, before Phase 8).
- [x] Ruff clean.
- [x] Deterministic evaluation available.
- [ ] Re-run suite and evaluation after Groq changes.
- [ ] Live NASA smoke test where network permits (never required by CI).
- [ ] Live Groq smoke test only if a key is supplied by the owner.

Exit criteria: exact, recorded outcomes; no unexecuted claim marked passed.

---

## Phase 10 — team handover (partial)

- [x] `TEAM_INTEGRATION.md` with adapter contract, gateway proposal, checklist.
- [x] `HANDOVER.md` with branch, SHAs, commands and guardrails.
- [ ] `PLACE_RETRIEVAL.md`, `IMAGE_RETRIEVAL.md`,
      `PROVIDER_CONFIGURATION.md`, `IMPLEMENTATION_ROADMAP.md` (this file).
- [ ] Node gateway patch proposal for the team.
- [ ] Final handover entry with verified SHAs.

Exit criteria: an integrating engineer can merge from the documents alone.

---

## Documentation map

| Topic | File |
|---|---|
| Audit, routes, engine caveats | `TEAM_INTEGRATION.md` |
| Phase plan and status | `IMPLEMENTATION_ROADMAP.md` (this file) |
| Place retrieval | `PLACE_RETRIEVAL.md` |
| Image retrieval | `IMAGE_RETRIEVAL.md` |
| Provider and model configuration | `PROVIDER_CONFIGURATION.md` |
| Quota-loss recovery | `HANDOVER.md` |

---

## Out of scope (explicit)

Raster/DEM processing, feature extraction, similarity/coverage/confidence
calculation, ranking, seeding, frontend redesign, model training, a second
database, MongoDB credentials, edits to the team repository.

---

## Commit checkpoints

1. `chore:` audit engines, defaults and credential state
2. `docs:` implementation roadmap and handover
3. `feat:` Groq hosted inference provider
4. `test:` Groq provider and fallback tests
5. `docs:` provider configuration and final handover
