# API-004 — restoring an entry page

The owner reports being asked to sign in after closing and reopening an ordinary
Yandex Browser window. The thirty-day server session and persistent secure cookie
are already deployed. The exact browser cookie-loss cause is not confirmed.

A separate reproducible gap remained: the landing, login and registration pages
checked a session only during their server render. An already open anonymous form
could remain visible after signing in in another tab or restoring a cached page.

These three entry pages now also recheck the existing session on client mount,
page restoration, focus and becoming visible. A valid account goes to Vault;
email verification and legal acceptance retain their original priority. Guests,
revoked sessions and removed memberships stay on the public page. Network,
timeout and malformed-response failures leave the form usable.

Checks include credentials and bypass the cache. Each page permits one request
at a time, bounds it to ten seconds and cancels it when unmounted. Late responses
cannot navigate after cancellation. No cookie contents, password, account data
or session tokens are persisted by this component.

This change cannot recreate an expired or browser-deleted cookie. The absolute
thirty-day expiry and explicit logout are unchanged. Actual owner Yandex Browser
close/reopen acceptance remains separate from source and lifecycle tests.

## Validation before rollout

- All 252 frontend tests passed; ESLint and the production build/type checks passed.
- Forty focused entry/lifecycle tests cover repeat checks after an anonymous result,
  account gates, hidden pages, concurrent events, timeout, cleanup and late responses.
- A separate synthetic local API and the current frontend were used in the Codex
  browser: the initial login page was anonymous, sign-in in a second tab opened
  Vault, and returning to the first page through Privacy/Back opened Vault without
  entering credentials again. This checks browser history restoration, not a
  Yandex Browser process restart. The synthetic API is not production PostgreSQL.
- Independent source review found no blocking issue. A verified current web
  package and unchanged API/worker release pins were retained for rollback.

Roll out only the frontend artifact from the exact tested merge. Verify its Linux
native modules, checksum, source SHA, entry-page client manifests, Sandbox billing
and analytics build values. After deployment, verify the served build and public
and protected entry routes, and keep API/worker releases and session settings
unchanged. Record deployment evidence separately from these source checks.
