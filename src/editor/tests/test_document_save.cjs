// Run: node --test src/editor/tests/test_document_save.cjs
// Exercise the actual save/navigation functions with delayed or failed API replies.
// No browser, model, network, or user transcript files are needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
// UIKit の代わり(ui-kit v24)。画面の JS から `window.UIKit &&` の予備の経路を外しても、抜き出した関数が動くように、
// vm の context にはいつも withUIKit(context) を通す(context.UIKit と、harness の window に window.UIKit)。呼ばれた部品は h.context.UIKit.called('toast') などで読める
const { withUIKit } = require(path.join(__dirname, '..', '..', 'ui-kit', 'tests', 'uikit_stub.cjs'));

// CSP 対応(script-src 'self')でアプリの JS は index.html から app.js へ外出しした。段10 で関数の定義は app-*.js に分けた。
// テストは index.html が読む順番(app-*.js → app.js)にファイルをつなげて読み、使う関数・状態を名前で取り出す
const editorDir = path.join(__dirname, '..');
const appFiles = [...fs.readFileSync(path.join(editorDir, 'index.html'), 'utf8').matchAll(/<script src="(app[\w-]*\.js)"><\/script>/g)].map(m => m[1]);
assert.ok(appFiles.includes('app.js'), 'index.html must load app.js');
const appJs = appFiles.map(f => fs.readFileSync(path.join(editorDir, f), 'utf8').replace(/\r\n/g, '\n')).join('\n');
function fnSource(name) {   // トップレベルの function / async function name(…) の宣言(1行のものも、次の行頭の } までのものも)
  const lines = appJs.split('\n'), re = new RegExp('^(async )?function ' + name.replace(/\$/g, '\\$') + '\\s*\\(');
  const i = lines.findIndex(l => re.test(l));
  assert.ok(i >= 0, 'application function must exist: ' + name);
  if (/}\s*(\/\/.*)?$/.test(lines[i]) && (lines[i].match(/{/g) || []).length === (lines[i].match(/}/g) || []).length) return lines[i] + '\n';
  const j = lines.findIndex((l, k) => k > i && l.startsWith('}'));
  return lines.slice(i, j + 1).join('\n') + '\n';
}
function lineSource(prefix) {
  const line = appJs.split('\n').find(l => l.startsWith(prefix));
  assert.ok(line, 'application line must exist: ' + prefix);
  return line + '\n';
}
const saveSource = lineSource('const hhmm =') + fnSource('setSaveState') + lineSource('let docSaveP') + fnSource('saveDoc') + fnSource('showConflict');   // 保存の 409 の案内は app-core.js の showConflict(0.60.1)
const openSource = fnSource('openDoc') + fnSource('docInfoText') + fnSource('setUrlDoc') + fnSource('setUrlParam');   // 文書の 1 行の説明と URL の ?doc=(app-core.js の setUrlParam)も本物
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function doc(title) { return { title, speakers: [], segments: [], updatedAt: 1, whole: true }; }
function harness(respond) {
  const S = { doc: doc('edited A'), docId: 'A', dirty: true, conflict: false, saving: false,
    baseUpdatedAt: 1, list: [{ id: 'A' }], navIdx: -1, forceNext: false };
  const nodes = {}, calls = [], timers = new Map();
  let timerId = 0;
  const context = { S, window: { scrollY: 0, scrollTo() {} }, V: { rate: 1 }, CUT: null, PACK: null, wideTab: () => false, txKeybarScene() {},
    renderDocBar() {}, renderDocAuto() {}, lookupSpeakerNames() {}, renderPlayerMsg() {}, renderDocExtras() {}, applyLock() {}, applyView() {}, loadSuggest() {}, navRestore() {}, renderDoc() {}, renderList() {}, renderTerms() {}, setNav() {}, setSaveState() {}, syncEval() {}, toggleMenu() {}, updateUndo() {}, isDrawer: () => false, menuOpen: () => false, PICK: { on: false, ids: new Set(), polling: 0, active: new Set() },   // 画面を描く関数(このテストでは何もしない。下で定義し直したものが優先)   // カットのタブ(E3 から openDoc が見る)・キーの帯(段2)。このテストでは無い
    $: selector => nodes[selector] ||= { classList: { add() {}, remove() {} }, setAttribute() {} },
    setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    markDirty() { S.dirty = true; },
    loadPos() { return null; }, navSnapshot() { return null; },
    player() { return { addEventListener() {} }; },
    api(url, options) {
      // Match api()'s immediate JSON serialization; later edits cannot change a sent request.
      const call = { url, method: options?.method || 'GET', body: options?.body && JSON.parse(JSON.stringify(options.body)) };
      calls.push(call);
      return respond(call, S);
    }
  };
  // 保存と切り替えの競合には関係しない画面の更新(上の context にないもの): 知らせ・学習と精度の読み直し・題名・一覧の進み具合・パックの見積もり・
  // 校正の手間(effortStart。マスタープラン Q2)・重なりの所の空の行の候補(ovdAfterSave・loadOvd。2026-10-05)
  for (const name of ['toast', 'scheduleLearn', 'scheduleAcc', 'scheduleProgress', 'updateDocTitle', 'syncListItem', 'cpAfterSave',
    'effortStart', 'ovdAfterSave', 'loadOvd', 'fillDiarNum', 'rememberLast', 'paintSaveState']) context[name] = () => {};   // 話者の人数の欄・前回の文書(段7 E-6・E-7)
  context.apiUrl = p => p;
  vm.createContext(withUIKit(context));
  vm.runInContext(saveSource + '\n' + openSource, context);
  return { S, calls, nodes, timers, context };
}

