# WEB-006 — Settings footer

The authenticated sidebar no longer has a language picker. Settings keeps the existing language menu. A labeled settings gear now sits beside the profile, using Flare’s existing Heroicons icon and button tokens. Both Funny preference rows were removed from Settings.

Reference lock: Fedor’s two screenshots from 2026-10-07 and the current sidebar/settings design system; preserve profile typography, theme tokens, rounded buttons and existing navigation. Gear target is 44 × 44 px. Long profile names truncate without moving it outside the sidebar. Public/auth language menus are outside this authenticated-footer change.

Product SHA: `4902654906e2bcac937dc54e1ae3cf9f4a2cff4c`.
Branch: `task/web-006-settings-footer-20261007`.

Validation:

- Local frontend: 215 tests passed; ESLint passed. Three new interaction regressions cover the gear threshold, current-route handling, mobile drawer and retained Settings controls. Existing persistence regression now verifies the legacy visible-mode preference does not enable the hidden mode.
- Exact-product GitHub checks [37598164474](https://github.com/VladimirMalevanik/flare/actions/runs/37598164474): frontend tests/lint/build and both backend database variants succeeded.
- Linux standalone build [37598165021](https://github.com/VladimirMalevanik/flare/actions/runs/37598165021): succeeded. ZIP SHA256 `86b4907019598bdf2fca7ad41853e867eeff58dd4bc9b6498fbcf955389572cd`.
- Playwright on that product build: first gear click navigates from Insights to Settings; 9 clicks leave the mode off, tenth keyboard activation enables it, reload retains it and ten more disable it. Same-route clicks prevent unnecessary navigation. Sidebar has zero language controls, Settings has one, both Funny rows are absent.
- Desktop 1440 × 900: dark and light themes verified. Mobile 390 × 844: gear target 44 × 44 px, drawer closes on gear navigation, no horizontal overflow. Existing keyboard focus and accessible Settings label retained.

Local preview: `http://localhost:8415/settings`, separate from previews on 8411 and 8413. Synthetic account/data only, existing isolated API on 8414. Local runtime overrides point API requests to that API and restrict CSP connect-src to self so the preview does not send analytics/payment traffic externally. Product source and dependency files are unchanged by these runtime overrides. The unconfigured local GitHub integration returns its existing 503; no uncaught application exception was observed during the completed interaction checks.

No backend, dependency, cloud, migration or deployment changes. Other tasks and shared checkout were left untouched. Product changes remain on the task branch awaiting acceptance; not merged to main.
