// Run: node --test tests/app/test_cand_panel.cjs
// Exercise real save/navigation/export functions with delayed and failed API replies.
// 案件の画面の候補のパネル(panels/cand.js)の中身 = スタジオの部品 src/app/ui/studio/review.js を切り出して試す。
// 新しい案件の引き出し(panels/new.js)が読む src/app/ui/studio/rank.js・queue.js の小さな確かめと、2 つのパネルが渡す window.Studio の代わりもここ。
// 残すのは画面の通し(e2e_cases_cand・e2e_live_studio・e2e_live_archive)で起こしにくい物だけ: 遅れて届いた答え・二重押し・失敗の答え・時計・計算・危ない文字
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
// UIKit の代わり。切り出した関数が UIKit を直接呼んでも動くように、vm の context にはいつも withUIKit(context) を通す
// (context.UIKit・context.window.UIKit。テストが自分で入れた UIKit / window.UIKit はそのまま)。呼ばれた部品は context.UIKit.called('toast') などで読める
const { makeUIKit, withUIKit } = require(path.join(__dirname, '..', 'ui-kit', 'uikit_stub.cjs'));
const SRC = path.join(__dirname, '..', '..', 'src');
const source = fs.readFileSync(path.join(SRC, 'app', 'ui', 'studio', 'review.js'), 'utf8').replace(/\r\n/g, '\n');   // 作業フォルダが CRLF でも同じに切り出す
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
  for (const name of ['refreshList', 'refreshListQuiet', 'renderExportUI',
    'renderTimeline', 'renderStats', 'renderMeta', 'renderLiveCount', 'renderList',
    'renderListKeep', 'renderAll', 'setNow', 'mountPlayer', 'fetchAutoTitle', 'syncFromServer', 'loadTranscripts', 'pollAuto',
    // loadVideo・startExportAll は typeof で確かめずに呼ぶ(前回の場所・ライブの録画・配信者の欄・書き出しの欄・書き出しのあとの文字起こし)
    'placeOf', 'placeScroll', 'liveOpened', 'fillAutoWho', 'syncExportDock', 'maybeAutoTranscribe']) context[name] = () => {};   // pollAuto: まとめて実行の進み具合(⑦)
  vm.createContext(withUIKit(context));
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

/* ---- マークの移動・書き出したファイル・二度押し・セリフ ---- */
function load(parts, extra) {
  const context = withUIKit({ Map, Set, Error, ...extra });
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
  // 部品は ui-kit の UIKit.confirmTwice。review.js の armDelete はそれを呼ぶだけ(1 回目の確認だけは e2e_portal の終了ボタンが見る)
  const kit = fs.readFileSync(path.join(SRC, 'ui-kit', 'ui-kit.js'), 'utf8');
  const a = kit.indexOf('function confirmTwice('), b = kit.indexOf('/* ---- prefs', a);
  assert.ok(a >= 0 && b > a, 'confirmTwice must exist in ui-kit.js');
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
  vm.createContext(withUIKit(context));
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
  assert.ok(html.includes(' open') && html.includes('rv-tx-line cut') && html.includes('切り抜きの記録が見つからない'));
  assert.equal(context.txHTML({ id: 'm9' }), '');
  S.cur = { id: 'C', marks: [{ id: 'm1', status: 'adopted' }] };   // 書き出したマークが無い動画は問い合わせない
  await context.loadTranscripts();
  assert.equal(pending.length, 2);
  assert.equal(S.tx, null);
});

/* ---- プレーヤーが使えないとき・事務所の選び方・解析の失敗の案内 ---- */
/* file: 'rank.js' など名前だけならスタジオの画面の部品のフォルダ(src/app/ui/studio/)、'app/ui/cases/panels/cand.js' のように / を含めば src/ から */
function sliceOf(file, start, end) {
  const src = fs.readFileSync(path.join(SRC, file.includes('/') ? file : path.join('app', 'ui', 'studio', file)), 'utf8').replace(/\r\n/g, '\n');   // 作業フォルダが CRLF でも、'\n' を含む切り出しの印が当たるように
  const a = src.indexOf(start), b = src.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `${file}: application function boundaries must exist (${start})`);
  return src.slice(a, b);
}

