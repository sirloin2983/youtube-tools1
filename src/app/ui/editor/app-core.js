/* app-core.js — 「編集」の画面: 共通の小道具・表示の好み・⚙・取り込まれたツールの場所・設定。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は src/app/ui/cases/edhost.js の ED_SCRIPTS の1か所) */
'use strict';

/* ---------- 共通 ---------- */

/* 文書の小さな部品は doc-kit.js(カット・パックのパネルと共用。この後の部品より先に読む) */
const { OTHER_SP, isOtherSp, fmtT, fmtCs, hasText, uid, segIndexAt, subColorOf, safeName, download, keepCutHTML } = EditDoc;

/* SVG の線のアイコン(UIKit.icon)の文字列。文字記号(✓ × ⋮ ▶)の代わり。ui-kit は必ず先に読み込む */
function uiIcon(name, opts){ return UIKit.icon(name, opts); }

/* kind: 'ok' | 'err' | 'info'(左の色の印。省略可)。ui-kit の UIKit.toast を呼ぶだけ(重ねて最大3つ・入れ物は #toast) */
function toast(msg, ms, kind = ''){   // ms にオブジェクト({ms, kind, action})を渡せば、そのまま UIKit.toast へ(ボタンつきの知らせ)
  return UIKit.toast(msg, ms && typeof ms === 'object' ? ms : { ms, kind });
}

/* 画面の赤い帯:何が起きたか + 次の一手([読み込み直す]・ホームから開いたときは [ホームへ])+ 閉じる(×)。
   opt.plain: msg をそのまま本文に(起動の失敗など、文が決まっているもの)。そうでなければ決まった文 + 原文は「詳しく」の中。
   版の違いの帯(UIKit.restart の「起動し直す」)が出ている間は上書きしない(起動し直すと直ることが多い) */
function showErr(msg, opt = {}){
  const b = $('#errBar'); if (!b || b.querySelector('.ui-restart-msg')) return;
  const el = (tag, cls, text) => { const x = document.createElement(tag); if (cls) x.className = cls; if (text !== undefined) x.textContent = text; return x; };
  b.textContent = '';
  b.append(el('span', 'tt-err-msg', opt.plain ? String(msg) : '画面でエラーが起きました。編集した内容は自動で保存しています(保存の状態は右上)。画面の動きがおかしいときは「読み込み直す」を押してください。'));
  if (!opt.plain){ const d = el('details', 'tt-err-detail'); d.append(el('summary', '', '詳しく'), el('span', '', String(msg).slice(0, 500))); b.append(d); }
  const acts = el('span', 'tt-err-acts'), reload = el('button', 'btn small', '読み込み直す');
  reload.type = 'button'; reload.addEventListener('click', () => location.reload()); acts.append(reload);
  if (document.querySelector('meta[name="ytt-token"]')){ const home = el('a', 'btn small', 'ホームへ'); home.href = '../'; home.setAttribute('data-ui-portal', ''); acts.append(home); }   // ホームから開いたときだけ(入口の / = この画面の 1 つ上)。TOKEN は app.js の読み込み前のエラーでも使えるように直接見る
  const x = el('button', 'btn small ghost icon tt-err-x'); x.type = 'button'; x.innerHTML = uiIcon('close', { size: 14 }); x.setAttribute('aria-label', 'エラーの帯を閉じる'); x.title = 'エラーの帯を閉じる'; x.addEventListener('click', () => { b.hidden = true; }); acts.append(x);
  b.append(acts); b.hidden = false;
}

/* 知らせの次の一手:「元に戻す」(校正の元に戻す)・「カット・パックへ」(タブの切り替えは殻のもの) */
function undoToast(msg, ms = 5000){ return toast(msg, { kind: 'ok', ms, action: { label: '元に戻す', fn: () => doUndo('tx') } }); }
const TO_CUT = Object.freeze({ label: 'カット・パックへ', fn: () => EDIT_HOST.tab('cut') });

