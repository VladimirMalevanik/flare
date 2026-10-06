import { safePage, safeTelemetryPage, type SafePage, type TelemetryConfig } from "./config";
import { CONSENT_KEY, encodeStoredConsent, parseStoredConsent, type ConsentChoice, type ConsentStorage, type StoredConsent } from "./consent";
import { COOKIE_POSTFIX, cookieOptions } from "./cookies";

export interface TelemetryItem { [key: string]: unknown; baseType?: string; baseData?: Record<string, unknown> }
export interface AnalyticsSdk {
  loadAppInsights(): unknown;
  addTelemetryInitializer(callback: (item: TelemetryItem) => boolean | void): unknown;
  trackPageView(page: { name: string; uri: string; refUri: string; properties: Record<string, never> }): unknown;
  getSender(): { pause(): void; _buffer?: { clear(): void } };
  unload(isAsync?: boolean): unknown;
}
export interface AnalyticsSnapshot {
  choice: "unset" | ConsentChoice;
  configured: boolean;
  privacyBlocked: boolean;
  storageError: boolean;
}
export interface AnalyticsDependencies {
  config: TelemetryConfig | null;
  storage: ConsentStorage;
  loadSdk: () => Promise<{ create(config: Record<string, unknown>): AnalyticsSdk }>;
  deleteCookies: () => void;
  privacyBlocked: () => boolean;
  cookieDocument?: { cookie: string };
  now?: () => number;
  schedule?: typeof setTimeout;
  cancelSchedule?: typeof clearTimeout;
}

export function sdkConfiguration(config: TelemetryConfig, isAllowed: () => boolean, cookieDocument: { cookie: string }, now: () => number, consentExpiresAt?: () => number) {
  return {
    connectionString: config.connectionString, samplingPercentage: 100, disableTelemetry: false,
    enableAutoRouteTracking: false, autoTrackPageVisitTime: false,
    disableAjaxTracking: true, disableFetchTracking: true, disableExceptionTracking: true,
    enableUnhandledPromiseRejectionTracking: false, disableDataLossAnalysis: true,
    isStorageUseDisabled: true, enableSessionStorageBuffer: false,
    loggingLevelTelemetry: 0, loggingLevelConsole: 0,
    disableCookiesUsage: false, cookieCfg: cookieOptions(isAllowed, cookieDocument, now, consentExpiresAt),
    userCookiePostfix: COOKIE_POSTFIX, sessionCookiePostfix: COOKIE_POSTFIX,
    idLength: 22, sessionExpirationMs: 24 * 60 * 60 * 1000, sessionRenewalMs: 30 * 60 * 1000,
    featureOptIn: { SdkStats: { mode: 2 } },
    extensionConfig: { AppInsightsCfgSyncPlugin: { cfgUrl: "", syncMode: 0, blkCdnCfg: true } },
  };
}

/** Runs at SDK priority199, after Properties110 and before Sender1001.
 * The SDK fails open if a callback throws: always catch and return false here.
 */
export function sanitizePageView(item: TelemetryItem, allowed: () => boolean, instrumentationKey: string, now: () => number): boolean {
  try {
    if (!allowed() || item.baseType !== "PageviewData" || !item.baseData) return false;
    const page = safeTelemetryPage(item.baseData.uri);
    if (!page) return false;
    const ext = item.ext as { user?: { id?: unknown }; app?: { sesId?: unknown } } | undefined;
    const anonymous = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9+/_-]{22}$/.test(value) ? value : null;
    const user = anonymous(ext?.user?.id), session = anonymous(ext?.app?.sesId);
    const tags: Record<string, string> = { "ai.cloud.role": "flare-web", "ai.operation.name": page.name };
    if (user) tags["ai.user.id"] = user;
    if (session) tags["ai.session.id"] = session;
    // Reconstruct the envelope. No caller properties, referrer, title, query,
    // trace/baggage, authenticated identity, source content or custom dimensions.
    for (const key of Object.keys(item)) delete item[key];
    Object.assign(item, {
      name: "Microsoft.ApplicationInsights.Pageview", time: new Date(now()).toISOString(),
      iKey: instrumentationKey, ver: "4.0", baseType: "PageviewData",
      baseData: { name: page.name, uri: page.uri, refUri: "", duration: "00:00:00.000", properties: {} },
      tags, ext: {}, data: {},
    });
    return true;
  } catch { return false; }
}

