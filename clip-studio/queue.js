/* 切り抜きスタジオ: ② 解析(入口・解析の設定・キュー)。Studio.enqueue(items) もここで定義する */
(() => {
'use strict';
const S = window.Studio, esc = S.esc;
const $ = s => document.querySelector(s);
const LS = 'clipstudio:queue:';
const lsGet = k => { try { return JSON.parse(localStorage.getItem(LS + k)); } catch { return null; } };
const STATUS = { waiting: ['待機中', 'wait'], running: ['解析中', 'run'], done: ['完了', 'ok'], error: ['失敗', 'err'], cancelled: ['中止', 'warn'], skipped: ['スキップ', 'wait'] };
const OPT_IDS = ['useAudio', 'useChat', 'useComments', 'count', 'length', 'sens', 'pre', 'lag', 'lagAuto', 'headSec', 'typePreset', 'typeOver', 'chatTo', 'maxH', 'wA', 'wC', 'wM'];   // noCache は保存しない
const Q = { items: [], prev: null, timer: null, seq: 0, max: 10, sig: null, pressed: false, dirty: false, warned: false };
const mmss = t => { t = Math.max(0, Math.floor(Number(t) || 0)); return Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0'); };

function paneHtml(){
  return `
  <div id="qWarn" class="notice" role="alert" hidden></div>
  <div id="qParam" class="notice info cs-notice-act" hidden><div><b>URL を受け取りました。</b> 下の欄に入れました。内容を確かめて「解析に追加」を押してください(自動では始めません)。</div><button type="button" class="btn small ghost" id="qParamClose">閉じる</button></div>
  <div class="q-grid">
  <div class="q-col">
  <section class="card" id="qEntry">
    <div class="card-head"><h2 class="card-title">解析する配信を入れる</h2></div>
    <div class="fld" style="margin-top:0"><label class="l" for="qUrls">YouTubeのURL <span class="muted">1行に1つ。まとめて最大10本</span></label>
      <textarea id="qUrls" rows="3" placeholder="https://www.youtube.com/watch?v=…&#10;https://youtu.be/…" autocomplete="off" spellcheck="false"></textarea></div>
    <div class="fld"><label class="l" for="qPath">手元の動画ファイルのパス <span class="muted">このパソコン上のフルパス。「音声」だけで判定します</span></label>
      <input type="text" id="qPath" placeholder="C:\\Users\\...\\stream.mp4" autocomplete="off" spellcheck="false">
      <span class="hint">URLとファイルの両方を入れると、両方を追加します</span></div>
    <div class="fld"><label class="lag q-collab" title="まとめて追加した動画どうしを、コラボのグループにします(2本以上のときだけ)。あとで「④ コラボ」の画面で、時刻のズレ(アンカー点)を指定してください"><input type="checkbox" class="ui-switch" id="qCollab"><span>コラボとしてまとめる <span class="muted">採用したマークを、他の人の配信にも候補として転写できるようにします</span></span></label></div>
    <div class="row q-acts"><button type="button" class="btn primary" id="qAdd">解析に追加</button><button type="button" class="btn" id="qOpen">解析せずに確認画面を開く</button></div>
    <p class="msg hint" id="qMsg" role="status"></p>
  </section>
  <section class="card" id="qOpts">
    <div class="card-head"><h2 class="card-title">解析の設定</h2><span class="card-sub">次に追加する分から使います。入口の「まとめて実行」も同じ設定で解析します</span></div>
    <div class="fld" style="margin-top:0"><span class="l">盛り上がりの判定に使う材料</span><div class="q-mats">
      <label class="lag q-mat"><input type="checkbox" id="useAudio" checked><span class="q-sw a"></span>音声 <span class="muted">音量・笑い声や叫びの高音域</span></label>
      <label class="lag q-mat" data-yt><input type="checkbox" id="useChat" checked><span class="q-sw c"></span>チャットのリプレイ <span class="muted">量・「草」など</span></label>
      <label class="lag q-mat" data-yt><input type="checkbox" id="useComments" checked><span class="q-sw m"></span>コメント欄の時刻 <span class="muted">「12:34 ここ最高」</span></label></div></div>
    <div class="cs-opts">
      <label class="cs-opt"><span class="l">本数(最大)</span><input type="number" id="count" min="1" max="30" value="8"></label>
      <label class="cs-opt"><span class="l">1本の長さ(秒)</span><input type="number" id="length" min="10" max="120" value="45"></label>
      <label class="cs-opt"><span class="l">感度</span><select id="sens"><option value="high">高(多めに拾う)</option><option value="normal" selected>標準</option><option value="low">低(強い場面だけ)</option></select></label>
    </div>
    <details class="ui-disclosure q-adv"><summary>詳しい設定</summary>
      <div class="cs-opts q-advgrid">
        <label class="cs-opt"><span class="l">ピークより前(%)</span><input type="number" id="pre" min="30" max="90" value="65"><span class="hint">区間のどこに山を置くか</span></label>
        <label class="cs-opt"><span class="l">冒頭の減点(秒)</span><input type="number" id="headSec" min="0" max="600" value="180"><span class="hint">0で無効。冒頭は挨拶やBGMで誤検出しやすいため、この秒数かけて少しずつ通常の点数に戻す</span></label>
        <label class="cs-opt"><span class="l">画質の上限</span><select id="maxH"><option value="1080" selected>1080p</option><option value="720">720p</option><option value="480">480p</option><option value="1440">1440p</option><option value="0">制限なし</option></select></label>
        <label class="cs-opt" data-yt><span class="l">チャットの遅れ補正(秒)</span><input type="number" id="lag" min="0" max="30" value="8"><span class="hint">自動推定できないときの値</span></label>
        <label class="cs-opt" data-yt><span class="l">チャット取得の待ち時間(上限・分)</span><input type="number" id="chatTo" min="1" max="120" value="20"></label>
        <label class="cs-opt" data-yt><span class="l">配信タイプ</span><select id="typeOver"><option value="auto" selected>自動(タイトル・タグから推定)</option><option value="ゲーム">ゲーム</option><option value="雑談">雑談</option><option value="歌枠">歌枠</option><option value="その他">その他</option></select><span class="hint">「配信タイプ別の重み」がオンのときだけ使用。倍率の初期値は仮で、歌枠は音声×0.6、雑談は音声×0.8・チャット×1.1</span></label>
      </div>
      <div class="q-switches">
        <label class="lag" data-yt><input type="checkbox" class="ui-switch" id="lagAuto" checked>チャットの遅れを自動で推定する</label>
        <label class="lag" data-yt><input type="checkbox" class="ui-switch" id="typePreset">配信タイプ別の重み(試験的)</label>
        <label class="lag" data-yt><input type="checkbox" class="ui-switch" id="noCache">キャッシュを使わない(音量の解析をやり直す)</label>
      </div>
      <div class="fld"><span class="l">重み</span><div class="cs-opts q-weights">
        <label class="cs-opt"><span class="l"><span class="q-sw a"></span>音声</span><input type="number" id="wA" min="0" max="3" step="0.1" value="1"></label>
        <label class="cs-opt"><span class="l"><span class="q-sw c"></span>チャット</span><input type="number" id="wC" min="0" max="3" step="0.1" value="1"></label>
        <label class="cs-opt"><span class="l"><span class="q-sw m"></span>コメント</span><input type="number" id="wM" min="0" max="3" step="0.1" value="0.7"></label></div></div>
      <p class="hint q-advnote">チャットの反応は少し遅れて来るので、その遅れだけ前へずらして盛り上がった瞬間に合わせます(遅れは動画ごとに音量の山との一致から自動で推定します)。同じ動画の再解析は、音量の解析結果のキャッシュで速くなります(配信中・配信直後の動画は「キャッシュを使わない」をオンに)。チャット取得は長い配信だと時間がかかるため、待ち時間の上限を超えたらチャットなしで続行します。</p></details>
  </section>
  </div>
  <section class="card q-listcard" id="qListCard">
    <div class="card-head"><h2 class="card-title">解析キュー</h2><span class="card-sub" id="qCount"></span><span class="spacer"></span><button type="button" class="btn small ghost" id="qClear" disabled>終わったものを消す</button></div>
    <div id="qList" aria-live="polite"></div>
  </section>
  </div>`;
}
const EMPTY_LIST = '<div class="empty"><b>まだ何も入っていません</b>URL かファイルのパスを入れて「解析に追加」を押すか、① 探す から選んでください。<br>1本ずつ順番に解析し、終わったものから「確認する」で ③ へ進めます。</div>';

/* ---------- 設定 ---------- */
function settings(){
  const num = (id, d) => { const v = Number($('#' + id).value); return Number.isFinite(v) && $('#' + id).value !== '' ? v : d; };
  return { useAudio: $('#useAudio').checked, useChat: $('#useChat').checked, useComments: $('#useComments').checked, count: num('count', 8), length: num('length', 45), sensitivity: $('#sens').value,
    preRatio: num('pre', 65) / 100, lag: num('lag', 8), lagAuto: $('#lagAuto').checked, headSec: num('headSec', 180), typePreset: $('#typePreset').checked, typeOverride: $('#typeOver').value, chatTimeout: num('chatTo', 20), noCache: $('#noCache').checked, maxHeight: num('maxH', 1080), wAudio: num('wA', 1), wChat: num('wC', 1), wComments: num('wM', 0.7) };
}
/* 解析の設定の保存先はスタジオのサーバー(/api/settings の settings.analyze。段階7-1)。
   まとめて実行(入口)も同じ設定で解析し、窓(専用のプロファイル)やほかのブラウザで開いても設定が変わらない。
   保存するのは settings() の形(noCache はその場だけの指定なので除く)。以前のブラウザの保存(localStorage の opts)は、サーバーに無いときに1回だけ引き継ぐ */
const FROM_SETTINGS = { useAudio: 'useAudio', useChat: 'useChat', useComments: 'useComments', count: 'count', length: 'length', sensitivity: 'sens',
  lag: 'lag', lagAuto: 'lagAuto', headSec: 'headSec', typePreset: 'typePreset', typeOverride: 'typeOver', chatTimeout: 'chatTo', maxHeight: 'maxH', wAudio: 'wA', wChat: 'wC', wComments: 'wM' };
const O = { timer: null, touched: false };
function applyForm(o){   // o: 画面の欄の id → 値
  for (const id of OPT_IDS){
    const e = $('#' + id); if (!e || !(id in o)) continue;
    if (e.type === 'checkbox') e.checked = !!o[id];
    else if (e.tagName === 'SELECT'){ if ([...e.options].some(op => op.value === String(o[id]))) e.value = String(o[id]); }   // 知らない値で空欄にしない
    else if (o[id] !== null && o[id] !== undefined && (typeof o[id] === 'number' || typeof o[id] === 'string')) e.value = o[id];
  }
}
function applySettings(v){   // v: settings() の形(サーバーに保存したもの)
  const o = {};
  for (const [k, id] of Object.entries(FROM_SETTINGS)) if (k in v) o[id] = v[k];
  if (typeof v.preRatio === 'number') o.pre = Math.round(v.preRatio * 100);
  applyForm(o);
}
async function pushOpts(){
  clearTimeout(O.timer); O.timer = null;
  const v = settings(); delete v.noCache;
  try { await S.api('/api/settings', { method: 'PUT', body: { section: 'analyze', value: v } }); }
  catch (e){ S.toast('解析の設定を保存できませんでした: ' + e.message, 6000, 'err'); }
}
function saveOpts(){ O.touched = true; clearTimeout(O.timer); O.timer = setTimeout(pushOpts, 400); }
async function loadOpts(){
  let saved = null, ok = false;
  try { const j = await S.api('/api/settings'); saved = j && j.settings ? j.settings.analyze : null; ok = true; } catch {}
  if (O.touched) return;   // 読み込みを待つ間に欄を変えた: その値を優先する(上書きしない)
  if (saved && typeof saved === 'object'){ applySettings(saved); paintKinds(); return; }
  const old = lsGet('opts');
  if (ok && old && typeof old === 'object'){ applyForm(old); paintKinds(); pushOpts(); }   // 以前のブラウザの保存を1回だけ引き継ぐ
}

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
  S.toast(msg, r.rejected.length ? 9000 : 4500, r.rejected.length ? (r.added.length ? 'info' : 'err') : 'ok'); setMsg(msg);
  await tick(); S.go('queue');
  return r;
};
/* コラボとしてまとめる: まとめて追加した動画(videoId)からグループを作る(経路1)。時刻のズレの指定は「④ コラボ」で別途行う */
async function makeCollabGroup(videoIds){
  try {
    const r = await S.api('/api/collab/group', { body: { videoIds } });
    S.toast(`コラボのグループにまとめました(${r.group.members.length}本)。「④ コラボ」でズレ(アンカー点)を指定してください`, 8000, 'ok');
    if (S.collab && S.collab.refresh) S.collab.refresh();
  } catch (er){ S.toast('コラボのグループ化に失敗しました: ' + er.message, 8000, 'err'); }
}
async function addFromForm(){
  if ($('#qAdd').disabled) return;
  const e = entries();
  if (!e.length){ $('#qUrls').focus(); return S.toast('YouTubeのURLか、ファイルのパスを入れてください'); }
  let note = '';
  if (e.length > Q.max){ e.length = Q.max; note = '11本目以降は無視しました。'; }
  const wantGroup = $('#qCollab').checked;
  $('#qAdd').disabled = true; $('#qOpen').disabled = true;
  try {
    const r = await S.enqueue(e);
    if (r.added.length){ $('#qUrls').value = ''; $('#qPath').value = ''; paintKinds(); $('#qParam').hidden = true; }
    if (note) setMsg(note + $('#qMsg').textContent);
    if (wantGroup){
      if (r.added.length >= 2){ await makeCollabGroup(r.added.map(x => x.videoId)); $('#qCollab').checked = false; }
      else if (r.added.length) S.toast('コラボにまとめるには2本以上、解析に追加する必要があります');
    }
  } catch (er){ S.toast(er.message, 0, 'err'); setMsg(er.message); }
  $('#qAdd').disabled = false; $('#qOpen').disabled = false;
}
async function openWithout(){
  if ($('#qOpen').disabled) return;
  const e = entries();
  if (!e.length){ $('#qUrls').focus(); return S.toast('YouTubeのURLか、ファイルのパスを入れてください'); }
  $('#qOpen').disabled = true; $('#qAdd').disabled = true;
  try {
    const r = await S.api('/api/videos/open', { body: e[0] });
    setMsg(e.length > 1 ? `複数入っているので、最初の1つだけ開きました(${r.video.title || r.video.id})` : `確認画面を開きました(${r.video.title || r.video.id})`);
    if (S.review && S.review.open) await S.review.open(r.video.id); else S.toast('確認画面がまだ読み込まれていません', 0, 'err');
  } catch (er){ S.toast(er.message, 0, 'err'); setMsg(er.message); }
  $('#qOpen').disabled = false; $('#qAdd').disabled = false;
}

/* ---------- キュー一覧 ---------- */
function itemHtml(it){
  const [label, cls] = STATUS[it.status] || [String(it.status || ''), 'wait'];
  const id = esc(it.qid), running = it.status === 'running', chat = running && it.chat && it.chat.state === 'running' ? it.chat : null, pct = Math.round((it.progress || 0) * 100);
  let h = `<div class="q-item st-${esc(cls)}" data-qid="${id}" data-status="${esc(it.status)}"><span class="q-ic" aria-hidden="true"></span><div class="q-main"><div class="q-title">${esc(it.title || it.videoId)}</div>
    <div class="q-meta"><span class="pill ${esc(cls)}">${esc(label)}</span><span>${it.kind === 'file' ? 'ファイル' : esc(it.channel || '')}</span>${it.channel || it.kind === 'file' ? '<span class="q-dot">・</span>' : ''}<span class="mono">${esc(it.videoId)}</span>${it.status === 'done' ? `<span class="q-dot">・</span><span>マーク <b class="num">${Number(it.marks) || 0}</b>件</span>` : ''}</div></div>
    <div class="q-act">`;
  if (it.status === 'done') h += `<button type="button" class="btn small primary" data-act="review" data-vid="${esc(it.videoId)}">確認する</button>`;
  if (running) h += `<button type="button" class="btn small" data-act="cancel">中止</button>`;
  if (it.status === 'waiting') h += `<button type="button" class="btn small ghost" data-act="cancel">取り除く</button>`;
  if (['error', 'cancelled', 'skipped'].includes(it.status)) h += `<button type="button" class="btn small" data-act="retry">やり直し</button>`;
  h += '</div>';
  if (running){
    h += `<div class="q-sub q-prog"><span class="q-phase">${esc(it.phase)}</span><span class="num q-pct">${pct}%</span></div><div class="bar q-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i style="width:${pct}%"></i></div>`;
    if (chat) h += `<div class="q-sub q-chat"><span class="ui-spin" aria-hidden="true"></span>チャット取得: 並行して実行中 <span class="q-chat-t num">${mmss(chat.elapsed)}</span> <button type="button" class="btn small ghost" data-act="skipchat" title="チャットなしで(音声・コメントだけで)先に進みます">チャットを待たずに進める</button></div>`;
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
  $('#qList').innerHTML = its.length ? its.map(itemHtml).join('') : EMPTY_LIST;
}
function updateLive(){
  for (const it of Q.items){
    if (it.status !== 'running') continue;
    const el = document.querySelector(`#qList .q-item[data-qid="${CSS.escape(it.qid)}"]`); if (!el) continue;
    const pct = Math.round((it.progress || 0) * 100), ph = el.querySelector('.q-phase'), pc = el.querySelector('.q-pct'), bar = el.querySelector('.q-bar'), ct = el.querySelector('.q-chat-t');
    if (ph) ph.textContent = it.phase || '';
    if (pc) pc.textContent = pct + '%';
    if (bar){ bar.setAttribute('aria-valuenow', String(pct)); bar.firstElementChild.style.width = pct + '%'; }
    if (ct && it.chat) ct.textContent = mmss(it.chat.elapsed);
  }
}
function updateMeta(){
  const its = Q.items, act = its.filter(i => i.status === 'waiting' || i.status === 'running').length;
  $('#qCount').textContent = its.length ? `待ち・実行中 ${act}/${Q.max}本 ・ 全${its.length}件` : '';
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
  S.toast(txt, 9000, 'err');
}
function detect(items){
  const prev = Q.prev; Q.prev = new Map(items.map(i => [i.qid, i.status]));
  if (!prev) return;
  for (const it of items){
    const p = prev.get(it.qid);
    if (it.status === 'done' && (p === 'running' || p === 'waiting')) S.toast(`『${it.title || it.videoId}』の解析が完了しました(${Number(it.marks) || 0}件のマーク)。確認できます`, 6000, 'ok');
    else if (it.status === 'error' && (p === 'running' || p === 'waiting')) S.toast(`『${it.title || it.videoId}』の解析に失敗しました: ${it.error || ''}`, 7000, 'err');
  }
}
async function tick(){
  clearTimeout(Q.timer); const my = ++Q.seq;
  let ok = true;
  try {
    const q = await S.api('/api/queue');
    if (my !== Q.seq) return;
    Q.items = Array.isArray(q.items) ? q.items : []; Q.max = q.max || 10;
    detect(Q.items);
    refreshView();
  } catch { ok = false; }
  if (my !== Q.seq) return;
  const active = Q.items.some(i => i.status === 'waiting' || i.status === 'running');
  const visible = S.step === 'queue';
  if (active) Q.timer = setTimeout(tick, ok ? 1000 : 3000);
  else if (visible) Q.timer = setTimeout(tick, 5000);   // 見えていて何も動いていない間はゆっくり(別の操作でも変化に気づけるように)
}
async function listClick(e){
  const b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
  const act = b.dataset.act, qid = b.closest('.q-item').dataset.qid;
  if (act === 'review'){ if (S.review && S.review.open) S.review.open(b.dataset.vid); else S.toast('確認画面がまだ読み込まれていません', 0, 'err'); return; }
  b.disabled = true;
  try {
    const path = { cancel: '/api/queue/cancel', skipchat: '/api/queue/skipchat', retry: '/api/queue/retry' }[act];
    if (!path) return;
    await S.api(path, { body: { qid } });
    if (act === 'retry') S.toast('もう一度キューに入れました', 0, 'ok');
  } catch (er){ S.toast(er.message, 0, 'err'); }
  tick();
}

S.queue = { refresh: tick };
S.onReady(() => {
  $('#paneQueue').innerHTML = paneHtml();
  $('#qList').innerHTML = EMPTY_LIST;
  paintKinds(); loadOpts();
  OPT_IDS.forEach(id => $('#' + id).addEventListener('change', saveOpts));
  if (window.UIKit && UIKit.life) UIKit.life.onLeave(() => { if (O.timer) pushOpts(); });   // 変えた直後に離れた・閉じたときも送る
  $('#qUrls').addEventListener('input', paintKinds); $('#qPath').addEventListener('input', paintKinds);
  $('#qUrls').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)){ e.preventDefault(); addFromForm(); } });   // Ctrl+Enter で追加
  $('#qPath').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); addFromForm(); } });
  $('#qAdd').addEventListener('click', addFromForm);
  $('#qOpen').addEventListener('click', openWithout);
  $('#qList').addEventListener('click', listClick);
  $('#qList').addEventListener('pointerdown', () => { Q.pressed = true; });
  document.addEventListener('pointerup', release); document.addEventListener('pointercancel', release);
  showWarn(); S.on('state', showWarn);
  $('#qClear').addEventListener('click', async e => {
    const b = e.currentTarget; if (b.disabled) return; b.disabled = true;
    try { await S.api('/api/queue/clear', { method: 'POST', body: {} }); } catch (er){ S.toast(er.message, 0, 'err'); }
    tick();
  });
  $('#qParamClose').addEventListener('click', () => { $('#qParam').hidden = true; });
  /* 他のツールからのリンク(?url=)。欄に入れるだけで、解析は押すまで始めない */
  if (S.params && S.params.url){
    $('#qUrls').value = S.params.url; paintKinds(); $('#qParam').hidden = false;
    setTimeout(() => { try { $('#qAdd').focus({ preventScroll: true }); } catch {} }, 0);
  }
  S.on('step', st => { if (st === 'queue') tick(); });
  tick();
});
})();
