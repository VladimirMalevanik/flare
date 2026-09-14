import type { Item, Insight } from "@/lib/data/types";
const makeItem = (
  id: string,
  type: Item["type"],
  title: string,
  sourceLabel: string,
  category: Item["category"],
  facts: string[],
  relatedItemIds: string[],
): Item => ({
  id,
  currentVersionId: `${id}-version-1`,
  versionNumber: 1,
  type,
  title,
  sourceLabel,
  category,
  content: facts.join("\n\n"),
  createdAt: "2026-09-05T08:00:00Z",
  updatedAt: "2026-09-05T08:00:00Z",
  status: "ready",
  extractedFacts: facts.map((text, i) => ({ id: `${id}-${i}`, text })),
  relatedItemIds,
});
export const contextItems: Item[] = [
  makeItem(
    "pricing-decision", "note", "Pricing test", "Founder note · Elena Rostova", "note",
    [
      "Monthly-first until we understand willingness to pay.",
      "Revisit packaging after the beta has enough customer conversations.",
    ],
    ["launch-pricing-note"],
  ),
  makeItem(
    "customer-interview-maya", "note", "Customer interview: Maya", "Customer interview · Beta user", "discussion",
    [
      "Maya left onboarding before she could explain what the product would help her do.",
      "She expected a clear first result before being asked to set up her workspace.",
    ],
    ["beta-onboarding-feedback", "founder-first-value-note"],
  ),
  makeItem(
    "beta-onboarding-feedback", "note", "Beta onboarding feedback", "Beta feedback · September cohort", "discussion",
    [
      "Two beta users paused during setup because the product value was not clear yet.",
      "The welcome screen should show an example Flare before asking for more context.",
    ],
    ["customer-interview-maya", "founder-first-value-note"],
  ),
  makeItem(
    "founder-first-value-note", "note", "First-value hypothesis", "Founder note · Elena Rostova", "note",
    [
      "Our goal is for beta users to reach a useful result during onboarding.",
      "Keep onboarding focused on adding context, then show a grounded Flare when evidence is sufficient.",
    ],
    ["customer-interview-maya", "beta-onboarding-feedback"],
  ),
  makeItem(
    "launch-pricing-note", "note", "Launch pricing note", "Launch note · Founder team", "note",
    [
      "The launch page currently describes an annual-only plan.",
      "Publish the pricing test copy before inviting the next beta cohort.",
    ],
    ["pricing-decision"],
  ),
  makeItem(
    "csv-export-voice-memo", "audio", "CSV export follow-up", "Voice memo · Elena Rostova", "voice",
    ["We agreed to revisit CSV export after reaching 10 beta signups.", "Do not build it before people ask for a way to take their context with them."],
    ["beta-signups-milestone"],
  ),
  makeItem(
    "beta-signups-milestone", "note", "10 beta signups reached", "Founder note · Beta milestone", "note",
    ["Ten people have now signed up for the beta.", "The CSV export follow-up has not been scheduled yet."],
    ["csv-export-voice-memo"],
  ),
];
const evidence = (id: string, excerpt: string) => {
  const item = contextItems.find((i) => i.id === id)!;
  return {
    itemId: id,
    sourceTitle: item.title,
    sourceType: item.type,
    excerpt,
  };
};
// Curated examples follow the same public taxonomy; no automatic Discovery rename.
export const contextInsights: Insight[] = [
  {
    id: "onboarding-next-action", type: "Recommendation",
    title: "Test the first result before expanding setup",
    statement: "Beta users leave before they understand the product value.",
    action: "Test an example result with beta users before adding more setup steps.",
    reason: "The onboarding goal is blocked by users leaving before reaching a useful result.",
    createdAt: "2026-09-05T08:25:00Z",
    evidence: [
      evidence("founder-first-value-note", "Our goal is for beta users to reach a useful result during onboarding."),
      evidence("customer-interview-maya", "Maya left onboarding before she could explain what the product would help her do."),
      evidence("beta-onboarding-feedback", "Two beta users paused during setup because the product value was not clear yet."),
    ],
  },
  {
    id: "pricing-test-conflict", type: "Warning",
    title: "Launch pricing conflicts with the agreed test",
    statement: "The launch page offers annual-only pricing despite the monthly-first decision.",
    action: null,
    reason: "Annual-only copy tests a different pricing hypothesis from the agreed monthly experiment.",
    createdAt: "2026-09-05T07:00:00Z",
    evidence: [
      evidence("pricing-decision", "Monthly-first until we understand willingness to pay."),
      evidence("launch-pricing-note", "The launch page currently describes an annual-only plan."),
    ],
  },
  {
    id: "csv-export-reminder", type: "Reminder",
    title: "Revisit export at the signup milestone",
    statement: "Ten beta signups activate the agreed CSV export review.",
    action: null,
    reason: "The review trigger is now met and the follow-up has not been scheduled.",
    createdAt: "2026-09-05T06:00:00Z",
    evidence: [
      evidence("csv-export-voice-memo", "We agreed to revisit CSV export after reaching 10 beta signups."),
      evidence("beta-signups-milestone", "Ten people have now signed up for the beta.\n\nThe CSV export follow-up has not been scheduled yet."),
    ],
  },
];
