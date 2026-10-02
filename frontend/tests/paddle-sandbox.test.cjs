const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const priceId = "pri_01m3y1nvmgw2avt60bz87161c2";
const publicTestToken = "test_placeholder_for_unit_tests";
const user = { id: "flare-user", email: "founder@example.com" };
const plain = (value) => JSON.parse(JSON.stringify(value));

function load(relative, mocks = {}, globals = {}) {
  const filename = path.join(__dirname, relative);
  const code = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, {
    exports,
    __dirname: path.dirname(filename),
    process: { env: {} },
    setTimeout,
    clearTimeout,
    require(name) {
      if (name in mocks) return mocks[name];
      throw Error(`Unexpected import ${name}`);
    },
    ...globals,
  });
  return exports;
}

function fakeTimers() {
  const pending = new Map();
  let id = 0;
  return {
    setTimeout(fn, ms) { pending.set(++id, { fn, ms }); return id; },
    clearTimeout(timerId) { pending.delete(timerId); },
    fire(ms) {
      for (const [timerId, timer] of [...pending]) {
        if (timer.ms !== ms) continue;
        pending.delete(timerId);
        timer.fn();
      }
    },
    fireNext(ms) {
      const next = [...pending].find(([, timer]) => timer.ms === ms);
      if (next) {
        pending.delete(next[0]);
        next[1].fn();
      }
    },
    count: () => pending.size,
  };
}

function setup(overrides = {}) {
  const timers = fakeTimers();
  const calls = { initialized: [], opened: [], closed: 0 };
  let eventCallback;
  const paddle = {
    Initialized: true,
    Checkout: {
      open(options) { calls.opened.push(options); },
      close() { calls.closed++; eventCallback?.({ name: "checkout.closed" }); },
    },
  };
  const { createSandboxCheckoutClient } = load("../src/lib/billing/checkout-controller.ts", {}, timers);
  const client = createSandboxCheckoutClient({
    token: publicTestToken,
    proPriceId: priceId,
    loadTimeoutMs: 30,
    openTimeoutMs: 40,
    ...overrides,
    initialize: async (options) => {
      calls.initialized.push(options);
      eventCallback = options.eventCallback;
      return overrides.initialize ? overrides.initialize(options, paddle) : paddle;
    },
  });
  return {
    client, calls, paddle, timers,
    emit: (name, extra = {}) => eventCallback?.({ name, ...extra }),
    snapshot: () => plain(client.getSnapshot()),
  };
}

async function flushMicrotasks() {
  for (let count = 0; count < 5; count++) await Promise.resolve();
}

test("missing configuration, Live tokens, invalid prices, and missing identity fail before SDK initialization", async () => {
  const cases = [
    [{ token: undefined }, user, "configuration"],
    [{ token: "   " }, user, "configuration"],
    [{ proPriceId: undefined }, user, "configuration"],
    [{ token: "live_placeholder" }, user, "sandbox-only"],
    [{ token: "test_" }, user, "sandbox-only"],
    [{ proPriceId: "pri_01m3pri_mgw2avt60bz87161c2" }, user, "price"],
    [{ proPriceId: "unexpected" }, user, "price"],
    [{}, null, "auth"],
    [{}, { id: " ", email: user.email }, "auth"],
    [{}, { id: 123, email: user.email }, "auth"],
    [{}, { id: null, email: user.email }, "auth"],
    [{}, { id: user.id, email: null }, "auth"],
    [{}, { id: user.id, email: "not-an-email" }, "auth"],
  ];
  for (const [configuration, identity, error] of cases) {
    const f = setup(configuration);
    await f.client.openProCheckout(identity, "en");
    assert.deepEqual(f.snapshot(), { phase: "idle", error });
    assert.equal(f.calls.initialized.length, 0);
    assert.equal(f.calls.opened.length, 0);
    assert.equal(f.timers.count(), 0);
  }
});

