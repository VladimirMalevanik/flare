# WEB-003 final design lock — 2026-10-03

Read-only source inspection and fresh web research. No product source, dependency, Git, task-sync, shared browser, credential, or main-branch changes.

## Decision

Use the original accepted page as the dominant reference. Restore its exact hero, centered composition, original blue phrase, concise founder problem, and one main action. Refine alignment and replace decoration with the actual evidence interaction. Do not solve this rejection with another wholesale visual theme or a generic landing-page template.

The rejected direction changed the strongest product-specific sentence into “Your startup’s knowledge, ready for the next decision.” Its screenshot also splits the body and CTA across the viewport, introduces repeated preview labels, and adds arbitrary boxed glyphs. These choices dilute the original idea and make the screen feel assembled from a marketing template. The original also contains numbered section labels and decorative orbit graphics; returning to it should not restore those rejected conventions.

## Evidence inspected

- Original accepted source: `/Users/fedornikonov/.paperclip/instances/default/flare/worktrees/qa/flare-user-preview-20261003/frontend/src/app/page.tsx` and `landing.css`.
- Rejected source: `/Users/fedornikonov/.paperclip/instances/default/flare/worktrees/qa/flare-web003-design-20261003/frontend/src/app/page.tsx` and `landing.css`.
- Rejected rendered desktop screenshot: `../landing/flare-desktop.png`. Original was assessed from its exact source and CSS; an original screenshot was not available in this evidence folder.
- Actual product source: `frontend/src/features/sources/sources-page.tsx:121` describes Notion/Obsidian ZIP snapshots containing Markdown, TXT and CSV and explicitly says Analyze runs only when chosen. `frontend/src/features/insights/insights-page.tsx:141` exposes the actual AnalyzeAction. The component tracks completion and empty results; a Flare should therefore not be presented as guaranteed for every run.
- Product fonts/tokens: existing Inter asset and `--ink: #1d1d1f`, `--accent: #0071e3` in globals.css. Preserve them. The global canvas is a faint tinted near-white; page white is already used. Do not globally change the application palette.

## Exact original copy to keep

1. Hero: **“Your notes go quiet.” / “Flare doesn't.”** Keep these exact words and two-line relationship.
2. Hero audience line: **“Built for founders who forget things”**. Show it as a quiet sentence, not an all-caps badge.
3. Hero description: **“Capture decisions, research, calls, and loose thoughts. Flare keeps the context together and surfaces grounded insights when you choose to analyze it.”** This already explains input, value, grounding, and user control. It does not need a new corporate headline.
4. Main CTA: **“Create a workspace”**. Preserve the ordinary right arrow if an arrow is retained; do not replace it with arbitrary northeast-arrow ornament.
5. **“Early access · Bring your own startup context”**.
6. Problem heading: **“Startup context disappears in plain sight.”** Preserve the short statements “Decisions hide in chat.”, “Research sits in tabs.”, “Meeting notes become archives.”, “Patterns only surface when it's too late.” and the original answer “Flare gives scattered knowledge one place to become useful again.”
7. Workflow heading: **“From scattered context to one useful signal.”**
8. Demo heading: **“See the signal, then see why.”** Keep “2 supporting sources” and original “Open evidence” / “Hide evidence” labels.
9. Closing heading: **“Give your startup a memory.”** and original **“Start capturing the context you'll wish you had later.”**

Do not rewrite accepted copy merely to make it sound newer. Only adjust literal product facts that are outdated. The three workflow steps are the place for this small factual correction: Capture → Analyze → Review the evidence. The original middle step “Flare connects it” does not make the trigger clear; label it “Analyze” and use one direct sentence explaining that the user starts analysis. Keep ZIP support in the import description rather than implying live sync.

## Remove

- All chapter-number/caps labels: “01 / THE WORKFLOW”, “02 / YOUR SOURCES”, “03 / THE PRINCIPLE”, and the original “01 / THE PROBLEM” through “06 / WHY FLARE”. Removing only the new ones leaves the same rejected template in place.
- The new headline, “A small habit for the decisions that deserve a little more context”, “Your context. Your next move.”, and “THE NEXT DECISION STARTS HERE”. They are broad marketing language and add no explanation.
- “Explore the preview” alongside the hero CTA, “Build your Vault” in imports, and repeated marketing-action links. Keep the existing account actions in navigation, the single hero action, the final repeat, and controls that actually operate the demo.
- Initial-in-box pseudo logos for Notion/Obsidian; empty-square “file” icons; northeast-arrow file glyphs; decorative plus/arrow/spark marks attached to every feature. Use existing real product icons only where the product actually needs them. The existing Flare BrandMark stays.
- The original hero card’s fake stacked-card pseudo-elements and the original orbit/core/count illustration. They suggest complexity and scale without showing how the product works.
- Unexplained confidence/record/count claims in samples (“High confidence”, “148 records”, “connected records”), timestamps that imply a real event, “Updated 4 min ago”, and fictional customer identity chrome. Label the example as sample data once.
- Repetitive principle, outcome, comparison, and implementation-security marketing sections that restate the same promise. No bento feature-grid replacement. Security source names such as PostgreSQL and HttpOnly sessions do not belong in the main product story.

## Bounded layout changes

