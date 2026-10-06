/* app-list.js — 「編集」の画面: 保存済み一覧(履歴)・選んだ文書をまとめて実行(段10 で app.js から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は index.html の1か所) */
'use strict';

/* ---------- 保存済み一覧(履歴。v0.15.0 で作り直し: docs/spec/ui-guidelines.md 4.) ----------
   サーバーの /api/transcripts が、校正の進み具合・長さ・元の配信・配信者・元の動画とパックの有無を返す(serve.py の list_transcripts)。
   画面では 絞り込み → 並び替え → まとめる(配信ごと/配信者ごと/まとめない)→ 開いているまとまりの分だけ描く(「もっと見る」で足す)。
   同じ題名が並んでも見分けられるように、配信ごとのときは見出しの配信の題名を省いて、マークの名前・元の配信の時刻・いつ・長さを出す */

async function loadList(){
  try { S.list = (await api('/api/transcripts')).items; } catch { S.list = []; }
  renderList(); renderMissing(); scheduleProgress(); if (S.doc){ renderCutPack(); renderDocBar(); }
}

function txGroupKey(i){
  if (L.group === 'channel') return 'c:' + (i.channel || '');
  if (L.group === 'stream') return 'v:' + (i.videoId || '');
  return 'all';
}

function txGroupHead(key, items){
  const f = items[0], when = ago(Math.max(...items.map(i => Number(i.updatedAt) || 0)));
  const done = items.filter(i => txStatus(i) === 'done').length;
  if (key.startsWith('c:')) return { title: f.channel || '配信者が分からないもの', sub: `最終更新 ${when}`, done };
  if (key === 'v:') return { title: '配信と紐づいていない文字起こし', sub: `手元の動画など ・ 最終更新 ${when}`, done };
  return { title: txStream(f) || f.videoId, sub: [f.channel, `最終更新 ${when}`].filter(Boolean).join(' ・ '), done };
}

function txSortFn(){
  const up = (a, b) => (Number(b.updatedAt) || 0) - (Number(a.updatedAt) || 0);
  const left = i => (Number(i.rows) || 0) - (Number(i.proofed) || 0);
  if (L.sort === 'created') return (a, b) => (Number(b.createdAt) || 0) - (Number(a.createdAt) || 0);
  if (L.sort === 'remain') return (a, b) => left(b) - left(a) || up(a, b);
  if (L.sort === 'title') return (a, b) => String(a.title || '').localeCompare(String(b.title || ''), 'ja') || up(a, b);
  return up;
}

/* 非表示の操作は ui-kit の UIKit.hide(入口から開いたときだけ使える)。隠していても、今開いている文書は一覧から消さない */
const hideOn = () => !!(window.UIKit && UIKit.hide && UIKit.hide.available());
const txIsHidden = i => hideOn() && UIKit.hide.has('transcripts', i.id);

function txFiltered(opt){
  const q = norm($('#txSearch').value.trim());
  const keepHidden = (opt && opt.withHidden) || !hideOn() || UIKit.hide.showing('transcripts');
  return S.list.filter(i => {
    if (!keepHidden && i.id !== S.docId && UIKit.hide.has('transcripts', i.id)) return false;
    if (L.kind === 'clip' && !i.hasClip) return false;
    if (L.kind === 'other' && i.hasClip) return false;
    if (L.kind === 'eval' && !i.evalSet) return false;
    if (L.state !== 'all' && txStatus(i) !== L.state) return false;
    return !q || norm(`${i.title || ''} ${txStream(i)} ${i.clipTitle || ''} ${i.channel || ''} ${i.sourceName || ''} ${i.markLabel || ''}`).includes(q);
  }).sort(txSortFn());
}

/* 1件の表示用の題名: 配信ごとにまとめているときは、見出しにある配信の題名を省いて「違う部分」(マークの名前など)を出す */
function txShortTitle(i){
  const t = String(i.title || '').trim() || '無題';
  if (L.group !== 'stream') return t;
  for (const p of [txStream(i), i.clipTitle].filter(Boolean)){
    if (t.startsWith(p) && t.length > p.length){ const rest = t.slice(p.length).replace(/^[\s・:：\-–—|]+/, '').trim(); if (rest) return rest; }
  }
  return t;
}

