// Run: node --test studio/tests/test_review.cjs
// Exercise real save/navigation/export functions with delayed and failed API replies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '..', 'review.js'), 'utf8');
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
    'renderListKeep', 'renderAll', 'setNow', 'mountPlayer', 'fetchAutoTitle', 'syncFromServer', 'loadTranscripts', 'pollAuto']) context[name] = () => {};   // pollAuto: まとめて実行の進み具合(⑦)
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

/* ---- 2026-09-24 画面の見直しで足したテスト ---- */
function load(parts, extra) {
  const context = { Map, Set, Error, ...extra };
  vm.createContext(context);
  vm.runInContext(parts.map(([a, b]) => between(a, b)).join('\n'), context);
  return context;
}
function navHarness(sortBy, filter, sel) {
  const marks = [
    { id: 'a', start: 10, end: 15, score: 2, status: '' },
    { id: 'b', start: 20, end: 25, score: 9, status: '' },
    { id: 'c', start: 30, end: 35, score: 5, status: 'adopted' },
    { id: 'd', start: 40, end: 45, score: 7, status: '' },
  ];
  const S = { settings: { sortBy }, filter, sel }, picked = [], notes = [];
  const ctx = load([['const statusOf', 'const isFolded'], ['const byScore', 'function setStatus('], ['function goMark(', 'function decideSel(']], {
    S, sortedMarks: () => [...marks].sort((x, y) => x.start - y.start), toast: m => notes.push(m), selectMark: m => { picked.push(m.id); S.sel = m.id; } });
  return { ctx, S, picked, notes, marks };
}

test('next/previous mark follows the displayed order (score sort), not only time', () => {
  const h = navHarness('score', 'all', 'b');   // 点数順: b(9) d(7) c(5) a(2)
  h.ctx.goMark(1, false); h.ctx.goMark(1, false); h.ctx.goMark(1, false);
  assert.deepEqual(h.picked, ['d', 'c', 'a']);
  h.ctx.goMark(1, false);
  assert.ok(h.notes.at(-1).includes('後のマークはありません'));
  h.ctx.goMark(-1, false);
  assert.equal(h.picked.at(-1), 'c');
});

test('time order navigation is unchanged and "next candidate" skips decided marks from the changed mark', () => {
  const h = navHarness('time', 'all', null);
  h.ctx.goMark(1, false);
  assert.deepEqual(h.picked, ['a']);
  h.ctx.goMark(1, true, h.marks.find(m => m.id === 'b'));   // b を採用した直後: c(採用済み)を飛ばして d へ
  assert.equal(h.picked.at(-1), 'd');
  const s = navHarness('score', '', null);   // 候補だけ表示 + 点数順
  s.ctx.goMark(1, true, s.marks.find(m => m.id === 'd'));   // d(7) の次の候補は a(2)(c は採用済み)
  assert.equal(s.picked.at(-1), 'a');
});

test('exported file path: server path first, otherwise outDir + relative file with the right separator', () => {
  const ctx = load([['/* ---------- 書き出したファイルのパス', 'function handoffHTML(']], {});
  assert.equal(ctx.clipPathOf({ outDir: 'C:\\Users\\me\\exports' }, { file: '動画 A/01_x.mp4' }), 'C:\\Users\\me\\exports\\動画 A\\01_x.mp4');
  assert.equal(ctx.clipPathOf({ outDir: '/home/me/exports/' }, { file: 'v/01.mp4' }), '/home/me/exports/v/01.mp4');
  assert.equal(ctx.clipPathOf({ outDir: 'C:\\x' }, { file: 'v/01.mp4', path: 'D:\\clips\\v\\01.mp4' }), 'D:\\clips\\v\\01.mp4');
  assert.equal(ctx.clipPathOf({}, { file: 'v/01.mp4' }), '');          // outDir が分からなければリンクを出さない
  assert.equal(ctx.clipPathOf({ outDir: 'relative/dir' }, { file: 'v/01.mp4' }), '');
  assert.equal(ctx.clipPathOf({ outDir: 'C:\\x' }, { file: null }), '');
});

