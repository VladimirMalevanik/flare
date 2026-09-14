import type { AnalyticsEventInput, FlareDataProvider } from "./provider";
import type {
  AnalysisRun,
  AnalysisSchedule,
  CreateItemInput,
  DailyAnalysisStatus,
  Insight,
  Item,
  ItemStatus,
  ItemType,
  ListItemOptions,
  Source,
  GitHubConnection,
  GitHubRepository,
  ImportFormat,
  ImportResult,
  ImportTextFileInput,
  UpdateItemInput,
} from "./types";

type ApiDataProviderOptions = {
  baseUrl: string;
  fallback: FlareDataProvider;
};

const itemTypes: ItemType[] = ["note", "url", "file", "audio"];
const itemStatuses: ItemStatus[] = ["ready", "processing", "error"];

export class FlareApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "FlareApiError";
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new FlareApiError("The server returned an invalid item.");
  }
  return value as Record<string, unknown>;
}

function stringField(value: Record<string, unknown>, key: string): string {
  if (typeof value[key] !== "string") {
    throw new FlareApiError(`The server response is missing ${key}.`);
  }
  return value[key];
}

function mapItem(value: unknown): Item {
  const dto = asRecord(value);
  const type = stringField(dto, "type");
  const status = stringField(dto, "status");
  if (!itemTypes.includes(type as ItemType)) {
    throw new FlareApiError(`The server returned an unknown item type: ${type}.`);
  }
  if (!itemStatuses.includes(status as ItemStatus)) {
    throw new FlareApiError(`The server returned an unknown item status: ${status}.`);
  }

  const createdAt = stringField(dto, "createdAt");
  if (!Number.isFinite(Date.parse(createdAt))) {
    throw new FlareApiError("The server returned an invalid creation date.");
  }
  const updatedAt = stringField(dto, "updatedAt");
  if (!Number.isFinite(Date.parse(updatedAt))) {
    throw new FlareApiError("The server returned an invalid update date.");
  }
  const versionNumber = numberField(dto, "versionNumber");
  if (!Number.isInteger(versionNumber) || versionNumber < 1) {
    throw new FlareApiError("The server returned an invalid item version.");
  }

  const facts = Array.isArray(dto.extractedFacts) ? dto.extractedFacts : [];
  const relatedIds = Array.isArray(dto.relatedItemIds)
    ? dto.relatedItemIds.filter((id): id is string => typeof id === "string")
    : [];

  return {
    id: stringField(dto, "id"),
    type: type as ItemType,
    title: stringField(dto, "title"),
    content: stringField(dto, "content"),
    status: status as ItemStatus,
    createdAt,
    updatedAt,
    currentVersionId: stringField(dto, "currentVersionId"),
    versionNumber,
    extractedFacts: facts.map((fact) => {
      const mapped = asRecord(fact);
      return {
        id: stringField(mapped, "id"),
        text: stringField(mapped, "text"),
      };
    }),
    relatedItemIds: relatedIds,
    ...(typeof dto.sourceUrl === "string" ? { sourceUrl: dto.sourceUrl } : {}),
    ...(typeof dto.fileName === "string" ? { fileName: dto.fileName } : {}),
    ...(typeof dto.fileSize === "number" ? { fileSize: dto.fileSize } : {}),
    ...(typeof dto.fileType === "string" ? { fileType: dto.fileType } : {}),
  };
}

function nullableDateField(dto: Record<string, unknown>, key: string): string | null {
  const value = dto[key];
  if (value === null) return null;
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) {
    throw new FlareApiError(`The server returned an invalid ${key}.`);
  }
  return value;
}

function mapAnalysisSchedule(value: unknown): AnalysisSchedule {
  const dto = asRecord(value);
  const localTime = stringField(dto, "localTime");
  const timezone = stringField(dto, "timezone");
  const updatedAt = stringField(dto, "updatedAt");
  if (typeof dto.enabled !== "boolean"
    || !/^([01]\d|2[0-3]):[0-5]\d$/.test(localTime)
    || !timezone.trim()
    || dto.leadMinutes !== 30
    || !Number.isFinite(Date.parse(updatedAt))) {
    throw new FlareApiError("The server returned an invalid analysis schedule.");
  }
  return {
    enabled: dto.enabled,
    timezone,
    localTime,
    leadMinutes: 30,
    nextRefreshAt: nullableDateField(dto, "nextRefreshAt"),
    nextRunAt: nullableDateField(dto, "nextRunAt"),
    updatedAt,
  };
}

