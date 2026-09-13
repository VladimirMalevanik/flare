# AI models for the manual-input MVP

Verified against official documentation on **2026-09-07**. Provider research plus integration guidance; implementation status is described below. Provider facts below are linked; application defaults and effort estimates are recommendations.

**Agreed MVP scope:** [MVP implementation plan](MVP_IMPLEMENTATION_PLAN.md) takes precedence over the broader options researched here. Implement 20B only for text, explicit Analyze, a durable Postgres worker, and Whisper Turbo with temporary audio staging deleted after processing. 120B routing, V3 fallback, permanent audio storage and scheduling are deferred. Model comparisons and paid-rate estimates below remain technical reference, not MVP requirements.

## Implemented boundary (Block 2)

The backend now provides an isolated `TextAnalyzer` / `GroqTextAnalyzer` for
caller-authorized `Evidence[]`, using only 20B/low and strict structured output.
It performs no DB access, HTTP wiring, jobs or persistence. SDK retries are zero;
source IDs and exact quotes are validated. See the implemented
[text-analysis contract](../backend/docs/text-analysis.md) for settings, bounds,
errors, metadata and the opt-in smoke command. Block 1 auth is already implemented.
The broader flows below remain research/planning, not enabled behavior.

## Models and pricing

Use **Groq API**. The meeting's “Grok/Wispr” choice is superseded by this requested Groq/GPT-OSS/Whisper stack. No automatic source synchronization or embeddings in this MVP.

| Role | Exact Groq model ID | USD input / output per 1M tokens, or audio hour |
| --- | --- | --- |
| Default text and reasoning | `openai/gpt-oss-20b` | $0.075 / $0.30; cached input $0.037 |
| Complex reasoning escalation | `openai/gpt-oss-120b` | $0.15 / $0.60; cached input $0.075 |
| Default transcription | `whisper-large-v3-turbo` | $0.04/hour |
| Optional accuracy-first transcription | `whisper-large-v3` | $0.111/hour |

