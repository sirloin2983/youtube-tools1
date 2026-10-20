/* スタジオの部品(review.js・rank.js・queue.js・collab.js)が使う window.Studio の代わりのうち、2 つのパネル(panels/cand.js・panels/new.js)で同じ部分。
   スタジオ単体の画面(core.js)はもう無いので、部品はパネルが渡すこの Studio の上で動く。パネルごとに違う物(API の口・段の切り替え・設定を開く先・ライブ・片付け)は
   create の返事に Object.assign で足す。window.StudioShim.create(o) -> Studio(emit・fireReady も持つ)。
   o = { label: 失敗の知らせの頭('候補のパネル')・api(path, opt): スタジオの API・homeOffline: ホームにつながらないときの文(省略可)・
         params: パネルが開くときに受けた引数・isDead(): 片付け済みか } */
(function () {
  'use strict';
  var esc = UIKit.esc;
  window.StudioShim = {
    create: function (o) {
      var subs = {}, readyFns = [], tokenTag = document.head.querySelector('meta[name="ytt-token"]');
      function guard(fn, arg, what) { try { fn(arg); } catch (e) { UIKit.report(o.label + what + ': ' + (e && e.message), { stack: e && e.stack }); } }
      var Studio = {
        esc: esc, token: tokenTag ? tokenTag.content : '', state: null, step: '', review: null, params: o.params || {}, ready: false,
        fmtTime: function (t) { return UIKit.fmt.dur(t, { tenths: true }); },
        url: function (p) { return 'studio/' + String(p).replace(/^\/+/, ''); },
        api: o.api,
        portalApi: function (path, body) { return UIKit.homeApi(path, { body: body, offline: o.homeOffline }); },
        toast: function (msg, ms, kind) { return ms && typeof ms === 'object' ? UIKit.toast(msg, ms) : UIKit.toast(msg, { ms: ms || undefined, kind: kind }); },
        showErr: function (msg) { UIKit.toast(String(msg), { ms: 0, kind: 'err' }); },
        why: function (b, why, okTitle) { b.disabled = !!why; b.title = why || okTitle || ''; if (why) b.setAttribute('data-ui-why', why); else b.removeAttribute('data-ui-why'); },
        ago: function (ms) { return UIKit.fmt.ago(ms); },
        date: function (ms) { return UIKit.fmt.date(ms); },
        isVideoId: function (s) { return /^[\w-]{11}$/.test(s || ''); },
        watchUrl: function (id, t) { return 'https://www.youtube.com/watch?v=' + encodeURIComponent(id) + (t >= 1 ? '&t=' + Math.floor(t) + 's' : ''); },
        matchWords: function (words, hay) { return String(words || '').trim().toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return String(hay).toLowerCase().indexOf(w) >= 0; }); },
        groupBy: function (list, key) { var m = new Map(); list.forEach(function (x) { var k = key(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x); }); return m; },
        /* 入力中か: ui-kit の判定 + 時刻の欄(UIKit.timebox)。キーの判定は殻が先にするので、ここは部品の中の確かめ用 */
        isTyping: function (el) { return !!el && ((el.classList && el.classList.contains('ui-time')) || UIKit.keys.isTyping(el)); },
        on: function (name, fn) { (subs[name] = subs[name] || []).push(fn); },
        onReady: function (fn) { if (Studio.ready) fn(); else readyFns.push(fn); },
        emit: function (name, detail) { (subs[name] || []).slice().forEach(function (fn) { guard(fn, detail, 'で失敗しました'); }); },
        /* 部品を読み終えた: onReady に登録された初期化を流す(画面を作る・見張り・設定を読む) */
        fireReady: function () { Studio.ready = true; readyFns.splice(0).forEach(function (fn) { guard(fn, undefined, 'の初期化に失敗しました'); }); },
        refreshState: function () {
          return Studio.api('/api/state').then(function (st) { if (o.isDead()) return st; Studio.state = st; Studio.emit('state', st); return st; });
        },
        /* 作業データ(data.json)の読み込みの問題(起動のあと 1 回だけ /api/state に載る)。帯に文だけ出す */
        dataWarning: function (box) {
          var w = Studio.state && Studio.state.dataWarning;
          if (!box) return;
          box.hidden = !w;
          if (w && !box.childElementCount) box.innerHTML = '<div><b>スタジオの作業データの読み込みで問題がありました</b><br>' + esc(w) + '</div>';
        }
      };
      return Studio;
    }
  };
})();
