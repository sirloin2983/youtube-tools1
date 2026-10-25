/* 確かめるのカード「区間を聞いて直す(評価用)」(/check-cards/section.js。C-EVAL (2)。口は check.js の先頭・出どころは src/app/check/eval_sources.py・
   反映は src/human/check/section.py)。評価のレーン(/check?lane=eval)だけに出る。
   評価用の動画を頭から 20〜40 秒の区間に分け、区間を聞いて **持ち主の行**(行の中心がこの区間にある行)を 合っている / 直す / 消す、無い声は 足す。
   答えた持ち主の行は正解(校正済み)になる。機械の予想・覚えた声の候補は出さない(正解が機械寄りにならない)。話者の選択肢はメンバーのフォルダの名前だけ(打ってもよい)。
   隣の区間の行は灰色で見せるだけ(ここでは直さない = 全部の行がちょうど 1 回ずつ答えられる)。「声が無いかも」= 話者の判別の声の区間と 3 割未満しか重ならない行。
   カード: target = {docId, from, to, rows, updatedAt, last, index}・rows = [{id, start, end, text, speaker(名前), owned, novoice, proofed, tags}]・options = [名前…]・progress。
   答え = {rows: [{id, text?, speaker?, game?, tags?, drop?}](変えた行だけ), add: [{start, end, text, speaker?, game?, tags?}]}。何も変えなければ {} = 合っている。
   話者の選択肢の「ゲームの音」= game: true(組み込みの話者「ゲーム音声など」)。行ごとのメモ 重なり・BGM 大・聞き取れない = tags(overlap・bgm・unclear。
   変えた行だけ 3 つの値を送る)。10-25 確かめるの混ざりと BGM のルール
   キー: Enter = 答える(入力中は Ctrl+Enter)・A = 行を足す(今の再生の位置から 2 秒) */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var TYPE = '__type__', GAME = '__game__';
  var MEMOS = [{ t: 'overlap', l: '重なり', title: '別の人の声が同時に入っている行' }, { t: 'bgm', l: 'BGM 大', title: 'ゲーム音・BGM が大きい行' },
    { t: 'unclear', l: '聞き取れない', title: '聞き取れない所がある行(評価から外します)' }];

  function fmt(t) {
    t = Math.max(0, +t || 0);
    var m = Math.floor(t / 60), s = t - m * 60;
    return m + ':' + (s < 10 ? '0' : '') + s.toFixed(1);
  }
  function speakerSelect(names, cur) {
    return '<select class="input chk-sec-spk" data-sec-spk aria-label="話者">' +
      '<option value="">' + esc(cur ? 'そのまま(' + cur + ')' : 'そのまま(話者なし)') + '</option>' +
      names.map(function (n) { return '<option value="' + esc(n) + '">' + esc(n) + '</option>'; }).join('') +
      '<option value="' + GAME + '">ゲームの音</option>' +
      '<option value="' + TYPE + '">名前を打つ…</option></select>' +
      '<input class="input chk-sec-name" data-sec-name maxlength="30" placeholder="名前" aria-label="話者の名前" hidden>';
  }
  function memoHtml(tags) {
    tags = Array.isArray(tags) ? tags : [];
    return '<span class="chk-sec-memos">' + MEMOS.map(function (m) {
      return '<label class="chk-sec-memo" title="' + esc(m.title) + '"><input type="checkbox" data-sec-memo="' + m.t + '"' + (tags.indexOf(m.t) >= 0 ? ' checked' : '') + '> ' + esc(m.l) + '</label>';
    }).join('') + '</span>';
  }
  function memosOf(li) {
    return MEMOS.filter(function (m) { var c = li.querySelector('[data-sec-memo="' + m.t + '"]'); return c && c.checked; }).map(function (m) { return m.t; });
  }
  function rowHtml(r, names) {
    if (!r.owned) {
      return '<li class="chk-sec-row chk-sec-other" title="隣の区間の行です(ここでは直しません)"><span class="chk-sec-t">' + esc(fmt(r.start)) + '</span>' +
        '<span class="chk-sec-txt">' + esc(r.text) + '</span></li>';
    }
    return '<li class="chk-sec-row" data-sec-row="' + esc(r.id) + '"><span class="chk-sec-t">' + esc(fmt(r.start)) + '〜' + esc(fmt(r.end)) + '</span>' +
      (r.novoice ? '<span class="pill warn" title="話者の判別の声の区間とほとんど重なりません。声が無ければ [消す]">声が無いかも</span>' : '') +
      speakerSelect(names, r.speaker) +
      '<input class="input chk-sec-text" data-sec-text maxlength="2000" aria-label="行の文字" value="' + esc(r.text) + '">' + memoHtml(r.tags) +
      '<label class="chk-sec-drop"><input type="checkbox" data-sec-drop> 消す</label></li>';
  }
  function addHtml(a, b, names) {
    return '<li class="chk-sec-row chk-sec-add" data-sec-add><span class="chk-sec-t">足す</span>' +
      '<input class="input chk-sec-num" data-sec-a type="number" step="0.1" min="0" value="' + a.toFixed(1) + '" aria-label="始まり(秒)">〜' +
      '<input class="input chk-sec-num" data-sec-b type="number" step="0.1" min="0" value="' + b.toFixed(1) + '" aria-label="終わり(秒)">' +
      speakerSelect(names, '') + '<input class="input chk-sec-text" data-sec-text maxlength="2000" placeholder="聞こえた言葉" aria-label="足す行の文字">' + memoHtml([]) +
      '<button type="button" class="btn ghost small" data-sec-unadd>やめる</button></li>';
  }

  CheckCards.define('section', function () {
    var cur = null;
    function nameOf(li) {
      var sel = li.querySelector('[data-sec-spk]'), inp = li.querySelector('[data-sec-name]');
      if (!sel || !sel.value || sel.value === GAME) return '';
      return sel.value === TYPE ? (inp.value || '').trim() : sel.value;
    }
    function putWho(li, one) {
      var sel = li.querySelector('[data-sec-spk]'), nm = nameOf(li);
      if (sel && sel.value === GAME) one.game = true;
      else if (nm) one.speaker = nm;
    }
    function build() {
      if (!cur) return null;
      var rows = [], add = [], byId = {};
      (cur.card.rows || []).forEach(function (r) { byId[r.id] = r; });
      Array.prototype.forEach.call(cur.el.querySelectorAll('[data-sec-row]'), function (li) {
        var r = byId[li.getAttribute('data-sec-row')];
        if (!r) return;
        if (li.querySelector('[data-sec-drop]').checked) { rows.push({ id: r.id, drop: true }); return; }
        var one = { id: r.id }, t = li.querySelector('[data-sec-text]').value.trim(), mm = memosOf(li);
        if (t !== String(r.text || '').trim()) one.text = t;
        putWho(li, one);
        if (mm.join(',') !== (Array.isArray(r.tags) ? r.tags : []).join(',')) one.tags = mm;
        if (Object.keys(one).length > 1) rows.push(one);
      });
      var bad = '';
      Array.prototype.forEach.call(cur.el.querySelectorAll('[data-sec-add]'), function (li) {
        var t = li.querySelector('[data-sec-text]').value.trim(), a = +li.querySelector('[data-sec-a]').value, b = +li.querySelector('[data-sec-b]').value;
        if (!t) return;
        if (!(isFinite(a) && isFinite(b) && b > a)) { bad = '足す行の時刻は 始まり < 終わり にしてください'; return; }
        var one = { start: a, end: b, text: t }, mm = memosOf(li);
        putWho(li, one);
        if (mm.length) one.tags = mm;
        add.push(one);
      });
      if (bad) { UIKit.toast(bad, { kind: 'err' }); return null; }
      var out = {};
      if (rows.length) out.rows = rows;
      if (add.length) out.add = add;
      return out;
    }
    function refreshBtn() {
      if (!cur) return;
      var a = build(), b = cur.el.querySelector('[data-chk-k="Enter"]');
      if (b) b.firstChild.nodeValue = a && (a.rows || a.add) ? '直して答える ' : '合っている ';
    }
    function addRow() {
      var t = cur.card.target || {}, v = cur.handle && cur.handle.media && cur.handle.media();
      var at = v && isFinite(v.currentTime) ? v.currentTime : +t.from || 0;
      at = Math.min(Math.max(at, +t.from || 0), Math.max(+t.from || 0, (+t.to || 0) - 0.5));
      var ul = cur.el.querySelector('[data-sec-list]');
      ul.insertAdjacentHTML('beforeend', addHtml(at, Math.min(at + 2, +t.to || at + 2), cur.card.options || []));
      var inp = ul.lastElementChild.querySelector('[data-sec-text]');
      if (inp) inp.focus();
    }
    return {
      typingKeys: true,
      render: function (card, el, ctx) {
        var names = (Array.isArray(card.options) ? card.options : []).filter(function (n) { return typeof n === 'string' && n; });
        var rows = (Array.isArray(card.rows) ? card.rows : []).filter(function (r) { return r && typeof r.id === 'string'; });
        var p = card.progress || {};
        el.innerHTML = '<div class="chk-q">区間を聞いて、行を直す・足す</div>' +
          '<p class="hint">' + esc(card.note || '') + (p.totalSec ? '(' + esc(fmt(p.fromSec)) + ' / ' + esc(fmt(p.totalSec)) + ')' : '') + '</p>' +
          '<div class="chk-stagebox" data-chk-media></div>' +
          '<ul class="chk-sec-list" data-sec-list>' + (rows.length ? rows.map(function (r) { return rowHtml(r, names); }).join('') :
            '<li class="hint">この区間に行はありません(声があれば [行を足す])</li>') + '</ul>' +
          '<p class="hint">2 人が同時に話していたら、もう 1 人を同じ時刻で [行を足す]。重なり・BGM が大きい・聞き取れない行は、行のメモに印を付けます。</p>' +
          '<div class="chk-acts">' + CheckCards.btn('合っている', 'Enter', 'primary') +
          '<button type="button" class="btn" data-sec-addrow>行を足す <kbd class="ui-kbd">A</kbd></button></div>';
        cur = { card: card, el: el, handle: null };
        cur.handle = ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: '' });
        el.addEventListener('change', function (e) {
          var sel = e.target.closest && e.target.closest('[data-sec-spk]');
          if (sel) { var inp = sel.parentNode.querySelector('[data-sec-name]'); inp.hidden = sel.value !== TYPE; if (!inp.hidden) inp.focus(); }
          refreshBtn();
        });
        el.addEventListener('input', refreshBtn);
        el.addEventListener('click', function (e) {
          if (e.target.closest && e.target.closest('[data-sec-addrow]')) { addRow(); refreshBtn(); }
          var un = e.target.closest && e.target.closest('[data-sec-unadd]');
          if (un) { un.closest('li').remove(); refreshBtn(); }
        });
      },
      keys: function (e) {
        if (!cur) return null;
        var k = CheckCards.keyOf(e), typing = !e.fromButton && UIKit.keys.isTyping(e.target);
        if (k === 'Enter' && (!typing || e.ctrlKey) && !e.altKey && !e.metaKey) return build() || true;
        if (typing || e.ctrlKey || e.altKey || e.metaKey) return null;
        if (k === 'A') { addRow(); refreshBtn(); return true; }
        return null;
      },
      keybar: function () { return [{ k: 'Enter', l: '答える' }, { k: 'A', l: '行を足す' }]; },
      unmount: function () { cur = null; }
    };
  });
})();
