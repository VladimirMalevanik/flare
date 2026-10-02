# Accepted onboarding, Project Memory and attribution decisions

Accepted by the human/product owner on 2 October 2026. This document records the
owner's explicit acceptance and the contracts for the next tasks. It authorizes
task creation, not implementation by the coordination agent or deployment.

The accepted research is preserved unchanged, including its historical
"acceptance pending" wording. The decisions here govern the choices resolved by
the owner; remaining research proposals and numeric examples are not approvals.

| Research | Original branch | Accepted head | Artifacts |
| --- | --- | --- | --- |
| DATA-001 | research/data-001-async-zip-20261002 | `c7f7834a5c000049c0f284915b26e16bfc8acdfb` | [DATA report and supporting artifacts](research/DATA-001/report.md) |
| ARCH-001 | research/arch-001-project-memory-20261002 | `d2fef70c545bc0229487c637315279985b9d4682` | [ARCH report and supporting artifacts](research/ARCH-001/report.md) |
| GROWTH-001 | research/growth-001-attribution-20261002 | `090f7ab9071d032dbb1964015ed71beeae951494` | [GROWTH report and supporting artifacts](research/GROWTH-001/report.md) |

Integration began from main `8cfddd49b2af7d88e357173a55af5e1a35384c9e`.
Each entire research diff was inspected against its recorded research base;
only new regular files inside its declared directory were present. Normal
cherry-picks preserve the original heads in commit messages and preserve artifact
bytes. The task-sync completion records identify the published integration SHA
and retain each task's original validation evidence. Research acceptance does
not establish measured production capacity, live Groq quality, or verified Azure
collector/storage configuration.

## Import

The purpose is one-time onboarding of existing project knowledge. Notion uses a
ZIP snapshot, with no OAuth/workspace synchronization in v1. Obsidian uses a ZIP
vault/project snapshot, with no watcher or plugin synchronization in v1.
Processing is asynchronous.

**Publication uses a package gate.** Package files cannot become normal visible
or Analyze-eligible Project Memory until the package publication gate commits.
Each file remains atomic; bounded provisional writes/checkpoints do not expose
incomplete content. Every reader must honor the gate, including list/detail,
Vault/search, source exports, manual/scheduled Analyze selection and evidence
reads. Successful packages may complete with skips and a durable entry report.
Unsafe archive paths, encryption, malformed archives, failed integrity and
resource-policy violations fail before visibility. Partial early publication is
not the accepted v1 contract.

Supported v1 content is `.md`, `.markdown`, `.txt` and `.csv`. Preserve provenance,
safe relative paths and authoritative source/version/chunk evidence. Markdown
may retain literal safe frontmatter, code and inline HTML as source text;
nothing is executed.

Images, PDF, audio, video, Office files, standalone unsupported HTML/JSON/Canvas
or plugin data, nested archives, and Obsidian/plugin/application configuration
are **skip + report**. They are neither analyzed nor sent to an AI provider.
Unsupported entries still pass applicable package safety checks; skipping a
format cannot turn a security or integrity failure into success.

The original ZIP is temporary staging. After durable successful publication,
delete it through durable, retryable cleanup. Long-term source-ZIP retention is
not required. Failed/cancelled/abandoned staging expiry and physical retention
need explicit operational settings; an API deletion does not prove all retained
versions/backups are gone.

Transport and finalize retries are idempotent. The exact same accepted package
in the same workspace/source context replays the existing receipt/result rather
than duplicating documents, including after source edits/deletions. A genuinely
different ZIP is a new onboarding import. There is no automatic reconciliation,
update or deletion synchronization with older snapshots. Identity and policy
binding must be explicit and tenant-safe.

Use an independently configurable policy matrix:

| Dimension | Independent controls |
| --- | --- |
| Archive | Compressed upload bytes, expanded bytes, entry count, individual file bytes, safe path/depth |
| Parsing | Text/CSV/chunk bounds; bounded reports and response pagination |
| Runtime | Upload/processing deadlines; worker CPU, RAM and scratch |
| Storage | Staged storage quota; durable source quota; reservation and release |
| Admission | Concurrent imports per workspace; global concurrency |
| Recovery | Retries, leases, backoff, staging expiry and cleanup expiry |

