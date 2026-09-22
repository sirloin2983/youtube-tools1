/* 切り抜きスタジオ: ② 解析(入口・解析の設定・キュー)。Studio.enqueue(items) もここで定義する */
(() => {
'use strict';
const S = window.Studio, esc = S.esc;
const $ = s => document.querySelector(s);
const LS = 'clipstudio:queue:';
const lsGet = k => { try { return JSON.parse(localStorage.getItem(LS + k)); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(LS + k, JSON.stringify(v)); } catch {} };
const STATUS = { waiting: ['待機中', 'wait'], running: ['解析中', 'run'], done: ['完了', 'ok'], error: ['失敗', 'err'], cancelled: ['中止', 'warn'], skipped: ['スキップ', 'wait'] };
const OPT_IDS = ['useAudio', 'useChat', 'useComments', 'count', 'length', 'sens', 'pre', 'lag', 'lagAuto', 'headSec', 'typePreset', 'typeOver', 'chatTo', 'maxH', 'wA', 'wC', 'wM'];   // noCache は保存しない
const Q = { items: [], prev: null, timer: null, seq: 0, max: 10, sig: null, pressed: false, dirty: false, warned: false };
const mmss = t => Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0');

function paneHtml(){
  return `
  <div id="qWarn" class="notice" role="alert" hidden></div>
  <section class="card" id="qEntry">
    <h2>解析する配信を入れる</h2>
    <div class="fld" style="margin-top:0"><label class="l" for="qUrls">YouTubeのURL(1行に1つ。まとめて最大10本)</label>
      <textarea id="qUrls" rows="3" placeholder="https://www.youtube.com/watch?v=…&#10;https://youtu.be/…" autocomplete="off" spellcheck="false"></textarea></div>
    <div class="fld"><label class="l" for="qPath">手元の動画ファイルのパス(このパソコン上のフルパス。この場合は「音声」だけで判定します)。URLとファイルの両方を入れると、両方を追加します</label>
      <input type="text" id="qPath" placeholder="C:\\Users\\...\\stream.mp4" autocomplete="off" spellcheck="false"></div>
    <div class="fld"><label class="lag" title="まとめて追加した動画どうしを、コラボのグループにします(2本以上のときだけ)。あとで「④ コラボ」の画面で、時刻のズレ(アンカー点)を指定してください"><input type="checkbox" id="qCollab">コラボとしてまとめる(採用したマークを、他の人の配信にも候補として転写できるようにします)</label></div>
    <div class="row" style="margin-top:10px"><button type="button" class="btn primary" id="qAdd">解析に追加</button><button type="button" class="btn" id="qOpen">解析せずに確認画面を開く</button></div>
    <p class="msg hint" id="qMsg" role="status"></p>
  </section>
  <section class="card" id="qOpts">
    <h2>解析の設定</h2>
    <div class="fld" style="margin-top:0"><span class="l">盛り上がりの判定に使う材料</span><div class="row">
      <label class="lag"><input type="checkbox" id="useAudio" checked>音声(音量・笑い声や叫びの高音域)</label>
      <label class="lag" data-yt><input type="checkbox" id="useChat" checked>チャットのリプレイ(量・「草」など)</label>
      <label class="lag" data-yt><input type="checkbox" id="useComments" checked>コメント欄の時刻(「12:34 ここ最高」)</label></div></div>
    <div class="row" style="margin-top:10px">
      <label class="lag">本数(最大) <input type="number" id="count" min="1" max="30" value="8" style="width:72px"></label>
      <label class="lag">1本の長さ <input type="number" id="length" min="10" max="120" value="45" style="width:72px">秒</label>
      <label class="lag">感度 <select id="sens"><option value="high">高(多めに拾う)</option><option value="normal" selected>標準</option><option value="low">低(強い場面だけ)</option></select></label></div>
    <details style="margin-top:8px"><summary>詳しい設定</summary>
      <div class="row" style="margin-top:8px">
        <label class="lag">ピークより前 <input type="number" id="pre" min="30" max="90" value="65" style="width:72px">%(区間のどこに山を置くか)</label>
        <label class="lag" data-yt><input type="checkbox" id="lagAuto" checked>チャットの遅れを自動で推定する</label>
        <label class="lag">チャットの遅れ補正 <input type="number" id="lag" min="0" max="30" value="8" style="width:72px">秒(自動推定できないときの値)</label>
        <label class="lag" data-yt><input type="checkbox" id="typePreset">配信タイプ別の重み(試験的)</label>
        <label class="lag" data-yt>配信タイプ <select id="typeOver"><option value="auto" selected>自動(タイトル・タグから推定)</option><option value="ゲーム">ゲーム</option><option value="雑談">雑談</option><option value="歌枠">歌枠</option><option value="その他">その他</option></select>(オンのときだけ使用。倍率の初期値は仮で、歌枠は音声×0.6、雑談は音声×0.8・チャット×1.1)</label>
        <label class="lag">冒頭の減点 <input type="number" id="headSec" min="0" max="600" value="180" style="width:72px">秒(0で無効。冒頭は挨拶やBGMで誤検出しやすいため、この秒数かけて少しずつ通常の点数に戻す)</label>
        <label class="lag" data-yt>チャット取得の待ち時間(上限) <input type="number" id="chatTo" min="1" max="120" value="20" style="width:72px">分</label>
        <label class="lag" data-yt><input type="checkbox" id="noCache">キャッシュを使わない(音量の解析をやり直す)</label>
        <label class="lag">画質の上限 <select id="maxH"><option value="1080" selected>1080p</option><option value="720">720p</option><option value="480">480p</option><option value="1440">1440p</option><option value="0">制限なし</option></select></label></div>
      <div class="row" style="margin-top:8px">
        <label class="lag">重み 音声 <input type="number" id="wA" min="0" max="3" step="0.1" value="1" style="width:64px"></label>
        <label class="lag">チャット <input type="number" id="wC" min="0" max="3" step="0.1" value="1" style="width:64px"></label>
        <label class="lag">コメント <input type="number" id="wM" min="0" max="3" step="0.1" value="0.7" style="width:64px"></label></div>
      <p class="hint" style="margin:8px 0 0">チャットの反応は少し遅れて来るので、その遅れだけ前へずらして盛り上がった瞬間に合わせます(遅れは動画ごとに音量の山との一致から自動で推定します)。同じ動画の再解析は、音量の解析結果のキャッシュで速くなります(配信中・配信直後の動画は「キャッシュを使わない」をオンに)。チャット取得は長い配信だと時間がかかるため、待ち時間の上限を超えたらチャットなしで続行します。</p></details>
  </section>
  <section class="card" id="qListCard">
    <div class="row" style="justify-content:space-between"><h2 style="margin:0">解析キュー <span class="hint" id="qCount"></span></h2><button type="button" class="btn small" id="qClear" disabled>終わったものを消す</button></div>
    <div id="qList" aria-live="polite"><p class="hint" style="margin:8px 0 0">まだ何も入っていません。</p></div>
  </section>`;
}

/* ---------- 設定 ---------- */
function settings(){
  const num = (id, d) => { const v = Number($('#' + id).value); return Number.isFinite(v) && $('#' + id).value !== '' ? v : d; };
  return { useAudio: $('#useAudio').checked, useChat: $('#useChat').checked, useComments: $('#useComments').checked, count: num('count', 8), length: num('length', 45), sensitivity: $('#sens').value,
    preRatio: num('pre', 65) / 100, lag: num('lag', 8), lagAuto: $('#lagAuto').checked, headSec: num('headSec', 180), typePreset: $('#typePreset').checked, typeOverride: $('#typeOver').value, chatTimeout: num('chatTo', 20), noCache: $('#noCache').checked, maxHeight: num('maxH', 1080), wAudio: num('wA', 1), wChat: num('wC', 1), wComments: num('wM', 0.7) };
}
function saveOpts(){ const o = {}; for (const id of OPT_IDS){ const e = $('#' + id); o[id] = e.type === 'checkbox' ? e.checked : e.value; } lsSet('opts', o); }
function loadOpts(){ const o = lsGet('opts'); if (o) for (const id of OPT_IDS){ const e = $('#' + id); if (e && id in o){ if (e.type === 'checkbox') e.checked = !!o[id]; else e.value = o[id]; } } }

/* ---------- 入口の読み取り ---------- */
const unquote = s => s.trim().replace(/^["'“”‘’]+|["'“”‘’]+$/g, '').trim();
const looksYt = s => /^https?:\/\//i.test(s) || /(^|[/.@])(youtube\.com|youtu\.be)\b/i.test(s) || /^[\w-]{11}$/.test(s);
function entries(){
  const out = [];
  for (const l of $('#qUrls').value.split(/\r?\n/)){
    const s = unquote(l); if (!s) continue;
    out.push(looksYt(s) ? { kind: 'youtube', url: /^[\w-]{11}$/.test(s) ? 'https://www.youtube.com/watch?v=' + s : s } : { kind: 'file', path: s });
  }
  const p = unquote($('#qPath').value);
  if (p) out.push(looksYt(p) ? { kind: 'youtube', url: p } : { kind: 'file', path: p });
  return out;
}
function paintKinds(){
  const e = entries(), allFile = e.length > 0 && e.every(x => x.kind === 'file');
  document.querySelectorAll('#qOpts [data-yt]').forEach(l => { l.classList.toggle('off', allFile); const i = l.querySelector('input'); if (i) i.disabled = allFile && (i.id === 'useChat' || i.id === 'useComments' || i.id === 'chatTo' || i.id === 'noCache'); });
}
function setMsg(t){ const m = $('#qMsg'); if (m) m.textContent = t || ''; }

/* ---------- キューへ追加 ---------- */
S.enqueue = async items => {
  if (!items || !items.length) return { added: [], rejected: [] };
  const r = await S.api('/api/queue/add', { body: { items, settings: settings() } });
  const parts = [];
  if (r.added.length) parts.push(r.added.length + '本を解析に追加しました');
  if (r.rejected.length) parts.push('追加できなかった分: ' + r.rejected.map(x => (x.input ? '「' + String(x.input).slice(0, 40) + '」 ' : '') + x.reason).join(' / '));
  if (!parts.length) parts.push('追加するものがありませんでした');
  const msg = parts.join('。');
  S.toast(msg, r.rejected.length ? 9000 : 4500); setMsg(msg);
  await tick(); S.go('queue');
  return r;
};
/* コラボとしてまとめる: まとめて追加した動画(videoId)からグループを作る(経路1)。時刻のズレの指定は「④ コラボ」で別途行う */
async function makeCollabGroup(videoIds){
  try {
    const r = await S.api('/api/collab/group', { body: { videoIds } });
    S.toast(`コラボのグループにまとめました(${r.group.members.length}本)。「④ コラボ」でズレ(アンカー点)を指定してください`, 8000);
    if (S.collab && S.collab.refresh) S.collab.refresh();
  } catch (er){ S.toast('コラボのグループ化に失敗しました: ' + er.message, 8000); }
}
async function addFromForm(){
  const e = entries();
  if (!e.length) return S.toast('YouTubeのURLか、ファイルのパスを入れてください');
  let note = '';
  if (e.length > Q.max){ e.length = Q.max; note = '11本目以降は無視しました。'; }
  const wantGroup = $('#qCollab').checked;
  $('#qAdd').disabled = true;
  try {
    const r = await S.enqueue(e);
    if (r.added.length){ $('#qUrls').value = ''; $('#qPath').value = ''; paintKinds(); }
    if (note) setMsg(note + $('#qMsg').textContent);
    if (wantGroup){
      if (r.added.length >= 2){ await makeCollabGroup(r.added.map(x => x.videoId)); $('#qCollab').checked = false; }
      else if (r.added.length) S.toast('コラボにまとめるには2本以上、解析に追加する必要があります');
    }
  } catch (er){ S.toast(er.message); setMsg(er.message); }
  $('#qAdd').disabled = false;
}
async function openWithout(){
  const e = entries();
  if (!e.length) return S.toast('YouTubeのURLか、ファイルのパスを入れてください');
  $('#qOpen').disabled = true;
  try {
    const r = await S.api('/api/videos/open', { body: e[0] });
    setMsg(e.length > 1 ? `複数入っているので、最初の1つだけ開きました(${r.video.title || r.video.id})` : `確認画面を開きました(${r.video.title || r.video.id})`);
    if (S.review && S.review.open) await S.review.open(r.video.id); else S.toast('確認画面がまだ読み込まれていません');
  } catch (er){ S.toast(er.message); setMsg(er.message); }
  $('#qOpen').disabled = false;
}

/* ---------- キュー一覧 ---------- */
function itemHtml(it){
  const [label, cls] = STATUS[it.status] || [it.status, 'wait'];
  const id = esc(it.qid), running = it.status === 'running', chat = running && it.chat && it.chat.state === 'running' ? it.chat : null;
  let h = `<div class="q-item" data-qid="${id}" data-status="${esc(it.status)}"><div style="min-width:0"><div class="q-title">${esc(it.title || it.videoId)}</div>
    <div class="q-meta"><span class="pill ${cls}">${label}</span> ${it.kind === 'file' ? 'ファイル' : esc(it.channel || '')}${it.channel || it.kind === 'file' ? ' ・ ' : ''}<span class="mono">${esc(it.videoId)}</span>${it.status === 'done' ? ` ・ マーク ${Number(it.marks) || 0}件` : ''}</div></div>
    <div class="q-act">`;
  if (it.status === 'done') h += `<button type="button" class="btn small primary" data-act="review" data-vid="${esc(it.videoId)}">確認する</button>`;
  if (running) h += `<button type="button" class="btn small" data-act="cancel">中止</button>`;
  if (it.status === 'waiting') h += `<button type="button" class="btn small" data-act="cancel">取り除く</button>`;
  if (['error', 'cancelled', 'skipped'].includes(it.status)) h += `<button type="button" class="btn small" data-act="retry">やり直し</button>`;
  h += '</div>';
  if (running){
    h += `<div class="q-sub q-phase">${esc(it.phase)} ・ ${Math.round((it.progress || 0) * 100)}%</div><div class="bar q-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round((it.progress || 0) * 100)}"><i style="width:${Math.round((it.progress || 0) * 100)}%"></i></div>`;
    if (chat) h += `<div class="q-sub">チャット取得: 並行して実行中 <span class="q-chat-t">${mmss(chat.elapsed)}</span> <button type="button" class="btn small" data-act="skipchat" title="チャットなしで(音声・コメントだけで)先に進みます">チャットを待たずに進める</button></div>`;
  } else if (it.status === 'waiting') h += `<div class="q-sub">${esc(it.phase)}</div>`;
  else if (it.status === 'error') h += `<div class="q-sub q-err">失敗: ${esc(it.error || it.phase)}</div>`;
  else if (it.phase && it.status !== 'done') h += `<div class="q-sub">${esc(it.phase)}</div>`;
  return h + '</div>';
}
/* 構造(項目・状態・ボタン)が変わったときだけ作り直す。実行中の進捗・フェーズ・チャット経過は、その場で書き換える */
const chatShown = it => it.status === 'running' && !!it.chat && it.chat.state === 'running';
const sig = it => [it.qid, it.status, it.error, it.title, it.channel, it.marks, it.kind, it.status === 'running' ? '' : it.phase, chatShown(it)].join('\u001f');
function renderList(){
  const its = Q.items;
  $('#qList').innerHTML = its.length ? its.map(itemHtml).join('') : '<p class="hint" style="margin:8px 0 0">まだ何も入っていません。</p>';
}
function updateLive(){
  for (const it of Q.items){
    if (it.status !== 'running') continue;
    const el = document.querySelector(`#qList .q-item[data-qid="${CSS.escape(it.qid)}"]`); if (!el) continue;
    const pct = Math.round((it.progress || 0) * 100), ph = el.querySelector('.q-phase'), bar = el.querySelector('.q-bar'), ct = el.querySelector('.q-chat-t');
    if (ph) ph.textContent = `${it.phase} ・ ${pct}%`;
    if (bar){ bar.setAttribute('aria-valuenow', String(pct)); bar.firstElementChild.style.width = pct + '%'; }
    if (ct && it.chat) ct.textContent = mmss(it.chat.elapsed);
  }
}
function updateMeta(){
  const its = Q.items, act = its.filter(i => i.status === 'waiting' || i.status === 'running').length;
  $('#qCount').textContent = its.length ? `(待ち・実行中 ${act}/${Q.max}本)` : '';
  $('#qClear').disabled = !its.some(i => !['waiting', 'running'].includes(i.status));
  S.setBadge('queue', act ? String(act) : '');
}
function refreshView(){
  const sg = Q.items.map(sig).join('\n');
  if (sg !== Q.sig){
    if (Q.pressed) Q.dirty = true;   // ボタンを押している間は作り直さない(押した瞬間に要素が消えてクリックが失われるのを防ぐ)
    else { Q.sig = sg; Q.dirty = false; renderList(); }
  }
  updateLive(); updateMeta();
}
function release(){ setTimeout(() => { Q.pressed = false; if (Q.dirty) refreshView(); }, 60); }
/* dataWarning: 壊れた data.json を退避したときにサーバーが知らせる */
function showWarn(){
  const w = S.state && S.state.dataWarning; if (!w || Q.warned) return;
  Q.warned = true;
  const txt = String(w) + (S.state.corruptBackup ? `(退避したファイル: ${S.state.corruptBackup})` : '');
  const box = $('#qWarn'); box.innerHTML = `<b>データの読み込みで問題がありました</b><br>${esc(txt)}<br><button type="button" class="btn small" id="qWarnClose">閉じる</button>`; box.hidden = false;
  $('#qWarnClose').addEventListener('click', () => { box.hidden = true; });
  S.toast(txt, 9000);
}
function detect(items){
  const prev = Q.prev; Q.prev = new Map(items.map(i => [i.qid, i.status]));
  if (!prev) return;
  for (const it of items){
    const p = prev.get(it.qid);
    if (it.status === 'done' && (p === 'running' || p === 'waiting')) S.toast(`『${it.title || it.videoId}』の解析が完了しました(${Number(it.marks) || 0}件のマーク)。確認できます`, 6000);
    else if (it.status === 'error' && (p === 'running' || p === 'waiting')) S.toast(`『${it.title || it.videoId}』の解析に失敗しました: ${it.error || ''}`, 6000);
  }
}
async function tick(){
  clearTimeout(Q.timer); const my = ++Q.seq;
  let ok = true;
  try {
    const q = await S.api('/api/queue');
    if (my !== Q.seq) return;
    Q.items = q.items; Q.max = q.max || 10;
    detect(q.items);
    refreshView();
  } catch { ok = false; }
  if (my !== Q.seq) return;
  const active = Q.items.some(i => i.status === 'waiting' || i.status === 'running');
  const visible = S.step === 'queue';
  if (active) Q.timer = setTimeout(tick, ok ? 1000 : 3000);
  else if (visible) Q.timer = setTimeout(tick, 5000);   // 見えていて何も動いていない間はゆっくり(別の操作でも変化に気づけるように)
}
async function listClick(e){
  const b = e.target.closest('[data-act]'); if (!b) return;
  const act = b.dataset.act, qid = b.closest('.q-item').dataset.qid;
  if (act === 'review'){ if (S.review && S.review.open) S.review.open(b.dataset.vid); else S.toast('確認画面がまだ読み込まれていません'); return; }
  b.disabled = true;
  try {
    const path = { cancel: '/api/queue/cancel', skipchat: '/api/queue/skipchat', retry: '/api/queue/retry' }[act];
    await S.api(path, { body: { qid } });
    if (act === 'retry') S.toast('もう一度キューに入れました');
  } catch (er){ S.toast(er.message); }
  tick();
}

S.queue = { refresh: tick };
S.onReady(() => {
  $('#paneQueue').innerHTML = paneHtml();
  loadOpts(); paintKinds();
  OPT_IDS.forEach(id => $('#' + id).addEventListener('change', saveOpts));
  $('#qUrls').addEventListener('input', paintKinds); $('#qPath').addEventListener('input', paintKinds);
  $('#qAdd').addEventListener('click', addFromForm);
  $('#qOpen').addEventListener('click', openWithout);
  $('#qList').addEventListener('click', listClick);
  $('#qList').addEventListener('pointerdown', () => { Q.pressed = true; });
  document.addEventListener('pointerup', release); document.addEventListener('pointercancel', release);
  showWarn(); S.on('state', showWarn);
  $('#qClear').addEventListener('click', async () => { try { await S.api('/api/queue/clear', { method: 'POST', body: {} }); } catch (e){ S.toast(e.message); } tick(); });
  S.on('step', st => { if (st === 'queue') tick(); });
  tick();
});
})();
