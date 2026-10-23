'use strict';
/* 案件の画面(/cases)の校正のパネルの口。src/app/ui/cases/edhost.js が app.js より先に window.EditHost を置く = {base(API の頭), keybar(帯), tab(タブ), open(別の文書), opening}。
   URL・タブ・カットとパック(panels/cut.js が持つ)は殻のもの */
const EDIT_HOST = window.EditHost;
const APP_VERSION = (document.querySelector('meta[name="ytt-version"]') || {}).content || '';   // 全体の版(ytt/version.py)。入口が画面を返すときに meta ytt-version へ入れる(JS に版の文字は書かない)。入口なしだと空 = 版の比べはしない
const $ = s => document.querySelector(s);
const esc = UIKit.esc;   // ui-kit の 1 か所(null・undefined は '')
const S = { tools: null, settings: {}, jobs: [], list: [], doc: null, docId: null, dirty: false, saving: false,
  undo: [], sel: new Set(), curIdx: -1, playEnd: null, seen: new Set(), pollT: null,
  navIdx: -1, conflict: false, forceNext: false, baseUpdatedAt: null, stripR: null, sess: { n: 0, activeMs: 0, lastBreak: 0, lastAct: Date.now() },
  eff: { id: null, ms: 0 } };   // eff = 操作中の知らせ(effortFlush = 文書の effort.lastAt)を送るまでの、たまった操作の時間
const PALETTE = ['#2f62d6', '#d9534f', '#2e9e5b', '#c98a12', '#8a4fd6', '#0f9aa8', '#d6479a', '#6b7280'];
/* ---------- 共通 ---------- */
window.addEventListener('error', e => showErr(e.message));
window.addEventListener('unhandledrejection', e => showErr(String(e.reason && e.reason.message || e.reason)));
/* サーバーの API・動画の URL は、必ずこの apiUrl() を通して作る(将来1つのアプリに統合するとき、
   ベースのパスをここ1か所で変えられるように)。殻の口(EDIT_HOST.base)から求める(絶対パス "/xxx" は直接書かない) */
const BASE = EDIT_HOST.base;
const apiUrl = path => BASE + path;
/* 入口の統合サーバーに取り込まれたときの合言葉(CSRF トークン。入口が <meta name="ytt-token"> で画面に入れる)。
   書き込み系(GET/HEAD 以外)の要求にだけ付ける */
const TOKEN = (document.querySelector('meta[name="ytt-token"]') || {}).content || '';
/* 話者の色: 文書の JSON は手で直せるので、色の文字列は #rgb / #rrggbb だけを通す(style 属性に入れるため。
   そのまま入れると「red;background:url(外部)」のような値で CSS を差し込まれ、外へ通信されうる) */
const spColor = sp => sp && /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(String(sp.color || '')) ? sp.color : '';
const norm = s => String(s).normalize('NFKC').toLowerCase();

/* ---------- 表示の好み(長時間の作業向け。このブラウザにだけ保存) ---------- */
const VIEW_KEY = 'tx.view.v1';
const V = { fs: '15', dense: false, vid: 'l', follow: true, frameFollow: false, adjStep: '0.1', autoNext: false, rate: '1', brk: '45' };
const VID_H = { s: '18vh', m: '28vh', l: '38vh' };
/* 画面の色は設定の引き出し(UIKit.settings。全体の節)で変える。ここは帯の色の描き直しだけ */
UIKit.theme.onChange(() => { if (S.doc) drawStripSoon(); });   // ヘッダーのボタン・別のタブ・OS の設定・設定の引き出しで変わったとき(帯の色も描き直す)
{
  const bind = (id, key, get) => $('#' + id).addEventListener('change', e => { V[key] = get(e.target); saveView(); applyView(); });
  bind('vFs', 'fs', t => t.value); bind('vVid', 'vid', t => t.value); bind('vDense', 'dense', t => t.checked); bind('vBrk', 'brk', t => t.value); bind('autoNext', 'autoNext', t => t.checked);
  bind('follow', 'follow', t => t.checked); bind('frameFollow', 'frameFollow', t => t.checked); bind('adjStep', 'adjStep', t => t.value); bind('rate', 'rate', t => t.value);
  $('#btnKeys').addEventListener('click', () => openKeys());
  document.addEventListener('click', e => document.querySelectorAll('details.pop[open], details.ui-menu[open]').forEach(d => { if (!d.contains(e.target) || e.target.closest('.ui-menu-pop a')) d.open = false; }));
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || imeKey(e)) return;
    document.querySelectorAll('details.pop[open], details.ui-menu[open]').forEach(d => { d.open = false; });
  });
}

/* ---------- ヘッダーの ⚙(ui-kit v6。UIKit.settings)。「表示」の内容はツールの節、画面の色は全体の節(ui-kit) ---------- */
$('#edSettings').hidden = false; UIKit.settings.mount({ tool: $('#edSettings'), title: '設定', version: 'v' + APP_VERSION });
document.addEventListener('DOMContentLoaded', setAppnavVersion);
setAppnavVersion();

/* ---------- 取り込まれたツールの場所(app-core.js の loadSiblings) ---------- */
let sibP = null;

/* ---------- 設定(用語集・置換辞書など。保存は差のキーだけ = app-core.js の sendSettings) ---------- */
let setT = null, setSaved = {}, setFailed = false, setChain = Promise.resolve(true);
S.settingsLoadErr = '';
const setSnap = o => { const m = {}; for (const k of Object.keys(o || {})) m[k] = JSON.stringify(o[k]); return m; };
const setStatus = (...a) => UIKit.settings.status(...a);
/* 画面を離れた(ui-kit の UIKit.life: タブの切り替え 'hidden'・別の窓へ移った 'blur'・閉じる直前 'pagehide')。
   窓を並べて使うと、隣の窓をクリックしてもタブの切り替え(visibilitychange)は来ないため。visibilitychange を直接は使わない */
const onLeave = fn => UIKit.life.onLeave(fn);
/* 入力の直後(0.6秒以内)にタブを閉じても設定が消えないように、画面を離れるときは待たずに送る(keepalive: 閉じたあとも送り切る) */
onLeave(() => { if (setT){ clearTimeout(setT); setT = null; sendSettings(true); } });
UIKit.life.onReturn(() => { if (setFailed && !S.settingsLoadErr) sendSettings(); });   // 離れるときの送信が失敗していたら送り直す

/* 左の各カードの開閉を覚える */
document.querySelectorAll('aside details.card[id]').forEach(d => {
  try { const v = localStorage.getItem('tx.fold.' + d.id); if (v === '0') d.open = false; else if (v === '1') d.open = true; } catch {}
  d.addEventListener('toggle', () => { try { localStorage.setItem('tx.fold.' + d.id, d.open ? '1' : '0'); } catch {} });
});

/* ---------- ジョブの進捗 ---------- */
const ACTIVE = new Set(['queued', 'extracting', 'loading', 'running']);
const STATE_LABEL = { queued: '待機中', extracting: '準備中', loading: '準備中', running: '処理中', done: '完了', error: '失敗', cancelled: '中止' };
const pctOf = j => Math.max(0, Math.min(100, Math.round((Number(j.progress) || 0) * 100)));

/* ---------- 保存済み一覧(読み込みは app-list.js)・題名の行の「まとめて実行」 ---------- */
const ago = ms => UIKit.fmt.ago(ms);
const RUNS = { polling: 0, active: new Set(), last: [] };   // 入口の実行の見張り(app-list.js の pollRuns)
/* 状態の言葉は共通の部品(UIKit.autorun。どの入口も同じ言葉)。ここは札の色だけ */
const RUN_CLS = { queued: 'wait', running: 'run', done: 'ok', error: 'err', cancelled: 'wait' };
const runLabelOf = r => UIKit.autorun.runLabel(r);
const stepLabelOf = s => UIKit.autorun.stepLabel(s);

/* ---------- 話者の自動判別 ---------- */
const LOCK_KINDS = ['diarize', 'retranscribe'];
const LOCK_LABEL = { retranscribe: '再認識', diarize: '話者を判別' };
/* ---------- 声を覚える(関数は app-jobs.js) ---------- */
const DEFAULT_SPK = /^話者\d+$/;
const EVAL_VOICE_MSG = '評価用の文字起こしでは声を覚えません(評価用のデータを、ほかの文書の話者の名前付けに使わないため)。評価用を外すと覚えられます';
/* 覚える前の確認の本文。一般的な名前の判定・行の選び方はサーバー(/api/voices/preview)の1か所で、ここは結果を並べるだけ */
const VOICE_SKIP = [['unproofed', '未校正'], ['tagged', '音のメモ(重なり・BGM・聞き取れない)'], ['mixed', '声が混ざる'], ['short', '1秒未満']];
const voiceSec = s => s >= 60 ? `${Math.round(s / 6) / 10}分` : `${Math.round(s)}秒`;
/* 全行をこの人に(評価用。マスタープラン Q4。app-jobs.js の renderSpAll)。候補は文書ごとに api/drill/candidates から1回 */
const SPALL = { id: null, cands: [], suggest: '' };
/* この動画だけを今の設定で作り直す(app-learn.js の redoOneHere): busy = 保存・確認・送るの途中 */
const REDO1 = { busy: false };
const SPALL_FROM = { voice: '覚えた声', folder: 'メンバーのフォルダ', stream: '配信の文脈' };
/* 行の時刻を言葉に合わせる(app-rows.js の rt*): cache = 行の中身ごとの候補({c: 候補 | null, why})・el = 選んだ行の操作の欄に置いた部品・
   open = 見せている候補 {id, key, c}・t = 少し止まったら調べる予約 */
const RT = { cache: new Map(), el: null, open: null, t: 0 };
$('#voiceList').addEventListener('click', e => {
  const b = e.target.closest('[data-act=vdel]'); if (!b) return;
  const row = b.closest('[data-name]');
  armDelete(b, async () => {
    try { await api('/api/voices/delete', { body: { embedding: row.dataset.emb, name: row.dataset.name } }); toast(`「${row.dataset.name}」の声を忘れました`, 2500); }
    catch (er){ toast(er.message, 4000, 'err'); }
    loadVoices();
  }, `もう一度押すと「${row.dataset.name}」の声を忘れます`);
});
/* 押すと: 保存 → 覚える前の確認(誰・何行・何秒・覚えない名前・使わなかった行)→ 既にある名前は1人ずつ「同じ人ですか」→ 確かめた人だけ送る。
   確認のあとで文書が変わっても、サーバーの検査(409/400)が正(知らせに出す) */
