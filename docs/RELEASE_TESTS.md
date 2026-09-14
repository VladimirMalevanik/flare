# Flare Release Tests

This is the compact P0/P1 manual suite for a production release candidate. Run it
against the exact commit under release after automated CI passes. Use two isolated
browser profiles and two workspaces for authorization cases. Do not record passwords,
tokens, cookies, private Note text, provider payloads, or database URLs in evidence.

Severity meanings:

- **P0:** security isolation, irreversible data integrity, or complete canonical-flow failure.
- **P1:** a required release function is broken with no acceptable workaround.

## RT-01 — Registration, verification, and login

- **Severity:** P1
- **Precondition:** Production email verification is enabled; SMTP and public HTTPS
  origin are configured; the email address is unused.
- **Steps:** Register. Attempt to open Vault before verification. Open the received
  link. Attempt to reuse the link. Log out, then log in with the verified account.
- **Expected:** Registration creates a limited session. Vault is denied before
  verification. The first valid link verifies the account; reuse fails. Login and
  `/auth/me` succeed afterward without exposing a token in application logs.

## RT-02 — Invalid credentials and neutral resend

- **Severity:** P1
- **Precondition:** One verified account exists; a second email is unused.
- **Steps:** Try a wrong password. Request verification resend for both addresses.
- **Expected:** The wrong password returns a safe invalid-credentials response. Both
  resend requests return the same neutral 202 shape; no account-existence detail leaks.

## RT-03 — Session logout and cookie policy

- **Severity:** P1
- **Precondition:** A verified user is logged in over production HTTPS.
- **Steps:** Inspect cookie attributes. Log out. Reuse the previous cookie against
  `/auth/me`.
- **Expected:** Cookie is `__Host-flare_session`, Secure, HttpOnly, SameSite=Lax,
  host-only, and Path `/`. Logout revokes the session; reuse returns 401.

## RT-04 — Note capture and Vault persistence

- **Severity:** P0
- **Precondition:** A verified owner/editor is logged in.
- **Steps:** Capture a uniquely titled Note. Open Vault, search for it, open it, and
  refresh the page.
- **Expected:** The Note appears once with the correct body and remains after refresh.
  It is backed by a ready immutable version and chunk in the same workspace. No
  analysis cycle, daily quota, or job is created until manual or scheduled Analyze.

## RT-05 — Note soft deletion

- **Severity:** P1
- **Precondition:** A persisted Note exists.
- **Steps:** Delete it. Refresh Vault. Request its prior item ID.
- **Expected:** It disappears from Vault and the item route returns 404. Published
  version/chunk history is not overwritten.

## RT-06 — Analyze to Flare to Evidence

- **Severity:** P0
- **Precondition:** A verified owner/editor has sufficient distinctive Note evidence;
  worker and Groq are healthy.
- **Steps:** Press Analyze. Observe status until terminal. Open the new Flare and each
  evidence link.
- **Expected:** Analyze returns a run without blocking on Groq. The worker completes
  extraction then generation. Status becomes completed. Any generated Flare has a
  valid type, evidence quote, and link to the correct Vault Note. A valid empty result
  is accepted only when the input does not support a Flare.

## RT-07 — Analyze idempotency

- **Severity:** P0
- **Precondition:** A workspace has eligible Notes.
- **Steps:** Submit the same valid `Idempotency-Key` twice, including once after the
  run reaches terminal state.
- **Expected:** Both responses identify one logical run. No duplicate analysis job,
  generation run, or Flare set is created.

## RT-08 — Worker restart recovery

- **Severity:** P0
- **Precondition:** A run is pending and the worker can be supervised manually.
- **Steps:** Let the worker claim a job, stop it before finish, wait for lease expiry,
  then restart it.
- **Expected:** A later claim resumes the work. The run reaches one terminal state
  without duplicate results or an indefinitely locked job.

## RT-09 — Groq temporary failure and retry

- **Severity:** P1
- **Precondition:** A controlled method can produce one retryable provider failure.
- **Steps:** Start Analyze, cause the temporary failure, restore access, and observe
  the job through the next attempt.
- **Expected:** The Note stays readable. The job schedules a bounded retry rather than
  sleeping in the API. It completes after recovery or exposes only a safe terminal
  code after attempt exhaustion.

