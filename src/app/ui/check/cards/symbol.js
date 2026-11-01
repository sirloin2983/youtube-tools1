/* 確かめるの記号のカード(/check-cards/symbol.js。11-01・11-02 ユーザーの案 1。口は check.js の先頭・出どころは src/app/check/symbol_sources.py・反映は src/human/check/symbol.py)。
   文字起こしの素で、決まり(pipeline/transcribe/symbols)が消す記号が出てきた 1 か所 = 1 枚。その文の中で消すか残すかを答える。音は出さない(文字だけで決める)。
   出す物: 記号(大きく)と名前・全角 / 半角(card.name)・前後の文脈に色を付けた記号(card.context)・「消した後」の文・場面(前後の字の種類。card.scene)。
   答え(段 2): 消してよい・残す・迷う。どれも記録だけ(同じ場面の答えがたまると道具が決まりの案を作り、ユーザーが認めた物だけ決まりに入る = 画面の上の記号の決まりの欄。
   「迷う」は同じ欄の一覧で見返せる) */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var OPTS = [
    { k: 'A', label: '消してよい', primary: true, answer: { choice: 'ok' }, title: 'この文のこの記号は消してよい' },
    { k: 'K', label: '残す', answer: { choice: 'keep' }, title: 'この文のこの記号は残す(答えがたまると決まりの案になります)' },
    { k: 'U', label: '迷う', answer: { choice: 'unsure' }, title: '決められない(記録だけ。上の記号の決まりの欄の一覧で見返せます)' }
  ];

  function body(card) {
    var x = card.context || {}, ch = card.text || '';
    return '<div class="chk-sym-head"><span class="chk-sym-big" aria-label="記号">' + esc(ch) + '</span>' +
      '<span class="chk-sym-name">' + esc(card.name || '') + '</span></div>' +
      '<p class="chk-sym-ctx">' + esc(x.left || '') + '<mark class="chk-sym-mark">' + esc(ch) + '</mark>' + esc(x.right || '') + '</p>' +
      '<p class="chk-sym-after"><span class="hint">消した後: </span>' + esc(x.removed || '') + '</p>' +
      '<p class="hint">場面: ' + esc(card.scene || '') + (card.sceneCount ? '(同じ場面 ' + esc(String(card.sceneCount)) + ' か所)' : '') +
      '</p>';
  }

  CheckCards.define('symbol', CheckCards.simple({
    question: function (card) { return 'この文の「' + (card.text || '') + '」は消してよい?'; },
    body: body,
    options: function () { return OPTS; },
    media: false
  }));
})();
