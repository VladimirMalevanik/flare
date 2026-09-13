# Flare MVP implementation plan

Agreed scope, 2026-09-07; implementation status updated 2026-09-13. This plan governs MVP scope; broader model-routing and storage options in earlier research are future work.

Related technical research and architecture:

- [AI model research](AI_MODELS.md): provider APIs, model capabilities, pricing, limits and integration details.
- [Backend architecture](../backend/docs/architecture.md): layer boundaries.
- [Database design](../backend/docs/database.md): workspace isolation, immutable versions and citations.
- [Frontend API contract](../frontend/docs/API_CONTRACT.md): existing data shapes and adapters.

## Current status

- Blocks 1–4: implemented and merged (authentication, 20B extraction, durable jobs,
  persisted evidence-backed Flares, and Yandex-compatible migrations).
- Email verification and the GitHub App connection flow are merged. GitHub activity
  ingestion is not implemented and the real GitHub handshake still needs live smoke.
- Block 5 is merged: explicit Analyze, bounded current source selection,
  immutable job sources, idempotent runs, status API, frontend polling and Compose worker.
  New Notes and text imports also enqueue durable analysis automatically. Live Groq
  acceptance requires a local worker key.
- Voice and quota work remain outside this change.

See [Block 4 implementation](../backend/docs/flare-generation.md).

## Goal

Build the first complete production-shaped vertical slice:

```text
Login → save project context → Analyze → background AI processing
      → GPT-OSS 20B → extracted facts → evidence-backed Flares
      → show real Flares in frontend
```

Deliver a high-quality MVP that stays within free provider limits during early testing and can move to paid Groq without redesign.

## Core principles

- The unified monorepo is the source of truth.
- Use production-quality authentication from the start; preserve strict user, workspace, membership and permission boundaries.
- Save raw input before AI processing. Processing must be asynchronous, durable and retryable.
- Back Flares with evidence; missing evidence must not produce invented conclusions.
- Keep infrastructure simple, enforce shared free-tier quotas and make paid-tier limits a configuration change.
- Preserve RLS, soft deletion, immutable published versions and existing API/service/persistence boundaries.

## Phase 1 — Authentication

Implement real user identity, login, workspace membership and roles/permissions. Replace development identity for real users. Verify identity and membership on the server before selecting workspace context; preserve the restricted database role and RLS. Define workspace creation and initial-owner provisioning. This is durable product authentication, not disposable MVP auth.

## Phase 2 — Groq text integration

Use **Groq API** with **`openai/gpt-oss-20b` only** for MVP text processing. No 120B routing, embeddings or external agent framework.

Add centralized backend configuration, server-side `GROQ_API_KEY`, and one async Groq client/provider behind `ai_engine`. Keep model IDs out of business logic and all keys out of frontend code. Produce structured JSON for facts, decisions, intentions, problems and entities where useful. Validate schema and meaning before persistence; record the selected route, actual model and prompt/schema versions.

## Phase 3 — Durable jobs / worker

Prefer a simple Postgres-backed worker; introduce Redis/Celery only if a concrete requirement makes it necessary.

Separate saving from analysis:

```text
Save context → commit raw input → return successfully (no LLM call)
Analyze → persist job referencing saved context → return job status
Worker → claim job → call AI outside DB transactions → validate/persist results
```

For an operation that both accepts input and requests processing, save input and enqueue atomically, return successfully, then process separately. Audio upload requests transcription, not automatic Flare generation.

Jobs need persistent status, attempts, retry scheduling, atomic claim/lease, deduplication and recovery after worker crashes. Bound retries and preserve input when Groq fails. Recheck workspace authorization, source deletion and version state before saving results. Repeated Analyze requests or retried jobs must not create duplicate Flares.

Expose processing/error status without hiding saved notes. The current item query reads through the published version, so pending uploads and analysis jobs need a deliberate status contract. Never keep a note-save HTTP transaction open while calling AI.

## Phase 4 — Real Flares

Replace mock Flares with backend-generated records. Reuse `insights` / `insight_sources` internally where appropriate; user-facing terminology remains **Flare**.

Each Flare must contain:

- Type: **Recommendation / Reminder / Warning**.
- Title, statement, specific action when applicable, and reason.
- Evidence/citations with source IDs and chunk IDs.
- Creation timestamp and model/prompt provenance.

Validate citations against the exact evidence supplied to the model, including workspace ownership and quoted text. A weak single mention should not automatically become a Flare. Allow an empty result or an insufficient-evidence outcome. The public taxonomy is separate from extraction categories. The frontend keeps the internal `Insight` name with the typed Flare DTO; legacy untyped insights remain hidden.

## Phase 5 — Analyze flow

**Explicit Analyze remains the workspace-level MVP trigger.** Context accumulates
until the user presses Analyze; a worker then analyzes a bounded workspace snapshot
and new Flares appear. New Notes and bounded text imports also enqueue their own
immutable source chunks for background extraction; HTTP requests never call Groq.

