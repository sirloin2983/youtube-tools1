/* 確かめるの記号のカード(/check-cards/symbol.js。11-01。口は check.js の先頭・出どころは src/app/check/symbol_sources.py・反映は src/human/check/symbol.py)。
   文字起こしの素から、決まり(pipeline/transcribe/symbols)が消す記号 1 つ = 1 枚。前後 10 字の文脈を 1〜3 個、記号に色を付けて並べる。音は出さない(文字だけで決める)。
   答え: A 消してよい・K 例外にする(次から消さない字に足す。Z で外れる)・U 迷う。 */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var OPTS = [
    { k: 'A', label: '消してよい', primary: true, answer: { choice: 'ok' }, title: 'この記号は文字起こしから消してよい' },
    { k: 'K', label: '例外にする', answer: { choice: 'keep' }, title: 'この記号は消さずに残す(次から例外の字)' },
    { k: 'U', label: '迷う', answer: { choice: 'unsure' }, title: '決められない(記録だけ)' }
  ];

  function body(card) {
    var ex = Array.isArray(card.examples) ? card.examples : [];
    var mark = '<mark class="chk-sym-mark">' + esc(card.text || '') + '</mark>';
    return '<div class="chk-sym-big" aria-label="記号">' + esc(card.text || '') + '</div>' +
      '<p class="hint">消した数 ' + esc(String(card.count || 0)) + ' 回・' + esc(String(card.docs || 0)) + ' 本</p>' +
      '<ul class="chk-sym-ex">' + ex.map(function (e) {
        return '<li><span class="chk-sym-ctx">' + esc(e.left || '') + mark + esc(e.right || '') + '</span>' +
          '<span class="chk-sym-src">' + esc(e.title || '') + '</span></li>';
      }).join('') + '</ul>';
  }

  CheckCards.define('symbol', CheckCards.simple({
    question: function () { return '文字起こしから消した記号です。消してよい?'; },
    body: body,
    options: function () { return OPTS; },
    media: false
  }));
})();