$('#voiceLearn').addEventListener('click', async () => {
  if (!S.doc) return;
  if (S.doc.evalSet) return toast(EVAL_VOICE_MSG, 6000, 'err');
  try {
    if (!(await saveFirst())) return;
    const emb = $('#diarEmb').value, docId = S.docId;
    const r = await api('/api/voices/preview?tid=' + encodeURIComponent(docId) + '&embedding=' + encodeURIComponent(emb));
    if (r.evalSet) return toast(EVAL_VOICE_MSG, 6000, 'err');
    if (!r.people.length) return toast('覚えられる話者がいません。' + voicePreviewText(r).replace(/\n/g, ' '), 10000, 'err');   // 知らせは改行を出さないので1行に
    if (!await confirmDlg('声を覚える', voicePreviewText(r), '覚える')) return;
    const names = [], same = [];
    for (const p of r.people){
      if (!p.exists){ names.push(p.name); continue; }
      const o = p.old || {};
      const ok = await confirmDlg('同じ人ですか', `「${p.name}」の声はもう覚えています(${o.rows || 0}行・${voiceSec(o.sec || 0)}・${ago(o.updatedAt) || '日時不明'})。\n`
        + `この文書の「${p.name}」は同じ人ですか。同じ人なら、前に覚えた声に足します。別の人なら、名前を変えてから覚えてください`, '同じ人なので足す');
      if (ok){ names.push(p.name); same.push(p.name); }
    }
    if (!names.length) return toast('覚える人がいないので、やめました', 4000);
    if (S.docId !== docId) return;   // 確かめている間に別の文書へ移った
    await api('/api/voices/learn', { body: { tid: docId, embedding: emb, names, confirmSame: same } });
    await kickJobs(); toast(names.join('・') + ' の声を覚える処理を待機列に追加しました', 4000);
  } catch (er){ toast(er.message, 6000, 'err'); }
});
$('#spDetails').addEventListener('toggle', () => { if ($('#spDetails').open){ renderVoiceLearn(); loadVoices(); } });
$('#diarSmooth').addEventListener('change', e => diarSmoothSave(e.target.checked));
$('#diarEmb').addEventListener('change', () => { if ($('#spDetails').open) loadVoices(); });
try { $('#diarRecog').checked = localStorage.getItem('tx.voiceRecog') !== '0'; } catch {}
$('#diarRecog').addEventListener('change', () => { try { localStorage.setItem('tx.voiceRecog', $('#diarRecog').checked ? '1' : '0'); } catch {} });

/* 「道具 ▾」: 映像の下のカード(話者・置換と再認識・書き出し・以前の版)へ移動して開く(映像の列の中でスクロールする) */
document.querySelectorAll('[data-jump]').forEach(b => b.addEventListener('click', () => {
  const el = $('#' + b.dataset.jump); if (!el) return;
  $('#jumpMenu').open = false;
  el.hidden = false;   // 4枚のカードは閉じている間は隠している(下)。ここで出してから開く
  if (el.tagName === 'DETAILS') el.open = true;
  const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' });
  const sm = el.querySelector('summary'); if (sm) sm.focus({ preventScroll: true });
}));
/* 話者・文字をまとめて直す・書き出し・以前の版の4枚は、一覧の上の「…」からだけ開く(ブリーフ: 操作の入口は役割ごとに1つ)。
   閉じている間は隠し、どこから開いても(「…」・ほかの画面の案内・覚えていた開閉)出す。閉じればまた隠す */
for (const id of ['spDetails', 'fixDetails', 'exDetails', 'hiDetails']){
  const d = $('#' + id); if (!d) continue;
  d.hidden = !d.open;
  d.addEventListener('toggle', () => { d.hidden = !d.open; });
}
$('#diarGo').addEventListener('click', e => {
  const b = e.currentTarget;
  const run = async () => { b.disabled = true; try { await startDiarize(); } catch (er){ toast(er.message); } finally { b.disabled = !(S.tools && S.tools.diarize && S.tools.diarize.ready); } };
  if (S.doc && (S.doc.speakers.length || S.doc.segments.some(s => s.speaker))) armDelete(b, run, 'もう一度押すと判別し直します(今の話者は置き換わります)'); else run();
});
/* 評価用の文書の「確かめ済み」(app-learn.js) */
$('#evrMark').addEventListener('click', e => busy(e.currentTarget, evalReviewHere).finally(renderEvalReview));
$('#evrUndo').addEventListener('click', () => unmarkReviewed());
$('#evrRedo').addEventListener('click', () => redoOneHere());   // この動画を作り直す(今の設定で)
$('#spAllName').addEventListener('change', () => { syncSpAllNew(); if ($('#spAllName').value === 'other') $('#spAllNew').focus(); });
$('#spAllGo').addEventListener('click', async e => {
  const b = e.currentTarget; b.disabled = true;
  try { await spAllGo(); } catch (er){ toast(er.message); } finally { b.disabled = !!lockJob(); }
});

/* ---------- 再認識 ---------- */
const SPK_FLAGS = ['声が混ざっている可能性', '話者が不確か', '話者を判別できなかった'];
const RANGE_MAX = 900;
/* 動画全体(docs/design/whole-retranscribe-design.md の 3-1): 範囲・残す行・差し替える行・かかる時間の目安。
   目安は large-v3 の CPU で測った速さ(実時間の約 0.37 倍。src/eval/tools/eval_asr.py)だけ。ほかのモデルは出さない(でたらめな数字を出さない) */
const WHOLE_RTF = { 'large-v3': 0.37 };
$('#rtGo').addEventListener('click', e => {
  const b = e.currentTarget, first = !b.dataset.armed;
  armDelete(b, async () => { b.disabled = true; try { await startRetranscribe(); } catch (er){ toast(er.message); } finally { updateRt(); } });   // 文字を上書きするので、2度押しにする
  if (first && $('#rtTarget').value === 'whole') b.textContent = 'もう一度押す(直した行は残り、ほかの行が書き換わります)';
});
$('#rtTarget').addEventListener('change', updateRt);
$('#rtModel').addEventListener('change', updateRt);   // 動画全体の目安はモデルで変わる

/* ---------- 修正の提案(文脈つきの統計) ---------- */
S.sug = [];
let sugSeq = 0;
$('#btnSugHigh').addEventListener('click', () => {
  const done = [];
  pushUndo();
  for (const s of S.doc.segments) for (const x of sugList(s).filter(y => y.tier === 'high')) if (applySug(s, x)) done.push(x);
  if (!done.length){ S.undo.pop(); updateUndo(); return; }
  S.sug = S.sug.filter(y => !done.includes(y)); sugFeedback('accept', done); markDirty(); renderDoc(); renderChips();
  toast(`${done.length}件を採用しました(「元に戻す」で戻せます)`);
});
/* 2つ目のエンジンとの食い違いの候補(D1-b): S.alt = 結果の情報(GET /api/suggest の alt)。文書は書き換えないので、聞いている間も編集できる */
S.alt = null;
$('#altGo').addEventListener('click', async () => {
  if (!S.docId || altJob()) return;
  try {
    await api('/api/rerun', { body: { tid: S.docId, target: 'whole', engine: 'alt', result: 'propose', altEngine: $('#altEngine').value } });
    kickJobs();
  } catch (e){ toast(e.message, 7000, 'err'); }
});
$('#altEngine').addEventListener('change', async e => {   // 設定 altEngine(送ったキーだけ直す api/settings/patch。ほかの窓の設定を消さない)
  if (!(await patchSettings({ altEngine: e.target.value }, '2つ目のエンジンを保存できませんでした'))) renderAlt();   // 先に S.settings へ入れる(保存を待つ間の描き直し renderAlt で選択が戻らないように)。失敗は元に戻して描き直す
});

/* ---------- 校正済み(正解として使える行の印) ---------- */
setInterval(() => {   // 操作している時間だけ数える(放置している間は進めない)。休憩のお知らせも、この時間で出す
  if (Date.now() - S.sess.lastAct < 120000){
    S.sess.activeMs += 30000; updateSess();
    effortTick(30000);   // 開いている文書の操作中の知らせ(effort.lastAt)
    const b = Number(V.brk) * 60000;
    if (b && S.sess.activeMs - S.sess.lastBreak >= b){ S.sess.lastBreak = S.sess.activeMs; toast(`操作を始めて${Math.round(S.sess.activeMs / 60000)}分たちました。少し休憩しませんか(目を離す・肩を回す・水分)`, 9000); }
  }
}, 30000);
['keydown', 'pointerdown', 'wheel'].forEach(t => window.addEventListener(t, () => { S.sess.lastAct = Date.now(); }, { passive: true, capture: true }));

/* ---------- 進み具合の帯(校正済み・要確認・未校正を、時間軸で見る) ---------- */
let stripQ = 0;
$('#strip').addEventListener('click', e => {
  const r = S.stripR; if (!r || !S.doc) return;
  const t = r[0] + e.offsetX / e.currentTarget.clientWidth * (r[1] - r[0]), segs = S.doc.segments, i = Math.max(0, segIndexAt(segs, t));
  if (!gotoRow(i, { center: true })) return toast('その位置の行は、絞り込みで隠れています');
  player().currentTime = segs[i].start; S.playEnd = null;
});
/* 全行を校正済みに / 全解除: 元に戻せる操作なので確認はしない。知らせの [元に戻す] で戻す */
$('#btnProofAll').addEventListener('click', () => {
  if (!S.doc) return;
  const all = S.doc.segments.length && S.doc.segments.every(s => s.proofed);
  pushUndo(); const before = unproofedCount();
  for (const s of S.doc.segments){ if (all) delete s.proofed; else if (s.text.trim()) s.proofed = true; }
  renderDoc(); markDirty();
  if (!all && before > 0 && unproofedCount() === 0)   // 全部済んだ: 1 行ずつの経路と同じ次の一手 [2 カットへ]。元に戻すは Ctrl+Z・「元に戻す」のボタンで
    return toast('全行を校正済みにしました(戻すときは Ctrl+Z)。次はカットを決めます', { kind: 'ok', ms: 8000, action: TO_CUT });
  undoToast(all ? '校正済みを全て解除しました' : '全行を校正済みにしました', 8000);   // この知らせの「元に戻す」は文字起こしの側だけ(あとでカットを変えていても、カットは戻さない)
});
/* 「まとめて」のポップオーバー(UI の見直し S1): 映像の列(.tx-stage)は overflow:auto なので、中に開くと下・右が切れていた。
   開いている間は画面に固定して置く(下に入らなければ上に開き、それでも入らなければ高さを抑えて中を回す) */
