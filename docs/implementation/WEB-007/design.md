# Manual email composer

Designing a manual email form for Flare developers on desktop and mobile. The owner
asked for the familiar recipient / subject / body workflow and postponed sequences.

## Reference lock

Primary target: the current Flare Settings sections, capture sheet, and shared Dialog
at base `a08d349cff2c81c7d286192c12b30920cd3bd261`. Keep the existing font, surface,
thin borders, 16px sheet radius, and blue primary action. Reuse `--surface`, `--ink`,
`--inset`, `--line`, and `--accent`; introduce no new brand palette or dependencies.
Refero MCP is unavailable. Research uses this existing product target and bundled
Refero form/focus/accessibility craft guidance. No image assets are needed.

| Decision | Source | Purpose |
| --- | --- | --- |
| One Settings section and native modal | Flare Settings / capture / Dialog | Familiar entry, keyboard dismissal and focus return |
| Fixed From, then To, Subject, Message | Owner's normal-mail brief | Make sender and recipient intent explicit |
| Paste addresses separated by comma, semicolon or newline | Owner's recipient-window brief | Fast manual entry without a contact database |
| Separate recipient copies | Manual outreach requirement | Recipients do not see the other addresses |
| Keep draft in component memory when closing | Refero craft-details form guidance | Recover from dismissal without storing mail in browser storage |
| Pending controls and per-recipient outcomes | Refero craft-details + SMTP uncertainty | Prevent double submission and avoid false delivery claims |
| No automatic resend after unknown result | SMTP acknowledgement boundary | A lost response can follow acceptance |

Journey: authenticated Settings → server capability → Compose → validate → Send →
provider-accepted / failed / unknown outcomes. Only failed recipients remain eligible
for a deliberate retry; unknown results require checking the provider first.
