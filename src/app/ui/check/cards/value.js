/* 確かめるのカード「切り抜く価値があるか(70 点以上か)」(/check-cards/value.js)。殻の決まった形 CheckCards.simple。
   自動で採った = 送る / 要らない・候補のまま = 採用 / 不採用。[送る]・[要らない] は 1 枚遅れで確定(decisions 3-41・Q12。反映は src/human/check/value.py)。口は check.js の先頭。
   カード(src/eval/check/sources.py): source auto = options ["send", "drop"]・cand = ["adopt", "reject"]。答え = {choice: options の 1 つ} */
(function () {
  'use strict';
  var LABEL = { send: '送る', drop: '要らない', adopt: '採用', reject: '不採用' };
  var TITLE = { send: '70 点以上として数え、友人へ届けます(次のカードに答えたときに確定)', drop: '70 点未満として数えます',
    adopt: '70 点以上として数え、書き出して案件の切り抜きに足します', reject: '70 点未満として数えます' };
  CheckCards.define('value', CheckCards.simple({
    question: function () { return '切り抜く価値があるか(70 点以上か)?'; },
    body: function (card) {
      var s = typeof card.score === 'number' && isFinite(card.score) ? '<p class="hint">機械の点数: ' + Math.round(card.score) + '</p>' : '';
      return (card.text ? '<p>' + UIKit.esc(card.text) + '</p>' : '') + s;
    },
    options: function (card) {
      var o = Array.isArray(card.options) && card.options.length === 2 ? card.options : (card.source === 'auto' ? ['send', 'drop'] : ['adopt', 'reject']);
      return [{ k: 'A', label: LABEL[o[0]] || String(o[0]), primary: true, answer: { choice: o[0] }, title: TITLE[o[0]] || '' },
        { k: 'X', label: LABEL[o[1]] || String(o[1]), answer: { choice: o[1] }, title: TITLE[o[1]] || '' }];
    }
  }));
})();
