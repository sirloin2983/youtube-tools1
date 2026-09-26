/* 「編集」2 カット のタブ(docs/edit-tool-design.md の 3・4・8)。app.js より先に読み込み、app.js が EditCut.create(host) で起動する。
   編集の内容(残す区間 = カットの正)はサーバーの transcripts/<id>.edit.json(GET/PUT /api/edit。rev で競合を見る)。
   区間はフレームの整数 [開始, 終了) で持ち、保存のときだけ秒(小数3桁)にする(浮動小数の丸めで1フレームずれないため)。
   タイムラインの区間・つまみ・字幕は DOM(見えている所だけ描く)、波形だけ canvas。
   たたき台の規則(行から・無音・時刻リスト・スタジオ)はここに書かない: 「行から」はサーバーの /api/edit/draft(pack.TRANSCRIPT_ROWS)、
   それ以外は cut2resolve の api/plan(結果の keepsSec で今の区間を置き換える)。行の「カット済」の規則は serve.py の edit_cut_flags と同じ(rowCutFlags) */
(function () {
'use strict';
const CUT_TOLERANCE_FRAMES = 0.75;   // serve.py の CUT_TOLERANCE_FRAMES と同じ
const SAVE_DELAY = 800;              // 操作のたびではなく、0.8 秒まとめて保存する(ドラッグ中は送らない)
const SNAP_PX = 8;                   // 吸い付く距離(画面の点)
const MIN_TICK_PX = 70;
const UNDO_MAX = 200;
const SILENCE_LEVEL = 40, SILENCE_MIN = 0.3;   // 波形(平方根の 0〜255)から無音の境目を出す(吸い付く先)

function create(h){
  const $ = h.$, esc = h.esc;
  const M = {
    docId: null, loading: 0, fps: null, dur: 0, total: 0, clips: [], rev: 0, origin: 'manual', pristine: true, off: '', offCode: '',
    sel: null, edge: null, io: { i: null, o: null }, undo: [], redo: [], dirty: false, saving: null, conflict: null, saveT: 0,
    peaks: null, peaksRate: 100, peaksAudio: true, peaksMsg: '', silence: [], planBeside: '', draftBusy: false, lastDraftSig: '',
    pps: 0, fit: true, snap: true, vis: [0, 0], mode: 'cut', mediaFor: null, drag: null, rowFlags: [], shown: false, seekingOut: false
  };
  const V = () => $('#cutPlayer');
  /* ---------- フレームと秒 ---------- */
  const f2s = f => f * M.fps[1] / M.fps[0];
  const sec3 = f => Math.round(f * M.fps[1] * 1000 / M.fps[0]) / 1000;   // 保存の形(フレームの境目の秒・小数3桁)
  /* 秒 → フレーム。pack の sec_to_frames と同じ丸め(ミリ秒に四捨五入 → フレームに 0.5 は大きい方へ)を整数で計算する */
  const s2f = t => { const ms = Math.floor(Number(t) * 1000 + 0.5), n = M.fps[0], d = M.fps[1]; return Math.floor((2 * ms * n + 1000 * d) / (2000 * d)); };
  const frameSec = () => M.fps[1] / M.fps[0];
  const fmtF = f => h.fmtCs(f2s(f));

  /* ---------- 区間の操作(すべてフレーム。[開始, 終了) ・時刻の順・重ならない) ---------- */
  const norm = cs => cs.filter(([a, b]) => b > a).sort((x, y) => x[0] - y[0]);
  function subtract(cs, a, b){
    const out = [];
    for (const [p, q] of cs){
      if (q <= a || p >= b){ out.push([p, q]); continue; }
      if (p < a) out.push([p, a]);
      if (q > b) out.push([b, q]);
    }
    return norm(out);
  }
  function addRange(cs, a, b){   // 足した範囲と重なる・接する区間だけ1つにまとめる(他の分割はそのまま)
    let lo = a, hi = b; const out = [];
    for (const [p, q] of cs){
      if (q < lo || p > hi) out.push([p, q]);
      else { lo = Math.min(lo, p); hi = Math.max(hi, q); }
    }
    out.push([lo, hi]);
    return norm(out);
  }
  const mergedCount = cs => { let n = 0, end = -1; for (const [a, b] of cs){ if (a > end) n++; end = b; } return n; };   // 接している区間(分割しただけ)は1つに数える(パックと同じ)
  const keptFrames = cs => cs.reduce((x, [a, b]) => x + b - a, 0);
  function gaps(){   // 削る区間(先頭・区間の間・末尾)
    const out = []; let cur = 0;
    for (const [a, b] of M.clips){ if (a > cur) out.push([cur, a]); cur = Math.max(cur, b); }
    if (cur < M.total) out.push([cur, M.total]);
    return out;
  }
  function clipAt(f){ let lo = 0, hi = M.clips.length; while (lo < hi){ const m = (lo + hi) >> 1; if (M.clips[m][1] <= f) lo = m + 1; else hi = m; } return lo < M.clips.length && M.clips[lo][0] <= f ? lo : -1; }
  function nextClip(f){ let lo = 0, hi = M.clips.length; while (lo < hi){ const m = (lo + hi) >> 1; if (M.clips[m][1] <= f) lo = m + 1; else hi = m; } return lo; }
  /* 元の動画の時刻(フレーム)→ カット後の時刻(フレーム)。削る区間の中なら、次の残す区間の頭 */
  function outFrame(f){
    let acc = 0;
    for (const [a, b] of M.clips){ if (f < a) return acc; if (f < b) return acc + f - a; acc += b - a; }
    return acc;
  }

  /* ---------- 行の「カット済」(serve.py の edit_cut_flags と同じ規則) ---------- */
  function rowCutFlags(segs){
    const tol = CUT_TOLERANCE_FRAMES * frameSec();
    const cs = M.clips.map(([a, b]) => [f2s(a), f2s(b)]), starts = cs.map(c => c[0]);
    const bis = x => { let lo = 0, hi = starts.length; while (lo < hi){ const m = (lo + hi) >> 1; if (starts[m] <= x) lo = m + 1; else hi = m; } return lo; };
    return segs.map(s => {
      const a = Number(s.start) || 0, b = Number(s.end) || 0;
      if (b - a <= 2 * tol){ const mid = (a + b) / 2, j = bis(mid) - 1; return !(j >= 0 && cs[j][0] <= mid && mid < cs[j][1]); }
      let kept = 0;
      for (let i = Math.max(0, bis(a) - 1); i < cs.length && cs[i][0] < b; i++) kept += Math.max(0, Math.min(b, cs[i][1]) - Math.max(a, cs[i][0]));
      return kept < tol;
    });
  }
  /* 編集の内容から、文書の行の cutState を付け直す(表示用。保存するのはサーバーが編集の内容から)。変わった行の番号を app.js に知らせる */
  function syncRowCuts(){
    const d = h.S.doc; if (!d || !M.fps || h.S.docId !== M.docId) return;
    const flags = rowCutFlags(d.segments), changed = [];
    d.segments.forEach((g, i) => { const was = g.cutState === 'cut'; if (flags[i] !== was){ if (flags[i]) g.cutState = 'cut'; else delete g.cutState; changed.push(i); } });
    M.rowFlags = flags;
    h.onCutMarks(changed);
    renderSubsSoon();
  }

  /* ---------- 元に戻す・変更 ---------- */
  function change(fn, opt = {}){
    if (!ready()) return false;
    const before = M.clips.map(c => c.slice());
    const next = fn(M.clips.map(c => c.slice()));
    if (!next || JSON.stringify(next) === JSON.stringify(before)) return false;
    M.undo.push({ clips: before, origin: M.origin }); if (M.undo.length > UNDO_MAX) M.undo.shift();
    M.redo = [];
    M.clips = next; M.origin = opt.origin || 'manual';
    afterChange();
    return true;
  }
  function afterChange(){
    M.pristine = false;
    if (M.sel && M.sel.kind === 'clip' && M.sel.i >= M.clips.length) M.sel = null;
    if (M.sel && M.sel.kind === 'gap') M.sel = null;
    syncRowCuts(); render(); scheduleSave();
  }
  function undo(){ const u = M.undo.pop(); if (!u) return; M.redo.push({ clips: M.clips, origin: M.origin }); M.clips = u.clips; M.origin = u.origin; M.sel = null; afterChange(); }
  function redo(){ const r = M.redo.pop(); if (!r) return; M.undo.push({ clips: M.clips, origin: M.origin }); M.clips = r.clips; M.origin = r.origin; M.sel = null; afterChange(); }

  /* ---------- 読み込み(文書を開いたとき) ---------- */
  function reset(docId){
    clearTimeout(M.saveT);
    Object.assign(M, { docId, fps: null, dur: 0, total: 0, clips: [], rev: 0, origin: 'manual', pristine: true, off: '', offCode: '', sel: null, edge: null,
      io: { i: null, o: null }, undo: [], redo: [], dirty: false, saving: null, conflict: null, saveT: 0, peaks: null, peaksAudio: true, peaksMsg: '', silence: [],
      planBeside: '', draftBusy: false, lastDraftSig: '', fit: true, mediaFor: null, drag: null, rowFlags: [] });
    const v = V(); v.pause(); v.removeAttribute('src'); v.load();
    renderSaveState();   // 競合の案内・保存の状態も初めに戻す(読み直したとき)
  }
  async function load(docId){
    reset(docId);
    const seq = ++M.loading;
    let ed = null, dr = null, drErr = null;
    await Promise.all([
      h.api('/api/edit?id=' + encodeURIComponent(docId)).then(r => { ed = r; }).catch(() => { ed = null; }),
      h.api('/api/edit/draft?id=' + encodeURIComponent(docId)).then(r => { dr = r; }).catch(e => { drErr = e; })
    ]);
    if (seq !== M.loading || M.docId !== docId) return;
    if (dr && dr.unavailable){ drErr = { message: dr.unavailable.message, code: dr.unavailable.code }; dr = null; }   // 動画が無い・ネットワーク上・音声だけ
    const e = ed && ed.edit;
    if (dr){ M.fps = dr.fps; M.dur = dr.durationSec; M.planBeside = dr.planBeside || ''; }
    else if (e){ M.fps = e.sources[0].fps; M.dur = e.sources[0].duration; }
    if (drErr) setOff(drErr.message, drErr.code || 'draft');
    if (!M.fps){ render(); h.onCutState(); return; }
    M.total = Math.max(1, Math.round(M.dur * M.fps[0] / M.fps[1]));
    if (e){
      M.rev = ed.rev; M.origin = e.origin || 'manual'; M.pristine = false;
      M.clips = norm(e.clips.map(c => [s2f(c.in), s2f(c.out)]));
      if (dr){   // 動画の長さが変わった(同じパスの動画を書き出し直した): 後ろの区間を切って知らせる
        const over = M.clips.some(([, b]) => b > M.total + 1);
        if (over){
          M.clips = norm(M.clips.map(([a, b]) => [a, Math.min(b, M.total)]));
          h.toast('動画の長さが、カットを決めたときと変わっています(書き出し直した?)。動画の終わりより後ろの区間は切りました', 8000, 'err');
          M.pristine = false; scheduleSave();
        } else M.clips = norm(M.clips.map(([a, b]) => [a, Math.min(b, M.total)]));
      }
      if (ed.broken) h.toast('保存されていたカットのファイルが読めませんでした。たたき台から始めます(壊れたファイルは残してあります)', 7000, 'err');
    } else if (dr){
      M.clips = norm(dr.keepsSec.map(([a, b]) => [s2f(a), s2f(b)])); M.origin = dr.base === 'rows' ? 'rows' : 'all'; M.pristine = true; M.rev = ed ? ed.rev : 0;
      if (ed && ed.broken) h.toast('保存されていたカットのファイルが読めませんでした。たたき台から始めます(壊れたファイルは残してあります)', 7000, 'err');
    }
    M.lastDraftSig = rowSig();
    syncRowCuts(); render(); h.onCutState();
    if (M.shown) onShown();
  }
  function setOff(msg, code){ M.off = msg; M.offCode = code; }
  const ready = () => !!(M.fps && M.docId && h.S.docId === M.docId);
  const editable = () => ready() && !M.off;
  const rowSig = () => { const d = h.S.doc; return d ? d.segments.map(g => `${g.start},${g.end},${g.cutState === 'cut' ? 1 : 0},${String(g.text || '').trim() ? 1 : 0}`).join(';') : ''; };

  /* ---------- 保存(0.8 秒まとめて PUT・rev で競合を見る) ---------- */
  function scheduleSave(){ M.dirty = true; clearTimeout(M.saveT); if (!M.drag) M.saveT = setTimeout(save, SAVE_DELAY); renderSaveState(); }
  function body(baseRev){
    return { baseRev, edit: { sources: [{ fps: M.fps, duration: Math.round(M.dur * 1000) / 1000 }], clips: M.clips.map(([a, b]) => ({ src: 0, in: sec3(a), out: sec3(b) })), origin: M.origin } };
  }
  function save(force){
    clearTimeout(M.saveT);
    if (M.saving) return M.saving;
    if (!M.dirty || !ready() || (M.conflict && !force)) return Promise.resolve(!M.dirty);
    const id = M.docId;
    M.saving = (async () => {
      while (M.dirty && M.docId === id){
        M.dirty = false; renderSaveState();
        const baseRev = force ? M.conflict.rev : M.rev;
        try {
          const r = await h.api('/api/edit?id=' + encodeURIComponent(id), { method: 'PUT', body: body(baseRev) });
          if (M.docId !== id) return false;
          M.rev = r.rev; M.conflict = null; force = false;
          h.onCutSaved(r);
        } catch (e){
          if (M.docId !== id) return false;
          M.dirty = true;
          if (e.status === 409 && e.data && Number.isInteger(e.data.rev)){ M.conflict = { rev: e.data.rev }; h.toast('別のタブか窓で、先にカットが保存されています。カットのタブの案内から選んでください', 7000, 'err'); }
          else { h.toast('カットを保存できませんでした: ' + e.message, 5000, 'err'); clearTimeout(M.saveT); M.saveT = setTimeout(save, 5000); }
          renderSaveState();
          return false;
        }
      }
      return !M.dirty;
    })().finally(() => { M.saving = null; renderSaveState(); });
    return M.saving;
  }
  async function flush(){
    if (M.drag) endDrag(true);
    if (!M.dirty) return !(M.saving && !(await M.saving));
    return save();
  }
  async function reloadFromServer(){ const id = M.docId; M.conflict = null; M.dirty = false; await load(id); h.toast('保存されているカットを読み直しました', 3000, 'ok'); }
  function renderSaveState(){
    $('#cutConflict').hidden = !M.conflict;
    const el = $('#cutSaveSt');
    const [t, k] = M.conflict ? ['カットが競合しています', 'err'] : M.saving ? ['カットを保存中…', 'busy'] : M.dirty ? ['未保存…', ''] : M.rev ? ['カットを保存しました', 'ok'] : ['', ''];
    el.textContent = t; el.setAttribute('data-state', k);
    h.onCutState();
  }

  /* ---------- たたき台(規則はサーバー・cut2resolve) ---------- */
  function confirmReplace(){
    if (M.pristine || !M.undo.length && M.origin !== 'manual') return Promise.resolve(true);
    return h.confirm('今のカットを、たたき台で置き換えますか?', '手で直したカットがあります。置き換えても「元に戻す」(Ctrl+Z)で戻せます。', '置き換える');
  }
  function applyKeeps(keepsSec, origin, label){
    const cs = norm((keepsSec || []).map(([a, b]) => [s2f(a), Math.min(s2f(b), M.total)]));
    if (!cs.length) return h.toast('残る区間がありませんでした(条件を見直してください)', 5000, 'err');
    change(() => cs, { origin }) ? h.toast(`${label}のたたき台にしました(残す ${mergedCount(cs)}区間)。「元に戻す」で戻せます`, 5000, 'ok') : h.toast('今のカットと同じでした', 3000);
  }
  async function draftRows(){
    if (!editable() || M.draftBusy) return;
    if (!(await confirmReplace())) return;
    M.draftBusy = true; renderTools();
    try {
      if (!(await h.saveDoc())) return h.toast('文字起こしの保存が終わっていません。少し待ってから、もう一度押してください', 5000, 'err');
      const r = await h.api('/api/edit/draft?id=' + encodeURIComponent(M.docId));
      if (r.unavailable) return h.toast(r.unavailable.message, 6000, 'err');
      applyKeeps(r.keepsSec, 'rows', r.base === 'rows' ? '文字起こしの行から' : '(残す行が無いので)動画全体');
    } catch (e){ h.toast('たたき台を作れませんでした: ' + e.message, 6000, 'err'); }
    finally { M.draftBusy = false; renderTools(); }
  }
  async function draftC2R(kind){
    if (!editable() || M.draftBusy) return;
    if (!h.c2rBase()) return h.toast('このたたき台は cut2resolve を使います。入口(start-all.bat)から開いてください', 6000, 'err');
    const src = String(h.S.doc.sourcePath || '');
    let spec;
    if (kind === 'silence'){
      const num = (id, dv) => { const v = Number($(id).value); return Number.isFinite(v) ? v : dv; };
      spec = { video: src, mode: 'silence', silence: { noise: num('#cutNoise', -35), min: num('#cutSilMin', 0.6), pad: num('#cutSilPad', 0.15) }, dropCutRows: false };   // 最短の長さは cut2resolve の既定(ごく短い切れ端を残さない)
    } else if (kind === 'list'){
      const text = $('#cutListText').value.trim();
      if (!text) return h.toast('残す区間を1行に1つ書いてください(例: 0:05 0:20)', 5000);
      spec = { video: src, mode: 'list', listKind: 'keep', listText: text, minLen: 0, dropCutRows: false };
    } else {
      if (!M.planBeside) return;
      spec = { video: src, plan: M.planBeside, mode: 'keep', keepSource: 'plan', dropCutRows: false };
    }
    if (!(await confirmReplace())) return;
    M.draftBusy = true; renderTools();
    const label = { silence: '無音', list: '時刻リスト', plan: 'スタジオ(.cut-plan.json)' }[kind];
    try {
      const j = await h.c2rApi('api/plan', { body: { spec, output: {} } });
      h.toast(label + 'のたたき台を計算しています…', 3000);
      const res = await h.c2rWait(j.job);
      if (h.S.docId !== M.docId) return;
      for (const w of (res.warnings || []).slice(0, 2)) h.toast(w, 6000);
      applyKeeps(res.keepsSec || [], kind, label);
      document.querySelectorAll('#tabCut details.pop[open]').forEach(d => { d.open = false; });
    } catch (e){ h.toast(label + 'のたたき台を作れませんでした: ' + (e.code === 'busy' ? 'cut2resolve で別の処理が動いています。終わってから、もう一度押してください' : e.message), 7000, 'err'); }
    finally { M.draftBusy = false; renderTools(); }
  }
  /* 開いたまま(まだ手で直していない)下書きは、行が変わったら「行から」を作り直す(以前の「カットとパック」と同じ結果に保つ) */
  function docChanged(){
    if (!ready()) return;
    if (M.pristine && M.origin === 'rows' || M.pristine && M.origin === 'all'){
      const sig = rowSig();
      if (sig !== M.lastDraftSig){ clearTimeout(docChanged.t); docChanged.t = setTimeout(async () => {
        if (!M.pristine || M.docId !== h.S.docId) return;
        try {
          const r = await h.api('/api/edit/draft?id=' + encodeURIComponent(M.docId));
          if (!M.pristine || M.docId !== h.S.docId || r.unavailable) return;
          M.clips = norm(r.keepsSec.map(([a, b]) => [s2f(a), s2f(b)])); M.origin = r.base === 'rows' ? 'rows' : 'all'; M.lastDraftSig = rowSig();
          syncRowCuts(); render(); h.onCutState();
        } catch {}
      }, 1500); }
      return;
    }
    syncRowCuts();   // 行の時刻が変わった → 行の「カット済」を付け直す(カットはそのまま)
  }
  /* 1 文字起こし のタブの行の「削る/戻す」(行の時間を削る区間にする/残す区間にする) */
  function rowsCut(idxs, cut){
    const segs = h.S.doc.segments;
    return change(cs => {
      for (const i of idxs){ const g = segs[i]; if (!g) continue; const a = Math.max(0, s2f(g.start)), b = Math.min(M.total, Math.max(s2f(g.end), a + 1)); cs = cut ? subtract(cs, a, b) : addRange(cs, a, b); }
      return cs;
    });
  }

  /* ---------- 描画 ---------- */
  const scroller = () => $('#tlScroll');
  function viewW(){ return Math.max(200, scroller().clientWidth); }
  function fitPps(){ return viewW() / Math.max(frameSec(), M.dur || 1); }
  function maxPps(){ return 14 / frameSec(); }   // 1フレームが 14 点(つまみを1フレームずつ動かせる)
  const X = f => f2s(f) * M.pps;
  let rq = 0;
  function render(){ if (!rq) rq = requestAnimationFrame(() => { rq = 0; renderNow(); }); }
  function renderNow(){
    const tab = $('#tabCut');
    const off = $('#cutOff'), noVideo = !ready() || !!M.off;
    off.hidden = !(M.off || (!ready() && h.S.doc));
    off.textContent = M.off ? M.off + '。1 文字起こし のタブは今までどおり使えます' : (!ready() && h.S.doc ? 'カットの準備をしています…' : '');
    tab.classList.toggle('tt-cut-disabled', noVideo);
    renderTools(); renderStatus(); renderSubsSoon();
    if (!ready() || !M.shown) return;
    if (M.fit || !M.pps) M.pps = fitPps();
    M.pps = Math.min(Math.max(M.pps, fitPps()), maxPps());
    const cw = M.fit ? viewW() : Math.max(viewW(), Math.ceil(M.dur * M.pps));   // 全体のときは、ちょうど1画面(横にずらせない)
    $('#tlContent').style.width = cw + 'px';
    if (M.fit) scroller().scrollLeft = 0;
    renderRange();
  }
  /* 見えている所(前後に1画面ずつ)だけ描く(区間・字幕が数千あっても重くしない) */
  const clipHTML = (a, b, i) => `<div class="tt-k" data-i="${i}" style="left:${X(a)}px;width:${Math.max(1, X(b) - X(a))}px" title="残す区間 ${fmtF(a)}〜${fmtF(b)}(${fmtF(b - a)})"></div>`;
  const gapsHTML = () => gaps().filter(([a, b]) => !(b < M.vis[0] || a > M.vis[1])).map(([a, b]) =>
    `<div class="tt-x" data-a="${a}" data-b="${b}" style="left:${X(a)}px;width:${Math.max(1, X(b) - X(a))}px" title="削る区間 ${fmtF(a)}〜${fmtF(b)}。選んで Del で戻す"></div>`).join('');
  function renderRange(){
    const sc = scroller(), l = sc.scrollLeft, w = viewW();
    const f0 = Math.max(0, s2f((l - w) / M.pps)), f1 = s2f((l + 2 * w) / M.pps);
    M.vis = [f0, f1];
    renderRuler(l, w);
    let html = '';
    M.clips.forEach(([a, b], i) => { if (!(b < f0 || a > f1)) html += clipHTML(a, b, i); });
    $('#tlVideo').innerHTML = html + gapsHTML();
    renderSel(true);
    const segs = h.S.doc ? h.S.doc.segments : [];
    let sh = '';
    for (let i = 0; i < segs.length; i++){
      const g = segs[i], a = s2f(g.start), b = s2f(g.end);
      if (b < f0 || a > f1 || !String(g.text || '').trim()) continue;
      sh += `<div class="tt-s${M.rowFlags[i] ? ' cut' : ''}" data-i="${i}" style="left:${X(a)}px;width:${Math.max(2, X(b) - X(a) - 2)}px" title="${esc(fmtF(a))} ${esc(g.text)}">${esc(g.text)}</div>`;
    }
    $('#tlSubs').innerHTML = sh;
    const io = $('#tlIO'), i0 = M.io.i, o0 = M.io.o;
    io.hidden = i0 === null && o0 === null;
    if (!io.hidden){
      const a = i0 !== null ? i0 : o0, b = o0 !== null ? o0 : i0;
      io.style.left = X(Math.min(a, b)) + 'px'; io.style.width = Math.max(1, Math.abs(X(b) - X(a))) + 'px';
      io.innerHTML = (i0 !== null ? `<b class="i" style="left:${X(i0) - X(Math.min(a, b))}px">I</b>` : '') + (o0 !== null ? `<b class="o" style="left:${X(o0) - X(Math.min(a, b))}px">O</b>` : '');
    }
    drawWave(); moveHead();
  }
  function scrolled(){
    const l = scroller().scrollLeft, w = viewW(), f0 = s2f(l / M.pps), f1 = s2f((l + w) / M.pps), m = s2f(w / 2 / M.pps);
    if (f0 - m < M.vis[0] && M.vis[0] > 0 || f1 + m > M.vis[1] && M.vis[1] < M.total) renderRange();
    else drawWave();
  }
  function renderSel(quiet){
    const box = $('#tlVideo');
    box.querySelectorAll('.sel').forEach(e => e.classList.remove('sel'));
    box.querySelectorAll('.tt-h').forEach(e => e.remove());
    if (M.sel && M.sel.kind === 'clip'){
      const el = box.querySelector(`.tt-k[data-i="${M.sel.i}"]`);
      if (el){ el.classList.add('sel'); el.insertAdjacentHTML('beforeend',
        `<i class="tt-h in${M.edge === 'in' ? ' on' : ''}" data-edge="in" title="始まりをドラッグ(1フレーム単位。Alt で吸い付かない)"></i><i class="tt-h out${M.edge === 'out' ? ' on' : ''}" data-edge="out" title="終わりをドラッグ(1フレーム単位。Alt で吸い付かない)"></i>`); }
    } else if (M.sel && M.sel.kind === 'gap'){
      const el = [...box.querySelectorAll('.tt-x')].find(x => Number(x.dataset.a) === M.sel.a); if (el) el.classList.add('sel');
    }
    if (!quiet){ renderStatus(); renderTools(); }
  }
  function tickStep(){
    const fs = frameSec(), c = [fs, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];
    for (const s of c) if (s * M.pps >= MIN_TICK_PX) return s;
    return 7200;
  }
  function renderRuler(l, w){
    const st = tickStep(), t0 = Math.max(0, Math.floor((l - w) / M.pps / st) * st), t1 = Math.min(M.dur, (l + 2 * w) / M.pps);
    let html = '';
    for (let t = t0, n = 0; t <= t1 + 1e-9 && n < 2000; t += st, n++){
      const lab = st < 1 ? h.fmtCs(t) : h.fmtT(t);
      html += `<span class="tt-tick" style="left:${t * M.pps}px">${lab}</span>`;
    }
    $('#tlRuler').innerHTML = html;
  }
  /* 波形(canvas は見えている幅だけ。横にずらしたら描き直す) */
  function drawWave(){
    const cv = $('#tlWave'), box = $('#tlAudio'), sc = scroller();
    const w = viewW(), hgt = box.clientHeight || 64, dpr = window.devicePixelRatio || 1;
    cv.style.left = sc.scrollLeft + 'px'; cv.style.width = w + 'px'; cv.style.height = hgt + 'px';
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(hgt * dpr)){ cv.width = Math.round(w * dpr); cv.height = Math.round(hgt * dpr); }
    const cx = cv.getContext('2d'); cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, w, hgt);
    const cs = getComputedStyle(document.documentElement);
    const col = (cs.getPropertyValue('--accent') || '#5b5bd6').trim(), dim = (cs.getPropertyValue('--ink-4') || '#999').trim();
    if (!M.peaks){ cx.fillStyle = dim; cx.font = '12px sans-serif'; cx.fillText(M.peaksMsg || (M.peaksAudio ? '音の波形を読み込んでいます…' : '音声がありません'), 8, hgt / 2 + 4); return; }
    const p = M.peaks, rate = M.peaksRate, mid = hgt / 2, l = sc.scrollLeft;
    const cutFr = []; for (const [a, b] of gaps()) cutFr.push([f2s(a), f2s(b)]);
    let gi = 0;
    for (let x = 0; x < w; x++){
      const t0 = (l + x) / M.pps, t1 = (l + x + 1) / M.pps;
      let i0 = Math.floor(t0 * rate), i1 = Math.max(i0 + 1, Math.ceil(t1 * rate)), v = 0;
      if (i0 >= p.length) break;
      for (let i = i0; i < i1 && i < p.length; i++) if (p[i] > v) v = p[i];
      while (gi < cutFr.length && cutFr[gi][1] <= t0) gi++;
      const inCut = gi < cutFr.length && cutFr[gi][0] <= t0;
      const hh = Math.max(1, v / 255 * (mid - 2));
      cx.fillStyle = inCut ? dim : col; cx.globalAlpha = inCut ? 0.55 : 0.9;
      cx.fillRect(x, mid - hh, 1, hh * 2);
    }
    cx.globalAlpha = 1;
  }
  async function loadPeaks(){
    const id = M.docId;
    M.peaksMsg = '';
    for (let n = 0; n < 1200 && M.docId === id; n++){
      let r;
      try { r = await fetch(h.apiUrl('/api/peaks?id=' + encodeURIComponent(id)), { cache: 'no-store' }); } catch { M.peaksMsg = '音の波形を読み込めませんでした'; break; }
      if (M.docId !== id) return;
      if (r.status === 202){ const j = await r.json().catch(() => ({})); M.peaksMsg = j.message || '音の波形を作っています…'; drawWave(); await new Promise(res => setTimeout(res, 1000)); continue; }
      if (!r.ok){ const j = await r.json().catch(() => ({})); M.peaksMsg = '音の波形を作れませんでした' + (j.message ? ': ' + j.message : ''); break; }
      M.peaksRate = Number(r.headers.get('X-Peaks-Rate')) || 100; M.peaksAudio = r.headers.get('X-Peaks-Audio') !== '0';
      M.peaks = new Uint8Array(await r.arrayBuffer());
      if (!M.peaksAudio){ M.peaks = null; M.peaksMsg = '音声がありません'; }
      else findSilence();
      break;
    }
    if (M.docId === id) drawWave();
  }
  function findSilence(){   // 無音の境目(吸い付く先)
    const p = M.peaks, rate = M.peaksRate, out = []; let st = -1;
    for (let i = 0; i <= p.length; i++){
      const q = i < p.length && p[i] < SILENCE_LEVEL;
      if (q && st < 0) st = i;
      else if (!q && st >= 0){ if ((i - st) / rate >= SILENCE_MIN){ out.push(s2f(st / rate), s2f(i / rate)); } st = -1; }
    }
    M.silence = out;
  }
  function moveHead(){
    if (!ready()) return;
    const t = V().currentTime || 0, x = t * M.pps;
    $('#tlHead').style.left = x + 'px';
    const f = s2f(t);
    $('#cutTimeSrc').textContent = h.fmtCs(t);
    $('#cutTimeOut').textContent = fmtF(outFrame(f));
    $('#cutTotal').textContent = fmtF(keptFrames(M.clips));
    showCaption(t);
  }
  function keepHeadVisible(){
    const sc = scroller(), x = (V().currentTime || 0) * M.pps, w = viewW();
    if (x < sc.scrollLeft || x > sc.scrollLeft + w - 20){ sc.scrollLeft = Math.max(0, x - w * 0.2); }
  }
  let capIdx = -2;
  function showCaption(t){   // プレビューの字幕(Resolve の Text+ のおおよその見え方。カット後では削った行を出さない)
    const segs = h.S.doc ? h.S.doc.segments : []; let idx = -1;
    for (let i = 0; i < segs.length; i++){ const g = segs[i]; if (g.start <= t && t < g.end && String(g.text || '').trim() && !(M.mode === 'cut' && M.rowFlags[i])){ idx = i; break; } if (g.start > t) break; }
    if (idx === capIdx) return;
    capIdx = idx;
    const el = $('#cutCaption'); el.textContent = idx >= 0 ? segs[idx].text : ''; el.hidden = idx < 0;
    document.querySelectorAll('#cutSubs .tt-csub.now').forEach(r => r.classList.remove('now'));
    const row = idx >= 0 ? document.querySelector(`#cutSubs .tt-csub[data-i="${idx}"]`) : null;
    if (row){ row.classList.add('now'); if (!V().paused){ const box = $('#cutSubs'), rt = row.offsetTop - box.offsetTop; if (rt < box.scrollTop || rt > box.scrollTop + box.clientHeight - 40) box.scrollTop = rt - 40; } }
  }
  function renderStatus(){
    const st = $('#cutStatus');
    if (!ready()){ st.innerHTML = ''; return; }
    const n = mergedCount(M.clips), kf = keptFrames(M.clips);
    let sel = '';
    if (M.sel && M.sel.kind === 'clip' && M.clips[M.sel.i]){ const [a, b] = M.clips[M.sel.i]; sel = `選んだ区間: <b>${M.sel.i + 1}</b> <span class="mono">${fmtF(a)} – ${fmtF(b)}</span>(${h.fmtCs(f2s(b - a))}秒)`; }
    else if (M.sel && M.sel.kind === 'gap'){ sel = `選んだ削る区間: <span class="mono">${fmtF(M.sel.a)} – ${fmtF(M.sel.b)}</span>(Del で戻す)`; }
    const snapTo = M.snap ? '吸い付く先: 字幕の行の端・無音の境目・再生位置・隣の区間の端(Alt を押している間は吸い付かない)' : '吸着: 切';
    st.innerHTML = `<span>残す <b>${n}区間</b></span><span>カット後 <b class="mono">${fmtF(kf)}</b> / 元 <span class="mono">${h.fmtCs(M.dur)}</span></span>${sel ? `<span>${sel}</span>` : ''}<span class="hint">${snapTo}</span>` +
      (M.origin && M.pristine ? `<span class="hint">(${M.origin === 'rows' ? '文字起こしの行から作った下書き' : '動画全体の下書き'}。手で直すと保存します)</span>` : '');
  }
  function renderTools(){
    const ok = editable(), c2r = !!h.c2rBase(), busy = M.draftBusy;
    $('#cutUndo').disabled = !ok || !M.undo.length; $('#cutRedo').disabled = !ok || !M.redo.length;
    ['#cutSplit', '#cutDel', '#cutIO', '#cutZoomIn', '#cutZoomOut', '#cutZoomFit', '#cutPlay'].forEach(s => { $(s).disabled = !ok; });
    $('#cutDraftRows').disabled = !ok || busy;
    const why = c2r ? '' : '(cut2resolve を使います。入口から開いたときだけ)';
    for (const s of ['#cutDraftSilence', '#cutDraftList']){ const d = $(s), sm = d.querySelector('summary'); sm.classList.toggle('disabled', !ok || !c2r || busy); sm.title = why || sm.dataset.title; if (!ok || !c2r) d.open = false; }
    const pb = $('#cutDraftPlan'); pb.hidden = !M.planBeside; pb.disabled = !ok || !c2r || busy; pb.title = why || ('動画の隣の ' + String(M.planBeside).split(/[\\/]/).pop() + '(スタジオなどの残す区間の指定)から');
    $('#cutIO').disabled = !ok || M.io.i === null || M.io.o === null || M.io.i === M.io.o;
    $('#cutSnap').checked = M.snap;
    $('#cutModeSrc').setAttribute('aria-pressed', M.mode === 'src' ? 'true' : 'false'); $('#cutModeCut').setAttribute('aria-pressed', M.mode === 'cut' ? 'true' : 'false');
    $('#cutModePill').textContent = M.mode === 'cut' ? 'カット後の見え方' : '元の動画';
  }
  /* 右の字幕の一覧(押すとその位置へ・行ごとの「削る/戻す」。文字は直さない) */
  let sq = 0;
  function renderSubsSoon(){ if (!sq) sq = requestAnimationFrame(() => { sq = 0; renderSubs(); }); }
  function renderSubs(){
    const box = $('#cutSubs'), d = h.S.doc;
    if (!d || !M.shown){ return; }
    const rows = d.segments.map((g, i) => [g, i]).filter(([g]) => String(g.text || '').trim());
    if (!rows.length){ box.innerHTML = `<p class="hint tt-csub-empty">${d.model ? '文字のある行がありません' : 'まだ文字起こししていません(1 文字起こし のタブから文字起こしできます)。カットは文字起こしをしなくても決められます'}</p>`; capIdx = -2; return; }
    const ok = editable();
    box.innerHTML = rows.map(([g, i]) => { const c = !!M.rowFlags[i];
      return `<div class="tt-csub${c ? ' cut' : ''}" data-i="${i}" role="listitem"><button type="button" class="tt-csub-go" data-act="go" title="この行の頭へ"><span class="mono">${h.fmtCs(g.start)}</span><span class="tx">${esc(g.text)}</span></button>` +
        `<button type="button" class="btn ghost small" data-act="cutrow"${ok ? '' : ' disabled'} title="${c ? 'この行の時間を残す区間に戻します' : 'この行の時間を削る区間にします'}">${c ? '戻す' : '削る'}</button></div>`; }).join('');
    capIdx = -2; if (ready()) showCaption(V().currentTime || 0);
  }

  /* ---------- 再生(カット後は削る区間を飛ばす) ---------- */
  function ensureMedia(){
    if (!M.docId || M.mediaFor === M.docId || M.off) return;
    M.mediaFor = M.docId;
    const v = V(); v.src = h.apiUrl('/media?id=' + encodeURIComponent(M.docId));
    v.addEventListener('loadedmetadata', () => { const t = h.player().currentTime || 0; if (t > 0) v.currentTime = t; }, { once: true });
    loadPeaks();
  }
  let loopOn = false;
  function tick(){
    if (!ready()) return;
    const v = V();
    if (M.mode === 'cut' && !v.paused && M.clips.length && !M.seekingOut){
      const f = s2f(v.currentTime), i = clipAt(f);
      if (i < 0){
        const n = nextClip(f);
        if (n < M.clips.length){ M.seekingOut = true; v.currentTime = f2s(M.clips[n][0]) + 0.0005; }
        else { v.pause(); v.currentTime = Math.max(0, f2s(M.clips[M.clips.length - 1][1]) - frameSec()); }
      }
    }
    moveHead(); if (!v.paused) keepHeadVisible();
  }
  function loop(){
    const v = V();
    tick();
    if (!v.paused){ if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(loop); else requestAnimationFrame(loop); }
    else loopOn = false;
  }
  function startLoop(){ if (!loopOn){ loopOn = true; loop(); } }
  function togglePlay(){
    const v = V(); if (!ready()) return;
    if (v.paused){
      if (M.mode === 'cut' && M.clips.length){   // 削る区間の中・最後の区間より後ろからは、次の残す区間の頭から
        const f = s2f(v.currentTime); if (clipAt(f) < 0){ const n = nextClip(f); v.currentTime = f2s(M.clips[n < M.clips.length ? n : 0][0]) + 0.0005; }
      }
      v.play().catch(() => {});
    } else v.pause();
  }
  function seekTo(t, keep){ const v = V(); v.currentTime = Math.max(0, Math.min(M.dur, t)); if (!keep) M.seekingOut = false; moveHead(); keepHeadVisible(); }
  const stepFrames = n => { const v = V(); v.pause(); seekTo(f2s(Math.max(0, Math.min(M.total, s2f(v.currentTime) + n))) + 0.0005); };

  /* ---------- 操作 ---------- */
  const headFrame = () => Math.max(0, Math.min(M.total, s2f(V().currentTime || 0)));
  function split(){
    const f = headFrame(), i = clipAt(f);
    if (i < 0 || f <= M.clips[i][0] || f >= M.clips[i][1]) return h.toast('残す区間の中に再生位置(赤い線)を置いてから分割します', 3000);
    change(cs => { const [a, b] = cs[i]; cs.splice(i, 1, [a, f], [f, b]); return cs; }) && (M.sel = { kind: 'clip', i: i + 1 }, M.edge = 'in', render());
  }
  function delOrRestore(){
    if (!M.sel) return h.toast('区間を押して選んでから(削る区間を選ぶと、戻せます)', 3000);
    if (M.sel.kind === 'clip'){ const i = M.sel.i; change(cs => { cs.splice(i, 1); return cs; }); M.sel = null; render(); }
    else { const { a, b } = M.sel; change(cs => addRange(cs, a, b)); M.sel = null; render(); }
  }
  function cutIO(){
    const { i, o } = M.io; if (i === null || o === null || i === o) return h.toast('I で始まり、O で終わりを決めてから(X)', 3000);
    const a = Math.min(i, o), b = Math.max(i, o);
    if (change(cs => subtract(cs, a, b))){ M.io = { i: null, o: null }; render(); }
  }
  function nudgeEdge(dir){
    if (!M.sel || M.sel.kind !== 'clip' || !M.edge) return h.toast('区間を選んで、動かす端(始まり/終わり)を押してから', 3000);
    const i = M.sel.i, e = M.edge;
    change(cs => { const f = cs[i][e === 'in' ? 0 : 1] + dir; return setEdge(cs, i, e, f) ? cs : null; });
  }
  function setEdge(cs, i, e, f){   // 隣の区間を越えない・長さは1フレーム以上
    const c = cs[i]; if (!c) return false;
    if (e === 'in'){ const lo = i > 0 ? cs[i - 1][1] : 0; f = Math.max(lo, Math.min(f, c[1] - 1)); if (f === c[0]) return false; c[0] = f; }
    else { const hi = i < cs.length - 1 ? cs[i + 1][0] : M.total; f = Math.min(hi, Math.max(f, c[0] + 1)); if (f === c[1]) return false; c[1] = f; }
    return true;
  }
  function zoom(k, anchorX){
    if (!ready()) return;
    const sc = scroller(), ax = anchorX === undefined ? viewW() / 2 : anchorX, t = (sc.scrollLeft + ax) / M.pps;
    M.fit = false; M.pps = Math.min(Math.max(M.pps * k, fitPps()), maxPps());
    if (M.pps <= fitPps() + 1e-9) M.fit = true;
    renderNow(); sc.scrollLeft = Math.max(0, t * M.pps - ax); renderRange();
  }
  /* 吸い付く先(フレーム): 字幕の行の端・無音の境目・再生位置・他の区間の端 */
  function snapTargets(exceptI){
    const out = [headFrame()], segs = h.S.doc ? h.S.doc.segments : [];
    for (const g of segs) if (String(g.text || '').trim()){ out.push(s2f(g.start), s2f(g.end)); }
    out.push(...M.silence);
    M.clips.forEach(([a, b], i) => { if (i !== exceptI){ out.push(a, b); } });
    return out;
  }
  function snapFrame(f, targets, alt){
    if (!M.snap || alt) return { f, snapped: null };
    const lim = SNAP_PX / M.pps / frameSec();
    let best = null, bd = Infinity;
    for (const t of targets){ const dd = Math.abs(t - f); if (dd < bd){ bd = dd; best = t; } }
    return best !== null && bd <= lim ? { f: best, snapped: best } : { f, snapped: null };
  }
  function frameFromEvent(e){ const r = $('#tlContent').getBoundingClientRect(); return Math.max(0, Math.min(M.total, Math.round((e.clientX - r.left) / M.pps / frameSec()))); }

  /* ---------- ドラッグ(区間の端) ---------- */
  function startDrag(e, i, edge){
    e.preventDefault(); e.stopPropagation();
    M.sel = { kind: 'clip', i }; M.edge = edge;
    M.drag = { i, edge, start: M.clips[i][edge === 'in' ? 0 : 1], before: M.clips.map(c => c.slice()), origin: M.origin, targets: snapTargets(i), pid: e.pointerId };
    try { e.target.setPointerCapture(e.pointerId); } catch {}
    document.querySelectorAll('#tlVideo .tt-h').forEach(x => x.classList.toggle('on', x.dataset.edge === edge));
  }
  function moveDrag(e){
    const d = M.drag; if (!d) return;
    const raw = frameFromEvent(e), s = snapFrame(raw, d.targets, e.altKey);
    const cs = M.clips.map(c => c.slice());
    if (setEdge(cs, d.i, d.edge, s.f) || cs[d.i][d.edge === 'in' ? 0 : 1] !== M.clips[d.i][d.edge === 'in' ? 0 : 1]) M.clips = cs;
    const cur = M.clips[d.i][d.edge === 'in' ? 0 : 1], dlt = cur - d.start;
    const tip = $('#tlTip'); tip.hidden = false; tip.style.left = X(cur) + 'px';
    tip.textContent = `${d.edge === 'in' ? '始まり' : '終わり'} ${fmtF(cur)}(${dlt >= 0 ? '+' : ''}${dlt}フレーム)`;
    const sn = $('#tlSnap'); sn.hidden = s.snapped === null || cur !== s.snapped; if (!sn.hidden) sn.style.left = X(cur) + 'px';
    const el = document.querySelector(`#tlVideo .tt-k[data-i="${d.i}"]`), [a, b] = M.clips[d.i];
    if (el){ el.style.left = X(a) + 'px'; el.style.width = Math.max(1, X(b) - X(a)) + 'px'; }
    document.querySelectorAll('#tlVideo .tt-x').forEach(x => x.remove());
    $('#tlVideo').insertAdjacentHTML('beforeend', gapsHTML());
    renderStatus();
  }
  function endDrag(cancel){
    const d = M.drag; if (!d) return;
    M.drag = null; $('#tlTip').hidden = true; $('#tlSnap').hidden = true;
    if (cancel === true){ M.clips = d.before; render(); return; }
    if (JSON.stringify(d.before) !== JSON.stringify(M.clips)){
      M.undo.push({ clips: d.before, origin: d.origin }); if (M.undo.length > UNDO_MAX) M.undo.shift(); M.redo = []; M.origin = 'manual';
      afterChange();
    } else render();
  }

  /* ---------- イベント ---------- */
  function bind(){
    const sc = scroller();
    sc.addEventListener('scroll', () => { if (ready()) { if (!bind.q) bind.q = requestAnimationFrame(() => { bind.q = 0; scrolled(); }); } });
    sc.addEventListener('wheel', e => { if (!(e.ctrlKey || e.metaKey) || !ready()) return; e.preventDefault(); const r = sc.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.25 : 0.8, e.clientX - r.left); }, { passive: false });
    $('#tlContent').addEventListener('pointerdown', e => {
      if (!editable() || e.button !== 0) return;
      const hd = e.target.closest('.tt-h');
      if (hd){ const k = hd.closest('.tt-k'); startDrag(e, Number(k.dataset.i), hd.dataset.edge); return; }
      const k = e.target.closest('.tt-k');
      if (k){ const i = Number(k.dataset.i), f = frameFromEvent(e), [a, b] = M.clips[i]; M.sel = { kind: 'clip', i }; M.edge = f - a < b - f ? 'in' : 'out'; renderSel(); sc.focus({ preventScroll: true }); return; }
      const x = e.target.closest('.tt-x');
      if (x){ M.sel = { kind: 'gap', a: Number(x.dataset.a), b: Number(x.dataset.b) }; M.edge = null; renderSel(); sc.focus({ preventScroll: true }); return; }
      const s = e.target.closest('.tt-s');
      if (s){ const g = h.S.doc.segments[Number(s.dataset.i)]; if (g) seekTo(g.start + 0.0005); return; }
      // 目盛り・空いた所: 再生位置を動かす(ドラッグで動かし続ける)
      M.sel = null; seekTo(f2s(frameFromEvent(e)) + 0.0005); renderSel();
      const mv = ev => seekTo(f2s(frameFromEvent(ev)) + 0.0005), up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); };
      window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
      sc.focus({ preventScroll: true });
    });
    window.addEventListener('pointermove', e => { if (M.drag) moveDrag(e); });
    window.addEventListener('pointerup', () => { if (M.drag) endDrag(); });
    window.addEventListener('pointercancel', () => { if (M.drag) endDrag(true); });
    $('#cutSubs').addEventListener('click', e => {
      const b = e.target.closest('[data-act]'); if (!b) return;
      const i = Number(b.closest('.tt-csub').dataset.i), g = h.S.doc && h.S.doc.segments[i]; if (!g) return;
      if (b.dataset.act === 'go') seekTo(g.start + 0.0005);
      else if (b.dataset.act === 'cutrow') rowsCut([i], !M.rowFlags[i]);
    });
    $('#cutPlay').addEventListener('click', togglePlay);
    $('#cutSplit').addEventListener('click', split);
    $('#cutDel').addEventListener('click', delOrRestore);
    $('#cutIO').addEventListener('click', cutIO);
    $('#cutUndo').addEventListener('click', undo);
    $('#cutRedo').addEventListener('click', redo);
    $('#cutZoomIn').addEventListener('click', () => zoom(1.5));
    $('#cutZoomOut').addEventListener('click', () => zoom(1 / 1.5));
    $('#cutZoomFit').addEventListener('click', () => { M.fit = true; render(); });
    $('#cutSnap').addEventListener('change', e => { M.snap = e.target.checked; renderStatus(); });
    $('#cutModeSrc').addEventListener('click', () => { M.mode = 'src'; capIdx = -2; renderTools(); moveHead(); });
    $('#cutModeCut').addEventListener('click', () => { M.mode = 'cut'; capIdx = -2; renderTools(); moveHead(); });
    $('#cutDraftRows').addEventListener('click', draftRows);
    $('#cutDraftSilenceGo').addEventListener('click', () => draftC2R('silence'));
    $('#cutDraftListGo').addEventListener('click', () => draftC2R('list'));
    $('#cutDraftPlan').addEventListener('click', () => draftC2R('plan'));
    document.querySelectorAll('#tabCut details.pop > summary').forEach(s => { s.dataset.title = s.title; s.addEventListener('click', e => { if (s.classList.contains('disabled')){ e.preventDefault(); h.toast(s.title || '今は使えません', 3000); } }); });
    $('#cutReload').addEventListener('click', reloadFromServer);
    $('#cutForce').addEventListener('click', () => { if (M.conflict) save(true); });
    const v = V();
    v.addEventListener('play', startLoop);
    v.addEventListener('seeked', () => { M.seekingOut = false; moveHead(); });
    v.addEventListener('timeupdate', () => { if (v.paused) moveHead(); });
    v.addEventListener('click', togglePlay);
    window.addEventListener('resize', () => { if (M.shown) render(); });
    if (window.ResizeObserver){   // タイムラインの幅が変わった(窓の大きさ・ページのスクロールバーの出入り・メニューの開閉)→ 倍率と位置を計算し直す
      let lastW = 0;
      new ResizeObserver(() => { const w = viewW(); if (w !== lastW){ lastW = w; if (M.shown && ready()) renderNow(); } }).observe(sc);
    }
    window.addEventListener('keydown', onKey);
    window.addEventListener('keyup', e => { if (e.key === 'Alt' && M.drag) e.preventDefault(); });
    h.onLeave(() => { if (M.dirty || M.drag){ if (M.drag) endDrag(); save(); } });
    window.addEventListener('beforeunload', e => { if (M.dirty || M.saving){ e.preventDefault(); e.returnValue = ''; } });
  }
  function onKey(e){
    if (h.tab() !== 'cut' || !h.S.doc || e.isComposing || e.keyCode === 229 || document.querySelector('dialog[open]') || h.isTextEntry(e.target)) return;
    if (e.altKey && !e.ctrlKey && !e.metaKey && /^Digit/.test(e.code)) return;   // Alt+1/2/3 はタブ(app.js)
    const k = e.key, ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && (k === 'z' || k === 'Z')){ e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (ctrl && (k === 'y' || k === 'Y')){ e.preventDefault(); redo(); return; }
    if (ctrl || e.altKey) return;
    if (!ready()) return;
    const run = fn => { e.preventDefault(); fn(); };
    switch (e.code){
      case 'Space': if (!e.target.matches('button,summary,video,input[type=checkbox]')) run(togglePlay); return;
      case 'KeyJ': return run(() => seekTo((V().currentTime || 0) - 1));
      case 'KeyK': return run(() => V().pause());
      case 'KeyL': return run(() => { const v = V(); if (v.paused){ v.playbackRate = 1; togglePlay(); } else v.playbackRate = v.playbackRate >= 2 ? 1 : v.playbackRate + 0.5; });
      case 'ArrowLeft': if (!e.target.closest('#edTabs')) run(() => stepFrames(e.shiftKey ? -Math.round(1 / frameSec()) : -1)); return;
      case 'ArrowRight': if (!e.target.closest('#edTabs')) run(() => stepFrames(e.shiftKey ? Math.round(1 / frameSec()) : 1)); return;
      case 'Home': return run(() => seekTo(0));
      case 'End': return run(() => seekTo(M.dur));
    }
    if (e.shiftKey && k !== '+') return;
    if (!editable()) return;
    switch (k){
      case 's': case 'S': return run(split);
      case 'Delete': case 'Backspace': return run(delOrRestore);
      case 'i': case 'I': return run(() => { M.io.i = headFrame(); render(); });
      case 'o': case 'O': return run(() => { M.io.o = headFrame(); render(); });
      case 'x': case 'X': return run(cutIO);
      case ',': return run(() => nudgeEdge(-1));
      case '.': return run(() => nudgeEdge(1));
      case '+': case '=': return run(() => zoom(1.5));
      case '-': return run(() => zoom(1 / 1.5));
      case 'Escape': if (M.sel || M.io.i !== null || M.io.o !== null){ run(() => { M.sel = null; M.io = { i: null, o: null }; render(); }); } return;
    }
  }
  function onShown(){
    M.shown = true;
    if (!ready()) { render(); return; }
    ensureMedia();
    const v = V(), t = h.player().currentTime || 0;
    if (v.readyState >= 1 && Math.abs(v.currentTime - t) > 0.05) v.currentTime = t;
    render(); renderSubsSoon();
  }
  function onHidden(){
    M.shown = false;
    const v = V(); if (!v.paused) v.pause();
    if (ready() && v.readyState >= 1){ const p = h.player(); if (p.readyState >= 1) p.currentTime = v.currentTime; }
    if (M.drag) endDrag();
    save();
  }

  bind();
  return {
    load, flush, docChanged, rowsCut, onShown, onHidden,
    active: () => ready(),
    unload(){ M.loading++; reset(null); render(); },
    summary(){ return ready() ? { count: mergedCount(M.clips), keptSec: f2s(keptFrames(M.clips)), durSec: M.dur, pristine: M.pristine } : null; },
    state(){ return { dirty: M.dirty, saving: !!M.saving, conflict: !!M.conflict, rev: M.rev, off: M.off, pristine: M.pristine, origin: M.origin }; },
    keepsSec(){ return ready() ? M.clips.map(([a, b]) => [sec3(a), sec3(b)]) : null; },
    _debug: M
  };
}
window.EditCut = { create };
})();
