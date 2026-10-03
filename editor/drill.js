/* drill.js — 評価ドリルの画面(マスタープラン Q4。docs/plan/q3-q4-design.md の (c))。
   評価用の文書の未校正の行を乱数で 20 行(GET api/drill/pick)→ 1 行ずつ自動で再生 → 直して「済み」(POST api/drill/row。行ごとに保存)/「飛ばす」。
   決まり: API の URL は apiUrl() だけで作る(入口の /transcribe/ の下でも単体でも動く)・書き込みは合言葉(X-YTT-Token)を付ける・
   外から来る文字(行・話者・題名)は textContent で入れる(innerHTML に入れない)。
   キー: Space 再生・停止 / Ctrl+Enter 聞き直す / Enter 済み(文字を直している間も)/ Shift+Space 済み / D 飛ばす / 1〜9 話者 / E 文字を直す / Esc 文字の欄を抜ける */
'use strict';

const BASE = location.pathname.replace(/\/[^/]*$/, '');
const apiUrl = path => BASE + path;
const TOKEN = (document.querySelector('meta[name="ytt-token"]') || {}).content || '';
const $ = s => document.querySelector(s);
const video = $('#drVideo');
const TAGS = [['overlap', '#drTagOverlap'], ['bgm', '#drTagBgm'], ['unclear', '#drTagUnclear']];
const FROM_LABEL = { voice: '覚えた声', folder: 'メンバーのフォルダ', stream: '配信の文脈' };
const MAX_ROW_SEC = 600;

const D = { rows: [], docs: {}, i: 0, res: { done: 0, skip: 0, conflict: 0 }, shownAt: 0, sessionDocs: new Set(), endAt: null, busy: false, raf: 0, stTimer: 0 };

