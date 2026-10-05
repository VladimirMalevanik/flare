const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/lib/landing-motion.ts'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const exportsFixture = {};
vm.runInNewContext(code, { exports: exportsFixture, Set, WeakSet });

function fixture({ reduced = false, observer = true } = {}) {
  const mediaListeners = new Set();
  const docListeners = new Set();
  const media = { matches: reduced, addEventListener: (_, cb) => mediaListeners.add(cb), removeEventListener: (_, cb) => mediaListeners.delete(cb) };
  const doc = { hidden: false, addEventListener: (_, cb) => docListeners.add(cb), removeEventListener: (_, cb) => docListeners.delete(cb) };
  const animations = [];
  const element = (kind) => ({
    dataset: {},
    hasAttribute: name => name === kind,
    matches: selector => selector === `[${kind}]`,
    animate(frames, options) {
      const animation = { frames, options, canceled: false, finished: new Promise(() => {}), cancel() { this.canceled = true; } };
      animations.push(animation); return animation;
    },
  });
  const reveal = element('data-motion-reveal');
  const annotation = element('data-motion-annotation');
  const loop = element('data-motion-loop');
  const items = [reveal, annotation, loop];
  const root = { dataset: {}, ownerDocument: doc, querySelectorAll: selector => selector === '[data-motion-loop]' ? [loop] : items };
  let io;
  const view = { matchMedia: () => media };
  if (observer) view.IntersectionObserver = class {
    observed = new Set(); disconnected = false;
    constructor(callback) { this.callback = callback; io = this; }
    observe(item) { this.observed.add(item); }
    unobserve(item) { this.observed.delete(item); }
    disconnect() { this.disconnected = true; this.observed.clear(); }
  };
  const controller = exportsFixture.attachLandingMotion(root, view);
  return { root, reveal, annotation, loop, animations, media, doc, mediaListeners, docListeners, io, controller,
    enter(target, isIntersecting = true) { io.callback([{ target, isIntersecting }]); },
    preference(value) { media.matches = value; mediaListeners.forEach(cb => cb()); },
    visibility(hidden) { doc.hidden = hidden; docListeners.forEach(cb => cb()); },
  };
}

test('section reveals run once and loops follow actual viewport visibility', () => {
  const f = fixture();
  assert.equal(f.root.dataset.motion, 'running');
  f.enter(f.loop); assert.equal(f.loop.dataset.inView, 'true');
  f.enter(f.loop, false); assert.equal(f.loop.dataset.inView, 'false');
  f.enter(f.reveal); f.enter(f.reveal);
  assert.equal(f.animations.length, 1);
  assert.equal(f.io.observed.has(f.reveal), false);
  assert.equal(f.animations[0].options.fill, undefined, 'completed animation cannot keep content hidden');
  f.enter(f.annotation); assert.equal(f.animations.length, 2);
});

test('pause, hidden tab and live reduced-motion changes cancel transient animations and stop loops', () => {
  const f = fixture(); f.enter(f.reveal);
  f.controller.setPaused(true);
  assert.equal(f.root.dataset.motion, 'paused'); assert.equal(f.animations[0].canceled, true);
  f.controller.setPaused(false); assert.equal(f.root.dataset.motion, 'running');
  f.visibility(true); assert.equal(f.root.dataset.motion, 'paused');
  f.visibility(false); assert.equal(f.root.dataset.motion, 'running');
  f.enter(f.annotation); f.preference(true);
  assert.equal(f.root.dataset.motion, 'reduced'); assert.equal(f.animations[1].canceled, true);
  f.preference(false); assert.equal(f.root.dataset.motion, 'running');
});

test('reduced motion and missing observer leave readable static content without animation work', () => {
  const f = fixture({ reduced: true }); f.enter(f.reveal); f.enter(f.annotation);
  assert.equal(f.animations.length, 0); assert.equal(f.root.dataset.motion, 'reduced');
  assert.deepEqual(f.reveal.dataset, {}, 'no hidden/pending flags on readable content');
  const fallback = fixture({ observer: false });
  assert.equal(fallback.animations.length, 0); assert.equal(fallback.loop.dataset.inView, 'true');
});

test('unmount disconnects everything, cancels running animations and makes a late controller inert', () => {
  const f = fixture(); f.enter(f.loop); f.enter(f.reveal); f.controller.dispose();
  assert.equal(f.io.disconnected, true); assert.equal(f.mediaListeners.size, 0); assert.equal(f.docListeners.size, 0);
  assert.equal(f.animations[0].canceled, true); assert.equal(f.root.dataset.motion, undefined); assert.equal(f.loop.dataset.inView, undefined);
  f.controller.setPaused(false); f.controller.dispose();
  f.enter(f.loop); f.enter(f.annotation);
  assert.equal(f.animations.length, 1, 'queued observer delivery after unmount cannot start work');
  assert.equal(f.loop.dataset.inView, undefined);
  assert.equal(f.root.dataset.motion, undefined);
});
