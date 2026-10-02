/* ui-kit/styleguide.html の見本を動かす部品(CSP の script-src 'self' に合わせてインラインの <script> を使わず、この外部ファイルにした)。
   ここは見本専用で、dev/sync_ui_kit.py の写し先ではない(各ツールの画面はそれぞれの app.js 等でこれと同じ形の呼び出しを行う)。 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    // ---- 「他のツール」メニュー ----
    UIKit.tools.render(document.querySelector('[data-ui-toolnav]'), { current: 'studio' });

    // ---- 色のトークン ----
    document.getElementById('sw').innerHTML = ['--bg', '--panel', '--panel-2', '--line', '--ink', '--ink-2', '--ink-3', '--accent', '--accent-soft',
      '--ok', '--warn', '--danger', '--info', '--c-audio', '--c-chat', '--c-com']
      .map(function (v) { return '<div style="--c:var(' + v + ')">' + v + '</div>'; }).join('');
    document.getElementById('swStage').innerHTML = ['--stage-bg', '--stage-ink', '--playhead', '--toast-bg', '--toast-ink']
      .map(function (v) { return '<div class="on-stage" style="--c:var(' + v + ')">' + v + '</div>'; }).join('');

    // ---- アイコンの一覧(UIKit.icon の ICONS と同じ名前) ----
    var ICON_NAMES = ['play', 'pause', 'back', 'forward', 'frame-prev', 'frame-next', 'scissors', 'split', 'merge', 'trash', 'plus', 'minus', 'more',
      'gear', 'menu', 'close', 'chevron-down', 'chevron-right', 'chevron-left', 'folder', 'download', 'undo', 'redo', 'check', 'alert', 'info',
      'search', 'home', 'film', 'text', 'mic', 'flag', 'keyboard', 'zoom-in', 'zoom-out', 'refresh', 'external', 'copy', 'sun', 'moon',
      'mark-in', 'mark-out', 'clock', 'list', 'layers', 'wave', 'user'];
    document.getElementById('iconGrid').innerHTML = ICON_NAMES.map(function (n) {
      return '<div><span class="ui-icon" data-icon="' + n + '"></span><small>' + n + '</small></div>';
    }).join('');
    UIKit.icon.fill(document.getElementById('iconGrid'));

    // ---- 引き出し(drawer) ----
    var drawerModal = document.getElementById('drawerModalDemo');
    if (!drawerModal) {
      drawerModal = document.createElement('aside');
      drawerModal.id = 'drawerModalDemo'; drawerModal.className = 'ui-drawer'; drawerModal.hidden = true;
      drawerModal.setAttribute('aria-labelledby', 'drawerModalTitle');
      drawerModal.innerHTML = '<div class="ui-drawer-head"><h2 class="ui-drawer-title" id="drawerModalTitle">設定ふうの引き出し</h2>' +
        '<button type="button" class="btn ghost icon small" id="drawerModalClose" aria-label="閉じる"><span class="ui-icon" data-icon="close"></span></button></div>' +
        '<div class="ui-drawer-body"><p class="hint">modal:true。裏(ヘッダー・本文)は inert になり、Tab で外へ出られません。Esc でも閉じます。</p>' +
        '<button type="button" class="btn" id="drawerModalFocusCheck">中のボタン</button></div>';
      document.body.appendChild(drawerModal);
      UIKit.icon.fill(drawerModal);
      drawerModal.querySelector('#drawerModalClose').addEventListener('click', function () { UIKit.drawer.close(drawerModal); });
    }
    document.getElementById('btnDrawerModal').addEventListener('click', function (e) {
      UIKit.drawer.open(drawerModal, { modal: true, opener: e.currentTarget });
    });

    var drawerDocked = document.getElementById('drawerDockedDemo');
    if (!drawerDocked) {
      drawerDocked = document.createElement('aside');
      drawerDocked.id = 'drawerDockedDemo'; drawerDocked.className = 'ui-drawer'; drawerDocked.hidden = true;
      drawerDocked.setAttribute('aria-labelledby', 'drawerDockedTitle');
      drawerDocked.innerHTML = '<div class="ui-drawer-head"><h2 class="ui-drawer-title" id="drawerDockedTitle">書き出しふうの引き出し</h2>' +
        '<button type="button" class="btn ghost icon small" id="drawerDockedClose" aria-label="閉じる"><span class="ui-icon" data-icon="close"></span></button></div>' +
        '<div class="ui-drawer-body"><p class="hint">modal:false(docked)。幕が無く、裏の画面も操作できます。開いたまま他の作業を続けられます。</p></div>';
      document.body.appendChild(drawerDocked);
      UIKit.icon.fill(drawerDocked);
      drawerDocked.querySelector('#drawerDockedClose').addEventListener('click', function () { UIKit.drawer.close(drawerDocked); });
    }
    document.getElementById('btnDrawerDocked').addEventListener('click', function (e) {
      UIKit.drawer.open(drawerDocked, { modal: false, opener: e.currentTarget });
    });

    // ---- ダイアログ ----
    document.getElementById('btnConfirm').addEventListener('click', function () {
      UIKit.dialog.confirm({ title: '削除しますか', body: 'この操作は元に戻せません。', ok: '削除する', cancel: 'キャンセル', danger: true })
        .then(function (ok) { UIKit.toast(ok ? '削除しました(見本。実際には消していません)' : 'キャンセルしました', { kind: ok ? 'ok' : 'info' }); });
    });
    document.getElementById('btnAlert').addEventListener('click', function () {
      UIKit.dialog.alert({ title: 'お知らせ', body: 'これは見本のお知らせダイアログです。' });
    });

    // ---- トースト ----
    document.getElementById('btnToastOk').addEventListener('click', function () { UIKit.toast('保存しました', { kind: 'ok' }); });
    document.getElementById('btnToastErr').addEventListener('click', function () {
      UIKit.toast('書き出しに失敗しました。ディスクの空きを確かめてください', { kind: 'err', detail: 'OSError: [Errno 28] No space left on device' });
    });
    document.getElementById('btnToastInfo').addEventListener('click', function () { UIKit.toast('自動では始めません', { kind: 'info' }); });

    // ---- 版の帯(UIKit.restart。v10)。window.__restartDemoOpts はテストが待つ間隔を短くするため ----
    document.getElementById('btnRestartBand').addEventListener('click', function () {
      UIKit.restart.check(document.getElementById('restartBandDemo'), '0.2.0', '0.1.0', window.__restartDemoOpts || {});
    });

    // ---- 時刻の欄(UIKit.timebox。v11) ----
    var tbStart = document.getElementById('tbStart'), tbEnd = document.getElementById('tbEnd'), tbMsg = document.getElementById('tbMsg'), tbHelp = tbMsg.textContent;
    function tbShowLen() {
      var a = UIKit.timebox.get(tbStart), b = UIKit.timebox.get(tbEnd), bad = a !== null && b !== null && b <= a;
      document.getElementById('tbLen').textContent = a !== null && b !== null && b > a ? '長さ ' + UIKit.fmt.dur(b - a) : '長さ —';
      if (bad) tbEnd.setAttribute('aria-invalid', 'true'); else tbEnd.removeAttribute('aria-invalid');   // 誤りの見せ方は使う画面が決める
      tbMsg.textContent = bad ? '終了が開始より前です。終了の時刻を直してください' : tbHelp;
    }
    document.addEventListener('ui-time', function (e) { window.__tbLast = { id: e.target.id, value: e.detail.value }; tbShowLen(); });
    document.addEventListener('ui-time-reject', function (e) { window.__tbReject = { id: e.target.id, reason: e.detail.reason }; tbMsg.textContent = e.detail.reason; });
    document.getElementById('tbPlus30').addEventListener('click', function () {
      var a = UIKit.timebox.get(tbStart);
      if (a === null) { tbMsg.textContent = '先に開始の時刻を入れてください'; tbStart.focus(); return; }
      UIKit.timebox.set(tbEnd, a + 30);
      tbShowLen();
    });

    // ---- 下の帯(keybar) ----
    document.getElementById('btnKeybarSet').addEventListener('click', function () {
      UIKit.keybar.set([{ k: 'Space', l: '再生・停止' }, { k: '↓', l: '次の行' }, { k: '↑', l: '前の行' }, { k: 'Shift+Space', l: '校正済みで次へ' }, { k: '?', l: 'キー操作' }]);
    });
    document.getElementById('btnKeybarFlash').addEventListener('click', function () { UIKit.keybar.flash('Space'); });
    document.getElementById('btnKeybarClear').addEventListener('click', function () { UIKit.keybar.clear(); });

    // ---- 共通の再生キー(ダミーの media) ----
    document.getElementById('keysHelpBox').innerHTML = '<div class="ui-kgrid">' + UIKit.keys.helpHtml() + '</div>';
    var fakeTimeEl = document.getElementById('fakeTime'), fakeRateEl = document.getElementById('fakeRate');
    var fakeMedia = { currentTime: 0, duration: 600, paused: true, playbackRate: 1,
      play: function () { this.paused = false; paintFake(); }, pause: function () { this.paused = true; paintFake(); } };
    function paintFake() { fakeTimeEl.textContent = fakeMedia.currentTime.toFixed(2); fakeRateEl.textContent = fakeMedia.playbackRate.toFixed(1); }
    var handlePlayback = UIKit.keys.playback({
      media: fakeMedia, fps: 30,
      onIn: function () { UIKit.toast('始まりの印(見本)', { kind: 'info', ms: 1200 }); },
      onOut: function () { UIKit.toast('終わりの印(見本)', { kind: 'info', ms: 1200 }); },
      onKey: function () { paintFake(); }
    });
    document.addEventListener('keydown', function (e) { handlePlayback(e); });

    // ---- 設定(⚙。UIKit.settings.mount) ----
    var toolSection = document.getElementById('tool-settings-body');
    toolSection.hidden = false;
    UIKit.settings.mount({ tool: toolSection, title: 'ui-kit 見本の設定', version: 'v6' });
  });
})();
