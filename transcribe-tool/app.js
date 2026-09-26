(() => {
'use strict';
const APP_VERSION = '0.14.0';
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const S = { tools: null, settings: {}, marker: { found: false, videos: [] }, jobs: [], list: [], doc: null, docId: null, dirty: false, saving: false,
  undo: [], sel: new Set(), curIdx: -1, playEnd: null, seen: new Set(), pollT: null,
  navIdx: -1, conflict: false, forceNext: false, baseUpdatedAt: null, stripR: null, sess: { n: 0, activeMs: 0, lastBreak: 0, lastAct: Date.now() } };
const PALETTE = ['#2f62d6', '#d9534f', '#2e9e5b', '#c98a12', '#8a4fd6', '#0f9aa8', '#d6479a', '#6b7280'];

/* ---------- 共通 ---------- */
function fmtT(t, ms){
  t = Math.max(0, Number(t) || 0);
  const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
  const ss = ms ? s.toFixed(1).padStart(4, '0') : String(Math.floor(s)).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}
function parseT(str){
  str = String(str || '').trim().replace(/[：]/g, ':');
  if (!str) return NaN;
  const p = str.split(':');
  if (p.length > 3 || p.some(x => !/^\d+(\.\d+)?$/.test(x.trim()))) return NaN;
  return p.reduce((a, x) => a * 60 + Number(x), 0);
}
let toastT = null;
/* kind: 'ok' | 'err' | 'info'(左の色の印。省略可)。押すと消える */
function toast(msg, ms = 3800, kind = ''){ const t = $('#toast'); t.textContent = msg; t.className = 'toast' + (kind ? ' ' + kind : ''); t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, ms); }
$('#toast').addEventListener('click', () => { $('#toast').hidden = true; });
function showErr(msg){ const b = $('#errBar'); b.textContent = '画面エラー: ' + msg; b.hidden = false; }
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
async function api(path, opt = {}){
  const init = { cache: 'no-store', method: opt.method || 'GET', ...(opt.keepalive ? { keepalive: true } : {}) };
  if (opt.body !== undefined){ init.method = opt.method || 'POST'; init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(opt.body); }
  if (TOKEN && init.method !== 'GET' && init.method !== 'HEAD') init.headers = { ...(init.headers || {}), 'X-YTT-Token': TOKEN };
  let r;
  try { r = await fetch(apiUrl(path), init); } catch { throw new Error('サーバーに接続できません。黒い画面(ターミナル)が閉じていないか確認してください'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok){ const er = new Error(j.message || ('エラー ' + r.status)); er.code = j.error; er.status = r.status; throw er; }
  return j;
}
/* ファイル(zip)を受け取る POST。失敗時は api() と同じ形のエラー。成功時は Response(ヘッダーと blob を使う) */
async function apiBlob(path, body){
  let r;
  try { r = await fetch(apiUrl(path), { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json', ...(TOKEN ? { 'X-YTT-Token': TOKEN } : {}) }, body: JSON.stringify(body) }); }
  catch { throw new Error('サーバーに接続できません。黒い画面(ターミナル)が閉じていないか確認してください'); }
  if (!r.ok){ const j = await r.json().catch(() => ({})); const er = new Error(j.message || ('エラー ' + r.status)); er.code = j.error; er.status = r.status; throw er; }
  return r;
}
function download(blob, name){
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 30000);
}
const safeName = (t, fb = 'transcript') => String(t || '').replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_').trim().slice(0, 80) || fb;
/* 話者の色: 文書の JSON は手で直せるので、色の文字列は #rgb / #rrggbb だけを通す(style 属性に入れるため。
   そのまま入れると「red;background:url(外部)」のような値で CSS を差し込まれ、外へ通信されうる) */
const spColor = sp => sp && /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(String(sp.color || '')) ? sp.color : '';
function setRowSp(row, sp){ const c = spColor(sp); if (c) row.style.setProperty('--sp', c); else row.style.removeProperty('--sp'); }
function armDelete(btn, run){
  if (btn.dataset.armed){ run(); return; }
  const label = btn.textContent; btn.dataset.armed = '1'; btn.textContent = 'もう一度押す';
  setTimeout(() => { if (btn.isConnected){ delete btn.dataset.armed; btn.textContent = label; } }, 3000);
}
const uid = () => 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const norm = s => String(s).normalize('NFKC').toLowerCase();

/* ---------- 表示の好み(長時間の作業向け。このブラウザにだけ保存) ---------- */
const VIEW_KEY = 'tx.view.v1';
const V = { menu: true, fs: '15', dense: false, vid: 'l', follow: true, frameFollow: false, adjStep: '0.1', autoNext: false, rate: '1', brk: '45', sideTab: 'start' };
const VID_H = { s: '18vh', m: '28vh', l: '38vh' };
/* v0.9.8: 左のメニューの開閉(V.menu)は保存する(上の「☰」ボタンがいつも見えているので、閉じたままでも迷わない)。
   文字起こしを開いていないときに閉じていると何も見えないので、その場合は案内にボタンを出す(showNoDoc) */
function loadView(){
  try {
    const o = JSON.parse(localStorage.getItem(VIEW_KEY) || '{}');
    if (o && typeof o === 'object'){
      for (const k of Object.keys(V)) if (k in o && typeof o[k] === typeof V[k]) V[k] = o[k];
      /* 画面の色は ui-kit(localStorage の ytt:theme)に1本化した(ヘッダーの切り替えボタンと「表示」の設定のどちらで変えても同じ所に保存)。
         以前の版が tx.view.v1 の theme に保存していた選択は、ui-kit にまだ選択が無いときだけ引き継ぐ */
      if ((o.theme === 'light' || o.theme === 'dark') && window.UIKit && UIKit.theme.get() === 'system'){ try { if (localStorage.getItem('ytt:theme') === null) UIKit.theme.set(o.theme); } catch {} }
      if ('theme' in o){ delete o.theme; saveView(); }
    }
  } catch {}
}
function saveView(){ try { localStorage.setItem(VIEW_KEY, JSON.stringify(V)); } catch {} }
function applySideTab(){
  if (!['start', 'files', 'quality', 'data'].includes(V.sideTab)) V.sideTab = 'start';
  document.querySelectorAll('[data-side-tab]').forEach(b => b.setAttribute('aria-selected', b.dataset.sideTab === V.sideTab ? 'true' : 'false'));
  document.querySelectorAll('[data-side-pane]').forEach(p => { p.hidden = p.dataset.sidePane !== V.sideTab; });
}
function setSideTab(tab, openPanel = true){ V.sideTab = tab; if (openPanel) V.menu = true; saveView(); applyView(); }   // タブの切り替え(v0.9.9: GPT 版のタブを ☰ のメニューの中に統合)
function applyView(){
  const r = document.documentElement;
  if (!['13', '15', '17', '20'].includes(V.fs)) V.fs = '15';
  if (!['l', 'm', 's', 'a'].includes(V.vid)) V.vid = 'l';
  if (!['0.75', '1', '1.25', '1.5', '1.75', '2'].includes(V.rate)) V.rate = '1';
  if (!['0', '30', '45', '60'].includes(V.brk)) V.brk = '45';
  r.style.setProperty('--fs', V.fs + 'px'); r.style.setProperty('--vh', VID_H[V.vid] || VID_H.l);
  r.classList.toggle('dense', !!V.dense); r.classList.toggle('vid-audio', V.vid === 'a');
  applySideTab();
  $('.app').classList.toggle('menu-closed', !V.menu);
  $('#btnMenu').setAttribute('aria-expanded', V.menu ? 'true' : 'false'); $('#btnMenuT').textContent = V.menu ? 'メニューを閉じる' : 'メニューを開く';
  $('#noDocMenu').hidden = !!V.menu;
  $('#vFs').value = V.fs; $('#vVid').value = V.vid; $('#vDense').checked = V.dense; syncThemeSelect(); $('#vBrk').value = V.brk;
  if (!['0.05', '0.1', '0.25', '0.5', '1'].includes(V.adjStep)) V.adjStep = '0.1';
  $('#follow').checked = V.follow; $('#frameFollow').checked = !!V.frameFollow; $('#adjStep').value = V.adjStep; $('#autoNext').checked = V.autoNext; $('#rate').value = V.rate;
  const p = $('#player'); p.defaultPlaybackRate = Number(V.rate); p.playbackRate = Number(V.rate);
  if (S.doc){ autoSizeSoon(); drawStripSoon(); }
}
/* 画面の色: 「表示」の選択肢(auto/light/dark)と ui-kit の選択('system'/'light'/'dark')を対応づける。保存は ui-kit だけ */
function syncThemeSelect(){ const p = window.UIKit ? UIKit.theme.get() : 'system'; $('#vTheme').value = p === 'system' ? 'auto' : p; }
if (window.UIKit) UIKit.theme.onChange(() => { syncThemeSelect(); if (S.doc) drawStripSoon(); });   // ヘッダーのボタン・別のタブ・OS の設定で変わったとき(帯の色も描き直す)
function toggleMenu(open){ V.menu = open === undefined ? !V.menu : !!open; saveView(); applyView(); }
/* メニューの中の項目へ移動する(閉じていれば開く) */
function showInMenu(el){ const pane = el.closest('[data-side-pane]'); if (pane) V.sideTab = pane.dataset.sidePane; V.menu = true; saveView(); applyView(); if (el.tagName === 'DETAILS') el.open = true; el.scrollIntoView({ block: 'center' }); }
{
  const bind = (id, key, get) => $('#' + id).addEventListener('change', e => { V[key] = get(e.target); saveView(); applyView(); });
  bind('vFs', 'fs', t => t.value); bind('vVid', 'vid', t => t.value); bind('vDense', 'dense', t => t.checked); bind('vBrk', 'brk', t => t.value);
  $('#vTheme').addEventListener('change', e => { if (window.UIKit) UIKit.theme.set(e.target.value === 'auto' ? 'system' : e.target.value); });
  bind('follow', 'follow', t => t.checked); bind('frameFollow', 'frameFollow', t => t.checked); bind('adjStep', 'adjStep', t => t.value); bind('autoNext', 'autoNext', t => t.checked); bind('rate', 'rate', t => t.value);
  $('#btnMenu').addEventListener('click', () => toggleMenu());
  $('#btnMenuClose').addEventListener('click', () => toggleMenu(false));
  $('#noDocMenu').addEventListener('click', () => toggleMenu(true));
  document.querySelectorAll('[data-side-tab]').forEach(b => b.addEventListener('click', () => setSideTab(b.dataset.sideTab, false)));
  $('#btnKeys').addEventListener('click', () => $('#keys').showModal());
  $('#jobBadge').addEventListener('click', () => showInMenu($('#jobsCard')));
  document.addEventListener('click', e => document.querySelectorAll('details.pop[open], details.ui-menu[open]').forEach(d => { if (!d.contains(e.target) || e.target.closest('.ui-menu-pop a')) d.open = false; }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelectorAll('details.pop[open], details.ui-menu[open]').forEach(d => { d.open = false; }); });
}

/* ---------- 他のツール(実際のポートはサーバーの /api/siblings。答えない・古いサーバーなら既定のポート) ---------- */
S.ports = null;
function renderTools(){
  const el = $('#toolNav'); if (!el || !window.UIKit) return;
  UIKit.tools.render(el, { current: 'transcribe', ports: S.ports || undefined });
  /* /api/siblings が答えた(=起動中のツールが分かっている)のに載っていないツールは、起動していない。押しても開けないことを先に知らせる(スタジオと同じ) */
  if (S.ports){
    const links = el.querySelectorAll('a');
    UIKit.tools.list.forEach((t, i) => {
      const a = links[i]; if (!a || t.id === 'transcribe' || S.ports[t.id]) return;
      const sm = a.querySelector('small'); if (sm) sm.textContent += '(起動していないようです。そのツールの start.bat で起動してください)';
      a.classList.add('tt-tool-off');
    });
  }
}
let sibP = null;
function loadSiblings(){
  if (sibP) return sibP;
  sibP = api('/api/siblings')
    .then(j => {
      S.ports = j && j.tools && typeof j.tools === 'object' ? j.tools : null;
      if (window.UIKit && UIKit.tools.setPaths) UIKit.tools.setPaths(j && j.paths);   // 入口の統合サーバーに取り込まれたツールの場所(/studio/ など)
    })
    .catch(() => { S.ports = null; })   // 古いサーバー(404)・通信の失敗は、既定のポートで
    .finally(() => { sibP = null; renderTools(); renderHandoff(); });
  return sibP;
}
const toolUrl = (id, path) => window.UIKit ? UIKit.tools.url(id, S.ports, path) : '';
$('#toolMenu').addEventListener('toggle', () => { if ($('#toolMenu').open) loadSiblings(); });   // 開くたびに確かめ直す(あとから起動したツールにも気づけるように)
renderTools();

/* ---------- 設定(用語集・置換辞書など) ---------- */
let setT = null;
function saveSettings(){ clearTimeout(setT); setT = setTimeout(() => { setT = null; api('/api/settings', { method: 'PUT', body: S.settings }).catch(() => {}); }, 600); }
/* 入力の直後(0.6秒以内)にタブを閉じても設定が消えないように、画面を離れるときは待たずに送る(keepalive: 閉じたあとも送り切る) */
document.addEventListener('visibilitychange', () => { if (document.hidden && setT){ clearTimeout(setT); setT = null; api('/api/settings', { method: 'PUT', body: S.settings, keepalive: true }).catch(() => {}); } });
function readOpts(){
  const s = S.settings;
  s.device = $('#optDevice').value; s.model = $('#optModel').value; s.language = $('#optLang').value; s.quality = $('#optQuality').value; s.vadMode = $('#optVad').value; s.boost = $('#optBoost').checked; s.autoDict = $('#optAutoDict').checked; s.wordSplit = $('#optWordSplit').checked; s.stripPunct = $('#optStripPunct').checked; s.autoGloss = $('#optAutoGloss').checked; s.autoLearned = $('#optAutoLearned').checked; s.archiveAuto = $('#arcAuto').checked; s.archiveFull = $('#arcFull').checked;
  if ($('#rtModel').value){ s.rtModel = $('#rtModel').value; s.rtTarget = $('#rtTarget').value; }
  s.glossary = $('#optGloss').value.slice(0, 4000); s.replacements = $('#repDict').value.slice(0, 20000);
  s.exBase = $('#exBase').value; s.exWrap = $('#exWrap').value; s.exSpk = $('#exSpk').checked; s.exTs = $('#exTs').checked; s.mPad = $('#mPad').value; s.mFilter = $('#mFilter').value; s.diarNum = $('#diarNum').value; s.diarEmb = $('#diarEmb').value;
  saveSettings(); if (S.doc) renderTerms();
}
function applySettings(){
  const s = S.settings;
  if (s.model && [...$('#optModel').options].some(o => o.value === s.model)) $('#optModel').value = s.model;
  if (s.language && [...$('#optLang').options].some(o => o.value === s.language)) $('#optLang').value = s.language;
  $('#optQuality').value = s.quality === 'fast' ? 'fast' : 'best'; $('#optDevice').value = ['cuda', 'cpu'].includes(s.device) ? s.device : 'auto'; $('#optVad').value = ['normal', 'off'].includes(s.vadMode) ? s.vadMode : 'weak'; $('#optBoost').checked = !!s.boost; $('#optAutoDict').checked = s.autoDict !== false; $('#optWordSplit').checked = s.wordSplit !== false; $('#optStripPunct').checked = s.stripPunct !== false; $('#optAutoGloss').checked = s.autoGloss !== false; $('#optAutoLearned').checked = s.autoLearned === true; $('#arcAuto').checked = s.archiveAuto !== false; $('#arcFull').checked = s.archiveFull !== false;
  $('#optGloss').value = s.glossary || ''; $('#repDict').value = s.replacements || ''; if (typeof renderGlossFit === 'function') renderGlossFit();
  if (s.exBase) $('#exBase').value = s.exBase; if (s.exWrap) $('#exWrap').value = s.exWrap;
  $('#exSpk').checked = !!s.exSpk; $('#exTs').checked = !!s.exTs; if (s.mPad) $('#mPad').value = s.mPad; if (s.mFilter) $('#mFilter').value = s.mFilter;
  if (s.diarNum && [...$('#diarNum').options].some(o => o.value === s.diarNum)) $('#diarNum').value = s.diarNum;
}

/* ---------- 準備状況 ---------- */
function renderSetup(){
  const t = S.tools, box = $('#setup'); if (!t){ box.innerHTML = ''; return; }
  const miss = [];
  if (!t.ffmpeg) miss.push('<b>ffmpeg</b> が見つかりません。Windows: <code>winget install Gyan.FFmpeg</code> / Mac: <code>brew install ffmpeg</code>(入れたらこのツールを起動し直す)');
  if (!t.fasterWhisper && t.backend !== 'fake') miss.push('<b>faster-whisper</b> が入っていません。フォルダ内の <code>install.bat</code>(Mac は <code>install.command</code>)を実行してください');
  const extra = t.backend === 'fake' ? '<details class="setup-banner"><summary>テスト用モード</summary><div class="setup-body">実際の文字起こしはしません。</div></details>' : '';
  let gpu = '';
  if (t.backend !== 'fake' && !miss.length){
    if (t.cuda) gpu = `<p class="hint" style="margin:0 0 10px">GPU${t.nvidia ? '(' + esc(t.nvidia) + ')' : ''}を使って処理します。</p>`;
    else if (t.nvidia) gpu = `<div class="notice"><b>${esc(t.nvidia)}</b> が見つかりましたが、GPU 用のライブラリが入っていないため CPU で処理します。<br>フォルダ内の <code>install-gpu.bat</code> を実行すると GPU が使えます(実行後に起動し直す)。</div>`;
    else gpu = '<p class="hint" style="margin:0 0 10px">NVIDIA の GPU が見つからないため、CPU で処理します(AMD・Intel の GPU は使えません)。長い動画は時間がかかるため、「small」や「速度優先」がおすすめです。</p>';
  }
  const env = (Array.isArray(t.envWarnings) ? t.envWarnings : []).slice(0, 8);   // サーバーの起動時の確認(ディスクの空き・OneDrive・部品の欠けなど)
  const envHtml = env.length ? `<details class="setup-banner"${miss.length ? '' : ' open'}><summary>起動時の確認(${env.length}件)</summary><div class="setup-body">${env.map(x => esc(x)).join('<br>')}</div></details>` : '';
  box.innerHTML = extra + envHtml + (miss.length ? `<details class="setup-banner" open><summary>準備が必要です(${miss.length}件)</summary><div class="setup-body">${miss.join('<br>')}</div></details>` : '') + gpu;
}

/* ---------- 進行度 ---------- */
const MILESTONES = [[1800, '辞書・名簿・提案の効果を、数字で測れる'], [3600, '設定の比較(A/B)で方針を決められる'], [10800, '追加学習(LoRA)を小さく試せる']];
let PG = null;
const fmtDur = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}時間${String(m).padStart(2, '0')}分` : m >= 1 ? `${m}分${String(s % 60).padStart(2, '0')}秒` : `${s}秒`; };
function goalSec(){ const h = Number(S.settings.goalHours); return (Number.isFinite(h) && h >= 0.5 && h <= 200 ? h : 5) * 3600; }
function todayKey(){ const d = new Date(); return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; }
function renderProgress(){
  if (!PG) return;
  const goal = goalSec(), cur = PG.proofedSec, pct = Math.min(100, cur / goal * 100);
  $('#goalFill').style.width = pct + '%'; $('#goalBar').setAttribute('aria-valuenow', Math.round(pct));
  const shown = pct < 10 ? pct.toFixed(1) : String(Math.round(pct));
  $('#goalText').innerHTML = `<b>${fmtDur(cur)}</b> / ${fmtDur(goal)}(<b>${shown}%</b>)・${PG.proofedLines}行`;
  const bar = $('#goalBar'); bar.querySelectorAll('b').forEach(x => x.remove());
  const ms = MILESTONES.filter(m => m[0] < goal);
  for (const [s] of ms){ const b = document.createElement('b'); b.style.left = (s / goal * 100) + '%'; bar.appendChild(b); }
  const list = [...ms, [goal, '目標']];
  const next = list.find(m => cur < m[0]);
  $('#goalMs').innerHTML = list.map(([s, txt]) => `<div class="ms${cur >= s ? ' done' : ''}"><span class="ck">${cur >= s ? '✓' : '・'}</span><span>${fmtDur(s)}: ${esc(txt)}${next && next[0] === s ? `(あと ${fmtDur(s - cur)})` : ''}</span></div>`).join('');
  let base = cur;
  try { const o = JSON.parse(localStorage.getItem('tx.goalday') || 'null'); if (o && o.day === todayKey() && Number.isFinite(o.base)) base = o.base; else localStorage.setItem('tx.goalday', JSON.stringify({ day: todayKey(), base: cur })); } catch {}
  const gain = Math.max(0, cur - base);
  $('#goalToday').textContent = gain > 0 ? `今日は ${fmtDur(gain)} 進みました` : '今日はまだ進んでいません';
  { const n = PG.evalDocs, sec = PG.evalProofedSec, need = 1200, ok = n > 0 && sec >= need && !PG.evalPendingLines;
    $('#evalStat').innerHTML = `<div style="font-weight:600;font-size:13.5px">評価用(学習に使わない・精度を測るためだけ)</div>` + (n ? `<p style="margin:4px 0 0;font-size:13.5px"><b>${n}</b>本 ・ 校正済み <b>${fmtDur(sec)}</b> / 目安 ${fmtDur(need)}以上 ・ 全行校正済み ${PG.evalDocsDone}/${n}本</p>`
      + `<p class="hint" style="margin:2px 0 0">${ok ? '準備できました。「認識精度の測定」で「基準を記録」を押して、出発点を残してください。' : `${[PG.evalPendingLines ? `未校正の行が${PG.evalPendingLines}行あります` : '', sec < need ? `校正済みがあと ${fmtDur(need - sec)} ほど足りません` : ''].filter(Boolean).join(' ・ ')}。評価用は、全行を校正してください。`}</p>`
      : `<p class="hint" style="margin:4px 0 0">まだありません。文字起こしを開いて「評価用にする」にチェックしてください(2〜3本・合計20分以上が目安)。校正を始める前に決めてください。</p>`); }
  const p = $('#goalPill'); p.hidden = false; p.classList.toggle('on', cur > 0);
  p.textContent = `校正 ${fmtDur(cur)} / ${fmtDur(goal)}(${shown}%)`;
  p.style.background = `linear-gradient(90deg, var(--accent-soft) ${pct}%, var(--panel-2) ${pct}%)`;
  if (document.activeElement !== $('#goalHours')) $('#goalHours').value = String(goal / 3600);
  // 節目に届いたら、一度だけ知らせる
  try {
    const reached = list.filter(m => cur >= m[0]).length, seenN = Number(localStorage.getItem('tx.goalseen') || '-1');
    if (seenN >= 0 && reached > seenN) toast(`節目に届きました: ${fmtDur(list[reached - 1][0])}(${list[reached - 1][1]})`, 6000);
    if (reached !== seenN) localStorage.setItem('tx.goalseen', String(reached));
  } catch {}
}
async function loadProgress(){ try { PG = await api('/api/progress'); } catch { return; } renderProgress(); }
function scheduleProgress(){ clearTimeout(scheduleProgress.t); scheduleProgress.t = setTimeout(loadProgress, 2500); }
$('#goalHours').addEventListener('change', e => { const h = Number(e.target.value); if (!(h >= 0.5 && h <= 200)){ toast('0.5〜200 時間の間で入力してください'); e.target.value = String(goalSec() / 3600); return; } S.settings.goalHours = h; saveSettings(); renderProgress(); });
$('#goalPill').addEventListener('click', () => showInMenu($('#goalCard')));
/* 左の各カードの開閉を覚える */
document.querySelectorAll('aside details.card[id]').forEach(d => {
  try { if (localStorage.getItem('tx.fold.' + d.id) === '0') d.open = false; } catch {}
  d.addEventListener('toggle', () => { try { localStorage.setItem('tx.fold.' + d.id, d.open ? '1' : '0'); } catch {} });
});

/* ---------- 新規ジョブ ---------- */
let tab = 'file';
function setTab(t){
  tab = t; $('#paneFile').hidden = t !== 'file'; $('#paneMarker').hidden = t !== 'marker'; $('#paneFolder').hidden = t !== 'folder';
  $('#tabFile').setAttribute('aria-pressed', t === 'file'); $('#tabMarker').setAttribute('aria-pressed', t === 'marker'); $('#tabFolder').setAttribute('aria-pressed', t === 'folder');
  $('#btnStart').textContent = t === 'file' ? '文字起こしを開始' : t === 'folder' ? '選んだ動画を、それぞれ文字起こし' : '選んだポイントを文字起こし';
  if (t === 'folder') fdSyncStudio();
  if (t === 'marker') renderMarker();
}
function jobOpts(){
  return { model: $('#optModel').value, language: $('#optLang').value, quality: $('#optQuality').value, device: $('#optDevice').value, vadMode: $('#optVad').value, boost: $('#optBoost').checked, autoDict: $('#optAutoDict').checked, wordSplit: $('#optWordSplit').checked, stripPunct: $('#optStripPunct').checked, autoGloss: $('#optAutoGloss').checked, autoLearned: $('#optAutoLearned').checked, glossary: $('#optGloss').value };
}
async function startFile(){
  const path = $('#srcPath').value.trim();
  if (!path) return toast('ファイルのパスを入力してください');
  const a = $('#rStart').value.trim(), b = $('#rEnd').value.trim();
  const body = { sourcePath: path, title: $('#jTitle').value.trim(), ...jobOpts() };
  if (a){ const v = parseT(a); if (!Number.isFinite(v)) return toast('開始の時刻が正しくありません(例: 1:23:45)'); body.start = v; }
  if (b){ const v = parseT(b); if (!Number.isFinite(v)) return toast('終了の時刻が正しくありません(例: 1:30:00)'); body.end = v; }
  await api('/api/transcribe', { body });
  toast('待機列に追加しました');
}
async function startMarker(){
  const v = S.marker.videos[Number($('#mVideo').value)];
  if (!v) return toast('動画を選んでください');
  const path = $('#mPath').value.trim();
  const ids = [...document.querySelectorAll('#mClips input:checked')].map(x => Number(x.dataset.i));
  if (!ids.length) return toast('文字起こしするポイントを選んでください');
  if (!path){   // 元の動画が手元に無いときは、スタジオが書き出した切り抜き(mp4)を、そのまま文字起こしする
    const files = ids.map(i => v.clips[i].fileAbs).filter(Boolean);
    if (!files.length) return toast('元の動画・音声ファイルのパスを入力してください(書き出し済みの切り抜きが見つかったポイントは、パスなしでも文字起こしできます)');
    const r = await api('/api/transcribe-batch', { body: { paths: files, skipDone: true, ...jobOpts() } });
    return toast(`書き出し済みの切り抜き ${r.added.length}本を待機列に追加しました` + (r.skipped.length ? `(${r.skipped.length}本は文字起こし済みなどで追加せず)` : '') + (files.length < ids.length ? `。書き出されていない${ids.length - files.length}件は対象外` : ''), 6000);
  }
  const pad = Number($('#mPad').value) || 0;
  let n = 0;
  for (const i of ids){
    const c = v.clips[i];
    const start = Math.max(0, c.start - pad), end = c.end + pad;
    try {
      await api('/api/transcribe', { body: { sourcePath: path, start, end, title: c.title || `${v.title || v.videoId} ${fmtT(c.start)}-${fmtT(c.end)}`, ...jobOpts() } });
      n++;
    } catch (e){ toast(`${n}件追加したところで失敗: ${e.message}`); break; }
  }
  if (n) toast(`${n}件を待機列に追加しました`);
}
async function onStart(){
  readOpts();
  const btn = $('#btnStart'); btn.disabled = true;
  try { await (tab === 'file' ? startFile() : tab === 'folder' ? startFolder() : startMarker()); startPolling(); await pollJobs(); }
  catch (e){ toast(e.message); }
  finally { btn.disabled = false; }
}

/* ---------- フォルダ内すべて ---------- */
let FD = { files: [], dir: '' };
const fmtSize = n => n >= 1e9 ? (n / 1e9).toFixed(1) + 'GB' : n >= 1e6 ? Math.round(n / 1e6) + 'MB' : Math.max(1, Math.round(n / 1e3)) + 'KB';
function fdSyncStudio(){ const b = $('#fdStudio'); b.hidden = !S.marker.outDir; }
function renderFolder(){
  const box = $('#fdList'), skip = $('#fdSkip').checked;
  if (!FD.files.length){ box.innerHTML = '<p class="hint" style="padding:8px;margin:0">動画・音声が見つかりませんでした</p>'; $('#fdCount').textContent = ''; return; }
  box.innerHTML = FD.files.map((f, i) => {
    const st = f.doneTid ? '文字起こし済み' : f.queued ? '待機中' : '', off = skip && st;
    return `<label><input type="checkbox" data-i="${i}" ${off ? '' : 'checked'}><span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(f.path)}">${esc(f.rel)}</span><span class="hint">${fmtSize(f.size)}</span>${st ? `<span class="pill">${st}</span>` : ''}</label>`;
  }).join('');
  updateFdCount();
}
function updateFdCount(){ const n = document.querySelectorAll('#fdList input:checked').length, t = document.querySelectorAll('#fdList input').length; $('#fdCount').textContent = t ? `${n} / ${t} 本を選択` + (FD.truncated ? '(多いので、先頭の500本だけ)' : '') : ''; $('#fdAll').checked = t > 0 && n === t; }
async function scanFolder(){
  const path = $('#fdPath').value.trim(); if (!path) return toast('フォルダのパスを入力してください');
  const r = await api('/api/scan-folder', { body: { path, recursive: $('#fdRec').checked } });
  FD = { files: r.files, dir: r.dir, truncated: r.truncated }; renderFolder();
}
async function startFolder(){
  if (!FD.files.length) await scanFolder();
  const paths = [...document.querySelectorAll('#fdList input:checked')].map(x => FD.files[Number(x.dataset.i)].path);
  if (!paths.length) return toast('文字起こしする動画を選んでください');
  const r = await api('/api/transcribe-batch', { body: { paths, skipDone: $('#fdSkip').checked, ...jobOpts() } });
  const sk = r.skipped.length;
  toast(`${r.added.length}本を待機列に追加しました` + (sk ? `(${sk}本は追加していません: ${r.skipped.slice(0, 2).map(x => x.reason).join(' / ')}${sk > 2 ? ' ほか' : ''})` : ''), 6000);
  await scanFolder().catch(() => {});   // 追加した分に「待機中」を付け直す
}
$('#fdScan').addEventListener('click', () => scanFolder().catch(e => toast(e.message)));
$('#fdPath').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); scanFolder().catch(er => toast(er.message)); } });
$('#fdStudio').addEventListener('click', () => { $('#fdPath').value = S.marker.outDir || ''; $('#fdRec').checked = true; scanFolder().catch(e => toast(e.message)); });
$('#fdSkip').addEventListener('change', renderFolder);
$('#fdList').addEventListener('change', updateFdCount);
$('#fdAll').addEventListener('change', e => { document.querySelectorAll('#fdList input').forEach(x => { x.checked = e.target.checked; }); updateFdCount(); });