test('two-step confirmation resets after running (a quick third click does not run again)', () => {
  // 部品は ui-kit の UIKit.confirmTwice の1つ(気が利く画面へ 段1)。review.js の armDelete はそれを呼ぶだけ
  const kit = fs.readFileSync(path.join(__dirname, '..', '..', 'ui-kit', 'ui-kit.js'), 'utf8');
  const a = kit.indexOf('function confirmTwice('), b = kit.indexOf('/* ---- prefs', a);
  assert.ok(a >= 0 && b > a, 'confirmTwice must exist in ui-kit.js');
  assert.ok(between('function armDelete(', 'const statusOf').includes('UIKit.confirmTwice('), 'review.js uses the shared confirmTwice');
  const timers = [];
  const ctx = { setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout: () => {} };
  vm.createContext(ctx); vm.runInContext(kit.slice(a, b) + '\nthis.confirmTwice = confirmTwice;', ctx);
  const cls = new Set(), attrs = {};
  const btn = { innerHTML: '削除', isConnected: true, classList: { add: c => cls.add(c), remove: c => cls.delete(c) },
    getAttribute: k => (k in attrs ? attrs[k] : null), setAttribute: (k, v) => { attrs[k] = String(v); }, removeAttribute: k => { delete attrs[k]; },
    set textContent(v) { this.innerHTML = v; } };
  let runs = 0;
  ctx.confirmTwice(btn, () => runs++, 'もう一度押すと削除');
  assert.equal(runs, 0); assert.ok(cls.has('armed')); assert.equal(btn.innerHTML, 'もう一度押すと削除');
  ctx.confirmTwice(btn, () => runs++);
  assert.equal(runs, 1); assert.equal(btn.innerHTML, '削除'); assert.ok(!cls.has('armed'));
  ctx.confirmTwice(btn, () => runs++);
  assert.equal(runs, 1, 'the third click only arms again');
  timers[timers.length - 1]();   // 3秒たつと元に戻る
  assert.equal(btn.innerHTML, '削除'); assert.ok(!cls.has('armed'));
});

test('transcript lines: escaped text, stale replies ignored, open state kept', async () => {
  const pending = [];
  const S = { cur: { id: 'A', marks: [{ id: 'm1', status: 'exported', path: '/x/a.mp4' }, { id: 'm2', status: 'adopted' }] }, tx: null, txOpen: new Set(['m1']), txSeq: 0 };
  let renders = 0;
  const context = { S, enc: encodeURIComponent, esc: s => String(s).replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';'), fmt: t => 't' + t,
    renderListKeep: () => { renders++; },
    Studio: { api: url => new Promise(resolve => pending.push({ url, resolve })) } };
  vm.createContext(context);
  vm.runInContext(between('function txHTML(', 'function renderList(){'), context);
  const first = context.loadTranscripts();
  assert.equal(pending[0].url, '/api/transcripts?id=A');
  S.cur = { id: 'B', marks: [{ id: 'm1', status: 'exported', path: '/x/b.mp4' }] };   // 返事が来る前に別の動画へ
  const second = context.loadTranscripts();
  const line = { start: 3, end: 4, text: '<img src=x onerror=alert(1)>', speaker: '<b>', cut: true };
  pending[1].resolve({ marks: { m1: { segments: 1, proofed: 0, others: 0, offsetFrom: 'mark', lines: [line] } } });
  await second;
  pending[0].resolve({ marks: { m1: { segments: 9, lines: [] } } });   // 古い返事は捨てる
  await first;
  assert.equal(S.tx.vid, 'B');
  assert.equal(renders, 1);
  const html = context.txHTML({ id: 'm1' });
  assert.ok(!html.includes('<img') && html.includes('&#60;img') && html.includes('rv-tx-spk">&#60;b&#62;</span>'));
  assert.ok(html.includes(' open') && html.includes('rv-tx-line cut') && html.includes('data-t="3"') && html.includes('.clip.json'));
  assert.equal(context.txHTML({ id: 'm9' }), '');
  S.cur = { id: 'C', marks: [{ id: 'm1', status: 'adopted' }] };   // 書き出したマークが無い動画は問い合わせない
  await context.loadTranscripts();
  assert.equal(pending.length, 2);
  assert.equal(S.tx, null);
});

