/* app-jobs.js — 「編集」の画面: 新規ジョブ・フォルダ一括・スタジオ/マーカー連携・ジョブの進捗・話者の自動判別・声を覚える・再認識(段10 で app.js から分けた。docs/plan/phase10-code-split.md)。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は index.html の1か所) */
'use strict';

/* ---------- 新規ジョブ ---------- */

function setTab(t){
  tab = t; $('#paneFile').hidden = t !== 'file'; $('#paneMarker').hidden = t !== 'marker'; $('#paneFolder').hidden = t !== 'folder';
  $('#tabFile').setAttribute('aria-pressed', t === 'file'); $('#tabMarker').setAttribute('aria-pressed', t === 'marker'); $('#tabFolder').setAttribute('aria-pressed', t === 'folder');
  $('#btnStart').textContent = t === 'file' ? '文字起こしを開始' : t === 'folder' ? '選んだ動画を、それぞれ文字起こし' : '選んだポイントを文字起こし';
  $('#btnOpenVideo').hidden = t !== 'file';
  if (t === 'folder') fdSyncStudio();
  if (t === 'marker') renderMarker();
}

function jobOpts(){
  return { model: $('#optModel').value, language: $('#optLang').value, quality: $('#optQuality').value, device: $('#optDevice').value, vadMode: $('#optVad').value, boost: $('#optBoost').checked, autoDict: $('#optAutoDict').checked, wordSplit: $('#optWordSplit').checked, ...subtitleReq(), stripPunct: $('#optStripPunct').checked, autoGloss: $('#optAutoGloss').checked, autoContext: $('#optAutoContext').checked, autoLearned: $('#optAutoLearned').checked, autoRedo: $('#optAutoRedo').checked, autoAlt: $('#optAutoAlt').checked, autoDiarize: $('#optAutoDiar').checked, redoLarge: $('#optRedoLarge').checked, glossary: $('#optGloss').value, evalSet: $('#optEvalStart').checked };
}

async function startFile(){
  const path = $('#srcPath').value.trim();
  if (!path) return toast('ファイルのパスを入力してください');
  const a = $('#rStart').value.trim(), b = $('#rEnd').value.trim();
  const body = { sourcePath: path, title: $('#jTitle').value.trim(), ...jobOpts() };
  if (a){ const v = parseT(a); if (!Number.isFinite(v)) return toast('開始の時刻が正しくありません(例: 1:23:45)'); body.start = v; }
  if (b){ const v = parseT(b); if (!Number.isFinite(v)) return toast('終了の時刻が正しくありません(例: 1:30:00)'); body.end = v; }
  await api('/api/transcribe', { body });
  toast('待機列に追加しました');
}

async function startMarker(){
  const v = S.marker.videos[Number($('#mVideo').value)];
  if (!v) return toast('動画を選んでください');
  const path = $('#mPath').value.trim();
  const ids = [...document.querySelectorAll('#mClips input:checked')].map(x => Number(x.dataset.i));
  if (!ids.length) return toast('文字起こしするポイントを選んでください');
  if (!path){   // 元の動画が手元に無いときは、スタジオが書き出した切り抜き(mp4)を、そのまま文字起こしする
    const files = ids.map(i => v.clips[i].fileAbs).filter(Boolean);
    if (!files.length) return toast('元の動画・音声ファイルのパスを入力してください(書き出し済みの切り抜きが見つかったポイントは、パスなしでも文字起こしできます)');
    const r = await api('/api/transcribe-batch', { body: { paths: files, skipDone: true, ...jobOpts() } });
    return toast(`書き出し済みの切り抜き ${r.added.length}本を待機列に追加しました` + (r.skipped.length ? `(${r.skipped.length}本は文字起こし済みなどで追加せず)` : '') + (files.length < ids.length ? `。書き出されていない${ids.length - files.length}件は対象外` : ''), 6000);
  }
  const pad = Number($('#mPad').value) || 0;
  let n = 0;
  for (const i of ids){
    const c = v.clips[i];
    const start = Math.max(0, c.start - pad), end = c.end + pad;
    try {
      await api('/api/transcribe', { body: { sourcePath: path, start, end, title: c.title || `${v.title || v.videoId} ${fmtT(c.start)}-${fmtT(c.end)}`, ...jobOpts() } });
      n++;
    } catch (e){ toast(`${n}件追加したところで失敗: ${e.message}`); break; }
  }
  if (n) toast(`${n}件を待機列に追加しました`);
}

/* 文字起こしせずに開く: 動画のパスだけで文書を作り(同じ動画の文書があればそれ)、カットのタブを開く */
async function openVideoNoTx(){
  const path = $('#srcPath').value.trim();
  if (!path) return toast('動画のパスを入力してください');
  const b = $('#btnOpenVideo'); b.disabled = true;
  try {
    const r = await api('/api/open-video', { body: { path, title: $('#jTitle').value.trim() } });
    await loadList();
    if (!(await openDoc(r.id))) return;
    $('#mediaChoice').hidden = true;
    if (r.created) setEditTab('cut');
    toast(r.created ? '文字起こしせずに開きました。カットのタブで残す・削る所を決められます(文字起こしは 1 文字起こし のタブから、あとでもできます)' : 'この動画は前に開いています。その文書を開きました', 6000, 'ok');
    for (const w of r.warnings || []) toast(w, 6000);
  } catch (e){ toast(e.message, 6000, 'err'); }
  finally { b.disabled = false; }
}

async function onStart(){
  readOpts();
  const btn = $('#btnStart'); btn.disabled = true;
  try { await (tab === 'file' ? startFile() : tab === 'folder' ? startFolder() : startMarker()); startPolling(); await pollJobs(); }
  catch (e){ toast(e.message); }
  finally { btn.disabled = false; }
}

/* ---------- フォルダ内すべて ---------- */

function fdSyncStudio(){ const b = $('#fdStudio'); b.hidden = !S.marker.outDir; }

