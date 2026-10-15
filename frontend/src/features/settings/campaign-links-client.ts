import { apiBaseUrl } from "@/lib/auth/session";
import { projectApiUrl } from "@/lib/team-context";

export type CampaignLink = {
  id: string;
  label: string;
  slug: string;
  shortUrl: string;
  destinationPath: string;
  utmSource: string;
  utmMedium: string;
  utmCampaign: string;
  utmContent: string | null;
  clickCount: number;
  createdAt: string;
  archivedAt: string | null;
};

export type CampaignLinkDraft = {
  label: string;
  destinationPath: string;
  utmSource: string;
  utmMedium: string;
  utmCampaign: string;
  utmContent: string;
};

export class CampaignLinkError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "CampaignLinkError";
  }
}

export class CampaignLinkDraftError extends CampaignLinkError {
  constructor(message: string) {
    super(message);
    this.name = "CampaignLinkDraftError";
  }
}

const destinations = new Set(["/", "/register", "/login"]);
const token = /^[a-z0-9._-]{1,80}$/;

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new CampaignLinkError("The server returned an invalid campaign link.");
  }
  return value as Record<string, unknown>;
}

function text(value: Record<string, unknown>, key: string): string {
  if (typeof value[key] !== "string") {
    throw new CampaignLinkError("The server returned an invalid campaign link.");
  }
  return value[key];
}

function nullableDate(value: Record<string, unknown>, key: string): string | null {
  const result = value[key];
  if (result === null) return null;
  if (typeof result !== "string" || !Number.isFinite(Date.parse(result))) {
    throw new CampaignLinkError("The server returned an invalid campaign link.");
  }
  return result;
}

export function mapCampaignLink(value: unknown): CampaignLink {
  const item = record(value);
  const clickCount = item.clickCount;
  const destinationPath = text(item, "destinationPath");
  const utmContent = item.utmContent;
  const createdAt = text(item, "createdAt");
  if (!Number.isSafeInteger(clickCount) || (clickCount as number) < 0 ||
      !destinations.has(destinationPath) || !Number.isFinite(Date.parse(createdAt)) ||
      !(utmContent === null || typeof utmContent === "string")) {
    throw new CampaignLinkError("The server returned an invalid campaign link.");
  }
  return {
    id: text(item, "id"),
    label: text(item, "label"),
    slug: text(item, "slug"),
    shortUrl: text(item, "shortUrl"),
    destinationPath,
    utmSource: text(item, "utmSource"),
    utmMedium: text(item, "utmMedium"),
    utmCampaign: text(item, "utmCampaign"),
    utmContent,
    clickCount: clickCount as number,
    createdAt,
    archivedAt: nullableDate(item, "archivedAt"),
  };
}

export function normalizeCampaignDraft(value: CampaignLinkDraft): CampaignLinkDraft {
  const normalized = {
    label: value.label.trim(),
    destinationPath: value.destinationPath,
    utmSource: value.utmSource.trim().toLowerCase(),
    utmMedium: value.utmMedium.trim().toLowerCase(),
    utmCampaign: value.utmCampaign.trim().toLowerCase(),
    utmContent: value.utmContent.trim().toLowerCase(),
  };
  if (!normalized.label || normalized.label.length > 80 || /[\x00-\x1f\x7f]/.test(normalized.label) ||
      !destinations.has(normalized.destinationPath) || !token.test(normalized.utmSource) ||
      !token.test(normalized.utmMedium) || !token.test(normalized.utmCampaign) ||
      (normalized.utmContent && !token.test(normalized.utmContent))) {
    throw new CampaignLinkDraftError("Check the campaign link fields.");
  }
  return normalized;
}

async function request(path: string, options: RequestInit = {}): Promise<unknown> {
  const response = await fetch(projectApiUrl(`${apiBaseUrl}/campaign-links${path}`), {
    credentials: "include",
    cache: "no-store",
    ...options,
  });
  if (!response.ok) {
    throw new CampaignLinkError("Campaign links could not be updated. Please retry.", response.status);
  }
  return response.status === 204 ? null : await response.json();
}

export async function listCampaignLinks(signal?: AbortSignal): Promise<CampaignLink[]> {
  const value = await request("", { signal });
  const rows = Array.isArray(value) ? value : record(value).links;
  if (!Array.isArray(rows)) throw new CampaignLinkError("The server returned an invalid campaign link list.");
  return rows.map(mapCampaignLink);
}

export async function createCampaignLink(draft: CampaignLinkDraft): Promise<CampaignLink> {
  const value = normalizeCampaignDraft(draft);
  return mapCampaignLink(await request("", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      label: value.label,
      destinationPath: value.destinationPath,
      utmSource: value.utmSource,
      utmMedium: value.utmMedium,
      utmCampaign: value.utmCampaign,
      ...(value.utmContent ? { utmContent: value.utmContent } : {}),
    }),
  }));
}

export async function archiveCampaignLink(id: string): Promise<void> {
  if (!id || id.length > 100) throw new CampaignLinkError("Campaign link is unavailable.");
  await request(`/${encodeURIComponent(id)}/archive`, { method: "POST" });
}
