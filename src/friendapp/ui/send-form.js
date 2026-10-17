/* 送る欄(F3-3。notes:plan/f1-friend-requirements.md の C-2-6〜C-2-13・C-2-17〜C-2-19)。口 = POST api/friend/send(friendapp/api.py の説明)。
   形は 3 つ: 何も選んでいない(URL の欄と動画ファイルの受け皿)/ 配信(一覧のカードか URL。アーカイブ・終わったばかり = 区間と本数・ライブ中・予定 = 録画を頼む)/
   動画ファイル(複数・落とす・選ぶ)。区間・本数・映像トラック・配信者は別の配信に替えても残す(アプリを閉じるまで)。Esc で閉じる(入れかけも消える)。
   外から来た文字(題・名前)は textContent でだけ入れる */
(function () {
  'use strict';
  var $, el, api;
  var RANGES_MAX = 5, TOP_MAX = 20, FILES_MAX = 20;
  var STATE_PILL = { live: ['err', 'ライブ中'], upcoming: ['info', '予定'], justEnded: ['wait', '終わったばかり'], checking: ['wait', '確かめ中'] };
  var f = { mode: 'none', stream: null, peekSeq: 0, checking: false, top: 5, people: [], streamer: { name: '', hex: null, auto: true }, files: [],
    sending: false, inited: false };

  /* ---------------------------------------------------------------- 文字 */
  function hmsText(sec) {
    if (sec == null) return '';
    sec = Math.round(sec);
    var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return (h ? h + '時間' : '') + (h || m ? m + '分' : '') + (s < 10 && (h || m) ? '0' : '') + s + '秒';
  }
  function vidOf(text) {   /* 貼った文字から YouTube の動画の id(無ければ '') */
    var m = /(?:[?&]v=|youtu\.be\/|\/live\/|\/shorts\/)([A-Za-z0-9_-]{11})/.exec(String(text || ''));
    return m ? m[1] : '';
  }

  /* ---------------------------------------------------------------- 配信者の札(C-2-9) */
  var nameList = null;
  function names() {   /* 名簿(期・グループの順)を datalist に 1 回だけ */
    if (nameList) return nameList;
    nameList = UIKit.http('api/ytt/streamer-colors', { body: { q: '', all: true } }).then(function (j) {
      var dl = el('datalist', { id: 'frNames' });
      (j.items || []).forEach(function (e) { dl.appendChild(el('option', { value: e.name })); });
      document.body.appendChild(dl);
      return j.items || [];
    }, function () { nameList = null; return []; });
    return nameList;
  }
  /* 打った名前 -> {name, hex, auto: false}(名簿に合えば名簿の名前と色・合わなければ打ったまま = 色なし) */
  function resolveName(name) {
    if (!name) return Promise.resolve({ name: '', hex: null, auto: false });
    return UIKit.http('api/ytt/streamer-colors', { body: { q: name } }).then(function (j) {
      return j.match ? { name: j.match.name, hex: j.match.hex, auto: false } : { name: name, hex: null, auto: false };
    }, function () { return { name: name, hex: null, auto: false }; });
  }
  function chip(who, onSet, onRemove) {
    var wrap = el('span', { cls: 'fr-chip' });
    function draw() {
      wrap.textContent = '';
      var b = el('button', { type: 'button', cls: 'fr-chip-btn', title: '押すと名前を変えられます(名簿から選ぶか、打って Enter)' });
      var dot = el('span', { cls: 'fr-dot' + (who.hex ? '' : ' none'), 'aria-hidden': 'true' });
      if (who.hex) dot.style.background = who.hex;
      b.appendChild(dot);
      b.appendChild(document.createTextNode(who.name || '配信者を選ぶ'));
      b.addEventListener('click', edit);
      wrap.appendChild(b);
      if (who.name && !who.hex) wrap.appendChild(el('span', { cls: 'hint fr-nocolor', text: '色なし' }));
      if (onRemove) wrap.appendChild(el('button', { type: 'button', cls: 'btn ghost icon small fr-chip-x', 'aria-label': (who.name || '人') + ' を外す', title: '外す',
        on: { click: onRemove } }, ['×']));
    }
    function edit() {
      wrap.textContent = '';
      var i = el('input', { type: 'text', cls: 'fr-chip-in', 'aria-label': '配信者の名前', placeholder: '名前を打つと絞り込み', autocomplete: 'off', list: 'frNames' });
      i.value = who.name || '';
      var done = false;
      function commit() {
        if (done) return;
        done = true;
        resolveName(i.value.trim()).then(onSet);
      }
      i.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done = true; draw(); }
      });
      i.addEventListener('blur', commit);
      wrap.appendChild(i);
      names();
      i.focus();
      i.select();
    }
    draw();
    return wrap;
  }
  function drawWho() {
    var box = $('headWho');
    box.textContent = '';
    box.appendChild(chip(f.streamer, function (w) { f.streamer = w; drawWho(); }));
    f.people.forEach(function (p, i) {
      box.appendChild(chip(p, function (w) { f.people[i] = w; if (!w.name) f.people.splice(i, 1); drawWho(); }, function () { f.people.splice(i, 1); drawWho(); }));
    });
    if (f.people.length < 5) box.appendChild(el('button', { type: 'button', cls: 'btn ghost small fr-add-person', title: 'コラボの相手を足します(字幕の色に使います)',
      on: { click: function () { f.people.push({ name: '', hex: null }); drawWho(); var c = box.querySelectorAll('.fr-chip-btn'); if (c.length) c[c.length - 1].click(); } } }, ['+ 人']));
  }

  /* ---------------------------------------------------------------- 区間(C-2-7) */
  function rangeRows() { return Array.prototype.slice.call($('ranges').querySelectorAll('.fr-range')); }
  function boxes(row) { return row.querySelectorAll('.ui-time'); }
  function addRange(focus) {
    if (rangeRows().length >= RANGES_MAX) return null;
    var row = el('div', { cls: 'fr-range' });
    var a = UIKit.timebox.create({ youtube: true, wheel: true, label: '始まり' });
    var b = UIKit.timebox.create({ youtube: true, wheel: true, label: '終わり' });
    var x = el('button', { type: 'button', cls: 'btn ghost icon small', 'aria-label': 'この区間を外す', title: '外す', on: { click: function () {
      if (rangeRows().length > 1) row.remove(); else { UIKit.timebox.set(a, null); UIKit.timebox.set(b, null); }
      sync();
    } } }, ['×']);
    var last = a;
    function step(sec) { return el('button', { type: 'button', cls: 'btn ghost small fr-step', title: '選んでいる時刻を ' + (sec > 0 ? '+' : '') + sec + ' 秒',
      on: { click: function () { UIKit.timebox.add(last, sec); } } }, [(sec > 0 ? '+' : '−') + Math.abs(sec)]); }
    function len(sec, label) { return el('button', { type: 'button', cls: 'btn ghost small fr-step', title: '始まりから ' + label + '(押すたび足す)',
      on: { click: function () {
        var s = UIKit.timebox.get(a), e = UIKit.timebox.get(b);
        if (s == null) return;
        UIKit.timebox.set(b, e != null && e > s && row.getAttribute('data-len') === 'on' ? e + sec : s + sec);
        row.setAttribute('data-len', 'on');
        sync();
      } } }, ['+' + label]); }
    var said = el('div', { cls: 'fr-range-said', 'aria-live': 'polite' });
    row.appendChild(el('div', { cls: 'fr-range-times' }, [a, el('span', { cls: 'fr-tilde', text: '〜' }), b, x]));
    row.appendChild(el('div', { cls: 'fr-range-steps' }, [step(-5), step(-1), step(1), step(5), el('span', { cls: 'hint fr-from', text: '始まりから' }),
      len(30, '30秒'), len(60, '1分'), len(180, '3分')]));
    row.appendChild(said);
    [a, b].forEach(function (t) {
      t.addEventListener('focus', function () { last = t; });
      t.addEventListener('ui-time', function () { if (t === b) row.removeAttribute('data-len'); sync(); });
      t.addEventListener('ui-time-commit', function (e) {
        sync();
        if (e.detail.via !== 'enter') return;
        if (t === a) b.focus();   /* Enter で次の欄へ */
        else { var rs = rangeRows(), i = rs.indexOf(row); var n = rs[i + 1] || addRange(false); if (n) boxes(n)[0].focus(); else $('btnSend').focus(); }
      });
      t.addEventListener('ui-time-beforepaste', function (e) {   /* 別の配信の時刻つき URL = 時刻は入れずに知らせる */
        var v = vidOf(e.detail.text);
        if (v && f.stream && v !== f.stream.videoId) { e.preventDefault(); otherVideo(row, v, e.detail.text); }
      });
      t.addEventListener('ui-time-reject', function (e) { said.textContent = e.detail.reason; said.className = 'fr-range-said fr-bad'; });
    });
    $('ranges').appendChild(row);
    if (focus) a.focus();
    sync();
    return row;
  }
  function otherVideo(row, vid, text) {
    var said = row.querySelector('.fr-range-said');
    said.textContent = '';
    said.className = 'fr-range-said fr-bad';
    said.appendChild(document.createTextNode('選んでいる配信と違う配信の URL です '));
    said.appendChild(el('button', { type: 'button', cls: 'btn small', on: { click: function () { openUrl(text); } } }, ['その配信に切り替える']));
  }
  /* 区間を読む -> {list, bad, any}。行ごとに読み取った結果か誤りを出す */
  function readRanges() {
    var out = [], bad = '', durSec = f.stream && f.stream.duration;
    rangeRows().forEach(function (row) {
      var t = boxes(row), s = UIKit.timebox.get(t[0]), e = UIKit.timebox.get(t[1]), said = row.querySelector('.fr-range-said'), msg = '', err = false;
      if (said.querySelector('button')) return;   /* 別の配信の知らせを出している間は触らない */
      if (s != null || e != null) {
        if (s == null || e == null) { msg = '始まりと終わりの両方を入れてください'; err = true; }
        else if (e <= s) { msg = '終わりは始まりより後にしてください'; err = true; }
        else if (durSec && e > durSec + 1) { msg = '配信の長さ(' + hmsText(durSec) + ')を超えています'; err = true; }
        else msg = hmsText(s) + ' 〜 ' + hmsText(e) + '(' + hmsText(e - s) + ')';
      }
      row.classList.toggle('bad', err);
      said.textContent = msg;
      said.className = 'fr-range-said' + (err ? ' fr-bad' : ' hint');
      if (err && !bad) bad = msg;
      if (!err && s != null && e != null) out.push([s, e]);
    });
    return { list: out, bad: bad };
  }

  /* ---------------------------------------------------------------- 形の切り替え */
  function kind() {
    if (f.mode === 'files') return 'files';
    var s = f.stream && f.stream.state;
    return s === 'live' || s === 'upcoming' ? 'live' : s === 'justEnded' ? 'wait' : 'url';
  }
  function liveRow() {   /* この配信を録画している行(送った物の中) */
    var rows = ((FR.state.inbox || {}).rows) || [];
    return f.stream ? rows.filter(function (r) { return r.state === 'recording' && r.kind === 'live' && (r.source || {}).videoId === f.stream.videoId && !r.cancelled; })[0] : null;
  }
  function sync() {
    if (!f.inited) return;
    var k = kind(), pcUser = ((FR.state.form || {}).pc) === 'user';
    $('formEmpty').hidden = f.mode !== 'none';
    $('formStream').hidden = f.mode !== 'stream';
    $('formFiles').hidden = f.mode !== 'files';
    $('sendRow').hidden = f.mode === 'none';
    FR.$('sent').classList.toggle('slim', f.mode !== 'none');
    if (f.mode === 'none') return;
    var why = '', label = '送る';
    if (f.mode === 'stream') {
      var s = f.stream;
      $('archiveBox').hidden = k === 'live';
      $('liveBox').hidden = k !== 'live';
      $('waitNote').hidden = k !== 'wait';
      var rg = k === 'live' ? { list: [], bad: '' } : readRanges();
      $('topLine').hidden = rg.list.length > 0 || rangeRows().some(function (r) { return UIKit.timebox.get(boxes(r)[0]) != null; });
      $('btnRange').hidden = rangeRows().length >= RANGES_MAX;
      $('topVal').textContent = String(f.top);
      $('topMinus').disabled = f.top <= 1; $('topPlus').disabled = f.top >= TOP_MAX;
      var rec = k === 'live' ? liveRow() : null;
      f.rec = rec;
      $('liveNow').hidden = !rec;
      if (rec && f.recId !== rec.id) {   /* 録画中の配信を開いた = 今の設定を出す(途中で変えられる = C-2-11) */
        f.recId = rec.id;
        fillLive(Object.assign({}, (FR.state.form || {}).live || {}, (rec.form || {}).live || {}));
      } else if (!rec && f.recId) { f.recId = ''; fillLive((FR.state.form || {}).live || {}); }
      $('liveLead').textContent = rec ? '録画しています(届いた ' + rec.packs.length + ' 本)。設定を変えると、この先の切り抜きから効きます。' :
        '配信が終わるまで録画し、面白い所を自動で切ります。できた分から「受け取る」に届きます。';
      label = rec ? '録画を取り消す' : k === 'live' ? (s.state === 'upcoming' ? '予約する' : '録画を頼む') : pcUser ? '依頼する' : '送る';
      if (f.checking) why = '配信を確かめています…';
      else if (s.blocked) why = s.blocked;
      else if (rg.bad) why = rg.bad;
    } else {
      var up = f.files.some(function (x) { return !x.id; });
      label = pcUser ? '依頼する' : '送る';
      if (!f.files.length) why = '動画ファイルを選んでください';
      else if (up) why = '動画を読み込んでいます…';
    }
    var parts = !pcUser && FR.state.partsWhy;
    if (!why && parts) why = parts;
    $('btnSend').textContent = (f.mode === 'files' && f.files.length > 1 ? f.files.length + ' 本を' : '') + label;
    $('btnSend').classList.toggle('primary', !f.rec);
    $('btnSend').classList.toggle('danger', !!f.rec);
    $('btnSend').disabled = !!why || f.sending;
    $('btnSend').title = why;
    $('sendWhy').hidden = !why || why === '配信を確かめています…';
    $('sendWhy').textContent = why;
    $('pcNote').hidden = !pcUser;
  }
  function fillLive(lv) {
    $('lvPerHour').value = lv.perHour;
    $('lvLength').value = lv.length;
    Array.prototype.forEach.call(document.querySelectorAll('input[name=lvLenMode]'), function (r) { r.checked = r.value === (lv.lengthMode || 'auto'); });
    lenBox((lv.lengthMode || 'auto') === 'fixed');
    $('lvAfter').checked = !!lv.afterStream;
  }
  function lenBox(on) {
    $('lvLength').disabled = !on;
    $('lvLength').title = on ? '1 本の長さ(10〜180 秒)' : '「固定」を選ぶと入れられます';
  }
  function head(s) {
    $('headThumb').src = s.thumb || (s.videoId ? 'https://i.ytimg.com/vi/' + s.videoId + '/mqdefault.jpg' : '');
    $('headThumb').hidden = !s.videoId && !s.thumb;
    $('headTitle').textContent = s.title || '(題を確かめています)';
    $('headTitle').title = s.title || '';
    $('headLen').textContent = s.duration ? FR.dur(s.duration) : '';
    var p = STATE_PILL[s.state];
    $('headState').hidden = !p;
    if (p) { $('headState').className = 'pill ' + p[0]; $('headState').textContent = p[1]; }
    $('streamWhy').hidden = !s.blocked;
    $('streamWhy').textContent = s.blocked || '';
  }

  /* ---------------------------------------------------------------- 配信を開く(カード・URL・Ctrl+V) */
  function setAutoStreamer(name, hex) {
    if (f.streamer.auto || !f.streamer.name) { f.streamer = { name: name || '', hex: hex || null, auto: true }; drawWho(); }
  }
  function openStream(it) {
    f.mode = 'stream';
    f.stream = { videoId: it.videoId, url: it.url, title: it.title, thumb: it.thumb, state: it.state, duration: it.duration, startAt: it.startAt, blocked: '' };
    f.files = [];
    head(f.stream);
    setAutoStreamer(it.streamer, it.hex);
    FRList.select(it.videoId);
    if (!rangeRows().length) addRange(false);
    if (it.state === 'checking') probe(it.url, ++f.peekSeq, false);
    sync();
    reveal();
  }
  function reveal() {   /* 送る欄を見える所へ: 2 列 = 右の列を上へ・1 列(狭い)= 欄までスクロール(欄は一覧の上) */
    var side = document.querySelector('.fr-side');
    if (side) side.scrollTop = 0;
    if (window.innerWidth <= 960) $('sendForm').scrollIntoView({ block: 'start' });
    else if (window.scrollY > 0) window.scrollTo(0, 0);   /* 2 列 = 右の列は画面の上に貼り付く。画面ごと下がっていると欄の頭が隠れる */
  }
  function openUrl(text) {
    var vid = vidOf(text);
    if (!vid) { $('urlWhy').hidden = false; $('urlWhy').textContent = 'YouTube の配信の URL を貼ってください'; return; }
    $('urlWhy').hidden = true;
    var hit = FRList.item(vid);
    if (hit) { openStream(hit); return; }   /* 一覧にある配信 = そのカードを選んだ状態に(C-2-17) */
    var url = 'https://www.youtube.com/watch?v=' + vid;
    openStream({ videoId: vid, url: url, title: '', thumb: '', state: 'checking', duration: null });
    var my = f.peekSeq;
    api('peek?url=' + encodeURIComponent(url)).then(function (p) {
      if (my !== f.peekSeq) return;
      f.stream.title = p.title || '(題が取れませんでした)';
      head(f.stream);
      setAutoStreamer(p.streamer, p.hex);
      sync();
    }, function (e) { if (my === f.peekSeq) { f.stream.blocked = e.message; head(f.stream); sync(); } });
  }
  function probe(url, my, quiet) {   /* 配信中・予定・終わったばかり・メンバー限定か(yt-dlp で数秒) */
    f.checking = true; sync();
    api('peek-live?url=' + encodeURIComponent(url)).then(function (lv) {
      if (my !== f.peekSeq) return;
      var s = f.stream;
      s.state = lv.status === 'is_live' ? 'live' : lv.status === 'is_upcoming' ? 'upcoming' : lv.status === 'post_live' ? 'justEnded' : 'ended';
      if (lv.status === 'members') s.blocked = 'メンバー限定の配信は切り抜けません';
      head(s);
    }, function () { if (my === f.peekSeq && !quiet) { f.stream.state = 'ended'; head(f.stream); } }).then(function () {
      if (my !== f.peekSeq) return;
      f.checking = false; sync();
    });
  }
  function close() {   /* Esc・×: 送る欄を閉じる(入れかけも消える = C-2-18) */
    f.peekSeq++;
    f.mode = 'none'; f.stream = null; f.files = []; f.checking = false; f.people = []; f.rec = null; f.recId = '';
    f.streamer = { name: '', hex: null, auto: true };
    $('ranges').textContent = '';
    $('url').value = '';
    $('urlWhy').hidden = true;
    FRList.select('');
    drawFiles();
    sync();
  }
  /* 一覧のカードの状態が変わった(ライブが終わった・アーカイブが出た)= 開いている欄の中身を切り替える(入れかけは残す = C-2-12) */
  function follow() {
    if (f.mode !== 'stream' || !f.stream) return;
    var it = FRList.item(f.stream.videoId);
    if (!it || it.state === 'checking') return;
    if (it.state !== f.stream.state || it.duration !== f.stream.duration || (it.title && it.title !== f.stream.title)) {
      f.stream.state = it.state; f.stream.duration = it.duration; f.stream.title = it.title || f.stream.title;
      head(f.stream);
      sync();
    }
  }

  /* ---------------------------------------------------------------- 動画ファイル(C-2-13) */
  function drawFiles() {
    var ul = $('fileList');
    ul.textContent = '';
    f.files.forEach(function (x, i) {
      var who = chip(x.who, function (w) { x.who = w; drawFiles(); });
      var li = el('li', { cls: 'fr-file-row' }, [
        el('span', { cls: 'fr-file-name', text: x.name, title: x.name }),
        el('span', { cls: 'hint', text: x.id ? FR.sizeText(x.size) : '読み込んでいます ' + (x.pct || 0) + '%' }),
        who,
        el('button', { type: 'button', cls: 'btn ghost icon small', 'aria-label': x.name + ' を外す', title: '外す', on: { click: function () {
          if (x.xhr) x.xhr.abort();
          f.files.splice(i, 1);
          if (!f.files.length) close(); else { drawFiles(); sync(); }
        } } }, ['×'])]);
      ul.appendChild(li);
    });
    $('filesTitle').textContent = f.files.length ? '動画ファイル(' + f.files.length + ' 本)' : '動画ファイル';
  }
  function addFile(got) {   /* {id, name, size, streamer, hex} */
    if (got.id && f.files.some(function (y) { return y.id === got.id; })) return null;   /* 同じ物は足さない(玄関が同じパスに同じ id を返す) */
    if (f.files.length >= FILES_MAX) { UIKit.toast('動画ファイルは 1 回に ' + FILES_MAX + ' 本までです', { kind: 'err' }); return null; }
    if (f.mode !== 'files') { close(); f.mode = 'files'; setTimeout(reveal, 0); }
    var x = { id: got.id || '', name: got.name, size: got.size, who: { name: got.streamer || '', hex: got.hex || null, auto: true }, pct: 0 };
    f.files.push(x);
    drawFiles();
    sync();
    return x;
  }
  function pickFile() {
    $('btnPick').disabled = $('btnPickMore').disabled = true;
    api('pick-file', {}).then(function (j) { if (j.file) addFile(j.file); }, function (e) { FR.fail('ファイルを選べませんでした', e); })
      .then(function () { $('btnPick').disabled = $('btnPickMore').disabled = false; });
  }
  function upload(file) {   /* 落とした動画を玄関へ(ブラウザはパスを渡せないので中身を送る。進み具合つき) */
    if (!/\.(mp4|mkv|mov|webm|m4v|avi|ts|flv|wmv)$/i.test(file.name)) {
      UIKit.toast(file.name + ' は動画ではないので外しました', { kind: 'err', ms: 5000 });
      return;
    }
    if (f.files.some(function (y) { return y.name === file.name && y.size === file.size; })) return;   /* 同じ名前・大きさは足さない */
    var x = addFile({ name: file.name, size: file.size });
    if (!x) return;
    var xhr = new XMLHttpRequest();
    x.xhr = xhr;
    xhr.open('PUT', 'api/friend/upload?name=' + encodeURIComponent(file.name));
    xhr.setRequestHeader('X-YTT-Token', FR.token());
    xhr.upload.onprogress = function (e) { if (e.lengthComputable) { x.pct = Math.floor(e.loaded * 100 / e.total); drawFiles(); } };
    xhr.onload = function () {
      x.xhr = null;
      var j = null;
      try { j = JSON.parse(xhr.responseText); } catch (e) { j = null; }
      if (xhr.status === 200 && j && j.file) {
        x.id = j.file.id; x.size = j.file.size;
        if (x.who.auto && j.file.streamer) x.who = { name: j.file.streamer, hex: j.file.hex, auto: true };
      } else {
        UIKit.toast(file.name + ': ' + ((j && j.message) || '受け取れませんでした'), { kind: 'err', ms: 6000 });
        f.files.splice(f.files.indexOf(x), 1);
      }
      if (!f.files.length) close(); else { drawFiles(); sync(); }
    };
    xhr.onerror = function () { x.xhr = null; f.files.splice(f.files.indexOf(x), 1); UIKit.toast(file.name + ' を読み込めませんでした', { kind: 'err' }); drawFiles(); sync(); };
    xhr.send(file);
  }
  function dropTarget(zone) {
    zone.addEventListener('dragover', function (e) { if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0) { e.preventDefault(); zone.classList.add('on'); } });
    zone.addEventListener('dragleave', function () { zone.classList.remove('on'); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      e.stopPropagation();   /* 落とす所は入れ子(送る欄の中に落とす所)。外側にも届くと同じ物が 2 回入る */
      zone.classList.remove('on');
      var files = (e.dataTransfer && e.dataTransfer.files) || [];
      if (!files.length) return;
      if (window.FriendHost && FriendHost.isApp) {   /* exe の窓 = exe が本物のパスを読んで玄関へ(F3-1。写すのは送るとき) */
        FriendHost.sendFiles(files, function (err, j) {
          ((j && j.skipped) || []).forEach(function (x) { UIKit.toast(x.name + ': ' + x.message, { kind: 'err', ms: 6000 }); });
          if (err && !(j && j.files && j.files.length)) { UIKit.toast(err.message, { kind: 'err', ms: 6000 }); return; }
          ((j && j.files) || []).forEach(addFile);
        });
        return;
      }
      Array.prototype.forEach.call(files, upload);   /* 窓の外(Edge・開発の PC)= 中身を玄関へ送る */
    });
  }

  /* ---------------------------------------------------------------- 送る */
  function liveBody() {
    var mode = (document.querySelector('input[name=lvLenMode]:checked') || {}).value || 'auto';
    return { perHour: parseInt($('lvPerHour').value, 10) || 6, lengthMode: mode, length: parseInt($('lvLength').value, 10) || 45, afterStream: $('lvAfter').checked };
  }
  function liveChanged() {   /* 録画中の配信の設定を途中で変える(この先の切り抜きから効く) */
    if (!f.rec) return;
    api('live-settings', Object.assign({ id: f.rec.id }, liveBody())).then(function () {
      UIKit.toast('録画の設定を変えました(この先の切り抜きから効きます)', { ms: 4000 });
      FR.refresh();
    }, function (e) { FR.fail('設定を変えられませんでした', e); });
  }
  function cancelRec() {
    var rec = f.rec;
    UIKit.dialog.confirm({ title: '録画を取り消します', body: '録画と、この先の切り抜きを止めます。届いた物は「受け取る」に残り、作りかけは捨てます。',
      ok: '取り消す', cancel: '続ける', danger: true }).then(function (yes) {
      if (!yes) return;
      api('cancel', { id: rec.id }).then(function () { close(); FR.refresh(); }, function (e) { FR.fail('取り消せませんでした', e); });
    });
  }
  function send() {
    if ($('btnSend').disabled) return;
    if (f.mode === 'stream' && f.rec) { cancelRec(); return; }
    var body;
    if (f.mode === 'files') {
      body = { source: 'files', videoTracks: parseInt($('tracksF').value, 10) || 1,
        files: f.files.map(function (x) { return { fileId: x.id, streamer: x.who.name || '' }; }) };
    } else {
      var k = kind(), rg = k === 'live' ? { list: [] } : readRanges();
      body = { source: 'url', kind: k, url: f.stream.url, title: f.stream.title, ranges: rg.list, top: rg.list.length ? null : f.top,
        streamer: f.streamer.name || '', people: f.people.map(function (p) { return p.name; }).filter(Boolean),
        videoTracks: parseInt($('tracks').value, 10) || 1, startAt: f.stream.startAt || null };
      if (k === 'live') body.live = liveBody();
    }
    f.sending = true; sync();
    api('send', body).then(function (j) {
      (j.skipped || []).forEach(function (s) { UIKit.toast(s.message, { kind: 'err', ms: 6000 }); });
      close();
      FR.refresh();
    }, function (e) { FR.fail(f.mode === 'stream' && kind() === 'live' ? '録画を頼めませんでした' : '送れませんでした', e); })
      .then(function () { f.sending = false; sync(); });
  }

  function fillForm(form) {   /* 前回の値(C-2-8・C-2-10・C-2-11) */
    f.top = form.top || 5;
    $('tracks').value = $('tracksF').value = String(form.videoTracks || 1);
    fillLive(form.live);
  }

  document.addEventListener('DOMContentLoaded', function () {
    $ = FR.$; el = FR.el; api = FR.api;
    FRList.onPick = openStream;
    $('url').addEventListener('keydown', function (e) { if (e.key === 'Enter') openUrl($('url').value); });
    $('url').addEventListener('paste', function (e) {
      var t = (e.clipboardData || window.clipboardData).getData('text');
      if (vidOf(t)) { e.preventDefault(); $('url').value = t; openUrl(t); }
    });
    $('url').addEventListener('change', function () { if ($('url').value.trim()) openUrl($('url').value); });
    $('btnFormClose').addEventListener('click', close);
    $('btnFilesClose').addEventListener('click', close);
    $('btnRange').addEventListener('click', function () { addRange(true); });
    $('topMinus').addEventListener('click', function () { f.top = Math.max(1, f.top - 1); sync(); });
    $('topPlus').addEventListener('click', function () { f.top = Math.min(TOP_MAX, f.top + 1); sync(); });
    Array.prototype.forEach.call(document.querySelectorAll('input[name=lvLenMode]'), function (r) {
      r.addEventListener('change', function () { lenBox(r.value === 'fixed' && r.checked); liveChanged(); });
    });
    ['lvPerHour', 'lvLength', 'lvAfter'].forEach(function (id) { $(id).addEventListener('change', liveChanged); });
    $('btnSend').addEventListener('click', send);
    $('btnPick').addEventListener('click', pickFile);
    $('btnPickMore').addEventListener('click', pickFile);
    dropTarget($('dropZone'));
    dropTarget($('dropMore'));
    dropTarget($('sendForm'));
    /* どこでも Ctrl+V で URL を貼ればその配信を開く(文字を入れる場所では使わない = C-2-17) */
    document.addEventListener('paste', function (e) {
      if (FR.view !== 'send' || FR.typing(e.target)) return;
      var t = (e.clipboardData || window.clipboardData).getData('text');
      if (vidOf(t)) { e.preventDefault(); openUrl(t); }
    });
    document.addEventListener('keydown', function (e) {   /* Esc で送る欄を閉じる(⚙ や確認の窓が開いているときはそちら) */
      if (e.key !== 'Escape' || FR.view !== 'send' || f.mode === 'none' || document.querySelector('dialog[open]') || FR.drawerOpen()) return;
      if (e.target && e.target.classList && e.target.classList.contains('fr-chip-in')) return;
      close();
    });
    FR.on(function (what, d) {
      if (what === 'data') {
        if (!f.inited) { f.inited = true; fillForm(d.inbox.form); drawWho(); }
        follow();
        sync();
      } else if (what === 'prefs' || what === 'parts') sync();
    });
  });
  window.FRForm = { open: openStream, openUrl: openUrl, close: close, get mode() { return f.mode; } };
})();
