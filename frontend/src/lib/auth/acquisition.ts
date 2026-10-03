/** No persisted URLs or attribution fields. The server owns the opaque cookie. */
const fields = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "ref"];
const routes = new Set(["/", "/login", "/register"]);
export const consentKey = "flare_measurement_opt_in";

export function landingTouch(href: string, referrer: string): Record<string, string> | null {
  if (href.length > 2048 || referrer.length > 2048) return null;
  try {
    const url = new URL(href);
    if (!routes.has(url.pathname) || url.search.length > 1024) return null;
    const touch: Record<string, string> = { landing_route: url.pathname };
    for (const key of fields) {
      const values = url.searchParams.getAll(key).map(value => value.trim().toLowerCase());
      if (new Set(values).size > 1 || values.some(value => !/^[a-z0-9._-]{1,80}$/.test(value))) return null;
      if (values.length) touch[key] = values[0];
    }
    // Encoded key spellings and double encoding are ambiguous; discard the touch.
    for (const part of url.search.slice(1).split("&")) {
      const key = part.split("=", 1)[0];
      if (key.includes("%") && fields.includes(decodeURIComponent(key))) return null;
    }
    if (referrer) {
      const from = new URL(referrer);
      const host = from.hostname.toLowerCase();
      if (["http:", "https:"].includes(from.protocol) && host !== url.hostname &&
          !host.endsWith(`.${url.hostname}`) && /^[a-z0-9.-]{1,80}$/.test(host)) touch.referrer_domain = host;
    }
    return touch;
  } catch { return null; }
}

export async function captureAcquisition(base: string): Promise<void> {
  try {
    const signal = AbortSignal.timeout(1000);
    const response = await fetch(`${base}/acquisition/policy`, { credentials: "include", cache: "no-store", signal });
    if (!response.ok) return;
    const policy = await response.json();
    if (!policy.enabled || policy.eligibility !== "explicit-opt-in" ||
        sessionStorage.getItem(consentKey) !== policy.revision) return;
    const touch = landingTouch(window.location.href, document.referrer);
    if (!touch) return;
    await fetch(`${base}/acquisition/touch`, { method: "POST", credentials: "include", signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ touch, revision: policy.revision, eligible: true }) });
  } catch { /* Storage denial/outages never block navigation or auth. */ }
}

export function resetAcquisitionConsent(): void {
  try { sessionStorage.removeItem(consentKey); } catch { /* optional storage */ }
}