function renderFolder(){
  const box = $('#fdList'), skip = $('#fdSkip').checked;
  if (!FD.files.length){ box.innerHTML = '<p class="hint" style="padding:8px;margin:0">動画・音声が見つかりませんでした</p>'; $('#fdCount').textContent = ''; return; }
  box.innerHTML = FD.files.map((f, i) => {
    const st = f.doneTid ? '文字起こし済み' : f.queued ? '待機中' : '', off = skip && st;
    return `<label><input type="checkbox" data-i="${i}" ${off ? '' : 'checked'}><span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(f.path)}">${esc(f.rel)}</span><span class="hint">${fmtSize(f.size)}</span>${st ? `<span class="pill">${st}</span>` : ''}</label>`;
  }).join('');
  updateFdCount();
}

function updateFdCount(){ const n = document.querySelectorAll('#fdList input:checked').length, t = document.querySelectorAll('#fdList input').length; $('#fdCount').textContent = t ? `${n} / ${t} 本を選択` + (FD.truncated ? '(多いので、先頭の500本だけ)' : '') : ''; $('#fdAll').checked = t > 0 && n === t; }

async function scanFolder(){
  const path = $('#fdPath').value.trim(); if (!path) return toast('フォルダのパスを入力してください');
  const r = await api('/api/scan-folder', { body: { path, recursive: $('#fdRec').checked } });
  FD = { files: r.files, dir: r.dir, truncated: r.truncated }; renderFolder();
}

async function startFolder(){
  if (!FD.files.length) await scanFolder();
  const paths = [...document.querySelectorAll('#fdList input:checked')].map(x => FD.files[Number(x.dataset.i)].path);
  if (!paths.length) return toast('文字起こしする動画を選んでください');
  const r = await api('/api/transcribe-batch', { body: { paths, skipDone: $('#fdSkip').checked, ...jobOpts() } });
  const sk = r.skipped.length;
  toast(`${r.added.length}本を待機列に追加しました` + (sk ? `(${sk}本は追加していません: ${r.skipped.slice(0, 2).map(x => x.reason).join(' / ')}${sk > 2 ? ' ほか' : ''})` : ''), 6000);
  await scanFolder().catch(() => {});   // 追加した分に「待機中」を付け直す
}

/* ---------- 切り抜きスタジオ/マーカー連携 ---------- */

function parseMarker(d){
  const out = [];
  let vids = d && typeof d === 'object' ? d.videos : null;
  if (Array.isArray(vids)) vids = Object.fromEntries(vids.filter(v => v && typeof v === 'object').map((v, i) => [String(v.videoId || v.id || i), v]));
  if (!vids || typeof vids !== 'object') return out;
  for (const [vid, v] of Object.entries(vids).slice(0, 500)){
    if (!v || typeof v !== 'object' || v.demo) continue;
    const clips = [], raw = ['clips', 'marks', 'points'].map(k => v[k]).find(Array.isArray) || [];
    for (const c of raw.slice(0, 500)){
      if (!c || typeof c !== 'object') continue;
      const a = Number(c && c.start), b = Number(c && c.end);
      if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) continue;
      clips.push({ start: a, end: b, title: String(c.title || c.label || '').slice(0, 120), src: String(c.src || '').slice(0, 8), score: Number.isFinite(Number(c.score)) && c.score !== null && c.score !== '' ? Number(c.score) : null, status: String(c.status || ''), file: String(c.file || '').slice(0, 500), rating: Math.round(Number(c.rating) || 0) });
    }
    if (clips.length) out.push({ videoId: String(vid).slice(0, 20), title: String(v.title || '').slice(0, 120), local: v.local === true,
      fileName: String(v.fileName || '').slice(0, 200), sourcePath: String(v.sourcePath || '').slice(0, 500), clips });
  }
  return out;
}

function renderMarker(){
  const vs = S.marker.videos, sel = $('#mVideo');
  $('#mStatus').textContent = S.marker.found ? `${(S.marker.sources || []).map(x => (x.kind === 'studio' ? '切り抜きスタジオ' : x.kind === 'file' ? '選んだ data.json' : '切り抜きマーカー') + x.videos + '本').join(' / ') || '切り抜きマーカー'}のデータを読み込みました(${vs.length}本の動画)` : '隣の clip-studio(または clip-marker)フォルダに data.json が見つかりません。下のボタンで data.json を選んでください。';
  const cur = sel.value;
  const FROM = { studio: 'スタジオ', marker: '旧マーカー', file: '選んだ data.json' };
  sel.innerHTML = vs.map((v, i) => `<option value="${i}">[${FROM[v.from || (S.marker.sources || [])[0]?.kind] || '?'}] ${esc((v.title || v.videoId) + (v.local ? '(ローカル)' : ''))} — ${v.clips.length}件</option>`).join('');
  $('#mSources').innerHTML = (S.marker.sources || []).map(x => `<div class="src"><span class="pill ok">${FROM[x.kind] || esc(x.kind)}</span><span>${Number(x.videos) || 0}本</span><span class="mono">${esc(x.path)}</span></div>`).join('')
    + (S.marker.outDir ? `<div class="src"><span class="pill">書き出し先</span><span class="mono">${esc(S.marker.outDir)}</span></div>` : '');
  if (cur && vs[Number(cur)]) sel.value = cur;
  renderMarkerClips();
}

