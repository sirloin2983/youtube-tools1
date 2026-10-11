/* 案件の画面の「校正」のパネル(#proof。切り抜き 1 本の文字起こしの行を直す)。口の形は cases.js の先頭の説明。
   RS8 C1 では空(何の欄かと今の画面への行き先だけ)。C2b で編集 1 の行の編集(app-rows・app-core の保存と 409・行の道具・話者・札)と
   小さい配信プレーヤー・機械の結果が変わった行の 3 択(panels/machpick.js)をここへ移す。
   パネルの中の要素は root.querySelector で引く(document.getElementById・document.querySelector は使わない) */
(function () {
  'use strict';
  window.CasesPanels.define('proof', function () {
    var root = null;
    function paint(ctx) {
      var tx = (ctx.item && ctx.item.tx) || null;
      root.innerHTML = window.CasesPanels.stub(ctx, {
        id: 'proof', title: '校正: ' + ((ctx.item && ctx.item.label) || ''),
        text: tx ? '行の文字・話者・時刻の直しは、ここに入ります(準備中)。今は編集の画面で続けられます。'
                 : 'この切り抜きはまだ文字起こししていません。文字起こしすると、ここで校正できます。',
        facts: [['文書', tx ? tx.title || tx.id : ''], ['行', tx ? tx.segments : ''], ['校正済みの行', tx ? tx.proofed : '']],
        href: ctx.docId ? 'transcribe/?doc=' + encodeURIComponent(ctx.docId) + '#tx' : '', link: '編集で校正を開く'
      });
    }
    return {
      id: 'proof',
      mount: function (el, ctx) { root = el; paint(ctx); },
      update: function (ctx) { if (root) paint(ctx); },
      unmount: function () { root = null; },
      keys: function () { return false; },
      keybar: function () { return []; }
    };
  });
})();
