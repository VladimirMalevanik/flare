const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function load(relative, mocks, globals = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, relative), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require(name) {
    if (name in mocks) return mocks[name];
    throw Error(`Unexpected import ${name}`);
  }, ...globals });
  return exports;
}

const session = {
  user: { id: 'synthetic-user', name: 'Test', email: 'test@example.invalid',
    emailVerified: true, legalAccepted: true },
  workspace: { id: 'synthetic-workspace', name: 'Test workspace', role: 'owner' },
};

function harness({ cookie = '__Host-flare_session=test-token', status = 200,
  identity = session, failure, demo = false } = {}) {
  const requests = [];
  let headerReads = 0;
  const server = load('../src/lib/auth/server.ts', {
    'server-only': {},
    'next/headers': { async headers() {
      headerReads += 1;
      return new Headers(cookie ? { cookie } : {});
    } },
    'next/navigation': { redirect(url) {
      throw Object.assign(new Error('Redirect'), { destination: url });
    } },
    './session': { isLocalDemo: demo },
  }, {
    AbortSignal, process: { env: { API_INTERNAL_URL: 'http://api.example.invalid' } },
    async fetch(url, options) {
      requests.push({ url, options });
      if (failure) throw failure;
      return { status, ok: status === 200, json: async () => identity };
    },
  });
  return { server, requests, headerReads: () => headerReads };
}

const entryPages = [
  ['../src/app/page.tsx', 'landing'],
  ['../src/app/login/page.tsx', 'auth'],
  ['../src/app/register/page.tsx', 'auth'],
];

function page(relative, server) {
  return load(relative, {
    '@/lib/auth/server': server,
    '@/features/landing/landing-page': { default: 'landing' },
    '@/features/auth/auth-form': { AuthForm: 'auth' },
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }) },
  }).default;
}

for (const [relative, type] of entryPages) {
  test(`${relative}: guests see the existing page without an API dependency`, async () => {
    const h = harness({ cookie: 'flare-locale=es; ai_user_flare_site_analytics=anonymous' });
    const result = await page(relative, h.server)();
    assert.equal(result.type, type);
    if (relative.includes('register')) assert.equal(result.props.register, true);
    assert.equal(h.requests.length, 0);
  });

  for (const [identity, destination] of [
    [session, '/vault'],
    [{ ...session, user: { ...session.user, emailVerified: false } }, '/verify-email?pending=1'],
    [{ ...session, user: { ...session.user, legalAccepted: false } }, '/legal-acceptance'],
  ]) {
    test(`${relative}: existing account goes to ${destination}`, async () => {
      const h = harness({ identity });
      await assert.rejects(page(relative, h.server)(), (error) => error.destination === destination);
      assert.equal(h.requests.length, 1);
      const { url, options } = h.requests[0];
      assert.equal(url, 'http://api.example.invalid/auth/me');
      assert.equal(options.headers.Cookie, '__Host-flare_session=test-token');
      assert.equal(options.cache, 'no-store');
      assert.ok(options.signal instanceof AbortSignal);
    });
  }

  for (const status of [401, 403]) {
    test(`${relative}: ${status} never loops into a protected account`, async () => {
      const h = harness({ status });
      assert.equal((await page(relative, h.server)()).type, type);
    });
  }

  test(`${relative}: an unavailable API does not pretend the visitor is logged out`, async () => {
    const h = harness({ status: 503 });
    await assert.rejects(page(relative, h.server)(), /Authentication service is unavailable/);
    const offline = harness({ failure: new Error('Connection unavailable') });
    await assert.rejects(page(relative, offline.server)(), /Connection unavailable/);
  });
}

test('protected pages preserve authentication, membership and verification gates', async () => {
  const valid = harness();
  assert.equal(await valid.server.requireSession(), session);
  for (const [options, destination] of [
    [{ cookie: '' }, '/login'],
    [{ status: 401 }, '/login'],
    [{ status: 403 }, '/login?reason=membership'],
    [{ identity: { ...session, user: { ...session.user, emailVerified: false } } }, '/verify-email?pending=1'],
    [{ identity: { ...session, user: { ...session.user, legalAccepted: false } } }, '/legal-acceptance'],
  ]) {
    const h = harness(options);
    await assert.rejects(h.server.requireSession(), (error) => error.destination === destination);
  }
});

test('local demo remains usable without checking real authentication', async () => {
  const h = harness({ demo: true });
  assert.equal(await h.server.requireSession(), null);
  await h.server.redirectSignedInUser();
  assert.equal(h.requests.length, 0);
  assert.equal(h.headerReads(), 0);
});

test('only exact auth cookie names trigger a lookup and development cookies still work', async () => {
  for (const cookie of ['xflare_session=fake', 'acquisition=flare_session=fake']) {
    const h = harness({ cookie });
    await h.server.redirectSignedInUser();
    assert.equal(h.requests.length, 0);
  }
  const h = harness({ cookie: 'flare-locale=en; flare_session=dev-token' });
  await assert.rejects(h.server.redirectSignedInUser(), (error) => error.destination === '/vault');
  assert.equal(h.requests[0].options.headers.Cookie, 'flare-locale=en; flare_session=dev-token');
});
