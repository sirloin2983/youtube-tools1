/* app-tools.js — 「編集」の画面: 動画を選び直す・検索と置換・書き出し・受け渡し・確認のダイアログ・カット・パックのタブとのつなぎ。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は src/app/ui/cases/edhost.js の ED_SCRIPTS の1か所) */
'use strict';

/* ---------- 動画を選び直す。付け替えの API は POST だけ(URL の引数では付け替えない) ---------- */

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

/* 「参照…」: PC の標準の窓で選ぶ。窓はサーバーが開く(ブラウザからは実際のパスを知れないため。ytt/pick.py)。やめたら null */
async function pickPath(kind, hint){
  try { const r = await api('/api/pick', { body: { kind, hint: hint || '' } }); return r.path || null; }
  catch (e){ toast(e.message, 6000, 'err'); return null; }
}

/* ブラウザのタブの題名: 「● タイトル - 編集」(● は未保存・保存できていない) */
function updateDocTitle(){
  const d = S.doc, st = $('#saveState').getAttribute('data-state');
  document.title = d ? `${S.dirty || S.saving || st === 'err' ? '● ' : ''}${String(d.title || '無題').slice(0, 60)} - 編集` : '編集';   // ui-audit: allow A-10 窓の題名の未保存の印(画面のアイコンではない)
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
  const it = curItem() || {}, parts = [];
  if (it.channel) parts.push(it.channel);
  const len = docLength(d); if (len > 0) parts.push(fmtT(len));
  const rg = d.clip && typeof d.clip === 'object' && d.clip.range && typeof d.clip.range === 'object' ? d.clip.range : null, a = rg ? Number(rg.start) : NaN;
  if (Number.isFinite(a)) parts.push('元の配信 ' + fmtT(a) + '〜');
  const meta = $('#docMeta'); meta.textContent = parts.join(' ・ '); meta.title = String(d.sourcePath || '');
  const txt = d.segments.filter(hasText), pf = txt.filter(g => g.proofed).length;
  const pp = $('#pillProof'); pp.hidden = !txt.length; pp.textContent = `校正 ${pf} / ${txt.length}行`; pp.className = 'pill ' + (txt.length && pf === txt.length ? 'ok' : 'wait');
  const pc = $('#pillCut'), sp = cpApproxSpans();   // 校正の欄にはカットの区間が無い = 行の印からの目安
  pc.hidden = !sp.length; pc.textContent = `残す ${sp.length}区間 ・ カット後 約${fmtCs(sp.reduce((x, [p, q]) => x + q - p, 0))}`;
}

/* ---------- 検索・話者・置換 ---------- */

