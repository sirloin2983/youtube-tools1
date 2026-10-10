/* app-learn.js — 「編集」の画面: 修正から学習した候補・修正の提案・校正済み・進み具合の帯・認識精度の測定・名簿と用語集・保存データへの保管(段10 で app.js から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は index.html の1か所) */
'use strict';

/* ---------- 修正から学習した候補 ---------- */

function scheduleLearn(){ clearTimeout(scheduleLearn.t); scheduleLearn.t = setTimeout(loadLearned, 4000); }

async function loadLearned(){
  try { learned = await api('/api/learned?min=' + encodeURIComponent($('#lnMin').value)); } catch { return; }
  renderLearned(); loadSuggest();
}

function renderLearned(){
  const box = $('#lnList'), items = learned.items;
  $('#lnStat').textContent = learned.docs ? `修正した行: ${learned.lines || 0}行(学習の対象: ${learned.docs}件の文字起こし)` : '';
  if (!items.length){
    box.innerHTML = `<p class="hint" style="margin:8px 0 0">${learned.docs ? '候補はありません(文字起こしを直すと、ここに出ます)' : 'v0.5 以降で文字起こしした分から学習します。文字起こしを直すと、ここに候補が出ます'}</p>`;
    $('#lnMore').hidden = true;
    return;
  }
  const q = norm($('#lnSearch').value.trim());
  const found = items.map((x, i) => ({ x, i })).filter(({ x }) => !q || norm(`${x.wrong} ${x.right}`).includes(q));
  if (!found.length){ box.innerHTML = '<p class="hint" style="margin:8px 0">条件に合う候補はありません。検索の文字を消すと、すべての候補が出ます。</p>'; $('#lnMore').hidden = true; return; }
  const shown = learnedShowAll ? found : found.slice(0, 10);
  box.innerHTML = shown.map(({ x, i }) => {
    const d = lnDraft[lnKey(x)] || { w: x.wrong, r: x.right }, edited = d.w !== x.wrong || d.r !== x.right;
    return `<div class="ln${edited ? ' edited' : ''}" data-i="${i}">
    <div class="row" style="flex-wrap:nowrap;gap:4px"><input class="lw" type="text" value="${esc(d.w)}" maxlength="40" aria-label="誤(置換される文字)" style="flex:1;min-width:0"><span>→</span><input class="lr" type="text" value="${esc(d.r)}" maxlength="40" aria-label="正(置換後の文字)" style="flex:1;min-width:0"></div>
    <div class="row" style="margin-top:3px"><span class="pill">${x.count}回</span><button type="button" class="btn small" data-act="lnadd">登録</button><button type="button" class="btn small" data-act="lnign">無視</button><button type="button" class="btn small" data-act="lnrev"${edited ? '' : ' hidden'}>編集を戻す</button></div></div>`;
  }).join('') + '<p class="hint" style="margin:6px 0 0">「誤」「正」は、その場で直してから登録できます(例: 前後の文字を消して短くする)。</p>';
  const more = $('#lnMore'); more.hidden = found.length <= 10; more.textContent = learnedShowAll ? '上位10件だけ表示' : `残り${found.length - shown.length}件を表示`;
}

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
    const yt = x.tier === 'yt' || (alt && (x.also || []).includes('yt')), both = alt && yt;   // YouTube の字幕(A1)。alt と同じ直しは 1 つにまとめて札「別・YT」
    const ytName = ytLabel();
    const tip = both ? `別のエンジン(${S.alt ? S.alt.label : ''})と${ytName}の両方が、こう聞こえた候補です(2つが一致)。聞いて合っていれば採用してください`
      : alt ? `別のエンジン(${S.alt ? S.alt.label : ''})では、こう聞こえた候補です。聞いて合っていれば採用してください`
      : yt ? `${ytName}では、こう書かれている候補です。聞いて合っていれば採用してください` : `この置換は ${x.pos}回 直されています / そのまま残した例 ${x.neg}件`;
    return `<span class="sg ${x.tier === 'high' ? 'high' : ''}${alt ? ' tt-sg-alt' : ''}${x.tier === 'yt' ? ' tt-sg-yt' : ''}${both ? ' tt-sg-both' : ''}" title="${esc(tip)}"><span class="sgl">${x.tier === 'high' ? '確度高' : both ? '別・YT' : alt ? '別' : yt ? 'YT' : '候補'}</span>「${esc(x.wrong)}」→「${esc(x.right)}」<button type="button" data-act="sgok" data-n="${x.n}">採用</button><button type="button" data-act="sgno" data-n="${x.n}">却下</button></span>`;
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
  S.sug = (r.items || []).map(x => ({ ...x, n: ++sugSeq })); S.alt = r.alt || null; S.yt = r.yt ? { ...r.yt, tid: id } : null; renderChips(); renderAlt();
}