No final production numbers are approved. Explicit development/test fixtures
are allowed; production tuning needs representative load evidence and approval.
Import never starts normal Analyze, consumes its daily slot, or synchronously
creates a Groq call per file. Originals remain usable independently of AI
enrichment. The existing one manual OR scheduled Analyze per workspace local
calendar day and its safeguards remain intact.

Vova has not selected the production staging service or upload path. Domain
interfaces, local/test storage and application/worker contracts may proceed.
Azure Blob, shared filesystem, network, managed identity and production storage
topology must not be silently selected or provisioned.

## Project Memory

The accepted flow is:

`original source → deterministic bounded sections → compact derived characteristics → document representation where useful → lexical-first relevance retrieval → explicit counterevidence/completion retrieval → original evidence → existing bounded Analyze/Flare generation`.

Original source/version/chunk evidence is authoritative. Derived characteristics
and summaries are retrieval indexes, not project truth or final citation
evidence. Missing completion evidence is not proof of unfinished work. Preserve
edit/delete invalidation, tenant isolation and historical citation lineage.

Start with layered section/document characteristics and lexical retrieval.
Embeddings are deferred, even though a vector column exists. Reconsider them
only after measured lexical/paraphrase/language evaluation.

**AI enrichment implementation is deferred.** The responsible owner/person must
supply approved entitlement, onboarding AI credit, rolling/day budget, workspace
and global Groq ceilings, concurrency, paid/free behavior, actual numeric limits
and rollout policy. Research completion grants no automatic provider calls or
additional Analyze allowance. Existing source usability cannot depend on
enrichment availability. Research budget examples are not production defaults.

## Analytics and attribution

The long-term goal is acquisition → signup → activation → retention, with more
product behavior analysis possible later. The initial implementation stays small
and extensible. Flare owns authoritative first-party attribution and business
milestones. Azure/Application Insights/Log Analytics can later provide reporting
or operational telemetry if Vova verifies it; they are not the sole conversion
truth. No third-party analytics vendor is selected.

Store both first observed touch and last eligible non-direct touch before
registration. Freeze signup attribution at account creation. Later login does
not rewrite it. The bounded initial fields are `utm_source`, `utm_medium`,
`utm_campaign`, optional `utm_content`, approved referral/ref code, external
referrer domain, canonical landing route, timestamps and schema-policy revision.
Server validation and normalization discard arbitrary query parameters and full
referrer URLs/query strings. Optional analytics must not block account creation.

Initial milestones support:

`eligible landing/touch → account created → actual email verification where applicable → committed capture OR published import → manual Analyze completed → voluntary Flare/evidence inspection → qualifying human activity on a later day`.

Use stable logical outcome IDs and authoritative commit/terminal facts for
dedupe/reconciliation. Upload acceptance, parsing, enrichment, Analyze requests
or preparation refreshes do not establish these completed milestones. Replays
do not add conversions. Verification bypass/legacy status is not actual email
verification. Scheduled/background jobs, polling and delivery retries are not
human return. Keep milestone contracts versioned so approved product actions can
be added later, without a generic every-click warehouse.

Analytics excludes bodies, titles/paths, ZIP paths, emails/names/passwords,
session/verification secrets, provider prompts/responses and arbitrary
URLs/query strings. Reuse authenticated `activity_events` where appropriate;
keep anonymous/acquisition persistence separate without weakening tenant RLS.
Maintain data minimization, deletion/cleanup hooks, measurement eligibility and
bounded anonymous intake.

Start with restricted queries, aggregate exports and reporting; a large internal
analytics UI is deferred. The versioned schema/query contracts must support a
later UI. Anonymous lookback, cookie lifetime, raw and aggregate retention need
explicit later product/deployment approval. No production duration or headline
activation/D7/W1 metric is silently selected from research examples. Report
milestones, coverage, unknowns and cohort maturity explicitly.

