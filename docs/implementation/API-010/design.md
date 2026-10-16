# Original source view

Reference lock: the existing Flare evidence panel and Vault item sheet accepted in API-008/API-009; owner screenshot of the same sheet. This is an extension of that UI, not a redesign. Refero craft guidance: explicit state, clear next action, existing focus-visible controls, restrained typography and truthful error text.

An evidence link carries both item and immutable document-version ID. The existing Vault sheet shows the exact saved content, original author, version number and saved date. A short notice identifies it as the version used for the Flare. Edit and delete are absent; Open current version is the sole primary footer action. Current source editing stays in the normal Vault view. Closing removes both item and version query parameters while preserving project/filter context. Late responses must not reopen or replace a different selected sheet.

Use existing sheet spacing, muted metadata, button and focus styles. Dates follow the selected UI locale. Unavailable/deleted/foreign versions produce a clear error without falling back silently to another version. Old evidence DTOs without a version ID keep the existing current-note link for rolling release compatibility. No new icon, illustration, animation or dependency is required for this UI.