/* ---- 2026-09-26 v0.8.0 画面の全面見直しで足したテスト ---- */
function sliceOf(file, start, end) {
  const src = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
  const a = src.indexOf(start), b = src.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `${file}: application function boundaries must exist (${start})`);
  return src.slice(a, b);
}

test('player unavailable: automatic playback stays silent, an explicit play explains once per press', () => {
  const notes = [], seeks = [];
  const S = { playerAlive: false, playerErr: true, settings: { autoPlay: true }, now: 0 };
  const context = { S, yt: null, toast: m => notes.push(m), seek: t => { seeks.push(t); S.now = t; } };
  vm.createContext(context);
  vm.runInContext(between('const canPlay', 'function phMsg(') + '\n' + between('function togglePlay(', '// iframe内をクリック'), context);
  context.previewClip({ start: 12, end: 20 }, true);   // 前後のマークへ移動したときの自動再生
  context.previewClip({ start: 30, end: 40 }, true);
  assert.deepEqual(notes, []);
  assert.deepEqual(seeks, [12, 30], 'the position still moves to the mark');
  context.previewClip({ start: 50, end: 60 });          // ▶ を押した
  context.togglePlay();                                  // 再生 / 停止
  assert.equal(notes.length, 2);
  assert.ok(notes.every(n => n.includes('再生できません')));
  S.playerErr = false; S.playerAlive = true;
  let played = 0;
  context.yt = { playVideo: () => played++, pauseVideo() {} };
  context.previewClip({ start: 1, end: 2 }, true);
  assert.equal(played, 1);
  assert.equal(S.previewEnd, 2);
});

test('agency checks: untouched agencies follow registration, user choices are kept (rank.js)', () => {
  const store = {};
  const context = { R: { agPick: {} }, lsGet: k => (k in store ? JSON.parse(store[k]) : null) };
  vm.createContext(context);
  vm.runInContext(sliceOf('rank.js', 'const okCount', 'function renderAgChecks(') + '\nthis.agChecked = agChecked;', context);   // const は context に出ないので渡す
  const ag = (id, ok) => ({ id, channels: Array.from({ length: ok }, () => ({ status: 'ok' })).concat([{ status: 'error' }]) });
  assert.equal(context.agChecked(ag('vspo', 0)), false, 'no resolved channel yet: not checked');
  assert.equal(context.agChecked(ag('vspo', 4)), true, 'registered later without touching the check: checked (it was stuck unchecked before)');
  context.R.agPick.nijisanji = false;
  assert.equal(context.agChecked(ag('nijisanji', 4)), false, 'the user unchecked it: stays unchecked');
  context.R.agPick.neoporte = true;
  assert.equal(context.agChecked(ag('neoporte', 0)), true, 'the user checked it: stays checked');
  // v0.7.0 の保存(選んだ ID の配列)は「選んだ」だけ引き継ぐ。空の配列は「全部外した」とは読まない
  context.R.agPick = {}; store.ags = JSON.stringify(['hololive']);
  context.loadAgPick();
  assert.deepEqual({ ...context.R.agPick }, { hololive: true });
  context.R.agPick = {}; store.ags = JSON.stringify([]);
  context.loadAgPick();
  assert.equal(context.agChecked(ag('hololive', 3)), true);
  context.R.agPick = {}; store.agsel = JSON.stringify({ vspo: false, x: 'bad' });
  context.loadAgPick();
  assert.deepEqual({ ...context.R.agPick }, { vspo: false });
});

