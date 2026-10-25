/* 確かめるのカード「どちらの読みが正しいか」(/check-cards/read.js。V2b)。比べる欄は ui-kit の .ui-pair(3 択と共用)・口は check.js の先頭。
   カード: options = [{id: "1", text}, {id: "2", text}]。read:fill は 1 = 後処理のあと・2 = 認識のまま / read:alt は 1 = 今の字幕・2 = その読みを入れた行。
   答え = {choice: "1" | "2"} か {choice: "other", text: 打った正しい文字}(1 / 2 / 3 で答える。3 = どちらも違う = 入力欄が開き、Enter で決める・Esc でやめる)/
   {choice: "shift"}(4 = 区間がずれている・ほかの発言が入っている。文字は変えず、行は時刻のカードに回る)/
   {choice: "unclear"}(5 = 聞き取れない。文字は変えず、行の音のメモ unclear = 時刻のカード・評価に回らない。10-25 確かめるの混ざりと BGM のルール)。
   流す区間は行の時刻にきっちり(頭の余白は前の行の終わりまで・末の余白 0 = 次の行の発言を入れない。src/app/check/sources.py の _tight)。
   **文字だけの判定**: 行を校正済みにしない・行の時刻の正解には使わない(反映は src/human/check/read.py)。 */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var LABELS = { fill: ['後処理のあと', '認識のまま'], alt: ['今の字幕', '2 つ目のエンジン'] };
  var MAX_TEXT = 1000;
  var UNCLEAR_TITLE = '音が小さい・BGM や別の声にかき消されて、どちらとも決められない(文字は変えず、行に「聞き取れない」のメモを付けます)';
  var SHIFT_TITLE = '流れた区間が行とずれている・次の発言が入っていて読みを決められない(文字は変えず、行の時刻のカードに回します)';

  function opts(card) {
    return (Array.isArray(card.options) ? card.options : []).filter(function (x) { return x && typeof x === 'object'; }).slice(0, 2);
  }
  /* 後処理(fill)のカードの note は直した部品の名前(by = name / llm / エンジンの名前)。画面には何をした行かの文で出す(編集の「別の読み」の札と同じ言い方) */
  var FILL_BY = { name: '行の頭の話者名(「名前:」)を外した行です', llm: 'LLM が名簿の呼び名に直した行です' };
  function noteText(card) {
    var n = String(card.note || '');
    if (card.source !== 'fill' || !n) return n;
    return FILL_BY[n] || '別のエンジン(' + n + ')の読みで埋めた行です';
  }
  function pair(card) {
    var o = opts(card), lb = LABELS[card.source] || ['', ''];
    if (o.length < 2) return '';
    return '<div class="ui-pair">' + o.map(function (x, i) {
      return '<div class="ui-pair-opt"><span class="ui-pair-lb">' + (i + 1) + ' ' + esc(x.label || lb[i]) + '</span><p>' + esc(x.text || '(文字なし)') + '</p></div>';
    }).join('') + '</div>';
  }

  CheckCards.define('read', function () {
    var cur = null, typing = false, root = null, ctxRef = null;

    function box() { return root && root.querySelector('[data-chk-type]'); }
    function field() { return root && root.querySelector('[data-chk-text]'); }
    function open() {
      var b = box(), f = field();
      if (!b || !f) return;
      typing = true;
      b.hidden = false;
      f.focus();
      f.select();
      if (ctxRef && ctxRef.refreshKeys) ctxRef.refreshKeys();
    }
    function close() {
      var b = box();
      typing = false;
      if (b) b.hidden = true;
      if (root && root.ownerDocument.activeElement && root.contains(root.ownerDocument.activeElement)) root.ownerDocument.activeElement.blur();
      if (ctxRef && ctxRef.refreshKeys) ctxRef.refreshKeys();
    }
    function typed() {
      var f = field(), t = f ? f.value.replace(/\s+/g, ' ').trim() : '';
      if (!t) { UIKit.toast('正しい文字を入れてください', { ms: 2500 }); return true; }   // 空では答えない(true = 使ったが答えではない)
      if (t.length > MAX_TEXT) { UIKit.toast('長すぎます(' + MAX_TEXT + ' 字まで)', { ms: 2500 }); return true; }
      return { choice: 'other', text: t };
    }

    return {
      render: function (card, el, ctx) {
        cur = card; root = el; ctxRef = ctx; typing = false;
        el.innerHTML = '<div class="chk-q">どちらの読みが正しい?</div>' +
          '<div class="chk-media"><div class="chk-stagebox" data-chk-media></div><div class="chk-info">' + pair(card) +
          (card.note ? '<p class="hint">' + esc(noteText(card)) + '</p>' : '') +
          '<p class="hint">文字だけの判定です(行を校正済みにしない・時刻の正解には使わない)。</p>' +
          '<p class="hint">この行の人の言葉だけを判定します(後ろの別の声・ゲームの声は読みに入れない)。</p></div></div>' +
          '<div class="chk-acts">' + CheckCards.btn('1 が正しい', '1', '') + CheckCards.btn('2 が正しい', '2', '') + CheckCards.btn('どちらも違う(打つ)', '3', '') +
          CheckCards.btn('区間がずれている・ほかの発言が入っている', '4', '').replace('<button ', '<button title="' + esc(SHIFT_TITLE) + '" ') +
          CheckCards.btn('聞き取れない', '5', '').replace('<button ', '<button title="' + esc(UNCLEAR_TITLE) + '" ') + '</div>' +
          '<div class="chk-type" data-chk-type hidden><label class="hint" for="chkReadText">正しい文字(行の全体を打ち直します)</label>' +
          '<div class="row"><input type="text" id="chkReadText" class="chk-text" data-chk-text maxlength="' + MAX_TEXT + '" value="' + esc(card.text || '') + '" autocomplete="off">' +
          CheckCards.btn('決める', 'Enter', 'primary') + '</div></div>';
        var m = card.media || {};
        if (m.url || m.youtube) ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: card.text, docId: card.target && card.target.docId });
      },
      typingKeys: true,
      keys: function (e) {
        if (!cur || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return null;
        var k = CheckCards.keyOf(e), inField = !!(e.target && e.target.matches && e.target.matches('input, textarea'));
        if (inField && !e.fromButton) {   // 入力欄の中: Enter で決める・Esc でやめる。ほかは打つ
          if (k === 'Enter') return typed();
          if (k === 'Escape') { close(); return true; }
          return null;
        }
        if (k === 'Enter' && typing) return typed();
        if (k === 'Escape' && typing) { close(); return true; }
        if (k === '1' || k === '2') { var o = opts(cur)[Number(k) - 1]; return o ? { choice: String(o.id || k) } : null; }
        if (k === '3') { open(); return true; }
        if (k === '4') return { choice: 'shift' };
        if (k === '5') return { choice: 'unclear' };
        return null;
      },
      keybar: function () {
        return typing ? [{ k: 'Enter', l: '決める' }, { k: 'Esc', l: 'やめる' }] : [{ k: '1', l: '1 が正しい' }, { k: '2', l: '2 が正しい' }, { k: '3', l: '打つ' }, { k: '4', l: '区間がずれている' }, { k: '5', l: '聞き取れない' }];
      },
      unmount: function () { cur = null; root = null; ctxRef = null; typing = false; }
    };
  });
})();
