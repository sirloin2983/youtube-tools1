/* doc-kit.js — 文書(文字起こしの行・話者)の小さな部品(window.EditDoc)。状態は持たない。
   校正の欄(app-*.js。src/app/ui/cases/edhost.js が読む)とカット・パックのパネル(src/app/ui/cases/panels/cut.js)が同じ物を使う。
   どちらも、ほかの部品より先に読む */
(function () {
  'use strict';

  /* 組み込みの話者「ゲーム音声など」(ゲームのキャラ・NPC・動画の音声など、その場かぎりの声)。サーバーの ed_state.OTHER_SPK_* と同じ値(変えるときは両方)。
     話者の選択の候補に常に出し(話者なしの次・文書の話者より前)、選ぶと文書の speakers に 1 つだけ足す。名前は変えられない・声を覚えない・Alt+数字の番号に入らない。
     この話者を付けた行は「字幕に出さない」(行の印 noSub)が自動でオン、別の話者へ変えるとオフ */
  const OTHER_SP = Object.freeze({ id: 'other', name: 'ゲーム音声など', builtin: 'other', color: '#8a8f98' });
  const isOtherSp = sp => !!sp && sp.id === OTHER_SP.id;

  function fmtT(t, ms) {
    t = Math.max(0, Number(t) || 0);
    const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
    const ss = ms ? s.toFixed(1).padStart(4, '0') : String(Math.floor(s)).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
  }
  /* 1/100 秒まで(0:28.60) */
  function fmtCs(t) {
    t = Math.max(0, Number(t) || 0);
    const cs = Math.round(t * 100), h = Math.floor(cs / 360000), m = Math.floor(cs % 360000 / 6000), sec = (cs % 6000) / 100;
    return (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + sec.toFixed(2).padStart(5, '0');
  }
  /* 行に文字があるか(空白だけは数えない・text の無い行でも落ちない) */
  const hasText = g => !!String(g && g.text || '').trim();
  const uid = () => 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  /* 行の並び(開始時刻の順)で、開始が t 以前の最後の行の添字(無ければ -1。二分探索) */
  function segIndexAt(segs, t) {
    let lo = 0, hi = segs.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (segs[m].start <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans;
  }
  /* 話者の字幕の色(sub.color。"#RRGGBB" か '')。文書の JSON は手で直せるので形を確かめる(style 属性に入れるため) */
  function subColorOf(sp) {
    const c = sp && sp.sub && typeof sp.sub === 'object' ? String(sp.sub.color || '') : '';
    return /^#[0-9a-fA-F]{6}$/.test(c) ? c.toUpperCase() : '';
  }

  /* 行の「残す / カット」の 2 択のボタン。act = [残す側, カット側] の data-act、dis = ' disabled' など */
  const KEEP_TITLE = 'この行を残す', CUT_TITLE = 'この行をカット済にする(Resolve の仮編集から外します。元の素材は残るので、あとで「残す」に戻せます)';
  function keepCutHTML(cut, act = ['keep', 'cut'], dis = '') {
    return `<span class="tt-kc" role="group" aria-label="この行を残すかカットするか"><button type="button" data-act="${act[0]}" aria-pressed="${cut ? 'false' : 'true'}" title="${KEEP_TITLE}"${dis}>残す</button>`
      + `<button type="button" data-act="${act[1]}" aria-pressed="${cut ? 'true' : 'false'}" title="${UIKit.esc(CUT_TITLE)}"${dis}>カット</button></span>`;
  }

  /* ---------- 重なる行の字幕 ----------
     校正の映像の上(#playerCaption)とカットのプレビュー(#cutCaption)が同じ関数を使う */
  const CAP_SCAN = 40;   // 再生位置より前に始まった行を何行さかのぼって見るか(長い行が続く所でも足りる数。全部は見ない)
  const CAP_OVERLAP_MIN = 0.3, CAP_MAX_STACK = 3;
  const capOk = g => hasText(g) && !g.noSub;
  const capOverlap = (a, b) => Math.min(a.end, b.end) - Math.max(a.start, b.start);

  /* 時刻 t に出す字幕の行(添字。下の段 → 上の段の順)。重なりが CAP_OVERLAP_MIN 秒以上の行どうしは両方(開始が早い方を下・同時開始は話者の並び順・
     CAP_MAX_STACK 段まで。それより多ければ 3 段目は開始がいちばん遅い行)。それより短い重なりは今までどおり後の行だけ。
     opt.primary: 今の行(校正の S.curIdx。行の終わりの少し後まで残る)。opt.skip(i): 出さない行(カット後の見え方で削った行)。opt.speakers: 文書の話者(並び順に使う) */
  function capStack(segs, t, opt = {}) {
    const ok = i => capOk(segs[i]) && !(opt.skip && opt.skip(i));
    const last = segIndexAt(segs, t), on = [];
    for (let i = last; i >= 0 && i > last - CAP_SCAN; i--) if (t < segs[i].end && ok(i)) on.push(i);
    const p = opt.primary;
    let top = on.length ? on[0] : -1;   // 開始がいちばん遅い行(後の行に切り替わる)
    if (p != null && p >= 0 && ok(p) && (top < 0 || segs[p].start >= segs[top].start)) top = p;
    if (top < 0) return [];
    const spIdx = id => { const k = (opt.speakers || []).findIndex(s => s.id === id); return k < 0 ? 99 : k; };
    const out = on.filter(i => i !== top && capOverlap(segs[i], segs[top]) >= CAP_OVERLAP_MIN).concat([top])
      .sort((a, b) => segs[a].start - segs[b].start || spIdx(segs[a].speaker) - spIdx(segs[b].speaker) || a - b);
    return out.length > CAP_MAX_STACK ? out.slice(0, CAP_MAX_STACK - 1).concat(out.slice(-1)) : out;
  }

  /* 字幕の箱に行を描く。1 行なら箱の文字と色。2 行以上は 1 行ずつの span(上の段が先 = 開始が遅い行)に話者の色(hexOf(行) = メンバーカラー。無ければ '')。
     同じ中身なら描き直さない(再生中は timeupdate のたびに呼ばれる) */
  function paintCaps(el, idxs, segs, hexOf) {
    const items = idxs.map(i => ({ text: String(segs[i].text || '').trim(), hex: segs[i].speaker ? hexOf(segs[i]) : '' })).filter(x => x.text);
    const key = JSON.stringify(items);
    if (el.dataset.capKey === key) return;
    el.dataset.capKey = key;
    el.hidden = !items.length;
    if (items.length <= 1) {
      const x = items[0];
      el.textContent = x ? x.text : '';
      if (x && x.hex) el.style.setProperty('--tt-cap-color', x.hex); else el.style.removeProperty('--tt-cap-color');   // 無ければ配信者の色(pack-tab.js が入れる)のまま
      return;
    }
    el.style.removeProperty('--tt-cap-color');
    el.innerHTML = items.slice().reverse().map(x => `<span class="tt-cap-line"${/^#[0-9a-fA-F]{6}$/.test(x.hex) ? ` style="--tt-cap-color:${x.hex}"` : ''}>${UIKit.esc(x.text)}</span>`).join('');
  }

  window.EditDoc = { OTHER_SP, isOtherSp, fmtT, fmtCs, hasText, uid, segIndexAt, subColorOf, keepCutHTML, capStack, paintCaps };
})();
