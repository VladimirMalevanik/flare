# СТАТУС ПРОЕКТА

> Этот файл генерирует `task-sync`; вручную его не редактируют.

Сформировано: `2026-10-02T09:17:06Z`
Последнее обновление работы: `2026-10-02T09:17:06Z`
Снимок состояния: `sha256:e9e6de86cec3f8e42e5f320d5e45df673ba53377627bdc319aa7a82e12eeee94`

## Ближайшая цель

[Prepare Flare for safe parallel development and then implement scalable imports, Project Memory improvements, and acquisition attribution through separately claimed tasks.](NOW.md)

Критерий готовности: Coordination is ready when root AGENTS.md leads a fresh agent to AGENT_SETUP.md, task-sync v0.1.0 reads the published shared state, render-status and verify-snapshot pass, doctor succeeds, and the branch, scope, overlap, and acceptance rules are documented. Product work requires separate task-specific acceptance and evidence.

## Ближайшие шаги (не более пяти)

1. `OPS-001` (в работе) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Сейчас: Collect redacted repository and authorized runtime evidence; compare staging choices and exact DATA-002 blockers; documentation only
2. `DATA-002` (в работе) — Implement production-quality asynchronous one-time Notion/Obsidian ZIP onboarding, including package gate, tenant-safe jobs, provenance/idempotency, configurable reservations, local/test staging, recovery/cleanup and Vault integration. Full required contract and acceptance checks: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#data-002. No automatic Analyze or AI provider calls.. Сейчас: Implement accepted asynchronous ZIP package gate end to end, local/test staging, durable worker and comprehensive validation; зависит от: DATA-001
3. `GROWTH-002` (будем брать) — Implement the minimal extensible first-party attribution and milestone foundation: bounded pre-auth first/last non-direct touches frozen at signup, authoritative outcomes/dedupe, separate acquisition persistence, authenticated-event reuse, restricted aggregate reports, privacy and cleanup. Full contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#growth-002. No analytics UI, every-click collector, vendor or Azure correctness dependency.. Условие: Unclaimed and blocked on DATA-002 acceptance/integration to main. Fetch and validate that single migration head before claim; start a new clean branch there, never an independent migration head from the old base. Planned scope: acquisition/auth/event/reporting modules, minimal domain-outcome observation, successor migrations/schema/readiness, public/auth/client-event wiring, tests/query/load scripts, docs/implementation/GROWTH-002/. Exact envelope in decision document; no unapproved production retention/lookback durations.; зависит от: GROWTH-001, DATA-002; не завершены: DATA-002

## В работе

- `OPS-001` (в работе) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Сейчас: Collect redacted repository and authorized runtime evidence; compare staging choices and exact DATA-002 blockers; documentation only; владелец: Fedor / Codex / OPS-001; Vova decision owner
- `DATA-002` (в работе) — Implement production-quality asynchronous one-time Notion/Obsidian ZIP onboarding, including package gate, tenant-safe jobs, provenance/idempotency, configurable reservations, local/test staging, recovery/cleanup and Vault integration. Full required contract and acceptance checks: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#data-002. No automatic Analyze or AI provider calls.. Сейчас: Implement accepted asynchronous ZIP package gate end to end, local/test staging, durable worker and comprehensive validation; владелец: Fedor / Codex / DATA-002; зависит от: DATA-001

## На проверке

Нет.

## Блокеры

- `ARCH-002` (требуется информация) — Future Project Memory implementation after budget approval: layered section/document characteristics, lexical-first retrieval, explicit counterevidence/completion lane, original evidence grounding and lifecycle/evaluation. Embeddings deferred. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#arch-002. This task currently authorizes no automatic enrichment implementation or provider calls.. Условие: WAITING: responsible enrichment-budget owner must supply approved entitlement/onboarding credit, rolling/day and workspace/global Groq ceilings, concurrency, paid/free behavior, numeric limits and rollout policy. Record approval, coordinate shared/migration scopes and fresh main before moving to next or claim. Planned future envelope: memory modules, bounded Analyze/context adapters, versioned schema/worker capabilities, tests and docs/implementation/ARCH-002/; no scope activated now.; владелец: ARCH / unassigned; Groq budget decision owner pending; зависит от: ARCH-001
- `GROWTH-002` (будем брать) — Implement the minimal extensible first-party attribution and milestone foundation: bounded pre-auth first/last non-direct touches frozen at signup, authoritative outcomes/dedupe, separate acquisition persistence, authenticated-event reuse, restricted aggregate reports, privacy and cleanup. Full contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#growth-002. No analytics UI, every-click collector, vendor or Azure correctness dependency.. Условие: Unclaimed and blocked on DATA-002 acceptance/integration to main. Fetch and validate that single migration head before claim; start a new clean branch there, never an independent migration head from the old base. Planned scope: acquisition/auth/event/reporting modules, minimal domain-outcome observation, successor migrations/schema/readiness, public/auth/client-event wiring, tests/query/load scripts, docs/implementation/GROWTH-002/. Exact envelope in decision document; no unapproved production retention/lookback durations.; владелец: GROWTH / unassigned; зависит от: GROWTH-001, DATA-002; не завершены: DATA-002

## Вопросы пользователю

- Немедленного решения пользователя не требуется.

## Предупреждения

- OPS-001: ещё не записаны опубликованная ветка и область файлов.
- DATA-002: ещё не записаны опубликованная ветка и область файлов.