/* ---------- 区間の終わりで止める見張り(「この行だけ再生」・▶・評価ドリルの帯の「聞く」・端を動かしたあとの聞き直し) ----------
   timeupdate(Chromium で約 250ms ごと)で止めると行の終わりを平均 約 116ms 過ぎ、機械の行の終わりは次の声の出だしの
   0.05〜0.1 秒前にあることが多いので、次の行の頭の言葉が聞こえてしまう。そのため
   ここでは終わりの手前までは setTimeout で眠り(残り時間 ÷ 再生の速さ。長く眠りすぎないよう 0.5 秒まで)、近づいたら requestVideoFrameCallback(コマごと)と
   requestAnimationFrame の早いほうで currentTime を見て、終わりの STOP_LEAD(pause が効くまでの遅れの分)手前で pause する。止めたあと終わりを過ぎていたら currentTime を終わりへ戻す。
   getEnd() が null を返す(S.playEnd が解かれた)・一時停止・別の見張りに替わったら、見張りは自然に終わる。timeupdate 側の止め(app.js)は、タブが隠れて
   タイマーが間引かれたときの保険として残す。cut.js の再生は requestVideoFrameCallback のループ(tick)で見ているので、ここは使わない */
const STOP_LEAD = 0.02;
const EndGuard = { gen: 0, timer: 0, raf: 0, vfc: 0, media: null };
function stopAtEnd(media, getEnd, onStop){
  const g = EndGuard, my = ++g.gen;
  clearTimeout(g.timer); if (g.raf) cancelAnimationFrame(g.raf);
  if (g.vfc && g.media && g.media.cancelVideoFrameCallback) try { g.media.cancelVideoFrameCallback(g.vfc); } catch {}
  g.timer = g.raf = g.vfc = 0; g.media = media;
  const alive = () => g.gen === my;
  function step(){
    if (!alive()) return;
    g.timer = g.raf = 0;
    const end = getEnd();
    if (end === null || end === undefined || media.paused) return;   // 解かれた・止まった(play() が断られた場合も、ここで見張りをやめる)
    const rate = media.playbackRate || 1, remain = end - media.currentTime;
    if (remain <= STOP_LEAD * rate){ g.gen++; media.pause(); if (media.currentTime > end) media.currentTime = end; if (onStop) onStop(end); return; }
    if (remain / rate > 0.12){ g.timer = setTimeout(step, Math.min(500, Math.max(10, (remain / rate - 0.1) * 1000))); return; }
    const once = () => { if (!alive()) return; if (g.vfc && media.cancelVideoFrameCallback) try { media.cancelVideoFrameCallback(g.vfc); } catch {} if (g.raf) cancelAnimationFrame(g.raf); g.vfc = g.raf = 0; step(); };
    g.raf = requestAnimationFrame(once);
    if (media.requestVideoFrameCallback) g.vfc = media.requestVideoFrameCallback(once);
  }
  step();
}
/* S.playEnd を立てて play() したあとに呼ぶ(再生の速さが変わったときも呼び直す) */
function armPlayEnd(){ if (S.playEnd !== null) stopAtEnd(player(), () => S.playEnd, () => { S.playEnd = null; }); }

/* 編集のサーバーの API。中身は ui-kit の UIKit.http の 1 本(合言葉 X-YTT-Token を付ける条件・エラーの形はそこの 1 か所)。
   失敗は Error: message(サーバーの message、無ければ「エラー n」)・code(サーバーの error、無ければ 'http'。つながらないときは 'network')・status・data(本文) */
const NO_SERVER = 'サーバーに接続できません。黒い画面(ターミナル)が閉じていないか確認してください';
const httpFailText = st => 'エラー ' + st;
function api(path, opt = {}){
  return UIKit.http(apiUrl(path), { method: opt.method, body: opt.body, keepalive: opt.keepalive, offline: NO_SERVER, fail: httpFailText });
}

/* ファイル(zip)を受け取る POST。失敗時は api() と同じ形のエラー。成功時は Response(ヘッダーと blob を使う) */
function apiBlob(path, body){
  return UIKit.http(apiUrl(path), { body, raw: true, offline: NO_SERVER, fail: httpFailText });
}

