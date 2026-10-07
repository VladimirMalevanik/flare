const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('./i18n-utils.cjs');

const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
function load(relative, mocks = {}, globals = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, relative), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, Intl, Date, ...globals, require(name) {
    if (name in mocks) return mocks[name];
    if (name === 'react/jsx-runtime') return jsx;
    if (name === '@/i18n/provider') return i18nMock();
    throw Error(`Unexpected import ${name}`);
  } });
  return exports;
}
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function text(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join(' ');
  return text(node.props?.children);
}
const funny = load('../src/features/funny/funny-state.ts');

test('four intentional direction reversals unlock once; a drag, jitter, or pause does not', () => {
  let tracker = funny.beginShake(0, 0, 0);
  let ritual = { phase: 'armed', requestId: 1, shakes: 0 };
  for (const [x, time] of [[30, 50], [60, 100], [90, 150]]) {
    const move = funny.moveShake(tracker, x, 0, time);
    assert.equal(move.shake, false);
    tracker = move.tracker;
  }
  for (const x of [93, 87, 94, 88]) assert.equal(funny.moveShake(tracker, x, 0, 180).shake, false);
  for (const [x, time] of [[50, 200], [90, 250], [50, 300], [90, 350]]) {
    const move = funny.moveShake(tracker, x, 0, time);
    assert.equal(move.shake, true);
    tracker = move.tracker;
    ritual = funny.advanceFunnyShake(ritual);
  }
  assert.equal(ritual.phase, 'shaken');
  assert.equal(ritual.shakes, 4);
  assert.equal(funny.advanceFunnyShake(ritual), ritual);
  assert.equal(funny.moveShake(tracker, 50, 0, 1400).shake, false);
  assert.equal(funny.consumeFunnyRequest(ritual, 0, true), 1);
  assert.equal(funny.consumeFunnyRequest(ritual, 1, true), null);
  assert.equal(funny.consumeFunnyRequest(ritual, 0, false), null);
  assert.equal(funny.consumeFunnyRequest({ ...ritual, phase: 'armed' }, 0, true), null);
  const thinking = funny.advanceFunnyShake({ ...ritual, phase: 'thinking' });
  assert.equal(thinking.phase, 'thinking');
  assert.equal(funny.consumeFunnyRequest(thinking, 0, true), null);
  assert.match(funny.funnyMessage({ ...ritual, phase: 'empty' }), /No new Flares/);
  assert.match(funny.funnyMessage({ ...ritual, phase: 'error' }), /snag/);
});

