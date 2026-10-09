// YouTube Studio のコンテンツ一覧(動画・ショート・ライブ配信)の「日付」の欄に、公開(投稿)した時刻を足す。
//
// 仕組み: Studio は一覧を内部の API(youtubei/v1/creator/list_creator_videos)から受け取る。その応答には各動画の
// timePublishedSeconds(公開した時刻)・timeCreatedSeconds(アップロードした時刻)が入っているが、画面には日付しか出ない。
// この拡張はページと同じ世界(manifest の world: MAIN)で fetch と XMLHttpRequest を包んで応答を控え、
// 一覧の行(ytcp-video-row)の videoId と突き合わせて時刻を書き足す。外部との通信は無い(自分のブラウザの中だけ)。
//
// 調べるとき: Studio の画面で DevTools の Console に localStorage.yttStudioTimeDebug = '1' を入れて再読み込みすると、
// 控えた件数と行ごとの結果を出す。__yttStudioTime.times が控え(videoId → 秒)。
//
// 前半(応答の読み取り・時刻の選び方・書式)は純粋な関数で、node --test tests/test_main.cjs が確かめる。後半が画面。
(function (root) {
  'use strict';
  const TAG = 'ytt-pub-time';
  const API_RE = /\/youtubei\/v1\/creator\/[a-z_]*videos/;            // 一覧を返す内部 API
  const ID_RE = /\/video\/([A-Za-z0-9_-]{11})(?:[/?#]|$)/;             // 行のリンク /video/<id>/edit
  const DATE_RE = /\d{4}[\/.-]\d{1,2}[\/.-]\d{1,2}|\d{1,2}[\/.-]\d{1,2}[\/.-]\d{4}|[A-Za-z]{3,9}\.? \d{1,2}, \d{4}/;  // 日付の欄の文字(日本語・英語)
  const PUBLISHED_KEYS = ['timePublishedSeconds', 'publishedTimeSeconds', 'publishTimeSeconds'];
  const CREATED_KEYS = ['timeCreatedSeconds', 'createdTimeSeconds', 'uploadTimeSeconds'];
  const UPLOADED_LABEL = /アップロード|Uploaded/i;                     // 欄の小さな文字が「アップロード日」ならアップロードの時刻

  const times = new Map();   // videoId → {published, created}(秒。無ければ null)

  function toSec(v) {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : null;
  }
  function pick(obj, keys) {
    for (const k of keys) if (obj[k] != null) return toSec(obj[k]);
    return null;
  }
  // 応答の JSON や行の持つデータから videoId と時刻の組を拾って times に入れる(入れ子の位置に頼らない)。拾った件数を返す
  function harvest(obj, visited = new Set(), depth = 0) {
    if (!obj || typeof obj !== 'object' || depth > 12 || visited.has(obj)) return 0;
    if (typeof Node !== 'undefined' && obj instanceof Node) return 0;
    visited.add(obj);
    let n = 0;
    if (typeof obj.videoId === 'string') {
      const published = pick(obj, PUBLISHED_KEYS), created = pick(obj, CREATED_KEYS);
      if (published || created) { times.set(obj.videoId, { published: published, created: created }); n = 1; }
    }
    let vals;
    try { vals = Array.isArray(obj) ? obj : Object.values(obj); } catch (e) { return n; }
    for (const v of vals) if (v && typeof v === 'object') n += harvest(v, visited, depth + 1);
    return n;
  }
  const pad = n => (n < 10 ? '0' : '') + n;
  function fmtTime(sec) { const d = new Date(sec * 1000); return pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  function fmtFull(sec) {
    const d = new Date(sec * 1000);
    return d.getFullYear() + '/' + pad(d.getMonth() + 1) + '/' + pad(d.getDate()) + ' ' + fmtTime(sec) + ':' + pad(d.getSeconds());
  }
  // 欄の文字が「アップロード日」ならアップロードの時刻、それ以外(「公開日」)は公開の時刻。片方しか無ければそれ
  function choose(t, label) {
    if (!t) return null;
    return UPLOADED_LABEL.test(label || '') ? (t.created || t.published) : (t.published || t.created);
  }
  function videoIdFromHref(href) { const m = ID_RE.exec(href || ''); return m ? m[1] : null; }
  function tooltip(t) {
    const parts = [];
    if (t.published) parts.push('公開 ' + fmtFull(t.published));
    if (t.created) parts.push('アップロード ' + fmtFull(t.created));
    return parts.join(' / ');
  }

  const api = { harvest: harvest, times: times, choose: choose, fmtTime: fmtTime, fmtFull: fmtFull, tooltip: tooltip, videoIdFromHref: videoIdFromHref, DATE_RE: DATE_RE, API_RE: API_RE };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  root.__yttStudioTime = api;

  // ---------- ここから画面 ----------
  const debug = () => { try { return localStorage.getItem('yttStudioTimeDebug') === '1'; } catch (e) { return false; } };
  const log = (...args) => { if (debug()) console.log('[' + TAG + ']', ...args); };

  // 応答を控える(fetch と XHR の両方。Studio がどちらを使っても拾う)
  function capture(url, body) {
    try {
      const data = typeof body === 'string' ? JSON.parse(body) : body;
      const n = harvest(data);
      log('応答から', n, '本', url);
      if (n) schedule();
    } catch (e) { log('応答を読めなかった', url, e); }
  }
  const origFetch = window.fetch;
  window.fetch = function (input) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const p = origFetch.apply(window, arguments);
    if (API_RE.test(url)) p.then(res => res.clone().text()).then(t => capture(url, t), () => {});   // 読めなくても Studio の動きは変えない
    return p;
  };
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    const u = String(url);
    if (API_RE.test(u)) this.addEventListener('load', function () {
      capture(u, this.responseType === '' || this.responseType === 'text' ? this.responseText : this.response);
    });
    return origOpen.apply(this, arguments);
  };

  // 行を探す範囲。Studio の部品が shadow DOM を使っていても拾えるよう、作られた shadow root を覚えて見張る
  const OBS = { childList: true, subtree: true, characterData: true };
  let observer = null;
  const roots = new Set([document]);
  const origAttach = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (init) {
    const sr = origAttach.call(this, init);
    roots.add(sr);
    if (observer) observer.observe(sr, OBS);
    return sr;
  };
  const queryAll = sel => [...roots].flatMap(r => [...r.querySelectorAll(sel)]);
  // 行の中を探す範囲(行そのものと、あれば行の shadow root)
  const scopesOf = row => row.shadowRoot ? [row, row.shadowRoot] : [row];
  function inRow(row, sel) {
    for (const s of scopesOf(row)) { const el = s.querySelector(sel); if (el) return el; }
    return null;
  }
  function videoIdOf(row) {
    const a = inRow(row, 'a[href*="/video/"]');
    const id = a && videoIdFromHref(a.getAttribute('href'));
    if (id) return id;
    const d = row.video || (row.__data && row.__data.video);
    return d && typeof d.videoId === 'string' ? d.videoId : null;
  }
  function ownText(el) {
    let s = '';
    for (const c of el.childNodes) if (c.nodeType === 3) s += c.textContent;
    return s;
  }
  // 日付の欄(.tablecell-date)。無ければ日付の形の文字を直接持つ要素の親
  function dateCellOf(row) {
    const cell = inRow(row, '.tablecell-date');
    if (cell) return cell;
    for (const s of scopesOf(row)) for (const el of s.querySelectorAll('div, span')) if (DATE_RE.test(ownText(el))) return el.parentElement || el;
    return null;
  }
  // 欄の中で日付の文字を直接持つ要素(そのうしろに時刻を足す)。無ければ欄そのもの
  function dateLineOf(cell) {
    if (DATE_RE.test(ownText(cell))) return cell;
    for (const el of cell.querySelectorAll('*')) if (DATE_RE.test(ownText(el))) return el;
    return cell;
  }
  // 1 行に時刻を足す(足してあれば何もしない。行は Polymer が使い回すので videoId と秒を鍵にして見分ける)。足せたら true
  function decorate(row) {
    const id = videoIdOf(row);
    if (!id) return false;
    if (!times.has(id)) harvest(row.video || row.__data || null);   // 応答を通らずに出た行は、行が持つデータから
    const t = times.get(id) || null;
    const cell = dateCellOf(row);
    if (!cell) { log('日付の欄が見つからない', id); return false; }
    const sec = choose(t, cell.textContent);
    let span = cell.querySelector('.' + TAG);
    const key = id + ':' + (sec || '');
    if (span && span.dataset.key === key) return true;
    if (!sec) { if (span) span.remove(); log('時刻が無い', id); return false; }
    if (!span) {
      span = document.createElement('span');
      span.className = TAG;
      span.style.cssText = 'margin-left:.45em;opacity:.8;font-variant-numeric:tabular-nums;white-space:nowrap';
    }
    span.textContent = fmtTime(sec);
    span.title = tooltip(t);
    span.dataset.key = key;
    const line = dateLineOf(cell);
    if (span.parentElement !== line) line.appendChild(span);
    return true;
  }
  let timer = 0;
  function schedule() { if (!timer) timer = setTimeout(run, 150); }
  function run() {
    timer = 0;
    const rows = queryAll('ytcp-video-row');
    if (!rows.length) return;
    let done = 0;
    rows.forEach(function (row) { try { if (decorate(row)) done++; } catch (e) { log('行の処理に失敗', e); } });
    log('行', rows.length, '時刻を出した', done, '控え', times.size);
  }
  function start() {
    observer = new MutationObserver(schedule);
    roots.forEach(function (r) { observer.observe(r, OBS); });
    schedule();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})(globalThis);
