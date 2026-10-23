# Campaign link activity

The existing Flare Settings design is the visual target: its type, white/dark surfaces,
blue action accent, existing Select menus, borders, spacing and buttons remain in use.
Charts are native SVG and CSS; no production dependencies or decorative imagery.

References reviewed on 2026-10-23:
- https://plausible.io/docs/top-referrers — a shared date range and link/source drill-down.
- https://posthog.com/docs/web-analytics/dashboard — a time series above ranked breakdowns.
- Existing Flare Campaign links — internal owner capability, anonymous counts and link actions.

| Decision | Source | Role and reason |
| --- | --- | --- |
| Activity and Links views within existing Settings section | Existing Flare settings + Plausible report tabs | Keep the chart immediately visible; isolate creation and archive actions from reading data. |
| 7/30/90-day range and one link filter | Plausible UTM segmentation | Compare a shared period or inspect one campaign without another page. |
| Blue daily chart; ranked horizontal bars | PostHog trend/breakdown structure; Flare accent | Time is read left to right; link labels remain readable beside bars. |
| Coverage note and missing values before migration | Existing lifetime-only database | Never draw invented history as zero traffic. The first recorded day and today may be partial. |
| Recorded opens, not visitors or conversion | Existing public counter semantics | Repeat opens and bots count; registration attribution is a separate restricted system. |
| Native chart, keyboard day navigation and data table | Refero craft/accessibility | Expose the same values without hover, color recognition or SVG support. |

Scope: anonymous aggregate opens only. No new cookies, identities, user activity events,
registration attribution changes, third-party analytics, secrets or production rollout.