function renderMarkerClips(){
  const v = S.marker.videos[Number($('#mVideo').value)], box = $('#mClips');
  if (!v){ box.innerHTML = '<p class="hint" style="padding:8px;margin:0">ポイントのある動画がありません</p>'; $('#mCount').textContent = ''; return; }
  if (document.activeElement !== $('#mPath')) $('#mPath').value = v.sourcePath || '';
  $('#mFileHint').textContent = v.sourcePath ? '' : v.clips.some(c => c.fileAbs) ? '元の動画のパスが空でも、書き出し済みの切り抜きは、そのまま文字起こしできます(パスを入れると、元の動画のその区間を文字起こしします)' : (v.fileName ? `切り抜きマーカーで開いたファイル名: ${v.fileName}(パスは入力が必要です)` : 'YouTube の動画は、手元にファイルがある場合だけ使えます');
  const only = $('#mFilter').value === 'adopted', skip = $('#mSkip').checked;
  const rows = v.clips.map((c, i) => ({ c, i })).filter(x => !only || x.c.status === 'adopted' || x.c.status === 'exported');
  box.innerHTML = rows.length ? rows.map(({ c, i }) => `<label><input type="checkbox" data-i="${i}" ${skip && c.doneTid ? '' : 'checked'}>
    <span class="mono">${fmtT(c.start)}–${fmtT(c.end)}</span><span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.title || '無題')}</span>
    ${c.src ? `<span class="pill" title="${c.src === 'auto' ? '自動で見つけた区間' : '自分でマークした区間'}${c.score != null ? '(点数 ' + esc(c.score) + ')' : ''}">${c.src === 'auto' ? '自動' + (c.score != null ? ' ' + esc(c.score) : '') : c.src === 'manual' ? '手動' : esc(c.src)}</span>` : ''}${c.fileAbs ? '<span class="pill ok" title="書き出し済みの切り抜き(mp4)が見つかりました">mp4あり</span>' : ''}${c.doneTid ? '<span class="pill" title="この範囲は、すでに文字起こし済みです">文字起こし済み</span>' : ''}
    <span class="pill">${esc({ '': '候補', candidate: '候補', adopted: '採用', rejected: '不採用', exported: '書き出し済み' }[c.status] ?? c.status)}</span></label>`).join('')
    : '<p class="hint" style="padding:8px;margin:0">条件に合うポイントがありません(「対象」を「すべて」にしてみてください)</p>';
  $('#mAll').checked = true; updateMCount();
}

function updateMCount(){ const n = document.querySelectorAll('#mClips input:checked').length, t = document.querySelectorAll('#mClips input').length; $('#mCount').textContent = t ? `${n} / ${t} 件を選択` : ''; }

async function loadMarker(){
  try { S.marker = await api('/api/marker'); } catch { S.marker = { found: false, videos: [] }; }
  renderMarker(); fdSyncStudio();
}

/* ---------- ジョブの進捗 ---------- */

function startPolling(){ if (!S.pollT) S.pollT = setInterval(pollJobs, 1000); }

async function pollJobs(){
  let j; try { j = await api('/api/jobs'); } catch { return; }
  S.jobs = j.jobs.slice().reverse();
  let doneNew = false, diar = null, abDone = null, txDone = [], failed = null, voiceDone = null, normDone = [], altDone = [];
  for (const x of S.jobs){
    if (S.seen.has(x.id)) continue;
    if (x.state === 'done'){ S.seen.add(x.id); doneNew = true; if (LOCK_KINDS.includes(x.kind)) diar = x; else if (x.kind === 'abtest') abDone = x; else if (x.kind === 'voice-learn') voiceDone = x; else if (x.kind === 'normalize') normDone.push(x); else if (x.kind === 'alt') altDone.push(x); else if (x.tid) txDone.push(x); }
    else if (x.state === 'error'){ S.seen.add(x.id); failed = x; }   // 失敗も一度だけ知らせる(メニューを閉じていると気づけないため)
  }
  renderJobs(); applyLock();
  // 開いている評価用の文書の作り直し(1 本ずつ・まとめての)が終わった: 読み直す(下の「文字起こしが終わりました」には数えない)
  const redone = S.doc ? txDone.find(x => x.redo && x.tid === S.docId) : null;
  if (redone) txDone = txDone.filter(x => x !== redone);
  for (const x of txDone) if (x.vadNote) toast(`「${x.title || '無題'}」: ${x.vadNote}`, 9000);   // 声の検出を緩めてやり直した(4-2)。今回終わった文字起こしだけ
  for (const x of txDone.concat(normDone)) if (x.normNote) toast(`「${x.title || '無題'}」: ${x.normNote}`, 9000, x.normOk ? 'ok' : undefined);   // 30fps にそろえた・そろえられなかった(Q1)
  if (failed) toast(`「${failed.title || '無題'}」の処理に失敗しました: ${failed.error || ''}`, 8000, 'err');
  if (abDone){ loadEvals(); toast('設定の比較が終わりました。左の「認識精度の測定」に結果が出ます'); }
  if (altDone.some(x => x.tid === S.docId)){ await loadSuggest(); toast(`別のエンジンで聞き終えました。食い違う所に候補を ${S.sug.filter(x => x.tier === 'alt').length} 件出しました(行の「別」)`, 6000, 'ok'); }   // D1-b: 文書は書き換えないので、候補だけ読み直す
  if (voiceDone){ toast(`声を覚えました: ${(voiceDone.learned || []).join('・')}。次からの話者判別で、この声の話者に名前を付けます`, 6000, 'ok'); loadVoices(); }
  if (doneNew){
    await loadList();
    if (redone && S.docId === redone.tid){
      if (redone.redoSkipped) toast(redone.phase || '作り直しませんでした', 8000);
      else if (await openDoc(redone.tid, true)) toast(`この動画を今の設定で作り直しました(${S.doc.segments.length}行。前の版は「以前の版に戻す」に残っています。話者は、自動の判別が使えるときは続けて付けます)`, 7000, 'ok');
    }
    if (S.doc && normDone.some(x => x.tid === S.docId && x.normOk)) await openDoc(S.docId, true);   // 開いている文書の動画を 30fps の写しに付け替えた → 読み直す(更新日時は変わらないので保存は競合しない)
    if (diar){
      if (diar.kind === 'diarize'){ try { S.tools = await api('/api/tools'); renderDiarSetup(); } catch {} }
      loadLearned();
      if (diar.tid === S.docId) await openDoc(diar.tid, true);
      toast(diar.kind === 'redo' ? `疑わしい所を認識し直しました: ${diar.phase || ''}` + (diar.segments ? '(前の版は「以前の版に戻す」に残っています)' : '')
        : diar.kind === 'retranscribe' ? `${diar.segments}行を再認識しました。` + (diar.kept || diar.emptyKept ? [diar.kept ? `校正済み ${diar.kept} 行` : '', diar.emptyKept ? `文字が出なかった ${diar.emptyKept} 行` : ''].filter(Boolean).join('と') + 'は元のままです。' : '')
          + (diar.loose ? `声が重なる所などを緩い条件で ${diar.loose} 行拾いました(要確認)。` : '') + (diar.unsure ? `まだ不確かな行が${diar.unsure}行あります。` : '') + (diar.vadNote ? diar.vadNote : '')
        : diar.autoSkipped ? `話者の自動判別: ${diar.phase || '判別しませんでした'}`
        : `${diar.auto ? '話者を自動で判別しました' : '話者を判別しました'}(${diar.speakers}人)。` + (namedBy(diar, false).length ? `覚えている声で名前を付けました: ${namedBy(diar, false).map(x => x.name).join('・')}。` : '')
          + (namedBy(diar, true).length ? `動画の場所・配信から名前を付けました: ${namedBy(diar, true).map(x => x.name).join('・')}(違っていたら直してください)。` : '')
          + (diar.unsure ? `不確かな行が${diar.unsure}行あります(「要確認」で絞り込めます)` : ''),
        diar.kind === 'diarize' && diar.tid === S.docId && (diar.named || []).length < diar.speakers ? { ms: 10000, action: { label: '名前を付ける', fn: focusSpeakerNames } } : undefined);
    } else if (S.doc && txDone.some(x => x.tid === S.docId) && !S.doc.segments.length){   // 開いている文字起こしの無い文書に、文字起こしが入った
      if (await openDoc(S.docId, true)) toast(`文字起こしが終わりました(${S.doc.segments.length}行)`, 5000, 'ok');
    } else if (!S.doc){ const last = S.jobs.find(x => x.state === 'done' && x.tid); if (last) openDoc(last.tid); }
    else if (txDone.length) toast(txDone.length > 1 ? `${txDone.length}本の文字起こしが終わりました(メニューの「履歴」から開けます)` : `「${txDone[0].title || '無題'}」の文字起こしが終わりました(メニューの「処理状況」の「開く」で開けます)`, 6000, 'ok');
  }
  if (!S.jobs.some(x => ACTIVE.has(x.state))){ clearInterval(S.pollT); S.pollT = null; }
}

