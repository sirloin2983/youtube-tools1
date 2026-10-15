/* 分析と日報の画面。API は相対パス(api/…)。書き込みは合言葉(X-YTT-Token)付き(入口が <meta name="ytt-token"> で渡す) */
(function () {
  'use strict';
  var KIND_NAMES = { daily: '日報', weekly: '週報', monthly: '月報' };
  var view = 'daily';
  var runKind = 'daily';
  var last = null;
  var timer = null;

  function $(id) { return document.getElementById(id); }
  function token() { var m = document.querySelector('meta[name="ytt-token"]'); return m ? m.content : ''; }

  function api(path, body) {
    var opt = { headers: {} };
    if (body !== undefined) {
      opt.method = 'POST';
      opt.headers['Content-Type'] = 'application/json';
      opt.headers['X-YTT-Token'] = token();
      opt.body = JSON.stringify(body);
    }
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.message || ('エラー ' + r.status)); e.code = j.error; throw e; }
        return j;
      });
    });
  }

  function fmtTime(v) {
    if (!v) return '—';
    var d = typeof v === 'number' ? new Date(v) : new Date(v);
    if (isNaN(d.getTime())) return String(v);
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function render(s) {
    last = s;
    $('ver').textContent = 'v' + s.version;
    var st = $('state');
    st.textContent = s.stateLabel + (s.message ? ' — ' + s.message : '');
    st.className = 'an-state' + (s.state === 'error' ? ' error' : '');
    $('latest').textContent = s.latestRaw ? '最新のデータ: ' + fmtTime(s.latestRaw.fetchedAt) + ' にタップした分(' + s.latestRaw.name + ')' : 'まだデータを受け取っていません';
    var busy = s.busy || s.state === 'running';
    $('run-send').disabled = busy || !s.config.url;
    $('run-only').disabled = busy || !s.config.url;
    if (!$('cfg-box').dataset.loaded) {
      $('url').value = s.config.url || '';
      $('secret').placeholder = s.config.hasSecret ? '設定済み(変えるときだけ入れる)' : 'makeSecret が出した合言葉';
      $('enabled').checked = s.config.enabled !== false;
      $('plan').value = s.config.planPerWeek || 28;
      $('boundary').value = s.config.boundary || '';
      $('cfg-box').open = !s.config.url || !s.config.hasSecret;
      $('cfg-box').dataset.loaded = '1';
    }
    renderPeriods();
    var ul = $('runs');
    ul.textContent = '';
    (s.runs || []).forEach(function (r) {
      var li = document.createElement('li');
      var t = fmtTime(r.at) + (r.manual ? '(手動)' : '') + ' 受け取り ' + r.fetched + ' 件' + (r.sent.length ? '・作成 ' + r.sent.join('、') : '');
      li.textContent = t;
      if (r.errors && r.errors.length) {
        var e = document.createElement('span');
        e.className = 'err';
        e.textContent = ' ' + r.errors.join(' / ');
        li.appendChild(e);
      }
      ul.appendChild(li);
    });
    if (!ul.firstChild) { var li = document.createElement('li'); li.textContent = 'まだ実行していません'; ul.appendChild(li); }
    clearTimeout(timer);
    timer = setTimeout(load, busy ? 3000 : 30000);
  }

  function renderPeriods() {
    var list = (last && last.reports && last.reports[view]) || [];
    var sel = $('period');
    var cur = sel.value;
    sel.textContent = '';
    list.forEach(function (x) {
      var o = document.createElement('option');
      o.value = x.period;
      o.textContent = x.period + (x.sent ? '' : '(未送信)');
      sel.appendChild(o);
    });
    if (cur && list.some(function (x) { return x.period === cur; })) sel.value = cur;
    $('empty').hidden = list.length > 0;
    $('frame').hidden = list.length === 0;
    showFrame();
  }

  function showFrame() {
    var sel = $('period');
    var list = (last && last.reports && last.reports[view]) || [];
    var x = list.filter(function (r) { return r.period === sel.value; })[0];
    $('sent').textContent = x ? (x.sent ? 'LINE に送った: ' + fmtTime(x.sentAt) : 'LINE には送っていません') : '';
    var src = x ? 'report/' + view + '/' + encodeURIComponent(x.period) + '.html' : 'about:blank';
    var f = $('frame');
    if (f.getAttribute('src') !== src) f.setAttribute('src', src);
    var a = $('open');
    a.hidden = !x;
    if (x) a.setAttribute('href', src);
  }

  function load() { api('api/state').then(render).catch(function (e) { $('state').textContent = '状態を読めませんでした: ' + e.message; }); }

  function run(send) {
    var what = KIND_NAMES[runKind] + (send ? 'を作って LINE に送ります。' : 'を作り直します(LINE には送りません)。');
    $('state').textContent = what;
    api('api/run', { kind: runKind, send: send }).then(function (s) { view = runKind; selectTab(); render(s); })
      .catch(function (e) { $('state').textContent = e.message; $('state').className = 'an-state error'; });
  }

  function selectTab() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-view]'), function (b) { b.setAttribute('aria-selected', String(b.dataset.view === view)); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(document.querySelectorAll('[data-kind]'), function (b) {
      b.addEventListener('click', function () {
        runKind = b.dataset.kind;
        Array.prototype.forEach.call(document.querySelectorAll('[data-kind]'), function (x) { x.setAttribute('aria-pressed', String(x === b)); });
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-view]'), function (b) {
      b.addEventListener('click', function () { view = b.dataset.view; selectTab(); $('period').value = ''; renderPeriods(); });
    });
    $('period').addEventListener('change', showFrame);
    $('run-send').addEventListener('click', function () { run(true); });
    $('run-only').addEventListener('click', function () { run(false); });
    $('cfg').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var body = { url: $('url').value.trim(), enabled: $('enabled').checked, plan: Number($('plan').value) || 28 };
      if ($('boundary').value) body.boundary = $('boundary').value;
      if ($('secret').value.trim()) body.secret = $('secret').value.trim();
      api('api/config', body).then(function () {
        $('secret').value = '';
        $('cfg-msg').textContent = '保存しました';
        $('cfg-box').dataset.loaded = '';
        load();
      }).catch(function (e) { $('cfg-msg').textContent = e.message; });
    });
    $('ping').addEventListener('click', function () {
      $('cfg-msg').textContent = '確かめています…';
      api('api/ping', {}).then(function (r) {
        $('cfg-msg').textContent = 'つながりました' + (r.folder ? '(Drive のフォルダも開けます)' : '(Drive のフォルダが開けません。DRIVE_FOLDER_ID を確かめてください)');
      }).catch(function (e) { $('cfg-msg').textContent = e.message; });
    });
    load();
  });
}());
