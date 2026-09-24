# Analyze: Block 5

The Flares page submits an authenticated, Origin-protected `POST /analyze` with
`Idempotency-Key: UUID` and `{}`. Only owners/editors can start a run. Any current
workspace member can read `GET /analysis-runs/{id}`. Cookies are required even in
development identity mode. No caller-supplied identity or source IDs are accepted.

Migration 0015 adds one daily analysis cycle per workspace local date, enforced by
`UNIQUE(workspace_id, local_date)`. The date comes from the workspace IANA timezone.
Manual Analyze consumes the same slot as the permanent schedule. Replaying the same
idempotency key returns the same run; a different key on that local date returns
`409 daily_limit`. Automatic transient attempts remain inside the same job/cycle.
A terminal failure keeps the slot consumed until the next local date. A second
workspace cycle is also blocked until 20 hours after the prior cycle's run instant. This
keeps the local-calendar UI, allows the normal 23-hour spring DST cadence, and
prevents changing the timezone to obtain a second immediate run. Daily status
returns that recent consumed cycle even when its original local date differs in
the newly selected timezone. A compact `analysis_daily_quotas` tombstone survives
job/run retention, so cleanup cannot reopen a still-active local date, including
the 25-hour day during a fall DST transition.

`GET/PUT /analysis-schedule` manages `{enabled, timezone, localTime}`; the lead is
fixed at 30 minutes. Saving within that lead window defers the first scheduled run
until tomorrow. `GET /analysis/daily-status` exposes the cycle, run, refresh state
and snapshot count. The single worker materializes due cycles, freezes their source
IDs at T-30, and enqueues the pinned snapshot at T. DST gaps and overlaps follow
PostgreSQL `AT TIME ZONE` semantics, so API previews and worker materialization agree.
An edit after T-30 publishes a new version for a future analysis and does not alter
the frozen evidence. An explicit delete is a privacy revocation: if it happens before
the provider receives evidence, validation fails with `source_invalid`, no scheduled
provider output is produced, and the daily quota remains consumed.
Changing or disabling a schedule atomically removes only automatic cycles that have
not created a run; completed, failed and already-enqueued history remains immutable.
Slots more than one hour overdue fail closed instead of producing catch-up runs.
If the editor who last saved a schedule loses write access, the next refresh fails
with `authorization_revoked` and disables that still-unadopted schedule. Another
owner/editor can re-enable it, becoming the new accountable actor.

Selection starts from the 200 most recently updated eligible stored text sources of every
schema type (`note`, `file`, `url`, `audio`; `updated_at DESC, id DESC`): current
ready version, immutable chunks, same workspace, not deleted. Per source, at most
`min(LLM_MAX_SOURCES, 100)` chunks are considered in ordinal/id order, and the
combined candidate pool is capped at four times that source limit (never above 400).
Reserve the newest chunk that fits, then rank remaining chunks by distinct explicit
project words (see `SIGNALS` in `context_selection.py`), with recency as the tie-break.
Whole chunks are added only if the complete serialized provider request remains
within `LLM_MAX_INPUT_BYTES` and the source count fits. No embeddings or extra AI
call; no task completion inferred from absent text. Revision: `recent-project-v1`.
No fitting context returns 422 without creating a job. The response detail is a
fact-based reason: `no_context`, `no_ready_context`, `context_too_large`,
`request_budget_exceeded`, or `unsupported_context`. These codes expose only
selection state, never source text or database details.

Migration 0007 adds `analysis_runs`; migration 0015 adds schedules, cycles and
immutable cycle-source snapshots. A
workspace/user/key advisory lock serializes replay. Selection, document locks,
existing durable enqueue, pinned `analysis_job_sources`, and run insertion share
one transaction. A new key creates a new attempt; replay returns the same snapshot
without reselecting after edits. Deletion still revokes evidence at the worker validity
boundary described above.
Run metadata is immutable; only its creation timestamp is stored, and mutable
status is derived from existing job/generation rows rather than duplicated.

Capabilities use `flare_job_executor` for self-managed PostgreSQL and `flare_owner`
for Yandex. The table uses FORCE RLS; PUBLIC has no access. The API role can read
its workspace rows and execute start/read capabilities, but cannot mutate runs
directly. The worker cannot read the run table directly. The old three-argument
enqueue capability is revoked from `flare_app`; all runtime requests therefore pass
through the run/cycle quota boundary. Migration/admin tests may still exercise the
legacy helper with migration credentials.

The API never invokes Groq. Analysis completion atomically creates the generation
row using the run's pinned revision. Therefore readers cannot observe a legitimate
completion/handoff gap; a missing matching row is reported as `generation_mismatch`.
Only successful generation completes a run, including zero Flares. Terminal error
codes come from constrained job/generation fields, never provider bodies or prompts.

## Local Compose

Provide `POSTGRES_PASSWORD`, `APP_PASSWORD`, and a distinct `WORKER_PASSWORD` in
the Compose environment. For live processing also provide `GROQ_API_KEY` to the
worker. Run `docker compose up --build -d`. The database initializes, migrations
finish, and the one-shot `configure-worker` service sets the restricted worker
role password before the worker starts. The worker runs
`python -m app.workers.analysis_worker`; an absent key fails closed at startup.
GitHub connection metadata is reported as `not_ingested`: repository-content
ingestion is not implemented and the scheduler never claims that it was refreshed.

The API receives only its runtime database URL and nonsecret model settings.
The worker receives only its worker URL, provider key and model settings.
The migration URL belongs only to migration; admin password provisioning belongs
to the one-shot configuration service. Keep API and worker model settings aligned.
No secrets are sent in public frontend variables.

`GET /ops/queue` includes daily-cycle refresh/run backlog, expired refresh leases,
overdue cycles and failures alongside both durable queues. Owner-only maintenance
recovers bounded stale refreshes, fails terminal/overdue cycles, and removes old
failed cycles according to `cycleFailedRetentionDays`. Every scheduled enqueue
outcome is bounded and logged by cycle ID plus a fixed error code; successful
scheduled requests also emit `analysis_requested` with `{mode: "scheduled"}`.

## Verification

`check_jobs_migration.py`, `check_flares_migration.py` and
`check_analysis_runs_migration.py` accept `--provider self-managed|yandex` and
`--pg-bin`. They use disposable clusters, preserve old data, repeat upgrades and
check provider ownership. `test_analysis_runs.py` covers HTTP auth/roles/Origin,
bounded selection, concurrency, immutable snapshots, rollback, RLS/status, and
register → Notes → Analyze → fake worker → real persisted Flares (also zero output).
No automated test calls Groq; live Compose acceptance is reported separately.
