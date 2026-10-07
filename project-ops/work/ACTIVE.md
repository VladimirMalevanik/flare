# active

| ID | Ожидаемый результат | Владелец | Состояние | Зависит от | Обновлено UTC | Подтверждение |
|---|---|---|---|---|---|---|
| API-004 | Fix owner-reported repeated Flare sign-in: persist a bounded secure session across browser restarts and return already authenticated users to their workspace. Preserve logout, revocation, verification/legal gates, cross-workspace access and billing. Add meaningful backend/frontend/browser regressions; integrate and deploy the scoped fix on existing Azure services with readiness and rollback verification. No new paid resources, secrets in source, migrations or unrelated feature changes. | Vova / Codex / API-004 | ветка=—; base=—; HEAD=—; область=—; действие=Audit persistent cookie, idle expiry and signed-in entry routing; reproduce regression before minimal fix. | — | 2026-10-07T08:45:50Z | User request in current chat; reproduce session/routing behavior, tested PR, exact-source CI and Azure smoke after deployment. |