/* ---------- ボタンの処理の決まった形(同じ書き方を 1 か所に。保存できていなければ知らせて false) ---------- */
/* 押している間はボタンを押せなくし(label があれば文字も)、終わったら(失敗しても)戻す。押せるかを計算し直す所は busy(...).finally(renderX) */
async function busy(btn, fn, label){
  const t = btn.textContent; btn.disabled = true; if (label) btn.textContent = label;
  try { return await fn(); } finally { btn.disabled = false; if (label) btn.textContent = t; }
}
function kickJobs(){ startPolling(); return pollJobs(); }   // ジョブを待機列に入れたあと: 見回りを始めて、すぐ 1 回読む
async function saveFirst(){   // ジョブを始める前(話者判別・再認識など)
  await saveDoc();
  if (S.dirty || S.saving){ toast('保存中です。少し待ってから、もう一度押してください'); return false; }
  return true;
}
async function saveDone(){   // サーバーが保存済みの文書で計算する操作の前(行の分け直し・時刻の候補)
  if (await saveDoc()) return true;
  toast('保存が終わっていません。少し待ってから、もう一度押してください', 5000, 'err'); return false;
}
async function savedAll(){   // まとめて実行・動画の付け替えの前(カットは別のパネルが保存する)
  if (await saveDoc()) return true;
  toast('保存が追いついていません。少し待ってから、もう一度押してください', 5000, 'err'); return false;
}
/* 文書 id を保存し終えたか(知らせない。保存の途中・競合・別の文書へ移ったなら false) */
async function savedFor(id){ return !!(await saveDoc()) && !S.dirty && !S.saving && !S.conflict && S.docId === id; }
function showConflict(){ S.conflict = true; $('#conflictBar').hidden = false; setSaveState('競合しています', 'err'); }   // 保存の 409 の案内(saveDoc もこれを呼ぶ)
function copyPath(text){   // 動画の隣に保存した結果のパス(写し方と知らせは UIKit.copy の 1 か所)
  return UIKit.copy(text, { ok: 'パスをコピーしました', fail: 'コピーできませんでした(パスを選んでコピーしてください)' });
}
/* キーの前置きの判定(日本語の変換中にキーを奪わない・Ctrl/⌘/Alt つき。cut.js には h で渡す) */
const imeKey = e => e.isComposing || e.keyCode === 229;
const anyMod = e => e.ctrlKey || e.metaKey || e.altKey;
/* 未校正の行(文字があって校正済みでない) */
const isUnproofed = g => !g.proofed && hasText(g);
function setCut(g, on){ if (on) g.cutState = 'cut'; else delete g.cutState; }   // 行の「カット済」の印(残すなら印を消す)
function curItem(){ return S.list.find(x => x.id === S.docId); }   // 今の文書の、履歴の一覧の項目(無ければ undefined)
function modalOpen(){ return !!document.querySelector('dialog[open], .ui-drawer:not([hidden])'); }   // ダイアログ・引き出しが開いている = 文書を操作するキーを効かせない
const approxLen = sec => sec < 90 ? Math.round(sec) + '秒' : Math.round(sec / 60) + '分';   // 音声の長さのおおよそ

function setRowSp(row, sp){ const c = sp ? rowSpColor(sp.id) : ''; if (c) row.style.setProperty('--sp', c); else row.style.removeProperty('--sp'); }

/* 2回押しの確認(戻せない操作だけ)。部品は ui-kit の UIKit.confirmTwice の1つ */
function armDelete(btn, run, text){ UIKit.confirmTwice(btn, run, text); }

/* ---------- 表示の好み(長時間の作業向け。このブラウザにだけ保存) ---------- */

function loadView(){
  try {
    const o = JSON.parse(localStorage.getItem(VIEW_KEY) || '{}');
    if (o && typeof o === 'object'){
      for (const k of Object.keys(V)) if (k in o && typeof o[k] === typeof V[k]) V[k] = o[k];
      /* 画面の色は ui-kit(localStorage の ytt:theme)に1本化している(設定の引き出しで変える。保存先は1か所)。
         tx.view.v1 の theme に保存してある選択は、ui-kit にまだ選択が無いときだけ引き継ぐ。
         ytt:theme が無いときの既定は 'light' なので、「無い」の判定は UIKit.theme.get() ではなく localStorage を直接見る */
      if (o.theme === 'light' || o.theme === 'dark'){ try { if (localStorage.getItem('ytt:theme') === null) UIKit.theme.set(o.theme); } catch {} }
      if ('theme' in o){ delete o.theme; saveView(); }
    }
  } catch {}
}

function saveView(){ try { localStorage.setItem(VIEW_KEY, JSON.stringify(V)); } catch {} }

