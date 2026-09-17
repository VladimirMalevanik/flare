# Flare Release Checklist

Use this checklist for a production release candidate built from `main`. Record the
commit SHA, operator, timestamps, Azure subscription/resource group, and evidence
links with the release ticket. A checked item requires evidence from the exact
candidate or from production after that candidate is deployed.

**Current release status: BLOCKED for verified-email production launch.** The Azure
application stack exists and the public site is reachable, but outbound SMTP has not
been configured or tested. `EMAIL_VERIFICATION_REQUIRED` remains `false` until a
sender domain and SMTP credentials work end to end. Repository, deployment, database,
AI, voice, desktop, and non-verification product checks can continue while that
external dependency is completed.

Current production topology to verify again for every release:

- Azure resource group `flare-dev` in `centralus`.
- Linux App Services `flare-web-vm-260914`, `flare-api-vm-260914`, and
  `flare-worker-vm-260914` on the B1 plan `flare-dev-web-plan`, with no configured
  deployment slots.
- Azure Database for PostgreSQL Flexible Server `flare-dev-pg-vm-260914`.
- Azure Key Vault `flare-dev-kv-260914`, accessed by the API and worker through
  managed identities and Key Vault references.
- Public origin `https://flare4u.tech`; `www.flare4u.tech` is also bound to the web
  app and must redirect to the canonical apex origin before launch.
- Prebuilt artifacts deployed directly with Azure OneDeploy. There is no connected
  repository deployment source or automatic application rollback.

## A. Code gate

- [ ] Record the release commit: `git rev-parse origin/main`.
- [ ] Confirm local `main` is clean and equals `origin/main`:
  `git status --short --branch` and `git rev-parse HEAD`.
- [ ] Confirm every required PR is merged and no release PR is Draft or blocked.
- [ ] Confirm required checks are green for the exact release SHA.
- [ ] Confirm P0 count is zero and P1 release-blocker count is zero.
- [ ] Confirm Alembic has one head and record its revision.
- [ ] Run `git diff --check origin/main^..origin/main` and review the release diff.
- [ ] Identify every change to `backend/pyproject.toml`, migrations, startup scripts,
  Azure packaging, and runtime environment variables before building artifacts.
- [ ] Run the full backend suite against disposable PostgreSQL 17 with pgvector and
  the restricted API/worker roles.
- [ ] Keep the self-managed and Yandex-compatible CI matrices green as regression
  coverage; do not treat them as evidence for the Azure production database.
- [ ] Run frontend tests: `cd frontend && node --test tests/*.test.cjs`.
- [ ] Run frontend lint: `npm --prefix frontend run lint`.
- [ ] Run frontend production build/typecheck: `npm --prefix frontend run build`.
- [ ] Run desktop security tests: `cd desktop && pnpm install --frozen-lockfile && pnpm test`.
- [ ] Confirm no generated artifacts, local environment files, provider responses,
  tokens, private keys, or real credentials are tracked.

## B. Azure infrastructure gate

- [ ] Record the active Azure subscription, tenant, resource group, region, and
  operator without copying access tokens or secret values into release evidence.
- [ ] Confirm the web, API, and worker App Services are `Running` and still use the
  intended Linux runtimes and B1 plan.
- [ ] Confirm `Always On` is enabled for all three services and that the plan has
  enough memory and connection headroom for one web process, one API process, and
  one worker process.
- [ ] Confirm no deployment slot exists. Record the expected brief production
  interruption and the rollback owner before using OneDeploy.
- [ ] Confirm API health check path is `/ready` and web health check path is
  `/api/ready`.
- [ ] Configure and verify the worker health check path `/ready`.
- [ ] Require HTTPS for the web, API, and worker App Services; verify plain HTTP
  redirects instead of serving worker health directly.
- [ ] Confirm the apex and `www` hostname bindings use valid SNI certificates and
  record their expiry dates.
- [ ] Confirm `www.flare4u.tech` redirects every path to the same path on
  `https://flare4u.tech` so host-only sessions are not split between two origins.
- [ ] Confirm the API and worker managed identities can resolve only their intended
  Key Vault references. Do not print resolved values.
- [ ] Confirm Key Vault references cover the API database URL, worker database URL,
  Groq credentials, GitHub App credentials, and, once available, SMTP credentials.
