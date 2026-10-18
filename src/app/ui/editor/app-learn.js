/* app-learn.js — 「編集」の画面: 修正から学習した候補・修正の提案・校正済み・進み具合の帯・認識精度の測定・名簿と用語集・保存データへの保管・評価用の確かめ済み(段10 で app.js から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は src/app/ui/cases/edhost.js の ED_SCRIPTS の1か所。RS8 C4 で編集の画面のページは消した) */
'use strict';

/* ---------- 修正の提案の読み直し(保存のあと。学習した候補の一覧と登録はホームの運用の「編集の精度と学習」= src/app/ui/home/portal-edit.js) ---------- */

function scheduleSuggest(){ clearTimeout(scheduleSuggest.t); scheduleSuggest.t = setTimeout(loadSuggest, 4000); }

async function putSettingsNow(){   // すぐ保存する(辞書への登録・カットの設定など)。保存できなければ投げる(呼んだ側が知らせる)
  clearTimeout(setT); setT = null;
  if (S.settingsLoadErr) throw new Error('設定を読み込めていないため保存しません(設定の「読み直す」を押してください)');
  if (!(await sendSettings())) throw new Error('設定を保存できませんでした(設定に理由と「もう一度」があります)');
}

/* ---------- 修正の提案(文脈つきの統計) ---------- */

function sugList(s){ return S.sug.filter(x => x.seg === s.id && s.text.includes(x.wrong)); }

function sugHTML(s){
  return sugList(s).map(x => {
    const alt = x.tier === 'alt';   // 2つ目のエンジンとの食い違い(D1-b)。学習の候補と見分けられるように札「別」と色
    const tip = alt ? `別のエンジン(${S.alt ? S.alt.label : ''})では、こう聞こえた候補です。聞いて合っていれば採用してください`
      : `この置換は ${x.pos}回 直されています / そのまま残した例 ${x.neg}件`;
    return `<span class="sg ${x.tier === 'high' ? 'high' : ''}${alt ? ' tt-sg-alt' : ''}" title="${esc(tip)}"><span class="sgl">${x.tier === 'high' ? '確度高' : alt ? '別' : '候補'}</span>「${esc(x.wrong)}」→「${esc(x.right)}」<button type="button" data-act="sgok" data-n="${x.n}">採用</button><button type="button" data-act="sgno" data-n="${x.n}">却下</button></span>`;
  }).join('');
}

function renderChips(){
  if (!S.doc) return;
  document.querySelectorAll('#segs .seg').forEach(el => { const s = S.doc.segments[Number(el.dataset.i)], box = el.querySelector('.sug'); if (s && box) box.innerHTML = sugHTML(s); });
  let hi = 0, all = 0;
  for (const s of S.doc.segments){ const l = sugList(s); all += l.length; for (const x of l) if (x.tier === 'high') hi++; }
  const b = $('#btnSugHigh'); b.hidden = !hi; b.textContent = `確度高の提案を全部採用(${hi})`;
  $('#flagKind').querySelector('option[value=sug]').textContent = all ? `修正の提案がある行だけ(${all}件)` : '修正の提案がある行だけ';
  if ($('#flagKind').value === 'sug') applyFilter();
}

async function loadSuggest(){
  const id = S.docId; if (!id) return;
  let r; try { r = await api('/api/suggest?id=' + encodeURIComponent(id)); } catch { return; }
  if (S.docId !== id) return;
  S.sug = (r.items || []).map(x => ({ ...x, n: ++sugSeq })); S.alt = r.alt || null; renderChips(); renderAlt();
}

function sugFeedback(action, xs){
  const tid = S.docId; if (!tid || !xs.length) return;
  api('/api/suggest/feedback', { body: { tid, action, items: xs.map(x => ({ seg: x.seg, wrong: x.wrong, right: x.right, ...(x.tier === 'alt' ? { tier: x.tier } : {}) })) } }).catch(() => {});
}

/* ---------- 2つ目のエンジンとの食い違いの候補(精度改善 第2版 D1-b。サーバーは human/proof/alt.py) ---------- */

