# СТАТУС ПРОЕКТА

> Этот файл генерирует `task-sync`; вручную его не редактируют.

Сформировано: `2026-10-02T08:05:19Z`
Последнее обновление работы: `2026-10-02T08:05:19Z`
Снимок состояния: `sha256:62fe7a0ec6543db256dda992abca1b1cb2863ec507531427eed7059d434fb0da`

## Ближайшая цель

[Prepare Flare for safe parallel development and then implement scalable imports, Project Memory improvements, and acquisition attribution through separately claimed tasks.](NOW.md)

Критерий готовности: Coordination is ready when root AGENTS.md leads a fresh agent to AGENT_SETUP.md, task-sync v0.1.0 reads the published shared state, render-status and verify-snapshot pass, doctor succeeds, and the branch, scope, overlap, and acceptance rules are documented. Product work requires separate task-specific acceptance and evidence.

## Ближайшие шаги (не более пяти)

1. `DATA-002` (будем брать) — Implement production-quality asynchronous one-time Notion/Obsidian ZIP onboarding, including package gate, tenant-safe jobs, provenance/idempotency, configurable reservations, local/test staging, recovery/cleanup and Vault integration. Full required contract and acceptance checks: docs/ONBOARDING_MEMORY_ATTRIBUTION_DECISIONS.md#data-002. No automatic Analyze or AI provider calls.. Условие: Unclaimed. Planned scope: import API/model/service/worker and local/test storage, publication-reader gate wiring, new linear migrations/schema/RLS/readiness, import tests/load harness, capture/Vault/source contracts and UI, docs/implementation/DATA-002/; exact path envelope in decision document. Fresh main/context and own published scope before edits. No production staging/topology choice or quota numbers; specific indispensable infra choices -> waiting. Production wiring awaits only required OPS-001 decisions.; зависит от: DATA-001

## В работе

Нет.

## На проверке

Нет.

## Блокеры

Нет.

## Вопросы пользователю

- Немедленного решения пользователя не требуется.

## Предупреждения

Нет.
