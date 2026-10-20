// 案件の画面へのリンクと校正の進み(src/app/ui/cases/caselink.js。ホームと案件の画面が同じ物を使う)
const test = require('node:test');
const assert = require('node:assert');
const path = require('path');

global.window = {};
require(path.join(__dirname, '..', 'ui', 'cases', 'caselink.js'));
const L = window.CaseLink;

test('リンクは c・d・m の順・あるものだけ・知らないタブは proof', () => {
  assert.strictEqual(L.href({ c: 'vid1', d: '0123456789ab', tab: 'cut' }), '/cases?c=vid1&d=0123456789ab#cut');
  assert.strictEqual(L.href({ c: 'vid1', m: 'k 1', tab: 'proof' }), '/cases?c=vid1&m=k%201#proof');
  assert.strictEqual(L.href({ c: 'vid1', tab: 'cand' }), '/cases?c=vid1#cand');
  assert.strictEqual(L.href({ d: 'abc', tab: 'tx' }), '/cases?d=abc#proof');
  assert.strictEqual(L.href({}), '/cases#proof');
});

test('URL を読む(作ったリンクがそのまま読める)', () => {
  const u = new URL('http://x' + L.href({ c: 'a&b', d: 'd1', m: 'm1', tab: 'cut' }));
  assert.deepStrictEqual(L.parse(u), { c: 'a&b', d: 'd1', m: 'm1', v: '', tab: 'cut' });
  assert.deepStrictEqual(L.parse({ search: '?v=C%3A%2Fa.mp4', hash: '#zzz' }), { c: '', d: '', m: '', v: 'C:/a.mp4', tab: '' });
});

test('校正の進み', () => {
  assert.strictEqual(L.txProgress(null), 'none');
  assert.strictEqual(L.txProgress({ segments: 0, proofed: 0 }), 'none');
  assert.strictEqual(L.txProgress({ segments: 6, proofed: 0 }), 'todo');
  assert.strictEqual(L.txProgress({ segments: 6, proofed: 2 }), 'proofing');
  assert.strictEqual(L.txProgress({ segments: 6, proofed: 6 }), 'proofed');
});
