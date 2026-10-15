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

  CheckCards.define('cut', function () {
    var cur = null;
    return {
      render: function (card, el, ctx) {
        var o = OPTS[card.source] || [];
        cur = { card: card, opts: o, unbind: null };
        el.innerHTML = '<div class="chk-q">' + esc(QUESTION[card.source] || '機械のカットの確認') + '</div>' +
          '<div class="chk-media"><div class="chk-stagebox" data-chk-media></div><div class="chk-info">' +
          (card.note ? '<p class="hint">' + esc(card.note) + '</p>' : '') + '</div></div>' +
          '<div class="chk-acts">' + o.map(function (x) {
            return CheckCards.btn(x.label, x.k, x.primary ? 'primary' : '').replace('<button ', '<button title="' + esc(x.title) + '" ');
          }).join('') + '</div>';
        var m = card.media || {};
        var handle = m.url ? ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: '', docId: card.target && card.target.docId }) : null;
        var v = handle && handle.media ? handle.media() : null;
        var fn = v ? skipper(card, v) : null;
        if (v && fn) {
          v.addEventListener('timeupdate', fn);
          cur.unbind = function () { v.removeEventListener('timeupdate', fn); };
        }
      },
      keys: function (e) {
        if (!cur || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return null;
        var k = CheckCards.keyOf(e);
        for (var i = 0; i < cur.opts.length; i++) {
          if (CheckCards.keyOf({ key: cur.opts[i].k }) === k) return cur.opts[i].answer;
        }
        return null;
      },
      keybar: function () { return cur ? cur.opts.slice(0, 5).map(function (x) { return { k: x.k, l: x.label }; }) : []; },
      unmount: function () { if (cur && cur.unbind) cur.unbind(); cur = null; }
    };
  });
})();
