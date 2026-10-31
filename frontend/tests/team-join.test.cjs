const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = path.resolve(__dirname, '../src');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const flush = async () => { for (let i = 0; i < 35; i++) await Promise.resolve(); };
const text = n => typeof n === 'string' ? n : Array.isArray(n) ? n.map(text).join(' ') : n && typeof n === 'object' ? text(n.props?.children) : '';
const nodes = n => !n || typeof n !== 'object' ? [] : Array.isArray(n) ? n.flatMap(nodes) : [n, ...nodes(n.props?.children)];
const session = { user: { id: 'member', email: 'member@example.invalid', name: 'Member', emailVerified: true, legalAccepted: true }, workspace: { id: 'personal', name: 'Personal', role: 'owner' } };
const response = value => ({ ok: true, status: 200, json: async () => value });

function screen({ fetchImpl = async () => response(session), teamImpl, joinError, locale = 'en' } = {}) {
  const state = [], effects = [], setups = [], cleanup = [], timers = new Map(), requests = [], navigations = [], writes = [];
  const storage = new Map(); let cursor = 0, timerId = 0, disposed = false;
  class TeamError extends Error { constructor(message, status, code) { super(message); this.status = status; this.code = code; } }
  const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
  const react = { useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial; return [state[i], value => { writes.push({ disposed }); state[i] = typeof value === 'function' ? value(state[i]) : value; }]; }, useEffect(fn) { effects.push(fn); } };
  const mocks = {
    react, 'react/jsx-runtime': jsx, 'next/link': { default: 'a' },
    '@/components/brand-mark': { BrandMark: 'brand' }, '@/i18n/provider': { useI18n: () => ({ locale }) },
    '@/lib/auth/session': { apiBaseUrl: '/api', authRequest: async (...args) => { requests.push({ auth: args }); } },
    '@/lib/team-context': { switchProject: (...args) => navigations.push(args) },
    './api': { TeamError, teamRequest: async (url, body) => {
      requests.push({ url, body });
      if (teamImpl) { const result = teamImpl(url, body); if (result !== undefined) return result; }
      if (url === '/projects') return { capability: { requiresVerification: false } };
      if (url === '/invitations/preview') return { projectName: 'Shared research', invitedBy: 'Owner', role: 'editor', expiresAt: '2099-01-01T00:00:00Z' };
      if (url === '/invitations/accept') { if (joinError) throw new TeamError(joinError.message, joinError.status, joinError.code); return { workspaceId: 'shared-project' }; }
      return {};
    } },
  };
  const cache = new Map();
  function load(relative) {
    if (cache.has(relative)) return cache.get(relative);
    const exports = {}; cache.set(relative, exports);
    const compiled = ts.transpileModule(fs.readFileSync(path.join(source, relative), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
    vm.runInNewContext(compiled, { exports, Error, Date, AbortController, AbortSignal, Promise, console,
      fetch: (...args) => { requests.push({ fetch: args }); return fetchImpl(...args); },
      setTimeout(fn, ms) { timers.set(++timerId, { fn, ms }); return timerId; }, clearTimeout(id) { timers.delete(id); },
      sessionStorage: { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
      window: { location: { hash: '#' + 'a'.repeat(43), replace: url => navigations.push(url), reload: () => navigations.push('reload') }, history: { replaceState() {} } },
      require(name) { if (name in mocks) return mocks[name]; if (name === '@/lib/data/import-request') return load('lib/data/import-request.ts'); throw Error('Unexpected import ' + name); },
    }); return exports;
  }
  const { JoinPage } = load('features/team/join-page.tsx');
  return { timers, requests, navigations, writes, storage, render() { cursor = 0; return JoinPage(); },
    async start() { this.render(); for (const fn of effects.splice(0)) { setups.push(fn); cleanup.push(fn()); } await flush(); },
    replay() { cleanup.pop()?.(); cleanup.push(setups[0]()); },
    dispose() { disposed = true; for (const fn of cleanup) fn?.(); },
    expire() { const timer = [...timers.values()].find(v => v.ms === 12000); assert.ok(timer, 'account loading must have a deadline'); timer.fn(); },
  };
}

test('invitation previews the email-bound project but joins only after explicit consent', async () => {
  const h = screen(); await h.start(); let tree = h.render();
  assert.match(text(tree), /Shared research/);
  assert.equal(h.requests.filter(r => r.url === '/invitations/accept').length, 0);
  assert.equal(nodes(tree).find(n => n.type === 'button' && text(n) === 'Join project').props.disabled, true);
  nodes(tree).find(n => n.type === 'input' && n.props.type === 'checkbox').props.onChange({ target: { checked: true } });
  tree = h.render(); await nodes(tree).find(n => n.type === 'button' && text(n) === 'Join project').props.onClick(); await flush();
  assert.equal(h.requests.filter(r => r.url === '/invitations/accept').length, 1);
  assert.deepEqual(h.navigations, [['shared-project', '/team']]);
  assert.equal(h.storage.has('flare-team-invitation'), false); h.dispose();
});

for (const phase of ['transport', 'json']) test(`stalled account ${phase} stops with retry and ignores late completion`, async () => {
  const late = deferred(); const h = screen({ fetchImpl: () => phase === 'transport' ? late.promise : Promise.resolve({ ok: true, status: 200, json: () => late.promise }) });
  await h.start(); assert.match(text(h.render()), /Checking your account/); h.expire(); await flush();
  assert.doesNotMatch(text(h.render()), /Checking your account/); assert.ok(nodes(h.render()).some(n => n.props?.role === 'alert'));
  assert.ok(nodes(h.render()).some(n => n.type === 'button' && text(n) === 'Check again'));
  const count = h.writes.length; late.resolve(phase === 'transport' ? response(session) : session); await flush();
  assert.equal(h.writes.length, count); assert.equal(h.requests.some(r => r.url === '/projects'), false); assert.equal(h.timers.size, 0); h.dispose();
});

test('cleanup fences ignored-abort JSON responses and does not start Team queries', async () => {
  const late = deferred(); const h = screen({ fetchImpl: async () => ({ ok: true, status: 200, json: () => late.promise }) });
  await h.start(); h.dispose(); late.resolve(session); await flush();
  assert.equal(h.requests.some(r => r.url === '/projects'), false);
  assert.equal(h.writes.some(w => w.disposed), false); assert.equal(h.timers.size, 0);
});

for (const phase of ['/projects', '/invitations/preview']) test(`cleanup ignores a late ${phase} response`, async () => {
  const late = deferred(); const h = screen({ teamImpl: url => url === phase ? late.promise : undefined });
  await h.start(); h.dispose(); late.resolve(phase === '/projects' ? { capability: { requiresVerification: false } } : { projectName: 'Late project' }); await flush();
  assert.equal(h.writes.some(w => w.disposed), false);
  if (phase === '/projects') assert.equal(h.requests.some(r => r.url === '/invitations/preview'), false);
});

test('effect replay uses the latest account and ignores an old response even if abort is ignored', async () => {
  const late = deferred(); let calls = 0;
  const h = screen({ fetchImpl: async () => ++calls === 1 ? { ok: true, status: 200, json: () => late.promise } : response(session) });
  await h.start(); h.replay(); await flush();
  assert.match(text(h.render()), /member@example.invalid/);
  const writes = h.writes.length;
  late.resolve({ ...session, user: { ...session.user, email: 'stale@example.invalid' } }); await flush();
  assert.equal(h.writes.length, writes); assert.doesNotMatch(text(h.render()), /stale@example.invalid/);
  assert.equal(h.requests.filter(r => r.url === '/projects').length, 1); assert.equal(h.timers.size, 0); h.dispose();
});

test('a signed-out account can sign in without querying or accepting a private invitation', async () => {
  const h = screen({ fetchImpl: async () => ({ ok: false, status: 401 }) }); await h.start(); const tree = h.render();
  assert.ok(nodes(tree).some(n => n.type === 'a' && n.props.href === '/login'));
  assert.ok(nodes(tree).some(n => n.type === 'a' && n.props.href === '/register'));
  assert.equal(h.requests.some(r => r.url), false); assert.equal(h.timers.size, 0); h.dispose();
});

for (const code of ['team_subscription_required', 'team_permission']) test(`${code} stays a real admission error instead of asking for another verification email`, async () => {
  const message = code === 'team_subscription_required' ? 'An active Team subscription is required.' : 'A verified account with the required project role is needed.';
  const h = screen({ joinError: { status: 403, code, message } }); await h.start();
  let tree = h.render(); nodes(tree).find(n => n.type === 'input' && n.props.type === 'checkbox').props.onChange({ target: { checked: true } });
  tree = h.render(); await nodes(tree).find(n => n.type === 'button' && text(n) === 'Join project').props.onClick(); await flush(); tree = h.render();
  assert.ok(text(tree).includes(message)); assert.doesNotMatch(text(tree), /Verify this email/);
  assert.equal(h.requests.some(r => r.auth || r.url === '/verify-email'), false); assert.equal(h.navigations.length, 0); h.dispose();
});

test('a real verification rejection requests auth re-verification rather than a protected Team endpoint', async () => {
  const h = screen({ joinError: { status: 403, code: 'email_verification_required', message: 'Verify your email to continue.' } }); await h.start();
  let tree = h.render(); nodes(tree).find(n => n.type === 'input' && n.props.type === 'checkbox').props.onChange({ target: { checked: true } });
  tree = h.render(); await nodes(tree).find(n => n.type === 'button' && text(n) === 'Join project').props.onClick(); await flush();
  tree = h.render(); await nodes(tree).find(n => n.type === 'button' && text(n) === 'Verify this email').props.onClick(); await flush();
  assert.equal(h.requests.some(r => r.auth?.[0] === 'resend-verification'), true); assert.equal(h.requests.some(r => r.url === '/verify-email'), false); h.dispose();
});

test('renewed legal consent redirects to terms rather than mislabeling the account as unverified', async () => {
  const h = screen({ locale: 'es', joinError: { status: 403, code: 'legal_acceptance_required', message: 'Review the current terms.' } }); await h.start();
  let tree = h.render(); nodes(tree).find(n => n.type === 'input' && n.props.type === 'checkbox').props.onChange({ target: { checked: true } });
  tree = h.render(); await nodes(tree).find(n => n.type === 'button' && text(n) === 'Unirse al proyecto').props.onClick(); await flush(); tree = h.render();
  assert.ok(nodes(tree).some(n => n.type === 'a' && n.props.href === '/legal-acceptance'));
  assert.doesNotMatch(text(tree), /Verificar este correo/); h.dispose();
});
