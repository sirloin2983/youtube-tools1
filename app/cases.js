/* 案件の画面(app/cases.html)。/api/cases を読んで配信を1行にまとめ、状態・メモを /api/cases/update で保存する。
   CSP(script-src 'self')の下で動く。値は textContent で入れる(配信のタイトル・パスに < などが入っていても画面を壊さない)。

   一覧は 1件1行(details。開くと切り抜きの一覧・まとめて実行・メモがその場に出る)。上の道具の行(検索・絞り込み・並び替え・
   まとめ方・件数)で絞り込み、絞り込んだ分だけ描いて「もっと見る」で増やす(件数が多くても重くならない作り。2026-09-26 画面の見直し)。
   まとめて実行が動いている行・その行を含むまとまりは、進み具合を見失わないよう閉じさせない(クリックでの折りたたみを打ち消す)。 */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $all = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var TOKEN = (document.querySelector('meta[name="ytt-token"]') || {}).content || '';
  var STATUS = { '': '未設定', working: '作業中', posted: '投稿済み', skipped: '見送り' };
  var STATUS_PILL = { '': '', working: 'run', posted: 'ok', skipped: 'wait' };
  var STEP_STATE = { wait: 'まだ', run: '実行中', done: '済み', skip: '飛ばした', warn: '一部失敗', error: '失敗' };
  var STEP_PILL = { wait: 'wait', run: 'run', done: 'ok', skip: 'wait', warn: 'warn', error: 'err' };
  var PAGE_SIZE = 30;

  var data = null, toastTimer = null;
  var runs = {}, autoTimer = null, wasActive = {};   // まとめて実行: 配信ごとのいちばん新しい実行
  var visibleCount = PAGE_SIZE;                      // 「もっと見る」で増える(絞り込み・並び替え・まとめ方・検索を変えたら 30 に戻す)
  var openCases = {};                                // この画面を開いてから自分で開閉した案件(id → bool。閉じたら消す)
  var groupOpenCache = null;                         // まとまりの開閉(localStorage に覚える。鍵 → bool)
  var termShown = {};                                // 専門用語の説明(abbr)は画面に出す最初の1回だけ

  function lsGet(k, d) { try { var v = localStorage.getItem('ytt.cases.' + k); return v === null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem('ytt.cases.' + k, v); } catch (e) { /* 保存できなくても動く */ } }
  function groupOpenMap() {
    if (!groupOpenCache) { try { groupOpenCache = JSON.parse(lsGet('groupOpen', '{}')) || {}; } catch (e) { groupOpenCache = {}; } }
    return groupOpenCache;
  }
  function setGroupOpen(key, open) { groupOpenMap()[key] = !!open; lsSet('groupOpen', JSON.stringify(groupOpenCache)); }

  function toast(msg, kind) {
    var t = $('#toast');
    t.className = 'toast ' + (kind || 'info');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 4000);
  }
  function err(msg) { var b = $('#errbar'); b.textContent = msg; b.hidden = !msg; }

  function api(path, body) {
    var opt = body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-YTT-Token': TOKEN }, body: JSON.stringify(body) } : {};
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.message || ('HTTP ' + r.status));
        return j;
      });
    });
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function term(word, title) {
    // 専門用語(Text+ など)は画面に出す最初の場所だけ <abbr class="ui-term"> にする(docs/ui-guidelines.md の 1)
    if (termShown[word]) return document.createTextNode(word);
    termShown[word] = true;
    var a = document.createElement('abbr');
    a.className = 'ui-term'; a.title = title; a.textContent = word;
    return a;
  }
  function tc(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
  }
  function when(ms) {
    if (!ms) return '';
    var d = new Date(ms);
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function basename(p) { return String(p || '').split(/[\\/]/).pop(); }
  function link(text, href) {
    var a = el('a', 'btn small', text);
    a.href = href; a.target = '_blank'; a.rel = 'noopener';
    return a;
  }

  function clipRow(c) {
    var li = el('li', 'pt-clip');
    var head = el('div', 'row');
    head.appendChild(el('span', 'pt-clip-range mono', tc(c.start) + '–' + tc(c.end)));
    head.appendChild(el('span', 'grow', c.label || c.file || '(名前なし)'));
    if (c.file) {   // ファイル名は見せる。フルパスは title だけ(audit #4: 常に出ているとうるさい)
      var fn = el('span', 'hint mono pt-clip-file', c.file);
      if (c.path) fn.title = c.path;
      head.appendChild(fn);
    }
    if (!c.exists) head.appendChild(el('span', 'pill warn', '動画が見つからない'));
    li.appendChild(head);
    var st = el('div', 'row pt-clip-steps');
    // 文字起こし
    if (c.transcript) {
      var t = c.transcript, done = t.segments && t.proofed >= t.segments;
      st.appendChild(el('span', 'pill ' + (done ? 'ok' : 'run'), '文字起こし 校正 ' + t.proofed + '/' + t.segments + '行'));
    } else {
      st.appendChild(el('span', 'pill wait', '文字起こし まだ'));
    }
    // パック
    if (c.pack) {
      var pill = el('span', 'pill ok');
      if (c.pack.textplus) pill.append(term('Text+', 'DaVinci Resolve のテロップ(字幕)機能'), ' パック ' + when(c.pack.updatedAt));
      else pill.textContent = 'パック ' + when(c.pack.updatedAt);
      st.appendChild(pill);
    } else {
      st.appendChild(el('span', 'pill wait', 'パック まだ'));
    }
    // 「編集」で開く(文字起こし・カット・パックは同じツールの3つのタブ。文書が無ければ「文字起こしする / せずに開く」を選ぶ)
    if (c.exists && c.path) st.appendChild(link('編集で開く', '/transcribe/?media=' + encodeURIComponent(c.path)));
    li.appendChild(st);
    return li;
  }

  function fillClips(node, c) {
    var ol = $('.pt-clips', node);
    ol.textContent = '';
    if (!c.clips.length) ol.appendChild(el('li', 'hint', c.marks.adopted ? '採用したマークはまだ書き出していません(スタジオで書き出すか、下の「まとめて実行」で)' : '書き出した切り抜きはありません'));
    c.clips.forEach(function (cl) { ol.appendChild(clipRow(cl)); });
  }

  // ---- まとめて実行(/api/autorun。app/autorun.py)
  function active(r) { return r && (r.state === 'queued' || r.state === 'running'); }
  function activeIn(ids) { return ids.some(function (id) { return active(runs[id]); }); }

  function wireAuto(node, c) {
    var box = $('.pt-auto', node), mode = $('.pt-auto-mode', box), top = $('.pt-auto-top', box);
    if (c.gone) { box.hidden = true; return; }   // スタジオから消えた配信は実行できない
    mode.value = lsGet('mode', 'adopted');
    if (!mode.value) mode.value = 'adopted';
    top.value = lsGet('top', '3');
    var sync = function () { $('.pt-auto-topbox', box).hidden = mode.value !== 'full'; };
    mode.addEventListener('change', function () { lsSet('mode', mode.value); sync(); });
    top.addEventListener('change', function () { lsSet('top', top.value); });
    sync();
    $('.pt-auto-run', box).addEventListener('click', function () {
      var body = { id: c.id, mode: mode.value };
      if (mode.value === 'full') body.top = Math.round(Number(top.value) || 3);
      api('/api/autorun/start', body).then(function (r) {
        runs[c.id] = r.run; node.open = true; renderAuto(node, c.id); toast('「' + r.run.modeLabel + '」を始めました', 'ok'); pollAuto();
      }).catch(function (e) { toast('始められませんでした: ' + e.message, 'err'); });
    });
    $('.pt-auto-cancel', box).addEventListener('click', function () {
      var r = runs[c.id]; if (!r) return;
      api('/api/autorun/cancel', { runId: r.id }).then(function (x) { runs[c.id] = x.run; renderAuto(node, c.id); })
        .catch(function (e) { toast('中止できませんでした: ' + e.message, 'err'); });
    });
    renderAuto(node, c.id);
  }
  function renderAuto(node, id) {
    var box = $('.pt-auto', node); if (!box) return;
    var r = runs[id], ol = $('.pt-auto-steps', box), msg = $('.pt-auto-msg', box);
    $('.pt-auto-run', box).disabled = active(r);
    $('.pt-auto-cancel', box).hidden = !active(r);
    ol.textContent = ''; msg.textContent = '';
    if (!r) return;
    r.steps.forEach(function (st) {
      var li = el('li', 'pt-auto-step');
      li.appendChild(el('span', 'pill ' + (STEP_PILL[st.state] || 'wait'), st.label + ' ' + (STEP_STATE[st.state] || st.state)));
      if (st.detail) li.appendChild(el('span', 'hint', st.detail));
      ol.appendChild(li);
    });
    var head = r.modeLabel + ': ' + ({ queued: '順番待ち', running: '実行中', done: '完了', error: '止まりました', cancelled: '中止しました' }[r.state] || r.state);
    msg.textContent = head + (r.error ? ' ・ ' + r.error : '') + (r.finished ? '(' + when(r.finished) + ')' : '');
  }

  // ---- 一覧の1行(details。閉じているあいだは中身を描かない分だけ軽い)
  function caseSubText(c) {
    var parts = [c.channel || '(配信者不明)'];
    if (c.streamedAt && window.UIKit && UIKit.fmt) parts.push(UIKit.fmt.ago(c.streamedAt));
    parts.push('切り抜き ' + c.marks.exported + '本');
    if (c.gone) parts.push('スタジオから消えた動画(最後に見えた内容)');
    return parts.filter(Boolean).join(' ・ ');
  }
  function txSummaryText(t) {
    if (!t || !t.clips) return '';
    if (!t.withTranscript) return '文字起こし まだ';
    var base = '校正 ' + t.proofed + '/' + t.segments + '行';
    var missing = t.clips - t.withTranscript;
    return missing ? base + '(未着手 ' + missing + '本)' : base;
  }
  function packSummaryText(p) {
    if (!p || !p.total) return '';
    if (!p.have) return 'パック まだ';
    return p.have === p.total ? 'パック 済み(' + p.have + '本)' : 'パック ' + p.have + '/' + p.total;
  }

  function caseCard(c) {
    var node = $('#tplCase').content.firstElementChild.cloneNode(true);
    node.dataset.id = c.id;
    $('.pt-case-title', node).textContent = c.title || c.id;
    $('.pt-case-sub', node).textContent = caseSubText(c);
    var pill = $('.pt-case-statuspill', node);
    pill.className = 'pill pt-case-statuspill' + (STATUS_PILL[c.status || ''] ? ' ' + STATUS_PILL[c.status || ''] : '');
    pill.textContent = STATUS[c.status || ''];
    var tx = $('.pt-case-tx', node), txt = txSummaryText(c.tx);
    tx.hidden = !txt; tx.textContent = txt;
    var pk = $('.pt-case-pack', node), pkt = packSummaryText(c.packs);
    pk.hidden = !pkt; pk.textContent = pkt;
    var nx = $('.pt-case-next', node);
    nx.hidden = !c.next; nx.textContent = c.next ? c.next.label + ' ' + c.next.count + '本' : '';

    node.open = !!openCases[c.id] || active(runs[c.id]);
    $('.pt-case-row', node).addEventListener('click', function (e) {
      if (node.open && active(runs[c.id])) { e.preventDefault(); return; }   // 実行中は閉じさせない(進み具合を見失わないため)
      setTimeout(function () { openCases[c.id] = node.open; }, 0);
    });

    var sel = $('.pt-case-status', node);
    sel.value = c.status || '';
    sel.addEventListener('change', function () {
      api('/api/cases/update', { id: c.id, status: sel.value }).then(function (r) {
        c.status = r.status; toast('状態を「' + STATUS[r.status] + '」にしました', 'ok');
        pill.className = 'pill pt-case-statuspill' + (STATUS_PILL[r.status] ? ' ' + STATUS_PILL[r.status] : '');
        pill.textContent = STATUS[r.status];
        updateSummaryLine();
      }).catch(function (e) { sel.value = c.status || ''; toast('保存できませんでした: ' + e.message, 'err'); });
    });
    fillClips(node, c);
    wireAuto(node, c);
    var ta = $('textarea', node), msg = $('.pt-memo-msg', node);
    ta.value = c.memo || '';
    if (c.memo) $('.pt-case-memo', node).open = true;
    $('.pt-memo-save', node).addEventListener('click', function () {
      api('/api/cases/update', { id: c.id, memo: ta.value }).then(function (r) {
        c.memo = r.memo; msg.textContent = '保存しました';
      }).catch(function (e) { msg.textContent = '保存できませんでした: ' + e.message; });
    });
    return node;
  }

  function wireGroup(g, key, ids) {
    $('summary', g).addEventListener('click', function (e) {
      if (g.open && activeIn(ids)) { e.preventDefault(); return; }   // 実行中の案件を含むまとまりは閉じさせない
      setTimeout(function () { setGroupOpen(key, g.open); }, 0);
    });
  }

  // ---- 絞り込み・並び替え・まとめ方
  function visible(c) {
    var fs = $('#fStatus').value, q = $('#fText').value.trim().toLowerCase();
    if (fs === 'none' && c.status) return false;
    if (fs && fs !== 'none' && c.status !== fs) return false;
    if (q && ((c.title || '') + ' ' + (c.channel || '')).toLowerCase().indexOf(q) < 0) return false;
    return true;
  }
  function sortList(list) {
    var key = $('#fSort').value;
    if (key === 'remaining') list.sort(function (a, b) { return (b.remaining || 0) - (a.remaining || 0) || (b.streamedAt || 0) - (a.streamedAt || 0); });
    else if (key === 'channel') list.sort(function (a, b) { return (a.channel || '').localeCompare(b.channel || '', 'ja') || (a.title || '').localeCompare(b.title || '', 'ja'); });
    else if (key === 'title') list.sort(function (a, b) { return (a.title || '').localeCompare(b.title || '', 'ja'); });
    else list.sort(function (a, b) { return (b.streamedAt || 0) - (a.streamedAt || 0); });
  }
  function groupKeyOf(c) {
    var g = $('#fGroup').value;
    if (g === 'channel') return c.channel || '(配信者不明)';
    if (g === 'status') return STATUS[c.status || ''];
    return '';
  }

  function render() {
    if (!data) return;
    var full = data.cases.filter(visible);
    sortList(full);
    var totalCount = full.length, gval = $('#fGroup').value;
    var fullCount = {};
    if (gval) full.forEach(function (c) { var k = groupKeyOf(c); fullCount[k] = (fullCount[k] || 0) + 1; });
    var shown = full.slice(0, Math.max(0, visibleCount));

    var list = $('#list');
    list.textContent = '';
    if (!shown.length) {
      list.appendChild(el('p', 'empty', data.cases.length ? '条件に合う配信はありません' : 'まだ配信がありません(切り抜きスタジオで配信を解析すると、ここに出ます)'));
    } else if (!gval) {
      shown.forEach(function (c) { list.appendChild(caseCard(c)); });
    } else {
      var order = [], bucket = {};
      shown.forEach(function (c) { var k = groupKeyOf(c); if (!bucket[k]) { bucket[k] = []; order.push(k); } bucket[k].push(c); });
      order.forEach(function (k) {
        var key = gval + ':' + k, ids = bucket[k].map(function (c) { return c.id; });
        var g = $('#tplGroup').content.firstElementChild.cloneNode(true);
        g.dataset.key = key;
        $('.pt-group-label', g).textContent = k;
        $('.ui-group-n', g).textContent = (fullCount[k] || bucket[k].length) + '件';
        var body = $('.pt-group-body', g);
        bucket[k].forEach(function (c) { body.appendChild(caseCard(c)); });
        g.open = !!groupOpenMap()[key] || activeIn(ids);
        wireGroup(g, key, ids);
        list.appendChild(g);
      });
    }

    var moreBox = $('#moreBox'), moreBtn = $('#btnMore'), rest = totalCount - shown.length;
    moreBox.hidden = rest <= 0;
    if (rest > 0) moreBtn.textContent = 'もっと見る(あと ' + rest + ' 件)';
    var narrowed = gval || $('#fStatus').value || $('#fText').value.trim();
    $('#count').textContent = narrowed ? shown.length + ' / ' + totalCount + ' 件' : totalCount + ' 件';
    updateSummaryLine();
    $('#casesFile').textContent = '状態・メモの保存先: ' + (data.casesFile || '');
    renderUnlinked();
  }
  function resetPaging() { visibleCount = PAGE_SIZE; render(); }

  function updateSummaryLine() {
    var n = { '': 0, working: 0, posted: 0, skipped: 0 };
    data.cases.forEach(function (c) { n[c.status || ''] = (n[c.status || ''] || 0) + 1; });
    $('#summary').textContent = '配信 ' + data.cases.length + ' 本(作業中 ' + n.working + '・投稿済み ' + n.posted + '・見送り ' + n.skipped + '・未設定 ' + n[''] + ')';
  }
  function renderUnlinked() {
    var ul = $('#unlinked');
    ul.textContent = '';
    data.unlinked.forEach(function (t) {
      var li = el('li', '');
      li.appendChild(el('span', '', (t.title || t.id) + '(校正 ' + t.proofed + '/' + t.segments + '行)'));
      if (t.sourcePath) {
        var p = el('span', 'hint mono pt-clip-file', basename(t.sourcePath));
        p.title = t.sourcePath;
        li.appendChild(document.createElement('br'));
        li.appendChild(p);
      }
      ul.appendChild(li);
    });
    $('#unlinkedCount').textContent = data.unlinked.length + ' 件';
    $('#unlinkedBox').hidden = !data.unlinked.length;
  }

  function refreshCases() {
    return api('/api/cases').then(function (j) { data = j; render(); }).catch(function () { /* 次の読み込みで直る */ });
  }
  function pollAuto() {
    clearTimeout(autoTimer);
    api('/api/autorun').then(function (j) {
      var latest = {}, anyActive = false, finished = false;
      (j.runs || []).forEach(function (r) { if (!latest[r.videoId]) latest[r.videoId] = r; });   // 新しい順に来る
      Object.keys(latest).forEach(function (id) {
        var r = latest[id];
        if (active(r)) anyActive = true;
        if (wasActive[id] && !active(r)) finished = true;   // 終わった: 切り抜き・文字起こし・パックの表示を新しくする
        wasActive[id] = active(r);
      });
      runs = latest;
      $all('#list .pt-case').forEach(function (node) {
        renderAuto(node, node.dataset.id);
        if (active(runs[node.dataset.id])) node.open = true;   // 実行中になった行は開く(進み具合を見失わないため)
      });
      $all('#list .ui-group').forEach(function (g) {
        if (activeIn($all('.pt-case', g).map(function (n) { return n.dataset.id; }))) g.open = true;
      });
      if (finished) refreshCases();
      autoTimer = setTimeout(pollAuto, anyActive ? 2000 : 15000);
    }).catch(function () { autoTimer = setTimeout(pollAuto, 5000); });
  }

  function load() {
    err('');
    return api('/api/cases').then(function (j) { data = j; resetPaging(); }).catch(function (e) { err('案件の一覧を読めませんでした: ' + e.message); });
  }

  function restoreFilters() {
    var st = lsGet('status', ''), so = lsGet('sort', 'new'), gr = lsGet('group', '');
    if ($('#fStatus').querySelector('option[value="' + st + '"]')) $('#fStatus').value = st;
    if ($('#fSort').querySelector('option[value="' + so + '"]')) $('#fSort').value = so;
    if ($('#fGroup').querySelector('option[value="' + gr + '"]')) $('#fGroup').value = gr;
  }

  $('#fStatus').addEventListener('change', function () { lsSet('status', $('#fStatus').value); resetPaging(); });
  $('#fText').addEventListener('input', function () { resetPaging(); });
  $('#fSort').addEventListener('change', function () { lsSet('sort', $('#fSort').value); resetPaging(); });
  $('#fGroup').addEventListener('change', function () { lsSet('group', $('#fGroup').value); resetPaging(); });
  $('#btnMore').addEventListener('click', function () { visibleCount += PAGE_SIZE; render(); });
  $('#btnReload').addEventListener('click', function () { load().then(function () { toast('読み込み直しました'); }); });

  restoreFilters();
  load().then(pollAuto);
})();