test('player unavailable: automatic playback stays silent, an explicit play explains once per press', () => {
  const notes = [], seeks = [];
  const S = { playerAlive: false, playerErr: true, settings: { autoPlay: true }, now: 0 };
  const context = { S, yt: null, toast: m => notes.push(m), seek: t => { seeks.push(t); S.now = t; } };
  vm.createContext(withUIKit(context));
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

test('agency checks: untouched = hololive only when it has resolved channels, user choices are kept (rank.js)', () => {
  const store = {};
  const context = { R: { agPick: {} }, lsGet: k => (k in store ? JSON.parse(store[k]) : null) };
  vm.createContext(withUIKit(context));
  vm.runInContext(sliceOf('rank.js', 'const okCount', 'function renderAgChecks(') + '\nthis.agChecked = agChecked;', context);   // const は context に出ないので渡す
  const ag = (id, n) => ({ id, n });   // 事務所の選び方は「ホロライブ / その他」の 2 つ。n = 解決済みのチャンネルの数
  assert.equal(context.agChecked(ag('hololive', 0)), false, 'no resolved channel yet: not checked');
  assert.equal(context.agChecked(ag('hololive', 4)), true, 'registered later without touching the check: checked');
  assert.equal(context.agChecked(ag('other', 4)), false, 'other is off unless the user checks it');
  context.R.agPick.hololive = false;
  assert.equal(context.agChecked(ag('hololive', 4)), false, 'the user unchecked it: stays unchecked');
  context.R.agPick.other = true;
  assert.equal(context.agChecked(ag('other', 0)), true, 'the user checked it: stays checked');
  // 前の形の保存(選んだ ID の配列)は「選んだ」だけ引き継ぐ。空の配列は「全部外した」とは読まない
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
  vm.createContext(withUIKit(context));
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

/* ---- ライブの録画(kind live)の再生位置・書き出しの行 ---- */
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
  const ctx = load([['const fileLabel', 'function errHint('], ['function jobItemHTML(', 'function renderJob(j){']], {
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
  assert.ok(studio.includes('50%') && !studio.includes('lxcancel'), 'studio export rows: progress, no portal cancel button');
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
    sortedMarks: () => v.marks.slice().sort((x, y) => x.start - y.start), exportTargets: () => v.marks.filter(m => m.status === 'adopted'), autoTxEnabled: () => true,
    LIVE_AFTERS: ['none', 'auto'], liveWhoName: () => '兎田ぺこら' });
  await ctx.startLiveExport();
  assert.equal(saved, 1, 'the studio marks are saved before asking the portal');
  assert.deepEqual(calls.map(c => c.rest), ['api/export', 'api/export'], 'the mark already being exported (c) is not sent again');
  assert.deepEqual(plain(calls[0].body), { recorder: 'local', recording: 'R1', title: '配信', url: 'https://youtu.be/x', after: 'auto', transcribe: true,
    streamer: '兎田ぺこら', studio: { video: 'V', mark: 'a', n: 1, label: 'A', start: 1, end: 5 } });   // 設定が無い = 全自動
  assert.equal(calls[1].body.studio.n, 2);
  assert.ok(notes.at(-1).includes('書き出しの途中です'));
  assert.equal(LV.queued.size, 0); assert.equal(LV.starting, false);
  assert.ok(LV.busy.has('a') && !LV.busy.has('b'), 'only the mark that could not be sent is released (it can be exported again right away)');
  assert.equal(polled, 1);
});

// ---- アーカイブから書き出す(書き出しの行・帯の 1 行・録画を消したとき) ----
const arch = (state, extra) => ({ state, label: '', message: '', progress: 0, ...extra });

test('archive state of portal jobs is shown on the export rows (label, progress, 本番版 chip, reason)', () => {
  const ctx = liveJobs();
  const jobs = [
    job('lx-1', 'done', { video: 'V', mark: 'a', start: 1, end: 5 }, { path: 'C:\\c\\a.mp4', archive: arch('done', { label: '本番版に入れ替えました' }) }),
    job('lx-2', 'done', { video: 'V', mark: 'b', start: 10, end: 20 }, { path: 'C:\\c\\b.mp4', archive: arch('align', { label: '照合中', progress: 0.25 }) }),
    job('lx-3', 'error', { video: 'V', mark: 'c', start: 30, end: 40 }, { error: '区間に欠けがあります', needsArchive: true, archive: arch('error', { message: '<b>メンバー限定</b>' }) }),
    job('lx-4', 'done', { video: 'V', mark: 'd', start: 50, end: 60 }, { path: 'C:\\c\\d.mp4' }),
    job('lx-5', 'done', { video: 'V', mark: 'e', start: 70, end: 80 }, { path: 'C:\\c\\e.mp4', archive: { label: 'x' } }),
  ];
  const items = ctx.liveJobView('V', jobs).items;
  assert.deepEqual(plain(items.map(i => i.archive && [i.archive.state, i.archive.label, i.archive.active])),
    [['done', '本番版に入れ替えました', false], ['align', '照合中', true], ['error', '失敗', false], null, null], 'missing label falls back to the studio words; no state = no archive');
  assert.equal(items[1].archive.progress, 0.25);
  assert.equal(items[2].needsArchive, true); assert.equal(items[0].needsArchive, false);
  assert.equal(ctx.liveArchView(arch('fetch', { progress: 7 })).progress, 1, 'progress is clamped to 0..1');

  const esc = s => String(s).replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');
  const html = load([['const fileLabel', 'function errHint('], ['function jobItemHTML(', 'function renderJob(j){']], {
    fmt: t => 't' + t, esc, handoffHTML: () => '', loudHTML: () => '', ARCH_TITLE: 'アーカイブから作り直して、速報版と入れ替えました' });
  const row = (it, i) => html.jobItemHTML({ live: true }, it, i);
  const done = row(items[0], 0);
  assert.ok(done.includes('rv-chip arch') && done.includes('>アーカイブ<') && done.includes('アーカイブから作り直して'), 'done: アーカイブ chip with the explanation');
  const run = row(items[1], 1);
  assert.ok(run.includes('アーカイブから: 照合中 25%') && !run.includes('rv-chip arch'));
  const err = row(items[2], 2);
  assert.ok(err.includes('アーカイブから書き出せませんでした: &#60;b&#62;メンバー限定') && !err.includes('<b>'), 'the reason is escaped');
  assert.ok(err.includes('帯の「アーカイブから書き出す」') && !err.includes('「書き出す」でやり直せます'), 'gap errors point to the archive');
  const plainRow = row(items[3], 3);
  assert.ok(!plainRow.includes('アーカイブ'), 'no archive = no line');
  assert.ok(row({ ...items[3], archive: ctx.liveArchView(arch('cancelled')) }, 3).includes('取り消しました'));
  assert.equal(row(items[1], 1), row(items[1], 1), 'the same state gives the same HTML (rows are not rebuilt by the poll)');
});

test('reconcile: archived jobs mark exported marks as 本番版 once; adopted marks get both at once', () => {
  const ctx = liveJobs();
  const marks = [
    { id: 'a', start: 1, end: 5, status: 'exported' },                    // 速報版で書き出し済み → 本番版の札を付ける
    { id: 'b', start: 10, end: 20, status: 'exported', archived: true },  // もう本番版 → しない
    { id: 'c', start: 30, end: 40, status: 'adopted' },                   // 欠けで書き出せなかった → 作り直しで済んだ: 書き出し済み + 本番版
    { id: 'd', start: 50, end: 60, status: 'exported' },                  // 速報版のまま(作り直し中)→ しない
    { id: 'e', start: 72, end: 80, status: 'exported' },                  // 位置を直した(ジョブは 70〜80)→ しない
    { id: 'f', start: 90, end: 95, status: 'adopted' },                   // 速報版がいま済んだ → 書き出し済みだけ
  ];
  const jobs = [
    job('lx-1', 'done', { video: 'V', mark: 'a', start: 1, end: 5 }, { path: 'C:\\c\\a.mp4', archive: arch('done') }),
    job('lx-2', 'done', { video: 'V', mark: 'b', start: 10, end: 20 }, { path: 'C:\\c\\b.mp4', archive: arch('done') }),
    job('lx-3', 'done', { video: 'V', mark: 'c', start: 30, end: 40 }, { path: 'C:\\c\\c.mp4', needsArchive: true, archive: arch('done') }),
    job('lx-4', 'done', { video: 'V', mark: 'd', start: 50, end: 60 }, { path: 'C:\\c\\d.mp4', archive: arch('fetch') }),
    job('lx-5', 'done', { video: 'V', mark: 'e', start: 70, end: 80 }, { path: 'C:\\c\\e.mp4', archive: arch('done') }),
    job('lx-6', 'done', { video: 'V', mark: 'f', start: 90, end: 95 }, { path: 'C:\\c\\f.mp4' }),
  ];
  const todo = plain(ctx.liveReconcile(marks, jobs, new Set()));
  assert.deepEqual(todo.map(t => [t.markId, t.jobId, t.archived]).sort(), [['a', 'lx-1', true], ['c', 'lx-3', true], ['f', 'lx-6', false]]);
  assert.deepEqual(todo.map(t => t.key).sort(), ['lx-1#archive', 'lx-3#archive', 'lx-6']);
  // 速報版のときに送った(lx-1)あとで本番版になった: 別の印なので、もう一度送る
  assert.deepEqual(plain(ctx.liveReconcile(marks, jobs, new Set(['lx-1', 'lx-6'])).map(t => t.jobId)).sort(), ['lx-1', 'lx-3']);
  assert.deepEqual(plain(ctx.liveReconcile(marks, jobs, new Set(['lx-1#archive', 'lx-3#archive', 'lx-6']))), [], 'sent ones are not sent again in this opening');
});

test('the band line for exporting from the archive (progress, not ready, done, failed, nothing to do)', () => {
  const ctx = liveJobs();
  const o = { videoId: 'abcdefghijk', known: true };
  const J = (id, mark, state, a, extra) => job(id, state, { video: 'V', mark, start: 0, end: 1 }, { path: state === 'done' ? 'C:\\c\\' + mark + '.mp4' : '', archive: a, ...extra });
  const M = ['a', 'b', 'c', 'd', 'e'];
  // 対象 = 録画に無い区間で書き出せなかった(error + needsArchive)か、配信後の採用で待っている(wait + from archive)か、アーカイブから書き出し済み
  const pend = () => M.map((m, i) => J('lx-' + i, m, 'error', undefined, { needsArchive: true }));
  const run = st => M.map((m, i) => i < 2 ? J('lx-' + i, m, 'done', arch('done')) : J('lx-' + i, m, 'wait', st(i), { from: 'archive' }));
  let s = ctx.liveArchSummary(run(i => i === 2 ? arch('align', { label: '照合中' }) : arch('wait')), null, o);
  assert.equal(s.text, 'アーカイブから書き出しています 2/5 本(照合中)');
  assert.equal(s.running, true); assert.equal(s.can, false);
  s = ctx.liveArchSummary(M.map((m, i) => J('lx-' + i, m, 'done', arch('done'))), null, o);
  assert.equal(s.text, 'アーカイブから書き出しました 5/5 本');
  assert.equal(s.can, false); assert.equal(s.why, 'すべてアーカイブから書き出しました');
  s = ctx.liveArchSummary(pend(), { ready: false, message: 'post_live' }, o);
  assert.equal(s.text, 'アーカイブがまだ用意できていません(自動で確かめ直します)');
  assert.equal(s.can, true, 'the user may still try (the portal answers 409 with the reason)');
  s = ctx.liveArchSummary(M.map((m, i) => i < 2 ? J('lx-' + i, m, 'done', arch('done')) : J('lx-' + i, m, 'error', arch('error', { message: '配信者がアーカイブを切り貼りしています' }), { needsArchive: true })), { ready: true }, o);
  assert.equal(s.text, 'アーカイブから書き出しました 2/5 本。3 本はアーカイブから書き出せませんでした: 配信者がアーカイブを切り貼りしています');
  assert.equal(s.warn, true); assert.equal(s.can, true, 'failed ones can be tried again');
  s = ctx.liveArchSummary(pend(), null, { ...o, msg: 'アーカイブがまだ用意できていません(配信が終わったばかりです)' });
  assert.equal(s.text, 'アーカイブがまだ用意できていません(配信が終わったばかりです)', 'the 409 message is shown as is');
  // 対象: マークごとの最新のジョブで、欠けで書き出せなかった物・待っている物・アーカイブから書き出し済みの物(keep ありは数えない)
  const mixed = [J('lx-1', 'a', 'error', undefined, { created: '2026-10-05T10:00:01Z' }), J('lx-2', 'a', 'done', undefined, { created: '2026-10-05T10:00:02Z' }),
    J('lx-3', 'b', 'error', undefined, { needsArchive: true }), J('lx-4', 'c', 'error'), J('lx-5', 'd', 'encode'), J('lx-6', 'e', 'cancelled'),
    J('lx-7', 'f', 'done', arch('done')), J('lx-8', 'g', 'done', arch('done', { keep: true }))];
  assert.deepEqual(plain(ctx.liveArchTargets(mixed).map(j => j.id)).sort(), ['lx-3', 'lx-7']);
  s = ctx.liveArchSummary([J('lx-4', 'c', 'error'), J('lx-5', 'd', 'encode')], null, o);
  assert.equal(s.can, false); assert.ok(s.why.includes('録画に無い区間のマークがありません')); assert.equal(s.text, '');
  s = ctx.liveArchSummary(pend(), null, { ...o, videoId: '' });
  assert.equal(s.can, false); assert.ok(s.text.includes('YouTube の動画が分からない'));
  assert.equal(ctx.liveArchSummary(pend(), null, { ...o, known: false }).can, false, 'not before the job list is read');
  assert.equal(ctx.liveArchSummary(pend(), null, { ...o, starting: true }).can, false, 'no double press');
});

test('a recording deleted by the portal (auto delete) is told apart from a missing one; old Resolve packs are pointed out', () => {
  const ctx = liveJobs();
  const e404 = { status: 404, message: 'その録画はありません' }, e502 = { status: 502, message: 'x' };
  const jd = [job('lx-1', 'done', { video: 'V', mark: 'a', start: 0, end: 1 }, { archive: arch('done'), recordingDeleted: '2026-10-05T12:00:00Z' })];
  const jn = [job('lx-1', 'done', { video: 'V', mark: 'a', start: 0, end: 1 }, { archive: arch('done') })];
  assert.equal(ctx.liveRecDeleted(e404, jd, []), true, 'the portal says it deleted the recording');
  assert.equal(ctx.liveRecDeleted(e502, jd, []), false, 'only when the status is 404');
  assert.equal(ctx.liveRecDeleted(null, jd, []), false);
  assert.equal(ctx.liveRecDeleted(e404, jn, [{ status: 'exported', archived: true }, { status: 'rejected' }]), true, 'all exported marks are 本番版 (job record trimmed)');
  assert.equal(ctx.liveRecDeleted(e404, jn, [{ status: 'exported', archived: true }, { status: 'exported' }]), false, 'a mark is not 本番版 = deleted by hand: 見つかりません');
  assert.equal(ctx.liveRecDeleted(e404, [], []), false, 'no marks, no record: 見つかりません');
  // 前に作ったパックが速報版のまま(ホームの archive.packOld): 書き出しの行にだけ出す(帯の 1 行には出さない)
  const J = (id, mark, a) => job(id, 'done', { video: 'V', mark, start: 0, end: 1 }, { path: 'C:\\c\\' + mark + '.mp4', archive: a });
  const s = ctx.liveArchSummary([J('lx-1', 'a', arch('done', { packOld: true })), J('lx-2', 'b', arch('done'))], null, { videoId: 'abcdefghijk', known: true });
  assert.equal(s.text, 'アーカイブから書き出しました 2/2 本', 'the band has no old-pack line');
  assert.equal(ctx.liveArchView(arch('done', { packOld: true })).packOld, true);
  assert.equal(ctx.liveArchView(arch('error', { packOld: true })).packOld, false);
  const esc = x => String(x).replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');
  const html = load([['const fileLabel', 'function errHint('], ['function jobItemHTML(', 'function renderJob(j){']], {
    fmt: t => 't' + t, esc, handoffHTML: () => '', loudHTML: () => '', ARCH_TITLE: 't' });
  const it = { id: 'a', start: 0, end: 1, title: '', status: 'done', stateLabel: '済み', progress: 1, path: 'C:\\c\\a.mp4', file: 'a.mp4', archive: ctx.liveArchView(arch('done', { packOld: true })) };
  const row = html.jobItemHTML({ live: true }, it, 0);
  assert.ok(row.includes('>アーカイブ<') && row.includes('前に作ったパックは速報版のまま'), row);
  assert.ok(!html.jobItemHTML({ live: true }, { ...it, archive: ctx.liveArchView(arch('done')) }, 0).includes('速報版のまま'));
});

test('the band line for the after-stream auto clipping: the portal text as is, warn on failures, poll sooner while it moves', () => {
  const ctx = liveJobs();
  const view = a => plain(ctx.liveAfterView(a === undefined ? null : { ready: true, afterStream: a }));
  assert.deepEqual(view(), { text: '', warn: false, running: false });
  assert.deepEqual(plain(ctx.liveAfterView({ ready: true })), { text: '', warn: false, running: false }, 'no afterStream (the setting is off)');
  const p = (o) => ({ total: 3, exported: 3, archived: 3, handed: 3, finished: 0, failed: 0, ...o });
  let v = view({ state: 'analyze', label: 'アーカイブを解析しています', text: '配信後の自動の切り抜き: アーカイブを解析しています(アーカイブを解析しています(scan 40%))' });
  assert.equal(v.text, '配信後の自動の切り抜き: アーカイブを解析しています(アーカイブを解析しています(scan 40%))');
  assert.equal(v.running, true); assert.equal(v.warn, false);
  v = view({ state: 'done', text: '配信後の自動の切り抜き: 済み(3 本のうち …)', progress: p({ finished: 1 }) });
  assert.equal(v.running, true, 'handed to the batch run but not packed yet');
  v = view({ state: 'done', text: 'x', progress: p({ finished: 2, failed: 1 }) });
  assert.equal(v.running, false); assert.equal(v.warn, true, 'a failure is shown in the warn color');
  assert.equal(view({ state: 'error', text: '配信後の自動の切り抜き: 失敗(…)' }).warn, true);
  assert.equal(view({ state: 'error', text: 'x' }).running, false);
  assert.equal(view({ state: 'none', text: 'x' }).running, false);
  assert.equal(view({ state: 'wait', text: 5 }).text, '', 'only a string is shown');
});

// ---- 書き出したあと(after)と自動の文字起こし(autoTx)・前回の場所・書き出し完了の [編集で開く]・押せない理由 ----
test('live after: the saved choice wins, else it follows autoTx; autoTx lives in the server settings and the old browser value is taken over once', () => {
  let legacy = null;
  const ctx = load([['const LIVE_AFTERS', '/* ---------- 状態 ---------- */']], { autoTxLegacy: () => legacy, sec1: (v, d) => d, sanitizeKeymap: () => ({}), KEY_PRESETS: { standard: {} }, DEFAULT_QUICK_SPANS: [30, 60, 120, 180, 300] });
  assert.equal(ctx.sanitizeSettings({}).liveAfter, 'auto');
  assert.equal(ctx.sanitizeSettings({ autoTx: false }).liveAfter, 'none');
  assert.equal(ctx.sanitizeSettings({ autoTx: false, liveAfter: 'auto' }).liveAfter, 'auto');
  assert.equal(ctx.sanitizeSettings({ autoTx: false, liveAfter: 'auto' }).liveAfter, 'auto', 'a saved choice is kept even when autoTx is off');
  assert.equal(ctx.sanitizeSettings({ autoTx: false, liveAfter: 'check' }).liveAfter, 'auto', 'the removed transcribe-only choice is read as full auto');
  assert.equal(ctx.sanitizeSettings({ autoTx: false, liveAfter: 'full' }).liveAfter, 'none', 'unknown values fall back');
  assert.equal(ctx.sanitizeSettings({}).autoTx, true, 'default on');
  legacy = false;
  assert.equal(ctx.sanitizeSettings({}).autoTx, false, 'nothing on the server yet: the old localStorage value');
  assert.equal(ctx.sanitizeSettings({}).liveAfter, 'none');
  assert.equal(ctx.sanitizeSettings({ autoTx: true }).autoTx, true, 'once on the server, the server wins');
  assert.equal(ctx.sanitizeSettings({ autoTx: 'no' }).autoTx, false, 'a broken value falls back to the old value / default');
  const load2 = between('async function loadSettings(', 'function syncSettingsUI(');
  assert.ok(load2.includes("typeof raw.autoTx === 'boolean'") && load2.includes('autoTxLegacy() !== null') && load2.includes('touchSettings()'), 'loadSettings sends the old value to the server once');
  // the switch is on the settings page (home /settings → review.autoTx); the panel's "settings" goes to that page
  const open = sliceOf('app/ui/cases/panels/cand.js', 'openSettings:', 'enqueue:');
  assert.ok(open.includes("homeUrl('settings')") && open.includes('#sec-studio') && !open.includes('localStorage'), 'the panel opens the studio section of the settings page');
});

function placeHarness(store) {
  const timers = [];
  const S = { cur: null, now: 0, sel: null };
  const ctx = load([['const PLACE_KEY', '/* 戻した選択の行を']], {
    S, JSON, Math, Number, Object, Array, Date,
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
    setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout: () => {} });
  return { ctx, S, timers, read: () => JSON.parse(store['ytt:studio.place'] || '{}') };
}

test('the place in each stream: position and the selected mark are remembered per stream and given back', () => {
  const store = {};
  const h = placeHarness(store);
  const A = { id: 'A', duration: 100, marks: [{ id: 'm1' }, { id: 'm2' }] }, B = { id: 'B', duration: 0, marks: [] };
  assert.equal(h.ctx.placeOf(A), null, 'nothing remembered yet');
  h.S.cur = A; h.S.now = 12.34; h.S.sel = 'm2';
  h.ctx.placeNote();
  assert.equal(h.timers.length, 1, 'written a little later (not on every 0.1 s tick)');
  h.S.now = 15.06; h.ctx.placeNote();
  assert.equal(h.timers.length, 1, 'one pending write at a time');
  h.ctx.placeFlush();
  assert.deepEqual(h.read().A.slice(0, 2), [15.1, 'm2']);
  h.S.cur = B; h.S.now = 3; h.S.sel = null;
  h.ctx.placeNote();   // another stream: the pending one is written first, then this one waits
  h.ctx.placeFlush();
  assert.deepEqual(h.read().B.slice(0, 2), [3, '']);
  assert.deepEqual(JSON.parse(JSON.stringify(h.ctx.placeOf(A))), { t: 15.1, sel: 'm2' });
  assert.deepEqual(JSON.parse(JSON.stringify(h.ctx.placeOf({ ...A, duration: 10, marks: [{ id: 'm1' }] }))), { t: 10, sel: null }, 'a deleted mark is not selected; the position stays inside the stream');
  store['ytt:studio.place'] = 'not json';
  assert.equal(h.ctx.placeOf(A), null, 'a broken value is ignored');
  const many = {};
  for (let i = 0; i < 205; i++) many['v' + i] = [1, '', i];
  store['ytt:studio.place'] = JSON.stringify(many);
  h.S.cur = { id: 'new' }; h.S.now = 5; h.ctx.placeNote(); h.ctx.placeFlush();
  const kept = h.read();
  assert.equal(Object.keys(kept).length, 200, 'at most 200 streams');
  assert.ok(kept.new && !kept.v0 && kept.v204, 'the oldest are dropped first');
});

// 開き直したときの再生位置(見回りが 0 に戻さない)は e2e_cases_cand の 7 が見る。ここは選んだマークと、プレーヤーの準備前の表示
test('opening a stream gives back the place (selected mark and the position the player is moved to)', async () => {
  const h = harness(async () => ({ video: video('B', 3) }));
  h.S.dirty = false;
  const at = [];
  h.context.setNow = t => at.push(t);
  h.context.placeOf = v => (v.id === 'B' ? { t: 42.5, sel: 'm2' } : null);
  assert.equal(await h.context.loadVideo('B'), true);
  assert.equal(h.S.sel, 'm2');
  assert.equal(h.S.fold.get('m2'), false, 'the selected mark is unfolded');
  assert.equal(h.S.resumeAt, 42.5);
  assert.deepEqual(at, [42.5], 'the shown position is the remembered one before the player is ready');
  h.context.placeOf = () => null;
  assert.equal(await h.context.loadVideo('B'), true);
  assert.equal(h.S.sel, null); assert.equal(h.S.resumeAt, null);
});

// 書き出しの行の「編集で開く」の URL は e2e_cases_cand の 5 が見る。ここは知らせのボタン(アプリの窓 / ブラウザのタブ・何本目か)
test('export done notice has [編集で開く] with the same URL as the row link, opened the same way', () => {
  const shown = [], opened = [];
  let app = false;
  // copyText は UIKit.copy なので、切り出しの終わりは次の関数(jobDirText)。openEditor は UIKit.win を直接使う
  const ctx = load([['function editorHref(', 'function jobDirText(']], {
    enc: encodeURIComponent, toast: (m, ms, k) => shown.push({ m, ms, k }),
    Studio: { token: 't', toast: (m, o) => shown.push({ m, o }) },
    UIKit: makeUIKit({ 'win.isApp': () => app, 'win.open': u => { opened.push(['win', u]); return Promise.resolve(); } }),
    window: { open: (u, t, f) => opened.push(['tab', u, t, f]) } });
  assert.equal(ctx.editorHref('C:\\clips\\a b.mp4'), '/cases?v=C%3A%5Cclips%5Ca%20b.mp4#proof');
  ctx.doneToast('書き出し完了: 1/1件', 'ok', ['C:\\clips\\a.mp4']);
  const t1 = shown.at(-1);
  assert.equal(t1.o.action.label, '編集で開く'); assert.equal(t1.o.ms, 8000); assert.equal(t1.o.kind, 'ok');
  t1.o.action.fn();
  assert.deepEqual(opened.at(-1), ['tab', '/cases?v=C%3A%5Cclips%5Ca.mp4#proof', '_blank', 'noopener'], 'a browser tab: a new tab, like the row link');
  app = true;
  t1.o.action.fn();
  assert.deepEqual(opened.at(-1), ['win', '/cases?v=C%3A%5Cclips%5Ca.mp4#proof'], 'an app window: asks the home to open a window (UIKit.win)');
  ctx.doneToast('書き出し完了: 2/3件(失敗あり)', 'err', ['', 'C:\\b.mp4', 'C:\\c.mp4']);
  assert.equal(shown.at(-1).o.action.label, '1本目を編集で開く', 'several: the first one');
  ctx.doneToast('書き出しを中止しました', '', []);
  assert.deepEqual(shown.at(-1), { m: '書き出しを中止しました', ms: 0, k: '' }, 'nothing to open: the plain notice');
});

test('links to the home use data-ui-portal (no new tab); the autorun bar links to the case', () => {
  const rv = between('async function pollAuto(', 'function showDataWarning(');
  // 「案件で見る」はこの配信の案件の画面(候補)を開く(ホームへのリンクではない = data-ui-portal の決まりの外)
  assert.ok(rv.includes('href="../cases?c=${encodeURIComponent(vid)}#cand"') && !rv.includes('href="../#cases"'), '案件で見る');
  const rk = sliceOf('rank.js', 'class="row rk-autogo"', '</div>');
  assert.ok(rk.includes('data-ui-portal') && !rk.includes('_blank'), '案件の一覧');
});

test('"export all" always tells why it cannot be pressed', () => {
  const nodes = {};
  const S = { videos: [{ kind: 'youtube', adopted: 2 }, { kind: 'live', adopted: 5 }], live: false };
  const ctx = load([['function renderExpMore(', 'function renderExportUI(']], {
    S, $: sel => (nodes[sel] ||= {}), failedIds: () => new Set(), joinIds: () => [] });
  const why = (...a) => { ctx.renderExpMore(...a); return [nodes['#rvExpAll'].disabled, nodes['#rvExpAll'].title]; };
  assert.deepEqual(why(false, false, false), [false, '採用にしたマークがある全部の配信を、順番に書き出します(ライブの録画は除きます)']);
  assert.ok(why(false, true, false)[1].includes('実行中'));
  assert.ok(why(false, false, true)[1].includes('ffmpeg'));
  assert.ok(why(true, false, false)[1].includes('ライブの録画を開いている間'));
  S.live = true; assert.ok(why(false, false, false)[1].includes('配信中'));
  S.live = false; S.videos = [{ kind: 'youtube', adopted: 0 }];
  const [dis, t] = why(false, false, false);
  assert.ok(dis && t.includes('採用にしたマークがある配信がありません'), t);
});

test('live export body: after / streamer follow the band (settings and the streamer field)', () => {
  const v = { id: 'V', kind: 'live', title: 't', live: { recorder: 'local', recording: 'R1', url: 'u' }, marks: [{ id: 'a', start: 1, end: 2 }] };
  const S = { cur: v, settings: { liveAfter: 'auto' } };
  const LV = { who: { vid: 'V', name: ' 兎田ぺこら ', match: true } };
  const ctx = load([['function liveWhoName(', '/* 録画を開いたとき'], ['function liveExportBody(', '/* ライブの録画の書き出し(']],
    { S, LV, LIVE_AFTERS: ['none', 'auto'], sortedMarks: () => v.marks });
  let b = ctx.liveExportBody(v, v.marks[0]);
  assert.equal(b.after, 'auto'); assert.equal(b.transcribe, true); assert.equal(b.streamer, '兎田ぺこら');
  S.settings.liveAfter = 'none';
  b = ctx.liveExportBody(v, v.marks[0]);
  assert.equal(b.after, 'none'); assert.equal(b.transcribe, false);
  LV.who = { vid: 'OTHER', name: '宝鐘マリン' };
  assert.equal(ctx.liveExportBody(v, v.marks[0]).streamer, '', 'the name for another recording is not used');
  LV.who = null;
  assert.equal(ctx.liveExportBody(v, v.marks[0]).streamer, '');
  assert.equal(ctx.liveWhoLabel(null), '配信者: 未設定(字幕は既定の色)');
  assert.equal(ctx.liveWhoLabel({ name: '' }), '配信者: 未設定(字幕は既定の色)');
  assert.equal(ctx.liveWhoLabel({ name: 'だれか', match: false }), '配信者: だれか(色の一覧に無いので既定の色)');
});

test('portal export rows: progress of the handed-off autorun (transcribe only / full auto to the pack)', () => {
  const ctx = load([['function liveTxText(', '/* 書き出しの行の、本番版への作り直しの1行']], {});
  const st = (key, label, state) => ({ key, label, state, stateLabel: state });
  assert.equal(ctx.liveTxText(null), '');
  assert.equal(ctx.liveTxText({ state: 'done', label: '済み' }), '文字起こし: 済み', 'old shape (no steps)');
  assert.equal(ctx.liveTxText({ state: 'running', label: '実行中', steps: [st('transcribe', '文字起こし', 'run')] }), '文字起こし: 実行中(文字起こし)');
  const auto = [st('transcribe', '文字起こし', 'done'), st('pack', 'パック', 'run'), st('deliver', 'Dropbox へ届ける', 'wait')];
  assert.equal(ctx.liveTxText({ state: 'running', label: '実行中', steps: auto }), '文字起こし → パック: 実行中(パック)');
  const done = [st('transcribe', '文字起こし', 'done'), st('pack', 'パック', 'done'), st('deliver', 'Dropbox へ届ける', 'skip')];
  assert.equal(ctx.liveTxText({ state: 'done', label: '済み', steps: done }), '文字起こし → パック: パック済み');
  const noPack = [st('transcribe', '文字起こし', 'done'), st('pack', 'パック', 'skip'), st('deliver', 'Dropbox へ届ける', 'skip')];
  assert.equal(ctx.liveTxText({ state: 'done', label: '済み', steps: noPack }), '文字起こし → パック: 文字起こし済み(パックは作れませんでした)');
  assert.equal(ctx.liveTxText({ state: 'error', label: '失敗', message: '文字起こしに失敗しました', steps: auto }), '文字起こし → パック: 失敗(文字起こしに失敗しました)');
});

/* パネルが渡す window.Studio の代わり(var Studio = {…})を、まわりの変数を偽物にして切り出す */
function studioShim(file, start, end, extra) {
  const ctx = withUIKit({ Map, String, Promise, Date, encodeURIComponent, esc: s => s, params: {}, dead: false, visible: true, document: { head: { querySelector: () => ({ content: 't' }) } },
    LIVE: { infoP: null, offAt: 0 }, LIVE_RECHECK_MS: 60000, STUDIO_OFFLINE: 'スタジオにつながりませんでした', HOME_OFFLINE: 'ホームにつながりませんでした',
    setStep() {}, q: () => null, location: { assign() {} }, window: {}, ...extra });
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(SRC, 'app/ui/cases/panels/studio-shim.js'), 'utf8'), ctx);   // 2 つのパネルが共有する Studio の代わりの共通の部分
  ctx.StudioShim = ctx.window.StudioShim;
  vm.runInContext(sliceOf(file, start, end), ctx);
  return ctx;
}
const NEW_SHIM = ['app/ui/cases/panels/new.js', 'var Studio = StudioShim.create(', '/* パネルが見えている間だけ'];
const CAND_SHIM = ['app/ui/cases/panels/cand.js', 'var Studio = StudioShim.create(', '/* review.js に渡す env'];

