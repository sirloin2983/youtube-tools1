/* 確かめるのカード「価値」(/check-cards/value.js)。口は check.js の先頭。
   source auto(自動でできた切り抜き・2-8) = 送った後の品質の確認: [良い](A) / [悪い](X) / [不明](S・どちらとも言えない = 理由なしで記録)。悪いを押したら理由の札を 1 つ選べる(数字 1〜7・任意。Enter = 理由なしで記録)。
     記録だけ(src/human/check/value.py)。送るかには効かせない = [送る]・[要らない] は無い。すぐ記録(1 枚遅れなし)。Z で記録を取り消す。
   source cand(候補のまま) = 採用 / 不採用(殻の決まった形 CheckCards.simple・今のまま。1 枚遅れで確定)。
   カード(src/app/check/sources.py): auto = options ["good","bad","unknown"]・reasons [{id, text}] / cand = options ["adopt","reject"]。答え = {choice} / 悪いの理由 {choice:"bad", reason: id}
   5 段階の点(10-29。友人のアプリ src/friendapp/ui/receive.js と同じ形): [1]〜[5] のボタンか数字のキーで選ぶ・同じ数をもう一度で外す。答えに score(1〜5・付けなければ無し)を
   一緒に送る(付けずに答えてもよい)。auto の悪いの理由の段は数字が理由の札なので点は出さない(点は前の段で選ぶ)。押し続けの守りは殻(check.js の e.repeat) */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var LABEL = { adopt: '採用', reject: '不採用' };
  var TITLE = { adopt: '70 点以上として数え、書き出して案件の切り抜きに足します', reject: '70 点未満として数えます' };
  var AUTO_TITLE = { good: '出来が良い(記録だけ。送るかには効きません)', bad: '出来が悪い(理由の札を選べます・記録だけ)', unknown: 'どちらとも言えない(記録だけ)' };
  var WHY = '悪い理由を 1 つ選べます(数字)。選ばずに記録するなら Enter';
  var SCORE = [[1, 'つまらない'], [2, 'いまいち'], [3, 'ふつう'], [4, '面白い'], [5, 'すごく面白い']];
  function scored(answer, st) { return st.score ? Object.assign({}, answer, { score: st.score }) : answer; }
  function scoreOpts(st) {   // 押す = 選ぶ・同じ数をもう一度 = 外す(答えではない = ボタンだけ描き直す)
    return SCORE.map(function (p) {
      return { k: String(p[0]), label: p[0] + ' ' + p[1], pressed: st.score === p[0], title: '面白さ ' + p[1] + '(キー ' + p[0] + '。もう一度押すと外す)',
        answer: function (c, h, s, repaint) { s.score = s.score === p[0] ? null : p[0]; repaint(); return null; } };
    });
  }
  var MIX_GUIDE = '<p class="hint">声の重なり・BGM が大きいことは減点にしません(中身で決める)。</p>';   // 10-25 確かめるの混ざりと BGM のルール

  function candBody(card) {
    var s = typeof card.score === 'number' && isFinite(card.score) ? '<p class="hint">機械の点数: ' + Math.round(card.score) + '</p>' : '';
    return (card.text ? '<p>' + esc(card.text) + '</p>' : '') + s;
  }
  var cand = CheckCards.simple({
    question: function () { return '切り抜く価値があるか(70 点以上か)?'; },
    body: candBody,
    after: function () { return MIX_GUIDE; },
    options: function (card, st) {
      var o = Array.isArray(card.options) && card.options.length === 2 ? card.options : ['adopt', 'reject'];
      return [{ k: 'A', label: LABEL[o[0]] || String(o[0]), primary: true, answer: scored({ choice: o[0] }, st), title: TITLE[o[0]] || '' },
        { k: 'X', label: LABEL[o[1]] || String(o[1]), answer: scored({ choice: o[1] }, st), title: TITLE[o[1]] || '' }].concat(scoreOpts(st));
    },
    keybar: function (card) {
      var o = Array.isArray(card.options) && card.options.length === 2 ? card.options : ['adopt', 'reject'];
      return [{ k: 'A', l: LABEL[o[0]] || String(o[0]) }, { k: 'X', l: LABEL[o[1]] || String(o[1]) }, { k: '1〜5', l: '面白さ' }];
    }
  });

  /* 自動でできた切り抜き: 2 段(良い / 悪い → 悪いのとき理由の札)。段は st.step に持つ(カードが変わると作り直す) */
  function reasons(card) { return Array.isArray(card && card.reasons) ? card.reasons.filter(function (r) { return r && typeof r.id === 'string' && r.id; }).slice(0, 7) : []; }
  var autoView = CheckCards.simple({
    question: function () { return '送ったあとの出来は良いか?'; },
    body: function (c) {
      var s = typeof c.score === 'number' && isFinite(c.score) ? '<p class="hint">機械の点数: ' + Math.round(c.score) + '</p>' : '';
      return (c.text ? '<p>' + esc(c.text) + '</p>' : '') + s;
    },
    after: function () { return '<p class="hint">送ったかどうかは見ずに、出来だけを見てください(記録だけ・送るかには効きません)</p>' + MIX_GUIDE; },
    wave: false,
    hint: function (card, st) { return st.step === 'why' ? '<p class="hint">' + esc(WHY) + '</p>' : ''; },
    options: function (card, st) {
      if (st.step === 'why') {
        return reasons(card).map(function (r, i) { return { k: String(i + 1), label: r.text || r.id, answer: scored({ choice: 'bad', reason: r.id }, st) }; })
          .concat([{ k: 'Enter', label: '理由なしで記録', answer: scored({ choice: 'bad' }, st) }]);
      }
      return [{ k: 'A', label: '良い', primary: true, answer: scored({ choice: 'good' }, st), title: AUTO_TITLE.good },
        { k: 'X', label: '悪い', title: AUTO_TITLE.bad, answer: function (c, h, s, repaint) { s.step = 'why'; repaint(); return true; } },   // 悪い = 理由の段へ(答えはまだ)
        { k: 'S', label: '不明', answer: scored({ choice: 'unknown' }, st), title: AUTO_TITLE.unknown }].concat(scoreOpts(st));   // 不明 = 理由の段を通らず記録(check.js の Z・N・Enter・再生キーと重ならない)
    },
    keybar: function (card, st) {
      return st.step === 'why' ? [{ k: '1〜7', l: '理由' }, { k: 'Enter', l: '理由なしで記録' }] : [{ k: 'A', l: '良い' }, { k: 'X', l: '悪い' }, { k: 'S', l: '不明' }, { k: '1〜5', l: '面白さ' }];
    }
  });

  CheckCards.define('value', function () {
    var a = autoView(), c = cand(), cur = null;
    return {
      render: function (card, el, ctx) { cur = card && card.source === 'auto' ? a : c; cur.render(card, el, ctx); },
      keys: function (e, card) { return cur ? cur.keys(e, card) : null; },
      keybar: function (card) { return cur ? cur.keybar(card) : []; },
      unmount: function () { if (cur) cur.unmount(); cur = null; }
    };
  });
})();
