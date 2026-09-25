/* cut2resolve の画面。サーバー(serve.py)の API は api() だけを通す(入口の統合サーバーに取り込まれたときも BASE が変わるだけ)。
   外から来る文字列(ファイル名・パス・字幕・エラーの文言)は textContent か esc() で入れる。CSP で style 属性・インラインのスクリプトは使えないので、
   位置は element.style(CSSOM)で付ける。 */
(() => {
'use strict';
// 画面の場所("" または入口に取り込まれたときの "/cut2resolve")。API・動画の URL はこれを前に付ける(絶対パス "/api/..." を直接書かない)
const BASE = location.pathname.replace(/\/[^/]*$/, '');
// 入口に取り込まれたときの合言葉(CSRF トークン。入口が <meta name="ytt-token"> で入れる)。書き込み系の要求に付ける
const TOKEN = (document.querySelector('meta[name="ytt-token"]') || {}).content || '';
const APP_VERSION = document.documentElement.getAttribute('data-app-version') || '';
const LS_KEY = 'c2r:form:v1';
const FIELDS = ['video', 'srt', 'transcript', 'plan'];
const INPUT_ID = { video: 'inVideo', srt: 'inSrt', transcript: 'inTranscript', plan: 'inPlan' };
const STATUS_ID = { video: 'stVideo', srt: 'stSrt', transcript: 'stTranscript', plan: 'stPlan' };
const VIDEO_EXTS = ['.mp4', '.m4v', '.mov', '.mkv', '.webm', '.avi', '.mxf', '.ts', '.mts', '.m2ts', '.flv', '.wmv'];
const PERSIST = ['inVideo', 'inSrt', 'inTranscript', 'inPlan', 'handles', 'listText', 'noise', 'silMin', 'silPad', 'minLen', 'joinGap',
  'srcStartTc', 'recStart', 'edlName', 'reel', 'outDir', 'optRender', 'optCopy', 'optFcpxml', 'optTextPlus', 'textplusFps', 'textplusSize', 'dropCutRows', 'silenceExtra'];

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const byId = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------- API ---------- */
async function api(path, opts) {
  opts = opts || {};
  const init = { method: opts.method || (opts.body !== undefined || opts.raw !== undefined ? 'POST' : 'GET'), cache: 'no-store', headers: {} };
  if (opts.raw !== undefined) { init.headers['Content-Type'] = 'application/octet-stream'; init.body = opts.raw; }
  else if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  if (TOKEN && init.method !== 'GET' && init.method !== 'HEAD') init.headers['X-YTT-Token'] = TOKEN;
  let r;
  try { r = await fetch(BASE + path, init); }
  catch (e) { const er = new Error('サーバーに接続できません(黒い画面が閉じていないか確認してください)'); er.code = 'network'; throw er; }
  let j = null;
  try { j = await r.json(); } catch (e) { /* 本文が JSON でない */ }
  if (!r.ok) {
    const er = new Error((j && j.message) || ('サーバーエラー(HTTP ' + r.status + ')'));
    er.code = (j && j.error) || 'http'; er.status = r.status; er.data = j;
    throw er;
  }
  return j;
}
const mediaSrc = u => BASE + u;

/* ---------- 小物 ---------- */
function fmt(sec) {
  if (sec == null || !isFinite(sec)) return '—';
  const cs = Math.round(Math.max(0, sec) * 100);
  const h = Math.floor(cs / 360000), m = Math.floor(cs % 360000 / 6000), s = (cs % 6000) / 100;
  const ss = s.toFixed(2).padStart(5, '0');
  return h ? h + ':' + String(m).padStart(2, '0') + ':' + ss : m + ':' + ss;
}
function fmtBytes(n) {
  if (n == null) return '—';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(2) + ' GB';
}
const baseName = p => String(p || '').split(/[\\/]/).pop();
const normPath = p => String(p || '').trim().replace(/^["']|["']$/g, '').replace(/\//g, '\\').toLowerCase();
let toastT = null;
function toast(msg, ms) {
  const t = byId('toast'); t.textContent = String(msg); t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, ms || 4200);
}
function showErr(msg) { const b = byId('errBar'); b.textContent = String(msg); b.hidden = false; }
function notice(el, msg, kind) {
  if (!msg) { el.hidden = true; el.textContent = ''; return; }
  el.className = 'notice' + (kind ? ' ' + kind : '');
  el.textContent = String(msg); el.hidden = false;
}
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = String(text);
  return e;
}

/* ---------- 状態 ---------- */
const S = {
  info: { video: null, srt: null, transcript: null, plan: null },   // 読み込んだ結果(正しく読めたものだけ)
  inspected: {},                    // 読み込んだときの欄の値(値が変わったら読み込み直す)
  uploaded: {},                     // アップロードしたコピーのパス → 元のファイル名
  mode: 'silence', keepSource: 'plan', listKind: 'keep',
  handlesTouched: false,
  plan: null, planSig: '',
  job: null, pollT: null,
  result: null,
  ports: null, limits: {}, state: null,
  keeps: [], keepsSec: [], cum: [], fps: [30, 1], total: 0, dur: 0,
  rough: false,                     // 粗編集の動画を再生中
  raf: 0,
};

/* ---------- 欄の値・保存 ---------- */
const val = f => byId(INPUT_ID[f]).value.trim();
function setVal(f, v) { byId(INPUT_ID[f]).value = v || ''; }
function saveForm() {
  const d = { mode: S.mode, keepSource: S.keepSource, listKind: S.listKind, handlesTouched: S.handlesTouched };
  for (const id of PERSIST) { const e = byId(id); d[id] = e.type === 'checkbox' ? e.checked : e.value; }
  try { localStorage.setItem(LS_KEY, JSON.stringify(d)); } catch (e) { /* 保存できなくても動く */ }
}
function loadForm() {
  let d = null;
  try { d = JSON.parse(localStorage.getItem(LS_KEY) || 'null'); } catch (e) { d = null; }
  if (!d || typeof d !== 'object') return false;
  for (const id of PERSIST) {
    if (!(id in d)) continue;
    const e = byId(id);
    if (e.type === 'checkbox') e.checked = !!d[id]; else e.value = typeof d[id] === 'string' ? d[id] : '';
  }
  if (['silence', 'keep', 'list'].includes(d.mode)) S.mode = d.mode;
  if (['plan', 'transcript'].includes(d.keepSource)) S.keepSource = d.keepSource;
  if (['keep', 'drop'].includes(d.listKind)) S.listKind = d.listKind;
  S.handlesTouched = !!d.handlesTouched;
  return true;
}

/* ---------- 入力の読み込み ---------- */
function setStatus(f, kind, text, extra) {
  const box = byId(STATUS_ID[f]);
  box.className = 'c2r-status' + (kind ? ' is-' + kind : '');
  box.textContent = '';
  if (!kind) return;
  const dot = el('span', 'dot ' + (kind === 'ok' ? 'ok' : kind === 'err' ? 'err' : kind === 'run' ? 'run' : ''));
  const body = el('div', 'c2r-status-body');
  body.appendChild(el('span', 'c2r-status-text', text));
  if (extra) body.appendChild(extra);
  box.append(dot, body);
}

function summarize(f, r) {
  if (f === 'video') {
    const orient = r.h > r.w ? '縦' : '横';
    return orient + ' ' + r.w + '×' + r.h + ' · ' + r.fpsLabel + 'fps · ' + fmt(r.durationSec) + ' · 音声' + (r.audio ? 'あり' : 'なし') +
      ' · 開始TC ' + r.startTc;
  }
  if (f === 'srt') return r.count + '件の字幕(最後 ' + fmt(r.lastSec) + ')';
  if (f === 'transcript') return r.rows + '行(残す ' + r.kept + '・カット済 ' + r.cut + ')' + (r.title ? '「' + r.title + '」' : '');
  if (f === 'plan') {
    return '採用区間 ' + r.segments + '件(合計 ' + fmt(r.totalSec) + ')' +
      (r.fineGrained ? ' · 文字起こし由来(行単位)' : '') + (r.includesHandles ? ' · 余白込み' : '');
  }
  return '';
}

function statusExtra(f, r) {
  const wrap = el('div', 'c2r-status-extra');
  if (S.uploaded[r.path]) wrap.appendChild(el('span', 'pill', 'アップロードしたコピー: ' + S.uploaded[r.path]));
  if (f === 'video') {
    for (const w of r.warnings || []) wrap.appendChild(el('div', 'c2r-warn-line', w));
    const url = window.UIKit ? UIKit.tools.url('transcribe', S.ports, '/?media=' + encodeURIComponent(r.path)) : '';
    if (url) {
      const a = el('a', 'c2r-link', '文字起こしツールで開く');
      a.href = url; a.target = '_blank'; a.rel = 'noopener';
      a.title = '文字起こしツールを、この動画を入れた状態で開きます(自動では始めません)';
      wrap.appendChild(a);
    }
  }
  if ((f === 'transcript' || f === 'plan') && r.mediaPath && val('video') && normPath(r.mediaPath) !== normPath(val('video'))) {
    wrap.appendChild(el('div', 'c2r-warn-line', 'このファイルに書かれた動画(' + baseName(r.mediaPath) + ')と、上の動画が違うようです'));
  }
  if (f === 'transcript' && r.bad) wrap.appendChild(el('div', 'c2r-warn-line', '時刻が正しくない ' + r.bad + ' 行は使いません'));
  return wrap.childNodes.length ? wrap : null;
}

async function inspect(fields, opts) {
  opts = opts || {};
  const body = {};
  for (const f of fields || FIELDS) {
    const v = val(f);
    if (!v) { S.info[f] = null; S.inspected[f] = ''; setStatus(f, ''); continue; }
    body[f] = v;
  }
  const keys = Object.keys(body);
  if (!keys.length) { afterInputs(); return; }
  for (const f of keys) setStatus(f, 'run', '読み込んでいます…');
  let j;
  try { j = await api('/api/inspect', { body }); }
  catch (e) { for (const f of keys) setStatus(f, 'err', e.message); afterInputs(); return; }
  for (const f of keys) {
    const r = j.inputs[f];
    S.inspected[f] = body[f];
    if (r && r.ok) { S.info[f] = r; setStatus(f, 'ok', summarize(f, r), statusExtra(f, r)); }
    else { S.info[f] = null; setStatus(f, 'err', r ? r.error : '読み込めませんでした'); }
  }
  if (j.suggestVideo && !val('video') && !opts.noSuggest) {
    setVal('video', j.suggestVideo);
    toast('文字起こし(または cut-plan)に書かれた動画を入れました: ' + baseName(j.suggestVideo));
    await inspect(['video', 'transcript', 'plan'].filter(f => val(f)), { noSuggest: true });
    return;
  }
  afterInputs();
}

async function ensureInspected() {
  const need = FIELDS.filter(f => val(f) !== (S.inspected[f] || ''));
  if (need.length) await inspect(need);
}

function afterInputs() {
  const v = S.info.video;
  // プレビューの動画
  const player = byId('player');
  if (v && !S.rough && player.getAttribute('data-src') !== v.mediaUrl) {
    player.setAttribute('data-src', v.mediaUrl);
    player.src = mediaSrc(v.mediaUrl);
    byId('playerMsg').hidden = true;
  }
  if (!v && !S.rough) { player.removeAttribute('src'); player.removeAttribute('data-src'); player.load(); }
  byId('playerEmpty').hidden = !!(v || S.rough);
  byId('btnPlay').disabled = !(v || S.rough);
  byId('pvInfo').textContent = v ? v.name : '';
  byId('outDir').placeholder = v ? v.defaultOutDir : '空欄 = 動画と同じ場所の <動画名>_pack';
  // 文字起こしの「カット済」
  const tr = S.info.transcript;
  byId('cutRowsWrap').hidden = !(tr && tr.cut > 0);
  if (tr) byId('cutRowsLabel').textContent = '文字起こしの「カット済」の行(' + tr.cut + '行)を削る';
  syncMode();
  markStale();
  syncSteps();
}

/* ---------- カットの決め方 ---------- */
function defaultHandles() {
  if (S.keepSource === 'transcript') return 0;
  const p = S.info.plan;
  return p ? p.defaultHandles : 10;
}
function syncMode() {
  $$('#modes button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === S.mode)));
  $$('.c2r-panel').forEach(p => { p.hidden = p.dataset.panel !== S.mode; });
  $$('#keepSrc button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.src === S.keepSource)));
  $$('#listKind button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.kind === S.listKind)));
  byId('silenceExtraWrap').hidden = S.mode === 'silence';
  byId('silBox').hidden = !(S.mode === 'silence' || byId('silenceExtra').checked);
  if (!S.handlesTouched) byId('handles').value = String(defaultHandles());
  const hint = byId('keepHint'), p = S.info.plan;
  let t;
  if (S.keepSource === 'transcript') {
    t = S.info.transcript ? '文字起こしの残す行(カット済でない行)だけを残します。行と行の間のすき間(無音など)は削ります。余白を足すと、行の前後のすき間も少し残ります。'
      : '「文字起こし」の欄にファイルを入れてください。';
  } else if (!p) {
    t = '「残す区間(cut-plan)」の欄にファイルを入れてください。';
  } else if (p.fineGrained) {
    t = 'この cut-plan は文字起こし由来(行単位の短い区間)なので、余白の既定は 0 秒です。10 秒にすると区間どうしがつながり、カット済の行が消えません。';
  } else if (p.includesHandles) {
    t = 'この cut-plan は cut2resolve が書いたもの(余白込み)なので、余白の既定は 0 秒です。';
  } else {
    t = '採用区間の前後に余白(既定 10 秒)を残します。Resolve でカット位置を調整できるようにするためです。';
  }
  hint.textContent = t;
  byId('listHint').textContent = S.listKind === 'keep'
    ? '書いた区間だけを残します。時刻は 12.5 / 1:02.5 / 0:01:02 の形。区切りは空白・-・〜・→ など。'
    : '書いた区間を削ります(空なら動画全体)。文字起こしのカット済・無音と組み合わせられます。';
}

function buildSpec() {
  const num = id => byId(id).value.trim();
  return {
    video: val('video'), srt: val('srt'), transcript: val('transcript'), plan: val('plan'),
    mode: S.mode, keepSource: S.keepSource, handles: num('handles'),
    listKind: S.listKind, listText: byId('listText').value,
    silence: { noise: num('noise'), min: num('silMin'), pad: num('silPad') },
    silenceExtra: byId('silenceExtra').checked,
    dropCutRows: byId('dropCutRows').checked,
    minLen: num('minLen'), joinGap: num('joinGap'),
    advanced: { srcStartTc: num('srcStartTc'), recStart: num('recStart'), name: num('edlName'), reel: num('reel') },
  };
}
function outputOpts(force) {
  const textplus = byId('optTextPlus').checked;
  return { dir: byId('outDir').value.trim(), render: byId('optRender').checked, copyVideo: byId('optCopy').checked,
    fcpxml: byId('optFcpxml').checked && !textplus, textplus,
    textplusFps: byId('textplusFps').value, textplusSize: byId('textplusSize').value, force: !!force };
}
const specSig = () => JSON.stringify(buildSpec());

function markStale() {
  const stale = !!S.plan && S.planSig !== specSig();
  byId('staleNotice').hidden = !stale;
  byId('cardPreview').classList.toggle('is-stale', stale);
  syncSteps();
}

/* ---------- ジョブ(試算・パック作成) ---------- */
function setBusy(b) {
  for (const id of ['btnPlan', 'btnBuild', 'btnInspect']) byId(id).disabled = b;
  document.body.classList.toggle('is-busy', b);
}
function renderJob(kind, j) {
  const box = byId(kind === 'plan' ? 'jobPlan' : 'jobBuild');
  if (!j) { box.hidden = true; box.textContent = ''; return; }
  box.hidden = false;
  box.textContent = '';
  const row = el('div', 'c2r-job-row');
  const pill = el('span', 'pill run', j.state === 'running' ? '実行中' : j.state);
  const msg = el('span', 'c2r-job-msg', j.message || (kind === 'plan' ? '試算しています…' : 'パックを作っています…'));
  const pct = el('span', 'mono c2r-job-pct', j.progress != null ? Math.round(j.progress * 100) + '%' : '');
  const el2 = el('span', 'mono muted c2r-job-el', j.elapsed != null ? j.elapsed.toFixed(1) + '秒' : '');
  const cancel = el('button', 'btn small danger', '取り消す');
  cancel.type = 'button';
  cancel.id = kind === 'plan' ? 'btnCancelPlan' : 'btnCancelBuild';
  cancel.addEventListener('click', () => cancelJob());
  row.append(pill, msg, el('span', 'spacer'), el2, pct, cancel);
  const bar = el('div', 'bar' + (j.progress == null ? ' indeterminate' : ''));
  const i = el('i');
  if (j.progress != null) i.style.width = Math.round(j.progress * 100) + '%';
  bar.appendChild(i);
  box.append(row, bar);
}
function trackJob(job, kind, onDone, onError) {
  S.job = job; setBusy(true); renderJob(kind, job);
  let fails = 0;
  const tick = async () => {
    let j;
    try { j = await api('/api/job?id=' + encodeURIComponent(job.id)); fails = 0; }
    catch (e) {
      if (++fails < 20 && e.code === 'network') { S.pollT = setTimeout(tick, 500); return; }
      S.job = null; setBusy(false); renderJob(kind, null); (onError || (() => {}))({ message: e.message }); return;
    }
    if (j.state === 'running') { renderJob(kind, j); S.pollT = setTimeout(tick, 250); return; }
    S.job = null; setBusy(false); renderJob(kind, null);
    if (j.state === 'done') onDone(j.result);
    else if (j.state === 'cancelled') toast('取り消しました');
    else if (onError) onError(j.error || { message: '失敗しました' });
  };
  S.pollT = setTimeout(tick, 120);
}
async function cancelJob() {
  if (!S.job) return;
  try { await api('/api/job/cancel', { body: { id: S.job.id } }); } catch (e) { toast(e.message); }
}

async function runPlan() {
  if (S.job) return;
  notice(byId('cutError'), '');
  if (!val('video')) { notice(byId('cutError'), '動画のパスを入れてください', 'danger'); byId('inVideo').focus(); return; }
  await ensureInspected();
  const spec = buildSpec(), sig = JSON.stringify(spec);
  let j;
  try { j = await api('/api/plan', { body: { spec, output: outputOpts() } }); }
  catch (e) { notice(byId('cutError'), e.message, 'danger'); return; }
  trackJob(j.job, 'plan', res => {
    S.plan = res; S.planSig = sig;
    renderPlan(res);
    markStale();
  }, err => notice(byId('cutError'), err.message, 'danger'));
}

async function runBuild(force) {
  if (S.job) return;
  notice(byId('buildError'), '');
  if (!val('video')) { notice(byId('buildError'), '動画のパスを入れてください', 'danger'); byId('inVideo').focus(); return; }
  await ensureInspected();
  const spec = buildSpec(), sig = JSON.stringify(spec);
  let j;
  try { j = await api('/api/build', { body: { spec, output: outputOpts(force) } }); }
  catch (e) {
    if (e.code === 'exists' && e.data) {
      if (await confirmOverwrite(e.data.files || [], e.data.dir || '')) runBuild(true);
      return;
    }
    notice(byId('buildError'), e.message, 'danger'); return;
  }
  byId('result').hidden = true;
  trackJob(j.job, 'build', res => {
    S.plan = res.summary; S.planSig = sig;
    renderPlan(res.summary);
    showResult(res);
    markStale();
  }, async err => {
    if (err.code === 'exists') {
      if (await confirmOverwrite(err.files || [], byId('outDir').value.trim())) runBuild(true);
      return;
    }
    notice(byId('buildError'), err.message, 'danger');
  });
}

function confirmOverwrite(files, dir) {
  const dlg = byId('dlgOverwrite');
  byId('owDir').textContent = dir || '';
  byId('owDir').hidden = !dir;
  const ul = byId('owFiles'); ul.textContent = '';
  for (const f of files) ul.appendChild(el('li', 'mono', f));
  return new Promise(resolve => {
    const done = v => { dlg.close(); byId('owOk').onclick = null; byId('owCancel').onclick = null; dlg.oncancel = null; resolve(v); };
    byId('owOk').onclick = () => done(true);
    byId('owCancel').onclick = () => done(false);
    dlg.oncancel = e => { e.preventDefault(); done(false); };
    dlg.showModal();
    byId('owCancel').focus();
  });
}

/* ---------- 試算の結果 ---------- */
function frameSec(n) { return n * S.fps[1] / S.fps[0]; }

function seg(cls, a, b, total, title) {
  const d = el('div', 'c2r-seg ' + cls);
  d.style.left = (a / total * 100) + '%';
  d.style.width = Math.max(0, (b - a) / total * 100) + '%';
  if (title) d.title = title;
  return d;
}

function renderPlan(r) {
  S.fps = r.fps; S.total = r.total; S.dur = r.durationSec; S.keeps = r.keeps;
  S.keepsSec = r.keeps.map(([a, b]) => [frameSec(a), frameSec(b)]);
  S.cum = []; let acc = 0;
  for (const [a, b] of S.keepsSec) { S.cum.push(acc); acc += b - a; }
  const total = r.total;
  // タイムライン(カットの帯)
  const lane = byId('laneCut'); lane.textContent = '';
  const frag = document.createDocumentFragment();
  const drops = r.drops || {};
  const dropCls = { silence: 'is-silence', cutRows: 'is-cutrows', list: 'is-list', lines: 'is-list' };
  for (const k of Object.keys(drops)) {
    for (const [a, b] of drops[k]) frag.appendChild(seg('c2r-dseg ' + (dropCls[k] || ''), a, b, total));
  }
  const hasCore = (r.baseKind === 'plan' || r.baseKind === 'rows') && r.handles > 0;
  r.keeps.forEach(([a, b], i) => {
    frag.appendChild(seg('c2r-keep' + (hasCore ? ' has-core' : ''), a, b, total,
      '残す ' + (i + 1) + ': ' + fmt(frameSec(a)) + ' – ' + fmt(frameSec(b)) + '(' + fmt(frameSec(b - a)) + ')'));
  });
  if (hasCore) for (const [a, b] of r.selected || []) frag.appendChild(seg('c2r-core', a, b, total));
  lane.appendChild(frag);
  // 字幕・文字起こしの行
  const sub = byId('laneSub'); sub.textContent = '';
  const f2 = document.createDocumentFragment();
  let subKind = '';
  if (r.transcriptRows && r.transcriptRows.length) {
    subKind = '文字起こしの行';
    for (const [a, b, cut, kept] of r.transcriptRows) f2.appendChild(seg('c2r-row' + (cut ? ' is-cut' : kept ? '' : ' is-empty'), a, b, total));
  } else if (r.subtitles && r.subtitles.cues) {
    subKind = '字幕';
    for (const [a, b, t] of r.subtitles.cues) f2.appendChild(seg('c2r-cue', a, b, total, t));
  }
  sub.appendChild(f2);
  sub.hidden = !subKind;
  // 目盛り
  const ruler = byId('ruler'); ruler.textContent = '';
  for (let i = 0; i <= 4; i++) ruler.appendChild(el('span', '', fmt(S.dur * i / 4)));
  // 凡例
  $('.c2r-lg-core').hidden = !hasCore;
  $('.c2r-lg-silence').hidden = !drops.silence;
  $('.c2r-lg-cutrows').hidden = !drops.cutRows;
  $('.c2r-lg-list').hidden = !(drops.list || drops.lines);
  const lgSub = $('.c2r-lg-sub'); lgSub.hidden = !subKind;
  lgSub.lastChild.textContent = subKind || '字幕';
  // カット後のタイムライン
  const after = byId('afterBar');
  $$('.c2r-seg', after).forEach(x => x.remove());
  const kept = r.keptSec;
  let pos = 0;
  S.keepsSec.forEach(([a, b], i) => {
    const d = el('div', 'c2r-seg c2r-aseg' + (i % 2 ? ' is-alt' : ''));
    d.style.left = (pos / kept * 100) + '%'; d.style.width = ((b - a) / kept * 100) + '%';
    d.title = (i + 1) + ': ' + fmt(pos) + ' – ' + fmt(pos + b - a);
    after.insertBefore(d, byId('afterHead'));
    pos += b - a;
  });
  byId('afterLen').textContent = fmt(kept) + '(' + r.count + 'か所をつなぐ)';
  byId('afterWrap').hidden = false;
  byId('tCutDur').textContent = '/ ' + fmt(kept);
  byId('tDur').textContent = '/ ' + fmt(S.dur);
  // 合計
  const stats = byId('stats'); stats.textContent = '';
  const tile = (label, value, sub, cls) => {
    const d = el('div', 'c2r-stat' + (cls ? ' ' + cls : ''));
    d.append(el('small', '', label), el('b', 'mono', value));
    if (sub) d.appendChild(el('span', '', sub));
    stats.appendChild(d);
  };
  tile('元の長さ', fmt(r.durationSec), r.total + ' フレーム');
  tile('残す', fmt(r.keptSec), r.keptPercent + '%', 'is-keep');
  tile('削る', fmt(r.removedSec), (100 - r.keptPercent).toFixed(1) + '%', 'is-cut');
  tile('区間', String(r.count), r.count > 999 ? 'EDL の上限を超えています' : 'か所');
  if (r.subtitles) tile('字幕', r.subtitles.in + ' → ' + r.subtitles.out, r.subtitles.vanished ? 'カットで消えた ' + r.subtitles.vanished + '件' : (r.subtitles.source === 'transcript' ? '文字起こしから' : 'SRT から'));
  stats.hidden = false;
  // 注意
  const w = byId('planWarns'); w.textContent = '';
  for (const m of r.warnings || []) w.appendChild(el('div', 'notice', m));
  // 残す区間の一覧
  const tb = byId('keepRows'); tb.textContent = '';
  const LIMIT = 500;
  S.keepsSec.slice(0, LIMIT).forEach(([a, b], i) => {
    const tr = el('tr');
    tr.dataset.i = String(i);
    tr.tabIndex = 0;
    tr.append(el('td', 'n mono', i + 1), el('td', 'mono', fmt(a) + ' – ' + fmt(b)), el('td', 'n mono', fmt(b - a)), el('td', 'n mono', fmt(S.cum[i])));
    tb.appendChild(tr);
  });
  if (S.keepsSec.length > LIMIT) {
    const tr = el('tr'); const td = el('td', 'muted', '… 残り ' + (S.keepsSec.length - LIMIT) + ' か所');
    td.colSpan = 4; tr.appendChild(td); tb.appendChild(tr);
  }
  byId('keepCount').textContent = r.count + 'か所';
  byId('keepBox').hidden = false;
  byId('planEmpty').hidden = true;
  byId('playhead').hidden = false;
  byId('timeline').setAttribute('aria-valuemax', String(Math.round(S.dur)));
  byId('btnPrevKeep').disabled = byId('btnNextKeep').disabled = !S.keepsSec.length;
  // 作るもの
  if (r.outputs) {
    const ex = r.outputs.existing || [];
    byId('buildHint').textContent = '作るもの: ' + r.outputs.files.join('・') + (ex.length ? '(' + ex.length + '件は既にあります。作るときに上書きの確認をします)' : '');
  }
  updateTime();
  syncSteps();
}

function showResult(res) {
  S.result = res;
  byId('resDir').textContent = res.outDir;
  const tb = byId('resFiles'); tb.textContent = '';
  for (const f of res.files) {
    const tr = el('tr');
    const name = el('td', 'mono c2r-fname', f.name);
    name.title = f.path;
    tr.append(name, el('td', '', f.note), el('td', 'n mono', fmtBytes(f.size)));
    tb.appendChild(tr);
  }
  const w = byId('resWarns'); w.textContent = '';
  for (const m of res.warnings || []) w.appendChild(el('div', 'notice', m));
  byId('resReadme').textContent = res.readme || '';
  byId('btnPlayRough').hidden = !res.roughcutUrl;
  byId('result').hidden = false;
  byId('buildHint').textContent = '同じ出力先でもう一度作るときは、上書きの確認が出ます';
  syncSteps();
  byId('result').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ---------- プレビューの再生 ---------- */
const player = byId('player');
function keepAt(t) {
  // t を含む区間の番号と、次の区間の番号(二分探索)
  const k = S.keepsSec;
  let lo = 0, hi = k.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (k[mid][1] <= t) lo = mid + 1; else hi = mid; }
  return { inside: lo < k.length && k[lo][0] <= t + 1e-6 ? lo : -1, next: lo };
}
function cutTime(t) {
  if (!S.keepsSec.length) return null;
  const k = keepAt(t);
  if (k.inside >= 0) return S.cum[k.inside] + t - S.keepsSec[k.inside][0];
  if (k.next < S.keepsSec.length) return S.cum[k.next];
  const last = S.keepsSec.length - 1;
  return S.cum[last] + S.keepsSec[last][1] - S.keepsSec[last][0];
}
function sourceTimeFromCut(c) {
  for (let i = S.keepsSec.length - 1; i >= 0; i--) if (S.cum[i] <= c) return S.keepsSec[i][0] + (c - S.cum[i]);
  return 0;
}
function updateTime() {
  const t = player.currentTime || 0;
  const dur = S.dur || player.duration || 0;
  if (S.rough) {
    byId('tNow').textContent = '—';
    byId('tCut').textContent = fmt(t);
    setHead(byId('afterHead'), S.plan ? t / S.plan.keptSec : 0);
    byId('playhead').hidden = true;
    return;
  }
  byId('tNow').textContent = fmt(t);
  if (!S.plan) { byId('tDur').textContent = '/ ' + fmt(player.duration); }
  const c = cutTime(t);
  byId('tCut').textContent = c == null ? '—' : fmt(c);
  byId('timeline').setAttribute('aria-valuenow', String(Math.round(t)));
  if (dur) { byId('playhead').hidden = false; setHead(byId('playhead'), t / dur); }
  if (c != null && S.plan) setHead(byId('afterHead'), c / S.plan.keptSec);
  const inside = S.keepsSec.length ? keepAt(t).inside >= 0 : true;
  byId('timeline').classList.toggle('is-in-cut', !inside);
}
function setHead(h, frac) { h.style.left = (Math.max(0, Math.min(1, frac || 0)) * 100) + '%'; }
function skipRemoved() {
  if (S.rough || !byId('cutView').checked || !S.keepsSec.length) return;
  const t = player.currentTime;
  const k = keepAt(t);
  if (k.inside >= 0) return;
  if (k.next < S.keepsSec.length) player.currentTime = S.keepsSec[k.next][0] + 0.001;
  else { player.pause(); player.currentTime = Math.max(0, S.keepsSec[S.keepsSec.length - 1][1] - 0.04); }
}
function loop() {
  updateTime();
  skipRemoved();
  if (!player.paused) S.raf = requestAnimationFrame(loop);
}
function togglePlay() {
  if (!player.src) return;
  if (player.paused) { skipRemoved(); player.play().catch(() => {}); } else player.pause();
}
function seekTo(t) {
  if (!player.src) return;
  const dur = S.rough ? (S.plan ? S.plan.keptSec : player.duration) : (S.dur || player.duration || 0);
  player.currentTime = Math.max(0, Math.min(dur || 0, t));
  updateTime();
}
function jumpKeep(dir) {
  if (!S.keepsSec.length || S.rough) return;
  const t = player.currentTime + (dir > 0 ? 0.05 : -0.3);
  const k = keepAt(t);
  let i = dir > 0 ? (k.inside >= 0 ? k.inside + 1 : k.next) : (k.inside >= 0 ? k.inside - 1 : k.next - 1);
  i = Math.max(0, Math.min(S.keepsSec.length - 1, i));
  seekTo(S.keepsSec[i][0]);
}
function setRough(on) {
  if (!S.result || !S.result.roughcutUrl) on = false;
  S.rough = on;
  player.pause();
  if (on) { player.src = mediaSrc(S.result.roughcutUrl); player.setAttribute('data-src', S.result.roughcutUrl); }
  else if (S.info.video) { player.src = mediaSrc(S.info.video.mediaUrl); player.setAttribute('data-src', S.info.video.mediaUrl); }
  byId('btnPlayRough').textContent = on ? '元の動画に戻す' : '粗編集の動画を再生';
  byId('pvInfo').textContent = on ? '粗編集の動画を再生中' : (S.info.video ? S.info.video.name : '');
  byId('cardPreview').classList.toggle('is-rough', on);
  updateTime();
}

/* ---------- ドロップ・アップロード ---------- */
async function detectSchema(file) {
  const head = await file.slice(0, 8192).text();
  let m = head.match(/"schema"\s*:\s*"([^"]{1,80})"/);
  if (!m && file.size < 40 * 1048576) {
    try { const d = JSON.parse(await file.text()); if (d && typeof d.schema === 'string') return d.schema; } catch (e) { return ''; }
  }
  return m ? m[1] : '';
}
async function upload(field, kind, file) {
  const lim = S.limits[kind];
  if (lim && file.size > lim) { toast(file.name + ' は大きすぎます(上限 ' + fmtBytes(lim) + ')'); return false; }
  const r = await api('/api/upload?kind=' + kind + '&name=' + encodeURIComponent(file.name), { raw: file });
  setVal(field, r.path);
  S.uploaded[r.path] = file.name;
  return true;
}
async function handleFiles(files) {
  notice(byId('dropNotice'), '');
  const changed = [];
  for (const f of files) {
    const ext = (f.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
    try {
      if (ext === '.srt' || ext === '.vtt') { if (await upload('srt', 'srt', f)) changed.push('srt'); }
      else if (ext === '.json') {
        const sc = await detectSchema(f);
        if (sc.startsWith('youtube-tools-transcript/')) { if (await upload('transcript', 'transcript', f)) changed.push('transcript'); }
        else if (sc.startsWith('youtube-tools-cut-plan/')) { if (await upload('plan', 'plan', f)) changed.push('plan'); }
        else toast(f.name + ': 文字起こし(transcript/v1)でも cut-plan でもない JSON です');
      } else if (VIDEO_EXTS.includes(ext)) droppedVideo(f);
      else toast('このファイルは使えません: ' + f.name);
    } catch (e) { toast(f.name + ': ' + e.message); }
  }
  if (changed.length) await inspect(changed.concat(['video'].filter(x => val(x) && !changed.includes(x) && !S.info.video)));
}
function droppedVideo(f) {
  const cands = [S.info.transcript && S.info.transcript.mediaPath, S.info.plan && S.info.plan.mediaPath].filter(Boolean);
  const hit = cands.find(p => baseName(p).toLowerCase() === f.name.toLowerCase());
  if (hit) {
    setVal('video', hit);
    toast('文字起こし(cut-plan)に書かれた場所の動画を使います: ' + hit);
    inspect(['video']);
    return;
  }
  if (S.info.video && S.info.video.name.toLowerCase() === f.name.toLowerCase()) { toast('その動画はもう入っています'); return; }
  notice(byId('dropNotice'), '動画「' + f.name + '」は、ブラウザからは置き場所が分かりません。エクスプローラーで動画を右クリック →「パスのコピー」を選び、上の「動画」の欄に貼り付けてください(動画はコピーせず、その場所のまま使います)。', '');
  byId('inVideo').focus();
}

/* ---------- 手順の表示(ヘッダー) ---------- */
function syncSteps() {
  const done = { in: !!S.info.video, cut: !!S.plan && S.planSig === specSig(), out: !!S.result };
  const cur = !done.in ? 'in' : !done.cut ? 'cut' : 'out';
  $$('#steps .ui-tab').forEach(b => {
    const s = b.dataset.step;
    b.setAttribute('aria-pressed', String(s === cur));
    b.classList.toggle('is-done', !!done[s]);
    b.querySelector('.ui-tab-n').textContent = done[s] ? '✓' : String({ in: 1, cut: 2, out: 3 }[s]);
  });
}

/* ---------- 他のツール ---------- */
async function loadSiblings() {
  const nav = $('[data-ui-toolnav]');
  let ports = null;
  try {
    const j = await api('/api/siblings');
    ports = j.tools;
    if (window.UIKit && UIKit.tools.setPaths) UIKit.tools.setPaths(j.paths);   // 入口の統合サーバーに取り込まれたツールの場所(/studio/ など)
  } catch (e) { ports = null; }
  S.ports = ports;
  if (!window.UIKit || !nav) return;
  UIKit.tools.render(nav, { current: 'cut2resolve', ports: ports || undefined });
  if (ports) {
    $$('a', nav).forEach((a, i) => {
      const t = UIKit.tools.list[i];
      if (t && t.id !== 'cut2resolve' && !ports[t.id]) {
        a.classList.add('c2r-tool-off');
        a.title = '起動していないようです(既定のポートで開きます。start.bat で起動してから開いてください)';
        const small = a.querySelector('small');
        if (small) small.textContent += '(起動していません)';
      }
    });
  }
  for (const f of ['video']) if (S.info[f]) setStatus(f, 'ok', summarize(f, S.info[f]), statusExtra(f, S.info[f]));
}

/* ---------- イベント ---------- */
function bind() {
  byId('ver').textContent = 'v' + APP_VERSION;
  for (const f of FIELDS) {
    const inp = byId(INPUT_ID[f]);
    inp.addEventListener('change', () => { saveForm(); if (val(f) !== (S.inspected[f] || '')) inspect([f]); });
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); inspect([f]); } });
    inp.addEventListener('input', () => markStale());
  }
  $$('[data-clear]').forEach(b => b.addEventListener('click', () => {
    const f = b.dataset.clear; setVal(f, ''); S.info[f] = null; S.inspected[f] = ''; setStatus(f, ''); saveForm(); afterInputs();
  }));
  byId('btnInspect').addEventListener('click', () => { notice(byId('linkNotice'), ''); inspect(); });
  $$('#modes button').forEach(b => b.addEventListener('click', () => { S.mode = b.dataset.mode; syncMode(); saveForm(); markStale(); }));
  $$('#keepSrc button').forEach(b => b.addEventListener('click', () => { S.keepSource = b.dataset.src; syncMode(); saveForm(); markStale(); }));
  $$('#listKind button').forEach(b => b.addEventListener('click', () => { S.listKind = b.dataset.kind; syncMode(); saveForm(); markStale(); }));
  byId('handles').addEventListener('input', () => { S.handlesTouched = true; });
  byId('silenceExtra').addEventListener('change', () => syncMode());
  for (const id of PERSIST) {
    const e = byId(id);
    e.addEventListener('change', () => { saveForm(); markStale(); });
    if (e.tagName === 'TEXTAREA' || e.type === 'number' || e.type === 'text') e.addEventListener('input', () => markStale());
  }
  byId('btnPlan').addEventListener('click', runPlan);
  byId('btnBuild').addEventListener('click', () => runBuild(false));
  byId('btnOpen').addEventListener('click', async () => {
    if (!S.result) return;
    try { await api('/api/open-folder', { body: { path: S.result.outDir } }); } catch (e) { toast(e.message); }
  });
  byId('btnCopyDir').addEventListener('click', async () => {
    if (!S.result) return;
    try { await navigator.clipboard.writeText(S.result.outDir); toast('フォルダのパスをコピーしました'); }
    catch (e) { toast('コピーできませんでした: ' + S.result.outDir); }
  });
  byId('btnPlayRough').addEventListener('click', () => setRough(!S.rough));
  // ドロップ
  const drop = byId('drop'), fileIn = byId('fileIn');
  drop.addEventListener('click', () => fileIn.click());
  drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileIn.click(); } });
  fileIn.addEventListener('change', () => { handleFiles(Array.from(fileIn.files || [])); fileIn.value = ''; });
  let dragDepth = 0;
  window.addEventListener('dragenter', e => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) { dragDepth++; drop.classList.add('over'); } });
  window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) drop.classList.remove('over'); });
  window.addEventListener('dragover', e => { e.preventDefault(); });   // ファイルを落としたときにブラウザがそのファイルを開かないように
  window.addEventListener('drop', e => {
    e.preventDefault(); dragDepth = 0; drop.classList.remove('over');
    const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
    if (files.length) handleFiles(files);
  });
  // 手順
  $$('#steps .ui-tab').forEach(b => b.addEventListener('click', () => {
    const target = { in: 'cardIn', cut: 'cardCut', out: 'cardOut' }[b.dataset.step];
    byId(target).scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  // プレビュー
  player.addEventListener('play', () => { document.body.classList.add('is-playing'); cancelAnimationFrame(S.raf); S.raf = requestAnimationFrame(loop); });
  player.addEventListener('pause', () => { document.body.classList.remove('is-playing'); updateTime(); });
  player.addEventListener('seeked', updateTime);
  player.addEventListener('timeupdate', updateTime);
  player.addEventListener('loadedmetadata', updateTime);
  player.addEventListener('error', () => {
    if (!player.getAttribute('src')) return;
    const m = byId('playerMsg');
    m.textContent = 'このブラウザでは再生できない形式です(H.265・一部の mkv など)。試算とパック作成はできます。';
    m.hidden = false;
  });
  byId('btnPlay').addEventListener('click', togglePlay);
  byId('btnPrevKeep').addEventListener('click', () => jumpKeep(-1));
  byId('btnNextKeep').addEventListener('click', () => jumpKeep(1));
  byId('cutView').addEventListener('change', () => { skipRemoved(); byId('cardPreview').classList.toggle('is-cutview', byId('cutView').checked); });
  const tl = byId('timeline');
  const seekFromEvent = (e, box, toCut) => {
    const r = box.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    if (toCut) { if (S.plan) seekTo(S.rough ? frac * S.plan.keptSec : sourceTimeFromCut(frac * S.plan.keptSec)); }
    else if (!S.rough) seekTo(frac * (S.dur || player.duration || 0));
  };
  let dragging = null;
  tl.addEventListener('pointerdown', e => { dragging = tl; tl.setPointerCapture(e.pointerId); seekFromEvent(e, tl, false); });
  byId('afterBar').addEventListener('pointerdown', e => { dragging = byId('afterBar'); dragging.setPointerCapture(e.pointerId); seekFromEvent(e, dragging, true); });
  window.addEventListener('pointermove', e => { if (dragging) seekFromEvent(e, dragging, dragging !== tl); });
  window.addEventListener('pointerup', () => { dragging = null; });
  tl.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); seekTo(player.currentTime + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 5 : 1)); }
  });
  byId('keepRows').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-i]'); if (!tr) return;
    const k = S.keepsSec[+tr.dataset.i]; if (k) { if (S.rough) setRough(false); seekTo(k[0]); }
  });
  byId('keepRows').addEventListener('keydown', e => { if (e.key === 'Enter') e.target.click(); });
  // キー操作(入力欄・ボタンの上では使わない)
  window.addEventListener('keydown', e => {
    const t = e.target;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (t && (t.closest('input,textarea,select,[contenteditable],dialog') || (t.tagName === 'BUTTON' && (e.key === ' ' || e.key === 'Enter')))) return;
    if (e.key === ' ' || e.key === 'k' || e.key === 'K') { e.preventDefault(); togglePlay(); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { if (!player.src) return; e.preventDefault(); seekTo(player.currentTime + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 5 : 1)); }
    else if (e.key === 'c' || e.key === 'C') { const c = byId('cutView'); c.checked = !c.checked; c.dispatchEvent(new Event('change')); toast(c.checked ? 'カット後の見え方で再生します' : '元の動画のまま再生します', 1800); }
    else if (e.key === '[') jumpKeep(-1);
    else if (e.key === ']') jumpKeep(1);
  });
  // 画面を閉じる前の確認(書き出し中)
  window.addEventListener('beforeunload', e => { if (S.job) { e.preventDefault(); e.returnValue = ''; } });
}

