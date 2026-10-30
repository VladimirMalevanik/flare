const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
const flush = () => new Promise(resolve => setImmediate(resolve));
function nodes(node) { if (!node || typeof node !== 'object') return []; if (Array.isArray(node)) return node.flatMap(nodes); return [node, ...nodes(node.props?.children)]; }
function text(node) { if (typeof node === 'string') return node; if (Array.isArray(node)) return node.map(text).join(''); return node && typeof node === 'object' ? text(node.props?.children) : ''; }
function load(relative, mocks, globals = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, relative), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {}; vm.runInNewContext(code, { exports, AbortController, URL, setTimeout, clearTimeout, ...globals, require(name) { if (name in mocks) return mocks[name]; if (name === 'react/jsx-runtime') return jsx; if (name === '@/lib/team-context') return { projectHref: url => url };
    throw Error(`Unexpected import ${name}`); } }); return exports;
}
function harness(overrides = {}) {
  const values = [], refs = [], cleanups = [], calls = []; let cursor = 0, refCursor = 0, refreshes = 0;
  const provider = { async sourceResources(id, cursor) { calls.push(['resources', id, cursor]); return { resources: [{ id: 'L1', name: 'Support', kind: 'label' }], cursor: null, scopeRevision: 2 }; },
    async selectSourceResources(...args) { calls.push(['select', ...args]); }, async sourceConnectionAction(...args) { calls.push(['action', ...args]); }, async connectSource(...args) { calls.push(['connect', ...args]); return { connected: true }; }, ...overrides };
  const componentModule = load('../src/features/sources/connected-source.tsx', {
    react: { useState(initial) { const index = cursor++; if (!(index in values)) values[index] = initial; return [values[index], update => { values[index] = typeof update === 'function' ? update(values[index]) : update; }]; }, useRef(initial) { const index = refCursor++; if (!(index in refs)) refs[index] = { current: initial }; return refs[index]; }, useEffect(fn) { if (cleanups.length === 0) cleanups.push(fn()); } },
    '@/components/dialog': { Dialog: 'dialog' }, '@/components/icons': { Icon: 'icon' }, '@/i18n/provider': require('./i18n-utils.cjs').i18nMock(), '@/lib/data': { dataProvider: provider },
  }, { window: { location: { assign(url) { calls.push(['redirect', url]); } } } });
  const connection = { id: 'c1', provider: 'gmail', owner: true, canDisconnect: true, accountLabel: 'test@example.invalid', scopeRevision: 2, status: 'connected', enabled: false, resources: [], lastSyncAt: null, nextSyncAt: null, errorCode: null, lastResult: null, job: null };
  const props = { provider: 'gmail', connection, available: true, syncAvailable: true, refresh: async () => { refreshes++; } };
  return { props, calls, componentModule, render() { cursor = 0; refCursor = 0; return nodes(componentModule.ConnectedSource(props)); }, button(name) { return this.render().find(node => node.type === 'button' && text(node) === name); }, close() { cleanups.forEach(fn => fn?.()); }, refreshes: () => refreshes };
}

test('selected private context requires explicit sharing; only chosen IDs are sent', async () => {
  const app = harness(); app.button('Choose context').props.onClick(); await flush();
  let checkboxes = app.render().filter(node => node.type === 'input' && node.props.type === 'checkbox');
  assert.equal(checkboxes.length, 2); assert.equal(checkboxes[1].props.checked, false);
  checkboxes[0].props.onChange({ target: { checked: true } });
  assert.equal(app.button('Save selection').props.disabled, true);
  checkboxes = app.render().filter(node => node.type === 'input'); checkboxes[1].props.onChange({ target: { checked: true } });
  assert.equal(app.button('Save selection').props.disabled, false);
  app.button('Save selection').props.onClick(); await flush();
  const call = app.calls.find(call => call[0] === 'select');
  assert.deepEqual(JSON.parse(JSON.stringify(call.slice(1,5))), ['c1',2,['L1'],true]);
  assert.equal(app.refreshes(), 1); assert.ok(!app.render().some(node => node.type === 'dialog'));
});

test('teammate connection and disabled capability cannot browse or connect', () => {
  const app = harness(); app.props.connection.owner = false;
  assert.equal(app.button('Choose context'), undefined); assert.equal(app.button('Sync now'), undefined);
  assert.ok(app.button('Disconnect')); assert.equal(app.calls.length, 0);
  app.props.connection = undefined; app.props.available = false; assert.equal(app.button('Connect').props.disabled, true);
});

test('failed cancellation never shows a cancelled run; recovery stays available', async () => {
  const app = harness({ async sourceConnectionAction() { throw { code: 'import_request_timeout' }; } });
  app.props.connection.enabled = true; app.props.connection.status = 'syncing'; app.props.connection.job = { id: 'j1', status: 'processing', added: 2, updated: 0, unchanged: 0, skipped: 0, conflicts: 0, more: true };
  app.button('Cancel sync').props.onClick(); await flush();
  assert.ok(app.render().some(node => node.props?.role === 'alert' && text(node).includes('Check status')));
  assert.ok(app.button('Cancel sync')); assert.equal(app.props.connection.job.status, 'processing'); assert.equal(app.refreshes(), 0);
});

