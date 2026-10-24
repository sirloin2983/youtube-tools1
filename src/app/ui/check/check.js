/* 確かめる(/check = 入口の直下の 1 枚。部品は src/app/ui/check/。RS8 V1 = 殻。作り方 notes:docs/design/v1-check-build.md・何を作るか notes:docs/design/briefs/rs8-cases/DESIGN_BRIEF.md 2-3・3)。
   案件をまたいだ軽い確認の待ち行列を 1 枚ずつカードで出し、答えたらすぐ次へ。Z で 1 つ前に戻す・[飛ばす](N)はその日は後ろへ・10 件ごとに小さなまとめ。
   URL: /check?c=<案件 id>(その案件だけ)&kind=value|read|voice|time|speech(この種類だけ)&back=cases(終わったら案件へ戻るボタン)。URL を開いただけでは何も書かない。
   レーン(C-EVAL): 普段(既定)/ 評価(?lane=eval = 評価用の動画の区間カード section だけ。頭に評価用の一括の 始める / 止める / 進み具合・定点の「あと何分」・
   未確認の本数。transcribe/api/eval-batch・transcribe/api/drill/status を直に読む)。評価のカードは普段に出ない・その逆も。
   読む口・書く口(入口。入口 src/app/check/ が数えて並べ、③ src/human/check/apply.py が実物に反映する。V0):
     GET  api/check/next?c=&kind=&n=<枚数。0 = 数だけ>&skip=<id,…>  → {cards: [カード], counts: {today, perKind, failed}, goal, goals: {種類: {label, left, unit, opens, reached}}, total}
     POST api/check/answer {card, answer, ms, skip(待っている id), page} → {ok, answer(答えの id = Z で戻すときに使う), applied, held, flushed, next}
     POST api/check/answer {undo: <答えの id>}                       → {ok, answer, card, reverted}
     POST api/check/skip   {card, page}                               → {ok, flushed}・POST api/check/flush {page} → {ok, flushed}(タブを閉じた・隠したとき)
     page = この画面の印(開くたびに作る)。保留(1 枚遅れの [送る])の確定は、この画面の次の答え・飛ばす・タブを閉じる / 隠すときに、この画面の分だけ
     (別の窓へ移っただけ = blur では確定しない。決定 Q12 (a))
   カード = {id, kind, source, case: {id, title}, target, media: {url | youtube, start, end, pad}, text, guess, options, score, note}。
   殻が持つ物: 上の帯(今日 n 件・この確認で決まる物)・カードの枠・keydown 1 本・Z・[飛ばす]・10 件のまとめ・先読み(10 枚を持ち、3 枚を切ったら補充)・
   空の状態・失敗・UIKit.life(見えなくなったら再生を止める)・カードの再生部品の後始末。CSP(script-src 'self')の下で動く: インラインの script・on〇〇= は書かない。

   ---- カードの登録の口(V2 の 4 本 = cards/value.js・read.js・voice.js・time.js が同じ形で作る)----
   CheckCards.define(kind, create)   create() が新しい描き手を 1 つ返す(カードを出すたびに作り直す)
   描き手 = {
     render(card, el, ctx)   el = カードの中身の入れ物(中の要素は el.querySelector で引く。document.getElementById は使わない)
     keys(e, card) -> 答え | true | null   殻の keydown から 1 回だけ。答え(object)を返すと殻が送ってすぐ次のカードへ。true = 使ったが答えではない
                       (印を動かすなど。殻が preventDefault)。null = 使わない(殻が再生のキー UIKit.keys.playback に回す)。
                       el の中の <button data-chk-k="A"> を押したときも、同じ keys が {key: 'A', fromButton: true, target: ボタン} で呼ばれる(ボタンとキーは 1 本の道)
     keybar(card) -> [{k, l}]   下の帯の分(殻が [N 飛ばす][Space 再生][R もう一度聞く][Z 戻す] を後ろに足す。N・Z・R は殻が先に取る = カードで使わない)。変わったら ctx.refreshKeys()
     unmount()        (任意)カードを離れる。ctx.player で作った再生部品は殻が止めて外す
     leave(reason)    (任意)画面を離れた(UIKit.life。'blur' = 隣の窓へ / 'hidden'・'pagehide')
     typingKeys       (任意)true なら入力中(UIKit.keys.isTyping)のキーも keys に渡す(「どちらも違う(打つ)」の欄)
   }
   ctx = { player(el, media, opt) -> CheckPlayer の手(check-player.js。カードを離れると殻が止めて外す), answer(答え)(keys 以外の道で答える),
           refreshKeys(), api(path, opt)(入口の相対パス。UIKit.http の包み), case(案件 {id, title}), kindLabel }
   小道具: CheckCards.btn(文字, キー, class) = 答えのボタンの HTML / CheckCards.keyOf(e) = 'A'・'1'・'Enter'(大文字にそろえる)/
           CheckCards.simple({question, body, options, media, wave}) = 問い + 再生 + 答えのボタン の決まった形の描き手を作る(空のカード 4 本が使う) */
