# Paddle Sandbox activation

Owner-authorized activation uses existing Flare Azure resources only. Live Paddle,
new paid resources and unmerged colleague branches are outside this release.
The subsequently accepted WEB-005 landing change is already part of main.

## Confirmed preparation

- PR36 was merged as `f62bc3f43b739bfd1f91b9630553f3f989fef52d`.
  Its exact reviewed head passed both backend profiles and frontend CI. Accepted
  main changes have no changed-file overlap with the billing implementation.
- Azure API, worker and web are running. The production database provider is
  `self-managed`; email verification remains enabled.
- PostgreSQL reports seven-day point-in-time restore retention. This metadata is
  not a restore test or a substitute for a confirmed pre-migration restore point.
- PR40 merged as `e6b831cc51ce80e517490c25327fb0a88559efcd` makes Azure
  deployment releases explicitly use `--latest=false`. This prevents future Azure
  packages from replacing a selected desktop Latest release. Before this fix,
  Latest was already `azure-8679d075ea97`; this change does not claim to restore it.
- Integrated main CI 37324816392 and package build 37325189642 passed at that exact
  SHA. Frontend 177 tests, lint, TypeScript and standalone build also passed before
  subsequent accepted main changes. These preliminary packages must not be
  deployed until the API-002 compatibility fix is integrated and rebuilt.
- All three pre-release private archives were captured and hashed. Existing API
  and worker are `8679d075ea973d2d8ca63e178591fb520642412e`; existing web is
  `b54220213f47f3d165546a05aaac0eb68b39ac1f`. Archives are operator-private and
  deliberately not committed or published.
- Read-only queries through the existing API credential confirmed production head
  `0018` and 26 public tables owned by `flare_admin`. That migration administrator
  is NOSUPERUSER/CREATEROLE/BYPASSRLS. Restricted API/job executor flags remain
  NOSUPERUSER/NOCREATEROLE/NOBYPASSRLS. Its inert executor ADMIN membership has
  INHERIT/SET false, while Azure administration permits effective SET/USAGE.
- API-002 was reviewed independently and merged through PR41 as
  `453ebec4b6592d1e089a3f5d04da0f35a78a4f09`. All six exact-head checks and
  integrated main CI 37329909083 passed. The original failure and full rollback
  were reproduced; the final fix passed 28 restricted-admin PostgreSQL 17 cases,
  29 billing database tests, both complete backend profiles (997 self-managed;
  996 managed plus one expected skip), and preserved-data/repeat upgrades.
