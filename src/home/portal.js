/* ホーム(src/home/portal.html。段階5で入口 + 案件を1つにした)。
   - ツールの起動状態(旧・入口)は /api/status を定期的に読んで「詳しく」の中のカードに出す(開く・起動・停止・再起動・すべて終了)
   - 案件(配信ごと)の一覧(旧・cases.html)は /api/cases を読んで組み立てる。状態・メモは /api/cases/update に保存
   - 「次にやること」は、案件の一覧・まとめて実行(/api/autorun)・「編集」の文書の一覧(/transcribe/api/transcripts。読めるときだけ)
     から、この画面の中で組み立てる。確認前の候補・書き出し待ち・文字起こし待ちは案件の一覧の todo(cases.py。入口 0.42.0・S-6)
   - 画面の移り方(S-15): ツールの画面へのリンクは同じ窓で移る(target を付けない。新しい窓は Ctrl・中クリック = 窓の中なら UIKit.win)。
     「詳しく」のツールのカードの「開く」(サーバーの管理)だけは新しい窓
   - 「単体の文字起こし」は、案件の一覧が返す unlinked(どの配信にも紐づかない文字起こし。src/ytt_core/txindex の規則そのまま)を、
     「編集」の文書の一覧と id で突き合わせて、校正の進み具合・パックの有無まで見せる。読めないときは案件の一覧の項目だけで表示する
   ツール名・ログ・メッセージ・配信のタイトルなどはすべて textContent で入れる(HTML として解釈させない)。 */
