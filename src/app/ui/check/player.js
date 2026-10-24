/* 確かめるのカード用の軽い再生部品(/check-player.js。RS8 V1。作り方 notes:docs/design/v1-check-build.md の 4・5 節)。
   案件のパネル(編集の全画面・review.js)は丸ごと載せず、口・見た目・キーを共用する:
     切り抜き・文書 = 編集の transcribe/media?id=<文書 id>(Range つき。ホームの続けて確認と同じ口)を <video> で、行の区間 ± pad 秒だけ再生して止まる
     候補のまま(配信の区間)= YouTube の埋め込み(youtube-nocookie.com。校正の小さい配信プレーヤーと同じ形)
     波形(行の時刻のカード)= 編集の transcribe/api/peaks?id=(0〜255 の 1 バイトの並び + X-Peaks-Rate。作っている間は 202)を区間だけ描く
     キー = 殻が UIKit.keys.playback に media() を渡す(Space・J/K/L・← →・, .)。R = もう一度聞く(殻が replay() を呼ぶ。編集の「この行をもう一度聞く」と同じキー)
     もう一度聞く = 画面の下のボタン(data-chk-replay)と R。区間の頭(win[0] = 行の頭 - pad)から流し直す。足す余白は無し
     (編集の「この行をもう一度聞く」も行の頭から = 余白 0。カードの pad はカードを作る側が決めた物をそのまま使う)。
     区間の終わりで止まった後の Space・L・動画の再生ボタンも頭から(止まった位置から再生するとすぐ止まって聞けなかった)
   CheckPlayer.mount(el, media, opt) -> 手
     media = {url: 'transcribe/media?id=…'(入口の直下からの相対。絶対パス・ほかのサイトは断る) | youtube: '<動画 id 11 文字>', start, end, pad, padEnd}(秒。pad 既定 0 = 頭の余白・padEnd = 末の余白(無ければ pad))
     opt   = {text(字幕 1 行), wave(true = 波形の帯), docId(波形の文書 id), autoplay(既定 true = 出したら自動で再生)}
   手 = {media() = <video> か null(埋め込み), play(), replay()(区間の頭から流し直す), stop(), ended() = 区間の終わりまで 1 度は再生したか, onEnded(fn), range() = [頭, 末](再生する窓),
         marks() = [行の始まり, 行の終わり], setMarks(a, b)(波形の頭・末の印を動かす = 時刻のカード),
         setGuides([頭, 末] | null)(波形に点線の参考の印 = 単語の時刻の候補。時刻のカード), destroy()}
   CSP(script-src 'self')の下で動く。色は ui-kit のトークンを読む(固定の色を書かない) */
