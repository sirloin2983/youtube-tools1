/* 切り抜きスタジオ: 画面の共通部分(window.Studio)。各 JS はこのAPIだけに依存する。
   ヘッダー(タブ・他のツール・キー一覧・設定の引き出し)と、起動時の ?url= の受け取りもここで扱う。 */
(() => {
'use strict';
const APP_VERSION = (document.querySelector('meta[name="ytt-version"]') || {}).content || '';   // 全体の版(ytt/version.py)。入口が画面を返すときに meta ytt-version へ入れる(JS に版の文字は書かない)。入口なしだと空 = 版の比べはしない
const $ = s => document.querySelector(s);
const Studio = window.Studio = { version: APP_VERSION, state: null, review: null, ready: false, ports: null, params: {} };
const STEPS = ['rank', 'review'];   // 0.24.0: 「2 解析」のタブを無くした(URL の欄と順番待ちは ① の先頭・解析の設定は ⚙ の「解析」。docs/spec/settings.md の 3)
const PANES = { rank: '#paneRank', review: '#paneReview' };
/* ui-kit.js は index.html で core.js より先に同期で読むので、UIKit はいつもある(無いときの予備の経路は持たない。0.23.4) */

Studio.esc = UIKit.esc;   // HTML の文字の書き換え(ui-kit の 1 か所。null・undefined は '')
/* 秒 → 1:23.4 / 1:02:03.4(0.1 秒まで。② のマーク・コラボの時刻。ui-kit の 1 か所) */
Studio.fmtTime = t => UIKit.fmt.dur(t, { tenths: true });

/* API・メディアの URL はここでだけ組み立てる(docs/spec/pipeline.md 5.)。
   画面の場所から決める: 単独で起動したときは http://localhost:8800/ → ''、入口の統合サーバーに取り込まれたときは http://localhost:8700/studio/ → '/studio' */
Studio.base = location.pathname.replace(/\/[^/]*$/, '');
/* 統合サーバーは、書き込み系の API に合言葉(CSRF トークン)を求める。画面に埋め込まれていれば送る(単独で起動したときは無い) */
const tokenMeta = document.querySelector('meta[name="ytt-token"]');
Studio.token = tokenMeta ? tokenMeta.content : '';
Studio.url = p => Studio.base + p;

/* JSON API 呼び出し。中身は ui-kit の UIKit.http(合言葉を付けるのも失敗の形を決めるのもそこの 1 か所。0.23.4)。
   失敗は Error(message)(e.code にサーバーのエラーコード(無ければ 'http'。応答が無ければ 'network')、e.status にHTTPステータス、e.body に応答の JSON(無ければ {})、e.detail)。
   サーバーが文を返さなかった失敗の文は UIKit.http の既定(HTTP の番号は本文に出さず e.detail に。見直し S4・2 周目) */
const OFFLINE_STUDIO = 'サーバーに接続できません(黒い画面が閉じていないか確認してください)';
const OFFLINE_HOME = 'ホームのサーバーに接続できません(start.bat の黒い画面が閉じていないか確かめてください)';
Studio.api = (path, opts = {}) => UIKit.http(Studio.url(path), { method: opts.method, body: opts.body, signal: opts.signal, offline: OFFLINE_STUDIO });

/* 入口の API(/api/autorun など。まとめて実行)。取り込まれた画面は入口の /studio/ の下にあるので、画面の場所から1つ上(UIKit.homeApi。絶対パスを書かない)。
   入口から開いたとき(Studio.token があるとき)だけ使う。body があれば POST(合言葉つき)、無ければ GET。失敗の形は Studio.api と同じ */
Studio.portalApi = (path, body) => UIKit.homeApi(path, { body, offline: OFFLINE_HOME });

/* ---------- 入口のリアルタイム切り抜き(線 D の P3。plan/line-d-live-clipping.md の 0-8)の API(../live/…) ----------
   スタジオのサーバーは録画の部品と話さない(単独でも動く作りを保つ)ので、画面が入口の ../live/… を呼ぶ(同じオリジン・入口の合言葉)。
   URL はここでだけ組み立てる(Studio.live.url)。入口から開いたとき(Studio.token)だけ使う。機能がオフなら入口は 404 を返す */
const LIVE = { infoP: null, offAt: 0 };
const LIVE_RECHECK_MS = 60000;   // オフ(404)と分かったあと、入口の設定でオンにされたかを確かめ直すまでの間(begin は呼ばない)
Studio.live = {
  info: null,
  url: rest => UIKit.homeUrl('live/' + rest),
  /* JSON の API(UIKit.homeApi)。失敗の形は Studio.api と同じ(時間切れは e.code 'timeout')。GET は 10 秒・POST は 45 秒で打ち切る(begin は yt-dlp で配信の状態を調べるので数秒かかる)。
     GET 以外はいつも本文を送る(無ければ {}。begin・stop などが頼っている) */
  api: (rest, opts = {}) => {
    const method = opts.method || (opts.body !== undefined ? 'POST' : 'GET');
    return UIKit.homeApi('live/' + rest, { method, body: method !== 'GET' ? (opts.body || {}) : undefined, timeout: opts.timeout || (method === 'GET' ? 10000 : 45000),
      offline: OFFLINE_HOME, slow: 'ホームから時間内に応答がありません' });
  },
  /* ライブの機能が使えるか(入口の ../live/api/info)。使えるなら info、使えない(単独起動・オフ・失敗)なら null。
     成功は覚える。404(オフ)も覚えて、しばらく聞き直さない。通信の失敗は覚えない(次に聞き直す) */
  available: () => {
    if (!Studio.token) return Promise.resolve(null);
    if (LIVE.offAt && Date.now() - LIVE.offAt < LIVE_RECHECK_MS) return Promise.resolve(null);
    if (!LIVE.infoP){
      LIVE.infoP = Studio.live.api('api/info').then(j => {
        if (!j || j.enabled === false){ LIVE.offAt = Date.now(); LIVE.infoP = null; return null; }
        LIVE.offAt = 0; Studio.live.info = j; return j;
      }, e => { LIVE.infoP = null; if (e.status === 404) LIVE.offAt = Date.now(); return null; });
    }
    return LIVE.infoP;
  },
  /* 置き場所・空きを読み直す(設定の引き出しを開いたとき) */
  refreshInfo: () => { LIVE.infoP = null; LIVE.offAt = 0; return Studio.live.available(); },
  /* 録画をスタジオの配信1本(kind "live")として登録する(既にあればそれ)。録画を始める・開くのはどの道(① の URL 欄・② の「開く」・① 探す・ヘッダーの札)もここを通る。
     rec = {id, url?, title?, channel?}(入口の begin の recording か、札・① 探す の録画)。fb = 録画に無いときに使う {url?, title?, channel?}(① 探す の行のチャンネル名など)。
     channel は配信者の名前(字幕の色)をチャンネル名から決めるのに使う(サーバーは空なら入れない・既にあれば上書きしない) → {video} */
  register: (recorder, rec, fb = {}) => Studio.api('/api/videos/open', { body: { kind: 'live', recorder, recording: rec.id,
    url: rec.url || fb.url || '', title: rec.title || fb.title || '', channel: String(rec.channel || fb.channel || '').slice(0, 100) } }),
  /* URL の配信が配信中・配信前なら録画を始め(入口の api/begin)、スタジオに配信1本(kind "live")として登録する。
     → { video, existing, recording, recorder }。配信中でない・機能がない・調べられない → null(今までどおり解析・開くへ)。
     録画は始まったのにスタジオに登録できなかったときだけ例外(解析へ回すと、同じ配信を二重に扱うため)。
     opts.channel: 入口の begin がチャンネル名を返さなかったときに使う名前(① 探す の行は取得元からチャンネル名を持っている) */
  begin: async (url, opts = {}) => {
    if (!(await Studio.live.available())) return null;
    let b;
    try { b = await Studio.live.api('api/begin', { body: { url } }); }
    catch (e){ if (e.status === 404){ LIVE.offAt = Date.now(); LIVE.infoP = null; } return null; }
    const rec = b && b.live && b.recording;
    if (!rec || !rec.id || !b.recorder) return null;
    let r;
    try { r = await Studio.live.register(b.recorder, rec, { url, channel: opts && opts.channel }); }
    catch (e){ throw new Error('録画は始めましたが、スタジオに登録できませんでした: ' + e.message); }
    try { UIKit.liveBadge.refresh(); } catch {}   // ヘッダーの「録画中」の札をすぐ出す(札の見回りは 10 秒ごと)
    return { video: r.video, existing: !!b.existing, recording: rec, recorder: b.recorder };
  },
  /* begin の結果 b を知らせる文(① の URL 欄・② の「開く」・① 探す の「録画する」で同じ文) */
  begunText: b => (b.existing ? 'この配信はもう録画しています。その録画を開きました' : '配信の録画を始めました。見ながらマークできます'),
  /* 録画を始めた配信を知らせて ② で開く(① の URL 欄・① 探す)。more: 文の後ろに足す一言 */
  openBegun: (b, more) => {
    Studio.toast(Studio.live.begunText(b) + (more || ''), 6000, 'ok');
    return Studio.openReview(b.video.id);
  }
};

/* 通知。kind: 'ok' | 'err' | 'info'(省略時は色なし)。ui-kit の重ねて最大3つのトースト(入れ物は id="toast")を呼ぶだけ。
   ms が 0・省略なら ui-kit の既定の秒数(成功 2.5 秒・失敗 8 秒)。呼び出しの多くは昔の「0 = 既定」の形(toast(msg, 0, 'ok'))なので、
   ui-kit v7 の ms: 0 =「消えない」をそのまま渡さない(段1。渡していたので、成功の知らせまで × を押すまで残っていた)。
   消えない知らせにしたいときは ms にオブジェクトを渡す(例: Studio.toast(msg, { ms: 0, kind: 'err' })。そのまま UIKit.toast へ) */
Studio.toast = (msg, ms, kind) => {
  if (ms && typeof ms === 'object') return UIKit.toast(msg, ms);
  return UIKit.toast(msg, { ms: ms || undefined, kind });
};
/* 赤い帯(画面の全体の失敗)。文 + [読み込み直す] + 閉じる(見直し S4。以前は文だけで、閉じられなかった)。「起動し直す」の帯(UIKit.restart)が出ているときは上書きしない */
Studio.showErr = msg => {
  const b = $('#errBar'); if (!b || b.querySelector('.ui-restart-msg')) return;
  const el = (tag, cls, text) => { const x = document.createElement(tag); if (cls) x.className = cls; if (text !== undefined) x.textContent = text; return x; };
  b.textContent = '';
  const acts = el('span', 'cs-err-acts'), reload = el('button', 'btn small', '読み込み直す');
  reload.type = 'button'; reload.addEventListener('click', () => location.reload());
  const x = el('button', 'btn small ghost icon cs-err-x'); x.type = 'button'; x.setAttribute('aria-label', 'エラーの帯を閉じる'); x.title = 'エラーの帯を閉じる';
  x.innerHTML = UIKit.icon('close', { size: 14 });
  x.addEventListener('click', () => { b.hidden = true; });
  acts.append(reload, x);
  b.append(el('span', 'cs-err-msg', String(msg)), acts); b.hidden = false;
};

/* 作業データ(data.json)の読み込みの問題。サーバーは起動して最初の /api/state で 1 回だけ知らせる(dataWarning)ので、ここで覚えて
   ① と ② の帯の両方に同じ文を出す。閉じるとどちらも消え、知らせは 1 回だけ(見直し M8。以前は帯 2 つと知らせ 2 回)。
   文はサーバーが作る「何が起きたか + 戻し方」。退避したファイルの名前と作業データのフォルダは畳んだ「詳しく」へ */
const DW = { w: '', backup: '', dir: '', dismissed: false, toasted: false, boxes: new Set() };
Studio.dataWarning = box => {
  const st = Studio.state || {};
  if (st.dataWarning && !DW.w){ DW.w = String(st.dataWarning); DW.backup = String(st.corruptBackup || ''); DW.dir = String(st.dataDir || ''); }
  if (!box) return;
  if (!DW.boxes.has(box)){
    DW.boxes.add(box);
    box.addEventListener('click', e => { if (!e.target.closest('[data-dw-close]')) return; DW.dismissed = true; DW.boxes.forEach(b => { b.hidden = true; }); });
  }
  if (!DW.w || DW.dismissed){ box.hidden = true; return; }
  if (!box.hidden && box.childElementCount) return;
  const det = [DW.backup && '退避したファイル: ' + DW.backup, '1 つ前の控え: data.json.bak(ある場合)', DW.dir && '作業データのフォルダ: ' + DW.dir].filter(Boolean);
  box.innerHTML = `<div><b>作業データの読み込みで問題がありました</b><br>${Studio.esc(DW.w)}<details class="q-raw ui-disclosure"><summary>詳しく</summary><code>${det.map(Studio.esc).join('\n')}</code></details></div><button type="button" class="btn small" data-dw-close>閉じる</button>`;
  box.hidden = false;
  if (!DW.toasted){ DW.toasted = true; Studio.toast('作業データの読み込みで問題がありました(上の帯に戻し方があります)', 9000, 'err'); }
};

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

/* 押せない理由(A-34): why があれば押せなくして、理由を title と data-ui-why に出す。無ければ押せるようにして、title は okTitle(使えるときの説明) */
Studio.why = (b, why, okTitle) => {
  b.disabled = !!why; b.title = why || okTitle || '';
  if (why) b.setAttribute('data-ui-why', why); else b.removeAttribute('data-ui-why');
};

/* タブの右の小さな件数(「残っている作業の数」。赤い警告ではない)。text が空なら隠す。title は件数の意味(読み上げにも使う) */
Studio.setBadge = (step, text, title) => {
  const b = $('#badge' + step.charAt(0).toUpperCase() + step.slice(1)); if (!b) return;
  b.textContent = text || ''; b.hidden = !text;
  if (title){ b.title = title; b.setAttribute('aria-label', title); } else { b.removeAttribute('title'); b.removeAttribute('aria-label'); }
};
/* 一覧の「いつの」(ui-kit の UIKit.fmt。ms が無いときは空) */
Studio.ago = ms => UIKit.fmt.ago(ms);
Studio.date = ms => UIKit.fmt.date(ms);
/* 配信か手元の動画ファイルか(用語集: 配信 = YouTube の配信、動画ファイル = 手元のファイル)。
   ライブの録画(kind "live")も配信1本として扱う(録画中の札は ② の一覧と LIVE の帯で出す) */
Studio.noun = v => (v && v.kind === 'file' ? '動画ファイル' : '配信');
/* YouTube の動画 ID(11 文字)か。① 探す・① の URL 欄・② で同じ決まり */
Studio.isVideoId = s => /^[\w-]{11}$/.test(s || '');
/* YouTube で開く URL(t 秒が 1 以上ならその位置から) */
Studio.watchUrl = (id, t) => 'https://www.youtube.com/watch?v=' + encodeURIComponent(id) + (t >= 1 ? '&t=' + Math.floor(t) + 's' : '');
/* 一覧の探す欄: 空白で分けた語が全部 hay(題名・配信者など)に入っているか。大文字と小文字は区別しない。q が空なら true */
Studio.matchWords = (q, hay) => {
  q = String(q || '').trim().toLowerCase();
  if (!q) return true;
  hay = String(hay).toLowerCase();
  return q.split(/\s+/).every(w => hay.includes(w));
};
/* key(x) ごとにまとめる → Map(最初に出てきた順) */
Studio.groupBy = (list, key) => {
  const m = new Map();
  for (const x of list){ const k = key(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x); }
  return m;
};

Studio.step = 'rank';
Studio.go = step => {
  if (step === 'queue') step = 'rank';   // 旧い保存値(clipstudio:step)と以前の呼び出し(解析のタブ)は ① へ(URL の欄は ① の先頭にある)
  if (!STEPS.includes(step)) return;
  Studio.step = step;
  for (const s of STEPS){ $(PANES[s]).hidden = s !== step; }
  document.querySelectorAll('#steps .step').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.step === step)));
  try { localStorage.setItem('clipstudio:step', step); } catch {}
  document.dispatchEvent(new CustomEvent('studio:step', { detail: step }));
};

