/* app-tools.js — 「編集」の画面: 動画を選び直す・まとめて付け替える・検索と置換・書き出し・左パネル・受け渡し・cut2resolve の API・確認のダイアログ・カットとパックのタブとのつなぎ(段10 で app.js から分けた。docs/plan/phase10-code-split.md)。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は index.html の1か所) */
'use strict';

/* ---------- 動画を選び直す(段2 B-4。docs/plan/phase2-data-safety.md の 1)。付け替えの API は POST だけ(URL の引数では付け替えない) ---------- */

function rlSync(){ const c = RL.check; $('#rlGo').disabled = !c || c.sameAsNow || (c.mismatch && !$('#rlAccept').checked); }

function rlReset(){
  RL.seq++; RL.check = null; RL.path = '';
  const res = $('#rlResult'); res.hidden = true; res.textContent = ''; res.className = 'tt-rl-res';
  $('#rlAcceptRow').hidden = true; $('#rlAccept').checked = false; rlSync();
}

function openRelink(){
  const dlg = $('#relinkDlg');
  if (!S.doc || dlg.open) return;
  RL.id = S.docId; $('#rlOld').value = S.doc.sourcePath || ''; $('#rlPath').value = ''; rlReset();
  dlg.showModal(); $('#rlPath').focus();
}

function renderRlResult(c){
  const res = $('#rlResult'), dl = document.createElement('dl');
  const add = (k, v) => { const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = k; dd.textContent = v; dl.append(dt, dd); };
  const diff = Number(c.diffSec);
  add('ファイル', c.name);
  add('長さ', `元 ${c.docDuration != null ? fmtT(c.docDuration) : '不明'} / 選んだ動画 ${fmtT(c.durationSec)}` + (c.diffSec != null && Math.abs(diff) >= 0.05 ? `(差 ${diff > 0 ? '+' : ''}${diff.toFixed(2)} 秒)` : ''));
  add('fps', c.fps ? String(Math.round(c.fps[0] / c.fps[1] * 1000) / 1000) : '―(映像なし)');
  if ((c.usedBy || []).length) add('同じ動画を使う文書', c.usedBy.map(u => u.title || u.id).join('、'));
  res.textContent = ''; res.append(dl);
  const notes = [...(c.sameAsNow ? ['今と同じ動画です(付け替える必要はありません)'] : []), ...(c.warnings || [])];
  if (!notes.length) notes.push('長さは元の動画と同じです。付け替えられます');
  const ul = document.createElement('ul');
  for (const w of notes){ const li = document.createElement('li'); li.textContent = w; ul.append(li); }
  res.append(ul);
  res.className = 'tt-rl-res notice ' + (c.mismatch || c.sameAsNow ? 'err' : (c.warnings || []).length ? '' : 'ok');
  res.hidden = false;
  $('#rlAcceptRow').hidden = !c.mismatch;
}

async function rlCheck(){
  const path = $('#rlPath').value.trim();
  if (!path){ toast('新しいパスを入れてください', 3000, 'err'); $('#rlPath').focus(); return; }
  rlReset();
  const seq = RL.seq, res = $('#rlResult'), b = $('#rlCheck');
  res.hidden = false; res.textContent = '調べています…(Dropbox などの「オンラインのみ」のファイルは、ダウンロードが終わるまで時間がかかることがあります)';
  b.disabled = true;
  try {
    const c = await api('/api/relink/check', { body: { id: RL.id, path } });
    if (seq !== RL.seq) return;
    RL.check = c; RL.path = path; renderRlResult(c);
  } catch (e){ if (seq === RL.seq){ res.className = 'tt-rl-res notice err'; res.textContent = '選べません: ' + e.message; } }
  finally { b.disabled = false; rlSync(); }
}

/* 「参照…」(2026-10-01): PC の標準の窓で選ぶ。窓はサーバーが開く(ブラウザからは実際のパスを知れないため。ytt_core/pick.py)。やめたら null */
async function pickPath(kind, hint){
  try { const r = await api('/api/pick', { body: { kind, hint: hint || '' } }); return r.path || null; }
  catch (e){ toast(e.message, 6000, 'err'); return null; }
}

/* ---------- 見つからない動画をまとめて付け替える(2026-10-01)。候補は「選んだフォルダの中の同じファイル名」か行ごとの「参照…」。
   付け替えは1件ずつ /api/relink(控え・長さ・競合の確認は1件のときと同じ)。長さが違うものは最初は選ばない ---------- */

function renderMissing(){
  const n = S.list.filter(i => i.mediaOk === false && i.sourceName).length;
  $('#txMissingText').textContent = `元の動画が見つからない文書が ${n} 件あります(移した・名前を変えた動画は、付け替えると再生・カット・パックに使えます)`;
  $('#txMissing').hidden = !n;
}

function raSync(){
  const n = RA.rows.filter(r => r.pick && r.check && !r.done).length;
  $('#raGo').disabled = RA.busy || !n;
  $('#raGo').textContent = n ? `付け替える(${n} 件)` : '付け替える';
  for (const id of ['#raCancel', '#raBrowse', '#raFind']) $(id).disabled = RA.busy;
}