- Final package build 37330253646 passed for that exact accepted SHA. Release
  [azure-453ebec4b659](https://github.com/VladimirMalevanik/flare/releases/tag/azure-453ebec4b659)
  supersedes the preliminary e6 packages. Both final archives were downloaded
  privately and verified against the published SHA256 and sidecar checksum,
  ZIP CRC, expected files and embedded RELEASE_SHA. See `validation.json`.
- The public Checkout token and price are configured and match Sandbox; no token
  is reproduced here. Operator login on 2026-10-06 confirmed the Flare Sandbox
  product and active USD12/month price with a 30-day trial.
- Owner-confirmed Sandbox destination `ntfset_01m47zz283676cayy23388e71v` was
  created for the exact API URL and eight subscription events listed below,
  Platform traffic/API1. It is explicitly Inactive while the API is unprepared.
  The endpoint secret was saved as `paddle-sandbox-webhook-secret` in the existing
  Key Vault and compared privately; the temporary local plaintext was deleted.
  Existing API secret permissions remain only `get`/`list`. No API secret
  reference or billing environment settings have yet been applied.
- A 2026-10-06 read-only preflight in the actual API container verified existing
  managed-identity access to the migration credential in memory, full pinned
  source import provenance, schema0018, restricted migration-admin flags and zero
  processing analysis/Flare/refresh work. Existing row-count snapshots are private.
  No production migration was attempted. PostgreSQL remains Ready with7-day
  retention; this remains metadata, not a performed restore.

## Gates before changing production

1. Preserve the private archives and final matching packages. Resolve the recovery
   gate below and confirm a current restore point immediately before migration.
2. After operator login, prepare one disabled Sandbox platform-event destination:
   `https://flare-api-vm-260914.azurewebsites.net/billing/paddle/webhook`. Subscribe
   only to subscription.created, updated, trialing, activated, past_due, paused,
   resumed and canceled. Keep sensitive fields disabled. Store its endpoint secret
   only through the existing server secret mechanism; never put it in frontend
   variables, Git, documentation or raw command output.
3. Set API PADDLE_ENVIRONMENT=sandbox and PADDLE_PRO_PRICE_ID to the configured
   Sandbox price. Keep the destination disabled and billing inactive during the
   transition. Preserve verified-email auth and existing restricted runtime roles.
4. Stop application writes, let in-flight worker work finish, and use a coordinated
   maintenance window: old API expects `0018` while new API expects `0021`. There is no
   common ready schema. Process start or `/health` does not prove compatibility.
5. Upgrade `0018` through `0019`, `0020` and forward-only `0021` from the complete
   exact-SHA checkout. The release ZIP omits migrations/db SQL. Run from that
   checkout's `backend/` directory through the existing Python runtime; confirm
   `app.__file__` points at the checkout before invoking
   `-m alembic -c alembic.ini upgrade head`. This prevents the wrapper's old site-packages from supplying
   stale app settings. Inject the migration credential only into that controlled
   process. Verify head and repeat-upgrade; API/worker keep restricted credentials.
6. Deploy matching API/worker, then web. Check embedded release SHAs, API schema
   `/ready`, and actual worker SQL/job processing. Worker `/ready` alone checks
   liveness. Keep FLARE_IMPORT_STAGING_ROOT unset; local ZIP staging is rejected
   by the production API and is outside this billing rollout.
7. Add PADDLE_WEBHOOK_SECRET to API only, restart API, enable the Sandbox destination,
   and test from a fresh browser tab. Old web checkout lacks the server-bound intent
   and cannot prove new subscription binding. Verify real owner checkout, signed
   delivery, shared workspace Pro, reload, duplicate/cancellation behavior and
   isolation of an unrelated workspace.

## Recovery gate

Migration `0021` cannot be downgraded. The captured old API/worker expect `0018` and
are not a valid application rollback after commit. A source reference compatible
with `0021` is also not proof of an independently validated fallback package.

Azure Flexible Server [PITR creates a new server and requires redirecting clients](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore).
Seven-day retention is therefore not an executable recovery plan within the
current no-new-paid-resources boundary. Before committing the migration, either
prepare and verify a same-schema application fallback, or obtain a concrete
authorized and tested database recovery plan. No such restoration was performed
and no database recovery permission or successful restore is inferred here.

Read-only comparison identified a candidate for temporary core-service recovery:
pin legacy `8679d075ea973d2d8ca63e178591fb520642412e` API/worker/web while retaining
the complete accepted `453ebec4b6592d1e089a3f5d04da0f35a78a4f09`
`backend/app/models/database.py`. This preserves current schema, RLS and private
ledger capability checks; changing only the legacy revision constant is rejected.
Existing analysis SQL/worker contracts are unchanged, and legacy auth uses explicit
columns compatible with the additive migrations. This is source-level evidence,
not a tested or publishable fallback artifact. Billing, ZIP import and new
privacy/growth interfaces would be temporarily unavailable, and verification
provenance would be incomplete. A matching legacy web is required to stop checkout.

Before accepting that candidate, run it under restricted API/worker roles against
disposable PostgreSQL17 upgraded from preserved0018 data through the accepted0021
migration. Verify verified-email registration/login and existing sessions, workspace
isolation, notes/text import/export, queued analysis/scheduler/daily quota, pending
ZIP invisibility, and rejection of deliberately exposed billing ledger permissions.
Pin all package hashes, leave schema/data at0021, and verify Sandbox replay after
returning to the current release. No candidate code was edited or deployed here.

Direct local database access timed out, and the older SSH tunnel returned403.
The official App Service execute path completed the read-only catalog query; no
firewall, TLS or access policy was loosened. Temporary probe source/output contain
no credentials or user data and are removed after collecting the private record.

API-001 and API-002 implementation acceptance is recorded separately. OPS-002
activation remains unfinished: an executable recovery package, cloud
migration/deployment and real Sandbox lifecycle evidence are pending.
No production DDL or deployment was performed during this preparation. Temporary
identity probes and the local migration credential copy were removed. Nonsecret
controlled migration source/preflight output remains operator-private in Azure
until rollout cleanup. The new Sandbox signing secret is stored in Key Vault;
application settings have not changed. No secret, token, private database URL or
raw webhook payload belongs in this report.

## Controlled execution preparation

OPS-003's local behavior report now passes215 historical core tests plus the
preserved-data, new-email verification, restricted queue/Flare, daily-quota,
pending-ZIP, private-ledger and cold-restart scenarios. One obsolete FK-only
assertion is explicitly excluded and replaced with actual restrictive RLS denial
and zero inserted rows. Independent source review and matching Linux artifacts
remain required; no fallback was deployed.

`controlled_migration.py` is an operator-only script, outside the application
package. It defaults to read-only preflight and verifies the SHA256 of a complete
git archive of accepted453ebec, source import location, database host, existing TLS
and migration-admin restrictions. Each run extracts into a fresh exclusive
directory, checks the Alembic graph head0021, and removes that directory. It
retrieves the existing Key Vault migration
credential through the API's existing managed identity, in memory only. The
Alembic child gets a minimal migration-role environment; ordinary API/worker
settings keep their restricted credentials. Only sanitized status and aggregate
counts are written; raw exception/child output is discarded.

Applying requires the explicit503 endpoint from `maintenance_server.py`, zero
active background work, independently confirmed stopped worker and current backup
metadata. The database snapshot is retaken after the maintenance check immediately
before applying; a sanitized post-failure snapshot distinguishes old/new/unknown
schema state without assuming rollback. `maintenance_startup.sh` unpacks the existing runtime for the controlled
process while the maintenance server rejects all public requests. Original
startup and `/ready` health check must be preserved and restored with the matching
accepted application package. Never enable delivery before schema/runtime/secret
reference checks pass. No operator script changes normal runtime or relaxes its
readiness checks. OPS-003 prepares the separate validated recovery package.

Python compilation, shell syntax and seven-method maintenance HTTP checks pass.
The hardened preflight completed in Azure with its exact operator-script checksum,
graph/import verification and temporary-source cleanup. No apply action was run.