- [ ] Confirm the API and worker can reach Azure PostgreSQL and the required Groq
  endpoints over TLS.
- [ ] Define log retention, availability/queue alerts, notification recipients,
  incident ownership, and the person authorized to roll back a release.

### Email launch blocker

- [ ] Select an outbound email provider and verify a sender on `flare4u.tech` using
  `docs/EMAIL_PROVIDER_DECISION.md` and `docs/EMAIL_SETUP.md`.
- [ ] Store the SMTP connection string in Key Vault; give only the API and worker
  managed identities read access to that secret.
- [ ] Set `EMAIL_FROM` for the API and worker to the verified sender. Keep SMTP out of
  frontend settings and build artifacts.
- [ ] Complete the SMTP and verification smokes in sections E and F.
- [ ] Set `EMAIL_VERIFICATION_REQUIRED=true` only after successful delivery, link
  consumption, resend, and failure-path tests on the public HTTPS origin.

## C. Azure PostgreSQL release gate

- [ ] Confirm Azure PostgreSQL Flexible Server is available and reachable from the
  API and worker App Services over TLS.
- [ ] Record the PostgreSQL engine version, pgvector extension version, database
  name, availability mode, firewall/network policy, backup retention, and restore
  owner without recording credentials.
- [ ] Confirm the migration owner credential is available only for controlled
  migrations and is unavailable to API and worker processes.
- [ ] Confirm the `flare_app` credential passes `/ready` and the expected RLS checks.
- [ ] Confirm the `flare_worker` credential passes restricted worker-role checks.
- [ ] Confirm PostgreSQL reports the required version and the `vector` type exists.
- [ ] Confirm runtime database URLs require TLS and Azure rejects connections that
  do not meet the configured transport policy.
- [ ] Take or confirm a restorable backup or point-in-time restore point before a
  migration.
- [ ] Record the current `alembic_version` before deployment.
- [ ] Apply `alembic -c backend/alembic.ini upgrade head` with the migration owner
  environment only when the candidate contains a migration.
- [ ] Run the migration command again and confirm it is idempotent.
- [ ] Confirm required tenant tables have enabled and forced RLS.
- [ ] Confirm a `flare_app` transaction without workspace context sees no tenant rows.
- [ ] Confirm the worker cannot directly read tenant tables and can execute only its
  reviewed claim/load/finish functions.
- [ ] Restore a production backup or point-in-time snapshot into a separate database
  and run the readiness/security smoke before relying on the backup procedure.
- [ ] Record the connection budget using
  `API process count × pool size + worker concurrency + migration/admin/monitoring headroom`
  and prove it remains below the Azure server limit.

## D. OneDeploy application release

- [ ] Build every artifact from the recorded release SHA and write that SHA into the
  artifact as `RELEASE_SHA` or equivalent immutable metadata.
- [ ] Build the Next.js standalone web artifact on Linux x64. Confirm native modules
  are Linux binaries; do not deploy `sharp` or other native modules built on macOS.
- [ ] If backend dependencies changed, create a fresh Azure-Linux-compatible Python
  runtime. Reusing a previous `antenv` is allowed only when `pyproject.toml` and its
  resolved dependency set are unchanged and reviewed.
- [ ] Build separate API and worker zips. Each must contain the reviewed bootstrap,
  the exact same backend source/runtime archive, and
  `SCM_DO_BUILD_DURING_DEPLOYMENT=false` deployment metadata.
- [ ] Before deployment, download each current App Service `site/wwwroot` as a
  rollback artifact, record its SHA-256, and store it outside the web app.
- [ ] Confirm the rollback artifacts can be opened and contain the prior startup
  script and runtime files.
- [ ] Confirm no analysis job is actively processing, or record how the worker lease
  will recover after its deployment restart.
- [ ] Deploy in compatibility order: worker, API, then web.
- [ ] For each artifact run a tracked deployment such as:

  ```sh
  az webapp deploy -g flare-dev -n <app-name> \
    --src-path <artifact.zip> --type zip --clean true --restart true \
    --track-status true --timeout 900000 --tag <release-sha>
  ```

- [ ] After the worker deployment, confirm its `/ready` endpoint and idle polling
  state before deploying the API.
- [ ] After the API deployment, confirm `/health` and `/ready` before deploying web.
- [ ] After the web deployment, confirm `/`, `/login`, `/download`, and `/api/ready`
  on `https://flare4u.tech`.
