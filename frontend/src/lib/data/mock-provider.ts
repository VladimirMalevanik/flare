"use client";
import {
  contextInsights as seedInsights,
  contextItems as seedItems,
} from "@/mocks/cupertino";
import { seedSources } from "@/mocks/sources";
import { readLocal, writeLocal } from "@/lib/storage/preferences";
import type { Source } from "./types";
import type { FlareDataProvider } from "./provider";
import type { CreateItemInput, Insight, Item, ListItemOptions } from "./types";
const STORAGE_KEY = "flare-user-items-v1";
const DELETED_ITEMS_KEY = "flare-deleted-items-v1";
const LEGACY_DEMO_SOURCE_IDS = new Set([
  "telegram", "github", "linear", "notion", "drive", "gmail", "reviews", "slack",
]);
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const getUserItems = (): Item[] => {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter(
          (item): item is Item =>
            typeof item === "object" &&
            item !== null &&
            typeof item.id === "string" &&
            typeof item.title === "string" &&
            typeof item.content === "string" &&
            ["note", "url", "file", "audio"].includes(item.type) &&
            typeof item.createdAt === "string" &&
            Number.isFinite(Date.parse(item.createdAt)) &&
            Array.isArray(item.extractedFacts) &&
            Array.isArray(item.relatedItemIds),
        )
      : [];
  } catch {
    return [];
  }
};
const setUserItems = (items: Item[]) => {
  if (typeof window !== "undefined")
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
};
const getDeletedItemIds = (): string[] => {
  if (typeof window === "undefined") return [];
  try {
    const parsed: unknown = JSON.parse(
      window.localStorage.getItem(DELETED_ITEMS_KEY) ?? "[]",
    );
    return Array.isArray(parsed)
      ? parsed.filter((id): id is string => typeof id === "string")
      : [];
  } catch {
    return [];
  }
};
const titleFor = (input: CreateItemInput) =>
  input.title?.trim() ||
  (input.type === "url"
    ? (input.sourceUrl ?? "Untitled link")
    : input.type === "audio"
      ? "New voice memo"
      : (input.fileName ?? "Untitled note"));
export class MockDataProvider implements FlareDataProvider {
  async listSources(): Promise<Source[]> {
    const saved = readLocal<Source[] | null>("flare-sources-v1", null);
    if (!Array.isArray(saved)) return clone(seedSources);
    const savedById = new Map(saved.map((source) => [source.id, source]));
    const seededIds = new Set(seedSources.map((source) => source.id));
    return clone([
      ...seedSources.map((source) =>
        source.status === "ready" ? (savedById.get(source.id) ?? source) : source,
      ),
      ...saved.filter(
        (source) =>
          !seededIds.has(source.id) && !LEGACY_DEMO_SOURCE_IDS.has(source.id),
      ),
    ]);
  }
  async saveSource(source: Source): Promise<Source> {
    const sources = await this.listSources();
    const index = sources.findIndex((s) => s.id === source.id);
    if (index < 0) sources.push(source);
    else sources[index] = source;
    writeLocal("flare-sources-v1", sources);
    return source;
  }
  async listItems(options: ListItemOptions = {}): Promise<Item[]> {
    const query = options.query?.toLowerCase().trim() ?? "";
    const deleted = new Set(getDeletedItemIds());
    return [...getUserItems(), ...clone(seedItems)]
      .filter((item) => !deleted.has(item.id))
      .filter(
        (item) =>
          (options.type ?? "all") === "all" || item.type === options.type,
      )
      .filter(
        (item) =>
          !query ||
          `${item.title} ${item.content}`.toLowerCase().includes(query),
      )
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .slice(0, options.limit);
  }
  async getItem(id: string) {
    return (await this.listItems()).find((item) => item.id === id) ?? null;
  }
  async createItem(input: CreateItemInput): Promise<Item> {
    const item: Item = {
      id: `local-${crypto.randomUUID()}`,
      type: input.type,
      title: titleFor(input),
      content:
        input.content?.trim() ||
        (input.type === "audio"
          ? "Audio captured locally. A demo transcript will be available while processing."
          : "No original content available."),
      sourceUrl: input.sourceUrl,
      fileName: input.fileName,
      fileSize: input.fileSize,
      fileType: input.fileType,
      status: input.status ?? "ready",
      createdAt: new Date().toISOString(),
      extractedFacts: [],
      relatedItemIds: [],
    };
    setUserItems([item, ...getUserItems()]);
    return item;
  }
  async deleteItem(id: string): Promise<void> {
    setUserItems(getUserItems().filter((item) => item.id !== id));
    const deleted = new Set(getDeletedItemIds());
    deleted.add(id);
    if (typeof window !== "undefined")
      window.localStorage.setItem(DELETED_ITEMS_KEY, JSON.stringify([...deleted]));
  }
  async listInsights(): Promise<Insight[]> {
    return clone(seedInsights);
  }
  async getInsight(id: string) {
    return clone(seedInsights).find((insight) => insight.id === id) ?? null;
  }
  async resetDemoData() {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem(DELETED_ITEMS_KEY);
    }
  }
}