1. **Hero:** restore centered alignment. A common center line should own audience line, two-line headline, description, CTA, and caption. Desktop headline about 80–88px rather than the old 96px maximum; line-height about 1.02 and tracking about -0.05em. Body width 640–680px, 20px, line-height 1.55. CTA below copy, not stranded at the far right. Preserve a blue second line because it is the original branded reply, not an arbitrary accent word.
2. **Hero proof:** retain one compact interactive insight under the CTA, around 680–720px wide, centered. Title remains “You already set this boundary.” Use the original source pair and exact quotes: June planning note (“Keep acquisition spend below $8k/month.”), Launch brief (“Proposed paid launch budget: $14k.”). For literal consistency, body should reference the acquisition-spend limit rather than call it a runway limit. Open evidence reveals these two source rows. This interaction is the distinctive visual move: a forgotten decision and new plan visibly connect. Avoid decorative diagrams.
3. **One grid:** retain the original 1200px outer container, 24px minimum desktop gutters, 20px mobile gutters. Section heading and its body must share a visible left edge. Once numbered label columns are removed, remove their associated 190px/222px offsets; do not leave ghost columns or margins. Prefer a readable content width near 1040px for lower sections.
4. **Page sequence:** Hero + small evidence example → original founder problem → Capture / Analyze / Review the evidence → original separate product preview → concise imports fact within Vault section → final original CTA → footer. Do not move the entire dashboard into the hero: the original separate hero and later preview provide clearer pacing.
5. **Workflow:** three plain text columns on desktop, same baseline and lengths, no icons, numbered chips, enclosing cards, or vertical-rule ornament. On mobile use a single natural reading column. Labels are ordinary Capture, Analyze, Review the evidence.
6. **Preview:** preserve the original Capture / Flares / Vault story and real keyboard/tab behavior already improved in the rejected implementation. Keep only functional interactions. Use the application’s existing labels and icon system rather than inventing one. A quiet single app frame is enough; remove repeated “PRODUCT PREVIEW”, “Interactive example”, “ANALYSIS EXAMPLE”, “FROM YOUR VAULT” tiers. “Sample data” in the preview caption is enough.
7. **Imports:** text-only list, Notion and Obsidian names as text; one short description each. Preserve the precise fact: “ZIP imports are one-time copies. Later changes in Notion or Obsidian are not synced automatically.” This should be smaller factual support, not another big inspirational section.
8. **Finish:** use normal blue primary controls with the original restrained pill shape; reduce shadow rather than changing every control into a new square treatment. Keep a single soft elevation on the interactive hero proof and demo frame. No gradient haze is needed. Blue has three roles: Flare identity, action, selected state/evidence link.
9. **Responsive QA:** verify at 1440, 1024, 768, 390, 320px and at least the current second-language screen. Check actual headline wraps, no arbitrary inline/block span word breaks, no horizontal overflow, CTA relationship, source-row alignment, and demo focus visibility. Compare the new result side-by-side with the original, with changes narrow enough to explain individually.

## Fresh primary-source research and what it contributes

- [Linear, A calmer interface for a product in motion](https://linear.app/now/behind-the-latest-design-refresh), March 12, 2026. The team describes reducing icon usage and prominent sidebar treatments, softening unnecessary separators, making action positions predictable, and comparing old/new during iteration. **Bounded adaptation:** remove excessive decorative icons/chrome; keep actual content visually dominant; compare the revised screen with the accepted baseline. Do not borrow its dark palette or entire landing composition.
- [NN/G, Good Visual Design, Explained](https://www.nngroup.com/articles/good-visual-design/), November 14, 2025. Its examples connect polish with grids, a small type hierarchy, strategic color, and purposeful imagery. **Bounded adaptation:** common alignment rails, disciplined type levels, original limited palette, and product evidence as meaningful imagery. Exact Flare pixels above are implementation recommendations, not values prescribed by NN/G.
- [Government Design Principles](https://www.gov.uk/guidance/government-design-principles), updated April 2, 2025. Research actual needs, concentrate on the irreducible core, and iterate rather than reinventing useful patterns. **Bounded adaptation:** the user's explicit rejection is evidence; remove unsupported expansion and preserve the clear original language. This is a method reference, not a visual template.
- [Things by Cultured Code](https://culturedcode.com/things/). Its page states the concrete product category, shows the actual application, and keeps the introduction focused before expanding into feature details. **Bounded adaptation:** product explanation plus actual evidence; do not copy its imagery, claims, icon, awards, or purchase model.
- [Craft](https://www.craft.do/). Its current homepage starts with literal notes/tasks language and uses actual app contents to explain writing, planning, and organization. **Bounded adaptation:** source/data/UI as proof, not empty abstract feature boxes. Craft’s broader integrations, illustration style, awards, social proof, and complex page are inappropriate for Flare’s present scope.
- [Framer Marketplace templates](https://www.framer.com/marketplace/templates/). Reviewed as a template source. It offers broad software and SaaS categories, but a complete template would reintroduce a prefabricated section stack. No template selected or purchased. Use only a narrow layout reference if needed; the user-provided accepted Flare page is the stronger build target.

## Reference lock / decision ledger

| Decision | Authority | Role / reason |
|---|---|---|
| Restore exact original hero and centered composition | User says old was better + accepted page source | Primary foundation; keep product identity |
| Inter, white/near-white, black, original blue | Existing product + user palette constraint | No type/palette rebrand |
| One hero action | Original + user rejects excess actions | One next step; preview controls remain functional |
| No numbered chapter template, no invented icons | User explicit rejection | Remove from both new and original |
| Shared grid and three main text scales | NN/G craft research | Make alignment legible |
| Quiet chrome and fewer icons/separators | Linear 2026 refresh | Content earns attention; navigation supports it |
| Actual source-pair reveal is the signature | Existing Flare sample + working source/evidence model | Brand distinction comes from product, not ornament |
| ZIP and Analyze facts retained narrowly | Actual source UI and AnalyzeAction | Avoid live-sync or guaranteed-result implication |

The research supports disciplined editing and specific product proof; it does not establish a universal scientific list of what “AI design” looks like. The numbered labels, invented glyphs, vague new copy, excess actions, and misaligned composition are concrete problems in this page, confirmed by the user's feedback.
