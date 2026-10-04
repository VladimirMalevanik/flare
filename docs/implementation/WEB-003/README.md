# WEB-003 — local design review

ZIP import now starts from a drop/select dialog shared by Notion and Obsidian.
Choosing a valid ZIP closes the picker and starts the existing asynchronous import.
Progress reflects actual file checks; 100% checked still waits for publication.
Compact Checked / All / Failed counters replace redundant status boxes. Failed
includes skipped and otherwise unpublished files. The report opens full paths and
actual reasons and supports paged results. Duplicate uploads still resolve to the
canonical receipt without adding duplicate sources. Cancellation, retry and explicit
Analyze contracts remain unchanged.

Language, timezone, data-retention and GitHub repository controls share a Flare menu
with selected checks, keyboard/typeahead, Escape, mobile placement and top-layer
layering inside modal navigation. Locale persistence stays in the existing provider.
Vault deletion uses explicit in-app confirmation: Cancel, Escape and backdrop preserve
the item; duplicate pending requests are blocked and failures remain recoverable.
Dialogs restore launcher focus. Mobile close targets and focus rings are improved.
Native time parsing and Voice behavior are preserved.

The landing preserves the original centered “Your notes go quiet. Flare doesn't.”
hero, its exact explanatory sentence, Inter and the existing palette. Numbered labels,
extra marketing actions, decorative graphs/counts, invented glyphs, comparative promises
and SQL/HTTP jargon are removed. Alignment, spacing, type hierarchy and restrained
motion refine that foundation. Examples are visibly samples, reuse the application's
icons, and reveal matching sources. Capture/Vault/Analyze and filters operate locally.
See [design lock](design-lock.md) for the references and copy decisions.

## Verification

- Frontend suite: 158/158 passed, including ZIP state/pagination, locale persistence,
  source selection, sample evidence, menu choices and deletion confirmation.
- ESLint and TypeScript passed with no warnings/errors.
- Browser checks: desktop/mobile, English/Spanish, light/dark, reduced motion;
  keyboard, nested Escape/focus, viewport placement and long timezone list.
- The existing 60-file ZIP receipt and a repeated upload were checked with the local
  API/worker. No duplicate sources were added. All opened 60 actual report entries;
  Failed correctly showed no omitted files. Earlier separate worker fixtures covered
  mixed supported/skipped files. No live Analyze/provider was invoked.
- Production build and final release evidence are recorded in the external operator
  WEB-003 evidence directory after completion.

## Review boundaries

Only WEB-003's owned task worktree and delegated frontend paths were edited. Fresh
context at 679894d94245dd3f6e1701ba919dd1f9e8f9abeb showed only WEB-003 active. Other
tasks and the original dirty checkout remain untouched. No dependency, backend,
migration, billing, Voice, credential, production or analytics-policy change.

The user explicitly prohibited main pushes after the initial scope claim. Further
task-sync mutations publish main and are therefore deferred. Expanded menu scope and
handoff are recorded locally and on the task branch. No merge, acceptance or task
completion is asserted. The localhost preview uses an external synthetic-only
authentication wrapper and isolated database; production authentication is unchanged.