- [ ] Confirm Azure deployment status is successful for all three applications and
  that the deployed SHA matches the recorded release SHA.
- [ ] Confirm App Service logs are accessible without exposing cookies, Note bodies,
  provider payloads, database URLs, private keys, or tokens.
- [ ] Run `BASE_URL=https://flare4u.tech python3 backend/scripts/release_smoke.py`.
  For authenticated checks, also set `SMOKE_EMAIL` and `SMOKE_PASSWORD`; set
  `EXPECTED_SUPPORT_EMAIL` only after the support route is verified.

## E. External dependency smoke

### Groq text analysis

- [ ] From the production worker, run the repository's opt-in text smoke using the
  configured model and the Key Vault-backed worker credential.
- [ ] Confirm HTTP 200, structured-output validation, bounded retries, and no API key,
  prompt body, Note content, or raw provider response in logs.
- [ ] Create an eligible Note, press Analyze once, and confirm the worker completes
  extraction and Flare generation with valid evidence.

### Voice transcription: WAV and WebM

- [ ] Confirm the API alone receives `VOICE_GROQ_API_KEY`; the web and analysis
  worker must not receive the voice credential.
- [ ] Confirm `VOICE_FFPROBE_PATH` resolves to the checksum-pinned executable in the
  persistent App Service volume after an API restart.
- [ ] In a clean browser session, confirm the account accepted the current Privacy
  Policy that names Groq, then upload a short valid WAV recording within the
  configured size/duration limits.
- [ ] Confirm the WAV request succeeds, the transcription becomes an editable Note,
  and the Note remains in Vault after refresh.
- [ ] Record a short browser-native WebM/Opus clip through the production UI and
  repeat the same persistence check.
- [ ] Confirm both formats pass bounded media inspection and provider deadlines, and
  that unsupported, malformed, over-size, and over-duration media fail safely.
- [ ] Confirm raw audio is not written to PostgreSQL, object storage, application
  logs, or retry payloads, and that temporary bytes are released after each request.
- [ ] Confirm voice logs contain only safe operational metadata and never audio,
  transcript text, credentials, or provider response bodies.

### SMTP and email verification

- [ ] Register a disposable account with verification enabled and confirm the message
  arrives from the verified `flare4u.tech` sender.
- [ ] Confirm the email link uses `https://flare4u.tech`, verifies once, and cannot be
  reused or altered.
- [ ] Confirm resend succeeds after its cooldown and returns the same neutral response
  for existing and unknown addresses.
- [ ] Confirm a wrong SMTP credential produces an operator-visible failure without
  exposing the credential or verification token.
- [ ] With SMTP deliberately unavailable in a controlled environment, confirm
  registration state remains durable and a later resend can recover.

### PostgreSQL

- [ ] Run `/ready` and one authenticated Note create/read/edit/delete flow.
- [ ] Import one UTF-8 CSV, TXT, or Markdown file and confirm the canonical item,
  batch status, bounded chunks, and provenance persist after refresh.
- [ ] Confirm saving and importing do not consume the daily analysis slot; only
  manual or scheduled Analyze creates the run/job.
- [ ] Confirm all connections use TLS and the intended runtime role.
- [ ] In a controlled environment, interrupt database access and confirm `/ready`
  fails without exposing the URL or credentials; restore access and confirm recovery.

### GitHub, if included in this release

- [ ] Confirm the production GitHub App uses the exact callback URL, requests user
  authorization during installation, has metadata read-only permission, and has no
  unnecessary webhooks or repository permissions.
- [ ] Complete the live authorization, real repository listing, repository selection,
  refresh persistence, disconnect, replay rejection, and unavailable-repository tests
  from `docs/RELEASE_TESTS.md`.
- [ ] If these checks are incomplete, exclude GitHub from release claims or mark the
  release NO-GO. Automated tests alone do not prove the external authorization flow.

### DNS, TLS, and origin behavior

- [ ] Resolve `flare4u.tech` and `www.flare4u.tech` from an external network.
- [ ] Confirm certificate chain, hostname, expiry, and HTTP-to-HTTPS redirect for
  every public hostname.
- [ ] Confirm `www` redirects to the apex origin without losing the path or query.
- [ ] Confirm session cookies are `Secure`, HttpOnly, SameSite=Lax, host-only, and use
  the `__Host-flare_session` name.

