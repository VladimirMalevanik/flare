export const COOKIE_POSTFIX = "_flare_site_analytics";
export const ANALYTICS_COOKIE_NAMES = [`ai_user${COOKIE_POSTFIX}`, `ai_session${COOKIE_POSTFIX}`] as const;
export const COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;
const owned = (name: string) => (ANALYTICS_COOKIE_NAMES as readonly string[]).includes(name);

export function readOwnCookie(cookieHeader: string, name: string): string {
  if (!owned(name)) return "";
  const prefix = name + "=";
  return cookieHeader.split(";").map(part => part.trim()).find(part => part.startsWith(prefix))?.slice(prefix.length) ?? "";
}

export function boundedCookie(name: string, value: string, now: number): string | null {
  if (!owned(name) || value.length > 1024 || !Number.isFinite(now)) return null;
  const [payload, ...attributes] = value.split(";");
  if (!/^[A-Za-z0-9._~|%+=/:\-]{1,512}$/.test(payload)) return null;
  let seconds = COOKIE_MAX_AGE_SECONDS;
  for (const attribute of attributes) {
    const separator = attribute.indexOf("=");
    const key = attribute.slice(0, separator).trim().toLowerCase();
    const item = attribute.slice(separator + 1).trim();
    if (key === "max-age") {
      if (!/^-?[0-9]+$/.test(item)) return null;
      seconds = Math.min(seconds, Number(item));
    } else if (key === "expires") {
      const deadline = Date.parse(item);
      if (!Number.isFinite(deadline)) return null;
      seconds = Math.min(seconds, Math.floor((deadline - now) / 1000));
    }
  }
  seconds = Math.max(0, Math.min(COOKIE_MAX_AGE_SECONDS, Math.floor(seconds)));
  return `${name}=${payload}; Path=/; Secure; SameSite=Lax; Max-Age=${seconds}; Expires=${new Date(now + seconds * 1000).toUTCString()}`;
}

export function deleteCookieAssignments(): string[] {
  return ANALYTICS_COOKIE_NAMES.map(name => `${name}=; Path=/; Secure; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT`);
}

export function cookieOptions(isAllowed: () => boolean, documentLike: { cookie: string }, now = () => Date.now()) {
  return {
    enabled: true, path: "/", disableCookieDefer: true,
    getCookie(name: string) { return isAllowed() ? readOwnCookie(documentLike.cookie, name) : ""; },
    setCookie(name: string, value: string) {
      if (!isAllowed()) return;
      const assignment = boundedCookie(name, value, now());
      if (assignment) documentLike.cookie = assignment;
    },
    delCookie(name: string) {
      if (!owned(name)) return;
      documentLike.cookie = deleteCookieAssignments()[ANALYTICS_COOKIE_NAMES.indexOf(name as typeof ANALYTICS_COOKIE_NAMES[number])];
    },
  };
}
