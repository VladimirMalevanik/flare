import type {
  AnalysisRun,
  CreateItemInput,
  Insight,
  Item,
  ListItemOptions,
  Source,
  GitHubConnection,
  GitHubRepository,
} from "./types";
export interface FlareDataProvider {
  startAnalysis(key: string, signal?: AbortSignal): Promise<AnalysisRun>;
  getAnalysisRun(id: string, signal?: AbortSignal): Promise<AnalysisRun>;
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
  deleteItem(id: string): Promise<void>;
  listInsights(): Promise<Insight[]>;
  getInsight(id: string): Promise<Insight | null>;
  resetDemoData(): Promise<void>;
}
