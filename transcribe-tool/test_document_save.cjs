// Run: node --test transcribe-tool/test_document_save.cjs
// Exercise the actual save/navigation functions with delayed or failed API replies.
// No browser, model, network, or user transcript files are needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

// CSP 対応(script-src 'self')でアプリの JS は index.html から app.js へ外出しした。テストは app.js を直接読む
const appJs = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8').replace(/\r\n/g, '\n');
function between(source, start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, 'application function boundaries must exist');
  return source.slice(a, b);
}
const saveSource = between(appJs, 'const hhmm =', "$('#cfReload').addEventListener");
const openSource = between(appJs, 'async function openDoc(', 'function opts(');
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
  const context = { S, window: { scrollY: 0, scrollTo() {} }, V: { rate: 1 },
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
  for (const name of ['toast', 'autoArchive', 'scheduleLearn', 'scheduleAcc', 'scheduleProgress',
    'renderDataset', 'syncEval', 'renderDoc', 'renderList', 'updateUndo', 'applyLock', 'loadSuggest',
    'renderAb', 'loadEvals', 'renderTerms', 'navRestore', 'renderDocExtras', 'updateDocTitle']) context[name] = () => {};
  context.apiUrl = p => p;
  vm.createContext(context);
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
  assert.equal(h.timers.size, 0);
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
  const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
  assert.ok(scripts.length > 0);
  for (const [, attrs, source] of scripts) {
    assert.ok(/\bsrc=/.test(attrs), 'index.html の <script> は src 付き(外部ファイル)であること');
    assert.equal(source.trim(), '');
  }
  new vm.Script(appJs);
  new vm.Script(fs.readFileSync(path.join(__dirname, 'ui-kit.js'), 'utf8'));
});