function placeMoreTools(){
  const d = $('#moreTools'), p = d && d.querySelector('.vpop'); if (!p) return;
  if (!d.open){ p.classList.remove('tt-vpop-fixed'); p.style.top = p.style.left = p.style.right = p.style.bottom = p.style.maxHeight = ''; return; }
  const kb = document.querySelector('.ui-keybar:not([hidden])'), kt = kb && kb.offsetHeight ? kb.getBoundingClientRect().top : innerHeight;   // 下のキーの帯に隠れないように
  const r = d.querySelector('summary').getBoundingClientRect(), vw = document.documentElement.clientWidth || innerWidth, vh = Math.min(innerHeight, kt), m = 8;
  p.classList.add('tt-vpop-fixed'); p.style.right = p.style.bottom = 'auto'; p.style.maxHeight = '';
  const w = p.offsetWidth, ph = p.offsetHeight;
  let top = r.bottom + 6; if (top + ph > vh - m && r.top - 6 - ph >= m) top = r.top - 6 - ph;
  p.style.top = Math.round(top) + 'px'; p.style.left = Math.round(Math.max(m, Math.min(r.left, vw - w - m))) + 'px';
  p.style.maxHeight = Math.max(120, vh - top - m) + 'px';
}
$('#moreTools').addEventListener('toggle', placeMoreTools);
for (const t of [window, document.querySelector('.tx-stage')]) if (t) t.addEventListener(t === window ? 'resize' : 'scroll', () => { if ($('#moreTools').open) placeMoreTools(); }, { passive: true });
window.addEventListener('scroll', () => { if ($('#moreTools').open) placeMoreTools(); }, { passive: true });
$('#btnProofSel').addEventListener('click', () => {
  if (!S.doc || !S.sel.size) return;
  pushUndo(); let n = 0; const before = unproofedCount();
  for (const s of S.doc.segments) if (S.sel.has(s.id) && s.text.trim()){ s.proofed = true; n++; }
  renderDoc(); markDirty();
  if (!proofNext(before)) toast(`${n}行を校正済みにしました(「元に戻す」で戻せます)`);   // 未校正が 0 になったら [2 カットへ]
});

/* ---------- 編集画面 ---------- */
const player = () => $('#player');
const hhmm = () => { const d = new Date(); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
let docSaveP = null, docOpenSeq = 0;
$('#cfReload').addEventListener('click', async () => {
  clearTimeout(markDirty.t); S.dirty = false; S.conflict = false; S.forceNext = false; await openDoc(S.docId, true); toast('保存済みの内容を読み込みました');
});
$('#cfForce').addEventListener('click', e => armDelete(e.currentTarget, () => {
  S.conflict = false; S.forceNext = true; $('#conflictBar').hidden = true; S.dirty = true; saveDoc();
}));
onLeave(() => { if (S.dirty && !S.conflict){ clearTimeout(markDirty.t); saveDoc(); } });   // タブ・窓を離れるとき・画面を閉じるときに、待たずに保存する
onLeave(() => effortFlush(true));   // 操作中の知らせのまだ送っていない分も送る(保存とは別の小さな POST。'blur' でも送るだけ = 重い処理はしない。閉じるときも届くよう keepalive)
/* ---------- 字幕の文字数(既定。app-rows.js の readSubtitle) ---------- */
const SUB_DEFAULT = { orientation: 'vertical', maxChars: { vertical: 16, horizontal: 28 }, wrapChars: { vertical: 8, horizontal: 14 } };

const TAG_LABEL = { unclear: '聞き取れない', overlap: '声が重なる', bgm: 'BGM・音が大きい' };
const tagsHTML = (s, tt) => Object.keys(TAG_LABEL).map(t => `<button type="button" data-act="tag" data-t="${t}" aria-pressed="${(s.tags || []).includes(t) ? 'true' : 'false'}" title="${tt ? tt[t] : esc(titleTag(t))}">${TAG_LABEL[t]}</button>`).join('');   // tt = 描き直しで 1 回だけ作った title(rowTitles)
/* 行の高さ: 対応ブラウザは CSS(field-sizing)にまかせる。それ以外は、画面の近くにある行だけを測る(数千行でも重くならないように) */
const NATIVE_FS = !/[?&]nofs=1/.test(location.search) && !!(window.CSS && CSS.supports && CSS.supports('field-sizing', 'content'));
if (NATIVE_FS) document.documentElement.classList.add('fsz');
const visRows = new Set();
const rowIO = !NATIVE_FS && 'IntersectionObserver' in window ? new IntersectionObserver(ents => {
  const add = [];
  for (const en of ents){ if (en.isIntersecting){ visRows.add(en.target); add.push(en.target); } else visRows.delete(en.target); }
  if (add.length) autoSizeList(add.map(r => r.querySelector('textarea')).filter(Boolean));
}, { rootMargin: '800px 0px' }) : null;
let sizeT = null;
window.addEventListener('resize', autoSizeSoon);
if (window.ResizeObserver){
  new ResizeObserver(() => { document.documentElement.style.setProperty('--pbh', $('.tt-player').offsetHeight + 'px'); }).observe($('.tt-player'));   // 1列のときに画面の上に固定する部分の高さ
  new ResizeObserver(() => { document.documentElement.style.setProperty('--toph', $('.top').offsetHeight + 'px'); }).observe($('.top'));
  new ResizeObserver(drawStripSoon).observe($('#stripBox'));
}
/* 元に戻す: 文字起こしの履歴 S.undo とカットの履歴(cut.js の M.undo)は別々に持ち、
   積むときに操作の通し番号(seq)を付ける。1 文字起こし の「元に戻す」・Ctrl+Z は、2つの一番上を比べて新しい方を1つ戻す(2 カット のタブの Ctrl+Z はカットだけ) */
let opSeq = 0;
const nextOp = () => ++opSeq;

$('#segs').addEventListener('input', e => {
  const row = e.target.closest('.seg'); if (!row) return;
  const i = Number(row.dataset.i), s = S.doc.segments[i]; if (!s) return;
  if (e.target.dataset.f === 'text'){
    s.text = e.target.value.slice(0, 2000); autoSize(e.target); markDirty();
    const bx = row.querySelector('.sug'); if (bx && (bx.children.length || S.sug.some(x => x.seg === s.id))) bx.innerHTML = sugHTML(s);
    if (i === (capFollow ? S.curIdx : S.navIdx)) updateCaption();   // 映像に重ねた字幕が、いま直している行なら打った文字にすぐ追従させる
    paintRead(row, s);   // 読む速さの札(打っている行だけすぐ。件数は保存の予約のあとの syncRead)
    if (RT.open && RT.open.id === s.id){ RT.open = null; rtPaint(); }   // 見せていた時刻の候補は古くなるので閉じる
  }
});
$('#segs').addEventListener('change', e => {
  const row = e.target.closest('.seg'); if (!row) return;
  const i = Number(row.dataset.i), s = S.doc.segments[i]; if (!s) return;
  const f = e.target.dataset.f;
  if (e.target.classList.contains('sel')){ e.target.checked ? S.sel.add(s.id) : S.sel.delete(s.id); updateSel(); return; }
  if (f === 'speaker'){ pushUndo(); setSegSpeaker(s, e.target.value, row); markDirty(); renderSpeakers(); }
});
/* 行の時刻の欄(UIKit.timebox。分:秒.0.1秒)を直した: Enter か欄を離れたときに確定(ui-time-commit = 入力欄の change に当たる)。
   並びが変わらなければ、その行だけ直す(描き直さない = 開始を打って Tab で終了へ、と続けて打てる)。並びが変わるときだけ並べ直して描き直す */
$('#segs').addEventListener('ui-time-commit', e => {
  const row = e.target.closest('.seg'); if (!row) return;
  const i = Number(row.dataset.i), s = S.doc.segments[i], f = e.target.dataset.f; if (!s || (f !== 'start' && f !== 'end')) return;
  const v = e.detail.value;
  const ok = v !== null && Number.isFinite(v) && (f === 'start' ? v < s.end : v > s.start);
  if (!ok){ toast(v === null ? '時刻を空にはできません(元の時刻に戻しました)' : f === 'start' ? '開始は、終了より前にしてください(元の時刻に戻しました)' : '終了は、開始より後にしてください(元の時刻に戻しました)'); UIKit.timebox.set(e.target, s[f]); return; }
  pushUndo(); s[f] = Math.round(v * 100) / 100; markDirty();
  const segs = S.doc.segments;
  if ((segs[i - 1] && segs[i - 1].start > s.start) || (segs[i + 1] && segs[i + 1].start < s.start)){
    /* 時刻で並びが変わると、今の行(S.navIdx)の添字がずれる。直した行を探し直して、今の行にする */
    sortSegs(); S.navIdx = segs.indexOf(s); snapEdge(S.navIdx, f, true); renderDoc();
    rowsEl()[S.navIdx]?.querySelector('textarea')?.focus({ preventScroll: true });
  } else { if (snapEdge(i, f, true)) UIKit.timebox.set(e.target, s[f]); markOvl(i); }   // 隣の境目と見える時刻が同じなら隣の値にそろえる(欄の表示も)
});
$('#btnAddAt').addEventListener('click', () => { if (S.doc) insertAtTime(player().currentTime || 0); });
$('#segs').addEventListener('click', e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  if (b.dataset.act === 'addfirst'){ if (!lockJob()) insertAtTime(player().currentTime || 0); return; }
  if (b.dataset.act === 'txagain'){ transcribeInto(b); return; }   // 文字が認識されなかった文書: この文書にもう一度文字起こし
  const row = b.closest('.seg'), i = Number(row.dataset.i), segs = S.doc.segments, s = segs[i]; if (!s) return;
  if (S.navIdx !== i){ setNav(i); savePos(); }   // 押したボタンの行を「今の行」にする(mousedown ではフォーカスを移さないため、ここで)
  switch (b.dataset.act){
    case 'keep': case 'cut': {   // 2 択の「残す」「カット」:押した側の状態にする(今と同じなら何もしない)
      const want = b.dataset.act === 'cut'; if ((s.cutState === 'cut') === want) break;
      hostRowsCut([i], want); break;   // 区間が決まっていればカット・パックのタブへ(app-tools.js)
    }
    case 'play': playSeg(s, true); break;   // 行の▶は、必ずその行だけ再生する(勝手に次の行へ続けない)
    case 'adj': nudge(s, row, b.dataset.f, Number(b.dataset.d)); break;
    case 'setnow': setTimeNow(s, b.dataset.f); break;
    case 'proof': { const before = unproofedCount(); setProof(s, !s.proofed, row); markDirty(); updatePfStat(); proofNext(before); break; }   // 未校正が 0 になったら [2 カットへ]
  case 'nosub': pushUndo(); setNoSub(s, !s.noSub, row); markDirty(); break;   // 字幕に出さない ⇄ 出す(どの話者の行でも)
    case 'tag': toggleTag(s, b.dataset.t, row); break;
    case 'unfill': {   // 別の読みで埋めた行を whisper の文字に戻す(ed_fill)。後処理の印も外し、行を描き直す(元に戻せる)
      pushUndo(); s.text = (s.fill && s.fill.from) || ''; delete s.fill;
      s.flag = (s.flag || '').split('、').filter(f => f && !/^(別の読みで埋めた|名簿の呼び名に直した|話者名を外した)/.test(f)).join('、');
      rowChanged(); undoToast('whisper の文字に戻しました'); break; }
    case 'unflag': pushUndo(); s.flag = ''; row.classList.remove('flag'); b.remove(); markDirty(); updateRt(); drawStripSoon();
      undoToast('要確認の印を外しました(確認済み)'); break;
    case 'sgok': { const x = S.sug.find(y => y.n === Number(b.dataset.n)); if (x) acceptSug(s, x); break; }
    case 'sgno': { const x = S.sug.find(y => y.n === Number(b.dataset.n)); if (x) rejectSug(x); break; }
    case 'split': doSplit(i, row); break;
    case 'adda': insertAfter(i); break;
    case 'addb': insertBefore(i); break;
    case 'merge': mergeRows(i); break;   // 中身は app-rows.js(キー M・Shift+M と共用。A6)
    case 'del': {   // 元に戻せる操作なので確認しない。消したら知らせに [元に戻す](Z のキーは押し間違いを防ぐため 2 回押しのまま)
      const navId = navSnapshot(); pushUndo(); S.sel.delete(s.id); segs.splice(i, 1); navRestore(navId, i); renderDoc(); markDirty();
      undoToast('行を削除しました', 6000);
      break;
    }
    case 'retime': rtRow(); break;   // 時刻を言葉に合わせる(app-rows.js の rt*)
    case 'rtok': case 'rtno': rtAnswer(b.dataset.act === 'rtok'); break;
  }
});
/* 読む速さの札で絞り込む(関数は app-rows.js の read*) */
$('#flagKind').add(new Option('読みにくい行だけ(速い・短い)', 'read'));
$('#rtSelected').addEventListener('click', () => { $('#moreTools').open = false; rtSelected(); });
/* 行の右クリックのメニュー:選んだ行の下に出るボタンと同じ操作(data-act はそのまま)。
   キーボードだけの操作は今までどおり(選んだ行の下のボタン)なので、この方が必ず要るわけではない代わりの入口。
   .seg は content-visibility:auto(見えない行を描かない)で、これが position:fixed の子の基準になってしまい
   画面の外へ出す前に切り取られる(clip)ため、メニューは document.body の直下に置く。その代わり、行の中の
   「本物」のボタン(data-act)は行番号(row)から探して .click() で押す(状態の更新はその1本の処理に任せ、
   ここでは行わない。押したら閉じる) */
