const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { loadPure, i18nMock } = require('./i18n-utils.cjs');
const { parseLocale, SUPPORTED_LOCALES } = loadPure('../src/i18n/config.ts');
const { translate, localizeLabel, localizeMessage, dictionaries } = loadPure('../src/i18n/translate.ts');
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };

function load(relative, mocks = {}, globals = {}) {
  const filename = path.join(__dirname, relative);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, Intl, ...globals, require(name) {
    if (name in mocks) return mocks[name];
    if (name === 'react/jsx-runtime') return jsx;
    if (name === 'next/link') return { default: 'a' };
    if (name === '@/components/language-selector') return { LanguageSelector: 'language-selector' };
    if (name === '@/components/brand-mark') return { BrandMark: 'brand-mark' };
    if (name === '@/components/icons') return { Icon: 'icon', itemIcon: { note: 'note' } };
    if (name === '@/components/dialog') return { Dialog: 'dialog' };
    if (name === '@/lib/support') return { DEFAULT_SUPPORT_EMAIL: 'support@flare4u.tech', supportMailto: () => 'mailto:support@flare4u.tech' };
    throw Error(`Unexpected import ${name}`);
  } });
  return exports;
}
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function text(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('');
  return text(node.props?.children);
}
function hooks(overrides = {}) {
  const states = [];
  let cursor = 0;
  return {
    react: {
      useState(initial) {
        const i = cursor++;
        if (!(i in states)) states[i] = i in overrides ? overrides[i] : typeof initial === 'function' ? initial() : initial;
        return [states[i], next => { states[i] = typeof next === 'function' ? next(states[i]) : next; }];
      },
      useEffect() {}, useLayoutEffect() {}, useMemo: fn => fn(), useCallback: fn => fn, useRef: () => ({ current: null }),
      createContext: () => ({ Provider: 'provider' }),
    },
    render(component) { cursor = 0; return component(); },
  };
}

test('locale defaults, invalid values, matching dictionaries, and interpolation', () => {
  for (const value of [undefined, null, '', 'fr', 'ES', 'es-MX', 'bad;cookie']) assert.equal(parseLocale(value), 'en');
  for (const locale of SUPPORTED_LOCALES) assert.equal(parseLocale(locale), locale);
  assert.equal(translate(undefined, 'settings'), 'Settings');
  assert.equal(translate('es', 'settings'), 'Ajustes');
  assert.deepEqual(Object.keys(dictionaries.en).sort(), Object.keys(dictionaries.es).sort());
  assert.equal(translate('es', 'rememberedItems', { count: 12 }), '12 elementos guardados');
  const title = 'Roadmap {unchanged} — José';
  assert.equal(translate('es', 'deleteItemConfirmation', { title }), `¿Eliminar «${title}»?`);
  assert.equal(localizeMessage('es', 'untrusted English server details'), 'Algo salió mal. Inténtalo de nuevo.');
});

test('Analyze localizes recent-cycle labels, statuses, and completion details', () => {
  assert.equal(translate('es', 'Check recent insight'), 'Consultar el Flare más reciente');
  assert.equal(translate('es', 'Next insight later'), 'Próximo Flare más adelante');
  assert.equal(localizeMessage('es', 'Loading the most recent insight…'), 'Cargando el Flare más reciente…');
  assert.equal(localizeMessage('es', 'The most recent insight status is unavailable.'), 'El estado del Flare más reciente no está disponible.');
  for (const [english, spanish] of [
    ['The most recent insight is complete. The next analysis slot is not available yet.', 'El Flare más reciente está completado. El próximo análisis aún no está disponible.'],
    ['The previous insight slot was used. The next analysis slot is not available yet.', 'Ya se utilizó el análisis anterior. El próximo análisis aún no está disponible.'],
    ['The most recent insight did not complete. The next analysis slot is not available yet.', 'El Flare más reciente no se completó. El próximo análisis aún no está disponible.'],
  ]) assert.equal(localizeLabel('es', english), spanish);

  assert.equal(translate('es', 'Analysis complete.'), 'Análisis completado.');
  assert.equal(translate('es', 'Analyzed {count} selected text section.', { count: 1 }), 'Se analizó 1 sección de texto seleccionada.');
  assert.equal(translate('es', 'Analyzed {count} selected text sections.', { count: 3 }), 'Se analizaron 3 secciones de texto seleccionadas.');
  assert.equal(translate('es', 'Flares refreshed.'), 'Flares actualizados.');
  assert.match(translate('es', 'No new Flares were found. Later additions cannot change this run’s result.'), /no cambiarán el resultado/);
});

