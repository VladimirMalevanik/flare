const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');

function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
const options = [
  { value: 'en', label: 'English' },
  { value: 'blocked', label: 'French', disabled: true },
  { value: 'es', label: 'Español' },
  { value: 'it', label: 'Italiano' },
];
function fixture(extra = {}) {
  const states = [], refs = [], calls = [];
  let cursor = 0, refCursor = 0, focusCount = 0;
  const exports = {};
  const react = {
    useId: () => 'fixture', useEffect() {}, useLayoutEffect() {},
    useState(initial) { const index = cursor++; if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }]; },
    useRef(initial) { const index = refCursor++; return refs[index] ??= { current: initial }; },
  };
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/components/select.tsx'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
    throw new Error(name);
  } });
  const props = { value: 'en', options, 'aria-label': 'Language', onValueChange: value => calls.push(value), ...extra };
  const render = () => {
    cursor = refCursor = 0;
    const tree = exports.Select(props);
    nodes(tree).find(node => node.props?.role === 'combobox').props.ref.current = { focus() { focusCount++; } };
    return tree;
  };
  const key = value => {
    const event = { key: value, prevented: false, stopped: false,
      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
    nodes(render()).find(node => node.props?.role === 'combobox').props.onKeyDown(event);
    return event;
  };
  return { render, key, calls, props, focus: () => focusCount };
}
const trigger = tree => nodes(tree).find(node => node.props?.role === 'combobox');
const active = tree => nodes(tree).find(node => node.props?.role === 'option' && node.props['data-active']);

test('select keeps the current value while browsing and commits only an explicit keyboard choice', () => {
  const app = fixture();
  app.key('ArrowDown');
  assert.equal(trigger(app.render()).props['aria-expanded'], true);
  assert.equal(active(app.render()).props['aria-label'], 'English');
  app.key('ArrowDown');
  assert.equal(active(app.render()).props['aria-label'], 'Español');
  assert.deepEqual(app.calls, []);
  app.key('Enter');
  assert.deepEqual(app.calls, ['es']);
  assert.equal(trigger(app.render()).props['aria-expanded'], false);
  assert.equal(app.focus(), 1);
});

test('Escape cancels highlighted changes and stops Escape reaching the containing dialog', () => {
  const app = fixture();
  app.key('End');
  assert.equal(active(app.render()).props['aria-label'], 'Italiano');
  const event = app.key('Escape');
  assert.equal(event.stopped, true);
  assert.equal(event.prevented, true);
  assert.deepEqual(app.calls, []);
  assert.equal(trigger(app.render()).props['aria-expanded'], false);
});

test('Home, End, typeahead and Tab select enabled options without trapping the tab key', () => {
  const app = fixture();
  app.key('End');
  app.key('Home');
  assert.equal(active(app.render()).props['aria-label'], 'English');
  app.key('i');
  assert.equal(active(app.render()).props['aria-label'], 'Italiano');
  const event = app.key('Tab');
  assert.equal(event.prevented, false);
  assert.deepEqual(app.calls, ['it']);
  assert.equal(app.focus(), 0);
});

test('pointer selection ignores disabled entries and reflects controlled selection', () => {
  const app = fixture();
  trigger(app.render()).props.onClick();
  nodes(app.render()).find(node => node.props?.['aria-label'] === 'French').props.onClick();
  assert.deepEqual(app.calls, []);
  nodes(app.render()).find(node => node.props?.['aria-label'] === 'Español').props.onClick();
  assert.deepEqual(app.calls, ['es']);
  app.props.value = 'es';
  assert.equal(nodes(app.render()).find(node => node.props?.role === 'option' && node.props['aria-selected']).props['aria-label'], 'Español');
});

test('disabled and empty selectors do not open or emit a value; unknown values show a placeholder', () => {
  for (const props of [{ disabled: true }, { options: [] }]) {
    const app = fixture(props);
    app.key('ArrowDown'); app.key('Enter');
    assert.equal(trigger(app.render()).props['aria-expanded'], false);
    assert.deepEqual(app.calls, []);
  }
  const app = fixture({ value: '', placeholder: 'Choose a language' });
  assert.ok(nodes(app.render()).some(node => node.props?.children === 'Choose a language'));
});
