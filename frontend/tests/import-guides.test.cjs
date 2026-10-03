const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('./i18n-utils.cjs');

function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  if (typeof node.type === 'function') return nodes(node.type(node.props));
  return [node, ...nodes(node.props?.children)];
}
function text(node) {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join(' ');
  if (typeof node?.type === 'function') return text(node.type(node.props));
  return node ? text(node.props?.children) : '';
}
function harness(relative, locale) {
  const state = [], effects = [];
  let cursor = 0;
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src', relative), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' };
    if (name === 'next/link') return { default: 'a' };
    if (name === '@/i18n/provider') return i18nMock(locale);
    if (name === 'react') return {
      useState(initial) { const i = cursor++; if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial;
        return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }]; },
      useEffect(fn) { effects.push(fn); }, useMemo(fn) { return fn(); },
    };
    if (name === '@/lib/data') return { dataProvider: { async listSources() {
      return ['notion', 'obsidian', 'evernote'].map(id => ({ id, name: id, scope: '', description: '', channels: [], status: 'manual-import', updated: '' }));
    } } };
    if (name === './zip-import') return { ZipImport: ({ sourceKind }) => ({ type: 'form', props: { 'data-source': sourceKind } }) };
    if (name === '@/components/workspace-context') return { useWorkspace: () => ({ profile: { timezone: 'UTC', name: 'Test User', email: 'test@example.invalid', role: 'Member' }, openCapture() {} }) };
    if (name === '@/components/auth-session') return { useSession: () => null };
    if (name === '@/components/icons') return { Icon: () => null };
    if (name === '@/components/language-selector') return { LanguageSelector: () => null };
    if (name === '@/lib/storage/preferences') return { readLocal: (_, fallback) => fallback, writeLocal() {} };
    if (name === '@/features/funny/funny-sounds') return { playFunnySound() {} };
    if (name === '@/lib/auth/session') return { apiBaseUrl: '/api' };
    throw Error(`Unexpected import ${name}`);
  } });
  return { render(component, props = {}) { cursor = 0; return exports[component](props); },
    async loadSources() { effects[0](); await new Promise(resolve => setImmediate(resolve)); } };
}

for (const locale of ['en', 'es']) {
  for (const source of ['Notion', 'Obsidian']) test(`${locale} ${source} ZIP guide gives provider upload, publication and report directions`, () => {
    const app = harness('features/settings/import-guide-page.tsx', locale);
    const tree = app.render('ImportGuidePage', { source, preparation: 'LEGACY SINGLE FILE' });
    const copy = text(tree);
    for (const extension of ['.md', '.markdown', '.txt', '.csv']) assert.ok(copy.includes(extension));
    assert.doesNotMatch(copy, /200 KB|Capture|LEGACY SINGLE FILE/);
    assert.equal(nodes(tree).filter(n => n.type === 'li').length, 5);
    assert.match(copy, new RegExp(locale === 'en' ? `choose the ${source} card` : `tarjeta de ${source}`));
    assert.match(copy, locale === 'en' ? /asynchronously/ : /asíncrono/);
    assert.match(copy, locale === 'en' ? /import report/ : /informe de importación/);
    assert.match(copy, locale === 'en' ? /after the package is published/ : /cuando se publica el paquete/);
    assert.match(copy, locale === 'en' ? /does not start Analyze automatically/ : /no inicia el análisis automáticamente/);
    assert.match(copy, locale === 'en' ? /not synchronized/ : /no se sincronizan/);
    const primary = nodes(tree).find(n => n.type === 'a' && n.props.className === 'button primary');
    assert.equal(primary.props.href, '/sources');
    assert.equal(text(primary), locale === 'en' ? 'Open Sources' : 'Abrir Fuentes');
  });

  test(`${locale} Evernote keeps its single-file guide and workspace destination`, () => {
    const app = harness('features/settings/import-guide-page.tsx', locale);
    const tree = app.render('ImportGuidePage', { source: 'Evernote', preparation: "Use Evernote's official export tools, then prepare the content as Markdown, text, or CSV for Flare." });
    assert.equal(nodes(tree).filter(n => n.type === 'li').length, 3);
    assert.match(text(tree), /200 KB/);
    assert.match(text(tree), locale === 'en' ? /Open Capture.*attach that one file/ : /Abre Capturar.*adjunta el archivo/);
    assert.doesNotMatch(text(tree), /ZIP|asynchronously|asíncrono/);
    assert.equal(nodes(tree).find(n => n.type === 'a' && n.props.className === 'button primary').props.href, '/dashboard');
  });

  test(`${locale} Sources ZIP forms retain a guide link for each provider`, async () => {
    const app = harness('features/sources/sources-page.tsx', locale);
    app.render('SourcesPage'); await app.loadSources();
    const tree = app.render('SourcesPage');
    for (const source of ['notion', 'obsidian', 'evernote']) {
      const card = nodes(tree).find(n => n.type === 'article' && nodes(n).some(child => child.type === 'a' && child.props.href === `/settings/import-guides/${source}`));
      assert.ok(card, source);
      const link = nodes(card).find(n => n.type === 'a');
      assert.equal(text(link), locale === 'en' ? 'View import guide' : 'Ver guía de importación');
      assert.equal(nodes(card).filter(n => n.type === 'form').length, source === 'evernote' ? 0 : 1);
    }
  });

  test(`${locale} Settings differentiates ZIP rows from the unchanged Evernote limit`, () => {
    const app = harness('features/settings/settings-page.tsx', locale);
    const tree = app.render('SettingsPage', { supportEmail: null });
    for (const source of ['notion', 'obsidian', 'evernote']) {
      const row = nodes(tree).find(n => n.props?.className === 'setting-row' && nodes(n).some(child => child.type === 'a' && child.props.href === `/settings/import-guides/${source}`));
      assert.ok(row, source);
      if (source === 'evernote') assert.match(text(row), /200 KB/);
      else { assert.match(text(row), /ZIP/); assert.match(text(row), /\.markdown/); assert.doesNotMatch(text(row), /200 KB/); }
    }
  });
}