function sugFeedback(action, xs){
  const tid = S.docId; if (!tid || !xs.length) return;
  api('/api/suggest/feedback', { body: { tid, action, items: xs.map(x => ({ seg: x.seg, wrong: x.wrong, right: x.right, ...(x.tier === 'alt' || x.tier === 'yt' ? { tier: x.tier } : {}), ...(Array.isArray(x.also) && x.also.length ? { also: x.also } : {}) })) } }).catch(() => {});
}

/* ---------- 2つ目のエンジンとの食い違いの候補(精度改善 第2版 D1-b。サーバーは ed_alt.py) ---------- */

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
  renderYtcap();   // 下の「YouTube の字幕の候補」も同じ時に描き直す(ジョブの進み・候補の読み直し・設定の読み直し)
}

/* ---------- 元の配信の YouTube の字幕の候補(案 A1。サーバーは ed_ytcap.py) ---------- */

function ytcapJob(){ return S.doc ? S.jobs.find(j => j.kind === 'ytcap' && j.tid === S.docId && ACTIVE.has(j.state)) : null; }

function ytLabel(){ const y = S.yt && S.yt.tid === S.docId ? S.yt : null; return y && y.kind === 'manual' ? 'YouTube の字幕(配信者が付けたもの)' : 'YouTube の自動字幕'; }

/* 押せない理由(サーバーの ytcap_spec と同じ順。元の配信 = スタジオで書き出した切り抜きの clip の YouTube の配信) */
function ytcapWhy(d){
  if (!d) return '';
  if (d.evalSet) return '評価用の文字起こしには出しません(定点の正解が字幕に寄らないように)';
  const src = d.clip && d.clip.source;
  if (!src || src.kind !== 'youtube' || !/^[\w-]{11}$/.test(src.videoId || '')) return '元の配信が分からない文書です(スタジオで書き出した切り抜きだけ使えます)';
  if (!(d.segments || []).some(hasText)) return '先に文字起こしをしてください';
  const t = S.tools && S.tools.ytcap;
  return t && !t.ready ? (t.why || 'yt-dlp が見つかりません') : '';
}

