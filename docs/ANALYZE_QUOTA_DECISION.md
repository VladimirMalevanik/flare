# Daily Analyze Quota Decision Record

**Status: implemented at migration head `0015`.** Flare allows one accepted
analysis cycle per workspace local calendar day. Manual Analyze requests and
scheduled analysis use the same slot.

## Product contract

- The quota subject is the workspace, not an individual user.
- The allowance is one logical analysis cycle for each workspace local date.
- The date uses the workspace schedule's IANA timezone. A workspace without a
  saved schedule uses `UTC`.
- Manual and scheduled analysis share the allowance. Whichever path reserves the
  day first prevents a second path from starting that day.
- A 20-hour minimum separation check also applies to the prior promised run time.
  This closes the immediate bypass where changing the workspace timezone would
  otherwise expose a different calendar date moments after an analysis.
- Capture, import, and source editing do not consume the allowance and do not
  enqueue analysis. They only publish source data for a later manual or scheduled
  cycle.

This is a product usage rule rather than provider billing. One slot is reserved
when Flare atomically accepts a manual run or materializes a scheduled cycle. AI
retries inside that cycle do not consume another slot. A failed cycle remains the
workspace's cycle for that day; failures do not silently permit extra provider
work.

## Manual Analyze

`POST /analyze` requires a verified owner/editor and a UUID `Idempotency-Key`.
Before creating work, the service checks for a prior run with the same workspace,
user, and key. Replaying an accepted request returns that run and does not consume
another slot.

For a new logical request, the database serializes the workspace operation,
validates the selected current source chunks, reserves the daily slot, and creates
the cycle, analysis job, public run, pinned source references, and
`analysis_requested` event in one transaction. Concurrent requests cannot both
pass the limit.

If today's slot, or the 20-hour guard, is already occupied, a new request returns
HTTP `409` with the exact stable detail code `daily_limit`. A changed source
selection remains a separate `409 selection_changed` response, so the frontend can
tell the user whether to retry now or wait for the next available day.

## Scheduled Analyze and the T-30 snapshot

Owners and editors can save one workspace schedule with an IANA timezone and local
run time. The lead time is fixed at 30 minutes.

At T-30, the worker materializes the day's scheduled cycle and reserves the shared
daily slot. The refresh stage then selects eligible current source chunks and
stores their exact immutable chunk IDs in `analysis_cycle_sources`. At the selected
run time, the worker enqueues analysis from that pinned snapshot. Edits or imports
made after the snapshot remain available for a later cycle but do not rewrite the
current cycle's evidence. Deleting source evidence still causes the existing
source-validity checks to reject or hide invalid results.

A schedule change may cancel automatic work that has not created an analysis run
and release that unstarted reservation. Already enqueued, completed, or failed
daily work remains consumed. Worker leases, bounded refresh retries, and the queue
maintenance path recover or surface stuck scheduled work without creating an
extra cycle.

## Durable enforcement and retention

`analysis_daily_quotas` is the compact, retention-safe record of a consumed local
day. It is independent of job and run foreign keys, so deleting old queue or result
rows cannot reopen that date. Migration `0015` also backfills one UTC-day tombstone
for each workspace/day represented by legacy `analysis_runs` before the new rule
becomes reachable.

Database constraints, workspace advisory locks, and restricted security-definer
functions enforce the rule for both API and worker paths. Row-level security keeps
schedule, cycle, snapshot, and quota rows inside their workspace. The daily-status
API reports the cycle state, scheduled and refresh times, pinned source count, and
whether another request is available without exposing source content.

## Future product changes

The implemented launch rule is fixed at one workspace cycle per local day. Paid
tiers, additional manual runs, provider-call billing, refunds, and custom allowance
counts are separate future product decisions. Changing them requires a new
database/API contract; they must not be inferred from the current tombstone.
