/* 確かめるのカード「これは誰の声?」(/check-cards/voice.js)。V1 = 空のカード(殻の決まった形 CheckCards.simple)。
   V2c が中身を作る(機械の予想・再生が終わるまで Enter は効かない・名前 / その他 / 混ざり・名前を付けた行は声を覚える材料)。口は check.js の先頭。
   カード(V0): options = [{id, name}…, {id: "other"}, {id: "mixed"}]・guess = {id, name}。答え = {choice: 話者の id}(仮)。
   名前は数字キー 1〜9・その他 O・混ざり M・予想どおり Enter */
(function () {
  'use strict';
  var EXTRA = { other: { k: 'O', label: 'その他(ゲームの音など)' }, mixed: { k: 'M', label: '声が混ざっている' } };
  CheckCards.define('voice', CheckCards.simple({
    question: function () { return 'これは誰の声?'; },
    body: function (card) {
      var g = card.guess;
      return g && g.id ? '<p class="notice info">機械の予想: <b>' + UIKit.esc(g.name || g.id) + '</b>(再生が終わると Enter で予想どおりに答えられます)</p>' : '';
    },
    options: function (card) {
      var all = (Array.isArray(card.options) ? card.options : []).filter(function (o) { return o && typeof o === 'object' && typeof o.id === 'string' && o.id; });
      var g = card.guess && card.guess.id ? card.guess : null;
      var out = all.filter(function (o) { return !EXTRA[o.id]; }).slice(0, 9).map(function (o, i) {
        return { k: String(i + 1), label: o.name || o.id, primary: !!g && o.id === g.id, answer: { choice: o.id } };
      });
      if (g) {
        out.push({ k: 'Enter', label: '予想どおり', title: '再生が終わってから押せます',
          answer: function (c, player) { return !player || player.ended() ? { choice: g.id } : null; } });
      }
      all.forEach(function (o) { if (EXTRA[o.id]) out.push({ k: EXTRA[o.id].k, label: EXTRA[o.id].label, answer: { choice: o.id } }); });
      return out;
    }
  }));
})();
