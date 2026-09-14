# AWS Managed PostgreSQL Readiness

This audit covers migration head `0016`. AWS-managed PostgreSQL is the approved
production direction. The exact AWS service, version, network topology, and capacity
are unresolved, so this document does not select RDS for PostgreSQL, Aurora
PostgreSQL, a deployment region, or a connection proxy.

## Ready in the current design

- Flare uses PostgreSQL 17 SQL, `plpgsql`, row-level security, transaction-local
  settings, advisory locks, and `SECURITY DEFINER` functions with fixed
  `search_path` values. It does not require filesystem or host access at runtime.
- API, worker, and migration credentials are separate. API readiness rejects a role
  with `SUPERUSER`, `BYPASSRLS`, `CREATEDB`, `CREATEROLE`, or inherited role
  membership. The worker performs the same restricted-role checks.
- AWS RDS for PostgreSQL currently lists pgvector among its supported extensions.
  The exact version still depends on the selected engine release; extension upgrades
  are separate from engine upgrades.
- The application accepts libpq connection strings, so TLS parameters can be
  supplied independently in `DATABASE_URL`, `WORKER_DATABASE_URL`, and
  `MIGRATION_DATABASE_URL` without a code change.
- API connections use a bounded pool of 1–10 per API process. The single initial
  worker opens short-lived connections with connect, statement, and lock timeouts.
  Alembic uses `NullPool`.
- The self-managed and Yandex-compatible migration suites remain useful regression
  coverage for standard PostgreSQL and restricted managed-service behavior.

## Needs configuration and a disposable AWS rehearsal

- Select an AWS service and PostgreSQL engine release that exposes the `vector` type
  and supports the chosen pgvector version. Confirm with `SHOW rds.extensions` or the
  equivalent service catalog before migration.
- Create the database and `flare_app` role before `0001`. For an RDS for PostgreSQL
  rehearsal, the existing `self-managed` migration path is the closest current path:
  it creates the no-login function owners and worker login role. Run it only after
  proving that the migration principal owns the database and can create/alter those
  roles. The label describes the migration behavior, not an AWS production approval.
- Give the migration principal only the temporary privileges needed for extension,
  role, schema, function-owner, grant, and policy DDL. RDS does not provide a true
  PostgreSQL superuser; its initial administrator has `rds_superuser` plus
  `CREATEDB`/`CREATEROLE`. Do not give those privileges or that credential to the API
  or worker.
- Set `rds.force_ssl=1` or the chosen service equivalent. Every connection string
  must use `sslmode=verify-full` and an AWS CA bundle, and certificate rotation must
  be an owned procedure. Libpq otherwise defaults to a mode that does not verify the
  server hostname.
- Restrict network reachability to the application server and approved operator or
  migration paths. Security groups, VPC/subnet layout, public accessibility, and DNS
  are infrastructure decisions.
- Budget database connections as
  `API process count × 10 + worker concurrency + migration/admin/monitoring headroom`.
  The instance connection limit, API process count, and any proxy are still TBD.
- Configure automated backup retention and a backup window, then prove point-in-time
  recovery into a separate database. A configured backup is not release evidence
  until a restore drill succeeds.
- Rehearse fresh `upgrade head`, historical upgrade, repeated `upgrade head`, `/ready`,
  RLS isolation, worker capabilities, and application restart against a disposable
  instance of the exact selected service before production.

## Incompatible or needs work

- `FLARE_DATABASE_PROVIDER=yandex` is not an AWS mode. Its `0001` prerequisite check
  requires a membership-free role named `flare_owner` and assumes extensions and
  login roles were created by the Yandex control plane. It must not be used on AWS.
- IAM database authentication is not implemented. Current pools expect a stable
  password-bearing connection string; expiring token generation and pool refresh
  would require reviewed code and operational work if IAM auth is selected.
- No AWS-specific CI or disposable managed-database test exists. Existing green
  PostgreSQL matrices do not prove AWS compatibility.

## Unknown until the AWS service is chosen

- RDS for PostgreSQL versus Aurora PostgreSQL, provisioned versus serverless
  capacity, engine minor version, pgvector version, Multi-AZ/failover behavior, and
  maintenance policy.
- Whether a connection proxy is needed and whether its pooling mode preserves every
  transaction-local assumption under the final workload.
- Final role bootstrap method, secret rotation mechanism, database endpoint/DNS
  behavior, monitoring integration, alert thresholds, and cost limits.
- Exact `max_connections` budget and application process count.

## Required AWS acceptance evidence

1. Record the selected AWS service, engine/extension versions, endpoint, parameter
   group, network path, and role bootstrap procedure without recording credentials.
2. Run the disposable migration and security rehearsal described above.
3. Capture `0016`, pgvector, TLS verification, role attributes, forced RLS, readiness,
   connection-budget, backup, restore, and failover evidence.
4. Keep the result BLOCKED until every item is observed on the selected service.

Current AWS references: [RDS PostgreSQL roles and `rds_superuser`](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Roles.rds_superuser.html),
[RDS PostgreSQL extensions](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html),
[RDS PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html),
and [RDS automated backups](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_ManagingAutomatedBackups.html).
