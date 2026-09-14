"use client";
import {
  contextInsights as seedInsights,
  contextItems as seedItems,
} from "@/mocks/cupertino";
import { seedSources } from "@/mocks/sources";
import { readLocal, writeLocal } from "@/lib/storage/preferences";
import type { Source } from "./types";
import type { AnalyticsEventInput, FlareDataProvider } from "./provider";
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
  UpdateItemInput,
} from "./types";
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
        ).map((item) => ({
          ...item,
          currentVersionId: typeof item.currentVersionId === "string"
            ? item.currentVersionId
            : `${item.id}-version-1`,
          versionNumber: typeof item.versionNumber === "number" ? item.versionNumber : 1,
          updatedAt: typeof item.updatedAt === "string" ? item.updatedAt : item.createdAt,
        }))
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

type ZonedParts = {
  date: string;
  minuteOfDay: number;
};

const zonedParts = (value: Date, timezone: string): ZonedParts => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value);
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value ?? "0");
  const year = read("year");
  const month = read("month");
  const day = read("day");
  return {
    date: `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}-${day.toString().padStart(2, "0")}`,
    minuteOfDay: read("hour") * 60 + read("minute"),
  };
};

const addLocalDays = (date: string, days: number) => {
  const [year, month, day] = date.split("-").map(Number);
  const result = new Date(Date.UTC(year, month - 1, day + days));
  return result.toISOString().slice(0, 10);
};

// Resolve a local wall-clock time without assuming a fixed UTC offset. Scanning
// also mirrors PostgreSQL AT TIME ZONE: the standard-time occurrence on overlaps
// and the first valid minute after a clock gap.
const localInstant = (date: string, localTime: string, timezone: string) => {
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = localTime.split(":").map(Number);
  const targetMinute = hour * 60 + minute;
  const center = Date.UTC(year, month - 1, day, hour, minute);
  let gapCandidate: Date | null = null;
  let gapMinute = Number.POSITIVE_INFINITY;
  let exactCandidate: Date | null = null;
  for (let offset = -18 * 60; offset <= 18 * 60; offset += 1) {
    const candidate = new Date(center + offset * 60_000);
    const local = zonedParts(candidate, timezone);
    if (local.date !== date) continue;
    if (local.minuteOfDay === targetMinute) {
      exactCandidate = candidate;
      continue;
    }
    if (local.minuteOfDay > targetMinute && local.minuteOfDay < gapMinute) {
      gapCandidate = candidate;
      gapMinute = local.minuteOfDay;
    }
  }
  return exactCandidate ?? gapCandidate;
};

const nextScheduleWindow = (
  now: Date,
  timezone: string,
  localTime: string,
  leadMinutes: number,
  skipToday = false,
) => {
  const today = zonedParts(now, timezone).date;
  for (let dayOffset = skipToday ? 1 : 0; dayOffset < 4; dayOffset += 1) {
    const runAt = localInstant(addLocalDays(today, dayOffset), localTime, timezone);
    if (runAt && runAt.getTime() - now.getTime() >= leadMinutes * 60_000) {
      return {
        nextRunAt: runAt.toISOString(),
        nextRefreshAt: new Date(runAt.getTime() - leadMinutes * 60_000).toISOString(),
      };
    }
  }
  throw new Error("Could not calculate the next demo schedule window.");
};