/* ---------- 起動 ---------- */
function applyUrlParams() {
  const q = new URLSearchParams(location.search);
  const given = FIELDS.filter(f => q.has(f === 'srt' ? 'srt' : f));
  if (!given.length) return false;
  for (const f of FIELDS) setVal(f, q.get(f) || '');   // リンクで来たときは、前回の入力を混ぜない
  notice(byId('linkNotice'), '他のツールのリンクから入力欄を埋めました。内容を確かめて「読み込む」を押してください(自動では読み込みません)。', 'info');
  try { history.replaceState(null, '', location.pathname); } catch (e) { /* 何もしない */ }
  return true;
}

async function start() {
  bind();
  const restored = loadForm();
  const fromLink = applyUrlParams();
  syncMode();
  syncSteps();
  try {
    const p = await api('/api/ping');
    if (p.app !== 'cut2resolve') throw new Error('このアドレスは cut2resolve ではありません');
    if (p.version !== APP_VERSION) showErr('画面(v' + APP_VERSION + ')とサーバー(v' + p.version + ')の版が違います。黒い画面を閉じて start.bat で起動し直してください');
    S.state = await api('/api/state');
    S.limits = S.state.uploadLimits || {};
    if (!S.state.ffmpeg || !S.state.ffprobe) showErr('ffmpeg / ffprobe が見つかりません。README の「準備」を見てインストールし、黒い画面を開き直してください');
    if (S.state.job) toast('前の処理(' + S.state.job.kind + ')がまだ動いています');
  } catch (e) { showErr(e.message); }
  loadSiblings();
  if (restored && !fromLink && FIELDS.some(f => val(f))) inspect();   // 前回の自分の入力は読み込み直す(リンクで来たときはボタンを押すまで読まない)
  else afterInputs();
}
start();
})();