/* 話者判別のジョブの named を、覚えた声(と消去法)と動画の手がかり(by: context。評価用の自動の判別。v0.50.0)に分ける */
function namedBy(j, ctx){ return (j.named || []).filter(x => (x.by === 'context') === ctx); }

function renderJobBadge(){
  const act = S.jobs.filter(j => ACTIVE.has(j.state)), b = $('#jobBadge');
  b.hidden = !act.length; if (act.length){ const j = act[0]; b.textContent = `処理中 ${act.length}件 ${j.state === 'running' ? pctOf(j) + '%' : STATE_LABEL[j.state] || ''}`; }
}

/* 文字起こしの無い文書の「この動画を文字起こしする」: この文書に入れる文字起こし(intoDoc)が動いている間は押せない */
function renderIntoState(){
  if (!S.doc) return;
  const j = S.jobs.find(x => x.kind === 'transcribe' && x.into === S.docId && ACTIVE.has(x.state));
  $('#btnTxInto').disabled = !!j || !S.doc.sourcePath;
  $('#txIntoHint').textContent = j ? `文字起こし中 ${j.state === 'running' ? pctOf(j) + '%' : STATE_LABEL[j.state] || ''}(終わると、ここに行が出ます)`
    : S.doc.sourcePath ? '認識の設定は、メニューの「新規」のものを使います' : 'この文書には動画のパスが無いため、文字起こしできません';
}

function renderJobs(){
  renderJobBadge(); renderIntoState(); renderAlt();
  const box = $('#jobs');
  if (!S.jobs.length){ box.innerHTML = '<p class="hint" style="margin:6px 0 0">ジョブはありません</p>'; return; }
  box.innerHTML = S.jobs.slice(0, 10).map(j => `<div class="job" data-id="${esc(j.id)}">
    <div class="row" style="justify-content:space-between;flex-wrap:nowrap"><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500">${esc(j.title)}</span>
      <span class="pill ${j.state === 'done' ? 'ok' : j.state === 'error' ? 'err' : ACTIVE.has(j.state) ? (j.state === 'queued' ? 'wait' : 'run') : ''}">${esc(STATE_LABEL[j.state] || j.state)}</span></div>
    ${j.hasClip ? '<div class="hint" style="margin-top:2px">元の配信の情報(.clip.json)つき</div>' : ''}
    ${ACTIVE.has(j.state) ? `<div class="bar${j.state === 'running' ? '' : ' indeterminate'}"><i style="width:${pctOf(j)}%"></i></div><div class="row" style="justify-content:space-between;margin-top:3px"><span class="hint">${esc(j.phase || '')}${j.state === 'running' ? ' ' + pctOf(j) + '%' : ''}${j.device ? '(' + devLabel(j.device) + ')' : ''}</span><button type="button" class="btn small" data-act="cancel">中止</button></div>` : ''}
    ${j.error ? `<div class="hint" style="color:var(--danger);margin-top:3px">${esc(j.error)}</div>` : ''}
    ${(Array.isArray(j.warnings) ? j.warnings : []).slice(0, 3).map(w => `<div class="notice tt-jwarn">${esc(w)}</div>`).join('')}
    ${j.state === 'done' && j.kind === 'abtest' ? `<div class="row" style="margin-top:3px"><span class="hint">${j.segments}行で比較</span><button type="button" class="btn small" data-act="evalview">結果を見る</button></div>` : ''}
    ${j.state === 'done' && j.tid ? `<div class="row" style="margin-top:3px"><span class="hint">${j.kind === 'voice-learn' ? (j.learned || []).length + '人の声を覚えた' : j.kind === 'diarize' ? j.speakers + '人を判別' + ((j.named || []).length ? '(' + j.named.length + '人に名前)' : '') : j.kind === 'retranscribe' ? j.segments + '行を更新' : j.kind === 'redo' ? j.segments + 'か所を置き換え' : j.kind === 'normalize' ? (j.normOk ? '30fps にそろえました' : '元の動画のまま') : j.kind === 'alt' ? '別のエンジンで ' + j.segments + '行' : j.segments + '行'}</span><button type="button" class="btn small" data-act="open" data-tid="${esc(j.tid)}">開く</button></div>` : ''}
  </div>`).join('');
}

