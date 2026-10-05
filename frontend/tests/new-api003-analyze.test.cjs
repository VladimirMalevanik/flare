const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('./i18n-utils.cjs');
const settle = () => new Promise(resolve => setImmediate(resolve));
const pending = { id: 'run', status: 'pending', stage: 'analysis', selectedChunkCount: 2, flareIds: [], error: null };
const completed = { ...pending, status: 'completed', stage: 'completed', flareIds: ['flare'] };
function clock() {
  let now = 0, next = 0;
  const timers = new Map();
  return { timers,
    setTimeout(fn, ms) { const id = ++next; timers.set(id, { fn, time: now + ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    tick(ms) { const end = now + ms;
      for (;;) {
        const nextTimer = [...timers].filter(([, timer]) => timer.time <= end).sort((a, b) => a[1].time - b[1].time)[0];
        if (!nextTimer) break;
        const [id, timer] = nextTimer; now = timer.time; timers.delete(id); timer.fn();
      }
      now = end;
    },
  };
}
function modules(timer, mocks = {}) {
  const cache = new Map();
  return function load(relative) {
    const filename = path.resolve(__dirname, relative);
    if (cache.has(filename)) return cache.get(filename);
    const exports = {}; cache.set(filename, exports);
    const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    vm.runInNewContext(code, { exports, AbortController, Intl, Date,
      setTimeout: timer.setTimeout, clearTimeout: timer.clearTimeout, window: timer,
      require(name) {
        if (name in mocks) return mocks[name];
        if (name.startsWith('.')) return load(path.relative(__dirname, path.resolve(path.dirname(filename), `${name}.ts`)));
        throw Error(`Unexpected import ${name}`);
      },
    });
    return exports;
  };
}
function setup(provider, sleep = async () => {}, maxPolls = 40) {
  const timer = clock(), states = [], keys = [];
  let refreshed = 0;
  const { AnalyzeController } = modules(timer)('../src/features/analyze/analyze-controller.ts');
  const controller = new AnalyzeController(provider, state => states.push(state), () => refreshed++, sleep,
    () => { const key = `key-${keys.length + 1}`; keys.push(key); return key; }, maxPolls);
  return { controller, timer, states, keys, refreshed: () => refreshed };
}

test('resume expires an abort-aware fetch, releases busy and can retry the real run', async () => {
  let reads = 0, signal;
  const f = setup({ startAnalysis: () => assert.fail('resume must not enqueue'), getAnalysisRun: (_, active) => {
    signal = active;
    if (++reads === 1) return new Promise((_, reject) => active.addEventListener('abort', () => reject(Error('aborted'))));
    return Promise.resolve(completed);
  } });
  const request = f.controller.resume('run'); assert.equal(f.states.at(-1).busy, true);
  f.timer.tick(29_999); await settle(); assert.equal(f.states.at(-1).busy, true);
  f.timer.tick(1); await request;
  assert.equal(signal.aborted, true); assert.equal(f.states.at(-1).busy, false);
  assert.equal(f.states.at(-1).error, true); assert.match(f.states.at(-1).message, /status is unavailable/);
  assert.equal(f.timer.timers.size, 0); assert.equal(f.refreshed(), 0);
  await f.controller.resume('run'); assert.equal(reads, 2); assert.equal(f.refreshed(), 1);
});

test('resume deadline also settles when the provider never honors cancellation', async () => {
  let signal;
  const f = setup({ startAnalysis: () => assert.fail(), getAnalysisRun: (_, active) => {
    signal = active; return new Promise(() => {});
  } });
  const request = f.controller.resume('old', false); f.timer.tick(30_000); await request;
  assert.equal(signal.aborted, true); assert.equal(f.states.at(-1).busy, false);
  assert.equal(f.states.at(-1).message, 'The most recent insight status is unavailable.');
  assert.equal(f.refreshed(), 0); assert.equal(f.timer.timers.size, 0);
});

test('a timed out resume cannot publish its late completion over a newer run', async () => {
  let finish;
  const f = setup({ startAnalysis: async () => ({ ...completed, id: 'new' }),
    getAnalysisRun: () => new Promise(resolve => { finish = resolve; }) });
  const request = f.controller.resume('old'); f.timer.tick(30_000); await request;
  await f.controller.start(); const count = f.states.length;
  finish({ ...completed, id: 'old' }); await settle();
  assert.equal(f.states.length, count); assert.equal(f.states.at(-1).run.id, 'new'); assert.equal(f.refreshed(), 1);
});

test('a late rejected resume is handled and cannot change the deadline error', async () => {
  let fail;
  const f = setup({ startAnalysis: () => assert.fail(), getAnalysisRun: () => new Promise((_, reject) => { fail = reject; }) });
  const request = f.controller.resume('run'); f.timer.tick(30_000); await request;
  const count = f.states.length; fail(Error('late network rejection')); await settle();
  assert.equal(f.states.length, count); assert.equal(f.refreshed(), 0); assert.equal(f.timer.timers.size, 0);
});

test('resume polling keeps today or recent context without creating another run', async () => {
  for (const today of [true, false]) {
    let reads = 0;
    const f = setup({ startAnalysis: () => assert.fail('resumed work must not enqueue'),
      getAnalysisRun: async () => ++reads === 1 ? pending : completed });
    await f.controller.resume('run', today);
    assert.equal(reads, 2); assert.equal(f.states.at(-1).completion.today, today);
    assert.match(f.states.at(-1).message, today ? /Today’s insight is complete/ : /Analysis complete/);
    assert.equal(f.refreshed(), 1); assert.equal(f.timer.timers.size, 0);
  }
});

test('a bounded daily poll keeps its context when checked again', async () => {
  let reads = 0;
  const f = setup({ startAnalysis: () => assert.fail(), getAnalysisRun: async () => ++reads < 3 ? pending : completed }, async () => {}, 1);
  await f.controller.resume('run', true); assert.equal(f.states.at(-1).busy, false);
  await f.controller.start(); assert.equal(f.states.at(-1).completion.today, true); assert.equal(f.refreshed(), 1);
});

test('overall analysis expiry releases busy even for a stalled POST and reuses its unknown-outcome key', async () => {
  let finish;
  const posted = [];
  const f = setup({ startAnalysis: key => {
    posted.push(key); return posted.length === 1 ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(completed);
  }, getAnalysisRun: () => assert.fail() });
  const request = f.controller.start(); f.timer.tick(300_000); await request;
  assert.equal(f.states.at(-1).busy, false); assert.match(f.states.at(-1).message, /still pending/);
  assert.equal(f.timer.timers.size, 0);
  await f.controller.start(); assert.deepEqual(posted, ['key-1', 'key-1']);
  const count = f.states.length; finish(completed); await settle();
  assert.equal(f.states.length, count); assert.equal(f.refreshed(), 1);
});

test('overall polling expiry suppresses a late successful status read', async () => {
  let finish, entered;
  const polling = new Promise(resolve => { entered = resolve; });
  const f = setup({ startAnalysis: async () => pending, getAnalysisRun: () => { entered(); return new Promise(resolve => { finish = resolve; }); } });
  const request = f.controller.start(); await polling; f.timer.tick(300_000); await request;
  const count = f.states.length; finish(completed); await settle();
  assert.equal(f.states.length, count); assert.equal(f.states.at(-1).busy, false);
  assert.equal(f.refreshed(), 0); assert.equal(f.timer.timers.size, 0);
});

test('completion and failures clear all request deadlines', async () => {
  for (const run of [completed, { ...pending, status: 'failed', error: 'network' }, Error('unavailable')]) {
    for (const operation of ['start', 'resume']) {
      const result = async () => { if (run instanceof Error) throw run; return run; };
      const f = setup({ startAnalysis: result, getAnalysisRun: result });
      await (operation === 'start' ? f.controller.start() : f.controller.resume('run'));
      assert.equal(f.timer.timers.size, 0, `${operation} ${run.status ?? 'network error'}`);
      assert.equal(f.states.at(-1).busy, false);
    }
  }
});

test('reset and dispose clear deadlines immediately and settle noncooperative requests without stale output', async () => {
  for (const cancel of ['reset', 'dispose']) for (const operation of ['start', 'resume']) {
    let finish;
    const wait = () => new Promise(resolve => { finish = resolve; });
    const f = setup({ startAnalysis: wait, getAnalysisRun: wait });
    const request = operation === 'start' ? f.controller.start() : f.controller.resume('run');
    assert.equal(f.timer.timers.size, 1); f.controller[cancel]();
    assert.equal(f.timer.timers.size, 0); const count = f.states.length;
    await request; finish(completed); await settle();
    assert.equal(f.states.length, count); assert.equal(f.refreshed(), 0);
  }
});

test('the initial daily status deadline releases Analyze and cleanup suppresses late daily responses', async () => {
  for (const unmount of [false, true]) {
    const timer = clock(), state = [], effects = [], cleanups = [], deps = [];
    const ritual = { phase: 'idle', requestId: 0, shakes: 0 };
    let cursor = 0, starts = 0, finish;
    const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
    const load = modules(timer, {
      'react/jsx-runtime': jsx,
      'react': {
        useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial;
          return [state[i], value => state[i] = typeof value === 'function' ? value(state[i]) : value]; },
        useRef(initial) { const i = cursor++; if (!(i in state)) state[i] = { current: initial }; return state[i]; },
        useEffect(fn, values) { const i = cursor++; if (!deps[i] || values.some((value, j) => value !== deps[i][j])) { effects.push(fn); deps[i] = values; } },
      },
      '@/i18n/provider': i18nMock(),
      '@/components/auth-session': { useSession: () => ({ workspace: { role: 'owner' } }) },
      '@/components/workspace-context': { useWorkspace: () => ({ refresh() {}, captureOpen: false, funnyMode: false,
        funnyRitual: ritual, setFunnyRitual() {} }) },
      '@/lib/data': { dataProviderMode: 'api', dataProvider: { getDailyAnalysisStatus: () => new Promise(resolve => { finish = resolve; }) } },
      './analyze-controller': { AnalyzeController: class { start() { starts++; } dispose() {} reset() {} } },
      '@/features/funny/funny-state': { consumeFunnyRequest: () => null, funnyMessage: () => '', REQUIRED_SHAKES: 3 },
      '@/features/funny/funny-sounds': { playFunnySound() {}, speakFunnyLine() {} },
    });
    const { AnalyzeAction } = load('../src/features/analyze/analyze-action.tsx');
    const render = () => { cursor = 0; return AnalyzeAction(); };
    const button = () => render().props.children[0];
    render(); for (const effect of effects.splice(0)) { const cleanup = effect(); if (cleanup) cleanups.push(cleanup); }
    assert.equal(button().props.disabled, true);
    if (unmount) { for (const cleanup of cleanups) cleanup(); assert.equal(timer.timers.size, 0); }
    else { timer.tick(30_000); await settle(); assert.equal(button().props.disabled, false);
      button().props.onClick(); assert.equal(starts, 1); }
    const snapshot = JSON.stringify(state);
    finish({ state: 'scheduled', canRequestToday: false, timezone: 'UTC' }); await settle();
    assert.equal(JSON.stringify(state), snapshot);
    if (!unmount) for (const cleanup of cleanups) cleanup();
    assert.equal(timer.timers.size, 0);
  }
});