## RT-10 — Invalid AI evidence rejection

- **Severity:** P0
- **Precondition:** A controlled provider stub can return an unknown source ID or a
  quote absent from the supplied chunk.
- **Steps:** Run extraction/generation with the invalid response.
- **Expected:** Validation rejects the whole stage. No partial `insights` or
  `insight_sources` set is published; private provider content is absent from errors.

## RT-11 — Cross-workspace isolation

- **Severity:** P0
- **Precondition:** User A/workspace A and user B/workspace B each have unique Notes,
  run IDs, Flares, and optional GitHub state.
- **Steps:** As A, list data and request B's known item, run, Flare, and GitHub state;
  repeat as B for A. Attempt cross-workspace deletion and mutation.
- **Expected:** Lists contain only the active workspace. Foreign identifiers are
  denied or indistinguishable from missing data. No read, write, delete, or provider
  mutation crosses the workspace boundary.

## RT-12 — Viewer restrictions

- **Severity:** P0
- **Precondition:** A viewer membership exists in a workspace with data.
- **Steps:** Read allowed Notes/Flares, then attempt Note create/delete, Analyze, and
  GitHub connect/select/disconnect.
- **Expected:** Reads allowed by product policy succeed. Every mutation is rejected
  and no database state changes.

## RT-13 — API restart durability

- **Severity:** P1
- **Precondition:** A user is logged in and an Analyze run is pending.
- **Steps:** Restart only the API. Reload the UI and read the run after the API is ready.
- **Expected:** Session, Note, run, job, and Flare state remain in PostgreSQL. The
  worker continues independently and the final result becomes readable.

## RT-14 — GitHub App live flow, conditional release gate

- **Severity:** P1 when GitHub is included; otherwise not run
- **Precondition:** Production GitHub App uses the exact callback URL, requests user
  authorization during installation, has metadata read-only permission only, and has
  no webhooks. A verified owner/editor can install it on at least two repositories.
- **Steps:** Start connection. Complete GitHub authorization. Confirm repository list.
  Select one repository. Refresh and sign in again. Disconnect. Attempt to replay the
  callback state and select an unavailable repository ID.
- **Expected:** State is workspace/user bound and single use. Only authorized
  repositories appear. One selection persists across refresh/login. Disconnect
  removes it. Replay and unavailable selection fail safely. No GitHub token or secret
  is stored or exposed. No commit/PR/issue ingestion is claimed.

## RT-15 — Readiness and database role separation

- **Severity:** P0
- **Precondition:** Production database is migrated and all three credential sets exist.
- **Steps:** Call `/ready`. Connect separately as API, worker, and migration owner.
  Test tenant reads without context and direct worker table reads.
- **Expected:** `/ready` succeeds only at migration `0015` with pgvector and forced
  RLS. API without context sees no tenant rows. Worker direct table reads fail while
  reviewed capabilities work. Runtime processes do not possess migration credentials.

## RT-16 — Final production journey

- **Severity:** P0
- **Precondition:** All prior required tests pass in production; use a clean browser profile.
- **Steps:** Register → Verify email → Login → Capture Note → Vault → Analyze → wait
  for worker completion → open Flare → open Evidence.
- **Expected:** The full journey succeeds on the public HTTPS origin with durable
  state, correct evidence, no cross-workspace exposure, and no P0/P1 errors in logs.

## RT-17 — Bounded text import and idempotency

- **Severity:** P0
- **Precondition:** A verified owner/editor is logged in; the AI worker may be stopped.
- **Steps:** Import one small UTF-8 CSV or Markdown file, repeat the same content under
  another name, refresh Vault, and request both batch results. Try a malformed CSV,
  mismatched extension, binary-like text, and an over-limit body.
- **Expected:** The first import creates one canonical document, bounded chunks, and
  exact batch/version provenance atomically, without creating an analysis cycle or
  job. The duplicate resolves to that document. Invalid inputs return safe validation
  errors and create no partial rows.

## RT-18 — Queue operations and safe analytics

