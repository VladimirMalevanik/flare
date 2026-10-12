# OPS-005 — bounded production ZIP import

## Objective and scope

Activate the accepted DATA-002 one-time Notion/Obsidian ZIP flow on flare4u.tech.
The owner assigned the temporary storage decision and existing-resource rollout
on 2026-10-09. Analyze remains a separate explicit action. No new paid resources,
AI calls, billing changes, auth changes, or unrelated API-005 generation work.

## Verified starting state

`preflight.json` records read-only Azure evidence. API and worker were deployed
at 9663c9bc856898de62668465341a899c557b64c6, web at a6046adc24ab6dd3d22ae7a9c4d752c49cd07a13.
The deployed worker bootstrap started health and analysis only. Authenticated
Sources displayed disabled Notion/Obsidian buttons and “ZIP import is unavailable
in this environment.” Both /ready endpoints passed, illustrating that those
endpoints did not prove an import consumer existed.

On 2026-10-09 the subscription had no Storage Accounts. Existing PostgreSQL 17
flare-dev-pg-vm-260914 is B1ms, 32GB Premium_LRS/P4, 120IOPS, autogrow disabled.
Its existing PITR backup retention is 7 days; geo-redundancy is disabled.
API and worker run separately on the existing shared B1 App Service plan.
Their /home volumes must not be assumed to be shared.

## Storage decision

Use bounded chunked temporary PostgreSQL storage via the existing psycopg driver.
This is a limited activation tier, not a recommendation for unbounded production
archive storage. No Storage Account, SDK dependency, network rule or new secrets
are added. The API and worker retain their existing restricted logins.

Payload rows are private, forced-RLS and accessible only through role-specific
SECURITY DEFINER functions with fixed search paths. API writes bind authenticated
workspace/member and the current upload token. Worker reads bind its active job
lease/generation; cleanup binds its current cleanup token. The existing permanent
import_objects row fences retired keys, including writers paused across cleanup.
No open database transaction spans client streaming or decoder execution.

Payload blocks are at most 256KiB. SQL independently limits objects to 8MiB,
live declared reservations to 64MiB globally, and newly admitted archive bytes to
128MiB per rolling hour and 128 upload admissions per hour. A workspace can
create at most 120 package sessions per hour. Content-free receipts and retirement
fences are retained; the time window expiry does not delete those rows. These are ceilings, not a paid storage reservation.
Workspace admission, archive inspection and package publication bounds remain
independent. Payload deletion does not remove content-free receipts/tombstones.
Churn caps bound archive WAL production; operator monitoring must still track
DB storage/WAL/autovacuum and capacity before expanding traffic.

Deletion means removal of the live temporary payload rows and bounded local
scratch files. PostgreSQL WAL/PITR backups can retain prior archive contents for
up to the existing 7-day backup window. This is not immediate irreversible erasure
from all backups. Do not shorten production backup retention for this feature.

## Runtime policy and rollout

Next external rewrites explicitly allow 150 seconds, covering the API’s 120-second
streaming deadline and bounded 3-second pool/2-second lock/5-second SQL operations;
this stays below Azure’s 240-second request ceiling.

See backend/.env.import-production.example for every explicit admission, ZIP,
parser, process, retry and cleanup limit. The API can be disabled independently
with FLARE_IMPORT_ENABLED=false. Its production defaults stay disabled.
Processing and cleanup are separate supervised worker processes; a failure of
any required child stops the worker service rather than hiding a dead consumer.
Capabilities require both recent database-backed import-consumer heartbeats.
Heartbeat freshness proves liveness, not that an arbitrary package succeeded.

Planned rollout: verify tests and exact artifact; migrate additively 0021→0022
using the migration identity; deploy backend with import disabled; verify runtime
and schema; set identical explicit policy on API and worker; enable worker first,
then API; verify full authenticated flow and cleanup. Retain exact old packages
and configuration for rollback. Because readiness is schema-specific, a rollback
must use reviewed 0022-compatible code, not deploy an old 0021 readiness module
onto 0022 or delete accepted import lineage. Disable admission first if an incident
occurs, while keeping bounded cleanup running.

## Acceptance evidence

