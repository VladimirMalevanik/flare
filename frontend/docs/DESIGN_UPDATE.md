# Cupertino Minimal update

The eight `*_cupertino_*_simplified` screens in `stitch_flare_context_intelligence_webapp.zip` are the visual references. Both Cupertino `DESIGN.md` files informed the tokens. The full, non-simplified screens are excluded from the implementation target.

Reference decisions:

- 240px sidebar, 40px floating capture capsule, 28px filter pills, 8px controls, 16px cards, and local Inter typography.
- One CSS token system owns light/dark surfaces, hairlines, accent, typography, and states. The dark Vault retains the reference's wide first card; the light Vault uses equal columns.
- The legacy capture reference contains a text area, attachment action, microphone, and submit toolbar, but no actual expanded floating island. The shared modal adapts those controls to the requested collapsed → expanded interaction and auto-detects notes/URLs.
- Mock counts reflect actual records rather than the reference's decorative 142/10 counters. A few demo narratives replace infrastructure-specific content. Confidence scores, notification sending, infrastructure panels, archive export, and team administration are not implemented.
- A consistent initials avatar and Heroicons replace reference portraits and Material Symbols. Settings omits profile-photo upload and workspace/team administration. Sources and notification preferences explicitly identify local/demo behavior.

Changed areas: shared shell/tokens, workspace state, modal/capture, Insights, Vault, new Sources/Settings routes, provider contracts and demo seeds. Existing capture storage is retained. Legacy Dashboard source remains in the repository but its route redirects to Insights.

Validation: lint, production build, isolated-browser tests for capture text/URL/file, persistence, search/filter/detail, evidence, theme switching, system theme, source settings, and mobile layouts. Physical microphone permission and real transcription require a manual/device or backend integration check.

Voice fallback was also verified: pending microphone permission → explicit demo voice memo → saved processing item with demo transcript. The test environment did not provide a usable audio device; actual recording is not claimed as verified.

## Changed and added files

```text
README.md
docs/ARCHITECTURE.md
docs/API_CONTRACT.md
docs/INTEGRATION.md
docs/PRODUCT.md
docs/DESIGN_UPDATE.md
public/fonts/OFL.txt
public/fonts/inter-latin.woff2
src/app/page.tsx
src/app/layout.tsx
src/app/globals.css
src/app/(flare)/dashboard/page.tsx
src/app/(flare)/settings/page.tsx
src/app/(flare)/sources/page.tsx
src/components/app-shell.tsx
src/components/icons.tsx
src/components/dialog.tsx
src/components/workspace-context.tsx
src/features/capture/capture.tsx
src/features/insights/insights-page.tsx
src/features/vault/vault-page.tsx
src/features/settings/settings-page.tsx
src/features/sources/sources-page.tsx
src/lib/data/api-provider.ts
src/lib/data/index.ts
src/lib/data/mock-provider.ts
src/lib/data/provider.ts
src/lib/data/types.ts
src/lib/storage/preferences.ts
src/mocks/cupertino.ts
src/mocks/sources.ts
```
