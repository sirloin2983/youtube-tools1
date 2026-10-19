/* app-jobs.js — 「編集」の画面: 新規ジョブ・スタジオ/マーカー連携・ジョブの進捗・話者の自動判別・声を覚える・再認識。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は src/app/ui/cases/edhost.js の ED_SCRIPTS の1か所) */
'use strict';

/* ---------- 新規ジョブ ---------- */

function jobOpts(){
  return { model: $('#optModel').value, language: $('#optLang').value, quality: $('#optQuality').value, device: $('#optDevice').value, vadMode: vadModeOf(),
    ...checksOf(OPT_CHECKS), ...subtitleReq(), glossary: $('#optGloss').value, evalSet: $('#optEvalStart').checked };   // チェックの表は app-core.js の OPT_CHECKS
}

async function startFile(){
  const path = $('#srcPath').value.trim();
  if (!path) return toast('ファイルのパスを入力してください');
  const a = $('#rStart').value.trim(), b = $('#rEnd').value.trim();
  const body = { sourcePath: path, title: $('#jTitle').value.trim(), ...jobOpts() };
  if (a){ const v = parseT(a); if (!Number.isFinite(v)) return toast('開始の時刻が正しくありません(例: 1:23:45)'); body.start = v; }
  if (b){ const v = parseT(b); if (!Number.isFinite(v)) return toast('終了の時刻が正しくありません(例: 1:30:00)'); body.end = v; }
  if (!a && !b && !(await askTxAgain(path))) return;   // 動画全体の二度目は「前に作った文書があります」(範囲の指定は別の文書になるので聞かない)
  await api('/api/transcribe', { body });
  toast('待機列に追加しました');
}

/* 同じ動画の二度目の文字起こし(重い認識を 2 本走らせない): 行のある文書が前にあれば [開く](主・Enter)[作り直す]・Esc でやめる。
   -> 新しく文字起こしするか。UIKit.dialog.confirm は Esc も「キャンセル」と同じ false なので、Esc(dialog の cancel)だけは別に見て「やめる」にする */
async function askTxAgain(path){
  let r; try { r = await api('/api/doc-for?path=' + encodeURIComponent(path)); } catch { return true; }   // 調べられなければ今までどおり始める
  const hit = r && r.doc; if (!hit || !(hit.rows > 0)) return true;   // 行の無い文書(行 0)は聞かない
  const it = S.list.find(x => x.id === hit.id), when = it ? ago(Number(it.updatedAt) || 0) : '';
  const p = UIKit.dialog.confirm({ title: '前に作った文書があります', ok: '開く', cancel: '作り直す',
    body: `この動画は前に文字起こししています(「${(it && it.title) || '無題'}」・${hit.rows} 行${when ? '・' + when : ''})。「開く」でその文書の続きから直せます。` +
      '「作り直す」と、今の認識の設定で新しい文書をもう 1 つ作ります(前の文書は消えません)。Esc でやめます。' });
  const open = document.querySelectorAll('dialog.ui-dialog[open]'), dlg = open[open.length - 1];
  let escaped = false; if (dlg) dlg.addEventListener('cancel', () => { escaped = true; });
  if (await p){ await loadList(); if (await openDoc(hit.id)) toast('前に作った文書を開きました', 3000, 'ok'); return false; }
  return !escaped;
}

async function onStart(){
  readOpts();
  const btn = $('#btnStart'); btn.disabled = true;
  let ok = false;
  try { await startFile(); await kickJobs(); ok = true; }
  catch (e){ toast(e.message); }
  finally { btn.disabled = false; }
  if (ok){ const jb = $('#jobBadge'); if (!jb.hidden && jb.offsetParent) jb.focus(); }   // 始めたら処理中の札へ(押すと処理状況)
}

/* ---------- ジョブの進捗 ---------- */

function startPolling(){ if (!S.pollT) S.pollT = setInterval(pollJobs, 1000); }