test('switching locale persists one long-lived cookie, updates document language, and keeps children', async () => {
  const h = hooks();
  const document = { cookie: '', documentElement: { lang: 'en' } };
  const config = loadPure('../src/i18n/config.ts');
  const translations = loadPure('../src/i18n/translate.ts');
  const { I18nProvider } = load('../src/i18n/provider.tsx', { react: h.react, './config': config, './translate': translations }, { document });
  const children = { type: 'workspace-with-draft', props: { draft: 'Texto del usuario' } };
  let provider = h.render(() => I18nProvider({ initialLocale: 'en', children }));
  assert.equal(provider.props.value.t('settings'), 'Settings');
  provider.props.value.setLocale('es');
  assert.equal(document.documentElement.lang, 'es');
  assert.match(document.cookie, /^flare-locale=es; Path=\/; Max-Age=31536000; SameSite=Lax$/);
  provider = h.render(() => I18nProvider({ initialLocale: 'en', children }));
  assert.equal(provider.props.value.t('settings'), 'Ajustes');
  assert.equal(provider.props.children, children);
  provider.props.value.setLocale('en');
  assert.equal(document.documentElement.lang, 'en');

  // A new server render reads the persisted cookie, including after a browser restart.
  for (const cookieValue of ['es', undefined, 'invalid']) {
    const { default: RootLayout } = load('../src/app/layout.tsx', {
      'next/headers': { cookies: async () => ({ get: () => ({ value: cookieValue }) }) },
      '@/i18n/config': config, '@/i18n/provider': { I18nProvider: 'i18n-provider' }, './globals.css': {},
    });
    const root = await RootLayout({ children });
    assert.equal(root.props.lang, cookieValue === 'es' ? 'es' : 'en');
    assert.equal(root.props.children.props.children.props.initialLocale, root.props.lang);
  }
});

test('shared LanguageSelector exposes supported locales and switches through the provider', () => {
  const changes = [];
  const { LanguageSelector } = load('../src/components/language-selector.tsx', {
    '@/i18n/provider': i18nMock('es', value => changes.push(value)), '@/i18n/config': loadPure('../src/i18n/config.ts'),
  });
  for (const compact of [true, false]) {
    const select = nodes(LanguageSelector({ compact })).find(node => node.type === 'select');
    assert.equal(select.props.value, 'es');
    assert.equal(select.props['aria-label'], 'Idioma');
    assert.deepEqual(nodes(select).filter(node => node.type === 'option').map(node => node.props.value), ['en', 'es']);
    select.props.onChange({ target: { value: 'en' } });
  }
  assert.deepEqual(changes, ['en', 'en']);
});

test('landing selectors and translated demo retain tab, filter, and evidence state', () => {
  const h = hooks();
  let locale = 'en';
  const { default: Home } = load('../src/app/page.tsx', { react: h.react, '@/i18n/provider': { useI18n: () => i18nMock(locale).useI18n() } });
  let tree = h.render(Home);
  assert.ok(text(tree).includes('Your notes go quiet.'));
  const all = nodes(tree);
  all.find(node => node.props?.['aria-label'] === 'Toggle navigation').props.onClick();
  all.find(node => node.type === 'button' && text(node) === 'Risks').props.onClick();
  all.find(node => node.type === 'button' && text(node).includes('Open evidence ↓')).props.onClick();
  locale = 'es';
  tree = h.render(Home);
  assert.ok(text(tree).includes('Tus notas se quedan en silencio.'));
  assert.equal(nodes(tree).filter(node => node.type === 'language-selector').length, 2);
  assert.ok(nodes(tree).some(node => node.props?.className === 'active' && text(node) === 'Riesgos'));
  assert.ok(text(tree).includes('Ocultar evidencia ↑'));
});

