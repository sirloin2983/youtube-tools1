/* lite.js — 友人用 文字起こし簡易版の画面(docs/plan/friend-lite-plan.md・.design/friend-transcribe-lite/DESIGN_BRIEF.md)。
   一本道: 1 読み込み → 2 文字起こし中 → 3 校正 → 4 書き出し(どこへでも戻れる)。サーバーは「編集」と同じ(文書の保存・ジョブ)+ /api/lite/…(ed_lite.py)。
   決まり: API の URL は apiUrl() だけで作る(入口の /transcribe/ の下でも単体でも動く)・書き込みは合言葉(X-YTT-Token)を付ける・
   外から来る文字(行・話者・ファイル名)は textContent で入れる(innerHTML に入れない)・再生キーは ui-kit の共通の再生キー(編集と同じ割り当て) */
'use strict';

const BASE = location.pathname.replace(/\/[^/]*$/, '');
const apiUrl = path => BASE + path;
const TOKEN = (document.querySelector('meta[name="ytt-token"]') || {}).content || '';
const $ = s => document.querySelector(s);
const LS = { job: 'lite.job', doc: 'lite.doc', step: 'lite.step' };
const LONG_NOTE = 10 * 60, LONG_ASK = 30 * 60;   // 10 分超は注意・30 分超は確認(どちらも続けられる。上限なし)
const NUDGE = 0.1, MIN_LEN = 0.1;

const L = {
  step: 'load', st: null, file: null, jobId: '', doc: null, tid: '', base: null, cur: 0,
  undo: [], redo: [], typing: null, dirty: false, saving: false, saveTimer: 0, conflict: false,
  played: new Set(), ops: [], keymap: null, exporting: false, lastExport: null
};

/* ---------- 小道具 ---------- */
function lsGet(k){ try { return localStorage.getItem(k) || ''; } catch { return ''; } }
function lsSet(k, v){ try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch { /* 使えない環境 */ } }
function fmtT(t, ms){
  t = Math.max(0, Number(t) || 0);
  const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
  const ss = ms ? s.toFixed(1).padStart(4, '0') : String(Math.floor(s)).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}