let ctxMenuEl = null;
const CTX_ITEMS = [
  ['proof', s => s.proofed ? '校正済みを外す' : '校正済みにする'],
  ['cut', s => s.cutState === 'cut' ? '残す区間に戻す' : 'カット済にする'],
  ['split', () => '分割(カーソル位置)'],
  ['addb', () => '＋前に行を足す'],
  ['adda', () => '＋後ろに行を足す'],
  ['merge', () => '次の行と結合'],
  ['nosub', s => s.noSub ? '字幕に出す(印を外す)' : '字幕に出さない'],   // 項目の並び(↓ の回数)は変えない
  ['del', () => 'この行を削除']
];
/* 文字を打つ欄・時刻の欄の上は、普通の右クリックはブラウザ既定のメニュー(コピー・貼り付け)、Shift+右クリックで行のメニュー。
   日本語の変換中は出さない(メニューへフォーカスが移ると、変換中の文字が確定してしまう。contextmenu には isComposing が無いので自分で覚える) */
let segsComposing = false;
$('#segs').addEventListener('compositionstart', () => { segsComposing = true; });
$('#segs').addEventListener('compositionend', () => { segsComposing = false; });
$('#segs').addEventListener('focusout', () => { segsComposing = false; });
$('#segs').addEventListener('contextmenu', e => {
  const row = e.target.closest('.seg'); if (!row || lockJob()) return;
  if (isTextEntry(e.target) && (!e.shiftKey || segsComposing)) return;
  const i = Number(row.dataset.i), s = S.doc.segments[i]; if (!s) return;
  e.preventDefault();
  if (S.navIdx !== i){ setNav(i); savePos(); }
  closeCtxMenu();
  const m = document.createElement('div'); m.className = 'ui-pop-body tt-ctxmenu'; m.setAttribute('role', 'menu'); m.hidden = false;
  m.innerHTML = CTX_ITEMS.map(([act, label]) => `<button type="button" role="menuitem" data-act="${act}">${esc(label(s))}</button>`).join('');
  let cx = e.clientX, cy = e.clientY;
  if (!cx && !cy){   // キーボード(Shift+F10・アプリケーションキー)から開いたときは位置が 0,0 になるので、欄(か行)の下に出す
    const r = (isTextEntry(e.target) ? e.target : row).getBoundingClientRect();
    cx = r.left + 16; cy = r.bottom + 2;
  }
  const x = Math.max(4, Math.min(cx, window.innerWidth - 220)), y = Math.max(4, Math.min(cy, window.innerHeight - 260));
  m.style.left = x + 'px'; m.style.top = y + 'px';
  document.body.appendChild(m); ctxMenuEl = m;
  m.addEventListener('click', e2 => {
    const b = e2.target.closest('[data-act]'); if (!b) return;
    const real = row.querySelector(`[data-act="${b.dataset.act}"]`);
    closeCtxMenu();
    if (real) real.click();
  });
  setTimeout(() => { document.addEventListener('click', onCtxOutside, true); document.addEventListener('contextmenu', onCtxOutside, true); }, 0);
  m.querySelector('button').focus({ preventScroll: true });
});
/* 右クリックのメニューを開いている間は、キーはメニューだけが受け取る(↓ で裏の行が動くと、メニューの対象 = 右クリックした行とずれるため)。
   ↑ ↓・Home・End = メニューの中の移動 / Enter・Space = 選ぶ(ボタンの既定の動き)/ Esc・Tab = 閉じる / それ以外のキー = 何もしない(裏の行の操作に渡さない) */
window.addEventListener('keydown', e => {
  if (!ctxMenuEl) return;
  const items = [...ctxMenuEl.querySelectorAll('button')], cur = items.indexOf(document.activeElement);
  if (e.key === 'Enter' || e.key === ' '){ if (cur < 0 && items[0]){ e.preventDefault(); items[0].focus(); } e.stopImmediatePropagation(); return; }   // フォーカスしているボタンを押す(既定の動き)
  e.stopImmediatePropagation();
  if (e.key === 'Escape' || e.key === 'Tab'){ e.preventDefault(); const row = rowsEl()[S.navIdx]; closeCtxMenu(); if (row) row.focus({ preventScroll: true }); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;   // Ctrl+C など、ブラウザのキーは止めない(裏の行の操作だけ止める)
  e.preventDefault();
  let n = cur;
  if (e.key === 'ArrowDown') n = cur < 0 ? 0 : (cur + 1) % items.length;
  else if (e.key === 'ArrowUp') n = cur < 0 ? items.length - 1 : (cur - 1 + items.length) % items.length;
  else if (e.key === 'Home') n = 0;
  else if (e.key === 'End') n = items.length - 1;
  if (n !== cur && items[n]) items[n].focus({ preventScroll: true });
}, true);
$('#segs').addEventListener('keydown', e => {
  const dm = e.altKey && !e.ctrlKey && !e.metaKey && /^Digit([0-9])$/.exec(e.code);
  if (dm){   // Alt+1〜9: その行の話者を、話者の一覧の n 番目にする(Alt+0: 話者なし)。文字を打っている途中でも使える
    const row = e.target.closest('.seg'), s = row && S.doc.segments[Number(row.dataset.i)], n = Number(dm[1]), sps = numberedSpeakers();
    if (s && (n === 0 || sps[n - 1])){   // 番号は組み込みの「ゲーム音声など」を除いた並び(今までの番号のまま)
      e.preventDefault(); pushUndo(); setSegSpeaker(s, n === 0 ? '' : sps[n - 1].id, row);
      markDirty(); renderSpeakers(); return;
    }
  }
  if (e.key === 'Enter' && e.altKey && !e.ctrlKey && !e.metaKey && e.target.matches('textarea')){   // 校正済みの切り替え。付けたら次の行へ
    e.preventDefault(); const row = e.target.closest('.seg'), s = S.doc.segments[Number(row.dataset.i)];
    if (s){
      setProof(s, !s.proofed, row); markDirty(); updatePfStat();
      if (s.proofed){ const ni = findRow(Number(row.dataset.i), 1); if (ni >= 0) gotoRow(ni, { play: V.autoNext, edit: true }); }
    }
    return;
  }
  if (e.key === 'Escape' && e.target.matches('textarea')){ e.target.blur(); return; }   // 入力欄から抜ける(Space で再生・停止できるように)
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && e.target.matches('textarea')){   // 入力中にこの行を聞き直す
    e.preventDefault(); const s = S.doc.segments[Number(e.target.closest('.seg').dataset.i)]; if (s) playSeg(s, true);
  }
});
/* ---------- 行の移動(キーボードで校正を回す) ---------- */
const rowsEl = () => $('#segs').children;
const rowIdxOf = el => { const r = el && el.closest && el.closest('.seg'); return r ? Number(r.dataset.i) : -1; };
const posKey = id => 'tx.pos.' + id;
/* 字幕がどちらを見せるか(capFollow)。true = 再生位置(S.curIdx。timeupdate・シークで付く)、false = 選んだ行(S.navIdx。setNav で付く)。
   「止まっているか」だけで切り替えると、止めたまま時間軸を手でつまんで動かす(シーク)と、再生位置は動いたのに
   字幕は前に選んでいた行のまま(コマとずれる)になる。timeupdate はシークでも来るので、そこで再生位置の側へ切り替える */
let capFollow = false;
/* ---------- 話者の色(決め方は app-rows.js の speakerColor の 1 か所) ---------- */
const SPKC = new Map();   // 話者の名前 → {name, hex}(合う人)| null(合わない)| undefined(照らし合わせ中)
const speakerColorsOn = () => !S.settings || S.settings.speakerColors !== false;
const rowSpColor = spId => { const c = speakerColor(spId); return c.hex || c.auto; };
/* 一括操作用のチェック(左端の□。複数行を選んでまとめて処理する)は、キーボードの「今の行」を動かさない。
   これを分けないと、マウスでチェックを付けているだけで、Shiftキー操作の対象が知らない間にそちらへ移ってしまう */
/* 行のボタンを押すとき、押した瞬間(mousedown)にフォーカスが移ると「今の行」が変わり、前の行の操作ボタンの段が消えて
   一覧が上にずれ、指を離した位置が別のボタンになって押し損じる。ボタン・チェックは mousedown でフォーカスを移さず、
   「今の行」は click の時点で切り替える(ボタンにフォーカスが残らないので、そのあとの1文字キーや Space も誤爆しない) */
