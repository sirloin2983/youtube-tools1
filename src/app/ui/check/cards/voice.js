/* 確かめるのカード「これは誰の声?」(/check-cards/voice.js。V2c。口は check.js の先頭・反映は src/human/check/voice.py)。
   全部のカードに機械の予想(card.guess)を付け、合っていれば Enter。**行の再生が終わるまで Enter は効かない**(よく聞かずに押すのを防ぐ。ボタンも押せない)。
   カード: options = [{id, name, voice?}…(文書の話者・覚えた声の登録簿にいて文書にいない人 = id "name:<名前>"), {id: "other"}, {id: "mixed"}]・guess = {id, name}。
   答え = {choice: 話者の id} / {name: 名前}(id が "name:" で始まる人 = 文書に話者を足す)/ {choice: "other"}(その他・ゲームの音など)/ {choice: "mixed"}(声が混ざっている)。
   G = 「ゲーム音・BGM が大きい」の切り替え(押してから名前などを選ぶ)。入っていると答えに bgm: true を足す = 話者はその人・行の音のメモ bgm・覚える材料にしない。
   名前で答えた行(1 秒以上・混ざっていない・音のメモが無い・評価用でない)は、その人の声を覚え直す材料になる(1 人 30 秒分たまったら自動で。サーバーの側)。
   キー: 名前は数字キー 1〜9・その他 O・混ざり M・予想どおり Enter・ゲーム音・BGM が大きい G */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var EXTRA = { other: { k: 'O', label: 'その他(ゲームの音など)' }, mixed: { k: 'M', label: '声が混ざっている' } };
  var NAME_PREFIX = 'name:';
  var NOTE = { below_match: '覚えた声との似かたが弱い話者です', margin: '覚えた声の 2 人が近く、どちらか決めきれなかった話者です',
    solo: 'ソロ配信と見た配信の行です(声を覚える材料を集めています)。ほかの人の声ならその人を、分からなければ [飛ばす]' };
  var WAIT = '再生が終わってから押せます(よく聞いてから答えるため)';
  var BGM = { k: 'G', label: 'ゲーム音・BGM が大きい', title: '入れてから名前を選ぶと、話者はその人・行に「BGM が大きい」の音のメモを付け、声を覚える材料にしません' };

  function answerOf(id, st) {
    var a = id.indexOf(NAME_PREFIX) === 0 ? { name: id.slice(NAME_PREFIX.length) } : { choice: id };
    if (st && st.bgm) a.bgm = true;
    return a;
  }
  function options(card) {
    return (Array.isArray(card.options) ? card.options : []).filter(function (o) { return o && typeof o === 'object' && typeof o.id === 'string' && o.id; });
  }
  function guessOf(card) {
    var g = card.guess && typeof card.guess === 'object' && typeof card.guess.id === 'string' && card.guess.id ? card.guess : null;
    return g && options(card).some(function (o) { return o.id === g.id; }) ? g : null;
  }

  var base = CheckCards.simple({
    question: function () { return 'これは誰の声?'; },
    body: function (card) {
      var g = guessOf(card);
      return (g ? '<p class="notice info">機械の予想: <b>' + esc(g.name || g.id) + '</b>(再生が終わると Enter で予想どおりに答えられます)</p>' :
        '<p class="notice info">機械の予想はありません。聞いて選んでください。</p>') +
        '<p class="hint">名前を選んだ行は、その人の声を覚え直す材料になります(1 秒以上・混ざっていない行)。</p>';
    },
    hint: function (card, st) {
      return st.bgm ? '<p class="hint" data-chk-bgm>ゲーム音・BGM が大きい行として答えます(声を覚える材料にしません。G でやめる)</p>' : '';
    },
    options: function (card, st) {
      var all = options(card), g = guessOf(card);
      var out = all.filter(function (o) { return !EXTRA[o.id]; }).slice(0, 9).map(function (o, i) {
        var nm = o.name || o.id;
        return { k: String(i + 1), label: nm, primary: !!g && o.id === g.id, answer: function (c, p, s) { return answerOf(o.id, s); },
          title: o.id.indexOf(NAME_PREFIX) === 0 ? '覚えた声の人です(この文書の話者に「' + nm + '」を足します)' : '' };
      });
      if (g) {
        out.push({ k: 'Enter', label: '予想どおり', title: WAIT,
          answer: function (c, player, s) { return !player || player.ended() ? answerOf(g.id, s) : null; } });
      }
      all.forEach(function (o) {
        if (EXTRA[o.id]) out.push({ k: EXTRA[o.id].k, label: EXTRA[o.id].label, answer: function (c, p, s) { return answerOf(o.id, s); } });
      });
      out.push({ k: BGM.k, label: BGM.label, title: BGM.title, pressed: !!st.bgm,
        answer: function (c, p, s, repaint) { s.bgm = !s.bgm; repaint(); return null; } });
      return out;
    },
    keybar: function (card, st) {
      var o = options(card).filter(function (x) { return !EXTRA[x.id]; }).slice(0, 4).map(function (x, i) { return { k: String(i + 1), l: x.name || x.id }; });
      if (guessOf(card)) o.push({ k: 'Enter', l: '予想どおり' });
      o.push({ k: BGM.k, l: st.bgm ? 'BGM が大きい: 入' : BGM.label });
      return o;
    }
  });

  CheckCards.define('voice', function () {
    var view = base(), gone = false, lock = null;
    return {
      render: function (card, el, ctx) {
        var handle = null;
        var shown = Object.assign({}, card, { note: NOTE[card.note] || '' });
        view.render(shown, el, Object.assign({}, ctx, {
          player: function (box, media, opt) { handle = ctx.player(box, media, opt); return handle; }
        }));
        lock = function () {   // G でボタンを描き直したときも、再生が終わるまで Enter を押せないままにする
          var enter = el.querySelector('[data-chk-k="Enter"]');
          if (!enter || gone) return;
          var wait = !!handle && !handle.ended();
          enter.disabled = wait;
          if (wait) enter.setAttribute('data-ui-why', WAIT); else enter.removeAttribute('data-ui-why');
          enter.title = wait ? WAIT : '機械の予想どおりに答えます';
        };
        lock();
        if (handle && !handle.ended()) handle.onEnded(function () { if (lock) lock(); });
      },
      keys: function (e, card) {
        var r = view.keys(e, card);
        if (r === true && lock) lock();
        return r;
      },
      keybar: function (card) { return view.keybar(card); },
      unmount: function () { gone = true; lock = null; view.unmount(); }
    };
  });
})();
