/* 案件の画面の「候補」のパネル(#cand。配信全体の候補の採用・不採用・書き出し・LIVE の帯。RS8 C2a)。口の形は cases.js の先頭の説明。
   中身はスタジオ ② の部品 src/app/ui/studio/review.js(window.StudioReview.create(env))をそのまま使う = 古い画面と同じコード・同じ動き(古い画面は凍結。C4 で review.js をここへ移して古い画面を消す)。
   このファイルは「つなぎ」だけ: review.js を studio/review.js から 1 回読み(タブを開いたときだけ)、パネルの箱の中で作り、core.js の window.Studio の代わり(Studio の写し)を渡す。
     DOM はパネルの箱(el の子)の中だけを引く(document.getElementById・document.querySelector は使わない)・keydown は殻の 1 本から keys(e) で受ける・
     離れた / 戻ったは殻の leave / back で受ける・下のキーの帯は keybar() で殻へ渡す・API はスタジオの今の口(ctx.api('studio', …)。合言葉は ui-kit)。
   古い画面との違い(パネルの中だけ): 配信の選択(探す一覧・URL を開く)は出さない(案件は左の一覧で選ぶ)・キー操作の一覧(?)はパネルの中のダイアログ・
     「② の操作」(キー配置・ライブのマークをまとめてずらす)はパネルの下の畳んだ欄・「この配信を解析する」は解析の順番待ちへ直に入れる・
     出力先の「変更」は設定の画面へ・「編集で開く」は今の編集の画面(transcribe/?media=。C4 の転送で案件の画面へ)・ヘッダーの録画中の札の「開く」は札の既定の行き先。
   CSS は panels/cand.css(review.css の写し)。 */