async function pollJobs(){
  let j; try { j = await api('/api/jobs'); } catch { return; }
  S.jobs = j.jobs.slice().reverse();
  let doneNew = false, diar = null, txDone = [], failed = null, voiceDone = null, normDone = [], altDone = [];
  for (const x of S.jobs){
    if (S.seen.has(x.id)) continue;
    if (x.state === 'done'){ S.seen.add(x.id); doneNew = true; if (LOCK_KINDS.includes(x.kind)) diar = x; else if (x.kind === 'voice-learn') voiceDone = x; else if (x.kind === 'normalize') normDone.push(x); else if (x.kind === 'alt') altDone.push(x); else if (x.tid) txDone.push(x); }
    else if (x.state === 'error'){ S.seen.add(x.id); failed = x; }   // 失敗も一度だけ知らせる(メニューを閉じていると気づけないため)
  }
  renderJobs(); applyLock();
  // 開いている文書の作り直し(評価用の 1 本ずつ・まとめて・校正の全体の再認識)が終わった: 読み直す(下の「文字起こしが終わりました」には数えない)
  const redone = S.doc ? txDone.find(x => (x.redo || x.rerunWhole) && x.tid === S.docId) : null;
  if (redone) txDone = txDone.filter(x => x !== redone);
  for (const x of txDone) if (x.vadNote) toast(`「${x.title || '無題'}」: ${x.vadNote}`, 9000);   // 声の検出を緩めてやり直した。今回終わった文字起こしだけ
  for (const x of txDone.concat(normDone)) if (x.normNote) toast(`「${x.title || '無題'}」: ${x.normNote}`, 9000, x.normOk ? 'ok' : undefined);   // 30fps にそろえた・そろえられなかった
  if (failed) toast(jobFailText(failed), { ms: 15000, kind: 'err', detail: failed.errorDetail || undefined,
    action: failed.canRetry ? { label: 'やり直す', fn: () => retryJob(failed.id) } : undefined });   // 原文は「詳しく」の中だけ・[やり直す]
  if (altDone.some(x => x.tid === S.docId)){ await loadSuggest(); toast(`別のエンジンで聞き終えました。食い違う所に候補を ${S.sug.filter(x => x.tier === 'alt').length} 件出しました(行の「別」)`, 6000, 'ok'); }   // 文書は書き換えないので、候補だけ読み直す
  if (voiceDone){ toast(`声を覚えました: ${(voiceDone.learned || []).join('・')}。次からの話者判別で、この声の話者に名前を付けます`, 6000, 'ok'); loadVoices(); }
  if (doneNew){
    await loadList();
    if (redone && S.docId === redone.tid){
      if (redone.redoSkipped) toast(redone.phase || '作り直しませんでした', 8000);
      else if (redone.rerunWhole){ if (await openDoc(redone.tid, true)) toast(`動画全体を再認識しました(${S.doc.segments.length}行。直した行は元のまま` + (redone.kept ? `・機械が変わった ${redone.kept} 行には印` : '') + (redone.emptyKept ? `・文字が出なかった ${redone.emptyKept} 行は元のまま` : '') + '。前の版は「以前の版に戻す」に残っています)' + (redone.vadNote ? redone.vadNote : ''), 8000, 'ok'); }
      else if (await openDoc(redone.tid, true)) toast(`この動画を今の設定で作り直しました(${S.doc.segments.length}行。前の版は「以前の版に戻す」に残っています。話者は、自動の判別が使えるときは続けて付けます)`, 7000, 'ok');
    }
    if (S.doc && normDone.some(x => x.tid === S.docId && x.normOk)) await openDoc(S.docId, true);   // 開いている文書の動画を 30fps の写しに付け替えた → 読み直す(更新日時は変わらないので保存は競合しない)
    if (diar){
      if (diar.kind === 'diarize'){ try { S.tools = await api('/api/tools'); renderDiarSetup(); } catch {} }
      if (diar.tid === S.docId) await openDoc(diar.tid, true); else loadSuggest();
      toast(diar.kind === 'retranscribe' ? `${diar.segments}行を再認識しました。` + (diar.kept || diar.emptyKept ? [diar.kept ? `直した ${diar.kept} 行は元のまま(機械が変わった行には印)` : '', diar.emptyKept ? `文字が出なかった ${diar.emptyKept} 行は元のまま` : ''].filter(Boolean).join('。') + '。' : '')
          + (diar.loose ? `声が重なる所などを緩い条件で ${diar.loose} 行拾いました(要確認)。` : '') + (diar.unsure ? `まだ不確かな行が${diar.unsure}行あります。` : '') + (diar.vadNote ? diar.vadNote : '')
        : diar.autoSkipped ? `話者の自動判別: ${diar.phase || '判別しませんでした'}`
        : `${diar.auto ? '話者を自動で判別しました' : '話者を判別しました'}(${diar.speakers}人)。` + (namedBy(diar, false).length ? `覚えている声で名前を付けました: ${namedBy(diar, false).map(x => x.name).join('・')}。` : '')
          + (namedBy(diar, true).length ? `動画の場所・配信から名前を付けました: ${namedBy(diar, true).map(x => x.name).join('・')}(違っていたら直してください)。` : '')
          + (diar.unsure ? `不確かな行が${diar.unsure}行あります(「要確認」で絞り込めます)` : ''),
        diar.kind === 'diarize' && diar.tid === S.docId && (diar.named || []).length < diar.speakers ? { ms: 10000, action: { label: '名前を付ける', fn: focusSpeakerNames } } : undefined);
    } else if (S.doc && txDone.some(x => x.tid === S.docId) && !S.doc.segments.length){   // 開いている文字起こしの無い文書に、文字起こしが入った
      if (await openDoc(S.docId, true)) toast(`文字起こしが終わりました(${S.doc.segments.length}行)`, 5000, 'ok');
    } else if (!S.doc){ const last = S.jobs.find(x => x.state === 'done' && x.tid); if (last) openDoc(last.tid); }
    else if (txDone.length){   // 別の文書を開いている間に終わった: [開く](1 本)・[履歴を見る](2 本以上)。次の一手
      const one = txDone.length === 1 ? txDone[0] : null;
      toast(one ? `「${one.title || '無題'}」の文字起こしが終わりました` : `${txDone.length}本の文字起こしが終わりました`,
        { ms: 8000, kind: 'ok', action: one ? { label: '開く', fn: () => openDoc(one.tid) } : { label: '履歴を見る', fn: () => setSideTab('files') } });
    }
  }
  if (!S.jobs.some(x => ACTIVE.has(x.state))){ clearInterval(S.pollT); S.pollT = null; }
}

