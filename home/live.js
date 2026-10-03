/* リアルタイム切り抜き(試験中)の画面(線 D の P1。home/live.py・recorder/)。
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
    });
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
  }

  function goLive() {
    var v = $('#player');
    if (hls && hls.liveSyncPosition != null) v.currentTime = hls.liveSyncPosition;
    else if (v.seekable && v.seekable.length) v.currentTime = v.seekable.end(v.seekable.length - 1) - 1;
    v.play().catch(function () { /* ▶ で */ });
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
    $('#folderInput').addEventListener('input', function () { this.dataset.dirty = '1'; $('#folderMsg').textContent = ''; });
    $('#recPick').addEventListener('change', function () { rid = this.value; lsSet('recorder', rid); closePlayer(); listData = null; poll(); });
    if (window.UIKit && UIKit.life) UIKit.life.onReturn(function () { poll(); });
    loadInfo().then(poll, function (e) {
      err(e.status === 404 ? 'リアルタイム切り抜きはオフです。ホームの「詳しく」→「試験中の機能」でオンにしてください。' : '読み込めませんでした: ' + e.message);
      setConn('err', 'オフ');
    });
  });
})();