(function () {
  'use strict';

  var esc = UIKit.esc;
  var $ = function (s) { return document.querySelector(s); };

  /* ---- カードの登録の口(カードのファイルはこのあとに読む。DOMContentLoaded までに全部そろう)---- */
  var defs = {};
  function keyOf(e) {
    var k = e && e.key;
    if (!k) return '';
    if (k === ' ' || k === 'Spacebar') return 'Space';
    return k.length === 1 ? k.toUpperCase() : k;
  }
  function answerBtn(label, key, cls) {
    return '<button type="button" class="btn lg ' + esc(cls || '') + '" data-chk-k="' + esc(key) + '">' + esc(label) +
      ' <kbd class="ui-kbd">' + esc(key) + '</kbd></button>';
  }
  /* 決まった形の描き手: 問い・再生(card.media)・字幕 1 行・答えのボタン。options(card, st) = [{k, label, answer, primary, title}]。
     answer が関数なら押したときに answer(card, 再生の手, st, repaint) を呼ぶ(null を返すと答えない = 再生が終わるまで Enter を効かせない、など)。
     段のあるカードは st(カードごとの入れ物)に段を持ち、answer の中で変えて repaint() すると、ボタン(options と hint)だけ描き直す。
     spec: question(card)・body(card)(情報欄)・after(card)(備考のあとの情報)・hint(card, st)(ボタンの前の 1 行)・keybar(card, st)(下の帯。省略 = options の先頭 5 つ)・
     media: false = 再生を出さない・text: false = 再生に字幕を渡さない・wave・mounted(card, 再生の手) = 再生ができたとき呼ぶ(外すときの関数を返す) */
  function simple(spec) {
    return function () {
      var cur = null, handle = null, unbind = null, box = null, rctx = null;
      function acts() {
        cur.opts = (spec.options && spec.options(cur.card, cur.st)) || [];
        return (spec.hint ? spec.hint(cur.card, cur.st) : '') + cur.opts.map(function (o) {
          return answerBtn(o.label, o.k, o.primary ? 'primary' : '').replace('<button ', '<button title="' + esc(o.title || '') + '" ');
        }).join('');
      }
      function repaint() {
        var a = box && box.querySelector('.chk-acts');
        if (a) a.innerHTML = acts();
        if (rctx && typeof rctx.refreshKeys === 'function') rctx.refreshKeys();
      }
      return {
        render: function (card, el, ctx) {
          cur = { card: card, opts: [], st: {} }; box = el; rctx = ctx;
          var q = spec.question ? spec.question(card) : '';
          el.innerHTML = '<div class="chk-q">' + esc(q) + '</div>' +
            '<div class="chk-media"><div class="chk-stagebox" data-chk-media></div><div class="chk-info">' +
            (spec.body ? spec.body(card) : '') + (card.note ? '<p class="hint">' + esc(card.note) + '</p>' : '') + (spec.after ? spec.after(card) : '') + '</div></div>' +
            '<div class="chk-acts">' + acts() + '</div>';
          var m = card.media || {};
          if (spec.media !== false && (m.url || m.youtube)) {
            handle = ctx.player(el.querySelector('[data-chk-media]'), card.media, { text: spec.text === false ? '' : card.text, wave: !!spec.wave, docId: card.target && card.target.docId });
            if (spec.mounted) unbind = spec.mounted(card, handle) || null;
          }
        },
        keys: function (e) {
          if (!cur || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return null;
          var k = keyOf(e);
          for (var i = 0; i < cur.opts.length; i++) {
            var o = cur.opts[i];
            if (keyOf({ key: o.k }) !== k) continue;
            var a = typeof o.answer === 'function' ? o.answer(cur.card, handle, cur.st, repaint) : o.answer;
            return a || true;
          }
          return null;
        },
        keybar: function () {
          if (!cur) return [];
          return spec.keybar ? spec.keybar(cur.card, cur.st) : cur.opts.slice(0, 5).map(function (o) { return { k: o.k, l: o.label }; });
        },
        unmount: function () { if (unbind) unbind(); cur = null; handle = null; unbind = null; box = null; rctx = null; }
      };
    };
  }
  window.CheckCards = {
    define: function (kind, create) { if (typeof create === 'function' && /^[a-z]{1,20}$/.test(kind)) defs[kind] = create; },
    has: function (kind) { return Object.prototype.hasOwnProperty.call(defs, kind); },
    create: function (kind) { return this.has(kind) ? defs[kind]() : null; },
    btn: answerBtn, keyOf: keyOf, simple: simple
  };

  var KIND_TEXT = { value: '切り抜く価値があるか', read: 'どちらの読みが正しいか', voice: 'これは誰の声?', time: '行の時刻が合っているか',
    speech: 'この行は声ですか?', cut: '機械のカットの確認', section: '区間を聞いて直す(評価用)' };
  var SOURCE_TEXT = { auto: '自動で採った', cand: '候補のまま', fill: '後処理', alt: '別のエンジン', diar: '話者の判別', solo: 'ソロ配信', row: '文字が決まった行', eval: '評価用の動画', edge: '切れ目', gap: '消した所', whole: '仕上がり' };
  var KEEP = 10, LOW = 3, SUM_EVERY = 10;
  var ID_RE = /^[\w:.#|\/-]{1,200}$/;
  var LOAD_TEXT = { offline: 'ホームにつながりませんでした(start.bat の黒い画面が閉じていないか確かめてください)' };
  var PAGE = 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);   // この画面の印(秘密ではない。保留の確定を画面ごとに分けるだけ)
  var GONE_UNDO = { cannot_undo: 1, changed: 1, undone: 1, not_found: 1 };   // Z を断られた答えは履歴から外す(次の Z は 1 つ前へ)

  var S = {
    want: { c: '', kind: '', back: '', lane: '' },
    queue: [], seen: {}, cur: null, view: null, players: [], shownAt: 0,
    hist: [],            // 答えたカード [{card, p: 答えの id の Promise}](Z で新しい方から戻す)
    today: 0, answered: 0, goal: null, goals: {}, failedCount: 0, sum: false,
    loading: null, exhausted: false, failed: null, keys: null
  };

  function api(path, opt) {
    return UIKit.http(new URL(String(path).replace(/^\/+/, ''), location.href).href, Object.assign({ timeout: 30000 }, LOAD_TEXT, opt || {}));
  }
  function kindLabel(card) { return KIND_TEXT[card.kind] || card.kind || '確認'; }
  function sourceLabel(card) { return card.sourceLabel || SOURCE_TEXT[card.source] || card.source || ''; }

  /* ---- URL(読むだけ。書き換えない)---- */
  var EVAL_KINDS = { section: 1 };
  function readUrl() {
    var q = new URLSearchParams(location.search), c = q.get('c') || '', kind = q.get('kind') || '', lane = q.get('lane') === 'eval' ? 'eval' : '';
    if (KIND_TEXT[kind] && !!EVAL_KINDS[kind] !== (lane === 'eval')) kind = '';   // レーンの種類だけ(違えば種類の指定を捨てる)
    return { c: lane ? '' : (/^[A-Za-z0-9_-]{1,64}$/.test(c) ? c : ''), kind: KIND_TEXT[kind] ? kind : '', back: !lane && q.get('back') === 'cases' ? 'cases' : '', lane: lane };
  }
  function backHref() { return S.want.back === 'cases' && S.want.c ? 'cases?c=' + encodeURIComponent(S.want.c) : ''; }
  function nextQuery(n) {
    var q = new URLSearchParams();
    if (S.want.c) q.set('c', S.want.c);
    if (S.want.kind) q.set('kind', S.want.kind);
    if (S.want.lane) q.set('lane', S.want.lane);
    q.set('n', String(n));
    var skip = Object.keys(S.seen).concat(S.queue.map(function (c) { return c.id; }));
    if (n && skip.length) q.set('skip', skip.slice(-200).join(','));
    return 'api/check/next?' + q.toString();
  }

  /* ---- 上の帯 ---- */
  /* 目標(⑤ の goals の 1 行 = {label, opens, left, unit, reached})→「C1 盛り上がりの重み まで あと 2 本(採用の記録 配信 10 本)」。今のカードの種類の目標を先に */
  function curGoal() {
    var k = S.cur ? S.cur.kind : '', g = (k && S.goals[k]) || S.goal;
    return g && typeof g === 'object' && (g.label || g.opens) ? g : null;
  }
  function goalHtml(g) {
    if (!g) return '';
    var what = '<b>' + esc(g.opens || g.label) + '</b>', left = Math.max(0, +g.left || 0), unit = g.unit || '件';
    if (g.reached || (g.left != null && left === 0)) return 'この確認で決まる物: ' + what + ' は目標に届きました';
    if (g.left == null) return 'この確認で決まる物: ' + what + '<span class="hint">(' + (g.label ? esc(g.label) + '・' : '') + 'まだ測っていません)</span>';   // 未測定(now も left も無い)を「あと 0」と出さない
    if (unit === 'sec') { left = Math.ceil(left / 60); unit = '分'; }
    return 'この確認で決まる物: ' + what + ' まで あと <b data-chk-left>' + left + '</b> ' + esc(unit) + (g.opens && g.label ? '<span class="hint">(' + esc(g.label) + ')</span>' : '');
  }
  function renderBand() {
    $('#chkToday').textContent = String(S.today);
    $('#chkGoal').innerHTML = goalHtml(curGoal());
    var f = $('#chkFailed'), n = S.failedCount;
    f.hidden = !n;
    f.textContent = n ? '前に答えた ' + n + ' 件を実物に反映できませんでした(案件の画面で確かめてください)' : '';
  }
  function takeCounts(j) {
    if (!j || typeof j !== 'object') return;
    if (j.counts && typeof j.counts.today === 'number') S.today = j.counts.today;
    if (j.counts && typeof j.counts.failed === 'number') S.failedCount = j.counts.failed;
    if ('goal' in j) S.goal = j.goal && typeof j.goal === 'object' ? j.goal : null;
    if (j.goals && typeof j.goals === 'object') S.goals = j.goals;
    if ('sectionCards' in j) S.sectionCards = j.sectionCards === true;
    renderBand();
  }

  /* ---- 待ち行列(先読み)---- */
  function fill() {
    if (S.loading || S.exhausted) return S.loading || Promise.resolve();
    var want = KEEP - S.queue.length;
    if (want <= 0) return Promise.resolve();
    S.loading = api(nextQuery(want)).then(function (j) {
      S.loading = null; S.failed = null;
      takeCounts(j);
      var got = (Array.isArray(j.cards) ? j.cards : []).filter(function (c) {
        return c && typeof c === 'object' && typeof c.id === 'string' && ID_RE.test(c.id) && !S.seen[c.id] &&
          (!S.cur || S.cur.id !== c.id) && !S.queue.some(function (x) { return x.id === c.id; });
      });
      if (!got.length) S.exhausted = true;
      S.queue = S.queue.concat(got);
      renderQueue();
    }, function (e) {
      S.loading = null; S.failed = e;
      throw e;
    });
    return S.loading;
  }
  function refill() { if (S.queue.length <= LOW) fill().then(null, function () { /* 次に要るときにもう一度 */ }); }
  var countsTimer = 0;
  function refreshCounts() {   // 答えたあとの帯の数(⑤ が数え直す)。続けて答える間は待つ
    clearTimeout(countsTimer);
    countsTimer = setTimeout(function () { api(nextQuery(0)).then(takeCounts, function () { /* 帯が古いだけ */ }); }, 1500);
  }

  /* ---- カードを出す・外す ---- */
  function stopPlayers() { S.players.forEach(function (p) { try { p.stop(); } catch (e) { /* 無視 */ } }); }
  function unmountCard() {
    S.players.forEach(function (p) { try { p.destroy(); } catch (e) { /* 無視 */ } });
    S.players = [];
    if (S.view && S.view.unmount) { try { S.view.unmount(); } catch (e) { UIKit.report('カードの unmount で失敗しました: ' + (e && e.message)); } }
    S.view = null;
    $('#chkBody').innerHTML = '';
  }
  function ctxFor(card) {
    return {
      case: card.case || null, kindLabel: kindLabel(card), api: api, refreshKeys: renderKeys,
      answer: function (a) { if (S.cur === card) answer(a); },
      player: function (el, media, opt) {
        var h = window.CheckPlayer ? CheckPlayer.mount(el, media, opt) : null;
        if (h) S.players.push(h);
        return h;
      }
    };
  }
  function show() {
    unmountCard();
    S.cur = null;
    $('#chkCard').hidden = true; $('#chkSum').hidden = true; $('#chkEmpty').hidden = true;
    if (S.sum) return showSummary();
    if (!S.queue.length) {
      if (S.loading || (!S.exhausted && !S.failed)) {
        $('#chkEmpty').innerHTML = '<p class="hint chk-loading" role="status">確認を読み込んでいます…</p>';
        $('#chkEmpty').hidden = false;
        fill().then(show, showFail);
        return renderKeys();
      }
      if (S.failed) return showFail(S.failed);
      return showEmpty();
    }
    var card = S.queue.shift();
    S.cur = card; S.shownAt = Date.now();
    $('#chkCard').hidden = false;
    $('#chkKind').innerHTML = '<b>' + esc(kindLabel(card)) + '</b>' + (sourceLabel(card) ? ' <span class="pill">' + esc(sourceLabel(card)) + '</span>' : '') +
      (card.case && card.case.title ? ' <span class="chk-case" title="' + esc(card.case.title) + '">' + esc(card.case.title) + '</span>' : '');
    var view = CheckCards.create(card.kind), body = $('#chkBody');
    S.view = view;
    if (!view) {
      body.innerHTML = '<p class="notice">この種類のカード(' + esc(card.kind || '?') + ')はまだ描けません。[飛ばす] で次へ進んでください。</p>';
    } else {
      try { view.render(card, body, ctxFor(card)); } catch (e) {
        UIKit.report('カードを描けませんでした: ' + (e && e.message), { stack: e && e.stack });
        body.innerHTML = '<p class="notice err">このカードを描けませんでした。[飛ばす] で次へ進んでください。</p>';
      }
    }
    renderBand(); renderUndo(); renderQueue(); renderKeys();
    refill();
  }
  function emptyBox(title, text, acts) {
    return '<div class="empty chk-empty"><b>' + esc(title) + '</b><span>' + esc(text) + '</span><div class="row">' + acts + '</div></div>';
  }
  function endActs() {
    var back = backHref();
    return (back ? '<a class="btn primary" href="' + esc(back) + '">案件へ戻る</a><a class="btn" href="./">ホームへ</a>' : '<a class="btn primary" href="./">ホームへ</a>');
  }
  function showEmpty() {
    var e = $('#chkEmpty');
    if (S.want.lane === 'eval') {   // 評価のレーン: スイッチが切れている / 全部聞いた
      e.innerHTML = S.sectionCards === false ?
        emptyBox('区間カードは試験中で止めてあります', '設定 → 編集(文字起こし)の「確かめるの評価のレーンに区間カードを出す」をオンにすると、ここに出ます。それまでは編集の画面の評価ドリルで確かめてください。',
          '<a class="btn primary" href="settings">設定へ</a><a class="btn" href="check">普段のレーンへ</a>') :
        emptyBox('いま確かめる評価用の動画はありません', '評価用の動画を文字起こしすると(上の「まとめて文字起こし」)、ここに区間カードが出ます。' + (S.answered ? '(この画面で ' + S.answered + ' 件答えました)' : ''),
          '<a class="btn primary" href="check">普段のレーンへ</a><a class="btn" href="./">ホームへ</a>');
      e.hidden = false;
      renderUndo(); renderQueue(); renderKeys();
      return;
    }
    e.innerHTML = emptyBox(S.answered ? '今日の分は終わりです' : 'いま確かめる物はありません',
      '新しい切り抜き・文字起こしができると、ここに確認が出ます。' + (S.answered ? '(この画面で ' + S.answered + ' 件答えました)' : ''), endActs());
    e.hidden = false;
    renderUndo(); renderQueue(); renderKeys();
  }
  function showFail(err) {
    var e = $('#chkEmpty');
    e.innerHTML = '<div class="empty chk-empty" data-chk-fail><b>確認の一覧を読み込めませんでした</b><span>' + esc((err && err.message) || '') + '</span>' +
      '<div class="row"><button type="button" class="btn primary" data-chk-retry>もう一度読み込む</button><a class="btn" href="./">ホームへ</a></div>' +
      (err && err.detail ? '<details class="ui-disclosure"><summary>詳しく</summary><p class="hint">' + esc(err.detail) + ' ' + esc(err.reason || '') + '</p></details>' : '') + '</div>';
    e.hidden = false;
    renderKeys();
  }
  /* 10 件ごとのまとめ(「10 件答えた・C1 まであと 1 配信」)。目標の数は ⑤ に数え直してもらってから描き直す */
  function paintSummary() {
    var el = $('#chkSum'), g = curGoal() || S.goal;
    el.innerHTML = '<div class="chk-q">' + S.answered + ' 件答えました</div>' +
      '<p class="hint" data-chk-sumgoal>' + (g ? goalHtml(g) + '。' : '') + 'ひと息ついてから続けられます。</p>' +
      '<div class="chk-acts"><button type="button" class="btn primary lg" data-chk-go>続ける <kbd class="ui-kbd">Enter</kbd></button>' + endActs().replace(/btn primary/, 'btn') + '</div>';
    el.hidden = false;
  }
  function showSummary() {
    paintSummary();
    renderUndo(); renderQueue(); renderKeys();
    clearTimeout(countsTimer);
    api(nextQuery(0)).then(function (j) { takeCounts(j); if (S.sum && !$('#chkSum').hidden) paintSummary(); }, function () { /* 数が古いだけ */ });
  }

  /* ---- 評価のレーンの頭(C-EVAL。評価用の一括 = 編集の ⑤ eval/drill/evalbatch・定点 = eval/drill/drill.drill_status。編集を取り込んだ入口の transcribe/ を直に読む)---- */
  var evalTimer = 0, evalBusy = false;
  function evalHeadHtml(st, eb) {
    var left = st && isFinite(+st.leftSec) ? Math.ceil(+st.leftSec / 60) : null;
    var fixed = st ? (st.ready ? '定点(確かめ済みの評価用 ' + Math.round((+st.goalSec || 0) / 60) + ' 分)に届きました' :
      '定点まで あと <b>' + (left == null ? '?' : left) + '</b> 分(確かめ済み ' + (+st.reviewedDocs || 0) + ' 本・未確認 ' + (+st.pendingDocs || 0) + ' 本' +
      ((+st.untranscribed || 0) ? '・まだ文字起こししていない ' + st.untranscribed + ' 本' : '') + ')') : '定点の数を読めませんでした';
    var run = eb && eb.enabled, line = !eb ? '評価用の一括の状態を読めませんでした(編集が動いていないかもしれません)' :
      run ? 'まとめて文字起こし中: 入れた ' + (+eb.enqueued || 0) + ' 本・済み ' + (+eb.done || 0) + ' 本' + (eb.remaining != null ? '・残り ' + eb.remaining + ' 本' : '') +
        ((+eb.failed || 0) ? '・失敗 ' + eb.failed + ' 本' : '') + (eb.titles && eb.titles.length ? '(' + eb.titles.slice(0, 2).join('・') + ')' : '') :
      (eb.finished ? 'まとめて文字起こしは終わりました' : 'まとめて文字起こしは止まっています') + ((+eb.done || 0) ? '(済み ' + eb.done + ' 本)' : '');
    return '<div class="card-title">評価用の動画</div><p>' + fixed + '</p>' +
      '<div class="row chk-evalbatch"><span class="hint" role="status">' + esc(line) + '</span>' +
      (eb ? (run ? '<button type="button" class="btn" data-chk-eb="stop">止める</button>' :
        '<button type="button" class="btn" data-chk-eb="start" title="評価用のフォルダの動画を、文字起こししていない物から順にまとめて文字起こしします">まとめて文字起こし</button>') : '') +
      '</div>' + (eb && eb.lastError ? '<p class="notice err">' + esc(String(eb.lastError).slice(0, 200)) + '</p>' : '') +
      '<p class="hint">区間を聞いて直した行は正解(校正済み)になります。機械の予想・覚えた声の候補は出しません。評価用の動画からは学習しません。</p>';
  }
  function loadEvalHead() {
    clearTimeout(evalTimer);
    var box = $('#chkEvalHead');
    if (S.want.lane !== 'eval' || document.hidden) return;
    var soft = function (p) { return p.then(function (j) { return j; }, function () { return null; }); };
    Promise.all([soft(api('transcribe/api/drill/status', { timeout: 15000 })), soft(api('transcribe/api/eval-batch', { timeout: 15000 }))]).then(function (r) {
      box.innerHTML = evalHeadHtml(r[0], r[1]);
      box.hidden = false;
      evalTimer = setTimeout(loadEvalHead, r[1] && r[1].enabled ? 5000 : 30000);   // 動いている間は 5 秒ごと
    });
  }
  function evalBatch(op) {
    if (evalBusy) return;
    evalBusy = true;
    api('transcribe/api/eval-batch/' + op, { body: {} }).then(function () {
      UIKit.toast(op === 'start' ? 'まとめての文字起こしを始めました' : 'まとめての文字起こしを止めました', { ms: 2500 });
    }, function (e) {
      UIKit.toast((op === 'start' ? '始められませんでした: ' : '止められませんでした: ') + e.message, { kind: 'err', detail: e.detail });
    }).then(function () { evalBusy = false; loadEvalHead(); });
  }

  /* ---- 答える・戻す・飛ばす ---- */
  function answer(a) {
    var card = S.cur;
    if (!card || !a || typeof a !== 'object') return;
    var body = { card: card.id, answer: a, ms: Math.max(0, Date.now() - S.shownAt), skip: S.queue.slice(0, 50).map(function (c) { return c.id; }), page: PAGE };
    var entry = { card: card, p: null };
    entry.p = api('api/check/answer', { body: body }).then(function (j) {
      if (!j || typeof j.answer !== 'string' || !j.answer) throw Object.assign(new Error('答えの記録の番号が返ってきませんでした'), { code: 'no_id' });
      refreshCounts();
      return j.answer;
    });
    entry.p.then(null, function (e) {   // 記録できなかった = そのカードを次に戻す(今日の数も戻す)
      var i = S.hist.indexOf(entry);
      if (i >= 0) S.hist.splice(i, 1);
      S.today = Math.max(0, S.today - 1); S.answered = Math.max(0, S.answered - 1);
      delete S.seen[card.id];
      S.queue.unshift(card);
      renderBand(); renderUndo(); renderQueue();
      if (!S.cur && !S.sum) show();
      UIKit.toast('答えを記録できませんでした: ' + e.message + '(このカードはもう一度出ます)', { kind: 'err', detail: e.detail });
    });
    S.hist.push(entry);
    S.seen[card.id] = 1;
    S.today++; S.answered++;
    if (S.answered % SUM_EVERY === 0) S.sum = true;
    renderBand();
    show();
  }
  var undoing = false;
  function undo() {
    var last = S.hist[S.hist.length - 1];
    if (!last || undoing) { if (!last) UIKit.toast('戻せる答えがありません(飛ばしたカードは戻しません)', { ms: 2500 }); return; }
    undoing = true;
    function back() {   // 戻せた(か、もう戻っていた)= カードを前に出し直す
      var i = S.hist.indexOf(last);
      if (i >= 0) S.hist.splice(i, 1);
      S.today = Math.max(0, S.today - 1); S.answered = Math.max(0, S.answered - 1);
      if (S.cur) S.queue.unshift(S.cur);
      S.sum = false;
      delete S.seen[last.card.id];
      S.queue.unshift(last.card);
      renderBand(); refreshCounts();
      show();
      UIKit.keybar.flash('Z');
    }
    last.p.then(function (id) {
      return api('api/check/answer', { body: { undo: id } });
    }).then(function () {
      undoing = false;
      back();
    }, function (e) {
      undoing = false;
      var i = S.hist.indexOf(last);
      if (i < 0) return;   // 記録できなかった答え(もう戻してある)
      if (e && e.code === 'undone') return back();   // 前の Z がサーバーで済んでいた(やりかけのやり直し)
      if (e && GONE_UNDO[e.code]) {   // 戻せない答え(届けた・あとで直された)は履歴から外す = 次の Z は 1 つ前へ
        S.hist.splice(i, 1);
        renderUndo(); renderKeys();
        UIKit.toast('この答えは戻せません: ' + e.message + '(次の Z は 1 つ前の答えへ)', { kind: 'err', detail: e.detail });
        return;
      }
      UIKit.toast('1 つ前に戻せませんでした: ' + e.message, { kind: 'err', detail: e.detail });
    });
  }
  function skip() {
    var card = S.cur;
    if (!card) return;
    S.seen[card.id] = 1;
    api('api/check/skip', { body: { card: card.id, page: PAGE } }).then(null, function (e) {
      UIKit.toast('飛ばしたことを記録できませんでした(次に開くとまた出ます): ' + e.message, { kind: 'err', detail: e.detail });
    });
    UIKit.keybar.flash('N');
    show();
  }

  /* この画面の保留(1 枚遅れの [送る])を確定する。タブを閉じた・隠したとき(閉じる直前も keepalive で届く)。失敗は次に開いたときの counts.failed。
     別の窓へ移っただけ(blur)では確定しない(案件の画面や別のアプリを見に行っただけで届かないように。決定 Q12 (a)) */
  function flush() {
    if (!S.hist.length) return;
    api('api/check/flush', { body: { page: PAGE }, keepalive: true, timeout: 10000 }).then(null, function () { /* 次の答え・しばらくして別の画面の答えで確定する */ });
  }

  /* ---- このあと・戻すボタン・下の帯 ---- */
  function renderQueue() {
    var list = (S.cur ? [S.cur] : []).concat(S.queue).slice(0, 7);
    $('#chkQueue').innerHTML = list.length ? list.map(function (c, i) {
      return '<li' + (i === 0 && S.cur ? ' aria-current="true"' : '') + '><span class="chk-q-k">' + esc(kindLabel(c)) + '</span>' +
        (sourceLabel(c) ? '<span class="hint">' + esc(sourceLabel(c)) + '</span>' : '') + '</li>';
    }).join('') + (S.queue.length > 6 ? '<li class="hint">ほか ' + (S.queue.length - 6) + ' 件</li>' : '') : '<li class="hint">待っている確認はありません</li>';
  }
  function renderUndo() {
    var b = $('#chkUndo'), n = S.hist.length;
    b.disabled = !n;
    b.title = n ? '最後に答えたカードへ戻り、答えを取り消します' : 'まだ答えたカードがありません(飛ばしたカードは戻しません)';
  }
  function renderKeys() {
    var items = [];
    if (S.sum) items = [{ k: 'Enter', l: '続ける' }];
    else if (S.cur && S.view && S.view.keybar) { try { items = S.view.keybar(S.cur) || []; } catch (e) { items = []; } }
    if (S.cur) items = items.concat([{ k: 'N', l: '飛ばす' }, { k: 'Space', l: '再生・停止' }]);
    if (S.cur && replayable()) items.push({ k: 'R', l: 'もう一度聞く' });
    if (S.hist.length) items.push({ k: 'Z', l: '1 つ前に戻す' });
    UIKit.keybar.set(items);
  }

  /* ---- キー(keydown は 1 本。殻のキー → カード → 共通の再生キー)---- */
  function inOverlay(t) { return !!(t && t.closest && t.closest('.ui-drawer, dialog, [role="dialog"], [aria-modal="true"]')); }
  function curMedia() {
    for (var i = 0; i < S.players.length; i++) { var m = S.players[i].media && S.players[i].media(); if (m) return m; }
    return null;
  }
  /* もう一度聞く(R = 編集の「この行をもう一度聞く」と同じキー。カードのキーより先 = どのカードでも効く。ボタンは再生部品の中) */
  function replayable() { return S.players.some(function (p) { return p.canReplay && p.canReplay(); }); }
  function replay() {
    for (var i = 0; i < S.players.length; i++) if (S.players[i].canReplay && S.players[i].canReplay()) { S.players[i].replay(); return; }
  }
  function viewKeys(e) {
    var v = S.view, r = null;
    if (!v || !v.keys || !S.cur) return null;
    try { r = v.keys(e, S.cur); } catch (x) { UIKit.report('カードのキーで失敗しました: ' + (x && x.message), { stack: x && x.stack }); }
    return r;
  }
  function onKey(e) {
    if (e.defaultPrevented || e.isComposing || e.keyCode === 229) return;
    if (UIKit.keymap && UIKit.keymap.capturing && UIKit.keymap.capturing()) return;
    if (inOverlay(e.target)) return;
    var typing = UIKit.keys.isTyping(e.target), plain = !e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey, k = keyOf(e);
    if (!typing && plain && k === 'Z') { e.preventDefault(); undo(); return; }
    if (S.sum) {
      if (!typing && plain && k === 'Enter') { e.preventDefault(); goOn(); }
      return;
    }
    if (!typing && plain && k === 'N' && S.cur) { e.preventDefault(); skip(); return; }
    if (!typing && plain && k === 'R' && S.cur && replayable()) { e.preventDefault(); if (!e.repeat) { UIKit.keybar.flash('R'); replay(); } return; }
    if (typing && !(S.view && S.view.typingKeys)) return;
    var r = viewKeys(e);
    if (r && typeof r === 'object') { e.preventDefault(); UIKit.keybar.flash(k); answer(r); return; }
    if (r === true) { e.preventDefault(); return; }
    if (!typing && S.keys && S.keys(e)) return;
  }
  function goOn() { S.sum = false; show(); }

  /* ---- 起動 ---- */
  document.addEventListener('DOMContentLoaded', function () {
    UIKit.settings.mount({ title: '設定' });
    UIKit.homeApi('api/status', { method: 'GET', timeout: 8000 }).then(function (j) {
      if (j && j.version) { $('#ver').textContent = 'v' + j.version; if (UIKit.appnav && UIKit.appnav.setVersion) UIKit.appnav.setVersion('v' + j.version); }
    }, function () { /* 版が出ないだけ */ });
    S.want = readUrl();
    Array.prototype.forEach.call(document.querySelectorAll('[data-chk-lane]'), function (a) {
      if ((a.getAttribute('data-chk-lane') === 'eval') === (S.want.lane === 'eval')) a.setAttribute('aria-current', 'page');
    });
    if (S.want.lane === 'eval') {
      $('#chkEvalHead').addEventListener('click', function (e) { var b = e.target.closest && e.target.closest('[data-chk-eb]'); if (b) evalBatch(b.getAttribute('data-chk-eb')); });
      UIKit.life.onReturn(loadEvalHead);   // 隠していた間は止めて、戻ったら読み直す
      loadEvalHead();
    }
    S.keys = UIKit.keys.playback({ media: curMedia, enabled: function () { return !!S.cur; } });
    document.addEventListener('keydown', onKey);
    $('#chkBody').addEventListener('click', function (e) {   // 答えのボタン = キーと同じ道(描き手の keys)
      var b = e.target.closest ? e.target.closest('[data-chk-k]') : null;
      if (!b || b.disabled || !S.cur) return;
      var r = viewKeys({ key: b.getAttribute('data-chk-k'), fromButton: true, target: b, shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, preventDefault: function () {} });
      if (r && typeof r === 'object') answer(r);
    });
    $('#chkSkip').addEventListener('click', skip);
    $('#chkUndo').addEventListener('click', undo);
    $('#chkSum').addEventListener('click', function (e) { if (e.target.closest && e.target.closest('[data-chk-go]')) goOn(); });
    $('#chkEmpty').addEventListener('click', function (e) {
      if (!(e.target.closest && e.target.closest('[data-chk-retry]'))) return;
      S.failed = null; S.exhausted = false; show();
    });
    UIKit.life.onLeave(function (reason) {
      if (reason !== 'blur') {   // 'blur' = 隣の窓へ(画面は見えている。保留は確定しない・再生は止めない)
        flush();   // 1 枚遅れの [送る] を確定(隠したまま閉じても届く。decisions 3-41・Q12)
        stopPlayers();
      }
      if (S.view && S.view.leave) { try { S.view.leave(reason); } catch (e) { UIKit.report('カードの leave で失敗しました: ' + (e && e.message)); } }
    });
    renderBand(); renderQueue();
    show();
  });

  /* 画面のテスト(tests/app/e2e_check.py)が今の状態を読む口 */
  window.CheckShell = {
    state: function () {
      return { cur: S.cur ? S.cur.id : '', kind: S.cur ? S.cur.kind : '', queue: S.queue.map(function (c) { return c.id; }), today: S.today, answered: S.answered,
        hist: S.hist.length, summary: S.sum, empty: !$('#chkEmpty').hidden && !!$('#chkEmpty .chk-empty:not([data-chk-fail])'),
        failed: !$('#chkEmpty').hidden && !!$('#chkEmpty [data-chk-fail]'), want: S.want };
    }
  };
})();