function raUpdate(r){
  const st = r.elSt, c = r.check;
  if (!st) return;
  let text = '', cls = '';
  if (r.done){ text = '付け替えました'; cls = 'ok'; }
  else if (r.state === 'checking') text = '確かめています…(「オンラインのみ」のファイルは時間がかかることがあります)';
  else if (r.state === 'saving') text = '付け替えています…';
  else if (r.err){ text = '選べません: ' + r.err; cls = 'err'; }
  else if (c && c.sameAsNow){ text = '今と同じ動画です'; cls = 'err'; }
  else if (c && c.mismatch){
    text = `長さが元の動画と違います(元 ${c.docDuration != null ? fmtT(c.docDuration) : '不明'} / 選んだ動画 ${fmtT(c.durationSec)})。別の動画でないか確かめてください。選ぶと、違うのを分かったうえで付け替えます`;
    cls = 'warn';
  } else if (c){
    text = ['長さは元の動画と同じです', ...(c.warnings || [])].join('。'); cls = (c.warnings || []).length ? 'warn' : 'ok';
  } else text = '動画を選んでください';
  if (r.note && !r.done) text += '。' + r.note;
  st.textContent = text; st.className = 'tt-ra-st' + (cls ? ' ' + cls : '');
  r.elPick.checked = !!(r.pick && !r.done);
  r.elPick.disabled = RA.busy || r.done || !c || c.sameAsNow || !!r.err || !!r.state;
  r.elPath.disabled = r.elBrowse.disabled = RA.busy || r.done;
  raSync();
}

function raCheck(r){
  r.check = null; r.err = ''; r.pick = false; r.state = r.path ? 'checking' : ''; raUpdate(r);
  if (!r.path) return;
  const tok = r.tok = (r.tok || 0) + 1, seq = RA.seq;
  RA.q = RA.q.then(async () => {   // 動画を調べる(ffprobe)のは1件ずつ
    if (tok !== r.tok || seq !== RA.seq) return;
    try {
      const c = await api('/api/relink/check', { body: { id: r.id, path: r.path } });
      if (tok !== r.tok || seq !== RA.seq) return;
      r.check = c; r.pick = !c.mismatch && !c.sameAsNow;
    } catch (e){ if (tok !== r.tok) return; r.err = e.message; }
    r.state = ''; raUpdate(r);
  });
}

function raSetPath(r, p, fromFind){ r.path = p; r.fromFind = fromFind; r.elPath.value = p; raCheck(r); }

function renderRa(){
  const box = $('#raList'); box.textContent = '';
  for (const r of RA.rows){
    const name = r.title || r.sourceName || '無題';
    const row = document.createElement('div'); row.className = 'tt-ra-row'; row.dataset.id = r.id;
    const pick = document.createElement('input'); pick.type = 'checkbox'; pick.setAttribute('aria-label', `${name} を付け替える`);
    pick.addEventListener('change', () => { r.pick = pick.checked; raSync(); });
    const main = document.createElement('div'); main.className = 'tt-ra-main';
    const t = document.createElement('div'); t.className = 'tt-ra-title'; t.textContent = name;
    const old = document.createElement('div'); old.className = 'tt-ra-old mono'; old.textContent = '元: ' + r.sourcePath;
    const line = document.createElement('div'); line.className = 'tt-ra-path';
    const inp = document.createElement('input'); inp.type = 'text'; inp.className = 'mono'; inp.spellcheck = false; inp.autocomplete = 'off';
    inp.placeholder = '新しいパス'; inp.setAttribute('aria-label', `${name} の新しいパス`);
    inp.addEventListener('input', () => { r.check = null; r.err = ''; r.pick = false; r.note = ''; r.tok = (r.tok || 0) + 1; r.state = ''; raUpdate(r); });   // 確かめ直すまで選べない
    inp.addEventListener('change', () => { const v = inp.value.trim(); if (v !== r.path || !r.check){ r.path = v; r.fromFind = false; raCheck(r); } });
    const br = document.createElement('button'); br.type = 'button'; br.className = 'btn small'; br.textContent = '参照…';
    br.addEventListener('click', async () => {
      br.disabled = true;
      try { const p = await pickPath('file', r.path || r.sourcePath); if (p && $('#relinkAllDlg').open){ r.note = ''; raSetPath(r, p, false); } }
      finally { raUpdate(r); }
    });
    const st = document.createElement('div'); st.className = 'tt-ra-st'; st.setAttribute('role', 'status');
    line.append(inp, br); main.append(t, old, line, st); row.append(pick, main); box.append(row);
    Object.assign(r, { elPick: pick, elPath: inp, elBrowse: br, elSt: st });
    raUpdate(r);
  }
}

