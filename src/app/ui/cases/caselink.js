/* 案件の画面へのリンクと切り抜きの校正の進み(ホームの案件の一覧 portal.js と案件の画面 cases.js の両方が読む。/cases-caselink.js)。
   URL: /cases?c=<案件 id>&d=<文書 id>&m=<マーク id>#cand|proof|cut(c・d・m はあるものだけ・この順)。v=<動画のパス> は案件の画面が読むだけ。
   校正の進みは ④ の transcript {segments, proofed}(どちらも数)だけで決める。札の言葉と形は画面ごと */
(function () {
  'use strict';
  var TABS = { cand: 1, proof: 1, cut: 1 };

  window.CaseLink = {
    TABS: TABS,
    /* {c, d, m, tab} -> '/cases?…#tab'(tab が無い・知らない物は proof) */
    href: function (o) {
      var q = [];
      if (o.c) q.push('c=' + encodeURIComponent(o.c));
      if (o.d) q.push('d=' + encodeURIComponent(o.d));
      if (o.m) q.push('m=' + encodeURIComponent(o.m));
      return '/cases' + (q.length ? '?' + q.join('&') : '') + '#' + (TABS[o.tab] ? o.tab : 'proof');
    },
    /* location -> {c, d, m, v, tab}(無い物は ''。tab は知っている物だけ) */
    parse: function (loc) {
      var q = new URLSearchParams(loc.search), h = loc.hash.replace(/^#/, '');
      return { c: q.get('c') || '', d: q.get('d') || '', m: q.get('m') || '', v: q.get('v') || '', tab: TABS[h] ? h : '' };
    },
    /* 文字起こし(④ の transcript か null)-> 'none'(文字起こし前・行なし)| 'todo' | 'proofing' | 'proofed' */
    txProgress: function (t) {
      if (!t || !(t.segments > 0)) return 'none';
      if (t.proofed >= t.segments) return 'proofed';
      return t.proofed > 0 ? 'proofing' : 'todo';
    }
  };
})();
