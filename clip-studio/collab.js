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
/* 2回押しの確認。実行したらすぐ元に戻す(以前は3秒間「確認済み」のままで、続けて押すともう一度実行されていた) */
function armDelete(btn, run, text){
  if (btn.dataset.armed){ clearTimeout(Number(btn.dataset.armT)); delete btn.dataset.armed; btn.textContent = btn.dataset.label; btn.classList.remove('solid'); run(); return; }
  btn.dataset.label = btn.textContent; btn.dataset.armed = '1'; btn.textContent = text || 'もう一度押すと削除'; btn.classList.add('solid');
  btn.dataset.armT = String(setTimeout(() => { if (btn.isConnected && btn.dataset.armed){ delete btn.dataset.armed; btn.textContent = btn.dataset.label; btn.classList.remove('solid'); } }, 3000));
}

/* addTo: 既存グループに動画を追加するモード中は、そのグループID。anchorOpen: 開いているアンカー指定フォーム({gid, videoId}) */
const C = { videos: [], groups: [], checked: new Set(), base: null, addTo: null, anchorOpen: null, seq: 0, busy: false, loaded: false };

function paneHtml(){
  return `
  <div class="cl-grid">
  <section class="card" id="clMake">
    <div class="card-head"><h2 class="card-title" id="clMakeTitle">動画をコラボにまとめる</h2></div>
    <p class="hint cl-sub" id="clMakeSub"></p>
    <div class="cs-opts" id="clBaseRow">
      <label class="cs-opt"><span class="l">基準にする動画</span><select id="clBase"></select></label>
      <label class="cs-opt cl-name"><span class="l">グループ名(任意)</span><input type="text" id="clName" maxlength="120" placeholder="例: 9/20 マリオカート部屋" autocomplete="off"></label>
    </div>
    <div class="cl-vlist" id="clVideoList"><div class="ui-skel" style="height:44px"></div><div class="ui-skel" style="height:44px;margin-top:6px"></div></div>
    <div class="row cl-acts">
      <button type="button" class="btn primary" id="clGo" disabled>選んだ動画をまとめる</button>
      <button type="button" class="btn" id="clCancelAdd" hidden>キャンセル</button>
      <span class="hint" id="clMsg"></span>
    </div>
  </section>
  <section class="card" id="clGroups">
    <div class="card-head"><h2 class="card-title">コラボグループ</h2><span class="card-sub">採用したマークを、同じグループの他の動画へ候補として転写します</span></div>
    <div id="clGroupList"></div>
  </section>
  </div>`;
}
const EMPTY_GROUPS = '<div class="empty"><b>まだグループがありません</b>左で2本以上の動画を選んで「まとめる」か、② 解析で「コラボとしてまとめる」をオンにして追加してください。</div>';