// Stable state/ref/effect slots exercise the real component's effect gate without
// adding a browser-test dependency. The real AnalyzeController still owns HTTP work.
function hooks() {
  const slots = [], pending = [];
  let cursor = 0;
  const state = initial => {
    const index = cursor++;
    if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
    return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
  };
  const effect = (fn, deps) => {
    const index = cursor++, old = slots[index];
    if (old && deps && deps.length === old.deps?.length && deps.every((value, i) => Object.is(value, old.deps[i]))) return;
    slots[index] = { deps, cleanup: old?.cleanup };
    pending.push(() => { slots[index].cleanup?.(); slots[index].cleanup = fn(); });
  };
  return {
    react: {
      useState: state,
      useRef(initial) { return state(() => ({ current: initial }))[0]; },
      useEffect: effect, useLayoutEffect: effect,
      useCallback: fn => fn, useMemo: fn => fn(),
      createContext: () => ({ Provider: 'provider' }),
    },
    render(component) { cursor = 0; return component(); },
    async flush(component) {
      let tree;
      for (let i = 0; i < 4; i++) {
        tree = this.render(component);
        while (pending.length) pending.shift()();
        await new Promise(resolve => setImmediate(resolve));
      }
      return tree;
    },
    dispose() { for (const slot of slots) slot?.cleanup?.(); },
  };
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
const available = { state: 'available', canRequestToday: true, runId: null, localDate: '2026-10-02', timezone: 'UTC', scheduledFor: null };
const emptyRun = { id: 'run-1', status: 'completed', stage: 'complete', selectedChunkCount: 5, flareIds: [], error: null };
function analyzeHarness({ mode = true, role = 'owner', status = available, muted = false, lookupError = false } = {}) {
  const h = hooks(), response = deferred(), calls = [], sounds = [], speech = [];
  const timers = new Map();
  let timerId = 0;
  const workspace = {
    refresh() {}, captureOpen: false, funnyMode: mode, funnySounds: !muted, funnyAudioPaused: false,
    funnyRitual: { ...funny.INITIAL_FUNNY_RITUAL },
    setFunnyRitual(value) { this.funnyRitual = typeof value === 'function' ? value(this.funnyRitual) : value; },
  };
  // React passes setters as bare callbacks; bind once so effect dependencies are stable.
  workspace.setFunnyRitual = workspace.setFunnyRitual.bind(workspace);
  const controllerModule = load('../src/features/analyze/analyze-controller.ts', {}, {
    AbortController, setTimeout, clearTimeout, crypto: { randomUUID: () => 'one-key' },
  });
  const provider = {
    async getDailyAnalysisStatus() { return status; },
    async startAnalysis(key) { calls.push(key); return response.promise; },
    async getAnalysisRun(id) { calls.push(`get:${id}`); if (lookupError) throw Error('status unavailable'); return emptyRun; },
  };
  const { AnalyzeAction } = load('../src/features/analyze/analyze-action.tsx', {
    react: h.react,
    '@/components/auth-session': { useSession: () => ({ workspace: { role } }) },
    '@/components/workspace-context': { useWorkspace: () => workspace },
    '@/lib/data': { dataProvider: provider, dataProviderMode: 'api' },
    './analyze-controller': controllerModule,
    './daily-status-copy': load('../src/features/analyze/daily-status-copy.ts'),
    '@/features/funny/funny-state': funny,
    '@/features/funny/funny-sounds': { playFunnySound(kind, enabled) { if (enabled) sounds.push(kind); }, speakFunnyLine(line, enabled) { if (enabled) speech.push(line); } },
  }, { window: { setTimeout: fn => { timers.set(++timerId, fn); return timerId; }, clearTimeout: id => timers.delete(id), addEventListener() {}, removeEventListener() {} }, document: { querySelector: () => ({ focus() {} }) } });
  return { workspace, response, calls, sounds, speech, render: () => h.flush(AnalyzeAction), dispose: () => h.dispose(), changeDaily(next) {
    status = next;
    const [id, fn] = Array.from(timers.entries()).at(-1);
    timers.delete(id);
    fn();
  } };
}
function primary(tree) { return nodes(tree).find(node => node.type === 'button' && node.props.className === 'button primary'); }

function capturePointerHarness(workspace) {
  const h = hooks(), captures = [], releases = [], positions = [], sounds = [];
  let opened = 0;
  Object.assign(workspace, {
    draft: '', captureOrbSize: 'medium', setDraft() {}, closeCapture() {},
    setFunnyAudioPaused(value) { workspace.funnyAudioPaused = value; },
    openCapture() { opened++; },
  });
  const { Capture } = load('../src/features/capture/capture.tsx', {
    react: h.react, 'next/link': { default: 'a' }, '@/components/icons': { Icon: 'icon' },
    '@/components/workspace-context': { useWorkspace: () => workspace },
    '@/lib/data': { dataProvider: {}, dataErrorMessage: (_error, fallback) => fallback },
    '@/lib/storage/preferences': { readLocal: (_key, fallback) => fallback, writeLocal: (_key, value) => positions.push(value) }, '@/lib/voice': {},
    './capture-position': load('../src/features/capture/capture-position.ts'),
    './use-voice-capture': { useVoiceCapture: () => ({ state: 'idle', recording: null, error: '', cancel() {}, start() {}, stop() {} }) },
    '@/features/funny/funny-state': funny,
    '@/features/funny/funny-sounds': { playFunnySound(kind, enabled) { if (enabled) sounds.push(kind); } },
  }, { window: { innerWidth: 1200, innerHeight: 800, addEventListener() {}, removeEventListener() {}, clearTimeout() {} }, requestAnimationFrame: fn => { fn(); return 1; }, cancelAnimationFrame() {} });
  let tree;
  const target = { setPointerCapture: id => captures.push(id), releasePointerCapture: id => releases.push(id) };
  return {
    async render() {
      tree = await h.flush(Capture);
      const island = nodes(tree).find(node => node.props?.['data-capture-state']);
      island.props.ref.current = { getBoundingClientRect: () => ({ left: 578, top: 19, width: 44, height: 44 }) };
      return tree;
    },
    ball: () => nodes(tree).find(node => node.props?.className === 'flare-capture-trigger'),
    event(pointerType, x, time, pointerId = 7) {
      return { button: pointerType === 'touch' ? 1 : 0, pointerType, pointerId, clientX: x, clientY: 100, timeStamp: time, currentTarget: target };
    },
    captures, releases, positions, sounds, opened: () => opened, dispose: () => h.dispose(),
  };
}

test('Analyze click only arms; the fourth shake creates one real request and preserves an empty result', async () => {
  const a = analyzeHarness({ muted: true });
  try {
    let tree = await a.render();
    primary(tree).props.onClick();
    tree = await a.render();
    assert.equal(a.workspace.funnyRitual.phase, 'armed');
    assert.equal(a.calls.length, 0);
    assert.match(text(tree), /Nah, dude/);
    for (let i = 0; i < 3; i++) {
      a.workspace.setFunnyRitual(funny.advanceFunnyShake);
      await a.render();
      assert.equal(a.calls.length, 0);
    }
    a.workspace.setFunnyRitual(funny.advanceFunnyShake);
    await a.render();
    assert.deepEqual(a.calls, ['one-key']);
    assert.equal(a.workspace.funnyRitual.phase, 'thinking');
    for (let i = 0; i < 8; i++) a.workspace.setFunnyRitual(funny.advanceFunnyShake);
    await a.render();
    assert.equal(a.calls.length, 1);
    a.response.resolve(emptyRun);
    tree = await a.render();
    assert.equal(a.workspace.funnyRitual.phase, 'empty');
    assert.match(text(tree), /Analyzed 5 selected text sections/);
    assert.match(text(tree), /No new Flares were found/);
    assert.deepEqual(a.sounds, []);
    assert.deepEqual(a.speech, []);
    // Replayed effect for the same gesture never spends another daily slot.
    a.workspace.funnyRitual = { phase: 'shaken', shakes: 4, requestId: 1 };
    await a.render();
    assert.equal(a.calls.length, 1);
  } finally { a.dispose(); }
});

test('a provider failure stays an error; capture, mode-off, viewer and reserved quota cannot enqueue a shaken ritual', async () => {
  const a = analyzeHarness();
  try {
    primary(await a.render()).props.onClick();
    a.workspace.funnyRitual = { phase: 'shaken', requestId: 1, shakes: 4 };
    await a.render();
    a.response.reject(Object.assign(new Error('daily slot consumed'), { status: 409, code: 'daily_limit' }));
    const tree = await a.render();
    assert.equal(a.workspace.funnyRitual.phase, 'error');
    assert.match(text(tree), /Today’s insight slot is already used or scheduled/);
    assert.ok(nodes(tree).some(node => node.props?.role === 'alert'));
    assert.deepEqual(a.sounds, ['error']);
  } finally { a.dispose(); }
  for (const options of [{ mode: false }, { role: 'viewer' }, { status: { ...available, canRequestToday: false, state: 'consumed' } }, { capture: true }]) {
    const b = analyzeHarness(options);
    try {
      await b.render();
      b.workspace.captureOpen = options.capture ?? false;
      b.workspace.funnyRitual = { phase: 'shaken', requestId: 1, shakes: 4 };
      await b.render();
      assert.equal(b.calls.length, 0);
      assert.equal(b.workspace.funnyRitual.phase, 'idle');
    } finally { b.dispose(); }
  }
});

test('checking an existing completed daily run bypasses the ritual and only reads status', async () => {
  const a = analyzeHarness({ status: { ...available, canRequestToday: false, state: 'completed', runId: 'existing' } });
  try {
    const tree = await a.render();
    assert.equal(primary(tree).props.disabled, false);
    primary(tree).props.onClick();
    const completed = await a.render();
    assert.deepEqual(a.calls, ['get:existing']);
    assert.equal(a.workspace.funnyRitual.phase, 'empty');
    assert.match(text(completed), /Today’s insight is complete/);
  } finally { a.dispose(); }
});

test('mouse and touch handlers require four reversals, enqueue once, and suppress capture after the shake', async () => {
  for (const pointerType of ['mouse', 'touch']) {
    const a = analyzeHarness({ muted: true });
    const c = capturePointerHarness(a.workspace);
    try {
      primary(await a.render()).props.onClick();
      await c.render();
      c.ball().props.onPointerDown(c.event(pointerType, 100, 0));
      for (const [x, time] of [[130, 50], [160, 100], [190, 150]]) c.ball().props.onPointerMove(c.event(pointerType, x, time));
      assert.equal(a.workspace.funnyRitual.shakes, 0);
      c.ball().props.onPointerUp(c.event(pointerType, 190, 200));
      c.ball().props.onClick();
      assert.equal(c.opened(), 0);
      assert.equal(a.calls.length, 0);
      c.ball().props.onPointerDown(c.event(pointerType, 100, 250));
      c.ball().props.onPointerMove(c.event(pointerType, 140, 300));
      for (const [index, x] of [100, 140, 100, 140].entries()) {
        c.ball().props.onPointerMove(c.event(pointerType, x, 350 + index * 50));
        assert.equal(a.workspace.funnyRitual.shakes, index + 1);
      }
      assert.equal(a.workspace.funnyRitual.phase, 'shaken');
      await a.render();
      await c.render();
      assert.deepEqual(a.calls, ['one-key']);
      assert.equal(a.workspace.funnyRitual.phase, 'thinking');
      c.ball().props.onPointerUp(c.event(pointerType, 140, 550));
      c.ball().props.onClick();
      assert.equal(c.opened(), 0);
      assert.deepEqual(c.captures, [7, 7]);
      assert.deepEqual(c.releases, [7, 7]);
      assert.deepEqual(c.positions, []);
      await a.render();
      assert.equal(a.calls.length, 1);
      a.response.resolve(emptyRun);
      await a.render();
    } finally { c.dispose(); a.dispose(); }
  }
});

test('cancel/lost capture discard an unfinished pointer gesture; idle dragging retains position and never analyzes', async () => {
  for (const cancel of ['onPointerCancel', 'onLostPointerCapture']) {
    const a = analyzeHarness();
    const c = capturePointerHarness(a.workspace);
    try {
      primary(await a.render()).props.onClick();
      await c.render();
      c.ball().props.onPointerDown(c.event('touch', 100, 0));
      c.ball().props.onPointerMove(c.event('touch', 140, 50));
      c.ball().props.onPointerMove(c.event('touch', 100, 100));
      assert.equal(a.workspace.funnyRitual.shakes, 1);
      c.ball().props[cancel](c.event('touch', 100, 110));
      for (const [index, x] of [140, 100, 140, 100, 140].entries()) c.ball().props.onPointerMove(c.event('touch', x, 150 + index * 50));
      c.ball().props.onPointerUp(c.event('touch', 140, 450));
      await a.render();
      assert.equal(a.calls.length, 0);
      assert.equal(a.workspace.funnyRitual.shakes, 1);
      assert.deepEqual(c.releases, []);
      assert.deepEqual(c.positions, []);
    } finally { c.dispose(); a.dispose(); }
  }
  const a = analyzeHarness();
  const c = capturePointerHarness(a.workspace);
  try {
    await a.render();
    await c.render();
    c.ball().props.onPointerDown(c.event('mouse', 100, 0));
    c.ball().props.onPointerMove(c.event('mouse', 140, 50));
    await c.render();
    c.ball().props.onPointerUp(c.event('mouse', 140, 100));
    c.ball().props.onClick();
    await c.render();
    await a.render();
    assert.equal(c.positions.length, 1);
    assert.equal(c.positions[0].x, 640);
    assert.equal(c.positions[0].y, 41);
    assert.equal(c.opened(), 0);
    assert.equal(a.workspace.funnyRitual.phase, 'idle');
    assert.equal(a.calls.length, 0);
  } finally { c.dispose(); a.dispose(); }
});

test('a changed daily cycle clears an armed/old result and a failed status resume produces honest error feedback', async () => {
  const a = analyzeHarness();
  try {
    primary(await a.render()).props.onClick();
    for (let i = 0; i < 3; i++) a.workspace.setFunnyRitual(funny.advanceFunnyShake);
    await a.render();
    a.changeDaily({ ...available, localDate: '2026-10-03' });
    let tree = await a.render();
    assert.equal(a.workspace.funnyRitual.phase, 'idle');
    a.workspace.setFunnyRitual(funny.advanceFunnyShake);
    await a.render();
    assert.equal(a.calls.length, 0);
    primary(tree).props.onClick();
    for (let i = 0; i < 4; i++) a.workspace.setFunnyRitual(funny.advanceFunnyShake);
    await a.render();
    a.response.resolve(emptyRun);
    await a.render();
    assert.equal(a.workspace.funnyRitual.phase, 'empty');
    a.changeDaily({ ...available, localDate: '2026-10-04' });
    tree = await a.render();
    assert.equal(a.workspace.funnyRitual.phase, 'idle');
    assert.doesNotMatch(text(tree), /Analyzed 5 selected text sections|No new Flares were found/);
  } finally { a.dispose(); }
  const b = analyzeHarness({ status: { ...available, canRequestToday: false, state: 'completed', runId: 'existing' }, lookupError: true });
  try {
    primary(await b.render()).props.onClick();
    const tree = await b.render();
    assert.deepEqual(b.calls, ['get:existing']);
    assert.equal(b.workspace.funnyRitual.phase, 'error');
    assert.match(text(tree), /Today’s insight status is unavailable/);
    assert.deepEqual(b.sounds, ['click', 'error']);
  } finally { b.dispose(); }
});

test('Funny mode and mute persist across a remount; disabling and cross-tab changes cancel the ritual', async () => {
  const storage = new Map([['flare-funny-mode-v1', true]]), listeners = new Map();
  let stops = 0;
  const document = { documentElement: { dataset: {} } };
  const mount = () => {
    const h = hooks();
    const { WorkspaceProvider } = load('../src/components/workspace-context.tsx', {
      react: h.react,
      './auth-session': { useSession: () => null },
      '@/lib/storage/preferences': { readLocal: (key, fallback) => storage.has(key) ? storage.get(key) : fallback, writeLocal: (key, value) => storage.set(key, value) },
      '@/features/funny/funny-state': funny,
      '@/features/funny/funny-sounds': { stopFunnySounds() { stops++; } },
    }, { document, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }), window: { addEventListener: (key, fn) => listeners.set(key, fn), removeEventListener: key => listeners.delete(key) } });
    return { render: () => h.flush(() => WorkspaceProvider({ children: 'content' })), dispose: () => h.dispose() };
  };
  const first = mount();
  let tree = await first.render();
  assert.equal(tree.props.value.funnyMode, false);
  tree.props.value.setFunnyMode(true);
  tree.props.value.setFunnySounds(false);
  tree = await first.render();
  assert.equal(document.documentElement.dataset.funnyMode, 'true');
  assert.equal(tree.props.value.funnySounds, false);
  tree.props.value.setFunnyRitual({ phase: 'armed', requestId: 4, shakes: 3 });
  tree = await first.render();
  tree.props.value.setFunnyMode(false);
  tree = await first.render();
  assert.equal(tree.props.value.funnyRitual.phase, 'idle');
  assert.equal(document.documentElement.dataset.funnyMode, 'false');
  storage.set('flare-funny-mode-v2', true);
  listeners.get('storage')();
  tree = await first.render();
  assert.equal(tree.props.value.funnyMode, true);
  first.dispose();
  assert.equal(document.documentElement.dataset.funnyMode, undefined);
  const second = mount();
  tree = await second.render();
  assert.equal(tree.props.value.funnyMode, true);
  assert.equal(tree.props.value.funnySounds, false);
  assert.equal(tree.props.value.funnyRitual.phase, 'idle');
  assert.ok(stops > 0);
  second.dispose();
});

