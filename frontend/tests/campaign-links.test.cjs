const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const sample = {
  id: "link-1",
  label: "Founder post",
  slug: "founder-post-a1b2",
  shortUrl: "https://flare4u.tech/r/founder-post-a1b2",
  destinationPath: "/register",
  utmSource: "x",
  utmMedium: "organic_social",
  utmCampaign: "launch_2026_10",
  utmContent: "founder_video",
  clickCount: 12,
  createdAt: "2026-10-15T09:00:00Z",
  archivedAt: null,
};

function compile(file, jsx = false) {
  return ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: jsx ? ts.JsxEmit.ReactJSX : undefined,
    },
  }).outputText;
}

function loadClient(fetch, selectedWorkspace = "project-1") {
  const exports = {};
  const file = path.join(__dirname, "../src/features/settings/campaign-links-client.ts");
  vm.runInNewContext(compile(file), {
    exports,
    fetch,
    require(name) {
      if (name === "@/lib/auth/session") return { apiBaseUrl: "/api" };
      if (name === "@/lib/team-context") return {
        projectApiUrl: url => `${url}${url.includes("?") ? "&" : "?"}workspace=${encodeURIComponent(selectedWorkspace)}`,
      };
      throw Error(name);
    },
  });
  return exports;
}

test("campaign client normalizes UTM fields and sends create/archive in the selected project", async () => {
  const calls = [];
  const client = loadClient(async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/archive")) return { ok: true, status: 204 };
    if (options.method === "POST") return { ok: true, status: 201, json: async () => sample };
    return { ok: true, status: 200, json: async () => [sample] };
  });
  const listed = await client.listCampaignLinks();
  assert.equal(listed[0].clickCount, 12);
  const created = await client.createCampaignLink({
    label: "  Founder post  ", destinationPath: "/register", utmSource: " X ",
    utmMedium: "Organic_Social", utmCampaign: "Launch_2026_10", utmContent: " ",
  });
  assert.equal(created.shortUrl, sample.shortUrl);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    label: "Founder post", destinationPath: "/register", utmSource: "x",
    utmMedium: "organic_social", utmCampaign: "launch_2026_10",
  });
  await client.archiveCampaignLink("link/1");
  assert.equal(calls[0].url, "/api/campaign-links?workspace=project-1");
  assert.equal(calls[2].url, "/api/campaign-links/link%2F1/archive?workspace=project-1");
  assert.equal(calls[2].options.method, "POST");
});

test("campaign operations stay scoped to the selected team workspace", async () => {
  const urls = [];
  const client = loadClient(async (url, options = {}) => {
    urls.push(url);
    if (url.includes("/archive")) return { ok: true, status: 204 };
    if (options.method === "POST") return { ok: true, status: 201, json: async () => sample };
    return { ok: true, status: 200, json: async () => [sample] };
  }, "team-selected");
  await client.listCampaignLinks();
  await client.createCampaignLink({
    label: "Team launch", destinationPath: "/", utmSource: "newsletter",
    utmMedium: "email", utmCampaign: "team_launch", utmContent: "",
  });
  await client.archiveCampaignLink("link-1");
  assert.deepEqual(urls, [
    "/api/campaign-links?workspace=team-selected",
    "/api/campaign-links?workspace=team-selected",
    "/api/campaign-links/link-1/archive?workspace=team-selected",
  ]);
  assert.ok(urls.every(url => !url.includes("personal-initial")));
});

test("campaign client rejects invalid labels, UTM tokens, destinations and malformed stats", async () => {
  let calls = 0;
  const client = loadClient(async () => { calls += 1; return { ok: true, status: 200, json: async () => [] }; });
  const valid = { label: "Post", destinationPath: "/", utmSource: "x", utmMedium: "social", utmCampaign: "launch", utmContent: "" };
  for (const changed of [
    { label: " " }, { label: "bad\nlabel" }, { destinationPath: "/vault" },
    { utmSource: "paid social" }, { utmMedium: "#social" }, { utmCampaign: "a".repeat(81) },
    { utmContent: "contains/slash" },
  ]) await assert.rejects(client.createCampaignLink({ ...valid, ...changed }), /campaign link fields/i);
  assert.equal(calls, 0);
  assert.throws(() => client.mapCampaignLink({ ...sample, clickCount: -1 }), /invalid campaign link/i);
  assert.throws(() => client.mapCampaignLink({ ...sample, createdAt: "not-a-date" }), /invalid campaign link/i);
});

