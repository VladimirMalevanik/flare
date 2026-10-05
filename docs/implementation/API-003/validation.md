# API-003 — audit regression fixes

The owner assigned these fixes on 2026-10-05 after the read-only audit of
`c811bbd12309bb3055497bd2cadd7d08c52c460b`. Product code was implemented on isolated
branches, with declared scope and no changes to foreign tasks or the shared checkout.
The tested product commit is `c8fb1dbd313a0a8b2753bd65e019d1733fbb4dde`.

## Result

- Voice rejects nonwriters before upload processing or provider work. The existing
  transactional write check remains authoritative if membership changes during
  transcription; those failures return 403. Synchronous item and analytics
  persistence run in a worker thread.
- ZIP export uses one read-only repeatable-read transaction, established before
  tenant-context and membership reads. Workspace metadata, all paginated notes and
  Flares, Markdown and JSON share that snapshot. Normal transactions keep their
  existing isolation; export pagination, spool rollover and cleanup are unchanged.
- The legacy dashboard component guards simultaneous click/keyboard saves, keeps
  newer drafts, treats telemetry as optional, and confirms a successful save before
  independently refreshing its list. Recent Flares handles errors and retries.
  `/dashboard` currently redirects to `/insights`; this component was tested
  behaviorally, not claimed as an active browser route.
- Analyze status reads have a 30-second deadline; the existing analysis lifecycle
  keeps its 300-second deadline. Cancellation settles even noncooperative provider
  promises, releases the UI, retains unknown-POST idempotency keys, and suppresses
  late responses. Daily-status cancellation reaches fetch. Resumed polling keeps
  its today/recent context. New interface copy has English and Spanish translations.

## Validation

Full tests ran from an immutable Git archive of the tested product SHA. The worktree
inherits sparse-checkout exclusions for environment files; the archive includes the
public committed example templates required by existing tests. No real environment
file, credential store or production secret was read or changed.

| Check | Result |
| --- | --- |
| Backend, self-managed PostgreSQL 17 | 1015 passed, no skips |
| Backend, local Yandex emulation | 1014 passed, one expected self-managed-only skip |
| Frontend | 202 passed, no skips |
| Frontend ESLint | Passed |
| Frontend production build and TypeScript | Passed |
| Independent backend/frontend review | Passed at the tested product SHA |
| Diff whitespace and declared scope | Passed |

Eighteen backend and twenty frontend regressions were added. Voice tests include
real cookie authentication and PostgreSQL persistence, plus deterministic event-loop
barriers for item and analytics writes. Export tests commit edits, deletion and
insertion while pagination is in progress. Frontend tests cover duplicate submissions,
refresh failure after a successful save, newer drafts, telemetry failures, rejection
handling, deadlines, cancellation, late responses, idempotency and daily context.

Playwright checked the production build on a separate local preview:

1. Held the initial daily-status request: Analyze was disabled while loading and
   became usable after the 30-second deadline.
2. Returned a pending daily run and held its status request: the UI showed progress,
   then a recoverable status error and an enabled check button after the deadline.
   This flow made one status GET and zero Analyze POSTs.
3. Removed all test interception and returned to the normal Flares page.

The preview uses a synthetic account and an isolated database. No real AI, SMTP,
Paddle or cloud calls were made. Browser cancellation produces expected aborted
network requests. Unit/component tests still use simulated hooks; browser checks
cover the active Analyze route, not every product journey.

## Review boundary

No production dependency, migration, billing, quota, provider-budget or infrastructure
change was made. Product acceptance, merge to main and deployment remain separate.
Local preview: `http://localhost:8413/insights`; previous preview on 8411 is preserved.
