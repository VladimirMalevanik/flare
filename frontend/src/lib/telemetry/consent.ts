export const CONSENT_KEY = "flare-site-analytics-consent-v1";
export const CONSENT_TTL_MS = 30 * 24 * 60 * 60 * 1000;
export type ConsentChoice = "allowed" | "rejected";
export interface StoredConsent { version: 1; choice: ConsentChoice; expiresAt: number }
export interface ConsentStorage { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void }

export function parseStoredConsent(raw: string | null, now: number): StoredConsent | null {
  if (!raw || raw.length > 256) return null;
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || Object.keys(value).sort().join(",") !== "choice,expiresAt,version"
        || value.version !== 1 || !["allowed", "rejected"].includes(value.choice)
        || typeof value.expiresAt !== "number" || !Number.isSafeInteger(value.expiresAt)
        || value.expiresAt <= now || value.expiresAt > now + CONSENT_TTL_MS) return null;
    return value as StoredConsent;
  } catch { return null; }
}

export function encodeStoredConsent(choice: ConsentChoice, now: number): string {
  if (!["allowed", "rejected"].includes(choice) || !Number.isSafeInteger(now)) throw new Error("Invalid analytics choice");
  return JSON.stringify({ version: 1, choice, expiresAt: now + CONSENT_TTL_MS });
}

export function privacySignalBlocked(navigatorLike: { globalPrivacyControl?: boolean; doNotTrack?: string | null; msDoNotTrack?: string | null }, windowLike?: { doNotTrack?: string | null }): boolean {
  const blocked = (value: string | null | undefined) => value?.trim().toLowerCase() === "1" || value?.trim().toLowerCase() === "yes";
  return navigatorLike.globalPrivacyControl === true || blocked(navigatorLike.doNotTrack)
    || blocked(navigatorLike.msDoNotTrack) || blocked(windowLike?.doNotTrack);
}