test('a save conflict blocks navigation and keeps the edited document', async () => {
  const h = harness(async () => { throw Object.assign(new Error('conflict'), { code: 'conflict' }); });
  const edited = h.S.doc;
  assert.equal(await h.context.openDoc('B'), false);
  assert.equal(h.S.doc, edited);
  assert.equal(h.S.docId, 'A');
  assert.equal(h.S.dirty, true);
  assert.equal(h.S.conflict, true);
  assert.equal(h.nodes['#conflictBar'].hidden, false);
  assert.deepEqual(h.calls.map(x => x.method), ['PUT']);
});

test('a network failure preserves edits, schedules retry, and then permits navigation', async () => {
  let failed = false;
  const h = harness(async call => {
    if (!failed) { failed = true; throw new Error('offline'); }
    return call.method === 'PUT' ? { updatedAt: 2 } : doc('B');
  });
  assert.equal(await h.context.openDoc('B'), false);
  assert.equal(h.S.doc.title, 'edited A');
  assert.equal(h.S.dirty, true);
  assert.equal(h.timers.size, 1);
  assert.equal(await h.context.openDoc('B'), true);
  assert.equal(h.S.docId, 'B');
  assert.equal(h.S.dirty, false);
  assert.equal(h.timers.size, 1);   // 保存のやり直しの予約は消え、残るのは「前の文書が評価用の仮置きなら移す」確認の予約だけ(編集 0.33.0 の evalSettle)
  assert.deepEqual(h.calls.map(x => x.method), ['PUT', 'PUT', 'GET']);
});

test('navigation waits for an in-flight save even when dirty has been cleared', async () => {
  const pending = deferred();
  const h = harness(call => call.method === 'PUT' ? pending.promise : Promise.resolve(doc('B')));
  const saving = h.context.saveDoc();
  assert.equal(h.S.dirty, false);
  assert.equal(h.S.saving, true);
  const opening = h.context.openDoc('B');
  await flush();
  assert.equal(h.S.docId, 'A');
  assert.deepEqual(h.calls.map(x => x.method), ['PUT']);
  pending.resolve({ updatedAt: 2 });
  assert.equal(await saving, true);
  assert.equal(await opening, true);
  assert.equal(h.S.docId, 'B');
});

test('edits made during a save are also saved before switching documents', async () => {
  const pending = deferred();
  let puts = 0;
  const h = harness(call => {
    if (call.method === 'PUT') return ++puts === 1 ? pending.promise : Promise.resolve({ updatedAt: 3 });
    return Promise.resolve(doc('B'));
  });
  const opening = h.context.openDoc('B');
  h.S.doc.title = 'newest edit';
  h.context.markDirty();
  pending.resolve({ updatedAt: 2 });
  assert.equal(await opening, true);
  assert.deepEqual(h.calls.map(x => x.method), ['PUT', 'PUT', 'GET']);
  assert.equal(h.calls[0].body.title, 'edited A');
  assert.equal(h.calls[1].body.title, 'newest edit');
  assert.equal(h.calls[1].body.baseUpdatedAt, 2);
});

