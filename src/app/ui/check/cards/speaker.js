/* 確かめるの「話者」カード(/check-cards/speaker.js。11-02 ユーザー: 誰の声(voice)とコラボの話者(speaker)を 1 つにまとめた。口は check.js の先頭)。
   流す音: ソロの配信の文字起こしの 1 行(voice:solo・diar・measure)/ コラボの配信の 10 秒の区間(speaker:collab)。画面の上では区別しない。
   答え方: 話している人を全部選んでから [決める](何人でも)。予想の人を初めから選んでおくことはしない・予想どおりのボタンも無い。
   選べる物(段 3): その配信に出るはずの人の名前のボタン(card.cast。ソロ = 配信者・コラボ = 出る人全員)・人と同じく選べる札
     「誰か分からないメンバー」「メンバー以外の人」「ゲームの声」・[ほかのメンバーを足す](押すと開く: 上に探す欄 = ひらがな・ローマ字・呼び名で絞れる、
     下に期ごとの名前の札 = メンバーの色を小さく添える。押した人は名前のボタンの最後に「足した」として加わり選ばれた状態になる。何人でも続けて足せる。[閉じる] で畳む)。
     探し方の表は GET api/check/members(src/app/check/members.py)。見つからない名前は「〇〇 を足す」で名簿の外の名前のまま足せる。
   印(段 3): BGM が大きい・声色が違う(真似・笑い・歌)。
   答え(段 2): [決める] = {names: [選んだ名前…], bgm?, alt?}(コラボの「メンバー以外の人」は card.otherPerson の名前で送る = 前の答えと同じ)/
     [声なし] = {choice: "other"}(名前を選んでいる間は押せない)。声の材料にするか(測る専用の札 measureOnly・1 人だけ・印なし)はサーバーが決める
     (human/check/voice・app/check/speaker_solo)。キーは無い(入力欄の Enter = 絞った 1 人を足す・Esc = 閉じる) */
