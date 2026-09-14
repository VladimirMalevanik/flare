import type {
  AnalysisRun,
  AnalysisSchedule,
  DailyAnalysisStatus,
  CreateItemInput,
  Insight,
  ImportResult,
  ImportTextFileInput,
  Item,
  ListItemOptions,
  UpdateItemInput,
  Source,
  GitHubConnection,
  GitHubRepository,
} from "./types";

export interface AnalyticsEventInput {
  eventType: string;
  targetType?: string;
  targetId?: string;
  metadata?: Record<string, unknown>;
}

export interface FlareDataProvider {
  startAnalysis(key: string, signal?: AbortSignal): Promise<AnalysisRun>;
  getAnalysisRun(id: string, signal?: AbortSignal): Promise<AnalysisRun>;
  getAnalysisSchedule(): Promise<AnalysisSchedule>;
  updateAnalysisSchedule(input: {
    enabled: boolean;
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
