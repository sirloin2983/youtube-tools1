/* ui-kit v37 —テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。
   画面の全面見直し(notes:docs/design/briefs/ui-overhaul/)の段階1。ES5 のまま(var・function。アロー関数・テンプレート文字列は使わない): <head> で同期に読み込むため。
   正本は src/ui-kit/ui-kit.js。写し先は無い(この正本を直接直す)。
   window.UIKit.theme  : get() 保存した選択('system'|'light'|'dark'。保存が無いときは既定で 'light') / set(p) / onChange(fn)
   window.UIKit.tools  : setPaths(/api/siblings の paths) で、入口の統合サーバーに取り込まれたツールの場所(/studio/ など)を覚える。base(id)・mounted()
   window.UIKit.life   : onLeave(fn(reason)) / onReturn(fn(reason)) / isAway()。画面を離れた・戻ったの合図(段階7-2)。
                         離れた = タブの切り替え('hidden')・別の窓へ移った('blur')・閉じる直前('pagehide')。戻った = 'visible' | 'focus' | 'pageshow'
   window.UIKit.report : report(message, info) 画面のエラーを入口のログ(app\logs\client-errors.jsonl)へ送る(段階7-0)。
                         捕まえられなかったエラー(error・unhandledrejection)は自動で送る。入口の外(合言葉なし)では送らない
   window.UIKit.win    : isApp() 窓(Edge のアプリモード)で開いているか / open(url) 入口に頼んで開く(段階7-3)。
                         窓の中の「新しいタブで開く」リンクは自動で: このパソコンの画面 → 同じ形の窓、外のサイト → いつものブラウザ
   window.UIKit.fmt : ago(ms) 相対の日時(「3日前」)/ date(ms) 日付と時刻 / dur(秒) 長さ(1:23:45)・day・dur の opt(floor・tenths・noHours)、window.UIKit.esc(s)
   UIKit.streamer : 配信者の名前(字幕の色)の欄 <input data-ui-streamer>(候補と色の見本)
   UIKit.portal : 入口へ戻るリンク(data-ui-portal)は、入口がほかの窓・タブで開いていれば新しく開かずにそちらを前に出す(入口が二つにならないように)
   画面の全面見直し(使い方は README.md の「v6」): UIKit.appnav(ホーム / 案件 / 確かめる / 設定の切り替え。<nav data-ui-appnav="portal|cases|check|settings">)・UIKit.drawer(右から出る引き出し)・UIKit.dialog(確認・警告)・
       details.ui-pop(ポップオーバー。ui-menu と同じ閉じ方)・UIKit.toast(通知。重ねて最大2つ)・UIKit.keybar(下の細い帯)・
       UIKit.settings.mount(設定の引き出し)・UIKit.keys(共通の再生キー)・UIKit.icon(SVG の線のアイコン)
   UIKit.toast : ms: 0 = 消えない・action: {label, fn}(ボタン1つ)・閉じるボタン・戻り値 {close}。UIKit.confirmTwice(btn, run, text)(二度押しの確認を1つに)。
       知らせがあふれたときは 時間で消える → ボタン・消えない知らせ(失敗でない) → ボタンの無い失敗 → 古いもの の順に閉じる(失敗の知らせは最後まで残す)。README.md の「v7」「v22」「v23」
   UIKit.prefs(ホームの設定 api/ytt/prefs: get(sections)・patch(section, value)(節ごと・まとめて送る)・remember(kind, key, name)・
       available()。保存に失敗したら知らせと [もう一度])。
   UIKit.autorun(まとめて実行の部品: panel(el, {kind}) = 要約1行と「設定を変える」・start(orders, opts) = 見積もり → 始める → 終わったら知らせ・
       stepLabel / runLabel = 状態の言葉)。受付は ② の口 POST api/flow/submit {envelope, spec} の 1 本。UIKit.flow.order(欄 → 封筒 + 束の差分。
       Python の src/flow/order.py と同じ変換)・start は見積もり api/flow/estimate を 1 本ずつ足す → 1 本ずつ submit → 終わるまで api/flow/runs を見て知らせる。README.md の「v28」
   UIKit.keymap(キーの一覧 = キー配置の設定。README.md の「v8」)。キーを変える場所は ? の一覧の 1 か所(⚙ にはボタンだけ)
   UIKit.settings.status(state, message, retry, label)(設定の保存・読み込みの失敗を ⚙ の印と引き出しの先頭に)・statusOf()
   UIKit.restart(版の赤い帯に「起動し直す」: check(el, 画面の版, サーバーの版) / band / run / available。入口の api/ytt/restart-self)。
       入口の応答に notice(まとめて実行の待ち・実行中は起動し直したあとに続きから進む)があれば、待つ間の帯の文に足す
   UIKit.theme.palette : サイバー風(計器盤)の形と配色。明るい = アイスライト、暗い = ネオンシアン・鋼の白・ターミナルグリーン・シンセウェーブ(synth)から選ぶ(README.md の「v12」)
   引き出し(modal)が裏を inert にするとき、<dialog> は外す(showModal が自分で前面と周りの扱いを決める。外さないと、ページに最初からあるダイアログ(編集の #dlgConfirm など)を ⚙ の中から開いたとき inert で操作できず固まる)
   UIKit.hide(一覧の項目を任意に非表示に。ホームの設定の節 hidden に覚える: load / has / set(list, ids, on) / count / showing / setShowing /
       toggle(btn, list, n)(「非表示 n件を表示」の切り替え)/ onChange。データは消さない。README.md の「v13」)
   UIKit.sound(ほかの窓で音が鳴っているかを BroadcastChannel で知らせ合う: other(tool) / onChange。スタジオの配信の音を、編集で再生している間だけ下げる・消すのに使う)。
   UIKit.liveBadge(ヘッダーの「録画中」の札。入口の api/ytt/live を 10 秒(オフなら 60 秒)ごとに問い合わせ、録画があるときだけ appnav のあるヘッダーに札と一覧を出す: get / refresh / onChange / onOpen。
       録画が終わった・切れたときの知らせ付き。線 D・notes:plan/line-d-live-clipping.md の 0-8。「開く」は案件の画面の候補(/cases?c=<録画 id>#cand)。README.md の「v16」)
   UIKit.timebox(時刻の欄。「:」を打たずに 時 → 分 → 秒 の順に数字だけで入れる: <span data-ui-time> / attach / create / get / set / parse / format。README.md の「v11」)。
       ホイール(opt.wheel / data-ui-time-wheel。マウスの下の単位を ±1・Shift で ±10・動いた単位を一瞬光らせる)・add(秒)(今の値に足す・動いた一番上の単位を光らせる)・貼り付けの前の口 ui-time-beforepaste(取り消せる。画面が止めたら値も reject も出さない)。README.md の「v29」
   画面の文言は「入口」でなく「ホーム」(用語集)。押せないメニュー(details.ui-menu / ui-pop の summary[aria-disabled=true] は開かずに理由を知らせる。UIKit.menuOff(el, why, title))・
       一覧の行の中の「次の一手」のボタン .ui-next-btn(ui-kit.css)。README.md の「v21」
   ポップオーバーの置き場所の直し(fitPop)は、まとめて実行の「設定を変える」の中身が読み込めたあとにもう一度・編集の形のポップオーバー(details.pop > .vpop)にもかける・
       置き直す中身に [data-ui-fit](画面が作った中身。スタジオ ① の .rk-autopop)。ui-kit.css の --danger-on(赤い面の上の文字)。知らせの × は SVG。設定の「全体」の節の名前は label for。README.md の「v22」「v23」
   UIKit.http(url, opt)(JSON の API を呼ぶ 1 か所・合言葉を付ける 1 か所・失敗の形を 1 つに)・
       UIKit.homeApi(path, opt) / homeUrl(path)(入口の API。画面の 1 つ上)・UIKit.copy(text, opt)(クリップボード)。ui-kit の中の fetch の包みは http を呼ぶ。README.md の「v24」
   UIKit.settingsForm(宣言的なスキーマから設定の節を描く。入口の /settings/ の画面が使う)・
       ⚙ の「全体」の節に「すべての設定を 1 つの画面で」(入口に取り込まれているときだけ。/settings へ)。README.md の「v25」
   左の一覧 .ui-rail・.ui-rail-item(ui-kit.css)・共通の再生キーにできないキーに Shift+N(案件: 次の未校正の切り抜き)。README.md の「v26」
   画面はどれも入口の直下の正本 ui-kit.js・ui-kit.css を読む(ツールごとの写しは無い)。README.md の「v27」 */