const dailyStates: DailyAnalysisStatus["state"][] = [
  "available", "scheduled", "refreshing", "ready", "queued", "processing", "completed", "consumed", "failed",
];

function mapDailyAnalysisStatus(value: unknown): DailyAnalysisStatus {
  const dto = asRecord(value);
  const state = stringField(dto, "state") as DailyAnalysisStatus["state"];
  const sync = asRecord(dto.sync);
  const github = asRecord(sync.github);
  const syncStatus = stringField(sync, "status") as DailyAnalysisStatus["sync"]["status"];
  const githubStatus = stringField(github, "status") as DailyAnalysisStatus["sync"]["github"]["status"];
  if (!dailyStates.includes(state)
    || !["not_started", "running", "succeeded", "failed", "unknown"].includes(syncStatus)
    || ((state === "consumed") !== (syncStatus === "unknown"))
    || !["not_connected", "not_ingested"].includes(githubStatus)
    || typeof github.connected !== "boolean"
    || github.ingestionSupported !== false
    || typeof dto.canRequestToday !== "boolean"
    || !Number.isInteger(dto.sourceSnapshotCount) || (dto.sourceSnapshotCount as number) < 0
    || (dto.cycleId !== null && typeof dto.cycleId !== "string")
    || (dto.runId !== null && typeof dto.runId !== "string")
    || ![null, "manual", "scheduled"].includes(dto.mode as never)
    || ![null, "daily_limit", "no_eligible_context", "sync_failed"].includes(dto.reason as never)
    || !/^\d{4}-\d{2}-\d{2}$/.test(stringField(dto, "localDate"))) {
    throw new FlareApiError("The server returned an invalid daily analysis status.");
  }
  return {
    localDate: dto.localDate as string,
    timezone: stringField(dto, "timezone"),
    state,
    cycleId: dto.cycleId as string | null,
    runId: dto.runId as string | null,
    mode: dto.mode as DailyAnalysisStatus["mode"],
    scheduledFor: nullableDateField(dto, "scheduledFor"),
    refreshDueAt: nullableDateField(dto, "refreshDueAt"),
    sourceSnapshotCount: dto.sourceSnapshotCount as number,
    canRequestToday: dto.canRequestToday,
    reason: dto.reason as DailyAnalysisStatus["reason"],
    sync: {
      status: syncStatus,
      github: {
        connected: github.connected,
        ingestionSupported: false,
        status: githubStatus,
      },
    },
  };
}

function numberField(value: Record<string, unknown>, key: string): number {
  if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
    throw new FlareApiError(`The server response is missing ${key}.`);
  }
  return value[key];
}

function mapImportResult(value: unknown): ImportResult {
  const dto = asRecord(value);
  const format = stringField(dto, "format");
  if (format !== "csv" && format !== "txt" && format !== "md") {
    throw new FlareApiError("The server returned an unknown import format.");
  }
  const rowCount = dto.rowCount;
  if (rowCount !== null && (!Number.isInteger(rowCount) || (rowCount as number) < 0)) {
    throw new FlareApiError("The server returned an invalid import row count.");
  }
  const chunkCount = numberField(dto, "chunkCount");
  const analysisJobsQueued = numberField(dto, "analysisJobsQueued");
  if (!Number.isInteger(chunkCount) || chunkCount < 1 ||
      !Number.isInteger(analysisJobsQueued) || analysisJobsQueued < 0) {
    throw new FlareApiError("The server returned invalid import progress.");
  }
  return {
    id: stringField(dto, "id"),
    format: format as ImportFormat,
    fileName: stringField(dto, "fileName"),
    item: mapItem(dto.item),
    rowCount: rowCount as number | null,
    chunkCount,
    analysisJobsQueued,
  };
}

