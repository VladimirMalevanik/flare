# Team: shared notes and shared Flares

The owner clarified on 13 October 2026 that Team is shared project context, not a task manager. This corrects the task-oriented interface shipped in API-006/API-007.

## Product behavior

- Team opens shared notes by default. Add a note uses the existing Capture editor; Open Vault uses the existing shared note store and version-conflict protections.
- All explicit Team navigation stays in the selected project: Vault items, Sources, Flares and analysis settings. Membership/invitations remain in a secondary Members view.
- Notes and imported context in the Team workspace participate in the existing scheduled workspace analysis. Members read the same Flare feed and its original source notes. The quota is per project, not per participant.
- Personal Vault context is never copied automatically or included in Team analysis. Removing a member preserves their saved shared notes.
- Server-authenticated name/identity are recorded for new manual notes, voice transcripts and single-text-file imports. A colleague's edit preserves the original creator; duplicate imports retain the original receipt's author. The HTTP request cannot supply author/createdBy. Historical and asynchronous provider/import snapshots without a known creator stay unattributed; no author is fabricated.
- Viewer/expired-license projects remain readable; new writes still require an editor/owner and a current Team license. Project, member, document and UTF-8 content limits are unchanged.
- Task controls, task fetching/export and task-specific client types/styles are removed. Existing task records and server compatibility routes are retained without a destructive data migration.

## Validation

`test_team_shared_notes.py` exercises real restricted PostgreSQL and verified synthetic accounts: two members create notes, a colleague edits without changing the creator, spoofed author fields are rejected, viewer writes are denied and text import dedupe keeps its author.

The full scheduled pipeline test materializes one real project cycle, selects both members' notes, excludes a private note, runs analysis and Flare generation through deterministic fake AI adapters, and verifies one shared Flare with evidence from both notes. Owner/editor/viewer read the same result; an outsider receives404, personal Flare feeds remain empty, replay does not enqueue another analysis and one project daily quota is consumed. No provider calls or quota resets occur.

Frontend checks cover the default shared-note view, authenticated author display, all project-bound links, Capture entry, read-only states, honest empty/error states, bounded loading, invitation acknowledgement and the actual API adapter. Existing unrelated tests and scheduled-only behavior are retained. Local full-suite/CI/artifact results are recorded in PR/task evidence.

## Release and local review

Schema remains0024; no new migration, runtime dependency, external credential, production authorization, payment or real invitation. API-005 generation files stay untouched. OPS-006 activation gates remain: deploy matching integrated API/web/workers on existing resources, configure verified email and a genuine Team Sandbox price, and verify two consenting accounts sharing notes and reading the same scheduled Flare. Do not use the former task-demo flow as product acceptance.

The existing synthetic local Team preview on8427 is updated to this interface and retained for owner review. Synthetic fake-AI evidence verifies plumbing and access, not live model usefulness.
