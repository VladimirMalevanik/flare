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
Production rollout and live smoke are still pending. No production import success
is claimed yet.
The deterministic synthetic fixture contains 12 supported text files (.md,
.markdown, .txt, .csv) and 1 unsupported PNG. Full acceptance requires a dedicated
verified test account, real picker/drop/progress/report, 12 files opened in Vault,
same-ZIP replay with unchanged source/publication counts, no analysis activity,
and verified active payload/scratch cleanup.
