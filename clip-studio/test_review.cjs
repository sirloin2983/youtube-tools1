// Run: node --test clip-studio/test_review.cjs
// Exercise real save/navigation/export functions with delayed and failed API replies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, 'review.js'), 'utf8');
function between(start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, 'application function boundaries must exist');
  return source.slice(a, b);
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
}
function video(id = 'A', count = 1) {
  return { id, title: id, rev: 1, marks: Array.from({ length: count }, (_, i) =>
    ({ id: 'm' + i, start: i * 10, end: i * 10 + 5, label: '', status: 'adopted', src: 'manual' })) };
}
function harness(respond) {
  const S = { cur: video(), dirty: true, editSeq: 1, loadSeq: 0, seen: new Set(),
    settings: {}, videos: [], starting: false, exportAll: null };
  const calls = [], notices = [], remembered = [], timers = new Map(), nodes = {};
  let timerId = 0, polls = 0;
  async function api(url, opts = {}) {
    const call = { url, method: opts.method || 'GET', body: opts.body && JSON.parse(JSON.stringify(opts.body)) };
    calls.push(call);
    return respond(call, S);
  }
  const context = { S, Studio: { api }, Map, Set, Error, enc: encodeURIComponent,
    $: sel => nodes[sel] ||= { dataset: {} },
    toast: msg => notices.push(msg),
    marksPayload: marks => marks, marks: () => S.cur.marks,
    sortedMarks: () => S.cur.marks, exportTargets: () => S.cur.marks,
    fetch: async (url, opts) => {
      const data = await api(url, { method: opts.method, body: JSON.parse(opts.body) });
      return { ok: true, json: async () => data };
    },
    setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    rememberJob: value => remembered.push(value),
    renderJob(j) { S.lastJob = j; if (S.job) S.job.running = j.state === 'running'; },
    pollJob() { polls++; },
    inList: () => false,
  };
  for (const name of ['renderVideoSelect', 'refreshList', 'refreshListQuiet', 'renderExportUI',
    'renderTimeline', 'renderStats', 'renderMeta', 'renderLiveCount', 'renderList',
    'renderListKeep', 'renderAll', 'setNow', 'mountPlayer', 'fetchAutoTitle', 'syncFromServer']) context[name] = () => {};
  vm.createContext(context);
  vm.runInContext(
    between('let saveTimer =', '/* サーバー側の最新') +
    between('async function flushSave()', '/* サーバーだけが決める') +
    between('function mergeServerFields(', 'const inList =') +
    between('async function loadVideo(', '/* 別の場所') +
    between('async function startExport(', '/* ---------- 描画 ---------- */'), context);
  return { S, context, calls, notices, remembered, timers, polls: () => polls };
}

test('failed save preserves edits and prevents navigation', async () => {
  const h = harness(async () => { throw new Error('disk full'); });
  const original = h.S.cur;
  assert.equal(await h.context.loadVideo('B'), false);
  assert.equal(h.S.cur, original);
  assert.equal(h.S.dirty, true);
  assert.deepEqual(h.calls.map(c => c.method), ['PUT']);
});

test('save failure prevents single and all-video exports', async () => {
  for (const method of ['startExport', 'startExportAll']) {
    const h = harness(async () => { throw new Error('offline'); });
    await h.context[method]();
    assert.equal(h.S.dirty, true);
    assert.equal(h.S.starting, false);
    assert.ok(h.calls.every(c => c.method === 'PUT'));
  }
});

test('navigation waits for ongoing save and saves edits made during it', async () => {
  const pending = deferred(); let puts = 0;
  const h = harness(async call => {
    if (call.method === 'PUT') {
      if (++puts === 1) await pending.promise;
      return { video: { ...call.body, rev: puts + 1 } };
    }
    return { video: video('B') };
  });
  const save = h.context.save();
  const opening = h.context.loadVideo('B');
  await tick();
  assert.equal(h.S.cur.id, 'A');
  h.S.cur.title = 'new edit'; h.context.markDirty();
  pending.resolve(); await save;
  assert.equal(await opening, true);
  assert.deepEqual(h.calls.map(c => c.method), ['PUT', 'PUT', 'GET']);
  assert.equal(h.calls[1].body.title, 'new edit');
  assert.equal(h.S.cur.id, 'B');
});

