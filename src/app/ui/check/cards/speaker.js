/* 確かめるのコラボの話者のカード(/check-cards/speaker.js。11-01。口は check.js の先頭・出どころと答えの検査は src/app/check/voice_collab.py)。
   コラボの配信の行を 1 つ流し、話した人を選ぶ。道具の予想は出さない。声は覚えない(測る専用の正解)。
   カード: people = [その配信に出る人…](名簿の順 = 配信者を先頭にしない・配信ごとに固定)・pick = [「ほかの人を選ぶ」の欄の候補…]。
   答え: {names: [選んだ名前…]}(1 人以上。同時に話していれば全員)/ {choice: "other"}(声が無い・叫びだけ)。分からない(W)・飛ばす(N)は殻。
   キー: 数字 1〜n = その人を選ぶ / 外す(何人でも)・Enter = 決める(1 人も選んでいなければ効かない)・O = 声が無い・叫びだけ。
   「ほかの人を選ぶ」の欄で選んだ人は、名前のボタンの後ろに足して選んだ状態にする(数字キーも続きの番号)。 */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var OTHER = { k: 'O', label: '声が無い・叫びだけ', title: '人の言葉が無い行(ゲームの音・BGM・叫び声だけ)' };

  function list(a) { return (Array.isArray(a) ? a : []).filter(function (x) { return typeof x === 'string' && x; }); }

  CheckCards.define('speaker', function () {
    var cur = null, box = null, rctx = null;
    function names() { return list(cur.card.people).concat(cur.extra); }
    function acts() {
      var all = names();
      return '<div class="chk-spk-names" role="group" aria-label="話した人(何人でも)">' + all.map(function (n, i) {
        var on = cur.sel.indexOf(n) >= 0;
        return '<button type="button" class="btn lg chk-spk-name" aria-pressed="' + on + '" data-chk-k="' + (i + 1) + '">' +
          '<kbd class="ui-kbd">' + (i + 1) + '</kbd> ' + esc(n) + '</button>';
      }).join('') + '</div>' +
        '<div class="chk-spk-row"><label class="hint" for="chkSpkPick">出る人が違うとき: ほかの人を選ぶ</label> ' +
        '<select id="chkSpkPick" data-chk-spk-pick><option value="">(選ぶ)</option>' +
        list(cur.card.pick).filter(function (n) { return all.indexOf(n) < 0; }).map(function (n) {
          return '<option value="' + esc(n) + '">' + esc(n) + '</option>';
        }).join('') + '</select></div>' +
        '<div class="chk-spk-row">' +
        '<button type="button" class="btn lg primary" data-chk-k="Enter"' + (cur.sel.length ? '' : ' disabled') + '>決める' +
        (cur.sel.length ? '(' + esc(cur.sel.join('・')) + ')' : '') + ' <kbd class="ui-kbd">Enter</kbd></button> ' +
        CheckCards.btn(OTHER.label, OTHER.k, '').replace('<button ', '<button title="' + esc(OTHER.title) + '" ') + '</div>';
    }
    function repaint() {
      var a = box && box.querySelector('.chk-acts');
      if (a) a.innerHTML = acts();
      if (rctx && typeof rctx.refreshKeys === 'function') rctx.refreshKeys();
    }
    function onPick(e) {
      var t = e.target;
      if (!cur || !t || !t.matches || !t.matches('[data-chk-spk-pick]') || !t.value) return;
      if (names().indexOf(t.value) < 0) cur.extra.push(t.value);
      if (cur.sel.indexOf(t.value) < 0) cur.sel.push(t.value);
      repaint();
      t.blur();
    }
    return {
      render: function (card, el, ctx) {
        cur = { card: card, sel: [], extra: [] }; box = el; rctx = ctx;
        el.innerHTML = '<div class="chk-q">この行を話したのは誰?</div>' +
          '<div class="chk-media"><div class="chk-stagebox" data-chk-media></div><div class="chk-info">' +
          '<p class="chk-spk-cast">この配信に出る人: <b>' + esc(list(card.people).join('・')) + '</b></p>' +
          '<p class="hint">数字キーで選んで Enter。2 人以上が同時に話していれば、全員を選んでから Enter。声を覚える材料にはしません(測る専用)。</p>' +
          '</div></div><div class="chk-acts">' + acts() + '</div>';
        el.addEventListener('change', onPick);
        var m = card.media || {};
        if (m.url) ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: '' });
      },
      keys: function (e) {
        if (!cur || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return null;
        var k = CheckCards.keyOf(e), all = names();
        if (/^[1-9]$/.test(k) && Number(k) <= all.length) {
          var n = all[Number(k) - 1], i = cur.sel.indexOf(n);
          if (i >= 0) cur.sel.splice(i, 1); else cur.sel.push(n);
          repaint();
          return true;
        }
        if (k === 'Enter') return cur.sel.length ? { names: cur.sel.slice() } : true;
        if (k === OTHER.k) return { choice: 'other' };
        return null;
      },
      keybar: function () {
        if (!cur) return [];
        var n = names().length;
        return [{ k: n > 1 ? '1〜' + n : '1', l: '人を選ぶ(何人でも)' }, { k: 'Enter', l: '決める' }, { k: OTHER.k, l: OTHER.label }];
      },
      unmount: function () { if (box) box.removeEventListener('change', onPick); cur = null; box = null; rctx = null; }
    };
  });
})();
