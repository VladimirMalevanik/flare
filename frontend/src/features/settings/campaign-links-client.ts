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

export async function campaignLinksCapability(signal?: AbortSignal): Promise<boolean> {
  const value = record(await request("/capability", { signal }));
  if (typeof value.allowed !== "boolean") {
    throw new CampaignLinkError("The server returned an invalid campaign link capability.");
  }
  return value.allowed;
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

export type CampaignActivity = {
  days: 7 | 30 | 90;
  timezone: "UTC";
  generatedAt: string;
  recordingStartedAt: string | null;
  totalOpens: number;
  daily: { date: string; opens: number | null }[];
  topLinks: { id: string; label: string; opens: number; archivedAt: string | null }[];
};

export function mapCampaignActivity(value: unknown): CampaignActivity {
  const item = record(value);
  const fail = (): never => { throw new CampaignLinkError("The server returned an invalid campaign activity report."); };
  const count = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0;
  if (![7, 30, 90].includes(item.days as number) || item.timezone !== "UTC" ||
      !count(item.totalOpens) || !Array.isArray(item.daily) || item.daily.length !== item.days ||
      !Array.isArray(item.topLinks) || item.topLinks.length > 10) return fail();
  const generatedAt = text(item, "generatedAt");
  if (!Number.isFinite(Date.parse(generatedAt))) return fail();
  const recordingStartedAt = nullableDate(item, "recordingStartedAt");
  const end = new Date(generatedAt).toISOString().slice(0, 10);
  const start = Date.parse(`${end}T00:00:00Z`) - ((item.days as number) - 1) * 86400000;
  const coverage = recordingStartedAt ? new Date(recordingStartedAt).toISOString().slice(0, 10) : null;
  const daily = item.daily.map((raw, index) => {
    const row = record(raw), day = new Date(start + index * 86400000).toISOString().slice(0, 10);
    if (row.date !== day || !(row.opens === null || count(row.opens)) ||
        ((coverage === null || day < coverage) !== (row.opens === null))) return fail();
    return { date: day, opens: row.opens as number | null };
  });
  if (daily.reduce((sum, day) => sum + (day.opens ?? 0), 0) !== item.totalOpens) return fail();
  const ids = new Set<string>();
  const topLinks = item.topLinks.map(raw => {
    const row = record(raw), id = text(row, "id"), label = text(row, "label");
    if (!id || !label || label.length > 80 || ids.has(id) || !count(row.opens) || row.opens > (item.totalOpens as number)) return fail();
    ids.add(id);
    return { id, label, opens: row.opens, archivedAt: nullableDate(row, "archivedAt") };
  });
  if (topLinks.reduce((sum, link) => sum + link.opens, 0) > item.totalOpens) return fail();
  return { days: item.days as 7 | 30 | 90, timezone: "UTC", generatedAt,
    recordingStartedAt, totalOpens: item.totalOpens, daily, topLinks };
}

export async function getCampaignActivity(days: 7 | 30 | 90, linkId: string | null, signal?: AbortSignal): Promise<CampaignActivity> {
  if (![7, 30, 90].includes(days) || (linkId !== null && (!linkId || linkId.length > 100))) {
    throw new CampaignLinkError("Choose a valid campaign activity filter.");
  }
  const value = await request(`/activity?days=${days}${linkId ? `&linkId=${encodeURIComponent(linkId)}` : ""}`, { signal });
  const result = mapCampaignActivity(value);
  if (result.days !== days || (linkId !== null && (result.topLinks.length !== 1 || result.topLinks[0].id !== linkId))) {
    throw new CampaignLinkError("The server returned activity for a different filter.");
  }
  return result;
}