test('the 8-ball keyboard path counts deliberate presses and retains normal capture while idle', () => {
  let opened = 0, plays = 0, prevented = 0;
  const workspace = {
    captureOpen: false, draft: '', captureOrbSize: 'medium', funnyMode: true, funnySounds: true, funnyAudioPaused: false,
    funnyRitual: { phase: 'armed', requestId: 1, shakes: 0 },
    setFunnyRitual(value) { this.funnyRitual = typeof value === 'function' ? value(this.funnyRitual) : value; },
    setFunnyAudioPaused() {}, openCapture() { opened++; }, closeCapture() {}, setDraft() {}, refresh() {},
  };
  workspace.setFunnyRitual = workspace.setFunnyRitual.bind(workspace);
  const { Capture } = load('../src/features/capture/capture.tsx', {
    react: { useState: initial => [initial, () => {}], useRef: () => ({ current: null }), useEffect() {}, useLayoutEffect() {}, useCallback: fn => fn },
    'next/link': { default: 'a' }, '@/components/icons': { Icon: 'icon' },
    '@/components/workspace-context': { useWorkspace: () => workspace },
    '@/lib/data': { dataProvider: {}, dataErrorMessage: (_error, fallback) => fallback }, '@/lib/storage/preferences': {}, '@/lib/voice': {},
    './capture-position': load('../src/features/capture/capture-position.ts'),
    './use-voice-capture': { useVoiceCapture: () => ({ state: 'idle', recording: null, error: '', cancel() {}, start() {}, stop() {} }) },
    '@/features/funny/funny-state': funny,
    '@/features/funny/funny-sounds': { playFunnySound(_kind, enabled) { if (enabled) plays++; } },
  });
  const ball = () => nodes(Capture()).find(node => node.props?.className === 'flare-capture-trigger');
  ball().props.onClick();
  assert.equal(opened, 0);
  ball().props.onKeyDown({ key: ' ', repeat: true, preventDefault() { prevented++; } });
  assert.equal(workspace.funnyRitual.shakes, 0);
  for (const key of [' ', 'Enter', ' ', 'Enter']) ball().props.onKeyDown({ key, repeat: false, preventDefault() { prevented++; } });
  assert.equal(workspace.funnyRitual.phase, 'shaken');
  assert.equal(prevented, 5);
  assert.equal(plays, 4);
  workspace.funnyRitual = { phase: 'idle', requestId: 1, shakes: 0 };
  ball().props.onClick();
  assert.equal(opened, 1);
  workspace.funnyAudioPaused = true;
  workspace.funnyRitual.phase = 'armed';
  ball().props.onKeyDown({ key: 'Enter', repeat: false, preventDefault() {} });
  assert.equal(plays, 4);
});

