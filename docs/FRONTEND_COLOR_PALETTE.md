# Flare Frontend Color Palette

Source: `origin/main` at `68b882dc1d18ab4fa7a38c24f52950618887d307`, verified against GitHub. Flare uses light and dark palettes with blue accents, neutral surfaces, and green, amber, and red status colors. Light is the default.

Opaque values below include RGB. Transparent colors preserve their original alpha rather than being flattened against an arbitrary background.

## Primary palette

| Role | Light | Dark | Token |
|---|---|---|---|
| Page background | `#FAF8FE` · RGB 250, 248, 254 | `#111215` · RGB 17, 18, 21 | `--canvas` |
| Surface | `#FFFFFF` · RGB 255, 255, 255 | `#1F1F23` · RGB 31, 31, 35 | `--surface` |
| Inset surface | `#F4F3F8` · RGB 244, 243, 248 | `#131417` · RGB 19, 20, 23 | `--inset` |
| Primary text | `#1D1D1F` · RGB 29, 29, 31 | `#F4F4F6` · RGB 244, 244, 246 | `--ink` |
| Secondary text | `#6E6E73` · RGB 110, 110, 115 | `#C0C7D5` · RGB 192, 199, 213 | `--secondary` |
| Border | `rgba(20, 25, 50, 0.1)` | `rgba(255, 255, 255, 0.09)` | `--line` |
| Primary accent | `#0071E3` · RGB 0, 113, 227 | `#2997FF` · RGB 41, 151, 255 | `--accent` |
| Accent text | `#0059B5` · RGB 0, 89, 181 | `#A3C9FF` · RGB 163, 201, 255 | `--accent-text` |
| Success | `#00A66B` · RGB 0, 166, 107 | `#47E266` · RGB 71, 226, 102 | `--green` |
| Warning | `#AC6200` · RGB 172, 98, 0 | `#FFB868` · RGB 255, 184, 104 | `--amber` |
| Error | `#DF2228` · RGB 223, 34, 40 | `#FFB4AB` · RGB 255, 180, 171 | `--red` |

## Full semantic palette

### Background

| Role | HEX / rgba | Current usage | Landing-page recommendation |
|---|---|---|---|
| Page background · `--canvas` | Light `#FAF8FE`; dark `#111215` | Body canvas | Use as the page canvas for the matching theme |
| Navigation background · `--sidebar` | Light `#F4F3F8`; dark `#1B1B1F` | Sidebar and mobile drawer | Use for persistent navigation or a distinct page band |

### Surfaces

| Role | HEX / rgba | Current usage | Landing-page recommendation |
|---|---|---|---|
| Primary surface · `--surface` | Light `#FFFFFF`; dark `#1F1F23` | Cards, dialogs, buttons, auth panels, toasts | Use for cards and feature panels |
| Inset surface · `--inset` | Light `#F4F3F8`; dark `#131417` | Inputs, quotes, attachments, badges | Use for recessed content and fields |
| Hover/active surface · `--hover` | Light `#E9E7ED`; dark `#292A2D` | Button hover, active navigation, tags, view toggles | Use for neutral hover and selected states |
| Floating surface · `--float` | Light `rgba(255, 255, 255, 0.88)`; dark `rgba(31, 31, 35, 0.9)` | Expanded Capture and recording island | Preserve alpha for floating, blurred UI only |
| Elevated surface | No dedicated opaque token | Dialogs reuse `--surface`; Capture uses `--float` | Reuse surface or float according to context |

### Text

| Role | HEX / rgba | Current usage | Landing-page recommendation |
|---|---|---|---|
| Primary text · `--ink` | Light `#1D1D1F`; dark `#F4F4F6` | Headings, body, form text | Use for headlines and main copy |
| Secondary text · `--secondary` | Light `#6E6E73`; dark `#C0C7D5` | Descriptions, metadata, `.muted`, inactive navigation | Use for supporting copy |
| Muted text · `--muted` | Light `#86868B`; dark `#929AA7` | Keyboard hints, including Vault's Esc hint | Reserve for tertiary annotations |
| Text on accent | `#FFFFFF` | Primary buttons, brand mark, switch thumb | Use on blue primary actions |
| Disabled text/control | Existing color at `opacity: 0.5` | Disabled buttons | Preserve the current opacity treatment |

### Borders

| Role | HEX / rgba | Current usage | Landing-page recommendation |
|---|---|---|---|
| Default border · `--line` | Light `rgba(20, 25, 50, 0.1)`; dark `rgba(255, 255, 255, 0.09)` | Cards, controls, navigation boundaries | Use for standard component borders |
| Subtle divider · `--divider` | Light `rgba(20, 25, 50, 0.06)`; dark `rgba(255, 255, 255, 0.05)` | Card footers, Settings separators | Use for internal separators |
| Strong/active border | `--accent`; active insight cards mix accent at 45% with `--line` | Selected filters, active cards, hover borders | Use accent for active state borders |
| Focus border/ring | `--accent` | General 2px focus outline; Vault search outline | Use the theme accent for keyboard focus |

