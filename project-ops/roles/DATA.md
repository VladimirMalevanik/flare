# DATA — Persistence / ingestion / Project Memory

## Scope

Likely areas are backend persistence models, ingestion and context services,
`backend/migrations/versions/`, and their tests. Declare exact paths and coordinate
shared API/UI contracts. A direction does not approve an import architecture or
large-context strategy; those require the product owner's choice.

## Work and validation

Follow `../AGENT_SETUP.md`, claim first, publish your own clean branch and scope,
and inspect all active work before editing. Verify current migration head and
coordinate migration ordering. Preserve workspace isolation, immutable versions,
historical citations, idempotency, and one manual or scheduled Analyze per workspace
local calendar day. Test the relevant persistence and ingestion invariants.

## Stop and coordinate

Stop on migration-chain or semantic/file overlap, unclear retention or identity
rules, unapproved architecture changes, or rejected state writes. Do not mark done
until task acceptance is confirmed.
