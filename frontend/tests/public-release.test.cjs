const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = (relative) => fs.readFileSync(path.join(__dirname, relative), "utf8");

test("public landing page exposes product, account, and legal routes", () => {
  const source = read("../src/app/page.tsx");
  for (const route of ["/register", "/login", "/privacy", "/terms"]) {
    assert.match(source, new RegExp(`href=[{]?\"${route.replace("/", "\\/")}\"`));
  }
  assert.match(source, /Every published Flare links back to the saved context/);
  assert.doesNotMatch(source, /redirect\(/);
});

test("legal pages describe current data processing without draft placeholders", () => {
  const privacy = read("../src/app/privacy/page.tsx");
  const terms = read("../src/app/terms/page.tsx");
  assert.match(privacy, /AI provider/);
  assert.match(privacy, /request bodies, query values, cookies, and secrets/);
  assert.match(terms, /early-access/);
  assert.match(terms, /AI-generated output/);
  assert.doesNotMatch(privacy + terms, /\[State|Optional:|insert arbitration/i);
});

test("registration sends explicit consent and the API records versioned acceptance", () => {
  const form = read("../src/features/auth/auth-form.tsx");
  const api = read("../../backend/app/api/auth.py");
  const repository = read("../../backend/app/models/auth.py");
  assert.match(form, /termsAccepted: data\.get\("legalAccepted"\) === "on"/);
  assert.match(form, /privacyAccepted: data\.get\("legalAccepted"\) === "on"/);
  assert.match(api, /termsAccepted: Literal\[True\]/);
  assert.match(api, /privacyAccepted: Literal\[True\]/);
  assert.match(repository, /auth_legal_acceptances/);
});

test("frontend applies release security headers", () => {
  const config = read("../next.config.ts");
  for (const header of [
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
  ]) assert.match(config, new RegExp(header));
});
