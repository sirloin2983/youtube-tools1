/* 確かめるの「行ごとの話者と区切り」カード(/check-cards/lines.js。11-02 ユーザー「誰の声カードでそれぞれの行に話者をあてる形にしてほしい・ついでに行の中身も調整する」・
   11-02 午後に決め直した形 = 保管庫 plan/話者の物差し-1101.md の 13 章「カード イ」。口は check.js の先頭・出どころと答えの検査は src/app/check/voice_lines.py)。
   1 枚 = かけらの一切れ(6 秒ほど。行の時刻はかけらの頭からの秒 = 再生の窓 media.start〜end の外の時刻もそのまま)。上に [前後も流す](±3 秒)。
   行ごと: 再生(その行)・±(前後 2 秒も)・時刻・話者の欄・言葉。
   話者の欄 = 打つと候補が出る欄(datalist。候補 = card.people = 出る人・予想の名前・声を覚えた全員・名簿の全員 + ほかの人・声なし・2 人同時・分からない。名簿に無い名前も打てる)。
     初めは道具の予想の 1 位(予想の無い行は空 = 選ぶまで [決める] を押せない)。2 人同時 = 下に 2 人の欄が出る。
   区切りの直し: 言葉の間を押す = そこで行を 2 つに分ける・←前へ/→次へ = 頭・終わりの言葉を隣の行へ移す・つなぐ = 分けた行を前の行へ戻す。
     言葉 = 行の words(Haas の言葉ごとの時刻)。無い行は 1 字ずつで、区切りを変えると「時刻は仮」(時刻はサーバーが言葉から決める・人には選ばせない)。
   文字: ✎ を押したときだけ欄が開く(直す行は区切りの直しを止める)。行が無い声の印: 下のチェック(時刻は選ばせない)。
   答え: [決める] = {rows: [{w: [頭, 末), speaker | both | none | unknown, text?}], voiceNoRow?}(何も変えなければ {})。直した所は橙の枠。キーは無い。
   [決める] は行が多くても遠のかないよう .chk-dock に置く */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var OTHER = 'ほかの人', NONE = '声なし', BOTH = '2 人同時', UNKNOWN = '分からない';
  var SPECIAL = [OTHER, NONE, BOTH, UNKNOWN];
  var NAME_MAX = 30, NEAR = 3, ROW_NEAR = 2;
  var FROM = { friend: '友人の依頼', material: '声の材料', research: '研究のコラボ' };

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

    /* ---- 形: 言葉の通し(flat)・元の区切り(cuts0)・今の行(segs = {a, b, spk, b1, b2, text}) ---- */
    function build(rows) {
      var flat = [], cuts0 = [];
      rows.forEach(function (r, i) {
        cuts0.push(flat.length);
        var ws = Array.isArray(r.words) && r.words.length ? r.words : [[r.text || '', r.start, r.end]];
        ws.forEach(function (w) { flat.push({ w: String(w[0] || ''), s: +w[1], e: +w[2], row: i }); });
      });
      return { flat: flat, cuts0: cuts0 };
    }
    function ends0(i) { return i + 1 < cur.cuts0.length ? cur.cuts0[i + 1] : cur.flat.length; }
    function rowsOf(sg) { var o = []; for (var k = sg.a; k < sg.b; k++) if (o.indexOf(cur.flat[k].row) < 0) o.push(cur.flat[k].row); return o; }
    function mainRow(sg) {   // 言葉の多い元の行(サーバーと同じ)
      var n = {}, best = cur.flat[sg.a].row;
      for (var k = sg.a; k < sg.b; k++) { var r = cur.flat[k].row; n[r] = (n[r] || 0) + 1; if (n[r] > (n[best] || 0)) best = r; }
      return best;
    }
    function whole(sg) { var h = cur.flat[sg.a].row; return rowsOf(sg).length === 1 && sg.a === cur.cuts0[h] && sg.b === ends0(h); }
    function times(sg) {   // サーバー(voice_lines._apply_lines)と同じ決め方
      var h = cur.flat[sg.a].row, t = cur.flat[sg.b - 1].row;
      var a = sg.a === cur.cuts0[h] ? cur.rows[h].start : cur.flat[sg.a].s, b = sg.b === ends0(t) ? cur.rows[t].end : cur.flat[sg.b - 1].e;
      var guess = !whole(sg) && rowsOf(sg).some(function (i) { return cur.rows[i].timed === false; });
      return { a: a, b: Math.max(a, b), guess: guess };
    }
    function text0(sg) {
      if (whole(sg)) return String(cur.rows[cur.flat[sg.a].row].text || '');
      var s = '';
      for (var k = sg.a; k < sg.b; k++) s += cur.flat[k].w;
      return s;
    }
    function guessOf(sg) { return cur.rows[mainRow(sg)].guess || ''; }
    function changedCuts() {
      var now = cur.segs.map(function (s) { return s.a; });
      return now.length !== cur.cuts0.length || now.some(function (a, i) { return a !== cur.cuts0[i]; });
    }

    /* ---- 描く ---- */
    function spkInput(cls, val, attr, label) {
      return '<input class="input chk-ln-spk' + cls + '" list="chk-ln-names" maxlength="' + NAME_MAX + '" ' + attr + ' aria-label="' + esc(label) + '" value="' + esc(val || '') + '" autocomplete="off">';
    }
    function segHtml(sg, i) {
      var tm = times(sg), main = cur.rows[mainRow(sg)], g = guessOf(sg), split = !whole(sg);
      var hint = g ? '予想 ' + g + (score(main.score) ? ' ' + score(main.score) : '') +
        (main.second && main.second.name ? '・2 位 ' + main.second.name + (score(main.second.score) ? ' ' + score(main.second.score) : '') : '') : '予想なし';
      var h = '<li class="chk-ln-row' + (split ? ' chk-ln-split' : '') + '" data-ln-row="' + i + '">';
      h += '<span class="chk-ln-plays"><button type="button" class="btn small chk-ln-play" data-ln-play="' + i + '" aria-label="この行だけ流す" title="この行だけ流す">' + UIKit.icon('play') + '</button>' +
        '<button type="button" class="btn small" data-ln-near="' + i + '" title="この行と前後 ' + ROW_NEAR + ' 秒を流す">±</button></span>';
      h += '<span class="chk-ln-t">' + esc(fmt(tm.a)) + '〜' + esc(fmt(tm.b)) + (tm.guess ? '<small class="chk-ln-tag">時刻は仮</small>' : split ? '<small class="chk-ln-tag">分けた行</small>' : '') + '</span>';
      h += '<span class="chk-ln-who">' + spkInput(sg.spk !== g ? ' chk-ln-chg' : '', sg.spk, 'data-ln-spk="' + i + '"', '話者');
      if (sg.spk === BOTH) h += '<span class="chk-ln-both">' + spkInput(' chk-ln-chg', sg.b1, 'data-ln-b1="' + i + '"', '同時に話す 1 人目') + spkInput(' chk-ln-chg', sg.b2, 'data-ln-b2="' + i + '"', '同時に話す 2 人目') + '</span>';
      h += '<span class="chk-ln-guess" title="' + esc(hint) + '">' + esc(hint) + '</span></span>';
      h += '<span class="chk-ln-words">';
      if (i > 0 && sg.text == null) h += '<button type="button" class="chk-ln-mv" data-ln-prev="' + i + '" title="頭の言葉を前の行へ移す">←前へ</button>';
      if (sg.text != null) {
        h += '<input class="input chk-ln-text' + (sg.text.trim() !== text0(sg).trim() ? ' chk-ln-chg' : '') + '" data-ln-text="' + i + '" maxlength="200" aria-label="行の文字" value="' + esc(sg.text) + '">';
      } else {
        for (var k = sg.a; k < sg.b; k++) {
          if (k > sg.a) h += '<button type="button" class="chk-ln-gap" data-ln-cut="' + k + '" aria-label="ここで行を分ける" title="ここで行を分ける"></button>';
          h += '<span class="chk-ln-w">' + esc(cur.flat[k].w || '(文字なし)') + '</span>';
        }
      }
      if (i < cur.segs.length - 1 && sg.text == null) h += '<button type="button" class="chk-ln-mv" data-ln-next="' + i + '" title="終わりの言葉を次の行へ移す">→次へ</button>';
      if (i > 0 && cur.flat[sg.a].row === cur.flat[cur.segs[i - 1].b - 1].row) h += '<button type="button" class="chk-ln-mv chk-ln-join" data-ln-join="' + i + '" title="前の行とつなぐ">つなぐ</button>';
      if (sg.text == null) h += '<button type="button" class="chk-ln-ed" data-ln-edit="' + i + '" title="文字を直す">✎ 文字</button>';
      return h + '</span></li>';
    }
    function draw() {
      var list = cur.el.querySelector('[data-ln-list]');
      if (list) list.innerHTML = cur.segs.map(segHtml).join('');
      cur.now = -1;
      refresh();
    }

    /* ---- 答え ---- */
    function state() {
      var out = [], spk = 0, txt = 0, missing = 0, cuts = changedCuts();
      cur.segs.forEach(function (sg) {
        var one = { w: [sg.a, sg.b] }, v = (sg.spk || '').trim();
        if (!v) missing++;
        else if (v === NONE) one.none = true;
        else if (v === UNKNOWN) one.unknown = true;
        else if (v === BOTH) {
          var x = (sg.b1 || '').trim(), y = (sg.b2 || '').trim();
          if (!x || !y || x === y) missing++;
          else one.both = [x, y];
        } else one.speaker = v;
        if (v !== guessOf(sg)) spk++;
        if (sg.text != null && sg.text.trim() !== text0(sg).trim()) { one.text = sg.text.trim(); txt++; }
        out.push(one);
      });
      var box = cur.el.querySelector('[data-ln-norow]');
      var ans = spk || txt || cuts ? { rows: out } : {};
      if (box && box.checked) ans.voiceNoRow = true;
      return { ans: ans, spk: spk, txt: txt, cuts: cuts, missing: missing };
    }
    function refresh() {
      if (!cur) return;
      var s = state(), b = cur.el.querySelector('[data-chk-k="Enter"]');
      if (!b) return;
      var parts = [];
      if (s.spk) parts.push('話者 ' + s.spk + ' 行');
      if (s.cuts) parts.push('区切り');
      if (s.txt) parts.push('文字 ' + s.txt + ' 行');
      b.textContent = parts.length ? '決める(' + parts.join('・') + 'を直した)' : '決める(全部この通り)';
      b.disabled = s.missing > 0;
      b.title = s.missing ? '話者が空の行・2 人同時の 2 人が欠けた行(' + s.missing + ' 行)を埋めてから押せます' : '';
    }

    /* ---- 区切りの操作 ---- */
    function cut(k) {
      for (var i = 0; i < cur.segs.length; i++) {
        var sg = cur.segs[i];
        if (k > sg.a && k < sg.b) {
          cur.segs.splice(i + 1, 0, { a: k, b: sg.b, spk: sg.spk, b1: sg.b1, b2: sg.b2, text: null });
          sg.b = k;
          return draw();
        }
      }
    }
    function move(i, dir) {
      var sg = cur.segs[i], o = cur.segs[i + dir];
      if (!sg || !o) return;
      if (dir < 0) { o.b++; sg.a++; } else { o.a--; sg.b--; }
      if (sg.a >= sg.b) cur.segs.splice(i, 1);
      draw();
    }
    function join(i) {
      var sg = cur.segs[i], p = cur.segs[i - 1];
      if (!sg || !p) return;
      p.b = sg.b;
      cur.segs.splice(i, 1);
      draw();
    }

    /* ---- 再生 ---- */
    function video() { return cur && cur.handle && cur.handle.media ? cur.handle.media() : null; }
    function play(a, b) {
      var v = video();
      if (!v) return;
      cur.stopAt = b;
      try { v.currentTime = Math.max(0, a); } catch (e) { /* 読み込みの途中 */ }
      var p = v.play();
      if (p && p.catch) p.catch(function () { /* 自動再生を断られた = Space で流す */ });
    }
    function clipEnd() { return +cur.card.clipSec || ((cur.card.media && +cur.card.media.end) || 0) + NEAR; }
    function onTime() {
      var v = video();
      if (!v || !cur) return;
      var t = v.currentTime;
      if (cur.stopAt != null && t >= cur.stopAt) { cur.stopAt = null; v.pause(); }
      var at = -1;
      cur.segs.forEach(function (sg, i) { var tm = times(sg); if (at < 0 && t >= tm.a && t < tm.b) at = i; });
      if (at === cur.now) return;
      var old = cur.el.querySelector('.chk-ln-now');
      if (old) old.classList.remove('chk-ln-now');
      var li = at >= 0 ? cur.el.querySelector('[data-ln-row="' + at + '"]') : null;
      if (li) li.classList.add('chk-ln-now');
      cur.now = at;
    }
    function num(e, name) { var b = e.target.closest && e.target.closest('[' + name + ']'); return b ? +b.getAttribute(name) : null; }

    return {
      render: function (card, el, ctx) {
        var rows = (Array.isArray(card.rows) ? card.rows : []).filter(function (r) { return r && typeof r.id === 'string'; });
        var names = (Array.isArray(card.people) ? card.people : []).filter(function (n) { return typeof n === 'string' && n && SPECIAL.indexOf(n) < 0; });
        var m0 = card.media && +card.media.start || 0, m1 = card.media && +card.media.end || 0, at = +card.at + m0, sec = Math.max(0, m1 - m0);
        var where = [card.who ? '配信者 ' + card.who : '', isFinite(at) && card.at != null ? hms(at) + '〜' + hms(at + sec) : '', FROM[card.from] || '', card.scene || ''].filter(Boolean).join('・');
        cur = { card: card, el: el, rows: rows, handle: null, stopAt: null, now: -1 };
        var b = build(rows);
        cur.flat = b.flat;
        cur.cuts0 = b.cuts0;
        cur.segs = rows.map(function (r, i) { return { a: b.cuts0[i], b: i + 1 < b.cuts0.length ? b.cuts0[i + 1] : b.flat.length, spk: r.guess || '', b1: '', b2: '', text: null }; });
        el.innerHTML = '<div class="chk-q">この ' + Math.max(1, Math.round(sec)) + ' 秒の行ごとに、話している人を選ぶ(区切りと文字も直せます)</div>' +
          '<p class="hint">' + esc(card.case && card.case.title || '') + (where ? '(' + esc(where) + ')' : '') + '。初めは道具の予想の 1 位を入れてあります。違う所だけ直して [決める]。</p>' +
          '<div class="chk-ln-top"><div class="chk-stagebox" data-chk-media></div><button type="button" class="btn small" data-ln-around>前後も流す(±' + NEAR + ' 秒)</button></div>' +
          '<datalist id="chk-ln-names">' + names.concat(SPECIAL).map(function (n) { return '<option value="' + esc(n) + '"></option>'; }).join('') + '</datalist>' +
          '<ul class="chk-ln-list" data-ln-list></ul>' +
          '<p class="hint">話者の欄: 打つと候補が出ます(名簿の全員・名簿に無い名前もそのまま)。ほかに ' + OTHER + '(名簿のだれでもない声)・' + NONE + '・' + BOTH + '(その 2 人も選ぶ)・' + UNKNOWN + '。<br>' +
          '言葉の間を押す = 行を 2 つに分ける・←前へ/→次へ = 頭・終わりの言葉を隣の行へ移す(時刻は言葉の時刻から決まります。言葉の時刻が無い行は「時刻は仮」)。</p>' +
          '<div class="chk-dock"><label class="chk-ln-norow"><input type="checkbox" data-ln-norow> 行が無い声がある(相づちなど)</label><div class="chk-acts">' + CheckCards.btn('決める(全部この通り)', 'Enter', 'primary') + '</div></div>';
        draw();
        cur.handle = ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: '' });
        var v = video();
        if (v) { cur.video = v; v.addEventListener('timeupdate', onTime); }
        // el は殻の入れ物(カードをまたいで同じ)なので、外すときに聞き手も外す
        cur.on = {
          change: refresh,
          input: function (e) {
            var t = e.target, i;
            if ((i = t.getAttribute('data-ln-spk')) != null) {
              var sg = cur.segs[+i], was = sg.spk;
              sg.spk = t.value;
              if ((was === BOTH) !== (t.value === BOTH)) {   // 2 人同時の欄を出す・畳む
                draw();
                var f = cur.el.querySelector(t.value === BOTH ? '[data-ln-b1="' + i + '"]' : '[data-ln-spk="' + i + '"]');
                if (f) f.focus();
                return;
              }
              t.classList.toggle('chk-ln-chg', t.value !== guessOf(sg));
            } else if ((i = t.getAttribute('data-ln-b1')) != null) cur.segs[+i].b1 = t.value;
            else if ((i = t.getAttribute('data-ln-b2')) != null) cur.segs[+i].b2 = t.value;
            else if ((i = t.getAttribute('data-ln-text')) != null) {
              cur.segs[+i].text = t.value;
              t.classList.toggle('chk-ln-chg', t.value.trim() !== text0(cur.segs[+i]).trim());
            }
            refresh();
          },
          click: function (e) {
            var i;
            if ((i = num(e, 'data-ln-play')) != null) { var tm = times(cur.segs[i]); return play(tm.a, tm.b); }
            if ((i = num(e, 'data-ln-near')) != null) { var tn = times(cur.segs[i]); return play(tn.a - ROW_NEAR, Math.min(clipEnd(), tn.b + ROW_NEAR)); }
            if (e.target.closest && e.target.closest('[data-ln-around]')) return play(m0 - NEAR, Math.min(clipEnd(), m1 + NEAR));
            if ((i = num(e, 'data-ln-cut')) != null) return cut(i);
            if ((i = num(e, 'data-ln-prev')) != null) return move(i, -1);
            if ((i = num(e, 'data-ln-next')) != null) return move(i, 1);
            if ((i = num(e, 'data-ln-join')) != null) return join(i);
            if ((i = num(e, 'data-ln-edit')) != null) {
              cur.segs[i].text = text0(cur.segs[i]);
              draw();
              var f = cur.el.querySelector('[data-ln-text="' + i + '"]');
              if (f) f.focus();
            }
          }
        };
        Object.keys(cur.on).forEach(function (t) { el.addEventListener(t, cur.on[t]); });
        refresh();
      },
      keys: function (e) {
        if (!cur || !e.fromButton) return null;
        if (CheckCards.keyOf(e) !== 'Enter') return null;
        var s = state();
        if (s.missing) { UIKit.toast('話者が空の行・2 人同時の 2 人が欠けた行を埋めてください', { kind: 'err' }); return true; }
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
