# Paddle Sandbox activation

The owner authorized this rollout on existing Flare Azure resources. Paddle Live,
new paid resources, security weakening and foreign unmerged PR43 are excluded.
Migration, deployment and server configuration are verified. Real Sandbox
subscription delivery and entitlement acceptance remain pending final Sandbox
checkout confirmation. The owner is signed in, and the actual Checkout is open.
Package installation alone is not application readiness.

## Accepted release

PR36 billing merged as `f62bc3f43b739bfd1f91b9630553f3f989fef52d`.
PR40 release `--latest=false` guard merged as
`e6b831cc51ce80e517490c25327fb0a88559efcd`.
PR41 restricted PostgreSQL 17 migration fix merged as
`453ebec4b6592d1e089a3f5d04da0f35a78a4f09`. The accepted WEB-005
landing change is included; PR43 is not.

Exact-head and integrated CI 37329909083 passed. Migration validation included
28 restricted-admin PostgreSQL 17 cases, 29 billing database cases, both full
backend profiles (997 self-managed; 996 managed and one expected skip), preserved
data and repeat upgrades. Frontend 177 tests, lint, TypeScript and standalone
build passed before the subsequently accepted database-only compatibility fix.

Build 37330253646 produced the matching
[azure-453ebec4b659 release](https://github.com/VladimirMalevanik/flare/releases/tag/azure-453ebec4b659).
Private downloads matched published digests, SHA256 sidecars, ZIP CRC, required
files and embedded release SHA. Both API and worker use the same backend ZIP.
Hashes and installation evidence are recorded in `validation.json`.

## Recovery boundary

The captured private old API/worker archives expect schema 0018; old web is
b54220213f47. These are not a valid rollback after forward-only migration 0021.
PostgreSQL has 7-day PITR retention; restore metadata was checked immediately
before migration. No actual PITR restore was performed: Azure PITR creates a new
server, outside this rollout's no-new-paid-resources boundary.

OPS-003 closed the prerequisite with independently reviewed, executable Linux
packages that retain schema 0021 and the complete accepted database capability
checks. PR44's first workflow had invalid runner-context job env expressions;
PR45 corrected only that workflow and its own report. Actual Linux build
[37431064967](https://github.com/VladimirMalevanik/flare/actions/runs/37431064967)
passed at `b9ccdc62fd166d13ea412753f736c635eff0a984`, including 215
historical core tests, restricted preserved 18→21 data, auth/email/sessions,
workspace isolation, queue/Flare, daily quota, pending-ZIP/private-ledger
isolation, cold restart, portable imports and legacy frontend checks. One obsolete
FK-only case was explicitly deselected and replaced by restrictive RLS denial
and zero inserted rows.

All three fallback ZIPs were independently downloaded and validated: hashes,
CRC, source manifests, 79 complete application modules in both installed and
top-level locations, matching API/worker runtime tar, native Linux web binaries
and embedded release SHA. Source pins and hashes are in `validation.json`.
Fallback has not been deployed in production. Its temporary limitations include
unavailable billing, ZIP import and new privacy/growth UI. Recovery requires all
three matching components, pausing Paddle, keeping schema/data 0021, and replaying
delivery when the normal release returns. A revision-only readiness patch is
not an acceptable fallback.

## Controlled cloud migration

On 2026-10-06 the actual restricted production administrator upgraded 0018→0021.
The sanitized report completed at 07:59:48 UTC: first upgrade exit 0, repeated
upgrade exit 0, actual head 0021, preserved aggregate table counts unchanged and
zero active analysis, Flare or refresh work. The worker was independently
confirmed stopped, and the local maintenance endpoint rejected all writes with 503
before the final snapshot and DDL. Public maintenance probes timed out during
Azure warmup; the successful local guard authorized apply. No public 200 was claimed.

`controlled_migration.py` ran from a complete exact 453ebec git archive, since the
application ZIP omits migration/db SQL. It checked archive/script checksums,
fresh exclusive extraction, source import location, Alembic graph, database host,
TLS and administrator restrictions. The existing managed identity fetched the
migration credential into process memory only. The Alembic child had a minimal
migration-role environment. No administrator credential was put in application
settings or a plaintext file, and the temporary extraction was removed.

The administrator remains NOSUPERUSER/CREATEROLE/BYPASSRLS. API/worker retain
their restricted credentials and normal readiness checks. Firewall, TLS,
verified-email auth, staging restrictions and secret access policies are unchanged.

## Deployment and Sandbox configuration

Azure SCM reports complete/status 4 for the normal API, worker and web ZIP
installations. Embedded 453ebec RELEASE_SHA was read back for each site. Normal
API startup was restored after maintenance; worker was started and web restarted.
API /ready 200 and the web /api/ready 200 passed. Unsigned webhook requests return
401 billing_invalid_signature; unauthenticated web billing returns 401. The worker
passed a separate read-only SQL/runtime/capability/process check before its brief
resource-coordination stop. GET /login 200 verifies page availability, not an
authenticated session.
The restarted worker returned 200 and its fresh read-only SQL/process probe
passed all 27 checks at 08:29:57 UTC. This is not a completed-job test.
Slow Azure Linux certificate initialization preceded a startup-probe failure; API cold-start
allowance was increased to 600 seconds without removing readiness or TLS checks.

Paddle Sandbox product Flare Pro has the configured active USD 12/month price
`pri_01m3y1nvmgw2avt60bz87161c2` and 30-day trial. Public frontend settings
match Sandbox; no token is reproduced in this report.

The verified owner signed into the deployed Flare Settings page on 2026-10-06.
The first Buy action exposed Paddle's `transaction_default_checkout_url_not_set`
error. The existing Sandbox default payment link was set to
`https://flare4u.tech/settings`; its UI shows Approved and Test Mode. Retrying
Buy opened the actual Paddle Sandbox overlay with Flare Pro, quantity 1 and a
30-day free trial. Only the official fictitious Paddle card was entered.
The final Subscribe now step is awaiting the owner's action-time confirmation;
no completed checkout, signed event or Pro grant is claimed from opening the form.
Automatic `_ptxn` payment-method-update/dunning links have not been verified;
the current client initializes Paddle when Buy is clicked.

Owner-confirmed destination `ntfset_01m47zz283676cayy23388e71v` points at
`https://flare-api-vm-260914.azurewebsites.net/billing/paddle/webhook`, Platform
traffic/API1, with exactly subscription.created, updated, trialing, activated,
past_due, paused, resumed and canceled. It was activated only after API/web
readiness, secret resolution and the worker
SQL proof passed. The Sandbox UI now shows Active, 8 events and Platform traffic.

Its signing secret was stored privately as `paddle-sandbox-webhook-secret` in the
existing Key Vault, privately compared and the local plaintext removed. API-only
PADDLE_ENVIRONMENT=sandbox, PADDLE_PRO_PRICE_ID and a versioned Key Vault secret
reference are configured. Azure reports that reference Resolved. Existing API
secret rights remain get/list. No server signing secret goes to worker/frontend.

## Remaining acceptance checks

1. Complete the prepared real Sandbox checkout in the owner's verified Flare
   session. Verify server-bound checkout intent, trialing Pro persisted
   through refresh, signed delivery, workspace-wide state and cancellation.
   Never manually grant Pro or forge provider events to claim live verification.
2. Replay the genuine event and verify unchanged state. Paddle changes
   notification_id on replay; this release fingerprints the raw envelope and may
   return a safe conflict/noop rather than duplicate. HTTP 200 alone is insufficient.

Temporary cloud scripts, archive, sanitized remote reports and source directories
were removed after normal startup and the fresh worker SQL proof. Private local
sanitized evidence remains available to the operator.

No Paddle Live environment, server API key, premium quota expansion, user-data
dump or production database restore was introduced. No secret, private database
URL, raw webhook body, opaque checkout intent or authentication token belongs in
this public report.
