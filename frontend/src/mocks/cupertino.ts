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
  type,
  title,
  sourceLabel,
  category,
  content: facts.join("\n\n"),
  createdAt: "2026-09-05T08:00:00Z",
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
      "People should see one useful connection before they are asked to organize anything.",
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
    ["Revisit CSV export after we reach 10 beta signups.", "Do not build it before people ask for a way to take their context with them."],
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
export const contextInsights: Insight[] = [
  {
    id: "onboarding-first-value", kind: "Hidden Connection", flareType: "Discovery",
    title: "Users keep getting stuck before seeing first value",
    summary:
      "Three separate beta users described leaving onboarding before understanding what the product actually does.",
    explanation:
      "The interview, beta feedback, and founder hypothesis all point to the same moment: people need a concrete first result before setup feels worthwhile.",
    createdAt: "2026-09-05T08:25:00Z",
    evidence: [
      evidence(
        "customer-interview-maya", "Maya left onboarding before she could explain what the product would help her do.",
      ),
      evidence(
        "beta-onboarding-feedback", "Two beta users paused during setup because the product value was not clear yet.",
      ),
      evidence("founder-first-value-note", "People should see one useful connection before they are asked to organize anything."),
    ],
  },
  {
    id: "pricing-test-conflict", kind: "Contradiction", flareType: "Warning",
    title: "The current pricing test conflicts with an earlier decision",
    summary:
      "The team agreed to test monthly pricing first, but the latest launch note describes annual-only pricing.",
    explanation:
      "The current launch copy may test a different pricing hypothesis than the one the team agreed to validate.",
    createdAt: "2026-09-05T07:00:00Z",
    evidence: [
      evidence(
        "pricing-decision", "Monthly-first until we understand willingness to pay.",
      ),
      evidence(
        "launch-pricing-note", "The launch page currently describes an annual-only plan.",
      ),
    ],
  },
  {
    id: "csv-export-reminder", kind: "Unresolved Question", flareType: "Reminder",
    title: "You planned to revisit CSV export after 10 beta signups",
    summary:
      "That threshold has now been reached, but the follow-up is still unresolved.",
    explanation:
      "This is an earlier promise with a clear trigger, not a recommendation to build a new feature immediately.",
    createdAt: "2026-09-05T06:00:00Z",
    evidence: [
      evidence(
        "csv-export-voice-memo", "Revisit CSV export after we reach 10 beta signups.",
      ),
      evidence(
        "beta-signups-milestone", "Ten people have now signed up for the beta.",
      ),
    ],
  },
];