function altJob(){ return S.doc ? S.jobs.find(j => j.kind === 'alt' && j.tid === S.docId && ACTIVE.has(j.state)) : null; }

/* 「文字をまとめて直す」の「別のエンジンの候補」: エンジンの選択(設定 altEngine)・始めるボタン・今の結果 */
function renderAlt(){
  const sel = $('#altEngine'), info = S.tools && S.tools.alt;
  if (info && sel.dataset.filled !== '1'){
    sel.innerHTML = info.engines.map(e => `<option value="${esc(e.key)}"${e.ready ? '' : ` title="${esc(e.why || '')}"`}>${esc(e.label)}${e.ready ? '' : '(まだ使えません)'}</option>`).join('');
    sel.dataset.filled = '1';
  }
  if (info){ const want = S.settings.altEngine || info.default; if ([...sel.options].some(o => o.value === want)) sel.value = want; }
  const d = S.doc, j = altJob(), b = $('#altGo'), msg = $('#altMsg');
  const why = !d ? '' : d.evalSet ? '評価用の文字起こしでは使えません(定点の正解が2つのエンジンに寄らないように)' : !d.sourcePath ? 'この文書には動画のパスが無いため使えません'
    : !(d.segments || []).some(hasText) ? '先に文字起こしをしてください' : '';
  b.disabled = !d || !!why || !!j;
  b.title = why;
  const n = (S.sug || []).filter(x => x.tier === 'alt').length;
  msg.textContent = j ? `聞いています(${jobPhase(j)})。終わると候補が行に出ます`
    : why ? why
    : S.alt ? `${S.alt.label} の結果(${ago(S.alt.at)}): 食い違いの候補 ${n} 件`
    : 'まだ別のエンジンで聞いていません';
}

function applySug(s, x){
  const k = s.text.startsWith(x.wrong, x.i) ? x.i : s.text.indexOf(x.wrong); if (k < 0) return false;
  s.text = (s.text.slice(0, k) + x.right + s.text.slice(k + x.wrong.length)).slice(0, 2000); delete s.proofed; return true;
}

function acceptSug(s, x){
  pushUndo();
  if (!applySug(s, x)){ S.undo.pop(); updateUndo(); return; }
  S.sug = S.sug.filter(y => y !== x); sugFeedback('accept', [x]); markDirty();
  const i = S.doc.segments.indexOf(s), ta = document.querySelector(`#segs .seg[data-i="${i}"] textarea`);
  if (ta){ ta.value = s.text; autoSize(ta); }
  syncProof(s); updatePfStat(); renderChips();
}

function rejectSug(x){ S.sug = S.sug.filter(y => y !== x); sugFeedback('reject', [x]); renderChips(); }

/* ---------- 校正済み(正解として使える行の印) ---------- */

function setProof(s, on, row){
  if (on && !s.proofed) S.sess.n++; else if (!on && s.proofed && S.sess.n > 0) S.sess.n--;
  if (on) s.proofed = true; else delete s.proofed;
  if (row){ row.classList.toggle('proofed', !!on); const b = row.querySelector('[data-act=proof]'); if (b) b.setAttribute('aria-pressed', on ? 'true' : 'false'); }
}

function syncProof(s){ const i = S.doc.segments.indexOf(s), row = document.querySelector(`#segs .seg[data-i="${i}"]`); if (row) setProof(s, !!s.proofed, row); }

function updatePfStat(){
  renderDocBar();
  if (!S.doc) return;
  const n = S.doc.segments.filter(s => s.proofed).length, t = S.doc.segments.length;
  $('#btnProofAll').textContent = t && n === t ? '校正済みを全解除' : '全行を校正済みに';
  $('#btnProofSel').disabled = !S.sel.size; $('#btnProofSel').title = S.sel.size ? '左端のチェックで選んだ行を校正済みにします' : '行の左端のチェックで行を選ぶと押せます';   // 押せない理由(S16)
  $('#btnNextUn').classList.toggle('primary', S.doc.segments.some(isUnproofed));   // 未校正がある間は次の一手(S3)
  updateSess(); drawStripSoon();
}