test('an existing conflict also blocks an automatic same-document refresh', async () => {
  const h = harness(async () => { throw new Error('API must not be called'); });
  h.S.conflict = true;
  const edited = h.S.doc;
  assert.equal(await h.context.openDoc('A', true), false);
  assert.equal(h.S.doc, edited);
  assert.equal(h.S.dirty, true);
  assert.equal(h.calls.length, 0);
});

test('edits made while the next document loads cannot be discarded', async () => {
  const pending = deferred();
  const h = harness(() => pending.promise);
  h.S.dirty = false;
  const opening = h.context.openDoc('B');
  await flush();
  h.S.doc.title = 'typed during load';
  h.context.markDirty();
  pending.resolve(doc('B'));
  assert.equal(await opening, false);
  assert.equal(h.S.docId, 'A');
  assert.equal(h.S.doc.title, 'typed during load');
  assert.equal(h.S.dirty, true);
});

test('a stale same-document response cannot replace edits saved while it loads', async () => {
  const pending = deferred();
  const h = harness(call => call.method === 'GET' ? pending.promise : Promise.resolve({ updatedAt: 2 }));
  h.S.dirty = false;
  const opening = h.context.openDoc('A', true);
  await flush();
  h.S.doc.title = 'new saved text';
  h.context.markDirty();
  await h.context.saveDoc();
  pending.resolve(doc('stale A'));
  assert.equal(await opening, false);
  assert.equal(h.S.doc.title, 'new saved text');
});

test('out-of-order responses honor the most recent navigation request', async () => {
  const pendingB = deferred(), pendingC = deferred();
  const h = harness(call => call.url.endsWith('B') ? pendingB.promise : pendingC.promise);
  h.S.dirty = false;
  const first = h.context.openDoc('B');
  await flush();
  const second = h.context.openDoc('C');
  await flush();
  pendingC.resolve(doc('C'));
  assert.equal(await second, true);
  pendingB.resolve(doc('B'));
  assert.equal(await first, false);
  assert.equal(h.S.docId, 'C');
});

test('app.js and ui-kit.js parse successfully (CSP: index.html has no inline <script>)', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
  assert.ok(scripts.length > 0);
  for (const [, attrs, source] of scripts) {
    assert.ok(/\bsrc=/.test(attrs), 'index.html の <script> は src 付き(外部ファイル)であること');
    assert.equal(source.trim(), '');
  }
  for (const f of appFiles) new vm.Script(fs.readFileSync(path.join(editorDir, f), 'utf8'), { filename: f });   // 1つずつ(画面と同じく別のスクリプト)
  new vm.Script(fs.readFileSync(path.join(__dirname, '..', 'ui-kit.js'), 'utf8'));
});

// 字幕の読む速さの印(2026-10-05): 画面の readMark とサーバーの ed_retime.subread_mark が同じ結果になること(例は tests/subread_cases.json。test_retime.py も読む)
test('readMark matches the server rule (subread_cases.json)', () => {
  const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'subread_cases.json'), 'utf8'));
  const src = lineSource("const OVD_KIND =") + lineSource('const DRAFT_KINDS =') + lineSource('const READ_FAST_CPS') + lineSource('const READ_CH') + lineSource('const READ_MEMO')
    + fnSource('isBlankDraft') + fnSource('readChars') + fnSource('readLimits') + fnSource('readMark');
  const context = { S: { settings: {} } };
  vm.createContext(withUIKit(context));
  vm.runInContext(src + '\nthis.readChars = readChars; this.readMark = readMark;', context);
  for (const [text, n] of cases.chars) assert.equal(context.readChars(text), n, text);
  for (const [row, want] of cases.marks) {
    const m = context.readMark(row);
    assert.deepEqual(m === null ? null : [m.fast, m.short], want, JSON.stringify(row));
  }
  context.S.settings = { subtitle: { read: { fastCps: 14, shortSec: 0.3 } } };   // 設定 subtitle.read(範囲の中だけ使う)
  assert.equal(context.readMark({ start: 0, end: 1.0, text: 'あいうえおかきくけこさ' }), null);
  context.S.settings = { subtitle: { read: { fastCps: 1 } } };
  assert.deepEqual(context.readMark({ start: 0, end: 1.0, text: 'あいうえおかきくけこさ' }).fast, true);
});
