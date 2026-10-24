/* 新しい版の帯の 1 行(更新。notes:docs/design/friend-history.md の 7 章)。
   画面(F3-B)は帯に <div data-fr-update></div> を置き <script src="update.js" defer> を読むだけ。新しい版が無ければ何も出さない。
   新しい版は同期が <home>/app-<版>/ に入れておく → 「新しい版 n があります [更新する]」→ 押すと、作業と預かりが無ければ exe がすぐ入れ替えて開き直す・
   あれば「作業が終わったら更新します(…)」で待つ。外の文字は textContent で入れる(CSP の下で動く)。 */
(function () {
  'use strict';
  var POLL = 30000, POLL_WAIT = 3000, timer = 0, busy = false;
  var curU = null, curT = null, tidyBusy = false;   /* 新しい版の知らせ・フォルダの整理の view(口が無い・失敗のときは null) */

  function api(path, body) { return UIKit.http('api/friend/' + path, body === undefined ? {} : { body: body }); }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  function drawUpdate(box, u) {
    box.textContent = '';
    box.hidden = false;
    box.setAttribute('role', 'status');
    var msg = el('span', 'fr-update-text');
    /* 重要な直し(待っている間)・24 時間溜まった更新: 端の 1 行と [今すぐ](録画中だけは録画が終わるまで待つ) */
    var urgent = u.hosted && !u.now && ((u.important && u.requested && u.waiting) || (u.overdue && !(u.requested && !u.waiting)));
    if (urgent) {
      msg.textContent = u.important ? '大事な直しが届きました。今の処理が終わったら更新します' : '更新が溜まっています';
      box.appendChild(msg);
      var now = el('button', 'btn primary small', u.important ? '今すぐ' : '今すぐ更新');
      now.type = 'button';
      now.setAttribute('data-fr-update-now', '');
      now.title = '今の処理を止めて新しい版に入れ替えます(止めた処理は開き直したあと続きから。録画中は録画が終わってから)';
      now.addEventListener('click', function () { apply(box, now, 'update/now'); });
      box.appendChild(now);
      return;
    }
    if (!u.requested) {
      msg.textContent = '新しい版 ' + u.version + ' があります' + (u.auto ? '。処理が終わったら自動で新しい版にします(今すぐ:' : '');
      box.appendChild(msg);
      var b = el('button', 'btn primary small', '更新する');
      b.type = 'button';
      b.title = '新しい版に入れ替えて開き直します(作っている途中の物があれば、終わってから入れ替えます)';
      b.addEventListener('click', function () { apply(box, b); });
      box.appendChild(b);
      if (u.auto) box.appendChild(el('span', 'fr-update-text', ')'));
      return;
    }
    if (!u.hosted) msg.textContent = '新しい版 ' + u.version + ' は、アプリを開き直すと使えます';
    else if (u.waiting) msg.textContent = '作業が終わったら新しい版 ' + u.version + ' に更新します' + (u.label ? '(' + u.label + ')' : '');
    else msg.textContent = '新しい版 ' + u.version + ' に更新しています。開き直すまでお待ちください';
    box.appendChild(msg);
  }

  function apply(box, b, path) {
    if (busy) return;
    busy = true;
    b.disabled = true;
    api(path || 'update/apply', {}).then(function (j) { curU = j.update; redraw(); }, function (e) {
      UIKit.toast('更新できませんでした: ' + ((e && e.message) || ''), { kind: 'err', ms: 5000 });
      b.disabled = false;
    }).then(function () { busy = false; poll(); });
  }

  function viewOf(j) { return j && j.tidy && typeof j.tidy === 'object' ? j.tidy : j; }

  function sizeText(n) { return n >= 1e9 ? (n / 1e9).toFixed(1) + 'GB' : Math.max(1, Math.round((n || 0) / 1e6)) + 'MB'; }

  /* 時刻は秒か ms の数、または日付の文字列(読めなければ 0) */
  function toMs(at) {
    if (typeof at === 'number') return at < 1e12 ? at * 1000 : at;
    var t = Date.parse(at);
    return isFinite(t) ? t : 0;
  }

  /* 帯の 1 行(フォルダの整理・F3-A): 片付けている → 片付ける物がある(聞く) → 2 分以内の結果 の順。何も無ければ隠す */
  function drawTidy(box, v) {
    box.textContent = '';
    box.hidden = true;
    if (!v || typeof v !== 'object') return;
    var last = v.last, ask = !!v.ask && v.askCount > 0, msg = '';
    if (v.state === 'applying') msg = '片付けています…';
    else if (ask) msg = 'フォルダに片付けられる物が ' + v.askCount + ' 件(' + sizeText(v.askBytes) + ')あります';
    else if (last && Date.now() - toMs(last.at) <= 120000) {
      if (last.failed) msg = '片付けられませんでした' + (last.message ? ': ' + last.message : '');
      else if (last.count > 0) msg = last.count + ' 件 ' + sizeText(last.bytes) + ' を片付けました(3 日はごみ箱に残ります)';
    }
    if (!msg) return;
    box.hidden = false;
    box.setAttribute('role', 'status');
    box.appendChild(el('span', 'fr-update-text', msg));
    if (!ask || v.state === 'applying') return;
    var go = el('button', 'btn primary small', '片付ける');
    go.type = 'button';
    go.disabled = !!v.blocked || tidyBusy;
    go.title = v.blocked || '片付ける物を全部、アプリのごみ箱へ移します(3 日は戻せます)';
    go.addEventListener('click', function () { tidyAct('apply', {}); });
    var see = el('button', 'btn ghost small', '内容を見る');
    see.type = 'button';
    see.title = '⚙ の「フォルダを整理する」で中身を見て選べます';
    see.addEventListener('click', function () { if (window.FriendSettings) window.FriendSettings.open('tidy'); });
    var later = el('button', 'btn ghost small', 'あとで');
    later.type = 'button';
    later.title = 'この版ではもう聞きません';
    later.addEventListener('click', function () { tidyAct('later', {}); });
    box.appendChild(go);
    box.appendChild(see);
    box.appendChild(later);
  }

  function tidyAct(path, body) {
    if (tidyBusy) return;
    tidyBusy = true;
    redraw();
    api('tidy/' + path, body).then(function (j) {
      var v = viewOf(j);
      if (v && typeof v === 'object') curT = v;
    }, function (e) {
      UIKit.toast('できませんでした: ' + ((e && e.message) || ''), { kind: 'err', ms: 5000 });
    }).then(function () {
      tidyBusy = false;
      redraw();
      document.dispatchEvent(new CustomEvent('friend-tidy', { detail: curT }));   /* 引き出しの節も同じ見え方に・この帯も読み直す */
    });
  }

  function redraw() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-fr-update]'), function (box) {
      if (curU && curU.available) drawUpdate(box, curU); else drawTidy(box, curT);
    });
  }

  function poll() {
    clearTimeout(timer);
    if (!document.querySelector('[data-fr-update]')) return;
    var u = api('update').then(function (x) { curU = x; return x; }, function () { return curU; });
    var t = api('tidy').then(function (j) { curT = viewOf(j); return curT; }, function () { curT = null; return null; });
    Promise.all([u, t]).then(function (r) {
      redraw();
      var fast = !!(r[0] && r[0].requested) || !!(curT && curT.state === 'applying');
      timer = setTimeout(poll, fast ? POLL_WAIT : POLL);
    });
  }

  document.addEventListener('DOMContentLoaded', poll);
  document.addEventListener('friend-tidy', function () { poll(); });   /* 引き出しで変えたら帯も読み直す */
  window.FriendUpdate = { refresh: poll };
})();
