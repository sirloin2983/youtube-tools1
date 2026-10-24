/* 確かめるの自動カットのカード(/check-cards/cut.js。CUT-CARD。口は check.js の先頭・出どころは src/app/check/cut_sources.py・反映は src/human/check/cutcard.py)。
   出どころ 3 つ(card.source): edge = 切れ目(前後 2 秒をつないで流す・消した所は飛ばす)/ gap = 消した所(消した所だけ流す)/ whole = 仕上がり(残した所を通しで流し、消した所は飛ばす)。
   答えは記録するだけ(文書は触らない)。キー: edge = Enter 良い・E 早すぎ・L 遅すぎ・K 切らない / gap = A 消してよい・K 残すべき / whole = Enter 良い・T テンポ・U 不自然。 */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var OPTS = {
    edge: [
      { k: 'Enter', label: '良い', primary: true, answer: { choice: 'good' }, title: 'ちょうどいい切れ目' },
      { k: 'E', label: '早すぎ(言葉が切れる)', answer: { choice: 'early' }, title: '切れ目が早すぎて言葉が切れている' },
      { k: 'L', label: '遅すぎ(間が残る)', answer: { choice: 'late' }, title: '切れ目が遅くて間が残っている' },
      { k: 'K', label: 'ここは切らない', answer: { choice: 'keep' }, title: 'この所は切ってはいけない(笑い・反応など)' }
    ],
    gap: [
      { k: 'A', label: '消してよい', primary: true, answer: { choice: 'ok' }, title: '消した所は消してよい' },
      { k: 'K', label: '残すべき(笑い・反応など)', answer: { choice: 'keep' }, title: '消した所は残すべき' }
    ],
    whole: [
      { k: 'Enter', label: '良い', primary: true, answer: { choice: 'good' }, title: '自動で切った 1 本は自然' },
      { k: 'T', label: 'テンポが悪い', answer: { choice: 'tempo' }, title: '切ったあとのテンポが悪い' },
      { k: 'U', label: '不自然な所がある', answer: { choice: 'unnatural' }, title: '不自然な所がある' }
    ]
  };
  var QUESTION = {
    edge: '切れ目はちょうどいい?(前後 2 秒をつないで流します)',
    gap: '機械が消した所です。消してよい?',
    whole: '自動で切った 1 本は自然?'
  };

  // 残す区間の外(消した所)にいるときは次の残す区間の頭へ飛ばす
  function skipper(card, v) {
    var t = card.target || {};
    if (card.source === 'edge' || card.source === 'gap') {
      var c = t.cut;
      if (!Array.isArray(c) || c.length !== 2) return null;
      return function () {
        var now = v.currentTime;
        if (card.source === 'edge' && now > c[0] && now < c[1]) v.currentTime = c[1];
      };
    }
    if (card.source === 'whole') {
      var keeps = Array.isArray(t.keeps) ? t.keeps : [];
      return function () {
        var now = v.currentTime;
        for (var i = 0; i < keeps.length; i++) {
          if (keeps[i][1] > now) {
            if (keeps[i][0] > now) v.currentTime = keeps[i][0];
            return;
          }
        }
      };
    }
    return null;
  }

  CheckCards.define('cut', CheckCards.simple({
    question: function (card) { return QUESTION[card.source] || '機械のカットの確認'; },
    options: function (card) { return OPTS[card.source] || []; },
    text: false,
    confine: true,   // 切れ目の自然さを聞く区間が決まっている = 窓の中だけ流す
    mounted: function (card, handle) {
      var v = handle && handle.media ? handle.media() : null, fn = v ? skipper(card, v) : null;
      if (!v || !fn) return null;
      v.addEventListener('timeupdate', fn);
      return function () { v.removeEventListener('timeupdate', fn); };
    }
  }));
})();
