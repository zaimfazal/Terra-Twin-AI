# LLM experiment log

Record timestamps, model/quantization, hardware, prompt version, retrieval
configuration, fixtures, question set, command, exact outcome, latency,
malformed output, citation errors, hallucination failures and follow-up.
No secrets are recorded.

## Environment

| Item | Value |
|---|---|
| Date | 2026-11-14 |
| OS | Windows |
| Python | 3.12 |
| CPU | 11th Gen Intel Core i5-11320H @ 3.20 GHz |
| RAM | 8,362,713,088 bytes (~7.8 GiB) |
| GPU | NVIDIA GeForce GTX 1650, 4,293,918,720 bytes reported (~4 GiB) |
| GPU driver | 32.0.15.9579 |
| Ollama | 0.40.16 |
| Retrieval | SQLite FTS5, 9 sources / 38 chunks |
| Model | `qwen3:4b-instruct-2507-q4_K_M` (Ollama ID `0edcdef34593`, 2.5 GB) |
| Prompt version | `assistant-rag-v1.1.0` |
| Generation | temperature 0.0, seed 42, num_ctx 8192, num_predict 1200 |
| Structured data | synthetic test-only fixture (2 candidates, 2 reports, 16 evidence items) |

## Corpus provenance

| File | Title | Organisation | URL / DOI | Licence |
|---|---|---|---|---|
| 01_platform_methodology.md | Platform methodology: similarity, coverage, confidence and evidence classes | Terra Twin LLM workstream | — | Internal project documentation |
| 02_modis_lst_caveat.md | MODIS MOD11A2: land-surface temperature is not air temperature | NASA LP DAAC (product identity and URL) | https://lpdaac.usgs.gov/products/mod11a2v061/ | NASA open data; see provider terms |
| 03_planetary_environment_differences.md | Earth, Moon and Mars: environment differences relevant to analog interpretation | NASA (general background; see URLs) | https://science.nasa.gov/moon/ | NASA public domain / open data |
| 04_proxy_evidence_caveats.md | Proxy evidence caveats: glaciers, permafrost, land cover, hydrogen and spectra | Terra Twin LLM workstream | — | Internal project documentation |
| 05_dataset_provenance_requirements.md | Dataset provenance requirements for the assistant corpus | Terra Twin LLM workstream | — | Internal project documentation |
| 06_report_explanation_guide.md | How to explain an Analog Intelligence Report without changing it | Terra Twin LLM workstream | — | Internal project documentation |
| 07_jezero_background.md | Jezero Crater: general reference background | NASA Mars Exploration Program | https://science.nasa.gov/mission/mars-2020-perseverance/ | NASA public domain / open data |
| 08_moon_background.md | Lunar south pole and Shackleton Crater: general reference background | NASA | https://science.nasa.gov/moon/ | NASA public domain / open data |
| 09_answer_style.md | Assistant answer style and uncertainty language | Terra Twin LLM workstream | — | Internal project documentation |

Content hashes and ingestion timestamps are stored in the SQLite `sources`
table for each document.

---

## Run 1 — generation tests, first execution

Command:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/test_generation.py -q
```

Outcome: **1 failed, 7 passed**. Failure:
`test_malformed_model_output_falls_back` expected the substring "malformed";
the parser correctly returned `no JSON object found in model output`.

Action: changed the test to assert the actual parser message. No production
logic changed.

## Run 2 — generation tests after assertion fix

Command: same as Run 1.

Outcome: **8 passed**.

## Run 3 — evaluation, first execution

Command:

```powershell
python scripts/run_evaluation.py
```

Outcome: **25/26 passed**. Q12 (`citation_attack`) failed:
`guardrail_notice_contains: guardrail notices=[]`.

Root cause: `CITATION_FABRICATION_RE` matched singular "citation" but not the
plural "citations" because of the trailing word boundary.

Action: changed the regex to `(citations?|references?|dois?|papers?|sources?)`,
updated the loader's analogous pattern, and added regression tests.

## Run 4 — evaluation after citation fix

Command: same as Run 3.

Outcome: **26/26 passed**. Result file:
`evaluation/results/eval-20261114T131930Z-evidence_only_fallback.json`.

All questions ran in `evidence_only_fallback` mode; no inference was used and
none is claimed.

## Run 5 — full automated tests

Command:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -p no:warnings
```

Outcome: **70 passed in 7.71s**. The `PYTEST_DISABLE_PLUGIN_AUTOLOAD` flag is
required on this machine because the globally installed `logfire` pytest plugin
fails with `ImportError: cannot import name '_ExtendedAttributes'`.

## Run 5b — negation handling and final test count

Observation: a correct sentence such as "the glacier indicator does not prove
subsurface water ice" was flagged as `proof_language` /
`glacier_as_confirmed_water`, and "is not a direct measurement" was flagged as
`proxy_presented_as_direct`. This is a false positive that would mislabel a
good model answer.

Change: added a narrow local negation check and applied it to overclaim, proxy
and missing-as-zero detection. Added
`test_negated_overclaims_are_not_flagged`. Positive overclaim tests still pass.

Command: `python -m pytest -p no:warnings`

Outcome: **71 passed in 7.40s**. Evaluation rerun: **26/26 passed**. Ruff:
**All checks passed!**.

## Run 6 — lint

Command:

```powershell
python -m ruff check .
```

Outcome: **All checks passed!** Twelve safe autofixes were applied (import
sorting, unused imports) and one unused variable was turned into a real
validation check (unknown source IDs on foreground claims).

## Run 7 — corpus ingestion script

Command:

```powershell
python scripts/ingest_corpus.py
```

Outcome:

```json
{"ingested": 9, "skipped": 0, "failed": 0, "errors": [],
 "stats": {"sources": 9, "failed_sources": 0, "chunks": 38, "fts5_available": true}}
```

Note: the script initially failed with `ModuleNotFoundError: No module named
'assistant'` when run as `python scripts/...`. Both scripts now prepend the
workstream root to `sys.path`; rerun succeeded as shown.

## Run 8 — model selection and download

Verification:

- `ollama --version` -> `ollama version is 0.40.16`.
- `https://ollama.com/library/qwen3/tags` lists
  `qwen3:4b-instruct-2507-q4_K_M` — 2.5 GB, 256K context, text input.
- `https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507` declares
  `License: apache-2.0`, 4.0B parameters, 262,144 native context.
- Ollama runtime licence: MIT.

Command:

```powershell
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Progress observed: 2.5 GB download at approximately 3.9 MB/s. The pull
completed successfully. `ollama list` then reported:

```text
NAME                             ID              SIZE      MODIFIED
qwen3:4b-instruct-2507-q4_K_M    0edcdef34593    2.5 GB    29 seconds ago
```

`GET /api/version` returned `{"version":"0.40.16"}`.

## Run 9 — model inference

To be appended after the pull completes. Must record:

- exact `ollama list` output and digest;
- first-token/total latency;
- prompt/eval token counts;
- model response JSON;
- validation result and whether the answer came from the model or fallback;
- any malformed output or citation errors.

Do not mark this run passed if the model was not actually called.

## Run 10 — model-mode evaluation

To be appended after a successful Run 9. Must record the exact
`python scripts/run_evaluation.py --use-model ...` command, pass count, failure
details, and per-question generation mode. Fallback substitution is not
acceptable as a model result.