function mapFlare(value: unknown): Insight {
  const dto = asRecord(value);
  const type = stringField(dto, "type");
  if (type !== "Reminder" && type !== "Warning" && type !== "Recommendation") {
    throw new FlareApiError("The server returned an unknown Flare type.");
  }
  const action = dto.action;
  if (action !== null && typeof action !== "string") throw new FlareApiError("Invalid Flare action.");
  if (type === "Recommendation" && !action?.trim()) throw new FlareApiError("Recommendation requires an action.");
  const createdAt = stringField(dto, "createdAt");
  if (!Number.isFinite(Date.parse(createdAt))) throw new FlareApiError("Invalid Flare date.");
  if (!Array.isArray(dto.evidence) || dto.evidence.length < 1 || dto.evidence.length > 4) {
    throw new FlareApiError("Invalid Flare evidence.");
  }
  return {
    id: stringField(dto, "id"), type, title: stringField(dto, "title"),
    statement: stringField(dto, "statement"), action, reason: stringField(dto, "reason"), createdAt,
    evidence: dto.evidence.map((value) => {
      const e = asRecord(value);
      const sourceType = stringField(e, "sourceType");
      if (!itemTypes.includes(sourceType as ItemType)) throw new FlareApiError("Invalid evidence type.");
      if (e.sourceUrl !== null && typeof e.sourceUrl !== "string") throw new FlareApiError("Invalid source URL.");
      return { itemId: stringField(e, "itemId"), sourceTitle: stringField(e, "sourceTitle"),
        sourceType: sourceType as ItemType, excerpt: stringField(e, "excerpt"), sourceUrl: e.sourceUrl };
    }),
  };
}

async function responseError(
  response: Response,
): Promise<{ message: string; code?: string }> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const record = body as Record<string, unknown>;
      if (typeof record.detail === "string") {
        return { message: record.detail, code: record.detail };
      }
      if (typeof record.detail === "object" && record.detail !== null) {
        const detail = record.detail as Record<string, unknown>;
        if (typeof detail.message === "string") {
          return {
            message: detail.message,
            ...(typeof detail.code === "string" ? { code: detail.code } : {}),
          };
        }
      }
      if (typeof record.message === "string") return { message: record.message };
    }
  } catch {
    // The status text below is enough for non-JSON errors.
  }
  return {
    message: response.statusText || `Request failed with status ${response.status}`,
  };
}

function mapAnalysisRun(value: unknown): AnalysisRun {
  const dto = asRecord(value);
  const status = stringField(dto, "status");
  const stage = stringField(dto, "stage");
  if (!["pending", "processing", "completed", "failed"].includes(status)
    || !["analysis", "flare_generation", "completed", "failed"].includes(stage)
    || ((status === "completed" || status === "failed") ? stage !== status : !["analysis", "flare_generation"].includes(stage))
    || !Number.isInteger(dto.selectedChunkCount) || (dto.selectedChunkCount as number) < 1
    || (dto.selectedChunkCount as number) > 100
    || !Array.isArray(dto.flareIds) || dto.flareIds.length > 3 || dto.flareIds.some(id => typeof id !== "string")
    || (status !== "completed" && dto.flareIds.length !== 0)
    || (dto.error !== null && typeof dto.error !== "string")) {
    throw new FlareApiError("Invalid analysis status.");
  }
  return { id: stringField(dto, "id"), status: status as AnalysisRun["status"],
    stage: stage as AnalysisRun["stage"], selectedChunkCount: dto.selectedChunkCount as number,
    flareIds: dto.flareIds as string[], error: dto.error as string | null };
}

function mapGitHubRepository(value: unknown): GitHubRepository {
  const dto = asRecord(value);
  if (!Number.isInteger(dto.id) || (dto.id as number) <= 0 || typeof dto.private !== "boolean") {
    throw new FlareApiError("The server returned an invalid GitHub repository.");
  }
  return {
    id: dto.id as number,
    owner: stringField(dto, "owner"),
    name: stringField(dto, "name"),
    fullName: stringField(dto, "fullName"),
    private: dto.private,
    htmlUrl: stringField(dto, "htmlUrl"),
  };
}

function mapGitHubConnection(value: unknown): GitHubConnection {
  const dto = asRecord(value);
  const status = stringField(dto, "status");
  if (!["disconnected", "pending", "connected"].includes(status)) {
    throw new FlareApiError("The server returned an invalid GitHub connection status.");
  }
  if (dto.accountLogin !== null && dto.accountLogin !== undefined && typeof dto.accountLogin !== "string") {
    throw new FlareApiError("The server returned an invalid GitHub account.");
  }
  const repository = dto.repository === null || dto.repository === undefined
    ? null : mapGitHubRepository(dto.repository);
  if ((status === "connected") !== (repository !== null)) {
    throw new FlareApiError("The server returned an incomplete GitHub connection.");
  }
  return {
    status: status as GitHubConnection["status"],
    accountLogin: dto.accountLogin as string | null | undefined,
    repository,
  };
}