export class MockDataProvider implements FlareDataProvider {
  private analysisRuns = new Map<string, AnalysisRun>();
  private dailyRun: AnalysisRun | null = null;
  private dailyRunDate: string | null = null;
  private dailyMode: DailyAnalysisStatus["mode"] = null;
  private schedule: AnalysisSchedule = {
    enabled: false,
    timezone: "Europe/Moscow",
    localTime: "19:00",
    leadMinutes: 30,
    nextRefreshAt: null,
    nextRunAt: null,
    updatedAt: new Date().toISOString(),
  };
  private rollDailyState(now: Date) {
    const localDate = zonedParts(now, this.schedule.timezone).date;
    if (this.dailyRunDate && this.dailyRunDate !== localDate) {
      this.dailyRun = null;
      this.dailyRunDate = null;
      this.dailyMode = null;
    }
    if (!this.schedule.enabled || !this.schedule.nextRunAt) return localDate;
    const scheduledDate = zonedParts(new Date(this.schedule.nextRunAt), this.schedule.timezone).date;
    if (scheduledDate < localDate) {
      const next = nextScheduleWindow(now, this.schedule.timezone, this.schedule.localTime, this.schedule.leadMinutes);
      this.schedule = { ...this.schedule, ...next };
    } else if (!this.dailyRun && scheduledDate === localDate && now >= new Date(this.schedule.nextRunAt)) {
      const id = `scheduled-${localDate}`;
      const run: AnalysisRun = {
        id,
        status: "completed",
        stage: "completed",
        selectedChunkCount: 1,
        flareIds: seedInsights.slice(0, 3).map((flare) => flare.id),
        error: null,
      };
      this.analysisRuns.set(id, run);
      this.dailyRun = run;
      this.dailyRunDate = localDate;
      this.dailyMode = "scheduled";
    }
    return localDate;
  }
  async startAnalysis(key: string): Promise<AnalysisRun> {
    const prior = this.analysisRuns.get(key);
    if (prior) return clone(prior);
    const now = new Date();
    const localDate = this.rollDailyState(now);
    if (this.dailyRun) throw new Error("daily_limit");
    const refreshDueAt = this.schedule.nextRefreshAt ? new Date(this.schedule.nextRefreshAt) : null;
    if (this.schedule.enabled && refreshDueAt && now >= refreshDueAt) throw new Error("daily_limit");
    const run: AnalysisRun = { id: key, status: "completed", stage: "completed",
      selectedChunkCount: 1, flareIds: seedInsights.slice(0, 3).map(flare => flare.id), error: null };
    this.analysisRuns.set(key, run);
    this.dailyRun = run;
    this.dailyRunDate = localDate;
    this.dailyMode = "manual";
    return clone(run);
  }
  async getAnalysisRun(id: string): Promise<AnalysisRun> {
    const run = this.analysisRuns.get(id);
    if (!run) throw new Error("Demo run not found.");
    return clone(run);
  }

