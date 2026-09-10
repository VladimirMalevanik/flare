# Analyze: Block 5

The Flares page submits an authenticated, Origin-protected `POST /analyze` with
`Idempotency-Key: UUID` and `{}`. Only owners/editors can start a run. Any current
workspace member can read `GET /analysis-runs/{id}`. Cookies are required even in
development identity mode. No caller-supplied identity or source IDs are accepted.

Selection inspects the most recent 200 eligible Notes (`created_at DESC, id DESC`):
current ready version, immutable chunks, same workspace, not deleted. Per Note,
at most `min(LLM_MAX_SOURCES, 100)` chunks are inspected in ordinal/id order.
Reserve the newest chunk that fits, then rank remaining chunks by distinct explicit
project words (see `SIGNALS` in `context_selection.py`), with recency as the tie-break.
Whole chunks are added only if the complete serialized provider request remains
within `LLM_MAX_INPUT_BYTES` and the source count fits. No embeddings or extra AI
call; no task completion inferred from absent text. Revision: `recent-project-v1`.
No fitting context returns 422 without creating a job.

Migration 0007 adds `analysis_runs`; existing migrations remain unchanged. A
workspace/user/key advisory lock serializes replay. Selection, document locks,
existing durable enqueue, pinned `analysis_job_sources`, and run insertion share
one transaction. A new key creates a new attempt; replay returns the same snapshot
without reselecting, even after edits/deletion. Worker validity checks still apply.
Run metadata is immutable; only its creation timestamp is stored, and mutable
status is derived from existing job/generation rows rather than duplicated.

Capabilities use `flare_job_executor` for self-managed PostgreSQL and `flare_owner`
for Yandex. The table uses FORCE RLS; PUBLIC has no access. The API role can read
its workspace rows and execute start/read capabilities, but cannot mutate runs
directly. The worker cannot read the run table directly. The private enqueue
overload preserves legacy three-argument enqueue semantics.

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

The API receives only its runtime database URL and nonsecret model settings.
The worker receives only its worker URL, provider key and model settings.
The migration URL belongs only to migration; admin password provisioning belongs
to the one-shot configuration service. Keep API and worker model settings aligned.
No secrets are sent in public frontend variables.

## Verification

`check_jobs_migration.py`, `check_flares_migration.py` and
`check_analysis_runs_migration.py` accept `--provider self-managed|yandex` and
`--pg-bin`. They use disposable clusters, preserve old data, repeat upgrades and
check provider ownership. `test_analysis_runs.py` covers HTTP auth/roles/Origin,
bounded selection, concurrency, immutable snapshots, rollback, RLS/status, and
register → Notes → Analyze → fake worker → real persisted Flares (also zero output).
No automated test calls Groq; live Compose acceptance is reported separately.
