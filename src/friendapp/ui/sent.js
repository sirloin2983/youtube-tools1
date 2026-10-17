/* 送った物(F3-3。notes:plan/f1-friend-requirements.md の C-2-14〜C-2-16)。行 = GET api/friend/inbox の rows のうち、まだ届け終えていない物と失敗。
   どの行にも [取り消す](作っている・録画中は確認)。進み具合 = 行の steps(friendapp/api.py が progress.text で作った 1 行と段の番号)。
   失敗 = 2 段(上 = 友人の言葉で次にすること・下 = 詳しい文と [コピー])+ [もう一度送る] [消す]。同じ失敗が 2 回目なら [作る人に知らせる]。
   送る欄を開いている間は 1 行に縮む(押すと開く)。別の知らせ(数秒で消える物)は出さない */
(function () {
  'use strict';
  var $, el, api;
  var my = { key: '', open: false, slim: false, details: {} };

  function title(r) { var s = r.source || {}; return s.title || s.fileName || s.videoId || r.id; }
  function hm(ms) { var d = new Date(ms); return d.getHours() + ':' + (d.getMinutes() < 10 ? '0' : '') + d.getMinutes(); }
  function pct(p) { return p && p.total ? Math.floor(p.done * 100 / p.total) : 0; }
  function shown(r) { return !r.cancelled && ['waiting', 'sent', 'making', 'recording', 'failed'].indexOf(r.state) >= 0; }
  function upcoming(r) { var f = r.form || {}; return r.kind === 'live' && f.startAt && f.startAt > Date.now() && (r.live || {}).phase === 'recording' && !r.packs.length; }

  function line(r) {   /* 進み具合の 1 行(と棒の割合 0〜1 か null) */
    if (r.state === 'waiting') return ['アーカイブ待ち(出たら自動で作り始めます)', null];
    if (r.state === 'recording') {
      if (upcoming(r)) return ['録画を予約しました(' + hm(r.form.startAt) + ' から)', null];
      var ph = (r.live || {}).phase;
      return [(ph === 'making' ? '録画は終わりました。残りを作っています' : ph === 'after' ? 'アーカイブから足すのを待っています' : '録画中') + '・届いた ' + r.packs.length + ' 本', null];
    }
    if (r.pc === 'user') {
      var rs = (r.remote || {}).state;
      if (r.state === 'making' || rs === 'accepted') return ['作る人の PC で作っています', null];
      if (rs === 'pending' && r.progress) return ['Dropbox へ動画を上げています(' + pct(r.progress) + '%)', pct(r.progress) / 100];
      return [rs === 'pending' ? '依頼を送っています' : '作る人の PC の受付を待っています' + (r.waitHours >= 1 ? '(' + r.waitHours + ' 時間)' : ''), null];
    }
    if (r.kind === 'file' && !r.runId) return ['動画を写しています(' + pct(r.progress) + '%)', pct(r.progress) / 100];
    var s = r.steps;
    if (!s) return ['順番を待っています', null];
    return [s.text, s.total ? (s.index - 0.5) / s.total : null];
  }
  function cancel(r) {
    var working = r.state === 'making' || r.state === 'recording';
    var go = working ? UIKit.dialog.confirm({ title: r.state === 'recording' ? '録画を取り消します' : '作るのを取り消します',
      body: (r.state === 'recording' ? '録画と、この先の切り抜きを止めます。' : '作っている途中で止めます。') + '届いた物は「受け取る」に残り、作りかけは捨てます。',
      ok: '取り消す', cancel: '続ける', danger: true }) : Promise.resolve(true);
    go.then(function (yes) {
      if (!yes) return;
      api('cancel', { id: r.id }).then(FR.refresh, function (e) { FR.fail('取り消せませんでした', e); });
    });
  }
  function failBox(r, kids, acts) {
    var fl = r.fail || { message: r.error || 'うまくいきませんでした', detail: r.error || '' };
    if (fl.retrying) {
      kids.push(el('div', { cls: 'fr-sent-line', text: fl.code === 'bot' ? '30 分ほどあとに、自動で 1 回だけもう一度試します' : '少し待ってから、自動でもう一度試します' }));
      kids.push(el('div', { cls: 'hint', text: fl.message }));
    } else if (fl.repeat) {
      kids.push(el('div', { cls: 'fr-fail-top', text: fl.reported ? '知らせました。直るまで待ってください' : '直りませんでした。作る人に知らせてください' }));
      if (!fl.reported) acts.push(el('button', { type: 'button', cls: 'btn small primary', on: { click: function (e) {
        e.currentTarget.disabled = true;
        api('report', { id: r.id }).then(FR.refresh, function (er) { FR.fail('知らせられませんでした', er); });
      } } }, ['作る人に知らせる']));
    } else kids.push(el('div', { cls: 'fr-fail-top', text: fl.message }));
    if (fl.detail) {
      var d = el('details', { cls: 'fr-fail-more' });
      if (my.details[r.id]) d.open = true;
      d.addEventListener('toggle', function () { my.details[r.id] = d.open; });
      d.appendChild(el('summary', {}, ['詳しく']));
      d.appendChild(el('p', { cls: 'fr-fail-detail', text: fl.detail }));
      d.appendChild(el('button', { type: 'button', cls: 'btn ghost small', on: { click: function () {
        (navigator.clipboard ? navigator.clipboard.writeText(fl.detail) : Promise.reject(new Error('')))
          .then(function () { UIKit.toast('詳しい文をコピーしました', { ms: 2500 }); }, function () { UIKit.toast('コピーできませんでした', { kind: 'err' }); });
      } } }, ['コピー']));
      kids.push(d);
    }
    if ((!fl.retrying || fl.code === 'bot') && r.form) acts.unshift(el('button', { type: 'button', cls: 'btn small', on: { click: function (e) {
      e.currentTarget.disabled = true;
      api('retry', { id: r.id }).then(FR.refresh, function (er) { FR.fail('送れませんでした', er); FR.refresh(); });
    } } }, ['もう一度送る']));
    acts.push(el('button', { type: 'button', cls: 'btn ghost small', on: { click: function () {
      api('cancel', { id: r.id }).then(FR.refresh, function (er) { FR.fail('消せませんでした', er); });
    } } }, ['消す']));
  }
  function rowEl(r) {
    var vid = (r.source || {}).videoId;
    var thumb = el('span', { cls: 'fr-sent-thumb' });
    if (vid) thumb.appendChild(el('img', { alt: '', loading: 'lazy', src: 'https://i.ytimg.com/vi/' + vid + '/default.jpg' }));
    var kids = [el('div', { cls: 'fr-sent-title', text: title(r), title: title(r) })];
    var who = (r.form || {}).streamer;
    if (who) kids.push(el('div', { cls: 'hint fr-sent-who', text: who }));
    var acts = [];
    if (r.state === 'failed') failBox(r, kids, acts);
    else {
      var ln = line(r);
      kids.push(el('div', { cls: 'fr-sent-line', text: ln[0] }));
      if (ln[1] != null) {
        var bar = el('div', { cls: 'bar fr-sent-bar-prog', role: 'progressbar', 'aria-label': '進み具合', 'aria-valuemin': '0', 'aria-valuemax': '100',
          'aria-valuenow': String(Math.round(ln[1] * 100)) }, [el('i')]);
        bar.firstChild.style.width = Math.round(ln[1] * 100) + '%';
        kids.push(bar);
      }
      if (r.canLocal) acts.push(el('button', { type: 'button', cls: 'btn small', title: '作る人の PC への依頼をやめて、この PC で作ります', on: { click: function () {
        api('local', { id: r.id }).then(FR.refresh, function (e) { FR.fail('この PC でやり直せませんでした', e); });
      } } }, ['この PC で作る']));
      acts.push(el('button', { type: 'button', cls: 'btn ghost small', 'aria-label': title(r) + ' を取り消す', on: { click: function () { cancel(r); } } }, ['取り消す']));
    }
    return el('div', { cls: 'fr-sent-row' + (r.state === 'failed' ? ' failed' : ''), 'data-row': r.id }, [thumb,
      el('div', { cls: 'fr-sent-body' }, kids), el('div', { cls: 'fr-sent-acts' }, acts)]);
  }
  function summary(rows) {
    var work = rows.filter(function (r) { return r.state !== 'failed'; }).length, bad = rows.length - work;
    return (work ? '作っている ' + work + ' 件' : '') + (work && bad ? '・' : '') + (bad ? '失敗 ' + bad + ' 件' : '');
  }
  function render(rows) {
    var list = $('sentList');
    var focusRow = document.activeElement && document.activeElement.closest ? document.activeElement.closest('.fr-sent-row') : null;
    var focusId = focusRow && focusRow.getAttribute('data-row'), focusText = focusId && document.activeElement.textContent;
    list.textContent = '';
    rows.forEach(function (r) { list.appendChild(rowEl(r)); });
    $('sentEmpty').hidden = rows.length > 0;
    $('sentSum').textContent = summary(rows);
    if (focusId) {   /* 描き直しでフォーカスを失わない(押そうとしていたボタンへ戻す) */
      var b = Array.prototype.filter.call(list.querySelectorAll('[data-row="' + focusId + '"] button'), function (x) { return x.textContent === focusText; })[0];
      if (b) b.focus();
    }
  }
  function layout() {   /* 送る欄を開いている間は縮めておく(押すと開く)・閉じている間は開いておく(押すと縮む) */
    var slim = $('sent').classList.contains('slim');
    var open = slim ? my.open : !my.closed;
    $('sentBar').setAttribute('aria-expanded', open ? 'true' : 'false');
    $('sentList').hidden = !open;
    $('sentEmpty').hidden = !open || $('sentList').childNodes.length > 0;
  }
  document.addEventListener('DOMContentLoaded', function () {
    $ = FR.$; el = FR.el; api = FR.api;
    $('sentBar').addEventListener('click', function () { if ($('sent').classList.contains('slim')) my.open = !my.open; else my.closed = !my.closed; layout(); });
    new MutationObserver(function () { my.open = false; layout(); }).observe($('sent'), { attributes: true, attributeFilter: ['class'] });
    FR.on(function (what, d) {
      if (what !== 'data') return;
      var rows = (d.inbox.rows || []).filter(shown);
      var key = JSON.stringify(rows.map(function (r) { return [r.id, r.state, line(r)[0], r.fail, r.canLocal, r.progress && pct(r.progress)]; }));
      if (key !== my.key) { my.key = key; render(rows); }
      layout();
    });
  });
})();
