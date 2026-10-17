/* 友人のアプリの共通の部分(F3)。口は friendapp/server.py の説明。外から来た文字(題・名前・理由)は textContent でだけ入れる。
   ここ = [送る] / [受け取る] の切り替え・3 秒おきの問い合わせ(送った物の行・受け取る物)を各部品へ配る(FR.on)・⚙・初回の準備・上の帯・止めて終了。
   部品: send-list.js(配信の一覧)・send-form.js(送る欄)・sent.js(送った物)・receive.js(受け取る) */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var POLL = 3000, POLL_AWAY = 10000;
  var subs = [], timer = 0, listTimer = 0, view = 'send', undecided = 0;
  var st = { partsWhy: '', setupKey: '', setupRun: false, hasKey: true, inbox: null, receive: null, form: null };

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'cls') e.className = attrs[k];
      else if (k === 'on') Object.keys(attrs.on).forEach(function (ev) { e.addEventListener(ev, attrs.on[ev]); });
      else if (attrs[k] === true) e.setAttribute(k, '');
      else if (attrs[k] !== false && attrs[k] != null) e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  function api(path, body) { return UIKit.http('api/friend/' + path, body === undefined ? {} : { body: body }); }
  function sizeText(n) { return n == null ? '不明' : n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : Math.max(1, Math.round(n / 1e6)) + ' MB'; }
  function fail(what, e) { UIKit.toast(what + ': ' + e.message, { kind: 'err', detail: e.detail, ms: 6000 }); }
  function dur(sec) {
    if (sec == null) return '';
    sec = Math.round(sec);
    var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60, p = function (n) { return (n < 10 ? '0' : '') + n; };
    return (h ? h + ':' + p(m) : String(m)) + ':' + p(s);
  }
  function token() { var m = document.querySelector('meta[name="ytt-token"]'); return m ? m.content : ''; }
  /* 文字を打つ場所か(Ctrl+V・Esc・Space の扱いを変える) */
  function typing(t) {
    t = t || document.activeElement;
    if (!t || !t.tagName) return false;
    return /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable || t.getAttribute('role') === 'spinbutton';
  }

  /* ---------------------------------------------------------------- [送る] / [受け取る](C-2-1) */
  function show(v) {
    view = v === 'receive' ? 'receive' : 'send';
    $('viewSend').hidden = view !== 'send';
    $('viewReceive').hidden = view !== 'receive';
    $('tabSend').setAttribute('aria-pressed', view === 'send' ? 'true' : 'false');
    $('tabReceive').setAttribute('aria-pressed', view === 'receive' ? 'true' : 'false');
    if (location.hash !== '#' + view) history.replaceState(null, '', '#' + view);
    emit('view', view);
    if (view === 'send') pollList();
  }
  function pollList() {   /* 一覧は送る画面を出している間だけ問い合わせる(玄関の中の写しを読むだけ = 軽い) */
    clearTimeout(listTimer);
    if (view !== 'send' || !window.FRList) return;
    FRList.load().catch(function () { /* 玄関とつながらない = 上の帯が知らせる */ }).then(function () {
      listTimer = setTimeout(pollList, UIKit.life.isAway() ? POLL_AWAY : POLL);
    });
  }
  function setCount(n) {   /* ●n = まだ決めていない本数(C-3-9)。窓のタイトルにも(窓はタイトルを写す = F3-A) */
    undecided = n;
    $('tabN').hidden = !n;
    $('tabN').textContent = n ? String(n) : '';
    $('tabReceive').setAttribute('aria-label', n ? '受け取る(まだ決めていない ' + n + ' 本)' : '受け取る');
    document.title = n ? '切り抜き(' + n + ')' : '切り抜き';
  }

  /* ---------------------------------------------------------------- 配る */
  function on(fn) { subs.push(fn); }
  function emit(what, data) { subs.forEach(function (fn) { try { fn(what, data); } catch (e) { if (window.console) console.error(e); } }); }

  function banner(j) {
    var sy = j.sync || {};
    st.hasKey = sy.key !== false;
    $('noKey').hidden = !sy.message;
    $('noKey').textContent = sy.message || '';
    $('updated').hidden = !sy.updated || st.updatedSeen === sy.updated;
    $('updatedText').textContent = sy.updated ? '新しい版 ' + sy.updated + ' を入れました(次に開いたときから)' : '';
    var p = j.prep || {};
    $('prep').hidden = p.state === 'ready';
    $('prep').textContent = p.message || '';
    $('prep').classList.toggle('err', p.state === 'error');
    var old = (j.rollback ? j.rollback + '。' : '') + (j.notice ? '前の部品 ' + j.notice.freedGB + ' GB を片付けました' : '');
    var cl = st.receive && st.receive.notice;
    $('cleaned').hidden = !(old || cl);
    $('cleanedText').textContent = old || (cl ? '3 日たった ' + cl.n + ' 本を片付けました' : '');
    $('cleaned').setAttribute('data-what', old ? 'old' : 'cleaned');
    $('setPcUser').disabled = !st.hasKey;
    $('setPcUserLabel').title = st.hasKey ? '' : 'Dropbox の鍵が無いので選べません';
  }
  function refresh() {
    clearTimeout(timer);
    return Promise.all([api('inbox'), api('receive')]).then(function (got) {
      var j = got[0];
      $('errbar').hidden = true;
      st.inbox = j; st.receive = got[1]; st.form = j.form;
      $('btnSaved').title = '受け取った物の保存先を開きます: ' + (j.saveDir || '');
      setupView(j.setup);
      banner(j);
      setCount(got[1].undecided || 0);
      emit('data', { inbox: j, receive: got[1] });
    }, function (e) {
      $('errbar').hidden = false;
      $('errbar').textContent = 'アプリとつながりません。アプリを開き直してください';
      if (window.console) console.warn(e.message);
    }).then(function () { timer = setTimeout(refresh, UIKit.life.isAway() ? POLL_AWAY : POLL); });
  }

  /* ---------------------------------------------------------------- 初回の準備(F2-5。F3-5 で作り直す) */
  function setupView(s) {
    s = s || {};
    var miss = !!s.active && s.count > 0, run = !!s.running, res = s.result;
    st.partsWhy = !s.active ? '' : run ? '処理の部品を取っています。取り終えると送れます' :
      miss ? '処理の部品が足りません。上の [取ってくる] から取ってください' : '';
    if (st.setupRun && !run && res && res.ok) UIKit.toast('処理の部品を取り終わりました。送れるようになりました', { ms: 5000 });
    st.setupRun = run;
    var card = !!s.active && (run || (miss && !s.later));
    $('setupCard').hidden = !card;
    $('setupBand').hidden = !(miss && s.later && !run);
    $('setupBandText').textContent = miss ? '部品が足りません(約 ' + sizeText(s.total) + ')。取り終わるまで、この PC での処理はできません' : '';
    if (!card) return;
    var key = JSON.stringify(s.missing || []);
    if (key !== st.setupKey) {
      st.setupKey = key;
      $('setupItems').textContent = '';
      (s.missing || []).forEach(function (m) { $('setupItems').appendChild(el('li', {}, [m.label + '(' + sizeText(m.size) + ')'])); });
    }
    $('setupLead').textContent = run ? '部品を取っています。窓を閉じても続きます(取れた分は残り、止めても次は続きから)。' :
      '文字起こしなどに使う部品を取ってきます(約 ' + sizeText(s.total) + ')。取り終わるまで、この PC での処理はできません。';
    $('setupWhere').textContent = (s.places || []).map(function (p) { return '置き場所: ' + p.path + '(空き ' + sizeText(p.free) + '・要る ' + sizeText(p.need) + ')'; }).join('\n');
    var why = run ? '' : s.reason || (res && !res.ok ? (res.cancelled ? '止めました。取れた分は残っています(続きからやり直せます)' :
      '取れなかった物があります。ネットを確かめて、やり直してください') : '');
    $('setupWhy').hidden = !why;
    $('setupWhy').textContent = why;
    var p = s.progress;
    $('setupProgWrap').hidden = !run;
    if (run && p) {
      var frac = p.total ? Math.min(1, p.done / p.total) : 0;
      $('setupBar').firstElementChild.style.width = Math.round(frac * 100) + '%';
      $('setupBar').setAttribute('aria-valuenow', String(Math.round(frac * 100)));
      $('setupProg').textContent = p.index ? '取っています(' + p.index + ' / ' + p.count + ')' : (p.phase || '');
    }
    $('btnSetupStart').hidden = run;
    $('btnSetupStart').disabled = !s.canStart;
    $('btnSetupStart').textContent = res && !res.ok ? 'やり直す' : '始める';
    $('btnSetupStart').title = s.canStart ? '部品を取り始めます' : (s.reason || '');
    $('btnSetupLater').hidden = run;
    $('btnSetupCancel').hidden = !run;
  }
  function setupAct(what) {
    return api('setup/' + what, {}).then(function (j) { setupView(j.setup); emit('parts', st.partsWhy); }, function (e) { fail('初回の準備', e); });
  }

  /* ---------------------------------------------------------------- ⚙ 設定 */
  function fillSettings(s) {
    $('setSave').textContent = s.saveDir + (s.saveIsDefault ? '(既定)' : '');
    $('setCases').textContent = s.caseRoot + (s.caseIsDefault ? '(既定)' : '');
    $('btnResetSave').disabled = !!s.saveIsDefault;
    $('btnResetSave').title = s.saveIsDefault ? '今が既定の場所です' : '既定の場所(ビデオの 受け取ったパック)に戻します';
    $('btnResetCases').disabled = !!s.caseIsDefault;
    $('btnResetCases').title = s.caseIsDefault ? '今が既定の場所です' : '既定の場所(アプリのフォルダの 作業)に戻します';
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setEngine]'), function (r) { r.checked = r.value === s.engine; });
    $('setGpu').textContent = s.gpu ? 'この PC の GPU: ' + s.gpu.name : '';
    $('setKeyState').textContent = s.apiKey ? '入っています' : 'まだ入っていません';
    $('btnKeyClear').disabled = !s.apiKey;
    $('btnKeyClear').title = s.apiKey ? '保存してあるキーを消します' : 'キーが入っていません';
    $('setKeyHelp').textContent = s.apiKeyHelp || '';
    if (document.activeElement !== $('setDisk')) $('setDisk').value = s.diskMinGB == null ? '' : s.diskMinGB;
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setCut]'), function (r) { r.checked = r.value === s.cut; });
  }
  function fillPrefs(f) {   /* ⚙ の処理する PC・ライブ・重み(form.json = C-2-19・C-2-11) */
    if (!f) return;
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setPc]'), function (r) { r.checked = r.value === (f.pc || 'this'); });
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setSens]'), function (r) { r.checked = r.value === f.live.sens; });
    if (document.activeElement !== $('setWait')) $('setWait').value = f.live.waitMin;
    if (document.activeElement !== $('setPad')) $('setPad').value = f.live.pad;
    $('setUseW').checked = !!f.useWeights;
    $('setWLine').hidden = !f.useWeights;
    $('setWAudio').value = f.weights.wAudio; $('setWChat').value = f.weights.wChat; $('setWComments').value = f.weights.wComments;
  }
  function loadSettings() {
    fillPrefs(st.form);
    return api('settings').then(function (j) { fillSettings(j.settings); }, function (e) { fail('設定を読めませんでした', e); });
  }
  function putSettings(body) {
    return api('settings', body).then(function (j) {
      fillSettings(j.settings);
      if (j.message) UIKit.toast(j.message, { ms: 4000 });
    }, function (e) { fail('変えられませんでした', e); loadSettings(); });
  }
  function putPrefs(body) {
    return api('prefs', body).then(function (j) {
      st.form = j.form; fillPrefs(j.form);
      emit('prefs', j.form);
      if (j.message) UIKit.toast(j.message, { ms: 4000 });
    }, function (e) { fail('変えられませんでした', e); fillPrefs(st.form); });
  }
  function num(id, dflt) { var v = parseFloat($(id).value); return isNaN(v) ? dflt : v; }
  function pickFolder(what) {
    var b = $(what === 'save' ? 'btnPickSave' : 'btnPickCases');
    b.disabled = true;
    api('pick-folder', { what: what }).then(function (j) {
      fillSettings(j.settings);
      if (j.chosen && j.message) UIKit.toast(j.message, { ms: 4000 });
    }, function (e) { fail('フォルダを変えられませんでした', e); }).then(function () { b.disabled = false; });
  }
  function saveKey(key) {
    var b = $('btnKeySave');
    b.disabled = true;
    if (key) $('setKeyState').textContent = '確かめています…';
    api('settings/key', { key: key }).then(function (j) {
      $('setKey').value = '';
      fillSettings(j.settings);
      UIKit.toast(j.message, { ms: 4000 });
    }, function (e) { fail('API キー', e); loadSettings(); }).then(function () { b.disabled = false; });
  }
  function openSettings() {
    UIKit.drawer.open($('settingsDrawer'), { opener: $('btnSettings') });
    loadSettings();
  }

  window.FR = { $: $, el: el, api: api, fail: fail, sizeText: sizeText, dur: dur, token: token, typing: typing, on: on, refresh: refresh, show: show,
    get state() { return st; }, get view() { return view; } };
  window.FriendApp = { show: show, count: function () { return undecided; } };   /* 窓(F3-A)から呼ぶ口(仮 = decisions 3-83 (f3b-e)) */

  document.addEventListener('DOMContentLoaded', function () {
    var v = document.querySelector('meta[name="ytt-version"]');
    $('ver').textContent = v ? 'v' + v.content : '';
    $('tabSend').addEventListener('click', function () { show('send'); });
    $('tabReceive').addEventListener('click', function () { show('receive'); });
    window.addEventListener('hashchange', function () { show(location.hash.slice(1)); });
    $('btnSaved').addEventListener('click', function () { api('open', { what: 'saved' }).catch(function (e) { fail('開けませんでした', e); }); });
    $('btnQuit').addEventListener('click', function () {
      api('../shutdown', {}).then(function () {
        clearTimeout(timer); clearTimeout(listTimer);
        document.querySelector('.fr-main').textContent = '';
        document.querySelector('.fr-main').appendChild(el('p', { cls: 'fr-bye', text: '止めて終了しました。この窓は閉じてかまいません(次に開くと、作っていた物の続きから始めます)' }));
      }, function (e) { fail('終了できませんでした', e); });
    });
    $('btnSetupStart').addEventListener('click', function () { setupAct('start'); });
    $('btnSetupLater').addEventListener('click', function () { setupAct('later'); });
    $('btnSetupCancel').addEventListener('click', function () { setupAct('cancel'); });
    $('btnSetupOpen').addEventListener('click', function () { setupAct('open'); });
    $('btnSettings').addEventListener('click', openSettings);
    $('settingsClose').addEventListener('click', function () { UIKit.drawer.close($('settingsDrawer')); });
    $('btnPickSave').addEventListener('click', function () { pickFolder('save'); });
    $('btnPickCases').addEventListener('click', function () { pickFolder('cases'); });
    $('btnResetSave').addEventListener('click', function () { putSettings({ reset: 'save' }); });
    $('btnResetCases').addEventListener('click', function () { putSettings({ reset: 'cases' }); });
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setEngine]'), function (r) {
      r.addEventListener('change', function () { if (r.checked) putSettings({ engine: r.value }); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setCut]'), function (r) {
      r.addEventListener('change', function () { if (r.checked) putSettings({ cut: r.value }); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setPc]'), function (r) {
      r.addEventListener('change', function () { if (r.checked) putPrefs({ pc: r.value }); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setSens]'), function (r) {
      r.addEventListener('change', function () { if (r.checked) putPrefs({ liveSens: r.value }); });
    });
    $('setWait').addEventListener('change', function () { putPrefs({ liveWait: Math.round(num('setWait', 5)) }); });
    $('setPad').addEventListener('change', function () { putPrefs({ livePad: num('setPad', 2) }); });
    $('setUseW').addEventListener('change', function () { putPrefs({ useWeights: $('setUseW').checked }); });
    ['setWAudio', 'setWChat', 'setWComments'].forEach(function (id) {
      $(id).addEventListener('change', function () {
        putPrefs({ weights: { wAudio: Math.round(num('setWAudio', 1)), wChat: Math.round(num('setWChat', 1)), wComments: Math.round(num('setWComments', 1)) } });
      });
    });
    $('setDisk').addEventListener('change', function () {
      var x = parseFloat($('setDisk').value);
      if (isNaN(x)) { UIKit.toast('空き容量の下限は数(GB)で入れてください', { kind: 'err' }); loadSettings(); return; }
      putSettings({ diskMinGB: x });
    });
    $('btnKeySave').addEventListener('click', function () {
      var k = $('setKey').value.trim();
      if (!k) { UIKit.toast('キーを貼ってから押してください', { kind: 'err' }); return; }
      saveKey(k);
    });
    $('setKey').addEventListener('keydown', function (e) { if (e.key === 'Enter' && $('setKey').value.trim()) saveKey($('setKey').value.trim()); });
    $('btnKeyClear').addEventListener('click', function () { saveKey(''); });
    $('cleanedOk').addEventListener('click', function () {
      var what = $('cleaned').getAttribute('data-what');
      api('notice-seen', what === 'cleaned' ? { what: 'cleaned' } : {}).then(function () { $('cleaned').hidden = true; if (st.receive) st.receive.notice = null; });
    });
    $('updatedOk').addEventListener('click', function () { st.updatedSeen = ((st.inbox || {}).sync || {}).updated; $('updated').hidden = true; });
    UIKit.life.onReturn(function () { refresh(); pollList(); });
    show(location.hash.slice(1));
    refresh();
  });
})();
