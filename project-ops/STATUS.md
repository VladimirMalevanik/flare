# СТАТУС ПРОЕКТА

> Этот файл генерирует `task-sync`; вручную его не редактируют.

Сформировано: `2026-10-02T07:03:59Z`
Последнее обновление работы: `2026-10-02T07:03:59Z`
Снимок состояния: `sha256:9a7ef9dc7504d3d2056984c114bff305183592c90f0e13e5090dae3a6e77a3f1`

## Ближайшая цель

[Prepare Flare for safe parallel development and then implement scalable imports, Project Memory improvements, and acquisition attribution through separately claimed tasks.](NOW.md)

Критерий готовности: Coordination is ready when root AGENTS.md leads a fresh agent to AGENT_SETUP.md, task-sync v0.1.0 reads the published shared state, render-status and verify-snapshot pass, doctor succeeds, and the branch, scope, overlap, and acceptance rules are documented. Product work requires separate task-specific acceptance and evidence.

## Ближайшие шаги (не более пяти)

1. `DATA-001` (будем брать) — Async package ingestion architecture. A technically evidenced implementation contract for one-time asynchronous Notion and Obsidian ZIP onboarding imports. Requirements: Product decisions: initial Notion integration is ZIP import, not OAuth; initial Obsidian integration is ZIP import, not automatic local/plugin sync; primarily one-time project onboarding; ongoing synchronization/reconciliation is not the current requirement; asynchronous processing; independently configurable limits tunable after load tests; images are not analyzed in version one; original ZIP needs no long-term retention after successful processing; import must not automatically trigger normal Analyze. Cover upload/staging lifecycle and safe ZIP inspection/extraction, zip bombs, path traversal, symlinks, encrypted archives, expanded-size and compressed-size limits, file-count and individual-file limits, nesting/depth and processing-time limits, workspace storage quota, concurrent-import quota, cancellation, retry/restart/checkpoints, and idempotent retry of the same upload. Cover Notion export topology, Obsidian vault topology, preserved relative paths and provenance, supported text formats, unsupported assets reporting, and PDF/audio/other non-image attachments as an explicit open question. Cover package/file progress, partial-success versus atomic-publication options, needed schema/jobs/migrations as design only, worker architecture, Vault implications, cleanup of the staged archive after processing, and Azure/storage/runtime requirements requiring Vova's decision. Do not select arbitrary production limit numbers. Bounded local measurements may establish evidenced ranges, but final tuning stays configurable. Record method, input size, results, and limitations for any measurements. Own ingestion, publication, progress, and staging lifecycle design. Define the boundary to downstream enrichment, but leave AI enrichment, retrieval, and provider budgets to ARCH-001. Research does not require completion of ARCH-001. Write scope is only docs/research/DATA-001/ for the report and supporting research artifacts. Product code/configuration/migrations are read-only; no implementation or deployment. Claim your own task, use your own clean branch/worktree, publish scope through task-sync, re-check active tasks before editing or expanding scope, and stop/coordinate on semantic or file overlap. Acceptance: publish an evidenced report in docs/research/DATA-001/report.md with exact repository SHA, current primary documentation, contract alternatives, explicit open questions, proposed validation/load-test plan, and decisions reserved for Vova. Move to review with the report/branch or PR, SHA, and checks when research is complete; do not mark done without confirmed acceptance.. Условие: Ready for an independent research/design agent; unclaimed and no dependencies. Planned write scope: docs/research/DATA-001/; repository product code is read-only. Claim first, publish your own branch and scope, re-check active tasks, and stop on overlap.

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