function updateSess(){
  if (!S.doc){ $('#sessStat').textContent = ''; return; }
  const un = S.doc.segments.filter(s => !s.proofed && s.text.trim()), sec = un.reduce((a, s) => a + (s.end - s.start), 0), m = Math.round(S.sess.activeMs / 60000);
  $('#sessStat').textContent = `未校正 ${un.length}行(音声 約${approxLen(sec)}) ・ 今回 +${S.sess.n}行 ・ 作業${m}分`;
}

/* ---------- 操作中の知らせ: 操作している間、文書の effort.lastAt を進める(api/effort) ----------
   ⑤ の評価用の作り直しが「人が作業中」の文書を上書きしない守りに使う。作業した時間は数えない(決定 3-47。数え方が粗いのでやめた)。
   上の S.sess.activeMs と同じ 30 秒刻み(2 分操作しなければ数えない)で、5 分たまったとき・画面を離れたとき・別の文書を開くときに送る。
   文書の保存とは別の API なので、文書の updatedAt を変えない(保存の競合 409 に巻き込まない)。校正済みにした行の数は、保存のときにサーバーが数える */
function effortTick(ms){
  if (!S.docId || !S.doc) return;
  if (S.eff.id !== S.docId) effortStart(S.docId);
  S.eff.ms += ms;
  if (S.eff.ms >= 300000) effortFlush();
}

function effortStart(id){
  if (S.eff.id === id) return;
  effortFlush();
  S.eff = { id, ms: 0 };
}

function effortFlush(keepalive){
  const e = S.eff;
  if (!e.id || !e.ms) return;
  e.ms = 0;
  api('/api/effort', { body: { id: e.id }, keepalive: !!keepalive }).catch(() => {});   // 知らせなので、失敗しても作業は止めない(操作が続けば次の 5 分でまた送る)
}

/* ---------- 進み具合の帯(校正済み・要確認・未校正を、時間軸で見る) ---------- */

function drawStripSoon(){ if (!stripQ) stripQ = requestAnimationFrame(() => { stripQ = 0; drawStrip(); }); }

function drawStrip(){
  const cv = $('#strip'); if (!S.doc || !cv || !cv.offsetParent) return;
  const g = S.doc.segments; let a = Infinity, b = 0;
  for (const x of g){ if (x.start < a) a = x.start; if (x.end > b) b = x.end; }
  S.stripR = g.length && b > a ? [a, b] : null;
  const w = cv.clientWidth, h = cv.clientHeight, dpr = window.devicePixelRatio || 1;
  cv.width = Math.max(1, Math.round(w * dpr)); cv.height = Math.max(1, Math.round(h * dpr));
  if (!S.stripR) return;
  const c = cv.getContext('2d'), cs = getComputedStyle(document.documentElement);
  const col = { ok: cs.getPropertyValue('--ok').trim(), warn: cs.getPropertyValue('--warn').trim(), off: cs.getPropertyValue('--line-2').trim() }, k = cv.width / (b - a);
  for (const x of g){ c.fillStyle = x.proofed ? col.ok : x.flag ? col.warn : col.off; c.fillRect((x.start - a) * k, 0, Math.max(1, (x.end - x.start) * k - 0.5), cv.height); }
  moveStripHead();
}

function moveStripHead(){
  const r = S.stripR, hd = $('#stripHead'); if (!r) return;
  hd.style.left = Math.min(100, Math.max(0, (player().currentTime - r[0]) / (r[1] - r[0]) * 100)) + '%';
}

/* ---------- 評価用の文書の「確かめ済み」(動画を全部聞いて直した印 evalReviewed。校正の画面の右の上。定点に数えるのはこれだけ。サーバーは eval/drill/drill.py) ---------- */

