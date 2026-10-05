# Paddle Sandbox activation

Owner-authorized activation uses existing Flare Azure resources only. Live Paddle,
new paid resources and the isolated WEB-005 branch are outside this release.

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
- Integrated main CI37324816392 and package build37325189642 passed at that exact
  SHA. Frontend177 tests, lint, TypeScript and standalone build also passed before
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

## Gates before changing production

1. Preserve the captured private archives and confirm a current PostgreSQL restore
   point immediately before the coordinated migration.
2. Review and accept API-002. Migration0021's original guard rejects PostgreSQL17's
   automatic inert administrative membership for a NOSUPERUSER CREATEROLE creator.
   The failure was reproduced on disposable PG17; the fix must preserve executor
   isolation and prove restricted-role migration and transaction rollback.
3. Verify final integrated release CI and matching immutable deployment assets.
4. Upgrade `0018` through `0019`, `0020` and forward-only `0021` from the complete
   exact-SHA checkout, using the
   migration credential only in the controlled migration process. API and worker
   retain their restricted existing credentials. Verify repeat-upgrade and head.
5. Deploy matching API/worker/web packages and verify actual schema readiness and
   worker processing. Worker `/ready` alone is only a liveness signal.
6. Configure one Paddle Sandbox platform-event destination and store its endpoint
   secret only in the existing API secret mechanism. Verify real owner checkout,
   signed event delivery, shared workspace Pro, reload, duplicate and cancellation
   behavior, and isolation of an unrelated workspace.

Migration0021 cannot be downgraded. An old application archive expecting0020 is
not a valid automatic rollback after this migration. Recovery must use a reviewed
same-schema application fallback or a coordinated PostgreSQL point-in-time restore.

Direct local database access timed out, and the older SSH tunnel returned403.
The official App Service execute path completed the read-only catalog query; no
firewall, TLS or access policy was loosened. Temporary probe source/output contain
no credentials or user data and are removed after collecting the private record.

Dashboard login, API-002 acceptance and real Sandbox lifecycle evidence remain pending. This document
records preparation, not completion of production activation. No secret, token,
private database URL or raw webhook payload belongs in this report.
