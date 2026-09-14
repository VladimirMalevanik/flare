# Flare Release Checklist

Use this checklist for a production release candidate built from `main`. Record the
commit SHA, operator, timestamps, environment, and evidence links with the release
ticket. A checked item requires observed evidence from the target release candidate
or production environment.

**Current release status: BLOCKED.** Vova has not yet supplied the application
server, and the exact AWS PostgreSQL service/network, public domain, TLS edge, SMTP
provider, deployment automation, production secrets, and final support email are
TBD. Repository checks can be completed now; infrastructure and production E2E items
must remain unchecked until observed.

## A. Code gate

- [ ] Record the release commit: `git rev-parse origin/main`.
- [ ] Confirm local `main` is clean and equals `origin/main`:
  `git status --short --branch` and `git rev-parse HEAD`.
- [ ] Confirm every required PR is merged and no release PR is Draft or blocked.
- [ ] Confirm required checks are green for the exact release SHA.
- [ ] Confirm P0 count is zero and P1 release-blocker count is zero.
- [ ] Confirm Alembic has one head and it is `0015`.
- [ ] Run `git diff --check origin/main^..origin/main` and review the release diff.
- [ ] Run the full self-managed backend suite against disposable PostgreSQL 17 with
  pgvector and the restricted API/worker roles.
- [ ] Run the full Yandex-compatible backend suite with the CI provisioning model.
- [ ] Review `docs/AWS_POSTGRESQL_READINESS.md` and record the disposable test plan
  for the selected AWS PostgreSQL service. Existing local/Yandex matrices do not
  replace that evidence.
- [ ] Run frontend tests: `cd frontend && node --test tests/*.test.cjs`.
- [ ] Run frontend lint: `npm --prefix frontend run lint`.
- [ ] Run frontend production build/typecheck: `npm --prefix frontend run build`.
- [ ] Run `docker compose config` with a non-production local env file and confirm
  all referenced settings resolve.
- [ ] Confirm no generated/local artifacts or real secrets are tracked.

## B. Infrastructure prerequisites

- [ ] **BLOCKED:** receive the approved single application server from Vova.
- [ ] **TBD:** select VPS provider, country, and size.
- [ ] **TBD:** select public domain structure and create DNS records.
- [ ] **TBD:** select reverse proxy and terminate HTTPS with a trusted certificate.
- [ ] **TBD:** select and provision an AWS-managed PostgreSQL service with a supported
  PostgreSQL 17 release and pgvector.
- [ ] **TBD:** select the AWS region, VPC/subnet path, security groups, public/private
  reachability, failover mode, and database endpoint policy.
- [ ] Confirm the VPS can reach `https://api.groq.com` over HTTPS.
- [ ] **TBD:** select and configure the SMTP provider and verified sender.
- [ ] **TBD:** select deployment automation and secret-injection mechanism.
- [ ] Create separate production env/secret sets for migration, API, and worker.
- [ ] Define log collection, monitoring, alerting, and on-call ownership.

## C. Database release gate

- [ ] Managed PostgreSQL is reachable from the application VPS using TLS.
- [ ] The selected AWS service passes every required item in
  `docs/AWS_POSTGRESQL_READINESS.md`; record service, engine, and pgvector versions.
- [ ] The migration owner credentials connect and are unavailable to API/worker.
- [ ] The `flare_app` credentials connect and pass `/ready` role/RLS checks.
- [ ] The `flare_worker` credentials connect and pass restricted worker-role checks.
- [ ] PostgreSQL reports version 17 and the `vector` type is available.
- [ ] Database clients use `sslmode=verify-full` with the current AWS CA bundle, and
  the service rejects non-TLS connections.
- [ ] Take or confirm a restorable backup before migration.
- [ ] Record the current `alembic_version` before deployment.
- [ ] Apply `alembic -c backend/alembic.ini upgrade head` with the migration env.
- [ ] Confirm the one applied version row is `0015`.
- [ ] Run the migration command again and confirm it is idempotent.
- [ ] Confirm required tenant tables have enabled and forced RLS.
- [ ] Confirm a `flare_app` transaction without workspace context sees no tenant rows.
- [ ] Confirm the worker cannot directly read tenant tables and can execute only its
  reviewed claim/load/finish functions.
- [ ] Record backup identifier, retention, and restore owner.
- [ ] Restore the backup or point-in-time snapshot into a separate database and run
  the readiness/security smoke against it.
- [ ] Record the connection budget using
  `API process count × 10 + worker concurrency + migration/admin/monitoring headroom`
  and prove it stays below the selected service limit.