test("synchronous click lock prevents concurrent checkouts and initialization happens once across retries", async () => {
  let resolve;
  const f = setup({ initialize: (_options, sdk) => new Promise((done) => { resolve = () => done(sdk); }) });
  const first = f.client.openProCheckout(user, "en");
  assert.equal(f.snapshot().phase, "loading");
  await f.client.openProCheckout(user, "en");
  await flushMicrotasks();
  assert.equal(f.calls.initialized.length, 1);
  resolve();
  await first;
  assert.equal(f.calls.opened.length, 1);
  f.emit("checkout.loaded");
  await f.client.openProCheckout(user, "en");
  assert.equal(f.calls.opened.length, 1);
  f.emit("checkout.closed");
  await f.client.openProCheckout(user, "es");
  assert.equal(f.calls.initialized.length, 1);
  assert.equal(f.calls.opened.length, 2);
  f.emit("checkout.closed");
  assert.equal(f.timers.count(), 0);
});

test("checkout sends the exact Sandbox price, quantity, authenticated email, and user ID without other account fields", async () => {
  const f = setup({ token: ` ${publicTestToken} `, proPriceId: ` ${priceId} `, getTheme: () => "dark" });
  await f.client.openProCheckout({ ...user, password: "must-not-send", token: "must-not-send", workspace: "extra" }, "es");
  const initialization = f.calls.initialized[0];
  assert.equal(initialization.environment, "sandbox");
  assert.equal(initialization.token, publicTestToken);
  assert.equal(typeof initialization.eventCallback, "function");
  assert.deepEqual(plain(f.calls.opened[0]), {
    items: [{ priceId, quantity: 1 }],
    customer: { email: user.email },
    customData: { userId: user.id },
    settings: { displayMode: "overlay", allowLogout: false, locale: "es", theme: "dark" },
  });
  assert.doesNotMatch(JSON.stringify(f.calls.opened[0]), /must-not-send|password|token|workspace/);
  f.emit("checkout.closed");
});

test("SDK rejection, undefined result, and an uninitialized SDK release the lock without opening checkout", async () => {
  for (const initialize of [
    async () => { throw Error("private provider detail"); },
    async () => undefined,
    async () => ({ Initialized: false, Checkout: { open: () => assert.fail("uninitialized SDK") } }),
  ]) {
    const f = setup({ initialize });
    await f.client.openProCheckout(user, "en");
    assert.deepEqual(f.snapshot(), { phase: "idle", error: "load" });
    assert.equal(f.calls.opened.length, 0);
    assert.equal(f.timers.count(), 0);
    await f.client.openProCheckout(user, "en");
    assert.equal(f.calls.initialized.length, 1);
    assert.equal(f.snapshot().error, "load");
  }
});

test("load timeout never opens checkout automatically after the SDK eventually resolves", async () => {
  let resolve;
  const f = setup({ initialize: (_options, sdk) => new Promise((done) => { resolve = () => done(sdk); }) });
  const opening = f.client.openProCheckout(user, "en");
  await flushMicrotasks();
  f.timers.fire(30);
  await opening;
  assert.deepEqual(f.snapshot(), { phase: "idle", error: "load" });
  resolve();
  await flushMicrotasks();
  assert.equal(f.calls.opened.length, 0);
  assert.equal(f.snapshot().error, "load");
  await f.client.openProCheckout(user, "en");
  assert.equal(f.calls.initialized.length, 1);
  assert.equal(f.calls.opened.length, 1);
  f.emit("checkout.closed");
});

test("throwing Checkout.open closes a partial overlay and retry reuses the initialized SDK", async () => {
  const f = setup();
  const originalOpen = f.paddle.Checkout.open;
  f.paddle.Checkout.open = () => { throw Error("private checkout error"); };
  await f.client.openProCheckout(user, "en");
  assert.deepEqual(f.snapshot(), { phase: "idle", error: "open" });
  assert.equal(f.calls.closed, 1);
  assert.equal(f.timers.count(), 0);
  f.paddle.Checkout.open = originalOpen;
  await f.client.openProCheckout(user, "en");
  assert.equal(f.calls.initialized.length, 1);
  assert.equal(f.calls.opened.length, 1);
  f.emit("checkout.closed");
});

