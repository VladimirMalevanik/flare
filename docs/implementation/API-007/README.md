# API-007 — implementation closeout

The owner requested completion of everything within our control on 13 October 2026
(Moscow). Sources PR57 is merged at1382c1e8faad8fdee4b434704fa8b2178d0af686.
This integration brings Team, current Settings and mail together and recovers
missing fixes from the stale API-003 review. External accounts and production
activation remain separate, explicitly recorded release-owner actions.

## Delivered

- Sources and Team follow one Alembic chain 0022→0023→0024. Both readiness capability
  families and private source-retirement hooks are retained; no parallel heads.
- Existing Settings polish and manual developer-mail implementation are preserved.
- Voice nonwriters are rejected before upload parsing/provider work. Persistence
  runs in the existing thread pool; revoked memberships return 403. Real-cookie,
  restricted-DB and deterministic event-loop regressions cover the behavior.
- Vault ZIP export uses one read-only repeatable-read transaction before any
  tenant-context/membership read. Concurrent edits/deletes/inserts cannot split
  Markdown, JSON and paginated items across different database snapshots. Ordinary
  bounded transactions keep their prior defaults/deadlines.
- Legacy dashboard capture guards duplicate click/keyboard submissions, preserves
  newer drafts, treats telemetry as optional and reports post-save reload failures
  truthfully. Recent Flares handles errors/retry. Its links preserve Team selection.
  The existing /dashboard redirect remains; this is not a new dashboard rollout.
- The old manual Analyze recovery code is superseded by scheduled-only Insights.
  Daily status/schedule reads already use bounded importRequest deadlines and
  cancellation; existing nine scheduled-analysis checks prove no manual start.
  Manual POST /analyze remains 410 and no quota is reset.

API-005 generation files and its owner's checkout were not modified. No new
runtime dependency, real invitation, provider call, payment or cloud deployment.

## Validation

Backend source 01d226e570079c3c63ad34c8c95baa723f2c6f65; final frontend ef5c652 preserves Team selection from Sources/import-guide links in Settings and updates synchronized-source analysis copy. A behavior regression checks the actual project helper and all four product links.

| Check | Result |
| --- | --- |
| Full PostgreSQL 17 self-managed | 1305 passed, 1 managed-only skip |
| Full PostgreSQL 17 managed owner | 1304 passed, 2 self-managed-only skips |
| Frontend existing/recovered checks | 319 passed |
| ESLint |Passed |
| Linux standalone release artifact 38419727162 |Passed |

The first whole run exposed an obsolete test pool signature that lacked the
current timeout argument. Only that synthetic pool adapter was updated; nine
voice unit regressions and real-cookie tests keep their original assertions.
The full matrices above then passed. SQL behavior was verified against
[PostgreSQL 17 SET TRANSACTION](https://www.postgresql.org/docs/17/sql-set-transaction.html).
CI installs the existing locked dependencies and exercises fresh/preserved-data
upgrades, both restricted-role profiles, frontend type/build and voice runtime.
Final exact-head CI and merge evidence are recorded in the PR/task handoff.

Source and Team remain disabled by default. Local synthetic preview is not proof
of live provider authorization, delivery or billing. Activation checklist:
[release-handoff.md](release-handoff.md). Service/account inventory and common
Gmail setup: [service-register.md](service-register.md).

## Combined local review

Synthetic preview: http://localhost:8427/team?project=582a85ee-a4a4-41af-a856-7c6678625889.
The account is a disposable Fedor owner with Ilyas editor and Vova viewer. Team,
Sources, current Settings and shared Vault run against one restricted local DB.
Provider connections remain unconfigured; the local mail recorder sends no emails.
No daily/source worker is started and no real payment/AI request is made.

Browser checks confirmed Team tasks, creator/assignee, role and project-aware
navigation, current Team billing status, honest unconfigured source states and
shared-project ZIP export. The downloaded ZIP contains workspace metadata, raw
JSON and the expected synthetic interview note. Source/import guide navigation
from Settings is additionally covered by the final behavior regression.
Screenshot: local project outputs/closeout-qa/team.jpg.

The backend/frontend code trees at the merged review head are the release source.
Documentation-only follow-ups do not authorize using an older archive when the
frontend code has changed. Operator activation stays in OPS-006.