test('analysis errors are explained as what happened + what to do (queue.js)', () => {
  const context = {};
  vm.createContext(context);
  vm.runInContext(sliceOf('queue.js', 'const ERR_HELP', '/* ---------- キューへ追加'), context);
  const h = m => context.errHelp(m);
  assert.match(h('音声を取得できませんでした: ERROR: [youtube] x: Sign in to confirm your age').what, /年齢制限/);
  assert.match(h('音声を取得できませんでした: HTTP Error 403: Forbidden').how, /yt-dlp/);
  assert.match(h('音声を取得できませんでした: 不明なエラー').how, /数時間/);
  assert.match(h('yt-dlp が見つかりません(README の準備手順を確認してください)').how, /winget install yt-dlp/);
  assert.match(h('ファイルが見つかりません(動画・音声ファイルのパスを指定してください)').what, /見つかりません/);
  assert.match(h('チャットのリプレイが、10分間、出力がなかったため中止しました').what, /止まった/);
  assert.match(h('内部エラー: KeyError x').how, /やり直し/);
  assert.match(h('an image message page usage').what, /解析に失敗/, 'words that merely contain "age" are not taken as an age restriction');
  const d = h('');
  assert.ok(d.what && d.how);
});

/* ---- 2026-10-05 線 D の P3: ライブの録画(kind live)をスタジオの中で ---- */
const plain = x => JSON.parse(JSON.stringify(x));   // vm の中で作った配列・オブジェクトを、この realm の形に(deepStrictEqual は realm の違いも見る)
function liveTime() {
  const ctx = load([['const LT = {', '/* hls.js(入口の']], {});
  vm.runInContext('this.LT = LT;', ctx);
  return ctx.LT;
}
// 4 秒のセグメント。1つ目のセッションが 3 本(0〜12 秒)、繋ぎ直しで 20 秒欠けて、2つ目のセッションが 2 本(受信時刻 32〜40 秒)。
// hls.js のメディアの秒は欠けを詰める(12〜20 秒)
const T0 = Date.UTC(2026, 9, 5, 9, 53, 0);
const FRAGS = [0, 4, 8].map(s => ({ start: s, duration: 4, programDateTime: T0 + s * 1000 }))
  .concat([12, 16].map((s, i) => ({ start: s, duration: 4, programDateTime: T0 + (32 + i * 4) * 1000 })));

test('live player time: seconds from the first segment PDT, across a reconnect gap', () => {
  const LT = liveTime();
  const fr = LT.frags(FRAGS.slice().reverse()), base = LT.base(fr);
  assert.equal(base, T0, 'the base is the first fragment programDateTime');
  assert.equal(LT.timeOf(fr, base, 0), 0);
  assert.equal(LT.timeOf(fr, base, 10.5), 10.5);
  assert.equal(LT.timeOf(fr, base, 12), 32, 'the first media second after the gap is 32 s into the recording');
  assert.equal(LT.timeOf(fr, base, 17), 37);
  assert.equal(LT.mediaOf(fr, base, 37), 17);
  assert.equal(LT.mediaOf(fr, base, 5), 5);
  assert.equal(LT.mediaOf(fr, base, 20), 12, 'a time inside the gap seeks to the head of the next fragment');
  assert.equal(LT.mediaOf(fr, base, -3), 0);
  assert.equal(LT.mediaOf(fr, base, 99), 20, 'after the end: the end of the last fragment');
  assert.equal(LT.durationOf(fr, base), 40, 'duration = end of the last fragment PDT - base (the gap counts)');
  for (const t of [0, 3.3, 11.9, 32, 39.5]) assert.ok(Math.abs(LT.timeOf(fr, base, LT.mediaOf(fr, base, t)) - t) < 1e-9, 'seek and read back give the same time: ' + t);
});

