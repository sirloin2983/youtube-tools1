/* 案件の画面(app/cases.html)。/api/cases を読んで配信ごとに並べ、状態・メモを /api/cases/update で保存する。
   CSP(script-src 'self')の下で動く。値は textContent で入れる(配信のタイトル・パスに < などが入っていても画面を壊さない) */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var TOKEN = (document.querySelector('meta[name="ytt-token"]') || {}).content || '';
  var STATUS = { '': '未設定', working: '作業中', posted: '投稿済み', skipped: '見送り' };
  var data = null, toastTimer = null;
  var runs = {}, autoTimer = null, wasActive = {};   // まとめて実行: 配信ごとのいちばん新しい実行
  var STEP_STATE = { wait: 'まだ', run: '実行中', done: '済み', skip: '飛ばした', warn: '一部失敗', error: '失敗' };
  var STEP_PILL = { wait: 'wait', run: 'run', done: 'ok', skip: 'wait', warn: 'warn', error: 'err' };
  function lsGet(k, d) { try { var v = localStorage.getItem('ytt.cases.' + k); return v === null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem('ytt.cases.' + k, v); } catch (e) { /* 保存できなくても動く */ } }

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
    if (!c.exists) head.appendChild(el('span', 'pill warn', '動画が見つからない'));
    li.appendChild(head);
    var st = el('div', 'row pt-clip-steps');
    // 文字起こし
    if (c.transcript) {
      var t = c.transcript, done = t.segments && t.proofed >= t.segments;
      st.appendChild(el('span', 'pill ' + (done ? 'ok' : 'run'), '文字起こし 校正 ' + t.proofed + '/' + t.segments + '行'));
    } else {
      st.appendChild(el('span', 'pill wait', '文字起こし まだ'));
      if (c.exists && c.path) st.appendChild(link('文字起こしで開く', '/transcribe/?media=' + encodeURIComponent(c.path)));
    }
    // パック
    if (c.pack) st.appendChild(el('span', 'pill ok', (c.pack.textplus ? 'Text+ パック ' : 'パック ') + when(c.pack.updatedAt)));
    else {
      st.appendChild(el('span', 'pill wait', 'パック まだ'));
      if (c.exists && c.path) st.appendChild(link('cut2resolve で開く', '/cut2resolve/?video=' + encodeURIComponent(c.path)));
    }
    li.appendChild(st);
    if (c.path) li.appendChild(el('div', 'hint mono pt-clip-path', c.path));
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
        runs[c.id] = r.run; renderAuto(node, c.id); toast('「' + r.run.modeLabel + '」を始めました', 'ok'); pollAuto();
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
  function refreshCases() {
    return api('/api/cases').then(function (j) {
      data = j;
      document.querySelectorAll('#list .pt-case').forEach(function (node) {
        var c = data.cases.find(function (x) { return x.id === node.dataset.id; });
        if (c) fillClips(node, c);
      });
    }).catch(function () { /* 次の読み込みで直る */ });
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
      document.querySelectorAll('#list .pt-case').forEach(function (node) { renderAuto(node, node.dataset.id); });
      if (finished) refreshCases();
      autoTimer = setTimeout(pollAuto, anyActive ? 2000 : 15000);
    }).catch(function () { autoTimer = setTimeout(pollAuto, 5000); });
  }

  function caseCard(c) {
    var node = $('#tplCase').content.firstElementChild.cloneNode(true);
    node.dataset.id = c.id;
    $('.pt-case-title', node).textContent = c.title || c.id;
    var sub = [c.channel, c.kind === 'youtube' ? 'YouTube' : (c.kind === 'file' ? 'ファイル' : ''),
               'マーク ' + c.marks.total + '(採用 ' + c.marks.adopted + '・書き出し ' + c.marks.exported + ')'];
    if (c.gone) sub.push('スタジオから消えた動画(最後に見えた内容)');
    $('.pt-case-sub', node).textContent = sub.filter(Boolean).join(' ・ ');
    var sel = $('.pt-case-status', node);
    sel.value = c.status || '';
    sel.addEventListener('change', function () {
      api('/api/cases/update', { id: c.id, status: sel.value }).then(function (r) {
        c.status = r.status; toast('状態を「' + STATUS[r.status] + '」にしました', 'ok'); summary();
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

  function visible(c) {
    var fs = $('#fStatus').value, q = $('#fText').value.trim().toLowerCase();
    if (fs === 'none' && c.status) return false;
    if (fs && fs !== 'none' && c.status !== fs) return false;
    if (q && ((c.title || '') + ' ' + (c.channel || '')).toLowerCase().indexOf(q) < 0) return false;
    return true;
  }
  function summary() {
    if (!data) return;
    var n = { '': 0, working: 0, posted: 0, skipped: 0 };
    data.cases.forEach(function (c) { n[c.status || ''] = (n[c.status || ''] || 0) + 1; });
    $('#summary').textContent = '配信 ' + data.cases.length + ' 本(作業中 ' + n.working + '・投稿済み ' + n.posted + '・見送り ' + n.skipped + '・未設定 ' + n[''] + ')';
  }
  function render() {
    var list = $('#list');
    list.textContent = '';
    var shown = data.cases.filter(visible);
    if (!shown.length) list.appendChild(el('p', 'empty', data.cases.length ? '条件に合う配信はありません' : 'まだ配信がありません(切り抜きスタジオで配信を解析すると、ここに出ます)'));
    shown.forEach(function (c) { list.appendChild(caseCard(c)); });
    var ul = $('#unlinked');
    ul.textContent = '';
    data.unlinked.forEach(function (t) {
      var li = el('li', '');
      li.appendChild(el('span', '', (t.title || t.id) + '(校正 ' + t.proofed + '/' + t.segments + '行)'));
      if (t.sourcePath) li.appendChild(el('div', 'hint mono', t.sourcePath));
      ul.appendChild(li);
    });
    $('#unlinkedCount').textContent = data.unlinked.length + ' 件';
    $('#unlinkedBox').hidden = !data.unlinked.length;
    $('#casesFile').textContent = '状態・メモの保存先: ' + (data.casesFile || '');
    summary();
  }
  function load() {
    err('');
    return api('/api/cases').then(function (j) { data = j; render(); })
      .catch(function (e) { err('案件の一覧を読めませんでした: ' + e.message); });
  }

  $('#fStatus').addEventListener('change', render);
  $('#fText').addEventListener('input', function () { if (data) render(); });
  $('#btnReload').addEventListener('click', function () { load().then(function () { toast('読み込み直しました'); }); });
  load().then(pollAuto);
})();
