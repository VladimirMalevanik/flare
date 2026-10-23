const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const folder = path.join(__dirname, '../src/features/settings');
const compile = name => ts.transpileModule(fs.readFileSync(path.join(folder, name), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
function report(days = 7) {
  const end = Date.parse('2026-10-23T00:00:00Z');
  return {
    days, timezone: 'UTC', generatedAt: '2026-10-23T12:30:00Z', recordingStartedAt: '2026-10-21T09:00:00Z', totalOpens: 8,
    daily: Array.from({ length: days }, (_, i) => ({ date: new Date(end - (days - 1 - i) * 86400000).toISOString().slice(0, 10), opens: i < days - 3 ? null : [2, 0, 6][i - days + 3] })),
    topLinks: [{ id: 'link-1', label: 'Flare on X', opens: 6, archivedAt: null }, { id: 'link-2', label: 'Founder post', opens: 2, archivedAt: '2026-10-22T10:00:00Z' }],
  };
}
function client(fetch) {
  const exports = {};
  vm.runInNewContext(compile('campaign-links-client.ts'), { exports, fetch,
    require(name) {
      if (name === '@/lib/auth/session') return { apiBaseUrl: '/api' };
      if (name === '@/lib/team-context') return { projectApiUrl: url => `${url}${url.includes('?') ? '&' : '?'}workspace=team-selected` };
      throw Error(name);
    },
  }); return exports;
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const nodes = node => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
const text = node => typeof node === 'string' || typeof node === 'number' ? String(node) : Array.isArray(node) ? node.map(text).join(' ') : node ? text(node.props?.children) : '';
function harness(getActivity = async () => report(), locale = 'en') {
  const stores = new Map(), requests = []; let current, cursor;
  const exports = {};
  vm.runInNewContext(compile('campaign-activity.tsx'), { exports, AbortController, Intl, Date,
    require(name) {
      if (name === 'react/jsx-runtime') return { jsx: (type, props, key) => ({ type, props, key }), jsxs: (type, props, key) => ({ type, props, key }) };
      if (name === 'react') return {
        useId: () => 'test-chart-id',
        useState(initial) { const store = current, index = cursor++; if (!(index in store.state)) store.state[index] = initial;
          return [store.state[index], value => { store.updates++; store.state[index] = typeof value === 'function' ? value(store.state[index]) : value; }]; },
        useEffect(effect, deps) { const index = cursor++, store = current;
          if (!store.deps[index] || deps.some((value, i) => value !== store.deps[index][i])) {
            store.cleanup[index]?.(); store.deps[index] = deps; store.effects.push(() => { store.cleanup[index] = effect(); });
          }
        },
      };
      if (name === '@/components/select') return { Select: 'select' };
      if (name === '@/i18n/provider') return { useI18n: () => ({ locale }) };
      if (name === './campaign-links-client') return { getCampaignActivity: (...args) => { requests.push(args); return getActivity(...args); } };
      throw Error(name);
    },
  }); return { exports, requests,
    render(fn, props) { const id = fn.name; if (!stores.has(id)) stores.set(id, { state: [], deps: [], effects: [], cleanup: [], updates: 0 }); current = stores.get(id); cursor = 0; return fn(props); },
    async effects(fn) { for (const effect of stores.get(fn.name).effects.splice(0)) effect(); await flush(); },
    dispose(fn) { for (const cleanup of stores.get(fn.name).cleanup) cleanup?.(); },
    updates(fn) { return stores.get(fn.name).updates; },
  };
}
const link = { id: 'link-1', label: 'Flare on X', archivedAt: null, clickCount: 20 };
function panel(app, changes = {}) {
  return app.render(app.exports.CampaignActivityPanel, { links: [link], loading: false, failed: false, onRetryLinks() {}, onManage() {}, ...changes });
}
function resultNode(node) { return nodes(node).find(node => node.type?.name === 'CampaignActivityResult'); }
for (const days of [7, 30, 90]) test(`activity client preserves workspace, filter, credentials, abort and ${days}-day range`, async () => {
  const calls = [], signal = new AbortController().signal;
  const api = client(async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({ ...report(days), totalOpens: 6, daily: report(days).daily.map((d, i) => ({ ...d, opens: d.opens === null ? null : i === days - 1 ? 6 : 0 })), topLinks: [report(days).topLinks[0]] }) }; });
  const data = await api.getCampaignActivity(days, 'link-1', signal); assert.equal(data.totalOpens, 6);
  assert.equal(calls[0].url, `/api/campaign-links/activity?days=${days}&linkId=link-1&workspace=team-selected`);
  assert.equal(calls[0].options.credentials, 'include'); assert.equal(calls[0].options.cache, 'no-store'); assert.equal(calls[0].options.signal, signal);
});
test('malformed report cannot become a misleading chart', () => {
  const api = client(), data = report();
  for (const change of [
    { days: 8 }, { timezone: 'local' }, { daily: [] }, { totalOpens: -1 }, { totalOpens: 9 },
    { generatedAt: 'invalid' }, { recordingStartedAt: null }, { recordingStartedAt: 'invalid' },
    { topLinks: [...data.topLinks, data.topLinks[0]] }, { topLinks: [{ ...data.topLinks[0], opens: 9 }] },
    { topLinks: Array(11).fill(data.topLinks[0]) },
    { daily: data.daily.map((row, i) => i === 0 ? { ...row, opens: 0 } : row) },
    { daily: data.daily.map((row, i) => i === 6 ? { ...row, opens: null } : row) },
    { daily: data.daily.map((row, i) => i === 6 ? { ...row, date: '2026-10-24' } : row) },
  ]) assert.throws(() => api.mapCampaignActivity({ ...data, ...change }), /invalid campaign/i);
  assert.equal(api.mapCampaignActivity(data).daily[0].opens, null);
});
test('HTTP failures and wrong-filter results are errors, never zero activity', async () => {
  const forbidden = client(async () => ({ ok: false, status: 403 }));
  await assert.rejects(forbidden.getCampaignActivity(7, null), error => error.status === 403);
  const wrong = client(async () => ({ ok: true, json: async () => report(30) }));
  await assert.rejects(wrong.getCampaignActivity(7, null), /different filter/);
  await assert.rejects(wrong.getCampaignActivity(30, 'another-link'), /different filter/);
  await assert.rejects(wrong.getCampaignActivity(8, null), /valid campaign activity filter/);
});
test('chart skips unrecorded history and plots actual zero on the baseline', () => {
  const app = harness(), chart = app.exports.campaignChartPoints(report().daily);
  assert.equal(chart.points.length, 3); assert.equal(chart.points[0].index, 4);
  assert.equal(chart.points[1].y, 200); assert.ok(chart.points[2].y < chart.points[0].y);
  assert.ok(chart.path.startsWith(`M${chart.points[0].x},`)); assert.doesNotMatch(chart.path, /NaN|Infinity/);
  assert.equal(app.exports.campaignChartPoints([{ date: '2026-10-23', opens: 0 }]).points[0].x, 44);
});
test('empty, loading and unavailable states never display invented metrics', () => {
  const app = harness(); let managed = 0, retried = 0;
  let tree = panel(app, { links: [], onManage: () => managed++ });
  assert.match(text(tree), /Create a link, share it/); nodes(tree).find(node => node.type === 'button').props.onClick(); assert.equal(managed, 1);
  tree = panel(app, { loading: true }); assert.match(text(tree), /Loading/); assert.equal(resultNode(tree), undefined);
  tree = panel(app, { failed: true, onRetryLinks: () => retried++ }); assert.match(text(tree), /unavailable/);
  nodes(tree).find(node => node.type === 'button').props.onClick(); assert.equal(retried, 1);
});
test('period and link selection replace the chart request key; refresh retries the same filter', () => {
  const app = harness(); let tree = panel(app); const initial = resultNode(tree);
  nodes(tree).find(node => node.type === 'button' && text(node) === '7 days').props.onClick();
  tree = panel(app); const seven = resultNode(tree); assert.equal(seven.props.days, 7); assert.notEqual(initial.key, seven.key);
  nodes(tree).find(node => node.type === 'select').props.onValueChange('link-1');
  tree = panel(app); const selected = resultNode(tree); assert.equal(selected.props.linkId, 'link-1'); assert.notEqual(selected.key, seven.key);
  nodes(tree).find(node => node.type === 'button' && text(node) === 'Refresh').props.onClick();
  tree = panel(app); assert.notEqual(resultNode(tree).key, selected.key); assert.equal(resultNode(tree).props.linkId, 'link-1');
});
test('result fetch cancellation fences stale success and failure after a filter changes', async () => {
  for (const reject of [false, true]) {
    let resolve, fail; const app = harness(() => new Promise((yes, no) => { resolve = yes; fail = no; }));
    const node = resultNode(panel(app)); app.render(node.type, node.props); await app.effects(node.type);
    assert.equal(app.requests.length, 1); app.dispose(node.type); assert.equal(app.requests[0][2].aborted, true);
    if (reject) fail(Error('late')); else resolve(report()); await flush(); assert.equal(app.updates(node.type), 0);
  }
});
test('failed statistics display a retry, not a zero-valued graph', async () => {
  const app = harness(async () => { throw Error('unavailable'); }), node = resultNode(panel(app)); let retry = 0;
  const props = { ...node.props, onRetry: () => retry++ }; app.render(node.type, props); await app.effects(node.type);
  const tree = app.render(node.type, props); assert.match(text(tree), /unavailable/); assert.doesNotMatch(text(tree), /Busiest day|Days with opens/);
  nodes(tree).find(node => node.type === 'button').props.onClick(); assert.equal(retry, 1);
});
test('result renders totals, archived ranking and readable daily values with keyboard chart navigation', async () => {
  const app = harness(), node = resultNode(panel(app)); app.render(node.type, node.props); await app.effects(node.type);
  const tree = app.render(node.type, node.props); assert.match(text(tree), /Recorded opens 8/); assert.match(text(tree), /Archived/);
  const chart = nodes(tree).find(node => node.type?.name === 'DailyOpensChart');
  let rendered = app.render(chart.type, chart.props), svg = nodes(rendered).find(node => node.type === 'svg');
  assert.equal(svg.props.tabIndex, 0); assert.ok(svg.props['aria-describedby']); assert.match(text(rendered), /Not recorded/); assert.match(text(rendered), /View daily data/);
  let prevented = 0; svg.props.onKeyDown({ key: 'Home', preventDefault: () => prevented++ });
  rendered = app.render(chart.type, chart.props); assert.match(text(rendered), /Oct 21 · 2 opens/);
  svg = nodes(rendered).find(node => node.type === 'svg'); svg.props.onKeyDown({ key: 'End', preventDefault: () => prevented++ });
  rendered = app.render(chart.type, chart.props); assert.match(text(rendered), /Oct 23 · 6 opens/); assert.equal(prevented, 2);
});
test('Spanish activity labels and honest zero state are localized', async () => {
  const data = report(); data.totalOpens = 0; data.daily = data.daily.map(row => ({ ...row, opens: row.opens === null ? null : 0 })); data.topLinks = data.topLinks.map(row => ({ ...row, opens: 0 }));
  const app = harness(async () => data, 'es'), node = resultNode(panel(app)); app.render(node.type, node.props); await app.effects(node.type);
  const tree = app.render(node.type, node.props); assert.match(text(tree), /Aperturas registradas 0/); assert.match(text(tree), /No son visitantes únicos/);
  const chart = nodes(tree).find(node => node.type?.name === 'DailyOpensChart'); assert.match(text(app.render(chart.type, chart.props)), /No hay aperturas registradas/);
});