test('live player time: no fragments yet and playlists without PDT do not throw', () => {
  const LT = liveTime();
  assert.equal(LT.base([]), null);
  assert.equal(LT.mediaOf([], null, 10), null);
  assert.equal(LT.durationOf([], null), 0);
  assert.equal(LT.timeOf([], null, 7), 7);
  const fr = LT.frags([{ start: 0, duration: 4 }, { start: 4, duration: 4 }, { start: 8, duration: NaN }, null]);
  assert.equal(fr.length, 2, 'broken fragments are skipped');
  assert.equal(LT.timeOf(fr, LT.base(fr), 5), 5, 'without PDT the media second is the recording second');
});

function liveJobs() {
  return load([['const LIVE_ACTIVE', 'const LV = {'], ['function liveJobView(', '/* 配信を開いたとき(loadVideo)']], {});
}
const job = (id, state, studio, extra) => ({ id, state, recorder: 'local', recording: 'R1', markId: 'lm-1', label: '', start: '', end: '',
  progress: 0, path: '', error: '', message: '', warning: '', created: '2026-10-05T10:00:0' + id.slice(-1) + 'Z', studio, ...extra });

test('portal export jobs are shown in the studio export list shape (wait / fetch / encode n% / done / error)', () => {
  const ctx = liveJobs();
  const jobs = [
    job('lx-3', 'encode', { video: 'V', mark: 'c', start: 30, end: 42 }, { stateLabel: '作り直し中', progress: 0.4, message: '30fps に作り直しています', label: '<b>絶叫</b>' }),
    job('lx-1', 'done', { video: 'V', mark: 'a', start: 1, end: 5 }, { path: 'C:\\clips\\配信\\01_a.mp4', tx: { state: 'done', label: '済み' } }),
    job('lx-2', 'wait', { video: 'V', mark: 'b', start: 10, end: 20 }, { message: '録画が届くのを待っています' }),
    job('lx-4', 'error', { video: 'V', mark: 'd', start: 50, end: 60 }, { error: '区間に欠けがあります' }),
    job('lx-5', 'done', { video: 'OTHER', mark: 'z', start: 0, end: 1 }),
    job('lx-6', 'done', null),
  ];
  const v = ctx.liveJobView('V', jobs);
  assert.equal(v.id, 'live:V');
  assert.equal(v.live, true);
  assert.equal(v.state, 'running', 'running while any job is waiting / fetching / encoding');
  assert.deepEqual(plain(v.items.map(i => i.jobId)), ['lx-1', 'lx-2', 'lx-3', 'lx-4'], 'only this video, oldest first (numbers do not move)');
  assert.deepEqual(plain(v.items.map(i => i.status)), ['done', 'queued', 'running', 'error']);
  assert.deepEqual(plain(v.items.map(i => i.stateLabel)), ['済み', '録画待ち', '作り直し中', '失敗']);
  const [a, b, c, d] = v.items;
  assert.equal(a.id, 'a'); assert.equal(a.start, 1); assert.equal(a.end, 5);
  assert.equal(a.path, 'C:\\clips\\配信\\01_a.mp4'); assert.equal(a.file, '01_a.mp4'); assert.equal(a.message, '', 'no progress message once done');
  assert.equal(a.tx.label, '済み');
  assert.equal(b.message, '録画が届くのを待っています');
  assert.equal(c.progress, 0.4); assert.equal(c.title, '<b>絶叫</b>', 'text is passed through as data (jobItemHTML escapes it)');
  assert.equal(d.error, '区間に欠けがあります');
  assert.equal(ctx.liveJobView('V', [jobs[1]]).state, 'done');
  assert.deepEqual(plain(ctx.liveJobView('V', null).items), []);
});