## D. Application deployment gate

- [ ] Deploy the exact recorded commit to the application VPS.
- [ ] Run the frontend, API, and worker as separate supervised processes.
- [ ] Confirm exactly one worker is enabled for the initial release.
- [ ] Configure automatic restart with a bounded backoff for each process.
- [ ] Confirm the frontend responds on its internal port.
- [ ] Confirm API `/health` returns success.
- [ ] Confirm API `/ready` returns success against production PostgreSQL.
- [ ] Confirm the worker starts with `flare_worker` and reaches an idle polling state.
- [ ] Confirm public HTTPS routes pages and `/api` to the intended processes.
- [ ] Confirm process logs are accessible without exposing cookies, Note bodies,
  provider payloads, database URLs, or secrets.
- [ ] Run `BASE_URL=https://<release-origin> python3 backend/scripts/release_smoke.py`.
  For authenticated read checks, also set `SMOKE_EMAIL` and `SMOKE_PASSWORD`; set
  `EXPECTED_SUPPORT_EMAIL` after the final contact address is configured.

## E. External dependency smoke

### Groq

- [ ] From the production VPS, make the repository's opt-in text smoke request using
  the worker secret environment and the configured `openai/gpt-oss-20b` model.
- [ ] Confirm HTTP 200, returned model acceptance, structured-output validation, and
  no key or prompt/body leakage in logs.

### SMTP

- [ ] Register a disposable production-domain account.
- [ ] Confirm the message arrives from the configured sender and its link uses the
  production HTTPS origin.
- [ ] Confirm a wrong SMTP credential produces an operationally visible failure
  without exposing the credential or verification token.
- [ ] With SMTP deliberately unavailable, confirm registration remains durable,
  returns the documented safe delivery failure, and a later resend can recover.

### PostgreSQL

- [ ] Run `/ready` and one authenticated Note create/read/delete flow.
- [ ] Import one UTF-8 TXT or Markdown file and confirm the canonical item, batch
  status, bounded chunks, and analysis jobs persist after refresh.
- [ ] Confirm all connections use TLS and the intended runtime role.
- [ ] In a controlled environment, interrupt database access and confirm `/ready`
  fails without exposing the URL or credentials; restore access and confirm recovery.

### GitHub, if included in this release

- [ ] Configure a production GitHub App with user authorization during installation,
  the exact callback URL, metadata read-only permission, no webhooks, and no other
  repository permissions.
- [ ] Complete the live test cases in `docs/RELEASE_TESTS.md` for authorization,
  repository selection, refresh persistence, and disconnect.
- [ ] If those checks are not complete, exclude GitHub from the release scope or mark
  the release NO-GO; automated tests alone do not satisfy the recorded live gap.

### DNS and TLS

- [ ] Resolve every public hostname from an external network.
- [ ] Confirm the certificate chain, hostname, expiry, and HTTP-to-HTTPS redirect.
- [ ] Confirm session cookies are `Secure`, HttpOnly, SameSite=Lax, host-only, and use
  the `__Host-flare_session` name.

### Support

- [ ] **TBD:** Vladimir supplies the final domain-based support email.
- [ ] Set `SUPPORT_EMAIL` only in the frontend runtime and restart the frontend; do
  not place it in `NEXT_PUBLIC_*` build arguments.
- [ ] Open Settings and confirm **Contact support** points to the exact approved
  address. With the variable absent or malformed, confirm Settings shows **Not
  configured** and renders no `mailto:` link.

## F. Authentication smoke

- [ ] Register a new account and receive the restricted pre-verification session.
- [ ] Confirm verification email delivery and consume its link once.
- [ ] Confirm reusing or altering the verification token fails.
- [ ] Log in with the verified account and load `/auth/me`.
- [ ] Log out and confirm the previous session no longer authenticates.
- [ ] Confirm a wrong password returns a safe invalid-credentials response.
- [ ] Confirm an unverified account cannot access Items, Vault, Analyze, Flares, or
  GitHub integration routes.
- [ ] Confirm resend returns the same neutral response for existing and unknown email.

## G. Core product smoke

- [ ] Capture a Note with a distinctive title and body.
- [ ] Open Vault, find the Note, refresh the browser, and confirm persistence.
- [ ] Press Analyze once and observe pending or processing state.
- [ ] Confirm capture/import/edit persist versions without analysis jobs; explicit
  Analyze still creates one idempotent workspace run.
- [ ] Confirm the worker claims and completes extraction and Flare generation.
- [ ] Confirm the run reaches completed state; an evidence-backed Flare appears when
  the fixture has sufficient evidence.