/* ---------- 切り抜きスタジオ/マーカー連携 ---------- */
function parseMarker(d){
  const out = [];
  let vids = d && typeof d === 'object' ? d.videos : null;
  if (Array.isArray(vids)) vids = Object.fromEntries(vids.filter(v => v && typeof v === 'object').map((v, i) => [String(v.videoId || v.id || i), v]));
  if (!vids || typeof vids !== 'object') return out;
  for (const [vid, v] of Object.entries(vids).slice(0, 500)){
    if (!v || typeof v !== 'object' || v.demo) continue;
    const clips = [], raw = ['clips', 'marks', 'points'].map(k => v[k]).find(Array.isArray) || [];
    for (const c of raw.slice(0, 500)){
      if (!c || typeof c !== 'object') continue;
      const a = Number(c && c.start), b = Number(c && c.end);
      if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) continue;
      clips.push({ start: a, end: b, title: String(c.title || c.label || '').slice(0, 120), src: String(c.src || '').slice(0, 8), score: Number.isFinite(Number(c.score)) && c.score !== null && c.score !== '' ? Number(c.score) : null, status: String(c.status || ''), file: String(c.file || '').slice(0, 500), rating: Math.round(Number(c.rating) || 0) });
    }
    if (clips.length) out.push({ videoId: String(vid).slice(0, 20), title: String(v.title || '').slice(0, 120), local: v.local === true,
      fileName: String(v.fileName || '').slice(0, 200), sourcePath: String(v.sourcePath || '').slice(0, 500), clips });
  }
  return out;
}
function renderMarker(){
  const vs = S.marker.videos, sel = $('#mVideo');
  $('#mStatus').textContent = S.marker.found ? `${(S.marker.sources || []).map(x => (x.kind === 'studio' ? '切り抜きスタジオ' : x.kind === 'file' ? '選んだ data.json' : '切り抜きマーカー') + x.videos + '本').join(' / ') || '切り抜きマーカー'}のデータを読み込みました(${vs.length}本の動画)` : '隣の clip-studio(または clip-marker)フォルダに data.json が見つかりません。下のボタンで data.json を選んでください。';
  const cur = sel.value;
  const FROM = { studio: 'スタジオ', marker: '旧マーカー', file: '選んだ data.json' };
  sel.innerHTML = vs.map((v, i) => `<option value="${i}">[${FROM[v.from || (S.marker.sources || [])[0]?.kind] || '?'}] ${esc((v.title || v.videoId) + (v.local ? '(ローカル)' : ''))} — ${v.clips.length}件</option>`).join('');
  $('#mSources').innerHTML = (S.marker.sources || []).map(x => `<div class="src"><span class="pill ok">${FROM[x.kind] || esc(x.kind)}</span><span>${Number(x.videos) || 0}本</span><span class="mono">${esc(x.path)}</span></div>`).join('')
    + (S.marker.outDir ? `<div class="src"><span class="pill">書き出し先</span><span class="mono">${esc(S.marker.outDir)}</span></div>` : '');
  if (cur && vs[Number(cur)]) sel.value = cur;
  renderMarkerClips();
}
function renderMarkerClips(){
  const v = S.marker.videos[Number($('#mVideo').value)], box = $('#mClips');
  if (!v){ box.innerHTML = '<p class="hint" style="padding:8px;margin:0">ポイントのある動画がありません</p>'; $('#mCount').textContent = ''; return; }
  if (document.activeElement !== $('#mPath')) $('#mPath').value = v.sourcePath || '';
  $('#mFileHint').textContent = v.sourcePath ? '' : v.clips.some(c => c.fileAbs) ? '元の動画のパスが空でも、書き出し済みの切り抜きは、そのまま文字起こしできます(パスを入れると、元の動画のその区間を文字起こしします)' : (v.fileName ? `切り抜きマーカーで開いたファイル名: ${v.fileName}(パスは入力が必要です)` : 'YouTube の動画は、手元にファイルがある場合だけ使えます');
  const only = $('#mFilter').value === 'adopted', skip = $('#mSkip').checked;
  const rows = v.clips.map((c, i) => ({ c, i })).filter(x => !only || x.c.status === 'adopted' || x.c.status === 'exported');
  box.innerHTML = rows.length ? rows.map(({ c, i }) => `<label><input type="checkbox" data-i="${i}" ${skip && c.doneTid ? '' : 'checked'}>
    <span class="mono">${fmtT(c.start)}–${fmtT(c.end)}</span><span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.title || '無題')}</span>
    ${c.src ? `<span class="pill" title="${c.src === 'auto' ? '自動で見つけた区間' : '自分でマークした区間'}${c.score != null ? '(点数 ' + esc(c.score) + ')' : ''}">${c.src === 'auto' ? '自動' + (c.score != null ? ' ' + esc(c.score) : '') : c.src === 'manual' ? '手動' : esc(c.src)}</span>` : ''}${c.fileAbs ? '<span class="pill ok" title="書き出し済みの切り抜き(mp4)が見つかりました">mp4あり</span>' : ''}${c.doneTid ? '<span class="pill" title="この範囲は、すでに文字起こし済みです">文字起こし済み</span>' : ''}
    <span class="pill">${esc({ '': '候補', candidate: '候補', adopted: '採用', rejected: '不採用', exported: '書き出し済み' }[c.status] ?? c.status)}</span></label>`).join('')
    : '<p class="hint" style="padding:8px;margin:0">条件に合うポイントがありません(「対象」を「すべて」にしてみてください)</p>';
  $('#mAll').checked = true; updateMCount();
}
function updateMCount(){ const n = document.querySelectorAll('#mClips input:checked').length, t = document.querySelectorAll('#mClips input').length; $('#mCount').textContent = t ? `${n} / ${t} 件を選択` : ''; }
async function loadMarker(){
  try { S.marker = await api('/api/marker'); } catch { S.marker = { found: false, videos: [] }; }
  renderMarker(); fdSyncStudio();
}