### Brand / Accent

| Role | HEX / rgba | Current usage | Landing-page recommendation |
|---|---|---|---|
| Primary Flare accent · `--accent` | Light `#0071E3`; dark `#2997FF` | CTA fill, logo tile, waveforms, focus rings, selected borders | Use for primary CTAs and high-signal interaction |
| Accent text · `--accent-text` | Light `#0059B5`; dark `#A3C9FF` | Links, active navigation text, callout icons | Use for text links and accent copy |
| Accent wash · `--accent-wash` | Light `rgba(0, 113, 227, 0.09)`; dark `rgba(41, 151, 255, 0.12)` | Active counts, dark selected filters, syncing status | Use for subtle blue backgrounds |
| Linear integration color | `#6554FF` · RGB 101, 84, 255 | Linear source icon only | Keep integration-specific; do not promote to Flare accent |

The Capture orb is the notable product gradient:

```css
background: radial-gradient(
  circle at 32% 25%,
  #D7F3FF,
  #69BCFF 28%,
  var(--accent) 65%,
  #164B91
);
```

Its additional stops are `#D7F3FF` (RGB 215, 243, 255), `#69BCFF` (RGB 105, 188, 255), and `#164B91` (RGB 22, 75, 145). Keep these colors scoped to the orb.

### Status

| Role | HEX / rgba | Current usage | Landing-page recommendation |
|---|---|---|---|
| Success · `--green` | Light `#00A66B`; dark `#47E266` | Ready/connected badges, Vault dot, Recommendation Flares | Use for success and connected states |
| Warning · `--amber` | Light `#AC6200`; dark `#FFB868` | Warning Flares, disconnected status | Use for warnings and attention states |
| Error/danger · `--red` | Light `#DF2228`; dark `#FFB4AB` | Capture/auth/loading errors, error badges, Reminder Flares | Use for errors and destructive feedback |
| Informational | Accent text + accent wash | Blue callouts and syncing badges | Reuse the accent pair |
| Coming soon | Secondary text + hover surface | Sources badges | Use neutral styling for unavailable features |
| Disabled | Existing colors at `opacity: 0.5` | Disabled buttons | Do not introduce a separate disabled color |

Status badge backgrounds use the theme status color through `color-mix`: red at 7%, green at 8%, amber at 8%; red and green borders use 25%.

### Interactive

| Role | HEX / rgba | Current usage | Landing-page recommendation |
|---|---|---|---|
| Primary button | `--accent` + `#FFFFFF` | Primary actions; hover applies `filter: brightness(1.08)` | Reuse the existing brightness hover; there is no separate hover HEX |
| Secondary button | `--surface` + `--ink` + `--line`; hover `--hover` | Standard secondary actions | Use for lower-priority actions |
| Destructive button | No distinct palette | Disconnect currently uses the normal button style | Do not invent a destructive-button color |
| Links | `--accent-text`; ordinary anchors inherit text color | Text buttons, auth links, toast links | Use accent text for explicit action links |
| Active navigation | `--hover` + `--accent-text`; counts use `--accent-wash` | Current sidebar route | Reuse for selected navigation |
| Inputs | `--inset` + `--ink` + `--line` | Auth, Settings, Capture-related forms | Use the same field treatment |
| Selected filters | Light: `--accent` + `#FFFFFF`; dark: `--accent-wash` + `--accent-text` + accent border | Vault and Insights filters | Match the chosen theme exactly |

The Capture textarea uses a transparent background and removes its local focus outline. The Vault search uses `--surface` and places the accent focus outline on its wrapper.

## Landing-page shortlist

Use these 14 light-theme values to match Flare's default product palette. If the landing page supports dark mode, substitute the corresponding dark values from the tables above as a complete set.

| Role | HEX / rgba | Current Flare usage | Landing-page recommendation |
|---|---|---|---|
| Background | `#FAF8FE` | Page canvas | Main canvas |
| Surface | `#FFFFFF` | Cards, dialogs | Feature and content panels |
| Inset | `#F4F3F8` | Inputs, sidebar | Recessed areas |
| Hover | `#E9E7ED` | Hover/active controls | Hover and selected neutral surfaces |
| Border | `rgba(20, 25, 50, 0.1)` | Default borders | Preserve alpha |
| Text primary | `#1D1D1F` | Headings and body | Headlines and main copy |
| Text secondary | `#6E6E73` | Descriptions | Supporting copy |
| Text muted | `#86868B` | Keyboard hints | Small tertiary annotations |
| Accent | `#0071E3` | Primary actions | CTA fill and focus |
| Accent text | `#0059B5` | Links | Text links |
| Accent subtle | `rgba(0, 113, 227, 0.09)` | Selected accents | Subtle accent backgrounds |
| Success | `#00A66B` | Ready/connected | Success feedback |
| Warning | `#AC6200` | Warning Flares | Warning feedback |
| Danger | `#DF2228` | Errors | Error feedback |

## CSS variables

