const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const session = {
  user: { id: 'synthetic-user', emailVerified: true, legalAccepted: true },
  workspace: { id: 'synthetic-workspace' },
};
const flush = () => new Promise(resolve => setImmediate(resolve));

function eventTarget() {
  const listeners = new Map();
  return {
    addEventListener(name, callback) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(callback);
    },
    removeEventListener(name, callback) { listeners.get(name)?.delete(callback); },
    emit(name, properties = {}) {
      for (const callback of [...(listeners.get(name) ?? [])]) callback({ type: name, ...properties });
    },
    count(name) { return listeners.get(name)?.size ?? 0; },
  };
}

function fixture({ demo = false, visible = true } = {}) {
  const requests = [];
  const navigations = [];
  const timers = new Map();
  let timerId = 0;
  let effect;
  const window = {
    ...eventTarget(),
    location: { replace(destination) { navigations.push(destination); } },
  };
  const document = {
    ...eventTarget(),
    visibilityState: visible ? 'visible' : 'hidden',
  };
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(
    path.join(__dirname, '../src/components/auth-entry-session.tsx'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, {
    exports, window, document, AbortController,
    setTimeout(callback, milliseconds) {
      const id = ++timerId;
      timers.set(id, { callback, milliseconds });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    require(name) {
      if (name === 'react') return { useEffect(callback) { effect = callback; } };
      if (name === '@/lib/auth/session') return { apiBaseUrl: '/api', isLocalDemo: demo };
      throw Error(`Unexpected import ${name}`);
    },
    fetch(url, options) {
      // The synthetic transport intentionally ignores aborts: the component must
      // independently reject late results after its deadline or cleanup.
      let resolve, reject;
      const promise = new Promise((onResolve, onReject) => { resolve = onResolve; reject = onReject; });
      requests.push({ url, options,
        respond(status = 200, body = session) {
          resolve({ status, ok: status >= 200 && status < 300, json: async () => body });
        },
        malformedJson() {
          resolve({ status: 200, ok: true, json: async () => { throw new SyntaxError('Invalid JSON'); } });
        },
        reject,
      });
      return promise;
    },
  });
  assert.equal(exports.AuthEntrySession(), null, 'session revalidation adds no visual chrome');
  const cleanup = effect();
  return { requests, navigations, timers, window, document,
    cleanup() { cleanup?.(); },
    deadline() {
      assert.equal(timers.size, 1);
      const timer = [...timers.values()][0];
      assert.equal(timer.milliseconds, 10_000);
      timer.callback();
    },
  };
}

test('a restored entry page returns to the account using only its HttpOnly browser session', async () => {
  const f = fixture();
  assert.equal(f.requests.length, 1);
  const { url, options } = f.requests[0];
  assert.equal(url, '/api/auth/me');
  assert.equal(options.credentials, 'include');
  assert.equal(options.cache, 'no-store');
  assert.ok(options.signal instanceof AbortSignal);
  assert.equal(options.headers, undefined, 'do not construct token or cookie headers in JavaScript');
  assert.equal(options.body, undefined, 'do not send passwords or identity from browser storage');
  f.requests[0].respond();
  await flush();
  assert.deepEqual(f.navigations, ['/vault']);
  assert.equal(f.timers.size, 0);
  f.window.emit('focus');
  f.window.emit('pageshow', { persisted: true });
  assert.equal(f.requests.length, 1, 'do not reopen navigation after the account redirect starts');
  f.cleanup();
});

for (const [body, destination] of [
  [{ ...session, user: { ...session.user, emailVerified: false } }, '/verify-email?pending=1'],
  [{ ...session, user: { ...session.user, legalAccepted: false } }, '/legal-acceptance'],
  [{ ...session, user: { ...session.user, emailVerified: false, legalAccepted: false } }, '/verify-email?pending=1'],
]) {
  test(`restored sessions retain account gate ${destination}`, async () => {
    const f = fixture();
    f.requests[0].respond(200, body);
    await flush();
    assert.deepEqual(f.navigations, [destination]);
    f.cleanup();
  });
}

for (const event of ['focus', 'pageshow', 'visibilitychange']) {
  test(`${event} rechecks an old public page after sign-in elsewhere`, async () => {
    const f = fixture();
    f.requests[0].respond(401, {});
    await flush();
    assert.deepEqual(f.navigations, []);
    (event === 'visibilitychange' ? f.document : f.window).emit(event, { persisted: true });
    assert.equal(f.requests.length, 2, 'an initial anonymous result cannot permanently stop rechecks');
    f.requests[1].respond();
    await flush();
    assert.deepEqual(f.navigations, ['/vault']);
    f.cleanup();
  });
}

test('hidden tabs defer checks until visible and overlapping browser events share one request', async () => {
  const f = fixture({ visible: false });
  assert.equal(f.requests.length, 0);
  f.window.emit('focus');
  f.window.emit('pageshow');
  f.document.emit('visibilitychange');
  assert.equal(f.requests.length, 0);
  f.document.visibilityState = 'visible';
  f.document.emit('visibilitychange');
  f.window.emit('focus');
  f.window.emit('pageshow', { persisted: true });
  assert.equal(f.requests.length, 1);
  f.requests[0].respond(401, {});
  await flush();
  f.window.emit('focus');
  assert.equal(f.requests.length, 2, 'settled checks must release the single-flight gate');
  f.cleanup();
});

for (const status of [401, 403, 503]) {
  test(`${status} leaves the login form available without a spurious logout`, async () => {
    const f = fixture();
    f.requests[0].respond(status, {});
    await flush();
    assert.deepEqual(f.navigations, []);
    assert.equal(f.timers.size, 0);
    f.window.emit('focus');
    assert.equal(f.requests.length, 2);
    f.requests[1].respond();
    await flush();
    assert.deepEqual(f.navigations, ['/vault']);
    f.cleanup();
  });
}

test('network failures and invalid JSON do not destroy the session and a later check can recover', async () => {
  for (const fail of [request => request.reject(new Error('Network unavailable')),
    request => request.malformedJson()]) {
    const f = fixture();
    fail(f.requests[0]);
    await flush();
    assert.deepEqual(f.navigations, []);
    assert.equal(f.timers.size, 0);
    f.window.emit('focus');
    f.requests[1].respond();
    await flush();
    assert.deepEqual(f.navigations, ['/vault']);
    f.cleanup();
  }
});

test('malformed successful responses cannot bypass gates or send a visitor to a verification loop', async () => {
  for (const body of [null, 'not a session', [], {}, { user: null },
    { ...session, user: { ...session.user, id: '' } },
    { ...session, workspace: { id: '' } },
    { ...session, user: { id: session.user.id, legalAccepted: true } },
    { ...session, user: { id: session.user.id, emailVerified: true } },
    { ...session, user: { ...session.user, emailVerified: 'true' } },
    { ...session, user: { ...session.user, legalAccepted: 1 } }]) {
    const f = fixture();
    f.requests[0].respond(200, body);
    await flush();
    assert.deepEqual(f.navigations, []);
    f.cleanup();
  }
});

test('cleanup removes lifecycle hooks and aborts a check; even a late successful response stays inert', async () => {
  const f = fixture();
  const request = f.requests[0];
  assert.equal(f.window.count('focus'), 1);
  assert.equal(f.window.count('pageshow'), 1);
  assert.equal(f.document.count('visibilitychange'), 1);
  f.cleanup();
  assert.equal(request.options.signal.aborted, true);
  assert.equal(f.timers.size, 0);
  assert.equal(f.window.count('focus'), 0);
  assert.equal(f.window.count('pageshow'), 0);
  assert.equal(f.document.count('visibilitychange'), 0);
  request.respond();
  await flush();
  assert.deepEqual(f.navigations, []);
  f.window.emit('focus');
  assert.equal(f.requests.length, 1);
});

test('the deadline aborts a stuck check and old completions cannot navigate or clear the newer check', async () => {
  const f = fixture();
  const stale = f.requests[0];
  f.deadline();
  assert.equal(stale.options.signal.aborted, true);
  f.window.emit('focus');
  assert.equal(f.requests.length, 2);
  stale.respond();
  await flush();
  assert.deepEqual(f.navigations, [], 'a timed-out response cannot resurrect an old decision');
  f.window.emit('pageshow');
  assert.equal(f.requests.length, 2, 'the old completion cannot clear the current request gate');
  f.requests[1].respond();
  await flush();
  assert.deepEqual(f.navigations, ['/vault']);
  f.cleanup();
});

test('local demo installs no authentication request or browser lifecycle hooks', () => {
  const f = fixture({ demo: true });
  assert.equal(f.requests.length, 0);
  assert.equal(f.timers.size, 0);
  assert.equal(f.window.count('focus'), 0);
  assert.equal(f.window.count('pageshow'), 0);
  assert.equal(f.document.count('visibilitychange'), 0);
  f.cleanup();
});