/* ---------- 動画の選択(上のカード) ---------- */
function vlabel(v){ return v.title || v.fileName || v.id; }
function videoRowHtml(v){
  const grouped = !!v.groupId, dis = grouped ? ' disabled' : '';
  const checked = C.checked.has(v.id) ? ' checked' : '';
  const badge = grouped ? '<span class="pill wait">すでにグループ済み</span>' : (v.duration ? '' : '<span class="pill wait">解析前</span>');
  return `<label class="cl-video${grouped ? ' is-grouped' : ''}${C.checked.has(v.id) ? ' is-checked' : ''}">
    <input type="checkbox" data-vid="${esc(v.id)}"${checked}${dis} aria-label="${esc(vlabel(v))}を選ぶ">
    <span class="cl-vmain"><span class="cl-vtitle">${esc(vlabel(v))}</span>
      <span class="cl-vmeta">${v.kind === 'file' ? 'ファイル' : esc(v.channel || '')} ・ <span class="mono">${esc(v.id)}</span>${v.duration ? ' ・ <span class="num">' + fmt(v.duration) + '</span>' : ''}</span></span>
    ${badge}</label>`;
}
function renderVideoList(){
  const box = $('#clVideoList'); if (!box) return;
  box.innerHTML = C.videos.length ? C.videos.map(videoRowHtml).join('')
    : '<div class="empty"><b>動画がありません</b>② 解析、または ③ 確認・書き出しから動画を登録してください。</div>';
  renderBaseSelect();
}
function renderBaseSelect(){
  const ids = [...C.checked];
  if (C.addTo){
    $('#clGo').disabled = !ids.length || C.busy;
    return;
  }
  const sel = $('#clBase');
  if (!ids.length){ sel.innerHTML = '<option value="">(2本以上選ぶ)</option>'; sel.disabled = true; $('#clGo').disabled = true; return; }
  sel.disabled = false;
  if (!ids.includes(C.base)) C.base = ids[0];
  sel.innerHTML = ids.map(id => { const v = C.videos.find(x => x.id === id); return `<option value="${esc(id)}"${id === C.base ? ' selected' : ''}>${esc(v ? vlabel(v) : id)}</option>`; }).join('');
  $('#clGo').disabled = ids.length < 2 || C.busy;
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
  return `<div class="cl-anchor">
    <p class="hint">両方の動画で「同じ瞬間」を見つけて、その時刻を入力してください(例: 1:23.5、1時間以上は 1:02:03.5)。2点目も指定すると、配信中のわずかなズレの変化(ドリフト)も補正できます。</p>
    <div class="cl-apoints">
      <span class="cl-plabel">点1</span>
      <label class="cs-opt"><span class="l">この動画 <span class="muted">${esc(m.title || m.id)}</span></span><input type="text" class="mono" id="clA1this" placeholder="0:00.0" autocomplete="off"></label>
      <label class="cs-opt"><span class="l">基準 <span class="muted">${esc(baseTitle(g))}</span></span><input type="text" class="mono" id="clA1ref" placeholder="0:00.0" autocomplete="off"></label>
    </div>
    <label class="lag cl-a2" for="clA2on"><input type="checkbox" class="ui-switch" id="clA2on">2点目も指定する</label>
    <div class="cl-apoints" id="clA2row" hidden>
      <span class="cl-plabel">点2</span>
      <label class="cs-opt"><span class="l">この動画</span><input type="text" class="mono" id="clA2this" placeholder="0:00.0" autocomplete="off"></label>
      <label class="cs-opt"><span class="l">基準</span><input type="text" class="mono" id="clA2ref" placeholder="0:00.0" autocomplete="off"></label>
    </div>
    <div class="row cl-acts"><button type="button" class="btn primary" data-act="saveAnchor">計算して保存</button>
      <button type="button" class="btn ghost" data-act="cancelAnchor">キャンセル</button><span class="hint cl-amsg" id="clAnchorMsg" role="status"></span></div>
  </div>`;
}
function memberRowHtml(g, m){
  const open = C.anchorOpen && C.anchorOpen.gid === g.id && C.anchorOpen.videoId === m.id;
  let h = `<li class="cl-member${open ? ' is-open' : ''}${m.isBase ? ' is-base' : ''}" data-gid="${esc(g.id)}" data-vid="${esc(m.id)}"><div class="cl-mh">
    <span class="cl-mtitle">${esc(m.title || m.id)}</span>${!m.exists ? '<span class="pill">削除済み</span>' : ''}
    ${m.isBase ? '<span class="pill accent">基準</span>'
      : (m.offsetSet ? `<span class="pill ok" title="${esc(offsetText(m.offset))}">ズレ設定済み <span class="num">${esc(offsetText(m.offset))}</span></span>` : '<span class="pill warn">ズレ未設定</span>')}
    <span class="spacer"></span>`;
  if (!m.isBase) h += `<button type="button" class="btn small${m.offsetSet ? '' : ' soft'}" data-act="anchor" aria-expanded="${open}">${m.offsetSet ? 'アンカーを設定し直す' : 'アンカーを指定'}</button>`;
  h += `<button type="button" class="btn small ghost danger" data-act="removeMember" title="${m.isBase ? '基準の動画を外すと、グループごと削除されます' : 'この動画をグループから外します(転写済みのマークは残ります)'}">グループから外す</button></div>`;
  if (open) h += anchorFormHtml(g, m);
  h += '</li>';
  return h;
}
function groupHtml(g){
  return `<div class="cl-group" data-gid="${esc(g.id)}">
    <div class="cl-ghead">
      <b class="cl-gname">${esc(g.name || '(名称未設定)')}</b><span class="pill ${g.allSet ? 'ok' : 'warn'}">${g.allSet ? 'ズレ設定済み' : 'ズレ未設定あり'}</span><span class="card-sub num">${g.members.length}本</span>
      <span class="spacer"></span>
      <button type="button" class="btn small ghost" data-act="addMore">動画を追加</button>
      <button type="button" class="btn small ghost danger" data-act="deleteGroup">グループを削除</button>
    </div>
    <ol class="cl-members">${g.members.map(m => memberRowHtml(g, m)).join('')}</ol>
  </div>`;
}
function renderGroups(){
  const box = $('#clGroupList'); if (!box) return;
  box.innerHTML = C.groups.length ? C.groups.map(groupHtml).join('') : EMPTY_GROUPS;
}

