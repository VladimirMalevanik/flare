import type { FlareDataProvider } from "./provider";
import type { Source } from "./types";
import type { CreateItemInput, Insight, Item, ListItemOptions } from "./types";
/** Integration seam: map backend DTOs to frontend domain types here. */
export class ApiDataProvider implements FlareDataProvider {
  async listSources(): Promise<Source[]> {
    return this.unavailable();
  }
  async saveSource(_source: Source): Promise<Source> {
    return this.unavailable();
  }
  private unavailable(): never {
    throw new Error(
      "ApiDataProvider is not configured. Use MockDataProvider until an API adapter is implemented.",
    );
  }
  listItems(_options?: ListItemOptions): Promise<Item[]> {
    return Promise.reject(this.unavailable());
  }
  getItem(_id: string): Promise<Item | null> {
    return Promise.reject(this.unavailable());
  }
  createItem(_input: CreateItemInput): Promise<Item> {
    return Promise.reject(this.unavailable());
  }
  listInsights(): Promise<Insight[]> {
    return Promise.reject(this.unavailable());
  }
  getInsight(_id: string): Promise<Insight | null> {
    return Promise.reject(this.unavailable());
  }
  resetDemoData(): Promise<void> {
    return Promise.resolve();
  }
}