function openRelinkAll(){
  const dlg = $('#relinkAllDlg');
  if (dlg.open) return;
  RA.seq++; RA.rows = []; RA.busy = false; $('#raList').textContent = ''; $('#raFolder').value = '';
  $('#raNote').textContent = '元の動画が見つからない文書を調べています…'; raSync();
  dlg.showModal(); $('#raFolder').focus();
  const seq = RA.seq;
  api('/api/relink/missing', { body: {} }).then(res => {
    if (seq !== RA.seq) return;
    RA.rows = res.items.map(i => ({ ...i, path: '', check: null, err: '', note: '', pick: false, state: '', done: false, fromFind: false }));
    $('#raNote').textContent = (RA.rows.length ? `元の動画が見つからない文書: ${RA.rows.length} 件。動画を移したフォルダを選んでください` : '元の動画が見つからない文書はありません')
      + (res.skipped ? `(ネットワーク上の動画を使う ${res.skipped} 件は調べていません)` : '');
    renderRa();
  }).catch(e => { if (seq === RA.seq) $('#raNote').textContent = '調べられませんでした: ' + e.message; });
}

async function raFind(){
  const folder = $('#raFolder').value.trim();
  if (!folder){ toast('フォルダを選ぶか、フォルダのパスを入れてください', 3000, 'err'); $('#raFolder').focus(); return; }
  const rows = RA.rows.filter(r => !r.done && (!r.path || r.fromFind));   // 自分で選んだ動画は上書きしない
  if (!rows.length || RA.busy) return;
  const seq = RA.seq;
  RA.busy = true; RA.rows.forEach(raUpdate);
  $('#raNote').textContent = 'フォルダの中を探しています…';
  try {
    const res = await api('/api/relink/find', { body: { folder, ids: rows.map(r => r.id) } });
    if (seq !== RA.seq) return;
    RA.busy = false;
    let hit = 0;
    for (const r of rows){
      const c = res.candidates[r.id] || [];
      if (c.length){
        hit++; r.note = c.length > 1 ? `同じ名前の動画が ${c.length} 件あります(1件目を入れました。違えば「参照…」で選んでください)` : '';
        raSetPath(r, c[0], true);
      } else {
        r.note = 'このフォルダには同じ名前の動画がありません(「参照…」で選べます)';
        if (r.fromFind){ r.path = ''; r.elPath.value = ''; r.check = null; r.pick = false; r.fromFind = false; }
        raUpdate(r);
      }
    }
    $('#raNote').textContent = `${hit} / ${rows.length} 件の動画が見つかりました` + (res.truncated ? '(フォルダが大きいので途中までしか探していません。動画のあるフォルダを選ぶと確実です)' : '');
  } catch (e){ if (seq === RA.seq) $('#raNote').textContent = '探せませんでした: ' + e.message; }
  finally { RA.busy = false; RA.rows.forEach(raUpdate); raSync(); }
}

/* ブラウザのタブの題名: 「● タイトル - 編集」(● は未保存・保存できていない) */
function updateDocTitle(){
  const d = S.doc, st = $('#saveState').getAttribute('data-state');
  document.title = d ? `${S.dirty || S.saving || st === 'err' ? '● ' : ''}${String(d.title || '無題').slice(0, 60)} - 編集` : '編集';
}

/* 題名の行(どのタブにも): 配信者・長さ・元の配信の位置と、札「校正 n / m行」「残す n区間 ・ カット後 m:ss.ff」。描き直しはフレームごとに1回 */
function docLength(d){
  const a = Number(d.start) || 0, b = Number(d.end), dur = Number(d.duration);
  if (b > a) return b - a;
  if (dur > a) return dur - a;
  return Math.max(0, ...d.segments.map(g => Number(g.end) || 0)) - a;
}

function renderDocBar(){ if (!dbQ) dbQ = requestAnimationFrame(() => { dbQ = 0; renderDocBarNow(); }); }

function renderDocBarNow(){
  const d = S.doc; if (!d) return;
  const it = S.list.find(x => x.id === S.docId) || {}, parts = [];
  if (it.channel) parts.push(it.channel);
  const len = docLength(d); if (len > 0) parts.push(fmtT(len));
  const rg = d.clip && typeof d.clip === 'object' && d.clip.range && typeof d.clip.range === 'object' ? d.clip.range : null, a = rg ? Number(rg.start) : NaN;
  if (Number.isFinite(a)) parts.push('元の配信 ' + fmtT(a) + '〜');
  const meta = $('#docMeta'); meta.textContent = parts.join(' ・ '); meta.title = String(d.sourcePath || '');
  const txt = d.segments.filter(g => String(g.text || '').trim()), pf = txt.filter(g => g.proofed).length;
  const pp = $('#pillProof'); pp.hidden = !txt.length; pp.textContent = `校正 ${pf} / ${txt.length}行`; pp.className = 'pill ' + (txt.length && pf === txt.length ? 'ok' : 'wait');
  const pc = $('#pillCut'), cs = CUT && CUT.summary();
  if (cs){ pc.textContent = `残す ${cs.count}区間 ・ カット後 ${fmtCs(cs.keptSec)}`; pc.hidden = false; }
  else { const sp = cpApproxSpans(); pc.hidden = !sp.length; pc.textContent = `残す ${sp.length}区間 ・ カット後 約${fmtCs(sp.reduce((x, [p, q]) => x + q - p, 0))}`; }
}

