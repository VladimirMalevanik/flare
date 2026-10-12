# WEB-010 — Settings spacing and copy

The owner screenshots show two concrete defects: the browser analytics action
runs into the campaign-measurement heading, and the subscription retry button
runs into the error notice. Long attribution paragraphs also span the entire card.

The UI patch is `a52f53c68256ee4de3fb69828558174d237e64c3` on
`task/web-010-settings-polish-20261013`, reviewed in
[PR 59](https://github.com/VladimirMalevanik/flare/pull/59).

## Reference lock

Use the existing Flare Settings design and the owner's supplied screenshots.
Refero typography craft informs grouping, consistent vertical rhythm and bounded
reading width; frontend-design and copy-edit guide implementation and wording.
Keep the existing font, canvas/surface/divider/accent roles, buttons and menus.
No new font, icon, dependency, decorative surface or product flow.

| Decision | Evidence and purpose |
| --- | --- |
| Separate privacy groups | Screenshot 1 shows adjacent unrelated controls; add 20px group padding and an existing divider |
| Website analytics heading | Make browser analytics distinct from account link measurement |
| Reading width 68ch | Refero typography guide recommends bounded prose; avoid full-card paragraphs |
| Shorter account wording | Preserve account-only withdrawal, untouched notes/Flares/account and separate browser analytics |
| Feedback/action gap 12px | Screenshot 2 shows the retry touching the alert; group them without altering error handling |
| Expanded paragraph gap 10px | Mobile inspection found adjacent paragraphs without separation |
| Wrap schedule feedback | Mobile 320px inspection found the status squeezed beside the button |

Durations remain seven days for the link cookie and ninety days for linked
measurement. General consent/measurement notice text remains unchanged; only
account Settings uses the shorter retention line. No consent choices, tracking,
withdrawal, billing, quotas or backend behavior changed.

## Checks and local preview

- Main-based patch: 294 existing frontend tests and ESLint passed locally.
- [Main standalone build](https://github.com/VladimirMalevanik/flare/actions/runs/38318666932) passed at a52f53c.
- [Main code CI](https://github.com/VladimirMalevanik/flare/actions/runs/38318648275): all frontend and both backend profile jobs passed.
- Isolated Sources preview: source 16703c6 plus the same two UI commits, final
  `d6cfb1cf7ffc1b1cd60cfed55779546141a4816f`; [standalone build](https://github.com/VladimirMalevanik/flare/actions/runs/38318665038) passed.
- [Sources integration CI](https://github.com/VladimirMalevanik/flare/actions/runs/38318664215) also passed all jobs.
- The patch applies cleanly to Team ca58655 (`git apply --check` only). The Team
  and Sources author branches/worktrees were not edited.

Real browser verification at [localhost 8425 Settings](http://localhost:8425/settings):
separate privacy headings/dividers; readable account copy; open/close analytics
choices; unchanged selected consent; retry retains the real synthetic-server
billing error with a 12px action gap. At 320×844, document width equals viewport
width 320px, nested analytics paragraphs have 10px separation, and schedule status
uses a full row above the action. Desktop spacing was also inspected visually.
The viewport override was reset and the Settings tab retained.

Screenshots are saved in the local project mirror under
`outputs/settings-qa/desktop-privacy.jpg`, `desktop-billing.jpg`,
`mobile-analytics.jpg` and `mobile-billing.jpg`.
The preview artifact SHA-256 is
`d6b31fba331a381bbe460c55d46a95a8e766ba2b88a9b9bc161c2c41250d1e5a`.
The extracted local artifact routes API calls to the existing synthetic
127.0.0.1:8426 service; production configuration in the repository is unchanged.
The demo's unavailable subscription/schedule responses are test-server behavior,
not hidden or presented as a successful real provider connection.

No production deployment or product main merge was performed. Fedor's visual
acceptance is pending. Merge this UI patch normally with the existing feature
PRs; do not replace their backend or migration implementation with the preview.
