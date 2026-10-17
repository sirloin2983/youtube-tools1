/* 受け取る画面(F3-4。notes:plan/f1-friend-requirements.md の C-3)。口 = GET api/friend/receive(friendapp/inbox.py の receive_view)・
   POST api/friend/decide {items, verdict: keep|skip|bad, reason}・undo {items}・media?id=&name=(1 本の確認用の動画)・open {id, name}。
   一覧 = 配信ごとの段(最後に届いた時刻の新しい順・段の中は番号順)。カードを押すと再生画面(左に再生・右に同じ配信の物が先の一覧)。
   決めると自動で次(同じ配信の次の番号 → 次の配信 → 全部決まったら一覧)。チェックでまとめて決める帯。見送った物は 3 日の間 [戻す]。
   キー: 再生画面 = Space 再生 / 一時停止・← → 5 秒・↑ ↓ 音量・Esc 一覧へ(チェックがあれば先に外す)/ 一覧 = Esc でチェックを外す */
(function () {
  'use strict';
  var $, el, api;
  var my = { data: null, key: '', sel: {}, cur: null, playing: false, busy: false };

  function k(it) { return it.id + '\n' + it.name; }
  function thumbOf(vid, size) { return vid ? 'https://i.ytimg.com/vi/' + vid + '/' + (size || 'mqdefault') + '.jpg' : ''; }
  function all() { var out = []; ((my.data || {}).sections || []).forEach(function (s) { s.items.forEach(function (it) { out.push({ it: it, sec: s }); }); }); return out; }
  function find(key) { return all().filter(function (x) { return k(x.it) === key; })[0] || null; }
  function selected() { return all().filter(function (x) { return my.sel[k(x.it)]; }).map(function (x) { return x.it; }); }
  function open(it) { return !it.verdict && it.want !== 'keep'; }

  /* ---------------------------------------------------------------- カード */
  function card(it, sec, small) {
    var key = k(it);
    var cb = el('input', { type: 'checkbox', cls: 'fr-pick', 'aria-label': it.title + ' を選ぶ', disabled: !open(it) });
    cb.checked = !!my.sel[key];
    cb.addEventListener('change', function () { my.sel[key] = cb.checked; if (!cb.checked) delete my.sel[key]; bulk(); });
    var th = el('span', { cls: 'fr-thumb' });
    var src = thumbOf(sec.videoId);
    if (src) th.appendChild(el('img', { alt: '', loading: 'lazy', src: src }));
    th.appendChild(el('span', { cls: 'fr-num-badge', text: '#' + it.num + (it.seconds ? ' ' + FR.dur(it.seconds) : '') }));
    if (it.want === 'keep') th.appendChild(el('span', { cls: 'fr-badge', text: '受け取っています' }));
    var b = el('button', { type: 'button', cls: 'fr-rcard-btn', title: it.title, on: { click: function () { play(key); } } }, [th,
      el('span', { cls: 'fr-card-title', text: small ? '#' + it.num + ' ' + (it.clip || '') : it.clip || it.title })]);
    var kids = [b, el('label', { cls: 'fr-pick-wrap' }, [cb])];
    if (it.error) kids.push(el('span', { cls: 'fr-bad fr-rcard-err', text: it.error }));
    return el('div', { cls: 'fr-rcard' + (my.cur === key ? ' on' : '') + (small ? ' small' : ''), 'data-key': key }, kids);
  }
  function secHead(s) {
    var th = el('span', { cls: 'fr-sec-thumb' });
    if (s.videoId) th.appendChild(el('img', { alt: '', loading: 'lazy', src: thumbOf(s.videoId, 'default') }));
    var st = s.making ? (s.expect ? s.expect + ' 本中 ' + s.arrived + ' 本・作っています' : '届いた ' + s.arrived + ' 本・作っています') : s.items.length + ' 本';
    var meta = [el('span', { text: s.streamer || '' }), el('span', { cls: 'hint', text: st })];
    if (s.auto) meta.push(el('span', { cls: 'pill info', text: '自動で届いた', title: '作る人の PC が、配信から自動で選んで届けた物です' }));
    return el('div', { cls: 'fr-rsec-h' }, [th, el('div', { cls: 'fr-rsec-hb' }, [el('h2', { cls: 'fr-rsec-title', text: s.title || '(題なし)', title: s.title || '' }),
      el('div', { cls: 'fr-rsec-meta' }, meta)])]);
  }
  function renderList() {
    var d = my.data || { sections: [], skipped: [] };
    var box = $('rcvSections');
    box.textContent = '';
    d.sections.forEach(function (s) {
      var grid = el('div', { cls: 'fr-rcards' });
      s.items.forEach(function (it) { grid.appendChild(card(it, s)); });
      box.appendChild(el('section', { cls: 'fr-rsec', 'aria-label': s.title }, [secHead(s), grid]));
    });
    $('rcvEmpty').hidden = d.sections.length > 0;
    $('rcvCount').textContent = d.undecided ? 'まだ決めていない ' + d.undecided + ' 本' : '';
    var sk = d.skipped || [];
    $('rcvSkipped').hidden = !sk.length;
    $('rcvSkippedSum').textContent = '見送った物(' + sk.length + ' 本・3 日で消えます)';
    var ul = $('rcvSkipList');
    ul.textContent = '';
    sk.forEach(function (it) {
      ul.appendChild(el('li', { cls: 'fr-skip-row' }, [el('span', { cls: 'fr-skip-title', text: it.title }),
        el('span', { cls: 'hint', text: (it.verdict === 'bad' ? (it.reason === 'cut' ? '切り方が変' : 'つまらない') : '見送った') + '・あと ' + it.left + ' 日' }),
        el('button', { type: 'button', cls: 'btn ghost small', 'aria-label': it.title + ' を戻す', on: { click: function () { undo([it]); } } }, ['戻す'])]));
    });
  }

  /* ---------------------------------------------------------------- 再生画面(C-3-3) */
  function sideList() {
    var cur = find(my.cur), box = $('playerList');
    box.textContent = '';
    if (!cur) return;
    var secs = ((my.data || {}).sections || []).slice().sort(function (a, b) { return (a.key === cur.sec.key ? -1 : 0) - (b.key === cur.sec.key ? -1 : 0); });
    secs.forEach(function (s) {
      var ht = (s.streamer ? s.streamer + '|' : '') + (s.title || '');
      box.appendChild(el('div', { cls: 'fr-side-h', text: ht, title: ht }));
      s.items.forEach(function (it) { box.appendChild(card(it, s, true)); });
    });
    var on = box.querySelector('.fr-rcard.on'), side = box.parentNode;   /* 右の一覧の中だけ動かす(画面ごと動かすと上の見出しが隠れる) */
    if (on && side) {
      var top = on.offsetTop - side.offsetTop, bottom = top + on.offsetHeight;
      if (top < side.scrollTop) side.scrollTop = Math.max(0, top - 28);
      else if (bottom > side.scrollTop + side.clientHeight) side.scrollTop = bottom - side.clientHeight;
    }
  }
  function play(key) {
    var x = find(key);
    if (!x) { back(); return; }
    my.cur = key;
    $('rcvList').hidden = true;
    $('rcvPlayer').hidden = false;
    $('viewReceive').classList.add('playing');
    var v = $('playerVideo');
    $('playerNoVideo').hidden = x.it.preview;
    $('playerNoVideo').style.backgroundImage = x.it.preview || !x.sec.videoId ? '' : 'url("' + thumbOf(x.sec.videoId, 'hqdefault') + '")';
    v.hidden = !x.it.preview;
    if (x.it.preview) {
      v.src = 'api/friend/media?id=' + encodeURIComponent(x.it.id) + '&name=' + encodeURIComponent(x.it.name);
      v.currentTime = 0;   /* 次は最初から再生 */
      var p = v.play();
      if (p && p.catch) p.catch(function () { /* 自動の再生を止められた = 押せば再生 */ });
    } else v.removeAttribute('src');
    $('playerTitle').textContent = x.it.title;
    $('playerMeta').textContent = (x.it.clip ? x.it.clip + '・' : '') + (x.it.seconds ? FR.dur(x.it.seconds) : '') + (x.it.auto ? '・自動で届いた' : '');
    buttons();
    sideList();
  }
  function buttons() {
    var x = find(my.cur), can = !!x && open(x.it);
    ['btnKeep', 'btnSkip', 'btnBoring', 'btnCut'].forEach(function (id) { $(id).disabled = !can || my.busy; });
    $('btnKeep').textContent = x && x.it.want === 'keep' ? '受け取っています' : '受け取る';
  }
  function back() {
    my.cur = null;
    var v = $('playerVideo');
    v.pause(); v.removeAttribute('src'); v.load();
    $('rcvPlayer').hidden = true;
    $('viewReceive').classList.remove('playing');
    $('rcvList').hidden = false;
    renderList();
    bulk();
  }
  function nextAfter(key) {   /* 同じ配信の次の番号 → 次の配信 → 無ければ null */
    var list = all(), i = -1;
    list.forEach(function (x, j) { if (k(x.it) === key) i = j; });
    var cur = list[i], rest = list.filter(function (x, j) { return j !== i && open(x.it); });
    if (!cur) return rest[0] ? k(rest[0].it) : null;
    var same = rest.filter(function (x) { return x.sec.key === cur.sec.key && x.it.num > cur.it.num; })[0] ||
      rest.filter(function (x) { return x.sec.key === cur.sec.key; })[0];
    var other = rest.filter(function (x) { return x.sec.key !== cur.sec.key; })[0];
    return same ? k(same.it) : other ? k(other.it) : null;
  }

  /* ---------------------------------------------------------------- 決める(C-3-4・C-3-5・C-3-6) */
  function decide(items, verdict, reason) {
    if (!items.length || my.busy) return Promise.resolve(null);
    my.busy = true;
    var nxt = my.cur && items.length === 1 && k(items[0]) === my.cur ? nextAfter(my.cur) : null;
    return api('decide', { items: items.map(function (it) { return { id: it.id, name: it.name }; }), verdict: verdict, reason: reason || null }).then(function (j) {
      (j.errors || []).forEach(function (x) { UIKit.toast(x.message, { kind: 'err', ms: 0 }); });
      var done = j.done || [];
      items.forEach(function (it) { delete my.sel[k(it)]; });
      if (verdict === 'keep' && done.length) {
        var first = done[0];
        UIKit.toast(done.length > 1 ? done.length + ' 本を保存先に入れました' : '保存先に入れました', { ms: 5000,
          action: { label: 'フォルダを開く', fn: function () { api('open', first).catch(function (e) { FR.fail('開けませんでした', e); }); } } });
      } else if (verdict === 'keep' && (j.pending || []).length) {
        UIKit.toast('Dropbox から取ってきています(取り終えると保存先に入ります)', { ms: 5000 });
      } else if (done.length) {
        my.toast = UIKit.toast((verdict === 'bad' ? '届かなくてよかったにしました' : '見送りました') + (done.length > 1 ? '(' + done.length + ' 本)' : ''), { ms: 6000,
          action: { label: '戻す', fn: function () { undo(done); } } });
      }
      return FR.refresh().then(function () {
        if (!my.cur) return;
        if (nxt && my.cur !== nxt) play(nxt);
        else if (!nxt && !find(my.cur)) back();
      });
    }, function (e) { FR.fail(verdict === 'keep' ? '受け取れませんでした' : '決められませんでした', e); }).then(function () { my.busy = false; bulk(); buttons(); });
  }
  function undo(items) {
    return api('undo', { items: items.map(function (it) { return { id: it.id, name: it.name }; }) }).then(function (j) {
      (j.errors || []).forEach(function (x) { UIKit.toast(x.message, { kind: 'err', ms: 0 }); });
      if ((j.done || []).length) UIKit.toast('戻しました', { ms: 3000 });
      return FR.refresh();
    }, function (e) { FR.fail('戻せませんでした', e); });
  }
  function bulk() {
    var s = selected();
    $('bulkBar').hidden = !s.length;
    document.body.classList.toggle('fr-bulk-on', !!s.length && !my.cur);   /* 一覧の下の帯が出ている = 知らせを帯の上へ */
    $('bulkCount').textContent = s.length + ' 本を選んでいます';
    Array.prototype.forEach.call(document.querySelectorAll('.fr-rcard'), function (c) {
      var cb = c.querySelector('.fr-pick');
      if (cb) cb.checked = !!my.sel[c.getAttribute('data-key')];
    });
  }
  function bulkKeep() {
    var s = selected();
    if (!s.length) return;
    UIKit.dialog.confirm({ title: s.length + ' 本を受け取ります', body: s.slice(0, 10).map(function (it) { return '・' + it.title; }).join('\n') +
      (s.length > 10 ? '\nほか ' + (s.length - 10) + ' 本' : ''), ok: '受け取る' }).then(function (yes) { if (yes) decide(s, 'keep'); });
  }
  function clearSel() { my.sel = {}; bulk(); }

  /* ---------------------------------------------------------------- キー(C-3-10) */
  function onKey(e) {
    if (FR.view !== 'receive' || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('dialog[open]') || FR.drawerOpen()) return;
    if (e.key === 'Escape') {
      if (selected().length) { clearSel(); e.preventDefault(); return; }
      if (my.cur) { back(); e.preventDefault(); }
      return;
    }
    if (!my.cur || FR.typing(e.target)) return;
    var v = $('playerVideo');
    if (e.key === ' ' && !(e.target && e.target.tagName === 'BUTTON')) { e.preventDefault(); if (v.paused) v.play(); else v.pause(); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); v.currentTime = Math.max(0, v.currentTime + (e.key === 'ArrowLeft' ? -5 : 5)); }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); v.volume = Math.max(0, Math.min(1, v.volume + (e.key === 'ArrowUp' ? 0.1 : -0.1))); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    $ = FR.$; el = FR.el; api = FR.api;
    $('btnPlayerBack').addEventListener('click', back);
    function curItem() { var x = find(my.cur); return x ? [x.it] : []; }
    $('btnKeep').addEventListener('click', function () { decide(curItem(), 'keep'); });
    $('btnSkip').addEventListener('click', function () { decide(curItem(), 'skip'); });
    $('btnBoring').addEventListener('click', function () { decide(curItem(), 'bad', 'boring'); });
    $('btnCut').addEventListener('click', function () { decide(curItem(), 'bad', 'cut'); });
    $('bulkKeep').addEventListener('click', bulkKeep);
    $('bulkSkip').addEventListener('click', function () { decide(selected(), 'skip'); });
    $('bulkBoring').addEventListener('click', function () { decide(selected(), 'bad', 'boring'); });
    $('bulkCut').addEventListener('click', function () { decide(selected(), 'bad', 'cut'); });
    $('bulkClear').addEventListener('click', clearSel);
    document.addEventListener('keydown', onKey);
    FR.on(function (what, d) {
      if (what === 'view' && d !== 'receive') {   /* 送るへ切り替えた = 再生を止め、「見送りました [戻す]」を閉じる(一覧の下の「見送った物」からは戻せる) */
        if (my.cur) $('playerVideo').pause();
        if (my.toast && my.toast.close) { my.toast.close(); my.toast = null; }
        return;
      }
      if (what !== 'data') return;
      my.data = d.receive;
      Object.keys(my.sel).forEach(function (key) { var x = find(key); if (!x || !open(x.it)) delete my.sel[key]; });
      var key = JSON.stringify(d.receive.sections) + JSON.stringify(d.receive.skipped);
      if (key === my.key) return;
      my.key = key;
      if (my.cur) {   /* 再生中は動画を触らず、右の一覧に静かに足す(C-3-3) */
        if (!find(my.cur)) { if (!my.busy) { var n = nextAfter(my.cur); if (n) play(n); else back(); } } else { sideList(); buttons(); }
      } else renderList();
      bulk();
    });
  });
})();