test('double connect submits once; closing picker prevents late resource state', async () => {
  let finish;
  const app = harness({ connectSource: () => new Promise(resolve => { finish = resolve; }) });
  app.props.connection = undefined; const button = app.button('Connect'); button.props.onClick(); button.props.onClick();
  finish({ connected: true }); await flush(); assert.equal(app.refreshes(), 1);
  let complete;
  const picker = harness({ sourceResources: () => new Promise(resolve => { complete = resolve; }) });
  picker.button('Choose context').props.onClick(); picker.render().find(node => node.type === 'dialog').props.onClose();
  complete({ resources: [{id:'late',name:'Late',kind:'label'}], cursor:null, scopeRevision:2 }); await flush();
  assert.ok(!picker.render().some(node => node.type === 'dialog'));
});

test('connection decoder exposes only known public fields and rejects unsafe capabilities', () => {
  const request = load('../src/lib/data/import-request.ts', {});
  const projectContext = load('../src/lib/team-context.ts', {});
  const componentModule = load('../src/lib/data/api-provider.ts', { './import-request': request, '../team-context': projectContext });
  const conn = { id:'c', provider:'gmail', owner:true, canDisconnect:true, accountLabel:'Test', scopeRevision:1, status:'ready', enabled:true, resources:[], lastSyncAt:null, nextSyncAt:null, errorCode:null, lastResult:null, job:null, credentialBlob:'PRIVATE' };
  const dto = componentModule.mapSourceConnections({ providers:[{provider:'gmail',available:true,syncAvailable:false}],connections:[conn] });
  assert.ok(!JSON.stringify(dto).includes('PRIVATE'));
  assert.equal(dto.connections[0].canReconnect, false);
  assert.equal(componentModule.mapSourceConnections({providers:[],connections:[{...conn,canReconnect:true}]}).connections[0].canReconnect, true);
  assert.throws(() => componentModule.mapSourceConnections({providers:[],connections:[{...conn,canReconnect:'true'}]}));
  assert.throws(() => componentModule.mapSourceConnections({providers:[{provider:'unknown',available:true,syncAvailable:true}],connections:[]}));
  assert.throws(() => componentModule.mapSourceConnections({providers:[],connections:[{...conn,status:'pretend-success'}]}));
});


test('source badge follows live connection and retry status instead of the catalog', () => {
  const { sourceConnectionBadge } = load('../src/features/sources/sources-page.tsx', {
    react: {}, 'next/link': {}, './connected-source': {}, './zip-import': {}, '@/i18n/provider': {}, '@/lib/data': {}, '@/components/icons': {}, '@/components/select': {}, '@/components/workspace-context': {},
  });
  const source = { status: 'disconnected' };
  assert.equal(sourceConnectionBadge(source, {status:'ready',job:null}).label, 'Connected');
  assert.equal(sourceConnectionBadge(source, {status:'error',job:{status:'retry_wait'}}).label, 'Waiting for source');
  assert.equal(sourceConnectionBadge(source, {status:'disabled',job:null}).label, 'Not connected');
});


test('cancelled run displays its saved partial counts and preserves the last completed timestamp', () => {
  const app = harness(); app.props.connection.enabled = true; app.props.connection.status = 'ready';
  app.props.connection.lastResult = {added: 10, updated: 0, unchanged: 0, skipped: 0, conflicts: 0, more: false};
  app.props.connection.job = {id: 'j', status: 'cancelled', added: 3, updated: 0, unchanged: 0, skipped: 0, conflicts: 0, more: true};
  const tree = app.render(); assert.ok(tree.some(node => text(node).includes('Added: 3')));
  assert.ok(tree.some(node => text(node).includes('Sync cancelled. Context already saved in Vault is kept.')));
  assert.equal(app.button('Cancel sync'), undefined);
});


test('reconnect uses an explicit server capability and does not expose teammate controls', async () => {
  const app = harness(); Object.assign(app.props.connection, {owner: false, status: 'disabled'});
  assert.equal(app.button('Connect').props.disabled, true);
  app.props.connection.canReconnect = true;
  assert.equal(app.button('Connect your account').props.disabled, false);
  assert.equal(app.button('Choose context'), undefined);
  assert.equal(app.button('Sync now'), undefined);
  app.button('Connect your account').props.onClick(); await flush();
  assert.equal(app.calls.filter(call => call[0] === 'connect').length, 1);
  app.props.connection.status = 'pending';
  assert.equal(app.button('Connect').props.disabled, true);
  assert.ok(app.button('Cancel connection'));
});

test('a pending setup can be cancelled; unavailable provider still cannot reconnect', async () => {
  const app = harness(); Object.assign(app.props.connection, {status: 'pending'});
  app.button('Cancel connection').props.onClick(); await flush();
  assert.deepEqual(app.calls.find(call => call[0] === 'action').slice(1,3), ['c1', 'disconnect']);
  Object.assign(app.props.connection, {owner: false, canReconnect: true, status: 'disabled'});
  app.props.available = false;
  assert.equal(app.button('Connect your account').props.disabled, true);
});