Integrated checks on 2026-10-09: PostgreSQL 17 self-managed full suite 1127 passed;
managed-role full suite 1125 passed, 2 profile-specific skips. Both checked the
0021→0022 preservation snapshot, existing-user email-verification backfill and
UTC daily allowance preservation. The separate restricted-administrator checker
passed 28 ownership/rejection/rollback cases and repeat upgrade to 0022.
Frontend: 256 tests passed; lint and production build passed. Cancellation tests
cover opening, deadline expiry, repeated client cancellation and bounded lock waits.
Actual production-built Next→API→PG upload checks passed for an exact 8MiB ZIP
both immediately and paced over 34.239 seconds; the reconstructed 32 blocks matched
the request SHA-256. An actual 8MiB+1 PUT failed with HTTP413 `compressed_bytes`,
cleared its upload token and was retired by the cleanup consumer. This loopback
fixture used explicit test identity and did not finalize or run Analyze; it is not
Azure or browser drag/drop acceptance. Linux CI exposed a SCRAM-specific missing
password in the disposable administrator fixture; the test now creates a random
test-only password and overrides the bootstrap DSN password for that new role.
Production schema 0022 and release 1e3cdeb were deployed to the existing API,
worker and web services. Both import consumers were observed running with fresh
database-backed heartbeats. Authenticated Sources enabled its ZIP controls.
The first real synthetic ZIP attempt failed before manifest inspection with
`decoder_resource_limit`; no sources were published. A bounded read-only probe
of the exact worker runtime confirmed that the stripped decoder environment
could not import psycopg, while adding the installed portable dependency path
allowed the actual decoder module to load. The decoder now forwards only the
application root and the dependency root of the already loaded psycopg package;
it does not inherit database credentials or other server environment variables.
A real child-process regression uses a separate interpreter without installed
dependencies and verifies ZIP manifest and Unicode text decoding. The correction
at d109c094d6dbb8a77dd200020d16f3f07d626665 passed 132 runtime/ZIP tests and all
GitHub backend/frontend checks. Official Linux release run 38124614760 passed;
the verified backend package SHA-256 is
2e6de2a04e22bccfbfb5705fa90add0b37b7ca0962b57755460ff0af1e564278.

On 2026-10-11 the corrected worker-only deployment completed at 15:56:37 UTC.
Independent Kudu status4/complete/active, exact release marker and public readiness
confirmed it; API and web retained the compatible 1e3cdeb release. Schema and
explicit policy stayed unchanged. A separate read-only runtime proof verified
97 exact source files, the exact portable wrapper, trusted Azure interpreter,
four supervised children and advancing successful import/cleanup heartbeat stamps. Azure CLI's
initial observation timed out; that failed observation and genuine deployment
request timestamp were preserved rather than deploying again.

Live browser acceptance on https://flare4u.tech used a separate verified test
account and the deterministic 3192-byte fixture, SHA-256
9c38a48208acb51114ba6c5cce2e228a125f5f038b3d419c35b428285d462152.
It contains 12 supported .md/.markdown/.txt/.csv files and one unsupported PNG.
Actual external drag/drop progressed through upload, inspection and file reading
(including 5/13 at 38%) to 13/13 at 100%, reporting
“12 files added to Vault · 1 not added”. The expanded PNG report said
“Unsupported file format”; all 12 supported entries were Imported. Every added
file was opened in Vault and matched its original synthetic text, Unicode and
CSV content. The account's two pre-existing items remained: 14 total after import.
Repeating the exact ZIP under the same Obsidian connector returned duplicate,
zero newly published files and the canonical completed package. After refreshing,
Vault still held 14 items and exactly 12 unique synthetic files. Analyze was not
clicked; imported files opened as ready, without extracted facts.

The worker's container stdout capture was initially disabled. Filesystem logging
was enabled on that existing service, retaining its previous 35MB/7-day bounds;
no new resource, network rule or permission was added. Earlier receipt scans were
preserved as failed observations. A further exact replay was completed after the
logging restart, so its current archive reference can be correlated with captured
cleanup output. That exact replay was created at 17:00:25.390095 UTC. A bounded
read-only Kudu scan observed one strict committed cleanup receipt matching both
its current package and object references at 17:00:28.141393 UTC, approximately
2.75 seconds later. The current d109 release marker was verified before and after
the scan; six log tails, 128887 bytes total, were read without outputting raw logs
or credentials. This witnesses committed live PostgreSQL payload retirement and
token-fenced cleanup completion under the verified cleanup code. It is not a
direct private-table row count, a fresh runtime-process proof, or backup erasure.
The earlier independent runtime/source proof retains its actual earlier timestamp.
Anonymous local scratch handles close when the decoder/import contexts finish;
that lifecycle is covered by runtime tests, not a claimed live filesystem count.

Sanitized browser evidence: [acceptance metadata](evidence/live-acceptance.json),
[successful import](evidence/live-import-success.png),
and [unsupported-format reason](evidence/live-skip-report.png).
Content-free cleanup correlation is recorded in
[cleanup evidence](evidence/live-cleanup.json).