/* ---------- ジョブの進捗 ---------- */
const ACTIVE = new Set(['queued', 'extracting', 'loading', 'running']);
const STATE_LABEL = { queued: '待機中', extracting: '準備中', loading: '準備中', running: '処理中', done: '完了', error: '失敗', cancelled: '中止' };
function startPolling(){ if (!S.pollT) S.pollT = setInterval(pollJobs, 1000); }
async function pollJobs(){
  let j; try { j = await api('/api/jobs'); } catch { return; }
  S.jobs = j.jobs.slice().reverse();
  let doneNew = false, diar = null, abDone = null, txDone = [], failed = null;
  for (const x of S.jobs){
    if (S.seen.has(x.id)) continue;
    if (x.state === 'done'){ S.seen.add(x.id); doneNew = true; if (LOCK_KINDS.includes(x.kind)) diar = x; else if (x.kind === 'abtest') abDone = x; else if (x.tid) txDone.push(x); }
    else if (x.state === 'error'){ S.seen.add(x.id); failed = x; }   // 失敗も一度だけ知らせる(メニューを閉じていると気づけないため)
  }
  renderJobs(); applyLock();
  if (failed) toast(`「${failed.title || '無題'}」の処理に失敗しました: ${failed.error || ''}`, 8000, 'err');
  if (abDone){ loadEvals(); toast('設定の比較が終わりました。左の「認識精度の測定」に結果が出ます'); }
  if (doneNew){
    await loadList();
    if (diar){
      if (diar.kind === 'diarize'){ try { S.tools = await api('/api/tools'); renderDiarSetup(); } catch {} }
      loadLearned();
      if (diar.tid === S.docId) await openDoc(diar.tid, true);
      toast(diar.kind === 'retranscribe' ? `${diar.segments}行を再認識しました。` + (diar.unsure ? `まだ不確かな行が${diar.unsure}行あります` : '')
        : `話者を判別しました(${diar.speakers}人)。` + (diar.unsure ? `不確かな行が${diar.unsure}行あります(「要確認」で絞り込めます)` : '「話者」で名前を付けてください'));
    } else if (!S.doc){ const last = S.jobs.find(x => x.state === 'done' && x.tid); if (last) openDoc(last.tid); }
    else if (txDone.length) toast(txDone.length > 1 ? `${txDone.length}本の文字起こしが終わりました(メニューの「履歴」から開けます)` : `「${txDone[0].title || '無題'}」の文字起こしが終わりました(メニューの「処理状況」の「開く」で開けます)`, 6000, 'ok');
  }
  if (!S.jobs.some(x => ACTIVE.has(x.state))){ clearInterval(S.pollT); S.pollT = null; }
}
function renderJobBadge(){
  const act = S.jobs.filter(j => ACTIVE.has(j.state)), b = $('#jobBadge');
  b.hidden = !act.length; if (act.length){ const j = act[0]; b.textContent = `処理中 ${act.length}件 ${j.state === 'running' ? pctOf(j) + '%' : STATE_LABEL[j.state] || ''}`; }
}
const pctOf = j => Math.max(0, Math.min(100, Math.round((Number(j.progress) || 0) * 100)));
function renderJobs(){
  renderJobBadge();
  const box = $('#jobs');
  if (!S.jobs.length){ box.innerHTML = '<p class="hint" style="margin:6px 0 0">ジョブはありません</p>'; return; }
  box.innerHTML = S.jobs.slice(0, 10).map(j => `<div class="job" data-id="${esc(j.id)}">
    <div class="row" style="justify-content:space-between;flex-wrap:nowrap"><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500">${esc(j.title)}</span>
      <span class="pill ${j.state === 'done' ? 'ok' : j.state === 'error' ? 'err' : ACTIVE.has(j.state) ? (j.state === 'queued' ? 'wait' : 'run') : ''}">${esc(STATE_LABEL[j.state] || j.state)}</span></div>
    ${j.hasClip ? '<div class="hint" style="margin-top:2px">元の配信の情報(.clip.json)つき</div>' : ''}
    ${ACTIVE.has(j.state) ? `<div class="bar${j.state === 'running' ? '' : ' indeterminate'}"><i style="width:${pctOf(j)}%"></i></div><div class="row" style="justify-content:space-between;margin-top:3px"><span class="hint">${esc(j.phase || '')}${j.state === 'running' ? ' ' + pctOf(j) + '%' : ''}${j.device ? '(' + (j.device === 'cuda' ? 'GPU' : 'CPU') + ')' : ''}</span><button type="button" class="btn small" data-act="cancel">中止</button></div>` : ''}
    ${j.error ? `<div class="hint" style="color:var(--danger);margin-top:3px">${esc(j.error)}</div>` : ''}
    ${(Array.isArray(j.warnings) ? j.warnings : []).slice(0, 3).map(w => `<div class="notice tt-jwarn">${esc(w)}</div>`).join('')}
    ${j.state === 'done' && j.kind === 'abtest' ? `<div class="row" style="margin-top:3px"><span class="hint">${j.segments}行で比較</span><button type="button" class="btn small" data-act="evalview">結果を見る</button></div>` : ''}
    ${j.state === 'done' && j.tid ? `<div class="row" style="margin-top:3px"><span class="hint">${j.kind === 'diarize' ? j.speakers + '人を判別' : j.kind === 'retranscribe' ? j.segments + '行を更新' : j.segments + '行'}</span><button type="button" class="btn small" data-act="open" data-tid="${esc(j.tid)}">開く</button></div>` : ''}
  </div>`).join('');
}

/* ---------- 保存済み一覧 ---------- */
async function loadList(){
  try { S.list = (await api('/api/transcripts')).items; } catch { S.list = []; }
  renderList(); scheduleProgress();
}
let txShowAll = false;
function renderList(){
  const box = $('#txList'); $('#txCount').textContent = S.list.length ? `(${S.list.length}件)` : '';
  if (!S.list.length){ box.innerHTML = '<p class="hint" style="margin:6px 0 0">まだありません</p>'; $('#txMore').hidden = true; return; }
  const q = norm($('#txSearch').value.trim()), type = $('#txFilter').value;
  const found = S.list.filter(i => (!q || norm(`${i.title || ''} ${i.sourceName || ''}`).includes(q)) && (type === 'all' || (type === 'eval') === !!i.evalSet));
  if (!found.length){ box.innerHTML = '<p class="hint" style="margin:8px 0">条件に合う文字起こしはありません</p>'; $('#txMore').hidden = true; return; }
  const shown = txShowAll ? found : found.slice(0, 8);
  box.innerHTML = shown.map(i => `<div class="txi${i.id === S.docId ? ' cur' : ''}" data-id="${esc(i.id)}">
    <div class="txi-head"><button type="button" class="t" data-act="open" title="${esc(i.title)}">${i.evalSet ? '<span class="pill ok">評価用</span> ' : ''}${esc(i.title || '無題')}</button><details class="pop txi-menu"><summary aria-label="${esc(i.title || '無題')}の操作">…</summary><div class="vpop"><button type="button" class="btn small danger" data-act="del">削除</button></div></details></div>
    <div class="hint">${esc(i.sourceName || '')}${i.end ? ` ・ ${fmtT(i.start)}–${fmtT(i.end)}` : ''} ・ ${Number(i.segments) || 0}行 ・ ${esc(String(i.model || '').split('/').pop())}${i.hasClip ? ' ・ 元の配信あり' : ''}</div>
    </div>`).join('');
  const more = $('#txMore'); more.hidden = found.length <= 8; more.textContent = txShowAll ? '最近の8件だけ表示' : `残り${found.length - shown.length}件を表示`;
}
$('#txSearch').addEventListener('input', () => { txShowAll = false; renderList(); });
$('#txFilter').addEventListener('change', () => { txShowAll = false; renderList(); });
$('#txMore').addEventListener('click', () => { txShowAll = !txShowAll; renderList(); });

/* ---------- 話者の自動判別 ---------- */
function renderDiarSetup(){
  const t = S.tools, box = $('#diarSetup'), d = t && t.diarize;
  if (!d){ box.innerHTML = ''; return; }
  const sel = $('#diarEmb'), cur = sel.value || S.settings.diarEmb || d.default;
  sel.innerHTML = d.embeddings.map(e => `<option value="${esc(e.key)}">${esc(e.label)}${e.ready ? '' : `(初回に約${e.mb}MBをダウンロード)`}</option>`).join('');
  sel.value = d.embeddings.some(e => e.key === cur) ? cur : d.default;
  const e = d.embeddings.find(x => x.key === sel.value);
  box.innerHTML = !d.ready ? '<div class="notice">話者の自動判別には、追加の部品(sherpa-onnx)が必要です。フォルダ内の <code>install-diarize.bat</code>(Mac は <code>install-diarize.command</code>)を実行して、ツールを起動し直してください。</div>'
    : (!(d.segReady && e && e.ready) ? `<p class="hint" style="margin:0">初回だけ、判別用のモデルを自動でダウンロードします(合計 約${(d.segReady ? 0 : 6) + (e ? e.mb : 0)}MB)。</p>` : '');
  $('#diarGo').disabled = !d.ready;
}
const LOCK_KINDS = ['diarize', 'retranscribe'];
function lockJob(){ return S.doc ? S.jobs.find(j => LOCK_KINDS.includes(j.kind) && j.tid === S.docId && ACTIVE.has(j.state)) : null; }
function applyLock(){
  const j = lockJob(), on = !!j;
  $('#segs').inert = on; $('#doc .card').inert = on; $('#docTitle').disabled = on;
  const b = $('#diarBanner'); b.hidden = !on;
  if (on) b.textContent = `${j.kind === 'retranscribe' ? '再認識' : '話者を判別'}しています(${j.phase}${j.state === 'running' ? ' ' + Math.round(j.progress * 100) + '%' : ''})。終わると自動で読み込み直します。それまで編集はできません(中止は左の「処理状況」から)。`;
}
async function startDiarize(){
  if (!S.doc) return;
  await saveDoc();
  if (S.dirty || S.saving) return toast('保存中です。少し待ってから、もう一度押してください');
  await api('/api/diarize', { body: { tid: S.docId, numSpeakers: Number($('#diarNum').value) || 0, embedding: $('#diarEmb').value } });
  startPolling(); await pollJobs(); toast('話者の判別を待機列に追加しました');
}
$('#btnSpk').addEventListener('click', () => {   // 折りたたみの中にあって見つけにくいので、上のボタンから開く
  const d = $('#spDetails'); d.open = !d.open;
  if (d.open) d.scrollIntoView({ block: 'start', behavior: 'smooth' });
});
$('#diarGo').addEventListener('click', e => {
  const b = e.currentTarget;
  const run = async () => { b.disabled = true; try { await startDiarize(); } catch (er){ toast(er.message); } finally { b.disabled = !(S.tools && S.tools.diarize && S.tools.diarize.ready); } };
  if (S.doc && (S.doc.speakers.length || S.doc.segments.some(s => s.speaker))) armDelete(b, run); else run();
});

/* ---------- 再認識 ---------- */
const SPK_FLAGS = ['声が混ざっている可能性', '話者が不確か', '話者を判別できなかった'];
function flagParts(s){ const p = String(s.flag || '').split('、').filter(Boolean); return { spk: p.filter(x => SPK_FLAGS.includes(x)), text: p.filter(x => !SPK_FLAGS.includes(x)) }; }
function flagMatch(s, kind){ if (kind === 'proofed') return !!s.proofed; if (kind === 'unproofed') return !s.proofed; if (kind === 'sug') return sugList(s).length > 0; const f = flagParts(s); return kind === 'any' ? !!s.flag : kind === 'text' ? f.text.length > 0 : f.spk.length > 0; }
function renderRtSetup(){
  const t = S.tools, sel = $('#rtModel'); if (!t) return;
  sel.innerHTML = t.models.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  const want = S.settings.rtModel && t.models.some(m => m[0] === S.settings.rtModel) ? S.settings.rtModel : (t.models.some(m => m[0] === 'large-v3') ? 'large-v3' : t.models[0][0]);
  sel.value = want;
  if (['text', 'sel', 'all', 'range'].includes(S.settings.rtTarget)) $('#rtTarget').value = S.settings.rtTarget;
}
const RANGE_MAX = 900;
function rtRange(){   // 選んだ行の最初〜最後(間の行も含む)
  const segs = S.doc.segments.filter(s => S.sel.has(s.id)); if (!segs.length) return null;
  const a = Math.min(...segs.map(s => s.start)), b = Math.max(...segs.map(s => s.end));
  return { a, b, ids: S.doc.segments.filter(s => { const m = (s.start + s.end) / 2; return m >= a - 1e-6 && m <= b + 1e-6; }).map(s => s.id) };
}
function rtIds(){
  if (!S.doc) return [];
  const k = $('#rtTarget').value, segs = S.doc.segments;
  if (k === 'range'){ const r = rtRange(); return r ? r.ids.slice(0, 2000) : []; }
  return segs.filter(s => k === 'all' || (k === 'sel' ? S.sel.has(s.id) : flagMatch(s, 'text'))).map(s => s.id).slice(0, 2000);
}
function updateRt(){
  if (!S.doc){ $('#rtHint').textContent = ''; return; }
  const ids = new Set(rtIds()), sec = S.doc.segments.filter(s => ids.has(s.id)).reduce((a, s) => a + (s.end - s.start), 0);
  $('#rtHint').textContent = `対象: ${ids.size}行(音声 約${sec < 90 ? Math.round(sec) + '秒' : Math.round(sec / 60) + '分'})`;
  $('#rtGo').disabled = !ids.size;
  if ($('#rtTarget').value === 'range'){
    const r = rtRange();
    $('#rtHint').textContent = r ? `範囲: ${fmtT(r.a)}〜${fmtT(r.b)}(${r.ids.length}行を、新しい行に差し替えます。行の数は変わります。選んでいない間の行も入ります)` + (r.b - r.a > RANGE_MAX ? ' — 長すぎます(最大15分)' : '') : '行を選んでください(チェックボックス)';
    if (!r || r.b - r.a > RANGE_MAX) $('#rtGo').disabled = true;
  }
}
async function startRetranscribe(){
  if (!S.doc) return;
  const ids = rtIds(); if (!ids.length) return toast('再認識する行がありません');
  await saveDoc();
  if (S.dirty || S.saving) return toast('保存中です。少し待ってから、もう一度押してください');
  await api('/api/retranscribe', { body: { tid: S.docId, ids, mode: $('#rtTarget').value === 'range' ? 'range' : 'each', vadMode: $('#optVad').value, wordSplit: $('#optWordSplit').checked, stripPunct: $('#optStripPunct').checked, model: $('#rtModel').value, language: $('#optLang').value, device: $('#optDevice').value,
    boost: $('#optBoost').checked, glossary: $('#optGloss').value, autoDict: $('#optAutoDict').checked, autoGloss: $('#optAutoGloss').checked } });
  startPolling(); await pollJobs(); toast(`${ids.length}行の再認識を待機列に追加しました`);
}
$('#rtGo').addEventListener('click', e => {
  const b = e.currentTarget;
  armDelete(b, async () => { b.disabled = true; try { await startRetranscribe(); } catch (er){ toast(er.message); } finally { updateRt(); } });   // 文字を上書きするので、2度押しにする
});
$('#rtTarget').addEventListener('change', updateRt);

/* ---------- 修正から学習した候補 ---------- */
let learned = { items: [], docs: 0 };
let learnedShowAll = false;
function scheduleLearn(){ clearTimeout(scheduleLearn.t); scheduleLearn.t = setTimeout(loadLearned, 4000); }
async function loadLearned(){
  try { learned = await api('/api/learned?min=' + encodeURIComponent($('#lnMin').value)); } catch { return; }
  renderLearned(); loadSuggest();
}
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
function renderLearned(){
  const box = $('#lnList'), items = learned.items;
  $('#lnStat').textContent = learned.docs ? `修正した行: ${learned.lines || 0}行(学習の対象: ${learned.docs}件の文字起こし)` : '';
  if (!items.length){
    box.innerHTML = `<p class="hint" style="margin:8px 0 0">${learned.docs ? '候補はありません(文字起こしを直すと、ここに出ます)' : 'v0.5 以降で文字起こしした分から学習します。文字起こしを直すと、ここに候補が出ます'}</p>`;
    $('#lnMore').hidden = true;
    return;
  }
  const q = norm($('#lnSearch').value.trim());
  const found = items.map((x, i) => ({ x, i })).filter(({ x }) => !q || norm(`${x.wrong} ${x.right}`).includes(q));
  if (!found.length){ box.innerHTML = '<p class="hint" style="margin:8px 0">条件に合う候補はありません</p>'; $('#lnMore').hidden = true; return; }
  const shown = learnedShowAll ? found : found.slice(0, 10);
  box.innerHTML = shown.map(({ x, i }) => {
    const d = lnDraft[lnKey(x)] || { w: x.wrong, r: x.right }, edited = d.w !== x.wrong || d.r !== x.right;
    return `<div class="ln${edited ? ' edited' : ''}" data-i="${i}">
    <div class="row" style="flex-wrap:nowrap;gap:4px"><input class="lw" type="text" value="${esc(d.w)}" maxlength="40" aria-label="誤(置換される文字)" style="flex:1;min-width:0"><span>→</span><input class="lr" type="text" value="${esc(d.r)}" maxlength="40" aria-label="正(置換後の文字)" style="flex:1;min-width:0"></div>
    <div class="row" style="margin-top:3px"><span class="pill">${x.count}回</span><button type="button" class="btn small" data-act="lnadd">登録</button><button type="button" class="btn small" data-act="lnign">無視</button><button type="button" class="btn small" data-act="lnrev"${edited ? '' : ' hidden'}>編集を戻す</button></div></div>`;
  }).join('') + '<p class="hint" style="margin:6px 0 0">「誤」「正」は、その場で直してから登録できます(例: 前後の文字を消して短くする)。</p>';
  const more = $('#lnMore'); more.hidden = found.length <= 10; more.textContent = learnedShowAll ? '上位10件だけ表示' : `残り${found.length - shown.length}件を表示`;
}
async function putSettingsNow(){ clearTimeout(setT); await api('/api/settings', { method: 'PUT', body: S.settings }); }
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
function sugList(s){ return S.sug.filter(x => x.seg === s.id && s.text.includes(x.wrong)); }
function sugHTML(s){
  return sugList(s).map(x => `<span class="sg ${x.tier === 'high' ? 'high' : ''}" title="${esc(`この置換は ${x.pos}回 直されています / そのまま残した例 ${x.neg}件`)}"><span class="sgl">${x.tier === 'high' ? '確度高' : '候補'}</span>「${esc(x.wrong)}」→「${esc(x.right)}」<button type="button" data-act="sgok" data-n="${x.n}">採用</button><button type="button" data-act="sgno" data-n="${x.n}">却下</button></span>`).join('');
}
function renderChips(){
  if (!S.doc) return;
  document.querySelectorAll('#segs .seg').forEach(el => { const s = S.doc.segments[Number(el.dataset.i)], box = el.querySelector('.sug'); if (s && box) box.innerHTML = sugHTML(s); });
  const hi = S.doc.segments.reduce((n, s) => n + sugList(s).filter(x => x.tier === 'high').length, 0), all = S.doc.segments.reduce((n, s) => n + sugList(s).length, 0);
  const b = $('#btnSugHigh'); b.hidden = !hi; b.textContent = `確度高の提案を全部採用(${hi})`;
  $('#flagKind').querySelector('option[value=sug]').textContent = all ? `修正の提案がある行だけ(${all}件)` : '修正の提案がある行だけ';
  if ($('#flagKind').value === 'sug') applyFilter();
}
let sugSeq = 0;
async function loadSuggest(){
  const id = S.docId; if (!id) return;
  let r; try { r = await api('/api/suggest?id=' + encodeURIComponent(id)); } catch { return; }
  if (S.docId !== id) return;
  S.sug = (r.items || []).map(x => ({ ...x, n: ++sugSeq })); renderChips();
}
function sugFeedback(action, xs){
  const tid = S.docId; if (!tid || !xs.length) return;
  api('/api/suggest/feedback', { body: { tid, action, items: xs.map(x => ({ seg: x.seg, wrong: x.wrong, right: x.right })) } }).catch(() => {});
}
function applySug(s, x){
  const k = s.text.startsWith(x.wrong, x.i) ? x.i : s.text.indexOf(x.wrong); if (k < 0) return false;
  s.text = (s.text.slice(0, k) + x.right + s.text.slice(k + x.wrong.length)).slice(0, 2000); delete s.proofed; return true;
}
function acceptSug(s, x){
  pushUndo();
  if (!applySug(s, x)){ S.undo.pop(); updateUndo(); return; }
  S.sug = S.sug.filter(y => y !== x); sugFeedback('accept', [x]); markDirty();
  const i = S.doc.segments.indexOf(s), ta = document.querySelector(`#segs .seg[data-i="${i}"] textarea`);
  if (ta){ ta.value = s.text; autoSize(ta); }
  syncProof(s); updatePfStat(); renderChips();
}
function rejectSug(x){ S.sug = S.sug.filter(y => y !== x); sugFeedback('reject', [x]); renderChips(); }
$('#btnSugHigh').addEventListener('click', () => {
  const done = [];
  pushUndo();
  for (const s of S.doc.segments) for (const x of sugList(s).filter(y => y.tier === 'high')) if (applySug(s, x)) done.push(x);
  if (!done.length){ S.undo.pop(); updateUndo(); return; }
  S.sug = S.sug.filter(y => !done.includes(y)); sugFeedback('accept', done); markDirty(); renderDoc(); renderChips();
  toast(`${done.length}件を採用しました(「元に戻す」で戻せます)`);
});