test('live recordings are registered in one place with the channel name (new case panel register; rank.js "録画する" / "開く" pass the row channel)', async () => {
  // 新しい案件の引き出し(panels/new.js): Studio.live.register / begin(begin の返事のチャンネル名 → 無ければ opts.channel)
  const opened = [];
  const ctx = studioShim(...NEW_SHIM);
  ctx.Studio.api = async (url, o) => { opened.push({ url, body: o.body }); return { video: { id: o.body.recording } }; };
  let reply = { live: true, recorder: 'local', recording: { id: '20261005-185300-abcdefghijk', url: 'https://www.youtube.com/watch?v=abcdefghijk', title: 'T', state: 'recording', channel: '' } };
  ctx.Studio.live.available = async () => ({});
  ctx.Studio.live.api = async () => reply;
  await ctx.Studio.live.begin('https://youtu.be/abcdefghijk', { channel: 'Marine Ch. 宝鐘マリン' });
  assert.equal(opened.at(-1).body.channel, 'Marine Ch. 宝鐘マリン', 'no channel from the portal: the caller\'s name is used');
  reply.recording.channel = 'Pekora Ch. 兎田ぺこら';
  await ctx.Studio.live.begin('https://youtu.be/abcdefghijk', { channel: 'Marine Ch. 宝鐘マリン' });
  assert.equal(opened.at(-1).body.channel, 'Pekora Ch. 兎田ぺこら', 'the portal\'s channel wins');
  await ctx.Studio.live.begin('https://youtu.be/abcdefghijk');
  assert.deepEqual(plain(opened.at(-1).body), { kind: 'live', recorder: 'local', recording: '20261005-185300-abcdefghijk', url: 'https://www.youtube.com/watch?v=abcdefghijk', title: 'T', channel: 'Pekora Ch. 兎田ぺこら' });
  await ctx.Studio.live.register('local', { id: 'R2' }, { channel: 'x'.repeat(150) });
  assert.equal(opened.at(-1).body.channel.length, 100);
  // rank.js(① 探す の「録画する」「開く」): 行のチャンネル名を渡す・登録は register
  const rk = sliceOf('rank.js', 'async function lvBegin(', 'function wireLive(');
  assert.ok(rk.includes("S.live.begin(url, { channel: v.channel || '' })"), 'lvBegin passes the row channel to begin');
  assert.ok(rk.includes('S.live.register(') && !rk.includes("'/api/videos/open'"), 'lvOpen registers through Studio.live.register');
  assert.ok(!sliceOf('review.js', 'async function openLiveRecording(', '/* ---------- マーク操作').includes("'/api/videos/open'"), 'the header badge "開く" uses register too');
});

