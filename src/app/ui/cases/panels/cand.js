/* 案件の画面の「候補」のパネル(#cand。配信全体の候補・採用・書き出し)。口の形は cases.js の先頭の説明。
   RS8 C1 では空(何の欄かと今の画面への行き先だけ)。C2a でスタジオ ② の review.js(プレーヤー・タイムライン・マークの一覧・採用 / 不採用・書き出し・LivePlayer)をここへ移す。
   パネルの中の要素は root.querySelector で引く(document.getElementById・document.querySelector は使わない = 殻とほかのパネルの id とぶつからない) */
(function () {
  'use strict';
  window.CasesPanels.define('cand', function () {
    var root = null;
    function paint(ctx) {
      var c = ctx.case || {}, mk = c.marks || {};
      root.innerHTML = window.CasesPanels.stub(ctx, {
        id: 'cand', title: '候補(配信全体)',
        text: '配信のプレーヤー・タイムライン・候補の一覧と採用 / 不採用・書き出しは、ここに入ります(準備中)。今はスタジオの画面で続けられます。',
        facts: [['候補', mk.candidates || 0], ['採用(書き出し前)', mk.adopted || 0], ['書き出した切り抜き', mk.exported || 0], ['種類', ctx.caseKind === 'live' ? 'ライブの録画' : '配信']],
        href: ctx.videoId ? 'studio/?video=' + encodeURIComponent(ctx.videoId) : '', link: 'スタジオで候補を開く'
      });
    }
    return {
      id: 'cand',
      mount: function (el, ctx) { root = el; paint(ctx); },
      update: function (ctx) { if (root) paint(ctx); },
      unmount: function () { root = null; },
      keys: function () { return false; },
      keybar: function () { return []; }
    };
  });
})();