function fmtMin(sec){ const m = Math.round((sec || 0) / 60); return m >= 60 ? `${Math.floor(m / 60)} 時間 ${m % 60} 分` : `${m} 分`; }
function r2(x){ return Math.round(x * 100) / 100; }
function el(tag, cls, text){ const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function toast(msg, kind, ms){ if (window.UIKit && UIKit.toast) UIKit.toast(msg, { kind: kind || '', ms }); }
function show(node, on){ node.hidden = !on; }

async function api(path, opt = {}){
  const init = { cache: 'no-store', method: opt.method || 'GET' };
  if (opt.body !== undefined){ init.method = opt.method || 'POST'; init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(opt.body); }
  if (TOKEN && init.method !== 'GET') init.headers = { ...(init.headers || {}), 'X-YTT-Token': TOKEN };
  let r;
  try { r = await fetch(apiUrl(path), init); } catch { const e = new Error('ツールにつながりません。黒い画面(start.bat の窓)が閉じていないか確かめて、閉じていたら start.bat をもう一度開いてください'); e.code = 'offline'; throw e; }
  const j = await r.json().catch(() => ({}));
  if (!r.ok){ const e = new Error(j.message || ('エラー ' + r.status)); e.code = j.error; e.status = r.status; throw e; }
  return j;
}

/* 失敗の文を、次にやることが分かる平易な文に(ブリーフの原則 9) */
const NEXT_STEP = {
  no_ffmpeg: '動画を読む部品(ffmpeg)が見つかりません。この窓と黒い画面を閉じて、start.bat をもう一度開いてください(足りない部品を準備します)。',
  no_whisper: '文字起こしの部品が入っていません。start.bat をもう一度開いてください(準備のやり直しをします)。',
  gpu_failed: 'GPU で処理できませんでした。NVIDIA のドライバを新しくしてから(「GeForce Experience」か NVIDIA のサイトのドライバのページ)、もう一度始めてください。',
  model_failed: '文字起こしのモデルを読み込めませんでした。初めての時はインターネットからモデルを取ってきます。つながっているか確かめて、もう一度始めてください。',
  no_memory: 'メモリが足りません。ほかのアプリ(ゲーム・動画編集ソフトなど)を閉じてから、もう一度始めてください。',
  no_audio: 'この動画には音が入っていません。別の動画を選んでください。',
  bad_ext: '動画ファイルではないようです。mp4・mkv・mov などの動画を選んでください。',
  no_file: '動画が見つかりません。動かしたり名前を変えたりしていないか確かめてください。',
  source_missing: '元の動画が見つかりません。動かしたり名前を変えたりした場合は、元の場所・名前に戻してください。',
  no_space: 'ディスクの空きが足りません。「ファイルを選ぶ…」から選ぶと、動画を写さずに使えます。',
  pick_unavailable: 'ファイルを選ぶ窓を開けませんでした。動画をこの画面にドロップしてください。'
};
function friendly(e){ const next = NEXT_STEP[e && e.code]; return next ? next + (e.message && !next.includes(e.message) ? `\n(くわしく: ${e.message})` : '') : (e && e.message) || String(e); }
function showErr(node, e){ node.textContent = friendly(e); node.hidden = false; }

/* ---------- 手順(4 つの段) ---------- */
const STEPS = ['load', 'run', 'proof', 'export'];
function setStep(name){
  L.step = name;
  lsSet(LS.step, name);
  for (const s of STEPS) show($('#st' + s[0].toUpperCase() + s.slice(1)), s === name);
  document.querySelectorAll('.lt-steps button').forEach(b => {
    const s = b.dataset.step;
    b.toggleAttribute('aria-current', s === name);
    if (s === name) b.setAttribute('aria-current', 'step');
    b.disabled = !(s === 'load' || (s === 'run' && L.jobId) || ((s === 'proof' || s === 'export') && L.doc));
    b.classList.toggle('done', STEPS.indexOf(s) < STEPS.indexOf(name) && !b.disabled);
  });
  if (window.UIKit && UIKit.keybar){
    if (name === 'proof') UIKit.keybar.set([{ k: 'Space', l: '再生・停止' }, { k: 'Enter', l: '確認して次へ' }, { k: '↑↓', l: '行の移動' }, { k: '1〜9', l: '話者' }, { k: 'I / O', l: '今を開始/終了に' }, { k: 'Ctrl+Z', l: '取り消し' }]);
    else UIKit.keybar.clear();
  }
  if (name !== 'proof'){ const v = $('#ltVideo'); if (!v.paused) v.pause(); }
  if (name === 'export') renderExportSummary();
  if (name === 'proof') requestAnimationFrame(() => focusRow(L.cur, false));
}
document.querySelectorAll('.lt-steps button').forEach(b => b.addEventListener('click', () => { if (!b.disabled) setStep(b.dataset.step); }));

/* ---------- 1 読み込み ---------- */
async function loadState(){
  L.st = await api('/api/lite/state');
  const dl = $('#ltStreamerList'); dl.textContent = '';
  const seen = new Set();
  const add = n => { if (!n || seen.has(n)) return; seen.add(n); const o = document.createElement('option'); o.value = n; dl.appendChild(o); };
  (L.st.settings.streamers || []).forEach(add);
  (L.st.groups || []).forEach(g => (g.names || []).forEach(add));
  if (!$('#ltStreamer').value && L.st.settings.streamers[0]) $('#ltStreamer').value = L.st.settings.streamers[0];
  $('#ltWorker').value = L.st.settings.worker || '';
  $('#ltRuleList').textContent = '';
  L.st.rules.forEach(r => $('#ltRuleList').appendChild(el('li', '', r)));
  renderWorks();
  if (!L.st.ffmpeg) showErr($('#ltLoadErr'), { code: 'no_ffmpeg' });
  else if (!L.st.fasterWhisper) showErr($('#ltLoadErr'), { code: 'no_whisper' });
  updateStart();
}

function renderWorks(){
  const box = $('#ltWorks'); box.textContent = '';
  const ws = (L.st && L.st.works) || [];
  show($('#ltResume'), ws.length > 0);
  for (const w of ws.slice(0, 6)){
    const b = el('button', 'lt-work'); b.type = 'button';
    const main = el('div', 'lt-w-main');
    main.appendChild(el('div', 'lt-w-title', w.title || '(題名なし)'));
    const sub = [w.streamer, `確認済み ${w.checked}/${w.rows} 行`, w.exportedAt ? '書き出し済み' : '', w.mediaOk ? '' : '動画が見つかりません'].filter(Boolean).join(' ・ ');
    main.appendChild(el('div', 'lt-w-sub', sub));
    b.appendChild(main);
    b.appendChild(el('span', 'btn sm', '開く'));
    b.addEventListener('click', () => openDoc(w.id).catch(e => { showErr($('#ltLoadErr'), e); }));
    box.appendChild(b);
  }
}

function setFile(f){
  L.file = f;
  show($('#ltFile'), !!f);
  $('#ltFileName').textContent = f ? f.name : '';
  $('#ltFileLen').textContent = f && f.durationSec ? `長さ ${fmtT(f.durationSec)}` : '';
  const warn = $('#ltLenWarn');
  if (f && f.durationSec > LONG_NOTE){
    warn.textContent = `${fmtMin(f.durationSec)}の長い動画です。文字起こしと校正に時間がかかります(GPU なら動画の長さの数分の1ほど)。`;
    warn.hidden = false;
  } else warn.hidden = true;
  updateStart();
}

function updateStart(){
  const ok = !!(L.file && $('#ltStreamer').value.trim() && L.st && L.st.ffmpeg && L.st.fasterWhisper);
  $('#ltStart').disabled = !ok;
  $('#ltStartHint').textContent = ok ? '' : (!L.file ? '動画を選んでください' : !$('#ltStreamer').value.trim() ? '配信者を選んでください' : '');
}

async function probe(path){
  $('#ltLoadErr').hidden = true;
  const p = await api('/api/lite/probe', { body: { path } });
  setFile({ path, name: p.name, durationSec: p.durationSec });
}

function upload(file){
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('POST', apiUrl('/api/lite/upload?name=' + encodeURIComponent(file.name)));
    if (TOKEN) x.setRequestHeader('X-YTT-Token', TOKEN);
    x.setRequestHeader('Content-Type', 'application/octet-stream');
    const bar = $('#ltUpBar'); bar.hidden = false; bar.firstElementChild.style.width = '0';
    x.upload.onprogress = ev => { if (ev.lengthComputable) bar.firstElementChild.style.width = (ev.loaded / ev.total * 100).toFixed(1) + '%'; };
    x.onload = () => {
      bar.hidden = true;
      let j = {}; try { j = JSON.parse(x.responseText); } catch { /* 空 */ }
      if (x.status >= 200 && x.status < 300) resolve(j);
      else { const e = new Error(j.message || ('エラー ' + x.status)); e.code = j.error; reject(e); }
    };
    x.onerror = () => { bar.hidden = true; const e = new Error('受け取りが途中で切れました'); e.code = 'offline'; reject(e); };
    x.send(file);
  });
}