/* ---------- 話者の自動判別 ---------- */

function renderDiarSetup(){
  const t = S.tools, box = $('#diarSetup'), d = t && t.diarize;
  if (!d){ box.innerHTML = ''; return; }
  const sel = $('#diarEmb'), cur = sel.value || S.settings.diarEmb || d.default;
  sel.innerHTML = d.embeddings.map(e => `<option value="${esc(e.key)}">${esc(e.label)}${e.ready ? '' : `(初回に約${e.mb}MBをダウンロード)`}</option>`).join('');
  sel.value = d.embeddings.some(e => e.key === cur) ? cur : d.default;
  const e = d.embeddings.find(x => x.key === sel.value);
  box.innerHTML = !d.ready ? '<div class="notice">話者の自動判別には、追加の部品(sherpa-onnx)が必要です。フォルダ内の <code>install-diarize.bat</code>(Mac は <code>install-diarize.command</code>)を実行して、ツールを起動し直してください。</div>'
    : (!(d.segReady && e && e.ready) ? `<p class="hint" style="margin:0">初回だけ、判別用のモデルを自動でダウンロードします(合計 約${(d.segReady ? 0 : 6) + (e ? e.mb : 0)}MB)。</p>` : '');
  $('#diarGo').disabled = !d.ready;
}

/* 編集を止めるジョブ: 話者判別・再認識・疑わしい所の認識し直しと、この動画の作り直し(1 本ずつ。文字起こしのジョブで tid は終わるまで空 = into で見る) */
function lockJob(){ return S.doc ? S.jobs.find(j => ACTIVE.has(j.state) && ((LOCK_KINDS.includes(j.kind) && j.tid === S.docId) || (j.redoOne && j.into === S.docId))) : null; }

function applyLock(){
  const j = lockJob(), on = !!j;
  $('#segs').inert = on; document.querySelectorAll('#doc .tt-lockable').forEach(el => { el.inert = on; }); $('#docTitle').disabled = on;
  if (S.doc) renderCutPack();
  renderRedoOne(); renderOvd();
  const b = $('#diarBanner'); b.hidden = !on;
  if (on) b.textContent = `${j.redoOne ? 'この動画を今の設定で作り直' : LOCK_LABEL[j.kind] || '処理'}しています(${j.phase}${j.state === 'running' ? ' ' + Math.round(j.progress * 100) + '%' : ''})。終わると自動で読み込み直します。それまで編集はできません(中止は左の「処理状況」から)。`;
}

async function startDiarize(){
  if (!S.doc) return;
  await saveDoc();
  if (S.dirty || S.saving) return toast('保存中です。少し待ってから、もう一度押してください');
  await api('/api/diarize', { body: { tid: S.docId, numSpeakers: Number($('#diarNum').value) || 0, embedding: $('#diarEmb').value, recognize: $('#diarRecog').checked } });
  startPolling(); await pollJobs(); toast('話者の判別を待機列に追加しました');
}

/* ---------- 重なりの所に空の行を置く(2026-10-05。docs/plan/other-voice-and-overlap-plan.md の 5-3 の C・6-2 の 1・2) ----------
   同時にしゃべっている所は、認識が片方しか書かない。話者判別の記録(diar.json)で声があったのに行の無い所を GET api/overlap-drafts で数え、
   押したら時刻(と分かれば話者)を入れた空の行(印 draft・音のメモ「声が重なる」)を画面で足す。サーバーに行を作る API は無い
   (元に戻す 1 回で全部消える・保存はいつもの道)。自動では置かない。確かめ済みの評価用の文書には置かない(空の行が残ると「全部聞いた」と合わない)。
   状態は app.js の OVD。行の見た目・印の外し方は app-rows.js の isBlankDraft・clearDraftMark */

/* 置けるか -> [押せるか, 理由(数の下に出す文・ボタンの title)] */
function ovdState(){
  const d = S.doc;
  if (!d || !S.docId) return [false, ''];
  if (d.evalReviewed) return [false, '確かめ済みの動画には置けません(空の行が残ると「全部聞いて確かめた」と合わなくなるため)。置くときは、先に確かめ済みを取り消してください'];
  if (lockJob()) return [false, '処理中です(終わってから押してください)'];
  if (OVD.busy) return [false, '置いています…'];
  if (OVD.id !== S.docId) return [false, OVD.err || '数えています…'];
  if (OVD.reason) return [false, OVD.reason];
  if (!OVD.items.length) return [false, '声があるのに行の無い所はありません(書いてある所・置いた空の行は数えません)'];
  return [true, ''];
}

function renderOvd(){
  const box = $('#ovdBox'); if (!box) return;
  const [ok, why] = ovdState(), n = OVD.id === S.docId ? OVD.items.length : 0;
  const un = OVD.items.filter(x => x.why === 'unassigned').length;
  $('#ovdCount').textContent = ok
    ? `声があるのに行の無い所: ${n} か所(話者の分かる所 ${n - un}・誰の声か分からない所 ${un})${OVD.more ? `。ほかに ${OVD.more} か所あります(置いたあとで、もう一度押すと続きを置けます)` : ''}`
    : why;
  $('#ovdCount').classList.toggle('tt-ovd-none', !ok);
  const go = $('#ovdGo'); go.disabled = !ok; go.title = ok ? `${n} か所に、時刻(分かれば話者も)を入れた空の行を置きます。聞いて文字を打ってください` : why;
  const k = blankDrafts().length, cl = $('#ovdClear');
  cl.hidden = !k; cl.textContent = `空のままの下書きを消す(${k} 行)`; cl.disabled = !!lockJob() || OVD.busy;
}

