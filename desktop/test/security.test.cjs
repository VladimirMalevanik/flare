"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const {
  createNavigationPolicy,
  isAudioOnlyMediaRequest,
  resolveAppUrl,
  resolveRuntimeAppUrl,
} = require("../security.cjs");

test("production and configured Flare origins stay inside the app", () => {
  const policy = createNavigationPolicy("https://preview.flare4u.tech/");

  assert.equal(policy.classify("https://flare4u.tech/vault"), "app");
  assert.equal(policy.classify("https://www.flare4u.tech/login"), "app");
  assert.equal(policy.classify("https://preview.flare4u.tech/sources"), "app");
  assert.equal(policy.isTrustedAppOrigin("https://preview.flare4u.tech/api/auth/me"), true);
  assert.equal(policy.isTrustedAppOrigin("https://github.com/login"), false);
});

test("GitHub authentication stays in the app and unrelated HTTPS links open externally", () => {
  const policy = createNavigationPolicy("https://flare4u.tech/");

  assert.equal(policy.classify("https://github.com/apps/flare/installations/new"), "auth");
  assert.equal(policy.classify("https://www.github.com/login/oauth/authorize"), "auth");
  assert.equal(policy.classify("https://example.com/privacy"), "external");
  assert.equal(policy.classify("mailto:support@flare4u.tech"), "external");
});

test("dangerous and malformed navigation is blocked", () => {
  const policy = createNavigationPolicy("https://flare4u.tech/");

  assert.equal(policy.classify("javascript:alert(1)"), "blocked");
  assert.equal(policy.classify("file:///etc/passwd"), "blocked");
  assert.equal(policy.classify("data:text/html,hello"), "blocked");
  assert.equal(policy.classify("not a url"), "blocked");
});

test("application URL requires HTTPS except for explicit local development", () => {
  assert.equal(resolveAppUrl("https://flare4u.tech"), "https://flare4u.tech/");
  assert.equal(
    resolveAppUrl("http://localhost:3000", { allowInsecureLocalhost: true }),
    "http://localhost:3000/",
  );
  assert.throws(() => resolveAppUrl("http://flare4u.tech"), /must use HTTPS/);
  assert.throws(() => resolveAppUrl("https://user:secret@flare4u.tech"), /embedded credentials/);
});

test("packaged builds ignore environment URL overrides", () => {
  assert.equal(
    resolveRuntimeAppUrl("https://attacker.example", { isPackaged: true }),
    "https://flare4u.tech/",
  );
  assert.equal(
    resolveRuntimeAppUrl("http://localhost:3000", { isPackaged: false }),
    "http://localhost:3000/",
  );
});

test("microphone permission excludes video capture", () => {
  assert.equal(isAudioOnlyMediaRequest({ mediaTypes: ["audio"] }), true);
  assert.equal(isAudioOnlyMediaRequest({ mediaType: "audio" }), true);
  assert.equal(isAudioOnlyMediaRequest({ mediaType: "video" }), false);
  assert.equal(isAudioOnlyMediaRequest({ mediaType: "unknown" }), false);
  assert.equal(isAudioOnlyMediaRequest({ mediaTypes: [] }), false);
  assert.equal(isAudioOnlyMediaRequest({ mediaTypes: ["video"] }), false);
  assert.equal(isAudioOnlyMediaRequest({ mediaTypes: ["audio", "video"] }), false);
});

test("packaging includes Electron and Chromium license notices", () => {
  const packageJson = require("../package.json");
  const resource = packageJson.build.extraResources.find(
    (entry) => entry.to === "licenses",
  );
  assert.ok(resource);
  assert.deepEqual(resource.filter, [
    "LICENSE.electron.txt",
    "LICENSES.chromium.html",
  ]);
});
