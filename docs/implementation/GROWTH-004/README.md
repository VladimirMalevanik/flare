# GROWTH-004 — Campaign link activity

Settings → Campaign links now opens an Activity view. The Links view keeps the
existing creation, copying and archiving controls. Access still requires the exact
internal account grant and workspace owner role; this is not customer analytics.

Activity includes 7/30/90 UTC-day ranges, one-link filtering, a daily time series,
recorded opens, days with opens, busiest day, and up to ten ranked links with their
share of period opens. The total/time series include every link, even when only ten
ranked rows are displayed. Archived links keep recorded history but stop counting
future opens. Refresh reloads both the report and the link list/lifetime counters.

## Measurement

Only existing Flare /r/ short-link redirects count. Direct URLs with utm_* parameters
are not counted by this report. Repeat opens, automatic previews and bots can count;
best-effort telemetry can miss opens. These are neither unique people nor signup
conversion rates. Optional account-linked attribution remains a separate restricted
system; its grants, consent, policy and reporting thresholds have not changed.

Migration0026 adds a per-link UTC-day aggregate and a recording-start timestamp.
The stored aggregate has only link ID, date and count: no per-visit events, IP,
cookie, user agent, referrer or visitor/account identity. Metadata stays protected
by the existing owner/workspace model. It remains until the parent workspace is
deleted, matching the notice; no new cookie or external analytics service is added.

Lifetime and daily increments commit atomically through the existing narrow
counter function. The separate resolver and its fail-open telemetry behavior,
public admission cap, statement/lock timeouts and payload-free bounded logs remain.
Runtime/worker/PUBLIC cannot write the daily table; owner reads are forced through
RLS. Readiness requires schema0026 and checks the daily table's RLS/policies/grants.
The read API uses a bounded repeatable-read snapshot, a single aggregate SQL query,
90 daily buckets maximum, ten ranking rows maximum, and a one-second statement
budget. No full visit log is loaded into the browser.

Earlier lifetime totals have no dates and are never reconstructed. Days before
recording began are null/“Not recorded”; known days with no opens are zero. The
first recorded day and today may be partial. Each filter has its own cancellable
request; stale responses cannot replace newer data. Errors expose retry rather
than zero traffic. SVG chart navigation works with arrows/Home/End; the same daily
values are available in a readable table. English/Spanish, dark and mobile states
use the existing Flare tokens and Select component. See design.md for references.

## Validation and rollout

New regressions cover real redirects, UTC buckets, concurrent increments, archive,
legacy coverage, empty/invalid periods, link/workspace isolation, ranking bounds,
rollback on failed daily writes and fail-closed readiness under weakened grants/RLS.
Frontend regressions cover response validation, sums/ranges, filter keys, abort and
stale responses, error/zero/empty states, keyboard navigation and localization.
Actual CI run links/head SHA and rendered-browser evidence are recorded in the PR
and task-sync after validation; no production completion is implied here.

Local tests use only an isolated PostgreSQL17 database, synthetic users/links and
existing read-only dependency installations. The complete normal CI is authoritative:
it installs the unchanged lockfiles and includes both self-managed and Yandex DB
profiles, existing migrations, all backend/frontend tests, lint, production build
and native ffprobe/WAV checks. No new dependency or production secret was added.

Vova must deploy the reviewed source with migration0026 on the existing database.
Take the normal reviewed backup/PITR checkpoint, apply the normal migration sequence
with the existing migration role, and deploy matching API/worker/web artifacts.
Both old and new code pin their expected schema revision: do not deploy old0025 code
against0026 or update only one runtime. Verify readiness, private-owner visibility,
a controlled /r/ redirect increment and its UTC-day report. Daily history begins
at migration/creation time; no historical backfill job or Azure configuration is
needed. A code-only rollback across this schema boundary is insufficient; use the
project's reviewed backup/rollback process. This task does not deploy or activate
optional attribution, mail, Team, payment, AI or any social account integration.