/* 候補を数える(読むだけ)。id = 開いている文書。待っている間に別の文書を開いたら捨てる */
async function loadOvd(id = S.docId){
  if (!id) return;
  const seq = ++OVD.seq;
  if (OVD.id !== id) OVD.err = '';   // 前の文書で数えられなかった知らせを、この文書に出さない
  let r;
  try { r = await api('/api/overlap-drafts?id=' + encodeURIComponent(id)); }
  catch (e){ if (seq === OVD.seq && S.docId === id){ OVD.err = '数えられませんでした: ' + e.message; renderOvd(); } return null; }
  if (seq !== OVD.seq || S.docId !== id) return null;
  Object.assign(OVD, { id, items: Array.isArray(r.items) ? r.items : [], more: Number(r.more) || 0, reason: r.reason || '', diarAt: r.diarAt || null, err: '', drafts: blankDrafts().length });
  renderOvd();
  return r;
}

/* 押した: 保存し終えてから数え直す → 確かめる → 行を足す(1 回の元に戻す) */
async function ovdPlace(){
  const id = S.docId;
  if (!ovdState()[0]) return;
  OVD.busy = true; renderOvd();
  try {
    if (!(await saveDoc()) || S.dirty || S.saving || S.conflict || S.docId !== id){
      if (S.docId === id) toast('保存が終わっていないため、置いていません(保存の状態を確かめてから、もう一度押してください)', 6000, 'err');
      return;
    }
    const r = await loadOvd(id);   // 保存済みの文書で数え直す(今の行で数える = 2 回押しても増えない)
    if (!r || S.docId !== id) return;
    const items = OVD.items.slice(), n = items.length;
    if (!n) return toast(OVD.reason || '声があるのに行の無い所はありません', 5000);
    if (!(await UIKit.dialog.confirm({ title: '空の行を置きますか', ok: '空の行を置く',
      body: `${n} か所に空の行を置きます。文字はありません。聞いて打ってください(打つと札「下書き(重なり)」が外れます。置いた行は、元に戻す 1 回でまとめて消せます)` }))) return;
    if (S.docId !== id || lockJob() || S.doc.evalReviewed) return;
    const navId = navSnapshot();
    pushUndo();
    const added = items.map(x => ({ id: uid(), start: r2(x.start), end: r2(x.end), text: '', speaker: x.speaker && spById(x.speaker) ? x.speaker : '', flag: '', tags: ['overlap'], draft: OVD_KIND }));
    S.doc.segments.push(...added);
    sortSegs(); navRestore(navId, S.navIdx); renderDoc(); markDirty();
    const goFirst = () => {   // 知らせの「最初の行へ」: 絞り込みで隠れていれば解いてから
      const i = S.doc && S.docId === id ? S.doc.segments.findIndex(g => g.id === added[0].id) : -1; if (i < 0) return;
      if (rowsEl()[i] && rowsEl()[i].hidden){ $('#q').value = ''; $('#flagKind').value = ''; applyFilter(); }
      gotoRow(i, { center: true });
    };
    toast(`${n} か所に空の行を置きました(札「下書き(重なり)」。絞り込みの「重なりの下書きだけ」で、その行だけを出せます)`, { ms: 8000, kind: 'ok', action: { label: '最初の行へ', fn: goFirst } });
    if (await saveDoc() && S.docId === id) await loadOvd(id);
  } finally { OVD.busy = false; renderOvd(); }
}

/* 保存のあと: 空のままの下書きの数が変わった(置いた・消した・元に戻した・行を消した)なら数え直す(候補は保存済みの文書で数えるため) */
function ovdAfterSave(){
  if (!S.doc || OVD.id !== S.docId) return;
  const k = blankDrafts().length;
  if (k !== OVD.drafts) loadOvd(S.docId);
}

/* 空のままの下書きを消す(1 回の元に戻す。文字を打った行・印の無い空の行は消さない) */
async function ovdClear(){
  const id = S.docId, k = blankDrafts().length;
  if (!k || lockJob()) return;
  removeBlankDrafts();
  toast(`空のままの下書きを ${k} 行消しました(元に戻すで戻せます)`, 4000, 'ok');
  if (await saveDoc() && S.docId === id) loadOvd(id);
}

/* 空のままの下書きを消す本体(「済みにして次へ」の前にも使う)。-> 消した行の数 */
function removeBlankDrafts(){
  const k = blankDrafts().length; if (!k) return 0;
  const navId = navSnapshot();
  pushUndo();
  for (const g of S.doc.segments) if (isBlankDraft(g)) S.sel.delete(g.id);
  S.doc.segments = S.doc.segments.filter(g => !isBlankDraft(g));
  navRestore(navId, S.navIdx); renderDoc(); markDirty();
  return k;
}

/* ---------- 全行をこの人に(評価用。マスタープラン Q4。docs/plan/q3-q4-design.md の (c)) ----------
   評価用の文書で話者の無い行があるとき(評価用のフォルダへ移すには全行に話者が要る)、候補(GET api/drill/candidates =
   この文書の覚えた声 → メンバーのフォルダ → 配信の文脈 → ほかの覚えた声・メンバー)から1人選び、既存の 1人指定
   (POST api/diarize の numSpeakers 1 + names。サーバーの single_speaker が全行をその人にして diar.json も書く)で付ける。状態は app.js の SPALL */

function spAllNeeded(){
  const d = S.doc; if (!d || d.evalSet !== true) return false;
  const ids = new Set((d.speakers || []).map(s => s.id));
  return d.segments.some(s => String(s.text || '').trim() && !ids.has(s.speaker));
}

function renderSpAll(){
  const box = $('#spAllBox'); if (!box) return;
  if (typeof renderDrillSpk === 'function') renderDrillSpk();   // ドリルの帯の「話者の無い行 n 行」も合わせる
  const on = spAllNeeded(); box.hidden = !on;
  if (!on) return;
  if (SPALL.id !== S.docId){ SPALL.id = S.docId; SPALL.cands = []; SPALL.suggest = ''; fillSpAll(); loadSpAll(S.docId); }
  const ids = new Set(S.doc.speakers.map(s => s.id)), none = S.doc.segments.filter(s => String(s.text || '').trim() && !ids.has(s.speaker)).length;
  $('#spAllHint').textContent = `話者の無い行が ${none} 行あります(評価用のフォルダへ移すには、全行に話者が要ります)。1人で話している動画なら、候補から選んで全行に付けられます(今付いている話者も置き換わります)。`;
  $('#spAllGo').disabled = !!lockJob();
}

