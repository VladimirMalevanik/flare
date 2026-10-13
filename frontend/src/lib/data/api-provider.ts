import type { ImportPackage, ImportPackageReport, ZipSourceKind } from "./types";
import { importRequest, IMPORT_UPLOAD_MS } from "./import-request";
import { projectApiUrl } from "../team-context";
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
    ...(typeof dto.importPackageId === "string" ? { importPackageId: dto.importPackageId } : {}),
    ...(typeof dto.relativePath === "string" ? { relativePath: dto.relativePath } : {}),
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
    || typeof dto.emailNotificationsEnabled !== "boolean"
    || !/^([01]\d|2[0-3]):[0-5]\d$/.test(localTime)
    || !timezone.trim()
    || dto.leadMinutes !== 30
    || !Number.isFinite(Date.parse(updatedAt))) {
    throw new FlareApiError("The server returned an invalid analysis schedule.");
  }
  return {
    enabled: dto.enabled,
    emailNotificationsEnabled: dto.emailNotificationsEnabled,
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
        if (typeof detail.code === "string" && typeof detail.message !== "string") return { message: "Source operation could not complete.", code: detail.code };
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
  async getSourceConnections(signal?: AbortSignal): Promise<import("./types").SourceConnections> {
    return mapSourceConnections(await importRequest((signal) => this.request("/integrations/sources", { signal }), signal));
  }
  async connectSource(provider: import("./types").ConnectedProvider, signal?: AbortSignal): Promise<{url?: string; connected?: boolean}> {
    const row = asRecord(await importRequest((signal) => this.request(`/integrations/sources/${provider}/connect`, { method: "POST", body: "{}", signal }), signal));
    if (row.connected === true) return { connected: true };
    const url = stringField(row, "url");
    const destination = new URL(url);
    if (destination.protocol !== "https:" || !["accounts.google.com", "slack.com", "api.notion.com"].includes(destination.hostname)) throw new FlareApiError("Invalid source authorization");
    return { url };
  }
  async sourceResources(id: string, cursor?: string, signal?: AbortSignal): Promise<import("./types").SourceResourcePage> {
    const row = asRecord(await importRequest((signal) => this.request(`/integrations/sources/connection/${encodeURIComponent(id)}/resources${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`, { signal }), signal));
    return { resources: sourceResourceRows(row.resources), cursor: nullableString(row, "cursor"), scopeRevision: countField(row, "scopeRevision") };
  }
  async selectSourceResources(id: string, expectedRevision: number, resourceIds: string[], shareWithWorkspace: boolean, signal?: AbortSignal): Promise<void> {
    await importRequest((signal) => this.request(`/integrations/sources/connection/${encodeURIComponent(id)}/selection`, { method: "POST", body: JSON.stringify({ expectedRevision, resourceIds, shareWithWorkspace }), signal }), signal);
  }
  async sourceConnectionAction(id: string, action: "sync" | "cancel" | "disconnect", signal?: AbortSignal): Promise<void> {
    await importRequest((signal) => this.request(`/integrations/sources/connection/${encodeURIComponent(id)}/${action}`, { method: "POST", body: "{}", signal }), signal);
  }

  private readonly baseUrl: string;
  private readonly fallback: FlareDataProvider;

  constructor({ baseUrl, fallback }: ApiDataProviderOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.fallback = fallback;
  }

  private async request(path: string, init?: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(projectApiUrl(`${this.baseUrl}${path}`), {
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

  async getImportCapabilities(signal?: AbortSignal): Promise<{ available: boolean; maxUploadBytes: number | null }> {
    const body = asRecord(await importRequest((signal) => this.request("/imports/packages/capabilities", { signal }), signal));
    if (typeof body.available !== "boolean") throw new FlareApiError("Invalid import capability");
    return { available: body.available, maxUploadBytes: body.maxUploadBytes === null ? null : countField(body, "maxUploadBytes") };
  }
  async createImportPackage(input: { sourceKind: ZipSourceKind; fileName: string; fileSize: number; requestKey: string }, signal?: AbortSignal): Promise<ImportPackage> {
    return mapImportPackage(await importRequest((signal) => this.request("/imports/packages", { method: "POST", body: JSON.stringify(input), signal }), signal));
  }
  async uploadImportPackage(id: string, file: File, signal?: AbortSignal): Promise<ImportPackage> {
    return mapImportPackage(await importRequest((signal) => this.request(`/imports/packages/${encodeURIComponent(id)}/upload`, {
      method: "PUT", body: file, signal, headers: { "Content-Type": "application/octet-stream" },
    }), signal, IMPORT_UPLOAD_MS));
  }
  async importPackageAction(id: string, action: "finalize" | "cancel" | "retry", signal?: AbortSignal): Promise<ImportPackage> {
    return mapImportPackage(await importRequest((signal) => this.request(`/imports/packages/${encodeURIComponent(id)}/${action}`, { method: "POST", signal }), signal));
  }
  async getImportPackage(id: string, signal?: AbortSignal): Promise<ImportPackage> {
    return mapImportPackage(await importRequest((signal) => this.request(`/imports/packages/${encodeURIComponent(id)}`, { signal }), signal));
  }
  async listImportPackages(signal?: AbortSignal): Promise<ImportPackage[]> {
    const body = await importRequest((signal) => this.request("/imports/packages", { signal }), signal);
    if (!Array.isArray(body)) throw new FlareApiError("Invalid import response");
    return body.map(mapImportPackage);
  }
  async getImportPackageReport(id: string, after = -1, signal?: AbortSignal): Promise<ImportPackageReport> {
    const body = asRecord(await importRequest((signal) => this.request(`/imports/packages/${encodeURIComponent(id)}/entries?after=${after}`, { signal }), signal));
    if (!Array.isArray(body.entries)) throw new FlareApiError("Invalid import report");
    return { entries: body.entries.map((value) => {
      const row = asRecord(value);
      const status = stringField(row, "status");
      if (!["pending", "prepared", "skipped", "published", "failed"].includes(status)) throw new FlareApiError("Invalid entry status");
      return { ordinal: countField(row, "ordinal"), path: stringField(row, "path"), fileBytes: countField(row, "file_bytes"),
        skipReason: nullableString(row, "skip_reason"), status: status as ImportPackageReport["entries"][number]["status"], documentId: nullableString(row, "document_id") };
    }), nextCursor: body.nextCursor === null ? null : countField(body, "nextCursor") };
  }

  async startAnalysis(key: string, signal?: AbortSignal): Promise<AnalysisRun> {
    return mapAnalysisRun(await this.request("/analyze", {
      method: "POST", headers: { "Idempotency-Key": key }, body: "{}", signal,
    }));
  }

  async getAnalysisRun(id: string, signal?: AbortSignal): Promise<AnalysisRun> {
    return mapAnalysisRun(await this.request(`/analysis-runs/${encodeURIComponent(id)}`, { signal }));
  }

  async getAnalysisSchedule(signal?: AbortSignal): Promise<AnalysisSchedule> {
    return mapAnalysisSchedule(await importRequest((signal) => this.request("/analysis-schedule", { signal }), signal));
  }

  async updateAnalysisSchedule(input: {
    enabled: boolean;
    emailNotificationsEnabled: boolean;
    timezone: string;
    localTime: string;
  }): Promise<AnalysisSchedule> {
    return mapAnalysisSchedule(await this.request("/analysis-schedule", {
      method: "PUT",
      body: JSON.stringify(input),
    }));
  }

  async getDailyAnalysisStatus(signal?: AbortSignal): Promise<DailyAnalysisStatus> {
    return mapDailyAnalysisStatus(await importRequest((signal) => this.request("/analysis/daily-status", { signal }), signal));
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
          description: "Repository connection is active.",
          channels: [], updated: "Choose which repository context to sync below.",
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
      if (event.eventType === "voluntary_inspection") {
        await this.request("/analytics/inspection", { method: "POST", body: JSON.stringify({
          interactionId: event.interactionId, flareId: event.flareId, sourceId: event.sourceId,
        }) });
        return;
      }
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

function countField(row: Record<string, unknown>, key: string): number {
  const value = row[key];
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new FlareApiError("Invalid import count");
  return value;
}
function nullableString(row: Record<string, unknown>, key: string): string | null {
  return row[key] === null ? null : stringField(row, key);
}
export function mapImportPackage(value: unknown): ImportPackage {
  const row = asRecord(value), status = stringField(row, "status"), phase = stringField(row, "phase"), sourceKind = stringField(row, "source_kind");
  if (!["uploading", "staged", "queued", "processing", "retry_wait", "completed", "completed_with_skips", "failed", "cancelled", "expired", "duplicate"].includes(status)
      || !["upload", "inspect", "parse", "publish", "complete"].includes(phase)
      || !["notion", "obsidian"].includes(sourceKind) || typeof row.retryable !== "boolean") throw new FlareApiError("Invalid import state");
  return { id: stringField(row, "id"), sourceKind: sourceKind as ZipSourceKind, fileName: stringField(row, "file_name"), fileSize: countField(row, "file_size"),
    canonicalId: nullableString(row, "canonical_id"),
    status: status as ImportPackage["status"], phase: phase as ImportPackage["phase"], entryCount: row.entry_count === null ? null : countField(row, "entry_count"),
    supportedCount: countField(row, "prepared_count"), skippedCount: countField(row, "skipped_count"), importedCount: countField(row, "published_count"),
    chunkCount: countField(row, "chunk_count"), failedCount: countField(row, "failed_count"), errorCode: nullableString(row, "error_code"), retryable: row.retryable };
}

const connectedProviders = ["slack", "gmail", "drive", "notion", "github"];
function sourceResourceRows(value: unknown): import("./types").SourceResource[] {
  if (!Array.isArray(value) || value.length > 10000) throw new FlareApiError("Invalid source resources");
  return value.map(value => { const row = asRecord(value); return { id: stringField(row, "id"), name: stringField(row, "name"), kind: stringField(row, "kind") }; });
}
function sourceCounts(value: unknown): import("./types").SourceCounts {
  const row = asRecord(value);
  return { added: countField(row, "added"), updated: countField(row, "updated"), unchanged: countField(row, "unchanged"), skipped: countField(row, "skipped"), conflicts: countField(row, "conflicts"), more: row.more === true };
}
export function mapSourceConnections(value: unknown): import("./types").SourceConnections {
  const body = asRecord(value);
  if (!Array.isArray(body.providers) || !Array.isArray(body.connections) || body.connections.length > 5) throw new FlareApiError("Invalid source connections");
  return { providers: body.providers.map(value => {
    const row = asRecord(value), provider = stringField(row, "provider");
    if (!connectedProviders.includes(provider) || typeof row.available !== "boolean" || typeof row.syncAvailable !== "boolean") throw new FlareApiError("Invalid source capability");
    return { provider: provider as import("./types").ConnectedProvider, available: row.available, syncAvailable: row.syncAvailable };
  }), connections: body.connections.map(value => {
    const row = asRecord(value), provider = stringField(row, "provider"), status = stringField(row, "status");
    if (!connectedProviders.includes(provider) || !["pending", "connected", "ready", "syncing", "error", "disabled"].includes(status) || typeof row.owner !== "boolean" || typeof row.canDisconnect !== "boolean" || typeof row.enabled !== "boolean") throw new FlareApiError("Invalid source connection");
    const job = row.job === null ? null : asRecord(row.job);
    return { id: stringField(row, "id"), provider: provider as import("./types").ConnectedProvider, status: status as import("./types").SourceConnection["status"], owner: row.owner, canDisconnect: row.canDisconnect, enabled: row.enabled, accountLabel: nullableString(row, "accountLabel"), scopeRevision: countField(row, "scopeRevision"), resources: sourceResourceRows(row.resources), lastSyncAt: nullableDateField(row, "lastSyncAt"), nextSyncAt: nullableDateField(row, "nextSyncAt"), errorCode: nullableString(row, "errorCode"), lastResult: row.lastResult === null ? null : sourceCounts(row.lastResult), job: job ? { ...sourceCounts(job), id: stringField(job, "id"), status: stringField(job, "status"), errorCode: nullableString(job, "errorCode") } : null };
  }) };
}
