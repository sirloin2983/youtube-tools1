/* 切り抜きスタジオ: 画面の共通部分(window.Studio)。各 JS はこのAPIだけに依存する。
   ヘッダー(タブ・他のツール・キー一覧・設定の引き出し)と、起動時の ?url= の受け取りもここで扱う。 */
(() => {
'use strict';
const APP_VERSION = '0.11.0';   // serve.py の SERVER_VERSION と同じ値にする
const $ = s => document.querySelector(s);
const Studio = window.Studio = { version: APP_VERSION, state: null, review: null, ready: false, ports: null, params: {} };
const STEPS = ['rank', 'queue', 'review'];
const PANES = { rank: '#paneRank', queue: '#paneQueue', review: '#paneReview' };

Studio.esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* API・メディアの URL はここでだけ組み立てる(docs/pipeline.md 5.)。
   画面の場所から決める: 単独で起動したときは http://localhost:8800/ → ''、入口の統合サーバーに取り込まれたときは http://localhost:8700/studio/ → '/studio' */
Studio.base = location.pathname.replace(/\/[^/]*$/, '');
/* 統合サーバーは、書き込み系の API に合言葉(CSRF トークン)を求める。画面に埋め込まれていれば送る(単独で起動したときは無い) */
const tokenMeta = document.querySelector('meta[name="ytt-token"]');
Studio.token = tokenMeta ? tokenMeta.content : '';
Studio.url = p => Studio.base + p;

/* JSON API 呼び出し。失敗は Error(message)(e.code にサーバーのエラーコード、e.status にHTTPステータス、e.body に応答の JSON) */
Studio.api = async (path, opts = {}) => {
  const init = { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'), cache: 'no-store', headers: {} };
  if (opts.body !== undefined){ init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  if (Studio.token && init.method !== 'GET') init.headers['X-YTT-Token'] = Studio.token;
  if (opts.signal) init.signal = opts.signal;
  let r;
  try { r = await fetch(Studio.url(path), init); } catch (e){ const er = new Error('サーバーに接続できません(黒い画面が閉じていないか確認してください)'); er.code = 'network'; throw er; }
  let j = null;
  try { j = await r.json(); } catch {}
  if (!r.ok){ const er = new Error((j && j.message) || ('サーバーエラー(HTTP ' + r.status + ')')); er.code = (j && j.error) || 'http'; er.status = r.status; er.body = j; throw er; }
  return j;
};

/* 入口の API(/api/autorun など。まとめて実行)。取り込まれた画面は入口の /studio/ の下にあるので、画面の場所から1つ上(絶対パスを書かない)。
   入口から開いたとき(Studio.token があるとき)だけ使う。失敗は Error(message)(e.code・e.status) */
Studio.portalApi = async (path, body) => {
  const init = { cache: 'no-store', method: body === undefined ? 'GET' : 'POST' };
  if (body !== undefined){ init.headers = { 'Content-Type': 'application/json', 'X-YTT-Token': Studio.token }; init.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(new URL('../' + path, location.href).href, init); } catch { throw new Error('ホームのサーバーに接続できません(start.bat の黒い画面が閉じていないか確かめてください)'); }
  let j = {};
  try { j = await r.json(); } catch {}
  if (!r.ok){ const er = new Error(j.message || ('エラー(HTTP ' + r.status + ')')); er.code = j.error; er.status = r.status; throw er; }
  return j;
};

/* 通知。kind: 'ok' | 'err' | 'info'(省略時は色なし)。ui-kit の重ねて最大3つのトースト(入れ物は id="toast")を呼ぶだけ */
Studio.toast = (msg, ms, kind) => { if (window.UIKit && UIKit.toast) UIKit.toast(msg, { ms, kind }); };
Studio.showErr = msg => { const b = $('#errBar'); b.textContent = String(msg); b.hidden = false; };

/* 状態の取得。続けて呼ばれたときは、最後に頼んだ分だけを反映する(古い応答で新しい状態を上書きしない) */
let stateSeq = 0;
Studio.refreshState = async () => {
  const my = ++stateSeq;
  const st = await Studio.api('/api/state');
  if (my !== stateSeq) return Studio.state;
  Studio.state = st;
  document.dispatchEvent(new CustomEvent('studio:state', { detail: Studio.state }));
  return Studio.state;
};

/* タブの右の小さな件数(「残っている作業の数」。赤い警告ではない)。text が空なら隠す。title は件数の意味(読み上げにも使う) */
Studio.setBadge = (step, text, title) => {
  const b = $('#badge' + step.charAt(0).toUpperCase() + step.slice(1)); if (!b) return;
  b.textContent = text || ''; b.hidden = !text;
  if (title){ b.title = title; b.setAttribute('aria-label', title); } else { b.removeAttribute('title'); b.removeAttribute('aria-label'); }
};
/* 一覧の「いつの」(ui-kit の UIKit.fmt。無いときは空) */
Studio.ago = ms => (window.UIKit && UIKit.fmt && ms ? UIKit.fmt.ago(ms) : '');
Studio.date = ms => (window.UIKit && UIKit.fmt && ms ? UIKit.fmt.date(ms) : '');
/* 配信か手元の動画ファイルか(用語集: 配信 = YouTube の配信、動画ファイル = 手元のファイル) */
Studio.noun = v => (v && v.kind === 'file' ? '動画ファイル' : '配信');

Studio.step = 'rank';
Studio.go = step => {
  if (!STEPS.includes(step)) return;
  Studio.step = step;
  for (const s of STEPS){ $(PANES[s]).hidden = s !== step; }
  document.querySelectorAll('#steps .step').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.step === step)));
  try { localStorage.setItem('clipstudio:step', step); } catch {}
  document.dispatchEvent(new CustomEvent('studio:step', { detail: step }));
};

/* 各 JS の初期化。ready 後に呼ばれる(すでに ready なら即実行) */
const readyFns = [];
Studio.onReady = fn => { if (Studio.ready) fn(); else readyFns.push(fn); };
Studio.on = (name, fn) => document.addEventListener('studio:' + name, e => fn(e.detail));

/* 文字入力中か(キー操作を奪わない判定。チェックボックスの上は入力中に数えない。range は UIKit.keys.isTyping と合わせて
   入力中に数える: スライダー(音量など)の上では ← → などのキーをスライダー自身に譲り、③ のショートカットに奪わせない) */
Studio.isTyping = el => {
  if (!el || !el.tagName) return false;
  const tag = el.tagName;
  return tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable || (tag === 'INPUT' && !['checkbox', 'radio', 'button', 'submit', 'reset', 'color', 'file'].includes(el.type));
};
/* 設定の引き出し・ダイアログが開いている間は、③ のショートカットを止める(裏の動画が勝手に動かないように) */
Studio.overlayOpen = () => !!(document.querySelector('dialog[open]') || (Studio.drawer && Studio.drawer.isOpen()));
/* 開いているメニュー(他のツール・③ の配信の選択など)の中でのキー操作か。メニューの中の文字やボタンでは ③ のキー操作を効かせない */
Studio.inMenu = el => !!(el && el.closest && el.closest('details.ui-menu[open]'));

/* ---------- ヘッダーの高さ(sticky の位置合わせ用。狭い画面ではタブが2段になるので実測する) ---------- */
function watchHeader(){
  const h = $('#appHeader'); if (!h) return;
  const set = () => document.documentElement.style.setProperty('--cs-head', Math.ceil(h.getBoundingClientRect().height) + 'px');
  set();
  if (window.ResizeObserver) new ResizeObserver(set).observe(h); else window.addEventListener('resize', set);
}

/* ---------- 他のツール(実際のポートはサーバーの /api/siblings。無い・失敗したら既定のポート)----------
   v6: ヘッダーの「他のツール」メニューはやめ、左上の ui-appnav(ホーム/スタジオ/編集)に一本化した(ui-kit.js が描く)。
   ここでは実際のポート(Studio.ports)だけ確かめておく(Studio.toolUrl・書き出し後の「編集で開く」リンクが使う) */
let sibP = null;
Studio.loadSiblings = () => {
  if (sibP) return sibP;
  sibP = Studio.api('/api/siblings')
    .then(j => {
      Studio.ports = j && j.tools && typeof j.tools === 'object' ? j.tools : null;
      if (window.UIKit && window.UIKit.tools.setPaths) window.UIKit.tools.setPaths(j && j.paths);   // 取り込まれたツールの場所(/studio/ など)
    })
    .catch(() => { Studio.ports = null; })   // 404(未実装の古いサーバー)・通信失敗は既定のポートで
    .finally(() => { sibP = null; document.dispatchEvent(new CustomEvent('studio:ports', { detail: Studio.ports })); });
  return sibP;
};
/* 他のツールの画面の URL(ports が分からなければ既定のポート) */
Studio.toolUrl = (id, path) => window.UIKit ? window.UIKit.tools.url(id, Studio.ports, path) : '';

/* ---------- 設定の引き出し(中身は settings.js。器は ui-kit の UIKit.settings.mount が作る #uiSettingsDrawer) ----------
   Studio.drawer / Studio.openSettings は他のコード・テストが使うので、薄い包み(UIKit.drawer + #uiSettingsDrawer)として残す */
const drawer = Studio.drawer = {
  isOpen: () => { const d = $('#uiSettingsDrawer'); return !!(d && window.UIKit && UIKit.drawer.isOpen(d)); },
  open(opener){ const d = $('#uiSettingsDrawer'); if (d && window.UIKit) UIKit.drawer.open(d, { modal: true, opener: opener || document.activeElement }); },
  close(){ const d = $('#uiSettingsDrawer'); if (d && window.UIKit) UIKit.drawer.close(d); }
};
/* settings.js が中身を作ったあとで、特定の節を開く版に置き換える。ここでは引き出しを開くだけ */
Studio.openSettings = () => drawer.open();

/* ---------- キー操作の一覧(? キー) ---------- */
function keyRows(rows){
  return rows.map(([k, label]) => `<div class="ui-krow"><span class="ui-kkeys">${k ? k.split(' / ').map(x => `<kbd>${Studio.esc(x)}</kbd>`).join('<span class="muted">/</span>') : '<span class="muted">未設定</span>'}</span><span class="ui-klabel">${Studio.esc(label)}</span></div>`).join('');
}
Studio.openKeyHelp = () => {
  const dlg = $('#keyHelp'); if (!dlg || dlg.open) return;
  const km = Studio.review && Studio.review.keymap;
  if (km){ km.mount($('#keyHelpBody')); km.clearNote(); dlg.showModal(); return; }   // キーの一覧 = キー配置(UIKit.keymap。③ の「キー配置」と同じ部品。段6)
  let html = window.UIKit && UIKit.keys ? `<div class="ui-kgrid">${UIKit.keys.helpHtml()}</div>` : '';
  html += `<section class="ui-kgroup"><h3 class="section-title">全体</h3>${keyRows([['?', 'この一覧を開く・閉じる'], ['Esc', '一覧・設定を閉じる']])}</section>`;
  const groups = Studio.review && Studio.review.keyHelp ? Studio.review.keyHelp() : [];
  if (groups.length){
    html += `<p class="hint cs-khint">③ 確認・書き出しで配信を開いているときに使えます(文字の入力欄にいる間は効きません)。共通の再生キーの下は、③ の「操作の設定」→「キー配置」で変えられます。</p>`;
    html += `<div class="ui-kgrid">${groups.map(([h, rows]) => `<section class="ui-kgroup"><h3 class="section-title">${Studio.esc(h)}</h3>${keyRows(rows)}</section>`).join('')}</div>`;
  }
  $('#keyHelpBody').innerHTML = html;
  dlg.showModal();
};
function wireKeyHelp(){
  const dlg = $('#keyHelp');
  $('#btnKeys').addEventListener('click', Studio.openKeyHelp);
  $('#keyHelpClose').addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });   // 枠の外(背景)を押したら閉じる
  /* window の bubble で受ける: document で受ける ③ のショートカットより後に動く。③ が ? を割り当てて処理した(defaultPrevented)ときは開かない。
     Esc は ui-kit(設定の引き出し・ポップオーバー)が自分で閉じるので、ここでは ? のキー一覧だけを扱う */
  window.addEventListener('keydown', e => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
    if (e.key !== '?' || Studio.isTyping(e.target)) return;
    if (dlg.open){ e.preventDefault(); dlg.close(); return; }
    if (drawer.isOpen()) return;
    e.preventDefault(); Studio.openKeyHelp();
  });
}