const profile = { name: 'José Founder', role: 'Founder', email: 'user@example.test', timezone: 'UTC' };
const workspace = { useWorkspace: () => ({ profile, captureOrbSize: 'medium', theme: 'light', revision: 0, draft: 'User content — keep unchanged', captureOpen: true, openCapture() {}, closeCapture() {}, setDraft() {}, refresh() {}, setTheme() {}, setCompact() {}, setCaptureOrbSize() {}, updateProfile() {} }) };
function screenMocks(h, locale) {
  return { react: h.react, '@/i18n/provider': i18nMock(locale), '@/components/workspace-context': workspace,
    '@/components/auth-session': { useSession: () => null },
    '@/lib/auth/session': { apiBaseUrl: '/api', authRequest() {}, AuthRequestError: class extends Error {} },
    '@/lib/data': { dataProvider: {}, dataErrorMessage: (_error, fallback) => fallback },
    '@/lib/storage/preferences': { readLocal: () => null, writeLocal() {} },
    'next/navigation': { useSearchParams: () => new URLSearchParams(), usePathname: () => '/vault', useRouter: () => ({}) },
  };
}
test('auth and verification reuse the selector and render Spanish', () => {
  const h = hooks();
  const mocks = screenMocks(h, 'es');
  const { AuthForm } = load('../src/features/auth/auth-form.tsx', mocks);
  const login = h.render(() => AuthForm({}));
  assert.ok(text(login).includes('Iniciar sesión'));
  assert.equal(nodes(login).filter(node => node.type === 'language-selector').length, 1);
  const register = h.render(() => AuthForm({ register: true }));
  assert.ok(text(register).includes('Crea tu espacio de trabajo'));
  const verifyHooks = hooks();
  const { VerifyEmail } = load('../src/features/auth/verify-email.tsx', screenMocks(verifyHooks, 'es'));
  const verify = verifyHooks.render(() => VerifyEmail({ token: '', awaitingEmail: true }));
  assert.ok(text(verify).includes('Revisa tu correo'));
  assert.equal(nodes(verify).filter(node => node.type === 'language-selector').length, 1);
});

test('Settings, Sources, Vault, Flares, and Capture render Spanish without translating content', () => {
  const cases = [
    ['settings/settings-page', 'SettingsPage', 'Ajustes', { supportEmail: null }],
    ['sources/sources-page', 'SourcesPage', 'Fuentes'],
    ['vault/vault-page', 'VaultPage', 'Buscar notas, voz, archivos o contexto…'],
    ['insights/insights-page', 'InsightsPage', 'Cargando Flares…'],
    ['capture/capture', 'Capture', 'Añadir contexto'],
  ];
  for (const [file, component, expected, props] of cases) {
    const h = hooks();
    const mocks = { ...screenMocks(h, 'es'), '@/features/analyze/analyze-action': { AnalyzeAction: 'analyze' },
      './view-analytics': { nextFlareViewEvent() {}, resetFlareView() {} },
      './capture-position': loadPure('../src/features/capture/capture-position.ts'),
      '@/lib/voice': { transcribeVoice() {} },
      './use-voice-capture': { useVoiceCapture: () => ({ state: 'idle', recording: null, error: '', cancel() {} }) },
    };
    const screen = load(`../src/features/${file}.tsx`, mocks)[component];
    const tree = h.render(() => screen(props));
    assert.ok(text(tree).includes(expected) || nodes(tree).some(node => node.props?.placeholder === expected), file);
    if (component === 'SettingsPage') assert.ok(nodes(tree).some(node => node.type === 'language-selector' && node.props.compact === false));
    if (component === 'Capture') assert.equal(nodes(tree).find(node => node.type === 'textarea').props.value, 'User content — keep unchanged');
  }
});

test('legal document body stays English and declares its own language', () => {
  const { LegalPage } = load('../src/components/legal-page.tsx', { './legal-chrome': { LegalChrome: 'legal-chrome' }, './brand-mark': { BrandMark: 'brand-mark' } });
  for (const file of ['privacy', 'terms']) {
    const { default: Page } = load(`../src/app/${file}/page.tsx`, { '@/components/legal-page': { LegalPage, LegalSection: 'section' } });
    const page = Page();
    const rendered = LegalPage(page.props);
    const article = nodes(rendered).find(node => node.type === 'article');
    assert.equal(article.props.lang, 'en');
    assert.ok(text(article).includes(file === 'privacy' ? 'This Privacy Policy explains' : 'These terms govern access'));
  }
});