// ---- スタジオの API の包み 3 つは ui-kit の UIKit.http / homeApi を呼ぶだけ ----
test('the panels\' Studio API wrappers go through UIKit.http / homeApi with their messages, the live timeouts and the empty POST body', async () => {
  const calls = [];
  const kit = () => makeUIKit({
    http: (url, o) => { calls.push(['http', url, o]); return Promise.resolve({ ok: 1 }); },
    homeApi: (p, o) => { calls.push(['home', p, o]); return Promise.resolve({ ok: 2 }); },
    homeUrl: p => 'http://h/' + p,
    toast: (m, o) => { calls.push(['toast', m, o]); } });
  // 新しい案件の引き出し(panels/new.js): スタジオの API は UIKit.http(Studio.url)・入口は homeApi
  let ctx = studioShim(...NEW_SHIM, { UIKit: kit() });
  assert.deepEqual(plain(await ctx.Studio.api('/api/video', { method: 'PUT', body: { id: 'A' } })), { ok: 1 });
  let [kind, url, o] = calls.at(-1);
  assert.equal(kind, 'http'); assert.equal(url, 'studio/api/video', 'the URL is made by Studio.url (relative, one place)');
  assert.deepEqual(plain({ method: o.method, body: o.body }), { method: 'PUT', body: { id: 'A' } });
  assert.equal(o.offline, ctx.STUDIO_OFFLINE);
  await ctx.Studio.portalApi('api/autorun');
  [kind, url, o] = calls.at(-1);
  assert.equal(kind, 'home'); assert.equal(url, 'api/autorun'); assert.equal(o.body, undefined, 'no body = GET (no token)');
  assert.equal(o.offline, ctx.HOME_OFFLINE);
  await ctx.Studio.live.api('api/info');
  [kind, url, o] = calls.at(-1);
  assert.deepEqual([kind, url, o.method, o.body, o.timeout], ['home', 'live/api/info', 'GET', undefined, 10000], 'GET: 10 seconds, no body');
  await ctx.Studio.live.api('r/local/R1/stop', { body: undefined, method: 'POST' });
  o = calls.at(-1)[2];
  assert.deepEqual([o.method, plain(o.body), o.timeout], ['POST', {}, 45000], 'POST: 45 seconds and always a body ({} when none)');
  await ctx.Studio.live.api('api/begin', { body: { url: 'u' }, timeout: 5000 });
  o = calls.at(-1)[2];
  assert.deepEqual([o.method, plain(o.body), o.timeout, o.slow], ['POST', { url: 'u' }, 5000, 'ホームから時間内に応答がありません']);
  assert.equal(ctx.Studio.live.url('hls.min.js'), 'http://h/live/hls.min.js', 'media URLs come from UIKit.homeUrl');
  // 候補のパネル(panels/cand.js): スタジオの API は殻の ctx.api('studio', …)(待ちの時間切れなし)・ライブの口は同じ時間・録画の登録はしない
  const shell = [];
  ctx = studioShim(...CAND_SHIM, { UIKit: kit(), cctx: { api: (tool, p, opt) => { shell.push([tool, p, opt]); return Promise.resolve({ ok: 3 }); } } });
  assert.deepEqual(plain(await ctx.Studio.api('/api/video', { method: 'PUT', body: { id: 'A' } })), { ok: 3 });
  [kind, url, o] = shell.at(-1);
  assert.deepEqual([kind, url, o.method, plain(o.body), o.timeout], ['studio', '/api/video', 'PUT', { id: 'A' }, 0], 'studio API through the shell, no timeout (exports can be long)');
  assert.ok(o.offline.includes('スタジオにつながりませんでした'));
  assert.equal(ctx.Studio.url('/media?id=x'), 'studio/media?id=x');
  await ctx.Studio.portalApi('api/flow/submit', { envelope: { id: 'A' } });
  [kind, url, o] = calls.at(-1);
  assert.deepEqual([kind, url, plain(o.body)], ['home', 'api/flow/submit', { envelope: { id: 'A' } }]);
  await ctx.Studio.live.api('api/info');
  o = calls.at(-1)[2];
  assert.deepEqual([calls.at(-1)[1], o.method, o.body, o.timeout], ['live/api/info', 'GET', undefined, 10000]);
  await ctx.Studio.live.api('r/local/R1/stop', { method: 'POST' });
  o = calls.at(-1)[2];
  assert.deepEqual([o.method, plain(o.body), o.timeout], ['POST', {}, 45000]);
  await assert.rejects(ctx.Studio.live.register('local', { id: 'R1' }), /録画の登録はしません/);
  // Studio.toast(msg, 0, kind) の 0 は「既定の秒数」(ui-kit の「消えない」ms: 0 として渡さない)。オブジェクトはそのまま
  for (const c of [CAND_SHIM, NEW_SHIM]) {
    const seen = [];
    const t = studioShim(...c, { UIKit: makeUIKit({ toast: (m, opt) => { seen.push(opt); } }) });
    t.Studio.toast('a', 0, 'ok'); t.Studio.toast('b', 1200); t.Studio.toast('c', { ms: 0, kind: 'err' });
    assert.deepEqual(seen.map(x => [x.ms === undefined ? null : x.ms, x.kind || null]), [[null, 'ok'], [1200, null], [0, 'err']], c[0]);
  }
});

