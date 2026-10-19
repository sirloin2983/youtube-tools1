// Run: node --test src/app/tests/test_portal_edit.cjs
// ホームの運用の「編集の精度と学習」(src/app/ui/home/portal-edit.js)の、学習した候補の「登録」を切り出して試す。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '..', 'ui', 'home', 'portal-edit.js'), 'utf8').replace(/\r\n/g, '\n');
function between(start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, 'application function boundaries must exist: ' + start);
  return source.slice(a, b);
}

test('register a learned candidate: |wrong|=>right for katakana words, the right word into the glossary, one patch of top-level keys', async () => {
  const puts = [];
  const ctx = { draft: {}, toast() {}, $: () => ({ checked: true }), Promise, Array, String, Error, RegExp,
    api: (p, o) => (o && o.method === 'PUT' ? (puts.push(o.body), Promise.resolve({})) : Promise.resolve({ replacements: '', glossary: '既存', learnIgnore: [] })) };
  vm.createContext(ctx);
  vm.runInContext(between('  var key = function', '  function loadLearned()') + between('  /* 設定(置換辞書', '  function ignoreCand(') + '\nthis.register = register;', ctx);
  const row = { querySelector: s => ({ value: s === '.lw' ? 'ホシミ' : '星見' }) };
  await ctx.register({ wrong: 'ホシミ', right: '星見', count: 3 }, row);
  assert.deepEqual(JSON.parse(JSON.stringify(puts)), [{ patch: { replacements: '|ホシミ|=>星見', glossary: '既存\n星見' } }]);
});
