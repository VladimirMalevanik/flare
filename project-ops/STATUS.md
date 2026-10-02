# СТАТУС ПРОЕКТА

> Этот файл генерирует `task-sync`; вручную его не редактируют.

Сформировано: `2026-10-02T19:11:53Z`
Последнее обновление работы: `2026-10-02T19:11:53Z`
Снимок состояния: `sha256:e72f83451ad8d25ed6e83af562397e1f9b969dd3cc0538a26b6fee17225529de`

## Ближайшая цель

[Prepare Flare for safe parallel development and then implement scalable imports, Project Memory improvements, and acquisition attribution through separately claimed tasks.](NOW.md)

Критерий готовности: Coordination is ready when root AGENTS.md leads a fresh agent to AGENT_SETUP.md, task-sync v0.1.0 reads the published shared state, render-status and verify-snapshot pass, doctor succeeds, and the branch, scope, overlap, and acceptance rules are documented. Product work requires separate task-specific acceptance and evidence.

## Ближайшие шаги (не более пяти)

1. `DATA-002` (в работе) — Implement production-quality asynchronous one-time Notion/Obsidian ZIP onboarding, including package gate, tenant-safe jobs, provenance/idempotency, configurable reservations, local/test staging, recovery/cleanup and Vault integration. Full required contract and acceptance checks: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#data-002. No automatic Analyze or AI provider calls.. Сейчас: Prepare PR and return validated two-defect DATA-002 correction to owner review; зависит от: DATA-001
2. `WEB-002` (на проверке) — Add a Subscription section to Settings with Free, Pro and Team descriptions; grey Current for the current Free tier and blue Buy actions. Connect Pro Buy to official Paddle.js Sandbox overlay using public env placeholders and price pri_01m3y1nvmgw2avt60bz87161c2, quantity 1, authenticated email and customData.userId. Enforce sandbox-only tokens, single initialization and checkout locking, localized recoverable errors, existing design/auth preservation and frontend checks. Team stays explicitly unconfigured until a separate Sandbox price exists. No Live, server API key, webhooks, entitlement/DB changes, portal, cancellation or deployment.. Условие: Owner requested merge and deployment on 2026-10-02. PR32 merged and deployed to https://flare4u.tech/settings; Paddle remains Sandbox. Actual signed-in checkout/trial/payment verification is pending a Flare session; no paid access or plan DB changes.
3. `OPS-001` (на проверке) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Условие: Review redacted runtime/staging decision and evidence record; Vova selection/acceptance and sanitized inventory remain pending. Do not mark done or authorize rollout from public probes.
4. `GROWTH-002` (будем брать) — Implement the minimal extensible first-party attribution and milestone foundation: bounded pre-auth first/last non-direct touches frozen at signup, authoritative outcomes/dedupe, separate acquisition persistence, authenticated-event reuse, restricted aggregate reports, privacy and cleanup. Full contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#growth-002. No analytics UI, every-click collector, vendor or Azure correctness dependency.. Условие: Unclaimed and blocked on DATA-002 acceptance/integration to main. Fetch and validate that single migration head before claim; start a new clean branch there, never an independent migration head from the old base. Planned scope: acquisition/auth/event/reporting modules, minimal domain-outcome observation, successor migrations/schema/readiness, public/auth/client-event wiring, tests/query/load scripts, docs/implementation/GROWTH-002/. Exact envelope in decision document; no unapproved production retention/lookback durations.; зависит от: GROWTH-001, DATA-002; не завершены: DATA-002

## В работе

- `DATA-002` (в работе) — Implement production-quality asynchronous one-time Notion/Obsidian ZIP onboarding, including package gate, tenant-safe jobs, provenance/idempotency, configurable reservations, local/test staging, recovery/cleanup and Vault integration. Full required contract and acceptance checks: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#data-002. No automatic Analyze or AI provider calls.. Сейчас: Prepare PR and return validated two-defect DATA-002 correction to owner review; владелец: Fedor / Codex / DATA-002; зависит от: DATA-001

## На проверке

- `WEB-002` (на проверке) — Add a Subscription section to Settings with Free, Pro and Team descriptions; grey Current for the current Free tier and blue Buy actions. Connect Pro Buy to official Paddle.js Sandbox overlay using public env placeholders and price pri_01m3y1nvmgw2avt60bz87161c2, quantity 1, authenticated email and customData.userId. Enforce sandbox-only tokens, single initialization and checkout locking, localized recoverable errors, existing design/auth preservation and frontend checks. Team stays explicitly unconfigured until a separate Sandbox price exists. No Live, server API key, webhooks, entitlement/DB changes, portal, cancellation or deployment.. Условие: Owner requested merge and deployment on 2026-10-02. PR32 merged and deployed to https://flare4u.tech/settings; Paddle remains Sandbox. Actual signed-in checkout/trial/payment verification is pending a Flare session; no paid access or plan DB changes.; владелец: Vova / Codex / WEB-002
- `OPS-001` (на проверке) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Условие: Review redacted runtime/staging decision and evidence record; Vova selection/acceptance and sanitized inventory remain pending. Do not mark done or authorize rollout from public probes.; владелец: Vova / OPS decision owner

## Блокеры

- `ARCH-002` (требуется информация) — Future Project Memory implementation after budget approval: layered section/document characteristics, lexical-first retrieval, explicit counterevidence/completion lane, original evidence grounding and lifecycle/evaluation. Embeddings deferred. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#arch-002. This task currently authorizes no automatic enrichment implementation or provider calls.. Условие: WAITING: responsible enrichment-budget owner must supply approved entitlement/onboarding credit, rolling/day and workspace/global Groq ceilings, concurrency, paid/free behavior, numeric limits and rollout policy. Record approval, coordinate shared/migration scopes and fresh main before moving to next or claim. Planned future envelope: memory modules, bounded Analyze/context adapters, versioned schema/worker capabilities, tests and docs/implementation/ARCH-002/; no scope activated now.; владелец: ARCH / unassigned; Groq budget decision owner pending; зависит от: ARCH-001
- `GROWTH-002` (будем брать) — Implement the minimal extensible first-party attribution and milestone foundation: bounded pre-auth first/last non-direct touches frozen at signup, authoritative outcomes/dedupe, separate acquisition persistence, authenticated-event reuse, restricted aggregate reports, privacy and cleanup. Full contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#growth-002. No analytics UI, every-click collector, vendor or Azure correctness dependency.. Условие: Unclaimed and blocked on DATA-002 acceptance/integration to main. Fetch and validate that single migration head before claim; start a new clean branch there, never an independent migration head from the old base. Planned scope: acquisition/auth/event/reporting modules, minimal domain-outcome observation, successor migrations/schema/readiness, public/auth/client-event wiring, tests/query/load scripts, docs/implementation/GROWTH-002/. Exact envelope in decision document; no unapproved production retention/lookback durations.; владелец: GROWTH / unassigned; зависит от: GROWTH-001, DATA-002; не завершены: DATA-002

## Вопросы пользователю

- Немедленного решения пользователя не требуется.

## Предупреждения

Нет.
