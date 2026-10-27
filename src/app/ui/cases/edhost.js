/* 案件の画面に「編集」の校正(1 文字起こし)をそのまま載せる台(RS8 C2b。作り方 資料の git:before-1028-cleanup:docs/design/rs8-cases-build.md の C2b)。
   編集の app-*.js・app.js は包みの無いトップレベルの名前(S・$・openDoc・saveDoc …)で動くので、包まずにそのまま読む。
   ここがするのは:
   (1) 初めて校正を開いたときに 1 回だけ組み立てる: ホームの api/status で編集(transcribe)が取り込まれているかを見る → 版の meta → transcribe/app-tpl.js(欄の
       テンプレート)と transcribe/proof.css → 欄を組み立てて隠し場所(.cs-ed-park)へ → transcribe/app-core.js … app.js を順に読む(app.js が起動 boot() する)。
       ⚙ の節は設定の引き出しへ app.js が移す。
       カット・パックは panels/cut.js が自分で持つ(app.js は作らない)。⚙ の「パック」の節(#edSetPack)は同じ id が
       カット・パックのパネルにあるので外す(app.js は欄が無ければ飛ばす)。
   (2) 校正のパネル(panels/proof.js)が開いている間だけ欄をパネルの中へ移し(attach)、閉じたら隠し場所へ戻す(detach。再生を止め・保存を送る)。
       欄は捨てない = app.js の配線(id で引いた要素)が生きたまま。
   (3) app.js が見る口 window.EditHost(app.js の先頭の説明): base = 編集の API の頭(transcribe)・keybar = 下の帯の中身を殻に渡す・
       tab = 「2 カットへ」などのタブの切り替えを殻へ・open = 別の文書を開く要求を殻の一覧へ(無ければその文書の案件へ移る)・opening = 台が開いている間は真。
   (4) 編集のキー(window の keydown)は、校正のパネルが開いていない間は届けない(document で止める。殻の keydown 1 本は document なので先に動く)。
   CSP(script-src 'self')の下で動く: 部品は同じ入口の相対パス transcribe/… から読む(カット・パックのパネルと同じ)。 */
