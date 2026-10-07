/* 「編集」2 カット のタブ(docs/design/edit-tool-design.md の 3・4・8)。app.js より先に読み込み、app.js が EditCut.create(host) で起動する。
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
/* 2 カット の固定のキー(onKey。キー配置では変えられない)。? の一覧(app.js の CUT_KEY_ROWS)・知らせ・title・1 文字起こし のキー配置の検査は、ここから作る
   (2 周目の見直し R1: キーを X → H に変えたあと、知らせの文だけ「(X)」のまま残っていた) */
const IO_CUT_KEY = 'H';   // 始まりの印〜終わりの印を削る(外す)。X は 1 文字起こし の「聞き取れない」と重なっていた(M2・仮決め (ay))
const KEY_ROWS = [['[ / ]', '前/次の区間を選ぶ'], ['Q / W', '選んだ区間の始まり/終わりの端を選ぶ'], ['S', '分割'], ['Del', '削る/戻す'], [IO_CUT_KEY, '始まりの印〜終わりの印を削る(外す)'],
  ['Shift+, / Shift+.', '選んだ端を10コマ(1コマは共通の再生キー)'], ['+ / −', '拡大・縮小'], ['Home / End', '先頭・末尾へ'], ['Esc', '選択を外す'], ['Ctrl+Z / Ctrl+Shift+Z', '元に戻す・やり直す']];
/* 1 文字起こし のキー・共通の再生キーにも割り当てさせないキー(UIKit.keys.comboOf の表記 → 使い道)。S・Q・W は 1 では別の意味と決めてある(ガイドラインの例外)ので入れない */
const FIXED_KEYS = { [IO_CUT_KEY.toLowerCase()]: '2 カット: 始まり〜終わりを削る', Delete: '2 カット: 削る/戻す', Backspace: '2 カット: 削る/戻す', '[': '2 カット: 前の区間', ']': '2 カット: 次の区間',
  '+': '2 カット: 拡大', '=': '2 カット: 拡大', '-': '2 カット: 縮小', Home: '2 カット: 先頭へ', End: '2 カット: 末尾へ' };

