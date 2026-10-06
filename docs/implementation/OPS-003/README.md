# OPS-003: temporary core recovery on schema 0021

This is a build and compatibility gate for OPS-002, not authorization to deploy.
It makes no Azure/Paddle changes and never connects to a customer database. A
successful artifact build does not prove production recovery or close activation.

## Exact source boundary

- Legacy API, analysis worker and matching web:
  `8679d075ea973d2d8ca63e178591fb520642412e`.
- The **complete, unchanged** `backend/app/models/database.py` comes from accepted
  `453ebec4b6592d1e089a3f5d04da0f35a78a4f09`. This preserves current schema,
  tenant/ZIP isolation, private billing ledger, narrow capability and function-owner
  checks. A revision-only replacement is prohibited.
- No other accepted application source or dependency is substituted. Those DB
  module imports already exist in the legacy dependency set.
- Source export is deterministic: every blob, mode, origin SHA and SHA256 appears
  in `schema21-core-fallback-manifest.json`, with a checksum sidecar. Export into
  an existing directory is rejected. Verification rejects altered/missing/extra
  files, symlinks, secret filenames and credential-shaped literals.
- Normal runtime files are untouched. The export has no migrations or billing/ZIP
  handlers. Source pins cannot be selected through workflow inputs.

The source export is reproducible. Runtime dependency resolution and native
builds are platform-dependent; the Linux workflow records resolved versions and
checksums the resulting immutable packages. Do not claim byte-identical future
rebuilds without using that dependency inventory and comparing the checksums.

## Local compatibility proof

Use the existing backend development dependency environment, PostgreSQL **17**
with pgvector, and a non-root OS account:

```sh
python backend/deploy/build_schema21_core_fallback.py --self-test
python backend/scripts/check_schema21_core_fallback.py \
  --pg-bin /path/to/postgresql17/bin --report /tmp/schema21-core-check.json
```

The checker creates and removes two private Unix-socket-only clusters. It ignores
ambient database URLs/dotenv/credentials, replaces its environment with controlled
test settings, and blocks Python TCP connections in its process and descendants.
The first cluster migrates accepted source to 0018, seeds verified accounts,
sessions, evidence and a queued daily run, then upgrades 0019–0021 as a fixture
`NOSUPERUSER CREATEROLE BYPASSRLS` administrator. That fixture authority is never
granted to application or worker roles. Every original row and column is compared
before/after the migration; repeat upgrade must preserve it.

Legacy API/worker behavior then verifies:

- Existing verified session and note remain readable; a newly registered account
  is blocked until its captured email token is consumed. Password/session and
  origin checks remain in force.
- The preserved job is processed using deterministic fake providers and produces
  a stored Flare with pinned evidence. No actual inference request is made.
- The consumed daily slot still rejects another `/analyze` with HTTP409
  `daily_limit`.
- An otherwise ready-looking pending ZIP document, version and chunk remain
  invisible in items, raw DB reads and workspace export.
- Foreign workspace reads/deletes and a malicious cross-workspace parent insert
  are denied. The insert must leave zero rows.
- Accepted readiness rejects a deliberately introduced private billing ledger
  grant; after its removal readiness recovers. Checkout intent token hashes remain
  unreadable by `flare_app`.
- Cold PostgreSQL restart preserves the scenario snapshot and schema0021; a new
  API instance accepts the old verified session and reads the preserved note.

Historical core API/queue/Flare/scheduler/quota tests run in the second cluster,
with independent roles and empty queues. Their source assertions are unchanged.
Two historical-fixture differences are explicit:

1. `test_database.py::test_cross_tenant_parent_reference_is_rejected` is excluded,
   **not counted as passed**. It expects only `ForeignKeyViolation`; schema0019's
   restrictive `import_gate` rejects earlier with `InsufficientPrivilege`. The
   checker supplies an actual RLS insert-denial/zero-row replacement.
2. `test_analysis_jobs.py::test_independent_worker_process` runs with explicit
   `FLARE_PROCESS_ROLE=worker`. Inheriting an API role removes its fake worker key
   under the existing secret isolation rules. No legacy assertion or runtime
   code is modified. TCP blocking is retained even when the test overrides its
   child's `PYTHONPATH`.

## Build gate

The manual `azure-schema21-core-fallback.yml` workflow has only `contents: read`.
It runs source integrity and disposable-PG checks, historical frontend tests,
lint, TypeScript and a Linux standalone build. It packages:

- `flare-schema21-core-api.zip`;
- `flare-schema21-core-worker.zip`, from the identical Python runtime;
- `flare-schema21-core-web.zip`, from matching legacy source.

Every package includes the same source manifest plus its component and workflow
release SHA. Artifact upload includes all three ZIP checksums and the behavior
report. There are no Azure logins, server keys, provider tokens, deployment jobs
or automatic migration commands. Linux artifact build and checksum acceptance
remain necessary before OPS-002 may treat this as a usable recovery candidate.

### Dispatch context correction

The first actual GitHub dispatch after PR44 merge failed HTTP422; run
`37430202138` rejected `runner.temp` in job-level `env` at lines20–23. The earlier
YAML parsing and Bash syntax checks did not validate GitHub context availability.
GitHub permits `runner` at step scope, not `jobs.<job_id>.env`: see the
[official context table](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability).

The correction keeps only `PYTHONDONTWRITEBYTECODE` in job-level `env`. The first
Bash step writes the four paths from `$RUNNER_TEMP` into `$GITHUB_ENV`; subsequent
steps inherit them. Actionlint1.7.7 from its official checksum-verified release
reproduced all four original context errors and accepts the corrected workflow.
All ten Bash steps parse, and an execution of the initialization step verifies
the exact four environment records, including paths containing whitespace.
This is a workflow-only change; prior 215-test behavior evidence is preserved,
not claimed rerun. A successful real Linux build is still required.

## Temporary limitations and recovery procedure

This restores core service only. Billing/Pro, ZIP import management and new
acquisition/privacy inspection/withdrawal UI are temporarily unavailable. Matching
legacy web has no Paddle code or checkout dependency. Existing schema0021 billing,
ZIP and growth data stay in the database; there is no downgrade or role weakening.
Legacy email verification preserves its boolean access checks but does not update
the newer `verification_provenance` measurement: new/verified fallback accounts
retain `legacy_unknown`. Normal notes, TXT/MD/CSV import, export and daily analysis
must retain their tested contracts. Legacy exports omit newer ZIP metadata fields.

Only the authorized OPS-002 operator may activate recovery:

1. Pause the Sandbox notification destination and prevent new checkout before
   switching; record the outage interval and delivery state without copying
   tokens or payload secrets into public logs.
2. Verify all three fallback archives/checksums/manifests from the same successful
   run. Coordinate worker/API/web switching on existing resources. Never deploy
   a mixture, run legacy migrations or reduce email verification/daily quotas.
3. Keep schema0021 and current app/worker credentials/permissions. Require current
   readiness and worker-role checks plus core authenticated smoke after switching.
   Communicate the temporary feature limitations to users.
4. When accepted normal artifacts are restored, verify readiness and subscription
   intent/status/webhook routes before enabling checkout or the Sandbox destination.
5. Re-enable Sandbox delivery and inspect/replay notifications from the outage
   through Paddle's existing retry/replay mechanism. Require idempotent handling,
   latest subscription state and entitlement checks; do not assume pausing
   automatically captures every event or that a delivery simulator creates a real
   subscription. Resolve missing events before declaring billing restored.

This candidate does not replace a backup/PITR plan, prove production permissions,
provide full billing availability, or authorize a schema rollback. Acceptance and
actual deployment belong to OPS-002 and the owner.
