/* app-learn.js — 「編集」の画面: 修正から学習した候補・修正の提案・校正済み・進み具合の帯・認識精度の測定・名簿と用語集・保存データへの保管(段10 で app.js から分けた。docs/plan/phase10-code-split.md)。
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
  if (!found.length){ box.innerHTML = '<p class="hint" style="margin:8px 0">条件に合う候補はありません</p>'; $('#lnMore').hidden = true; return; }
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
  if (S.settingsLoadErr) throw new Error('設定を読み込めていないため保存しません(⚙ 設定の「読み直す」を押してください)');
  if (!(await sendSettings())) throw new Error('設定を保存できませんでした(⚙ 設定に理由と「もう一度」があります)');
}

/* ---------- 修正の提案(文脈つきの統計) ---------- */

function sugList(s){ return S.sug.filter(x => x.seg === s.id && s.text.includes(x.wrong)); }

function sugHTML(s){
  return sugList(s).map(x => `<span class="sg ${x.tier === 'high' ? 'high' : ''}" title="${esc(`この置換は ${x.pos}回 直されています / そのまま残した例 ${x.neg}件`)}"><span class="sgl">${x.tier === 'high' ? '確度高' : '候補'}</span>「${esc(x.wrong)}」→「${esc(x.right)}」<button type="button" data-act="sgok" data-n="${x.n}">採用</button><button type="button" data-act="sgno" data-n="${x.n}">却下</button></span>`).join('');
}

function renderChips(){
  if (!S.doc) return;
  document.querySelectorAll('#segs .seg').forEach(el => { const s = S.doc.segments[Number(el.dataset.i)], box = el.querySelector('.sug'); if (s && box) box.innerHTML = sugHTML(s); });
  const hi = S.doc.segments.reduce((n, s) => n + sugList(s).filter(x => x.tier === 'high').length, 0), all = S.doc.segments.reduce((n, s) => n + sugList(s).length, 0);
  const b = $('#btnSugHigh'); b.hidden = !hi; b.textContent = `確度高の提案を全部採用(${hi})`;
  $('#flagKind').querySelector('option[value=sug]').textContent = all ? `修正の提案がある行だけ(${all}件)` : '修正の提案がある行だけ';
  if ($('#flagKind').value === 'sug') applyFilter();
}

async function loadSuggest(){
  const id = S.docId; if (!id) return;
  let r; try { r = await api('/api/suggest?id=' + encodeURIComponent(id)); } catch { return; }
  if (S.docId !== id) return;
  S.sug = (r.items || []).map(x => ({ ...x, n: ++sugSeq })); renderChips();
}

function sugFeedback(action, xs){
  const tid = S.docId; if (!tid || !xs.length) return;
  api('/api/suggest/feedback', { body: { tid, action, items: xs.map(x => ({ seg: x.seg, wrong: x.wrong, right: x.right })) } }).catch(() => {});
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
  $('#pfStat').textContent = t ? `校正済み ${n}/${t}行` : '';
  $('#btnProofAll').textContent = t && n === t ? '校正済みを全解除' : '全行を校正済みに';
  $('#btnProofSel').disabled = !S.sel.size;
  renderAbHint(); updateSess(); drawStripSoon();
}

