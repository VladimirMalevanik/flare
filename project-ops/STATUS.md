# СТАТУС ПРОЕКТА

> Этот файл генерирует `task-sync`; вручную его не редактируют.

Сформировано: `2026-10-04T05:13:00Z`
Последнее обновление работы: `2026-10-04T05:13:00Z`
Снимок состояния: `sha256:cf695f417635daca65fbbe56a3bb3c52c690fbc56da7199930b78ff56274e48b`

## Ближайшая цель

[Prepare Flare for safe parallel development and then implement scalable imports, Project Memory improvements, and acquisition attribution through separately claimed tasks.](NOW.md)

Критерий готовности: Coordination is ready when root AGENTS.md leads a fresh agent to AGENT_SETUP.md, task-sync v0.1.0 reads the published shared state, render-status and verify-snapshot pass, doctor succeeds, and the branch, scope, overlap, and acceptance rules are documented. Product work requires separate task-specific acceptance and evidence.

## Ближайшие шаги (не более пяти)

1. `WEB-003` (на проверке) — Improve existing Flare design: accessible drop/select ZIP dialog for Notion and Obsidian, real package/file progress and compact All/not-added report; consistent language control across public/auth/app pages; reference-grounded same-palette landing with honest product demonstration and restrained accessible motion.. Условие: Completed WEB-003 at 681714a: original landing wording and palette retained, unified accessible menus and Vault confirmation, ZIP picker and real file progress/report. Human approved main integration on 2026-10-04; ready to merge PR37.; зависит от: DATA-002, GROWTH-002
2. `API-001` (на проверке) — Implement Paddle Sandbox signed webhooks, durable ordered/deduplicated subscription state and authoritative workspace-wide Pro entitlement during trialing/active subscriptions. Add authenticated server-bound checkout intents, tenant-safe persistence, truthful Subscription status refresh and backend/frontend regression/security tests. Preserve auth, design, daily Analyze limits and Sandbox-only checkout. No Live, cancellation portal, new premium quota policy, production secret access or deployment.. Условие: Review PR36 at319a91de9f38ebbfa406fd92ad77c12b1415786c: signed Paddle Sandbox webhooks, durable workspace subscription state and Pro entitlement for all members. Matching0021/API/web rollout and Sandbox endpoint-secret setup plus real delivery smoke remain separate activation; no Live or deployment performed.; зависит от: GROWTH-002
3. `WEB-002` (на проверке) — Add a Subscription section to Settings with Free, Pro and Team descriptions; grey Current for the current Free tier and blue Buy actions. Connect Pro Buy to official Paddle.js Sandbox overlay using public env placeholders and price pri_01m3y1nvmgw2avt60bz87161c2, quantity 1, authenticated email and customData.userId. Enforce sandbox-only tokens, single initialization and checkout locking, localized recoverable errors, existing design/auth preservation and frontend checks. Team stays explicitly unconfigured until a separate Sandbox price exists. No Live, server API key, webhooks, entitlement/DB changes, portal, cancellation or deployment.. Условие: Owner requested merge and deployment on 2026-10-02. PR32 merged and deployed to https://flare4u.tech/settings; Paddle remains Sandbox. Actual signed-in checkout/trial/payment verification is pending a Flare session; no paid access or plan DB changes.
4. `OPS-001` (на проверке) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Условие: Review redacted runtime/staging decision and evidence record; Vova selection/acceptance and sanitized inventory remain pending. Do not mark done or authorize rollout from public probes.

## В работе

Нет.

## На проверке

- `WEB-003` (на проверке) — Improve existing Flare design: accessible drop/select ZIP dialog for Notion and Obsidian, real package/file progress and compact All/not-added report; consistent language control across public/auth/app pages; reference-grounded same-palette landing with honest product demonstration and restrained accessible motion.. Условие: Completed WEB-003 at 681714a: original landing wording and palette retained, unified accessible menus and Vault confirmation, ZIP picker and real file progress/report. Human approved main integration on 2026-10-04; ready to merge PR37.; владелец: Fedor / Codex Design / WEB-003; зависит от: DATA-002, GROWTH-002
- `API-001` (на проверке) — Implement Paddle Sandbox signed webhooks, durable ordered/deduplicated subscription state and authoritative workspace-wide Pro entitlement during trialing/active subscriptions. Add authenticated server-bound checkout intents, tenant-safe persistence, truthful Subscription status refresh and backend/frontend regression/security tests. Preserve auth, design, daily Analyze limits and Sandbox-only checkout. No Live, cancellation portal, new premium quota policy, production secret access or deployment.. Условие: Review PR36 at319a91de9f38ebbfa406fd92ad77c12b1415786c: signed Paddle Sandbox webhooks, durable workspace subscription state and Pro entitlement for all members. Matching0021/API/web rollout and Sandbox endpoint-secret setup plus real delivery smoke remain separate activation; no Live or deployment performed.; владелец: Vova / product owner; зависит от: GROWTH-002
- `WEB-002` (на проверке) — Add a Subscription section to Settings with Free, Pro and Team descriptions; grey Current for the current Free tier and blue Buy actions. Connect Pro Buy to official Paddle.js Sandbox overlay using public env placeholders and price pri_01m3y1nvmgw2avt60bz87161c2, quantity 1, authenticated email and customData.userId. Enforce sandbox-only tokens, single initialization and checkout locking, localized recoverable errors, existing design/auth preservation and frontend checks. Team stays explicitly unconfigured until a separate Sandbox price exists. No Live, server API key, webhooks, entitlement/DB changes, portal, cancellation or deployment.. Условие: Owner requested merge and deployment on 2026-10-02. PR32 merged and deployed to https://flare4u.tech/settings; Paddle remains Sandbox. Actual signed-in checkout/trial/payment verification is pending a Flare session; no paid access or plan DB changes.; владелец: Vova / Codex / WEB-002
- `OPS-001` (на проверке) — Resolve production staging service/upload path, API-worker storage reachability, worker isolation/resources, storage identity/network/CORS, physical ZIP deletion/retention and monitoring/load-test environment. Publish dated redacted operator decisions/evidence; no provisioning. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#ops-001.. Условие: Review redacted runtime/staging decision and evidence record; Vova selection/acceptance and sanitized inventory remain pending. Do not mark done or authorize rollout from public probes.; владелец: Vova / OPS decision owner

## Блокеры

- `ARCH-002` (требуется информация) — Future Project Memory implementation after budget approval: layered section/document characteristics, lexical-first retrieval, explicit counterevidence/completion lane, original evidence grounding and lifecycle/evaluation. Embeddings deferred. Contract: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#arch-002. This task currently authorizes no automatic enrichment implementation or provider calls.. Условие: WAITING: responsible enrichment-budget owner must supply approved entitlement/onboarding credit, rolling/day and workspace/global Groq ceilings, concurrency, paid/free behavior, numeric limits and rollout policy. Record approval, coordinate shared/migration scopes and fresh main before moving to next or claim. Planned future envelope: memory modules, bounded Analyze/context adapters, versioned schema/worker capabilities, tests and docs/implementation/ARCH-002/; no scope activated now.; владелец: ARCH / unassigned; Groq budget decision owner pending; зависит от: ARCH-001

## Вопросы пользователю

- Немедленного решения пользователя не требуется.

## Предупреждения

Нет.
