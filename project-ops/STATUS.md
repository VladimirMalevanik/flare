# СТАТУС ПРОЕКТА

> Этот файл генерирует `task-sync`; вручную его не редактируют.

Сформировано: `2026-10-02T10:48:21Z`
Последнее обновление работы: `2026-10-02T10:48:21Z`
Снимок состояния: `sha256:7272c2d32a0ccbd83945e5a9ec8baa81b9662e6562aabb81025210b059e7ef1f`

## Ближайшая цель

[Prepare Flare for safe parallel development and then implement scalable imports, Project Memory improvements, and acquisition attribution through separately claimed tasks.](NOW.md)

Критерий готовности: Coordination is ready when root AGENTS.md leads a fresh agent to AGENT_SETUP.md, task-sync v0.1.0 reads the published shared state, render-status and verify-snapshot pass, doctor succeeds, and the branch, scope, overlap, and acceptance rules are documented. Product work requires separate task-specific acceptance and evidence.

## Ближайшие шаги (не более пяти)

1. `WEB-001` (в работе) — Implement opt-in Funny mode: persisted settings toggle, colorful light/dark theme, Magic 8-ball replacing capture orb, English shake instructions, single real Analyze request after deliberate shaking, progress/result animation and bounded muteable funny sounds. Preserve daily allowance, auth, capture/voice, true empty/error results and reduced-motion accessibility. No backend, schema or production dependency changes.. Сейчас: Implement Funny mode in isolated frontend branch; preserve real Analyze state and capture/voice behavior
2. `DATA-002` (на проверке) — Implement production-quality asynchronous one-time Notion/Obsidian ZIP onboarding, including package gate, tenant-safe jobs, provenance/idempotency, configurable reservations, local/test staging, recovery/cleanup and Vault integration. Full required contract and acceptance checks: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#data-002. No automatic Analyze or AI provider calls.. Условие: Review the complete asynchronous Notion/Obsidian ZIP onboarding application, linear migration 0019, package-gated publication, tenant-safe worker/recovery/cleanup, configurable local-test staging and EN/ES UI. Owner acceptance and product integration remain pending; production OPS/Vova decisions and browser visual QA remain separate. Do not mark done.; зависит от: DATA-001
3. `OPS-001` (на проверке) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Условие: Review redacted runtime/staging decision and evidence record; Vova selection/acceptance and sanitized inventory remain pending. Do not mark done or authorize rollout from public probes.
4. `GROWTH-002` (будем брать) — Implement the minimal extensible first-party attribution and milestone foundation: bounded pre-auth first/last non-direct touches frozen at signup, authoritative outcomes/dedupe, separate acquisition persistence, authenticated-event reuse, restricted aggregate reports, privacy and cleanup. Full contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#growth-002. No analytics UI, every-click collector, vendor or Azure correctness dependency.. Условие: Unclaimed and blocked on DATA-002 acceptance/integration to main. Fetch and validate that single migration head before claim; start a new clean branch there, never an independent migration head from the old base. Planned scope: acquisition/auth/event/reporting modules, minimal domain-outcome observation, successor migrations/schema/readiness, public/auth/client-event wiring, tests/query/load scripts, docs/implementation/GROWTH-002/. Exact envelope in decision document; no unapproved production retention/lookback durations.; зависит от: GROWTH-001, DATA-002; не завершены: DATA-002

## В работе

- `WEB-001` (в работе) — Implement opt-in Funny mode: persisted settings toggle, colorful light/dark theme, Magic 8-ball replacing capture orb, English shake instructions, single real Analyze request after deliberate shaking, progress/result animation and bounded muteable funny sounds. Preserve daily allowance, auth, capture/voice, true empty/error results and reduced-motion accessibility. No backend, schema or production dependency changes.. Сейчас: Implement Funny mode in isolated frontend branch; preserve real Analyze state and capture/voice behavior; владелец: Vova / Codex / WEB-001

## На проверке

- `DATA-002` (на проверке) — Implement production-quality asynchronous one-time Notion/Obsidian ZIP onboarding, including package gate, tenant-safe jobs, provenance/idempotency, configurable reservations, local/test staging, recovery/cleanup and Vault integration. Full required contract and acceptance checks: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#data-002. No automatic Analyze or AI provider calls.. Условие: Review the complete asynchronous Notion/Obsidian ZIP onboarding application, linear migration 0019, package-gated publication, tenant-safe worker/recovery/cleanup, configurable local-test staging and EN/ES UI. Owner acceptance and product integration remain pending; production OPS/Vova decisions and browser visual QA remain separate. Do not mark done.; владелец: Fedor / Codex / DATA-002; зависит от: DATA-001
- `OPS-001` (на проверке) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Условие: Review redacted runtime/staging decision and evidence record; Vova selection/acceptance and sanitized inventory remain pending. Do not mark done or authorize rollout from public probes.; владелец: Vova / OPS decision owner

## Блокеры

- `ARCH-002` (требуется информация) — Future Project Memory implementation after budget approval: layered section/document characteristics, lexical-first retrieval, explicit counterevidence/completion lane, original evidence grounding and lifecycle/evaluation. Embeddings deferred. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#arch-002. This task currently authorizes no automatic enrichment implementation or provider calls.. Условие: WAITING: responsible enrichment-budget owner must supply approved entitlement/onboarding credit, rolling/day and workspace/global Groq ceilings, concurrency, paid/free behavior, numeric limits and rollout policy. Record approval, coordinate shared/migration scopes and fresh main before moving to next or claim. Planned future envelope: memory modules, bounded Analyze/context adapters, versioned schema/worker capabilities, tests and docs/implementation/ARCH-002/; no scope activated now.; владелец: ARCH / unassigned; Groq budget decision owner pending; зависит от: ARCH-001
- `GROWTH-002` (будем брать) — Implement the minimal extensible first-party attribution and milestone foundation: bounded pre-auth first/last non-direct touches frozen at signup, authoritative outcomes/dedupe, separate acquisition persistence, authenticated-event reuse, restricted aggregate reports, privacy and cleanup. Full contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#growth-002. No analytics UI, every-click collector, vendor or Azure correctness dependency.. Условие: Unclaimed and blocked on DATA-002 acceptance/integration to main. Fetch and validate that single migration head before claim; start a new clean branch there, never an independent migration head from the old base. Planned scope: acquisition/auth/event/reporting modules, minimal domain-outcome observation, successor migrations/schema/readiness, public/auth/client-event wiring, tests/query/load scripts, docs/implementation/GROWTH-002/. Exact envelope in decision document; no unapproved production retention/lookback durations.; владелец: GROWTH / unassigned; зависит от: GROWTH-001, DATA-002; не завершены: DATA-002

## Вопросы пользователю

- Немедленного решения пользователя не требуется.

## Предупреждения

- WEB-001: ещё не записаны опубликованная ветка и область файлов.
