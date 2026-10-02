# OPS — Infrastructure / release / coordination

## Scope

Coordination work touches root `AGENTS.md` and `project-ops/`. Release or infrastructure
tasks may touch workflows, Compose, and deployment documentation only within their
assigned scope. Production cloud, deployment, and network decisions belong to Vova.
Do not change `.codex/`, secrets, credentials, or another worktree.

## Work and validation

Follow `../AGENT_SETUP.md`, claim existing tasks before implementation, publish your
own branch and scope, and check active work. Keep task-sync out of runtime dependencies.
Use CLI state transitions. For authorized coordination-document changes preserve
schema headings, run `task-sync render-status`, `task-sync verify-snapshot`, and
`git diff --check`, inspect the complete diff, and fetch before publication. After
publishing, run `task-sync doctor --json` and `task-sync summary --json`.

## Stop and coordinate

Stop on semantic/file overlap, incompatible main protection, unexpected tracked
changes, uncertain push outcome, or rejected state writes. Never force-push or
weaken protection. Confirm actual acceptance before marking done; an artifact build
alone does not prove a production deployment.