/* 文書を閉じる(開いている文書を削除したとき) */
function closeDoc(){
  clearTimeout(markDirty.t);
  S.doc = null; S.docId = null; S.dirty = false; S.conflict = false; S.forceNext = false; S.undo = []; S.sel = new Set(); S.navIdx = -1; S.curIdx = -1; S.handoff = null;
  if (CUT) CUT.unload();
  if (PACK) PACK.load(null);
  $('#doc').hidden = true; $('#noDoc').hidden = false; $('#conflictBar').hidden = true; $('.app').classList.remove('has-doc');
  setUrlDoc(null);
  S.mediaSeq = (S.mediaSeq || 0) + 1; player().removeAttribute('src'); player().load();
  renderList(); updateDocTitle();
}

/* ---------- 検索・話者・置換 ---------- */

function syncEval(){
  const on = !!(S.doc && S.doc.evalSet), lock = !!(S.doc && S.doc.evalLocked), cb = $('#evalSet');
  cb.checked = on || lock; cb.disabled = lock; cb.parentElement.title = lock ? EVAL_LOCK_MSG : EVAL_TITLE;
  $('#evalBanner').hidden = !(on || lock); renderVoiceLearn();   // 評価用では「声を覚える」を押せない(監査02)
}

/* 評価用のフォルダ(⚙。サーバーの設定 evalDirs = api/settings/patch。整理 = 動画の名前をそろえて文書を付け替える) */
function evNote(info){
  const l = info && info.last, el = $('#evNote');
  if (!info) return void (el.textContent = '');
  const miss = (info.dirs || []).length - (info.active || []).length;
  el.textContent = (miss > 0 ? `見つからないフォルダが ${miss} 個あります(ドライブを確かめてください)。` : '')
    + (l ? `前回の整理(${l.trigger === 'startup' ? '起動時' : 'ボタン'} ${new Date(l.at).toLocaleString()}): 動画 ${l.videos} 本・名前を変えた ${l.renamed.length} 本・仮置きから移した ${(l.moved || []).length} 本・評価用にした ${l.marked} 件` + ((l.staged || []).length ? `・仮置きに残した ${l.staged.length} 本` : '') + (l.skipped.length ? `・飛ばした ${l.skipped.length} 本` : '') : (info.active || []).length ? 'まだ整理していません' : '');
}

async function loadEvalFolders(){
  try { const info = await api('/api/eval-folders'); S.evalDirsActive = !!(info.active || []).length; $('#evDirs').value = (info.dirs || []).join('\n'); evNote(info); } catch {}
}

/* 評価用の仮置き: ほかの文書へ移ったとき、前の文書が「全行に話者 + 全行が校正済み」なら、話した時間が最も長いメンバーのフォルダへ移す(サーバーが判定) */
async function evalSettle(id){
  try {
    const r = await api('/api/eval-folders/settle', { body: { id } });
    if (r.intake){   // 評価用にした文書の動画を、評価用のフォルダへ取り込み始めた(別のドライブへのコピーは裏で。終わったら一覧に出る)
      toast('評価用にした動画を、評価用のフォルダへ移しています(すべて校正済みならメンバーのフォルダ、それ以外は仮置き)', 6000);
      for (const ms of [5000, 30000, 120000]) setTimeout(() => loadList(), ms);
      return;
    }
    if (!r.moved) return;
    const to = r.moved.to.split(/[\\/]/);
    toast(`評価用の仮置きから「${to[to.length - 2]}」へ移しました: ${to[to.length - 1]}`, 6000);
    loadList();
  } catch {}   // 文書が消えた・入口が止まった: 次の整理で移す
}

