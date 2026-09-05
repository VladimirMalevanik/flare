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
    "pr-412",
    "url",
    "WebSocket Fallback REST Adapter",
    "GitHub · PR #412",
    "pull-request",
    [
      "Bypasses synchronous pre-flight key verification for established client sessions.",
      "Introduced /v2/sync HTTP fallback to prevent socket disconnects during handoffs.",
      "Linear DEV-89 attached with 4 sub-tickets.",
    ],
    ["mobile-thread", "linear-3091"],
  ),
  makeItem(
    "sprint-sync",
    "audio",
    "Architecture Sprint Sync",
    "Voice Memo · Elena Rostova",
    "voice",
    [
      "The team is reviewing the mobile sync contract before staging deploy.",
      "Elena assigned DRI for staged production rollout.",
    ],
    ["pr-412", "linear-3091"],
  ),
  makeItem(
    "mobile-thread",
    "note",
    "Idempotency Collision Handling",
    "Telegram · #dev-mobile",
    "discussion",
    [
      "Client 4.1 expects 409 Conflict if duplicate idempotency key arrives.",
      "Local SQLite journal corrupts if server returns 200 on duplicate.",
    ],
    ["pr-412"],
  ),
  {
    ...makeItem(
      "residency",
      "file",
      "EU Data Residency & AWS Frankfurt VPC",
      "Notion · Compliance",
      "note",
      [
        "Frankfurt VPC required for enterprise tenant tier by Q4.",
        "Requires formal DPA sign-off from General Counsel.",
      ],
      [],
    ),
    fileName: "EU Data Residency.pdf",
    fileSize: 1400000,
    fileType: "application/pdf",
  },
  makeItem(
    "checkout",
    "note",
    "Safari 3DS Checkout Drop-off Finding",
    "Meeting Note · Product & Eng",
    "discussion",
    [
      "Multi-factor challenge timeouts cascading into unhandled promise rejections in iOS webviews.",
      "4.2% drop-off identified in DACH checkout funnel during payment challenge handoff.",
    ],
    ["linear-3091"],
  ),
  makeItem(
    "linear-3091",
    "note",
    "ENG-3091: Optimistic Validation Latch",
    "Linear Issue · In Progress",
    "note",
    [
      "Wrap async dispatch queue in optimistic validation latch.",
      "Prevents duplicate event bus ingestion under network jitter.",
    ],
    ["pr-412", "sprint-sync"],
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
    id: "sync-divergence",
    kind: "Contradiction",
    detailTitle: "Mobile & Web Sync Divergence",
    title: "Conflicting API contract between Mobile client and Web sync engine",
    summary:
      "The iOS client expects immediate 409 Conflict rejection for duplicate idempotency tokens, but the newly merged PR #412 introduces asynchronous queueing that skips pre-flight checks.",
    explanation:
      "Risk of local client state corruption and silent transaction loss during peak traffic.",
    createdAt: "2026-09-05T08:25:00Z",
    evidence: [
      evidence(
        "mobile-thread",
        "Client 4.1 expects 409 Conflict if duplicate idempotency key arrives; otherwise we don’t branch to retry state.",
      ),
      evidence(
        "pr-412",
        "Bypassing synchronous pre-flight key verification in favor of optimistic pub-sub ingestion queue.",
      ),
    ],
  },
  {
    id: "checkout-friction",
    kind: "Repeated Problem",
    title: "Recurring 3DS checkout timeout reports after Stripe migration",
    summary:
      "Customer support escalated checkout failures matching webview timeout errors previously noted in team discussions.",
    explanation:
      "Direct conversion loss impacting European enterprise renewals.",
    createdAt: "2026-09-05T07:00:00Z",
    evidence: [
      evidence(
        "checkout",
        "Multi-factor challenge timeouts cascade into unhandled promise rejections in iOS webviews.",
      ),
      evidence(
        "linear-3091",
        "Wrap async dispatch queue in optimistic validation latch.",
      ),
    ],
  },
  {
    id: "rollout-connection",
    kind: "Hidden Connection",
    title: "Sprint decisions connect to the mobile sync rollout",
    summary:
      "The sprint voice memo and implementation notes describe the same validation work from different sides of the rollout.",
    explanation:
      "Connecting the discussion to the implementation makes ownership and rollout expectations easier to verify.",
    createdAt: "2026-09-05T06:00:00Z",
    evidence: [
      evidence(
        "sprint-sync",
        "Elena assigned DRI for staged production rollout.",
      ),
      evidence(
        "linear-3091",
        "Prevents duplicate event bus ingestion under network jitter.",
      ),
    ],
  },
];