function txRowHTML(i){
  const st = txStatus(i), r = Number(i.rows) || 0, p = Number(i.proofed) || 0, full = String(i.title || '無題');
  const pick = PICK.on ? `<input type="checkbox" class="txi-pick" data-act="pick"${PICK.ids.has(i.id) ? ' checked' : ''} aria-label="${esc(full)} を選ぶ">` : '';
  /* だれの・いつの を先に(狭いと後ろが「…」で切れるため)。まとまりの見出しにある情報は省く */
  const meta = [];
  if (L.group === 'none' && i.channel) meta.push(i.channel);
  if (!i.hasClip && i.sourceName) meta.push(i.sourceName);                  // 配信と紐づかないものは、ファイル名で見分ける
  meta.push(ago(Number(i.updatedAt) || Number(i.createdAt) || 0));
  if (i.hasClip && i.clipStart !== null && Number.isFinite(Number(i.clipStart))) meta.push('配信の ' + fmtT(i.clipStart) + '〜');
  if (Number(i.durationSec) > 0) meta.push(window.UIKit && UIKit.fmt ? UIKit.fmt.dur(i.durationSec) : fmtT(i.durationSec));
  const side = [];
  if (i.evalSet) side.push('<span class="pill info" title="精度を測るためだけに取っておく文字起こし(学習・辞書に使わない)">評価用</span>');
  if (i.mediaOk === false) side.push(`<span class="pill warn" title="元の動画が見つかりません(移動・削除した可能性があります)。文字の直しと書き出しはできます">動画なし</span>`);
  if (st === 'todo') side.push(`<span class="pill wait" title="まだ1行も校正していません(${r}行)">未校正</span>`);
  else if (st === 'doing') side.push(`<span class="tt-prog" title="校正済み ${p}行 / ${r}行"><i><b style="width:${Math.round(p / Math.max(1, r) * 100)}%"></b></i>${p}/${r}</span>`);
  if (i.pack) side.push(Number(i.pack.updatedAt) < (Number(i.updatedAt) || 0) - 2000
    ? '<span class="ui-next" title="パックを作ったあとに、行を直しています">作り直す</span>'
    : `<span class="pill ok" title="パック(${i.pack.textplus ? 'Text+ 字幕つき' : 'カットだけ'})を作ってあります">パック済み</span>`);
  else if (st === 'done') side.push(i.hasClip && i.mediaOk !== false ? '<span class="ui-next" title="校正が終わりました。開いて 3 パック のタブで作ります">パックを作る</span>' : '<span class="pill ok">校正済み</span>');
  const info = [i.sourceName, txStream(i) && txStream(i) !== full ? '元の配信: ' + txStream(i) : '', i.channel, `${Number(i.segments) || 0}行`, String(i.model || '').split('/').pop()].filter(Boolean).join(' ・ ');
  const hid = txIsHidden(i);
  if (hid) side.push('<span class="ui-hidden-tag">非表示</span>');
  const hideBtn = hideOn() ? (hid ? '<button type="button" class="btn small" data-act="unhide" title="一覧にまた出します">表示に戻す</button>' : '<button type="button" class="btn small" data-act="hide" title="履歴に出さないだけで、文字起こしは消しません">一覧で非表示にする</button>') : '';
  return `<div class="txi${i.id === S.docId ? ' cur' : ''}${hid ? ' ui-hidden-item' : ''}" data-id="${esc(i.id)}">
    <div class="txi-head">${pick}<button type="button" class="t" data-act="open" title="${esc(full)}"${i.id === S.docId ? ' aria-current="true"' : ''}>${esc(txShortTitle(i))}</button><details class="pop txi-menu"><summary aria-label="${esc(full)} の操作と詳しい情報" title="操作と詳しい情報">⋮</summary><div class="vpop"><p class="tt-full">${esc(full)}</p><span class="hint">${esc(info)}</span>${i.mediaOk === false ? '<button type="button" class="btn small" data-act="relink">動画を選び直す</button>' : ''}${hideBtn}<button type="button" class="btn small danger" data-act="del">この文字起こしを削除</button></div></details></div>
    <div class="txi-sub"><span class="txi-meta">${esc(meta.filter(Boolean).join(' ・ '))}</span><span class="txi-side">${side.join('')}</span></div>
  </div>`;
}

