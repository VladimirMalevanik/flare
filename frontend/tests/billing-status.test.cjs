const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const plain = value => JSON.parse(JSON.stringify(value));
function load(file, mocks = {}, globals = {}) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, AbortController, setTimeout, clearTimeout, fetch,
    require: name => { if (name in mocks) return mocks[name]; throw Error(name); }, ...globals });
  return exports;
}
const api = load("../src/lib/billing/billing-api.ts");
const identity = { userId: "user-one", workspaceId: "workspace-one" };
const free = {
  environment: "sandbox", workspaceId: identity.workspaceId, plan: "free", status: null,
  canManageBilling: true, checkoutAvailable: true, accessUntil: null, trialEndsAt: null,
  currentPeriodEndsAt: null, scheduledChange: null,
};
const pro = { ...free, plan: "pro", status: "trialing", trialEndsAt: "2099-11-03T00:00:00Z", accessUntil: "2099-11-03T00:00:00Z" };
const intent = {
  environment: "sandbox", priceId: "pri_01m3y1nvmgw2avt60bz87161c2", quantity: 1,
  email: "owner@example.test", customData: { userId: identity.userId, checkoutIntent: "server-intent" },
  expiresAt: "2099-01-01T00:00:00Z",
};
function fakeTimers() {
  let id = 0;
  const pending = new Map();
  return {
    setTimeout(fn, ms) { pending.set(++id, { fn, ms }); return id; },
    clearTimeout(key) { pending.delete(key); },
    fire(ms) { for (const [key, value] of [...pending]) if (value.ms === ms) { pending.delete(key); value.fn(); } },
    count: () => pending.size,
  };
}
async function flush() { for (let i = 0; i < 15; i++) await Promise.resolve(); }
function setup(loader = async () => free, options = {}) {
  const timers = fakeTimers();
  const calls = [];
  const { createBillingStatusClient } = load("../src/lib/billing/billing-status-controller.ts", { "./billing-api": api }, timers);
  const client = createBillingStatusClient({ load: async signal => { calls.push(signal); return loader(signal); }, ...options });
  return { client, timers, calls, snapshot: () => plain(client.getSnapshot()) };
}

test("billing requests send only authenticated cookies and empty intent body; server response owns checkout identity", async () => {
  const calls = [];
  const client = api.createBillingApi({ baseUrl: "/api", request: async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => url.endsWith("status") ? free : intent };
  } });
  const signal = new AbortController().signal;
  assert.deepEqual(plain(await client.getStatus(signal)), free);
  assert.deepEqual(plain(await client.createCheckoutIntent(signal)), intent);
  assert.equal(calls[0].url, "/api/billing/status");
  assert.equal(calls[1].url, "/api/billing/checkout-intents");
  assert.equal(calls[1].options.body, "{}");
  for (const { options } of calls) {
    assert.equal(options.credentials, "include");
    assert.equal(options.cache, "no-store");
    assert.equal(options.signal, signal);
    assert.doesNotMatch(JSON.stringify(options), /user-one|owner@example/);
  }
});

test("Live, incomplete and invented plan API responses never become a verified status or intent", () => {
  for (const value of [null, {}, { ...free, environment: "live" }, { ...free, plan: "team" },
    { ...free, checkoutAvailable: "true" }, { ...free, scheduledChange: {} }]) {
    assert.throws(() => api.parseBillingStatus(value), api.BillingRequestError);
  }
  for (const value of [null, {}, { ...intent, environment: "live" }, { ...intent, quantity: 2 },
    { ...intent, customData: { userId: identity.userId } }]) {
    assert.throws(() => api.parseCheckoutIntent(value), api.BillingRequestError);
  }
  assert.equal(api.parseBillingStatus(pro).plan, "pro");
  for (const accessUntil of [null, "", "invalid-date"]) {
    assert.throws(() => api.parseBillingStatus({ ...pro, accessUntil }), api.BillingRequestError);
  }
});

test("auth, ownership, setup and server errors expose only safe error codes", async () => {
  for (const [status, detail, expected] of [[401, "private detail", "auth"], [403, "private", "permission"],
    [503, { code: "billing_not_configured", message: "private" }, "configuration"], [500, "private", "backend"]]) {
    const client = api.createBillingApi({ baseUrl: "/api", request: async () => ({ ok: false, status, json: async () => ({ detail }) }) });
    await assert.rejects(client.getStatus(new AbortController().signal), error => error.code === expected && !error.message.includes("private"));
  }
});

