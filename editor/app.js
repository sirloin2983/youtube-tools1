'use strict';
const APP_VERSION = '0.48.0';
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const S = { tools: null, settings: {}, marker: { found: false, videos: [] }, jobs: [], list: [], doc: null, docId: null, dirty: false, saving: false,
  undo: [], sel: new Set(), curIdx: -1, playEnd: null, seen: new Set(), pollT: null,
  navIdx: -1, conflict: false, forceNext: false, baseUpdatedAt: null, stripR: null, sess: { n: 0, activeMs: 0, lastBreak: 0, lastAct: Date.now() },
  eff: { id: null, tx: 0, cut: 0, fresh: true } };   // eff = 文書ごとの校正の手間のまだ送っていない分(effortFlush。マスタープラン Q2)
const PALETTE = ['#2f62d6', '#d9534f', '#2e9e5b', '#c98a12', '#8a4fd6', '#0f9aa8', '#d6479a', '#6b7280'];

/* ---------- 共通 ---------- */
window.addEventListener('error', e => showErr(e.message));
window.addEventListener('unhandledrejection', e => showErr(String(e.reason && e.reason.message || e.reason)));
/* サーバーの API・動画の URL は、必ずこの apiUrl() を通して作る(将来1つのアプリに統合するとき、
   ベースのパスをここ1か所で変えられるように)。画面の場所から求める(絶対パス "/xxx" は直接書かない。
   "" または入口に取り込まれたときの "/transcribe" になる) */
const BASE = location.pathname.replace(/\/[^/]*$/, '');
const apiUrl = path => BASE + path;
/* 入口の統合サーバーに取り込まれたときの合言葉(CSRF トークン。入口が <meta name="ytt-token"> で画面に入れる)。
   書き込み系(GET/HEAD 以外)の要求にだけ付ける */
const TOKEN = (document.querySelector('meta[name="ytt-token"]') || {}).content || '';
const safeName = (t, fb = 'transcript') => String(t || '').replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_').trim().slice(0, 80) || fb;
/* 話者の色: 文書の JSON は手で直せるので、色の文字列は #rgb / #rrggbb だけを通す(style 属性に入れるため。
   そのまま入れると「red;background:url(外部)」のような値で CSS を差し込まれ、外へ通信されうる) */
const spColor = sp => sp && /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(String(sp.color || '')) ? sp.color : '';
const uid = () => 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const norm = s => String(s).normalize('NFKC').toLowerCase();

/* ---------- 表示の好み(長時間の作業向け。このブラウザにだけ保存) ---------- */
const VIEW_KEY = 'tx.view.v1';
const V = { menu: true, fs: '15', dense: false, vid: 'l', follow: true, frameFollow: false, adjStep: '0.1', autoNext: false, rate: '1', brk: '45', sideTab: 'start' };
const VID_H = { s: '18vh', m: '28vh', l: '38vh' };
/* 「編集」の3つのタブ(docs/design/edit-tool-design.md 3)。今のタブは URL の #tx / #cut / #pack に残す(再読み込み・窓で開いても同じタブ)。
   カット・パックのタブでは、左のメニューを細い帯に畳む(overlay = 帯から開いて本文の上に重ねている間)。V.menu(文字起こしのタブの開閉)とは別に持つ */
const ED_TABS = ['tx', 'cut', 'pack'];
const EDT = { tab: 'tx', overlay: false };
const wideTab = () => EDT.tab !== 'tx';
const menuOpen = () => wideTab() ? EDT.overlay : V.menu;
/* 画面の色: v6 からは設定の引き出し(UIKit.settings。全体の節)に一本化(以前の #vTheme はなくした)。ここは帯の色の描き直しだけ */
if (window.UIKit) UIKit.theme.onChange(() => { if (S.doc) drawStripSoon(); });   // ヘッダーのボタン・別のタブ・OS の設定・設定の引き出しで変わったとき(帯の色も描き直す)
/* v0.15.0: 720px 未満では、左のメニューは本文の上に重ねる引き出し(CSS)。開いたら中へ、閉じたら ☰ へフォーカスを移す(キーボードで迷わないように) */
const OVERLAY_MID = '(max-width: 1599.98px)';   // B-7: 文書を開いている間は、この幅まで左のメニューを重ねて開く(index.html の同じ幅の @media)
const isDrawer = () => wideTab() || !!(window.matchMedia && (matchMedia('(max-width: 719.98px)').matches || ($('.app').classList.contains('has-doc') && matchMedia(OVERLAY_MID).matches)));   // カット・パックのタブでも重ねて開く
{
  const bind = (id, key, get) => $('#' + id).addEventListener('change', e => { V[key] = get(e.target); saveView(); applyView(); });
  bind('vFs', 'fs', t => t.value); bind('vVid', 'vid', t => t.value); bind('vDense', 'dense', t => t.checked); bind('vBrk', 'brk', t => t.value); bind('autoNext', 'autoNext', t => t.checked);
  bind('follow', 'follow', t => t.checked); bind('frameFollow', 'frameFollow', t => t.checked); bind('adjStep', 'adjStep', t => t.value); bind('rate', 'rate', t => t.value);
  $('#btnMenu').addEventListener('click', () => toggleMenu());
  $('#btnMenuClose').addEventListener('click', () => toggleMenu(false));
  $('#noDocMenu').addEventListener('click', () => toggleMenu(true));
  $('#menuScrim').addEventListener('click', () => toggleMenu(false));   // 引き出しの外(暗い幕)を押したら閉じる
  document.querySelectorAll('[data-strip]').forEach(b => b.addEventListener('click', () => { if (b.dataset.strip === 'menu') toggleMenu(true); else setSideTab(b.dataset.strip, true); }));
  document.querySelectorAll('[data-edtab]').forEach(b => b.addEventListener('click', () => setEditTab(b.dataset.edtab)));
  $('#edTabs').addEventListener('keydown', e => {   // タブの並び(role=tablist)の中は ← → で移る
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault(); const i = ED_TABS.indexOf(EDT.tab);
    setEditTab(ED_TABS[(i + (e.key === 'ArrowRight' ? 1 : ED_TABS.length - 1)) % ED_TABS.length], { focus: true });
  });
  window.addEventListener('hashchange', () => { const t = tabFromHash(); if (t && t !== EDT.tab) setEditTab(t, { hash: false }); });
  document.querySelectorAll('[data-side-tab]').forEach(b => b.addEventListener('click', () => setSideTab(b.dataset.sideTab, false)));
  $('#btnKeys').addEventListener('click', () => openKeys());
  $('#jobBadge').addEventListener('click', () => showInMenu($('#jobsCard')));
  document.addEventListener('click', e => document.querySelectorAll('details.pop[open], details.ui-menu[open]').forEach(d => { if (!d.contains(e.target) || e.target.closest('.ui-menu-pop a')) d.open = false; }));
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || e.isComposing || e.keyCode === 229) return;
    const open = document.querySelectorAll('details.pop[open], details.ui-menu[open]');
    if (open.length){ open.forEach(d => { d.open = false; }); return; }
    if (isDrawer() && menuOpen() && !document.querySelector('dialog[open]') && !(e.target && e.target.matches && e.target.matches('input[type=search]') && e.target.value)) toggleMenu(false);   // 引き出しは Esc で閉じる(検索欄に文字があるときは、まず検索欄を空にする)
  });
}

/* ---------- ヘッダーの ⚙(ui-kit v6。UIKit.settings)。「表示」の内容(旧 #viewMenu)をツールの節にし、画面の色は全体の節(ui-kit)へ一本化 ---------- */
if (window.UIKit && UIKit.settings){ $('#edSettings').hidden = false; UIKit.settings.mount({ tool: $('#edSettings'), title: '設定', version: 'v' + APP_VERSION }); }
/* キー操作の一覧(#keys)の先頭に、共通の再生キーの表を差し込む(段2) */
/* 共通の再生キーの表(#keysCommon)は、割り当てのとおりに renderKeyUI() が描く */
/* 左メニューの「すべての文字起こし → ホーム」(段2。履歴の一覧そのものはホーム(段5)ができるまでここに残す)。入口に取り込まれているときだけ */
$('#txHomeLink').hidden = !(window.UIKit && UIKit.tools.mounted());
document.addEventListener('DOMContentLoaded', setAppnavVersion);
setAppnavVersion();

/* ---------- 他のツール(実際のポートはサーバーの /api/siblings。答えない・古いサーバーなら既定のポート) ----------
   v6: ヘッダーの「他のツール」メニューは ui-appnav(ホーム/スタジオ/編集)に置き換えたので、ここでは S.ports と
   UIKit.tools.setPaths(cut2resolve の URL・c2rBase() が使う)だけを整える */
S.ports = null;
let sibP = null;

/* ---------- 設定(用語集・置換辞書など) ----------
   監査 11(全体の計画 段2): 保存は「最後に保存した内容との差のキーだけ」を PUT /api/settings {"patch"}(サーバーはロックの中で今のファイルに合わせる。
   窓を2つ開いても、別々の設定なら消し合わない。同じキーを同時に変えたときだけ後勝ち)。失敗は ⚙ の印と設定の引き出しの先頭に [もう一度](UIKit.settings.status)。
   読み込みに失敗したら「設定を読み込めませんでした [読み直す]」にして、読み直すまで保存しない(空の設定で用語集・置換辞書・キー配置を上書きしないため) */
let setT = null, setSaved = {}, setFailed = false, setChain = Promise.resolve(true);
S.settingsLoadErr = '';
const setSnap = o => { const m = {}; for (const k of Object.keys(o || {})) m[k] = JSON.stringify(o[k]); return m; };
const setStatus = (...a) => { if (window.UIKit && UIKit.settings && UIKit.settings.status) UIKit.settings.status(...a); };
/* 画面を離れた(ui-kit の UIKit.life: タブの切り替え 'hidden'・別の窓へ移った 'blur'・閉じる直前 'pagehide')。
   窓を並べて使うと、隣の窓をクリックしてもタブの切り替え(visibilitychange)は来ないため(段階7-2)。ui-kit が無いときはタブの切り替えだけ */
const onLeave = fn => (window.UIKit && UIKit.life) ? UIKit.life.onLeave(fn) : document.addEventListener('visibilitychange', () => { if (document.hidden) fn('hidden'); });
/* 入力の直後(0.6秒以内)にタブを閉じても設定が消えないように、画面を離れるときは待たずに送る(keepalive: 閉じたあとも送り切る) */
onLeave(() => { if (setT){ clearTimeout(setT); setT = null; sendSettings(true); } });
if (window.UIKit && UIKit.life) UIKit.life.onReturn(() => { if (setFailed && !S.settingsLoadErr) sendSettings(); });   // 離れるときの送信が失敗していたら送り直す

/* ---------- 準備状況 ---------- */

