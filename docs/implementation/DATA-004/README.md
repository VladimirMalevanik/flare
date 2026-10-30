# DATA-004 — imported note authors and source handoff

CJM F13: ZIP and selected-source publication omitted the trusted creator even
though the Vault already renders author information. A disconnected connection
also prevented a project owner from connecting their own account after its
previous owner left.

## Result

- New ZIP versions stamp the package requester ID and stored account display name.
- Source publication ignores incoming reserved author fields. The leased actor is
  the creator; subsequent sync versions keep the original stored display name.
- Existing active and historical note views fill missing display authors from
  their immutable first snapshot, a document's protected import-package pointer,
  or its first source snapshot's connection. A bounded private read returns only
  connection ID, creator ID and display name in the selected workspace, including
  former members. Viewers and read-only projects can read this provenance.
- Reads do not rewrite content, hashes, IDs, timestamps or historical snapshots.
  Truly unknown provenance stays unknown. Metadata is not an access-control rule.
- A project owner can connect their own account only after another user's source
  is fully disconnected. The old row is retired, its credentials, pending OAuth
  state and cursors are erased/fenced, and a fresh connection ID starts normal
  authorization and explicit selection consent. Saved notes retain their creator.
- Each workspace/provider still has exactly one current binding. Archived bindings
  preserve source-item provenance. Remote IDs from different accounts cannot
  overwrite each other. Reconnecting the same corpus under another binding can
  create another snapshot; cross-account dedupe is deliberately not guessed.
- Editors/viewers cannot reclaim another user's binding. Active foreign sources
  cannot be silently taken over. Private account labels remain private. Pending
  connection setup can be cancelled from the existing Sources card.

## Database and release

0028 follows0027. Released SQL snapshots are unchanged; checked patches preserve
installed function ownership, pinned search paths, ACLs and Team/worker guards.
A partial unique index replaces the old provider uniqueness constraint; retired
rows must remain disabled without credentials or cursors. Only the private function
owner gains SELECT(name); app/worker get no direct source-table privileges.
No dependencies, provider credentials, pricing, AI generation or retention policy
changed. New web, API and worker must be released together with schema0028. Do not
report deployment or external OAuth/SMTP acceptance based on this code change.

## Validation

Restricted PostgreSQL tests cover forged authors, original names on updates,
legacy current/history reads with no persisted changes, former-member provenance,
foreign-workspace/malformed/bounded lookup rejection, unknown manual metadata,
Notion/Obsidian Team imports and a second uploader's duplicate ZIP, owner handoff,
stale OAuth/worker writes, external-ID collisions and role/unique-index guards.
Existing source, import, Team, auth and item suites must remain green. Frontend
checks cover capability decoding, consent, cancellation and gated reconnect.