$('#segs').addEventListener('mousedown', e => {
  if (e.button !== 0) return;
  const t = e.target.closest('button, input.sel'); if (!t || !t.closest('.seg')) return;
  e.preventDefault();
  const a = document.activeElement, row = t.closest('.seg');
  if (a && a !== document.body && isTextEntry(a) && a.closest('.seg') !== row) a.blur();   // 別の行で入力中なら、確定して抜ける
});
$('#segs').addEventListener('focusin', e => { if (e.target.classList.contains('sel')) return; const i = rowIdxOf(e.target); if (i >= 0){ setNav(i); savePos(); } txKeybarScene(); });
$('#segs').addEventListener('focusout', () => setTimeout(txKeybarScene, 0));   // 入力欄から抜けた直後(次の activeElement が決まってから)
$('#btnNextUn').addEventListener('click', () => navigate('unproofed', 1));
/* .ui-time = 時刻の欄(UIKit.timebox。数字・矢印を自分で使うので、入力欄と同じ扱いにする) */
const isTextEntry = t => !!(t && t.matches && (t.matches('textarea,select,.ui-time,[contenteditable=""],[contenteditable=true]') || (t.matches('input') && !/^(checkbox|radio|button|submit|range|color|file)$/i.test(t.type))));
let zArm = null;
/* 左手だけの操作: キー単体(Shift 不要)。文字を入力しているとき(入力欄にカーソルがあるとき)は使えません(Esc で抜けます)。
   ↓/↑・Shift+↓/↑ も残す(固定の別の手段)。S の分割は 2 カット のタブだけ(校正のキーは 1 文字起こし のタブだけなので重ならない)。
   キー配置: 割り当ては ⚙ 設定の「キー配置」で変えられる。保存は S.settings.keymap(サーバーの config.json。どのブラウザ・窓でも同じ)。
   共通の再生キー(UIKit.keys.PLAYBACK_ACTIONS)も同じ keymap に入れ、1 文字起こし・2 カット の両方の共通キーに渡す */
const TX_ACTIONS = [   // [id, 既定のキー(UIKit.keys.comboOf の表記), 説明, まとまり]
  ['rowNext', 's', '次の行', 'move'], ['rowPrev', 'w', '前の行', 'move'], ['unNext', 'd', '次の未校正', 'move'], ['unPrev', 'a', '前の未校正', 'move'], ['flagNext', 'f', '次の要確認', 'move'],
  ['replay', 'r', 'この行をもう一度聞く', 'listen'], ['back3', 'q', '3秒戻る', 'listen'], ['fwd3', 'e', '3秒進む', 'listen'], ['proof', 'Shift+Space', '校正済みにして次へ', 'listen'],
  ['edit', 't', 'この行の文字を直す(入力欄へ)', 'listen'], ['autoNext', 'b', '「移動したら自動で再生」のオン/オフ', 'listen'],
  ['tagUnclear', 'x', '聞き取れない', 'memo'], ['tagOverlap', 'c', '声が重なる', 'memo'], ['tagBgm', 'v', 'BGM・音が大きい', 'memo'], ['insert', 'n', '後ろに行を追加', 'memo'], ['del', 'z', 'この行を削除(2回押し)', 'memo'],
  /* つなぐ・分ける(校正でいちばん時間を食う操作) */
  ['mergeNext', 'm', '次の行とつなぐ', 'memo'], ['mergePrev', 'Shift+m', '前の行とつなぐ', 'memo'], ['splitPlay', 'y', '再生位置で行を分ける', 'memo']
];
/* Shift+N は殻の「次の案件へ」・Alt+1/2 は殻のタブなので、割り当てさせない(KEY_SHELL) */
const KEY_SHELL = { 'Shift+n': '次の案件へ(案件の画面)', 'Shift+N': '次の案件へ(案件の画面)', 'Alt+1': 'タブの切り替え(案件の画面)', 'Alt+2': 'タブの切り替え(案件の画面)' };
const KEY_GROUPS = [['move', '行を移動する'], ['listen', '聞く・校正する'], ['memo', '音の状態のメモ・行の編集'], ['screen', '画面']];
const KEY_ALT = { rowNext: '↓', rowPrev: '↑', unNext: 'Shift+↓', unPrev: 'Shift+↑' };   // 固定の別の手段(一覧・帯に並べて出す)
/* 割り当てられないキー(固定の意味がある)。値は使い道(「X は『使い道』に使っているので割り当てられません」) */
const KEY_FIXED = { ArrowDown: '次の行(固定)', ArrowUp: '前の行(固定)', 'Shift+ArrowDown': '次の未校正(固定)', 'Shift+ArrowUp': '前の未校正(固定)',
  Tab: '入力欄に入る/抜ける', 'Shift+Tab': 'ふつうのフォーカスの移動', Escape: '入力欄から抜ける・取り消し', Enter: 'ボタンを押す', '?': 'キー操作の一覧' };
/* 2 カット のタブのキー(cut.js の onKey。変えられない)。一覧はこの表から作る */
const CUT_KEY_ROWS = window.EditCut ? EditCut.KEY_ROWS : [];   // 表の正は cut.js(キーを変えたら一覧・知らせ・title が一緒に変わるように)
const CUT_FIXED = (window.EditCut && EditCut.FIXED_KEYS) || {};   // 2 カット の固定のキー: 1 文字起こし のキー・共通の再生キーに割り当てさせない
const keyText = k => UIKit.keys.keyText(k);
/* キーの一覧 = キー配置(UIKit.keymap):? の一覧と ⚙ 設定の「キー配置」は同じ部品。重なりの検査(固定・共通の再生キー・
   派生キー = ← → に当たるキー + Shift)も部品の 1 か所。共通の再生キーはホームの設定(スタジオと同じ)。校正のキーは編集の設定 keymap(送ったキーだけ直す) */
const KM = UIKit.keymap.create({
  groups: KEY_GROUPS,
  actions: TX_ACTIONS.map(a => ({ id: a[0], def: a[1], label: a[2], group: a[3], alt: KEY_ALT[a[0]] })),
  refuse: combo => KEY_FIXED[combo] || KEY_SHELL[combo] || CUT_FIXED[combo] || (/^[0-9]$/.test(combo) ? '話者の番号(1〜9・0)' : ''),
  intro: 'キーのボタンを押してから、割り当てたいキーを押します(Esc = 取り消し・Delete = 外す)。すでに使っているキーを選ぶと、そちらの割り当てが外れます(すぐ下の「戻す」で戻せます)。文字を入力している間は効きません(Esc で入力欄から抜ける)。',
  playbackNote: '(スタジオ・編集で同じ。1 文字起こし・2 カット のタブで効きます)',
  fixed: [
    { group: 'listen', why: '入力欄の出入りに使うキー', rows: [['Tab', '選んだ行の入力欄へ'], ['Esc / Tab', '入力欄から抜ける']] },
    { group: 'memo', why: 'Ctrl つきのキー', rows: [['Ctrl+Z', '元に戻す']] },
    { group: 'screen', rows: [['Alt+1 / Alt+2', 'タブ(校正・カット・パック)を切り替える', 'Alt つきのキー'], ['Shift+N', '次の案件へ', '案件の画面のキー'], ['?', 'この一覧を開く・閉じる', '一覧を開くキー']] },
    { title: '話者', why: '数字は話者の番号', rows: [['1…9', 'この行の話者を n 番目に'], ['0', '話者なし']] },
    { title: '入力中に使えるキー', why: '入力欄の中で使うキー', rows: [['Alt+Enter', '校正済みにして次の行の入力欄へ'], ['Ctrl+Enter', 'この行を聞き直す'], ['Alt+1…9', 'この行の話者'], ['Shift+右クリック', '行のメニュー(普通の右クリックはコピー・貼り付け)']] },
    { title: '2 カット のタブ', note: '(共通の再生キーに加えて)', why: '2 カット のタブの操作', rows: CUT_KEY_ROWS }
  ],
  footNote: 'キー配置は、どのブラウザ・窓でも同じです。',
  load: () => (S.settings && S.settings.keymap) || {},
  save: km => saveKeymap(km),
  fallbackPlayback: { load: () => (S.settings && S.settings.keymap) || {}, save: pb => saveKeymap(pb) },   // 入口の外で開いたとき(編集の設定に)
  onChange: () => renderKeyUI()
});
const KEY_FN = {
  rowNext: () => navigate(null, 1), rowPrev: () => navigate(null, -1), unNext: () => navigate('unproofed', 1), unPrev: () => navigate('unproofed', -1), flagNext: () => navigate('flag', 1),
  replay: () => replayCur(), back3: () => seek(-3), fwd3: () => seek(3), proof: () => proofOk(), edit: () => editCur(),
  autoNext: () => { V.autoNext = !V.autoNext; saveView(); applyView(); toast('移動したら自動で再生: ' + (V.autoNext ? 'オン' : 'オフ'), 1500); },
  tagUnclear: () => tagCur('unclear'), tagOverlap: () => tagCur('overlap'), tagBgm: () => tagCur('bgm'),
  insert: () => { const c = rowAndSeg(); if (c) insertAfter(c.i); else insertAtTime(player().currentTime); },
  del: () => deleteCur(),
  mergeNext: () => mergeKey(1), mergePrev: () => mergeKey(-1), splitPlay: () => splitKey()   // app-rows.js
};
/* 押しっぱなし(キーの自動の繰り返し)で続けて働いてよいのは、移動とシークだけ。
   それ以外(特に Z の2回押しの削除・Shift+Space の校正済み)は、押しっぱなしで「2回目」や「聞かずに校正済み」にならないように、繰り返しを無視する */
const REPEAT_OK = new Set(['rowNext', 'rowPrev', 'unNext', 'unPrev', 'flagNext', 'back3', 'fwd3']);
window.addEventListener('keydown', e => {
  if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || imeKey(e) || e.defaultPrevented || modalOpen()) return;   // 引き出しが開いている間はタブを変えない(ダイアログと同じ扱い)
  const m = /^Digit([12])$/.exec(e.code); if (!m) return;   // タブは 2 つ(Alt+3 は何もしない)
  if (e.target && e.target.closest && e.target.closest('#segs') && isTextEntry(e.target)) return;   // 行の文字の入力中の Alt+数字 は話者(#segs の keydown)
  e.preventDefault(); if (!e.repeat && m[1] === '2') EDIT_HOST.tab('cut');   // Alt+1 は校正(いまのタブ)
});
/* 共通の再生キー(ui-kit.js の UIKit.keys.playback。既定は Space・J/K/L・← →(Shift で5秒)・, .・I/O。割り当ては keymap())。
   1 文字起こし のタブだけ・ダイアログが開いていないときだけ有効にし、自分のキー処理(下)より先に呼ぶ。処理したら true が返るので、そのときは自分の処理をしない(1つのキーは全体で1つの意味) */
