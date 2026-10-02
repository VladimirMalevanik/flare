# GROWTH-001: acquisition and product-funnel analytics

Research date: 2 October 2026 (Europe/Moscow). Owner: Fedor / Codex / GROWTH-001.
Status at handoff: research complete, submitted for review; acceptance pending.

## Result and recommendation

**No Azure product-analytics service is verified as enabled by this research.**
The repository describes Linux Azure App Service hosting and Azure PostgreSQL,
and public web/API/worker endpoints respond successfully. It does not declare
Application Insights instrumentation, a Log Analytics workspace/diagnostic route,
or Front Door. Their absence from the repository does not prove their absence
from Azure. No Azure management-plane access, deployed resource inventory,
telemetry samples, or authenticated production database evidence was available.

Flare already implements a bounded, first-party PostgreSQL `activity_events`
layer for authenticated product interactions and outcomes. It is not an anonymous
acquisition layer. Its current summary counts workspace events, not ordered
user funnels or acquisition cohorts. The public analytics route rejects an
unauthenticated read; that establishes a reachable protected route, not that
events are being persisted correctly in production.

**Recommended next implementation direction, subject to product approval:**
extend Flare's existing first-party foundation with separate, minimal acquisition
and registration-link persistence; reuse useful authenticated events; reconcile
business outcomes with authoritative records. Start with restricted reports and
exports, not a full internal analytics UI. Keep operational telemetry separate
from the source of truth for conversion. This is a recommendation, not approval
of touch semantics, new schema, dependencies, telemetry services, or deployment.

If Vova supplies evidence of a working Application Insights/Log Analytics setup,
Option A below becomes a credible alternative reporting sink. It still needs
Flare-owned attribution normalization, anonymous-to-user linkage, trustworthy
outcome emission, and explicit sampling/completeness policy. Azure hosting alone
does not supply these.

## 1. Scope, snapshot, and coordination

| Item | Recorded value |
| --- | --- |
| Repository | `VladimirMalevanik/flare` |
| Pre-claim context SHA | `1dc923c0ea80a43cab908f81c6eb644ae017a392` |
| Successful published claim / source / branch base SHA | `7d734d4deabb90eb0d22a6e2840bf8755f44c13b` |
| Published scope-state SHA | `6c62eaa9e05b103ecee1b20e42f68d34cc0d7d00` |
| Branch | `research/growth-001-attribution-20261002` |
| Worktree | `/Users/fedornikonov/flare-growth-001` |
| Only declared write scope | `docs/research/GROWTH-001/` |
| Required report | `docs/research/GROWTH-001/report.md` |
| Acceptance | Human review; task must not be marked done |

Root `AGENTS.md`, `project-ops/AGENT_SETUP.md`, BOARD, NOW, GROWTH role,
summary, list, task context, and the entire claim `required_context` were read.
The coordination tool is isolated outside the checkout: task-sync-git 0.1.0,
upstream tag resolving to `4d936d3c76e71f28aaa03b8d196a2a812e6b0f40`.
The clean branch was ordinarily pushed before scope publication and first edits.
The existing dirty main checkout and other agents' worktrees were left untouched.

All active tasks were inspected before claim and again after scope publication:

| Other active task | Declared scope | Ownership boundary |
| --- | --- | --- |
| DATA-001 | `docs/research/DATA-001/` | ZIP staging, processing, publication, progress; GROWTH observes import outcomes only |
| ARCH-001 | `docs/research/ARCH-001/` | Enrichment, retrieval, quality, AI budgets; GROWTH observes Analyze outcomes only |

Scopes are disjoint. There is no product implementation overlap. Section 6 records
shared event-interface proposals and requests for those owners' review, without
claiming agreement. They are observational contracts, not changes to ingestion,
retrieval, provider budgets, or the one manual OR scheduled Analyze per workspace
local calendar day rule. Their completion is not a dependency of this research.

Before publication, ARCH-001 had moved to review. Its published report at
`d2fef70c545bc0229487c637315279985b9d4682`, section 6, was inspected read-only:
its outcome boundary is consistent with this report (enrichment readiness is
not Analyze/activation, and no per-chunk/content payload goes to funnel analytics).
This compatibility check is not owner acceptance of the proposed envelope.
DATA-001 was still active with the same distinct scope. The final context receipts
and coordination-only main advancement are recorded in `repository-evidence.json`.

Repository facts below refer to the source SHA above. Later coordination commits
do not silently change that source. The inventory in `repository-evidence.json`
records file hashes and line anchors. Public deployment observations are a
different snapshot and do not establish that production runs this source SHA.

## 2. What Azure is actually deployed or configured

### Evidence categories

* **Observed production:** a direct, timestamped public read made in this task.
* **Repository:** code, declarations, or documented topology at the source SHA;
  it does not prove a setting is enabled or a migration applied in production.
* **Platform capability:** current primary documentation; conditional on service,
  permissions, instrumentation, and configuration being present.
* **Unknown / Vova:** management-plane, database, or operator evidence unavailable
  here. No secrets, `.env`, credential stores, cloud settings values, or private
  user data were read.
* **Proposed Flare persistence:** a future design; nothing has been implemented.

### Actual evidence inventory