// ---- ② の設定と欄の対応は 1 つの表(欄から保存までのつなぎは e2e_live_studio の 15 が「書き出したあと」で見る) ----
test('review settings: one table of field ↔ setting; every field value read back through sanitizeSettings gives the same setting', () => {
  const ctx = load([['const LIVE_AFTERS', '/* ---------- 状態 ---------- */'], ['const SET_UI = [', 'function syncSettingsUI(']],
    { autoTxLegacy: () => null, sec1: (v, d) => d, sanitizeKeymap: () => ({}), KEY_PRESETS: { standard: {} }, DEFAULT_QUICK_SPANS: [30, 60, 120, 180, 300] });
  vm.runInContext('this.SET_UI = SET_UI;', ctx);
  const def = ctx.sanitizeSettings({}), sels = ctx.SET_UI.map(r => r[0]);
  assert.equal(new Set(sels).size, sels.length, 'each field once');
  for (const [sel, k, prop] of ctx.SET_UI){
    assert.ok(k in def, sel + ': ' + k + ' is a sanitized setting');
    assert.ok(prop === 'value' || prop === 'checked', sel);
    const shown = prop === 'checked' ? !!def[k] : String(def[k]);   // syncSettingsUI が欄へ書く値
    assert.deepEqual(ctx.sanitizeSettings({ ...def, [k]: shown })[k], def[k], sel + ': the field value comes back as the same setting');
  }
  assert.equal(ctx.sanitizeSettings({ lag: '3' }).lag, 3); assert.equal(ctx.sanitizeSettings({ exportLoudness: '0' }).exportLoudness, 0);
  assert.equal(ctx.sanitizeSettings({ liveMode: 'x' }).liveMode, 'auto', 'an unknown field value falls back like the saved settings do');
});