/* ---------- 進行度 ---------- */
const MILESTONES = [[1800, '辞書・名簿・提案の効果を、数字で測れる'], [3600, '設定の比較(A/B)で方針を決められる'], [10800, '追加学習(LoRA)を小さく試せる']];
let PG = null;
const fmtDur = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}時間${String(m).padStart(2, '0')}分` : m >= 1 ? `${m}分${String(s % 60).padStart(2, '0')}秒` : `${s}秒`; };
$('#goalHours').addEventListener('change', e => { const h = Number(e.target.value); if (!(h >= 0.5 && h <= 200)){ toast('0.5〜200 時間の間で入力してください'); e.target.value = String(goalSec() / 3600); return; } S.settings.goalHours = h; saveSettings(); renderProgress(); });
$('#goalPill').addEventListener('click', () => showInMenu($('#goalCard')));
/* 左の各カードの開閉を覚える */
document.querySelectorAll('aside details.card[id]:not(#cutPack)').forEach(d => {
  try { const v = localStorage.getItem('tx.fold.' + d.id); if (v === '0') d.open = false; else if (v === '1') d.open = true; } catch {}
  d.addEventListener('toggle', () => { try { localStorage.setItem('tx.fold.' + d.id, d.open ? '1' : '0'); } catch {} });
});

/* ---------- 新規ジョブ ---------- */
let tab = 'file';

/* ---------- フォルダ内すべて ---------- */
let FD = { files: [], dir: '' };
const fmtSize = n => n >= 1e9 ? (n / 1e9).toFixed(1) + 'GB' : n >= 1e6 ? Math.round(n / 1e6) + 'MB' : Math.max(1, Math.round(n / 1e3)) + 'KB';
$('#fdScan').addEventListener('click', () => scanFolder().catch(e => toast(e.message)));
$('#fdPath').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); scanFolder().catch(er => toast(er.message)); } });
$('#fdStudio').addEventListener('click', () => { $('#fdPath').value = S.marker.outDir || ''; $('#fdRec').checked = true; scanFolder().catch(e => toast(e.message)); });
$('#fdSkip').addEventListener('change', renderFolder);
$('#fdList').addEventListener('change', updateFdCount);
$('#fdAll').addEventListener('change', e => { document.querySelectorAll('#fdList input').forEach(x => { x.checked = e.target.checked; }); updateFdCount(); });

/* ---------- 切り抜きスタジオ/マーカー連携 ---------- */

/* ---------- ジョブの進捗 ---------- */
const ACTIVE = new Set(['queued', 'extracting', 'loading', 'running']);
const STATE_LABEL = { queued: '待機中', extracting: '準備中', loading: '準備中', running: '処理中', done: '完了', error: '失敗', cancelled: '中止' };
const pctOf = j => Math.max(0, Math.min(100, Math.round((Number(j.progress) || 0) * 100)));

/* ---------- 保存済み一覧(履歴。v0.15.0 で作り直し: docs/spec/ui-guidelines.md 4.) ----------
   サーバーの /api/transcripts が、校正の進み具合・長さ・元の配信・配信者・元の動画とパックの有無を返す(serve.py の list_transcripts)。
   画面では 絞り込み → 並び替え → まとめる(配信ごと/配信者ごと/まとめない)→ 開いているまとまりの分だけ描く(「もっと見る」で足す)。
   同じ題名が並んでも見分けられるように、配信ごとのときは見出しの配信の題名を省いて、マークの名前・元の配信の時刻・いつ・長さを出す */
const LIST_KEY = 'tx.list.v1';
const L = { state: 'all', kind: 'all', sort: 'updated', group: 'stream' };
const LIST_OPTS = { state: ['all', 'todo', 'doing', 'done'], kind: ['all', 'clip', 'other', 'eval'], sort: ['updated', 'created', 'remain', 'title'], group: ['stream', 'channel', 'none'] };
try { const o = JSON.parse(localStorage.getItem(LIST_KEY) || '{}'); for (const k of Object.keys(L)) if (o && LIST_OPTS[k].includes(o[k])) L[k] = o[k]; } catch {}
const saveListPrefs = () => { try { localStorage.setItem(LIST_KEY, JSON.stringify(L)); } catch {} };
const txOpen = new Set();      // 開いているまとまり(この画面の間だけ覚える)
const txLimit = {};            // まとまりごとの表示件数(「もっと見る」で増やす)
let txInitDone = false, txAuto = null, txGroups = new Map();   // txAuto: 最初に自動で開いた先頭のまとまり(文書を開いたら閉じる。人が開閉したら触らない)
const GROUP_FIRST = 20, FLAT_FIRST = 40, MORE_STEP = 50;
const ago = ms => (window.UIKit && UIKit.fmt) ? UIKit.fmt.ago(ms) : '';

/* 校正の状態: 未校正(1行も校正していない)/ 校正中 / 校正済み(文字のある行が全部校正済み) */
const txStatus = i => { const r = Number(i.rows) || 0, p = Number(i.proofed) || 0; return p <= 0 ? 'todo' : (r > 0 && p >= r ? 'done' : 'doing'); };
const txStream = i => i.streamTitle || i.clipTitle || '';
/* ---------- 選んだ文書をまとめて(12 ⑦(b)。入口の /api/autorun/start-docs。入口から開いたときだけ) ---------- */
const PICK = { on: false, ids: new Set(), polling: 0, active: new Set() };
const PICK_MAX = 20;   // まとめて実行に一度に入れられる文書の数(home/autorun.py の MAX_WAITING)
/* 状態の言葉は共通の部品(UIKit.autorun。どの入口も同じ言葉。段4)。ここは札の色だけ */
const RUN_CLS = { queued: 'wait', running: 'run', done: 'ok', error: 'err', cancelled: 'wait' };
const runLabelOf = r => (window.UIKit && UIKit.autorun ? UIKit.autorun.runLabel(r) : r.state);
const stepLabelOf = s => (window.UIKit && UIKit.autorun ? UIKit.autorun.stepLabel(s) : s.state);

$('#txPickAll').addEventListener('click', () => pickTx(false));
$('#txPickNoPack').addEventListener('click', () => pickTx(true));

$('#txList').addEventListener('click', e => { if (e.target.closest && e.target.closest('details.ui-group>summary')) txAuto = null; });   // 人が開閉したら、自動で閉じない
/* まとまりを開いたときに、その中だけ描く(閉じたまとまりの行は作らない) */
$('#txList').addEventListener('toggle', e => {
  const d = e.target; if (!d || !d.matches || !d.matches('details.ui-group')) return;
  const k = d.dataset.g;
  if (d.open){ txOpen.add(k); const rows = d.querySelector('.tt-g-rows'); if (rows && !rows.children.length) rows.innerHTML = txRowsHTML(k, txGroups.get(k) || []); }
  else txOpen.delete(k);
}, true);
$('#txSearch').addEventListener('input', () => { for (const k of Object.keys(txLimit)) delete txLimit[k]; renderList(); });
[['txState', 'state'], ['txFilter', 'kind'], ['txSort', 'sort'], ['txGroup', 'group']].forEach(([id, k]) => {
  const el = $('#' + id); el.value = L[k];
  el.addEventListener('change', () => {
    L[k] = el.value; saveListPrefs();
    for (const x of Object.keys(txLimit)) delete txLimit[x];
    if (k === 'group'){ txOpen.clear(); txInitDone = false; txAuto = null; }
    renderList();
  });
});

/* ---------- 話者の自動判別 ---------- */
const LOCK_KINDS = ['diarize', 'retranscribe', 'redo'];
const LOCK_LABEL = { retranscribe: '再認識', redo: '疑わしい所を認識し直し', diarize: '話者を判別' };
/* ---------- 声を覚える(A-3)。覚えるのはジョブ(/api/voices/learn)、照らし合わせは話者判別のジョブの中(recognize)。
   声の特徴そのものは画面に来ない(一覧は名前・行の数・秒だけ) ---------- */
const DEFAULT_SPK = /^話者\d+$/;
const EVAL_VOICE_MSG = '評価用の文字起こしでは声を覚えません(評価用のデータを、ほかの文書の話者の名前付けに使わないため)。評価用を外すと覚えられます';
/* 覚える前の確認の本文(段1。監査17・18)。一般的な名前の判定・行の選び方はサーバー(/api/voices/preview)の1か所で、ここは結果を並べるだけ */
const VOICE_SKIP = [['unproofed', '未校正'], ['tagged', '音のメモ(重なり・BGM・聞き取れない)'], ['mixed', '声が混ざる'], ['short', '1秒未満']];
const voiceSec = s => s >= 60 ? `${Math.round(s / 6) / 10}分` : `${Math.round(s)}秒`;
/* 全行をこの人に(評価用。マスタープラン Q4。app-jobs.js の renderSpAll)。候補は文書ごとに api/drill/candidates から1回 */
const SPALL = { id: null, cands: [], suggest: '' };
/* 評価ドリル(URL の ?drill=1。マスタープラン Q4。app-learn.js の drill*): on = 帯を出している・done = このドリルで済みにした本数・skip = 飛ばした文書(次に出さない)・
   none = 次に出せる動画が無い理由・status = api/drill/status(定点の残りと条件)・busy = 済み/飛ばすの途中 */
const DR = { on: false, done: 0, skip: [], none: '', status: null, busy: false };
const SPALL_FROM = { voice: '覚えた声', folder: 'メンバーのフォルダ', stream: '配信の文脈' };
$('#voiceList').addEventListener('click', e => {
  const b = e.target.closest('[data-act=vdel]'); if (!b) return;
  const row = b.closest('[data-name]');
  armDelete(b, async () => {
    try { await api('/api/voices/delete', { body: { embedding: row.dataset.emb, name: row.dataset.name } }); toast(`「${row.dataset.name}」の声を忘れました`, 2500); }
    catch (er){ toast(er.message, 4000, 'err'); }
    loadVoices();
  }, `もう一度押すと「${row.dataset.name}」の声を忘れます`);
});
/* 押すと: 保存 → 覚える前の確認(誰・何行・何秒・覚えない名前・使わなかった行)→ 既にある名前は1人ずつ「同じ人ですか」→ 確かめた人だけ送る(段1。監査17・18)。
   確認のあとで文書が変わっても、サーバーの検査(409/400)が正(知らせに出す) */
$('#voiceLearn').addEventListener('click', async () => {
  if (!S.doc) return;
  if (S.doc.evalSet) return toast(EVAL_VOICE_MSG, 6000, 'err');
  try {
    await saveDoc();
    if (S.dirty || S.saving) return toast('保存中です。少し待ってから、もう一度押してください');
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
    startPolling(); await pollJobs(); toast(names.join('・') + ' の声を覚える処理を待機列に追加しました(メニューの「処理状況」に出ます)', 4000);
  } catch (er){ toast(er.message, 6000, 'err'); }
});
$('#spDetails').addEventListener('toggle', () => { if ($('#spDetails').open){ renderVoiceLearn(); loadVoices(); } });
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
/* 段3 の見直し(design-review): 話者・文字をまとめて直す・書き出し・以前の版の4枚は、一覧の上の「…」からだけ開く(ブリーフ: 操作の入口は役割ごとに1つ)。
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
/* 評価ドリル(帯のボタン・進行度のカードの「始める」)と、評価用の文書の「確かめ済み」(app-learn.js) */
$('#drDone').addEventListener('click', () => drillDone());
$('#drSkip').addEventListener('click', () => drillSkip());
$('#drEnd').addEventListener('click', () => drillEnd());
$('#drillGo').addEventListener('click', () => { if (!DR.on) drillStart(); });
$('#evrMark').addEventListener('click', async e => { const b = e.currentTarget; b.disabled = true; try { await evalReviewHere(); } finally { b.disabled = false; renderEvalReview(); } });
$('#evrUndo').addEventListener('click', () => unmarkReviewed());
$('#spAllName').addEventListener('change', () => { syncSpAllNew(); if ($('#spAllName').value === 'other') $('#spAllNew').focus(); });
$('#spAllGo').addEventListener('click', async e => {
  const b = e.currentTarget; b.disabled = true;
  try { await spAllGo(); } catch (er){ toast(er.message); } finally { b.disabled = !!lockJob(); }
});

/* ---------- 再認識 ---------- */
const SPK_FLAGS = ['声が混ざっている可能性', '話者が不確か', '話者を判別できなかった'];
const RANGE_MAX = 900;
/* 動画全体(docs/design/whole-retranscribe-design.md の 3-1): 範囲・残す行・差し替える行・かかる時間の目安。
   目安は large-v3 の CPU で測った速さ(実時間の約 0.37 倍。2026-09-28 dev/eval_asr.py)だけ。ほかのモデルは出さない(でたらめな数字を出さない) */
const WHOLE_RTF = { 'large-v3': 0.37 };
$('#rsGo').addEventListener('click', resplitDoc);
$('#redoGo').addEventListener('click', async () => {   // 疑わしい所だけ認識し直す(12 ③-2)
  if (!S.docId || lockJob()) return;
  if (!(await saveDoc())) return toast('保存が終わっていません。少し待ってから、もう一度押してください', 5000, 'err');
  try {
    await api('/api/redo', { body: { tid: S.docId, redoLarge: $('#optRedoLarge').checked } });
    $('#redoMsg').textContent = '認識し直しています(終わると読み込み直します)';
    startPolling(); pollJobs();
  } catch (e){ $('#redoMsg').textContent = ''; toast(e.message, 7000, 'err'); }
});
$('#rsOrient').addEventListener('change', () => { $('#rsOrient').dataset.touched = '1'; });
['optSubOrient', 'optMaxV', 'optMaxH'].forEach(id => $('#' + id).addEventListener('change', renderResplitOpts));
$('#rtGo').addEventListener('click', e => {
  const b = e.currentTarget, first = !b.dataset.armed;
  armDelete(b, async () => { b.disabled = true; try { await startRetranscribe(); } catch (er){ toast(er.message); } finally { updateRt(); } });   // 文字を上書きするので、2度押しにする
  if (first && $('#rtTarget').value === 'whole') b.textContent = 'もう一度押す(校正済み以外の行が書き換わります)';
});
$('#rtTarget').addEventListener('change', updateRt);
$('#rtModel').addEventListener('change', updateRt);   // 動画全体の目安はモデルで変わる

/* ---------- 修正から学習した候補 ---------- */
let learned = { items: [], docs: 0 };
let learnedShowAll = false;
$('#lnExport').addEventListener('click', async () => {
  const b = $('#lnExport'), scope = $('#lnExScope').value;
  if (scope === 'doc' && !S.docId) return toast('先に文字起こしを開いてください');
  if (S.dirty) await saveDoc();
  const label = b.textContent; b.disabled = true; b.textContent = '書き出し中…(音声つきは数分かかることがあります)';
  try {
    const r = await apiBlob('/api/export-corrections', { audio: $('#lnExAudio').checked, tid: scope === 'doc' ? S.docId : null, scope: $('#lnExKind').value });
    const [n, na, sk] = (r.headers.get('X-Clips') || '0,0,0').split(',').map(Number), blob = await r.blob();
    const d = new Date(), z = v => String(v).padStart(2, '0');
    download(blob, `corrections-${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}.zip`);
    toast(`${n}行を書き出しました(音声つき${na}行${sk ? ' ・ 上限のため' + sk + '行はとばしました' : ''})。ダウンロードフォルダを確認してください`, 5000, 'ok');
  } catch (er){ toast('書き出せませんでした: ' + er.message, 6000, 'err'); }
  finally { b.disabled = false; b.textContent = label; }
});
const lnKey = x => `${x.wrong}=>${x.right}`;
const lnDraft = {};   // 候補ごとの、編集中の文字(一覧を更新しても消えないように残す)
$('#lnList').addEventListener('input', e => {
  const row = e.target.closest('.ln'), x = row && learned.items[Number(row.dataset.i)]; if (!x) return;
  const w = row.querySelector('.lw').value, r = row.querySelector('.lr').value, edited = w !== x.wrong || r !== x.right;
  if (edited) lnDraft[lnKey(x)] = { w, r }; else delete lnDraft[lnKey(x)];
  row.classList.toggle('edited', edited); row.querySelector('[data-act=lnrev]').hidden = !edited;
});
$('#lnList').addEventListener('click', async e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  const row = b.closest('.ln'), x = learned.items[Number(row.dataset.i)]; if (!x) return;
  try {
    if (b.dataset.act === 'lnrev'){ delete lnDraft[lnKey(x)]; renderLearned(); return; }
    if (b.dataset.act === 'lnadd'){
      const w = row.querySelector('.lw').value.trim(), r = row.querySelector('.lr').value.trim();
      if (!w) return toast('「誤」の文字を入れてください');
      if (w === r) return toast('「誤」と「正」が同じです');
      if (/=>|[\r\n]/.test(w + r)) return toast('「=>」と改行は使えません');
      const wbW = ccOf(w[0]) && [...w].every(c => ccOf(c) === ccOf(w[0])) && !w.includes('|') ? `|${w}|` : w;   // カタカナ・漢字・英数字だけの語は、単語の途中には当てない形で登録する
      const d = $('#repDict'), lines = d.value.split(/\r?\n/), same = lines.findIndex(l => { const k = l.indexOf('=>'); return k > 0 && wbSplit(l.slice(0, k).trim())[0] === w; });
      let msg = '置換辞書に登録しました。開いている文字起こしにも直すには「辞書を全体に適用」を押してください';
      if (same >= 0){ msg = `同じ「${w}」の登録があったので、置き換えました。` + msg.slice(msg.indexOf('開いている')); lines[same] = `${wbW}=>${r}`; d.value = lines.join('\n'); }
      else d.value = (d.value.replace(/\s+$/, '') + `\n${wbW}=>${r}`).replace(/^\n/, '');
      if ($('#lnGloss').checked && r.length >= 2 && r.length <= 15 && (!x.ctx || r !== x.right)){   // 前後の文字を足した断片のままなら、用語集には入れない
        const g = $('#optGloss'); if (!g.value.split(/\r?\n/).some(l => l.trim() === r)) g.value = (g.value.replace(/\s+$/, '') + '\n' + r).replace(/^\n/, '');
      }
      if (w !== x.wrong || r !== x.right) S.settings.learnIgnore = [...(S.settings.learnIgnore || []), lnKey(x)].slice(-500);   // 直して登録したときは、元の候補は消す
      delete lnDraft[lnKey(x)];
      readOpts(); await putSettingsNow(); toast(msg);
    } else {
      S.settings.learnIgnore = [...(S.settings.learnIgnore || []), lnKey(x)].slice(-500); delete lnDraft[lnKey(x)]; await putSettingsNow();
    }
    await loadLearned();
  } catch (er){ toast(er.message); }
});
$('#lnRefresh').addEventListener('click', loadLearned);
$('#lnSearch').addEventListener('input', () => { learnedShowAll = false; renderLearned(); });
$('#lnMore').addEventListener('click', () => { learnedShowAll = !learnedShowAll; renderLearned(); });
$('#lnMin').addEventListener('change', () => { learnedShowAll = false; loadLearned(); });

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

/* ---------- 校正済み(正解として使える行の印) ---------- */
setInterval(() => {   // 操作している時間だけ数える(放置している間は進めない)。休憩のお知らせも、この時間で出す
  if (Date.now() - S.sess.lastAct < 120000){
    S.sess.activeMs += 30000; updateSess();
    effortTick(30000);   // 文書ごとの校正の手間にも同じ時間を足す(開いている文書・今のタブ)
    const b = Number(V.brk) * 60000;
    if (b && S.sess.activeMs - S.sess.lastBreak >= b){ S.sess.lastBreak = S.sess.activeMs; toast(`操作を始めて${Math.round(S.sess.activeMs / 60000)}分たちました。少し休憩しませんか(目を離す・肩を回す・水分)`, 9000); }
  }
}, 30000);
['keydown', 'pointerdown', 'wheel'].forEach(t => window.addEventListener(t, () => { S.sess.lastAct = Date.now(); }, { passive: true, capture: true }));

/* ---------- 進み具合の帯(校正済み・要確認・未校正を、時間軸で見る) ---------- */
let stripQ = 0;
$('#strip').addEventListener('click', e => {
  const r = S.stripR; if (!r || !S.doc) return;
  const t = r[0] + e.offsetX / e.currentTarget.clientWidth * (r[1] - r[0]), segs = S.doc.segments;
  let lo = 0, hi = segs.length - 1, i = 0;
  while (lo <= hi){ const m = (lo + hi) >> 1; if (segs[m].start <= t){ i = m; lo = m + 1; } else hi = m - 1; }
  if (!gotoRow(i, { center: true })) return toast('その位置の行は、絞り込みで隠れています');
  player().currentTime = segs[i].start; S.playEnd = null;
});
/* 全行を校正済みに / 全解除: 元に戻せる操作なので確認はしない(気が利く画面へ 段1。以前は二度押し)。知らせの [元に戻す] で戻す */
$('#btnProofAll').addEventListener('click', () => {
  if (!S.doc) return;
  const all = S.doc.segments.length && S.doc.segments.every(s => s.proofed);
  pushUndo();
  for (const s of S.doc.segments){ if (all) delete s.proofed; else if (s.text.trim()) s.proofed = true; }
  renderDoc(); markDirty();
  UIKit.toast(all ? '校正済みを全て解除しました' : '全行を校正済みにしました', { kind: 'ok', ms: 8000, action: { label: '元に戻す', fn: () => doUndo('tx') } });   // この知らせの「元に戻す」は文字起こしの側だけ(あとでカットを変えていても、カットは戻さない)
});
$('#btnProofSel').addEventListener('click', () => {
  if (!S.doc || !S.sel.size) return;
  pushUndo(); let n = 0;
  for (const s of S.doc.segments) if (S.sel.has(s.id) && s.text.trim()){ s.proofed = true; n++; }
  renderDoc(); markDirty(); toast(`${n}行を校正済みにしました(「元に戻す」で戻せます)`);
});

/* ---------- 認識精度の測定・設定の比較(A/B) ---------- */
const pct = v => v == null ? '—' : (v * 100).toFixed(1) + '%';
let accT = null;
$('#blGo').addEventListener('click', async e => {
  const b = e.currentTarget; b.disabled = true;
  try { const r = await api('/api/eval-baseline', { body: { label: $('#blLabel').value } }); $('#blLabel').value = ''; toast(`記録しました: CER ${pct(r.cer)}(正解 ${r.refChars}字)`); await loadBaselines(); }
  catch (er){ toast(er.message); } finally { b.disabled = false; }
});
$('#accScope').addEventListener('change', loadAcc);
$('#accRefresh').addEventListener('click', loadAcc);
$('#accLegacy').addEventListener('change', loadAcc);

/* ---------- ホロライブの名簿 / 用語集の「認識に効く長さ」 ---------- */
const GLOSS_PROMPT = 150;   // serve.py の whisper_kwargs と揃える(initial_prompt に渡る文字数)
const glossTerms = t => [...new Set(String(t || '').split(/[\r\n,、]+/).map(x => x.trim()).filter(Boolean))];
$('#rosterAdd').addEventListener('click', () => {
  const ids = [...document.querySelectorAll('#rosterGroups .rg:checked')].map(x => x.value), add = rosterNames(ids);
  if (!add.length){ toast('追加する所属にチェックを入れてください'); return; }
  const g = $('#optGloss'), have = glossTerms(g.value), fresh = add.filter(n => !have.includes(n));
  g.value = have.concat(fresh).join('\n'); readOpts(); renderGlossFit();
  document.querySelectorAll('#rosterGroups .rg:checked').forEach(x => x.checked = false);
  toast(fresh.length ? `${fresh.length}語を用語集に追加しました` : 'すべて登録済みです');
});
$('#optGloss').addEventListener('input', renderGlossFit);

let abVariants = null;
$('#abRows').addEventListener('change', e => {
  if (e.target.classList.contains('abr')){
    const row = e.target.parentElement.previousElementSibling.previousElementSibling, v = row && abVariants[Number(row.dataset.i)];
    if (v && e.target.value){ v.terms = glossTerms(v.terms).concat(rosterNames([e.target.value]).filter(n => !glossTerms(v.terms).includes(n))).join('\n'); renderAb(); }
    return;
  }
  const row = e.target.closest('[data-i]'), v = row && abVariants[Number(row.dataset.i)]; if (!v) return;
  const was = v.glossary;
  v.model = row.querySelector('.abm').value; v.glossary = row.querySelector('.abg').checked;
  if (was !== v.glossary) renderAb();
});
$('#abRows').addEventListener('input', e => {
  const row = e.target.closest('[data-i]'), v = e.target.classList.contains('abt') ? abVariants[Number(e.target.previousElementSibling.dataset.i)] : null;
  if (v){ v.terms = e.target.value; const h = e.target.nextElementSibling.querySelector('.hint'), t = glossTerms(v.terms), f = glossFit(t); h.textContent = !t.length ? '' : f.fit >= t.length ? t.length + '語' : t.length + '語のうち先頭' + f.fit + '語だけ効きます'; }
});
$('#abRows').addEventListener('click', e => {
  const b = e.target.closest('[data-act=abdel]'); if (!b) return;
  abVariants.splice(Number(b.closest('[data-i]').dataset.i), 1); renderAb();
});
$('#abAdd').addEventListener('click', () => { if (abVariants.length < 4){ abVariants.push({ model: abVariants[abVariants.length - 1].model, glossary: true }); renderAb(); } });
$('#abGo').addEventListener('click', async () => {
  if (!S.doc) return;
  const b = $('#abGo'); b.disabled = true;
  try {
    await saveDoc();
    if (S.dirty || S.saving) throw new Error('保存中です。少し待ってから、もう一度押してください');
    await api('/api/abtest', { body: { tid: S.docId, variants: abVariants, language: $('#optLang').value, device: $('#optDevice').value, boost: $('#optBoost').checked,
      glossary: $('#optGloss').value, autoGloss: $('#optAutoGloss').checked } });
    startPolling(); await pollJobs(); toast('設定の比較を待機列に追加しました。終わると、ここに結果が出ます');
  } catch (er){ toast(er.message); } finally { renderAbHint(); }
});

/* ---------- 保存データ(dataset/)への保管 ---------- */
const mb = n => n >= 1e9 ? (n / 1e9).toFixed(1) + 'GB' : Math.max(1, Math.round(n / 1e6)) + 'MB';
const minStr = sec => sec < 90 ? Math.round(sec) + '秒' : (sec / 3600 >= 1 ? (sec / 3600).toFixed(1) + '時間' : Math.round(sec / 60) + '分');
let arcPoll = null;
S.arcDirty = false;
$('#arcNow').addEventListener('click', async () => { if (!S.docId) return toast('先に文字起こしを開いてください'); await saveDoc(); archiveNow(S.docId); });
$('#arcAll').addEventListener('click', async () => {
  await saveDoc();
  try { await api('/api/archive', { body: { full: $('#arcFull').checked } }); S.arcDirty = false; loadDataset(); toast('校正済みのある文字起こしを、すべて保管します'); } catch (e){ toast(e.message); }
});
setInterval(() => { if (S.docId && S.doc && !document.hidden) autoArchive(S.docId); }, 10 * 60 * 1000);
/* 離れたら保存し、タブを離れた・閉じるときだけ保管する(保管は音声の切り出しがあるので、隣の窓へ移るたび('blur')には走らせない) */
onLeave(reason => { if (S.docId && S.doc){ (async () => { await saveDoc(); if (reason !== 'blur') autoArchive(S.docId); })(); } });

/* ---------- 編集画面 ---------- */
const player = () => $('#player');
const hhmm = () => { const d = new Date(); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
let docSaveP = null, docOpenSeq = 0;
$('#cfReload').addEventListener('click', async () => {
  clearTimeout(markDirty.t); S.dirty = false; S.conflict = false; S.forceNext = false; await openDoc(S.docId, true); toast('保存済みの内容を読み込みました'); if (CUT) CUT.refresh();
});
$('#cfForce').addEventListener('click', e => armDelete(e.currentTarget, () => {
  S.conflict = false; S.forceNext = true; $('#conflictBar').hidden = true; S.dirty = true; saveDoc(); if (CUT) CUT.refresh();
}));
onLeave(() => { if (S.dirty && !S.conflict){ clearTimeout(markDirty.t); saveDoc(); } });   // タブ・窓を離れるとき・画面を閉じるときに、待たずに保存する
onLeave(() => effortFlush(true));   // 校正の手間のまだ送っていない分も送る(保存とは別の小さな POST。'blur' でも送るだけ = 重い処理はしない。閉じるときも届くよう keepalive)
/* ---------- 字幕の文字数(docs/design/edit-tool-design.md の 12 ②。設定の subtitle。範囲の確認はサーバーの subtitle_settings と同じ) ---------- */
const SUB_DEFAULT = { orientation: 'vertical', maxChars: { vertical: 16, horizontal: 28 }, wrapChars: { vertical: 8, horizontal: 14 } };

const TAG_LABEL = { unclear: '聞き取れない', overlap: '声が重なる', bgm: 'BGM・音が大きい' };
const tagsHTML = s => Object.keys(TAG_LABEL).map(t => `<button type="button" data-act="tag" data-t="${t}" aria-pressed="${(s.tags || []).includes(t) ? 'true' : 'false'}" title="${esc(titleTag(t))}">${TAG_LABEL[t]}</button>`).join('');
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
/* 元に戻す(段3 3-5 監査 05・ユーザー決定 09-29): 文字起こしの履歴 S.undo とカットの履歴(cut.js の M.undo)は別々に持ち、
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
  }
});
$('#segs').addEventListener('change', e => {
  const row = e.target.closest('.seg'); if (!row) return;
  const i = Number(row.dataset.i), s = S.doc.segments[i]; if (!s) return;
  const f = e.target.dataset.f;
  if (e.target.classList.contains('sel')){ e.target.checked ? S.sel.add(s.id) : S.sel.delete(s.id); updateSel(); return; }
  if (f === 'speaker'){ pushUndo(); s.speaker = e.target.value; setRowSp(row, spById(s.speaker)); markDirty(); }
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
    sortSegs(); S.navIdx = segs.indexOf(s); renderDoc();
    rowsEl()[S.navIdx]?.querySelector('textarea')?.focus({ preventScroll: true });
  } else markOvl(i);
});
$('#btnAddAt').addEventListener('click', () => { if (S.doc) insertAtTime(player().currentTime || 0); });
$('#segs').addEventListener('click', e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  if (b.dataset.act === 'addfirst'){ if (!lockJob()) insertAtTime(player().currentTime || 0); return; }
  const row = b.closest('.seg'), i = Number(row.dataset.i), segs = S.doc.segments, s = segs[i]; if (!s) return;
  if (S.navIdx !== i){ setNav(i); savePos(); }   // 押したボタンの行を「今の行」にする(mousedown ではフォーカスを移さないため、ここで)
  switch (b.dataset.act){
    case 'cut':
      if (CUT && CUT.active()){ CUT.rowsCut([i], s.cutState !== 'cut'); break; }   // 行の時間を削る区間にする/戻す(印は編集の内容から付く)
      pushUndo();
      if (s.cutState === 'cut') delete s.cutState; else s.cutState = 'cut';
      row.classList.toggle('cut', s.cutState === 'cut');
      b.setAttribute('aria-pressed', s.cutState === 'cut' ? 'true' : 'false');
      b.textContent = s.cutState === 'cut' ? 'カット済' : '残す';
      markDirty(); renderCutPack();
      break;
    case 'play': playSeg(s, true); break;   // 行の▶は、必ずその行だけ再生する(勝手に次の行へ続けない)
    case 'adj': nudge(s, row, b.dataset.f, Number(b.dataset.d)); break;
    case 'setnow': setTimeNow(s, b.dataset.f); break;
    case 'proof': setProof(s, !s.proofed, row); markDirty(); updatePfStat(); break;
    case 'tag': toggleTag(s, b.dataset.t, row); break;
    case 'unflag': s.flag = ''; row.classList.remove('flag'); b.remove(); markDirty(); updateRt(); drawStripSoon(); break;
    case 'sgok': { const x = S.sug.find(y => y.n === Number(b.dataset.n)); if (x) acceptSug(s, x); break; }
    case 'sgno': { const x = S.sug.find(y => y.n === Number(b.dataset.n)); if (x) rejectSug(x); break; }
    case 'split': doSplit(i, row); break;
    case 'adda': insertAfter(i); break;
    case 'addb': insertBefore(i); break;
    case 'merge':
      if (i >= segs.length - 1) return toast('最後の行です');
      { const navId = navSnapshot(); pushUndo(); const n = segs[i + 1], sep = /[A-Za-z0-9]$/.test(s.text) && /^[A-Za-z0-9]/.test(n.text) ? ' ' : '';
        /* 終了は遅い方(次の行が重なって先に終わる場合に、この行の後ろを失わない)。音の状態のメモはまとめ、カット済は両方ともカット済のときだけ残す */
        s.text = (s.text + sep + n.text).slice(0, 2000); s.end = Math.max(s.end, n.end); s.flag = [...new Set([s.flag, n.flag].join('、').split('、').filter(Boolean))].join('、');
        if (!(s.proofed && n.proofed)) delete s.proofed;
        if (!(s.cutState === 'cut' && n.cutState === 'cut')) delete s.cutState;
        { const tg = Object.keys(TAG_LABEL).filter(k => (s.tags || []).includes(k) || (n.tags || []).includes(k)); if (tg.length) s.tags = tg; else delete s.tags; }
        S.sel.delete(n.id); segs.splice(i + 1, 1);
        navRestore(navId, i); }
      renderDoc(); markDirty(); break;
    case 'del': armDelete(b, () => { const navId = navSnapshot(); pushUndo(); S.sel.delete(s.id); segs.splice(i, 1); navRestore(navId, i); renderDoc(); markDirty(); }); break;
  }
});
/* 行の右クリックのメニュー(段2): 選んだ行の下に出るボタンと同じ操作(data-act はそのまま)。
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
  ['del', () => 'この行を削除']
];
/* B-9(段1): 文字を打つ欄・時刻の欄の上は、普通の右クリックはブラウザ既定のメニュー(コピー・貼り付け)、Shift+右クリックで行のメニュー。
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
/* 右クリックのメニューを開いている間は、キーはメニューだけが受け取る(B-3: ↓ で裏の行が動き、メニューの対象 = 右クリックした行とずれていた)。
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
    const row = e.target.closest('.seg'), s = row && S.doc.segments[Number(row.dataset.i)], n = Number(dm[1]);
    if (s && (n === 0 || S.doc.speakers[n - 1])){
      e.preventDefault(); pushUndo(); s.speaker = n === 0 ? '' : S.doc.speakers[n - 1].id;
      row.querySelector('.spk').value = s.speaker; setRowSp(row, spById(s.speaker));
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
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && e.target.matches('textarea')){   // 入力中にこの行を聞き直す(段2 でやめたが戻した)
    e.preventDefault(); const s = S.doc.segments[Number(e.target.closest('.seg').dataset.i)]; if (s) playSeg(s, true);
  }
});
/* ---------- 行の移動(キーボードで校正を回す) ---------- */
const rowsEl = () => $('#segs').children;
const rowIdxOf = el => { const r = el && el.closest && el.closest('.seg'); return r ? Number(r.dataset.i) : -1; };
const posKey = id => 'tx.pos.' + id;
/* 字幕がどちらを見せるか(capFollow)。true = 再生位置(S.curIdx。timeupdate・シークで付く)、false = 選んだ行(S.navIdx。setNav で付く)。
   以前は「止まっているか」だけで切り替えていたので、止めたまま時間軸を手でつまんで動かす(シーク)と、再生位置は動いたのに
   字幕は前に選んでいた行のまま(コマとずれる)になっていた。timeupdate はシークでも来るので、そこで再生位置の側へ切り替える */
let capFollow = false;
/* ---------- 話者の色(気が利く画面へ 段2)----------
   色を決めるのはここ1つ: 行の左端の線・話者の欄・映像の上の字幕・カットのプレビュー・パックの見本(cut.js・pack-tab.js にも渡す)。
   話者の名前がメンバーと合えばメンバーカラー(照らし合わせは入口の api/ytt/streamer-colors → ytt_core/colors.py。名前の一覧をまとめて1回)。
   合わなければ、行の線・話者の欄は今の自動の色、字幕は配信者の色(--tt-cap-color)。**文字起こしの行の文字の色は変えない**(明るい色は白い背景で読めない)。
   スイッチは編集の設定 speakerColors(パックのタブの「話者の名前がメンバーと合えば…」。まとめて実行も同じ値に従う。以前はこのブラウザの tx.pk.speakerColors) */
const SPKC = new Map();   // 話者の名前 → {name, hex}(合う人)| null(合わない)| undefined(照らし合わせ中)
const speakerColorsOn = () => !S.settings || S.settings.speakerColors !== false;
const rowSpColor = spId => { const c = speakerColor(spId); return c.hex || c.auto; };
/* v0.9.6: 一括操作用のチェック(左端の□。複数行を選んでまとめて処理する)は、キーボードの「今の行」を動かさない。
   これを分けないと、マウスでチェックを付けているだけで、Shiftキー操作の対象が知らない間にそちらへ移ってしまう */
/* v0.9.8: 行のボタンを押すとき、押した瞬間(mousedown)にフォーカスが移ると「今の行」が変わり、前の行の操作ボタンの段が消えて
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
   画面の全面見直し(段2)で W/S・A/D・Q/E・B・Tab をやめたが、ユーザーの指摘(「左手での操作が使いやすかった」2026-09-27)で戻した。
   ↓/↑・Shift+↓/↑ も残す(固定の別の手段)。S の分割は 2 カット のタブだけ(校正のキーは 1 文字起こし のタブだけなので重ならない)。
   キー配置(2026-09-27): 割り当ては ⚙ 設定の「キー配置」で変えられる。保存は S.settings.keymap(サーバーの config.json。どのブラウザ・窓でも同じ)。
   共通の再生キー(UIKit.keys.PLAYBACK_ACTIONS)も同じ keymap に入れ、1 文字起こし・2 カット の両方の共通キーに渡す */
const TX_ACTIONS = [   // [id, 既定のキー(UIKit.keys.comboOf の表記), 説明, まとまり]
  ['rowNext', 's', '次の行', 'move'], ['rowPrev', 'w', '前の行', 'move'], ['unNext', 'd', '次の未校正', 'move'], ['unPrev', 'a', '前の未校正', 'move'], ['flagNext', 'f', '次の要確認', 'move'],
  ['replay', 'r', 'この行をもう一度聞く', 'listen'], ['back3', 'q', '3秒戻る', 'listen'], ['fwd3', 'e', '3秒進む', 'listen'], ['proof', 'Shift+Space', '校正済みにして次へ', 'listen'],
  ['edit', 't', 'この行の文字を直す(入力欄へ)', 'listen'], ['autoNext', 'b', '「移動したら自動で再生」のオン/オフ', 'listen'],
  ['tagUnclear', 'x', '聞き取れない', 'memo'], ['tagOverlap', 'c', '声が重なる', 'memo'], ['tagBgm', 'v', 'BGM・音が大きい', 'memo'], ['insert', 'n', '後ろに行を追加', 'memo'], ['del', 'z', 'この行を削除(2回押し)', 'memo'],
  ['menu', 'g', '左のメニューを開く/閉じる', 'screen'],
  /* 評価ドリル(?drill=1 の帯が出ているときだけ働く)。単体キーにしない(押し間違いで「全部聞いた」にならないように Shift つき) */
  ['drillDone', 'Shift+d', '評価ドリル: 済みにして次へ', 'drill'], ['drillSkip', 'Shift+n', '評価ドリル: 飛ばして次へ', 'drill']
];
const KEY_GROUPS = [['move', '行を移動する'], ['listen', '聞く・校正する'], ['memo', '音の状態のメモ・行の編集'], ['screen', '画面'], ['drill', '評価ドリル(帯が出ているときだけ)']];
const KEY_ALT = { rowNext: '↓', rowPrev: '↑', unNext: 'Shift+↓', unPrev: 'Shift+↑' };   // 固定の別の手段(一覧・帯に並べて出す)
/* 割り当てられないキー(固定の意味がある)。値は使い道(「X は『使い道』に使っているので割り当てられません」) */
const KEY_FIXED = { ArrowDown: '次の行(固定)', ArrowUp: '前の行(固定)', 'Shift+ArrowDown': '次の未校正(固定)', 'Shift+ArrowUp': '前の未校正(固定)',
  Tab: '入力欄に入る/抜ける', 'Shift+Tab': 'ふつうのフォーカスの移動', Escape: '入力欄から抜ける・取り消し', Enter: 'ボタンを押す', '?': 'キー操作の一覧' };
/* 2 カット のタブのキー(cut.js の onKey。変えられない)。一覧はこの表から作る(以前は index.html と cut.js に二重に書いていた。S-30) */
const CUT_KEY_ROWS = [['[ / ]', '前/次の区間を選ぶ'], ['Q / W', '選んだ区間の始まり/終わりの端を選ぶ'], ['S', '分割'], ['Del', '削る/戻す'], ['X', '始まりの印〜終わりの印を削る'],
  ['Shift+, / Shift+.', '選んだ端を10コマ(1コマは共通の再生キー)'], ['+ / −', '拡大・縮小'], ['Home / End', '先頭・末尾へ'], ['Esc', '選択を外す'], ['Ctrl+Z / Ctrl+Shift+Z', '元に戻す・やり直す']];
const keyText = k => window.UIKit && UIKit.keys && UIKit.keys.keyText ? UIKit.keys.keyText(k) : (k || '未設定');
/* キーの一覧 = キー配置(UIKit.keymap。気が利く画面へ 段6): ? の一覧と ⚙ 設定の「キー配置」は同じ部品。重なりの検査(固定・共通の再生キー・
   派生キー = ← → に当たるキー + Shift)も部品の 1 か所。共通の再生キーはホームの設定(スタジオと同じ)。校正のキーは編集の設定 keymap(送ったキーだけ直す) */
const KM = window.UIKit && UIKit.keymap ? UIKit.keymap.create({
  groups: KEY_GROUPS,
  actions: TX_ACTIONS.map(a => ({ id: a[0], def: a[1], label: a[2], group: a[3], alt: KEY_ALT[a[0]] })),
  refuse: combo => KEY_FIXED[combo] || (/^[0-9]$/.test(combo) ? '話者の番号(1〜9・0)' : ''),
  intro: 'キーのボタンを押してから、割り当てたいキーを押します(Esc = 取り消し・Delete = 外す)。すでに使っているキーを選ぶと、そちらの割り当てが外れます(すぐ下の「戻す」で戻せます)。文字を入力している間は効きません(Esc で入力欄から抜ける)。',
  playbackNote: '(スタジオ・編集で同じ。1 文字起こし・2 カット のタブで効きます)',
  fixed: [
    { group: 'listen', why: '入力欄の出入りに使うキー', rows: [['Tab', '選んだ行の入力欄へ'], ['Esc / Tab', '入力欄から抜ける']] },
    { group: 'memo', why: 'Ctrl つきのキー', rows: [['Ctrl+Z', '元に戻す']] },
    { group: 'screen', rows: [['Alt+1 / Alt+2 / Alt+3', 'タブ(文字起こし・カット・パック)を切り替える', 'Alt つきのキー'], ['?', 'この一覧を開く・閉じる', '一覧を開くキー']] },
    { title: '話者', why: '数字は話者の番号', rows: [['1…9', 'この行の話者を n 番目に'], ['0', '話者なし']] },
    { title: '入力中に使えるキー', why: '入力欄の中で使うキー', rows: [['Alt+Enter', '校正済みにして次の行の入力欄へ'], ['Ctrl+Enter', 'この行を聞き直す'], ['Alt+1…9', 'この行の話者'], ['Shift+右クリック', '行のメニュー(普通の右クリックはコピー・貼り付け)']] },
    { title: '2 カット のタブ', note: '(共通の再生キーに加えて)', why: '2 カット のタブの操作', rows: CUT_KEY_ROWS }
  ],
  footNote: 'キー配置は、どのブラウザ・窓でも同じです。',
  load: () => (S.settings && S.settings.keymap) || {},
  save: km => saveKeymap(km),
  fallbackPlayback: { load: () => (S.settings && S.settings.keymap) || {}, save: pb => saveKeymap(pb) },   // 入口の外で開いたとき(以前と同じく編集の設定に)
  onChange: () => renderKeyUI()
}) : null;
const KEY_FN = {
  rowNext: () => navigate(null, 1), rowPrev: () => navigate(null, -1), unNext: () => navigate('unproofed', 1), unPrev: () => navigate('unproofed', -1), flagNext: () => navigate('flag', 1),
  replay: () => replayCur(), back3: () => seek(-3), fwd3: () => seek(3), proof: () => proofOk(), edit: () => editCur(),
  autoNext: () => { V.autoNext = !V.autoNext; saveView(); applyView(); toast('移動したら自動で再生: ' + (V.autoNext ? 'オン' : 'オフ'), 1500); },
  tagUnclear: () => { const c = rowAndSeg(); if (c) toggleTag(c.g, 'unclear', c.row); }, tagOverlap: () => { const c = rowAndSeg(); if (c) toggleTag(c.g, 'overlap', c.row); },
  tagBgm: () => { const c = rowAndSeg(); if (c) toggleTag(c.g, 'bgm', c.row); },
  insert: () => { const c = rowAndSeg(); if (c) insertAfter(c.i); else insertAtTime(player().currentTime); },
  del: () => deleteCur(), menu: () => toggleMenu(),
  drillDone: () => drillKey('drillDone'), drillSkip: () => drillKey('drillSkip')
};
/* 左のメニューがキーを持つ間は、文書を操作するキー(校正のキー・共通の再生キー・Ctrl+Z・Tab・2 カット のキー)を効かせない(GPT-04・段3 3-1 監査 04):
   (a) 本文の上に重ねて開いている間(フォーカスが幕・本文のどこにあっても)または (b) フォーカスがメニューの中にある間(並べて出す 1600px 以上でも)。
   (a) だけだと並べて出す幅で、(b) だけだと幕の上で押したキーが後ろへ漏れるので両方。残すのは G(開閉)・Esc(閉じる)・Alt+1/2/3(タブ)・?(一覧) */
const menuHasKeys = t => !!((menuOpen() && isDrawer()) || (t && t.closest && t.closest('#menuPanel')));
/* 押しっぱなし(キーの自動の繰り返し)で続けて働いてよいのは、移動とシークだけ。
   それ以外(特に Z の2回押しの削除・Shift+Space の校正済み)は、押しっぱなしで「2回目」や「聞かずに校正済み」にならないように、繰り返しを無視する */
const REPEAT_OK = new Set(['rowNext', 'rowPrev', 'unNext', 'unPrev', 'flagNext', 'back3', 'fwd3']);
window.addEventListener('keydown', e => {
  if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.isComposing || e.keyCode === 229 || e.defaultPrevented || document.querySelector('dialog[open]') || document.querySelector('.ui-drawer:not([hidden])')) return;   // 引き出しが開いている間はタブを変えない(ダイアログと同じ扱い。監査01)
  const m = /^Digit([123])$/.exec(e.code); if (!m) return;
  if (e.target && e.target.closest && e.target.closest('#segs') && isTextEntry(e.target)) return;   // 行の文字の入力中の Alt+数字 は話者(#segs の keydown)
  e.preventDefault(); if (!e.repeat) setEditTab(ED_TABS[Number(m[1]) - 1]);
});
/* 共通の再生キー(ui-kit.js の UIKit.keys.playback。既定は Space・J/K/L・← →(Shift で5秒)・, .・I/O。割り当ては keymap())。
   1 文字起こし のタブだけ・ダイアログが開いていないときだけ有効にし、自分のキー処理(下)より先に呼ぶ。処理したら true が返るので、そのときは自分の処理をしない(1つのキーは全体で1つの意味) */
const editPlaybackKeys = window.UIKit && UIKit.keys ? UIKit.keys.playback({
  media: () => player(), keymap: () => keymap(),
  /* 1コマ = 素材の fps(2 カット と同じ。段3 3-4 監査 15)。フレームの境目にそろえて動かす(押し続けても浮動小数のずれが溜まらない)。
     fps が分からない文書・開いた直後(カットの読み込み中)は ui-kit の既定(1/30 秒) */
  fps: () => { const f = CUT && CUT.fps(); return f ? f[0] / f[1] : 30; },
  onFrame: dir => {
    const p = player(), t = CUT && CUT.frameStep ? CUT.frameStep(p.currentTime || 0, dir) : null;
    if (t === null) return false;
    p.pause(); p.currentTime = t;   // 2 カット の stepFrames と同じく止めてから(再生中の1コマは意味がない)
    return true;
  },
  enabled: () => !wideTab() && !!S.doc && !document.querySelector('dialog[open]') && !document.querySelector('.ui-drawer:not([hidden])') && !menuHasKeys(document.activeElement)
}) : null;
window.addEventListener('keydown', e => {
  /* #edTabs(タブの並び)の ← → など、他の場所ですでに処理済み(preventDefault 済み)のキーには重ねて反応しない。
     ⚙ 設定・パックの詳しい設定の引き出しが開いている間も、文書を操作するキーは効かせない(dialog と同じ扱い) */
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || document.querySelector('dialog[open]') || document.querySelector('.ui-drawer:not([hidden])') || isTextEntry(e.target)) return;
  if (editPlaybackKeys && editPlaybackKeys(e)) return;   // 処理したら、ここでは何もしない(I/O は校正では何もしない = 別の意味にしない)
  const c = e.code;
  if (e.key === '?'){ e.preventDefault(); if (!e.repeat) openKeys(); return; }   // キー操作の一覧(配列によって Shift が要るので、Shift の判定より先に)
  const act = txActionOf(window.UIKit && UIKit.keys && UIKit.keys.comboOf ? UIKit.keys.comboOf(e) : '');
  if (act === 'menu'){ e.preventDefault(); if (!e.repeat) toggleMenu(); return; }   // メニューは文書を開いていなくても
  if (menuHasKeys(e.target)) return;   // 重ねて開いたメニューの中では、メニューの操作(↓ で次の項目など)を優先する(GPT-04)
  if (!S.doc || lockJob() || wideTab()) return;   // 校正のキーは 1 文字起こし のタブだけ(カットのタブは cut.js のキー)
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
   (以前は行の文字の欄だけだったので、検索や速さを変えたあとに ↓ や Shift+↓ が効かず「取りこぼし」に見えた)。日本語の変換中は変換の取り消しにだけ使う */
window.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || e.isComposing || e.keyCode === 229 || document.querySelector('dialog[open]')) return;
  const t = e.target;
  if (isTextEntry(t) && t.closest && t.closest('#doc')) t.blur();
});

/* Tab: 入力欄の中 → 抜ける(コマンドモード) / 行を選んでいて入力欄の外 → その行の入力欄に入る。日本語変換中・Shift+Tab・ダイアログ中は、ふつうの動き
   (段2 でやめたが、左手の操作と一緒に戻した。2026-09-27) */
window.addEventListener('keydown', e => {
  if (e.key !== 'Tab' || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.keyCode === 229 || !S.doc || wideTab() || document.querySelector('dialog[open]') || document.querySelector('.ui-drawer:not([hidden])') || menuHasKeys(e.target)) return;   // メニューの中の Tab はふつうのフォーカスの移動(3-1)
  const t = e.target;
  if (t.matches && t.matches('#segs textarea')){ e.preventDefault(); t.blur(); return; }
  const free = t === document.body || t === document.documentElement || (t.matches && t.matches('video')) || (t.closest && t.closest('#segs') && !isTextEntry(t) && !t.matches('button,a'));
  if (free && !lockJob() && rowAndSeg()){ e.preventDefault(); editCur(); }
});

/* ---------- キー配置の表示と変更(⚙ 設定の「キー配置」。2026-09-27) ----------
   割り当てを変えたら、下の帯・一覧の上の手がかり・キー操作の一覧(?)・設定の欄をまとめて描き直す(renderKeyUI) */
const kbdHTML = combo => combo ? keyText(combo).split('+').map(p => `<kbd>${esc(p)}</kbd>`).join('+') : '<span class="muted">未設定</span>';
const keyWithAlt = id => { const km = keymap(), a = KEY_ALT[id]; return [km[id] ? keyText(km[id]) : '', a || ''].filter(Boolean).join(' / ') || '未設定'; };
/* ツールチップ・知らせの中のキー(今の割り当てから作る。割り当てを外したら出さない。GPT-16) */
const keyParen = id => { const k = keymap()[id]; return k ? '(' + keyText(k) + ')' : ''; };
const titlePlay = () => `この行だけ再生${keyParen('replay')}。行の終わりで止まります`;
const titleProof = () => `聞いて確認して、この行の文字が正しいと判断したら押す${keyParen('proof').replace(/\)$/, '。次の行へ進みます)') || '(次の行へ進みます)'}`;
const TAG_ACT = { unclear: 'tagUnclear', overlap: 'tagOverlap', bgm: 'tagBgm' };
const titleTag = t => `この行の音の状態のメモ${keyParen(TAG_ACT[t])}。「聞き取れない」の行は、精度の測定と学習の正解に使いません`;
const titleAddAfter = () => `この行の後に、空の行を足します${keyParen('insert')}`;
const titleDel = () => { const k = keymap().del; return `この行を消します(2回押し${k ? '。' + keyText(k) + ' でも消せます' : ''})`; };
window.addEventListener('keydown', e => {
  const d = $('#keys');
  if (e.key !== '?' || e.defaultPrevented || !d.open || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || isTextEntry(e.target)) return;   // defaultPrevented = 同じ ? で今開いたところ
  e.preventDefault(); if (!e.repeat) d.close();
});
if (KM){ KM.mount($('#keysList')); }
/* ⚙ の「キー配置を変える(?)」: キーを変える場所は ? の一覧だけ。設定の引き出しを閉じてから一覧を開く */
$('#setKeysOpen').addEventListener('click', () => {
  const dr = document.getElementById('uiSettingsDrawer');
  if (dr && window.UIKit && UIKit.drawer) UIKit.drawer.close(dr);
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
      await saveDoc();
      if (S.dirty || S.saving) return toast('保存中です。少し待ってから、もう一度押してください');
      await api('/api/restore', { body: { id: S.docId, ts } });
      await openDoc(S.docId, true); await loadHistory();
      toast('選んだ時点に戻しました(戻す前の状態も「以前の版」に残っています)');
    } catch (er){ toast(er.message); }
  });
});

/* ---------- v0.9.8: 行の追加(認識で抜けたセリフを書き足す) ----------
   時刻は前後の行の「すき間」に置く(すき間が 8 秒より長ければ 8 秒まで)。すき間が無いときは 1.5 秒の仮の長さで置き、重なりを案内する。
   並び順(開始時刻順)を必ず保つため、足したあと sortSegs() して id で位置を探し直す。原文(original)には何も足さないので、
   サーバー側の精度測定では「人が足した行 = 認識の脱落」として正しく数えられ、置換の学習には使われない */
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
  const i = curIndex(t); if (i === S.curIdx) return;
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

/* ---------- 動画を選び直す(段2 B-4。docs/plan/phase2-data-safety.md の 1)。付け替えの API は POST だけ(URL の引数では付け替えない) ---------- */
const RL = { id: null, seq: 0, check: null, path: '' };
$('#rlCheck').addEventListener('click', rlCheck);
$('#rlPath').addEventListener('input', rlReset);   // 確かめたあとにパスを変えたら、確かめ直すまで付け替えない
$('#rlPath').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing){ e.preventDefault(); rlCheck(); } });
$('#rlAccept').addEventListener('change', rlSync);
$('#rlCancel').addEventListener('click', () => $('#relinkDlg').close());
$('#relinkDlg').addEventListener('close', () => { RL.seq++; });
$('#rlCopy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('#rlOld').value); toast('元のパスをコピーしました', 2500, 'ok'); }
  catch { $('#rlOld').select(); toast('コピーできませんでした(欄を選んだので Ctrl+C でコピーしてください)', 5000, 'err'); }
});
$('#rlGo').addEventListener('click', async () => {
  const c = RL.check, id = RL.id, b = $('#rlGo');
  if (!c || S.docId !== id) return;
  b.disabled = true;
  try {
    if (!(await saveDoc()) || (CUT && !(await CUT.flush()))) return toast('保存が追いついていません。少し待ってから、もう一度押してください', 5000, 'err');
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

/* ---------- 見つからない動画をまとめて付け替える(2026-10-01)。候補は「選んだフォルダの中の同じファイル名」か行ごとの「参照…」。
   付け替えは1件ずつ /api/relink(控え・長さ・競合の確認は1件のときと同じ)。長さが違うものは最初は選ばない ---------- */
const RA = { rows: [], seq: 0, busy: false, q: Promise.resolve() };
$('#txMissingGo').addEventListener('click', () => openRelinkAll());
$('#raFind').addEventListener('click', raFind);
$('#raFolder').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing){ e.preventDefault(); raFind(); } });
$('#raBrowse').addEventListener('click', async () => {
  const b = $('#raBrowse'); b.disabled = true;
  try {
    const first = RA.rows.find(r => !r.done);
    const p = await pickPath('dir', $('#raFolder').value.trim() || (first ? first.sourcePath : ''));
    if (p && $('#relinkAllDlg').open){ $('#raFolder').value = p; await raFind(); }
  } finally { raSync(); }
});
$('#raGo').addEventListener('click', async () => {
  const rows = RA.rows.filter(r => r.pick && r.check && !r.done);
  if (!rows.length || RA.busy) return;
  RA.busy = true; RA.rows.forEach(raUpdate);
  const cur = S.docId, curIn = rows.some(r => r.id === cur);
  let ok = 0;
  try {
    if (curIn && (!(await saveDoc()) || (CUT && !(await CUT.flush())))) return toast('保存が追いついていません。少し待ってから、もう一度押してください', 5000, 'err');
    for (const r of rows){
      r.state = 'saving'; raUpdate(r);
      try {
        await api('/api/relink', { body: { id: r.id, path: r.path, baseUpdatedAt: r.id === S.docId ? S.baseUpdatedAt : r.updatedAt, acceptDiff: !!r.check.mismatch, normalize: false } });   // まとめて付け替える = 以前の文書の動画を移したとき。30fps に作り直さない(Q1: 以前の動画はそのまま)
        r.done = true; ok++;
      } catch (e){
        r.err = e.message; r.pick = false;
        if (e.code === 'duration_mismatch' && e.data && e.data.check) r.check = e.data.check;
      }
      r.state = ''; raUpdate(r);
    }
    if (ok) toast(`${ok} 件を付け替えました(前の状態は各文書の「以前の版に戻す」で戻せます)`, 7000, 'ok');
    if (ok < rows.length) toast(`${rows.length - ok} 件は付け替えられませんでした(理由は一覧に出しています)`, 8000, 'err');
    await loadList();
    if (curIn && S.docId === cur && rows.some(r => r.id === cur && r.done)) await openDoc(cur);   // 開いている文書は新しいパスで読み直す
  } finally { RA.busy = false; RA.rows.forEach(raUpdate); raSync(); }
});
$('#raCancel').addEventListener('click', () => { if (!RA.busy) $('#relinkAllDlg').close(); });
$('#relinkAllDlg').addEventListener('cancel', e => { if (RA.busy) e.preventDefault(); });   // 付け替えている途中は閉じない
$('#relinkAllDlg').addEventListener('close', () => { RA.seq++; });
player().addEventListener('playing', () => { $('#playerMsg').hidden = true; updateCaption(); });
/* v0.9.6: 行の▶などで「そこだけ再生」した直後に手動で止めた場合、S.playEnd が残ったままだと、
   表示部(動画本体)の再生ボタンで再開したときにも、またそこで止まってしまう。
   一時停止するたびに必ずクリアして、表示部の再生は常に最後まで続けて流れるようにする(字幕も、選んだ行のものへ戻す) */
player().addEventListener('pause', () => { S.playEnd = null; updateCaption(); });

const fmtCs = t => { t = Math.max(0, Number(t) || 0); const cs = Math.round(t * 100), h = Math.floor(cs / 360000), m = Math.floor(cs % 360000 / 6000), sec = (cs % 6000) / 100;
  return (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + sec.toFixed(2).padStart(5, '0'); };   // 0:28.60(1/100 秒まで)
let dbQ = 0;

/* ---------- 検索・話者・置換 ---------- */
$('#q').addEventListener('input', applyFilter);
$('#flagKind').addEventListener('change', applyFilter);
$('#btnUndo').addEventListener('click', doUndo);
const EVAL_LOCK_MSG = '評価用のフォルダの動画なので、評価用の印は外せません(⚙ の「評価用のフォルダ」)';
const EVAL_TITLE = $('#evalSet').parentElement.title;
$('#evalSet').addEventListener('change', e => {
  if (!S.doc) return;
  if (S.doc.evalLocked && !e.target.checked){ e.target.checked = true; return toast(EVAL_LOCK_MSG, 5000); }
  S.doc.evalSet = e.target.checked; syncEval(); markDirty();
  const it = S.list.find(x => x.id === S.docId); if (it){ it.evalSet = S.doc.evalSet; renderList(); }
  toast(S.doc.evalSet ? '評価用にしました。この文字起こしは、辞書・提案・追加学習には使いません(すでに登録した辞書は残ります)。'
    + (S.evalDirsActive ? 'ほかの文書へ移ると、動画を評価用のフォルダへ移します(すべて校正済みならメンバーのフォルダ、それ以外は仮置き)' : '')
    : '評価用を外しました。この文字起こしは、学習用として扱われます', 7000);
  setTimeout(() => { loadProgress(); loadLearned(); loadAcc(); }, 1500);
});
$('#evSave').addEventListener('click', async () => {
  const dirs = $('#evDirs').value.split(/\r?\n/).map(x => x.trim().replace(/^"|"$/g, '').trim()).filter(Boolean);
  try {
    await api('/api/settings/patch', { body: { values: { evalDirs: dirs } } });
    toast(dirs.length ? '評価用のフォルダを保存しました' : '評価用のフォルダを空にしました', 3000); loadEvalFolders();
  } catch (e){ toast('保存できませんでした(ドライブから始まるパスを1行に1つ入れてください): ' + e.message, 6000, 'err'); }
});
$('#evRun').addEventListener('click', async () => {
  const b = $('#evRun'); b.disabled = true;
  try {
    if (S.doc && !(await saveDoc())) return toast('文書を保存できないため整理しませんでした', 5000, 'err');
    const r = await api('/api/eval-folders/organize', { body: {} });
    if (!r.dirs) return toast('評価用のフォルダが設定されていないか、見つかりません', 5000, 'err');
    const intaken = r.intaken || [];
    toast(`整理しました: 外から取り込んだ ${intaken.length} 本・名前を変えた ${r.renamed.length} 本・仮置きから移した ${r.moved.length} 本・評価用にした ${r.marked} 件` + (r.skipped.length ? `・飛ばした ${r.skipped.length} 本(${r.skipped[0].reason})` : ''), 7000, r.skipped.length ? 'err' : '');
    if (S.doc && (r.marked || r.renamed.concat(r.moved, intaken).some(x => x.docs.includes(S.docId)))) await openDoc(S.docId, true);
    loadList(); loadEvalFolders();
  } catch (e){ toast('整理できませんでした: ' + e.message, 6000, 'err'); }
  finally { b.disabled = false; }
});
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
  if (S.doc.speakers.length >= 20) return toast('話者は20人までです');
  let n = S.doc.speakers.length + 1; while (S.doc.speakers.some(s => s.id === 'S' + n)) n++;
  pushUndo(); S.doc.speakers.push({ id: 'S' + n, name: '話者' + n, color: PALETTE[(n - 1) % PALETTE.length] });
  renderDoc(); markDirty();
});
$('#spList').addEventListener('change', e => {
  const row = e.target.closest('.sp-row'); if (!row) return;
  const sp = S.doc.speakers[Number(row.dataset.i)]; if (!sp) return;
  if (e.target.type === 'color') sp.color = e.target.value; else sp.name = e.target.value.trim().slice(0, 30) || sp.id;
  if (e.target.type === 'text') e.target.blur();   // 確定したら描き直せるように(打っている間は renderSpeakers が描き直さない)
  renderDoc(); markDirty(); lookupSpeakerNames([sp.name]);
});
/* 話者の名前の欄の候補(気が利く画面へ 段2・E-1): 覚えた声の名前・この文書の配信者・名簿の名前 */
let spVoiceNames = [];
$('#spList').addEventListener('click', e => {
  const pb = e.target.closest('[data-act="spplay"]');
  if (pb){ const sp = S.doc.speakers[Number(pb.closest('.sp-row').dataset.i)]; if (sp) playSpeaker(sp.id); return; }
  const b = e.target.closest('[data-act="spdel"]'); if (!b) return;
  armDelete(b, () => {
    pushUndo(); const sp = S.doc.speakers.splice(Number(b.closest('.sp-row').dataset.i), 1)[0];
    for (const s of S.doc.segments) if (s.speaker === sp.id) s.speaker = '';
    renderDoc(); markDirty();
  });
});
$('#spApply').addEventListener('click', () => {
  if (!S.sel.size) return toast('先に、行の左端のチェックで行を選んでください');
  const id = $('#spBulk').value; pushUndo();
  for (const s of S.doc.segments) if (S.sel.has(s.id)) s.speaker = id;
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
['exBase', 'exWrap', 'exSpk', 'exTs'].forEach(id => $('#' + id).addEventListener('change', readOpts));

/* ---------- 左パネルのイベント ---------- */
$('#tabFile').addEventListener('click', () => setTab('file'));
$('#tabMarker').addEventListener('click', () => setTab('marker'));
$('#tabFolder').addEventListener('click', () => setTab('folder'));
$('#btnStart').addEventListener('click', onStart);
$('#btnMarkerFile').addEventListener('click', () => $('#markerFile').click());
$('#markerFile').addEventListener('change', async e => {
  const f = e.target.files[0]; e.target.value = ''; if (!f) return;
  if (f.size > 64 * 1024 * 1024) return toast('ファイルが大きすぎます');
  let vs; try { vs = parseMarker(JSON.parse(await f.text())); } catch { return toast('data.json を読み込めませんでした'); }
  try {
    const { items } = await api('/api/transcribed-ranges');
    for (const v of vs) if (v.sourcePath) for (const c of v.clips) c.doneTid = coveredBy(items, v.sourcePath, c.start, c.end);
  } catch {}
  S.marker = { found: true, videos: vs, sources: [{ kind: 'file', path: f.name, videos: vs.length }] }; renderMarker(); if (!vs.length) toast('ポイントのある動画が見つかりませんでした');
});
$('#mVideo').addEventListener('change', () => { $('#mPath').value = ''; renderMarkerClips(); });
$('#mFilter').addEventListener('change', () => { renderMarkerClips(); readOpts(); });
$('#mSkip').addEventListener('change', renderMarkerClips);
$('#mPad').addEventListener('change', readOpts);
$('#mAll').addEventListener('change', e => { document.querySelectorAll('#mClips input').forEach(c => { c.checked = e.target.checked; }); updateMCount(); });
$('#mClips').addEventListener('change', updateMCount);
$('#diarNum').addEventListener('change', readOpts);
$('#diarEmb').addEventListener('change', () => { readOpts(); renderDiarSetup(); });
['optModel', 'optLang', 'optQuality', 'optDevice', 'optVad', 'optBoost', 'optAutoDict', 'optWordSplit', 'optSubOrient', 'optMaxV', 'optMaxH', 'optWrapV', 'optWrapH', 'optStripPunct', 'optAutoGloss', 'optAutoLearned', 'optAutoRedo', 'optRedoLarge', 'arcAuto', 'arcFull', 'rtModel', 'rtTarget'].forEach(id => $('#' + id).addEventListener('change', readOpts));
['optGloss', 'repDict'].forEach(id => $('#' + id).addEventListener('input', readOpts));
$('#txPick').addEventListener('change', () => { PICK.on = $('#txPick').checked; if (!PICK.on) PICK.ids.clear(); renderList(); renderPickBar(); });
$('#txBatchGo').addEventListener('click', startBatch);
$('#docAutoGo').addEventListener('click', startDocAuto);
if (window.UIKit && UIKit.autorun){   // まとめて実行の設定の要約と「設定を変える」・上書きのチェックはホームの設定(どの入口で変えても同じ。段4)
  const syncOw = st => { if (st){ $('#docAutoOverwrite').checked = st.overwrite; $('#txOverwrite').checked = st.overwrite; } };
  document.addEventListener('ui-autorun-settings', e => syncOw(e.detail));
  for (const id of ['#docAutoOverwrite', '#txOverwrite']) $(id).addEventListener('change', e => { if (UIKit.prefs) UIKit.prefs.patch('autorun', { overwrite: e.target.checked }).catch(() => {}); syncOw(Object.assign({}, UIKit.autorun.state() || {}, { overwrite: e.target.checked })); });
  $('#docAuto').addEventListener('toggle', () => { if ($('#docAuto').open && TOKEN){ UIKit.autorun.panel($('#docAutoPanel'), { kind: 'docs' }); UIKit.autorun.load().then(syncOw, () => {}); } });
  $('#txPick').addEventListener('change', () => { if ($('#txPick').checked && TOKEN){ UIKit.autorun.panel($('#txBatchPanel'), { kind: 'docs' }); UIKit.autorun.load().then(syncOw, () => {}); } });
}
if (window.UIKit && UIKit.packLoud){   // パックの音量(編集の設定 packLoudness の1か所。ほかの画面のまとめて実行の欄で変えたときも、この画面の値を合わせる。2026-09-29)
  UIKit.packLoud.mount($('#docAutoLoud'));
  document.addEventListener('ui-packloud', e => { if (S.settings && e.detail){ S.settings.packLoudness = e.detail.loud; S.settings.packVolume = e.detail.vol; } if (PACK) PACK.changed(); });
}
$('#docAuto').addEventListener('toggle', () => {   // 開いたとき、配信者の欄を入れ直す(パックのタブで直した名前も覚えた名前になっている。段5)
  if ($('#docAuto').open && window.UIKit && UIKit.streamer && S.docId) UIKit.streamer.autoFill($('#docAutoWho'), { docId: S.docId });
});
$('#txRuns').addEventListener('click', async e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  const row = b.closest('.tt-run');
  if (b.dataset.act === 'runopen') openDoc(row.dataset.doc);
  else if (b.dataset.act === 'runcancel'){ try { await portalApi('api/autorun/cancel', { runId: row.dataset.run }); } catch (er){ toast(er.message, 4000, 'err'); } pollRuns(); }
});
$('#jobs').addEventListener('click', async e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  if (b.dataset.act === 'open') openDoc(b.dataset.tid);
  else if (b.dataset.act === 'evalview'){ showInMenu($('#accCard')); loadEvals(); }   // 「精度」タブに切り替えてから見せる(別のタブのままだと隠れていて何も起きなかった)
  else if (b.dataset.act === 'cancel'){ try { await api('/api/transcribe/cancel', { body: { id: b.closest('.job').dataset.id } }); pollJobs(); } catch (er){ toast(er.message); } }
});
$('#txList').addEventListener('click', e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  if (b.dataset.act === 'more'){   // まとまりの「もっと見る」: そのまとまりだけ描き足す
    const k = b.dataset.g; txLimit[k] = (txLimit[k] || (k === 'all' ? FLAT_FIRST : GROUP_FIRST)) + MORE_STEP;
    const rows = b.closest('.tt-g-rows'); if (rows) rows.innerHTML = txRowsHTML(k, txGroups.get(k) || []);
    return;
  }
  const row = b.closest('.txi'); if (!row) return; const id = row.dataset.id;
  if (b.dataset.act === 'pick'){ if (b.checked) PICK.ids.add(id); else PICK.ids.delete(id); renderPickBar(); return; }
  if (b.dataset.act === 'open') openDoc(id);
  else if (b.dataset.act === 'hide' || b.dataset.act === 'unhide'){
    const it = S.list.find(x => x.id === id), menu = b.closest('details'); if (menu) menu.open = false;
    UIKit.hide.set('transcripts', [id], b.dataset.act === 'hide', { label: it && it.title ? it.title : '無題' });
  }
  else if (b.dataset.act === 'relink'){   // 動画が見つからない文書: 開いてから、付け替えのダイアログ(段2 B-4)
    const menu = b.closest('details'); if (menu) menu.open = false;
    (S.docId === id ? Promise.resolve(true) : openDoc(id)).then(ok => { if (ok && S.docId === id) openRelink(); });
  }
  else if (b.dataset.act === 'del') armDelete(b, async () => {
    /* 開いている文書を消すときは、待っている自動保存を止め、送信中の保存が終わるのを待ってから消す
       (消したあとに保存が届くと失敗し続け、「未保存」が残って他の文書を開けなくなるため) */
    if (S.docId === id){ clearTimeout(markDirty.t); if (docSaveP) await docSaveP.catch(() => {}); }
    try { await api('/api/transcript?id=' + encodeURIComponent(id), { method: 'DELETE' }); } catch (er){ return toast(er.message, 3800, 'err'); }
    if (S.docId === id) closeDoc();
    toast('削除しました', 2500);
    loadList();
  });
});
window.addEventListener('keydown', e => {
  if (!S.doc || wideTab() || isTextEntry(e.target) || document.querySelector('dialog[open]') || document.querySelector('.ui-drawer:not([hidden])') || menuHasKeys(e.target)) return;   // メニューがキーを持つ間は戻さない(3-1)
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z'){ e.preventDefault(); if (!lockJob()) doUndo(); }
  /* Space の再生・停止は共通の再生キー(editPlaybackKeys)だけが受け持つ。ここにも残っていたため1回押すと「再生 → すぐ停止」の2回分になっていた(2026-09-27 に削除) */
});
window.addEventListener('beforeunload', e => { if (S.dirty || S.saving){ e.preventDefault(); e.returnValue = ''; } });   // 送信中の保存も、閉じると届かないことがある

/* ---------- 受け渡し(docs/spec/pipeline.md 2・3・6): 元の配信(.clip.json)・URL で渡された動画・動画の隣に保存 ---------- */
const YT_PREFIX = 'https://www.youtube.com/';
const CLIP_IC = '<span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/></svg></span>';
const WARN_IC = '<span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg></span>';
/* 動画(または .clip.json)のパスから、隣の .clip.json を調べて「元の配信」を出す。サーバーはネットワークのパスを調べず、ffmpeg も呼ばないのですぐ返る */
let clipSeq = 0;
$('#srcPath').addEventListener('change', e => lookupClip(e.target.value));
/* 開いた文書の「元の配信」と、「動画の隣に保存」の結果の表示 */
S.handoff = null;   // { id, transcript, srt, plan }: 開いている文書を、動画の隣に保存したパス
const HANDOFF_KEY = { 'transcript-v1': 'transcript', srt: 'srt', 'cut-plan-v1': 'plan' };
const handoffRow = (h, k, l) => `<div><span class="hint">${l}:</span> <span class="path">${esc(h[k])}</span> <button type="button" class="btn ghost small" data-act="copy" data-k="${k}" title="このパスをコピー">コピー</button></div>`;
document.querySelectorAll('[data-beside]').forEach(b => b.addEventListener('click', () => exportBeside(b.dataset.beside, b)));
$('#btnOpenVideo').addEventListener('click', openVideoNoTx);
$('#mcOpen').addEventListener('click', openVideoNoTx);
$('#mcTx').addEventListener('click', () => { $('#mediaChoice').hidden = true; onStart(); });
$('#btnTxInto').addEventListener('click', async () => {
  if (!S.doc || !S.doc.sourcePath) return;
  readOpts();
  const id = S.docId, b = $('#btnTxInto'); b.disabled = true;
  try {
    await api('/api/transcribe', { body: { sourcePath: S.doc.sourcePath, intoDoc: id, ...jobOpts() } });
    toast('文字起こしを始めました(終わると、この画面に行が出ます)', 5000); startPolling(); await pollJobs();
  } catch (e){ toast(e.message, 6000, 'err'); }
  finally { renderIntoState(); }
});
[$('#handoffOut'), $('#cpPlanOut')].forEach(el => el.addEventListener('click', async e => {
  const b = e.target.closest('[data-act=copy]'); if (!b || !S.handoff) return;
  const v = S.handoff[b.dataset.k]; if (!v) return;
  try { await navigator.clipboard.writeText(v); toast('パスをコピーしました', 2000, 'ok'); } catch { toast('コピーできませんでした(パスを選んでコピーしてください)', 3000, 'err'); }
}));

/* ---------- cut2resolve の API(3 パック のタブ・カットのたたき台が使う) ----------
   パックを作るのは cut2resolve/pack.py だけ(文字起こし側に Resolve 用の計算を書き足さない。docs/design/resolve-pack-unification.md)。
   cut2resolve の API は、入口に取り込まれているとき(同じアドレスの /cut2resolve/。合言葉も同じ)だけ使う。別のポートの cut2resolve には送らない
   (合言葉を別のサーバーへ渡さない・CORS で断られるため) */
const c2rUrl = path => c2rBase() + String(path).replace(/^\/+/, '');
/* 行の「残す/カット」に関わる内容だけの印(文字を直しただけでは変わらない。文字が空になった行は残らないので含める) */
const rowSig = () => S.doc ? S.doc.segments.map(g => `${g.start},${g.end},${g.cutState === 'cut' ? 1 : 0},${g.text.trim() ? 1 : 0}`).join(';') : '';
/* 行やカットが変わったとき: 「まとめて ▾」の選んだ行のボタンと、3 パック のタブを描き直す(フレームごとに1回) */
let cpQ = 0;
$('#cutSelected').addEventListener('click', () => bulkCut(true));
$('#keepSelected').addEventListener('click', () => bulkCut(false));

/* ---------- キー操作の手がかり(行の一覧の上。閉じたら覚える) ---------- */
const KH_KEY = 'tx.keyhint';
const khOn = () => { try { return localStorage.getItem(KH_KEY) === '1'; } catch { return false; } };   // 段3 の仕上げ: 既定は出さない(画面の下のキーの帯と同じ中身のため)。出したいときだけ '1'
$('#keyHintClose').addEventListener('click', () => { try { localStorage.setItem(KH_KEY, '0'); } catch {} applyKeyHint(); toast('キー操作の手がかりを閉じました(右上の「キー操作」から、また出せます)', 4000); });
$('#keyHintAll').addEventListener('click', () => openKeys());
$('#keyHintOn').addEventListener('change', e => { try { localStorage.setItem(KH_KEY, e.target.checked ? '1' : '0'); } catch {} applyKeyHint(); });
applyKeyHint();
if (window.ResizeObserver) new ResizeObserver(() => { document.documentElement.style.setProperty('--khh', $('#listHead').offsetHeight + 'px'); }).observe($('#listHead'));   // 一覧の上に固定した道具の高さ(行へ移動したとき、その下に隠れないように)

/* ---------- 確認のダイアログ(はい/やめる) ---------- */

/* ---------- 2 カット(cut.js)。区間の編集は cut.js、行の表示・文書の保存はこちら ---------- */
const CUT = window.EditCut ? EditCut.create({ S, $, esc, fmtT, fmtCs, toast, api, apiUrl, player, isTextEntry, onLeave, saveDoc, putSettings: putSettingsNow, speakerColor, pushUndo, undoDocIf, splitRowAt, rowChanged, lockJob, doUndo: () => doUndo(undefined, true),
  c2rApi, c2rWait, c2rBase, tab: () => EDT.tab, keymap: () => keymap(), menuHasKeys, confirm: confirmDlg, onCutMarks, onCutSaved, onCutState: () => { renderDocBar(); renderPlayerMsg(); renderFpsNote(); updateUndo(); if (PACK) PACK.changed(); }, relink: () => openRelink(), nextOp }) : null;

/* ---------- 3 パック(pack-tab.js) ---------- */
const PACK = window.EditPack ? EditPack.create({ S, $, esc, fmtT, fmtCs, toast, api, apiBlob, download, safeName, ago, TOKEN, rowSig, lockJob, saveDoc, saveSettings,
  c2rApi, c2rWait, c2rBase, cpExport, confirmOverwrite, CUT, tab: () => EDT.tab, onPacked, speakerColor, speakerColorByName, onSpeakerColors, putSettings: putSettingsNow }) : null;

/* ---------- 起動 ---------- */
async function boot(){
  $('#ver').textContent = 'v' + APP_VERSION;
  loadView(); setEditTab(tabFromHash() || 'tx', { hash: !!tabFromHash() });
  try {
    const ping = await api('/api/ping');
    if (ping.version !== APP_VERSION && !(window.UIKit && UIKit.restart && UIKit.restart.check($('#errBar'), APP_VERSION, ping.version)))   // 帯に「起動し直す」(段9 9-3)
      showErr(`画面(v${APP_VERSION})とサーバー(v${ping.version})の版が違います。黒い画面を閉じて、起動し直してください`);
  } catch (e){ return showErr(e.message + '。入口(youtube-tools フォルダの start.bat)から起動してください'); }
  try { S.tools = await api('/api/tools'); } catch {}
  $('#txBatchBox').hidden = !TOKEN;   // まとめて実行は入口から開いたときだけ(12 ⑦(b))
  $('#docAuto').hidden = !TOKEN;      // 今の文書のまとめて実行(docs/archive/followup-2026-09-27.md の 3)も同じ
  if (TOKEN) pollRuns();
  await loadRoster();
  if (S.tools){
    $('#optModel').innerHTML = S.tools.models.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
    if (S.tools.wcpp && S.tools.wcpp.ready && !$('#optDevice option[value="vulkan"]')){   // AMD などの GPU(whisper.cpp)は、作ってあるときだけ選べる(段2-2)
      const o = document.createElement('option'); o.value = 'vulkan'; o.textContent = 'GPU(AMD など・whisper.cpp)'; $('#optDevice').append(o);
    }
    $('#optLang').innerHTML = S.tools.langs.map(l => `<option value="${esc(l)}">${esc({ ja: '日本語', en: '英語', ko: '韓国語', zh: '中国語', auto: '自動判定' }[l] || l)}</option>`).join('');
  }
  await loadSettings();   // 読めなければ ⚙ に「読み直す」を出し、読み直すまで保存しない(監査 11)
  if (KM) KM.reload();   // 校正のキーは編集の設定。共通の再生キーを以前ここに保存していたら、ホームの設定へ移す(部品が 1 回だけ)
  if (S.settings.speakerColors === undefined){   // 話者の色のスイッチは、以前はこのブラウザ(tx.pk.speakerColors)。初回だけサーバーへ移す(localStorage は消さない)
    try { if (localStorage.getItem('tx.pk.speakerColors') === '0'){ S.settings.speakerColors = false; saveSettings(); } } catch {}
  }
  applySettings(); renderSetup(); renderDiarSetup(); renderRtSetup(); renderOptSummary(); renderKeyUI();   // キー配置は設定(サーバー)に入っている
  takeUrlParams();   // ?media= / ?clip=(他のツールからのリンク)。設定を読んだあとに入れる(タブの切り替えで上書きされないように)
  loadSiblings();
  try { const j = await api('/api/jobs'); for (const x of j.jobs) if (x.state === 'done' || x.state === 'error') S.seen.add(x.id); } catch {}   // 開く前に終わっていたものは知らせない
  if (window.UIKit && UIKit.hide){ UIKit.hide.onChange(l => { if (!l || l === 'transcripts') renderList(); }); UIKit.hide.load().then(() => renderList()); }
  await Promise.all([loadList(), loadMarker(), pollJobs(), loadLearned(), loadAcc(), loadDataset(), loadProgress(), loadBaselines()]);
  if (S.jobs.some(j => ACTIVE.has(j.state))) startPolling();
}
boot();
