/* app-core.js — 「編集」の画面: 共通の小道具・表示の好み・⚙・他のツール・設定・準備状況・進行度(段10 で app.js から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は index.html の1か所) */
'use strict';

/* ---------- 共通 ---------- */

function fmtT(t, ms){
  t = Math.max(0, Number(t) || 0);
  const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
  const ss = ms ? s.toFixed(1).padStart(4, '0') : String(Math.floor(s)).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

function parseT(str){
  str = String(str || '').trim().replace(/[：]/g, ':');
  if (!str) return NaN;
  const p = str.split(':');
  if (p.length > 3 || p.some(x => !/^\d+(\.\d+)?$/.test(x.trim()))) return NaN;
  return p.reduce((a, x) => a * 60 + Number(x), 0);
}

/* SVG の線のアイコン(UIKit.icon)の文字列。文字記号(✓ × ⋮ ▶)の代わり(UI の見直し A-10)。ui-kit が無いときは空(呼ぶ側が文字で補う) */
function uiIcon(name, opts){ return (window.UIKit && UIKit.icon) ? UIKit.icon(name, opts) : ''; }

/* kind: 'ok' | 'err' | 'info'(左の色の印。省略可)。ui-kit v6 の UIKit.toast を呼ぶだけ(重ねて最大3つ・入れ物は #toast) */
function toast(msg, ms, kind = ''){   // ms にオブジェクト({ms, kind, action})を渡せば、そのまま UIKit.toast へ(ボタンつきの知らせ)
  if (ms && typeof ms === 'object' && window.UIKit && UIKit.toast) return UIKit.toast(msg, ms);
  if (window.UIKit && UIKit.toast) UIKit.toast(msg, { ms, kind });
  else { const t = $('#toast'); if (t){ t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, ms || 3800); } }
}

/* 画面の赤い帯(段8 E-26): 何が起きたか + 次の一手([読み込み直す]・ホームから開いたときは [ホームへ])+ 閉じる(×)。
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
  const x = el('button', 'btn small ghost icon tt-err-x'); x.type = 'button'; x.innerHTML = uiIcon('close', { size: 14 }) || '閉じる'; x.setAttribute('aria-label', 'エラーの帯を閉じる'); x.title = 'エラーの帯を閉じる'; x.addEventListener('click', () => { b.hidden = true; }); acts.append(x);
  b.append(acts); b.hidden = false;
}

/* ---------- 区間の終わりで止める見張り(「この行だけ再生」・▶・評価ドリルの帯の「聞く」・端を動かしたあとの聞き直し) ----------
   以前は timeupdate(Chromium で約 250ms ごと)で止めていて、止まるまでに 9〜236ms(平均 約 116ms)行の終わりを過ぎた。機械の行の終わりは次の声の出だしの
   0.05〜0.1 秒前にあることが多いので、行の終わりに次の行の頭の言葉が聞こえていた(2026-10-04)。
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

/* 応答が ok でないときのエラー(api()・apiBlob()・portalApi() で同じ形: message・code = サーバーの error・status・data = 本文) */
function httpError(r, j){ const er = new Error(j.message || ('エラー ' + r.status)); er.code = j.error; er.status = r.status; er.data = j; return er; }
const NO_SERVER = 'サーバーに接続できません。黒い画面(ターミナル)が閉じていないか確認してください';

