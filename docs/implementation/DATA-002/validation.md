# DATA-002 validation and measured evidence

Completed 2026-10-02 after integrating coordination main `9b9a44ae6885605a3f64c1ea80e35f1b2320c4c9`. All archives and users were synthetic. Nothing contacted an AI provider, Azure storage or a production database.

## Final affected checks

| Check | Result |
| --- | --- |
| Existing `python -m pip install -e 'backend[dev]'` | Passed in an isolated Python 3.12 environment; no dependency/lockfile changes |
| `python -m pip check` | Passed; no broken requirements |
| `pytest -q backend/tests`, self-managed topology | **734 passed**, 2 warnings, 41.99 seconds |
| `pytest -q backend/tests`, Yandex-compatible topology | **733 passed, 1 skipped**, 2 warnings, 41.36 seconds |
| Focused ZIP/parser/API/worker/gate tests | **78 passed** in the final focused run before the full suite |
| `npm --prefix frontend ci` | Passed using the existing lockfile |
| `npm --prefix frontend test` | **91 passed** |
| `npm --prefix frontend run lint` | Passed |
| `npm --prefix frontend run build` | Passed, including TypeScript and 20 generated pages |
| `git diff --check` | Passed |
| Migration head enumeration | One linear head: **0019** |

The Yandex skip is the existing self-managed-only 0018 executor CREATE-privilege regression, not a skipped import/security test. Warnings are the current TestClient transport deprecation and the intentional duplicate-name ZIP fixture. No dependency upgrade was made to silence them. `npm ci` reported advisories in existing dependencies; resolving them is a separate dependency task, not an unrequested production dependency change.

Runtime evidence: Python 3.12.11; PostgreSQL 17.11 (Homebrew); pgvector 0.8.6; Next.js 16.3.4; React 19.2.8; TypeScript 5.9.3; macOS 26.6.2 arm64. Tests were run in two **isolated disposable local PostgreSQL17 clusters** emulating the supported CI roles/topologies. This was not a Yandex cloud deployment or an Ubuntu/container isolation benchmark.

## Migration validation

Both clusters started with fresh databases and ran the CI sequence: upgrade to 0005, upgrade to 0007, prepare legacy email-verification fixtures, upgrade to 0014, prepare legacy daily-quota fixtures, upgrade to head, verify both legacy migrations, then upgrade to head **again**. Self-managed worker-role provisioning ran afterward; Yandex-compatible owner/app/worker provisioning was emulated using the existing CI setup before migration.

Both sequences passed. The Yandex migrations ran as the non-superuser, non-bypass `flare_owner`; the API and ZIP tests used `flare_app`, and the worker used `flare_worker`. Readiness passed at 0019. The import step's self-managed owner is the non-login definer executor; its CREATE privilege is **false** after upgrade. Existing schemas and old migrations were not rewritten. The new 0019 SQL snapshot is covered by these fresh-upgrade checks and is immutable after release.

## Security, fidelity and recovery coverage

The synthetic fixtures cover Notion/Obsidian-style ZIPs, nested folders, Markdown/frontmatter, BOM, Unicode paths/content, CSV multiline/quoting, duplicate titles in different paths and inert HTML/script text. Unsafe absolute/drive/UNC/backslash/dot/empty paths, reserved portable names, controls, Unicode/case collisions, file-prefix collisions, symlinks/special files, encryption, malformed/truncated structures, dishonest directory counts and file sizes, local-header/data-descriptor/CRC corruption and unsupported compression are rejected. CRC/resource verification includes unsupported skipped assets.

Independent bounds are exercised for compressed/expanded bytes, files, entry count, actual directory/manifest allocation, path length/depth/segments, CSV rows/fields/records, file/package chunk limits and source/staging reservations. The suite also covers no-supported-content failure, explicit unsupported skips, immutable local objects and zero-content cleanup tombstones that prevent delayed creation after deletion.

Integration tests cover exact-package replay after source deletion, concurrent finalize, one logical publication, crash/restart checkpoints, stale lease/generation, exhausted attempts/deadlines, global concurrency despite an oversized caller request, cancellation/gate races, retry scheduling/eligible retry-now, cleanup storage failure, stale cleanup tokens, expired unused sessions, quota admission races, revoked authorization, viewers and workspace isolation. The dedicated worker refuses an API-role connection and cannot select package tables directly.

