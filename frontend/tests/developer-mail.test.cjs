const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
const settle = () => new Promise(resolve => setImmediate(resolve));
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function text(node) {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('');
  return node ? text(node.props?.children) : '';
}
function load(file, mocks, globals = {}) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/features/settings', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, AbortController, setTimeout, clearTimeout, ...globals, require(name) {
    if (name in mocks) return mocks[name];
    throw Error(name);
  } });
  return exports;
}
const clientModule = load('developer-mail-client.ts', { '@/lib/auth/session': { apiBaseUrl: '/api' } });
function harness({ capability = { allowed: true, ready: true, sender: 'sender@flare.example' }, send, locale = 'en' } = {}) {
  const state = [], deps = [], effects = [], calls = [];
  let cursor = 0;
  const client = { ...clientModule, mailCapability: async () => capability,
    async sendMail(recipients, draft) {
      calls.push({ recipients: [...recipients], draft: { ...draft } });
      return send ? send(recipients, draft) : recipients.map(recipient => ({ recipient, status: 'accepted' }));
    } };
  const exports = load('developer-mail.tsx', {
    'react/jsx-runtime': jsx,
    react: {
      useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial;
        return [state[i], value => state[i] = typeof value === 'function' ? value(state[i]) : value]; },
      useRef(initial) { const i = cursor++; if (!(i in state)) state[i] = { current: initial }; return state[i]; },
      useEffect(fn, values) { const i = cursor++; if (!deps[i] || values.some((value, index) => value !== deps[i][index])) {
        deps[i] = values; effects.push(fn);
      } },
    },
    '@/components/auth-session': { useSession: () => null },
    '@/components/dialog': { Dialog: 'dialog' }, '@/components/icons': { Icon: 'icon' },
    '@/i18n/provider': { useI18n: () => ({ locale }) }, './developer-mail-client': client, './developer-mail.css': {},
  });
  const app = {
    calls, render() { cursor = 0; return exports.MailComposer({ accountId: 'account-1' }); },
    async ready() { app.render(); for (const effect of effects.splice(0)) effect(); await settle(); },
    button(label) { return nodes(app.render()).find(node => node.type === 'button' && text(node) === label); },
    click(label) { const button = app.button(label); assert.ok(button, label); button.props.onClick(); },
    field(id, value) { nodes(app.render()).find(node => node.props?.id === id).props.onChange({ target: { value } }); },
    submit() { return nodes(app.render()).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); },
    open() { app.click(locale === 'es' ? 'Redactar correo' : 'Compose email'); },
    fill() { app.field('mail-recipients', 'one@example.invalid; two@example.invalid'); app.field('mail-subject', 'Hello'); app.field('mail-body', 'Manual message.'); },
  };
  return app;
}

test('paste accepts ordinary delimiters, deduplicates, and rejects injected/invalid/oversized lists', () => {
  assert.equal(JSON.stringify(clientModule.parseRecipients('one@example.invalid; TWO@example.invalid\nONE@example.invalid, three@example.invalid')), JSON.stringify(['ONE@example.invalid', 'TWO@example.invalid', 'three@example.invalid']));
  for (const value of ['', 'Name <x@example.invalid>', 'a..b@example.invalid', 'x@y', 'x@example.invalid\r\nBcc: y@example.invalid',
    Array.from({ length: 21 }, (_, i) => `user${i}@example.invalid`).join(',')]) assert.throws(() => clientModule.parseRecipients(value));
});

test('normal users and capability errors never render the developer button', async () => {
  const app = harness({ capability: { allowed: false } });
  assert.equal(app.render(), null); await app.ready(); assert.equal(app.render(), null);
});

test('unconfigured mail preserves a draft, but cannot submit', async () => {
  const app = harness({ capability: { allowed: true, ready: false } }); await app.ready(); app.open(); app.fill();
  assert.ok(app.button('Send email').props.disabled); await app.submit(); assert.equal(app.calls.length, 0);
  nodes(app.render()).find(node => node.type === 'dialog').props.onClose();
  app.open(); assert.equal(nodes(app.render()).find(node => node.props?.id === 'mail-body').props.value, 'Manual message.');
});