| Item | What the evidence establishes | What it does not establish |
| --- | --- | --- |
| Public web and auth page | `https://flare4u.tech/` and `/login` returned HTTP 200 at 10:15 Moscow; `www` login navigation ended at the canonical apex | Build/source SHA, actual registrations, traffic volume, or any enabled cloud collector |
| API proxy and Azure API hostname | `/health` returned `{"status":"ok"}` and `/ready` returned `{"status":"ready"}` at both public proxy and `flare-api-vm-260914.azurewebsites.net` | Azure subscription, plan, resource state, event inserts, exact production schema, or PostgreSQL service identity |
| Worker Azure hostname | `flare-worker-vm-260914.azurewebsites.net/ready` returned `{"status":"ready","role":"worker"}` | Scheduled-job success, provider access, Analyze completion, or telemetry retention |
| Public analytics surface | GET `/api/analytics/events` returned 401 `Authentication required` | Authenticated insert/read behavior or persisted production event counts |
| Landing-page telemetry | No listed telemetry markers in landing HTML, login HTML, or the 11 landing script assets inspected; hashes retained | Runtime network behavior, dynamically loaded/authenticated assets, same-origin collectors, or server-side instrumentation |
| Browser security policy | Public CSP has `connect-src 'self'`; `Referrer-Policy` is `strict-origin-when-cross-origin` | An analytics SDK or a collector; current policy would need review for direct browser Azure ingestion |
| Azure topology | Release checklist describes resource group `flare-dev`, `centralus`, three Linux App Services on B1, PostgreSQL Flexible Server, Key Vault and OneDeploy [R1] | Fresh Azure inventory; checklist requires re-verification and is not a deployment receipt |
| Release packaging | Workflows build standalone web and separate backend packages; public API hostname and API provider are configured in packaging [R2] | Artifact deployment success or what App Service app settings currently contain |
| API logs | Startup disables Uvicorn access logs; custom request logger emits method, route template, response status, duration, excluding URL/query/body/user identity [R3] | Whether App Service captures/retains this output, forwards it, or has any separate HTTP logs |
| Application Insights / OpenTelemetry | No matching SDK dependencies, initialization, connection-string declaration, or agent configuration in scanned source/deployment paths [R4] | Portal-configured agent/autoinstrumentation cannot be excluded |
| Azure Monitor / Log Analytics | No workspace or diagnostic-settings deployment declaration identified in tracked files | Logs enabled in portal, their destinations/categories, table plans, retention, sampling, caps, dashboards or billing |
| Azure Front Door | No configuration declaration identified | Presence or absence in the live request path; it must be verified by resource inventory |
| Existing product events | Source defines `activity_events`, authenticated endpoint, exact allowlists and producers [R5–R9] | Production migrations and reliable coverage; public readiness is insufficient proof |

The concrete meaning of “Azure analytics” supported by available evidence is
**Azure-hosted Flare with application log code and first-party PostgreSQL product
events**. Enabled Azure analytics/telemetry collection remains unresolved. Do not
rename this evidence “Application Insights analytics,” “Azure Monitor funnels,”
or “Front Door traffic analytics.”

### Native platform capabilities, only if configured