Package gate checks use actual item list/detail, search, portable export, manual Analyze selection, scheduled candidate selection and direct source/version/chunk reads. Pre-gate sources are absent; after the transaction commits they are visible and eligible. Existing immutable historical evidence/citation and single-file import tests also pass. Import leaves analysis jobs/runs and daily quota absent; one scheduled-reader fixture intentionally seeds an existing schedule cycle and verifies that the quota created by that fixture's own trigger remains unchanged by import. Provider methods are guarded against invocation in the ZIP integration fixture.

Frontend tests exercise the actual component's upload/finalize/status/count/report paging, reload/resume, cancellation, eligible retry, uncertain-create idempotency, disabled deployment capability, double click/unmount behavior and strict provider DTO/raw ZIP transport. Existing Sources/GitHub/i18n/capture/Vault regressions remain in the suite. The frontend displays original relative paths as user content and never translates them.

## Measured decoder fixtures

These are individual synthetic runs on one local machine, not production capacity claims, percentile distributions or final quota recommendations. The decoder harness includes per-file child startup and private scratch I/O. Its bounded source generator uses deterministic text; the associated security cases are refused before extraction.

| Entries | Expanded bytes | Compressed bytes | Chunks | Inspect seconds | Parse seconds | Child peak RSS bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 20,000 | 12,422 | 10 | 0.1263 | 1.2369 | 39,452,672 |
| 100 | 200,000 | 124,202 | 100 | 0.1157 | 12.4472 | 39,469,056 |
| 100 | 5,000,000 | 2,939,602 | 1,300 | 0.1018 | 12.7729 | 39,485,440 |

Machine-readable files: [decoder-10.json](evidence/decoder-10.json), [decoder-100.json](evidence/decoder-100.json), [decoder-100-large.json](evidence/decoder-100-large.json). These runs exclude network upload, PostgreSQL publication, concurrent tenants and production storage. The final large fixture included the full-stream/data-descriptor verifier; the smaller runs preceded that final verifier addition. The final full security suite verified the complete implementation afterward.

Reproduce with `PYTHONPATH=backend python backend/scripts/check_zip_imports.py --entries 100 --file-bytes 50000`. Inputs are bounded by the local/test policy; the harness never accepts private archives or calls providers.

## Full application and live API evidence

The final full-suite application fixture uploaded/finalized **30 files / 117,000 expanded bytes**, published 30 sources with exact content and performed cleanup. It measured 0.0153 seconds through queue admission, 4.9067 seconds for the worker through the gate, and 0.0311 seconds for result reads plus cleanup. See [application-30.json](evidence/application-30.json). This was one local workspace with local staging/PostgreSQL; concurrent finalization/quota/lease behavior is covered separately by integration tests.

A separate running localhost API and actual dedicated worker CLI processed a synthetic Notion ZIP: before the gate **0 visible sources**, afterward **2 published sources**, **1 skip**, **3 report entries**, and deletion of the temporary ZIP. Metadata included correct original paths/package IDs. See [live-api.json](evidence/live-api.json). API/frontend development servers were stopped after QA; no runtime/deployment file was changed.

**Browser UI QA is unverified.** The native browser tool refused to open localhost because the admin-enforced browser security policy could not be verified. No browser-security bypass or alternate browser automation was attempted. Automated component/provider tests, production compilation and the live API flow passed; no screenshot or visual pass is claimed.

## Remaining verification before production

OPS/Vova must validate the selected storage adapter, actual API/worker topology, physical retirement/deletion and blocked-I/O behavior, Linux/container resource enforcement, cancellation/cleanup under that topology, and sustained concurrent application/database load. They must measure package gate/lock latency and quota-accounting costs, choose final product settings, and define monitoring/retention. These local measured ranges must not be copied into production quotas as if they were approved limits. Owner acceptance and integration of the application/migration branch remain separate from DATA-002 review completion.

## Focused owner-requested correction — 2026-10-02

OWNER ACCEPTANCE PENDING. This cycle fixes the two owner-confirmed defects and
returns the same DATA-002 to review. The original implementation and evidence
above remain historical evidence, not newly rerun measurements.

