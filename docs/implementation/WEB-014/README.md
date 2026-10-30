# WEB-014 — first-save guidance and truthful Settings

The owner requested fixes from the 30 October CJM. This unit addresses F01, F03,
F04 and F05 without changing analysis admission, generation, quotas or data expiry.

## Reference lock

Primary target: existing Flare Capture confirmation and Settings rows. Preserve
the established surface, typography, blue navigation accent, borders and radii.
Secondary references: existing Flares schedule statuses and Auth form recovery
links. Refero craft guidance supplies live feedback, visible focus, readable copy,
and enough time to act. No new imagery, decorative animation or dependency.

| Decision | Reference / role | Reason |
| --- | --- | --- |
| Saved title remains independent of schedule lookup | Existing Capture toast | A failed status read must not imply the note failed to save |
| Actual off/on/date/unavailable copy and Settings link | Existing Flares status | Explain the next step without enabling or starting analysis |
| Eight-second toast, paused while hovered/focused | Refero feedback/focus craft | Give time to read and follow the new action |
| Remove inactive controls; retain stored legacy values | Existing Settings rows, CJM F04/F05 | Avoid promising notifications or automatic deletion that have no consumer |
| Project-bound links and full project navigation | Existing Team helper | Preserve workspace isolation and fence old requests |

The schedule read is bounded to four seconds, aborted on unmount, and late results
cannot update the removed view. The saved note remains accessible during loading
or failure. The Settings anchor opens the existing schedule rather than a new flow.
Email notifications remain a real separate server-backed preference. No existing
notes, local legacy preferences or retention policy are modified or deleted.

When preparation may already have happened, the confirmation warns that newly
added content may wait for the following run. The comparison uses the time of the
schedule response, so a re-render cannot silently change the displayed promise.

## Local validation

- 429 frontend tests: 428 pass; the existing public-build-variable fixture cannot
  read the deliberately excluded `.env.example` in this secret-free checkout.
  No test was skipped or weakened. The unchanged CI checkout supplies that fixture.
- ESLint and exact locked production build are required in CI. The reused local
  dependency tree lacks the existing Application Insights SDK, so its local build
  failure is an environment limitation, not a successful production build.
- Rendered actual components in an explicitly labelled synthetic-data fixture:
  desktop light and 390px mobile dark; schedule off, on, unavailable; English and
  Spanish; keyboard language selection. At 390px the document remains 390px wide
  and the 358px confirmation stays within 16px side margins.
- The fixture alone substitutes disabled telemetry because its reused dependency
  tree lacks that SDK. It does not validate live authentication, billing, mail or
  provider delivery. No real account or production write was used.

Implementation follows React's documented [Effect cleanup](https://react.dev/reference/react/useEffect).
Behavior tests and rendered browser checks are recorded in the task/PR evidence.
