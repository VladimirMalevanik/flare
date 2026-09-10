const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
).outputText, filename);
const { VoiceRecorder } = require('../src/features/capture/voice-recorder.ts');

function setup(getMedia) {
  let stopped = 0;
  let requests = 0;
  const media = { getTracks: () => [{ stop() { stopped++; } }] };
  const recorders = [];
  class FakeRecorder {
    static isTypeSupported(mime) { return mime.startsWith('audio/webm'); }
    constructor(_, options) { this.mimeType = options.mimeType; this.state = 'inactive'; recorders.push(this); }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; }
    chunk(text) { this.ondataavailable?.({ data: new Blob([text]) }); }
    finish() { this.onstop?.(); }
  }
  global.MediaRecorder = FakeRecorder;
  Object.defineProperty(global, 'navigator', { configurable: true, value: { mediaDevices: {
    getUserMedia: () => { requests++; return getMedia ? getMedia(media) : Promise.resolve(media); }
  } } });
  const states = [];
  const controller = new VoiceRecorder(s => states.push(s));
  return {controller, states, recorders, stopped: () => stopped, requests: () => requests};
}

test('start/stop assembles final chunks and stops tracks, ready retains Blob only', async () => {
  const f = setup();
  await f.controller.start();
  f.recorders[0].chunk('first');
  f.controller.stop();
  f.recorders[0].chunk('last');
  f.recorders[0].finish();
  assert.deepEqual(f.states.map(s => s.state), ['requesting', 'recording', 'stopping', 'ready']);
  assert.equal(await f.states.at(-1).recording.blob.text(), 'firstlast');
  assert.equal(f.states.at(-1).recording.mimeType, 'audio/webm;codecs=opus');
  assert.equal(f.stopped(), 1);
  f.controller.cancel();
  assert.equal(f.states.at(-1).recording, null);
});
test('double start is locked before permission resolves; cancel releases late stream', async () => {
  let resolve;
  const f = setup(media => new Promise(r => { resolve = () => r(media); }));
  const pending = f.controller.start();
  await f.controller.start();
  assert.equal(f.requests(), 1);
  f.controller.cancel(); resolve(); await pending;
  assert.equal(f.recorders.length, 0);
  assert.equal(f.stopped(), 1);
});
test('cancel ignores stale callbacks even after another start', async () => {
  const f = setup(); await f.controller.start();
  const old = f.recorders[0];
  const onstop = old.onstop, ondata = old.ondataavailable, onerror = old.onerror;
  f.controller.cancel(); await f.controller.start();
  ondata({data:new Blob(['stale'])}); onstop(); onerror();
  assert.equal(f.states.at(-1).state, 'recording');
  f.controller.dispose();
  assert.equal(f.stopped(), 2);
});
test('dispose releases tracks and suppresses callbacks, including pending permissions', async () => {
  let resolve;
  const f = setup(media => new Promise(r => { resolve = () => r(media); }));
  const pending = f.controller.start();
  f.controller.dispose(); const count = f.states.length;
  resolve(); await pending;
  assert.equal(f.states.length, count); assert.equal(f.stopped(), 1);
});
test('empty recording and recorder error fail safely and release microphone', async () => {
  const f = setup(); await f.controller.start(); f.controller.stop(); f.recorders[0].finish();
  assert.equal(f.states.at(-1).state, 'error');
  await f.controller.start(); f.recorders[1].onerror();
  assert.equal(f.states.at(-1).state, 'error'); assert.equal(f.stopped(), 2);
});
test('no demo transcription, transport or persistence in recording code', () => {
  for (const file of ['voice-recorder.ts', 'use-voice-capture.ts', 'capture.tsx']) {
    const source = fs.readFileSync(require('node:path').join(__dirname, '../src/features/capture', file), 'utf8');
    assert.doesNotMatch(source, /Demo transcript|Use demo transcript|GROQ_API_KEY/);
  }
});
test('oversized recording is discarded and tracks stop', async () => {
  const f = setup(); await f.controller.start();
  f.recorders[0].ondataavailable({data: new Blob([new Uint8Array(10 * 1024 * 1024 + 1)])});
  assert.equal(f.states.at(-1).state, 'error');
  assert.equal(f.states.at(-1).recording, null);
  assert.equal(f.stopped(), 1);
});
test('permission rejection is recoverable without demo success', async () => {
  const f = setup(() => Promise.reject(new Error('denied')));
  await f.controller.start();
  assert.equal(f.states.at(-1).state, 'error');
  assert.equal(f.states.at(-1).recording, null);
  f.controller.cancel(); assert.equal(f.states.at(-1).state, 'idle');
});
test('recorder stop failure cannot prevent track cleanup', async () => {
  const f = setup(); await f.controller.start();
  f.recorders[0].stop = () => { throw new Error('already failed'); };
  f.controller.cancel();
  assert.equal(f.stopped(), 1); assert.equal(f.states.at(-1).state, 'idle');
});