Original published DATA HEAD: `7a37ad7eede0d624c4995141ef9c5410f116c19d`.
Accepted main product base: `34b5054051c514b66e96bc0baff6a23e8418a9d2`.
Fresh main immediately before publication:
`58a1951845f595566c881946c8811e5d0814f290`; its later changes are coordination only.
Fix branch: `task/data-002-receipt-20261002-fix`.
Compatible integration base before bugfix:
`cec7730654a88b1248cdfd086ece00ec8b38bbba`.
Minimal bugfix commit: `70f8bee3dd18af2388d20d43aa17ea48d58c23c8`.
`git diff cec7730654a88b1248cdfd086ece00ec8b38bbba..70f8bee3dd18af2388d20d43aa17ea48d58c23c8`
contains six files, 163 insertions and 13 deletions. Final published HEAD and PR
are recorded in task-sync and the handoff, separately from this document.

### Corrections and compatibility

Create-session compares the persisted winning request's `source_kind`,
`file_name` and `file_size` before returning it. The existing SQL workspace lock
and unique request key serialize admission; the application checks the immutable
winner even for concurrent reuse. A mismatch returns HTTP 409 with
`detail=request_key_conflict`. Identical retries preserve the original session,
reservations, publication and server-owned policy snapshot. Tests cover all three
changed fields, concurrent identical/conflicting creation, tenant separation,
revoked write access, changed server policy and completed-session replay/conflict.
No SQL or migration change was needed.

The adapter/type retain `canonical_id` as `canonicalId`. History, polling and
action results resolve a duplicate to its authoritative package. When that
package is outside the history page, the existing tenant-bound detail API loads
it. Counts, report pagination and Vault link use the resolved ID. Missing or
invalid canonical results do not create an accepted receipt. Tests exercise the
actual adapter/component and API/persistence behavior, including fresh mount,
refresh, navigation back, report pages and one publication after exact replay.

The integration commit resolves the EN/ES dictionary and MVP UI-test conflicts
by retaining both sides. The automatically merged i18n tests were also inspected.
Funny mode, Capture/Voice controls, manual Analyze request semantics, mute,
accessibility and Subscription/Paddle Sandbox remain covered by the full suite
and focused browser smoke. No WEB ownership/state was changed.

### Actual checks in this cycle

| Check | Actual result |
| --- | --- |
| Full backend, fresh isolated self-managed CI topology | **740 passed**, no skips, 2 existing warnings, 36.40 seconds |
| Focused backend request identity/canonical receipt regressions | **6 passed**, 19 deselected, no skips |
| Full frontend | **129 passed**, no skips |
| Focused frontend adapter/component regression file | **11 passed**, no skips |
| Frontend lint | Passed |
| Frontend production build | Passed, TypeScript and 20 generated pages |
| Whitespace | `git diff --check` passed |
| Migration chain | Sole head **0019**, parent **0018**, no sibling heads |
| Migration application | Fresh CI legacy-fixture sequence through 0019, legacy verification, repeated upgrade to head passed |
| Published 0019/SQL snapshot comparison | Both files byte-identical to original DATA HEAD; SHA-256 evidence retained |
| RLS, tenant isolation, package gates, worker fencing/recovery | Actual migrated restricted-role tests passed in the full backend suite, no skips |
| AI/Analyze import invariants | Provider-guarded integration tests passed; final browser workspace has 0 analysis jobs, 0 runs and 0 daily quota rows |

Backend warnings remain TestClient/httpx deprecation and the intentional duplicate
ZIP-name fixture. Dependencies and lockfiles were not changed. The Yandex topology
was not rerun in this focused cycle; its original results above remain historical.

An intermediate repeat accidentally shared the browser database with a running
import worker and residual manual-smoke jobs: **735 passed / 5 failed**. The
failures involved global queue/cleanup expectations. That run is not a pass.
The runtime was stopped and a second entirely fresh cluster was migrated before
the final isolated 740-pass run. Browser automation attempts also caught test
timing mistakes around delayed Capture closing; the final isolated retest below
completed all assertions. No product change was made to hide these failures.

Logs: [backend suite](evidence/fix-backend-suite.txt),
[frontend suite](evidence/fix-frontend-suite.txt).
Migration/RLS/no-Analyze facts:
[fix-migration-security.json](evidence/fix-migration-security.json).

### Playwright MCP retest

