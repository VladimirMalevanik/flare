import type { FlareDataProvider } from "./provider";
import type {
  CreateItemInput,
  Insight,
  Item,
  ItemStatus,
  ItemType,
  ListItemOptions,
  Source,
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

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const record = body as Record<string, unknown>;
      if (typeof record.detail === "string") return record.detail;
      if (typeof record.message === "string") return record.message;
    }
  } catch {
    // The status text below is enough for non-JSON errors.
  }
  return response.statusText || `Request failed with status ${response.status}`;
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
    if (!response.ok) {
      throw new FlareApiError(await errorMessage(response), response.status);
    }
    if (response.status === 204) return undefined;
    return response.json();
  }

  listSources(): Promise<Source[]> {
    return this.fallback.listSources();
  }

  saveSource(source: Source): Promise<Source> {
    return this.fallback.saveSource(source);
  }

  async listItems(options: ListItemOptions = {}): Promise<Item[]> {
    const params = new URLSearchParams();
    if (options.query?.trim()) params.set("query", options.query.trim());
    if (options.type && options.type !== "all") params.set("type", options.type);
    if (options.limit !== undefined) params.set("limit", String(options.limit));
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
    if (input.type !== "note") {
      throw new FlareApiError(
        "The connected API currently supports notes only. File, URL, and audio capture are coming next.",
      );
    }
    const content = input.content?.trim() ?? "";
    if (!content) throw new FlareApiError("Write something before capturing it.");
    return mapItem(
      await this.request("/items", {
        method: "POST",
        body: JSON.stringify({
          type: "note",
          ...(input.title?.trim() ? { title: input.title.trim() } : {}),
          content,
        }),
      }),
    );
  }

  async deleteItem(id: string): Promise<void> {
    await this.request(`/items/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  listInsights(): Promise<Insight[]> {
    return this.fallback.listInsights();
  }

  getInsight(id: string): Promise<Insight | null> {
    return this.fallback.getInsight(id);
  }

  resetDemoData(): Promise<void> {
    return this.fallback.resetDemoData();
  }
}
