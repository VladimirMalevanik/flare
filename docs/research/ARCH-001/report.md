# ARCH-001 — Project Memory retrieval, enrichment and Groq budgets

Research/design handoff, 2026-10-02. Implementation and product acceptance are pending.

## 1. Result and authority

Recommend **layered document/section characteristics with lexical retrieval first**, an independent, bounded enrichment queue, and explicit counterevidence selection before loading original chunks into the existing Analyze pipeline. Add embeddings only if a held-out evaluation shows a useful improvement. This is a recommendation for the product owner, not an approved implementation choice.

The selected direction is preserved: `original documents/chunks → bounded AI characteristics → retrieval/ranking → original evidence → bounded extraction/Flare generation`. Characteristics help locate evidence; they cannot establish a goal, completion, contradiction or final citation. Missing selected completion evidence means **unknown**, never proof of unfinished work.

The launch contract remains **one manual OR scheduled Analyze per workspace local calendar day**, including the existing 20-hour guard, shared reservation, T-30 source snapshot, idempotent replay and retention-safe quota tombstone. Preprocessing needs a separately approved allowance. Import/save/edit never implicitly starts normal Analyze or consumes its slot.

| Handoff field | Value |
| --- | --- |
| Task/owner | ARCH-001 / Fedor / Codex |
| Initial fresh main | `80dc00d7b471621908c5f4d1e215da5032429073` |
| Pre-claim context | `e90279640a4c410b172dbc92739c109fd5d6b40d` |
| Claim/base/source SHA | `71e26d9cfbfec836770d4e43d4a79fe53bf32686` |
| Published branch | `research/arch-001-project-memory-20261002` |
| Declared write scope | `docs/research/ARCH-001/` |
| Scope declaration commit on main | `1dc923c0ea80a43cab908f81c6eb644ae017a392` |
| Pre-edit context | `6c62eaa9e05b103ecee1b20e42f68d34cc0d7d00` |
| Required result | This report and supporting offline research artifacts; hand off to review, never done |

Repository findings below use the single claim/base/source SHA. Later main advances observed before writing were coordination-only for the inspected product paths. The branch starts from fresh main after the successful claim. Root AGENTS.md, AGENT_SETUP.md, BOARD.md, NOW.md and ARCH role were read. Task-sync-git 0.1.0 was installed outside the checkout from pinned upstream tag v0.1.0 (resolved upstream SHA `4d936d3c76e71f28aaa03b8d196a2a812e6b0f40`). The existing dirty checkout was untouched.