function renderEvalReview(){
  const box = $('#evrBox'); if (!box) return;
  renderRedoOne();   // 「この動画を作り直す」
  const d = S.doc, on = !!(d && d.evalSet === true);
  box.hidden = !on; if (!on) return;
  const rv = d.evalReviewed && typeof d.evalReviewed === 'object' ? d.evalReviewed : null;
  $('#evrPill').className = 'pill ' + (rv ? 'ok' : 'wait'); $('#evrPill').textContent = rv ? '確かめ済み' : 'まだ確かめていない';
  $('#evrText').textContent = rv ? `${UIKit.fmt.date(rv.at)} に、動画を全部聞いて確かめました(定点に数えます。直しても印は残ります)`
    : '動画をはじめから終わりまで聞いて(行と行のすき間も)直したら、済みにしてください。精度の測定の正解(定点)に数えるのは、済みにした動画だけです';
  $('#evrMark').hidden = !!rv; $('#evrUndo').hidden = !rv;
  $('#evrMark').disabled = !!lockJob();
}

/* 「全部聞いて直したので済みにする」。via: 'editor'(サーバーの記録に残す入口の名前)。
   話者の無い行があれば確かめる → 編集中の内容を保存し終える(未保存の変更を失わない)→ api/drill/reviewed。-> 付けたか */
async function markReviewed(via){
  if (!S.doc || !S.docId) return false;
  if (S.doc.evalSet !== true){ toast('評価用の文字起こしではありません(確かめ済みの印は、評価用の文字起こしだけに付けます)', 5000, 'err'); return false; }
  if (lockJob()){ toast('この文字起こしは処理中です。終わってから、もう一度押してください', 5000); return false; }
  const id = S.docId, ids = new Set((S.doc.speakers || []).map(s => s.id));
  const none = S.doc.segments.filter(s => hasText(s) && !ids.has(s.speaker)).length;
  if (none && !(await UIKit.dialog.confirm({ title: '話者が無い行があります', ok: 'このまま済みにする',
    body: `話者が無い行が ${none} 行あります(評価用のフォルダへ移すには全行に話者が要ります)。このまま済みにしますか` }))) return false;
  if (S.docId !== id) return false;
  if (!(await savedFor(id))){
    toast('保存が終わっていないため、済みにしていません(保存の状態を確かめてから、もう一度押してください)', 6000, 'err'); return false;
  }
  let r;
  try { r = await api('/api/drill/reviewed', { body: { id, baseUpdatedAt: S.baseUpdatedAt, via } }); }
  catch (e){
    if (S.docId !== id) return false;
    if (e.code === 'conflict') showConflict();   // 保存の 409 と同じ案内(映像の上の帯から選ぶ)
    toast('済みにできませんでした: ' + e.message, 7000, 'err'); return false;
  }
  if (S.docId === id){ S.baseUpdatedAt = r.updatedAt; S.doc.evalReviewed = r.evalReviewed; }
  toast(`確かめ済みにしました${r.proofed ? `(残りの ${r.proofed} 行を校正済みに)` : ''}`, 4000, 'ok');
  return true;
}

async function unmarkReviewed(){
  if (!S.doc || !S.doc.evalReviewed) return;
  const id = S.docId;
  if (!(await UIKit.dialog.confirm({ title: '確かめ済みを取り消しますか', ok: '取り消す',
    body: '「動画を全部聞いて確かめた」印を外します。印を付けたときに校正済みにした行も、未校正に戻します(それより前から校正済みだった行はそのままです)。' }))) return;
  if (S.docId !== id) return;
  if (!(await savedFor(id))) return toast('保存が終わっていないため、取り消していません', 6000, 'err');
  try { await api('/api/drill/unreviewed', { body: { id, baseUpdatedAt: S.baseUpdatedAt } }); }
  catch (e){
    if (S.docId === id && e.code === 'conflict') showConflict();
    return toast('取り消せませんでした: ' + e.message, 7000, 'err');
  }
  if (S.docId === id) await openDoc(id, true);   // 戻した行の校正済みを画面にも(見ていた行はそのまま)
  toast('確かめ済みを取り消しました', 4000); syncListItem();
}

/* 「全部聞いて直したので済みにする」: 印を付けたら読み直す(校正済みにした行を画面にも。見ていた行はそのまま) */
async function evalReviewHere(){
  const id = S.docId;
  if (await markReviewed('editor') && S.docId === id){ await openDoc(id, true); syncListItem(); }
}