The configured user-level Playwright MCP ran against localhost with a real API,
restricted dedicated import worker, disposable PostgreSQL17 and synthetic ZIPs.
An isolated browser context avoided interference from navigation in the shared
tab. No cookies, session values or credentials were exported into evidence.

All import/create/history/report traffic used real persistence. All three changed
request identities returned 409; identical retry returned the same session.
The accepted Notion package had 2 imported and 1 skipped file. Exact duplicate
finalize, refresh and navigation back retained the same canonical result, all
three report entries and `/vault`. Publication/source counts stayed **1 / 2**.
The real history-page boundary was exercised with 49 cancelled synthetic sessions:
the returned 50 rows contained the duplicate but excluded its canonical row;
refresh fetched the canonical package through the detail API and retained the
same receipt. No extra publication was created by those sessions.

Desktop 1440×1100 and narrow 390×844 passed in EN/ES, including ES refresh.
Funny mode/mute, Escape cancellation, Capture, accessible file/Voice controls and
Free/Pro/Team Sandbox subscription UI passed. Four intentional keyboard shakes
produced **one** Analyze request, fulfilled with a synthetic pending DTO; its poll
was also intercepted. This is frontend request smoke, not a live AI result.
Import produced **zero** Analyze requests. Voice recording/transcription and
Paddle checkout were not submitted.

The final isolated run had no runtime exceptions or unexpected failed requests.
Console errors were the three expected 409 conflict probes and expected 503s from
the deliberately unconfigured local GitHub integration. No GitHub provider or
production payment operation was attempted.

Standard Turbopack development mode exposed an existing original-DATA issue:
`mock-provider.ts` places an import before `"use client"`. The retest used webpack,
matching the project's production build. This separate issue remains outside
the two-defect correction and must not be described as fixed.

Machine-readable results: [fix-playwright.json](evidence/fix-playwright.json).
Screenshots: [desktop EN](evidence/fix-canonical-desktop.png),
[desktop ES](evidence/fix-canonical-desktop-es.png),
[narrow EN](evidence/fix-canonical-narrow-en.png),
[narrow ES](evidence/fix-canonical-narrow-es.png),
[Subscription Sandbox](evidence/fix-subscription-desktop.png).
Existing production OPS/Vova gates remain. No finish/done, product merge or
deployment is authorized by this correction.

## Standard development compiler correction — 2026-10-03

Owner acceptance remains pending. The user explicitly delegated DATA-002 to the
Flare Paperclip team. The task was returned to correction, claimed as
`Fedor / Paperclip Flare Web / DATA-002`, and its complete inherited import scope
was published before editing. The correction branch
`task/data-002-dev-fix-20261003` includes the existing PR #33 import unit at
`4b49eb6d8cfd14e4bc72a0c533c094784e592c40` on fresh coordination main.

The previously recorded Turbopack failure is fixed in this cycle: `"use client"`
now precedes every import in `frontend/src/lib/data/mock-provider.ts`. The only
new changes relative to the imported unit are that directive order and this
validation addendum. Backend, migration/SQL, import semantics, dependency files
and other tasks were not changed.

| Check rerun for this correction | Actual result |
| --- | --- |
| Complete frontend test suite | **129 passed**, no failures or skips |
| ESLint on the changed provider | Passed |
| Standard `next dev` with Turbopack | `/sources`, `/vault`, and both Notion/Obsidian guide routes returned HTTP 200 with no compilation error |
| Production `next build --webpack` | Passed, including TypeScript and 20 generated pages |

These checks ran in the team's own clean task worktree with an isolated copy of
already installed dependencies, the synthetic mock provider and a disabled API
address. No dependencies were installed or upgraded. The owned development
process was stopped afterward and generated tracked development typing changes
were restored. The HTTP smoke proves compilation and route serving; it does not
claim a new live-API/browser acceptance run. The prior real-persistence browser
and backend results above remain evidence for the unchanged import unit.

The independent Paperclip Critic audit of the inherited `4b49eb6` unit reported
PASS for package gates/RLS, bounded ZIP validation/cleanup, request identity and
canonical replay, linear migration 0019, and absence of automatic Analyze. That
audit was static and did not rerun suites. Exact published SHA, CI results and
final review handoff are recorded separately in task-sync and the pull request.
Production OPS decisions, owner acceptance, authorized integration and finish
remain separate gates.
