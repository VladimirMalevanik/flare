# Flare shared task protocol

Root `AGENTS.md` is the automatic entry point for agents entering this repository.
Read this file before product work. Human product decisions and explicit owner
instructions take priority over task-sync templates. A task assignment does not
authorize unrequested product decisions, production dependency changes, deployment,
or access to secrets.

## Pinned tool and installation

Use **task-sync-git 0.1.0**, installed from
`git+https://github.com/Nikkfh5/task-sync.git@v0.1.0`. It requires Python 3.11+ and Git.
Reuse a compatible isolated environment, or create one outside the checkout. For
example, from the repository root:

```sh
python3 -m venv ../flare-task-sync-venv
../flare-task-sync-venv/bin/python -m pip install "git+https://github.com/Nikkfh5/task-sync.git@v0.1.0"
. ../flare-task-sync-venv/bin/activate
```

Do not add task-sync to backend runtime dependencies or vendor its source. Installing
or upgrading the coordination tool is separate from Flare runtime dependencies.
All participants use the pinned version; upgrades require an explicit decision.

Version 0.1.0 uses `origin/main` and `project-ops/`. Read the pinned upstream
[README](https://github.com/Nikkfh5/task-sync/blob/v0.1.0/README.md),
[integration instructions](https://github.com/Nikkfh5/task-sync/blob/v0.1.0/docs/INTEGRATION.md),
and [command reference](https://github.com/Nikkfh5/task-sync/blob/v0.1.0/docs/COMMANDS.md)
for command details. General options precede commands:
`task-sync --repo <checkout-path> summary --json`.

## Shared state and authority

Task-sync reads fresh state from `origin/main`. Local board files may be stale even
after your own successful state command. Read `task-sync summary --json` and
`task-sync list --json`; do not pull, stash, reset, or switch another worktree to
read the board. A failed fetch is a stop condition, not permission to use cached state.

`create`, `claim`, `update`, `move`, `to-review`, and `finish` publish task-state
commits directly to main. They use a temporary worktree without changing the caller's
branch or dirty files. State commits remain separate from substantive product
branches. Task-sync does not run agents or merge product branches.

Normal push access to main is required for state commands. Do not weaken branch
protection to accommodate the tool. `doctor` checks schema, author identity, fetch,
and a dry-run push; it does not guarantee future server acceptance.

The human assigns the coordinator role and task IDs. If no task is assigned, stop
before product edits and ask the human coordinator for an assignment. Do not create
fictional tasks, invent completed work, or claim another person's active task.
An assigned coordinator creates tasks through the CLI with a verifiable expected
result, scope boundaries, owner, dependencies, and start condition.

## Before editing product code

1. Inspect status, HEAD, `origin/main`, and the worktree list. Fetch with
   `git fetch origin --prune`, then read `task-sync summary --json` and
   `task-sync list --json`. Leave existing dirty checkouts untouched.
2. Read `task-sync context <TASK-ID> --json`. From its single `base_sha`, read
   `task`, `active_tasks`, `now`, `role`, and every required linked document. For
   linked files use `git show <base_sha>:<path>`. This prevents mixing snapshots.
3. Successfully run
   `task-sync claim <TASK-ID> --owner "<person / agent / task ID>" --action "<next action>" --json`.
   Start only after exit code 0 and a confirmed push. Read the entire returned
   `required_context`; its `base_sha` is the published claim commit. `claim` accepts
   tasks in `next`, with dependencies completed in `done`.
4. Check every other active task for semantic overlap and file overlap. Treat an
   undeclared scope as unresolved: get its intended scope before editing. Overlap
   means stop and coordinate with the human coordinator and affected owner.
5. Create your own branch and clean worktree from the freshly fetched main, using
   a unique task branch. Never modify another agent's branch, worktree, index, or
   files. Publish the clean branch with an ordinary push before product edits.
6. From that clean, published branch, declare the intended paths using
   `task-sync update <TASK-ID> --from-state active --sync-branch --scope <path> --action "<next action>" --json`.
   Repeat `--scope` for multiple paths. Directories end in `/`; files use exact
   repository-relative paths. In v0.1.0, `--scope` is used with `--sync-branch`.
7. Re-read fresh context after publishing the scope and immediately before the
   first edit. Stop on newly visible overlap. Edit only within the declared scope
   and assigned result. Claims assign a task; they are not automatic file locks.

The direction guides describe likely areas, not exclusive ownership or permission
to edit every listed path. Cross-direction work needs explicit scope agreement.

## While working and handing off

Before expanding scope, fetch and re-read summary, list, and task context. Resolve
semantic or file overlap before expanding the declaration or editing additional
paths. Publish an updated scope from a clean branch with `update --sync-branch`.
If the expansion changes the expected result, refer it to the coordinator; do not
silently redefine an active task.

Commit and publish product changes on your task branch. After a substantive push,
record its published HEAD and current action through `update --sync-branch`. This
checks that the branch is clean, published, and within its declared file scope;
it does not detect semantic conflicts or merge the branch.

Run the checks required by the task and repository. Use `to-review` with the PR or
branch reference and actual validation evidence. Merge only under the owner's
instructions. Use `finish` only after acceptance is actually confirmed, recording
the accepted result, SHA or merged PR where applicable, and checks. The CLI records
your assertion; it does not verify acceptance. `review` and `waiting` are not done.

State transitions use task-sync commands whenever a command exists. Preserve the
schema-required headings and tables in NOW.md, QUESTIONS.md, and board files.
For an authorized objective, question, or instruction edit, run `render-status`
then `verify-snapshot` and publish the coordination documents together. Do not run
`init` over an existing board or manually edit tables to bypass a rejected command.

## Concurrent writes and failures

Never force-push, reset another worktree, overwrite unexpected tracked changes, or
silently resolve semantic conflicts. If main advances while preparing an ordinary
coordination commit, fetch, inspect the changes, and review integration before
publishing. Keep substantive product changes out of coordination state commits.

| Exit code | Meaning | Required response |
| --- | --- | --- |
| 0 | Successful operation | Read the returned snapshot or required context. |
| 2 | Invalid arguments, schema, state, or transition | Read context and correct the request. |
| 3 | Main changed before a state push | Re-read context and ownership; do not automatically replay or take another owner's claim. |
| 4 | Git, network, permissions, or environment failure | Inspect the remote state before deciding whether a write needs retrying. |

A network failure after push can have an unknown outcome. Read `show` or `context`
first: the commit may already exist. No automatic write retry, force-push, or manual
board conflict resolution is allowed. File and semantic overlap checks are agent
responsibilities; task-sync's stale-write rejection is not a substitute.

## Directions and final reports

Directions are configured in `task-sync.json`: ARCH, WEB, API, DATA, GROWTH, OPS.
Read `BOARD.md`, `NOW.md`, the assigned role, and fresh task context before work.
Production cloud, deployment, and network decisions belong to Vova. Product
architecture choices belong to the product owner.

In a handoff, report the task ID and actual state, result, scope, branch/PR and SHA,
checks, limitations, and condition for continuing. Do not claim acceptance that
has not happened.
