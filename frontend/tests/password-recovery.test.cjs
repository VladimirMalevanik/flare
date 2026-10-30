const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock, loadPure } = require('./i18n-utils.cjs');
const TOKEN = 'r'.repeat(43);
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
const nodes = n => !n || typeof n !== 'object' ? [] : Array.isArray(n) ? n.flatMap(nodes) : [n, ...nodes(n.props?.children)];
const text = n => typeof n === 'string' ? n : Array.isArray(n) ? n.map(text).join(' ') : n && typeof n === 'object' ? text(n.props?.children) : '';
const flush = () => new Promise(resolve => setImmediate(resolve));
const source = file => ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src', file), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
}).outputText;
class AuthRequestError extends Error { constructor(code, status = 0) { super(code); this.code = code; this.status = status; } }

function setup({ reset = false, fragment = '#token=' + TOKEN, locale = 'en', request = async () => ({ ok: true }) } = {}) {
  const slots = [], pending = [], calls = [], replacements = [], listeners = new Map();
  let reloads = 0;
  let cursor = 0, writes = 0;
  const location = { hash: fragment, pathname: '/reset-password', reload() { reloads++; } };
  const history = { replaceState(...args) { replacements.push(args); location.hash = ''; } };
  const forbiddenStorage = { getItem() { assert.fail('recovery token must stay out of persistent storage'); }, setItem() { assert.fail('recovery token must stay out of persistent storage'); } };
  const react = {
    useState(initial) { const i = cursor++; slots[i] ??= { value: initial };
      return [slots[i].value, value => { writes++; slots[i].value = typeof value === 'function' ? value(slots[i].value) : value; }]; },
    useRef(current) { return slots[cursor++] ??= { current }; },
    useEffect(fn, deps) { const i = cursor++; const before = slots[i];
      if (!before || deps.some((v, j) => v !== before.deps[j])) {
        slots[i] = { deps, fn };
        pending.push(() => { before?.cleanup?.(); slots[i].cleanup = fn(); });
      }
    },
  };
  const tokenModule = {};
  vm.runInNewContext(source('features/auth/reset-token.ts'), { exports: tokenModule, URLSearchParams });
  const exports = {};
  vm.runInNewContext(source('features/auth/password-recovery.tsx'), {
    exports, window: { location, history, localStorage: forbiddenStorage, sessionStorage: forbiddenStorage,
      addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: (name, fn) => { if (listeners.get(name) === fn) listeners.delete(name); } },
    FormData: class { constructor(values) { this.values = values; } get(key) { return this.values[key] ?? null; } },
    require(name) {
      if (name === 'react/jsx-runtime') return jsx;
      if (name === '@/components/password-field') return { PasswordField: 'password-field' };
      if (name === 'react') return react;
      if (name === 'next/link') return { default: 'a' };
      if (name === '@/i18n/provider') return i18nMock(locale);
      if (name === '@/components/brand-mark') return { BrandMark: 'brand' };
      if (name === '@/components/language-selector') return { LanguageSelector: 'language' };
      if (name === '@/lib/support') return { supportMailto: () => 'mailto:support@flare.test' };
      if (name === './reset-token') return tokenModule;
      if (name === '@/lib/auth/session') return { AuthRequestError, authRequest: async (...args) => { calls.push(args); return request(...args); } };
      throw Error(name);
    },
  });
  return {
    render() { cursor = 0; return exports.PasswordRecovery({ reset }); },
    async effects({ strict = false } = {}) {
      for (const commit of pending.splice(0)) commit();
      if (strict) {
        for (const slot of slots) if (slot?.fn) { slot.cleanup?.(); slot.cleanup = slot.fn(); }
      }
      await flush();
    },
    submit(tree, values) { return nodes(tree).find(n => n.type === 'form').props.onSubmit({ preventDefault() {}, currentTarget: values }); },
    dispose() { for (const slot of slots) slot?.cleanup?.(); },
    calls, replacements, writes: () => writes, reloads: () => reloads,
    changeHash(hash) { location.hash = hash; listeners.get('hashchange')?.(); },
  };
}

