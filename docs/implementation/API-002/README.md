# API-002 — PostgreSQL 17 billing migration compatibility

Migration `0021` now supports a PostgreSQL 17 migration administrator with
`NOSUPERUSER CREATEROLE`. The previous membership guard rejected the role creator's
automatic administrative grant before any billing tables could be created.
The failure was reproduced under a real restricted login after `0018 → 0020`;
Alembic rolled back the new executor and tables and retained schema `0020`.

## Role and transaction boundaries

PostgreSQL creates an automatic membership from the new executor to its creator:
`ADMIN TRUE, INHERIT FALSE, SET FALSE`, with bootstrap-superuser grantor OID 10.
The migration permits only this exact inert edge to its current restricted
`CREATEROLE` administrator. It continues rejecting unsafe executor attributes,
all memberships of the executor in other roles, and every other incoming edge.
The known `flare_app`, `flare_worker` and registration `flare_onboarding` principals
cannot act as billing migration administrators, even if accidentally elevated.

A non-superuser administrator receives a separate, temporary self-granted
`SET TRUE, INHERIT TRUE, ADMIN FALSE` membership, explicitly recorded with that
administrator as grantor. `SET` is needed for ownership transfer; `INHERIT` is
needed for subsequent function-owner DDL. The migration revokes only its own
membership after function grants/settings and schema-CREATE cleanup, then
rechecks the executor's restricted role/membership state. The bootstrap grant
remains. A connection's `createrole_self_grant` setting is temporarily cleared
only during fresh role creation and immediately restored.

The retained ADMIN edge is **not a security boundary against the migration
administrator**: it can explicitly grant itself access again. That administrator
is trusted and must remain outside API/worker processes. Existing administrator
capabilities, including an already-present Azure BYPASSRLS privilege, are not
changed or copied to the executor. Runtime users gain no new role memberships,
table mutations, private-ledger reads, or private-helper execution.

Alembic's existing transaction encloses the role grants and DDL. Failure after
function ownership transfer rolls back the temporary grant and all new billing
objects; an existing executor's original administrative grant is preserved.
The `yandex` managed-owner branch is unchanged. Billing SQL, webhook validation,
entitlements, auth, quotas, frontend and deployment configuration are unchanged.

This is a compatibility correction to the rollout-blocking `0021`, not a new
schema revision. A later migration cannot repair a preceding migration that
fails before committing. No cloud DDL, new resources, secrets or Live Paddle
changes were performed by this task. Deployment and final Azure verification
remain with OPS-002.

## Reproducible verification

From `backend/`, with existing development dependencies, pgvector, and PostgreSQL
17 binaries:

```sh
python scripts/check_billing_restricted_admin.py --pg-bin /path/to/postgresql17/bin --billing-tests
python scripts/check_analysis_runs_migration.py --pg-bin /path/to/postgresql17/bin --provider self-managed
python scripts/check_analysis_runs_migration.py --pg-bin /path/to/postgresql17/bin --provider yandex
```

The new checker always creates and removes its own Unix-socket-only temporary
cluster, without ambient database URLs or dotenv. Bootstrap provisions the
existing `0018` fixture; the actual `0019 → 0021` DDL connects as a separate
`NOSUPERUSER CREATEROLE NOCREATEDB` login. Legacy executor administration is granted
only to that fixture administrator to model pre-existing ownership rights;
provider-specific Azure administrator behavior is not emulated.

It verifies 28 behavioral cases: four connection self-grant settings, exact
membership cleanup, existing-creator reuse, new/existing-role post-transfer
failure rollback, all original unsafe executor flags, outgoing/foreign/runtime
memberships, wrong bootstrap options, non-bootstrap inert/effective self grants,
misconfigured runtime and registration principals, preservation of existing
administrator BYPASSRLS, actual Alembic upgrade and repeat upgrade, FORCE RLS,
private-ledger/helper denial and no runtime SET/inherited executor access. The
29 billing database tests then run on that restricted-migration schema, covering
atomic events, ordering, lifecycle and tenant isolation.

The complete backend suites run separately on the repository's existing CI role
models. Legacy tests assume their fixture administrator owns public objects and
that the legacy job executor has no administrative members; running them all on
the new restricted-administrator fixture initially exposed three such fixture
assumptions, plus two dotenv failures caused by keeping the migration-only dotenv
disable flag during that experimental test invocation. No product fixes were
made for those assumptions. The restricted checker therefore runs the relevant
billing database suite; full regressions use clean standard provider fixtures.

Primary references:

- [PostgreSQL 17 role attributes and automatic creator grants](https://www.postgresql.org/docs/17/role-attributes.html)
- [PostgreSQL 17 membership options and explicit grantors](https://www.postgresql.org/docs/17/sql-grant.html)
- [PostgreSQL 17 revocation and grantor boundaries](https://www.postgresql.org/docs/17/sql-revoke.html)
- [PostgreSQL 17 connection self-grant setting](https://www.postgresql.org/docs/17/runtime-config-client.html#GUC-CREATEROLE-SELF-GRANT)
- [PostgreSQL 17 bootstrap role OID](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/include/catalog/pg_authid.dat)
- [Azure PostgreSQL administrator and public-schema behavior](https://learn.microsoft.com/en-us/azure/postgresql/security/security-access-control)
