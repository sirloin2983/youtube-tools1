/* ホーム(src/app/ui/home/portal.html。段階5で入口 + 案件を1つにした)。
   - ツールの起動状態は /api/status を定期的に読んで「詳しく」の中のカードに出す(開く・起動・停止・再起動・すべて終了)
   - 案件(配信ごと)の一覧は /api/cases を読んで組み立てる。状態・メモは持たない(MARKS-3)
   - 「処理の状況」は、まとめて実行(/api/flow/runs)の実行中(今の段・全体の進み)・待ち・失敗と、失敗の文がある自動の切り抜き(案件の一覧の failed)。
     案件の一覧の行は依頼(誰の・何を)と結果(切り抜き・校正・パック・失敗)だけ。「確かめる」は api/check/next?n=0 の goal から今いちばん効く確認を 1 つ・[始める] は /check(V1 確かめる)。
     「新しい案件」は引き出し(cases-panels/new.js = スタジオ ① のつなぎ)。受付・バックアップ・記録・編集の精度・調子は「運用」の枠に畳む
   - 画面の移り方(S-15): ツールの画面へのリンクは同じ窓で移る(target を付けない。新しい窓は Ctrl・中クリック = 窓の中なら UIKit.win)。
     「詳しく」のツールのカードの「開く」(サーバーの管理)だけは新しい窓
   - 「単体の文字起こし」は、案件の一覧が返す unlinked(どの配信にも紐づかない文字起こし)の件数と「案件の画面で見る」だけ
     (選んでまとめて実行する一覧は 10-24 ユーザーの OK で消した。「編集」の履歴の「選んで、まとめて実行」は残る)
   ツール名・ログ・メッセージ・配信のタイトルなどはすべて textContent で入れる(HTML として解釈させない)。 */