### Support

- [ ] Confirm mail sent to `support@flare4u.tech` reaches the approved support inbox.
- [ ] Keep `SUPPORT_EMAIL` only in frontend runtime settings; do not place it in a
  `NEXT_PUBLIC_*` build argument.
- [ ] Open Settings and confirm **Contact support** and **Send feedback** use the exact
  approved address with distinct subjects.

## F. Authentication smoke

The following checks are required with `EMAIL_VERIFICATION_REQUIRED=true`; they
remain a launch blocker while SMTP is unavailable.

- [ ] Register a new account and receive the restricted pre-verification session.
- [ ] Confirm unverified users cannot access Items, Vault, Analyze, Flares, or GitHub.
- [ ] Consume the verification email link once and confirm replay fails.
- [ ] Log in with the verified account and load `/auth/me`.
- [ ] Log out and confirm the previous session no longer authenticates.
- [ ] Confirm a wrong password returns a safe invalid-credentials response.
- [ ] Confirm resend remains enumeration-safe for existing and unknown email.

While verification is temporarily disabled, record that fact on all smoke evidence;
a successful registration in that mode does not satisfy this section.

## G. Core product smoke

- [ ] Capture a Note with a distinctive title and body.
- [ ] Open Vault, find the Note, refresh the browser, and confirm persistence.
- [ ] Edit the Note and confirm the previous immutable version remains available to
  existing evidence while the latest version appears in Vault.
- [ ] Import representative CSV, TXT, and Markdown sources and confirm they remain
  editable where the product allows editing.
- [ ] Press Analyze once and observe pending or processing state.
- [ ] Confirm capture/import/edit persist without analysis jobs; explicit Analyze or
  the configured daily schedule creates one idempotent workspace run.
- [ ] Confirm the worker claims and completes extraction and Flare generation.
- [ ] Confirm the run reaches a terminal state and every published Flare contains
  valid evidence linked to the correct source version.
- [ ] Confirm the once-per-workspace-local-day quota and the T-30 scheduled snapshot
  behavior match `docs/RELEASE_TESTS.md`.
- [ ] Delete a supporting Note and confirm its Flare is no longer exposed.

## H. macOS release and landing order

Publish desktop assets before deploying a landing page that links to them:

1. Merge the desktop code and release workflow into `main`.
2. Tag the exact merged commit as `desktop-v<version>` and push the tag.
3. Wait for the macOS workflow tests and both architecture builds to pass.
4. Publish or verify the non-draft GitHub Release and all four stable asset names.
5. Verify the `releases/latest/download/...` URLs from a logged-out browser.
6. Deploy the landing and `/download` page only after those URLs work.

- [ ] Confirm tag `desktop-v<version>` points to the recorded release commit.
- [ ] Confirm desktop security tests pass on that tag.
- [ ] Confirm the GitHub Release is published, marked latest, and contains exactly:
  `Flare-macOS-arm64.dmg`, `Flare-macOS-arm64.zip`,
  `Flare-macOS-x64.dmg`, and `Flare-macOS-x64.zip`.
- [ ] Confirm both DMG `releases/latest/download/...` URLs resolve successfully before
  deploying the web page that advertises them.
- [ ] Install and launch the arm64 DMG on Apple silicon; install and launch the x64
  DMG on an Intel Mac or an approved x64 test environment.
- [ ] Confirm login, logout, session persistence, GitHub authorization handoff,
  external links, and microphone permission work in the desktop shell.
- [ ] Confirm the download page clearly states that the early-access build is
  ad-hoc signed and not notarized, including the required macOS **Open Anyway** step.
- [ ] Confirm `/download` returns 200 on the apex domain and its architecture buttons
  point to the exact published assets.

## I. Security and isolation smoke

- [ ] Create users in two workspaces and seed distinguishable Notes in each.
- [ ] Confirm list, get, delete, Analyze status, Flares, and GitHub status never expose
  the other workspace's data.
- [ ] Confirm a viewer can read allowed workspace data but cannot create/delete Notes,
  start Analyze, or mutate GitHub connection state.
- [ ] Confirm owner/editor writes succeed only in their workspace.
- [ ] Confirm caller-supplied user/workspace headers do not select identity.
- [ ] Confirm cross-workspace identifiers return the documented denied/not-found
  response and do not reveal whether the target exists.
