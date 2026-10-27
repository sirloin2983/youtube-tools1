/* 案件の画面(/cases = 入口の直下の 1 枚。部品は src/app/ui/cases/。RS8 C1 = 殻。作り方 資料の git:before-1028-cleanup:docs/design/rs8-cases-build.md・何を作るか notes:docs/design/briefs/rs8-cases/)。
   URL: /cases?c=<案件 id>&d=<文書 id>#cand|proof|cut。d だけでも開ける(④ に ?doc= で案件を聞く)。
     v=<動画のパス> だけでも開ける(編集の api/doc-for で文書を引く。無ければホームの新しい案件の欄 /#new?media=)。
     文字起こしがまだの切り抜きは d の代わりに m=<マーク id>。根のパスは URL に出さない。
   読む口: 案件の中身 = ④ GET api/cases(?doc=)/ 今動いている物 = ② GET api/flow/status?case=<根>(動いていれば 2 秒・止まっていれば 15 秒。rev が同じなら描き直さない)。
   殻が持つ物: ヘッダー・URL の読み書き(replaceState)・左の一覧・タブ・「次の未校正の切り抜き」・keydown 1 本・UIKit.life・問い合わせ。
   CSP(script-src 'self')の下で動く: インラインの script・on〇〇= は書かない。API の URL は ctx.api / api() の 1 か所で相対に組む。

   ---- パネルの口(C2 の 3 本 = panels/cand.js・proof.js・cut.js が同じ形で作る)----
   CasesPanels.define(id, create)   id = 'cand' | 'proof' | 'cut'。create() が新しいパネルを 1 つ返す(タブを開くたびに作り直す。確かめる V1 のカードも同じ create で作る)
   パネル = {
     id,
     mount(el, ctx)    el = 右の欄(パネルだけの入れ物。中の要素は el.querySelector で引く = document.getElementById・document.querySelector は使わない)
     update(ctx)       左の一覧で同じタブのまま別の物を選んだ・② の status が変わった(rev)・④ を読み直した。ctx は毎回新しい物
     unmount()         タブを離れる・別の物を選んでタブが変わる(再生を止め・保存を flush・自分で付けた見張りを外す)。el は殻が空にする
     keys(e) -> bool   殻の keydown から今のパネルに 1 回だけ。使ったら true(殻が preventDefault)。入力中(UIKit.keys.isTyping)・変換中は渡さない
                       (typingKeys: true を持つパネルだけ入力中も渡す)。殻が先に取るキー: Alt+1 / Alt+2(タブ)・Shift+N(次の未校正の切り抜き)
     keybar() -> [{k, l}]   下の帯(UIKit.keybar)のパネルの分。殻が自分の分を後ろに足す。変わったら ctx.refreshKeys()
     leave(reason)     (任意)画面を離れた(UIKit.life)。'blur' = 隣の窓へ → 保存だけ / 'hidden'・'pagehide' → 再生も止める
     back(reason)      (任意)画面に戻った
     typingKeys        (任意)true なら入力中のキーも keys に渡す
   }
   ctx = { caseId, caseKind('stream'|'live'|'file'|'eval'|'orphan'), root(案件の根 = ② の case。無ければ null), videoId(スタジオの配信 id。無ければ null),
           docId(文書 id か null), markId(マーク id か null), item(左の一覧の 1 行 = {key, kind:'cand'|'clip', n, label, sub, state, clip, tx}),
           case(④ の案件の行そのまま), status: {rev, jobs(② の Job をこの物に絞った物), all(この案件の Job 全部)},
           api(tool, path, opt)(tool = 'home'|'studio'|'transcribe'|'cut2resolve'。UIKit.http の包み = 合言葉・失敗の形は ui-kit のまま),
           onDone()(この切り抜きが済んだ → 次の未校正の切り抜きへ), setHint(text)(タブの横の短い説明), refreshKeys(), reload()(④ を読み直す) }
   文書の保存の受け渡し(RS8 C4): 校正(編集の S)とカット・パック(panels/cut.js の S)は同じ文書を別々に持つ。閉じるパネルは送り始めた保存を
   CasesPanels.track(promise) に渡し、開くパネルは文書を読む前に CasesPanels.settled() を待つ(タブを素早く切り替えても、前のパネルの保存より前の文書を読まない) */