/* ---------- 校正済み(正解として使える行の印) ---------- */
function setProof(s, on, row){
  if (on && !s.proofed) S.sess.n++; else if (!on && s.proofed && S.sess.n > 0) S.sess.n--;
  if (on) s.proofed = true; else delete s.proofed;
  if (row){ row.classList.toggle('proofed', !!on); const b = row.querySelector('[data-act=proof]'); if (b) b.setAttribute('aria-pressed', on ? 'true' : 'false'); }
}
function syncProof(s){ const i = S.doc.segments.indexOf(s), row = document.querySelector(`#segs .seg[data-i="${i}"]`); if (row) setProof(s, !!s.proofed, row); }
function updatePfStat(){
  if (!S.doc) return;
  const n = S.doc.segments.filter(s => s.proofed).length, t = S.doc.segments.length;
  $('#pfStat').textContent = t ? `校正済み ${n}/${t}行` : '';
  $('#btnProofAll').textContent = t && n === t ? '校正済みを全解除' : '全行を校正済みに';
  $('#btnProofSel').disabled = !S.sel.size;
  renderAbHint(); updateSess(); drawStripSoon();
}
function updateSess(){
  if (!S.doc){ $('#sessStat').textContent = ''; return; }
  const un = S.doc.segments.filter(s => !s.proofed && s.text.trim()), sec = un.reduce((a, s) => a + (s.end - s.start), 0), m = Math.round(S.sess.activeMs / 60000);
  $('#sessStat').textContent = `未校正 ${un.length}行(音声 約${sec < 90 ? Math.round(sec) + '秒' : Math.round(sec / 60) + '分'}) ・ 今回 +${S.sess.n}行 ・ 作業${m}分`;
}
setInterval(() => {   // 操作している時間だけ数える(放置している間は進めない)。休憩のお知らせも、この時間で出す
  if (Date.now() - S.sess.lastAct < 120000){
    S.sess.activeMs += 30000; updateSess();
    const b = Number(V.brk) * 60000;
    if (b && S.sess.activeMs - S.sess.lastBreak >= b){ S.sess.lastBreak = S.sess.activeMs; toast(`操作を始めて${Math.round(S.sess.activeMs / 60000)}分たちました。少し休憩しませんか(目を離す・肩を回す・水分)`, 9000); }
  }
}, 30000);
['keydown', 'pointerdown', 'wheel'].forEach(t => window.addEventListener(t, () => { S.sess.lastAct = Date.now(); }, { passive: true, capture: true }));

