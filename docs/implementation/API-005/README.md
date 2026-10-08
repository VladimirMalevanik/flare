# API-005 — explicit decision reminders

Owner report, 2026-10-08: generating from four saved records twice showed no
Flares. This report is not yet attributed to a particular completed database run.

## Reproduced defect and change

The `flare-v7` prompt explicitly permits a durable Reminder for
`decided/chose/selected/решили/выбрали`. The validator checked a narrower
commitment expression first, silently dropping the latter three cues before
reaching its decision check. One shared decision expression now governs both
checks. Exact source/quote validation and relevance requirements for other
commitments remain intact. This does not require every collection of notes to
produce a Flare; weak facts and intentions may still correctly return zero.

Generation identity remains compatible with the deployed worker. This corrects
the decision behavior already promised by `flare-v7`; prompt, schema, model and
limits remain unchanged. Public manual and scheduled daily runs allocate fresh
request keys and parent analysis jobs, so a future eligible run invokes generation
without reusing the earlier parent's completed-empty result. Keeping the existing
identity also preserves compatibility for work queued before deployment.
Existing completed daily runs remain immutable; there is no quota reset, data
rewrite, extra provider call, or automatic rerun.

## Evidence

- Audited product baseline: `93b3f858f902157fb198a483816538db79658f67`.
- New decision cases against the original validator: six expected failures
  (`chose`, `selected`, `выбрали`, each with commitment or constraint support).
- Queue-compatible detector/context-selection suite: **127 passed**, local
  Python 3.12, mock transports, no provider calls. The two pinned legacy identity
  cases cover default and changed limits; unrelated revision guards still reject.
- Exact-source and quote mutations still fail; other commitments still require
  current relevance support; valid empty results remain valid.
- Independent read-only review of the cue fix found no actionable defect.
- Earlier tested tree `6ff35ba`: full self-managed PostgreSQL 17 backend suite
  **1027 passed** and focused pipeline **186 passed**, including persistence,
  RLS, retry/atomicity and daily
  scheduling. Schema `0021`, migration preservation probes and pip check passed.
  Only the task's disposable database was used and subsequently stopped.
- Queue-compatible tree `88f4ad8`: focused PostgreSQL pipeline **187 passed**.
  Full backend and exact-head CI are rechecked before release.
- `git diff --check` passed.

## Production correlation and rollout boundary

Read-only browser inspection showed an authenticated owner workspace with four
saved records (three notes and one file), zero available Flares, and today's
Analyze action available. No Analyze action was submitted, note changed, or
account switched. This may be a different collection from the reported incident;
account and result details were requested from the owner.

Azure worker state was Running and its release marker was
`453ebec4b6592d1e089a3f5d04da0f35a78a4f09`. Limited GET-only log inspection
returned no stage counters. Running state does not prove generation is healthy.
The owner confirmed the affected account and read-only diagnostics. Automatic
approval review still rejected an interactive API SSH shell because its capabilities
are not confined to reading. Direct PostgreSQL connectivity timed out; no firewall
rule was changed. Incident-specific database attribution remains unavailable.
The owner separately requested deployment on 2026-10-08. No SSH workaround,
database writes, secret disclosure, quota reset or incident-specific success is claimed.

Rollout uses matching tested API and worker artifacts with the unchanged generation
identity. Jobs already queued remain compatible; earlier completed daily results
remain immutable. This avoids depending on an unobservable global queue drain.

## Remaining separately reproduced limitation

Context selection bounds the extraction request, while generation carries the
same evidence plus analysis under its own 32,000-byte ceiling. Four 6,500-byte
synthetic notes and one short valid observation can fit extraction but exceed
generation. That case fails with `invalid_request`; it is not a completed-empty
result. This patch does not increase request limits or truncate pinned evidence.
A complete fix needs an enforced analysis-output byte allowance and selection
that reserves the full generation envelope before pinning; checking an empty
analysis alone is insufficient. Preserve all pinned counterevidence and exact
quotes. Incident correlation must distinguish this failure from valid empty
output and from the corrected decision filter.