/* 「文字をまとめて直す」の「YouTube の字幕の候補」: 始めるボタン・今の結果(取れなかった理由も) */
function renderYtcap(){
  const b = $('#ytcapGo'), msg = $('#ytcapMsg'); if (!b) return;
  const d = S.doc, j = ytcapJob(), why = ytcapWhy(d), y = S.yt && S.yt.tid === S.docId ? S.yt : null;
  b.disabled = !d || !!why || !!j;
  b.title = why;
  const n = (S.sug || []).filter(x => x.tier === 'yt' || (x.also || []).includes('yt')).length, agree = (S.sug || []).filter(x => x.tier === 'alt' && (x.also || []).includes('yt')).length;
  const err = !j && !y && d ? S.jobs.find(x => x.kind === 'ytcap' && x.tid === S.docId && x.state === 'error') : null;
  msg.textContent = j ? `字幕を取っています(${j.phase || ''})。終わると候補が行に出ます`
    : why ? why
    : y ? `${ytLabel()}(取得: ${ago(y.fetchedAt)}): 食い違いの候補 ${n} 件${agree ? `(うち別のエンジンと一致 ${agree} 件)` : ''}`
    : err ? `取れませんでした: ${err.error || ''}`
    : 'まだ字幕を取っていません';
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

/* ---------- 校正の手間(マスタープラン Q2): 文書ごとに操作していた時間をため、api/effort へ送る ----------
   時間は上の S.sess.activeMs と同じ 30 秒刻み(2 分操作しなければ数えない)。1 文字起こし のタブ = activeSec、2 カット・3 パック = cutSec。
   送るのは 5 分たまったとき・画面を離れたとき・別の文書を開くとき。文書の保存とは別の API なので、文書の updatedAt を変えない(保存の競合 409 に巻き込まない)。
   校正済みにした行の数は、保存のときにサーバーが数える(ここでは数えない) */
function effortTick(ms){
  if (!S.docId || !S.doc) return;
  if (S.eff.id !== S.docId) effortStart(S.docId);
  if (EDT.tab === 'tx') S.eff.tx += ms; else S.eff.cut += ms;
  if (S.eff.tx + S.eff.cut >= 300000) effortFlush();
}

function effortStart(id){
  if (S.eff.id === id) return;
  effortFlush();
  S.eff = { id, tx: 0, cut: 0, fresh: true };
}

function effortFlush(keepalive){
  const e = S.eff;
  if (!e.id || !(e.tx || e.cut)) return;
  const body = { id: e.id, activeSec: Math.round(e.tx / 1000), cutSec: Math.round(e.cut / 1000), newSession: e.fresh };
  e.tx = 0; e.cut = 0; e.fresh = false;
  api('/api/effort', { body, keepalive: !!keepalive }).catch(err => {   // 記録なので、失敗しても作業は止めない
    if (err.status && err.status < 500) return;   // 文書が消えた・形が違う: 送り直さない
    if (S.eff.id === body.id){ S.eff.tx += body.activeSec * 1000; S.eff.cut += body.cutSec * 1000; S.eff.fresh = S.eff.fresh || body.newSession; }   // 通信の失敗: 次に送る
  });
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

/* ---------- 認識精度の測定 ---------- */

async function loadBaselines(){
  let items = []; try { items = (await api('/api/eval-baselines')).items; } catch { return; }
  $('#blOut').innerHTML = items.length ? '<table class="acct"><tr><th>日時</th><th>メモ</th><th>CER</th><th>正解字</th><th>置換/脱落/挿入</th></tr>' + items.slice().reverse().slice(0, 12).map((x, i, a) => {
    const prev = a[i + 1], d = prev ? (x.cer - prev.cer) * 100 : null;
    return `<tr><td>${new Date(x.at).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td><td>${esc(x.label || '')}</td><td><b>${pct(x.cer)}</b>${d === null ? '' : `<br><span class="hint">${d <= 0 ? '' : '+'}${d.toFixed(1)}pt</span>`}</td><td>${x.refChars}</td><td>${x.sub}/${x.del}/${x.ins}</td></tr>`;
  }).join('') + '</table><p class="hint" style="margin:4px 0 0">pt = 1つ前の記録との差(マイナスがよくなった)。正解が1000字未満のうちは、差は誤差の範囲かもしれません。</p>' : '<p class="hint" style="margin:6px 0 0">まだ記録がありません</p>';
}

function scheduleAcc(){ clearTimeout(accT); accT = setTimeout(loadAcc, 4000); }

async function loadAcc(){
  try { renderAcc(await api('/api/metrics?legacy=' + ($('#accLegacy').checked ? 1 : 0) + '&scope=' + encodeURIComponent($('#accScope').value))); } catch (e){ $('#accOut').innerHTML = `<p class="hint" style="margin:8px 0 0;color:var(--danger)">${esc(e.message)}</p>`; }
}

function renderAcc(m){
  const o = m.overall, box = $('#accOut');
  if (!o.groups){
    box.innerHTML = `<p class="hint" style="margin:8px 0 0">校正済みの行がまだありません(${m.docs}件の文字起こしのうち、校正済みの行があるのは${m.docsProofed}件)。聞いて確認した行の「校正済み」ボタン${keyParen('proof')}で印を付けると、ここに文字誤り率が出ます。「印のない旧データも含める」で、これまでに直した分を仮計算できます。</p>`;
    return;
  }
  const errs = o.errs || 0, share = v => errs ? Math.round(v / errs * 100) + '%' : '—';
  const rows = list => list.map(c => `<tr><td>${esc(c.config || c.title || '')}</td><td>${c.groups}</td><td>${c.refChars}</td><td><b>${pct(c.cer)}</b></td><td>${c.sub}/${c.del}/${c.ins}</td></tr>`).join('');
  box.innerHTML = `<div class="accmain">文字誤り率(CER) <b>${pct(o.cer)}</b> <span class="hint">誤り ${errs}字 ÷ 正解 ${o.refChars}字</span></div>
    <p class="hint" style="margin:4px 0 0">内訳: 置換(別の字に間違い) ${o.sub}字(${share(o.sub)}) ・ 脱落(聞き逃し) ${o.del}字(${share(o.del)}) ・ 挿入(余計な字。幻覚など) ${o.ins}字(${share(o.ins)})<br>
    機械が出したが人が消した行: ${o.machineOnly}行(${o.machineOnlyChars}字) ・ 用語が正しく出た率: ${o.termRef ? `${o.termHit}/${o.termRef}(${pct(o.termRate)})` : '—'} ・ 用語の誤挿入: ${o.termExtra}回</p>
    <p class="hint" style="margin:4px 0 0">${m.legacy ? '※ 校正済みの印がない旧データを仮計算に含んでいます。' : ''}${o.refChars < 1000 ? '※ 正解が1000字未満なので、数値は目安です(同じ動画を何度も文字起こしした分は、重複して数えられます)。' : ''}校正済み ${m.proofedLines}行 ・ 対象 ${m.byDoc.length}件</p>
    <table class="acct"><tr><th>設定</th><th>行数</th><th>正解字</th><th>CER</th><th>置換/脱落/挿入</th></tr>${rows(m.byConfig)}</table>
    <details style="margin-top:6px"><summary class="hint">文字起こしごと</summary><table class="acct"><tr><th>文字起こし</th><th>行数</th><th>正解字</th><th>CER</th><th>置換/脱落/挿入</th></tr>${rows(m.byDoc)}</table></details>
    <details style="margin-top:6px"><summary class="hint">誤りが多い場所(上位)</summary>${o.worst.map(w => `<div class="wl"><span class="mono">${esc(w.doc || '')} ${fmtT(w.start)}</span><br>正: ${esc(w.ref) || '(人が消した行)'}<br>機: ${esc(w.hyp) || '(聞き逃し)'}</div>`).join('')}</details>`;
}

/* ---------- 評価ドリル(動画 1 本ずつ・この画面で。マスタープラン Q4。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md の (c)) ----------
   評価用の動画 1 本(30〜40 秒)を、いつもの 1 文字起こし の校正で全部聞いて直す(結合・分割・行の追加・削除・時刻・話者・全行をこの人に がそのまま使える)。
   「済みにして次へ」= 編集中の内容を保存し終えてから api/drill/reviewed(印 evalReviewed と残りの行の校正済み)→ api/drill/next → openDoc で開く
   (画面の再読み込みはしない)。URL の ?drill=1(?doc= と並べる)で帯を出す。状態は app.js の DR(済ませた本数・飛ばした文書はこのタブの sessionStorage)。
   定点(全部聞いて確かめた評価用の動画 15 分)の残りと条件は api/drill/status(「評価ドリル」のカード #drillCard と帯で同じ数字) */

async function loadDrillStat(){
  try { DR.status = await api('/api/drill/status'); } catch { return; }   // 古いサーバー・つながらない: 前の表示のまま
  renderDrillStat(DR.status); renderDrillBar();
}

const drillLeftText = st => st.leftSec > 0 ? `定点まであと ${Math.ceil(st.leftSec / 60)} 分` : '定点の 15 分に届きました';
const drillCondsText = st => (st.conds || []).map(c => `・${c.label} ${c.have}/${c.need}${c.unit}${c.ok ? '(済)' : ''}`).join('  ');

function renderDrillStat(st){
  if (!st || !$('#drillLeft') || st.reviewedSec === undefined) return;
  $('#drillLeft').textContent = `${drillLeftText(st)}(確かめ済み ${st.reviewedDocs} 本・${fmtDur(st.reviewedSec)} / 15 分。まだ ${st.pendingDocs} 本${st.untranscribed ? `・文字起こし前 ${st.untranscribed} 本` : ''})`;
  $('#drillConds').textContent = drillCondsText(st) + (st.ready ? '  — 条件がそろいました。「認識精度の測定」の「基準を記録」で出発点を残せます' : '');
  const go = $('#drillGo');
  go.disabled = DR.on || !st.pendingDocs;
  go.title = DR.on ? '評価ドリルの途中です(1 文字起こし のタブの上の帯)' : !st.pendingDocs ? 'まだ確かめていない評価用の動画(文字起こし済み)がありません' : 'まだ確かめていない評価用の動画を 1 本ずつ(乱数で)開きます。全部聞いて直したら「済みにして次へ」';
}

function drillLoad(){
  try {
    const o = JSON.parse(sessionStorage.getItem('tx.drill') || 'null');
    if (o && typeof o === 'object'){ DR.done = Math.max(0, Number(o.done) || 0); DR.skip = Array.isArray(o.skip) ? o.skip.filter(x => /^[0-9a-f]{12}$/.test(x)).slice(-200) : []; }
  } catch {}
}
function drillSave(){ try { sessionStorage.setItem('tx.drill', JSON.stringify({ done: DR.done, skip: DR.skip })); } catch {} }

function setUrlDrill(on){ setUrlParam('drill', on ? '1' : ''); }   // ?drill=1 を URL に残す(再読み込み・窓の開き直しでドリルを続ける)。?doc= は setUrlDoc が並べて残す

/* ドリルの帯(1 文字起こし のタブの上)。この動画の状態・定点の残り・済ませた本数・ボタン(キーは今の割り当て) */
function renderDrillBar(){
  const bar = $('#drillBar'); if (!bar) return;
  bar.hidden = !DR.on;
  renderEvalReview();
  if (!DR.on) return;
  const d = S.doc, pill = $('#drPill'), st = DR.status;
  const [cls, txt] = !d ? ['wait', '動画を選んでいます'] : d.evalSet !== true ? ['warn', 'この文字起こしは評価用ではありません'] : d.evalReviewed ? ['ok', 'この動画: 確かめ済み'] : ['wait', 'この動画: まだ'];
  pill.className = 'pill ' + cls; pill.textContent = txt;
  $('#drLeft').textContent = st && st.reviewedSec !== undefined ? `${drillLeftText(st)}(確かめ済み ${fmtDur(st.reviewedSec)} / 15 分)` : '';
  $('#drCount').textContent = `このドリルで ${DR.done} 本済み${DR.skip.length ? `・飛ばした ${DR.skip.length} 本` : ''}${st && st.reviewedSec !== undefined ? `・まだの動画 ${st.pendingDocs} 本` : ''}`;
  $('#drConds').textContent = st && st.conds ? '条件: ' + drillCondsText(st) : '';
  $('#drNone').hidden = !DR.none; $('#drNone').textContent = DR.none || '';
  const km = keymap(), kb = id => km[id] ? ' ' + kbdHTML(km[id]) : '';
  $('#drDoneKey').innerHTML = kb('drillDone'); $('#drSkipKey').innerHTML = kb('drillSkip');
  const off = DR.busy || !d || !!lockJob();
  $('#drDone').disabled = off || d.evalSet !== true; $('#drSkip').disabled = DR.busy;
  renderDrillSpk();
}

/* ドリルの帯の「話者を付ける…」の隣: 話者の無い行の数(評価用のフォルダへ移すには全行に話者が要る)。話者を付けたら renderSpAll からも呼ばれて数が変わる */
function renderDrillSpk(){
  const el = $('#drSpkHint'); if (!el || !DR.on) return;
  const d = S.doc;
  if (!d){ el.textContent = ''; return; }
  const ids = new Set((d.speakers || []).map(s => s.id)), rows = d.segments.filter(hasText);
  const none = rows.filter(s => !ids.has(s.speaker)).length;
  el.textContent = !rows.length ? '' : none ? `話者の無い行 ${none} 行` : '話者: 全行に付いています';
  // 機械が付けた話者(文字起こしのあとの自動の判別。文書の diarization.auto。人が判別し直す・全行をこの人に で消える。v0.50.0)
  const au = $('#drAutoSpk'), dz = d.diarization && typeof d.diarization === 'object' ? d.diarization : null;
  if (au){
    au.hidden = !(dz && dz.auto && rows.length);
    au.textContent = au.hidden ? '' : '話者は自動で付けてあります' + (dz.contextName ? `(「${dz.contextName}」は動画の入ったフォルダ・配信から推測)` : '') + '。違っていたら直してください';
  }
}

/* 評価用の文書の「確かめ済み」(ドリルの外。校正の画面の右の上)。ドリルの間は帯に出すので隠す(同じ操作の入口を2つ並べない) */
function renderEvalReview(){
  const box = $('#evrBox'); if (!box) return;
  renderRedoOne();   // 「この動画を作り直す」(ドリルの帯と、この欄の両方)
  const d = S.doc, on = !!(d && d.evalSet === true) && !DR.on;
  box.hidden = !on; if (!on) return;
  const rv = d.evalReviewed && typeof d.evalReviewed === 'object' ? d.evalReviewed : null;
  $('#evrPill').className = 'pill ' + (rv ? 'ok' : 'wait'); $('#evrPill').textContent = rv ? '確かめ済み' : 'まだ確かめていない';
  $('#evrText').textContent = rv ? `${UIKit.fmt.date(rv.at)} に、動画を全部聞いて確かめました(定点に数えます。直しても印は残ります)`
    : '動画をはじめから終わりまで聞いて(行と行のすき間も)直したら、済みにしてください。精度の測定の正解(定点)に数えるのは、済みにした動画だけです';
  $('#evrMark').hidden = !!rv; $('#evrUndo').hidden = !rv;
  $('#evrMark').disabled = !!lockJob();
}

/* 「全部聞いて直したので済みにする」(ドリルの「済みにして次へ」とドリルの外のボタン)。via: 'drill' | 'editor'。
   話者の無い行があれば確かめる → 編集中の内容を保存し終える(未保存の変更を失わない)→ api/drill/reviewed。-> 付けたか */
async function markReviewed(via){
  if (!S.doc || !S.docId) return false;
  if (S.doc.evalSet !== true){ toast('評価用の文字起こしではありません(確かめ済みの印は、評価用の文字起こしだけに付けます)', 5000, 'err'); return false; }
  if (lockJob()){ toast('この文字起こしは処理中です。終わってから、もう一度押してください', 5000); return false; }
  const id = S.docId, ids = new Set((S.doc.speakers || []).map(s => s.id));
  const drafts = blankDrafts().length;   // 重なり・抜けの所に置いた空の行が打たれずに残っている = その所はまだ聞いていない(残したまま「全部聞いた」にしない)
  if (drafts){
    if (!(await UIKit.dialog.confirm({ title: '空のままの下書きがあります', ok: '消して済みにする',
      body: `空のままの下書き(重なり・抜けの所に置いた空の行)が ${drafts} 行あります。消して済みにしますか(聞いて打つなら「キャンセル」。消した行は元に戻すで戻せます)` }))) return false;
    if (S.docId !== id) return false;
    removeBlankDrafts();
  }
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
  loadDrillStat();
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
  toast('確かめ済みを取り消しました', 4000); loadDrillStat(); syncListItem();
}

/* ドリルの外の「全部聞いて直したので済みにする」: 印を付けたら読み直す(校正済みにした行を画面にも。見ていた行はそのまま) */
async function evalReviewHere(){
  const id = S.docId;
  if (await markReviewed('editor') && S.docId === id){ await openDoc(id, true); syncListItem(); }
}

/* この動画だけを今の設定で作り直す(2026-10-05。評価ドリルで校正しながら、後処理の調整の効き目を 1 本ずつ確かめる)。
   サーバーの ed_evalbatch.eval_batch_redo_one: 見回りを待たずにすぐ待機列へ・確かめ済みは断る・人が手を入れた文書は確認のあと force。
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
  for (const id of ['drRedo', 'evrRedo']){ const b = $('#' + id); if (b){ b.disabled = !ok; b.title = why; } }
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
    const send = force => api('/api/eval-batch/redo-one', { body: { id, baseUpdatedAt: S.baseUpdatedAt, ...(force ? { force: true } : {}) } });
    try { await send(false); }
    catch (e){
      if (S.docId !== id) return;
      if (e.code !== 'touched') throw e;
      const x = e.data || {};
      if (!(await UIKit.dialog.confirm({ title: 'この動画を作り直しますか', ok: '作り直す',
        body: `この動画で直した${x.rows ? ` ${x.rows} 行` : '所'}${x.label ? `(${x.label})` : ''}は、新しい文字起こしに置き換わります(以前の版に戻すで戻せます)。作り直しますか` }))) return;
      if (S.docId !== id) return;
      if (!(await savedFor(id))) return toast('保存が終わっていないため、作り直していません', 6000, 'err');
      await send(true);
    }
    toast('この動画の作り直しを待機列に追加しました(終わると自動で読み込み直します。それまで編集はできません)', 6000, 'ok');
    await kickJobs();
  } catch (e){
    if (S.docId !== id) return;
    if (e.code === 'conflict') showConflict();   // 保存の 409 と同じ案内
    toast('作り直せませんでした: ' + e.message, 7000, 'err');
  } finally { REDO1.busy = false; renderRedoOne(); }
}

/* 始める(「評価ドリル」のカード #drillCard のボタン。URL の ?drill=1 で文書が無いときも)。続きの数(済ませた本数・飛ばした文書)は新しく数え直す */
async function drillStart(fresh = true){
  DR.on = true; DR.none = '';
  if (fresh){ DR.done = 0; DR.skip = []; drillSave(); }
  setUrlDrill(true);
  if (EDT.tab !== 'tx') setEditTab('tx');
  renderDrillBar(); txKeybarScene();
  if (!DR.status) loadDrillStat();
  return drillNext();
}

/* 次の 1 本を選んで開く(無ければ帯に理由)。-> 開いたか */
async function drillNext(){
  let r;
  try { r = await api('/api/drill/next?skip=' + encodeURIComponent(DR.skip.join(','))); }
  catch (e){ toast('次の動画を選べませんでした: ' + e.message, 6000, 'err'); return false; }
  if (!DR.on) return false;   // 待っている間にドリルを終えた
  if (!r.id){ DR.none = (r.reason || '次に出せる評価用の動画がありません') + '。「ドリルを終える」で閉じられます'; renderDrillBar(); toast(r.reason || '次に出せる評価用の動画がありません', 7000, 'info'); return false; }
  DR.none = '';
  const ok = await openDoc(r.id);
  if (!ok) toast('次の動画を開けませんでした(保存の状態を確かめてから、もう一度押してください)', 6000, 'err');
  renderDrillBar(); loadDrillStat();
  return ok;
}

async function drillDone(){
  if (!DR.on || DR.busy) return;
  DR.busy = true; renderDrillBar();
  const id = S.docId;
  try {
    if (!(await markReviewed('drill'))) return;
    DR.done++; drillSave();
    if (!(await drillNext()) && S.docId === id) await openDoc(id, true);   // 次が無い: 今の文書を読み直して、校正済みにした行を画面にも
  } finally { DR.busy = false; renderDrillBar(); }
}

async function drillSkip(){
  if (!DR.on || DR.busy) return;
  DR.busy = true; renderDrillBar();
  try {
    if (S.docId && !DR.skip.includes(S.docId)){ DR.skip.push(S.docId); drillSave(); }
    await drillNext();   // 直した分は openDoc が保存してから切り替える
  } finally { DR.busy = false; renderDrillBar(); }
}

function drillEnd(){
  const n = DR.done;
  DR.on = false; DR.none = ''; DR.done = 0; DR.skip = [];
  try { sessionStorage.removeItem('tx.drill'); } catch {}
  setUrlDrill(false); renderDrillBar(); txKeybarScene(); renderDrillStat(DR.status);
  toast(n ? `評価ドリルを終えました(このドリルで ${n} 本を済ませました)` : '評価ドリルを終えました', 5000, 'ok');
}

/* キー(⚙ のキー配置・? の一覧の「評価ドリル」)。帯が出ていないときは何もしないで知らせる */
function drillKey(act){
  if (!DR.on) return toast('評価ドリルの間だけ使えるキーです(メニューの「精度」の「評価ドリルを始める」)', 3000);
  if (act === 'drillDone') drillDone(); else drillSkip();
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