test('buildDOM: the parts put together keep every id exactly once', () => {
  const box = {};
  const ctx = { $: sel => (box[sel] ||= {}) };
  vm.createContext(withUIKit(ctx));
  vm.runInContext(source.match(/^const FILTERS = .*$/m)[0] + '\n' + between('const SVG = {', '/* ---------- 保存(サーバー') + '\nbuildDOM();', ctx);
  const html = box['#paneReview'].innerHTML;
  const ids = [...html.matchAll(/\sid="([^"$]+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length, 'ids are unique: ' + ids.filter((x, i) => ids.indexOf(x) !== i));
  for (const id of ['rvRoot', 'rvJump', 'rvMain', 'rvPlayerBox', 'rvLiveBar', 'rvQuickbar', 'rvMarkDetails', 'rvExport', 'rvClipbox', 'rvList'])
    assert.ok(ids.includes(id), id);
  assert.equal((html.match(/<section /g) || []).length, (html.match(/<\/section>/g) || []).length);
});

test('export count text: what will be written, or what to do when nothing can be written', () => {
  const S = { settings: { exportTarget: 'adopted' }, exportAll: null, live: false };
  const ctx = { S, fmt: t => t + 's' };
  vm.createContext(withUIKit(ctx));
  vm.runInContext(between('function exportCountText(', '/* 「書き出す」を押せるか'), ctx);
  const v = (...st) => ({ marks: st.map((s, i) => ({ id: 'm' + i, status: s })) });
  const t2 = [{ start: 0, end: 5 }, { start: 10, end: 12 }];
  assert.equal(ctx.exportCountText(v('adopted'), false, t2, null, false, 0, []), '採用のマーク 2件(合計 7s)を mp4 にします');
  assert.equal(ctx.exportCountText(v(''), false, [], null, false, 0, []), '候補を「採用」にすると、書き出せるようになります');
  assert.equal(ctx.exportCountText(v(), true, [], null, false, 0, []), 'マークを付けると、ここに書き出しの進み具合が出ます');
  assert.equal(ctx.exportCountText(v('rejected'), false, [], null, false, 0, []), '書き出すマークはありません(「採用」にしたマークを書き出します)');
  assert.equal(ctx.exportCountText(v('adopted'), true, [], null, false, 0, [{ state: 'wait' }, { state: 'fetch' }]), '書き出し中 2件(録画待ち 1件)');
  assert.equal(ctx.exportCountText(v('adopted'), false, t2, { items: [1, 2, 3] }, true, 1, []), '書き出し中 1/3件');
  assert.equal(ctx.exportCountText(null, false, [], null, false, 0, []), '');
  S.live = true;
  assert.ok(ctx.exportCountText(v('adopted'), true, t2, null, false, 0, []).endsWith('(録画が届くのを待ってから作ります)'));
  S.exportAll = { idx: 2, total: 5, fail: 1 };
  assert.equal(ctx.exportCountText(v('adopted'), false, t2, null, false, 0, []), '全部の配信の書き出し: 2/5 本目(失敗 1件)');
  S.settings.exportTarget = 'pending'; S.exportAll = null; S.live = false;
  assert.ok(ctx.exportCountText(v('adopted'), false, t2, null, false, 0, []).startsWith('採用と候補のマーク 2件'));
});

// ---- 配信中の候補(LIVE の帯の一覧・入口の GET/POST ../live/api/peaks) ----
// 行の並び・控えも見る・マウスが乗った行を残す・札(枠 / 控え / 採用 / 見送り)・[採用] [見送り] [戻す]・p / z は e2e_live_studio の L3 が見る
const PEAK_FNS = ['const PEAK_PRE = 5;', '/* 配信中の候補の状態'];
const mmss = t => Math.floor(t / 60) + ':' + String(Math.floor(t % 60)).padStart(2, '0');
const pk = (id, start, end, extra) => ({ id, start, end, peak: start + 2, score: 5, reasons: ['音量が急上昇'], hour: 0, state: 'frame', ...extra });