/* カットの欄は別のパネル = fps を読めない。文書ごとに 1 回、カット(edit.json)か下書きの fps を引いて控える(引けるまでは 1/30 秒) */
let HOST_FPS = { id: '', f: null };
function hostFps(){
  if (!S.docId) return null;
  if (HOST_FPS.id !== S.docId){
    const id = S.docId, q = '?id=' + encodeURIComponent(id);
    HOST_FPS = { id, f: null };
    api('/api/edit' + q).then(r => (r && r.edit && r.edit.sources && r.edit.sources[0] && r.edit.sources[0].fps) || api('/api/edit/draft' + q).then(d => d && d.fps))
      .then(f => { if (HOST_FPS.id === id && Array.isArray(f) && f[0] > 0 && f[1] > 0) HOST_FPS.f = f; }).catch(() => {});
  }
  return HOST_FPS.f;
}
const editPlaybackKeys = UIKit.keys.playback({
  media: () => player(), keymap: () => keymap(),
  /* 1コマ = 素材の fps(2 カット と同じ)。フレームの境目にそろえて動かす(押し続けても浮動小数のずれが溜まらない)。
     fps が分からない文書・開いた直後(カットの読み込み中)は ui-kit の既定(1/30 秒) */
  fps: () => { const f = hostFps(); return f ? f[0] / f[1] : 30; },
  onFrame: dir => {
    const p = player(), f = hostFps();
    if (!f) return false;
    p.pause(); p.currentTime = Math.max(0, (Math.floor((p.currentTime || 0) * f[0] / f[1] + 0.5) + dir) * f[1] / f[0]) + 0.0005;   // フレームの境目にそろえて動かす(cut.js の frameStep と同じ)。止めてから(再生中の1コマは意味がない)
    return true;
  },
  enabled: () => { hostFps(); return !!S.doc && !modalOpen(); }   // hostFps(): fps を先に引いておく
});
window.addEventListener('keydown', e => {
  /* #edTabs(タブの並び)の ← → など、他の場所ですでに処理済み(preventDefault 済み)のキーには重ねて反応しない。
     ⚙ 設定・パックの詳しい設定の引き出しが開いている間も、文書を操作するキーは効かせない(dialog と同じ扱い) */
  if (e.defaultPrevented || anyMod(e) || e.isComposing || modalOpen() || isTextEntry(e.target)) return;
  if (editPlaybackKeys(e)) return;   // 処理したら、ここでは何もしない(I/O は校正では何もしない = 別の意味にしない)
  const c = e.code;
  if (e.key === '?'){ e.preventDefault(); if (!e.repeat) openKeys(); return; }   // キー操作の一覧(配列によって Shift が要るので、Shift の判定より先に)
  const act = txActionOf(UIKit.keys.comboOf(e));
  if (!S.doc || lockJob()) return;   // 校正のキーは校正のパネルが開いている間だけ(edhost.js の guard。カットのタブは cut.js のキー)
  if (c === 'ArrowDown' || c === 'ArrowUp'){
    e.preventDefault();
    navigate(e.shiftKey ? 'unproofed' : null, c === 'ArrowDown' ? 1 : -1);   // 押しっぱなしで続けて動いてよい
    return;
  }
  if (act){ e.preventDefault(); if (!e.repeat || REPEAT_OK.has(act)) KEY_FN[act](); return; }
  if (e.shiftKey) return;   // 割り当ての無い Shift+キー は何もしない(誤って押しても発動しないように)
  const dm = /^Digit([0-9])$/.exec(c);
  if (dm){ e.preventDefault(); if (!e.repeat) assignSpeaker(Number(dm[1])); return; }
});

/* Esc: 編集画面のどの入力欄(検索・絞り込み・速さ・タイトル・行の時刻や話者)からでも抜けて、操作キーを使えるようにする
   (検索や速さを変えたあとに ↓ や Shift+↓ が効かないと「取りこぼし」に見えるため)。日本語の変換中は変換の取り消しにだけ使う */
window.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || imeKey(e) || document.querySelector('dialog[open]')) return;
  const t = e.target;
  if (isTextEntry(t) && t.closest && t.closest('#doc')) t.blur();
});

/* Tab: 入力欄の中 → 抜ける(コマンドモード) / 行を選んでいて入力欄の外 → その行の入力欄に入る。日本語変換中・Shift+Tab・ダイアログ中は、ふつうの動き */
window.addEventListener('keydown', e => {
  if (e.key !== 'Tab' || e.shiftKey || anyMod(e) || imeKey(e) || !S.doc || modalOpen()) return;
  const t = e.target;
  if (t.matches && t.matches('#segs textarea')){ e.preventDefault(); t.blur(); return; }
  const free = t === document.body || t === document.documentElement || (t.matches && t.matches('video')) || (t.closest && t.closest('#segs') && !isTextEntry(t) && !t.matches('button,a'));
  if (free && !lockJob() && rowAndSeg()){ e.preventDefault(); editCur(); }
});

/* ---------- キー配置の表示(描き直しは app-rows.js の renderKeyUI) ---------- */
const kbdHTML = combo => combo ? keyText(combo).split('+').map(p => `<kbd>${esc(p)}</kbd>`).join('+') : '<span class="muted">未設定</span>';
const keyWithAlt = id => { const km = keymap(), a = KEY_ALT[id]; return [km[id] ? keyText(km[id]) : '', a || ''].filter(Boolean).join(' / ') || '未設定'; };
/* ツールチップ・知らせの中のキー(今の割り当てから作る。割り当てを外したら出さない) */
const keyParen = id => { const k = keymap()[id]; return k ? '(' + keyText(k) + ')' : ''; };
const titlePlay = () => `この行だけ再生${keyParen('replay')}。行の終わりで止まります`;
const titleProof = () => `聞いて確認して、この行の文字が正しいと判断したら押す${keyParen('proof').replace(/\)$/, '。次の行へ進みます)') || '(次の行へ進みます)'}`;
const TAG_ACT = { unclear: 'tagUnclear', overlap: 'tagOverlap', bgm: 'tagBgm' };
/* BGM の付け方の基準(notes:docs/spec/subtitles.md) */
const TAG_RULE = { bgm: '付けるのは BGM・ゲーム音のせいで聞き取りにくい行だけ(聞き直したくなった・声と同じくらいか大きい・歌声が流れている・効果音が言葉にかぶる)。鳴っているだけで楽に聞き取れる行・迷う行には付けません' };
const titleTag = t => `この行の音の状態のメモ${keyParen(TAG_ACT[t])}。` + (TAG_RULE[t] || '「聞き取れない」の行は、精度の測定と学習の正解に使いません');
const titleAddAfter = () => `この行の後に、空の行を足します${keyParen('insert')}`;
const titleDel = () => { const k = keymap().del; return `この行を消します(元に戻せます${k ? '。' + keyText(k) + ' でも消せます(2回押し)' : ''})`; };
window.addEventListener('keydown', e => {
  const d = $('#keys');
  if (e.key !== '?' || e.defaultPrevented || !d.open || anyMod(e) || e.isComposing || isTextEntry(e.target)) return;   // defaultPrevented = 同じ ? で今開いたところ
  e.preventDefault(); if (!e.repeat) d.close();
});
KM.mount($('#keysList'));
/* ⚙ の「キー配置を変える(?)」: キーを変える場所は ? の一覧だけ。設定の引き出しを閉じてから一覧を開く */
$('#setKeysOpen').addEventListener('click', () => {
  const dr = document.getElementById('uiSettingsDrawer');
  if (dr) UIKit.drawer.close(dr);
  openKeys();
});
renderKeyUI();

/* ---------- 用語のワンクリック挿入 ---------- */
$('#terms').addEventListener('mousedown', e => { if (e.target.closest('.chip')) e.preventDefault(); });   // 押しても、行の入力欄からフォーカスが外れないように
$('#terms').addEventListener('click', e => {
  const b = e.target.closest('.chip'); if (!b) return;
  const ta = S.navIdx >= 0 && rowsEl()[S.navIdx] && rowsEl()[S.navIdx].querySelector('textarea');
  if (!ta) return toast('先に、文字を入れる行をクリックしてください');
  const a = ta.selectionStart == null ? ta.value.length : ta.selectionStart, z = ta.selectionEnd == null ? a : ta.selectionEnd, t = b.dataset.t, pos = a + t.length;
  ta.value = ta.value.slice(0, a) + t + ta.value.slice(z); ta.focus(); ta.setSelectionRange(pos, pos);
  ta.dispatchEvent(new Event('input', { bubbles: true }));
});

/* ---------- 履歴(自動バックアップ) ---------- */
$('#hiRefresh').addEventListener('click', loadHistory);
$('#hiDetails').addEventListener('toggle', () => { if ($('#hiDetails').open && S.docId) loadHistory(); });
$('#hiList').addEventListener('click', e => {
  const b = e.target.closest('[data-act=hirest]'); if (!b) return;
  const ts = Number(b.closest('[data-ts]').dataset.ts);
  armDelete(b, async () => {
    try {
      if (!(await saveFirst())) return;
      await api('/api/restore', { body: { id: S.docId, ts } });
      await openDoc(S.docId, true); await loadHistory();
      toast('選んだ時点に戻しました(戻す前の状態も「以前の版」に残っています)');
    } catch (er){ toast(er.message); }
  });
});

/* ---------- 行の追加(app-rows.js の insertRow。すき間の長さ・仮の長さ・最小のすき間) ---------- */
const NEW_LEN = 1.5, NEW_MAX = 8, NEW_MIN_GAP = 0.3;
const r2 = v => Math.round(Math.max(0, v) * 100) / 100;
player().addEventListener('timeupdate', () => {
  if (!S.doc) return;
  moveStripHead();
  const t = player().currentTime;
  if (S.playEnd !== null && t >= S.playEnd){ player().pause(); S.playEnd = null; }
  /* 再生中はもちろん、止めたままシークしたときも timeupdate は来る。どちらでも字幕は再生位置(S.curIdx)へ切り替える
     (シークで curIndex が前と同じ行になったときは i === S.curIdx で下を素通りするので、ここで先に切り替えておく) */
  if (!capFollow){ capFollow = true; updateCaption(); }
  const i = curIndex(t); if (i === S.curIdx){ updateCaption(); return; }   // 重なる行の字幕は、今の行が同じでも前の行が終われば消える(中身が同じなら描き直さない)
  const rows = rowsEl();
  rows[S.curIdx]?.classList.remove('cur'); S.curIdx = i;
  updateCaption();
  const el = rows[i]; if (!el) return;
  el.classList.add('cur');
  const typing = document.activeElement?.matches('#segs textarea, #segs input, #segs select, #segs .ui-time');
  if (V.frameFollow && !typing && S.navIdx !== i) setNav(i);
  if ($('#follow').checked && !el.hidden && !typing) ensureVisible(el, 0.35);
});
player().addEventListener('error', () => { if (!S.doc) return; S.playerErr = S.docId; renderPlayerMsg(); });
$('#playerRelink').addEventListener('click', () => openRelink());

