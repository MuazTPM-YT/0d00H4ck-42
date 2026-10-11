const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(file) {
  const source = fs.readFileSync(path.join(__dirname, '../src/lib', file), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } }).outputText;
  const mod = { exports: {} };
  new Function('exports', 'module', code)(mod.exports, mod);
  return mod.exports;
}
const { acceptsNumericEdit, validQuantity, validDate, millDate } = load('validation.ts');
const { rupeesToPaise } = load('format.ts');
const { emptyJobWarning, rollLengths } = load('floor.ts');

test('numeric edits reject negative paste, exponents and junk without changing their meaning', () => {
  for (const value of ['-800', '+800', '1e3', 'NaN', 'Infinity', '8.0.0', 'eight', '−800']) assert.equal(acceptsNumericEdit(value), false, value);
  for (const value of ['', '.', '0.', '800', '800.123']) assert.equal(acceptsNumericEdit(value), true, value);
  assert.equal(acceptsNumericEdit('000123', true), true);
  assert.equal(acceptsNumericEdit('1.2', true), false);
});
test('quantity boundaries and optional zero', () => {
  for (const value of ['-800', '0', '', '1e3', '100000.001', '0.0001', 'NaN']) assert.equal(validQuantity(value, 100000), false, value);
  for (const value of ['0.001', '800', '100000']) assert.equal(validQuantity(value, 100000), true, value);
  assert.equal(validQuantity('0', 100000, 3, 0), true);
});
test('dates are real calendar days within inclusive limits in IST', () => {
  assert.equal(millDate(0, Date.parse('2026-10-10T20:00:00Z')), '2026-10-11');
  assert.equal(validDate('2026-02-30'), false);
  assert.equal(validDate('0000-01-01'), false);
  assert.equal(validDate('2026-10-10', '2026-10-11'), false);
  assert.equal(validDate('2026-10-11', '2026-10-11', '2026-10-11'), true);
  assert.equal(validDate('2026-10-12', undefined, '2026-10-11'), false);
});
test('money is exact, bounded and never signed or fractional paise', () => {
  assert.equal(rupeesToPaise('1,234.50'), 123450);
  assert.equal(rupeesToPaise('0'), 0);
  for (const value of ['-800', '1.001', '1e3', 'Infinity', '9007199254740993', '1000000000000.01']) assert.equal(rupeesToPaise(value), null, value);
});
test('finishing a loom or jigger job that made nothing asks first, spinning never does', () => {
  assert.match(emptyJobWarning('weaving', 'WO-000016', '0.000'), /^No roll cut yet on WO-000016\. Nothing will reach QC/);
  assert.match(emptyJobWarning('dyeing', 'WO-000017', '0'), /^No roll dyed yet on WO-000017/);
  assert.equal(emptyJobWarning('weaving', 'WO-1', '40.5'), null);
  assert.equal(emptyJobWarning('dyeing', 'WO-2', '2.000'), null);
  assert.equal(emptyJobWarning('spinning', 'WO-3', '0'), null);
});
test('skip cuts the planned metres into rolls of at most 1000 m', () => {
  assert.deepEqual(rollLengths('2.000'), ['2.000']);
  assert.deepEqual(rollLengths('1000'), ['1000.000']);
  assert.deepEqual(rollLengths('2500.5'), ['1000.000', '1000.000', '500.500']);
  assert.deepEqual(rollLengths('0'), []);
});
