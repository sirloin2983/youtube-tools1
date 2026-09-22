/* 切り抜きスタジオ: ④ コラボ(動画のグループ化・時刻のズレの指定)。
   マーク転写そのもの(採用時に候補として作る処理)はサーバー側(store.py)で行う。ここではグループの作成・編集・アンカー点の指定だけを扱う。 */
(() => {
'use strict';
const S = window.Studio;
if (!S) return;
const esc = S.esc;
const $ = s => document.querySelector(s);
const pad = n => String(n).padStart(2, '0');

function fmt(t){
  t = Math.max(0, Number(t) || 0);
  const d = Math.round(t * 10), h = Math.floor(d / 36000), m = Math.floor(d % 36000 / 600), s = ((d % 600) / 10).toFixed(1).padStart(4, '0');
  return h ? `${h}:${pad(m)}:${s}` : `${m}:${s}`;
}
function parseTime(str){
  str = String(str || '').trim().replace(/[：]/g, ':');
  if (!str) return NaN;
  const parts = str.split(':');
  if (parts.length > 3) return NaN;
  let t = 0;
  for (const p of parts){ if (!/^\d+(\.\d+)?$/.test(p)) return NaN; t = t * 60 + parseFloat(p); }
  return t;
}
function armDelete(btn, run){
  if (btn.dataset.armed){ run(); return; }
  const label = btn.textContent; btn.dataset.armed = '1'; btn.textContent = 'もう一度押すと削除';
  setTimeout(() => { if (btn.isConnected){ delete btn.dataset.armed; btn.textContent = label; } }, 3000);
}

/* addTo: 既存グループに動画を追加するモード中は、そのグループID。anchorOpen: 開いているアンカー指定フォーム({gid, videoId}) */
const C = { videos: [], groups: [], checked: new Set(), base: null, addTo: null, anchorOpen: null };

function paneHtml(){
  return `
  <section class="card" id="clMake">
    <h2 id="clMakeTitle">動画をコラボにまとめる</h2>
    <p class="hint" id="clMakeSub"></p>
    <div class="row" id="clBaseRow" style="margin-top:8px">
      <label class="lag">基準にする動画 <select id="clBase"></select></label>
      <label class="lag">グループ名(任意) <input type="text" id="clName" maxlength="120" placeholder="例: 9/20 マリオカート部屋" style="width:220px" autocomplete="off"></label>
    </div>
    <div id="clVideoList" style="margin-top:8px"></div>
    <div class="row" style="margin-top:8px">
      <button type="button" class="btn primary" id="clGo" disabled>選んだ動画をまとめる</button>
      <button type="button" class="btn" id="clCancelAdd" hidden>キャンセル</button>
      <span class="hint" id="clMsg"></span>
    </div>
  </section>
  <section class="card" id="clGroups">
    <h2>コラボグループ</h2>
    <div id="clGroupList"><p class="hint" style="margin:8px 0 0">まだグループがありません。</p></div>
  </section>`;
}

/* ---------- 動画の選択(上のカード) ---------- */
function vlabel(v){ return v.title || v.fileName || v.id; }
function videoRowHtml(v){
  const grouped = !!v.groupId, dis = grouped ? ' disabled' : '';
  const checked = C.checked.has(v.id) ? ' checked' : '';
  const badge = grouped ? '<span class="pill wait">すでにグループ済み</span>' : (v.duration ? '' : '<span class="pill wait">解析前</span>');
  return `<label class="q-item" style="cursor:${grouped ? 'default' : 'pointer'};align-items:center">
    <div style="min-width:0"><input type="checkbox" data-vid="${esc(v.id)}"${checked}${dis} style="margin-right:8px" aria-label="${esc(vlabel(v))}を選ぶ">
      <span class="q-title">${esc(vlabel(v))}</span>
      <div class="q-meta">${v.kind === 'file' ? 'ファイル' : esc(v.channel || '')} ・ <span class="mono">${esc(v.id)}</span>${v.duration ? ' ・ ' + fmt(v.duration) : ''} ${badge}</div>
    </div></label>`;
}
function renderVideoList(){
  const box = $('#clVideoList'); if (!box) return;
  box.innerHTML = C.videos.length ? C.videos.map(videoRowHtml).join('')
    : '<p class="hint">動画がありません。② 解析、または ③ 確認・書き出しから動画を登録してください。</p>';
  renderBaseSelect();
}
function renderBaseSelect(){
  const ids = [...C.checked];
  if (C.addTo){
    $('#clGo').disabled = !ids.length;
    return;
  }
  const sel = $('#clBase');
  if (!ids.length){ sel.innerHTML = '<option value="">(2本以上選んでください)</option>'; sel.disabled = true; $('#clGo').disabled = true; return; }
  sel.disabled = false;
  if (!ids.includes(C.base)) C.base = ids[0];
  sel.innerHTML = ids.map(id => { const v = C.videos.find(x => x.id === id); return `<option value="${esc(id)}"${id === C.base ? ' selected' : ''}>${esc(v ? vlabel(v) : id)}</option>`; }).join('');
  $('#clGo').disabled = ids.length < 2;
}
function renderMakeCard(){
  const g = C.addTo ? C.groups.find(x => x.id === C.addTo) : null;
  $('#clMakeTitle').textContent = C.addTo ? `『${g ? (g.name || '(名称未設定)') : ''}』に動画を追加` : '動画をコラボにまとめる';
  $('#clMakeSub').textContent = C.addTo
    ? 'チェックした動画をこのグループに追加します(すでに解析済み・未解析どちらでも構いません)。'
    : 'チェックした動画を1つのグループにします。採用したマークを、同じグループの他の動画にも候補として転写できるようになります(自動採用はしません)。まとめたあと、下の「コラボグループ」でズレ(アンカー点)を指定してください。';
  $('#clBaseRow').hidden = !!C.addTo;
  $('#clGo').textContent = C.addTo ? '追加する' : '選んだ動画をまとめる';
  $('#clCancelAdd').hidden = !C.addTo;
}

/* ---------- グループの一覧 ---------- */
function offsetText(off){
  if (!off) return '';
  const drift = Math.abs(off.a - 1) > 0.0005 ? `傾き ${off.a.toFixed(4)} ・ ` : '';
  const b = off.b >= 0 ? `+${off.b.toFixed(1)}秒` : `${off.b.toFixed(1)}秒`;
  return `${drift}オフセット ${b}`;
}
function baseTitle(g){ const b = g.members.find(x => x.isBase); return b ? (b.title || b.id) : g.base; }
function anchorFormHtml(g, m){
  return `<div class="rv-body">
    <p class="hint">両方の動画で「同じ瞬間」を見つけて、その時刻を入力してください(例: 1:23.5、1時間以上は 1:02:03.5)。2点目も指定すると、配信中のわずかなズレの変化(ドリフト)も補正できます。</p>
    <div class="row"><span class="hint" style="min-width:32px">点1</span>
      <label class="lag">この動画(${esc(m.title || m.id)}) <input type="text" class="mono" id="clA1this" placeholder="0:00.0" style="width:110px" autocomplete="off"></label>
      <label class="lag">基準(${esc(baseTitle(g))}) <input type="text" class="mono" id="clA1ref" placeholder="0:00.0" style="width:110px" autocomplete="off"></label></div>
    <div class="row" style="margin-top:6px"><label class="rv-check" for="clA2on"><input type="checkbox" id="clA2on">2点目も指定する</label></div>
    <div class="row" id="clA2row" hidden><span class="hint" style="min-width:32px">点2</span>
      <label class="lag">この動画 <input type="text" class="mono" id="clA2this" placeholder="0:00.0" style="width:110px" autocomplete="off"></label>
      <label class="lag">基準 <input type="text" class="mono" id="clA2ref" placeholder="0:00.0" style="width:110px" autocomplete="off"></label></div>
    <div class="row" style="margin-top:8px"><button type="button" class="btn primary" data-act="saveAnchor">計算して保存</button>
      <button type="button" class="btn" data-act="cancelAnchor">キャンセル</button><span class="hint" id="clAnchorMsg"></span></div>
  </div>`;
}
function memberRowHtml(g, m){
  const open = C.anchorOpen && C.anchorOpen.gid === g.id && C.anchorOpen.videoId === m.id;
  let h = `<li class="rv-mark-row" data-gid="${esc(g.id)}" data-vid="${esc(m.id)}"><div class="rv-mh" style="flex-wrap:wrap">
    <span class="rv-tc">${esc(m.title || m.id)}</span>${!m.exists ? '<span class="rv-chip">(削除済み)</span>' : ''}
    ${m.isBase ? '<span class="rv-chip done">基準</span>'
      : (m.offsetSet ? `<span class="rv-chip done" title="${esc(offsetText(m.offset))}">ズレ設定済み(${esc(offsetText(m.offset))})</span>` : '<span class="rv-chip live">ズレ未設定</span>')}`;
  if (!m.isBase) h += `<button type="button" class="btn small" data-act="anchor">${m.offsetSet ? 'アンカーを設定し直す' : 'アンカーを指定'}</button>`;
  h += `<button type="button" class="btn small rv-danger" data-act="removeMember">グループから外す</button></div>`;
  if (open) h += anchorFormHtml(g, m);
  h += '</li>';
  return h;
}
function groupHtml(g){
  return `<div class="card" style="margin:10px 0 0;padding:10px" data-gid="${esc(g.id)}">
    <div class="row" style="justify-content:space-between">
      <b>${esc(g.name || '(名称未設定)')}</b>
      <span class="row" style="gap:6px"><span class="pill ${g.allSet ? 'ok' : 'warn'}">${g.allSet ? 'ズレ設定済み' : 'ズレ未設定あり'}</span>
        <button type="button" class="btn small" data-act="addMore">動画を追加</button>
        <button type="button" class="btn small rv-danger" data-act="deleteGroup">グループを削除</button></span>
    </div>
    <ol class="rv-list" style="margin-top:6px">${g.members.map(m => memberRowHtml(g, m)).join('')}</ol>
  </div>`;
}
function renderGroups(){
  const box = $('#clGroupList'); if (!box) return;
  box.innerHTML = C.groups.length ? C.groups.map(groupHtml).join('') : '<p class="hint" style="margin:8px 0 0">まだグループがありません。</p>';
}

/* ---------- 操作 ---------- */
async function refresh(){
  let vr, gr;
  try { [vr, gr] = await Promise.all([S.api('/api/videos'), S.api('/api/collab/groups')]); }
  catch (e){ S.toast(e.message); return; }
  C.videos = vr.videos || []; C.groups = gr.groups || [];
  for (const id of [...C.checked]) if (!C.videos.some(v => v.id === id)) C.checked.delete(id);
  if (C.addTo && !C.groups.some(g => g.id === C.addTo)) C.addTo = null;
  if (C.anchorOpen && !C.groups.some(g => g.id === C.anchorOpen.gid)) C.anchorOpen = null;
  renderMakeCard(); renderVideoList(); renderGroups();
  S.setBadge('collab', (() => { const n = C.groups.filter(g => !g.allSet).length; return n ? String(n) : ''; })());
}
async function onGo(){
  const ids = [...C.checked];
  if (C.addTo){
    if (!ids.length) return S.toast('追加する動画を選んでください');
    try {
      await S.api('/api/collab/group/add', { body: { id: C.addTo, videoIds: ids } });
      S.toast(`${ids.length}本を追加しました`);
      C.checked.clear(); C.addTo = null;
      await refresh();
    } catch (e){ S.toast(e.message); }
    return;
  }
  if (ids.length < 2) return S.toast('2本以上選んでください');
  try {
    await S.api('/api/collab/group', { body: { videoIds: ids, name: $('#clName').value, base: C.base } });
    S.toast('コラボのグループにまとめました。下の一覧でズレ(アンカー点)を指定してください', 6000);
    C.checked.clear(); $('#clName').value = '';
    await refresh();
  } catch (e){ S.toast(e.message); }
}
function onVideoChange(e){
  const cb = e.target.closest('input[type=checkbox][data-vid]'); if (!cb) return;
  if (cb.checked) C.checked.add(cb.dataset.vid); else C.checked.delete(cb.dataset.vid);
  renderBaseSelect();
}
async function saveAnchor(gid, vid){
  const msg = $('#clAnchorMsg');
  const t1 = parseTime($('#clA1this').value), r1 = parseTime($('#clA1ref').value);
  if (!Number.isFinite(t1) || !Number.isFinite(r1)){ msg.textContent = '点1の時刻を入力してください(例: 1:23.5)'; return; }
  const points = [[t1, r1]];
  if ($('#clA2on').checked){
    const t2 = parseTime($('#clA2this').value), r2 = parseTime($('#clA2ref').value);
    if (!Number.isFinite(t2) || !Number.isFinite(r2)){ msg.textContent = '点2の時刻を入力してください(例: 1:23.5)'; return; }
    points.push([t2, r2]);
  }
  try {
    await S.api('/api/collab/anchor', { body: { id: gid, videoId: vid, points } });
    S.toast('ズレを保存しました');
    C.anchorOpen = null;
    await refresh();
  } catch (e){ msg.textContent = e.message; }
}
async function onGroupClick(e){
  const b = e.target.closest('[data-act]'); if (!b) return;
  const wrap = b.closest('[data-gid]'); if (!wrap) return;
  const gid = wrap.dataset.gid, vid = wrap.dataset.vid;
  const act = b.dataset.act;
  if (act === 'addMore'){
    C.addTo = gid; C.checked.clear(); renderMakeCard(); renderVideoList();
    $('#clMake').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else if (act === 'deleteGroup'){
    armDelete(b, async () => {
      try { await S.api('/api/collab/group/delete', { body: { id: gid } }); S.toast('グループを削除しました'); await refresh(); }
      catch (er){ S.toast(er.message); }
    });
  } else if (act === 'removeMember'){
    try {
      const r = await S.api('/api/collab/group/remove', { body: { id: gid, videoId: vid } });
      S.toast(r.deleted ? 'グループから外しました(残り1本になったため、グループごと削除しました)' : 'グループから外しました');
      await refresh();
    } catch (er){ S.toast(er.message); }
  } else if (act === 'anchor'){
    C.anchorOpen = (C.anchorOpen && C.anchorOpen.gid === gid && C.anchorOpen.videoId === vid) ? null : { gid, videoId: vid };
    renderGroups();
  } else if (act === 'cancelAnchor'){
    C.anchorOpen = null; renderGroups();
  } else if (act === 'saveAnchor'){
    saveAnchor(gid, vid);
  }
}
function onGroupChange(e){
  if (e.target.id === 'clA2on'){
    const row = e.target.closest('.rv-body').querySelector('#clA2row');
    if (row) row.hidden = !e.target.checked;
  }
}

S.collab = { refresh };
S.onReady(() => {
  $('#paneCollab').innerHTML = paneHtml();
  $('#clGo').addEventListener('click', onGo);
  $('#clCancelAdd').addEventListener('click', () => { C.addTo = null; C.checked.clear(); renderMakeCard(); renderVideoList(); });
  $('#clBase').addEventListener('change', e => { C.base = e.target.value; });
  $('#clVideoList').addEventListener('change', onVideoChange);
  $('#clGroupList').addEventListener('click', onGroupClick);
  $('#clGroupList').addEventListener('change', onGroupChange);
  S.on('step', st => { if (st === 'collab') refresh(); });
  refresh();
});
})();