/* ---------- 動画を選び直す(付け替えの API は POST だけ(URL の引数では付け替えない) ---------- */
const RL = { id: null, seq: 0, check: null, path: '' };
$('#rlCheck').addEventListener('click', rlCheck);
$('#rlPath').addEventListener('input', rlReset);   // 確かめたあとにパスを変えたら、確かめ直すまで付け替えない
$('#rlPath').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing){ e.preventDefault(); rlCheck(); } });
$('#rlAccept').addEventListener('change', rlSync);
$('#rlCancel').addEventListener('click', () => $('#relinkDlg').close());
$('#relinkDlg').addEventListener('close', () => { RL.seq++; });
$('#rlCopy').addEventListener('click', async () => {
  if (!(await UIKit.copy($('#rlOld').value, { ok: '元のパスをコピーしました' }))){ $('#rlOld').select(); toast('コピーできませんでした(欄を選んだので Ctrl+C でコピーしてください)', 5000, 'err'); }
});
$('#rlGo').addEventListener('click', async () => {
  const c = RL.check, id = RL.id, b = $('#rlGo');
  if (!c || S.docId !== id) return;
  b.disabled = true;
  try {
    if (!(await savedAll())) return;
    const r = await api('/api/relink', { body: { id, path: RL.path, baseUpdatedAt: S.baseUpdatedAt, acceptDiff: $('#rlAccept').checked } });
    $('#relinkDlg').close();
    await openDoc(id);   // 同じ文書でも読み直す(映像・カット・パックを新しいパスで)
    loadList();
    toast('付け替えました(前の状態は「以前の版に戻す」で戻せます)' + (r && r.normalizing ? '。30fps でないので、隣に 30fps の動画を作っています(終わると自動でそちらに付け替えます。進み具合は「処理状況」)' : ''), 9000, 'ok');
    if (r && r.normNote) toast(r.normNote, 8000);   // 30fps にそろえられない理由(ネットワーク上など。付け替えは済んでいる)
    if (r && r.normalizing) startPolling();
  } catch (e){
    if (e.code === 'duration_mismatch' && e.data && e.data.check){ RL.check = e.data.check; renderRlResult(e.data.check); }
    toast('付け替えられませんでした: ' + e.message, 8000, 'err');
  } finally { rlSync(); }
});

$('#rlBrowse').addEventListener('click', async () => {
  const b = $('#rlBrowse'); b.disabled = true;
  try {
    const p = await pickPath('file', $('#rlPath').value.trim() || $('#rlOld').value);
    if (p && $('#relinkDlg').open){ $('#rlPath').value = p; rlCheck(); }
  } finally { b.disabled = false; }
});

player().addEventListener('playing', () => { $('#playerMsg').hidden = true; updateCaption(); });
/* 行の▶などで「そこだけ再生」した直後に手動で止めた場合、S.playEnd が残ったままだと、
   表示部(動画本体)の再生ボタンで再開したときにも、またそこで止まってしまう。
   一時停止するたびに必ずクリアして、表示部の再生は常に最後まで続けて流れるようにする(字幕も、選んだ行のものへ戻す) */
player().addEventListener('pause', () => { S.playEnd = null; updateCaption(); });
player().addEventListener('ratechange', armPlayEnd);   // 再生の速さを変えたら、終わりで止める見張りの待ち時間を計算し直す(0.5× → 2× で過ぎないように)

let dbQ = 0;

/* ---------- 検索・話者・置換 ---------- */
$('#q').addEventListener('input', applyFilter);
$('#flagKind').addEventListener('change', applyFilter);
$('#btnUndo').addEventListener('click', doUndo);
const EVAL_LOCK_MSG = '評価用のフォルダの動画なので、評価用の印は外せません(設定の「評価用のフォルダ」)';
const EVAL_TITLE = $('#evalSet').parentElement.title;
$('#evalSet').addEventListener('change', e => {
  if (!S.doc) return;
  if (S.doc.evalLocked && !e.target.checked){ e.target.checked = true; return toast(EVAL_LOCK_MSG, 5000); }
  S.doc.evalSet = e.target.checked; syncEval(); markDirty();
  const it = curItem(); if (it) it.evalSet = S.doc.evalSet;
  toast(S.doc.evalSet ? '評価用にしました。この文字起こしは、辞書・提案・追加学習には使いません(すでに登録した辞書は残ります)。'
    + (S.evalDirsActive ? 'ほかの文書へ移ると、動画を評価用のフォルダへ移します(すべて校正済みならメンバーのフォルダ、それ以外は仮置き)' : '')
    : '評価用を外しました。この文字起こしは、学習用として扱われます', 7000);
  setTimeout(loadSuggest, 1500);
});
$('#evSave').addEventListener('click', async () => {
  const dirs = $('#evDirs').value.split(/\r?\n/).map(x => x.trim().replace(/^"|"$/g, '').trim()).filter(Boolean);
  if (!(await patchSettings({ evalDirs: dirs }, '保存できませんでした(ドライブから始まるパスを1行に1つ入れてください)', { apply: false }))) return;   // evalDirs はサーバーだけが持つ(S.settings に入れない)
  toast(dirs.length ? '評価用のフォルダを保存しました' : '評価用のフォルダを空にしました', 3000); loadEvalFolders();
});
$('#evRun').addEventListener('click', () => busy($('#evRun'), async () => {
  try {
    if (S.doc && !(await saveDoc())) return toast('文書を保存できないため整理しませんでした', 5000, 'err');
    const r = await api('/api/eval-folders/organize', { body: {} });
    if (!r.dirs) return toast('評価用のフォルダが設定されていないか、見つかりません', 5000, 'err');
    const intaken = r.intaken || [];
    toast(`整理しました: 外から取り込んだ ${intaken.length} 本・名前を変えた ${r.renamed.length} 本・仮置きから移した ${r.moved.length} 本・評価用にした ${r.marked} 件` + (r.skipped.length ? `・飛ばした ${r.skipped.length} 本(${r.skipped[0].reason})` : ''), 7000, r.skipped.length ? 'err' : '');
    if (S.doc && (r.marked || r.renamed.concat(r.moved, intaken).some(x => x.docs.includes(S.docId)))) await openDoc(S.docId, true);
    loadList(); loadEvalFolders();
  } catch (e){ toast('整理できませんでした: ' + e.message, 6000, 'err'); }
}));
loadEvalFolders();
/* 評価用の文書では、正解を機械が書き換える操作(一括置換・提案の採用)を止める */
document.addEventListener('click', e => {
  if (S.doc && S.doc.evalSet && e.target.closest && e.target.closest('#repGo, #repDictGo, #btnSugHigh, [data-act=sgok]')){ e.stopPropagation(); e.preventDefault(); toast('評価用の文字起こしでは使えません(正解が機械で書き換わるため)。評価用を外してから行ってください', 5000); }
}, true);
$('#docTitle').addEventListener('input', e => { if (S.doc){ S.doc.title = e.target.value.slice(0, 120); markDirty(); } });
$('#selAll').addEventListener('change', e => {
  S.sel = e.target.checked ? new Set(S.doc.segments.map(s => s.id)) : new Set();
  document.querySelectorAll('#segs .sel').forEach(c => { c.checked = e.target.checked; }); updateSel();
});
$('#spAdd').addEventListener('click', () => {
  const sps = numberedSpeakers();   // 組み込みの「ゲーム音声など」は 20 人にも番号にも数えない
  if (sps.length >= 20) return toast('話者は20人までです');
  let n = sps.length + 1; while (S.doc.speakers.some(s => s.id === 'S' + n)) n++;
  pushUndo(); addSpeaker({ id: 'S' + n, name: '話者' + n, color: PALETTE[(n - 1) % PALETTE.length] });
  renderDoc(); markDirty();
});
/* 字幕の色の欄(16 進 6 桁・# なし): 打つ間は 16 進だけに寄せて見本を合わせ、確定(change)で保存する。空 = 指定なし(メンバーカラーなど今までどおり) */
$('#spList').addEventListener('input', e => {
  if (e.target.dataset.f !== 'sub') return;
  const v = subHexInput(e.target.value); if (v !== e.target.value) e.target.value = v;
  const sw = e.target.parentElement.querySelector('.tt-sp-subsw'); if (sw){ sw.hidden = v.length !== 6; if (v.length === 6) sw.style.background = '#' + v; }
  e.target.removeAttribute('aria-invalid');
});
/* 字幕の色の確定: 欄を離れた・Enter(打つ間に値を寄せ直すので、ブラウザの change が来ないことがある = focusout でも確定する。同じ値なら何もしない) */
function commitSubInput(inp){
  const row = inp.closest('[data-i]');   // 字幕の色の段(.tt-sp-subrow)にも話者の番号 data-i がある
  const sp = row && S.doc ? S.doc.speakers[Number(row.dataset.i)] : null; if (!sp || isOtherSp(sp)) return;
  const v = subHexInput(inp.value);
  if (v && v.length !== 6){ inp.setAttribute('aria-invalid', 'true'); return toast('字幕の色は 16 進 6 桁で入れてください(例: FF8FDF。空にすると指定なし)', 4000, 'err'); }
  const cur = subColorOf(sp), next = v ? '#' + v : '';
  if (cur === next) return;
  pushUndo(); setSubColor(sp, next);
  markDirty(); setTimeout(onSpeakerColors, 0);   // 行の線・映像の上の字幕・パックの見本・話者の欄を塗り直す(フォーカスが移ってから = 話者の欄を描き直せるように)
}
$('#spList').addEventListener('focusout', e => { if (e.target.dataset && e.target.dataset.f === 'sub') commitSubInput(e.target); });
$('#spList').addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.dataset && e.target.dataset.f === 'sub'){ e.preventDefault(); e.target.blur(); } });
$('#spList').addEventListener('change', e => {
  if (e.target.dataset.f === 'sub') return commitSubInput(e.target);
  const row = e.target.closest('.sp-row'); if (!row) return;
  const sp = S.doc.speakers[Number(row.dataset.i)]; if (!sp || isOtherSp(sp)) return;
  if (e.target.type === 'color') sp.color = e.target.value; else sp.name = e.target.value.trim().slice(0, 30) || sp.id;
  if (e.target.type === 'text') e.target.blur();   // 確定したら描き直せるように(打っている間は renderSpeakers が描き直さない)
  renderDoc(); markDirty(); lookupSpeakerNames([sp.name]);
});
/* 話者の名前の欄の候補:覚えた声の名前・この文書の配信者・名簿の名前 */
let spVoiceNames = [];
$('#spList').addEventListener('click', e => {
  const pb = e.target.closest('[data-act="spplay"]');
  if (pb){ const sp = S.doc.speakers[Number(pb.closest('.sp-row').dataset.i)]; if (sp) playSpeaker(sp.id); return; }
  const b = e.target.closest('[data-act="spdel"]'); if (!b) return;
  armDelete(b, () => {
    pushUndo(); const sp = S.doc.speakers.splice(Number(b.closest('.sp-row').dataset.i), 1)[0];
    for (const s of S.doc.segments) if (s.speaker === sp.id) setSegSpeaker(s, '');   // ゲーム音声などを消したら、その行の「字幕に出さない」も外れる
    renderDoc(); markDirty();
  });
});
$('#spApply').addEventListener('click', () => {
  if (!S.sel.size) return toast('先に、行の左端のチェックで行を選んでください');
  const id = $('#spBulk').value; pushUndo();
  for (const s of S.doc.segments) if (S.sel.has(s.id)) setSegSpeaker(s, id);
  renderDoc(); markDirty(); toast(`${S.sel.size}行の話者を変更しました`);
});
/* 単語の途中には当てない置換(serve.py の _cc / _bounded / wb_split と同じ規則。「誤」を |語| と書くと有効) */
const ccOf = ch => { const o = ch.codePointAt(0); if ((o >= 0x30A1 && o <= 0x30FA) || 'ー・ヽヾ'.includes(ch)) return 'K'; if ((o >= 0x4E00 && o <= 0x9FFF) || '々〆'.includes(ch)) return 'H'; if (/[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]/.test(ch)) return 'A'; return ''; };
const boundedAt = (t, k, w) => {
  let c = ccOf(w[0]); if (c && k > 0 && ccOf(t[k - 1]) === c) return false;
  c = ccOf(w[w.length - 1]); if (c && k + w.length < t.length && ccOf(t[k + w.length]) === c) return false;
  return true;
};
const wbSplit = w => (w.length >= 3 && w[0] === '|' && w[w.length - 1] === '|') ? [w.slice(1, -1), true] : [w, false];
$('#repGo').addEventListener('click', () => {
  const f = $('#repFrom').value, t = $('#repTo').value; if (!f) return toast('置換前の文字を入力してください');
  const n = withUndoReplace([[f, t]]); $('#repMsg').textContent = n ? `${n}箇所を置換しました(元に戻せます)` : '該当する文字がありませんでした';
});
$('#repDictGo').addEventListener('click', () => {
  const pairs = $('#repDict').value.split(/\r?\n/).map(l => { const k = l.indexOf('=>'); return k > 0 ? [l.slice(0, k).trim(), l.slice(k + 2).trim()] : null; }).filter(Boolean).slice(0, 500)
    .sort((a, b) => b[0].length - a[0].length);
  if (!pairs.length) return toast('辞書に「誤=>正」の行がありません');
  const n = withUndoReplace(pairs); $('#repMsg').textContent = n ? `${n}箇所を置換しました(元に戻せます)` : '該当する文字がありませんでした';
});