/* ---------- 選んだ文書をまとめて(12 ⑦(b)。入口の /api/autorun/start-docs。入口から開いたときだけ) ---------- */

/* 入口の API(/api/...)。画面は入口の /transcribe/ の下にあるので、画面の場所から1つ上(絶対パスを書かない) */
async function portalApi(path, body){
  const init = { cache: 'no-store', method: body === undefined ? 'GET' : 'POST' };
  if (body !== undefined){ init.headers = { 'Content-Type': 'application/json', 'X-YTT-Token': TOKEN }; init.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(new URL('../' + path, location.href).href, init); } catch { throw new Error('ホームのサーバーに接続できません(start.bat の黒い画面が閉じていないか確かめてください)'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok){ const er = new Error(j.message || ('エラー ' + r.status)); er.code = j.error; er.status = r.status; throw er; }
  return j;
}

function renderPickBar(){
  $('#txBatch').hidden = !PICK.on;
  const n = PICK.ids.size;
  $('#txPickN').textContent = n > PICK_MAX ? `${n} 本を選んでいます(一度に ${PICK_MAX} 本までです)` : n ? `${n} 本を選んでいます(${PICK_MAX} 本まで)` : `文書を選んでください(一覧の行の左のチェック。${PICK_MAX} 本まで)`;
  $('#txBatchGo').disabled = !n || n > PICK_MAX;
}

/* 表示中を全部選ぶ / パックが無いものだけ選ぶ(S-11)。20 本までにして、あふれたら知らせる */
function pickTx(onlyNoPack){
  const items = txFiltered().filter(i => !onlyNoPack || !i.pack);
  PICK.ids.clear(); for (const i of items.slice(0, PICK_MAX)) PICK.ids.add(i.id);
  renderList(); renderPickBar();
  if (items.length > PICK_MAX) toast(`一度に選べるのは ${PICK_MAX} 本までです(上から ${PICK_MAX} 本を選びました)`, 5000);
  else if (!items.length) toast(onlyNoPack ? 'パックが無い文書はありません' : '選べる文書がありません', 4000);
}

function renderRuns(runs){
  const box = $('#txRuns');
  box.innerHTML = runs.slice(0, 10).map(r => {
    const cls = r.nothing ? 'info' : RUN_CLS[r.state] || 'info', label = runLabelOf(r);
    const steps = r.steps.map(s => `${esc(s.label)}: ${esc(stepLabelOf(s))}${s.detail ? '(' + esc(s.detail) + ')' : ''}`).join(' / ');
    return `<div class="tt-run" data-run="${esc(r.id)}" data-doc="${esc(r.docId || '')}"><b title="${esc(r.title)}">${esc(r.title)}</b><span class="pill ${cls}">${esc(label)}</span>` +
      (r.state === 'queued' || r.state === 'running' ? '<button type="button" class="btn small" data-act="runcancel">中止</button>' : '') +
      (r.state === 'done' && r.docId ? '<button type="button" class="btn small" data-act="runopen">開く</button>' : '') +
      `<span class="tt-run-steps">${steps}${r.error ? ' ・ ' + esc(r.error) : ''}</span></div>`;
  }).join('');
}

async function pollRuns(){
  clearTimeout(PICK.polling);
  if (!TOKEN) return;
  let runs = [];
  try { runs = ((await portalApi('api/autorun')).runs || []).filter(r => r.kind === 'doc'); } catch { return; }
  PICK.lastRuns = runs; renderRuns(runs); renderDocAuto(runs);
  const active = new Set(runs.filter(r => r.state === 'queued' || r.state === 'running').map(r => r.id));
  if ([...PICK.active].some(id => !active.has(id))){   // 終わった実行があれば、一覧の「パック済み」などを今の状態に
    loadList();
    const fin = runs.find(r => r.docId === S.docId && PICK.active.has(r.id) && !active.has(r.id));
    if (fin && PACK && !S.dirty) PACK.load(S.docId);   // 今の文書のパックができた: パックのタブの「前回のパック」を読み直す
  }
  PICK.active = active;
  if (active.size) PICK.polling = setTimeout(pollRuns, 2000);
}

/* 今の文書を最後まで(題名の行の「まとめて実行 ▾」。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 3): 履歴の「選んで、まとめて実行」と同じ入口の API を1本で。
   先に文書とカットを保存する(まとめて実行は保存済みの内容を読む)。進み具合は pollRuns が題名の行の札に出す */
async function startDocAuto(){
  const id = S.docId; if (!id || !TOKEN) return;
  const b = $('#docAutoGo'); b.disabled = true;
  try {
    if (!(await saveDoc()) || (CUT && !(await CUT.flush()))) return toast('保存が追いついていません。少し待ってから、もう一度押してください', 5000, 'err');
    const who = window.UIKit && UIKit.streamer && UIKit.streamer.check ? await UIKit.streamer.check($('#docAutoWho')) : $('#docAutoWho').value.trim();
    if (who === null) return;   // 見つからない名前で「やめる」を選んだ(S-20)
    const body = { ids: [id], overwrite: $('#docAutoOverwrite').checked, streamer: who };   // 空 = 色なし(欄は自動で入る)
    const ar = window.UIKit && UIKit.autorun;   // 見積もり → 始める → 終わったら知らせる(どの入口も同じ部品。段4)
    const r = ar ? await ar.start('api/autorun/start-docs', body, { ids: [id], overwrite: body.overwrite }) : await portalApi('api/autorun/start-docs', body);
    if (!r) return;   // やることが無い(知らせは部品が出す)
    if ((r.runs || []).length) $('#docAuto').open = false;
    else toast('始められませんでした: ' + ((r.skipped || [])[0] ? r.skipped[0].reason : '理由が分かりません'), 7000, 'err');
    pollRuns();
  } catch (e){ toast('まとめて実行を始められませんでした: ' + e.message, 7000, 'err'); }
  finally { b.disabled = false; }
}

function renderDocAuto(runs){   // 題名の行の札: 今の文書のいちばん新しい実行(終わって10分より前のものは出さない)
  const pill = $('#pillAuto'); if (!pill) return;
  const r = S.docId ? runs.find(x => x.docId === S.docId) : null;
  const active = !!r && (r.state === 'queued' || r.state === 'running');
  if (!r || (!active && Date.now() - (r.finished || 0) > 10 * 60 * 1000)){ pill.hidden = true; return; }
  const cls = r.nothing ? 'info' : RUN_CLS[r.state] || 'info', label = runLabelOf(r);
  const step = (r.steps || []).find(s => s.state === 'run');
  pill.className = 'pill ' + cls; pill.hidden = false;
  pill.textContent = 'まとめて実行: ' + label + (step ? '(' + step.label + ')' : '');
  pill.title = (r.steps || []).map(s => `${s.label}: ${stepLabelOf(s)}${s.detail ? '(' + s.detail + ')' : ''}`).join(' / ') + (r.error ? ' ・ ' + r.error : '');
}

async function startBatch(){
  const ids = [...PICK.ids]; if (!ids.length) return;
  const b = $('#txBatchGo'); b.disabled = true;
  try {
    const who = $('#txBatchWho').value.trim();   // 手で入れたときだけ字幕の色に
    const body = { ids, overwrite: $('#txOverwrite').checked, ...(who ? { streamer: who } : {}) };
    const ar = window.UIKit && UIKit.autorun;   // 見積もり → 始める → 終わったら知らせる(どの入口も同じ部品。段4)
    const r = ar ? await ar.start('api/autorun/start-docs', body, { ids, overwrite: body.overwrite }) : await portalApi('api/autorun/start-docs', body);
    if (!r) return;
    PICK.ids.clear(); renderList(); renderPickBar(); pollRuns();
  } catch (e){ toast('まとめて実行を始められませんでした: ' + e.message, 7000, 'err'); }
  finally { renderPickBar(); }
}

function txRowsHTML(key, items){
  const lim = txLimit[key] || (key === 'all' ? FLAT_FIRST : GROUP_FIRST), rest = items.length - Math.min(lim, items.length);
  return items.slice(0, lim).map(txRowHTML).join('') + (rest > 0 ? `<button type="button" class="btn small list-more" data-act="more" data-g="${esc(key)}">もっと見る(残り${rest}件)</button>` : '');
}

function renderList(){
  const box = $('#txList'), total = S.list.length;
  $('#txTotal').textContent = total ? `(${total}件)` : '';   // 折りたたんでも件数が見えるように
  if (!total){ $('#txCount').textContent = ''; if (hideOn()) UIKit.hide.toggle($('#txHiddenToggle'), 'transcripts', 0); box.innerHTML = '<p class="hint" style="margin:6px 0 0">まだ文字起こしはありません。「新規」から文字起こしすると、ここに出ます。</p>'; return; }
  const found = txFiltered();
  if (hideOn()){   // 隠れている数 = 非表示以外の絞り込みに合うもののうち、非表示のもの(今の文書は除く)
    const hn = txFiltered({ withHidden: true }).filter(i => i.id !== S.docId && UIKit.hide.has('transcripts', i.id)).length;
    UIKit.hide.toggle($('#txHiddenToggle'), 'transcripts', hn);
  }
  $('#txCount').textContent = found.length === total ? `${total}件` : `${found.length} / ${total}件`;
  if (!found.length){ box.innerHTML = '<p class="hint" style="margin:8px 0">条件に合う文字起こしはありません。検索の文字や、状態・種類の絞り込みを変えてみてください。</p>'; return; }
  if (L.group === 'none'){ txGroups = new Map([['all', found]]); box.innerHTML = `<div class="tt-g-rows tt-flat">${txRowsHTML('all', found)}</div>`; return; }
  txGroups = new Map();
  for (const i of found){ const k = txGroupKey(i); if (!txGroups.has(k)) txGroups.set(k, []); txGroups.get(k).push(i); }
  const cur = S.docId && S.list.find(i => i.id === S.docId), curKey = cur ? txGroupKey(cur) : null;
  if (curKey){ txOpen.add(curKey); if (txAuto && txAuto !== curKey) txOpen.delete(txAuto); txAuto = null; }   // 今開いている文書のまとまりだけ開く
  if (!txInitDone){ txInitDone = true; if (!txOpen.size){ txAuto = txGroups.keys().next().value; txOpen.add(txAuto); } }   // 文書を開いていなければ、先頭のまとまりを開く
  const q = $('#txSearch').value.trim();
  box.innerHTML = [...txGroups].map(([k, items]) => {
    const h = txGroupHead(k, items), open = !!q || txOpen.has(k);   // 検索中は、当たったまとまりを全部開く
    return `<details class="ui-group" data-g="${esc(k)}"${open ? ' open' : ''}><summary><span class="tt-g-main"><b title="${esc(h.title)}">${esc(h.title)}</b><small>${esc(h.sub)}</small></span><span class="ui-group-n" title="${items.length}本のうち、校正済み ${h.done}本">${items.length}本${h.done ? `<span class="tt-g-done"> ・ 済${h.done === items.length ? 'み' : ' ' + h.done}</span>` : ''}</span></summary><div class="tt-g-rows">${open ? txRowsHTML(k, items) : ''}</div></details>`;
  }).join('');
}

/* 保存したら、一覧の進み具合も今の内容に合わせる(一覧を読み直さずに。開いている「⋮」を閉じないよう、少し待ってから) */
function syncListItem(){
  const d = S.doc, it = d && S.list.find(x => x.id === S.docId); if (!it) return;
  const segs = d.segments, txt = segs.filter(g => g.text.trim());
  Object.assign(it, { title: d.title, evalSet: d.evalSet === true, segments: segs.length, rows: txt.length, proofed: txt.filter(g => g.proofed).length,
    cut: segs.filter(g => g.cutState === 'cut').length, flagged: segs.filter(g => g.flag).length, updatedAt: S.baseUpdatedAt || it.updatedAt });
  clearTimeout(syncListItem.t);
  syncListItem.t = setTimeout(() => { if (!document.querySelector('#txList details.txi-menu[open]')) renderList(); }, 1500);
}