function syncEval(){
  const on = !!(S.doc && S.doc.evalSet), lock = !!(S.doc && S.doc.evalLocked), cb = $('#evalSet');
  cb.checked = on || lock; cb.disabled = lock; cb.parentElement.title = lock ? EVAL_LOCK_MSG : EVAL_TITLE;
  $('#evalBanner').hidden = !(on || lock); renderVoiceLearn();   // 評価用では「声を覚える」を押せない
  renderEvalReview();   // 「確かめ済み」(開いた文書・評価用の切り替えに合わせる)
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

function renderSpNames(){
  let dl = document.getElementById('spNames');
  if (!dl){ dl = document.createElement('datalist'); dl.id = 'spNames'; document.body.appendChild(dl); }
  const who = $('#pkWho') ? $('#pkWho').value.trim() : '';
  const roster = S.roster ? [...new Set(S.roster.groups.filter(g => g.id !== 'units').flatMap(g => g.names))] : [];
  const names = [...new Set([...spVoiceNames, ...(who ? [who] : []), ...roster])].slice(0, 300);
  const key = names.join('\n'); if (dl.dataset.key === key) return;
  dl.dataset.key = key; dl.innerHTML = names.map(n => `<option value="${esc(n)}">`).join('');
}

/* 話者判別が終わったら: 名前が付いていない話者の最初の名前の欄へ */
function focusSpeakerNames(){
  const d = $('#spDetails'); if (!d || !S.doc) return;
  d.hidden = false; d.open = true;
  const i = S.doc.speakers.findIndex(s => !String(s.name || '').trim() || /^話者\d+$/.test(String(s.name)) || s.name === s.id);
  const inp = $('#spList').querySelectorAll('.sp-row input.tt-sp-name')[Math.max(0, i)];   // 名前の欄(字幕の色の欄も type=text なので名前で選ぶ)
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

/* sub = 字幕の形(SRT・VTT)。字幕に出さない行(noSub)は入れない(テキスト・JSON には入れる = 読み物・データとしては残す) */
function exportRows(sub){
  const d = S.doc, only = $('#exSel').checked;
  const base = $('#exBase').value === 'rel' && !d.whole ? d.start : 0;
  const wrap = Number($('#exWrap').value) || 0, spk = $('#exSpk').checked;
  const rows = [];
  for (const s of d.segments){
    if (only && !S.sel.has(s.id)) continue;
    if (!s.text.trim() || s.end - base <= 0 || (sub && s.noSub)) continue;
    const sp = spById(s.speaker);
    rows.push({ start: Math.max(0, s.start - base), end: s.end - base, text: wrapText(s.text.trim(), wrap), name: spk && sp ? sp.name : '', noSub: !!s.noSub });
  }
  return rows;
}

/* 重なる字幕の段分け(SRT・VTT。10-23。規則は src/pipeline/pack/srt2resolve.py の stack_overlaps と同じ): 重なる間は、その時に出ている字幕の文を
   始まりの順に改行でつないだ 1 つの字幕に分ける。0.3 秒未満のはみ出しは前の字幕を次の始まりで切る。話者名は文の頭に付けてからつなぐ */
const STACK_SMALL = 0.3;
function stackRows(rows){
  const out = rows.map((r, k) => ({ start: r.start, end: r.end, text: (r.name ? '[' + r.name + '] ' : '') + r.text, k }))
    .sort((a, b) => a.start - b.start || a.end - b.end || a.k - b.k);
  out.forEach((r, k) => { r.k = k; });
  for (let j = 1; j < out.length; j++){ const p = out[j - 1], c = out[j]; if (p.start < c.start && c.start < p.end && p.end - c.start < STACK_SMALL) p.end = c.start; }
  const live = out.filter(r => r.end > r.start);
  let end = null, clash = false;
  for (const r of live){ if (end != null && r.start < end){ clash = true; break; } end = end == null ? r.end : Math.max(end, r.end); }
  if (!clash) return live.map(r => ({ start: r.start, end: r.end, text: r.text, name: '' }));
  const edges = [...new Set(live.flatMap(r => [r.start, r.end]))].sort((a, b) => a - b), pieces = [];
  for (let i = 0; i + 1 < edges.length; i++){
    const a = edges[i], b = edges[i + 1], on = live.filter(r => r.start <= a && r.end >= b);
    if (!on.length) continue;
    const text = on.sort((x, y) => x.k - y.k).map(r => r.text).join('\n'), last = pieces[pieces.length - 1];
    if (last && last.end === a && last.text === text) last.end = b; else pieces.push({ start: a, end: b, text, name: '' });
  }
  return pieces;
}

function buildExport(kind){
  let rows = exportRows(kind === 'srt' || kind === 'vtt'), d = S.doc;
  if (!rows.length) return null;
  if (kind === 'srt' || kind === 'vtt') rows = stackRows(rows);   // 重なる字幕は段に分ける(話者名は文に入れた)
  if (kind === 'srt') return rows.map((r, i) => `${i + 1}\n${tcode(r.start, ',')} --> ${tcode(r.end, ',')}\n${r.name ? '[' + r.name + '] ' : ''}${r.text}\n`).join('\n');
  if (kind === 'vtt'){
    const e = t => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return 'WEBVTT\n\n' + rows.map(r => `${tcode(r.start, '.')} --> ${tcode(r.end, '.')}\n${r.name ? e('[' + r.name + '] ') : ''}${e(r.text)}\n`).join('\n');
  }
  if (kind === 'txt'){
    const ts = $('#exTs').checked;
    return rows.map(r => `${ts ? '[' + fmtT(r.start) + '] ' : ''}${r.name ? r.name + ': ' : ''}${r.text.replace(/\n/g, '')}`).join('\n') + '\n';
  }
  return JSON.stringify({ title: d.title, source: d.sourceName, start: d.start, end: d.end, speakers: d.speakers, segments: rows.map(r => ({ start: r.start, end: r.end, speaker: r.name, text: r.text.replace(/\n/g, ''), ...(r.noSub ? { noSub: true } : {}) })) }, null, 1);
}

/* ---------- 受け渡し(notes:docs/spec/pipeline.md 2・3・6): 元の配信(.clip.json)・URL で渡された動画・動画の隣に保存 ---------- */

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

function renderDocExtras(d){
  const box = $('#docClip'), clip = d && d.clip;
  if (clip && typeof clip === 'object'){ box.className = 'tt-clip'; box.innerHTML = clipHTML(clip); box.hidden = false; }
  else { box.hidden = true; box.innerHTML = ''; }
  if (S.handoff && S.handoff.id !== S.docId) S.handoff = null;
  renderHandoff();
}

function renderHandoff(){
  const box = $('#handoffOut'), h = S.handoff;
  if (!S.doc || !h || h.id !== S.docId){ box.hidden = true; box.innerHTML = ''; return; }
  const rows = [['transcript', '文字起こし'], ['srt', '字幕']].filter(([k]) => h[k]).map(([k, l]) => handoffRow(h, k, l)).join('');
  box.innerHTML = rows + '<div class="row"><span class="hint">Resolve へ渡すパックは <b>カット・パック</b> のタブで作ります</span></div>';
  box.hidden = !rows;
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
    renderHandoff();
    toast(`${r.overwritten ? '上書き保存' : '保存'}しました: ${r.name}(${Number(r.count) || 0}行)`, 5000, 'ok');
  } catch (e){
    if (e.status === 409) toast('保存が追いついていません(書き出す直前に内容が変わりました)。少し待ってから、もう一度押してください', 6000, 'err');
    else toast('作業用フォルダに保存できませんでした: ' + e.message, 7000, 'err');
  } finally { btn.disabled = false; btn.textContent = label; }
}

/* 題名の行の「残す区間」の目安(校正の欄にはカットの区間が無い): 残す行(文字があり、カット済でない)の時間を、重なりをまとめて足す */
function cpApproxSpans(){
  const spans = S.doc.segments.filter(g => g.cutState !== 'cut' && hasText(g) && g.end > g.start).map(g => [g.start, g.end]).sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const [a, b] of spans){ const cur = out[out.length - 1]; if (cur && a <= cur[1]) cur[1] = Math.max(cur[1], b); else out.push([a, b]); }
  return out;
}

