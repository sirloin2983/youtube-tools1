/* 確かめるのカード「行の時刻が合っているか」(/check-cards/time.js)。V1 = 空のカード(殻の決まった形 CheckCards.simple + 波形の帯)。
   V2d が中身を作る(← → で頭・末の印を動かした量だけ行の時刻を変える = decisions 3-41・単語の印は POST api/retime の edges)。口は check.js の先頭。
   カード(V0): options ["ok", "head", "tail", "both"]・guess "ok"。答え = {choice: options の 1 つ}(仮) */
(function () {
  'use strict';
  var KEYS = { ok: ['Enter', 'ちょうどいい'], head: ['H', '頭がずれている'], tail: ['E', '末がずれている'], both: ['B', '両方'] };
  CheckCards.define('time', CheckCards.simple({
    wave: true,
    question: function () { return '行の時刻が合っているか?'; },
    options: function () {
      return ['ok', 'head', 'tail', 'both'].map(function (id) { return { k: KEYS[id][0], label: KEYS[id][1], primary: id === 'ok', answer: { choice: id } }; });
    }
  }));
})();