test('live peaks: normalize, the full list and the since-changes (unknown ids and end-pending peaks ask for the full list)', () => {
  const ctx = load([PEAK_FNS], { tickLabel: mmss });
  assert.equal(ctx.peakNorm({ id: 'a', start: 5, end: 5 }), null, 'end must be after start');
  assert.equal(ctx.peakNorm({ start: 1, end: 5 }), null, 'an id is needed');
  const n = plain(ctx.peakNorm({ id: 'a', start: -1, end: 8, peak: 3700, state: 'odd', reasons: ['x', 3], score: '7.25', endPending: 1 }));
  assert.deepEqual(n, { id: 'a', start: 0, end: 8, peak: 3700, score: 7.25, parts: {}, reasons: ['x'], hour: 1, state: 'frame', endPending: false, origin: '', text: '' },
    'unknown state → frame, the hour comes from the peak second, endPending only when true');
  // 配信中の文字起こし: text は文字列だけ残す(2000 字まで)。changes の peak に text が付けば手元の候補にも入り、state だけの change では消えない
  assert.equal(ctx.peakNorm(pk('t', 1, 5, { text: 'あいう' })).text, 'あいう');
  assert.equal(ctx.peakNorm(pk('t', 1, 5, { text: 3 })).text, '', 'not a string: empty');
  assert.equal(ctx.peakNorm(pk('t', 1, 5, { text: 'x'.repeat(2500) })).text.length, 2000);
  const tl = ctx.peakMerge(ctx.peakList([pk('t', 1, 5)]), [{ seq: 2, id: 't', state: 'frame', peak: pk('t', 1, 5, { text: '文字が付いた' }) }]).list;
  assert.equal(tl[0].text, '文字が付いた', 'a change with the peak carries the text');
  assert.equal(ctx.peakMerge(tl, [{ seq: 3, id: 't', state: 'adopted' }]).list[0].text, '文字が付いた', 'a state-only change keeps the text');
  assert.deepEqual(plain(ctx.peakList([pk('b', 30, 34), null, pk('a', 10, 14), { id: 'x' }]).map(p => p.id)), ['a', 'b'], 'time order, broken ones dropped');
  const list = ctx.peakList([pk('a', 10, 14), pk('b', 30, 34), pk('c', 50, 58, { endPending: true })]);
  let m = ctx.peakMerge(list, [{ seq: 6, id: 'b', state: 'bench' }]);
  assert.equal(m.full, false);
  assert.deepEqual(plain(m.list.map(p => p.id + ':' + p.state)), ['a:frame', 'b:bench', 'c:frame'], 'only the changed state; the rest stays as it was');
  assert.equal(ctx.peakMerge(list, [{ seq: 7, id: 'z', state: 'frame' }]).full, true, 'a new peak (unknown id) needs the full list');
  m = ctx.peakMerge(list, [{ seq: 7, id: 'z', state: 'frame', start: 70, end: 74 }]);
  assert.equal(m.full, false, 'a change that carries the range is enough');
  assert.equal(m.list.at(-1).id, 'z');
  assert.equal(ctx.peakMerge(list, [{ seq: 8, id: 'c', state: 'frame' }]).full, true, 'the end of an end-pending peak may have moved');
  m = ctx.peakMerge(list, [{ seq: 8, id: 'c', state: 'frame', end: 57.5, endPending: false }]);
  assert.equal(m.full, false); assert.equal(m.list[2].end, 57.5); assert.equal(m.list[2].endPending, false);
  assert.equal(ctx.peakMerge(list, null).full, false, 'no changes: nothing to do');
  // 入口の changes は {seq, id, state, peak: 今の形}: 新しい候補も・終わりが決まった候補も、読み直さずに当てられる
  m = ctx.peakMerge(list, [{ seq: 9, id: 'c', state: 'frame', peak: { ...pk('c', 50, 56.5), endPending: false, seq: 9 } }, { seq: 9, id: 'y', state: 'bench', peak: pk('y', 80, 84, { state: 'bench' }) }]);
  assert.equal(m.full, false);
  assert.deepEqual(plain(m.list.map(p => [p.id, p.state, p.end, p.endPending, p.peak])), [['a', 'frame', 14, false, 12], ['b', 'frame', 34, false, 32], ['c', 'frame', 56.5, false, 52], ['y', 'bench', 84, false, 82]]);
  assert.equal(plain(ctx.peakSeries({ n: 3600, step: 6, total: [1] })).n, 3600, 'n from the portal when given');
});

test('live peaks: p after the last one finds nothing; when the current one left the list, it starts from the first', () => {
  const ctx = load([PEAK_FNS], { tickLabel: mmss });
  const list = ctx.peakList([pk('a', 10, 14, { state: 'adopted' }), pk('b', 30, 34, { state: 'bench' }), pk('c', 50, 58), pk('d', 70, 74, { state: 'dismissed' })]);
  assert.equal(ctx.peakNext(ctx.peakShown(list, true), 'c'), null, 'dismissed ones are skipped; after the last there is no next');
  assert.equal(ctx.peakNext(ctx.peakShown(list, false), 'gone').id, 'a');
});

test('live peaks: the header line (count, this hour x/perHour, delay, chat, auto adopt) and what each row shows', () => {
  const ctx = load([PEAK_FNS], { tickLabel: mmss });
  const list = ctx.peakList([pk('a', 10, 14, { state: 'adopted', origin: 'manual' }), pk('b', 30, 34, { state: 'bench' }), pk('c', 50, 58),
    pk('d', 3700, 3710, { hour: 1 }), pk('e', 3800, 3810, { hour: 1, state: 'adopted', origin: 'auto' })]);
  let h = ctx.peakHead(list, { perHour: 6, counts: { 0: 1, 1: 2 } }, { running: true, behindSec: 34.6, chat: 'ok' }, { waitMin: 5 }, { hour: 1, active: true });
  assert.equal(h.count, '候補 4 件(この 1 時間 2/6)', 'frame + adopted; this hour from the portal counts');
  assert.equal(h.info, '遅れ 35 秒・チャットを読んでいます・自動採用(5 分待ち)');
  h = ctx.peakHead(list, null, { running: true, chat: 'restarting' }, null, { hour: 1, active: true });
  assert.equal(h.count, '候補 4 件(この 1 時間 2/6)', 'without counts: frame + auto-adopted in the hour (a hand-adopted one is not counted)');
  assert.equal(h.info, 'チャットをつなぎ直しています・自動採用(5 分待ち)', 'the portal has not said the wait yet: the default (auto-adopt is always on since 10-19)');
  assert.equal(ctx.peakHead([], null, { running: false, message: '' }, null, { hour: 0, active: true }).info, '検出が止まっています(ホームが起動し直します)・自動採用(5 分待ち)');
  assert.equal(ctx.peakHead(list, { perHour: 8, counts: {} }, { running: false }, { waitMin: 5 }, { hour: 0, active: false }).info, '', 'an ended recording: nothing about the worker');
  assert.equal(ctx.peakHead(list, { perHour: 8, counts: {} }, null, null, { hour: 0 }).count, '候補 4 件(この 1 時間 0/8)');
  // 配信中の文字起こしの状態 o.tx: オンで準備が無いときだけ「文字起こしなし(理由)」(whisper.cpp が無いときは e2e_live_studio の _scene_peak_text が見る)。
  // 準備がある・オフ・録画が終わった・o.tx が無い(tx を返さない入口)は何も出さない
  const run = { running: true, chat: 'ok' }, auto = { waitMin: 3 };
  const txOf = tx => ctx.peakHead(list, null, run, auto, { hour: 0, active: true, tx }).info;
  assert.equal(txOf({ enabled: true, ready: false, message: '' }), 'チャットを読んでいます・自動採用(3 分待ち)・文字起こしなし(準備がありません)');
  assert.equal(txOf({ enabled: true, ready: true, message: '' }), 'チャットを読んでいます・自動採用(3 分待ち)', 'ready: nothing');
  assert.equal(txOf({ enabled: false, ready: false, message: 'オフ(設定 live.liveTx)' }), 'チャットを読んでいます・自動採用(3 分待ち)', 'turned off: nothing');
  assert.equal(txOf(undefined), 'チャットを読んでいます・自動採用(3 分待ち)', 'an older portal (no tx): nothing');
  assert.equal(txOf('x'), 'チャットを読んでいます・自動採用(3 分待ち)', 'not an object: nothing');
  assert.equal(ctx.peakHead(list, null, { running: false }, auto, { hour: 0, active: false, tx: { enabled: true, ready: false, message: 'ffmpeg がありません' } }).info, '',
    'an ended recording: nothing about the transcription either');
  const v = p => plain(ctx.peakView(ctx.peakNorm(p), false));
  let r = v(pk('c', 50, 58.5, { score: 6.25 }));
  assert.equal(r.time, '0:50'); assert.equal(r.title, '0:50 – 0:58(8.5 秒)・山 0:52'); assert.equal(r.score, '6.3点');
  r = v(pk('a', 10, 14, { state: 'adopted', origin: 'auto' }));
  assert.deepEqual([r.pill[1], r.adopt, r.dismiss, r.restore], ['自動で採用', false, false, false], 'auto adopted: the chip only');
  r = v(pk('e', 90, 99, { endPending: true }));
  assert.ok(r.pending && r.why.includes('終わりがまだ録れていません'), 'end pending: cannot be adopted yet (with the reason)');
  assert.equal(plain(ctx.peakView(ctx.peakNorm(pk('c', 50, 58)), true)).why, '送っています…', 'while the request is on the way');
  assert.equal(v(pk('f', 1, 2, { score: null })).score, '');
  assert.deepEqual(plain(ctx.peakSeries({ step: 0.5, total: [1, '2', null], audio: [3], chat: 'x' })), { n: 2, step: 0.5, total: [1, 2, 0], audio: [3], chat: [] },
    'the portal series in the analysis series shape (n = seconds)');
  assert.equal(ctx.peakSeries({ step: 1, total: [] }), null);
});

