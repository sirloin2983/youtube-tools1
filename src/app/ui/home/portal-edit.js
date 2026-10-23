/* ホームの運用の中の「編集の精度」(src/app/ui/home/portal.html の #editOpsBox。RS8 C3)。
   編集の左メニューにあった「精度」(認識精度の測定・評価用の基準の記録)を、古い編集の画面を開かなくても使えるようにここへ写した物。
   毎日は見ない物なので、ホームの運用に畳んで、開いたときに初めて読む。使う API は編集の transcribe/api/metrics。
   (「学習」= 修正から学習した候補の一覧は 10-24 ユーザーの OK で消した)
   ツール名・文字・数はすべて esc / textContent で入れる。CSP script-src 'self' のため、インラインのスクリプト・on〇〇= は使わない。 */
(function () {
  'use strict';
  var box = document.getElementById('editOpsBox');
  if (!box) return;
  var $ = function (s) { return box.querySelector(s); };
  var esc = UIKit.esc;
  var started = false;

  function api(path, opt) {
    return UIKit.http('transcribe/' + path, Object.assign({ timeout: 30000, offline: '編集につながりませんでした(start.bat の黒い画面が閉じていないか確かめてください)' }, opt || {}));
  }
  var pct = function (v) { return v == null ? '—' : (v * 100).toFixed(1) + '%'; };
  function fmtT(t) {
    t = Math.max(0, Number(t) || 0);
    var h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = Math.floor(t % 60);
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
  }
  function errLine(e) { return '<p class="hint pt-edit-err" role="alert">' + esc(e && e.message ? e.message : String(e)) + '</p>'; }

  /* ================= 認識精度の測定 ================= */
  function loadAcc() {
    var scope = encodeURIComponent($('#accScope').value);
    return api('api/metrics?scope=' + scope).then(renderAcc, function (e) { $('#accOut').innerHTML = errLine(e); });
  }
  function renderAcc(m) {
    var o = m.overall, out = $('#accOut');
    if (!o.groups) {
      out.innerHTML = '<p class="hint">校正済みの行がまだありません(' + (Number(m.docs) || 0) + '件の文字起こしのうち、校正済みの行があるのは' + (Number(m.docsProofed) || 0) + '件)。案件の画面の校正で、聞いて確認した行に「校正済み」の印を付けると、ここに文字誤り率が出ます。「印のない旧データも含める」で、これまでに直した分を仮計算できます。</p>';
      return;
    }
    var errs = o.errs || 0, share = function (v) { return errs ? Math.round(v / errs * 100) + '%' : '—'; };
    var rows = function (list) {
      return list.map(function (c) { return '<tr><td>' + esc(c.config || c.title || '') + '</td><td>' + (Number(c.groups) || 0) + '</td><td>' + (Number(c.refChars) || 0) + '</td><td><b>' + pct(c.cer) + '</b></td><td>' + (Number(c.sub) || 0) + '/' + (Number(c.del) || 0) + '/' + (Number(c.ins) || 0) + '</td></tr>'; }).join('');
    };
    out.innerHTML = '<div class="accmain">文字誤り率(CER) <b>' + pct(o.cer) + '</b> <span class="hint">誤り ' + errs + '字 ÷ 正解 ' + (Number(o.refChars) || 0) + '字</span></div>' +
      '<p class="hint">内訳: 置換(別の字に間違い) ' + (Number(o.sub) || 0) + '字(' + share(o.sub) + ') ・ 脱落(聞き逃し) ' + (Number(o.del) || 0) + '字(' + share(o.del) + ') ・ 挿入(余計な字。幻覚など) ' + (Number(o.ins) || 0) + '字(' + share(o.ins) + ')<br>' +
      '機械が出したが人が消した行: ' + (Number(o.machineOnly) || 0) + '行(' + (Number(o.machineOnlyChars) || 0) + '字) ・ 用語が正しく出た率: ' + (o.termRef ? (Number(o.termHit) || 0) + '/' + o.termRef + '(' + pct(o.termRate) + ')' : '—') + ' ・ 用語の誤挿入: ' + (Number(o.termExtra) || 0) + '回</p>' +
      '<p class="hint">' + (o.refChars < 1000 ? '※ 正解が1000字未満なので、数値は目安です(同じ動画を何度も文字起こしした分は、重複して数えられます)。' : '') + '校正済み ' + (Number(m.proofedLines) || 0) + '行 ・ 対象 ' + ((m.byDoc || []).length) + '件</p>' +
      '<table class="acct"><tr><th>設定</th><th>行数</th><th>正解字</th><th>CER</th><th>置換/脱落/挿入</th></tr>' + rows(m.byConfig || []) + '</table>' +
      '<details class="ui-disclosure"><summary class="hint">文字起こしごと</summary><table class="acct"><tr><th>文字起こし</th><th>行数</th><th>正解字</th><th>CER</th><th>置換/脱落/挿入</th></tr>' + rows(m.byDoc || []) + '</table></details>' +
      '<details class="ui-disclosure"><summary class="hint">誤りが多い場所(上位)</summary>' + (o.worst || []).map(function (w) {
        return '<div class="wl"><span class="mono">' + esc(w.doc || '') + ' ' + fmtT(w.start) + '</span><br>正: ' + (esc(w.ref) || '(人が消した行)') + '<br>機: ' + (esc(w.hyp) || '(聞き逃し)') + '</div>';
      }).join('') + '</details>';
  }

  function wire() {
    $('#accScope').addEventListener('change', loadAcc);
    $('#accRefresh').addEventListener('click', loadAcc);
  }

  function start() {
    if (started) return;
    started = true;
    wire();
    loadAcc();
  }
  /* 開いたときに初めて読む(毎日は見ない物なので、ホームを開くたびには聞かない)。#edit-acc のハッシュで直に開ける */
  box.addEventListener('toggle', function () { if (box.open) start(); });
  if (box.open) start();
  window.PortalEdit = { start: start, open: function () { box.open = true; start(); } };
})();