  async getAnalysisSchedule(): Promise<AnalysisSchedule> {
    return clone(this.schedule);
  }
  async updateAnalysisSchedule(input: {
    enabled: boolean;
    timezone: string;
    localTime: string;
  }): Promise<AnalysisSchedule> {
    const now = new Date();
    const localDate = this.rollDailyState(now);
    const skipToday = this.dailyRunDate === localDate;
    const next = input.enabled
      ? nextScheduleWindow(now, input.timezone, input.localTime, 30, skipToday)
      : { nextRefreshAt: null, nextRunAt: null };
    this.schedule = {
      ...input,
      leadMinutes: 30,
      ...next,
      updatedAt: now.toISOString(),
    };
    return clone(this.schedule);
  }
  async getDailyAnalysisStatus(): Promise<DailyAnalysisStatus> {
    const now = new Date();
    const localDate = this.rollDailyState(now);
    const run = this.dailyRun;
    const refreshDueAt = this.schedule.nextRefreshAt ? new Date(this.schedule.nextRefreshAt) : null;
    const reserved = Boolean(this.schedule.enabled && refreshDueAt && now >= refreshDueAt);
    const state: DailyAnalysisStatus["state"] = run
      ? run.status === "pending" ? "queued" : run.status
      : reserved ? "ready" : "available";
    return {
      localDate,
      timezone: this.schedule.timezone,
      state,
      cycleId: run?.id ?? (reserved ? `cycle-${localDate}` : null),
      runId: run?.id ?? null,
      mode: run ? this.dailyMode : reserved ? "scheduled" : null,
      scheduledFor: this.schedule.nextRunAt,
      refreshDueAt: this.schedule.nextRefreshAt,
      sourceSnapshotCount: run?.selectedChunkCount ?? (reserved ? seedItems.length : 0),
      canRequestToday: !run && !reserved,
      reason: run || reserved ? "daily_limit" : null,
      sync: {
        status: reserved ? "succeeded" : "not_started",
        github: { connected: false, ingestionSupported: false, status: "not_connected" },
      },
    };
  }

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
  async getGitHubConnection(): Promise<GitHubConnection> {
    return { status: "disconnected" };
  }
  async startGitHubConnection(): Promise<string> {
    throw new Error("GitHub connection requires the Flare API.");
  }
  async listGitHubRepositories(): Promise<GitHubRepository[]> {
    return [];
  }
  async selectGitHubRepository(): Promise<GitHubConnection> {
    throw new Error("GitHub connection requires the Flare API.");
  }
  async disconnectGitHub(): Promise<void> {}
  async listItems(options: ListItemOptions = {}): Promise<Item[]> {
    if ((options.beforeUpdatedAt === undefined) !== (options.beforeId === undefined)) {
      throw new Error("Both item cursor fields are required.");
    }
    const query = options.query?.toLowerCase().trim() ?? "";
    const deleted = new Set(getDeletedItemIds());
    const userItems = getUserItems();
    const overridden = new Set(userItems.map((item) => item.id));
    return [...userItems, ...clone(seedItems).filter((item) => !overridden.has(item.id))]
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
      .sort((a, b) =>
        b.updatedAt.localeCompare(a.updatedAt) || b.id.localeCompare(a.id),
      )
      .filter((item) => {
        if (options.beforeUpdatedAt === undefined || options.beforeId === undefined) return true;
        const itemTime = Date.parse(item.updatedAt);
        const cursorTime = Date.parse(options.beforeUpdatedAt);
        return itemTime < cursorTime || (itemTime === cursorTime && item.id < options.beforeId);
      })
      .slice(0, options.limit ?? 50);
  }
  async getItem(id: string) {
    return (await this.listItems()).find((item) => item.id === id) ?? null;
  }
  async createItem(input: CreateItemInput): Promise<Item> {
    if (input.type === "audio") {
      throw new Error("Voice transcription requires the Flare API.");
    }
    const now = new Date().toISOString();
    const id = `local-${crypto.randomUUID()}`;
    const item: Item = {
      id,
      currentVersionId: `${id}-version-1`,
      versionNumber: 1,
      type: input.type,
      title: titleFor(input),
      content:
        input.content?.trim() ||
        "No original content available.",
      sourceUrl: input.sourceUrl,
      fileName: input.fileName,
      fileSize: input.fileSize,
      fileType: input.fileType,
      status: input.status ?? "ready",
      createdAt: now,
      updatedAt: now,
      extractedFacts: [],
      relatedItemIds: [],
    };
    setUserItems([item, ...getUserItems()]);
    return item;
  }
  async updateItem(id: string, input: UpdateItemInput): Promise<Item> {
    const items = getUserItems();
    const index = items.findIndex((item) => item.id === id);
    const existing = index >= 0 ? items[index] : clone(seedItems).find((item) => item.id === id);
    if (!existing) throw new Error("Item not found.");
    if (existing.currentVersionId !== input.expectedCurrentVersionId) {
      throw new Error("This item changed while you were editing it. Reopen it and try again.");
    }
    const versionNumber = existing.versionNumber + 1;
    const title = input.title === undefined ? existing.title : input.title.trim();
    const content = input.content === undefined
      ? existing.content
      : input.type === "file"
        ? input.content
        : input.content.trim();
    if (!title || !content.trim()) throw new Error("Title and content are required.");
    const updated: Item = {
      ...existing,
      title,
      content,
      sourceUrl: input.sourceUrl ?? existing.sourceUrl,
      fileName: input.fileName ?? existing.fileName,
      fileSize: input.fileSize ?? existing.fileSize,
      fileType: input.fileType ?? existing.fileType,
      currentVersionId: `${id}-version-${versionNumber}`,
      versionNumber,
      updatedAt: new Date().toISOString(),
      extractedFacts: [],
    };
    if (index >= 0) items[index] = updated;
    else items.unshift(updated);
    setUserItems(items);
    return clone(updated);
  }
  async importTextFile(input: ImportTextFileInput): Promise<ImportResult> {
    const item = await this.createItem({
      type: "file",
      title: input.fileName,
      content: input.content,
      fileName: input.fileName,
      fileSize: input.fileSize,
      fileType: input.fileType,
    });
    return {
      id: `local-import-${crypto.randomUUID()}`,
      format: input.format,
      fileName: input.fileName,
      item,
      rowCount: input.format === "csv"
        ? Math.max(0, input.content.split(/\r?\n/).filter(Boolean).length - 1)
        : null,
      chunkCount: 1,
      analysisJobsQueued: 0,
    };
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
  async trackEvent(_event: AnalyticsEventInput): Promise<void> {}
  async resetDemoData() {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem(DELETED_ITEMS_KEY);
    }
  }
}
