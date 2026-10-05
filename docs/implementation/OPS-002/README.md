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
- Azure deployment releases now explicitly use `--latest=false`, preserving the
  desktop release selected by the website's download links.

## Gates before changing production

1. Capture and hash private current API/worker/web archives and release SHAs.
2. Confirm production schema revision, migration role capabilities and table
   ownership through the existing App Service network path. Direct local access
   timed out; no firewall or TLS policy was loosened.
3. Verify final integrated release CI and matching immutable deployment assets.
4. Run forward-only migration0021 from the complete exact-SHA checkout, using the
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

Dashboard login and real Sandbox lifecycle evidence remain pending. This document
records preparation, not completion of production activation. No secret, token,
private database URL or raw webhook payload belongs in this report.
