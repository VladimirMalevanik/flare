# WEB-009 — scheduled analysis only

Owner instruction on 2026-10-12: remove Analyze today and keep scheduled analysis.

The Flares header now reads the workspace schedule and daily status and links to
the existing Settings controls. No manual action component is mounted, so neither
the button nor its hidden gesture can request an analysis. Completed run changes
refresh the displayed Flares automatically. Disabled schedules, active processing,
failures and unavailable status have distinct English/Spanish messages. Reads are
abortable and bounded to 15 seconds; polling never overlaps. Settings retains its
existing time, timezone, permission and notification controls.

Authenticated public POST /analyze now returns 410 scheduled_analysis_only without
resolving AI configuration or creating jobs, cycles or quota reservations. Existing
body/header/origin/authentication validation remains. Historical GET run status
and internal historical-cycle compatibility remain; the scheduled worker, frozen
context, daily allowance and generation pipeline are unchanged. Regression tests
preserve historical quota/retention invariants with direct internal fixture calls
and verify that public manual requests cannot create work. Existing scheduled
worker end-to-end tests still exercise real scheduling and publication.

Reference lock: existing Flares header/analyze-action spacing, current button/link
styles and Settings schedule surface. Preserve palette, typography, density and
keyboard focus. Refero async-state/focus guidance informs truthful status and
semantic status announcements; no new visuals, dependencies or layout system.

New UI tests are colocated with insights-page and explicitly run by CI to avoid
writing the frontend/tests directory currently owned by active WEB-007. Existing
controller tests retain coverage of historical orchestration; that legacy action
is no longer mounted in the product. Acceptance and final checks are recorded in
the PR/task handoff. No production rollout or private configuration is performed.
The release owner must deploy both API and web from the accepted main revision;
the existing scheduler must be running and a workspace schedule enabled.
