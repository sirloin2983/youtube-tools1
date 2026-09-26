/* 入口の画面。/api/status を定期的に読んでツールの状態を出し、開く・起動・停止・再起動・すべて終了を送る。
   cut2resolve は「編集」の部品なのでカードを出さない(hidden)。止まっている・落ちた・見つからないときだけ出す(起動し直せるように)。
   ツール名・ログ・メッセージはすべて textContent で入れる(ログには動画の題名などが入るので、HTML として解釈させない)。 */
(function () {
  'use strict';
  var STEP = { studio: '1', transcribe: '2' };
  var LABEL = { starting: '起動中…', running: '動作中', external: '別の画面で起動済み', stopping: '停止中…', stopped: '停止', crashed: '異常終了', missing: '見つかりません' };
  var PILL = { starting: 'run', running: 'ok', external: 'info', stopping: 'wait', stopped: 'wait', crashed: 'err', missing: 'err' };
  var BUSY_LABEL = { start: '起動しています…', stop: '止めています…', restart: '再起動しています…' };
  var POLL_MS = 1500, POLL_HIDDEN_MS = 5000;
  var cards = {};        // id → {el, data}
  var busy = {};         // id → 実行中の操作(二重押し防止)
  var fails = 0, closed = false, timer = null, toastTimer = null, quitArmed = 0, quitTimer = null;
  var tokenMeta = document.querySelector('meta[name="ytt-token"]');
  var TOKEN = tokenMeta ? tokenMeta.content : '';   // 書き込み系の API の合言葉(CSRF トークン。サーバーが画面に入れる)

  function $(sel, el) { return (el || document).querySelector(sel); }

  /* fetch に時間の上限を付ける(止まりかけのサーバーで応答が返らないと、定期的な読み込みが止まってしまうため) */
  function fetchT(path, init, ms) {
    var ctl = window.AbortController ? new AbortController() : null, t = null;
    if (ctl) { init.signal = ctl.signal; t = setTimeout(function () { ctl.abort(); }, ms); }
    return fetch(path, init).then(function (r) { clearTimeout(t); return r; }, function (e) { clearTimeout(t); throw e; });
  }

  /* 入口の API。POST は JSON で送る(サーバーは application/json 以外を拒否する: 他サイトからのフォーム送信を防ぐため)。
     起動・停止・再起動は、止まるまで待つので時間の上限を長めにする */
  function api(path, method, body) {
    var init = { method: method || 'GET', cache: 'no-store', headers: {} };
    if (init.method === 'POST') { init.headers['Content-Type'] = 'application/json'; init.headers['X-YTT-Token'] = TOKEN; init.body = JSON.stringify(body || {}); }
    return fetchT(path, init, init.method === 'POST' ? 60000 : 8000).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.message || ('エラー(HTTP ' + r.status + ')')); e.status = r.status; throw e; }
        return j;
      });
    });
  }

  function toast(msg, kind) {
    var t = $('#toast');
    t.className = 'toast ' + (kind || 'info');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 5000);
  }

  /* 入口に取り込んだツールは同じアドレスの /studio/ など(path)。別のプログラムとして動いているものはそのポートの直下 */
  function toolUrl(t) {
    var path = /^\/(?:[a-z0-9][a-z0-9-]{0,31}\/)?$/.test(t.path || '') ? t.path : '/';
    return 'http://' + location.hostname + ':' + t.port + path;
  }

  function build(t) {
    var li = $('#tplTool').content.firstElementChild.cloneNode(true);
    li.setAttribute('data-tool', t.id);
    $('.pt-step', li).textContent = STEP[t.id] || '';
    var mark = $('.ui-brand-mark', li), icon = document.getElementById('icon-' + t.id);
    mark.setAttribute('data-tool', t.id);
    if (icon) mark.appendChild(icon.content.firstElementChild.cloneNode(true));
    $('.pt-name', li).textContent = t.name;
    $('.pt-sub', li).textContent = t.sub;
    $('.pt-toggle', li).addEventListener('click', function () {
      var s = cards[t.id].data.state;
      act(t.id, s === 'running' || s === 'starting' ? 'stop' : 'start');
    });
    $('.pt-restart', li).addEventListener('click', function () { act(t.id, 'restart'); });
    var box = $('.pt-logbox', li);
    box.addEventListener('toggle', function () { if (box.open) loadLog(t.id); });
    $('#flow').appendChild(li);
    return (cards[t.id] = { el: li, data: t });
  }

  function update(t) {
    if (t.hidden && !cards[t.id] && (t.state === 'running' || t.state === 'starting' || t.state === 'external')) return;   // 部品(cut2resolve)は困っているときだけ出す
    if (t.hidden && cards[t.id] && (t.state === 'running' || t.state === 'external') && !busy[t.id]) { cards[t.id].el.remove(); delete cards[t.id]; return; }
    var c = cards[t.id] || build(t);
    c.data = t;
    var el = c.el, b = busy[t.id], s = t.state;
    el.setAttribute('data-state', s);
    var pill = $('.pt-pill', el);
    pill.className = 'pill pt-pill ' + (b ? 'run' : (PILL[s] || ''));
    pill.textContent = b ? BUSY_LABEL[b] : (LABEL[s] || s);

    var meta = [];
    if (t.port) meta.push('ポート ' + t.port);
    if (t.version) meta.push('v' + t.version);
    if (t.mounted) meta.push('入口に取り込み');
    $('.pt-meta', el).textContent = meta.join(' · ');

    var msg = $('.pt-msg', el), text = t.message || (s === 'external' ? '別の黒い画面で起動したツールです。止めるときはその画面を閉じてください。' : '');
    msg.hidden = !text;
    msg.textContent = text;
    msg.className = 'notice pt-msg' + (s === 'crashed' || s === 'missing' ? ' danger' : (s === 'external' && t.message) ? '' : ' info');

    var open = $('.pt-open', el), up = (s === 'running' || s === 'external') && !!t.port && !b;
    if (up) { open.href = toolUrl(t); open.removeAttribute('aria-disabled'); }
    else { open.removeAttribute('href'); open.setAttribute('aria-disabled', 'true'); }

    var toggle = $('.pt-toggle', el), restart = $('.pt-restart', el);
    var runningHere = s === 'running' || s === 'starting';
    toggle.textContent = runningHere || s === 'stopping' || s === 'external' ? '停止' : '起動';
    toggle.disabled = !!b || closed || s === 'stopping' || s === 'external' || s === 'missing' || !!t.mounted;
    toggle.title = s === 'external' ? '別の黒い画面で起動したツールは、その画面で止めてください'
      : t.mounted ? '入口と一緒に動いています(「すべて終了」で一緒に終わります)' : '';
    restart.disabled = !!b || closed || !(t.managed && runningHere) || !!t.mounted;
    restart.title = t.mounted ? toggle.title : '';
    if (fails >= 2) { toggle.disabled = true; restart.disabled = true; }
  }

  function loadLog(id) {
    var c = cards[id];
    if (!c) return;
    var pre = $('.pt-log', c.el);
    api('/api/log?tool=' + encodeURIComponent(id) + '&lines=300').then(function (j) {
      var atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24;
      var text = j.exists ? (j.lines.length ? j.lines.join('\n') : '(まだ出力はありません)') : '(ログはまだありません)';
      if (c.data.state === 'external') text = '※ 別の黒い画面で起動したツールの出力は、その画面に出ています。下は、以前この入口から起動したときのログです。\n\n' + text;
      if (pre.textContent !== text) {
        pre.textContent = text;
        if (atBottom) pre.scrollTop = pre.scrollHeight;
      }
      $('.pt-logpath', c.el).textContent = 'ログの場所: ' + j.log;
    }).catch(function () { /* 次の読み込みで直る */ });
  }

  function setConn(ok) {
    var p = $('#conn'), bar = $('#errbar');
    p.className = 'pill ' + (ok ? 'ok' : 'err');
    p.textContent = ok ? '接続中' : '切断';
    bar.hidden = ok;
    bar.textContent = ok ? '' : '入口のサーバーに接続できません。黒い画面が閉じられた可能性があります。start-all.bat をダブルクリックして起動し直してください。';
  }

  function poll() {
    if (closed) return;
    clearTimeout(timer);
    api('/api/status').then(function (st) {
      fails = 0;
      setConn(true);
      $('#ver').textContent = '入口 v' + st.version;
      if (st.dataDir) { $('#dataDir').textContent = st.dataDir; $('#dataBox').hidden = false; }
      if (st.window) renderWin(st.window);
      st.tools.forEach(update);
      Object.keys(cards).forEach(function (id) { if ($('.pt-logbox', cards[id].el).open) loadLog(id); });
    }).catch(function () {
      fails++;
      if (fails >= 2) { setConn(false); Object.keys(cards).forEach(function (id) { update(cards[id].data); }); }
    }).then(function () {
      if (!closed) timer = setTimeout(poll, document.hidden ? POLL_HIDDEN_MS : POLL_MS);
    });
  }

  function act(id, action) {
    if (busy[id] || closed) return;
    busy[id] = action;
    update(cards[id].data);
    api('/api/tools/' + encodeURIComponent(id) + '/' + action, 'POST').then(function (j) {
      delete busy[id];
      if (j.tool) update(j.tool);
    }).catch(function (e) {
      delete busy[id];
      update(cards[id].data);
      toast(e.message || '操作に失敗しました', 'err');
    }).then(poll);
  }

  /* 窓で開く(試用。段階7-3): Edge のアプリモードの窓。設定は次に起動したときから。窓の中のリンクは ui-kit(UIKit.win)が入口に頼んで開く */
  var winBusy = false;
  function inApp() { return !!(window.UIKit && UIKit.win && UIKit.win.isApp()); }
  function renderWin(w) {
    if (winBusy) return;
    var box = $('#winBox'), sw = $('#winMode'), now = $('#btnWinNow');
    box.hidden = false;
    sw.checked = w.mode === 'app';
    sw.disabled = !w.available && w.mode !== 'app';   // Edge が無くても、オフには戻せる
    var text = w.available
      ? 'オンにすると、次に start-all.bat で起動したときから、ブラウザのタブではなく Microsoft Edge の専用の窓で開きます。' +
        '窓の中のリンクも窓で開き、YouTube などの外のサイトはいつものブラウザで開きます。窓の設定・拡張機能・ログインは、いつものブラウザと別です。' +
        '合わなければオフに戻すだけで元どおりです。'
      : 'Microsoft Edge が見つからないので、窓では開けません(いつものブラウザで開きます)。';
    if (inApp()) text += '(いまは窓で開いています)';
    $('#winHint').textContent = text;
    now.hidden = !w.available || inApp();
  }
  function setWin(mode) {
    winBusy = true;
    api('/api/window', 'POST', { mode: mode }).then(function (j) {
      winBusy = false;
      renderWin(j.window);
      toast(mode === 'app' ? '次に起動したときから、窓で開きます(いま開くなら「いま窓で開く」)' : '次に起動したときから、いつものブラウザで開きます', 'ok');
    }).catch(function (e) {
      winBusy = false;
      toast('設定を保存できませんでした: ' + e.message, 'err');
      poll();
    });
  }
  function openWinNow() {
    if (!(window.UIKit && UIKit.win)) return;
    UIKit.win.open(location.origin + '/').then(function () {
      toast('窓で開きました。このタブは閉じてかまいません', 'ok');
    }, function (e) { toast('窓で開けませんでした: ' + e.message, 'err'); });
  }

  /* すべて終了: 誤操作を防ぐため2回押し(4秒以内)。あと何秒で確認が消えるかを見せる(audit #5: 見えないと不安になる) */
  var quitCountdown = null;
  function resetQuit() {
    var b = $('#btnQuit');
    quitArmed = 0;
    clearInterval(quitCountdown);
    b.textContent = 'すべて終了';
    b.classList.remove('solid');
  }
  function armQuit() {
    var b = $('#btnQuit');
    quitArmed = Date.now();
    b.classList.add('solid');
    clearTimeout(quitTimer);
    clearInterval(quitCountdown);
    var tick = function () {
      var left = Math.ceil((4000 - (Date.now() - quitArmed)) / 1000);
      if (left <= 0) { resetQuit(); return; }
      b.textContent = 'もう一度押すと終了します(あと' + left + '秒)';
    };
    tick();
    quitCountdown = setInterval(tick, 250);
    quitTimer = setTimeout(resetQuit, 4000);
  }
  function quit() {
    var b = $('#btnQuit');
    if (!quitArmed || Date.now() - quitArmed > 4000) { armQuit(); return; }
    clearTimeout(quitTimer);
    clearInterval(quitCountdown);
    b.disabled = true;
    b.textContent = '終了しています…';
    api('/api/shutdown', 'POST').then(function () {
      closed = true;
      clearTimeout(timer);
      $('#main').hidden = true;
      $('#done').hidden = false;
      waitGone(0);
    }).catch(function (e) {
      b.disabled = false;
      resetQuit();
      toast(e.message || '終了できませんでした', 'err');
    });
  }
  /* サーバーが応答しなくなったら終了 */
  function waitGone(n) {
    fetchT('/api/ping', { cache: 'no-store' }, 2000).then(function () {
      if (n < 40) setTimeout(function () { waitGone(n + 1); }, 700);
      else doneText('終了に時間がかかっています', '黒い画面が残っていれば、その画面を閉じてください。');
    }).catch(function () {
      doneText('すべて終了しました', 'この画面(タブ・窓)は閉じてかまいません。もう一度使うときは start-all.bat をダブルクリックしてください。');
    });
  }
  function doneText(title, text) { $('#doneTitle').textContent = title; $('#doneText').textContent = text; }

  document.addEventListener('DOMContentLoaded', function () {
    $('#btnQuit').addEventListener('click', quit);
    $('#winMode').addEventListener('change', function () { setWin(this.checked ? 'app' : 'browser'); });
    $('#btnWinNow').addEventListener('click', openWinNow);
    $('#btnCopyData').addEventListener('click', function () {
      var t = $('#dataDir').textContent;
      if (!t) return;
      (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(
        function () { toast('パスをコピーしました'); },
        function () { toast('コピーできませんでした。パスを選んでコピーしてください', 'err'); });
    });
    $('#toast').addEventListener('click', function () { this.hidden = true; });
    /* タブ・窓に戻ったらすぐ読み直す(ui-kit の UIKit.life。窓を並べて使うとタブの切り替えは来ないため。段階7-2) */
    if (window.UIKit && UIKit.life) UIKit.life.onReturn(function () { poll(); });
    else document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });
    poll();
  });
})();
