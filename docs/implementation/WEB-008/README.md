# WEB-008 — ZIP cancellation and timeout recovery

Owner request: fix the failed Notion import with a still-moving progress bar,
missing recovery actions and unbounded waiting. The same component serves Obsidian.

## Behavior

- Failed, cancelled and expired packages stop animated progress. Unknown file
  counts remain unknown; no invented 100% or imported result. Server deadline
  failures explain that processing stopped and suggest a smaller ZIP.
- Terminal results have Close import; unsuccessful results also offer Choose
  another ZIP. Closing clears only local UI state, not server history or Vault data.
- ZIP control/status/report requests stop waiting after 15 seconds; upload after
  120 seconds. Deadlines include response parsing, abort the transport and reject
  even when a transport ignores abort. Caller cancellation and unmount abort the
  current ZIP operation. Other API requests are unchanged.
- A progress request failure pauses automatic polling and animation. Check status
  reconnects to the authoritative package; cancellation remains available.
- Cancelling replaces an upload/action request, prevents rapid duplicate cancels
  and displays a pending state. A lost response triggers a bounded status read.
  If neither request confirms a terminal result, show cancellation unconfirmed
  with retry/reconnect controls, never a fabricated cancelled result.
- Before a create response arrives, recover the original idempotency key solely
  to cancel its package: never upload or finalize from this recovery path. A late
  original response cannot resume upload. Retrying an uncertain create reuses its
  key and displays an existing active/terminal receipt without finalizing again.
- Closing a loading report aborts it; old responses cannot replace a reopened
  report. Existing paged All/Failed results and canonical duplicate receipts remain.
- New recovery copy is translated into English and Spanish. Reference lock:
  existing Sources ZIP card, zip-text-action buttons and import dialogs; preserve
  palette, layout, typography and focus styles. Refero craft details inform the
  async status announcements and semantic keyboard-accessible buttons.

## Validation and release

Regression tests cover both source kinds, all unsuccessful terminal states,
unknown counts, deadlines, ignored abort, late responses, duplicate cancellation,
pre-ID cancellation, reconnect and report closure. Full frontend tests, lint,
production build and a synthetic browser check must pass on the published PR.
Actual final results are recorded in the PR/task handoff.

The change is frontend-only. Existing server worker deadlines, leases, staging
cleanup, atomic publication, authentication and Analyze allowances are preserved.
A browser timeout is not proof the server job stopped; server-owned deadlines and
confirmed cancellation remain authoritative. This task pushes a reviewable source
branch; production deployment still belongs to the release owner. No dependencies,
secrets, migrations or cloud settings change.
