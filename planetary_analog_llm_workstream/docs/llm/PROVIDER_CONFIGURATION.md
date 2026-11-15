# Inference provider configuration

The assistant has one generation pipeline and two interchangeable inference
providers:

| Provider | Where it runs | Credential | Default |
|---|---|---|---|
| **Ollama** | local process on the operator's machine | none | **yes** |
| **Groq** | hosted, OpenAI-compatible API | server-side `GROQ_API_KEY` | optional |

Both return the same `ModelResponse`, and both pass through the **same**
parsing and evidence validation. Provider choice never bypasses validation.
Neither provider is required: without either, the assistant returns the
deterministic evidence-only fallback.

Selection:

```dotenv
ASSISTANT_LLM_PROVIDER=ollama   # or: groq
```

`Settings.llm_provider` is a validated literal; an unknown value fails at
startup instead of silently selecting a provider.

## Ollama (local, default)

```dotenv
ASSISTANT_OLLAMA_BASE_URL=http://127.0.0.1:11434
ASSISTANT_OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M
ASSISTANT_OLLAMA_FALLBACK_MODEL=qwen2.5:3b-instruct-q4_K_M
ASSISTANT_OLLAMA_NUM_CTX=8192
ASSISTANT_OLLAMA_TEMPERATURE=0.0
ASSISTANT_OLLAMA_NUM_PREDICT=1200
ASSISTANT_OLLAMA_TIMEOUT_S=600
ASSISTANT_OLLAMA_HEALTH_TIMEOUT_S=3
ASSISTANT_REQUIRE_MODEL=false
```

- Health calls `GET /api/tags`; `available` means Ollama answered.
  `configured_model_present` means the configured model is installed.
- Generation calls `POST /api/chat` with the JSON schema in `format`, retrying
  once in `"json"` mode if the runtime rejects a schema.
- No network egress and no credential are involved.
- Model selection rationale, licence and hardware measurements are in
  `MODEL_SELECTION.md`.

## Groq (hosted, optional)

```dotenv
GROQ_API_KEY=gsk_...                      # server-side only
GROQ_MODEL=openai/gpt-oss-120b
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_TIMEOUT_S=60
GROQ_HEALTH_TIMEOUT_S=5
GROQ_TEMPERATURE=0.0
GROQ_MAX_COMPLETION_TOKENS=4096
GROQ_STRICT_SCHEMA=false
```

These use the provider's own `GROQ_*` environment names (not the `ASSISTANT_`
prefix) so a key can be supplied without renaming. `ASSISTANT_LLM_PROVIDER`
keeps the `ASSISTANT_` prefix. No duplicate settings exist, and there is no
second copy of the key under another name.

### Model choice

`openai/gpt-oss-120b` is the default hosted model because:

- it is a current production model on Groq;
- it is one of the models for which Groq documents JSON-Schema structured
  outputs;
- it supports long context and a large completion budget.

`GROQ_MODEL` is configurable. Other previously popular IDs (for example
`llama-3.3-70b-versatile`) have been deprecated for free/developer accounts and
do not all support `json_schema`; do not hard-code a model from a blog post.
List what the key can actually use:

```bash
curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"
```

### Structured output modes

`response_format` is always sent as `type: json_schema` with the `ModelDraft`
schema.

- `GROQ_STRICT_SCHEMA=false` (default) uses best-effort mode. Groq's strict mode
  requires **every** field to be required and `additionalProperties: false`;
  `ModelDraft` intentionally has optional fields, so best-effort is the correct
  mode for this schema.
- `GROQ_STRICT_SCHEMA=true` requests constrained decoding. Only use it with a
  schema where all fields are required and the selected model supports it,
  otherwise Groq returns HTTP 400.
- If Groq rejects `json_schema` for the chosen model, the adapter retries once
  with `{"type": "json_object"}`. The schema is still enforced server-side by
  `parse_draft` and `validate_draft`; JSON mode is not a validation bypass.

### Health semantics

`GET /api/assistant/health` reports the provider honestly:

| Field | Meaning |
|---|---|
| `inference.provider` | `ollama` or `groq` |
| `inference.configured` | a key is present (Groq) / settings exist (Ollama) |
| `inference.reachable` | the provider host answered an HTTP request |
| `inference.authenticated` | Groq accepted the key (HTTP 200 on `/models`) |
| `inference.available` | a request actually succeeded — **not** just a key being set |
| `inference.configured_model` | configured model ID |
| `inference.configured_model_present` | model appears in the provider's list, or `null` if unknown |
| `inference.error` | safe diagnostic; never contains the key |