async function api(path, opt = {}){
  const init = { cache: 'no-store', method: opt.method || 'GET', ...(opt.keepalive ? { keepalive: true } : {}) };
  if (opt.body !== undefined){ init.method = opt.method || 'POST'; init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(opt.body); }
  if (TOKEN && init.method !== 'GET' && init.method !== 'HEAD') init.headers = { ...(init.headers || {}), 'X-YTT-Token': TOKEN };
  let r;
  try { r = await fetch(apiUrl(path), init); } catch { throw new Error(NO_SERVER); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw httpError(r, j);
  return j;
}

/* ファイル(zip)を受け取る POST。失敗時は api() と同じ形のエラー。成功時は Response(ヘッダーと blob を使う) */
async function apiBlob(path, body){
  let r;
  try { r = await fetch(apiUrl(path), { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json', ...(TOKEN ? { 'X-YTT-Token': TOKEN } : {}) }, body: JSON.stringify(body) }); }
  catch { throw new Error(NO_SERVER); }
  if (!r.ok) throw httpError(r, await r.json().catch(() => ({})));
  return r;
}

/* ---------- ボタンの処理の決まった形(同じ書き方を 1 か所に。保存できていなければ知らせて false) ---------- */
function kickJobs(){ startPolling(); return pollJobs(); }   // ジョブを待機列に入れたあと: 見回りを始めて、すぐ 1 回読む
async function saveFirst(){   // ジョブを始める前(話者判別・再認識など)
  await saveDoc();
  if (S.dirty || S.saving){ toast('保存中です。少し待ってから、もう一度押してください'); return false; }
  return true;
}
async function saveDone(){   // サーバーが保存済みの文書で計算する操作の前(行の分け直し・疑わしい所の認識し直し・時刻の候補)
  if (await saveDoc()) return true;
  toast('保存が終わっていません。少し待ってから、もう一度押してください', 5000, 'err'); return false;
}
async function savedAll(){   // 文書とカットの両方(まとめて実行・付け替え・zip)
  if ((await saveDoc()) && !(CUT && !(await CUT.flush()))) return true;
  toast('保存が追いついていません。少し待ってから、もう一度押してください', 5000, 'err'); return false;
}
/* 文書 id を保存し終えたか(知らせない。保存の途中・競合・別の文書へ移ったなら false) */
async function savedFor(id){ return !!(await saveDoc()) && !S.dirty && !S.saving && !S.conflict && S.docId === id; }
function showConflict(){ S.conflict = true; $('#conflictBar').hidden = false; setSaveState('競合しています', 'err'); }   // 保存の 409 の案内(saveDoc と同じ形)
async function copyPath(text){   // 動画の隣に保存した結果・前回のパックのパス
  try { await navigator.clipboard.writeText(text); toast('パスをコピーしました', 2000, 'ok'); }
  catch { toast('コピーできませんでした(パスを選んでコピーしてください)', 3000, 'err'); }
}
/* URL の引数を 1 つ直す(replaceState。v が空・null なら消す)。タブの # とほかの引数はそのまま */
function setUrlParam(key, v){
  try {
    const q = new URLSearchParams(location.search);
    if (v) q.set(key, v); else q.delete(key);
    const rest = q.toString(), url = location.pathname + (rest ? '?' + rest : '') + location.hash;
    if (url !== location.pathname + location.search + location.hash) history.replaceState(history.state, '', url);
  } catch {}
}
function modalOpen(){ return !!document.querySelector('dialog[open], .ui-drawer:not([hidden])'); }   // ダイアログ・引き出しが開いている = 文書を操作するキーを効かせない
/* 行の並び(開始時刻の順)で、開始が t 以前の最後の行の添字(無ければ -1。二分探索) */
function segIndexAt(segs, t){ let lo = 0, hi = segs.length - 1, ans = -1; while (lo <= hi){ const m = (lo + hi) >> 1; if (segs[m].start <= t){ ans = m; lo = m + 1; } else hi = m - 1; } return ans; }
const approxLen = sec => sec < 90 ? Math.round(sec) + '秒' : Math.round(sec / 60) + '分';   // 音声の長さのおおよそ

function download(blob, name){
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 30000);
}

function setRowSp(row, sp){ const c = sp ? rowSpColor(sp.id) : ''; if (c) row.style.setProperty('--sp', c); else row.style.removeProperty('--sp'); }

/* 2回押しの確認(戻せない操作だけ)。部品は ui-kit の UIKit.confirmTwice の1つ(気が利く画面へ 段1)。
   以前のこの版は実行後も3秒間「確認済み」のままで、続けて押すと同じ操作がもう一度走り、文言も「もう一度押す」だけだった */
function armDelete(btn, run, text){ UIKit.confirmTwice(btn, run, text); }

/* ---------- 表示の好み(長時間の作業向け。このブラウザにだけ保存) ---------- */

/* v0.9.8: 左のメニューの開閉(V.menu)は保存する(上の「☰」ボタンがいつも見えているので、閉じたままでも迷わない)。
   文字起こしを開いていないときに閉じていると何も見えないので、その場合は案内にボタンを出す(showNoDoc) */
function loadView(){
  try {
    const o = JSON.parse(localStorage.getItem(VIEW_KEY) || '{}');
    if (o && typeof o === 'object'){
      for (const k of Object.keys(V)) if (k in o && typeof o[k] === typeof V[k]) V[k] = o[k];
      /* 画面の色は ui-kit(localStorage の ytt:theme)に1本化した(設定の引き出しで変える。保存先は1か所。ヘッダーの切り替えボタンは v14 でやめた)。
         以前の版が tx.view.v1 の theme に保存していた選択は、ui-kit にまだ選択が無いときだけ引き継ぐ。
         v6 から ytt:theme が無いときの既定は 'system' ではなく 'light' になったので、「無い」の判定は UIKit.theme.get() ではなく
         localStorage を直接見る(以前は既定が 'system' だったことを前提にしていたため、v6 のままだと引き継ぎが動かなかった) */
      if ((o.theme === 'light' || o.theme === 'dark') && window.UIKit){ try { if (localStorage.getItem('ytt:theme') === null) UIKit.theme.set(o.theme); } catch {} }
      if ('theme' in o){ delete o.theme; saveView(); }
    }
  } catch {}
}

function saveView(){ try { localStorage.setItem(VIEW_KEY, JSON.stringify(V)); } catch {} }

function tabFromHash(){ const h = String(location.hash || '').replace(/^#/, ''); return ED_TABS.includes(h) ? h : null; }

function setEditTab(t, opt = {}){
  if (!ED_TABS.includes(t)) t = 'tx';
  const was = EDT.tab;
  EDT.tab = t; EDT.overlay = false;
  document.querySelectorAll('[data-edtab]').forEach(b => { const on = b.dataset.edtab === t; b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
  /* 監査01(段1): 隠れるタブの中で開いている引き出し(3 パック の設定など)は、隠す前に閉じる。modal の引き出しは裏を inert にし、close まで残すので、
     開いたまま隠すと見えない引き出しが全部の操作を塞ぐ(Alt+数字は下で止めるが、戻る・# のリンク・プログラムからの切り替えでも残さないための保険) */
  let closedDrawer = false;
  document.querySelectorAll('[data-edpanel]').forEach(p => {
    if (p.dataset.edpanel === t) return;
    p.querySelectorAll('.ui-drawer:not([hidden])').forEach(d => { closedDrawer = true; if (window.UIKit && UIKit.drawer) UIKit.drawer.close(d); else d.hidden = true; });
  });
  document.querySelectorAll('[data-edpanel]').forEach(p => { p.hidden = p.dataset.edpanel !== t; });
  document.documentElement.dataset.edtabNow = t;   // CSS 用(html[data-edtab-now])。[data-edtab] はタブのボタンだけに使う
  if (opt.hash !== false && location.hash !== '#' + t){ try { history.replaceState(history.state, '', location.pathname + location.search + '#' + t); } catch {} }
  applyView();
  if (was !== t){ onEditTab(was, t); rememberLast(); }   // 前回の文書とタブ(段7 E-7。文書を開いていなければ何もしない)
  if (opt.focus || closedDrawer){ const b = document.querySelector(`[data-edtab="${t}"]`); if (b) b.focus(); }   // 閉じた引き出しは隠れたタブのボタンへフォーカスを返すので、移った先のタブのボタンへ置き直す
}

/* タブを移ったとき: 文字起こしのタブの映像は隠れるので止める(隠れたまま音だけ鳴らさない)。戻ったら行の高さと帯を描き直す */
function onEditTab(from, to){
  if (from === 'tx' && S.doc) player().pause();
  if (from === 'cut' && CUT) CUT.onHidden();   // カットのタブの再生位置を、文字起こしの映像へ引き継ぐ・未保存のカットを保存
  if (to === 'tx' && S.doc){ autoSizeSoon(); drawStripSoon(); }
  if (to === 'cut' && CUT) CUT.onShown();
  if (to === 'pack' && PACK) PACK.shown();
  /* カット・パックのタブは、CUT.onShown()/PACK.shown()(上)が自分の帯をすでに出している(cut は M.sel に応じた場面、pack は clear)。
     ここで tx 以外もまとめて「from が tx なら clear」としてしまうと、その直後の帯を上書きして消してしまう(2026-09-27 に見つけて直した) */
  if (to === 'tx') txKeybarScene();
  renderDocBar();
}

/* 画面の下の帯(UIKit.keybar。段2)。1 文字起こし のタブだけ、2つの場面(行を選んでいる/文字を直している)で置き換える */
function txKeybarScene(){
  if (!window.UIKit || !UIKit.keybar || wideTab()) return;
  if (!S.doc){ UIKit.keybar.clear(); return; }
  const editing = document.activeElement && document.activeElement.matches && document.activeElement.matches('#segs textarea');
  if (editing) UIKit.keybar.set([{ k: 'Esc', l: '抜ける' }, { k: 'Alt+Enter', l: '校正済みで次へ' }]);
  else {   // 割り当て(⚙ 設定の「キー配置」)のとおりに出す
    const km = keymap(), k = id => km[id] ? keyText(km[id]) : '';
    UIKit.keybar.set([{ k: keyWithAlt('rowNext'), l: '次の行' }, { k: keyWithAlt('rowPrev'), l: '前の行' }, { k: k('unNext'), l: '次の未校正' }, { k: k('proof'), l: '校正済みで次へ' },
      { k: k('replay'), l: '聞く' }, { k: k('edit'), l: '直す' }, { k: [k('back3'), k('fwd3')].filter(Boolean).join(' / '), l: '3秒' },
      ...(DR.on ? [{ k: k('drillDone'), l: '済みにして次へ' }] : []), { k: '?', l: 'キー操作' }].filter(x => x.k));   // 評価ドリルの間は「済みにして次へ」も
  }
}

function applySideTab(){
  if (!['start', 'files', 'quality', 'data'].includes(V.sideTab)) V.sideTab = 'start';
  document.querySelectorAll('[data-side-tab]').forEach(b => b.setAttribute('aria-selected', b.dataset.sideTab === V.sideTab ? 'true' : 'false'));
  document.querySelectorAll('[data-side-pane]').forEach(p => { p.hidden = p.dataset.sidePane !== V.sideTab; });
}

function setSideTab(tab, openPanel = true){ V.sideTab = tab; if (openPanel){ if (wideTab()) EDT.overlay = true; else V.menu = true; } saveView(); applyView(); }   // タブの切り替え(v0.9.9: GPT 版のタブを ☰ のメニューの中に統合)

function applyView(){
  const r = document.documentElement;
  if (!['13', '15', '17', '20'].includes(V.fs)) V.fs = '15';
  if (!['l', 'm', 's', 'a'].includes(V.vid)) V.vid = 'l';
  if (!['0.75', '1', '1.25', '1.5', '1.75', '2'].includes(V.rate)) V.rate = '1';
  if (!['0', '30', '45', '60'].includes(V.brk)) V.brk = '45';
  r.style.setProperty('--fs', V.fs + 'px'); r.style.setProperty('--vh', VID_H[V.vid] || VID_H.l);
  r.classList.toggle('dense', !!V.dense); r.classList.toggle('vid-audio', V.vid === 'a');
  applySideTab();
  const app = $('.app'), wide = wideTab();
  app.classList.toggle('tab-wide', wide); app.classList.toggle('menu-overlay', wide && EDT.overlay);
  app.classList.toggle('menu-closed', !menuOpen());
  $('#btnMenu').setAttribute('aria-expanded', menuOpen() ? 'true' : 'false'); $('#btnMenuT').textContent = menuOpen() ? 'メニューを閉じる' : 'メニューを開く';
  $('#noDocMenu').hidden = !!V.menu;
  $('#vFs').value = V.fs; $('#vVid').value = V.vid; $('#vDense').checked = V.dense; $('#vBrk').value = V.brk;
  if (!['0.05', '0.1', '0.25', '0.5', '1'].includes(V.adjStep)) V.adjStep = '0.1';
  $('#follow').checked = V.follow; $('#frameFollow').checked = !!V.frameFollow; $('#adjStep').value = V.adjStep; $('#autoNext').checked = V.autoNext; $('#rate').value = V.rate;
  const p = $('#player'); p.defaultPlaybackRate = Number(V.rate); p.playbackRate = Number(V.rate);
  if (S.doc){ autoSizeSoon(); drawStripSoon(); }
}

function toggleMenu(open){
  const was = menuOpen();
  if (wideTab()) EDT.overlay = open === undefined ? !EDT.overlay : !!open;
  else { V.menu = open === undefined ? !V.menu : !!open; saveView(); }
  applyView();
  if (isDrawer() && was !== menuOpen()){
    if (menuOpen()){ const t = document.querySelector('[data-side-tab][aria-selected=true]'); if (t) t.focus({ preventScroll: true }); }
    else if (document.activeElement && $('#menuPanel').contains(document.activeElement)) $('#btnMenu').focus({ preventScroll: true });
  }
}

/* メニューの中の項目へ移動する(閉じていれば開く) */
function showInMenu(el){ const pane = el.closest('[data-side-pane]'); if (pane) V.sideTab = pane.dataset.sidePane; if (wideTab()) EDT.overlay = true; else V.menu = true; saveView(); applyView(); if (el.tagName === 'DETAILS') el.open = true; el.scrollIntoView({ block: 'center' }); }

/* ---------- ヘッダーの ⚙(ui-kit v6。UIKit.settings)。「表示」の内容(旧 #viewMenu)をツールの節にし、画面の色は全体の節(ui-kit)へ一本化 ---------- */

/* ヘッダー左の ui-appnav(ホーム/スタジオ/編集)に版を出す。appnav は DOMContentLoaded で描かれるので、間に合わなければそこでも試す */
function setAppnavVersion(){ if (window.UIKit && UIKit.appnav) UIKit.appnav.setVersion('v' + APP_VERSION); }

/* ---------- 他のツール(実際のポートはサーバーの /api/siblings。答えない・古いサーバーなら既定のポート) ----------
   v6: ヘッダーの「他のツール」メニューは ui-appnav(ホーム/スタジオ/編集)に置き換えたので、ここでは S.ports と
   UIKit.tools.setPaths(cut2resolve の URL・c2rBase() が使う)だけを整える */

function loadSiblings(){
  if (sibP) return sibP;
  sibP = api('/api/siblings')
    .then(j => {
      S.ports = j && j.tools && typeof j.tools === 'object' ? j.tools : null;
      if (window.UIKit && UIKit.tools.setPaths) UIKit.tools.setPaths(j && j.paths);   // 入口の統合サーバーに取り込まれたツールの場所(/studio/ など)
    })
    .catch(() => { S.ports = null; })   // 古いサーバー(404)・通信の失敗は、既定のポートで
    .finally(() => { sibP = null; S.sibLoaded = true; renderHandoff(); if (S.doc) cpAfterSave(); if (CUT) CUT.refresh(); });
  return sibP;
}

/* ---------- 設定(用語集・置換辞書など) ----------
   監査 11(全体の計画 段2): 保存は「最後に保存した内容との差のキーだけ」を PUT /api/settings {"patch"}(サーバーはロックの中で今のファイルに合わせる。
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
  if (KM) KM.reload();
  applySettings(); renderSetup(); renderDiarSetup(); renderRtSetup(); renderAlt(); renderOptSummary(); renderKeyUI();
  toast('設定を読み直しました', 3000, 'ok');
}

/* 設定のチェック [設定の鍵, 欄の id, 無いときの扱い](readOpts・applySettings・jobOpts と、変えたら保存する配線(app.js)が同じ表を使う)。
   扱い: true = 明示の false のときだけ外す / false = true のときだけ付ける / null = 真らしい値なら付ける。
   OPT_CHECKS = 「認識の設定」(文字起こしの要求にも付ける。autoYtcap = 終わったら元の配信の YouTube の字幕と比べる 案 A1) */
const OPT_CHECKS = [['boost', 'optBoost', null], ['autoDict', 'optAutoDict', true], ['wordSplit', 'optWordSplit', true], ['stripPunct', 'optStripPunct', true],
  ['autoGloss', 'optAutoGloss', true], ['autoContext', 'optAutoContext', false], ['autoLearned', 'optAutoLearned', false], ['autoRedo', 'optAutoRedo', false],
  ['autoAlt', 'optAutoAlt', false], ['autoYtcap', 'optAutoYtcap', false], ['autoDiarize', 'optAutoDiar', false], ['redoLarge', 'optRedoLarge', true]];
const SET_CHECKS = OPT_CHECKS.concat([['archiveAuto', 'arcAuto', true], ['archiveFull', 'arcFull', true], ['exSpk', 'exSpk', null], ['exTs', 'exTs', null]]);
const checksOf = list => Object.fromEntries(list.map(([k, id]) => [k, $('#' + id).checked]));

function readOpts(){
  const s = S.settings;
  s.device = $('#optDevice').value; s.model = $('#optModel').value; s.language = $('#optLang').value; s.quality = $('#optQuality').value; s.vadMode = $('#optVad').value; s.subtitle = readSubtitle();
  Object.assign(s, checksOf(SET_CHECKS));
  if ($('#rtModel').value){ s.rtModel = $('#rtModel').value; s.rtTarget = $('#rtTarget').value; }
  s.glossary = $('#optGloss').value.slice(0, 4000); s.replacements = $('#repDict').value.slice(0, 20000);
  s.exBase = $('#exBase').value; s.exWrap = $('#exWrap').value; s.mPad = $('#mPad').value; s.mFilter = $('#mFilter').value; s.diarEmb = $('#diarEmb').value;   // 話者の人数は文書ごと(diarNumChanged。欄の値は開いている文書のもの)
  saveSettings(); if (S.doc) renderTerms(); renderOptSummary();
  if (PACK) PACK.changed();   // 字幕の1段の文字数(subtitle.wrapChars)はパックの見積もりの鍵(段4 4-1。監査 07)
}

/* 「認識の設定」は既定で閉じるので(段2)、開かなくても分かるように「始める」の上へ1行の要約を出す */
function renderOptSummary(){
  // GPU(AMD など・whisper.cpp)で使えないモデルなら、始める前にその場で案内する(サーバーも断る)。「認識の設定」は閉じていることが多いので要約にも出す
  const w = S.tools && S.tools.wcpp, vk = $('#optDevice').value === 'vulkan';
  const bad = vk && w && !(w.models || []).includes($('#optModel').value);
  const badText = bad ? `GPU(whisper.cpp)で使えるモデルは ${(w.models || []).join('・')} です。モデルを選び直してください。` : '';
  const dh = $('#optDevHint');
  if (dh){ dh.hidden = !bad; dh.textContent = badText; }
  const el = $('#optSummary'); if (!el) return;
  const model = $('#optModel').selectedOptions[0], lang = $('#optLang').selectedOptions[0];
  const q = $('#optQuality').value === 'fast' ? '速度優先' : '精度優先';
  el.textContent = model ? `モデル: ${model.textContent} ・ 言語: ${lang ? lang.textContent : ''} ・ ${q}${vk ? ' ・ GPU(whisper.cpp)' : ''}${bad ? ' ― ' + badText : ''}` : '';
}

function applySettings(){
  const s = S.settings;
  if (s.model && [...$('#optModel').options].some(o => o.value === s.model)) $('#optModel').value = s.model;
  if (s.language && [...$('#optLang').options].some(o => o.value === s.language)) $('#optLang').value = s.language;
  $('#optQuality').value = s.quality === 'fast' ? 'fast' : 'best'; $('#optDevice').value = [...$('#optDevice').options].some(o => o.value === s.device && o.value) ? s.device : 'auto'; $('#optVad').value = ['normal', 'off'].includes(s.vadMode) ? s.vadMode : 'weak'; fillSubtitle(s.subtitle);
  for (const [k, id, dv] of SET_CHECKS) $('#' + id).checked = dv === true ? s[k] !== false : dv === false ? s[k] === true : !!s[k];
  $('#optGloss').value = s.glossary || ''; $('#repDict').value = s.replacements || ''; renderGlossFit();
  if (s.exBase) $('#exBase').value = s.exBase; if (s.exWrap) $('#exWrap').value = s.exWrap;
  if (s.mPad) $('#mPad').value = s.mPad; if (s.mFilter) $('#mFilter').value = s.mFilter;
  fillDiarNum();   // 話者の人数: 開いている文書の人数(無ければ話者の数 → 全体の既定 s.diarNum。段7 E-6)
}

/* ---------- 準備状況 ---------- */

// 処理の機器の表示(ジョブ・設定の比較・文書の認識の設定)。vulkan = AMD などの GPU で whisper.cpp(精度改善の計画 段2-2)
function devLabel(d){ return d === 'cuda' ? 'GPU' : d === 'vulkan' ? 'GPU(whisper.cpp)' : 'CPU'; }

function renderSetup(){
  const t = S.tools, box = $('#setup'); if (!t){ box.innerHTML = ''; return; }
  const miss = [];
  if (!t.ffmpeg) miss.push('<b>ffmpeg</b> が見つかりません。Windows: <code>winget install Gyan.FFmpeg</code> / Mac: <code>brew install ffmpeg</code>(入れたらこのツールを起動し直す)');
  if (!t.fasterWhisper && t.backend !== 'fake') miss.push('<b>faster-whisper</b> が入っていません。フォルダ内の <code>install.bat</code>(Mac は <code>install.command</code>)を実行してください');
  const banner = (title, body, open) => `<details class="setup-banner"${open ? ' open' : ''}><summary>${title}</summary><div class="setup-body">${body}</div></details>`;
  const hint = html => `<p class="hint" style="margin:0 0 10px">${html}</p>`;
  let gpu = '';
  if (t.backend !== 'fake' && !miss.length){
    if (t.cuda) gpu = hint(`GPU${t.nvidia ? '(' + esc(t.nvidia) + ')' : ''}を使って処理します。`);
    else if (t.nvidia) gpu = `<div class="notice"><b>${esc(t.nvidia)}</b> が見つかりましたが、GPU 用のライブラリが入っていないため CPU で処理します。<br>フォルダ内の <code>install-gpu.bat</code> を実行すると GPU が使えます(実行後に起動し直す)。</div>`;
    else if (t.wcpp && t.wcpp.ready) gpu = hint('AMD などの GPU は、「認識の設定」の処理方式で「GPU(AMD など・whisper.cpp)」を選ぶと使えます(モデルは large-v3 か large-v3-turbo)。');
    else gpu = hint('NVIDIA の GPU が見つからないため、CPU で処理します(AMD の GPU は setup フォルダの build-whisper-vulkan.bat で使えるようになります)。長い動画は時間がかかるため、「small」や「速度優先」がおすすめです。');
  }
  const env = (Array.isArray(t.envWarnings) ? t.envWarnings : []).slice(0, 8);   // サーバーの起動時の確認(ディスクの空き・OneDrive・部品の欠けなど)
  box.innerHTML = (t.backend === 'fake' ? banner('テスト用モード', '実際の文字起こしはしません。') : '')
    + (env.length ? banner(`起動時の確認(${env.length}件)`, env.map(x => esc(x)).join('<br>'), !miss.length) : '')
    + (miss.length ? banner(`準備が必要です(${miss.length}件)`, miss.join('<br>'), true) : '') + gpu;
}

/* ---------- 進行度 ---------- */

function goalSec(){ const h = Number(S.settings.goalHours); return (Number.isFinite(h) && h >= 0.5 && h <= 200 ? h : 5) * 3600; }

function todayKey(){ const d = new Date(); return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; }

function renderProgress(){
  if (!PG) return;
  const goal = goalSec(), cur = PG.proofedSec, pct = Math.min(100, cur / goal * 100);
  $('#goalFill').style.width = pct + '%'; $('#goalBar').setAttribute('aria-valuenow', Math.round(pct));
  const shown = pct < 10 ? pct.toFixed(1) : String(Math.round(pct));
  $('#goalText').innerHTML = `<b>${fmtDur(cur)}</b> / ${fmtDur(goal)}(<b>${shown}%</b>)・${PG.proofedLines}行`;
  const bar = $('#goalBar'); bar.querySelectorAll('b').forEach(x => x.remove());
  const ms = MILESTONES.filter(m => m[0] < goal);
  for (const [s] of ms){ const b = document.createElement('b'); b.style.left = (s / goal * 100) + '%'; bar.appendChild(b); }
  const list = [...ms, [goal, '目標']];
  const next = list.find(m => cur < m[0]);
  $('#goalMs').innerHTML = list.map(([s, txt]) => `<div class="ms${cur >= s ? ' done' : ''}"><span class="ck">${cur >= s ? uiIcon('check', { size: 12 }) || '済' : '・'}</span><span>${fmtDur(s)}: ${esc(txt)}${next && next[0] === s ? `(あと ${fmtDur(s - cur)})` : ''}</span></div>`).join('');
  let base = cur;
  try { const o = JSON.parse(localStorage.getItem('tx.goalday') || 'null'); if (o && o.day === todayKey() && Number.isFinite(o.base)) base = o.base; else localStorage.setItem('tx.goalday', JSON.stringify({ day: todayKey(), base: cur })); } catch {}
  const gain = Math.max(0, cur - base);
  $('#goalToday').textContent = gain > 0 ? `今日は ${fmtDur(gain)} 進みました` : '今日はまだ進んでいません';
  /* 評価用の本数と校正済みの行(学習用と分けて数える)。精度の目標は下の「定点」(全部聞いて確かめた動画 15 分。renderDrillStat)に一本化した(Q4。以前の「目安 20 分・全行を校正」はやめた) */
  { const n = PG.evalDocs;
    $('#evalStat').innerHTML = `<div style="font-weight:600;font-size:13.5px">評価用(学習に使わない・精度を測るためだけ)</div>` + (n ? `<p style="margin:4px 0 0;font-size:13.5px"><b>${n}</b>本 ・ 校正済みの行 ${PG.evalProofedLines}行(${fmtDur(PG.evalProofedSec)})</p>`
      + `<p class="hint" style="margin:2px 0 0">精度の測定の正解(定点)に数えるのは、動画を全部聞いて「済み」にしたものだけです(下の評価ドリル)。</p>`
      : `<p class="hint" style="margin:4px 0 0">まだありません。設定の「評価用のフォルダ」から仮置きの動画をまとめて文字起こしするか、文字起こしを開いて「評価用にする」にチェックしてください(校正を始める前に決めてください)。</p>`); }
  const p = $('#goalPill'); p.hidden = false;
  $('#goalPillT').textContent = `校正 ${fmtDur(cur)} / ${fmtDur(goal)}`;
  $('#goalPillBar').style.width = pct + '%';
  p.title = `校正済みの量 ${fmtDur(cur)} / 目標 ${fmtDur(goal)}(${shown}%)。押すと進行度を見ます`;
  if (document.activeElement !== $('#goalHours')) $('#goalHours').value = String(goal / 3600);
  // 節目に届いたら、一度だけ知らせる
  try {
    const reached = list.filter(m => cur >= m[0]).length, seenN = Number(localStorage.getItem('tx.goalseen') || '-1');
    if (seenN >= 0 && reached > seenN) toast(`節目に届きました: ${fmtDur(list[reached - 1][0])}(${list[reached - 1][1]})`, 6000);
    if (reached !== seenN) localStorage.setItem('tx.goalseen', String(reached));
  } catch {}
}

async function loadProgress(){ loadDrillStat(); try { PG = await api('/api/progress'); } catch { return; } renderProgress(); }   // 定点の「あと何分」(Q4)も一緒に

function scheduleProgress(){ clearTimeout(scheduleProgress.t); scheduleProgress.t = setTimeout(loadProgress, 2500); }