/* ② 確認・書き出しでその配信を開く(① 探す・① の URL 欄・録画を始めたとき)。review.js は読み込みの時点で Studio.review を作るので、
   無いのは review.js が読み込みで落ちたときだけ(そのときは知らせる) */
Studio.openReview = async id => {
  if (Studio.review && Studio.review.open) return Studio.review.open(id);
  Studio.toast('確認画面がまだ読み込まれていません', 0, 'err');
};

/* 各 JS の初期化。ready 後に呼ばれる(すでに ready なら即実行) */
const readyFns = [];
Studio.onReady = fn => { if (Studio.ready) fn(); else readyFns.push(fn); };
Studio.on = (name, fn) => document.addEventListener('studio:' + name, e => fn(e.detail));

/* 文字入力中か(キー操作を奪わない判定。チェックボックスの上は入力中に数えない。range は UIKit.keys.isTyping と合わせて
   入力中に数える: スライダー(音量など)の上では ← → などのキーをスライダー自身に譲り、② のショートカットに奪わせない) */
Studio.isTyping = el => {
  if (!el || !el.tagName) return false;
  const tag = el.tagName;
  if (el.classList && el.classList.contains('ui-time')) return true;   // 時刻の欄(UIKit.timebox。数字・矢印を自分で使う)
  return tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable || (tag === 'INPUT' && !['checkbox', 'radio', 'button', 'submit', 'reset', 'color', 'file'].includes(el.type));
};
/* 設定の引き出し・ダイアログが開いている間は、② のショートカットを止める(裏の動画が勝手に動かないように) */
Studio.overlayOpen = () => !!(document.querySelector('dialog[open]') || (Studio.drawer && Studio.drawer.isOpen()));
/* 開いているメニュー(他のツール・② の配信の選択など)の中でのキー操作か。メニューの中の文字やボタンでは ② のキー操作を効かせない */
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
      UIKit.tools.setPaths(j && j.paths);   // 取り込まれたツールの場所(/studio/ など)
    })
    .catch(() => { Studio.ports = null; })   // 404(未実装の古いサーバー)・通信失敗は既定のポートで
    .finally(() => { sibP = null; document.dispatchEvent(new CustomEvent('studio:ports', { detail: Studio.ports })); });
  return sibP;
};
/* 他のツールの画面の URL(ports が分からなければ既定のポート) */
Studio.toolUrl = (id, path) => UIKit.tools.url(id, Studio.ports, path);

