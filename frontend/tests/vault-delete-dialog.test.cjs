const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const item = { id: 'note-1', title: 'Project decision', type: 'note', status: 'ready',
  content: 'Keep the saved source.', extractedFacts: [], relatedItemIds: [],
  createdAt: '2026-10-03T00:00:00Z', updatedAt: '2026-10-03T00:00:00Z', versionNumber: 1 };
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
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
const settle = () => new Promise(resolve => setImmediate(resolve));
function harness(deleteItem) {
  const state = [], deps = [], effects = [], timers = [], calls = [], focus = [], replacements = [];
  let cursor = 0, refreshes = 0;
  const query = new URLSearchParams('filter=note&item=note-1');
  const exports = {};
  const filename = path.join(__dirname, '../src/features/vault/vault-page.tsx');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, URLSearchParams, window: {
    setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout() {},
    confirm() { throw Error('Native confirmation must never open'); },
  }, require(name) {
    if (name === 'react/jsx-runtime') return jsx;
    if (name === 'react') return {
      useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial;
        return [state[i], value => state[i] = typeof value === 'function' ? value(state[i]) : value]; },
      useRef(initial) { const i = cursor++; if (!(i in state)) state[i] = { current: initial }; return state[i]; },
      useCallback(fn) { return fn; },
      useEffect(fn, values) { const i = cursor++; if (!deps[i] || values.some((value, j) => value !== deps[i][j])) {
        effects.push(fn); deps[i] = values;
      } },
    };
    if (name === 'next/link') return { default: 'a' };
    if (name === 'next/navigation') return { usePathname: () => '/vault', useSearchParams: () => query,
      useRouter: () => ({ replace: (...args) => replacements.push(args) }) };
    if (name === '@/components/dialog') return { Dialog: 'dialog' };
    if (name === '@/components/icons') return { Icon: 'icon', itemIcon: { note: 'note' } };
    if (name === '@/components/auth-session') return { useSession: () => ({ workspace: { role: 'owner' } }) };
    if (name === '@/components/workspace-context') return { useWorkspace: () => ({ revision: 0, refresh() { refreshes++; } }) };
    if (name === '@/i18n/provider') return { useI18n: () => ({ locale: 'en', label: value => value, message: value => value,
      t: (key, values) => key === 'deleteItemConfirmation' ? `Delete “${values.title}”?` : key }) };
    if (name === '@/lib/data') return { dataErrorMessage: error => error.message, dataProvider: {
      listItems: async () => [item], getItem: async () => item, trackEvent() {},
      async deleteItem(id) { calls.push(id); return deleteItem?.(id); },
    } };
    throw Error(name);
  } });
  function render() {
    cursor = 0;
    const tree = exports.VaultPage();
    for (const node of nodes(tree)) if (node.props?.ref && node.type === 'button') {
      node.props.ref.current = { focus: () => focus.push(text(node)) };
    }
    return tree;
  }
  async function runEffects() { for (const effect of effects.splice(0)) effect(); await settle(); }
  return { calls, focus, replacements, render, runEffects, get refreshes() { return refreshes; },
    dialog: () => nodes(render()).find(node => node.type === 'dialog'),
    async ready() { render(); await runEffects(); for (const timer of timers.splice(0)) timer(); await settle(); render(); await runEffects(); },
    async click(label) { const button = nodes(render()).find(node => node.type === 'button' && text(node) === label);
      assert.ok(button, label); assert.ok(!button.props.disabled, `${label} enabled`); button.props.onClick(); render(); await runEffects(); },
  };
}

test('delete requires explicit in-app confirmation; Cancel and dialog dismiss never delete the saved item', async () => {
  const app = harness(); await app.ready();
  await app.click('Delete item');
  assert.deepEqual(app.calls, []);
  assert.equal(app.dialog().props.title, 'Delete “Project decision”?');
  assert.equal(app.focus.at(-1), 'Cancel');
  await app.click('Cancel');
  assert.equal(app.dialog().props.title, 'Project decision');
  assert.equal(app.focus.at(-1), 'Delete item');
  for (const dismiss of ['Escape', 'backdrop', 'close']) {
    await app.click('Delete item');
    app.dialog().props.onClose(); app.render(); await app.runEffects();
    assert.equal(app.dialog().props.title, 'Project decision', dismiss);
    assert.deepEqual(app.calls, []);
    assert.equal(app.replacements.length, 0);
  }
});

test('confirmed delete is single request while pending and retains linked-item cleanup on success', async () => {
  let resolve;
  const app = harness(() => new Promise(done => { resolve = done; })); await app.ready();
  await app.click('Delete item');
  const confirm = nodes(app.dialog()).find(node => node.type === 'button' && text(node) === 'Delete item');
  confirm.props.onClick(); confirm.props.onClick();
  app.render(); await app.runEffects();
  assert.deepEqual(app.calls, ['note-1']);
  assert.ok(nodes(app.dialog()).filter(node => node.type === 'button').every(node => node.props.disabled));
  app.dialog().props.onClose();
  assert.ok(app.dialog());
  resolve(); await settle();
  assert.equal(app.dialog(), undefined);
  assert.equal(app.refreshes, 1);
  assert.equal(app.replacements[0][0], '/vault?filter=note');
});

test('delete failure stays visible inside confirmation, preserves item and supports retry or cancellation', async () => {
  let fail = true;
  const app = harness(async () => { if (fail) throw Error('Could not delete saved source'); }); await app.ready();
  await app.click('Delete item'); await app.click('Delete item');
  assert.equal(app.refreshes, 0);
  assert.equal(app.replacements.length, 0);
  assert.ok(nodes(app.dialog()).some(node => node.props?.role === 'alert' && text(node) === 'Could not delete saved source'));
  await app.click('Cancel');
  assert.equal(app.dialog().props.title, 'Project decision');
  assert.match(text(app.render()), /Could not delete saved source/);
  await app.click('Delete item'); fail = false; await app.click('Delete item');
  assert.deepEqual(app.calls, ['note-1', 'note-1']);
  assert.equal(app.dialog(), undefined);
  assert.equal(app.refreshes, 1);
});