test("cancelling pending SDK loading ignores late success and explicit restart shares the same initialization", async () => {
  let resolve;
  const f = setup({ initialize: (_options, sdk) => new Promise((done) => { resolve = () => done(sdk); }) });
  const first = f.client.openProCheckout(user, "en");
  await flushMicrotasks();
  f.client.cancelPendingCheckout();
  assert.deepEqual(f.snapshot(), { phase: "idle", error: null });
  resolve();
  await first;
  assert.equal(f.calls.opened.length, 0);
  assert.equal(f.timers.count(), 0);
  await f.client.openProCheckout(user, "es");
  assert.equal(f.calls.initialized.length, 1);
  assert.equal(f.calls.opened.length, 1);
  assert.equal(f.calls.opened[0].settings.locale, "es");
  f.emit("checkout.closed");
});

test("old load timeout cannot overwrite a newer attempt after cancellation and restart", async () => {
  let resolve;
  const f = setup({ initialize: (_options, sdk) => new Promise((done) => { resolve = () => done(sdk); }) });
  const first = f.client.openProCheckout(user, "en");
  await flushMicrotasks();
  f.client.cancelPendingCheckout();
  const second = f.client.openProCheckout(user, "es");
  await flushMicrotasks();
  f.timers.fireNext(30);
  await first;
  assert.deepEqual(f.snapshot(), { phase: "loading", error: null });
  assert.equal(f.calls.opened.length, 0);
  resolve();
  await second;
  assert.equal(f.calls.initialized.length, 1);
  assert.equal(f.calls.opened.length, 1);
  assert.equal(f.calls.opened[0].settings.locale, "es");
  f.emit("checkout.closed");
});

test("cancelling before checkout.loaded closes the pending overlay and ignores its stale events and deadline", async () => {
  const f = setup();
  await f.client.openProCheckout(user, "en");
  assert.equal(f.snapshot().phase, "loading");
  f.client.cancelPendingCheckout();
  assert.equal(f.calls.closed, 1);
  assert.equal(f.timers.count(), 0);
  f.emit("checkout.loaded");
  f.emit("checkout.error");
  f.emit("checkout.completed");
  f.timers.fire(40);
  assert.deepEqual(f.snapshot(), { phase: "idle", error: null });
  await f.client.openProCheckout(user, "en");
  assert.equal(f.calls.initialized.length, 1);
  assert.equal(f.calls.opened.length, 2);
  f.emit("checkout.closed");
});

test("unmount cancellation keeps already loaded or completed checkout open and locked", async () => {
  for (const event of ["checkout.loaded", "checkout.completed"]) {
    const f = setup();
    await f.client.openProCheckout(user, "en");
    f.emit(event);
    const before = f.snapshot();
    f.client.cancelPendingCheckout();
    assert.deepEqual(f.snapshot(), before);
    assert.equal(f.calls.closed, 0);
    await f.client.openProCheckout(user, "en");
    assert.equal(f.calls.opened.length, 1);
    f.emit("checkout.closed");
  }
});

test("overlay opening timeout and checkout error clean up, preserve the error, and allow retry", async () => {
  for (const fail of [(f) => f.timers.fire(40), (f) => f.emit("checkout.error"), (f) => f.emit("checkout.failed")]) {
    const f = setup();
    await f.client.openProCheckout(user, "en");
    fail(f);
    assert.deepEqual(f.snapshot(), { phase: "idle", error: "open" });
    assert.equal(f.calls.closed, 1);
    assert.equal(f.timers.count(), 0);
    f.emit("checkout.completed");
    assert.equal(f.snapshot().error, "open");
    await f.client.openProCheckout(user, "en");
    assert.equal(f.calls.initialized.length, 1);
    assert.equal(f.calls.opened.length, 2);
    f.emit("checkout.closed");
  }
});

test("checkout.loaded cancels the opening deadline and payment errors keep the existing overlay locked", async () => {
  const f = setup();
  await f.client.openProCheckout(user, "en");
  f.emit("checkout.loaded");
  assert.deepEqual(f.snapshot(), { phase: "open", error: null });
  assert.equal(f.timers.count(), 0);
  for (const name of ["checkout.payment.failed", "checkout.payment.error"]) {
    f.emit(name, { data: { email: "private@example.com", payment: "private" } });
    assert.deepEqual(f.snapshot(), { phase: "open", error: "payment" });
    await f.client.openProCheckout(user, "en");
    assert.equal(f.calls.opened.length, 1);
    assert.equal(f.calls.closed, 0);
  }
  f.emit("checkout.closed");
  assert.deepEqual(f.snapshot(), { phase: "idle", error: null });
});