/* ---------- 設定の引き出し(中身は settings.js。器は ui-kit の UIKit.settings.mount が作る #uiSettingsDrawer) ----------
   Studio.drawer / Studio.openSettings は他のコード・テストが使うので、薄い包み(UIKit.drawer + #uiSettingsDrawer)として残す */
const drawer = Studio.drawer = {
  isOpen: () => { const d = $('#uiSettingsDrawer'); return !!(d && UIKit.drawer.isOpen(d)); },
  open(opener){ const d = $('#uiSettingsDrawer'); if (d) UIKit.drawer.open(d, { modal: true, opener: opener || document.activeElement }); },
  close(){ const d = $('#uiSettingsDrawer'); if (d) UIKit.drawer.close(d); }
};
/* settings.js が中身を作ったあとで、特定の節を開く版に置き換える。ここでは引き出しを開くだけ */
Studio.openSettings = () => drawer.open();

/* ---------- キー操作の一覧(? キー) ---------- キーの一覧 = キー配置(UIKit.keymap。② の「キー配置」と同じ部品。段6) */
Studio.openKeyHelp = () => {
  const dlg = $('#keyHelp'), km = Studio.review && Studio.review.keymap; if (!dlg || dlg.open || !km) return;
  km.mount($('#keyHelpBody')); km.clearNote(); dlg.showModal();
};
function wireKeyHelp(){
  const dlg = $('#keyHelp');
  $('#btnKeys').addEventListener('click', Studio.openKeyHelp);
  $('#keyHelpClose').addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });   // 枠の外(背景)を押したら閉じる
  /* window の bubble で受ける: document で受ける ② のショートカットより後に動く。② が ? を割り当てて処理した(defaultPrevented)ときは開かない。
     Esc は ui-kit(設定の引き出し・ポップオーバー)が自分で閉じるので、ここでは ? のキー一覧だけを扱う */
  window.addEventListener('keydown', e => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
    if (e.key !== '?' || Studio.isTyping(e.target)) return;
    if (dlg.open){ e.preventDefault(); dlg.close(); return; }
    if (drawer.isOpen()) return;
    e.preventDefault(); Studio.openKeyHelp();
  });
}

