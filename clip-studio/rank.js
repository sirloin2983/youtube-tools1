/* 切り抜きスタジオ: ① 探す(配信ランキング)。検索 → 事務所ごとの結果 → チェックして「解析に追加」 */
(() => {
'use strict';
const S = window.Studio, esc = S.esc;
const $ = s => document.querySelector(s);
const MAX_PICK = 10;
const LS = 'clipstudio:rank:';
const lsGet = k => { try { return JSON.parse(localStorage.getItem(LS + k)); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(LS + k, JSON.stringify(v)); } catch {} };
const fmtN = n => Number(n).toLocaleString('ja-JP');
const fmtDur = s => { const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); };
const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const okThumb = u => /^https:\/\/([\w-]+\.)?ytimg\.com\//.test(u || '');
const okId = i => /^[\w-]{11}$/.test(i || '');

const R = { reg: { agencies: [] }, job: null, result: null, poll: null, picked: new Map(), inQueue: new Set(), analyzed: new Set(), regEls: [] };

/* ================= 所属の登録(設定パネルに置く) ================= */
let saveT = null;
function saveReg(now){
  clearTimeout(saveT);
  const run = async () => { try { R.reg = await S.api('/api/rank/registry', { method: 'PUT', body: R.reg }); } catch (e){ S.toast('保存に失敗: ' + e.message); } renderReg(); renderAgChecks(); };
  if (now) return run(); saveT = setTimeout(run, 500);
}
function renderReg(){
  const open = new Set(); document.querySelectorAll('.reg-host .ag[open]').forEach(d => open.add(d.dataset.i));
  const html = `<p class="hint" style="margin:0">各事務所に所属するチャンネルを登録します。@ハンドル・チャンネルID(UC…)・YouTubeのURL(…/@name、…/channel/UC…)を1行に1つ貼り付けられます。登録後に「解決」を押すと、チャンネルIDとチャンネル名が確定します。登録したチャンネルだけが検索の対象になります。</p>` +
  R.reg.agencies.map((a, i) => {
    const bad = a.channels.filter(c => c.status !== 'ok').length;
    return `<details class="ag" style="margin-top:12px" data-i="${i}"${open.has(String(i)) ? ' open' : ''}><summary>${esc(a.name)}<span class="sub">${a.channels.length - bad}チャンネル解決済み${bad ? ` ・ <b style="color:var(--warn)">${bad}件が未解決</b>` : ''}</span></summary>
    <div class="fld"><label class="l">公式チャンネル(所属チャンネルの取り込みに使います。@ハンドルかURL。空白区切りで複数可)<input type="text" class="off" value="${esc(a.official.join(' '))}" maxlength="200" placeholder="@hololive" style="margin-top:3px"></label>
      <div style="margin-top:6px"><button type="button" class="btn small" data-act="imp">公式から取り込む</button></div></div>
    <div class="fld"><label class="l">チャンネルを追加(1行に1つ)<textarea class="paste" rows="3" placeholder="@handle&#10;https://www.youtube.com/@handle&#10;UCxxxxxxxxxxxxxxxxxxxxxx" style="margin-top:3px"></textarea></label>
      <div class="row" style="margin-top:6px"><button type="button" class="btn small primary" data-act="add">追加して解決</button><button type="button" class="btn small" data-act="res">未解決を解決</button><button type="button" class="btn small danger" data-act="delag">この事務所を削除</button></div></div>
    <div style="margin-top:8px">${a.channels.map((c, k) => `<div class="ch" data-k="${k}"><span class="st ${esc(c.status)}">${c.status === 'ok' ? '解決済' : c.status === 'error' ? '失敗' : '未解決'}</span><span style="flex:1;min-width:0;overflow-wrap:anywhere">${esc(c.title || c.ref)}${c.note ? ` <span class="hint">${esc(c.note)}</span>` : ''}</span><span class="rf hide-s">${esc(c.ref)}</span><button type="button" class="btn small" data-act="delch">外す</button></div>`).join('') || '<p class="hint" style="margin:4px 0 0">まだチャンネルがありません</p>'}</div></details>`;
  }).join('') || '<p class="hint">事務所がありません</p>';
  const add = `<div class="row" style="margin-top:10px"><label class="hint" for="newAgency">事務所を追加</label><input type="text" id="newAgency" placeholder="例: ○○プロダクション" maxlength="40" style="max-width:320px"><button type="button" class="btn small" data-act="addag">追加</button></div>`;
  for (const el of R.regEls){
    const keep = el.querySelector('#newAgency') ? el.querySelector('#newAgency').value : '';
    el.innerHTML = html + add; if (keep) el.querySelector('#newAgency').value = keep;
  }
}
async function callResolve(agency, label){
  S.toast(label + '…');
  try { const r = await S.api('/api/rank/resolve', { body: { agency } }); R.reg = r.registry; S.toast(`${r.tried}件を確認: ${r.resolved}件を解決しました`); } catch (e){ S.toast(e.message); }
  renderReg(); renderAgChecks(); S.refreshState().catch(() => {});
}
function regClick(e){
  const b = e.target.closest('[data-act]'); if (!b) return;
  const act = b.dataset.act;
  if (act === 'addag'){
    const inp = b.closest('.row').querySelector('#newAgency'), n = inp.value.trim(); if (!n) return;
    R.reg.agencies.push({ id: '', name: n, official: [], channels: [] }); inp.value = ''; saveReg(true); return;
  }
  const box = b.closest('.ag'); if (!box) return;
  const a = R.reg.agencies[Number(box.dataset.i)], id = a.id;
  if (act === 'add'){
    const lines = box.querySelector('.paste').value.split(/\r?\n/).map(x => x.trim()).filter(Boolean); if (!lines.length) return;
    const before = a.channels.length;
    for (const l of lines) a.channels.push({ ref: l });
    saveReg(true).then(async () => {
      const skipped = lines.length - ((R.reg.agencies.find(x => x.id === id)?.channels.length || 0) - before);
      if (skipped > 0) S.toast(`${skipped}行は、重複か、読み取れない形式のため追加しませんでした(@ハンドル・UC…のID・youtube.com/@… か /channel/… のURLだけ使えます)`, 7000);
      await callResolve(id, 'チャンネルを確認中');
    });
  } else if (act === 'res') callResolve(id, '未解決のチャンネルを確認中');
  else if (act === 'imp'){
    b.disabled = true; S.toast('公式チャンネルから取り込み中…');
    saveReg(true).then(() => S.api('/api/rank/import-official', { body: { agency: id } }))
      .then(r => { R.reg = r.registry; S.toast(`${r.added}件を取り込みました` + (r.notes.length ? '。' + r.notes.join(' / ') : ''), 7000); })
      .catch(er => S.toast(er.message)).finally(() => { renderReg(); renderAgChecks(); S.refreshState().catch(() => {}); });
  } else if (act === 'delch'){ a.channels.splice(Number(b.closest('.ch').dataset.k), 1); saveReg(true); }
  else if (act === 'delag'){
    if (b.dataset.arm){ R.reg.agencies.splice(Number(box.dataset.i), 1); saveReg(true); }
    else { b.dataset.arm = '1'; b.textContent = '本当に削除する'; setTimeout(() => { b.dataset.arm = ''; b.textContent = 'この事務所を削除'; }, 3000); }
  }
}
function regInput(e){
  if (!e.target.matches('.off')) return;
  const a = R.reg.agencies[Number(e.target.closest('.ag').dataset.i)]; a.official = e.target.value.split(/\s+/).filter(Boolean); saveReg();
}
function mountRegistry(el){
  if (!R.regEls.includes(el)){ R.regEls.push(el); el.classList.add('reg-host'); el.addEventListener('click', regClick); el.addEventListener('input', regInput); }
  renderReg();
}

/* ================= 検索条件 ================= */
function paneHtml(){
  return `
  <div id="rkSetupNotice" class="notice" hidden><b>最初に、対象の事務所のチャンネルを登録します。</b><br>設定 → 事務所の登録 →「公式から取り込む」(ホロライブ・にじさんじ・ぶいすぽっ!)。ネオポルテは公式の一覧がないので、チャンネルのURL(または @ハンドル)を入れて「追加して解決」<br><button type="button" class="btn small" id="rkOpenReg">事務所の登録を開く</button></div>
  <div id="rkKeyNotice" class="notice" hidden><b>YouTube Data API のキーが未設定です。</b> 配信を検索するにはキーが必要です(URLを直接入れて解析する場合は不要です)。<br><button type="button" class="btn small" id="rkOpenSet">設定を開く</button></div>
  <section class="card" id="rkCond">
    <h2>配信を探す</h2>
    <div class="row">
      <label class="lag wrap">期間 <input type="date" id="dStart"> 〜 <input type="date" id="dEnd"></label>
      <button type="button" class="btn small" data-days="7">直近7日</button><button type="button" class="btn small" data-days="30">直近30日</button><button type="button" class="btn small" data-days="90">直近90日</button>
      <button type="button" class="btn small" data-m="0">今月</button><button type="button" class="btn small" data-m="1">先月</button></div>
    <div class="fld"><label class="l" for="words">ワード(空白かカンマで区切る。空なら人気順だけ)</label><input type="text" id="words" placeholder="例: マイクラ 歌枠" maxlength="200" autocomplete="off"></div>
    <div class="row" style="margin-top:8px">
      <label class="lag">一致 <select id="mode"><option value="any">どれか1つを含む</option><option value="all">すべて含む</option></select></label>
      <label class="lag">探す場所 <select id="inDesc"><option value="1">タイトル+概要欄</option><option value="0">タイトルだけ</option></select></label>
      <label class="lag">1事務所の表示 <select id="top"><option>10</option><option selected>20</option><option>50</option><option>100</option></select>本</label>
      <label class="lag">最低再生数 <input type="number" id="minViews" min="0" step="1000" value="0" style="width:110px"></label></div>
    <div class="row" style="margin-top:8px">
      <label class="lag"><input type="checkbox" id="archiveOnly" checked>配信アーカイブだけ(通常の投稿動画を除く)</label>
      <label class="lag"><input type="checkbox" id="noShorts" checked>ショート動画を除く</label></div>
    <div class="fld"><span class="l">対象の事務所(登録は「設定」の「事務所の登録」)</span><div class="chips" id="agChecks" role="group" aria-label="対象の事務所"></div></div>
    <div class="row" style="margin-top:12px"><button type="button" class="btn primary" id="btnGo">検索する</button><button type="button" class="btn" id="btnCancel" hidden>中止</button><span class="hint" id="phase" role="status"></span></div>
    <div class="bar" id="barWrap" hidden><i id="bar"></i></div>
  </section>
  <div class="card rk-sticky" id="pickBar" hidden><div class="row"><span><b id="pickN">0</b> 本選択中 <span class="hint">(最大${MAX_PICK}本まで)</span></span>
    <span class="row"><button type="button" class="btn small" id="pickClear">選択を外す</button><button type="button" class="btn primary" id="pickGo" disabled>選んだ配信 0 本を解析に追加</button></span></div></div>
  <div id="results"></div>`;
}
function renderAgChecks(){
  const box = $('#agChecks'); if (!box) return;
  const sn = $('#rkSetupNotice'); if (sn) sn.hidden = R.reg.agencies.some(a => a.channels.some(c => c.status === 'ok'));
  const cur = [...box.querySelectorAll('.agc')].map(x => x.value + (x.checked ? '1' : '0'));
  const sel = cur.length ? [...box.querySelectorAll('.agc:checked')].map(x => x.value) : lsGet('ags');
  box.innerHTML = R.reg.agencies.map(a => { const n = a.channels.filter(c => c.status === 'ok').length;
    return `<label class="lag"><input type="checkbox" class="agc" value="${esc(a.id)}"${(sel ? sel.includes(a.id) : n > 0) ? ' checked' : ''}>${esc(a.name)}<span class="hint">(${n})</span></label>`; }).join('') || '<span class="hint">事務所がありません</span>';
}
function setRange(a, b){ $('#dStart').value = ymd(a); $('#dEnd').value = ymd(b); }
function condBody(){
  return { start: $('#dStart').value, end: $('#dEnd').value, words: $('#words').value, mode: $('#mode').value, inDesc: $('#inDesc').value === '1', top: Number($('#top').value),
    minViews: Number($('#minViews').value) || 0, archiveOnly: $('#archiveOnly').checked, noShorts: $('#noShorts').checked, agencies: [...document.querySelectorAll('.agc:checked')].map(x => x.value) };
}
function saveCond(){ const c = condBody(); lsSet('cond', { words: c.words, mode: c.mode, inDesc: c.inDesc, top: c.top, minViews: c.minViews, archiveOnly: c.archiveOnly, noShorts: c.noShorts, start: c.start, end: c.end }); lsSet('ags', c.agencies); }
function setBusy(b){ $('#btnGo').disabled = b || noKey(); $('#btnCancel').hidden = !b; $('#barWrap').hidden = !b; if (!b) $('#phase').textContent = ''; }
const noKey = () => !(S.state && S.state.hasKey);
function keyNotice(){ $('#rkKeyNotice').hidden = !noKey(); $('#btnGo').disabled = noKey() || !$('#btnCancel').hidden; }

async function startSearch(){
  saveCond(); const body = condBody();
  if (!body.start || !body.end) return S.toast('期間(開始日・終了日)を入れてください');
  if (!body.agencies.length) return S.toast('対象の事務所を選んでください');
  setBusy(true); $('#results').innerHTML = ''; R.result = null; R.picked.clear(); paintPick();
  try { R.job = await S.api('/api/rank/search', { body }); } catch (e){ setBusy(false); return S.toast(e.message); }
  clearInterval(R.poll); R.poll = setInterval(pollJob, 700); pollJob();
}
async function pollJob(){
  let j; try { j = await S.api('/api/rank/search?id=' + encodeURIComponent(R.job.id)); } catch (e){ clearInterval(R.poll); setBusy(false); return S.toast(e.message); }
  $('#phase').textContent = j.phase; $('#bar').style.width = Math.round((j.progress || 0) * 100) + '%';
  if (j.state === 'running') return;
  clearInterval(R.poll); setBusy(false); S.refreshState().catch(() => {});
  if (j.state === 'error') return S.toast(j.error);
  if (j.state === 'cancelled') return S.toast('中止しました');
  R.result = j.result; await loadMarks(); renderResults();
}

/* ================= 結果 ================= */
function renderResults(){
  const r = R.result; if (!r) return;
  let html = '';
  if (r.unresolved) html += `<div class="notice">未解決のチャンネルが${r.unresolved}件あり、対象から外しています(設定の「事務所の登録」で確認できます)。</div>`;
  if (r.warnings.length) html += `<div class="notice">${r.warnings.map(esc).join('<br>')}</div>`;
  html += `<p class="hint" style="margin:8px 0">調べた動画: ${fmtN(r.videos)}本 ・ 使用ユニット: ${r.quota}(1日の目安 10,000) ・ 再生数は検索した時点の値です</p>`;
  html += r.agencies.map(a => `<section class="card"><details class="ag" open><summary>${esc(a.name)}<span class="sub">該当 ${fmtN(a.matched)}本 ・ 期間内の配信 ${fmtN(a.scanned)}本 ・ ${a.channels}チャンネル</span></summary>
    ${a.channels === 0 ? '<p class="hint" style="margin:8px 0 0">解決済みのチャンネルがありません。設定の「事務所の登録」で追加してください。</p>' : !a.items.length ? '<p class="hint" style="margin:8px 0 0">条件に合う配信アーカイブがありませんでした。</p>' :
    `<div class="tbl-wrap"><table><thead><tr><th><span class="sr-only" style="position:absolute;left:-9999px">選択</span></th><th>#</th><th class="hide-s"></th><th>タイトル</th><th class="n">再生数</th><th class="n hide-s">高評価</th><th class="hide-s">配信日時</th><th class="n hide-s">長さ</th></tr></thead><tbody>${a.items.map((v, i) => row(v, i)).join('')}</tbody></table></div>`}
    </details></section>`).join('');
  $('#results').innerHTML = html; paintRows(); paintPick();
}
function row(v, i){
  const id = okId(v.id), link = id ? 'https://www.youtube.com/watch?v=' + encodeURIComponent(v.id) : '';
  return `<tr data-vid="${esc(v.id)}"><td class="ck">${id ? `<input type="checkbox" class="pk" aria-label="解析に追加する: ${esc(v.title)}" data-id="${esc(v.id)}" data-title="${esc(v.title)}" data-channel="${esc(v.channel)}">` : ''}</td><td class="rk mono">${i + 1}</td>
    <td class="hide-s">${okThumb(v.thumb) && id ? `<a href="${link}" target="_blank" rel="noopener noreferrer"><img loading="lazy" src="${esc(v.thumb)}" alt=""></a>` : ''}</td>
    <td class="tt">${id ? `<a href="${link}" target="_blank" rel="noopener noreferrer">${esc(v.title)}</a>` : esc(v.title)}<div class="hint">${esc(v.channel)}</div>
      ${id ? `<div class="row"><button type="button" class="btn small add1" data-id="${esc(v.id)}" data-title="${esc(v.title)}" data-channel="${esc(v.channel)}">解析に追加</button><span class="chip"></span></div>` : ''}</td>
    <td class="n mono">${fmtN(v.views)}</td><td class="n mono hide-s">${fmtN(v.likes)}</td><td class="mono hide-s">${esc(v.at)}</td><td class="n mono hide-s">${fmtDur(v.dur)}</td></tr>`;
}
/* 「解析済み」「キューにあります」の印と、チェックの有効/無効 */
function paintRows(){
  const full = R.picked.size >= MAX_PICK;
  document.querySelectorAll('#results tr[data-vid]').forEach(tr => {
    const id = tr.dataset.vid, q = R.inQueue.has(id), d = R.analyzed.has(id);
    tr.querySelector('.chip').innerHTML = q ? '<span class="pill run">キューにあります</span>' : d ? '<span class="pill ok">解析済み</span>' : '';
    const cb = tr.querySelector('.pk'); if (cb){ cb.checked = R.picked.has(id); cb.disabled = q || (full && !cb.checked); }
    const b = tr.querySelector('.add1'); if (b) b.disabled = q;
  });
}
function paintPick(){
  const n = R.picked.size, bar = $('#pickBar'); if (!bar) return;
  bar.hidden = !R.result;
  $('#pickN').textContent = n; const g = $('#pickGo'); g.textContent = `選んだ配信 ${n} 本を解析に追加`; g.disabled = !n;
  paintRows();
}
async function loadMarks(){
  try {
    const [q, v] = await Promise.all([S.api('/api/queue'), S.api('/api/videos')]);
    R.inQueue = new Set(q.items.filter(i => i.status === 'waiting' || i.status === 'running').map(i => i.videoId));
    R.analyzed = new Set(v.videos.filter(x => x.analysis || x.marks > 0).map(x => x.id));
  } catch {}
}
async function refreshMarks(){ await loadMarks(); paintRows(); }
async function enqueue(items){
  if (!S.enqueue) return S.toast('解析画面がまだ読み込まれていません。ページを開き直してください');
  try {
    const r = await S.enqueue(items);
    if (r && r.added && r.added.length){ for (const it of items) R.picked.delete(it.videoId); }
  } catch (e){ S.toast(e.message); }
  await refreshMarks(); paintPick();
}

/* ================= 起動 ================= */
S.rank = { mountRegistry, refresh: refreshMarks };
S.onReady(async () => {
  const pane = $('#paneRank'); pane.innerHTML = paneHtml();
  const c = lsGet('cond');
  if (c){ $('#words').value = c.words || ''; $('#mode').value = c.mode || 'any'; $('#inDesc').value = c.inDesc === false ? '0' : '1'; if ([10, 20, 50, 100].includes(c.top)) $('#top').value = c.top; $('#minViews').value = c.minViews || 0; $('#archiveOnly').checked = c.archiveOnly !== false; $('#noShorts').checked = c.noShorts !== false; }
  if (c && /^\d{4}-\d\d-\d\d$/.test(c.start || '') && /^\d{4}-\d\d-\d\d$/.test(c.end || '')) setRange(new Date(c.start + 'T00:00:00'), new Date(c.end + 'T00:00:00'));
  else { const e = new Date(), s = new Date(); s.setDate(s.getDate() - 29); setRange(s, e); }
  document.querySelectorAll('[data-days]').forEach(b => b.addEventListener('click', () => { const e = new Date(), s = new Date(); s.setDate(s.getDate() - (Number(b.dataset.days) - 1)); setRange(s, e); }));
  document.querySelectorAll('[data-m]').forEach(b => b.addEventListener('click', () => { const n = new Date(), k = Number(b.dataset.m); setRange(new Date(n.getFullYear(), n.getMonth() - k, 1), k ? new Date(n.getFullYear(), n.getMonth(), 0) : n); }));
  ['words', 'mode', 'inDesc', 'top', 'minViews', 'archiveOnly', 'noShorts', 'dStart', 'dEnd'].forEach(id => $('#' + id).addEventListener('change', saveCond));
  $('#agChecks').addEventListener('change', saveCond);
  $('#btnGo').addEventListener('click', startSearch);
  $('#btnCancel').addEventListener('click', () => { if (R.job) S.api('/api/rank/search/cancel', { body: { id: R.job.id } }).catch(() => {}); });
  $('#rkOpenSet').addEventListener('click', () => { if (S.openSettings) S.openSettings('setKey'); else { $('#settingsBox').open = true; $('#settingsBox').scrollIntoView(); } });
  $('#rkOpenReg').addEventListener('click', () => S.openSettings('setReg'));
  $('#pickClear').addEventListener('click', () => { R.picked.clear(); paintPick(); });
  $('#pickGo').addEventListener('click', () => enqueue([...R.picked.values()]));
  $('#results').addEventListener('change', e => {
    const cb = e.target.closest('.pk'); if (!cb) return;
    if (cb.checked){ if (R.picked.size >= MAX_PICK){ cb.checked = false; return S.toast('一度に選べるのは最大10本です'); } R.picked.set(cb.dataset.id, { kind: 'youtube', videoId: cb.dataset.id, title: cb.dataset.title, channel: cb.dataset.channel }); }
    else R.picked.delete(cb.dataset.id);
    paintPick();
  });
  $('#results').addEventListener('click', e => {
    const b = e.target.closest('.add1'); if (!b) return;
    enqueue([{ kind: 'youtube', videoId: b.dataset.id, title: b.dataset.title, channel: b.dataset.channel }]);
  });
  keyNotice(); S.on('state', keyNotice);
  S.on('step', st => { if (st === 'rank') refreshMarks(); });
  try { R.reg = await S.api('/api/rank/registry'); } catch (er){ S.showErr(er.message); }
  renderReg(); renderAgChecks();
  await loadMarks(); paintRows();
});
})();
