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
  sourceUrl?: string | null;
}
export type FlareType = "Reminder" | "Warning" | "Recommendation";
export interface Insight {
  id: string;
  type: FlareType;
  title: string;
  statement: string;
  action: string | null;
  reason: string;
  evidence: Evidence[];
  createdAt: string;
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

export type ImportFormat = "csv" | "txt" | "md";

export interface ImportTextFileInput {
  format: ImportFormat;
  fileName: string;
  fileType?: string;
  fileSize: number;
  content: string;
}

export interface ImportResult {
  id: string;
  format: ImportFormat;
  fileName: string;
  item: Item;
  rowCount: number | null;
  chunkCount: number;
  analysisJobsQueued: number;
}
export interface Source {
  id: string;
  name: string;
  scope: string;
  description: string;
  channels: string[];
  status: "connected" | "syncing" | "disconnected" | "error" | "ready" | "coming-soon";
  updated: string;
  accountLogin?: string;
  repository?: GitHubRepository;
  error?: string;
  providers?: SourceProvider[];
}
export interface GitHubRepository {
  id: number;
  owner: string;
  name: string;
  fullName: string;
  private: boolean;
  htmlUrl: string;
}
export interface GitHubConnection {
  status: "disconnected" | "pending" | "connected";
  accountLogin?: string | null;
  repository?: GitHubRepository | null;
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

export interface AnalysisRun {
  id: string;
  status: "pending" | "processing" | "completed" | "failed";
  stage: "analysis" | "flare_generation" | "completed" | "failed";
  selectedChunkCount: number;
  flareIds: string[];
  error: string | null;
}