/* 画面の下の帯(UIKit.keybar)。2つの場面(行を選んでいる/文字を直している)で置き換える */
function txKeybarScene(){
  if (!S.doc){ keybarSet(null); return; }
  const editing = document.activeElement && document.activeElement.matches && document.activeElement.matches('#segs textarea');
  if (editing) keybarSet([{ k: 'Esc', l: '抜ける' }, { k: 'Alt+Enter', l: '校正済みで次へ' }]);
  else {   // 割り当て(⚙ 設定の「キー配置」)のとおりに出す
    const km = keymap(), k = id => km[id] ? keyText(km[id]) : '';
    keybarSet([{ k: keyWithAlt('rowNext'), l: '次の行' }, { k: keyWithAlt('rowPrev'), l: '前の行' }, { k: k('unNext'), l: '次の未校正' }, { k: k('proof'), l: '校正済みで次へ' },
      { k: k('replay'), l: '聞く' }, { k: k('edit'), l: '直す' },   // 「3秒戻る・進む」は ? の一覧に(帯は 7 個まで)
      { k: '?', l: 'キー操作' }].filter(x => x.k));
  }
}

/* 下の帯に出す(殻の帯に混ぜてもらう = EDIT_HOST.keybar。null = 消す) */
function keybarSet(items){ EDIT_HOST.keybar(items); }

function applyView(){
  const r = document.documentElement;
  if (!['13', '15', '17', '20'].includes(V.fs)) V.fs = '15';
  if (!['l', 'm', 's', 'a'].includes(V.vid)) V.vid = 'l';
  if (!['0.75', '1', '1.25', '1.5', '1.75', '2'].includes(V.rate)) V.rate = '1';
  if (!['0', '30', '45', '60'].includes(V.brk)) V.brk = '45';
  r.style.setProperty('--fs', V.fs + 'px'); r.style.setProperty('--vh', VID_H[V.vid] || VID_H.l);
  r.classList.toggle('dense', !!V.dense); r.classList.toggle('vid-audio', V.vid === 'a');
  $('#vFs').value = V.fs; $('#vVid').value = V.vid; $('#vDense').checked = V.dense; $('#vBrk').value = V.brk;
  if (!['0.05', '0.1', '0.25', '0.5', '1'].includes(V.adjStep)) V.adjStep = '0.1';
  $('#follow').checked = V.follow; $('#frameFollow').checked = !!V.frameFollow; $('#adjStep').value = V.adjStep; $('#autoNext').checked = V.autoNext; $('#rate').value = V.rate;
  const p = $('#player'); p.defaultPlaybackRate = Number(V.rate); p.playbackRate = Number(V.rate);
  if (S.doc){ autoSizeSoon(); drawStripSoon(); }
}

/* ---------- ヘッダーの ⚙(UIKit.settings)。「表示」の内容はツールの節・画面の色は全体の節(ui-kit) ---------- */

/* ヘッダー左の ui-appnav(ホーム/案件/確かめる/設定)に版を出す。appnav は DOMContentLoaded で描かれるので、間に合わなければそこでも試す */
function setAppnavVersion(){ UIKit.appnav.setVersion('v' + APP_VERSION); }

/* ---------- 取り込まれたツールの場所(サーバーの /api/siblings を UIKit.tools.setPaths に渡す。答えない・古いサーバーなら既定のまま) ---------- */

function loadSiblings(){
  if (sibP) return sibP;
  sibP = api('/api/siblings')
    .then(j => { UIKit.tools.setPaths(j && j.paths); })   // 入口の統合サーバーに取り込まれたツールの場所(/studio/ など)
    .catch(() => {})
    .finally(() => { sibP = null; });
  return sibP;
}

/* ---------- 設定(用語集・置換辞書など) ----------
   保存は「最後に保存した内容との差のキーだけ」を PUT /api/settings {"patch"}(サーバーはロックの中で今のファイルに合わせる。
   窓を2つ開いても、別々の設定なら消し合わない。同じキーを同時に変えたときだけ後勝ち)。失敗は ⚙ の印と設定の引き出しの先頭に [もう一度](UIKit.settings.status)。
   読み込みに失敗したら「設定を読み込めませんでした [読み直す]」にして、読み直すまで保存しない(空の設定で用語集・置換辞書・キー配置を上書きしないため) */