(function () {
  'use strict';
  var LABEL = { starting: '起動中…', running: '動作中', external: '別の画面で起動済み', stopping: '停止中…', stopped: '停止', crashed: '異常終了', missing: '見つかりません' };
  var PILL = { starting: 'run', running: 'ok', external: 'info', stopping: 'wait', stopped: 'wait', crashed: 'err', missing: 'err' };
  var BUSY_LABEL = { start: '起動しています…', stop: '止めています…', restart: '再起動しています…' };
  var STATUS = { '': '未設定', working: '作業中', posted: '投稿済み', skipped: '見送り' };
  var STATUS_PILL = { '': '', working: 'accent', posted: 'ok', skipped: 'wait' };   // 作業中は人が付けた状態(回る輪の run は本当に動いているときだけ。M7)
  var STEP_STATE = { wait: '待ち', run: '実行中', done: '済み', skip: '飛ばした', warn: '一部失敗', error: '失敗' };
  var STEP_PILL = { wait: 'wait', run: 'run', done: 'ok', skip: 'wait', warn: 'warn', error: 'err' };
  var POLL_MS = 1500, POLL_HIDDEN_MS = 5000;
  var PAGE_SIZE = 30, DOC_PAGE = 20, TODO_CAP = 5;

  var cards = {};        // ツールID → {el, data}
  var busy = {};         // ツールID → 実行中の操作(二重押し防止)
  var fails = 0, closed = false, timer = null, quitNotice = '';
  var tokenMeta = document.querySelector('meta[name="ytt-token"]');
  var TOKEN = tokenMeta ? tokenMeta.content : '';   // 書き込み系の API の合言葉(CSRF トークン。サーバーが画面に入れる)

  var casesData = null;                 // /api/cases の中身
  var txList = null, txById = {};       // /transcribe/api/transcripts(読めないときは null。次にやること・単体の文字起こしの詳しい表示に使う)
  var runsByVideo = {}, runsByDoc = {}; // /api/autorun の実行(配信単位・文書単位)。最新のものだけ
  var pastByVideo = {}, pastByDoc = {}; // /api/autorun の past: 前回の結果(記録のファイルから。この起動の実行が無い配信・文書だけ。段2 B-6)
  var HIST_PAGE = 50, histOffset = 0, histBusy = false;   // 「まとめて実行の記録」(/api/autorun/history。開いたときだけ読む)
  var runsByFile = {};                  // /api/autorun の kind "file"(依頼の文字起こしだけ。videoId・docId が無いので実行の id で持つ)
  // あとから解析(mode post_analyze。依頼の区間と比べるためだけ。2026-10-05)。案件の行の「まとめて実行」とは別に持つ
  // (最中でも行を自動で開かない・実行を押せる = 押すとあとから解析は止まって、押した実行が先に動く)
  var postByVideo = {}, wasActivePost = {};
  var POST_MODE = 'post_analyze';
  var wasActiveVideo = {}, wasActiveDoc = {}, wasActiveFile = {};
  var autoTimer = null;
  var visibleCount = PAGE_SIZE;         // 案件の一覧の「もっと見る」
  var docVisibleCount = DOC_PAGE;       // 単体の文字起こしの「もっと見る」
  var docPicked = {};                   // 単体の文字起こしで選んだ文書の id
  var openCases = {};                   // この画面を開いてから自分で開閉した案件(id → bool)
  var caseDrafts = {};                  // 保存していない入力(メモ・配信者)。id → {memo, streamer}(再描画(alt-tab で戻ったときなど)でも保つ)
  function draftFor(id) { return caseDrafts[id] || (caseDrafts[id] = {}); }
  var memoSave = {};                    // メモの保存の状態。id → {busy, sent, again, msg}(1つずつ順に送る = 応答の順が入れ替わらない。監査 14)
  var groupOpenCache = null;
  var termShown = {};
  var todoShowAll = false;

  function $(sel, el) { return (el || document).querySelector(sel); }
  function $all(sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); }

  function fetchT(path, init, ms) {
    var ctl = window.AbortController ? new AbortController() : null, t = null;
    if (ctl) { init.signal = ctl.signal; t = setTimeout(function () { ctl.abort(); }, ms); }
    return fetch(path, init).then(function (r) { clearTimeout(t); return r; }, function (e) { clearTimeout(t); throw e; });
  }

  function api(path, method, body) {
    var init = { method: method || 'GET', cache: 'no-store', headers: {} };
    if (init.method === 'POST') { init.headers['Content-Type'] = 'application/json'; init.headers['X-YTT-Token'] = TOKEN; init.body = JSON.stringify(body || {}); }
    return fetchT(path, init, init.method === 'POST' ? 60000 : 8000).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) {   // 本文に出すのは日本語の文だけ。HTTP の番号・サーバーの原文は detail(知らせの「詳しく」・title)へ(B-03)
          var e = new Error(j.message || 'ホームがうまく応答できませんでした');
          e.status = r.status; e.reason = j.message || ''; e.detail = 'HTTP ' + r.status + (j.message ? ' ' + j.message : '');
          throw e;
        }
        return j;
      });
    }, function (e) {
      var ne = new Error(e && e.name === 'AbortError' ? 'ホームの応答が遅れています' : 'ホームにつながりませんでした');
      ne.reason = ''; ne.detail = String((e && e.message) || e);
      throw ne;
    });
  }

  function toast(msg, kind) { if (window.UIKit && UIKit.toast) UIKit.toast(msg, kind ? { kind: kind } : undefined); }
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
    var text = failText(what, next, e), opt = { kind: 'err', detail: detailOf(e) };
    if (retry) { opt.action = { label: 'もう一度', fn: retry }; opt.ms = 0; }
    if (window.UIKit && UIKit.toast) UIKit.toast(text, opt);
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
  /* ---- 一覧の非表示(ui-kit の UIKit.hide。2026-10-04)---- 案件・次にやること・単体の文字起こし・届いた依頼・まとめて実行の記録。
     覚える場所はホームの設定の節 hidden(どの窓・ツールでも同じ)。データは消さない。「非表示 n件を表示」で薄く出して「表示に戻す」 */
  function hideApi() { return window.UIKit && UIKit.hide && UIKit.hide.available() ? UIKit.hide : null; }
  function isHid(list, id) { var h = hideApi(); return !!(h && h.has(list, id)); }
  function showHid(list) { var h = hideApi(); return !!(h && h.showing(list)); }
  /* 押したボタンが描き直しで消えても、フォーカスを失わない(M6。キーボードの人が画面の先頭から Tab し直さないように)。
     行には data-fkey(一覧の名前:id)を付けてあるので、描き直したあとで引く: その行がまだあれば行の中の「非表示にする」・
     隠れて無くなったら次の行(無ければ前の行)の最初の操作・それも無ければその一覧の「非表示 n件を表示」 */
  var HIDE_TOGGLE = { cases: '#casesHidden', transcripts: '#docHidden', todo: '#todoHidden', intake: '#intakeHidden', runs: '#historyHidden' };
  function rowByKey(k) { return k ? $all('[data-fkey]').filter(function (n) { return n.getAttribute('data-fkey') === k; })[0] || null : null; }
  function firstFocusable(root) {
    return root ? (root.querySelector('a[href], summary, button:not([disabled]), input:not([disabled]), select, textarea') || null) : null;
  }
  function focusFallback(list, near) {
    var t = near || (HIDE_TOGGLE[list] ? $(HIDE_TOGGLE[list]) : null), box = t && t.hidden ? null : t;
    if (box) { box.focus({ preventScroll: true }); return; }
    var h = $(list === 'cases' ? '#fText' : list === 'transcripts' ? '#docSearch' : '#todoBox h2');
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
    if (window.UIKit && UIKit.icon) ic.innerHTML = UIKit.icon(on ? 'undo' : 'close', { size: 14 });   // 狭い幅では文字をやめてアイコンだけ(S11)
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
  function hideToggle(sel, list, n) { if (window.UIKit && UIKit.hide) UIKit.hide.toggle($(sel), list, n); }

  function term(word, title) {
    if (termShown[word]) return document.createTextNode(word);
    termShown[word] = true;
    var a = document.createElement('abbr');
    a.className = 'ui-term'; a.title = title; a.textContent = word;
    return a;
  }
  function tc(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
  }
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
  function baseName(p) { return String(p || '').split(/[\\/]/).pop(); }
  /* 欄の Enter で実行(S-24)。かな漢字変換を確定する Enter(isComposing・229)では動かさない */
  function enterRuns(input, btn) {
    if (!input || !btn) return;
    input.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229 || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;
      e.preventDefault();
      if (!btn.disabled && !btn.hidden) btn.click();
    });
  }

  /* ================================================================ ツールの起動状態(旧・入口。「詳しく」の中) ================================================================ */

  function toolUrl(t) {
    var path = /^\/(?:[a-z0-9][a-z0-9-]{0,31}\/)?$/.test(t.path || '') ? t.path : '/';
    return 'http://' + location.hostname + ':' + t.port + path;
  }

  /* ui-appnav(ヘッダー左の「ホーム/スタジオ/編集」)の「スタジオ」「編集」の項目は、DOMContentLoaded の時点(/api/status を
     まだ読んでいない)で作られるので、ホームに取り込まれているかどうかに関わらず既定の場所(base の '/')のままになる。
     UIKit.tools.setPaths(v6)は渡した場所を覚えて appnav のリンクを描き直してくれる(UIKit.appnav.setVersion の title は
     描き直しても保たれる)ので、ここでは /api/status から場所だけ取り出して渡す(href を直接書き換えない) */
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
    $('.pt-toggle', li).addEventListener('click', function () {
      var s = cards[t.id].data.state;
      act(t.id, s === 'running' || s === 'starting' ? 'stop' : 'start');
    });
    $('.pt-restart', li).addEventListener('click', function () { act(t.id, 'restart'); });
    var box = $('.pt-logbox', li);
    box.addEventListener('toggle', function () { if (box.open) loadLog(t.id); });
    $('#flow').appendChild(li);
    return (cards[t.id] = { el: li, data: t });
  }

  function updateTool(t) {
    if (t.hidden && !cards[t.id] && (t.state === 'running' || t.state === 'starting' || t.state === 'external')) return;   // 部品(cut2resolve)は困っているときだけ出す
    if (t.hidden && cards[t.id] && (t.state === 'running' || t.state === 'external') && !busy[t.id]) { cards[t.id].el.remove(); delete cards[t.id]; return; }
    var c = cards[t.id] || build(t);
    c.data = t;
    var el2 = c.el, b = busy[t.id], s = t.state;
    el2.setAttribute('data-state', s);
    var pill = $('.pt-pill', el2);
    pill.className = 'pill pt-pill ' + (b ? 'run' : (PILL[s] || ''));
    pill.textContent = b ? BUSY_LABEL[b] : (LABEL[s] || s);

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

    var open = $('.pt-open', el2), up = (s === 'running' || s === 'external') && !!t.port && !b;
    if (up) { open.href = toolUrl(t); open.removeAttribute('aria-disabled'); }
    else { open.removeAttribute('href'); open.setAttribute('aria-disabled', 'true'); }

    var toggle = $('.pt-toggle', el2), restart = $('.pt-restart', el2);
    toggle.hidden = restart.hidden = !!t.mounted;   // ホームに取り込んだツールは、ずっと押せない停止・再起動を並べない(S6。説明の 1 行だけ)
    var runningHere = s === 'running' || s === 'starting';
    toggle.textContent = runningHere || s === 'stopping' || s === 'external' ? '停止' : '起動';
    toggle.disabled = !!b || closed || s === 'stopping' || s === 'external' || s === 'missing' || !!t.mounted;
    toggle.title = s === 'external' ? '別の黒い画面で起動したツールは、その画面で止めてください'
      : t.mounted ? 'ホームと一緒に動いています(「すべて終了」で一緒に終わります)' : '';
    restart.disabled = !!b || closed || !(t.managed && runningHere) || !!t.mounted;
    restart.title = t.mounted ? toggle.title : '';
    if (fails >= 2) { toggle.disabled = true; restart.disabled = true; }
  }

  function loadLog(id) {
    var c = cards[id];
    if (!c) return;
    var pre = $('.pt-log', c.el);
    api('/api/log?tool=' + encodeURIComponent(id) + '&lines=300').then(function (j) {
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
    api('/api/status').then(function (st) {
      fails = 0;
      setConn(true);
      $('#ver').textContent = 'ホーム v' + st.version;
      if (window.UIKit && UIKit.appnav) UIKit.appnav.setVersion('v' + st.version);
      if (st.dataDir) { $('#dataDir').textContent = st.dataDir; $('#dataBox').hidden = false; }
      if (st.window) renderWin(st.window);
      st.tools.forEach(updateTool);
      if (window.UIKit && UIKit.tools && UIKit.tools.setPaths) UIKit.tools.setPaths(toolPaths(st.tools));
      Object.keys(cards).forEach(function (id) { if ($('.pt-logbox', cards[id].el).open) loadLog(id); });
    }).catch(function () {
      fails++;
      if (fails >= 2) { setConn(false); Object.keys(cards).forEach(function (id) { updateTool(cards[id].data); }); }
    }).then(function () {
      if (!closed) timer = setTimeout(poll, document.hidden ? POLL_HIDDEN_MS : POLL_MS);
    });
  }

  function act(id, action) {
    if (busy[id] || closed) return;
    busy[id] = action;
    updateTool(cards[id].data);
    api('/api/tools/' + encodeURIComponent(id) + '/' + action, 'POST').then(function (j) {
      delete busy[id];
      if (j.tool) updateTool(j.tool);
    }).catch(function (e) {
      delete busy[id];
      updateTool(cards[id].data);
      failToast('ツールの操作ができませんでした', '少し待って、もう一度押してください', e);
    }).then(poll);
  }

  /* 窓で開く(段階7-3。2026-09-27 から既定で窓) */
  var winBusy = false;
  function inApp() { return !!(window.UIKit && UIKit.win && UIKit.win.isApp()); }
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
    api('/api/window', 'POST', { mode: mode }).then(function (j) {
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
    if (!(window.UIKit && UIKit.win)) return;
    UIKit.win.open(location.origin + '/').then(function () {
      toast('窓で開きました。このタブは閉じてかまいません', 'ok');
    }, function (e) { failToast('窓で開けませんでした', 'いつものブラウザのタブのまま使えます', e); });
  }

  /* すべて終了: 誤操作を防ぐため 2 回押し(UIKit.confirmTwice。ほかの画面の「取り消せない操作」と同じ形・3 秒以内。S7) */
  function doQuit() {
    var b = $('#btnQuit');
    b.disabled = true;
    b.textContent = '終了しています…';
    api('/api/shutdown', 'POST').then(function (r) {
      quitNotice = (r && r.notice) || '';   // 録画中なので録画の部品を残した、など(0.38.1)
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
    if (window.UIKit && UIKit.confirmTwice) UIKit.confirmTwice(b, doQuit, 'もう一度押すと終了します');
  }
  function waitGone(n) {
    fetchT('/api/ping', { cache: 'no-store' }, 2000).then(function () {
      if (n < 40) setTimeout(function () { waitGone(n + 1); }, 700);
      else doneText('終了に時間がかかっています', '黒い画面が残っていれば、その画面を閉じてください。');
    }).catch(function () {
      doneText('すべて終了しました', 'この画面(タブ・窓)は閉じてかまいません。もう一度使うときは start.bat をダブルクリックしてください。');
    });
  }
  function doneText(title, text) { $('#doneTitle').textContent = title; $('#doneText').textContent = text + (quitNotice ? ' ' + quitNotice : ''); }

  /* ================================================================ 案件(配信ごと)の一覧(旧・cases.html) ================================================================ */

  function lsGet(k, d) { try { var v = localStorage.getItem('ytt.cases.' + k); return v === null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem('ytt.cases.' + k, v); } catch (e) { /* 保存できなくても動く */ } }
  function groupOpenMap() {
    if (!groupOpenCache) { try { groupOpenCache = JSON.parse(lsGet('groupOpen', '{}')) || {}; } catch (e) { groupOpenCache = {}; } }
    return groupOpenCache;
  }
  function setGroupOpen(key, open) { groupOpenMap()[key] = !!open; lsSet('groupOpen', JSON.stringify(groupOpenCache)); }

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
    var auto = !!(c.auto && kase);   // 自動でできた切り抜き(線 D の M9)
    if (auto) { li.classList.add('pt-ac'); li.setAttribute('data-fkey', 'auto:' + autoKey(kase, c)); autoPills(head, c); }
    li.appendChild(head);
    if (auto) autoFail(li, c);
    var st = el('div', 'row pt-clip-steps');
    if (c.transcript) {
      var t = c.transcript, done = t.segments && t.proofed >= t.segments;
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
    if (c.transcript && c.transcript.id) open = link('編集で開く', docHref(c.transcript.id, c.exists ? c.path : '', 'tx'));
    else if (c.exists && c.path) open = link('編集で開く', '/transcribe/?media=' + encodeURIComponent(c.path) + '#tx');
    if (open) {
      st.appendChild(open);
      if (auto) ['click', 'auxclick'].forEach(function (ev) { open.addEventListener(ev, function () { markSeen(kase, c); }); });   // 開いたら「見た」
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

  /* ---- 自動でできた切り抜きの確認(線 D の M9・M12。入口 0.43.1)----
     .clip.json の出どころが自動(配信中の候補・配信後の解析)の切り抜きに「自動」の札・出どころ・点数・控え・未見/見た・届けた・失敗の文と、
     [採用](= 友人へ届ける。パックがあって、依頼の受付の Dropbox のフォルダが決まっているときだけ押せる。全自動では届けない = 10-06 ユーザー決定)・
     [要らない](ごみ箱フォルダへ移す + スタジオのマークを不採用に + 誤検出として記録)を出す。どちらも二度押し(UIKit.confirmTwice)。
     中身はサーバー(/api/cases/auto = src/home/cases.py の auto_review)。届けている途中の進み具合は api/ytt/deliver の status で聞き直す */
  var ORIGIN_TITLE = { auto: '配信中に盛り上がりを見つけて、自動で採用した候補から作った切り抜きです',
    archive: '配信のあとでアーカイブを解析して、自動で採用した候補から作った切り抜きです' };
  var autoOnly = false;          // 「自動の切り抜き: 未確認 n 件」の絞り込み(この画面の間だけ。覚えない)
  var deliverJobs = {};          // 案件の id/マークの id → {msg}(届けている途中。一覧を描き直しても出し続ける)
  var deliverFolder = null;      // 依頼の受付の Dropbox のフォルダが決まっているか(null = まだ分からない = 押せる。決まっていなければサーバーが理由を返す)
  function autoKey(kase, cl) { return kase.id + '/' + cl.markId; }
  function twice(btn, run, text) { if (window.UIKit && UIKit.confirmTwice) UIKit.confirmTwice(btn, run, text); }   // 二度押しの確認(ブラウザの confirm は使わない)
  function iconBtn(icon, label, cls) {
    var b = el('button', 'btn small ' + cls);
    b.type = 'button';
    if (window.UIKit && UIKit.icon) b.innerHTML = UIKit.icon(icon);   // 決まった SVG の文字列だけ(画面のデータは入れない)
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
    var s;
    if (rv.deliveredAt) { s = el('span', 'pill ok pt-ac-done', '届けた ' + ago(rv.deliveredAt)); s.title = 'Dropbox の 出力 に置きました' + (rv.delivered ? ': ' + rv.delivered : ''); }
    else if (rv.seenAt) { s = el('span', 'hint pt-ac-seen', '見た ' + ago(rv.seenAt)); s.title = when(rv.seenAt); }
    else { s = el('span', 'pill info pt-ac-unseen', '未見'); s.title = 'まだ開いていません(「編集で開く」・採用・要らない のどれかで「見た」になります)'; }
    head.appendChild(s);
  }
  /* 失敗の文(線 D の M3。「調子」・スタジオの LIVE の帯と同じ文 = src/home/live_failures.py の failure_of) */
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
      ok.addEventListener('click', function () { twice(ok, function () { autoDeliver(kase, cl); }, 'もう一度押すと届けます'); });
      row.appendChild(ok);
      msg.textContent = dj ? dj.msg : why;
    }
    var no = iconBtn('trash', '要らない', 'danger pt-ac-discard');
    no.disabled = !!dj;
    no.title = dj ? '届けている途中です(終わってから押せます)' : 'パック・切り抜きの動画を ごみ箱フォルダ へ移し(14 日で消えます)、スタジオのマークを不採用にして、誤検出として記録します';
    no.addEventListener('click', function () { twice(no, function () { autoDiscard(kase, cl, no); }, 'もう一度押すとごみ箱へ'); });
    row.appendChild(no);
    row.appendChild(msg);
    li.appendChild(row);
  }
  /* 開いたら「見た」(移る前に送る = keepalive。送れなくても開くのは止めない) */
  function markSeen(kase, cl) {
    if ((cl.review || {}).seenAt) return;
    cl.review = Object.assign({}, cl.review, { seenAt: Date.now(), unconfirmed: false });
    try {
      fetch('/api/cases/auto', { method: 'POST', keepalive: true, cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-YTT-Token': TOKEN },
        body: JSON.stringify({ op: 'seen', id: kase.id, markId: cl.markId }) }).catch(function () { /* 次に開いたときにまた送る */ });
    } catch (e) { /* 同上 */ }
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
    api('/api/cases/auto', 'POST', { op: 'deliver', id: kase.id, markId: cl.markId }).then(function (r) {
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
  function autoDiscard(kase, cl, btn) {
    btn.disabled = true;
    api('/api/cases/auto', 'POST', { op: 'discard', id: kase.id, markId: cl.markId }).then(function (r) {
      if (window.UIKit && UIKit.toast) UIKit.toast('ごみ箱フォルダへ移して、スタジオのマークを不採用にしました(14 日で消えます)', { kind: 'ok', detail: r.trash || '' });
      if (window.UIKit && UIKit.hide && UIKit.hide.available()) UIKit.hide.load(true);   // その文字起こしを非表示にしたので、覚えている非表示を読み直す
      afterAutoAction(kase.id);
    }, function (e) {
      btn.disabled = false;
      failToast('片付けられませんでした', 'ファイルを開いているアプリを閉じてから、もう一度「要らない」を押してください', e);
    });
  }
  /* 採用・要らないのあと: 一覧を読み直して、同じ配信の次の自動の切り抜き → 配信の行 → 絞り込みのボタン の順にフォーカスを移す(押したボタンが消えるため) */
  function afterAutoAction(caseId) {
    return refreshCases().then(function () {
      var node = document.getElementById('case-' + caseId);
      var t = (node && node.open && node.querySelector('.pt-ac button:not([disabled])')) || (node && $('.pt-case-row', node)) || (!$('#autoFilter').hidden && $('#autoFilter')) || $('#fText');
      if (t) t.focus({ preventScroll: true });
    });
  }
  /* 一覧の上の「自動の切り抜き: 未確認 n 件」(押すと、未確認の自動の切り抜きがある配信だけに絞る。もう一度押すと戻す) */
  function paintAutoFilter() {
    var b = $('#autoFilter'), a = (casesData && casesData.auto) || { total: 0, unconfirmed: 0 };
    b.hidden = !a.total && !autoOnly;
    b.setAttribute('aria-pressed', String(autoOnly));
    b.textContent = '自動の切り抜き: 未確認 ' + (a.unconfirmed || 0) + ' 件';
    b.title = autoOnly ? 'もう一度押すと、全部の配信に戻します' : '自動でできた切り抜きのうち、まだ見ていない・届けていないものがある配信だけを出します(行も開きます)';
  }
  function paintCaseAuto(node, c) {
    var p = $('.pt-case-autopill', node), a = c.autoClips || { total: 0, unconfirmed: 0 };
    p.hidden = !a.total;
    if (!a.total) return;
    p.className = 'pill pt-case-autopill ' + (a.unconfirmed ? 'accent' : 'wait');
    p.textContent = a.unconfirmed ? '自動 未確認 ' + a.unconfirmed + '本' : '自動 ' + a.total + '本';
    p.title = '自動でできた切り抜き ' + a.total + '本(未確認 ' + a.unconfirmed + '本)。行を開くと、採用(友人へ届ける)・要らない を選べます';
  }

  function active(r) { return r && (r.state === 'queued' || r.state === 'running'); }
  function activeIn(ids) { return ids.some(function (id) { return active(runsByVideo[id]); }); }

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

  function wireAuto(node, c) {
    var box = $('.pt-auto', node), mode = $('.pt-auto-mode', box), top = $('.pt-auto-top', box), who = $('.pt-auto-streamer', box);
    if (c.gone) { goneAuto(box, c); return; }
    if (window.UIKit && UIKit.streamer) UIKit.streamer.attach(who);
    var draft = draftFor(c.id);
    if (draft.streamer != null) { who.value = draft.streamer; who.dispatchEvent(new Event('input')); }   // 未保存の入力を再描画でも保つ(E2 finding 1)
    else if (window.UIKit && UIKit.streamer && UIKit.streamer.autoFill) UIKit.streamer.autoFill(who, { videoId: c.id, channel: c.channel || '' });   // 覚えた名前 → チャンネル名から(段5)
    who.addEventListener('input', function () { draftFor(c.id).streamer = who.value; });
    /* 形・採用数・上書きはホームの設定(UIKit.autorun = どの入口で変えても同じ。気が利く画面へ 段4。以前はこのブラウザの ytt.cases.mode/top)。
       形の初期値は配信の状態から(マークが 0 = 解析から全部・採用あり = 採用後を全部。どちらでもなければ保存した形。S-4) */
    var ar = window.UIKit && UIKit.autorun;
    var stateMode = !c.marks.total ? 'full' : c.marks.adopted ? 'adopted' : null;
    mode.value = stateMode || 'adopted';
    var sync = function () { $('.pt-auto-topbox', box).hidden = mode.value !== 'full'; };
    if (ar) {
      ar.panel($('.pt-auto-panel', box), { kind: 'video' });
      ar.load().then(function (st) { if (!stateMode && st.mode) mode.value = st.mode; top.value = String(st.top); sync(); }, function () {});
    }
    mode.addEventListener('change', function () { if (window.UIKit && UIKit.prefs) UIKit.prefs.patch('autorun', { mode: mode.value }).catch(function () {}); sync(); });
    top.addEventListener('change', function () { var n = Math.round(Number(top.value)); if (n >= 1 && n <= 20 && window.UIKit && UIKit.prefs) UIKit.prefs.patch('autorun', { top: n }).catch(function () {}); });
    sync();
    $('.pt-auto-run', box).addEventListener('click', function () {
      var st = ar ? ar.state() : null;
      var body = { id: c.id, mode: mode.value, overwrite: !!(st && st.overwrite) };
      if (mode.value === 'full') body.top = Math.round(Number(top.value) || 3);
      var chk = window.UIKit && UIKit.streamer && UIKit.streamer.check ? UIKit.streamer.check(who) : Promise.resolve(who.value.trim());
      var estBody = { id: c.id, mode: body.mode, top: body.top, overwrite: body.overwrite };
      chk.then(function (name) {
        if (name === null) return null;   // 見つからない名前で「やめる」を選んだ
        body.streamer = name;   // 欄の名前(空 = 色なし。欄は自動で入るので、空は「色なし」の意味)
        // 先に見積もる: やることが無いなら、理由だけでなく次の一手(スタジオで候補を確認する など)を押せる形で知らせる(M2)
        return api('api/autorun/estimate', 'POST', estBody).catch(function () { return null; }).then(function (est) {
          if (est && est.nothing) { nothingToDo(c, est.reason); return null; }
          return ar ? ar.start('api/autorun/start', body, estBody) : api('/api/autorun/start', 'POST', body);
        });
      }).then(function (r) {
        if (!r) return;   // やることが無い(見積もり。知らせは上の nothingToDo)
        runsByVideo[c.id] = r.run; node.open = true; renderAuto(node, c.id); focusCancel(c.id); pollAuto();
      }).catch(function (e) { failToast('まとめて実行を始められませんでした', 'もう一度「実行」を押してください', e); });
    });
    enterRuns(who, $('.pt-auto-run', box));   // 配信者・採用する数の欄の Enter で実行(S-24)
    enterRuns(top, $('.pt-auto-run', box));
    $('.pt-auto-cancel', box).addEventListener('click', function () {
      var r = runsByVideo[c.id]; if (!r) return;
      api('/api/autorun/cancel', 'POST', { runId: r.id }).then(function (x) { runsByVideo[c.id] = x.run; renderAuto(node, c.id); })
        .catch(function (e) { failToast('中止できませんでした', 'もう一度「中止」を押してください', e); });
    });
    renderAuto(node, c.id);
  }
  /* 「実行」を押したが、やることが無かったとき(M2): 理由 + 次の一歩 + その画面へ行くボタン(以前は理由だけで、押せる次の一手が無かった) */
  function nothingToDo(c, reason) {
    var cand = (c.marks && c.marks.candidates) || 0, adopted = (c.marks && c.marks.adopted) || 0, exported = (c.marks && c.marks.exported) || 0;
    var next = '', act = null;
    if (!c.gone && !adopted && !exported) {
      if (cand) { next = '。スタジオの ③ 確認で候補を採用すると、書き出せます'; act = { label: '候補の確認へ', href: studioHref(c.id) }; }
      else { next = '。スタジオで配信を解析すると、候補が出ます'; act = { label: 'スタジオで解析する', href: studioHref(c.id) }; }
    }
    var opt = { kind: 'info', ms: 12000 };
    if (act) opt.action = { label: act.label, fn: function () { location.href = act.href; } };   // 同じ窓で移る(S-15)
    if (window.UIKit && UIKit.toast) UIKit.toast('やることがありません: ' + (reason || '済んでいます') + next, opt);
  }
  function runLabel(r) { return window.UIKit && UIKit.autorun ? UIKit.autorun.runLabel(r) : r.state; }   // 状態の言葉は1か所(何もしなかったら「完了」と言わない)
  function ago(ms) { return ms ? (window.UIKit && UIKit.fmt ? UIKit.fmt.ago(ms) : when(ms)) : ''; }
  /* 止まった理由(失敗 = エラーの文・中止 = 「入口を終了しました」など)。済みなら空 */
  function runReason(r) { return r.error || (r.state === 'cancelled' && r.message ? r.message : ''); }
  /* 前回の結果の1行(記録のファイルから。段2 B-6): 「前回 採用後を全部: 失敗 ・ 理由(3日前)」 */
  function pastText(p) {
    var why = runReason(p);
    return '前回 ' + (p.modeLabel || '') + ': ' + runLabel(p) + (why ? ' ・ ' + why : '') + (p.finished ? '(' + ago(p.finished) + ')' : '');
  }
  /* あとから解析(測るため)の最中: 行の右に小さな札だけ出す(行は開かない・実行は押せる) */
  function renderPost(node, id) {
    var p = postByVideo[id], pill = $('.pt-case-post', node), on = active(p);
    if (!on) { if (pill) pill.remove(); return; }
    if (!pill) {
      pill = el('span', 'pill run pt-case-post', 'あとから解析(測るため) 実行中');
      pill.title = '依頼の区間と自動の候補を比べるためだけの解析です(友人には何も届きません)。「まとめて実行」を押すと止まり、終わったあとで続きます';
      var row = $('.pt-case-row', node), nx = $('.pt-case-next', node);
      if (row) row.insertBefore(pill, nx && nx.parentNode === row ? nx : null);
    }
  }
  function renderAuto(node, id) {
    renderPost(node, id);
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
      li.appendChild(el('span', 'pill ' + (STEP_PILL[st.state] || 'wait'), st.label + ' ' + (window.UIKit && UIKit.autorun ? UIKit.autorun.stepLabel(st) : (STEP_STATE[st.state] || st.state))));
      if (st.detail) li.appendChild(el('span', 'hint', st.detail));
      ol.appendChild(li);
    });
    if (past) { msg.textContent = pastText(past); return; }
    msg.textContent = r.modeLabel + ': ' + runLabel(r) + (r.error ? ' ・ ' + r.error : '') + (r.finished ? '(' + when(r.finished) + ')' : '');
  }

  /* 編集で文書を開くリンク。文書 ID で開く(B-1: 動画のパスだと、同じ動画から作った別の文書 = いちばん新しい文書が開いていた)。
     パスは文書が見つからなかったときの予備(編集の takeUrlParams が ?doc= を先に見る) */
  function docHref(id, path, tab) {
    var q = [];
    if (id) q.push('doc=' + encodeURIComponent(id));
    if (path) q.push('media=' + encodeURIComponent(path));
    return '/transcribe/' + (q.length ? '?' + q.join('&') : '') + '#' + (tab || 'tx');
  }
  /* その配信をスタジオの ③ 確認で開く(案件の id = スタジオの配信の id。スタジオが ?video= を確かめ、保存済みなら ③ で開く。B-8) */
  function studioHref(id) { return '/studio/?video=' + encodeURIComponent(id); }
  /* 案件の「次にやること」の行き先(S-6・S-18)。候補の確認・書き出し・文字起こし = スタジオの ③ でその配信を開く・
     校正・パック = 最初に残っている切り抜きの文書を編集で開く(そのタブへ)。スタジオから消えた配信は ③ で開けないので、
     文字起こしは残っている切り抜きを編集で開く。行き先が無ければ '' */
  function caseNextHref(c, kind) {
    var clips = c.clips || [];
    for (var i = 0; i < clips.length; i++) {
      var cl = clips[i], t = cl.transcript, path = cl.exists ? cl.path : '';
      if (kind === 'proof' && t && t.proofed < t.segments) return docHref(t.id, path, 'tx');
      if (kind === 'pack' && t && !cl.pack) return docHref(t.id, path, 'pack');
      if (kind === 'transcribe' && c.gone && !t && path) return '/transcribe/?media=' + encodeURIComponent(path) + '#tx';
    }
    return kind === 'proof' || kind === 'pack' || c.gone ? '' : studioHref(c.id);
  }
  var NEXT_TITLE = { review: 'スタジオの ③ 確認でこの配信を開きます(候補を採用・見送りする)', export: 'スタジオの ③ 確認でこの配信を開きます(採用したマークを書き出す)',
    transcribe: 'スタジオの ③ 確認でこの配信を開きます(書き出した切り抜きを文字起こしする)', proof: '編集で、校正が残っている切り抜きの文書を開きます',
    pack: '編集で、パックがまだの切り抜きの文書を「3 パック」のタブで開きます' };
  /* 案件の行の「次にやること」(S-18): 押せるボタン(同じ窓で移る)。行き先が無ければ押せない札。見送り・投稿済みの案件には出さない(次にやることと同じ。B-4) */
  function paintNext(node, c) {
    var a = $('.pt-case-next', node), n = c.next;
    a.hidden = !n || !!DONE_STATUS[c.status];
    if (a.hidden) return;
    var href = caseNextHref(c, n.kind);
    a.textContent = n.label + ' ' + n.count + (n.kind === 'review' ? '個' : '本');
    if (href) { a.href = href; a.title = NEXT_TITLE[n.kind] || ''; a.className = 'btn small ui-next-btn pt-case-next'; }   // 見た目は ui-kit の次の一手のボタン(v21。編集の履歴と同じ)
    else { a.removeAttribute('href'); a.title = c.gone ? 'スタジオから消えた配信なので、ここからは開けません' : '「編集」で開ける切り抜きがありません。スタジオで切り抜きを書き出してください'; a.className = 'ui-next-btn pt-case-next'; }   // 行き先が無い = 押せない案内の文字だけ(理由は title。S6)
  }

  function caseSubText(c) {
    var parts = [c.channel || '(配信者不明)'];
    if (c.streamedAt && window.UIKit && UIKit.fmt) parts.push(UIKit.fmt.ago(c.streamedAt));
    parts.push('切り抜き ' + c.marks.exported + '本');
    if (c.gone) parts.push('スタジオから消えた配信(最後に見えた内容)');
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
    var pill = $('.pt-case-statuspill', node);
    pill.className = 'pill pt-case-statuspill' + (STATUS_PILL[c.status || ''] ? ' ' + STATUS_PILL[c.status || ''] : '');
    pill.textContent = STATUS[c.status || ''];
    var tx = $('.pt-case-tx', node), txt = txSummaryText(c.tx);
    tx.hidden = !txt; tx.textContent = txt;
    var pk = $('.pt-case-pack', node), pkt = packSummaryText(c.packs);
    pk.hidden = !pkt; pk.textContent = pkt;
    paintNext(node, c);
    paintCaseAuto(node, c);
    if (c.gone) node.dataset.gone = '1';
    markHid(node, 'cases', c.id, $('.pt-case-main', node));

    // 「自動の切り抜き: 未確認」で絞ったときは、その配信の行を開いて切り抜きを見せる(自分で閉じた行は閉じたまま)
    node.open = openCases[c.id] != null ? !!openCases[c.id] || active(runsByVideo[c.id]) : active(runsByVideo[c.id]) || (autoOnly && !!(c.autoClips && c.autoClips.unconfirmed));
    $('.pt-case-row', node).addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('a[href], button')) return;   // 行の中のボタン(次にやること)は行を開閉しない・移るのを止めない
      if (node.open && active(runsByVideo[c.id])) { e.preventDefault(); return; }
      setTimeout(function () { openCases[c.id] = node.open; }, 0);
    });

    var sel = $('.pt-case-status', node);
    sel.value = c.status || '';
    sel.addEventListener('change', function () {
      api('/api/cases/update', 'POST', { id: c.id, status: sel.value }).then(function (r) {
        c.status = r.status; toast('状態を「' + STATUS[r.status] + '」にしました', 'ok');
        pill.className = 'pill pt-case-statuspill' + (STATUS_PILL[r.status] ? ' ' + STATUS_PILL[r.status] : '');
        pill.textContent = STATUS[r.status];
        paintNext(node, c);
        updateSummaryLine();
      }).catch(function (e) {
        var want = sel.value;
        sel.value = c.status || '';
        failToast('状態を保存できませんでした', '少し待って、もう一度選んでください', e, function () { sel.value = want; sel.dispatchEvent(new Event('change')); });
      });
    });
    // B-8(段1): その配信をスタジオの ③ 確認で開く(案件の id = スタジオの配信の id。スタジオが ?video= を正規表現で確かめ、保存済みなら ③ で開く)。
    // スタジオから消えた配信は開いても ① に落ちるので出さない。場所は /studio/ の直書き(docHref が /transcribe/ を直書きしているのと同じ。取り込みに失敗して子プロセスで動いたときは合わない → B-7 で見直す候補)
    if (!c.gone) $('.pt-case-studio', node).appendChild(link('スタジオで開く', studioHref(c.id)));
    if (hideApi()) $('.pt-case-studio', node).parentNode.appendChild(hideBtn('cases', c.id, c.title || c.id));
    fillClips(node, c);
    wireAuto(node, c);
    var ta = $('textarea', node);
    var draft = draftFor(c.id);
    ta.value = draft.memo != null ? draft.memo : (c.memo || '');   // 未保存の入力を再描画でも保つ(E2 finding 1)
    if (ta.value) $('.pt-case-memo', node).open = true;
    ta.addEventListener('input', function () {
      draftFor(c.id).memo = ta.value;
      var st = memoSave[c.id];
      if (st && !st.busy && st.msg) { st.msg = ''; memoUi(c.id); }   // 前の保存の結果の文は、書き足したら消す(「保存しました」のまま未保存にしない)
    });
    $('.pt-memo-save', node).addEventListener('click', function () { draftFor(c.id).memo = ta.value; saveMemo(c.id); });
    memoUi(c.id, node);   // 保存中に再描画されても「保存中…」・結果の文を保つ
    return node;
  }

  /* ---- メモの保存(監査 14)。書き込む先は ID で今の行(#case-<id>)と今の案件の一覧から引く(応答を待つ間に再描画で行が作り直されるため) ---- */
  function caseById(id) {
    var list = (casesData && casesData.cases) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  function memoNow(id) {   // 今の下書き(無ければ行の欄・保存済みの値)
    var d = caseDrafts[id];
    if (d && d.memo != null) return d.memo;
    var node = document.getElementById('case-' + id), ta = node && $('textarea', node);
    if (ta) return ta.value;
    var c = caseById(id);
    return c ? (c.memo || '') : '';
  }
  function memoUi(id, node) {
    node = node || document.getElementById('case-' + id);
    if (!node) return;
    var st = memoSave[id], btn = $('.pt-memo-save', node), msg = $('.pt-memo-msg', node);
    btn.textContent = st && st.busy ? '保存中…' : 'メモを保存';
    if (st && st.busy) btn.setAttribute('aria-busy', 'true'); else btn.removeAttribute('aria-busy');
    msg.textContent = (st && st.msg) || '';
    msg.title = (st && st.msg && st.detail) || '';
  }
  /* 送るのは1つずつ。送っている間に押し直したら again にして、応答のあとで今の下書きを1回だけ送る。
     「保存しました」は、送った値と今の下書きが同じときだけ(違えば下書きを残して、まだ保存していないと出す) */
  function saveMemo(id) {
    var st = memoSave[id] || (memoSave[id] = { busy: false, sent: null, again: false, msg: '' });
    if (st.busy) { st.again = true; return; }
    var value = memoNow(id);
    st.busy = true; st.sent = value; st.again = false; st.msg = '';
    memoUi(id);
    api('/api/cases/update', 'POST', { id: id, memo: value }).then(function (r) {
      var c = caseById(id);
      if (c) c.memo = r.memo;
      st.busy = false;
      var now = memoNow(id);
      if (st.again && now !== st.sent) { saveMemo(id); return; }   // 押し直しの分(今の下書き)を送る
      st.again = false;
      if (now === st.sent) {
        var d = caseDrafts[id]; if (d) delete d.memo;   // 保存できたので下書きは要らない
        st.msg = '保存しました';
      } else {
        st.msg = '保存しました(そのあとの入力はまだ保存していません)';
      }
      memoUi(id);
    }, function (e) {
      st.busy = false;
      if (st.again) { saveMemo(id); return; }   // 失敗のあとでも、押し直した分は送る
      st.msg = '保存できませんでした。もう一度「メモを保存」を押してください';   // 原文(HTTP の番号など)は title に
      st.detail = detailOf(e);
      memoUi(id);
    });
  }

  function wireGroup(g, key, ids) {
    $('summary', g).addEventListener('click', function (e) {
      if (g.open && activeIn(ids)) { e.preventDefault(); return; }
      setTimeout(function () { setGroupOpen(key, g.open); }, 0);
    });
  }

  /* noHide: 非表示かどうかを見ない(「非表示 n件を表示」の数を数えるため)。実行中の案件は隠していても出す */
  function visible(c, noHide) {
    if (!noHide && isHid('cases', c.id) && !showHid('cases') && !active(runsByVideo[c.id])) return false;
    var fs = $('#fStatus').value, q = $('#fText').value.trim().toLowerCase();
    if (autoOnly && !(c.autoClips && c.autoClips.unconfirmed)) return false;   // 「自動の切り抜き: 未確認」の絞り込み
    if (fs === 'none' && c.status) return false;
    if (fs && fs !== 'none' && c.status !== fs) return false;
    if (q && ((c.title || '') + ' ' + (c.channel || '')).toLowerCase().indexOf(q) < 0) return false;
    return true;
  }
  function sortList(list) {
    var key = $('#fSort').value;
    if (key === 'remaining') list.sort(function (a, b) { return (b.remaining || 0) - (a.remaining || 0) || (b.streamedAt || 0) - (a.streamedAt || 0); });
    else if (key === 'channel') list.sort(function (a, b) { return (a.channel || '').localeCompare(b.channel || '', 'ja') || (a.title || '').localeCompare(b.title || '', 'ja'); });
    else if (key === 'title') list.sort(function (a, b) { return (a.title || '').localeCompare(b.title || '', 'ja'); });
    else list.sort(function (a, b) { return (b.streamedAt || 0) - (a.streamedAt || 0); });
  }
  function groupKeyOf(c) {
    var g = $('#fGroup').value;
    if (g === 'channel') return c.channel || '(配信者不明)';
    if (g === 'status') return STATUS[c.status || ''];
    return '';
  }

  /* 再描画で入力中のフォーカス・カーソル位置を失わないように、一覧を作り直す前後で保つ(E2 finding 1:
     alt-tab で戻ったときの refreshCases → render が、行の中で入力中だったフォーカスを消してしまっていた) */
  function captureFocus(container) {
    var a = document.activeElement;
    if (!a || !container || !container.contains(a)) return null;
    var card = a.closest ? a.closest('.pt-case') : null;
    if (!card) return null;
    var role = a.classList.contains('pt-auto-streamer') ? 'streamer' : a.tagName === 'TEXTAREA' ? 'memo'
      : a.classList.contains('pt-case-status') ? 'status' : a.classList.contains('pt-auto-cancel') ? 'cancel' : a.classList.contains('pt-auto-run') ? 'run' : null;
    if (!role) return null;
    var info = { id: card.dataset.id, role: role };
    if (typeof a.selectionStart === 'number') { info.selStart = a.selectionStart; info.selEnd = a.selectionEnd; }
    return info;
  }
  function restoreFocus(info) {
    if (!info) return;
    var card = document.getElementById('case-' + info.id);
    if (!card) return;
    var sel = { memo: 'textarea', streamer: '.pt-auto-streamer', status: '.pt-case-status', cancel: '.pt-auto-cancel', run: '.pt-auto-run' }[info.role];
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
    var totalCount = full.length, gval = $('#fGroup').value;
    var fullCount = {};
    if (gval) full.forEach(function (c) { var k = groupKeyOf(c); fullCount[k] = (fullCount[k] || 0) + 1; });
    var shown = full.slice(0, Math.max(0, visibleCount));

    var list = $('#list');
    list.textContent = '';
    if (!shown.length) {
      list.appendChild(casesData.cases.length ? emptyFiltered() : emptyCases());
    } else if (!gval) {
      shown.forEach(function (c) { list.appendChild(caseCard(c)); });
    } else {
      var order = [], bucket = {};
      shown.forEach(function (c) { var k = groupKeyOf(c); if (!bucket[k]) { bucket[k] = []; order.push(k); } bucket[k].push(c); });
      order.forEach(function (k) {
        var key = gval + ':' + k, ids = bucket[k].map(function (c) { return c.id; });
        var g = $('#tplGroup').content.firstElementChild.cloneNode(true);
        g.dataset.key = key;
        $('.pt-group-label', g).textContent = k;
        $('.ui-group-n', g).textContent = (fullCount[k] || bucket[k].length) + '件';
        var body = $('.pt-group-body', g);
        bucket[k].forEach(function (c) { body.appendChild(caseCard(c)); });
        g.open = !!groupOpenMap()[key] || activeIn(ids);
        wireGroup(g, key, ids);
        list.appendChild(g);
      });
    }

    var moreBox = $('#moreBox'), moreBtn = $('#btnMore'), rest = totalCount - shown.length;
    moreBox.hidden = rest <= 0;
    if (rest > 0) moreBtn.textContent = 'もっと見る(あと ' + rest + ' 件)';
    hideToggle('#casesHidden', 'cases', casesData.cases.filter(function (c) { return visible(c, true) && isHid('cases', c.id) && !active(runsByVideo[c.id]); }).length);
    paintAutoFilter();
    var narrowed = gval || $('#fStatus').value || $('#fText').value.trim() || autoOnly;
    // 絞り込んだときは「合う数 / 全体の数」(分母は全体。「もっと見る」で隠れている分は別に書く。S5)
    $('#count').textContent = (narrowed ? totalCount + ' / ' + casesData.cases.length + ' 件' : totalCount + ' 件') + (rest > 0 ? '(' + shown.length + ' 件を表示)' : '');
    restoreFocus(focusInfo);
    updateSummaryLine();
  }
  function resetPaging() { visibleCount = PAGE_SIZE; render(); }
  /* 絞り込みで 0 件のとき(M5): 条件を消すボタン。条件が空なのに 0 件 = 全部が非表示 → 非表示を出すボタン */
  function emptyFiltered() {
    var filtered = $('#fStatus').value || $('#fText').value.trim();
    if (autoOnly && !filtered) {   // 自動の切り抜きの未確認だけで絞って 0 件 = 全部確かめ終えた
      return emptyBox('未確認の自動の切り抜きはありません', '自動でできた切り抜きは、全部 見た・届けた・片付けた のどれかです。', { label: '全部の配信に戻す', fn: function () {
        autoOnly = false; resetPaging(); $('#autoFilter').focus({ preventScroll: true });
      } });
    }
    if (!filtered) {
      return emptyBox('表示できる配信はありません', 'すべて非表示にしています。「非表示のものも出す」と、また見られます。',
        { label: '非表示のものも出す', fn: function () { if (window.UIKit && UIKit.hide) UIKit.hide.setShowing('cases', true); } });
    }
    return emptyBox('条件に合う配信はありません', '絞り込みを消すと、全部の配信が出ます。', { label: '絞り込みを消す', fn: function () {
      $('#fText').value = ''; $('#fStatus').value = ''; lsSet('status', ''); autoOnly = false; resetPaging(); $('#fText').focus({ preventScroll: true });
    } });
  }
  /* 続きを出したあと、最初に増えた行へフォーカスを移す(ボタンが消えても、押した場所を失わない。M6) */
  function focusNewRow(sel, from) {
    var rows = $all(sel), r = rows[from] || rows[rows.length - 1], t = firstFocusable(r);
    if (t) t.focus({ preventScroll: false });
  }

  /* 配信が 1 本も無いときの空の表示(S-13): 2 文 + 次に押すボタン(スタジオで配信を探す・依頼の受付を設定する) */
  function emptyCases() {
    var box = el('div', 'empty pt-empty');
    box.appendChild(el('b', '', 'まだ配信はありません'));
    box.appendChild(document.createTextNode('切り抜きスタジオで配信を探して解析するか、友人からの依頼を受け付けると、ここに出ます。'));
    var row = el('div', 'row pt-empty-acts');
    var a = el('a', 'btn small primary', 'スタジオで配信を探す');
    a.id = 'emptyStudio'; a.href = '/studio/?step=rank'; a.title = 'スタジオの ① 探す を開きます(① 探す・② 解析で配信を入れます)';
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
  /* 「依頼の受付」を開いて、最初に入れる欄へ(見張るフォルダが空ならフォルダ、入っていれば「依頼を受け付ける」のスイッチ) */
  function openIntakeSettings() {
    var box = $('#intakeBox');
    box.open = true;
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    ($('#intakeFolder').value.trim() ? $('#intakeEnabled') : $('#intakeFolder')).focus({ preventScroll: true });
  }

  /* 「作業データのバックアップ」を開いて、最初に入れる欄へ(写す先が空ならフォルダ、入っていれば「自動でバックアップする」のスイッチ) */
  function openBackupSettings() {
    var box = $('#backupBox');
    box.open = true;
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    ($('#backupFolder').value.trim() ? $('#backupEnabled') : $('#backupFolder')).focus({ preventScroll: true });
  }

  function updateSummaryLine() {
    if (!casesData) return;
    var n = { '': 0, working: 0, posted: 0, skipped: 0 };
    var hid = 0;
    casesData.cases.forEach(function (c) { n[c.status || ''] = (n[c.status || ''] || 0) + 1; if (isHid('cases', c.id)) hid++; });
    $('#summary').textContent = '配信 ' + casesData.cases.length + ' 本(作業中 ' + n.working + '・投稿済み ' + n.posted + '・見送り ' + n.skipped + '・未設定 ' + n[''] + ')' +
      (hid ? ' ・ 非表示 ' + hid + ' 本' : '');
  }

  var casesLoadFailed = false;
  function loadCases() {
    return api('/api/cases').then(function (j) { casesLoadFailed = false; casesData = j; resetPaging(); }).catch(function (e) {
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
    return Promise.all([loadCases(), loadTxList()]).then(function () { renderDocs(); buildTodo(); if (!casesLoadFailed) toast('読み込み直しました'); });
  }
  function refreshCases() {
    // render() だけでなく、案件の一覧から組み立てる「次にやること」・「単体の文字起こし」も一緒に作り直す
    // (E2 finding 1: 前は render() だけで、alt-tab で戻ったときにこの2つが古いままだった)
    return api('/api/cases').then(function (j) { casesLoadFailed = false; casesData = j; render(); renderDocs(); buildTodo(); }).catch(function () { /* 次の読み込みで直る */ });
  }

  function restoreFilters() {
    var st = lsGet('status', ''), so = lsGet('sort', 'new'), gr = lsGet('group', '');
    if ($('#fStatus').querySelector('option[value="' + st + '"]')) $('#fStatus').value = st;
    if ($('#fSort').querySelector('option[value="' + so + '"]')) $('#fSort').value = so;
    if ($('#fGroup').querySelector('option[value="' + gr + '"]')) $('#fGroup').value = gr;
  }

  /* ================================================================ 単体の文字起こし(紐づかない文書。旧・案件画面の下の一覧を拡張) ================================================================ */

  function loadTxList() {
    return fetchT('/transcribe/api/transcripts', { cache: 'no-store' }, 8000).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    }).then(function (j) {
      txList = (j && j.items) || [];
      txById = {};
      txList.forEach(function (it) { txById[it.id] = it; });
    }).catch(function () { txList = null; txById = {}; });   // 「編集」が動いていない・取り込まれていないときは、案件の一覧の項目だけで表示する
  }

  function mergedDoc(u) {
    var tx = txById[u.id];
    if (!tx) return { id: u.id, title: u.title || u.id, rows: u.segments, proofed: u.proofed, pack: null, packKnown: false, updatedAt: u.updatedAt || 0, sourcePath: u.sourcePath,
                      fileName: baseName(u.sourcePath) };
    return { id: u.id, title: tx.streamTitle || tx.clipTitle || tx.title || u.title || u.id, rows: tx.rows, proofed: tx.proofed, pack: tx.pack, packStale: tx.packStale,
             packKnown: true, updatedAt: tx.updatedAt || u.updatedAt || 0, sourcePath: u.sourcePath, fileName: tx.sourceName || baseName(u.sourcePath) };
  }
  /* 同じ題名の文書を見分ける副題(S-26): 元のファイル名・更新日時 */
  function docSubText(fileName, updatedAt) { return [fileName || '', updatedAt ? '更新 ' + ago(updatedAt) : ''].filter(Boolean).join(' ・ '); }

  function docSearchList(noHide) {
    var q = $('#docSearch').value.trim().toLowerCase();
    var list = ((casesData && casesData.unlinked) || []).filter(function (u) { return noHide || !isHid('transcripts', u.id) || showHid('transcripts'); });
    if (q) list = list.filter(function (u) { return (mergedDoc(u).title || '').toLowerCase().indexOf(q) >= 0; });
    list.sort(function (a, b) { return (mergedDoc(b).updatedAt || 0) - (mergedDoc(a).updatedAt || 0); });
    return list;
  }

  function docCard(u) {
    var d = mergedDoc(u);
    var li = $('#tplDoc').content.firstElementChild.cloneNode(true);
    li.id = 'doc-' + d.id;
    li.dataset.id = d.id;
    li.setAttribute('data-fkey', 'transcripts:' + d.id);
    $('.pt-doc-title', li).textContent = d.title;
    var sub = $('.pt-doc-sub', li);
    sub.textContent = docSubText(d.fileName, d.updatedAt);
    sub.title = d.sourcePath || '';   // フルパスは title だけ(ui-guidelines 4)
    var txt = d.rows ? ('校正 ' + (d.proofed || 0) + '/' + d.rows + '行') : '文字起こし まだ';
    if (d.packKnown) txt += d.pack ? (d.packStale ? ' ・ パック 作り直しが要る' : ' ・ パック済み') : ' ・ パック まだ';
    $('.pt-doc-tx', li).textContent = txt;
    var chk = $('.pt-doc-check', li);
    chk.checked = !!docPicked[d.id];
    chk.addEventListener('change', function () { if (chk.checked) docPicked[d.id] = true; else delete docPicked[d.id]; syncDocRunButton(); });
    var openA = $('.pt-doc-open', li);
    openA.href = docHref(d.id, d.sourcePath, 'tx'); openA.removeAttribute('aria-disabled');   // 文書 ID で開く(動画が無くても文書は開ける)
    if (hideApi()) $('.pt-doc-steps', li).appendChild(hideBtn('transcripts', d.id, d.title));
    markHid(li, 'transcripts', d.id, $('.pt-doc-main', li).parentNode);
    return li;
  }

  function renderDocRun(id) {
    var li = document.getElementById('doc-' + id); if (!li) return;
    var r = runsByDoc[id], past = r ? null : pastByDoc[id], pill = $('.pt-doc-runpill', li), msg = $('.pt-doc-runmsg', li);
    if (msg) { msg.hidden = !past; msg.textContent = past ? pastText(past) : ''; }   // 前回の結果(入口を起動し直したあと。段2 B-6)
    if (!r && past && past.state === 'error') r = past;
    if (r && r.state === 'error') {   // 失敗は札に残す(以前は終わると消えて、失敗したことが分からなかった。S-5)
      pill.hidden = false; pill.className = 'pill pt-doc-runpill err'; pill.textContent = '失敗'; pill.title = r.error || ''; return;
    }
    if (!active(r)) { pill.hidden = true; return; }
    pill.hidden = false;
    pill.className = 'pill pt-doc-runpill ' + (r.state === 'running' ? 'run' : 'wait');
    pill.textContent = r.state === 'running' ? '実行中' : '待ち';
  }

  /* 押せないボタンには理由を title に(A-34)。押せるときは title を外す */
  function offBtn(b, off, why) { b.disabled = !!off; if (off) b.title = why; else b.removeAttribute('title'); }
  var DOC_BATCH_MAX = 20;   // まとめて実行に一度に入れられる文書の数(src/home/autorun.py の MAX_WAITING)
  function syncDocRunButton() {
    var n = Object.keys(docPicked).length;
    offBtn($('#docRunBtn'), !n || n > DOC_BATCH_MAX, n ? '一度に ' + DOC_BATCH_MAX + ' 本までです。選びを減らすと押せます' : '文字起こしを選ぶと押せます(一覧の左のチェック)');
    $('#docPickHint').textContent = n > DOC_BATCH_MAX ? n + '本を選んでいます(一度に ' + DOC_BATCH_MAX + ' 本までです)'
      : n ? (n + '本を選んでいます(' + DOC_BATCH_MAX + ' 本まで)') : '文字起こしを選んでください(一覧の左のチェック。' + DOC_BATCH_MAX + ' 本まで)';
  }
  /* 表示中を全部選ぶ / パックが無いものだけ選ぶ(S-11)。20 本までにして、あふれたら知らせる */
  function pickDocs(onlyNoPack) {
    var shown = docSearchList().slice(0, Math.max(0, docVisibleCount)).map(mergedDoc).filter(function (d) { return !onlyNoPack || (d.packKnown && !d.pack); });
    docPicked = {};
    shown.slice(0, DOC_BATCH_MAX).forEach(function (d) { docPicked[d.id] = true; });
    renderDocs();
    if (shown.length > DOC_BATCH_MAX) toast('一度に選べるのは ' + DOC_BATCH_MAX + ' 本までです(上から ' + DOC_BATCH_MAX + ' 本を選びました)', 'info');
    else if (!shown.length) toast(onlyNoPack ? 'パックが無い文字起こしはありません' : '選べる文字起こしがありません', 'info');
  }

  function renderDocs() {
    var total = (casesData && casesData.unlinked && casesData.unlinked.length) || 0;
    $('#unlinkedGroup').hidden = !total; $('#unlinkedHead').hidden = !total;
    if (!total) return;
    $('#unlinkedCount').textContent = total + '件';   // ホームの数(txindex の unlinked)。「編集」の履歴の「それ以外」(!hasClip)とは集合が少し違うので、あちらの件数とは比べない
    var full = docSearchList();
    var shown = full.slice(0, Math.max(0, docVisibleCount));
    var ul = $('#docList');
    ul.textContent = '';
    shown.forEach(function (u) { ul.appendChild(docCard(u)); });
    var de = $('#docEmpty'); de.hidden = !!shown.length;   // 検索で 0 件のとき(M5)
    if (!shown.length) {
      if ($('#docSearch').value.trim()) emptyBox('条件に合う文字起こしはありません', '検索を消すと、全部の文字起こしが出ます。', { label: '検索を消す', fn: function () { $('#docSearch').value = ''; resetDocPaging(); $('#docSearch').focus(); } }, de);
      else emptyBox('表示できる文字起こしはありません', 'すべて非表示にしています。「非表示のものも出す」と、また見られます。', { label: '非表示のものも出す', fn: function () { if (window.UIKit && UIKit.hide) UIKit.hide.setShowing('transcripts', true); } }, de);
    }
    Object.keys(runsByDoc).concat(Object.keys(pastByDoc)).forEach(renderDocRun);
    hideToggle('#docHidden', 'transcripts', docSearchList(true).filter(function (u) { return isHid('transcripts', u.id); }).length);
    var narrowed = $('#docSearch').value.trim();
    var restN = full.length - shown.length;
    $('#docCount').textContent = (narrowed ? full.length + ' / ' + total + ' 件' : full.length + ' 件') + (restN > 0 ? '(' + shown.length + ' 件を表示)' : '');   // 分母は全体(S5)
    var rest = restN;
    $('#docMoreBox').hidden = rest <= 0;
    if (rest > 0) $('#docMore').textContent = 'もっと見る(あと ' + rest + ' 件)';
    syncDocRunButton();
  }
  function resetDocPaging() { docVisibleCount = DOC_PAGE; renderDocs(); }

  function runDocsBatch() {
    var ids = Object.keys(docPicked);
    if (!ids.length) return;
    var body = { ids: ids, overwrite: $('#docOverwrite').checked };
    var who = $('#docWho').value.trim();
    if (who) body.streamer = who;
    offBtn($('#docRunBtn'), true, '始めています。少し待ってください');
    var ar = window.UIKit && UIKit.autorun;
    var go = ar ? ar.start('api/autorun/start-docs', body, { ids: ids, overwrite: body.overwrite }) : api('/api/autorun/start-docs', 'POST', body);
    go.then(function (r) {
      if (!r) { syncDocRunButton(); return; }   // やることが無い(見積もり)
      (r.runs || []).forEach(function (run) { runsByDoc[run.docId] = run; });
      docPicked = {};
      renderDocs();
      pollAuto();
      if (!ar) toast(r.runs.length + '件を始めました', 'ok');
    }).catch(function (e) { failToast('まとめて実行を始められませんでした', 'もう一度「選んだ文字起こしをまとめて実行」を押してください', e); syncDocRunButton(); });
  }

  /* ================================================================ 調子(段9 9-1。/api/health。数字は入口、良い/注意/悪い の判定はここ) ================================================================ */
  var GB = 1024 * 1024 * 1024;
  function fmtBytes(b) { b = Number(b) || 0; return b >= GB ? (b / GB).toFixed(b >= 10 * GB ? 0 : 1) + ' GB' : b >= 1048576 ? Math.round(b / 1048576) + ' MB' : b >= 1024 ? Math.round(b / 1024) + ' KB' : b + ' B'; }
  function fmtAgo(sec) { sec = Number(sec) || 0; return sec < 90 ? Math.round(sec) + ' 秒前' : sec < 5400 ? Math.round(sec / 60) + ' 分前' : sec < 172800 ? Math.round(sec / 3600) + ' 時間前' : Math.round(sec / 86400) + ' 日前'; }
  var healthBusy = false, healthTimer = 0;
  /* ================================================================ 片付け(段9 9-2。/api/cleanup。候補 → 選ぶ → ごみ箱フォルダへ移す) ================================================================ */
  var cleanData = null, cleanBusy = false;
  function loadCleanup() {
    if (cleanBusy) return;
    cleanBusy = true;
    $('#cleanWhen').textContent = '探しています…';
    api('/api/cleanup').then(renderCleanup, function (e) {
      $('#cleanWhen').textContent = '';
      var box = $('#cleanKinds'); box.textContent = '';
      var p = el('p', 'hint', failText('候補を読めませんでした', '「候補を探す」をもう一度押してください', e)); p.title = detailOf(e);
      box.appendChild(p);
    }).then(function () { cleanBusy = false; });
  }
  function cleanPicked() { return Array.prototype.map.call(document.querySelectorAll('#cleanKinds input[data-id]:checked'), function (c) { return c.getAttribute('data-id'); }); }
  function cleanSync() {
    var ids = cleanPicked(), bytes = 0;
    (cleanData && cleanData.kinds || []).forEach(function (k) { k.items.forEach(function (i) { if (ids.indexOf(i.id) >= 0) bytes += i.bytes; }); });
    $('#cleanSel').textContent = ids.length ? ids.length + ' 件・' + fmtBytes(bytes) + ' を選んでいます' : '';
    offBtn($('#btnCleanMove'), !ids.length, '先に「候補を探す」を押し、移す物にチェックを付けると押せます');
  }
  function renderCleanup(d) {
    cleanData = d;
    $('#cleanWhen').textContent = '候補 ' + fmtBytes(d.bytes);
    $('#cleanDays').textContent = d.keepDays;
    var box = $('#cleanKinds'); box.textContent = '';
    d.kinds.forEach(function (k) {
      var det = el('details'), sum = el('summary');
      var all = el('input'); all.type = 'checkbox'; all.disabled = !k.count; all.setAttribute('aria-label', k.label + 'をすべて選ぶ');
      sum.appendChild(all); sum.appendChild(document.createTextNode(' ' + k.label + ' — ' + k.count + ' 件・' + fmtBytes(k.bytes)));
      det.appendChild(sum);
      var ul = el('ul');
      k.items.forEach(function (i) {
        var li = el('li'), lb = el('label'), cb = el('input');
        cb.type = 'checkbox'; cb.setAttribute('data-id', i.id);
        lb.appendChild(cb);
        lb.appendChild(el('span', '', i.name + '(' + fmtBytes(i.bytes) + (i.extra && i.extra.length ? '・途中のファイル ' + i.extra.length + ' 個も' : '') + ')'));
        if (i.note) lb.appendChild(el('span', 'hint', i.note));
        lb.title = i.path;
        li.appendChild(lb); ul.appendChild(li);
      });
      if (!k.count) ul.appendChild(el('li', 'hint', 'ありません'));
      det.appendChild(ul);
      all.addEventListener('click', function (e) { e.stopPropagation(); });
      all.addEventListener('change', function () { ul.querySelectorAll('input[data-id]').forEach(function (c) { c.checked = all.checked; }); cleanSync(); });
      ul.addEventListener('change', cleanSync);
      box.appendChild(det);
    });
    cleanSync();
  }
  function moveCleanup() {
    var ids = cleanPicked();
    if (!ids.length) return;
    var ask = window.UIKit && UIKit.dialog ? UIKit.dialog.confirm({ title: 'ごみ箱フォルダへ移す', ok: '移す',
      body: $('#cleanSel').textContent + '。ごみ箱フォルダ(動画と同じドライブ)へ移し、' + cleanData.keepDays + ' 日たつとホームの起動時に消えます。それまではエクスプローラーで元の場所へ戻せます(元の場所は、ごみ箱フォルダの中の記録のファイルに書いてあります)。' })
      : Promise.resolve(window.confirm('選んだ物をごみ箱フォルダへ移しますか?'));
    ask.then(function (ok) {
      if (!ok) return;
      offBtn($('#btnCleanMove'), true, '移しています。少し待ってください');
      return api('/api/cleanup', 'POST', { ids: ids }).then(function (r) {
        var msg = r.moved.length + ' 件をごみ箱フォルダへ移しました' + (r.failed.length ? '。' + r.failed.length + ' 件は移せませんでした(使っているツールを閉じてから、もう一度「候補を探す」で選び直してください)' : '');
        if (r.failed.length && window.UIKit && UIKit.toast) UIKit.toast(msg, { kind: 'err', detail: String(r.failed[0].error || '') });
        else toast(msg);
        loadCleanup();
      }, function (e) { failToast('ごみ箱フォルダへ移せませんでした', 'もう一度選んで「移す」を押してください', e); cleanSync(); });
    });
  }

  function loadHealth(refresh) {
    if (healthBusy) return;
    healthBusy = true;
    api('/api/health' + (refresh ? '?refresh=1' : '')).then(function (h) {
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
  function healthRow(state, title, text, subs, tip) {
    var li = el('li'), pill = state === 'info' ? el('span', 'pill info', '測定')   // info = 良い・悪いを決めない数字(精度)
      : el('span', 'pill ' + (state === 'ok' ? 'ok' : state === 'bad' ? 'err' : 'warn'), state === 'ok' ? '問題なし' : state === 'bad' ? '要対応' : '注意');
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
        : healthRow('ok', '外部プログラム', 'ffmpeg ' + t.ffmpeg.version + '・ffprobe ' + t.ffprobe.version + '・yt-dlp ' + t.ytdlp.version, [t.ffmpeg.path, t.ytdlp.path]));
    }
    // 空き容量
    (h.disk || []).forEach(function (d) {
      var st = d.freeBytes < 10 * GB ? 'bad' : d.freeBytes < 30 * GB ? 'warn' : 'ok';
      ul.appendChild(healthRow(st, '空き容量 ' + (d.drive || d.path), fmtBytes(d.freeBytes) + ' / ' + fmtBytes(d.totalBytes) + (st !== 'ok' ? '。片付けを考えてください' : ''), [d.path]));
    });
    // 作業データの大きさ
    if (h.data) {
      var subs = (h.data.dirs || []).map(function (d) {
        var top = (d.items || []).slice(0, 4).map(function (i) { return i.name + ' ' + fmtBytes(i.bytes); }).join('・');
        return d.label + ' ' + fmtBytes(d.bytes) + '(' + d.files + ' ファイル' + (top ? '。' + top : '') + ')';
      });
      ul.appendChild(healthRow(h.data.bytes > 50 * GB ? 'warn' : 'ok', '作業データ ' + fmtBytes(h.data.bytes), h.data.root ? h.data.root : '(各ツールのフォルダの中)', subs));
    } else ul.appendChild(healthRow('warn', '作業データ', '大きさを数えています…'));
    // エラーの件数
    var e = h.errors || {};
    ul.appendChild(healthRow(e.clientLast24h ? 'warn' : 'ok', '画面のエラー(24 時間)', (e.clientLast24h || 0) + ' 件', [e.clientLog]));
    ul.appendChild(healthRow(e.autorunFailedLast7d ? 'warn' : 'ok', 'まとめて実行の失敗(7 日)', (e.autorunFailedLast7d || 0) + ' 件' + (e.autorunFailedLast7d ? '(上の「まとめて実行の記録」に理由)' : ''), [e.autorunLog]));
    // 異常終了(見張り役。git の履歴(679ff01 以前)の docs/plan/stability-review-2026-10.md)。OS 側が増えたら PC の不安定、アプリ側だけならこのツールの不具合の目安
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
      var lst = r.freeBytes == null ? 'warn' : r.freeBytes < 10 * GB ? 'bad' : r.freeBytes < 30 * GB ? 'warn' : 'ok';
      var st = !r.folderOk || r.streamlink === false || (r.expected && r.version !== r.expected) ? 'bad' : lst;
      var text = (r.active ? '録画中 ' + r.active + ' 本' : '録画していません') + '・空き ' + (r.freeBytes != null ? fmtBytes(r.freeBytes) + ' / ' + fmtBytes(r.totalBytes) : '不明')
        + (r.expected && r.version !== r.expected ? '。版が違います(動いているのは ' + r.version + '、ファイルは ' + r.expected + '。録画中でなければ、ホームが 30 秒以内に起動し直します)' : '')
        + (r.streamlink === false ? '。streamlink が入っていません(setup\install.bat)' : '') + (r.folderMessage ? '。' + r.folderMessage : '');
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
    // リアルタイム切り抜きの失敗(M3。書き出し・まとめて実行へ渡す・文字起こし・パック。文はスタジオの LIVE の帯と同じ = src/home/live_failures.py)
    if (h.live && h.live.failures) {
      var lf = h.live.failures;
      var row = healthRow(lf.length ? 'warn' : 'ok', 'リアルタイム切り抜きの失敗(7 日)', lf.length ? lf.length + ' 件(新しい順。スタジオの LIVE の帯にも同じ文)' : 'なし',
        lf.map(function (x) { return x.text; }));
      row.id = 'liveFailures';
      ul.appendChild(row);
    }
    // 配信中の盛り上がりの検出(L2。検出がオンのときだけ h.live.detect): 動いているか・遅れ・チャット・起動し直しの数(失敗は上の一覧に kind detect で出る)
    if (h.live && h.live.detect) {
      var dd = h.live.detect, recs = dd.recordings || [];
      var chatText = { ok: 'あり', restarting: '起動し直し中', none: 'なし(音だけ)', off: '使わない' };
      var dText = (dd.running ? (recs.length ? '録画 ' + recs.length + ' 本を見ています・遅れ ' + Math.round(dd.behindSec || 0) + ' 秒・チャット ' + (chatText[dd.chat] || dd.chat)
        : '動いています(録画中の配信はありません)') : '止まっています' + (dd.message ? '(' + dd.message + ')' : ''))
        + '・ワーカーの起動し直し ' + (dd.restarts || 0) + ' 回' + (dd.autoAdopt && dd.autoAdopt.enabled ? '・自動の採用 オン(' + dd.autoAdopt.waitMin + ' 分待ち)' : '');
      var dRow = healthRow(!dd.running || dd.error || (dd.restarts || 0) > 3 ? 'warn' : 'ok', '盛り上がりの検出', dText,
        recs.map(function (x) { return x.id + ': 候補 ' + x.peaks + ' 本・遅れ ' + Math.round(x.behindSec || 0) + ' 秒・チャットの遅れ ' + (x.lag == null ? '—' : x.lag + ' 秒') + '・チャット ' + (chatText[x.chat] || x.chat); }));
      dRow.id = 'liveDetectHealth';
      ul.appendChild(dRow);
    }
    // 重い処理
    var hv = h.heavy;
    if (hv) ul.appendChild(healthRow('ok', '重い処理', '実行中 ' + (hv.active || []).length + '・順番待ち ' + (hv.waiting || []).length + '(同時に ' + hv.limit + ' まで)'));
    renderAccuracy(h.accuracy, ul);
  }

  /* ---- 精度(Q3。src/home/accuracy.py): 領域ごとに「直近 x(前回 y)・日時・文書数」。手が空いた夜に 1 日 1 回測る。「今すぐ測る」はいつでも ---- */
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
    if (ac.goals && ac.goals.length) ul.appendChild(goalsRow(ac.goals));
    if (live) accTimer = setTimeout(function () { loadHealth(false); }, 2500);   // 測っている間・手が空くのを待っている間は軽く読み直す
  }
  /* 入口の条件(入口 0.38.0。accuracy.py の GOALS = plan/README.md の 7): 各工程を始めてよい量の「今 / 目標 / あと」を 1 行ずつ。値は直近の測定のもの */
  function goalAmount(v, unit) { return unit === 'sec' ? String(+(v / 60).toFixed(1)) + ' 分' : Math.round(v) + ' ' + unit; }
  function goalsRow(goals) {
    var done = goals.filter(function (g) { return g.reached; }).length, unknown = goals.filter(function (g) { return g.now == null; }).length;
    var plain = function (s) {   // 計画の記号(G1・B4・I-2a など)は本文から外し、元の文は title に(S9)
      return String(s || '').replace(/\([A-Z]-\d+[a-z]?\)/g, '').replace(/(^|・)[A-Z]\d+(?:-[a-z])?\s+/g, '$1').replace(/^[A-Z]\d\s+/, '').trim();
    };
    var subs = goals.map(function (g) {
      var big = g.unit === 'sec' && g.target >= 3600;   // 時間の目標は「時間」で並べる(分と時間が混ざって読み違えないように)
      var amt = function (v) { return big ? String(+(v / 3600).toFixed(2)) + ' 時間' : goalAmount(v, g.unit); };
      var body = g.now == null ? '未測定' : '今 ' + amt(g.now) + ' / 目標 ' + amt(g.target) + ' / ' + (g.reached ? '届いた' : 'あと ' + amt(g.left));
      return { text: plain(g.label) + ': ' + body + '(→ ' + plain(g.opens) + ')', title: g.label + ' → ' + g.opens };
    });
    var text = '届いた ' + done + ' / ' + goals.length + (unknown ? '・未測定 ' + unknown + '(道具が無いか、まだ測っていない。「精度を今すぐ測る」で測れます)' : '');
    var row = healthRow('info', '始める条件(あと何本・何分)', text, subs);
    row.id = 'accuracyGoals';
    return row;
  }
  function accuracyNow() {
    var btn = $('#btnAccuracyNow');
    btn.disabled = true;
    api('api/accuracy/run', 'POST', {}).then(function () { toast('精度の測定を受け付けました(手が空くまで待つことがあります)'); loadHealth(false); },
      function (e) { failToast('精度を測れませんでした', '少し待って、もう一度押してください', e); loadHealth(false); });
  }

  /* ================================================================ 次にやること ================================================================ */

  function buildPathMap() {
    var map = {};
    ((casesData && casesData.cases) || []).forEach(function (c) {
      (c.clips || []).forEach(function (cl) { if (cl.transcript) map[cl.transcript.id] = { path: cl.path, caseId: c.id, kase: c }; });
    });
    ((casesData && casesData.unlinked) || []).forEach(function (u) { if (!map[u.id]) map[u.id] = { path: u.sourcePath, caseId: null, kase: null }; });
    return map;
  }
  /* 案件の状態が「見送り」「投稿済み」なら、次にやることに出さない(B-4。作業をやめた・終えた案件を勧めない) */
  var DONE_STATUS = { skipped: 1, posted: 1 };

  function clipHint(it) {
    // 同じ配信から複数の切り抜きを作ると title(配信の題名)が同じになるので、マークの名前・時間帯で見分けられるようにする(E2 finding 2)
    if (it.markLabel) return it.markLabel;
    if (it.clipStart != null && it.clipEnd != null) return tc(it.clipStart) + '–' + tc(it.clipEnd);
    return '';
  }
  function buildTodoFine() {
    var items = [], pathMap = buildPathMap();
    txList.forEach(function (it) {
      var rows = it.rows || 0, proofed = it.proofed || 0;
      if (!rows) return;
      var title = it.streamTitle || it.clipTitle || it.title || it.markLabel || '(無題)';
      var hint = clipHint(it), suffix = hint ? '(' + hint + ')' : '';
      var loc = pathMap[it.id];
      if (loc && loc.kase && DONE_STATUS[loc.kase.status]) return;
      if (isHid('transcripts', it.id) || (loc && loc.kase && isHid('cases', loc.kase.id))) return;   // 非表示にした文書・案件の作業は勧めない
      /* どの配信か分かるように、配信者と配信日(案件に無ければ文字起こしの配信者)を添える(B-5) */
      var kase = loc && loc.kase, who = (kase && kase.channel) || it.channel || '';
      var day = kase && kase.streamedAt && window.UIKit && UIKit.fmt ? UIKit.fmt.date(kase.streamedAt).split(' ')[0] : '';
      var meta = [who, day ? day + ' の配信' : ''].filter(Boolean).join(' ・ ');
      // 配信に紐づかない文書は同じ題名が並びやすいので、元のファイル名と更新日時も添える(S-26)
      if (!kase) meta = [meta, docSubText(it.sourceName || baseName(loc && loc.path), it.updatedAt)].filter(Boolean).join(' ・ ');
      if (meta) suffix = ' ・ ' + meta + suffix;
      if (proofed < rows) {
        items.push({ kind: 'proof', key: 'proof:' + it.id, updatedAt: it.updatedAt || 0, title: title, sub: '校正 ' + proofed + '/' + rows + '行' + suffix,
          href: docHref(it.id, loc && loc.path, 'tx'), pillText: '校正待ち', pillClass: 'wait' });
      }
      // パック待ち・作り直しは、校正が済んでいて(proofed >= rows)、かつ元の動画の有無を実際に確かめられたとき(mediaOk === true)だけ出す。
      // it.pack が null なのは、まだパックが無いときだけでなく、確かめる時間切れ(PACK_CHECK_BUDGET)・動画が見つからない(mediaOk === false)
      // ときもある(src/editor/serve.py の _files_state)。それらまで「パック待ち」にすると、校正中の文書と重複したり
      // 見当違いの案内になる(E2 finding 2)
      if (proofed >= rows && it.mediaOk === true && (!it.pack || it.packStale)) {
        items.push({ kind: 'pack', key: 'pack:' + it.id, updatedAt: it.updatedAt || 0, title: title, sub: (it.pack ? 'パックの作り直しが要ります' : 'パックがまだありません') + suffix,
          href: docHref(it.id, loc && loc.path, 'pack'), pillText: it.pack ? '作り直し' : 'パック待ち', pillClass: it.pack ? 'warn' : 'wait' });
      }
    });
    return items;
  }
  /* 案件(配信)ごとの作業(S-6。入口 0.42.0): 文字起こし待ち・書き出し待ち・確認前の候補は案件の一覧の todo(cases.py)から、いつも出す
     (リンクはスタジオの ③ でその配信を開く = caseNextHref)。校正待ち・パック待ちは、「編集」の文書の一覧が読めれば文書ごと(buildTodoFine)・
     読めないとき(withDocs が false)だけここで配信ごとに出す */
  var CASE_TODO = [
    ['transcribe', '文字起こし待ち', function (n) { return '文字起こし ' + n + '本(書き出した切り抜き)'; }],
    ['export', '書き出し待ち', function (n) { return '書き出し ' + n + '本(採用したマーク)'; }],
    ['review', '候補の確認待ち', function (n) { return '候補 ' + n + '個(採用・見送りをまだ決めていない)'; }]   // 作業の名前は案件の行のボタン(cases.py の TODO_LABEL)と同じ言葉(S1)
  ];
  function buildTodoCoarse(withDocs) {
    var items = [];
    ((casesData && casesData.cases) || []).forEach(function (c) {
      if (!c.next || DONE_STATUS[c.status] || isHid('cases', c.id)) return;
      var meta = [c.channel, c.streamedAt && window.UIKit && UIKit.fmt ? UIKit.fmt.date(c.streamedAt).split(' ')[0] + ' の配信' : ''].filter(Boolean).join(' ・ ');
      meta = meta ? ' ・ ' + meta : '';
      CASE_TODO.forEach(function (k) {
        var n = active(runsByVideo[c.id]) ? 0 : (c.todo || {})[k[0]] || 0;   // まとめて実行の最中は進行中の行だけ(同じ作業を二重に勧めない)
        if (n) items.push({ kind: k[0], key: k[0] + ':case:' + c.id, updatedAt: c.updatedAt || 0, title: c.title, sub: k[2](n) + meta,
          href: caseNextHref(c, k[0]) || '#case-' + c.id, pillText: k[1], pillClass: 'wait' });
      });
      if (withDocs) return;
      if (c.next.kind === 'proof') items.push({ kind: 'proof', key: 'proof:case:' + c.id, updatedAt: c.updatedAt || 0, title: c.title, sub: '校正 ' + c.next.count + '本' + meta,
        href: '#case-' + c.id, pillText: '校正待ち', pillClass: 'wait' });
      else if (c.next.kind === 'pack') items.push({ kind: 'pack', key: 'pack:case:' + c.id, updatedAt: c.updatedAt || 0, title: c.title, sub: 'パック ' + c.next.count + '本' + meta,
        href: '#case-' + c.id, pillText: 'パック待ち', pillClass: 'wait' });
    });
    return items;
  }
  function runningItems() {
    var items = [];
    function push(r, hrefBase) {
      if (!active(r)) return;
      var total = r.steps.length, doneN = r.steps.filter(function (s) { return s.state === 'done' || s.state === 'skip'; }).length;
      var pct = total ? Math.round(doneN / total * 100) : 0;
      items.push({ kind: 'running', updatedAt: r.created || 0, title: r.title || (r.docId ? '文字起こし' : r.kind === 'file' ? '依頼の動画ファイル' : '配信'),
        sub: r.modeLabel + ' ・ ' + (r.state === 'running' ? pct + '%' : '待ち'), href: hrefBase,
        pillText: r.state === 'running' ? '実行中' : '待ち', pillClass: r.state === 'running' ? 'run' : 'wait',
        progress: r.state === 'running' ? pct : null });
    }
    var known = {};
    ((casesData && casesData.cases) || []).forEach(function (c) { known[c.id] = true; });
    Object.keys(runsByVideo).forEach(function (id) { push(runsByVideo[id], known[id] ? '#case-' + id : '#intake'); });   // 依頼の解析は、案件の行がまだ無いことがある
    Object.keys(runsByFile).forEach(function (id) { push(runsByFile[id], '#intake'); });
    Object.keys(postByVideo).forEach(function (id) { push(postByVideo[id], known[id] ? '#case-' + id : '#intake'); });   // あとから解析(名前で依頼の実行と見分ける)
    Object.keys(runsByDoc).forEach(function (id) { push(runsByDoc[id], '#doc-' + id); });
    return items;
  }

  function todoRow(it) {
    var li = $('#tplTodo').content.firstElementChild.cloneNode(true);
    if (it.key) li.setAttribute('data-fkey', 'todo:' + it.key);
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
    if (it.key && hideApi()) {   // 実行中の行は隠せない(終われば消える)
      var hb = hideBtn('todo', it.key, it.title);
      hb.classList.add('pt-todo-hide');
      li.appendChild(hb);
      markHid(li, 'todo', it.key, $('.pt-todo-main', li));
    }
    return li;
  }
  function renderTodo(all) {
    var box = $('#todoList'), empty = $('#todoEmpty'), more = $('#todoMore');
    var hidN = all.filter(function (it) { return it.key && isHid('todo', it.key); }).length;
    if (!showHid('todo')) all = all.filter(function (it) { return !it.key || !isHid('todo', it.key); });
    hideToggle('#todoHidden', 'todo', hidN);
    box.textContent = '';
    if (!all.length) {
      empty.hidden = false;
      // casesData が無い(案件の一覧をまだ読めていない)ときは「作業は無い」ではなく、読めていないと分かる文言にする(E2 finding 4)
      var go = $('#todoEmptyBtn');
      $('b', empty).textContent = casesData ? 'いま手が要る作業はありません' : '案件の一覧を読み込めていません';
      $('#todoEmptyText').textContent = casesData ? 'スタジオで配信を解析すると、ここに出ます。' : '案件の一覧の欄に、直し方が出ています(「読み込み直す」を押してください)。';
      go.hidden = !casesData;   // 次の一手(スタジオで配信を探す)は、案件の一覧を読めているときだけ
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
  function buildTodo() {
    // casesData が無くても、実行中(running)だけは出せる・空のときの案内も出したい(E2 finding 4: 前は早期リターンで
    // まとめて実行の進み具合すら出なかった)。案件の一覧が要る校正待ち・パック待ちだけ、読めているときに限る
    var running = runningItems();
    var rest = casesData ? (txList ? buildTodoFine() : []).concat(buildTodoCoarse(!!txList)) : [];
    rest.sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); });
    // 進行中 → 仕上げに近い作業から(校正 → パック → 文字起こし → 書き出し → 候補の確認。仕掛かりを先に終わらせる。S-6)。
    // 並びの表は案件の一覧(cases.py の TODO_ORDER)が返す todoOrder と同じ 1 つ: 案件の行のボタン(case.next)も同じ順で決まるので、
    // 同じ配信なら上の一覧の先頭の作業と行のボタンが必ず同じになる(UI の見直し M1)
    var order = (casesData && casesData.todoOrder) || TODO_ORDER;
    var byKind = order.map(function (k) { return rest.filter(function (i) { return i.kind === k; }); });
    renderTodo(running.concat.apply(running, byKind));
  }
  var TODO_ORDER = ['proof', 'pack', 'transcribe', 'export', 'review'];   // 案件の一覧が todoOrder を返さない古いサーバーのときの予備(正は cases.py)

  /* ================================================================ まとめて実行の進み具合(配信・文書。共通の定期読み込み) ================================================================ */

  function pollAuto() {
    clearTimeout(autoTimer);
    api('/api/autorun').then(function (j) {
      var latestV = {}, latestD = {}, latestF = {}, latestP = {}, anyActive = false, finished = false;
      (j.runs || []).forEach(function (r) {
        if (r.mode === POST_MODE) { if (r.videoId && !latestP[r.videoId]) latestP[r.videoId] = r; }
        else if (r.kind === 'doc') { if (r.docId && !latestD[r.docId]) latestD[r.docId] = r; }
        else if (r.kind === 'file' || !r.videoId) latestF[r.id || ('f' + Object.keys(latestF).length)] = r;   // 依頼の文字起こしだけ(配信にも文書にも紐づかない)
        else if (!latestV[r.videoId]) latestV[r.videoId] = r;
      });
      Object.keys(latestF).forEach(function (id) {
        var r = latestF[id];
        if (active(r)) anyActive = true;
        if (wasActiveFile[id] && !active(r)) finished = true;
        wasActiveFile[id] = active(r);
      });
      runsByFile = latestF;
      Object.keys(latestP).forEach(function (id) {
        var r = latestP[id];
        if (active(r)) anyActive = true;
        if (wasActivePost[id] && !active(r)) finished = true;   // 自動マークが増える(案件の表示を新しくする)
        wasActivePost[id] = active(r);
      });
      postByVideo = latestP;
      Object.keys(latestV).forEach(function (id) {
        var r = latestV[id];
        if (active(r)) anyActive = true;
        if (wasActiveVideo[id] && !active(r)) finished = true;
        wasActiveVideo[id] = active(r);
      });
      Object.keys(latestD).forEach(function (id) {
        var r = latestD[id];
        if (active(r)) anyActive = true;
        if (wasActiveDoc[id] && !active(r)) finished = true;
        wasActiveDoc[id] = active(r);
      });
      runsByVideo = latestV; runsByDoc = latestD;
      var pastV = {}, pastD = {};   // 前回の結果(サーバーがこの起動の実行の無い配信・文書だけを返す。新しい順)
      (j.past || []).forEach(function (p) {
        if (p.kind === 'doc') { if (p.docId && !pastD[p.docId]) pastD[p.docId] = p; }
        else if (p.videoId && !pastV[p.videoId]) pastV[p.videoId] = p;
      });
      var goneD = Object.keys(pastByDoc).filter(function (id) { return !pastD[id]; });   // 前回の表示を消す行
      pastByVideo = pastV; pastByDoc = pastD;
      goneD.forEach(renderDocRun);
      $all('#list .pt-case').forEach(function (node) {
        renderAuto(node, node.dataset.id);
        if (active(runsByVideo[node.dataset.id])) node.open = true;
      });
      $all('#list .ui-group').forEach(function (g) {
        if (activeIn($all('.pt-case', g).map(function (n) { return n.dataset.id; }))) g.open = true;
      });
      Object.keys(runsByDoc).concat(Object.keys(pastByDoc)).forEach(renderDocRun);
      pollIntake();   // 依頼の受付も同じ周期で読む(別のタイマーは持たない)
      pollBackup();
      if (finished) {
        refreshCases();
        loadTxList().then(function () { renderDocs(); buildTodo(); });
        if ($('#historyBox').open) loadHistory(true);   // 開いている記録にも、終わった実行を足す
      } else {
        buildTodo();
      }
      autoTimer = setTimeout(pollAuto, anyActive ? 2000 : 15000);
    }).catch(function () { autoTimer = setTimeout(pollAuto, 5000); });
  }


  /* ================================================================ 依頼の受付(友人の依頼の自動受付。docs/spec/friend-intake.md の 6) ================================================================ */

  var INTAKE_PILL = { off: 'wait', watching: 'ok', error: 'err' };
  var intakeData = null, intakeSig = '', intakeBusy = false, intakeDirty = false, intakeOpened = false;
  var INTAKE_NUMS = [['top', '#intakeTop', '既定の切り抜く数', 1, 10], ['dailyMax', '#intakeDaily', '1日の上限', 1, 50],
    ['maxHours', '#intakeHours', '配信の長さの上限', 1, 24], ['maxGB', '#intakeGB', '動画の大きさの上限', 1, 200], ['interval', '#intakeInterval', '見る間隔', 10, 600]];

  function fillIntakeSettings(d) {
    $('#intakeEnabled').checked = !!d.enabled;
    $('#intakeFolder').value = d.folder || '';
    INTAKE_NUMS.forEach(function (n) { if (d[n[0]] != null) $(n[1]).value = String(d[n[0]]); });
    intakeDirty = false;
  }
  function renderIntakeStatus(d) {
    var pill = $('#intakeState');
    pill.className = 'pill ' + (INTAKE_PILL[d.state] || 'wait');
    pill.textContent = d.stateLabel || (d.enabled ? '見張り中' : 'オフ');
    $('#intakeMsg').textContent = d.message || '';
    $('#intakeScan').textContent = d.lastScan ? '最後に確認: ' + ago(d.lastScan) : (d.state === 'watching' ? 'まだ確認していません' : '');
    $('#intakeScan').title = d.lastScan ? when(d.lastScan) : '';
    $('#intakeToday').textContent = d.enabled ? '今日 ' + (d.today || 0) + ' / ' + (d.dailyMax || 0) + ' 件' : '';
    $('#intakeScanBtn').disabled = intakeBusy || !d.enabled;
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
    head.appendChild(el('span', 'pill info', r.kind === 'url' ? 'URL' : '動画'));
    head.appendChild(el('span', 'pt-intake-title', r.title || (r.kind === 'url' ? '(題名なし)' : '(ファイル名なし)')));
    head.appendChild(el('span', 'pill ' + (r.state === 'accepted' ? 'ok' : 'warn'), r.stateLabel || (r.state === 'accepted' ? '受け付けた' : '断った')));
    var t = el('span', 'hint pt-intake-when', ago(r.received)); t.title = r.received ? when(r.received) : '';
    head.appendChild(t);
    if (r.id && hideApi()) head.appendChild(hideBtn('intake', r.id, r.title));
    if (r.id) markHid(li, 'intake', r.id, head);
    li.appendChild(head);
    var sub = [r.flowLabel || '', r.rangesLabel || '', r.cutLabel || '', r.weightsLabel || '', r.speakersLabel || '', r.tracksLabel || '', r.streamer ? '字幕の色: ' + r.streamer : '', r.source === 'manual' ? 'フォルダに直接置かれた' : 'アプリから', r.memo ? 'メモ: ' + r.memo : ''].filter(Boolean).join(' ・ ');
    if (sub) li.appendChild(el('span', 'hint pt-intake-sub', sub));
    if (r.reason) li.appendChild(el('span', 'hint pt-intake-sub', (r.state === 'rejected' ? '断った理由: ' : '') + r.reason));
    if (r.items && r.items.length) { var ul = el('ul', 'pt-intake-items'); r.items.forEach(function (it) { ul.appendChild(intakeItemRow(it)); }); li.appendChild(ul); }
    return li;
  }
  function renderIntake(d) {
    intakeData = d;
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
        if ((d.requests || []).length) emptyBox('表示できる依頼はありません', 'すべて非表示にしています。「非表示のものも出す」と、また見られます。', { label: '非表示のものも出す', fn: function () { if (window.UIKit && UIKit.hide) UIKit.hide.setShowing('intake', true); } }, $('#intakeEmpty'));
        else emptyBox('まだ依頼は届いていません', '友人のアプリから送られると、ここに出ます。', { label: d.enabled ? '受付の設定を見る' : '受付をオンにする', fn: openIntakeSettings }, $('#intakeEmpty'));
      }
    }
    hideToggle('#intakeHidden', 'intake', hidN);
    if (!intakeOpened) {   // 最初の1回だけ: 動いているとき・止まっているときは開いて見せる(オフのときは閉じたまま)
      intakeOpened = true;
      if (d.enabled || d.state === 'error') $('#intakeBox').open = true;
      fillIntakeSettings(d);
    } else if (!intakeDirty) fillIntakeSettings(d);
  }
  function pollIntake() {
    return api('api/intake').then(renderIntake, function (e) {
      if (e.status === 404) { $('#intakeBox').hidden = true; return; }   // 受付の無い版の入口(古いサーバー)では出さない
      $('#intakeState').className = 'pill wait'; $('#intakeState').textContent = '読めません'; $('#intakeState').title = failText('依頼の受付の状態を読めませんでした', '画面を読み込み直してください', e);
    });
  }
  function intakeScanNow() {
    if (intakeBusy) return;
    intakeBusy = true; $('#intakeScanBtn').disabled = true;
    api('api/intake/scan', 'POST', {}).then(function (d) { renderIntake(d); toast('確認しました'); },
      function (e) { failToast('依頼を確認できませんでした', '少し待って、もう一度「今すぐ確認」を押してください', e); })
      .then(function () { intakeBusy = false; if (intakeData) renderIntakeStatus(intakeData); });
  }
  function intakeValue() {
    var v = { enabled: $('#intakeEnabled').checked, folder: $('#intakeFolder').value.trim() };
    for (var i = 0; i < INTAKE_NUMS.length; i++) {
      var n = INTAKE_NUMS[i], x = Number($(n[1]).value);
      if (!isFinite(x) || $(n[1]).value === '' || x < n[3] || x > n[4]) throw new Error(n[2] + 'は ' + n[3] + '〜' + n[4] + ' の数で入れてください');
      v[n[0]] = Math.round(x);
    }
    return v;
  }
  function intakeSave(partial) {
    var msg = $('#intakeSaveMsg'), v;
    try { v = partial || intakeValue(); } catch (e) { msg.textContent = e.message; return Promise.resolve(); }
    msg.textContent = '保存しています…';
    return api('api/ytt/prefs', 'POST', { op: 'patch', section: 'intake', value: v }).then(function () {
      msg.textContent = '保存しました';
      if (!partial) intakeDirty = false;
      return pollIntake();
    }, function (e) {
      msg.textContent = failText('保存できませんでした', '内容を確かめて、もう一度「設定を保存」を押してください', e);
      failToast('依頼の受付の設定を保存できませんでした', '内容を確かめて、もう一度お試しください', e, function () { intakeSave(partial); });
      if (partial && intakeData) $('#intakeEnabled').checked = !!intakeData.enabled;   // スイッチだけの保存が断られたら、表示を元に戻す
    });
  }
  function wireIntake() {
    if (!$('#intakeBox')) return;
    $('#intakeScanBtn').addEventListener('click', intakeScanNow);
    $('#intakeSave').addEventListener('click', function () { intakeSave(); });
    $('#intakeEnabled').addEventListener('change', function () { intakeSave({ enabled: $('#intakeEnabled').checked }); });   // スイッチは押したらすぐ効く
    ['#intakeFolder', '#intakeTop', '#intakeDaily', '#intakeHours', '#intakeGB', '#intakeInterval'].forEach(function (s) {
      $(s).addEventListener('input', function () { intakeDirty = true; $('#intakeSaveMsg').textContent = ''; });
    });
  }

  /* ================================================================ 作業データのバックアップ(src/home/backup.py。docs/spec/data-location.md の「バックアップ」) ================================================================ */

  var BACKUP_PILL = { off: 'wait', idle: 'ok', running: 'run', error: 'err' };
  var backupData = null, backupBusy = false, backupDirty = false, backupOpened = false, backupTimer = null, backupFastUntil = 0;

  function fillBackupSettings(d) {
    $('#backupEnabled').checked = !!d.enabled;
    $('#backupFolder').value = d.folder || '';
    if (d.everyHours != null) $('#backupEvery').value = String(d.everyHours);
    backupDirty = false;
  }
  function renderBackupStatus(d) {
    var pill = $('#backupState');
    pill.className = 'pill ' + (BACKUP_PILL[d.state] || 'wait');
    pill.textContent = d.stateLabel || (d.enabled ? '動いています' : 'オフ');
    var n = (d.errors || []).length;
    $('#backupMsg').textContent = d.message || '';
    $('#backupMsg').title = n ? d.errors.join(' / ') : '';
    $('#backupLast').textContent = d.lastOk ? '最後に写した: ' + ago(d.lastOk) + '(' + (d.copied || 0) + ' 個・' + fmtBytes(d.bytes) + ')' : (d.enabled ? 'まだ写していません' : '');
    $('#backupLast').title = d.lastOk ? when(d.lastOk) + (d.dest ? ' → ' + d.dest : '') : '';
    $('#backupRunBtn').disabled = backupBusy || !d.enabled || d.state === 'running';
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
    } else if (!backupDirty) fillBackupSettings(d);
  }
  function pollBackup() {
    if (!$('#backupBox')) return Promise.resolve();
    return api('api/backup').then(renderBackup, function (e) {
      if (e.status === 404) { $('#backupBox').hidden = true; return; }   // バックアップの無い版の入口(古いサーバー)では出さない
      $('#backupState').className = 'pill wait'; $('#backupState').textContent = '読めません'; $('#backupState').title = failText('バックアップの状態を読めませんでした', '画面を読み込み直してください', e);
    });
  }
  function backupRunNow() {
    if (backupBusy) return;
    backupBusy = true; $('#backupRunBtn').disabled = true;
    backupFastUntil = Date.now() + 30000;
    api('api/backup/run', 'POST', {}).then(function (d) { renderBackup(d); toast('バックアップを始めました'); },
      function (e) { failToast('バックアップを始められませんでした', '写す先のフォルダを確かめて、もう一度「今すぐ写す」を押してください', e); })
      .then(function () { backupBusy = false; if (backupData) renderBackupStatus(backupData); });
  }
  function backupValue() {
    var x = Number($('#backupEvery').value);
    if (!isFinite(x) || $('#backupEvery').value === '' || x < 1 || x > 168) throw new Error('間隔は 1〜168 の数で入れてください');
    var v = { enabled: $('#backupEnabled').checked, folder: $('#backupFolder').value.trim(), everyHours: Math.round(x) };
    if (v.enabled && !v.folder) throw new Error('写す先のフォルダを入れてください');
    return v;
  }
  function backupSave(partial) {
    var msg = $('#backupSaveMsg'), v;
    try { v = partial || backupValue(); } catch (e) { msg.textContent = e.message; if (partial === undefined && backupData) $('#backupEnabled').checked = !!backupData.enabled; return Promise.resolve(); }
    msg.textContent = '保存しています…';
    return api('api/ytt/prefs', 'POST', { op: 'patch', section: 'backup', value: v }).then(function () {
      msg.textContent = '保存しました';
      backupDirty = false;
      backupFastUntil = Date.now() + 30000;
      return pollBackup();
    }, function (e) {
      msg.textContent = failText('保存できませんでした', '写す先のフォルダを確かめて、もう一度「設定を保存」を押してください', e);
      failToast('バックアップの設定を保存できませんでした', '写す先のフォルダを確かめて、もう一度お試しください', e, function () { backupSave(partial); });
      if (backupData) $('#backupEnabled').checked = !!backupData.enabled;   // 断られたら、スイッチの表示を元に戻す
    });
  }
  function wireBackup() {
    if (!$('#backupBox')) return;
    $('#backupRunBtn').addEventListener('click', backupRunNow);
    $('#backupSave').addEventListener('click', function () { backupSave(); });
    $('#backupEnabled').addEventListener('change', function () { backupSave(); });   // スイッチは押したらすぐ効く(フォルダと一緒に送る。フォルダが空ならオンにできない)
    ['#backupFolder', '#backupEvery'].forEach(function (s) {
      $(s).addEventListener('input', function () { backupDirty = true; $('#backupSaveMsg').textContent = ''; });
    });
  }

  /* ================================================================ まとめて実行の記録(段2 B-6。入口を終えても残る。開いたときだけ読む) ================================================================ */

  var HIST_PILL = { done: 'ok', error: 'err', cancelled: 'wait' };
  function historyRow(r) {
    var li = $('#tplHistory').content.firstElementChild.cloneNode(true);
    if (r.id) li.setAttribute('data-fkey', 'runs:' + r.id);
    var pill = $('.pt-history-pill', li);
    pill.className = 'pill pt-history-pill ' + (r.nothing ? 'wait' : (HIST_PILL[r.state] || 'wait'));
    pill.textContent = runLabel(r);
    var a = $('.pt-history-title', li);
    a.textContent = r.title || (r.kind === 'doc' ? r.docId : r.videoId) || (r.kind === 'file' ? '依頼の動画' : '');
    if (r.kind === 'doc') { a.href = docHref(r.docId, null, 'tx'); a.title = '編集で開く'; }   // 文書 → 編集で開く(同じ窓。S-15)
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
    api('/api/autorun/history?limit=' + HIST_PAGE + '&offset=' + histOffset).then(function (j) {
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

  /* ================================================================ 試験中の機能: リアルタイム切り抜き(線 D。src/home/live.py)================================================================
     ホームの設定の節 live の enabled だけをここで切り替える(既定はオフ)。録画と再生・マークはスタジオの中(P3。別の録画の画面は 2026-10-05 にやめた) */
  function renderLive(v) {
    $('#liveEnabled').checked = !!(v && v.enabled);
    var box = $('#liveAutoBox'), a = (v && v.auto) || {};   // 書き出したあとの自動の流れ(live.auto。M2)。オンのときだけ
    if (!box) return;
    box.hidden = !(v && v.enabled);
    $('#liveAutoAfter').value = a.after || 'check';
    $('#liveAutoCut').value = a.cut || '';
    $('#liveAutoEngine').value = a.engine || '';
    if (document.activeElement !== $('#liveAutoModel')) $('#liveAutoModel').value = a.model || '';
    if ($('#liveAfterStream')) {   // 配信後の全自動(M7)
      $('#liveAfterStream').checked = !!(v && v.autoAfterStream);
      if (document.activeElement !== $('#liveAfterPerHour')) $('#liveAfterPerHour').value = (v && v.afterStreamPerHour) || 6;
    }
    var db = $('#liveDetectBox'), dt = (v && v.detect) || {}, aa = (v && v.autoAdopt) || {};   // 配信中の候補(L2)・自動の採用(M11)
    if (db) {
      db.hidden = !(v && v.enabled);
      $('#liveDetect').checked = !!dt.enabled;
      $('#liveDetectSens').value = dt.sens || 'normal';
      if (document.activeElement !== $('#liveDetectPerHour')) $('#liveDetectPerHour').value = dt.perHour || 6;
      $('#liveAutoAdopt').checked = !!aa.enabled;
      if (document.activeElement !== $('#liveAutoAdoptWait')) $('#liveAutoAdoptWait').value = aa.waitMin || 5;
    }
  }
  function saveLiveTop(value, okText) {   // live の節の 1 つの鍵(auto の外。M7)
    api('api/ytt/prefs', 'POST', { op: 'patch', section: 'live', value: value }).then(function (j) {
      renderLive(j.value);
      toast(okText, 'ok');
    }, function (e) {
      failToast('設定を保存できませんでした', 'もう一度お試しください', e);
      loadLive();
    });
  }
  function saveLiveAuto(key, value) {
    var body = {}; body[key] = value;
    api('api/ytt/prefs', 'POST', { op: 'patch', section: 'live', value: { auto: body } }).then(function (j) {
      renderLive(j.value);
      toast('書き出したあとの設定を保存しました', 'ok');
    }, function (e) {
      failToast('設定を保存できませんでした', 'もう一度お試しください', e);
      loadLive();
    });
  }
  function loadLive() {
    return api('api/ytt/prefs', 'POST', { op: 'get', sections: ['live'] }).then(function (j) { renderLive((j.prefs || {}).live); },
      function () { $('#labBox').hidden = true; });   // 設定を読めない(古い入口)なら出さない
  }
  function wireLive() {
    if (!$('#labBox')) return;
    $('#liveEnabled').addEventListener('change', function () {
      var on = $('#liveEnabled').checked, msg = $('#liveMsg');
      api('api/ytt/prefs', 'POST', { op: 'patch', section: 'live', value: { enabled: on } }).then(function (j) {
        renderLive(j.value);
        msg.hidden = false;
        msg.textContent = on ? 'オンにしました。録画の部品を裏で起動します(数秒かかります)。スタジオの URL の欄に配信中の URL を入れると録画します' : 'オフにしました(録画中の物があれば、録画の部品はそのまま続けます)';
      }, function (e) {
        $('#liveEnabled').checked = !on;
        failToast('試験中の機能を切り替えられませんでした', 'もう一度お試しください', e);
      });
    });
    if ($('#liveAutoBox')) {
      [['#liveAutoAfter', 'after'], ['#liveAutoCut', 'cut'], ['#liveAutoEngine', 'engine']].forEach(function (p) {
        $(p[0]).addEventListener('change', function () { saveLiveAuto(p[1], $(p[0]).value); });
      });
      $('#liveAutoModel').addEventListener('change', function () { saveLiveAuto('model', $('#liveAutoModel').value.trim()); });
    }
    if ($('#liveAfterStream')) {
      $('#liveAfterStream').addEventListener('change', function () {
        var on = $('#liveAfterStream').checked;
        saveLiveTop({ autoAfterStream: on }, on ? '配信が終わったら、アーカイブの解析で自動で切り抜きます' : '配信後の自動の切り抜きをやめました');
      });
      $('#liveAfterPerHour').addEventListener('change', function () {
        var n = parseInt($('#liveAfterPerHour').value, 10);
        if (!(n >= 1 && n <= 30)) { toast('1 時間あたりの数は 1〜30 にしてください', 'err'); loadLive(); return; }
        saveLiveTop({ afterStreamPerHour: n }, '1 時間あたり ' + n + ' 本にしました');
      });
    }
    if ($('#liveDetectBox')) {   // 配信中の候補(live.detect。L2)・候補の自動の採用(live.autoAdopt。M11)。節の中の鍵ごとに送る
      $('#liveDetect').addEventListener('change', function () {
        var on = $('#liveDetect').checked;
        saveLiveTop({ detect: { enabled: on } }, on ? '配信中の候補を出します(録画中の配信を見ます)' : '配信中の候補をやめました');
      });
      $('#liveDetectSens').addEventListener('change', function () { saveLiveTop({ detect: { sens: $('#liveDetectSens').value } }, '候補の感度を変えました'); });
      $('#liveDetectPerHour').addEventListener('change', function () {
        var n = parseInt($('#liveDetectPerHour').value, 10);
        if (!(n >= 1 && n <= 30)) { toast('1 時間の本数は 1〜30 にしてください', 'err'); loadLive(); return; }
        saveLiveTop({ detect: { perHour: n } }, '候補は 1 時間に ' + n + ' 本までにしました');
      });
      $('#liveAutoAdopt').addEventListener('change', function () {
        var on = $('#liveAutoAdopt').checked;
        saveLiveTop({ autoAdopt: { enabled: on } }, on ? '候補を自動で採用します(確定から ' + ($('#liveAutoAdoptWait').value || 5) + ' 分待ちます)' : '候補の自動の採用をやめました');
      });
      $('#liveAutoAdoptWait').addEventListener('change', function () {
        var n = parseInt($('#liveAutoAdoptWait').value, 10);
        if (!(n >= 1 && n <= 60)) { toast('待つ分は 1〜60 にしてください', 'err'); loadLive(); return; }
        saveLiveTop({ autoAdopt: { waitMin: n } }, '候補が確定してから ' + n + ' 分待って採用します');
      });
    }
    loadLive();
  }

  /* ================================================================ ハッシュ(#cases・#case-<id>・#doc-<id>): 次にやることのリンク先へ移る ================================================================ */

  function focusHash() {
    var h = location.hash;
    if (!h) return;
    if (h === '#intake') { var ib = $('#intakeBox'); if (ib) { ib.open = true; ib.scrollIntoView({ behavior: 'smooth', block: 'start' }); } return; }
    if (h === '#cases') { var sec = $('#caseListSection'); if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    var m = /^#(case|doc)-(.+)$/.exec(h);
    if (!m) return;
    var id = decodeURIComponent(m[2]);
    if (m[1] === 'case') { visibleCount = Math.max(visibleCount, 10000); render(); }
    else { docVisibleCount = Math.max(docVisibleCount, 10000); $('#unlinkedGroup').open = true; renderDocs(); }
    var target = document.getElementById(m[1] + '-' + id);
    if (!target) return;
    // 対象自身(details なら)だけでなく、まとめ方(配信者・状態でまとめる。.ui-group)で包まれているときは
    // その details も開く。閉じたままだと target が非表示のまま scrollIntoView されてしまう(E2 finding 3)
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
  if (window.UIKit && UIKit.portal) UIKit.portal.listen();

  document.addEventListener('DOMContentLoaded', function () {
    /* ⚙ 設定の「ホーム」の節(M10): 窓で開く・まとめて実行の既定・試験中の機能。以前は「詳しく」の中・案件の行に散らばっていた。
       依頼の受付・バックアップは状態と一覧を持つ欄なので今の場所に残し、ここからは「開く」ボタンで移る */
    var hs = $('#homeSettings');
    if (window.UIKit && UIKit.settings) { if (hs) hs.hidden = false; UIKit.settings.mount(hs ? { title: '設定', tool: hs } : { title: '設定' }); }
    if (window.UIKit && UIKit.autorun && $('#setAutorun')) UIKit.autorun.panel($('#setAutorun'), { kind: 'new' });
    function goFromSettings(open) {
      var d = document.getElementById('uiSettingsDrawer');
      if (d && window.UIKit && UIKit.drawer) UIKit.drawer.close(d);
      setTimeout(open, 0);
    }
    $('#setGoIntake').addEventListener('click', function () { goFromSettings(openIntakeSettings); });
    $('#setGoBackup').addEventListener('click', function () { goFromSettings(openBackupSettings); });
    if (window.UIKit && UIKit.streamer) UIKit.streamer.attach($('#docWho'));

    $('#btnQuit').addEventListener('click', quit);
    $('#btnHealthRefresh').addEventListener('click', function () { loadHealth(true); });
    $('#btnAccuracyNow').addEventListener('click', accuracyNow);
    var adv = $('#healthBox') && $('#healthBox').closest('details');
    if (adv) { adv.addEventListener('toggle', function () { if (adv.open) loadHealth(false); }); if (adv.open) loadHealth(false); }
    $('#btnCleanFind').addEventListener('click', loadCleanup);
    $('#btnCleanMove').addEventListener('click', moveCleanup);
    $('#winMode').addEventListener('change', function () { setWin(this.checked ? 'app' : 'browser'); });
    $('#btnWinNow').addEventListener('click', openWinNow);
    $('#btnCopyData').addEventListener('click', function () {
      var t = $('#dataDir').textContent;
      if (!t) return;
      (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(
        function () { toast('パスをコピーしました'); },
        function () { toast('コピーできませんでした。パスを選んでコピーしてください', 'err'); });
    });

    $('#fStatus').addEventListener('change', function () { lsSet('status', $('#fStatus').value); resetPaging(); });
    $('#fText').addEventListener('input', function () { resetPaging(); });
    $('#fSort').addEventListener('change', function () { lsSet('sort', $('#fSort').value); resetPaging(); });
    $('#fGroup').addEventListener('change', function () { lsSet('group', $('#fGroup').value); resetPaging(); });
    $('#autoFilter').addEventListener('click', function () { autoOnly = !autoOnly; openCases = {}; resetPaging(); });   // 絞り込みを変えたら、行の開き方は絞り込みに合わせ直す
    /* 紐づかない文書の「パックがあれば作り直す(上書き)」も、まとめて実行の設定(ホームの設定)と同じ値(どの入口で変えても同じ。段4) */
    if (window.UIKit && UIKit.autorun) {
      UIKit.autorun.load().then(function (st) { $('#docOverwrite').checked = st.overwrite; }, function () {});
      document.addEventListener('ui-autorun-settings', function (e) { if (e.detail) $('#docOverwrite').checked = e.detail.overwrite; });
    }
    $('#docPickAll').addEventListener('click', function () { pickDocs(false); });
    $('#docPickNoPack').addEventListener('click', function () { pickDocs(true); });
    $('#docOverwrite').addEventListener('change', function () { if (window.UIKit && UIKit.prefs) UIKit.prefs.patch('autorun', { overwrite: $('#docOverwrite').checked }).catch(function () {}); });
    $('#btnMore').addEventListener('click', function () {
      var from = $all('#list .pt-case').length; visibleCount += PAGE_SIZE; render(); focusNewRow('#list .pt-case', from);
    });
    $('#btnReload').addEventListener('click', reloadAll);

    $('#docSearch').addEventListener('input', function () { resetDocPaging(); });
    $('#docMore').addEventListener('click', function () {
      var from = $all('#docList .pt-doc').length; docVisibleCount += DOC_PAGE; renderDocs(); focusNewRow('#docList .pt-doc', from);
    });
    $('#docRunBtn').addEventListener('click', runDocsBatch);
    enterRuns($('#docWho'), $('#docRunBtn'));   // 配信者の欄の Enter で実行(S-24)

    $('#todoMore').addEventListener('click', function () {   // すべて見る ⇄ 少なく表示。広げたら最初に増えた行へフォーカス(M6・S10)
      todoShowAll = !todoShowAll; buildTodo();
      if (todoShowAll) { var rows = $all('#todoList .pt-todo-link'), t = rows[TODO_CAP]; if (t) t.focus(); }
    });
    $('#historyBox').addEventListener('toggle', function () { if ($('#historyBox').open) loadHistory(true); });
    $('#historyMore').addEventListener('click', function () { loadHistory(false); });
    wireIntake();
    wireBackup();
    wireLive();
    if (window.UIKit && UIKit.hide) {   // 非表示にした項目を読んだら・変えたら、その一覧を描き直す(別の窓で変えた分は戻ったときに部品が読み直す)
      UIKit.hide.onChange(function (list) {
        if (!list || list === 'cases') render();
        if (!list || list === 'transcripts') renderDocs();
        if (!list || list === 'cases' || list === 'transcripts' || list === 'todo') buildTodo();
        if ((!list || list === 'intake') && intakeData) renderIntake(intakeData);
        if (!list || list === 'runs') applyHistoryHidden();
      });
      UIKit.hide.load();
    }

    restoreFilters();
    /* タブ・窓に戻ったらすぐ読み直す(ui-kit の UIKit.life。窓を並べて使うとタブの切り替えは来ないため) */
    if (window.UIKit && UIKit.life) UIKit.life.onReturn(function () { poll(); refreshCases(); });
    else document.addEventListener('visibilitychange', function () { if (!document.hidden) { poll(); refreshCases(); } });

    poll();
    loadCases().then(function () { return loadTxList(); }).then(function () { renderDocs(); buildTodo(); pollAuto(); focusHash(); });
  });
})();
