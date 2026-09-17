const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = (relative) => fs.readFileSync(path.join(__dirname, relative), "utf8");

test("public landing page exposes product, account, and legal routes", () => {
  const source = read("../src/app/page.tsx");
  for (const route of ["/register", "/login", "/privacy", "/terms", "/download"]) {
    assert.match(source, new RegExp(`href=[{]?\"${route.replace("/", "\\/")}\"`));
  }
  assert.match(source, /Every published Flare links back to the saved context/);
  assert.doesNotMatch(source, /redirect\(/);
});

test("macOS download page points both architectures at stable release assets", () => {
  const source = read("../src/app/download/page.tsx");
  const desktopPackage = JSON.parse(read("../../desktop/package.json"));
  assert.equal(desktopPackage.build.artifactName, "Flare-macOS-${arch}.${ext}");
  assert.match(
    source,
    /const RELEASES_URL = "https:\/\/github\.com\/VladimirMalevanik\/flare\/releases\/latest";/,
  );
  assert.match(source, /const APPLE_SILICON_URL = `\$\{RELEASES_URL\}\/download\/Flare-macOS-arm64\.dmg`;/);
  assert.match(source, /const INTEL_URL = `\$\{RELEASES_URL\}\/download\/Flare-macOS-x64\.dmg`;/);
  assert.match(source, /href=\{APPLE_SILICON_URL\}/);
  assert.match(source, /href=\{INTEL_URL\}/);
  assert.match(source, /Apple silicon/);
  assert.match(source, /Intel/);
  assert.match(source, /Privacy &amp;[\s\S]*Security/);
  assert.match(source, /not yet notarized/);
});

test("landing exposes Mac download from navigation, hero, closing CTA, and footer", () => {
  const source = read("../src/app/page.tsx");
  assert.equal(source.match(/href="\/download"/g)?.length, 5);
  assert.match(source, /landing-actions[\s\S]*?Download for Mac/);
  assert.match(source, /landing-final-actions[\s\S]*?Download for Mac/);
});

test("mobile Vault illustration keeps a centered bounded core", () => {
  const styles = read("../src/app/landing.css");
  assert.match(
    styles,
    /\.landing-depth-core\s*\{[\s\S]*?width: clamp\(116px, 34%, 168px\);[\s\S]*?transform: translate\(-50%, -50%\);[\s\S]*?\}/,
  );
  const mobileStyles = styles.slice(styles.indexOf("@media (max-width: 680px)"));
  assert.match(
    mobileStyles,
    /\.landing-depth-visual\s*\{[\s\S]*?width: min\(100%, 360px\);[\s\S]*?aspect-ratio: 1;[\s\S]*?\}/,
  );
  assert.doesNotMatch(mobileStyles, /\.landing-depth-visual\s*\{[^}]*min-height/);
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
  assert.match(config, /poweredByHeader: false/);
  for (const header of [
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
  ]) assert.match(config, new RegExp(header));
});

test("www redirects to the canonical apex origin", () => {
  const config = read("../next.config.ts");
  assert.match(config, /type: "host", value: "www\.flare4u\.tech"/);
  assert.match(config, /destination: "https:\/\/flare4u\.tech\/:path\*"/);
  assert.match(config, /permanent: true/);
});