/* ---------- 小道具 ---------- */
function el(tag, cls, text){ const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function toast(msg, kind, ms){ if (window.UIKit && UIKit.toast) UIKit.toast(msg, { kind: kind || '', ms }); }
function show(node, on){ node.hidden = !on; }
function fmtT(t){ t = Math.max(0, Number(t) || 0); const m = Math.floor(t / 60), s = t % 60; return `${m}:${s.toFixed(1).padStart(4, '0')}`; }
function fmtDur(s){ s = Math.max(0, Math.round(s)); const m = Math.floor(s / 60); return m ? `${m}分${String(s % 60).padStart(2, '0')}秒` : `${s}秒`; }

async function api(path, opt = {}){
  const init = { cache: 'no-store', method: opt.method || 'GET' };
  if (opt.body !== undefined){ init.method = opt.method || 'POST'; init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(opt.body); }
  if (TOKEN && init.method !== 'GET') init.headers = { ...(init.headers || {}), 'X-YTT-Token': TOKEN };
  let r;
  try { r = await fetch(apiUrl(path), init); } catch { const e = new Error('ツールにつながりません。start.bat の窓が閉じていないか確かめてください'); e.code = 'offline'; throw e; }
  const j = await r.json().catch(() => ({}));
  if (!r.ok){ const e = new Error(j.message || ('エラー ' + r.status)); e.code = j.error; e.status = r.status; throw e; }
  return j;
}

/* ---------- 定点の「あと何分」と条件 ---------- */
function renderStatus(st){
  if (!st) return;
  const left = $('#drLeft'); left.textContent = '';
  if (st.leftSec > 0) left.append('定点まで ', el('b', '', `あと ${Math.ceil(st.leftSec / 60)} 分`));
  else left.append(el('b', '', '15 分に届きました'));
  left.append(`(校正済み ${fmtDur(st.proofedSec)} / 15 分・評価用 ${st.docs} 本・まだの行 ${st.pendingRows} 行)`);
  const pct = Math.min(100, st.proofedSec / st.goalSec * 100);
  $('#drBarFill').style.width = pct + '%'; $('#drBar').setAttribute('aria-valuenow', String(Math.round(pct)));
  const ul = $('#drConds'); ul.textContent = '';
  for (const c of st.conds || []){
    const li = el('li', ''); li.dataset.cond = c.key;
    li.append(el('span', '', `${c.label} ${c.have}/${c.need}${c.unit}`), el('span', 'pill ' + (c.ok ? 'ok' : 'wait'), c.ok ? '済み' : 'まだ'));
    if (c.items && c.items.length) li.title = c.items.join('・');
    ul.append(li);
  }
  if (st.ready) ul.append(el('li', 'hint', '条件がそろいました。編集の「精度」で基準を記録できます'));
}
async function loadStatus(){ try { renderStatus(await api('/api/drill/status')); } catch (e){ $('#drLeft').textContent = e.message; } }
function statusSoon(){ clearTimeout(D.stTimer); D.stTimer = setTimeout(loadStatus, 400); }

/* ---------- 始める ---------- */
async function start(){
  const b = $('#drGo'), again = $('#drAgain');
  b.disabled = again.disabled = true; $('#drStartNote').textContent = '行を選んでいます…';
  try {
    const r = await api('/api/drill/pick');
    renderStatus(r.status);
    D.rows = r.rows || []; D.docs = r.docs || {}; D.i = 0; D.res = { done: 0, skip: 0, conflict: 0 }; D.sessionDocs = new Set();
    $('#drStartNote').textContent = '';
    show($('#drEnd'), false);
    if (!D.rows.length){
      show($('#drStart'), false); show($('#drRun'), false); show($('#drEmpty'), true);
      $('#drEmptyText').textContent = !r.pool && !r.recent
        ? 'まだ校正していない評価用の行がありません。編集で文字起こしを「評価用にする」か、⚙ の「評価用のフォルダ」の動画を文字起こしすると、ここに出ます。'
        : `直前(10 分以内)に編集した評価用の文書 ${r.recent} 本は、開いている途中かもしれないので選んでいません。少し時間をおいてから、もう一度開いてください。`;
      return;
    }
    show($('#drStart'), false); show($('#drEmpty'), false); show($('#drRun'), true);
    showRow();
  } catch (e){ $('#drStartNote').textContent = e.message; }
  finally { b.disabled = again.disabled = false; }
}

/* ---------- 1 行 ---------- */
function cur(){ return D.rows[D.i]; }
function docOf(r){ return D.docs[r.id] || { title: '', speakers: [], candidates: [] }; }

function spkOptions(r){
  const doc = docOf(r), sel = $('#drSpk'); sel.textContent = '';
  sel.append(new Option('(話者なし)', ''));
  let n = 0;
  const names = new Set();
  for (const s of doc.speakers || []){ n++; names.add(String(s.name || '').normalize('NFKC').replace(/\s+/g, '').toLowerCase()); sel.append(new Option(`${n <= 9 ? n + ' ' : ''}${s.name || s.id}`, 'id:' + s.id)); }
  for (const c of doc.candidates || []){
    const k = String(c.name || '').normalize('NFKC').replace(/\s+/g, '').toLowerCase();
    if (!k || names.has(k)) continue;
    names.add(k); n++;
    sel.append(new Option(`${n <= 9 ? n + ' ' : ''}${c.name}(足す・${FROM_LABEL[c.from] || c.from})`, 'name:' + c.name));
  }
  sel.append(new Option('ほかの名前を入れる…', 'other'));
  sel.value = r.speaker && (doc.speakers || []).some(s => s.id === r.speaker) ? 'id:' + r.speaker : '';
  syncNewName();
}
function syncNewName(){ const on = $('#drSpk').value === 'other'; show($('#drSpkNew'), on); if (!on) $('#drSpkNew').value = ''; }

function showRow(){
  const r = cur(); if (!r) return finish();
  const doc = docOf(r);
  $('#drPos').textContent = `${D.i + 1} / ${D.rows.length}`;
  $('#drDoc').textContent = doc.title || doc.sourceName || ''; $('#drDoc').title = doc.sourceName || '';
  $('#drTime').textContent = `${fmtT(r.start)}〜${fmtT(r.end)}(${(r.end - r.start).toFixed(1)} 秒)`;
  $('#drText').value = r.text;
  for (const [t, sel] of TAGS) $(sel).checked = (r.tags || []).includes(t);
  spkOptions(r);
  show($('#drErr'), false);
  D.shownAt = Date.now();
  if (video.dataset.tid !== r.id){ video.dataset.tid = r.id; video.src = apiUrl('/media?id=' + encodeURIComponent(r.id)); }
  playRow();
  const ta = $('#drText'); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
}

/* その行だけを頭から鳴らして、終わりで止める(timeupdate は 4 回/秒なので、鳴っている間は描画ごとに見る) */
function playRow(){
  const r = cur(); if (!r) return;
  const go = () => {
    try { video.currentTime = r.start; } catch { /* 読み込み前 */ }
    D.endAt = r.end;
    const p = video.play(); if (p && p.catch) p.catch(() => {});
  };
  if (video.readyState >= 1) go(); else video.addEventListener('loadedmetadata', go, { once: true });
}
function watchEnd(){
  cancelAnimationFrame(D.raf);
  const tick = () => {
    if (video.paused) return;
    if (D.endAt != null && video.currentTime >= D.endAt){ video.pause(); D.endAt = null; return; }
    D.raf = requestAnimationFrame(tick);
  };
  D.raf = requestAnimationFrame(tick);
}
video.addEventListener('play', watchEnd);
video.addEventListener('error', () => { if (!$('#drRun').hidden) showErr('動画を再生できません(動かしたり名前を変えたりした可能性があります)。この行は「飛ばす」で次へ進めます。'); });
function togglePlay(){ if (!video.paused){ video.pause(); D.endAt = null; } else playRow(); }

function showErr(msg){ const n = $('#drErr'); n.textContent = msg; n.hidden = false; }
function note(msg){ const n = $('#drNote'); n.textContent = msg || ''; n.hidden = !msg; }

function speakerBody(){
  const v = $('#drSpk').value;
  if (v === 'other'){
    const nm = $('#drSpkNew').value.trim();
    if (!nm){ $('#drSpkNew').focus(); throw new Error('新しい話者の名前を入れてください(やめるときは話者の選択を戻してください)'); }
    return { speakerName: nm };
  }
  if (v.startsWith('name:')) return { speakerName: v.slice(5) };
  return { speaker: v.startsWith('id:') ? v.slice(3) : '' };
}

async function done(){
  const r = cur(); if (!r || D.busy) return;
  let spk;
  try { spk = speakerBody(); } catch (e){ return showErr(e.message); }
  const doc = docOf(r);
  const body = { id: r.id, rowId: r.rowId, baseUpdatedAt: doc.updatedAt, text: $('#drText').value, tags: TAGS.filter(([, s]) => $(s).checked).map(([t]) => t),
                 proofed: true, activeSec: Math.min(MAX_ROW_SEC, Math.max(0, Math.round((Date.now() - D.shownAt) / 1000))), newSession: !D.sessionDocs.has(r.id), ...spk };
  D.busy = true; $('#drDone').disabled = true;
  try {
    const res = await api('/api/drill/row', { body });
    doc.updatedAt = res.updatedAt;
    if (res.speakers) doc.speakers = res.speakers;   // 足した名前は、同じ文書の次の行では既にある話者になる
    D.sessionDocs.add(r.id); D.res.done++;
    note(''); if (res.added) toast(`話者「${body.speakerName}」を足しました`, 'ok', 2500);
    statusSoon(); next();
  } catch (e){
    if (e.status === 409){   // 別の所(編集の画面・再認識など)で変わった: この文書の残りの行も同じになるので、まとめて飛ばす
      const left = D.rows.slice(D.i + 1).filter(x => x.id === r.id).length;
      D.rows = D.rows.slice(0, D.i + 1).concat(D.rows.slice(D.i + 1).filter(x => x.id !== r.id));
      D.res.conflict += 1 + left;
      const msg = `この行の文字起こしは、別の所(編集の画面・再認識など)で先に変わっていたので、保存せずに飛ばしました${left ? `(同じ文字起こしの残り ${left} 行も)` : ''}。編集の画面で開いているなら、そちらで直してください。`;
      toast('別の所で変わっていたので飛ばしました', 'warn', 4000);
      next(); note(msg);
    } else showErr(e.message);
  } finally { D.busy = false; $('#drDone').disabled = false; }
}
function skip(){ if (!cur() || D.busy) return; D.res.skip++; note(''); next(); }
function next(){ D.i++; if (D.i >= D.rows.length) finish(); else showRow(); }

function finish(){
  video.pause(); D.endAt = null;
  show($('#drRun'), false); show($('#drEnd'), true);
  const ul = $('#drSum'); ul.textContent = '';
  ul.append(el('li', '', `済み ${D.res.done} 行`), el('li', '', `飛ばした ${D.res.skip} 行`));
  if (D.res.conflict) ul.append(el('li', '', `別の所で変わっていた ${D.res.conflict} 行`));
  $('#drAgain').focus();
  loadStatus();
}

/* ---------- 配線 ---------- */
$('#drGo').addEventListener('click', start);
$('#drAgain').addEventListener('click', () => { show($('#drEnd'), false); start(); });
$('#drPlay').addEventListener('click', togglePlay);
$('#drDone').addEventListener('click', done);
$('#drSkip').addEventListener('click', skip);
$('#drSpk').addEventListener('change', () => { syncNewName(); if ($('#drSpk').value === 'other') $('#drSpkNew').focus(); });

document.addEventListener('keydown', ev => {
  if ($('#drRun').hidden || document.querySelector('dialog[open]') || ev.isComposing || ev.keyCode === 229) return;
  const t = ev.target, typing = window.UIKit && UIKit.keys ? UIKit.keys.isTyping(t) : /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
  if (ev.key === 'Enter' && !ev.shiftKey && !ev.altKey){
    if (ev.ctrlKey || ev.metaKey){ ev.preventDefault(); playRow(); return; }
    if (t.tagName === 'BUTTON' || t.tagName === 'A' || t.tagName === 'SELECT') return;   // ボタン・リンクは押したものを動かす
    ev.preventDefault(); done(); return;
  }
  if (ev.key === 'Escape' && typing){ ev.preventDefault(); t.blur(); return; }
  if (typing || ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const k = ev.key;
  if (k === ' '){
    if (/^(BUTTON|A|INPUT|SELECT|SUMMARY)$/.test(t.tagName)) return;   // ボタン・チェックは Space で押す(ブラウザの決まり)
    ev.preventDefault(); if (ev.shiftKey) done(); else togglePlay();
  }
  else if (k === 'd' || k === 'D'){ ev.preventDefault(); skip(); }
  else if (k === 'e' || k === 'E' || k === 'F2'){ ev.preventDefault(); const ta = $('#drText'); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
  else if (/^[1-9]$/.test(k)){
    const opts = [...$('#drSpk').options].filter(o => o.value.startsWith('id:') || o.value.startsWith('name:'));
    const o = opts[+k - 1]; if (o){ ev.preventDefault(); $('#drSpk').value = o.value; syncNewName(); }
  }
});

function renderKeys(){
  const box = $('#drKeys'); box.textContent = '';
  for (const [k, d] of [['Space', '再生・停止'], ['Ctrl+Enter', '聞き直す'], ['Enter', '済みにして次へ'], ['D', '飛ばす'], ['1〜9', '話者'], ['E', '文字を直す'], ['Esc', '文字の欄を抜ける']]){
    const s = el('span', ''); s.append(el('kbd', 'ui-kbd', k), d); box.append(s);
  }
}

if (window.UIKit && UIKit.life) UIKit.life.onLeave(reason => { if (reason !== 'blur'){ video.pause(); D.endAt = null; } });   // 隣の窓へ移っただけ(blur)なら止めない
renderKeys();
loadStatus();
$('#drGo').focus();
