/* 確かめるのカード「この行は声ですか?」(/check-cards/speech.js。C-EVAL (3)。口は check.js の先頭・反映は src/human/check/speech.py)。
   出どころ speech:diar(src/app/check/speech_sources.py)= 声の区間と重なるのが少ない行。殻の決まった形 CheckCards.simple(備考 note は殻が出す)。
   options = ["keep", "drop"]。答え = {choice}。残す(A・既定)= 今のまま(文書は触らない)/ 消す(X)= 字幕に出さない印とメモ novoice を付ける(行は消さない・校正済みにしない)。 */
(function () {
  'use strict';
  var LABEL = { keep: '残す', drop: '消す' };
  var TITLE = { keep: '今のまま(文書は触りません)', drop: '字幕に出さない印を付けます。行は消しません' };
  CheckCards.define('speech', CheckCards.simple({
    question: function () { return 'この行は声ですか?(声が無ければ字幕に出しません)'; },
    body: function (card) {
      return card.text ? '<p>' + UIKit.esc(card.text) + '</p>' : '';
    },
    options: function (card) {
      var o = Array.isArray(card.options) && card.options.length === 2 ? card.options : ['keep', 'drop'];
      return [{ k: 'A', label: LABEL[o[0]] || String(o[0]), primary: true, answer: { choice: o[0] }, title: TITLE[o[0]] || '' },
        { k: 'X', label: LABEL[o[1]] || String(o[1]), answer: { choice: o[1] }, title: TITLE[o[1]] || '' }];
    }
  }));
})();