test("completed checkout changes no account data and remains locked until the success overlay closes", async () => {
  const identity = Object.freeze({ ...user, plan: "free" });
  const f = setup();
  await f.client.openProCheckout(identity, "en");
  f.emit("checkout.completed", { data: { subscription_id: "sub_external", custom_data: { plan: "pro" } } });
  assert.deepEqual(f.snapshot(), { phase: "complete", error: null });
  assert.equal(identity.plan, "free");
  assert.deepEqual(Object.keys(f.client.getSnapshot()).sort(), ["error", "phase"]);
  await f.client.openProCheckout(user, "en");
  assert.equal(f.calls.opened.length, 1);
  assert.equal(f.timers.count(), 0);
  f.emit("checkout.closed");
  await f.client.openProCheckout(user, "en");
  assert.equal(f.calls.opened.length, 2);
  f.emit("checkout.closed");
});

test("external-store subscribers receive changes, unsubscribe cleanly, and server snapshot always stays initial", async () => {
  const f = setup();
  const updates = [];
  const unsubscribe = f.client.subscribe(() => updates.push(f.snapshot()));
  const initialServer = f.client.getServerSnapshot();
  assert.deepEqual(plain(initialServer), { phase: "idle", error: null });
  await f.client.openProCheckout(user, "en");
  f.emit("checkout.loaded");
  assert.equal(updates.length, 2);
  assert.equal(f.client.getServerSnapshot(), initialServer);
  assert.equal(f.client.getSnapshot(), f.client.getSnapshot());
  unsubscribe();
  f.emit("checkout.completed");
  assert.equal(updates.length, 2);
  f.emit("checkout.closed");
});

test("public adapter loads the official SDK lazily and shares one controller with the current document theme", async () => {
  const { createSandboxCheckoutClient } = load("../src/lib/billing/checkout-controller.ts");
  let importCount = 0, options;
  const opened = [];
  const paddle = { Initialized: true, Checkout: { open: (value) => opened.push(value), close() {} } };
  const adapter = load("../src/lib/billing/paddle-sandbox.ts", {
    "./checkout-controller": { createSandboxCheckoutClient },
    "@paddle/paddle-js": { initializePaddle: async (value) => { importCount++; options = value; return paddle; } },
  }, {
    process: { env: { NEXT_PUBLIC_PADDLE_CLIENT_TOKEN: publicTestToken, NEXT_PUBLIC_PADDLE_PRO_PRICE_ID: priceId, PADDLE_API_KEY: "must-not-use" } },
    document: { documentElement: { dataset: { theme: "dark" } } },
  });
  const client = adapter.paddleSandboxCheckout;
  assert.equal(importCount, 0);
  await client.openProCheckout(user, "en");
  assert.equal(importCount, 1);
  assert.equal(options.environment, "sandbox");
  assert.equal(opened[0].settings.theme, "dark");
  options.eventCallback({ name: "checkout.closed" });
  await client.openProCheckout(user, "es");
  assert.equal(importCount, 1);
  options.eventCallback({ name: "checkout.closed" });
});

const jsx = {
  jsx: (type, props) => ({ type, props }),
  jsxs: (type, props) => ({ type, props }),
};
function nodes(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function textContent(node) {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textContent).join(" ");
  return node ? textContent(node.props?.children) : "";
}
function uiSetup(locale = "en", session = { user }) {
  const f = setup();
  let notice = null;
  let cleanup;
  const { subscriptionCopy } = load("../src/features/subscription/subscription-copy.ts");
  const { SubscriptionSection } = load("../src/features/subscription/subscription-section.tsx", {
    "react/jsx-runtime": jsx,
    react: {
      useState: () => [notice, (next) => { notice = next; }],
      useEffect: (effect) => { cleanup ??= effect(); },
      useSyncExternalStore: (_subscribe, snapshot) => snapshot(),
    },
    "@/components/auth-session": { useSession: () => session },
    "@/components/icons": { Icon: "icon" },
    "@/i18n/provider": { useI18n: () => ({ locale }) },
    "@/lib/billing/paddle-sandbox": { paddleSandboxCheckout: f.client },
    "./subscription-copy": { subscriptionCopy },
    "./subscription-section.module.css": { current: "current", plan: "plan", selected: "selected", error: "error" },
  });
  return {
    ...f,
    render: () => SubscriptionSection(),
    buttons: () => nodes(SubscriptionSection()).filter((node) => node.type === "button"),
    unmount: () => cleanup?.(),
  };
}