function peakHarness(respond) {
  const calls = [], notes = [], after = [];
  const S = { cur: { id: 'R', kind: 'live', live: { recorder: 'local', recording: 'R' }, marks: [] }, settings: { liveAfter: 'auto' }, now: 0, duration: 120 };
  const ctx = load([['const PEAK_PRE = 5;', '/* ---------- マーク操作 ---------- */']], {
    S, LV: { status: { active: true }, deletedShown: false },
    Studio: { token: 't', step: 'review', toast: m => notes.push(m), live: { api: async (url, o) => { const c = { url, body: o && o.body }; calls.push(c); return respond(c); } } },
    $: () => null, document: { querySelector: () => null, activeElement: null, body: {} }, CSS: { escape: s => s },
    toast: m => notes.push(m), flushSave: async () => { after.push('save'); }, syncFromServer: async () => { after.push('sync'); }, pollLiveJobs: async () => { after.push('jobs'); }, liveResume: () => {},
    renderGraph: () => {}, previewClip: c => notes.push('preview ' + c.start + '-' + c.end), keybarScene: () => {}, liveSet: () => {},
    tickLabel: mmss, reasonTags: () => '', SVG: { play: '' }, esc: s => s, enc: encodeURIComponent, totalDur: () => 120, pct: t => t,
    LIVE_AFTERS: ['none', 'auto'], liveWhoName: () => '兎田ぺこら', curKeymap: () => ({ nextPeak: 'p' }), keyText: k => k, Date, setTimeout, clearTimeout });
  const PKV = vm.runInContext('PKV', ctx);
  return { ctx, S, PKV, calls, notes, after };
}
const settle = async () => { for (let i = 0; i < 6; i++) await tick(); };

test('live peaks: asked only when detection is on; full list first, then since-changes; 404 is given up after the first time', async () => {
  let reply = null;
  const h = peakHarness(async c => (typeof reply === 'function' ? reply(c) : reply));
  h.ctx.peaksOpened('R');
  h.ctx.peakPrefs({ detect: { enabled: false } });
  await h.ctx.pollPeaks(h.S.cur);
  assert.equal(h.calls.length, 0, 'detection off: the API is not asked (no 404 from an old portal)');
  reply = { ok: true, seq: 5, enabled: true, worker: { running: true, behindSec: 30, chat: 'ok' }, hour: { perHour: 6, counts: { 0: 2 } },
    peaks: [pk('b', 30, 34), pk('a', 10, 14)], series: { step: 1, total: [1, 2, 3], audio: [1], chat: [2] } };
  h.ctx.peakPrefs({ detect: { enabled: true }, autoAdopt: { waitMin: 5 } });
  await settle();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, 'api/peaks?recorder=local&recording=R', 'the first ask has no since (all + series)');
  assert.deepEqual(plain(h.PKV.list.map(p => p.id)), ['a', 'b']);
  assert.equal(h.PKV.seq, 5); assert.equal(h.PKV.series.n, 3);
  reply = { ok: true, seq: 6, enabled: true, changes: [{ seq: 6, id: 'b', state: 'bench' }] };
  await h.ctx.pollPeaks(h.S.cur);
  assert.equal(h.calls[1].url, 'api/peaks?recorder=local&recording=R&since=5');
  assert.equal(h.PKV.list[1].state, 'bench'); assert.equal(h.PKV.seq, 6);
  const urls = [];
  reply = c => { urls.push(c.url); return c.url.includes('since=') ? { ok: true, seq: 7, changes: [{ seq: 7, id: 'n', state: 'frame' }] }
    : { ok: true, seq: 7, peaks: [pk('a', 10, 14), pk('b', 30, 34, { state: 'bench' }), pk('n', 60, 64)] }; };
  await h.ctx.pollPeaks(h.S.cur); await settle();
  assert.deepEqual(urls, ['api/peaks?recorder=local&recording=R&since=6', 'api/peaks?recorder=local&recording=R'], 'an unknown id: the full list right away');
  assert.deepEqual(plain(h.PKV.list.map(p => p.id)), ['a', 'b', 'n']);
  reply = () => { const e = new Error('見つかりません'); e.status = 404; throw e; };
  h.PKV.needFull = true;
  await h.ctx.pollPeaks(h.S.cur);
  const n = h.calls.length;
  await h.ctx.pollPeaks(h.S.cur);
  assert.equal(h.calls.length, n, 'after a 404 the band stops asking');
  assert.equal(h.PKV.missing, true);
});

test('live peaks: adopt sends one request (no double press) with the band settings, then reads the marks and the export jobs again', async () => {
  const gate = deferred();
  const h = peakHarness(async c => {
    if (!c.body) return { ok: true, seq: 1, enabled: true, worker: { running: true }, peaks: [pk('a', 10, 14, { text: '候補の文字' }), pk('b', 30, 34, { endPending: true })] };
    if (c.body.op === 'adopt'){ await gate.promise; return { ok: true, peak: pk('a', 10, 14, { state: 'adopted', origin: 'manual', markId: 'm1' }), job: { id: 'lx-1' }, mark: 'm1', existing: false }; }
    return { ok: true, peak: pk(c.body.id, 30, 34, { state: c.body.op === 'dismiss' ? 'dismissed' : 'frame', endPending: true }) };
  });
  h.ctx.peaksOpened('R'); h.ctx.peakPrefs({ detect: { enabled: true } }); await settle();
  const first = h.ctx.adoptPeak('a'), second = h.ctx.adoptPeak('a');
  await settle(); gate.resolve(); await first; await second;
  const posts = h.calls.filter(c => c.body);
  assert.equal(posts.length, 1, 'pressed twice before the answer: one request');
  assert.deepEqual(plain(posts[0].body), { op: 'adopt', recorder: 'local', recording: 'R', id: 'a', after: 'auto', streamer: '兎田ぺこら' });
  assert.deepEqual(h.after, ['save', 'sync', 'jobs'], 'saved first; then the new mark and the export row are read (② does not see server-side marks by itself)');
  assert.equal(h.PKV.list[0].state, 'adopted');
  assert.equal(h.PKV.list[0].text, '候補の文字', 'the POST answer has no text (the GET adds it): the text on the row stays');
  assert.ok(h.notes.some(m => String(m).includes('候補 0:10 を採用しました')));
  await h.ctx.adoptPeak('b');
  assert.equal(h.calls.filter(c => c.body).length, 1, 'an end-pending peak is not adopted');
  assert.ok(h.notes.at(-1).includes('終わりがまだ録れていません'));
  await h.ctx.setPeakState('b', 'dismiss');
  assert.equal(h.PKV.list[1].state, 'dismissed');
  assert.ok(h.notes.some(m => String(m).includes('を見送りました')), 'dismissing is undone from the notice (no confirmation)');
  await h.ctx.setPeakState('b', 'restore');
  assert.equal(h.PKV.list[1].state, 'frame');
  // p / z
  h.ctx.peakKeyNext();
  assert.equal(h.notes.at(-1), 'preview 5-14', 'p: nothing played yet → the first candidate from 5 s before');
  h.ctx.peakKeyNext();
  assert.equal(h.notes.at(-1), 'preview 25-34', 'p again: the next one');
  h.ctx.peakKeyAdopt();
  assert.ok(h.notes.at(-1).includes('終わりがまだ録れていません'), 'z: the one just played (end pending here)');
});

// ---- 書き出しのあと自動で(autoTx)・マークの行の「この後を」= 書き出しから全部(mode full + run.from export + marks。10-19) ----
test('autoTx and "this one onward": the same order = from export to pack with the marks, and the send target when the intake folder is set', async () => {
  const sent = [], started = [], notes = [];
  let out = 'C:/Dropbox/切り抜き依頼/出力';
  const UIKit = { flow: { order: f => f }, autorun: { watch() {}, state: () => ({ overwrite: false }), start: async orders => { started.push(...orders); return { runs: [] }; } },
    streamer: { check: async () => '兎田ぺこら' } };
  const ctx = load([['async function sendOutDir(', '/* ---------- 書き出しのあと自動でパックまで'], ['async function autoOrder(', '/* まとめて実行(マークの行の「この後を」)'],
    ['async function startAuto(', 'async function pollAuto(']], {
    UIKit, Studio: { token: 't' }, S: { settings: {}, cur: { id: 'V', title: '配信' }, dirty: false }, toast: m => notes.push(m), pollAuto() {}, flushSave: async () => {},
    portalApi: async (path, body) => { if (path === 'api/intake') return { outDir: out }; sent.push({ path, body }); return { run: { id: 'r1' } }; },
    autoTxEnabled: () => true, $: sel => ({}) });
  await ctx.maybeAutoTranscribe('V', ['m1', 'm2']);
  assert.deepEqual(plain(sent[0]), { path: 'api/flow/submit', body: { kind: 'url', videoId: 'V', from: 'export', upto: 'pack', marks: ['m1', 'm2'],
    deliver: { origin: 'auto', dir: out } } }, 'autoTx: from export to pack, with the send target (the send gate decides)');
  assert.equal(notes.at(-1), '書き出しに続けて、文字起こし → パックを始めました');
  await ctx.startAuto(['m3']);
  assert.deepEqual(plain(started[0]), { kind: 'url', videoId: 'V', from: 'export', upto: 'pack', marks: ['m3'], deliver: { origin: 'auto', dir: out },
    title: '配信', streamer: '兎田ぺこら', repack: false }, '"this one onward" is the same order as autoTx');
  out = null;   // 受付のフォルダが決まっていない: 届け先なし(送らない)
  await ctx.maybeAutoTranscribe('V', ['m4']);
  assert.equal('deliver' in sent[1].body, false);
});
