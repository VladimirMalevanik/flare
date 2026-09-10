# Block 4: real Flares

The input is a completed `TextAnalysis` plus the parent's pinned, authorized
chunks. This stage does not select project history. There is no Analyze endpoint,
frontend trigger or automatic analysis after Note saving; those belong to Block 5.

## Two durable stages

`analysis_jobs` remains the extraction queue. Migration `0006_real_flares.py`
adds `flare_generation_runs`, unique by parent job and generation revision, with
workspace-safe parent FK, four states (pending/processing/completed/failed),
attempts, `available_at`, lease owner/token/expiry, timestamps, safe error and
metadata, and up to three persisted Flare IDs. Evidence is not copied.

An AFTER-completion trigger inserts the generation run inside the extraction
completion transaction. `WorkerJobs.finish` sets the generation revision locally
in that transaction; the revision hashes prompt/schema/model/effort and bounds.
Legacy SQL callers without this setting create an `unconfigured` run, which fails
closed as `generation_mismatch`. Deploy updated workers with the migration.
Existing completed jobs can use internal `FlareRuns.enqueue(parent, revision)`;
repeated enqueue is idempotent and does not rerun extraction or reset failed work.

The existing worker alternates stage priority and handles one attempt at a time:

`claim COMMIT/close → load parent/evidence COMMIT/close → await detector → finalize`

Claims use SKIP LOCKED and fresh lease tokens. Expired leases are reclaimable;
stale tokens cannot persist. Exhausted expired runs fail during bounded claim
cleanup. Transient errors reuse Block 3 exponential jitter/backoff and Retry-After;
the SDK never retries. Stage 2 retries never rerun extraction. Configuration,
auth, invalid request/output, revoked access, source invalidation and generation
mismatch fail terminally. No user retry or requeue interface is exposed.

## Detector contract

`FlareDetector.detect(TextAnalysis, Evidence[]) → FlareResult` is separate from
TextAnalyzer. The official Groq async SDK uses the centrally configured
`openai/gpt-oss-20b`, low effort, strict JSON Schema, `include_reasoning=false`,
`stream=false`, and zero SDK retries. Any finish reason other than `stop` fails.

Output is `{flares: [{type, title, statement, action, reason, evidence}]}`:

- At most three candidates; no minimum. Types: Reminder, Warning, Recommendation.
- Title 80 characters/12 words; statement 180/30; action 160/24; reason 240/40.
  Action may be null except for Recommendation. Fields are single-line plain
  text; statement/action/reason use one sentence. No truncation or quota filling.
- Evidence has `source_id`, exact `quote` (240 characters maximum), and structural
  `supports` labels: goal/state/constraint/commitment/relevance/conflict.
  At most four entries and one quote per chunk. Extra output fields are forbidden.
- Invented sources/quotes and malformed output fail the whole response. Exact
  matching uses the extraction whitespace normalization, never fuzzy matching.
  Insufficient semantic support drops the candidate; an empty result completes.
- Reminder requires commitment/constraint plus present relevance. Warning needs
  conflict or repeated unresolved trouble. Recommendation needs an explicit,
  unambiguous goal, current state/constraint and specific action. Model instructions
  and conservative structural/lexical checks enforce these gates; labels are not
  proof of meaning and these checks cannot guarantee semantic quality.

Configuration shares existing AI key/model, deadlines and evidence limits:

| Variable | Default | Meaning |
| --- | --- | --- |
| `FLARE_MAX_COMPLETION_TOKENS` | 1024 | Separate generation completion budget |
| `FLARE_MAX_REQUEST_BYTES` | 32000 | Serialized request safety bound, not token accounting |

Oversized input fails without truncation. Bump prompt/schema versions when changing
their meaning; revision changes allow new generation results. No live Groq call
is part of automated validation.

## Persistence and security

Reuse `insights`: existing title and body (statement), new type/action/reason,
parent analysis ID, generation/schema revision and SHA-256 candidate fingerprint.
Existing model/prompt fields remain provenance. Legacy summary becomes nullable;
old rows remain intact. PR #6 adds a Yandex path to migrations 0001/0004/0005;
the self-managed SQL they emit is unchanged. `insight_sources.quote` stores
exact evidence with deterministic ordinal; legacy null ordinals remain valid.

Fingerprint includes workspace, generation revision, type, normalized prose,
explicit null action, and canonically sorted chunk IDs/quotes. Workspace uniqueness
dedupes repeated/concurrent identical candidates, including across parent jobs;
the first row keeps its provenance and later runs reference it. New revisions may
create new rows. There is no semantic dedupe across differently worded candidates.
Flares, citations and completed run commit atomically; final lease expiry rolls
back all inserts. Empty valid output completes with zero IDs.