test('fragment is consumed once and removed before displaying the form, including Strict Mode', async () => {
  const h = setup({ reset: true });
  assert.match(text(h.render()), /Checking reset link/);
  assert.equal(h.replacements.length, 0); assert.equal(h.calls.length, 0);
  await h.effects({ strict: true });
  const tree = h.render();
  assert.equal(h.replacements.length, 1); assert.equal(h.replacements[0][2], '/reset-password');
  assert.ok(nodes(tree).some(n => n.type === 'form'));
  assert.ok(!JSON.stringify(tree).includes(TOKEN));
  await h.submit(tree, { password: 'new-password-here', confirmPassword: 'new-password-here' });
  assert.equal(h.calls[0][0], 'reset-password'); assert.equal(h.calls[0][1].token, TOKEN);
  await h.effects({ strict: true }); assert.match(text(h.render()), /Password updated/);
  h.dispose();
});

for (const fragment of ['', '#token=bad', '#token=' + TOKEN + '&token=' + TOKEN, '#token=' + ' '.repeat(43)]) test('missing, malformed and duplicate links show a recovery action: ' + fragment.slice(0, 15), async () => {
  const h = setup({ reset: true, fragment }); h.render(); await h.effects(); const tree = h.render();
  assert.match(text(tree), /invalid, expired or already used/);
  assert.ok(!nodes(tree).some(n => n.type === 'form'));
  assert.ok(nodes(tree).some(n => n.type === 'a' && n.props.href === '/forgot-password'));
  assert.equal(h.calls.length, 0); h.dispose();
});

test('blocked URL cleanup fails closed instead of exposing the token or breaking the page', () => {
  const exports = {};
  vm.runInNewContext(source('features/auth/reset-token.ts'), { exports, URLSearchParams });
  assert.equal(exports.consumeResetToken({ hash: '#token=' + TOKEN, pathname: '/reset-password' }, { replaceState() { throw Error('blocked'); } }), '');
});

test('another email fragment opens a fresh document and removes its listener on unmount', async () => {
  const h = setup({ reset: true }); h.render(); await h.effects({ strict: true });
  assert.equal(h.reloads(), 0);
  h.changeHash('#token=' + 's'.repeat(43)); assert.equal(h.reloads(), 1);
  assert.equal(h.calls.length, 0);
  h.dispose(); h.changeHash('#token=' + TOKEN); assert.equal(h.reloads(), 1);
});

test('mismatch and short passwords are rejected without a request', async () => {
  const h = setup({ reset: true }); h.render(); await h.effects();
  await h.submit(h.render(), { password: 'new-password', confirmPassword: 'different' });
  assert.match(text(h.render()), /do not match/);
  await h.submit(h.render(), { password: 'short', confirmPassword: 'short' });
  assert.match(text(h.render()), /8 to 128/); assert.equal(h.calls.length, 0); h.dispose();
});

for (const locale of ['en', 'es']) test('successful reset requires ordinary sign-in and never navigates automatically (' + locale + ')', async () => {
  const h = setup({ reset: true, locale }); h.render(); await h.effects();
  await h.submit(h.render(), { password: 'new-password', confirmPassword: 'new-password' }); const tree = h.render();
  assert.match(text(tree), locale === 'en' ? /previous sessions have ended/ : /sesiones anteriores/);
  assert.ok(!nodes(tree).some(n => n.type === 'form'));
  assert.ok(nodes(tree).some(n => n.type === 'a' && n.props.href === '/login'));
  assert.equal(h.calls.length, 1); assert.equal(h.replacements.length, 1); h.dispose();
});

