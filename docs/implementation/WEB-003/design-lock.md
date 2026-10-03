# WEB-003 design lock

## Brief and target

Improve the existing Flare web landing for founders and startup teams. Preserve the
existing brand, Inter, white/black/blue palette, product vocabulary, and theme support.
Explain the working product: a Vault for saved context, one-time Notion/Obsidian ZIP
imports, explicit Analyze, and insights linked to supporting sources. This is a direct
improvement of the existing design system, authorized under WEB-003; no new brand or
unselected visual exploration is part of this change.

Fresh task context read before product edits: `75e31fb35ea991756586fc322abbc6f426eea495`.
The root team owns the claimed, published task worktree and has assigned the landing
files to its design agent. Other product tasks are in review/waiting and remain untouched.

## Current references inspected on 2026-10-03

Official live HTML and 1440 × 1050 isolated browser captures were inspected. These are
composition references, not endorsements or evidence of popularity.

- [Linear](https://linear.app/): left-aligned, medium-weight Inter headline; a broad,
  detailed product stage immediately below it; thin rules and quiet navigation. Borrow
  composition and product density only. Its dark palette does not replace Flare's brand.
- [Granola](https://www.granola.ai/): clear audience/job headline and a concrete note
  example; the page explains before/during/after through product evidence. Borrow the
  narrative sequencing only, not serif typography, green accents, or textured imagery.
- [Reflect](https://reflect.app/): an explicit optional-AI section, source-linked
  answers, and concrete capture capabilities. Borrow product precision, not purple glow,
  orbital graphics, or claims about its storage model.
- [Mem](https://get.mem.ai/): useful separation of workspace memory from an agent's
  actions and specific example artifacts. Its continuous/proactive AI is outside Flare's
  supported behavior and must not appear in Flare's copy.
- [Tana](https://tana.inc/): short outcome framing paired with a visible output. The
  current homepage sells a meeting product, distinct from Tana Outliner; do not reuse its
  meeting/automation/integration claims for Flare.

Captures are outside Git under `/tmp/flare-design-research/`. No shared browser session,
new dependencies, credentials, or product data were used for this research.

## Reference lock

Primary direction: Flare's existing light product identity, sharpened with Linear's
headline-to-product-stage composition. Secondary references have bounded roles:
Granola owns sequence; Reflect owns clear source/AI language.

Preserve:

1. Existing Inter, recognizable Flare mark, white surfaces, near-black text, blue actions.
2. One strong left-aligned headline; compact navigation and clear reading measures.
3. A wide, interactive sample product stage with genuine tab/filter/evidence behavior.
4. Thin dividers and substantial product content, rather than decorative card grids.
5. Explicit user control: saving/importing does not promise automatic analysis or sync.

Token commitments: use the existing surface/ink/accent tokens. Landing surfaces are
white in light theme and inherit the current dark surface in dark theme. Blue identifies
primary actions, selected product controls, and Flare signals; it is not a decorative
word highlight. Use 12–18px product container radii, 8–10px controls, one modest stage
shadow, 64–72px desktop display type, 36–44px mobile type, 16–19px readable body copy.

Media strategy: code-native UI with visible sample labels and source excerpts. No
invented testimonials, customer logos, confidence levels, record counts, or fake browser
chrome. This is an example, not a simulated live backend or saved workspace.

Reject: purple/cream/serif brand drift, radial hero glow, floating card stacks, orbit
diagrams, ubiquitous pills, false time labels, comparison stereotypes, empty hero copy,
infinite loops, typewriter effects, fake progress, and hidden-on-load content.

## Decision ledger

| Decision | Evidence / role | Reason |
| --- | --- | --- |
| Left-aligned headline above a wide stage | Linear composition; existing Flare brand | The product gets the visual weight and the visitor sees the workflow early. |
| Same Inter and white/black/blue tokens | Explicit user constraint; existing UI | Improve composition without changing brand or font dependencies. |
| Capture → Analyze → check sources | Granola narrative sequence; local product behavior | State when AI runs and how to inspect the result. |
| Source excerpts and category filters in the sample | Reflect source-linked answer pattern; existing Flare preview | Make evidence an interaction visitors can verify. |
| Explicit sample labels; no timestamps/confidence/count metrics | Local static preview; copy-edit/Refero proof rules | Avoid presenting fictional data as live results or adoption evidence. |
| Import options shown as ZIP snapshots | User brief; local import guides/types | Imported copies are not continuous Notion/Obsidian synchronization. |
| Plain product trust statements | Verified local manual-analysis/evidence behavior | Remove HttpOnly/PostgreSQL/SQL language and unverified security/export guarantees. |
| Short hover/focus/state motion only | Refero motion/craft guidance | Add feedback while keeping content readable and reduced-motion complete. |

## QA target

Review desktop/mobile, English/Spanish, light/dark, and reduced motion. Inspect headline
wraps, nav reachability, focus rings, responsive sample tabs, working category filters,
expanded evidence, and both capture-to-Vault-to-analysis sample transitions. Verify that
every button has a real sample action or navigation target; source values remain visibly
sample data; native language selection and ZIP reports are handled by root-owned files.

Visual checks must use the built implementation, compare against this lock, and resolve
any unreadable text, overflow, broken interaction, or major visual drift before handoff.
