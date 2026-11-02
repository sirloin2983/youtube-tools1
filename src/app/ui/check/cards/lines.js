/* 確かめるの「行ごとの話者」カード(/check-cards/lines.js。11-02 ユーザー「誰の声カードでそれぞれの行に話者をあてる形にしてほしい・ついでに行の中身も調整する」。
   口は check.js の先頭・出どころと答えの検査は src/app/check/voice_lines.py)。
   1 枚 = 声の材料の配信の短いかけら(48 秒ほど)。中の行を並べ、行ごとに: 再生のボタン(その行だけ流す)・話者の欄・文字の欄。
   話者の欄: 初めは道具の予想の 1 位(予想の無い行は「選んでください」)。候補は声を覚えた全員(card.people)・ほかの人(card.otherPerson)・声なし。
   直した所(予想と違う話者・元と違う文字)は橙の枠で示す。今流れている行は色を付ける。
   答え: [決める] = {rows: [{id, speaker? | none?, text?}](変えた行だけ)}。何も変えなければ {} = 全部の行が予想どおり・文字どおり。
   予想の無い行の話者を選ぶまでは押せない。キーは無い(Space の再生は殻の共通のキー)。行が多くても [決める] が遠のかないよう .chk-dock に置く */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var NONE = '__none__';

  function fmt(t) {
    t = Math.max(0, +t || 0);
    var m = Math.floor(t / 60), s = t - m * 60;
    return m + ':' + (s < 10 ? '0' : '') + s.toFixed(1);
  }
  function hms(t) {
    t = Math.max(0, Math.floor(+t || 0));
    var h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
    return h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }
  function score(x) { return typeof x === 'number' && isFinite(x) ? x.toFixed(2) : ''; }

  CheckCards.define('lines', function () {
    var cur = null;
    function options(r, names, other) {
      return (r.guess ? '' : '<option value="">選んでください</option>') +
        names.map(function (n) { return '<option value="' + esc(n) + '">' + esc(n) + '</option>'; }).join('') +
        '<option value="' + esc(other) + '">' + esc(other) + '</option><option value="' + NONE + '">声なし</option>';
    }
    function rowHtml(r, i, names, other) {
      var g = r.guess ? '予想 ' + r.guess + (score(r.score) ? ' ' + score(r.score) : '') + (r.second && r.second.name ? '・2 位 ' + r.second.name + (score(r.second.score) ? ' ' + score(r.second.score) : '') : '') : '予想なし';
      return '<li class="chk-ln-row" data-ln-row="' + i + '"><button type="button" class="btn small chk-ln-play" data-ln-play="' + i + '" aria-label="この行だけ流す" title="この行だけ流す">' + UIKit.icon('play') + '</button>' +
        '<span class="chk-ln-t">' + esc(fmt(r.start)) + '〜' + esc(fmt(r.end)) + '</span>' +
        '<select class="input chk-ln-spk" data-ln-spk aria-label="話者">' + options(r, names, other) + '</select>' +
        '<span class="chk-ln-guess" title="' + esc(g) + '">' + esc(g) + '</span>' +
        '<input class="input chk-ln-text" data-ln-text maxlength="200" aria-label="行の文字" value="' + esc(r.text) + '"></li>';
    }
    function state() {   // -> {ans, spk: 話者を変えた行の数, txt: 文字を直した行の数, missing: 話者を選んでいない行の数}
      var out = [], spk = 0, txt = 0, missing = 0;
      cur.rows.forEach(function (r, i) {
        var li = cur.el.querySelector('[data-ln-row="' + i + '"]');
        if (!li) return;
        var sel = li.querySelector('[data-ln-spk]'), inp = li.querySelector('[data-ln-text]'), one = { id: r.id };
        var v = sel.value, t = inp.value.trim(), sc = false, tc = false;
        if (!v) missing++;
        else if (v === NONE) { one.none = true; sc = true; }
        else if (v !== r.guess) { one.speaker = v; sc = true; }
        if (t !== String(r.text || '').trim()) { one.text = t; tc = true; }
        sel.classList.toggle('chk-ln-chg', sc);
        inp.classList.toggle('chk-ln-chg', tc);
        if (sc) spk++;
        if (tc) txt++;
        if (sc || tc) out.push(one);
      });
      return { ans: out.length ? { rows: out } : {}, spk: spk, txt: txt, missing: missing };
    }
    function refresh() {
      if (!cur) return;
      var s = state(), b = cur.el.querySelector('[data-chk-k="Enter"]');
      if (!b) return;
      var parts = [];
      if (s.spk) parts.push('話者 ' + s.spk + ' 行');
      if (s.txt) parts.push('文字 ' + s.txt + ' 行');
      b.textContent = parts.length ? '決める(' + parts.join('・') + 'を直した)' : '決める(全部この通り)';
      b.disabled = s.missing > 0;
      b.title = s.missing ? '予想の無い行(' + s.missing + ' 行)の話者を選んでから押せます' : '';
    }
    function video() { return cur && cur.handle && cur.handle.media ? cur.handle.media() : null; }
    function playRow(i) {
      var r = cur.rows[i], v = video();
      if (!r || !v) return;
      cur.stopAt = r.end;
      try { v.currentTime = r.start; } catch (e) { /* 読み込みの途中 */ }
      var p = v.play();
      if (p && p.catch) p.catch(function () { /* 自動再生を断られた = Space で流す */ });
    }
    function onTime() {
      var v = video();
      if (!v || !cur) return;
      var t = v.currentTime;
      if (cur.stopAt != null && t >= cur.stopAt) { cur.stopAt = null; v.pause(); }
      var at = -1;
      cur.rows.forEach(function (r, i) { if (at < 0 && t >= r.start && t < r.end) at = i; });
      if (at === cur.now) return;
      var old = cur.el.querySelector('.chk-ln-now');
      if (old) old.classList.remove('chk-ln-now');
      var li = at >= 0 ? cur.el.querySelector('[data-ln-row="' + at + '"]') : null;
      if (li) li.classList.add('chk-ln-now');
      cur.now = at;
    }
    return {
      render: function (card, el, ctx) {
        var rows = (Array.isArray(card.rows) ? card.rows : []).filter(function (r) { return r && typeof r.id === 'string'; });
        var other = typeof card.otherPerson === 'string' && card.otherPerson ? card.otherPerson : 'ほかの人';
        var names = (Array.isArray(card.people) ? card.people : []).filter(function (n) { return typeof n === 'string' && n && n !== other; });
        var sec = card.media && +card.media.end || 0, at = +card.at;
        el.innerHTML = '<div class="chk-q">この ' + Math.round(sec || 0) + ' 秒の行ごとに、話している人を選ぶ(文字の誤りも直せます)</div>' +
          '<p class="hint">' + (card.who ? '配信者 ' + esc(card.who) + (isFinite(at) && card.at != null ? '・' + esc(hms(at)) + '〜' + esc(hms(at + sec)) : '') + '。' : '') +
          '初めは道具の予想の 1 位を入れてあります。違う行だけ直して [決める]。</p>' +
          '<div class="chk-stagebox" data-chk-media></div>' +
          '<ul class="chk-ln-list" data-ln-list>' + rows.map(function (r, i) { return rowHtml(r, i, names, other); }).join('') + '</ul>' +
          '<p class="hint">話者の欄: 声を覚えた全員・' + esc(other) + '(覚えた人のだれでもない声)・声なし(人の声が無い)。再生のボタン = その行だけ流す。直した所は橙の枠で示します。</p>' +
          '<div class="chk-dock"><div class="chk-acts">' + CheckCards.btn('決める(全部この通り)', 'Enter', 'primary') + '</div></div>';
        cur = { card: card, el: el, rows: rows, handle: null, stopAt: null, now: -1 };
        rows.forEach(function (r, i) {   // 初めの選び = 予想の 1 位(候補に無ければ選んでいない)
          var sel = el.querySelector('[data-ln-row="' + i + '"] [data-ln-spk]');
          if (sel && r.guess) sel.value = r.guess;
        });
        cur.handle = ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: '' });
        var v = video();
        if (v) { cur.video = v; v.addEventListener('timeupdate', onTime); }
        // el は殻の入れ物(カードをまたいで同じ)なので、外すときに聞き手も外す
        cur.on = {
          change: refresh,
          input: refresh,
          click: function (e) {
            var b = e.target.closest && e.target.closest('[data-ln-play]');
            if (b) playRow(+b.getAttribute('data-ln-play'));
          }
        };
        Object.keys(cur.on).forEach(function (t) { el.addEventListener(t, cur.on[t]); });
        refresh();
      },
      keys: function (e) {
        if (!cur || !e.fromButton) return null;
        if (CheckCards.keyOf(e) !== 'Enter') return null;
        var s = state();
        if (s.missing) { UIKit.toast('予想の無い行の話者を選んでください', { kind: 'err' }); return true; }
        return s.ans;
      },
      unmount: function () {
        if (cur && cur.on) Object.keys(cur.on).forEach(function (t) { cur.el.removeEventListener(t, cur.on[t]); });
        if (cur && cur.video) cur.video.removeEventListener('timeupdate', onTime);
        cur = null;
      }
    };
  });
})();