Bound evidence by token budget using authorized project context without vector retrieval. Record the input versions used for a run. Frontend must show pending, completed, failed and quota-deferred outcomes through the existing data-provider layer.

Leave room for daily, every-N-days, weekly and eventually proactive scheduling, but do not build scheduling now.

## Phase 6 — Audio MVP

```text
Audio upload → Whisper Turbo → persist transcript as context
             → same text pipeline on explicit Analyze
```

Use **`whisper-large-v3-turbo`**, free-tier limits and configurable per-user/workspace quotas. Persist the transcript before deleting the original audio; retain source identity and useful timestamps in text provenance.

Do **not** retain original audio after processing. Use minimal private temporary staging sufficient for asynchronous retries and crash recovery, not permanent audio storage or a complex object-storage subsystem. Define a bounded cleanup policy for failed/abandoned uploads; tell the user when retransmission is required after expiry. Successful transcript persistence is the boundary after which audio can be deleted without losing the saved context.

No V3 automatic fallback and no 120B reasoning initially. Permanent audio storage and retranscription are later product options.

## Phase 7 — Free-tier guardrails

The MVP must be usable without payment details. Groq quotas are **organization-level**, shared across users and workers. Starting values from the dated [AI research](AI_MODELS.md):

| Model | Requests/min | Requests/day | Tokens/min | Tokens/day | Audio seconds/hour | Audio seconds/day |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GPT-OSS 20B | 30 | 1,000 | 8,000 | 200,000 | — | — |
| Whisper Turbo | 20 | 2,000 | — | — | 7,200 | 28,800 |

Verify the actual organization limits before implementation/deployment; these are planning values, not a guarantee of account capacity. See [official rate limits](https://console.groq.com/docs/rate-limits).

Implement shared quota accounting, configurable per-workspace/user allowances, throttling, bounded token/audio budgets and graceful exhaustion. Concurrent workers and retries must count against the same allowance. Defer or reject processing visibly when exhausted while keeping saved context accessible; do not start runaway retry loops.

Free → Developer should change configured budgets and provider account settings, not the pipeline. Basic caps and retry bounds are required before any live AI testing; complete quota enforcement is a release gate, even though it appears late in the delivery order.

## Current MVP non-goals

- GPT-OSS 120B routing, V3 fallback, Voyage, embeddings or a vector-retrieval dependency.
- Telegram, GitHub, Gmail, App Reviews, Notion or Linear synchronization.
- Redis/Celery unless required, fine-tuning or an autonomous agent framework.
- Permanent audio storage, complex object storage for audio or automatic scheduled analysis.

Existing pgvector/schema capacity can remain unused; this scope does not require removing it.

## Suggested implementation order

1. Production authentication.
2. Groq 20B adapter/configuration.
3. Structured text extraction.
4. Durable jobs and worker.
5. Real Flare persistence/API.
6. Frontend real Flares.
7. Analyze action.
8. Audio upload and Whisper Turbo.
9. Complete free-tier quota enforcement.
10. End-to-end hardening/tests.

Phases 2–3 can be developed as isolated components; expose production analysis only once durable jobs and explicit Analyze are connected. Block 5 connects the explicit trigger to durable jobs; see [Analyze flow](../backend/docs/analyze.md).

## Definition of MVP

A real user can register/login, enter a workspace, add notes/context, see it persisted after refresh, press Analyze, receive asynchronous analysis, see real Recommendation/Reminder/Warning Flares, inspect their evidence, and add a voice note with a saved transcript. Other workspaces remain inaccessible.

The system survives provider failures, retries safely, preserves raw text and successful transcripts, respects free-tier quotas, rejects fabricated evidence, and can move from Groq Free to Developer without architectural changes. Original audio follows the temporary retention policy above.

Acceptance checks must cover authentication/roles, cross-workspace reads and writes, persistence after refresh, crash recovery and duplicate jobs, invalid citations, insufficient evidence, provider failures/quota exhaustion, audio cleanup, and the complete frontend flow. The complete MVP gate still depends on the live Analyze acceptance, audio and quota slices.

## Decisions still needed

- Exact configurable user/workspace quotas, Analyze context/token budgets and the organization's available free limits.
- Temporary audio staging location, maximum upload size/duration and expiry/cleanup behavior after terminal failure or crash.
- Representative Flare quality evaluation on real project data.
- Groq data-retention settings: application-side audio deletion does not control provider retention; see [AI research](AI_MODELS.md).

Settled for MVP: 20B only, explicit Analyze, Postgres worker preferred, no embeddings, no automatic V3 fallback and no permanent audio retention.

## Block 6 status

- **6A implemented:** real browser Blob recording and isolated Groq Whisper Turbo
  provider boundary with audio/transcript validation and mock-transport tests.
- **6B pending teammate API/DB review:** FastAPI upload, server media duration
  inspection and durable transcript persistence through the ordinary Note path.
  Voice end-to-end is not ready; no automatic Analyze or permanent audio storage.

See [voice boundary and 6B requirements](../backend/docs/voice-transcription.md).
