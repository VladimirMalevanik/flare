# Block 3: durable analysis jobs

`POST /items` now creates documents for all supported input types and enqueues
durable analysis jobs for the new chunks when AI/worker configuration is valid.
Invalid configuration never rolls back ordinary item capture. The Block 2 analyzer remains a
pure `Evidence[]` component. Block 4 adds a separate [Flare generation stage](flare-generation.md)
after completion; extraction still persists only `TextAnalysis` on its job.

## Schema and dedupe

Migration `0005_analysis_jobs.py` adds:

- `analysis_jobs`: workspace/requester, task (`text_analysis`), pipeline revision,
  SHA-256 dedupe key, `pending | processing | completed | failed`, attempts/limit,
  `available_at`, lease owner/token/expiry, timestamps, safe error code, result and
  metadata JSONB. Partial indexes cover runnable jobs and expired leases.
- `analysis_job_sources`: ordered immutable chunk references, with composite
  workspace FKs to both the job and chunk. No raw input body is copied into it.

Uniqueness covers workspace + requester + task + fingerprint of sorted chunk
IDs and pipeline revision. The revision hashes prompt/schema versions, configured
20B model, low reasoning effort and input/output bounds. Bump prompt/schema version
when changing their meaning. Different source order produces the same job. Since migration 0006, future source
ordinals follow document creation time, document ID, version number, chunk ordinal
and chunk ID. Sorted UUIDs remain only the dedupe input; historical ordinals stay unchanged.
Requester identity is included so one user's job cannot replace another's request.

Repeated/concurrent enqueue returns the same job, including completed/failed jobs;
it never automatically resets terminal work. Retry attempts reuse that job.
A future authorized requeue can reset a failed row's attempts/status/timestamps
without replacing its identity or uniqueness key. No requeue capability is exposed.

## Security and transaction boundary

`flare_app` retains its existing RLS restrictions. It can execute enqueue and read
only its requester's jobs in the selected workspace while the account is active
and membership exists. It cannot mutate queue tables or call worker functions.
Only real `auth_users` identities with owner/editor membership can enqueue.
Existing string membership IDs and migrations 0001–0004 are unchanged.

`flare_worker` is LOGIN, NOSUPERUSER, NOBYPASSRLS, NOINHERIT, NOCREATEROLE and
NOCREATEDB. On self-managed PostgreSQL migration `0005` creates it; on Yandex
Managed PostgreSQL it must be created through the Yandex Cloud control plane
before migrations. It has no direct tenant-table grants. Its three EXECUTE
capabilities: `claim_analysis_job`, `load_analysis_evidence`,
`finish_analysis_job`.

Five SECURITY DEFINER functions (including enqueue and a private validation
helper) belong to dedicated `flare_job_executor` on self-managed PostgreSQL. It
is NOLOGIN, has no superuser/BYPASSRLS and has no role members. Yandex Managed
PostgreSQL does not allow creating that custom role, so the functions belong to
the database owner `flare_owner`; its connection URL is restricted to migration
operations and never enters the API or worker environment. All functions revoke
PUBLIC execution, use qualified table/function references and a fixed
`search_path=pg_catalog,public,pg_temp`. The public schema must remain
non-writable to runtime roles. Block 4 adds four separate generation
capabilities; no direct worker table grants.

On self-managed PostgreSQL the executor has explicit queue policies and narrow
tenant grants. On Yandex Managed PostgreSQL `flare_owner` necessarily retains
the broader ownership privileges used for migrations, so its credentials must
remain outside runtime environments. Tenant tables remain FORCE RLS; their
existing workspace policy is intersected with new executor requester/membership
restrictions. Worker-supplied workspace/user GUCs are never used to choose
evidence: the validation helper derives context from the claimed job and verifies
its active account, owner/editor membership, ready chunk versions, supported source
type and absence of soft deletion.

Every capability uses its own connection context:

`claim COMMIT/close → evidence COMMIT/close → await analyzer → finalize COMMIT/close`

Finalization locks only the job, requester account, requester membership and
referenced documents (`FOR SHARE`, ordered by document ID). This serializes with
account disable, role change/revoke and document deletion. It checks authorization,
source state and the current lease before writing, and checks lease expiry again
after possible lock waits. Invalidated authorization discards result and metadata.
Ready snapshots remain pinned even if a newer document version is published.

## Processing and recovery

Atomic claim uses `FOR UPDATE SKIP LOCKED`, increments attempts and creates a fresh
UUID lease token. Expired processing jobs can be reclaimed; old tokens cannot
load evidence or finalize. A crash on the last allowed attempt is marked failed
by a bounded cleanup within subsequent claims (up to 100 rows per call).