```css
:root {
  --flare-bg: #FAF8FE;
  --flare-surface: #FFFFFF;
  --flare-inset: #F4F3F8;
  --flare-hover: #E9E7ED;
  --flare-border: rgba(20, 25, 50, 0.1);

  --flare-text: #1D1D1F;
  --flare-text-secondary: #6E6E73;
  --flare-text-muted: #86868B;

  --flare-accent: #0071E3;
  --flare-accent-text: #0059B5;
  --flare-accent-subtle: rgba(0, 113, 227, 0.09);

  --flare-success: #00A66B;
  --flare-warning: #AC6200;
  --flare-danger: #DF2228;
}
```

## Theme behavior and transparency

- Flare has two actual palettes: light and dark. “System” selects between them and is not a third palette.
- Settings and the sidebar switch update `html[data-theme]`; the selection persists as `flare-theme`. First-time default is light, and System follows OS changes.
- Dark mode changes the core colors, selected-filter treatment, and some Sources layout/content visibility.
- Auth pages reuse the tokens but sit outside `WorkspaceProvider`; a fresh auth-page load defaults to light and does not independently restore the saved theme.
- The logo uses a fixed `#0071E3` hexagon with a white star on a transparent canvas. It intentionally does not follow the dark-theme accent override.
- The Settings system-theme preview alone uses `linear-gradient(90deg, #F6F6F8, #DEDEE3)` with `#5E5E63` icon text. It is not a marketing gradient.

Floating and mixed colors retain their original alpha:

| Transparency / mix | Semantic use |
|---|---|
| Red 7% background / 25% border | Reminder and error badges |
| Green 8% background / 25% border | Recommendation and connected/ready badges |
| Amber 8% background | Warning and disconnected badges |
| Accent 20% / 22% | Selection/drag rings and orb glow |
| Accent 45% mixed with `--line` | Active insight-card border |
| Canvas 85% mixed with `--surface` | Evidence-panel background |
| Float 92% mixed with `--surface` | Hover-expanded Capture background |
| `#FFFFFF25` = `rgba(255, 255, 255, 0.145098…)` | Capture keyboard-chip background |
| `#003B6F35` = `rgba(0, 59, 111, 0.207843…)` | Orb inset shadow |
| `#0005` = `rgba(0, 0, 0, 0.333333…)` | Dialog backdrop |
| `#0002` / `#0003` | Black shadows at 13⅓% / 20% |
| `#00000012` / `#0000001C` / `#00000018` | Capture shadows at 7.06% / 10.98% / 9.41% |
| `rgba(0, 0, 0, 0.045)` | Shared light-theme surface shadow; dark token is `none` |

## Usage notes and inconsistencies

- Widely referenced tokens: `--line` 37 times, `--accent` 27, `--secondary` 23, `--accent-text` 16, `--inset` 14, `--surface` 12, and `--hover` 11. Counts are CSS `var()` references and include dormant rules.
- `--muted` has one CSS reference and is used for Vault's keyboard hint. The `.muted` utility uses `--secondary`, not `--muted`.
- No core color variable is unreferenced. `--panel`, however, is referenced by the GitHub repository picker but never defined, so that background declaration is invalid.
- Light `--sidebar` and `--inset` intentionally duplicate `#F4F3F8`. `white`, `#fff`, and `#FFFFFF` are equivalent duplicates. Theme previews hardcode values already represented by tokens.
- Orb stops, Linear purple, and system-preview colors occur in one definition each and have narrow roles.
- Legacy `dashboard-page.tsx`, `ui-states.tsx`, and `item-type.tsx` contain slate/red Tailwind colors. The dashboard route redirects to Insights and the legacy component has no route caller; exclude these colors from the current palette.
- The old `.capture-bar` rule includes a `#00000009` shadow but is no longer rendered. `.kind-3`, `.source-drive`, `.recording`, and `.needs-attention` also appear dormant.
- Reminder Flares use red; Recommendation Flares use green. These colors encode content categories as well as status.
- `.button.secondary` has no separate styling and receives the base button appearance.
- The canonical web brand assets live in `public/brand/flare-mark.svg` and `public/brand/flare-mark.png`; `src/app/icon.svg` and `src/app/apple-icon.png` provide browser and device icons.

## Files inspected

All paths are under `frontend/` at the verified commit:

- `src/app/globals.css`; root and `(flare)` layouts, route pages and error boundaries; login, register, and verify-email routes.
- `src/components/app-shell.tsx`, `workspace-context.tsx`, `icons.tsx`, `dialog.tsx`, `auth-session.tsx`, `item-type.tsx`, and `ui-states.tsx`.
- `src/features/capture/capture.tsx`; Vault, Insights, Sources, Settings, and legacy Dashboard page components.
- `src/features/auth/auth-form.tsx`, `verify-email.tsx`, and `src/features/analyze/analyze-action.tsx`.
- `src/lib/storage/preferences.ts`, source/data references, and `src/mocks/sources.ts`.
- The full `src/` tree was scanned for color literals, variables, inline styles, and SVG attributes; `public/` assets were inventoried.