async function takeDropped(files){
  const f = files && files[0];
  if (!f) return;
  $('#ltLoadErr').hidden = true;
  try {
    toast(`「${f.name}」を読み込んでいます`, 'info');
    const r = await upload(f);
    await probe(r.path);
  } catch (e){ showErr($('#ltLoadErr'), e); }
}

(function wireDrop(){
  const drop = $('#ltDrop');
  ['dragenter', 'dragover'].forEach(t => document.addEventListener(t, e => { if (L.step !== 'load') return; e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'dragend'].forEach(t => document.addEventListener(t, e => { if (!e.relatedTarget) drop.classList.remove('over'); }));
  document.addEventListener('drop', e => {
    e.preventDefault(); drop.classList.remove('over');
    if (L.step === 'load') takeDropped(e.dataTransfer && e.dataTransfer.files);
    else toast('動画は「1 読み込み」でドロップしてください', 'info');
  });
})();

$('#ltPick').addEventListener('click', async () => {
  try {
    const r = await api('/api/pick', { body: { kind: 'file' } });
    if (r.path) await probe(r.path);
  } catch (e){ showErr($('#ltLoadErr'), e); }
});
$('#ltStreamer').addEventListener('input', updateStart);
$('#ltWorker').addEventListener('change', () => { api('/api/lite/settings', { body: { worker: $('#ltWorker').value } }).catch(() => {}); });

$('#ltStart').addEventListener('click', async () => {
  if (!L.file) return;
  if (L.file.durationSec > LONG_ASK){
    const go = await UIKit.dialog.confirm({ title: '長い動画です', body: `${fmtMin(L.file.durationSec)}あります。文字起こしにも校正にも時間がかかります。途中でやめても、閉じても、次に開いたときに続きから進められます。始めますか?`, ok: '始める', cancel: 'やめる' });
    if (!go) return;
  }
  $('#ltStart').disabled = true;
  try {
    const job = await api('/api/lite/start', { body: { path: L.file.path, streamer: $('#ltStreamer').value.trim(), sourceUrl: $('#ltUrl').value.trim() } });
    L.jobId = job.id; lsSet(LS.job, job.id);
    $('#ltRunTitle').textContent = L.file.name;
    startRun();
  } catch (e){ showErr($('#ltLoadErr'), e); updateStart(); }
});

/* ---------- 2 文字起こし中 ---------- */
let runTimer = 0, runT0 = 0;
function startRun(){
  runT0 = Date.now();
  $('#ltRunErr').hidden = true; show($('#ltRunBack'), false); show($('#ltCancel'), true);
  $('#ltRunBar').style.width = '0';
  setStep('run');
  clearInterval(runTimer);
  runTimer = setInterval(pollRun, 1000);
  pollRun();
}
async function pollRun(){
  let j;
  try { j = (await api('/api/jobs')).jobs.find(x => x.id === L.jobId); } catch (e){ $('#ltRunPhase').textContent = friendly(e); return; }
  if (!j){ clearInterval(runTimer); L.jobId = ''; lsSet(LS.job, ''); runFailed({ message: 'ツールを起動し直したため、文字起こしが止まりました。もう一度始めてください。' }); return; }
  $('#ltRunTitle').textContent = j.title || $('#ltRunTitle').textContent;
  $('#ltRunPhase').textContent = j.phase || '';
  const p = Math.max(0, Math.min(1, j.progress || 0));
  $('#ltRunBar').style.width = (p * 100).toFixed(1) + '%';
  const el2 = (Date.now() - runT0) / 1000;
  $('#ltRunLeft').textContent = p > 0.03 && j.state === 'running' ? `残り およそ ${fmtMin(el2 / p * (1 - p))}` : '';
  $('#ltRunDevice').textContent = j.device === 'cuda' ? 'GPU で処理しています' : j.device === 'cpu' ? 'CPU で処理しています(GPU より時間がかかります)' : '';
  if (j.state === 'done' && j.tid){
    clearInterval(runTimer); L.jobId = ''; lsSet(LS.job, '');
    (j.warnings || []).forEach(w => toast(w, 'info', 6000));
    await openDoc(j.tid);
  } else if (j.state === 'error'){
    clearInterval(runTimer); L.jobId = ''; lsSet(LS.job, '');
    runFailed({ message: j.error || '失敗しました', code: guessCode(j.error) });
  } else if (j.state === 'cancelled'){
    clearInterval(runTimer); L.jobId = ''; lsSet(LS.job, '');
    toast('文字起こしをやめました', 'info'); setStep('load');
  }
}
function guessCode(msg){
  msg = String(msg || '');
  if (/GPU/.test(msg)) return 'gpu_failed';
  if (/メモリ/.test(msg)) return 'no_memory';
  if (/モデル/.test(msg)) return 'model_failed';
  if (/ffmpeg/.test(msg)) return 'no_ffmpeg';
  return '';
}
function runFailed(e){ showErr($('#ltRunErr'), e); show($('#ltCancel'), false); show($('#ltRunBack'), true); }
$('#ltCancel').addEventListener('click', async () => {
  if (!L.jobId) return;
  try { await api('/api/transcribe/cancel', { body: { id: L.jobId } }); $('#ltRunPhase').textContent = 'やめています…'; } catch (e){ toast(friendly(e), 'err'); }
});
$('#ltRunBack').addEventListener('click', () => setStep('load'));

/* ---------- 3 校正 ---------- */
const video = $('#ltVideo');
function rows(){ return L.doc ? L.doc.segments : []; }
function spk(id){ return (L.doc.speakers || []).find(s => s.id === id); }
function nextId(){ return 'l' + Math.random().toString(36).slice(2, 9); }

async function openDoc(tid){
  const d = await api('/api/transcript?id=' + encodeURIComponent(tid));
  d.segments = (d.segments || []).slice().sort((a, b) => a.start - b.start || a.end - b.end);
  d.speakers = d.speakers || [];
  if (!d.speakers.length){   // 簡易版より前の文書など: 既定の話者を必ず入れる(ブリーフの原則 3)
    const pal = L.st ? L.st.palette : { text: [{ hex: '#FFE600' }], outline: [{ hex: '#000000' }] };
    d.speakers = [{ id: 'A', name: (d.lite && d.lite.streamer) || '話者1', color: pal.text[0].hex, outline: pal.outline[0].hex }];
  }
  L.doc = d; L.tid = tid; L.base = d.updatedAt; L.undo = []; L.redo = []; L.played = new Set(); L.conflict = false;
  for (const g of d.segments) if (!d.speakers.some(s => s.id === g.speaker)) g.speaker = d.speakers[0].id;
  lsSet(LS.doc, tid);
  video.src = apiUrl('/media?id=' + encodeURIComponent(tid));
  L.cur = Math.max(0, d.segments.findIndex(g => g.proofed !== true));
  if (L.cur < 0) L.cur = 0;
  $('#ltConflict').hidden = true;
  renderSpeakers(); renderRows();
  setSave('');
  setStep('proof');
}

function setSave(state){
  const n = $('#ltSave');
  n.dataset.state = state;
  n.textContent = { saving: '保存中…', ok: '保存しました', err: '保存できませんでした', dirty: '保存待ち' }[state] || '';
}

/* 元に戻す: 文書の行と話者の控え(最大 100) */
function snap(){ return JSON.stringify({ s: L.doc.segments, p: L.doc.speakers }); }
function pushUndo(){ L.undo.push(snap()); if (L.undo.length > 100) L.undo.shift(); L.redo = []; }
function restore(json){ const o = JSON.parse(json); L.doc.segments = o.s; L.doc.speakers = o.p; L.cur = Math.min(L.cur, Math.max(0, o.s.length - 1)); renderSpeakers(); renderRows(); markDirty(); }
function undo(){ if (!L.undo.length) return toast('取り消せる操作はありません', 'info'); L.redo.push(snap()); restore(L.undo.pop()); logOp({ op: 'undo' }); }
function redo(){ if (!L.redo.length) return toast('やり直せる操作はありません', 'info'); L.undo.push(snap()); restore(L.redo.pop()); logOp({ op: 'redo' }); }

/* 作業の記録(edits.jsonl。サーバーが形を確かめる) */
function logOp(o){ L.ops.push(Object.assign({ t: Math.round(video.currentTime * 1000) / 1000 }, o)); }
async function flushOps(){
  if (!L.ops.length || !L.tid) return;
  const ops = L.ops.splice(0, 500);
  try { await api('/api/lite/ops', { body: { id: L.tid, ops } }); } catch { L.ops = ops.concat(L.ops).slice(-2000); }
}
setInterval(flushOps, 3000);

function markDirty(){
  L.dirty = true; setSave('dirty');
  clearTimeout(L.saveTimer);
  L.saveTimer = setTimeout(() => save(), 800);
  updateCount();
}
async function save(force){
  if (!L.doc || (!L.dirty && !force) || L.conflict) return;
  if (L.saving){ clearTimeout(L.saveTimer); L.saveTimer = setTimeout(() => save(force), 400); return; }
  L.saving = true; L.dirty = false; setSave('saving');
  try {
    const r = await api('/api/transcript?id=' + encodeURIComponent(L.tid), { method: 'PUT', body: { title: L.doc.title, speakers: L.doc.speakers, segments: L.doc.segments, baseUpdatedAt: L.base, force: force === 'force' } });
    L.base = r.updatedAt; setSave('ok');
  } catch (e){
    if (e.status === 409){ L.conflict = true; showConflict(); setSave('err'); }
    else { L.dirty = true; setSave('err'); toast(friendly(e), 'err'); }
  } finally { L.saving = false; }
}
function showConflict(){
  const box = $('#ltConflict'); box.textContent = '別の窓でこの作業が変えられました。どちらを残すか選んでください。 ';
  const a = el('button', 'btn sm', '別の窓の内容を読み込む'); a.type = 'button';
  a.addEventListener('click', () => openDoc(L.tid).catch(e => toast(friendly(e), 'err')));
  const b = el('button', 'btn sm', 'この画面の内容で上書き'); b.type = 'button';
  b.addEventListener('click', () => { L.conflict = false; box.hidden = true; save('force'); });
  box.append(a, ' ', b); box.hidden = false;
}
if (window.UIKit && UIKit.life) UIKit.life.onLeave(() => { if (L.dirty) save(); flushOps(); });
window.addEventListener('beforeunload', () => { if (L.dirty) save(); });

function updateCount(){
  const rs = rows(), ok = rs.filter(g => g.proofed === true).length;
  $('#ltCount').textContent = `確認済み ${ok}/${rs.length} 行`;
}

/* 話者 */
function paletteSelect(list, value, label){
  const s = el('select'); s.setAttribute('aria-label', label);
  for (const c of list){ const o = el('option', '', c.name); o.value = c.hex; s.appendChild(o); }
  if (!list.some(c => c.hex === value)){ const o = el('option', '', value); o.value = value; s.appendChild(o); }
  s.value = value; return s;
}
function renderSpeakers(){
  const box = $('#ltSpk'); box.textContent = '';
  const pal = L.st ? L.st.palette : { text: [], outline: [] };
  L.doc.speakers.forEach((s, i) => {
    box.appendChild(el('kbd', 'ui-kbd', String(i + 1)));
    const name = el('input'); name.value = s.name; name.maxLength = 30; name.setAttribute('aria-label', `話者 ${i + 1} の名前`);
    name.addEventListener('change', () => { const v = name.value.trim(); if (!v){ name.value = s.name; return; } pushUndo(); s.name = v; renderRows(); markDirty(); rememberStyle(s); });
    const sw = el('span', 'lt-swatch', 'あいう'); sw.style.setProperty('--c', s.color); sw.style.setProperty('--o', s.outline || '#000000'); sw.title = '字幕の見え方';
    const c = paletteSelect(pal.text, s.color, `話者 ${i + 1} の文字の色`);
    const o = paletteSelect(pal.outline, s.outline || '#000000', `話者 ${i + 1} のふちの色`);
    c.addEventListener('change', () => { pushUndo(); s.color = c.value; renderSpeakers(); renderRows(); markDirty(); rememberStyle(s); });
    o.addEventListener('change', () => { pushUndo(); s.outline = o.value; renderSpeakers(); renderRows(); markDirty(); rememberStyle(s); });
    box.append(name, sw, c, o);
  });
}
function rememberStyle(s){ api('/api/lite/settings', { body: { speakerStyles: { [s.name]: { color: s.color, outline: s.outline || '#000000' } } } }).then(r => { if (L.st) L.st.settings = r; }).catch(() => {}); }
$('#ltSpkAdd').addEventListener('click', () => {
  const name = $('#ltSpkNew').value.trim();
  if (!name) return toast('話者の名前を入れてください', 'info');
  if (L.doc.speakers.length >= 9) return toast('話者は 9 人までです', 'info');
  const used = new Set(L.doc.speakers.map(s => s.id));
  const id = 'ABCDEFGHI'.split('').find(x => !used.has(x)) || nextId().slice(0, 6);
  const saved = L.st && L.st.settings.speakerStyles[name];
  const pal = L.st.palette;
  const color = saved ? saved.color : (pal.text.find(c => !L.doc.speakers.some(s => s.color === c.hex)) || pal.text[0]).hex;
  pushUndo();
  L.doc.speakers.push({ id, name, color, outline: saved ? saved.outline : pal.outline[0].hex });
  $('#ltSpkNew').value = '';
  renderSpeakers(); renderRows(); markDirty();
});

/* 行 */
function renderRows(){
  const box = $('#ltRows'); box.textContent = '';
  const frag = document.createDocumentFragment();
  rows().forEach((g, i) => frag.appendChild(rowEl(g, i)));
  box.appendChild(frag);
  updateCount();
  markCur();
}
function rowEl(g, i){
  const r = el('div', 'lt-row' + (g.proofed ? ' ok' : '')); r.dataset.i = i; r.setAttribute('role', 'listitem'); r.tabIndex = -1;
  const s = spk(g.speaker); if (s) r.style.setProperty('--sp', s.color);
  const chk = el('button', 'lt-chk', '✓'); chk.type = 'button';
  chk.setAttribute('aria-pressed', g.proofed ? 'true' : 'false');
  chk.setAttribute('aria-label', g.proofed ? '確認済み(押すと未確認に戻す)' : '確認済みにする');
  chk.addEventListener('click', ev => { ev.stopPropagation(); select(i, false); setChecked(i, !g.proofed); });
  const t = el('div', 'lt-time');
  t.append(el('b', '', fmtT(g.start, true)), el('br'), el('span', '', '〜 ' + fmtT(g.end, true)));
  const sp = el('select', 'lt-sp'); sp.setAttribute('aria-label', '話者');
  L.doc.speakers.forEach((x, k) => { const o = el('option', '', `${k + 1} ${x.name}`); o.value = x.id; sp.appendChild(o); });
  sp.value = g.speaker;
  sp.addEventListener('change', () => setSpeaker(i, sp.value));
  sp.addEventListener('focus', () => select(i, false));
  const col = el('div');
  const ta = el('textarea', 'lt-text'); ta.rows = 1; ta.value = g.text || ''; ta.setAttribute('aria-label', `${i + 1} 行目の文字`); ta.spellcheck = false;
  ta.addEventListener('focus', () => { if (L.cur !== i) select(i, true); });
  ta.addEventListener('input', () => {
    if (L.typing !== i){ pushUndo(); L.typing = i; }
    clearTimeout(ta._t); ta._t = setTimeout(() => { if (L.typing === i) L.typing = null; }, 1200);
    const v = ta.value.replace(/[\r\n]+/g, ' ');
    if (v !== ta.value) ta.value = v;
    if (g.text !== v){ g.text = v; logOp({ op: 'text', row: g.id, len: v.length }); markDirty(); }
    autosize(ta);
  });
  ta.addEventListener('keydown', ev => {
    if (ev.isComposing || ev.keyCode === 229) return;
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.ctrlKey && !ev.altKey){ ev.preventDefault(); confirmNext(i, true); }
    else if (ev.key === 'Enter' && ev.ctrlKey){ ev.preventDefault(); splitRow(i, ta.selectionStart); }
    else if (ev.key === 'Escape'){ ev.preventDefault(); ta.blur(); focusRow(i, false); }
  });
  col.append(ta, el('span', 'lt-state', g.proofed ? '確認済み' : '未確認'));
  const tools = el('div', 'lt-rowtools');
  const mk = (label, title, fn) => { const b = el('button', 'btn ghost sm', label); b.type = 'button'; b.title = title; b.addEventListener('click', ev => { ev.stopPropagation(); fn(); }); return b; };
  tools.append(mk('ここで分ける', '文字のカーソルの位置と再生位置で、この行を2つに分ける(Ctrl+Enter)', () => splitRow(i, ta.selectionStart)),
               mk('次の行とつなげる', '次の行と1つにする', () => mergeRow(i)),
               mk('下に行を足す', 'この行のすぐ後に空の行を足す', () => addRow(i)),
               mk('行を消す', 'この行を消す(取り消しで戻せます)', () => deleteRow(i)));
  r.append(chk, t, sp, col, tools);
  r.addEventListener('click', ev => { if (ev.target.closest('button, select, textarea')) return; select(i, false); playFrom(g.start); });
  requestAnimationFrame(() => autosize(ta));
  return r;
}
function autosize(ta){ ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; }
function rowNode(i){ return $('#ltRows').children[i]; }
function markCur(){
  const box = $('#ltRows');
  for (const n of box.querySelectorAll('.lt-row.cur')) n.classList.remove('cur');
  const n = rowNode(L.cur); if (n) n.classList.add('cur');
}
function select(i, seek){
  const rs = rows(); if (!rs.length) return;
  L.cur = Math.max(0, Math.min(rs.length - 1, i));
  markCur();
  const n = rowNode(L.cur); if (n) n.scrollIntoView({ block: 'nearest' });
  if (seek){ const g = rs[L.cur]; if (video.currentTime < g.start || video.currentTime > g.end) seekTo(g.start); }
}
function focusRow(i, text){
  select(i, false);
  const n = rowNode(L.cur); if (!n) return;
  if (text) n.querySelector('.lt-text').focus(); else n.focus({ preventScroll: true });
}
function seekTo(t){ try { video.currentTime = Math.max(0, t); } catch { /* 読み込み前 */ } }
function playFrom(t){ seekTo(t); const p = video.play(); if (p && p.catch) p.catch(() => {}); }

function refreshRow(i){ const old = rowNode(i); if (!old) return renderRows(); const n = rowEl(rows()[i], i); old.replaceWith(n); markCur(); updateCount(); }

function setChecked(i, on){
  const g = rows()[i]; if (!g) return;
  if (!!g.proofed === on) return;
  pushUndo();
  if (on) g.proofed = true; else delete g.proofed;
  logOp(on ? { op: 'confirm', row: g.id, played: L.played.has(g.id) } : { op: 'unconfirm', row: g.id });
  refreshRow(i); markDirty();
}
function confirmNext(i, text){
  setChecked(i, true);
  const rs = rows();
  if (i + 1 < rs.length){ focusRow(i + 1, text); playFrom(rs[i + 1].start); }
  else { toast('最後の行です。よければ「書き出しへ」に進んでください', 'ok'); }
}
function setSpeaker(i, id){
  const g = rows()[i]; if (!g || g.speaker === id || !spk(id)) return;
  pushUndo(); g.speaker = id; logOp({ op: 'speaker', row: g.id, speaker: id }); refreshRow(i); markDirty();
}

/* 時刻: 前後の行と重ならないように入力のときに抑える(すでに重なっていた所は、それより悪くしない) */
function bounds(i){
  const rs = rows(), g = rs[i];
  const prevEnd = i > 0 ? rs[i - 1].end : 0;
  const nextStart = i + 1 < rs.length ? rs[i + 1].start : (video.duration || L.doc.duration || g.end + 3600);
  return { lo: Math.min(prevEnd, g.start), hi: Math.max(nextStart, g.end) };
}
function setEdge(i, edge, t, how){
  const g = rows()[i]; if (!g) return;
  const b = bounds(i);
  const v = edge === 'start' ? r2(Math.max(b.lo, Math.min(t, g.end - MIN_LEN))) : r2(Math.min(b.hi, Math.max(t, g.start + MIN_LEN)));
  if (v === g[edge]){ toast(edge === 'start' ? 'これ以上は前の行と重なります' : 'これ以上は次の行と重なります', 'info'); return; }
  pushUndo();
  logOp({ op: 'time', row: g.id, edge, from: g[edge], to: v, how });
  g[edge] = v;
  refreshRow(i); markDirty();
}
function nudge(edge, d){ const g = rows()[L.cur]; if (g) setEdge(L.cur, edge, g[edge] + d, 'nudge'); }

function splitRow(i, caret){
  const rs = rows(), g = rs[i]; if (!g) return;
  const text = g.text || '';
  let at = Number.isInteger(caret) && caret > 0 && caret < text.length ? caret : Math.floor(text.length / 2);
  const now = video.currentTime;
  const t = now > g.start + MIN_LEN && now < g.end - MIN_LEN ? now : (g.start + g.end) / 2;
  if (g.end - g.start < MIN_LEN * 2) return toast('短すぎて分けられません', 'info');
  pushUndo();
  const b = Object.assign({}, g, { id: nextId(), start: r2(t), text: text.slice(at).trim() });
  delete b.proofed;
  g.end = r2(t); g.text = text.slice(0, at).trim(); delete g.proofed;
  rs.splice(i + 1, 0, b);
  logOp({ op: 'split', row: g.id, with: b.id, at: r2(t) });
  renderRows(); markDirty(); focusRow(i + 1, true);
}
function mergeRow(i){
  const rs = rows(), g = rs[i], n = rs[i + 1];
  if (!g || !n) return toast('次の行がありません', 'info');
  pushUndo();
  g.end = Math.max(g.end, n.end); g.text = [g.text, n.text].filter(Boolean).join(' '); delete g.proofed;
  rs.splice(i + 1, 1);
  logOp({ op: 'merge', row: g.id, with: n.id });
  renderRows(); markDirty(); focusRow(i, true);
}
function addRow(i){
  const rs = rows(), g = rs[i]; if (!g) return;
  const nextStart = i + 1 < rs.length ? rs[i + 1].start : (video.duration || g.end + 2);
  if (nextStart - g.end < MIN_LEN * 2) return toast('次の行とのすきまがないので足せません。先にこの行の終わりを早めてください', 'info');
  pushUndo();
  const n = { id: nextId(), start: r2(g.end), end: r2(Math.min(nextStart, g.end + 2)), text: '', speaker: g.speaker, flag: '' };
  rs.splice(i + 1, 0, n);
  logOp({ op: 'add', row: n.id, start: n.start, end: n.end });
  renderRows(); markDirty(); focusRow(i + 1, true);
}
function deleteRow(i){
  const rs = rows(), g = rs[i]; if (!g) return;
  pushUndo(); rs.splice(i, 1);
  logOp({ op: 'delete', row: g.id });
  L.cur = Math.min(i, rs.length - 1);
  renderRows(); markDirty();
  toast('行を消しました', '', 0 || 4000);
}
function nextUnchecked(){
  const rs = rows();
  for (let k = 1; k <= rs.length; k++){ const j = (L.cur + k) % rs.length; if (rs[j].proofed !== true){ focusRow(j, false); seekTo(rs[j].start); return; } }
  toast('すべての行を確認しました', 'ok');
}

/* 再生位置: 今の行の印・確定の前に聞いたかの記録 */
video.addEventListener('timeupdate', () => {
  const t = video.currentTime;
  $('#ltNow').textContent = fmtT(t, true);
  const box = $('#ltRows');
  for (const n of box.querySelectorAll('.lt-row.playing')) n.classList.remove('playing');
  const rs = rows();
  const k = rs.findIndex(g => g.start <= t && t < g.end);
  if (k >= 0){ const n = rowNode(k); if (n) n.classList.add('playing'); if (!video.paused) L.played.add(rs[k].id); }
});
video.addEventListener('loadedmetadata', () => { $('#ltDur').textContent = '/ ' + fmtT(video.duration); });
video.addEventListener('error', () => { if (L.step === 'proof') toast(friendly({ code: 'source_missing' }), 'err'); });

$('#ltUndo').addEventListener('click', undo);
$('#ltRedo').addEventListener('click', redo);
$('#ltNextUn').addEventListener('click', nextUnchecked);
$('#ltToExport').addEventListener('click', () => setStep('export'));

const playKeys = window.UIKit && UIKit.keys ? UIKit.keys.playback({
  media: () => video, fps: () => 30, keymap: () => L.keymap, enabled: () => L.step === 'proof',
  onIn: () => { const g = rows()[L.cur]; if (g) setEdge(L.cur, 'start', video.currentTime, 'now'); },
  onOut: () => { const g = rows()[L.cur]; if (g) setEdge(L.cur, 'end', video.currentTime, 'now'); }
}) : () => false;

document.addEventListener('keydown', ev => {
  if (L.step !== 'proof' || !L.doc) return;
  if (document.querySelector('dialog[open]')) return;
  const typing = UIKit.keys.isTyping(ev.target);
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && !typing){
    const k = ev.key.toLowerCase();
    if (k === 'z' && !ev.shiftKey){ ev.preventDefault(); undo(); return; }
    if (k === 'y' || (k === 'z' && ev.shiftKey)){ ev.preventDefault(); redo(); return; }
  }
  if (typing || ev.ctrlKey || ev.altKey || ev.metaKey || ev.isComposing) return;
  if (playKeys(ev)) return;
  const k = ev.key;
  if (k === 'Enter'){ ev.preventDefault(); confirmNext(L.cur, false); }
  else if (k === 'ArrowDown'){ ev.preventDefault(); focusRow(L.cur + 1, false); }
  else if (k === 'ArrowUp'){ ev.preventDefault(); focusRow(L.cur - 1, false); }
  else if (/^[1-9]$/.test(k)){ const s = L.doc.speakers[+k - 1]; if (s){ ev.preventDefault(); setSpeaker(L.cur, s.id); } }
  else if (k === 'z' || k === 'Z'){ ev.preventDefault(); nudge('start', -NUDGE); }
  else if (k === 'x' || k === 'X'){ ev.preventDefault(); nudge('start', NUDGE); }
  else if (k === 'c' || k === 'C'){ ev.preventDefault(); nudge('end', -NUDGE); }
  else if (k === 'v' || k === 'V'){ ev.preventDefault(); nudge('end', NUDGE); }
  else if (k === 'n' || k === 'N'){ ev.preventDefault(); nextUnchecked(); }
  else if (k === 'e' || k === 'E' || k === 'F2'){ ev.preventDefault(); focusRow(L.cur, true); }
});