`flare_worker` retains no direct tenant-table access, superuser or BYPASSRLS.
It receives only four extra EXECUTE capabilities: enqueue, claim, load and finish
generation. SECURITY DEFINER functions belong to `flare_job_executor` (NOLOGIN)
on self-managed PostgreSQL and to the pre-provisioned `flare_owner` on Yandex.
Yandex creates no `flare_job_executor`. Both paths use qualified objects and a
fixed `pg_catalog,public,pg_temp` search path,
and revoke PUBLIC execution. FORCE RLS remains enabled. `flare_app` loses direct
INSERT/UPDATE/DELETE on insights and citations; its read access remains tenant-bound.

Load and finalize derive identity from the parent and repeat active-account,
owner/editor membership, ready immutable source and soft-deletion checks. Narrow
account/member/document row locks serialize revocation and deletion with writes.
No lock or connection survives the detector await. Finalization rechecks every
citation against the pinned parent. Python persists only allowlisted metadata;
neither raw provider output, exception bodies nor hidden reasoning is stored.

Read-only `/flares` endpoints exclude legacy rows and hide the entire Flare if
any supporting document is deleted. Historical rows remain stored. See the
[API contract](../../frontend/docs/API_CONTRACT.md). API mode has no Flare mock
fallback; development mock mode has independently curated fixtures.

## Checks and remaining limits

With disposable migrated PostgreSQL and runtime/admin test URLs, from repo root:

```sh
pytest -q backend/tests/test_flare_detector.py backend/tests/test_flare_runs.py backend/tests/test_flares_api.py
pytest -q backend/tests
python backend/scripts/check_flares_migration.py --pg-bin /path/to/postgresql/bin --provider self-managed
python backend/scripts/check_flares_migration.py --pg-bin /path/to/postgresql/bin --provider yandex
python backend/scripts/check_jobs_migration.py --pg-bin /path/to/postgresql/bin --provider self-managed
python backend/scripts/check_jobs_migration.py --pg-bin /path/to/postgresql/bin --provider yandex
python -m pip check
node --test frontend/tests/*.test.cjs
npm --prefix frontend run lint
npm --prefix frontend run build
git diff --check
```

Migration check creates its own cluster, verifies eleven populated tables and
historical source order across 0005 → 0006, repeat upgrade and atomic handoff.
The older migration checker remains pinned to 0004 → 0005. Both scripts create
fresh clusters and support both providers; Yandex DDL runs as restricted
`flare_owner`, not the bootstrap administrator. The full CI matrix tests actual
`flare_app` and `flare_worker` connections, capability ownership, table/column
privileges, PUBLIC execution, FORCE RLS, persistence, deletion and lease fencing.

## Deployment compatibility

Existing self-managed databases stamped at 0005 do not replay rewritten migrations.
The self-managed SQL emitted by 0001/0004/0005 is unchanged, so these installations
can apply 0006 without a corrective migration solely for PR #6. Rewriting history
is an acceptable pre-production tradeoff for fresh provider-specific installs;
freeze these files for production. This does not provide in-place provider conversion.
A restored or existing database must retain its role/ownership topology or undergo
a separately reviewed conversion/bootstrap before selecting Yandex mode. The
provider flag alone neither transfers ownership nor reapplies policies.

Use separate explicit dotenv files for API, worker and migration processes. API
Flare reads require only `DATABASE_URL`; generation runs in the worker with
`WORKER_DATABASE_URL` and `GROQ_API_KEY`. Migration credentials are excluded from
both runtime processes. The default dotenv-discovery path permits the union of
API/worker secrets; deployments must enforce the split with selected role files
or separately injected environments. Tests exercise worker generation and API
reads in separate processes without migration credentials.

Block 6B must decide how transcription fits the worker-owned Groq key. Do not add
a synchronous API-to-Whisper path by copying the key into the API environment.

Provider calls remain at-least-once across crash-after-response-before-commit.
There is no heartbeat, retention cleanup, production deployment verification or
real-provider quality evaluation. Revocation cannot unsend an in-flight request.
The small completion budget may reject otherwise useful responses as incomplete.
Semantic gates are intentionally conservative and may miss useful candidates.
Browser acceptance remains pending because automatic tool approval was blocked;
passing provider tests and builds do not substitute for that check.