- [ ] Inspect built frontend and desktop assets and HTTP responses for backend secrets.
- [ ] Confirm production CORS contains only the exact approved HTTPS origins.
- [ ] Confirm registration records acceptance of the current Terms and Privacy Policy.
- [ ] Confirm public pages return CSP, HSTS, frame, MIME-sniffing, referrer, and
  browser-permission headers without breaking registration, voice, or GitHub flows.

## J. Worker and failure smoke

- [ ] Stop the worker after it claims a job; restart it after lease expiry and confirm
  the run resumes without duplicate terminal state.
- [ ] Restart the API during a pending run and confirm the worker completes and status
  remains readable afterward.
- [ ] Simulate a temporary Groq failure and confirm a scheduled retry with bounded
  attempts and a safe public error code.
- [ ] Replay the same `Idempotency-Key` and confirm it returns the same logical run.
- [ ] Confirm malformed or fabricated AI evidence publishes no partial Flare set.
- [ ] Confirm a permanently failed analysis does not modify or hide the saved Note.
- [ ] Confirm SMTP unavailability produces the documented safe registration/resend
  behavior and an operator-visible error without leaking credentials or tokens.
- [ ] As a workspace owner, inspect `/ops/queue`, run maintenance with its default
  dry-run, then apply controlled stale-lease recovery and verify the audit event.
- [ ] Confirm old jobs/results and activity events follow the documented retention
  policy, and configure an alert for a stalled or repeatedly failing queue.

## K. Final production E2E

Run the canonical flow in a clean browser profile against `https://flare4u.tech`:

```text
Register
→ Verify email
→ Login
→ Capture or import evidence
→ Vault
→ Analyze
→ worker completion
→ Flare
→ Evidence
```

- [ ] Record timestamps, account, workspace, run ID, Flare ID, evidence Note ID, and
  log/dashboard evidence without recording secrets or Note contents.
- [ ] Run the GitHub flow only when GitHub is included and all GitHub checks pass.
- [ ] Run WAV and WebM voice flows only after explicit provider consent.
- [ ] Open Settings and verify the configured support actions.
- [ ] Refresh and sign in again to confirm durable PostgreSQL state.

## L. Go / No-Go

Release is **GO** only when all statements are true:

- [ ] P0 count is zero and P1 release-blocker count is zero.
- [ ] The exact release SHA has green required CI and matches all deployed artifacts.
- [ ] The migration chain is valid and production is at the expected revision.
- [ ] Azure PostgreSQL health, TLS, RLS, role separation, connection budget, backup,
  and restore procedure are verified.
- [ ] All three App Services are healthy after OneDeploy and their rollback artifacts
  are available.
- [ ] Groq text analysis and both WAV and WebM voice transcription pass in production.
- [ ] SMTP sends a usable verification email and
  `EMAIL_VERIFICATION_REQUIRED=true` passes the authentication suite.
- [ ] The support address and Settings actions work.
- [ ] The macOS release assets exist before the landing download links are deployed.
- [ ] The final production E2E passes.
- [ ] Every enabled external integration has completed its live smoke.

Any unchecked required item is **NO-GO**. Record the decision maker and evidence.

## M. Rollback

- [ ] Record the SHA-256 and storage location of the pre-release web, API, and worker
  rollback zips before deploying.
- [ ] Record the most recent restorable Azure PostgreSQL backup or restore point.
- [ ] On an application-only regression, redeploy the saved OneDeploy artifacts in
  compatibility order, then rerun worker `/ready`, API `/health` and `/ready`, public
  `/api/ready`, authentication, Note/Vault, and read-only Flare checks.
- [ ] Because the B1 production apps have no deployment slots, record the rollback
  start/end time and expected user-visible interruption.
- [ ] Do not automatically run `alembic downgrade`. Migrations may intentionally
  refuse downgrade or require a reviewed data restore/forward fix.
- [ ] If the previous application cannot safely run with the current schema, stop
  writes and worker processing. The release owner and database owner decide between
  a forward fix and restoring into a controlled database.
- [ ] Never restore over the current production database without preserving
  post-backup data and an explicit incident-owner decision.
- [ ] Record rollback application SHA, schema revision, backup used, data-loss
  assessment, decision maker, and verification evidence.

Name the release owner, database owner, incident commander, and the person authorized
to decide rollback before production launch.
