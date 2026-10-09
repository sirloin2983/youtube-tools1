/* 設定の画面(/settings = 入口の直下の 1 枚。部品は src/home/settings/。設定を 1 つに S5。docs/spec/settings.md の 4)。
   スキーマ schema.json(鍵・型・範囲・既定値・ラベル・説明)を読み、UIKit.settingsForm が節を描く。値の置き場所(store)ごとに読み書きの口を 1 つずつ:
     home      … 入口の api/ytt/prefs(節ごと。入れ子の鍵は {auto: {after: …}} の形で送る = 送った鍵だけ直る)
     studio    … studio/api/settings(節を丸ごと置き換えるので、今の節に鍵を 1 つ直して送る)・outDir は studio/api/outdir
     editor    … transcribe/api/settings(validated の鍵は api/settings/patch で検査つき・ほかは差分の PUT。入れ子は最上位の物を丸ごと)
     analytics … analytics/api/config
   ツールが動いていない(取り込まれていない)ときは、その節の欄を無効にして理由を出す。API の URL は相対(この画面は入口の直下にあるので、studio/… がそのまま取り込んだツール)。
   CSP(script-src 'self')の下で動く: インラインの script・onclick は書かない。 */
(function () {
  'use strict';
  var $ = function (s, el) { return (el || document).querySelector(s); };
  var API_TEXT = { offline: 'サーバーにつながりませんでした(start.bat の黒い画面が閉じていないか確かめてください)' };
  function home(path, body) { return UIKit.homeApi(path, Object.assign({ body: body, timeout: 15000 }, API_TEXT)); }
  function tool(base, path, opt) { return UIKit.http(new URL(base + path, location.href).href, Object.assign({ timeout: 15000 }, API_TEXT, opt || {})); }
  function pathGet(obj, parts) { var o = obj; for (var i = 0; i < parts.length; i++) { if (o == null || typeof o !== 'object') return undefined; o = o[parts[i]]; } return o; }
  function nest(parts, v) { var out = v; for (var i = parts.length - 1; i >= 0; i--) { var o = {}; o[parts[i]] = out; out = o; } return out; }
  function clone(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
  function offText(name, e) {
    if (e && e.code === 'network') return name + 'につながりません(ホームが止まっているか、起動し直しの途中)。';
    return name + 'は動いていません(ホームに取り込まれていません)。ここの値は読めず、変えられません。';
  }

  /* ---- 置き場所ごとの読み書き ---- */
  var HOME = {
    name: 'ホーム', data: {}, off: '',
    sections: ['autorun', 'intake', 'backup', 'accuracy', 'live'],
    load: function () {
      return home('api/ytt/prefs', { op: 'get', sections: HOME.sections }).then(function (j) { HOME.data = j.prefs || {}; HOME.off = ''; },
        function (e) { HOME.off = offText('ホームの設定', e); throw e; });
    },
    get: function (key) { return pathGet(HOME.data, key.split('.')); },
    set: function (key, v) {
      var parts = key.split('.'), section = parts[0];
      return home('api/ytt/prefs', { op: 'patch', section: section, value: nest(parts.slice(1), v) }).then(function (j) { HOME.data[section] = j.value; });
    },
    disabled: function () { return HOME.off; }
  };
  var STUDIO = {
    name: 'スタジオ', base: 'studio/', data: {}, state: {}, off: '',
    load: function () {
      return Promise.all([tool(STUDIO.base, 'api/settings'), tool(STUDIO.base, 'api/state')]).then(function (r) {
        STUDIO.data = (r[0] && r[0].settings) || {}; STUDIO.state = r[1] || {}; STUDIO.off = '';
      }, function (e) { STUDIO.off = offText('切り抜きスタジオ', e); throw e; });
    },
    get: function (key) {
      if (key === 'outDir') { var s = STUDIO.state; return s.outDir && s.outDir !== s.defaultOutDir ? s.outDir : ''; }
      return pathGet(STUDIO.data, key.split('.'));
    },
    set: function (key, v) {
      if (key === 'outDir') return tool(STUDIO.base, 'api/outdir', { method: 'PUT', body: { path: v } }).then(function (j) { STUDIO.state.outDir = j.outDir; STUDIO.state.defaultOutDir = j.defaultOutDir; });
      var parts = key.split('.'), section = parts[0], obj = Object.assign({}, STUDIO.data[section] || {});
      obj[parts[1]] = v;
      return tool(STUDIO.base, 'api/settings', { method: 'PUT', body: { section: section, value: obj } }).then(function () { STUDIO.data[section] = obj; });
    },
    disabled: function () { return STUDIO.off; }
  };
  var EDITOR = {
    name: '編集', base: 'transcribe/', data: {}, off: '', validated: {},
    load: function () {
      return tool(EDITOR.base, 'api/settings').then(function (j) { EDITOR.data = j && typeof j === 'object' ? j : {}; EDITOR.off = ''; },
        function (e) { EDITOR.off = offText('編集', e); throw e; });
    },
    get: function (key) { return pathGet(EDITOR.data, key.split('.')); },
    set: function (key, v) {
      var parts = key.split('.'), top = parts[0], value = v;
      if (parts.length > 1) {   /* 入れ子は最上位の物を丸ごと(ほかの鍵は今の値のまま。subtitle.splitChars などを消さない) */
        value = clone(EDITOR.data[top]); if (value == null || typeof value !== 'object') value = {};
        var o = value; for (var i = 1; i < parts.length - 1; i++) { if (o[parts[i]] == null || typeof o[parts[i]] !== 'object') o[parts[i]] = {}; o = o[parts[i]]; }
        o[parts[parts.length - 1]] = v;
      }
      var p = EDITOR.validated[top] ? tool(EDITOR.base, 'api/settings/patch', { method: 'POST', body: { values: nest([top], value) } })
        : tool(EDITOR.base, 'api/settings', { method: 'PUT', body: { patch: nest([top], value) } });
      return p.then(function () { EDITOR.data[top] = value; });
    },
    disabled: function () { return EDITOR.off; }
  };
  var ANALYTICS = {
    name: '分析と日報', base: 'analytics/', data: {}, off: '',
    load: function () {
      return tool(ANALYTICS.base, 'api/state').then(function (j) { ANALYTICS.data = (j && j.config) || {}; ANALYTICS.off = ''; },
        function (e) { ANALYTICS.off = offText('分析と日報', e); throw e; });
    },
    get: function (key) { return ANALYTICS.data[key]; },
    set: function (key, v) {
      var body = {}; body[key === 'planPerWeek' ? 'plan' : key] = v;
      return tool(ANALYTICS.base, 'api/config', { method: 'POST', body: body }).then(function (j) { ANALYTICS.data = (j && j.config) || ANALYTICS.data; });
    },
    disabled: function () { return ANALYTICS.off; }
  };
  var STORES = { home: HOME, studio: STUDIO, editor: EDITOR, analytics: ANALYTICS };

  /* ---- 描く ---- */
  var SCHEMA = null, forms = [];
  function io(store) { return { get: store.get, set: store.set, disabled: store.disabled }; }
  function secEl(sec) {
    var el = document.createElement('section'); el.className = 'st-sec'; el.id = 'sec-' + sec.id; el.setAttribute('data-st-sec', sec.id);
    var h2 = document.createElement('h2'); h2.textContent = sec.title; el.appendChild(h2);
    if (sec.hint) { var p = document.createElement('p'); p.className = 'hint'; p.textContent = sec.hint; el.appendChild(p); }
    return el;
  }
  function render() {
    var host = $('#stSections'), nav = $('#stNav');
    host.innerHTML = ''; nav.innerHTML = ''; forms = [];
    SCHEMA.sections.forEach(function (sec) {
      var el = secEl(sec), store = sec.store ? STORES[sec.store] : null;
      if (store && store.off) { var pill = document.createElement('span'); pill.className = 'pill'; pill.textContent = '動いていません'; el.querySelector('h2').appendChild(pill); }
      if (sec.kind === 'general') el.appendChild(UIKit.settings.general());
      (sec.groups || []).forEach(function (g) {
        var st = g.store ? STORES[g.store] : store;
        g.items.forEach(function (it) { if (it.validated && st === EDITOR) EDITOR.validated[it.key.split('.')[0]] = true; });
        forms.push(UIKit.settingsForm.render(el, g, st ? io(st) : { get: function () { return undefined; }, set: function () { return Promise.resolve(); }, disabled: function () { return ''; } }));
      });
      host.appendChild(el);
      var a = document.createElement('a'); a.href = '#sec-' + sec.id; a.textContent = sec.title; a.setAttribute('data-st-nav', sec.id);
      if (store && store.off) a.classList.add('st-nav-off');
      nav.appendChild(a);
    });
    watchNav();
  }
  function watchNav() {
    var links = {}; [].forEach.call(document.querySelectorAll('[data-st-nav]'), function (a) { links[a.getAttribute('data-st-nav')] = a; });
    var secs = [].slice.call(document.querySelectorAll('[data-st-sec]'));
    function mark(id) { Object.keys(links).forEach(function (k) { if (k === id) links[k].setAttribute('aria-current', 'true'); else links[k].removeAttribute('aria-current'); }); }
    if (!('IntersectionObserver' in window)) { if (secs[0]) mark(secs[0].getAttribute('data-st-sec')); return; }
    var seen = {};
    var ob = new IntersectionObserver(function (es) {
      es.forEach(function (e) { seen[e.target.getAttribute('data-st-sec')] = e.isIntersecting; });
      for (var i = 0; i < secs.length; i++) { var id = secs[i].getAttribute('data-st-sec'); if (seen[id] && !secs[i].classList.contains('st-nomatch')) { mark(id); return; } }
    }, { rootMargin: '-80px 0px -60% 0px' });
    secs.forEach(function (s) { ob.observe(s); });
  }
  function applyFilter() {
    var q = $('#stSearch').value, n = 0;
    [].forEach.call(document.querySelectorAll('[data-st-sec]'), function (sec) {
      var k = UIKit.settingsForm.filter(sec, q);
      var general = !sec.querySelector('[data-ui-set-group]');
      sec.classList.toggle('st-nomatch', !!q.trim() && k === 0 && !general);
      if (general) sec.classList.toggle('st-nomatch', !!q.trim() && (sec.textContent || '').toLowerCase().indexOf(q.trim().toLowerCase()) < 0);
      n += k;
    });
    $('#stCount').textContent = q.trim() ? n + ' 件' : '';
  }
  function copyJson() {
    var out = { home: HOME.data, studio: STUDIO.data, editor: EDITOR.data, analytics: ANALYTICS.data, outDir: STUDIO.state.outDir || '' };
    UIKit.copy(JSON.stringify(out, null, 1), { ok: '今の設定を JSON の文字でコピーしました', fail: 'コピーできませんでした(ブラウザが拒みました)' });
  }
  function load() {
    var stores = [HOME, STUDIO, EDITOR, ANALYTICS];
    return Promise.all(stores.map(function (s) { return s.load().then(null, function () { /* off に理由を入れた */ }); })).then(function () {
      var off = stores.filter(function (s) { return s.off; });
      var bar = $('#stOffline');
      if (HOME.off) { bar.textContent = HOME.off; bar.hidden = false; } else bar.hidden = true;
      $('#stLoading').remove();
      render();
      applyFilter();
      if (location.hash) { var t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
      return off.length;
    });
  }
  document.addEventListener('DOMContentLoaded', function () {
    if (!UIKit.tools.mounted()) { $('#stOffline').textContent = 'ホーム(start.bat)から開いたときだけ使えます。'; $('#stOffline').hidden = false; }
    UIKit.homeApi('api/status', { method: 'GET', timeout: 8000 }).then(function (j) { if (j && j.version) $('#ver').textContent = 'v' + j.version; }, function () { /* 版が出ないだけ */ });
    var timer = 0;
    $('#stSearch').addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(applyFilter, 120); });
    document.addEventListener('ui-set-changed', function () { forms.forEach(function (f) { f.refresh(); }); applyFilter(); });   /* ほかの節の when も描き直す */
    $('#stCopy').addEventListener('click', copyJson);
    UIKit.http(new URL('settings-schema.json', location.href).href, { timeout: 8000 }).then(function (j) { SCHEMA = j; return load(); }).then(null, function (e) {
      $('#stLoading').textContent = '設定を読み込めませんでした: ' + ((e && e.message) || '');
    });
  });
  window.YttSettings = { stores: STORES, reload: load, filter: applyFilter };   /* 画面のテスト(e2e_settings.py)が読む */
})();
