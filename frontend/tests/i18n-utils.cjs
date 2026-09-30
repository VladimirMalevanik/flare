const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const cache = new Map();
function loadPure(relative) {
  const filename = path.resolve(__dirname, relative);
  if (cache.has(filename)) return cache.get(filename);
  const exports = {};
  cache.set(filename, exports);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, Intl, Date, require(name) {
    if (!name.startsWith('.')) throw Error(`Unexpected pure import ${name}`);
    return loadPure(path.relative(__dirname, path.resolve(path.dirname(filename), `${name}.ts`)));
  } });
  return exports;
}
const translations = loadPure('../src/i18n/translate.ts');
function i18nMock(locale = 'en', setLocale = () => {}) {
  return { useI18n: () => ({
    locale, setLocale,
    t: (key, values) => translations.translate(locale, key, values),
    label: value => translations.localizeLabel(locale, value),
    message: value => translations.localizeMessage(locale, value),
  }) };
}
module.exports = { loadPure, i18nMock };