(function () {
  'use strict';

  var ED_SCRIPTS = ['app-core.js', 'app-jobs.js', 'app-list.js', 'app-learn.js', 'app-rows.js', 'app-tools.js', 'app.js'];
  var NOT_MOUNTED = '編集(文字起こし)がホームに取り込まれていません。ホームの「すべて終了」から start.bat で起動し直してください';
  var park = null, wrap = null, readyP = null, guardOn = false, built = false, later = [];

  function loadCss(href) {
    return new Promise(function (resolve) {
      var l = document.createElement('link');
      l.rel = 'stylesheet'; l.href = href;
      l.onload = l.onerror = function () { resolve(); };   // 見た目が無くても動きは止めない
      document.head.appendChild(l);
    });
  }

  /* 編集の版の meta(app.js が読む = 設定の引き出しの版・サーバーとの版の比べ)。殻の画面には入口が入れないので api/status の版を入れる */
  function versionMeta(v) {
    if (!v || document.head.querySelector('meta[name="ytt-version"]')) return;
    var m = document.createElement('meta');
    m.name = 'ytt-version'; m.content = String(v);
    document.head.appendChild(m);
  }

  /* app.js の配線が引く欄。見せるのは #errBar・保存の状態・キー操作・題名の行・1 文字起こし の欄だけ(ほかは cases の CSS で隠す) */
  function build() {
    var T = window.EditProofTpl || {};
    if (!T.tx || !T.docbar || !T.settings || !T.dialogs) throw new Error('編集の欄のテンプレート(app-tpl.js)が古いか読めません');
    park = document.createElement('div');
    park.className = 'cs-ed-park'; park.hidden = true;
    wrap = document.createElement('div');
    wrap.className = 'cs-ed-wrap';
    wrap.innerHTML = '<div class="errbar" id="errBar" hidden role="alert"></div>' +
      '<div class="cs-ed-bar">' +
        '<div class="cs-ed-tools" data-ed-tools></div><span class="cs-spacer"></span>' +
        '<span class="savest" id="saveState" role="status"></span>' +
        '<button type="button" class="btn ghost small" id="btnKeys" title="キー操作の一覧(?)" aria-haspopup="dialog"><span class="ui-icon" data-icon="keyboard" aria-hidden="true"></span>キー操作</button>' +
      '</div>' +
      '<main class="editor" id="editor"><div id="doc" hidden>' + T.docbar + T.tx + '</div></main>';
    park.appendChild(wrap);
    var set = document.createElement('div');
    set.hidden = true;
    set.innerHTML = T.settings;
    park.appendChild(set);
    var dlg = document.createElement('div');
    dlg.className = 'cs-ed-dialogs';   // ダイアログは隠し場所の外(隠した親の中では開いても見えない)
    dlg.innerHTML = T.dialogs;
    document.body.appendChild(park);
    document.body.appendChild(dlg);
    if (UIKit.icon && UIKit.icon.fill) UIKit.icon.fill(wrap);
  }

  /* 校正のパネルが開いていない間は、編集の window の keydown へ届けない(殻の keydown は document = 先に済んでいる)。キー配置の入力中は止めない */
  function guard(e) {
    if (H.active) return;
    if (UIKit.keymap && UIKit.keymap.capturing && UIKit.keymap.capturing()) return;
    e.stopPropagation();
  }

  function boot() {
    return UIKit.homeApi('api/status', { method: 'GET', timeout: 8000 }).then(function (st) {
      var t = ((st && st.tools) || []).filter(function (x) { return x && x.id === 'transcribe'; })[0];
      if (!t || !t.mounted) { var e = new Error(NOT_MOUNTED); e.code = 'not_mounted'; throw e; }
      versionMeta(st.version);
      return Promise.all([UIKit.loadScript('transcribe/app-tpl.js'), loadCss('transcribe/proof.css')]);
    }).then(function () {
      build(); built = true;
      if (!guardOn) { document.addEventListener('keydown', guard); guardOn = true; }
      /* cut.js を先に(app.js が読み込みの時点で EditCut.KEY_ROWS・FIXED_KEYS を写す = ? の一覧の「2 カット のタブ」の節とキー配置の検査。RS8 C4。
         カット・パックのパネルが先に読んでいれば読まない) */
      var first = window.EditCut ? Promise.resolve() : UIKit.loadScript('transcribe/cut.js');
      var all = (window.EditDoc ? [] : ['doc-kit.js']).concat(ED_SCRIPTS);   // 文書の部品(doc-kit.js)は、カット・パックのパネルが先に読んでいれば読まない
      return all.reduce(function (p, n) { return p.then(function () { return UIKit.loadScript('transcribe/' + n); }); }, first);
    }).then(function () {
      later.splice(0).forEach(function (fn) { fn(); });   // 編集の部品が「app.js のあとで」と頼んだ初期化(app-tools.js の evbInit)
      return BOOTED;   // app.js の起動(boot())の約束(app.js の最後の行)
    });
  }

  var H = window.EditHost = {
    base: location.pathname.replace(/\/[^/]*$/, '') + '/transcribe',   // /cases → /transcribe(編集の apiUrl の頭)
    opening: false, active: false, items: [], onKeys: null,
    later: function (fn) { later.push(fn); },
    keybar: function (items) { H.items = items || []; if (H.active && H.onKeys) H.onKeys(); },
    tab: function (t) { var cs = window.CasesShell; if (cs) cs.setTab(t === 'tx' ? 'proof' : 'cut'); },
    open: function (id) {
      var cs = window.CasesShell;
      if (!(cs && cs.select('d:' + id, 'proof'))) location.href = 'cases?d=' + encodeURIComponent(id) + '#proof';
      return Promise.resolve(false);
    },
    /* 編集を読み込んで起動し終えるまで(1 回だけ。失敗したら次に呼んだときにもう一度) */
    ensure: function () {
      /* 編集の部品を読む前の失敗(取り込まれていない・つながらない)はもう一度試せる。読み始めたあとの失敗は画面の読み込み直しが要る(同じ名前を 2 回は置けない) */
      if (!readyP) readyP = boot().catch(function (e) { if (!built) readyP = null; else e.reload = true; throw e; });
      return readyP;
    },
    /* 欄をパネルの中へ(onKeys = 下の帯が変わったとき)/ 隠し場所へ戻す(再生を止め・保存を送る) */
    attach: function (el, onKeys) {
      if (!wrap) return;
      el.appendChild(wrap);
      H.active = true; H.onKeys = onKeys || null;
      applyView();
    },
    detach: function () {
      if (!wrap) return;
      H.active = false; H.onKeys = null;
      try { player().pause(); window.CasesPanels.track(saveDoc()); } catch (e) { /* 編集が起動できていない */ }   // 次に開くパネル(カット・パック)はこの保存を待ってから文書を読む
      park.appendChild(wrap);
    },
    tools: function () { return wrap ? wrap.querySelector('[data-ed-tools]') : null; }
  };
})();