(function () {
  'use strict';
  var LABEL = { starting: '起動中…', running: '動作中', external: '別の画面で起動済み', stopping: '停止中…', stopped: '停止', crashed: '異常終了', missing: '見つかりません' };
  var PILL = { starting: 'run', running: 'ok', external: 'info', stopping: 'wait', stopped: 'wait', crashed: 'err', missing: 'err' };
  var STEP_PILL = { wait: 'wait', run: 'run', done: 'ok', skip: 'wait', warn: 'warn', error: 'err' };
  var POLL_MS = 1500, POLL_HIDDEN_MS = 5000;
  var PAGE_SIZE = 30, TODO_CAP = 8;

  var cards = {};        // ツールID → {el, data}
  var fails = 0, closed = false, timer = null, quitNotice = '';

  var casesData = null;                 // /api/cases の中身
  var casesRev = null, casesRevAt = 0, casesRevTimer = 0;   // /api/status の casesRev(案件の一覧の元の更新の印)・最後に一覧を読んだ時刻
  var autoPushed = null;              // /api/status の autoPushed(まとめて実行に積んだ回数。増えたら pollAuto をすぐ)
  var runsByVideo = {}, runsByDoc = {}; // /api/flow/runs の実行(配信単位・文書単位)。最新のものだけ
  var pastByVideo = {}, pastByDoc = {}; // /api/flow/runs の past: 前回の結果(記録のファイルから。この起動の実行が無い配信・文書だけ。段2 B-6)
  var HIST_PAGE = 50, histOffset = 0, histBusy = false;   // 「まとめて実行の記録」(/api/flow/history。開いたときだけ読む)
  var runsByFile = {};                  // /api/flow/runs の kind "file"(依頼の文字起こしだけ。videoId・docId が無いので実行の id で持つ)
  var wasActiveVideo = {}, wasActiveDoc = {}, wasActiveFile = {};
  var autoTimer = null;
  var visibleCount = PAGE_SIZE;         // 案件の一覧の「もっと見る」
  var openCases = {};                   // この画面を開いてから自分で開閉した案件(id → bool)
  var caseDrafts = {};                  // 保存していない入力(配信者)。id → {streamer}(再描画(alt-tab で戻ったときなど)でも保つ)
  function draftFor(id) { return caseDrafts[id] || (caseDrafts[id] = {}); }
  var termShown = {};
  var todoShowAll = false;

  function $(sel, el) { return (el || document).querySelector(sel); }
  function $all(sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); }

  /* 入口の API(UIKit.homeApi。合言葉・時間切れ・失敗の形は ui-kit の 1 か所)。path は入口の直下からの相対('api/cases')。
     POST はいつも本文を送る(無ければ {})。時間切れは GET 8 秒・POST 60 秒(opt で上書き: keepalive・timeout)。
     失敗の本文(message)に出すのは日本語の文だけ。サーバーの文は e.reason、HTTP の番号・通信の例外の原文は e.detail(知らせの「詳しく」・title)へ(B-03) */
  var API_TEXT = { offline: 'ホームにつながりませんでした', slow: 'ホームの応答が遅れています', fail: 'ホームがうまく応答できませんでした' };
  function api(path, method, body, opt) {
    var post = method === 'POST';
    return UIKit.homeApi(path, Object.assign({ method: method || 'GET', body: post ? (body || {}) : undefined, timeout: post ? 60000 : 8000 }, API_TEXT, opt));
  }

  function toast(msg, kind) { UIKit.toast(msg, kind ? { kind: kind } : undefined); }
  /* 失敗の文は「何ができなかったか」+「どうすればいいか」(B-03)。サーバーの文(日本語)は間に入れ、HTTP の番号・例外の名前・英語の原文は
     知らせの「詳しく」(detail)・title にだけ出す */
  function reasonOf(e) {
    var m = e && e.reason !== undefined ? e.reason : String((e && e.message) || '');
    return /HTTP \d{3}|Failed to fetch|NetworkError|Load failed|AbortError|Error:/.test(m) ? '' : m;
  }
  function detailOf(e) { return (e && e.detail) || (e && e.message) || ''; }
  function failText(what, next, e) {
    var why = reasonOf(e);
    return what + '。' + (why ? why.replace(/[。.]+$/, '') + '。' : '') + (next ? next + (/[。.]$/.test(next) ? '' : '。') : '');
  }
  function failToast(what, next, e, retry) {
    if (e && e.code === 'token') return '';   /* ホームの起動し直し(合言葉の失効)は UIKit.http が「開き直す」の知らせを出す。ここで「少し待って」と重ねない */
    var text = failText(what, next, e), opt = { kind: 'err', detail: detailOf(e) };
    if (retry) { opt.action = { label: 'もう一度', fn: retry }; opt.ms = 0; }
    UIKit.toast(text, opt);
    return text;
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  /* 空の表示(M5。ui-guidelines 5): 「まだ〇〇はありません」+「〇〇すると、ここに出ます」の 2 文 + 次に押すボタン 1 つ。
     act = {label, href} か {label, fn}(無ければボタンなし)。box を渡すとその中身を作り直す */
  function emptyBox(title, text, act, box) {
    box = box || el('div', 'empty pt-empty');
    box.textContent = '';
    box.appendChild(el('b', '', title));
    box.appendChild(document.createTextNode(text));
    if (act) {
      var row = el('div', 'row pt-empty-acts'), b;
      if (act.href) { b = el('a', 'btn small', act.label); b.href = act.href; }
      else { b = el('button', 'btn small', act.label); b.type = 'button'; b.addEventListener('click', act.fn); }
      row.appendChild(b); box.appendChild(row);
    }
    return box;
  }
  /* ---- 一覧の非表示(ui-kit の UIKit.hide)---- 案件・次にやること・単体の文字起こし・届いた依頼・まとめて実行の記録。
     覚える場所はホームの設定の節 hidden(どの窓・ツールでも同じ)。データは消さない。「非表示 n件を表示」で薄く出して「表示に戻す」 */
  function hideApi() { return UIKit.hide.available() ? UIKit.hide : null; }   // 合言葉があるとき(start.bat から開いたとき)だけ使える
  function isHid(list, id) { var h = hideApi(); return !!(h && h.has(list, id)); }
  function showHid(list) { var h = hideApi(); return !!(h && h.showing(list)); }
  /* 押したボタンが描き直しで消えても、フォーカスを失わない(M6。キーボードの人が画面の先頭から Tab し直さないように)。
     行には data-fkey(一覧の名前:id)を付けてあるので、描き直したあとで引く: その行がまだあれば行の中の「非表示にする」・
     隠れて無くなったら次の行(無ければ前の行)の最初の操作・それも無ければその一覧の「非表示 n件を表示」 */
  var HIDE_TOGGLE = { cases: '#casesHidden', todo: '#todoHidden', intake: '#intakeHidden', runs: '#historyHidden' };
  function rowByKey(k) { return k ? $all('[data-fkey]').filter(function (n) { return n.getAttribute('data-fkey') === k; })[0] || null : null; }
  function firstFocusable(root) {
    return root ? (root.querySelector('a[href], summary, button:not([disabled]), input:not([disabled]), select, textarea') || null) : null;
  }
  function focusFallback(list, near) {
    var t = near || (HIDE_TOGGLE[list] ? $(HIDE_TOGGLE[list]) : null), box = t && t.hidden ? null : t;
    if (box) { box.focus({ preventScroll: true }); return; }
    var h = $(list === 'cases' ? '#fText' : '#todoBox h2');
    if (h) { if (!/INPUT|BUTTON|A|SUMMARY/.test(h.tagName)) h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
  }
  function hidePlan(btn, list) {
    var row = btn.closest('[data-fkey]'), key = row && row.getAttribute('data-fkey');
    var sib = row && (row.nextElementSibling || row.previousElementSibling);
    var sibKey = sib && sib.getAttribute && sib.getAttribute('data-fkey');
    return function () {
      var mine = rowByKey(key), tgt = mine ? ($('.pt-hide', mine) || firstFocusable(mine)) : (rowByKey(sibKey) ? firstFocusable(rowByKey(sibKey)) : null);
      if (tgt) tgt.focus({ preventScroll: true }); else focusFallback(list);
    };
  }
  function hideBtn(list, id, label) {
    var on = isHid(list, id), h0 = hideApi();
    var b = el('button', 'btn small ghost pt-hide');
    var ic = el('span', 'pt-hide-ic'); ic.setAttribute('aria-hidden', 'true');
    ic.innerHTML = UIKit.icon(on ? 'undo' : 'close', { size: 14 });   // 狭い幅では文字をやめてアイコンだけ(S11)
    b.appendChild(ic); b.appendChild(el('span', 'pt-hide-t', on ? '表示に戻す' : '非表示にする'));
    b.type = 'button';
    b.setAttribute('aria-label', on ? '表示に戻す' : '非表示にする');
    b.title = on ? '一覧に戻します' : '一覧に出さないようにします(データは消しません。一覧の「非表示 n件を表示」で出せます)';
    b.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      var h = hideApi(); if (!h) return;
      var after = hidePlan(b, list);
      var p = h.set(list, [id], !on, { label: label });   // 画面は set の中で(同期で)描き直される
      after();
      p.catch(function () { /* 知らせは部品が出す */ });
    });
    return b;
  }
  function markHid(node, list, id, tagBox) {
    if (!isHid(list, id)) return;
    node.classList.add('ui-hidden-item');
    if (tagBox) tagBox.appendChild(el('span', 'ui-hidden-tag', '非表示'));
  }
  function hideToggle(sel, list, n) { UIKit.hide.toggle($(sel), list, n); }

  function term(word, title) {
    if (termShown[word]) return document.createTextNode(word);
    termShown[word] = true;
    var a = document.createElement('abbr');
    a.className = 'ui-term'; a.title = title; a.textContent = word;
    return a;
  }
  function tc(sec) { return UIKit.fmt.dur(sec, { floor: true }); }   // 秒 → 1:23:45(切り捨て)
  /* 月/日 時:分(時は 0 埋めしない・年は出さない。UIKit.fmt.date と文が違うので残す。札の title・パックの日時) */
  function when(ms) {
    if (!ms) return '';
    var d = new Date(ms);
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function link(text, href) {   // 同じ窓で移る(S-15。窓・タブを増やさない)
    var a = el('a', 'btn small', text);
    a.href = href;
    return a;
  }

  /* ================================================================ ツールの起動状態(「詳しく」の中) ================================================================ */

  /* ホームに取り込んだツールの画面のページは無い = 「開く」は今その仕事をする画面へ(スタジオ = 新しい案件・編集 = 案件の画面) */
  var MOUNTED_OPEN = { studio: '/#new', transcribe: '/cases' };
  function toolUrl(t) {
    if (t.mounted) return 'http://' + location.hostname + ':' + t.port + (MOUNTED_OPEN[t.id] || '/');
    var path = /^\/(?:[a-z0-9][a-z0-9-]{0,31}\/)?$/.test(t.path || '') ? t.path : '/';
    return 'http://' + location.hostname + ':' + t.port + path;
  }

  /* 取り込んだツールの場所(/studio/・/transcribe/・/cut2resolve/)を UIKit.tools.setPaths(v6)に渡す(ツールの API の base を引く部品のため)。
     ヘッダー左の ui-appnav は今は ホーム/案件/確かめる/設定 で、入口の画面だけを指す。
     ここでは /api/status から場所だけ取り出して渡す(href を直接書き換えない) */
  function toolPaths(tools) {
    var out = {};
    tools.forEach(function (t) { if (t.mounted && t.path) out[t.id] = t.path; });
    return out;
  }

  function build(t) {
    var li = $('#tplTool').content.firstElementChild.cloneNode(true);
    li.setAttribute('data-tool', t.id);
    var mark = $('.ui-brand-mark', li), icon = document.getElementById('icon-' + t.id);
    mark.setAttribute('data-tool', t.id);
    if (icon) mark.appendChild(icon.content.firstElementChild.cloneNode(true));
    $('.pt-name', li).textContent = t.name;
    $('.pt-sub', li).textContent = t.sub;
    var box = $('.pt-logbox', li);
    box.addEventListener('toggle', function () { if (box.open) loadLog(t.id); });
    $('#flow').appendChild(li);
    return (cards[t.id] = { el: li, data: t });
  }

  function updateTool(t) {
    if (t.hidden && !cards[t.id] && (t.state === 'running' || t.state === 'starting' || t.state === 'external')) return;   // 部品(cut2resolve)は困っているときだけ出す
    if (t.hidden && cards[t.id] && (t.state === 'running' || t.state === 'external')) { cards[t.id].el.remove(); delete cards[t.id]; return; }
    var c = cards[t.id] || build(t);
    c.data = t;
    var el2 = c.el, s = t.state;
    el2.setAttribute('data-state', s);
    var pill = $('.pt-pill', el2);
    pill.className = 'pill pt-pill ' + (PILL[s] || '');
    pill.textContent = LABEL[s] || s;

    var meta = [];
    if (t.port) meta.push('ポート ' + t.port);
    if (t.version) meta.push('v' + t.version);
    if (t.mounted) meta.push('ホームに取り込み');
    $('.pt-meta', el2).textContent = meta.join(' · ');

    var msg = $('.pt-msg', el2), text = t.message || (s === 'external' ? '別の黒い画面で起動したツールです。止めるときはその画面を閉じてください。' :
      t.mounted && (s === 'running' || s === 'starting') ? 'ホームと一緒に動いています(止めるときは「すべて終了」)。' : '');
    msg.hidden = !text;
    msg.textContent = text;
    msg.className = 'notice pt-msg' + (s === 'crashed' || s === 'missing' ? ' danger' : (s === 'external' && t.message) ? '' : ' info');

    var open = $('.pt-open', el2), up = (s === 'running' || s === 'external') && !!t.port;
    if (up) { open.href = toolUrl(t); open.removeAttribute('aria-disabled'); }
    else { open.removeAttribute('href'); open.setAttribute('aria-disabled', 'true'); }

  }

  function loadLog(id) {
    var c = cards[id];
    if (!c) return;
    var pre = $('.pt-log', c.el);
    api('api/log?tool=' + encodeURIComponent(id) + '&lines=300').then(function (j) {
      var atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24;
      var text = j.exists ? (j.lines.length ? j.lines.join('\n') : '(まだ出力はありません)') : '(ログはまだありません)';
      if (c.data.state === 'external') text = '※ 別の黒い画面で起動したツールの出力は、その画面に出ています。下は、以前この画面から起動したときのログです。\n\n' + text;
      if (pre.textContent !== text) {
        pre.textContent = text;
        if (atBottom) pre.scrollTop = pre.scrollHeight;
      }
      $('.pt-logpath', c.el).textContent = 'ログの場所: ' + j.log;
    }).catch(function () { /* 次の読み込みで直る */ });
  }

  function setConn(ok) {
    var p = $('#conn'), bar = $('#errbar');
    p.className = 'pill ' + (ok ? 'ok' : 'err');
    p.textContent = ok ? '接続済み' : '切断';
    p.hidden = ok;   // いつも出ている緑の札は要らない(状態の知らせは切れたときの帯だけ。S12)
    // 赤い帯は接続の文だけ(一覧の読み込みの失敗などは、その欄の中に出す。接続を確かめるたびに別の文を消さない)
    bar.hidden = ok;
    bar.textContent = ok ? '' : 'サーバーに接続できません。黒い画面が閉じられた可能性があります。start.bat をダブルクリックして起動し直してください。';
  }

  function poll() {
    if (closed) return;
    clearTimeout(timer);
    api('api/status').then(function (st) {
      fails = 0;
      setConn(true);
      $('#ver').textContent = 'ホーム v' + st.version;
      UIKit.appnav.setVersion('v' + st.version);
      if (st.dataDir) { $('#dataDir').textContent = st.dataDir; $('#dataBox').hidden = false; }
      if (st.window) renderWin(st.window);
      if (st.autoPushed !== autoPushed) {   /* まとめて実行に積まれた(友人の依頼の受付など)= 15 秒を待たずに一覧を読む */
        if (autoPushed !== null) pollAuto();
        autoPushed = st.autoPushed;
      }
      if (st.casesRev && st.casesRev !== casesRev) {   /* 案件の一覧の元が変わった(届けた・ライブの書き出し・友人の判断)= 戻るのを待たずに読み直す(5 秒に 1 回まで) */
        var first = casesRev === null;
        casesRev = st.casesRev;
        if (!first && !casesRevTimer) casesRevTimer = setTimeout(function () { casesRevTimer = 0; refreshCases(); }, Math.max(0, casesRevAt + 5000 - Date.now()));
      }
      st.tools.forEach(updateTool);
      UIKit.tools.setPaths(toolPaths(st.tools));
      Object.keys(cards).forEach(function (id) { if ($('.pt-logbox', cards[id].el).open) loadLog(id); });
    }).catch(function () {
      fails++;
      if (fails >= 2) { setConn(false); Object.keys(cards).forEach(function (id) { updateTool(cards[id].data); }); }
    }).then(function () {
      if (!closed) timer = setTimeout(poll, document.hidden ? POLL_HIDDEN_MS : POLL_MS);
    });
  }

  /* 窓で開く(段階7-3。既定は窓) */
  var winBusy = false;
  function inApp() { return UIKit.win.isApp(); }
  function renderWin(w) {
    if (winBusy) return;
    var box = $('#winBox'), sw = $('#winMode'), now = $('#btnWinNow');
    box.hidden = false;
    sw.checked = w.mode === 'app';
    sw.disabled = !w.available && w.mode !== 'app';
    var text = w.available
      ? 'オン(既定)のとき、start.bat で起動すると、ブラウザのタブではなく Microsoft Edge の専用の窓で開きます。' +
        '窓の中のリンクも窓で開き、YouTube などの外のサイトはいつものブラウザで開きます。窓の設定・拡張機能・ログインは、いつものブラウザと別です。' +
        'オフにすると、次の起動からいつものブラウザのタブで開きます。'
      : 'Microsoft Edge が見つからないので、窓では開けません(いつものブラウザで開きます)。';
    if (inApp()) text += '(いまは窓で開いています)';
    $('#winHint').textContent = text;
    now.hidden = !w.available || inApp();
  }
  function setWin(mode) {
    winBusy = true;
    api('api/window', 'POST', { mode: mode }).then(function (j) {
      winBusy = false;
      renderWin(j.window);
      toast(mode === 'app' ? '次に起動したときから、窓で開きます(いま開くなら「いま窓で開く」)' : '次に起動したときから、いつものブラウザで開きます', 'ok');
    }).catch(function (e) {
      winBusy = false;
      failToast('窓で開く設定を保存できませんでした', 'もう一度切り替えてください', e);
      poll();
    });
  }
  function openWinNow() {
    UIKit.win.open(location.origin + '/').then(function () {
      toast('窓で開きました。このタブは閉じてかまいません', 'ok');
    }, function (e) { failToast('窓で開けませんでした', 'いつものブラウザのタブのまま使えます', e); });
  }

  /* すべて終了: 誤操作を防ぐため 2 回押し(UIKit.confirmTwice。ほかの画面の「取り消せない操作」と同じ形・3 秒以内。S7) */
  function doQuit() {
    var b = $('#btnQuit');
    b.disabled = true;
    b.textContent = '終了しています…';
    api('api/shutdown', 'POST').then(function (r) {
      quitNotice = (r && r.notice) || '';   // 録画中なので録画の部品を残した、など
      closed = true;
      clearTimeout(timer);
      $('#main').hidden = true;
      $('#done').hidden = false;
      waitGone(0);
    }).catch(function (e) {
      b.disabled = false;
      b.textContent = 'すべて終了';
      failToast('終了できませんでした', 'もう一度「すべて終了」を押すか、黒い画面を閉じてください', e);
    });
  }
  function quit() {
    var b = $('#btnQuit');
    UIKit.confirmTwice(b, doQuit, 'もう一度押すと終了します');
  }
  /* 入口が止まるまで待つ: 応答があれば(エラーの応答 = e.status があるときも)まだ動いている。応答が無くなったら終わった */
  function waitGone(n) {
    function alive() {
      if (n < 40) setTimeout(function () { waitGone(n + 1); }, 700);
      else doneText('終了に時間がかかっています', '黒い画面が残っていれば、その画面を閉じてください。');
    }
    api('api/ping', 'GET', null, { timeout: 2000 }).then(alive, function (e) {
      if (e.status) { alive(); return; }
      doneText('すべて終了しました', 'この画面(タブ・窓)は閉じてかまいません。もう一度使うときは start.bat をダブルクリックしてください。');
    });
  }
  function doneText(title, text) { $('#doneTitle').textContent = title; $('#doneText').textContent = text + (quitNotice ? ' ' + quitNotice : ''); }

  /* ================================================================ 案件(配信ごと)の一覧 ================================================================ */

  function lsGet(k, d) { try { var v = localStorage.getItem('ytt.cases.' + k); return v === null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem('ytt.cases.' + k, v); } catch (e) { /* 保存できなくても動く */ } }

  function clipRow(c, kase) {
    var li = el('li', 'pt-clip');
    var head = el('div', 'row');
    head.appendChild(el('span', 'pt-clip-range mono', tc(c.start) + '–' + tc(c.end)));
    head.appendChild(el('span', 'grow', c.label || c.file || '(名前なし)'));
    if (c.file) {
      var fn = el('span', 'hint mono pt-clip-file', c.file);
      if (c.path) fn.title = c.path;
      head.appendChild(fn);
    }
    if (!c.exists) head.appendChild(el('span', 'pill warn', '動画が見つからない'));
    var auto = !!(c.auto && kase);   // 自動でできた切り抜き(札・失敗の文・採用 / 要らない は下の auto* が足す)
    if (auto) { li.classList.add('pt-ac'); li.setAttribute('data-fkey', 'auto:' + autoKey(kase, c)); autoPills(head, c); }
    li.appendChild(head);
    if (auto) autoFail(li, c);
    var st = el('div', 'row pt-clip-steps');
    if (c.transcript) {
      var t = c.transcript, done = CaseLink.txProgress(t) === 'proofed';
      st.appendChild(el('span', 'pill ' + (done ? 'ok' : 'info'), '文字起こし 校正 ' + t.proofed + '/' + t.segments + '行'));   // 校正の途中は動いているのではないので run(回る輪)にしない(M7)
    } else {
      st.appendChild(el('span', 'pill wait', '文字起こし まだ'));
    }
    if (c.pack) {
      var pill = el('span', 'pill ok');
      if (c.pack.textplus) pill.append(term('Text+', 'DaVinci Resolve のテロップ(字幕)機能'), ' パック ' + when(c.pack.updatedAt));
      else pill.textContent = 'パック ' + when(c.pack.updatedAt);
      st.appendChild(pill);
    } else {
      st.appendChild(el('span', 'pill wait', 'パック まだ'));
    }
    var open = null;
    if (c.transcript && c.transcript.id) open = link('校正で開く', docHref(c.transcript.id, '', 'proof', kase && kase.id));
    else if (c.exists && c.path && kase && c.markId) open = link('校正で開く', markHref(kase.id, c.markId));
    if (open) {
      st.appendChild(open);
    }
    li.appendChild(st);
    if (auto) autoActs(li, kase, c);
    return li;
  }

  function fillClips(node, c) {
    var ol = $('.pt-clips', node);
    ol.textContent = '';
    if (!c.clips.length) ol.appendChild(el('li', 'hint', c.marks.adopted ? '採用したマークはまだ書き出していません(スタジオで書き出すか、下の「まとめて実行」で)' : '書き出した切り抜きはありません'));
    c.clips.forEach(function (cl) { ol.appendChild(clipRow(cl, c)); });
  }

  /* ---- 自動でできた切り抜きの確認 ----
     .clip.json の出どころが自動(配信中の候補・配信後の解析)の切り抜きに「自動」の札・出どころ・点数・控え・届けた・失敗の文と、
     [採用](= 友人へ届ける。パックがあって、依頼の受付の Dropbox のフォルダが決まっているときだけ押せる。全自動の流れでは届けない = 人が確かめてから)・
     [要らない](ごみ箱フォルダへ移す + スタジオのマークを不採用に + 誤検出として記録)を出す。どちらも二度押し(UIKit.confirmTwice)。
     中身はサーバー(/api/cases/auto = src/manage/cases/cases.py の auto_review)。届けている途中の進み具合は api/ytt/deliver の status で聞き直す */
  var ORIGIN_TITLE = { auto: '配信中に盛り上がりを見つけて、自動で採用した候補から作った切り抜きです',
    archive: '配信のあとでアーカイブを解析して、自動で採用した候補から作った切り抜きです' };
  var AUTO_NONE = { total: 0 };   // 自動の切り抜きの数(配信ごとの autoClips)が無いとき
  var deliverJobs = {};          // 案件の id/マークの id → {msg}(届けている途中。一覧を描き直しても出し続ける)
  var deliverFolder = null;      // 依頼の受付の Dropbox のフォルダが決まっているか(null = まだ分からない = 押せる。決まっていなければサーバーが理由を返す)
  function autoKey(kase, cl) { return kase.id + '/' + cl.markId; }
  function iconBtn(icon, label, cls) {
    var b = el('button', 'btn small ' + cls);
    b.type = 'button';
    b.innerHTML = UIKit.icon(icon);   // 決まった SVG の文字列だけ(画面のデータは入れない)
    b.appendChild(document.createTextNode(label));
    return b;
  }
  function autoPills(head, cl) {
    var a = cl.auto, rv = cl.review || {}, p = el('span', 'pill accent pt-ac-pill', '自動');
    p.title = (ORIGIN_TITLE[a.origin] || '自動で採用した候補から作った切り抜きです') + '。字幕は校正前のたたき台です';
    head.appendChild(p);
    head.appendChild(el('span', 'hint pt-ac-origin', (a.originLabel || '') + (a.score != null ? ' ・ 点数 ' + Number(a.score).toFixed(2) : '')));
    if (a.bench) {
      var b = el('span', 'pill warn pt-ac-bench', '控え');
      b.title = '1 時間の枠から外れた候補です(書き出し済みなので取り消していません。要らなければ「要らない」で片付けます)';
      head.appendChild(b);
    }
    if (rv.deliveredAt) {
      var s = el('span', 'pill ok pt-ac-done', '届けた ' + ago(rv.deliveredAt));
      s.title = 'Dropbox の 出力 に置きました' + (rv.delivered ? ': ' + rv.delivered : '');
      head.appendChild(s);
    }
  }
  /* 失敗の文(「調子」・スタジオの LIVE の帯と同じ文 = src/flow/live_failures.py の failure_of) */
  function autoFail(li, cl) {
    var f = (cl.review || {}).failure;
    if (!f) return;
    var row = el('div', 'row pt-ac-fail'), p = el('span', 'pill err', '失敗');
    p.title = f.kindLabel || '';
    row.appendChild(p);
    row.appendChild(el('span', 'hint grow', f.text || ''));
    li.appendChild(row);
  }
  function deliverWhy(cl) {
    if (!cl.pack) return 'パックがまだありません(文字起こし → パックが済むと届けられます)';
    if (deliverFolder === false) return '届ける先が決まっていません(下の「依頼の受付」で Dropbox のフォルダを決めると届けられます)';
    return '';
  }
  function autoActs(li, kase, cl) {
    var rv = cl.review || {}, k = autoKey(kase, cl), dj = deliverJobs[k];
    var row = el('div', 'row pt-ac-acts'), msg = el('span', 'hint grow pt-ac-msg');
    msg.id = 'pt-ac-msg-' + kase.id + '-' + cl.markId;
    msg.setAttribute('aria-live', 'polite');
    if (!rv.deliveredAt) {   // 届けたあとは札(届けた)だけ。二度は届けない(直した版は「編集」の 3 パック から)
      var ok = iconBtn('check', '採用(友人へ届ける)', 'pt-ac-deliver'), why = dj ? '届けている途中です' : deliverWhy(cl);
      ok.disabled = !!why;
      ok.title = why || 'パックを zip にして Dropbox の 出力 に置きます(友人のアプリの「受け取る」に出ます。字幕は校正前のたたき台です)';
      ok.setAttribute('aria-describedby', msg.id);
      ok.addEventListener('click', function () { UIKit.confirmTwice(ok, function () { autoDeliver(kase, cl); }, 'もう一度押すと届けます'); });   // 二度押しの確認(ブラウザの confirm は使わない)
      row.appendChild(ok);
      msg.textContent = dj ? dj.msg : why;
    }
    var no = iconBtn('trash', '要らない', 'danger pt-ac-discard');
    no.disabled = !!dj;
    no.title = dj ? '届けている途中です(終わってから押せます)' : 'パック・切り抜きの動画を ごみ箱フォルダ へ移し(3 日で消えます)、スタジオのマークを不採用にして、誤検出として記録します';
    no.addEventListener('click', function () { UIKit.confirmTwice(no, function () { autoDiscard(kase, cl, no); }, 'もう一度押すとごみ箱へ'); });
    row.appendChild(no);
    row.appendChild(msg);
    li.appendChild(row);
  }
  /* 案件の行の切り抜きだけを描き直す(押したボタンが消えても、同じ切り抜きの次の操作へフォーカスを移す) */
  function repaintClips(caseId) {
    var node = document.getElementById('case-' + caseId), c = caseById(caseId);
    if (!node || !c) return;
    var a = document.activeElement, row = a && a.closest ? a.closest('.pt-clip[data-fkey]') : null;
    var key = row && node.contains(row) ? row.getAttribute('data-fkey') : null;
    fillClips(node, c);
    var r = key && rowByKey(key), t = r && r.querySelector('button:not([disabled]), a[href]');
    if (t) t.focus({ preventScroll: true });
  }
  function paintDeliverMsg(k) {
    var r = rowByKey('auto:' + k), m = r && $('.pt-ac-msg', r);
    if (m) m.textContent = deliverJobs[k] ? deliverJobs[k].msg : '';
  }
  function autoDeliver(kase, cl) {
    var k = autoKey(kase, cl);
    deliverJobs[k] = { msg: 'zip にしています…' };
    repaintClips(kase.id);
    api('api/cases/auto', 'POST', { op: 'deliver', id: kase.id, markId: cl.markId }).then(function (r) {
      followDeliver(kase, cl, r.job, 0);
    }, function (e) {
      delete deliverJobs[k];
      repaintClips(kase.id);
      failToast('届けられませんでした', '理由を確かめてから、もう一度「採用」を押してください', e);
    });
  }
  function followDeliver(kase, cl, j, errs) {
    var k = autoKey(kase, cl);
    if (j && j.state === 'running') {
      deliverJobs[k] = { msg: (j.message || 'zip にしています') + '…' + (j.progress ? ' ' + Math.round(j.progress * 100) + '%' : '') };
      paintDeliverMsg(k);
      setTimeout(function () {
        api('api/ytt/deliver', 'POST', { op: 'status', job: j.id }).then(function (r) { followDeliver(kase, cl, r.job, 0); },
          function (e) { if (errs < 5) followDeliver(kase, cl, j, errs + 1); else { delete deliverJobs[k]; failToast('届けた結果を確かめられませんでした', '一覧を読み込み直してください', e); refreshCases(); } });
      }, 800);
      return;
    }
    delete deliverJobs[k];
    if (j && j.state === 'done') toast('友人へ届けました(Dropbox の 出力 に ' + (j.name || 'zip') + ' を置きました)', 'ok');
    else failToast('届けられませんでした', 'もう一度「採用」を押してください', { reason: (j && j.message) || '' });
    afterAutoAction(kase.id);
  }
  /* 片付けられたかを返す */
  function autoDiscard(kase, cl, btn) {
    if (btn) btn.disabled = true;
    return api('api/cases/auto', 'POST', { op: 'discard', id: kase.id, markId: cl.markId }).then(function (r) {
      UIKit.toast('ごみ箱フォルダへ移して、スタジオのマークを不採用にしました(3 日で消えます)', { kind: 'ok', detail: r.trash || '' });
      var h = hideApi(); if (h) h.load(true);   // その文字起こしを非表示にしたので、覚えている非表示を読み直す
      afterAutoAction(kase.id);
      return true;
    }, function (e) {
      if (btn) btn.disabled = false;
      failToast('片付けられませんでした', 'ファイルを開いているアプリを閉じてから、もう一度「要らない」を押してください', e);
      return false;
    });
  }
  /* 採用・要らないのあと: 一覧を読み直して、同じ配信の次の自動の切り抜き → 配信の行 → 絞り込みの欄 の順にフォーカスを移す(押したボタンが消えるため)。 */
  function afterAutoAction(caseId) {
    return refreshCases().then(function () {
      var node = document.getElementById('case-' + caseId);
      var t = (node && node.open && node.querySelector('.pt-ac button:not([disabled])')) || (node && $('.pt-case-row', node)) || $('#fText');
      if (t) t.focus({ preventScroll: true });
    });
  }
  function paintCaseAuto(node, c) {
    var p = $('.pt-case-autopill', node), a = c.autoClips || AUTO_NONE;
    p.hidden = !a.total;
    if (!a.total) return;
    p.className = 'pill pt-case-autopill wait';
    p.textContent = '自動 ' + a.total + '本';
    p.title = '自動でできた切り抜き ' + a.total + '本。行を開くと、採用(友人へ届ける)・要らない を選べます';
  }

  var active = UIKit.autorun.isActive;

  /* スタジオから消えた配信(c.gone): まとめて実行に要るマークがスタジオに無い。欄は隠さずに押せなくして、理由と戻し方を出す(S-25) */
  function goneAuto(box, c) {
    $all('select, input, button', box).forEach(function (x) { x.disabled = true; });
    var why = $('.pt-auto-why', box), run = $('.pt-auto-run', box);
    why.id = 'pt-auto-why-' + c.id;
    why.hidden = false;
    why.textContent = 'スタジオから消えた配信なので、まとめて実行は使えません(書き出し・文字起こしに要るマークが、スタジオにありません)。' +
      'スタジオに同じ配信を入れ直すと、また使えます。' + ((c.clips || []).some(function (x) { return x.exists; }) ? '残っている切り抜きは、上の「編集で開く」から開けます。' : '');
    run.setAttribute('aria-describedby', why.id);
    run.title = 'スタジオから消えた配信なので使えません';
  }
  /* 実行を押したら中止へフォーカスを移す(押したボタンが押せなくなってフォーカスが消えないように。S-24)。行は作り直されていることがあるので id で引く */
  function focusCancel(id) {
    var n = document.getElementById('case-' + id), b = n && $('.pt-auto-cancel', n);
    if (b && !b.hidden) b.focus();
  }

  /* 友人へ自動で送る(いつも出す = まとめて実行は解析から全部だけ。受付のフォルダが無いと画面が知っているときだけ注を出す = 知らなければ出さない) */
  function sendFolderMissing() { return !!intakeData && !intakeData.folder; }
  /* 友人へ自動で送る届け先(受付のフォルダの 出力。GET api/intake の outDir)。まだ読んでいなければ読む。決まっていなければ null(D-SEND・RV A1) */
  function sendOutDir() {
    if (intakeData) return Promise.resolve(intakeData.outDir || null);
    return api('api/intake').then(function (d) { return (d && d.outDir) || null; }, function () { return null; });
  }
  function paintSendBox(box) {
    $('.pt-auto-sendnote', box).hidden = !sendFolderMissing();
  }
  function wireAuto(node, c) {
    var box = $('.pt-auto', node), top = $('.pt-auto-top', box), who = $('.pt-auto-streamer', box);
    if (c.gone) { goneAuto(box, c); return; }
    box.setAttribute('data-auto-send', '');   // 友人へ自動で送る の注を付け直す対象(まとめて実行を配線した箱だけ)
    var send = $('.pt-auto-send', box);
    send.checked = true;   // 描くたびにオン(前回の値は覚えない = 3-47)
    var ar = UIKit.autorun, sync = function () { paintSendBox(box); };
    /* 採用数・上書きはホームの設定(UIKit.autorun = どの入口で変えても同じ。気が利く画面へ 段4)。まとめて実行の形は解析から全部だけ(10-19 ユーザー決定:
       人が採用した配信にも自動の上位で採用する数まで足す。人が選んだ 1 本だけは案件の画面の候補のマークの行の「この後を」)。配信者・採用数の欄の Enter で実行(S-24) */
    ar.form({ who: who, top: top, panel: $('.pt-auto-panel', box), kind: 'video', run: $('.pt-auto-run', box), onLoad: sync });
    var draft = draftFor(c.id);
    if (draft.streamer != null) { who.value = draft.streamer; who.dispatchEvent(new Event('input')); }   // 未保存の入力を再描画でも保つ(E2 finding 1)
    else UIKit.streamer.autoFill(who, { videoId: c.id, channel: c.channel || '' });   // 覚えた名前 → チャンネル名から(段5)
    who.addEventListener('input', function () { draftFor(c.id).streamer = who.value; });
    sync();
    $('.pt-auto-run', box).addEventListener('click', function () {
      var st = ar.state();
      /* 欄 → 封筒 + 束の差分(UIKit.flow.order = ② の口 api/flow/submit の本文。RV A1)。解析から全部 = 頭からパックまで */
      var f = { kind: 'url', videoId: c.id, title: c.title || '', upto: 'pack', repack: !!(st && st.overwrite), top: ar.topOf(top) };
      var chk = UIKit.streamer.check(who);
      chk.then(function (name) {
        if (name === null) return null;   // 見つからない名前で「やめる」を選んだ
        f.streamer = name;   // 欄の名前(空 = 色なし。欄は自動で入るので、空は「色なし」の意味)
        // 友人へ自動で送る(D-SEND 案 B3): 依頼の受付のフォルダが決まっていれば出どころ auto。チェックが入っていれば届け先も置く。
        // 外した = 届け先なし(送らず、送らなかった記録が残る = 品質のカード 2-8)
        return sendOutDir().then(function (out) {
          if (out) f.deliver = { origin: 'auto', dir: send.checked ? out : null };
          var order = UIKit.flow.order(f);
          // 先に見積もる: やることが無いなら、理由だけでなく次の一手(スタジオで候補を確認する など)を押せる形で知らせる(M2)
          return api('api/flow/estimate', 'POST', order).catch(function () { return null; }).then(function (est) {
            if (est && est.nothing) { nothingToDo(c, est.reason); return null; }
            return ar.start([order]);
          });
        });
      }).then(function (r) {
        if (!r) return;   // やることが無い(見積もり。知らせは上の nothingToDo)
        runsByVideo[c.id] = r.run; node.open = true; renderAuto(node, c.id); focusCancel(c.id); pollAuto();
      }).catch(function (e) { failToast('まとめて実行を始められませんでした', 'もう一度「実行」を押してください', e); });
    });
    $('.pt-auto-cancel', box).addEventListener('click', function () {
      var r = runsByVideo[c.id]; if (!r) return;
      api('api/flow/cancel', 'POST', { id: 'run:' + r.id }).then(function () { pollAuto(); })   // 掲示板の id(RV A1)。止まったかは定期の読み込みで
        .catch(function (e) { failToast('中止できませんでした', 'もう一度「中止」を押してください', e); });
    });
    renderAuto(node, c.id);
  }
  /* 「実行」を押したが、やることが無かったとき(M2): 理由 + 次の一歩 + その画面へ行くボタン */
  function nothingToDo(c, reason) {
    var cand = (c.marks && c.marks.candidates) || 0, adopted = (c.marks && c.marks.adopted) || 0, exported = (c.marks && c.marks.exported) || 0;
    var next = '', act = null;
    if (!c.gone && (cand || adopted || exported)) {   // 解析から全部は人の採用 + 自動の上位まで済んでいる。人が選んだ 1 本は候補のタブのマークの行の「この後を」
      next = '。人が選んだマークだけを進めるときは、案件の画面の候補のマークの行の「この後を」を使います'; act = { label: '候補の確認へ', href: studioHref(c.id) };
    } else if (!c.gone) { act = { label: '案件の画面で開く', href: studioHref(c.id) }; }
    var opt = { kind: 'info', ms: 12000 };
    if (act) opt.action = { label: act.label, fn: function () { location.href = act.href; } };   // 同じ窓で移る(S-15)
    UIKit.toast('やることがありません: ' + (reason || '済んでいます') + next, opt);
  }
  function runLabel(r) { return UIKit.autorun.runLabel(r); }   // 状態の言葉は1か所(何もしなかったら「完了」と言わない)
  function ago(ms) { return UIKit.fmt.ago(ms); }   // 「3分前」「昨日 12:34」(無ければ '')
  /* 止まった理由(失敗 = エラーの文・中止 = 「入口を終了しました」など)。済みなら空 */
  function runReason(r) { return r.error || (r.state === 'cancelled' && r.message ? r.message : ''); }
  /* 前回の結果の1行(記録のファイルから。段2 B-6): 「前回 解析から全部: 失敗 ・ 理由(3日前)」(古い記録の札もそのまま出す) */
  function pastText(p) {
    var why = runReason(p);
    return '前回 ' + (p.modeLabel || '') + ': ' + runLabel(p) + (why ? ' ・ ' + why : '') + (p.finished ? '(' + ago(p.finished) + ')' : '');
  }
  function renderAuto(node, id) {
    var box = $('.pt-auto', node); if (!box) return;
    var r = runsByVideo[id], past = r ? null : pastByVideo[id], ol = $('.pt-auto-steps', box), msg = $('.pt-auto-msg', box);
    var run = $('.pt-auto-run', box), cancel = $('.pt-auto-cancel', box), cancelFocused = document.activeElement === cancel;
    run.disabled = active(r) || node.dataset.gone === '1';   // スタジオから消えた配信は押せないまま(S-25)
    cancel.hidden = !active(r);
    if (cancelFocused && cancel.hidden && !run.disabled) run.focus();   // 終わった・中止した: フォーカスを実行へ戻す(S-24)
    ol.textContent = ''; msg.textContent = '';
    var x = r || past;
    if (!x) return;
    (x.steps || []).forEach(function (st) {   // 段の札は前回の分も出す
      var li = el('li', 'pt-auto-step');
      li.appendChild(el('span', 'pill ' + (STEP_PILL[st.state] || 'wait'), st.label + ' ' + UIKit.autorun.stepLabel(st)));
      if (st.detail) li.appendChild(el('span', 'hint', st.detail));
      ol.appendChild(li);
    });
    if (past) { msg.textContent = pastText(past); return; }
    msg.textContent = r.modeLabel + ': ' + runLabel(r) + (r.error ? ' ・ ' + r.error : '') + (r.finished ? '(' + when(r.finished) + ')' : '');
  }

  /* 編集で文書を開くリンク。文書 ID で開く(B-1: 動画のパスだと、同じ動画から作った別の文書 = いちばん新しい文書が開いていた)。
     パスは文書が見つからなかったときの予備(編集の takeUrlParams が ?doc= を先に見る) */
  /* 行き先は案件の画面(/cases。URL の形は caselink.js の 1 か所)。文書 ID だけで開ける(殻が ④ に ?doc= で案件を聞く)。
     case を渡せば案件も決まる(仮の案件 eval・orphan・動画ファイルの案件を開くとき) */
  function docHref(id, path, tab, caseId) { return CaseLink.href({ c: caseId, d: id, tab: tab }); }
  /* その配信を案件の画面の候補で開く(案件の id = スタジオの配信の id。B-8) */
  function studioHref(id) { return CaseLink.href({ c: id, tab: 'cand' }); }
  /* 文字起こしがまだの切り抜きは、マーク id で校正の欄を開く(殻が ?m= を受ける) */
  function markHref(caseId, markId) { return CaseLink.href({ c: caseId, m: markId, tab: 'proof' }); }

  /* 依頼の内容(誰の・何を): その配信の最後のまとめて実行(この起動の実行か前回の結果)。無ければ自動の切り抜きの出どころ */
  function whoOf(r) { return r.requestId ? '友人の依頼' : '自分'; }
  function requestText(c) {
    var r = runsByVideo[c.id] || pastByVideo[c.id];
    if (r) return whoOf(r) + ' ・ ' + (r.modeLabel || '');
    var a = (c.clips || []).filter(function (cl) { return cl.auto; })[0];
    return a ? '自動(' + (a.auto.originLabel || '自動の候補') + ')' : '依頼の記録なし';
  }
  function caseSubText(c) {
    var parts = [c.channel || '(配信者不明)'];
    if (c.streamedAt) parts.push(ago(c.streamedAt));
    if (c.gone) parts.push('スタジオから消えた配信(最後に見えた内容)');
    parts.push(requestText(c));
    return parts.filter(Boolean).join(' ・ ');
  }
  function txSummaryText(t) {
    if (!t || !t.clips) return '';
    if (!t.withTranscript) return '文字起こし まだ';
    var base = '校正 ' + t.proofed + '/' + t.segments + '行';
    var missing = t.clips - t.withTranscript;
    return missing ? base + '(未着手 ' + missing + '本)' : base;
  }
  function packSummaryText(p) {
    if (!p || !p.total) return '';
    if (!p.have) return 'パック まだ';
    return p.have === p.total ? 'パック 済み(' + p.have + '本)' : 'パック ' + p.have + '/' + p.total;
  }

  function caseCard(c) {
    var node = $('#tplCase').content.firstElementChild.cloneNode(true);
    node.dataset.id = c.id;
    node.id = 'case-' + c.id;
    node.setAttribute('data-fkey', 'cases:' + c.id);
    $('.pt-case-title', node).textContent = c.title || c.id;
    $('.pt-case-sub', node).textContent = caseSubText(c);
    var cn = $('.pt-case-clips', node), cnt = c.marks && c.marks.exported ? '切り抜き ' + c.marks.exported + '本' : '切り抜き なし';
    cn.hidden = false; cn.textContent = cnt;
    var tx = $('.pt-case-tx', node), txt = txSummaryText(c.tx);
    tx.hidden = !txt; tx.textContent = txt;
    var pk = $('.pt-case-pack', node), pkt = packSummaryText(c.packs);
    pk.hidden = !pkt; pk.textContent = pkt;
    var fl = $('.pt-case-failed', node);
    fl.hidden = !c.failed; fl.textContent = '失敗 ' + (c.failed || 0);
    fl.title = '失敗した切り抜き ' + (c.failed || 0) + ' 本(行を開くと理由が出ます)';
    paintCaseAuto(node, c);
    if (c.gone) node.dataset.gone = '1';
    markHid(node, 'cases', c.id, $('.pt-case-main', node));

    // 自分で開閉した通り(まだ触っていない行は閉じたまま。実行中の進み具合は「処理の状況」が見せる)
    node.open = !!openCases[c.id];
    $('.pt-case-row', node).addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('a[href], button')) return;   // 行の中のボタンは行を開閉しない
      setTimeout(function () { openCases[c.id] = node.open; }, 0);
    });

    // RS8 C3: その配信を案件の画面で開く(案件の id = スタジオの配信の id。B-8)。スタジオから消えた配信は候補を開けないので、校正・パックのタブへ
    $('.pt-case-studio', node).appendChild(link('案件の画面で開く', CaseLink.href({ c: c.id, tab: c.gone ? 'proof' : 'cand' })));
    if (hideApi()) $('.pt-case-studio', node).parentNode.appendChild(hideBtn('cases', c.id, c.title || c.id));
    fillClips(node, c);
    wireAuto(node, c);
    return node;
  }

  /* ---- 案件の一覧から ID で引く ---- */
  function caseById(id) {
    var list = (casesData && casesData.cases) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }


  /* noHide: 非表示かどうかを見ない(「非表示 n件を表示」の数を数えるため)。実行中の案件は隠していても出す */
  function visible(c, noHide) {
    if (!noHide && isHid('cases', c.id) && !showHid('cases') && !active(runsByVideo[c.id])) return false;
    var q = $('#fText').value.trim().toLowerCase();
    if (q && ((c.title || '') + ' ' + (c.channel || '')).toLowerCase().indexOf(q) < 0) return false;
    return true;
  }
  function sortList(list) {
    var key = $('#fSort').value;
    if (key === 'channel') list.sort(function (a, b) { return (a.channel || '').localeCompare(b.channel || '', 'ja') || (a.title || '').localeCompare(b.title || '', 'ja'); });
    else if (key === 'title') list.sort(function (a, b) { return (a.title || '').localeCompare(b.title || '', 'ja'); });
    else list.sort(function (a, b) { return (b.streamedAt || 0) - (a.streamedAt || 0); });
  }

  /* 再描画で入力中のフォーカス・カーソル位置を失わないように、一覧を作り直す前後で保つ(E2 finding 1:
     alt-tab で戻ったときの refreshCases → render で、行の中で入力中だったフォーカスが消えるため) */
  function captureFocus(container) {
    var a = document.activeElement;
    if (!a || !container || !container.contains(a)) return null;
    var card = a.closest ? a.closest('.pt-case') : null;
    if (!card) return null;
    var role = a.classList.contains('pt-auto-streamer') ? 'streamer'
      : a.classList.contains('pt-auto-cancel') ? 'cancel' : a.classList.contains('pt-auto-run') ? 'run' : null;
    if (!role) return null;
    var info = { id: card.dataset.id, role: role };
    if (typeof a.selectionStart === 'number') { info.selStart = a.selectionStart; info.selEnd = a.selectionEnd; }
    return info;
  }
  function restoreFocus(info) {
    if (!info) return;
    var card = document.getElementById('case-' + info.id);
    if (!card) return;
    var sel = { streamer: '.pt-auto-streamer', cancel: '.pt-auto-cancel', run: '.pt-auto-run' }[info.role];
    var target = $(sel, card);
    if (target && info.role === 'cancel' && target.hidden) target = $('.pt-auto-run', card);   // 作り直す間に終わっていたら実行へ(S-24)
    if (!target) return;
    // 行の中を操作していた = 行(とまとまり)は開いていた。閉じたままだとフォーカスを戻せない(まとめて実行が終わって作り直したときなど)
    openCases[info.id] = true;
    for (var n = card; n; n = n.parentElement) { if (n.tagName === 'DETAILS') n.open = true; }
    target.focus({ preventScroll: true });
    if (info.selStart != null && target.setSelectionRange) { try { target.setSelectionRange(info.selStart, info.selEnd); } catch (e) { /* select 等は対象外 */ } }
  }

  function render() {
    if (!casesData) return;
    var focusInfo = captureFocus($('#list'));
    var full = casesData.cases.filter(visible);
    sortList(full);
    var totalCount = full.length;
    var shown = full.slice(0, Math.max(0, visibleCount));

    var list = $('#list');
    list.textContent = '';
    if (!shown.length) {
      list.appendChild(casesData.cases.length ? emptyFiltered() : emptyCases());
    } else {
      shown.forEach(function (c) { list.appendChild(caseCard(c)); });
    }

    var narrowed = $('#fText').value.trim();
    paintCount('#count', '#moreBox', '#btnMore', narrowed, totalCount, casesData.cases.length, shown.length);
    hideToggle('#casesHidden', 'cases', casesData.cases.filter(function (c) { return visible(c, true) && isHid('cases', c.id) && !active(runsByVideo[c.id]); }).length);
    restoreFocus(focusInfo);
    updateSummaryLine();
    renderVirtual();
  }
  /* 配信のない案件(RS8 C3。brief 3-3・3-4): 動画ファイルの案件・評価用・どの案件にも入らない文字起こし。④ の virtual をそのまま並べ、押すと案件の画面で開く。
     まとめて実行は持たない(配信の案件だけ)ので、展開しない 1 行。題名の絞り込みには従う */
  var VKIND = { file: '動画ファイルの案件', 'eval': '評価用(精度を測るための文書)', orphan: 'どの案件にも入らない文字起こし' };
  function renderVirtual() {
    var box = $('#vlistBox'), ul = $('#vlist'), q = $('#fText').value.trim().toLowerCase();
    var list = ((casesData && casesData.virtual) || []).filter(function (c) { return !q || (c.title || '').toLowerCase().indexOf(q) >= 0; });
    if (!casesData) list = [];
    ul.textContent = '';
    box.hidden = !list.length;
    list.forEach(function (c) {
      var li = el('li', 'pt-vrow'), a = el('a', 'pt-vrow-link');
      a.href = '/cases?c=' + encodeURIComponent(c.id) + '#proof';
      a.setAttribute('data-case', c.id);
      var main = el('span', 'pt-vrow-main');
      main.appendChild(el('span', 'pt-case-title ui-ell', c.title || c.id));
      main.appendChild(el('span', 'hint pt-case-sub ui-ell', VKIND[c.caseKind] || ''));
      a.appendChild(main);
      var n = (c.clips || []).length;
      a.appendChild(el('span', 'hint num', '文書 ' + n + ' 本'));
      var tx = txSummaryText(c.tx), pk = packSummaryText(c.packs);
      if (tx) a.appendChild(el('span', 'hint num', tx));
      if (pk) a.appendChild(el('span', 'hint num', pk));
      if (c.caseKind !== 'file') a.appendChild(el('span', 'pill wait', '仮の案件'));
      a.appendChild(el('span', 'ui-caret right', ''));
      li.appendChild(a);
      ul.appendChild(li);
    });
  }
  /* 一覧の件数の文と「もっと見る(あと n 件)」(案件・単体の文字起こし)。絞り込んだときは「合う数 / 全体の数」(分母は全体。
     「もっと見る」で隠れている分は「(m 件を表示)」と別に書く。S5) */
  function paintCount(countSel, moreBoxSel, moreBtnSel, narrowed, n, total, shownN) {
    var rest = n - shownN;
    $(moreBoxSel).hidden = rest <= 0;
    if (rest > 0) $(moreBtnSel).textContent = 'もっと見る(あと ' + rest + ' 件)';
    $(countSel).textContent = (narrowed ? n + ' / ' + total + ' 件' : n + ' 件') + (rest > 0 ? '(' + shownN + ' 件を表示)' : '');
  }
  function resetPaging() { visibleCount = PAGE_SIZE; render(); }
  /* 絞り込みで 0 件のとき(M5): 条件を消すボタン。条件が空なのに 0 件 = 全部が非表示 → 非表示を出すボタン */
  function emptyFiltered() {
    var filtered = $('#fText').value.trim();
    if (!filtered) {
      return emptyBox('表示できる配信はありません', 'すべて非表示にしています。「非表示のものも出す」と、また見られます。',
        { label: '非表示のものも出す', fn: function () { UIKit.hide.setShowing('cases', true); } });
    }
    return emptyBox('条件に合う配信はありません', '絞り込みを消すと、全部の配信が出ます。', { label: '絞り込みを消す', fn: function () {
      $('#fText').value = ''; resetPaging(); $('#fText').focus({ preventScroll: true });
    } });
  }
  /* 続きを出したあと、最初に増えた行へフォーカスを移す(ボタンが消えても、押した場所を失わない。M6) */
  function focusNewRow(sel, from) {
    var rows = $all(sel), r = rows[from] || rows[rows.length - 1], t = firstFocusable(r);
    if (t) t.focus({ preventScroll: false });
  }

  /* 配信が 1 本も無いときの空の表示(S-13): 2 文 + 次に押すボタン(新しい案件を始める・依頼の受付を設定する) */
  function emptyCases() {
    var box = el('div', 'empty pt-empty');
    box.appendChild(el('b', '', 'まだ配信はありません'));
    box.appendChild(document.createTextNode('「新しい案件」で配信を探して解析するか、友人からの依頼を受け付けると、ここに出ます。'));
    var row = el('div', 'row pt-empty-acts');
    var a = el('button', 'btn small primary', '新しい案件を始める');
    a.type = 'button'; a.id = 'emptyStudio'; a.title = '配信を探す・URL から入れる引き出しを開きます';
    a.addEventListener('click', function () { openNewCase(a); });
    row.appendChild(a);
    if (!$('#intakeBox').hidden) {   // 受付の無い古い入口では出さない
      var b = el('button', 'btn small', '依頼の受付を設定する');
      b.type = 'button'; b.id = 'emptyIntake';
      b.addEventListener('click', openIntakeSettings);
      row.appendChild(b);
    }
    box.appendChild(row);
    return box;
  }
  /* 受付・バックアップのパネルを開いて、オン/オフのスイッチへ(フォルダ・数の欄は設定の画面) */
  function openOps() { var o = $('#opsBox'); if (o) o.open = true; }
  function openSettingsBox(boxSel, switchSel) {
    var box = $(boxSel);
    openOps();
    box.open = true;
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    $(switchSel).focus({ preventScroll: true });
  }
  function openIntakeSettings() { openSettingsBox('#intakeBox', '#intakeEnabled'); }   // 「依頼を受け付ける」のスイッチ

  function updateSummaryLine() {
    if (!casesData) return;
    var hid = 0;
    casesData.cases.forEach(function (c) { if (isHid('cases', c.id)) hid++; });
    $('#summary').textContent = '配信 ' + casesData.cases.length + ' 本' +
      (hid ? ' ・ 非表示 ' + hid + ' 本' : '');
  }

  var casesLoadFailed = false;
  var casesSeq = 0;   // 案件の一覧の読みの連番(重なったとき、古い答えで新しい一覧を戻さない)
  function loadCases() {
    var my = ++casesSeq;
    return api('api/cases').then(function (j) { if (my !== casesSeq) return; casesLoadFailed = false; casesData = j; resetPaging(); }).catch(function (e) {
      if (my !== casesSeq) return;
      casesLoadFailed = true;
      if (casesData) { failToast('案件の一覧を読み直せませんでした', '「読み込み直す」を押してください', e); return; }   // 前の一覧は残す
      // 初めての読み込みの失敗(M9): 欄の中に「何が」+「どうすれば」の 2 文 + [読み込み直す](赤い帯は接続の文だけ)
      var list = $('#list'), box = emptyBox('案件の一覧を読めませんでした', failText('', 'もう一度「読み込み直す」を押してください。続くときは「すべて終了」→ start.bat で起動し直してください', e).replace(/^。/, ''),
        { label: '読み込み直す', fn: reloadAll });
      box.title = detailOf(e);
      list.textContent = '';
      list.appendChild(box);
      $('#moreBox').hidden = true; $('#count').textContent = ''; $('#summary').textContent = '';
      buildTodo();
    });
  }
  /* 案件の一覧・文字起こしの一覧を読み直す(ヘッダーの「読み込み直す」と、読めなかったときのボタン) */
  function reloadAll() {
    loadCheck();
    return loadCases().then(function () { renderDocs(); buildTodo(); if (!casesLoadFailed) toast('読み込み直しました'); });
  }
  function refreshCases() {
    // render() だけでなく、案件の一覧から組み立てる「次にやること」・「単体の文字起こし」も一緒に作り直す
    // (E2 finding 1: render() だけだと、alt-tab で戻ったときにこの2つが古いままになる)
    casesRevAt = Date.now();
    var my = ++casesSeq;
    return api('api/cases').then(function (j) { if (my !== casesSeq) return; casesLoadFailed = false; casesData = j; render(); renderDocs(); buildTodo(); }).catch(function () { /* 次の読み込みで直る */ });
  }

  function restoreFilters() {
    var so = lsGet('sort', 'new');
    if ($('#fSort').querySelector('option[value="' + so + '"]')) $('#fSort').value = so;   // 無くなった並び方(次にやることが多い順など)を覚えていたら新しい順
  }

  /* ================================================================ 単体の文字起こし(紐づかない文書) ================================================================ */

  /* 件数と「案件の画面で見る」の 1 行(一覧は案件の画面の「どの案件にも入らない文字起こし」) */
  function renderDocs() {
    var total = (casesData && casesData.unlinked && casesData.unlinked.length) || 0;
    $('#unlinkedHead').hidden = !total;
    if (total) $('#unlinkedCount').textContent = total + '件';   // ホームの数(txindex の unlinked)
  }

  /* ================================================================ 調子(段9 9-1。/api/health。数字は入口、良い/注意/悪い の判定はここ) ================================================================ */
  var GB = 1024 * 1024 * 1024;
  function fmtBytes(b) { b = Number(b) || 0; return b >= GB ? (b / GB).toFixed(b >= 10 * GB ? 0 : 1) + ' GB' : b >= 1048576 ? Math.round(b / 1048576) + ' MB' : b >= 1024 ? Math.round(b / 1024) + ' KB' : b + ' B'; }
  function fmtAgo(sec) { sec = Number(sec) || 0; return sec < 90 ? Math.round(sec) + ' 秒前' : sec < 5400 ? Math.round(sec / 60) + ' 分前' : sec < 172800 ? Math.round(sec / 3600) + ' 時間前' : Math.round(sec / 86400) + ' 日前'; }
  var healthBusy = false, healthTimer = 0;

  function loadHealth(refresh) {
    if (healthBusy) return;
    healthBusy = true;
    api('api/health' + (refresh ? '?refresh=1' : '')).then(function (h) {
      renderHealth(h);
      clearTimeout(healthTimer);
      if (h.computing) healthTimer = setTimeout(function () { loadHealth(false); }, 1500);   // 数えている途中: 少し待って読み直す
    }).catch(function (e) {
      var ul = $('#healthList'); ul.textContent = '';
      ul.appendChild(healthRow('bad', '調子を読めませんでした', '「数え直す」をもう一度押してください。続くときは「すべて終了」→ start.bat で起動し直してください', null, detailOf(e)));
    }).then(function () { healthBusy = false; });
  }
  /* 調子の 1 行。札の言葉は決まりの言葉(ok = 問題なし・warn = 注意・err = 要対応・info = 測った数字。S13)。
     subs の項目は文字か {text, title}。tip は行の title(開発者向けの細かい説明・pid・環境変数など。本文には出さない。S9) */
  var HEALTH_PILL = { ok: ['ok', '問題なし'], bad: ['err', '要対応'], warn: ['warn', '注意'], info: ['info', '測定'] };   // info = 良い・悪いを決めない数字(精度)
  function healthRow(state, title, text, subs, tip) {
    var p = HEALTH_PILL[state] || HEALTH_PILL.warn, li = el('li'), pill = el('span', 'pill ' + p[0], p[1]);
    var body = el('div', 'pt-health-body');
    body.appendChild(el('b', '', title));
    if (text) body.appendChild(el('span', 'hint', ' ' + text));
    if (subs && subs.length) {
      var ul = el('ul', 'pt-health-sub');
      subs.forEach(function (s) { var x = typeof s === 'object' && s ? s : { text: s }; var l = el('li', '', x.text); if (x.title) l.title = x.title; ul.appendChild(l); });
      body.appendChild(ul);
    }
    if (tip) li.title = tip;
    li.appendChild(pill); li.appendChild(body);
    return li;
  }
  /* 配信中の盛り上がりの検出の 1 行(検出がオンのときだけ h.live.detect がある): 動いているか・遅れ・チャット・起動し直しの数。
     失敗は「リアルタイム切り抜きの失敗」の一覧に kind detect で出る */
  var DETECT_CHAT = { ok: 'あり', restarting: '起動し直し中', none: 'なし(音だけ)', off: '使わない' };
  function detectHealthRow(dd) {
    var recs = dd.recordings || [], chat = function (c) { return DETECT_CHAT[c] || c; };
    var text = (dd.running ? (recs.length ? '録画 ' + recs.length + ' 本を見ています・遅れ ' + Math.round(dd.behindSec || 0) + ' 秒・チャット ' + chat(dd.chat)
      : '動いています(録画中の配信はありません)') : '止まっています' + (dd.message ? '(' + dd.message + ')' : ''))
      + '・ワーカーの起動し直し ' + (dd.restarts || 0) + ' 回' + (dd.autoAdopt ? '・自動の採用(' + dd.autoAdopt.waitMin + ' 分待ち)' : '');
    var row = healthRow(!dd.running || dd.error || (dd.restarts || 0) > 3 ? 'warn' : 'ok', '盛り上がりの検出', text,
      recs.map(function (x) { return x.id + ': 候補 ' + x.peaks + ' 本・遅れ ' + Math.round(x.behindSec || 0) + ' 秒・チャットの遅れ ' + (x.lag == null ? '—' : x.lag + ' 秒') + '・チャット ' + chat(x.chat); }));
    row.id = 'liveDetectHealth';
    return row;
  }
  /* 空き容量の判定(10 GB 未満 = 要対応・30 GB 未満 = 注意) */
  function diskState(freeBytes) { return freeBytes < 10 * GB ? 'bad' : freeBytes < 30 * GB ? 'warn' : 'ok'; }
  function renderHealth(h) {
    var ul = $('#healthList'); ul.textContent = '';
    $('#healthWhen').textContent = h.countedAt ? '大きさは ' + fmtAgo((Date.now() - h.countedAt) / 1000) + 'に数えた' + (h.computing ? '(数えています…)' : '') : (h.computing ? '数えています…' : '');
    // 版(期待 = ファイル、実際 = 動いている物)
    var bad = (h.versions || []).filter(function (v) { return !v.ok; });
    ul.appendChild(bad.length ? healthRow('bad', '版が違います', bad.map(function (v) { return v.name + '(動いているのは ' + v.version + '、ファイルは ' + v.expected + ')'; }).join('・') + '。「すべて終了」→ start.bat で起動し直してください')
      : healthRow('ok', '版', (h.versions || []).filter(function (v) { return v.version; }).map(function (v) { return v.name + ' ' + v.version; }).join('・') || '(まだ動いていません)'));
    // 文字起こしの処理(別のプロセスの「認識ワーカー」。プロセス番号は title へ。S9)
    var w = h.worker;
    ul.appendChild(!w ? healthRow('warn', '文字起こしの処理', '「編集」が動いていないか、状態を読めません')
      : w.alive ? healthRow('ok', '文字起こしの処理', '動いています' + (w.lastUsedAgo != null ? '(' + fmtAgo(w.lastUsedAgo) + 'に使った)' : '') + '。' + Math.round((w.silenceTimeoutSec || 0) / 60) + ' 分応答が無ければ止めます', null, '認識ワーカー(pid ' + w.pid + ')')
      : healthRow('ok', '文字起こしの処理', '止まっています(次の文字起こしで起動します。起動した回数 ' + (w.starts || 0) + ')', null, '認識ワーカー'));
    // 外部プログラム
    var t = h.tools;
    if (t) {
      var miss = ['ffmpeg', 'ffprobe', 'ytdlp'].filter(function (k) { return !(t[k] && t[k].path); });
      ul.appendChild(miss.length ? healthRow('bad', '外部プログラム', miss.map(function (k) { return k === 'ytdlp' ? 'yt-dlp' : k; }).join('・') + ' が見つかりません。インストールをやり直してください(setup の install.bat)', null, '場所を自分で指定するときは、環境変数 YTT_FFMPEG など(README)')
        : t.ytdlp.old ? healthRow('warn', '外部プログラム', 'yt-dlp が古い版です(今 ' + t.ytdlp.version + '・最新 ' + t.ytdlp.latest + ')。YouTube に断られやすくなるので、PowerShell で winget upgrade yt-dlp を流して新しくしてください', [t.ytdlp.path])
        : healthRow('ok', '外部プログラム', 'ffmpeg ' + t.ffmpeg.version + '・ffprobe ' + t.ffprobe.version + '・yt-dlp ' + t.ytdlp.version, [t.ffmpeg.path, t.ytdlp.path]));
    }
    // 空き容量
    (h.disk || []).forEach(function (d) {
      var st = diskState(d.freeBytes);
      ul.appendChild(healthRow(st, '空き容量 ' + (d.drive || d.path), fmtBytes(d.freeBytes) + ' / ' + fmtBytes(d.totalBytes) + (st !== 'ok' ? '。要らない動画を消して空きを作ってください' : ''), [d.path]));
    });
    // 作業データの大きさ
    if (h.data) {
      var subs = (h.data.dirs || []).map(function (d) {
        var top = (d.items || []).slice(0, 4).map(function (i) { return i.name + ' ' + fmtBytes(i.bytes); }).join('・');
        return d.label + ' ' + fmtBytes(d.bytes) + '(' + d.files + ' ファイル' + (top ? '。' + top : '') + ')';
      });
      ul.appendChild(healthRow(h.data.bytes > 50 * GB ? 'warn' : 'ok', '作業データ ' + fmtBytes(h.data.bytes), h.data.root ? h.data.root : '(各ツールのフォルダの中)', subs));
      // 作業データの外(書き出し先など)は別の行。注意の線は付けない(空き容量の行が警告する。opt-manage 8b-2)
      (h.data.outside || []).forEach(function (d) {
        var top = (d.items || []).slice(0, 6).map(function (i) { return i.name + ' ' + fmtBytes(i.bytes); });
        ul.appendChild(healthRow('ok', d.label + ' ' + fmtBytes(d.bytes), d.path, top));
      });
    } else ul.appendChild(healthRow('warn', '作業データ', '大きさを数えています…'));
    // エラーの件数
    var e = h.errors || {};
    ul.appendChild(healthRow(e.clientLast24h ? 'warn' : 'ok', '画面のエラー(24 時間)', (e.clientLast24h || 0) + ' 件', [e.clientLog]));
    // 自動の切り抜きの長さの目安(友人の区間からその場で数える = flow/lengthhint。使う ⇄ 使わないが切り替わったら分かるように。OPT-E2)
    if (h.lengthHint) ul.appendChild(healthRow(h.lengthHint.used ? 'ok' : 'info', '自動の切り抜きの長さ', h.lengthHint.text));
    // 異常終了(見張り役)。OS 側が増えたら PC の不安定、アプリ側だけならこのツールの不具合の目安
    var cr = h.crashes;
    if (!cr) ul.appendChild(healthRow('warn', '異常終了(7 日)', h.computing ? '数えています…' : '読めませんでした'));
    else if (!cr.events) ul.appendChild(healthRow('warn', '異常終了(7 日)', '読めませんでした(Windows のイベントログ)'));
    else {
      var co = cr.events.os, ca = cr.events.apps, wk = cr.tool;
      var appText = Object.keys(ca).filter(function (k) { return k !== 'total' && ca[k]; }).map(function (k) { return k + ' ' + ca[k]; }).join('・');
      var parts = ['OS ' + co.total + ' 件' + (co.total ? '(電源断 ' + co.kernelPower41 + '・予期しない終了 ' + co.unexpectedShutdown6008 + '・ハードのエラー ' + co.whea + ')' : ''),
        'アプリ ' + ca.total + ' 件' + (appText ? '(' + appText + ')' : '')];
      if (wk) parts.push('文字起こしの処理 ' + (wk.crashed + wk.hung) + ' 件' + (wk.crashed + wk.hung ? '(落ちた ' + wk.crashed + '・黙って強制終了 ' + wk.hung + ')' : ''));
      var none = !co.total && !ca.total && !(wk && wk.crashed + wk.hung);
      ul.appendChild(healthRow(co.total ? 'warn' : 'ok', '異常終了(7 日)', none ? 'なし'
        : co.total ? parts.join('。') + '。PC が不安定かもしれません(OS 側の異常終了はハードの目安。続くときは、文字起こしを速くする設定を遅い側に戻してください)' : parts.join('。')));
    }
    // リアルタイム切り抜き(線 D。オンのときだけ h.live がある): 録画元ごとにつながるか・置き場所と空き容量・録画中の本数
    if (h.live) (h.live.recorders || []).forEach(function (r) {
      if (!r.ok) { ul.appendChild(healthRow('bad', '録画元 ' + r.name, r.message || 'つながりません', [r.url])); return; }
      var lst = r.freeBytes == null ? 'warn' : diskState(r.freeBytes);
      var st = !r.folderOk || r.streamlink === false || (r.expected && r.version !== r.expected) ? 'bad' : lst;
      var text = (r.active ? '録画中 ' + r.active + ' 本' : '録画していません') + '・空き ' + (r.freeBytes != null ? fmtBytes(r.freeBytes) + ' / ' + fmtBytes(r.totalBytes) : '不明')
        + (r.expected && r.version !== r.expected ? '。版が違います(動いているのは ' + r.version + '、ファイルは ' + r.expected + '。録画中でなければ、ホームが 30 秒以内に起動し直します)' : '')
        + (r.streamlink === false ? '。streamlink が入っていません(setup/install.bat)' : '') + (r.folderMessage ? '。' + r.folderMessage : '');
      ul.appendChild(healthRow(st, '録画元 ' + r.name, text, [r.folder || '', r.url].concat((r.recordings || []).map(function (x) { return (x.title || x.id) + ' ' + x.state + (x.message ? '(' + x.message + ')' : ''); }))));
    });
    // リアルタイム切り抜きの空き容量(M4。書き出し先・パック・live\work。5 GB 未満で新しい書き出し・文字起こしを「空き待ち」・20 GB 未満で注意)
    if (h.live && h.live.disk) (h.live.disk.rows || []).forEach(function (r) {
      var st = r.state === 'low' ? 'bad' : r.state === 'warn' ? 'warn' : 'ok';
      var text = '空き ' + fmtBytes(r.freeBytes) + ' / ' + fmtBytes(r.totalBytes)
        + (r.state === 'low' ? '。' + Math.round(h.live.disk.lowBytes / GB) + ' GB を切ったので、新しい書き出し・文字起こしを止めて待っています(空くと続けます)'
          : r.state === 'warn' ? '。' + Math.round(h.live.disk.warnBytes / GB) + ' GB を切りました。片付けを考えてください' : '');
      var row = healthRow(st, 'リアルタイム切り抜きの空き ' + (r.label || '') + '(' + (r.drive || '') + ')', text, [r.path || '']);
      row.className = 'pt-live-disk';
      ul.appendChild(row);
    });
    // リアルタイム切り抜きの失敗(M3。書き出し・まとめて実行へ渡す・文字起こし・パック。文はスタジオの LIVE の帯と同じ = src/flow/live_failures.py)
    if (h.live && h.live.failures) {
      var lf = h.live.failures;
      var row = healthRow(lf.length ? 'warn' : 'ok', 'リアルタイム切り抜きの失敗(7 日)', lf.length ? lf.length + ' 件(新しい順。スタジオの LIVE の帯にも同じ文)' : 'なし',
        lf.map(function (x) { return x.text; }));
      row.id = 'liveFailures';
      ul.appendChild(row);
    }
    if (h.live && h.live.detect) ul.appendChild(detectHealthRow(h.live.detect));
    // 重い処理
    var hv = h.heavy;
    if (hv) ul.appendChild(healthRow('ok', '重い処理', '実行中 ' + (hv.active || []).length + '・順番待ち ' + (hv.waiting || []).length + '(同時に ' + hv.limit + ' まで)'));
    if (h.places) ul.appendChild(placesHealthRow(h.places));
    if (h.watch) watchHealthRows(h.watch).forEach(function (r) { ul.appendChild(r); });
    renderAccuracy(h.accuracy, ul);
  }
  /* 見張り(src/manage/ops/watch.py。10-23): 届けた切り抜きの元の配信が公開でなくなった(週 1 回)・ガイドラインの改定の日付が変わった(月 1 回) */
  function watchHealthRows(w) {
    var out = [], s = w.sources, t = w.terms;
    function day(ms) { var d = new Date(ms); return (d.getMonth() + 1) + '/' + d.getDate(); }
    if (s) {
      var ch = s.changed || [];
      if (ch.length) out.push(healthRow('warn', '元の配信', '届けた切り抜きの元の配信のうち ' + ch.length + ' 本が公開でなくなりました。投稿した切り抜きをどうするか確かめてください',
        ch.slice(0, 8).map(function (x) { return x.state + '(' + day(x.since) + 'に気づいた): ' + (x.title || x.videoId); })));
      else if (s.error) out.push(healthRow('warn', '元の配信', '見張れませんでした: ' + s.error));
      else out.push(healthRow('ok', '元の配信', '届けた切り抜きの元の配信 ' + (s.checked || 0) + ' 本は公開のままです(' + day(s.at * 1000) + 'に確かめた・週 1 回)'));
    }
    if (t) {
      if (t.changedAt) out.push(healthRow('warn', 'ガイドライン', '二次創作のガイドラインの改定の日付が変わりました(' + day(t.changedAt) + 'に気づいた)。読んで、決まりが変わっていないか確かめてください',
        ['今: ' + (t.mark || '?'), '前: ' + (t.prev || '?'), t.url || '']));
      else if (t.error) out.push(healthRow('warn', 'ガイドライン', t.error));
    }
    return out;
  }
  /* 置き場所の 1 行(src/manage/cases/outdirs.py の status): 案件のフォルダが見えない文書・配信の数と、書き出し先を変えて繋ぎ直した本数。出す物が無ければ出さない */
  function placesHealthRow(pl) {
    var subs = [], parts = [];
    Object.keys(pl.docReasons || {}).forEach(function (k) { subs.push('見えない理由: ' + k + ' ' + pl.docReasons[k] + ' 本'); });
    if (pl.docs) parts.push('案件のフォルダが見えない文書が ' + pl.docs + ' 本');
    if (pl.cases) parts.push('案件のフォルダが見えない配信が ' + pl.cases + ' 本');
    if (pl.relinked) subs.push('書き出し先を変えて繋ぎ直した案件 ' + pl.relinked + ' 本');
    var text = parts.join('・');
    if (text) text += '(ドライブがつながっているか確かめてください。動かしたなら py -3.12 src/manage/cases/outdirs.py --relink <配信の id> <フォルダ> で繋ぎ直せます)';
    var row = healthRow(parts.length ? 'warn' : 'ok', '置き場所', text || '案件のフォルダは見えています', subs);
    row.id = 'placesHealth';
    return row;
  }

  /* ---- 精度(Q3。src/eval/drill/accuracy.py): 領域ごとに「直近 x(前回 y)・日時・文書数」。手が空いた夜に 1 日 1 回測る。「今すぐ測る」はいつでも ---- */
  var accTimer = 0;
  function accPct(v) { return v == null ? '—' : (v * 100).toFixed(1) + '%'; }
  function accuracyRow(a) {
    var title = '精度 ' + a.label, l = a.latest;
    if (!l) return a.error ? healthRow('warn', title, '測れませんでした: ' + a.error) : healthRow('info', title, 'まだ測っていません(手が空いた夜に自動で測ります)');
    var s = l.summary || {}, p = a.prev && a.prev.summary;
    var parts = [(s.label || '') + ' ' + accPct(s.value) + (s.range ? '(95% の範囲 ' + accPct(s.range[0]) + '〜' + accPct(s.range[1]) + ')' : '')];
    if (p && p.value != null) parts.push('前回 ' + accPct(p.value));
    parts.push((s.unit || '文書') + ' ' + (s.docs || 0) + ' 本');
    parts.push(ago(l.at));
    var text = (s.few ? 'まだ少ない: ' : '') + parts.join('・') + (s.lowData && !s.few ? '(参考。データがまだ少ない)' : '');
    var subs = (s.extra || []).filter(function (x) { return x.value != null; }).map(function (x) {
      var pe = ((p && p.extra) || []).filter(function (y) { return y.label === x.label && y.value != null; })[0];
      return x.label + ' ' + accPct(x.value) + (pe ? '(前回 ' + accPct(pe.value) + ')' : '');
    });
    if (a.error) subs.push('最後の測定は失敗しました: ' + a.error);
    var row = healthRow(a.error ? 'warn' : 'info', title, text, subs);
    row.title = when(l.at) + ' に測った結果のファイル: ' + l.file;
    return row;
  }
  function renderAccuracy(ac, ul) {
    var btn = $('#btnAccuracyNow');
    if (!btn) return;
    clearTimeout(accTimer);
    btn.hidden = !ac;
    if (!ac) return;
    var live = ac.state === 'running' || (ac.forced && ac.state !== 'off');
    btn.disabled = !ac.enabled || live;
    btn.textContent = ac.state === 'running' ? '測っています…' : ac.forced && ac.enabled ? '手が空くのを待っています' : '精度を今すぐ測る';
    var win = '夜 ' + ac.nightFrom + '〜' + ac.nightTo + ' 時に手が空いていれば 1 日 1 回';
    ul.appendChild(healthRow('info', '精度の自動測定', ac.stateLabel + (ac.message ? '。' + ac.message : '') + (ac.enabled ? '(' + win + (ac.lastRun ? '・最後に ' + ago(ac.lastRun) : '') + ')' : '')));
    (ac.areas || []).forEach(function (a) { if (a.available || a.latest || a.error) ul.appendChild(accuracyRow(a)); });
    if (live) accTimer = setTimeout(function () { loadHealth(false); }, 2500);   // 測っている間・手が空くのを待っている間は軽く読み直す
  }
  /* 入口の条件(accuracy.py の GOALS = plan/README.md の 7): 各工程を始めてよい量の「今 / 目標 / あと」を 1 行ずつ。値は直近の測定のもの */
  function goalAmount(v, unit) { return unit === 'sec' ? String(+(v / 60).toFixed(1)) + ' 分' : Math.round(v) + ' ' + unit; }
  function goalPlain(s) {   // 計画の記号(G1・B4・I-2a など)は本文から外し、元の文は title に(S9)
    return String(s || '').replace(/\([A-Z]-\d+[a-z]?\)/g, '').replace(/(^|・)[A-Z]\d+(?:-[a-z])?\s+/g, '$1').replace(/^[A-Z]\d\s+/, '').trim();
  }
  function goalAmt(g, v) {   // 時間の目標は「時間」で並べる(分と時間が混ざって読み違えないように)
    return g.unit === 'sec' && g.target >= 3600 ? String(+(v / 3600).toFixed(2)) + ' 時間' : goalAmount(v, g.unit);
  }
  function goalsRow(goals) {
    var done = goals.filter(function (g) { return g.reached; }).length, unknown = goals.filter(function (g) { return g.now == null; }).length;
    var plain = goalPlain;
    var subs = goals.map(function (g) {
      var amt = function (v) { return goalAmt(g, v); };
      var body = g.now == null ? '未測定' : '今 ' + amt(g.now) + ' / 目標 ' + amt(g.target) + ' / ' + (g.reached ? '届いた' : 'あと ' + amt(g.left));
      return { text: plain(g.label) + ': ' + body + '(→ ' + plain(g.opens) + ')', title: g.label + ' → ' + g.opens };
    });
    var text = '届いた ' + done + ' / ' + goals.length + (unknown ? '・未測定 ' + unknown + '(道具が無いか、まだ測っていない。「精度を今すぐ測る」で測れます)' : '');
    var row = healthRow('info', '始める条件(あと何本・何分)', text, subs);
    row.id = 'accuracyGoals';
    return row;
  }
  /* ---- 確かめる(RS8 C3・V1 確かめる V3)----
     「今いちばん効く確認 + あと何本」は入口の GET api/check/next?n=0 の goal(確かめるの待ち行列が選ぶ。brief 2-1・2-3)。画面側で選び直さない。
     [始める] は /check へ(確かめるの画面)。すべての条件(今 / 目標 / あと)は畳んだ欄に(/api/accuracy の goals = 精度の自動測定の直近の結果) */
  /* 次に出す札が無いとき(今、確かめる物が 0 枚)も「いちばん効く確認」を出す: 入口が返す種類ごとの条件から、目標まであと少しの物 → まだ測っていない物 */
  function nearest(map) {
    var list = Object.keys(map || {}).map(function (k) { return map[k]; }).filter(function (g) { return g && !g.reached; });
    var known = list.filter(function (g) { return g.now != null && g.target > 0; });
    known.sort(function (a, b) { return (a.left / a.target) - (b.left / b.target); });
    return known[0] || list[0] || null;
  }
  function renderCheck(ac, nx) {
    var now = $('#checkNow'), sub = $('#checkSub'), list = $('#checkGoals'), start = $('#checkStart'), why = $('#checkWhy');
    if (!now) return;
    list.textContent = '';
    start.disabled = false; start.removeAttribute('title'); start.removeAttribute('data-ui-why'); why.textContent = '';
    var goals = (ac && ac.goals) || [];
    if (!ac && !nx) { now.textContent = '確かめる物を読み込めませんでした'; sub.textContent = '「読み込み直す」を押してください。続くときは運用の「調子」を見てください。'; return; }
    var done = goals.filter(function (g) { return g.reached; }).length, best = nx && (nx.goal || nearest(nx.goals));
    if (nx && nx.total != null) why.textContent = '確かめると効く物 ' + nx.total + ' 件';
    if (!best || best.reached) {
      if (!goals.length && !(nx && nx.total)) { now.textContent = 'まだ測っていません'; sub.textContent = '手が空いた夜に自動で測ります(運用の「調子」の「精度を今すぐ測る」でも測れます)。'; }
      else { now.textContent = 'どの確認も、目標に届いています'; sub.textContent = goals.length ? '届いた ' + done + ' / ' + goals.length + '。新しい確認が増えたら、ここに出ます。' : ''; }
    } else if (best.now == null) {
      now.textContent = goalPlain(best.label) + ': まだ測っていません';
      sub.textContent = '測ると「あと何本」が出ます(→ 届くと ' + goalPlain(best.opens) + ' を始められます)。届いた ' + done + ' / ' + goals.length;
    } else {
      now.textContent = goalPlain(best.label) + ': あと ' + goalAmt(best, best.left);
      sub.textContent = '今 ' + goalAmt(best, best.now) + ' / 目標 ' + goalAmt(best, best.target) + '(→ 届くと ' + goalPlain(best.opens) + ' を始められます)。届いた ' + done + ' / ' + goals.length;
    }
    now.title = best ? best.label + ' → ' + best.opens : '';
    if (goals.length) list.appendChild(goalsRow(goals));
  }
  function loadCheck() {
    var ac = null, nx = null;
    Promise.all([
      api('api/accuracy').then(function (j) { ac = j; }, function () { /* 条件の一覧だけ無い */ }),
      api('api/check/next?n=0').then(function (j) { nx = j; }, function () { /* 今いちばん効く確認だけ無い */ })
    ]).then(function () { renderCheck(ac, nx); });
  }
  function accuracyNow() {
    var btn = $('#btnAccuracyNow');
    btn.disabled = true;
    api('api/accuracy/run', 'POST', {}).then(function () { toast('精度の測定を受け付けました(手が空くまで待つことがあります)'); loadHealth(false); loadCheck(); },
      function (e) { failToast('精度を測れませんでした', '少し待って、もう一度押してください', e); loadHealth(false); });
  }

  /* ================================================================ 処理の状況 ================================================================
     まとめて実行の実行中(今の段・全体の進み)・待ち(順番)・失敗(その配信・文書の最後の実行が失敗 = 前回の起動の結果も。やり直して済めば消える)と、
     失敗の文がある自動の切り抜き(案件の一覧の failed。非表示の案件も出す = 失敗は見落とさない側)。採用・校正・パックの残りはここに出さない
     (案件の一覧の行の結果で読む)。押すと案件の行・案件の画面へ */
  function stepNow(r) {   // -> {label, at(1 から), total}
    var steps = r.steps || [], i;
    for (i = 0; i < steps.length; i++) if (steps[i].state === 'run') break;
    if (i >= steps.length) i = steps.filter(function (s) { return s.state === 'done' || s.state === 'skip'; }).length;
    return { label: (steps[i] || {}).label || '', at: Math.min(i + 1, steps.length), total: steps.length };
  }
  function failedStep(r) { var s = (r.steps || []).filter(function (x) { return x.state === 'error'; })[0]; return s ? s.label : ''; }
  function runTitle(r) { return r.title || (r.docId ? '文字起こし' : r.kind === 'file' ? '依頼の動画ファイル' : '配信'); }
  function statusItems() {
    var runs = [], fails = [];
    function add(r, href) {
      if (!r) return;
      if (active(r)) runs.push({ r: r, href: href });
      else if (r.state === 'error') fails.push({ r: r, href: href });
    }
    var known = {};
    ((casesData && casesData.cases) || []).forEach(function (c) { known[c.id] = true; });
    function vHref(id) { return known[id] ? '#case-' + id : '#intake'; }   // 依頼の解析は、案件の行がまだ無いことがある
    Object.keys(runsByVideo).forEach(function (id) { add(runsByVideo[id], vHref(id)); });
    Object.keys(runsByFile).forEach(function (id) { add(runsByFile[id], '#intake'); });
    Object.keys(runsByDoc).forEach(function (id) { add(runsByDoc[id], docHref(id, '', 'proof')); });
    Object.keys(pastByVideo).forEach(function (id) { if (!runsByVideo[id]) add(pastByVideo[id], vHref(id)); });
    Object.keys(pastByDoc).forEach(function (id) { if (!runsByDoc[id]) add(pastByDoc[id], docHref(id, '', 'proof')); });
    var queued = runs.filter(function (x) { return x.r.state === 'queued'; }).sort(function (a, b) { return (a.r.created || 0) - (b.r.created || 0); });
    var items = [];
    runs.filter(function (x) { return x.r.state === 'running'; }).forEach(function (x) {
      var r = x.r, st = stepNow(r), doneN = (r.steps || []).filter(function (s) { return s.state === 'done' || s.state === 'skip'; }).length;
      var pct = st.total ? Math.round(doneN / st.total * 100) : 0;
      items.push({ kind: 'running', title: runTitle(r), href: x.href, pillText: '実行中', pillClass: 'run', progress: pct,
        sub: whoOf(r) + ' ・ ' + r.modeLabel + ' ・ 今: ' + st.label + '(' + st.at + '/' + st.total + ' 段)・ 全体 ' + pct + '%' });
    });
    queued.forEach(function (x, i) {
      items.push({ kind: 'queued', title: runTitle(x.r), href: x.href, pillText: '待ち', pillClass: 'wait',
        sub: whoOf(x.r) + ' ・ ' + x.r.modeLabel + ' ・ 順番を待っています(' + (i + 1) + ' 番目)' });
    });
    fails.sort(function (a, b) { return (b.r.finished || 0) - (a.r.finished || 0); }).forEach(function (x) {
      var r = x.r, at = failedStep(r), why = runReason(r);
      items.push({ kind: 'failed', title: runTitle(r), href: x.href, pillText: '失敗', pillClass: 'err',
        sub: whoOf(r) + ' ・ ' + r.modeLabel + ' ・ ' + (at ? at + 'で失敗' : '失敗') + (why ? ': ' + why : '') + (r.finished ? '(' + ago(r.finished) + ')' : '') });
    });
    failedClipItems().forEach(function (it) { items.push(it); });
    return items;
  }
  /* 失敗の文がある自動の切り抜き(案件ごとに 1 行。動画ファイルの案件も。仮の案件 eval・orphan は含めない) */
  function failedClipItems() {
    if (!casesData) return [];
    var list = (casesData.cases || []).concat((casesData.virtual || []).filter(function (c) { return c.caseKind === 'file'; }));
    return list.filter(function (c) { return !c.gone && c.failed > 0; }).map(function (c) {
      var cl = (c.clips || []).filter(function (x) { return (x.review || {}).failure; })[0] || {}, f = (cl.review || {}).failure || {};
      var d = cl.transcript && cl.transcript.id ? cl.transcript.id : '';
      return { kind: 'failed', title: '自動の切り抜き ' + c.failed + ' 件', href: CaseLink.href({ c: c.id, d: d, tab: d ? 'proof' : 'cand' }), pillText: '失敗', pillClass: 'err',
        sub: (c.title || c.id) + ' ・ ' + (f.kindLabel ? f.kindLabel + 'で失敗' : '失敗') + (f.text ? ': ' + f.text : '') };
    });
  }

  function todoRow(it) {
    var li = $('#tplTodo').content.firstElementChild.cloneNode(true);
    if (it.key) li.setAttribute('data-fkey', 'todo:' + it.key);
    li.setAttribute('data-kind', it.kind || '');
    var a = $('.pt-todo-link', li);
    a.setAttribute('href', it.href);
    var pill = $('.pt-todo-pill', li);
    pill.className = 'pill pt-todo-pill ' + (it.pillClass || '');
    pill.textContent = it.pillText || '';
    var tt = $('.pt-todo-title', li), ts = $('.pt-todo-sub', li);
    tt.textContent = it.title || '';
    ts.textContent = it.sub || '';
    tt.title = it.title || '';   // 狭い幅で切れても全文が分かる(A-36)
    ts.title = it.sub || '';
    var prog = $('.pt-todo-prog', li);
    if (typeof it.progress === 'number') { prog.hidden = false; prog.style.setProperty('--p', it.progress + '%'); }
    return li;
  }
  function renderTodo(all) {
    var box = $('#todoList'), empty = $('#todoEmpty'), more = $('#todoMore');
    hideToggle('#todoHidden', 'todo', 0);
    box.textContent = '';
    if (!all.length) {
      empty.hidden = false;
      // casesData が無い(案件の一覧をまだ読めていない)ときは「無い」ではなく、読めていないと分かる文言にする(自動の切り抜きの失敗が数えられない)
      // 読み込みの途中(まだ答えが無い・失敗もしていない)は「読み込んでいます」(失敗の文を一瞬出さない)
      var loading = !casesData && !casesLoadFailed;
      $('b', empty).textContent = casesData ? 'いま動いている処理・待っている処理・失敗はありません' : loading ? '読み込んでいます…' : '案件の一覧を読み込めていません';
      $('#todoEmptyText').textContent = casesData ? 'まとめて実行や友人の依頼が始まると、ここに今の段と進み具合が出ます。' : loading ? '' : '案件の一覧の欄に、直し方が出ています(「読み込み直す」を押してください)。';
      more.hidden = true;
      return;
    }
    empty.hidden = true;
    var shown = todoShowAll ? all : all.slice(0, TODO_CAP);
    shown.forEach(function (it) { box.appendChild(todoRow(it)); });
    var rest = all.length - TODO_CAP;
    more.hidden = rest <= 0;
    more.textContent = todoShowAll ? '少なく表示' : 'すべて見る(あと ' + rest + ' 件)';
  }
  function buildTodo() { renderTodo(statusItems()); }   // casesData が無くても、まとめて実行の分は出せる

  /* ================================================================ まとめて実行の進み具合(配信・文書。共通の定期読み込み) ================================================================ */

  function pollAuto() {
    clearTimeout(autoTimer);
    api('api/flow/runs').then(function (j) {
      var latestV = {}, latestD = {}, latestF = {}, anyActive = false, finished = false;
      (j.runs || []).forEach(function (r) {
        if (r.kind === 'doc') { if (r.docId && !latestD[r.docId]) latestD[r.docId] = r; }
        else if (r.kind === 'file' || !r.videoId) latestF[r.id || ('f' + Object.keys(latestF).length)] = r;   // 依頼の文字起こしだけ(配信にも文書にも紐づかない)
        else if (!latestV[r.videoId]) latestV[r.videoId] = r;
      });
      /* 実行の種類ごとに: 動いているものがあるか(読む間隔)・前は動いていて今は終わったものがあるか(一覧を読み直す)。was はその種類の前回の状態 */
      function track(latest, was) {
        Object.keys(latest).forEach(function (id) {
          var on = active(latest[id]);
          if (on) anyActive = true;
          if (was[id] && !on) finished = true;   // 実行が終わった = 案件の表示を新しくする
          was[id] = on;
        });
      }
      track(latestF, wasActiveFile); track(latestV, wasActiveVideo); track(latestD, wasActiveDoc);
      runsByFile = latestF; runsByVideo = latestV; runsByDoc = latestD;
      var pastV = {}, pastD = {};   // 前回の結果(サーバーがこの起動の実行の無い配信・文書だけを返す。新しい順)
      (j.past || []).forEach(function (p) {
        if (p.kind === 'doc') { if (p.docId && !pastD[p.docId]) pastD[p.docId] = p; }
        else if (p.videoId && !pastV[p.videoId]) pastV[p.videoId] = p;
      });
      pastByVideo = pastV; pastByDoc = pastD;
      $all('#list .pt-case').forEach(function (node) {
        renderAuto(node, node.dataset.id);
        var c = caseById(node.dataset.id);
        if (c) $('.pt-case-sub', node).textContent = caseSubText(c);   // 依頼の内容は最後のまとめて実行から
      });
      pollIntake();   // 依頼の受付も同じ周期で読む(別のタイマーは持たない)
      pollBackup();
      if (finished) {
        refreshCases();
        if ($('#historyBox').open) loadHistory(true);   // 開いている記録にも、終わった実行を足す
      } else {
        buildTodo();
      }
      autoTimer = setTimeout(pollAuto, anyActive ? 2000 : 15000);
    }).catch(function () { autoTimer = setTimeout(pollAuto, 5000); });
  }


  /* ================================================================ 依頼の受付(友人の依頼の自動受付。notes:docs/spec/friend.md の 6) ================================================================ */

  /* ---- 状態と設定を持つ欄(依頼の受付・バックアップ)の共通の形 ---- */
  /* 状態の札: 色は state の表から・言葉はサーバーの stateLabel(無ければ オン = onText / オフ) */
  var SECTION_PILL = { off: 'wait', watching: 'ok', idle: 'ok', running: 'run', error: 'err' };
  function paintStatePill(sel, d, onText) {
    var pill = $(sel);
    pill.className = 'pill ' + (SECTION_PILL[d.state] || 'wait');
    pill.textContent = d.stateLabel || (d.enabled ? onText : 'オフ');
  }
  /* 状態を読む。404(その機能の無い版の入口)なら欄ごと隠す・それ以外で読めなければ札に「読めません」(理由は title) */
  function pollSection(path, boxSel, pillSel, what, render) {
    return api(path).then(render, function (e) {
      if (e.status === 404) { $(boxSel).hidden = true; return; }
      var pill = $(pillSel);
      pill.className = 'pill wait'; pill.textContent = '読めません'; pill.title = failText(what + 'の状態を読めませんでした', '画面を読み込み直してください', e);
    });
  }
  /* ホームの設定の節の一部を保存する(api/ytt/prefs の patch。答えの value = 保存したあとの節)。UIKit.prefs.patch はまとめて送り・知らせを自分で出すので使わない */
  function prefsPatch(section, value) { return api('api/ytt/prefs', 'POST', { op: 'patch', section: section, value: value }); }
  /* 欄の設定を保存できなかった: 欄の下の文と、知らせ([もう一度] つき)。check = 何を確かめるか */
  function saveFailed(msg, what, check, e, retry) {
    msg.textContent = failText('保存できませんでした', check + '、もう一度お試しください', e);
    failToast(what + 'の設定を保存できませんでした', check + '、もう一度お試しください', e, retry);
  }
  /* 状態と設定を持つ欄(依頼の受付・バックアップ)の共通の動き。sec: { prefs: 設定の節, what, check, box・enabled・msg・btn: 要素の selector, runPath・runOk・failTitle・failHint: 「今すぐ」,
     data(): 今の状態, status(d)・render(d)・poll(): 描く・読む, fast(): 保存や実行の直後に呼ぶ(任意), busy }。
     スイッチ(enabled)だけをその場で保存する(フォルダ・数は設定の画面)。断られたら(フォルダが空など)理由を出してスイッチを戻す */
  function sectionSave(sec, v) {
    var msg = $(sec.msg);
    msg.textContent = '保存しています…';
    return prefsPatch(sec.prefs, v).then(function () {
      msg.textContent = '';
      if (sec.fast) sec.fast();
      return sec.poll();
    }, function (e) {
      saveFailed(msg, sec.what, sec.check, e, function () { sectionSave(sec, v); });
      if (sec.data()) $(sec.enabled).checked = !!sec.data().enabled;   // 断られたら、表示を元に戻す
    });
  }
  function sectionRun(sec) {
    if (sec.busy) return;
    sec.busy = true; $(sec.btn).disabled = true;
    if (sec.fast) sec.fast();
    api(sec.runPath, 'POST', {}).then(function (d) { sec.render(d); toast(sec.runOk); },
      function (e) { failToast(sec.failTitle, sec.failHint, e); })
      .then(function () { sec.busy = false; if (sec.data()) sec.status(sec.data()); });
  }
  function wireSection(sec) {
    if (!$(sec.box)) return;
    $(sec.btn).addEventListener('click', function () { sectionRun(sec); });
    $(sec.enabled).addEventListener('change', function () { sectionSave(sec, { enabled: $(sec.enabled).checked }); });   // スイッチは押したらすぐ効く
  }

  var intakeData = null, intakeSig = '', noticeSig = '', intakeOpened = false;
  /* 見張るフォルダ・数の欄は設定の画面(/settings。範囲は app/prefs.py の INTAKE_RANGES とスキーマを test_settings_schema が突き合わせる)。ここはスイッチと今のフォルダだけ */
  function fillIntakeSettings(d) {
    $('#intakeEnabled').checked = !!d.enabled;
    $('#intakeFolderNow').textContent = d.folder ? '見張るフォルダ: ' + d.folder : '見張るフォルダは未設定(「設定を変える」で決めます)';
    $('#intakeFolderNow').title = d.folder || '';
  }
  function renderIntakeStatus(d) {
    paintStatePill('#intakeState', d, '見張り中');
    $('#intakeMsg').textContent = d.message || '';
    $('#intakeScan').textContent = d.lastScan ? '最後に確認: ' + ago(d.lastScan) : (d.state === 'watching' ? 'まだ確認していません' : '');
    $('#intakeScan').title = d.lastScan ? when(d.lastScan) : '';
    $('#intakeToday').textContent = d.enabled ? '今日 ' + (d.today || 0) + ' 件' + (d.todayRejects ? '・要らない ' + d.todayRejects + ' 本' : '') : '';
    $('#intakeScanBtn').disabled = INTAKE.busy || !d.enabled;
    $('#intakeScanBtn').title = d.enabled ? '' : '受付がオフです。下の「依頼を受け付ける」をオンにすると押せます';
  }
  function intakeItemRow(it) {
    var li = el('li');
    li.appendChild(el('span', 'pill ' + (it.state === 'accepted' ? 'ok' : 'warn'), it.state === 'accepted' ? '受け付けた' : '断った'));
    li.appendChild(el('span', '', it.label || ''));
    if (it.reason) li.appendChild(el('span', 'hint', it.reason));
    return li;
  }
  function intakeRow(r) {
    var li = el('li', 'pt-intake-item');
    if (r.id) li.setAttribute('data-fkey', 'intake:' + r.id);
    var head = el('div', 'pt-intake-head');
    head.appendChild(el('span', 'pill info', r.kind === 'url' ? 'URL' : r.kind === 'feedback' ? '友人の返事' : r.kind === 'live' ? 'ライブ' : '動画'));
    head.appendChild(el('span', 'pt-intake-title', r.title || (r.kind === 'url' ? '(題名なし)' : '(ファイル名なし)')));
    head.appendChild(el('span', 'pill ' + (r.state === 'accepted' ? 'ok' : 'warn'), r.stateLabel || (r.state === 'accepted' ? '受け付けた' : '断った')));
    var t = el('span', 'hint pt-intake-when', ago(r.received)); t.title = r.received ? when(r.received) : '';
    head.appendChild(t);
    if (r.id && hideApi()) head.appendChild(hideBtn('intake', r.id, r.title));
    if (r.id) markHid(li, 'intake', r.id, head);
    li.appendChild(head);
    var sub = [r.flowLabel || '', r.rangesLabel || '', r.cutLabel || '', r.speakersLabel || '', r.tracksLabel || '', r.streamer ? '字幕の色: ' + r.streamer : '', r.source === 'manual' ? 'フォルダに直接置かれた' : 'アプリから'].filter(Boolean).join(' ・ ');
    if (sub) li.appendChild(el('span', 'hint pt-intake-sub', sub));
    if (r.reason) li.appendChild(el('span', 'hint pt-intake-sub', (r.state === 'rejected' ? '断った理由: ' : '') + r.reason));
    if (r.items && r.items.length) { var ul = el('ul', 'pt-intake-items'); r.items.forEach(function (it) { ul.appendChild(intakeItemRow(it)); }); li.appendChild(ul); }
    return li;
  }
  /* 友人から知らせ(送り返しの .notice.json = 友人のアプリの [作る人に知らせる]。F3-6・C-2-16)。無ければ欄ごと隠す */
  function noticeRow(n) {
    var li = el('li', 'pt-intake-item');
    var head = el('div', 'pt-intake-head');
    head.appendChild(el('span', 'pill warn', '失敗'));
    head.appendChild(el('span', 'pt-intake-title', n.title || '(依頼の題なし)'));
    var t = el('span', 'hint pt-intake-when', ago(n.receivedAt)); t.title = n.receivedAt ? when(n.receivedAt) : '';
    head.appendChild(t);
    li.appendChild(head);
    li.appendChild(el('span', 'pt-intake-sub', n.message || ''));
    var sub = [n.code ? '種類: ' + n.code : '', n.appVersion ? 'アプリ ' + n.appVersion : '', n.requestId ? '依頼 ' + n.requestId : '', n.hasLog ? 'ログあり' : ''].filter(Boolean).join(' ・ ');
    if (sub) li.appendChild(el('span', 'hint pt-intake-sub', sub));
    if (n.detail) {
      var det = el('details'); det.appendChild(el('summary', 'hint', '詳しい文'));
      det.appendChild(el('pre', 'pt-notice-detail', n.detail));
      li.appendChild(det);
    }
    return li;
  }
  function renderNotices(list) {
    var box = $('#intakeNotices');
    if (!box) return;
    var sig = JSON.stringify(list || []);
    if (sig === noticeSig) return;
    noticeSig = sig;
    var ol = $('#intakeNoticeList'); ol.textContent = '';
    (list || []).forEach(function (n) { ol.appendChild(noticeRow(n)); });
    box.hidden = !(list && list.length);
  }
  function renderIntake(d) {
    intakeData = d;
    renderNotices(d.notices);
    $all('.pt-auto[data-auto-send]').forEach(function (b) { paintSendBox(b); });   // 受付のフォルダが分かったら注を出し直す
    var had = deliverFolder;
    deliverFolder = !!d.folder;   // 自動でできた切り抜きの「採用」(友人へ届ける)が押せるか。変わったら、自動の切り抜きがあるときだけ一覧を描き直す
    if (had !== deliverFolder && casesData && casesData.auto && casesData.auto.total) render();
    renderIntakeStatus(d);
    var reqs = d.requests || [];
    var hidN = reqs.filter(function (r) { return isHid('intake', r.id); }).length;
    if (!showHid('intake')) reqs = reqs.filter(function (r) { return !isHid('intake', r.id); });
    var sig = JSON.stringify(reqs) + '|' + showHid('intake') + '|' + reqs.map(function (r) { return isHid('intake', r.id) ? 1 : 0; }).join('');
    if (sig !== intakeSig) {
      intakeSig = sig;
      var ol = $('#intakeList'); ol.textContent = '';
      reqs.forEach(function (r) { ol.appendChild(intakeRow(r)); });
      $('#intakeEmpty').hidden = !!reqs.length;
      if (!reqs.length) {
        if ((d.requests || []).length) emptyBox('表示できる依頼はありません', 'すべて非表示にしています。「非表示のものも出す」と、また見られます。', { label: '非表示のものも出す', fn: function () { UIKit.hide.setShowing('intake', true); } }, $('#intakeEmpty'));
        else emptyBox('まだ依頼は届いていません', '友人のアプリから送られると、ここに出ます。', { label: d.enabled ? '受付の設定を見る' : '受付をオンにする', fn: openIntakeSettings }, $('#intakeEmpty'));
      }
    }
    hideToggle('#intakeHidden', 'intake', hidN);
    if (!intakeOpened) {   // 最初の1回だけ: 動いているとき・止まっているときは開いて見せる(オフのときは閉じたまま)
      intakeOpened = true;
      if (d.enabled || d.state === 'error') $('#intakeBox').open = true;
      fillIntakeSettings(d);
    } else fillIntakeSettings(d);
  }
  function pollIntake() {
    return pollSection('api/intake', '#intakeBox', '#intakeState', '依頼の受付', renderIntake);
  }
  var INTAKE = { prefs: 'intake', what: '依頼の受付', check: '「設定を変える」で見張るフォルダを決めて', box: '#intakeBox', enabled: '#intakeEnabled', msg: '#intakeSaveMsg', btn: '#intakeScanBtn',
    runPath: 'api/intake/scan', runOk: '確認しました', failTitle: '依頼を確認できませんでした', failHint: 'もう一度「今すぐ確認」を押してください(直らないときは画面を開き直してください)',
    busy: false, data: function () { return intakeData; }, status: renderIntakeStatus, render: renderIntake, poll: pollIntake };
  function wireIntake() { wireSection(INTAKE); }

  /* ================================================================ 作業データのバックアップ(src/manage/keep/backup.py。notes:docs/spec/data.md の「バックアップ」) ================================================================ */

  var backupData = null, backupOpened = false, backupTimer = null, backupFastUntil = 0;
  /* 写す先・間隔の欄は設定の画面(/settings)。ここはスイッチと今の写す先だけ */
  function fillBackupSettings(d) {
    $('#backupEnabled').checked = !!d.enabled;
    $('#backupFolderNow').textContent = d.folder ? '写す先: ' + d.folder + (d.everyHours ? '(' + d.everyHours + ' 時間ごと)' : '') : '写す先は未設定(「設定を変える」で決めます)';
    $('#backupFolderNow').title = d.folder || '';
  }
  function renderBackupStatus(d) {
    paintStatePill('#backupState', d, '動いています');
    var n = (d.errors || []).length;
    $('#backupMsg').textContent = d.message || '';
    $('#backupMsg').title = n ? d.errors.join(' / ') : '';
    $('#backupLast').textContent = d.lastOk ? '最後に写した: ' + ago(d.lastOk) + '(' + (d.copied || 0) + ' 個・' + fmtBytes(d.bytes) + ')' : (d.enabled ? 'まだ写していません' : '');
    $('#backupLast').title = d.lastOk ? when(d.lastOk) + (d.dest ? ' → ' + d.dest : '') : '';
    $('#backupRunBtn').disabled = BACKUP.busy || !d.enabled || d.state === 'running';
    $('#backupRunBtn').title = d.enabled ? '' : 'バックアップがオフです。下の「自動でバックアップする」をオンにすると押せます';
  }
  function renderBackup(d) {
    backupData = d;
    renderBackupStatus(d);
    clearTimeout(backupTimer);   // 写している間・保存や「今すぐ」の直後は、短い間隔で読み直す(まとめて実行の周期 15 秒を待たない)
    if (d.state === 'running' || Date.now() < backupFastUntil) backupTimer = setTimeout(pollBackup, 1500);
    if (!backupOpened) {   // 最初の1回だけ: まだ決めていない・止まっているときは開いて見せる(動いているときは閉じたまま)
      backupOpened = true;
      if ((!d.enabled && d.source) || d.state === 'error') $('#backupBox').open = true;
      fillBackupSettings(d);
    } else fillBackupSettings(d);
  }
  function pollBackup() {
    if (!$('#backupBox')) return Promise.resolve();
    return pollSection('api/backup', '#backupBox', '#backupState', 'バックアップ', renderBackup);
  }
  var BACKUP = { prefs: 'backup', what: 'バックアップ', check: '「設定を変える」で写す先のフォルダを決めて', box: '#backupBox', enabled: '#backupEnabled', msg: '#backupSaveMsg', btn: '#backupRunBtn',
    runPath: 'api/backup/run', runOk: 'バックアップを始めました', failTitle: 'バックアップを始められませんでした', failHint: '写す先のフォルダを確かめて、もう一度「今すぐ写す」を押してください',
    busy: false, data: function () { return backupData; }, status: renderBackupStatus, render: renderBackup, poll: pollBackup,
    fast: function () { backupFastUntil = Date.now() + 30000; } };   // 写している間・保存や「今すぐ」の直後は、短い間隔で読み直す
  function wireBackup() { wireSection(BACKUP); }

  /* ================================================================ まとめて実行の記録(段2 B-6。入口を終えても残る。開いたときだけ読む) ================================================================ */

  function historyRow(r) {
    var li = $('#tplHistory').content.firstElementChild.cloneNode(true);
    if (r.id) li.setAttribute('data-fkey', 'runs:' + r.id);
    var pill = $('.pt-history-pill', li);
    pill.className = 'pill pt-history-pill ' + (r.nothing ? 'wait' : UIKit.state.cls(r.state));
    pill.textContent = runLabel(r);
    var a = $('.pt-history-title', li);
    a.textContent = r.title || (r.kind === 'doc' ? r.docId : r.videoId) || (r.kind === 'file' ? '依頼の動画' : '');
    if (r.kind === 'doc') { a.href = docHref(r.docId, null, 'proof'); a.title = '案件の画面で校正を開く'; }   // 文書 → 編集で開く(同じ窓。S-15)
    else if (r.kind === 'file' || !r.videoId) { a.href = '#intake'; a.title = '依頼の受付へ'; }
    else { a.href = '#case-' + encodeURIComponent(r.videoId || ''); a.title = '案件の行へ'; }   // 配信 → 案件の行
    var why = runReason(r);
    $('.pt-history-sub', li).textContent = (r.modeLabel || '') + (why ? ' ・ ' + why : '');
    var t = $('.pt-history-when', li), at = r.finished || r.created;
    t.textContent = ago(at); t.title = at ? when(at) : '';
    if (r.id) {
      li.dataset.id = r.id;
      li.dataset.title = r.title || '';
      if (hideApi()) li.appendChild(hideBtn('runs', r.id, r.title));
    }
    return li;
  }
  /* 記録は少しずつ読む(もっと見る)ので、非表示は読んだ行の hidden で切り替える(読み直さない)。行の中のボタン・札もここで合わせる */
  function applyHistoryHidden() {
    var n = 0;
    $all('#historyList > li').forEach(function (li) {
      var id = li.dataset.id; if (!id) return;
      var on = isHid('runs', id);
      if (on) n++;
      li.hidden = on && !showHid('runs');
      li.classList.toggle('ui-hidden-item', on);
      var tag = $('.ui-hidden-tag', li);
      if (on && !tag) $('.pt-history-main', li).appendChild(el('span', 'ui-hidden-tag', '非表示'));
      if (!on && tag) tag.remove();
      var old = $('.pt-hide', li);
      if (old) old.replaceWith(hideBtn('runs', id, li.dataset.title || ''));
    });
    hideToggle('#historyHidden', 'runs', n);
  }
  function loadHistory(reset) {
    if (histBusy) return;
    histBusy = true;
    if (reset) histOffset = 0;
    var empty = $('#historyEmpty');
    api('api/flow/history?limit=' + HIST_PAGE + '&offset=' + histOffset).then(function (j) {
      var ol = $('#historyList'), runs = j.runs || [];
      if (reset) ol.textContent = '';
      runs.forEach(function (r) { ol.appendChild(historyRow(r)); });
      histOffset += runs.length;
      applyHistoryHidden();
      empty.hidden = !!ol.children.length;
      if (!empty.hidden) emptyBox('まだ記録はありません', 'まとめて実行が終わると、ここに出ます。', { label: '案件の一覧へ', href: '#cases' }, empty);
      var rest = Math.max(0, (j.total || 0) - histOffset);
      $('#historyMoreBox').hidden = !j.more;
      $('#historyMore').textContent = 'もっと見る(あと ' + rest + ' 件)';
    }).catch(function (e) {
      empty.hidden = false;
      emptyBox('記録を読めませんでした', failText('', '「もう一度読む」を押してください', e).replace(/^。/, ''), { label: 'もう一度読む', fn: function () { loadHistory(true); } }, empty);
      empty.title = detailOf(e);
    }).then(function () { histBusy = false; });
  }

  /* 試験中の機能(リアルタイム切り抜き。線 D)の欄は設定の画面(/settings の「リアルタイム切り抜き」の節)にある(notes:docs/spec/data.md の 6)。
     録画と再生・マークはスタジオの中(P3)。入口の側の切り替え(録画の部品の起動)は api/ytt/prefs の patch(section live)で動く */

  /* ================================================================ 新しい案件(RS8 C3。引き出し #newDrawer) ================================================================
     配信を探す・URL や動画ファイルから入れる・解析の順番待ち = スタジオ ① の部品(rank.js・queue.js)を、つなぎ cases-panels/new.js が載せる。
     引き出しを初めて開いたときに css と js を読む(ホームを開くたびには読まない)。URL: /#new(?url=<配信の URL>・?media=<動画のパス> は欄に入れるだけ。解析は押すまで始めない。
     ?set=key|reg|collab = 末尾の「探す設定」の API キー・事務所の登録・コラボを開く(設定の画面のリンク)) */
  var NEW_SET = { key: 'setKey', reg: 'setReg', collab: 'setCollab' };
  var newPanel = null, newLoad = null;
  function newCaseArgs() {
    var q = new URLSearchParams(location.search), h = location.hash, i = h.indexOf('?'), hq = i >= 0 ? new URLSearchParams(h.slice(i + 1)) : new URLSearchParams();
    return { url: (q.get('url') || hq.get('url') || '').trim(), media: (q.get('media') || hq.get('media') || '').trim(), set: NEW_SET[hq.get('set') || ''] || '' };
  }
  function loadNewPanel() {
    if (newLoad) return newLoad;
    var css = document.createElement('link');
    css.rel = 'stylesheet'; css.href = 'cases-panels/new.css';
    document.head.appendChild(css);
    newLoad = UIKit.loadScript('cases-panels/studio-shim.js')
      .then(function () { return UIKit.loadScript('cases-panels/new.js', { ready: function () { return !!window.NewCasePanel; } }); })
      .catch(function (e) { newLoad = null; throw e; });
    return newLoad;
  }
  function openNewCase(opener, opts) {
    var d = $('#newDrawer');
    if (!d) return;
    opts = opts || {};
    UIKit.drawer.open(d, { modal: true, opener: opener || document.activeElement });
    loadNewPanel().then(function () {
      if (!newPanel) { newPanel = window.NewCasePanel.create(); newPanel.mount($('#newBody'), opts); }
      else newPanel.update(opts);
      newPanel.setVisible(UIKit.drawer.isOpen(d));
      if (opts.set) { var p = newPanel; p.whenReady().then(function () { p.openSettings(opts.set); }, function () { /* 読めなければ案内はパネルが出す */ }); }
    }, function (e) {
      $('#newBody').textContent = '';
      var box = el('div', 'empty pt-empty');
      box.appendChild(el('b', '', '新しい案件の画面を読み込めませんでした'));
      box.appendChild(document.createTextNode(reasonOf(e) + ' スタジオが動いていないかもしれません。「調子」で確かめてから、もう一度開いてください。'));
      $('#newBody').appendChild(box);
    });
  }
  function wireNewCase() {
    var d = $('#newDrawer');
    if (!d) return;
    $('#newCaseBtn').addEventListener('click', function () { openNewCase($('#newCaseBtn'), newCaseArgs()); });
    $('#newClose').addEventListener('click', function () { UIKit.drawer.close(d); });
    document.addEventListener('ui-drawer', function (e) {
      if (!e.detail || e.detail.el !== d) return;
      if (newPanel) newPanel.setVisible(e.detail.open);
      if (!e.detail.open && (location.hash === '#new' || location.hash.indexOf('#new?') === 0)) history.replaceState(null, '', location.pathname);
    });
  }

  /* ================================================================ ハッシュ(#cases・#case-<id>): 次にやることのリンク先へ移る ================================================================ */

  function focusHash() {
    var h = location.hash;
    if (!h) return;
    if (h === '#intake') { var ib = $('#intakeBox'); if (ib) { openOps(); ib.open = true; ib.scrollIntoView({ behavior: 'smooth', block: 'start' }); } return; }
    if (h === '#new' || h.indexOf('#new?') === 0) { openNewCase(null, newCaseArgs()); return; }
    if (h === '#edit-acc') { openOps(); var eb = $('#editOpsBox'); if (eb) { eb.open = true; eb.scrollIntoView({ behavior: 'smooth', block: 'start' }); } return; }
    if (h === '#cases') { var sec = $('#caseListSection'); if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    var m = /^#case-(.+)$/.exec(h);
    if (!m) return;
    var id = decodeURIComponent(m[1]);
    visibleCount = Math.max(visibleCount, 10000); render();
    var target = document.getElementById('case-' + id);
    if (!target) return;
    // 対象自身(details なら)と、それを包む details も開く。閉じたままだと target が非表示のまま scrollIntoView されてしまう(E2 finding 3)
    for (var node = target; node; node = node.parentElement) { if (node.tagName === 'DETAILS') node.open = true; }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  window.addEventListener('hashchange', focusHash);
  // 同じハッシュのリンクを続けてクリックしても hashchange は来ない(URL が変わらないため)ので、クリックでも直接呼ぶ(E2 finding 3)
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (a && a.getAttribute('href') === location.hash) { e.preventDefault(); focusHash(); }
  });

  // ホームがここで開いていることを、ほかの窓の「ホーム」リンクに答える(開き直さずにこの窓を前に出すため。ui-kit の UIKit.portal)
  UIKit.portal.listen();

  document.addEventListener('DOMContentLoaded', function () {
    /* ⚙ 設定の「ホーム」の節(M10): 窓で開く と、設定の画面へのリンク(まとめて実行の既定・試験中の機能・受付・バックアップの欄は設定の画面にある) */
    var hs = $('#homeSettings');
    if (hs) hs.hidden = false;
    UIKit.settings.mount(hs ? { title: '設定', tool: hs } : { title: '設定' });

    $('#btnQuit').addEventListener('click', quit);
    $('#btnHealthRefresh').addEventListener('click', function () { loadHealth(true); });
    $('#btnAccuracyNow').addEventListener('click', accuracyNow);
    var adv = $('#healthBox') && $('#healthBox').closest('details');
    if (adv) { adv.addEventListener('toggle', function () { if (adv.open) loadHealth(false); }); if (adv.open) loadHealth(false); }
    $('#winMode').addEventListener('change', function () { setWin(this.checked ? 'app' : 'browser'); });
    $('#btnWinNow').addEventListener('click', openWinNow);
    $('#btnCopyData').addEventListener('click', function () {
      var t = $('#dataDir').textContent;
      if (t) UIKit.copy(t, { ok: 'パスをコピーしました', fail: 'コピーできませんでした。パスを選んでコピーしてください' });
    });

    $('#fText').addEventListener('input', function () { resetPaging(); });
    $('#fSort').addEventListener('change', function () { lsSet('sort', $('#fSort').value); resetPaging(); });
    $('#btnMore').addEventListener('click', function () {
      var from = $all('#list .pt-case').length; visibleCount += PAGE_SIZE; render(); focusNewRow('#list .pt-case', from);
    });
    $('#btnReload').addEventListener('click', reloadAll);


    $('#todoMore').addEventListener('click', function () {   // すべて見る ⇄ 少なく表示。広げたら最初に増えた行へフォーカス(M6・S10)
      todoShowAll = !todoShowAll; buildTodo();
      if (todoShowAll) { var rows = $all('#todoList .pt-todo-link'), t = rows[TODO_CAP]; if (t) t.focus(); }
    });
    $('#historyBox').addEventListener('toggle', function () { if ($('#historyBox').open) loadHistory(true); });
    $('#historyMore').addEventListener('click', function () { loadHistory(false); });
    wireIntake();
    wireBackup();
    wireNewCase();
    /* 運用の枠: 中の欄(受付・バックアップ・記録・編集の精度・調子)が開いたら枠も開く(コードで開く「まだ決めていない」の受付・バックアップも見える) */
    ['intakeBox', 'backupBox', 'historyBox', 'editOpsBox', 'advancedBox'].forEach(function (id) {
      var b = $('#' + id);
      if (b) b.addEventListener('toggle', function () { if (b.open) openOps(); });
    });
    UIKit.hide.onChange(function (list) {   // 非表示にした項目を読んだら・変えたら、その一覧を描き直す(別の窓で変えた分は戻ったときに部品が読み直す)
      if (!list || list === 'cases') render();
      if (!list || list === 'cases' || list === 'todo') buildTodo();
      if ((!list || list === 'intake') && intakeData) renderIntake(intakeData);
      if (!list || list === 'runs') applyHistoryHidden();
    });
    UIKit.hide.load();

    restoreFilters();
    /* タブ・窓に戻ったらすぐ読み直す(ui-kit の UIKit.life。窓を並べて使うとタブの切り替えは来ないため。visibilitychange は直接使わない) */
    /* 依頼の受付・バックアップも(設定の画面でフォルダを決めて戻ったとき、受付のフォルダで決まる「採用」がすぐ押せる) */
    UIKit.life.onReturn(function () { poll(); refreshCases(); loadCheck(); pollIntake(); pollBackup(); });

    poll();
    loadCheck();
    loadCases().then(function () { renderDocs(); buildTodo(); pollAuto(); focusHash(); });
  });
})();