(function () {
  'use strict';
  if (!window.CasesPanels) return;
  var REVIEW_JS = 'studio/review.js';   // 取り込んだスタジオの静的ファイル(相対パス)
  var reviewP = null;
  /* review.js を 1 回だけ読む(CSP script-src 'self' のまま。失敗したら次に開いたとき読み直す) */
  function loadReview() {
    if (window.StudioReview) return Promise.resolve();
    if (reviewP) return reviewP;
    var tag = document.createElement('script');
    reviewP = new Promise(function (resolve, reject) {
      tag.src = REVIEW_JS;
      tag.onload = function () { if (window.StudioReview) resolve(); else reject(new Error('部品の形が違います')); };
      tag.onerror = function () { reject(new Error('部品を読み込めませんでした')); };
      document.head.appendChild(tag);
    }).catch(function (e) { reviewP = null; tag.remove(); throw e; });
    return reviewP;
  }

  var PANEL_HTML =
    '<div class="cd-status" data-cd-status role="status" hidden></div>' +
    '<section class="cd-review" id="paneReview" aria-label="候補の確認・書き出し"></section>' +
    '<details class="ui-disclosure cd-ops" data-cd-ops><summary>この画面の操作の設定 <span class="muted">キー配置・ライブのマークをまとめてずらす</span></summary><div id="opsHost"></div></details>' +
    '<dialog class="cs-keyhelp" id="keyHelp" aria-labelledby="keyHelpTitle">' +
    '<div class="ui-dlg-head"><h2 id="keyHelpTitle">キー操作の一覧</h2><button type="button" class="btn ghost small icon" id="keyHelpClose" aria-label="閉じる" title="閉じる(Esc)"><span class="ui-icon" data-icon="close"></span></button></div>' +
    '<div class="cs-keypreset" id="keyPresetRow" hidden><label class="lag keep" for="rvKeyPreset">まとめて変える</label><select id="rvKeyPreset"><option value="standard">標準</option><option value="left">左手だけ</option><option value="custom" disabled>今の配置(手で変えた)</option></select></div>' +
    '<div id="keyHelpBody"></div></dialog>';
  var ACTIVE = { queued: 1, running: 1 };

  function create() {
    var pane = null, cctx = null, dead = false, started = false, vid = '', keyFn = null, kb = [], lifeFns = [null, null], subs = {}, readyFns = [], listeners = [], activeJobs = {};
    var esc = UIKit.esc;
    var q = function (sel) { return pane.querySelector(sel); };
    var tokenTag = document.head.querySelector('meta[name="ytt-token"]');

    /* ---- core.js の window.Studio の代わり(review.js が使う分だけ)---- */
    function emit(name, detail) { (subs[name] || []).slice().forEach(function (fn) { try { fn(detail); } catch (e) { UIKit.report('候補のパネルで失敗しました: ' + (e && e.message), { stack: e && e.stack }); } }); }
    var Studio = {
      esc: esc, token: tokenTag ? tokenTag.content : '', state: null, step: '', review: null, params: {},
      fmtTime: function (t) { return UIKit.fmt.dur(t, { tenths: true }); },
      api: function (path, o) {
        o = o || {};
        return cctx.api('studio', path, { method: o.method, body: o.body, signal: o.signal, timeout: 0, offline: 'スタジオにつながりませんでした(start.bat の黒い画面が閉じていないか確かめてください)' });
      },
      url: function (p) { return 'studio/' + String(p).replace(/^\/+/, ''); },
      portalApi: function (path, body) { return UIKit.homeApi(path, { body: body }); },
      toolUrl: function (id, path) { return id + '/' + String(path || '').replace(/^\/+/, ''); },
      toast: function (msg, ms, kind) { return ms && typeof ms === 'object' ? UIKit.toast(msg, ms) : UIKit.toast(msg, { ms: ms || undefined, kind: kind }); },
      why: function (b, why, okTitle) { b.disabled = !!why; b.title = why || okTitle || ''; if (why) b.setAttribute('data-ui-why', why); else b.removeAttribute('data-ui-why'); },
      setBadge: function () {},
      ago: function (ms) { return UIKit.fmt.ago(ms); },
      date: function (ms) { return UIKit.fmt.date(ms); },
      isVideoId: function (s) { return /^[\w-]{11}$/.test(s || ''); },
      watchUrl: function (id, t) { return 'https://www.youtube.com/watch?v=' + encodeURIComponent(id) + (t >= 1 ? '&t=' + Math.floor(t) + 's' : ''); },
      matchWords: function (words, hay) { return String(words || '').trim().toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return String(hay).toLowerCase().indexOf(w) >= 0; }); },
      groupBy: function (list, key) { var m = new Map(); list.forEach(function (x) { var k = key(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x); }); return m; },
      /* 入力中か: ui-kit の判定 + 時刻の欄(UIKit.timebox)。キーの判定は殻が先にするので、ここは review.js の中の確かめ用 */
      isTyping: function (el) { return !!el && ((el.classList && el.classList.contains('ui-time')) || UIKit.keys.isTyping(el)); },
      inMenu: function (el) { return !!(el && el.closest && el.closest('details.ui-menu[open]')); },
      overlayOpen: function () {
        var d = document.body.querySelector('#uiSettingsDrawer');
        return !!(document.body.querySelector('dialog[open]') || (d && UIKit.drawer.isOpen(d)));
      },
      on: function (name, fn) { (subs[name] = subs[name] || []).push(fn); },
      onReady: function (fn) { readyFns.push(fn); },
      go: function (step) { if (step !== 'review' || dead) return; Studio.step = 'review'; emit('step', 'review'); },
      refreshState: function () {
        return Studio.api('/api/state').then(function (st) { if (dead) return st; Studio.state = st; emit('state', st); return st; });
      },
      /* 作業データ(data.json)の読み込みの問題(スタジオの起動のあと 1 回だけ /api/state に載る)。パネルでは帯に文だけ出す */
      dataWarning: function (box) {
        var w = Studio.state && Studio.state.dataWarning;
        if (!box) return;
        box.hidden = !w;
        if (w && !box.childElementCount) box.innerHTML = '<div><b>スタジオの作業データの読み込みで問題がありました</b><br>' + esc(w) + '</div>';
      },
      openKeyHelp: function () {
        var dlg = q('#keyHelp'), km = Studio.review && Studio.review.keymap;
        if (!dlg || dlg.open || !km) return;
        km.mount(q('#keyHelpBody')); km.clearNote(); dlg.showModal();
      },
      /* 出力先などスタジオの設定は設定の画面(入口の /settings のスタジオの節)で変える */
      openSettings: function () { location.assign(UIKit.homeUrl('settings') + '#sec-studio'); },
      /* 「この配信を解析する」: 解析の順番待ちへ入れる(スタジオ ① の queue.js と同じ口。解析の設定はスタジオの設定の analyze の節) */
      enqueue: function (items) {
        return Studio.api('/api/settings').then(function (j) {
          var opts = j && j.settings && j.settings.analyze && typeof j.settings.analyze === 'object' ? j.settings.analyze : {};
          return Studio.api('/api/queue/add', { body: { items: items, settings: opts } });
        }).then(function (r) {
          var added = (r && r.added) || [], rejected = (r && r.rejected) || [];
          if (added.length) Studio.toast('解析の順番待ちに入れました。終わると、ここに自動のマークが出ます(左の一覧に進み具合が出ます)', 6000, 'ok');
          else Studio.toast('解析に入れられませんでした: ' + (rejected.map(function (x) { return x.reason; }).join(' / ') || '入れる物がありませんでした'), 0, 'err');
          return r;
        }, function (e) { Studio.toast('解析に入れられませんでした: ' + e.message, 0, 'err'); });
      },
      /* ライブの録画(入口の ../live/…)。録画を始める・登録する口はパネルでは使わない(配信の選択を出さないため) */
      live: {
        info: null,
        url: function (rest) { return UIKit.homeUrl('live/' + rest); },
        api: function (rest, o) {
          o = o || {};
          var method = o.method || (o.body !== undefined ? 'POST' : 'GET');
          return UIKit.homeApi('live/' + rest, { method: method, body: method === 'GET' ? undefined : (o.body || {}), timeout: o.timeout || (method === 'GET' ? 10000 : 45000) });
        },
        available: function () { return Promise.resolve(null); },
        begin: function () { return Promise.resolve(null); },
        begunText: function () { return ''; },
        register: function () { return Promise.reject(new Error('案件の画面では録画の登録はしません')); }
      }
    };
    /* review.js に渡す env(review.js の先頭の説明)。見張りは片付けで外す・document の keydown は殻の keys へ */
    var env = {
      Studio: Studio, wide: '(min-width:1241px)',   // 左の一覧(280px)の分だけ、2 列にする幅を広げる(cand.css と同じ区切り)
      $: function (sel) { return pane.querySelector(sel); },
      $$: function (sel) { return pane.querySelectorAll(sel); },
      listen: function (target, type, fn, opt) {
        if (target === document && type === 'keydown') { keyFn = fn; return; }
        target.addEventListener(type, fn, opt);
        listeners.push([target, type, fn, opt]);
      },
      keybar: function (list) { kb = list || []; if (!dead && started && cctx) cctx.refreshKeys(); },
      life: function (onLeave, onReturn) { lifeFns = [onLeave, onReturn]; }
    };

    /* ---- 読み込み中・失敗の案内(何が / 次にどうする)---- */
    function status(kind, detail) {
      var box = q('[data-cd-status]');
      if (!kind) { box.hidden = true; box.innerHTML = ''; return; }
      var t = {
        loading: ['候補を読み込んでいます…', ''],
        script: ['候補の画面の部品を読み込めませんでした', 'スタジオが動いていないかもしれません。ホームの「調子」でスタジオを確かめてから、もう一度読み込んでください。'],
        video: ['この配信をスタジオで開けませんでした', 'スタジオから削除したか、まだスタジオに入れていない配信です(理由は知らせに出ています)。ホームの案件の一覧から開き直すか、もう一度読み込んでください。'],
        none: ['この案件には配信がありません', 'ホームの案件の一覧から開き直してください。']
      }[kind];
      box.className = 'cd-status' + (kind === 'loading' ? '' : ' empty');
      box.innerHTML = '<b>' + esc(t[0]) + '</b>' + (t[1] ? '<span>' + esc(t[1]) + '</span>' : '') +
        (detail ? '<span class="hint">' + esc(detail) + '</span>' : '') +
        (kind === 'script' || kind === 'video' ? '<div class="cs-emptyacts"><button type="button" class="btn primary small" data-cd-retry>もう一度読み込む</button></div>' : '');
      box.hidden = false;
    }

    function openVideo() {
      if (!vid) { status('none'); return; }
      status('loading');
      Studio.review.open(vid).then(function (ok) { if (!dead) status(ok ? null : 'video'); });
    }
    function start() {
      window.StudioReview.create(env);   // Studio.review・Studio.onReady(…)を登録する(画面はまだ作らない)
      started = true;
      readyFns.splice(0).forEach(function (fn) { fn(); });   // 画面を作る・見張り・設定を読む(review.js の onReady)
      UIKit.liveBadge.onOpen(null);   // 札の「開く」で別の録画をこのパネルに読み込まない(札の既定の行き先へ)
      Studio.refreshState().catch(function () { /* ffmpeg の有無が分からないだけ */ });
      openVideo();
    }
    /* ② のジョブ(この配信の解析・書き出しなど)が終わった = マークが増えた・書き出し済みになった → 読み直す(スタジオの画面で ② に戻ったときと同じ) */
    function watchJobs(ctx) {
      var all = (ctx.status && ctx.status.all) || [], now = {}, finished = false;
      all.forEach(function (j) {
        var t = j.target || {};
        if (t.videoId !== vid) return;
        if (ACTIVE[j.state]) now[j.id] = 1; else if (activeJobs[j.id]) finished = true;
      });
      activeJobs = now;
      if (finished && started && Studio.review && Studio.review.open) Studio.go('review');
    }

    return {
      id: 'cand',
      mount: function (el, ctx) {
        cctx = ctx; vid = ctx.videoId || '';
        pane = document.createElement('div');
        pane.className = 'cd-panel';
        pane.innerHTML = PANEL_HTML;
        el.appendChild(pane);
        UIKit.icon.fill(pane);
        q('#keyHelpClose').addEventListener('click', function () { q('#keyHelp').close(); });
        q('#keyHelp').addEventListener('click', function (e) { if (e.target === q('#keyHelp')) q('#keyHelp').close(); });   // 枠の外を押したら閉じる
        pane.addEventListener('click', function (e) {
          if (!e.target.closest('[data-cd-retry]')) return;
          if (started) openVideo(); else begin();
        });
        watchJobs(ctx);
        begin();
        function begin() {
          status('loading');
          loadReview().then(function () { if (!dead) start(); }, function (e) { if (!dead) status('script', e.message); });
        }
      },
      update: function (ctx) {
        cctx = ctx;
        var v = ctx.videoId || '';
        if (v !== vid) { vid = v; activeJobs = {}; if (started) openVideo(); }
        watchJobs(ctx);
      },
      unmount: function () {
        dead = true;
        Studio.step = '';   // review.js の見回りは「② を開いている間」だけ(遅れて届いた答えで次の見回りを入れない)
        if (started && Studio.review && Studio.review.dispose) Studio.review.dispose();   // 保存・再生を止める・見回りを止める・書き出しの欄を閉じる
        listeners.splice(0).forEach(function (x) { x[0].removeEventListener(x[1], x[2], x[3]); });
        keyFn = null;
        var dlg = q('#keyHelp'); if (dlg && dlg.open) dlg.close();
        if (started) UIKit.liveBadge.onOpen(null);
      },
      /* 殻の keydown から(入力中・変換中・引き出しやダイアログの中は殻が除く)。? = キー操作の一覧(スタジオの画面と同じ)。ほかは review.js の keydown */
      keys: function (e) {
        if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey && !e.repeat) { Studio.openKeyHelp(); return true; }
        if (!keyFn) return false;
        keyFn(e);
        return e.defaultPrevented;
      },
      keybar: function () { return kb; },
      leave: function (reason) { if (lifeFns[0]) lifeFns[0](reason); },
      back: function (reason) { if (lifeFns[1]) lifeFns[1](reason); }
    };
  }
  window.CasesPanels.define('cand', create);
})();
