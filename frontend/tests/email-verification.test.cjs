const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function load(relative, mocks = {}, globals = {}) {
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
      if (name === "@/lib/support") {
        return {
          DEFAULT_SUPPORT_EMAIL: "support@flare4u.tech",
          supportMailto(subject) {
            return `mailto:support@flare4u.tech?subject=${encodeURIComponent(subject)}`;
          },
        };
      }
      if (name === "@/components/brand-mark") {
        return { BrandMark: "brand-mark" };
      }
      throw Error(`Unexpected import ${name}`);
    },
    ...globals,
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

function hookHarness() {
  const state = [];
  let cursor = 0;
  let effects = [];
  return {
    react: {
      useState(initial) {
        const index = cursor++;
        if (!(index in state)) state[index] = initial;
        return [state[index], (value) => {
          state[index] = typeof value === "function" ? value(state[index]) : value;
        }];
      },
      useEffect(effect) {
        effects.push(effect);
      },
    },
    render(component) {
      cursor = 0;
      effects = [];
      return nodes(component());
    },
    runEffects() {
      return effects.map((effect) => effect());
    },
  };
}

test("authRequest exposes stable verification codes and registration metadata", async () => {
  const responses = [
    {
      ok: false,
      status: 403,
      json: async () => ({
        detail: {
          code: "email_verification_required",
          message: "Verify your email to continue.",
        },
      }),
    },
    {
      ok: true,
      status: 201,
      json: async () => ({ ok: true, emailVerificationRequired: true }),
    },
  ];
  const session = load("../src/lib/auth/session.ts", {}, {
    process: { env: {} },
    fetch: async () => responses.shift(),
  });
  await assert.rejects(
    session.authRequest("login", {}),
    (error) =>
      error instanceof session.AuthRequestError &&
      error.code === "email_verification_required" &&
      error.status === 403,
  );
  assert.deepEqual(
    await session.authRequest("register", {}),
    { ok: true, emailVerificationRequired: true },
  );
});

test("registration routes a verification-required account to the pending page", async () => {
  const hooks = hookHarness();
  const navigations = [];
  const auth = {
    AuthRequestError: class AuthRequestError extends Error {},
    authRequest: async () => ({ ok: true, emailVerificationRequired: true }),
  };
  const { AuthForm } = load(
    "../src/features/auth/auth-form.tsx",
    {
      "react/jsx-runtime": jsx,
      react: hooks.react,
      "next/link": { default: "a" },
      "@/components/icons": { Icon: "icon" },
      "@/lib/auth/session": auth,
    },
    {
      FormData: class FormData {
        constructor(values) { this.values = values; }
        get(name) { return this.values[name]; }
      },
      window: { location: { replace: (url) => navigations.push(url) } },
    },
  );
  const tree = hooks.render(() => AuthForm({ register: true }));
  await tree.find((node) => node.type === "form").props.onSubmit({
    preventDefault() {},
    currentTarget: {
      email: "new@flare.test",
      password: "password",
      name: "New User",
      legalAccepted: "on",
    },
  });
  assert.deepEqual(navigations, ["/verify-email?pending=1"]);
  assert.equal(tree.find((node) => node.props?.name === "legalAccepted").props.required, true);
  assert.ok(tree.some((node) => String(node.props?.href).startsWith("mailto:support@flare4u.tech")));
});

test("login verification error offers an enumeration-safe resend", async () => {
  const hooks = hookHarness();
  const calls = [];
  class AuthRequestError extends Error {
    constructor(message, code) {
      super(message);
      this.code = code;
    }
  }
  const { AuthForm } = load(
    "../src/features/auth/auth-form.tsx",
    {
      "react/jsx-runtime": jsx,
      react: hooks.react,
      "next/link": { default: "a" },
      "@/components/icons": { Icon: "icon" },
      "@/lib/auth/session": {
        AuthRequestError,
        async authRequest(path, body) {
          calls.push([path, body]);
          if (path === "login") {
            throw new AuthRequestError(
              "Verify your email to continue.",
              "email_verification_required",
            );
          }
          return { ok: true };
        },
      },
    },
    {
      FormData: class FormData {
        constructor(values) { this.values = values; }
        get(name) { return this.values[name]; }
      },
      window: { location: { replace() {} } },
    },
  );
  let tree = hooks.render(() => AuthForm({ register: false }));
  await tree.find((node) => node.type === "form").props.onSubmit({
    preventDefault() {},
    currentTarget: { email: "user@flare.test", password: "password" },
  });
  tree = hooks.render(() => AuthForm({ register: false }));
  const resend = tree.find(
    (node) => node.type === "button" && node.props.type === "button",
  );
  assert.equal(resend.props.children, "Resend verification email");
  await resend.props.onClick();
  assert.equal(calls[1][0], "resend-verification");
  assert.equal(calls[1][1].email, "user@flare.test");
});

test("verification page covers pending, success, invalid, resend, and support states", async () => {
  for (const succeeds of [true, false]) {
    const hooks = hookHarness();
    const calls = [];
    const { VerifyEmail } = load(
      "../src/features/auth/verify-email.tsx",
      {
        "react/jsx-runtime": jsx,
        react: hooks.react,
        "next/link": { default: "a" },
        "@/components/icons": { Icon: "icon" },
        "@/lib/auth/session": {
          apiBaseUrl: "/api",
          async authRequest(path, body) {
            calls.push([path, body]);
            if (path === "verify-email" && !succeeds) throw Error("invalid");
            return { ok: true };
          },
        },
      },
      {
        fetch: async () => ({
          ok: true,
          json: async () => ({ user: { email: "user@flare.test" } }),
        }),
      },
    );
    let tree = hooks.render(() =>
      VerifyEmail({ token: "token", awaitingEmail: false }),
    );
    assert.ok(tree.some((node) => node.props?.children === "Verifying your email…"));
    hooks.runEffects();
    await new Promise((resolve) => setImmediate(resolve));
    tree = hooks.render(() =>
      VerifyEmail({ token: "token", awaitingEmail: false }),
    );
    assert.ok(
      tree.some(
        (node) =>
          node.props?.children === (succeeds ? "Email verified" : "Link unavailable"),
      ),
    );
    assert.ok(tree.some((node) => String(node.props?.href).startsWith("mailto:support@flare4u.tech")));
    assert.equal(calls[0][0], "verify-email");
    if (!succeeds) {
      const resend = tree.find(
        (node) => node.type === "button" && node.props.type === "button",
      );
      await resend.props.onClick();
      assert.equal(calls[1][0], "resend-verification");
    }
  }
});
