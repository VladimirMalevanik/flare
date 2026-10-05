# СТАТУС ПРОЕКТА

> Этот файл генерирует `task-sync`; вручную его не редактируют.

Сформировано: `2026-10-05T19:27:42Z`
Последнее обновление работы: `2026-10-05T19:27:42Z`
Снимок состояния: `sha256:9cc594e11e02e5f6541d9bd14f747833ee4461d9dcf6fec9ce050be9c2ffbddf`

## Ближайшая цель

[Prepare Flare for safe parallel development and then implement scalable imports, Project Memory improvements, and acquisition attribution through separately claimed tasks.](NOW.md)

Критерий готовности: Coordination is ready when root AGENTS.md leads a fresh agent to AGENT_SETUP.md, task-sync v0.1.0 reads the published shared state, render-status and verify-snapshot pass, doctor succeeds, and the branch, scope, overlap, and acceptance rules are documented. Product work requires separate task-specific acceptance and evidence.

## Ближайшие шаги (не более пяти)

1. `API-003` (в работе) — Fix the six regressions confirmed by the read-only audit of c811bbd: voice write authorization before provider work and nonblocking persistence, consistent ZIP export, dashboard duplicate capture and recent-insight errors, bounded Analyze status requests. Add reproducing regressions and fix concrete closely related defects found during implementation. Preserve existing product semantics and quotas; no migrations, billing, provider-budget changes, production dependencies or deployment.. Сейчас: Fix confirmed audit regressions on an isolated branch; prepare exact-scope regression tests and independent review.
2. `WEB-002` (на проверке) — Add a Subscription section to Settings with Free, Pro and Team descriptions; grey Current for the current Free tier and blue Buy actions. Connect Pro Buy to official Paddle.js Sandbox overlay using public env placeholders and price pri_01m3y1nvmgw2avt60bz87161c2, quantity 1, authenticated email and customData.userId. Enforce sandbox-only tokens, single initialization and checkout locking, localized recoverable errors, existing design/auth preservation and frontend checks. Team stays explicitly unconfigured until a separate Sandbox price exists. No Live, server API key, webhooks, entitlement/DB changes, portal, cancellation or deployment.. Условие: Owner requested merge and deployment on 2026-10-02. PR32 merged and deployed to https://flare4u.tech/settings; Paddle remains Sandbox. Actual signed-in checkout/trial/payment verification is pending a Flare session; no paid access or plan DB changes.
3. `OPS-001` (на проверке) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Условие: Review redacted runtime/staging decision and evidence record; Vova selection/acceptance and sanitized inventory remain pending. Do not mark done or authorize rollout from public probes.

## В работе

- `API-003` (в работе) — Fix the six regressions confirmed by the read-only audit of c811bbd: voice write authorization before provider work and nonblocking persistence, consistent ZIP export, dashboard duplicate capture and recent-insight errors, bounded Analyze status requests. Add reproducing regressions and fix concrete closely related defects found during implementation. Preserve existing product semantics and quotas; no migrations, billing, provider-budget changes, production dependencies or deployment.. Сейчас: Fix confirmed audit regressions on an isolated branch; prepare exact-scope regression tests and independent review.; владелец: Fedor / Codex / API-003

## На проверке

- `WEB-002` (на проверке) — Add a Subscription section to Settings with Free, Pro and Team descriptions; grey Current for the current Free tier and blue Buy actions. Connect Pro Buy to official Paddle.js Sandbox overlay using public env placeholders and price pri_01m3y1nvmgw2avt60bz87161c2, quantity 1, authenticated email and customData.userId. Enforce sandbox-only tokens, single initialization and checkout locking, localized recoverable errors, existing design/auth preservation and frontend checks. Team stays explicitly unconfigured until a separate Sandbox price exists. No Live, server API key, webhooks, entitlement/DB changes, portal, cancellation or deployment.. Условие: Owner requested merge and deployment on 2026-10-02. PR32 merged and deployed to https://flare4u.tech/settings; Paddle remains Sandbox. Actual signed-in checkout/trial/payment verification is pending a Flare session; no paid access or plan DB changes.; владелец: Vova / Codex / WEB-002
- `OPS-001` (на проверке) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Условие: Review redacted runtime/staging decision and evidence record; Vova selection/acceptance and sanitized inventory remain pending. Do not mark done or authorize rollout from public probes.; владелец: Vova / OPS decision owner

## Блокеры

- `OPS-002` (требуется информация) — Activate workspace-wide Paddle Sandbox billing from reviewed PR36 on existing Flare Azure resources. Verify updated integration checks, coordinate merge, record backup/PITR and rollback boundaries, apply migration0021 through a controlled full checkout, deploy matching API/worker/web artifacts, save only Sandbox notification secret using existing server secret mechanism, and verify real Sandbox lifecycle. No Live, new paid resources, security weakening, foreign feature branches or premium quota changes.. Условие: Operator login is required in the open Paddle Sandbox tab for the account containing Flare Pro. Resume after login to configure the Sandbox destination, validate the documented recovery candidate, then perform coordinated migration/deployment and real checkout lifecycle smoke. Code acceptance/build is complete; Azure activation is not. Published OPS branch task/ops-002-paddle-activation-20261005 HEADa28b49ac6731e07c2bff0ea11a2a190eab3fb0e7; preserve worktree and private preflight archives.; владелец: Vova / Codex / OPS-002
- `ARCH-002` (требуется информация) — Future Project Memory implementation after budget approval: layered section/document characteristics, lexical-first retrieval, explicit counterevidence/completion lane, original evidence grounding and lifecycle/evaluation. Embeddings deferred. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#arch-002. This task currently authorizes no automatic enrichment implementation or provider calls.. Условие: WAITING: responsible enrichment-budget owner must supply approved entitlement/onboarding credit, rolling/day and workspace/global Groq ceilings, concurrency, paid/free behavior, numeric limits and rollout policy. Record approval, coordinate shared/migration scopes and fresh main before moving to next or claim. Planned future envelope: memory modules, bounded Analyze/context adapters, versioned schema/worker capabilities, tests and docs/implementation/ARCH-002/; no scope activated now.; владелец: ARCH / unassigned; Groq budget decision owner pending; зависит от: ARCH-001

## Вопросы пользователю

- Немедленного решения пользователя не требуется.

## Предупреждения

- API-003: ещё не записаны опубликованная ветка и область файлов.