/* この動画だけを今の設定で作り直す(2026-10-05。評価ドリルで校正しながら、後処理の調整の効き目を 1 本ずつ確かめる)。
   サーバーの eval/drill/evalbatch.py の eval_batch_redo_one: 見回りを待たずにすぐ待機列へ・確かめ済みは断る・人が手を入れた文書は確認のあと force。
   作り直しの間は編集を止める(lockJob が public_job の redoOne を見る)・終わると pollJobs が読み直す。キーは割り当てない(押し間違いで消さない) */
function redoOneState(){   // -> [押せるか, 理由(ボタンの title)]
  const d = S.doc;
  if (!d || d.evalSet !== true) return [false, '評価用の文字起こしだけを作り直せます'];
  if (d.evalReviewed) return [false, '確かめ済みの動画は作り直せません(先に確かめ済みを取り消してください)'];
  if (!d.model) return [false, 'まだ文字起こししていません'];
  if (REDO1.busy || lockJob()) return [false, 'この文字起こしは処理中です(終わってから押してください)'];
  return [true, '今の編集の設定(メニューの「新規」の認識の設定)で、この動画をはじめから文字起こしし直します。前の版は「以前の版に戻す」に残ります。話者は自動でもう一度判別します'];
}
function renderRedoOne(){
  const [ok, why] = redoOneState();
  const b = $('#evrRedo'); if (b){ b.disabled = !ok; b.title = why; }
}
async function redoOneHere(){
  const id = S.docId;
  const [ok, why] = redoOneState(); if (!ok) return toast(why, 5000);
  REDO1.busy = true; renderRedoOne();
  try {
    if (!(await savedFor(id))){
      if (S.docId === id) toast('保存が終わっていないため、作り直していません(保存の状態を確かめてから、もう一度押してください)', 6000, 'err');
      return;
    }
    await api('/api/eval-batch/redo-one', { body: { id, baseUpdatedAt: S.baseUpdatedAt } });   // 直した行は残る(機械の層だけ入れ替える = X-RERUN)
    toast('この動画の作り直しを待機列に追加しました(終わると自動で読み込み直します。それまで編集はできません)', 6000, 'ok');
    await kickJobs();
  } catch (e){
    if (S.docId !== id) return;
    if (e.code === 'conflict') showConflict();   // 保存の 409 と同じ案内
    toast('作り直せませんでした: ' + e.message, 7000, 'err');
  } finally { REDO1.busy = false; renderRedoOne(); }
}

/* ---------- ホロライブの名簿 / 用語集の「認識に効く長さ」 ---------- */

function glossFit(terms){   // 先頭から何語がヒントに収まるか
  let n = 0, len = 0;
  for (const t of terms){ const add = (n ? 1 : 0) + t.length; if (len + add > GLOSS_PROMPT) break; len += add; n++; }
  return { fit: n, len: terms.join('、').length };
}
function renderGlossFit(){
  const t = glossTerms($('#optGloss').value), f = glossFit(t);
  $('#glossFit').textContent = !t.length ? '' : f.fit >= t.length ? `${t.length}語(認識のヒントに全部入ります)` : `${t.length}語のうち、認識のヒントに入るのは先頭の${f.fit}語まで(${GLOSS_PROMPT}字まで)。後ろの語は効きません。今回の動画に出る人だけに絞ってください`;
}

function rosterNames(ids){
  const seen = new Set(), out = [];
  for (const g of (S.roster && S.roster.groups) || []) if (ids.includes(g.id)) for (const n of g.names) if (!seen.has(n)){ seen.add(n); out.push(n); }
  return out;
}

async function loadRoster(){
  try { S.roster = await api('/api/roster'); } catch { S.roster = null; }
  const box = $('#rosterGroups'), r = S.roster;
  if (!r || !r.groups.length){ box.textContent = '名簿を読めません(hololive-roster.json が無いか壊れています)'; $('#rosterAdd').disabled = true; return; }
  box.innerHTML = r.groups.map(g => `<label class="lag" style="display:inline-block;margin:0 10px 3px 0"><input type="checkbox" class="rg" value="${esc(g.id)}">${esc(g.label)}(${g.names.length})</label>`).join('');
  $('#rosterNote').textContent = `${r.asOf} 時点`; $('#rosterBox').title = r.note;
}