A configured key alone never produces `available: true`. The health check
performs a real `GET /models` probe with a short timeout.

### Error handling

| Condition | Behaviour |
|---|---|
| Missing `GROQ_API_KEY` | no network call; `ModelUnavailable`; fallback |
| HTTP 401 / 403 | "rejected the API key"; fallback; key never echoed |
| HTTP 429 | rate-limit error, includes `Retry-After` when supplied; fallback |
| HTTP 404 | "model is not available"; check `GROQ_MODEL`; fallback |
| HTTP 400 (other) | request rejected with a redacted detail; fallback |
| Timeout | `ModelUnavailable` naming the timeout; fallback |
| Network error | `ModelUnavailable` "unreachable"; fallback |
| Malformed envelope / no choices / empty content | `ModelUnavailable`; fallback |
| Malformed JSON content | parsed by the shared validator; fallback with `schema_valid=false` |
| Evidence IDs/sources/numbers invalid | rejected by `validate_draft`; fallback |
| Key present in any diagnostic string | replaced with `[redacted]` before raising |

## Secret management

- Never commit `GROQ_API_KEY`; keep it in an untracked `.env` or the platform's
  secret store. `.env.example` contains only a commented placeholder.
- The key is stored as a `SecretStr`; printing settings shows `**********`.
- It is sent only in the `Authorization` header to `GROQ_BASE_URL`.
- It is never returned by any route, never written to logs, and never included
  in `repr()` of the client.
- Tests assert the key is absent from health payloads, error messages and logs.
- Rotate by replacing the environment value and restarting the service.

## Free-tier restrictions

Groq's free tier is rate-limited and can change without notice. At the time of
writing, `openai/gpt-oss-120b` is documented at roughly 30 requests/minute,
1,000 requests/day, 8,000 tokens/minute and 200,000 tokens/day, organisation
wide. Treat these as **subject to change** and check
`console.groq.com/settings/limits` for the account's real limits.

Consequences:

- a full 26-question evaluation can exhaust the daily token budget, especially
  with large evidence packs;
- the assistant does not retry 429s automatically;
- production use needs a paid plan or a local Ollama fallback.

## Local development

```powershell
cd planetary_analog_llm_workstream
# local default, no key needed
python scripts/run_assistant.py --host 127.0.0.1 --port 8100

# hosted provider, key in the current shell only
$env:ASSISTANT_LLM_PROVIDER = "groq"
$env:GROQ_API_KEY = "<your key>"
python scripts/run_assistant.py --host 127.0.0.1 --port 8100
```

Local use never requires a Groq key, and Groq use never requires Ollama.

## Production deployment

- Deploy the FastAPI service behind the team's Node gateway; the browser never
  calls Groq. It calls the team API, which proxies to this service.
- Inject `GROQ_API_KEY` from the platform secret store, not from the image.
- Keep `ASSISTANT_REQUIRE_MODEL=false` unless a missing provider should fail
  startup; otherwise the fallback path stays available.
- Restrict egress to `api.groq.com` when Groq is enabled (plus the team backend
  and NASA hosts for other features).
- Logs must never include request headers.
- If no credential can be supplied, leave `ASSISTANT_LLM_PROVIDER=ollama` or
  accept `evidence_only_fallback`; the platform remains functional.

## Fallback behaviour

| Situation | `generation_mode` |
|---|---|
| Provider returns a valid, validated draft | `model` |
| Provider unreachable / missing key / timeout / 429 | `evidence_only_fallback` |
| Provider returns malformed or schema-invalid content | `evidence_only_fallback` |
| Draft fails evidence/source/numeric/score validation | `evidence_only_fallback` |

Fallback never invents interpretation, proposals or numbers; it quotes stored
values and marks the response as retrieval-only. Supplied scores are identical
to the evidence pack in every mode.

## Verification status

Mocked tests only. No Groq API key was available in this environment, so **no
live Groq request has been made** (see `KNOWN_LIMITATIONS.md` L28). Ollama
inference was verified separately in `EXPERIMENT_LOG.md` Runs 8–10.