async function loadSpAll(id){
  let r; try { r = await api('/api/drill/candidates?id=' + encodeURIComponent(id)); } catch { return; }
  if (SPALL.id !== id) return;   // 待っている間に別の文書を開いた
  SPALL.cands = r.candidates || []; SPALL.suggest = r.suggest || '';
  fillSpAll();
}

function fillSpAll(){
  const sel = $('#spAllName'), keep = sel.value;
  sel.textContent = '';   // 名前は外から来る文字なので Option(textContent)で入れる
  if (!SPALL.suggest) sel.append(new Option('(選んでください)', ''));
  for (const c of SPALL.cands) sel.append(new Option(`${c.name}(${SPALL_FROM[c.from] || c.from}${c.near ? '' : '・ほかの文書'})`, c.name));
  sel.append(new Option('ほかの名前を入れる…', 'other'));
  sel.value = [...sel.options].some(o => o.value === keep && keep) ? keep : SPALL.suggest;
  syncSpAllNew();
}

function syncSpAllNew(){ const on = $('#spAllName').value === 'other'; $('#spAllNew').hidden = !on; if (!on) $('#spAllNew').value = ''; }

async function spAllGo(){
  if (!S.doc || lockJob()) return;
  const v = $('#spAllName').value, name = (v === 'other' ? $('#spAllNew').value : v).trim();
  if (!name){ toast('全行に付ける話者を選んでください'); return v === 'other' ? $('#spAllNew').focus() : $('#spAllName').focus(); }
  if (DEFAULT_SPK.test(name)) return toast('「話者1」のような仮の名前ではなく、配信者の名前を選んでください');
  const n = S.doc.segments.length, ids = new Set(S.doc.speakers.map(s => s.id)), had = S.doc.segments.filter(s => ids.has(s.speaker)).length;
  const ok = await UIKit.dialog.confirm({ title: `全行の話者を「${name}」にしますか`, ok: '全行をこの人に',
    body: `この文字起こしの ${n} 行すべての話者を「${name}」1人にします。${had ? `今 話者が付いている ${had} 行も置き換わります。` : ''}1人で話している動画のときだけ使ってください(元に戻すときは「以前の版に戻す」から)。` });
  if (!ok) return;
  await saveDoc();
  if (S.dirty || S.saving) return toast('保存中です。少し待ってから、もう一度押してください');
  await api('/api/diarize', { body: { tid: S.docId, numSpeakers: 1, names: [name], recognize: false } });
  startPolling(); await pollJobs(); toast(`全行の話者を「${name}」にしています`);
}

/* ---------- 声を覚える(A-3)。覚えるのはジョブ(/api/voices/learn)、照らし合わせは話者判別のジョブの中(recognize)。
   声の特徴そのものは画面に来ない(一覧は名前・行の数・秒だけ) ---------- */

function namedSpeakers(){ return S.doc ? (S.doc.speakers || []).filter(s => s.name && !DEFAULT_SPK.test(s.name)) : []; }

function renderVoiceLearn(){
  const b = $('#voiceLearn'), n = namedSpeakers(), d = S.tools && S.tools.diarize, ev = !!(S.doc && S.doc.evalSet);
  b.disabled = !S.doc || ev || !n.length || !(d && d.ready) || !!lockJob();   // 評価用は押せなくし、理由をヒントに出す(隠さない。監査02)
  $('#voiceLearnHint').textContent = ev ? EVAL_VOICE_MSG : !(d && d.ready) ? '話者判別の部品(sherpa-onnx)が要ります' : !n.length ? '先に下の一覧で話者に名前を付けてください'
    : n.map(s => s.name).slice(0, 6).join('・') + ' の声を覚えます(校正済みの行だけを使います。押すと、覚える前に確かめます)';
}

function voicePreviewText(r){
  const out = [];
  if (r.people.length) out.push('覚える声:', ...r.people.map(p => `・${p.name} ${p.rows}行・${voiceSec(p.sec)}` + (p.exists ? '(もう覚えている名前です。次に確かめます)' : '')));
  const why = { generic: '一般的な名前です。配信者の名前に変えてください', no_rows: '使える校正済みの行がありません' };
  if (r.refused.length) out.push('覚えない:', ...r.refused.map(x => `・${x.name}(${why[x.reason] || x.reason})`));
  const sk = VOICE_SKIP.filter(([k]) => r.skipped && r.skipped[k]).map(([k, t]) => `${t} ${r.skipped[k]}`);
  if (sk.length) out.push('使わなかった行: ' + sk.join('・'));
  out.push('(校正済みで、音のメモが無い1秒以上の行だけを使います)');
  return out.join('\n');
}

async function loadVoices(){
  let r; try { r = await api('/api/voices'); } catch { return; }
  const emb = $('#diarEmb').value, all = r.voices || {}, labels = {};
  ((S.tools && S.tools.diarize && S.tools.diarize.embeddings) || []).forEach(e => { labels[e.key] = e.label; });
  const n = Object.values(all).reduce((a, x) => a + x.length, 0);
  spVoiceNames = [...new Set(Object.values(all).flatMap(xs => xs.map(x => String(x.name || ''))).filter(Boolean))]; renderSpNames();   // 話者の名前の欄の候補にも
  $('#voiceCount').textContent = n ? `${n}人` : 'まだありません';
  $('#voiceList').innerHTML = !n ? '<p class="hint" style="margin:6px 0 0">まだ覚えている声はありません</p>'
    : Object.entries(all).map(([k, xs]) => `<div class="hint" style="margin-top:6px">${esc(labels[k] || k)}${k === emb ? '(今の判別モデル)' : ''}</div>` + xs.map(x =>
      `<div class="row" data-emb="${esc(k)}" data-name="${esc(x.name)}" style="margin-top:4px;justify-content:space-between;flex-wrap:nowrap"><span>${esc(x.name)} <span class="hint">${x.rows}行 ・ ${Math.round(x.sec / 6) / 10}分 ・ ${esc(ago(x.updatedAt))}</span>${x.generic ? ' <span class="pill warn" data-generic>一般的な名前です(忘れることをおすすめします)</span>' : ''}</span><button type="button" class="btn small" data-act="vdel">忘れる</button></div>`).join('')).join('');
}

