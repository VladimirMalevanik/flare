# Flare agent coordination

Before modifying product code:

1. Read `project-ops/AGENT_SETUP.md`.
2. Fetch fresh `origin/main` with `git fetch origin --prune`.
3. Read shared state with `task-sync summary --json`.
4. Work only from an assigned task ID; ask the human coordinator if none is assigned.
5. Read `task-sync context <TASK-ID> --json` and its required documents.
6. Successfully claim the task before changing product code.
7. Inspect all active tasks and their declared scopes for semantic and file overlap.
8. Use your own branch and clean worktree for substantive product work. Publish the
   branch and declare its scope through task-sync before editing.
9. Never modify another agent's branch, worktree, index, or files.
10. Before expanding scope, re-read shared state and coordinate any overlap.
11. Never force-push.
12. If another active task overlaps semantically or by file scope, stop and coordinate.

Task state lives under `project-ops/`. Use task-sync commands instead of manually
editing board state whenever a command exists. State commits are separate from
substantive product branches. Mark a task done only after acceptance is confirmed.

Human product decisions and explicit owner instructions take priority over
task-sync templates. Do not modify `.codex/` or access secrets without an explicit
owner request.