function settingsDiff(){
  const cur = setSnap(S.settings), out = {};
  for (const k of Object.keys(cur)) if (cur[k] !== setSaved[k]) out[k] = S.settings[k];
  for (const k of Object.keys(setSaved)) if (!(k in cur)) out[k] = null;   // 消したキー
  return out;
}

/* 差を送る(1つずつ順に)。-> 保存できたか。keepalive: 画面を離れるとき(応答を待たない。失敗は戻ったときに送り直す) */
function sendSettings(keepalive){
  const run = async () => {
    if (S.settingsLoadErr) return false;
    const patch = settingsDiff(), keys = Object.keys(patch);
    if (!keys.length){ if (setFailed){ setFailed = false; setStatus(''); } return true; }
    const snap = setSnap(S.settings);
    try {
      await api('/api/settings', { method: 'PUT', body: { patch }, ...(keepalive ? { keepalive: true } : {}) });
      for (const k of keys){ if (patch[k] === null) delete setSaved[k]; else setSaved[k] = snap[k]; }
      if (setFailed){ setFailed = false; setStatus(''); }
      return true;
    } catch (e){
      setFailed = true;
      setStatus('err', '設定を保存できていません: ' + e.message, () => sendSettings());
      return false;
    }
  };
  setChain = setChain.then(run, run);
  return setChain;
}

function saveSettings(){ clearTimeout(setT); setT = setTimeout(() => { setT = null; sendSettings(); }, 600); }

/* 設定の「送ったキーだけ直す」保存(POST api/settings/patch。ほかの窓の設定を消さない。上の sendSettings の差分の PUT とは別 = 1 か所の操作で 1〜数個のキーを今すぐ直すとき)。
   先に S.settings へ入れ(保存を待つ間の描き直しで選択が戻らないように)、失敗したら元に戻す。-> 保存できたか(失敗の知らせはここで出す。画面の巻き戻しは false を見て呼ぶ側で)
   label: 失敗の知らせの頭(「…を保存できませんでした」。あとに「: サーバーの文」が付く)
   opt: apply = false で S.settings に入れない(サーバーだけが持つ設定。evalDirs)・keep = true で失敗しても戻さない(キー配置: 画面は今の配置のまま、知らせだけ)
        ms = 知らせの秒(省略は 6000。0 = 閉じるまで)・retry = 知らせの [もう一度] で呼ぶ関数 */
async function patchSettings(values, label, opt = {}){
  const apply = opt.apply !== false, st = S.settings, old = {};
  if (apply) for (const k of Object.keys(values)){ old[k] = k in st ? { v: st[k] } : null; st[k] = values[k]; }
  try { await api('/api/settings/patch', { body: { values } }); return true; }
  catch (e){
    if (apply && !opt.keep) for (const k of Object.keys(old)){ if (old[k]) S.settings[k] = old[k].v; else delete S.settings[k]; }
    toast(label + ': ' + e.message, { kind: 'err', ms: 'ms' in opt ? opt.ms : 6000, ...(opt.retry ? { action: { label: 'もう一度', fn: opt.retry } } : {}) });
    return false;
  }
}

/* 設定を読む。失敗したら保存を止めて知らせる(-> 読めたか) */
async function loadSettings(){
  try {
    S.settings = await api('/api/settings');
    setSaved = setSnap(S.settings); S.settingsLoadErr = ''; setFailed = false; setStatus('');
    return true;
  } catch (e){
    if (!S.settings || typeof S.settings !== 'object') S.settings = {};
    S.settingsLoadErr = e.message || 'エラー';
    setStatus('err', `設定を読み込めませんでした(${S.settingsLoadErr})。読み直すまで、ここで変えた設定は保存しません`, () => reloadSettings(), '読み直す');
    return false;
  }
}

async function reloadSettings(){
  clearTimeout(setT); setT = null;
  if (!(await loadSettings())) return;
  KM.reload();
  applySettings(); renderDiarSetup(); renderRtSetup(); renderAlt(); renderKeyUI();
  toast('設定を読み直しました', 3000, 'ok');
}