test('portal export rows: escaped text, cancel button only while active, "編集で開く" when done', () => {
  const ctx = load([['const EXP_LABEL', 'function errHint('], ['function jobItemHTML(', 'function renderJob(j){']], {
    fmt: t => 't' + t, esc: s => String(s).replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';'),
    handoffHTML: (j, it) => (it.status === 'done' && it.path ? '<a>編集で開く</a>' : ''), loudHTML: () => '' });
  const j = { live: true };
  const run = ctx.jobItemHTML(j, { jobId: 'lx-3', start: 30, end: 42, title: '<b>x</b>', status: 'running', stateLabel: '作り直し中', progress: 0.4, message: '<i>m</i>' }, 0);
  assert.ok(run.includes('作り直し中 40%') && run.includes('data-act="lxcancel"') && run.includes('data-job="lx-3"'));
  assert.ok(!run.includes('<b>x</b>') && !run.includes('<i>m</i>'), 'title and message are escaped');
  const wait = ctx.jobItemHTML(j, { jobId: 'lx-2', start: 1, end: 2, status: 'queued', stateLabel: '録画待ち', message: '録画が届くのを待っています' }, 1);
  assert.ok(wait.includes('録画待ち') && wait.includes('録画が届くのを待っています') && wait.includes('lxcancel'));
  const done = ctx.jobItemHTML(j, { jobId: 'lx-1', start: 1, end: 2, status: 'done', stateLabel: '済み', path: 'C:\\a.mp4', file: 'a.mp4', tx: { state: 'done', label: '済み' } }, 2);
  assert.ok(done.includes('編集で開く') && done.includes('文字起こし: 済み') && !done.includes('lxcancel'));
  const studio = ctx.jobItemHTML({}, { start: 1, end: 2, status: 'running', progress: 0.5 }, 0);
  assert.ok(studio.includes('処理中 50%') && !studio.includes('lxcancel'), 'studio export rows are unchanged');
});

test('finished portal jobs mark the studio mark as exported only when the times still match', () => {
  const ctx = liveJobs();
  const marks = [
    { id: 'a', start: 1, end: 5, status: 'adopted' },      // 済み・時刻が同じ → 書き出し済みにする
    { id: 'b', start: 12, end: 20, status: 'adopted' },    // 位置を直した(ジョブは 10〜20)→ しない(もう一度書き出すまで)
    { id: 'c', start: 30, end: 42, status: 'exported' },   // もう書き出し済み → しない
    { id: 'd', start: 50, end: 60, status: '' },            // 候補(閉じていた間に済んだ)→ する
    { id: 'e', start: 70, end: 80, status: 'rejected' },   // 不採用にした → しない
  ];
  const jobs = [
    job('lx-1', 'done', { video: 'V', mark: 'a', start: 1, end: 5 }, { path: 'C:\\c\\a_old.mp4', updated: '2026-10-05T10:00:00Z' }),
    job('lx-7', 'done', { video: 'V', mark: 'a', start: 1.02, end: 5 }, { path: 'C:\\c\\a_new.mp4', updated: '2026-10-05T10:05:00Z' }),
    job('lx-2', 'done', { video: 'V', mark: 'b', start: 10, end: 20 }, { path: 'C:\\c\\b.mp4' }),
    job('lx-3', 'done', { video: 'V', mark: 'c', start: 30, end: 42 }, { path: 'C:\\c\\c.mp4' }),
    job('lx-4', 'done', { video: 'V', mark: 'd', start: 50, end: 60 }, { path: 'C:\\c\\d.mp4' }),
    job('lx-5', 'done', { video: 'V', mark: 'e', start: 70, end: 80 }, { path: 'C:\\c\\e.mp4' }),
    job('lx-6', 'encode', { video: 'V', mark: 'd', start: 50, end: 60 }),
    job('lx-8', 'done', { video: 'V', mark: 'gone', start: 0, end: 1 }, { path: 'C:\\c\\x.mp4' }),
    job('lx-9', 'done', { video: 'V', mark: 'a', start: 1, end: 5 }),   // path が無い済みは使わない
  ];
  const todo = ctx.liveReconcile(marks, jobs, new Set());
  assert.deepEqual(plain(todo.map(t => [t.markId, t.path, t.jobId]).sort()), [['a', 'C:\\c\\a_new.mp4', 'lx-7'], ['d', 'C:\\c\\d.mp4', 'lx-4']]);
  assert.deepEqual(plain(ctx.liveReconcile(marks, jobs, new Set(['lx-7', 'lx-4'])).map(t => t.jobId)), ['lx-1'], 'already applied jobs are not sent again');
  assert.deepEqual(plain(ctx.liveReconcile([], jobs, null)), []);
});