- **Severity:** P1
- **Precondition:** Owner and viewer memberships exist; one controlled stale lease exists.
- **Steps:** Read queue health as owner and viewer. Run default maintenance, then apply
  stale recovery with explicit bounds and delete a controlled activity event older
  than the configured retention. Request the analytics summary; try a view event for
  a nonexistent item and exceed the per-actor browser-event budget in a disposable workspace.
- **Expected:** Only the owner can inspect or mutate queue state. Default maintenance
  is dry-run. Applied recovery and retention affect only eligible workspace rows.
  Analytics contains allowlisted event names and bounded metadata, never imported or
  captured source text. Fake targets are rejected and excess telemetry is dropped
  without breaking the product action.

## RT-19 — Email support configuration

- **Severity:** P1
- **Precondition:** The final support address has been approved. Run once with
  `SUPPORT_EMAIL` set to that address and once with it absent or malformed.
- **Steps:** Open Settings. Inspect and activate **Contact support** in the configured
  case. Inspect the same row in the unconfigured case. Inspect the built client assets
  for backend secrets.
- **Expected:** The configured action is a `mailto:` link to the exact approved
  address. The other case says **Not configured** and has no `mailto:` link. No
  database, SMTP, Groq, GitHub, or other server credential appears in client assets.

## RT-20 — SMTP unavailable behavior

- **Severity:** P1
- **Precondition:** Email verification is required and SMTP failure can be induced in
  a controlled non-production environment.
- **Steps:** Register a new address while SMTP is unavailable. Restore SMTP and request
  resend, then consume the delivered link.
- **Expected:** Registration returns the safe `email_delivery_failed` contract without
  exposing SMTP or token details. Account/workspace state remains durable. Resend stays
  enumeration-safe and can recover after SMTP returns.

## RT-21 — Database unavailable behavior

- **Severity:** P0
- **Precondition:** A disposable release environment can interrupt API database
  connectivity without risking customer data.
- **Steps:** Record healthy `/ready`, interrupt connectivity, request `/ready` and one
  authenticated read, restore connectivity, then retry both.
- **Expected:** Readiness and the product request fail closed with safe 503 behavior;
  no database URL, credential, SQL detail, or demo data is exposed. Both recover after
  connectivity returns without data loss.

## RT-22 — Daily schedule, shared quota, and T-30 snapshot

- **Severity:** P0
- **Precondition:** Use two disposable verified owner/editor workspaces. The worker
  is running, its clock is correct, and one schedule can be set far enough ahead to
  observe the T-30 boundary. Database evidence may be inspected with the migration
  owner; do not use production customer content.
- **Steps:** In workspace A, create eligible source text and submit manual Analyze
  with key K1. Replay K1, then submit a different key K2 on the same local date.
  Change the schedule timezone so the displayed local date changes while less than
  20 hours have elapsed, and retry K2. In workspace B, enable a daily schedule and
  save distinctive source text before T-30. Observe the cycle at T-30, record its
  pinned chunk IDs/count, then edit that source and attempt manual Analyze before
  the scheduled run. Let the scheduled run finish. In the disposable database,
  apply the normal retention cleanup to the detailed terminal rows and inspect the
  corresponding `analysis_daily_quotas` row.
- **Expected:** Both K1 calls identify one logical run and one job. K2 returns exact
  HTTP `409` body `{"detail":"daily_limit"}` both on the original local date and
  after the timezone change. Workspace B reserves the same shared slot at T-30; the manual
  attempt also returns `409 daily_limit`. Its scheduled run is created once from the
  recorded immutable snapshot, so the later edit does not replace pinned evidence.
  Removing retention-eligible job/run/cycle detail does not remove the daily quota
  tombstone or reopen that local date. After the next workspace local date begins
  and at least 20 hours have passed since the prior promised run time, a new slot is
  available.

## Deferred from this release suite

Voice is excluded until its consent-gated upload/provider handoff and cleanup are
implemented. Media inspection and transcript persistence have isolated coverage.
Plan-based allowances beyond the implemented one workspace analysis per local day
are excluded. Full project-history semantics are not guaranteed: Analyze selects a
bounded set from recent eligible sources using keyword and recency signals. Do not
interpret a passing RT-06 as proof of full durable project memory. GitHub activity
ingestion is excluded because only connection metadata is implemented.
