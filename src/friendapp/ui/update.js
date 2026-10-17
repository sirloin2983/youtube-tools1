/* 新しい版の帯の 1 行(更新。notes:plan/f1-friend-requirements.md の 8 章・A-15。形は friend-apps/launcher/README.txt)。
   画面(F3-B)は帯に <div data-fr-update></div> を置き <script src="update.js" defer> を読むだけ。新しい版が無ければ何も出さない。
   新しい版は同期が <home>/app-<版>/ に入れておく → 「新しい版 n があります [更新する]」→ 押すと、作業と預かりが無ければ exe がすぐ入れ替えて開き直す・
   あれば「作業が終わったら更新します(…)」で待つ。外の文字は textContent で入れる(CSP の下で動く)。 */
(function () {
  'use strict';
  var POLL = 30000, POLL_WAIT = 3000, timer = 0, busy = false;

  function api(path, body) { return UIKit.http('api/friend/' + path, body === undefined ? {} : { body: body }); }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  function draw(box, u) {
    box.textContent = '';
    if (!u || !u.available) { box.hidden = true; return; }
    box.hidden = false;
    box.setAttribute('role', 'status');
    var msg = el('span', 'fr-update-text');
    if (!u.requested) {
      msg.textContent = '新しい版 ' + u.version + ' があります';
      box.appendChild(msg);
      var b = el('button', 'btn primary small', '更新する');
      b.type = 'button';
      b.title = '新しい版に入れ替えて開き直します(作っている途中の物があれば、終わってから入れ替えます)';
      b.addEventListener('click', function () { apply(box, b); });
      box.appendChild(b);
      return;
    }
    if (!u.hosted) msg.textContent = '新しい版 ' + u.version + ' は、アプリを開き直すと使えます';
    else if (u.waiting) msg.textContent = '作業が終わったら新しい版 ' + u.version + ' に更新します' + (u.label ? '(' + u.label + ')' : '');
    else msg.textContent = '新しい版 ' + u.version + ' に更新しています。開き直すまでお待ちください';
    box.appendChild(msg);
  }

  function apply(box, b) {
    if (busy) return;
    busy = true;
    b.disabled = true;
    api('update/apply', {}).then(function (j) { draw(box, j.update); }, function (e) {
      UIKit.toast('更新できませんでした: ' + ((e && e.message) || ''), { kind: 'err', ms: 5000 });
      b.disabled = false;
    }).then(function () { busy = false; poll(); });
  }

  function poll() {
    clearTimeout(timer);
    var boxes = document.querySelectorAll('[data-fr-update]');
    if (!boxes.length) return;
    api('update').then(function (u) {
      Array.prototype.forEach.call(boxes, function (box) { draw(box, u); });
      timer = setTimeout(poll, u && u.requested ? POLL_WAIT : POLL);
    }, function () { timer = setTimeout(poll, POLL); });
  }

  document.addEventListener('DOMContentLoaded', poll);
  window.FriendUpdate = { refresh: poll };
})();
