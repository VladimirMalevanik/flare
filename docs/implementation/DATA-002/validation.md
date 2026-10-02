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