/* 評価用の動画をまとめて文字起こし(⚙。サーバーの ed_evalbatch。始めるのはこのボタンだけ・止めるまで続く。待ちが 2 件までなので、ほかの操作が割り込める) */
let evbTimer = 0;
function evbRender(s){
  const note = $('#evbNote'), on = !!s.enabled;
  $('#evbStart').disabled = on; $('#evbStop').hidden = !on;
  let t = '';
  if (on){
    t = `動いています: 入れた ${s.enqueued} 本・残り ${s.remaining == null ? '調べています' : s.remaining + ' 本'}・今 ${s.active} 件(待ち・処理中)`
      + (s.failed ? `・飛ばした ${s.failed} 本` : '') + (s.deferred ? `。${s.deferred}` : '');
  } else if (s.finished){
    t = `終わりました: 済 ${s.done} 本` + (s.failed ? `・飛ばした ${s.failed} 本` : '') + (s.finishedAt ? `(${new Date(s.finishedAt).toLocaleString()})` : '');
  } else if (s.stoppedAt){
    t = `止めています(${new Date(s.stoppedAt).toLocaleString()})。もう一度押すと続きから入れます` + (s.active ? `。動いている ${s.active} 件は最後まで動きます` : '');
  }
  if (s.lastError) t += (t ? '。' : '') + `最後のエラー: ${s.lastError.src}: ${s.lastError.message}`;
  note.textContent = t;
  clearInterval(evbTimer); evbTimer = on || s.active ? setInterval(() => { if (!document.hidden) loadEvalBatch(); }, 15000) : 0;
}
async function loadEvalBatch(){
  try { evbRender(await api('/api/eval-batch')); }
  catch (e){ if (e.status === 404) $('#evbRow').hidden = true; }   // 古いサーバー(まだ部品が無い)では出さない
}
async function evbStart(){
  if (!await confirmDlg('仮置きをまとめて文字起こし', '評価用の動画を、手が空いたとき少しずつ文字起こしします。数が多いと CPU で数時間かかります(止めるまで続きます)。始めますか?', '始める')) return;
  try { evbRender(await api('/api/eval-batch/start', { body: {} })); toast('まとめての文字起こしを始めました(手が空いたとき少しずつ入れます)', 5000, 'ok'); }
  catch (e){ toast('始められませんでした: ' + e.message, 6000, 'err'); }
}
async function evbStop(){
  try { evbRender(await api('/api/eval-batch/stop', { body: {} })); toast('まとめての文字起こしを止めました', 4000); }
  catch (e){ toast('止められませんでした: ' + e.message, 6000, 'err'); }
}
function evbInit(){   // $ と api は app.js が先に読まれたあとで使える(この部品は app.js より先に読まれるので、読み込みが終わってから)
  $('#evbStart').addEventListener('click', evbStart);
  $('#evbStop').addEventListener('click', evbStop);
  loadEvalBatch();
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', evbInit); else evbInit();

function renderSpNames(){
  let dl = document.getElementById('spNames');
  if (!dl){ dl = document.createElement('datalist'); dl.id = 'spNames'; document.body.appendChild(dl); }
  const who = $('#pkWho') ? $('#pkWho').value.trim() : '';
  const roster = S.roster ? [...new Set(S.roster.groups.filter(g => g.id !== 'units').flatMap(g => g.names))] : [];
  const names = [...new Set([...spVoiceNames, ...(who ? [who] : []), ...roster])].slice(0, 300);
  const key = names.join('\n'); if (dl.dataset.key === key) return;
  dl.dataset.key = key; dl.innerHTML = names.map(n => `<option value="${esc(n)}">`).join('');
}

/* 話者判別が終わったら: 名前が付いていない話者の最初の名前の欄へ(E-10・E-12) */
function focusSpeakerNames(){
  const d = $('#spDetails'); if (!d || !S.doc) return;
  d.hidden = false; d.open = true;
  const i = S.doc.speakers.findIndex(s => !String(s.name || '').trim() || /^話者\d+$/.test(String(s.name)) || s.name === s.id);
  const inp = $('#spList').querySelectorAll('.sp-row input[type=text]')[Math.max(0, i)];
  if (inp){ inp.scrollIntoView({ block: 'center' }); inp.focus(); inp.select(); }
}

function playSpeaker(id){
  const list = S.doc.segments.filter(s => s.speaker === id && s.text.trim());
  if (!list.length) return toast('この話者の行がありません');
  const t = player().currentTime, next = list.find(s => s.start > t + 0.2) || list[0];
  playSeg(next, true);   // 「聞く」は、その行の終わりで止める(押すたびに、その人の次の発言へ)
}

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
  if (n){ S.undo.push({ seq: nextOp(), snap }); if (S.undo.length > 30) S.undo.shift(); updateUndo(); renderDoc(); markDirty(); }
  return n;
}

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

/* ---------- 左パネルのイベント ---------- */

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

/* ---------- 受け渡し(docs/spec/pipeline.md 2・3・6): 元の配信(.clip.json)・URL で渡された動画・動画の隣に保存 ---------- */

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

async function lookupClip(path){
  const box = $('#srcClip'), seq = ++clipSeq;
  path = String(path || '').trim().replace(/^"(.*)"$/, '$1');
  if (!path){ box.hidden = true; return null; }
  let r; try { r = await api('/api/clip-info?path=' + encodeURIComponent(path)); } catch { if (seq === clipSeq) box.hidden = true; return null; }   // 400(動画でないパス)などは、表示を消すだけ
  if (seq !== clipSeq) return null;   // 待っている間に別のパスが入った
  renderClipBox(box, r.clip, r.warning);
  return r;
}

/* URL の ?media=<動画のパス> / ?clip=<.clip.json のパス>(他のツールの画面からのリンク)。
   ファイル欄に入れるだけで、文字起こしは始めない(別のサイトのリンクからでも開けるので、重い処理を URL だけで動かさない。docs/spec/pipeline.md 3)。
   読んだら URL から消す(再読み込み・ブックマークで、同じ値が何度も入らないように) */
function showMediaChoice(){ $('#mediaChoice').hidden = false; }

