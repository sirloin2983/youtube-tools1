/* 確かめるのカード「価値」(/check-cards/value.js)。口は check.js の先頭。
   source auto(自動でできた切り抜き・2-8) = 送った後の品質の確認: [良い](A) / [悪い](X) / [不明](S・どちらとも言えない = 理由なしで記録)。悪いを押したら理由の札を 1 つ選べる(数字 1〜7・任意。Enter = 理由なしで記録)。
     記録だけ(src/human/check/value.py)。送るかには効かせない = [送る]・[要らない] は無い。すぐ記録(1 枚遅れなし)。Z で記録を取り消す。
   source cand(候補のまま) = 採用 / 不採用(殻の決まった形 CheckCards.simple・今のまま。1 枚遅れで確定)。
   カード(src/app/check/sources.py): auto = options ["good","bad","unknown"]・reasons [{id, text}] / cand = options ["adopt","reject"]。答え = {choice} / 悪いの理由 {choice:"bad", reason: id} */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var LABEL = { adopt: '採用', reject: '不採用' };
  var TITLE = { adopt: '70 点以上として数え、書き出して案件の切り抜きに足します', reject: '70 点未満として数えます' };
  var AUTO_TITLE = { good: '出来が良い(記録だけ。送るかには効きません)', bad: '出来が悪い(理由の札を選べます・記録だけ)', unknown: 'どちらとも言えない(記録だけ)' };
  var WHY = '悪い理由を 1 つ選べます(数字)。選ばずに記録するなら Enter';

  function candBody(card) {
    var s = typeof card.score === 'number' && isFinite(card.score) ? '<p class="hint">機械の点数: ' + Math.round(card.score) + '</p>' : '';
    return (card.text ? '<p>' + esc(card.text) + '</p>' : '') + s;
  }
  var cand = CheckCards.simple({
    question: function () { return '切り抜く価値があるか(70 点以上か)?'; },
    body: candBody,
    options: function (card) {
      var o = Array.isArray(card.options) && card.options.length === 2 ? card.options : ['adopt', 'reject'];
      return [{ k: 'A', label: LABEL[o[0]] || String(o[0]), primary: true, answer: { choice: o[0] }, title: TITLE[o[0]] || '' },
        { k: 'X', label: LABEL[o[1]] || String(o[1]), answer: { choice: o[1] }, title: TITLE[o[1]] || '' }];
    }
  });

  /* 自動でできた切り抜き: 2 段(良い / 悪い → 悪いのとき理由の札)。段は view の中だけで持つ(カードが変わると作り直す) */
  function autoView() {
    var card = null, ctx = null, box = null, step = 'pick';
    function reasons() { return Array.isArray(card && card.reasons) ? card.reasons.filter(function (r) { return r && typeof r.id === 'string' && r.id; }).slice(0, 7) : []; }
    function paint() {
      var acts = box && box.querySelector('.chk-acts');
      if (!acts) return;
      if (step === 'pick') {
        acts.innerHTML = btn('良い', 'A', 'primary', AUTO_TITLE.good) + btn('悪い', 'X', '', AUTO_TITLE.bad) + btn('不明', 'S', '', AUTO_TITLE.unknown);
      } else {
        acts.innerHTML = '<p class="hint">' + esc(WHY) + '</p>' + reasons().map(function (r, i) {
          return btn(r.text || r.id, String(i + 1), '', '');
        }).join('') + btn('理由なしで記録', 'Enter', '', '');
      }
      if (ctx && typeof ctx.refreshKeys === 'function') ctx.refreshKeys();
    }
    function btn(label, key, cls, title) {
      return CheckCards.btn(label, key, cls).replace('<button ', '<button title="' + esc(title) + '" ');
    }
    return {
      render: function (c, el, cx) {
        card = c; ctx = cx; box = el; step = 'pick';
        var m = c.media || {};
        var s = typeof c.score === 'number' && isFinite(c.score) ? '<p class="hint">機械の点数: ' + Math.round(c.score) + '</p>' : '';
        el.innerHTML = '<div class="chk-q">送ったあとの出来は良いか?</div>' +
          '<div class="chk-media"><div class="chk-stagebox" data-chk-media></div><div class="chk-info">' +
          (c.text ? '<p>' + esc(c.text) + '</p>' : '') + s + (c.note ? '<p class="hint">' + esc(c.note) + '</p>' : '') +
          '<p class="hint">送ったかどうかは見ずに、出来だけを見てください(記録だけ・送るかには効きません)</p>' +
          '</div></div><div class="chk-acts"></div>';
        if (m.url || m.youtube) ctx.player(el.querySelector('[data-chk-media]'), c.media, { text: c.text, wave: false, docId: c.target && c.target.docId });
        paint();
      },
      keys: function (e) {
        if (!card || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return null;
        var k = CheckCards.keyOf(e);
        if (step === 'pick') {
          if (k === 'A') return { choice: 'good' };
          if (k === 'S') return { choice: 'unknown' };   // 不明 = 理由の段を通らず記録(キー S。check.js の Z・N・Enter・再生キーと重ならない)
          if (k === 'X') { step = 'why'; paint(); return true; }   // 悪い = 理由の段へ(答えはまだ)
          return null;
        }
        if (k === 'Enter') return { choice: 'bad' };
        var r = /^[1-7]$/.test(k) ? reasons()[parseInt(k, 10) - 1] : null;
        return r ? { choice: 'bad', reason: r.id } : null;
      },
      keybar: function () {
        return step === 'pick' ? [{ k: 'A', l: '良い' }, { k: 'X', l: '悪い' }, { k: 'S', l: '不明' }] : [{ k: '1〜7', l: '理由' }, { k: 'Enter', l: '理由なしで記録' }];
      },
      unmount: function () { card = null; ctx = null; box = null; }
    };
  }

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
