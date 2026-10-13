# API-006 validation and local review

Product code reviewed at `b467c28ad8b75e17e6d109e1f9ee2d2db882d30f`.
Backend is identical to `22bf7c4ae1ea33fcb01c4a27cdb124c8de6ea67b`;
the later commit updates bilingual Team benefits and explains the license billing owner.
Task remains subject to Fedor's product acceptance and Vova's activation gates.

## Automated checks

At 22bf7c4, [complete CI](https://github.com/VladimirMalevanik/flare/actions/runs/38316140896)
passed both PostgreSQL17 profiles, preserved-data email verification/daily-quota
upgrades, repeat migration, dependency consistency, frontend tests/lint/build and
voice runtime checks:

| Profile | Result |
| --- | --- |
| Backend self-managed | 1,233 passed, 3 skipped |
| Backend managed non-superuser owner | 1,232 passed, 4 skipped |
| Frontend | 303 passed |
| Scheduled analysis frontend | 9 passed |

Conditional skip cases are managed-only capability isolation (self-managed),
self-managed role check (managed), and the two DATA-003 integration cases when
migration 0023 is absent. They do not hide Team behavioral failures. Remaining
warnings are the existing Starlette/httpx compatibility notice and an intentional
duplicate-name ZIP fixture.

At b467c28, [final code CI](https://github.com/VladimirMalevanik/flare/actions/runs/38317149547) and [PR CI](https://github.com/VladimirMalevanik/flare/actions/runs/38317235063) both passed the same full matrices above. Local frontend 303 checks and ESLint also passed. The separate
[standalone release build](https://github.com/VladimirMalevanik/flare/actions/runs/38317177252)
also passed; its ZIP checksum was verified before local extraction. The canonical
CI build installs existing locked dependencies; no production dependency was added.

Coverage includes actual restricted app/worker roles; email verification and
wrong-account/expired/canceled invitations; sharing acknowledgment; member/owner
permissions; last-owner protection; concurrency-safe seats/project creation;
server-authored creators; conflicting task versions and preserved drafts; keyset
pagination; UTF-8 quota rollback; request-body/response timeouts; expired-license
read/export and worker admission; billing server-price binding; per-tab project
scope; provider state binding; membership revocation and source retirement.
No real mail, provider account, billing payment or AI request was used.

## DATA-003 integration

A separate disposable checkout combines Team backend 22bf7c4 with
DATA-003 `16703c6aea827043f7512e740f67fe2a780f51e7`
([PR 57](https://github.com/VladimirMalevanik/flare/pull/57)). It preserves both
capability checks and changes only the Team migration parent to 0023 for the
combined0022 → 0023 → 0024 line. The author's source checkout was not modified.

| Combined profile | Focused Team/source checks | Whole backend |
| --- | --- | --- |
| Self-managed | 55 passed, 1 managed-only skip | 1,287 passed, 1 skipped |
| Managed non-superuser owner | 56 passed | 1,286 passed, 2 skipped |

Both source retirement tests run in this combined tree: member removal clears
credentials/auth states and cancels leases; license expiry prevents provider
admission and clears retired credentials while preserving saved snapshots.
These are local integration results, not proof of a production deployment.

Reproduction uses existing isolated Python runtime and disposable PostgreSQL17
clusters. Set distinct runtime, worker and test-admin URLs; migrate the selected
profile; from backend run `PYTHONPATH=. python -m pytest -q tests`. Never run
these fixtures against a real workspace: tests change the capability policy.
Integration checkout : `/private/tmp/flare-team-data003-integration`.
Logs : `/private/tmp/flare-team-combined-self-full.log` and
`/private/tmp/flare-team-combined-managed-full.log`.
The combined frontend passed 310 tests and ESLint. Its source decoder test
harness initially lacked the newly imported project-context dependency. The
isolated integration adds the actual transpiled Team helper to that harness;
the production decoder assertions are unchanged. Apply the included
`integration-test-harness.patch` when merging both branches. Individual Team and
DATA-003 builds pass CI; a combined production artifact was not built locally
because the pre-existing local dependency tree lacks the Azure analytics SDK.
No test outcome was inferred from that limitation.
File hashes for the reviewed integration are in `integration-manifest.json`.

**Merge gate:** the product branch currently follows 0022 because DATA-003 is
unmerged. If PR 57 is accepted first, resolve the migration parent/readiness merge
using this combined line and rerun the checks. Do not leave parallel migration
heads. No product branch was merged into main by API-006.

## Browser checks and morning preview

[Open local Team](http://localhost:8427/team?project=a36b651f-5e8f-412a-ac53-07259ba0e319).
The retained browser tab is signed in as the synthetic Fedor owner. This is a
separate empty test database, not a production account. API listens on 127.0.0.1:8428;
web listens on 127.0.0.1:8427. Existing 8425 source preview was not replaced.
The release artifact's API rewrite was changed only in the extracted local copy
to 8428; repository/production API configuration remains unchanged.

Verified in the real browser:

- Create a task; creator Fedor/time are filled automatically; history shows the creation.
- Viewer can open tasks/history but cannot edit fields, save or add tasks.
- A synthetic email invite creates a pending seat; cancellation changes its status.
- Personal project has no shared note; selecting Team shows the shared note and correct role.
- 390×844 mobile view has no horizontal overflow (viewport and document width both 390).
- Dialog opens at the title field; Escape closes it and returns focus to its launcher.
- Settings correctly identifies the Team license and its billing owner.

Synthetic accounts only : `fedor-team-preview@demo.invalid` (owner),
`ilyas-team-preview@demo.invalid` (editor), `vova-team-preview@demo.invalid` (viewer).
Password for these disposable accounts : `Team-preview-2026`. Do not reuse it.
The local mail adapter writes to `/private/tmp/flare-team-preview-mails.json`;
it never sends SMTP. Invitations to real people cannot be delivered in this preview.
Daily workers and actual provider OAuth are not started in this demo.

Try adding/editing a task, changing assignee/status, opening history, switching
between personal/Team Vault, and viewing Members. Genuine provider/mail/payment
acceptance belongs to the separate activation checklist in README.md.

Screenshot evidence under the local project output directory:
`outputs/team-qa/desktop-tasks.jpg`, `mobile-tasks.jpg`, `viewer-task.jpg`.
Local web artifact SHA-256 : `836dc2f2885d96f802849622417f22f055e9b2ab13e970135eaeb01f87432706`.

## Activation limits

Team defaults off in server and DB policy. Vova must configure a distinct Sandbox
Team price, matching administrator policy, genuine SMTP/HTTPS origin, exact
migration lineage and operational capacity, then complete the consenting-account
acceptance checklist. No price, service subscription, trial offer or Live mode was
created. Pro→Team self-service upgrade is not yet available; a second subscription
is blocked. No actual personal materials were copied into Team.