Successful completion also inserts a Stage 2 run in the same transaction through
a migration-0006 trigger. The worker supplies the configured generation revision.
Stage 2 retries reuse the completed extraction result.

The processor checks pipeline compatibility, bounds evidence before loading,
calls the existing analyzer, then repeats typed parsing and exact quote/source
validation. It stores `TextAnalysis` plus allowlisted model/ID/usage/finish/latency/
validation metadata on the job. No SDK body, reasoning or exception text is stored
or logged. Input-byte bounds are safety limits, not token accounting; Block 2 also
checks serialized request size. Oversized inputs fail without truncation.

Retry only when both normalized code and retryable flag permit it:
`rate_limited`, `timeout`, `network`, `provider_transient`, `provider_server`.
Delay is `min(cap, base * 2^(attempt-1) * uniform(0.5,1.5))`, raised to Retry-After
when that finite, nonnegative hint is longer. No sleep in a DB transaction; the
job returns to pending with `available_at`. Attempts exhausted or permanent
errors become failed. Pipeline mismatch, invalid evidence/output and unexpected
analyzer errors are terminal. Database failures leave leases for crash recovery.

## Configuration and running

For self-managed PostgreSQL, provision migrations with an administrator, then
set the worker password through an administrator-only psql process
(WORKER_PASSWORD already in its environment):

```sh
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/db/configure-worker.sql
```

Keep the worker's environment separate: it needs `WORKER_DATABASE_URL` for the
restricted role and existing `GROQ_API_KEY`/20B AI settings. Do not give the worker
an owner or API database URL. In self-managed mode the migrations create the
legacy NOLOGIN function-owner roles and `flare_worker`; pre-existing conflicting
role names fail closed. In Yandex mode `flare_owner`, `flare_app` and
`flare_worker` are created through Yandex Cloud before migration and worker's
password is managed there, so `configure-worker.sql` is not used. See the
[Yandex Managed PostgreSQL guide](yandex-managed-postgresql.md). Do not commit
credentials.

| Variable | Default |
| --- | --- |
| WORKER_DATABASE_URL | Required, no fallback |
| ANALYSIS_MAX_ATTEMPTS | 3 (1–10) |
| ANALYSIS_LEASE_SECONDS | 120; must exceed AI deadline by >30 seconds, at most 3600 |
| ANALYSIS_POLL_SECONDS | 1 |
| ANALYSIS_BACKOFF_SECONDS | 5 |
| ANALYSIS_MAX_BACKOFF_SECONDS | 300; Retry-After can exceed it |

DB connect/statement/lock timeouts are 3/10/5 seconds. AI deadline remains 40 seconds
by default. Invalid startup configuration fails before claiming jobs. SDK retries
remain disabled. From `backend/` with the backend package/dependencies installed:

```sh
python -m app.workers.analysis_worker          # SIGINT/SIGTERM finish current job
python -m app.workers.analysis_worker --once   # at most one job; may call Groq
```

Trusted ingestion services call `public.enqueue_analysis_job` inside the same
transaction that creates immutable chunks: `ItemService` handles `/items`, and
`ImportService` handles `/imports`. Authentication and source selection remain
server-owned; database authorization is repeated by the function.

## Checks and limits

From the repository root, configure disposable `DATABASE_URL` (flare_app),
`TEST_DATABASE_URL` (administrator) and `WORKER_DATABASE_URL` (flare_worker):

```sh
pytest -q backend/tests/test_analysis_jobs.py backend/tests/test_analysis_worker.py
pytest -q backend/tests
python backend/scripts/check_jobs_migration.py --pg-bin /path/to/postgresql/bin
python -m pip check
git diff --check
```

The migration check creates/stops a separate temporary cluster, requires pgvector
and a non-root OS user, and compares seven populated tables across 0004 → 0005.
Tests use fake analyzers, including a separate process and a blocked analyzer
while checking `pg_stat_activity`; they never require a live Groq call.

Limits: one sequential attempt per worker process; no automatic heartbeat,
scheduled maintenance, public retry or deployment orchestration. Workspace owners
can inspect the queue and run bounded retention/stale-lease maintenance through
`/ops/queue`, but a production scheduler/alert destination still has to invoke it.
A crash after a provider response but before commit can repeat a provider request;
lease fencing guarantees one committed result, not exactly-once external execution.
Revocation during an in-flight request cannot unsend evidence, but blocks
persistence. Server-owned DB identities and worker credentials remain trusted.

References: [PostgreSQL locking](https://www.postgresql.org/docs/17/explicit-locking.html),
[FORCE RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html),
[SECURITY DEFINER](https://www.postgresql.org/docs/17/sql-createfunction.html),
[Psycopg connection contexts](https://www.psycopg.org/psycopg3/docs/basic/usage.html),
[Block 2 contract](text-analysis.md).
