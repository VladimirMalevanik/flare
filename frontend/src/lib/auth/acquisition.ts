import { privacySignalBlocked } from "@/lib/telemetry/consent";
/** No persisted URLs or attribution fields. The server owns the opaque cookie. */
const fields = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "ref"];
const routes = new Set(["/", "/login", "/register"]);
export const consentKey = "flare_measurement_opt_in";
export const rejectionKey = "flare_measurement_rejected";
export const measurementRevision = "x-launch-2026-10-v1";
export const measurementNotice = "measurement-x-v1";
export interface AcquisitionPolicy {
  enabled: true; revision: string; noticeId: string;
  eligibility: "explicit-opt-in"; cookieSeconds: number;
}
let pendingTouch: Promise<void> | null = null;

export function acquisitionPrivacyBlocked(): boolean {
  return typeof navigator !== "undefined" && privacySignalBlocked(
    navigator as Navigator & { globalPrivacyControl?: boolean; msDoNotTrack?: string },
    typeof window === "undefined" ? undefined : window as Window & { doNotTrack?: string },
  );
}

export async function acquisitionPolicy(base: string, signal = AbortSignal.timeout(1000)): Promise<AcquisitionPolicy | null> {
  try {
    const response = await fetch(`${base}/acquisition/policy`, { credentials: "include", cache: "no-store", signal });
    if (!response.ok) return null;
    const policy = await response.json();
    // Only a reviewed notice can authorize this UI's consent. Unknown revisions
    // fail closed rather than silently changing purpose or retention.
    if (policy?.enabled !== true || policy.eligibility !== "explicit-opt-in" ||
        policy.revision !== measurementRevision || policy.noticeId !== measurementNotice ||
        policy.cookieSeconds !== 604800) return null;
    return policy;
  } catch { return null; }
}

export function acquisitionChoice(policy: AcquisitionPolicy): "allowed" | "rejected" | "unset" {
  try {
    if (sessionStorage.getItem(rejectionKey) === policy.revision) return "rejected";
    if (sessionStorage.getItem(consentKey) === policy.revision) return "allowed";
  } catch { /* optional storage */ }
  return "unset";
}

export function chooseAcquisition(policy: AcquisitionPolicy, allowed: boolean): boolean {
  resetAcquisitionConsent();
  try {
    sessionStorage.setItem(rejectionKey, policy.revision);
    if (allowed && !acquisitionPrivacyBlocked()) {
      sessionStorage.setItem(consentKey, policy.revision);
      sessionStorage.removeItem(rejectionKey);
      return true;
    }
    return !allowed;
  } catch { resetAcquisitionConsent(); return false; }
}

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

export async function captureAcquisition(base: string, approved?: AcquisitionPolicy): Promise<void> {
  if (pendingTouch) return pendingTouch;
  const request = async () => {
    try {
      if (acquisitionPrivacyBlocked()) return;
      const signal = AbortSignal.timeout(1000);
      const policy = approved ?? await acquisitionPolicy(base, signal);
      if (!policy || acquisitionPrivacyBlocked() || acquisitionChoice(policy) !== "allowed") return;
      const touch = landingTouch(window.location.href, document.referrer);
      if (!touch) return;
      await fetch(`${base}/acquisition/touch`, { method: "POST", credentials: "include", signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ touch, revision: policy.revision, eligible: true }) });
    } catch { /* Storage denial/outages never block navigation or auth. */ }
  };
  pendingTouch = request();
  try { await pendingTouch; } finally { pendingTouch = null; }
}

export async function withdrawAcquisition(base: string, account: boolean | "optional" = false): Promise<boolean> {
  // Stop future calls immediately, then clear the cookie after any bounded POST.
  resetAcquisitionConsent();
  await pendingTouch;
  const forget = async () => {
    try { return (await fetch(`${base}/acquisition/forget`, { method: "POST", credentials: "include", signal: AbortSignal.timeout(1500) })).ok; }
    catch { return false; }
  };
  const removeAccount = async () => {
    if (!account) return true;
    try {
      const response = await fetch(`${base}/analytics/withdraw`, { method: "POST", credentials: "include", signal: AbortSignal.timeout(3000) });
      return response.ok || (account === "optional" && response.status === 401);
    } catch { return false; }
  };
  const [forgotten, removed] = await Promise.all([forget(), removeAccount()]);
  return forgotten && removed;
}

export function resetAcquisitionConsent(): void {
  try { sessionStorage.removeItem(consentKey); } catch { /* optional storage */ }
}