* App Service can capture application diagnostic output; Linux application logging
  has explicit enablement, quota and retention settings. The documented W3C web
  server log option is listed for Windows, so it cannot be assumed for this Linux
  topology. Logs do not create the missing business identity bridge.
  [App Service diagnostic logs](https://learn.microsoft.com/en-us/azure/app-service/troubleshoot-diagnostic-logs).
* Application Insights supports instrumented page views/custom events, user/session
  analysis, funnels, cohorts and a retention workbook. Known-user context enables
  authenticated analysis; browser identifiers alone can count the same person
  separately across browsers. Business actions require appropriate events.
  [Usage analysis](https://learn.microsoft.com/en-us/azure/azure-monitor/app/usage).
* Browser SDK cookies and their scope are configurable. Flare would need a reviewed
  browser collection/identity policy and a compatible collector route/CSP; automatic
  collection must not copy private paths or queries.
  [JavaScript SDK configuration](https://learn.microsoft.com/en-us/azure/azure-monitor/app/javascript-sdk-configuration).
* Custom event tables require custom instrumentation. Application Insights and
  workspace query contexts use different table names, such as `customEvents` versus
  `AppEvents`; map the actual schema before building reports.
  [Telemetry model](https://learn.microsoft.com/en-us/azure/azure-monitor/app/data-model-complete).
* Sampling reduces stored telemetry, and a daily cap can stop ingestion. Exact
  cross-session conversion joins cannot be reconstructed from missing identities
  or events merely by weighting aggregate counts. Confirm loss separately for
  each collection path, including browser, server and export.
  [Sampling and caps](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-sampling).
* Azure Front Door can provide edge access/WAF diagnostics, but access logs are not
  enabled by default. Edge request correlation is not a registered-user or
  activation identity. No Front Door deployment was verified here.
  [Front Door monitoring](https://learn.microsoft.com/en-us/azure/frontdoor/monitor-front-door).

### Evidence needed from Vova

Supply a dated, redacted inventory, not credentials or setting values:

1. Deployed commit identifiers for web/API/worker, resource names/types/region and
   actual routing topology, including any Front Door/CDN/reverse proxy.
2. Whether Application Insights resources and linked Log Analytics workspaces
   exist; which app has SDK/agent/browser instrumentation; which setting **names**
   indicate enablement. Omit connection strings and keys entirely.
3. App Service log enablement/categories, diagnostic destinations, retention and
   quota; Azure log table plans/retention, sampler settings, ingestion caps and
   ingestion failures; whether safe request logs are captured.
4. Sanitized telemetry examples or schema-only query output showing event name,
   anonymous/authenticated identifiers, workspace association, timestamps and
   campaign dimensions. One controlled, owner-run journey should demonstrate
   landing → registration → actual verification → capture/import → manual Analyze
   completion → later human activity. Report identifiers as synthetic labels.
5. Production migration revision and existence/coverage of `activity_events`,
   `auth_users`, import batches and analysis records; reporting permissions and
   cleanup execution evidence, without downloading real user records.
6. Actual email-verification mode/SMTP readiness, analytics region/budget, query
   owner, deletion/export handling and acceptable reporting access.

The release checklist says verification launch is blocked and the setting remains
false until outbound mail works. That is a repository statement, **not a fresh live
configuration check**. No account was created, verification mail sent, or product
action triggered during these production reads.

## 3. Current Flare funnel coverage

| Question | Repository evidence and present limit | Needed for a trustworthy answer |
| --- | --- | --- |
| Where do visitors come from? | No UTM/ref/referral/referrer capture or anonymous visitor persistence found [R4, R10] | Validated landing touch, source/medium/campaign, referrer domain and measurement eligibility |
| Which visitors register? | Registration creates `auth_users` and an initial workspace atomically; request schema forbids extra fields and has no acquisition token [R10, R11] | A server-owned registration bridge to a valid anonymous attribution record; signup counted at account commit |
| Who really verified email? | `email_verified_at` and consumed verification records exist, but verification-disabled registration also marks verified; the migration backfills legacy accounts [R10, R12] | Verification provenance: link-confirmed vs bypassed vs legacy/unknown; timestamp alone is not sufficient |
| Who captures content? | Server `item_created` and browser capture interaction events exist [R6, R7, R9] | Distinct committed document/actor, not modal-open or retry counts; document source type retained without text |
| Who imports? | Server import start/completed/failed; completed has batch ID, replay emits completed again; only some failure paths emit failed [R8] | Distinct published batch and terminal status, cancellation/partial-publication semantics for future ZIP; no per-file flood |
| Who runs Analyze? | `analysis_requested` has manual/scheduled mode and run ID; refresh completed is a preparation stage [R6, R13] | Join run → analysis job → Flare generation terminal status; a request/refresh is not successful analysis |
| Who sees value? | `flare_viewed`, `item_viewed`, Sources navigation are browser signals; per-open view suppression is local UI behavior [R9] | Defined activation rule combining durable content/run outcome with voluntary interaction; view is not proof of usefulness |
| Who returns? | Events have actor/time; auth session `last_seen_at` is overwritten on session resolution, not a visit history [R5, R11] | Eligible foreground product event on a later date/session; separate human activity from scheduled jobs/polling |
| Which channels retain useful users? | No acquisition bridge, activation definition or channel/cohort query; existing summary groups event counts per workspace for 1–720 hours [R5] | Frozen acquisition basis, distinct actor/workspace cohort, ordered activation and matured retention windows |

Additional limitations matter for interpretation:

* `activity_events.workspace_id` is required; RLS binds membership and inserting
  actor identity. It is intentionally unsuitable for pre-auth visitors [R5].
* Browser events accept only eight named UI interactions, validate target presence
  where relevant, and permit at most 600 events/hour per actor/workspace. Metadata
  fields/values are bounded and source content is rejected [R6]. This protects
  the authenticated path; it is not an anonymous ingestion budget.
* Most product-event writes are best effort. They do not share the business action's
  transaction and may be dropped. Missing events must be reported as a coverage
  limitation, not proof no action happened. Some SQL-issued Analyze events are
  transactional; there is no uniform guarantee across the event vocabulary.
* Existing event IDs do not deduplicate replayed business actions. A retried import
  can produce several `import_completed` rows for one batch. Count unique stable
  outcome IDs or reconcile authoritative state; do not add unrelated event counts.
* `analysis_refresh_completed` does not establish model/Flare completion. The
  existing `read_analysis_run` contract combines analysis job and generation state
  [R13]. A completed run with zero Flares may be a valid completed run, but whether
  it is activation/value is a product decision.
* Activity maintenance is workspace-owner-invoked, bounded deletion. Its request
  defaults to 90-day retention and dry run. No automated execution was found in
  the inspected workers; a default request value is not an enforced production
  retention policy [R14]. Some job cleanup defaults are shorter, so later cohort
  joins need either retained terminal facts or rollups before source cleanup.
* Business records without events may recover committed registration/import/run
  counts. They cannot recover historic UTM, actual foreground visits, or missing
  verification provenance. Do not fabricate those dimensions during a backfill.

## 4. Azure-native extension versus bounded first-party extension

Both options require new application work; neither is implemented or approved.

| Dimension | A — Extend Azure telemetry, if verified present | B — Extend Flare first-party analytics |
| --- | --- | --- |
| Starting evidence | Azure hosts are reachable; a collector/workspace is unverified | Source already contains bounded authenticated events and relational business identities; production coverage unverified |
| Acquisition | Instrument page/touch collection, sanitize metadata, attach session and visitor context | Separate minimal attribution records; capture only landing/session touch, not every click/page |
| Anonymous → signup join | Explicit link event or durable attribution snapshot plus stable analytics user/workspace dimensions; setting known-user context after login is not a demonstrated historic bridge | Server registration consumes a server-issued touch/visitor reference and snapshots attribution with account/workspace IDs |
| Business trust | Emit committed server outcomes; browser success/HTTP 2xx is insufficient | Reuse events for interaction; rely on domain records or a minimal transactional terminal-fact/outbox design where completeness is needed |
| Retention cohorts | KQL/workbooks with consistent identity, complete collection and adequate table retention; normalize scheduled/human actions | SQL with stable IDs, explicit dedupe and cohort definitions; maintain bounded daily activity/terminal facts when raw records expire |
| Sampling and outages | Sampling, caps, ingestion delay/loss and browser blocking can break joins; instrument/monitor completeness | No sampling for business facts; landing/interaction losses still exist; isolation, idempotency and reconciliation require engineering |
| Security/privacy | Azure RBAC plus reviewed property collection, sanitization, browser policy and deletion in every sink | Preserve workspace RLS; separate acquisition writer; add restricted reporting access and deletion lifecycle; no public cross-tenant query |
| Operational reporting | Reuse actual existing workspace/KQL/workbooks if Vova proves access and suitable tables | Versioned restricted query/export first; aggregate report with no customer-content access; new analytics UI can wait |
| Cost | Ingestion GB, retention, alerts, export destination/egress and instrumentation maintenance; confirmed existing capacity may reduce marginal work | DB rows/indexes/WAL/backups, writer CPU, query load, cleanup/rollups and operations; existing DB does not make this free |
| Dependence | Azure schema/identity/query semantics and collector behavior | Flare schema/metric ownership, query and retention maintenance |
| What Flare still owns | Touch precedence, visitor/account bridge, authoritative event definitions, bot exclusions, consent eligibility and metric policy | Same product policy, plus bounded data persistence and report contracts |

### Decision gate

Choose A only after Vova can demonstrate an end-to-end joined synthetic journey,
reviewed data collection, suitable retention/cost, query access and an explicit
policy for event loss. If only infrastructure/request logs are enabled, extending
them with acquisition and domain events is significant application work, not an
existing funnel capability. Logs alone cannot reliably reconstruct the funnel.

Choose B if reliable business joins and Flare-owned attribution are the priority,
or the Azure evidence gate fails. Prefer separate acquisition persistence rather
than weakening workspace RLS or allowing arbitrary events into `activity_events`.
Reuse the latter for authenticated UI/action signals; do not build a duplicate
general-purpose clickstream. Optional later aggregate export to an existing Azure
workspace is a hybrid reporting choice, with one canonical metric definition and
deduplicated delivery. It must not create two competing sources of conversion truth.

A dedicated third-party analytics vendor could supply packaged funnel tooling,
but it would still need the same trust/identity/privacy work and add another
processor, SDK and cost surface. It is a comparison only; none is selected,
installed, configured or introduced by this task.

## 5. Attribution and identity design options

### Touch semantics — owner decision required

| Option | Benefit | Tradeoff |
| --- | --- | --- |
| First touch | Explains initial measured discovery; stable acquisition cohort | Later campaign that helped registration receives no credit |
| Last touch before signup | Explains the final measured acquisition interaction | Overwrites early discovery; direct-return overwrite policy becomes consequential |
| Both | Separates discovery from conversion assistance | More state, clear reporting basis needed; not multi-touch revenue attribution |

Recommend storing **first observed touch and last eligible non-direct touch before
registration**, plus signup landing context, if the owner approves. Freeze these
at registration. A later login or product session must not rewrite acquisition.
Alternatively first-only is smaller if the immediate question is initial channel
quality. Lookback window, direct handling and cookie lifetime remain decisions;
do not choose a production duration merely to match a reporting example.

Proposed classification, versioned and deterministic:

1. Valid allowlisted UTM fields take channel precedence; collect `utm_source`,
   `utm_medium`, `utm_campaign`. `utm_content` is optional if a real comparison
   needs it; exclude `utm_term` and ad click IDs initially unless approved.
2. Resolve `ref`/referral only against issued campaign/referral codes. Store an
   opaque campaign/code identifier, not a referrer's email or user ID. A referral
   claim is an attribution hint, not proof of incentive eligibility. Keep a
   distinct referral dimension when UTM and ref coexist; avoid silently combining
   their meanings. Reward/fraud logic is outside this scope.
3. Without valid UTM/ref, use an external HTTP(S) referrer domain. Internal origins
   and self-referrals do not introduce a new acquisition channel.
4. Missing/withheld referrer becomes `direct_or_unknown`, not a confident claim of
   intentional direct traffic. Invalid fields get a reason enum and discarded
   value; never preserve a malicious input for later inspection.

The browser referrer policy can reduce cross-origin referrer detail and omit
referrers in some cases; do not infer missing campaign or full upstream paths.
[Referrer Policy specification](https://www.w3.org/TR/referrer-policy/).

Normalize query fields once, handle duplicate keys deterministically (prefer
rejecting conflicting duplicates), apply Unicode/byte/character bounds and an
approved campaign vocabulary, and discard all other query data. Store only
canonical route labels/allowlisted landing paths, never full URL queries/fragments,
verification tokens, arbitrary document routes or input content. Strip referrer
path/query/userinfo; canonicalize domain and reject non-HTTP(S). Bounded strings
still can contain personal information, so campaign governance and an `other`
bucket are needed in addition to length validation.

### Pre-auth identity and cross-session boundaries

* With approved optional measurement, issue an independent random first-party
  visitor reference on the canonical public origin. It is not an auth credential,
  user email hash, workspace ID or fingerprint. Keep server-side normalized
  attribution state; a signed/random opaque reference prevents editing fields
  after issuance but does **not** prove UTM truth or prevent bot cookie churn.
* Keep a separate bounded session reference/window for measured return navigation
  if needed. First touch persists across eligible sessions only within the
  approved lookback/lifetime. No storage/permission means session-only measurement
  or unknown attribution, not silent fingerprinting or retrospective guessing.
* At successful account creation, the server reads/validates the reference and
  records visitor/touch → new user → initial workspace linkage. Account creation
  still succeeds when optional analytics fails. A transactionally saved minimal
  signup snapshot, or recoverable link/outbox in the account transaction, is the
  design option for stronger join completeness; reject arbitrary client user IDs.
* A registration bridge must be persisted before navigation clears client state.
  Verification on another device joins via the server's verification/account
  identity, not via the new browser's campaign cookie. Login links authenticated
  actions across devices from then on, without merging every prior anonymous
  history of that device.
* Shared browser: do not globally attach a visitor's entire past/future activity
  to the latest logged-in person. Use timestamped, specific registration links;
  clear/rotate user context on logout/account switch. Specify whether a visitor
  may lead to multiple accounts; report browser visitors and accounts separately.
* Web, desktop and email entry can have different browser/session contexts. Do not
  promise cross-device pre-auth attribution. If a future web-to-desktop transfer
  is wanted, require a narrowly scoped, expiring handoff reference and separate
  review. Current registration is already linked to its initial workspace; future
  membership/invite attribution must not give every workspace member the
  creator's channel without stating that reporting definition.

### What Flare would persist under B (conceptual, no migrations)

| Record | Minimum role and bounded fields | Lifecycle/isolation |
| --- | --- | --- |
| Visitor/touch state | Opaque reference, first/last eligible touch time, normalized source/medium/campaign/referral, referrer domain, landing route, measurement eligibility and policy version | No auth/content data; short approved expiry; updates limited to allowlisted touch transitions |
| Signup attribution | Server-linked user ID and initial workspace ID, frozen touch snapshots/references, registration time, basis/version, missing-data reason | Account-authorized writer; unique registration fact; retention/deletion tied to account policy |
| Authenticated outcome facts | Existing actor/workspace events plus stable logical outcome ID, canonical terminal timestamp/status and server provenance when needed | Preserve tenant boundaries; dedupe logical outcome; no document bodies, provider responses or error strings |
| Daily actor activity / rollup | User/workspace/date, approved voluntary-action class, cohort basis/version; terminal milestones or anonymous aggregate counts as needed | Only if reporting survives shorter raw/job retention; recomputable with defined late-data/deletion corrections |

This is a few bounded record types, not an unlimited event warehouse. Choose
between acquisition-only snapshots (smaller, insufficient visitor denominator)
and snapshots plus minimal eligible landing/session facts (answers measured
visitor conversion). State that distinction in the approved requirements.

`activity_events` should retain its required workspace and server-derived actor.
Anonymous touches belong separately. Adding acquisition metadata to every event
would duplicate sensitive data and invite high-cardinality queries. Reference the
frozen attribution record in reporting instead. Cross-workspace operator reports
need a specifically reviewed restricted aggregate view/job/export role, not a
public endpoint, application RLS bypass, or routine use of migration credentials.

## 6. Event, activation, and shared-interface contract

Proposed names below are report concepts; they are not added to the existing
allowlist or an agreed implementation contract.

| Milestone | Trust/identity and dedupe | Current mapping / new fact needed |
| --- | --- | --- |
| Eligible landing | Server-issued visitor/session reference; one canonical qualifying landing per session | New acquisition fact if visitor conversion is wanted; browser observation remains untrusted |
| Account created | Server account commit; unique user and initial workspace | `auth_users.created_at`; link attribution, include durable-account-but-mail-failed case |
| Email link confirmed | Successful token consumption; unique user; no raw token | Actual confirmation provenance required; exclude bypass/legacy from verified-email conversion |
| Content captured | Committed document; distinct document ID/actor/workspace | `item_created` plus source record reconciliation; exclude imported items when counting capture |
| Import published | Terminal publication; distinct batch/job ID; retry does not add conversion | Existing batch + `import_completed`; future async terminal event contract to DATA |
| Analyze requested | Accepted logical run; mode and requester retained | Existing `analysis_requested`, distinct run ID; not success or a human return when scheduled |
| Analyze completed | Terminal analysis AND Flare-generation result; distinct run ID | Reconcile existing run/job/generation state or future idempotent terminal fact; to ARCH |
| Value inspected | Foreground Flare detail or relevant evidence inspection | `flare_viewed`/`item_viewed` are bounded client signals; report collection loss |
| Human active day | Distinct user/workspace/day with approved voluntary product action | Existing interactions partly help; not auth keepalive, readiness, queue ops or scheduled runs |

**Shared review requests, published with this report's handoff:**

* DATA-001 owns what constitutes ZIP import publication. Please review an
  observational terminal envelope: stable import ID, authenticated requester and
  workspace, committed publication timestamp, terminal status (including partial,
  failed/cancelled if supported), bounded supported-file/document counts, replay
  indication and fixed failure code. GROWTH counts distinct published imports,
  not upload acceptance, extraction completion, enrichment completion or per-file
  progress. Existing synchronous retries emit duplicate completed events, so a
  future terminal fact needs dedupe. No package paths/text or new AI call follows.
* ARCH-001 owns enrichment/retrieval and Analyze behavior. Please review a
  terminal-observation envelope: stable logical run ID, workspace/requester, mode
  manual/scheduled, server terminal time/status and bounded result count. A
  preparation refresh and an AI preprocessing job are not an Analyze conversion.
  Enrichment calls must not count as user return or alter the daily Analyze rule.
* Owners should resolve differences in a separately claimed implementation task.
  This report has not edited their reports or asserted they accepted these
  fields. No dependency on their research completion is introduced.

### Activation and retention options

Owner must choose the metric before implementation. Candidate activation levels:

1. **Content activation:** first committed capture or published import. Fast,
   measures onboarding, does not establish a useful Flare.
2. **Analysis activation:** content plus a successfully completed manual Analyze.
   Stronger processing signal, excludes merely opening/clicking Analyze; daily
   quota means multiple same-day requests are not expected deeper use.
3. **Value-engagement activation:** completed Analyze plus voluntary value/evidence
   inspection within an approved window. Stronger behavioral proxy but depends
   on browser collection and does not prove the insight was useful.

Recommend reporting these as separate milestones initially; pick one headline
activation definition only after owner review. Scheduled completion can be a
workspace service-outcome metric, not evidence that a person returned. Measure
Flare usefulness by a separately approved feedback/outcome definition if needed;
do not rename a view “useful user.”

Proposed reporting specification:

* Acquisition cohort = accounts created in a fixed UTC week, with frozen first
  touch or last-touch basis displayed explicitly. Also allow workspace-creator
  cohorts, labeled separately. Counts use distinct actors/workspaces, not rows.
* Signup conversion = unique successfully created accounts linked to eligible
  measured landing visitors / eligible distinct measured landing visitors in a
  stated attribution window. Browser visitors are not people. Report attribution
  coverage and ineligible/unlinked counts beside it; do not claim all-traffic rate.
* Activation rate = cohort accounts satisfying the chosen **ordered** milestone
  within the chosen window / eligible cohort accounts with that window elapsed.
  Show excluded accounts, failures and unknown tracking separately.
* Candidate D7 retention = voluntary qualifying activity in the UTC half-open
  interval `[signup + 7 days, signup + 8 days)` / cohort accounts with the full
  interval observed. Candidate W1 retention instead uses `[signup + 7 days,
  signup + 14 days)`. These are different definitions; owner chooses. D30 also
  requires a completed observation window. Immature cohorts show “pending,”
  not zero. Registration-based and activation-based cohorts must not be mixed.
* Store timestamps in UTC. Acquisition report UTC boundaries are a recommendation,
  distinct from the product's workspace-local Analyze quota. If local-day
  reporting is chosen, freeze cohort timezone and version DST/boundary semantics.
* Return visit/navigation and meaningful product retention are separate metrics.
  Exclude scheduled jobs, telemetry delivery retries, API polling, queue
  maintenance, availability probes, research probes, staff/test accounts and
  known bots from human retention. Publish bot/unknown exclusions without claiming
  perfect bot detection or causal channel lift.
* Compare channels by absolute cohort size, coverage, signup, activation and mature
  retention, not just visits. A high-conversion small cohort is not established
  channel performance. Observational attribution is not causal incrementality.

## 7. Anonymous abuse, minimization, and retention

### Bounded anonymous intake

Prefer capture at a qualifying first-party landing/touch over a generic public
event API. If a collector is needed, allow only fixed landing/session events;
no anonymous “registration,” “import completed,” “Analyze completed,” arbitrary
user/workspace IDs, document targets or free-form metadata. Identity and committed
business facts are supplied by authenticated/server paths.

Require payload byte/field limits before expensive work, canonical route and
campaign limits, expiring server-issued references, same-origin/CSRF checks where
appropriate, trusted-proxy handling, per-reference and short-lived network-level
budgets, aggregate/global write/storage caps, concurrency limits and timeouts.
Origin headers and opaque IDs are useful controls, not proof of a real person.
Cookie churn bypasses per-visitor limits, so it cannot be the only cost bound.
Do not assume Front Door/WAF is available as the abuse boundary.

Reject oversized/invalid inputs, suppress retry amplification, deduplicate bounded
landing facts, and return without blocking navigation/account creation when
optional tracking is unavailable. No indefinite offline browser queue. Limit
request/log volume on dropped events and expose aggregate accepted/dropped/error
counts. Rate-limit counters may use short-lived pseudonymous network keys with
restricted access; do not retain raw IP history as acquisition identity. Final
limits are configurable and require load evidence, not arbitrary production
numbers borrowed from the authenticated 600/hour limit.

### Minimize before any sink

Keep emails, names, passwords, session cookies/hashes, verification tokens, Note
text, document titles/paths, uploaded filenames, audio, ZIP paths, provider input/
output and arbitrary URLs/query strings out of analytics. A pseudonymous analytics
identifier is still linkable data; restrict linkage access. If Azure SDKs are
chosen later, inspect automatic HTTP/exception/dependency collection and strip
private query/path/body data before transmission. Do not send model prompts or
content to a new telemetry sink.

Use only campaign fields needed for a question, a referrer domain, canonical
landing route, stable logical IDs, times, bounded counts/status enums and policy
version. Apply the same policy to exports, dashboards and error logs. Registration
acceptance of product Terms/Privacy is not automatically approval for optional
analytics storage; the product/privacy owner must decide collection eligibility,
notice, opt-out/deletion behavior and applicable consent requirements. No legal
compliance conclusion is asserted here.

### Retention choices requiring approval

* Anonymous touch lifetime must match the chosen lookback; unlinked visitors expire
  promptly. A cookie expiry alone does not delete corresponding server rows.
* Retain signup attribution only for a declared reporting purpose/window. Keep raw
  event retention separate from the attribution/cohort horizon; a long cohort
  report cannot depend on deleted jobs/raw events without retained facts/rollups.
* Existing activity maintenance defaults to 90 days but is dry-run/operator driven.
  Define owner, schedule, bounded batches, retry/catch-up and monitoring before
  treating any retention as enforced.
* Aggregate rollups may outlive raw records only under an approved policy with
  small-cohort disclosure controls. Define corrections for late facts, deleted
  users, account resets and restored backups; “aggregate” does not by itself make
  small linked cohorts anonymous.
* Account deletion/withdrawal must remove eligible visitor links and attribution,
  and propagate to event/fact stores and exports as required by the selected
  policy. `activity_events.actor_id` is text without an auth-user foreign key,
  so auth-user deletion alone is not a demonstrated event-deletion mechanism.
  Workspace deletion cascades that workspace's events [R5].
* If Azure becomes a sink, confirm table-level retention, purge/export copies and
  deletion procedure. Table plans have different query/retention behavior; their
  documented defaults are not evidence of Flare settings.
  [Log Analytics retention](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-retention-configure).

## 8. Queries, exports, dashboards, and operating cost

### Small reporting surface first

Current GET `/analytics/events` returns per-workspace event totals and a bounded
time window. It cannot produce the proposed global acquisition join. Start with
a versioned restricted query/report contract, not a new customer-facing dashboard:

1. Deduplicate logical server outcomes by user/workspace and document/batch/run ID.
   Reconcile dropped events with domain facts before aggregation.
2. Join frozen signup attribution to account timestamps and approved activation;
   attach verification provenance rather than just a non-null flag.
3. Build daily voluntary actor activity and apply ordered, matured cohort windows.
   Choose one channel basis per view. Display dataset freshness, coverage and
   exclusions, with unknown dimensions retained explicitly.
4. Export aggregate channel/week metrics or a tightly controlled synthetic/example
   dataset. A routine export should not include emails, account lists, content or
   session identities. Protect exported spreadsheet fields against formula
   interpretation and keep retention/access controls on copies.

For B, a future approved read-only aggregate reporting role/query job can use SQL,
bounded time windows, statement timeouts and suitable indexes. Avoid analytics
full scans on the interactive API database; measure headroom before recurring
reports. A read replica or warehouse is an option only if volume evidence
justifies its cost, not a prerequisite selected here.

For A, use saved KQL queries and an existing permitted workbook/dashboard after
mapping actual tables. Query time bounds and response-completeness checks belong
in any exporter. Continuous Log Analytics export, if approved, creates additional
destination data/cost and is not a magical historical backfill; deduplicate and
monitor export completeness. [Log Analytics export](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/logs-data-export).

A full internal analytics UI is currently overkill: definitions, live evidence,
data completeness and owners are unresolved. Reconsider once recurring report
users need drill-down/access control/self-service enough to justify a separate
maintained UI. No UI design/build is included in this research.

### Cost model: estimates only, no measured traffic or spend

Azure Monitor has volume/plan-dependent ingestion and retention pricing plus
optional export/alert charges. Select region, billing tier and current account
usage before quoting a dollar estimate; published free allowances cannot be
assumed available to Flare. [Azure Monitor pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/).

Use these planning equations, then replace assumptions with a sanitized pilot:

* `events/day = eligible measured landings + touch updates + terminal outcomes + bounded voluntary interactions`.
  Do not multiply ZIP file count or provider preprocessing attempts into growth events.
* `Azure ingested GB/month = 30 × events/day × measured billable bytes/event / 1e9`.
  Add actual extra request/dependency telemetry separately. Apply the region/tier
  ingestion rate, longer retention, alerts, export GB and destination costs.
  Budget caps can cause reporting gaps and must be surfaced.
* `DB retained rows ≈ events/day × raw retention days + active touch/link/fact rows`.
  Measure table/index bytes, write CPU/latency, WAL/backup overhead, bounded cleanup
  throughput and query runtime on a disposable representative dataset.
* `total operating burden = implementation + metric/query maintenance + ingestion/abuse monitoring + retention/deletion + report/export ownership`.
  B may avoid another telemetry service but adds DB and reporting duties. A may
  reuse an existing workspace, if verified, but still adds instrumentation and
  identity/completeness work.

Illustrative sizing only: 10,000 events/day at **assumed** 1,000 billable bytes
per Azure event is 0.30 decimal GB per 30-day month; 90 days of the same event
volume means 900,000 raw rows before indexes/other records. Neither event size,
volume, DB row size, telemetry sampling nor cost was measured for Flare. These
figures are arithmetic examples, not expected capacity or a production budget.

## 9. Remaining decisions

| Owner | Decision needed before implementation | Research position |
| --- | --- | --- |
| Vova | Actual resources, deployed SHA, enabled telemetry/diagnostic routes, retained tables/sampling/caps/query access | Unresolved; evidence list in section 2 |
| Vova | Verification flag and SMTP launch readiness; provenance of existing verified accounts | Checklist claims bypass currently; no live verification |
| Product owner + Vova | A versus B versus aggregate-export hybrid; acceptable reliability and spend | Recommend bounded B unless A evidence gate succeeds |
| Product owner | First/last/both, direct handling, lookback, referral precedence and campaign vocabulary | Recommend first + last eligible non-direct, subject to approval |
| Product/privacy owner | Anonymous identity eligibility/storage, notice, opt-out/deletion, raw/link/aggregate retention | Minimize fields; durations and policy unresolved |
| Product owner | Headline activation, useful-user definition, voluntary activity, D7/W1/D30 and UTC/local reporting | Show separate milestones; exclude automated runs from human return |
| Product owner | Account versus workspace-creator cohorts, future invites/desktop linkage and shared-device handling | Keep units explicit; no inferred cross-device pre-auth identity |
| DATA / ARCH owners | Observational terminal envelopes and retry/partial/zero-result semantics | Section 6 proposals; no claimed acceptance |
| Vova + future implementation owner | Restricted global reporting access, cleanup/export owner, DB load budgets, pipeline completeness | No RLS weakening or migration-credential report routine |
| Product owner | Need for recurring exports versus internal UI | Queries/aggregate export first; UI deferred |

Unknown deployment facts do not prevent completing this research: the task
explicitly permits unresolved facts with evidence needed from Vova. Product
semantics are presented as alternatives/proposals, not silently selected.

## 10. Validation and acceptance evidence

Completed evidence:

* Fresh origin fetch and single-snapshot context/claim workflow; confirmed task-sync
  state pushes succeeded. Published branch/scope and repeated active-scope checks.
* Read-only source inventory for actual telemetry, auth/verification, product-event
  producers, domain outcome status and maintenance. Exact file hashes/anchors in
  `repository-evidence.json`; no `.env`, credential access, cloud mutation or
  production event/account creation.
* Nine public endpoint reads in `public-probes.json`; eleven landing-script checks
  and safe response headers in `public-assets.json`. All are timestamped. Marker
  absence is bounded evidence only, not a claim no production collector exists.
* Context7 Azure Monitor resolve + two documentation queries, followed by primary
  Microsoft/W3C documentation. Context7 did not index the pinned task-sync tool;
  its exact upstream README/integration/command reference were read instead.
  No library advice relies on an unrelated Context7 match.
* `validate_research.py` checks scope, pinned source hashes/line anchors, artifacts,
  public-probe assertions and synthetic ordered/cohort/dedupe examples. Its JSON
  result is in `validation.json`. Synthetic examples are not product metrics or
  an implementation test of production ingestion.
* `git diff --check` and changed-path review. Documentation-only changes do not
  require runtime application builds, migrations or production smoke writes.

Required future validation after an implementation is separately authorized:

1. A controlled synthetic channel journey on a disposable/staging environment:
   landing → signup → explicit link verification → capture/import → terminal
   manual Analyze → voluntary later activity, with each join independently checked.
2. Bypass/legacy verification and SMTP failure-after-account-commit cases; duplicate
   signup/import/run/event delivery, partial/cancelled imports, zero-result Analyze
   and scheduled runs; no inflated activation or return counts.
3. Campaign precedence/duplicate/encoding cases, referrer suppression and self-referrals,
   cookie deletion/no-storage/opt-out, verification on another device, shared-browser
   switching and canonical redirect; no email/token/query leakage.
4. Anonymous load/abuse with cookie churn, invalid origins, forged actors/workspaces,
   oversized metadata, high campaign cardinality, retries and collector outage;
   demonstrate bounded writes, acceptable app latency and retained unknown counts.
5. Tenant isolation/reporting-role denial, missing target and provenance checks;
   cleanup/backfill/late events/deletion/export and backup-restore behavior.
6. Reconcile event versus authoritative counts, sampling/cap/export loss, cohort
   maturity and time boundaries. Measure storage/write/query/cleanup cost before
   approving limits and any recurring query schedule.

Review should accept the evidence distinctions and comparison, then record product
and Vova decisions for a separately assigned implementation task. This research
does not authorize product changes, new services, deployment, or marking done.

## Repository evidence references

All links are pinned to source SHA `7d734d4deabb90eb0d22a6e2840bf8755f44c13b`.

* [R1 — release topology and verification gate](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/docs/RELEASE_CHECKLIST.md#L8-L27).
* [R2 — Azure packaging](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/.github/workflows/azure-appservice-release.yml#L1-L24) and [public endpoint smoke](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/.github/workflows/production-smoke.yml#L15-L41).
* [R3 — safe request logs](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/main.py#L107-L138) and [API startup](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/deploy/bootstrap_flare_api.sh#L22-L24).
* R4 — scoped telemetry/attribution inventory: method, checked paths and dependency-file hashes in `repository-evidence.json`; negative search is not live absence proof.
* [R5 — activity schema/RLS](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/migrations/versions/0012_activity_events_and_source_types.py#L36-L88), [endpoint](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/api/analytics.py#L24-L67) and [summary query](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/models/events.py#L31-L45).
* [R6 — allowlisted metadata/targets/budget and best-effort handling](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/services/analytics_service.py#L37-L327).
* [R7 — committed item event](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/api/routes.py#L129-L147).
* [R8 — import event/replay behavior](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/api/imports.py#L66-L113).
* [R9 — client delivery](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/frontend/src/lib/data/api-provider.ts#L584-L597), [capture interactions](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/frontend/src/features/capture/capture.tsx#L170-L194) and [view suppression](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/frontend/src/features/insights/view-analytics.ts).
* [R10 — register schema/handler](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/api/auth.py#L27-L59) and [atomic signup/bypass verification](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/services/auth_service.py#L83-L133).
* [R11 — auth timestamps/session history limit](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/migrations/versions/0004_auth.py#L24-L45), [workspace provisioning](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/models/auth.py#L23-L43) and [session touch](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/models/auth.py#L98-L102).
* [R12 — verification migration](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/migrations/versions/0008_email_verification.py) and [token consumption/bypass](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/models/auth.py#L134-L158).
* [R13 — terminal run contract](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/migrations/versions/0007_analysis_runs.py#L131-L148) and [daily/mode events](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/migrations/versions/0015_daily_analysis_schedule.py).
* [R14 — maintenance defaults](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/app/api/schemas.py#L250-L273) and [bounded owner maintenance](https://github.com/VladimirMalevanik/flare/blob/7d734d4deabb90eb0d22a6e2840bf8755f44c13b/backend/migrations/versions/0015_daily_analysis_schedule.py#L806-L850).