## Shared implementation boundaries

DATA owns ingestion, publication, provenance, progress and staging lifecycle.
Its durable published-original contract supplies stable workspace/package/
document/version/chunk identity, parser revision and provenance to downstream
consumers through a bounded replayable outbox/cursor or equivalent durable
contract. Nothing triggers enrichment before publication, or requires an
enrichment consumer to make import succeed.

GROWTH observes committed capture/import outcomes and terminal manual Analyze
outcomes. It owns acquisition identity, normalized event/fact contracts, dedupe
and reporting. An import publication observation includes stable logical ID,
workspace/requester, committed time/status and bounded counts, without source
text/paths. Analyze observation distinguishes manual/scheduled mode and terminal
analysis plus Flare generation; enrichment is a separate status. Implementation
owners must review exact API/outbox contracts before editing shared files.

ARCH owns derived-memory lifecycle, retrieval, counterevidence and provider
admission/accounting after the budget gate is resolved. DATA never implements
automatic enrichment; GROWTH never changes retrieval or the Analyze allowance.

## Task contracts and migration ordering

These are planned scope envelopes, not claims or published implementation
branches. Each executor must fetch fresh main, read task context, inspect active
scopes, claim their task and publish the exact branch/base/head/write scope
before editing. Shared files are allowed only for the named task purpose. Stop
and coordinate unexpected overlaps or needed scope expansion. Accepted research,
secrets, `.codex/`, production deployment/resources and production dependencies
are outside these scopes; dependency changes require owner confirmation.

Latest inspected main has a single migration chain ending at `0018` and exact
runtime schema-readiness checks in `backend/app/models/database.py`. **DATA-002
integrates first; GROWTH-002 depends on DATA-002.** DATA-002 can be marked done
only after owner acceptance and integration to main. GROWTH-002 then fetches
that accepted main, validates its single migration head and starts a new clean
branch from that base. Allocate new revisions from the head actually merged;
do not reserve numbers now, create parallel heads from `0018`, rewrite existing
migrations, or weaken readiness/migration checks. This also serializes shared
API/provider/i18n edits. Any later ARCH migration requires the same fresh-main
single-chain coordination after its start gate is approved.

### DATA-002

State: `next`, unclaimed. Dependency: DATA-001 (accepted research).

Deliver production-quality application implementation of the accepted async
one-time ZIP contract: package/session states and new migrations, forced RLS and
tenant isolation, PostgreSQL jobs, safe inspection and parsing, package gate,
provenance, skip/report, exact-package idempotency, status/progress/cancel/retry
APIs, configurable quotas/reservations, staged-object abstraction and local/test
implementation, durable cleanup, leases/checkpoints/restart, Vault/source
integration, security fixtures, application tests and a load-test harness.
No automatic Analyze or AI calls.

Planned write envelope:

- Import-specific modules under `backend/app/api/`, `models/`, `services/` and
  `workers/` (new `import_*`/`zip_*` modules and existing `api/imports.py`,
  `models/import_batches.py`, `services/import_service.py`); a dedicated new
  staged-object storage namespace under `backend/app/`.
- Gate/contract wiring only in `backend/app/api/{schemas,routes,export}.py`,
  `backend/app/models/{tables,analysis_runs,analysis_schedules,flares,database}.py`,
  relevant item/context/analysis/schedule services, `backend/app/config.py`,
  `backend/app/main.py` and worker configuration/registration.
- New successors under `backend/migrations/versions/`; matching schema, import
  worker privileges and tenant inventory in `backend/db/`; corresponding
  `backend/tests/` and import-specific security/load scripts under
  `backend/scripts/`. Existing migration files stay unchanged.
- Import UI only in `frontend/src/features/{capture,vault,sources}/`, contract
  wiring in `frontend/src/lib/data/`, required import strings in
  `frontend/src/i18n/`, matching `frontend/tests/`, and
  `docs/implementation/DATA-002/`.