/* ---------- 再認識 ---------- */

function flagParts(s){ const p = String(s.flag || '').split('、').filter(Boolean); return { spk: p.filter(x => SPK_FLAGS.includes(x)), text: p.filter(x => !SPK_FLAGS.includes(x)) }; }

function flagMatch(s, kind){ if (kind === 'draft') return isBlankDraft(s); if (kind === 'proofed') return !!s.proofed; if (kind === 'unproofed') return !s.proofed; if (kind === 'cut') return s.cutState === 'cut'; if (kind === 'sug') return sugList(s).length > 0; const f = flagParts(s); return kind === 'any' ? !!s.flag : kind === 'text' ? f.text.length > 0 : f.spk.length > 0; }

function renderRtSetup(){
  const t = S.tools, sel = $('#rtModel'); if (!t) return;
  sel.innerHTML = t.models.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  const want = S.settings.rtModel && t.models.some(m => m[0] === S.settings.rtModel) ? S.settings.rtModel : (t.models.some(m => m[0] === 'large-v3') ? 'large-v3' : t.models[0][0]);
  sel.value = want;
  if (['text', 'sel', 'all', 'range', 'whole'].includes(S.settings.rtTarget)) $('#rtTarget').value = S.settings.rtTarget;
}

function rtRange(){   // 選んだ行の最初〜最後(間の行も含む)
  const segs = S.doc.segments.filter(s => S.sel.has(s.id)); if (!segs.length) return null;
  const a = Math.min(...segs.map(s => s.start)), b = Math.max(...segs.map(s => s.end));
  return { a, b, ids: S.doc.segments.filter(s => { const m = (s.start + s.end) / 2; return m >= a - 1e-6 && m <= b + 1e-6; }).map(s => s.id) };
}

function rtIds(){
  if (!S.doc) return [];
  const k = $('#rtTarget').value, segs = S.doc.segments;
  if (k === 'range'){ const r = rtRange(); return r ? r.ids.slice(0, 2000) : []; }
  if (k === 'whole') return segs.filter(s => !s.proofed).map(s => s.id);   // 数えるだけ(送らない。サーバーが校正済みでない行を選ぶ)
  return segs.filter(s => k === 'all' || (k === 'sel' ? S.sel.has(s.id) : flagMatch(s, 'text'))).map(s => s.id).slice(0, 2000);
}

function updateRt(){
  if (!S.doc){ $('#rtHint').textContent = ''; return; }
  const ids = new Set(rtIds()), sec = S.doc.segments.filter(s => ids.has(s.id)).reduce((a, s) => a + (s.end - s.start), 0);
  $('#rtHint').textContent = `対象: ${ids.size}行(音声 約${sec < 90 ? Math.round(sec) + '秒' : Math.round(sec / 60) + '分'})`;
  $('#rtGo').disabled = !ids.size;
  if ($('#rtTarget').value === 'whole'){ rtWholeHint(); return; }
  if ($('#rtTarget').value === 'range'){
    const r = rtRange();
    $('#rtHint').textContent = r ? `範囲: ${fmtT(r.a)}〜${fmtT(r.b)}(${r.ids.length}行を、新しい行に差し替えます。行の数は変わります。選んでいない間の行も入ります)` + (r.b - r.a > RANGE_MAX ? ' — 長すぎます(最大15分)' : '') : '行を選んでください(チェックボックス)';
    if (!r || r.b - r.a > RANGE_MAX) $('#rtGo').disabled = true;
  }
}

function docSpan(){
  const d = S.doc, p = player(), a = Number(d.start) || 0;
  const b = Number(d.end) || Number(d.duration) || (p && isFinite(p.duration) ? p.duration : 0) || Math.max(0, ...d.segments.map(s => s.end));
  return { a, b };
}

function rtWholeHint(){
  const { a, b } = docSpan(), kept = S.doc.segments.filter(s => s.proofed).length, rest = S.doc.segments.length - kept;
  const rtf = WHOLE_RTF[$('#rtModel').value], min = rtf ? Math.max(1, Math.round((b - a) * rtf / 60)) : 0;
  const tooLong = b - a > 6 * 3600;
  $('#rtHint').textContent = `動画全体 ${fmtT(a)}〜${fmtT(b)} を認識し直します。` + (kept ? `校正済みの ${kept} 行は残し、` : '') + `残り ${rest} 行を新しい行に差し替えます(行の数は変わります。文字が出なかった所は元の行を残します)。`
    + (min ? `目安 約${min}分(CPU・large-v3)。` : '') + (S.doc.evalSet ? ' — 評価用の文字起こしは再認識できません' : '') + (tooLong ? ' — 長すぎます(最大6時間)' : '');
  $('#rtGo').disabled = !(b > a) || tooLong || !!S.doc.evalSet;
}

async function startRetranscribe(){
  if (!S.doc) return;
  const whole = $('#rtTarget').value === 'whole';
  const ids = whole ? [] : rtIds(); if (!ids.length && !whole) return toast('再認識する行がありません');
  await saveDoc();
  if (S.dirty || S.saving) return toast('保存中です。少し待ってから、もう一度押してください');
  await api('/api/retranscribe', { body: { tid: S.docId, ids, mode: whole ? 'whole' : $('#rtTarget').value === 'range' ? 'range' : 'each', vadMode: $('#optVad').value, wordSplit: $('#optWordSplit').checked, ...subtitleReq(), stripPunct: $('#optStripPunct').checked, model: $('#rtModel').value, language: $('#optLang').value, device: $('#optDevice').value,
    boost: $('#optBoost').checked, glossary: $('#optGloss').value, autoDict: $('#optAutoDict').checked, autoGloss: $('#optAutoGloss').checked, autoContext: $('#optAutoContext').checked } });
  startPolling(); await pollJobs(); toast(whole ? '動画全体の再認識を待機列に追加しました(終わると読み込み直します)' : `${ids.length}行の再認識を待機列に追加しました`);
}
