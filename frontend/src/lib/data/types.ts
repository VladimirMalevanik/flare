export type ItemType = "note" | "url" | "file" | "audio";
export type ItemStatus = "ready" | "processing" | "error";

export interface ExtractedFact {
  id: string;
  text: string;
}
export interface Item {
  category?: "discussion" | "pull-request" | "note" | "voice";
  sourceLabel?: string;
  author?: string;
  fileType?: string;
  id: string;
  type: ItemType;
  title: string;
  content: string;
  sourceUrl?: string;
  fileName?: string;
  fileSize?: number;
  status: ItemStatus;
  createdAt: string;
  extractedFacts: ExtractedFact[];
  relatedItemIds: string[];
}
export interface Evidence {
  itemId: string;
  sourceTitle: string;
  sourceType: ItemType;
  excerpt: string;
}
export type InsightKind =
  | "Contradiction"
  | "Repeated Problem"
  | "Hidden Connection"
  | "Unresolved Question";
export interface Insight {
  id: string;
  title: string;
  summary: string;
  explanation: string;
  evidence: Evidence[];
  createdAt: string;
  kind?: InsightKind;
  /** User-facing label; internal detector names remain stable for API seams. */
  flareType?: "Discovery" | "Reminder" | "Warning";
  detailTitle?: string;
}
export interface CreateItemInput {
  type: ItemType;
  title?: string;
  content?: string;
  sourceUrl?: string;
  fileName?: string;
  fileSize?: number;
  fileType?: string;
  status?: ItemStatus;
}
export interface Source {
  id: string;
  name: string;
  scope: string;
  description: string;
  channels: string[];
  status: "connected" | "syncing" | "disconnected" | "ready" | "coming-soon";
  updated: string;
  providers?: SourceProvider[];
}
export interface SourceProvider {
  id: string;
  name: string;
  status: "connected" | "disconnected";
  selectedApps: string[];
  updated: string;
}
export interface ListItemOptions {
  query?: string;
  type?: ItemType | "all";
  limit?: number;
}