test('live export: one portal request per mark, saved first, busy marks skipped, failures released', async () => {
  const calls = [], notes = [];
  const v = { id: 'V', kind: 'live', title: '配信', live: { recorder: 'local', recording: 'R1', url: 'https://youtu.be/x' },
    marks: [{ id: 'a', start: 1, end: 5, status: 'adopted', label: 'A' }, { id: 'b', start: 10, end: 20, status: 'adopted', label: '' }, { id: 'c', start: 30, end: 40, status: 'adopted' }] };
  const S = { cur: v, settings: { exportTarget: 'adopted' } };
  const LV = { busy: new Set(['c']), queued: new Set(), chain: Promise.resolve(), starting: false };
  let saved = 0, polled = 0;
  const ctx = load([['function liveExportBody(', '/* ヘッダーの札の「開く」']], {
    S, LV, Studio: { token: 't', live: { api: async (rest, o) => { calls.push({ rest, body: o.body }); if (o.body.studio.mark === 'b') { const e = new Error('このマークは書き出しの途中です'); e.status = 409; throw e; } return { job: {} }; } } },
    toast: m => notes.push(m), flushSave: async () => { saved++; }, renderExportUI() {}, liveResume() {}, pollLiveJobs: async () => { polled++; },
    sortedMarks: () => v.marks.slice().sort((x, y) => x.start - y.start), exportTargets: () => v.marks.filter(m => m.status === 'adopted'), autoTxEnabled: () => true });
  await ctx.startLiveExport();
  assert.equal(saved, 1, 'the studio marks are saved before asking the portal');
  assert.deepEqual(calls.map(c => c.rest), ['api/export', 'api/export'], 'the mark already being exported (c) is not sent again');
  assert.deepEqual(plain(calls[0].body), { recorder: 'local', recording: 'R1', title: '配信', url: 'https://youtu.be/x', transcribe: true,
    studio: { video: 'V', mark: 'a', n: 1, label: 'A', start: 1, end: 5 } });
  assert.equal(calls[1].body.studio.n, 2);
  assert.ok(notes.at(-1).includes('書き出しの途中です'));
  assert.equal(LV.queued.size, 0); assert.equal(LV.starting, false);
  assert.ok(LV.busy.has('a') && !LV.busy.has('b'), 'only the mark that could not be sent is released (it can be exported again right away)');
  assert.equal(polled, 1);
});

test('live videos: studio export goes to the portal, autorun / join / all-video export leave live out', () => {
  const exp = between('async function startExport(', 'async function startExportAll(');
  assert.ok(exp.indexOf("S.cur.kind === 'live'") < exp.indexOf('S.starting'), 'the live branch comes before the "already exporting" guard');
  assert.ok(exp.includes('startLiveExport(onlyIds)'));
  assert.ok(between('async function startExportAll(', 'async function resumeJob(').includes("x.kind !== 'live'"));
  assert.ok(!between('function startLiveExport(', '/* ヘッダーの札の「開く」').includes('maybeAutoTranscribe'), 'the portal export hands off to transcription itself');
  assert.ok(between('function pushMark(', '/* サーバーと同じ規則').includes('startLiveExport(new Set([m.id]), { auto: true })'));
  assert.ok(source.includes('enableWorker: false'), 'hls.js runs without a Web Worker (no worker-src in the CSP)');
});