(function () {
  'use strict';
  var esc = UIKit.esc;
  var UNKNOWN = '誰か分からないメンバー', OUTSIDER = 'メンバー以外の人', GAME = 'ゲームの声';
  var SPECIAL_TITLE = {};
  SPECIAL_TITLE[UNKNOWN] = 'ホロライブのメンバーの声だが、誰か分からない';
  SPECIAL_TITLE[OUTSIDER] = 'メンバーではない人の声(ゲスト・家族・通話の相手など)';
  SPECIAL_TITLE[GAME] = 'ゲームの登場人物・動画の声など(人の配信者の声ではない)';
  var NOTE = { below_match: '覚えた声との似かたが弱い話者です', margin: '覚えた声の 2 人が近く、どちらか決めきれなかった話者です',
    solo: 'ソロ配信と見た配信の行です(声を覚える材料を集めています)', measure: 'ソロの配信の行です(覚えた声で人を当てられるかを測ります)' };
  var NAME_MAX = 30;
  var index = null, loading = null;   // 探し方の表(1 回だけ読む)

  function list(a) { return (Array.isArray(a) ? a : []).filter(function (x) { return typeof x === 'string' && x; }); }
  function castOf(card) {   // 出るはずの人
    if (Array.isArray(card.cast)) return list(card.cast);
    if (card.kind === 'speaker') return list(card.people);
    return (Array.isArray(card.options) ? card.options : []).filter(function (o) { return o && o.name && o.id !== 'other' && o.id !== 'mixed'; }).map(function (o) { return String(o.name); });
  }
  function fold(s) {   // 探す言葉をそろえる: 全角半角・大文字小文字・カタカナ → ひらがな・空白と中黒を外す
    return String(s || '').normalize('NFKC').toLowerCase().replace(/[ァ-ヶ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0x60); }).replace(/[\s・･]/g, '');
  }
  function hits(q) {
    var f = fold(q), out = [];
    if (!index || !f) return out;
    Object.keys(index.members).forEach(function (n) {
      var m = index.members[n] || {};
      var words = [n, m.yomi, m.en].concat(Array.isArray(m.calls) ? m.calls : []);
      if (words.some(function (w) { return w && fold(w).indexOf(f) >= 0; })) out.push(n);
    });
    return out;
  }

  function create() {
    var cur = null, box = null, rctx = null;
    function all() {   // 名前のボタンの並び: 出るはずの人 → 足した人
      return cur.cast.concat(cur.extra.filter(function (n) { return cur.cast.indexOf(n) < 0; }));
    }
    function nameBtn(n, i, added) {
      return '<button type="button" class="btn lg chk-spk-name chk-mark" aria-pressed="' + (cur.sel.indexOf(n) >= 0) + '" data-chk-k="N' + i + '"' +
        (SPECIAL_TITLE[n] ? ' title="' + esc(SPECIAL_TITLE[n]) + '"' : '') + '>' + esc(n) + (added ? '<span class="chk-spk-added">足した</span>' : '') + '</button>';
    }
    function panel() {
      if (!cur.open) return '';
      var q = cur.q || '', groups = index ? index.groups : [], found = q ? hits(q) : null;
      var chip = function (n) {
        var m = (index && index.members[n]) || {}, on = cur.sel.indexOf(n) >= 0;
        return '<button type="button" class="chk-spk-chip" aria-pressed="' + on + '" data-chk-add="' + esc(n) + '">' +
          (m.hex ? '<span class="chk-spk-dot" data-hex="' + esc(m.hex) + '"></span>' : '') + esc(n) + '</button>';
      };
      var body = !index ? '<p class="hint">メンバーの表を読み込んでいます…</p>' : found ? (found.length ? '<div class="chk-spk-chips">' + found.map(chip).join('') + '</div>' :
        '<p class="hint">見つかりません。</p>') + (q.trim() && q.trim().length <= NAME_MAX && found.indexOf(q.trim()) < 0 ?
        '<button type="button" class="btn small" data-chk-add="' + esc(q.trim()) + '">「' + esc(q.trim()) + '」を足す(名簿に無い名前)</button>' : '') :
        groups.map(function (g) {
          return '<div class="chk-spk-group"><span class="chk-spk-glabel">' + esc(g.label) + '</span><div class="chk-spk-chips">' + list(g.names).map(chip).join('') + '</div></div>';
        }).join('');
      return '<div class="chk-spk-panel" data-chk-panel><div class="row"><input type="search" class="chk-text" data-chk-find placeholder="ひらがな・ローマ字・呼び名で探す" value="' + esc(q) + '" autocomplete="off" aria-label="メンバーを探す">' +
        '<button type="button" class="btn" data-chk-k="CLOSE">閉じる</button></div><div data-chk-found>' + body + '</div></div>';
    }
    function rows() {
      var names = all(), specials = [UNKNOWN, OUTSIDER, GAME];
      var picked = cur.sel.length ? '決める(' + cur.sel.join('・') + ')' : '決める';
      return '<div class="chk-marks chk-spk-names" role="group" aria-label="話している人(何人でも)">' +
        names.map(function (n, i) { return nameBtn(n, i, cur.cast.indexOf(n) < 0); }).join('') +
        specials.map(function (n, i) { return nameBtn(n, 'S' + i, false); }).join('') +
        (cur.open ? '' : '<button type="button" class="btn" data-chk-k="OPEN">ほかのメンバーを足す</button>') + '</div>' + panel() +
        '<div class="chk-marks" role="group" aria-label="印(選ぶだけ)">' +
        CheckCards.mark('BGM が大きい', 'BGM', cur.bgm, 'ゲーム音・BGM が大きい(声を覚える材料にしません)') +
        CheckCards.mark('声色が違う(真似・笑い・歌)', 'ALT', cur.alt, 'いつもと違う声色(声を覚える材料にしません)') + '</div>' +
        '<div class="chk-acts"><button type="button" class="btn lg primary" data-chk-k="Enter"' + (cur.sel.length ? '' : ' disabled title="話している人を選んでから押せます"') + '>' + esc(picked) + '</button>' +
        CheckCards.btn('声なし', 'NONE', '', '人の声が無い(ゲームの音・BGM だけ)').replace('<button ', '<button ' + (cur.sel.length ? 'disabled title="名前を選んでいる間は押せません" ' : '')) + '</div>';
    }
    function paintDots() {   // 色は style 属性に書けない(CSP)ので描いたあとに入れる
      if (!box) return;
      Array.prototype.forEach.call(box.querySelectorAll('.chk-spk-dot[data-hex]'), function (d) { d.style.background = d.getAttribute('data-hex'); });
    }
    function repaint(keepFind) {
      var a = box && box.querySelector('.chk-rows');
      if (!a) return;
      var f = box.querySelector('[data-chk-find]'), focused = keepFind && f && box.ownerDocument.activeElement === f, pos = f ? f.selectionStart : 0;
      a.innerHTML = rows();
      paintDots();
      var nf = box.querySelector('[data-chk-find]');
      if (nf && (focused || cur.focusFind)) { nf.focus(); try { nf.setSelectionRange(pos, pos); } catch (e) { /* type=search で選べないことがある */ } }
      cur.focusFind = false;
    }
    function refound() {   // 探す欄を打つたびに結果だけ描き直す(入力欄は作り直さない)
      var el = box && box.querySelector('[data-chk-found]');
      if (!el) return;
      var tmp = box.ownerDocument.createElement('div');
      tmp.innerHTML = panel();
      var fresh = tmp.querySelector('[data-chk-found]');
      if (fresh) el.innerHTML = fresh.innerHTML;
      paintDots();
    }
    function toggle(n) {
      var i = cur.sel.indexOf(n);
      if (i >= 0) cur.sel.splice(i, 1); else cur.sel.push(n);
    }
    function add(n) {
      n = String(n || '').replace(/\s+/g, ' ').trim();
      if (!n || n.length > NAME_MAX) return;
      if (all().indexOf(n) < 0 && [UNKNOWN, OUTSIDER, GAME].indexOf(n) < 0) cur.extra.push(n);
      if (cur.sel.indexOf(n) < 0) cur.sel.push(n);
    }
    function loadIndex() {
      if (index || loading) return;
      loading = rctx.api('api/check/members', { method: 'GET', timeout: 15000 }).then(function (j) {
        index = { groups: Array.isArray(j && j.groups) ? j.groups : [], members: (j && j.members && typeof j.members === 'object') ? j.members : {} };
        if (cur && cur.open) repaint(true);
      }, function () { loading = null; index = { groups: [], members: {} }; if (cur && cur.open) repaint(true); });
    }
    function answer() {
      var other = typeof cur.card.otherPerson === 'string' && cur.card.otherPerson ? cur.card.otherPerson : OUTSIDER;
      var names = cur.sel.map(function (n) { return n === OUTSIDER && cur.card.kind === 'speaker' ? other : n; });
      var a = { names: names };
      if (cur.bgm) a.bgm = true;
      if (cur.alt) a.alt = true;
      return a;
    }
    function onClick(e) {
      var b = e.target.closest && e.target.closest('[data-chk-add]');
      if (!cur || !b) return;
      add(b.getAttribute('data-chk-add'));
      cur.focusFind = true;
      repaint(false);
    }
    function onInput(e) {
      if (!cur || !e.target.matches || !e.target.matches('[data-chk-find]')) return;
      cur.q = e.target.value;
      refound();
    }
    return {
      typingKeys: true,
      render: function (card, el, ctx) {
        cur = { card: card, cast: castOf(card), sel: [], extra: [], bgm: false, alt: false, open: false, q: '' };
        box = el; rctx = ctx;
        var note = NOTE[card.note] || '';
        el.innerHTML = '<div class="chk-q">' + (card.kind === 'speaker' ? 'この 10 秒で話している人は誰?(全員)' : 'この行で話している人は誰?(全員)') + '</div>' +
          '<div class="chk-media"><div class="chk-stagebox" data-chk-media></div><div class="chk-info">' +
          (cur.cast.length ? '<p class="chk-spk-cast">この配信に出る人: <b>' + esc(cur.cast.join('・')) + '</b></p>' : '') +
          '<p class="hint">話している人を全部選んで [決める](何人でも・順番は聞きません)。いないときは [ほかのメンバーを足す]。人の声が無ければ [声なし]。</p>' +
          (note ? '<p class="hint">' + esc(note) + '</p>' : '') + '</div></div><div class="chk-rows">' + rows() + '</div>';
        el.addEventListener('click', onClick);
        el.addEventListener('input', onInput);
        var m = card.media || {};
        if (m.url || m.youtube) ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: card.kind === 'speaker' ? '' : card.text, docId: card.target && card.target.docId });
      },
      keys: function (e) {
        if (!cur) return null;
        var k = CheckCards.keyOf(e);
        if (!e.fromButton) {   // 探す欄の中だけ: Enter = 絞った 1 人を足す・Esc = 閉じる
          if (!e.target || !e.target.matches || !e.target.matches('[data-chk-find]') || e.ctrlKey || e.altKey || e.metaKey) return null;
          if (k === 'Escape') { cur.open = false; repaint(false); return true; }
          if (k === 'Enter') {
            var h = hits(cur.q);
            if (h.length === 1) { add(h[0]); cur.q = ''; cur.focusFind = true; repaint(false); }
            return true;
          }
          return null;
        }
        if (k === 'OPEN') { cur.open = true; cur.focusFind = true; loadIndex(); repaint(false); return true; }
        if (k === 'CLOSE') { cur.open = false; repaint(false); return true; }
        if (k === 'BGM') { cur.bgm = !cur.bgm; repaint(true); return true; }
        if (k === 'ALT') { cur.alt = !cur.alt; repaint(true); return true; }
        if (k === 'Enter') return cur.sel.length ? answer() : true;
        if (k === 'NONE') return cur.sel.length ? true : { choice: 'other' };
        var m = /^N(S?)(\d+)$/.exec(k);
        if (m) {
          var n = m[1] ? [UNKNOWN, OUTSIDER, GAME][+m[2]] : all()[+m[2]];
          if (n) { toggle(n); repaint(true); }
          return true;
        }
        return null;
      },
      unmount: function () {
        if (box) { box.removeEventListener('click', onClick); box.removeEventListener('input', onInput); }
        cur = null; box = null; rctx = null;
      }
    };
  }

  CheckCards.define('voice', create);
  CheckCards.define('speaker', create);
})();
