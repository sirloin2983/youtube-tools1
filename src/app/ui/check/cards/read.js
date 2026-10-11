/* 確かめるのカード「どちらの読みが正しいか」(/check-cards/read.js)。V1 = 空のカード(殻の決まった形 CheckCards.simple + 比べる欄 ui-kit の .ui-pair)。
   V2b が中身を作る(3 = どちらも違う(打つ)・文字だけの判定 = 校正済みにしない・時刻の正解に使わない)。口は check.js の先頭。
   カード(V0): options = [{id: "1", text}, {id: "2", text}](read:fill は 1 = 後処理のあと・2 = 認識のまま)・guess "1"。答え = {choice: "1" | "2"}(仮) */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var LABELS = { fill: ['後処理のあと', '認識のまま'], alt: ['今の字幕', '2 つ目のエンジン'], yt: ['今の字幕', 'YouTube の字幕'] };
  function opts(card) {
    return (Array.isArray(card.options) ? card.options : []).filter(function (x) { return x && typeof x === 'object'; }).slice(0, 2);
  }
  function pair(card) {
    var o = opts(card), lb = LABELS[card.source] || ['', ''];
    if (o.length < 2) return '';
    return '<div class="ui-pair">' + o.map(function (x, i) {
      return '<div class="ui-pair-opt"><span class="ui-pair-lb">' + (i + 1) + ' ' + esc(x.label || lb[i]) + '</span><p>' + esc(x.text || '(文字なし)') + '</p></div>';
    }).join('') + '</div>';
  }
  CheckCards.define('read', CheckCards.simple({
    question: function () { return 'どちらの読みが正しい?'; },
    body: function (card) { return pair(card) + '<p class="hint">文字だけの判定です(行を校正済みにしない・時刻の正解には使わない)。</p>'; },
    options: function (card) {
      return opts(card).map(function (x, i) { return { k: String(i + 1), label: (i + 1) + ' が正しい', answer: { choice: String(x.id || i + 1) } }; });
    }
  }));
})();
