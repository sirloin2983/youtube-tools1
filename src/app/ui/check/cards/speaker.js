/* 確かめるのコラボの話者のカード(/check-cards/speaker.js。11-01。口は check.js の先頭・出どころと答えの検査は src/app/check/voice_collab.py)。
   コラボの配信の 10 秒の区間を流し、話している人を全員選ぶ(何人でも・順番は聞かない)。道具の予想は出さない。声は覚えない(測る専用の正解)。
   カード: people = [その配信に出る人…](名簿の順 = 配信者を先頭にしない・配信ごとに固定)・pick = [「ほかの人を選ぶ」の欄の候補 = 名簿の全員]・otherPerson = その他の人の名前。
   答え: {names: [選んだ名前…]}(1 人以上。その他の人も 1 人)/ {choice: "other"}(声なし)。分からない(W)・飛ばす(N)は殻。
   キー: 数字 1〜n = その人を選ぶ / 外す・X = その他の人(メンバー以外)・Enter = 決める(1 人も選んでいなければ効かない)・O = 声なし。
   「ほかの人を選ぶ」の欄で選んだ人は、名前のボタンの後ろに足して選んだ状態にする(数字キーも続きの番号)。 */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var OTHER = { k: 'O', label: '声なし', title: '人の声が無い(ゲームの音・BGM だけ)' };
  var EXT = { k: 'X', label: 'その他の人', title: 'メンバー以外の人の声(1 人と数える)' };

  function list(a) { return (Array.isArray(a) ? a : []).filter(function (x) { return typeof x === 'string' && x; }); }

  CheckCards.define('speaker', function () {
    var cur = null, box = null, rctx = null;
    function names() { return list(cur.card.people).concat(cur.extra); }
    function acts() {
      var all = names();
      return '<div class="chk-spk-names" role="group" aria-label="話した人(何人でも)">' + all.map(function (n, i) {
        var on = cur.sel.indexOf(n) >= 0;
        return '<button type="button" class="btn lg chk-spk-name" aria-pressed="' + on + '" data-chk-k="' + (i + 1) + '">' +
          esc(n) + '</button>';
      }).join('') + '</div>' +
        '<div class="chk-spk-row"><label class="hint" for="chkSpkPick">出る人が違うとき: ほかの人を選ぶ</label> ' +
        '<select id="chkSpkPick" data-chk-spk-pick><option value="">(選ぶ)</option>' +
        list(cur.card.pick).filter(function (n) { return all.indexOf(n) < 0; }).map(function (n) {
          return '<option value="' + esc(n) + '">' + esc(n) + '</option>';
        }).join('') + '</select> ' + extBtn() + '</div>' +
        '<div class="chk-spk-row">' +
        '<button type="button" class="btn lg primary" data-chk-k="Enter"' + (cur.sel.length ? '' : ' disabled') + '>決める' +
        (cur.sel.length ? '(' + esc(cur.sel.join('・')) + ')' : '') + '</button> ' +
        CheckCards.btn(OTHER.label, OTHER.k, '').replace('<button ', '<button title="' + esc(OTHER.title) + '" ') + '</div>';
    }
    function extName() { return typeof cur.card.otherPerson === 'string' && cur.card.otherPerson ? cur.card.otherPerson : EXT.label; }
    function extBtn() {
      return '<button type="button" class="btn lg chk-spk-name" title="' + esc(EXT.title) + '" aria-pressed="' + (cur.sel.indexOf(extName()) >= 0) +
        '" data-chk-k="' + EXT.k + '">' + esc(EXT.label) + '</button>';
    }
    function toggle(n) {
      var i = cur.sel.indexOf(n);
      if (i >= 0) cur.sel.splice(i, 1); else cur.sel.push(n);
      repaint();
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
        el.innerHTML = '<div class="chk-q">この 10 秒で話している人は誰?(全員)</div>' +
          '<div class="chk-media"><div class="chk-stagebox" data-chk-media></div><div class="chk-info">' +
          '<p class="chk-spk-cast">この配信に出る人: <b>' + esc(list(card.people).join('・')) + '</b></p>' +
          '<p class="hint">話している人を全員選んで [決める](順番は聞きません)。メンバー以外の声は [その他の人]。声を覚える材料にはしません(測る専用)。</p>' +
          '</div></div><div class="chk-acts">' + acts() + '</div>';
        el.addEventListener('change', onPick);
        var m = card.media || {};
        if (m.url) ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: '' });
      },
      keys: function (e) {
        if (!cur || !e.fromButton) return null;
        var k = CheckCards.keyOf(e), all = names();
        if (/^[1-9]$/.test(k) && Number(k) <= all.length) {
          toggle(all[Number(k) - 1]);
          return true;
        }
        if (k === EXT.k) { toggle(extName()); return true; }
        if (k === 'Enter') return cur.sel.length ? { names: cur.sel.slice() } : true;
        if (k === OTHER.k) return { choice: 'other' };
        return null;
      },
      unmount: function () { if (box) box.removeEventListener('change', onPick); cur = null; box = null; rctx = null; }
    };
  });
})();