function takeUrlParams(){
  let q; try { q = new URLSearchParams(location.search); } catch { return false; }
  const media = (q.get('media') || '').trim().slice(0, 1000), clip = (q.get('clip') || '').trim().slice(0, 1000);
  const docId = /^[0-9a-f]{12}$/.test(q.get('doc') || '') ? q.get('doc') : '';   // ホームからは文書 ID で開く(B-1。同じ動画の文書が複数あっても選んだ文書)
  const list = LIST_OPTS.kind.includes(q.get('list') || '') ? q.get('list') : '';   // ?list=other|clip|all|eval: 履歴を種類で絞って開く(ホームの「編集の履歴で見る」。段5 5-1・B-5)
  if (!q.has('media') && !q.has('clip') && !q.has('doc') && !list) return false;
  q.delete('media'); q.delete('clip'); q.delete('list');   // ?doc= は残す(開いた文書を URL に残す。監査 06。開けなければ下で消す)
  if (!docId) q.delete('doc');
  const rest = q.toString();
  try { history.replaceState(history.state, '', location.pathname + (rest ? '?' + rest : '') + location.hash); } catch {}
  if (list){   // 履歴の種類を変えて左のメニューの履歴を開く(doc・media と同時なら、下で文書を開く方も行う)
    L.kind = list; saveListPrefs(); const el = $('#txFilter'); if (el) el.value = list;
    for (const x of Object.keys(txLimit)) delete txLimit[x];
    setSideTab('files'); renderList();
  }
  if (!media && !clip && !docId) return false;
  if (docId){
    loadList().then(() => S.list.some(x => x.id === docId) ? openDoc(docId) : false).then(ok => {   // 一覧に無い(消された)文書は読みに行かない
      if (ok) return;
      if (S.docId !== docId) setUrlDoc(S.docId);   // 開けなかった文書を URL に残さない(再読み込みで同じ知らせを繰り返さない)
      if (media || clip){ toast('選んだ文書が見つからなかったので、動画から探します', 4000); openByMedia(); }
      else toast('選んだ文書が見つかりませんでした(消された可能性があります)', 5000, 'err');
    }).catch(() => { if (S.docId !== docId) setUrlDoc(S.docId); if (media || clip) openByMedia(); });
    return true;
  }
  return openByMedia();
  function openByMedia(){
  setTab('file'); $('#newBox').open = true;
  if (media) $('#srcPath').value = media;
  const ask = () => {   // まだ文書の無い動画: 「文字起こしする / 文字起こしせずに開く」を選ばせる(自動では始めない)
    setSideTab('start'); showMediaChoice();
    lookupClip(clip || media).then(r => {
      if (clip && !media && r && r.mediaPath && !$('#srcPath').value.trim()) $('#srcPath').value = r.mediaPath;   // ?clip= だけのときは、.clip.json が指す動画を入れる
    });
    window.scrollTo(0, 0);   // 「新しく文字起こしする」はメニューの先頭なので、一番上を見せる(ファイル欄と「元の配信」が見える)
    toast((media ? '動画のパスを入れました。' : '元の配信の情報(.clip.json)を読み込みます。') + '「文字起こしをする」か「文字起こしせずに開く」を選んでください(自動では始めません)', 7000, 'info');
  };
  if (!media) { ask(); return true; }
  api('/api/doc-for?path=' + encodeURIComponent(media)).then(async r => {   // その動画の文書があれば、それを開く(編集で開く)
    if (r && r.doc){ await loadList(); if (await openDoc(r.doc.id)) toast('この動画の文書を開きました', 3000, 'ok'); else ask(); }
    else ask();
  }).catch(ask);
  return true;
  }
}

function renderDocExtras(d){
  const box = $('#docClip');
  if (d && d.clip && typeof d.clip === 'object'){ box.className = 'tt-clip'; box.innerHTML = clipHTML(d.clip); box.hidden = false; }
  else { box.hidden = true; box.innerHTML = ''; }
  if (S.handoff && S.handoff.id !== S.docId) S.handoff = null;
  renderHandoff();
  /* ヘッダーの ui-appnav の「スタジオ」に、元の配信を引き継ぐ(スタジオの ?url= は解析の欄に入るだけ)。
     url が無い文書に切り替えたときは '?'(パラメータ無し)を渡して、前の文書の分を消す(渡さないと残ってしまう) */
  if (window.UIKit && UIKit.appnav){
    const src = d && d.clip && typeof d.clip === 'object' && d.clip.source && typeof d.clip.source === 'object' ? d.clip.source : null;
    const url = src && typeof src.url === 'string' && src.url.startsWith(YT_PREFIX) ? src.url : '';
    const vid = src && typeof src.videoId === 'string' && /^[\w-]{1,64}$/.test(src.videoId) ? src.videoId : '';
    /* B-6: ?video= を先に(スタジオに保存済みなら、その配信の確認画面で開く)。?url= は保存されていなかったときの予備(解析の欄に入る) */
    const q = [vid ? 'video=' + encodeURIComponent(vid) : '', url ? 'url=' + encodeURIComponent(url) : ''].filter(Boolean).join('&');
    UIKit.appnav.setLink('studio', '?' + q);
  }
}

function renderHandoff(){
  const box = $('#handoffOut'), pbox = $('#cpPlanOut'), h = S.handoff;
  if (!box) return;
  if (!S.doc || !h || h.id !== S.docId){ box.hidden = true; box.innerHTML = ''; if (pbox){ pbox.hidden = true; pbox.innerHTML = ''; } return; }
  const rows = [['transcript', '文字起こし'], ['srt', '字幕']].filter(([k]) => h[k]).map(([k, l]) => handoffRow(h, k, l)).join('');
  box.innerHTML = rows + '<div class="row"><span class="hint">Resolve へ渡すパックは <b>3 パック</b> のタブで作ります</span></div>';
  box.hidden = !rows;
  if (pbox){ pbox.innerHTML = h.plan ? handoffRow(h, 'plan', '残す区間') : ''; pbox.hidden = !h.plan; }
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
    else toast('作業用フォルダに保存できませんでした: ' + e.message, 7000, 'err');
  } finally { btn.disabled = false; btn.textContent = label; }
}