/* ---------- 起動時の URL 引数(?url= は ① の「URL から入れる」の欄へ入れるだけ。自動では始めない: docs/spec/pipeline.md 3.) ---------- */
function readParams(){
  let q; try { q = new URLSearchParams(location.search); } catch { return; }
  const url = (q.get('url') || '').trim(), video = (q.get('video') || '').trim(), step = (q.get('step') || '').trim();
  if (url) Studio.params.url = url.slice(0, 2000);
  if (/^[\w-]{1,64}$/.test(video)) Studio.params.video = video;   // B-6: 「編集」から戻るとき。保存済みの配信なら ② の確認画面で開く
  if (STEPS.includes(step)) Studio.params.step = step;   // 段7: ?step=rank = ① 探す を開く(ホームの「スタジオで配信を探す」。前回のタブより先)
  if ((url || video || step) && history.replaceState){ try { history.replaceState(null, '', location.pathname + location.hash); } catch {} }   // 再読み込みで二重に入れない
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
document.addEventListener('DOMContentLoaded', () => { UIKit.appnav.setVersion('v' + APP_VERSION); });
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
    if (!APP_VERSION) $('#ver').textContent = 'v' + p.version;
    else if (p.version !== APP_VERSION && !UIKit.restart.check($('#errBar'), APP_VERSION, p.version))   // 帯に「起動し直す」(段9 9-3)
      Studio.showErr('画面(v' + APP_VERSION + ')とサーバー(v' + p.version + ')の版が違います。黒い画面を閉じて起動し直してください');
    await Studio.refreshState();
  } catch (e){ Studio.showErr(e.message); paneError(e.message); return; }
  Studio.ready = true;
  /* B-6: ?video= の配信が保存済みなら、解析の欄(?url=)ではなく ② の確認画面でその配信を開く(作業の再開。再解析を求めているように見えないように) */
  let openVid = null;
  if (Studio.params.video){
    try { openVid = ((await Studio.api('/api/videos')).videos || []).some(v => v.id === Studio.params.video) ? Studio.params.video : null; } catch {}
    if (openVid) Studio.params.url = '';
  }
  for (const fn of readyFns.splice(0)){ try { fn(); } catch (e){ console.error(e); Studio.showErr('画面の初期化に失敗しました: ' + e.message); } }
  let st = 'rank'; try { st = localStorage.getItem('clipstudio:step') || 'rank'; } catch {}
  if (openVid && Studio.review){ Studio.review.open(openVid); return; }
  if (Studio.params.url) st = 'rank';   // URL の欄は ① の先頭(queue.js がフォーカスを当てる)
  else if (Studio.params.step) st = Studio.params.step;
  Studio.go(STEPS.includes(st) ? st : 'rank');
};
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
