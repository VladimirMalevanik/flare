# Block 3: durable analysis jobs

Internal flow only; Item HTTP routes and Note saving do not enqueue work.
The Block 2 analyzer remains a pure `Evidence[]` component. No Flare/insight
writes, frontend, voice, quotas, embeddings or new dependencies are added.

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
when changing their meaning. Different source order produces the same job.
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
NOCREATEDB. It has no direct tenant-table grants. Its three EXECUTE capabilities:
`claim_analysis_job`, `load_analysis_evidence`, `finish_analysis_job`.

Five SECURITY DEFINER functions (including enqueue and a private validation
helper) belong to dedicated `flare_job_executor`: NOLOGIN, no superuser/BYPASSRLS,
no role members. All revoke PUBLIC execution, use qualified table/function
references and fixed `search_path=pg_catalog,public,pg_temp`. The public schema
must remain non-writable to runtime roles (existing `init-role.sql`).

The executor has explicit queue policies and narrow tenant grants. Tenant tables
remain FORCE RLS; their existing workspace policy is intersected with new
executor requester/membership restrictions. Only this non-login role receives
column UPDATE privileges required for row locks. Worker-supplied workspace/user
GUCs are never used to choose evidence: the validation helper derives context
from the claimed job and verifies its active account, owner/editor membership,
ready chunk versions, Note document type and absence of soft deletion.

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

Provision migrations with an administrator, then set the worker password through
an administrator-only psql process (WORKER_PASSWORD already in its environment):

```sh
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/db/configure-worker.sql
```

Keep the worker's environment separate: it needs `WORKER_DATABASE_URL` for the
restricted role and existing `GROQ_API_KEY`/20B AI settings. Do not give the worker
an admin or API database URL. Migration creates roles; pre-existing conflicting
role names fail closed. Do not commit credentials.

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

The internal enqueue seam is `AnalysisJobService(queue, ai, worker_settings).enqueue(
identity, tuple_of_chunk_uuids)`. The trusted caller owns authentication and source
selection; database authorization is repeated. Nothing calls it from HTTP yet.

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

Limits: one sequential attempt per worker process; no heartbeat, retention cleanup,
public retry or deployment orchestration. Expired-lease recovery requires a running
worker. A crash after a provider response but before commit can repeat a provider
request; lease fencing guarantees one committed result, not exactly-once external
execution. Revocation during an in-flight request cannot unsend evidence, but blocks
persistence. Server-owned DB identities and worker credentials remain trusted.

References: [PostgreSQL locking](https://www.postgresql.org/docs/17/explicit-locking.html),
[FORCE RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html),
[SECURITY DEFINER](https://www.postgresql.org/docs/17/sql-createfunction.html),
[Psycopg connection contexts](https://www.psycopg.org/psycopg3/docs/basic/usage.html),
[Block 2 contract](text-analysis.md).
