/* 新しい案件のパネル(ホームの引き出し #newDrawer で開く。配信を探す・URL から入れる・解析の順番待ち。RS8 C3)。
   中身はスタジオ ① の部品 src/app/ui/studio/rank.js(配信を探す・配信中・まとめて実行)と src/app/ui/studio/queue.js(URL から入れる・解析の順番待ち)をそのまま使う。
   このファイルは「つなぎ」だけ(panels/cand.js と同じ作り): 2 本のスクリプトは window.Studio(core.js)に頼って書かれているので、
   そのうち使う分だけの代わり(下の Studio)を渡して読み込み、パネルの箱の中に ① の器(#paneRank)を作る。
   パネルの中だけの動き: 「確認する」「録画を ② で開く」は案件の画面(/cases?c=<配信 id>#cand)へ移る・
     解析の設定・出力先・ライブの録画は設定の画面(/settings のスタジオ・リアルタイム切り抜きの節)へ・ヘッダーの件数の札は出さない。
   RS8 C4: 「YouTube Data API キー」「事務所の登録」「コラボ」と ffmpeg・yt-dlp が無いときの案内は
     このパネルの末尾の「探す設定」(#nwSet)に置く。事務所の登録は rank.js の mountRegistry・コラボは studio/collab.js(開いたときに初めて読む)。
   口: window.NewCasePanel = { create() -> { mount(el, opts), update(opts), setVisible(on), unmount(), focus(), openSettings(which) } }(which = setKey | setReg | setCollab)。opts = { url, media }(?url= で受けた配信の URL・?media= で受けた動画のパス。欄に入れるだけ)。
   (案件の画面の殻が CasesPanels を持っているときは、同じ create を 'new' の名前でも登録する = V1 の確かめるが同じ口で開ける)
   パネルの箱の中の要素は、rank.js・queue.js が文書全体から id で引くので、その id はホームの id と重ならないこと(test_cases_page が検査)。CSS は panels/new.css(.nw-panel の下だけ)。CSP script-src 'self' のまま(スクリプトは相対パスで 1 回だけ読む)。 */
