/* 友人の受信箱(F2-2)。口は friendapp/server.py の説明。外から来た文字(題・チャンネル・理由)は textContent でだけ入れる */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var POLL = 3000, POLL_AWAY = 10000;
  var state = { key: '', rows: [], form: null, open: {}, sel: {}, peek: null, peekUrl: '', sending: false, auto: '', hasKey: true };
  var timer = 0;

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'cls') e.className = attrs[k];
      else if (k === 'on') Object.keys(attrs.on).forEach(function (ev) { e.addEventListener(ev, attrs.on[ev]); });
      else if (attrs[k] === true) e.setAttribute(k, '');
      else if (attrs[k] !== false && attrs[k] != null) e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  function api(path, body) { return UIKit.http('api/friend/' + path, body === undefined ? {} : { body: body }); }
  function fail(what, e) { UIKit.toast(what + ': ' + e.message, { kind: 'err', detail: e.detail }); }

  /* ---------------------------------------------------------------- 送る欄 */
  function rangeRow(r) {
    var a = UIKit.timebox.create({ youtube: true, label: '区間の始まり', value: r ? r[0] : null });
    var b = UIKit.timebox.create({ youtube: true, label: '区間の終わり', value: r ? r[1] : null });
    var row = el('span', { cls: 'fr-range' }, [a, ' 〜 ', b,
      el('button', { type: 'button', cls: 'btn ghost small', title: 'この区間を外します', on: { click: function () { row.remove(); syncForm(); } } }, ['外す'])]);
    [a, b].forEach(function (x) { x.addEventListener('ui-time-commit', syncForm); x.addEventListener('ui-time', syncForm); });
    $('ranges').appendChild(row);
    return row;
  }
  function ranges() {
    var out = [], bad = '';
    Array.prototype.forEach.call($('ranges').querySelectorAll('.fr-range'), function (row) {
      var t = row.querySelectorAll('[data-ui-time]'), s = UIKit.timebox.get(t[0]), e = UIKit.timebox.get(t[1]);
      if (s == null && e == null) return;
      if (s == null || e == null || e <= s) bad = '区間は「始まり 〜 終わり」の順に、両方入れてください';
      else out.push([s, e]);
    });
    return { list: out, bad: bad };
  }
  function people() {
    return Array.prototype.map.call($('people').querySelectorAll('input'), function (x) { return x.value.trim(); }).filter(Boolean);
  }
  function syncForm() {
    var rg = ranges(), has = rg.list.length > 0;
    $('topLine').hidden = has;
    $('weightLine').hidden = has;
    $('rangeHint').textContent = rg.bad || (has ? rg.list.length + ' 本(区間の数)を切ります' : '任意。入れると、その区間だけを切ります');
    $('rangeHint').classList.toggle('fr-bad', !!rg.bad);
    $('weights').hidden = !$('useWeights').checked;
    var user = pc() === 'user', noKey = user && !state.hasKey;
    var ok = !!state.peek && !rg.bad && !state.sending && !noKey;
    var btn = $('btnSend');
    btn.disabled = !ok;
    btn.textContent = user ? '送る(ユーザーの PC へ)' : '送る';   /* 覚えた値がユーザーの PC のとき、「詳しく」を閉じていても分かるように(A-2) */
    btn.title = state.sending ? '送っています' : !state.peek ? 'YouTube の配信の URL を貼ると押せます' : rg.bad ? rg.bad :
      noKey ? 'Dropbox の鍵が無いので、ユーザーの PC には頼めません(「詳しく」の処理する PC を「この PC」に)' : '';
  }
  function pc() { var r = document.querySelector('input[name=pc]:checked'); return r ? r.value : 'this'; }
  function fillForm(f) {
    $('top').value = f.top;
    $('tracks').value = String(f.videoTracks);
    Array.prototype.forEach.call(document.querySelectorAll('input[name=batch]'), function (r) { r.checked = r.value === String(f.deliverBatch); });
    $('useWeights').checked = !!f.useWeights;
    Array.prototype.forEach.call(document.querySelectorAll('input[name=pc]'), function (r) { r.checked = r.value === (f.pc || 'this'); });
    $('wAudio').value = f.weights.wAudio; $('wChat').value = f.weights.wChat; $('wComments').value = f.weights.wComments;
  }
  var peekSeq = 0;
  function onUrl() {
    var u = $('url').value.trim();
    if (u === state.peekUrl) return;
    state.peekUrl = u; state.peek = null; syncForm();
    if (!u) { $('peek').textContent = ''; return; }
    var my = ++peekSeq;
    $('peek').textContent = '配信を調べています…';
    api('peek?url=' + encodeURIComponent(u)).then(function (p) {
      if (my !== peekSeq) return;
      state.peek = p;
      $('peek').textContent = (p.title || '(題が取れませんでした)') + (p.channel ? ' ・ ' + p.channel : '');
      var s = $('streamer');
      if (!s.value.trim() || s.value === state.auto) {   /* 自分で打った名前は上書きしない */
        UIKit.streamer.set(s, p.streamer || '');
        state.auto = p.streamer || '';
        $('streamerAuto').hidden = !p.streamer;
      }
      syncForm();
    }, function (e) {
      if (my !== peekSeq) return;
      $('peek').textContent = e.message;
      syncForm();
    });
  }
  function num(id, lo, hi, dflt) { var v = parseInt($(id).value, 10); return isNaN(v) ? dflt : Math.max(lo, Math.min(hi, v)); }
  function send() {
    var rg = ranges();
    if (!state.peek || rg.bad) return;
    var batch = document.querySelector('input[name=batch]:checked');
    var body = { url: $('url').value.trim(), title: state.peek.title, channel: state.peek.channel, ranges: rg.list,
      top: rg.list.length ? null : num('top', 1, 30, 10), streamer: $('streamer').value.trim(), people: people(),
      videoTracks: parseInt($('tracks').value, 10) || 1, deliverBatch: batch ? parseInt(batch.value, 10) : 5,
      useWeights: $('useWeights').checked, pc: pc(),
      weights: { wAudio: num('wAudio', 0, 3, 1), wChat: num('wChat', 0, 3, 1), wComments: num('wComments', 0, 3, 1) } };
    state.sending = true; syncForm();
    api('send', body).then(function () {
      UIKit.toast(body.pc === 'user' ? 'ユーザーの PC に頼みました。作り終えると、下の受信箱に届きます' : '送りました。作り終えると、下の受信箱に届きます', { ms: 3000 });
      $('url').value = ''; state.peekUrl = ''; state.peek = null; $('peek').textContent = '';
      $('ranges').textContent = ''; $('people').textContent = '';
      UIKit.streamer.set($('streamer'), ''); state.auto = ''; $('streamerAuto').hidden = true;
      refresh();
    }, function (e) { fail('送れませんでした', e); }).then(function () { state.sending = false; syncForm(); });
  }

  /* ---------------------------------------------------------------- 受信箱 */
  var PILL = { sent: ['wait', '送った'], making: ['run', '作っている'], arrived: ['ok', '届いた'], failed: ['err', '失敗'] };
  function rowTitle(r) { return (r.source && (r.source.title || r.source.videoId)) || r.id; }
  function when(r) { return UIKit.fmt.ago(r.updatedAt || r.createdAt); }
  function stepText(run) {
    if (!run) return 'ほかの依頼のあとに始めます';
    if (run.state === 'queued') return run.message || '順番を待っています';
    var st = (run.steps || []).filter(function (s) { return s.state === 'run'; })[0];
    return st ? st.label + (st.detail ? '(' + st.detail + ')' : '') + 'の途中' : (run.stateLabel || '作っています');
  }
  function decide(r, names, verdict) {
    return api('decide', { id: r.id, names: names, verdict: verdict }).then(function (j) {
      (j.errors || []).forEach(function (x) { UIKit.toast(x.name + ': ' + x.message, { kind: 'err', ms: 0 }); });
      if (j.pending && j.pending.length) UIKit.toast(j.pending.length + ' 本を Dropbox から取ってきます(受け取り終えると保存先に並びます)', { ms: 3000 });
      if (j.done && j.done.length) UIKit.toast(verdict === 'keep' ? j.done.length + ' 本を保存先へ移しました' : j.done.length + ' 本を要らないにしました', { ms: 2500 });
      state.sel[r.id] = {};
      refresh();
    }, function (e) { fail(verdict === 'keep' ? '受け取れませんでした' : '要らないにできませんでした', e); });
  }
  function rejectSelected(r, names) {
    var titles = r.packs.filter(function (p) { return names.indexOf(p.name) >= 0; }).map(function (p) { return '・' + p.title; });
    UIKit.dialog.confirm({ title: names.length + ' 本を要らないにします', body: titles.slice(0, 10).join('\n') + (titles.length > 10 ? '\nほか ' + (titles.length - 10) + ' 本' : '') +
      '\nパックはごみ箱へ移します(3 日で消えます)', ok: '要らない', danger: true }).then(function (yes) { if (yes) decide(r, names, 'reject'); });
  }
  function packList(r, g) {
    var sel = state.sel[r.id] = state.sel[r.id] || {};
    var video = null;
    if (g.preview) {
      video = el('video', { cls: 'fr-video', controls: true, preload: 'metadata', src: 'api/friend/media?id=' + encodeURIComponent(r.id) + '&n=' + g.n });
    }
    var at = 0, items = g.names.map(function (n) {
      var p = r.packs.filter(function (x) { return x.name === n; })[0];
      if (!p) return null;
      var start = at;
      at = (at != null && p.seconds) ? at + p.seconds : null;
      var cb = el('input', { type: 'checkbox', 'aria-label': p.title + ' を選ぶ', disabled: !!p.verdict || p.want === 'keep' });
      cb.checked = !!sel[n];
      cb.addEventListener('change', function () { sel[n] = cb.checked; render(); });
      var kids = [el('label', { cls: 'fr-pack-pick' }, [cb, el('span', { cls: 'fr-pack-title', text: p.title })])];
      if (p.verdict) kids.push(el('span', { cls: 'pill ' + (p.verdict === 'keep' ? 'ok' : 'wait'), text: p.verdict === 'keep' ? '受け取った' : '要らない' }));
      else if (p.want === 'keep') kids.push(el('span', { cls: 'pill run', text: '受け取っています' }));
      else {
        if (p.error) kids.push(el('span', { cls: 'fr-err', text: p.error }));
        if (video && start != null) kids.push(el('button', { type: 'button', cls: 'btn ghost small', title: 'まとめ動画のこの切り抜きの所から再生します', on: { click: function () { video.currentTime = start; video.play(); } } }, ['ここから見る']));
        kids.push(el('button', { type: 'button', cls: 'btn small', on: { click: function () { decide(r, [n], 'keep'); } } }, ['受け取る']));
        kids.push(el('button', { type: 'button', cls: 'btn ghost small', on: { click: function () { rejectSelected(r, [n]); } } }, ['要らない']));
      }
      return el('li', { cls: 'fr-pack' }, kids);
    });
    return el('div', { cls: 'fr-group' }, [
      r.groups.length > 1 ? el('div', { cls: 'fr-group-h', text: g.n + ' 組目' }) : null,
      video || el('p', { cls: 'hint', text: g.remote ? 'まとめ動画を Dropbox から取ってきています(取り終えると、ここで続けて見られます)' : 'まとめ動画を作っています(できると、ここで続けて見られます)' }),
      el('ul', { cls: 'fr-packs' }, items)]);
  }
  function remoteText(r) {
    var st = (r.remote || {}).state;
    if (r.state === 'making' || st === 'accepted') return 'ユーザーの PC で作っています';
    if (st === 'pending') return state.hasKey ? 'Dropbox へ送っています(つながらなければ次の見回りでもう一度)' : 'Dropbox の鍵が無いので送れません';
    return 'ユーザーの PC の受付を待っています' + (r.waitHours >= 1 ? '(' + r.waitHours + ' 時間)' : '');
  }
  function rowEl(r) {
    var pill = PILL[r.state] || ['info', r.state];
    var head = [el('span', { cls: 'pill ' + pill[0], text: pill[1] }), el('span', { cls: 'fr-title', text: rowTitle(r), title: (r.source && r.source.url) || '' })];
    if (r.origin === 'auto') head.push(el('span', { cls: 'pill info', text: '依頼なし', title: 'ユーザーの PC が自分の配信から自動で届けた物です' }));
    if (r.pc === 'user') head.push(el('span', { cls: 'pill info', text: 'ユーザーの PC', title: 'ユーザーの PC で作った(作っている)依頼です' }));
    if (r.form && r.form.streamer) head.push(el('span', { cls: 'fr-who', text: r.form.streamer }));
    head.push(el('span', { cls: 'fr-when', text: when(r) }));
    var acts = [], sub = [];
    if ((r.state === 'sent' || r.state === 'making') && r.pc === 'user') {
      sub.push(el('span', { cls: 'hint', text: remoteText(r) }));
      if (r.canLocal) acts.push(el('button', { type: 'button', cls: 'btn small', title: 'ユーザーの PC への依頼を取り消して、同じ欄でこの PC で作ります', on: { click: function () {
        api('local', { id: r.id }).then(function () { UIKit.toast('この PC で作り直します', { ms: 2500 }); refresh(); }, function (e) { fail('この PC でやり直せませんでした', e); });
      } } }, ['この PC でやり直す']));
    } else if (r.state === 'sent' || r.state === 'making') {
      sub.push(el('span', { cls: 'hint', text: r.state === 'making' ? stepText(r.run) : '順番を待っています' }));
      acts.push(el('button', { type: 'button', cls: 'btn ghost small', title: 'この依頼を止めます(行は「失敗」になり、[もう一度送る] で続きから)', on: { click: function () {
        api('cancel', { id: r.id }).then(refresh, function (e) { fail('止められませんでした', e); });
      } } }, ['止める']));
    } else if (r.state === 'failed') {
      sub.push(el('span', { cls: 'fr-err', text: r.error || '止まりました' }));
      if (r.left != null) sub.push(el('span', { cls: 'hint', text: 'あと ' + r.left + ' 日で片付けます' }));
      if (r.form) acts.push(el('button', { type: 'button', cls: 'btn small ui-next-btn', on: { click: function () {
        api('retry', { id: r.id }).then(refresh, function (e) { fail('送れませんでした', e); });
      } } }, ['もう一度送る']));
      acts.push(el('button', { type: 'button', cls: 'btn ghost small', on: { click: function () {
        api('remove', { id: r.id }).then(refresh, function (e) { fail('消せませんでした', e); });
      } } }, ['消す']));
    } else if (r.state === 'arrived') {
      var sel = state.sel[r.id] || {}, picked = r.packs.filter(function (p) { return !p.verdict && sel[p.name]; }).map(function (p) { return p.name; });
      sub.push(el('span', { cls: 'hint', text: r.undecided + ' 本 まだ決めていません' + (r.left != null ? '(あと ' + r.left + ' 日で自動で要らないにします)' : '') }));
      if (r.note) sub.push(el('span', { cls: 'fr-err', text: r.note }));   /* ユーザーの PC の失敗の知らせ(一部だけ届いたとき) */
      var open = !!state.open[r.id];
      acts.push(el('button', { type: 'button', cls: 'btn small ui-next-btn', 'aria-expanded': open ? 'true' : 'false', on: { click: function () { state.open[r.id] = !open; render(); } } }, [open ? '閉じる' : '開く']));
      acts.push(el('button', { type: 'button', cls: 'btn small', title: picked.length ? '選んだ物を保存先へ移します' : 'まだ決めていない物を全部保存先へ移します',
        on: { click: function () { decide(r, picked, 'keep'); } } }, [picked.length ? '選んだ ' + picked.length + ' 本を受け取る' : 'すべて受け取る']));
      acts.push(el('button', { type: 'button', cls: 'btn ghost small', disabled: !picked.length, title: picked.length ? '' : '開いて、要らない物にチェックを付けると押せます',
        on: { click: function () { rejectSelected(r, picked); } } }, [picked.length ? '選んだ ' + picked.length + ' 本を要らない' : '選んだ物を要らない']));
    }
    var body = el('div', { cls: 'fr-row-body' }, [el('div', { cls: 'fr-row-head' }, head), el('div', { cls: 'fr-row-sub' }, sub)]);
    var row = el('div', { cls: 'fr-row', 'data-row': r.id }, [body, el('div', { cls: 'fr-row-acts' }, acts)]);
    if (r.state === 'arrived' && state.open[r.id]) {
      return el('div', { cls: 'fr-item open' }, [row, el('div', { cls: 'fr-detail' }, r.groups.map(function (g) { return packList(r, g); }))]);
    }
    return el('div', { cls: 'fr-item' }, [row]);
  }
  function render() {
    var list = $('list'), vids = list.querySelectorAll('video');
    for (var i = 0; i < vids.length; i++) if (!vids[i].paused) return;   /* 再生中は描き直さない(次の問い合わせで) */
    list.textContent = '';
    state.rows.forEach(function (r) { list.appendChild(rowEl(r)); });
    $('empty').hidden = state.rows.length > 0;
    list.hidden = !state.rows.length;
    $('count').textContent = state.rows.length ? state.rows.length + ' 件' : '';
  }
  function banner(j) {
    var sy = j.sync || {};
    state.hasKey = sy.key !== false;
    $('noKey').hidden = !sy.message;
    $('noKey').textContent = sy.message || '';
    $('updated').hidden = !sy.updated;
    $('updated').textContent = sy.updated ? '新しい版 ' + sy.updated + ' を入れました(次に開いたときから)' : '';
    $('pcUser').disabled = !state.hasKey;
    $('pcUserLabel').title = state.hasKey ? '' : 'Dropbox の鍵が無いので選べません';
    syncForm();
    var p = j.prep || {};
    $('prep').hidden = p.state === 'ready';
    $('prep').textContent = p.message || '';
    $('prep').classList.toggle('err', p.state === 'error');
    var b = j.blocked;
    $('blocked').hidden = !b;
    if (b) $('blocked').textContent = '空き容量が ' + b.freeGB + ' GB です。' + b.minGB + ' GB を切ったので、新しい処理を始めずに待っています(不要なファイルを消すと続きから始めます)';
    $('cleaned').hidden = !(j.notice || j.rollback);
    $('cleanedText').textContent = (j.rollback ? j.rollback + '。' : '') +
      (j.notice ? 'C: の古い部品 ' + j.notice.freedGB + ' GB を片付けました(新しいアプリの場所へ写してあります)' : '');
  }
  function refresh() {
    clearTimeout(timer);
    return api('inbox').then(function (j) {
      $('errbar').hidden = true;
      if (!state.form) { state.form = j.form; fillForm(j.form); syncForm(); }
      var key = JSON.stringify(j.rows || []);
      $('btnSaved').title = '受け取ったパックの保存先を開きます: ' + (j.saveDir || '');
      banner(j);
      if (key === state.key) return;   /* 変わっていなければ描き直さない(押そうとしているボタン・フォーカスを消さない) */
      state.key = key;
      state.rows = j.rows || [];
      render();
    }, function (e) {
      $('errbar').hidden = false;
      $('errbar').textContent = 'アプリの処理の部品とつながりません(' + e.message + ')。アプリを開き直してください';
    }).then(function () { timer = setTimeout(refresh, UIKit.life.isAway() ? POLL_AWAY : POLL); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var v = document.querySelector('meta[name="ytt-version"]');
    $('ver').textContent = v ? 'v' + v.content : '';
    UIKit.streamer.attach($('streamer'));
    $('url').addEventListener('input', onUrl);
    $('url').addEventListener('change', onUrl);
    $('url').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !$('btnSend').disabled) send(); });
    $('streamer').addEventListener('input', function () { $('streamerAuto').hidden = $('streamer').value !== state.auto || !state.auto; });
    $('btnSend').addEventListener('click', send);
    $('btnRange').addEventListener('click', function () { rangeRow(); syncForm(); });
    $('btnPerson').addEventListener('click', function () {
      var i = el('input', { type: 'text', cls: 'fr-streamer', 'aria-label': 'コラボの相手の名前', placeholder: '名前', autocomplete: 'off' });
      var w = el('span', { cls: 'fr-person' }, [i, el('button', { type: 'button', cls: 'btn ghost small', title: 'この人を外します', on: { click: function () { w.remove(); } } }, ['外す'])]);
      $('people').appendChild(w);
      UIKit.streamer.attach(i);
      i.focus();
    });
    $('useWeights').addEventListener('change', syncForm);
    Array.prototype.forEach.call(document.querySelectorAll('input[name=pc]'), function (r) { r.addEventListener('change', syncForm); });
    $('btnSaved').addEventListener('click', function () { api('open', { what: 'saved' }).catch(function (e) { fail('開けませんでした', e); }); });
    $('btnQuit').addEventListener('click', function () {
      api('../shutdown', {}).then(function () {
        clearTimeout(timer);
        document.querySelector('.fr-main').textContent = '';
        document.querySelector('.fr-main').appendChild(el('p', { cls: 'fr-bye', text: '止めて終了しました。この窓は閉じてかまいません(次に開くと、待っていた依頼の続きから始めます)' }));
      }, function (e) { fail('終了できませんでした', e); });
    });
    $('cleanedOk').addEventListener('click', function () { api('notice-seen', {}).then(function () { $('cleaned').hidden = true; }); });
    UIKit.life.onReturn(function () { refresh(); });
    refresh();
  });
})();
