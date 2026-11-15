# Model selection

## Two inference providers, one pipeline

The assistant supports two interchangeable providers. They differ only in where
inference runs; both feed the same prompt, parser and evidence validation.

| Provider | Location | Credential | Required? | Weights needed? |
|---|---|---|---|---|
| **Ollama** | local process, loopback HTTP | none | no | yes, pulled locally |
| **Groq** | hosted OpenAI-compatible API | server-side `GROQ_API_KEY` | no | no |

- Ollama is the **default** and the offline path. It uses free/open weights and
  involves no hosted service.
- Groq is **optional** and exists so the deployed site can answer without a
  laptop-hosted Ollama. It sends the evidence pack to a hosted provider, so it
  is a data-egress decision the operator must make deliberately.
- Groq requires a server-side API key and is never called from a browser.
- A model's licence and a provider's terms are different things: an
  Apache-2.0 model served by Groq is still subject to Groq's usage terms, rate
  limits and pricing.
- Groq free-tier limits (requests/tokens per minute and per day) are subject to
  change; check the provider console. They constrain evaluation runs.
- Configuration and secret handling: `PROVIDER_CONFIGURATION.md`.

## Constraints (local default)

- Local inference must stay free and offline-capable.
- Configurable model name and generation options.
- Must run on the development machine: 8 GB RAM, GTX 1650 with ~4 GB VRAM,
  i5-11320H.
- Must return schema-constrained JSON reliably.
- Licence, quantization and hardware fit must be verified before selection.

## Selection

| Role | Model | Size | Context | Quantization | Weights licence |
|---|---|---|---|---|---|
| Primary | `qwen3:4b-instruct-2507-q4_K_M` | 2.5 GB | 256K native | Q4_K_M | Apache-2.0 |
| Fallback | `qwen2.5:3b-instruct-q4_K_M` | ~1.9 GB | 32K | Q4_K_M | Apache-2.0 |

Runtime: **Ollama 0.40.16**, MIT licence.

### Why this model

- 4B parameters at Q4_K_M plus an 8K working context loads in **4.2 GB**
  (`ollama ps`), so it runs partly on the 4 GB GTX 1650 and partly on CPU
  (about 55% GPU / 45% CPU in testing). The full 256K context is not used.
- Measured latency for the evidence-pack prompt at 8K context was **203-301 s**
  per answer. A 16K run loaded at 5.4 GB with 44% GPU and took **403 s**, so 8K
  is the better operating point on this machine.
- The `instruct-2507` variant is non-thinking, so it does not spend the output
  budget on `<think>` blocks and returns JSON directly.
- Qwen3 supports structured output through Ollama's JSON-schema `format`.
- Apache-2.0 permits local and commercial use without a hosted dependency.
- A 3B fallback keeps the assistant usable if the primary model is unavailable
  or too slow on a given machine.

Larger Qwen3 variants (8B, 14B, 30B, 32B) exceed comfortable VRAM at useful
context lengths on a 4 GB GPU. They are not required for evidence quotation and
would increase latency and the risk of truncation.

### Why the default is not a hosted model

A hosted tier is not an open-source licence and creates a network dependency,
data-egress consideration and availability risk. The evidence-grounded path is
required to work locally and offline, so Ollama remains the default and local
use never requires a hosted key or network inference.

Groq was added as an **explicit opt-in** (`ASSISTANT_LLM_PROVIDER=groq`) for
deployment, not as a replacement. It uses `openai/gpt-oss-120b`, a current
Groq-hosted model that supports JSON-Schema structured outputs. No model weights
are shipped or downloaded for the Groq path. See `PROVIDER_CONFIGURATION.md`.

## Verification performed

Checked on 2026-11-14:

- `ollama --version` -> `ollama version is 0.40.16`.
- Ollama model library lists `qwen3:4b-instruct-2507-q4_K_M` at 2.5 GB with a
  256K context window, text input.
- Hugging Face model card `Qwen/Qwen3-4B-Instruct-2507` declares
  `License: apache-2.0`, 4.0B parameters, 262,144 native context.
- `ollama pull qwen3:4b-instruct-2507-q4_K_M` succeeded on the development
  machine. `ollama list` reported ID `0edcdef34593`, 2.5 GB. See
  `EXPERIMENT_LOG.md` for run details.
- Hardware detected: GTX 1650 (4,293,918,720 bytes adapter RAM reported),
  ~7.8 GiB system RAM, i5-11320H.

## Configuration

Defaults in `assistant/config.py`:

```text
ASSISTANT_OLLAMA_BASE_URL=http://127.0.0.1:11434
ASSISTANT_OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M
ASSISTANT_OLLAMA_FALLBACK_MODEL=qwen2.5:3b-instruct-q4_K_M
ASSISTANT_OLLAMA_NUM_CTX=8192
ASSISTANT_OLLAMA_TEMPERATURE=0.0
ASSISTANT_OLLAMA_NUM_PREDICT=1200
ASSISTANT_OLLAMA_TIMEOUT_S=600
```

`temperature=0` and a fixed seed are used for reproducibility. This is a
generation setting only; it does not affect any scientific score.

## Health and fallback

`GET /api/assistant/health` reports:

- whether Ollama is reachable;
- configured and fallback model names;
- whether each is present;
- installed model list;
- retrieval backend, source/chunk counts and FTS5 availability;
- data provenance mode.

If inference is unavailable or output fails validation, the response is
`generation_mode=evidence_only_fallback`. The fallback quotes stored values and
never invents interpretation, proposals or numbers.

## What is not claimed

- No benchmark claim that this model is scientifically accurate in general.
- No claim that a 4B model is equivalent to a larger model.
- No claim that the model's answers are authoritative; server-side validation
  and the deterministic records remain authoritative.
- No claim that the model runs on every machine. If it does not fit or Ollama
  is absent, the fallback is the supported path.
