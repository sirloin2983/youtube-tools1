/* 案件の画面の「校正」のパネル(#proof。切り抜き 1 本の文字起こしの行を直す)。口の形は cases.js の先頭の説明。RS8 C2b。
   中身は今の編集の「1 文字起こし」そのもの(app-*.js・app.js を包まずに読み、欄を移して見せる = edhost.js の EditHost)。
   行の編集・保存と 409・行の道具・話者・札・キー(今のキーのまま。殻が先に Alt+1 / Alt+2 / Shift+N を取る)・UIKit.life(離れたら保存)は編集のコードが持つ。
   ここが持つのは: ctx.docId の文書を開く(別の切り抜きを選んだら保存してから切り替え・保存できなければ選び直さない)・開けない / 文字起こし前の案内・
   小さい配信のプレーヤー(DESIGN_BRIEF 2-2。元の配信(YouTube)のこの切り抜きの前後 30 秒。押したときだけ読む)・3 択(panels/machpick.js。キー Shift+C)。
   パネルの中の要素は root.querySelector で引く(document.getElementById・document.querySelector は使わない)。編集の名前(S・openDoc・saveDoc …)は edhost が読み込んだあとだけ使う */
(function () {
  'use strict';
  var STREAM_KEY = 'cases.proof.stream';   // 配信のプレーヤーを出すか(このブラウザの好み)
  var YT_ID = /^[A-Za-z0-9_-]{11}$/, PAD = 30;
  var esc = function (s) { return UIKit.esc(s); };
  function streamWanted() { try { return localStorage.getItem(STREAM_KEY) === '1'; } catch (e) { return false; } }
  function setStreamWanted(on) { try { localStorage.setItem(STREAM_KEY, on ? '1' : '0'); } catch (e) { /* 覚えられなくても今の画面は変える */ } }
  function proofedOf(d) { return d ? d.segments.filter(function (g) { return g.proofed && String(g.text || '').trim(); }).length : 0; }

  window.CasesPanels.define('proof', function () {
    var H = window.EditHost, root = null, ctx = null, alive = false, seq = 0, mp = null, attached = false, mcN = 0;
    var q = function (sel) { return root ? root.querySelector(sel) : null; };

    /* ---- 案内(文字起こし前・読み込み中・開けない)---- */
    function status(html) {
      var b = q('[data-pf-status]');
      b.innerHTML = html || '';
      b.hidden = !html;
    }
    function failHtml(e) {
      var again = e && e.reload ? '<button type="button" class="btn primary small" data-pf-reload>画面を読み込み直す</button>' : '<button type="button" class="btn primary small" data-pf-retry>もう一度</button>';
      return '<div class="empty" data-pf-fail><b>校正の欄を開けませんでした</b><span>' + esc((e && e.message) || '') + '</span><div class="row">' + again + '</div></div>';
    }

    /* ---- 欄をこのパネルへ / 隠し場所へ ---- */
    function attach() {
      if (attached) return;
      H.attach(q('[data-pf-host]'), function () { if (ctx) ctx.refreshKeys(); });
      attached = true;
      if (!mp) {
        mp = window.CasesMachPick.create({
          api: function (tool, path, opt) { return ctx.api(tool, path, opt); },
          segs: function () { return q('#segs'); }, doc: function () { return S.doc; }, docId: function () { return S.docId; },
          base: function () { return S.baseUpdatedAt; }, save: function () { return saveDoc(); },
          reload: function () { return openDoc(S.docId, true); }, goto: function (i) { gotoRow(i, { center: true }); },
          onCount: function (n) { mcN = n; paintTools(); if (ctx) { ctx.setHint(n ? '機械の結果が変わった行が ' + n + ' 行あります' : ''); ctx.refreshKeys(); } }
        });
      }
    }
    function detach() {
      if (!attached) return;
      var t = H.tools(), s = q('[data-pf-streambox]');
      if (s) s.remove();   // 配信の再生を止める(枠ごと外す)
      if (t) t.innerHTML = '';
      if (mp) { mp.stop(); mp = null; }
      H.detach();
      attached = false;
    }
    /* 校正済みの行の数が一覧(④)と変わった = 左の一覧の札を読み直す */
    function syncRail() { var tx = ctx && ctx.item && ctx.item.tx; if (tx && S.docId === tx.id && proofedOf(S.doc) !== tx.proofed) ctx.reload(); }

    /* ---- 開く ---- */
    function show(c) {
      ctx = c;
      var id = c.docId, my = ++seq;
      if (!id) {
        detach();
        status('<div class="empty" data-pf-none><b>この切り抜きはまだ文字起こししていません</b><span>文字起こしすると、ここで行の文字・話者・時刻を直せます。</span></div>');
        return;
      }
      if (!attached) status('<p class="hint" data-pf-loading>校正の欄を読み込んでいます…</p>');
      H.ensure().then(function () {
        if (!alive || my !== seq) return;
        attach();
        return window.CasesPanels.settled().then(function () {   // カット・パックのパネルが閉じるときに送った保存を待ってから読む(RS8 C4)
          if (!alive || my !== seq) return;
          return openFor(id, my);
        });
      }).catch(function (e) {
        if (!alive || my !== seq) return;
        detach();
        status(failHtml(e));
      });
    }
    function openFor(id, my) {
      var fresh = S.docId === id;
      if (fresh && (S.dirty || S.saving || S.conflict)) { status(''); return afterOpen(); }
      var prev = fresh ? '' : S.docId;
      if (!fresh && prev) syncRail();
      H.opening = true;
      return openDoc(id, fresh).then(function (ok) {   // 同じ文書 = 読み直す(カット・パックのパネルが字幕の時刻を直したかもしれない)
        H.opening = false;
        if (!alive || my !== seq) return;
        if (ok) { status(''); afterOpen(); return; }
        if (fresh) { status(''); afterOpen(); return; }
        if (prev && S.docId === prev) {   // 前の切り抜きを保存できない(競合など)= 切り替えない
          UIKit.toast('前の切り抜きの保存が終わっていないため、切り替えませんでした(校正の欄の上の案内から選んでください)', { kind: 'err', ms: 7000 });
          if (window.CasesShell) window.CasesShell.select('d:' + prev, 'proof');
          return;
        }
        status(failHtml({ message: '文字起こしを読み込めませんでした。少し待ってから「もう一度」を押してください' }));
      }, function (e) { H.opening = false; throw e; });
    }
    function afterOpen() {
      paintTools();
      if (mp) mp.refresh();
      if (ctx) ctx.refreshKeys();
    }

    /* ---- 上の帯の道具(機械が変わった行・配信のプレーヤー)と、小さい配信のプレーヤー ---- */
    function paintTools() {
      var t = H.tools();
      if (!t || !attached) return;
      t.innerHTML = (mcN ? '<button type="button" class="btn small cs-mc-count" data-pf-mc title="最初の行へ移って比べます(Shift+C)">機械が変わった行 <b>' + mcN + '</b></button>' : '') +
        '<button type="button" class="btn ghost small" data-pf-stream hidden></button>';
      renderStream();
    }
    function streamInfo() {
      var c = (ctx && ctx.case) || {}, cl = ctx && ctx.item && ctx.item.clip;
      if (!ctx || ctx.caseKind !== 'stream' || c.kind === 'live' || c.kind === 'file' || !YT_ID.test(String(ctx.videoId || '')) || !cl || typeof cl.start !== 'number') return null;
      var end = typeof cl.end === 'number' && cl.end > cl.start ? cl.end : cl.start;
      return { id: ctx.videoId, start: Math.max(0, Math.floor(cl.start - PAD)), end: Math.ceil(end + PAD) };
    }
    function renderStream() {
      var info = attached ? streamInfo() : null, on = !!info && streamWanted(), btn = q('[data-pf-stream]'), sec = q('[data-pf-streambox]'), stage = q('.tx-stage');
      if (btn) {
        btn.hidden = !info;
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.textContent = on ? '配信のプレーヤーを隠す' : '配信のプレーヤーを出す';
        btn.title = 'この切り抜きの元の配信(YouTube)を、前後 ' + PAD + ' 秒まで小さく出します';
      }
      if (!on || !stage) { if (sec) sec.remove(); return; }
      if (!sec) {
        sec = document.createElement('section');
        sec.className = 'card cs-pf-stream'; sec.setAttribute('data-pf-streambox', ''); sec.setAttribute('aria-label', '配信(この切り抜きの前後)');
        var pbox = stage.querySelector('.pbox');
        stage.insertBefore(sec, pbox ? pbox.nextSibling : stage.firstChild);
      }
      var src = 'https://www.youtube-nocookie.com/embed/' + info.id + '?start=' + info.start + '&end=' + info.end + '&rel=0&playsinline=1';
      if (sec.getAttribute('data-src') === src) return;
      sec.setAttribute('data-src', src);
      sec.innerHTML = '<div class="cs-pf-stream-h"><b>配信(この切り抜きの前後 ' + PAD + ' 秒まで)</b><span class="hint mono">' + esc(UIKit.fmt.dur(info.start)) + '〜' + esc(UIKit.fmt.dur(info.end)) + '</span></div>' +
        '<div class="cs-pf-stage"><iframe src="' + esc(src) + '" title="配信のプレーヤー(YouTube)" allow="encrypted-media; picture-in-picture" allowfullscreen ' +
        'referrerpolicy="strict-origin-when-cross-origin" sandbox="allow-scripts allow-same-origin allow-presentation allow-popups"></iframe></div>';
    }

    function onClick(e) {
      var t = e.target.closest ? e.target.closest('[data-pf-retry],[data-pf-reload],[data-pf-mc],[data-pf-stream]') : null;
      if (!t) return;
      if (t.hasAttribute('data-pf-retry')) show(ctx);
      else if (t.hasAttribute('data-pf-reload')) location.reload();
      else if (t.hasAttribute('data-pf-mc')) { if (mp) mp.first(); }
      else { setStreamWanted(!streamWanted()); renderStream(); }
    }

    return {
      id: 'proof',
      mount: function (el, c) {
        alive = true;
        el.innerHTML = '<div class="cs-pf" data-cs-proof><div class="cs-pf-status" data-pf-status hidden></div><div class="cs-pf-host" data-pf-host></div></div>';
        root = el.firstChild;
        root.addEventListener('click', onClick);
        show(c);
      },
      update: function (c) {
        if (!root) return;
        if (c.docId === (ctx && ctx.docId)) { ctx = c; if (attached) renderStream(); return; }
        show(c);
      },
      unmount: function () {
        alive = false; seq++;
        if (attached) syncRail();
        detach();
        if (root) root.removeEventListener('click', onClick);
        root = null;
      },
      /* Shift+C = 選んだ行の 3 択の欄を開く・閉じる(選んだ行に印が無ければ最初の印の行へ)。ほかのキーは編集の keydown が受ける(false を返す) */
      keys: function (e) {
        if (!attached || !mp || !mcN || !e.shiftKey || e.altKey || e.ctrlKey || e.metaKey || (e.key !== 'C' && e.key !== 'c')) return false;
        var c = rowAndSeg();
        if (!(c && mp.openAt(c.i))) mp.first();
        return true;
      },
      keybar: function () { return attached ? H.items.concat(mcN ? [{ k: 'Shift+C', l: '機械の結果を比べる' }] : []) : []; },
      leave: function (reason) {
        if (!attached) return;
        try { saveDoc(); if (reason !== 'blur') player().pause(); } catch (e) { /* 編集が起動できていない */ }
      }
    };
  });
})();