/* 話者判別のジョブの named を、覚えた声(と消去法)と動画の手がかり(by: context。評価用の自動の判別)に分ける */
function namedBy(j, ctx){ return (j.named || []).filter(x => (x.by === 'context') === ctx); }

function renderJobBadge(){
  const act = S.jobs.filter(j => ACTIVE.has(j.state)), b = $('#jobBadge');
  b.hidden = !act.length; if (act.length){ const j = act[0]; b.textContent = `処理中 ${act.length}件 ${jobProg(j)}`; }
}

/* 行の無い文書の「もう一度文字起こしする」(#btnTxAgain):
   この文書に入れる文字起こし(intoDoc)を始める。認識の設定はメニューの「新規」のもの */
async function transcribeInto(btn){
  if (!S.doc || !S.doc.sourcePath) return;
  readOpts();
  const id = S.docId; btn.disabled = true;
  try {
    await api('/api/transcribe', { body: { sourcePath: S.doc.sourcePath, intoDoc: id, ...jobOpts() } });
    toast('文字起こしを始めました(終わると、この画面に行が出ます)', 5000); await kickJobs();
  } catch (e){ toast(e.message, 6000, 'err'); }
  finally { renderIntoState(); }
}

/* 「もう一度文字起こしする」: この文書に入れる文字起こし(intoDoc)が動いている間は押せない */
function renderIntoState(){
  if (!S.doc) return;
  const j = S.jobs.find(x => x.kind === 'transcribe' && x.into === S.docId && ACTIVE.has(x.state));
  const again = $('#btnTxAgain'); if (again) again.disabled = !!j || !S.doc.sourcePath;
  const hint = $('#txIntoHint'); if (hint && j) hint.textContent = `文字起こし中 ${jobProg(j)}(終わると、ここに行が出ます)`;
  else if (hint && !S.doc.sourcePath) hint.textContent = 'この文書には動画のパスが無いため、文字起こしできません';
}

