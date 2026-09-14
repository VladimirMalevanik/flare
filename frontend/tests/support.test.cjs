const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function load(relative, mocks = {}) {
  const filename = path.join(__dirname, relative);
  const code = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, {
    exports,
    require(name) {
      if (name in mocks) return mocks[name];
      throw Error(`Unexpected import ${name}`);
    },
  });
  return exports;
}

const jsx = {
  jsx: (type, props) => ({ type, props }),
  jsxs: (type, props) => ({ type, props }),
};

function nodes(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}

function renderSettings(supportEmail) {
  const { SettingsPage } = load("../src/features/settings/settings-page.tsx", {
    "react/jsx-runtime": jsx,
    react: {
      useState: (initial) => [initial, () => {}],
      useEffect: () => {},
      useMemo: (factory) => factory(),
    },
    "@/components/auth-session": { useSession: () => null },
    "@/lib/auth/session": { authRequest: async () => ({ ok: true }) },
    "@/components/icons": { Icon: "icon" },
    "@/components/dialog": { Dialog: "dialog" },
    "@/components/workspace-context": {
      useWorkspace: () => ({
        theme: "system",
        setTheme() {},
        compact: false,
        setCompact() {},
        captureOrbSize: "medium",
        setCaptureOrbSize() {},
        profile: {
          name: "Flare User",
          email: "user@example.com",
          role: "Founder",
          timezone: "Europe/Moscow",
        },
        updateProfile() {},
      }),
    },
    "@/lib/storage/preferences": { readLocal: () => ({}), writeLocal() {} },
    "@/lib/data": {
      dataErrorMessage: (_error, fallback) => fallback,
      dataProvider: {
        async getAnalysisSchedule() {
          return {
            enabled: false,
            timezone: "Europe/Moscow",
            localTime: "19:00",
            leadMinutes: 30,
            nextRefreshAt: null,
            nextRunAt: null,
            updatedAt: "2026-09-14T00:00:00Z",
          };
        },
        async updateAnalysisSchedule(value) { return value; },
        async trackEvent() {},
      },
    },
  });
  return nodes(SettingsPage({ supportEmail }));
}

test("support email configuration accepts a conservative address only", () => {
  const { normalizeSupportEmail } = load("../src/lib/support.ts");
  assert.equal(normalizeSupportEmail(" help@flare.example "), "help@flare.example");
  for (const value of [undefined, "", "missing-domain@", "a@b", "line@example.com\nBcc:x@y.com"]) {
    assert.equal(normalizeSupportEmail(value), null);
  }
});

test("Settings exposes a mail link only when support is configured", () => {
  const configured = renderSettings("help@flare.example");
  const contact = configured.find((node) => node.props?.href === "mailto:help@flare.example");
  assert.equal(contact?.type, "a");
  assert.equal(contact?.props.children, "Contact support");

  const unconfigured = renderSettings(null);
  assert.equal(unconfigured.some((node) => String(node.props?.href).startsWith("mailto:")), false);
  assert.ok(unconfigured.some((node) => node.props?.children === "Not configured"));
  assert.ok(unconfigured.some((node) => node.props?.description === "The support address will be available after launch."));
});