Sources: Groq model pages for [20B](https://console.groq.com/docs/model/openai/gpt-oss-20b), [120B](https://console.groq.com/docs/model/openai/gpt-oss-120b), [Turbo](https://console.groq.com/docs/model/whisper-large-v3-turbo), and [Large V3](https://console.groq.com/docs/model/whisper-large-v3). These are standard listed rates; do not assume cache hits, promotional credits or discounted processing tiers. A free plan exists with quotas, not unlimited free inference.

Both GPT-OSS models accept and return text, support tools, and have **131,072-token context / 65,536-token maximum output on Groq**. Input plus generated tokens must fit the context. These ceilings are not recommended request sizes. OpenAI describes [20B](https://developers.openai.com/api/docs/models/gpt-oss-20b) as 21B total / 3.6B active parameters and [120B](https://developers.openai.com/api/docs/models/gpt-oss-120b) as 117B / 5.1B; both are open-weight MoE models. Groq's serving limits and API options govern this integration.

## Routing research (120B and V3 deferred beyond MVP)

For the agreed MVP, saved text/transcripts enter analysis only on explicit Analyze, and every text task uses 20B. The escalation policy below is a future option.

```text
Manual audio → Whisper Turbo → saved transcript → normal text pipeline
Manual text / parsed Markdown → normal text pipeline
Normal text pipeline → GPT-OSS 20B
Explicit complex task or justified quality escalation → GPT-OSS 120B
```

| Task | Initial route | Proposed effort |
| --- | --- | --- |
| Summary, facts, classification, metadata, basic note processing | Default / 20B | low |
| Straightforward flare or simple user question | Default / 20B | low; medium if evaluated as useful |
| Difficult contradictions, ambiguous evidence, hidden dependencies, complex multi-source synthesis or planning | Reasoning / 120B | medium; high only for demonstrated benefit |
| Re-analysis after an inadequate 20B answer | Reasoning / 120B, once | medium |

Keep a small task-to-profile mapping in the service layer, with a recorded `route_reason`. Multiple sources alone do not require escalation. Missing evidence should produce an insufficient-evidence result; switching models cannot recover unprovided information. Do not escalate on network errors, 429s, oversized context or malformed requests. Repair a recoverable output once on 20B; escalate only for a substantive reasoning failure, within a shared attempt/cost budget. Model self-reported confidence is not a sufficient trigger.

For a later audio version, consider one user-requested accuracy retry on V3 when the original audio is available. MVP uses Turbo only and deletes original audio after processing. Evaluate noisy recordings, names, accents and Russian/English samples before introducing automatic quality thresholds. Preserve the original transcription as provenance if transcript correction is added. V3 also supports English translation, while Turbo does not. Use transcription to preserve the spoken language. [Speech guide](https://console.groq.com/docs/speech-to-text).

## API and request contract

**Recommended client:** one backend `groq.AsyncGroq` instance per process/lifecycle behind the existing AI boundary. The [official SDK](https://github.com/groq/groq-python) supports async chat and audio. Block 2 declares the official Groq SDK in `backend/pyproject.toml`; no OpenAI client is used. The native SDK base URL is `https://api.groq.com`, because its resources add `/openai/v1` themselves.

**OpenAI SDK is a valid alternative:** configure its client with `api_key=GROQ_API_KEY` and `base_url=https://api.groq.com/openai/v1`; an OpenAI account key is not used. Compatibility is partial: avoid `logprobs`, `top_logprobs`, `logit_bias`, `messages[].name`, and `n != 1`. Audio SRT/VTT outputs are unsupported. [Compatibility guide](https://console.groq.com/docs/openai).

Use `POST /openai/v1/chat/completions` (`client.chat.completions.create`) and `POST /openai/v1/audio/transcriptions` (`client.audio.transcriptions.create`), authenticated with `Authorization: Bearer <server key>`. Chat uses JSON `model`, `messages`, and generation options; output is `choices[0].message.content`, with `finish_reason`, `model`, `id`, and `usage`. Prefer Chat Completions for this simple stateless pipeline; Responses is unnecessary. [API reference](https://console.groq.com/docs/api-reference).

**Text profile:** explicitly set `reasoning_effort`, `max_completion_tokens`, `stream=false`, and `include_reasoning=false`. GPT-OSS accepts `low`, `medium`, `high` (default: medium), not `none`; it does **not** support `reasoning_format`. Hiding reasoning does not disable computation. Reserve output capacity for reasoning as well as the final answer; estimate cost from reported completion usage, not visible answer length. [Reasoning guide](https://console.groq.com/docs/reasoning), [parameter reference](https://console.groq.com/docs/api-reference).

Start with temperature 0.2 for extraction, 0.5 for synthesis, leaving `top_p` at its default; tune on examples. Chat supports temperature 0–2 and top_p 0–1; avoid adjusting both simultaneously. Use `max_completion_tokens`, not deprecated `max_tokens`; omit unsupported frequency/presence penalties and metadata. A seed is best-effort, not a determinism guarantee. [API reference](https://console.groq.com/docs/api-reference).

**Structured results:** use `response_format={"type":"json_schema","json_schema":{"name":"note_analysis","strict":true,"schema":...}}` for facts, classifications and flares. Both models support strict mode. All properties must be required, every object must set `additionalProperties:false`; represent optional values with nullable types. Plain `json_object` guarantees JSON syntax only. Structured Outputs currently cannot be combined with streaming or tool use. Validate application semantics and source IDs even with strict JSON; handle refusals, empty content and truncated output before persistence. [Structured Outputs](https://console.groq.com/docs/structured-outputs).

**Tools:** both models support function calling. Requests use `tools` with function names, descriptions and parameter schemas; `tool_choice` can be `auto`, `none`, `required`, or a named function. The response's `tool_calls[].function.arguments` is a JSON string. Validate it, execute an allowlisted function with server-owned workspace identity, and return a `role:tool` message with matching `tool_call_id`. MVP recommendation: no tools or built-in browsing/code execution; the service supplies authorized evidence directly. If added later, cap tool rounds and keep schema-output generation separate. [Tool guide](https://console.groq.com/docs/tool-use/local-tool-calling).

**Audio request:** multipart upload with file bytes, configured model, `temperature=0`, and optional ISO-639-1 `language` (`en` or `ru`; omit when unknown). Do not force English because the UI is English. `json` returns `text`; `verbose_json` additionally supports segment/word timestamps and segment quality metadata. Use `verbose_json` with segment timestamps for provenance; the spelling/context prompt is limited to 224 tokens. Formats: `flac`, `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `ogg`, `wav`, `webm`. [Speech guide](https://console.groq.com/docs/speech-to-text).

Direct attachments are capped at **25 MB**. The guide lists 25 MB total for Free and 100 MB for Developer, with larger inputs sent by URL. Minimum accepted duration is 0.01 seconds; minimum billed duration is 10 seconds/request. Only the first audio track is processed. Propose a smaller MVP cap of **20 MB / 10 minutes**, direct upload, no chunking or arbitrary remote URLs. Groq downsamples to 16 kHz mono; FLAC can reduce size without lossy compression. The guide's parameter table correctly requires `verbose_json` for timestamps; its example comment incorrectly says `json`. [Speech guide](https://console.groq.com/docs/speech-to-text).

## Limits, reliability and costs

Published **Free plan** snapshot (organization-level, not per user):

| Model | Requests/min | Requests/day | Tokens/min | Tokens/day | Audio seconds/hour | Audio seconds/day |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Each GPT-OSS model | 30 | 1,000 | 8,000 | 200,000 | — | — |
| Each Whisper model | 20 | 2,000 | — | — | 7,200 | 28,800 |

Account-specific limits and Developer quotas must be checked in the [organization Limits page](https://console.groq.com/settings/limits); public tables allow exceptions. Track RPM/RPD/TPM/TPD, audio quotas, and any separate input/output TPM. The first exhausted limit wins. Honor `retry-after` and `x-ratelimit-remaining/reset-{requests,tokens}`; request headers refer to daily requests, token headers to TPM. Rate limiting returns 429. [Rate limits](https://console.groq.com/docs/rate-limits).

Proposed initial free-tier text budget: at most 4,000 input tokens plus 2,000 generated tokens; serialize/throttle jobs to the actual shared allowance. The API currently accepts notes up to 200,000 characters: storage acceptance must not imply one model request. Split or select evidence within budget. A 131k context window does not override an 8k/min quota. Larger reasoning budgets need account capacity first.

Proposed timeouts: connect 5s; read 30s for default text, 60s for escalation, 120s for STT; upload write 60s. Also enforce a wall-clock job deadline, initially 5 minutes, because transport timeouts are not total deadlines. These are starting settings, not measured SLAs. Groq SDK defaults to a one-minute timeout and two automatic retries. Set SDK `max_retries=0` if the job runner owns retries, avoiding multiplicative retries. [SDK](https://github.com/groq/groq-python).

Use at most three provider attempts per job, including quality retries/escalation. Retry connection failures/timeouts, 408, 409, 429 and 5xx with exponential backoff and jitter; respect longer `Retry-After` by scheduling later, not sleeping in HTTP handlers. Daily quota exhaustion should defer or fail visibly. Do not blindly retry 400/401/403/404/413/422: repair input/configuration or permissions first. Normalize provider errors into safe application error codes without raw prompts or credentials. A timed-out request may still have consumed quota/cost. [Errors](https://console.groq.com/docs/errors), [SDK](https://github.com/groq/groq-python).

Illustrative standard-rate estimates, not measured operations; all input includes instructions/evidence, output means total reported generated tokens. No caching or retries assumed:

| Operation | Assumption | USD |
| --- | --- | ---: |
| Note extraction on 20B | 2,000 input + 500 output | 0.00030 |
| Simple flare on 20B | 4,000 input + 1,000 output | 0.00060 |
| Same token counts on 120B | 4,000 input + 1,000 output | 0.00120 |
| Complex synthesis on 120B | 8,000 input + 2,000 output; requires sufficient quota | 0.00240 |
| One-minute voice note → 20B extraction | Turbo 60 seconds + first row | 0.00097 |
| Ten-minute transcription | Turbo / V3 | 0.00667 / 0.01850 |

Formula: `input_tokens × input_rate / 1e6 + completion_tokens × output_rate / 1e6`; audio: `max(seconds,10) × hourly_rate / 3600` per request. A Turbo→V3 retry costs both calls. Hosting, database, storage, network, taxes and failed/repeated requests are extra. Prices above link to the four provider model pages.

Record job/request IDs, task/route reason, configured and returned model, prompt/schema versions, input/completion usage (reasoning/cached breakdown where supplied), audio duration, latency, queue wait, retries, status/finish reason, validation outcome and estimated cost. Monitor escalation share, failure rate, p95 latency and per-workspace spend. Never log keys, raw audio, private note bodies or reasoning traces by default. Run a small representative quality set before changing model profiles. [Production recommendations](https://console.groq.com/docs/production-readiness/production-ready-checklist).

## Configuration

The current worker wires text settings in `backend/app/config.py` lazily. The isolated voice boundary exists, while durable STT and 120B escalation remain future configuration:

```dotenv
GROQ_API_KEY=<injected server-side; never committed>
GROQ_BASE_URL=https://api.groq.com
LLM_DEFAULT_MODEL=openai/gpt-oss-20b
STT_MODEL=whisper-large-v3-turbo
LLM_DEFAULT_REASONING_EFFORT=low
# Future options only; do not enable in MVP:
# LLM_REASONING_MODEL=openai/gpt-oss-120b
# STT_FALLBACK_MODEL=whisper-large-v3
# LLM_ESCALATION_REASONING_EFFORT=medium
```

Centralize timeouts, token budgets and retry caps in the same settings/profile definitions. Keep `language` per request, not a global English default. Resolve model IDs only in configuration/provider construction; services choose task profiles. Never expose the key through `NEXT_PUBLIC_*`. Missing AI configuration should disable processing with an explicit error while preserving manual note saving. Verify configured models through Groq's model endpoint during deployment checks, not on every request. [Model catalog](https://console.groq.com/docs/models).

## Repository integration and work remaining

| Existing location | Observed state → recommended change later |
| --- | --- |
| `backend/app/config.py` | Auth settings plus opt-in AI settings; see implemented boundary above. |
| `backend/app/ai_engine/` | TextAnalyzer and FlareDetector contracts, typed validation, Groq adapters, and an isolated Whisper boundary. Durable voice ingestion remains deferred. |
| `backend/app/services/item_service.py`, `models/tables.py` | Notes save and publish synchronously, with no model call → preserve raw input immediately; enqueue analysis on explicit Analyze. |
| `backend/app/services/{file_service,insight_service,storage}.py` | Ingestion/flare orchestration placeholders and storage protocol → add temporary audio staging, transcript and citation-backed flare persistence; permanent audio storage is deferred. |
| `backend/app/workers/` | Functioning PostgreSQL-backed extraction and Flare-generation worker; Celery placeholders are unused. |
| `backend/app/api/routes.py`, `api/analysis.py` | Authenticated Notes-only creation plus explicit Analyze and status routes. Upload remains future work. |
| `frontend/src/lib/data/api-provider.ts` | Rejects non-Note creation; real Notes, Analyze, Flares, and GitHub connection flow; other Sources catalog data remains demo-only. |

Keep the existing dependency direction: **API/workers → services → persistence and AI adapters**. Fetch only authorized, active workspace evidence before calling Groq; bound it by tokens using selected/recent notes and existing keyword search. No embeddings are required: `chunks.embedding` is nullable. Leave the schema's future vector capacity intact.

Use `insights` and `insight_sources` for flares, storing the actual model and prompt version. Validate citations against supplied chunk IDs and text, then save atomically. Keep internal `Insight` names and camelCase payloads until a coordinated contract change.

Two persistence details affect implementation:

- Published versions/chunks are immutable. Store derived analysis separately or publish a new version for corrected transcripts; never rewrite a ready chunk. Existing notes can remain readable even if AI analysis fails.
- `ItemRepository._SELECT_ITEM` joins through `current_version_id`, which can reference only a ready version. A pending upload cannot simply appear through the current query. Add an explicit job/status read path or adjust the item contract/query deliberately.

For durable processing, propose a migration-owned jobs table with workspace/version, task/profile, attempts, next-attempt time, lease and error fields; claim jobs atomically and recover expired leases. Analyze enqueues against already-saved context. An upload requesting transcription must durably stage input before acknowledging its job. Release DB transactions before network calls; recheck authorization/deletion/version before saving results. Deduplicate by input versions, task and pipeline revision. These jobs and the analysis provenance are new work, not existing queue capabilities.

Delivery order is defined in the [agreed MVP plan](MVP_IMPLEMENTATION_PLAN.md), starting with production authentication. Evaluated 120B/V3 escalation is future work. If manual Markdown import is included later, deterministic parsing and a server-enforced one-time onboarding entitlement remain options. Leave source synchronization and embeddings deferred.

**Effort assessment:** provider adapter/configuration is a small task; the working end-to-end MVP is medium scope because jobs, upload/storage, authentication, AI persistence and frontend contracts are unfinished. Changing a model name alone will not enable these flows. Before release, test route selection, schema/citation rejection, cross-workspace isolation, duplicate jobs, retry exhaustion, pending-item visibility and sample EN/RU audio; perform a small live Groq smoke test after credentials and SDK approval.

## Unresolved decisions

- Confirm the Groq organization's exact Free quotas and reachability from the intended Yandex Cloud deployment. No account limits, credentials or live inference were inspected. Paid-tier migration is later work.
- Approve one SDK at implementation time; recommend native Groq now, OpenAI-compatible SDK if cross-provider reuse becomes useful. A Postgres worker is the agreed preference.
- Agree on audio duration/size, recording versus file-upload UX, temporary staging and cleanup after failure. Successful processing deletes original audio; V3 fallback is deferred.
- Select authentication/onboarding and decide how job/analysis status extends the current API contract.
- Define a small 20B quality set, token budgets and prompt/schema versions. Explicit Analyze is settled; any future 120B/V3 escalation requires separate evaluation and scope approval.
- Review Groq data controls: inference content may be retained for reliability/abuse monitoring for up to 30 days; ZDR is available, and retained customer data is stored in the US. Yandex hosting does not keep Groq processing inside that deployment. [Data policy](https://console.groq.com/docs/your-data).

The current `backend/docs/database.md` describes future embedding processing; this MVP deliberately bypasses that step. The linked official pages were researched without reading secrets, installing application dependencies or changing application code.