(function () {
  'use strict';
  var RANK_JS = 'studio/rank.js', QUEUE_JS = 'studio/queue.js', COLLAB_JS = 'studio/collab.js';
  var loadP = null, collabP = null;

  /* 探す設定(RS8 C4。3 つの節)。id は nwSet で始める(ホームの id と重ねない) */
  var SET_HTML = '<div class="notice" id="nwToolNotice" role="alert" hidden></div>' +
    '<details class="card nw-set" id="nwSet"><summary><span class="set-title">探す設定</span><span class="set-sub">YouTube Data API キー・事務所の登録・コラボ</span><span class="pill" id="nwKeyState"></span></summary><div class="body">' +
    '<section class="nw-set-sec" id="nwSetKey" aria-labelledby="nwKeyH"><h3 class="nw-set-h" id="nwKeyH">YouTube Data API キー</h3>' +
      '<p class="hint">Google Cloud で「YouTube Data API v3」を有効にして作った API キーを入れます(配信を探すのに必要。コメント欄の時刻の解析にも使います)。キーはこのパソコンの中にだけ保存し、画面には出しません(作業データの config.json。環境変数 YOUTUBE_API_KEY があればそちらが優先)。</p>' +
      '<div class="fld"><label class="l" for="nwKeyIn">API キー</label><input type="password" id="nwKeyIn" placeholder="AIza..." autocomplete="off" spellcheck="false"></div>' +
      '<div class="row set-actions"><button type="button" class="btn small primary" id="nwKeySave">保存</button><button type="button" class="btn small danger" id="nwKeyDel">キーを削除</button></div>' +
      '<p class="msg hint" id="nwKeyMsg" role="status"></p></section>' +
    '<details class="nw-set-sec reg" id="nwSetReg"><summary><span class="set-title">事務所の登録</span><span class="set-sub">事務所ごとの所属チャンネル(配信を探す対象)</span></summary><div class="body" id="nwRegHost"></div></details>' +
    '<details class="nw-set-sec" id="nwSetCollab"><summary><span class="set-title">コラボ</span><span class="set-sub">複数人のコラボ配信をグループにまとめ、採用したマークを転写</span></summary><div class="body" id="nwCollabHost"></div></details>' +
    '</div></details>';
  var SET_SECS = { setKey: '#nwSetKey', setReg: '#nwSetReg', setCollab: '#nwSetCollab' };

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var tag = document.createElement('script');
      tag.src = src;
      tag.onload = function () { resolve(); };
      tag.onerror = function () { tag.remove(); reject(new Error('部品を読み込めませんでした: ' + src)); };
      document.head.appendChild(tag);
    });
  }

  function create() {
    var box = null, dead = false, started = false, visible = false, readyFns = [], subs = {}, params = {};
    var esc = UIKit.esc;
    var tokenTag = document.head.querySelector('meta[name="ytt-token"]');
    var STUDIO_OFFLINE = 'スタジオにつながりませんでした(start.bat の黒い画面が閉じていないか確かめてください)';
    var HOME_OFFLINE = 'ホームにつながりませんでした(start.bat の黒い画面が閉じていないか確かめてください)';
    var LIVE = { infoP: null, offAt: 0 };
    var LIVE_RECHECK_MS = 60000;

    function emit(name, detail) { (subs[name] || []).slice().forEach(function (fn) { try { fn(detail); } catch (e) { UIKit.report('新しい案件のパネルで失敗しました: ' + (e && e.message), { stack: e && e.stack }); } }); }

    /* ---- core.js の window.Studio の代わり(rank.js・queue.js が使う分だけ)---- */
    var Studio = {
      esc: esc, token: tokenTag ? tokenTag.content : '', state: null, step: '', review: null, params: params, ready: false,
      fmtTime: function (t) { return UIKit.fmt.dur(t, { tenths: true }); },
      url: function (p) { return 'studio/' + String(p).replace(/^\/+/, ''); },
      api: function (path, o) {
        o = o || {};
        return UIKit.http(Studio.url(path), { method: o.method, body: o.body, signal: o.signal, offline: STUDIO_OFFLINE });
      },
      portalApi: function (path, body) { return UIKit.homeApi(path, { body: body, offline: HOME_OFFLINE }); },
      toast: function (msg, ms, kind) { return ms && typeof ms === 'object' ? UIKit.toast(msg, ms) : UIKit.toast(msg, { ms: ms || undefined, kind: kind }); },
      showErr: function (msg) { UIKit.toast(String(msg), { ms: 0, kind: 'err' }); },
      why: function (b, why, okTitle) { b.disabled = !!why; b.title = why || okTitle || ''; if (why) b.setAttribute('data-ui-why', why); else b.removeAttribute('data-ui-why'); },
      setBadge: function () {},
      ago: function (ms) { return UIKit.fmt.ago(ms); },
      date: function (ms) { return UIKit.fmt.date(ms); },
      isVideoId: function (s) { return /^[\w-]{11}$/.test(s || ''); },
      watchUrl: function (id, t) { return 'https://www.youtube.com/watch?v=' + encodeURIComponent(id) + (t >= 1 ? '&t=' + Math.floor(t) + 's' : ''); },
      matchWords: function (words, hay) { return String(words || '').trim().toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return String(hay).toLowerCase().indexOf(w) >= 0; }); },
      groupBy: function (list, key) { var m = new Map(); list.forEach(function (x) { var k = key(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x); }); return m; },
      isTyping: function (el) { return !!el && ((el.classList && el.classList.contains('ui-time')) || UIKit.keys.isTyping(el)); },
      on: function (name, fn) { (subs[name] = subs[name] || []).push(fn); },
      onReady: function (fn) { if (Studio.ready) fn(); else readyFns.push(fn); },
      go: function (step) { if (step !== 'rank' || dead) return; setStep(visible ? 'rank' : ''); },
      refreshState: function () {
        return Studio.api('/api/state').then(function (st) { if (dead) return st; Studio.state = st; emit('state', st); return st; });
      },
      /* 作業データ(data.json)の読み込みの問題(起動のあと 1 回だけ /api/state に載る)。帯に文だけ出す */
      dataWarning: function (b) {
        var w = Studio.state && Studio.state.dataWarning;
        if (!b) return;
        b.hidden = !w;
        if (w && !b.childElementCount) b.innerHTML = '<div><b>スタジオの作業データの読み込みで問題がありました</b><br>' + esc(w) + '</div>';
      },
      /* API キー・事務所の登録・コラボはこのパネルの「探す設定」を開く(RS8 C4)。ほか(解析・出力先・ライブの録画)は設定の画面 */
      openSettings: function (which) {
        if (box && SET_SECS[which]) { openSet(which); return; }
        location.assign(UIKit.homeUrl('settings') + (which === 'setLive' ? '#sec-live' : '#sec-studio'));
      },
      /* 録画した配信・解析を終えた配信は案件の画面の候補で開く(古い画面の ② の代わり) */
      openReview: function (id) { location.assign(UIKit.homeUrl('cases') + '?c=' + encodeURIComponent(id) + '#cand'); return Promise.resolve(); },
      /* ライブの録画(入口の ../live/…。core.js と同じ。機能がオフなら 404 → 使えない) */
      live: {
        info: null,
        url: function (rest) { return UIKit.homeUrl('live/' + rest); },
        api: function (rest, o) {
          o = o || {};
          var method = o.method || (o.body !== undefined ? 'POST' : 'GET');
          return UIKit.homeApi('live/' + rest, { method: method, body: method !== 'GET' ? (o.body || {}) : undefined, timeout: o.timeout || (method === 'GET' ? 10000 : 45000),
            offline: HOME_OFFLINE, slow: 'ホームから時間内に応答がありません' });
        },
        available: function () {
          if (!Studio.token) return Promise.resolve(null);
          if (LIVE.offAt && Date.now() - LIVE.offAt < LIVE_RECHECK_MS) return Promise.resolve(null);
          if (!LIVE.infoP) {
            LIVE.infoP = Studio.live.api('api/info').then(function (j) {
              if (!j || j.enabled === false) { LIVE.offAt = Date.now(); LIVE.infoP = null; return null; }
              LIVE.offAt = 0; Studio.live.info = j; return j;
            }, function (e) { LIVE.infoP = null; if (e.status === 404) LIVE.offAt = Date.now(); return null; });
          }
          return LIVE.infoP;
        },
        refreshInfo: function () { LIVE.infoP = null; LIVE.offAt = 0; return Studio.live.available(); },
        register: function (recorder, rec, fb) {
          fb = fb || {};
          return Studio.api('/api/videos/open', { body: { kind: 'live', recorder: recorder, recording: rec.id,
            url: rec.url || fb.url || '', title: rec.title || fb.title || '', channel: String(rec.channel || fb.channel || '').slice(0, 100) } });
        },
        begin: function (url, opts) {
          opts = opts || {};
          return Studio.live.available().then(function (info) {
            if (!info) return null;
            return Studio.live.api('api/begin', { body: { url: url } }).then(function (b) {
              var rec = b && b.live && b.recording;
              if (!rec || !rec.id || !b.recorder) return null;
              return Studio.live.register(b.recorder, rec, { url: url, channel: opts.channel }).then(function (r) {
                try { UIKit.liveBadge.refresh(); } catch (e) { /* 札はなくてよい */ }
                return { video: r.video, existing: !!b.existing, recording: rec, recorder: b.recorder };
              }, function (e) { throw new Error('録画は始めましたが、スタジオに登録できませんでした: ' + e.message); });
            }, function (e) { if (e.status === 404) { LIVE.offAt = Date.now(); LIVE.infoP = null; } return null; });
          });
        },
        begunText: function (b) { return b.existing ? 'この配信はもう録画しています。その録画を開きました' : '配信の録画を始めました。見ながらマークできます'; },
        openBegun: function (b, more) {
          Studio.toast(Studio.live.begunText(b) + (more || ''), 6000, 'ok');
          return Studio.openReview(b.video.id);
        }
      }
    };

    /* ---- 探す設定(API キー・事務所の登録・コラボ。RS8 C4)---- */
    var regMounted = false;
    function q(sel) { return box ? box.querySelector(sel) : null; }
    function paintSet() {
      var t = Studio.state || {}, k = q('#nwKeyState'), n = q('#nwToolNotice'), miss = [];
      if (!k) return;
      var ks = '未設定', kc = 'warn';
      if (t.fake && !t.keySource) { ks = '疑似モード(キー不要)'; kc = 'info'; } else if (t.keySource === 'env') { ks = 'キー: 環境変数'; kc = 'ok'; } else if (t.hasKey) { ks = 'キー: 設定済み'; kc = 'ok'; }
      k.textContent = ks; k.className = 'pill ' + kc;
      if (t.ffmpeg === false) miss.push('<b>ffmpeg</b> が見つかりません(解析・書き出しに必要)。黒い画面で <code>winget install Gyan.FFmpeg</code> を実行し、start.bat で起動し直してください');
      if (t.ytdlp === false) miss.push('<b>yt-dlp</b> が見つかりません(YouTube の解析・書き出しに必要)。黒い画面で <code>winget install yt-dlp.yt-dlp</code>。手元のファイルだけなら要りません');
      if (n) { n.innerHTML = miss.length ? '<div><b>準備が必要です</b><br>' + miss.join('<br>') + '</div>' : ''; n.hidden = !miss.length; }
    }
    function mountReg() {
      var d = q('#nwSetReg'), host = q('#nwRegHost');
      if (regMounted || !d || !d.open || !host) return;
      if (Studio.rank && Studio.rank.mountRegistry) { regMounted = true; Studio.rank.mountRegistry(host); } else host.innerHTML = '<p class="hint">事務所の登録を読み込めませんでした(rank.js)。もう一度開いてください。</p>';
    }
    function mountCollab() {
      var d = q('#nwSetCollab'), host = q('#nwCollabHost');
      if (!d || !d.open || !host) return;
      if (!collabP) {
        var prev = window.Studio;
        window.Studio = Studio;   // collab.js も読み込みの時点で window.Studio を取る(rank.js と同じ)
        collabP = loadScript(COLLAB_JS).then(function () {
          if (prev === undefined) delete window.Studio; else window.Studio = prev;
        }, function (e) { if (prev === undefined) delete window.Studio; else window.Studio = prev; collabP = null; throw e; });
      }
      collabP.then(function () {
        if (dead || !q('#nwCollabHost')) return;
        if (Studio.collab && Studio.collab.mount) Studio.collab.mount(host); else host.innerHTML = '<p class="hint">コラボの部品を読み込めませんでした。画面を読み込み直してください。</p>';
      }, function (e) { if (!dead) host.innerHTML = '<p class="hint">' + esc(e.message) + '</p>'; });
    }
    function openSet(which) {
      var d = q('#nwSet'), sec = q(SET_SECS[which]);
      if (!d || !sec) return;
      d.open = true;
      if (sec.tagName === 'DETAILS') sec.open = true;
      if (which === 'setReg') mountReg();
      if (which === 'setCollab') mountCollab();
      requestAnimationFrame(function () {
        sec.scrollIntoView({ block: 'start', behavior: 'smooth' });
        if (which === 'setKey') { var f = q('#nwKeyIn'); if (f) f.focus({ preventScroll: true }); }
      });
    }
    function saveKey(v, btn) {
      var m = q('#nwKeyMsg');
      if (!m || btn.disabled) return;
      m.textContent = '';
      if (btn.id === 'nwKeySave' && !v) { m.textContent = 'キーを入力してください'; return; }   // 空の保存 = 削除にしない(削除は「キーを削除」だけ)
      if (btn.id === 'nwKeyDel' && !(Studio.state && Studio.state.hasKey)) { m.textContent = 'キーは設定されていません'; return; }
      btn.disabled = true;
      Studio.api('/api/config', { method: 'PUT', body: { apiKey: v } }).then(function () {
        var inp = q('#nwKeyIn'); if (inp) inp.value = '';
        return Studio.refreshState();
      }).then(function () {
        var env = Studio.state && Studio.state.keySource === 'env';
        if (q('#nwKeyMsg')) q('#nwKeyMsg').textContent = (v ? '保存しました' : '削除しました') + (env ? '(環境変数のキーがあるので、そちらが使われます)' : '');
        UIKit.toast(v ? 'API キーを保存しました' : 'API キーを削除しました', { ms: 3000, kind: 'ok' });
      }, function (e) { if (q('#nwKeyMsg')) q('#nwKeyMsg').textContent = e.message; }).then(function () { btn.disabled = false; });
    }
    function wireSet() {
      q('#nwKeySave').addEventListener('click', function () { saveKey(q('#nwKeyIn').value.trim(), q('#nwKeySave')); });
      q('#nwKeyIn').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); q('#nwKeySave').click(); } });
      q('#nwKeyDel').addEventListener('click', function () {
        var b = q('#nwKeyDel');
        if (!(Studio.state && Studio.state.hasKey)) { saveKey('', b); return; }
        /* キーを削除は取り消せない(もう一度貼り付けが要る)ので確かめる */
        UIKit.dialog.confirm({ title: 'API キーを削除しますか?', body: '保存してある YouTube Data API キーを消します。配信を探すにはキーをもう一度貼り付けます。', ok: '削除する', danger: true }).then(function (ok) { if (ok) saveKey('', b); });
      });
      q('#nwSetReg').addEventListener('toggle', mountReg);
      q('#nwSetCollab').addEventListener('toggle', mountCollab);
      Studio.on('state', paintSet);
    }

    /* パネルが見えている間だけ step = 'rank'(rank.js・queue.js の見回りは「見えている間」だけ動く)*/
    function setStep(step) { Studio.step = step; emit('step', step); }

    function start() {
      var prev = window.Studio;
      window.Studio = Studio;   // rank.js・queue.js は読み込みの時点で window.Studio を取る。読み終えたら元に戻す
      return loadScript(RANK_JS).then(function () { return loadScript(QUEUE_JS); }).then(function () {
        if (prev === undefined) delete window.Studio; else window.Studio = prev;
        if (dead) return;
        Studio.ready = true;
        started = true;
        readyFns.splice(0).forEach(function (fn) { try { fn(); } catch (e) { UIKit.report('新しい案件のパネルの初期化に失敗しました: ' + (e && e.message), { stack: e && e.stack }); } });
        Studio.refreshState().catch(function () { /* API キーの有無が分からないだけ */ });
        if (params.media) applyMedia(params.media);
        if (visible) setStep('rank');
      }, function (e) {
        if (prev === undefined) delete window.Studio; else window.Studio = prev;
        throw e;
      });
    }

    function fail(message) {
      var p = box.querySelector('#paneRank') || box;
      p.innerHTML = '<div class="empty cs-fatal"><b>新しい案件の画面を読み込めませんでした</b>' + esc(message) +
        '<br>スタジオが動いていないかもしれません。ホームの「調子」で確かめてから、もう一度開いてください。<div class="cs-emptyacts"><button type="button" class="btn small" data-nw-retry>もう一度読み込む</button></div></div>';
      var b = p.querySelector('[data-nw-retry]');
      if (b) b.addEventListener('click', function () { if (loadP) loadP = null; begin(); });
    }
    function begin() {
      loadP = start().catch(function (e) { if (!dead) fail(e.message); loadP = null; });
    }

    /* ?url= で受けた配信の URL は、欄に入れるだけ(解析は押すまで始めない)*/
    function applyUrl(url) {
      if (!url) return;
      params.url = String(url).slice(0, 2000);
      var ta = box && box.querySelector('#qUrls');
      if (!ta) return;
      ta.value = params.url; ta.dispatchEvent(new Event('input', { bubbles: true }));
      var p = box.querySelector('#qParam'); if (p) p.hidden = false;
    }

    /* ?media= で受けた動画ファイルのパスは、「動画ファイル・コラボ・やり直し」の欄に入れるだけ(開いて見せる。解析は押すまで始めない)*/
    function applyMedia(path) {
      var inp = box && box.querySelector('#qPath');
      if (!inp) return;
      inp.value = String(path).slice(0, 1000); inp.dispatchEvent(new Event('input', { bubbles: true }));
      var det = inp.closest('details'); if (det) det.open = true;
    }

    return {
      id: 'new',
      mount: function (el, opts) {
        box = document.createElement('div');
        box.className = 'nw-panel';
        box.innerHTML = '<section id="paneRank" aria-label="新しい案件(配信を探す・URL から入れる)"><div class="cs-loading" aria-busy="true"><div class="ui-skel" style="height:18px;width:30%"></div><div class="ui-skel" style="height:120px;margin-top:14px"></div><div class="ui-skel" style="height:60px;margin-top:12px"></div></div></section>' + SET_HTML;
        el.appendChild(box);
        wireSet();
        params.url = opts && opts.url ? String(opts.url).slice(0, 2000) : '';   // queue.js が起動時に欄へ入れる
        params.media = opts && opts.media ? String(opts.media) : '';
        begin();
      },
      update: function (opts) {
        if (!opts) return;
        if (opts.url) { if (started) applyUrl(opts.url); else params.url = String(opts.url).slice(0, 2000); }
        if (opts.media) { if (started) applyMedia(opts.media); else params.media = String(opts.media); }
      },
      setVisible: function (on) { visible = !!on; if (started) setStep(visible ? 'rank' : ''); },
      focus: function () { var ta = box && box.querySelector('#qUrls'); if (ta) ta.focus({ preventScroll: true }); },
      openSettings: function (which) { Studio.openSettings(which); },
      whenReady: function () { return loadP || Promise.resolve(); },
      unmount: function () { dead = true; visible = false; if (started) setStep(''); if (box) box.remove(); box = null; }
    };
  }

  window.NewCasePanel = { create: create };
  if (window.CasesPanels) window.CasesPanels.define('new', create);
})();