function updateSess(){
  if (!S.doc){ $('#sessStat').textContent = ''; return; }
  const un = S.doc.segments.filter(s => !s.proofed && s.text.trim()), sec = un.reduce((a, s) => a + (s.end - s.start), 0), m = Math.round(S.sess.activeMs / 60000);
  $('#sessStat').textContent = `未校正 ${un.length}行(音声 約${sec < 90 ? Math.round(sec) + '秒' : Math.round(sec / 60) + '分'}) ・ 今回 +${S.sess.n}行 ・ 作業${m}分`;
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

/* ---------- 認識精度の測定・設定の比較(A/B) ---------- */

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

function renderAbHint(){
  const n = S.doc ? S.doc.segments.filter(s => s.proofed && s.text.trim()).length : 0;
  const sec = S.doc ? S.doc.segments.filter(s => s.proofed && s.text.trim()).reduce((a, s) => a + (s.end - s.start), 0) : 0;
  $('#abHint').textContent = !S.doc ? '文字起こしを開いてください' : n ? `対象: 校正済み${Math.min(n, 300)}行(音声 約${sec < 90 ? Math.round(sec) + '秒' : Math.round(sec / 60) + '分'})` : '校正済みの行がありません';
  $('#abGo').disabled = !n;
}

function renderAb(){
  if (!S.tools) return;
  if (!abVariants){ const m = $('#optModel').value; abVariants = [{ model: m, glossary: true }, { model: m, glossary: false }]; }
  $('#abRows').innerHTML = abVariants.map((v, i) => `<div class="row" data-i="${i}" style="margin-top:4px;flex-wrap:nowrap">
    <select class="abm" style="min-width:0;flex:1" aria-label="モデル">${S.tools.models.map(([val, l]) => `<option value="${esc(val)}"${val === v.model ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>
    <label class="lag"><input type="checkbox" class="abg"${v.glossary ? ' checked' : ''}>用語集</label>${abVariants.length > 1 ? '<button type="button" class="btn small" data-act="abdel" aria-label="この設定を外す">×</button>' : ''}</div>
    ${v.glossary ? `<textarea class="abt" rows="2" style="width:100%;margin:2px 0 0" placeholder="空欄=上の共通の用語集を使う。書くと、この設定だけその語を使います(改行かカンマ区切り)" aria-label="この設定だけの用語集">${esc(v.terms || '')}</textarea>
    <div class="row" style="margin:2px 0 0"><select class="abr" aria-label="名簿から足す" style="min-width:0"><option value="">名簿から足す…</option>${((S.roster && S.roster.groups) || []).map(g => `<option value="${esc(g.id)}">${esc(g.label)}</option>`).join('')}</select><span class="hint">${(() => { const t = glossTerms(v.terms); if (!t.length) return ''; const f = glossFit(t); return f.fit >= t.length ? t.length + '語' : t.length + '語のうち先頭' + f.fit + '語だけ効きます'; })()}</span></div>` : ''}`).join('');
  $('#abAdd').disabled = abVariants.length >= 4;
  renderAbHint();
}

async function loadEvals(){
  const id = S.docId; if (!id) { $('#abOut').innerHTML = ''; return; }
  let r; try { r = await api('/api/evals?id=' + encodeURIComponent(id)); } catch { return; }
  if (S.docId !== id) return;
  $('#abOut').innerHTML = r.items.slice(0, 3).map(x => {
    const best = Math.min(...x.variants.map(v => v.cer == null ? Infinity : v.cer));
    return `<div class="abres"><div class="hint">${esc(new Date(x.at).toLocaleString())} ・ ${x.lines}行${x.device ? ' ・ ' + devLabel(x.device) : ''}</div>
      <table class="acct"><tr><th>設定</th><th>CER</th><th>辞書後</th><th>置換/脱落/挿入</th><th>用語の誤挿入</th><th>用語ヒット</th></tr>
      ${x.variants.map(v => `<tr${v.cer === best ? ' class="best"' : ''}><td>${esc(v.label)}</td><td>${pct(v.cer)}</td><td>${pct(v.cerDict)}</td><td>${v.sub}/${v.del}/${v.ins}</td><td>${v.termExtra}</td><td>${v.termRef ? v.termHit + '/' + v.termRef : '—'}</td></tr>`).join('')}</table>
      <p class="hint" style="margin:3px 0 0">「辞書後」= 置換辞書を当てたあとのCER。「用語の誤挿入」= 正解に無いのに用語(用語集・辞書の正)が出た回数。</p>
      <details><summary class="hint">誤りが多い行</summary>${x.variants.map(v => `<div class="hint" style="margin-top:4px"><b>${esc(v.label)}</b></div>` + v.worst.slice(0, 5).map(w => `<div class="wl"><span class="mono">${fmtT(w.start)}</span> 正: ${esc(w.ref)}<br>機: ${esc(w.hyp) || '(認識なし)'}</div>`).join('')).join('')}</details></div>`;
  }).join('');
}

/* ---------- 保存データ(dataset/)への保管 ---------- */

async function loadDataset(){
  let r; try { r = await api('/api/dataset'); } catch { return; }
  S.arc = r; renderDataset();
  if (r.running && !arcPoll) arcPoll = setInterval(loadDataset, 2000);
  if (!r.running && arcPoll){ clearInterval(arcPoll); arcPoll = null; if (r.errors.length) toast('保管でエラー: ' + r.errors[0], 6000); }
}

function renderDataset(){
  const r = S.arc; if (!r) return;
  const t = r.totals, box = $('#arcOut');
  const cur = S.docId && r.docs.find(d => d.tid === S.docId);
  $('#arcStat').textContent = r.running ? `保管中 ${r.progress.done}/${r.progress.total}…` : (S.doc && S.doc.segments.some(g => g.proofed) ? (cur ? (cur.stale || S.arcDirty ? '保管: 更新あり' : '保管: 済') : '保管: まだ') : '');
  box.innerHTML = `<p class="accmain" style="margin:10px 0 0">正解の行 <b>${t.positive}</b>行 ・ 約${minStr(t.positiveSec)}</p>
    <p class="hint" style="margin:2px 0 0">人が消した行(負例) ${t.negative}行(約${minStr(t.negativeSec)}) ・ 聞き取れない ${t.unclear}行 ・ 保管した文字起こし ${t.docs}件 ・ 使用量 ${mb(t.audioBytes)}${t.stale ? ` ・ <b>更新あり ${t.stale}件</b>` : ''}</p>
    ${t.evalSec ? `<p class="hint" style="margin:2px 0 0">評価用(上の量には含めない) 約${minStr(t.evalSec)}。追加学習に使うときは、保管データの <b>split が eval</b> の行を必ず除いてください。</p>` : ''}
    <p class="hint" style="margin:2px 0 0">目安: 追加学習(LoRA)は、正解が<b>2〜3時間分</b>から。声紋登録は、話者1人あたり<b>数分〜十数分</b>から。</p>
    ${Object.keys(r.speakers).length ? '<details style="margin-top:6px"><summary class="hint">話者ごとの正解の量</summary>' + Object.entries(r.speakers).slice(0, 12).map(([k, v]) => `<div class="dsrow"><span>${esc(k)}</span><span>${minStr(v)}</span></div>`).join('') + '</details>' : ''}
    ${r.docs.length ? '<details style="margin-top:6px"><summary class="hint">文字起こしごと</summary>' + r.docs.map(d => `<div class="dsrow"><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(d.title || '無題')}${d.orphan ? '(元の文字起こしは削除済み)' : ''}</span><span>${d.positive}行 ・ ${mb(d.audioBytes)}${d.stale ? ' ・ 更新あり' : ''}${d.note ? ' ・ ' + esc(d.note) : ''}</span></div>`).join('') + '</details>' : ''}
    <p class="hint" style="margin:8px 0 0">保管先: このフォルダの <b>dataset/</b>(バックアップは、この中をコピーしてください)。話者の声・会話の内容が入るので、他人に渡す・クラウドに上げるときは、相手の同意と規約を確認してください。</p>`;
}

async function archiveNow(tid, quiet){
  if (!tid) return;
  try {
    await api('/api/archive', { body: { tid, full: $('#arcFull').checked } });
    S.arcDirty = false; loadDataset(); if (!quiet) toast('保管を始めました。音声の切り出しに、少し時間がかかります');
  } catch (e){ if (!quiet && e.code !== 'busy') toast(e.message); if (e.code === 'busy') S.arcDirty = true; }
}

function autoArchive(tid){ if ($('#arcAuto').checked && tid && S.arcDirty) archiveNow(tid, true); }