test('global button effects detach and silence immediately while voice pauses audio', async () => {
  const h = hooks(), handlers = new Map(), calls = [];
  const workspace = { funnyMode: true, funnySounds: true, funnyAudioPaused: false };
  class Element {
    closest(selector) { return selector.startsWith('[data-funny') ? null : this; }
    matches() { return false; }
  }
  const { FunnyEffects } = load('../src/features/funny/funny-effects.tsx', {
    react: h.react, '@/components/workspace-context': { useWorkspace: () => workspace },
    './funny-sounds': { playFunnySound: (kind, enabled) => calls.push([kind, enabled]), stopFunnySounds: () => calls.push('stop') },
  }, { Element, performance: { now: () => 500 }, document: { hidden: false, addEventListener: (key, fn) => handlers.set(key, fn), removeEventListener: key => handlers.delete(key) } });
  await h.flush(FunnyEffects);
  handlers.get('click')({ isTrusted: true, target: new Element() });
  assert.deepEqual(calls, [['click', true]]);
  workspace.funnyAudioPaused = true;
  await h.flush(FunnyEffects);
  assert.equal(handlers.has('click'), false);
  assert.ok(calls.includes('stop'));
  workspace.funnyAudioPaused = false;
  workspace.funnySounds = false;
  await h.flush(FunnyEffects);
  assert.equal(handlers.has('click'), false);
  h.dispose();
});