function create(h){
  const $ = h.$, esc = h.esc;
  const M = {
    docId: null, loading: 0, loaded: false, fps: null, dur: 0, total: 0, clips: [], rev: 0, origin: 'manual', pristine: true, off: '', offCode: '',
    sel: null, edge: null, io: { i: null, o: null }, undo: [], redo: [], dirty: false, saving: null, conflict: null, saveT: 0,
    peaks: null, peaksRate: 100, peaksAudio: true, peaksMsg: '', silence: [], planBeside: '', draftBusy: false, lastDraftSig: '',
    pps: 0, fit: true, snap: true, vis: [0, 0], mode: 'cut', mediaFor: null, drag: null, rdrag: null, rowFlags: [], shown: false, seekingOut: false
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
  function nextClip(f){ let lo = 0, hi = M.clips.length; while (lo < hi){ const m = (lo + hi) >> 1; if (M.clips[m][1] <= f) lo = m + 1; else hi = m; } return lo; }   // 終わりが f より後の最初の区間
  function clipAt(f){ const i = nextClip(f); return i < M.clips.length && M.clips[i][0] <= f ? i : -1; }   // f を含む区間(無ければ -1)
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
    pushCutUndo(before, M.origin, opSeq());
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
  /* 積むときに操作の通し番号(app.js の nextOp。文字起こしの履歴と同じ番号)を付ける = 1 文字起こし の「元に戻す」が新しい方を選ぶ(段3 3-5)。やり直しも新しい番号 */
  const opSeq = () => (h.nextOp ? h.nextOp() : 0);
  function pushCutUndo(clips, origin, seq){ M.undo.push({ clips, origin, seq }); if (M.undo.length > UNDO_MAX) M.undo.shift(); M.redo = []; }   // 新しい操作(やり直しは消える)
  /* 2 カット の Ctrl+Z・元に戻すボタン: 文書(行の時刻・分割)とカットのうち新しい方を戻す(app.js の doUndo と同じ順。段6 6-4。字幕の段からは文書も変えるため) */
  function undoNewest(){ if (h.doUndo) h.doUndo(); else undo(); }
  function undo(){
    const u = M.undo.pop(); if (!u) return;
    M.redo.push({ clips: M.clips, origin: M.origin }); M.clips = u.clips; M.origin = u.origin; M.sel = null; afterChange();
    if (u.seq && h.undoDocIf && h.undoDocIf(u.seq)) h.toast('行の時刻と残す区間を戻しました', 2500);   // 字幕の段の1回の操作(行 + 区間)は同じ番号で積む(段6 6-4)→ 一緒に戻す
  }
  function redo(){ const r = M.redo.pop(); if (!r) return; M.undo.push({ clips: M.clips, origin: M.origin, seq: opSeq() }); M.clips = r.clips; M.origin = r.origin; M.sel = null; afterChange(); }

  /* ---------- 読み込み(文書を開いたとき) ---------- */
  function reset(docId){
    clearTimeout(M.saveT);
    Object.assign(M, { docId, loaded: false, fps: null, dur: 0, total: 0, clips: [], rev: 0, origin: 'manual', pristine: true, off: '', offCode: '', sel: null, edge: null,
      io: { i: null, o: null }, undo: [], redo: [], dirty: false, saving: null, conflict: null, saveT: 0, peaks: null, peaksAudio: true, peaksMsg: '', silence: [],
      planBeside: '', draftBusy: false, lastDraftSig: '', draft: null, fit: true, mediaFor: null, drag: null, rdrag: null, rowFlags: [] });
    const v = V(); v.pause(); v.removeAttribute('src'); v.load();
    renderSaveState();   // 競合の案内・保存の状態も初めに戻す(読み直したとき)
  }
  async function load(docId){
    reset(docId);
    const seq = ++M.loading;
    let ed = null, dr = null, drErr = null, edErr = null;
    await Promise.all([
      h.api('/api/edit?id=' + encodeURIComponent(docId)).then(r => { ed = r; }).catch(e => { edErr = e; }),
      h.api('/api/edit/draft?id=' + encodeURIComponent(docId)).then(r => { dr = r; }).catch(e => { drErr = e; })
    ]);
    if (seq !== M.loading || M.docId !== docId) return;
    if (dr && dr.unavailable){ drErr = { message: dr.unavailable.message, code: dr.unavailable.code }; dr = null; }   // 動画が無い・ネットワーク上・音声だけ
    const e = ed && ed.edit;
    if (dr){ M.fps = dr.fps; M.dur = dr.durationSec; M.planBeside = dr.planBeside || ''; }
    else if (e){ M.fps = e.sources[0].fps; M.dur = e.sources[0].duration; }
    if (drErr) setOff(drErr.message, drErr.code || 'draft');
    /* 監査 13: 保存済みのカットを読めなかった(通信の失敗・サーバーのエラー)ときは、たたき台で始めない(新規と見分けがつかず、
       違う区間でパックを作れてしまうため)。理由と「もう一度読み込む」を出し、区間を作らない(off なのでパックのタブも止まる)。
       未作成 = ed.edit が null(何も言わない)・壊れている = ed.broken(下の知らせ)・読めない = ここ。404(文書が無い)は今までどおり */
    else if (edErr && edErr.status !== 404){
      setOff(`保存済みのカットを読み込めませんでした(${edErr.message})`, 'edit_load');
      M.fps = null;
    }
    M.loaded = true;   // 読み込みが終わった(使えない理由 offCode もここで決まる。1 文字起こし の再生の失敗の案内が使う)
    if (!M.fps){ render(); h.onCutState(); return; }
    M.total = Math.max(1, Math.round(M.dur * M.fps[0] / M.fps[1]));
    if (e){
      M.rev = ed.rev; M.origin = e.origin || 'manual'; M.pristine = false;
      M.clips = norm(e.clips.map(c => [s2f(c.in), s2f(c.out)]));
      if (dr){   // 動画の長さが変わった(同じパスの動画を書き出し直した): 後ろの区間を切って知らせる
        const over = M.clips.some(([, b]) => b > M.total + 1);
        M.clips = norm(M.clips.map(([a, b]) => [a, Math.min(b, M.total)]));
        if (over){
          h.toast('動画の長さが、カットを決めたときと変わっています(書き出し直した?)。動画の終わりより後ろの区間は切りました', 8000, 'err');
          M.pristine = false; scheduleSave();
        }
      }
    } else if (dr){
      M.clips = norm(dr.keepsSec.map(([a, b]) => [s2f(a), s2f(b)])); M.origin = dr.base === 'rows' ? 'rows' : 'all'; M.pristine = true; M.rev = ed ? ed.rev : 0;
      noteDraft(M.origin, dr.keepsSec, M.origin === 'rows' ? edgeSetting() : {});
    }
    if ((e || dr) && ed && ed.broken) h.toast('保存されていたカットのファイルが読めませんでした。たたき台から始めます(壊れたファイルは残してあります)', 7000, 'err');
    M.lastDraftSig = rowSig();
    syncRowCuts(); render(); h.onCutState();
    if (M.shown) onShown(true);
  }
  function setOff(msg, code){ M.off = msg; M.offCode = code; }
  const ready = () => !!(M.fps && M.docId && h.S.docId === M.docId);
  const editable = () => ready() && !M.off;
  const rowSig = () => { const d = h.S.doc; return d ? d.segments.map(g => `${g.start},${g.end},${g.cutState === 'cut' ? 1 : 0},${String(g.text || '').trim() ? 1 : 0}`).join(';') : ''; };

  /* ---------- 保存(0.8 秒まとめて PUT・rev で競合を見る) ---------- */
  function scheduleSave(){ M.dirty = true; clearTimeout(M.saveT); if (!M.drag) M.saveT = setTimeout(save, SAVE_DELAY); renderSaveState(); }
  function body(baseRev){
    return { baseRev, edit: { sources: [{ fps: M.fps, duration: Math.round(M.dur * 1000) / 1000 }], clips: M.clips.map(([a, b]) => ({ src: 0, in: sec3(a), out: sec3(b) })), origin: M.origin },
      ...(baseRev === 0 && M.draft ? { draft: M.draft } : {}) };   // 初めての保存だけ、始めたたき台を添える(サーバーが edit.json に一度だけ書く)
  }
  /* 始めたたき台の記録(マスタープラン Q2。機械の最初の結果 = たたき台と、人の最終 = 保存したカット・パックを並べて、たたき台の規則を直すため)。
     まだ1回も保存していない間は、最後に作ったたたき台(種類・設定・区間の秒)を覚えておき、初めての保存に添える。保存済みのカットがあれば送らない */
  function noteDraft(origin, keepsSec, settings){
    if (M.rev) return;
    M.draft = { origin, settings: settings || {}, keepsSec: (keepsSec || []).map(([a, b]) => [Math.round(a * 1000) / 1000, Math.round(b * 1000) / 1000]), at: Date.now() };
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
    renderSaveState();   // M.saving が入ってから表示し直す(上の async の最初の renderSaveState は代入の前に走るので、送っている間も「保存しました」に見えていた)
    return M.saving;
  }
  async function flush(){
    if (M.drag) endDrag(true);
    if (M.rdrag) endRowDrag(true);
    if (!M.dirty) return !(M.saving && !(await M.saving));
    return save();
  }
  async function reloadFromServer(){ const id = M.docId; M.conflict = null; M.dirty = false; await load(id); h.toast('保存されているカットを読み直しました', 3000, 'ok'); }
  function renderSaveState(){
    $('#cutConflict').hidden = !M.conflict;
    const el = $('#cutSaveSt');
    const [t, k] = M.conflict ? ['カットが競合しています', 'err'] : M.saving ? ['カットを保存中…', 'busy'] : M.dirty ? ['未保存…', ''] : M.rev ? ['カットを保存しました', 'ok'] : ['', ''];
    el.textContent = t; el.setAttribute('data-state', k);
    if (h.onCutSave) h.onCutSave(M.conflict ? 'カット: 競合しています' : M.saving ? 'カット: 保存中…' : M.dirty ? 'カット: 未保存…' : M.rev ? 'カット: 保存しました' : '', k);   // ヘッダーの保存の状態へ(S4)
    h.onCutState();
  }

  /* ---------- たたき台(規則はサーバー・cut2resolve) ---------- */
  function confirmReplace(){
    if (M.pristine || !M.undo.length && M.origin !== 'manual') return Promise.resolve(true);
    if (window.UIKit && UIKit.dialog) return UIKit.dialog.confirm({ title: '今のカットを、たたき台で置き換えますか?', body: '手で直したカットがあります。置き換えても「元に戻す」(Ctrl+Z)で戻せます。', ok: '置き換える' });
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
      const r = await h.api('/api/edit/draft?rows=1&id=' + encodeURIComponent(M.docId));
      if (r.unavailable) return h.toast(r.unavailable.message, 6000, 'err');
      for (const w of (r.warnings || []).slice(0, 2)) h.toast(w, 7000);
      noteDraft(r.base === 'rows' ? 'rows' : 'all', r.keepsSec, r.base === 'rows' ? edgeSetting() : {});
      applyKeeps(r.keepsSec, 'rows', r.base === 'rows' ? '文字起こしの行から' : '(残す行が無いので)動画全体');
    } catch (e){ h.toast('たたき台を作れませんでした: ' + e.message, 6000, 'err'); }
    finally { M.draftBusy = false; renderTools(); }
  }
  /* カットしない(動画全体。気が利く画面へ 段3): 残す区間 = 動画全体。行の「カット済」は編集の内容から付け直す決まりなので、字幕も全部出る */
  async function draftWhole(){
    if (!editable() || M.draftBusy) return;
    if (!(await confirmReplace())) return;
    noteDraft('whole', [[0, M.dur]], {});
    applyKeeps([[0, M.dur]], 'whole', 'カットしない(動画全体)');
  }
  async function draftC2R(kind){
    if (!editable() || M.draftBusy) return;
    if (!h.c2rBase()) return h.toast('このたたき台は cut2resolve を使います。ホーム(start.bat)から開いてください', 6000, 'err');
    const src = String(h.S.doc.sourcePath || '');
    let spec;
    if (kind === 'silence'){
      const silence = await saveSil(); if (!silence) return;   // 値は覚える(設定 cutSilence。範囲の外なら知らせて作らない)
      spec = { video: src, mode: 'silence', silence, dropCutRows: false };   // 最短の長さは cut2resolve の既定(ごく短い切れ端を残さない)
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
      const ks = res.keepsSec || [];
      if (kind === 'silence' && ks.length <= 1 && (!ks.length || (ks[0][0] <= 0.05 && ks[0][1] >= (M.dur || 0) - 0.05))){   // 切れる所が無い: 今のカットは置き換えない(UI の見直し S11)
        h.toast('無音が見つかりませんでした。「無音とみなす音量」を上げる(-30 など)と見つかることがあります。今のカットはそのままです', 8000);
        return;
      }
      for (const w of (res.warnings || []).slice(0, 2)) h.toast(w, 6000);
      noteDraft(kind, res.keepsSec || [], kind === 'silence' ? spec.silence : kind === 'list' ? { lines: spec.listText.split(/\r?\n/).filter(x => x.trim()).length } : {});
      applyKeeps(res.keepsSec || [], kind, label);
      document.querySelectorAll('#tabCut details.pop[open]').forEach(d => { d.open = false; });
    } catch (e){ h.toast(label + 'のたたき台を作れませんでした: ' + (e.code === 'busy' ? 'cut2resolve で別の処理が動いています。終わってから、もう一度押してください' : e.message), 7000, 'err'); }
    finally { M.draftBusy = false; renderTools(); }
  }
  /* 「無音 ▾」の値(サーバーの設定 cutSilence = まとめて実行の「無音で削る」も同じ値。気が利く画面へ 段7 E-5)。
     範囲は cut2resolve の spec の検査と同じ(サーバーの ed_learn.CUT_SILENCE_RANGE も同じ)。[鍵, 欄, 既定, 下限, 上限, 欄の名前] */
  const SIL_FIELDS = [['noise', '#cutNoise', -35, -90, 0, '無音とみなす音量(dB)'], ['min', '#cutSilMin', 0.6, 0.05, 60, '無音の長さ(秒)'], ['pad', '#cutSilPad', 0.15, 0, 10, '話の前後に残す秒数']];
  function silSetting(){
    const v = (h.S.settings || {}).cutSilence, o = v && typeof v === 'object' ? v : {};
    return Object.fromEntries(SIL_FIELDS.map(([k, , dv, lo, hi]) => { const n = Number(o[k]); return [k, o[k] !== null && o[k] !== '' && Number.isFinite(n) && n >= lo && n <= hi ? n : dv]; }));
  }
  function fillSil(){ const s = silSetting(); for (const [k, id] of SIL_FIELDS) if (document.activeElement !== $(id)) $(id).value = String(s[k]); }
  /* 欄の値を確かめて覚える -> 値 {noise, min, pad}。範囲の外・数でなければ知らせて覚えている値に戻し null。覚えている値と同じなら送らない */
  async function saveSil(){
    const v = {};
    for (const [k, id, , lo, hi, label] of SIL_FIELDS){
      const raw = $(id).value.trim(), n = Number(raw);
      if (!raw || !Number.isFinite(n) || n < lo || n > hi){ h.toast(`${label}は ${lo}〜${hi} の数で入れてください`, 5000, 'err'); fillSil(); return null; }
      v[k] = Math.round(n * 100) / 100;
    }
    const cur = silSetting();
    if (SIL_FIELDS.every(([k]) => cur[k] === v[k])) return v;
    try { await h.api('/api/settings/patch', { body: { values: { cutSilence: v } } }); h.S.settings.cutSilence = v; }   // 送ったキーだけ直す(ほかの窓の設定を消さない)
    catch (e){ h.toast('無音の値を保存できませんでした(今回のたたき台には使います): ' + e.message, 6000, 'err'); }
    return v;
  }
  /* 「行から」の設定(行の端を声の止まる所まで広げる。サーバーの設定 rowEdge = zip・まとめて実行も同じ。規則は pack.py) */
  function edgeSetting(){
    const v = (h.S.settings || {}).rowEdge, o = v && typeof v === 'object' ? v : {};
    const num = (x, dv) => { const n = Number(x); return Number.isFinite(n) && n >= 0 && n <= 2 ? n : dv; };
    return { on: v !== false && o.on !== false, after: num(o.after, 0.5), before: num(o.before, 0.3), padAfter: num(o.padAfter, 0.2) };   // padAfter = 行の後の余白(段6 6-2。入口は 3 パック の詳しい設定)
  }
  function fillEdge(){
    const e = edgeSetting(); $('#cutEdgeOn').checked = e.on; $('#cutEdgeAfter').value = e.after; $('#cutEdgeBefore').value = e.before; $('#cutEdgeAfter').disabled = $('#cutEdgeBefore').disabled = !e.on;
    const pad = $('#cutEdgePad'); if (pad) pad.textContent = '後 ' + e.padAfter + ' 秒';   // 値を出すだけ(変える入口は 3 パック の詳しい設定の1か所。guidelines 3)
  }
  async function saveEdge(){
    const num = (id, dv) => { const n = Number($(id).value); return Number.isFinite(n) ? Math.min(2, Math.max(0, n)) : dv; };
    const cur = h.S.settings.rowEdge && typeof h.S.settings.rowEdge === 'object' ? h.S.settings.rowEdge : {};   // padAfter など、ここで扱わない値は残す
    h.S.settings.rowEdge = { ...cur, on: $('#cutEdgeOn').checked, after: num('#cutEdgeAfter', 0.5), before: num('#cutEdgeBefore', 0.3) };
    fillEdge();
    try { await h.putSettings(); return true; } catch (e){ h.toast('設定を保存できませんでした: ' + e.message, 5000, 'err'); return false; }
  }
  /* 開いたまま(まだ手で直していない)下書きは、行が変わったら「行から」を作り直す(以前の「カットとパック」と同じ結果に保つ) */
  function docChanged(){
    if (!ready()) return;
    if (M.pristine && M.origin === 'rows' || M.pristine && M.origin === 'all'){
      const sig = rowSig();
      if (sig !== M.lastDraftSig){ clearTimeout(docChanged.t); docChanged.t = setTimeout(async () => {
        if (!M.pristine || M.docId !== h.S.docId) return;
        try {
          const r = await h.api('/api/edit/draft?rows=1&id=' + encodeURIComponent(M.docId));
          if (!M.pristine || M.docId !== h.S.docId || r.unavailable) return;
          M.clips = norm(r.keepsSec.map(([a, b]) => [s2f(a), s2f(b)])); M.origin = r.base === 'rows' ? 'rows' : 'all'; M.lastDraftSig = rowSig();
          noteDraft(M.origin, r.keepsSec, M.origin === 'rows' ? edgeSetting() : {});
          syncRowCuts(); render(); h.onCutState();
        } catch {}
      }, 1500); }
      return;
    }
    syncRowCuts();   // 行の時刻が変わった → 行の「カット済」を付け直す(カットはそのまま)
  }
  /* 1 文字起こし のタブの行の「削る/戻す」(行の時間を削る区間にする/残す区間にする)。
     削るとき、行のすぐ前・後ろに残る切れ端(「行から」で端を声の止まる所まで広げた分)が、他の残す行と重ならず、
     端を広げる上限(「行から」の設定)より短ければ一緒に削る(行だけ削ると、広げた分が 0.1〜0.5 秒の切れ端で残るため。12 ⑥) */
  function rowsCut(idxs, cut){
    const segs = h.S.doc.segments, set = new Set(idxs);
    const e = edgeSetting(), lim = { before: e.on ? s2f(e.before) + 1 : 0, after: e.on ? s2f(e.after) + 1 : 0 };
    const keptRow = (p, q) => segs.some((g, j) => !set.has(j) && !M.rowFlags[j] && String(g.text || '').trim() && Math.min(q, s2f(g.end)) - Math.max(p, s2f(g.start)) > 0);
    return change(cs => {
      for (const i of idxs){
        const g = segs[i]; if (!g) continue;
        const a = Math.max(0, s2f(g.start)), b = Math.min(M.total, Math.max(s2f(g.end), a + 1));
        if (!cut){ cs = addRange(cs, a, b); continue; }
        cs = subtract(cs, a, b);
        const lo = cs.find(c => c[1] === a), hi = cs.find(c => c[0] === b);
        if (lo && lo[1] - lo[0] <= lim.before && !keptRow(lo[0], lo[1])) cs = subtract(cs, lo[0], lo[1]);
        if (hi && hi[1] - hi[0] <= lim.after && !keptRow(hi[0], hi[1])) cs = subtract(cs, hi[0], hi[1]);
      }
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
    $('#cutOffMsg').textContent = M.off ? M.off + '。1 文字起こし のタブは今までどおり使えます' : (!ready() && h.S.doc ? 'カットの準備をしています…' : '');
    $('#cutRelink').hidden = !(M.off && M.offCode === 'source_missing' && h.relink);   // 動画を選び直す(段2 B-4)
    $('#cutRetry').hidden = !(M.off && M.offCode === 'edit_load');
    tab.classList.toggle('tt-cut-disabled', noVideo);
    renderTools(); renderStatus(); renderSubsSoon();
    if (!ready()){ $('#tlVideo').innerHTML = ''; $('#tlSubs').innerHTML = ''; return; }   // 使えない間は、前の文書・読み直す前の区間を残さない(監査 13)
    if (!M.shown) return;
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
    const segs = h.S.doc ? h.S.doc.segments : [];
    let sh = '';
    for (let i = 0; i < segs.length; i++){
      const g = segs[i], a = s2f(g.start), b = s2f(g.end);
      if (b < f0 || a > f1 || !String(g.text || '').trim()) continue;
      sh += `<div class="tt-s${M.rowFlags[i] ? ' cut' : ''}" data-i="${i}" style="left:${X(a)}px;width:${Math.max(2, X(b) - X(a) - 2)}px" title="${esc(fmtF(a))} ${esc(g.text)}">${esc(g.text)}</div>`;
    }
    $('#tlSubs').innerHTML = sh;
    renderSel(true);   // 区間と字幕の段の両方を描いてから(行のつまみは字幕の段の中)
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
    const sb = $('#tlSubs');
    sb.querySelectorAll('.sel').forEach(e => e.classList.remove('sel')); sb.querySelectorAll('.tt-rh').forEach(e => e.remove());
    if (M.sel && M.sel.kind === 'row'){   // 字幕の段の行(段6 6-3): 選んだ行にだけ左右のつまみ(競合中・処理中は出さない = 6-6)
      const el = sb.querySelector(`.tt-s[data-i="${M.sel.i}"]`);
      if (el){
        el.classList.add('sel');
        if (rowEditable()) el.insertAdjacentHTML('beforeend', `<i class="tt-rh in${M.edge === 'in' ? ' on' : ''}" data-edge="in" title="行の始まりをドラッグ(前の行を越えない。端を選んで , . で1コマ)"></i><i class="tt-rh out${M.edge === 'out' ? ' on' : ''}" data-edge="out" title="行の終わりをドラッグ(次の行を越えない。端を選んで , . で1コマ)"></i>`);
        else el.title = rowWhy() || el.title;
      }
    }
    if (!quiet){ renderStatus(); renderTools(); }
    cutKeybarScene();
  }
  /* 共通の再生キーの今の割り当て(編集のキー配置 = UIKit.keymap)の表記。外していれば ''(帯・案内の文を割り当てから作る。段6・GPT-16) */
  function pkMap(){ const km = h.keymap ? h.keymap() : null; return km && Object.keys(km).length ? km : (window.UIKit && UIKit.keys ? UIKit.keys.playbackMap(null) : {}); }
  function pk(id){ const k = pkMap()[id]; return k && window.UIKit && UIKit.keys ? UIKit.keys.keyText(k) : ''; }
  /* 画面の下の帯(UIKit.keybar。段3): 端を選んでいる間だけ、1コマのキーの意味を知らせる場面に変える */
  function cutKeybarScene(){
    if (!window.UIKit || !UIKit.keybar || h.tab() !== 'cut' || !M.shown) return;
    const set = items => UIKit.keybar.set(items.filter(x => x.k));
    if (M.sel && M.sel.kind === 'clip' && M.edge) set([{ k: pk('frameBack'), l: '1コマ' }, { k: pk('frameFwd'), l: '1コマ' }, { k: 'Shift', l: '10コマ' }, { k: 'Q / W', l: '始まり/終わりの端' }, { k: '[ ]', l: '前/次の区間' }, { k: 'Esc', l: '選択を外す' }]);
    else if (M.sel && M.sel.kind === 'clip') set([{ k: 'Q / W', l: '始まり/終わりの端' }, { k: '[ ]', l: '前/次の区間' }, { k: 'Del', l: '削る' }, { k: 'S', l: '分割' }, { k: 'Esc', l: '選択を外す' }]);
    else if (M.sel && M.sel.kind === 'row' && M.edge) set([{ k: pk('frameBack'), l: '行の端を1コマ' }, { k: pk('frameFwd'), l: '1コマ' }, { k: 'Shift', l: '10コマ' }, { k: 'Q / W', l: '始まり/終わりの端' }, { k: 'Esc', l: '選択を外す' }]);
    else if (M.sel && M.sel.kind === 'row') set([{ k: 'Q / W', l: '行の始まり/終わりの端' }, { k: 'Esc', l: '選択を外す' }]);
    else set([{ k: pk('playPause'), l: '再生・停止' }, { k: '[ ]', l: '区間を選ぶ' }, { k: 'S', l: '分割' }, { k: 'Del', l: '削る/戻す' }, { k: pk('markIn'), l: '始まり' }, { k: pk('markOut'), l: '終わり' }, { k: 'Ctrl+Z', l: '元に戻す' }]);
  }
  /* タイムラインの下のキーの案内(今の割り当てから) */
  function renderKeysText(){
    const io = $('#cutIOLabel');   // 「I〜O を削る」のボタンの文字も、始まり/終わりの印のキーから(段3 3-3。外していれば「印の間を削る」)
    if (io) io.textContent = pk('markIn') && pk('markOut') ? pk('markIn') + '〜' + pk('markOut') + ' を削る' : '印の間を削る';
    const kb = document.querySelector('#cutIO kbd'); if (kb) kb.textContent = IO_CUT_KEY;
    /* タイムラインの下の長いキーの説明の行はやめた(帯・? の一覧と同じ中身を三度出していた。UI の見直し S17)。下の行は「すべてのキー: ?」だけ(index.html) */
  }
  window.addEventListener('ytt-keys-changed', () => { renderKeysText(); cutKeybarScene(); });
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
  /* canvas の大きさ(画面の点 × dpr)を合わせ、消して、2D の描き先を返す(波形・ミニマップ) */
  function canvas2d(cv, w, hgt){
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(hgt * dpr)){ cv.width = Math.round(w * dpr); cv.height = Math.round(hgt * dpr); }
    const cx = cv.getContext('2d'); cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, w, hgt);
    return cx;
  }
  /* t0〜t1 秒の波形のいちばん大きい値(0〜255)。波形の終わりより後ろなら -1 */
  function peakIn(t0, t1){
    const p = M.peaks, rate = M.peaksRate, i0 = Math.floor(t0 * rate);
    if (i0 >= p.length) return -1;
    let v = 0;
    for (let i = i0, i1 = Math.min(p.length, Math.max(i0 + 1, Math.ceil(t1 * rate))); i < i1; i++) if (p[i] > v) v = p[i];
    return v;
  }
  /* 波形(canvas は見えている幅だけ。横にずらしたら描き直す) */
  function drawWave(){
    const cv = $('#tlWave'), box = $('#tlAudio'), sc = scroller();
    const w = viewW(), hgt = box.clientHeight || 64;
    cv.style.left = sc.scrollLeft + 'px'; cv.style.width = w + 'px'; cv.style.height = hgt + 'px';
    const cx = canvas2d(cv, w, hgt);
    /* 段3: 波形は区間(#tlVideo。色で残す/削るを示す)の上に重ねて描く(4段 → 3段「区間(中に波形)」)。
       区間の色と見分けやすいよう、波形そのものは明暗どちらのテーマでも白系(削る区間は薄く) */
    if (!M.peaks){
      cx.fillStyle = (getComputedStyle(document.documentElement).getPropertyValue('--ink-4') || '#999').trim(); cx.font = '12px sans-serif';
      cx.fillText(M.peaksMsg || (M.peaksAudio ? '音の波形を読み込んでいます…' : '音声がありません'), 8, hgt / 2 + 4); renderMini(); return;
    }
    const col = 'rgba(255,255,255,.65)', dim = 'rgba(255,255,255,.32)', mid = hgt / 2, l = sc.scrollLeft;
    const cutFr = []; for (const [a, b] of gaps()) cutFr.push([f2s(a), f2s(b)]);
    let gi = 0;
    for (let x = 0; x < w; x++){
      const t0 = (l + x) / M.pps, v = peakIn(t0, (l + x + 1) / M.pps);
      if (v < 0) break;
      while (gi < cutFr.length && cutFr[gi][1] <= t0) gi++;
      const inCut = gi < cutFr.length && cutFr[gi][0] <= t0;
      const hh = Math.max(1, v / 255 * (mid - 2));
      cx.fillStyle = inCut ? dim : col; cx.globalAlpha = inCut ? 0.55 : 0.9;
      cx.fillRect(x, mid - hh, 1, hh * 2);
    }
    cx.globalAlpha = 1;
    renderMini();
  }
  /* ---------- ミニマップ(段3。全体を縮めた帯。見ている範囲の枠をドラッグで移動・端をドラッグで拡大縮小) ---------- */
  function miniEl(){ return $('#tlMini'); }
  function miniW(){ return miniEl().clientWidth || 1; }
  function renderMini(){
    if (!ready() || !M.dur){ return; }
    const w = miniW(), view = $('#tlMiniView');
    const left = (scroller().scrollLeft / M.pps) / M.dur * w;
    const width = (viewW() / M.pps) / M.dur * w;
    view.style.left = Math.max(0, Math.min(w - 4, left)) + 'px';
    view.style.width = Math.max(6, Math.min(w, width)) + 'px';
    drawMiniWave(w);
  }
  let miniSig = null;
  function drawMiniWave(w){
    const hgt = miniEl().clientHeight || 34;
    /* ミニマップの波形は全体を縮めたものなので、横にスクロールしても絵は変わらない(枠の位置は renderMini が別に動かす)。
       波形・区間・大きさが変わっていなければ描き直さない(スクロールのたびに全サンプルを走査すると重いため) */
    const sig = w + ':' + hgt + ':' + (M.peaks ? M.peaks.length : -1) + ':' + JSON.stringify(M.clips);
    if (sig === miniSig) return;
    miniSig = sig;
    const cx = canvas2d($('#tlMiniWave'), w, hgt);
    const cs = getComputedStyle(document.documentElement), accent = (cs.getPropertyValue('--accent') || '#5a46e0').trim(), dim = (cs.getPropertyValue('--ink-4') || '#999').trim();
    cx.fillStyle = accent; cx.globalAlpha = 0.4;
    for (const [a, b] of M.clips){ const x0 = f2s(a) / M.dur * w, x1 = f2s(b) / M.dur * w; cx.fillRect(x0, 0, Math.max(1, x1 - x0), hgt); }
    cx.globalAlpha = 1;
    if (M.peaks){
      const mid = hgt / 2;
      cx.fillStyle = dim;
      for (let x = 0; x < w; x++){
        const v = peakIn(x / w * M.dur, (x + 1) / w * M.dur);
        if (v < 0) break;
        const hh = Math.max(1, v / 255 * (mid - 2));
        cx.fillRect(x, mid - hh, 1, hh * 2);
      }
    }
  }
  function miniTimeAt(clientX){ const r = miniEl().getBoundingClientRect(); return Math.max(0, Math.min(M.dur, (clientX - r.left) / Math.max(1, r.width) * M.dur)); }
  /* 見る範囲を [tLeft, tRight](秒)に合わせる: 幅から倍率(pps)を決め、左端に合わせてスクロールする */
  function setViewByTimes(tLeft, tRight){
    tLeft = Math.max(0, tLeft); tRight = Math.min(M.dur, Math.max(tRight, tLeft + 0.05));
    const pps = viewW() / Math.max(0.05, tRight - tLeft);
    M.fit = false; M.pps = Math.min(Math.max(pps, fitPps()), maxPps());
    if (M.pps <= fitPps() + 1e-9) M.fit = true;
    renderNow(); scroller().scrollLeft = Math.max(0, tLeft * M.pps); renderRange();
  }
  /* 押したままの間、窓の pointermove を move へ(離す・取り消しで終わる) */
  function dragOnWindow(move){
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up);
  }
  function bindMini(){
    miniEl().addEventListener('pointerdown', e => {
      if (!ready() || e.button !== 0) return;
      e.preventDefault();
      const handle = e.target.closest('.tt-tl-mini-h'), onView = !handle && e.target.closest('#tlMiniView');
      if (handle){
        const side = handle.dataset.h, minW = viewW() / maxPps();   // 見る範囲がこれより狭くはならない(最大倍率と同じ)
        const fixed = side === 'l' ? (scroller().scrollLeft + viewW()) / M.pps : scroller().scrollLeft / M.pps;
        dragOnWindow(ev => {
          const raw = miniTimeAt(ev.clientX);
          if (side === 'l') setViewByTimes(Math.min(raw, fixed - minW), fixed); else setViewByTimes(fixed, Math.max(raw, fixed + minW));
        });
      } else if (onView){
        const startX = e.clientX, startScroll = scroller().scrollLeft, w = miniW();
        dragOnWindow(ev => { const dx = (ev.clientX - startX) / w * M.dur * M.pps; scroller().scrollLeft = Math.max(0, startScroll + dx); renderMini(); });
      } else {
        const t = miniTimeAt(e.clientX);
        M.fit = false; scroller().scrollLeft = Math.max(0, t * M.pps - viewW() / 2); renderRange();
      }
    });
  }
  async function loadPeaks(){
    const id = M.docId, seq = M.loading;
    const gone = () => M.docId !== id || M.loading !== seq;   // 別の文書・同じ文書の読み直し(reset で fps が無くなる)に移った
    M.peaksMsg = '';
    for (let n = 0; n < 1200 && !gone(); n++){
      let r;
      try { r = await fetch(h.apiUrl('/api/peaks?id=' + encodeURIComponent(id)), { cache: 'no-store' }); } catch { M.peaksMsg = '音の波形を読み込めませんでした'; break; }
      if (gone()) return;
      if (r.status === 202){ const j = await r.json().catch(() => ({})); M.peaksMsg = j.message || '音の波形を作っています…'; drawWave(); await new Promise(res => setTimeout(res, 1000)); continue; }
      if (!r.ok){ const j = await r.json().catch(() => ({})); M.peaksMsg = '音の波形を作れませんでした' + (j.message ? ': ' + j.message : ''); break; }
      M.peaksRate = Number(r.headers.get('X-Peaks-Rate')) || 100; M.peaksAudio = r.headers.get('X-Peaks-Audio') !== '0';
      const buf = await r.arrayBuffer();
      if (gone()) return;
      M.peaks = new Uint8Array(buf);
      if (!M.peaksAudio){ M.peaks = null; M.peaksMsg = '音声がありません'; }
      else findSilence();
      break;
    }
    if (!gone()) drawWave();
  }
  function findSilence(){   // 無音の境目(吸い付く先)
    if (!M.fps || !M.peaks) return;
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
    syncSplitBtn(t);
  }
  function keepHeadVisible(){
    const sc = scroller(), x = (V().currentTime || 0) * M.pps, w = viewW();
    if (x < sc.scrollLeft || x > sc.scrollLeft + w - 20){ sc.scrollLeft = Math.max(0, x - w * 0.2); }
  }
  let capIdx = -2;
  function showCaption(t){   // プレビューの字幕(Resolve の Text+ のおおよその見え方。カット後では削った行を出さない)
    const segs = h.S.doc ? h.S.doc.segments : [];
    /* 出す行は 1 文字起こし の映像の上の字幕と同じ関数(app-rows.js の capStack。字幕に出さない行を外し、0.3 秒以上重なる行は上下に積む。2026-10-05) */
    const idxs = h.capStack ? h.capStack(segs, t, { skip: i => M.mode === 'cut' && !!M.rowFlags[i] }) : [];
    const key = idxs.join(',');
    if (key === capIdx) return;
    capIdx = key;
    if (h.paintCaps) h.paintCaps($('#cutCaption'), idxs, segs);   // 話者の色も app.js の speakerColor の1か所(段2)。合わなければ配信者の色(body の --tt-cap-color)
    document.querySelectorAll('#cutSubs .tt-csub.now').forEach(r => r.classList.remove('now'));
    const idx = idxs.length ? idxs[idxs.length - 1] : -1;   // 一覧で「今」の印を付けて追うのは、いちばん上の段(開始が遅い行)
    for (const i of idxs){ const r = document.querySelector(`#cutSubs .tt-csub[data-i="${i}"]`); if (r) r.classList.add('now'); }
    const row = idx >= 0 ? document.querySelector(`#cutSubs .tt-csub[data-i="${idx}"]`) : null;
    if (row && !V().paused){ const box = $('#cutSubs'), rt = row.offsetTop - box.offsetTop; if (rt < box.scrollTop || rt > box.scrollTop + box.clientHeight - 40) box.scrollTop = rt - 40; }
  }
  function renderStatus(){
    const st = $('#cutStatus');
    if (!ready()){ st.innerHTML = ''; return; }
    const n = mergedCount(M.clips), kf = keptFrames(M.clips);
    let sel = '';
    if (M.sel && M.sel.kind === 'clip' && M.clips[M.sel.i]){ const [a, b] = M.clips[M.sel.i]; sel = `選んだ区間: <b>${M.sel.i + 1}</b> <span class="mono">${fmtF(a)} – ${fmtF(b)}</span>(${h.fmtCs(f2s(b - a))}秒)`; }
    else if (M.sel && M.sel.kind === 'gap'){ sel = `選んだ削る区間: <span class="mono">${fmtF(M.sel.a)} – ${fmtF(M.sel.b)}</span>(Del で戻す)`; }
    else if (M.sel && M.sel.kind === 'row' && segAt(M.sel.i)){   // 字幕の段の行(段6 6-3・6-5)
      const g = segAt(M.sel.i), can = canSplitRow(V().currentTime || 0);
      sel = `選んだ行: <b>${M.sel.i + 1}</b> <span class="mono">${h.fmtCs(g.start)} – ${h.fmtCs(g.end)}</span>` +
        ` <button type="button" class="btn small" data-act="rowsplit"${can ? '' : ' disabled'} title="${esc(can ? '再生位置(赤い線)でこの行を2つに分けます' : rowWhy() || '再生位置を行の中(端から 0.3 秒より内側)に置くと分けられます')}">再生位置でこの行を分ける</button>` +
        (rowEditable() ? '' : ` <span class="hint">${esc(rowWhy())}</span>`);
    }
    const snapTo = M.snap ? '吸い付く先: 字幕の行の端・無音の境目・再生位置・隣の区間の端(Alt を押している間は吸い付かない)' : '吸着: 切';
    st.innerHTML = `<span>残す <b>${n}区間</b></span><span>カット後 <b class="mono">${fmtF(kf)}</b> / 元 <span class="mono">${h.fmtCs(M.dur)}</span></span>${sel ? `<span>${sel}</span>` : ''}<span class="hint">${snapTo}</span>` +
      (M.origin && M.pristine ? `<span class="hint">(${M.origin === 'rows' ? '文字起こしの行から作ったたたき台' : '動画全体のたたき台'}。手で直すと保存します)</span>`
        : M.origin === 'whole' && M.clips.length === 1 ? '<span class="hint">(カットしない = 動画全体)</span>' : '') +
      (n > 0 && h.toPack ? '<button type="button" class="btn small ui-next-btn tt-cut-next" data-act="topack" title="カットを決めたら、3 パック のタブで Resolve へ渡すパックを作ります(Alt+3)">3 パックへ</button>' : '');   // 次の一手(M6)
  }
  function renderTools(){
    const ok = editable(), c2r = !!h.c2rBase(), busy = M.draftBusy;
    $('#cutUndo').disabled = !ok || !M.undo.length; $('#cutRedo').disabled = !ok || !M.redo.length;
    ['#cutSplit', '#cutDel', '#cutIO', '#cutZoomIn', '#cutZoomOut', '#cutZoomFit', '#cutPlay'].forEach(s => { $(s).disabled = !ok; });
    $('#cutDraftRows').disabled = !ok || busy; $('#cutEdgeGo').disabled = !ok || busy; $('#cutNone').disabled = !ok || busy;
    const why = c2r ? '' : '(cut2resolve を使います。ホームから開いたときだけ)';
    for (const s of ['#cutDraftSilence', '#cutDraftList']){ const d = $(s), sm = d.querySelector('summary'); sm.classList.toggle('disabled', !ok || !c2r || busy); sm.title = why || sm.dataset.title; if (!ok || !c2r) d.open = false; }
    const pb = $('#cutDraftPlan'); pb.hidden = !M.planBeside; pb.disabled = !ok || !c2r || busy; pb.title = why || ('作業用フォルダの ' + String(M.planBeside).split(/[\\/]/).pop() + '(スタジオなどの残す区間の指定)から');
    $('#cutIO').disabled = !ok || M.io.i === null || M.io.o === null || M.io.i === M.io.o;
    $('#cutIO').title = !$('#cutIO').disabled ? `始まりの印から終わりの印までを削ります(${IO_CUT_KEY})` : !ok ? '今はカットを変えられません' : `${pk('markIn') || 'I'}(始まり)と ${pk('markOut') || 'O'}(終わり)の印を付けると押せます`;   // 押せない理由(S16)
    $('#cutSnap').checked = M.snap;
    $('#cutModeSrc').setAttribute('aria-pressed', M.mode === 'src' ? 'true' : 'false'); $('#cutModeCut').setAttribute('aria-pressed', M.mode === 'cut' ? 'true' : 'false');
    $('#cutModePill').textContent = M.mode === 'cut' ? 'カット後の見え方' : '元の動画';
    const dc = $('#cutDocConflict'); if (dc) dc.hidden = !(ok && h.S.conflict);   // 文字起こしの保存の競合は、このタブにも出す(段6 6-6。行の時刻はここからも変えるため)
  }
  /* 右の字幕の一覧(押すとその位置へ・行ごとの「残す / カット済」の札。文字は直さない)。
     段7 E-25: 以前は「削る / 戻す」(押したらどうなるか)で、1 文字起こし の行の札「残す / カット済」(今の状態)と逆向きに読めた。
     同じ札・同じ言葉(用語集)・同じ見た目(カット済は赤)にそろえた。押したらどうなるかは title に */
  let sq = 0;
  function renderSubsSoon(){ if (!sq) sq = requestAnimationFrame(() => { sq = 0; renderSubs(); }); }
  function renderSubs(){
    const box = $('#cutSubs'), d = h.S.doc;
    if (!d || !M.shown){ return; }
    const rows = d.segments.map((g, i) => [g, i]).filter(([g]) => String(g.text || '').trim());
    if (!rows.length){   // 空の状態に次のボタン(段7 E-14): 1 文字起こし のタブの「この動画を文字起こしする」へ
      box.innerHTML = `<p class="hint tt-csub-empty">${d.model ? 'まだ字幕(文字のある行)がありません。1 文字起こし のタブで行を足すか、文字起こしし直すと、ここに出ます'
        : 'まだ文字起こししていません。文字起こしすると、ここに字幕が出ます(カットは文字起こしをしなくても決められます)'}</p>`
        + `<button type="button" class="btn small primary tt-csub-totx" data-act="totx">${d.model ? '1 文字起こし のタブへ' : '1 文字起こし のタブで文字起こしする'}</button>`;
      capIdx = -2; return;
    }
    const ok = editable();
    box.innerHTML = rows.map(([g, i]) => { const c = !!M.rowFlags[i];
      return `<div class="tt-csub${c ? ' cut' : ''}" data-i="${i}" role="listitem"><button type="button" class="tt-csub-go" data-act="go" title="この行の頭へ"><span class="mono">${h.fmtCs(g.start)}</span><span class="tx">${esc(g.text)}</span></button>` +
        h.keepCutHTML(c, ['keeprow', 'cutrow'], ok ? '' : ' disabled') + '</div>'; }).join('');   // 「残す / カット」の 2 択(1 文字起こし の行と同じ部品。M1)
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
    if (M.sel.kind === 'row') return h.toast('行の削除は 1 文字起こし のタブで。この行の時間をカットするなら、右の一覧のその行の「カット」を押してください', 4000);
    if (M.sel.kind === 'clip'){ const i = M.sel.i; change(cs => { cs.splice(i, 1); return cs; }); M.sel = null; render(); }
    else { const { a, b } = M.sel; change(cs => addRange(cs, a, b)); M.sel = null; render(); }
  }
  function cutIO(){
    const { i, o } = M.io; if (i === null || o === null || i === o) return h.toast(`${pk('markIn') || '始まりの印のキー'} で始まり、${pk('markOut') || '終わりの印のキー'} で終わりを決めてから(${IO_CUT_KEY})`, 3000);
    const a = Math.min(i, o), b = Math.max(i, o);
    if (change(cs => subtract(cs, a, b))){ M.io = { i: null, o: null }; render(); }
  }
  /* B-10: キーボードだけで区間・端を選ぶ。[ ] = 前/次の区間(選んでいなければ再生位置の前後)、Q / W = 選んだ区間(無ければ再生位置の区間)の始まり/終わりの端。
     端を選んだら , . で1コマ(Shift で10コマ)動かせる。選んだ所へ再生位置も動かす(すぐ聞ける・画面に入る) */
  function selectClip(i, edge){
    if (i < 0 || i >= M.clips.length) return false;
    M.sel = { kind: 'clip', i }; M.edge = edge || null;
    const [a, b] = M.clips[i];
    V().pause(); seekTo(f2s(edge === 'out' ? Math.max(a, b - 1) : a) + 0.0005);
    render(); renderSel();
    return true;
  }
  function stepClip(dir){
    if (!M.clips.length) return h.toast('残す区間がありません', 2500);
    let i;
    if (M.sel && M.sel.kind === 'clip') i = M.sel.i + dir;
    else {   // 選んでいなければ再生位置から: ] = 再生位置か、それより後に始まる区間(無ければ今いる区間)、[ = 再生位置より前に始まる区間(今いる区間を含む)
      const f = headFrame();
      i = dir > 0 ? M.clips.findIndex(c => c[0] >= f) : M.clips.map(c => c[0] < f).lastIndexOf(true);
      if (i < 0 && dir > 0) i = clipAt(f);
    }
    if (i < 0 || i >= M.clips.length) return h.toast(dir > 0 ? 'これより後に区間はありません' : 'これより前に区間はありません', 1500);
    selectClip(i, null);
  }
  function pickEdge(edge){
    if (M.sel && M.sel.kind === 'row' && segAt(M.sel.i)){   // 字幕の段の行の端(段6 6-3)
      const g = segAt(M.sel.i); M.edge = edge; V().pause(); seekTo((edge === 'out' ? Math.max(g.start, g.end - frameSec()) : g.start) + 0.0005); render(); renderSel(); return;
    }
    const i = M.sel && M.sel.kind === 'clip' ? M.sel.i : clipAt(headFrame());
    if (i < 0) return h.toast('[ ] で区間を選ぶか、残す区間の中に再生位置を置いてから', 3000);
    selectClip(i, edge);
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
  /* ---------- 字幕の段の行(段6 6-3〜6-6。git の履歴(679ff01 以前)の docs/plan/phase6-edit-features.md)。文書の時刻を書き、残す行を外へ広げたら残す区間も広げる ---------- */
  const segAt = i => (h.S.doc && Number.isInteger(i) ? h.S.doc.segments[i] : null);
  const rowEditable = () => editable() && !h.S.conflict && !(h.lockJob && h.lockJob());
  const rowWhy = () => !editable() ? '' : h.S.conflict ? '文字起こしの保存が競合しています(1 文字起こし の映像の上の案内から選んでください)' : (h.lockJob && h.lockJob()) ? '処理中(話者判別・再認識)のため、今は行を動かせません' : '';
  const r2 = v => Math.round(v * 100) / 100;
  function rowBounds(i, edge){   // フレーム。前後の行を越えない(重ならない)・長さは1フレーム以上
    const segs = h.S.doc.segments, g = segs[i], a = s2f(g.start), b = s2f(g.end);
    if (edge === 'in'){ const lo = i > 0 ? s2f(segs[i - 1].end) : 0; return [Math.min(lo, b - 1), b - 1]; }
    const hi = i < segs.length - 1 ? s2f(segs[i + 1].start) : M.total; return [a + 1, Math.max(hi, a + 1)];
  }
  function startRowDrag(e, i, edge){
    e.preventDefault(); e.stopPropagation();
    const g = segAt(i); if (!g || !rowEditable()) return;
    M.sel = { kind: 'row', i }; M.edge = edge;
    const own = [s2f(g.start), s2f(g.end)];
    M.rdrag = { i, edge, start: own[edge === 'in' ? 0 : 1], cur: null, targets: snapTargets(-1).filter(t => !own.includes(t)), bounds: rowBounds(i, edge), pid: e.pointerId };
    try { e.target.setPointerCapture(e.pointerId); } catch {}
    document.querySelectorAll('#tlSubs .tt-rh').forEach(x => x.classList.toggle('on', x.dataset.edge === edge));
    cutKeybarScene();
  }
  function moveRowDrag(e){
    const d = M.rdrag; if (!d) return;
    const raw = frameFromEvent(e), s = snapFrame(raw, d.targets, e.altKey);
    const f = Math.max(d.bounds[0], Math.min(d.bounds[1], s.f));
    d.cur = f;
    const g = segAt(d.i), a = d.edge === 'in' ? f : s2f(g.start), b = d.edge === 'out' ? f : s2f(g.end);
    const el = document.querySelector(`#tlSubs .tt-s[data-i="${d.i}"]`);
    if (el){ el.style.left = X(a) + 'px'; el.style.width = Math.max(2, X(b) - X(a) - 2) + 'px'; }
    const dlt = f2s(f - d.start);
    showTip(f, `行の${d.edge === 'in' ? '始まり' : '終わり'} ${fmtF(f)}(${dlt >= 0 ? '+' : ''}${dlt.toFixed(2)}秒)`, s.snapped);
  }
  function endRowDrag(cancel){
    const d = M.rdrag; if (!d) return;
    M.rdrag = null; hideTip();
    if (cancel === true || d.cur === null || d.cur === d.start){ render(); return; }
    applyRowEdge(d.i, d.edge, d.cur);
  }
  /* 行の端を f(フレーム)に。文書の時刻(0.01 秒に丸める)を書き、残す行を外へ広げた分が削る区間に入るなら区間も足す(6-4。縮めても区間は変えない)。
     1回の操作 = 文書の元に戻す(app.js)とカットの元に戻すに同じ番号で積む → Ctrl+Z で両方戻る。保存は編集の内容を先・文書を後(6-6) */
  function applyRowEdge(i, edge, f){
    const g = segAt(i); if (!g || !rowEditable()) return false;
    const segs = h.S.doc.segments, old = edge === 'in' ? g.start : g.end;
    let v = r2(f2s(f));
    if (edge === 'in'){ const lo = i > 0 ? segs[i - 1].end : 0, hi = r2(g.end - 0.01); v = Math.min(hi, Math.max(Math.min(lo, hi), v)); }
    else { const lo = r2(g.start + 0.01), hi = i < segs.length - 1 ? segs[i + 1].start : M.dur; v = Math.max(lo, Math.min(Math.max(hi, lo), v)); }
    v = r2(v);
    if (v === old){ render(); return false; }
    const seq = opSeq();
    h.pushUndo(seq);
    if (edge === 'in') g.start = v; else g.end = v;
    let widened = false;
    if (!M.pristine && !M.rowFlags[i]){   // 残す行を外へ広げた分が削る区間に入るなら、その分だけ区間も足す(たたき台のままなら「行から」の作り直しに任せる)
      const [p, q] = edge === 'in' ? [s2f(v), s2f(old)] : [s2f(old), s2f(v)];
      if (q > p && gaps().some(([a, b]) => a < q && b > p)){
        const before = M.clips.map(c => c.slice()), next = addRange(M.clips.map(c => c.slice()), p, q);
        if (JSON.stringify(next) !== JSON.stringify(before)){
          pushCutUndo(before, M.origin, seq);
          M.clips = next; M.origin = 'manual'; widened = true;
          M.dirty = true; save();   // 編集の内容を先に保存(文書は h.rowChanged → 0.7 秒後。文書の保存で行の印を新しい区間から付け直す)
        }
      }
    }
    h.rowChanged(i);   // 1 文字起こし のタブを描き直し、文書を保存(markDirty → CUT.docChanged)
    syncRowCuts(); render();
    if (widened) h.toast('行に合わせて残す区間も広げました(元に戻すで両方戻ります)', 3500);
    return true;
  }
  function nudgeRowEdge(dir){
    const i = M.sel.i, g = segAt(i); if (!g || !M.edge) return;
    const [lo, hi] = rowBounds(i, M.edge), f = Math.max(lo, Math.min(hi, s2f(M.edge === 'in' ? g.start : g.end) + dir));
    applyRowEdge(i, M.edge, f);
  }
  /* 行を分ける(6-5): 再生位置(行の端から 0.3 秒より内側)で。文字の分け目は時刻の比で決めた位置を初期値に、小さな欄で人が直して Enter */
  function canSplitRow(t){ const g = M.sel && M.sel.kind === 'row' ? segAt(M.sel.i) : null; return !!(g && rowEditable() && String(g.text || '').trim().length >= 2 && t > g.start + 0.3 && t < g.end - 0.3); }
  function syncSplitBtn(t){ const b = document.querySelector('#cutStatus [data-act=rowsplit]'); if (b){ const can = canSplitRow(t); if (b.disabled === can) b.disabled = !can; } }
  function splitRow(){
    if (!M.sel || M.sel.kind !== 'row') return;
    const i = M.sel.i, g = segAt(i); if (!g) return;
    if (!rowEditable()) return h.toast(rowWhy() || '行を選んでから', 3000);
    const text = String(g.text || ''), t = V().currentTime || 0;
    if (text.trim().length < 2) return h.toast('短すぎて分割できません', 2500);
    if (!(t > g.start + 0.3 && t < g.end - 0.3)) return h.toast('再生位置(赤い線)を行の中(端から 0.3 秒より内側)に置いてから', 3000);
    const cut = r2(t), pos = Math.max(1, Math.min(text.length - 1, Math.round(text.length * (cut - g.start) / (g.end - g.start))));
    const dlg = $('#cutSplitDlg'), inp = $('#cutSplitText');
    inp.value = text; $('#cutSplitAt').textContent = h.fmtCs(cut);
    M.splitPending = { i, g, text, cut };   // Enter・「分ける」で commitSplit(dialog の close イベントは遅れて来るので、それには頼らない)
    dlg.returnValue = ''; dlg.showModal(); inp.focus(); try { inp.setSelectionRange(pos, pos); } catch {}
  }
  function commitSplit(){
    const sp = M.splitPending; M.splitPending = null; if (!sp) return;
    const dlg = $('#cutSplitDlg'), inp = $('#cutSplitText'), p = inp.selectionStart, { i, g, text, cut } = sp;
    if (dlg.open) dlg.close('ok');
    if (!(p > 0 && p < text.length)) return h.toast('文字の中(先頭・末尾以外)にカーソルを置いて「分ける」を押してください', 3500);
    if (M.docId !== h.S.docId || segAt(i) !== g) return h.toast('文書が変わったので分けませんでした', 3000);
    if (h.splitRowAt(i, p, cut)){ M.sel = { kind: 'row', i: i + 1 }; M.edge = null; syncRowCuts(); render(); h.toast('行を2つに分けました(元に戻すで戻ります)', 2500); }
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

  /* ドラッグ中の端の位置の札(f フレーム)と、吸い付いた印(吸い付いた所 = f のときだけ) */
  function showTip(f, text, snapped){
    const tip = $('#tlTip'); tip.hidden = false; tip.style.left = X(f) + 'px'; tip.textContent = text;
    const sn = $('#tlSnap'); sn.hidden = snapped === null || f !== snapped; if (!sn.hidden) sn.style.left = X(f) + 'px';
  }
  function hideTip(){ $('#tlTip').hidden = true; $('#tlSnap').hidden = true; }

  /* ---------- ドラッグ(区間の端) ---------- */
  function startDrag(e, i, edge){
    e.preventDefault(); e.stopPropagation();
    M.sel = { kind: 'clip', i }; M.edge = edge;
    M.drag = { i, edge, start: M.clips[i][edge === 'in' ? 0 : 1], before: M.clips.map(c => c.slice()), origin: M.origin, targets: snapTargets(i), pid: e.pointerId };
    try { e.target.setPointerCapture(e.pointerId); } catch {}
    document.querySelectorAll('#tlVideo .tt-h').forEach(x => x.classList.toggle('on', x.dataset.edge === edge));
    cutKeybarScene();   // 端を選んだ(ドラッグしなくても)ので、下の帯を「, . 1コマ」の場面に
  }
  function moveDrag(e){
    const d = M.drag; if (!d) return;
    const raw = frameFromEvent(e), s = snapFrame(raw, d.targets, e.altKey);
    const cs = M.clips.map(c => c.slice());
    if (setEdge(cs, d.i, d.edge, s.f) || cs[d.i][d.edge === 'in' ? 0 : 1] !== M.clips[d.i][d.edge === 'in' ? 0 : 1]) M.clips = cs;
    const cur = M.clips[d.i][d.edge === 'in' ? 0 : 1], dlt = cur - d.start;
    showTip(cur, `${d.edge === 'in' ? '始まり' : '終わり'} ${fmtF(cur)}(${dlt >= 0 ? '+' : ''}${dlt}フレーム)`, s.snapped);
    const el = document.querySelector(`#tlVideo .tt-k[data-i="${d.i}"]`), [a, b] = M.clips[d.i];
    if (el){ el.style.left = X(a) + 'px'; el.style.width = Math.max(1, X(b) - X(a)) + 'px'; }
    document.querySelectorAll('#tlVideo .tt-x').forEach(x => x.remove());
    $('#tlVideo').insertAdjacentHTML('beforeend', gapsHTML());
    renderStatus();
  }
  function endDrag(cancel){
    const d = M.drag; if (!d) return;
    M.drag = null; hideTip();
    if (cancel === true){ M.clips = d.before; render(); return; }
    if (JSON.stringify(d.before) !== JSON.stringify(M.clips)){
      pushCutUndo(d.before, d.origin, opSeq()); M.origin = 'manual';
      afterChange();
    } else render();
  }

  /* ---------- イベント ---------- */
  function bind(){
    const sc = scroller();
    $('#cutRelink').addEventListener('click', () => { if (h.relink) h.relink(); });
    $('#cutRetry').addEventListener('click', () => { if (M.docId) load(M.docId); });
    sc.addEventListener('scroll', () => { if (ready()) { if (!bind.q) bind.q = requestAnimationFrame(() => { bind.q = 0; scrolled(); }); } });
    /* 段3: ホイールで拡大縮小(Ctrl は要らない。マウスの位置が中心)。Shift+ホイールは横に移動(縦のホイールを横の移動に読み替える) */
    sc.addEventListener('wheel', e => {
      if (!ready()) return; e.preventDefault();
      /* トラックパッドの横スワイプ(deltaX が主)は横に流す。縦のホイール(deltaY が主)だけ拡大縮小にする */
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)){ sc.scrollLeft += (e.deltaX || e.deltaY); return; }
      if (!e.deltaY) return;
      const r = sc.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.25 : 0.8, e.clientX - r.left);
    }, { passive: false });
    bindMini();
    $('#tlContent').addEventListener('pointerdown', e => {
      if (!editable() || e.button !== 0) return;
      const rh = e.target.closest('.tt-rh');
      if (rh){ const s0 = rh.closest('.tt-s'); if (s0) startRowDrag(e, Number(s0.dataset.i), rh.dataset.edge); return; }   // 行のつまみ(字幕の段)は区間より先に見る
      const hd = e.target.closest('.tt-h');
      if (hd){ const k = hd.closest('.tt-k'); startDrag(e, Number(k.dataset.i), hd.dataset.edge); return; }
      const k = e.target.closest('.tt-k');
      if (k){ const i = Number(k.dataset.i); M.sel = { kind: 'clip', i }; M.edge = null; renderSel(); sc.focus({ preventScroll: true }); return; }   // 区間の本体を押しただけでは端は選ばない(つまみ .tt-h を押したときだけ startDrag で選ぶ)。端が無ければ ,. は再生位置を送る
      const x = e.target.closest('.tt-x');
      if (x){ M.sel = { kind: 'gap', a: Number(x.dataset.a), b: Number(x.dataset.b) }; M.edge = null; renderSel(); sc.focus({ preventScroll: true }); return; }
      const s = e.target.closest('.tt-s');
      if (s){ const i = Number(s.dataset.i), g = h.S.doc.segments[i]; if (g){ M.sel = { kind: 'row', i }; M.edge = null; seekTo(g.start + 0.0005); renderSel(); sc.focus({ preventScroll: true }); } return; }   // 行を選ぶ(段6 6-3)+ 頭へ
      // 目盛り・空いた所: 再生位置を動かす(ドラッグで動かし続ける)
      M.sel = null; seekTo(f2s(frameFromEvent(e)) + 0.0005); renderSel();
      dragOnWindow(ev => seekTo(f2s(frameFromEvent(ev)) + 0.0005));
      sc.focus({ preventScroll: true });
    });
    window.addEventListener('pointermove', e => { if (M.drag) moveDrag(e); else if (M.rdrag) moveRowDrag(e); });
    window.addEventListener('pointerup', () => { if (M.drag) endDrag(); else if (M.rdrag) endRowDrag(); });
    window.addEventListener('pointercancel', () => { if (M.drag) endDrag(true); else if (M.rdrag) endRowDrag(true); });
    $('#cutStatus').addEventListener('click', e => { if (e.target.closest('[data-act=rowsplit]')) splitRow(); else if (e.target.closest('[data-act=topack]') && h.toPack) h.toPack(); });
    $('#cutSplitCancel').addEventListener('click', () => { M.splitPending = null; $('#cutSplitDlg').close(''); });
    $('#cutSplitDlg').addEventListener('close', () => { if ($('#cutSplitDlg').returnValue !== 'ok') M.splitPending = null; });   // Esc で閉じた
    $('#cutSplitDlg form').addEventListener('submit', e => { e.preventDefault(); commitSplit(); });   // 「分ける」ボタン
    $('#cutDocConflictGo').addEventListener('click', () => { location.hash = '#tx'; });
    $('#cutSubs').addEventListener('click', e => {
      const b = e.target.closest('[data-act]'); if (!b) return;
      if (b.dataset.act === 'totx'){ if (h.toTx) h.toTx(); return; }   // 字幕の無い文書: 1 文字起こし のタブの「文字起こしする」へ(段7 E-14)
      const i = Number(b.closest('.tt-csub').dataset.i), g = h.S.doc && h.S.doc.segments[i]; if (!g) return;
      if (b.dataset.act === 'go') seekTo(g.start + 0.0005);
      else if (b.dataset.act === 'cutrow' || b.dataset.act === 'keeprow'){ const want = b.dataset.act === 'cutrow'; if (!!M.rowFlags[i] !== want) rowsCut([i], want); }   // 押した側の状態に(M1)
    });
    $('#cutPlay').addEventListener('click', togglePlay);
    $('#cutSplit').addEventListener('click', split);
    $('#cutDel').addEventListener('click', delOrRestore);
    $('#cutIO').addEventListener('click', cutIO);
    $('#cutUndo').addEventListener('click', undoNewest);
    $('#cutSplitText').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing){ e.preventDefault(); commitSplit(); } });   // Enter = 分ける(暗黙の送信に頼らない)
    $('#cutRedo').addEventListener('click', redo);
    $('#cutZoomIn').addEventListener('click', () => zoom(1.5));
    $('#cutZoomOut').addEventListener('click', () => zoom(1 / 1.5));
    $('#cutZoomFit').addEventListener('click', () => { M.fit = true; render(); });
    $('#cutSnap').addEventListener('change', e => { M.snap = e.target.checked; renderStatus(); });
    for (const [id, mode] of [['#cutModeSrc', 'src'], ['#cutModeCut', 'cut']]) $(id).addEventListener('click', () => { M.mode = mode; capIdx = -2; renderTools(); moveHead(); });
    $('#cutDraftRows').addEventListener('click', draftRows);
    $('#cutNone').addEventListener('click', draftWhole);
    $('#cutRowEdge').addEventListener('toggle', () => { if ($('#cutRowEdge').open) fillEdge(); });
    for (const id of ['#cutEdgeOn', '#cutEdgeAfter', '#cutEdgeBefore']) $(id).addEventListener('change', saveEdge);
    $('#cutEdgeGo').addEventListener('click', async () => { if (!(await saveEdge())) return; $('#cutRowEdge').open = false; draftRows(); });
    $('#cutDraftSilenceGo').addEventListener('click', () => draftC2R('silence'));
    $('#cutDraftSilence').addEventListener('toggle', () => { if ($('#cutDraftSilence').open) fillSil(); });   // 覚えた値を入れる(段7 E-5)
    for (const [, id] of SIL_FIELDS) $(id).addEventListener('change', saveSil);
    $('#cutDraftListGo').addEventListener('click', () => draftC2R('list'));
    $('#cutDraftPlan').addEventListener('click', () => draftC2R('plan'));
    document.querySelectorAll('#tabCut details.pop > summary').forEach(s => { s.dataset.title = s.title; s.addEventListener('click', e => { if (s.classList.contains('disabled')){ e.preventDefault(); h.toast(s.title || '今は使えません', 3000); } }); });
    $('#cutReload').addEventListener('click', reloadFromServer);
    $('#cutForce').addEventListener('click', e => { if (!M.conflict) return; if (window.UIKit && UIKit.confirmTwice) UIKit.confirmTwice(e.currentTarget, () => { if (M.conflict) save(true); }); else save(true); });   // 保存済みのカットを上書きする(戻せない)= 二度押し(1 文字起こし の #cfForce と同じ。M4)
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
  /* 共通の再生キー(段3)に渡す「メディア」: 生の <video> をそのまま渡すと、Space/L の再生開始が cut.js の
     「カット後は削る区間を飛ばす」の頭出し(togglePlay)を通らない・, . / J K の秒がフレームの境目からずれる(浮動小数の蓄積)ので、
     このオブジェクトを挟んで、実際の操作は今までの関数(togglePlay・seekTo)に委ねる */
  const mediaProxy = {
    get paused(){ return V().paused; },
    get currentTime(){ return V().currentTime; },
    set currentTime(t){ seekTo(t); },
    get playbackRate(){ return V().playbackRate; },
    set playbackRate(r){ V().playbackRate = r; },
    /* play/pause は呼ばれる前に呼び手(ui-kit の K など)が V().paused を読んでいるとは限らない(K は無条件に pause() を呼ぶ)。
       togglePlay() は「今止まっているか」で再生/一時停止を選ぶので、素通しすると既に止まっている状態で pause() を呼んだときに
       逆に再生が始まってしまう。止まっているかを自分でも見てから、要るときだけ togglePlay() に委ねる */
    play(){ if (V().paused) togglePlay(); },
    pause(){ if (!V().paused) togglePlay(); }
  };
  const commonKeys = window.UIKit && UIKit.keys ? UIKit.keys.playback({
    media: () => mediaProxy, fps: () => (M.fps ? M.fps[0] / M.fps[1] : 30), keymap: () => (h.keymap ? h.keymap() : null),   // 再生のキーの割り当て(編集の ⚙ 設定の「キー配置」)
    enabled: () => h.tab() === 'cut' && ready() && !h.modalOpen() && !(h.menuHasKeys && h.menuHasKeys(document.activeElement)),
    onIn: () => { if (editable()){ M.io.i = headFrame(); render(); } },
    onOut: () => { if (editable()){ M.io.o = headFrame(); render(); } },
    /* , . : 端を選んでいればその端を1コマ(nudgeEdge)、そうでなければ再生位置を1コマ(stepFrames。フレームの境目に必ず揃える) */
    onFrame: dir => { if (editable() && M.sel && M.sel.kind === 'clip' && M.edge) nudgeEdge(dir); else if (M.sel && M.sel.kind === 'row' && M.edge && rowEditable()) nudgeRowEdge(dir); else stepFrames(dir); return true; },
    onKey: () => { moveHead(); keepHeadVisible(); }   // 共通キーは v.currentTime を直に書くので、タイムラインの追従はここで
  }) : null;
  function onKey(e){
    if (h.tab() !== 'cut' || !h.S.doc || e.isComposing || e.keyCode === 229 || h.modalOpen() || h.isTextEntry(e.target)) return;
    if (h.menuHasKeys && h.menuHasKeys(e.target)) return;   // 重ねて開いたメニューの中では、メニューの操作を優先する(GPT-04)
    if (e.altKey && !e.ctrlKey && !e.metaKey && /^Digit/.test(e.code)) return;   // Alt+1/2/3 はタブ(app.js)
    const k = e.key, ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && (k === 'z' || k === 'Z')){ e.preventDefault(); if (e.shiftKey) redo(); else undoNewest(); return; }
    if (ctrl && (k === 'y' || k === 'Y')){ e.preventDefault(); redo(); return; }
    if (ctrl || e.altKey) return;
    if (!ready()) return;
    const run = fn => { e.preventDefault(); fn(); };
    /* Shift+, / Shift+. : 選んだ端を10コマ(共通キーは Shift つきの , . を処理しないので、ここで先に扱う)。
       Shift を押すと e.key は ","."" ではなく "<"">"" になる(US 配列)ので、物理キーの e.code で見る */
    /* 1コマのキーが , . のままなら物理キー(e.code)で、英字などに変えていれば「そのキー + Shift」で */
    const fm = pkMap(), sc = e.shiftKey && window.UIKit && UIKit.keys ? UIKit.keys.comboOf(e) : '';
    const tenDir = !e.shiftKey ? 0 : (e.code === 'Comma' && fm.frameBack === ',') || (fm.frameBack && sc === 'Shift+' + fm.frameBack) ? -1 : (e.code === 'Period' && fm.frameFwd === '.') || (fm.frameFwd && sc === 'Shift+' + fm.frameFwd) ? 1 : 0;
    if (tenDir && editable() && M.sel && M.sel.kind === 'clip' && M.edge) return run(() => nudgeEdge(tenDir * 10));
    if (tenDir && M.sel && M.sel.kind === 'row' && M.edge && rowEditable()) return run(() => nudgeRowEdge(tenDir * 10));
    if ((e.code === 'ArrowLeft' || e.code === 'ArrowRight') && e.target && e.target.closest && e.target.closest('#edTabs')) return;   // タブの並びの中は #edTabs 自身の ← → 処理(タブ切り替え)に任せる
    if (commonKeys && commonKeys(e)) return;
    switch (e.code){
      case 'Home': return run(() => seekTo(0));
      case 'End': return run(() => seekTo(M.dur));
    }
    if (e.shiftKey && k !== '+') return;
    if (!editable()) return;
    switch (k){
      case 's': case 'S': return run(split);
      case '[': return run(() => stepClip(-1));
      case ']': return run(() => stepClip(1));
      case 'q': case 'Q': return run(() => pickEdge('in'));
      case 'w': case 'W': return run(() => pickEdge('out'));
      case 'Delete': case 'Backspace': return run(delOrRestore);
      case IO_CUT_KEY.toLowerCase(): case IO_CUT_KEY: return run(cutIO);   // 始まりの印〜終わりの印を削る(外す)。以前の X は 1 文字起こし の「聞き取れない」と重なっていた(M2。仮決め (ay))
      case '+': case '=': return run(() => zoom(1.5));
      case '-': return run(() => zoom(1 / 1.5));
      case 'Escape': if (M.sel || M.io.i !== null || M.io.o !== null){ run(() => { M.sel = null; M.io = { i: null, o: null }; render(); }); } return;
    }
  }
  function onShown(fromLoad){
    M.shown = true;
    cutKeybarScene(); renderKeysText();
    if (fromLoad !== true && M.offCode === 'edit_load' && M.docId && M.loaded){ load(M.docId); return; }   // 保存済みのカットを読めなかった: タブを開き直したら読み直す(監査 13)
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
    if (M.rdrag) endRowDrag();
    save();
  }

  bind();
  return {
    load, flush, docChanged, rowsCut, onShown, onHidden,
    active: () => ready(),
    refresh: () => render(),   // cut2resolve が使えるか分かったとき(たたき台のボタン)
    refreshCaption(){ capIdx = -2; if (ready()) showCaption(V().currentTime || 0); },   // 話者の色が変わったとき(app.js の onSpeakerColors。段2)
    /* 3 パック の「行の後の余白」を変えたとき(段6 6-2): たたき台のまま(手で直していない)なら「行から」を作り直す(→ true)。手で直したカットは触らない(→ false) */
    redraftPristine(){ if (!ready() || !M.pristine || !(M.origin === 'rows' || M.origin === 'all')) return false; M.lastDraftSig = ''; docChanged(); return true; },
    unload(){ M.loading++; reset(null); render(); },
    summary(){ return ready() ? { count: mergedCount(M.clips), keptSec: f2s(keptFrames(M.clips)), durSec: M.dur, pristine: M.pristine } : null; },
    state(){ return { dirty: M.dirty, saving: !!M.saving, conflict: !!M.conflict, rev: M.rev, off: M.off, offCode: M.offCode, loaded: M.loaded, docId: M.docId, pristine: M.pristine, origin: M.origin }; },
    keepsSec(){ return ready() ? M.clips.map(([a, b]) => [sec3(a), sec3(b)]) : null; },
    fps(){ return M.fps; },
    /* 1 文字起こし の「元に戻す」から(段3 3-5): 一番上の操作の番号(使えないとき・空なら 0)・1つ戻す(戻したら true)・積んでいる数 */
    undoTop(){ return ready() && M.undo.length ? (M.undo[M.undo.length - 1].seq || 0) : 0; },
    undo(){ if (!ready() || !M.undo.length) return false; if (M.drag) endDrag(); if (M.rdrag) endRowDrag(true); undo(); return true; },
    undoCount(){ return ready() ? M.undo.length : 0; },
    /* 1 文字起こし の「1コマ」(段3 3-4 監査 15): t 秒から n コマ動いた時刻(フレームの境目 + 0.5ms。stepFrames と同じ丸め = 2 カット と同じ位置に止まる)。
       fps が分からない(読み込み前・動画が無い・音声だけ)・別の文書なら null */
    frameStep(t, n){
      if (!M.fps || M.docId !== h.S.docId) return null;
      const f = Math.max(0, s2f(t || 0) + n);
      return f2s(M.total ? Math.min(M.total, f) : f) + 0.0005;
    },
    /* パックを作る前: まだ保存していない下書きも保存して、保存済みのカット(rev)から作れるようにする。-> 保存できたか */
    async commit(){
      if (!ready()) return false;
      if (M.drag) endDrag();
      if (M.pristine){ M.pristine = false; M.dirty = true; }
      if (M.dirty || M.saving) await save();
      return !M.dirty && !M.conflict && M.rev > 0;
    },
    _debug: M
  };
}
window.EditCut = { create, KEY_ROWS, FIXED_KEYS };
})();
