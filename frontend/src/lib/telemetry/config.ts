export interface TelemetryConfig { connectionString: string; ingestionOrigin: string }
export interface SafePage { name: string; uri: string }
export const CANONICAL_ORIGIN = "https://flare4u.tech";
const pages: Readonly<Record<string, string>> = Object.freeze({
  "/": "Home", "/login": "Login", "/register": "Register", "/download": "Download",
  "/privacy": "Privacy", "/terms": "Terms", "/verify-email": "Verify email",
  "/legal-acceptance": "Legal acceptance", "/dashboard": "Dashboard",
  "/insights": "Insights", "/vault": "Vault", "/sources": "Sources", "/settings": "Settings",
  "/settings/import-guides/notion": "Notion import guide",
  "/settings/import-guides/obsidian": "Obsidian import guide",
  "/settings/import-guides/evernote": "Evernote import guide",
});

export function parseTelemetryConfig(connectionString: string | undefined, enabled: string | undefined): TelemetryConfig | null {
  if (enabled !== "true") return null;
  const invalid = () => new Error("Application Insights configuration is invalid");
  if (!connectionString || connectionString.length > 2048) throw invalid();
  const fields = new Map<string, string>();
  for (const part of connectionString.split(";")) {
    if (!part.trim()) continue;
    const separator = part.indexOf("=");
    if (separator <= 0) throw invalid();
    const name = part.slice(0, separator).trim().toLowerCase();
    const value = part.slice(separator + 1).trim();
    if (fields.has(name)) throw invalid();
    fields.set(name, value);
  }
  const key = fields.get("instrumentationkey");
  const endpoint = fields.get("ingestionendpoint");
  if (!key || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(key)
      || !endpoint || !/^https:\/\/[a-z0-9-]+\.in\.applicationinsights\.azure\.com\/?$/.test(endpoint)) throw invalid();
  const origin = new URL(endpoint).origin;
  // Keep only the browser ingestion fields. No live endpoint, auth or caller
  // supplied SDK configuration is propagated from the public connection string.
  return { connectionString: `InstrumentationKey=${key};IngestionEndpoint=${origin}/`, ingestionOrigin: origin };
}

export function safePage(pathname: string): SafePage | null {
  if (typeof pathname !== "string" || pathname.length > 2048) return null;
  const path = pathname.split(/[?#]/, 1)[0];
  const name = Object.hasOwn(pages, path) ? pages[path] : null;
  return name ? { name, uri: CANONICAL_ORIGIN + path } : null;
}

export function safeTelemetryPage(uri: unknown): SafePage | null {
  if (typeof uri !== "string" || uri.length > 2048) return null;
  try {
    const url = new URL(uri);
    return url.origin === CANONICAL_ORIGIN && !url.username && !url.password ? safePage(url.pathname) : null;
  } catch { return null; }
}
