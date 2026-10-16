/* ホームの運用の中の「編集の精度と学習」(src/home/portal.html の #editOpsBox。RS8 C3)。
   編集の左メニューにあった「精度」(認識精度の測定・評価用の基準の記録)と「学習」(修正から学習した候補 → 置換辞書への登録)を、
   古い編集の画面(C4 で消える)を開かなくても使えるようにここへ写した物。毎日は見ない物なので、ホームの運用に畳んで、開いたときに初めて読む。
   使う API は編集の今の口そのまま(transcribe/api/metrics・learned・settings)。値の出し方・登録の規則は
   編集の app-learn.js・app.js と同じ(置換辞書 replacements の「誤=>正」の 1 行・カタカナ/漢字/英数字だけの語は |語| で単語の途中に当てない・用語集 glossary は 2〜15 字だけ)。
   違い: 設定の保存は編集の画面の設定の欄を通さず、PUT transcribe/api/settings {patch:{…}}(最上位のキーだけ合わせる。別の窓の変更を消さない)。
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
  var toast = function (msg, kind) { UIKit.toast(msg, kind ? { kind: kind } : undefined); };
  var pct = function (v) { return v == null ? '—' : (v * 100).toFixed(1) + '%'; };
  var norm = function (s) { return String(s).normalize('NFKC').toLowerCase(); };
  function fmtT(t) {
    t = Math.max(0, Number(t) || 0);
    var h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = Math.floor(t % 60);
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
  }
  function busy(btn, fn) {
    btn.disabled = true;
    return Promise.resolve().then(fn).then(function (r) { btn.disabled = false; return r; }, function (e) { btn.disabled = false; throw e; });
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

  /* ================= 修正から学習した候補 ================= */
  var learned = { items: [], docs: 0, lines: 0 }, showAll = false, draft = {}, ignore = null;
  var key = function (x) { return x.wrong + '=>' + x.right; };
  var ccOf = function (ch) {
    var o = ch.codePointAt(0);
    if ((o >= 0x30A1 && o <= 0x30FA) || 'ー・ヽヾ'.indexOf(ch) >= 0) return 'K';
    if ((o >= 0x4E00 && o <= 0x9FFF) || '々〆'.indexOf(ch) >= 0) return 'H';
    if (/[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]/.test(ch)) return 'A';
    return '';
  };
  var wbSplit = function (w) { return (w.length >= 3 && w[0] === '|' && w[w.length - 1] === '|') ? [w.slice(1, -1), true] : [w, false]; };

  function loadLearned() {
    return api('api/learned?min=' + encodeURIComponent($('#lnMin').value)).then(function (j) { learned = j || { items: [], docs: 0 }; renderLearned(); },
      function (e) { $('#lnList').innerHTML = errLine(e); });
  }
  function renderLearned() {
    var list = $('#lnList'), items = learned.items || [];
    $('#lnStat').textContent = learned.docs ? '修正した行: ' + (learned.lines || 0) + '行(学習の対象: ' + learned.docs + '件の文字起こし)' : '';
    if (!items.length) {
      list.innerHTML = '<p class="hint">' + (learned.docs ? '候補はありません(文字起こしを直すと、ここに出ます)' : 'v0.5 以降で文字起こしした分から学習します。文字起こしを直すと、ここに候補が出ます') + '</p>';
      $('#lnMore').hidden = true;
      return;
    }
    var q = norm($('#lnSearch').value.trim());
    var found = items.map(function (x, i) { return { x: x, i: i }; }).filter(function (f) { return !q || norm(f.x.wrong + ' ' + f.x.right).indexOf(q) >= 0; });
    if (!found.length) { list.innerHTML = '<p class="hint">条件に合う候補はありません。検索の文字を消すと、すべての候補が出ます。</p>'; $('#lnMore').hidden = true; return; }
    var shown = showAll ? found : found.slice(0, 10);
    list.innerHTML = shown.map(function (f) {
      var x = f.x, d = draft[key(x)] || { w: x.wrong, r: x.right }, edited = d.w !== x.wrong || d.r !== x.right;
      return '<div class="ln' + (edited ? ' edited' : '') + '" data-i="' + f.i + '">' +
        '<div class="row pt-ln-edit"><input class="lw" type="text" value="' + esc(d.w) + '" maxlength="40" aria-label="誤(置換される文字)"><span>→</span><input class="lr" type="text" value="' + esc(d.r) + '" maxlength="40" aria-label="正(置換後の文字)"></div>' +
        '<div class="row"><span class="pill">' + (Number(x.count) || 0) + '回</span><button type="button" class="btn small" data-act="lnadd">登録</button><button type="button" class="btn small" data-act="lnign">無視</button><button type="button" class="btn small" data-act="lnrev"' + (edited ? '' : ' hidden') + '>編集を戻す</button></div></div>';
    }).join('') + '<p class="hint">「誤」「正」は、その場で直してから登録できます(例: 前後の文字を消して短くする)。</p>';
    var more = $('#lnMore'); more.hidden = found.length <= 10; more.textContent = showAll ? '上位10件だけ表示' : '残り' + (found.length - shown.length) + '件を表示';
  }
  /* 設定(置換辞書 replacements・用語集 glossary・無視した候補 learnIgnore)を読む。保存は最上位のキー単位の patch(別の窓の変更を消さない) */
  function readSettings() { return api('api/settings'); }
  function patchSettings(patch) { return api('api/settings', { method: 'PUT', body: { patch: patch } }); }
  function addLines(text, line, sameKey) {
    var lines = String(text || '').split(/\r?\n/), same = -1;
    for (var i = 0; i < lines.length; i++) {
      var k = lines[i].indexOf('=>');
      if (sameKey != null && k > 0 && wbSplit(lines[i].slice(0, k).trim())[0] === sameKey) { same = i; break; }
      if (sameKey == null && lines[i].trim() === line) { same = i; break; }
    }
    if (same >= 0) { if (sameKey != null) lines[same] = line; return { text: lines.join('\n'), replaced: sameKey != null }; }
    return { text: (String(text || '').replace(/\s+$/, '') + '\n' + line).replace(/^\n/, ''), replaced: false };
  }
  function register(x, row) {
    var w = row.querySelector('.lw').value.trim(), r = row.querySelector('.lr').value.trim();
    if (!w) return Promise.reject(new Error('「誤」の文字を入れてください'));
    if (w === r) return Promise.reject(new Error('「誤」と「正」が同じです'));
    if (/=>|[\r\n]/.test(w + r)) return Promise.reject(new Error('「=>」と改行は使えません'));
    var wbW = ccOf(w[0]) && Array.from(w).every(function (c) { return ccOf(c) === ccOf(w[0]); }) && w.indexOf('|') < 0 ? '|' + w + '|' : w;   // カタカナ・漢字・英数字だけの語は、単語の途中には当てない形で登録する
    return readSettings().then(function (cur) {
      var rep = addLines(cur.replacements, wbW + '=>' + r, w), patch = { replacements: String(rep.text).slice(0, 20000) }, msg = '置換辞書に登録しました。次の文字起こしから自動で直ります';
      if (rep.replaced) msg = '同じ「' + w + '」の登録があったので、置き換えました。次の文字起こしから自動で直ります';
      if ($('#lnGloss').checked && r.length >= 2 && r.length <= 15 && (!x.ctx || r !== x.right)) {   // 前後の文字を足した断片のままなら、用語集には入れない
        patch.glossary = String(addLines(cur.glossary, r, null).text).slice(0, 4000);
      }
      if (w !== x.wrong || r !== x.right) patch.learnIgnore = (cur.learnIgnore || []).concat([key(x)]).slice(-500);   // 直して登録したときは、元の候補は消す
      return patchSettings(patch).then(function () { delete draft[key(x)]; toast(msg, 'ok'); });
    });
  }
  function ignoreCand(x) {
    return readSettings().then(function (cur) { return patchSettings({ learnIgnore: (cur.learnIgnore || []).concat([key(x)]).slice(-500) }); }).then(function () { delete draft[key(x)]; });
  }

  function wire() {
    $('#accScope').addEventListener('change', loadAcc);
    $('#accRefresh').addEventListener('click', loadAcc);
    $('#lnRefresh').addEventListener('click', loadLearned);
    $('#lnMin').addEventListener('change', function () { showAll = false; loadLearned(); });
    $('#lnSearch').addEventListener('input', function () { showAll = false; renderLearned(); });
    $('#lnMore').addEventListener('click', function () { showAll = !showAll; renderLearned(); });
    var list = $('#lnList');
    list.addEventListener('input', function (e) {
      var row = e.target.closest('.ln'), x = row && learned.items[Number(row.dataset.i)]; if (!x) return;
      var w = row.querySelector('.lw').value, r = row.querySelector('.lr').value, edited = w !== x.wrong || r !== x.right;
      if (edited) draft[key(x)] = { w: w, r: r }; else delete draft[key(x)];
      row.classList.toggle('edited', edited); row.querySelector('[data-act=lnrev]').hidden = !edited;
    });
    list.addEventListener('click', function (e) {
      var b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
      var row = b.closest('.ln'), x = row && learned.items[Number(row.dataset.i)]; if (!x) return;
      if (b.dataset.act === 'lnrev') { delete draft[key(x)]; renderLearned(); return; }
      var job = b.dataset.act === 'lnadd' ? register(x, row) : ignoreCand(x);
      busy(b, function () { return job; }).then(loadLearned, function (er) { toast(er.message || '保存できませんでした', 'err'); });
    });
  }

  function start() {
    if (started) return;
    started = true;
    wire();
    loadAcc(); loadLearned();
  }
  /* 開いたときに初めて読む(毎日は見ない物なので、ホームを開くたびには聞かない)。#edit-acc・#edit-learn のハッシュで直に開ける */
  box.addEventListener('toggle', function () { if (box.open) start(); });
  if (box.open) start();
  window.PortalEdit = { start: start, open: function () { box.open = true; start(); } };
})();