/* ---------- 書き出し ---------- */
document.querySelectorAll('[data-ex]').forEach(b => b.addEventListener('click', () => {
  const kind = b.dataset.ex, text = buildExport(kind);
  if (text === null) return toast('書き出す行がありません');
  const mime = { srt: 'application/x-subrip', vtt: 'text/vtt', txt: 'text/plain', json: 'application/json' }[kind];
  download(new Blob([text], { type: mime + ';charset=utf-8' }), safeName(S.doc.title) + '.' + kind);
}));
['exBase', 'exWrap'].forEach(id => $('#' + id).addEventListener('change', readOpts));   // exSpk・exTs のチェックは下の SET_CHECKS の配線で

/* ---------- 左パネルのイベント ---------- */
$('#diarNum').addEventListener('change', diarNumChanged);   // 文書ごとに覚える
$('#diarEmb').addEventListener('change', () => { readOpts(); renderDiarSetup(); });
// 設定のチェックは表(app-core.js の SET_CHECKS)から配線する。手で並べると表に足したチェックが漏れるため
SET_CHECKS.map(c => c[1]).concat(['optVad', 'optSubOrient', 'optMaxV', 'optMaxH', 'optWrapV', 'optWrapH', 'rtModel', 'rtTarget']).forEach(id => { const e = $('#' + id); if (e) e.addEventListener('change', readOpts); });
$('#repDict').addEventListener('input', readOpts);
$('#docAutoGo').addEventListener('click', startDocAuto);
{   // まとめて実行の設定の要約と「設定を変える」・上書きのチェックはホームの設定(どの入口で変えても同じ)
  const syncOw = st => { if (st) $('#docAutoOverwrite').checked = st.overwrite; };
  document.addEventListener('ui-autorun-settings', e => syncOw(e.detail));
  $('#docAutoOverwrite').addEventListener('change', e => { UIKit.prefs.patch('autorun', { overwrite: e.target.checked }).catch(() => {}); syncOw(Object.assign({}, UIKit.autorun.state() || {}, { overwrite: e.target.checked })); });
  $('#docAuto').addEventListener('toggle', () => { if ($('#docAuto').open && TOKEN){ UIKit.autorun.panel($('#docAutoPanel'), { kind: 'docs' }); UIKit.autorun.load().then(syncOw, () => {}); } });
}
{   // パックの音量(編集の設定 packLoudness の1か所。ほかの画面のまとめて実行の欄で変えたときも、この画面の値を合わせる)
  UIKit.packLoud.mount($('#docAutoLoud'));
  document.addEventListener('ui-packloud', e => { if (S.settings && e.detail){ S.settings.packLoudness = e.detail.loud; S.settings.packVolume = e.detail.vol; } });
}
$('#docAuto').addEventListener('toggle', () => {   // 開いたとき、配信者の欄を入れ直す(パックのタブで直した名前も覚えた名前になっている)
  if ($('#docAuto').open && S.docId) UIKit.streamer.autoFill($('#docAutoWho'), { docId: S.docId });
});
window.addEventListener('keydown', e => {
  if (!S.doc || isTextEntry(e.target) || modalOpen()) return;
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z'){ e.preventDefault(); if (!lockJob()) doUndo(); }
  /* Space の再生・停止は共通の再生キー(editPlaybackKeys)だけが受け持つ(ここでも扱うと1回押すと「再生 → すぐ停止」の2回分になる) */
});
window.addEventListener('beforeunload', e => { if (S.dirty || S.saving){ e.preventDefault(); e.returnValue = ''; } });   // 送信中の保存も、閉じると届かないことがある

/* ---------- 受け渡し(notes:docs/spec/pipeline.md 2・3・6): 元の配信(.clip.json)・URL で渡された動画・動画の隣に保存 ---------- */
const YT_PREFIX = 'https://www.youtube.com/';
const CLIP_IC = '<span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/></svg></span>';
/* 開いた文書の「元の配信」と、「動画の隣に保存」の結果の表示 */
S.handoff = null;   // { id, transcript, srt }: 開いている文書を、動画の隣に保存したパス
const HANDOFF_KEY = { 'transcript-v1': 'transcript', srt: 'srt' };
const handoffRow = (h, k, l) => `<div><span class="hint">${l}:</span> <span class="path">${esc(h[k])}</span> <button type="button" class="btn ghost small" data-act="copy" data-k="${k}" title="このパスをコピー">コピー</button></div>`;
document.querySelectorAll('[data-beside]').forEach(b => b.addEventListener('click', () => exportBeside(b.dataset.beside, b)));
$('#handoffOut').addEventListener('click', e => {
  const b = e.target.closest('[data-act=copy]'); if (!b || !S.handoff) return;
  const v = S.handoff[b.dataset.k]; if (v) copyPath(v);
});

/* 行が変わったとき: 「まとめて ▾」の選んだ行のボタンを描き直す(フレームごとに1回) */
let cpQ = 0;
$('#cutSelected').addEventListener('click', () => bulkCut(true));
$('#keepSelected').addEventListener('click', () => bulkCut(false));

/* ---------- キー操作の手がかり(行の一覧の上。閉じたら覚える) ---------- */
const KH_KEY = 'tx.keyhint';
const khOn = () => { try { return localStorage.getItem(KH_KEY) === '1'; } catch { return false; } };   // 既定は出さない(画面の下のキーの帯と同じ中身のため)。出したいときだけ '1'
$('#keyHintClose').addEventListener('click', () => { try { localStorage.setItem(KH_KEY, '0'); } catch {} applyKeyHint(); toast('キー操作の手がかりを閉じました(右上の「キー操作」から、また出せます)', 4000); });
$('#keyHintAll').addEventListener('click', () => openKeys());
$('#keyHintOn').addEventListener('change', e => { try { localStorage.setItem(KH_KEY, e.target.checked ? '1' : '0'); } catch {} applyKeyHint(); });
applyKeyHint();
if (window.ResizeObserver) new ResizeObserver(() => { document.documentElement.style.setProperty('--khh', $('#listHead').offsetHeight + 'px'); }).observe($('#listHead'));   // 一覧の上に固定した道具の高さ(行へ移動したとき、その下に隠れないように)

/* ---------- 起動 ---------- */
async function boot(){
  loadView(); applyView();
  applyNeedHome();   // 題名の行のまとめて実行は入口から開いたときだけ。開いていなければ押せない理由を出す(サーバーに届かないときも)
  try {
    const ping = await api('/api/ping');
    if (APP_VERSION && ping.version !== APP_VERSION && !UIKit.restart.check($('#errBar'), APP_VERSION, ping.version))   // 帯に「起動し直す」
      showErr(`画面(v${APP_VERSION})とサーバー(v${ping.version})の版が違います。黒い画面を閉じて、起動し直してください`, { plain: true });
  } catch (e){ return showErr(e.message + '。youtube-tools フォルダの start.bat で起動して、ホームから開いてください', { plain: true }); }
  try { S.tools = await api('/api/tools'); } catch {}
  if (TOKEN) pollRuns();
  await loadRoster();
  await loadSettings();   // 読めなければ ⚙ に「読み直す」を出し、読み直すまで保存しない
  KM.reload();   // 校正のキーは編集の設定。共通の再生キーがここの保存に残っていたら、ホームの設定へ移す(部品が 1 回だけ)
  if (S.settings.speakerColors === undefined){   // 話者の色のスイッチは、このブラウザの tx.pk.speakerColors が残っていれば初回だけサーバーへ移す(localStorage は消さない)
    try { if (localStorage.getItem('tx.pk.speakerColors') === '0'){ S.settings.speakerColors = false; saveSettings(); } } catch {}
  }
  applySettings(); renderDiarSetup(); renderRtSetup(); renderAlt(); renderKeyUI();   // キー配置は設定(サーバー)に入っている
  loadSiblings();
  try { const j = await api('/api/jobs'); for (const x of j.jobs) if (x.state === 'done' || x.state === 'error') S.seen.add(x.id); } catch {}   // 開く前に終わっていたものは知らせない
  await Promise.all([loadList(), pollJobs()]);
  if (S.jobs.some(j => ACTIVE.has(j.state))) startPolling();
}
const BOOTED = boot();   // 案件の画面(src/app/ui/cases/edhost.js)が起動し終えるのを待つ
