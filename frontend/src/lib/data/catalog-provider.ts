import type { AnalyticsEventInput, FlareDataProvider } from "./provider";
import { sourceCatalog } from "./source-catalog";
import type {
  AnalysisRun,
  AnalysisSchedule,
  CreateItemInput,
  DailyAnalysisStatus,
  GitHubConnection,
  GitHubRepository,
  ImportResult,
  ImportTextFileInput,
  Insight,
  Item,
  ListItemOptions,
  Source,
  UpdateItemInput,
} from "./types";

const cloneSources = (): Source[] =>
  sourceCatalog.map((source) => ({
    ...source,
    channels: [...source.channels],
    ...(source.repository ? { repository: { ...source.repository } } : {}),
  }));

/**
 * Production-safe static product catalog used only for source capability cards.
 * Every workspace-data method fails closed so API mode can never fall back to
 * seeded demo Notes, Flares, integrations, or success states.
 */
export class ProductionCatalogProvider implements FlareDataProvider {
  private unavailable(): never {
    throw new Error("This operation requires the Flare API.");
  }

  async listSources(): Promise<Source[]> {
    return cloneSources();
  }

  async saveSource(_source: Source): Promise<Source> {
    return this.unavailable();
  }

  async startAnalysis(_key: string, _signal?: AbortSignal): Promise<AnalysisRun> {
    return this.unavailable();
  }

  async getAnalysisRun(_id: string, _signal?: AbortSignal): Promise<AnalysisRun> {
    return this.unavailable();
  }

  async getAnalysisSchedule(): Promise<AnalysisSchedule> {
    return this.unavailable();
  }

  async updateAnalysisSchedule(_input: {
    enabled: boolean;
    emailNotificationsEnabled: boolean;
    timezone: string;
    localTime: string;
  }): Promise<AnalysisSchedule> {
    return this.unavailable();
  }

  async getDailyAnalysisStatus(): Promise<DailyAnalysisStatus> {
    return this.unavailable();
  }

  async getGitHubConnection(): Promise<GitHubConnection> {
    return this.unavailable();
  }

  async startGitHubConnection(): Promise<string> {
    return this.unavailable();
  }

  async listGitHubRepositories(): Promise<GitHubRepository[]> {
    return this.unavailable();
  }

  async selectGitHubRepository(_repositoryId: number): Promise<GitHubConnection> {
    return this.unavailable();
  }

  async disconnectGitHub(): Promise<void> {
    return this.unavailable();
  }

  async listItems(_options?: ListItemOptions): Promise<Item[]> {
    return this.unavailable();
  }

  async getItem(_id: string): Promise<Item | null> {
    return this.unavailable();
  }

  async createItem(_input: CreateItemInput): Promise<Item> {
    return this.unavailable();
  }

  async updateItem(_id: string, _input: UpdateItemInput): Promise<Item> {
    return this.unavailable();
  }

  async importTextFile(_input: ImportTextFileInput): Promise<ImportResult> {
    return this.unavailable();
  }

  async deleteItem(_id: string): Promise<void> {
    return this.unavailable();
  }

  async listInsights(): Promise<Insight[]> {
    return this.unavailable();
  }

  async getInsight(_id: string): Promise<Insight | null> {
    return this.unavailable();
  }

  async trackEvent(_event: AnalyticsEventInput): Promise<void> {
    return this.unavailable();
  }

  async resetDemoData(): Promise<void> {
    return this.unavailable();
  }
}
