/* 確かめるの「声の材料の確かめ」カード(/check-cards/material.js。11-02 保管庫 plan/話者の物差し-1101.md の 13 章「カード ア」・要件 4。
   口は check.js の先頭・出どころと答えの反映は src/app/check/voice_material.py)。
   1 枚 = 声の材料のかけら(ソロの判定を通った 48 秒ほど)の中の 6 秒ほど。[前後も流す] = card.near の窓(前後 5 秒ずつ)を流して止まる。
   答え(5 つ): この人だけ / この人ではない / 別の声が混ざる / 声がふだんと違う / 分からない = {answer: only | not | mixed | unusual | unknown}。
   押したあとにどうなるか(確か・配信ごと外す・かけらだけ外す・変えない)はボタンの title と下の 1 行に書く。キーは無い(Space の再生は殻の共通のキー) */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var TITLE = {
    only: 'このかけらを「確か」にします',
    not: 'この配信の声の材料を全部、登録簿から外します',
    mixed: '客・ゲームのキャラなど。この配信の声の材料を全部、登録簿から外します',
    unusual: 'BGM が大きい・叫び・ささやきなど。このかけらだけ外します',
    unknown: '何も変えません'
  };

  function hms(t) {
    t = Math.max(0, Math.floor(+t || 0));
    var h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
    return h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }
  var PART = { head: '頭', mid1: '中ほど 1 か所目', mid2: '中ほど 2 か所目', mid3: '中ほど 3 か所目', tail: '終わり', head4: '頭' };

  CheckCards.define('material', CheckCards.simple({
    question: function (card) { var m = card.media || {}; return (card.who || '') + ' の声の材料: この ' + Math.max(1, Math.round((+m.end || 0) - (+m.start || 0))) + ' 秒は ' + (card.who || 'この人') + ' だけの声ですか?'; },
    text: false,
    body: function (card) {
      var m = card.media || {}, at = card.at != null && isFinite(+card.at) ? +card.at + (+m.start || 0) : null;
      return '<p class="hint">' + esc(card.case && card.case.title || '') + (at != null ? '・' + esc(hms(at)) + '〜' + esc(hms(at + (+m.end || 0) - (+m.start || 0))) : '') +
        (PART[card.part] ? '(' + esc(PART[card.part]) + ')' : '') + '。この配信の材料は登録簿に' + (card.sure ? '入っています(このかけらは確か)' : '「仮」で入っています') + '。</p>' +
        '<p><button type="button" class="btn small" data-mat-near>前後も流す</button></p>';
    },
    after: function () { return '<p class="hint">外した材料は、次の見回りで登録簿から抜いて声をまとめ直します(Z で答えを取り消すと元に戻ります)。</p>'; },
    options: function (card) {
      var list = Array.isArray(card.answers) ? card.answers : [];
      return list.map(function (a, i) { return { k: 'M' + (i + 1), label: a[1], primary: a[0] === 'only', heavy: a[0] === 'not' || a[0] === 'mixed', answer: { answer: a[0] }, title: TITLE[a[0]] || '' }; });
    },
    mounted: function (card, handle) {
      var v = handle && handle.media ? handle.media() : null, box = v && v.closest ? v.closest('.chk-media') : null;
      var b = box ? box.querySelector('[data-mat-near]') : null, near = Array.isArray(card.near) ? card.near : null;   // 再生の隣の情報欄にある
      if (!v || !b || !near) return null;
      var stopAt = null;
      function tick() { if (stopAt != null && v.currentTime >= stopAt) { stopAt = null; v.pause(); } }
      function go() {
        stopAt = +near[1];
        try { v.currentTime = +near[0]; } catch (e) { /* 読み込みの途中 */ }
        var p = v.play();
        if (p && p.catch) p.catch(function () { /* 自動再生を断られた = Space で流す */ });
      }
      b.addEventListener('click', go);
      v.addEventListener('timeupdate', tick);
      return function () { b.removeEventListener('click', go); v.removeEventListener('timeupdate', tick); };
    }
  }));
})();