test("Subscription renders three plans with Current on Free, blue Buy buttons, and the configured trial description", () => {
  const f = uiSetup();
  const tree = f.render();
  const elements = nodes(tree);
  assert.deepEqual(elements.filter((node) => node.type === "h3").map(textContent), ["Free", "Pro", "Team"]);
  const [free, pro, team] = f.buttons();
  assert.equal(textContent(free), "Current");
  assert.equal(free.props.disabled, true);
  assert.match(free.props.className, /current/);
  assert.equal(textContent(pro), "Buy");
  assert.equal(textContent(team), "Buy");
  for (const button of [pro, team]) {
    assert.match(button.props.className, /\bprimary\b/);
    assert.equal(button.props.disabled, false);
  }
  assert.match(textContent(tree), /30-day free trial/);
  assert.match(textContent(tree), /Planned benefits/);
  assert.equal(elements.filter((node) => node.type === "li").length, 9);
});

test("Team Buy explains the missing price and never starts a Pro checkout", () => {
  const f = uiSetup();
  f.buttons()[2].props.onClick();
  assert.equal(f.calls.initialized.length, 0);
  assert.equal(f.calls.opened.length, 0);
  const notice = nodes(f.render()).find((node) => node.props?.role === "status");
  assert.match(textContent(notice), /Team checkout is not configured/);
  assert.equal(textContent(f.buttons()[0]), "Current");
});

test("Subscription effect cleanup prevents checkout appearing after navigating away during SDK loading", async () => {
  const f = uiSetup();
  f.buttons()[1].props.onClick();
  assert.equal(f.snapshot().phase, "loading");
  f.unmount();
  await flushMicrotasks();
  assert.deepEqual(f.snapshot(), { phase: "idle", error: null });
  assert.equal(f.calls.opened.length, 0);
  assert.equal(f.timers.count(), 0);
});

test("UI locks both Buy buttons through loading, open, and completed and always leaves Free current", async () => {
  const f = uiSetup();
  f.buttons()[1].props.onClick();
  assert.ok(f.buttons().every((button) => button.props.disabled));
  assert.equal(textContent(f.buttons()[1]), "Loading…");
  await flushMicrotasks();
  f.emit("checkout.loaded");
  assert.equal(textContent(f.buttons()[1]), "Checkout open");
  assert.ok(f.buttons().every((button) => button.props.disabled));
  f.emit("checkout.completed");
  assert.equal(textContent(f.buttons()[0]), "Current");
  assert.match(textContent(f.render()), /Your plan is still Free/);
  assert.ok(f.buttons().every((button) => button.props.disabled));
  f.emit("checkout.closed");
  assert.equal(textContent(f.buttons()[0]), "Current");
  assert.equal(f.buttons()[1].props.disabled, false);
});

test("missing session shows an accessible error and no local profile can become checkout identity", () => {
  const f = uiSetup("en", null);
  f.buttons()[1].props.onClick();
  const error = nodes(f.render()).find((node) => node.props?.role === "alert");
  assert.match(textContent(error), /Please sign in/);
  assert.equal(f.calls.initialized.length, 0);
});

test("Spanish subscription messages, plan buttons, and provider locale remain localized", async () => {
  const f = uiSetup("es");
  assert.match(textContent(f.render()), /Suscripción/);
  assert.equal(textContent(f.buttons()[0]), "Actual");
  assert.equal(textContent(f.buttons()[1]), "Comprar");
  assert.match(textContent(f.render()), /Prueba gratuita de 30 días/);
  f.buttons()[2].props.onClick();
  assert.match(textContent(f.render()), /precio independiente para Team/);
  f.buttons()[1].props.onClick();
  await flushMicrotasks();
  assert.equal(f.calls.opened[0].settings.locale, "es");
  f.emit("checkout.closed");
});