const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
function nodes(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function renderedText(node) {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(renderedText).join(" ");
  return node ? renderedText(node.props?.children) : "";
}

function uiHarness({ locale = "en", role = "owner", createStatus = null } = {}) {
  let currentRole = role;
  const state = [], dependencies = [], effects = [], copied = [], archived = [], created = [];
  let cursor = 0;
  class CampaignLinkError extends Error { constructor(message, status) { super(message); this.status = status; } }
  class CampaignLinkDraftError extends CampaignLinkError {}
  const client = {
    CampaignLinkError,
    CampaignLinkDraftError,
    listCampaignLinks: async () => [sample],
    createCampaignLink: async draft => {
      created.push(draft);
      if (createStatus !== null) throw new CampaignLinkError("create failed", createStatus);
      return { ...sample, id: "link-2", label: draft.label, shortUrl: "https://flare4u.tech/r/new-link", clickCount: 0 };
    },
    archiveCampaignLink: async id => { archived.push(id); },
  };
  const exports = {};
  const file = path.join(__dirname, "../src/features/settings/campaign-links.tsx");
  vm.runInNewContext(compile(file, true), {
    exports,
    AbortController,
    Intl,
    Date,
    navigator: { clipboard: { writeText: async value => { copied.push(value); } } },
    require(name) {
      if (name === "react/jsx-runtime") return jsx;
      if (name === "react") return {
        useState(initial) {
          const index = cursor++;
          if (!(index in state)) state[index] = initial;
          return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
        },
        useEffect(effect, values) {
          const index = cursor++;
          if (!dependencies[index] || values.some((value, offset) => value !== dependencies[index][offset])) {
            dependencies[index] = values;
            effects.push(effect);
          }
        },
      };
      if (name === "@/components/auth-session") return { useSession: () => ({ workspace: { role: currentRole } }) };
      if (name === "@/components/icons") return { Icon: "icon" };
      if (name === "@/components/select") return { Select: "select" };
      if (name === "@/i18n/provider") return { useI18n: () => ({ locale }) };
      if (name === "./campaign-links-client") return client;
      if (name === "./campaign-links.css") return {};
      throw Error(name);
    },
  });
  const app = {
    exports, copied, archived, created,
    render() { cursor = 0; return exports.CampaignLinksPanel(); },
    wrapper() { return exports.CampaignLinks(); },
    setRole(value) { currentRole = value; },
    async ready() {
      app.render();
      for (const effect of effects.splice(0)) effect();
      await new Promise(resolve => setImmediate(resolve));
    },
  };
  return app;
}

test("campaign Settings UI is owner-only, exposes honest counts, copy and archive", async () => {
  const app = uiHarness();
  app.setRole("editor");
  assert.equal(app.wrapper(), null);
  app.setRole("owner");
  assert.ok(app.wrapper());
  await app.ready();
  let tree = app.render();
  assert.match(renderedText(tree), /aggregate count with no visitor identifiers/i);
  assert.match(renderedText(tree), /automated previews, and bots can increase it/i);
  assert.match(renderedText(tree), /temporary service contention can miss opens/i);
  assert.match(renderedText(tree), /do not put names, email addresses, or confidential information/i);
  assert.match(renderedText(tree), /Archiving stops future opens from being counted/i);
  assert.match(renderedText(tree), /12 Recorded link opens/);
  const button = label => nodes(app.render()).find(node => node.type === "button" && renderedText(node).trim() === label);
  await button("Copy").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(app.copied, [sample.shortUrl]);
  await button("Archive").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(app.archived, [sample.id]);
  tree = app.render();
  assert.match(renderedText(tree), /Archived/);
  assert.match(renderedText(tree), /still redirect, but no longer increase this count/);
});

test("campaign Settings UI includes complete Spanish copy and targeted public rewrite", () => {
  const app = uiHarness({ locale: "es" });
  const text = renderedText(app.render());
  assert.match(text, /Enlaces de campaña/);
  assert.match(text, /No representa personas únicas/);
  assert.match(text, /sin identificadores de visitantes/);
  assert.match(text, /No incluyas nombres, correos electrónicos ni información confidencial/);
  const config = fs.readFileSync(path.join(__dirname, "../next.config.ts"), "utf8");
  assert.match(config, /source: "\/r\/:slug"/);
  assert.match(config, /campaign-links\/r\/:slug/);
  const notice = fs.readFileSync(path.join(__dirname, "../src/app/measurement/page.tsx"), "utf8");
  assert.match(notice, /Campaign-link redirects/);
  assert.match(notice, /does not create a per-request event/);
  assert.match(notice, /Archived links continue to redirect but stop increasing the counter/);
});

test("campaign Settings keeps every active link visible inside the bounded list", () => {
  const app = uiHarness();
  const rows = Array.from({ length: 125 }, (_, index) => ({
    ...sample,
    id: `link-${index}`,
    createdAt: new Date(Date.UTC(2026, 9, 15, 0, index)).toISOString(),
    archivedAt: index % 6 === 0 ? null : "2026-10-15T10:00:00Z",
  }));
  const visible = app.exports.visibleCampaignLinks(rows);
  assert.equal(visible.length, 100);
  const active = rows.filter(row => row.archivedAt === null);
  assert.deepEqual(
    Array.from(visible.slice(0, active.length), row => row.id).sort(),
    active.map(row => row.id).sort(),
  );
  assert.ok(visible.slice(active.length).every(row => row.archivedAt !== null));
});

test("campaign Settings UI explains the active-link cap instead of suggesting a retry", async () => {
  const app = uiHarness({ createStatus: 409 });
  const form = nodes(app.render()).find(node => node.type === "form");
  await form.props.onSubmit({ preventDefault() {} });
  await new Promise(resolve => setImmediate(resolve));
  const text = renderedText(app.render());
  assert.match(text, /up to 25 active campaign links/i);
  assert.match(text, /Archive one before creating another/i);
});