test("server Free stays Free after completion; bounded polling switches to Pro only after a verified response", async () => {
  let response = free;
  const f = setup(async () => response);
  f.client.start(identity);
  await flush();
  assert.equal(f.snapshot().status.plan, "free");
  f.client.confirmCheckout(1);
  await flush();
  assert.equal(f.snapshot().status.plan, "free");
  assert.equal(f.snapshot().pendingConfirmation, true);
  const before = f.calls.length;
  f.client.confirmCheckout(1);
  assert.equal(f.calls.length, before);
  response = pro;
  f.timers.fire(2000);
  await flush();
  assert.equal(f.snapshot().status.plan, "pro");
  assert.equal(f.snapshot().pendingConfirmation, false);
  assert.equal(f.timers.count(), 1);
  f.client.stop();
  assert.equal(f.timers.count(), 0);
});

test("mount and identity changes baseline historical checkout completions without polling or blocking Buy", async () => {
  const f = setup();
  f.client.start(identity, 12);
  await flush();
  const mountedCalls = f.calls.length;
  f.client.confirmCheckout(12);
  f.client.confirmCheckout(11);
  await flush();
  assert.equal(f.calls.length, mountedCalls);
  assert.equal(f.snapshot().phase, "ready");
  assert.equal(f.snapshot().status.plan, "free");
  assert.equal(f.snapshot().pendingConfirmation, false);
  assert.equal(f.timers.count(), 0);
  f.client.confirmCheckout(13);
  await flush();
  assert.equal(f.calls.length, mountedCalls + 1);
  assert.equal(f.snapshot().pendingConfirmation, true);

  // Another verified member/owner in the workspace must not inherit that poll.
  f.client.start({ ...identity, userId: "another-user" }, 13);
  await flush();
  const nextCalls = f.calls.length;
  f.client.confirmCheckout(13);
  await flush();
  assert.equal(f.calls.length, nextCalls);
  assert.equal(f.snapshot().pendingConfirmation, false);
  assert.equal(f.timers.count(), 0);
  f.client.stop();
});

test("confirmation polling stops at its deadline and explicit status check can later confirm Pro", async () => {
  let response = free;
  const f = setup(async () => response);
  f.client.start(identity); await flush();
  f.client.confirmCheckout(1); await flush();
  f.timers.fire(30000);
  assert.equal(f.snapshot().pendingConfirmation, false);
  assert.equal(f.snapshot().confirmationTimedOut, true);
  assert.equal(f.timers.count(), 0);
  const before = f.calls.length;
  f.timers.fire(2000); await flush();
  assert.equal(f.calls.length, before);
  response = pro;
  await f.client.checkAgain();
  assert.equal(f.snapshot().status.plan, "pro");
  assert.equal(f.snapshot().confirmationTimedOut, false);
  f.client.stop();
});

test("changing identity aborts pending work and ignores another workspace's late Pro response", async () => {
  let resolveFirst;
  let index = 0;
  const secondIdentity = { userId: "user-two", workspaceId: "workspace-two" };
  const secondFree = { ...free, workspaceId: secondIdentity.workspaceId, canManageBilling: false };
  const f = setup(() => ++index === 1 ? new Promise(resolve => { resolveFirst = resolve; }) : Promise.resolve(secondFree));
  f.client.start(identity);
  f.client.start(secondIdentity);
  await flush();
  assert.equal(f.calls[0].aborted, true);
  assert.equal(f.snapshot().status.workspaceId, secondIdentity.workspaceId);
  resolveFirst(pro); await flush();
  assert.equal(f.snapshot().status.plan, "free");
  assert.equal(f.snapshot().status.canManageBilling, false);
  assert.equal(f.timers.count(), 0);
  f.client.stop();
});