(function () {
  'use strict';

  var esc = UIKit.esc;
  var YT_RE = /^[\w-]{11}$/, YT_URL_RE = /^https:\/\/www\.youtube-nocookie\.com\/embed\/([\w-]{11})(?:[?#]|$)/;

  /* 入口の直下からの相対 URL だけ受け付ける(ほかのサイト・絶対パス・javascript: を断る) */
  function localUrl(u) {
    if (typeof u !== 'string' || !u || /^[a-z][\w+.-]*:/i.test(u) || /^[\/\\]/.test(u) || u.indexOf('\\') >= 0) return '';
    try { var x = new URL(u, location.href); return x.origin === location.origin ? x.href : ''; } catch (e) { return ''; }
  }
  function num(v, d) { v = +v; return isFinite(v) ? v : d; }
  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  function mount(el, media, opt) {
    media = media && typeof media === 'object' ? media : {};
    opt = opt || {};
    var pad = Math.max(0, num(media.pad, 0)), a = Math.max(0, num(media.start, 0)), b = num(media.end, 0);
    var padEnd = Math.max(0, num(media.padEnd, pad));   // 末の余白(無ければ pad。読み・誰の声のカードは 0 = 次の行の発言を入れない)
    var mk = [a, b > a ? b : a], win = [Math.max(0, a - pad), b > a ? b + padEnd : 0];
    var ytId = YT_RE.test(media.youtube || '') ? media.youtube : ((String(media.url || '').match(YT_URL_RE) || [])[1] || '');
    var src = ytId ? '' : localUrl(media.url);
    var video = null, frame = null, endedOnce = false, endFns = [], raf = 0, timer = 0, endTimer = 0, gone = false, wave = null;

    el.innerHTML = '<div class="chk-player">' +
      '<div class="chk-screen" data-chk-screen></div>' +
      (opt.wave ? '<div class="chk-wave"><canvas data-chk-wave height="72" aria-hidden="true"></canvas><p class="hint chk-wave-msg" data-chk-wavemsg></p></div>' : '') +
      (opt.text ? '<p class="chk-cap">' + esc(opt.text) + '</p>' : '') +
      '<div class="chk-replay-row" data-chk-replayrow hidden><button type="button" class="btn" data-chk-replay title="区間の頭から流し直します">もう一度聞く <kbd class="ui-kbd">R</kbd></button>' +
      '<p class="hint chk-play-msg" data-chk-msg role="status"></p></div></div>';   // 知らせはボタンの横(縦を使わない = 答えのボタンを上に保つ)
    var screen = el.querySelector('[data-chk-screen]'), msg = el.querySelector('[data-chk-msg]');
    function say(t) { if (msg) msg.textContent = t || ''; }
    function finish() {
      if (endedOnce) return;
      endedOnce = true;
      endFns.slice().forEach(function (f) { try { f(); } catch (e) { UIKit.report('再生の終わりの知らせで失敗しました: ' + (e && e.message)); } });
    }
    /* 区間の終わりで止める: 残りの時間に合わせたタイマー(重いときにコマが遅れても・窓が隠れてコマが止まっても止まる)・毎コマ・timeupdate のどれでも */
    function atEnd() {
      if (gone || !video || !(win[1] > win[0]) || video.paused) return false;
      if (video.currentTime < win[1]) return false;
      video.pause(); finish();
      return true;
    }
    function armEnd() {
      clearTimeout(endTimer); endTimer = 0;
      if (gone || !video || !(win[1] > win[0]) || video.paused || atEnd()) return;
      var ms = (win[1] - video.currentTime) / (video.playbackRate || 1) * 1000;
      endTimer = setTimeout(armEnd, Math.max(10, Math.min(ms, 250)));   // 近づくほど細かく見直す(タイマーの遅れを詰める)
    }
    function watch() {
      raf = 0;
      if (gone || !video) return;
      atEnd();
      if (wave) drawWave();
      if (!video.paused) raf = requestAnimationFrame(watch);
    }
    function play() {
      if (video) {
        if (win[1] > win[0] && (video.currentTime >= win[1] - 0.05 || video.currentTime < win[0] - 0.5)) video.currentTime = win[0];
        var p = video.play();
        if (p && p.catch) p.catch(function () { say('Space で再生します'); });
      }
    }
    function stop() { if (video) { try { video.pause(); } catch (e) { /* 無視 */ } } }
    function ytSrc(auto) {
      return 'https://www.youtube-nocookie.com/embed/' + ytId + '?start=' + Math.floor(win[0]) + (win[1] > win[0] ? '&end=' + Math.ceil(win[1]) : '') +
        (auto ? '&autoplay=1' : '') + '&rel=0&playsinline=1';
    }
    /* もう一度聞く: 区間の頭から流し直す(再生中でも・終わった後でも同じ)。埋め込みは読み直す(外から位置を動かす口が無い) */
    function replay() {
      if (gone) return;
      if (video) {
        try { video.currentTime = win[0]; } catch (e) { /* 読み込みの途中 = 読み込み後に win[0] へ動く */ }
        var p = video.play();
        if (p && p.catch) p.catch(function () { say('Space で再生します'); });
      } else if (frame) {
        frame.src = ytSrc(true);
      }
    }

    if (src) {
      video = document.createElement('video');
      video.className = 'chk-video'; video.preload = 'auto'; video.playsInline = true; video.controls = true;
      video.setAttribute('aria-label', '確かめる区間の再生');
      video.addEventListener('loadedmetadata', function () {
        if (win[0] > 0) { try { video.currentTime = win[0]; } catch (e) { /* 読み込みの途中 */ } }
        if (opt.autoplay !== false) play();
      });
      video.addEventListener('play', function () {
        say('');
        if (win[1] > win[0] && video.currentTime >= win[1] - 0.05) { try { video.currentTime = win[0]; } catch (e) { /* 無視 */ } }   // 終わりで止まった後の再生 = 頭から
        armEnd(); if (!raf) raf = requestAnimationFrame(watch); });
      video.addEventListener('playing', armEnd);
      video.addEventListener('seeked', armEnd);
      video.addEventListener('ratechange', armEnd);
      video.addEventListener('timeupdate', atEnd);
      video.addEventListener('ended', finish);
      video.addEventListener('error', function () { say('この動画を再生できませんでした(元の動画が動いたか、消えた可能性があります)'); });
      video.src = src;
      screen.appendChild(video);
    } else if (ytId) {
      screen.innerHTML = '<iframe class="chk-frame" src="' + esc(ytSrc(opt.autoplay !== false)) + '" title="配信のプレーヤー(YouTube)" ' +
        'allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin" ' +
        'sandbox="allow-scripts allow-same-origin allow-presentation allow-popups"></iframe>';
      frame = screen.firstChild;
      if (win[1] > win[0]) timer = setTimeout(finish, (win[1] - win[0]) * 1000);   // 埋め込みの再生の終わりは分からない = 区間の長さで「聞いた」にする
    } else {
      screen.innerHTML = '<p class="hint chk-nomedia">このカードには再生できる動画がありません。</p>';
      endedOnce = true;   // 聞く物が無い = 「聞き終えた」(再生の終わりを待つ答えを止めない)
    }
    if (video || frame) {
      var rrow = el.querySelector('[data-chk-replayrow]');
      rrow.hidden = false;
      rrow.querySelector('[data-chk-replay]').addEventListener('click', function (e) { e.preventDefault(); replay(); });
    }

    /* ---- 波形(区間 win だけ。頭・末の印 mk と再生位置)---- */
    var peaks = null, rate = 100, guides = null;
    function drawWave() {
      var cv = el.querySelector('[data-chk-wave]');
      if (!cv) return;
      var w = cv.clientWidth || 600, h = cv.height, dpr = window.devicePixelRatio || 1;
      if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.style.height = h + 'px'; }
      var g = cv.getContext('2d'), span = Math.max(0.1, win[1] - win[0]);
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, cv.width, cv.height);
      g.scale(dpr, cv.height / h);
      var x = function (t) { return (t - win[0]) / span * w; };
      g.fillStyle = cssVar('--accent-soft', 'transparent');
      g.fillRect(x(mk[0]), 0, Math.max(1, x(mk[1]) - x(mk[0])), h);
      if (peaks) {
        g.fillStyle = cssVar('--ink-3', 'gray');
        for (var px = 0; px < w; px++) {
          var i0 = Math.floor((win[0] + px / w * span) * rate), i1 = Math.max(i0 + 1, Math.floor((win[0] + (px + 1) / w * span) * rate)), m = 0;
          for (var i = i0; i < i1 && i < peaks.length; i++) if (peaks[i] > m) m = peaks[i];
          var bh = Math.max(1, m / 255 * (h - 6));
          g.fillRect(px, (h - bh) / 2, 1, bh);
        }
      }
      g.fillStyle = cssVar('--accent', 'blue');
      g.fillRect(x(mk[0]) - 1, 0, 2, h); g.fillRect(x(mk[1]) - 1, 0, 2, h);
      if (guides) {   // 単語の時刻の候補(点線)
        g.strokeStyle = cssVar('--ink-2', 'gray'); g.lineWidth = 1; g.setLineDash([3, 3]);
        guides.forEach(function (t) { g.beginPath(); g.moveTo(Math.round(x(t)) + 0.5, 0); g.lineTo(Math.round(x(t)) + 0.5, h); g.stroke(); });
        g.setLineDash([]);
      }
      if (video) { g.fillStyle = cssVar('--playhead', 'red'); g.fillRect(x(video.currentTime || 0), 0, 1, h); }
    }
    function loadPeaks(tries) {
      var note = el.querySelector('[data-chk-wavemsg]');
      UIKit.http(localUrl('transcribe/api/peaks?id=' + encodeURIComponent(opt.docId)), { raw: true, timeout: 30000 }).then(function (r) {
        if (gone) return;
        if (r.status === 202) {
          r.text().catch(function () {});   // 本文を読み切る(読まないと要求が終わらないまま残る = ブラウザの「通信中」が続く。2 カットの cut.js も読む)
          if (note) note.textContent = '波形を用意しています…(再生はできます)';
          if (tries < 60) setTimeout(function () { if (!gone) loadPeaks(tries + 1); }, 1000);
          return;
        }
        rate = Number(r.headers.get('X-Peaks-Rate')) || 100;
        return r.arrayBuffer().then(function (buf) {
          if (gone) return;
          peaks = new Uint8Array(buf);
          if (note) note.textContent = r.headers.get('X-Peaks-Audio') === '0' ? '音声がありません' : '';
          drawWave();
        });
      }, function (e) { if (!gone && note) note.textContent = '波形を読み込めませんでした' + (e && e.reason ? ': ' + e.reason : ''); });
    }
    if (opt.wave) {
      wave = true;
      drawWave();
      if (opt.docId && /^[\w-]{1,64}$/.test(String(opt.docId))) loadPeaks(0);
      else { var n0 = el.querySelector('[data-chk-wavemsg]'); if (n0) n0.textContent = '波形を出せる文書がありません'; }
    }

    return {
      media: function () { return video; },
      play: play, replay: replay, stop: stop, canReplay: function () { return !gone && !!(video || frame); },
      ended: function () { return endedOnce; },
      onEnded: function (fn) { if (typeof fn === 'function') { if (endedOnce) fn(); else endFns.push(fn); } },
      range: function () { return win.slice(); },
      marks: function () { return mk.slice(); },
      setMarks: function (s, e) { s = num(s, mk[0]); e = num(e, mk[1]); if (e >= s) { mk = [s, e]; if (wave) drawWave(); } },
      setGuides: function (v) { guides = Array.isArray(v) && v.length === 2 && isFinite(+v[0]) && isFinite(+v[1]) ? [+v[0], +v[1]] : null; if (wave) drawWave(); },
      destroy: function () {
        gone = true; endFns = [];
        cancelAnimationFrame(raf); clearTimeout(timer); clearTimeout(endTimer);
        if (video) { stop(); video.removeAttribute('src'); try { video.load(); } catch (e) { /* 無視 */ } }   // 読み出しを止める(Windows でファイルを掴んだままにしない)
        if (frame) frame.remove();
        el.innerHTML = '';
      }
    };
  }

  window.CheckPlayer = { mount: mount };
})();