- [ ] Open each evidence item and confirm it navigates to the correct Vault Note and
  displays the quoted source text.
- [ ] Delete a supporting Note and confirm its Flare is no longer exposed.

## H. Security and isolation smoke

- [ ] Create users in two workspaces and seed distinguishable Notes in each.
- [ ] Confirm list, get, delete, Analyze status, Flares, and GitHub status never expose
  the other workspace's data.
- [ ] Confirm a viewer can read allowed workspace data but cannot create/delete Notes,
  start Analyze, or mutate GitHub connection state.
- [ ] Confirm owner/editor writes succeed only in their workspace.
- [ ] Confirm caller-supplied user/workspace headers do not select identity.
- [ ] Confirm cross-workspace identifiers return the documented denied/not-found
  response and do not reveal whether the target exists.
- [ ] Inspect built frontend assets and HTTP responses for backend secrets.
- [ ] Confirm production CORS contains only the exact HTTPS frontend origin.

## I. Worker and failure smoke

- [ ] Stop the worker after it claims a job; restart it after lease expiry and confirm
  the run resumes without duplicate terminal state.
- [ ] Restart the API during a pending run and confirm the worker completes and status
  remains readable afterward.
- [ ] Interrupt API database connectivity and confirm `/ready` returns 503, product
  data is not replaced by demo data, and readiness recovers after connectivity does.
- [ ] Simulate a temporary Groq failure and confirm a scheduled retry with bounded
  attempts and a safe public error code.
- [ ] Replay the same `Idempotency-Key` and confirm it returns the same logical run.
- [ ] Confirm malformed or fabricated AI evidence publishes no partial Flare set.
- [ ] Confirm a permanently failed analysis does not modify or hide the saved Note.
- [ ] Confirm SMTP unavailability produces the documented safe registration/resend
  behavior and an operator-visible error without leaking credentials or tokens.
- [ ] As a workspace owner, inspect `/ops/queue`, run maintenance with its default
  dry-run, then apply a controlled stale-lease recovery and verify the audit event.

## J. Final production E2E

Run the canonical flow in a clean browser profile against the public production URL:

```text
Register
→ Verify email
→ Login
→ Capture Note
→ Vault
→ Analyze
→ worker completion
→ Flare
→ Evidence
```

- [ ] Record timestamps, account, workspace, run ID, Flare ID, evidence Note ID, and
  log/dashboard evidence without recording secrets or Note contents.
- [ ] Run the GitHub flow only when GitHub is explicitly included in this release and
  all GitHub checks in section E pass.
- [ ] Open Settings and verify the configured email support action.

## K. Go / No-Go

Release is **GO** only when all statements are true:

- [ ] P0 count is zero.
- [ ] P1 release-blocker count is zero.
- [ ] The exact release SHA has green required CI.
- [ ] The migration chain is valid and production is at `0015`.
- [ ] PostgreSQL health, TLS, RLS, role separation, and backup are verified.
- [ ] The exact selected AWS service passed the disposable migration and restore
  rehearsal; the connection budget is recorded.
- [ ] Groq returns HTTP 200 from the production VPS.
- [ ] SMTP sends a usable production verification email.
- [ ] The final support email is configured and the Settings contact action works.
- [ ] The final production E2E passes.
- [ ] Every enabled release integration has completed its live smoke.

Any unchecked required item is **NO-GO**. Record the decision maker and evidence.

## L. Rollback

- [ ] **TBD:** replace these placeholders with commands for the selected deployment
  tooling before the first production release.
- [ ] Keep the previous application artifact/image and its immutable commit SHA.
- [ ] On application-only regression, stop new rollout processes, restore the previous
  frontend/API/worker artifact together, restart them, and rerun `/health`, `/ready`,
  auth, Note/Vault, and read-only Flare checks.
- [ ] Do not automatically run `alembic downgrade`. Migrations may intentionally
  refuse downgrade and may contain data/security changes that require a reviewed
  restore plan.
- [ ] If the new application cannot safely run with the current schema, stop writes
  and worker processing. The release owner and database owner decide between a
  forward fix and restoring the pre-migration backup into a controlled database.
- [ ] Never restore a database over the current production database without preserving
  post-backup data and obtaining the incident owner's explicit decision.
- [ ] Record rollback start/end, application SHA, schema revision, backup used, data
  loss assessment, decision maker, and verification evidence.

**TBD / deferred.** Name the release owner, database owner, incident commander,
and the person authorized to decide rollback before production launch.