test("unmount stops polling and aborts pending requests without late state updates", async () => {
  let resolve;
  const f = setup(() => new Promise(done => { resolve = done; }));
  const updates = [];
  const unsubscribe = f.client.subscribe(() => updates.push(f.snapshot()));
  f.client.start(identity);
  f.client.confirmCheckout(1);
  f.client.stop();
  await flush();
  assert.equal(f.calls[0].aborted, true);
  const count = updates.length;
  resolve(pro); await flush();
  assert.equal(updates.length, count);
  assert.equal(f.timers.count(), 0);
  unsubscribe();
});

test("status request timeout and mismatched workspace fail closed without inventing Free or Pro", async () => {
  const f = setup(() => new Promise(() => {}));
  f.client.start(identity);
  f.timers.fire(8000); await flush();
  assert.equal(f.snapshot().phase, "error");
  assert.equal(f.snapshot().error, "backend");
  assert.equal(f.snapshot().status, null);
  assert.equal(f.calls[0].aborted, true);
  assert.equal(f.timers.count(), 0);
  f.client.stop();
  const other = setup(async () => ({ ...pro, workspaceId: "other" }));
  other.client.start(identity); await flush();
  assert.equal(other.snapshot().status, null);
  assert.equal(other.snapshot().error, "backend");
  other.client.stop();
});

test("authentication and partial setup failures stop confirmation polling without affecting app access", async () => {
  for (const code of ["auth", "configuration"]) {
    const f = setup(async () => { throw new api.BillingRequestError(code); });
    f.client.start(identity); await flush();
    f.client.confirmCheckout(1); await flush();
    assert.equal(f.snapshot().error, code);
    assert.equal(f.snapshot().pendingConfirmation, false);
    assert.equal(f.timers.count(), 0);
    f.client.stop();
  }
});

test("Pro expires to unknown before its refresh confirms Free or an outage, never keeping expired Current", async () => {
  for (const outcome of ["free", "outage"]) {
    let now = Date.now();
    const expires = now + 1000;
    let resolve;
    let calls = 0;
    const f = setup(async () => {
      if (++calls === 1) return { ...pro, accessUntil: new Date(expires).toISOString() };
      return new Promise(done => { resolve = done; });
    }, { now: () => now });
    f.client.start(identity); await flush();
    assert.equal(f.snapshot().status.plan, "pro");
    now = expires;
    f.timers.fire(1000);
    assert.equal(f.snapshot().status, null);
    assert.equal(f.snapshot().phase, "loading");
    await flush();
    if (outcome === "free") resolve(free);
    else f.timers.fire(8000);
    await flush();
    assert.equal(f.snapshot().status?.plan ?? null, outcome === "free" ? "free" : null);
    assert.equal(f.snapshot().error, outcome === "outage" ? "backend" : null);
    assert.equal(f.timers.count(), 0);
    f.client.stop();
  }
});

test("a stale Pro API response past its access deadline fails closed instead of restoring an expired plan", async () => {
  const now = Date.now();
  const f = setup(async () => ({ ...pro, accessUntil: new Date(now - 1).toISOString() }), { now: () => now });
  f.client.start(identity); await flush();
  assert.equal(f.snapshot().status, null);
  assert.equal(f.snapshot().error, "backend");
  assert.equal(f.timers.count(), 0);
  f.client.stop();
});

test("expiry timers belong to the latest identity and plan, and a long trial cannot overflow browser timers", async () => {
  let now = Date.now();
  let response = { ...pro, accessUntil: new Date(now + 1000).toISOString() };
  const f = setup(async () => response, { now: () => now });
  f.client.start(identity); await flush();
  response = { ...free, workspaceId: "second-workspace" };
  f.client.start({ userId: "second-user", workspaceId: "second-workspace" }); await flush();
  const count = f.calls.length;
  now += 1000;
  f.timers.fire(1000); await flush();
  assert.equal(f.calls.length, count);
  assert.equal(f.snapshot().status.workspaceId, "second-workspace");
  f.client.stop();

  response = { ...pro, accessUntil: new Date(now + 30 * 86400000).toISOString() };
  f.client.start(identity); await flush();
  f.timers.fire(2_147_483_647); await flush();
  assert.equal(f.snapshot().status.plan, "pro");
  assert.equal(f.calls.length, count + 1);
  assert.equal(f.timers.count(), 1);
  response = free;
  await f.client.refresh();
  assert.equal(f.timers.count(), 0);
  f.client.stop();
});
