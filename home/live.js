/* リアルタイム切り抜き(試験中)の画面(線 D の P1・P2。home/live.py・home/live_export.py・recorder/)。
   P2: 再生しながら I(開始)・O(終了)・N(直前の秒数)でマーク → 入口の api/marks に保存(押すたびに fsync)→ 書き出し(api/export。録画待ち → 取得 → 30fps → 検証 → 文字起こしへ)。
   マークの時刻は hls.js の playingDate(録画元の受信時刻 = 絶対時刻)。
   録画元への要求はすべて入口の中継 r/<録画元>/<残り>(同じオリジン。合言葉は入口が付ける)。書き込み(POST)は入口の合言葉 X-YTT-Token。
   再生は hls.js(home/vendor/hls.min.js を同梱。CSP script-src 'self' のまま)。Web Worker は使わない(CSP に worker-src を足さないため) */
(function () {
  'use strict';
  var TOKEN = (document.querySelector('meta[name="ytt-token"]') || {}).content || '';
  var STATE_TEXT = { waiting: '配信を待っています', recording: '録画中', reconnecting: 'つなぎ直し中', stopped: '停止', ended: '終了', error: 'エラー' };
  var STATE_PILL = { waiting: 'wait', recording: 'run', reconnecting: 'warn', stopped: 'ok', ended: 'ok', error: 'err' };
  var GB = 1024 * 1024 * 1024;
  var info = null, rid = null, listData = null, pollTimer = null, busy = false;
  var hls = null, playing = null, clockTimer = null;
  var JOB_PILL = { wait: 'wait', fetch: 'run', encode: 'run', done: 'ok', error: 'err', cancelled: 'warn' };
  var QUICK_SEC = 30;
  var markData = null, markBusy = false, markSeq = 0;

  function $(s) { return document.querySelector(s); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function lsGet(k) { try { return localStorage.getItem('ytt-live-' + k); } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem('ytt-live-' + k, v); } catch (e) { /* 覚えられなくても動く */ } }
  function toast(msg, kind) { if (window.UIKit && UIKit.toast) UIKit.toast(msg, kind ? { kind: kind } : undefined); }
  function err(msg) { var b = $('#errbar'); b.textContent = msg || ''; b.hidden = !msg; }

  function api(path, method, body) {
    var init = { method: method || 'GET', cache: 'no-store', headers: {} };
    if (init.method === 'POST') { init.headers['Content-Type'] = 'application/json'; init.headers['X-YTT-Token'] = TOKEN; init.body = JSON.stringify(body || {}); }
    var ctl = window.AbortController ? new AbortController() : null, t = null;
    if (ctl) { init.signal = ctl.signal; t = setTimeout(function () { ctl.abort(); }, init.method === 'POST' ? 45000 : 8000); }
    return fetch(path, init).then(function (r) {
      clearTimeout(t);
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.message || ('エラー(HTTP ' + r.status + ')')); e.status = r.status; throw e; }
        return j;
      });
    }, function (e) { clearTimeout(t); throw new Error(e && e.name === 'AbortError' ? '時間内に応答がありません' : 'ホームにつながりません'); });
  }
  function rpath(rest) { return 'r/' + encodeURIComponent(rid) + '/' + rest; }

  function fmtBytes(b) { return b == null ? '—' : b >= GB ? (b / GB).toFixed(1) + ' GB' : Math.round(b / 1048576) + ' MB'; }
  function fmtDur(s) {
    s = Math.max(0, Math.round(s || 0));
    var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (x < 10 ? '0' : '') + x;
  }
  function fmtTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  /* ---------------- 録画元 ---------------- */
  function loadInfo() {
    return api('api/info').then(function (d) {
      info = d;
      var pick = $('#recPick'); pick.textContent = '';
      (d.recorders || []).forEach(function (r) { var o = el('option', '', r.name + '(' + r.url + ')'); o.value = r.id; pick.appendChild(o); });
      $('#recPickLabel').hidden = (d.recorders || []).length < 2;
      var saved = lsGet('recorder');
      rid = (d.recorders || []).some(function (r) { return r.id === saved; }) ? saved : ((d.recorders || [])[0] || {}).id || null;
      pick.value = rid || '';
      $('#folderDefault').textContent = d.defaultFolder || '';
      $('#folderInput').placeholder = d.defaultFolder || '';
      if (!$('#folderInput').dataset.dirty) $('#folderInput').value = d.folder || '';
      initLag(d.lag);
      var a = d.audio || {};
      $('#audioNote').textContent = '書き出しの音量: スタジオの「書き出しの設定」に合わせています(' +
        (a.loudness ? a.loudness + ' LUFS にそろえる' : '音量 ' + (a.volume || 100) + '%') + ')。変えるときはスタジオの書き出しの設定で。';
    });
  }

  /* 開始(I)の反応の遅れ補正: スタジオと同じ選択肢(なし/−2/−3/−5秒)と既定値(なし)。最初の選び方はスタジオの設定、
     変えたらこの画面の好みとして覚える(localStorage。覚えられなくても動く) */
  var LAGS = [0, 2, 3, 5];
  function lagSec() { var v = Number($('#markLag').value); return LAGS.indexOf(v) >= 0 ? v : 0; }
  function initLag(studioLag) {
    var saved = lsGet('lag'), v = saved != null && saved !== '' ? Number(saved) : Number(studioLag);
    $('#markLag').value = String(LAGS.indexOf(v) >= 0 ? v : 0);
  }

  function setConn(state, text) { var c = $('#conn'); c.className = 'pill ' + state; c.textContent = text; }

  function renderRecorder(d, e) {
    var st = $('#recState'), guide = $('#recGuide'), msgs = [];
    var rc = ((info && info.recorders) || []).filter(function (r) { return r.id === rid; })[0];
    if (e) {
      st.className = 'pill err'; st.textContent = 'つながりません';
      setConn('err', '録画元につながりません');
      $('#recMsg').textContent = e.message; $('#recMsg').hidden = false;
      msgs.push(rc && rc.local ? '録画の部品につながりません。ホームが動いているあいだ、30 秒ごとに起動を試みます。続くときは、ホームの「詳しく」→「調子」と、作業データの app\\logs\\recorder.log を見てください。'
        : '録画元(' + (rc ? rc.url : '') + ')につながりません。その PC で録画の部品が動いているか、LAN につながっているかを確かめてください。');
      $('#recFolder').textContent = '—'; $('#recFree').textContent = '—';
    } else {
      st.className = 'pill ok'; st.textContent = 'つながっています' + (d.version ? '(v' + d.version + ')' : '');
      setConn('ok', d.active ? '録画中 ' + d.active + ' 本' : 'つながっています');
      $('#recMsg').textContent = ''; $('#recMsg').hidden = true;
      $('#recFolder').textContent = d.folder || '—';
      $('#recFree').textContent = d.freeBytes != null ? fmtBytes(d.freeBytes) + ' / ' + fmtBytes(d.totalBytes) : '—';
      if (!d.folderOk) msgs.push(d.folderMessage || '録画の置き場所が使えません。');
      else if (d.folderMessage) msgs.push(d.folderMessage);
      if (!d.streamlink) msgs.push('streamlink が入っていません。setup\\install.bat を実行してください(入れ終われば、そのまま録画を始められます)。');
    }
    guide.textContent = msgs.join(' ');
    guide.hidden = !msgs.length;
    guide.className = 'lv-guide' + (e || (d && (!d.folderOk || !d.streamlink)) ? ' bad' : '');
    $('#startBtn').disabled = !!e || !d || !d.folderOk || !d.streamlink;
  }

  /* ---------------- 録画の一覧 ---------------- */
  function renderList(d) {
    var ol = $('#list'); ol.textContent = '';
    var recs = (d && d.recordings) || [];
    $('#listEmpty').hidden = !!recs.length;
    recs.forEach(function (r) {
      var li = el('li', 'lv-item' + (playing === r.id ? ' playing' : ''));
      li.setAttribute('data-rec', r.id);
      li.setAttribute('data-state', r.state || '');
      li.appendChild(el('span', 'pill ' + (STATE_PILL[r.state] || 'wait'), STATE_TEXT[r.state] || r.state));
      var name = el('span', 'lv-name');
      name.appendChild(el('b', '', r.title || r.url || r.id));
      var sub = [fmtTime(r.created) + ' から', fmtDur(r.seconds) + ' 録画済み'];
      if (r.sessions > 1) sub.push('つなぎ直し ' + (r.sessions - 1) + ' 回');
      if (r.lastPdt) sub.push('最後 ' + fmtTime(r.lastPdt));
      name.appendChild(el('span', 'lv-sub', sub.join('・') + (r.message ? '。' + r.message : '')));
      li.appendChild(name);
      var play = el('button', 'btn small', playing === r.id ? '再生中' : '再生');
      play.type = 'button'; play.disabled = !r.segments;
      play.addEventListener('click', function () { startPlayer(r); });
      li.appendChild(play);
      if (r.active) {
        var stop = el('button', 'btn small danger', '停止');
        stop.type = 'button';
        stop.addEventListener('click', function () { stopRec(r, stop); });
        li.appendChild(stop);
      }
      ol.appendChild(li);
    });
  }

  function poll() {
    clearTimeout(pollTimer);
    if (!rid) { renderRecorder(null, new Error('録画元がありません')); return; }
    if (busy) { pollTimer = setTimeout(poll, 3000); return; }
    busy = true;
    api(rpath('list')).then(function (d) {
      listData = d; err('');
      renderRecorder(d, null); renderList(d);
      return loadMarks();
    }, function (e) {
      if (e.status === 404 && !listData) { err('リアルタイム切り抜きはオフです。ホームの「詳しく」→「試験中の機能」でオンにしてください。'); }
      renderRecorder(null, e);
    }).then(function () { busy = false; pollTimer = setTimeout(poll, 3000); });
  }

  function startRec() {
    var url = $('#startUrl').value.trim(), msg = $('#startMsg');
    if (!url) { msg.textContent = '配信の URL を入れてください'; $('#startUrl').focus(); return; }
    $('#startBtn').disabled = true; msg.textContent = '始めています…';
    api(rpath('start'), 'POST', { url: url, quality: $('#startQuality').value, title: $('#startTitle').value.trim() }).then(function (j) {
      msg.textContent = '録画を始めました(' + ((j.recording && j.recording.id) || '') + ')';
      $('#startUrl').value = ''; $('#startTitle').value = '';
      toast('録画を始めました');
      poll();
    }, function (e) { msg.textContent = '始められませんでした: ' + e.message; $('#startBtn').disabled = false; });
  }

  function stopRec(r, btn) {
    if (!window.confirm('「' + (r.title || r.url) + '」の録画を止めますか?(止めた後は、同じ URL でもう一度始めると新しい録画になります)')) return;
    btn.disabled = true;
    api(rpath(encodeURIComponent(r.id) + '/stop'), 'POST', {}).then(function () { toast('止めました'); poll(); },
      function (e) { toast('止められませんでした: ' + e.message, 'err'); btn.disabled = false; });
  }

  /* ---------------- 再生(hls.js) ---------------- */
  function playerState(k, v) { $('#player').setAttribute('data-' + k, String(v)); }

  function closePlayer() {
    if (hls) { try { hls.destroy(); } catch (e) { /* 閉じるだけ */ } hls = null; }
    clearInterval(clockTimer);
    var v = $('#player'); v.removeAttribute('src'); try { v.load(); } catch (e) { /* 空にするだけ */ }
    playing = null; $('#playerBox').hidden = true;
    markData = null; $('#marksBox').hidden = true;
    if (listData) renderList(listData);
  }

  function startPlayer(r) {
    closePlayer();
    var v = $('#player'), src = rpath(encodeURIComponent(r.id) + '/index.m3u8'), frags = 0;
    playing = r.id;
    $('#playerBox').hidden = false;
    $('#playerTitle').textContent = r.title || r.url || r.id;
    $('#playerMsg').textContent = '読み込んでいます…';
    ['manifest', 'frags', 'error', 'level'].forEach(function (k) { v.removeAttribute('data-' + k); });
    if (window.Hls && Hls.isSupported()) {
      hls = new Hls({ enableWorker: false, lowLatencyMode: false, liveDurationInfinity: true, backBufferLength: 90 });
      hls.on(Hls.Events.MANIFEST_PARSED, function () { playerState('manifest', 1); $('#playerMsg').textContent = ''; v.play().catch(function () { /* 自動再生が断られても、▶ で再生できる */ }); });
      hls.on(Hls.Events.LEVEL_LOADED, function (_e, d) { playerState('level', d && d.details ? d.details.fragments.length : 0); });
      hls.on(Hls.Events.FRAG_LOADED, function () { frags += 1; playerState('frags', frags); });
      hls.on(Hls.Events.ERROR, function (_e, d) {
        if (!d || !d.fatal) return;
        playerState('error', d.details || d.type);
        if (d.type === Hls.ErrorTypes.NETWORK_ERROR) { $('#playerMsg').textContent = '読み込めませんでした(録画元につながらない?)。少し待ってから「再生」を押し直してください'; }
        else if (d.type === Hls.ErrorTypes.MEDIA_ERROR) { $('#playerMsg').textContent = '再生でエラーが起きました。直しています…'; hls.recoverMediaError(); }
        else $('#playerMsg').textContent = '再生できませんでした: ' + (d.details || d.type);
      });
      hls.loadSource(src);
      hls.attachMedia(v);
    } else if (v.canPlayType('application/vnd.apple.mpegurl')) {
      v.src = src; playerState('manifest', 1); $('#playerMsg').textContent = '';
    } else {
      $('#playerMsg').textContent = 'このブラウザでは再生できません(Edge か Chrome で開いてください)';
      playerState('error', 'unsupported');
    }
    clockTimer = setInterval(function () {
      var d = hls && hls.playingDate;
      $('#playerClock').textContent = d ? '再生位置の時刻 ' + fmtTime(d.toISOString()) : '';
    }, 500);
    renderList(listData);
    $('#marksBox').hidden = false; $('#marksFor').textContent = r.title || r.url || r.id;
    $('#markMsg').textContent = '';
    loadMarks();
  }

  function goLive() {
    var v = $('#player');
    if (hls && hls.liveSyncPosition != null) v.currentTime = hls.liveSyncPosition;
    else if (v.seekable && v.seekable.length) v.currentTime = v.seekable.end(v.seekable.length - 1) - 1;
    v.play().catch(function () { /* ▶ で */ });
  }

  /* ---------------- マークと書き出し(P2) ---------------- */
  function curRec() { return ((listData && listData.recordings) || []).filter(function (x) { return x.id === playing; })[0] || {}; }
  function fmtClock(iso) {
    var d = new Date(iso);
    return isNaN(d) ? '—' : d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  function nowIso() {
    var d = hls && hls.playingDate;
    return d && !isNaN(d) ? d.toISOString() : null;
  }
  function markMsg(t) { $('#markMsg').textContent = t || ''; }

  function loadMarks() {
    if (!playing || !rid) return Promise.resolve();
    var want = playing, seq = ++markSeq;
    return api('api/marks?recorder=' + encodeURIComponent(rid) + '&recording=' + encodeURIComponent(want)).then(function (d) {
      if (want !== playing || seq !== markSeq) return;
      markData = d; renderMarks();
    }, function (e) { if (want === playing) markMsg('マークを読めませんでした: ' + e.message); });
  }

  function jobFor(mid) { return ((markData && markData.exports) || []).filter(function (j) { return j.markId === mid; })[0] || null; }

  function renderMarks() {
    var ol = $('#marks'), marks = ((markData && markData.marks) || []).slice().sort(function (a, b) { return a.start < b.start ? -1 : 1; });
    if (document.activeElement && document.activeElement.getAttribute('data-label-of')) return;   // ラベルを入力している間は描き直さない(入力が消えないように)
    ol.textContent = '';
    $('#marksEmpty').hidden = !!marks.length;
    marks.forEach(function (m) {
      var j = jobFor(m.id), active = !!j && (j.state === 'wait' || j.state === 'fetch' || j.state === 'encode');
      var li = el('li', 'lv-item lv-mark');
      li.setAttribute('data-mark', m.id);
      li.setAttribute('data-export', j ? j.state : '');
      li.appendChild(el('span', 'pill', '#' + m.n));
      var len = m.end ? (new Date(m.end) - new Date(m.start)) / 1000 : null;
      li.appendChild(el('span', 'num lv-when', fmtClock(m.start) + ' 〜 ' + (m.end ? fmtClock(m.end) + '(' + fmtDur(len) + ')' : '終了待ち')));
      var lab = el('input', 'lv-label'); lab.type = 'text'; lab.maxLength = 80; lab.placeholder = 'ラベル'; lab.value = m.label || '';
      lab.setAttribute('data-label-of', m.id); lab.setAttribute('aria-label', 'マーク #' + m.n + ' のラベル');
      lab.addEventListener('change', function () { updateMark(m.id, { label: lab.value }); });
      lab.addEventListener('keydown', function (e) { if (e.key === 'Enter') lab.blur(); });
      li.appendChild(lab);
      var st = el('span', 'lv-job');
      if (j) {
        st.appendChild(el('span', 'pill ' + (JOB_PILL[j.state] || 'wait'), j.stateLabel + (active && j.progress ? ' ' + Math.round(j.progress * 100) + '%' : '')));
        var detail = j.state === 'error' ? j.error : j.state === 'done' ? (j.path || '') : (j.message || '');
        if (j.state === 'done' && j.tx) detail += '(文字起こし: ' + (j.tx.label || j.tx.state) + (j.tx.state === 'error' && j.tx.message ? ' ' + j.tx.message : '') + ')';
        if (j.warning) detail += (detail ? '。' : '') + j.warning;
        if (detail) st.appendChild(el('span', 'lv-sub', detail));
      }
      li.appendChild(st);
      if (active) {
        var cancel = el('button', 'btn small', '取り消し'); cancel.type = 'button';
        cancel.addEventListener('click', function () { cancelJob(j.id, cancel); });
        li.appendChild(cancel);
      } else if (m.end) {
        var ex = el('button', 'btn small' + (j ? '' : ' primary'), j && j.state === 'done' ? 'もう一度書き出す' : j ? 'やり直す' : '書き出す'); ex.type = 'button';
        ex.addEventListener('click', function () { exportMark(m.id); });
        li.appendChild(ex);
      }
      var del = el('button', 'btn small ghost', '削除'); del.type = 'button';
      del.addEventListener('click', function () {
        if (!window.confirm('マーク #' + m.n + ' を消しますか?(書き出した動画は消えません)')) return;
        postMark({ op: 'delete', id: m.id }).then(function () { toast('マークを消しました'); }, function () {});
      });
      li.appendChild(del);
      ol.appendChild(li);
    });
  }

  function postMark(body) {
    if (!playing || !rid) return Promise.reject(new Error('再生している録画がありません'));
    var r = curRec();
    body.recorder = rid; body.recording = playing;
    if (body.op === 'add') { body.url = r.url || ''; body.title = r.title || ''; }
    if (markBusy) { markMsg('保存の途中です。少し待ってからもう一度押してください'); return Promise.reject(new Error('保存の途中です')); }
    markBusy = true;
    return api('api/marks', 'POST', body).then(function (j) {
      markBusy = false;
      if (markData) markData.marks = j.marks; else markData = { marks: j.marks, exports: [] };
      renderMarks();
      return j;
    }, function (e) { markBusy = false; markMsg('保存できませんでした: ' + e.message); throw e; });
  }
  function updateMark(id, fields) { fields.op = 'update'; fields.id = id; return postMark(fields).catch(function () { /* 知らせは markMsg */ }); }

  function openMark() {
    var ms = ((markData && markData.marks) || []).filter(function (m) { return !m.end; });
    return ms.sort(function (a, b) { return a.created < b.created ? 1 : -1; })[0] || null;
  }

  function markIn() {
    var t = nowIso();
    if (!t) { markMsg('再生している所の時刻が取れません(再生を始めてから押してください)'); return; }
    var lag = lagSec();
    if (lag) t = new Date(new Date(t).getTime() - lag * 1000).toISOString();
    postMark({ op: 'add', start: t }).then(function (j) {
      markMsg('開始をマークしました(#' + j.mark.n + (lag ? '。' + lag + ' 秒前から' : '') + ')。終わりで O を押します');
    }, function () {});
  }
  function markOut() {
    var t = nowIso(), m = openMark();
    if (!t) { markMsg('再生している所の時刻が取れません(再生を始めてから押してください)'); return; }
    if (!m) { markMsg('先に I で開始をマークしてください'); return; }
    postMark({ op: 'update', id: m.id, end: t }).then(function (j) {
      markMsg('マーク #' + j.mark.n + ' を付けました');
      if ($('#autoExport').checked) exportMark(j.mark.id);
    }, function () {});
  }
  function markQuick() {
    var t = nowIso();
    if (!t) { markMsg('再生している所の時刻が取れません(再生を始めてから押してください)'); return; }
    var start = new Date(new Date(t).getTime() - QUICK_SEC * 1000).toISOString();
    postMark({ op: 'add', start: start, end: t }).then(function (j) {
      markMsg('直前 ' + QUICK_SEC + ' 秒をマークしました(#' + j.mark.n + ')');
      if ($('#autoExport').checked) exportMark(j.mark.id);
    }, function () {});
  }
  function exportMark(mid) {
    api('api/export', 'POST', { recorder: rid, recording: playing, markId: mid, transcribe: $('#autoTx').checked }).then(function () {
      toast('書き出しを頼みました(録画が届くのを待ってから作ります)');
      loadMarks();
    }, function (e) { markMsg('書き出せません: ' + e.message); });
  }
  function cancelJob(id, btn) {
    btn.disabled = true;
    api('api/export/cancel', 'POST', { id: id }).then(function () { toast('取り消しました'); loadMarks(); },
      function (e) { toast('取り消せませんでした: ' + e.message, 'err'); btn.disabled = false; });
  }

  /* キー: 共通の再生キー(UIKit.keys.playback。Space・J/K/L・← →・I/O)+ N(直前の秒数)。再生している録画があるときだけ */
  var playbackKeys = window.UIKit && UIKit.keys ? UIKit.keys.playback({
    media: function () { return $('#player'); }, enabled: function () { return !!playing; }, onIn: markIn, onOut: markOut
  }) : null;
  function onKey(e) {
    if (playbackKeys && playbackKeys(e)) return;
    if (!playing || e.ctrlKey || e.altKey || e.metaKey || e.isComposing) return;
    if (window.UIKit && UIKit.keys && UIKit.keys.isTyping(e.target)) return;
    if (!playbackKeys && (e.key === 'i' || e.key === 'o')) { e.preventDefault(); (e.key === 'i' ? markIn : markOut)(); return; }
    if (e.key === 'n' && !e.repeat) { e.preventDefault(); markQuick(); }
  }

  /* ---------------- 置き場所 ---------------- */
  function saveFolder() {
    var f = $('#folderInput').value.trim(), msg = $('#folderMsg');
    msg.textContent = '保存しています…';
    api('../api/ytt/prefs', 'POST', { op: 'patch', section: 'live', value: { folder: f } }).then(function () {
      delete $('#folderInput').dataset.dirty;
      msg.textContent = '保存しました。録画の部品に伝えています(録画中は、止めるまで前の置き場所のままです)';
      setTimeout(poll, 1500);
    }, function (e) { msg.textContent = '保存できませんでした: ' + e.message; });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('#startBtn').addEventListener('click', startRec);
    $('#startUrl').addEventListener('keydown', function (e) { if (e.key === 'Enter') startRec(); });
    $('#playerClose').addEventListener('click', closePlayer);
    $('#playerLive').addEventListener('click', goLive);
    $('#folderSave').addEventListener('click', saveFolder);
    $('#markIn').addEventListener('click', markIn);
    $('#markOut').addEventListener('click', markOut);
    $('#markQuick').addEventListener('click', markQuick);
    $('#quickSec').textContent = String(QUICK_SEC);
    $('#markLag').addEventListener('change', function () { lsSet('lag', String(lagSec())); });
    [['autoExport', 'auto-export'], ['autoTx', 'auto-tx']].forEach(function (p) {
      var box = $('#' + p[0]); box.checked = lsGet(p[1]) !== '0';
      box.addEventListener('change', function () { lsSet(p[1], box.checked ? '1' : '0'); });
    });
    document.addEventListener('keydown', onKey);
    $('#folderInput').addEventListener('input', function () { this.dataset.dirty = '1'; $('#folderMsg').textContent = ''; });
    $('#recPick').addEventListener('change', function () { rid = this.value; lsSet('recorder', rid); closePlayer(); listData = null; poll(); });
    if (window.UIKit && UIKit.life) UIKit.life.onReturn(function () { poll(); });
    loadInfo().then(poll, function (e) {
      err(e.status === 404 ? 'リアルタイム切り抜きはオフです。ホームの「詳しく」→「試験中の機能」でオンにしてください。' : '読み込めませんでした: ' + e.message);
      setConn('err', 'オフ');
    });
  });
})();
