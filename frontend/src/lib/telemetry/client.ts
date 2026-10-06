import { parseTelemetryConfig } from "./config";
import { CONSENT_KEY, privacySignalBlocked } from "./consent";
import { createSiteAnalyticsController, type AnalyticsSdk, type AnalyticsSnapshot } from "./controller";
import { deleteCookieAssignments } from "./cookies";

const serverSnapshot: AnalyticsSnapshot = Object.freeze({ choice: "unset", configured: false, privacyBlocked: false, storageError: false });
let controller: ReturnType<typeof createSiteAnalyticsController> | null = null;
function client() {
  if (controller) return controller;
  let config = null;
  try {
    config = parseTelemetryConfig(process.env.NEXT_PUBLIC_APPLICATION_INSIGHTS_CONNECTION_STRING,
      process.env.NEXT_PUBLIC_APPLICATION_INSIGHTS_ENABLED);
  } catch { /* Deployment validates config; unexpected browser config stays off. */ }
  controller = createSiteAnalyticsController({
    config,
    storage: {
      getItem: key => window.localStorage.getItem(key),
      setItem: (key, value) => window.localStorage.setItem(key, value),
      removeItem: key => window.localStorage.removeItem(key),
    },
    privacyBlocked: () => privacySignalBlocked(navigator as Navigator & { globalPrivacyControl?: boolean; msDoNotTrack?: string }, window as Window & { doNotTrack?: string }),
    deleteCookies: () => { for (const assignment of deleteCookieAssignments()) document.cookie = assignment; },
    cookieDocument: {
      get cookie() { return typeof document === "undefined" ? "" : document.cookie; },
      set cookie(value: string) { if (typeof document !== "undefined") document.cookie = value; },
    },
    loadSdk: async () => {
      const applicationInsights = await import("@microsoft/applicationinsights-web");
      return { create: options => new applicationInsights.ApplicationInsights({ config: options }) as unknown as AnalyticsSdk };
    },
  });
  return controller;
}

export const siteAnalytics = {
  getSnapshot: () => typeof window === "undefined" ? serverSnapshot : client().getSnapshot(),
  getServerSnapshot: () => serverSnapshot,
  subscribe: (listener: () => void) => typeof window === "undefined" ? () => {} : client().subscribe(listener),
  initialize: () => { if (typeof window !== "undefined") client().initialize(); },
  trackPage: (pathname: string) => { if (typeof window !== "undefined") client().trackPage(pathname); },
  setConsent: (choice: "allowed" | "rejected") => { if (typeof window !== "undefined") client().setConsent(choice); },
  reconcile: () => { if (typeof window !== "undefined") client().reconcile(); },
  dispose: () => { if (typeof window !== "undefined") client().dispose(); },
};
export { CONSENT_KEY };