/* 失敗の文:想定外の失敗(errorDetail がある)は決まった文 + 次の一手。原文は知らせ・カードの「詳しく」の中だけ */
const JOB_KIND_NAME = { transcribe: '文字起こし', diarize: '話者の判別', retranscribe: '再認識', 'voice-learn': '声を覚える処理', alt: '別のエンジンでの聞き直し', normalize: '30fps にそろえる処理' };
/* 進み具合の文: 「n% か状態」(札・文字起こし中の 1 行)と「段階 + n%」(カード・別のエンジンの欄) */
const jobProg = j => j.state === 'running' ? pctOf(j) + '%' : STATE_LABEL[j.state] || '';
const jobPhase = j => (j.phase || '') + (j.state === 'running' ? ' ' + pctOf(j) + '%' : '');
/* 終わったジョブのカードの 1 行(種類ごと。表に無い種類は行の数) */
const JOB_DONE = { 'voice-learn': j => (j.learned || []).length + '人の声を覚えた', diarize: j => j.speakers + '人を判別' + ((j.named || []).length ? '(' + j.named.length + '人に名前)' : ''),
  retranscribe: j => j.segments + '行を更新', normalize: j => j.normOk ? '30fps にそろえました' : '元の動画のまま', alt: j => '別のエンジンで ' + j.segments + '行' };
const jobDoneText = j => (Object.hasOwn(JOB_DONE, j.kind) ? JOB_DONE[j.kind] : x => x.segments + '行')(j);
function jobFailText(j){
  const t = j.title || '無題', k = JOB_KIND_NAME[j.kind] || '処理';
  return j.internal ? `「${t}」の${k}が途中で止まりました。もう一度始めてください` : `「${t}」の${k}に失敗しました: ${j.error || '理由は不明です'}`;
}
/* 失敗した文字起こしを、同じ指定でもう一度待機列に入れる(知らせ・処理状況のカードの [やり直す]) */
async function retryJob(id){
  try { await api('/api/jobs/retry', { body: { id } }); await kickJobs(); toast('もう一度、待機列に入れました(メニューの「処理状況」に進み具合が出ます)', 4000); }
  catch (er){ toast(er.message, 6000, 'err'); }
}

function renderJobs(){
  renderJobBadge(); renderIntoState(); renderAlt();
  const box = $('#jobs');
  let html;
  if (!S.jobs.length) html = '<p class="hint" style="margin:6px 0 0">まだ処理中のものはありません。文字起こしを始めると、ここに進み具合が出ます。</p>';   // 空の状態は 2 文
  else html = S.jobs.slice(0, 10).map(j => `<div class="job" data-id="${esc(j.id)}">
    <div class="row" style="justify-content:space-between;flex-wrap:nowrap"><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500">${esc(j.title)}</span>
      <span class="pill ${j.state === 'done' ? 'ok' : j.state === 'error' ? 'err' : ACTIVE.has(j.state) ? (j.state === 'queued' ? 'wait' : 'run') : ''}">${esc(STATE_LABEL[j.state] || j.state)}</span></div>
    ${j.hasClip ? '<div class="hint" style="margin-top:2px">元の配信の情報(.clip.json)つき</div>' : ''}
    ${ACTIVE.has(j.state) ? `<div class="bar${j.state === 'running' ? '' : ' indeterminate'}"><i style="width:${pctOf(j)}%"></i></div><div class="row" style="justify-content:space-between;margin-top:3px"><span class="hint">${esc(jobPhase(j))}${j.device ? '(' + devLabel(j.device) + ')' : ''}</span><button type="button" class="btn small" data-act="cancel">中止</button></div>` : ''}
    ${j.error ? `<div class="hint tt-jerr">${esc(j.internal ? (JOB_KIND_NAME[j.kind] || '処理') + 'が途中で止まりました。もう一度始めてください' : j.error)}</div>${j.errorDetail ? `<details class="tt-jerr-detail"><summary>詳しく</summary><span class="mono">${esc(j.errorDetail)}</span></details>` : ''}${j.canRetry ? '<div class="row" style="margin-top:4px"><button type="button" class="btn small" data-act="retry">やり直す</button></div>' : ''}` : ''}
    ${(Array.isArray(j.warnings) ? j.warnings : []).slice(0, 3).map(w => `<div class="notice tt-jwarn">${esc(w)}</div>`).join('')}
    ${j.state === 'done' && j.tid ? `<div class="row" style="margin-top:3px"><span class="hint">${jobDoneText(j)}</span><button type="button" class="btn small" data-act="open" data-tid="${esc(j.tid)}">開く</button></div>` : ''}
  </div>`).join('');
  if (html === S.jobsHtml) return;   // 1 秒ごとの問い合わせで変わっていなければ描き直さない(開いた「詳しく」・フォーカスを保つ)
  box.innerHTML = html; S.jobsHtml = html;
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
  $('#diarSmooth').checked = S.settings.diarSmooth === true;
}

