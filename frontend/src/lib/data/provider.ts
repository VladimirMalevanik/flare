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
  startAnalysis(key: string, signal?: AbortSignal): Promise<AnalysisRun>;
  getAnalysisRun(id: string, signal?: AbortSignal): Promise<AnalysisRun>;
  getAnalysisSchedule(): Promise<AnalysisSchedule>;
  updateAnalysisSchedule(input: {
    enabled: boolean;
    emailNotificationsEnabled: boolean;
    timezone: string;
    localTime: string;
  }): Promise<AnalysisSchedule>;
  getDailyAnalysisStatus(): Promise<DailyAnalysisStatus>;
  listSources(): Promise<Source[]>;
  saveSource(source: Source): Promise<Source>;
  getGitHubConnection(): Promise<GitHubConnection>;
  startGitHubConnection(): Promise<string>;
  listGitHubRepositories(): Promise<GitHubRepository[]>;
  selectGitHubRepository(repositoryId: number): Promise<GitHubConnection>;
  disconnectGitHub(): Promise<void>;
  listItems(options?: ListItemOptions): Promise<Item[]>;
  getItem(id: string): Promise<Item | null>;
  createItem(input: CreateItemInput): Promise<Item>;
  updateItem(id: string, input: UpdateItemInput): Promise<Item>;
  importTextFile(input: ImportTextFileInput): Promise<ImportResult>;
  deleteItem(id: string): Promise<void>;
  listInsights(): Promise<Insight[]>;
  getInsight(id: string): Promise<Insight | null>;
  trackEvent(event: AnalyticsEventInput): Promise<void>;
  resetDemoData(): Promise<void>;
}