function renderKeys(){
  const km = UIKit.keys.playbackMap(L.keymap), kt = UIKit.keys.keyText;
  const list = [[kt(km.playPause), '再生・停止'], [`${kt(km.seekBack)} / ${kt(km.seekFwd)}`, '1秒戻る・進む(Shift で5秒)'],
    ['Enter', '確認済みにして次の行へ(文字を直している時も)'], ['↑ / ↓', '行の移動'], ['E', '文字を直す(Esc で戻る)'], ['1〜9', '話者を付ける'],
    [`${kt(km.markIn)} / ${kt(km.markOut)}`, '今の再生位置を開始/終了にする'], ['Z / X', '開始を 0.1 秒 早く/遅く'], ['C / V', '終了を 0.1 秒 早く/遅く'],
    ['Ctrl+Enter', '文字のカーソルの所で行を分ける'], ['N', '次の未確認の行へ'], ['Ctrl+Z / Ctrl+Y', '取り消し・やり直し']];
  const box = $('#ltKeys'); box.textContent = '';
  for (const [k, d] of list){ box.append(el('kbd', 'ui-kbd', k), el('span', '', d)); }
}

/* ---------- 4 書き出し ---------- */
function renderExportSummary(){
  if (!L.doc) return;
  const rs = rows(), ok = rs.filter(g => g.proofed === true).length;
  $('#ltExSummary').textContent = ok < rs.length
    ? `確認済み ${ok}/${rs.length} 行。まだ確認していない ${rs.length - ok} 行は、送る用ファイルでは使われません(書き出しはできます)。`
    : `すべての行(${rs.length} 行)を確認しました。`;
}
$('#ltExBack').addEventListener('click', () => setStep('proof'));
$('#ltExport').addEventListener('click', async () => {
  if (!L.doc || L.exporting) return;
  $('#ltExErr').hidden = true; show($('#ltDone'), false);
  L.exporting = true; $('#ltExport').disabled = true; show($('#ltExBarWrap'), true);
  try {
    clearTimeout(L.saveTimer); if (L.dirty) await save();
    if (L.conflict) throw new Error('別の窓との食い違いを先に解決してください(校正の画面の上の案内)');
    await flushOps();
    await api('/api/lite/export', { body: { id: L.tid } });
    for (;;){
      await new Promise(r => setTimeout(r, 800));
      const t = await api('/api/lite/export?id=' + encodeURIComponent(L.tid));
      $('#ltExPhase').textContent = t.phase || '';
      if (t.state === 'done'){ exportDone(t.result); break; }
      if (t.state === 'error'){ const e = new Error(t.error); e.code = t.code; throw e; }
    }
  } catch (e){ showErr($('#ltExErr'), e); }
  finally { L.exporting = false; $('#ltExport').disabled = false; show($('#ltExBarWrap'), false); $('#ltExport').textContent = 'もう一度書き出す'; }
});
function exportDone(res){
  L.lastExport = res;
  $('#ltExPhase').textContent = '';
  $('#ltZipName').textContent = res.zipName;
  const w = $('#ltExWarn'); w.textContent = '';
  (res.warnings || []).forEach(x => { w.appendChild(el('li', '', x)); toast(x, 'info', 6000); });
  show($('#ltDone'), true);
  toast('書き出しました', 'ok');
  openFolder('send');
}
async function openFolder(what){ try { await api('/api/lite/open', { body: { id: L.tid, what } }); } catch (e){ toast(friendly(e), 'err'); } }
$('#ltOpenSend').addEventListener('click', () => openFolder('send'));
$('#ltOpenPack').addEventListener('click', () => openFolder('pack'));

/* ---------- 起動: 続きから ---------- */
(async function boot(){
  try {
    if (window.UIKit && UIKit.prefs && UIKit.prefs.available()){
      UIKit.prefs.get(['keymap']).then(p => { L.keymap = (p && p.keymap && p.keymap.playback) || null; renderKeys(); }).catch(() => {});
    }
    renderKeys();
    await loadState();
    const job = lsGet(LS.job);
    if (job){
      const j = (await api('/api/jobs')).jobs.find(x => x.id === job);
      if (j && ['queued', 'loading', 'extracting', 'running'].includes(j.state)){ L.jobId = job; $('#ltRunTitle').textContent = j.title || ''; startRun(); return; }
      if (j && j.state === 'done' && j.tid){ lsSet(LS.job, ''); await openDoc(j.tid); return; }
      lsSet(LS.job, '');
    }
    const tid = lsGet(LS.doc), step = lsGet(LS.step);
    if (tid && (step === 'proof' || step === 'export') && (L.st.works || []).some(w => w.id === tid)){
      await openDoc(tid);
      if (step === 'export') setStep('export');
      return;
    }
    setStep('load');
  } catch (e){ setStep('load'); showErr($('#ltLoadErr'), e); }
})();