/* 短い 1 行だけ別の人になるのをならす(設定 diarSmooth。試験中・既定オフ。送ったキーだけ直す api/settings/patch。判別の要求でも smooth として送る) */
async function diarSmoothSave(on){
  if (!(await patchSettings({ diarSmooth: on }, '設定を保存できませんでした'))) $('#diarSmooth').checked = S.settings.diarSmooth === true;   // 失敗は元に戻したあとの値に合わせる
}

/* 編集を止めるジョブ: 話者判別・再認識と、この動画の作り直し(1 本ずつ。文字起こしのジョブで tid は終わるまで空 = into で見る) */
function lockJob(){ return S.doc ? S.jobs.find(j => ACTIVE.has(j.state) && ((LOCK_KINDS.includes(j.kind) && j.tid === S.docId) || ((j.redoOne || j.rerunWhole) && j.into === S.docId))) : null; }

function applyLock(){
  const j = lockJob(), on = !!j;
  $('#segs').inert = on; document.querySelectorAll('#doc .tt-lockable').forEach(el => { el.inert = on; }); $('#docTitle').disabled = on;
  if (S.doc) renderCutPack();
  renderRedoOne();
  const b = $('#diarBanner'); b.hidden = !on;
  if (on) b.textContent = `${j.redoOne ? 'この動画を今の設定で作り直' : LOCK_LABEL[j.kind] || '処理'}しています(${j.phase}${j.state === 'running' ? ' ' + Math.round(j.progress * 100) + '%' : ''})。終わると自動で読み込み直します。それまで編集はできません(中止は左の「処理状況」から)。`;
}

/* 話者判別の人数:文書ごと(文書の diarNum = 選んだとき POST api/doc-diarnum。文書の updatedAt は変えない)。
   選んでいない文書は、その文書の話者の数(組み込みの「ゲーム音声など」を除く。1〜8)、話者もいなければ全体の既定(設定 diarNum = 最後に選んだ人数)。
   -> {n, why: 'doc' | 'speakers' | 'default'} */
function diarNumFor(d){
  if (d && Number.isInteger(d.diarNum) && d.diarNum >= 0 && d.diarNum <= 8) return { n: d.diarNum, why: 'doc' };
  const k = d ? (d.speakers || []).filter(s => !isOtherSp(s)).length : 0;
  if (k > 0) return { n: Math.min(8, k), why: 'speakers' };
  const g = Number(S.settings.diarNum);
  return { n: Number.isInteger(g) && g >= 0 && g <= 8 ? g : 0, why: 'default' };
}

/* 文書を開いた・設定を読み直したとき: 人数の欄にこの文書の人数と、その理由(結果と理由を見せる) */
function fillDiarNum(){
  const r = diarNumFor(S.doc), w = $('#diarNumWhy');
  $('#diarNum').value = String(r.n);
  if (w) w.textContent = !S.doc ? '' : r.why === 'doc' ? 'この文書で選んだ人数' : r.why === 'speakers' ? `この文書の話者の数(${r.n}人)` : '';
}