test('desktop and mobile shared profile keep Settings navigation without a chevron', () => {
  const h = hooks({ 0: true });
  const { AppShell } = load('../src/components/app-shell.tsx', {
    ...screenMocks(h, 'es'), 'next/navigation': { usePathname: () => '/vault' },
    './icons': { Icon: 'icon' }, './brand-mark': { BrandMark: 'brand-mark' }, './dialog': { Dialog: 'dialog' },
    './workspace-context': { ...workspace, WorkspaceProvider: 'workspace-provider' }, '@/features/capture/capture': { Capture: 'capture' },
  });
  const provider = AppShell({ children: 'workspace' });
  const shell = h.render(() => provider.props.children.type(provider.props.children.props));
  const profiles = nodes(shell).filter(node => node.props?.className === 'profile');
  assert.equal(profiles.length, 2);
  assert.ok(profiles.every(node => node.props.href === '/settings' && text(node).includes(profile.name)));
  assert.ok(nodes(shell).every(node => node.props?.name !== 'chevron'));
});

test('all Capture sizes stay anchored inside every required viewport at centers, edges, and corners', () => {
  const { CAPTURE_PANEL_SIZES: sizes, placeCapturePanel, clampOrbPosition, captureTransformOrigin } = loadPure('../src/features/capture/capture-position.ts');
  assert.deepEqual({ ...sizes.medium }, { width: 500, height: 204, textareaHeight: 88 });
  for (const dimension of ['width', 'height', 'textareaHeight']) assert.ok(sizes.small[dimension] < sizes.medium[dimension] && sizes.medium[dimension] < sizes.large[dimension]);
  for (const [width, height] of [[1440, 900], [1280, 800], [900, 700], [390, 844]]) {
    const viewport = { width, height };
    for (const [size, orbSize] of [['small', 36], ['medium', 44], ['large', 52]]) {
      for (const x of [0, width / 2, width]) for (const y of [0, height / 2, height]) {
        const anchor = clampOrbPosition({ x, y }, orbSize, viewport);
        const original = { ...anchor };
        const panel = placeCapturePanel(anchor, orbSize, sizes[size], viewport);
        assert.ok(panel.x >= 16 && panel.y >= 16);
        assert.ok(panel.x + panel.width <= width - 16 && panel.y + panel.height <= height - 16);
        assert.ok(panel.x <= anchor.x - orbSize / 2 && panel.x + panel.width >= anchor.x + orbSize / 2);
        assert.ok(panel.y <= anchor.y - orbSize / 2 && panel.y + panel.height >= anchor.y + orbSize / 2);
        const origin = captureTransformOrigin(anchor, panel);
        assert.equal(panel.x + origin.x, anchor.x);
        assert.equal(panel.y + origin.y, anchor.y);
        assert.deepEqual({ ...anchor }, original);
      }
    }
  }
});

test('visible JSX strings use i18n apart from legal copy, names, and technical notation', () => {
  const root = path.join(__dirname, '../src');
  const allowed = new Set([
    'Flare', 'Flares', 'Vault', 'FLARES', 'VAULT', 'VM', 'Velocity Labs', '© 2026 Flare',
    'URL', 'KB', 'Esc', '⌘K', 'Apple silicon', 'Intel', 'M', 'i', 'DMG · arm64', 'DMG · x64',
    'Europe/Moscow', 'America/Los_Angeles', 'Europe/London', 'Asia/Singapore',
  ]);
  const attributes = new Set(['title', 'subtitle', 'description', 'placeholder', 'aria-label', 'label']);
  const violations = [];
  function scan(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) { scan(file); continue; }
      if (!file.endsWith('.tsx') || /app\/(privacy|terms)\//.test(file)) continue;
      const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      function check(value) {
        const normalized = value.replace(/\s+/g, ' ').trim();
        if (!/[A-Za-z]/.test(normalized) || allowed.has(normalized)) return;
        if (file.endsWith('/components/legal-page.tsx') && ['Legal', 'Last updated:'].includes(normalized)) return;
        violations.push(`${path.relative(root, file)}: ${normalized}`);
      }
      function literal(node) {
        if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) check(node.text);
        else if (ts.isConditionalExpression(node)) { literal(node.whenTrue); literal(node.whenFalse); }
        else if (ts.isBinaryExpression(node) && [ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.AmpersandAmpersandToken].includes(node.operatorToken.kind)) literal(node.right);
      }
      function visit(node) {
        if (ts.isJsxText(node)) check(node.text);
        if (ts.isJsxAttribute(node) && attributes.has(node.name.getText(source)) && node.initializer && ts.isStringLiteral(node.initializer)) check(node.initializer.text);
        if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) literal(node.expression);
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
  scan(root);
  assert.deepEqual(violations, []);
});