/* ---------- 進み具合の帯(校正済み・要確認・未校正を、時間軸で見る) ---------- */
let stripQ = 0;
function drawStripSoon(){ if (!stripQ) stripQ = requestAnimationFrame(() => { stripQ = 0; drawStrip(); }); }
function drawStrip(){
  const cv = $('#strip'); if (!S.doc || !cv || !cv.offsetParent) return;
  const g = S.doc.segments; let a = Infinity, b = 0;
  for (const x of g){ if (x.start < a) a = x.start; if (x.end > b) b = x.end; }
  S.stripR = g.length && b > a ? [a, b] : null;
  const w = cv.clientWidth, h = cv.clientHeight, dpr = window.devicePixelRatio || 1;
  cv.width = Math.max(1, Math.round(w * dpr)); cv.height = Math.max(1, Math.round(h * dpr));
  if (!S.stripR) return;
  const c = cv.getContext('2d'), cs = getComputedStyle(document.documentElement);
  const col = { ok: cs.getPropertyValue('--ok').trim(), warn: cs.getPropertyValue('--warn').trim(), off: cs.getPropertyValue('--line-2').trim() }, k = cv.width / (b - a);
  for (const x of g){ c.fillStyle = x.proofed ? col.ok : x.flag ? col.warn : col.off; c.fillRect((x.start - a) * k, 0, Math.max(1, (x.end - x.start) * k - 0.5), cv.height); }
  moveStripHead();
}
function moveStripHead(){
  const r = S.stripR, hd = $('#stripHead'); if (!r) return;
  hd.style.left = Math.min(100, Math.max(0, (player().currentTime - r[0]) / (r[1] - r[0]) * 100)) + '%';
}
$('#strip').addEventListener('click', e => {
  const r = S.stripR; if (!r || !S.doc) return;
  const t = r[0] + e.offsetX / e.currentTarget.clientWidth * (r[1] - r[0]), segs = S.doc.segments;
  let lo = 0, hi = segs.length - 1, i = 0;
  while (lo <= hi){ const m = (lo + hi) >> 1; if (segs[m].start <= t){ i = m; lo = m + 1; } else hi = m - 1; }
  if (!gotoRow(i, { center: true })) return toast('その位置の行は、絞り込みで隠れています');
  player().currentTime = segs[i].start; S.playEnd = null;
});
$('#btnProofAll').addEventListener('click', e => {
  const b = e.currentTarget; if (!S.doc) return;
  armDelete(b, () => {
    delete b.dataset.armed;
    const all = S.doc.segments.length && S.doc.segments.every(s => s.proofed);
    pushUndo();
    for (const s of S.doc.segments){ if (all) delete s.proofed; else if (s.text.trim()) s.proofed = true; }
    renderDoc(); markDirty();
    toast(all ? '校正済みを全て解除しました' : '全行を校正済みにしました(「元に戻す」で戻せます)');
  });
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
async function loadBaselines(){
  let items = []; try { items = (await api('/api/eval-baselines')).items; } catch { return; }
  $('#blOut').innerHTML = items.length ? '<table class="acct"><tr><th>日時</th><th>メモ</th><th>CER</th><th>正解字</th><th>置換/脱落/挿入</th></tr>' + items.slice().reverse().slice(0, 12).map((x, i, a) => {
    const prev = a[i + 1], d = prev ? (x.cer - prev.cer) * 100 : null;
    return `<tr><td>${new Date(x.at).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td><td>${esc(x.label || '')}</td><td><b>${pct(x.cer)}</b>${d === null ? '' : `<br><span class="hint">${d <= 0 ? '' : '+'}${d.toFixed(1)}pt</span>`}</td><td>${x.refChars}</td><td>${x.sub}/${x.del}/${x.ins}</td></tr>`;
  }).join('') + '</table><p class="hint" style="margin:4px 0 0">pt = 1つ前の記録との差(マイナスがよくなった)。正解が1000字未満のうちは、差は誤差の範囲かもしれません。</p>' : '<p class="hint" style="margin:6px 0 0">まだ記録がありません</p>';
}
$('#blGo').addEventListener('click', async e => {
  const b = e.currentTarget; b.disabled = true;
  try { const r = await api('/api/eval-baseline', { body: { label: $('#blLabel').value } }); $('#blLabel').value = ''; toast(`記録しました: CER ${pct(r.cer)}(正解 ${r.refChars}字)`); await loadBaselines(); }
  catch (er){ toast(er.message); } finally { b.disabled = false; }
});
$('#accScope').addEventListener('change', loadAcc);
function scheduleAcc(){ clearTimeout(accT); accT = setTimeout(loadAcc, 4000); }
async function loadAcc(){
  try { renderAcc(await api('/api/metrics?legacy=' + ($('#accLegacy').checked ? 1 : 0) + '&scope=' + encodeURIComponent($('#accScope').value))); } catch (e){ $('#accOut').innerHTML = `<p class="hint" style="margin:8px 0 0;color:var(--danger)">${esc(e.message)}</p>`; }
}
function renderAcc(m){
  const o = m.overall, box = $('#accOut');
  if (!o.groups){
    box.innerHTML = `<p class="hint" style="margin:8px 0 0">校正済みの行がまだありません(${m.docs}件の文字起こしのうち、校正済みの行があるのは${m.docsProofed}件)。聞いて確認した行の「校正済み」ボタン(Shift+Space)で印を付けると、ここに文字誤り率が出ます。「印のない旧データも含める」で、これまでに直した分を仮計算できます。</p>`;
    return;
  }
  const errs = o.errs || 0, share = v => errs ? Math.round(v / errs * 100) + '%' : '—';
  const rows = list => list.map(c => `<tr><td>${esc(c.config || c.title || '')}</td><td>${c.groups}</td><td>${c.refChars}</td><td><b>${pct(c.cer)}</b></td><td>${c.sub}/${c.del}/${c.ins}</td></tr>`).join('');
  box.innerHTML = `<div class="accmain">文字誤り率(CER) <b>${pct(o.cer)}</b> <span class="hint">誤り ${errs}字 ÷ 正解 ${o.refChars}字</span></div>
    <p class="hint" style="margin:4px 0 0">内訳: 置換(別の字に間違い) ${o.sub}字(${share(o.sub)}) ・ 脱落(聞き逃し) ${o.del}字(${share(o.del)}) ・ 挿入(余計な字。幻覚など) ${o.ins}字(${share(o.ins)})<br>
    機械が出したが人が消した行: ${o.machineOnly}行(${o.machineOnlyChars}字) ・ 用語が正しく出た率: ${o.termRef ? `${o.termHit}/${o.termRef}(${pct(o.termRate)})` : '—'} ・ 用語の誤挿入: ${o.termExtra}回</p>
    <p class="hint" style="margin:4px 0 0">${m.legacy ? '※ 校正済みの印がない旧データを仮計算に含んでいます。' : ''}${o.refChars < 1000 ? '※ 正解が1000字未満なので、数値は目安です(同じ動画を何度も文字起こしした分は、重複して数えられます)。' : ''}校正済み ${m.proofedLines}行 ・ 対象 ${m.byDoc.length}件</p>
    <table class="acct"><tr><th>設定</th><th>行数</th><th>正解字</th><th>CER</th><th>置換/脱落/挿入</th></tr>${rows(m.byConfig)}</table>
    <details style="margin-top:6px"><summary class="hint">文字起こしごと</summary><table class="acct"><tr><th>文字起こし</th><th>行数</th><th>正解字</th><th>CER</th><th>置換/脱落/挿入</th></tr>${rows(m.byDoc)}</table></details>
    <details style="margin-top:6px"><summary class="hint">誤りが多い場所(上位)</summary>${o.worst.map(w => `<div class="wl"><span class="mono">${esc(w.doc || '')} ${fmtT(w.start)}</span><br>正: ${esc(w.ref) || '(人が消した行)'}<br>機: ${esc(w.hyp) || '(聞き逃し)'}</div>`).join('')}</details>`;
}
$('#accRefresh').addEventListener('click', loadAcc);
$('#accLegacy').addEventListener('change', loadAcc);

/* ---------- ホロライブの名簿 / 用語集の「認識に効く長さ」 ---------- */
const GLOSS_PROMPT = 150;   // serve.py の whisper_kwargs と揃える(initial_prompt に渡る文字数)
const glossTerms = t => [...new Set(String(t || '').split(/[\r\n,、]+/).map(x => x.trim()).filter(Boolean))];
function glossFit(terms){   // 先頭から何語がヒントに収まるか
  let n = 0, len = 0;
  for (const t of terms){ const add = (n ? 1 : 0) + t.length; if (len + add > GLOSS_PROMPT) break; len += add; n++; }
  return { fit: n, len: terms.join('、').length };
}
function renderGlossFit(){
  const t = glossTerms($('#optGloss').value), f = glossFit(t);
  $('#glossFit').textContent = !t.length ? '' : f.fit >= t.length ? `${t.length}語(認識のヒントに全部入ります)` : `${t.length}語のうち、認識のヒントに入るのは先頭の${f.fit}語まで(${GLOSS_PROMPT}字まで)。後ろの語は効きません。今回の動画に出る人だけに絞ってください`;
}
function rosterNames(ids){
  const seen = new Set(), out = [];
  for (const g of (S.roster && S.roster.groups) || []) if (ids.includes(g.id)) for (const n of g.names) if (!seen.has(n)){ seen.add(n); out.push(n); }
  return out;
}
async function loadRoster(){
  try { S.roster = await api('/api/roster'); } catch { S.roster = null; }
  const box = $('#rosterGroups'), r = S.roster;
  if (!r || !r.groups.length){ box.textContent = '名簿を読めません(hololive-roster.json が無いか壊れています)'; $('#rosterAdd').disabled = true; return; }
  box.innerHTML = r.groups.map(g => `<label class="lag" style="display:inline-block;margin:0 10px 3px 0"><input type="checkbox" class="rg" value="${esc(g.id)}">${esc(g.label)}(${g.names.length})</label>`).join('');
  $('#rosterNote').textContent = `${r.asOf} 時点`; $('#rosterBox').title = r.note;
}
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
function renderAbHint(){
  const n = S.doc ? S.doc.segments.filter(s => s.proofed && s.text.trim()).length : 0;
  const sec = S.doc ? S.doc.segments.filter(s => s.proofed && s.text.trim()).reduce((a, s) => a + (s.end - s.start), 0) : 0;
  $('#abHint').textContent = !S.doc ? '文字起こしを開いてください' : n ? `対象: 校正済み${Math.min(n, 300)}行(音声 約${sec < 90 ? Math.round(sec) + '秒' : Math.round(sec / 60) + '分'})` : '校正済みの行がありません';
  $('#abGo').disabled = !n;
}
function renderAb(){
  if (!S.tools) return;
  if (!abVariants){ const m = $('#optModel').value; abVariants = [{ model: m, glossary: true }, { model: m, glossary: false }]; }
  $('#abRows').innerHTML = abVariants.map((v, i) => `<div class="row" data-i="${i}" style="margin-top:4px;flex-wrap:nowrap">
    <select class="abm" style="min-width:0;flex:1" aria-label="モデル">${S.tools.models.map(([val, l]) => `<option value="${esc(val)}"${val === v.model ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>
    <label class="lag"><input type="checkbox" class="abg"${v.glossary ? ' checked' : ''}>用語集</label>${abVariants.length > 1 ? '<button type="button" class="btn small" data-act="abdel" aria-label="この設定を外す">×</button>' : ''}</div>
    ${v.glossary ? `<textarea class="abt" rows="2" style="width:100%;margin:2px 0 0" placeholder="空欄=上の共通の用語集を使う。書くと、この設定だけその語を使います(改行かカンマ区切り)" aria-label="この設定だけの用語集">${esc(v.terms || '')}</textarea>
    <div class="row" style="margin:2px 0 0"><select class="abr" aria-label="名簿から足す" style="min-width:0"><option value="">名簿から足す…</option>${((S.roster && S.roster.groups) || []).map(g => `<option value="${esc(g.id)}">${esc(g.label)}</option>`).join('')}</select><span class="hint">${(() => { const t = glossTerms(v.terms); if (!t.length) return ''; const f = glossFit(t); return f.fit >= t.length ? t.length + '語' : t.length + '語のうち先頭' + f.fit + '語だけ効きます'; })()}</span></div>` : ''}`).join('');
  $('#abAdd').disabled = abVariants.length >= 4;
  renderAbHint();
}
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
async function loadEvals(){
  const id = S.docId; if (!id) { $('#abOut').innerHTML = ''; return; }
  let r; try { r = await api('/api/evals?id=' + encodeURIComponent(id)); } catch { return; }
  if (S.docId !== id) return;
  $('#abOut').innerHTML = r.items.slice(0, 3).map(x => {
    const best = Math.min(...x.variants.map(v => v.cer == null ? Infinity : v.cer));
    return `<div class="abres"><div class="hint">${esc(new Date(x.at).toLocaleString())} ・ ${x.lines}行${x.device ? ' ・ ' + (x.device === 'cuda' ? 'GPU' : 'CPU') : ''}</div>
      <table class="acct"><tr><th>設定</th><th>CER</th><th>辞書後</th><th>置換/脱落/挿入</th><th>用語の誤挿入</th><th>用語ヒット</th></tr>
      ${x.variants.map(v => `<tr${v.cer === best ? ' class="best"' : ''}><td>${esc(v.label)}</td><td>${pct(v.cer)}</td><td>${pct(v.cerDict)}</td><td>${v.sub}/${v.del}/${v.ins}</td><td>${v.termExtra}</td><td>${v.termRef ? v.termHit + '/' + v.termRef : '—'}</td></tr>`).join('')}</table>
      <p class="hint" style="margin:3px 0 0">「辞書後」= 置換辞書を当てたあとのCER。「用語の誤挿入」= 正解に無いのに用語(用語集・辞書の正)が出た回数。</p>
      <details><summary class="hint">誤りが多い行</summary>${x.variants.map(v => `<div class="hint" style="margin-top:4px"><b>${esc(v.label)}</b></div>` + v.worst.slice(0, 5).map(w => `<div class="wl"><span class="mono">${fmtT(w.start)}</span> 正: ${esc(w.ref)}<br>機: ${esc(w.hyp) || '(認識なし)'}</div>`).join('')).join('')}</details></div>`;
  }).join('');
}

/* ---------- 保存データ(dataset/)への保管 ---------- */
const mb = n => n >= 1e9 ? (n / 1e9).toFixed(1) + 'GB' : Math.max(1, Math.round(n / 1e6)) + 'MB';
const minStr = sec => sec < 90 ? Math.round(sec) + '秒' : (sec / 3600 >= 1 ? (sec / 3600).toFixed(1) + '時間' : Math.round(sec / 60) + '分');
let arcPoll = null;
S.arcDirty = false;
async function loadDataset(){
  let r; try { r = await api('/api/dataset'); } catch { return; }
  S.arc = r; renderDataset();
  if (r.running && !arcPoll) arcPoll = setInterval(loadDataset, 2000);
  if (!r.running && arcPoll){ clearInterval(arcPoll); arcPoll = null; if (r.errors.length) toast('保管でエラー: ' + r.errors[0], 6000); }
}
function renderDataset(){
  const r = S.arc; if (!r) return;
  const t = r.totals, box = $('#arcOut');
  const cur = S.docId && r.docs.find(d => d.tid === S.docId);
  $('#arcStat').textContent = r.running ? `保管中 ${r.progress.done}/${r.progress.total}…` : (S.doc && S.doc.segments.some(g => g.proofed) ? (cur ? (cur.stale || S.arcDirty ? '保管: 更新あり' : '保管: 済') : '保管: まだ') : '');
  box.innerHTML = `<p class="accmain" style="margin:10px 0 0">正解の行 <b>${t.positive}</b>行 ・ 約${minStr(t.positiveSec)}</p>
    <p class="hint" style="margin:2px 0 0">人が消した行(負例) ${t.negative}行(約${minStr(t.negativeSec)}) ・ 聞き取れない ${t.unclear}行 ・ 保管した文字起こし ${t.docs}件 ・ 使用量 ${mb(t.audioBytes)}${t.stale ? ` ・ <b>更新あり ${t.stale}件</b>` : ''}</p>
    ${t.evalSec ? `<p class="hint" style="margin:2px 0 0">評価用(上の量には含めない) 約${minStr(t.evalSec)}。追加学習に使うときは、保管データの <b>split が eval</b> の行を必ず除いてください。</p>` : ''}
    <p class="hint" style="margin:2px 0 0">目安: 追加学習(LoRA)は、正解が<b>2〜3時間分</b>から。声紋登録は、話者1人あたり<b>数分〜十数分</b>から。</p>
    ${Object.keys(r.speakers).length ? '<details style="margin-top:6px"><summary class="hint">話者ごとの正解の量</summary>' + Object.entries(r.speakers).slice(0, 12).map(([k, v]) => `<div class="dsrow"><span>${esc(k)}</span><span>${minStr(v)}</span></div>`).join('') + '</details>' : ''}
    ${r.docs.length ? '<details style="margin-top:6px"><summary class="hint">文字起こしごと</summary>' + r.docs.map(d => `<div class="dsrow"><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(d.title || '無題')}${d.orphan ? '(元の文字起こしは削除済み)' : ''}</span><span>${d.positive}行 ・ ${mb(d.audioBytes)}${d.stale ? ' ・ 更新あり' : ''}${d.note ? ' ・ ' + esc(d.note) : ''}</span></div>`).join('') + '</details>' : ''}
    <p class="hint" style="margin:8px 0 0">保管先: このフォルダの <b>dataset/</b>(バックアップは、この中をコピーしてください)。話者の声・会話の内容が入るので、他人に渡す・クラウドに上げるときは、相手の同意と規約を確認してください。</p>`;
}
async function archiveNow(tid, quiet){
  if (!tid) return;
  try {
    await api('/api/archive', { body: { tid, full: $('#arcFull').checked } });
    S.arcDirty = false; loadDataset(); if (!quiet) toast('保管を始めました。音声の切り出しに、少し時間がかかります');
  } catch (e){ if (!quiet && e.code !== 'busy') toast(e.message); if (e.code === 'busy') S.arcDirty = true; }
}
function autoArchive(tid){ if ($('#arcAuto').checked && tid && S.arcDirty) archiveNow(tid, true); }
$('#arcNow').addEventListener('click', async () => { if (!S.docId) return toast('先に文字起こしを開いてください'); await saveDoc(); archiveNow(S.docId); });
$('#arcAll').addEventListener('click', async () => {
  await saveDoc();
  try { await api('/api/archive', { body: { full: $('#arcFull').checked } }); S.arcDirty = false; loadDataset(); toast('校正済みのある文字起こしを、すべて保管します'); } catch (e){ toast(e.message); }
});
setInterval(() => { if (S.docId && S.doc && !document.hidden) autoArchive(S.docId); }, 10 * 60 * 1000);
document.addEventListener('visibilitychange', () => { if (document.hidden && S.docId && S.doc){ (async () => { await saveDoc(); autoArchive(S.docId); })(); } });

/* ---------- 編集画面 ---------- */
const player = () => $('#player');
function spById(id){ return S.doc && S.doc.speakers.find(s => s.id === id); }
function markDirty(){
  S.dirty = true; setSaveState(S.conflict ? '競合しています' : '未保存…', S.conflict ? 'err' : '');
  clearTimeout(markDirty.t); markDirty.t = setTimeout(saveDoc, 700);
}
const hhmm = () => { const d = new Date(); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
/* 保存の状態の表示。kind: ''(未保存)/ 'busy'(保存中)/ 'ok'(保存済み)/ 'err'(競合・失敗)。色の印は CSS の [data-state] */
function setSaveState(text, kind){ const el = $('#saveState'); el.textContent = text; el.setAttribute('data-state', kind || ''); updateDocTitle(); }
let docSaveP = null, docOpenSeq = 0;
function saveDoc(){
  clearTimeout(markDirty.t);
  if (docSaveP) return docSaveP;   // 文書を切り替える側も、実行中の保存が終わるまで待つ
  if (S.conflict) return Promise.resolve(false);
  if (!S.doc || !S.dirty) return Promise.resolve(true);
  S.saving = true;
  const run = async () => {
    while (S.doc && S.dirty){   // 保存を待っている間に編集された分も、順番に保存する
      S.dirty = false; setSaveState('保存中…', 'busy');
      const id = S.docId, force = S.forceNext;
      const body = { title: S.doc.title, evalSet: S.doc.evalSet === true, speakers: S.doc.speakers, segments: S.doc.segments, baseUpdatedAt: S.baseUpdatedAt, ...(force ? { force: true } : {}) };
      const count = body.segments.length;
      try {
        const r = await api('/api/transcript?id=' + encodeURIComponent(id), { method: 'PUT', body });
        if (S.docId !== id) return false;
        S.baseUpdatedAt = r.updatedAt; S.forceNext = false;
        if (S.dirty) setSaveState('未保存…', ''); else setSaveState('保存しました ' + hhmm(), 'ok');
        scheduleLearn(); scheduleAcc(); scheduleProgress(); S.arcDirty = true; renderDataset();
        const it = S.list.find(x => x.id === id); if (it){ it.title = body.title; it.segments = count; }
      } catch (e){
        if (S.docId !== id) return false;   // 保存を待つ間に文書が閉じられた(削除など)。閉じた文書の「未保存」を残さない
        S.dirty = true;
        if (e.code === 'conflict'){ S.conflict = true; $('#conflictBar').hidden = false; setSaveState('競合しています', 'err'); toast('別の場所で先に更新されています。映像の上の案内から選んでください', 6000, 'err'); }
        else { setSaveState('保存できません(5秒後にもう一度試します)', 'err'); toast('保存に失敗: ' + e.message, 3800, 'err'); clearTimeout(markDirty.t); markDirty.t = setTimeout(saveDoc, 5000); }
        return false;
      }
    }
    return !S.conflict;
  };
  docSaveP = run().finally(() => { S.saving = false; docSaveP = null; });
  return docSaveP;
}
$('#cfReload').addEventListener('click', async () => {
  clearTimeout(markDirty.t); S.dirty = false; S.conflict = false; S.forceNext = false; await openDoc(S.docId, true); toast('保存済みの内容を読み込みました');
});
$('#cfForce').addEventListener('click', e => armDelete(e.currentTarget, () => {
  S.conflict = false; S.forceNext = true; $('#conflictBar').hidden = true; S.dirty = true; saveDoc();
}));
document.addEventListener('visibilitychange', () => { if (document.hidden && S.dirty && !S.conflict){ clearTimeout(markDirty.t); saveDoc(); } });   // タブを離れるとき・画面を閉じるときに、待たずに保存する
async function openDoc(id, keep){
  const request = ++docOpenSeq;
  if (!(await saveDoc()) || request !== docOpenSeq) return false;
  const previousDoc = S.doc, previousVersion = S.baseUpdatedAt;
  if (!keep && S.docId && S.docId !== id) autoArchive(S.docId);   // 別の文字起こしに移るときに、それまでの分を保管する
  const navId = keep ? navSnapshot() : null;   // keep=true(再認識・話者判別が終わっての読み直しなど)は、見ていた行を id で覚えておく
  const scrollY = window.scrollY;
  let d; try { d = await api('/api/transcript?id=' + encodeURIComponent(id)); } catch (e){ toast(e.message); return false; }
  if (request !== docOpenSeq) return false;
  if (S.doc !== previousDoc || S.dirty || S.saving || S.conflict || S.baseUpdatedAt !== previousVersion){
    toast('読み込み中に編集されたため、現在の内容を保持しました。もう一度開いてください'); return false;
  }
  S.doc = d; S.docId = id; S.undo = []; S.sug = []; S.sel = new Set(); S.curIdx = -1; S.dirty = false; S.conflict = false; S.forceNext = false; S.baseUpdatedAt = d.updatedAt || null; $('#conflictBar').hidden = true;
  if (!keep) S.navIdx = -1; else navRestore(navId, S.navIdx);
  const pos = keep ? null : loadPos(id), resumeIdx = pos ? d.segments.findIndex(x => x.id === pos.id) : -1;
  $('#noDoc').hidden = true; $('#doc').hidden = false;
  let autoClosed = false;   // 画面が狭いとき(メニューを開いたままだと一覧が細くなる)は、文字起こしを開いた時点でメニューを閉じる
  if (!keep && V.menu && $('.editor').clientWidth < 1000){ toggleMenu(false); autoClosed = true; }
  $('.app').classList.add('has-doc');   // 文字起こしを開いている間は、メニューを少し細く(GPT 版)
  $('#docTitle').value = d.title || ''; setSaveState('', ''); syncEval(); renderDocExtras(d);
  { const pr = d.params || {}; $('#docInfo').textContent = `認識の設定: ${String(d.model || '').split('/').pop()}${pr.device ? ' / ' + (pr.device === 'cuda' ? 'GPU' : 'CPU') : ''} / ${{ weak: '声の検出: 弱め', normal: '声の検出: 標準', off: '声の検出: なし' }[pr.vadMode] || (pr.vad === false ? '声の検出: なし' : '声の検出: 標準')}${pr.boost ? ' / 音量補正あり' : ''}${pr.beam === 1 ? ' / 速度優先' : ''}${d.diarization ? ' / 話者判別: ' + d.diarization.found + '人(' + (d.diarization.requested ? '指定' + d.diarization.requested + '人' : '人数は自動') + ', ' + ({ voxceleb: 'VoxCeleb', campplus: 'CAM++', standard: 'ERes2Net' }[d.diarization.embedding] || 'ERes2Net') + ')' : ''}${pr.dictApplied ? ' / 辞書を自動適用(' + pr.dictApplied + '箇所)' : ''}${pr.learnApplied ? ' / 学習済みの置換を自動適用(' + pr.learnApplied + '箇所)' : ''}${(pr.glossAuto || []).length ? ' / 用語を自動追加: ' + pr.glossAuto.slice(0, 5).join('、') + (pr.glossAuto.length > 5 ? ' ほか' : '') : ''}${d.retranscribed ? ' / 再認識: ' + String(d.retranscribed.model).split('/').pop() + '(' + d.retranscribed.lines + '行)' : ''}`; }
  $('#playerMsg').hidden = true;
  const p = player();
  if (!keep){   // 話者判別のあとの読み直しでは、再生位置をそのままにする
    /* 読み込みに失敗した動画の loadedmetadata は来ないので、前の文書の待ち受けが残っていると、次に開いた文書の動画で
       前の文書の位置へ飛んでしまう。開くたびに番号を振り、最新の文書の待ち受けだけが働くようにする */
    const mediaSeq = S.mediaSeq = (S.mediaSeq || 0) + 1;
    p.addEventListener('loadedmetadata', () => { if (mediaSeq !== S.mediaSeq) return; p.playbackRate = Number(V.rate); if (resumeIdx >= 0) p.currentTime = d.segments[resumeIdx].start; else if (!d.whole && d.start > 0) p.currentTime = d.start; }, { once: true });
    p.src = apiUrl('/media?id=' + encodeURIComponent(id));
    $('#q').value = ''; $('#flagKind').value = '';
  }
  renderDoc(); renderList(); updateUndo(); applyLock(); loadSuggest(); renderAb(); loadEvals(); renderTerms(); renderDataset(); $('#hiList').innerHTML = '';
  if (keep) window.scrollTo(0, scrollY);
  else if (resumeIdx >= 0){ setNav(resumeIdx); const row = rowsEl()[resumeIdx]; if (row) row.scrollIntoView({ block: 'center' }); toast(`前回の続き(${fmtT(d.segments[resumeIdx].start)} の行)に移動しました。先頭から見るには、上へスクロールしてください`, 5000); }
  else window.scrollTo(0, 0);
  if (autoClosed && resumeIdx < 0) toast('編集欄を広くするため、メニューを閉じました(左上の ☰ で開けます)', 4000);
  return true;
}
function opts(sel){ return '<option value="">話者なし</option>' + S.doc.speakers.map(s => `<option value="${esc(s.id)}"${s.id === sel ? ' selected' : ''}>${esc(s.name)}</option>`).join(''); }
const TAG_LABEL = { unclear: '聞き取れない', overlap: '声が重なる', bgm: 'BGM・音が大きい' }, TAG_KEY = { unclear: 'X', overlap: 'C', bgm: 'V' };
const tagsHTML = s => Object.keys(TAG_LABEL).map(t => `<button type="button" data-act="tag" data-t="${t}" aria-pressed="${(s.tags || []).includes(t) ? 'true' : 'false'}" title="この行の音の状態のメモ(${TAG_KEY[t]})。「聞き取れない」の行は、精度の測定と学習の正解に使いません">${TAG_LABEL[t]}</button>`).join('');
/* 前後の行と時刻が重なっているか(書き出すと字幕が2段で出るので、時刻の欄を赤くして知らせる) */
function ovl(i){ const g = S.doc.segments, s = g[i], a = g[i - 1], b = g[i + 1]; return !!s && ((a && s.start < a.end - 0.01) || (b && s.end > b.start + 0.01)); }
function markOvl(i){ for (const j of [i - 1, i, i + 1]){ const r = rowsEl()[j]; if (r && r.classList && r.classList.contains('seg')){ const t = r.querySelector('.times'); const o = ovl(j); t.classList.toggle('ovl', o); if (o) t.title = '前後の行と時刻が重なっています(字幕が2段に重なって出ます)'; else t.removeAttribute('title'); } } }
function segHTML(s, i){
  const c = spColor(spById(s.speaker)), cut = s.cutState === 'cut', ov = ovl(i);
  return `<div class="seg${s.flag ? ' flag' : ''}${s.proofed ? ' proofed' : ''}${(s.tags || []).length ? ' tagged' : ''}${cut ? ' cut' : ''}" data-i="${i}"${c ? ` style="--sp:${c}"` : ''}>
    <input type="checkbox" class="sel" ${S.sel.has(s.id) ? 'checked' : ''} aria-label="この行を選択">
    <button type="button" class="play" data-act="play" title="この行だけ再生(R)。行の終わりで止まります" aria-label="この行だけ再生">▶</button>
    <div class="times${ov ? ' ovl' : ''}"${ov ? ' title="前後の行と時刻が重なっています(字幕が2段に重なって出ます)"' : ''}><input class="t" data-f="start" value="${fmtT(s.start, true)}" aria-label="開始"><span>–</span><input class="t" data-f="end" value="${fmtT(s.end, true)}" aria-label="終了"></div>
    <select class="spk" data-f="speaker" aria-label="話者">${opts(s.speaker)}</select>
    <textarea data-f="text" rows="1" spellcheck="false" aria-label="文字" placeholder="(空の行)文字を入力。不要なら「削除」">${esc(s.text)}</textarea>
    <span class="ops"><button type="button" class="cut-toggle" data-act="cut" aria-pressed="${cut ? 'true' : 'false'}" title="Resolveの仮編集から外します(カット済)。元素材は残るため、あとで「残す」に戻せます">${cut ? 'カット済' : '残す'}</button><button type="button" class="pf" data-act="proof" aria-pressed="${s.proofed ? 'true' : 'false'}" title="聞いて確認して、この行の文字が正しいと判断したら押す(Shift+Space。次の行へ進みます)">校正済み</button></span>
    <div class="sug">${sugHTML(s)}</div>
    <div class="tg">${tagsHTML(s)}</div>
    <div class="adj" aria-label="この行の操作"><span class="g" title="幅はツールの「⚙設定」の「時刻の微調整の幅」。数字を直接書き換えてもかまいません">開始<button type="button" data-act="adj" data-f="start" data-d="-1" title="開始を早める">−</button><button type="button" data-act="adj" data-f="start" data-d="1" title="開始を遅らせる">＋</button><button type="button" class="now" data-act="setnow" data-f="start" title="開始を、いまの再生位置にする">再生位置</button></span><span class="g">終了<button type="button" data-act="adj" data-f="end" data-d="-1" title="終了を早める">−</button><button type="button" data-act="adj" data-f="end" data-d="1" title="終了を遅らせる">＋</button><button type="button" class="now" data-act="setnow" data-f="end" title="終了を、いまの再生位置にする">再生位置</button></span><span class="sep" aria-hidden="true"></span><span class="g rowops" aria-label="行の操作"><button type="button" data-act="addb" title="この行の前に、空の行を足します(認識で抜けたセリフを書き足すとき)">＋前に行</button><button type="button" data-act="adda" title="この行の後に、空の行を足します(N)">＋後に行</button><button type="button" data-act="split" title="カーソル位置(なければ再生位置)で2つに分けます">分割</button><button type="button" data-act="merge" title="次の行とつなげて1行にします">次と結合</button><button type="button" data-act="del" class="del" title="この行を消します(2回押し。Z でも消せます)">削除</button></span></div>
    ${s.flag ? `<button type="button" class="fl" data-act="unflag" title="${esc(s.flag)}(押すと確認済みにします)">要確認: ${esc(s.flag)}</button>` : ''}
  </div>`;
}
function renderDoc(){
  const segs = S.doc.segments;
  $('#segs').innerHTML = segs.length ? segs.map(segHTML).join('') : '<div class="empty">文字が認識されませんでした(音声がない、または小さすぎる可能性があります)<div style="margin-top:10px"><button type="button" class="btn small" data-act="addfirst">＋行を追加(再生位置に)</button></div></div>';
  autoSizeAll(true);
  S.curIdx = -1;   // 描き直すと「再生中」の印(.cur)も消えるので、次の timeupdate で付け直す
  if (S.navIdx >= segs.length) S.navIdx = segs.length - 1;
  { const r = rowsEl()[S.navIdx]; if (S.navIdx >= 0 && r && r.classList && r.classList.contains('seg')) r.classList.add('nav'); }
  renderSpeakers(); applyFilter(); updateSel(); updatePfStat();
}
/* 行の高さ: 対応ブラウザは CSS(field-sizing)にまかせる。それ以外は、画面の近くにある行だけを測る(数千行でも重くならないように) */
const NATIVE_FS = !/[?&]nofs=1/.test(location.search) && !!(window.CSS && CSS.supports && CSS.supports('field-sizing', 'content'));
if (NATIVE_FS) document.documentElement.classList.add('fsz');
const visRows = new Set();
const rowIO = !NATIVE_FS && 'IntersectionObserver' in window ? new IntersectionObserver(ents => {
  const add = [];
  for (const en of ents){ if (en.isIntersecting){ visRows.add(en.target); add.push(en.target); } else visRows.delete(en.target); }
  if (add.length) autoSizeList(add.map(r => r.querySelector('textarea')).filter(Boolean));
}, { rootMargin: '800px 0px' }) : null;
function autoSize(ta){ if (NATIVE_FS) return; ta.style.height = 'auto'; ta.style.height = (ta.scrollHeight + 2) + 'px'; }
function autoSizeAll(fresh){
  if (NATIVE_FS) return;
  if (!rowIO) return autoSizeList([...document.querySelectorAll('#segs .seg:not([hidden]) textarea')]);
  if (fresh){ visRows.clear(); rowIO.disconnect(); for (const r of rowsEl()) if (r.classList && r.classList.contains('seg')) rowIO.observe(r); }
  else autoSizeList([...visRows].filter(r => !r.hidden).map(r => r.querySelector('textarea')).filter(Boolean));
}
function autoSizeList(tas){   // まとめて縮める → まとめて測る → まとめて設定(レイアウト計算を1回にする)
  for (const t of tas) t.style.height = 'auto';
  const hs = tas.map(t => t.scrollHeight);
  tas.forEach((t, i) => { if (hs[i] > 0) t.style.height = (hs[i] + 2) + 'px'; });
}
let sizeT = null;
function autoSizeSoon(){ clearTimeout(sizeT); sizeT = setTimeout(() => { if (S.doc) autoSizeAll(); drawStripSoon(); }, 200); }
window.addEventListener('resize', autoSizeSoon);
if (window.ResizeObserver){
  new ResizeObserver(() => { document.documentElement.style.setProperty('--pbh', $('.pbox').offsetHeight + 'px'); }).observe($('.pbox'));
  new ResizeObserver(() => { document.documentElement.style.setProperty('--toph', $('.top').offsetHeight + 'px'); }).observe($('.top'));
  new ResizeObserver(drawStripSoon).observe($('#stripBox'));
}
function applyFilter(){
  const q = norm($('#q').value.trim()), only = $('#flagKind').value;
  let n = 0; const shown = [];
  document.querySelectorAll('#segs .seg').forEach(el => {
    const s = S.doc.segments[Number(el.dataset.i)]; if (!s) return;
    const hit = (!q || norm(s.text).includes(q)) && (!only || flagMatch(s, only));
    if (hit && el.hidden){ const ta = el.querySelector('textarea'); if (ta) shown.push(ta); }
    el.hidden = !hit; if (hit) n++;
  });
  if (shown.length && !NATIVE_FS && !rowIO) autoSizeList(shown);   // 隠れていた行は、表示するときに高さを測り直す
  $('#qCount').textContent = (q || only) ? `${n}行が該当` : `${S.doc.segments.length}行`;
}
function renderSpeakers(){
  const box = $('#spList');
  box.innerHTML = S.doc.speakers.map((s, i) => `<div class="sp-row" data-i="${i}"><input type="color" value="${esc(/^#[0-9a-fA-F]{6}$/.test(s.color) ? s.color : '#888888')}" aria-label="色"><input type="text" value="${esc(s.name)}" maxlength="30" aria-label="話者名" style="flex:1"><span class="n">${S.doc.segments.filter(x => x.speaker === s.id).length}行 ・ ${i + 1}</span><button type="button" class="btn small" data-act="spplay" title="この人の発言を順に再生">▶ 聞く</button><button type="button" class="btn small danger" data-act="spdel">削除</button></div>`).join('');
  const cur = $('#spBulk').value;
  $('#spBulk').innerHTML = opts(cur);
}
function pushUndo(){
  S.undo.push(JSON.stringify({ speakers: S.doc.speakers, segments: S.doc.segments, sug: S.sug })); if (S.undo.length > 30) S.undo.shift(); updateUndo();
}
function updateUndo(){ $('#btnUndo').disabled = !S.undo.length; $('#btnUndo').textContent = S.undo.length ? `元に戻す(${S.undo.length})` : '元に戻す'; }
function doUndo(){
  if (!S.undo.length) return;
  const navId = navSnapshot();
  const d = JSON.parse(S.undo.pop()); S.doc.speakers = d.speakers; S.doc.segments = d.segments; S.sel.clear(); if (d.sug) S.sug = d.sug;
  navRestore(navId, S.navIdx);
  renderDoc(); renderChips(); updateUndo(); markDirty();
}
/* 開始/終了を、いまの再生位置にする(足した行の時刻を、聞きながら合わせるとき) */
function setTimeNow(s, f){
  const v = Math.round(player().currentTime * 100) / 100;
  if (f === 'start' ? !(v < s.end) : !(v > s.start)) return toast(f === 'start' ? '再生位置が、この行の終了より後です(先に終了を合わせてください)' : '再生位置が、この行の開始より前です', 2500);
  pushUndo(); s[f] = v; const id = s.id; sortSegs(); S.navIdx = S.doc.segments.findIndex(x => x.id === id); renderDoc(); markDirty();
  toast((f === 'start' ? '開始' : '終了') + 'を ' + fmtT(v, true) + ' にしました', 1500);
}
function nudge(s, row, f, dir){
  const step = Number(V.adjStep) || 0.1, MIN = 0.1;
  let v = Math.round((s[f] + dir * step) * 100) / 100;
  if (f === 'start') v = Math.min(Math.max(0, v), Math.round((s.end - MIN) * 100) / 100); else v = Math.max(v, Math.round((s.start + MIN) * 100) / 100);
  if (v === s[f]) return toast(f === 'start' ? (dir < 0 ? 'これより早くできません(0秒)' : '開始は、終了より0.1秒以上前にしてください') : '終了は、開始より0.1秒以上後にしてください', 1500);
  pushUndo(); s[f] = v; markDirty();
  const inp = row.querySelector(`input[data-f="${f}"]`); if (inp) inp.value = fmtT(v, true);
  const segs = S.doc.segments, i = segs.indexOf(s); markOvl(i);
  if ((segs[i - 1] && segs[i - 1].start > s.start) || (segs[i + 1] && segs[i + 1].start < s.start)){   // 並び順が変わるときだけ、並べ直す
    sortSegs(); const ni = segs.indexOf(s); renderDoc(); setNav(ni);
  }
  if (S.playEnd !== null || player().paused){ const p = player(); p.currentTime = f === 'end' ? Math.max(s.start, s.end - 1.2) : s.start; S.playEnd = s.end; p.play().catch(() => {}); }   // 動かした端を、すぐ聞き直せるように
}
function sortSegs(){ S.doc.segments.sort((a, b) => a.start - b.start); }   // v0.9.8: 開始が同じ行は、今の並びのまま(安定ソート)。終了で並べ替えると、足した行が意図と違う位置に動くため
function updateSel(){
  const n = S.sel.size; $('#selCount').textContent = n ? `${n}行を選択中` : '';
  $('#selAll').checked = n > 0 && n === S.doc.segments.length;
  updateRt(); $('#btnProofSel').disabled = !n;
}

$('#segs').addEventListener('input', e => {
  const row = e.target.closest('.seg'); if (!row) return;
  const s = S.doc.segments[Number(row.dataset.i)]; if (!s) return;
  if (e.target.dataset.f === 'text'){ s.text = e.target.value.slice(0, 2000); autoSize(e.target); markDirty(); const bx = row.querySelector('.sug'); if (bx && (bx.children.length || S.sug.some(x => x.seg === s.id))) bx.innerHTML = sugHTML(s); }
});
$('#segs').addEventListener('change', e => {
  const row = e.target.closest('.seg'); if (!row) return;
  const i = Number(row.dataset.i), s = S.doc.segments[i]; if (!s) return;
  const f = e.target.dataset.f;
  if (e.target.classList.contains('sel')){ e.target.checked ? S.sel.add(s.id) : S.sel.delete(s.id); updateSel(); return; }
  if (f === 'speaker'){ pushUndo(); s.speaker = e.target.value; setRowSp(row, spById(s.speaker)); markDirty(); }
  else if (f === 'start' || f === 'end'){
    const v = parseT(e.target.value);
    const ok = Number.isFinite(v) && (f === 'start' ? v < s.end : v > s.start);
    if (!ok){ toast('時刻が正しくありません(開始は終了より前、例 1:23.5)'); e.target.value = fmtT(s[f], true); return; }
    /* 時刻で並びが変わると、今の行(S.navIdx)の添字がずれる。直した行を id で探し直して、今の行にする */
    pushUndo(); s[f] = Math.round(v * 100) / 100; sortSegs(); S.navIdx = S.doc.segments.indexOf(s); renderDoc(); markDirty();
    rowsEl()[S.navIdx]?.querySelector('textarea')?.focus({ preventScroll: true });
  }
});
$('#btnAddAt').addEventListener('click', () => { if (S.doc) insertAtTime(player().currentTime || 0); });
$('#segs').addEventListener('click', e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  if (b.dataset.act === 'addfirst'){ if (!lockJob()) insertAtTime(player().currentTime || 0); return; }
  const row = b.closest('.seg'), i = Number(row.dataset.i), segs = S.doc.segments, s = segs[i]; if (!s) return;
  if (S.navIdx !== i){ setNav(i); savePos(); }   // 押したボタンの行を「今の行」にする(mousedown ではフォーカスを移さないため、ここで)
  switch (b.dataset.act){
    case 'cut':
      pushUndo();
      if (s.cutState === 'cut') delete s.cutState; else s.cutState = 'cut';
      row.classList.toggle('cut', s.cutState === 'cut');
      b.setAttribute('aria-pressed', s.cutState === 'cut' ? 'true' : 'false');
      b.textContent = s.cutState === 'cut' ? 'カット済' : '残す';
      markDirty();
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
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && e.target.matches('textarea')){
    e.preventDefault(); const s = S.doc.segments[Number(e.target.closest('.seg').dataset.i)]; if (s) playSeg(s, true);
  }
});
/* ---------- 行の移動(キーボードで校正を回す) ---------- */
const rowsEl = () => $('#segs').children;
const rowIdxOf = el => { const r = el && el.closest && el.closest('.seg'); return r ? Number(r.dataset.i) : -1; };
function curNav(){ const a = rowIdxOf(document.activeElement); return a >= 0 ? a : (S.navIdx >= 0 ? S.navIdx : S.curIdx); }
/* v0.9.6: 行の分割・削除・結合・元に戻す・再読み込みで一覧の並びや行数が変わっても、キーボードの「今の行」(S.navIdx)が
   同じ行を指し続けるようにする(そうしないと、直前に見ていた行と違う行にShiftキー操作が効いてしまう)。
   変更の直前に navSnapshot() で行の id を覚え、直後に navRestore() でその id の新しい位置を探し直す
   (その行自体が無くなっていれば、fallbackIdx で渡した位置に近い行のままにする)。 */
function navSnapshot(){ return S.navIdx >= 0 && S.doc.segments[S.navIdx] ? S.doc.segments[S.navIdx].id : null; }
function navRestore(id, fallbackIdx){
  if (id == null || !S.doc) return;
  const ni = S.doc.segments.findIndex(x => x.id === id);
  S.navIdx = ni >= 0 ? ni : Math.max(-1, Math.min(fallbackIdx, S.doc.segments.length - 1));
}
const posKey = id => 'tx.pos.' + id;
function savePos(){ if (!S.doc || S.navIdx < 0) return; const g = S.doc.segments[S.navIdx]; if (g){ try { localStorage.setItem(posKey(S.docId), JSON.stringify({ id: g.id, t: g.start })); } catch {} } }
function loadPos(id){ try { const o = JSON.parse(localStorage.getItem(posKey(id)) || 'null'); return o && typeof o.id === 'string' ? o : null; } catch { return null; } }
/* 行が見える範囲(固定の再生欄の下〜画面の下)に収まっていれば動かさない。外れるときだけ、一定の位置(上から35%)に、なめらかに寄せる */
function ensureVisible(row, at){
  if (!row || row.hidden) return;
  const top = parseFloat(getComputedStyle(row).scrollMarginTop) || 0, bot = window.innerHeight - 24, r = row.getBoundingClientRect();
  if (r.top >= top && r.bottom <= bot) return;
  const goal = top + Math.max(0, (bot - top - Math.min(r.height, bot - top)) * (at === undefined ? 0.35 : at));
  const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollBy({ top: r.top - goal, behavior: reduce ? 'auto' : 'smooth' });
}
function setNav(i){
  const rows = rowsEl(); if (S.navIdx >= 0 && rows[S.navIdx] && rows[S.navIdx].classList) rows[S.navIdx].classList.remove('nav');
  const was = S.navIdx; S.navIdx = i; if (i >= 0 && rows[i] && rows[i].classList) rows[i].classList.add('nav');
  if (was >= 0 && was !== i && rows[was] && rows[was].classList){ const w = rows[was]; w.classList.remove('was'); void w.offsetWidth; w.classList.add('was'); setTimeout(() => w.classList.remove('was'), 1500); }
}
function gotoRow(i, opt = {}){
  const row = rowsEl()[i]; if (!row || !row.classList.contains('seg') || row.hidden) return false;
  setNav(i);
  if (opt.edit){ const ta = row.querySelector('textarea'); if (ta) ta.focus({ preventScroll: true }); }
  else if (document.activeElement && document.activeElement.closest && document.activeElement.closest('#segs') && isTextEntry(document.activeElement)) document.activeElement.blur();
  ensureVisible(row, opt.center ? 0.5 : 0.35);
  savePos();
  if (opt.play) playSeg(S.doc.segments[i], true);
  return true;
}
function findRow(from, dir, pred){
  const segs = S.doc.segments, rows = rowsEl();
  for (let i = from + dir; i >= 0 && i < segs.length; i += dir){ if (!rows[i] || rows[i].hidden) continue; if (!pred || pred(segs[i])) return i; }
  return -1;
}
function navigate(kind, dir){
  if (!S.doc || lockJob()) return;
  const pred = kind === 'unproofed' ? g => !g.proofed && g.text.trim() : kind === 'flag' ? g => !!g.flag : null;
  const from = curNav(), i = findRow(from < 0 && dir > 0 ? -1 : from, dir, pred);
  if (i < 0) return toast({ unproofed: dir > 0 ? 'これより後に、未校正の行はありません' : 'これより前に、未校正の行はありません', flag: '該当する「要確認」の行はありません' }[kind] || (dir > 0 ? '最後の行です' : '最初の行です'));
  gotoRow(i, { play: V.autoNext, center: !!kind });
}
function replayCur(){ const i = curNav(), g = S.doc && S.doc.segments[i]; if (g) playSeg(g, true); }
function seek(d){ const p = player(); p.currentTime = Math.max(0, p.currentTime + d); S.playEnd = null; }
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
$('#segs').addEventListener('focusin', e => { if (e.target.classList.contains('sel')) return; const i = rowIdxOf(e.target); if (i >= 0){ setNav(i); savePos(); } });
$('#btnNextUn').addEventListener('click', () => navigate('unproofed', 1));
$('#seekBack').addEventListener('click', () => seek(-3));
$('#seekFwd').addEventListener('click', () => seek(3));
const isTextEntry = t => !!(t && t.matches && (t.matches('textarea,select,[contenteditable=""],[contenteditable=true]') || (t.matches('input') && !/^(checkbox|radio|button|submit|range|color|file)$/i.test(t.type))));
function toggleTag(s, t, row){
  const a = new Set(s.tags || []); if (a.has(t)) a.delete(t); else a.add(t);
  s.tags = Object.keys(TAG_LABEL).filter(k => a.has(k)); if (!s.tags.length) delete s.tags;
  if (row){ row.classList.toggle('tagged', !!s.tags); row.querySelector('.tg').innerHTML = tagsHTML(s); }
  markDirty();
}
function rowAndSeg(){ const i = curNav(), row = i >= 0 ? rowsEl()[i] : null, g = i >= 0 && S.doc.segments[i]; return g && row && row.classList && row.classList.contains('seg') ? { i, row, g } : null; }
function proofOk(){   // 校正済みにして、次の行へ(すでに校正済みなら、次へ進むだけ)
  const c = rowAndSeg(); if (!c) return toast('先に、行を選んでください(S で最初の行へ)');
  if (!c.g.proofed){ setProof(c.g, true, c.row); markDirty(); updatePfStat(); }
  const ni = findRow(c.i, 1); if (ni >= 0) gotoRow(ni, { play: V.autoNext }); else toast('最後の行です(表示している行は、すべて確認しました)');
}
let zArm = null;
function deleteCur(){
  const c = rowAndSeg(); if (!c) return;
  /* v0.9.8: 1文字キーになったので、Z は2回押し(1.5秒以内)で削除する(行のボタンの「削除」と同じ考え方) */
  if (!zArm || zArm.id !== c.g.id || Date.now() - zArm.t > 1500){ zArm = { id: c.g.id, t: Date.now() }; return toast('もう一度 Z で、この行を削除します', 1500); }
  zArm = null;
  pushUndo(); S.sel.delete(c.g.id); S.doc.segments.splice(c.i, 1); S.navIdx = Math.min(c.i, S.doc.segments.length - 1);
  renderDoc(); markDirty(); toast('行を削除しました(Ctrl+Z で元に戻せます)');
  if (V.autoNext && S.navIdx >= 0) playSeg(S.doc.segments[S.navIdx], true);
}
function assignSpeaker(n){
  const c = rowAndSeg(); if (!c || (n && !S.doc.speakers[n - 1])) return;
  pushUndo(); c.g.speaker = n === 0 ? '' : S.doc.speakers[n - 1].id;
  c.row.querySelector('.spk').value = c.g.speaker; setRowSp(c.row, spById(c.g.speaker));
  markDirty(); renderSpeakers();
}
function editCur(){ const c = rowAndSeg(); if (c){ const ta = c.row.querySelector('textarea'); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } }
/* 左手だけの操作: キー単体(Shift 不要)。文字を入力しているとき(入力欄にカーソルがあるとき)は使えません(Esc で抜けます)。
   例外は Space だけ: Space 単体はすでに動画の再生・停止に使っているので、「校正済みにして次へ」は Shift+Space のまま残す */
const CMD_KEYS = {
  KeyQ: () => seek(-3), KeyE: () => seek(3), KeyW: () => navigate(null, -1), KeyS: () => navigate(null, 1), KeyR: replayCur,
  KeyA: () => navigate('unproofed', -1), KeyD: () => navigate('unproofed', 1), KeyF: () => navigate('flag', 1),
  KeyZ: deleteCur, KeyX: () => { const c = rowAndSeg(); if (c) toggleTag(c.g, 'unclear', c.row); }, KeyC: () => { const c = rowAndSeg(); if (c) toggleTag(c.g, 'overlap', c.row); },
  KeyV: () => { const c = rowAndSeg(); if (c) toggleTag(c.g, 'bgm', c.row); },
  KeyN: () => { const c = rowAndSeg(); if (c) insertAfter(c.i); else insertAtTime(player().currentTime); },
  KeyT: editCur, KeyB: () => { V.autoNext = !V.autoNext; saveView(); applyView(); toast('移動したら自動で再生: ' + (V.autoNext ? 'オン' : 'オフ'), 1500); },
};
/* 押しっぱなし(キーの自動の繰り返し)で続けて働いてよいのは、移動とシークだけ。
   それ以外(特に Z の2回押しの削除・Shift+Space の校正済み)は、押しっぱなしで「2回目」や「聞かずに校正済み」にならないように、繰り返しを無視する */
const REPEAT_OK = new Set(['KeyW', 'KeyS', 'KeyA', 'KeyD', 'KeyF', 'KeyQ', 'KeyE']);
window.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || document.querySelector('dialog[open]') || isTextEntry(e.target)) return;
  const c = e.code;
  if (c === 'Space' && e.shiftKey){ if (!S.doc || lockJob()) return; e.preventDefault(); if (!e.repeat) proofOk(); return; }   // Space だけは例外で Shift+Space のまま
  if (e.shiftKey) return;   // Space 以外は Shift を押していたら何もしない(単体キーで動くので、誤って押しても発動しないように)
  if (c === 'KeyG'){ e.preventDefault(); if (!e.repeat) toggleMenu(); return; }
  if (!S.doc || lockJob()) return;
  const dm = /^Digit([0-9])$/.exec(c);
  if (dm){ e.preventDefault(); if (!e.repeat) assignSpeaker(Number(dm[1])); return; }
  if (CMD_KEYS[c]){ e.preventDefault(); if (!e.repeat || REPEAT_OK.has(c)) CMD_KEYS[c](); }
});

/* Esc: 編集画面のどの入力欄(検索・絞り込み・速さ・タイトル・行の時刻や話者)からでも抜けて、操作キーを使えるようにする
   (以前は行の文字の欄だけだったので、検索や速さを変えたあとに S や D が効かず「取りこぼし」に見えた)。日本語の変換中は変換の取り消しにだけ使う */
window.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || e.isComposing || e.keyCode === 229 || document.querySelector('dialog[open]')) return;
  const t = e.target;
  if (isTextEntry(t) && t.closest && t.closest('#doc')) t.blur();
});
/* Tab: 入力欄の中 → 抜ける(コマンドモード) / 行を選んでいて入力欄の外 → その行の入力欄に入る。日本語変換中・Shift+Tab・ダイアログ中は、ふつうの動き */
window.addEventListener('keydown', e => {
  if (e.key !== 'Tab' || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.keyCode === 229 || !S.doc || document.querySelector('dialog[open]')) return;
  const t = e.target;
  if (t.matches && t.matches('#segs textarea')){ e.preventDefault(); t.blur(); return; }
  const free = t === document.body || t === document.documentElement || (t.matches && t.matches('video')) || (t.closest && t.closest('#segs') && !isTextEntry(t) && !t.matches('button,a'));
  if (free && !lockJob() && rowAndSeg()){ e.preventDefault(); editCur(); }
});

/* ---------- 用語のワンクリック挿入 ---------- */
function renderTerms(){
  const box = $('#terms'), ts = String(S.settings.glossary || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean).slice(0, 16);
  box.hidden = !ts.length || !S.doc;
  box.innerHTML = ts.length ? '<span class="hint" title="行をクリックしてから押すと、カーソル位置に入ります。文字を選んでいれば、その文字を置き換えます">用語:</span>' + ts.map(t => `<button type="button" class="chip" data-t="${esc(t)}">${esc(t)}</button>`).join('') : '';
}
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
async function loadHistory(){
  const id = S.docId; if (!id) return;
  let r; try { r = await api('/api/history?id=' + encodeURIComponent(id)); } catch (e){ return toast(e.message); }
  if (S.docId !== id) return;
  $('#hiList').innerHTML = r.items.length ? r.items.map(x => `<div class="row" data-ts="${x.ts}" style="margin-top:4px;justify-content:space-between;flex-wrap:nowrap"><span class="hint">${esc(new Date(x.ts).toLocaleString())} ・ ${x.segments}行 ・ 校正済み${x.proofed}行 ・ ${x.chars}字</span><button type="button" class="btn small" data-act="hirest">この時点に戻す</button></div>`).join('')
    : '<p class="hint" style="margin:6px 0 0">まだ履歴がありません</p>';
}
$('#hiRefresh').addEventListener('click', loadHistory);
$('#spDetails').addEventListener('toggle', () => { if ($('#spDetails').open && S.docId) loadHistory(); });
$('#hiList').addEventListener('click', e => {
  const b = e.target.closest('[data-act=hirest]'); if (!b) return;
  const ts = Number(b.closest('[data-ts]').dataset.ts);
  armDelete(b, async () => {
    try {
      await saveDoc();
      if (S.dirty || S.saving) return toast('保存中です。少し待ってから、もう一度押してください');
      await api('/api/restore', { body: { id: S.docId, ts } });
      await openDoc(S.docId, true); await loadHistory();
      toast('選んだ時点に戻しました(戻す前の状態も、履歴に残っています)');
    } catch (er){ toast(er.message); }
  });
});

function doSplit(i, row){
  const segs = S.doc.segments, s = segs[i], ta = row.querySelector('textarea');
  let pos = ta.selectionStart;
  if (!(pos > 0 && pos < s.text.length)) pos = Math.floor(s.text.length / 2);
  if (s.text.length < 2) return toast('短すぎて分割できません');
  const t = player().currentTime;
  let cut = t > s.start + 0.3 && t < s.end - 0.3 ? t : s.start + (s.end - s.start) * pos / s.text.length;
  cut = Math.round(cut * 100) / 100;
  const navId = navSnapshot();
  pushUndo();
  const left = { ...s, text: s.text.slice(0, pos).trimEnd(), end: cut };
  const right = { ...s, id: uid(), text: s.text.slice(pos).trimStart(), start: cut, flag: '' };
  segs.splice(i, 1, left, right); navRestore(navId, i); renderDoc(); markDirty();
}
/* ---------- v0.9.8: 行の追加(認識で抜けたセリフを書き足す) ----------
   時刻は前後の行の「すき間」に置く(すき間が 8 秒より長ければ 8 秒まで)。すき間が無いときは 1.5 秒の仮の長さで置き、重なりを案内する。
   並び順(開始時刻順)を必ず保つため、足したあと sortSegs() して id で位置を探し直す。原文(original)には何も足さないので、
   サーバー側の精度測定では「人が足した行 = 認識の脱落」として正しく数えられ、置換の学習には使われない */
const NEW_LEN = 1.5, NEW_MAX = 8, NEW_MIN_GAP = 0.3;
const r2 = v => Math.round(Math.max(0, v) * 100) / 100;
function insertRow(at, start, end, speaker){
  if (lockJob()) return toast('処理中のため、今は行を足せません');
  if (!(end > start)) end = start + NEW_LEN;
  pushUndo();
  const g = { id: uid(), start: r2(start), end: r2(end), text: '', speaker: speaker || '', flag: '' };
  S.doc.segments.splice(at, 0, g);   // 決めた位置に入れる(開始時刻の順は、呼び出し側で保っている)
  S.navIdx = at; renderDoc(); markDirty();
  if (rowsEl()[at] && rowsEl()[at].hidden){ $('#q').value = ''; $('#flagKind').value = ''; applyFilter(); toast('絞り込みを解除しました(足した行が見えるように)'); }
  gotoRow(at, { edit: true, center: true });
  const segs = S.doc.segments, pv = segs[at - 1], nx = segs[at + 1];
  if ((nx && g.end > nx.start + 0.01) || (pv && g.start < pv.end - 0.01)) toast('前後の行と時刻が重なっています。必要なら開始・終了を直してください', 3500);
  else toast('行を足しました。文字を入力してください(Esc で抜けます・Ctrl+Z で取り消し)', 2500);
}
function insertAfter(i){
  const segs = S.doc.segments, s = segs[i], nx = segs[i + 1]; if (!s) return;
  let a = s.end, b = nx ? nx.start : s.end + NEW_LEN;
  if (nx && a > nx.start) a = nx.start;
  if (b - a >= NEW_MIN_GAP) b = Math.min(b, a + NEW_MAX);
  else { b = a + NEW_LEN; if (nx && nx.end - a >= 0.5) b = Math.min(b, nx.end); }   // すき間が無いときの仮の長さ(次の行より後ろまでは伸ばさない)
  insertRow(i + 1, a, b, s.speaker);
}
function insertBefore(i){
  const segs = S.doc.segments, s = segs[i], pv = segs[i - 1]; if (!s) return;
  let b = s.start, a = pv ? Math.min(pv.end, b) : Math.max(0, b - NEW_LEN);
  if (b - a >= NEW_MIN_GAP) a = Math.max(a, b - NEW_MAX); else a = Math.max(pv ? pv.start : 0, b - NEW_LEN);
  insertRow(i, a, b > a ? b : a + NEW_LEN, s.speaker);
}
function insertAtTime(t){
  const segs = S.doc.segments; t = Math.max(0, Number(t) || 0);
  let k = -1; for (let j = 0; j < segs.length && segs[j].start <= t; j++) k = j;
  if (k >= 0 && t < segs[k].end) return insertAfter(k);   // 行の途中なら、その行の後ろへ
  const pv = segs[k], nx = segs[k + 1], lo = pv ? pv.end : 0, hi = nx ? nx.start : Infinity;
  const a = Math.max(lo, t - 0.3), b = Math.min(hi, a + 3);
  insertRow(k + 1, a, b - a >= NEW_MIN_GAP ? b : a + NEW_LEN, pv ? pv.speaker : (nx ? nx.speaker : ''));
}
function playSeg(s, one){
  const p = player(); p.currentTime = s.start;
  S.playEnd = one ? s.end : null;
  p.play().catch(() => {});
}
function curIndex(t){
  const segs = S.doc ? S.doc.segments : []; let lo = 0, hi = segs.length - 1, ans = -1;
  while (lo <= hi){ const m = (lo + hi) >> 1; if (segs[m].start <= t){ ans = m; lo = m + 1; } else hi = m - 1; }
  return ans >= 0 && t < segs[ans].end + 0.4 ? ans : -1;
}
player().addEventListener('timeupdate', () => {
  if (!S.doc) return;
  moveStripHead();
  const t = player().currentTime;
  if (S.playEnd !== null && t >= S.playEnd){ player().pause(); S.playEnd = null; }
  const i = curIndex(t); if (i === S.curIdx) return;
  const rows = rowsEl();
  rows[S.curIdx]?.classList.remove('cur'); S.curIdx = i;
  const el = rows[i]; if (!el) return;
  el.classList.add('cur');
  const typing = document.activeElement?.matches('#segs textarea, #segs input, #segs select');
  if (V.frameFollow && !typing && S.navIdx !== i) setNav(i);
  if ($('#follow').checked && !el.hidden && !typing) ensureVisible(el, 0.35);
});
player().addEventListener('error', () => {
  const m = $('#playerMsg'); m.hidden = false;
  m.textContent = '元のファイルを再生できません(移動・削除された、または mkv など対応していない形式の可能性)。文字の編集と書き出しは、再生できなくても使えます。';
});
player().addEventListener('playing', () => { $('#playerMsg').hidden = true; });
/* v0.9.6: 行の▶などで「そこだけ再生」した直後に手動で止めた場合、S.playEnd が残ったままだと、
   表示部(動画本体)の再生ボタンで再開したときにも、またそこで止まってしまう。
   一時停止するたびに必ずクリアして、表示部の再生は常に最後まで続けて流れるようにする */
player().addEventListener('pause', () => { S.playEnd = null; });

/* ブラウザのタブの題名: 「● タイトル - 文字起こしツール」(● は未保存・保存できていない) */
function updateDocTitle(){
  const d = S.doc, st = $('#saveState').getAttribute('data-state');
  document.title = d ? `${S.dirty || S.saving || st === 'err' ? '● ' : ''}${String(d.title || '無題').slice(0, 60)} - 文字起こしツール` : '文字起こしツール';
}
/* 文書を閉じる(開いている文書を削除したとき) */
function closeDoc(){
  clearTimeout(markDirty.t);
  S.doc = null; S.docId = null; S.dirty = false; S.conflict = false; S.forceNext = false; S.undo = []; S.sel = new Set(); S.navIdx = -1; S.curIdx = -1; S.handoff = null;
  $('#doc').hidden = true; $('#noDoc').hidden = false; $('#conflictBar').hidden = true; $('.app').classList.remove('has-doc');
  S.mediaSeq = (S.mediaSeq || 0) + 1; player().removeAttribute('src'); player().load();
  renderList(); updateDocTitle();
}

/* ---------- 検索・話者・置換 ---------- */
$('#q').addEventListener('input', applyFilter);
$('#flagKind').addEventListener('change', applyFilter);
$('#btnUndo').addEventListener('click', doUndo);
function syncEval(){ const on = !!(S.doc && S.doc.evalSet); $('#evalSet').checked = on; $('#evalBanner').hidden = !on; }
$('#evalSet').addEventListener('change', e => {
  if (!S.doc) return;
  S.doc.evalSet = e.target.checked; syncEval(); markDirty();
  const it = S.list.find(x => x.id === S.docId); if (it){ it.evalSet = S.doc.evalSet; renderList(); }
  toast(S.doc.evalSet ? '評価用にしました。この文字起こしは、辞書・提案・追加学習には使いません(すでに登録した辞書は残ります)' : '評価用を外しました。この文字起こしは、学習用として扱われます', 6000);
  setTimeout(() => { loadProgress(); loadLearned(); loadAcc(); }, 1500);
});
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
  renderDoc(); markDirty();
});
function playSpeaker(id){
  const list = S.doc.segments.filter(s => s.speaker === id && s.text.trim());
  if (!list.length) return toast('この話者の行がありません');
  const t = player().currentTime, next = list.find(s => s.start > t + 0.2) || list[0];
  playSeg(next, true);   // 「聞く」は、その行の終わりで止める(押すたびに、その人の次の発言へ)
}
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
function replaceOne(t, f, to){   // [新しい文章, 置換した数]
  const [core, wb] = wbSplit(f);
  if (!core || !t.includes(core)) return [t, 0];
  if (!wb){ const parts = t.split(core); return [parts.join(to), parts.length - 1]; }
  let out = '', i = 0, n = 0, k = t.indexOf(core);
  while (k >= 0){
    if (boundedAt(t, k, core)){ out += t.slice(i, k) + to; i = k + core.length; n++; k = t.indexOf(core, i); }
    else k = t.indexOf(core, k + 1);
  }
  return [out + t.slice(i), n];
}
function replaceAll(pairs){
  let total = 0;
  const has = pairs.filter(([f]) => f);
  for (const s of S.doc.segments){
    let t = s.text;
    for (const [f, to] of has){ const [nt, n] = replaceOne(t, f, to); t = nt; total += n; }
    if (t.slice(0, 2000) !== s.text) delete s.proofed;   // 聞かずに書き換えた行は、確認し直すまで校正済みにしない
    s.text = t.slice(0, 2000);
  }
  return total;
}
function withUndoReplace(pairs){
  const snap = JSON.stringify({ speakers: S.doc.speakers, segments: S.doc.segments });
  const n = replaceAll(pairs);
  if (n){ S.undo.push(snap); if (S.undo.length > 30) S.undo.shift(); updateUndo(); renderDoc(); markDirty(); }
  return n;
}
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
function tcode(t, sep){
  t = Math.max(0, t); const ms = Math.round(t * 1000), h = Math.floor(ms / 3600000), m = Math.floor(ms % 3600000 / 60000), s = Math.floor(ms % 60000 / 1000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}${sep}${String(ms % 1000).padStart(3, '0')}`;
}
function wrapText(text, n){
  if (!n) return text;
  const chars = [...text], lines = [];
  for (let i = 0; i < chars.length; i += n) lines.push(chars.slice(i, i + n).join(''));
  return lines.join('\n');
}
function exportRows(){
  const d = S.doc, only = $('#exSel').checked;
  const base = $('#exBase').value === 'rel' && !d.whole ? d.start : 0;
  const wrap = Number($('#exWrap').value) || 0, spk = $('#exSpk').checked;
  const rows = [];
  for (const s of d.segments){
    if (only && !S.sel.has(s.id)) continue;
    if (!s.text.trim() || s.end - base <= 0) continue;
    const sp = spById(s.speaker);
    rows.push({ start: Math.max(0, s.start - base), end: s.end - base, text: wrapText(s.text.trim(), wrap), name: spk && sp ? sp.name : '' });
  }
  return rows;
}
function buildExport(kind){
  const rows = exportRows(), d = S.doc;
  if (!rows.length) return null;
  if (kind === 'srt') return rows.map((r, i) => `${i + 1}\n${tcode(r.start, ',')} --> ${tcode(r.end, ',')}\n${r.name ? '[' + r.name + '] ' : ''}${r.text}\n`).join('\n');
  if (kind === 'vtt'){
    const e = t => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return 'WEBVTT\n\n' + rows.map(r => `${tcode(r.start, '.')} --> ${tcode(r.end, '.')}\n${r.name ? e('[' + r.name + '] ') : ''}${e(r.text)}\n`).join('\n');
  }
  if (kind === 'txt'){
    const ts = $('#exTs').checked;
    return rows.map(r => `${ts ? '[' + fmtT(r.start) + '] ' : ''}${r.name ? r.name + ': ' : ''}${r.text.replace(/\n/g, '')}`).join('\n') + '\n';
  }
  return JSON.stringify({ title: d.title, source: d.sourceName, start: d.start, end: d.end, speakers: d.speakers, segments: rows.map(r => ({ start: r.start, end: r.end, speaker: r.name, text: r.text.replace(/\n/g, '') })) }, null, 1);
}
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
function coveredBy(entries, path, start, end){   // サーバーの _covered と同じ判定(元のファイルパス+範囲での重なり。9割以上で「済み」)。パスの正規化は簡易(大小文字とスラッシュの違いだけ)
  const k = String(path).toLowerCase().replace(/\\/g, '/'), len = Math.max(0.0001, end - start);
  for (const r of entries){
    if (r.path !== k) continue;
    if (r.whole) return r.tid;
    const ov = Math.min(r.end != null ? r.end : end, end) - Math.max(r.start, start);
    if (ov > 0 && ov / len >= 0.9) return r.tid;
  }
  return '';
}
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
['optModel', 'optLang', 'optQuality', 'optDevice', 'optVad', 'optBoost', 'optAutoDict', 'optWordSplit', 'optStripPunct', 'optAutoGloss', 'optAutoLearned', 'arcAuto', 'arcFull', 'rtModel', 'rtTarget'].forEach(id => $('#' + id).addEventListener('change', readOpts));
['optGloss', 'repDict'].forEach(id => $('#' + id).addEventListener('input', readOpts));
$('#jobs').addEventListener('click', async e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  if (b.dataset.act === 'open') openDoc(b.dataset.tid);
  else if (b.dataset.act === 'evalview'){ showInMenu($('#accCard')); loadEvals(); }   // 「精度」タブに切り替えてから見せる(別のタブのままだと隠れていて何も起きなかった)
  else if (b.dataset.act === 'cancel'){ try { await api('/api/transcribe/cancel', { body: { id: b.closest('.job').dataset.id } }); pollJobs(); } catch (er){ toast(er.message); } }
});
$('#txList').addEventListener('click', e => {
  const b = e.target.closest('[data-act]'); if (!b) return; const id = b.closest('.txi').dataset.id;
  if (b.dataset.act === 'open') openDoc(id);
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
  if (!S.doc || isTextEntry(e.target) || document.querySelector('dialog[open]')) return;
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z'){ e.preventDefault(); if (!lockJob()) doUndo(); }
  else if (e.key === ' ' && !e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey && !e.target.matches('button,summary,video')){ e.preventDefault(); const p = player(); p.paused ? p.play().catch(() => {}) : p.pause(); }
});
window.addEventListener('beforeunload', e => { if (S.dirty || S.saving){ e.preventDefault(); e.returnValue = ''; } });   // 送信中の保存も、閉じると届かないことがある

/* ---------- 受け渡し(docs/pipeline.md 2・3・6): 元の配信(.clip.json)・URL で渡された動画・動画の隣に保存 ---------- */
const YT_PREFIX = 'https://www.youtube.com/';
const CLIP_IC = '<span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/></svg></span>';
const WARN_IC = '<span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg></span>';
/* youtube-tools-clip/v1 の「元の配信: タイトル 12:34〜13:20」。中の文字列(配信タイトル・マークの名前・URL・パス)は外から来るので必ずエスケープし、
   リンクにするのは https://www.youtube.com/ で始まる URL だけ(javascript: などを踏ませないため) */
function clipHTML(clip){
  const o = v => v && typeof v === 'object' ? v : {};
  const src = o(clip.source), rg = o(clip.range), mk = o(clip.mark);
  const a = Number(rg.start), b = Number(rg.end);
  const title = String(src.title || (src.path ? String(src.path).split(/[\\/]/).pop() : '') || src.videoId || '(タイトル不明)').slice(0, 200);
  const url = typeof src.url === 'string' && src.url.startsWith(YT_PREFIX) ? src.url + (Number.isFinite(a) ? (src.url.includes('?') ? '&' : '?') + 't=' + Math.floor(a) + 's' : '') : '';
  const when = Number.isFinite(a) ? `${fmtT(a)}〜${Number.isFinite(b) ? fmtT(b) : ''}` : '';
  const name = url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="YouTube で元の配信のこの位置を開く">${esc(title)}</a>` : `<b>${esc(title)}</b>`;
  const label = mk.label ? ` ・ 「${esc(String(mk.label).slice(0, 80))}」` : '';
  return `${CLIP_IC}<span>元の配信: ${name} <span class="mono">${esc(when)}</span>${label}</span>`;
}
function renderClipBox(box, clip, warning){
  if (clip && typeof clip === 'object'){ box.className = 'tt-clip'; box.innerHTML = clipHTML(clip) + (warning ? `<span class="hint">(${esc(warning)})</span>` : ''); box.hidden = false; }
  else if (warning){ box.className = 'tt-clip warn'; box.innerHTML = `${WARN_IC}<span>${esc(warning)}</span>`; box.hidden = false; }
  else { box.hidden = true; box.innerHTML = ''; }
}
/* 動画(または .clip.json)のパスから、隣の .clip.json を調べて「元の配信」を出す。サーバーはネットワークのパスを調べず、ffmpeg も呼ばないのですぐ返る */
let clipSeq = 0;
async function lookupClip(path){
  const box = $('#srcClip'), seq = ++clipSeq;
  path = String(path || '').trim().replace(/^"(.*)"$/, '$1');
  if (!path){ box.hidden = true; return null; }
  let r; try { r = await api('/api/clip-info?path=' + encodeURIComponent(path)); } catch { if (seq === clipSeq) box.hidden = true; return null; }   // 400(動画でないパス)などは、表示を消すだけ
  if (seq !== clipSeq) return null;   // 待っている間に別のパスが入った
  renderClipBox(box, r.clip, r.warning);
  return r;
}
$('#srcPath').addEventListener('change', e => lookupClip(e.target.value));
/* URL の ?media=<動画のパス> / ?clip=<.clip.json のパス>(他のツールの画面からのリンク)。
   ファイル欄に入れるだけで、文字起こしは始めない(別のサイトのリンクからでも開けるので、重い処理を URL だけで動かさない。docs/pipeline.md 3)。
   読んだら URL から消す(再読み込み・ブックマークで、同じ値が何度も入らないように) */
function takeUrlParams(){
  let q; try { q = new URLSearchParams(location.search); } catch { return false; }
  const media = (q.get('media') || '').trim().slice(0, 1000), clip = (q.get('clip') || '').trim().slice(0, 1000);
  if (!q.has('media') && !q.has('clip')) return false;
  q.delete('media'); q.delete('clip');
  const rest = q.toString();
  try { history.replaceState(history.state, '', location.pathname + (rest ? '?' + rest : '') + location.hash); } catch {}
  if (!media && !clip) return false;
  setTab('file'); setSideTab('start'); $('#newBox').open = true;
  if (media) $('#srcPath').value = media;
  lookupClip(clip || media).then(r => {
    if (clip && !media && r && r.mediaPath && !$('#srcPath').value.trim()) $('#srcPath').value = r.mediaPath;   // ?clip= だけのときは、.clip.json が指す動画を入れる
  });
  window.scrollTo(0, 0);   // 「新しく文字起こしする」はメニューの先頭なので、一番上を見せる(ファイル欄と「元の配信」が見える)
  toast((media ? '動画のパスを入れました。' : '元の配信の情報(.clip.json)を読み込みます。') + '設定を確かめて「文字起こしを開始」を押してください(自動では始めません)', 7000, 'info');
  return true;
}
/* 開いた文書の「元の配信」と、「動画の隣に保存」の結果の表示 */
S.handoff = null;   // { id, transcript, srt, plan }: 開いている文書を、動画の隣に保存したパス
function renderDocExtras(d){
  const box = $('#docClip');
  if (d && d.clip && typeof d.clip === 'object'){ box.className = 'tt-clip'; box.innerHTML = clipHTML(d.clip); box.hidden = false; }
  else { box.hidden = true; box.innerHTML = ''; }
  if (S.handoff && S.handoff.id !== S.docId) S.handoff = null;
  renderHandoff();
}
const HANDOFF_KEY = { 'transcript-v1': 'transcript', srt: 'srt', 'cut-plan-v1': 'plan' };
function renderHandoff(){
  const box = $('#handoffOut'), h = S.handoff;
  if (!box) return;
  if (!S.doc || !h || h.id !== S.docId){ box.hidden = true; box.innerHTML = ''; return; }
  const rows = [['transcript', '文字起こし'], ['srt', '字幕'], ['plan', '残す区間']].filter(([k]) => h[k])
    .map(([k, l]) => `<div><span class="hint">${l}:</span> <span class="path">${esc(h[k])}</span> <button type="button" class="btn ghost small" data-act="copy" data-k="${k}" title="このパスをコピー">コピー</button></div>`).join('');
  const src = String(S.doc.sourcePath || '');
  const c2r = h.transcript && src ? toolUrl('cut2resolve', '/?video=' + encodeURIComponent(src) + '&transcript=' + encodeURIComponent(h.transcript)) : '';
  box.innerHTML = rows + `<div class="row">${c2r ? `<a class="btn small primary" id="openC2R" href="${esc(c2r)}" target="_blank" rel="noopener">cut2resolve で開く</a><span class="hint">動画と文字起こしを入れた状態で開きます</span>` : '<span class="hint">cut2resolve で開くには「文字起こし(.transcript.json)」を保存してください</span>'}</div>`;
  box.hidden = false;
}
async function exportBeside(fmt, btn){
  if (!S.doc) return;
  if (lockJob()) return toast('話者の判別・再認識の途中です。終わってから書き出してください', 4000, 'err');
  const id = S.docId, label = btn.textContent;
  btn.disabled = true; btn.textContent = '保存中…';
  try {
    /* 画面の内容を先に保存し、その版(baseUpdatedAt)を付けて頼む。サーバーは保存済みの内容を書き出すので、
       保存が終わっていない・競合しているときは書き出さない(画面と違う内容を次のツールへ渡さないため) */
    const ok = await saveDoc();
    if (S.docId !== id) return;
    if (!ok || S.dirty || S.saving) return toast(S.conflict ? '保存が競合しています。映像の上の案内から選んでから、もう一度押してください' : '保存が追いついていません。少し待ってから、もう一度押してください', 6000, 'err');
    const r = await api('/api/export-file', { body: { id, format: fmt, baseUpdatedAt: S.baseUpdatedAt, wrap: Number($('#exWrap').value) || 0, speakerNames: $('#exSpk').checked } });
    if (S.docId !== id) return;
    S.handoff = { ...(S.handoff && S.handoff.id === id ? S.handoff : {}), id, [HANDOFF_KEY[fmt]]: r.path };
    renderHandoff(); loadSiblings();   // cut2resolve のポートを確かめ直す(終わると、リンクを作り直す)
    toast(`${r.overwritten ? '上書き保存' : '保存'}しました: ${r.name}(${Number(r.count) || 0}${fmt === 'cut-plan-v1' ? '区間' : '行'})`, 5000, 'ok');
  } catch (e){
    if (e.status === 409) toast('保存が追いついていません(書き出す直前に内容が変わりました)。少し待ってから、もう一度押してください', 6000, 'err');
    else toast('動画の隣に保存できませんでした: ' + e.message, 7000, 'err');
  } finally { btn.disabled = false; btn.textContent = label; }
}
document.querySelectorAll('[data-beside]').forEach(b => b.addEventListener('click', () => exportBeside(b.dataset.beside, b)));
$('#handoffOut').addEventListener('click', async e => {
  const b = e.target.closest('[data-act=copy]'); if (!b || !S.handoff) return;
  const v = S.handoff[b.dataset.k]; if (!v) return;
  try { await navigator.clipboard.writeText(v); toast('パスをコピーしました', 2000, 'ok'); } catch { toast('コピーできませんでした(パスを選んでコピーしてください)', 3000, 'err'); }
});

/* ---------- 起動 ---------- */
async function boot(){
  $('#ver').textContent = 'v' + APP_VERSION;
  loadView(); applyView();
  try {
    const ping = await api('/api/ping');
    if (ping.version !== APP_VERSION) showErr(`画面(v${APP_VERSION})とサーバー(v${ping.version})の版が違います。黒い画面を閉じて、起動し直してください`);
  } catch (e){ return showErr(e.message + '。start.bat / start.command から起動してください'); }
  try { S.tools = await api('/api/tools'); } catch {}
  await loadRoster();
  if (S.tools){
    $('#optModel').innerHTML = S.tools.models.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
    $('#optLang').innerHTML = S.tools.langs.map(l => `<option value="${esc(l)}">${esc({ ja: '日本語', en: '英語', ko: '韓国語', zh: '中国語', auto: '自動判定' }[l] || l)}</option>`).join('');
  }
  try { S.settings = await api('/api/settings'); } catch { S.settings = {}; }
  applySettings(); renderSetup(); renderDiarSetup(); renderRtSetup();
  takeUrlParams();   // ?media= / ?clip=(他のツールからのリンク)。設定を読んだあとに入れる(タブの切り替えで上書きされないように)
  loadSiblings();
  try { const j = await api('/api/jobs'); for (const x of j.jobs) if (x.state === 'done' || x.state === 'error') S.seen.add(x.id); } catch {}   // 開く前に終わっていたものは知らせない
  await Promise.all([loadList(), loadMarker(), pollJobs(), loadLearned(), loadAcc(), loadDataset(), loadProgress(), loadBaselines()]);
  if (S.jobs.some(j => ACTIVE.has(j.state))) startPolling();
}
boot();
function installResolveExport(){
  const host = $('#handoffBox');   // 「動画の隣に保存」の下に置く(書き出しの流れ: ダウンロード → 次のツールへ → Resolve)
  if (!host || $('#resolveExportBox')) return;
  const box = document.createElement('div');
  box.id = 'resolveExportBox'; box.className = 'fld';
  box.innerHTML = `<span class="l">DaVinci Resolveへ渡す</span>
    <div class="row"><button type="button" class="btn small" id="cutSelected">選択行をカット</button><button type="button" class="btn small" id="keepSelected">選択行を残す</button></div>
    <div class="row"><label class="lag">プロジェクト <select id="resolveFps" style="width:auto"><option>24</option><option>25</option><option selected>30</option><option>50</option><option>60</option></select> fps</label><label class="lag"><select id="resolveSize" style="width:auto"><option value="1080x1920" selected>縦 1080×1920</option><option value="1920x1080">横 1920×1080</option></select></label><button type="button" class="btn small" id="resolveExport">Resolveパッケージ(zip)をダウンロード</button></div>
    <span class="hint">「残す/カット済」で仮編集を指定します。中身は cut2resolve の Text+ パックと同じです(動画・Text+ 字幕を作るスクリプト・手順書・EDL・SRT)。fps と画面の大きさは、Resolve で手で作るプロジェクトの設定です。切り抜きスタジオで新しく書き出した素材は、前後10秒までトリムを延ばせます。</span>`;
  host.after(box);
  const bulk = cut => {
    if (!S.doc || !S.sel.size) return toast('先に左端のチェックで行を選んでください');
    if (lockJob()) return toast('処理中のため、今は変更できません');
    pushUndo();
    for (const s of S.doc.segments) if (S.sel.has(s.id)) { if (cut) s.cutState = 'cut'; else delete s.cutState; }
    renderDoc(); markDirty(); toast(`${S.sel.size}行を${cut ? 'カット済' : '残す'}にしました(「元に戻す」で戻せます)`, 2500);
  };
  $('#cutSelected').addEventListener('click', () => bulk(true));
  $('#keepSelected').addEventListener('click', () => bulk(false));
  $('#resolveExport').addEventListener('click', async () => {
    if (!S.docId) return toast('先に文字起こしを開いてください');
    if (!(await saveDoc()) || S.dirty) return toast(S.conflict ? '保存が競合しています。映像の上の案内から選んでから、もう一度押してください' : '保存が追いついていません。少し待ってから、もう一度押してください', 5000, 'err');
    const b = $('#resolveExport'), label = b.textContent; b.disabled = true; b.textContent = '作成中…';
    try {
      const r = await apiBlob('/api/resolve-package', { tid: S.docId, fps: $('#resolveFps').value, size: $('#resolveSize').value });
      download(await r.blob(), `${safeName(S.doc.title)}-resolve.zip`);
      const cuts = r.headers.get('X-Resolve-Cuts') || '?', caps = r.headers.get('X-Resolve-Captions') || '?';
      const handles = r.headers.get('X-Resolve-Handles') === '1' ? '・余白つき素材' : '';
      toast(`Resolveパッケージを作成しました(残す区間${cuts}か所・Text+ ${caps}件${handles})。zip を展開して、中の「友人へ.txt」の手順で Resolve に取り込みます`, 8000, 'ok');
    } catch (e){ toast('Resolveパッケージを作れませんでした: ' + e.message, 7000, 'err'); }
    finally { b.disabled = false; b.textContent = label; }
  });
}
installResolveExport();
})();