test('edits made while the next video loads are not discarded', async () => {
  const pending = deferred();
  const h = harness(() => pending.promise); h.S.dirty = false;
  const opening = h.context.loadVideo('B'); await tick();
  h.S.cur.title = 'keep me'; h.context.markDirty();
  pending.resolve({ video: video('B') });
  assert.equal(await opening, false);
  assert.equal(h.S.cur.title, 'keep me');
  assert.equal(h.S.dirty, true);
});

test('only the newest requested video is displayed', async () => {
  const pending = deferred();
  const h = harness(call => call.url.endsWith('B') ? pending.promise : { video: video('C') });
  h.S.dirty = false;
  const first = h.context.loadVideo('B'); await tick();
  assert.equal(await h.context.loadVideo('C'), true);
  pending.resolve({ video: video('B') });
  assert.equal(await first, false);
  assert.equal(h.S.cur.id, 'C');
});

test('all-video export chunks more than 50 marks and prevents duplicate starts', async () => {
  const pending = deferred(); let jobs = 0;
  const h = harness(async call => {
    if (call.url === '/api/videos') { await pending.promise; return { videos: [{ id: 'A', adopted: 51 }] }; }
    if (call.url.startsWith('/api/video?')) return { video: video('A', 51) };
    if (call.method === 'POST') return { id: 'j' + ++jobs, state: 'done', items: call.body.markIds.map(id => ({ id, status: 'done' })) };
    throw new Error('unexpected request');
  }); h.S.dirty = false;
  const first = h.context.startExportAll(); await tick();
  await h.context.startExportAll();
  pending.resolve(); await first;
  assert.equal(h.calls.filter(c => c.url === '/api/videos').length, 1);
  assert.deepEqual(h.calls.filter(c => c.method === 'POST').map(c => c.body.markIds.length), [50, 1]);
  assert.equal(h.S.job.running, false);
  assert.ok(h.notices.some(n => n.includes('51件')));
});

test('poll failure keeps the active export tracked and does not claim completion', async () => {
  const h = harness(async call => {
    if (call.url === '/api/videos') return { videos: [{ id: 'A', adopted: 1 }, { id: 'B', adopted: 1 }] };
    if (call.url.startsWith('/api/video?')) return { video: video('A') };
    if (call.method === 'POST') return { id: 'job', state: 'running', items: [{ id: 'm0', status: 'running' }] };
    throw new Error('connection lost');
  }); h.S.dirty = false;
  await h.context.startExportAll();
  assert.equal(h.S.job.running, true);
  assert.equal(h.polls(), 1);
  assert.equal(h.calls.filter(c => c.method === 'POST').length, 1);
  assert.equal(h.remembered.at(-1).id, 'job');
  assert.ok(h.notices.at(-1).includes('中断'));
  assert.ok(!h.notices.some(n => n.includes('書き出し完了')));
});

test('cancellation during job creation cancels the newly created job', async () => {
  let cancelled = false;
  const h = harness(async (call, S) => {
    if (call.url === '/api/videos') return { videos: [{ id: 'A', adopted: 1 }] };
    if (call.url.startsWith('/api/video?')) return { video: video('A') };
    if (call.url === '/api/export') {
      S.exportAll.cancel = true;
      return { id: 'job', state: 'running', items: [] };
    }
    if (call.url === '/api/export/cancel') { cancelled = true; return {}; }
    return { id: 'job', state: 'cancelled', items: [] };
  }); h.S.dirty = false;
  await h.context.startExportAll();
  assert.equal(cancelled, true);
  assert.equal(h.S.job.running, false);
  assert.ok(h.notices.at(-1).includes('中止'));
});

test('restoring an export during a network failure keeps its ID for polling', async () => {
  const h = harness(async () => { throw new Error('offline'); });
  h.context.localStorage = { getItem: () => JSON.stringify({ id: 'saved', videoId: 'A' }) };
  await h.context.resumeJob();
  assert.equal(h.S.job.id, 'saved');
  assert.equal(h.S.job.running, true);
  assert.equal(h.polls(), 1);
  assert.equal(h.remembered.length, 0);
});

test('restoring a completed export shows its warnings and releases its saved ID', async () => {
  const job = { id: 'saved', state: 'done', items: [{ status: 'done', warning: 'record failed' }] };
  const h = harness(async () => job);
  h.context.localStorage = { getItem: () => JSON.stringify({ id: 'saved', videoId: 'A' }) };
  await h.context.resumeJob();
  assert.equal(h.S.lastJob.items[0].warning, 'record failed');
  assert.equal(h.S.job.running, false);
  assert.equal(h.remembered.at(-1), null);
});
