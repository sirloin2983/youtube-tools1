/* 校正のパネルの 3 択(RS8 C2b。作り方 notes:docs/design/rs8-cases-build.md の 4 節・決定 3-37 の案 A)。
   機械の結果が変わって人の直しと食い違う行(印「機械の結果が変わりました」= layers.MACH_CHANGED)に札を付け、押すと(キー Shift+C も)行の下に
   前の機械 / 今の機械 / あなたの直し を並べ、[自分の直しのまま](既定)/ [今の機械にする] を選ぶ。
   口は編集のサーバー GET transcribe/api/mach-changes?id= と POST transcribe/api/mach-changes/pick {id, row, pick, baseUpdatedAt}(src/human/proof/machpick.py)。
   行の一覧(#segs)は編集が描き直すので、描き直しのたびに(MutationObserver)札と開いた欄を付け直す。開いた行は覚えておく。
   CasesMachPick.create(env) -> {refresh, stop, count, openAt(i), first()}。env = {api, segs() = 行の一覧の要素, doc() = 開いている文書, docId(), base(),
   save() = 保存し終えるまで, reload() = 文書を読み直す, goto(i) = その行へ, onCount(n)}。DOM は env.segs() の中だけを触る */
(function () {
  'use strict';
  var esc = function (s) { return UIKit.esc(s); };
  var LABEL = '機械の結果が変わりました';
  var WHY = { conflict: '別の所で先に変わりました。「読み込み直す」を押してから、もう一度選んでください',
    not_changed: 'この行の印はもうありません(別の所で選んだか、機械が元に戻りました)。読み込み直すと消えます' };

  function texts(rows) {
    var t = (rows || []).map(function (r) { return String(r && r.text || '').trim(); }).filter(Boolean).join(' / ');
    return t || '(文字なし)';
  }

  window.CasesMachPick = {
    create: function (env) {
      var rows = {}, order = [], open = {}, err = {}, busy = false, seq = 0, docObj = null, mo = null, raf = 0, stopped = false;

      function count() { return order.length; }
      function idxOf(id) { var d = env.doc(); return d ? d.segments.findIndex(function (s) { return s.id === id; }) : -1; }
      function boxHTML(r) {
        var e = err[r.id];
        return '<div class="cs-mc" data-mc-box="' + esc(r.id) + '" role="group" aria-label="機械の結果が変わった行を比べる">' +
          '<div class="ui-pair">' +
            '<div class="ui-pair-opt"><span class="ui-pair-lb">前の機械</span><p>' + esc(texts(r.before)) + '</p></div>' +
            '<div class="ui-pair-opt"><span class="ui-pair-lb">今の機械</span><p>' + esc(texts(r.now)) + '</p></div>' +
            '<div class="ui-pair-opt is-accent"><span class="ui-pair-lb">あなたの直し</span><p>' + esc(r.human && r.human.text || '(文字なし)') + '</p></div>' +
          '</div>' +
          '<div class="row cs-mc-acts"><button type="button" class="btn small primary" data-mc-pick="mine" title="あなたの直しを残し、今の機械の結果を見たことにします(印が外れます)">自分の直しのまま</button>' +
            '<button type="button" class="btn small" data-mc-pick="machine" title="あなたの直し(文字・時刻・話者・校正済み)を外して、今の機械の行にします。「以前の版に戻す」で戻せます">今の機械にする</button>' +
            '<button type="button" class="btn small ghost" data-mc-close>閉じる</button></div>' +
          (e ? '<div class="notice err cs-mc-err" role="alert"><span>' + esc(e) + '</span> <button type="button" class="btn small" data-mc-reload>読み込み直す</button></div>' : '') +
        '</div>';
      }
      /* 札と開いた欄を今の行の一覧に合わせる(描き直されたあと・数が変わったあと) */
      function paint() {
        raf = 0;
        var host = env.segs(), d = env.doc();
        if (!host || !d) return;
        var on = count() > 0, segs = host.children;
        for (var i = 0; i < segs.length; i++) {
          var row = segs[i];
          if (!row.classList || !row.classList.contains('seg')) continue;
          var s = d.segments[Number(row.dataset.i)], r = on && s ? rows[s.id] : null;
          var tag = row.querySelector('[data-mc-tag]'), box = row.querySelector('[data-mc-box]');
          row.classList.toggle('cs-mc-row', !!r);
          if (!r) { if (tag) tag.remove(); if (box) box.remove(); continue; }
          if (!tag) {
            tag = document.createElement('button');
            tag.type = 'button'; tag.className = 'btn small cs-mc-tag'; tag.setAttribute('data-mc-tag', s.id);
            tag.title = '前の機械・今の機械・あなたの直しを比べて選びます(Shift+C)';
            tag.textContent = LABEL;
            row.appendChild(tag);
          }
          tag.setAttribute('aria-expanded', open[s.id] ? 'true' : 'false');
          if (open[s.id]) {
            var html = boxHTML(r);
            if (!box || box.getAttribute('data-html') !== html) {
              if (box) box.remove();
              row.insertAdjacentHTML('beforeend', html);
              row.lastElementChild.setAttribute('data-html', html);
            }
          } else if (box) box.remove();
        }
      }
      function soon() { if (!raf && !stopped) raf = requestAnimationFrame(paint); }

      function refresh() {
        var id = env.docId(), my = ++seq;
        docObj = env.doc();
        if (!id) { rows = {}; order = []; env.onCount(0); soon(); return Promise.resolve(); }
        return env.api('transcribe', 'api/mach-changes?id=' + encodeURIComponent(id), { timeout: 30000 }).then(function (j) {
          if (my !== seq || stopped) return;
          rows = {}; order = [];
          ((j && j.rows) || []).forEach(function (r) { if (r && r.id) { rows[r.id] = r; order.push(r.id); } });
          Object.keys(open).forEach(function (k) { if (!rows[k]) delete open[k]; });
          env.onCount(count());
          soon();
        }, function () {
          if (my !== seq) return;
          rows = {}; order = []; env.onCount(0); soon();   // 読めなければ札を出さない(古い編集のサーバーなど)。校正はそのまま続けられる
        });
      }
      function toggle(id, want) {
        if (!rows[id]) return false;
        open[id] = want === undefined ? !open[id] : !!want;
        if (!open[id]) delete err[id];
        paint();
        return true;
      }
      function pick(id, which) {
        if (busy || !rows[id]) return;
        busy = true; delete err[id];
        var hs = env.segs(), btns = hs ? hs.querySelectorAll('[data-mc-box] button') : [];
        for (var i = 0; i < btns.length; i++) btns[i].disabled = true;
        env.save().then(function (ok) {
          if (!ok) throw Object.assign(new Error('保存が終わっていないため選べませんでした。上の案内を見てから、もう一度押してください'), { code: 'save' });
          return env.api('transcribe', 'api/mach-changes/pick', { body: { id: env.docId(), row: id, pick: which, baseUpdatedAt: env.base() } });
        }).then(function () {
          delete open[id];
          UIKit.toast(which === 'mine' ? '自分の直しのままにしました' : '今の機械の行にしました(「以前の版に戻す」で戻せます)', { kind: 'ok', ms: 4000 });
          return env.reload();
        }).then(function () { return refresh(); }, function (e) {
          err[id] = WHY[e && e.code] || ('選べませんでした: ' + (e && e.message || ''));
          paint();
        }).then(function () { busy = false; paint(); });
      }

      var host0 = env.segs();
      function onClick(e) {
        var t = e.target.closest ? e.target.closest('[data-mc-tag],[data-mc-pick],[data-mc-close],[data-mc-reload]') : null;
        if (!t) return;
        var row = t.closest('.seg'), d = env.doc(), s = row && d ? d.segments[Number(row.dataset.i)] : null;
        if (!s) return;
        e.stopPropagation();
        if (t.hasAttribute('data-mc-tag')) toggle(s.id);
        else if (t.hasAttribute('data-mc-close')) toggle(s.id, false);
        else if (t.hasAttribute('data-mc-reload')) { delete err[s.id]; env.reload().then(refresh); }
        else pick(s.id, t.getAttribute('data-mc-pick'));
      }
      if (host0) {
        host0.addEventListener('click', onClick, true);   // 編集の行のクリック(data-act)より先に。札と欄のボタンは data-act を持たない
        mo = new MutationObserver(function () {
          if (env.doc() !== docObj) refresh();   // 文書を読み直した(機械が行を書き換えた・別の文書)= 数え直す
          else soon();
        });
        mo.observe(host0, { childList: true });
      }

      return {
        refresh: refresh,
        count: count,
        /* i 行目の欄を開く(閉じる)。印の無い行なら false */
        openAt: function (i) { var d = env.doc(), s = d && d.segments[i]; return !!s && toggle(s.id); },
        /* 最初の印の行へ移って欄を開く */
        first: function () {
          if (!order.length) return;
          var i = idxOf(order[0]);
          if (i < 0) return;
          env.goto(i);
          toggle(order[0], true);
        },
        stop: function () {
          stopped = true; seq++;
          if (mo) mo.disconnect();
          if (host0) host0.removeEventListener('click', onClick, true);
          if (raf) cancelAnimationFrame(raf);
          open = {}; rows = {}; order = []; paint();
        }
      };
    }
  };
})();
