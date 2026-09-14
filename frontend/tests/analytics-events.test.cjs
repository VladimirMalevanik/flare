const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');

function loadViewAnalytics() {
  const filename = path.join(__dirname, '../src/features/insights/view-analytics.ts');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require() { throw Error('Unexpected runtime import'); } });
  return exports;
}

test('a card click followed by its detail load records one Flare view', () => {
  const { nextFlareViewEvent } = loadViewAnalytics();
  const state = { current: null };
  const events = [nextFlareViewEvent(state, 'flare-1'), nextFlareViewEvent(state, 'flare-1')]
    .filter(Boolean);
  assert.equal(events.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(events[0])), {
    eventType: 'flare_viewed', targetType: 'flare', targetId: 'flare-1',
    metadata: { source: 'insights_feed' },
  });
});

test('a direct detail link records a view and reopening records a new one', () => {
  const { nextFlareViewEvent, resetFlareView } = loadViewAnalytics();
  const state = { current: null };
  assert.ok(nextFlareViewEvent(state, 'deep-link'));
  resetFlareView(state);
  assert.ok(nextFlareViewEvent(state, 'deep-link'));
});

test('capture opening and Sources navigation use their own event names once', () => {
  const capture = fs.readFileSync(
    path.join(__dirname, '../src/features/capture/capture.tsx'), 'utf8',
  );
  const insights = fs.readFileSync(
    path.join(__dirname, '../src/features/insights/insights-page.tsx'), 'utf8',
  );
  const dashboard = fs.readFileSync(
    path.join(__dirname, '../src/features/dashboard/dashboard-page.tsx'), 'utf8',
  );
  assert.equal((capture.match(/eventType: "capture_started"/g) || []).length, 1);
  assert.equal((dashboard.match(/eventType:"capture_started"/g) || []).length, 1);
  assert.equal((dashboard.match(/eventType:"capture_submitted"/g) || []).length, 1);
  assert.match(dashboard, /disabled=\{entry\.type === "audio"\}/);
  assert.match(dashboard, /entry\.type === "file"[\s\S]*openCapture\(\)/);
  assert.doesNotMatch(dashboard, /capture_voice_started|capture_voice_stopped|capture_file_attached/);
  assert.equal((insights.match(/eventType: "capture_started"/g) || []).length, 0);
  assert.match(insights, /eventType: "screen_opened"/);
  assert.doesNotMatch(insights, /eventType: "flare_viewed"[\s\S]{0,100}targetType: "screen"/);
});