The authoritative source tree is [Flare at the research base](https://github.com/VladimirMalevanik/flare/tree/71e26d9cfbfec836770d4e43d4a79fe53bf32686). The symbol references in section 2 and source digests make repository claims reproducible independently of later main changes.

### Evidence classes

- **Repository evidence:** code/schema at the source SHA; citations below are exact repository-relative paths and symbols. The artifact [research-results.json](research-results.json) records source-file SHA-256 digests.
- **Provider/documentation evidence:** public primary sources checked 2026-10-02 and linked beside claims. These show advertised capabilities, prices and limits, not the Flare account's settings or production behavior.
- **Offline checks:** deterministic synthetic slice/lineage/admission checks and arithmetic in [research_checks.py](research_checks.py). They do not run the application or a database.
- **Estimates/design:** cost sensitivity, candidate limits and queue policies are proposed, explicitly unmeasured. No provider calls, credentials, private corpus, deployed runtime, account limit inspection or production quality measurement occurred.

## 2. Current repository behavior

| Source at the recorded SHA | Observed behavior and implication |
| --- | --- |
| `backend/app/models/analysis_runs.py`, `AnalysisRuns.start` | Eligible current ready versions of active note/file/url/audio sources; at most 200 candidate documents, each contributing bounded chunks, then at most `min(max_sources*4,400)` candidates. Default `max_sources=5` means 20 final candidates before selection. History prioritizes never-selected/least-recently selected sections and interleaves documents. This is coverage rotation, not relevance retrieval across the whole corpus. |
| `backend/app/services/context_selection.py`, `select_context`, `SIGNALS` | Preserves rotation order with one actionable-section promotion; English/Russian keyword cues. Calls the real bounded request builder to fit whole chunks. No embedding, provider call or inferred project state. An old, previously selected goal can lose to unseen routine material. |
| `backend/migrations/versions/0018_rotate_analysis_context.py` | Compact last-selection history and scheduled candidate ordering. Any future selector must keep manual and scheduled selection consistent, with an explicit revision, not modify only one path. |
| `backend/app/config.py`, `AISettings`; `ai_engine/flare_config.py`, `FlareSettings` | Defaults: extraction request 32,000 UTF-8 bytes, five sources, 2,000 completion tokens; Flare request 32,000 bytes, 1,024 completion tokens. These byte limits include envelopes and are not token accounting. Current adapter validates only GPT-OSS 20B/low; 120B requires separate future implementation/approval. |
| `backend/app/services/item_service.py`, `create_item`, `_resolve_update` | Note creation inserts one chunk for the whole content. Note content edits generally replace it with one chunk; title-only changes can copy chunks into a new immutable version with new IDs. Long Notes can be readable but too large for Analyze. |
| `backend/app/services/import_service.py`, `prepare_content` | Current synchronous JSON text import: CSV/TXT/MD, 200,000-byte input, 4,000-byte chunk target, 20,000 rows and 2,000 chunk safety limits. Chunk concatenation must reproduce parsed text exactly; BOM removal is explicit. CSV rows and Markdown headings carry locators. Successful import records `analysis_jobs_queued=0`. These are existing single-file limits, not proposed ZIP limits. |
| `backend/app/models/tables.py`, `ItemRepository.list_active` | Current search is escaped substring `ILIKE` on snapshot title or current chunks, ordered by update time. No ranked full-text retrieval service. |
| `backend/db/schema.sql` | Nullable `chunks.embedding vector(1536)` and model label provide future capacity, not an embedding service. Do not assume a new model's dimension fits this column. |
| `backend/app/ai_engine/enrichment_prompts.py`, `build_enrichment_request`; `prompts/enrichment.md` | Single-item title/tags/200-character summary/related query/language scaffold; no length enforcement in the builder, typed durable result, queue, lineage, budget or production caller found. `backend/tests/test_enrichment.py` is a manual live smoke script, not provider-quality evidence from this task. |
| `backend/app/ai_engine/analysis.py`; `ai_engine/flares.py`, `validate_candidates`; `prompts/flare_generation.md` | Final citations require supplied source IDs and matching original quotes, with conservative semantic guards. Prompt explicitly rejects inferring unfinished tasks from missing completion. Quote membership alone does not prove entailment; preserve this distinction. |
| `backend/app/models/flares.py`, `SELECT_FLARES` | Historical evidence uses the cited version's snapshot title/source URL, rather than current-version text. Deleted-source results are filtered. Retrieval of current memory must not rewrite old citations. |
| `docs/ANALYZE_QUOTA_DECISION.md`; `models/analysis_runs.py`; `services/analysis_schedule.py` | Database daily slot, IANA timezone (UTC without schedule), 20-hour separation, T-30 immutable chunk pinning and tombstones. Failure does not reopen the day. |
| `ai_engine/groq_adapter.py`; `groq_structured.py`; `services/analysis_jobs.py` | SDK retries disabled, durable lease/retry handling, but strict-schema helper can make a second call on `json_validate_failed` inside one worker attempt. A provider budget must count actual calls, not just job attempts. Some older docs saying “no analyzer retry” miss this helper behavior. |

No live deployment claim is inferred from these files. In particular, docs/AI_MODELS.md contains older implementation/deployment descriptions; the current source and daily-quota decision govern this analysis.

## 3. Architecture and granularity options

| Option | Representation and retrieval | Benefits | Costs/risks and decision |
| --- | --- | --- | --- |
| A — document characteristics + lexical originals | One summary for each short document; long documents sampled with declared coverage; ranked metadata/original search, rotation fallback | Small queue and index; inexpensive initial path | Sampling can miss a remote goal/completion pair. A single summary cannot truthfully represent an entire long document unless every section is covered. Accept only as a staged baseline with visible coverage. |
| B — layered sections + document rollup, lexical first | Bounded section cards with exact evidence references; document card aggregates section IDs; independent goal/decision/completion facets; original-text lexical lane | Fits long Notes/imports; incremental rebuild; traces omissions; no extra inference at retrieval time | More jobs and derived storage. Recommended starting target, evaluated against A/current rotation. Document/project rollups remain optional and budgeted. |
| C — B plus semantic hybrid | Lexical lane + embeddings of section cards/original slices, merge ranks, retain counterevidence/coverage lanes | Paraphrase and cross-language discovery where vocabulary differs | Embedding compute/service, data policy, model/dimension revisions, index maintenance and query cost. Add only for measured gaps; no embedding provider is approved here. |
| D — hierarchical project summaries/graph retrieval | Entity/event links and recurring project/topic rollups, followed by original evidence loading | Potential global theme discovery | Highest rebuild/omission/summary-drift burden. Not justified without a global-question evaluation and funded budget. Never maintain one mutable “project truth.” |

Per-section cards are the durable retrieval unit. Short Notes can have one section; large Markdown uses heading-aware subdivisions; long CSV/text uses parser locators and bounded windows. A per-document card is an index over section cards, not a replacement for them. A project rollup references the exact child revisions and is marked partial when coverage is partial. Do not repeatedly summarize summaries without reachable original support.

The [GraphRAG research paper](https://arxiv.org/abs/2404.16130) studies graph/community summaries for global questions over a corpus. That motivates D as a comparison, not evidence that Flare needs a graph or that its cost/quality will improve here.

### Compact representation contract (proposed)

Server-owned identity fields: workspace, document, immutable version, section key, original chunk IDs and ranges; input hash; parser/slicer revision; prompt/schema/profile/model revision; derived revision; creation time; coverage counts/ranges and status. The model cannot invent these identities or choose authorization.

Model-produced fields: source-language title, neutral description, concrete entities/topics/aliases, stated dates/deadlines (with precision/ambiguity), goals, decisions/constraints, commitments, blockers and completion/cancellation/supersession **claims**. Each claim carries an allowed source reference and exact quote/offset. Store `unknown` when the content does not establish a state. Keep conflicting claims separately with their dates and original support; never collapse them into a single inferred “current status.”

Use a strict bounded schema and application validation: field lengths, list counts, source membership, offsets, exact quote match, content hash and language. Title/tag/summary limits in the existing scaffold may seed the index, but its no-verbatim-summary rule does not substitute for a separate exact-evidence field. Empty/unusable cards should fail safely or publish metadata-only coverage, not fabricated characteristics. Treat source text and cards as untrusted data; no tools, browsing or external URLs followed during enrichment.

## 4. Long Notes, lineage and derived-memory lifecycle

Normalize for **search** separately from **evidence**. Preserve the stored source text and parser-defined authoritative text. Search may casefold, tokenize or normalize Unicode; generated quotations must resolve to original code points. Do not strip punctuation or normalize a Note body merely to improve retrieval. Record any ingestion transformation and raw/parsed hashes through DATA's provenance contract.

Two long-Note choices require a product/data contract decision:

1. **Derived slices over an existing immutable chunk** (recommended compatibility path). Section ID maps to original chunk ID plus character/byte ranges, preserving every character; use heading/paragraph boundaries with deterministic hard splits for oversized paragraphs. Retrieval returns an original chunk locator and slice, never a new fictional chunk UUID.
2. **Publish a new source version containing proper chunks** for new/edited Notes, with an explicit parser revision. Existing ready chunks are never mutated. Backfilling published Notes must be a separate scoped migration/implementation decision; historical Flare citations stay pinned to the old version.

The current Analyze input is whole `Evidence(source_id,content)`, so merely slicing for enrichment does **not** fix oversized originals. Before implementing option 1, define an adapter change: load an exact slice, keep the original chunk UUID as `source_id`, merge adjacent selected ranges, and ensure one evidence entry per chunk. Persist original offsets in the selection manifest; final quotes must match both supplied slices and the complete original chunk. If a goal/completion pair inside one giant chunk cannot fit after range merging, defer rather than truncate silently. Option 2 avoids this adapter extension at the cost of source-version work. Both are design-only here.

Nonadjacent ranges must retain explicit boundaries, and a quote cannot cross a synthetic join. The current Flare candidate contract allows one quote per chunk; distant claims within one legacy giant chunk may therefore need properly chunked new versions or a separately reviewed evidence-contract extension. This report does not assume that changing only the retriever solves that limit.

Lifecycle: `metadata_only → pending → processing → ready`; side states `deferred_budget`, `deferred_provider`, `failed`, `stale`, `superseded`, `cancelled`. Import publication/readability is independent. A job dedupe key includes workspace, immutable version, section/input hash and all relevant revisions. Bounded transactional publication marks a card current only if the source is still current, ready, active and authorized; otherwise discard or retain as historical cache, excluded from current retrieval.

- Edit: mark old current cards stale immediately, enqueue/coalesce only the latest desired revision after an edit debounce. Unchanged text may reuse a validated payload within the same workspace, but rebind/revalidate new chunk IDs, title/path metadata and lineage. Hash equality never permits another tenant's data access.
- Prompt/model/parser changes: create a new revision, rebuild lazily under budget, never modify historical derived records in place. Project/document rollups invalidate when any child is deleted/replaced or coverage changes.
- Delete: cancel queued jobs, exclude cards/search entries synchronously, prevent in-flight finalize, and apply the same hiding policy to dependent Flare reads. Purge derived sensitive text according to an approved retention policy; minimal cost/idempotency records may outlive content.
- Historical citations: point to exact original version/chunks/snapshot metadata; an edit does not redirect a citation to current content. Deletion must keep existing visibility restrictions. A new summary cannot “repair” an old citation by swapping sources.

Design-only persistence: derived cards and card-source edges with composite workspace FKs/RLS; jobs/leases/dedupe; transactional usage reservations/attempt ledger; current-card manifest; retrieval selection manifest with query/selector revisions and original references. Use restricted worker capabilities like the existing queue, not unrestricted tenant browsing. Provider calls occur outside DB transactions and revalidate membership/source/lease before finalization. Runtime roles and Azure hosting are Vova's decisions, not instructions to deploy.

## 5. Retrieval contract and counterevidence

The user-visible Analyze API does not currently define a typed problem query. Decide whether the “current problem” is an optional explicit focus, owner-selected goal, current captured issue or several bounded queries derived deterministically from current original evidence/cards. Recommend bounded deterministic queries from evidenced goals/problems plus optional explicit focus. No paid query-rewrite/reranking call per search. User focus is a retrieval instruction, not evidence that a goal exists.

Proposed retrieval steps, all within the selected workspace:

1. Freeze an eligible corpus revision/time. Filter ready active **current** versions and valid derived revisions before ranking; retain metadata/original search for unenriched documents.
2. Build bounded candidate lanes: ranked original lexical text, card topics/entities, older goal/decision anchors, completion/cancellation/counterevidence, and unseen/least-selected coverage. Do not apply the existing 200-document recency/rotation cap before these indexes or old relevant sources remain unreachable.
3. Rank within each lane. PostgreSQL offers weighted `tsvector`, `ts_rank`/`ts_rank_cd`, and GIN indexing. Use explicit source-language configurations plus a `simple` lane for exact names/IDs/mixed text; compare English/Russian morphology on fixtures. Built-in ranking is not BM25 or a corpus-global semantic truth score. Keep original and AI card matches distinguishable. [PostgreSQL search controls](https://www.postgresql.org/docs/18/textsearch-controls.html), [index documentation](https://www.postgresql.org/docs/18/textsearch-indexes.html).
4. Fuse ranks (e.g. reciprocal rank fusion) rather than adding incompatible lexical/vector scales. Tune lane weights on development data; deterministic tie-breaking, near-duplicate suppression, document diversity and coverage aging prevent one import from dominating.
5. For every proposed goal/blocker/decision cluster, search **both** support and opposite/resolved/superseded evidence across history, using the same subject/entity/aliases plus completion/cancellation cues. Negation cannot be resolved by similarity alone. Include older anchors and newer changes; do not universally decay all old evidence.
6. Load exact original references and neighboring sections within a bounded expansion allowance. Revalidate version/hash/deletion/authorization. Fit the existing five-source and 32,000-byte whole-request limits and both stage envelopes. Token accounting is separate. When necessary, evict weak support to include counterevidence; lower output confidence/omit a status Flare if the relationship cannot fit.
7. Pin originals and selection metadata atomically into the existing manual cycle or scheduled T-30 snapshot, retaining existing quota rules. Enrichment finishing or edits after T-30 cannot change that cycle. Record partial coverage and selection omissions without implying no completion exists.
8. Run existing extraction and Flare detection on originals only. Validate exact citations and semantic support; zero Flares remains valid. Keep retrieval diagnostics out of public prose unless they help explain missing/partial processing.

Embeddings are optional. No embedding route was found in Flare; provider/model/dimension/cost/data controls need approval and separate accounting. Start with exact workspace-filtered vectors for evaluation. Approximate HNSW/IVFFlat can lose recall under post-scan tenant filters, so compare with exact results and deployed-version support before adoption. Preserve lexical entity/negation and counterevidence lanes. [pgvector primary documentation](https://github.com/pgvector/pgvector#filtering).

Proposed bounded search configuration has independent `query_count`, candidates per lane, total candidates, neighbors per hit, retrieval deadline, statement timeout and original evidence byte/token caps. Suggested **evaluation** grid: 20/50/100 candidates per lane; final original count stays five under the present contract. These are unmeasured tuning points, not production defaults. A giant import must not grow query fan-out with its document count.

## 6. Shared boundaries and coordination

Pre-edit shared context showed DATA-001 at `docs/research/DATA-001/` and GROWTH-001 at `docs/research/GROWTH-001/`; both have separate published branches. Their explicit task contracts assign ingestion/publication to DATA, enrichment/retrieval/budgets to ARCH, and acquisition/funnel analytics to GROWTH. No write-scope overlap or ownership conflict was found. This report does not edit either report or require their completion. Interface proposals below are not represented as agreement from those owners.

| Interface assumption | ARCH requirement | Owner / unresolved integration |
| --- | --- | --- |
| Published text-ready version | Workspace/document/version IDs, source type, parser revision, original chunk IDs/hash/order and provenance locators available after publication | DATA decides staging/extraction, accepted formats and atomic versus partial package publication. Enrich only visible published versions; no ZIP/raw asset input here. |
| Publication notification | Durable outbox or bounded cursor scan; key per published version, retry-safe | DATA chooses publication transaction boundary. ARCH can scan committed versions independently if no event is agreed; never lose publication or enqueue one model call per file synchronously. |
| Package progress | Import completion unchanged by missing AI enrichment; optional independent pending/ready/deferred counts | DATA owns package/file progress. ARCH owns enrichment statuses; combine only after a common API contract review. |
| Imported participation | Same eligibility, queue budget and retrieval lanes as native Notes; exact relative paths/locators retained | Images excluded in v1. PDF/audio/other attachment conversion is DATA/product's unresolved format decision; only already published supported text enters ARCH. |
| Capture/import/Analyze outcomes | Logical import published, Analyze accepted/completed/failed; separate enrichment readiness if useful | GROWTH owns identity/events/reporting. Enrichment completion is not Analyze or activation by itself. No per-chunk payload/content sent to funnel analytics. |
| Cancellation/deletion | Before/after provider-call source validation and card exclusion | Import cancellation before publication generates no enrichment. Once partially published sources exist, DATA decides rollback/deletion; ARCH follows source-validity policy. |

If DATA's final publication/identifier semantics differ, coordinate the interface before implementation; do not silently change that report or expand this scope. Existing task boundaries resolve ownership; they do not approve a new shared schema.

## 7. Provider evidence (checked 2026-10-02)

| Primary source | Documented fact | Consequence / uncertainty |
| --- | --- | --- |
| [Groq GPT-OSS 20B](https://console.groq.com/docs/model/openai/gpt-oss-20b) | Standard input $0.075 / output $0.30 per million tokens; 131,072 context and 65,536 max output | Small 20B/low calls are the starting comparison. These ceilings are not desired request sizes or free-tier entitlements. |
| [Groq GPT-OSS 120B](https://console.groq.com/docs/model/openai/gpt-oss-120b) | $0.15 / $0.60 per million; same context/output ceilings | Twice the token price at equal usage. No measured Flare quality uplift; escalation must be explicit and budgeted, not automatic. |
| [Structured Outputs](https://console.groq.com/docs/structured-outputs), [reasoning](https://console.groq.com/docs/reasoning), [API](https://console.groq.com/docs/api-reference) | GPT-OSS models support strict schema mode; streaming/tool use unsupported with structured outputs; low/medium/high effort; reasoning can be hidden; maximum completion tokens bound generation | Use strict schema and semantic/citation validation. Hiding reasoning is not disabling it or proof of a cheap short completion. Account for reported total completion usage. |
| [Rate limits](https://console.groq.com/docs/rate-limits) | Organization-level; public Free GPT-OSS rows show 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD; account exceptions and separate input/output TPM can apply. Request headers describe RPD, token headers TPM; 429 supplies retry-after | Read actual organization limits before deployment. Enrichment, Analyze and other consumers share provider capacity; local Analyze dates are unrelated to provider resets. No account capacity verified. |
| [Spend limits](https://console.groq.com/docs/spend-limits) | Monthly organization-wide, shared across keys/endpoints, 10–15-minute tracking delay; in-flight calls complete | Useful outer guard, insufficient for atomic workspace/day or rolling budgets. No console setting changed. |
| [Batch processing](https://console.groq.com/docs/batch) | GPT-OSS 20B/120B supported; 50% discount, separate standard-limit impact, 24h–7d windows; discount does not stack with caching; completed expired-batch requests billed | Optional paid cold-backlog path with full reservations before upload, per-result validation, retention review and bounded manifests. Not unlimited/free work. |
| [Batch guide](https://console.groq.com/docs/batch) versus [API reference](https://console.groq.com/docs/api-reference) | Guide: 50,000 lines/200 MB; create-batch reference: input file up to 100 MB | Official inconsistency. Use a much smaller configurable bound below both if selected; verify actual API/account behavior before launch. No endpoint measurement here. |
| [Your Data](https://console.groq.com/docs/your-data) | Inference content not retained by default; reliability/abuse exceptions up to 30 days. Batch input/output retained up to 30 days unless deleted sooner; ZDR disables persistence-dependent features. Retained customer data in US | Vova/product owner must verify actual controls and disclosures before enrichment/Batch rollout; source ZIP deletion does not delete provider copies. |

Context7 was used first for Groq, PostgreSQL and pgvector; official pages supplied precise current provider facts when broad indexed snippets lacked them. PostgreSQL lookup used the indexed v18 documentation; verify actual deployed database/extension versions before SQL implementation. No production dependency change was made.

## 8. Separate enrichment budget options

Every option preserves the daily Analyze allowance. Background work remains disabled until the owner selects its allowance and policy; raw content/search/Analyze can still work without enriched cards.

| Budget option | Enforcement | Tradeoff |
| --- | --- | --- |
| B1 — workspace/day allowance | Separate fixed request + input/output token + USD caps by workspace budget date; no carryover; global organization ceiling | Simple to explain; midnight burst and timezone gaming need a persisted budget timezone/reset policy. Do not reuse Analyze quota rows or allow timezone edits to refund spend. |
| B2 — rolling token/USD bucket | Workspace refill rate, bounded burst, per-call reservations; organization bucket; concurrent lease cap | Smoother traffic, no calendar reset bypass; needs user-facing next-eligible time and precise refill/reservation semantics. Recommended technical default for evaluation, amounts unapproved. |
| B3 — one-time onboarding credit + B1/B2 maintenance | Nonrenewable credit tied to accepted onboarding entitlement; daily/rolling maintenance for changed documents | Faster backlog coverage if funded. Reimport, filenames, users and new workspace creation must not recreate credits; global/account anti-abuse still required. |
| B4 — owner-selected/on-demand enrichment | Explicit approved documents/sections, same hard accounting and queue; optional paid Batch lane | Predictable priorities and no automatic backlog drain; partial coverage persists longer. A request to enrich does not grant a second Analyze. |

Combine a workspace cap with account/user/plan entitlement and a global monthly/daily/rolling spend ceiling so an attacker cannot multiply budgets by creating workspaces. Numeric launch allowances, paid tiers, reset timezone, carryover, refunds and sponsor credits are unresolved product decisions. A request-count cap alone is insufficient when Note lengths differ.

### Admission, actual-call accounting and abuse controls

Each physical call needs a unique attempt/reservation key. In a short transaction, verify entitlement, current version and runnable lease; enforce workspace concurrency `Cw`, global concurrency `Cg`, queue bounds and remaining token/USD/request budgets; reserve worst-case input+output cost and rate capacity atomically. Commit, release the connection, and only then call Groq. Unique reservation keys make replays safe. Every retry and strict-schema retry repeats admission. Do not reserve once per job and then permit hidden extra calls.

Implementation must place that admission boundary around both existing Analyze stages and their internal retries as well as new enrichment calls. Other Groq consumers must report to the organization governor, with audio quota dimensions where applicable. The separate Analyze product slot remains unchanged; shared provider accounting supplies no extra product entitlement. Settle/release each reservation once under a transaction, retain unknown liabilities across resets, and never refund dispatch merely because a lease or local-day bucket expired.

For known priced profile `m`, reserve `U = (I_bound * p_in(m) + O_max * p_out(m)) / 1e6`, with an approved safety margin if counting is approximate. Admission invariant: `settled + held + U <= allowance` simultaneously for workspace and organization. Enforce input/output/request quotas separately from dollars; free capacity is still scarce. A validated model tokenizer and full serialized envelope estimate are required for token admission. Until calibrated, use a conservative byte-based upper allowance with headroom and refuse ambiguous cases; never treat 4,000 bytes as 1,000 measured tokens.

On success reconcile to provider-reported input/completion tokens and recorded price revision. Store measured usage separately from calculated cost; invoices remain billing authority. On timeout/crash after dispatch, mark usage unknown and retain conservative spend/rate charges until safe reconciliation; lease expiry alone cannot refund a possibly billed call. A pre-dispatch cancellation may release a reservation. Late duplicate results never publish two cards; remote exact-once inference cannot be promised after unknown outcomes.

Coalesce rapid edits; invalidate cheap metadata immediately but debounce expensive work. Dedupe identical section inputs/revisions within a workspace, prioritize the current desired version, and cap requeues/attempts/queued items. Batch uploads reserve the entire admitted manifest across the processing window, including any global cap it crosses; do not release day-one holds at midnight. Limit new-workspace credits/account submissions, regeneration controls and oversized/churning inputs. Enforce fairness using workspace scheduling with aging and per-package/document shares, rather than first-come draining a massive import.

## 9. Queue, bounds and degradation

Use a logical enrichment lane separate from imports and daily analysis, even if all initially use PostgreSQL-backed workers. Claim small batches with leases/checkpoints; process only admitted jobs; retain imported originals and resume later. Per-workspace concurrency, global provider admission and fair scheduling must be shared across worker processes, not in-memory semaphores alone. Reserve provider headroom for accepted Analyze cycles; background backlog does not take that reserved capacity. A full import is never a command to launch concurrent provider calls.

Enumerate published versions/sections lazily from a durable cursor under a bounded pending-row cap. Preserve checkpoints so a 100,000-section backlog can wait without creating 100,000 immediate runnable calls or losing coverage. Mark section/document completeness separately; no document rollup says “complete” until its declared source range is covered.

### Proposed input/output envelope for evaluation

| Bound | Evaluation proposal, not production approval |
| --- | --- |
| Enrichment input | At most 4,000 total input tokens **including prompt/schema/identities**, plus an independent 32,000-byte serialized envelope. Both must fit; tokenizer/model context and actual rate capacity also apply. |
| Enrichment output | At most 1,024 total generated tokens including reasoning; parsed payload at most 8 KiB, title 80 chars, description 240 chars, at most 8 entities/topics and 6 evidence-backed claims with at most 2 references/claim and 240-char quotes. If the payload cannot fit, reduce claim count or split the section, never raise caps automatically. |
| Logical batch inside one completion | Only small sections from one authorized workspace, explicit section IDs and separate results; packing bound applies to the whole envelope/output. No cross-tenant mixing. Evaluate single-section first because shared output limits and one invalid item can cause collateral retries. |
| Provider Batch | Many independent, already admitted bounded requests; separate manifest/result/checkpoint identity, limited files/in-flight jobs, no auto-resubmission of successful requests. Confirm account eligibility, schema support on route, windows and data controls. |
| Attempts/concurrency | Evaluation starts with one in-flight background call/workspace; total physical provider attempts per logical enrichment job at most 3, counting strict-schema retry. Global concurrency derives from verified capacity. No numeric production allocation selected. |
| Runtime | Evaluation reuse of current 5s connect/30s operation/40s wall deadline; leases must exceed deadline plus finalization margin; queue age and section count bounded independently. Batch processing needs its own longer durable state machine, not this lease. |

These values are intentionally below model ceilings and make reservations calculable; they are not measured optimal choices. The schema itself must be included in input counting and output-bound feasibility tests, especially for multilingual/reasoning responses. No 120B fallback, tools or additional “repair” calls without a new admitted attempt.

Retry bounded transient 429/408/network/timeout/409/5xx with exponential jitter and provider retry-after/reset hints, storing `available_at` instead of sleeping while holding locks. Organization/day exhaustion defers until capacity returns. Invalid schema/citations/truncation or ordinary 4xx are terminal unless a specifically classified, capped schema retry is admitted; 401/403/configuration opens an operational circuit, avoiding retries across the entire backlog. Record returned model mismatch and reject it.

| Failure/degraded condition | Required behavior |
| --- | --- |
| Budget exhausted / backlog too large | Originals usable immediately; metadata/original lexical retrieval and rotation fallback; visible enrichment deferred/partial coverage and next eligible time. Prioritize evidenced active goals/issues, user-selected documents, then unseen sections with fairness aging. |
| Provider unavailable/rate-limited | Import success unaffected; delayed bounded retries/circuit; no provider call from API handlers; Analyze retains existing failure/slot semantics. |
| Stale/deleted/unauthorized source | Exclude from retrieval and reject finalization, even if a card or vector still exists. Preserve deletion visibility for historical Flares. |
| Summary hallucinates/omits negation | Search originals/counterevidence independently; validate card support; reject unsupported card fields; do not convert a characteristic into project truth. |
| Counterevidence not retrieved or cannot fit | State unknown, no unfinished/completed claim from absence; drop or defer that candidate. A harmless evidenced decision Reminder may still be possible under existing semantic guards. |
| Enrichment delayed past T-30 | Current scheduled snapshot unchanged; newly ready card participates next cycle. Never re-pin/enqueue a second run. |
| Optional embedding service fails | Lexical lanes still available; no secret automatic alternative provider or rebudgeting. |
| Worker crash / duplicate publication event | Durable cursor/outbox replay, idempotent section jobs and result publication; held unknown usage reconciled conservatively. |

## 10. Cost model and sensitivity (estimates only)

Formula: `USD = input_tokens * input_rate / 1e6 + total_completion_tokens * output_rate / 1e6`. Include prompts, schemas, reasoning, retries, failed/unknown calls, rollups and any embedding/query work. Hosting/DB/index/storage/network/taxes are additional and unmeasured. No cache hit or free credit assumed. Provider-reported tokens would be measured usage; multiplying by a published price would still be a calculated cost, not an invoice.

Illustrative per-section 20B usage: 2,000 input + 500 total completion tokens = **$0.00030**. Maximum evaluation-envelope reservation at 4,000 + 1,024 = **$0.0006072** per physical call. Three attempts at that upper envelope = **$0.0018216**. Equal token counts on 120B cost twice as much; quality is not measured.

| Section count, not document count | Assumed total tokens, no retries/rollup | Standard 20B USD estimate | Eligible Batch estimate | Days at illustrative separate 20k tokens/day |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 250,000 | 0.03 | 0.015 | 13 |
| 1,000 | 2,500,000 | 0.30 | 0.15 | 125 |
| 10,000 | 25,000,000 | 3.00 | 1.50 | 1,250 |

The 20k allocation is a sensitivity example, **not an approved allowance**. The public 200k TPD could at most fit 80 such section calls/day before any Analyze/other consumer or safety headroom, even if request ceilings are larger. Dollar affordability alone does not imply usable free-tier throughput. A 100k-character document may require many sections, so per-document flat estimates conceal import cost. Document/project rollup calls and repeated edits add independent terms.

For N section jobs with typical input I/output O, retry multiplier R and M rollups: `C ≈ N * R * cost(I,O) + M * cost(rollup_I,rollup_O) + embedding/query cost`. Drain lower bound uses the tightest request, token, concurrency and funded-spend allowance. Do not advertise the model page's tokens/second as end-to-end queue SLA.

Operational ledger fields: workspace/job/attempt/reservation, price/profile/model/prompt/schema revisions, configured/returned model, request/completion IDs, actual usage or unknown, estimated/reserved/calculated cost, latency/queue wait/retry reason, rate headers and validation outcome. Metrics: per-workspace/day/rolling usage, unknown liability, backlog coverage/age, physical calls per job, discarded stale work, invalid cards, retry share and Analyze starvation. No raw Notes, prompts, reasoning traces or keys in logs/analytics by default.

## 11. Validation evidence and evaluation plan

Run `python3 docs/research/ARCH-001/research_checks.py` from the task worktree. It imports no application code, reads only allowlisted source files through Git, uses no credentials/network, and writes results only within this scope.

The artifact checks exact UTF-8 reconstruction, size bounds and offsets for ASCII, Russian/emoji/CRLF and combining-character/BOM fixtures; serial reservation admission for 10,000 proposed jobs under a deliberately tiny cap; conservative timeout accounting; original-quote membership; current-version/deletion/workspace filtering; and unknown state when completion is omitted. It calculates the cost sensitivity table and records source digests. This is a small executable check of design invariants, **not** proof of database concurrency, production RLS, a semantic retrieval benchmark or measured model quality. Its byte splitter is deliberately a toy; it does not implement the proposed heading-aware chunker.

Actual offline result: **17 checks passed, zero provider calls**. Fixture sizes were 200,000 / 120,000 / 42,000 UTF-8 bytes, producing 50 / 30 / 11 bounded slices respectively. The serial budget example admitted one of 10,000 proposals and retained its charge after an unknown timeout. The research diff passed `git diff --check`; final publication additionally verifies the directory-only scope and a clean published HEAD through task-sync. These checks do not measure production throughput or provider billing.

No application suite or live enrichment smoke script was run: no product code changed, and live scripts load credentials/send provider calls. Source inspection of existing tests shows rotation, daily-quota, citation, stale-source and concurrency scenarios, but reading tests is not a fresh pass result.

### Ranking/counterevidence evaluation required before implementation acceptance

Build an owner-approved, de-identified EN/RU/mixed-language corpus with immutable document/section IDs, original quotes and timestamped expected relationships. Two reviewers label relevance and entailment, including neutral/ambiguous cases; adjudicate differences. Keep development queries separate from held-out queries and split at project/history level to avoid near-duplicate leakage. Synthetic data can exercise guards but cannot establish product quality.

Compare current rotation, raw lexical baseline, A, B, and optional C under **identical final five-source/byte/token budgets**. Measure both candidate recall and final evidence recall; an excellent 100-hit ranking can fail after context packing. Ablate summary-only search, counterevidence lane, historical anchors, neighbors and coverage reserve. Report per-language, source type, history age, enriched coverage and corpus-size strata.

| Fixture category | Required observation/metric |
| --- | --- |
| Goal/decision months before current state | Recall of original goal/constraint and explicit later state together; document diversity; pair recall@5 |
| Goal → distant completion/cancellation → recent routine updates | Completion/counterevidence recall@5, false unfinished rate; identical-subject disambiguation |
| Reopened work / contradictory claims with dates | Both relevant claims retained; no simplistic newest=truth rule; ordering/entailment judged on originals |
| Negation, aliases, Russian/English paraphrase | Recall@k, nDCG@k, false-goal/false-contradiction rate; semantic lane uplift versus cost |
| Long Note ending / Markdown/CSV split boundaries | Slice/neighbor evidence recovery without truncation or broken quotes |
| Deleted source, edit after enrichment, title-only edit, T-30 edit race | Zero leaked current retrieval/invalid publication; unchanged historical citations; fixed scheduled snapshot |
| Partial enrichment / cold huge import | Usability without AI, coverage fairness, worst backlog age, retrieval quality by coverage; zero unbounded call burst |
| Reimport, edit spam, workspace churn, timeout/429/schema retries | Physical-call reservations enforced; no extra Analyze slot; cross-worker admission/account entitlements tested |
| Prompt injection / fabricated citation / misleading summary | Zero unauthorized tools/actions/source IDs; exact-quote guards plus human entailment review |

Safety gates: zero cross-workspace/deleted-source exposure in the test matrix, zero fabricated original citations accepted, and no quota bypass. Product owner must set acceptable ranking/Flare quality thresholds before model comparison; do not invent a success percentage after viewing results. Measure false unfinished assertions explicitly, rather than relying only on nDCG.

Future controlled provider pilot must be explicitly funded: cap total calls/tokens/USD across all candidate profiles and judges, record inputs' sizes, usage/latency/errors and model revisions, and stop on reservations exhausted. Test output-cap truncation, reasoning usage, retries and actual organization headers. Do not use model-generated summaries as gold labels. Cost calibration must compare ledger totals with provider usage/billing; unknown calls remain a separate liability.

Future load/security validation: disposable migrated PostgreSQL, restricted roles, multiple worker processes racing the same budget/version, crash at reserve/dispatch/finalize, revoke membership/delete during calls, cancellation, DST/budget reset boundaries and scheduled/manual races. Verify query plans and recall for 1k/10k/100k sections across uneven tenants; record resource/latency ranges before limits are selected. The scale points are test plans, not measured capacity.

## 12. Decisions still reserved for the owner / Vova

| Decision | Choices / evidence needed |
| --- | --- |
| Initial architecture | A staged document baseline versus recommended B layered lexical target; C only after paraphrase/language evaluation; D later if global questions matter |
| Long Note contract | Derived ranges + slice-aware Analyze adapter versus new properly chunked versions; history/backfill and API implications require review |
| Current-problem definition | Explicit optional focus, evidenced goal selection or deterministic issue queries; no invented goal from user intent |
| Enrichment entitlement | Automatic bounded background versus explicit opt-in/on-demand; separate daily/rolling budget, amounts, onboarding credit, paid top-up and timezone/reset/refund policy |
| Model/quality profile | 20B/low first; approve any 120B escalation only with measured uplift and total-call budget |
| Coverage and rollout limits | Section/claim/card bounds, ranking lane caps, freshness/debounce, queue caps, fairness, concurrency and measurable SLOs after evaluation |
| Embeddings | Whether necessary; approved model/provider/location/dimension/query costs; exact versus ANN; deployed extension compatibility |
| Shared import interface | DATA publication/cursor/ID/partial visibility agreement; image exclusion retained; PDF/audio conversion still unresolved |
| Provider privacy and Batch | Actual Groq data controls/ZDR, account eligibility/limits, batch file-limit inconsistency, retention/deletion and user disclosure |
| Infrastructure | Vova chooses worker hosting/isolation, Azure network/provider reachability, database roles/extensions, observability and operational spend ceiling |
| Flare acceptance | Held-out ranking/pair-recall and false unfinished thresholds, human entailment review, safe presentation of partial coverage |
| Retention/analytics | Derived content/history TTL, deletion purge, minimal ledger retention; GROWTH decides event semantics without content payloads |

Continuation condition: owner reviews this design and selects the material contracts above; coordinator assigns implementation tasks with explicit scopes and funded provider tests. Research completion alone authorizes no product implementation, migrations, runtime configuration changes or deployment.

## 13. Review handoff

Required report is `docs/research/ARCH-001/report.md`; supporting artifacts are `research_checks.py` and `research-results.json`. All substantive changes stay in this declared directory. Publish the clean research branch, record its HEAD through task-sync, then move ARCH-001 to **review** with branch/SHA and actual check evidence. Acceptance remains pending; do not call finish or mark done.

The published task-sync review record supplies the final result commit SHA without embedding a self-referential commit hash in this file. The branch contains no product code, migrations, runtime config or deployment edits.
