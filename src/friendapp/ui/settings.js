/* ⚙ 設定の引き出し(notes:plan/done/f1-friend-requirements.md の C-5-2・C-2-19)。
   主の画面(F3-B)は <script src="settings.js" defer> と settings.css を読み、歯車のボタンを id="btnSettings" で置くだけ。中身・Esc はここ。
   口: GET api/friend/settings・POST api/friend/settings {…}・settings/key {key}・pick-folder {what}。
   フォルダの整理(F3-A): GET tidy・POST tidy/scan・tidy/apply {ids}・tidy/later・tidy/open-trash。口が無い(404)ときは節に「この版では使えません」。
   フォルダは [選ぶ] で Python が Windows の窓を開く(画面からパスを打たせない)。外の文字は textContent で入れる(CSP の下で動く)。 */
(function () {
  'use strict';
  var drawer = null, ui = {}, current = null;
  var tidy = null, tidyTimer = 0, tidyBusy = false, tidyChecked = {};   /* フォルダの整理の view・読み直しの timer・操作中・ask の物のチェック(既定は入れる) */

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
    ui.engine = h('p', {});   /* 文字起こしのエンジンは見せるだけ(10-23: 自動で選ぶ) */
    ui.gpu = h('p', { class: 'hint' });
    ui.keyState = h('p', {});
    ui.key = h('input', { type: 'text', class: 'fs-key', autocomplete: 'off', spellcheck: 'false', 'aria-labelledby': 'fsKeyH', placeholder: 'キーを貼る' });
    ui.keySave = h('button', { type: 'button', class: 'btn small', text: '確かめて保存' });
    ui.keyClear = h('button', { type: 'button', class: 'btn ghost small', text: '消す' });
    ui.keyHelp = h('p', { class: 'hint' });
    ui.remoteWhy = h('p', { class: 'hint' });
    ui.sens = h('select', { 'aria-labelledby': 'fsLiveSensL' });
    /* YouTube のログイン(notes:docs/spec/friend.md の 13-13)。ログインは exe の小窓(FriendHost.youtubeLogin)・ログアウトは POST settings {ytLogout} */
    ui.ytState = h('p', { 'aria-live': 'polite' });
    ui.ytLogin = h('button', { type: 'button', class: 'btn small', text: 'YouTube にログイン' });
    ui.ytLogout = h('button', { type: 'button', class: 'btn ghost small', text: 'ログアウト' });
    ui.ytWhy = h('p', { class: 'hint' });

    /* フォルダを整理する(F3-A)。[内容を見る] は帯から FriendSettings.open('tidy') で来る。中身の見え方は fillTidy */
    ui.tidyText = h('p', { class: 'fs-path', 'aria-live': 'polite' });
    ui.tidyScan = h('button', { type: 'button', class: 'btn small', text: '調べる' });
    ui.tidyApply = h('button', { type: 'button', class: 'btn small', text: '選んだ物を片付ける' });
    ui.tidyTrash = h('button', { type: 'button', class: 'btn ghost small', text: 'ごみ箱を開く', hidden: '' });
    ui.tidyList = h('ul', { class: 'fs-items', 'aria-label': '片付ける物' });
    ui.tidyAuto = h('p', { class: 'hint' });
    ui.tidyKept = h('p', { class: 'hint' });
    ui.tidyWrap = h('div', { class: 'fs-tidy' }, [ui.tidyText, h('div', { class: 'fs-line' }, [ui.tidyScan, ui.tidyApply, ui.tidyTrash]), ui.tidyList, ui.tidyAuto, ui.tidyKept]);
    ui.tidyOff = h('p', { class: 'hint fs-tidy-off', hidden: '', text: 'この版では使えません' });
    ui.tidySec = section('fsTidyH', 'フォルダを整理する', [ui.tidyWrap, ui.tidyOff],
      '作業の残りや使っていない物を、アプリのごみ箱へ移します。ごみ箱の物は 3 日で消えます。');
    ui.tidyScan.addEventListener('click', function () { tidyCall('scan', {}); });
    ui.tidyApply.addEventListener('click', function () { tidyCall('apply', { ids: selectedIds() }); });
    ui.tidyTrash.addEventListener('click', openTrash);

    /* 最近の更新(配った版で直したこと)。見に来れば見られるだけ(知らせ・印は出さない)。latest.json に notes が無ければ節ごと出さない */
    ui.notesList = h('div', { class: 'fs-notes' });
    ui.notesSec = section('fsNotesH', '最近の更新', [ui.notesList]);
    ui.notesSec.hidden = true;

    var body = h('div', { class: 'ui-drawer-body' }, [
      section('fsPcH', '処理する PC', [radios('fsPc', 'fsPcH', [['local', 'この PC で処理する'], ['remote', '依頼する']]), ui.remoteWhy],
              '「依頼する」にすると、この PC では処理せず、作る人の PC に頼みます(Dropbox で送ります)。'),
      section('fsYtH', 'YouTube のログイン', [ui.ytState, h('div', { class: 'fs-line' }, [ui.ytLogin, ui.ytLogout]), ui.ytWhy],
              'YouTube に「ロボットではないか」の確認で止められないように、この PC の取り込みで使います。メインではなく、サブの Google アカウントでログインしてください(止められても困らないように)。ログインの情報はこの PC の中だけに置き、外へは出しません。'),
      section('fsSaveH', '受け取った物の保存先', [ui.save, h('div', { class: 'fs-line' }, [ui.pickSave, ui.resetSave])],
              '[受け取る] を押した切り抜きを置く場所です。変えても、今ある物は移しません。'),
      section('fsCasesH', '一時保管', [ui.cases, h('div', { class: 'fs-line' }, [ui.pickCases, ui.resetCases])],
              '作っている途中の物・録画を置く場所です。選び直しても今ある物は移さず、新しい物から新しい場所に作ります。空き容量はこの場所のドライブで測ります。'),
      section('fsEngineH', '文字起こしのエンジン', [ui.engine, ui.gpu],
              'この PC に合わせて自動で選びます(NVIDIA の GPU なら C、ほかは A)。'),
      section('fsKeyH', 'YouTube の API キー', [ui.keyState, h('div', { class: 'fs-line' }, [ui.key, ui.keySave, ui.keyClear]), ui.keyHelp]),
      section('fsDiskH', '空き容量の下限', [h('div', { class: 'fs-line' }, [num('fsDisk', 0, 100000, 1, '空き容量の下限(GB)'), h('span', { class: 'hint', text: 'GB(空きがこれより少なくなると、新しい処理を始めずに待ちます)' })])]),
      section('fsCutH', 'カットの既定', [radios('fsCut', 'fsCutH', [['none', 'しない'], ['silence', '無音を削る']])], '送るときに使います。初めは「しない」です。'),
      section('fsLiveH', 'ライブの切り抜き', [
        h('div', { class: 'fs-line' }, [h('span', { id: 'fsLiveSensL', text: '感度' }), ui.sens]),
        h('div', { class: 'fs-line' }, [h('label', { class: 'fs-radio' }, ['待ち ', num('fsLiveWait', 1, 60, 1, '待ち(分)'), ' 分'])]),
        h('div', { class: 'fs-line' }, [h('label', { class: 'fs-radio' }, ['余白 ', num('fsLivePad', 0, 5, 0.5, '余白(秒)'), ' 秒'])])
      ], '録画しながら切り抜くときの細かい設定です。次の録画から使います。'),
      ui.tidySec,
      ui.notesSec
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
    ['none', 'silence'].forEach(function (v) { ui['fsCut:' + v].addEventListener('change', function () { put({ cut: v }); }); });
    ui.fsDisk.addEventListener('change', function () {
      var v = parseFloat(ui.fsDisk.value);
      if (isFinite(v)) put({ diskMinGB: v });
    });
    ui.keySave.addEventListener('click', function () { saveKey(ui.key.value.trim()); });
    ui.key.addEventListener('keydown', function (e) { if (e.key === 'Enter') saveKey(ui.key.value.trim()); });
    ui.keyClear.addEventListener('click', function () { saveKey(''); });
    ui.sens.addEventListener('change', putLive);
    ui.fsLiveWait.addEventListener('change', putLive);
    ui.fsLivePad.addEventListener('change', putLive);
    ui.ytLogin.addEventListener('click', ytLogin);
    ui.ytLogout.addEventListener('click', function () { put({ ytLogout: true }); });
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
    ui.engine.textContent = s.engine === 'C' ? 'C(NVIDIA 用)で動いています' : 'A(どの GPU でも)で動いています';
    ui.gpu.textContent = s.gpu ? 'この PC の GPU: ' + s.gpu.name + (s.gpu.vramGB ? '(' + s.gpu.vramGB + ' GB)' : '') : '';
    ui.keyState.textContent = s.apiKey ? '入っています' : 'まだ入っていません';
    ui.keyClear.disabled = !s.apiKey;
    ui.keyClear.title = s.apiKey ? '保存してあるキーを消します' : 'キーが入っていません';
    ui.keyHelp.textContent = s.apiKeyHelp || '';
    if (document.activeElement !== ui.fsDisk) ui.fsDisk.value = s.diskMinGB == null ? '' : s.diskMinGB;
    setRadio('fsCut', s.cut);
    var lv = s.live || {};
    if (!ui.sens.options.length || ui.sens.dataset.n !== String((s.liveSensOptions || []).length)) {
      ui.sens.textContent = '';
      (s.liveSensOptions || []).forEach(function (o) { ui.sens.appendChild(h('option', { value: o.value, text: o.label })); });
      ui.sens.dataset.n = String((s.liveSensOptions || []).length);
    }
    ui.sens.value = lv.sens || '';
    if (document.activeElement !== ui.fsLiveWait) ui.fsLiveWait.value = lv.waitMin == null ? '' : lv.waitMin;
    if (document.activeElement !== ui.fsLivePad) ui.fsLivePad.value = lv.pad == null ? '' : lv.pad;
    fillYt(s.ytLogin || {});
    if (Array.isArray(s.updateNotes)) fillNotes(s.updateNotes, s.version || '');
  }

  /* 版ごとに「版 n(日付)」と直したことの箇条。外から来た文字は textContent で */
  function fillNotes(notes, now) {
    ui.notesList.textContent = '';
    notes.forEach(function (n) {
      if (!n || !Array.isArray(n.items) || !n.items.length) return;
      var head = '版 ' + n.v + (typeof n.at === 'number' ? '(' + dayText(n.at) + ')' : '') + (n.v === now ? '・今の版' : '');
      ui.notesList.appendChild(h('p', { class: 'fs-path', text: head }));
      ui.notesList.appendChild(h('ul', { class: 'fs-items' }, n.items.map(function (t) { return h('li', { text: String(t) }); })));
    });
    ui.notesSec.hidden = !ui.notesList.childNodes.length;
  }

  function dayText(ms) { var d = new Date(ms); return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日'; }

  function fillYt(y) {
    var app = !!(window.FriendHost && FriendHost.isApp);
    ui.ytState.className = y.state === 'expired' ? 'fs-yt-bad' : '';
    ui.ytState.textContent = y.state === 'ok' ? 'ログインしています(' + dayText(y.at) + ')' :
      y.state === 'expired' ? 'ログインが切れた可能性があります。もう一度ログインしてください' : 'まだログインしていません';
    ui.ytLogin.textContent = y.state === 'none' ? 'YouTube にログイン' : 'もう一度ログイン';
    ui.ytLogin.disabled = !app;
    ui.ytLogin.title = app ? 'ログインの小窓を開きます。済むと自動で閉じます' : 'アプリの窓の中でだけログインできます';
    ui.ytLogout.hidden = y.state === 'none';
    ui.ytWhy.textContent = app ? '' : 'この窓ではログインできません。アプリ(FriendApp)の窓で開いてください';
  }

  function ytLogin() {
    ui.ytLogin.disabled = true;
    ui.ytState.textContent = 'ログインの小窓で続けてください…';
    FriendHost.youtubeLogin(function (ok, message) {
      if (message) UIKit.toast(message, { ms: 4000 });
      load();
    });
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

  /* ---- フォルダを整理する(F3-A)---- 口: GET tidy・POST tidy/scan・tidy/apply {ids}・tidy/later・tidy/open-trash。view の形は f3a-tidy-design.md */
  function viewOf(j) { return j && j.tidy && typeof j.tidy === 'object' ? j.tidy : j; }

  function toMs(at) {
    if (typeof at === 'number') return at < 1e12 ? at * 1000 : at;
    var t = Date.parse(at);
    return isFinite(t) ? t : 0;
  }

  function lastText(last) {
    if (last.failed) return '片付けられませんでした' + (last.message ? ': ' + last.message : '');
    return last.count > 0 ? last.count + ' 件 ' + sizeText(last.bytes) + ' を片付けました(3 日はごみ箱に残ります)' : '';
  }

  function selectedIds() {
    return ((tidy && tidy.items) || []).filter(function (it) { return it.mode === 'ask' && tidyChecked[it.id] !== false; })
      .map(function (it) { return it.id; });
  }

  /* 押せるか・押せないときの理由(title)。blocked は作業中などで今は走らせない理由の文 */
  function tidyButtons() {
    var v = tidy || {}, applying = v.state === 'applying', blocked = v.blocked || '', off = tidyBusy || applying;
    var n = selectedIds().length;
    ui.tidyScan.disabled = off || !!blocked || v.state === 'scanning';
    ui.tidyScan.title = blocked || (applying ? '片付けている間は調べられません' : '');
    ui.tidyApply.disabled = off || !!blocked || n === 0;
    ui.tidyApply.title = blocked || (applying ? '片付けている間は使えません' : n === 0 ? '片付ける物を 1 つ以上選んでください' : '選んだ物をアプリのごみ箱へ移します(3 日は戻せます)');
  }

  function fillTidy(v) {
    tidy = v;
    var applying = v.state === 'applying', scanning = v.state === 'scanning', last = v.last;
    var recent = !!last && Date.now() - toMs(last.at) <= 120000;
    ui.tidyOff.hidden = true;
    ui.tidyWrap.hidden = false;
    ui.tidyText.textContent = applying ? '片付けています…' : scanning ? '調べています…' : (v.blocked || (recent ? lastText(last) : ''));
    ui.tidyTrash.hidden = !v.trash;
    ui.tidyList.textContent = '';
    var asks = (v.items || []).filter(function (it) { return it.mode === 'ask'; });
    if (!asks.length) ui.tidyList.appendChild(h('li', { class: 'hint', text: '片付ける物はありません' }));
    asks.forEach(function (it) {
      var cb = h('input', { type: 'checkbox', value: String(it.id) });
      cb.checked = tidyChecked[it.id] !== false;   /* 初めは全部チェック */
      cb.addEventListener('change', function () { tidyChecked[it.id] = cb.checked; tidyButtons(); });
      ui.tidyList.appendChild(h('li', { class: 'fs-item' }, [h('label', { class: 'fs-radio' },
        [cb, ' ' + it.label + (it.where ? '(' + it.where + ')' : '') + ' ' + sizeText(it.bytes)])]));
    });
    var a = v.autoDone;
    ui.tidyAuto.textContent = a && a.count ? '前回黙って片付けた物 ' + a.count + ' 件(' + sizeText(a.bytes) + ')' : '前回黙って片付けた物はありません';
    ui.tidyKept.textContent = '触らなかった物 ' + (v.unknownCount || 0) + ' 件(何か分からない物は記録だけ)';
    tidyButtons();
    clearTimeout(tidyTimer);
    if ((applying || scanning) && drawer && UIKit.drawer.isOpen(drawer)) tidyTimer = setTimeout(tidyPoll, 3000);   /* 進みの文を開いている間だけ読み直す */
  }

  function tidyOff(text) {
    clearTimeout(tidyTimer);
    tidy = null;
    ui.tidyWrap.hidden = true;
    ui.tidyOff.textContent = text;
    ui.tidyOff.hidden = false;
  }

  function loadTidy() {
    return api('tidy').then(function (j) {
      var v = viewOf(j);
      if (v && typeof v === 'object') fillTidy(v); else tidyOff('フォルダの整理の状態を読めませんでした');
    }, function (e) {
      tidyOff(e && e.status === 404 ? 'この版では使えません' : 'フォルダの整理の状態を読めませんでした。引き出しを開き直してみてください');
    });
  }

  function tidyPoll() { if (drawer && UIKit.drawer.isOpen(drawer)) loadTidy(); }

  function tidyCall(path, body) {
    if (tidyBusy) return;
    tidyBusy = true;
    tidyButtons();
    api('tidy/' + path, body).then(function (j) {
      var v = viewOf(j);
      if (v && typeof v === 'object') fillTidy(v);
      document.dispatchEvent(new CustomEvent('friend-tidy', { detail: v }));   /* 帯の 1 行も読み直す */
    }, function (e) { fail('フォルダを整理できませんでした', e); }).then(function () { tidyBusy = false; tidyButtons(); });
  }

  function openTrash() {
    ui.tidyTrash.disabled = true;
    api('tidy/open-trash', {}).then(null, function (e) { fail('ごみ箱を開けませんでした', e); }).then(function () { ui.tidyTrash.disabled = false; });
  }

  /* open(opener) = ⚙ のボタン。open('tidy') = 「フォルダを整理する」の節へ(帯の [内容を見る]) */
  function open(opener) {
    var sec = typeof opener === 'string' ? opener : '';
    if (sec) opener = null;
    if (!drawer) build();
    UIKit.drawer.open(drawer, { opener: opener || document.getElementById('btnSettings') });
    load();
    loadTidy();
    if (sec === 'tidy') setTimeout(function () {
      ui.tidySec.scrollIntoView({ block: 'start' });
      if (!ui.tidyScan.disabled) ui.tidyScan.focus({ preventScroll: true });
    }, 60);
  }

  window.FriendSettings = { open: open, current: function () { return current; } };

  /* 帯(update.js)の操作で変わったら、開いている節も同じ見え方に */
  document.addEventListener('friend-tidy', function (e) {
    if (drawer && UIKit.drawer.isOpen(drawer) && e.detail && typeof e.detail === 'object') fillTidy(e.detail);
  });

  /* 歯車の絵: ui-kit の gear(丸と放射の線)は小さいと点の集まりに見えて設定だと分からないので、
     歯の付いた輪の形の線の SVG をここで持つ(形は Lucide の settings = ISC ライセンス)。大きさは settings.css の .fs-gear */
  var GEAR = 'M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1' +
    'a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20' +
    'a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08' +
    'a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z';

  function gearIcon() {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    [['viewBox', '0 0 24 24'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.8'], ['stroke-linecap', 'round'],
     ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false'], ['class', 'fs-gear']].forEach(function (a) { svg.setAttribute(a[0], a[1]); });
    var path = document.createElementNS(ns, 'path');
    path.setAttribute('d', GEAR);
    var dot = document.createElementNS(ns, 'circle');
    dot.setAttribute('cx', '12');
    dot.setAttribute('cy', '12');
    dot.setAttribute('r', '3');
    svg.appendChild(path);
    svg.appendChild(dot);
    return svg;
  }

  /* 主の画面(F3-B)が置いた歯車のボタンの見た目をそろえる: 絵・押せる範囲(ほかの小さいボタンと同じ高さの正方形)・乗せたときの「設定」 */
  function dressButton(b) {
    b.textContent = '';
    b.appendChild(gearIcon());
    b.classList.add('fs-gear-btn');
    b.title = '設定';
    b.setAttribute('aria-label', '設定');
  }

  document.addEventListener('DOMContentLoaded', function () {
    var b = document.getElementById('btnSettings');
    if (!b) return;
    dressButton(b);
    b.addEventListener('click', function () { open(b); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && drawer && UIKit.drawer.isOpen(drawer)) { UIKit.drawer.close(drawer); e.stopPropagation(); }
  }, true);
})();
