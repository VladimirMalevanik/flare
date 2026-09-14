# Analyze Quota Decision Note

No Analyze quota is implemented. Count, subject, reset period, charging boundary,
and paid/free behavior remain product decisions. This note identifies the safest
implementation boundary after those decisions are approved.

## Current request boundary

`POST /analyze` requires a verified owner/editor and a UUID `Idempotency-Key`.
`AnalysisRuns.start` opens the workspace transaction, serializes the logical key with
an advisory transaction lock, returns an existing run on replay, selects eligible
context, and calls the database `start_analysis_run` function. That function repeats
authorization and idempotency checks before it creates the durable job and run.

Note capture, text import and source editing do not enqueue jobs. Only the
explicit/scheduled insight boundary can consume the allowance.

## Recommended atomic enforcement point

Enforce an approved quota in the database transaction that creates a new logical
run, inside `start_analysis_run` or a database function it calls. Check for an
existing `(workspace_id, requested_by_user_id, idempotency_key)` first. A replay must
return its existing run without consuming another unit. For a new key, lock or
atomically update the relevant quota subject and period before inserting the job and
run; all three operations commit or roll back together.

An API-side `COUNT(*)` followed by enqueue is unsafe because concurrent requests can
both pass the count. Worker-start or provider-completion charging is also a different
product contract: it permits accepted jobs beyond the limit and requires reservations
or later settlement.

## Schema options after the contract is approved

| Option | Shape | Tradeoff |
| --- | --- | --- |
| Usage ledger | Immutable row per charged logical action with a unique reference to the run/request | Best audit trail; period counts need an index and may become expensive without rollups |
| Period counter | One row per subject and period, updated with a row lock or atomic conditional update | Fast enforcement; requires a precise period/time-zone contract and a separate audit story |
| Reservation and settlement | Reserved, consumed, and released units tied to a run | Supports charge-on-completion/refunds; adds failure recovery and reconciliation complexity |

Possible subject keys are workspace, user, or workspace-user. Possible boundaries are
accepted run, claimed job, provider request, completed analysis, or published Flare.
None is selected here.

## Idempotency and concurrency requirements

- The existing request key is the logical-action identity. Unknown POST outcomes and
  client retries with the same key must observe the original charge and run.
- Two new keys for the same quota subject may arrive concurrently. Enforcement must
  serialize on a stable subject/period row or use one conditional `UPDATE ... WHERE`
  that cannot exceed the limit.
- Authorization, source selection, quota consumption, analysis job insertion, and run
  insertion must have an explicit ordering. The recommended order avoids charging an
  idempotent replay or a request that cannot create a valid run.
- Retry attempts inside one durable job must not consume additional units unless the
  product owner explicitly chooses provider-call billing.
- Capture/import/edit must remain outside quota accounting because they create no job.

## Frontend and API contract to approve

When the limit is known, reject a new logical run with HTTP 429 and a stable structured
code such as `analysis_quota_exceeded`. The response may include a user-safe `resetAt`
timestamp and allowance metadata only if the product contract defines them. Use
`Retry-After` only for a time-based reset that the server can state accurately.

The frontend should preserve the current Note and prior run state, stop polling the
rejected request, and show specific recovery copy based on the approved reset or plan
behavior. `FlareApiError` currently keeps HTTP status but not the structured error
code, so the eventual implementation must carry that code through the provider and
add explicit controller/UI tests.

## Decisions required before implementation

1. Whether a unit is consumed by an accepted scheduled/explicit Analyze, provider
   attempt, completed analysis, or published Flare.
2. Is the subject a workspace, a user, or both?
3. What is the allowance and reset period, and which clock/time zone defines it?
4. Do configuration/provider failures consume, reserve, refund, or never charge?
5. How do free and paid plans differ, and what upgrade or support action is shown?
6. What usage/audit data may owners and operators see, and how long is it retained?
