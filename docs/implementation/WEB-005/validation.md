# WEB-005 validation

2026-10-05. Implementation is a local review candidate. No design merge or deployment is authorized by this task.

- 163 frontend tests pass, including motion lifecycle, once-only reveals, reduced-motion changes, hidden-tab pausing, missing observer fallback and cleanup after queued observer delivery.
- ESLint and production build/type checks pass. The preview build uses the existing local API on 8412, the real API provider and disabled Next telemetry.
- Header and hero JSX are byte-for-byte equal to the accepted baseline `9346a9ab75eb4820d1111c4a226d9632ffce0a36`. Pre-WEB-005 landing CSS is retained. Production dependencies and lockfiles are unchanged.
- EN and ES server responses contain restored outcome, comparison, Vault spheres and annotation markup. The visible pause control was removed after Fedor's review. Original link-cover bytes are preserved.
- HTTP checks confirm `/sources`, `/settings` and `/vault` return 200 without a login redirect, using the existing synthetic preview workspace.
- The old local API session returned 401 before these changes. Restarting only its existing preview wrapper restored 200 for the same workspace. No database reset, worker restart, real provider call or production change was performed.

Independent source review found two issues, now fixed: narrow-layout label overlap with the Vault center and an animation shorthand overriding the ribbon's paused state. The inner radius now has a safe responsive gap; shared orbit timing maintains category separation; the paused rule follows all animation shorthands. Review found no remaining confirmed P1/P2 source issues.

**Browser visual, keyboard, mobile-layout and actual frame-motion checks remain unverified.** CUA denied both the reference demo and localhost because mandatory browser policy verification was unavailable. Reconnecting the tool did not resolve it. No alternate browser/control path was used to bypass that policy, and no screenshot or pixel-quality claim is made.

Fedor's follow-up also corrects the anchor geometry: each rotating anchor has zero dimensions; the counter-rotating box contains only the sphere, and its label is absolutely positioned. Shared inset variables tie visible ring radii to motion tracks, widened slightly. The ribbon direction duration is 8 seconds instead of 18, with a modestly wider transform range.

For visual acceptance on `http://127.0.0.1:8411/`: scroll to Vault and watch sphere centers follow the ring lines while labels stay upright; continue to the faster blue ribbon, restored comparison and underline. Check English/Spanish and a narrow window. The previous interactive sample remains available through the unchanged Demo navigation link. With reduced motion enabled, the composition should remain static. There is no pause button.

Machine evidence is stored outside the source tree in the owned `evidence/web005-landing-20261005/` directory: frontend logs, HTTP candidate checks, preservation checks and independent research/review reports. Browser verification must be completed before treating this as visually accepted.