/* ---------- 操作 ---------- */
async function refresh(){
  const my = ++C.seq;
  let vr, gr;
  try { [vr, gr] = await Promise.all([S.api('/api/videos'), S.api('/api/collab/groups')]); }
  catch (e){ if (my === C.seq) S.toast(e.message, 0, 'err'); return; }
  if (my !== C.seq) return;   // 続けて呼ばれたとき、古い応答で新しい一覧を上書きしない
  C.loaded = true;
  C.videos = vr.videos || []; C.groups = gr.groups || [];
  for (const id of [...C.checked]) if (!C.videos.some(v => v.id === id)) C.checked.delete(id);
  if (C.addTo && !C.groups.some(g => g.id === C.addTo)) C.addTo = null;
  if (C.anchorOpen && !C.groups.some(g => g.id === C.anchorOpen.gid)) C.anchorOpen = null;
  renderMakeCard(); renderVideoList(); renderGroups();
  S.setBadge('collab', (() => { const n = C.groups.filter(g => !g.allSet).length; return n ? String(n) : ''; })());
}
async function onGo(){
  if (C.busy) return;
  C.busy = true; $('#clGo').disabled = true;
  try { await doGo(); } finally { C.busy = false; renderBaseSelect(); }
}
async function doGo(){
  const ids = [...C.checked];
  if (C.addTo){
    if (!ids.length) return S.toast('追加する動画を選んでください');
    try {
      await S.api('/api/collab/group/add', { body: { id: C.addTo, videoIds: ids } });
      S.toast(`${ids.length}本を追加しました`, 0, 'ok');
      C.checked.clear(); C.addTo = null;
      await refresh();
    } catch (e){ S.toast(e.message, 0, 'err'); }
    return;
  }
  if (ids.length < 2) return S.toast('2本以上選んでください');
  try {
    await S.api('/api/collab/group', { body: { videoIds: ids, name: $('#clName').value, base: C.base } });
    S.toast('コラボのグループにまとめました。「コラボグループ」でズレ(アンカー点)を指定してください', 6000, 'ok');
    C.checked.clear(); $('#clName').value = '';
    await refresh();
  } catch (e){ S.toast(e.message, 0, 'err'); }
}
function onVideoChange(e){
  const cb = e.target.closest('input[type=checkbox][data-vid]'); if (!cb) return;
  if (cb.checked) C.checked.add(cb.dataset.vid); else C.checked.delete(cb.dataset.vid);
  const row = cb.closest('.cl-video'); if (row) row.classList.toggle('is-checked', cb.checked);
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
  const btn = document.querySelector('[data-act="saveAnchor"]');
  if (btn){ if (btn.disabled) return; btn.disabled = true; }
  try {
    await S.api('/api/collab/anchor', { body: { id: gid, videoId: vid, points } });
    S.toast('ズレを保存しました', 0, 'ok');
    C.anchorOpen = null;
    await refresh();
  } catch (e){ msg.textContent = e.message; if (btn && btn.isConnected) btn.disabled = false; }
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
      try { await S.api('/api/collab/group/delete', { body: { id: gid } }); S.toast('グループを削除しました', 0, 'ok'); await refresh(); }
      catch (er){ S.toast(er.message, 0, 'err'); }
    });
  } else if (act === 'removeMember'){
    /* 以前は1回押すとすぐ外れていた。基準の動画を外す・残り1本になるとグループごと消えてズレの指定も失われるので、2回押しで確認する */
    const g = C.groups.find(x => x.id === gid), m = g && g.members.find(x => x.id === vid);
    const lose = !!(m && m.isBase) || !!(g && g.members.length <= 2);
    armDelete(b, async () => {
      try {
        const r = await S.api('/api/collab/group/remove', { body: { id: gid, videoId: vid } });
        S.toast(r.deleted ? 'グループから外しました(基準の動画を外した、または残り1本になったため、グループごと削除しました)' : 'グループから外しました', 6000, 'ok');
        await refresh();
      } catch (er){ S.toast(er.message, 0, 'err'); }
    }, lose ? 'もう一度押すとグループごと削除' : 'もう一度押すと外す');
  } else if (act === 'anchor'){
    C.anchorOpen = (C.anchorOpen && C.anchorOpen.gid === gid && C.anchorOpen.videoId === vid) ? null : { gid, videoId: vid };
    renderGroups();
    const f = $('#clA1this'); if (f && C.anchorOpen) f.focus();
  } else if (act === 'cancelAnchor'){
    C.anchorOpen = null; renderGroups();
  } else if (act === 'saveAnchor'){
    saveAnchor(gid, vid);
  }
}
function onGroupChange(e){
  if (e.target.id === 'clA2on'){
    const row = e.target.closest('.cl-anchor').querySelector('#clA2row');
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
  $('#clGroupList').addEventListener('keydown', e => {   // 時刻の欄で Enter を押したら保存
    if (e.key !== 'Enter' || !e.target.closest('.cl-anchor') || e.target.type !== 'text') return;
    e.preventDefault(); const li = e.target.closest('[data-gid][data-vid]'); if (li) saveAnchor(li.dataset.gid, li.dataset.vid);
  });
  S.on('step', st => { if (st === 'collab') refresh(); });
  refresh();
});
})();