(function () {
  'use strict';

  /* ---- パネルの登録の口(パネルのファイルはこのあとに読む。DOMContentLoaded までに全部そろう)---- */
  var defs = {}, saving = [];
  var SETTLE_MAX_MS = 15000;   // 保存の答えが来ないときも、ここまで待ったら読む(固まらない。読んだ文書が古ければ保存の 409 の案内になる)
  window.CasesPanels = {
    define: function (id, create) { if (typeof create === 'function') defs[id] = create; },
    track: function (p) {
      if (!p || typeof p.then !== 'function') return p;
      saving.push(p);
      var drop = function () { var i = saving.indexOf(p); if (i >= 0) saving.splice(i, 1); };
      p.then(drop, drop);
      return p;
    },
    settled: function () {
      if (!saving.length) return Promise.resolve();
      var all = Promise.all(saving.map(function (p) { return p.then(null, function () { /* 失敗も「終わった」*/ }); }));
      return Promise.race([all, new Promise(function (r) { setTimeout(r, SETTLE_MAX_MS); })]);
    },
    create: function (id) {
      var f = defs[id], p = f ? f() : null;
      if (p && !p.id) p.id = id;
      return p;
    },
    /* C1 の空のパネル(C2 で中身に替わるまでの案内)。ctx から「何の作業の欄か」と今の画面への行き先を出す */
    stub: function (ctx, o) {
      var it = ctx.item || {}, rows = [];
      for (var i = 0; i < (o.facts || []).length; i++) {
        var f = o.facts[i];
        if (f && f[1] !== '' && f[1] != null) rows.push('<dt>' + esc(f[0]) + '</dt><dd>' + esc(f[1]) + '</dd>');
      }
      var jobs = (ctx.status && ctx.status.jobs) || [], jl = '';
      for (var j = 0; j < jobs.length; j++) jl += '<li>' + jobPill(jobs[j]) + '<span>' + esc(jobs[j].title || KIND_TEXT[jobs[j].kind] || jobs[j].kind) + '</span></li>';
      return '<div class="cs-stub" data-cs-stub="' + esc(o.id) + '"><p><b>' + esc(o.title) + '</b></p><p class="hint">' + esc(o.text) + '</p>' +
        (rows.length ? '<dl>' + rows.join('') + '</dl>' : '') +
        (jl ? '<p class="hint">この' + (it.kind === 'cand' ? '配信' : '切り抜き') + 'で動いている物・終わった物</p><ul class="cs-jobs">' + jl + '</ul>' : '') +
        (o.href ? '<div class="row"><a class="btn small" href="' + esc(o.href) + '">' + esc(o.link) + '</a></div>' : '') + '</div>';
    }
  };

  var esc = UIKit.esc;
  var $ = function (s) { return document.querySelector(s); };
  var TABS = { cand: { label: '候補', n: 1 }, proof: { label: '校正', n: 1 }, cut: { label: 'カット・パック', n: 2 } };
  var NO_CAND = { file: 1, eval: 1, orphan: 1 };   // 候補(配信全体)の無い案件 = 動画ファイル 1 本・仮の案件
  var PSEUDO = { eval: '評価用', orphan: 'どの案件にも入らない文字起こし' };
  var TOOL_BASE = { home: '', studio: 'studio/', transcribe: 'transcribe/', cut2resolve: 'cut2resolve/' };
  var POLL_ACTIVE = 2000, POLL_IDLE = 15000;
  var ACTIVE = { queued: 1, running: 1 };
  var KIND_TEXT = { run: 'まとめて実行', analyze: '解析', adopt: '採用', 'export': '書き出し', transcribe: '文字起こし', diarize: '話者の判別', pack: 'パック',
    deliver: '届ける', rerun: '再認識', search: '配信の検索', live_export: 'ライブの書き出し', live_archive: 'アーカイブで作り直し', live_tx: '配信中の文字起こし' };
  /* 切り抜きの進み具合(④ の clips[].state。C0)→ 札の title(校正はユーザーがしないので、札の文字は友人へ渡したか = deliveryPill。10-24 画面の見直し)。
     無ければ文書の校正済みの行の数とパックの有無から殻が読む */
  var STATE_PILL = { none: ['wait', '文字起こし前'], todo: ['', '未校正'], proofing: ['accent', '校正中'], proofed: ['ok', '校正済み'], packed: ['ok', 'パック済み'] };
  var LOAD_TEXT = { offline: 'ホームにつながりませんでした(start.bat の黒い画面が閉じていないか確かめてください)' };

  var S = {
    want: null,          // URL で頼まれた物 {c, d, m, tab}
    data: null,          // ④ の応答
    kase: null,          // 今の案件の行
    sw: 0,               // 案件を切り替えた回数(別の案件・案件なしへ変わるたびに +1。同じ案件の読み直しでは増えない)
    items: [],           // 左の一覧
    sel: '',             // 選んだ行の key
    tab: '',
    panel: null, panelTab: '', panelKey: '',
    status: { rev: null, all: [] },
    railHtml: '', timer: 0, pollMs: 0, noCaseFilter: false, loading: false, checkN: 0, checkAt: 0
  };

  /* ---- API(相対パス。/cases は入口の直下なので '' = 入口・'studio/' = 取り込んだスタジオ)---- */
  function api(tool, path, opt) {
    if (!Object.prototype.hasOwnProperty.call(TOOL_BASE, tool)) return Promise.reject(new Error('知らないツールです: ' + tool));
    var url = new URL(TOOL_BASE[tool] + String(path == null ? '' : path).replace(/^\/+/, ''), location.href).href;
    return UIKit.http(url, Object.assign({ timeout: 30000 }, LOAD_TEXT, opt || {}));
  }

  /* ---- URL ---- */
  /* 引数なしで開いたとき(ヘッダーの「案件」= RS8 C4)は、前に開いていた案件を開く(この PC のこのブラウザだけの覚え。読めなければ空の状態)*/
  var LAST_KEY = 'ytt-cases-last';
  function lastCase() { try { var v = localStorage.getItem(LAST_KEY) || ''; return /^[\w:.-]{1,80}$/.test(v) ? v : ''; } catch (e) { return ''; } }
  function rememberCase(id) { try { if (id) localStorage.setItem(LAST_KEY, id); else localStorage.removeItem(LAST_KEY); } catch (e) { /* 覚えられなくてよい */ } }
  function readUrl() {
    var w = CaseLink.parse(location);   // URL の形は caselink.js の 1 か所(ホームのリンクと同じ)
    if (!w.c && !w.d && !w.v) { w.c = lastCase(); w.last = !!w.c; }
    return w;
  }
  /* ?v=<動画のパス>(c も d も無いとき。スタジオ ② の「編集で開く」= 棚卸し G5): 編集の口でその動画の文書を引いて開く(URL は writeUrl が ?c=&d= に直す)。
     文書が無い・引けないときは、ホームの新しい案件の動画ファイルの欄へ */
  function openMedia(w) {
    var toNew = function () { location.replace('./#new?media=' + encodeURIComponent(w.v)); };
    return api('transcribe', 'api/doc-for?path=' + encodeURIComponent(w.v)).then(function (j) {
      var id = j && j.doc && typeof j.doc.id === 'string' ? j.doc.id : '';
      if (!id) return toNew();
      S.want = { c: '', d: id, m: '', tab: w.tab || 'proof' };
      return load(false);
    }, toNew);
  }
  function writeUrl() {
    var q = new URLSearchParams(), it = curItem();
    if (S.kase) { q.set('c', S.kase.id); rememberCase(S.kase.id); }
    if (it && it.docId) q.set('d', it.docId);
    else if (it && it.markId) q.set('m', it.markId);
    var qs = q.toString(), url = location.pathname + (qs ? '?' + qs : '') + (S.tab ? '#' + S.tab : '');
    if (url !== location.pathname + location.search + location.hash) history.replaceState(null, '', url);
  }

  /* ---- ④ の案件の行 → 左の一覧 ---- */
  function caseKind(c) {
    if (!c) return '';
    var k = c.caseKind || '';
    if (k === 'stream' && c.kind === 'live') return 'live';
    /* スタジオに動画ファイルとして開いた配信(スタジオの kind file)は解析・マークがある = 候補のタブを出す(RS8 C4。古いスタジオの画面の代わり)。
       候補の無い「動画ファイル 1 本」の案件は、スタジオに無い案件(④ の case.json。kind が空)だけ */
    if (k === 'file' && c.kind === 'file') return 'stream';
    return k || (c.kind === 'live' ? 'live' : c.kind === 'file' ? 'file' : PSEUDO[c.id] ? c.id : 'stream');
  }
  /* 送らなかった理由の文(自動の切り抜き。review.notSent.code → 文。text が来ていればそれを優先)。文はこの 1 か所だけ */
  var NOT_SENT = { unchecked: 'チェックを外した', stale: '古い配信', requested: '友人の依頼あり', expired: '古くなった', unknown_end: '終わった時刻が分からない' };
  function notSentText(ns) { return (ns && ns.text) || NOT_SENT[ns && ns.code] || '理由が分かりません'; }   // 札「送れなかった」の title(deliveryOf)
  function clipState(cl) {
    var tx = cl.transcript || null, st = typeof cl.state === 'string' ? cl.state : '';
    if (st === 'proofing' && tx && !(tx.proofed > 0)) return 'todo';   // C0 の proofing は「校正済みが足りない」= 1 行も済んでいなければ未校正
    if (STATE_PILL[st]) return st;
    if (cl.pack) return 'packed';
    return CaseLink.txProgress(tx);
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function itemsOf(c) {
    var out = [], kind = caseKind(c), seen = {};
    if (!NO_CAND[kind]) {
      var mk = c.marks || {};
      out.push({ key: 'cand', kind: 'cand', n: 0, label: '候補(配信全体)', sub: '候補 ' + (mk.candidates || 0) + ' ・ 採用 ' + (mk.adopted || 0) + ' ・ 書き出し ' + (mk.exported || 0) });
    }
    var clips = Array.isArray(c.clips) ? c.clips : [];
    for (var i = 0; i < clips.length; i++) {
      var cl = clips[i] || {}, tx = cl.transcript || null, docId = tx && tx.id ? String(tx.id) : '', markId = cl.markId ? String(cl.markId) : '';
      var len = typeof cl.start === 'number' && typeof cl.end === 'number' && cl.end > cl.start ? Math.round(cl.end - cl.start) + ' 秒' : '';
      var label = typeof cl.start === 'number' ? pad2(i + 1) + ' ' + UIKit.fmt.dur(cl.start) : (cl.label || (tx && tx.title) || cl.file || '切り抜き ' + (i + 1));
      var sub = [len, typeof cl.start === 'number' ? cl.label : (tx && tx.title !== label ? tx.title : '')].filter(Boolean).join(' ・ ');
      var key = docId ? 'd:' + docId : 'm:' + (markId || String(i));
      if (seen[key]) continue;
      seen[key] = 1;
      out.push({ key: key, kind: 'clip', n: i + 1, docId: docId, markId: markId, label: label, sub: sub || (tx ? (tx.segments || 0) + ' 行' : '文字起こしはまだ'),
                 state: clipState(cl), clip: cl, tx: tx });
    }
    return out;
  }
  function allCases(j) {
    var list = [];
    if (j && j.case && typeof j.case === 'object') list.push(j.case);
    if (j && Array.isArray(j.cases)) list = list.concat(j.cases);
    if (j && Array.isArray(j.virtual)) list = list.concat(j.virtual);
    if (j && Array.isArray(j.unlinked) && !list.some(function (c) { return c && c.id === 'orphan'; })) {   // ④ に仮の案件がまだ無いとき(C0 の前)の代わり
      list.push({ id: 'orphan', caseKind: 'orphan', title: PSEUDO.orphan, clips: j.unlinked.map(function (t) { return { transcript: t, label: t.title, path: t.sourcePath || '' }; }) });
    }
    return list.filter(function (c) { return c && typeof c.id === 'string'; });
  }
  function hasDoc(c, d) {
    return (c.clips || []).some(function (cl) { return (cl.transcript && cl.transcript.id === d) || (cl.transcriptIds || []).indexOf(d) >= 0; });
  }
  function pickCase(list, w) {
    if (w.c) return list.filter(function (c) { return c.id === w.c; })[0] || null;
    if (w.d) return list.filter(function (c) { return hasDoc(c, w.d); })[0] || null;
    return null;
  }
  function curItem() { return S.items.filter(function (x) { return x.key === S.sel; })[0] || null; }
  function isUnproofed(it) { return it.kind === 'clip' && !!it.docId && (it.state === 'todo' || it.state === 'proofing'); }

  /* ---- ② の Job をこの行に絞る ---- */
  function normPath(p) { return String(p || '').replace(/\\/g, '/').toLowerCase(); }
  function jobsFor(it) {
    var all = S.status.all || [];
    if (!it) return [];
    return all.filter(function (j) {
      var t = j.target || {};
      if (it.kind === 'cand') return !t.docId && !t.markId && (!t.videoId || t.videoId === S.kase.id) && j.kind !== 'transcribe' && j.kind !== 'pack';
      return (it.docId && t.docId === it.docId) || (it.markId && t.markId === it.markId) || (t.path && it.clip && it.clip.path && normPath(t.path) === normPath(it.clip.path));
    });
  }
  function mine(j) {   // 案件の根が無い(④ が root を返さない)ときの絞り方: 配信 id・この案件の文書・マーク
    var t = j.target || {};
    if (t.videoId && t.videoId === S.kase.id) return true;
    return S.items.some(function (it) { return (it.docId && t.docId === it.docId) || (it.markId && t.markId === it.markId); });
  }
  function jobPill(j) {
    if (ACTIVE[j.state]) {
      var pct = typeof j.progress === 'number' ? ' ' + Math.round(j.progress * 100) + '%' : '';
      return '<span class="pill run" data-ui-audit-allow="A-33" title="' + esc(j.phase || j.stateLabel || '') + '">' + esc((KIND_TEXT[j.kind] || j.kind) + (j.waiting ? ' 待ち' : pct)) + '</span>';
    }
    if (j.state === 'error') return '<span class="pill err" data-ui-audit-allow="A-33" title="' + esc((j.error && j.error.text) || '') + '">' + esc((KIND_TEXT[j.kind] || j.kind) + 'に失敗') + '</span>';
    return '<span class="pill" data-ui-audit-allow="A-33">' + esc(j.stateLabel || j.state) + '</span>';
  }

  /* ---- 描く ---- */
  function pillOf(it) {
    var jobs = jobsFor(it), act = jobs.filter(function (j) { return ACTIVE[j.state]; })[0];
    var err = jobs.filter(function (j) { return j.state === 'error'; }).pop();
    if (act) return jobPill(act);
    if (err) return jobPill(err);
    if (it.kind !== 'clip') return '';
    var d = deliveryOf(it.clip), tip = [proofText(it)].concat(d[2] ? [d[2]] : []).join(' ・ ');
    return '<span class="pill ' + d[0] + '" data-ui-audit-allow="A-33" data-cs-deliver="' + d[3] + '" data-cs-proof="' + esc(it.state || 'none') + '" title="' + esc(tip) + '">' + esc(d[1]) + '</span>';
  }
  /* 札の文字 = 友人へ渡したか(④ の clip.review。届けた記録 deliveredAt・失敗の文 failure・送らなかった理由 notSent。review は自動の切り抜きだけに付く)
     -> [札の色, 文字, title に足す理由, data-cs-deliver] */
  function deliveryOf(cl) {
    var rv = (cl && cl.review) || {};
    if (rv.deliveredAt) return ['ok', '友人へ渡した', rv.deliveredAt > 1 ? '渡した日時 ' + UIKit.fmt.date(rv.deliveredAt) : '', 'done'];
    if (rv.failure || rv.notSent) return ['warn', '送れなかった', rv.notSent ? '送らなかった理由: ' + notSentText(rv.notSent) : String(typeof rv.failure === 'string' ? rv.failure : (rv.failure && rv.failure.text) || ''), 'fail'];
    return ['', 'まだ', '', 'none'];
  }
  /* 札の title = 校正の進み具合(校正 7/25 など)*/
  function proofText(it) {
    if (it.state === 'proofing' && it.tx && it.tx.segments) return '校正 ' + it.tx.proofed + '/' + it.tx.segments;
    return (STATE_PILL[it.state] || STATE_PILL.none)[1];
  }
  function renderRail() {
    var html = '', clipSep = false;
    for (var i = 0; i < S.items.length; i++) {
      var it = S.items[i];
      if (it.kind === 'clip' && !clipSep) { html += '<div class="ui-rail-sep">切り抜き</div>'; clipSep = true; }
      html += '<button type="button" class="ui-rail-item" data-cs-key="' + esc(it.key) + '" aria-current="' + (it.key === S.sel) + '" title="' + esc(it.label + (it.sub ? ' ・ ' + it.sub : '')) + '">' +
        '<span class="ui-rail-t"><b>' + esc(it.label) + '</b><span class="ui-rail-s">' + esc(it.sub || '') + '</span></span>' + pillOf(it) + '</button>';
    }
    if (!clipSep) html += '<div class="ui-rail-sep">切り抜き</div><p class="hint cs-rail-none">' + (NO_CAND[caseKind(S.kase)] ? 'この案件にはまだ文字起こしがありません。' : 'まだ書き出した切り抜きはありません。候補を採用して書き出すと、ここに 1 本 1 行で出ます。') + '</p>';
    if (html === S.railHtml) return;   // 変わっていなければ描き直さない(フォーカス・スクロールを保つ)
    var rail = $('#csRail'), focused = document.activeElement && rail.contains(document.activeElement) ? document.activeElement.getAttribute('data-cs-key') : null;
    rail.innerHTML = html;
    S.railHtml = html;
    if (focused) { var b = rail.querySelector('[data-cs-key="' + CSS.escape(focused) + '"]'); if (b) b.focus(); }
  }
  function tabsOf(it) { return !it ? [] : it.kind === 'cand' ? ['cand'] : ['proof', 'cut']; }
  function renderTabs() {
    var ts = tabsOf(curItem()), html = '';
    for (var i = 0; i < ts.length; i++) {
      var t = TABS[ts[i]];
      html += '<button type="button" class="ui-tab" role="tab" data-cs-tab="' + ts[i] + '" aria-selected="' + (ts[i] === S.tab) + '" title="' + esc(t.label + '(Alt+' + (i + 1) + ')') + '">' +
        '<span class="ui-tab-n">' + (i + 1) + '</span>' + esc(t.label) + '</button>';
    }
    $('#csTabs').innerHTML = html;
  }
  function nextTarget() {
    var list = S.items, at = list.indexOf(curItem());
    for (var k = 1; k <= list.length; k++) {
      var it = list[(Math.max(at, 0) + k) % list.length];
      if (it && it.key !== S.sel && isUnproofed(it)) return it;
    }
    return null;
  }
  function renderNext() {
    var b = $('#csNext'), nx = S.kase ? nextTarget() : null;   // 押せないとき(次が無い・案件が無い)は出さない(10-24 画面の見直し)
    b.hidden = !nx;
    b.disabled = !nx;
    b.title = nx ? '「' + nx.label + '」を開きます(Shift+N)' : '';
  }
  /* 確かめると効く物 n 件(V1 確かめる V3)。入口の GET api/check/next?c=<案件>&n=0 の total。殻の問い合わせ(poll)に合わせて 15 秒ごと(案件を開いたときにも 1 回)。
     0 件・読めないときは出さない。押すと /check?c=<案件>&back=cases(終わったら案件へ戻るボタンが出る) */
  var CHECK_EVERY_MS = 14000;
  function renderCheckLink() {
    var a = $('#csCheck'), n = S.checkN, c = S.kase;
    a.hidden = !(c && n > 0 && /^[A-Za-z0-9_-]{1,64}$/.test(c.id));
    if (a.hidden) return;
    a.textContent = '確かめると効く物 ' + n + ' 件';
    a.href = 'check?c=' + encodeURIComponent(c.id) + '&back=cases';
    a.title = 'この案件の、人が確かめると効く物(切り抜く価値・読み・誰の声・時刻)を 1 枚ずつ見ます';
  }
  function loadCheckCount() {
    var kase = S.kase;
    S.checkAt = Date.now();
    if (!kase || !/^[A-Za-z0-9_-]{1,64}$/.test(kase.id)) { S.checkN = 0; renderCheckLink(); return; }
    api('home', 'api/check/next?c=' + encodeURIComponent(kase.id) + '&n=0', { timeout: 15000 }).then(function (j) {
      if (S.kase !== kase) return;
      S.checkN = j && j.total > 0 ? j.total : 0;
      renderCheckLink();
    }, function () { if (S.kase === kase) { S.checkN = 0; renderCheckLink(); } });   // 数が読めないだけ(画面の仕事は止めない)
  }
  function renderHead() {
    var c = S.kase, kind = caseKind(c);
    var title = c ? (PSEUDO[kind] && !c.title ? PSEUDO[kind] : (c.title || c.id)) : '案件';
    $('#csTitle').textContent = title;
    document.title = '動画編集ツール — ' + title;
    var sub = [];
    if (c) {
      if (kind === 'live') sub.push('ライブの録画');
      if (kind === 'file') sub.push('動画ファイル');
      if (PSEUDO[kind]) sub.push('仮の案件');
      if (c.channel) sub.push(c.channel);
      if (c.streamedAt && !PSEUDO[kind]) sub.push(UIKit.fmt.day(c.streamedAt));
      var clips = (c.clips || []).length;
      sub.push('切り抜き ' + clips + ' 本');
      if (c.gone) sub.push('スタジオから消えた配信(候補は見られません)');
    }
    $('#csSub').textContent = sub.join(' ・ ');
    renderCheckLink();
  }

  /* ---- パネル ---- */
  function ctxFor(it) {
    var c = S.kase, kind = caseKind(c), jobs = jobsFor(it);
    return {
      caseId: c.id, caseKind: kind, root: c.root || null, videoId: NO_CAND[kind] ? null : (c.videoId || c.id),
      docId: it.docId || null, markId: it.markId || null, item: it, case: c,
      status: { rev: S.status.rev, jobs: jobs, all: S.status.all || [] },
      api: api, onDone: goNext, reload: function () { return load(true); },
      setHint: function (text) { $('#csHint').textContent = text || ''; },
      refreshKeys: renderKeybar
    };
  }
  function unmountPanel() {
    if (!S.panel) return;
    try { if (S.panel.unmount) S.panel.unmount(); } catch (e) { UIKit.report('パネルを閉じられませんでした: ' + (e && e.message), { stack: e && e.stack }); }
    S.panel = null; S.panelTab = ''; S.panelKey = '';
    $('#csPane').innerHTML = '';
  }
  function showPanel(force) {
    var it = curItem(), el = $('#csPane');
    if (!it) { unmountPanel(); return; }
    var ctx = ctxFor(it);
    if (S.panel && S.panelTab === S.tab) {
      if (force || S.panelKey !== it.key) $('#csHint').textContent = '';
      S.panelKey = it.key;
      try { if (S.panel.update) S.panel.update(ctx); } catch (e) { UIKit.report('パネルを描き直せませんでした: ' + (e && e.message), { stack: e && e.stack }); }
    } else {
      unmountPanel();
      $('#csHint').textContent = '';
      var p = window.CasesPanels.create(S.tab);
      if (!p) { el.innerHTML = '<div class="empty"><b>この作業の欄を読み込めませんでした</b><span>画面を読み込み直してください。直らなければ、ホームの「すべて終了」から start.bat で起動し直してください。</span></div>'; return; }
      S.panel = p; S.panelTab = S.tab; S.panelKey = it.key;
      try { p.mount(el, ctx); } catch (e) { UIKit.report('パネルを開けませんでした: ' + (e && e.message), { stack: e && e.stack }); }
    }
    renderKeybar();
  }
  function renderKeybar() {
    var own = [];
    try { own = (S.panel && S.panel.keybar && S.panel.keybar()) || []; } catch (e) { own = []; }
    var ts = tabsOf(curItem()), shell = [];
    if (ts.length > 1) shell.push({ k: 'Alt+1', l: TABS[ts[0]].label }, { k: 'Alt+2', l: TABS[ts[1]].label });
    if (S.kase && nextTarget()) shell.push({ k: 'Shift+N', l: '次の未校正の切り抜き' });   // ボタンと同じく、次が無いときは出さない
    UIKit.keybar.set(own.concat(shell));
  }

  /* ---- 選ぶ ---- */
  function select(key, tab) {
    var it = S.items.filter(function (x) { return x.key === key; })[0];
    if (!it) return false;
    var ts = tabsOf(it);
    S.sel = key;
    S.tab = ts.indexOf(tab) >= 0 ? tab : ts.indexOf(S.tab) >= 0 ? S.tab : ts[0];
    renderRail();
    renderTabs();
    renderNext();
    showPanel(false);
    writeUrl();
    return true;
  }
  function setTab(t) {
    if (tabsOf(curItem()).indexOf(t) < 0 || t === S.tab) return;
    S.tab = t;
    renderTabs();
    showPanel(false);
    writeUrl();
  }
  function goNext() {
    var nx = nextTarget();
    if (!nx) { UIKit.toast('この案件に、ほかの未校正の切り抜きはありません', { kind: 'info' }); return; }
    select(nx.key, 'proof');
    var b = $('#csRail [aria-current="true"]');
    if (b && b.scrollIntoView) b.scrollIntoView({ block: 'nearest' });
  }
  function defaultKey(w) {
    var byDoc = w.d && S.items.filter(function (x) { return x.docId === w.d; })[0];
    if (byDoc) return byDoc.key;
    var byMark = w.m && S.items.filter(function (x) { return x.markId === w.m; })[0];
    if (byMark) return byMark.key;
    if (w.tab === 'proof' || w.tab === 'cut') {
      var un = S.items.filter(isUnproofed)[0] || S.items.filter(function (x) { return x.kind === 'clip'; })[0];
      if (un) return un.key;
    }
    return S.items[0] ? S.items[0].key : '';
  }

  /* ---- 空の状態・失敗 ---- */
  function showEmpty(html) {
    unmountPanel();
    $('#csWrap').hidden = true;
    var e = $('#csEmpty');
    e.innerHTML = html;
    e.hidden = false;
    renderNext();
    UIKit.keybar.clear();
  }
  function emptyBox(title, text, acts) {
    return '<div class="empty"><b>' + esc(title) + '</b><span>' + esc(text) + '</span><div class="row">' + acts + '</div></div>';
  }
  var HOME_BTN = '<a class="btn primary small" href="./">ホームの案件の一覧へ</a>';
  function showFail(e) {
    var det = e && (e.detail || e.message) ? '<details class="ui-disclosure"><summary>詳しく</summary><p class="hint">' + esc(e.detail || '') + ' ' + esc(e.reason || '') + '</p></details>' : '';
    showEmpty('<div class="empty" data-cs-fail><b>案件を読み込めませんでした</b><span>' + esc((e && e.message) || '') + '</span>' +
      '<div class="row"><button type="button" class="btn primary small" id="csRetry">もう一度読み込む</button><a class="btn small" href="./">ホームへ</a></div>' + det + '</div>');
    $('#csRetry').addEventListener('click', function () { load(false); });
  }

  /* ---- 読む ---- */
  function fetchCases(w) {
    if (w.c || !w.d) return api('home', 'api/cases', { timeout: 60000 });
    return api('home', 'api/cases?doc=' + encodeURIComponent(w.d), { timeout: 60000 }).then(function (j) {
      return j && (j.case || Array.isArray(j.cases)) ? j : api('home', 'api/cases', { timeout: 60000 });
    }, function (e) {   // ?doc= を知らない入口・その文書の案件が無い(404)= 一覧から探す
      if (e && (e.status === 404 || e.status === 400)) return api('home', 'api/cases', { timeout: 60000 });
      throw e;
    });
  }
  function load(keep) {
    if (S.loading) return Promise.resolve();
    S.loading = true;
    var w = keep && S.kase ? { c: S.kase.id, d: (curItem() || {}).docId || '', m: (curItem() || {}).markId || '', tab: S.tab } : S.want;
    if (!w.c && !w.d) {
      S.loading = false;
      renderHead();
      showEmpty(emptyBox('案件が選ばれていません', 'ホームの案件の一覧から開くと、ここに候補と切り抜きが出ます。', HOME_BTN));
      return Promise.resolve();
    }
    return fetchCases(w).then(function (j) {
      S.loading = false;
      S.data = j;
      var c = pickCase(allCases(j), w);
      if (!c && w.last) {   // 覚えていた案件が無くなった = 引数なしで開いたのと同じ(覚えを捨てる)
        rememberCase(''); S.want = { c: '', d: '', m: '', tab: '' };
        S.kase = null; S.sw++;
        renderHead();
        return showEmpty(emptyBox('案件が選ばれていません', 'ホームの案件の一覧から開くと、ここに候補と切り抜きが出ます。', HOME_BTN));
      }
      if (!c) {
        S.kase = null; S.sw++;
        renderHead();
        return showEmpty(emptyBox('この案件は見つかりません', '消えたか、別の案件へ移った可能性があります。ホームの案件の一覧から開き直してください。', HOME_BTN));
      }
      var same = S.kase && S.kase.id === c.id;
      S.kase = c;
      if (!same) S.sw++;
      S.items = itemsOf(c);
      if (!same) { S.status = { rev: null, all: [] }; S.railHtml = ''; S.checkN = 0; S.checkAt = 0; }
      $('#csEmpty').hidden = true;
      $('#csWrap').hidden = false;
      renderHead();
      var key = keep && S.items.some(function (x) { return x.key === S.sel; }) ? S.sel : defaultKey(w);
      if (!key) {
        S.sel = ''; S.tab = '';
        renderRail(); renderTabs(); renderNext(); unmountPanel();
        $('#csPane').innerHTML = emptyBox('まだ作業できる物がありません', '切り抜きを書き出して文字起こしすると、ここで校正とカットができます。', HOME_BTN);
        renderKeybar(); writeUrl();
      } else if (keep && key === S.sel) {
        renderRail(); renderTabs(); renderNext(); showPanel(false);
      } else {
        select(key, w.tab);
      }
      if (!same) poll();
    }, function (e) {
      S.loading = false;
      if (keep && S.kase) { UIKit.toast('案件を読み直せませんでした: ' + e.message, { kind: 'err', detail: e.detail }); return; }
      renderHead();
      showFail(e);
    });
  }

  /* ---- ② の status の問い合わせ(動いていれば 2 秒・止まっていれば 15 秒。離れている間は止める)---- */
  function schedule(ms) {
    clearTimeout(S.timer);
    S.pollMs = ms;
    document.body.setAttribute('data-cs-poll', String(ms));
    S.timer = setTimeout(poll, ms);
  }
  function poll() {
    clearTimeout(S.timer);
    S.timer = 0;
    if (!S.kase || UIKit.life.isAway()) return;
    // 古い応答かどうかは「案件の ID と切り替えの番号」で比べる。同じ案件の読み直し(load(true))は S.kase を新しい物に入れ替えるので、
    // 物の同一性で比べると応答を捨てて schedule を呼ばず、自動の更新が止まる(GPT レビュー A1)。
    var kase = S.kase, id = kase.id, sw = S.sw, root = kase.root && !S.noCaseFilter ? kase.root : '';
    function stale() { return !S.kase || S.kase.id !== id || S.sw !== sw; }
    api('home', 'api/flow/status' + (root ? '?case=' + encodeURIComponent(root) : ''), { timeout: 15000 }).then(function (st) {
      if (stale()) return;
      var jobs = Array.isArray(st.jobs) ? st.jobs.filter(function (j) { return j && typeof j === 'object'; }) : [];
      if (!root) jobs = jobs.filter(mine);
      var active = jobs.some(function (j) { return ACTIVE[j.state]; });
      if (st.rev !== S.status.rev || S.status.rev === null) {
        var before = {};
        (S.status.all || []).forEach(function (j) { if (ACTIVE[j.state]) before[j.id] = 1; });
        var finished = jobs.some(function (j) { return before[j.id] && !ACTIVE[j.state]; });
        S.status = { rev: st.rev, all: jobs };
        renderRail();
        if (S.panel) showPanel(false);
        if (finished) load(true);   // 文字起こし・パックが終わった = 切り抜きの札が変わる(④ を読み直す)
      }
      if (Date.now() - S.checkAt >= CHECK_EVERY_MS) loadCheckCount();
      schedule(active ? POLL_ACTIVE : POLL_IDLE);
    }, function (e) {
      if (stale()) return;
      if (e && e.status === 400 && root) S.noCaseFilter = true;   // 根の形を断られた = 絞らずに読んで画面で絞る
      schedule(POLL_IDLE);
    });
  }

  /* ---- キー(keydown は 1 本。殻のキー → 今のパネル)---- */
  function inOverlay(t) { return !!(t && t.closest && t.closest('.ui-drawer, dialog, [role="dialog"], [aria-modal="true"]')); }
  function onKey(e) {
    if (e.defaultPrevented || e.isComposing || e.keyCode === 229) return;
    if (UIKit.keymap && UIKit.keymap.capturing && UIKit.keymap.capturing()) return;
    if (inOverlay(e.target)) return;
    var typing = UIKit.keys.isTyping(e.target);
    if (!typing && e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && (e.key === '1' || e.key === '2')) {
      var t = tabsOf(curItem())[+e.key - 1];
      if (t) { e.preventDefault(); setTab(t); UIKit.keybar.flash('Alt+' + e.key); }
      return;
    }
    if (!typing && e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'N' || e.key === 'n')) {
      if (S.kase) { e.preventDefault(); goNext(); UIKit.keybar.flash('Shift+N'); }
      return;
    }
    var p = S.panel;
    if (!p || !p.keys || (typing && !p.typingKeys)) return;
    var used = false;
    try { used = p.keys(e) === true; } catch (x) { UIKit.report('パネルのキーで失敗しました: ' + (x && x.message), { stack: x && x.stack }); }
    if (used) e.preventDefault();
  }

  /* ---- 起動 ---- */
  document.addEventListener('DOMContentLoaded', function () {
    UIKit.settings.mount({ title: '設定' });
    UIKit.homeApi('api/status', { method: 'GET', timeout: 8000 }).then(function (j) {
      if (j && j.version) { $('#ver').textContent = 'v' + j.version; if (UIKit.appnav && UIKit.appnav.setVersion) UIKit.appnav.setVersion('v' + j.version); }
    }, function () { /* 版が出ないだけ */ });
    $('#csRail').addEventListener('click', function (e) {
      var b = e.target.closest('[data-cs-key]');
      if (b) select(b.getAttribute('data-cs-key'), S.tab);
    });
    $('#csTabs').addEventListener('click', function (e) {
      var b = e.target.closest('[data-cs-tab]');
      if (b) setTab(b.getAttribute('data-cs-tab'));
    });
    $('#csNext').addEventListener('click', goNext);
    document.addEventListener('keydown', onKey);
    window.addEventListener('hashchange', function () {
      var t = location.hash.replace(/^#/, '');
      if (!TABS[t] || !S.kase) return;
      if (tabsOf(curItem()).indexOf(t) >= 0) setTab(t);
      else select(defaultKey({ tab: t }), t);   // 候補を開いているときに #proof = 最初の未校正の切り抜きへ
    });
    UIKit.life.onLeave(function (reason) {
      if (reason !== 'blur') { clearTimeout(S.timer); S.timer = 0; }   // 見えない間は問い合わせない('blur' = 隣の窓へ。画面は見えている)
      if (S.panel && S.panel.leave) { try { S.panel.leave(reason); } catch (e) { UIKit.report('パネルの leave で失敗しました: ' + (e && e.message)); } }
    });
    UIKit.life.onReturn(function (reason) {
      if (S.panel && S.panel.back) { try { S.panel.back(reason); } catch (e) { UIKit.report('パネルの back で失敗しました: ' + (e && e.message)); } }
      if (!S.timer) poll();
    });
    S.want = readUrl();
    if (S.want.v && !S.want.c && !S.want.d) openMedia(S.want);
    else load(false);
  });

  /* 画面のテスト(tests/app/e2e_cases_*.py)と確かめる(V1)が今の状態を読む口 */
  window.CasesShell = {
    state: function () { var it = curItem(); return { caseId: S.kase ? S.kase.id : '', sel: S.sel, tab: S.tab, docId: it ? it.docId || '' : '', pollMs: S.pollMs, rev: S.status.rev, panel: S.panelTab }; },
    select: select, setTab: setTab, next: goNext, reload: function () { return load(true); }, poll: function () { poll(); }
  };
})();
