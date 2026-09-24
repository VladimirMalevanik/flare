const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function loadVault() {
  const filename = path.join(__dirname, '../src/features/vault/vault-page.tsx');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, {
    exports,
    URLSearchParams,
    require: () => ({}),
  });
  return exports;
}

test('closing a linked Vault item removes only item without a reload URL', () => {
  const { withoutLinkedItem } = loadVault();
  assert.equal(withoutLinkedItem('/vault', 'item=abc'), '/vault');
  assert.equal(
    withoutLinkedItem('/vault', 'filter=voice&item=abc&sort=recent'),
    '/vault?filter=voice&sort=recent',
  );
});

test('Vault suppresses a closed deep link while revisions refresh', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '../src/features/vault/vault-page.tsx'),
    'utf8',
  );
  assert.match(source, /closedLinkedItem\.current === linkedItemId/);
  assert.match(source, /closeSelected\(\);\s*refresh\(\);/);
  assert.match(source, /onClose=\{\(\) => \{ if \(!saving\) closeSelected\(\); \}\}/);
});
