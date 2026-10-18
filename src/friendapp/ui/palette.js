/* 友人のアプリの配色(A ネオンシアン・B シンセウェーブ・C ターミナルグリーン・D アイスライト)。
   色は ui-kit のトークン(--bg・--panel・--ink・--accent など)だけで切り替える = 送る・受け取る・再生・⚙・初回の準備の全部が同じ変数を読む。
   ui-kit.js の直後に <script src="palette.js"></script>(defer なし)で読む = 描く前に色を決める(ちらつかない)。
   選んだ配色は玄関が覚える(<玄関>/palette.json・画面へは meta ytt-palette。exe は起動ごとに番号が変わる = ブラウザの保存は次に開いたとき使えない)。
   変える口 = POST api/friend/palette {name}。見本のボタンは [data-fr-palette] の入れ物に描く(無ければ描かない)。
   変数の名前は ui-kit のまま(--bg・--bg-2・--panel〜--panel-3・--field・--line〜--line-strong・--ink〜--ink-4・--accent・--accent-ink・--accent-soft・--accent-line・
   --ok・--warn・--danger・--info とその -ink・-soft)。data-theme(light / dark)と data-palette(cyan / synth / green / ice)を ui-kit の UIKit.theme が付ける */
(function () {
  'use strict';
  var LIST = [
    { name: 'A', label: 'ネオンシアン', theme: 'dark', pal: 'cyan', bg: '#0A0E14', accent: '#19D3F3' },
    { name: 'B', label: 'シンセウェーブ', theme: 'dark', pal: 'synth', bg: '#0D0A17', accent: '#FF3DA5' },
    { name: 'C', label: 'ターミナルグリーン', theme: 'dark', pal: 'green', bg: '#060B08', accent: '#3DFF8B' },
    { name: 'D', label: 'アイスライト', theme: 'light', pal: null, bg: '#EEF2F8', accent: '#1F5BFF' }
  ];
  function find(n) { for (var i = 0; i < LIST.length; i++) if (LIST[i].name === n) return LIST[i]; return null; }
  var meta = document.querySelector('meta[name="ytt-palette"]');
  var cur = find(meta && meta.content) || LIST[0];

  function paint(p) {
    if (!window.UIKit || !UIKit.theme) return;
    if (p.pal) UIKit.theme.palette(p.pal);   /* 暗いときの配色を先に(明るい/暗いを変えたときに一度で正しい色になる) */
    UIKit.theme.set(p.theme);
  }
  function mark() {
    var bs = document.querySelectorAll('[data-fr-palette] button');
    for (var i = 0; i < bs.length; i++) bs[i].setAttribute('aria-pressed', bs[i].getAttribute('data-name') === cur.name ? 'true' : 'false');
  }
  function set(name) {
    var p = find(name);
    if (!p || p === cur) return Promise.resolve(cur.name);
    cur = p;
    paint(p);
    mark();
    return UIKit.http('api/friend/palette', { body: { name: p.name } }).then(function () { return p.name; },
      function (e) { UIKit.toast('配色を覚えられませんでした(次に開くと前の配色に戻ります): ' + e.message, { kind: 'err', ms: 5000 }); return p.name; });
  }
  function draw(box) {
    box.textContent = '';
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', '配色');
    var lab = document.createElement('span');
    lab.className = 'fr-pal-label';
    lab.textContent = '配色';
    box.appendChild(lab);
    LIST.forEach(function (p) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'fr-pal';
      b.setAttribute('data-name', p.name);
      b.setAttribute('aria-label', '配色 ' + p.name + ' ' + p.label);
      b.title = '配色 ' + p.name + ' ' + p.label;
      var sw = document.createElement('span');
      sw.className = 'fr-pal-sw';
      sw.setAttribute('aria-hidden', 'true');
      sw.style.background = 'linear-gradient(135deg,' + p.bg + ' 0 52%,' + p.accent + ' 52% 100%)';
      b.appendChild(sw);
      b.addEventListener('click', function () { set(p.name); });
      box.appendChild(b);
    });
    mark();
  }
  var audit = false;   /* dev/ui_audit.py が明るい・暗いを自分で決めて確かめるとき(localStorage の ytt:palette-audit)は、覚えた配色で塗らない */
  try { audit = localStorage.getItem('ytt:palette-audit') === '1'; } catch (e) { audit = false; }
  if (!audit) paint(cur);
  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(document.querySelectorAll('[data-fr-palette]'), draw);
  });
  window.FriendPalette = { LIST: LIST, get: function () { return cur.name; }, set: set };
})();