/* 人数を選んだ: 開いている文書に覚え、全体の既定(話者のいない文書の初めの値)も最後に選んだ人数にする */
async function diarNumChanged(){
  const v = $('#diarNum').value, n = Number(v) || 0, d = S.doc, id = S.docId;
  S.settings.diarNum = v; saveSettings();
  if (!d){ fillDiarNum(); return; }
  const old = d.diarNum; d.diarNum = n; fillDiarNum();
  try { await api('/api/doc-diarnum', { body: { id, diarNum: n } }); }
  catch (e){ if (S.doc === d){ if (old === undefined) delete d.diarNum; else d.diarNum = old; fillDiarNum(); } toast('話者の人数を覚えられませんでした: ' + e.message, 6000, 'err'); }
}

async function startDiarize(){
  if (!S.doc) return;
  if (!(await saveFirst())) return;
  await api('/api/diarize', { body: { tid: S.docId, numSpeakers: Number($('#diarNum').value) || 0, embedding: $('#diarEmb').value, recognize: $('#diarRecog').checked, smooth: $('#diarSmooth').checked } });
  await kickJobs(); toast('話者の判別を待機列に追加しました');
}

/* ---------- 全行をこの人に(評価用) ----------
   評価用の文書で話者の無い行があるとき(評価用のフォルダへ移すには全行に話者が要る)、候補(GET api/drill/candidates =
   この文書の覚えた声 → メンバーのフォルダ → 配信の文脈 → ほかの覚えた声・メンバー)から1人選び、既存の 1人指定
   (POST api/diarize の numSpeakers 1 + names。サーバーの single_speaker が全行をその人にして diar.json も書く)で付ける。状態は app.js の SPALL */

function spAllNeeded(){
  const d = S.doc; if (!d || d.evalSet !== true) return false;
  const ids = new Set((d.speakers || []).map(s => s.id));
  return d.segments.some(s => hasText(s) && !ids.has(s.speaker));
}

function renderSpAll(){
  const box = $('#spAllBox'); if (!box) return;
  const on = spAllNeeded(); box.hidden = !on;
  if (!on) return;
  if (SPALL.id !== S.docId){ SPALL.id = S.docId; SPALL.cands = []; SPALL.suggest = ''; fillSpAll(); loadSpAll(S.docId); }
  const ids = new Set(S.doc.speakers.map(s => s.id)), none = S.doc.segments.filter(s => hasText(s) && !ids.has(s.speaker)).length;
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
  if (!(await saveFirst())) return;
  await api('/api/diarize', { body: { tid: S.docId, numSpeakers: 1, names: [name], recognize: false } });
  await kickJobs(); toast(`全行の話者を「${name}」にしています`);
}

/* ---------- 声を覚える。覚えるのはジョブ(/api/voices/learn)、照らし合わせは話者判別のジョブの中(recognize)。
   声の特徴そのものは画面に来ない(一覧は名前・行の数・秒だけ) ---------- */

function namedSpeakers(){ return S.doc ? (S.doc.speakers || []).filter(s => s.name && !DEFAULT_SPK.test(s.name)) : []; }

function renderVoiceLearn(){
  const b = $('#voiceLearn'), n = namedSpeakers(), d = S.tools && S.tools.diarize, ev = !!(S.doc && S.doc.evalSet);
  b.disabled = !S.doc || ev || !n.length || !(d && d.ready) || !!lockJob();   // 評価用は押せなくし、理由をヒントに出す(隠さない)
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
      `<div class="row" data-emb="${esc(k)}" data-name="${esc(x.name)}" style="margin-top:4px;justify-content:space-between;flex-wrap:nowrap"><span>${esc(x.name)} <span class="hint">${x.rows}行 ・ ${Math.round(x.sec / 6) / 10}分 ・ ${esc(ago(x.updatedAt))}</span>${x.generic ? ' <span class="pill warn" data-generic>一般的な名前です(忘れることをおすすめします)</span>' : ''}</span><button type="button" class="btn small danger" data-act="vdel">忘れる</button></div>`).join('')).join('');
}

/* ---------- 再認識 ---------- */

function flagParts(s){ const p = String(s.flag || '').split('、').filter(Boolean); return { spk: p.filter(x => SPK_FLAGS.includes(x)), text: p.filter(x => !SPK_FLAGS.includes(x)) }; }