export class ApiDataProvider implements FlareDataProvider {
  private readonly baseUrl: string;
  private readonly fallback: FlareDataProvider;

  constructor({ baseUrl, fallback }: ApiDataProviderOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.fallback = fallback;
  }

  private async request(path: string, init?: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        credentials: "include",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          ...(init?.body ? { "Content-Type": "application/json" } : {}),
          ...init?.headers,
        },
      });
    } catch {
      throw new FlareApiError(
        "Cannot reach the Flare API. Check that the backend is running.",
      );
    }
    if (response.status === 401 && typeof window !== "undefined") {
      window.location.replace("/login");
    }
    if (!response.ok) {
      const error = await responseError(response);
      if (
        response.status === 403 &&
        error.code === "email_verification_required" &&
        typeof window !== "undefined"
      ) {
        window.location.replace("/verify-email?pending=1");
      }
      throw new FlareApiError(error.message, response.status, error.code);
    }
    if (response.status === 204) return undefined;
    return response.json();
  }

  async startAnalysis(key: string, signal?: AbortSignal): Promise<AnalysisRun> {
    return mapAnalysisRun(await this.request("/analyze", {
      method: "POST", headers: { "Idempotency-Key": key }, body: "{}", signal,
    }));
  }

  async getAnalysisRun(id: string, signal?: AbortSignal): Promise<AnalysisRun> {
    return mapAnalysisRun(await this.request(`/analysis-runs/${encodeURIComponent(id)}`, { signal }));
  }

  async getAnalysisSchedule(): Promise<AnalysisSchedule> {
    return mapAnalysisSchedule(await this.request("/analysis-schedule"));
  }

  async updateAnalysisSchedule(input: {
    enabled: boolean;
    timezone: string;
    localTime: string;
  }): Promise<AnalysisSchedule> {
    return mapAnalysisSchedule(await this.request("/analysis-schedule", {
      method: "PUT",
      body: JSON.stringify(input),
    }));
  }

  async getDailyAnalysisStatus(): Promise<DailyAnalysisStatus> {
    return mapDailyAnalysisStatus(await this.request("/analysis/daily-status"));
  }

  async listSources(): Promise<Source[]> {
    const sources = await this.fallback.listSources();
    let connection: GitHubConnection;
    try {
      connection = await this.getGitHubConnection();
    } catch (error) {
      const message = error instanceof Error ? error.message : "GitHub connection could not be loaded.";
      return sources.map((source) => source.id === "github" ? {
        ...source, status: "error", scope: "One repository", channels: [],
        description: "GitHub authorization is unavailable.", updated: "Connection error", error: message,
      } : source);
    }
    return sources.map((source) => {
      if (source.id !== "github") return source;
      if (connection.status === "connected" && connection.repository) {
        return { ...source, status: "connected", scope: connection.repository.fullName,
          description: "Authorized read-only. Repository activity ingestion comes in the next phase.",
          channels: [], updated: `Connected as ${connection.accountLogin ?? "GitHub account"}`,
          accountLogin: connection.accountLogin ?? undefined, repository: connection.repository };
      }
      if (connection.status === "pending") {
        return { ...source, status: "syncing", scope: "Choose one repository", channels: [],
          description: "GitHub is authorized. Select the repository Flare should connect.",
          updated: `Authorized as ${connection.accountLogin ?? "GitHub account"}`,
          accountLogin: connection.accountLogin ?? undefined };
      }
      return { ...source, status: "disconnected", scope: "One repository", channels: [],
        description: "Authorize the Flare GitHub App, then choose one repository.", updated: "Not connected" };
    });
  }

  saveSource(source: Source): Promise<Source> {
    return this.fallback.saveSource(source);
  }

  async getGitHubConnection(): Promise<GitHubConnection> {
    return mapGitHubConnection(await this.request("/integrations/github"));
  }

  async startGitHubConnection(): Promise<string> {
    const body = asRecord(await this.request("/integrations/github/start", {
      method: "POST", body: "{}",
    }));
    return stringField(body, "authorizationUrl");
  }

  async listGitHubRepositories(): Promise<GitHubRepository[]> {
    const body = await this.request("/integrations/github/repositories");
    if (!Array.isArray(body)) throw new FlareApiError("The server returned an invalid repository list.");
    return body.map(mapGitHubRepository);
  }

  async selectGitHubRepository(repositoryId: number): Promise<GitHubConnection> {
    return mapGitHubConnection(await this.request("/integrations/github/repository", {
      method: "POST", body: JSON.stringify({ repositoryId }),
    }));
  }

  async disconnectGitHub(): Promise<void> {
    await this.request("/integrations/github", { method: "DELETE" });
  }

  async listItems(options: ListItemOptions = {}): Promise<Item[]> {
    if ((options.beforeUpdatedAt === undefined) !== (options.beforeId === undefined)) {
      throw new FlareApiError("Both item cursor fields are required.");
    }
    const params = new URLSearchParams();
    if (options.query?.trim()) params.set("query", options.query.trim());
    if (options.type && options.type !== "all") params.set("type", options.type);
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    if (options.beforeUpdatedAt !== undefined) params.set("beforeUpdatedAt", options.beforeUpdatedAt);
    if (options.beforeId !== undefined) params.set("beforeId", options.beforeId);
    const query = params.size ? `?${params.toString()}` : "";
    const body = await this.request(`/items${query}`);
    if (!Array.isArray(body)) {
      throw new FlareApiError("The server returned an invalid item list.");
    }
    return body.map(mapItem);
  }

  async getItem(id: string): Promise<Item | null> {
    try {
      return mapItem(await this.request(`/items/${encodeURIComponent(id)}`));
    } catch (error) {
      if (error instanceof FlareApiError && error.status === 404) return null;
      throw error;
    }
  }

  async createItem(input: CreateItemInput): Promise<Item> {
    const content = input.content?.trim();
    if (!content && input.type === "note") {
      throw new FlareApiError("Write something before capturing it.");
    }
    const body = {
      type: input.type,
      title: input.title?.trim(),
      content,
      sourceUrl: input.type === "url" ? input.sourceUrl?.trim() : undefined,
      fileName: input.fileName?.trim(),
      fileSize: input.fileSize,
      fileType: input.fileType,
    };
    return mapItem(
      await this.request("/items", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(
          Object.entries(body).filter(([, value]) => value !== undefined),
        )),
      }),
    );
  }

  async updateItem(id: string, input: UpdateItemInput): Promise<Item> {
    const title = input.title?.trim();
    const content = input.content === undefined
      ? undefined
      : input.type === "file"
        ? input.content
        : input.content.trim();
    if (title !== undefined && !title) throw new FlareApiError("Title is required.");
    if (content !== undefined && !content.trim()) {
      throw new FlareApiError("Content is required.");
    }
    return mapItem(await this.request(`/items/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({
        expectedCurrentVersionId: input.expectedCurrentVersionId,
        ...(title !== undefined ? { title } : {}),
        ...(content !== undefined ? { content } : {}),
        ...(input.sourceUrl !== undefined ? { sourceUrl: input.sourceUrl.trim() } : {}),
        ...(input.fileName !== undefined ? { fileName: input.fileName.trim() } : {}),
        ...(input.fileSize !== undefined ? { fileSize: input.fileSize } : {}),
        ...(input.fileType !== undefined ? { fileType: input.fileType.trim() } : {}),
      }),
    }));
  }

  async importTextFile(input: ImportTextFileInput): Promise<ImportResult> {
    return mapImportResult(await this.request("/imports", {
      method: "POST",
      body: JSON.stringify({
        format: input.format,
        fileName: input.fileName,
        fileType: input.fileType,
        fileSize: input.fileSize,
        content: input.content,
      }),
    }));
  }

  async deleteItem(id: string): Promise<void> {
    await this.request(`/items/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  async listInsights(): Promise<Insight[]> {
    const body = await this.request("/flares");
    if (!Array.isArray(body)) throw new FlareApiError("The server returned an invalid Flare list.");
    return body.map(mapFlare);
  }

  async getInsight(id: string): Promise<Insight | null> {
    try {
      return mapFlare(await this.request(`/flares/${encodeURIComponent(id)}`));
    } catch (error) {
      if (error instanceof FlareApiError && error.status === 404) return null;
      throw error;
    }
  }

  async trackEvent(event: AnalyticsEventInput): Promise<void> {
    try {
      await this.request("/analytics/events", {
        method: "POST",
        body: JSON.stringify({
          eventType: event.eventType,
          targetType: event.targetType,
          targetId: event.targetId,
          metadata: event.metadata,
        }),
      });
    } catch {
      // Product telemetry must not block a user-facing action.
    }
  }

  resetDemoData(): Promise<void> {
    return this.fallback.resetDemoData();
  }
}