/* ---------- 起動時の URL 引数(?url= は ② 解析の URL 欄へ入れるだけ。自動では始めない: docs/pipeline.md 3.) ---------- */
function readParams(){
  let q; try { q = new URLSearchParams(location.search); } catch { return; }
  const url = (q.get('url') || '').trim(), video = (q.get('video') || '').trim();
  if (url) Studio.params.url = url.slice(0, 2000);
  if (/^[\w-]{1,64}$/.test(video)) Studio.params.video = video;   // B-6: 「編集」から戻るとき。保存済みの配信なら ③ の確認画面で開く
  if ((url || video) && history.replaceState){ try { history.replaceState(null, '', location.pathname + location.hash); } catch {} }   // 再読み込みで二重に入れない
}

function paneError(msg){
  for (const s of STEPS){
    const p = $(PANES[s]); if (!p) continue;
    p.innerHTML = `<div class="empty cs-fatal"><b>画面を準備できませんでした</b>${Studio.esc(msg)}<br><button type="button" class="btn small" data-reload>再読み込み</button></div>`;
  }
  document.querySelectorAll('[data-reload]').forEach(b => b.addEventListener('click', () => location.reload()));
}

document.querySelectorAll('#steps .step').forEach(b => b.addEventListener('click', () => Studio.go(b.dataset.step)));
$('#ver').textContent = 'v' + APP_VERSION;
/* UIKit.appnav の中身は DOMContentLoaded で描かれるので、そのあと(= ここより後)で版を出す */
document.addEventListener('DOMContentLoaded', () => { if (window.UIKit && UIKit.appnav) UIKit.appnav.setVersion('v' + APP_VERSION); });
readParams();
watchHeader();
wireKeyHelp();
/* #btnSettings の click は UIKit.settings.mount()(settings.js)が data-ui-settings を見て自分で結びつける */