function flagMatch(s, kind){ if (kind === 'read') return !!readMark(s); if (kind === 'proofed') return !!s.proofed; if (kind === 'unproofed') return !s.proofed; if (kind === 'cut') return s.cutState === 'cut'; if (kind === 'sug') return sugList(s).length > 0; const f = flagParts(s); return kind === 'any' ? !!s.flag : kind === 'text' ? f.text.length > 0 : f.spk.length > 0; }

function renderRtSetup(){
  const t = S.tools, sel = $('#rtModel'); if (!t) return;
  sel.innerHTML = t.models.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  const want = S.settings.rtModel && t.models.some(m => m[0] === S.settings.rtModel) ? S.settings.rtModel : (t.models.some(m => m[0] === 'large-v3') ? 'large-v3' : t.models[0][0]);
  sel.value = want;
  if (['text', 'flagged', 'sel', 'all', 'range', 'whole'].includes(S.settings.rtTarget)) $('#rtTarget').value = S.settings.rtTarget;
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
  if (k === 'flagged') return [];   // サーバーが疑わしい行を選ぶ(送らない。数もサーバーが決める)
  if (k === 'whole') return segs.filter(s => !s.proofed).map(s => s.id);   // 数えるだけ(送らない。サーバーが直した行以外を選ぶ)
  return segs.filter(s => k === 'all' || (k === 'sel' ? S.sel.has(s.id) : flagMatch(s, 'text'))).map(s => s.id).slice(0, 2000);
}

function updateRt(){
  if (!S.doc){ $('#rtHint').textContent = ''; return; }
  const ids = new Set(rtIds()), sec = S.doc.segments.filter(s => ids.has(s.id)).reduce((a, s) => a + (s.end - s.start), 0);
  $('#rtHint').textContent = `対象: ${ids.size}行(音声 約${approxLen(sec)})`;
  $('#rtGo').disabled = !ids.size;
  if ($('#rtTarget').value === 'flagged'){
    $('#rtHint').textContent = '疑わしい行をサーバーが選びます(文字が少ない = 抜けの可能性のある行)';
    $('#rtGo').disabled = !!S.doc.evalSet;   // 評価用の文字起こしは再認識できません
    return;
  }
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
  $('#rtHint').textContent = `動画全体 ${fmtT(a)}〜${fmtT(b)} を認識し直します。` + (kept ? `直した ${kept} 行は残し、` : '') + `残り ${rest} 行を新しい行に差し替えます(行の数は変わります。文字が出なかった所は元の行を残します)。`
    + (min ? `目安 約${min}分(CPU・large-v3)。` : '') + (S.doc.evalSet ? ' — 評価用の文字起こしは再認識できません' : '') + (tooLong ? ' — 長すぎます(最大6時間)' : '');
  $('#rtGo').disabled = !(b > a) || tooLong || !!S.doc.evalSet;
}

async function startRetranscribe(){
  if (!S.doc) return;
  const k = $('#rtTarget').value, whole = k === 'whole', flagged = k === 'flagged';
  const ids = whole || flagged ? [] : rtIds(); if (!ids.length && !whole && !flagged) return toast('再認識する行がありません');
  const target = { text: 'rows', sel: 'rows', all: 'rows', range: 'span', whole: 'whole', flagged: 'flagged' }[k] || 'rows';   // サーバーの受付 POST /api/rerun の対象(flagged の ids はサーバーが選ぶ)
  if (!(await saveFirst())) return;
  await api('/api/rerun', { body: { tid: S.docId, target, engine: 'main', result: 'replace', ids, vadMode: vadModeOf(), wordSplit: optCheck('wordSplit'), ...subtitleReq(), stripPunct: optCheck('stripPunct'), model: $('#rtModel').value, language: $('#optLang').value, device: $('#optDevice').value,
    boost: optCheck('boost'), glossary: $('#optGloss').value, autoDict: optCheck('autoDict'), autoGloss: optCheck('autoGloss'), autoContext: optCheck('autoContext') } });   // チェックは設定の画面の値(保存した設定から)
  await kickJobs(); toast(whole ? '動画全体の再認識を待機列に追加しました(終わると読み込み直します)' : flagged ? '疑わしい行の再認識を待機列に追加しました' : `${ids.length}行の再認識を待機列に追加しました`);
}
