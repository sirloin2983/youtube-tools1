/* 友人の受信箱(F2-2)。口は friendapp/server.py の説明。外から来た文字(題・チャンネル・理由)は textContent でだけ入れる。
   F2-6: 動画ファイル([動画ファイルを選ぶ] = 玄関が Windows の窓を開いて id で覚える)・ライブ(URL が配信中・配信前なら 6 つの設定を出す) */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var POLL = 3000, POLL_AWAY = 10000;
  var state = { key: '', rows: [], form: null, open: {}, sel: {}, peek: null, peekUrl: '', sending: false, auto: '', hasKey: true,
    file: null, live: null, liveBusy: false, picking: false, partsWhy: '', setupKey: '', setupRun: false };
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
  function sizeText(n) { return n == null ? '不明' : n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : Math.max(1, Math.round(n / 1e6)) + ' MB'; }
  function helpLink(sec, what) {   /* [?] = 説明の節を新しい窓で開く(F2-5。9-3) */
    return el('a', { cls: 'btn ghost small fr-help', href: 'guide.html#' + sec, target: '_blank', rel: 'noopener', 'aria-label': what + 'を新しい窓で開く', title: what }, ['?']);
  }
  function pct(p) { return p && p.total ? Math.floor(p.done * 100 / p.total) + '%' : ''; }
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
  /* 送る物: 'file'(動画ファイルを選んだ)・'live'(配信中・配信前の URL)・'url' */
  function mode() { return state.file ? 'file' : (state.live && state.live.live ? 'live' : 'url'); }
  function syncForm() {
    var m = mode(), rg = m === 'url' ? ranges() : { list: [], bad: '' }, has = rg.list.length > 0;
    $('rangeLine').hidden = m !== 'url';
    $('topLine').hidden = has || m === 'file';
    $('topHint').textContent = m === 'live' ? '録画 1 本で自動で切る上限です' : '自動で見どころを探して、この本数を切ります';
    $('weightLine').hidden = has || m !== 'url';
    $('live').hidden = m !== 'live';
    $('rangeHint').textContent = rg.bad || (has ? rg.list.length + ' 本(区間の数)を切ります' : '任意。入れると、その区間だけを切ります');
    $('rangeHint').classList.toggle('fr-bad', !!rg.bad);
    $('weights').hidden = !$('useWeights').checked;
    $('url').hidden = !!state.file;
    $('fileChip').hidden = !state.file;
    $('urlLabel').textContent = state.file ? '動画ファイル' : '配信の URL';
    $('btnPick').hidden = !!state.file;
    $('btnPick').disabled = state.picking;
    var user = pc() === 'user', noKey = user && !state.hasKey, noParts = !user && !!state.partsWhy;   /* 部品が足りない = この PC では作れない(F2-5。9-1) */
    var postLive = m === 'url' && state.live && state.live.status === 'post_live';
    var ready = m === 'file' ? true : (!!state.peek && !state.liveBusy && !postLive);
    var ok = ready && !rg.bad && !state.sending && !noKey && !noParts;
    $('sendWhy').hidden = !noParts;
    $('sendWhy').textContent = noParts ? state.partsWhy : '';
    var btn = $('btnSend');
    btn.disabled = !ok;
    btn.textContent = (m === 'live' ? '録画を頼む' : '送る') + (user ? '(ユーザーの PC へ)' : '');   /* 覚えた値がユーザーの PC のとき、「詳しく」を閉じていても分かるように(A-2) */
    btn.title = state.sending ? '送っています' : noParts ? state.partsWhy : m !== 'file' && !state.peek ? 'YouTube の配信の URL を貼るか、動画ファイルを選ぶと押せます' :
      state.liveBusy ? '配信中か調べています(数秒)' : postLive ? state.live.message : rg.bad ? rg.bad :
      noKey ? 'Dropbox の鍵が無いので、ユーザーの PC には頼めません(「詳しく」の処理する PC を「この PC」に)' : '';
  }
  function pc() { var r = document.querySelector('input[name=pc]:checked'); return r ? r.value : 'this'; }
  function fillLive(s) {
    Array.prototype.forEach.call(document.querySelectorAll('input[name=lvSens]'), function (r) { r.checked = r.value === s.sens; });
    $('lvPerHour').value = s.perHour; $('lvLength').value = s.length; $('lvWait').value = s.waitMin; $('lvPad').value = s.pad;
    $('lvAfter').checked = !!s.afterStream;
  }
  function fillForm(f) {
    $('top').value = f.top;
    $('tracks').value = String(f.videoTracks);
    Array.prototype.forEach.call(document.querySelectorAll('input[name=batch]'), function (r) { r.checked = r.value === String(f.deliverBatch); });
    $('useWeights').checked = !!f.useWeights;
    Array.prototype.forEach.call(document.querySelectorAll('input[name=pc]'), function (r) { r.checked = r.value === (f.pc || 'this'); });
    $('wAudio').value = f.weights.wAudio; $('wChat').value = f.weights.wChat; $('wComments').value = f.weights.wComments;
    if (f.live) fillLive(f.live);
  }
  function setAutoStreamer(name) {
    var s = $('streamer');
    if (!s.value.trim() || s.value === state.auto) {   /* 自分で打った名前は上書きしない */
      UIKit.streamer.set(s, name || '');
      state.auto = name || '';
      $('streamerAuto').hidden = !name;
    }
  }
  var peekSeq = 0;
  function onUrl() {
    var u = $('url').value.trim();
    if (u === state.peekUrl) return;
    state.peekUrl = u; state.peek = null; state.live = null; state.liveBusy = false; syncForm();
    if (!u) { $('peek').textContent = ''; FRList.select(''); return; }
    var my = ++peekSeq;
    $('peek').textContent = '配信を調べています…';
    api('peek?url=' + encodeURIComponent(u)).then(function (p) {
      if (my !== peekSeq) return;
      state.peek = p;
      FRList.select(FRList.item(p.videoId) ? p.videoId : '');   /* 一覧にある配信ならそのカードを選んだ状態に(C-2-17) */
      $('peek').textContent = (p.title || '(題が取れませんでした)') + (p.channel ? ' ・ ' + p.channel : '');
      setAutoStreamer(p.streamer);
      state.liveBusy = true;   /* 配信中・配信前か(yt-dlp で数秒)。分かるまで [送る] は待つ(ライブを普通の URL で送らない) */
      syncForm();
      return api('peek-live?url=' + encodeURIComponent(u)).then(function (lv) {
        if (my !== peekSeq) return;
        state.live = lv;
        $('liveNote').textContent = lv.status === 'is_upcoming' ? '配信前です。始まったら録画しながら切り抜きます' : '配信中です。録画しながら切り抜きます';
        if (lv.status === 'post_live') $('peek').textContent += ' ・ ' + lv.message;
      }, function () { if (my === peekSeq) state.live = null; }).then(function () {
        if (my !== peekSeq) return;
        state.liveBusy = false; syncForm();
      });
    }, function (e) {
      if (my !== peekSeq) return;
      $('peek').textContent = e.message;
      syncForm();
    });
  }
  function pickFile() {
    state.picking = true; syncForm();
    api('pick-file', {}).then(function (j) {
      if (!j.file) return;   /* 窓でやめた */
      state.file = j.file;
      $('fileName').textContent = j.file.name;
      $('fileName').title = j.file.name;
      $('peek').textContent = '動画ファイル: ' + j.file.name + '(' + sizeText(j.file.size) + ')';
      setAutoStreamer(j.file.streamer);
    }, function (e) { fail('ファイルを選べませんでした', e); }).then(function () { state.picking = false; syncForm(); });
  }
  function clearFile() {
    state.file = null; $('fileName').textContent = ''; $('peek').textContent = '';
    state.peekUrl = ''; onUrl(); syncForm();
  }
  function num(id, lo, hi, dflt) { var v = parseInt($(id).value, 10); return isNaN(v) ? dflt : Math.max(lo, Math.min(hi, v)); }
  function liveSettings() {
    var s = document.querySelector('input[name=lvSens]:checked'), pad = parseFloat($('lvPad').value);
    return { sens: s ? s.value : 'normal', perHour: num('lvPerHour', 1, 30, 6), length: num('lvLength', 10, 180, 45), waitMin: num('lvWait', 1, 60, 5),
      pad: isNaN(pad) ? 2 : Math.max(0, Math.min(5, pad)), afterStream: $('lvAfter').checked };
  }
  function send() {
    var m = mode(), rg = m === 'url' ? ranges() : { list: [], bad: '' };
    if ($('btnSend').disabled || rg.bad) return;
    var batch = document.querySelector('input[name=batch]:checked');
    var body = { source: m === 'file' ? 'file' : 'url', ranges: rg.list,
      top: rg.list.length || m === 'file' ? null : num('top', 1, 30, 10), streamer: $('streamer').value.trim(), people: people(),
      videoTracks: parseInt($('tracks').value, 10) || 1, deliverBatch: batch ? parseInt(batch.value, 10) : 5,
      useWeights: m === 'url' && $('useWeights').checked, pc: pc(),
      weights: { wAudio: num('wAudio', 0, 3, 1), wChat: num('wChat', 0, 3, 1), wComments: num('wComments', 0, 3, 1) } };
    if (m === 'file') body.fileId = state.file.id;
    else { body.url = $('url').value.trim(); body.title = state.peek.title; body.channel = state.peek.channel; }
    if (m === 'live') { body.kind = 'live'; body.live = liveSettings(); }
    state.sending = true; syncForm();
    api('send', body).then(function () {
      UIKit.toast(m === 'live' ? (body.pc === 'user' ? 'ユーザーの PC に録画を頼みました。切り抜けしだい、下の受信箱に届きます' : '録画を始めました。切り抜けしだい、下の受信箱に届きます') :
        body.pc === 'user' ? 'ユーザーの PC に頼みました。作り終えると、下の受信箱に届きます' : '送りました。作り終えると、下の受信箱に届きます', { ms: 3000 });
      $('url').value = ''; state.peekUrl = ''; state.peek = null; state.live = null; $('peek').textContent = '';
      state.file = null; $('fileName').textContent = '';
      $('ranges').textContent = ''; $('people').textContent = '';
      UIKit.streamer.set($('streamer'), ''); state.auto = ''; $('streamerAuto').hidden = true;
      refresh();
    }, function (e) { fail(m === 'live' ? '録画を始められませんでした' : '送れませんでした', e); }).then(function () { state.sending = false; syncForm(); });
  }

  /* ---------------------------------------------------------------- 受信箱 */
  var PILL = { sent: ['wait', '送った'], making: ['run', '作っている'], recording: ['run', '録画中'], arrived: ['ok', '届いた'], failed: ['err', '失敗'] };
  function rowTitle(r) { return (r.source && (r.source.title || r.source.fileName || r.source.videoId)) || r.id; }
  function livePhase(r) { return (r.live && r.live.phase) || 'recording'; }
  function liveText(r) {
    var ph = livePhase(r), got = r.packs.length - (r.waitingPacks || 0);
    var t = ph === 'making' ? '録画は終わりました。残りの切り抜きを作っています' : ph === 'after' ? '録画は終わりました。配信後のアーカイブから切り抜くのを待っています' :
      ph === 'done' ? '' : '録画しながら切り抜いています';
    var n = r.packs.length ? '届いた ' + got + ' 本' + (r.waitingPacks ? '・組になるのを待っている ' + r.waitingPacks + ' 本' : '') : '切り抜けしだい、ここに届きます';
    return t + (t ? '(' + n + ')' : n);
  }
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
      r.groups.length > 1 || g.label ? el('div', { cls: 'fr-group-h', text: g.n + ' 組目' + (g.label ? '(' + g.label + ')' : '') }) : null,
      video || el('p', { cls: 'hint', text: g.remote ? 'まとめ動画を Dropbox から取ってきています(取り終えると、ここで続けて見られます)' : 'まとめ動画を作っています(できると、ここで続けて見られます)' }),
      el('ul', { cls: 'fr-packs' }, items)]);
  }
  function remoteText(r) {
    var st = (r.remote || {}).state;
    if (r.state === 'making' || st === 'accepted') return 'ユーザーの PC で作っています';
    if (st === 'pending' && r.progress) return 'Dropbox へ動画を上げています(' + pct(r.progress) + ')';
    if (st === 'pending') return state.hasKey ? 'Dropbox へ送っています(つながらなければ次の見回りでもう一度)' : 'Dropbox の鍵が無いので送れません';
    return 'ユーザーの PC の受付を待っています' + (r.waitHours >= 1 ? '(' + r.waitHours + ' 時間)' : '');
  }
  function decideActs(r, acts, sub) {
    var sel = state.sel[r.id] || {}, picked = r.packs.filter(function (p) { return !p.verdict && sel[p.name]; }).map(function (p) { return p.name; });
    if (r.state === 'arrived') sub.push(el('span', { cls: 'hint', text: r.undecided + ' 本 まだ決めていません' + (r.left != null ? '(あと ' + r.left + ' 日で自動で要らないにします)' : '') }));
    if (r.note) sub.push(el('span', { cls: 'fr-err', text: r.note }));   /* ユーザーの PC の失敗の知らせ(一部だけ届いたとき) */
    if (!r.groups.length) return;
    var open = !!state.open[r.id];
    acts.push(el('button', { type: 'button', cls: 'btn small ui-next-btn', 'aria-expanded': open ? 'true' : 'false', on: { click: function () { state.open[r.id] = !open; render(); } } }, [open ? '閉じる' : '開く']));
    if (!r.undecided) return;
    acts.push(el('button', { type: 'button', cls: 'btn small', title: picked.length ? '選んだ物を保存先へ移します' : 'まだ決めていない物を全部保存先へ移します',
      on: { click: function () { decide(r, picked, 'keep'); } } }, [picked.length ? '選んだ ' + picked.length + ' 本を受け取る' : 'すべて受け取る']));
    acts.push(el('button', { type: 'button', cls: 'btn ghost small', disabled: !picked.length, title: picked.length ? '' : '開いて、要らない物にチェックを付けると押せます',
      on: { click: function () { rejectSelected(r, picked); } } }, [picked.length ? '選んだ ' + picked.length + ' 本を要らない' : '選んだ物を要らない']));
  }
  function rowEl(r) {
    var pill = PILL[r.state] || ['info', r.state];
    if (r.state === 'recording' && livePhase(r) !== 'recording') pill = ['run', '作っている'];
    var head = [el('span', { cls: 'pill ' + pill[0], text: pill[1] }), el('span', { cls: 'fr-title', text: rowTitle(r), title: (r.source && r.source.url) || '' })];
    if (r.kind === 'live') head.push(el('span', { cls: 'pill info', text: 'ライブ', title: '配信を録画しながら切り抜く依頼です' }));
    if (r.kind === 'file') head.push(el('span', { cls: 'pill info', text: '動画ファイル', title: 'パソコンの動画ファイルを送った依頼です' }));
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
    } else if (r.state === 'sent' && r.kind === 'file' && !r.runId) {   /* 動画を一時保管へ写している(この PC) */
      sub.push(el('span', { cls: 'hint', text: '動画を写しています' + (r.progress ? '(' + pct(r.progress) + ')' : '') }));
    } else if (r.state === 'sent' || r.state === 'making') {
      sub.push(el('span', { cls: 'hint', text: r.state === 'making' ? stepText(r.run) : '順番を待っています' }));
      acts.push(el('button', { type: 'button', cls: 'btn ghost small', title: 'この依頼を止めます(行は「失敗」になり、[もう一度送る] で続きから)', on: { click: function () {
        api('cancel', { id: r.id }).then(refresh, function (e) { fail('止められませんでした', e); });
      } } }, ['止める']));
    } else if (r.state === 'recording') {   /* この PC のライブ(F2-6): 録画中も、組になった物は決められる */
      sub.push(el('span', { cls: 'hint', text: liveText(r) }));
      if (r.live && r.live.errors) sub.push(el('span', { cls: 'fr-err', text: '作れなかった切り抜き ' + r.live.errors + ' 本' }));
      decideActs(r, acts, sub);
      if (livePhase(r) === 'recording') acts.push(el('button', { type: 'button', cls: 'btn ghost small', title: '録画を止めます(ここまでの切り抜きは作り終えて届きます)', on: { click: function () {
        api('cancel', { id: r.id }).then(function () { UIKit.toast('録画を止めました。ここまでの切り抜きを作り終えると届きます', { ms: 3000 }); refresh(); },
          function (e) { fail('録画を止められませんでした', e); });
      } } }, ['録画を止める']));
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
      decideActs(r, acts, sub);
    }
    var body = el('div', { cls: 'fr-row-body' }, [el('div', { cls: 'fr-row-head' }, head), el('div', { cls: 'fr-row-sub' }, sub)]);
    var row = el('div', { cls: 'fr-row', 'data-row': r.id }, [body, el('div', { cls: 'fr-row-acts' }, acts)]);
    if ((r.state === 'arrived' || r.state === 'recording') && r.groups.length && state.open[r.id]) {
      return el('div', { cls: 'fr-item open' }, [row, el('div', { cls: 'fr-detail' },
        [el('div', { cls: 'fr-detail-h' }, [helpLink('receive', '受け取り方の説明')])].concat(r.groups.map(function (g) { return packList(r, g); })))]);
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
  /* ---------------------------------------------------------------- 初回の準備(F2-5。9-1) */
  function setupView(s) {
    s = s || {};
    var miss = !!s.active && s.count > 0, run = !!s.running, res = s.result;
    state.partsWhy = !s.active ? '' : run ? '処理の部品を取っています。取り終えると送れます(進み具合は上の「初回の準備」)' :
      miss ? (s.later ? '処理の部品が足りません。上の帯の [取ってくる] から取ってください' : '処理の部品が足りません。上の「初回の準備」の [始める] から取ってください') : '';
    if (state.setupRun && !run && res) {
      if (res.ok) UIKit.toast('処理の部品を取り終わりました。送れるようになりました', { ms: 4000 });
    }
    state.setupRun = run;
    var card = !!s.active && (run || (miss && !s.later));
    $('setupCard').hidden = !card;
    $('setupBand').hidden = !(miss && s.later && !run);
    $('setupBandText').textContent = miss ? '部品が足りません(' + s.count + ' 個・約 ' + sizeText(s.total) + ')。取り終わるまで、この PC での処理はできません' : '';
    if (!card) return;
    var key = JSON.stringify(s.missing || []);
    if (key !== state.setupKey) {
      state.setupKey = key;
      $('setupItems').textContent = '';
      (s.missing || []).forEach(function (m) { $('setupItems').appendChild(el('li', {}, [m.label + '(' + sizeText(m.size) + ')'])); });
    }
    $('setupLead').textContent = run ? '部品を取っています。窓を閉じても続きます(取れた分は残り、止めても次は続きから)。' :
      '文字起こしなどに使う部品を取ってきます(' + s.count + ' 個・約 ' + sizeText(s.total) + ')。取り終わるまで、この PC での処理はできません。';
    $('setupWhere').textContent = (s.places || []).map(function (p) {
      return '置き場所: ' + p.path + '(空き ' + sizeText(p.free) + '・要る ' + sizeText(p.need) + ')';
    }).join('\n');
    var why = run ? '' : s.reason || (res && !res.ok ? (res.cancelled ? '止めました。取れた分は残っています(続きからやり直せます)' :
      '取れなかった物があります(' + res.failed.length + ' 個)。ネットワークを確かめて、やり直してください。' +
      res.failed.slice(0, 2).map(function (f) { return f.label + ': ' + f.message; }).join(' / ')) : '');
    $('setupWhy').hidden = !why;
    $('setupWhy').textContent = why;
    var p = s.progress;
    $('setupProgWrap').hidden = !run;
    if (run && p) {
      var frac = p.total ? Math.min(1, p.done / p.total) : 0;
      $('setupBar').firstElementChild.style.width = Math.round(frac * 100) + '%';
      $('setupBar').setAttribute('aria-valuenow', String(Math.round(frac * 100)));
      $('setupProg').textContent = p.index ? '取っています(' + p.index + ' / ' + p.count + ') ' + p.label + ' ・ ' + p.phase +
        (p.phase === '取っています' && p.itemTotal ? ' ' + sizeText(p.itemDone) + ' / ' + sizeText(p.itemTotal) : '') : p.phase;
    }
    $('btnSetupStart').hidden = run;
    $('btnSetupStart').disabled = !s.canStart;
    $('btnSetupStart').textContent = res && !res.ok ? 'やり直す' : '始める';
    $('btnSetupStart').title = s.canStart ? '部品を取り始めます' : (s.reason || '');
    $('btnSetupLater').hidden = run;
    $('btnSetupCancel').hidden = !run;
  }
  function setupAct(what) {
    return api('setup/' + what, {}).then(function (j) { setupView(j.setup); syncForm(); }, function (e) { fail('初回の準備', e); });
  }

  /* ---------------------------------------------------------------- ⚙ 設定(F2-5) */
  function fillSettings(s) {
    $('setSave').textContent = s.saveDir + (s.saveIsDefault ? '(既定)' : '');
    $('setCases').textContent = s.caseRoot + (s.caseIsDefault ? '(既定)' : '');
    $('btnResetSave').disabled = !!s.saveIsDefault;
    $('btnResetSave').title = s.saveIsDefault ? '今が既定の場所です' : '既定の場所(ビデオの 受け取ったパック)に戻します';
    $('btnResetCases').disabled = !!s.caseIsDefault;
    $('btnResetCases').title = s.caseIsDefault ? '今が既定の場所です' : '既定の場所(アプリのフォルダの 作業)に戻します';
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setEngine]'), function (r) { r.checked = r.value === s.engine; });
    $('setGpu').textContent = s.gpu ? 'この PC の GPU: ' + s.gpu.name + (s.gpu.vramGB ? '(' + s.gpu.vramGB + ' GB)' : '') : '';
    $('setKeyState').textContent = s.apiKey ? '入っています' : 'まだ入っていません';
    $('btnKeyClear').disabled = !s.apiKey;
    $('btnKeyClear').title = s.apiKey ? '保存してあるキーを消します' : 'キーが入っていません';
    $('setKeyHelp').textContent = s.apiKeyHelp || '';
    if (document.activeElement !== $('setDisk')) $('setDisk').value = s.diskMinGB == null ? '' : s.diskMinGB;
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setCut]'), function (r) { r.checked = r.value === s.cut; });
  }
  function loadSettings() {
    return api('settings').then(function (j) { fillSettings(j.settings); }, function (e) { fail('設定を読めませんでした', e); });
  }
  function putSettings(body) {
    return api('settings', body).then(function (j) {
      fillSettings(j.settings);
      if (j.message) UIKit.toast(j.message, { ms: 3500 });
      refresh();
    }, function (e) { fail('変えられませんでした', e); loadSettings(); });
  }
  function pickFolder(what) {
    var b = $(what === 'save' ? 'btnPickSave' : 'btnPickCases');
    b.disabled = true;
    api('pick-folder', { what: what }).then(function (j) {
      fillSettings(j.settings);
      if (j.chosen && j.message) UIKit.toast(j.message, { ms: 3500 });
    }, function (e) { fail('フォルダを変えられませんでした', e); }).then(function () { b.disabled = false; });
  }
  function saveKey(key) {
    var b = $('btnKeySave');
    b.disabled = true;
    $('setKeyState').textContent = key ? '確かめています…' : $('setKeyState').textContent;
    api('settings/key', { key: key }).then(function (j) {
      $('setKey').value = '';
      fillSettings(j.settings);
      UIKit.toast(j.message, { ms: 3500 });
    }, function (e) { fail('API キー', e); loadSettings(); }).then(function () { b.disabled = false; });
  }
  function openSettings() {
    UIKit.drawer.open($('settingsDrawer'), { opener: $('btnSettings') });
    loadSettings();
  }

  /* ---------------------------------------------------------------- [送る] / [受け取る](F3。C-2-1)と配信の一覧(F3-2) */
  var view = 'send', listTimer = 0, undecided = 0;
  function show(v) {
    view = v === 'receive' ? 'receive' : 'send';
    $('viewSend').hidden = view !== 'send';
    $('viewReceive').hidden = view !== 'receive';
    $('tabSend').setAttribute('aria-pressed', view === 'send' ? 'true' : 'false');
    $('tabReceive').setAttribute('aria-pressed', view === 'receive' ? 'true' : 'false');
    if (location.hash !== '#' + view) history.replaceState(null, '', '#' + view);
    if (view === 'send') pollList();
  }
  function pollList() {   /* 一覧は送る画面を出している間だけ問い合わせる(玄関の中の写しを読むだけ = 軽い) */
    clearTimeout(listTimer);
    if (view !== 'send') return;
    FRList.load().catch(function () { /* 玄関とつながらない = 上の帯が知らせる */ }).then(function () {
      listTimer = setTimeout(pollList, UIKit.life.isAway() ? POLL_AWAY : POLL);
    });
  }
  function setCount(n) {   /* ●n = まだ決めていない本数(C-3-9)。窓のタイトルにも(窓はタイトルを写す = F3-A) */
    undecided = n;
    $('tabN').hidden = !n;
    $('tabN').textContent = n ? String(n) : '';
    $('tabReceive').setAttribute('aria-label', n ? '受け取る(まだ決めていない ' + n + ' 本)' : '受け取る');
    document.title = n ? '切り抜き(' + n + ')' : '切り抜き';
  }
  function pickStream(it) {   /* カードを押した = URL の欄に入れて、貼ったときと同じに調べる(送る欄の作り直しは F3-3) */
    clearFile();
    $('url').value = it.url;
    onUrl();
  }
  window.FriendApp = { show: show, count: function () { return undecided; } };   /* 窓(F3-A)から呼ぶ口(仮) */

  function refresh() {
    clearTimeout(timer);
    return api('inbox').then(function (j) {
      $('errbar').hidden = true;
      if (!state.form) { state.form = j.form; fillForm(j.form); syncForm(); }
      var key = JSON.stringify(j.rows || []);
      $('btnSaved').title = '受け取ったパックの保存先を開きます: ' + (j.saveDir || '');
      setupView(j.setup);
      banner(j);
      if (key === state.key) return;   /* 変わっていなければ描き直さない(押そうとしているボタン・フォーカスを消さない) */
      state.key = key;
      state.rows = j.rows || [];
      setCount(state.rows.reduce(function (a, r) { return a + (r.undecided || 0); }, 0));
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
    $('btnPick').addEventListener('click', pickFile);
    $('btnFileClear').addEventListener('click', clearFile);
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
    $('btnSetupStart').addEventListener('click', function () { setupAct('start'); });
    $('btnSetupLater').addEventListener('click', function () { setupAct('later'); });
    $('btnSetupCancel').addEventListener('click', function () { setupAct('cancel'); });
    $('btnSetupOpen').addEventListener('click', function () { setupAct('open'); });
    $('btnSettings').addEventListener('click', openSettings);
    $('settingsClose').addEventListener('click', function () { UIKit.drawer.close($('settingsDrawer')); });
    $('btnPickSave').addEventListener('click', function () { pickFolder('save'); });
    $('btnPickCases').addEventListener('click', function () { pickFolder('cases'); });
    $('btnResetSave').addEventListener('click', function () { putSettings({ reset: 'save' }); });
    $('btnResetCases').addEventListener('click', function () { putSettings({ reset: 'cases' }); });
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setEngine]'), function (r) {
      r.addEventListener('change', function () { if (r.checked) putSettings({ engine: r.value }); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('input[name=setCut]'), function (r) {
      r.addEventListener('change', function () { if (r.checked) putSettings({ cut: r.value }); });
    });
    $('setDisk').addEventListener('change', function () {
      var v = parseFloat($('setDisk').value);
      if (isNaN(v)) { UIKit.toast('空き容量の下限は数(GB)で入れてください', { kind: 'err' }); loadSettings(); return; }
      putSettings({ diskMinGB: v });
    });
    $('btnKeySave').addEventListener('click', function () {
      var k = $('setKey').value.trim();
      if (!k) { UIKit.toast('キーを貼ってから押してください', { kind: 'err' }); return; }
      saveKey(k);
    });
    $('setKey').addEventListener('keydown', function (e) { if (e.key === 'Enter' && $('setKey').value.trim()) saveKey($('setKey').value.trim()); });
    $('btnKeyClear').addEventListener('click', function () { saveKey(''); });
    $('cleanedOk').addEventListener('click', function () { api('notice-seen', {}).then(function () { $('cleaned').hidden = true; }); });
    $('tabSend').addEventListener('click', function () { show('send'); });
    $('tabReceive').addEventListener('click', function () { show('receive'); });
    window.addEventListener('hashchange', function () { show(location.hash.slice(1)); });
    FRList.onPick = pickStream;
    UIKit.life.onReturn(function () { refresh(); pollList(); });
    show(location.hash.slice(1));
    refresh();
  });
})();
