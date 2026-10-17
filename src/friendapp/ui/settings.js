/* ⚙ 設定の引き出し(F3-5。notes:plan/f1-friend-requirements.md の C-5-2・C-2-19・C-1-2)。
   主の画面(F3-B)は <script src="settings.js" defer> と settings.css を読み、歯車のボタンを id="btnSettings" で置くだけ。中身・Esc はここ。
   口: GET api/friend/settings・POST api/friend/settings {…}・settings/key {key}・pick-folder {what}・setup/clean-old。
   フォルダは [選ぶ] で Python が Windows の窓を開く(画面からパスを打たせない)。外の文字は textContent で入れる(CSP の下で動く)。 */
(function () {
  'use strict';
  var drawer = null, ui = {}, current = null;

  function api(path, body) { return UIKit.http('api/friend/' + path, body === undefined ? {} : { body: body }); }

  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'text') e.textContent = attrs[k];
      else e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }

  function sizeText(n) { return n >= 1e9 ? (n / 1e9).toFixed(1) + 'GB' : Math.max(1, Math.round((n || 0) / 1e6)) + 'MB'; }

  function fail(what, e) { UIKit.toast(what + ((e && e.message) ? ': ' + e.message : ''), { ms: 5000 }); }

  function section(id, title, kids, hint) {
    return h('section', { class: 'ui-settings-sec fs-set', 'aria-labelledby': id }, [h('h3', { id: id, text: title })].concat(kids).concat(hint ? [h('p', { class: 'hint', text: hint })] : []));
  }

  function radios(name, label, items) {
    return h('div', { class: 'fs-line', role: 'radiogroup', 'aria-labelledby': label }, items.map(function (it) {
      var r = h('input', { type: 'radio', name: name, value: it[0] });
      ui[name + ':' + it[0]] = r;
      return h('label', { class: 'fs-radio' }, [r, ' ' + it[1]]);
    }));
  }

  function setRadio(name, v) {
    Object.keys(ui).forEach(function (k) { if (k.indexOf(name + ':') === 0) ui[k].checked = k === name + ':' + v; });
  }

  function num(id, min, max, step, label) {
    var e = h('input', { type: 'number', id: id, class: 'fs-num', min: String(min), max: String(max), step: String(step), 'aria-label': label });
    ui[id] = e;
    return e;
  }

  function build() {
    var close = h('button', { type: 'button', class: 'btn ghost icon small', 'aria-label': '閉じる' }, [h('span', { class: 'ui-icon', 'data-icon': 'close', 'aria-hidden': 'true' })]);
    close.addEventListener('click', function () { UIKit.drawer.close(drawer); });
    ui.save = h('p', { class: 'fs-path' });
    ui.cases = h('p', { class: 'fs-path' });
    ui.pickSave = h('button', { type: 'button', class: 'btn small', text: '選ぶ' });
    ui.resetSave = h('button', { type: 'button', class: 'btn ghost small', text: '既定に戻す' });
    ui.pickCases = h('button', { type: 'button', class: 'btn small', text: '選ぶ' });
    ui.resetCases = h('button', { type: 'button', class: 'btn ghost small', text: '既定に戻す' });
    ui.gpu = h('p', { class: 'hint' });
    ui.keyState = h('p', {});
    ui.key = h('input', { type: 'text', class: 'fs-key', autocomplete: 'off', spellcheck: 'false', 'aria-labelledby': 'fsKeyH', placeholder: 'キーを貼る' });
    ui.keySave = h('button', { type: 'button', class: 'btn small', text: '確かめて保存' });
    ui.keyClear = h('button', { type: 'button', class: 'btn ghost small', text: '消す' });
    ui.keyHelp = h('p', { class: 'hint' });
    ui.remoteWhy = h('p', { class: 'hint' });
    ui.useWeights = h('input', { type: 'checkbox' });
    ui.weightsRow = h('div', { class: 'fs-line fs-weights' }, [['wAudio', '音量'], ['wChat', 'チャット'], ['wComments', 'コメント']].map(function (w) {
      return h('label', { class: 'fs-radio' }, [w[1] + ' ', num('fsW_' + w[0], 0, 3, 1, w[1] + 'の重み')]);
    }));
    ui.sens = h('select', { 'aria-labelledby': 'fsLiveSensL' });
    ui.oldWrap = h('section', { class: 'ui-settings-sec fs-set', 'aria-labelledby': 'fsOldH', hidden: '' });
    ui.oldText = h('p', {});
    ui.oldBtn = h('button', { type: 'button', class: 'btn small', text: '片付ける' });
    ui.oldWrap.appendChild(h('h3', { id: 'fsOldH', text: '前のアプリ' }));
    ui.oldWrap.appendChild(ui.oldText);
    ui.oldWrap.appendChild(h('div', { class: 'fs-line' }, [ui.oldBtn]));

    var body = h('div', { class: 'ui-drawer-body' }, [
      section('fsPcH', '処理する PC', [radios('fsPc', 'fsPcH', [['local', 'この PC で処理する'], ['remote', '依頼する']]), ui.remoteWhy],
              '「依頼する」にすると、この PC では処理せず、作る人の PC に頼みます(Dropbox で送ります)。'),
      section('fsSaveH', '受け取った物の保存先', [ui.save, h('div', { class: 'fs-line' }, [ui.pickSave, ui.resetSave])],
              '[受け取る] を押した切り抜きを置く場所です。変えても、今ある物は移しません。'),
      section('fsCasesH', '一時保管', [ui.cases, h('div', { class: 'fs-line' }, [ui.pickCases, ui.resetCases])],
              '作っている途中の物・録画を置く場所です。選び直しても今ある物は移さず、新しい物から新しい場所に作ります。空き容量はこの場所のドライブで測ります。'),
      section('fsEngineH', '文字起こしのエンジン', [radios('fsEngine', 'fsEngineH', [['A', 'A(どの GPU でも)'], ['C', 'C(NVIDIA 用)']]), ui.gpu],
              'C は NVIDIA の GPU で速くなります。切り替えたとき足りない部品があれば取ってきます。次の処理から使います。'),
      section('fsKeyH', 'YouTube の API キー', [ui.keyState, h('div', { class: 'fs-line' }, [ui.key, ui.keySave, ui.keyClear]), ui.keyHelp]),
      section('fsDiskH', '空き容量の下限', [h('div', { class: 'fs-line' }, [num('fsDisk', 0, 100000, 1, '空き容量の下限(GB)'), h('span', { class: 'hint', text: 'GB(空きがこれより少なくなると、新しい処理を始めずに待ちます)' })])]),
      section('fsCutH', 'カットの既定', [radios('fsCut', 'fsCutH', [['none', 'しない'], ['silence', '無音を削る']])], '送るときに使います。初めは「しない」です。'),
      section('fsWH', '解析の重み', [h('label', { class: 'fs-radio' }, [ui.useWeights, ' 重みを指定する']), ui.weightsRow],
              '見どころを自動で探すときの手がかりの強さ(0〜3)。指定しなければ、作る人の PC の設定の値を使います。区間を入れた依頼では使いません。'),
      section('fsLiveH', 'ライブの切り抜き', [
        h('div', { class: 'fs-line' }, [h('span', { id: 'fsLiveSensL', text: '感度' }), ui.sens]),
        h('div', { class: 'fs-line' }, [h('label', { class: 'fs-radio' }, ['待ち ', num('fsLiveWait', 1, 60, 1, '待ち(分)'), ' 分'])]),
        h('div', { class: 'fs-line' }, [h('label', { class: 'fs-radio' }, ['余白 ', num('fsLivePad', 0, 5, 0.5, '余白(秒)'), ' 秒'])])
      ], '録画しながら切り抜くときの細かい設定です。次の録画から使います。'),
      ui.oldWrap
    ]);
    var help = h('a', { class: 'btn ghost small fs-help', href: 'guide.html#settings', target: '_blank', rel: 'noopener', 'aria-label': '設定の説明を新しい窓で開く', title: '設定の説明', text: '?' });
    drawer = h('aside', { class: 'ui-drawer', id: 'settingsDrawer', hidden: '', 'aria-labelledby': 'fsSetTitle' }, [
      h('div', { class: 'ui-drawer-head' }, [h('h2', { class: 'ui-drawer-title', id: 'fsSetTitle', text: '設定' }), help, close]), body]);
    document.body.appendChild(drawer);
    bind();
  }

  function bind() {
    ui.pickSave.addEventListener('click', function () { pick('save', ui.pickSave); });
    ui.pickCases.addEventListener('click', function () { pick('cases', ui.pickCases); });
    ui.resetSave.addEventListener('click', function () { put({ reset: 'save' }); });
    ui.resetCases.addEventListener('click', function () { put({ reset: 'cases' }); });
    ['local', 'remote'].forEach(function (v) { ui['fsPc:' + v].addEventListener('change', function () { put({ processing: v }); }); });
    ['A', 'C'].forEach(function (v) { ui['fsEngine:' + v].addEventListener('change', function () { put({ engine: v }); }); });
    ['none', 'silence'].forEach(function (v) { ui['fsCut:' + v].addEventListener('change', function () { put({ cut: v }); }); });
    ui.fsDisk.addEventListener('change', function () {
      var v = parseFloat(ui.fsDisk.value);
      if (isFinite(v)) put({ diskMinGB: v });
    });
    ui.keySave.addEventListener('click', function () { saveKey(ui.key.value.trim()); });
    ui.key.addEventListener('keydown', function (e) { if (e.key === 'Enter') saveKey(ui.key.value.trim()); });
    ui.keyClear.addEventListener('click', function () { saveKey(''); });
    ui.useWeights.addEventListener('change', putWeights);
    ['wAudio', 'wChat', 'wComments'].forEach(function (k) { ui['fsW_' + k].addEventListener('change', putWeights); });
    ui.sens.addEventListener('change', putLive);
    ui.fsLiveWait.addEventListener('change', putLive);
    ui.fsLivePad.addEventListener('change', putLive);
    ui.oldBtn.addEventListener('click', function () {
      ui.oldBtn.disabled = true;
      api('setup/clean-old', {}).then(function () { UIKit.toast('前のアプリを片付けました', { ms: 3500 }); load(); },
        function (e) { fail('片付けられませんでした', e); }).then(function () { ui.oldBtn.disabled = false; });
    });
  }

  function putWeights() {
    var w = null;
    if (ui.useWeights.checked) {
      w = {};
      ['wAudio', 'wChat', 'wComments'].forEach(function (k) { w[k] = Math.max(0, Math.min(3, parseInt(ui['fsW_' + k].value, 10) || 0)); });
    }
    put({ weights: w });
  }

  function putLive() {
    put({ live: { sens: ui.sens.value, waitMin: parseFloat(ui.fsLiveWait.value), pad: parseFloat(ui.fsLivePad.value) } });
  }

  function fill(s) {
    current = s;
    ui.save.textContent = (s.saveDir || '') + (s.saveIsDefault ? '(既定)' : '');
    ui.cases.textContent = (s.caseRoot || '') + (s.caseIsDefault ? '(既定)' : '');
    ui.resetSave.disabled = !!s.saveIsDefault;
    ui.resetSave.title = s.saveIsDefault ? '今が既定の場所です' : '既定の場所(ビデオの 受け取ったパック)に戻します';
    ui.resetCases.disabled = !!s.caseIsDefault;
    ui.resetCases.title = s.caseIsDefault ? '今が既定の場所です' : '既定の場所(アプリのフォルダの 作業)に戻します';
    setRadio('fsPc', s.processing || 'local');
    ui['fsPc:remote'].disabled = s.canRemote === false && s.processing !== 'remote';
    ui['fsPc:remote'].title = ui['fsPc:remote'].disabled ? 'Dropbox の鍵が無いので選べません' : '';
    ui.remoteWhy.textContent = s.canRemote === false ? 'Dropbox の鍵が無いので「依頼する」は選べません' : '';
    setRadio('fsEngine', s.engine);
    ui.gpu.textContent = s.gpu ? 'この PC の GPU: ' + s.gpu.name + (s.gpu.vramGB ? '(' + s.gpu.vramGB + ' GB)' : '') : '';
    ui.keyState.textContent = s.apiKey ? '入っています' : 'まだ入っていません';
    ui.keyClear.disabled = !s.apiKey;
    ui.keyClear.title = s.apiKey ? '保存してあるキーを消します' : 'キーが入っていません';
    ui.keyHelp.textContent = s.apiKeyHelp || '';
    if (document.activeElement !== ui.fsDisk) ui.fsDisk.value = s.diskMinGB == null ? '' : s.diskMinGB;
    setRadio('fsCut', s.cut);
    var w = s.weights;
    ui.useWeights.checked = !!w;
    ['wAudio', 'wChat', 'wComments'].forEach(function (k) {
      var e = ui['fsW_' + k];
      e.disabled = !w;
      e.title = w ? '0〜3' : '「重みを指定する」を入れると変えられます';
      if (document.activeElement !== e) e.value = w && w[k] != null ? w[k] : 1;
    });
    var lv = s.live || {};
    if (!ui.sens.options.length || ui.sens.dataset.n !== String((s.liveSensOptions || []).length)) {
      ui.sens.textContent = '';
      (s.liveSensOptions || []).forEach(function (o) { ui.sens.appendChild(h('option', { value: o.value, text: o.label })); });
      ui.sens.dataset.n = String((s.liveSensOptions || []).length);
    }
    ui.sens.value = lv.sens || '';
    if (document.activeElement !== ui.fsLiveWait) ui.fsLiveWait.value = lv.waitMin == null ? '' : lv.waitMin;
    if (document.activeElement !== ui.fsLivePad) ui.fsLivePad.value = lv.pad == null ? '' : lv.pad;
    var old = s.oldApp || {};
    if (old.canClean) ui.oldWrap.removeAttribute('hidden'); else ui.oldWrap.setAttribute('hidden', '');
    ui.oldText.textContent = old.canClean ? '前のアプリの部品(約 ' + sizeText(old.bytes) + ')が残っています。このアプリへ写して同じだと確かめてあります。' : '';
  }

  function load() { return api('settings').then(function (j) { fill(j.settings); }, function (e) { fail('設定を読めませんでした', e); }); }

  function put(body) {
    return api('settings', body).then(function (j) {
      fill(j.settings);
      if (j.message) UIKit.toast(j.message, { ms: 3500 });
      document.dispatchEvent(new CustomEvent('friend-settings', { detail: j.settings }));   // 主の画面が送る欄の文字を直す(依頼します 等)
    }, function (e) { fail('変えられませんでした', e); load(); });
  }

  function pick(what, btn) {
    btn.disabled = true;
    api('pick-folder', { what: what }).then(function (j) {
      fill(j.settings);
      if (j.chosen && j.message) UIKit.toast(j.message, { ms: 3500 });
    }, function (e) { fail('フォルダを変えられませんでした', e); }).then(function () { btn.disabled = false; });
  }

  function saveKey(key) {
    ui.keySave.disabled = true;
    if (key) ui.keyState.textContent = '確かめています…';
    api('settings/key', { key: key }).then(function (j) {
      ui.key.value = '';
      fill(j.settings);
      UIKit.toast(j.message, { ms: 3500 });
    }, function (e) { fail('API キー', e); load(); }).then(function () { ui.keySave.disabled = false; });
  }

  function open(opener) {
    if (!drawer) build();
    UIKit.drawer.open(drawer, { opener: opener || document.getElementById('btnSettings') });
    load();
  }

  window.FriendSettings = { open: open, current: function () { return current; } };

  document.addEventListener('DOMContentLoaded', function () {
    var b = document.getElementById('btnSettings');
    if (b) b.addEventListener('click', function () { open(b); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && drawer && UIKit.drawer.isOpen(drawer)) { UIKit.drawer.close(drawer); e.stopPropagation(); }
  }, true);
})();
