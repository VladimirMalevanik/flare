const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const plain = value => JSON.parse(JSON.stringify(value));
const frontendRoot = path.resolve(__dirname, "..");

// Exercise the same public TypeScript modules as the app, with explicit fake SDK
// and browser dependencies. No provider import, DOM, cookies or network is real.
function loadTs(relative, mocks = {}, globals = {}) {
  const cache = new Map();
  function visit(filename) {
    filename = path.resolve(filename);
    if (cache.has(filename)) return cache.get(filename).exports;
    const moduleFixture = { exports: {} };
    cache.set(filename, moduleFixture);
    const code = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    vm.runInNewContext(code, {
      module: moduleFixture, exports: moduleFixture.exports, __dirname: path.dirname(filename),
      process: { env: {} }, URL, setTimeout, clearTimeout, AbortController,
      require(name) {
        if (Object.hasOwn(mocks, name)) return mocks[name];
        const requested = name.startsWith("@/") ? path.join(frontendRoot, "src", name.slice(2))
          : name.startsWith(".") ? path.resolve(path.dirname(filename), name) : null;
        if (!requested) throw Error(`Unexpected runtime import ${name}`);
        const resolved = [requested, `${requested}.ts`, `${requested}.tsx`]
          .find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
        if (!resolved) throw Error(`Missing runtime module ${name}`);
        return visit(resolved);
      },
      ...globals,
    }, { filename });
    return moduleFixture.exports;
  }
  return visit(path.join(__dirname, relative));
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
async function flush() { for (let i = 0; i < 20; i++) await Promise.resolve(); }

async function csp(environment = {}) {
  const config = loadTs("../next.config.ts", {}, {
    process: { env: { NODE_ENV: "production", ...environment } },
  }).default;
  const rules = await config.headers();
  const value = rules.flatMap(rule => rule.headers).find(header => header.key === "Content-Security-Policy").value;
  return Object.fromEntries(value.split(";").map(directive => {
    const [key, ...values] = directive.trim().split(/\s+/);
    return [key, values];
  }));
}

test("production CSP preserves exact Paddle Sandbox origins without broad network or script permissions", async () => {
  const policy = await csp();
  assert.ok(policy["connect-src"].includes("'self'"));
  assert.ok(policy["connect-src"].includes("https://sandbox-api.paddle.com"));
  assert.deepEqual(plain(policy["frame-src"]), ["'self'", "https://sandbox-buy.paddle.com", "https://sandbox-cdn.paddle.com"]);
  assert.ok(policy["script-src"].includes("https://cdn.paddle.com"));
  assert.ok(policy["img-src"].includes("https://sandbox-cdn.paddle.com"));
  assert.ok(policy["style-src"].includes("https://sandbox-cdn.paddle.com"));
  for (const values of Object.values(policy)) {
    assert.equal(values.some(value => value.includes("*") || value === "https:" || value === "http:"), false);
  }
  assert.equal(policy["script-src"].includes("'unsafe-eval'"), false);
  assert.equal(policy["connect-src"].some(value => /api\.paddle\.com$/.test(value) && !/sandbox-api\.paddle/.test(value)), false);
  assert.deepEqual(plain(policy["object-src"]), ["'none'"]);
  assert.deepEqual(plain(policy["frame-ancestors"]), ["'none'"]);
});

const connectionString = "InstrumentationKey=00000000-0000-0000-0000-000000000001;IngestionEndpoint=https://centralus-0.in.applicationinsights.azure.com/";
const enabledEnvironment = {
  NEXT_PUBLIC_APPLICATION_INSIGHTS_ENABLED: "true",
  NEXT_PUBLIC_APPLICATION_INSIGHTS_CONNECTION_STRING: connectionString,
};

test("enabled CSP adds only its exact validated Azure ingestion origin and keeps existing Sandbox permissions", async () => {
  const baseline = await csp();
  const enabled = await csp(enabledEnvironment);
  assert.deepEqual(plain(enabled["connect-src"]), [...plain(baseline["connect-src"]), "https://centralus-0.in.applicationinsights.azure.com"]);
  for (const key of Object.keys(baseline).filter(key => key !== "connect-src")) {
    assert.deepEqual(plain(enabled[key]), plain(baseline[key]), key);
  }
  assert.equal(Object.values(enabled).flat().some(value => value.includes("*") || /dc\.services|js\.monitor|config\.applicationinsights/.test(value)), false);
});

test("disabled analytics leaves the CSP unchanged; enabled malformed endpoints fail without echoing input", async () => {
  const baseline = plain(await csp());
  for (const flag of [undefined, "false", "TRUE", "1", " true", ""]) {
    assert.deepEqual(plain(await csp({ ...enabledEnvironment,
      NEXT_PUBLIC_APPLICATION_INSIGHTS_ENABLED: flag,
      NEXT_PUBLIC_APPLICATION_INSIGHTS_CONNECTION_STRING: "not-a-real-private-placeholder" })), baseline);
  }
  for (const invalid of [undefined, "", "InstrumentationKey=invalid-private-placeholder",
    connectionString + ";InstrumentationKey=00000000-0000-0000-0000-000000000002",
    connectionString.replace("https://centralus-0.in.applicationinsights.azure.com/", "https://attacker.example/private-placeholder"),
    connectionString.replace("https://", "http://"),
    connectionString.replace("azure.com/", "azure.com:443/"),
    connectionString.replace("azure.com/", "azure.com/?token=private-placeholder"),
    connectionString.replace("centralus-0.in", "*.in"),
    connectionString.replace("azure.com/", "azure.com.evil.example/")]) {
    await assert.rejects(csp({ ...enabledEnvironment, NEXT_PUBLIC_APPLICATION_INSIGHTS_CONNECTION_STRING: invalid }), error => {
      assert.doesNotMatch(error.message, /private-placeholder|attacker|evil|InstrumentationKey=/);
      return true;
    });
  }
});

function telemetryModules() {
  return {
    get config() { return loadTs("../src/lib/telemetry/config.ts"); },
    get consent() { return loadTs("../src/lib/telemetry/consent.ts"); },
    get controller() { return loadTs("../src/lib/telemetry/controller.ts"); },
  };
}
function fakeScheduler() {
  let counter = 0;
  const pending = new Map();
  return {
    schedule(fn, ms) { pending.set(++counter, { fn, ms }); return counter; },
    cancelSchedule(id) { pending.delete(id); },
    fireAll() { for (const [id, timer] of [...pending]) { pending.delete(id); timer.fn(); } },
    count: () => pending.size,
  };
}
function fixture(options = {}) {
  const { config, consent, controller } = telemetryModules();
  const timers = fakeScheduler();
  const entries = new Map(Object.entries(options.stored ?? {}));
  const calls = { imports: 0, create: [], rawConfigurations: [], loads: 0, views: [], updates: [], order: [], deletedCookies: 0,
    storage: [], initializers: [], cookieWrites: [], cookieReads: 0 };
  let now = options.now ?? Date.parse("2026-10-06T00:00:00Z");
  let privacyBlocked = options.privacyBlocked ?? false;
  const sender = { pause() { calls.order.push("pause"); options.onSdkOperation?.("pause", calls); },
    _buffer: { clear() { calls.order.push("clear"); options.onSdkOperation?.("clear", calls); } } };
  const sdk = {
    loadAppInsights() { calls.loads++; calls.order.push("load"); },
    addTelemetryInitializer(fn) { calls.initializers.push(fn); return { remove() {} }; },
    trackPageView(view) { calls.views.push(plain(view)); },
    updateCfg(value, merge) { calls.updates.push({ value: plain(value), merge }); calls.order.push("update"); },
    getSender() { return sender; },
    unload(async) { calls.order.push("unload"); calls.unloadAsync = async; options.onSdkOperation?.("unload", calls); },
  };
  const adapter = { create(value) { calls.rawConfigurations.push(value); calls.create.push(plain(value)); return sdk; } };
  const storage = {
    getItem(key) { calls.storage.push(["get", key]); if (options.deniedRead) throw Error("private browser storage failure"); return entries.get(key) ?? null; },
    setItem(key, value) { calls.storage.push(["set", key, value]); if (options.deniedWrite) throw Error("private browser storage failure"); entries.set(key, value); },
    removeItem(key) { calls.storage.push(["remove", key]); if (options.deniedRemove) throw Error("private browser storage failure"); entries.delete(key); },
  };
  const client = controller.createSiteAnalyticsController({
    config: options.config === null ? null : config.parseTelemetryConfig(connectionString, "true"),
    storage, loadSdk() { calls.imports++; return options.loadSdk ? options.loadSdk(adapter) : Promise.resolve(adapter); },
    deleteCookies() { calls.deletedCookies++; calls.order.push("delete-cookies"); },
    cookieDocument: { get cookie() { calls.cookieReads++; return "flare_session=private-auth-token; ai_user_flare_site_analytics=stable-anonymous-value"; },
      set cookie(value) { calls.cookieWrites.push(value); } },
    privacyBlocked: () => privacyBlocked, now: () => now, ...timers,
  });
  return { client, sdk, calls, entries, consent, config, timers, adapter,
    setNow: value => { now = value; }, blockPrivacy: value => { privacyBlocked = value; },
    snapshot: () => plain(client.getSnapshot()),
  };
}

function assertNoSdk(f) {
  assert.equal(f.calls.imports, 0);
  assert.equal(f.calls.create.length, 0);
  assert.equal(f.calls.loads, 0);
  assert.equal(f.calls.views.length, 0);
}
function pageEnvelope(page, extras = {}) {
  return { name: "Microsoft.ApplicationInsights.Pageview", baseType: "PageviewData",
    baseData: { name: page.name, uri: page.uri }, ...extras };
}

test("telemetry config requires an explicit exact flag and a validated public Azure connection string", () => {
  const { parseTelemetryConfig } = telemetryModules().config;
  assert.ok(parseTelemetryConfig(connectionString, "true"));
  for (const flag of [undefined, "false", "TRUE", "1", " true", ""]) {
    assert.equal(parseTelemetryConfig("private-placeholder", flag), null);
  }
  for (const value of [undefined, "", "private-placeholder", connectionString + ";InstrumentationKey=duplicate",
    connectionString.replace("https://", "http://"),
    connectionString.replace("azure.com/", "azure.com/?token=private-placeholder"),
    connectionString.replace("azure.com/", "azure.com.evil.example/")]) {
    assert.throws(() => parseTelemetryConfig(value, "true"), error => {
      assert.doesNotMatch(error.message, /private-placeholder|InstrumentationKey=|evil/);
      return true;
    });
  }
});

test("only fixed routes receive fixed names and canonical URLs; query, hash and private paths cannot escape", () => {
  const { safePage } = telemetryModules().config;
  for (const pathname of ["/", "/login", "/register", "/privacy", "/terms", "/settings", "/sources", "/vault", "/insights"]) {
    const page = safePage(pathname);
    assert.ok(page, pathname);
    assert.equal(page.uri, `https://flare4u.tech${pathname}`);
    assert.equal(typeof page.name, "string");
    assert.ok(page.name.length > 0);
    assert.deepEqual(plain(safePage(`${pathname}?token=private-token&email=private-email@example.test#private-title`)), plain(page));
  }
  for (const pathname of ["/vault/private-document-name", "/insights/private-user-id", "/api/auth/token",
    "https://attacker.example/settings?token=private", "https://flare4u.tech/settings", "//attacker.example/settings",
    "/sources/private-repository", "/unknown-private-title", "/settings/../vault", "/%73ettings"]) {
    assert.equal(safePage(pathname), null, pathname);
  }
});

test("stored consent is bounded, versioned and fails closed for malformed, future or expired choices", () => {
  const { CONSENT_KEY, CONSENT_TTL_MS, encodeStoredConsent, parseStoredConsent } = telemetryModules().consent;
  const now = Date.parse("2026-10-06T00:00:00Z");
  assert.equal(typeof CONSENT_KEY, "string");
  assert.equal(CONSENT_TTL_MS, 30 * 24 * 60 * 60 * 1000);
  for (const choice of ["allowed", "rejected"]) {
    const raw = encodeStoredConsent(choice, now);
    assert.equal(parseStoredConsent(raw, now).choice, choice);
    assert.equal(parseStoredConsent(raw, now + CONSENT_TTL_MS - 1).choice, choice);
    assert.equal(parseStoredConsent(raw, now + CONSENT_TTL_MS), null);
    assert.equal(parseStoredConsent(raw, now - 1), null);
  }
  for (const raw of [null, "", "{", "null", "true", "[]", "allowed",
    '{"choice":"allowed"}', '{"version":999,"choice":"allowed","expiresAt":9999999999999}',
    '{"choice":"allowed","token":"private-placeholder"}']) assert.equal(parseStoredConsent(raw, now), null);
});

test("Global Privacy Control and Do Not Track signals override stored or newly chosen analytics consent", () => {
  const { privacySignalBlocked } = telemetryModules().consent;
  assert.equal(privacySignalBlocked({}, {}), false);
  for (const [navigatorLike, windowLike] of [[{ globalPrivacyControl: true }, {}], [{ doNotTrack: "1" }, {}],
    [{ doNotTrack: "yes" }, {}], [{ msDoNotTrack: "1" }, {}], [{}, { doNotTrack: "1" }]]) {
    assert.equal(privacySignalBlocked(navigatorLike, windowLike), true);
  }
  assert.equal(privacySignalBlocked({ doNotTrack: "0", globalPrivacyControl: false }, {}), false);
});

test("unknown consent does not import or initialize the SDK, send telemetry or create analytics cookies", async () => {
  const f = fixture();
  f.client.initialize(); f.client.trackPage("/"); f.client.trackPage("/settings?token=private-token");
  await flush();
  assertNoSdk(f);
  // Delete-only cleanup may remove a stale analytics cookie; no SDK or setter
  // can create one without consent (the cookie callbacks are exercised below).
  assert.equal(f.calls.storage.some(([kind]) => kind === "set"), false);
  assert.equal(f.snapshot().choice, "unset");
  f.client.dispose();
});

test("explicit consent initializes once and repeated renders or query-only changes produce one manual page view", async () => {
  const f = fixture();
  f.client.initialize(); f.client.trackPage("/");
  f.client.setConsent("allowed"); await flush();
  f.client.initialize(); f.client.trackPage("/"); f.client.trackPage("/?token=private-token#private-title");
  f.client.reconcile(); await flush();
  assert.equal(f.calls.imports, 1); assert.equal(f.calls.create.length, 1); assert.equal(f.calls.loads, 1);
  assert.equal(f.calls.views.length, 1);
  assert.equal(f.calls.views[0].name, f.config.safePage("/").name);
  assert.equal(f.calls.views[0].uri, "https://flare4u.tech/");
  assert.doesNotMatch(JSON.stringify(f.calls.views), /private-token|private-title|\?|#/);
  f.client.trackPage("/settings"); f.client.trackPage("/settings"); f.client.trackPage("/"); await flush();
  assert.deepEqual(f.calls.views.map(value => value.uri), ["https://flare4u.tech/", "https://flare4u.tech/settings", "https://flare4u.tech/"]);
  f.client.trackPage("/vault/private-file"); f.client.trackPage("/api/auth/private-token"); await flush();
  assert.equal(f.calls.views.length, 3);
  f.client.trackPage("/"); await flush();
  assert.equal(f.calls.views.length, 4, "returning from an untracked private route is a new public route visit");
  f.client.dispose();
});

test("SDK initialization disables automatic routes, dependency, exception and performance-context collection", async () => {
  const f = fixture(); f.client.initialize(); f.client.trackPage("/sources"); f.client.setConsent("allowed"); await flush();
  const configuration = f.calls.create[0];
  for (const name of ["disableAjaxTracking", "disableFetchTracking", "disableExceptionTracking"]) assert.equal(configuration[name], true, name);
  for (const name of ["enableAutoRouteTracking", "autoTrackPageVisitTime", "enableUnhandledPromiseRejectionTracking"]) assert.equal(configuration[name], false, name);
  assert.equal(configuration.enableSessionStorageBuffer, false);
  assert.equal(configuration.isStorageUseDisabled, true);
  assert.equal(configuration.disableDataLossAnalysis, true);
  assert.equal(configuration.loggingLevelTelemetry, 0);
  assert.equal(configuration.loggingLevelConsole, 0);
  assert.equal(configuration.featureOptIn.SdkStats.mode, 2, "SDK-owned stats bypass app telemetry filtering and must stay disabled");
  assert.equal(configuration.extensionConfig.AppInsightsCfgSyncPlugin.blkCdnCfg, true);
  assert.equal(configuration.extensionConfig.AppInsightsCfgSyncPlugin.syncMode, 0);
  assert.equal(configuration.extensionConfig.AppInsightsCfgSyncPlugin.cfgUrl, "");
  assert.equal(configuration.disableCookiesUsage, false, "analytics cookies are allowed only after the explicit choice");
  assert.doesNotMatch(JSON.stringify(configuration), /private-token|password|founder@example/);
  f.client.dispose();
});

test("the final telemetry initializer drops non-page events and removes private enrichment from allowed page views", async () => {
  const f = fixture(); f.client.initialize(); f.client.trackPage("/settings"); f.client.setConsent("allowed"); await flush();
  assert.ok(f.calls.initializers.length > 0);
  const initialize = f.calls.initializers.at(-1);
  const page = f.config.safePage("/settings");
  const enriched = pageEnvelope(page, {
    baseData: { name: "private-document-title", uri: "https://flare4u.tech/settings?token=private-token#private-title",
      refUri: "https://mail.example/private-email@example.test", id: "private-user-id",
      properties: { email: "private-email@example.test", password: "private-password", note: "private-user-content" },
      measurements: { private_metric: 9 } },
    tags: { "ai.user.id": "private-user-id", "ai.user.authUserId": "private-auth-id", "ai.session.id": "private-session-id",
      "ai.operation.name": "private-title", "ai.operation.id": "private-operation-id", "ai.device.id": "private-device-id" },
    ext: { user: { id: "private-auth-id" }, web: { domain: "private-workspace-name" } },
    data: { token: "private-token" }, properties: { authorization: "private-auth-token" },
  });
  // A known canonical path remains trackable even when SDK context contains a
  // document title or referrer; every outgoing value must come from our allowlist.
  assert.notEqual(initialize(enriched), false);
  assert.equal(enriched.baseData.name, page.name);
  assert.equal(enriched.baseData.uri, page.uri);
  assert.equal(enriched.baseData.refUri, "");
  assert.deepEqual(plain(enriched.baseData.properties), {});
  assert.doesNotMatch(JSON.stringify(enriched), /private-|email|password|token|referrer|\?|#/);
  for (const baseType of ["EventData", "ExceptionData", "RemoteDependencyData", "MessageData", "MetricData", "PageviewPerformanceData"]) {
    assert.equal(initialize({ ...pageEnvelope(page), baseType }), false, baseType);
  }
  assert.equal(initialize(pageEnvelope({ name: "private-name", uri: "https://attacker.example/private-token" })), false);
  assert.equal(initialize(pageEnvelope({ name: "private-title", uri: "https://flare4u.tech/vault/private-file" })), false);
  f.client.dispose();
});

test("rejecting consent and disabled configuration never import the SDK even after repeated route changes", async () => {
  for (const disabled of [false, true]) {
    const f = fixture({ config: disabled ? null : undefined });
    f.client.initialize(); f.client.setConsent("rejected"); f.client.trackPage("/"); f.client.trackPage("/settings");
    f.client.reconcile(); await flush(); assertNoSdk(f);
    assert.equal(f.snapshot().configured, !disabled);
    f.client.dispose();
  }
});

test("revocation gates outgoing telemetry synchronously, clears queued data without flushing and unloads before deletion", async () => {
  let guarded = 0;
  const f = fixture({ onSdkOperation(name, calls) {
    if (name === "pause" || name === "unload") {
      assert.equal(calls.initializers.at(-1)(pageEnvelope({ name: "Home", uri: "https://flare4u.tech/" })), false);
      guarded++;
    }
  } });
  f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  const initialViews = f.calls.views.length;
  f.calls.order.length = 0;
  f.client.setConsent("rejected");
  assert.equal(f.snapshot().choice, "rejected");
  f.client.trackPage("/settings"); await flush();
  assert.equal(f.calls.views.length, initialViews);
  assert.ok(guarded >= 2);
  assert.deepEqual(f.calls.order.slice(0, 4), ["pause", "clear", "unload", "delete-cookies"]);
  assert.equal(f.calls.updates.length, 0, "SDK dynamic config updates can resume Sender and must not occur during revocation");
  assert.equal(f.calls.unloadAsync, false);
  // A preference expiry timer is permitted; it cannot load or send analytics.
  f.timers.fireAll(); await flush();
  assert.equal(f.calls.views.length, initialViews);
  f.client.dispose();
});

test("withdrawal during a deferred SDK import prevents late initialization, page views and stale cookie writes", async () => {
  const loading = deferred();
  const f = fixture({ loadSdk: () => loading.promise });
  f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  assert.equal(f.calls.imports, 1);
  f.client.setConsent("rejected"); loading.resolve(f.adapter); await flush();
  assert.equal(f.calls.create.length, 0); assert.equal(f.calls.loads, 0); assert.equal(f.calls.views.length, 0);
  assert.equal(f.snapshot().choice, "rejected");
  f.client.dispose();
});

test("route changes during deferred initialization send only the latest allowed route, and dispose cancels stale work", async () => {
  const loading = deferred();
  const f = fixture({ loadSdk: () => loading.promise });
  f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  f.client.trackPage("/settings?token=private-token"); loading.resolve(f.adapter); await flush();
  assert.deepEqual(f.calls.views.map(value => value.uri), ["https://flare4u.tech/settings"]);
  f.client.dispose();

  const otherLoading = deferred();
  const other = fixture({ loadSdk: () => otherLoading.promise });
  other.client.initialize(); other.client.trackPage("/"); other.client.setConsent("allowed"); await flush();
  other.client.dispose(); otherLoading.resolve(other.adapter); await flush();
  assert.equal(other.calls.create.length, 0); assert.equal(other.calls.views.length, 0);
  assert.equal(other.timers.count(), 0);
});

test("SDK import failures remain contained and never leak provider errors or interrupt application navigation", async () => {
  const f = fixture({ loadSdk: async () => { throw Error("private-provider-error-with-token"); } });
  f.client.initialize(); f.client.trackPage("/");
  assert.doesNotThrow(() => f.client.setConsent("allowed")); await flush();
  assert.equal(f.calls.create.length, 0); assert.equal(f.calls.views.length, 0);
  assert.doesNotThrow(() => f.client.trackPage("/settings"));
  assert.doesNotMatch(JSON.stringify(f.snapshot()), /private-provider|token/);
  f.client.dispose();
});

test("denied browser storage cannot silently enable tracking or throw during opt-in, revocation or navigation", async () => {
  for (const options of [{ deniedRead: true }, { deniedWrite: true }, { deniedRead: true, deniedWrite: true, deniedRemove: true }]) {
    const f = fixture(options);
    assert.doesNotThrow(() => f.client.initialize()); f.client.trackPage("/"); await flush(); assertNoSdk(f);
    assert.doesNotThrow(() => f.client.setConsent("allowed")); await flush(); assertNoSdk(f);
    assert.equal(f.snapshot().storageError, true);
    assert.doesNotThrow(() => f.client.setConsent("rejected")); f.client.trackPage("/settings"); await flush(); assertNoSdk(f);
    f.client.dispose();
  }
});

test("a valid persisted opt-in can resume, while rejected, malformed or expired consent cannot initialize the SDK", async () => {
  const { consent } = telemetryModules();
  const now = Date.parse("2026-10-06T00:00:00Z");
  const f = fixture({ now, stored: { [consent.CONSENT_KEY]: consent.encodeStoredConsent("allowed", now - 1000) } });
  f.client.initialize(); f.client.trackPage("/"); await flush();
  assert.equal(f.calls.imports, 1); assert.equal(f.calls.views.length, 1); f.client.dispose();
  for (const raw of [consent.encodeStoredConsent("rejected", now - 1000), "malformed-private-input",
    consent.encodeStoredConsent("allowed", now - consent.CONSENT_TTL_MS)]) {
    const other = fixture({ now, stored: { [consent.CONSENT_KEY]: raw } });
    other.client.initialize(); other.client.trackPage("/"); await flush(); assertNoSdk(other); other.client.dispose();
  }
});

test("consent expiry and privacy signals revoke the SDK and cannot be bypassed by later routes or stored opt-in", async () => {
  const f = fixture(); f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  f.setNow(Date.parse("2026-10-06T00:00:00Z") + f.consent.CONSENT_TTL_MS);
  f.timers.fireAll(); await flush();
  const afterExpiry = f.calls.views.length;
  f.client.trackPage("/settings"); await flush(); assert.equal(f.calls.views.length, afterExpiry);
  assert.notEqual(f.snapshot().choice, "allowed"); f.client.dispose();

  const blocked = fixture({ privacyBlocked: true });
  blocked.client.initialize(); blocked.client.setConsent("allowed"); blocked.client.trackPage("/"); await flush(); assertNoSdk(blocked);
  assert.equal(blocked.snapshot().privacyBlocked, true); blocked.client.dispose();
  const changed = fixture(); changed.client.initialize(); changed.client.trackPage("/"); changed.client.setConsent("allowed"); await flush();
  changed.blockPrivacy(true); changed.client.reconcile(); const count = changed.calls.views.length;
  changed.client.trackPage("/settings"); await flush(); assert.equal(changed.calls.views.length, count);
  assert.ok(changed.calls.order.includes("pause")); changed.client.dispose();
});

test("cookie callbacks never read or write before opt-in, and cannot expose or delete application cookies", () => {
  const cookies = loadTs("../src/lib/telemetry/cookies.ts");
  let allowed = false;
  let reads = 0;
  const writes = [];
  const jar = new Map([["flare_session", "private-auth-token"], ["flare_locale", "es"], ["flare_acquisition", "private-source"],
    [cookies.ANALYTICS_COOKIE_NAMES[0], "anonymous-user"], [cookies.ANALYTICS_COOKIE_NAMES[1], "anonymous-session"]]);
  const documentLike = {
    get cookie() { reads++; return [...jar].map(([name, value]) => `${name}=${value}`).join("; "); },
    set cookie(value) {
      writes.push(value);
      const [pair] = value.split(";");
      const separator = pair.indexOf("=");
      const name = pair.slice(0, separator);
      if (/Max-Age=0(?:;|$)/.test(value)) jar.delete(name); else jar.set(name, pair.slice(separator + 1));
    },
  };
  const options = cookies.cookieOptions(() => allowed, documentLike, () => Date.parse("2026-10-06T00:00:00Z"));
  assert.equal(options.getCookie(cookies.ANALYTICS_COOKIE_NAMES[0]), "");
  options.setCookie(cookies.ANALYTICS_COOKIE_NAMES[0], "anonymous-user");
  assert.equal(reads, 0); assert.equal(writes.length, 0);
  allowed = true;
  assert.equal(options.getCookie(cookies.ANALYTICS_COOKIE_NAMES[0]), "anonymous-user");
  assert.equal(options.getCookie("flare_session"), "");
  options.setCookie("flare_session", "overwritten-secret"); options.delCookie("flare_locale");
  assert.equal(writes.length, 0);
  options.setCookie(cookies.ANALYTICS_COOKIE_NAMES[0], "replacement-anonymous");
  allowed = false;
  for (const name of cookies.ANALYTICS_COOKIE_NAMES) options.delCookie(name);
  assert.equal(jar.get("flare_session"), "private-auth-token");
  assert.equal(jar.get("flare_locale"), "es");
  assert.equal(jar.get("flare_acquisition"), "private-source");
  assert.equal(cookies.ANALYTICS_COOKIE_NAMES.some(name => jar.has(name)), false);
  assert.equal(writes.length, 3);
  assert.equal(writes.some(value => /private-|flare_session|flare_locale|flare_acquisition/.test(value)), false);
});

test("analytics cookies are fixed, Secure and limited to 30 days regardless of SDK-requested domain, path or expiry", () => {
  const cookies = loadTs("../src/lib/telemetry/cookies.ts");
  const now = Date.parse("2026-10-06T00:00:00Z");
  assert.equal(cookies.COOKIE_MAX_AGE_SECONDS, 30 * 24 * 60 * 60);
  assert.equal(cookies.ANALYTICS_COOKIE_NAMES.length, 2);
  for (const name of cookies.ANALYTICS_COOKIE_NAMES) {
    const assignment = cookies.boundedCookie(name, "anonymous; Domain=attacker.example; Path=/private; SameSite=None; Max-Age=31536000", now);
    assert.match(assignment, /; Path=\/; Secure; SameSite=Lax;/);
    assert.match(assignment, /Max-Age=2592000;/);
    assert.doesNotMatch(assignment, /Domain|attacker|private|SameSite=None/);
    assert.match(cookies.boundedCookie(name, "anonymous; Max-Age=600", now), /Max-Age=600;/);
    assert.match(cookies.boundedCookie(name, "anonymous; Expires=Tue, 06 Oct 2026 00:10:00 GMT", now), /Max-Age=600;/);
    assert.match(cookies.boundedCookie(name, "anonymous; Expires=Mon, 05 Oct 2026 23:00:00 GMT", now), /Max-Age=0;/);
    for (const value of ["", "bad\nvalue", "anonymous; Max-Age=invalid", "anonymous; Expires=invalid", "x".repeat(1025)]) {
      assert.equal(cookies.boundedCookie(name, value, now), null);
    }
  }
  assert.equal(cookies.boundedCookie("flare_session", "private-token", now), null);
  const deletions = cookies.deleteCookieAssignments();
  assert.equal(deletions.length, 2);
  for (const value of deletions) assert.match(value, /Max-Age=0; Expires=Thu, 01 Jan 1970/);
});

test("a cross-tab rejected choice revokes an active SDK before any subsequent page view", async () => {
  const f = fixture(); f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  const before = f.calls.views.length;
  f.entries.set(f.consent.CONSENT_KEY, f.consent.encodeStoredConsent("rejected", Date.parse("2026-10-06T00:00:00Z")));
  f.client.reconcile();
  assert.equal(f.snapshot().choice, "rejected");
  f.client.trackPage("/settings"); await flush();
  assert.equal(f.calls.views.length, before); assert.ok(f.calls.order.includes("pause"));
  f.client.dispose();
});

test("late imports cannot revive an older allowed generation after reject then opt-in again", async () => {
  const first = deferred(); const second = deferred(); let imports = 0;
  const f = fixture({ loadSdk: () => ++imports === 1 ? first.promise : second.promise });
  f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  f.client.setConsent("rejected"); f.client.setConsent("allowed"); await flush();
  first.resolve(f.adapter); await flush();
  assert.equal(f.calls.create.length, 0); assert.equal(f.calls.views.length, 0);
  second.resolve(f.adapter); await flush();
  assert.equal(f.calls.create.length, 1); assert.equal(f.calls.views.length, 1);
  f.client.dispose();
});

test("public connection-string extras cannot enable live endpoints, authorization or custom SDK behavior", () => {
  const { parseTelemetryConfig } = telemetryModules().config;
  const config = parseTelemetryConfig(`${connectionString};Authorization=private-authorization;LiveEndpoint=https://attacker.example/private-workspace;EndpointSuffix=private-suffix`, "true");
  assert.equal(config.ingestionOrigin, "https://centralus-0.in.applicationinsights.azure.com");
  assert.equal(config.connectionString, connectionString);
  assert.doesNotMatch(JSON.stringify(config), /private-|Authorization|LiveEndpoint|EndpointSuffix|attacker/);
});

test("a revoked SDK generation stays inert after a new opt-in, including retained initializers and cookie callbacks", async () => {
  const f = fixture(); f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  const oldInitializer = f.calls.initializers[0];
  const oldCookies = f.calls.rawConfigurations[0].cookieCfg;
  const page = f.config.safePage("/");
  assert.equal(oldInitializer(pageEnvelope(page)), true);
  assert.equal(oldCookies.getCookie("ai_user_flare_site_analytics"), "stable-anonymous-value");
  f.client.setConsent("rejected"); await flush();
  assert.equal(oldInitializer(pageEnvelope(page)), false);
  f.client.setConsent("allowed"); f.client.trackPage("/settings"); await flush();
  assert.equal(f.calls.create.length, 2);
  assert.equal(oldInitializer(pageEnvelope(page)), false, "a new SDK cannot reopen its predecessor's telemetry gate");
  assert.equal(oldCookies.getCookie("ai_user_flare_site_analytics"), "");
  const beforeWrites = f.calls.cookieWrites.length;
  const beforeReads = f.calls.cookieReads;
  oldCookies.setCookie("ai_user_flare_site_analytics", "stale-anonymous-value");
  assert.equal(oldCookies.getCookie("ai_user_flare_site_analytics"), "");
  assert.equal(f.calls.cookieWrites.length, beforeWrites);
  assert.equal(f.calls.cookieReads, beforeReads);
  const currentCookies = f.calls.rawConfigurations.at(-1).cookieCfg;
  currentCookies.setCookie("ai_user_flare_site_analytics", "new-anonymous-value");
  assert.equal(f.calls.cookieWrites.length, beforeWrites + 1);
  assert.equal(f.calls.initializers.at(-1)(pageEnvelope(f.config.safePage("/settings"))), true);
  f.client.dispose();
});

test("telemetry initializer errors and malformed SDK items fail closed instead of relying on SDK fail-open defaults", async () => {
  const f = fixture(); f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  const initialize = f.calls.initializers.at(-1);
  for (const value of [null, undefined, {}, { baseType: "PageviewData" }, { baseType: "PageviewData", baseData: null },
    { baseType: "PageviewData", baseData: { uri: 123 } }]) assert.equal(initialize(value), false);
  const throwing = { baseType: "PageviewData", get baseData() { throw Error("private SDK context error"); } };
  assert.equal(initialize(throwing), false);
  assert.equal(initialize(Object.freeze(pageEnvelope(f.config.safePage("/")))), false);
  f.client.dispose();
});

test("Strict Mode setup-cleanup-setup during SDK loading creates one active SDK and one initial view", async () => {
  const pending = deferred();
  const consent = telemetryModules().consent;
  const now = Date.parse("2026-10-06T00:00:00Z");
  const f = fixture({ now, loadSdk: () => pending.promise,
    stored: { [consent.CONSENT_KEY]: consent.encodeStoredConsent("allowed", now - 1000) } });
  f.client.initialize(); f.client.trackPage("/"); await flush();
  f.client.dispose();
  f.client.initialize(); f.client.trackPage("/"); await flush();
  pending.resolve(f.adapter); await flush();
  assert.equal(f.calls.create.length, 1); assert.equal(f.calls.loads, 1);
  assert.deepEqual(f.calls.views.map(value => value.uri), ["https://flare4u.tech/"]);
  f.client.dispose();
});

test("server-side singleton access never reaches browser storage, cookie APIs or the dynamic SDK import", async () => {
  let imports = 0;
  const mocks = Object.defineProperty({}, "@microsoft/applicationinsights-web", {
    get() { imports++; throw Error("SDK must not load during SSR"); },
  });
  const client = loadTs("../src/lib/telemetry/client.ts", mocks, { process: { env: enabledEnvironment } }).siteAnalytics;
  const snapshot = client.getServerSnapshot();
  assert.equal(client.getSnapshot(), snapshot);
  assert.equal(snapshot.configured, false);
  assert.equal(snapshot.choice, "unset");
  const unsubscribe = client.subscribe(() => { throw Error("server subscription must stay inert"); });
  client.initialize(); client.trackPage("/"); client.setConsent("allowed"); client.reconcile(); client.dispose(); unsubscribe();
  await flush();
  assert.equal(client.getSnapshot(), snapshot); assert.equal(imports, 0);
});

test("bounded analytics cookies cannot outlive the remaining consent period even when the SDK requests a year", () => {
  const cookies = loadTs("../src/lib/telemetry/cookies.ts");
  const now = Date.parse("2026-10-06T00:00:00Z");
  const deadline = now + 2 * 24 * 60 * 60 * 1000;
  for (const name of cookies.ANALYTICS_COOKIE_NAMES) {
    for (const requested of ["anonymous; Max-Age=31536000", "anonymous; Expires=Wed, 06 Oct 2027 00:00:00 GMT", "anonymous"]) {
      const assignment = cookies.boundedCookie(name, requested, now, deadline);
      assert.match(assignment, /Max-Age=172800;/);
      assert.equal(Date.parse(assignment.split("; Expires=")[1]), deadline);
    }
    assert.match(cookies.boundedCookie(name, "anonymous; Max-Age=600", now, deadline), /Max-Age=600;/);
    assert.match(cookies.boundedCookie(name, "anonymous; Max-Age=31536000", deadline, deadline), /Max-Age=0;/);
    assert.equal(cookies.boundedCookie(name, "anonymous", now, Number.NaN), null);
    assert.equal(cookies.boundedCookie(name, "anonymous", now, Number.POSITIVE_INFINITY), null);
  }
});

test("controller SDK cookies renewed on day 29 expire at the original consent deadline and do not renew the choice", async () => {
  const start = Date.parse("2026-10-06T00:00:00Z");
  const day = 24 * 60 * 60 * 1000;
  const f = fixture({ now: start });
  f.client.initialize(); f.client.trackPage("/"); f.client.setConsent("allowed"); await flush();
  const originalChoice = f.entries.get(f.consent.CONSENT_KEY);
  const deadline = f.consent.parseStoredConsent(originalChoice, start).expiresAt;
  assert.equal(deadline, start + 30 * day);
  const cookies = f.calls.rawConfigurations[0].cookieCfg;

  f.setNow(start + 28 * day);
  cookies.setCookie("ai_user_flare_site_analytics", "anonymous; Max-Age=31536000");
  const day28 = f.calls.cookieWrites.at(-1);
  assert.match(day28, /Max-Age=172800;/);
  assert.equal(Date.parse(day28.split("; Expires=")[1]), deadline);

  const day29 = start + 29 * day + 1234;
  f.setNow(day29);
  cookies.setCookie("ai_session_flare_site_analytics", "anonymous-session; Expires=Wed, 06 Oct 2027 00:00:00 GMT");
  const renewed = f.calls.cookieWrites.at(-1);
  const maxAge = Number(/Max-Age=([0-9]+);/.exec(renewed)[1]);
  assert.equal(maxAge, Math.floor((deadline - day29) / 1000));
  assert.ok(Date.parse(renewed.split("; Expires=")[1]) <= deadline);
  assert.equal(f.entries.get(f.consent.CONSENT_KEY), originalChoice);

  f.setNow(deadline);
  const writes = f.calls.cookieWrites.length;
  cookies.setCookie("ai_user_flare_site_analytics", "anonymous; Max-Age=31536000");
  assert.equal(f.calls.cookieWrites.length, writes, "expiry closes the cookie gate even before a timer or navigation runs");
  f.client.dispose();
});
