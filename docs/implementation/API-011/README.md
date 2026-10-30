# API-011 — password recovery

The CJM identified no way to recover a forgotten password (F02). This adds complete
forgot/reset screens and API support using existing SMTP. It also closes related
auth resource and concurrency problems found while implementing recovery.

## Decisions

- A 256-bit opaque token is stored only as SHA-256, expires after 30 minutes and
  works once. The email uses the configured public origin, never the Host header.
  Its fragment is removed on client initialization and never persisted in browser
  storage. Another fragment opens a fresh document. Both routes are noindex, use
  no-referrer metadata and are
  outside the existing analytics page allowlist.
- Recovery requests return the same conditional 202 before account lookup or
  SMTP. Global missing mail configuration gives 503 for every address. A bounded
  in-process dispatcher admits at most 32 jobs with four workers; it is not a
  durable mail queue. Process interruption can require another explicit request.
- The server serializes requests per account: a 60-second cooldown, at most five
  live links, and no invalidation of earlier confirmed sends on resend. SMTP
  failure may mean an acknowledgement was lost: the new link remains usable.
  A later request retires unconfirmed attempts after the cooldown, allowing
  recovery after a crash without filling all slots for 30 minutes.
- Password and all of that user's sessions change atomically. All reset links are
  removed in the same transaction. Other accounts, workspace identity, email
  verification, legal acceptance and quotas stay unchanged. Login rechecks the
  locked user/hash so an old verification cannot create a session after reset.
  Expiry uses wall-clock time after acquiring locks. A notification is queued
  after commit; notification failure cannot undo the reset. No automatic login.
- Public auth bodies are bounded to 8 KiB and ten seconds before JSON parsing.
  Expensive password work is limited to two concurrent operations per process
  with a 500ms admission wait. Reset operations also have two slots; DB acquisition,
  statements and locks are bounded. A busy response preserves the link, returns
  429 with Retry-After, and tells the user to retry. This is a resource guard, not
  a billing or AI allowance change.
  Known rolled-back database contention is retryable; an unknown server/transport
  outcome is shown as unconfirmed so the user checks sign-in before another link.
- Existing configured SMTP is used even when verification is optional. No new
  service, dependency, secret, cloud resource or provider configuration is added.

The UX follows existing Flare auth panels, fields, menu, type and buttons. Terminal
states focus the heading; actions reflect the outcome. Uncertain changes invite
sign-in with the new password before another request. A server error never
pretends that the password definitely stayed unchanged. Both locales are covered.

Security reference: [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
Effect cleanup follows [React documentation](https://react.dev/reference/react/useEffect).

## Persistence and validation

Migration 0027 adds only private recovery state and a nullable cooldown timestamp.
It preserves existing password hashes, sessions and verification links. CI now
seeds a 0026 fixture, upgrades, verifies preservation, and repeats the upgrade in
both database profiles. Startup rejects missing columns, worker/PUBLIC table or
column grants, app ownership, grant options and missing/excess app table privileges.

Local checks use a disposable PostgreSQL 17 instance, fake mail and synthetic
accounts. The focused acceptance tests cover concurrent links, login/reset race,
expiry after a lock wait, transaction rollback, unknown/disabled users, cooldown,
state caps, uncertain SMTP, crash recovery, notifications, stream/deadline limits,
password resource admission and privilege drift. Frontend tests exercise actual
component behavior, fragment cleanup/replay, locale, form checks, duplicate
submissions, unmount, uncertain outcomes and the analytics allowlist.

The full local suite has environment limits: public env-example fixtures are
deliberately absent and the reused dependency runtime has no editable install for
an isolated child-process test. The exact locked CI checkout remains required;
no tests or assertions were skipped or weakened to accommodate the local setup.
The exclusive database-clone check was rerun successfully with the browser fixture
on a separate database.

Browser checks use the actual forms, auth request helper, API and restricted-role
database with a local-only memory inbox, real Flare fonts and mark. Confirmed:
fragment removed; noindex; mismatch feedback; changed password accepted; old
password rejected; no automatic login. No real mail or production write occurred.

## Release acceptance

Release matching web/API/worker artifacts with schema 0027 through the existing
operator process. Verify readiness and use an operator-controlled mailbox to test
request, delivery, link, reset, old-session rejection and sign-in. Existing SMTP,
sender and public-origin settings are sufficient. A successful SMTP authentication
check alone does not establish real inbox delivery. API-005 and its analysis
investigation remain Vova's task.
