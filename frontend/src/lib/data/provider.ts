import type { ImportPackage, ImportPackageReport, ZipSourceKind } from "./types";
import type {
  AnalysisRun,
  AnalysisSchedule,
  DailyAnalysisStatus,
  CreateItemInput,
  Insight,
  ImportResult,
  ImportTextFileInput,
  Item,
  ItemType,
  ListItemOptions,
  UpdateItemInput,
  Source,
  GitHubConnection,
  GitHubRepository,
} from "./types";

export type AnalyticsEventInput =
  | { eventType: "voluntary_inspection"; interactionId: string; flareId: string; sourceId?: string }
  | { eventType: "capture_started"; targetType: "capture"; targetId?: never; metadata?: never }
  | { eventType: "capture_submitted"; targetType: "item"; targetId: string;
      metadata: { sourceType: ItemType } }
  | { eventType: "capture_file_attached"; targetType: "import"; targetId?: never;
      metadata: { format: "csv" | "txt" | "md"; fileSize: number } }
  | { eventType: "capture_voice_started" | "capture_voice_stopped";
      targetType: "capture"; targetId?: never; metadata?: never }
  | { eventType: "item_viewed"; targetType: "item"; targetId: string;
      metadata: { sourceType: ItemType } }
  | { eventType: "flare_viewed"; targetType: "flare"; targetId: string;
      metadata: { source: "insights_feed" } }
  | { eventType: "screen_opened"; targetType: "screen"; targetId?: never;
      metadata: { screen: "sources_from_insights" } };

export interface FlareDataProvider {
  getSourceConnections(signal?: AbortSignal): Promise<import("./types").SourceConnections>;
  connectSource(provider: import("./types").ConnectedProvider, signal?: AbortSignal): Promise<{url?: string; connected?: boolean}>;
  sourceResources(id: string, cursor?: string, signal?: AbortSignal): Promise<import("./types").SourceResourcePage>;
  selectSourceResources(id: string, expectedRevision: number, resourceIds: string[], shareWithWorkspace: boolean, signal?: AbortSignal): Promise<void>;
  sourceConnectionAction(id: string, action: "sync" | "cancel" | "disconnect", signal?: AbortSignal): Promise<void>;
  getImportCapabilities(signal?: AbortSignal): Promise<{ available: boolean; maxUploadBytes: number | null }>;
  createImportPackage(input: { sourceKind: ZipSourceKind; fileName: string; fileSize: number; requestKey: string }, signal?: AbortSignal): Promise<ImportPackage>;
  uploadImportPackage(id: string, file: File, signal?: AbortSignal): Promise<ImportPackage>;
  importPackageAction(id: string, action: "finalize" | "cancel" | "retry", signal?: AbortSignal): Promise<ImportPackage>;
  getImportPackage(id: string, signal?: AbortSignal): Promise<ImportPackage>;
  listImportPackages(signal?: AbortSignal): Promise<ImportPackage[]>;
  getImportPackageReport(id: string, after?: number, signal?: AbortSignal): Promise<ImportPackageReport>;
  startAnalysis(key: string, signal?: AbortSignal): Promise<AnalysisRun>;
  getAnalysisRun(id: string, signal?: AbortSignal): Promise<AnalysisRun>;
  getAnalysisSchedule(signal?: AbortSignal): Promise<AnalysisSchedule>;
  updateAnalysisSchedule(input: {
    enabled: boolean;
    emailNotificationsEnabled: boolean;
    timezone: string;
    localTime: string;
  }): Promise<AnalysisSchedule>;
  getDailyAnalysisStatus(signal?: AbortSignal): Promise<DailyAnalysisStatus>;
  listSources(): Promise<Source[]>;
  saveSource(source: Source): Promise<Source>;
  getGitHubConnection(): Promise<GitHubConnection>;
  startGitHubConnection(): Promise<string>;
  listGitHubRepositories(): Promise<GitHubRepository[]>;
  selectGitHubRepository(repositoryId: number): Promise<GitHubConnection>;
  disconnectGitHub(): Promise<void>;
  listItems(options?: ListItemOptions): Promise<Item[]>;
  getItem(id: string): Promise<Item | null>;
  getItemVersion(id: string, versionId: string): Promise<import('./types').ItemVersion | null>;
  createItem(input: CreateItemInput): Promise<Item>;
  updateItem(id: string, input: UpdateItemInput): Promise<Item>;
  importTextFile(input: ImportTextFileInput): Promise<ImportResult>;
  deleteItem(id: string): Promise<void>;
  listInsights(): Promise<Insight[]>;
  getInsight(id: string): Promise<Insight | null>;
  trackEvent(event: AnalyticsEventInput): Promise<void>;
  resetDemoData(): Promise<void>;
}