test('forgot request normalizes email and gives a conditional enumeration-safe notice', async () => {
  const h = setup(); let tree = h.render(); await h.effects();
  await h.submit(tree, { email: '  Person@Example.invalid  ' }); tree = h.render();
  assert.equal(h.calls[0][0], 'forgot-password'); assert.equal(h.calls[0][1].email, 'person@example.invalid');
  assert.match(text(tree), /If recovery is available/); assert.doesNotMatch(text(tree), /account exists|not found/i);
  assert.equal(h.replacements.length, 0); h.dispose();
});

test('a malformed email gives a field correction instead of a service error', async () => {
  const h = setup(); h.render(); await h.effects();
  for (const email of ['', 'person@localhost', 'person@@example.invalid', 'person @example.invalid']) {
    await h.submit(h.render(), { email });
    assert.match(text(h.render()), /valid email address/);
  }
  assert.equal(h.calls.length, 0); h.dispose();
});

test('pending submissions are fenced in the same event turn and disable editable fields', async () => {
  let finish;
  const h = setup({ request: () => new Promise(resolve => { finish = resolve; }) });
  const tree = h.render(); await h.effects();
  const first = h.submit(tree, { email: 'person@example.invalid' });
  await h.submit(tree, { email: 'person@example.invalid' });
  assert.equal(h.calls.length, 1);
  assert.ok(nodes(h.render()).filter(n => n.type === 'input' || n.type === 'button').every(n => n.props.disabled));
  finish({ ok: true }); await first; h.dispose();
});

test('a late response after navigation cannot update the removed form', async () => {
  let finish;
  const h = setup({ request: () => new Promise(resolve => { finish = resolve; }) });
  const tree = h.render(); await h.effects(); const result = h.submit(tree, { email: 'person@example.invalid' });
  h.dispose(); const writes = h.writes(); finish({ ok: true }); await result;
  assert.equal(h.writes(), writes);
});

for (const reset of [false, true]) test('an uncertain result offers the right next step without replay (' + reset + ')', async () => {
  const h = setup({ reset, request: async () => { throw new AuthRequestError('request_outcome_unknown'); } });
  h.render(); await h.effects();
  await h.submit(h.render(), reset ? { password: 'new-password', confirmPassword: 'new-password' } : { email: 'person@example.invalid' });
  const tree = h.render(); assert.ok(!nodes(tree).some(n => n.type === 'form'));
  assert.match(text(tree), reset ? /Try signing in with the new password/ : /Check your inbox before/);
  assert.equal(h.calls.length, 1); h.dispose();
});

test('a reused link is discarded, while a temporary busy error preserves the valid form', async () => {
  let code = 'password_recovery_busy';
  const h = setup({ reset: true, request: async () => { throw new AuthRequestError(code); } });
  h.render(); await h.effects(); const values = { password: 'new-password', confirmPassword: 'new-password' };
  await h.submit(h.render(), values);
  assert.match(text(h.render()), /wait a moment/); assert.ok(nodes(h.render()).some(n => n.type === 'form'));
  code = 'password_reset_invalid'; await h.submit(h.render(), values);
  assert.match(text(h.render()), /already used/); assert.ok(!nodes(h.render()).some(n => n.type === 'form')); h.dispose();
});

test('a server error after reset is treated as unconfirmed rather than inviting a blind retry', async () => {
  const h = setup({ reset: true, request: async () => { throw new AuthRequestError(undefined, 500); } });
  h.render(); await h.effects();
  await h.submit(h.render(), { password: 'new-password', confirmPassword: 'new-password' });
  assert.match(text(h.render()), /Try signing in with the new password/);
  assert.ok(!nodes(h.render()).some(n => n.type === 'form')); h.dispose();
});

test('existing analytics allowlist does not admit recovery URLs or their fragments', () => {
  const { safePage, safeTelemetryPage } = loadPure('../src/lib/telemetry/config.ts');
  for (const route of ['/forgot-password', '/reset-password']) {
    assert.equal(safePage(route), null);
    assert.equal(safeTelemetryPage('https://flare4u.tech' + route + '#token=' + TOKEN), null);
  }
});