test("document CSP permits lazy Sandbox checkout even after client navigation and keeps all security protections", async () => {
  for (const environment of ["development", "production"]) {
    const config = load("../next.config.ts", {}, { process: { env: { NODE_ENV: environment } } }).default;
    const headers = await config.headers();
    const baseline = headers.find((route) => route.source === "/:path*");
    assert.ok(baseline);
    const csp = (route) => route.headers.find((header) => header.key === "Content-Security-Policy").value;
    const directives = Object.fromEntries(csp(baseline).split("; ").map((line) => {
      const [name, ...values] = line.split(" ");
      return [name, values];
    }));
    assert.deepEqual(directives["connect-src"], ["'self'", "https://sandbox-api.paddle.com"]);
    assert.deepEqual(directives["frame-src"], ["'self'", "https://sandbox-buy.paddle.com", "https://sandbox-cdn.paddle.com"]);
    assert.deepEqual(directives["style-src"], ["'self'", "'unsafe-inline'", "https://sandbox-cdn.paddle.com"]);
    assert.deepEqual(directives["img-src"], ["'self'", "data:", "https://sandbox-cdn.paddle.com"]);
    assert.deepEqual(directives["script-src"], environment === "production"
      ? ["'self'", "'unsafe-inline'", "https://cdn.paddle.com"]
      : ["'self'", "'unsafe-inline'", "'unsafe-eval'", "https://cdn.paddle.com"]);
    assert.deepEqual(directives["default-src"], ["'self'"]);
    assert.deepEqual(directives["base-uri"], ["'self'"]);
    assert.deepEqual(directives["font-src"], ["'self'"]);
    assert.deepEqual(directives["form-action"], ["'self'"]);
    assert.deepEqual(directives["frame-ancestors"], ["'none'"]);
    assert.deepEqual(directives["object-src"], ["'none'"]);
    assert.doesNotMatch(csp(baseline), /https:\/\/(?:buy|api|checkout)\.paddle\.com|\*/);
    assert.ok(baseline.headers.some((header) => header.key === "X-Frame-Options" && header.value === "DENY"));
    assert.ok(baseline.headers.some((header) => header.key === "X-Content-Type-Options" && header.value === "nosniff"));
    assert.ok(baseline.headers.some((header) => header.key === "Referrer-Policy" && header.value === "strict-origin-when-cross-origin"));
    assert.equal(baseline.headers.some((header) => header.key === "Strict-Transport-Security" && header.value === "max-age=31536000; includeSubDomains"), environment === "production");
    assert.deepEqual(plain(await config.redirects()), [{
      source: "/:path*", has: [{ type: "host", value: "www.flare4u.tech" }],
      destination: "https://flare4u.tech/:path*", permanent: true,
    }]);
    assert.deepEqual(plain(await config.rewrites()), [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/:path*" }]);
  }
});

test("the official package and public build variables are wired without Paddle server secrets", () => {
  const frontend = path.join(__dirname, "..");
  const packageJson = JSON.parse(fs.readFileSync(path.join(frontend, "package.json"), "utf8"));
  assert.ok(packageJson.dependencies["@paddle/paddle-js"]);
  const files = [
    ".env.example", "Dockerfile", "src/lib/billing/paddle-sandbox.ts",
    "../.github/workflows/azure-web-artifact.yml", "../.github/workflows/azure-appservice-release.yml",
  ];
  for (const file of files) {
    const source = fs.readFileSync(path.join(frontend, file), "utf8");
    assert.match(source, /NEXT_PUBLIC_PADDLE_CLIENT_TOKEN/);
    assert.match(source, /NEXT_PUBLIC_PADDLE_PRO_PRICE_ID/);
    assert.doesNotMatch(source, /(?:NEXT_PUBLIC_)?PADDLE_(?:API_KEY|WEBHOOK_SECRET)\s*[:=]/);
    assert.doesNotMatch(source, /live_[A-Za-z0-9_-]+/);
  }
  const example = fs.readFileSync(path.join(frontend, ".env.example"), "utf8");
  assert.match(example, /^NEXT_PUBLIC_PADDLE_CLIENT_TOKEN=\s*$/m);
  assert.match(example, new RegExp(`^NEXT_PUBLIC_PADDLE_PRO_PRICE_ID=${priceId}$`, "m"));
});
