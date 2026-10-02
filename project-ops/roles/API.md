# API — Backend / integrations

## Scope

Backend API and integration work usually touches `backend/app/api/`, services,
AI adapters, and related tests. Declare exact paths. Persistence and migrations
overlap DATA; acquisition events overlap GROWTH; runtime/release changes overlap OPS.
Keep Voice API and transcript persistence unchanged unless explicitly authorized.

## Work and validation

Follow `../AGENT_SETUP.md`, claim first, use a clean task worktree, publish scope,
and inspect active tasks before editing. Preserve workspace isolation, source
provenance, and the shared daily Analyze contract. Run the backend tests relevant
to the assigned change and required repository checks. Use current primary docs
for external APIs. Ask before production dependency changes; never use source
text or credentials in telemetry or documentation queries.

## Stop and coordinate

Stop on shared contracts or files overlapping another task, new product decisions,
unapproved infrastructure changes, or rejected state writes. Confirm acceptance
before marking done.
