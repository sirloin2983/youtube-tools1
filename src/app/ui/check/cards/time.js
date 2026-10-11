/* 確かめるのカード「行の時刻が合っているか」(/check-cards/time.js。RS8 V1 の V2d。作り方 docs/design/v1-check-build.md の 3-2・5 節・決定 3-41)。
   行の区間の前後 2〜3 秒を再生し、波形の上に行の頭と末の印を出す(単語の時刻の候補があれば点線の参考の印も = POST transcribe/api/retime の edges)。
   答え = {choice: 'ok' | 'head' | 'tail' | 'both', dStart, dEnd}(dStart / dEnd = ← → で動かした秒。前へは負)。
     Enter = ちょうどいい(動かしていなければ)/ H = 頭がずれている / E = 末がずれている / B = 両方 を選び、← → でその印を 1 コマ(1/30 秒)ずつ動かす(Shift で 5 コマ)、
     Enter で答える。**動かした量だけ行の時刻を実際に変える**(動かさなければ判定の記録だけ。反映は human/check/timerow.py)。
     H / E をもう 1 度押すと、その印の選びを外して量を 0 に戻す。選んでいない間の ← → は普通の再生の移動(殻の再生のキー)
   カードの文書 id は card.target.docId・行は card.target.row・区間は card.media = {start, end, pad}。波形の用意は player の opt.wave(transcribe/api/peaks) */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var FRAME = 1 / 30, SHIFT_FRAMES = 5, LIMIT = 2.5;   // 1 コマ・Shift のコマ数・動かせる上限(窓の pad と同じ。窓の外へは出さない)
  var NAMES = { ok: 'ちょうどいい', head: '頭がずれている', tail: '末がずれている', both: '両方ずれている' };

  function r3(x) { return Math.round(x * 1000) / 1000; }
  function signed(x) { return (x > 0 ? '+' : x < 0 ? '−' : '±') + Math.abs(x).toFixed(2) + ' 秒'; }

  CheckCards.define('time', function () {
    var st = null;   // {card, ctx, el, handle, head, tail, active, dS, dE, guides}

    function choice() { return st.head && st.tail ? 'both' : st.head ? 'head' : st.tail ? 'tail' : 'ok'; }
    function answer() { return { choice: choice(), dStart: st.head ? r3(st.dS) : 0, dEnd: st.tail ? r3(st.dE) : 0 }; }
    function paint() {
      var m = st.card.media || {}, a = +m.start || 0, b = +m.end || a;
      if (st.handle) st.handle.setMarks(a + (st.head ? st.dS : 0), b + (st.tail ? st.dE : 0));
      var c = choice(), box = st.el.querySelector('[data-chk-tstate]');
      if (box) {
        box.innerHTML = '<b>' + esc(NAMES[c]) + '</b>' + (c === 'ok' ? '' :
          ' <span class="pill">頭 ' + (st.head ? signed(st.dS) : '—') + '</span> <span class="pill">末 ' + (st.tail ? signed(st.dE) : '—') + '</span>' +
          '<span class="hint"> 動かす印: ' + (st.active === 'start' ? '頭' : '末') + '(← → で動かす。Enter で答える)</span>');
      }
      var g = st.el.querySelector('[data-chk-tguide]');
      if (g) g.textContent = st.guides ? '言葉の時刻(参考・点線): 頭 ' + st.guides[0].toFixed(2) + ' 秒 / 末 ' + st.guides[1].toFixed(2) + ' 秒' : '';
      st.el.querySelectorAll('[data-chk-k]').forEach(function (btn) {
        var k = btn.getAttribute('data-chk-k');
        btn.classList.toggle('on', (k === 'H' && st.head) || (k === 'E' && st.tail) || (k === 'B' && st.head && st.tail));
        btn.setAttribute('aria-pressed', btn.classList.contains('on') ? 'true' : 'false');
      });
    }
    function toggle(which) {
      var on = which === 'start' ? 'head' : 'tail';
      if (!st[on]) { st[on] = true; st.active = which; }
      else if (st.active !== which && st.head && st.tail) st.active = which;   // 両方のとき、もう 1 度押すと動かす印をそちらへ
      else { st[on] = false; if (which === 'start') st.dS = 0; else st.dE = 0; st.active = st.head ? 'start' : st.tail ? 'end' : 'start'; }
    }
    function nudge(dir, big) {
      var key = st.active === 'start' ? 'dS' : 'dE', v = st[key] + dir * FRAME * (big ? SHIFT_FRAMES : 1);
      st[key] = Math.max(-LIMIT, Math.min(LIMIT, v));
    }
    function loadGuides(card) {   // 単語の時刻の候補(読むだけ。無ければ印なし)
      var t = card.target || {};
      st.ctx.api('transcribe/api/retime', { body: { id: t.docId, rows: [t.row] } }).then(function (j) {
        if (!st || st.card !== card) return;
        var it = j && Array.isArray(j.items) ? j.items[0] : null;
        if (it && it.matched !== false && isFinite(+it.start) && isFinite(+it.end) && +it.end > +it.start) {
          st.guides = [+it.start, +it.end];
          if (st.handle && st.handle.setGuides) st.handle.setGuides(st.guides);
          paint();
        }
      }, function () { /* 単語の時刻が無い・読めない = 参考の印なしのまま */ });
    }

    return {
      render: function (card, el, ctx) {
        st = { card: card, ctx: ctx, el: el, handle: null, head: false, tail: false, active: 'start', dS: 0, dE: 0, guides: null };
        el.innerHTML = '<div class="chk-q">行の時刻が合っているか?</div>' +
          '<div class="chk-media"><div class="chk-stagebox" data-chk-media></div><div class="chk-info">' +
          '<p class="hint">波形の青い印が字幕の頭と末です。聞いて、字幕が出る・消えるタイミングが合っていればそのまま Enter。</p>' +
          '<p data-chk-tstate role="status"></p><p class="hint" data-chk-tguide></p>' +
          (card.note ? '<p class="hint">' + esc(card.note) + '</p>' : '') + '</div></div>' +
          '<div class="chk-acts">' + CheckCards.btn('ちょうどいい', 'Enter', 'primary') + CheckCards.btn('頭がずれている', 'H') +
          CheckCards.btn('末がずれている', 'E') + CheckCards.btn('両方', 'B') + '</div>';
        var m = card.media || {};
        if (m.url || m.youtube) {
          st.handle = ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: card.text, wave: true, docId: card.target && card.target.docId });
        }
        paint();
        loadGuides(card);
      },
      keys: function (e) {
        if (!st || e.ctrlKey || e.altKey || e.metaKey) return null;
        var k = CheckCards.keyOf(e);
        if (k === 'ArrowLeft' || k === 'ArrowRight') {
          if (!st.head && !st.tail) return null;   // 印を選んでいないときは普通の再生の移動
          nudge(k === 'ArrowLeft' ? -1 : 1, e.shiftKey);
          paint();
          return true;
        }
        if (e.shiftKey) return null;
        if (k === 'Enter') return answer();
        if (k === 'H') toggle('start');
        else if (k === 'E') toggle('end');
        else if (k === 'B') { st.head = st.tail = true; st.active = 'start'; }
        else return null;
        paint();
        st.ctx.refreshKeys();
        return true;
      },
      keybar: function () {
        var o = [{ k: 'Enter', l: st && (st.head || st.tail) ? 'この時刻で答える' : 'ちょうどいい' }, { k: 'H', l: '頭がずれている' }, { k: 'E', l: '末がずれている' }, { k: 'B', l: '両方' }];
        if (st && (st.head || st.tail)) o.push({ k: '← →', l: '印を動かす(Shift で大きく)' });
        return o;
      },
      unmount: function () { st = null; }
    };
  });
})();