/* 設定のチェック [設定の鍵, 欄の id, 無いときの扱い](readOpts・applySettings・jobOpts と、変えたら保存する配線(app.js)が同じ表を使う)。
   扱い: true = 明示の false のときだけ外す / false = true のときだけ付ける / null = 真らしい値なら付ける。
   OPT_CHECKS = 「認識の設定」(文字起こしの要求にも付ける)。
   OPT_CHECKS の欄は設定の画面にある(notes:docs/spec/data.md の 6)。表は鍵と既定の扱いのために使い、欄が無ければ S.settings を読む */
const OPT_CHECKS = [['boost', 'optBoost', null], ['autoDict', 'optAutoDict', true], ['wordSplit', 'optWordSplit', true], ['stripPunct', 'optStripPunct', true],
  ['autoGloss', 'optAutoGloss', true], ['autoContext', 'optAutoContext', false], ['autoLearned', 'optAutoLearned', false],
  ['autoAlt', 'optAutoAlt', false],
  ['autoFill', 'optAutoFill', true],   // autoFill = 認識のあとの後処理(文字の少ない行を別の読みで埋める。既定オン)
  ['autoLlm', 'optAutoLlm', true],   // autoLlm = 名簿の呼び名の聞き違いらしい所だけを手元の LLM で直す(既定オン)
  ['stripNames', 'optStripNames', true]];   // stripNames = 行の頭の話者名(「名前:」)を外す(既定オン。欄は設定の画面だけ)
const SET_CHECKS = OPT_CHECKS.concat([['exSpk', 'exSpk', null], ['exTs', 'exTs', null]]);
/* 欄の無い鍵(認識の設定の自動の後処理 = 設定の画面にある)は、保存した設定 S.settings の値(無いときの扱い dv で既定)を使う */
const checksOf = list => Object.fromEntries(list.map(([k, id, dv]) => {
  const el = $('#' + id);
  return [k, el ? el.checked : (dv === true ? S.settings[k] !== false : dv === false ? S.settings[k] === true : !!S.settings[k])];
}));

/* 声の検出の欄は設定の画面にある。欄があれば欄、無ければ保存した設定(既定 weak) */
function vadModeOf(){ const e = $('#optVad'); const v = e ? e.value : (S.settings && S.settings.vadMode); return ['normal', 'off'].includes(v) ? v : 'weak'; }
/* 認識の設定のチェック 1 つの今の値(欄が無ければ保存した設定から。checksOf と同じ決まり) */
function optCheck(k){ return checksOf(OPT_CHECKS.filter(c => c[0] === k))[k] === true; }

function readOpts(){
  const s = S.settings;
  if ($('#optVad')) s.vadMode = $('#optVad').value;
  s.subtitle = readSubtitle();
  Object.assign(s, checksOf(SET_CHECKS));
  if ($('#rtModel').value){ s.rtModel = $('#rtModel').value; s.rtTarget = $('#rtTarget').value; }
  s.replacements = $('#repDict').value.slice(0, 20000);
  s.exBase = $('#exBase').value; s.exWrap = $('#exWrap').value; s.diarEmb = $('#diarEmb').value;   // 話者の人数は文書ごと(diarNumChanged。欄の値は開いている文書のもの)
  saveSettings(); if (S.doc) renderTerms();
}

function applySettings(){
  const s = S.settings;
  { const vd = $('#optVad'); if (vd) vd.value = ['normal', 'off'].includes(s.vadMode) ? s.vadMode : 'weak'; } fillSubtitle(s.subtitle);
  for (const [k, id, dv] of SET_CHECKS){ const el = $('#' + id); if (el) el.checked = dv === true ? s[k] !== false : dv === false ? s[k] === true : !!s[k]; }   // 欄の無い鍵(設定の画面にある)は飛ばす
  $('#repDict').value = s.replacements || '';
  if (s.exBase) $('#exBase').value = s.exBase; if (s.exWrap) $('#exWrap').value = s.exWrap;
  fillDiarNum();   // 話者の人数: 開いている文書の人数(無ければ話者の数 → 全体の既定 s.diarNum)
}

/* ---------- 処理の機器の表示 ---------- */

// 処理の機器の表示(ジョブ・文書の認識の設定)。vulkan = AMD などの GPU で whisper.cpp
function devLabel(d){ return d === 'cuda' ? 'GPU' : d === 'vulkan' ? 'GPU(whisper.cpp)' : 'CPU'; }
