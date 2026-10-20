/* app-list.js — 「編集」の画面: 保存済み一覧の読み込み・題名の行の「まとめて実行」。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は src/app/ui/cases/edhost.js の ED_SCRIPTS の1か所) */
'use strict';

/* ---------- 保存済み一覧 ----------
   サーバーの /api/transcripts が、校正の進み具合・長さ・元の配信・配信者・元の動画とパックの有無を返す(serve.py の list_transcripts)。
   開いている文書の項目(curItem)から、題名の行の配信者・長さ・カットの有無を引く */

async function loadList(){
  try { S.list = (await api('/api/transcripts')).items; } catch { S.list = []; }
  if (S.doc){ renderCutPack(); renderDocBar(); }
}

/* ---------- 題名の行の「まとめて実行」(入口の ② の口 /api/flow/submit = UIKit.flow.order。入口から開いたときだけ) ---------- */

/* 入口の API(/api/...)。画面は入口の /transcribe/ の下にあるので、画面の場所から1つ上(UIKit.homeApi。絶対パスを書かない。エラーの形は api() と同じ) */
function portalApi(path, body){
  return UIKit.homeApi(path, { body, offline: 'ホームのサーバーに接続できません(start.bat の黒い画面が閉じていないか確かめてください)', fail: httpFailText });
}

/* ホームから開いていない(合言葉なし)ときの「まとめて実行」: 隠さず、押せない見た目と理由を出す(機能があること自体が分かるように) */
const NEED_HOME = 'ホーム(start.bat)から開くと使えます(まとめて実行はホームの順番待ちで進みます)';
function applyNeedHome(){
  if (!TOKEN) UIKit.menuOff($('#docAuto'), NEED_HOME);   // 押しても開かずに理由を知らせる(ui-kit v21 の共通の書き方。Enter・Space も)
}

/* 実行の札の色と、手順ごとの状態の 1 行 */
const runCls = r => r.nothing ? 'info' : RUN_CLS[r.state] || 'info';
const runStepsText = r => (r.steps || []).map(s => `${s.label}: ${stepLabelOf(s)}${s.detail ? '(' + s.detail + ')' : ''}`).join(' / ') + (r.error ? ' ・ ' + r.error : '');

async function pollRuns(){
  clearTimeout(RUNS.polling);
  if (!TOKEN) return;
  let runs = [];
  try { runs = ((await portalApi('api/flow/runs')).runs || []).filter(r => r.kind === 'doc'); } catch { return; }
  RUNS.last = runs; renderDocAuto(runs);
  const active = new Set(runs.filter(r => r.state === 'queued' || r.state === 'running').map(r => r.id));
  if ([...RUNS.active].some(id => !active.has(id))) loadList();   // 終わった実行があれば、一覧の項目(パックの有無など)を今の状態に
  RUNS.active = active;
  if (active.size) RUNS.polling = setTimeout(pollRuns, 2000);
}

/* 今の文書を最後まで(題名の行の「まとめて実行 ▾」):入口の API を1本で。
   先に文書を保存する(まとめて実行は保存済みの内容を読む)。進み具合は pollRuns が題名の行の札に出す */
async function startDocAuto(){
  const id = S.docId; if (!id || !TOKEN) return;
  const b = $('#docAutoGo'); b.disabled = true;
  try {
    if (!(await savedAll())) return;
    const who = await UIKit.streamer.check($('#docAutoWho'));
    if (who === null) return;   // 見つからない名前で「やめる」を選んだ
    const order = UIKit.flow.order({ kind: 'docs', docId: id, repack: $('#docAutoOverwrite').checked, streamer: who });   // 空 = 色なし(欄は自動で入る)
    const r = await UIKit.autorun.start([order]);   // 見積もり → 始める → 終わったら知らせる(どの入口も同じ部品)
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
  const step = (r.steps || []).find(s => s.state === 'run');
  pill.className = 'pill ' + runCls(r); pill.hidden = false;
  pill.textContent = 'まとめて実行: ' + runLabelOf(r) + (step ? '(' + step.label + ')' : '');
  pill.title = runStepsText(r);
}

/* 保存したら、一覧の項目も今の内容に合わせる(一覧を読み直さずに) */
function syncListItem(){
  const d = S.doc, it = d && curItem(); if (!it) return;
  const segs = d.segments, txt = segs.filter(hasText);
  Object.assign(it, { title: d.title, evalSet: d.evalSet === true, segments: segs.length, rows: txt.length, proofed: txt.filter(g => g.proofed).length,
    cut: segs.filter(g => g.cutState === 'cut').length, flagged: segs.filter(g => g.flag).length, updatedAt: S.baseUpdatedAt || it.updatedAt });
}
