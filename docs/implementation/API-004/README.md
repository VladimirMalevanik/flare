# API-004 — persistent sign-in

Owner request: keep an already signed-in user in their Flare account when they
return, instead of asking for email/password every time.

## Behavior

The previous session default was seven days absolute expiry but only one day of
inactivity. The API now defaults to a fixed thirty-day lifetime and inactivity
limit (`2592000` seconds). The existing persistent HttpOnly, Secure,
SameSite=Lax, host-only cookie remains the only browser credential. Passwords
and session tokens are not added to localStorage or telemetry.

Opening `/`, `/login`, or `/register` with a valid session redirects to `/vault`.
Email verification and current legal acceptance are checked before that redirect.
Anonymous visitors keep the existing landing and forms. The interactive landing
component was moved mechanically without changing its design or content.

During server rendering, entry routes make no API call when there is no recognized session cookie.
An invalid or expired session shows the public page; a missing membership never
loops into Vault. A backend outage with a presented session uses the existing
retry error screen instead of pretending the user signed out.

Sessions do not renew on activity. Absolute expiry remains fixed, logout revokes
the current session, and disabled accounts and removed memberships remain denied.
Previously expired/revoked sessions are not restored. Existing sessions retain
their original absolute expiry; after signing in again the new cookie and database
session receive the thirty-day lifetime. Clearing browser data, incognito mode or
a different browser still requires sign-in.

Public entry pages also recheck the session when mounted, restored, focused or
made visible in the browser. This returns an already signed-in user from a stale
login form to their account. These bounded client checks do not read the HttpOnly
cookie and leave anonymous forms usable. See [browser-return.md](browser-return.md)
for the October 8 regression and its verification limits.

## Validation

- Frontend: 236 tests, ESLint and production build/type checks passed locally.
- Focused disposable PostgreSQL 17: 81 auth/config/email/legal/isolation tests passed.
- Regression coverage: returning after two and twenty-nine days, unchanged expiry,
  stricter explicit idle overrides, expired/revoked/disabled/membership rejection,
  reopening with the persisted cookie jar, logout, public entry routing and retry.
- Independent review confirmed the mechanical landing extraction and preservation
  of authorization and verification gates; 47 focused frontend checks passed.

## Rollout

Deploy the validated frontend source. Set only `SESSION_LIFETIME_SECONDS=2592000`
and `SESSION_IDLE_SECONDS=2592000` on the existing Azure API. The already deployed
API supports both environment variables, so no backend package, migration,
worker or credential change is necessary to apply the same policy.

Before rollout, retain the existing web package and both prior setting values
(including absence) for rollback. Confirm API readiness after its configuration
restart, anonymous landing/login/register, signed-in entry routing and existing
protected pages. Record actual deployment evidence separately from source tests.