/* ---------- cut2resolve の API(3 パック のタブ・カットのたたき台が使う) ----------
   パックを作るのは cut2resolve/pack.py だけ(文字起こし側に Resolve 用の計算を書き足さない。docs/design/resolve-pack-unification.md)。
   cut2resolve の API は、入口に取り込まれているとき(同じアドレスの /cut2resolve/。合言葉も同じ)だけ使う。別のポートの cut2resolve には送らない
   (合言葉を別のサーバーへ渡さない・CORS で断られるため) */

/* 取り込まれた cut2resolve の場所('/cut2resolve/')。使えないときは ''。URL はここと c2rUrl() だけで作る */
function c2rBase(){
  if (!TOKEN || !window.UIKit || !UIKit.tools.paths || !UIKit.tools.paths.cut2resolve) return '';
  const here = Number(location.port || (location.protocol === 'https:' ? 443 : 80));
  if (!S.ports || Number(S.ports.cut2resolve) !== here) return '';   // 同じ入口(同じポート)の中の cut2resolve だけ
  return UIKit.tools.base('cut2resolve');
}

async function c2rApi(path, opt = {}){
  if (!c2rBase()){ const e = new Error('cut2resolve を使えません(入口から開いてください)'); e.code = 'unavailable'; throw e; }
  const init = { cache: 'no-store', method: opt.body !== undefined ? 'POST' : 'GET', headers: {} };
  if (opt.body !== undefined){ init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opt.body); init.headers['X-YTT-Token'] = TOKEN; }
  let r;
  try { r = await fetch(c2rUrl(path), init); } catch { const e = new Error('cut2resolve に接続できません(入口の黒い画面が閉じていないか確認してください)'); e.code = 'network'; throw e; }
  const j = await r.json().catch(() => null);
  if (!r.ok){ const e = new Error((j && j.message) || `cut2resolve のエラー(${r.status})`); e.code = (j && j.error) || 'http'; e.status = r.status; e.data = j || {}; throw e; }
  return j;
}

/* cut2resolve のジョブが終わるまで待つ(api/job?id= を見て、done なら結果、error なら中身を投げる) */
async function c2rWait(job, onTick){
  let j = job, fails = 0;
  while (j.state === 'running'){
    await new Promise(res => setTimeout(res, 300));
    try { j = await c2rApi('api/job?id=' + encodeURIComponent(job.id)); fails = 0; }
    catch (e){ if (e.code === 'network' && ++fails < 20) continue; throw e; }
    if (onTick) onTick(j);
  }
  if (j.state === 'done') return j.result;
  const er = j.error || {}, e = new Error(j.state === 'cancelled' ? '中止しました' : (er.message || '失敗しました'));
  e.code = j.state === 'cancelled' ? 'cancelled' : (er.code || 'failed'); e.data = er; throw e;
}

/* カットが使えないとき(動画が無いなど)の題名の行の目安: 残す行(文字があり、カット済でない)の時間を、重なりをまとめて足す */
function cpApproxSpans(){
  const spans = S.doc.segments.filter(g => g.cutState !== 'cut' && g.text.trim() && g.end > g.start).map(g => [g.start, g.end]).sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const [a, b] of spans){ const cur = out[out.length - 1]; if (cur && a <= cur[1]) cur[1] = Math.max(cur[1], b); else out.push([a, b]); }
  return out;
}

/* 保存 → 動画の隣に .transcript.json(保存済みの内容を書き出す。画面と違う内容を cut2resolve に渡さないため、保存が追いついていなければ待つ) */
async function cpExport(id){
  const ok = await saveDoc();
  const fail = (msg, code) => Object.assign(new Error(msg), { code });
  if (S.docId !== id) throw fail('別の文字起こしに切り替えました', 'switched');
  if (!ok || S.dirty || S.saving) throw S.conflict ? fail('保存が競合しています。1 文字起こし のタブの案内から選んでください', 'conflict') : fail('保存が追いついていません', 'saving');
  let r;
  try { r = await api('/api/export-file', { body: { id, format: 'transcript-v1', baseUpdatedAt: S.baseUpdatedAt } }); }
  catch (e){ if (e.status === 409) e.code = 'saving'; throw e; }
  return r.path;
}

function confirmOverwrite(files, dir){
  const dlg = $('#dlgOverwrite');
  $('#owDir').textContent = dir || ''; $('#owDir').hidden = !dir;
  $('#owFiles').innerHTML = (files || []).slice(0, 20).map(f => `<li>${esc(f)}</li>`).join('') + ((files || []).length > 20 ? `<li>ほか ${files.length - 20}件</li>` : '');
  return new Promise(resolve => {
    const done = v => { $('#owOk').onclick = null; $('#owCancel').onclick = null; dlg.oncancel = null; if (dlg.open) dlg.close(); resolve(v); };
    $('#owOk').onclick = () => done(true);
    $('#owCancel').onclick = () => done(false);
    dlg.oncancel = e => { e.preventDefault(); done(false); };
    dlg.showModal(); $('#owCancel').focus();
  });
}

