/* 受け取る画面(F3-4。notes:plan/done/f1-friend-requirements.md の C-3)。口 = GET api/friend/receive(friendapp/inbox.py の receive_view)・
   POST api/friend/decide {items, verdict: keep|skip, score: 1〜5 か null}・undo {items}(「届かなくてよかった」のボタンは 10-27 に外した。古い判定の bad は一覧で読む)・media?id=&name=(1 本の確認用の動画)・open {id, name}。
   一覧 = 配信ごとの段(最後に届いた時刻の新しい順・段の中は番号順)。カードを押すと再生画面(左に再生・右に同じ配信の物が先の一覧)。
   決めると自動で次(同じ配信の次の番号 → 次の配信 → 全部決まったら一覧)。チェックでまとめて決める帯。見送った物は 3 日の間 [戻す]。
   キー: 再生画面 = Space 再生 / 一時停止・← → 5 秒・↑ ↓ 音量・1〜5 面白さの点(もう一度で外す)・Esc 一覧へ(チェックがあれば先に外す)/ 一覧 = Esc でチェックを外す
   点(5 段階・10-27)は受け取る / 見送ると別に付けられる。選ばずに決めたら点は空(推測で埋めない)。再生する物が替わると空に戻る */
(function () {
  'use strict';
  var $, el, api;
  var my = { data: null, key: '', sel: {}, cur: null, playing: false, busy: false, score: null, bulkScore: null };

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
    if (it.hold && !it.verdict) th.appendChild(el('span', { cls: 'fr-badge fr-badge-sent fr-badge-hold', text: '迷っている', title: '迷っている印があります(3 日たっても自動で見送りません)' }));
    var bk = [th, el('span', { cls: 'fr-card-title', text: small ? '#' + it.num + ' ' + (it.clip || '') : it.clip || it.title })];
    if (it.overlapNote && !small) bk.push(el('span', { cls: 'fr-card-head fr-card-overlap', text: '⚠ ' + it.overlapNote, title: it.overlapNote }));
    var b = el('button', { type: 'button', cls: 'fr-rcard-btn', title: it.title, on: { click: function () { play(key); } } }, bk);
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
    var fa = document.activeElement, fc = fa && box.contains(fa) && fa.closest ? fa.closest('.fr-rcard') : null;   /* 描き直しでフォーカスを失わない(B-17) */
    var focusKey = fc && fc.getAttribute('data-key'), focusTag = fc && fa.tagName, focusText = fc && fa.textContent;
    box.textContent = '';
    d.sections.forEach(function (s) {
      var grid = el('div', { cls: 'fr-rcards' });
      s.items.forEach(function (it) { grid.appendChild(card(it, s)); });
      box.appendChild(el('section', { cls: 'fr-rsec', 'aria-label': s.title }, [secHead(s), grid]));
    });
    if (focusKey) {   /* 同じカードの同じ種類・同じ文字の要素へ(無ければカードの最初の押せる物) */
      var card2 = box.querySelector('.fr-rcard[data-key="' + CSS.escape(focusKey) + '"]');
      var cands = card2 ? Array.prototype.slice.call(card2.querySelectorAll('button, input, a[href], [tabindex]')) : [];
      var hit = cands.filter(function (x) { return x.tagName === focusTag && x.textContent === focusText; })[0] || cands[0];
      if (hit) hit.focus();
    }
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

  /* ---------------------------------------------------------------- 操作の帯(YouTube 風。再生 / 一時停止・シークバー・時刻・音量・速度)
     音量(消音かも)と速度は玄関が覚える(GET / POST api/friend/player。exe は起動ごとに番号が変わる = localStorage は使えない)。次の 1 本・開き直しも同じ値で始める */
  var RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
  var pl = { prefs: { volume: 1, muted: false, rate: 1 }, saveT: 0, applying: false, dragging: false, dragVol: false };
  var SVG = { play: 'M7 4.5v15l13-7.5z', pause: 'M6 5h4v14H6zM14 5h4v14h-4z',
    vol: 'M4 9v6h4l5 4V5L8 9zM16 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12', mute: 'M4 9v6h4l5 4V5L8 9zM16 9l5 6M21 9l-5 6' };
  function icon(btn, name) {
    var ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), path = document.createElementNS(ns, 'path');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    path.setAttribute('d', SVG[name]);
    if (name === 'vol' || name === 'mute') {
      path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '2');
      path.setAttribute('stroke-linejoin', 'round'); path.setAttribute('stroke-linecap', 'round');
    }
    svg.appendChild(path);
    btn.textContent = '';
    btn.appendChild(svg);
  }
  function tm(sec) { return isFinite(sec) ? FR.dur(Math.max(0, sec)) : '0:00'; }
  function drawBar() {
    var v = $('playerVideo'), d = v.duration, t = v.currentTime, frac = d > 0 ? Math.min(1, t / d) : 0;
    $('pDone').style.width = (frac * 100) + '%';
    $('pKnob').style.left = (frac * 100) + '%';
    var b = 0;
    for (var i = 0; i < v.buffered.length; i++) if (v.buffered.start(i) <= t + 0.5) b = Math.max(b, v.buffered.end(i));
    $('pBuf').style.width = (d > 0 ? Math.min(1, b / d) * 100 : 0) + '%';
    $('pTime').textContent = tm(t) + ' / ' + tm(d);
    $('pSeek').setAttribute('aria-valuemax', String(Math.round(d || 0)));
    $('pSeek').setAttribute('aria-valuenow', String(Math.round(t || 0)));
    $('pSeek').setAttribute('aria-valuetext', tm(t) + ' / ' + tm(d));
  }
  function drawState() {
    var v = $('playerVideo');
    icon($('pPlay'), v.paused ? 'play' : 'pause');
    $('pPlay').setAttribute('aria-label', v.paused ? '再生(Space)' : '一時停止(Space)');
    $('pPlay').title = $('pPlay').getAttribute('aria-label');
    var m = v.muted || v.volume === 0;
    icon($('pMute'), m ? 'mute' : 'vol');
    $('pMute').setAttribute('aria-label', m ? '消音をやめる' : '消音');
    $('pMute').title = $('pMute').getAttribute('aria-label');
    if (!pl.dragVol) $('pVol').value = String(v.muted ? 0 : v.volume);
    $('pRate').value = String(v.playbackRate);
  }
  function applyPrefs() {   /* 覚えた音量・速度を動画に(読み込み直すと速度が 1 に戻るので、1 本ごとに) */
    var v = $('playerVideo');
    pl.applying = true;
    v.volume = pl.prefs.volume; v.muted = pl.prefs.muted;
    v.playbackRate = v.defaultPlaybackRate = pl.prefs.rate;
    pl.applying = false;
    drawState();
  }
  function savePrefs() {
    var v = $('playerVideo');
    if (pl.applying) return;
    pl.prefs = { volume: Math.round(v.volume * 100) / 100, muted: !!v.muted, rate: RATES.indexOf(v.playbackRate) >= 0 ? v.playbackRate : 1 };
    clearTimeout(pl.saveT);
    pl.saveT = setTimeout(function () { api('player', pl.prefs).catch(function () { /* 覚えられなくても再生は続ける */ }); }, 500);
  }
  function seekAt(clientX, commit) {
    var r = $('pSeek').getBoundingClientRect(), v = $('playerVideo'), d = v.duration;
    var frac = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    if (commit && d > 0) { v.currentTime = frac * d; drawBar(); }
    return { frac: frac, sec: d > 0 ? frac * d : 0 };
  }
  function tip(clientX) {
    var at = seekAt(clientX, false), t = $('pTip');
    t.hidden = false;
    t.textContent = tm(at.sec);
    t.style.left = (at.frac * 100) + '%';
  }
  function toggle() { var v = $('playerVideo'); if (v.paused) { var p = v.play(); if (p && p.catch) p.catch(function () {}); } else v.pause(); }
  function volBy(d) { var v = $('playerVideo'); v.muted = false; v.volume = Math.max(0, Math.min(1, Math.round((v.volume + d) * 100) / 100)); }
  function initBar() {
    var v = $('playerVideo'), seek = $('pSeek');
    ['timeupdate', 'progress', 'loadedmetadata', 'durationchange', 'seeked'].forEach(function (ev) { v.addEventListener(ev, drawBar); });
    ['play', 'pause', 'volumechange', 'ratechange'].forEach(function (ev) { v.addEventListener(ev, drawState); });
    v.addEventListener('volumechange', savePrefs);
    v.addEventListener('ratechange', savePrefs);
    v.addEventListener('loadedmetadata', applyPrefs);
    v.addEventListener('loadedmetadata', function () { var x = find(my.cur); if (x) meta(x.it, v.duration); });
    v.addEventListener('click', toggle);
    $('pPlay').addEventListener('click', toggle);
    $('pMute').addEventListener('click', function () { if (v.muted || v.volume === 0) { v.muted = false; if (v.volume === 0) v.volume = 0.5; } else v.muted = true; });
    $('pVol').addEventListener('input', function () { pl.dragVol = true; v.muted = false; v.volume = parseFloat($('pVol').value) || 0; });
    $('pVol').addEventListener('change', function () { pl.dragVol = false; drawState(); });
    $('pRate').addEventListener('change', function () { v.playbackRate = parseFloat($('pRate').value) || 1; });
    seek.addEventListener('pointerdown', function (e) { pl.dragging = true; seek.setPointerCapture(e.pointerId); seekAt(e.clientX, true); tip(e.clientX); });
    seek.addEventListener('pointermove', function (e) { tip(e.clientX); if (pl.dragging) seekAt(e.clientX, true); });
    seek.addEventListener('pointerup', function (e) { pl.dragging = false; seekAt(e.clientX, true); });
    seek.addEventListener('pointerleave', function () { if (!pl.dragging) $('pTip').hidden = true; });
    api('player').then(function (j) { if (j && j.player) { pl.prefs = j.player; applyPrefs(); } }, function () {});
    drawState(); drawBar();
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
    if (my.scoreFor !== key) { my.score = null; my.scoreFor = key; paintScore(); }   /* 再生する物が替わったら点は空に戻す */
    $('rcvList').hidden = true;
    $('rcvPlayer').hidden = false;
    $('viewReceive').classList.add('playing');
    var v = $('playerVideo');
    $('playerNoVideo').hidden = x.it.preview;
    $('pbar').hidden = !x.it.preview;
    $('playerNoVideo').style.backgroundImage = x.it.preview || !x.sec.videoId ? '' : 'url("' + thumbOf(x.sec.videoId, 'hqdefault') + '")';
    v.hidden = !x.it.preview;
    if (x.it.preview) {
      v.src = 'api/friend/media?id=' + encodeURIComponent(x.it.id) + '&name=' + encodeURIComponent(x.it.name);
      v.currentTime = 0;   /* 次は最初から再生 */
      applyPrefs();        /* 音量・速度は覚えた値で始める */
      var p = v.play();
      if (p && p.catch) p.catch(function () { /* 自動の再生を止められた = 押せば再生 */ });
    } else v.removeAttribute('src');
    $('playerTitle').textContent = x.it.title;
    meta(x.it, null);
    buttons();
    sideList();
  }
  /* 題の下の 1 行。長さは受け取る動画の長さ 1 つだけ(確認用の動画を読んだら、その長さ = 帯の長さと同じ数に合わせる。古い動画で食い違っても 2 通りに見せない) */
  function meta(it, dur) {
    var sec = dur > 0 ? dur : it.seconds;
    $('playerMeta').textContent = (it.clip ? it.clip + '・' : '') + (sec ? '長さ ' + FR.dur(sec) : '') + (it.auto ? '・自動で届いた' : '');
    var h = $('playerHead');
    h.hidden = !it.overlapNote;
    h.textContent = it.overlapNote ? '⚠ ' + it.overlapNote : '';
  }
  function buttons() {
    var x = find(my.cur), can = !!x && open(x.it);
    var why = x && x.it.want === 'keep' ? 'Dropbox から取ってきています(取り終えると保存先に入ります)' : my.busy ? '決めています…' : '';
    ['btnKeep', 'btnSkip'].forEach(function (id) {
      if ($(id).getAttribute('data-title0') === null) $(id).setAttribute('data-title0', $(id).title || '');
      $(id).disabled = !can || my.busy;
      $(id).setAttribute('data-ui-why', $(id).disabled ? why : '');   /* 押せない理由(乗せると出る = ui.md B-04) */
      if ($(id).disabled && why) $(id).title = why; else if ($(id).getAttribute('data-title0') !== null) $(id).title = $(id).getAttribute('data-title0');
    });
    $('btnKeep').textContent = x && x.it.want === 'keep' ? '受け取っています' : '受け取る';
    $('btnHold').disabled = !can || my.busy;
    $('btnHold').setAttribute('aria-pressed', String(!!(x && x.it.hold)));
  }
  /* 迷っている物の印(10-29): 押すと付く・もう一度押すと外れる。判定ではない(受け取る・見送るとは別)・印のある物は 3 日の自動の見送りの外 */
  function toggleHold() {
    var x = find(my.cur);
    if (!x || !open(x.it) || my.busy) return;
    var on = !x.it.hold;
    my.busy = true;
    api('hold', { items: [{ id: x.it.id, name: x.it.name }], on: on }).then(function (j) {
      if ((j.done || []).length) {
        x.it.hold = on;
        UIKit.toast(on ? '迷っている印を付けました(3 日たっても自動で見送りません)' : '迷っている印を外しました', { ms: 3000 });
      }
      return FR.refresh();
    }, function (e) { FR.fail('印を変えられませんでした', e); }).then(function () { my.busy = false; buttons(); });
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
  /* 5 段階の点(10-27): 押すと選ぶ・同じ数をもう一度で外す。root = 再生画面か帯の .fr-score */
  function setScore(which, n) {
    my[which] = my[which] === n ? null : n;
    paintScore();
  }
  function paintScore() {
    [['playerScore', my.score], ['bulkScore', my.bulkScore]].forEach(function (p) {
      Array.prototype.forEach.call($(p[0]).querySelectorAll('.fr-sc'), function (b) {
        b.setAttribute('aria-pressed', String(Number(b.getAttribute('data-score')) === p[1]));
      });
    });
  }
  function decide(items, verdict, reason, score) {
    if (!items.length || my.busy) return Promise.resolve(null);
    my.busy = true;
    var nxt = my.cur && items.length === 1 && k(items[0]) === my.cur ? nextAfter(my.cur) : null;
    return api('decide', { items: items.map(function (it) { return { id: it.id, name: it.name }; }), verdict: verdict, reason: reason || null,
      score: score == null ? null : score }).then(function (j) {
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
        my.toast = UIKit.toast('見送りました' + (done.length > 1 ? '(' + done.length + ' 本)' : ''), { ms: 6000,
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
      (s.length > 10 ? '\nほか ' + (s.length - 10) + ' 本' : ''), ok: '受け取る' }).then(function (yes) { if (yes) decide(s, 'keep', null, my.bulkScore); });
  }
  function clearSel() { my.sel = {}; my.bulkScore = null; paintScore(); bulk(); }

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
    if (e.key === ' ' && !(e.target && /^(BUTTON|SELECT)$/.test(e.target.tagName))) { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); v.currentTime = Math.max(0, v.currentTime + (e.key === 'ArrowLeft' ? -5 : 5)); }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); volBy(e.key === 'ArrowUp' ? 0.1 : -0.1); }
    else if (/^[1-5]$/.test(e.key)) { e.preventDefault(); setScore('score', Number(e.key)); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    $ = FR.$; el = FR.el; api = FR.api;
    $('btnPlayerBack').addEventListener('click', back);
    function curItem() { var x = find(my.cur); return x ? [x.it] : []; }
    $('btnKeep').addEventListener('click', function () { decide(curItem(), 'keep', null, my.score); });
    $('btnSkip').addEventListener('click', function () { decide(curItem(), 'skip', null, my.score); });
    $('btnHold').addEventListener('click', toggleHold);
    $('bulkKeep').addEventListener('click', bulkKeep);
    $('bulkSkip').addEventListener('click', function () { decide(selected(), 'skip', null, my.bulkScore); });
    [['playerScore', 'score'], ['bulkScore', 'bulkScore']].forEach(function (p) {
      $(p[0]).addEventListener('click', function (e) {
        var b = e.target.closest('.fr-sc');
        if (b) setScore(p[1], Number(b.getAttribute('data-score')));
      });
    });
    $('bulkClear').addEventListener('click', clearSel);
    document.addEventListener('keydown', onKey);
    initBar();
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