test('mute/recording stop active and deferred audio, while unsupported audio never blocks an action', async () => {
  let now = 100, constructors = 0, starts = 0, stops = 0, closes = 0;
  const resume = deferred();
  class AudioContext {
    constructor() { constructors++; this.state = 'suspended'; this.currentTime = 0; }
    resume() { this.state = 'running'; return resume.promise; }
    close() { closes++; this.state = 'closed'; return Promise.resolve(); }
    createOscillator() { return { frequency: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {}, disconnect() {}, start() { starts++; }, stop() { stops++; } }; }
    createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {}, disconnect() {} }; }
  }
  const sounds = load('../src/features/funny/funny-sounds.ts', {}, { window: { AudioContext }, document: { hidden: false }, performance: { now: () => now } });
  sounds.playFunnySound('shake', false);
  assert.equal(constructors, 0);
  sounds.playFunnySound('shake', true);
  assert.equal(constructors, 1);
  sounds.stopFunnySounds();
  resume.resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(starts, 0);
  assert.equal(closes, 1);
  now += 100;
  sounds.playFunnySound('shake', true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(starts, 1);
  sounds.stopFunnySounds();
  assert.equal(stops, 2); // One scheduled end and one immediate recording/mute stop.
  assert.equal(closes, 2);
  const unavailable = load('../src/features/funny/funny-sounds.ts', {}, { window: {}, document: { hidden: false }, performance: { now: () => 100 } });
  assert.doesNotThrow(() => unavailable.playFunnySound('click', true));
});
