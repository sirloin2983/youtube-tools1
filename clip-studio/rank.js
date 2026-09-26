/* 切り抜きスタジオ: ① 探す(配信ランキング)。検索 → 結果(全部まとめて再生数の順 / 事務所ごと)→ チェックして「解析に追加」 */
(() => {
'use strict';
const S = window.Studio, esc = S.esc;
const $ = s => document.querySelector(s);
const MAX_PICK = 10;
const LS = 'clipstudio:rank:';
const lsGet = k => { try { return JSON.parse(localStorage.getItem(LS + k)); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(LS + k, JSON.stringify(v)); } catch {} };
const fmtN = n => (Number.isFinite(Number(n)) ? Number(n).toLocaleString('ja-JP') : '-');
const fmtDur = s => { s = Math.max(0, Math.round(Number(s) || 0)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); };
const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const okThumb = u => /^https:\/\/([\w-]+\.)?ytimg\.com\//.test(u || '');
const okId = i => /^[\w-]{11}$/.test(i || '');
/* 検索結果の配信日時("2026-09-20 21:00"。日本時間)→ ミリ秒(読めなければ 0) */
const atMs = at => { const m = /^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d)$/.exec(at || ''); return m ? Date.parse(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00+09:00`) || 0 : 0; };
const LIMITS = [10, 30, 50, 100, 0];   // 「全部まとめて」の上位の本数(0 = すべて)

/* busy: 解決・取り込みの実行中の事務所ID(同じ事務所への二重実行で API のクォータを無駄にしないため) */
/* agPick: ユーザーが自分でチェックを変えた事務所だけ {事務所ID: true/false}。触っていない事務所は「解決済みのチャンネルがあれば選ぶ」。
   以前は画面の未チェックの状態から選択を決めていたため、事務所を登録してから ① に戻ると、件数は出ているのに全部外れていた */
const R = { reg: { agencies: [] }, job: null, result: null, poll: null, polling: false, picked: new Map(), inQueue: new Set(), analyzed: new Set(), regEls: [], busy: new Set(),
  agPick: {}, view: 'all', limit: 30, q: '' };

/* ================= 所属の登録(設定の引き出しに置く) ================= */
let saveT = null;
function saveReg(now){
  clearTimeout(saveT);
  const run = async () => { try { R.reg = await S.api('/api/rank/registry', { method: 'PUT', body: R.reg }); } catch (e){ S.toast('保存に失敗: ' + e.message, 0, 'err'); } renderReg(); renderAgChecks(); };
  if (now) return run(); saveT = setTimeout(run, 500);
}
const agKey = (a, i) => a.id || 'new-' + i;
/* 作り直しの前後で、入力途中の文字・フォーカス・開閉を引き継ぐ。
   以前は「公式チャンネル」欄の自動保存(0.5秒後)で全体を作り直していたため、入力中のカーソルと「チャンネルを追加」欄の書きかけが消えていた */
function captureReg(el){
  const st = { open: new Set(), paste: new Map(), off: new Map(), focus: null, newAgency: '' };
  el.querySelectorAll('.ag').forEach(d => {
    const k = d.dataset.key;
    if (d.open) st.open.add(k);
    const p = d.querySelector('.paste'); if (p && p.value) st.paste.set(k, p.value);
    const o = d.querySelector('.off'); if (o && document.activeElement === o) st.off.set(k, o.value);
  });
  const na = el.querySelector('.newAgency'); if (na) st.newAgency = na.value;
  const a = document.activeElement;
  if (a && el.contains(a)){
    const box = a.closest('.ag');
    st.focus = { key: box ? box.dataset.key : '', cls: ['paste', 'off', 'newAgency'].find(c => a.classList.contains(c)) || '', ss: a.selectionStart, se: a.selectionEnd };
  }
  return st;
}
function restoreReg(el, st){
  el.querySelectorAll('.ag').forEach(d => {
    const k = d.dataset.key;
    if (st.paste.has(k)) d.querySelector('.paste').value = st.paste.get(k);
    if (st.off.has(k)) d.querySelector('.off').value = st.off.get(k);
  });
  const na = el.querySelector('.newAgency'); if (na && st.newAgency) na.value = st.newAgency;
  const f = st.focus;
  if (f && f.cls){
    const scope = f.key ? el.querySelector(`.ag[data-key="${CSS.escape(f.key)}"]`) : el;
    const t = scope && scope.querySelector('.' + f.cls);
    if (t){ t.focus({ preventScroll: true }); try { t.setSelectionRange(f.ss, f.se); } catch {} }
  }
}
function renderReg(){
  const html = `<p class="hint">各事務所に所属するチャンネルを登録します。@ハンドル・チャンネルID(UC…)・YouTubeのURL(…/@name、…/channel/UC…)を1行に1つ貼り付けられます。登録後に「解決」を押すと、チャンネルIDとチャンネル名が確定します。登録したチャンネルだけが検索の対象になります。</p>` +
  (R.reg.agencies.map((a, i) => {
    const bad = a.channels.filter(c => c.status !== 'ok').length, k = agKey(a, i), busy = R.busy.has(a.id) ? ' disabled' : '';
    return `<details class="ag" data-i="${i}" data-key="${esc(k)}"><summary><span class="ag-name">${esc(a.name)}</span>${a.channels.length ? `<span class="pill ok">${a.channels.length - bad}件 解決済み</span>` : '<span class="pill">チャンネル未登録</span>'}${bad ? `<span class="pill warn">${bad}件 未解決</span>` : ''}${R.busy.has(a.id) ? '<span class="pill run">確認中</span>' : ''}</summary>
    <div class="ag-body">
    <div class="fld"><label class="l">公式チャンネル(所属チャンネルの取り込みに使います。@ハンドルかURL。空白区切りで複数可)<input type="text" class="off" value="${esc(a.official.join(' '))}" maxlength="200" placeholder="@hololive"></label>
      <div class="row ag-acts"><button type="button" class="btn small" data-act="imp"${busy}>公式から取り込む</button></div></div>
    <div class="fld"><label class="l">チャンネルを追加(1行に1つ)<textarea class="paste" rows="3" placeholder="@handle&#10;https://www.youtube.com/@handle&#10;UCxxxxxxxxxxxxxxxxxxxxxx"></textarea></label>
      <div class="row ag-acts"><button type="button" class="btn small primary" data-act="add"${busy}>追加して解決</button><button type="button" class="btn small" data-act="res"${busy}>未解決を解決</button><span class="spacer"></span><button type="button" class="btn small danger" data-act="delag">この事務所を削除</button></div></div>
    <div class="ch-list">${a.channels.map((c, j) => `<div class="ch" data-k="${j}"><span class="st ${c.status === 'ok' ? 'ok' : c.status === 'error' ? 'error' : 'pending'}">${c.status === 'ok' ? '解決済' : c.status === 'error' ? '失敗' : '未解決'}</span><span class="ch-name">${esc(c.title || c.ref)}${c.note ? ` <span class="hint">${esc(c.note)}</span>` : ''}</span><span class="rf hide-s">${esc(c.ref)}</span><button type="button" class="btn small ghost" data-act="delch">外す</button></div>`).join('') || '<p class="hint ch-empty">まだチャンネルがありません</p>'}</div></div></details>`;
  }).join('') || '<div class="empty"><b>事務所がありません</b>下の欄から追加してください</div>');
  const add = `<div class="row ag-new"><label class="l" for="newAgency">事務所を追加</label><input type="text" id="newAgency" class="newAgency" placeholder="例: ○○プロダクション" maxlength="40"><button type="button" class="btn small" data-act="addag">追加</button></div>`;
  for (const el of R.regEls){
    const st = captureReg(el);
    el.innerHTML = html + add;
    el.querySelectorAll('.ag').forEach(d => { if (st.open.has(d.dataset.key)) d.open = true; });
    restoreReg(el, st);
  }
}
async function callResolve(agency, label){
  if (R.busy.has(agency)) return;
  R.busy.add(agency); renderReg();
  S.toast(label + '…');
  try { const r = await S.api('/api/rank/resolve', { body: { agency } }); R.reg = r.registry; S.toast(`${r.tried}件を確認: ${r.resolved}件を解決しました`, 0, 'ok'); } catch (e){ S.toast(e.message, 0, 'err'); }
  R.busy.delete(agency);
  renderReg(); renderAgChecks(); S.refreshState().catch(() => {});
}
function regClick(e){
  const b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
  const act = b.dataset.act;
  if (act === 'addag'){
    const inp = b.closest('.row').querySelector('.newAgency'), n = inp.value.trim(); if (!n) return inp.focus();
    R.reg.agencies.push({ id: '', name: n, official: [], channels: [] }); inp.value = ''; saveReg(true); return;
  }
  const box = b.closest('.ag'); if (!box) return;
  const a = R.reg.agencies[Number(box.dataset.i)]; if (!a) return;
  const id = a.id;
  if (act === 'add'){
    const ta = box.querySelector('.paste');
    const lines = ta.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean); if (!lines.length) return ta.focus();
    const before = a.channels.length;
    for (const l of lines) a.channels.push({ ref: l });
    ta.value = '';   // 保存後の作り直しで書きかけとして残さない(追加済み)
    saveReg(true).then(async () => {
      const skipped = lines.length - ((R.reg.agencies.find(x => x.id === id)?.channels.length || 0) - before);
      if (skipped > 0) S.toast(`${skipped}行は、重複か、読み取れない形式のため追加しませんでした(@ハンドル・UC…のID・youtube.com/@… か /channel/… のURLだけ使えます)`, 7000);
      await callResolve(id, 'チャンネルを確認中');
    });
  } else if (act === 'res') callResolve(id, '未解決のチャンネルを確認中');
  else if (act === 'imp'){
    if (R.busy.has(id)) return;
    R.busy.add(id); renderReg(); S.toast('公式チャンネルから取り込み中…');
    saveReg(true).then(() => S.api('/api/rank/import-official', { body: { agency: id } }))
      .then(r => { R.reg = r.registry; S.toast(`${r.added}件を取り込みました` + (r.notes.length ? '。' + r.notes.join(' / ') : ''), 7000, 'ok'); })
      .catch(er => S.toast(er.message, 0, 'err')).finally(() => { R.busy.delete(id); renderReg(); renderAgChecks(); S.refreshState().catch(() => {}); });
  } else if (act === 'delch'){ a.channels.splice(Number(b.closest('.ch').dataset.k), 1); saveReg(true); }
  else if (act === 'delag'){
    if (b.dataset.arm){ R.reg.agencies.splice(Number(box.dataset.i), 1); saveReg(true); }
    else { b.dataset.arm = '1'; b.textContent = '本当に削除する'; b.classList.add('solid'); setTimeout(() => { if (b.isConnected){ b.dataset.arm = ''; b.textContent = 'この事務所を削除'; b.classList.remove('solid'); } }, 3000); }
  }
}
function regInput(e){
  if (!e.target.matches('.off')) return;
  const a = R.reg.agencies[Number(e.target.closest('.ag').dataset.i)]; if (!a) return;
  a.official = e.target.value.split(/\s+/).filter(Boolean); saveReg();
}
function mountRegistry(el){
  if (!R.regEls.includes(el)){ R.regEls.push(el); el.classList.add('reg-host'); el.addEventListener('click', regClick); el.addEventListener('input', regInput); }
  renderReg();
}

/* ================= 検索条件 ================= */
function paneHtml(){
  return `
  <div id="rkSetupNotice" class="notice info cs-notice-act" hidden><div><b>最初に、対象の事務所のチャンネルを登録します。</b><br>設定 → 事務所の登録 →「公式から取り込む」(ホロライブ・にじさんじ・ぶいすぽっ!)。ネオポルテは公式の一覧がないので、チャンネルのURL(または @ハンドル)を入れて「追加して解決」</div><button type="button" class="btn small" id="rkOpenReg">事務所の登録を開く</button></div>
  <div id="rkKeyNotice" class="notice cs-notice-act" hidden><div><b>YouTube Data API のキーが未設定です。</b> 配信を検索するにはキーが必要です(URLを直接入れて解析する場合は不要です)。</div><button type="button" class="btn small" id="rkOpenSet">設定を開く</button></div>
  <section class="card cs-search" id="rkCond">
    <div class="card-head"><h2 class="card-title">配信を探す</h2><span class="card-sub">登録した事務所の、期間内の配信アーカイブを再生数の多い順に並べます</span></div>
    <div class="cs-search-grid">
      <div class="fld cs-period"><span class="l">期間</span>
        <div class="row cs-dates"><input type="date" id="dStart" aria-label="開始日"><span class="muted">〜</span><input type="date" id="dEnd" aria-label="終了日"></div>
        <div class="cs-quick" role="group" aria-label="期間の早見"><button type="button" class="btn small ghost" data-days="7">直近7日</button><button type="button" class="btn small ghost" data-days="30">直近30日</button><button type="button" class="btn small ghost" data-days="90">直近90日</button><button type="button" class="btn small ghost" data-m="0">今月</button><button type="button" class="btn small ghost" data-m="1">先月</button></div></div>
      <div class="fld cs-words"><label class="l" for="words">ワード <span class="muted">(任意)</span></label><input type="search" id="words" placeholder="例: マイクラ 歌枠" maxlength="200" autocomplete="off"><span class="hint">空白かカンマで区切ります。空なら人気順だけ</span></div>
    </div>
    <div class="fld"><span class="l">対象の事務所 <span class="muted">(チャンネルの登録は「設定」の「事務所の登録」)</span></span><div class="chips" id="agChecks" role="group" aria-label="対象の事務所"></div></div>
    <details class="ui-disclosure cs-adv" id="rkAdv"><summary>詳しい条件 <span class="muted cs-advsum" id="rkAdvSum"></span></summary>
      <div class="cs-opts">
        <label class="cs-opt"><span class="l">ワードの一致</span><select id="mode"><option value="any">どれか1つを含む</option><option value="all">すべて含む</option></select></label>
        <label class="cs-opt"><span class="l">ワードを探す場所</span><select id="inDesc"><option value="1">タイトル+概要欄</option><option value="0">タイトルだけ</option></select></label>
        <label class="cs-opt"><span class="l">1事務所から取る数</span><select id="top"><option value="10">10本</option><option value="20" selected>20本</option><option value="50">50本</option><option value="100">100本</option></select></label>
        <label class="cs-opt"><span class="l">最低再生数</span><input type="number" id="minViews" min="0" step="1000" value="0"></label>
      </div>
      <div class="row cs-checks">
        <label class="lag"><input type="checkbox" class="ui-switch" id="archiveOnly" checked>配信アーカイブだけ(通常の投稿動画を除く)</label>
        <label class="lag"><input type="checkbox" class="ui-switch" id="noShorts" checked>ショート動画を除く</label></div>
    </details>
    <div class="row cs-go"><button type="button" class="btn primary lg" id="btnGo">検索する</button><button type="button" class="btn" id="btnCancel" hidden>中止</button><span class="hint" id="phase" role="status"></span></div>
    <div class="bar" id="barWrap" hidden><i id="bar"></i></div>
  </section>
  <div class="card rk-sticky" id="pickBar" hidden><div class="row"><span class="rk-pickn"><b id="pickN" class="num">0</b> 本選択中 <span class="hint">(最大${MAX_PICK}本まで)</span></span>
    <span class="row rk-pickact"><button type="button" class="btn small ghost" id="pickClear">選択を外す</button><button type="button" class="btn primary" id="pickGo" disabled>選んだ配信 0 本を解析に追加</button></span></div></div>
  <div id="results"><div class="empty"><b>まだ検索していません</b>条件を決めて「検索する」を押すと、人気の配信がここに並びます</div></div>`;
}
const okCount = a => a.channels.filter(c => c.status === 'ok').length;
/* 事務所にチェックが入るか: ユーザーが変えたならその値、触っていないなら「解決済みのチャンネルがあるか」 */
const agChecked = a => (Object.prototype.hasOwnProperty.call(R.agPick, a.id) ? !!R.agPick[a.id] : okCount(a) > 0);
function loadAgPick(){
  const v = lsGet('agsel');
  if (v && typeof v === 'object' && !Array.isArray(v)){ for (const [k, x] of Object.entries(v)) if (typeof x === 'boolean') R.agPick[k] = x; return; }
  const old = lsGet('ags');   // v0.7.0 まで: 選んだ事務所の ID の配列(外したのか、まだ登録していなかったのかは区別できないので「選んだ」だけ引き継ぐ)
  if (Array.isArray(old)) for (const k of old) if (typeof k === 'string' && k) R.agPick[k] = true;
}
function renderAgChecks(){
  const box = $('#agChecks'); if (!box) return;
  const sn = $('#rkSetupNotice'); if (sn) sn.hidden = R.reg.agencies.some(a => okCount(a) > 0);
  box.innerHTML = R.reg.agencies.map(a => { const n = okCount(a);
    return `<label class="cs-chip${n ? '' : ' cs-chip-empty'}" title="${n ? `登録して解決済みのチャンネル ${n} 件` : 'まだチャンネルがありません(設定の「事務所の登録」で追加します)'}"><input type="checkbox" class="agc" value="${esc(a.id)}"${agChecked(a) ? ' checked' : ''}>${esc(a.name)}<span class="cs-chip-n num">${n}</span></label>`; }).join('') || '<span class="hint">事務所がありません(設定の「事務所の登録」で追加します)</span>';
}
function setRange(a, b){ $('#dStart').value = ymd(a); $('#dEnd').value = ymd(b); }
function condBody(){
  return { start: $('#dStart').value, end: $('#dEnd').value, words: $('#words').value, mode: $('#mode').value, inDesc: $('#inDesc').value === '1', top: Number($('#top').value),
    minViews: Number($('#minViews').value) || 0, archiveOnly: $('#archiveOnly').checked, noShorts: $('#noShorts').checked, agencies: [...document.querySelectorAll('.agc:checked')].map(x => x.value) };
}
function saveCond(){ const c = condBody(); lsSet('cond', { words: c.words, mode: c.mode, inDesc: c.inDesc, top: c.top, minViews: c.minViews, archiveOnly: c.archiveOnly, noShorts: c.noShorts, start: c.start, end: c.end }); advSummary(); }
/* 「詳しい条件」を閉じていても、いまの条件が分かるように見出しの横に短く出す */
function advSummary(){
  const el = $('#rkAdvSum'); if (!el) return;
  const c = condBody(), parts = [];
  if (c.words.trim()) parts.push(c.mode === 'all' ? 'ワードをすべて含む' : 'ワードのどれかを含む', c.inDesc ? 'タイトル+概要欄' : 'タイトルだけ');
  parts.push('1事務所 ' + c.top + '本まで');
  if (c.minViews > 0) parts.push(fmtN(c.minViews) + '回以上');
  parts.push(c.archiveOnly ? 'アーカイブだけ' : '投稿動画も含む');
  if (c.noShorts) parts.push('ショートを除く');
  el.textContent = parts.join(' ・ ');
}
function setBusy(b){ $('#btnGo').disabled = b || noKey(); $('#btnCancel').hidden = !b; $('#barWrap').hidden = !b; if (!b){ $('#phase').textContent = ''; $('#bar').style.width = '0'; } }
const noKey = () => !(S.state && S.state.hasKey);
function keyNotice(){ $('#rkKeyNotice').hidden = !noKey(); $('#btnGo').disabled = noKey() || !$('#btnCancel').hidden; }

async function startSearch(){
  if ($('#btnGo').disabled) return;
  saveCond(); const body = condBody();
  if (!body.start || !body.end) return S.toast('期間(開始日・終了日)を入れてください');
  if (body.start > body.end) return S.toast('開始日は終了日より前にしてください');
  if (!body.agencies.length) return S.toast('対象の事務所を1つ以上選んでください(チャンネルを登録した事務所は、最初から選ばれています)');
  setBusy(true); $('#results').innerHTML = skeleton(); R.result = null; R.picked.clear(); R.q = ''; paintPick();
  try { R.job = await S.api('/api/rank/search', { body }); } catch (e){ setBusy(false); $('#results').innerHTML = ''; return S.toast(e.message, 0, 'err'); }
  clearInterval(R.poll); R.poll = setInterval(pollJob, 700); pollJob();
}
const skeleton = () => `<div class="card" aria-busy="true"><div class="ui-skel" style="height:16px;width:28%"></div>${'<div class="rk-skrow"><div class="ui-skel" style="width:96px;height:54px"></div><div style="flex:1"><div class="ui-skel" style="height:13px;width:70%"></div><div class="ui-skel" style="height:11px;width:30%;margin-top:8px"></div></div></div>'.repeat(4)}</div>`;
/* 700ms ごとに状態を聞く。前の問い合わせが終わる前に次を送らない(遅いときに応答が前後して表示が戻るのを防ぐ) */
async function pollJob(){
  if (R.polling || !R.job) return;
  R.polling = true;
  let j;
  try { j = await S.api('/api/rank/search?id=' + encodeURIComponent(R.job.id)); }
  catch (e){ clearInterval(R.poll); setBusy(false); $('#results').innerHTML = ''; S.toast(e.message, 0, 'err'); return; }
  finally { R.polling = false; }
  $('#phase').textContent = j.phase || ''; $('#bar').style.width = Math.round((j.progress || 0) * 100) + '%';
  if (j.state === 'running') return;
  clearInterval(R.poll); setBusy(false); S.refreshState().catch(() => {});
  if (j.state === 'error'){ $('#results').innerHTML = `<div class="empty"><b>検索できませんでした</b>${esc(j.error)}</div>`; return S.toast(j.error, 0, 'err'); }
  if (j.state === 'cancelled'){ $('#results').innerHTML = '<div class="empty"><b>検索を中止しました</b>条件を変えて、もう一度「検索する」を押してください</div>'; return S.toast('中止しました'); }
  R.result = j.result; await loadMarks(); renderResults();
}

/* ================= 結果 =================
   既定は「全部まとめて」(全事務所の結果を再生数の多い順に並べて上位 N 本。事務所をまたいで比べられる)。「事務所ごと」は以前の別々の表。
   道具の行(絞り込み・見せ方・本数)は作り直さず、下の一覧だけを描き直す(絞り込みの入力中にフォーカスが外れないように) */
function renderResults(){
  const r = R.result; if (!r) return;
  let html = '';
  if (r.unresolved) html += `<div class="notice">未解決のチャンネルが${Number(r.unresolved) || 0}件あり、対象から外しています(設定の「事務所の登録」で確認できます)。</div>`;
  if (r.warnings && r.warnings.length) html += `<div class="notice">${r.warnings.map(esc).join('<br>')}</div>`;
  html += `<div class="ui-listbar rk-bar">
      <input type="search" id="rkQ" placeholder="結果の中を題名・配信者で絞り込む" aria-label="検索結果を絞り込む" autocomplete="off">
      <div class="ui-seg" role="group" aria-label="結果の見せ方"><button type="button" data-view="all" aria-pressed="${R.view === 'all'}">全部まとめて</button><button type="button" data-view="ag" aria-pressed="${R.view === 'ag'}">事務所ごと</button></div>
      <label class="rk-limit"${R.view === 'all' ? '' : ' hidden'}><span class="sr-only">表示する本数</span><select id="rkLimit">${LIMITS.map(n => `<option value="${n}"${n === R.limit ? ' selected' : ''}>${n ? '上位 ' + n + ' 本' : 'すべて'}</option>`).join('')}</select></label>
      <span class="ui-count" id="rkCount"></span></div>
    <p class="hint rk-sum">調べた配信: <span class="num">${fmtN(r.videos)}</span>本 ・ 使用ユニット: <span class="num">${fmtN(r.quota)}</span>(1日の目安 10,000) ・ 再生数は検索した時点の値です</p>
    <div id="rkBody"></div>`;
  $('#results').innerHTML = html;
  const q = $('#rkQ'); q.value = R.q;
  renderBody(); paintPick();
}
const matchQ = (v, agName) => { const q = R.q.trim().toLowerCase(); if (!q) return true; return q.split(/\s+/).every(w => (v.title + ' ' + v.channel + ' ' + (agName || '')).toLowerCase().includes(w)); };
const TABLE_HEAD = '<thead><tr><th class="ck"><span class="sr-only">選択</span></th><th class="rk">#</th><th class="hide-s"><span class="sr-only">サムネイル</span></th><th>タイトル</th><th class="n">再生数</th><th class="n hide-s">高評価</th><th class="hide-s">配信日時</th><th class="n hide-s">長さ</th></tr></thead>';
function renderBody(){
  const r = R.result, box = $('#rkBody'); if (!r || !box) return;
  let html = '', shown = 0, total = 0;
  if (R.view === 'all'){
    const seen = new Set(), all = [];
    for (const a of r.agencies) for (const v of a.items){ if (seen.has(v.id)) continue; seen.add(v.id); all.push({ v, ag: a.name }); }
    all.sort((x, y) => (Number(y.v.views) || 0) - (Number(x.v.views) || 0));
    const hit = all.filter(x => matchQ(x.v, x.ag)); total = hit.length;
    const list = R.limit ? hit.slice(0, R.limit) : hit; shown = list.length;
    if (!all.length) html = `<div class="empty"><b>条件に合う配信はありませんでした</b>期間を広げるか、ワードを変えて、もう一度「検索する」を押してください</div>`;
    else if (!hit.length) html = `<div class="empty"><b>「${esc(R.q)}」に合う配信はありません</b>絞り込みの文字を消すと、すべての結果が出ます</div>`;
    else html = `<div class="card rk-all"><div class="tbl-wrap"><table class="rk-table">${TABLE_HEAD}<tbody>${list.map((x, i) => row(x.v, i, x.ag)).join('')}</tbody></table></div>` +
      (shown < total ? `<div class="rk-more"><button type="button" class="btn small" id="rkMore">もっと見る(残り ${total - shown} 本)</button></div>` : '') + '</div>';
  } else {
    html = r.agencies.map(a => {
      const items = a.items.filter(v => matchQ(v, a.name)); total += items.length; shown += items.length;
      return `<details class="ui-group rk-ag" open><summary><span class="ag-name">${esc(a.name)}</span><span class="ui-group-n">該当 <span class="num">${fmtN(a.matched)}</span>本 ・ 期間内の配信 <span class="num">${fmtN(a.scanned)}</span>本 ・ <span class="num">${fmtN(a.channels)}</span>チャンネル</span></summary>
      ${a.channels === 0 ? '<p class="hint rk-none">解決済みのチャンネルがありません。設定の「事務所の登録」で追加してください。</p>' : !a.items.length ? '<p class="hint rk-none">条件に合う配信アーカイブがありませんでした。</p>' : !items.length ? `<p class="hint rk-none">「${esc(R.q)}」に合う配信はありません。</p>` :
      `<div class="tbl-wrap"><table class="rk-table">${TABLE_HEAD}<tbody>${items.map((v, i) => row(v, i)).join('')}</tbody></table></div>`}
      </details>`; }).join('');
  }
  box.innerHTML = html;
  const c = $('#rkCount'); if (c) c.textContent = total ? (shown < total ? `${shown} / ${total} 本` : `${total} 本`) : '0 本';
  paintRows();
}
function row(v, i, agName){
  const id = okId(v.id), link = id ? 'https://www.youtube.com/watch?v=' + encodeURIComponent(v.id) : '', ms = atMs(v.at);
  const meta = [esc(v.channel), agName ? `<span class="rk-ag-name">${esc(agName)}</span>` : '', ms ? `<span title="${esc(v.at)}">${esc(S.ago(ms))}</span>` : ''].filter(Boolean).join('<span class="q-dot">・</span>');
  return `<tr data-vid="${esc(v.id)}"><td class="ck">${id ? `<input type="checkbox" class="pk" aria-label="解析に追加する: ${esc(v.title)}" data-id="${esc(v.id)}" data-title="${esc(v.title)}" data-channel="${esc(v.channel)}">` : ''}</td><td class="rk num">${i + 1}</td>
    <td class="hide-s th-cell">${okThumb(v.thumb) && id ? `<a href="${link}" target="_blank" rel="noopener noreferrer" tabindex="-1"><img loading="lazy" src="${esc(v.thumb)}" alt=""></a>` : '<span class="rk-noimg"></span>'}</td>
    <td class="tt">${id ? `<a href="${link}" target="_blank" rel="noopener noreferrer">${esc(v.title)}</a>` : esc(v.title)}<div class="hint rk-meta">${meta}</div>
      <div class="row tt-act">${id ? `<button type="button" class="btn small add1" data-id="${esc(v.id)}" data-title="${esc(v.title)}" data-channel="${esc(v.channel)}">解析に追加</button>` : ''}<span class="chip"></span></div></td>
    <td class="n num">${fmtN(v.views)}</td><td class="n num hide-s">${fmtN(v.likes)}</td><td class="num hide-s rk-at">${esc(v.at)}</td><td class="n num hide-s">${fmtDur(v.dur)}</td></tr>`;
}
/* 「解析済み」「キューにあります」の印と、チェックの有効/無効 */
function paintRows(){
  const full = R.picked.size >= MAX_PICK;
  document.querySelectorAll('#results tr[data-vid]').forEach(tr => {
    const id = tr.dataset.vid, q = R.inQueue.has(id), d = R.analyzed.has(id);
    const chip = tr.querySelector('.chip');   // 以前は ID が不正な行に .chip が無く、ここで例外になって以降の行が塗られなかった
    if (chip) chip.innerHTML = q ? '<span class="pill run">キューにあります</span>' : d ? '<span class="pill ok">解析済み</span>' : '';
    const cb = tr.querySelector('.pk'); if (cb){ cb.checked = R.picked.has(id); cb.disabled = q || (full && !cb.checked); }
    tr.classList.toggle('picked', R.picked.has(id));
    const b = tr.querySelector('.add1'); if (b) b.disabled = q;
  });
}
function paintPick(){
  const n = R.picked.size, bar = $('#pickBar'); if (!bar) return;
  bar.hidden = !R.result;
  $('#pickN').textContent = n; const g = $('#pickGo'); g.textContent = `選んだ配信 ${n} 本を解析に追加`; g.disabled = !n || R.adding;
  $('#pickClear').disabled = !n;
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
  if (!S.enqueue) return S.toast('解析画面がまだ読み込まれていません。ページを開き直してください', 0, 'err');
  if (R.adding) return;   // 二重送信の防止(同じ配信が2回キューに入らないように)
  R.adding = true; paintPick();
  try {
    const r = await S.enqueue(items);
    if (r && r.added && r.added.length){ for (const it of items) R.picked.delete(it.videoId); }
  } catch (e){ S.toast(e.message, 0, 'err'); }
  R.adding = false;
  await refreshMarks(); paintPick();
}

/* ================= 起動 ================= */
S.rank = { mountRegistry, refresh: refreshMarks };
S.onReady(async () => {
  const pane = $('#paneRank'); pane.innerHTML = paneHtml();
  loadAgPick();
  { const v = lsGet('view'), l = lsGet('limit'); if (v === 'ag' || v === 'all') R.view = v; if (LIMITS.includes(l)) R.limit = l; }
  const c = lsGet('cond');
  if (c){ $('#words').value = c.words || ''; $('#mode').value = c.mode === 'all' ? 'all' : 'any'; $('#inDesc').value = c.inDesc === false ? '0' : '1'; if ([10, 20, 50, 100].includes(c.top)) $('#top').value = String(c.top); $('#minViews').value = c.minViews || 0; $('#archiveOnly').checked = c.archiveOnly !== false; $('#noShorts').checked = c.noShorts !== false; }
  if (c && /^\d{4}-\d\d-\d\d$/.test(c.start || '') && /^\d{4}-\d\d-\d\d$/.test(c.end || '')) setRange(new Date(c.start + 'T00:00:00'), new Date(c.end + 'T00:00:00'));
  else { const e = new Date(), s = new Date(); s.setDate(s.getDate() - 29); setRange(s, e); }
  document.querySelectorAll('[data-days]').forEach(b => b.addEventListener('click', () => { const e = new Date(), s = new Date(); s.setDate(s.getDate() - (Number(b.dataset.days) - 1)); setRange(s, e); saveCond(); }));
  document.querySelectorAll('[data-m]').forEach(b => b.addEventListener('click', () => { const n = new Date(), k = Number(b.dataset.m); setRange(new Date(n.getFullYear(), n.getMonth() - k, 1), k ? new Date(n.getFullYear(), n.getMonth(), 0) : n); saveCond(); }));
  ['words', 'mode', 'inDesc', 'top', 'minViews', 'archiveOnly', 'noShorts', 'dStart', 'dEnd'].forEach(id => $('#' + id).addEventListener('change', saveCond));
  advSummary();
  $('#words').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); startSearch(); } });
  /* 事務所のチェックは、ユーザーが変えたものだけ覚える(触っていない事務所は、チャンネルを登録すれば自動で選ばれる) */
  $('#agChecks').addEventListener('change', e => { const cb = e.target.closest('.agc'); if (!cb) return; R.agPick[cb.value] = cb.checked; lsSet('agsel', R.agPick); });
  $('#btnGo').addEventListener('click', startSearch);
  $('#btnCancel').addEventListener('click', () => { if (R.job) S.api('/api/rank/search/cancel', { body: { id: R.job.id } }).catch(() => {}); });
  $('#rkOpenSet').addEventListener('click', () => S.openSettings('setKey'));
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
    const v = e.target.closest('[data-view]');
    if (v){ R.view = v.dataset.view === 'ag' ? 'ag' : 'all'; lsSet('view', R.view);
      document.querySelectorAll('#results [data-view]').forEach(x => x.setAttribute('aria-pressed', String(x === v)));
      const lb = document.querySelector('#results .rk-limit'); if (lb) lb.hidden = R.view !== 'all';
      renderBody(); return; }
    if (e.target.closest('#rkMore')){ const i = LIMITS.indexOf(R.limit); R.limit = LIMITS[Math.min(LIMITS.length - 1, i + 1)]; const sl = $('#rkLimit'); if (sl) sl.value = String(R.limit); lsSet('limit', R.limit); renderBody(); return; }
    const b = e.target.closest('.add1'); if (!b || b.disabled) return;
    enqueue([{ kind: 'youtube', videoId: b.dataset.id, title: b.dataset.title, channel: b.dataset.channel }]);
  });
  $('#results').addEventListener('input', e => { if (e.target.id === 'rkQ'){ R.q = e.target.value; renderBody(); } });
  $('#results').addEventListener('change', e => { if (e.target.id === 'rkLimit'){ R.limit = Number(e.target.value) || 0; lsSet('limit', R.limit); renderBody(); } });
  keyNotice(); S.on('state', keyNotice);
  S.on('step', st => { if (st === 'rank') refreshMarks(); });
  try { R.reg = await S.api('/api/rank/registry'); } catch (er){ S.showErr(er.message); }
  renderReg(); renderAgChecks();
  await loadMarks(); paintRows();
});
})();