/* スクリプトは body の最後で同期に読むので、DOMContentLoaded の時点で全部の onReady が登録済み(load を待つより早く始められる) */
const start = async () => {
  Studio.loadSiblings();
  try {
    const p = await Studio.api('/api/ping');
    if (p.app !== 'clip-studio') throw new Error('このアドレスは切り抜きスタジオではありません');
    if (p.version !== APP_VERSION) Studio.showErr('画面(v' + APP_VERSION + ')とサーバー(v' + p.version + ')の版が違います。黒い画面を閉じて起動し直してください');
    await Studio.refreshState();
  } catch (e){ Studio.showErr(e.message); paneError(e.message); return; }
  Studio.ready = true;
  /* B-6: ?video= の配信が保存済みなら、解析の欄(?url=)ではなく ③ の確認画面でその配信を開く(作業の再開。再解析を求めているように見えないように) */
  let openVid = null;
  if (Studio.params.video){
    try { openVid = ((await Studio.api('/api/videos')).videos || []).some(v => v.id === Studio.params.video) ? Studio.params.video : null; } catch {}
    if (openVid) Studio.params.url = '';
  }
  for (const fn of readyFns.splice(0)){ try { fn(); } catch (e){ console.error(e); Studio.showErr('画面の初期化に失敗しました: ' + e.message); } }
  let st = 'rank'; try { st = localStorage.getItem('clipstudio:step') || 'rank'; } catch {}
  if (openVid && Studio.review){ Studio.review.open(openVid); return; }
  if (Studio.params.url) st = 'queue';
  Studio.go(STEPS.includes(st) ? st : 'rank');
};
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