function renderCutPack(){ if (!cpQ) cpQ = requestAnimationFrame(() => { cpQ = 0; renderCutPackNow(); }); }

function renderCutPackNow(){
  if (!S.doc) return;
  const n = S.sel.size, locked = !!lockJob();
  $('#cutSelected').disabled = $('#keepSelected').disabled = !n || locked;
  $('#cutSelected').title = $('#keepSelected').title = locked ? '処理中は変えられません(終わると押せます)' : (n ? '' : '行の左端のチェックで行を選ぶと押せます');   // 押せない理由
  $('#cpSelHint').textContent = n ? `チェックした${n}行を、まとめて変えます` : '行の左端のチェックで選んだ行を、まとめて変えます';
  renderDocBar();   // 題名の行の札
}

/* カットの欄(EditCut)は別のパネルにあって校正の中には無い。カットの区間(edit.json)が決まっている文書で行の印だけを
   変えると、保存のときにサーバーが区間から印を付け直して黙って消える(区間は変わらない)。区間があるときは何も変えずにカット・パックのタブへ案内し、
   まだ無いとき(行の印がカットの正)だけ印を変える。idx = 行の番号の並び */
async function hostRowsCut(idx, cut){
  const id = S.docId;
  let edit = null;
  try { edit = (await api('/api/edit?id=' + encodeURIComponent(id))).edit; } catch (e){ return toast('カットの区間を確かめられませんでした: ' + e.message, 4000, 'err'); }
  if (S.docId !== id || !S.doc) return;
  if (edit){
    return toast('この切り抜きはカットの区間が決まっているので、残す・カットは「カット・パック」のタブで変えます(行の印はそのまま)',
      { ms: 7000, kind: 'info', action: { label: 'カット・パックへ', fn: () => EDIT_HOST.tab('cut') } });
  }
  pushUndo(); let n = 0;
  for (const i of idx){ const g = S.doc.segments[i]; if (g){ setCut(g, cut); n++; } }
  renderDoc(); markDirty(); renderCutPack();
  toast(`${n}行を${cut ? 'カット済' : '残す'}にしました(「元に戻す」で戻せます)`, 2500);
}
/* 選んだ行をまとめてカット済に/残す(1行ずつは、行の右の「残す / カット」) */
function bulkCut(cut){
  if (!S.doc || !S.sel.size) return toast('先に、行の左端のチェックで行を選んでください');
  if (lockJob()) return toast('処理中のため、今は変更できません');
  return hostRowsCut(S.doc.segments.map((g, i) => S.sel.has(g.id) ? i : -1).filter(i => i >= 0), cut);
}

/* ---------- キー操作の手がかり(行の一覧の上。閉じたら覚える) ---------- */

function applyKeyHint(){ const on = khOn(); $('#keyHint').hidden = !on; $('#keyHintOn').checked = on; }

/* ---------- 確認のダイアログ(はい/やめる) ----------
   ui-kit の UIKit.dialog.confirm。本文の改行は残す(.ui-dlg-body) */
function confirmDlg(title, text, okLabel){
  return UIKit.dialog.confirm({ title, body: text || '', ok: okLabel || 'はい', cancel: 'やめる' });
}