export function createSiteAnalyticsController(deps: AnalyticsDependencies) {
  const now = deps.now ?? (() => Date.now());
  const schedule = deps.schedule ?? setTimeout;
  const cancelSchedule = deps.cancelSchedule ?? clearTimeout;
  let snapshot: AnalyticsSnapshot = { choice: "unset", configured: !!deps.config, privacyBlocked: false, storageError: false };
  let stored: StoredConsent | null = null;
  let active = false;
  let forcedOff = false;
  let generation = 0;
  let sdk: AnalyticsSdk | null = null;
  let loading: Promise<void> | null = null;
  let currentPage: SafePage | null = null;
  let lastPage: string | null = null;
  let expiryTimer: ReturnType<typeof setTimeout> | undefined;
  const listeners = new Set<() => void>();
  const allowed = () => active && !!deps.config && snapshot.choice === "allowed"
    && !snapshot.privacyBlocked && !snapshot.storageError && !forcedOff && !!stored && stored.expiresAt > now();
  const publish = (next: AnalyticsSnapshot) => {
    if (Object.keys(next).every(key => next[key as keyof AnalyticsSnapshot] === snapshot[key as keyof AnalyticsSnapshot])) return;
    snapshot = next;
    listeners.forEach(listener => listener());
  };
  const deleteCookies = () => { try { deps.deleteCookies(); } catch { /* Never affect auth or navigation. */ } };
  function stopSdk(removeCookies: boolean) {
    generation += 1;
    loading = null;
    const previous = sdk;
    sdk = null;
    lastPage = null;
    if (previous) {
      // Close the wrapper gate before reaching this function. Pinned SDK
      // unload always flushes unless Sender is paused; false is sync teardown.
      // Do not update config here: its watcher can resume Sender before it
      // applies disableTelemetry. Keep pause/clear/unload synchronous instead.
      try { const sender = previous.getSender(); sender.pause(); sender._buffer?.clear(); } catch { /* Continue teardown. */ }
      try { previous.unload(false); } catch { /* No retry/flush or diagnostics. */ }
    }
    if (removeCookies) deleteCookies();
  }
  function scheduleExpiry() {
    if (expiryTimer !== undefined) cancelSchedule(expiryTimer);
    expiryTimer = undefined;
    if (!active || !stored) return;
    expiryTimer = schedule(() => { expiryTimer = undefined; reconcile(); },
      Math.min(Math.max(0, stored.expiresAt - now()), 2_147_483_647));
  }
  function sendCurrentPage() {
    if (!sdk || !allowed() || !currentPage || lastPage === currentPage.uri) return;
    try {
      sdk.trackPageView({ ...currentPage, refUri: "", properties: {} });
      lastPage = currentPage.uri;
    } catch { /* Optional analytics never affects a product action. */ }
  }
  function ensureSdk() {
    if (!allowed() || !currentPage || !deps.config) return;
    if (sdk) return sendCurrentPage();
    if (loading) return;
    const attempt = generation;
    const config = deps.config;
    const attemptAllowed = () => attempt === generation && allowed();
    const pending = Promise.resolve().then(() => deps.loadSdk()).then(factory => {
      if (!attemptAllowed()) return;
      const options = sdkConfiguration(config, attemptAllowed, deps.cookieDocument ?? { cookie: "" }, now, () => stored?.expiresAt ?? now());
      const next = factory.create(options);
      // Tests/factories can be reentrant; don't initialize after withdrawal.
      if (!attemptAllowed()) return;
      const key = config.connectionString.match(/InstrumentationKey=([^;]+)/)?.[1] ?? "";
      next.addTelemetryInitializer(item => sanitizePageView(item, attemptAllowed, key, now));
      if (!attemptAllowed()) return;
      sdk = next;
      next.loadAppInsights();
      if (!attemptAllowed()) return stopSdk(true);
      sendCurrentPage();
    }).catch(() => {
      if (attempt === generation) stopSdk(false);
    }).finally(() => { if (loading === pending) loading = null; });
    loading = pending;
  }
  function reconcile() {
    if (!active) return;
    let storageError = false;
    try { stored = parseStoredConsent(deps.storage.getItem(CONSENT_KEY), now()); }
    catch { stored = null; storageError = true; forcedOff = true; }
    let privacyBlocked = true;
    try { privacyBlocked = deps.privacyBlocked(); } catch { /* Fail closed. */ }
    publish({ ...snapshot, choice: forcedOff ? "rejected" : stored?.choice ?? "unset", privacyBlocked, storageError });
    if (!allowed()) stopSdk(true);
    scheduleExpiry();
    ensureSdk();
  }
  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    initialize() { active = true; reconcile(); },
    reconcile,
    trackPage(pathname: string) {
      currentPage = safePage(pathname);
      if (!currentPage) { lastPage = null; return; }
      if (active) reconcile();
    },
    setConsent(choice: ConsentChoice) {
      // Rejection closes the send/initializer/cookie gates synchronously even
      // when browser storage cannot persist the preference.
      if (choice === "rejected") {
        forcedOff = true;
        publish({ ...snapshot, choice: "rejected" });
        stopSdk(true);
        lastPage = null;
      }
      try {
        const value = encodeStoredConsent(choice, now());
        deps.storage.setItem(CONSENT_KEY, value);
        if (deps.storage.getItem(CONSENT_KEY) !== value) throw new Error("Choice was not saved");
        forcedOff = false;
      } catch {
        forcedOff = true;
        stored = null;
        publish({ ...snapshot, choice: "rejected", storageError: true });
        stopSdk(true);
        return;
      }
      active = true;
      reconcile();
    },
    dispose() {
      active = false;
      if (expiryTimer !== undefined) cancelSchedule(expiryTimer);
      expiryTimer = undefined;
      stopSdk(false);
      lastPage = null;
    },
  };
}
