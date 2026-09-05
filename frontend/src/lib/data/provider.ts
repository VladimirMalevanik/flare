import type {
  CreateItemInput,
  Insight,
  Item,
  ListItemOptions,
  Source,
} from "./types";
export interface FlareDataProvider {
  listSources(): Promise<Source[]>;
  saveSource(source: Source): Promise<Source>;
  listItems(options?: ListItemOptions): Promise<Item[]>;
  getItem(id: string): Promise<Item | null>;
  createItem(input: CreateItemInput): Promise<Item>;
  listInsights(): Promise<Insight[]>;
  getInsight(id: string): Promise<Insight | null>;
  resetDemoData(): Promise<void>;
}