function renderCutPack(){ if (!cpQ) cpQ = requestAnimationFrame(() => { cpQ = 0; renderCutPackNow(); }); }

function renderCutPackNow(){
  if (!S.doc) return;
  const n = S.sel.size, locked = !!lockJob();
  $('#cutSelected').disabled = $('#keepSelected').disabled = !n || locked;
  $('#cpSelHint').textContent = n ? `チェックした${n}行を、まとめて変えます` : '行の左端のチェックで選んだ行を、まとめて変えます';
  renderDocBar();   // 題名の行の札(カットが使えない文書では、行の印からの目安)
  if (PACK) PACK.refresh();
}

/* 文書を保存したあと: 3 パック のタブの見積もり(字幕の数など)を出し直す */
function cpAfterSave(){ if (S.doc && PACK) PACK.changed(); }

/* 選んだ行をまとめてカット/残す(1行ずつは、行の右の「残す/カット済」。同じ印を変える入口は、この2つだけ) */
function bulkCut(cut){
  if (!S.doc || !S.sel.size) return toast('先に、行の左端のチェックで行を選んでください');
  if (lockJob()) return toast('処理中のため、今は変更できません');
  if (CUT && CUT.active()){
    const idx = S.doc.segments.map((g, i) => S.sel.has(g.id) ? i : -1).filter(i => i >= 0);
    CUT.rowsCut(idx, cut);
    return toast(`${idx.length}行を${cut ? '削る区間に' : '残す区間に'}しました(「元に戻す」(Ctrl+Z)で戻せます)`, 4000);
  }
  pushUndo(); let n = 0;
  for (const g of S.doc.segments) if (S.sel.has(g.id)){ if (cut) g.cutState = 'cut'; else delete g.cutState; n++; }
  renderDoc(); markDirty(); toast(`${n}行を${cut ? 'カット済' : '残す'}にしました(「元に戻す」で戻せます)`, 2500);
}

/* ---------- キー操作の手がかり(行の一覧の上。閉じたら覚える) ---------- */

function applyKeyHint(){ const on = khOn(); $('#keyHint').hidden = !on; $('#keyHintOn').checked = on; }

/* ---------- 確認のダイアログ(はい/やめる) ---------- */

function confirmDlg(title, text, okLabel){
  const dlg = $('#dlgConfirm');
  $('#cfT').textContent = title; $('#cfText').textContent = text || ''; $('#cfOk').textContent = okLabel || 'はい';
  return new Promise(resolve => {
    const done = v => { $('#cfOk').onclick = null; $('#cfCancel').onclick = null; dlg.oncancel = null; if (dlg.open) dlg.close(); resolve(v); };
    $('#cfOk').onclick = () => done(true); $('#cfCancel').onclick = () => done(false);
    dlg.oncancel = e => { e.preventDefault(); done(false); };
    dlg.showModal(); $('#cfCancel').focus();
  });
}

/* ---------- 2 カット(cut.js)。区間の編集は cut.js、行の表示・文書の保存はこちら ---------- */

/* 編集の内容から付け直した行の「カット済」を、1 文字起こし のタブの行に出す(文書は保存しない。サーバーが編集の内容から付ける) */
function onCutMarks(changed){
  updateUndo();   // カットが変わった(変更・元に戻す・やり直す)→ 「元に戻す(n)」の数も(3-5)
  for (const i of changed){
    const row = document.querySelector(`#segs .seg[data-i="${i}"]`), g = S.doc && S.doc.segments[i]; if (!row || !g) continue;
    const cut = g.cutState === 'cut', b = row.querySelector('[data-act=cut]');
    row.classList.toggle('cut', cut);
    if (b){ b.setAttribute('aria-pressed', cut ? 'true' : 'false'); b.textContent = cut ? 'カット済' : '残す'; }
  }
  if (changed.length){ renderCutPack(); syncListItem(); if ($('#flagKind').value === 'cut') applyFilter(); }
  renderDocBar();
}

/* 保存できたら、サーバーが付けた行の印(cutRows)で合わせ直す(規則は同じなので、ふつうは変わらない) */
function onCutSaved(r){
  if (!S.doc) return;
  const set = new Set(r.cutRows || []), changed = [];
  S.doc.segments.forEach((g, i) => { const want = set.has(g.id); if (want !== (g.cutState === 'cut')){ if (want) g.cutState = 'cut'; else delete g.cutState; changed.push(i); } });
  const it = S.list.find(x => x.id === S.docId); if (it){ it.hasEdit = true; it.editRev = r.rev; }
  onCutMarks(changed);
  cpAfterSave();   // 3 パック のタブの見積もりを出し直す
}

/* ---------- 3 パック(pack-tab.js) ---------- */

/* パックを作り終えたら、履歴の一覧の「パック済み」も今の状態に */
function onPacked(id, info){
  const it = S.list.find(x => x.id === id);
  if (it){ Object.assign(it, { pack: { textplus: true, updatedAt: info.at }, packRev: info.rev, packAt: info.at, packStale: false }); renderList(); }
}