(function () {
  'use strict';
  var KEY = 'ytt:theme';
  /* 暗いときの配色(cyan = ネオンシアン・steel = 鋼の白・green = ターミナルグリーン・synth = シンセウェーブ)。明るいときはアイスライト(ice)だけ。
     明るい/暗い(ytt:theme)と分けて持つ = 切り替えボタン・OSに合わせる */
  var PAL_KEY = 'ytt:palette', DARK_PALETTES = { cyan: 'ネオンシアン', steel: '鋼の白', green: 'ターミナルグリーン', synth: 'シンセウェーブ' };   /* synth = 友人のアプリの配色(ピンクに固定) */
  function darkPalette() {
    try { var v = localStorage.getItem(PAL_KEY); return DARK_PALETTES[v] ? v : 'cyan'; } catch (e) { return 'cyan'; }
  }
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var subs = [];

  /* 保存が無いときの既定は明るい。'system'(OSに合わせる)は選んだときだけ明示的に保存する */
  function pref() {
    try { var v = localStorage.getItem(KEY); return v === 'light' || v === 'dark' || v === 'system' ? v : 'light'; } catch (e) { return 'light'; }
  }
  function resolve(p) { return p === 'system' ? (mq && mq.matches ? 'dark' : 'light') : p; }
  function paint(p) {
    var t = resolve(p);
    root.setAttribute('data-theme', t);
    root.setAttribute('data-palette', t === 'dark' ? darkPalette() : 'ice');
    root.setAttribute('data-theme-pref', p);
    for (var j = 0; j < subs.length; j++) { try { subs[j](t, p); } catch (e) { /* 購読側の失敗は無視 */ } }
  }
  function set(p) {
    if (p !== 'light' && p !== 'dark' && p !== 'system') p = 'light';
    try { localStorage.setItem(KEY, p); } catch (e) { /* 保存できなくても見た目は変える */ }   /* 'system' も明示的に保存する(absent は明るい) */
    paint(p);
  }
  var theme = {
    get: pref,
    set: set,
    /* 暗いときの配色。palette() → 'cyan' | 'steel' | 'green'、palette(name) で変えて保存する(明るい/暗いは変えない) */
    palette: function (name) {
      if (name === undefined) return darkPalette();
      if (!DARK_PALETTES[name]) return darkPalette();
      try { localStorage.setItem(PAL_KEY, name); } catch (e) { /* 保存できなくても見た目は変える */ }
      paint(pref());
      return name;
    },
    onChange: function (fn) { if (typeof fn === 'function') subs.push(fn); }
  };
  paint(pref());
  if (mq) {
    var onSys = function () { if (pref() === 'system') paint('system'); };
    if (mq.addEventListener) mq.addEventListener('change', onSys); else if (mq.addListener) mq.addListener(onSys);
  }
  /* 別のタブで切り替えたら、このタブも合わせる */
  window.addEventListener('storage', function (e) { if (e.key === KEY || e.key === PAL_KEY) paint(pref()); });
  /* 「他のツール」などの <details class="ui-menu"> と、<details class="ui-pop">(ポップオーバー)を、外側のクリックと Esc で閉じる */
  var POP_SEL = 'details.ui-menu[open], details.ui-pop[open]';
  document.addEventListener('click', function (e) {
    var open = document.querySelectorAll(POP_SEL);
    for (var i = 0; i < open.length; i++) if (!open[i].contains(e.target)) open[i].removeAttribute('open');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open = document.querySelectorAll(POP_SEL);
    for (var i = 0; i < open.length; i++) {
      var d = open[i], s = d.querySelector('summary');
      d.removeAttribute('open');
      if (s && s.focus) s.focus({ preventScroll: true });   /* Esc では summary へフォーカスを戻す */
    }
  });
  /* 押せないメニュー。
     <details class="ui-menu|ui-pop"> の <summary aria-disabled="true"> は開かずに、理由(data-ui-why、無ければ title)を知らせる。Enter・Space も click になる。
     捕まえる段階(capture)で止めるので、画面の側の summary の click は呼ばれない(押せないボタンと同じ)。付け外しは UIKit.menuOff(details か summary, 理由, 使えるときの title) */
  var MENU_OFF_SEL = 'details.ui-menu > summary[aria-disabled=true], details.ui-pop > summary[aria-disabled=true]';
  document.addEventListener('click', function (e) {
    var s = e.target && e.target.closest ? e.target.closest(MENU_OFF_SEL) : null;
    if (!s) return;
    e.preventDefault(); e.stopPropagation();
    var d = s.parentNode, open = document.querySelectorAll(POP_SEL);
    for (var i = 0; i < open.length; i++) if (!open[i].contains(d)) open[i].removeAttribute('open');   // ほかのメニューは、外側を押したときと同じく閉じる
    d.removeAttribute('open');
    var why = s.getAttribute('data-ui-why') || s.getAttribute('title') || 'いまは使えません';
    var shown = toastBox && toastBox.isConnected ? toastBox.querySelectorAll('.ui-toast-msg') : [];
    for (var k = 0; k < shown.length; k++) if (shown[k].textContent === why) return;   // 続けて押しても同じ知らせを積まない
    toastFn(why, { kind: 'info', ms: 5000 });
  }, true);
  function menuOff(el, why, title) {
    var s = !el ? null : el.tagName === 'SUMMARY' ? el : el.querySelector ? el.querySelector(':scope > summary') : null;
    if (!s) return;
    if (why) {
      s.setAttribute('aria-disabled', 'true'); s.setAttribute('data-ui-why', String(why)); s.title = String(why);
      s.parentNode.removeAttribute('open');
      return;
    }
    var was = s.getAttribute('data-ui-why');
    s.removeAttribute('aria-disabled'); s.removeAttribute('data-ui-why');
    if (title != null) s.title = title; else if (was && s.title === was) s.removeAttribute('title');
  }

  /* ポップオーバーを開いたら、画面の外にはみ出さないよう置き場所を直す(A-1: 右端の「…」の選択肢が画面の外に出ていた)。
     data-align の指定のまま置いてみて、はみ出す側だけ反対にそろえる。下にはみ出して上に余裕があれば上に開く。
     編集の形(details.pop > .vpop。2 カット の「無音 ▾」「時刻リスト ▾」など)にもかける。 */
  /* POP_SEL(開いているものだけの選択子)とは別の名前にする(同じ名前だと上書きされ、Esc で閉じているメニューの summary にもフォーカスが移って Space で開いてしまう) */
  var FIT_SEL = 'details.ui-pop, details.ui-menu, details.pop';
  function fitPop(d) {
    /* 画面が自分で作った中身(class が違う)も、data-ui-fit を付ければ同じく置き直す(スタジオ ① の選択の帯の「まとめて実行」.rk-autopop。
       帯が画面の下の方にあると、中身と「まとめて実行」のボタンが画面の下の外に出るため) */
    var body = d.querySelector(':scope > .ui-pop-body, :scope > .ui-menu-pop, :scope > .vpop, :scope > [data-ui-fit]'); if (!body) return;
    body.style.left = body.style.right = body.style.top = body.style.bottom = body.style.maxHeight = body.style.overflowY = '';
    var r = body.getBoundingClientRect(), vw = document.documentElement.clientWidth || window.innerWidth, vh = window.innerHeight, m = 8;
    if (r.right > vw - m) { body.style.left = 'auto'; body.style.right = '0'; r = body.getBoundingClientRect(); }
    if (r.left < m) { body.style.right = 'auto'; body.style.left = '0'; r = body.getBoundingClientRect(); }
    if (r.right > vw - m) { var p = d.getBoundingClientRect(); body.style.left = Math.round(m - p.left) + 'px'; body.style.right = 'auto'; }   /* どちらにそろえても入らない狭い画面: 画面の左端から */
    if (r.bottom > vh - m) {
      var top = d.getBoundingClientRect().top;
      if (top - r.height - 6 >= m) { body.style.top = 'auto'; body.style.bottom = 'calc(100% + 6px)'; }
      else { body.style.maxHeight = Math.max(120, vh - r.top - m) + 'px'; body.style.overflowY = 'auto'; }
    }
  }
  /* open が付いた直後(描く前)に直す。toggle イベントは後から届くので、1コマだけ画面の外に出て見えることがあった */
  if (window.MutationObserver) new MutationObserver(function (recs) {
    for (var i = 0; i < recs.length; i++) {
      var d = recs[i].target;
      if (d.open && d.matches && d.matches(FIT_SEL)) fitPop(d);
    }
  }).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['open'] });

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  var PATH_RE = /^\/(?:[a-z0-9][a-z0-9-]{0,31}\/)?$/;
  /* ---- 取り込まれたツールの場所 ---- */
  var tools = {
    /* 統合サーバーに取り込まれたツールの場所 {studio: '/studio/'}(/api/siblings の paths。無ければ各ツールのポートの直下) */
    paths: {},
    setPaths: function (p) {
      var out = {};
      if (p && typeof p === 'object') for (var k in p) if (Object.prototype.hasOwnProperty.call(p, k) && typeof p[k] === 'string' && PATH_RE.test(p[k])) out[k] = p[k];
      tools.paths = out;
      /* ツールの場所が分かったら、先に描いた appnav のリンクを描き直す(appnav は DOMContentLoaded で1回描くが、場所は /api/siblings・/api/status の答えで後から来る) */
      if (document.readyState !== 'loading') renderAppNav();
      if (typeof live !== 'undefined' && live && live.last) liveRender();   /* 録画の札の「開く」のリンクも(スタジオの場所を使う) */
    },
    base: function (id) { return tools.paths[id] || '/'; },
    /* 入口に取り込まれているか(入口が画面に合言葉 ytt-token を入れる)。取り込まれていれば入口は同じアドレスの / */
    mounted: function () { return !!document.querySelector('meta[name="ytt-token"]'); }
  };

  /* ---- 表示の書式 ---- 一覧で「いつのものか」をすぐ分かるように */
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  var fmt = {
    date: function (ms) {
      if (!ms) return '';
      var d = new Date(ms), now = new Date();
      return (d.getFullYear() !== now.getFullYear() ? d.getFullYear() + '/' : '') + (d.getMonth() + 1) + '/' + d.getDate() + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
    },
    ago: function (ms) {
      if (!ms) return '';
      var sec = (Date.now() - ms) / 1000;
      if (sec < 60) return 'たった今';
      if (sec < 3600) return Math.floor(sec / 60) + '分前';
      var d = new Date(ms), now = new Date();
      var days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
      if (days <= 0) return '今日 ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
      if (days === 1) return '昨日 ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
      if (days < 7) return days + '日前';
      return fmt.day(ms);
    },
    /* 日付だけ(date の時刻の前。年は今年でなければ付ける) */
    day: function (ms) { return ms ? fmt.date(ms).split(' ')[0] : ''; },
    /* 秒 → 1:23:45(1 時間未満は 23:45)。opt(省略なら四捨五入):
       floor = 切り捨て(タイムラインの目盛りなど)・tenths = 0.1 秒まで(0.1 秒で四捨五入して末尾に .4。スタジオの Studio.fmtTime と同じ)・
       noHours = 時を出さず分を 60 以上にも(83:45) */
    dur: function (sec, opt) {
      opt = opt || {};
      var t = Math.max(0, +sec || 0), d = Math.round(t * 10);
      var whole = opt.tenths ? Math.floor(d / 10) : opt.floor ? Math.floor(t) : Math.round(t);
      var h = opt.noHours ? 0 : Math.floor(whole / 3600), m = opt.noHours ? Math.floor(whole / 60) : Math.floor(whole % 3600 / 60), s2 = whole % 60;
      return (h ? h + ':' + pad2(m) : m) + ':' + pad2(s2) + (opt.tenths ? '.' + (d % 10) : '');
    }
  };

  /* ---- 入口の共通の API(api/ytt/…)---- 画面の場所からの相対パス(入口の画面 → /api/ytt/…、取り込んだツール → /studio/api/ytt/… など。
     どちらも入口が受け持つ)。合言葉はサーバーが </head> の直前に入れるので、このファイルの実行時ではなく送るときに読む */
  function token() { var m = document.querySelector('meta[name="ytt-token"]'); return m ? m.content : ''; }

  /* ---- http(notes:docs/design/reviews/code-review-simplify-2026-10-08.md の T3・B)---- JSON の API を呼ぶ 1 か所。合言葉を付けるのはここだけ。
     UIKit.http(url, opt) -> Promise<応答の JSON(JSON でなければ {})>(opt.raw なら成功のときは Response)。opt:
       method(既定: body があれば POST・無ければ GET)・body(JSON にして送る。Content-Type も付ける)・keepalive・
       timeout(ミリ秒。応答の見出しが届くまで)・signal(呼ぶ側の AbortSignal)・raw・
       token(省略 = 画面の meta ytt-token / 文字列 = その値 / false = 付けない)・needToken(合言葉が無ければ送らずに失敗 code 'no_token')・
       offline(つながらないときの文)・slow(時間切れの文)・fail(サーバーが message を返さなかったときの文。文字列か function(status))
     合言葉 X-YTT-Token は GET・HEAD 以外で、送り先が同じオリジンのときだけ付ける(ほかのサイトへ合言葉を出さない)。
     失敗はいつも Error で、形は 1 つ: message(画面に出す文)・code(サーバーの error | 'http' | 'network' | 'timeout' | 'abort' | 'no_token')・
       status(HTTP の番号。応答が無ければ 0)・body(応答の JSON。無い・JSON でなければ {})・data(body と同じもの)・
       reason(サーバーの message。無ければ '')・detail(知らせの「詳しく」に出す原文: 'HTTP 409' / 通信の例外の文) */
  var HTTP_OFFLINE = 'サーバーにつながりませんでした(start.bat の黒い画面が閉じていないか確かめてください)';
  var HTTP_SLOW = 'サーバーの応答が遅れています。少し待ってから、もう一度試してください';
  function httpFail(st) { return st >= 500 ? 'サーバーで問題が起きました。少し待ってから、もう一度試してください' : '要求を受け付けてもらえませんでした。画面を読み込み直してから、もう一度試してください'; }
  function httpCodeText(st) { return 'HTTP ' + st; }   /* ui-kit の中の呼び出しの失敗の文は HTTP 404 の形にする */
  function httpErr(message, code, status, j, detail) {
    var e = new Error(message), b = j && typeof j === 'object' ? j : {};
    e.code = code; e.status = status; e.body = b; e.data = b;
    e.reason = typeof b.message === 'string' ? b.message : ''; e.detail = detail || '';
    return e;
  }
  /* 入口を起動し直すと合言葉(X-YTT-Token)が変わり、開きっぱなしの画面の書き込みは 403 {"error":"token"} で断られる。
     待っても直らないので、「開き直す」の知らせを 1 回だけ出す(http が受けるので全部の画面に効く。http を通らない書き込みは UIKit.tokenStale() を呼ぶ) */
  var tokenStaleShown = false;
  function tokenStale() {
    if (tokenStaleShown) return;
    tokenStaleShown = true;
    toastFn('ホームが起動し直されました。この画面を開き直すと、また使えます', { kind: 'err', ms: 0, action: { label: '開き直す', fn: function () { location.reload(); } } });
  }
  function sameOrigin(url) { try { return new URL(url, location.href).origin === location.origin; } catch (e) { return false; } }
  function http(url, opt) {
    opt = opt || {};
    var method = String(opt.method || (opt.body === undefined ? 'GET' : 'POST')).toUpperCase();
    var tk = typeof opt.token === 'string' ? opt.token : opt.token === false ? '' : token();
    if (opt.needToken && !tk) return Promise.reject(httpErr('ホーム(start.bat)から開いたときだけ使えます', 'no_token', 0, null, ''));
    var init = { method: method, cache: 'no-store', credentials: 'same-origin', headers: {} };
    if (opt.keepalive) init.keepalive = true;
    if (opt.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opt.body); }
    if (tk && method !== 'GET' && method !== 'HEAD' && sameOrigin(url)) init.headers['X-YTT-Token'] = tk;
    var ctl = null, timer = 0, timedOut = false, outer = opt.signal || null;
    if (+opt.timeout > 0) {   /* 時間切れと呼ぶ側の取り消しを 1 つの signal に(どちらで止まったかは timedOut で分ける) */
      ctl = new AbortController();
      if (outer) { if (outer.aborted) ctl.abort(); else outer.addEventListener('abort', function () { ctl.abort(); }); }
      timer = setTimeout(function () { timedOut = true; ctl.abort(); }, +opt.timeout);
      init.signal = ctl.signal;
    } else if (outer) init.signal = outer;
    function noReply(e) {
      var detail = String((e && e.message) || e || '');
      if (timedOut) return httpErr(opt.slow || HTTP_SLOW, 'timeout', 0, null, detail);
      if (init.signal && init.signal.aborted) return httpErr('取り消しました', 'abort', 0, null, detail);
      return httpErr(opt.offline || HTTP_OFFLINE, 'network', 0, null, detail);
    }
    return fetch(url, init).then(function (r) {
      clearTimeout(timer);
      if (opt.raw && r.ok) return r;
      return r.json().then(null, function (e) { if (init.signal && init.signal.aborted) throw noReply(e); return null; }).then(function (j) {
        if (r.ok) return j == null ? {} : j;
        if (r.status === 403 && j && j.error === 'token') tokenStale();
        var fb = typeof opt.fail === 'function' ? opt.fail(r.status) : typeof opt.fail === 'string' ? opt.fail : httpFail(r.status);
        throw httpErr((j && j.message) ? String(j.message) : fb, (j && j.error) || 'http', r.status, j, 'HTTP ' + r.status);
      });
    }, function (e) { clearTimeout(timer); throw noReply(e); });
  }
  /* 入口(ホーム)の API の場所。path は入口の直下からの相対('api/flow/runs'・'api/ytt/prefs'・'live/api/info'。先頭の / は外す)。
     取り込んだツールの画面(/studio/・/transcribe/)からもホームの画面(/)からも、画面の場所の 1 つ上 = 入口の直下を指す(絶対パスを書かない) */
  function homeUrl(path) { return new URL('../' + String(path == null ? '' : path).replace(/^\/+/, ''), location.href).href; }
  function homeApi(path, opt) { return http(homeUrl(path), opt); }
  function yttPost(name, obj, keepalive) {
    /* 失敗の status(liveBadge が 404 と一時的な失敗を分ける) */
    return http('api/ytt/' + name, { method: 'POST', body: obj, keepalive: keepalive, needToken: true, fail: httpCodeText });
  }

  /* ---- 画面のエラーを入口のログへ(段階7-0)---- 同じエラーは1回、1回の表示で20件まで(画面の不具合でログを埋めない。サーバー側にも上限) */
  var sentN = 0, seen = {};
  function clip(v, n) { v = v == null ? '' : String(v); return v.length > n ? v.slice(0, n) : v; }
  function reportErr(e) { report(e && e.message ? e.message : String(e), { stack: e && e.stack }, 'error'); }   /* 購読側の関数の例外など */
  function report(message, info, kind) {
    try {
      info = info || {};
      message = clip(message, 500);
      if (!message || !token()) return false;
      var key = (kind || 'report') + '|' + message + '|' + (info.source || '') + '|' + (info.line || 0);
      if (seen[key] || sentN >= 20) return false;
      seen[key] = 1; sentN++;
      yttPost('client-log', { kind: kind || 'report', message: message, source: clip(info.source, 300), line: +info.line || 0, col: +info.col || 0,
        stack: clip(info.stack, 1500), page: clip(location.pathname, 200) }, true).catch(function () { /* 送れなくても画面は止めない */ });
      return true;
    } catch (e) { return false; }
  }
  window.addEventListener('error', function (e) {
    if (!e || !e.message) return;
    if (!e.filename && /^Script error\.?$/.test(e.message)) return;   // 別のサイトのスクリプト(YouTube のプレイヤー)の、中身の見えないエラー
    report(e.message, { source: e.filename, line: e.lineno, col: e.colno, stack: e.error && e.error.stack }, 'error');
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e ? e.reason : null;
    report(r && r.message ? r.message : String(r), { stack: r && r.stack }, 'rejection');
  });

  /* ---- 画面を離れた・戻った(段階7-2)----
     タブの切り替え(visibilitychange)だけだと、窓を並べて使うときに「隣の窓をクリックした」を取りこぼす(画面は見えたまま)。
     別の窓へ移った(blur)・閉じる直前(pagehide)も「離れた」にする。ただし埋め込みの YouTube(iframe)をクリックしても窓の blur が来るので、
     少し待って、フォーカスがまだこの画面の中(document.hasFocus() か、フォーカスが iframe)なら離れたことにしない */
  var leaveFns = [], returnFns = [], away = false, awayBy = '', blurTimer = null;
  function fire(list, reason) {
    for (var i = 0; i < list.length; i++) { try { list[i](reason); } catch (e) { reportErr(e); } }
  }
  function focusInside() {
    try { if (document.hasFocus()) return true; } catch (e) { /* 古いブラウザ */ }
    var a = document.activeElement;
    return !!(a && a.tagName === 'IFRAME');
  }
  function leave(reason) {
    /* 離れたのは1回だけ知らせる。ただし「隣の窓へ('blur')」のあとにタブを切り替えた・最小化した('hidden')ときは、もう一度知らせる
       ('blur' では再生の停止・重い処理をしない決まりなので、見えなくなった時点でそれをさせる)。閉じる直前('pagehide')はいつでも知らせる */
    if (away && !(reason === 'pagehide' || (reason === 'hidden' && awayBy === 'blur'))) return;
    away = true;
    awayBy = reason;
    fire(leaveFns, reason);
  }
  function back(reason) {
    if (!away) return;
    away = false;
    fire(returnFns, reason);
  }
  document.addEventListener('visibilitychange', function () { if (document.hidden) leave('hidden'); else back('visible'); });
  window.addEventListener('pagehide', function () { leave('pagehide'); });
  window.addEventListener('pageshow', function (e) { if (e && e.persisted) back('pageshow'); });
  window.addEventListener('blur', function () {
    clearTimeout(blurTimer);
    blurTimer = setTimeout(function () { if (!document.hidden && !focusInside()) leave('blur'); }, 150);
  });
  window.addEventListener('focus', function () { clearTimeout(blurTimer); if (!document.hidden) back('focus'); });
  var life = {
    onLeave: function (fn) { if (typeof fn === 'function') leaveFns.push(fn); },
    onReturn: function (fn) { if (typeof fn === 'function') returnFns.push(fn); },
    isAway: function () { return away; }
  };

  /* ---- 窓(Edge のアプリモード)で開いているときのリンク(段階7-3)----
     アプリモードの窓の中で「新しいタブで開く」と、タブのある普通の窓(専用のプロファイル)になってしまう。入口に頼んで開き直す:
     このパソコンの画面(localhost)→ 同じ形の窓、外のサイト(YouTube など)→ いつものブラウザ(ログインしている方)。
     アプリモードかどうかは display-mode(Edge のアプリの窓は standalone)で見る。ブラウザのタブで開いているときは何もしない */
  function isApp() { try { return !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches); } catch (e) { return false; } }
  function isLocal(u) { return u.hostname === location.hostname || u.hostname === 'localhost' || u.hostname === '127.0.0.1'; }
  function openVia(href) {
    var u;
    try { u = new URL(href, location.href); } catch (e) { return Promise.reject(e); }
    return yttPost(isLocal(u) ? 'open-window' : 'open-external', { url: u.href });
  }
  function onLink(e) {
    if (e.defaultPrevented || !isApp() || !token()) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a || a.hasAttribute('download')) return;
    var mod = e.ctrlKey || e.shiftKey || e.metaKey || e.button === 1;
    if (a.target !== '_blank' && !mod) return;
    var u;
    try { u = new URL(a.href, location.href); } catch (x) { return; }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return;
    e.preventDefault();
    openVia(u.href).catch(function (err) {
      report('窓で開けませんでした: ' + (err && err.message), { source: u.origin + u.pathname }, 'report');
      window.open(u.href, '_blank', 'noopener');   // 入口に頼めないときは、ブラウザに任せる(タブのある窓になる)
    });
  }
  document.addEventListener('click', function (e) { if (e.button === 0) onLink(e); });
  document.addEventListener('auxclick', function (e) { if (e.button === 1) onLink(e); });
  var win = { isApp: isApp, open: openVia };

  /* ---- 入口へ戻る ---- bat で開いた入口の窓があるのに、ツールの窓の「入口」で同じ窓を入口へ移すと、入口が二つになってしまう。
     入口の画面(portal.js が UIKit.portal.listen())が BroadcastChannel で答えたら、移らずに入口(サーバー)に「入口の窓を前に出して」と頼む
     (api/ytt/focus-portal。Windows の窓を題名で探す)。前に出せなかったら知らせるだけ(ツールの画面はそのまま)。
     答えが無ければ、その場で入口へ移る。同じパソコン・同じブラウザのプロファイルの中だけで届く(外には出ない) */
  var PORTAL_CH = 'ytt-portal';
  function portalOpen(ms) {
    return new Promise(function (resolve) {
      if (!window.BroadcastChannel) return resolve(false);
      var ch, done = false, id = String(Math.random()).slice(2);
      function end(v) { if (done) return; done = true; try { ch.close(); } catch (e) { /* 閉じ済み */ } resolve(v); }
      try { ch = new BroadcastChannel(PORTAL_CH); } catch (e) { return resolve(false); }
      ch.onmessage = function (e) { var d = e.data || {}; if (d.type === 'here' && d.re === id) end(true); };
      ch.postMessage({ type: 'ping', id: id });
      setTimeout(function () { end(false); }, ms || 400);
    });
  }
  function note(message) { toastFn(message, { kind: 'info', ms: 5000 }); }   /* UIKit.toast(下で定義)を使う(ツールごとの知らせの部品に頼らない) */
  var portal = {
    /* 入口の画面が呼ぶ: ほかの窓の「入口」リンクに「ここにある」と答える */
    listen: function () {
      if (!window.BroadcastChannel) return;
      try {
        var ch = new BroadcastChannel(PORTAL_CH);
        ch.onmessage = function (e) { var d = e.data || {}; if (d.type === 'ping' && d.id) ch.postMessage({ type: 'here', re: d.id }); };
      } catch (e) { /* 使えないブラウザ: 答えない(リンクは今までどおり移る) */ }
    },
    isOpen: portalOpen,
    /* 入口へ: 開いていれば前に出す(-> 'focused' | 'elsewhere')、無ければ href へ移る(-> 'moved') */
    go: function (href) {
      return portalOpen(400).then(function (open) {
        if (!open || !token()) { location.href = href || '/'; return 'moved'; }
        return yttPost('focus-portal', {}).then(function (r) { return r && r.focused ? 'focused' : 'elsewhere'; }, function () { return 'elsewhere'; })
          .then(function (how) {
            if (how === 'elsewhere') note('ホームはほかの窓(タブ)で開いています。タスクバーから切り替えてください');
            return how;
          });
      });
    }
  };
  document.addEventListener('click', function (e) {
    if (e.button !== 0 || e.defaultPrevented || e.ctrlKey || e.shiftKey || e.metaKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest('a[data-ui-portal]') : null;
    if (!a || !token()) return;
    e.preventDefault();
    portal.go(a.href);
  });

  /* ---- 配信者の名前(字幕の色)の欄 ---- <input data-ui-streamer> に、名前の候補(datalist)・色の見本・合う人の表示を付ける。
     名前 → メンバーカラーの照らし合わせは入口(api/ytt/streamer-colors → ytt/colors.py)の1か所。欄の値は名前のまま送り、
     使う側(cut2resolve・まとめて実行)も同じ規則で照らし合わせる(画面に規則を書かない)。入口の外では使えないと知らせる。
     値を画面から入れ直したら UIKit.streamer.set(input, 名前)。合う人が決まるたびに input に 'ui-streamer' イベント(detail: 人 | null) */
  var streamerList = null;
  function streamerItems() {
    if (!streamerList) streamerList = yttPost('streamer-colors', { q: '', all: true }).then(function (j) { return j.items || []; }, function () { streamerList = null; return []; });
    return streamerList;
  }
  function attachStreamer(input) {
    if (!input || input.__uiStreamer) return;
    var id = 'ui-streamer-list';
    if (!document.getElementById(id)) {
      var dl = document.createElement('datalist');
      dl.id = id;
      document.body.appendChild(dl);
      if (token()) streamerItems().then(function (items) {
        dl.innerHTML = items.map(function (e) { return '<option value="' + esc(e.name) + '">' + esc((e.group || '') + ' ' + e.hex) + '</option>'; }).join('');
      });
    }
    input.setAttribute('list', id);
    input.setAttribute('autocomplete', 'off');
    input.maxLength = 60;
    var sw = document.createElement('span'), hint = document.createElement('small');
    sw.className = 'ui-streamer-sw'; sw.hidden = true; sw.setAttribute('aria-hidden', 'true');
    hint.className = 'ui-streamer-hint'; hint.setAttribute('aria-live', 'polite');
    input.insertAdjacentElement('afterend', sw);
    sw.insertAdjacentElement('afterend', hint);
    var timer = 0, seq = 0, last = null;
    function tell(who) { try { input.dispatchEvent(new CustomEvent('ui-streamer', { detail: who })); } catch (e) { /* 古いブラウザ */ } }
    /* 同じ名前ではもう一度照らし合わせない(force を除く)。欄から離れた(change)ときに説明の文が変わると、隣のボタンが押している途中で
       ずれてクリックが成立しなくなる。同じ理由で、照らし合わせの途中は説明の文を変えない */
    function show(force) {
      var q = input.value.trim();
      if (!force && q === last) return;
      last = q;
      var my = ++seq;
      input.removeAttribute('data-color'); sw.hidden = true; sw.style.background = '';
      if (!q) { hint.textContent = '空なら黒い文字'; tell(null); return; }
      if (!token()) { hint.textContent = 'ホームから開くと使えます'; tell(null); return; }
      yttPost('streamer-colors', { q: q }).then(function (j) {
        if (my !== seq) return;
        if (j.match) {
          sw.hidden = false; sw.style.background = j.match.hex;
          hint.textContent = j.match.name + ' の色 ' + j.match.hex + '(文字をこの色に)';
          input.setAttribute('data-color', j.match.hex);
          tell(j.match);
        } else {
          hint.textContent = j.candidates && j.candidates.length ? '1人に決まりません。候補: ' + j.candidates.slice(0, 5).map(function (e) { return e.name; }).join('・')
            : '見つかりません(ホロカラーのマイカラーに足すと使えます)';
          tell(null);
        }
      }, function () { if (my === seq) { hint.textContent = '色の一覧を読めません'; tell(null); } });
    }
    input.__uiStreamer = show;
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { show(false); }, 200); });
    input.addEventListener('change', function () { clearTimeout(timer); show(false); });
    show(true);
  }
  /* 配信者の名前を自動で入れる(覚えた名前 → チャンネル名から。決める順は入口の api/ytt/streamer-guess の1か所)・
     札「自動(チャンネル名から)」「前回」・手で直したら文書・配信・チャンネルに覚える(空 = 「色なし」を覚える)・見つからない名前は始める前に聞く */
  function streamerBadge(input, text) {
    var b = input.__badge;
    if (!b) {
      b = document.createElement('span'); b.className = 'pill info ui-streamer-badge'; b.hidden = true;
      var after = input.nextElementSibling && input.nextElementSibling.nextElementSibling ? input.nextElementSibling.nextElementSibling : input;
      after.insertAdjacentElement('afterend', b); input.__badge = b;
    }
    b.textContent = text || ''; b.hidden = !text;
  }
  function streamerRemember(ctx, name) {
    if (!ctx || !prefs.available()) return;
    var noop = function () {};
    if (ctx.docId) prefs.remember('docs', ctx.docId, name).catch(noop);
    if (ctx.videoId) prefs.remember('videos', ctx.videoId, name).catch(noop);
    if (ctx.channel) prefs.remember('channels', ctx.channel, name).catch(noop);
  }
  var streamer = {
    attach: attachStreamer,
    set: function (input, value) { if (!input) return; input.value = value || ''; attachStreamer(input); input.__uiStreamer(true); if (input.__badge) streamerBadge(input, ''); },
    value: function (input) { return input ? input.value.trim() : ''; },
    /* ctx = {docId?, videoId?, channel?}(この欄が何の配信者か)。手で直していなければ、覚えた名前か チャンネル名から入れて札を付ける */
    autoFill: function (input, ctx) {
      if (!input) return Promise.resolve(null);
      attachStreamer(input);
      var key = JSON.stringify(ctx || {});
      if (input.__ctxKey === key && input.__touched) return Promise.resolve(null);   // 同じ相手の欄を手で直したあとは入れ直さない
      input.__ctx = ctx || {}; input.__ctxKey = key; input.__touched = false;
      if (!input.__autoBound) {
        input.__autoBound = true;
        /* 打ち始めたら、あとから届いた自動の名前で上書きしない(問い合わせの途中に打つと、打った名前が消えていた) */
        input.addEventListener('input', function () { input.__touched = true; });
        input.addEventListener('change', function () { input.__touched = true; streamerBadge(input, ''); streamerRemember(input.__ctx, input.value.trim()); });
      }
      if (!token()) return Promise.resolve(null);
      var my = input.__autoSeq = (input.__autoSeq || 0) + 1;
      return yttPost('streamer-guess', input.__ctx).then(function (j) {
        if (my !== input.__autoSeq || input.__touched) return j;
        input.value = j.name || ''; input.__uiStreamer(true);
        streamerBadge(input, j.name ? (j.source === 'auto' ? '自動(チャンネル名から)' : '前回') : (j.source ? '前回: 色なし' : ''));
        return j;
      }, function () { return null; });
    },
    /* 始める前: 欄の名前がメンバーに見つからなければ「色なしで進める」か聞く(S-20)。-> Promise<名前 | ''(色なし)| null(やめる)> */
    check: function (input) {
      var v = input ? input.value.trim() : '';
      if (!v || !token()) return Promise.resolve(v);
      /* 欄の data-color は照らし合わせの途中(打った直後・描き直した直後)に消えているので、ここで照らし合わせ直す */
      return yttPost('streamer-colors', { q: v }).then(function (j) {
        if (j.match) return v;
        return dialogConfirm({ title: '配信者がメンバーに見つかりません', ok: '色なしで進める',
          body: '「' + v + '」は色の一覧にありません。色なし(黒い文字)で進めますか?(ホロカラーのマイカラーに足すと、その色にできます)' })
          .then(function (ok) { return ok ? '' : null; });
      }, function () { return v; });   // 照らし合わせられないときは、サーバーが始める前に断る
    }
  };
  document.addEventListener('DOMContentLoaded', function () {
    var list = document.querySelectorAll('input[data-ui-streamer]');
    for (var i = 0; i < list.length; i++) attachStreamer(list[i]);
  });

  /* ==== 共通の部品。使い方は README.md の「v6」 ==== */

  /* ---- appnav(ホーム/案件/確かめる/設定の切り替え。ヘッダーの左) ---- <nav data-ui-appnav="portal|cases|check|settings"> に中身を作る。
     どの画面も入口の直下(/・/cases・/check・/settings)= 行き先は入口の直下からの相対(homeUrl。絶対パスを書かない) */
  var APPNAV_ITEMS = [{ id: 'portal', label: 'ホーム' }, { id: 'cases', label: '案件' }, { id: 'check', label: '確かめる' }, { id: 'settings', label: '設定' }];
  var appnavVersion = '';
  function appnavHref(id) { return id === 'portal' ? homeUrl('') : homeUrl(id); }
  function renderAppNav() {
    var navs = document.querySelectorAll('[data-ui-appnav]');
    for (var n = 0; n < navs.length; n++) {
      var nav = navs[n], current = nav.getAttribute('data-ui-appnav') || '', html = '';
      for (var i = 0; i < APPNAV_ITEMS.length; i++) {
        var it = APPNAV_ITEMS[i];
        html += '<a href="' + esc(appnavHref(it.id)) + '" data-ui-appnav-item="' + it.id + '"' +
          (it.id === current ? ' aria-current="page"' : '') + (it.id === 'portal' ? ' data-ui-portal' : '') + '>' + esc(it.label) + '</a>';
      }
      nav.innerHTML = html;
      if (appnavVersion) { var cur = nav.querySelector('[aria-current="page"]'); if (cur) cur.title = appnavVersion; }   /* 描き直しても版の title を保つ */
    }
  }
  document.addEventListener('DOMContentLoaded', renderAppNav);

  /* ---- すべて終了(10-24 ホームの見直しの 3): 入口の画面(上の帯に data-ui-appnav がある = ホーム・案件・確かめる・設定)の右端に赤い枠のボタン。
     押すと確かめの文 → POST /api/shutdown(入口がこの入口から起こしたツールを止めて終わる)→ 応答が無くなるまで待って、閉じてよいと出す。
     ホームから開いていない(合言葉が無い)画面には出さない */
  function quitCover(title, text) {
    var c = document.getElementById('uiQuitCover');
    if (!c) {
      c = document.createElement('div'); c.id = 'uiQuitCover'; c.className = 'ui-quit-cover'; c.setAttribute('role', 'status');
      c.innerHTML = '<div class="card raised ui-quit-card"><h2></h2><p class="hint"></p></div>';
      document.body.appendChild(c);
    }
    c.querySelector('h2').textContent = title; c.querySelector('p').textContent = text;
  }
  function quitWait(n, notice) {
    function alive() {
      if (n < 40) setTimeout(function () { quitWait(n + 1, notice); }, 700);
      else quitCover('終了に時間がかかっています', '黒い画面が残っていれば、その画面を閉じてください。' + notice);
    }
    http('/api/ping', { timeout: 2000 }).then(alive, function (e) {
      if (e && e.status) { alive(); return; }
      quitCover('すべて終了しました', 'この画面(タブ・窓)は閉じてかまいません。もう一度使うときは start.bat をダブルクリックしてください。' + notice);
    });
  }
  function quitRun(btn) {
    dialogConfirm({ title: 'すべて終了しますか', ok: 'すべて終了', danger: true,
                    body: 'このホームから起動したツールを止めて、ホームも終わります(録画中なら録画の部品は残し、次に開いたときに続けます)。別の黒い画面で起動したツールは止めません。' })
      .then(function (ok) {
        if (!ok) return;
        btn.disabled = true;
        quitCover('終了しています…', '起動したツールを止めています。少し待ってください。');
        http('/api/shutdown', { body: {} }).then(function (r) {
          quitWait(0, r && r.notice ? ' ' + r.notice : '');
        }, function (e) {
          btn.disabled = false;
          var c = document.getElementById('uiQuitCover'); if (c) c.parentNode.removeChild(c);
          toastFn('終了できませんでした: ' + ((e && e.message) || '') + '(もう一度「すべて終了」を押すか、黒い画面を閉じてください)', { kind: 'err', ms: 0 });
        });
      });
  }
  function addQuit() {
    if (!token()) return;
    var heads = document.querySelectorAll('.ui-header');
    for (var i = 0; i < heads.length; i++) {
      var h = heads[i], acts = h.querySelector('.ui-header-actions');
      if (!h.querySelector('[data-ui-appnav]') || !acts || h.querySelector('.ui-quit')) continue;
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'btn danger small ui-quit'; b.id = 'uiQuit';
      b.title = 'このホームから起動したツールを止めて、ホームも終わります(押すと確かめます)';
      b.innerHTML = icon('power', { size: 14 }) + 'すべて終了';
      b.addEventListener('click', function (e) { quitRun(e.currentTarget); });
      acts.appendChild(b);
    }
  }
  document.addEventListener('DOMContentLoaded', addQuit);
  var appnav = {
    /* 今の場所の項目の title に版を出す */
    setVersion: function (text) {
      appnavVersion = String(text || '');
      var navs = document.querySelectorAll('[data-ui-appnav]');
      for (var n = 0; n < navs.length; n++) { var cur = navs[n].querySelector('[aria-current="page"]'); if (cur) cur.title = text; }
    }
  };

  /* ---- drawer(右から出る引き出し。設定・書き出し・パックの詳しい設定など) ----
     UIKit.drawer.open(el, {modal:true|false, opener}) / close(el) / isOpen(el)。
     modal: 裏に幕・裏を inert(body の直接の子。引き出し自身・幕・トースト・キーの帯は除く)にしてフォーカスを閉じ込める(inert が Tab を外へ出さない)。
     docked(modal:false): 幕なし・裏も操作できる */
  function drawerKeepEls(el, scrim) {
    var keep = [el], toastEl = document.getElementById('toast'), kbEl = document.querySelector('.ui-keybar');
    if (scrim) keep.push(scrim);
    if (toastEl) keep.push(toastEl);
    if (kbEl) keep.push(kbEl);
    return keep;
  }
  function drawerInert(keep, on) {
    /* 引き出しから body までの道すじの各段で、道すじ以外の兄弟を inert にする(引き出しが body の直接の子でなくても、裏の全部を止める)。
       保つ要素(幕・トースト・キーの帯)を含む兄弟は inert にしない。<dialog> も inert にしない(showModal で開く確認などが操作できなくなるため。
       閉じた dialog は表示されず、開いた modal の dialog は showModal が裏(引き出しを含む)を止める) */
    var body = document.body; if (!body) return;
    var node = keep[0];
    while (node && node !== body && node.parentNode) {
      var sibs = node.parentNode.children;
      for (var i = 0; i < sibs.length; i++) {
        var k = sibs[i], keepThis = k === node;
        for (var j = 1; !keepThis && j < keep.length; j++) if (keep[j] && k.contains(keep[j])) keepThis = true;
        if (!keepThis && k.tagName !== 'DIALOG') k.inert = on;
      }
      node = node.parentNode;
    }
  }
  function drawerFocusables(el) {
    /* summary も数え、閉じた details の中身や隠れているものは除く(A-31) */
    var all = el.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])');
    var out = [];
    for (var i = 0; i < all.length; i++) { var f = all[i]; if (f.checkVisibility ? f.checkVisibility({ visibilityProperty: true, contentVisibilityAuto: true }) : f.offsetParent !== null) out.push(f); }
    return out;
  }
  function fireDrawerEvent(el, open) { try { document.dispatchEvent(new CustomEvent('ui-drawer', { detail: { open: open, el: el } })); } catch (e) { /* 古いブラウザ */ } }
  var drawer = {
    isOpen: function (el) { return !!(el && !el.hidden); },
    open: function (el, opt) {
      if (!el || !el.hidden) return;
      opt = opt || {};
      var modal = opt.modal !== false;
      el.__uiOpener = opt.opener || document.activeElement;
      el.__uiModal = modal;
      el.hidden = false;
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-hidden', 'false');
      if (modal) el.setAttribute('aria-modal', 'true'); else el.removeAttribute('aria-modal');
      if (modal) {
        var scrim = document.createElement('div');
        scrim.className = 'ui-drawer-scrim';
        scrim.addEventListener('click', function () { drawer.close(el); });
        (el.parentNode || document.body).insertBefore(scrim, el);
        el.__uiScrim = scrim;
        drawerInert(drawerKeepEls(el, scrim), true);
      }
      requestAnimationFrame(function () { el.classList.add('in'); });
      if (opt.focus !== false) setTimeout(function () {   /* focus:false: 自動で開くとき(スタジオの書き出しの欄)はフォーカスを動かさない */
        if (el.contains(document.activeElement)) return;
        var list = drawerFocusables(el);
        if (list.length && list[0].focus) list[0].focus({ preventScroll: true });
      }, 30);
      fireDrawerEvent(el, true);
    },
    close: function (el) {
      if (!el || el.hidden) return;
      el.classList.remove('in'); el.hidden = true; el.setAttribute('aria-hidden', 'true');
      if (el.__uiScrim) {
        drawerInert(drawerKeepEls(el, el.__uiScrim), false);
        if (el.__uiScrim.parentNode) el.__uiScrim.parentNode.removeChild(el.__uiScrim);
        el.__uiScrim = null;
      }
      var opener = el.__uiOpener; el.__uiOpener = null;
      if (opener && opener.isConnected && opener.focus) opener.focus({ preventScroll: true });
      fireDrawerEvent(el, false);
    }
  };
  /* modal の引き出しの中で Tab を回す(最後 → 先頭、Shift+Tab で先頭 → 最後)。inert だけではブラウザのアドレス欄へ抜けるため */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab' || document.querySelector('dialog[open]')) return;
    var open = document.querySelectorAll('.ui-drawer:not([hidden])'), el = null;
    for (var i = open.length - 1; i >= 0; i--) if (open[i].__uiModal) { el = open[i]; break; }
    if (!el) return;
    var list = [], all = drawerFocusables(el);
    for (var j = 0; j < all.length; j++) if (all[j].offsetParent !== null || all[j] === document.activeElement) list.push(all[j]);
    if (!list.length) return;
    var first = list[0], last = list[list.length - 1], a = document.activeElement;
    if (!el.contains(a)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && a === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && a === last) { e.preventDefault(); first.focus(); }
  });
  /* Esc: 開いている引き出しのうち、modal か(フォーカスが中にある docked)を閉じる(いちばん後ろ = 手前のものから)。
     引き出しの上に確認ダイアログ(<dialog>)が開いているときは、ダイアログだけが Esc を受け取る(ブラウザの標準の動きに任せる) */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (document.querySelector('dialog[open]')) return;
    if (document.querySelector('details.ui-menu[open], details.ui-pop[open]')) return;   /* 開いているメニューがあれば、その Esc はメニューだけを閉じる(引き出しは閉じない。ホームの見直し N2) */
    var open = document.querySelectorAll('.ui-drawer:not([hidden])');
    for (var i = open.length - 1; i >= 0; i--) {
      var el = open[i];
      if (el.__uiModal || el.contains(document.activeElement)) { e.preventDefault(); drawer.close(el); break; }
    }
  });

  /* ---- dialog(確認・警告) ---- <dialog class="ui-dialog"> + showModal(フォーカスの閉じ込め・Esc はブラウザに任せる)。本文は textContent で入れる(XSS を作らない) */
  function buildDialogShell() {
    var dlg = document.createElement('dialog'); dlg.className = 'ui-dialog';
    var head = document.createElement('div'); head.className = 'ui-dlg-head';
    var h2 = document.createElement('h2'); head.appendChild(h2);
    var body = document.createElement('div'); body.className = 'ui-dlg-body';
    var actions = document.createElement('div'); actions.className = 'ui-dlg-actions';
    dlg.appendChild(head); dlg.appendChild(body); dlg.appendChild(actions);
    (document.body || document.documentElement).appendChild(dlg);
    return { dlg: dlg, h2: h2, body: body, actions: actions };
  }
  function dialogBtn(cls, text) { var b = document.createElement('button'); b.type = 'button'; b.className = cls; b.textContent = text; return b; }
  /* 確認とお知らせで共通: buttons = [[ボタン, 押したときの値]] を並べて showModal。ボタン以外(Esc)で閉じたら closed の値。
     閉じたら要素を消して、開く前のフォーカスへ戻す */
  function dialogOpen(opts, defTitle, buttons, focusBtn, closed) {
    return new Promise(function (resolve) {
      var parts = buildDialogShell(), opener = document.activeElement, done = false;
      parts.h2.textContent = opts.title || defTitle;
      parts.body.textContent = opts.body || '';
      function finish(v) { if (done) return; done = true; resolve(v); parts.dlg.close(); }
      buttons.forEach(function (b) { parts.actions.appendChild(b[0]); b[0].addEventListener('click', function () { finish(b[1]); }); });
      parts.dlg.addEventListener('close', function () {
        if (!done) { done = true; resolve(closed); }
        if (parts.dlg.parentNode) parts.dlg.parentNode.removeChild(parts.dlg);
        if (opener && opener.isConnected && opener.focus) opener.focus({ preventScroll: true });
      });
      parts.dlg.showModal();
      focusBtn.focus({ preventScroll: true });
    });
  }
  function dialogConfirm(opts) {
    opts = opts || {};
    var cancelBtn = dialogBtn('btn ghost', opts.cancel || 'キャンセル'), okBtn = dialogBtn('btn ' + (opts.danger ? 'danger solid' : 'primary'), opts.ok || 'OK');
    /* 消す・戻せない操作(danger)は、既定のフォーカスを安全な方(キャンセル)に */
    return dialogOpen(opts, '確認', [[cancelBtn, false], [okBtn, true]], opts.danger ? cancelBtn : okBtn, false);
  }
  function dialogAlert(opts) {
    opts = opts || {};
    var okBtn = dialogBtn('btn primary', opts.ok || 'OK');
    return dialogOpen(opts, 'お知らせ', [[okBtn, undefined]], okBtn, undefined);
  }
  /* 3 択以上の確認(例: パックの上書き [作り直す][別の場所][やめる])。opts.buttons = [{label, value, kind: 'primary'|'danger'|'ghost'|''}, …]。
     戻り値は押したボタンの value。Esc・背景は opts.cancel(既定 null)。danger のボタンがあれば既定のフォーカスは最初の ghost(安全な方)、無ければ最初の primary */
  function dialogChoose(opts) {
    opts = opts || {};
    var defs = (opts.buttons || []).filter(function (b) { return b && b.label; });
    if (!defs.length) return dialogAlert(opts).then(function () { return opts.cancel === undefined ? null : opts.cancel; });
    var btns = defs.map(function (b) { var kind = b.kind === 'primary' ? 'primary' : b.kind === 'danger' ? 'danger solid' : b.kind === 'ghost' ? 'ghost' : ''; return [dialogBtn('btn ' + kind, b.label), b.value]; });
    var hasDanger = defs.some(function (b) { return b.kind === 'danger'; });
    var first = null;
    for (var i = 0; i < defs.length; i++) { if ((hasDanger && defs[i].kind === 'ghost') || (!hasDanger && defs[i].kind === 'primary')) { first = btns[i][0]; break; } }
    return dialogOpen(opts, '確認', btns, first || btns[0][0], opts.cancel === undefined ? null : opts.cancel);
  }
  var dialogApi = { confirm: dialogConfirm, alert: dialogAlert, choose: dialogChoose };

  /* ---- toast(通知。重ねて最大2つ) ---- <div class="ui-toasts" id="toast" aria-live="polite">。既存の単発の #toast(class=toast)があれば入れ物として作り直す */
  var toastBox = null;
  /* 重ねるのは 2 つまで(積み上がると画面の下の操作(編集のパックの「中止」など)を隠すため)。あふれたら古いものから閉じる。
     消えない知らせ(ms: 0)・ボタンのある知らせ(data-ui-keep)は後回しにして、時間で消える知らせから閉じる(失敗の [もう一度] を、ただの案内で押し流さない)。
     残す知らせばかりのときも、失敗(.err)は最後まで残す。ボタンの無い失敗(時間で消える err)も、失敗でない知らせより先には閉じない。
     閉じる順 = 失敗でない時間で消える知らせ → 失敗でない残す知らせ → 古いもの */
  var TOAST_MAX = 2;
  function toastPick(box, ok) {
    for (var i = 0; i < box.children.length; i++) if (ok(box.children[i])) return box.children[i];
    return null;
  }
  function toastMakeRoom(box) {
    while (box.children.length >= TOAST_MAX) {
      var drop = toastPick(box, function (t) { return !t.hasAttribute('data-ui-keep') && !t.classList.contains('err'); }) ||
                 toastPick(box, function (t) { return !t.classList.contains('err'); }) || box.firstChild;
      box.removeChild(drop);   // 時間で消える知らせのタイマーは、外したあとに呼ばれても何もしない(remove は parentNode を見る)
    }
  }
  function ensureToastBox() {
    if (toastBox && toastBox.isConnected) return toastBox;
    var el = document.getElementById('toast');
    if (el) { el.innerHTML = ''; el.hidden = false; el.removeAttribute('role'); }
    else { el = document.createElement('div'); el.id = 'toast'; (document.body || document.documentElement).appendChild(el); }
    el.className = 'ui-toasts';
    el.setAttribute('aria-live', 'polite');
    toastBox = el;
    return el;
  }
  /* ms: 0 = 閉じるまで出す。action: {label, fn} = ボタン1つ(押すと閉じてから fn)。閉じるボタン(×)はいつも。-> {close, el} */
  function toastFn(message, opt) {
    opt = opt || {};
    var kind = opt.kind || '', isErr = kind === 'err';
    var ms = opt.ms === 0 ? 0 : (+opt.ms > 0 ? +opt.ms : (isErr ? 8000 : 2500));
    var box = ensureToastBox();
    toastMakeRoom(box);
    var item = document.createElement('div');
    item.className = 'ui-toast' + (kind ? ' ' + kind : '');
    item.setAttribute('role', isErr ? 'alert' : 'status');
    var msgEl = document.createElement('div'); msgEl.className = 'ui-toast-msg'; msgEl.textContent = message == null ? '' : String(message);
    item.appendChild(msgEl);
    if (opt.detail) {
      var det = document.createElement('details'); det.className = 'ui-toast-detail';
      var sum = document.createElement('summary'); sum.textContent = '詳しく'; det.appendChild(sum);
      var pre = document.createElement('div'); pre.textContent = String(opt.detail); det.appendChild(pre);
      item.appendChild(det);
    }
    var act = opt.action && opt.action.label && typeof opt.action.fn === 'function' ? opt.action : null;
    if (act) {
      var ab = document.createElement('button');
      ab.type = 'button'; ab.className = 'ui-toast-act'; ab.textContent = String(act.label);
      ab.addEventListener('click', function (e) { e.stopPropagation(); remove(); restoreFocus(); act.fn(); });
      item.appendChild(ab);
    }
    var xb = document.createElement('button');
    xb.type = 'button'; xb.className = 'ui-toast-x'; xb.setAttribute('aria-label', '知らせを閉じる'); xb.innerHTML = icon('close', { size: 14 });   /* SVG(A-10) */
    xb.addEventListener('click', function (e) { e.stopPropagation(); remove(); restoreFocus(); });
    item.appendChild(xb);
    function remove() { clearTimeout(timer); if (item.parentNode) item.parentNode.removeChild(item); }
    /* 知らせのボタンをキーで押すと知らせが消えてフォーカスが body に落ちるので、知らせを出したときにフォーカスがあった所へ戻す */
    var opener = document.activeElement;
    function restoreFocus() { var a = document.activeElement; if ((!a || a === document.body) && opener && opener !== document.body && opener.isConnected && opener.focus) opener.focus({ preventScroll: true }); }
    var timer = ms > 0 ? setTimeout(remove, ms) : 0;
    if (act || ms === 0) item.setAttribute('data-ui-keep', '');
    item.addEventListener('click', function (e) {
      if (e.target && e.target.closest && e.target.closest('details')) return;   // 「詳しく」の開閉では閉じない
      if (act || ms === 0) return;   // ボタンのある知らせ・消えない知らせは、本文を押しても閉じない(× か ボタンで)
      remove();
    });
    box.appendChild(item);
    return { close: remove, el: item };
  }

  /* ---- copy ---- クリップボードへ文字を写す。UIKit.copy(text, opt) -> Promise<true | false>(失敗しても reject しない)。
     opt.ok / opt.fail に文があれば、その知らせ(UIKit.toast。ok は 2.5 秒・fail は 5 秒の err)も出す。
     clipboard API が使えない(権限なし・フォーカスが無い)ときは、見えない textarea を選んで execCommand('copy') で写す
     (失敗したときに欄を選ぶなどは呼ぶ側で) */
  function copyByCommand(text) {
    try {
      var ta = document.createElement('textarea'), back = document.activeElement;
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0'; ta.style.top = '0'; ta.style.left = '0';
      document.body.appendChild(ta); ta.select();
      var ok = document.execCommand('copy');
      ta.remove();
      if (back && back.focus) try { back.focus({ preventScroll: true }); } catch (e) { /* 戻せなくても写せたかは変わらない */ }
      return !!ok;
    } catch (e) { return false; }
  }
  function copyText(text, opt) {
    opt = opt || {};
    text = String(text == null ? '' : text);
    var p = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(text).then(function () { return true; }, function () { return copyByCommand(text); })
      : Promise.resolve(copyByCommand(text));
    return p.then(function (ok) {
      if (ok && opt.ok) toastFn(opt.ok, { kind: 'ok', ms: 2500 });
      if (!ok && opt.fail) toastFn(opt.fail, { kind: 'err', ms: 5000 });
      return ok;
    });
  }

  /* ---- confirmTwice(二度押しの確認)---- 1回目でボタンの文字を text に変え、3秒以内のもう1回で run。実行したらすぐ元に戻す
     (実行後も「確認済み」のままだと、続けて押すと同じ操作がもう一度走るため) */
  function confirmTwice(btn, run, text) {
    if (!btn) return;
    if (btn.getAttribute('data-armed')) {
      clearTimeout(+btn.getAttribute('data-arm-t') || 0);
      btn.removeAttribute('data-armed'); btn.innerHTML = btn.getAttribute('data-label') || ''; btn.classList.remove('armed');
      run(); return;
    }
    btn.setAttribute('data-label', btn.innerHTML); btn.setAttribute('data-armed', '1');
    btn.textContent = text || 'もう一度押すと実行します'; btn.classList.add('armed');
    btn.setAttribute('data-arm-t', String(setTimeout(function () {
      if (btn.isConnected && btn.getAttribute('data-armed')) { btn.removeAttribute('data-armed'); btn.innerHTML = btn.getAttribute('data-label') || ''; btn.classList.remove('armed'); }
    }, 3000)));
  }

  /* ---- prefs(ホームの設定)---- api/ytt/prefs(app/prefs.py)。ホームから開いていない(合言葉なし)ときは available() が false。
     patch は同じ節をまとめて 400ms 後に送る(続けて変えても1回)。失敗したら知らせと [もう一度] */
  var prefsPending = {}, prefsTimer = {};
  function prefsFail(section, err) {
    toastFn('設定を保存できませんでした: ' + (err && err.message ? err.message : ''), { kind: 'err', ms: 0,
      action: { label: 'もう一度', fn: function () { prefsFlush(section); } } });
  }
  function prefsFlush(section, value) {
    var v = value || prefsPending[section];
    delete prefsPending[section]; clearTimeout(prefsTimer[section]);
    if (!v) return Promise.resolve(null);
    return yttPost('prefs', { op: 'patch', section: section, value: v }).then(function (j) { return j.value; }, function (e) {
      prefsPending[section] = Object.assign({}, v, prefsPending[section] || {});   /* 失敗した値は残す([もう一度]・次の patch と一緒に送る) */
      prefsFail(section, e);
      throw e;
    });
  }
  var prefs = {
    available: function () { return !!token(); },
    get: function (sections) { return yttPost('prefs', { op: 'get', sections: sections || null }).then(function (j) { return j.prefs || {}; }); },
    patch: function (section, value) {
      prefsPending[section] = Object.assign(prefsPending[section] || {}, value || {});
      clearTimeout(prefsTimer[section]);
      return new Promise(function (resolve, reject) {
        prefsTimer[section] = setTimeout(function () { prefsFlush(section).then(resolve, reject); }, 400);
      });
    },
    flush: function (section) { return prefsFlush(section); },
    remember: function (kind, key, name) {
      return yttPost('prefs', { op: 'remember', kind: kind, key: key, name: name }).then(function (j) { return j.streamer; }, function (e) { prefsFail('streamer', e); throw e; });
    }
  };

  /* ---- hide(一覧の項目を非表示に)---- 覚える場所はホームの設定の節 hidden(app/prefs.py: 一覧の名前 → {id: 時刻})。
     どの窓・どのツールで隠しても同じ(戻ったときに読み直す)。足す・外すは1件ずつ(op "hide")送る = 窓を2つ並べても相手の分を消さない。
     「非表示のものも出す」はこの画面の間だけ(覚えない = 開き直すといつも隠れている)。入口の外(合言葉なし)では available() が false */
  var hideMap = null, hideP = null, hideSubs = [], hideShow = {};
  function hideNotify(list) { for (var i = 0; i < hideSubs.length; i++) { try { hideSubs[i](list || null); } catch (e) { /* 1つの失敗で他を止めない */ } } }
  function hideLoad(force) {
    if (!token()) { hideMap = hideMap || {}; return Promise.resolve(hideMap); }
    if (hideP && !force) return hideP;
    var p = hideP = yttPost('prefs', { op: 'get', sections: ['hidden'] }).then(function (j) {
      var before = JSON.stringify(hideMap);
      hideMap = (j.prefs && j.prefs.hidden) || {};
      if (before !== JSON.stringify(hideMap)) hideNotify(null);
      return hideMap;
    }, function () { if (hideP === p) hideP = null; hideMap = hideMap || {}; return hideMap; });
    return p;
  }
  function hideSetLocal(list, ids, on) {
    hideMap = hideMap || {};
    var m = hideMap[list] || (hideMap[list] = {}), now = Date.now();
    for (var i = 0; i < ids.length; i++) { if (on) m[ids[i]] = now; else delete m[ids[i]]; }
  }
  var hide = {
    available: function () { return !!token(); },
    load: function (force) { return hideLoad(force); },
    has: function (list, id) { return !!(hideMap && hideMap[list] && id != null && Object.prototype.hasOwnProperty.call(hideMap[list], String(id))); },
    /* ids(配列)のうち非表示の数。ids を省くと、その一覧で覚えている数 */
    count: function (list, ids) {
      if (!ids) return hideMap && hideMap[list] ? Object.keys(hideMap[list]).length : 0;
      var n = 0; for (var i = 0; i < ids.length; i++) if (hide.has(list, ids[i])) n++;
      return n;
    },
    /* 非表示にする(on = true)・表示に戻す(false)。先に画面を変えて(onChange)から送り、失敗したら戻して知らせる。
       opt.label: 知らせの文の項目名、opt.undo: false で「元に戻す」を出さない、opt.quiet: 知らせを出さない */
    set: function (list, ids, on, opt) {
      opt = opt || {};
      ids = (Array.isArray(ids) ? ids : [ids]).filter(function (x) { return x != null && x !== ''; }).map(String);
      if (!ids.length) return Promise.resolve(null);
      on = on !== false;
      hideSetLocal(list, ids, on); hideNotify(list);
      return yttPost('prefs', { op: 'hide', list: list, ids: ids, hidden: on }).then(function (j) {
        hideMap[list] = j.hidden || {};
        if (!opt.quiet) {
          var what = opt.label ? '「' + clip(opt.label, 40) + '」を' : ids.length > 1 ? ids.length + '件を' : '';
          toastFn(on ? what + '非表示にしました' : what + '表示に戻しました', on && opt.undo !== false ? { ms: 6000, action: { label: '元に戻す', fn: function () { hide.set(list, ids, false, { quiet: true }); } } } : undefined);
        }
        return j.hidden;
      }, function (e) {
        hideSetLocal(list, ids, !on); hideNotify(list);
        toastFn((on ? '非表示にできませんでした: ' : '表示に戻せませんでした: ') + (e && e.message ? e.message : ''), { kind: 'err' });
        throw e;
      });
    },
    showing: function (list) { return !!hideShow[list]; },
    setShowing: function (list, on) { hideShow[list] = !!on; hideNotify(list); },
    /* 「非表示 n件を表示」の切り替えのボタン(n = 今の絞り込みで隠れている数)。描くたびに呼ぶ。押したら setShowing(→ onChange) */
    toggle: function (btn, list, n) {
      if (!btn) return;
      if (!btn.__uiHide) {
        btn.__uiHide = true;
        btn.addEventListener('click', function () { hide.setShowing(btn.getAttribute('data-hide-list'), !hide.showing(btn.getAttribute('data-hide-list'))); });
      }
      var on = hide.showing(list);
      btn.setAttribute('data-hide-list', list);
      btn.setAttribute('aria-pressed', String(on));
      btn.textContent = on ? '非表示のものを隠す' : '非表示 ' + n + '件を表示';
      btn.title = on ? '非表示にした項目を、また隠します' : '非表示にした項目も一覧に出します(薄く表示。「表示に戻す」で元に戻せます)';
      btn.hidden = !hide.available() || (!on && !n);
    },
    onChange: function (fn) { if (typeof fn === 'function') hideSubs.push(fn); }
  };
  life.onReturn(function () { if (hideMap && token()) hideLoad(true); });   /* 別の窓・ツールで隠した分を、戻ったときに読み直す */

  /* ---- keybar(画面の下の細い帯。いま使えるキー) ---- 既定は表示。設定「キーの帯を出す」(localStorage 'ytt:keybar' === '0' で消す) */
  var keybarEl = null, keybarItems = [];
  function keybarWanted() { try { return localStorage.getItem('ytt:keybar') !== '0'; } catch (e) { return true; } }
  function ensureKeybarEl() {
    if (keybarEl && keybarEl.isConnected) return keybarEl;
    keybarEl = document.createElement('div');
    keybarEl.className = 'ui-keybar'; keybarEl.setAttribute('aria-hidden', 'true'); keybarEl.hidden = true; keybarEl.tabIndex = -1;   /* 横にスクロールできても Tab で止まらない(飾りの帯) */
    (document.body || document.documentElement).appendChild(keybarEl);
    return keybarEl;
  }
  function keybarPaint() {
    var el = ensureKeybarEl(), html = '';
    for (var i = 0; i < keybarItems.length; i++) {
      var it = keybarItems[i] || {};
      html += '<span class="ui-keybar-item" data-k="' + esc(it.k || '') + '"><kbd class="ui-kbd">' + esc(it.k || '') + '</kbd>' + esc(it.l || '') + '</span>';
    }
    el.innerHTML = html;
    var show = keybarItems.length > 0 && keybarWanted();
    el.hidden = !show;
    if (show) root.setAttribute('data-keybar', ''); else root.removeAttribute('data-keybar');
  }
  var keybar = {
    set: function (items) { keybarItems = items || []; keybarPaint(); },
    flash: function (k) {
      var el = ensureKeybarEl(), items = el.querySelectorAll('.ui-keybar-item');
      for (var i = 0; i < items.length; i++) if (items[i].getAttribute('data-k') === k) (function (node) {
        node.classList.add('flash');
        setTimeout(function () { node.classList.remove('flash'); }, 220);
      })(items[i]);
    },
    clear: function () { keybarItems = []; keybarPaint(); }
  };

  /* ---- 文字の大きさ(localStorage 'ytt:fs'。'lg' で html[data-fs=lg]。ui-kit.css がトークンを少し大きくする) ---- */
  var fsControls = [], keybarControls = [];
  function fsPref() { try { return localStorage.getItem('ytt:fs') === 'lg' ? 'lg' : 'md'; } catch (e) { return 'md'; } }
  function applyFontSize() { if (fsPref() === 'lg') root.setAttribute('data-fs', 'lg'); else root.removeAttribute('data-fs'); }
  applyFontSize();
  /* 全体の設定(テーマ・文字の大きさ・キーの帯)は、どのツールで変えても他のタブ・他のツールに効く(storage イベント。テーマは既存の paint() と同じ仕組み) */
  window.addEventListener('storage', function (e) {
    if (e.key === 'ytt:fs') {
      applyFontSize();
      var fv = fsPref();
      for (var i = 0; i < fsControls.length; i++) fsControls[i].value = fv;
    } else if (e.key === 'ytt:keybar') {
      keybarPaint();
      var kv = keybarWanted();
      for (var j = 0; j < keybarControls.length; j++) keybarControls[j].checked = kv;
    }
  });

  /* ---- settings(⚙ の引き出し) ---- UIKit.settings.mount({tool: 要素 | null, title, version}) */
  var settingsDrawerEl = null, generalSectionEl = null;
  function addOpt(sel, value, label) { var o = document.createElement('option'); o.value = value; o.textContent = label; sel.appendChild(o); }
  function buildGeneralSection() {
    /* settings.mount() が2回以上呼ばれても(ツールが呼び直したときも)、控え・リスナーを増やさない: 一度作った節を使い回す(appendChild で移す) */
    if (generalSectionEl) return generalSectionEl;
    var sec = document.createElement('section'); sec.className = 'ui-settings-sec';
    var h3 = document.createElement('h3'); h3.textContent = '全体'; sec.appendChild(h3);

    var themeRow = document.createElement('div'); themeRow.className = 'ui-settings-row';
    var themeLabel = document.createElement('label'); themeLabel.textContent = 'テーマ'; themeLabel.htmlFor = 'uiSetTheme';   /* label for(A-24) */
    var themeSel = document.createElement('select'); themeSel.id = 'uiSetTheme';
    /* 配色を選ぶ。明るい = アイスライト / 暗い = 3つ / OSに合わせる(暗いときは、最後に選んだ暗い配色) */
    /* 値: light = アイスライト / dark = ネオンシアン / steel・green = 暗い + その配色 */
    addOpt(themeSel, 'light', 'アイスライト(明るい)'); addOpt(themeSel, 'dark', 'ネオンシアン(暗い)'); addOpt(themeSel, 'steel', '鋼の白(暗い)');
    addOpt(themeSel, 'green', 'ターミナルグリーン(暗い)'); addOpt(themeSel, 'system', 'OSに合わせる');
    var themeValue = function (p) { var c = theme.palette(); return p === 'dark' && c !== 'cyan' ? c : p; };
    themeSel.value = themeValue(theme.get());
    themeSel.addEventListener('change', function () {
      var v = themeSel.value;
      if (v === 'dark') { theme.palette('cyan'); theme.set('dark'); }
      else if (DARK_PALETTES[v]) { theme.palette(v); theme.set('dark'); }
      else theme.set(v);
    });
    theme.onChange(function (t, p) { themeSel.value = themeValue(p); });
    themeRow.appendChild(themeLabel); themeRow.appendChild(themeSel);

    var fsRow = document.createElement('div'); fsRow.className = 'ui-settings-row';
    var fsLabel = document.createElement('label'); fsLabel.textContent = '文字の大きさ'; fsLabel.htmlFor = 'uiSetFs';
    var fsSel = document.createElement('select'); fsSel.id = 'uiSetFs';
    addOpt(fsSel, 'md', '標準'); addOpt(fsSel, 'lg', '大きい');
    fsSel.value = fsPref();
    fsSel.addEventListener('change', function () {
      try { localStorage.setItem('ytt:fs', fsSel.value); } catch (e) { /* 保存できなくても見た目は変える */ }
      applyFontSize();
    });
    fsControls.push(fsSel);
    fsRow.appendChild(fsLabel); fsRow.appendChild(fsSel);

    var kbRow = document.createElement('div'); kbRow.className = 'ui-settings-row';
    var kbLabel = document.createElement('label'); kbLabel.className = 'lag';
    var kbCheck = document.createElement('input'); kbCheck.type = 'checkbox'; kbCheck.checked = keybarWanted();
    kbCheck.addEventListener('change', function () {
      try { localStorage.setItem('ytt:keybar', kbCheck.checked ? '1' : '0'); } catch (e) { /* 保存できなくても見た目は変える */ }
      keybarPaint();
    });
    keybarControls.push(kbCheck);
    kbLabel.appendChild(kbCheck); kbLabel.appendChild(document.createTextNode('キーの帯を出す'));
    kbRow.appendChild(kbLabel);

    sec.appendChild(themeRow); sec.appendChild(fsRow); sec.appendChild(kbRow);
    if (tools.mounted() && !/\/settings\/?$/.test(location.pathname)) {   /* すべての設定を 1 つの画面で(入口の /settings。S5) */
      var allRow = document.createElement('div'); allRow.className = 'ui-settings-row';
      var allSpan = document.createElement('span'); allSpan.textContent = 'すべての設定を 1 つの画面で';
      var allA = document.createElement('a'); allA.className = 'btn small'; allA.href = homeUrl('settings'); allA.textContent = '設定の画面を開く';
      allRow.appendChild(allSpan); allRow.appendChild(allA); sec.appendChild(allRow);
    }
    generalSectionEl = sec;
    return sec;
  }
  function buildSettingsDrawer() {
    if (settingsDrawerEl && settingsDrawerEl.isConnected) return settingsDrawerEl;
    var el = document.createElement('aside');
    el.className = 'ui-drawer'; el.id = 'uiSettingsDrawer'; el.hidden = true;
    el.setAttribute('aria-hidden', 'true'); el.setAttribute('aria-labelledby', 'uiSettingsTitle');
    var head = document.createElement('div'); head.className = 'ui-drawer-head';
    var h2 = document.createElement('h2'); h2.className = 'ui-drawer-title'; h2.id = 'uiSettingsTitle'; h2.textContent = '設定';
    var ver = document.createElement('span'); ver.className = 'ui-ver'; ver.id = 'uiSettingsVer'; ver.hidden = true;
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button'; closeBtn.className = 'btn ghost icon small'; closeBtn.setAttribute('aria-label', '閉じる'); closeBtn.innerHTML = icon('close');
    closeBtn.addEventListener('click', function () { drawer.close(el); });
    head.appendChild(h2); head.appendChild(ver); head.appendChild(closeBtn);
    var body = document.createElement('div'); body.className = 'ui-drawer-body'; body.id = 'uiSettingsBody';
    el.appendChild(head); el.appendChild(body);
    (document.body || document.documentElement).appendChild(el);
    settingsDrawerEl = el;
    return el;
  }
  /* 設定の保存・読み込みの失敗を出す。UIKit.settings.status(state, message, retry, label)
     state = 'err' のとき、⚙ ボタン([data-ui-settings])に赤い印と title、設定の引き出しの先頭に「message [label(既定: もう一度)]」。
     それ以外('' / null)で消す。retry は押したときに呼ぶ関数(無ければボタンを出さない)。文書の保存の表示とは別の場所 */
  var setStatus = { state: '', message: '', retry: null, label: '' }, setStatusEl = null;
  function paintSettingsStatus() {
    var err = setStatus.state === 'err';
    var btns = document.querySelectorAll('[data-ui-settings]');
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      if (b.__uiSetLabel === undefined) b.__uiSetLabel = b.getAttribute('aria-label');
      if (b.__uiSetTitle === undefined) b.__uiSetTitle = b.getAttribute('title');
      if (err) {
        b.setAttribute('data-ui-status', 'err');
        b.setAttribute('title', setStatus.message);
        b.setAttribute('aria-label', (b.__uiSetLabel || '設定') + '(' + setStatus.message + ')');
      } else {
        b.removeAttribute('data-ui-status');
        if (b.__uiSetTitle === null) b.removeAttribute('title'); else b.setAttribute('title', b.__uiSetTitle);
        if (b.__uiSetLabel === null) b.removeAttribute('aria-label'); else b.setAttribute('aria-label', b.__uiSetLabel);
      }
    }
    if (!setStatusEl) return;
    setStatusEl.hidden = !err;
    setStatusEl.textContent = '';
    if (!err) return;
    var t = document.createElement('span'); t.textContent = setStatus.message; setStatusEl.appendChild(t);
    if (typeof setStatus.retry === 'function') {
      var rb = document.createElement('button'); rb.type = 'button'; rb.className = 'btn small'; rb.textContent = setStatus.label || 'もう一度';
      var fn = setStatus.retry;
      rb.addEventListener('click', function () { rb.disabled = true; try { var r = fn(); if (r && typeof r.then === 'function') r.then(function () { rb.disabled = false; }, function () { rb.disabled = false; }); else rb.disabled = false; } catch (e) { rb.disabled = false; } });
      setStatusEl.appendChild(rb);
    }
  }
  function settingsStatus(state, message, retry, label) {
    setStatus = { state: state === 'err' ? 'err' : '', message: String(message || ''), retry: retry || null, label: label || '' };
    paintSettingsStatus();
  }
  function settingsMount(opts) {
    opts = opts || {};
    var el = buildSettingsDrawer(), body = el.querySelector('#uiSettingsBody');
    body.innerHTML = '';
    if (!setStatusEl) { setStatusEl = document.createElement('div'); setStatusEl.className = 'notice err ui-settings-status'; setStatusEl.setAttribute('role', 'alert'); setStatusEl.hidden = true; }
    body.appendChild(setStatusEl);
    if (opts.tool) { opts.tool.classList.add('ui-settings-sec'); body.appendChild(opts.tool); }
    body.appendChild(buildGeneralSection());
    if (opts.title) el.querySelector('#uiSettingsTitle').textContent = opts.title;
    var verEl = el.querySelector('#uiSettingsVer');
    if (opts.version) { verEl.textContent = opts.version; verEl.hidden = false; } else verEl.hidden = true;
    var btns = document.querySelectorAll('[data-ui-settings]');
    for (var i = 0; i < btns.length; i++) {
      if (btns[i].__uiSettingsWired) continue;
      btns[i].__uiSettingsWired = true;
      (function (btn) { btn.addEventListener('click', function () { if (drawer.isOpen(el)) drawer.close(el); else drawer.open(el, { modal: true, opener: btn }); }); })(btns[i]);
    }
    paintSettingsStatus();
    return el;
  }
  var settings = { mount: settingsMount, status: settingsStatus,
                   general: buildGeneralSection };   /* 「全体」の節(テーマ・文字の大きさ・キーの帯)を /settings/ の画面にも置く */

  /* ---- settingsForm(設定を 1 つに S5。notes:docs/spec/data.md の 4)---- 宣言的なスキーマから設定の節を描く。
     ラベル・1 行の説明・範囲と形の検査・「標準に戻す」・保存の印が自動で付く(入口の /settings の画面が使う。各ツールの ⚙ は別の作り)。
     UIKit.settingsForm.render(host, group, io) -> {refresh()}
       group = {title, hint, items: [{key, type, label, hint, default, min, max, step, options: [[値, 表示]], unit, scale, placeholder, maxlength, pattern, when, link}]}
         type: 'bool'(スイッチ)/ 'enum'(select)/ 'int' / 'number' / 'text' / 'folder'(フルパスの欄)/ 'textarea' / 'link'(別の画面で直すもの。ボタンだけ)
         scale: 欄に出す値 = 保存の値 × scale(0.65 を 65% と出すとき 100)。when: {key, eq} か {key, ne}(その鍵の値で行を出す・隠す)
       io = {get(key) -> 今の値(undefined = 無い), set(key, 値) -> Promise(保存して io.get が新しい値を返すようにする), disabled() -> 文(あれば欄を無効にして理由を出す)}
     欄を変えると検査 → io.set → 行に「保存しました」(2 秒)→ 節の要素から 'ui-set-changed'(detail {key, value}。bubbles)。失敗なら理由を行に出して値を戻す。
     「標準に戻す」は default と違うときだけ出す。
     UIKit.settingsForm.filter(root, text) -> 見える項目の数(ラベル・説明・鍵に text を含む行だけ残す。節に 1 つも無ければ節も隠す) */
  function setFormId(key) { return 'uiSet-' + String(key).replace(/[^A-Za-z0-9_-]/g, '_'); }
  function setFormEl(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function setFormOptValue(item, str) {   /* select の文字列 → options に書いた元の型(数値の選択肢は数値のまま保存する) */
    var o = item.options || [];
    for (var i = 0; i < o.length; i++) if (String(o[i][0]) === str) return o[i][0];
    return str;
  }
  function setFormNum(item, raw) {   /* 欄の文字 → 保存する数(scale を戻す)。範囲の外・数でなければ null */
    var s = String(raw == null ? '' : raw).trim();
    if (!s) return null;
    var v = Number(s);
    if (!isFinite(v)) return null;
    if (item.scale) v = v / item.scale;
    v = Math.round(v * 1e6) / 1e6;
    if (item.type === 'int' && Math.round(v) !== v) return null;
    if (item.min != null && v < item.min) return null;
    if (item.max != null && v > item.max) return null;
    return v;
  }
  function setFormShown(item, v) { return v == null ? '' : item.scale ? String(Math.round(v * item.scale * 1e6) / 1e6) : String(v); }
  function setFormRangeText(item) {
    var lo = item.min != null ? setFormShown(item, item.min) : '', hi = item.max != null ? setFormShown(item, item.max) : '';
    return lo !== '' && hi !== '' ? lo + '〜' + hi : lo !== '' ? lo + ' 以上' : hi !== '' ? hi + ' 以下' : '';
  }
  function setFormControl(item, id) {
    var c;
    if (item.type === 'bool') { c = document.createElement('input'); c.type = 'checkbox'; c.className = 'ui-switch'; }
    else if (item.type === 'enum') {
      c = document.createElement('select');
      var o = item.options || [];
      for (var i = 0; i < o.length; i++) { var op = document.createElement('option'); op.value = String(o[i][0]); op.textContent = o[i][1] != null ? o[i][1] : String(o[i][0]); c.appendChild(op); }
    } else if (item.type === 'textarea') { c = document.createElement('textarea'); c.rows = item.rows || 3; c.spellcheck = false; }
    else if (item.type === 'link') { c = document.createElement('a'); c.className = 'btn small'; c.href = item.link && item.link.href ? item.link.href : '#'; c.textContent = item.link && item.link.label ? item.link.label : '開く'; }
    else {
      c = document.createElement('input');
      c.type = item.type === 'int' || item.type === 'number' ? 'number' : 'text';
      if (c.type === 'number') {
        if (item.min != null) c.min = setFormShown(item, item.min);
        if (item.max != null) c.max = setFormShown(item, item.max);
        c.step = item.step != null ? String(item.step) : item.type === 'int' ? '1' : 'any';
        c.inputMode = item.type === 'int' ? 'numeric' : 'decimal';
      } else { c.autocomplete = 'off'; c.spellcheck = false; if (item.type === 'folder') c.classList.add('ui-set-folder'); }
      if (item.maxlength) c.maxLength = item.maxlength;
    }
    if (item.placeholder && 'placeholder' in c) c.placeholder = item.placeholder;
    c.id = id;
    return c;
  }
  function setFormFill(item, c, v) {
    if (item.type === 'link') return;
    if (v === undefined) v = item['default'];
    if (item.type === 'bool') c.checked = v === true;
    else if (item.type === 'enum') {
      c.value = String(v == null ? '' : v);
      if (c.value !== String(v == null ? '' : v) && item['default'] !== undefined) c.value = String(item['default']);   /* 選択肢に無い値は標準に */
    } else if (item.type === 'int' || item.type === 'number') c.value = setFormShown(item, v);
    else c.value = v == null ? '' : String(v);
  }
  function setFormRead(item, c) {   /* 欄 → 保存する値。形が悪ければ {error} */
    if (item.type === 'bool') return { value: c.checked };
    if (item.type === 'enum') return { value: setFormOptValue(item, c.value) };
    if (item.type === 'int' || item.type === 'number') {
      var n = setFormNum(item, c.value);
      if (n === null) return { error: (setFormRangeText(item) ? setFormRangeText(item) + ' の' : '') + '数で入れてください' };
      return { value: n };
    }
    var s = String(c.value == null ? '' : c.value);
    if (item.type !== 'textarea') s = s.trim();
    if (item.maxlength && s.length > item.maxlength) return { error: item.maxlength + ' 文字までです' };
    if (item.pattern && s && !(new RegExp(item.pattern)).test(s)) return { error: item.patternText || '形が正しくありません' };
    return { value: s };
  }
  function setFormSame(a, b) { return JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b); }
  function setFormWhen(item, io) {
    var w = item.when;
    if (!w || !w.key) return true;
    var v = io.get(w.key);
    if ('eq' in w) return setFormSame(v, w.eq);
    if ('ne' in w) return !setFormSame(v, w.ne);
    return true;
  }
  function settingsFormRender(host, group, io) {
    var sec = setFormEl('section', 'ui-set-group');
    sec.setAttribute('data-ui-set-group', group.id || '');
    if (group.id) sec.id = 'uiSetGroup-' + group.id;   /* ほかの画面からのリンク先(settings#uiSetGroup-intake など) */
    if (group.title) sec.appendChild(setFormEl('h4', null, group.title));
    if (group.hint) sec.appendChild(setFormEl('p', 'hint ui-set-ghint', group.hint));
    var off = typeof io.disabled === 'function' ? io.disabled() : '';
    if (off) sec.appendChild(setFormEl('p', 'notice ui-set-off', off));
    var rows = [];
    for (var i = 0; i < (group.items || []).length; i++) {
      (function (item) {
        var id = setFormId(item.key), row = setFormEl('div', 'ui-set-item');
        row.setAttribute('data-ui-set-key', item.key);
        row.setAttribute('data-ui-set-text', ((item.label || '') + ' ' + (item.hint || '') + ' ' + item.key).toLowerCase());
        var main = setFormEl('div', 'ui-set-main'), lab = setFormEl('label', 'ui-set-label', item.label || item.key), ctl = setFormEl('div', 'ui-set-ctl');
        var c = setFormControl(item, id);
        if (item.type === 'link') lab.id = id + '-l'; else lab.htmlFor = id;
        if (off && item.type !== 'link') c.disabled = true;
        ctl.appendChild(c);
        if (item.unit) ctl.appendChild(setFormEl('span', 'hint ui-set-unit', item.unit));
        main.appendChild(lab); main.appendChild(ctl);
        var side = setFormEl('div', 'ui-set-side'), reset = setFormEl('button', 'btn ghost small ui-set-reset', '標準に戻す'), mark = setFormEl('span', 'ui-set-mark');
        reset.type = 'button'; reset.hidden = true; mark.setAttribute('role', 'status');
        side.appendChild(reset); side.appendChild(mark);
        if (item.type === 'link' || item['default'] === undefined || off) reset.hidden = true;
        row.appendChild(main); row.appendChild(side);
        if (item.hint) row.appendChild(setFormEl('p', 'hint ui-set-hint', item.hint));
        sec.appendChild(row);
        var markTimer = 0;
        function showMark(text, err) {
          clearTimeout(markTimer);
          mark.textContent = text; mark.classList.toggle('err', !!err);
          if (!err && text) markTimer = setTimeout(function () { mark.textContent = ''; }, 2000);
        }
        /* 打っている途中の欄(フォーカスのある text・int・number・folder・textarea)は、ほかの欄の保存の描き直しで書き戻さない
           (入力が消えて change も出ず保存されなかった)。保存の失敗で値を戻すときだけ force で書き戻す */
        /* 自分の保存が返るまでの欄(saving)も書き戻さない: 先に返ったほかの欄の保存の答えは、まだこの欄の新しい値を持っていない */
        var saving = false;
        function typingIn() { var a = document.activeElement; return a === c && (item.type === 'text' || item.type === 'folder' || item.type === 'int' || item.type === 'number' || item.type === 'textarea'); }
        function paint(force) {
          var v = io.get(item.key);
          if (force === true || (!saving && !typingIn())) setFormFill(item, c, v);
          if (item['default'] !== undefined && !off && item.type !== 'link') reset.hidden = setFormSame(v === undefined ? item['default'] : v, item['default']);
          row.hidden = !setFormWhen(item, io);
        }
        function save(value) {
          if (setFormSame(value, io.get(item.key))) { showMark(''); return Promise.resolve(); }
          c.disabled = true; saving = true;
          return Promise.resolve().then(function () { return io.set(item.key, value); }).then(function () {
            saving = false; c.disabled = !!off; showMark('保存しました', false); paintAll();
            /* ほかの節の when(この鍵で出す・隠す)も描き直せるように知らせる(画面が document で聞いて全部の節の refresh を呼ぶ) */
            sec.dispatchEvent(new CustomEvent('ui-set-changed', { bubbles: true, detail: { key: item.key, value: value } }));
          }, function (e) {
            saving = false; c.disabled = !!off; showMark((e && e.message) || '保存できませんでした', true); paint(true);
            throw e;
          }).then(null, function () { /* 行に出した */ });
        }
        if (item.type !== 'link') {
          c.addEventListener('change', function () {
            var r = setFormRead(item, c);
            if (r.error) { showMark(r.error, true); return; }
            save(r.value);
          });
          reset.addEventListener('click', function () { save(item['default']); });
        }
        rows.push(paint);
      })(group.items[i]);
    }
    function paintAll() { for (var k = 0; k < rows.length; k++) rows[k](false); }
    paintAll();
    host.appendChild(sec);
    return { el: sec, refresh: paintAll };
  }
  function settingsFormFilter(root, text) {
    var q = String(text || '').trim().toLowerCase(), n = 0;
    var groups = root.querySelectorAll('[data-ui-set-group]');
    for (var g = 0; g < groups.length; g++) {
      var items = groups[g].querySelectorAll('[data-ui-set-key]'), shown = 0;
      for (var i = 0; i < items.length; i++) {
        var hit = !q || (items[i].getAttribute('data-ui-set-text') || '').indexOf(q) >= 0;
        items[i].classList.toggle('ui-set-nomatch', !hit);
        if (hit && !items[i].hidden) shown++;
      }
      groups[g].classList.toggle('ui-set-nomatch', !!q && shown === 0);
      n += shown;
    }
    return n;
  }
  var settingsForm = { render: settingsFormRender, filter: settingsFormFilter, id: setFormId };

  /* ---- keys(共通の再生キー) ---- isTyping/helpHtml/playback(NOT auto-installed。画面が自分のキー処理の前に呼び、true なら自分の処理をしない) */
  /* 文字を打てる input だけ「入力中」とみなす(checkbox・radio・button・submit・color・file などは単体キーを邪魔しない) */
  var TYPING_INPUT_TYPES = { text: 1, search: 1, number: 1, email: 1, url: 1, password: 1, tel: 1, date: 1, time: 1, 'datetime-local': 1, month: 1, week: 1, range: 1 };
  function isTyping(t) {
    if (!t) return false;
    var tag = (t.tagName || '').toLowerCase();
    if (tag === 'textarea' || tag === 'select') return true;
    if (t.isContentEditable) return true;
    if (t.classList && t.classList.contains('ui-time')) return true;   // 時刻の欄(数字・矢印を自分で使う)
    if (tag === 'input') return !!TYPING_INPUT_TYPES[String(t.type || 'text').toLowerCase()];
    return false;
  }
  /* Space はこれらの上ではブラウザの既定の動き(ボタンを押す・チェックを切り替えるなど)に任せる */
  function isSpaceControlTarget(t) {
    if (!t) return false;
    var tag = (t.tagName || '').toLowerCase();
    if (tag === 'button' || tag === 'summary') return true;
    if (tag === 'a' && t.hasAttribute('href')) return true;
    if (t.getAttribute && t.getAttribute('role') === 'button') return true;
    if (tag === 'input') { var ty = String(t.type || '').toLowerCase(); return ty === 'checkbox' || ty === 'radio'; }
    return false;
  }
  /* キーの組み合わせの表記(割り当ての保存形式)。'j'・'Shift+j'・'Space'・'Shift+Space'・'ArrowLeft'・','。
     1文字の記号は Shift で文字そのものが変わる('?' など)ので Shift を付けない。英字・Space・名前のあるキー(矢印など)だけ Shift を付ける */
  var KEY_TEXT = { ArrowLeft: '←', ArrowRight: '→', ArrowUp: '↑', ArrowDown: '↓', Space: 'Space', Enter: 'Enter', Tab: 'Tab', Escape: 'Esc', Delete: 'Del', Backspace: 'BS' };
  function comboOf(e) {
    var k = e.key;
    if (!k || k === 'Shift' || k === 'Control' || k === 'Alt' || k === 'Meta' || k === 'Dead' || k === 'Process' || k === 'Unidentified') return '';
    var base, shiftable;
    if (k === ' ' || k === 'Spacebar') { base = 'Space'; shiftable = true; }
    else if (k.length === 1) { base = k.toLowerCase(); shiftable = /[a-z]/i.test(k); }
    else { base = k; shiftable = true; }
    return (e.shiftKey && shiftable ? 'Shift+' : '') + base;
  }
  function keyText(combo) {
    if (!combo) return '未設定';
    return String(combo).split('+').map(function (p) { return KEY_TEXT[p] || (p.length === 1 ? p.toUpperCase() : p); }).join('+');
  }
  /* 共通の再生キーの操作(id → 既定のキー・説明)。画面が keymap を渡せば割り当てを変えられる(編集)。渡さなければ既定のまま(スタジオ) */
  var PLAYBACK_ACTIONS = [
    ['playPause', 'Space', '再生・停止'], ['back1', 'j', '1秒戻る'], ['stop', 'k', '止める'], ['play', 'l', '再生(もう一度で 1.5 → 2 倍)'],
    ['seekBack', 'ArrowLeft', '1秒戻る(Shift で5秒)'], ['seekFwd', 'ArrowRight', '1秒進む(Shift で5秒)'],
    ['frameBack', ',', '1コマ戻る'], ['frameFwd', '.', '1コマ進む'], ['markIn', 'i', 'IN(始まりの印)'], ['markOut', 'o', 'OUT(終わりの印)']   /* スタジオのボタン「IN(開始)/ OUT(終了)」と同じ呼び方(S18) */
  ];
  function playbackMap(km) {
    var out = {};
    for (var i = 0; i < PLAYBACK_ACTIONS.length; i++) {
      var id = PLAYBACK_ACTIONS[i][0];
      out[id] = km && typeof km[id] === 'string' ? km[id] : PLAYBACK_ACTIONS[i][1];
    }
    return out;
  }
  /* K・L で戻す速さは、画面の速さの設定(defaultPlaybackRate。編集の「速さ」など)。無ければ 1 倍 */
  function baseRate(media) { var r = +media.defaultPlaybackRate; return r > 0 ? r : 1; }
  /* play() の約束(Promise)の失敗は無視する: 再生の直後に止めると「play() request was interrupted」で失敗するが、止めたかっただけなので問題ない */
  function playQuiet(media) { var p = media.play(); if (p && typeof p.catch === 'function') p.catch(function () { /* 無視 */ }); }
  /* 押しっぱなし(自動の繰り返し)で続けて働いてよい操作 */
  var PLAYBACK_REPEAT = { back1: 1, seekBack: 1, seekFwd: 1, frameBack: 1, frameFwd: 1 };
  function keysPlayback(opts) {
    opts = opts || {};
    return function (e) {
      if (opts.enabled && !opts.enabled()) return false;
      if (e.isComposing || e.keyCode === 229) return false;   // 日本語の変換中は受け取らない(段6)
      if (isTyping(e.target)) return false;
      if (e.ctrlKey || e.altKey || e.metaKey) return false;
      /* media・fps・keymap は関数でもよい(毎回そのとき呼ぶ: 動画の差し替え・読み込み後に決まる fps・設定の変更に対応) */
      var media = typeof opts.media === 'function' ? opts.media() : opts.media;
      var fps = typeof opts.fps === 'function' ? opts.fps() : opts.fps;
      fps = fps > 0 ? fps : 30;
      var km = playbackMap(typeof opts.keymap === 'function' ? opts.keymap() : opts.keymap);
      var combo = comboOf(e); if (!combo) return false;
      var action = null, big = false;
      for (var id in km) if (km[id] && km[id] === combo) { action = id; break; }
      /* ← → に当たる操作は Shift つきで5秒(割り当てたキー + Shift。決まりは derivedKeys の1か所 = キー配置の重なりの検査と同じ) */
      if (!action) { var dv = derivedKeys(km); if (dv[combo]) { action = dv[combo]; big = true; } }
      if (!action) return false;
      if (action === 'playPause' && isSpaceControlTarget(e.target) && (combo === 'Space' || combo === 'Enter')) return false;   // ボタン・チェックなどは Space の既定の動きに任せる
      e.preventDefault();
      if (e.repeat && !PLAYBACK_REPEAT[action]) return true;   // 押しっぱなしで再生・停止などを繰り返さない(ページのスクロールも止める)
      function seek(delta) { if (media) { try { media.currentTime = Math.max(0, (media.currentTime || 0) + delta); } catch (er) { /* まだ読み込めていない */ } } }
      if (action === 'playPause') { if (media) { try { if (media.paused) playQuiet(media); else media.pause(); } catch (er) { /* 無視 */ } } }
      else if (action === 'back1') seek(-1);
      else if (action === 'stop') { if (media) { try { media.pause(); media.playbackRate = baseRate(media); } catch (er) { /* 無視 */ } } }
      else if (action === 'play') {
        if (media) {
          try { if (media.paused) { media.playbackRate = baseRate(media); playQuiet(media); } else media.playbackRate = media.playbackRate >= 1.5 ? 2 : 1.5; } catch (er) { /* 無視 */ }
        }
      }
      else if (action === 'seekBack') seek(big ? -5 : -1);
      else if (action === 'seekFwd') seek(big ? 5 : 1);
      else if (action === 'frameBack' || action === 'frameFwd') {
        var dir = action === 'frameBack' ? -1 : 1, done = false;
        if (typeof opts.onFrame === 'function') done = opts.onFrame(dir) === true;
        if (!done) seek(dir * (1 / fps));
      }
      else if (action === 'markIn') { if (typeof opts.onIn === 'function') opts.onIn(); }
      else if (action === 'markOut') { if (typeof opts.onOut === 'function') opts.onOut(); }
      var name = keyText(combo);
      if (typeof opts.onKey === 'function') opts.onKey(name, action);   // どの操作か(キーの名前は割り当てで変わるので、画面は操作で判断する)
      keybar.flash(name);
      return true;
    };
  }
  /* 派生キー: 共通の再生キーの割り当て(km。足りない所は既定)から、「← → に当たるキー + Shift」(5秒)→ 操作の id。{ 'Shift+ArrowLeft': 'seekBack', … }
     keysPlayback(押したとき)と keymap(登録のときの重なりの検査)が同じこれを使う(段3 3-2 監査 03。派生を増やすときはここだけ) */
  function derivedKeys(km) {
    var m = playbackMap(km), out = {};
    ['seekBack', 'seekFwd'].forEach(function (id) { var d = kmDerived(m[id]); if (d && !out[d]) out[d] = id; });
    return out;
  }
  var keysApi = { isTyping: isTyping, playback: keysPlayback, comboOf: comboOf, keyText: keyText, PLAYBACK_ACTIONS: PLAYBACK_ACTIONS, playbackMap: playbackMap, derived: derivedKeys };

  /* ==== keymap = キーの一覧がそのままキー配置の設定(編集・スタジオで同じ部品。使い方は README.md の「v8」) ====
     キーを変える場所は ? の一覧の 1 か所(⚙ の設定には「キー配置を変える(?)」のボタンだけを置き、同じ一覧を開く。場所を重ねない)。キーのボタンを押す → その場で次のキーを待つ
     (Esc = 取り消しだけ・一覧は閉じない / Delete = 外す)。重なったら一覧の中に「「X」から外しました [戻す]」(一覧はモーダルの上なので、知らせは一覧の中に出す)。
     共通の再生キー(PLAYBACK_ACTIONS)はホームの設定 keymap.playback に 1 つ(どのツールで変えても同じ)。ツールのキーは各ツールが保存する。
     重なりの検査はここ 1 か所: 変えられないキー(全ツール)・共通の再生キー・ツールのキー・派生キー(← → に当たるキー + Shift = 5 秒。GPT-03) */
  var PB_IDS = {};
  for (var pbi = 0; pbi < PLAYBACK_ACTIONS.length; pbi++) PB_IDS[PLAYBACK_ACTIONS[pbi][0]] = PLAYBACK_ACTIONS[pbi];
  /* 共通の再生キーにできないキー(どれかのツールで固定の意味がある。再生のキーはどのタブ・ツールでも先に働くので、ツールごとには決められない) */
  var PB_BLOCKED = { ArrowUp: '編集: 前の行', ArrowDown: '編集: 次の行', 'Shift+ArrowUp': '編集: 前の未校正', 'Shift+ArrowDown': '編集: 次の未校正',
    Tab: '入力欄の出入り', 'Shift+Tab': 'フォーカスの移動', Escape: '取り消し・閉じる', Enter: 'ボタンを押す', '?': 'キーの一覧',
    s: '編集 2 カット: 分割', h: '編集 2 カット: I〜O を削る', q: '編集 2 カット: 始まりの端', w: '編集 2 カット: 終わりの端',
    '[': '編集 2 カット: 前の区間', ']': '編集 2 カット: 次の区間', Delete: '編集 2 カット: 削る/戻す', Backspace: '編集 2 カット: 削る/戻す',
    '+': '編集 2 カット: 拡大', '=': '編集 2 カット: 拡大', '-': '編集 2 カット: 縮小', Home: '編集 2 カット: 先頭へ', End: '編集 2 カット: 末尾へ',
    '<': '編集 2 カット: 選んだ端を10コマ戻す(Shift+,)', '>': '編集 2 カット: 選んだ端を10コマ進める(Shift+.)',   // Shift+, / Shift+. は e.key が < > になる(段3 3-2)
    'Shift+n': '案件: 次の未校正の切り抜き' };   // 案件の画面(/cases)
  for (var dgi = 0; dgi <= 9; dgi++) PB_BLOCKED[String(dgi)] = '編集: 話者の番号';
  var KM_COMBO_RE = /^(?:Shift\+)?(?:[^\x00-\x1f\x7f]|[A-Z][A-Za-z0-9]{1,20})$/;   /* app/prefs.py の COMBO_RE と同じ */
  /* ← → に当たるキー + Shift(5 秒)。1文字の記号は Shift で文字そのものが変わるので派生しない(comboOf と同じ決まり) */
  function kmDerived(combo) {
    if (!combo || combo.indexOf('Shift+') === 0) return '';
    if (combo.length === 1 && !/[a-z]/.test(combo)) return '';
    return 'Shift+' + combo;
  }
  /* キーの表記 → <kbd>。'Shift+j' → Shift + J・'+' はそのまま 1 つ */
  function kmKbd(combo) {
    var parts = combo.indexOf('Shift+') === 0 && combo.length > 6 ? ['Shift', combo.slice(6)] : [combo];
    return parts.map(function (p) { return '<kbd class="ui-kbd">' + esc(KEY_TEXT[p] || (p.length === 1 ? p.toUpperCase() : p)) + '</kbd>'; }).join('+');
  }
  /* 一覧に出すだけの表記(変えられないキー・固定の別の手段)。'Ctrl+Shift+Z'・'1…9'・'Shift+↓' など */
  function kmKbdText(text) {
    var t = String(text);
    var parts = t === '+' ? ['+'] : t.split('+');
    return parts.map(function (p) { return '<kbd class="ui-kbd">' + esc(p) + '</kbd>'; }).join('+');
  }
  var kmCap = null, kmEscAt = 0;   /* キーを待っている { km(内部), id, el }(画面に 1 つ)・Esc で取り消した時刻(同じ Esc で一覧が閉じないように) */
  function kmCreate(o) {
    o = o || {};
    var acts = o.actions || [], byId = {}, groups = o.groups || [], fixed = o.fixed || [];
    for (var i = 0; i < acts.length; i++) byId[acts[i].id] = acts[i];
    var self = { tool: {}, pb: {}, prefsPb: null, eff: {}, used: {}, lost: {}, derived: {}, mounts: [], note: null, lastId: null };
    function labelOf(id) { return PB_IDS[id] ? PB_IDS[id][2] : (byId[id] ? byId[id].label : id); }
    function defOf(id) { return PB_IDS[id] ? PB_IDS[id][1] : (byId[id] ? byId[id].def : ''); }
    function toolRefuse(combo) { return typeof o.refuse === 'function' ? (o.refuse(combo) || '') : ''; }
    /* 保存した値 → 今効く割り当て。重なり・使えないキーは外し、理由を lost に残す(一覧のその行に出す)。再生のキーが先(先に処理されるため) */
    function compute() {
      var eff = {}, used = {}, lost = {}, derived = {}, i, id, k, why;
      for (i = 0; i < PLAYBACK_ACTIONS.length; i++) {
        id = PLAYBACK_ACTIONS[i][0]; k = typeof self.pb[id] === 'string' ? self.pb[id] : PLAYBACK_ACTIONS[i][1];
        why = !k ? '' : !KM_COMBO_RE.test(k) ? '形が正しくない' : PB_BLOCKED[k] ? '「' + PB_BLOCKED[k] + '」に使う' : toolRefuse(k) ? '「' + toolRefuse(k) + '」に使う'
          : used[k] ? '「' + labelOf(used[k]) + '」と重なる' : '';
        if (why) { lost[id] = { key: k, why: why }; k = ''; }
        if (k) used[k] = id;
        eff[id] = k;
      }
      var dvk = derivedKeys(eff);   // 外れた(eff が '')再生のキーからは派生しない
      for (k in dvk) if (eff[dvk[k]] && !used[k]) derived[k] = dvk[k];
      for (i = 0; i < acts.length; i++) {
        id = acts[i].id; k = typeof self.tool[id] === 'string' ? self.tool[id].slice(0, 24) : acts[i].def;
        why = !k ? '' : !KM_COMBO_RE.test(k) ? '形が正しくない' : toolRefuse(k) ? '「' + toolRefuse(k) + '」に使う'
          : used[k] ? (PB_IDS[used[k]] ? '共通の再生キー「' + labelOf(used[k]) + '」に使われている' : '「' + labelOf(used[k]) + '」と重なる')
          : derived[k] ? '共通の再生キー「' + labelOf(derived[k]) + '」の Shift つき(5秒)に使われている' : '';
        if (why) { lost[id] = { key: k, why: why }; k = ''; }
        if (k) used[k] = id;
        eff[id] = k;
      }
      self.eff = eff; self.used = used; self.lost = lost; self.derived = derived;
    }
    /* 割り当てられない理由('' = 割り当てられる)。ほかの操作と重なるだけなら割り当てられる(そちらを外して [戻す] を出す) */
    function refusal(id, combo) {
      var K = keyText(combo), r, d;
      if (!KM_COMBO_RE.test(combo)) return K + ' は割り当てられません';
      if (PB_IDS[id]) {
        if ((r = PB_BLOCKED[combo] || toolRefuse(combo))) return K + ' は「' + r + '」に使っているので、共通の再生キーには割り当てられません';
        if ((id === 'seekBack' || id === 'seekFwd') && (d = kmDerived(combo)) && (r = PB_BLOCKED[d] || toolRefuse(d)))
          return K + ' に Shift を足した ' + keyText(d) + '(5秒)が「' + r + '」と重なるので割り当てられません';
        return '';
      }
      if ((r = toolRefuse(combo))) return K + ' は「' + r + '」に使っているので割り当てられません';
      if (self.derived[combo]) return K + ' は共通の再生キー「' + labelOf(self.derived[combo]) + '」に Shift を足した 5 秒の移動に使っているので割り当てられません';
      return '';
    }
    function fullTool(tool) {
      var out = {};
      for (var i = 0; i < acts.length; i++) { var id = acts[i].id; out[id] = typeof tool[id] === 'string' ? tool[id] : acts[i].def; }
      return out;
    }
    function copy(x) { var out = {}; for (var k in x) if (Object.prototype.hasOwnProperty.call(x, k)) out[k] = x[k]; return out; }
    function savePb() {
      var full = playbackMap(self.pb);
      if (prefs.available()) { self.prefsPb = full; prefs.patch('keymap', { playback: full }).catch(function () { /* 失敗の知らせは prefs が出す */ }); }
      else if (o.fallbackPlayback && typeof o.fallbackPlayback.save === 'function') o.fallbackPlayback.save(full);
    }
    function commit(tool, pb, before, msg, kind) {
      var toolChanged = JSON.stringify(tool) !== JSON.stringify(self.tool), pbChanged = JSON.stringify(pb) !== JSON.stringify(self.pb);
      self.tool = tool; self.pb = pb; compute();
      if (toolChanged && typeof o.save === 'function') o.save(fullTool(self.tool));
      if (pbChanged) savePb();
      self.note = msg ? { text: msg, kind: kind || '', undo: before } : null;
      paint(); changed();
    }
    function snapshot() { return { tool: copy(self.tool), pb: copy(self.pb) }; }
    function set(id, combo, msg) {
      if (!PB_IDS[id] && !byId[id]) return false;
      combo = combo || '';
      if (combo) { var why = refusal(id, combo); if (why) { say(why, 'warn'); return false; } }
      var before = snapshot(), tool = copy(self.tool), pb = copy(self.pb), taken = [], takenD = [], k;
      if (combo) {
        for (k in self.eff) if (k !== id && self.eff[k] === combo) {
          if (PB_IDS[k]) { pb[k] = ''; taken.push('「' + labelOf(k) + '」(共通の再生キー。スタジオ・編集とも)'); } else { tool[k] = ''; taken.push('「' + labelOf(k) + '」'); }
        }
        var d = (id === 'seekBack' || id === 'seekFwd') ? kmDerived(combo) : '';
        if (d) for (k in self.eff) if (byId[k] && self.eff[k] === d) { tool[k] = ''; takenD.push('「' + labelOf(k) + '」'); }   // Shift つき(5 秒)に使うキーを持っていた操作
      }
      (PB_IDS[id] ? pb : tool)[id] = combo;
      self.lastId = id;
      var lostMsg = [taken.length ? taken.join('・') + 'から ' + keyText(combo) + ' を外しました' : '',
        takenD.length ? takenD.join('・') + 'から ' + keyText(d) + '(' + keyText(combo) + ' + Shift = 5秒に使う)を外しました' : ''].filter(Boolean).join('。');
      commit(tool, pb, before, msg || (lostMsg ? lostMsg + '(未設定になりました)'
        : combo ? '「' + labelOf(id) + '」を ' + keyText(combo) + ' にしました' : '「' + labelOf(id) + '」のキーを外しました'), lostMsg ? 'warn' : '');
      return true;
    }
    function undo() {
      var n = self.note; if (!n || !n.undo) return;
      commit(n.undo.tool, n.undo.pb, null, 'もとに戻しました', '');
    }
    function say(text, kind, keepCap) {
      if (!keepCap && kmCap && kmCap.km === self) kmCap = null;
      self.note = { text: text, kind: kind || '', undo: null, capWarn: !!keepCap };   // 待っている間の注意は、案内の代わりに出す(待つのは続ける)
      paint();
    }
    function changed() { if (typeof o.onChange === 'function') { try { o.onChange(); } catch (e) { report(e && e.message ? e.message : String(e), { where: 'keymap.onChange' }, 'report'); } } }
    function anyCustom() {
      for (var id in self.eff) if ((self.eff[id] || '') !== (defOf(id) || '')) return true;
      return false;
    }
    function rowHtml(id, label, alt, extra) {
      var k = self.eff[id], cap = kmCap && kmCap.km === self && kmCap.id === id, def = defOf(id), lost = self.lost[id];
      var btn = '<button type="button" class="ui-km-key' + (k ? '' : ' none') + (cap ? ' cap' : '') + '" data-km="' + esc(id) + '" aria-label="' +
        esc(label + ' のキー: ' + (k ? keyText(k) : '未設定') + '(押して変える)') + '"' + (cap ? ' aria-pressed="true"' : '') + '>' +
        (cap ? 'キーを押す…' : k ? kmKbd(k) : '未設定') + '</button>';
      var alts = alt ? '<span class="muted">/</span>' + kmKbdText(alt) : '';
      var std = (k || '') !== (def || '') ? '<button type="button" class="btn small ghost ui-km-def" data-km-def="' + esc(id) + '" title="' + esc('標準の ' + (def ? keyText(def) : '未設定') + ' に戻す') +
        '" aria-label="' + esc(label + ' を標準の ' + (def ? keyText(def) : '未設定') + ' に戻す') + '">標準</button>' : '';
      return '<div class="ui-krow ui-km-row" data-km-row="' + esc(id) + '"><span class="ui-kkeys">' + btn + alts + '</span><span class="ui-klabel">' + esc(label) +
        (lost ? '<small class="ui-km-lost">' + esc(keyText(lost.key) + ' は' + lost.why + 'ので外れています') + '</small>' : '') + '</span>' + (extra || '') + std + '</div>';
    }
    function fixedRow(r) {
      var keys = String(r[0]).split(' / ').map(kmKbdText).join('<span class="muted">/</span>'), why = r[2] || o.fixedWhy || '';
      return '<div class="ui-krow ui-km-fixed"><span class="ui-kkeys">' + keys + '</span><span class="ui-klabel">' + esc(r[1]) + '</span>' +
        (why ? '<span class="ui-km-lock" role="img" aria-label="' + esc('変えられません: ' + why) + '" title="' + esc('変えられません: ' + why) + '">' + icon('lock', { size: 13 }) + '</span>' : '') + '</div>';
    }
    function section(title, note, body) {
      return body ? '<section class="ui-kgroup"><h3 class="section-title">' + esc(title) + (note ? ' <span class="hint">' + esc(note) + '</span>' : '') + '</h3>' + body + '</section>' : '';
    }
    function bodyHtml() {
      var extra = typeof o.extra === 'function' ? o.extra : function () { return ''; }, html = o.intro ? '<p class="hint ui-km-intro">' + esc(o.intro) + '</p>' : '', rows = '', i, j;
      html += '<div class="ui-kgrid ui-km-grid">';
      for (i = 0; i < PLAYBACK_ACTIONS.length; i++) rows += rowHtml(PLAYBACK_ACTIONS[i][0], PLAYBACK_ACTIONS[i][2], null, extra(PLAYBACK_ACTIONS[i][0]));
      html += section('共通の再生キー', o.playbackNote || '(スタジオ・編集で同じ)', rows);
      for (i = 0; i < groups.length; i++) {
        rows = '';
        for (j = 0; j < acts.length; j++) if (acts[j].group === groups[i][0]) rows += rowHtml(acts[j].id, acts[j].label, acts[j].alt, extra(acts[j].id));
        for (j = 0; j < fixed.length; j++) if (fixed[j].group === groups[i][0]) rows += fixed[j].rows.map(function (r) { return fixedRow([r[0], r[1], r[2] || fixed[j].why]); }).join('');
        html += section(groups[i][1], '', rows);
      }
      for (j = 0; j < fixed.length; j++) if (!fixed[j].group) html += section(fixed[j].title, fixed[j].note || '', fixed[j].rows.map(function (r) { return fixedRow([r[0], r[1], r[2] || fixed[j].why]); }).join(''));
      html += '</div><div class="ui-km-foot"><button type="button" class="btn small" data-km-reset' + (anyCustom() ? '' : ' disabled title="すべて標準のままです"') + '>すべて標準に戻す</button>' +
        (o.footNote ? '<span class="hint">' + esc(o.footNote) + '</span>' : '') + '</div>';
      return html;
    }
    function noteHtml() {
      var n = self.note, cap = kmCap && kmCap.km === self ? kmCap : null;
      if (cap && !(n && n.capWarn)) return esc('「' + labelOf(cap.id) + '」に割り当てるキーを押してください(Esc で取り消し・Delete で外す)');
      if (!n) return '';
      return esc(n.text) + (n.undo ? ' <button type="button" class="btn small" data-km-undo>戻す</button>' : '');
    }
    function paint() {
      for (var i = 0; i < self.mounts.length; i++) {
        var el = self.mounts[i], a = document.activeElement, had = !!(a && el.contains(a));
        var fid = had ? (a.getAttribute('data-km') || a.getAttribute('data-km-def') || self.lastId) : null;
        var note = el.querySelector('.ui-km-note'), body = el.querySelector('.ui-km-body');
        var n = self.note, cap = kmCap && kmCap.km === self;
        note.className = 'ui-km-note' + (n && n.kind && !(cap && !n.capWarn) ? ' ' + n.kind : '') + (cap ? ' cap' : '');
        note.innerHTML = noteHtml();
        body.innerHTML = bodyHtml();
        if (had && !el.contains(document.activeElement)) {
          var f = (fid && el.querySelector('[data-km="' + fid + '"]')) || el.querySelector('[data-km]');
          if (f) f.focus({ preventScroll: true });
        }
      }
    }
    function startCap(id, el) {
      kmCap = { km: self, id: id, el: el }; self.note = null;
      paint();
      var b = el.querySelector('[data-km="' + id + '"]'); if (b) b.focus({ preventScroll: true });
    }
    function stopCap() { if (kmCap && kmCap.km === self) { kmCap = null; paint(); } }
    function mount(el) {
      if (!el || el.__km) return;
      el.__km = true;
      el.classList.add('ui-km');
      el.innerHTML = '<p class="ui-km-note" role="status" aria-live="polite"></p><div class="ui-km-body"></div>';
      self.mounts.push(el);
      el.addEventListener('click', function (e) {
        var t = e.target && e.target.closest ? e.target.closest('[data-km],[data-km-def],[data-km-undo],[data-km-reset]') : null;
        if (!t || !el.contains(t) || t.disabled) return;
        if (t.hasAttribute('data-km')) startCap(t.getAttribute('data-km'), el);
        else if (t.hasAttribute('data-km-def')) { var id = t.getAttribute('data-km-def'); kmCap = null; set(id, defOf(id), '「' + labelOf(id) + '」を標準の ' + (defOf(id) ? keyText(defOf(id)) : '未設定') + ' に戻しました'); }
        else if (t.hasAttribute('data-km-undo')) undo();
        else if (t.hasAttribute('data-km-reset')) { kmCap = null; commit({}, {}, snapshot(), 'すべて標準に戻しました', ''); }
      });
      el.addEventListener('focusout', function () {   /* 別の所を押したら取り消し(キーを押したときは下の keydown が先に受ける) */
        if (!kmCap || kmCap.km !== self) return;
        setTimeout(function () { var a = document.activeElement; if (kmCap && kmCap.km === self && !(a && a.classList && a.classList.contains('cap'))) stopCap(); }, 0);
      });
      paint();
    }
    /* 共通の再生キーの読み込み: ホームの設定(入口の中)。初回は、ツールに保存していた再生キー(編集の settings.keymap)をホームの設定へ移す */
    function syncPb() {
      var fb = o.fallbackPlayback && typeof o.fallbackPlayback.load === 'function' ? (o.fallbackPlayback.load() || {}) : {};
      if (!prefs.available() || self.prefsPb === null) { self.pb = copy(fb); return; }
      var empty = true, custom = false, k;
      for (k in self.prefsPb) { empty = false; break; }
      for (k in PB_IDS) if (typeof fb[k] === 'string' && fb[k] !== PB_IDS[k][1]) custom = true;
      if (empty && custom) { var pb = {}; for (k in PB_IDS) if (typeof fb[k] === 'string') pb[k] = fb[k]; self.pb = pb; savePb(); return; }
      self.pb = copy(self.prefsPb);
    }
    function loadPrefs() {
      if (!prefs.available()) return;
      prefs.get(['keymap']).then(function (p) {
        var pb = p && p.keymap && p.keymap.playback;
        self.prefsPb = pb && typeof pb === 'object' ? pb : {};
        var was = JSON.stringify(self.eff);
        syncPb(); compute();
        if (JSON.stringify(self.eff) !== was) { paint(); changed(); }
      }, function () { /* 読めなければ今の割り当てのまま */ });
    }
    function reload() {
      self.tool = typeof o.load === 'function' ? copy(o.load() || {}) : {};
      syncPb(); compute(); paint(); changed();
    }
    self.tool = typeof o.load === 'function' ? copy(o.load() || {}) : {};
    syncPb(); compute(); loadPrefs();
    life.onReturn(loadPrefs);   /* 別の窓(スタジオ・編集)で変えた共通の再生キーを、戻ったときに読み直す */
    var api = {
      /* 今効く割り当て { 操作の id: キー }(共通の再生キーを含む。UIKit.keys.playback の keymap にそのまま渡せる) */
      map: function () { return self.eff; },
      key: function (id) { return self.eff[id] || ''; },
      text: function (id) { return self.eff[id] ? keyText(self.eff[id]) : ''; },
      /* キー(comboOf の表記)→ このツールの操作の id か null */
      actionOf: function (combo) { if (!combo) return null; var id = self.used[combo]; return id && byId[id] ? id : null; },
      mount: mount, reload: reload, refusal: refusal,
      set: function (id, combo) { return set(id, combo); },
      /* ツールのキーをまとめて(スタジオのプリセット)。[戻す] つき */
      setMany: function (map, msg) { kmCap = null; commit(copy(map || {}), copy(self.pb), snapshot(), msg || 'キー配置を変えました', ''); },
      clearNote: function () { if (kmCap && kmCap.km === self) kmCap = null; self.note = null; paint(); },
      capturing: function () { return !!(kmCap && kmCap.km === self); }
    };
    self.api = api; self.say = say; self.set = set; self.refusal = refusal;
    return api;
  }
  /* キーを待っている間は、どのキーも「割り当てるキー」として受け取る(捕捉の段階で受けて、ほかの処理 = 一覧・引き出しの Esc・再生のキーなどに渡さない) */
  window.addEventListener('keydown', function (e) {
    var c = kmCap; if (!c) return;
    if (e.isComposing || e.keyCode === 229) return;   // 日本語の変換中は受け取らない
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.repeat) return;
    var km = c.km;
    if (e.key === 'Escape') { kmCap = null; kmEscAt = Date.now(); km.say('取り消しました(キーは変わっていません)', ''); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { kmCap = null; km.set(c.id, ''); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) {
      if (e.key !== 'Control' && e.key !== 'Alt' && e.key !== 'Meta') { km.say('Ctrl・Alt つきのキーは割り当てられません(ブラウザ・タブの切り替えと重なるため)。別のキーを押してください', 'warn', true); }
      return;
    }
    var combo = comboOf(e); if (!combo) return;   // Shift だけを押した段階は、次のキーを待つ
    var why = km.refusal(c.id, combo);
    if (why) { km.say(why + '。別のキーを押すか、Esc で取り消してください', 'warn', true); return; }
    kmCap = null; km.set(c.id, combo);
  }, true);
  document.addEventListener('cancel', function (e) { if (kmCap || Date.now() - kmEscAt < 400) e.preventDefault(); }, true);   // キーを待っている間の Esc で一覧(dialog)を閉じない
  var keymapApi = { create: kmCreate, capturing: function () { return !!kmCap; } };

  /* ---- icon(SVG の線のアイコン。24x24・stroke currentColor・stroke-width 2・角丸) ---- UIKit.icon(name, opts) は文字列を返す。
     <span class="ui-icon" data-icon="play"></span> は読み込み後に中身が入る(UIKit.icon.fill(root)) */
  var ICONS = {
    power: '<path d="M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0"/>',
    play: '<path d="M7 4.5v15l13-7.5z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    back: '<path d="M11 5 4 12l7 7M4 12h16"/>',
    forward: '<path d="M13 5l7 7-7 7M20 12H4"/>',
    'frame-prev': '<path d="M11 6 5 12l6 6M19 5v14"/>',
    'frame-next': '<path d="M13 6l6 6-6 6M5 5v14"/>',
    scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M8.1 8.1 20 20"/>',
    split: '<path d="M12 3v6M12 15v6M5 21l7-7 7 7M5 3l7 7 7-7"/>',
    merge: '<path d="M12 21v-6M12 9V3M5 3l7 7 7-7M5 21l7-7 7 7"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    more: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.2M12 18.8V21M4.2 7l1.9 1.1M17.9 15.9l1.9 1.1M3 12h2.2M18.8 12H21M4.2 17l1.9-1.1M17.9 8.1l1.9-1.1M7 4.2l1.1 1.9M15.9 17.9l1.1 1.9"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    'chevron-right': '<path d="m9 6 6 6-6 6"/>',
    'chevron-left': '<path d="m15 6-6 6 6 6"/>',
    folder: '<path d="M4 7a1 1 0 0 1 1-1h4.5l1.5 2H19a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/>',
    download: '<path d="M12 4v11m0 0-4-4m4 4 4-4M5 19h14"/>',
    undo: '<path d="M9 8 4 12l5 4M4 12h9a5 5 0 1 1 0 10h-2"/>',   /* 弧の半径 5(24 の枠の下にはみ出さない) */
    redo: '<path d="M15 8l5 4-5 4M20 12H11a5 5 0 1 0 0 10h2"/>',
    check: '<path d="m5 13 4 4 10-10"/>',
    alert: '<path d="M12 3 2 20h20zM12 10v4"/><circle cx="12" cy="17" r=".2"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 11h1v6h1"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    home: '<path d="M4 11 12 4l8 7M6 10v9h12v-9"/>',
    film: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M8 4.5v15M16 4.5v15M3.5 9h4.5M3.5 15h4.5M16 9h4.5M16 15h4.5"/>',
    text: '<path d="M5 6h14M12 6v13M9 19h6"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    flag: '<path d="M6 3v18M6 4h11l-2.5 3.5L17 11H6"/>',
    keyboard: '<rect x="3" y="6" width="18" height="12" rx="1.5"/><path d="M7 10h.01M11 10h.01M15 10h.01M17 10h.01M7 14h10"/>',
    'zoom-in': '<circle cx="11" cy="11" r="7"/><path d="M11 8v6M8 11h6M21 21l-4.3-4.3"/>',
    'zoom-out': '<circle cx="11" cy="11" r="7"/><path d="M8 11h6M21 21l-4.3-4.3"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.9-4M4 13a8 8 0 0 0 14.9 4M4 4v5h5M20 20v-5h-5"/>',
    external: '<path d="M9 6H6a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-3M14 4h6v6M10 14 20 4"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M5.5 16H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v.5"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    'mark-in': '<path d="M8 4v16M8 4l8 4v8l-8 4"/>',
    'mark-out': '<path d="M16 4v16M16 4l-8 4v8l8 4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
    lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 14 9 5 9-5M3 8l9 5 9-5"/>',
    wave: '<path d="M2 12h2l1.5-6 3 12 3-16 3 16 3-10 1.5 4H22"/>',
    user: '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>'
  };
  function icon(name, opts) {
    opts = opts || {};
    var size = opts.size || 24;
    return '<svg viewBox="0 0 24 24" width="' + size + '" height="' + size + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      (Object.prototype.hasOwnProperty.call(ICONS, name) ? ICONS[name] : '') + '</svg>';
  }
  icon.fill = function (scopeEl) {
    var scope = scopeEl || document;
    var els = scope.querySelectorAll('[data-icon]');
    for (var i = 0; i < els.length; i++) {
      var name = els[i].getAttribute('data-icon');
      if (Object.prototype.hasOwnProperty.call(ICONS, name)) els[i].innerHTML = icon(name);
    }
  };
  document.addEventListener('DOMContentLoaded', function () { icon.fill(document); });

  /* ---- autorun(まとめて実行の部品)----
     どの入口(ホームの案件・紐づかない文書・スタジオ ①/③・編集の題名の行・履歴)でも、同じ設定の要約1行 +「設定を変える」+ 始める前の見積もり +
     終わったときの知らせ(ボタンつき)。値は1か所: まとめて実行の形・採用数・カットの方法・上書き・失敗したとき = ホームの設定 autorun(UIKit.prefs)、
     パックの出力(fps・縦横・話者の色・音量)は決まった形(10-24 から欄なし。flow/spec.pack_output)。
     状態の言葉もここ(サーバーの stateLabel が正。無いときの予備) */
  var AR_STEP = { wait: '待ち', run: '実行中', done: '済み', skip: '飛ばした', warn: '一部失敗', error: '失敗' };
  var AR_RUN = { queued: '待ち', running: '実行中', done: '済み', error: '失敗', cancelled: '中止', nothing: 'やることがありませんでした' };
  var AR_CUT = { rows: '行から', none: 'カットしない', silence: '無音で削る' };
  var arSeq = 0, arPanels = [], arWatched = {}, arTimer = 0, arState = null;
  function arHomeApi(path, body) { return homeApi(path, { body: body, fail: httpCodeText }); }
  /* ---- flow ---- 欄 → ② の口 POST api/flow/submit の本文 {envelope, spec}(封筒 = src/flow/envelope.py の版 2・spec = 束の差分)。
     Python の src/flow/order.py の order と同じ形(画面が使う欄だけ)。f: {kind: 'url'|'docs'|'file', videoId, docId, path, title,
     fresh: {title, channel}(まだスタジオに無い配信)・marks: [マークの id](このマークだけ。from は 'export')・from: null|'export'・upto: 'pack'|'transcribe'・
     top(採用する数。url だけ)・streamer(null = 自動・'' = 色なし)・repack(パックがあれば作り直す)・deliver: {origin: 'auto', dir: 届け先 か null}} */
  function flowId() {
    var a = new Uint8Array(5), s = '';
    try { window.crypto.getRandomValues(a); } catch (e) { for (var j = 0; j < a.length; j++) a[j] = Math.floor(Math.random() * 256); }
    for (var i = 0; i < a.length; i++) s += (a[i] < 16 ? '0' : '') + a[i].toString(16);
    return s;   /* 10 桁の 16 進 = 実行の id にもなる */
  }
  function flowOrder(f) {
    f = f || {};
    var kind = f.kind === 'docs' || f.kind === 'file' ? f.kind : 'url', title = String(f.title || '').slice(0, 120), inp;
    if (kind === 'url') {
      inp = { videoId: String(f.videoId || ''), title: title };
      if (f.fresh) inp.fresh = { title: String(f.fresh.title || '').slice(0, 120), channel: String(f.fresh.channel || '').slice(0, 100) };
      if (f.marks && f.marks.length) inp.marks = f.marks.slice();
    } else if (kind === 'docs') inp = { docId: String(f.docId || ''), title: title };
    else inp = { path: String(f.path || ''), title: title };
    var env = { id: f.id || flowId(), kind: kind, input: inp, specVersion: 2 };
    var d = f.deliver;
    if (d && (d.origin || d.dir)) env.deliver = { origin: d.origin || null, dir: d.dir || null };
    var run = { upto: f.upto === 'transcribe' ? 'transcribe' : 'pack' }, spec = { run: run };
    if (f.from) run.from = f.from;
    if (f.repack) run.repack = true;
    if (kind === 'url' && f.top != null) spec.adopt = { top: Math.round(+f.top) };
    if (f.streamer != null) spec.hints = { streamer: String(f.streamer) };
    return { envelope: env, spec: spec };
  }
  /* 同じ指定でもう一度(やり直す)= 新しい id の封筒 */
  function flowAgain(o) {
    var env = {};
    for (var k in o.envelope) if (Object.prototype.hasOwnProperty.call(o.envelope, k)) env[k] = o.envelope[k];
    env.id = flowId();
    return { envelope: env, spec: o.spec };
  }
  var flow = { order: flowOrder, again: flowAgain };
  function arLoad() {
    var pr = prefs.available() ? prefs.get(['autorun']).then(function (p) { return p.autorun || {}; }, function () { return {}; }) : Promise.resolve({});
    return pr.then(function (a) {
      arState = { mode: a.mode || null, top: +a.top || 3, cut: AR_CUT[a.cut] ? a.cut : 'rows', overwrite: a.overwrite === true, onFail: a.onFail === 'stop' ? 'stop' : 'next' };
      return arState;
    });
  }
  function arSummary(st, kind) {
    if (!st) return '';
    var bits = [];
    if (kind === 'new' || kind === 'video') bits.push('採用 ' + st.top);   // まとめて実行の形は解析から全部だけ(10-19)
    bits.push(AR_CUT[st.cut]);
    bits.push(st.overwrite ? 'パックがあれば作り直す' : 'パックがあれば飛ばす');
    bits.push(st.onFail === 'stop' ? '失敗したら止める' : '失敗したら次へ');
    return bits.join(' ・ ');
  }
  function arRepaint() {
    arPanels = arPanels.filter(function (p) { return p.el.isConnected; });
    for (var i = 0; i < arPanels.length; i++) arPanels[i].paint();
  }
  function arSave(where, values) {   /* ホームの設定 autorun(失敗は UIKit.prefs が知らせる) */
    return prefs.patch('autorun', values).then(function () { return arLoad(); }).then(function () { arRepaint(); try { document.dispatchEvent(new CustomEvent('ui-autorun-settings', { detail: arState })); } catch (e) {} },
      function () {});
  }
  function arEl(tag, attrs, text) {
    var el = document.createElement(tag);
    for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) el.setAttribute(k, attrs[k]);
    if (text != null) el.textContent = text;
    return el;
  }
  function arSelect(opts, value) {
    var s = arEl('select');
    for (var i = 0; i < opts.length; i++) { var o = arEl('option', { value: opts[i][0] }, opts[i][1]); s.appendChild(o); }
    s.value = String(value);
    return s;
  }
  function arField(label, control, hint) {
    var f = arEl('label', { 'class': 'ui-ar-f' });
    f.appendChild(arEl('span', { 'class': 'ui-ar-l' }, label));
    f.appendChild(control);
    if (hint) f.appendChild(arEl('span', { 'class': 'ui-ar-h' }, hint));
    return f;
  }
  /* 設定の欄(ポップオーバーの中身)。値を変えたらすぐ保存(どこで変えても全部の入口の既定) */
  function arForm(kind, opts) {
    var st = arState, box = arEl('div', { 'class': 'ui-ar-form' });
    if (kind === 'new' || kind === 'video') {
      var t = arEl('input', { type: 'number', min: '1', max: '20', step: '1' }); t.value = String(st.top); t.style.width = '5em';
      t.addEventListener('change', function () { var n = Math.round(+t.value); if (n >= 1 && n <= 20) arSave('prefs', { top: n }); });
      box.appendChild(arField('採用する数(解析から全部)', t));
    }
    var c = arSelect([['rows', '行から(文字起こしの行を残す)'], ['none', 'カットしない(動画全体)'], ['silence', '無音で削る']], st.cut);
    c.addEventListener('change', function () { arSave('prefs', { cut: c.value }); });
    box.appendChild(arField('カットの方法', c, 'カットを決めてある文書は、そのカットのとおり。細かい値は「編集」の 2 カット で'));
    box.appendChild(arEl('p', { 'class': 'ui-ar-h' }, 'パックは決まった形(30fps・縦 1080×1920・音量 -14 LUFS・話者の色)で作ります'));
    var ow = arEl('input', { type: 'checkbox' }); ow.checked = st.overwrite;
    ow.addEventListener('change', function () { arSave('prefs', { overwrite: ow.checked }); });
    var ol = arEl('label', { 'class': 'ui-ar-c' }); ol.appendChild(ow); ol.appendChild(document.createTextNode('パックがあれば作り直す(上書き)'));
    box.appendChild(ol);
    var of = arSelect([['next', '残りを続ける'], ['stop', 'そこで止める']], st.onFail);
    of.addEventListener('change', function () { arSave('prefs', { onFail: of.value }); });
    box.appendChild(arField('1本が失敗したとき', of));
    return box;
  }
  /* 1 本ずつの見積もりを足す(段の鍵ごと。どれかが読めなければ null = 見積もりなしで始める) */
  function arSumEstimates(list) {
    if (!list.length) return null;
    for (var i = 0; i < list.length; i++) if (!list[i] || !list[i].steps) return null;
    if (list.length === 1) return list[0];
    var order = [], by = {}, reasons = [], nothing = true, total = 0;
    list.forEach(function (e) {
      nothing = nothing && !!e.nothing;
      if (e.reason && reasons.indexOf(e.reason) < 0) reasons.push(e.reason);
      total += +e.total || 0;
      e.steps.forEach(function (s) {
        if (!by[s.key]) { by[s.key] = { key: s.key, label: s.label, count: 0, note: s.note || '' }; order.push(s.key); }
        by[s.key].count = by[s.key].count == null || s.count == null ? null : by[s.key].count + s.count;
      });
    });
    return { steps: order.map(function (k) { return by[k]; }), total: total, nothing: nothing, reason: nothing ? reasons.join('・') : '' };
  }
  function arEstimateText(e) {
    if (!e || !e.steps) return '';
    return e.steps.map(function (s) { return s.label + ' ' + (s.count == null ? 'あとで決まる' : s.count + ' 本'); }).join(' → ');
  }
  function arDocHref(run) {
    var id = run.docId || (run.docs && run.docs[0]);   /* 文書の実行はその文書・配信の実行は最初に文字起こし・パックした文書 */
    return id ? '/cases?d=' + encodeURIComponent(id) + '#proof' : '';   /* 案件の画面の校正 */
  }
  function arOpen(href) { if (href) location.href = href; }   /* 同じ窓で移る(窓・画面を増やさない。S-15) */
  function arFinished(run, again) {
    var title = run.title ? '「' + run.title + '」' : '';
    if (run.state === 'cancelled') return;
    if (run.state === 'error') {
      toastFn(title + 'のまとめて実行が止まりました: ' + (run.error || ''), { kind: 'err', ms: 0,
        action: again ? { label: 'やり直す', fn: again } : null });
      return;
    }
    if (run.nothing) { toastFn(title + (title ? ': ' : '') + (run.message || AR_RUN.nothing), { kind: 'info', ms: 8000 }); return; }
    var pk = null, warn = false;
    for (var i = 0; i < (run.steps || []).length; i++) { if (run.steps[i].key === 'pack') pk = run.steps[i]; if (run.steps[i].state === 'warn') warn = true; }
    var msg = title + 'のまとめて実行が終わりました' + (pk && pk.detail ? '(' + pk.detail.split('。')[0] + ')' : '') + (warn ? '。一部失敗しました(詳しくは進み具合の欄)' : '');
    var href = arDocHref(run);
    toastFn(msg, { kind: warn ? 'info' : 'ok', ms: 0, action: href ? { label: '校正を始める', fn: function () { arOpen(href); } } : null });
  }
  function arPoll() {
    arTimer = 0;
    var ids = Object.keys(arWatched);
    if (!ids.length) return;
    arHomeApi('api/flow/runs').then(function (j) {
      var runs = j.runs || [];
      for (var i = 0; i < ids.length; i++) {
        var r = null;
        for (var k = 0; k < runs.length; k++) if (runs[k].id === ids[i]) r = runs[k];
        if (!r) { delete arWatched[ids[i]]; continue; }
        if (r.state !== 'queued' && r.state !== 'running') { var again = arWatched[ids[i]]; delete arWatched[ids[i]]; arFinished(r, again); }
      }
    }).catch(function () {}).then(function () { if (Object.keys(arWatched).length) arTimer = setTimeout(arPoll, 2500); });
  }
  var autorun = {
    STEP: AR_STEP, RUN: AR_RUN, CUT: AR_CUT,
    stepLabel: function (s) { return (s && s.stateLabel) || AR_STEP[s && s.state] || (s && s.state) || ''; },
    runLabel: function (r) { return (r && r.stateLabel) || AR_RUN[r && r.nothing && r.state === 'done' ? 'nothing' : r && r.state] || (r && r.state) || ''; },
    load: arLoad,
    state: function () { return arState; },
    summary: arSummary,
    /* el に「要約1行 +『設定を変える』」を描く。opts: {kind: 'video'|'docs'|'new'}(まとめて実行の形は解析から全部だけ = 形を選ぶ欄は無い。v36) */
    panel: function (el, opts) {
      if (!el) return null;
      opts = opts || {};
      var kind = opts.kind || 'video', id = 'ui-ar-' + (++arSeq);
      el.classList.add('ui-autorun');
      el.innerHTML = '';
      var sum = arEl('span', { 'class': 'ui-ar-sum', id: id + '-sum' });
      var det = arEl('details', { 'class': 'ui-pop ui-ar-pop' });
      var s = arEl('summary', { 'class': 'btn small ghost', 'aria-describedby': id + '-sum' }, '設定を変える');
      var body = arEl('div', { 'class': 'ui-pop-body ui-ar-body', 'data-align': opts.align || 'left' });
      det.appendChild(s); det.appendChild(body);
      el.appendChild(sum); el.appendChild(det);
      var p = { el: el, paint: function () { sum.textContent = arState ? arSummary(arState, kind) : '…'; } };
      det.addEventListener('toggle', function () {
        if (!det.open) return;
        body.textContent = '読み込んでいます…';
        /* 開いた直後(fitPop)は「読み込んでいます…」の 1 行の大きさで置き場所を決めるので、中身を入れたらもう一度置き直す
           (置き直さないと下にはみ出したままになる) */
        arLoad().then(function () { body.innerHTML = ''; body.appendChild(arForm(kind, opts)); p.paint(); if (det.open) fitPop(det); });   /* 文書に入れてから音量の欄に値を入れる(M3) */
      });
      arPanels.push(p);
      if (arState) p.paint(); else arLoad().then(arRepaint, function () {});
      return p;
    },
    /* 始める: orders = UIKit.flow.order の {envelope, spec} の並び(1 つでもよい)。opts.estimate(既定 true)= 1 本ずつ見積もって足す
       (api/flow/estimate)→ やることが 0 なら始めない → 1 本ずつ api/flow/submit → 終わるまで見て知らせる。
       -> Promise<{run: 1 本目, runs, skipped: [{id, title, reason}]} | null(やることが無い)>。全部断られたら 1 本目の理由で reject */
    start: function (orders, opts) {
      orders = Array.isArray(orders) ? orders : [orders];
      opts = opts || {};
      var est = opts.estimate === false ? Promise.resolve(null)
        : Promise.all(orders.map(function (o) { return arHomeApi('api/flow/estimate', o).catch(function () { return null; }); })).then(arSumEstimates);
      return est.then(function (e) {
        if (e && e.nothing) { toastFn('やることがありません: ' + (e.reason || ''), { kind: 'info', ms: 8000 }); return null; }
        var runs = [], skipped = [], errs = [];
        var chain = orders.reduce(function (p, o) {
          return p.then(function () {
            return arHomeApi('api/flow/submit', o).then(function (j) {
              if (!j || !j.run) return;
              runs.push(j.run);
              arWatched[j.run.id] = function () { autorun.start([flowAgain(o)], opts); };
            }, function (er) {
              errs.push(er);
              skipped.push({ id: o.envelope.input.videoId || o.envelope.input.docId || o.envelope.id, title: o.envelope.input.title || '', reason: er && er.message || String(er) });
            });
          });
        }, Promise.resolve());
        return chain.then(function () {
          if (!runs.length && errs.length) throw errs[0];
          if (runs.length && !arTimer) arTimer = setTimeout(arPoll, 2500);
          var what = runs.length === 1 ? '「' + runs[0].modeLabel + '」' : runs.length + ' 本のまとめて実行';
          if (runs.length) toastFn(what + 'を始めました' + (e ? '(' + arEstimateText(e) + ')' : ''), { kind: 'ok', ms: 6000 });
          if (skipped.length) toastFn(skipped.length + ' 本は始めませんでした: ' + skipped[0].reason, { kind: 'info', ms: 8000 });
          return { run: runs[0] || null, runs: runs, skipped: skipped };
        });
      });
    },
    watch: function (runId, again) { arWatched[runId] = again || null; if (!arTimer) arTimer = setTimeout(arPoll, 2500); },
    estimateText: arEstimateText
  };

  /* ---- restart ---- 版の赤い帯から入口ごと起動し直す。
     取り込んだツールは入口と同じプロセスなので、版を入れ替えるには入口ごと起動し直す(入口の api/ytt/restart-self → home/restart.py)。
     ボタンはホームから開いた画面(合言葉 ytt-token がある)だけ。単体で開いたときは案内の文だけ。
     起動し直したあとは api/ping を数秒ごとに読み、戻ったら再読み込みする(新しい入口は合言葉が変わるので、読み込み直さないと書き込みができない) */
  var RESTART_POLL = 2000, RESTART_TIMEOUT = 90000;
  function restartPing(ms) { return http('api/ping', { timeout: ms, fail: httpCodeText }); }
  /* 頼んで、戻るのを待って、読み込み直す。opts: from(今のサーバーの版)・onState(state, text)('waiting' | 'done' | 'timeout')・
     interval・timeout(ミリ秒。テスト用)・reload(既定 location.reload)。-> Promise<true(読み込み直す) | false(戻らなかった)>。断られたら reject(理由の文) */
  function restartRun(opts) {
    opts = opts || {};
    var interval = +opts.interval || RESTART_POLL, limit = +opts.timeout || RESTART_TIMEOUT;
    var say = typeof opts.onState === 'function' ? opts.onState : function () {};
    var from = opts.from == null ? null : String(opts.from);
    var reload = typeof opts.reload === 'function' ? opts.reload : function () { location.reload(); };
    return yttPost('restart-self', opts.force ? { force: true } : {}).then(function (j) {
      /* 入口からの知らせ(notice。まとめて実行の待ち・実行中の N 件は起動し直したあとに続きから進む)も帯に出す(黙って止めたように見せない) */
      var note = j && j.notice ? String(j.notice) : '';
      say('waiting', '起動し直しています…(戻ったら画面を読み込み直します)' + (note ? '。' + note : ''));
      return new Promise(function (resolve) {
        var t0 = Date.now(), sawDown = false;
        /* 戻った = 一度答えなくなってから答えた、か、版が変わった(古い入口は後始末の間もしばらく答える) */
        function tick() {
          restartPing(Math.max(1000, Math.min(interval, 5000))).then(function (j) {
            var v = j && j.version != null ? String(j.version) : '';
            if (sawDown || (from !== null && v && v !== from)) { say('done', '起動し直しました。読み込み直しています…'); resolve(true); reload(); return; }
            next();
          }, function () { sawDown = true; next(); });
        }
        function next() {
          if (Date.now() - t0 > limit) { say('timeout', 'ホームが戻ってきませんでした。start.bat をダブルクリックして起動してください'); resolve(false); return; }
          setTimeout(tick, interval);
        }
        setTimeout(tick, interval);
      });
    });
  }
  /* 帯(ツールの .errbar など)に版の違いと「起動し直す」を出す。-> el */
  function restartBand(el, pageVersion, serverVersion, opts) {
    if (!el) return null;
    opts = opts || {};
    var head = '画面(v' + pageVersion + ')とサーバー(v' + serverVersion + ')の版が違います。';
    el.textContent = '';
    var msg = document.createElement('span'); msg.className = 'ui-restart-msg';
    el.appendChild(msg);
    el.hidden = false;
    if (!token()) { msg.textContent = head + '黒い画面を閉じて、起動し直してください'; el.removeAttribute('data-ui-restart'); return el; }
    msg.textContent = head + '処理が終わったら自動で起動し直します(今すぐ: [起動し直す])';
    el.setAttribute('data-ui-restart', 'ready');
    var b = document.createElement('button'); b.type = 'button'; b.className = 'btn small ui-restart-btn'; b.textContent = '起動し直す';
    el.appendChild(b);
    function send(force) {
      b.disabled = true;
      el.setAttribute('data-ui-restart', 'sending');
      msg.textContent = '起動し直すように頼んでいます…';
      restartRun({ from: serverVersion, interval: opts.interval, timeout: opts.timeout, reload: opts.reload, force: force, onState: function (state, text) {
        el.setAttribute('data-ui-restart', state);
        msg.textContent = text;
        if (state === 'timeout') b.hidden = true;   // 古い入口はもういない(合言葉も古い)。もう一度押しても届かない
      } }).catch(function (e) {   // 断られた(実行中の処理がある・終了の途中など)・届かなかった: 理由を出して、もう一度押せるように
        el.setAttribute('data-ui-restart', 'refused');
        msg.textContent = head + (e && e.message ? e.message : '起動し直せませんでした');
        b.disabled = false;
        /* ライブの録画中(入口の 409 live): 止まることを言って確かめる。既定は待つ(安全な方) */
        if (!force && e && e.body && e.body.error === 'live') {
          dialogConfirm({ title: '録画が止まります', body: e.message, ok: '録画を止めて起動し直す', cancel: '録画が終わるまで待つ', danger: true })
            .then(function (ok) { if (ok) send(true); });
        }
      });
    }
    b.addEventListener('click', function () { send(false); });
    return el;
  }
  var restart = {
    available: function () { return !!token(); },
    /* 版が違えば帯を出して true。同じなら何もしないで false(ツールの起動時の /api/ping のあとに呼ぶ) */
    check: function (el, pageVersion, serverVersion, opts) {
      if (String(pageVersion) === String(serverVersion)) return false;
      restartBand(el, pageVersion, serverVersion, opts);
      return true;
    },
    band: restartBand,
    run: restartRun
  };

  /* ==== 時刻の欄 UIKit.timebox。使い方は README.md の「v11」 ====
     時刻(1:23:45)を「:」を打たずに入れる欄。動き:
       欄は1つ。時・分・秒 のどれか1つが選ばれていて(反転)、数字は 時(1桁)→ 分(2桁)→ 秒(2桁)の順に入る(分・秒の最初が 6〜9 なら1桁で次へ)。
       ← → で場所を選ぶ(クリックでも)・↑ ↓ で選んだ単位を ±1(Shift で ±10)・BackSpace = 選んだ所を 0(もう 0 なら左へ)・Delete = 空に・
       貼り付け(1:23:45 / 83:45 / 1h23m45s。youtube: true のときだけ YouTube の URL の t= も読む)。
     形は3つ: 時:分:秒(既定)/ 時:分:秒.0.1秒(tenths)/ 分:秒.0.1秒(short。短い切り抜きの字幕の行など。1時間を超えたら分が 60 以上)。
     入力欄(input)ではなく、フォーカスできる要素に自分で描く: 文字を打ち込めない・日本語入力に数字のキーを取られない・選んだ所をアクセントの色で見せられる。
     値は秒(tenths・short のときは 0.1 秒刻み)。入っていなければ null。変わるたびに要素へ 'ui-time'(detail: {value})、
     欄を離れた・Enter を押したときに値が変わっていれば 'ui-time-commit'(input の change に当たる。detail: {value, via: 'enter'|'blur', to: 移った先の要素 | null})、
     読めない貼り付けは 'ui-time-reject'(detail: {reason})。
     ホイール(opt.wheel / data-ui-time-wheel)・add(秒)・貼り付けの前の口 'ui-time-beforepaste'(detail: {text}。取り消せる)・動いた単位の光り(.ui-time-flash)は README.md の「v29」 */
  var TB_MAX = 99 * 3600 + 59 * 60 + 59;   // 秒
  /* 形ごとの区切り: unit = その場所の 1 が 0.1 秒いくつ分か。先頭は桁数を決めない(1桁打ったら次へ)・2桁の所は 0 を付けて出す・0.1 秒は1桁 */
  var TB_FORMS = {
    hms: [{ unit: 36000, name: '時' }, { unit: 600, name: '分', two: true }, { unit: 10, name: '秒', two: true }],
    tenths: [{ unit: 36000, name: '時' }, { unit: 600, name: '分', two: true }, { unit: 10, name: '秒', two: true }, { unit: 1, name: '0.1秒' }],
    short: [{ unit: 600, name: '分' }, { unit: 10, name: '秒', two: true }, { unit: 1, name: '0.1秒' }]
  };
  function tbForm(f) { return TB_FORMS[f === true ? 'tenths' : f] || TB_FORMS.hms; }
  function tbParts(t10, form) {
    var out = [];
    for (var i = 0; i < form.length; i++) out.push(i === 0 ? Math.floor(t10 / form[0].unit) : Math.floor(t10 % form[i - 1].unit / form[i].unit));
    return out;
  }
  function tbPad(n) { return (n < 10 ? '0' : '') + n; }
  function tbText(t10, form) {
    var p = tbParts(t10, form), out = '';
    for (var i = 0; i < form.length; i++) out += (i ? (form[i].unit === 1 ? '.' : ':') : '') + (form[i].two ? tbPad(p[i]) : String(p[i]));
    return out;
  }
  /* 秒 → 文字。form: 省略 = 1:23:45 / true・'tenths' = 0:01:23.5 / 'short' = 1:23.5 */
  function tbFormat(sec, form) { return tbText(Math.round((Number(sec) || 0) * 10), tbForm(form)); }
  /* 貼り付けた文字 → 秒(読めなければ null)。数字だけ(「5025」)は 秒なのか 時分秒なのか決められないので読まない */
  function tbParse(text, opt) {
    opt = opt || {};
    var s = String(text == null ? '' : text).trim(), m;
    if (!s || s.length > 2048) return null;
    function units(v, bare) {
      if (/^\d+$/.test(v)) return bare ? Number(v) : null;
      var x = /^(?:(\d{1,3})h)?(?:(\d{1,4})m)?(?:(\d{1,6})s?)?$/i.exec(v);
      return x && v ? (Number(x[1]) || 0) * 3600 + (Number(x[2]) || 0) * 60 + (Number(x[3]) || 0) : null;
    }
    var sec = null;
    if (opt.youtube && (m = /(?:^|[?&#\s])t=([0-9hms]+)/i.exec(s))) sec = units(m[1], true);
    else if ((m = /^(\d{1,3})[:：](\d{1,2})(?:[:：](\d{1,2}))?(?:\.(\d))?$/.exec(s))) {
      sec = m[3] !== undefined ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) : Number(m[1]) * 60 + Number(m[2]);
      if (m[4] && opt.tenths) sec += Number(m[4]) / 10;
    } else if (!/^https?:/i.test(s)) sec = units(s, false);
    return sec === null || sec > TB_MAX ? null : sec;
  }
  function attachTime(el, opt) {
    if (!el) return null;
    if (el.__uiTime) return el.__uiTime;
    opt = opt || {};
    var formName = opt.short || el.hasAttribute('data-ui-time-short') ? 'short' : (opt.tenths !== undefined ? opt.tenths : el.hasAttribute('data-ui-time-tenths')) ? 'tenths' : 'hms';
    var form = TB_FORMS[formName], fine = formName !== 'hms', last = form.length - 1;
    var youtube = opt.youtube !== undefined ? !!opt.youtube : el.hasAttribute('data-ui-time-youtube');
    var wheelOn = opt.wheel !== undefined ? !!opt.wheel : el.hasAttribute('data-ui-time-wheel');   // ホイールで単位を ±1
    var maxSec = Number(opt.max !== undefined ? opt.max : el.getAttribute('data-ui-time-max')) || TB_MAX;
    var v = 0, has = false, seg = 0, half = false;   // v = 0.1 秒の数。half = 2桁の所の1桁目だけ打った所
    var baseV = 0, baseHas = false;                  // 欄に入ったとき(か最後に確定したとき)の値。離れたときに違えば ui-time-commit
    el.classList.add('ui-time');
    el.setAttribute('role', 'spinbutton');
    if (!el.hasAttribute('tabindex')) el.tabIndex = 0;
    if (!el.getAttribute('aria-label')) el.setAttribute('aria-label', '時刻');
    if (!el.title) el.title = formName === 'short' ? '数字だけ打つ(1235 → 1:23.5)。← → で 分・秒・0.1秒 を選び、↑ ↓ で動かす'
      : '数字だけ打つ(12345 → 1:23:45)。← → で 時・分・秒 を選び、↑ ↓ で動かす。Delete で空に';
    function clamp(x) { return Math.max(0, Math.min(Math.round(maxSec * 10), Math.round(x))); }
    function disabled() { return el.getAttribute('aria-disabled') === 'true'; }
    function fire(name, detail) { try { el.dispatchEvent(new CustomEvent(name, { bubbles: true, detail: detail })); } catch (e) { /* 古いブラウザ */ } }
    /* 取り消せる知らせ。false = 画面が preventDefault した */
    function ask(name, detail) { try { return el.dispatchEvent(new CustomEvent(name, { bubbles: true, cancelable: true, detail: detail })); } catch (e) { return true; } }
    function draw() {
      var p = tbParts(v, form), on = document.activeElement === el, shown = has || on, html = '';
      for (var i = 0; i <= last; i++) {
        if (i) html += '<span class="ui-time-sep" aria-hidden="true">' + (form[i].unit === 1 ? '.' : ':') + '</span>';
        html += '<span class="ui-time-seg' + (on && i === seg ? ' on' : '') + '" data-seg="' + i + '">' + (shown ? (form[i].two ? tbPad(p[i]) : String(p[i])) : (form[i].two ? '--' : '-')) + '</span>';
      }
      el.innerHTML = html;
      el.classList.toggle('ui-time-empty', !has);   // .empty は「空の状態の箱」の部品なので使わない
      el.setAttribute('aria-valuenow', String(v / 10));
      el.setAttribute('aria-valuetext', has ? tbText(v, form) + (on ? '(' + form[seg].name + 'を選択中)' : '') : '未入力');
    }
    function tell() { fire('ui-time', { value: has ? v / 10 : null }); }
    /* 値が動いた単位を一瞬光らせる(.ui-time-flash。400ms で消す)。draw のあとに当てる(描き直すと span が作り直されるため) */
    var flashT = null;
    function flash(i) {
      var s = el.querySelector('.ui-time-seg[data-seg="' + i + '"]');
      if (!s) return;
      clearTimeout(flashT);
      s.classList.add('ui-time-flash');
      flashT = setTimeout(function () { s.classList.remove('ui-time-flash'); }, 400);
    }
    /* ホイールのとき、マウスの下の単位(空の欄でも、その場所)。区切りの上なら一番近い単位 */
    function segAt(e) {
      var t = e.target && e.target.closest ? e.target.closest('.ui-time-seg') : null;
      if (t) return Number(t.getAttribute('data-seg'));
      var segs = el.querySelectorAll('.ui-time-seg'), best = 0, bd = Infinity;
      for (var i = 0; i < segs.length; i++) {
        var r = segs[i].getBoundingClientRect(), d = e.clientX < r.left ? r.left - e.clientX : e.clientX > r.right ? e.clientX - r.right : 0;
        if (d < bd) { bd = d; best = i; }
      }
      return best;
    }
    /* 今の値に sec 秒を足す(空なら 0 から・0 未満にならない・上限まで)。足したら ui-time と ui-time-commit(via: 'add')・動いた一番上の単位を光らせる */
    function addSec(sec) {
      if (sec === null || sec === undefined || sec === '' || !isFinite(Number(sec))) return;
      var wasV = v, wasHas = has, p0 = tbParts(v, form), nv = clamp(v + Math.round(Number(sec) * 10)), p1 = tbParts(nv, form), top = -1;
      for (var j = 0; j <= last; j++) if (p0[j] !== p1[j]) { top = j; break; }
      v = nv; has = true; half = false;
      draw();
      if (top >= 0) flash(top);
      if (wasV !== v || wasHas !== has) tell();
      commit('add', null);
    }
    function commit(via, to) {
      if (baseV === v && baseHas === has) return;
      baseV = v; baseHas = has;
      /* via = 'enter' | 'blur' | 'add'、to = 離れて移った先(画面を描き直す側が、フォーカスを奪い返さずに移った先へ戻せるように) */
      fire('ui-time-commit', { value: has ? v / 10 : null, via: via, to: to || null });
    }
    function setPart(i, n) {
      var p = tbParts(v, form), sum = 0;
      p[i] = n;
      for (var j = 0; j <= last; j++) sum += p[j] * form[j].unit;
      v = clamp(sum);
    }
    function advance() { half = false; if (seg < last) seg++; }
    function digit(d) {
      has = true;
      if (!form[seg].two) { setPart(seg, d); if (seg < last) advance(); }   // 先頭(時・分)と 0.1 秒は1桁。最後の 0.1 秒はその場で打ち直し
      else if (!half) { setPart(seg, d); if (d >= 6) advance(); else half = true; }
      else { setPart(seg, tbParts(v, form)[seg] * 10 + d); advance(); }
    }
    function paste(text) {
      var sec = tbParse(text, { youtube: youtube, tenths: fine });
      if (sec === null) {
        fire('ui-time-reject', { reason: youtube ? '時刻として読めませんでした。YouTube の「現在の時刻の動画の URL をコピー」か、1:23:45 の形を貼ってください' : '時刻として読めませんでした。1:23:45 の形を貼ってください' });
        return false;
      }
      v = clamp(sec * 10); has = true; half = false;
      return true;
    }
    el.addEventListener('keydown', function (e) {
      if (disabled() || e.ctrlKey || e.metaKey || e.altKey) return;
      var k = e.key, before = v, had = has, used = true, lit = -1;
      if (/^[0-9]$/.test(k)) digit(Number(k));
      else if (k === 'ArrowLeft') { seg = Math.max(0, seg - 1); half = false; }
      else if (k === 'ArrowRight') { seg = Math.min(last, seg + 1); half = false; }
      else if (k === 'ArrowUp' || k === 'ArrowDown') { var was = v; has = true; half = false; v = clamp(v + (k === 'ArrowUp' ? 1 : -1) * form[seg].unit * (e.shiftKey ? 10 : 1)); if (v !== was) lit = seg; }
      else if (k === 'Backspace') { if (tbParts(v, form)[seg] === 0 && !half) seg = Math.max(0, seg - 1); else setPart(seg, 0); half = false; }
      else if (k === 'Delete') { v = 0; has = false; seg = 0; half = false; }
      else if (k === 'Enter') { half = false; commit('enter', null); }
      else used = false;
      if (!used) return;
      e.preventDefault(); e.stopPropagation();   // 画面のキー操作(再生・矢印で 1 秒など)に渡さない
      draw();
      if (lit >= 0) flash(lit);
      if (before !== v || had !== has) tell();
    });
    /* ホイール(opt.wheel / data-ui-time-wheel のときだけ)。マウスの下の単位を ±1(Shift で ±10)。この欄の上だけページのスクロールを止める */
    if (wheelOn) el.addEventListener('wheel', function (e) {
      var dy = e.deltaY !== 0 ? e.deltaY : e.deltaX;   // Shift + ホイールで横に来るブラウザがあるので
      if (disabled() || !dy) return;
      e.preventDefault();
      var i = segAt(e), before = v, had = has;
      seg = i; half = false; has = true;
      v = clamp(v + (dy < 0 ? 1 : -1) * form[i].unit * (e.shiftKey ? 10 : 1));
      draw();
      if (before !== v) flash(i);
      if (before !== v || had !== has) tell();
    }, { passive: false });
    el.addEventListener('paste', function (e) {
      if (disabled()) return;
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData('text');
      if (!ask('ui-time-beforepaste', { text: text })) return;   // 画面が preventDefault したら値も ui-time-reject も変えない
      var before = v, had = has;
      if (paste(text)) { draw(); if (before !== v || had !== has) tell(); fire('ui-time-paste', { text: text }); }
    });
    el.addEventListener('copy', function (e) { if (has && e.clipboardData) { e.clipboardData.setData('text/plain', tbText(v, form)); e.preventDefault(); } });
    el.addEventListener('focus', function () { seg = 0; half = false; baseV = v; baseHas = has; draw(); });   // 欄に入ったら、左の端から打ち始める
    el.addEventListener('blur', function (e) { half = false; draw(); commit('blur', e.relatedTarget); });
    el.addEventListener('mousedown', function (e) {
      if (disabled()) { e.preventDefault(); return; }
      var t = e.target && e.target.closest ? e.target.closest('.ui-time-seg') : null, pick = t && has ? Number(t.getAttribute('data-seg')) : 0;
      if (document.activeElement !== el) el.focus();   // focus で左の端に戻るので、そのあとでクリックした所を選ぶ
      seg = pick; half = false; draw();
      e.preventDefault();
    });
    var api = el.__uiTime = {
      el: el,
      get: function () { return has ? v / 10 : null; },
      set: function (sec) {   // null・'' で空に。画面から入れたときは 'ui-time'・'ui-time-commit' を出さない(入れた側が知っているため)
        if (sec === null || sec === undefined || sec === '' || isNaN(Number(sec))) { v = 0; has = false; } else { v = clamp(Number(sec) * 10); has = true; }
        half = false; baseV = v; baseHas = has; draw();
      },
      text: function () { return has ? tbText(v, form) : ''; },
      add: function (sec) { addSec(sec); return has ? v / 10 : null; },   // 今の値に足す(空なら 0 から)
      focus: function () { el.focus(); }
    };
    var init = opt.value !== undefined ? opt.value : el.getAttribute('data-ui-time');
    api.set(init === null || init === '' ? null : init);
    return api;
  }
  var timebox = {
    attach: attachTime,
    /* 入れ物の中の [data-ui-time] を全部(画面を innerHTML で描き直したあとに呼ぶ) */
    attachAll: function (root) {
      var list = (root || document).querySelectorAll('[data-ui-time]');
      for (var i = 0; i < list.length; i++) attachTime(list[i]);
    },
    /* 要素を作って返す(画面をあとから作るとき)。opt: {tenths, short, youtube, max, value, label} */
    create: function (opt) {
      opt = opt || {};
      var el = document.createElement('span');
      if (opt.label) el.setAttribute('aria-label', opt.label);
      attachTime(el, opt);
      return el;
    },
    get: function (el) { var a = attachTime(el); return a ? a.get() : null; },
    set: function (el, sec) { var a = attachTime(el); if (a) a.set(sec); },
    /* 今の値に sec 秒を足す(欄の値を返す。ホイール・↑ ↓ と同じく 'ui-time'・'ui-time-commit'(via: 'add')を出す) */
    add: function (el, sec) { var a = attachTime(el); return a ? a.add(sec) : null; },
    parse: tbParse,
    format: tbFormat
  };
  document.addEventListener('DOMContentLoaded', function () { timebox.attachAll(document); });

  /* ---- liveBadge(ヘッダーの「録画中」の札)---- 線 D のリアルタイム切り抜き(notes:plan/line-d-live-clipping.md の 0-8)。
     入口の POST api/ytt/live {op: "status"} → {enabled, recordings: [{recorder, id, title, state, active, seconds, endedAt, url}]}(合言葉つき。入口が受け持つ)を
     オンのときは 10 秒ごと・オフ(enabled:false・404 などの 4xx)のときは 60 秒ごとに問い合わせ、appnav のあるヘッダー(.ui-header-actions の先頭)に札を出す。
     録画が無い・機能がオフ・合言葉が無いページ(入口を通さない単独起動)では何も作らない(場所も取らない)。隠れているタブは問い合わせない(戻ったらすぐ)。
     札を押すと一覧(録画ごとに 題・状態・録画済みの時間・「開く」・「停止」(二度押し))。一覧は差分で直す(10 秒ごとに作り直すと、押そうとしたボタンや二度押しの途中が消える)。
     知らせ(UIKit.toast): active だった録画が active でなくなった・recording → reconnecting になったとき。ページを開いた最初の1回では出さない */
  var LIVE_ON_MS = 10000, LIVE_OFF_MS = 60000, LIVE_ACTIVE = { waiting: 1, recording: 1, reconnecting: 1 };
  var LIVE_STATE_LABEL = { waiting: '配信待ち', recording: '録画中', reconnecting: 'つなぎ直し中', stopped: '停止', ended: '録画終了', error: 'エラー' };
  var live = { last: null, at: 0, prev: null, timer: 0, inflight: null, nextMs: LIVE_ON_MS, fails: 0, started: false, subs: [], openFn: null, els: null, rows: {}, open: false, tick: 0 };

  function liveStr(v) { return v == null ? '' : String(v); }
  function liveKey(r) { return r.recorder + '/' + r.id; }
  function liveTitle(r) { return r.title || r.url || r.id; }
  function liveNorm(j) {   // 外から来る値は形をそろえて持つ(文字は textContent でしか使わない)
    var out = { enabled: !!(j && j.enabled), recordings: [] };
    if (!out.enabled || !j.recordings || !j.recordings.length) return out;
    for (var i = 0; i < j.recordings.length; i++) {
      var r = j.recordings[i];
      if (!r || typeof r !== 'object' || r.id == null) continue;
      out.recordings.push({ recorder: liveStr(r.recorder), id: liveStr(r.id), title: liveStr(r.title), url: liveStr(r.url), state: liveStr(r.state),
        active: typeof r.active === 'boolean' ? r.active : !!LIVE_ACTIVE[r.state], seconds: +r.seconds > 0 ? +r.seconds : 0, endedAt: r.endedAt == null ? null : r.endedAt });
    }
    return out;
  }
  function liveNotify(cur) {
    if (!live.prev) return;   // ページを開いた最初の1回(と、オフから戻った最初の1回)では出さない
    var now = {}, i, k;
    for (i = 0; i < cur.recordings.length; i++) now[liveKey(cur.recordings[i])] = cur.recordings[i];
    for (k in live.prev) {
      if (!Object.prototype.hasOwnProperty.call(live.prev, k)) continue;
      var p = live.prev[k], c = now[k], name = '「' + liveTitle(c || p) + '」';
      if (p.active && c && c.state === 'error') toastFn(name + 'の録画でエラーが起きました', { kind: 'err' });
      else if (p.active && (!c || !c.active)) { if (p.state !== 'waiting' || (c || p).seconds) toastFn(name + 'の録画が終わりました(合計 ' + fmt.dur((c || p).seconds) + ')', { kind: 'ok', ms: 6000 }); }   // 録画を始める前の配信待ちが消えただけなら出さない
      else if (p.state === 'recording' && c && c.state === 'reconnecting') toastFn(name + 'の録画が切れました。つなぎ直しています', { kind: 'err' });
    }
  }
  function liveGot(j) {
    var cur = liveNorm(j);
    live.fails = 0; live.at = Date.now();
    if (!cur.enabled) { live.prev = null; live.nextMs = LIVE_OFF_MS; }
    else {
      liveNotify(cur);
      live.prev = {};
      for (var i = 0; i < cur.recordings.length; i++) { var r = cur.recordings[i]; live.prev[liveKey(r)] = { active: r.active, state: r.state, title: r.title, url: r.url, id: r.id, seconds: r.seconds }; }
      live.nextMs = LIVE_ON_MS;
    }
    live.last = cur;
  }
  function liveFail(e) {
    /* 4xx(まだ API が無い・機能がオフ)は、すぐ札を消して 60 秒後。ネットワークや 5xx の一時的な失敗は、2回までは今の表示のまま 10 秒後に */
    var st = e && e.status, hard = st >= 400 && st < 500;
    live.fails++;
    if (!hard && live.last && live.last.enabled && live.fails < 3) { live.nextMs = LIVE_ON_MS; return; }
    live.last = { enabled: false, recordings: [] };
    live.nextMs = LIVE_OFF_MS;
  }
  function liveRefresh() {
    if (!token() || !window.fetch) return Promise.resolve(live.last);
    if (live.inflight) return live.inflight;
    clearTimeout(live.timer);
    live.started = true;
    live.inflight = yttPost('live', { op: 'status' }).then(liveGot, liveFail).then(function () {
      try { liveRender(); liveFire(); } catch (e) { reportErr(e); }
    }).then(function () {
      live.inflight = null;
      clearTimeout(live.timer);
      live.timer = setTimeout(liveTick, live.nextMs);
      return live.last;
    });
    return live.inflight;
  }
  function liveTick() { if (document.hidden) { clearTimeout(live.timer); live.timer = setTimeout(liveTick, LIVE_ON_MS); return; } liveRefresh(); }   // 隠れているタブは問い合わせない
  function liveFire() { for (var i = 0; i < live.subs.length; i++) { try { live.subs[i](live.last); } catch (e) { reportErr(e); } } }
  function liveSet(el, text) { if (el.textContent !== text) el.textContent = text; }

  function liveEl(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }
  function liveEnsure() {
    if (live.els && live.els.box.isConnected) return live.els;
    var nav = document.querySelector('[data-ui-appnav]'), header = nav && nav.closest ? nav.closest('.ui-header') : null;
    if (!header) return null;
    var box = liveEl('span', 'ui-live'), btn = liveEl('button', 'btn ghost small ui-live-btn'), dot = liveEl('span', 'ui-live-dot'), text = liveEl('span', 'ui-live-text');
    var panel = liveEl('div', 'ui-live-panel'), list = liveEl('ul', 'ui-live-list');
    box.setAttribute('data-ui-live', ''); box.hidden = true;
    btn.type = 'button'; btn.setAttribute('aria-haspopup', 'dialog'); btn.setAttribute('aria-expanded', 'false');
    dot.setAttribute('aria-hidden', 'true');
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', '録画の一覧'); panel.tabIndex = -1; panel.hidden = true;
    btn.appendChild(dot); btn.appendChild(text); panel.appendChild(list); box.appendChild(btn); box.appendChild(panel);
    var acts = header.querySelector('.ui-header-actions');
    if (acts) acts.insertBefore(box, acts.firstChild); else header.appendChild(box);
    live.els = { box: box, btn: btn, text: text, panel: panel, list: list };
    live.rows = {};
    btn.addEventListener('click', function () { if (live.open) liveClose(false); else liveOpen(); });
    box.addEventListener('focusout', function (e) { if (live.open && e.relatedTarget && !box.contains(e.relatedTarget)) liveClose(false); });   // Tab で外へ出たら閉じる
    return live.els;
  }
  document.addEventListener('click', function (e) { if (live.open && live.els && !live.els.box.contains(e.target)) liveClose(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && live.open) liveClose(true); });

  function liveOpen() {
    var els = live.els; if (!els) return;
    live.open = true; els.panel.hidden = false; els.btn.setAttribute('aria-expanded', 'true');
    els.panel.style.left = els.panel.style.right = '';
    var r = els.panel.getBoundingClientRect(), m = 8;
    if (r.left < m) { els.panel.style.right = 'auto'; els.panel.style.left = Math.round(m - els.box.getBoundingClientRect().left) + 'px'; }   // 狭い画面で左へはみ出すときは画面の左端から
    clearInterval(live.tick); live.tick = setInterval(liveTimes, 1000);   // 開いている間だけ、録画済みの時間を1秒ごとに進める
    liveTimes();
    els.panel.focus({ preventScroll: true });
  }
  function liveClose(focusBtn) {
    var els = live.els; live.open = false; clearInterval(live.tick);
    if (!els) return;
    els.panel.hidden = true; els.btn.setAttribute('aria-expanded', 'false');
    if (focusBtn) els.btn.focus({ preventScroll: true });
  }
  function liveTimeText(r) {
    if (r.state === 'waiting') return '';
    var s = r.seconds + (r.state === 'recording' ? Math.max(0, (Date.now() - live.at) / 1000) : 0);   // 録画中は、問い合わせてからの分も足して滑らかに
    return fmt.dur(s);
  }
  function liveTimes() { for (var k in live.rows) { if (Object.prototype.hasOwnProperty.call(live.rows, k)) liveSet(live.rows[k].time, liveTimeText(live.rows[k].rec)); } }

  function liveStudioHref(r) { return homeUrl('cases') + '?c=' + encodeURIComponent(r.id) + '#cand'; }   // 案件の画面の候補
  function liveStop(row, btn) {
    btn.disabled = true;
    yttPost('live', { op: 'stop', recorder: row.rec.recorder, recording: row.rec.id }).then(function () { liveClose(true); return liveRefresh(); }, function (e) {   // 止めたら一覧を閉じる(終わりの知らせは札と toast で)
      toastFn('録画を止められませんでした: ' + (e && e.message ? e.message : ''), { kind: 'err' });
    }).then(function () { btn.disabled = false; });
  }
  function liveMakeRow() {
    var row = { rec: null }, li = liveEl('li', 'ui-live-row'), main = liveEl('span', 'ui-live-title'), meta = liveEl('span', 'ui-live-meta');
    var state = liveEl('span', 'ui-live-state'), time = liveEl('span', 'ui-live-time num'), acts = liveEl('span', 'ui-live-acts');
    var open = liveEl('a', 'btn small'), stop = liveEl('button', 'btn small danger');
    open.textContent = '開く'; stop.type = 'button'; stop.textContent = '停止';
    open.addEventListener('click', function (e) {
      open.setAttribute('href', liveStudioHref(row.rec));   // スタジオの場所が分かったのが描いたあとでも、押した時点の場所で移る
      if (!live.openFn || e.button !== 0 || e.ctrlKey || e.shiftKey || e.metaKey || e.altKey) return;   // スタジオの画面なら、移らずにその録画へ
      e.preventDefault(); liveClose(false);
      try { live.openFn(row.rec); } catch (x) { reportErr(x); }
    });
    stop.addEventListener('click', function () { confirmTwice(stop, function () { liveStop(row, stop); }, 'もう一度押すと停止'); });
    meta.appendChild(state); meta.appendChild(time); acts.appendChild(open); acts.appendChild(stop);
    li.appendChild(main); li.appendChild(meta); li.appendChild(acts);
    row.el = li; row.title = main; row.state = state; row.time = time; row.open = open; row.stop = stop;
    return row;
  }
  function liveRows(list) {
    var els = live.els, seen = {}, prevEl = null, i, k;
    for (i = 0; i < list.length; i++) {
      var r = list[i], key = liveKey(r), row = live.rows[key];
      if (!row) row = live.rows[key] = liveMakeRow();
      seen[key] = 1; row.rec = r;
      var t = liveTitle(r);
      liveSet(row.title, t); row.title.title = t;
      liveSet(row.state, LIVE_STATE_LABEL[r.state] || r.state);
      row.el.setAttribute('data-state', r.state);
      liveSet(row.time, liveTimeText(r)); row.time.hidden = !row.time.textContent;
      var href = liveStudioHref(r); if (row.open.getAttribute('href') !== href) row.open.setAttribute('href', href);
      row.open.setAttribute('aria-label', '「' + t + '」を案件の画面で開く');
      row.stop.setAttribute('aria-label', '「' + t + '」の録画を停止'); row.stop.hidden = !r.active;
      var want = prevEl ? prevEl.nextSibling : els.list.firstChild;
      if (want !== row.el) els.list.insertBefore(row.el, want);   // 順番が変わったときだけ動かす(押そうとしているボタンを巻き込まない)
      prevEl = row.el;
    }
    for (k in live.rows) {
      if (Object.prototype.hasOwnProperty.call(live.rows, k) && !seen[k]) { var gone = live.rows[k].el; if (gone.parentNode) gone.parentNode.removeChild(gone); delete live.rows[k]; }
    }
  }
  function liveRender() {
    var cur = live.last, list = cur && cur.enabled ? cur.recordings : [];
    if (!list.length) { if (live.els) { liveClose(false); live.els.box.hidden = true; } return; }
    var els = liveEnsure(); if (!els) return;
    var n = { reconnecting: 0, recording: 0, waiting: 0, error: 0 }, i, parts = [], state = '';
    for (i = 0; i < list.length; i++) if (n[list[i].state] !== undefined) n[list[i].state]++;
    if (n.reconnecting) { parts.push('つなぎ直し中' + (n.reconnecting > 1 ? ' ' + n.reconnecting : '')); state = 'reconnecting'; }
    if (n.recording) { parts.push('録画中 ' + n.recording); state = state || 'recording'; }
    if (n.waiting) { parts.push('配信待ち ' + n.waiting); state = state || 'waiting'; }
    if (!parts.length) {   // 動いているものが無い: 終わって間もない録画(開く先を残す)。エラーがあればそれを
      if (n.error) { parts.push('録画エラー'); state = 'error'; } else { parts.push('録画終了 ' + list.length); state = 'ended'; }
    }
    var label = parts.join('・');
    liveSet(els.text, label);
    els.btn.setAttribute('data-state', state);
    els.btn.setAttribute('aria-label', label + '。録画の一覧を開く');
    els.box.hidden = false;
    liveRows(list);
    if (live.open) liveTimes();
  }
  var liveBadge = {
    get: function () { return live.last; },                         /* 最後の応答 {enabled, recordings}(まだ無ければ null) */
    refresh: liveRefresh,                                           /* すぐ問い合わせ直す → Promise(最後の応答) */
    onChange: function (fn) { if (typeof fn === 'function') live.subs.push(fn); },   /* 応答のたびに fn(最後の応答) */
    onOpen: function (fn) { live.openFn = typeof fn === 'function' ? fn : null; }     /* スタジオの画面が登録: 「開く」で移らずに fn(録画)を呼ぶ */
  };
  life.onReturn(function () { if (live.started && token() && Date.now() - live.at > 3000) liveRefresh(); });
  function liveStart() { if (token() && document.querySelector('[data-ui-appnav]')) liveRefresh(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', liveStart); else liveStart();

  /* ---- sound(ほかの窓で音が鳴っているかを知らせ合う)---- 「編集」を別の窓で開いて再生すると、スタジオの配信の音と二重になる(ユーザーの指摘)。
     この画面の <video>・<audio> が鳴っている(再生中・消音でない・音量 0 でない)間、同じオリジンの窓へ BroadcastChannel で知らせる(外へは何も送らない)。
     鳴っている間は 2 秒ごとに送り直し、受ける側は 6 秒来なければ「止まった」とみなす(窓を閉じた・落ちたとき、下げたままにしない)。
     UIKit.sound.other(tool?) = ほかの窓(tool を渡せばそのツール以外)で鳴っているか / onChange(fn) = 変わったとき */
  var snd = { ch: null, id: Math.random().toString(36).slice(2), tool: (location.pathname.split('/')[1] || 'home'), on: false, beat: null, others: {}, subs: [], sweep: null };
  try { if (window.BroadcastChannel) snd.ch = new BroadcastChannel('ytt-sound'); } catch (e) { snd.ch = null; }
  function sndSend(on) { if (snd.ch) { try { snd.ch.postMessage({ id: snd.id, tool: snd.tool, playing: !!on }); } catch (e) { /* 知らせられなくても画面は動く */ } } }
  function sndMine() {
    var ms = document.querySelectorAll('video,audio');
    for (var i = 0; i < ms.length; i++) { var m = ms[i]; if (!m.paused && !m.ended && !m.muted && m.volume > 0 && m.readyState > 1) return true; }
    return false;
  }
  function sndCheck() {
    var on = sndMine();
    if (on === snd.on) return;
    snd.on = on; sndSend(on);
    clearInterval(snd.beat); snd.beat = on ? setInterval(function () { if (sndMine()) sndSend(true); else sndCheck(); }, 2000) : null;
  }
  function sndNotify() { snd.subs.forEach(function (fn) { try { fn(); } catch (x) { reportErr(x); } }); }
  function sndOther(tool) { for (var k in snd.others) { if (Object.prototype.hasOwnProperty.call(snd.others, k) && snd.others[k].tool !== tool) return true; } return false; }
  if (snd.ch) {
    ['play', 'playing', 'pause', 'ended', 'emptied', 'volumechange'].forEach(function (n) { document.addEventListener(n, sndCheck, true); });   // メディアのイベントは上へ伝わらないので capture で受ける
    window.addEventListener('pagehide', function () { if (snd.on) { snd.on = false; sndSend(false); } });
    snd.ch.onmessage = function (e) {
      var d = e.data; if (!d || typeof d.id !== 'string' || d.id === snd.id) return;
      var had = !!snd.others[d.id];
      if (d.playing) snd.others[d.id] = { tool: String(d.tool || ''), at: Date.now() }; else delete snd.others[d.id];
      if (had !== !!snd.others[d.id]) sndNotify();
      if (!snd.sweep) snd.sweep = setInterval(function () {
        var now = Date.now(), gone = false, n = 0;
        for (var k in snd.others) { if (Object.prototype.hasOwnProperty.call(snd.others, k)) { if (now - snd.others[k].at > 6000) { delete snd.others[k]; gone = true; } else n++; } }
        if (!n) { clearInterval(snd.sweep); snd.sweep = null; }
        if (gone) sndNotify();
      }, 2000);
    };
  }
  var sound = { other: sndOther, onChange: function (fn) { if (typeof fn === 'function') snd.subs.push(fn); }, tool: snd.tool };

  /* ---- 状態の言葉と色・Enter で実行・2 回押しの削除・空の表示・相対時刻の包み・まとめて実行の欄 ---- */
  /* UIKit.state: 順番待ち・実行・書き出しの状態(queued|waiting・running・done・error・cancelled・skipped)の言葉 label(s) と札の色 cls(s)。どの画面も同じ(中止は warn) */
  var STATE_CLS = { queued: 'wait', waiting: 'wait', running: 'run', done: 'ok', error: 'err', cancelled: 'warn', skipped: 'wait' };
  var uiState = {
    label: function (s) { return s === 'waiting' ? AR_RUN.queued : s === 'skipped' ? '飛ばした' : AR_RUN[s] || String(s || ''); },
    cls: function (s) { return STATE_CLS[s] || 'wait'; }
  };
  /* UIKit.onEnter(el, fn | ボタン, opt): 欄の Enter で実行。かな漢字変換を確定する Enter(isComposing・keyCode 229)では動かさない。
     ボタンを渡すと押せるときだけ押す。opt.ctrl = Ctrl(⌘)+Enter だけ・opt.plain = 修飾キーなしの Enter だけ */
  function onEnter(el, run, opt) {
    if (!el || !run) return;
    opt = opt || {};
    el.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
      var mod = e.ctrlKey || e.metaKey;
      if (opt.ctrl ? !mod : opt.plain && (mod || e.shiftKey || e.altKey)) return;
      e.preventDefault();
      if (typeof run === 'function') run(e); else if (!run.disabled && !run.hidden) run.click();
    });
  }
  /* 2 回押しの削除(confirmTwice の既定の文つき) */
  function armDelete(btn, run, text) { confirmTwice(btn, run, text || 'もう一度押すと削除'); }
  /* 空の表示の HTML: title(太字)+ 本文 + 次の一手のボタン(acts。HTML)。title・body・acts は呼ぶ側でエスケープ済み */
  function emptyHtml(title, body, acts) { return '<div class="empty"><b>' + title + '</b>' + (body || '') + (acts ? '<div class="cs-emptyacts">' + acts + '</div>' : '') + '</div>'; }
  /* 「3日前」に日付と時刻を title で添えた span(prefix = title の頭の文) */
  fmt.agoSpan = function (ms, prefix) { return '<span title="' + esc((prefix || '') + fmt.date(ms)) + '">' + esc(fmt.ago(ms)) + '</span>'; };
  /* まとめて実行の欄の共通の配線(配信者・採用数・設定の要約): o = {who: 配信者の欄, top: 採用数の欄, panel: 要約を描く箱, kind, run: 実行ボタン(欄の Enter で押す)} */
  autorun.topOf = function (input) { return Math.min(20, Math.max(1, Math.round(Number(input && input.value) || 3))); };
  autorun.form = function (o) {
    if (o.who) streamer.attach(o.who);
    if (o.panel) autorun.panel(o.panel, { kind: o.kind || 'video' });
    if (o.top) {
      arLoad().then(function (st) { o.top.value = String(st.top); if (o.onLoad) o.onLoad(st); }, function () {});
      o.top.addEventListener('change', function () { var n = Math.round(Number(o.top.value)); if (n >= 1 && n <= 20) prefs.patch('autorun', { top: n }).catch(function () {}); });
    }
    if (o.run) { onEnter(o.who, o.run, { plain: true }); onEnter(o.top, o.run, { plain: true }); }
  };
  /* 実行の一覧(api/flow/runs)の応答そのまま({runs, past})と、動いている(待ち・実行中)実行か */
  autorun.runs = function () { return arHomeApi('api/flow/runs'); };
  autorun.isActive = function (r) { return !!r && (r.state === 'queued' || r.state === 'running'); };

  /* スクリプトを 1 つ読む(CSP の script-src 'self' のまま。相対パスか同じ入口のパス)。-> 読み終わったら解決する Promise(失敗したらタグを消して Error)。
     opt.ready: 読み終わったあとに真でなければ「部品の形が違います」で失敗(window の名前を確かめる関数)・opt.timeout(ms): 待つ上限 */
  function loadScript(src, opt) {
    opt = opt || {};
    return new Promise(function (resolve, reject) {
      var tag = document.createElement('script'), timer = 0;
      function fail(msg) { clearTimeout(timer); tag.remove(); reject(new Error(msg)); }
      tag.src = src;
      tag.onload = function () { clearTimeout(timer); if (opt.ready && !opt.ready()) fail('部品の形が違います: ' + src); else resolve(); };
      tag.onerror = function () { fail(src + ' を読み込めませんでした'); };
      if (opt.timeout) timer = setTimeout(function () { fail(src + ' の読み込みが長引いています'); }, opt.timeout);
      document.head.appendChild(tag);
    });
  }

  window.UIKit = { version: 37, sound: sound, theme: theme, tools: tools, life: life, report: function (message, info) { return report(message, info, 'report'); }, win: win, fmt: fmt, esc: esc,
                   portal: portal, streamer: streamer, appnav: appnav, drawer: drawer, dialog: dialogApi, toast: toastFn, keybar: keybar, settings: settings, settingsForm: settingsForm, keys: keysApi, keymap: keymapApi, icon: icon,
                   confirmTwice: confirmTwice, prefs: prefs, autorun: autorun, flow: flow, restart: restart, timebox: timebox, hide: hide, liveBadge: liveBadge, menuOff: menuOff,
                   http: http, homeApi: homeApi, homeUrl: homeUrl, copy: copyText, tokenStale: tokenStale, loadScript: loadScript,
                   state: uiState, onEnter: onEnter, armDelete: armDelete, emptyHtml: emptyHtml };
})();