test('pending submission is locked synchronously and dismissal cannot lose its result', async () => {
  let resolve;
  const app = harness({ send: recipients => new Promise(done => { resolve = () => done(recipients.map(recipient => ({ recipient, status: 'accepted' }))); }) });
  await app.ready(); app.open(); app.fill();
  const submission = app.submit(); app.submit();
  assert.equal(app.calls.length, 1);
  assert.ok(app.button('Sending…').props.disabled);
  nodes(app.render()).find(node => node.type === 'dialog').props.onClose();
  assert.ok(nodes(app.render()).some(node => node.type === 'dialog'));
  resolve(); await submission;
  assert.match(text(app.render()), /Accepted by mail provider/);
  assert.equal(app.button('Send email'), undefined);
  await app.submit(); assert.equal(app.calls.length, 1);
});

test('validation errors retain the form and never call the send endpoint', async () => {
  const app = harness(); await app.ready(); app.open();
  await app.submit(); assert.match(text(app.render()), /Enter 1–20/);
  app.field('mail-recipients', 'one@example.invalid'); app.field('mail-subject', 'bad\nsubject');
  await app.submit(); assert.match(text(app.render()), /single-line subject/);
  app.field('mail-subject', 'Hello'); await app.submit(); assert.match(text(app.render()), /Enter a message/);
  assert.equal(app.calls.length, 0);
});

test('deliberate partial retry sends only explicitly rejected addresses', async () => {
  let attempt = 0;
  const app = harness({ send: recipients => recipients.map((recipient, i) => ({ recipient, status: attempt++ === 0 && i === 0 ? 'accepted' : 'failed' })) });
  await app.ready(); app.open(); app.fill(); await app.submit();
  assert.ok(app.button('Retry failed addresses'));
  await app.submit();
  assert.deepEqual(app.calls[1].recipients, ['two@example.invalid']);
  assert.equal(nodes(app.render()).find(node => node.props?.id === 'mail-body').props.value, 'Manual message.');
});

test('unknown outcomes and lost responses keep the draft and block automatic or manual retry of this send', async () => {
  for (const send of [recipients => recipients.map(recipient => ({ recipient, status: 'unknown' })), () => { throw new clientModule.MailRequestError(true); }]) {
    const app = harness({ send }); await app.ready(); app.open(); app.fill(); await app.submit();
    assert.match(text(app.render()), /may already have been sent/);
    assert.equal(app.button('Send email'), undefined); assert.equal(app.button('Retry failed addresses'), undefined);
    await app.submit(); assert.equal(app.calls.length, 1);
    assert.equal(nodes(app.render()).find(node => node.props?.id === 'mail-subject').props.value, 'Hello');
  }
});

test('explicit request rejection keeps an editable draft and Spanish composer copy is complete', async () => {
  const app = harness({ send: () => { throw new clientModule.MailRequestError(false); }, locale: 'es' });
  await app.ready(); app.open(); app.fill(); await app.submit();
  assert.match(text(app.render()), /solicitud fue rechazada/); assert.ok(app.button('Enviar correo'));
  assert.equal(nodes(app.render()).find(node => node.props?.id === 'mail-body').props.readOnly, false);
});

test('HTTP client sends authenticated plain text and treats network/malformed response as unknown', async () => {
  let captured;
  const mailClient = load('developer-mail-client.ts', { '@/lib/auth/session': { apiBaseUrl: '/api' } }, {
    fetch: async (url, options) => { captured = { url, options }; return { ok: true, json: async () => [{ recipient: 'one@example.invalid', status: 'accepted' }] }; },
  });
  await mailClient.sendMail(['one@example.invalid'], { recipients: 'unused', subject: 'Hello', body: 'Text\nbody' });
  assert.equal(captured.url, '/api/ops/mail/send'); assert.equal(captured.options.credentials, 'include');
  assert.deepEqual(JSON.parse(captured.options.body), { recipients: ['one@example.invalid'], subject: 'Hello', body: 'Text\nbody' });
  for (const fetch of [async () => { throw Error('private'); }, async () => ({ ok: true, json: async () => [] })]) {
    const broken = load('developer-mail-client.ts', { '@/lib/auth/session': { apiBaseUrl: '/api' } }, { fetch });
    await assert.rejects(broken.sendMail(['one@example.invalid'], { subject: 'Hello', body: 'Body' }), error => error.uncertain === true && !error.message.includes('private'));
  }
});
