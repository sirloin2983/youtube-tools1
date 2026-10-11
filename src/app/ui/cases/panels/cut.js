/* 案件の画面の「カット・パック」のパネル(#cut。残す区間を決めて、末尾で Resolve へ渡すパックを作る)。口の形は cases.js の先頭の説明。
   RS8 C1 では空(何の欄かと今の画面への行き先だけ)。C2c で編集の cut.js(EditCut.create(host))と pack-tab.js(EditPack.create(host))をここへ移す。
   パネルの中の要素は root.querySelector で引く(document.getElementById・document.querySelector は使わない) */
(function () {
  'use strict';
  window.CasesPanels.define('cut', function () {
    var root = null;
    function paint(ctx) {
      var cl = (ctx.item && ctx.item.clip) || {}, tx = (ctx.item && ctx.item.tx) || null, pk = cl.pack || null;
      root.innerHTML = window.CasesPanels.stub(ctx, {
        id: 'cut', title: 'カット・パック: ' + ((ctx.item && ctx.item.label) || ''),
        text: tx ? '残す区間の調整とパックづくりは、ここに入ります(準備中)。今は編集の画面で続けられます。'
                 : 'この切り抜きはまだ文字起こししていません。文字起こしすると、ここでカットとパックを作れます。',
        facts: [['カットした行', tx ? tx.cut : ''], ['パック', pk ? (pk.textplus ? 'あり(字幕つき)' : 'あり') : 'まだ']],
        href: ctx.docId ? 'transcribe/?doc=' + encodeURIComponent(ctx.docId) + '#cut' : '', link: '編集でカットを開く'
      });
    }
    return {
      id: 'cut',
      mount: function (el, ctx) { root = el; paint(ctx); },
      update: function (ctx) { if (root) paint(ctx); },
      unmount: function () { root = null; },
      keys: function () { return false; },
      keybar: function () { return []; }
    };
  });
})();