Production storage/deployment wiring requires the relevant OPS-001 decision;
the entire application task is not blanket-blocked on OPS. If an indispensable
choice prevents application work, move DATA-002 to waiting and name it exactly.
Do not invent production limits. Acceptance requires isolation/gate checks
across all readers, fidelity/idempotency, crash/cancel/cleanup recovery, no AI or
Analyze side effects, load evidence with explicit limitations, a single accepted
migration head and owner review. Production rollout remains separately gated.

### GROWTH-002

State: `next`, unclaimed and dependency-blocked. Dependencies: GROWTH-001 and
DATA-002. Start only after DATA-002's accepted migration/application base is
merged to main; fetch/validate that base before claim and editing.

Deliver bounded pre-auth acquisition, first observed plus last eligible
non-direct touch, account/workspace linkage, campaign/ref/referrer normalization,
server validation, milestone dedupe/reconciliation, suitable authenticated event
reuse, separate acquisition persistence, activation/return support, restricted
aggregate/query/export, minimization and deletion/cleanup. Test navigation →
registration → actual verification → product outcomes, including replays,
shared-device/unknown cases, scheduled exclusions and denied reporting access.
No full analytics UI, generic click collector, vendor or Azure correctness
dependency. Unapproved production lifetime/retention settings remain explicit
deployment gates; no silent defaults derived from research examples.

Planned write envelope:

- New `acquisition_*`/`attribution_*`/`funnel_*` backend modules; existing
  `backend/app/api/{auth,analytics,schemas}.py`,
  `backend/app/models/{auth,events,database}.py`, and
  `backend/app/services/{auth_service,analytics_service}.py` for attribution,
  provenance and reporting; minimal committed-outcome observation wiring in
  routes/import/analysis services without changing their domain semantics.
- New successors to the accepted DATA migration head under
  `backend/migrations/versions/`; matching schema/restricted reporting privileges
  in `backend/db/`, API/config registration, corresponding `backend/tests/`
  and growth-specific query/load scripts under `backend/scripts/`.
- Acquisition/identity and voluntary-event wiring in `frontend/src/app/`,
  `frontend/src/features/{auth,insights}/`, `frontend/src/lib/{auth,data}/`,
  required i18n strings, matching `frontend/tests/`, and
  `docs/implementation/GROWTH-002/`. No unrelated layout redesign.

Shared gate/provider/schema files are sequential, not concurrent ownership.
Acceptance includes lineage/dedupe/privacy, restricted reporting, bounded intake,
deletion/cleanup, coverage semantics and a single migration chain with exact
readiness checks and human acceptance.

### ARCH-002

State: `waiting`, unclaimed. Dependency: ARCH-001. This is a future implementation
contract, not an executable automatic-enrichment assignment.

Start condition: the responsible Groq/enrichment-budget owner supplies approved
entitlement/onboarding credit, rolling/day and workspace/global ceilings,
concurrency, paid/free behavior, numeric limits and rollout policy. Record that
approval and coordinate exact shared/migration scopes before moving to next or
claiming. Until then, do not implement/start automatic AI enrichment.

The future scope covers section/document characteristics and lifecycle, lexical
retrieval, explicit counterevidence/completion, original-evidence grounding and
evaluation. Embeddings are deferred. Planned envelope after approval is
memory-specific backend modules, bounded context/Analyze adapters, versioned
schema/worker capabilities and tests, and `docs/implementation/ARCH-002/`;
exact scopes are deliberately not activated before the budget decision.

### OPS-001

State: `next`, unclaimed; decision owner Vova. No task dependency.

Resolve production staging service, upload path, API/worker storage reachability,
worker isolation/resources, identity/network/CORS where relevant, physical ZIP
deletion/retention and monitoring/load-test environment. Publish a dated,
redacted decision/evidence record in `docs/implementation/OPS-001/`; do not
read secrets or provision resources under this decision-only scope. Repository
evidence alone does not complete the task. Product quota numbers still require
load evidence and owner approval. DATA production wiring waits only for the
specific required OPS decisions, not unrelated Azure analytics choices.
