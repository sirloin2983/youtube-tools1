/* 切り抜きスタジオ ③ 確認・書き出し(切り抜きマーカー由来)。
   Studio.review = { open(id), refresh() }。データはすべてサーバー保存(PUT /api/video)。UI設定は /api/settings の settings.review。 */
(() => {
'use strict';
const Studio = window.Studio;
if (!Studio) return;
const esc = Studio.esc;
const $ = s => document.querySelector(s);
const enc = encodeURIComponent;
const round1 = x => Math.round(x * 10) / 10;
const uid = () => Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-4);
const toast = (m, ms, kind) => Studio.toast(m, ms, kind);

/* ---------- 時刻ユーティリティ ---------- */
const fmt = Studio.fmtTime;
function parseTime(str){
  str = String(str).trim().replace(/[：]/g, ':');
  if (!str) return NaN;
  const parts = str.split(':');
  if (parts.length > 3) return NaN;
  let t = 0;
  for (const p of parts){ if (!/^\d+(\.\d+)?$/.test(p)) return NaN; t = t * 60 + parseFloat(p); }
  return t;
}
function looksLikeYouTube(s){
  s = String(s).trim();
  return /^[\w-]{11}$/.test(s) || /(?:youtu\.be\/|youtube\.com\/|[?&]v=)/i.test(s);
}

/* ---------- 定数・設定 ---------- */
const MAX_MARKS = 500, MAX_MARK_SEC = 3600;
const STATUS_LABEL = { '': '候補', adopted: '採用', rejected: '不採用', exported: '書き出し済み' };
const FILTERS = [['all', '全部'], ['', '候補'], ['adopted', '採用'], ['rejected', '不採用'], ['exported', '書き出し済み']];
const isAutoLike = m => m.src === 'auto' || m.score != null || (m.reasons && m.reasons.length > 0);
const marksPayload = ms => ms.map(m => { const { auto0, ...r } = m; return r; });
/* markIn/markOut/playPause/back5/fwd5/back1/fwd1 は全ツール共通の再生キー(Space・J/K/L・← →・I/O。UIKit.keys.playback)に
   吸収されたので、ここでは変更できる操作から外した(共通キーと別のキーを割り当てても、共通キーが先に処理して silently 上書きされていたため) */
const ACTION_DEFS = [
  ['addClip', 'マーク追加'], ['quickMark', '今をマーク①'], ['quickMark2', '今をマーク②'], ['quickMark3', '今をマーク③'], ['quickMark4', '今をマーク④'], ['quickMark5', '今をマーク⑤'],
  ['volUp', '音量+'], ['volDown', '音量−'], ['mute', 'ミュート'], ['theater', 'シアター'],
  ['prevMark', '前のマークへ'], ['nextMark', '次のマークへ'], ['adopt', '採用'], ['reject', '不採用'], ['moment', '一瞬を切り取る']
];
const KEY_PRESETS = {
  standard: { addClip: 'a', quickMark: 'n', quickMark2: '2', quickMark3: '3', quickMark4: '4', quickMark5: '5', volUp: 'ArrowUp', volDown: 'ArrowDown', mute: 'm', theater: 't', prevMark: '[', nextMark: ']', adopt: 'y', reject: 'u', moment: 'c' },
  left: { addClip: 'e', quickMark: 'r', quickMark2: '2', quickMark3: '3', quickMark4: '4', quickMark5: '5', volUp: 'f', volDown: 'v', mute: 'x', theater: 't', prevMark: 'g', nextMark: 'b', adopt: '1', reject: '6', moment: 'c' }
};
const sec1 = (v, d) => (Number.isFinite(Number(v)) && v !== null && v !== '' ? Math.min(60, Math.max(0, Math.round(Number(v) * 10) / 10)) : d);
function sanitizeKeymap(x){
  const out = {}, used = new Set();
  for (const [id] of ACTION_DEFS){
    let k = x && typeof x === 'object' && typeof x[id] === 'string' ? x[id].slice(0, 24) : KEY_PRESETS.standard[id];
    if (k && used.has(k)) k = ''; // 重複は後ろの割り当てを外す
    if (k) used.add(k); out[id] = k;
  }
  return out;
}
const QUICK_SPAN_CHOICES = [10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300, 420, 600];
const DEFAULT_QUICK_SPANS = [30, 60, 120, 180, 300];
const spanLabel = sec => sec >= 60 && sec % 60 === 0 ? sec / 60 + '分' : sec + '秒';
/* ライブの録画: 書き出したあと(入口の POST /live/api/export の after)。何もしない / 文字起こしまで(まとめて実行の ② 軽く確認)/ 全自動(文字起こし → パック。① 全自動) */
const LIVE_AFTERS = ['none', 'check', 'auto'];
const DEFAULT_SETTINGS = { volume: 100, muted: false, quickSpans: DEFAULT_QUICK_SPANS, keymap: KEY_PRESETS.standard, lag: 0, liveMode: 'auto', precision: 'accurate', maxHeight: 1080, exportVolume: 75, exportLoudness: -14, theater: false, graphLines: false, autoPlay: true, autoNext: true, exportTarget: 'adopted', sortBy: 'time', foldDefault: false, liveAutoExport: true, liveDuck: 'low' };
function sanitizeSettings(x){
  x = x && typeof x === 'object' ? x : {};
  const n = (v, lo, hi, d) => Number.isFinite(Number(v)) ? Math.min(hi, Math.max(lo, Math.round(Number(v)))) : d;
  const autoTx = typeof x.autoTx === 'boolean' ? x.autoTx : autoTxLegacy() !== false;
  return {
    volume: n(x.volume, 0, 100, 100), muted: !!x.muted,
    quickSpans: DEFAULT_QUICK_SPANS.map((d, i) => { const v = Array.isArray(x.quickSpans) ? Number(x.quickSpans[i]) : NaN; return Number.isFinite(v) ? Math.min(600, Math.max(5, Math.round(v))) : d; }),
    liveMode: ['auto', 'on', 'off'].includes(x.liveMode) ? x.liveMode : 'auto',
    precision: x.precision === 'fast' ? 'fast' : 'accurate',
    maxHeight: [0, 720, 1080, 1440, 2160].includes(Number(x.maxHeight)) ? Number(x.maxHeight) : 1080,
    exportVolume: n(x.exportVolume, 1, 200, 75),
    exportLoudness: [0, -11, -14, -16, -18].includes(Number(x.exportLoudness)) ? Number(x.exportLoudness) : -14,   // 0 = そろえない(音量(%)を使う)
    keymap: sanitizeKeymap(x.keymap), theater: x.theater === true, graphLines: x.graphLines === true,
    autoPlay: x.autoPlay !== false, autoNext: x.autoNext !== false, foldDefault: x.foldDefault === true,
    exportTarget: ['adopted', 'pending', 'all'].includes(x.exportTarget) ? x.exportTarget : 'adopted', sortBy: x.sortBy === 'score' ? 'score' : 'time',
    lag: [0, 2, 3, 5].includes(Number(x.lag)) ? Number(x.lag) : 0,
    momentBefore: sec1(x.momentBefore, 2), momentAfter: sec1(x.momentAfter, 3),   // 一瞬をマーク(C)の前・後の秒数
    liveAutoExport: x.liveAutoExport !== false,   // ライブの録画: マークしたらすぐ書き出す(既定オン。線 D の P3)
    liveDuck: ['low', 'mute', 'off'].includes(x.liveDuck) ? x.liveDuck : 'low',   // ライブの録画: ほかの窓(編集)で再生している間の配信の音(下げる / 消す / そのまま)
    /* 書き出しのあと自動で文字起こし(設定の「書き出し」節。入口から開いたときだけ効く。既定オン)。0.22.0 でこのブラウザ(localStorage の ytt:studio.autoTx)から
       この節(サーバー)へ移した(窓とブラウザで値が変わらないように)。サーバーにまだ無いときは、前のこのブラウザの値を引き継ぐ(loadSettings が1回だけ送る) */
    autoTx,
    /* ライブの録画: 書き出したあと。まだ選んでいなければ、「書き出しのあと自動で文字起こし」(autoTx)がオンなら文字起こしまで・オフなら何もしない */
    liveAfter: LIVE_AFTERS.includes(x.liveAfter) ? x.liveAfter : (autoTx ? 'check' : 'none')
  };
}

/* ---------- 状態 ---------- */
const S = {
  videos: [], cur: null, series: null, sel: null, filter: 'all', fold: new Map(), seen: new Set(),
  now: 0, duration: 0, playerState: -1, playerAlive: false, rate: 1, draft: { start: null, end: null }, previewEnd: null,
  settings: sanitizeSettings({}), live: false, job: null, lastJob: null,
  ytReadyMs: 20000,   // YT.Player を作ってから onReady が来るまでの待ち(5-7。テストで短くする)
  loadSeq: 0, editSeq: 0, dirty: false, built: false,
  tx: null, txOpen: new Set(), txSeq: 0,   // 書き出したマークのセリフ(「編集」の文字起こしのデータ。/api/transcripts)
  join: new Set(),   // つなげて1本にするマーク(チェックしたもの。配信を切り替えたら空に)
  expDockClosed: false, expModal: null   // 書き出しの欄(ui-drawer)。× で閉じたら次の配信を開くまで自動で開き直さない・今 modal で開いているか
};
const marks = () => (S.cur ? S.cur.marks : []);
const sortedMarks = () => [...marks()].sort((a, b) => a.start - b.start || (a.id < b.id ? -1 : 1));
const visible = () => Studio.step === 'review' && !document.hidden;

/* ---------- 画面の組み立て ---------- */
/* id はすべて従来のまま(JS・テストが参照する)。見た目は ui-kit の部品(card / btn / pill / ui-seg / btn-group)に寄せ、配置だけ review.css に書く */
const SVG = {
  theater: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 9h20"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.9l10.2-6.5a1 1 0 0 0 0-1.7L9.5 4.6A1 1 0 0 0 8 5.5z"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>'
};
const PICK_FILTERS = [['all', 'すべて'], ['cand', '判定待ちの候補がある'], ['adopt', '書き出し待ちの採用がある'], ['done', '書き出し済みがある'], ['none', 'マークがない']];
/* 上の行: 配信の選択(探す・開く)・保存の状態・まとめて実行・シアター・配信の操作 */
function topBarHTML(){
  return `  <div class="rv-warn notice" id="rvWarn" hidden><span id="rvWarnText"></span><button type="button" class="btn small" id="rvWarnClose">閉じる</button></div>
  <div class="rv-autobar" id="rvAutoBar" role="status" hidden></div>
  <div class="rv-top" id="rvTop">
    <details class="ui-menu rv-pick" id="rvPick">
      <summary class="rv-pickbtn" id="rvPickBtn" title="配信を選ぶ・開く(全部の配信から探せます)">
        <span class="rv-lbl">配信</span>
        <span class="rv-pickcur"><span class="rv-curlabel" id="rvCurLabel"></span><span class="rv-chips" id="rvChips"></span></span>
        <svg class="rv-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
      </summary>
      <div class="rv-pickpop" role="dialog" aria-label="配信を選ぶ">
        <div class="ui-listbar rv-pickbar">
          <input type="search" id="rvPickQ" placeholder="題名・配信者で探す" aria-label="配信を探す" autocomplete="off">
          <select id="rvPickF" aria-label="絞り込み">${PICK_FILTERS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>
          <select id="rvPickSort" aria-label="並び順"><option value="recent">新しい順</option><option value="channel">配信者ごと</option></select>
          <span class="ui-count" id="rvPickN"></span>
          <button type="button" class="btn small ghost" id="rvPickHidden" hidden></button>
        </div>
        <div class="rv-picklist" id="rvPickList"></div>
        <form class="rv-open" id="rvOpenForm" autocomplete="off">
          <label class="rv-fl" for="rvOpenIn">一覧に無い配信・動画ファイルを開く(解析せずに手でマークを付けるとき)<span class="rv-openlive" hidden>。配信中・配信前の URL なら録画を始めて開きます</span></label>
          <div class="rv-openrow"><input id="rvOpenIn" type="text" spellcheck="false" placeholder="YouTube の URL・動画 ID、または動画ファイルのフルパス">
          <button class="btn" type="submit" id="rvOpenBtn">開く</button></div>
          <p class="hint rv-openmsg" id="rvOpenMsg" role="status" hidden></p>
        </form>
      </div>
    </details>
    <button type="button" class="rv-save" id="rvSave" data-k="idle" role="status" title="マークは自動で保存します。失敗したときはここを押すと保存し直します">準備中</button>
    <span class="rv-topsp"></span>
    <details class="ui-menu rv-auto" id="rvAuto" hidden>
      <summary class="btn small ghost" title="案件の画面と同じ「まとめて実行」を、この配信で始めます"><span>まとめて実行</span></summary>
      <div class="rv-vmenupop rv-autopop">
        <p class="hint">この配信を、ホームの案件の画面と同じ順番待ちで自動で進めます。進み具合は上の帯と、ホームの案件の画面に出ます。</p>
        <button type="button" class="btn small primary" data-auto="adopted" title="採用したマークを書き出し → 文字起こし → パック">採用後を全部(書き出し → 文字起こし → パック)</button>
        <button type="button" class="btn small" data-auto="transcribe" title="採用したマークを書き出し → 文字起こし">文字起こしまで(書き出し → 文字起こし)</button>
        <div class="rv-autofull"><button type="button" class="btn small" data-auto="full" title="解析 → 上位を自動で採用 → 書き出し → 文字起こし → パック">解析から全部</button>
          <label class="lag">採用する数 <input id="rvAutoTop" type="number" min="1" max="30" step="1" value="3"></label></div>
        <label class="lag rv-autowho" title="名前を入れると、パックの字幕の文字をその人のメンバーカラーにします(空なら黒い文字)">配信者(字幕の色)
          <input id="rvAutoWho" type="text" size="12" placeholder="例: さくらみこ"></label>
        <div class="rv-autopanel"></div>
        <label class="lag rv-autoloud" title="パックに入れる動画の音量を、カットで残す部分だけ測ってそろえます(パックのタブと同じ設定。どこで変えても同じ値)" hidden>パックの音量 <select id="rvAutoLoud" data-ui-packloud></select></label>
      </div>
    </details>
    <button class="btn small ghost rv-theaterbtn" id="rvTheater" type="button" aria-pressed="false" title="シアター表示(プレーヤーを大きく)">${SVG.theater}<span>シアター</span></button>
    <details class="ui-menu rv-vmenu" id="rvVMenu">
      <summary class="btn small ghost" title="この配信の名前・解析・削除"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg><span>配信の操作</span></summary>
      <div class="rv-vmenupop">
        <label class="rv-fl" for="rvTitle">名前(自分用のラベル。一覧と書き出しのフォルダ名に使います)</label>
        <input id="rvTitle" type="text" maxlength="120" placeholder="例: 2026-09-12 マリオカート配信">
        <div class="rv-vmenuacts">
          <a class="btn small ghost" id="rvYtLink" target="_blank" rel="noopener noreferrer" hidden title="YouTube で、いまの位置から開きます">YouTube で開く</a>
          <button class="btn small" id="rvAnalyze" type="button" hidden title="この配信を ② 解析のキューに入れて、自動マークを作ります">この配信を解析する</button>
          <button class="btn small danger" id="rvDelVideo" type="button" title="スタジオの一覧から消します(書き出した切り抜きのファイルは残ります)">スタジオから削除</button>
        </div>
      </div>
    </details>
  </div>`;
}
/* 画面の中の移動(プレーヤー・マーク・書き出し)と、配信を開いていないときの案内 */
function jumpHTML(){
  return `  <nav class="rv-jump" id="rvJump" aria-label="この画面の中の移動">
    <button type="button" class="rv-jumpb rv-jump-n" data-jump="player">プレーヤー</button>
    <button type="button" class="rv-jumpb rv-jump-n" data-jump="marks">マーク <b class="num" id="rvJumpMarks">0</b></button>
    <button type="button" class="rv-jumpb rv-jump-exp" data-jump="export" title="書き出しの欄を開く">書き出し <b id="rvJumpExp"></b><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
  </nav>
  <div class="rv-emptybox empty" id="rvEmpty" hidden>
    <b>まだ配信が開かれていません</b>
    <span>② 解析で配信を入れると、終わったものから、ここで自動のマークを確かめられます。解析せずに手でマークを付けるときは、上の「配信」から URL か動画ファイルを開きます。</span>
    <div class="cs-emptyacts"><button type="button" class="btn" id="rvEmptyOpen">配信を選ぶ・開く</button><button type="button" class="btn ghost" id="rvEmptyRank" data-go-step="rank">① 探すで選ぶ</button><button type="button" class="btn ghost" id="rvEmptyQueue" data-go-step="queue">② 解析へ</button></div>
  </div>`;
}
/* プレーヤー・タイムライン・盛り上がりグラフ・再生の操作。
   タイムライン(#rvTl)のクリックで移動はマウスだけの便利(A-25 の例外): キーでは ← →(1秒・Shift で5秒)・, .(1コマ)・現在位置の欄に時刻を入れて Enter で動かせる。
   区間のボタン(#rvSegs の .rv-seg)の幅は時間で決まるので 28px より細いことがある(A-21 の例外): 同じマークは一覧の行(と前後移動キー)から選べる */
function playerHTML(){
  return `      <div class="rv-player" id="rvPlayerBox"><div class="rv-host" id="rvHost"></div><div class="rv-phmsg" id="rvPhMsg" hidden></div></div>
      <div class="rv-notice notice" id="rvNotice" hidden></div>

      <div class="rv-deck">
        <div class="rv-tl" id="rvTl" role="group" aria-label="タイムライン。クリックでその位置へ移動" data-ui-audit-allow="A-25">
          <div id="rvSegs" data-ui-audit-allow="A-21"></div><div class="rv-draft" id="rvDraft" hidden></div><div class="rv-ph" id="rvPh"></div>
        </div>
        <div class="rv-graph" id="rvGraph" hidden><div class="rv-gsvg" id="rvGSvg"></div><div class="rv-gticks" id="rvGTicks" aria-hidden="true"></div><div class="rv-gcur" id="rvGCur"></div><div class="rv-ghover" id="rvGHover" hidden aria-hidden="true"><span></span></div><div class="rv-gpeaks" id="rvGPeaks"></div></div>
        <div class="rv-scale" aria-hidden="true"><span>0:00.0</span><div class="rv-glegend" id="rvGLegend" hidden></div><span id="rvTlEnd">--</span></div>

        <div class="rv-transport">
          <div class="rv-nowbox">
            <label class="sr-only" for="rvNow">現在位置(直接入力でジャンプ)</label>
            <input id="rvNow" type="text" value="0:00.0" inputmode="decimal" autocomplete="off" title="現在位置。時刻を入れて Enter でジャンプ(例: 1:23.5 / 5025)"><span class="rv-dur mono" id="rvDur">/ --</span>
          </div>
          <div class="rv-tbtns">
            <div class="btn-group" role="group" aria-label="戻る">
              <button class="btn small" type="button" data-seek="-10">−10s</button>
              <button class="btn small" type="button" data-seek="-5">−5s</button>
            </div>
            <button class="btn small primary rv-playbtn" type="button" id="rvToggle">${SVG.play}再生 / 停止</button>
            <div class="btn-group" role="group" aria-label="進む">
              <button class="btn small" type="button" data-seek="5">+5s</button>
              <button class="btn small" type="button" data-seek="10">+10s</button>
            </div>
            <select id="rvRate" aria-label="再生速度" title="再生速度">
              <option value="0.5">0.5x</option><option value="0.75">0.75x</option><option value="1" selected>1x</option>
              <option value="1.25">1.25x</option><option value="1.5">1.5x</option><option value="2">2x</option>
            </select>
          </div>
        </div>
      </div>`;
}
/* LIVE の帯(ライブの録画: 録画の状態・すぐ書き出す・書き出したあと・配信者・アーカイブで作り直す・配信後の自動の切り抜きの進み具合) */
function liveBarHTML(){
  return `      <!-- LIVE の帯: 置き場所は placeQuickBar が決める(広い画面は右の列のマークの一覧の上・狭い画面とシアターは「今をマーク」の上) -->
      <div class="rv-livebar" id="rvLiveBar" hidden>
        <div class="rv-live-l"><span class="rv-live-badge" id="rvLiveBadge">LIVE</span>
          <span class="rv-live-k" id="rvLiveElapsedK">配信経過</span><span class="mono" id="rvLiveElapsed">--</span>
          <span class="rv-live-k rv-live-edgeinfo">ライブ端との差</span><span class="mono rv-live-edgeinfo" id="rvLiveGap">--</span>
          <span class="rv-live-k">ライブ印のマーク</span><span class="mono" id="rvLiveMarks">0件</span></div>
        <div><button class="btn small" id="rvEdge" type="button">ライブ端へ</button></div>
        <div class="rv-liverec" id="rvLiveRec" hidden>
          <span class="pill" id="rvRecState" role="status">確かめています…</span><span class="hint rv-recmsg" id="rvRecMsg"></span>
          <span class="rv-topsp"></span>
          <label class="rv-check" for="rvAutoExp" title="今をマーク ①〜⑤・一瞬・IN/OUT の追加で付けたマークを採用にして、すぐ書き出しに回します(録画が届くのを待ってから作ります)"><input type="checkbox" class="ui-switch" id="rvAutoExp">マークしたらすぐ書き出す</label>
          <label class="rv-duck rv-after" for="rvAfter" title="書き出した切り抜きを、ホームの「まとめて実行」でどこまで進めるか(手動の「書き出す」にも効きます)。文字起こしまで = 字幕は「編集」で直す / 全自動 = 文字起こしのあとパックまで作る(字幕は校正前)">書き出したあと <select id="rvAfter"><option value="none">何もしない</option><option value="check">文字起こしまで</option><option value="auto">全自動(パックまで)</option></select></label>
          <details class="ui-pop rv-livewho" id="rvLiveWho" hidden><summary class="btn small ghost" title="字幕の色を決める配信者です(覚えた名前か、チャンネル名から自動)。押すと直せます(直した名前は、この録画とこのチャンネルで次からも使います)"><span id="rvLiveWhoText">配信者: 未設定(字幕は既定の色)</span></summary>
            <div class="ui-pop-body rv-livewhobody" data-align="left"><label class="rv-fl" for="rvLiveWhoIn">配信者(字幕の色)</label><input type="text" id="rvLiveWhoIn" placeholder="例: 兎田ぺこら" aria-describedby="rvLiveWhoNote">
              <p class="hint" id="rvLiveWhoNote">次の書き出しから、この名前のメンバーカラーで字幕を作ります(空 = 既定の色)</p></div></details>
          <label class="rv-duck" for="rvDuck" title="「編集」を別の窓で開いて再生している間、配信の音をどうするか(止めると元に戻ります)">編集で再生中は <select id="rvDuck"><option value="low">音を下げる</option><option value="mute">音を消す</option><option value="off">そのまま</option></select></label>
          <button class="btn small danger" id="rvRecStop" type="button" hidden title="録画を止めます(録れた所までは、このあとも再生・マーク・書き出しができます)">録画を止める</button>
        </div>
        <p class="rv-liveguide rv-ducknote" id="rvDuckNote" role="status" hidden></p>
        <p class="rv-liveguide" id="rvLiveGuide" hidden></p>
        <div class="rv-liverec rv-arch" id="rvArch" hidden>
          <button class="btn small" id="rvArchRun" type="button">アーカイブで作り直す</button>
          <button class="btn small ghost" id="rvArchCancel" type="button" hidden title="本番版への作り直しを止めます(済んでいない分は速報版のままです)">取り消す</button>
          <span class="hint rv-archmsg" id="rvArchMsg" role="status"></span>
        </div>
        <p class="rv-liveguide" id="rvAfterStream" role="status" hidden></p>
      </div>`;
}
/* 今をマーク・一瞬をマーク・細かく決める(IN・OUT・追加) */
function markToolsHTML(){
  return `      <div class="rv-quickbar" id="rvQuickbar"><div class="rv-fl">今をマーク <span class="muted">押した位置の前後を、そのままマークにします。− ＋ で前後の長さを切り替え</span></div><div class="rv-qrow" id="rvQuickSlots"></div>
        <div class="rv-qrow rv-momrow"><button class="btn soft" type="button" id="rvMomBtn" title="今の位置の前後(下の秒数)を、マーク「一瞬」(採用)にします">一瞬をマーク<kbd class="ui-kbd" data-kbd="moment">C</kbd></button>
          <label class="rv-momset">前 <input type="number" id="rvMomBefore" min="0" max="60" step="0.1" inputmode="decimal" aria-label="一瞬の前の秒数"> 秒</label>
          <label class="rv-momset">後 <input type="number" id="rvMomAfter" min="0" max="60" step="0.1" inputmode="decimal" aria-label="一瞬の後の秒数"> 秒</label>
          <span class="hint">0.1 秒単位。押すとすぐマークになります(ライブ中も)</span></div></div>

      <details class="rv-markdetails ui-disclosure" id="rvMarkDetails">
        <summary>細かく決める <span class="muted">IN・OUT・追加(今をマークの代わりに、時刻を決めて追加)</span></summary>
        <div class="rv-mark">
          <div class="rv-markcell">
            <button class="rv-markbtn in" id="rvIn" type="button">IN(開始)<kbd class="ui-kbd" data-kbd="markIn" title="全ツール共通の再生キー(? の一覧で変えられます)">I</kbd></button>
            <div class="rv-val is-empty" id="rvInVal">--</div>
          </div>
          <div class="rv-markcell">
            <button class="rv-markbtn out" id="rvOut" type="button">OUT(終了)<kbd class="ui-kbd" data-kbd="markOut" title="全ツール共通の再生キー(? の一覧で変えられます)">O</kbd></button>
            <div class="rv-val is-empty" id="rvOutVal">--</div>
          </div>
          <div class="rv-markcell rv-addcell">
            <button class="btn primary" id="rvAdd" type="button">マーク追加<kbd class="ui-kbd" data-kbd="addClip">A</kbd></button>
            <span class="hint" id="rvDraftDur">IN と OUT を押すと追加できます</span>
          </div>
        </div>
      </details>`;
}
/* 操作の設定(音量・確認の進め方・マークの付け方・キー配置・ライブ配信) */
function settingsHTML(){
  return `      <details class="rv-settings ui-disclosure" id="rvSettings">
        <summary>操作の設定 <span class="muted">音量・確認の進め方・マークの付け方・キー配置・ライブ配信</span></summary>
        <div class="rv-setpanel">
          <section class="rv-sec">
            <h3>音量</h3>
            <div class="rv-setrow"><input type="range" id="rvVol" min="0" max="100" step="1" value="100" aria-label="音量"><output id="rvVolOut" class="mono" for="rvVol">100</output><label class="rv-check" for="rvMute"><input type="checkbox" id="rvMute">ミュート</label></div>
          </section>
          <section class="rv-sec">
            <h3>確認の進め方</h3>
            <div class="rv-setrow"><label class="rv-check" for="rvAutoPlay"><input type="checkbox" class="ui-switch" id="rvAutoPlay">前後のマークへ移動したら、その区間を自動で再生する</label></div>
            <div class="rv-setrow"><label class="rv-check" for="rvAutoNext"><input type="checkbox" class="ui-switch" id="rvAutoNext">「採用」「不採用」を押したら、次の候補へ進む</label></div>
          </section>
          <section class="rv-sec">
            <h3>マークの付け方</h3>
            <div class="rv-setrow"><label class="rv-check" for="rvLag">反応の遅れ補正</label><select id="rvLag"><option value="0">なし</option><option value="2">−2秒</option><option value="3">−3秒</option><option value="5">−5秒</option></select></div>
            <p class="rv-sechint">面白い場面を見てから IN・「今をマーク」を押すまでの遅れの分だけ、開始を前にずらします。</p>
          </section>
          <section class="rv-sec">
            <h3>キー配置</h3>
            <p class="rv-sechint">キーの割り当ては、ヘッダーの「キー操作」(? キー)の一覧の1か所で変えます。「標準」「左手だけ」の組み合わせも一覧の上で選べます。</p>
            <div class="rv-setrow"><button type="button" class="btn small" id="rvKeysOpen">キー配置を変える(?)</button></div>
          </section>
          <section class="rv-sec">
            <h3>ライブ配信向け</h3>
            <div class="rv-subh">打ったマークの時刻をまとめてずらす</div>
            <p class="rv-sechint">配信後にアーカイブで見て、記録がずれていたときに使います。「ライブ」印のマークだけが対象です。</p>
            <div class="rv-setrow"><label class="rv-check" for="rvShiftSec">ずらす秒数<input id="rvShiftSec" type="number" step="1" min="-3600" max="3600" value="0"></label><button class="btn small" id="rvShift" type="button">適用</button><span class="hint" id="rvShiftCount"></span></div>
            <details class="rv-adv ui-disclosure"><summary>詳細設定(通常は変更不要)</summary>
              <div class="rv-subh" style="margin-top:8px"><label for="rvLiveMode">ライブ判定</label></div>
              <select id="rvLiveMode"><option value="auto">自動(おすすめ)</option><option value="on">常にライブとして扱う</option><option value="off">常に通常の配信(アーカイブ)として扱う</option></select>
              <p class="rv-sechint" style="margin-top:6px">いま見ている配信が「配信中のライブ」かどうかの判定です。ライブなのにライブ用バーが出ないときだけ「常にライブ」を選んでください。</p>
            </details>
          </section>
        </div>
      </details>`;
}
/* 書き出しの引き出し(書き出す・つなげて1本に・設定・一覧) */
function exportDrawerHTML(){
  return `      <aside class="ui-drawer rv-exportdrawer" id="rvExport" hidden aria-labelledby="rvExpTitle">
        <div class="ui-drawer-head">
          <h2 class="ui-drawer-title" id="rvExpTitle">書き出し</h2>
          <span class="rv-exp-sum hint" id="rvExpSum"></span>
          <button type="button" class="btn ghost icon small" id="rvExpClose" aria-label="閉じる" title="閉じる"><span class="ui-icon" data-icon="close"></span></button>
        </div>
        <div class="ui-drawer-body">
          <div class="rv-status" id="rvToolStatus"></div>
          <div class="rv-tools">
            <button class="btn primary" id="rvExpRun" type="button">書き出す</button>
            <button class="btn" id="rvJoinRun" type="button" hidden>つなげて1本に</button>
            <button class="btn danger" id="rvExpCancel" type="button" hidden>中止</button>
            <details class="ui-pop rv-expmore" id="rvExpMore">
              <summary class="btn ghost icon" aria-label="その他の書き出し"><span class="ui-icon" data-icon="more"></span></summary>
              <div class="ui-pop-body" data-align="left">
                <button type="button" id="rvExpAll" title="採用にしたマークがある全部の配信を、順番に書き出します">全部の配信の採用を書き出す</button>
                <button type="button" id="rvExpRetry" hidden>失敗した分だけやり直す</button>
              </div>
            </details>
          </div>
          <p class="hint rv-expcount" id="rvExpCount"></p>
          <div class="bar rv-expbar" id="rvExpBar" hidden><i></i></div>
          <details class="ui-disclosure rv-expset" id="rvExpSet"><summary>書き出しの設定 <span class="muted rv-expsetsum" id="rvExpSetSum"></span></summary>
            <div class="rv-expgrid">
              <div class="rv-fld"><label class="rv-fl" for="rvExpTarget">書き出す対象</label>
                <select id="rvExpTarget"><option value="adopted">採用のみ(おすすめ)</option><option value="pending">採用 + 候補</option><option value="all">不採用以外すべて(書き出し済みも)</option></select></div>
              <div class="rv-fld"><label class="rv-fl" for="rvPrecision">切り出し方式</label>
                <select id="rvPrecision" title="どちらも 30fps に作り直し、位置はちょうどです。高速は速い設定で作り直すので、ファイルが少し大きくなります。"><option value="accurate">精密(おすすめ)</option><option value="fast">高速(ファイルが少し大きい)</option></select>
                </div>
              <div class="rv-fld" id="rvHeightBox"><label class="rv-fl" for="rvHeight">最大画質(YouTube)</label>
                <select id="rvHeight"><option value="720">720p</option><option value="1080">1080p</option><option value="1440">1440p</option><option value="2160">2160p</option><option value="0">制限なし</option></select></div>
              <div class="rv-fld"><label class="rv-fl" for="rvExpLoud">音量のそろえ方(<abbr class="ui-term" title="聞こえ方の音量(ラウドネス)の単位。YouTube は再生時に約 -14 LUFS に下げます">LUFS</abbr>)</label>
                <select id="rvExpLoud" title="切り抜きごとにバラバラな聞こえ方の音量(ラウドネス。単位 LUFS)を、書き出すときにそろえます。YouTube は再生時に約 -14 LUFS に下げます"><option value="-14">-14(YouTube の目安・おすすめ)</option><option value="-11">-11(大きめ)</option><option value="-16">-16(控えめ)</option><option value="-18">-18(小さめ)</option><option value="0">そろえない(音量 % で指定)</option></select></div>
              <div class="rv-fld" id="rvExpVolBox" role="group" aria-labelledby="rvExpVolL"><label class="rv-fl" id="rvExpVolL" for="rvExpVol">書き出しの音量(そろえないとき)</label>
                <div class="rv-setrow"><input type="range" id="rvExpVol" min="1" max="200" step="1" value="75" aria-label="書き出しの音量" title="出力ファイルの音量です(100で元の音量のまま)。元の音量だと大きすぎるとのことで、既定は75%にしています"><output id="rvExpVolOut" class="mono" for="rvExpVol">75</output><span class="muted">%</span></div>
              </div>
            </div>
            <p class="hint rv-outline">保存先: <span class="mono" id="rvOutDir"></span> <button type="button" class="btn small ghost" id="rvOutEdit">変更</button></p>
          </details>
          <ol class="rv-explist" id="rvExpList"></ol>
        </div>
      </aside>`;
}
/* マークの一覧(絞り込み・並び順・折りたたみ・候補をすべて採用) */
function clipboxHTML(){
  return `      <div class="rv-clipbox" id="rvClipbox">
        <div class="rv-clips-head"><h2>マーク</h2><div class="hint" id="rvStats"></div></div>
        <div class="rv-listtools">
          <div class="rv-filters ui-seg" id="rvFilters" role="group" aria-label="表示する判定">${FILTERS.map(([f, l]) => `<button type="button" data-filter="${f}" aria-pressed="${f === 'all'}">${l} <span class="n">0</span></button>`).join('')}</div>
          <div class="rv-listtools2">
            <select id="rvSort" aria-label="並び順"><option value="time">時刻順</option><option value="score">点数順</option></select>
            <button class="btn small ghost" id="rvFoldAll" type="button" title="すべてのマークを折りたたむ">すべて折りたたむ</button><button class="btn small ghost" id="rvUnfoldAll" type="button">すべて開く</button>
            <button class="btn small ghost" id="rvBulkAdopt" type="button" title="候補のマークをすべて採用にします">候補をすべて採用</button>
          </div>
        </div>
        <ol class="rv-list" id="rvList"></ol>
      </div>`;
}
function buildDOM(){
  $('#paneReview').innerHTML = `
<div class="rv-root" id="rvRoot">
${topBarHTML()}
${jumpHTML()}
  <div class="rv-grid" id="rvMain" hidden>
    <section class="rv-stage" id="rvStage" aria-label="プレーヤーとマークの付け方">
${playerHTML()}

${liveBarHTML()}

${markToolsHTML()}

${settingsHTML()}
    </section>

    <section class="rv-clips" aria-label="書き出しとマーク">
${exportDrawerHTML()}

${clipboxHTML()}
    </section>
  </div>
</div>`;
}

/* ---------- 保存(サーバー: PUT /api/video)---------- */
let saveTimer = null, saveP = null;
function setSaveState(k){
  const el = $('#rvSave'); if (!el) return; el.dataset.k = k;
  el.textContent = { pending: '変更あり', saving: '保存中…', saved: '保存済み', error: '保存に失敗しました(再保存)', idle: '自動保存' }[k] || '';
}
function markDirty(){
  S.editSeq++; S.dirty = true; setSaveState('pending');
  clearTimeout(saveTimer); saveTimer = setTimeout(save, 600);
}
const snap = ms => new Map(ms.map(m => [m.id, { start: m.start, end: m.end, label: m.label, live: !!m.live, status: m.status || '' }]));
/* Studio.api を通す(失敗時の e.status / e.code / e.body は Studio.api が付ける。API の置き場所を1か所で決めるため: docs/spec/pipeline.md 5.) */
function putVideo(body){ return Studio.api('/api/video', { method: 'PUT', body }); }
const MERGE_MSG = '解析や書き出しで内容が更新されたため、最新の内容に合わせて読み込み直しました';
function save(){
  clearTimeout(saveTimer); saveTimer = null;
  if (saveP) return saveP;
  const run = async () => {
    let conflicts = 0;
    while (S.dirty && S.cur){
      const v = S.cur, seq = S.editSeq; S.dirty = false; setSaveState('saving');
      const sent = snap(v.marks), sentTitle = v.title;
      try {
        const r = await putVideo({ id: v.id, title: v.title, marks: marksPayload(v.marks), baseRev: v.rev });
        v.rev = r.video.rev; S.base = sent; S.baseTitle = sentTitle; conflicts = 0;
        mergeServerFields(v, r.video);
        if (!S.dirty) setSaveState('saved');
        if (seq === S.editSeq && !S.dirty) refreshListQuiet();
      } catch (e){
        if (e.status === 409 && e.code === 'conflict' && e.body && e.body.video && S.cur === v){
          S.dirty = true;
          if (++conflicts > 3){ setSaveState('error'); toast('保存できません: 更新が重なって取り込めませんでした。もう一度お試しください', 0, 'err'); return; }
          applyServer(v, e.body.video, e.body.series); toast(MERGE_MSG);
          continue;
        }
        S.dirty = true; setSaveState('error');
        toast(e.code === 'bad_marks' ? e.message : '保存できません: ' + e.message, 0, 'err'); return;
      }
    }
  };
  saveP = run().finally(() => { saveP = null; });
  return saveP;
}
/* サーバー側の最新(sv)を土台にして、手元の未保存の編集(start/end/label/live・削除・新しい手動マーク・動画名)を重ねる。重ねたものがあれば true */
function applyServer(v, sv, series){
  const localBy = new Map(v.marks.map(m => [m.id, m])), base = S.base || new Map();
  const edited = m => { const b = base.get(m.id); return !!b && (b.start !== m.start || b.end !== m.end || b.label !== m.label || b.live !== !!m.live); };
  let had = false; const out = [], sids = new Set();
  for (const s of sv.marks){
    sids.add(s.id); const l = localBy.get(s.id);
    if (!l){ if (base.has(s.id)){ had = true; continue; } out.push(s); continue; } // 手元で削除した
    const stEdited = (base.get(l.id) || {}).status !== undefined && base.get(l.id).status !== (l.status || '');   // 手元で 候補/採用/不採用 を変えた
    if (edited(l) || stEdited){
      const mm = { ...s, start: l.start, end: l.end, label: l.label, live: !!l.live };
      if (stEdited){ mm.status = l.status || ''; mm.file = ''; mm.path = ''; mm.archived = false; }
      else if (s.status === 'exported' && (s.start !== l.start || s.end !== l.end)){ mm.status = 'adopted'; mm.file = ''; mm.path = ''; mm.archived = false; }
      out.push(mm); had = true;
    } else out.push(s);
  }
  for (const l of v.marks) if (!sids.has(l.id) && l.src !== 'auto'){ out.push(l); had = true; }
  const titleEdited = v.title !== S.baseTitle;
  if (titleEdited) had = true; else v.title = sv.title;
  v.rev = sv.rev; v.analysis = sv.analysis; v.duration = sv.duration || v.duration; v.channel = sv.channel; v.marks = out;
  S.base = snap(sv.marks); S.baseTitle = sv.title;
  if (series) S.series = series;
  const ids = new Set(out.map(m => m.id));
  for (const m of out) S.seen.add(m.id);
  if (S.sel && !ids.has(S.sel)) S.sel = null;
  renderTimeline(); renderStats(); renderMeta(); renderLiveCount(); renderListKeep();
  return had;
}
function renderListKeep(){
  const a = document.activeElement;
  if (!inList()){ renderList(); return; }
  const li = a.closest('.rv-mark-row'), id = li && li.dataset.id, f = a.dataset && a.dataset.f, val = a.value, ss = a.selectionStart, se = a.selectionEnd;
  renderList();
  const el = id && document.querySelector(`.rv-mark-row[data-id="${CSS.escape(id)}"] [data-f="${f}"]`);
  if (el){ el.focus(); try { if (f === 'label'){ el.value = val; el.setSelectionRange(ss, se); } } catch {} }
}
async function flushSave(){
  if (saveTimer){ clearTimeout(saveTimer); saveTimer = null; }
  if (S.dirty || saveP) await save();
  if (S.dirty) throw new Error('変更を保存できませんでした。「再保存」で保存してから操作してください');
}
/* サーバーだけが決める項目(書き出し状態・点数など)を手元のマークへ反映する。手元の編集(start/end/label)は上書きしない */
function mergeServerFields(v, sv){
  if (!v || !sv || S.cur !== v) return false;
  let changed = false;
  const by = new Map(sv.marks.map(m => [m.id, m]));
  for (const m of v.marks){
    const s = by.get(m.id); if (!s) continue;
    const b = (S.base || new Map()).get(m.id), localSt = !!b && b.status !== (m.status || '');   // 送ったあとに手元で 候補/採用/不採用 を変えたなら手元を残す
    if ((!localSt && m.status !== s.status) || m.file !== s.file || (m.path || '') !== (s.path || '') || !!m.archived !== !!s.archived) changed = true;
    m.src = s.src; m.score = s.score; m.reasons = s.reasons; m.parts = s.parts; m.file = s.file; m.path = s.path || ''; m.archived = !!s.archived;   // archived = 本番版に入れ替えた(ライブの録画。サーバーが持つ印)
    if (!localSt) m.status = s.status;
  }
  if (changed){
    renderTimeline(); renderStats(); if (!inList()) renderList();
  }
  return changed;
}
const inList = () => !!(document.activeElement && document.activeElement.closest && document.activeElement.closest('#rvList'));

/* ---------- 動画一覧・切り替え ---------- */
async function refreshList(){
  try { S.videos = (await Studio.api('/api/videos')).videos || []; } catch (e){ return; }
  renderVideoSelect(); updateBadge(); renderExportUI();
}
let quietT = null;
function refreshListQuiet(){ clearTimeout(quietT); quietT = setTimeout(() => { quietT = null; refreshList(); }, 300); }
/* ③ のタブの件数: 判定か書き出しが残っている配信の数(候補か、書き出していない採用がある) */
function updateBadge(){
  const n = S.videos.filter(v => (Number(v.candidates) || 0) + (Number(v.adopted) || 0) > 0).length;
  Studio.setBadge('review', n ? String(n) : '', n ? `判定か書き出しが残っている配信 ${n}本` : '');
}
function vLabel(v){ return v.title || v.fileName || v.id; }
const nz = x => Number(x) || 0;
const vWho = v => (v.kind === 'file' ? '動画ファイル' : (v.channel || (v.kind === 'live' ? 'ライブの録画' : '配信者不明')));
/* ---------- 配信の選択(ヘッダーの下の「配信」。50本以上でも探せるように、検索・絞り込み・配信者ごと) ----------
   関数名は以前の <select> のまま(renderVideoSelect)。選ぶ部分(ボタン)はいつも、一覧は開いているときだけ描く */
const PK = { q: '', f: 'all', sort: 'recent', limit: 80 };
function pickMatch(v){
  const f = PK.f;
  if (f === 'cand' && !nz(v.candidates)) return false;
  if (f === 'adopt' && !nz(v.adopted)) return false;
  if (f === 'done' && !nz(v.exported)) return false;
  if (f === 'none' && nz(v.marks)) return false;
  const q = PK.q.trim().toLowerCase(); if (!q) return true;
  const hay = (vLabel(v) + ' ' + vWho(v) + ' ' + v.id).toLowerCase();
  return q.split(/\s+/).every(w => hay.includes(w));
}
/* 非表示にした配信(UIKit.hide の一覧 'videos'。入口から開いたときだけ)。今開いている配信は隠していても一覧に残す */
const HIDE = window.UIKit && UIKit.hide;
const pickHidden = v => !!(HIDE && HIDE.available() && HIDE.has('videos', v.id) && !(S.cur && S.cur.id === v.id));
function pickRowHTML(v){
  const cur = S.cur && S.cur.id === v.id, t = v.createdAt || v.updatedAt;
  const hid = HIDE && HIDE.available() && HIDE.has('videos', v.id);
  const pills = [v.kind === 'live' ? (liveRecActive(v) ? '<span class="pill run">録画中</span>' : '<span class="pill">録画</span>') : '', nz(v.candidates) ? `<span class="pill warn">候補 ${nz(v.candidates)}</span>` : '', nz(v.adopted) ? `<span class="pill ok">採用 ${nz(v.adopted)}</span>` : '',
    nz(v.exported) ? `<span class="pill">書き出し済み ${nz(v.exported)}</span>` : '', !v.analysis && v.kind === 'youtube' ? '<span class="pill wait">解析前</span>' : '', v.groupId ? '<span class="pill info">コラボ</span>' : '', hid ? '<span class="ui-hidden-tag">非表示</span>' : ''].join('');
  const row = `<button type="button" class="rv-prow${cur ? ' is-cur' : ''}" data-vid="${esc(v.id)}"${cur ? ' aria-current="true"' : ''} title="${esc(vLabel(v))}">
    <span class="rv-prow-t">${esc(vLabel(v))}</span>
    <span class="rv-prow-m"><span>${esc(vWho(v))}</span>${t ? `<span class="q-dot">・</span><span title="スタジオに追加: ${esc(Studio.date(t))}">${esc(Studio.ago(t))}</span>` : ''}${pills ? `<span class="rv-prow-p">${pills}</span>` : ''}</span></button>`;
  if (!(HIDE && HIDE.available())) return row;
  const tip = hid ? '表示に戻す' : '一覧で非表示にする(配信のデータは消しません)';
  return `<div class="rv-prow-wrap${hid ? ' ui-hidden-item' : ''}">${row}<button type="button" class="btn small ghost rv-prow-hide" data-hide-vid="${esc(v.id)}" data-hide-on="${hid ? '0' : '1'}" title="${tip}" aria-label="${esc(vLabel(v))}: ${tip}">${hid ? '戻す' : '隠す'}</button></div>`;
}
function renderPickList(){
  const box = $('#rvPickList'); if (!box || !$('#rvPick').open) return;
  const vs = S.videos.map(v0 => (S.cur && S.cur.id === v0.id ? { ...v0, title: S.cur.title } : v0));
  const base = vs.filter(pickMatch), showHid = !HIDE || HIDE.showing('videos');
  const hit = showHid ? base : base.filter(v => !pickHidden(v));
  if (HIDE) HIDE.toggle($('#rvPickHidden'), 'videos', base.filter(pickHidden).length);
  $('#rvPickN').textContent = `${hit.length} / ${vs.length} 本`;
  if (!vs.length){ box.innerHTML = '<div class="empty"><b>まだ配信がありません</b>② 解析で配信を入れるか、下の欄で URL・動画ファイルを開くと、ここに出ます。</div>'; return; }
  if (!hit.length){ box.innerHTML = '<div class="empty"><b>条件に合う配信はありません</b>探す文字を消すか、絞り込みを「すべて」にしてください。</div>'; return; }
  const list = hit.slice(0, PK.limit);
  let html;
  if (PK.sort === 'channel'){
    const m = new Map();
    for (const v of list){ const k = vWho(v); if (!m.has(k)) m.set(k, []); m.get(k).push(v); }
    const curK = S.cur ? vWho(S.cur) : '', searching = !!PK.q.trim() || PK.f !== 'all';
    html = [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], 'ja')).map(([k, items]) =>
      `<details class="ui-group rv-pg"${searching || k === curK ? ' open' : ''}><summary>${esc(k)} <span class="ui-group-n">${items.length}本</span></summary><div class="rv-pg-body">${items.map(pickRowHTML).join('')}</div></details>`).join('');
  } else html = list.map(pickRowHTML).join('');
  if (hit.length > list.length) html += `<div class="rv-pickmore"><button type="button" class="btn small" data-pick-more>もっと見る(残り ${hit.length - list.length} 本)</button></div>`;
  box.innerHTML = html;
}
function renderVideoSelect(){
  renderPickList();
}
function openPicker(focusOpen){
  const d = $('#rvPick'); if (!d) return;
  d.open = true;
  setTimeout(() => { const f = focusOpen ? $('#rvOpenIn') : $('#rvPickQ'); if (f) f.focus(); }, 0);
}
/* ---------- 前回の場所(S-8): 配信ごとに、再生位置と選んでいたマークを覚えて、開いたときに戻す ----------
   置き場所はこのブラウザ(localStorage の ytt:studio.place)。ホームの設定(UIKit.prefs)は節が決まっていて(home/prefs.py の PATCHABLE)スタジオの節が無いこと、
   再生位置は再生中に数秒ごとに変わる値で、配信のデータ(マークの保存。rev で重なりを見ている)に書くとマークの保存と競合することから。
   形: { 配信の id: [秒, マークの id, 覚えた時刻(ms)] }。新しい順に PLACE_MAX 本まで(古いものから捨てる)。書くのは変わったときだけ・2 秒に1回まで */
const PLACE_KEY = 'ytt:studio.place', PLACE_MAX = 200;
const PLACE = { pend: null, timer: 0, last: '' };
function placeAll(){
  try { const o = JSON.parse(localStorage.getItem(PLACE_KEY) || '{}'); return o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch { return {}; }
}
/* この配信の前回の場所 → {t, sel} | null。マークが消えていれば選ばない・配信の長さを超える位置は長さまで */
function placeOf(v){
  const p = v && placeAll()[v.id];
  if (!Array.isArray(p)) return null;
  let t = Math.max(0, Number(p[0]) || 0);
  if (v.duration > 0) t = Math.min(t, v.duration);
  const sel = typeof p[1] === 'string' && (v.marks || []).some(m => m.id === p[1]) ? p[1] : null;
  return t > 0 || sel ? { t, sel } : null;
}
function placeFlush(){
  clearTimeout(PLACE.timer); PLACE.timer = 0;
  const p = PLACE.pend; PLACE.pend = null;
  if (!p) return;
  const key = p.id + '|' + p.t + '|' + p.sel;
  if (key === PLACE.last) return;
  const all = placeAll();
  all[p.id] = [p.t, p.sel, Date.now()];
  const ids = Object.keys(all);
  if (ids.length > PLACE_MAX) ids.sort((a, b) => (Number(all[a] && all[a][2]) || 0) - (Number(all[b] && all[b][2]) || 0)).slice(0, ids.length - PLACE_MAX).forEach(id => { delete all[id]; });
  try { localStorage.setItem(PLACE_KEY, JSON.stringify(all)); PLACE.last = key; } catch { /* 保存できない(容量・プライベート): 覚えないだけ */ }
}
/* 今の場所を覚える(再生位置が動いた・マークを選んだ)。別の配信の分が残っていれば先に書く */
function placeNote(){
  const v = S.cur; if (!v) return;
  if (PLACE.pend && PLACE.pend.id !== v.id) placeFlush();
  PLACE.pend = { id: v.id, t: Math.round((Number(S.now) || 0) * 10) / 10, sel: S.sel || '' };
  if (!PLACE.timer) PLACE.timer = setTimeout(placeFlush, 2000);
}
/* 戻した選択の行を、マークの一覧の中で見える位置へ(一覧が自分でスクロールする広い画面だけ。狭い画面でページごと動かさない) */
function placeScroll(){
  const ol = $('#rvList'), li = S.sel && ol && ol.querySelector(`.rv-mark-row[data-id="${CSS.escape(S.sel)}"]`);
  if (!li || getComputedStyle(ol).overflowY !== 'auto' || ol.scrollHeight <= ol.clientHeight) return;
  ol.scrollTop += li.getBoundingClientRect().top - ol.getBoundingClientRect().top - Math.round(ol.clientHeight / 3);
}
async function loadVideo(id){
  const seq = ++S.loadSeq;
  if (S.join) S.join.clear();   // つなぐのは同じ配信の中だけ(テストの状態には join が無いことがある)
  try { await flushSave(); } catch (e){ renderVideoSelect(); toast(e.message); return false; }
  if (seq !== S.loadSeq) return false;
  const editSeq = S.editSeq;
  let j;
  try { j = await Studio.api('/api/video?id=' + enc(id)); }
  catch (e){ if (seq === S.loadSeq){ toast('配信を読み込めません: ' + e.message); refreshList(); } return false; }
  if (seq !== S.loadSeq) return false;
  if (S.dirty || saveP || S.editSeq !== editSeq){
    renderVideoSelect(); toast('読み込み中に編集されたため、切り替えを止めました。保存後にもう一度選んでください'); return false;
  }
  S.cur = j.video; S.series = j.series || null; S.sel = null; S.live = false;
  setTimeout(pollAuto, 0);   // この配信の「まとめて実行」の進み具合
  S.draft = { start: null, end: null }; S.fold = new Map(); S.seen = new Set(); S.tx = null; S.txOpen = new Set(); S.txSeq++;
  S.expDockClosed = false;   // 配信を開き直したら、前の配信で × で閉じていたことは忘れる(1680px 以上ならまた開く)
  for (const m of marks()) S.seen.add(m.id);
  S.dirty = false; setSaveState('idle'); S.base = snap(S.cur.marks); S.baseTitle = S.cur.title;
  S.duration = S.cur.duration > 0 ? S.cur.duration : 0;
  /* 前回の場所(S-8): 選んでいたマークと再生位置へ戻す。位置はプレーヤーの準備ができたら合わせる(S.resumeAt。YouTube は playerVars の start) */
  const back = typeof placeOf === 'function' ? placeOf(S.cur) : null;
  if (back && back.sel){ S.sel = back.sel; S.fold.set(back.sel, false); }
  S.resumeAt = back && back.t > 0 ? back.t : null;
  $('#rvLiveBar').hidden = true;
  if (typeof liveOpened === 'function') liveOpened(S.cur);   // ライブの録画(kind live)なら録画の状態の見回りを始める。プレーヤーを作る前に(録画の状態で作り方が変わる)
  setNow(S.resumeAt || 0);
  mountPlayer();
  renderAll();
  if (S.sel && typeof placeScroll === 'function') placeScroll();
  if (typeof fillAutoWho === 'function') fillAutoWho();   // まとめて実行の配信者の欄を、この配信の覚えた名前 → チャンネル名から(段5)
  if (typeof syncExportDock === 'function') syncExportDock();   // (テストは loadVideo だけを切り出して動かすので、無いときは飛ばす) // 配信を開いたとき(の1回だけ)欄の開閉を合わせる
  refreshList();
  fetchAutoTitle(S.cur);
  loadTranscripts();
  return true;
}
/* 別の場所(② 解析の完了・書き出し)で変わったサーバー側の状態を取り込む。手元の未保存の編集は失わない */
async function syncFromServer(){
  const v0 = S.cur; if (!v0) return;
  try { await flushSave(); } catch { return; }
  if (S.cur !== v0) return;
  let j; try { j = await Studio.api('/api/video?id=' + enc(v0.id)); } catch (e){ return; }
  if (S.cur !== v0) return;
  if (j.video.rev === v0.rev){ if (j.series && !S.series){ S.series = j.series; renderGraph(); } return; }
  if (applyServer(v0, j.video, j.series)) markDirty();
  refreshList();
  loadTranscripts();   // 書き出しが終わったマークのセリフ(文字起こし済みなら)
}
async function openFromInput(){
  const inp = $('#rvOpenIn'), text = inp.value.trim();
  if (!text) return toast('YouTube の URL・動画 ID、または動画ファイルのパスを入力してください');
  const body = looksLikeYouTube(text) ? { kind: 'youtube', url: text } : { kind: 'file', path: text.replace(/^["']|["']$/g, '') };
  const btn = $('#rvOpenBtn'); if (btn.disabled) return;   // begin は数秒かかる: 二度押しを防ぐ
  btn.disabled = true;
  const msg = t => { const m = $('#rvOpenMsg'); if (m){ m.textContent = t || ''; m.hidden = !t; } };
  try {
    /* 配信中・配信前の URL なら録画を始めて、その録画を開く(線 D の P3。ライブの機能が使えるときだけ。違えば今までどおり) */
    if (body.kind === 'youtube' && Studio.live && await Studio.live.available()){
      msg('配信の状態を確かめています…(配信中・配信前なら録画を始めます)');
      const b = await Studio.live.begin(text);
      if (b){
        inp.value = '';
        const pk = $('#rvPick'); if (pk) pk.open = false;
        toast(b.existing ? 'この配信はもう録画しています。その録画を開きました' : '配信の録画を始めました。見ながらマークできます', 5000, 'ok');
        await loadVideo(b.video.id);
        return;
      }
    }
    const r = await Studio.api('/api/videos/open', { method: 'POST', body });
    inp.value = '';
    const pk = $('#rvPick'); if (pk) pk.open = false;
    await loadVideo(r.video.id);
  } catch (e){ toast(e.message); }
  finally { btn.disabled = false; msg(''); }
}
async function deleteCurrentVideo(){
  const v = S.cur; if (!v || S.deleting) return;   // 削除の通信中にもう一度押しても、2回目の削除(404)を送らない
  S.deleting = true;
  try { await deleteVideo(v); } finally { S.deleting = false; }
}
async function deleteVideo(v){
  const wasDirty = S.dirty || !!saveTimer;
  clearTimeout(saveTimer); saveTimer = null; S.dirty = false;
  try { await saveP; } catch {}
  try { await Studio.api('/api/video/delete', { method: 'POST', body: { id: v.id } }); }
  catch (e){ if (wasDirty && S.cur === v) markDirty(); return Studio.toast(e.message || '削除できません', 0, 'err'); }
  if (S.job && S.job.videoId === v.id){ S.job = null; S.lastJob = null; stopExpPoll(); rememberJob(null); $('#rvExpList').innerHTML = ''; }
  Studio.toast('スタジオの一覧から削除しました(書き出した切り抜きのファイルは残っています)', 0, 'ok');
  if (S.cur !== v){ await refreshList(); return; }   // 削除の通信中に別の動画へ切り替えていたら、そちらは閉じない
  S.cur = null; S.series = null; ++S.loadSeq; S.dirty = false;
  unmountPlayer(); renderAll();
  await refreshList();
  if (S.videos.length) loadVideo(S.videos[0].id);
}

/* ---------- プレーヤー(YouTube IFrame API / <video>) ---------- */
let yt = null, ytApiP = null, ytReadyTimer = null, pollTimer = null, playerToken = 0, lastSeekAt = 0, lastApplyAt = 0, pollTick = 0;
const YT_API_SRC = 'https://www.youtube.com/iframe_api';
function loadYTApi(){
  // 読み込みの時間切れのあとで script が遅れて読めても、window.YT ができるので次の呼び出しはここで済む
  if (window.YT && window.YT.Player) return Promise.resolve();
  if (ytApiP) return ytApiP;
  ytApiP = new Promise((resolve, reject) => {
    let timer = null;
    const ok = () => { clearTimeout(timer); resolve(); }, ng = e => { clearTimeout(timer); reject(e); };
    window.onYouTubeIframeAPIReady = ok;
    // 再試行では前の script を消してから足す(二重に読まない)
    document.querySelectorAll('script[data-yt-api]').forEach(x => x.remove());
    const s = document.createElement('script');
    s.src = YT_API_SRC; s.dataset.ytApi = '1';
    s.onerror = () => ng(new Error('load'));
    document.head.appendChild(s);
    timer = setTimeout(() => ng(new Error('timeout')), 12000);
  }).catch(e => { ytApiP = null; throw e; });
  return ytApiP;
}
function clearYtReadyTimer(){ if (ytReadyTimer){ clearTimeout(ytReadyTimer); ytReadyTimer = null; } }
/* プレーヤーが使えないときの案内(1か所に出したままにする)。YouTube の配信なら、YouTube で開くリンクを添える。
   使えない間は、前後のマークへ移動したときの自動再生で通知を出さない(押すたびに同じ通知が出ていた)。自分で再生を押したときだけ通知する */
function showNotice(t, opts){
  S.playerErr = true;
  const n = $('#rvNotice'), v = S.cur;
  const yt0 = v && v.kind === 'youtube' ? `https://www.youtube.com/watch?v=${enc(v.id)}` : liveYtHref(v);
  const retry = opts && opts.retry ? '<button type="button" class="btn small" data-act="ytretry">もう一度試す</button> ' : '';   // 押したときの動きは #rvNotice のクリックで受ける(CSP: インラインの onclick は動かない)
  n.innerHTML = `<b>この画面では再生できません。</b> ${esc(t)}<br><span class="hint">判定・時刻の入力・書き出しは続けられます(マークを移っても自動では再生しません)。</span>${retry || yt0 ? ' ' : ''}${retry}${yt0 ? `<a class="btn small" href="${esc(yt0)}" target="_blank" rel="noopener noreferrer" data-yt-now>YouTube で開く</a>` : ''}`;
  n.hidden = false; phMsg('');
}
const canPlay = () => !!(yt && S.playerAlive && !S.playerErr);
function noPlayerToast(){ toast(S.playerErr ? 'この画面では再生できません(プレーヤーの下の案内を見てください)' : 'プレーヤーを準備しています。少し待ってからもう一度押してください', 5000); }
/* プレーヤーの上の「読み込み中」表示(準備できたら・失敗したら消す) */
function phMsg(t){ const m = $('#rvPhMsg'); if (!m) return; m.hidden = !t; m.innerHTML = t ? `<span class="ui-spin" aria-hidden="true"></span><span>${esc(t)}</span>` : ''; }
function hideNotice(){ $('#rvNotice').hidden = true; }
function ytErrorMessage(code){
  if (code === 'local') return 'この動画ファイルはブラウザで再生できません(mkvや一部コーデックなど)。mp4(H.264/AAC)に変換して開き直すか、時刻の手入力で記録してください。書き出しは元ファイルからそのまま行えます。';
  if (code === 100) return 'この配信は見つからないか、非公開です(エラー100)。';
  if (code === 101 || code === 150) return 'この配信は、配信者が埋め込み再生を許可していません(エラー' + code + ')。時刻の手入力なら記録は続けられます。';
  if (code === 153) return 'プレーヤー設定エラー(153)。file:// で開いていないか確認し、サーバー経由の http://localhost で開いてください。';
  return 'プレーヤーでエラーが発生しました(コード ' + code + ')。';
}
function setDuration(d){
  S.duration = d;
  renderTimeline(); renderGraph();
}

/* <video> を YT.Player と同じ最小の形で操る部分(動画ファイルの LocalPlayer・ライブの録画の LivePlayer で共通) */
class VideoPlayer {
  getPlayerState(){ const e = this.el; return e.ended ? 0 : e.paused ? 2 : (e.readyState < 3 ? 3 : 1); }
  pauseVideo(){ this.el.pause(); }
  setPlaybackRate(r){ this.el.playbackRate = r; }
  setVolume(v){ this.el.volume = Math.min(1, Math.max(0, v / 100)); }
  getVolume(){ return Math.round(this.el.volume * 100); }
  mute(){ this.el.muted = true; }
  unMute(){ this.el.muted = false; }
  isMuted(){ return this.el.muted; }
  destroy(){ try { this.el.pause(); this.el.removeAttribute('src'); this.el.load(); } catch {} this.el.remove(); }
}
/* ローカル動画: YT.Player と同じ最小インターフェースを持つ <video> アダプタ(サーバーの /media から Range 再生) */
class LocalPlayer extends VideoPlayer {
  constructor(host, url, ev){
    super();
    this.ev = ev;
    const el = this.el = document.createElement('video');
    el.playsInline = true; el.preload = 'metadata'; el.controls = true;
    el.src = url;
    el.addEventListener('loadedmetadata', () => ev.onReady && ev.onReady({ target: this }), { once: true });
    el.addEventListener('error', () => ev.onError && ev.onError({ data: 'local' }));
    const st = () => ev.onStateChange && ev.onStateChange({ data: this.getPlayerState() });
    for (const n of ['play', 'pause', 'ended', 'waiting', 'playing', 'durationchange']) el.addEventListener(n, st);
    host.appendChild(el);
  }
  getDuration(){ const d = this.el.duration; return Number.isFinite(d) ? d : 0; }
  getCurrentTime(){ return this.el.currentTime || 0; }
  getVideoData(){ return { isLive: false }; }
  seekTo(t){ this.el.currentTime = Math.max(0, t); }
  playVideo(){ const r = this.el.play(); if (r && r.catch) r.catch(() => {}); }
}

/* ---------- ライブの録画(kind live。線 D の P3)の時刻: 「録画の最初のセグメントの受信時刻(PDT)」からの秒 ----------
   スタジオのマーク・書き出し(入口の live_export の基準 = 録画元の firstPdt)はこの秒で持つ。繋ぎ直しで欠けた間も時間は進む。
   hls.js の再生位置(video.currentTime。欠けを詰めた「メディアの秒」)とは、フラグメントごとの programDateTime で行き来する。
   DOM も hls.js も使わない純粋な関数(test_review.cjs が切り出して試す)。frags は [{ pdt: 受信時刻(ms), start: メディアの秒, dur: 秒 }](時刻の順) */
const LT = {
  /* hls.js の level.details.fragments → frags。programDateTime が無い再生リストでは、メディアの秒をそのまま時刻にする(欠けは分からない) */
  frags(fragments){
    const out = [];
    for (const f of fragments || []){
      const start = Number(f && f.start), dur = Number(f && f.duration);
      if (!Number.isFinite(start) || !(dur > 0)) continue;
      const p = Number(f.programDateTime);
      out.push({ pdt: Number.isFinite(p) && p > 0 ? p : start * 1000, start, dur });
    }
    return out.sort((a, b) => a.start - b.start);
  },
  base: frags => (frags && frags.length ? frags[0].pdt : null),
  /* メディアの秒 → 録画の秒。区間の外(最初より前・最後より後)は近い端のフラグメントから伸ばす */
  timeOf(frags, base, media){
    if (!frags || !frags.length || base == null) return Math.max(0, Number(media) || 0);
    media = Number(media) || 0;
    let f = frags[0];
    for (const x of frags){ if (x.start <= media + 1e-6) f = x; else break; }
    return Math.max(0, (f.pdt + (media - f.start) * 1000 - base) / 1000);
  },
  /* 録画の秒 → メディアの秒。欠け(繋ぎ直しの間に落ちた時刻)なら次のフラグメントの頭。最初より前は頭・最後より後は終わり。frags が無ければ null */
  mediaOf(frags, base, sec){
    if (!frags || !frags.length || base == null) return null;
    const at = base + Math.max(0, Number(sec) || 0) * 1000;
    for (const f of frags){
      if (at < f.pdt) return f.start;                                  // 欠けの中(か最初より前): 次のフラグメントの頭
      if (at < f.pdt + f.dur * 1000) return f.start + (at - f.pdt) / 1000;
    }
    const l = frags[frags.length - 1];
    return l.start + l.dur;
  },
  /* 録画の長さ = 最後のフラグメントの終わりの受信時刻 − 基準(録画中は伸びる) */
  durationOf(frags, base){
    if (!frags || !frags.length || base == null) return 0;
    const l = frags[frags.length - 1];
    return Math.max(0, (l.pdt + l.dur * 1000 - base) / 1000);
  }
};
/* hls.js(入口の ../live/hls.min.js。ライブの録画を開いたときだけ読む。CSP script-src 'self' のまま) */
let hlsP = null;
function loadHls(){
  if (window.Hls) return Promise.resolve();
  if (hlsP) return hlsP;
  hlsP = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = Studio.live.url('hls.min.js'); s.dataset.hls = '1';
    const timer = setTimeout(() => reject(new Error('timeout')), 15000);
    s.onload = () => { clearTimeout(timer); window.Hls ? resolve() : reject(new Error('no Hls')); };
    s.onerror = () => { clearTimeout(timer); reject(new Error('load')); };
    document.head.appendChild(s);
  }).catch(e => { hlsP = null; document.querySelectorAll('script[data-hls]').forEach(x => x.remove()); throw e; });
  return hlsP;
}
/* ライブの録画: YT.Player と同じ最小インターフェースを持つ <video> + hls.js のアダプタ(LocalPlayer と同じ形)。時刻は LT の「録画の秒」。
   Web Worker は使わない(enableWorker: false。CSP に worker-src を足さないため)。opts.autoplay: 準備ができたら再生を始める(録画中のとき。ライブ端の少し手前から) */
class LivePlayer extends VideoPlayer {
  constructor(host, url, ev, opts){
    super();
    this.ev = ev; this.frags = []; this.base = null; this.ready = false; this.recording = !!(opts && opts.autoplay); this.mediaErrs = 0; this.title = (opts && opts.title) || '';
    const el = this.el = document.createElement('video');
    el.playsInline = true; el.preload = 'auto';
    /* 標準のコントロールは出さない: その時間は「つないだ映像の秒」で、つなぎ直しの欠けがあるとスタジオの時間(受信時刻の幅)と食い違う。
       再生・シーク・音量は下のスタジオの操作で。映像のクリックで再生 / 停止 */
    el.controls = false;
    el.addEventListener('click', () => { if (el.paused) this.playVideo(); else this.pauseVideo(); });
    host.appendChild(el);
    const st = () => ev.onStateChange && ev.onStateChange({ data: this.getPlayerState() });
    for (const n of ['play', 'pause', 'ended', 'waiting', 'playing']) el.addEventListener(n, st);
    const H = window.Hls;
    const hls = this.hls = new H({ enableWorker: false, lowLatencyMode: false, liveDurationInfinity: true, backBufferLength: 90 });
    const onLevel = (_e, d) => {
      const fr = LT.frags(d && d.details && d.details.fragments);
      if (!fr.length) return;
      this.frags = fr;
      const b = LT.base(fr); if (this.base == null || b < this.base) this.base = b;   // 基準は一度決めたら動かさない(先頭が消える再生リストでも)
      if (!this.ready){
        this.ready = true;
        ev.onReady && ev.onReady({ target: this });
        if (opts && opts.autoplay) this.playVideo(true);
      } else st();   // 長さが伸びたことを知らせる(onState が getDuration を読み直す)
    };
    hls.on(H.Events.LEVEL_LOADED, onLevel);
    if (H.Events.LEVEL_UPDATED) hls.on(H.Events.LEVEL_UPDATED, onLevel);
    /* フラグメントを読んだあと、hls.js は映像の実際の時刻(PTS)で fragment.start を直す(繋ぎ直しの欠けのあとで 0.1 秒ほど動く)。
       表を取り直して、getCurrentTime・seekTo を hls.playingDate と同じ値に保つ(2026-10-05 の通しの確認: 欠けのあとのマークが 0.115 秒早かった) */
    if (H.Events.LEVEL_PTS_UPDATED) hls.on(H.Events.LEVEL_PTS_UPDATED, (_e, d) => { const fr = LT.frags(d && d.details && d.details.fragments); if (fr.length && this.ready) this.frags = fr; });
    hls.on(H.Events.ERROR, (_e, d) => {
      if (!d || !d.fatal) return;
      if (d.type === H.ErrorTypes.MEDIA_ERROR && this.mediaErrs++ < 2){   // 映像の読み違い: 2回までは hls.js の直し方で続ける
        try { if (this.mediaErrs === 2 && hls.swapAudioCodec) hls.swapAudioCodec(); hls.recoverMediaError(); return; } catch {}
      }
      const code = d.details === 'manifestIncompatibleCodecsError' || d.details === 'bufferIncompatibleCodecsError' ? 'codec'
        : d.type === H.ErrorTypes.NETWORK_ERROR ? 'network' : (d.details || d.type || 'error');
      ev.onError && ev.onError({ data: code });
    });
    try { hls.loadSource(url); hls.attachMedia(el); }
    catch { setTimeout(() => ev.onError && ev.onError({ data: 'error' }), 0); }
  }
  getDuration(){ return LT.durationOf(this.frags, this.base); }
  /* hls.playingDate(再生位置の受信時刻)− 基準 と同じ値を、フラグメントの表から計算する(seekTo と同じ表を使うので、行き来しても揺れない) */
  getCurrentTime(){
    if (this.frags.length) return LT.timeOf(this.frags, this.base, this.el.currentTime || 0);
    const d = this.hls && this.hls.playingDate;
    return d && this.base != null ? Math.max(0, (d.getTime() - this.base) / 1000) : 0;
  }
  getVideoData(){ return { isLive: this.recording, title: this.title }; }
  seekTo(t){ const m = LT.mediaOf(this.frags, this.base, t); if (m != null) try { this.el.currentTime = m; } catch {} }
  /* ライブ端の少し手前へ(hls.js の liveSyncPosition。無ければ録画の終わりの 8 秒前) */
  goLive(){
    const p = this.hls && this.hls.liveSyncPosition;
    if (Number.isFinite(p)) try { this.el.currentTime = p; } catch {}
    else this.seekTo(Math.max(0, this.getDuration() - 8));
    this.playVideo();
  }
  playVideo(auto){
    const r = this.el.play();
    if (r && r.catch) r.catch(e => { if (auto && e && e.name === 'NotAllowedError' && this.ev.onAutoplayBlocked) this.ev.onAutoplayBlocked(); });
  }
  destroy(){
    if (this.hls){ try { this.hls.destroy(); } catch {} this.hls = null; }
    super.destroy();
  }
}
function unmountPlayer(){
  playerToken++; stopPoll(); clearYtReadyTimer();
  if (yt){ try { yt.destroy(); } catch {} yt = null; }
  S.playerAlive = false; S.playerErr = false; S.playerState = -1; S.previewEnd = null; hideNotice(); phMsg('');
  const host = $('#rvHost'); if (host) host.innerHTML = '';
}
async function mountPlayer(){
  unmountPlayer();
  const token = playerToken, v = S.cur;
  if (!v) return;
  const host = $('#rvHost');
  let timedOut = false;   // 準備の時間切れの案内を出したあとか
  const onReady = e => {
    if (token !== playerToken) return;
    clearYtReadyTimer();
    if (timedOut){ timedOut = false; S.playerErr = false; hideNotice(); }   // 遅れて準備ができた: 案内を消して使えるようにする
    S.playerAlive = true; phMsg('');
    const d = e.target.getDuration(); if (d > 0) setDuration(d);
    /* 前回の場所(S-8)へ。録画中のライブの録画はライブ端から(戻さない)。YouTube は作るときの start で合わせてある(seekTo は止めている動画を再生してしまう) */
    if (S.resumeAt != null){
      if (e.target.recording) S.resumeAt = null;
      else if (v.kind !== 'youtube'){ try { e.target.seekTo(S.resumeAt); } catch {} }
    }
    e.target.setPlaybackRate(S.rate);
    applyToPlayer(); startPoll(); setTimeout(updateLive, 400); setTimeout(autoTitleFromPlayer, 1500);
  };
  const onState = e => {
    if (token !== playerToken) return;
    S.playerState = e.data;
    if (e.data === 1){ autoTitleFromPlayer(); updateLive(); }
    const d = yt && yt.getDuration ? yt.getDuration() : 0; if (d > 0 && d !== S.duration) setDuration(d);
  };
  if (v.kind === 'live'){ mountLivePlayer(host, token, v, onReady, onState); return; }
  phMsg('プレーヤーを準備しています…');
  if (v.kind === 'file'){
    yt = new LocalPlayer(host, Studio.url('/media?id=' + enc(v.id)), { onReady, onStateChange: onState, onError: e => { if (token === playerToken) showNotice(ytErrorMessage(e.data)); } });
    return;
  }
  if (location.protocol === 'file:'){ showNotice('file:// で開くとYouTube埋め込みが動きません。サーバーを起動して http://localhost から開いてください。'); return; }
  const mount = document.createElement('div'); host.appendChild(mount);
  try { await loadYTApi(); }
  catch { if (token === playerToken) showNotice('YouTube のプレーヤーを読み込めません(ネットの接続を確かめてください)。', { retry: true }); return; }
  if (token !== playerToken) return;
  const notReady = '時刻の手入力でマークは続けられます。';
  try {
    yt = new YT.Player(mount, {
      width: '100%', height: '100%', videoId: v.id,
      playerVars: { playsinline: 1, rel: 0, origin: location.origin, hl: 'ja', cc_load_policy: 0, ...(S.resumeAt >= 1 ? { start: Math.floor(S.resumeAt) } : {}) },
      events: { onReady, onStateChange: onState, onError: e => { if (token !== playerToken) return; clearYtReadyTimer(); showNotice(ytErrorMessage(e.data)); } }
    });
  } catch {
    if (token === playerToken) showNotice('YouTube のプレーヤーを作れませんでした(回線・埋め込みの制限のおそれ)。' + notReady, { retry: true });
    return;
  }
  // onReady も onError も来ないまま止まる場合(回線・埋め込みの制限)。自動では再試行しない(YouTube に何度も繋ぎに行かない)
  clearYtReadyTimer();
  ytReadyTimer = setTimeout(() => {
    ytReadyTimer = null;
    if (token !== playerToken || S.playerAlive) return;
    timedOut = true;
    showNotice('YouTube のプレーヤーの準備が終わりません(回線・埋め込みの制限のおそれ)。' + notReady, { retry: true });
  }, S.ytReadyMs);
}
/* ライブの録画のプレーヤー。まだ録れたセグメントが無い(配信待ち)間は作らず、録画の状態の見回り(applyLiveStatus)が録れ始めたのを見て作り直す */
const LIVE_PLAY_ERR = {
  codec: 'このブラウザでは録画の映像(H.264)を再生できません(Edge か Chrome で開いてください)。',
  network: '録画を読み込めませんでした(録画元につながらないかもしれません)。少し待ってから「もう一度試す」を押してください。',
  unsupported: 'このブラウザでは録画を再生できません(Edge か Chrome で開いてください)。'
};
async function mountLivePlayer(host, token, v, onReady, onState){
  const keep = 'マークの時刻の手入力・書き出しは続けられます。';
  if (!Studio.token || !v.live || !v.live.recorder || !v.live.recording){ showNotice('ライブの録画は、ホーム(start.bat)から開いたときだけ再生できます。' + keep); return; }
  if (LV.vid === v.id && LV.deletedShown){ LV.deletedShown = false; liveDeletedShown(v); return; }   // 自動で消した録画(P4): 案内をもう一度出す
  const st = LV.vid === v.id ? LV.status : null;
  if (!st || !(Number(st.segments) > 0)){
    LV.waitPlay = true;
    phMsg(st ? '配信が始まるのを待っています。始まると自動で再生します' : '録画の状態を確かめています…');
    return;
  }
  LV.waitPlay = false;
  phMsg('録画を読み込んでいます…');
  try { await loadHls(); }
  catch { if (token === playerToken) showNotice('再生の部品(hls.js)を読み込めませんでした(ホームが古いままかもしれません)。' + keep, { retry: true }); return; }
  if (token !== playerToken) return;
  let ok = false; try { ok = !!(window.Hls && Hls.isSupported()); } catch {}
  if (!ok){ showNotice(LIVE_PLAY_ERR.unsupported + keep); return; }
  const autoplay = !!st.active && visible();   // 録画中なら、ライブ端の少し手前から自動で再生する(終わった録画は頭から・自動では再生しない)
  try {
    yt = new LivePlayer(host, Studio.live.url(liveRest(v, 'index.m3u8')), {
      onReady, onStateChange: onState,
      onError: e => { if (token !== playerToken) return; showNotice((LIVE_PLAY_ERR[e.data] || '録画を再生できませんでした(' + e.data + ')。') + keep, { retry: e.data !== 'codec' }); },
      onAutoplayBlocked: () => { if (token === playerToken) toast('自動では再生できませんでした。「再生 / 停止」を押すと再生します', 6000); }
    }, { autoplay, title: v.title || '' });
    yt.recording = !!st.active;
  } catch { if (token === playerToken) showNotice('録画のプレーヤーを作れませんでした。' + keep, { retry: true }); }
}
function startPoll(){
  stopPoll();
  if (!yt || !visible()) return;
  pollTimer = setInterval(() => {
    if (!yt || !yt.getCurrentTime) return;
    if (Date.now() - lastSeekAt < 400) return; // seek直後は古い値が返るので無視
    S.playerState = yt.getPlayerState();
    if (++pollTick % 5 === 0) syncVolumeFromPlayer();
    const cur = yt.getCurrentTime();
    /* 前回の場所へ戻した直後: プレーヤーがその位置に来る(か再生を始める)までは、表示と覚える位置を 0 に戻さない(YouTube は再生を押すまで 0 を返す) */
    if (S.resumeAt != null && S.playerState !== 1 && Math.abs(cur - S.resumeAt) >= 1.5){ /* 待つ */ }
    else { S.resumeAt = null; setNow(cur); }
    if (pollTick % 10 === 0) updateLive();
    if (S.previewEnd != null && S.now >= S.previewEnd - 0.05){ yt.pauseVideo(); setNow(S.previewEnd); S.previewEnd = null; }
  }, 100);
}
function stopPoll(){ if (pollTimer){ clearInterval(pollTimer); pollTimer = null; } }
function pausePlayback(){
  S.previewEnd = null;
  // 読み込み中(3)も止める: ライブの録画・動画ファイルは、読み込みを待っている間に離れると、読めたあとで再生が始まっていた
  try { if (yt && yt.pauseVideo && (S.playerState === 1 || S.playerState === 3)) yt.pauseVideo(); } catch {}
}
function setNow(t){
  S.now = t;
  const inp = $('#rvNow'); if (inp && document.activeElement !== inp) inp.value = fmt(t);
  renderPlayhead();
  placeNote();
}
/* final = false はタイムラインをドラッグしている途中(YouTube の seekTo の allowSeekAhead) */
function seek(t, final = true){
  S.resumeAt = null;   // 自分で動かした: 前回の場所への合わせはやめる
  t = Math.max(0, S.duration ? Math.min(t, S.duration) : t);
  if (yt){ try { yt.seekTo(t, final); } catch {} lastSeekAt = Date.now(); }
  setNow(t);
}
function togglePlay(){
  if (!canPlay()) return noPlayerToast();   // 自分で押したときだけ知らせる
  if (S.playerState === 1) yt.pauseVideo(); else yt.playVideo();
}
/* マークの区間を再生する。auto = 前後のマークへ移動したときの自動再生(使えないときは黙って位置だけ動かす) */
function previewClip(c, auto){
  if (!canPlay()){ seek(c.start); if (!auto) noPlayerToast(); return; }
  seek(c.start); S.previewEnd = c.end; yt.playVideo();
}
// iframe内をクリックするとフォーカスがiframeに移り、親ページのショートカットが効かなくなるため、マウスが外れたら戻す
function reclaimFocus(){
  const a = document.activeElement;
  if (a && a.tagName === 'IFRAME'){ const pb = $('#rvPlayerBox'); pb.tabIndex = -1; pb.focus({ preventScroll: true }); }
}

/* ---------- 音量・設定の保存(/api/settings の settings.review だけを読み書き)---------- */
/* 監査 11(全体の計画 段2): 保存の失敗は ⚙ の印と設定の引き出しの先頭に出して [もう一度](UIKit.settings.status)。成功したら消す。
   読み込みに失敗したら既定値で始めるが、読み直すまで保存しない(既定値で保存済みの設定を上書きしないため) */
let setTimer = null, setFailed = false, setLoadErr = '';
const settingsStatus = (...a) => { if (window.UIKit && UIKit.settings && UIKit.settings.status) UIKit.settings.status(...a); };
function touchSettings(){ clearTimeout(setTimer); setTimer = setTimeout(saveSettings, 600); }
async function saveSettings(){
  clearTimeout(setTimer); setTimer = null;
  if (setLoadErr) return false;
  try {
    // review の節だけを送る(サーバーがロックの中で合わせる。別のタブが別の節を同時に保存しても消し合わない)
    await Studio.api('/api/settings', { method: 'PUT', body: { section: 'review', value: { ...S.settings } } });
    if (setFailed){ setFailed = false; settingsStatus(''); }
    return true;
  } catch (e){
    setFailed = true;
    settingsStatus('err', '設定を保存できていません: ' + (e && e.message || 'エラー'), () => saveSettings());
    return false;
  }
}
async function loadSettings(){
  try {
    const j = await Studio.api('/api/settings'), raw = j && j.settings && j.settings.review;
    S.settings = sanitizeSettings(raw);
    if (setLoadErr){ setLoadErr = ''; settingsStatus(''); }
    if (!(raw && typeof raw.autoTx === 'boolean') && autoTxLegacy() !== null) touchSettings();   // 前のこのブラウザの「書き出しのあと自動で文字起こし」を1回だけサーバーへ(0.22.0)
  } catch (e){
    S.settings = sanitizeSettings({});
    setLoadErr = (e && e.message) || 'エラー';
    settingsStatus('err', `設定を読み込めませんでした(${setLoadErr})。読み直すまで、ここで変えた設定は保存しません`, () => loadSettings(), '読み直す');
  }
  if (KM) KM.reload();
  syncSettingsUI(); applyTheater();
}
function syncSettingsUI(){
  const s = S.settings;
  $('#rvVol').value = s.volume; $('#rvVolOut').textContent = s.volume; $('#rvMute').checked = s.muted;
  renderKeyUI(); $('#rvLag').value = String(s.lag); $('#rvLiveMode').value = s.liveMode;
  $('#rvHeight').value = String(s.maxHeight); $('#rvPrecision').value = s.precision;
  $('#rvExpVol').value = s.exportVolume; $('#rvExpVolOut').textContent = s.exportVolume;
  $('#rvExpLoud').value = String(s.exportLoudness); $('#rvExpVol').disabled = !!s.exportLoudness;
  /* 音量をそろえるときは使わない欄: 薄く見せ、押せない欄であることと理由を属性で伝える(押せない物は薄くてよい。A-22・A-34) */
  { const vb = $('#rvExpVolBox'), off = !!s.exportLoudness; vb.classList.toggle('rv-off', off); vb.setAttribute('aria-disabled', String(off)); vb.title = off ? '音量のそろえ方が「そろえない」のときだけ使います' : ''; }
  expSetSummary();
  { const ae = $('#rvAutoExp'); if (ae) ae.checked = s.liveAutoExport; }
  { const dk = $('#rvDuck'); if (dk) dk.value = s.liveDuck; }
  { const af = $('#rvAfter'); if (af) af.value = s.liveAfter; }
  { const at = $('#setAutoTx'); if (at) at.checked = s.autoTx !== false; }   // 設定の「書き出し」節(settings.js が作る。入口から開いたときだけ)
  $('#rvAutoPlay').checked = s.autoPlay; $('#rvAutoNext').checked = s.autoNext; $('#rvSort').value = s.sortBy; $('#rvExpTarget').value = s.exportTarget;
}
/* 「書き出しの設定」を閉じていても、いまの設定が分かるように見出しの横に短く出す */
function expSetSummary(){
  const el = $('#rvExpSetSum'); if (!el) return;
  const s = S.settings, v = S.cur;
  const parts = [{ adopted: '採用のみ', pending: '採用 + 候補', all: '不採用以外' }[s.exportTarget] || '', s.precision === 'fast' ? '高速' : '精密'];
  if (!(v && (v.kind === 'file' || v.kind === 'live'))) parts.push(s.maxHeight ? s.maxHeight + 'p まで' : '画質の制限なし');
  parts.push(s.exportLoudness ? s.exportLoudness + ' LUFS' : '音量 ' + s.exportVolume + '%');
  el.textContent = parts.filter(Boolean).join(' ・ ');
}
/* ライブの録画: ほかの窓(別の窓で開いた「編集」)で音が鳴っている間は、配信の音を下げる(2 割)か消す(UIKit.sound。設定 liveDuck)。
   音が二重になって文字起こしを聞き取れない(2026-10-05 ユーザー)。設定の音量・消音そのものは変えない(止まれば元の音に戻る) */
const DUCK_RATIO = 0.2;
function duckMode(){
  if (!(S.cur && S.cur.kind === 'live') || S.settings.liveDuck === 'off') return 'off';
  return window.UIKit && UIKit.sound && UIKit.sound.other('studio') ? S.settings.liveDuck : 'off';
}
function applyToPlayer(){
  const mode = duckMode();
  { const el = $('#rvDuckNote'); if (el){ el.hidden = mode === 'off'; if (mode !== 'off') liveSet('#rvDuckNote', mode === 'mute' ? '編集で再生中: 配信の音を消しています' : '編集で再生中: 配信の音を下げています'); } }
  if (!yt) return;
  lastApplyAt = Date.now();
  try { yt.setVolume(mode === 'low' ? Math.round(S.settings.volume * DUCK_RATIO) : S.settings.volume); if (S.settings.muted || mode === 'mute') yt.mute(); else yt.unMute(); } catch {}
}
function syncVolumeFromPlayer(){ // プレーヤー側(標準UI)での変更を設定へ反映
  if (S.cur && S.cur.kind === 'live') return;   // ライブの録画は標準のコントロールを出さない(下げている間の音量を設定に書き戻さない)
  if (Date.now() - lastApplyAt < 1500) return;
  try {
    const vol = Math.round(yt.getVolume()), mu = !!yt.isMuted();
    if (vol !== S.settings.volume || mu !== S.settings.muted){ S.settings.volume = vol; S.settings.muted = mu; syncSettingsUI(); touchSettings(); }
  } catch {}
}
function adjustVolume(d){ S.settings.volume = Math.min(100, Math.max(0, S.settings.volume + d)); syncSettingsUI(); applyToPlayer(); touchSettings(); }
function toggleMute(){ S.settings.muted = !S.settings.muted; syncSettingsUI(); applyToPlayer(); touchSettings(); }
function wireSettings(){
  $('#rvVol').addEventListener('input', e => {
    S.settings.volume = Number(e.target.value); $('#rvVolOut').textContent = S.settings.volume;
    applyToPlayer();
    touchSettings();
  });
  $('#rvMute').addEventListener('change', e => { S.settings.muted = e.target.checked; applyToPlayer(); touchSettings(); });
  $('#rvLag').addEventListener('change', e => { S.settings.lag = Number(e.target.value) || 0; touchSettings(); });
  $('#rvLiveMode').addEventListener('change', e => { S.settings.liveMode = e.target.value; updateLive(); touchSettings(); });
  $('#rvPrecision').addEventListener('change', e => { S.settings.precision = e.target.value === 'fast' ? 'fast' : 'accurate'; touchSettings(); expSetSummary(); });
  $('#rvHeight').addEventListener('change', e => { S.settings.maxHeight = Number(e.target.value); touchSettings(); expSetSummary(); });
  $('#rvExpVol').addEventListener('input', e => {
    S.settings.exportVolume = Number(e.target.value); $('#rvExpVolOut').textContent = S.settings.exportVolume;
    touchSettings(); expSetSummary();
  });
  $('#rvExpLoud').addEventListener('change', e => { S.settings.exportLoudness = Number(e.target.value) || 0; syncSettingsUI(); touchSettings(); });
  $('#rvAutoPlay').addEventListener('change', e => { S.settings.autoPlay = e.target.checked; touchSettings(); });
  $('#rvAutoNext').addEventListener('change', e => { S.settings.autoNext = e.target.checked; touchSettings(); });
  $('#rvSort').addEventListener('change', e => { S.settings.sortBy = e.target.value === 'score' ? 'score' : 'time'; touchSettings(); renderList(); });
  $('#rvExpTarget').addEventListener('change', e => { S.settings.exportTarget = ['adopted', 'pending', 'all'].includes(e.target.value) ? e.target.value : 'adopted'; touchSettings(); renderExportUI(); expSetSummary(); });
}

/* ---------- キー配置 ---------- */
/* キーの表記と、押したキーの組み合わせ(Shift+j など)は ui-kit の 1 か所(? の一覧・編集と同じ) */
const keyText = combo => (window.UIKit && UIKit.keys ? UIKit.keys.keyText(combo) : combo || '未設定');
const comboOf = e => (window.UIKit && UIKit.keys ? UIKit.keys.comboOf(e) : '');
/* ACTION_DEFS の操作 → 実行(I/O・再生・移動は共通の再生キー UIKit.keys.playback が受け持つ) */
const ACTION_FN = {
  addClip: () => addClip(), quickMark: () => quickMark(0), quickMark2: () => quickMark(1), quickMark3: () => quickMark(2), quickMark4: () => quickMark(3), quickMark5: () => quickMark(4),
  volUp: () => adjustVolume(5), volDown: () => adjustVolume(-5), mute: () => toggleMute(), theater: () => toggleTheater(),
  prevMark: () => goMark(-1, false), nextMark: () => goMark(1, false), adopt: () => decideSel('adopted'), reject: () => decideSel('rejected'),
  moment: () => momentMark()
};
function currentPreset(){
  const km = S.settings.keymap;
  return Object.keys(KEY_PRESETS).find(n => ACTION_DEFS.every(([id]) => (KEY_PRESETS[n][id] || '') === (km[id] || ''))) || 'custom';
}
const KEY_GROUPS = [['マークの操作', ['addClip', 'moment']], ['今をマーク(長さは ③ のボタンの横の − ＋ で変更)', ['quickMark', 'quickMark2', 'quickMark3', 'quickMark4', 'quickMark5']], ['判定・移動', ['prevMark', 'nextMark', 'adopt', 'reject']], ['音量・表示', ['volUp', 'volDown', 'mute', 'theater']]];
/* 割り当てられないキー(固定の意味がある)。値は使い道 */
const STUDIO_FIXED = { Escape: '閉じる・取り消し', Enter: '確定', Tab: 'フォーカスの移動', 'Shift+Tab': 'フォーカスの移動', '?': 'キー操作の一覧' };
const PRESET_NAMES = { standard: '標準', left: '左手だけ' };
/* プリセットの名前は実際の割り当てから(S-28。以前は「標準(I O A ・矢印)」と実際と違う文字だった) */
function presetLabel(n){
  const p = KEY_PRESETS[n], k = id => keyText(p[id]);
  return `${PRESET_NAMES[n]}(マーク追加 ${k('addClip')}・採用 ${k('adopt')}・不採用 ${k('reject')}・前後のマーク ${k('prevMark')} ${k('nextMark')})`;
}
/* キーの一覧 = キー配置(UIKit.keymap。気が利く画面へ 段6): ? の一覧と「操作の設定 → キー配置」は同じ部品。共通の再生キー(Space・J/K/L など)も
   ここで変えられる(ホームの設定。編集と同じ割り当て。S-27)。重なりの検査は部品の 1 か所 */
const KM = window.UIKit && UIKit.keymap ? UIKit.keymap.create({
  groups: KEY_GROUPS.map(([h], i) => ['g' + i, h]),
  actions: ACTION_DEFS.map(([id, label]) => ({ id, def: KEY_PRESETS.standard[id], label, group: 'g' + KEY_GROUPS.findIndex(g => g[1].includes(id)) })),
  refuse: combo => STUDIO_FIXED[combo] || '',
  intro: '③ 確認・書き出しで配信を開いているときに使えます(文字の入力欄にいる間は効きません)。キーのボタンを押してから、割り当てたいキーを押します(Esc = 取り消し・Delete = 外す)。すでに使っているキーを選ぶと、そちらの割り当てが外れます(すぐ下の「戻す」で戻せます)。',
  fixed: [{ title: '全体', rows: [['?', 'この一覧を開く・閉じる', '一覧を開くキー'], ['Esc', '一覧・設定を閉じる', '閉じるキー']] },
    { title: 'その他', why: '入力欄のキー', rows: [['Enter', '時刻の欄: 確定して移動 / ラベル: 確定']] }],
  /* 今をマークの長さは見せるだけ(変えるのは ③ のボタンの横の − ＋ の1か所。設定の場所を重ねない 2026-10-04) */
  extra: id => { const m = /^quickMark(\d?)$/.exec(id); return m ? `<span class="muted rv-kmspan">前後${spanLabel((S.settings ? S.settings.quickSpans : DEFAULT_QUICK_SPANS)[m[1] ? Number(m[1]) - 1 : 0])}</span>` : ''; },
  footNote: '「すべて標準に戻す」は共通の再生キーも標準に戻します(編集も同じ割り当てです)。',
  load: () => (S.settings && S.settings.keymap) || {},
  save: km => { S.settings.keymap = km; touchSettings(); },
  onChange: () => renderKeyUI()
}) : null;
const curKeymap = () => (KM ? KM.map() : S.settings.keymap);
function spanSelHTML(i){
  const cur = S.settings.quickSpans[i];
  return `<span class="rv-stepper"><button type="button" class="rv-step" data-slot="${i}" data-d="-1" aria-label="ボタン${i + 1}の長さを短く">−</button><span class="rv-stv"><span class="rv-pre">前後</span>${spanLabel(cur)}</span><button type="button" class="rv-step" data-slot="${i}" data-d="1" aria-label="ボタン${i + 1}の長さを長く">＋</button></span>`;
}
function onSpanStep(e){
  const b = e.target.closest('.rv-step'); if (!b) return;
  const i = Number(b.dataset.slot), d = Number(b.dataset.d), cur = S.settings.quickSpans[i];
  const L = QUICK_SPAN_CHOICES; let idx = L.findIndex(x => x >= cur); if (idx < 0) idx = L.length; // 一覧にない値は最寄りの段へ
  idx = L[idx] === cur ? idx + d : (d > 0 ? idx : idx - 1);
  idx = Math.min(L.length - 1, Math.max(0, idx));
  const q = S.settings.quickSpans.slice(); q[i] = QUICK_SPAN_CHOICES[idx]; S.settings.quickSpans = q;
  renderKeyUI(); touchSettings();
}
function renderKeyUI(){
  const km = curKeymap();
  $('#rvQuickSlots').innerHTML = S.settings.quickSpans.map((sp, i) =>
    `<div class="rv-qslot"><button class="btn${i === 0 ? ' soft' : ''}" type="button" data-slot="${i}" title="今の位置の前後${spanLabel(sp)}をマーク"><span class="rv-qn">${i + 1}</span><kbd class="ui-kbd" data-kbd="${i ? 'quickMark' + (i + 1) : 'quickMark'}"></kbd></button>${spanSelHTML(i)}</div>`).join('');
  for (const el of document.querySelectorAll('#rvRoot kbd[data-kbd]')){ el.textContent = km[el.dataset.kbd] ? keyText(km[el.dataset.kbd]) : ''; el.hidden = !km[el.dataset.kbd]; }   // 割り当てを外したら、ボタンの横のキーも出さない
  const pre = $('#rvKeyPreset');
  if (pre){
    for (const o of pre.options) if (PRESET_NAMES[o.value]) o.textContent = presetLabel(o.value);
    pre.value = currentPreset();
  }
  if (Studio.step === 'review') keybarScene();   // キー配置を変えたら、下の帯もすぐ合わせる
}

/* ---------- ライブ配信 ---------- */
// IFrame APIの仕様上、ライブ中の getDuration() は「配信開始からの経過時間」を返す。
/* マークの「ライブ」の印 = YouTube の配信中に付けた(あとでアーカイブの時刻へずらす対象)。ライブの録画の時刻は録画の秒で、ずらす物ではないので付けない・出さない */
const markLive = () => !!S.live && !(S.cur && S.cur.kind === 'live');
function renderLiveCount(){
  const n = marks().filter(c => c.live).length;
  $('#rvLiveMarks').textContent = n + '件'; $('#rvShiftCount').textContent = n ? `対象 ${n}件` : '対象なし';
}
function updateLive(){
  if (!S.cur) return;
  const rec = S.cur.kind === 'live';   // ライブの録画: 録画中か = 録画の状態(LV.status.active)。帯は録画が終わっても出す(状態・終わりの案内を出す所)
  if (!yt && !rec) return;
  const isFile = S.cur.kind === 'file';
  let live = S.settings.liveMode === 'on' && !isFile;
  if (rec) live = liveRecActive(S.cur);
  else if (S.settings.liveMode === 'auto'){
    try { live = !isFile && !!(yt.getVideoData && yt.getVideoData().isLive); } catch { live = false; }
  }
  if (live !== S.live){ S.live = live; if (rec) renderExportUI(); }
  $('#rvLiveBar').hidden = !(live || rec);
  { const lm = $('#rvLiveMarks'); lm.hidden = rec; if (lm.previousElementSibling) lm.previousElementSibling.hidden = rec; }   // ライブ印の件数は、録画では出さない
  if (rec) renderLiveRec();
  if (!S.live || !yt) return;
  let e = 0; try { e = yt.getDuration(); } catch {}
  if (e > 0 && Math.abs(e - S.duration) >= 1) setDuration(e);
  $('#rvLiveElapsed').textContent = fmt(S.duration);
  const gap = S.duration - S.now;
  $('#rvLiveGap').textContent = (gap >= 0 ? '−' : '+') + Math.round(Math.abs(gap)) + '秒';
}

/* ---------- ライブの録画(kind live。線 D の P3。plan/line-d-live-clipping.md の 0-8) ----------
   録画 = スタジオの配信1本。マークはいつものマーク(保存も PUT /api/video)で、時刻は「録画の最初のセグメントの受信時刻」からの秒(LT)。
   画面が入口の ../live/… を呼ぶ(Studio.live): 録画の状態(r/<録画元>/<録画>/status。3 秒ごと・見えている間だけ)・停止・書き出し(api/export)・書き出しの一覧(api/exports)。
   入口の書き出しが済んだマークは POST /api/live/exported でスタジオの「書き出し済み」にする(閉じていた間に済んだ分は、次に開いたときに突き合わせる)。
   定期的な見回りでは一覧やボタンを作り直さない(文字と属性だけを差分で直す。0-7 の 2) */
const LIVE_ACTIVE = ['wait', 'fetch', 'encode'];
const LIVE_JOB_ST = { wait: 'queued', fetch: 'running', encode: 'running', done: 'done', error: 'error', cancelled: 'cancelled' };
const LIVE_JOB_LABEL = { wait: '録画待ち', fetch: '取得中', encode: '作り直し中', done: '済み', error: '失敗', cancelled: '取り消し' };
const LIVE_REC_STATE = { waiting: ['wait', '配信を待っています'], recording: ['run', '録画中'], reconnecting: ['warn', 'つなぎ直し中'], stopped: ['ok', '停止'], ended: ['ok', '終了'], error: ['err', 'エラー'] };
/* アーカイブで本番版に作り直す(P4。計画の 0-9)。ジョブの archive.state。wait = 順番・アーカイブの用意を待っている(見回りはゆっくり)、ほかは動いている */
const ARCH_RUN = ['probe', 'align', 'fetch', 'verify'];
const ARCH_ACTIVE = ['wait', ...ARCH_RUN];
const ARCH_LABEL = { wait: '待ち', probe: 'アーカイブを確かめ中', align: '照合中', fetch: '取得中', verify: '検証中', done: '本番版', error: '失敗', cancelled: '取り消し' };
const ARCH_TITLE = 'アーカイブから作り直して、速報版と入れ替えました';
/* 配信後の全自動(線 D の M7)の afterStream.state のうち、もう進まないもの(入口の src/home/live_archive.py の AFTER_END と同じ) */
const AFTER_END = ['done', 'none', 'error'];
const LV = { vid: null, status: null, err: null, seq: 0, timer: 0, waitPlay: false, wasActive: null, endedShown: false,
  jobs: [], jobsKnown: false, jobsSeq: 0, jobsAt: 0, prevJobs: new Map(), busy: new Set(), queued: new Set(), applied: new Set(), chain: Promise.resolve(), starting: false,
  archiveInfo: null, archStarting: false, archCancelling: false, archMsg: '', autoArchive: null, autoDelete: null, deletedShown: false,
  who: null };   // who: 帯の「配信者」(liveWhoOpened)
const liveRest = (v, tail) => 'r/' + enc(v.live.recorder) + '/' + enc(v.live.recording) + '/' + tail;
const liveRecId = v => (v && v.live && v.live.recording) || (v && v.id) || '';
/* YouTube の配信へのリンク(動画の id が分かるときだけ。録画の秒は配信の秒ではないので時刻は付けない) */
function liveVideoId(v){ const id = v && v.kind === 'live' && v.live && v.live.videoId; return id && /^[\w-]{11}$/.test(id) ? id : ''; }
function liveYtHref(v){ const id = liveVideoId(v); return id ? 'https://www.youtube.com/watch?v=' + id : ''; }
/* 録画中か。開いている1本は録画の状態(3 秒ごと)、ほかはヘッダーの札(UIKit.liveBadge。10 秒ごと)から */
function liveRecActive(v){
  if (!v || v.kind !== 'live') return false;
  if (LV.vid === v.id && LV.status) return !!LV.status.active;
  const lb = window.UIKit && UIKit.liveBadge && UIKit.liveBadge.get ? UIKit.liveBadge.get() : null, rid = liveRecId(v);
  return !!(lb && lb.enabled && (lb.recordings || []).some(r => r.id === rid && r.active && (!r.recorder || !v.live || r.recorder === v.live.recorder)));
}
const liveAutoExportOn = v => !!(v && v.kind === 'live' && Studio.token && S.settings.liveAutoExport);
const liveSet = (sel, t) => { const el = $(sel); if (el && el.textContent !== t) el.textContent = t; };
/* 録画の合計の長さ(秒)。受信時刻の幅とセグメントの長さの合計の大きい方(欠けの間も時間は進む) */
function liveTotal(st){
  if (!st) return 0;
  const a = Date.parse(st.firstPdt), b = Date.parse(st.lastPdt);
  return Math.max(Number(st.seconds) || 0, Number.isFinite(a) && Number.isFinite(b) ? (b - a) / 1000 : 0);
}

/* 入口の書き出しのジョブ → renderJob が読む形({id, live, state, items: [{id, start, end, title, status, progress, path, file, …}]})。この配信の分だけ・古い順(番号が動かない)・新しい 40 件 */
function liveJobView(vid, jobs){
  const own = (jobs || []).filter(j => j && j.studio && j.studio.video === vid)
    .sort((a, b) => String(a.created || '').localeCompare(String(b.created || ''))).slice(-40);
  const items = own.map(j => {
    const path = typeof j.path === 'string' ? j.path : '', active = LIVE_ACTIVE.includes(j.state);
    return { id: j.studio.mark, jobId: j.id, start: Number(j.studio.start) || 0, end: Number(j.studio.end) || 0, title: j.label || '',
      status: LIVE_JOB_ST[j.state] || 'queued', stateLabel: j.stateLabel || LIVE_JOB_LABEL[j.state] || String(j.state || ''),
      progress: Number(j.progress) || 0, path, file: path ? path.split(/[\\/]/).pop() : '', manifest: j.manifest || '',
      message: active ? String(j.message || '') : '', error: j.state === 'error' ? String(j.error || j.message || '') : '', warning: String(j.warning || ''), tx: j.tx || null,
      needsArchive: j.state === 'error' && !!j.needsArchive, archive: liveArchView(j.archive) };
  });
  return { id: 'live:' + vid, live: true, state: own.some(j => LIVE_ACTIVE.includes(j.state)) ? 'running' : 'done', items };
}
/* ジョブの archive(入口の本番版への作り直し)→ 行に出す形 {state, label, progress, message}。無い・形が違えば null */
function liveArchView(a){
  if (!a || typeof a !== 'object' || !a.state) return null;
  const state = String(a.state);
  return { state, label: String(a.label || ARCH_LABEL[state] || state), progress: Math.max(0, Math.min(1, Number(a.progress) || 0)),
    message: String(a.message || ''), active: ARCH_ACTIVE.includes(state), packOld: state === 'done' && !!a.packOld };
}
/* 入口が録画を自動で消したか(P4 の「録画を自動で消す」)。録画の状態が 404 で、入口のジョブに recordingDeleted がある
   (ジョブの記録が古くて消えていても、書き出し済みのマークが全部「本番版」なら同じ)。マークが本番版でないのに 404 は「録画が見つかりません」のまま */
function liveRecDeleted(err, jobs, marks){
  if (!err || err.status !== 404) return false;
  if ((jobs || []).some(j => j && j.recordingDeleted)) return true;
  const exp = (marks || []).filter(m => m && m.status === 'exported');
  return exp.length > 0 && exp.every(m => m.archived);
}
const LIVE_DELETED = '録画は消しました(本番版に入れ替え済み)。マークと本番版はそのまま使えます';
const liveArchBusy = j => !!(j && j.archive && ARCH_ACTIVE.includes(j.archive.state));
const liveArchRunning = j => !!(j && j.archive && ARCH_RUN.includes(j.archive.state));
/* 本番版に作り直す対象(入口と同じ決め方): マークごとの最新のジョブで、済み(入れ替え)か、欠けで書き出せなかった(error + needsArchive。新しく作る)もの */
function liveArchTargets(jobs){
  const last = new Map();
  for (const j of jobs || []){
    if (!j || !j.studio || !j.studio.mark) continue;
    const p = last.get(j.studio.mark);
    if (!p || String(j.created || '') >= String(p.created || '')) last.set(j.studio.mark, j);
  }
  return [...last.values()].filter(j => j.state === 'done' || (j.state === 'error' && j.needsArchive));
}
/* 終わった録画の帯の「アーカイブで作り直す」の1行とボタンの状態。o: {videoId, known(ジョブを読めた), starting, msg(断られたときの入口の文), autoOn}
   → {text, warn, can, why, running, total, done, pending} */
function liveArchSummary(jobs, info, o){
  o = o || {};
  const t = liveArchTargets(jobs), total = t.length, done = t.filter(j => j.archive && j.archive.state === 'done').length, pending = total - done;
  const busy = (jobs || []).filter(liveArchBusy), running = busy.length > 0;
  const errs = t.filter(j => j.archive && j.archive.state === 'error').map(j => String(j.archive.message || j.archive.label || '理由は分かりません'));
  const r = { text: '', warn: false, can: false, why: '', running, total, done, pending };
  if (!o.videoId){ r.text = 'YouTube の動画が分からない録画なので、アーカイブで作り直せません'; r.why = r.text; return r; }
  if (running){
    const cur = busy.find(liveArchRunning) || busy[0], a = liveArchView(cur.archive);
    r.text = `本番版に作り直しています ${done}/${total} 本` + (a && a.label ? `(${a.label})` : '');
    r.why = '作り直しています(「取り消す」で止められます)';
    return r;
  }
  const parts = [];
  if (o.msg){ parts.push(o.msg); r.warn = true; }
  else if (pending && info && info.ready === false) parts.push('アーカイブがまだ用意できていません' + (o.autoOn ? '(自動で確かめ直します)' : '(用意できたら、もう一度押してください)'));
  if (done){
    const packs = t.filter(j => j.archive && j.archive.state === 'done' && j.archive.packOld).length;   // 前に作ったパックは速報版のまま(ホームの archive.packOld)
    parts.push(`本番版に入れ替えました ${done}/${total} 本` + (packs ? `(${packs} 本は前に作ったパックが速報版のままです。「編集」の 3 パック のタブで作り直してください)` : ''));
  }
  if (errs.length){ parts.push(`${errs.length} 本は作り直せませんでした: ${errs[0]}`); r.warn = true; }
  r.text = parts.join('。');
  r.can = !!o.known && pending > 0 && !o.starting;
  r.why = !o.known ? '書き出しの一覧を確かめています…' : !total ? '書き出したマークがありません(書き出したマークを、アーカイブから作り直します)'
    : !pending ? 'すべて本番版に入れ替えました' : o.starting ? '頼んでいます…' : '';
  return r;
}
/* 配信後の全自動(M7)の帯の 1 行: 入口の GET ../live/api/exports の archiveInfo.afterStream(入口 0.41.0)の text をそのまま出す。
   → {text, warn(失敗がある), running(まだ進む = 一覧を早めに読み直す。済んだあとも、まとめて実行へ渡した分の文字起こし → パックが残っている間)} */
function liveAfterView(info){
  const a = info && typeof info === 'object' && info.afterStream && typeof info.afterStream === 'object' ? info.afterStream : null;
  if (!a) return { text: '', warn: false, running: false };
  const state = String(a.state || ''), p = a.progress && typeof a.progress === 'object' ? a.progress : {};
  const failed = Number(p.failed) || 0, left = (Number(p.handed) || 0) - (Number(p.finished) || 0) - failed;
  return { text: typeof a.text === 'string' ? a.text : '', warn: state === 'error' || failed > 0,
    running: !!state && (!AFTER_END.includes(state) || (state === 'done' && left > 0)) };
}
/* 済んだジョブのうち、スタジオのマークにまだ付けていないもの。時刻(studio.start/end)が今のマークと同じものだけ
   (位置を直したマークは採用に戻っているので、もう一度書き出すまで書き出し済みにしない)。マークごとに新しいジョブ1つ
   → [{markId, path, jobId, archived, key}]。採用(か候補)のマーク = 「書き出し済み」に。本番版に入れ替えたジョブ(archive.state done)なら archived も付ける。
   もう書き出し済みのマークは、本番版に入れ替わってまだ archived でないときだけ(札「本番版」を付ける)。key = applied に入れる印(本番版は別の印 = 速報版で付けたあとでも送る) */
function liveReconcile(marks, jobs, applied){
  const by = new Map((marks || []).map(m => [m.id, m])), best = new Map();
  const same = (a, b) => Math.abs((Number(a) || 0) - (Number(b) || 0)) < 0.05;
  for (const j of jobs || []){
    if (!j || j.state !== 'done' || !j.path || !j.studio) continue;
    const archived = !!(j.archive && j.archive.state === 'done'), key = archived ? j.id + '#archive' : j.id;
    if (applied && applied.has(key)) continue;
    const m = by.get(j.studio.mark);
    if (!m || !same(m.start, j.studio.start) || !same(m.end, j.studio.end)) continue;
    const st = m.status || '';
    if (!(st === '' || st === 'adopted' || (st === 'exported' && archived && !m.archived))) continue;
    const prev = best.get(m.id), at = String(j.updated || j.created || '');
    if (!prev || at > prev.at) best.set(m.id, { markId: m.id, path: j.path, jobId: j.id, archived, key, at });
  }
  return [...best.values()].map(({ markId, path, jobId, archived, key }) => ({ markId, path, jobId, archived, key }));
}

/* 配信を開いたとき(loadVideo)。ライブの録画なら状態の見回りを始める。ほかの配信なら、ライブの帯・書き出しの行を片付ける */
function liveOpened(v){
  clearTimeout(LV.timer); LV.timer = 0; LV.seq++; LV.jobsSeq++;
  Object.assign(LV, { vid: v && v.kind === 'live' ? v.id : null, status: null, err: null, waitPlay: false, wasActive: null, endedShown: false,
    jobs: [], jobsKnown: false, jobsAt: 0, prevJobs: new Map(), busy: new Set(), queued: new Set(), applied: new Set(),
    archiveInfo: null, archStarting: false, archCancelling: false, archMsg: '', deletedShown: false });
  const rec = !!LV.vid;
  $('#rvArch').hidden = true;
  renderLiveAfter();   // 前に開いていた録画の「配信後の自動の切り抜き」を残さない(archiveInfo は空にした)
  $('#rvLiveRec').hidden = !rec; $('#rvLiveGuide').hidden = true;
  $('#rvLiveBar').classList.toggle('is-rec', rec); $('#rvLiveBar').classList.remove('is-ended');
  liveSet('#rvLiveBadge', 'LIVE'); liveSet('#rvLiveElapsedK', rec ? '録画の長さ' : '配信経過');
  for (const el of document.querySelectorAll('#rvLiveBar .rv-live-edgeinfo')) el.hidden = false;
  $('#rvEdge').hidden = false;
  const ol = $('#rvExpList'), want = rec ? 'live:' + v.id : '';
  if (ol && String(ol.dataset.job || '').startsWith('live:') && ol.dataset.job !== want){   // 前に開いていた録画の書き出しの行を残さない
    ol.innerHTML = ''; ol.dataset.job = ''; S.jobRows = [];
    if (!rec && S.lastJob) renderJobRows(S.lastJob);
  } else if (rec && ol && ol.dataset.job !== want){ ol.innerHTML = ''; ol.dataset.job = want; S.jobRows = []; }
  if (!rec) return;
  $('#rvAutoExp').checked = !!S.settings.liveAutoExport;
  $('#rvAfter').value = S.settings.liveAfter;
  $('#rvLiveBar').hidden = false;
  liveWhoOpened(v);
  loadLiveAutoArchive(v);
  renderLiveRec();
  pollLiveStatus();
}
/* ホームの設定の live.autoArchive(帯の案内の「自動: オン/オフ」用。既定オン)。設定の引き出しで変えたら studio:liveprefs で届く */
function loadLiveAutoArchive(v){
  if (!(window.UIKit && UIKit.prefs && UIKit.prefs.available())) return;
  UIKit.prefs.get(['live']).then(p => {
    if (LV.vid !== v.id) return;
    LV.autoArchive = !(p && p.live && p.live.autoArchive === false);
    LV.autoDelete = !!(p && p.live && p.live.autoDelete === true);   // 録画を自動で消す(入口と同じく true のときだけ)
    renderLiveRec();
  }, () => {});
}
function liveStopPoll(){ clearTimeout(LV.timer); LV.timer = 0; LV.seq++; }
function liveResume(){ if (S.cur && S.cur.kind === 'live' && LV.vid === S.cur.id && !LV.timer && visible()) pollLiveStatus(); }
async function pollLiveStatus(){
  clearTimeout(LV.timer); LV.timer = 0;
  const v = S.cur; if (!v || v.kind !== 'live' || LV.vid !== v.id || !v.live || !Studio.token) return;
  const seq = ++LV.seq;
  let st = null, err = null;
  try { st = await Studio.live.api(liveRest(v, 'status?since=999999999')); } catch (e){ err = e; }   // since: セグメントの一覧(最大 5000 件)は要らない(入口の _rec_status と同じ)
  if (seq !== LV.seq || S.cur !== v) return;
  if (err && err.status === 404 && !LV.deletedShown){   // 録画が無い: 自動で消した録画か(ジョブの recordingDeleted)を先に読み直す(「見つかりません」を一瞬出さない)
    await pollLiveJobs();
    if (seq !== LV.seq || S.cur !== v) return;
  }
  applyLiveStatus(v, st, err);
  if (LV.deletedShown){   // 消した録画: 状態はもう変わらない(1 分ごとに確かめるだけ)
    if (visible()) LV.timer = setTimeout(pollLiveStatus, 60000);
    return;
  }
  const busy = () => LV.queued.size > 0 || LV.jobs.some(x => LIVE_ACTIVE.includes(x.state));
  const arch = () => LV.jobs.some(liveArchRunning);
  /* 終わった録画は、書き出しが無くても 1 分ごとに一覧を読み直す(入口が自動で本番版への作り直しを始めた・待ちから進んだのに気づくため) */
  const stale = () => !!st && !st.active && Date.now() - LV.jobsAt > 60000;
  const after = () => liveAfterView(LV.archiveInfo).running && Date.now() - LV.jobsAt > 15000;   // 配信後の自動の切り抜き(M7)が進んでいる間は、帯の 1 行を 15 秒ごとに
  if (!LV.jobsKnown || busy() || arch() || (LV.jobs.some(liveArchBusy) && Date.now() - LV.jobsAt > 15000) || stale() || after()) await pollLiveJobs();
  if (seq !== LV.seq || S.cur !== v || !visible()) return;
  LV.timer = setTimeout(pollLiveStatus, !err && st && !st.active && !busy() ? (arch() ? 5000 : 10000) : 3000);   // 終わった録画で書き出しも無ければゆっくり(本番版の作り直しの間は 5 秒)
}
function applyLiveStatus(v, st, err){
  if (err){
    LV.err = err;
    if (liveRecDeleted(err, LV.jobs, v.marks)) liveDeletedShown(v);
    renderLiveRec(); return;
  }
  LV.deletedShown = false;
  LV.err = null; LV.status = st && typeof st === 'object' ? st : {};
  const active = !!LV.status.active;
  if (LV.status.title && !v.title) setAutoTitle(v, LV.status.title);   // 題は録画の題を取り込む(配信名が分かったとき。自分で付けた名前は上書きしない)
  if (LV.wasActive === true && !active) liveEndedNotice();
  LV.wasActive = active;
  if (yt && yt instanceof LivePlayer) yt.recording = active;
  if (!yt && LV.waitPlay){
    if (Number(LV.status.segments) > 0) mountPlayer();   // 配信が始まった(録れ始めた): プレーヤーを作って自動で再生
    else phMsg('配信が始まるのを待っています。始まると自動で再生します');
  }
  if (!S.playerAlive){ const t = liveTotal(LV.status); if (t > 0 && Math.abs(t - S.duration) >= 1) setDuration(t); }   // 再生できない画面でも、タイムラインと時刻の入力は録画の長さで
  updateLive();
}
/* 自動で消した録画を開いた(か、開いている間に消えた): プレーヤーの所に案内を出す(エラーではない・「もう一度試す」は出さない)。1回だけ */
function liveDeletedShown(v){
  if (LV.deletedShown) return;
  LV.deletedShown = true; LV.waitPlay = false;
  if (yt) unmountPlayer();   // 開いている間に消えた: 読めなくなった再生リストを読み続けない
  S.playerErr = true;
  const n = $('#rvNotice'), href = liveYtHref(v);
  n.innerHTML = `<b>${esc(LIVE_DELETED)}</b><br><span class="hint">録画が無いので、この画面では再生できません。本番版の切り抜きは書き出し先にあります(文字起こし・カット・パックもそのまま使えます)。</span>${href ? ` <a class="btn small" href="${esc(href)}" target="_blank" rel="noopener noreferrer" data-yt-now>YouTube で開く</a>` : ''}`;
  n.hidden = false; phMsg('');
}
/* 録画が終わった(録画中 → 終わり)ときの知らせ(1回)。ヘッダーの札(UIKit.liveBadge)が動いているなら、札が同じ知らせを出すので重ねない */
function liveEndedNotice(){
  if (LV.endedShown) return;
  LV.endedShown = true;
  const lb = window.UIKit && UIKit.liveBadge && UIKit.liveBadge.get ? UIKit.liveBadge.get() : null;
  if (!(lb && lb.enabled)) toast(`録画が終わりました(合計 ${tickLabel(liveTotal(LV.status))})。最後まで再生・マーク・書き出しができます`, 8000, 'ok');
  renderExportUI();
}
/* LIVE の帯の録画の部分(状態の札・案内・停止)。文字と属性だけを直す */
function renderLiveRec(){
  const v = S.cur; if (!v || v.kind !== 'live') return;
  const st = LV.status, err = LV.err, active = !!(st && st.active), waiting = active && !(Number(st.segments) > 0);
  const gone = !!err && LV.deletedShown;   // 自動で消した録画(P4)。エラーにしない
  let cls = 'wait', label = '確かめています…', msg = '';
  if (gone){ cls = 'ok'; label = '録画を消しました'; }
  else if (err){ cls = 'err'; label = err.status === 404 ? '録画が見つかりません' : '録画元につながりません'; msg = err.message || ''; }
  else if (st){
    const m = LIVE_REC_STATE[st.state] || ['wait', String(st.state || '不明')]; cls = m[0]; label = m[1];
    msg = [Number(st.sessions) > 1 ? `つなぎ直し ${Number(st.sessions) - 1} 回` : '', st.state === 'stopped' ? '' : String(st.message || '')].filter(Boolean).join('・');   // 「停止」の札に「停止しました」は重ねない
  }
  const pill = $('#rvRecState'), pc = 'pill ' + cls;
  if (pill.className !== pc) pill.className = pc;
  liveSet('#rvRecState', label); liveSet('#rvRecMsg', msg);
  $('#rvRecStop').hidden = !active;
  for (const sel of ['label[for="rvAutoExp"]', 'label[for="rvDuck"]', 'label[for="rvAfter"]']){ const el = document.querySelector(sel); if (el && el.hidden !== gone) el.hidden = gone; }   // 録画が無い: すぐ書き出す・音の扱い・書き出したあとは意味が無い
  { const w = $('#rvLiveWho'), can = !gone && !!(Studio.token && window.UIKit && UIKit.streamer && UIKit.streamer.autoFill); if (w && w.hidden !== !can) w.hidden = !can; }
  const ended = (!!st && !err && !active) || gone;
  $('#rvLiveBar').classList.toggle('is-ended', ended);
  liveSet('#rvLiveBadge', ended ? '録画' : 'LIVE');
  for (const el of document.querySelectorAll('#rvLiveBar .rv-live-edgeinfo')) el.hidden = !active;
  $('#rvEdge').hidden = !active;
  if (!active && st) liveSet('#rvLiveElapsed', tickLabel(Math.max(liveTotal(st), S.duration)));
  else if (active && !S.playerAlive) liveSet('#rvLiveElapsed', fmt(S.duration));   // 再生できない間は録画の状態の長さ(再生中は updateLive が直す)
  let guide = '';
  if (gone) guide = LIVE_DELETED;
  else if (err || !st) guide = '';
  else if (waiting) guide = '配信が始まるのを待っています。始まると自動で再生します(録画の部品は、配信が始まるまで待ち続けます)';
  else if (active) guide = '見ながら ①〜⑤ か I・O でマークします。' + (liveAutoExportOn(v) ? 'マークは自動で書き出されます(録画が届くのを待ってから作ります)' : '採用にしたマークを「書き出す」で書き出します(録画中でも書き出せます)');
  else {
    guide = `録画は終わりました(合計 ${tickLabel(Math.max(liveTotal(st), S.duration))})。最後まで再生・マーク・書き出しができます`;
    if (liveVideoId(v) && liveArchTargets(LV.jobs).some(j => !(j.archive && j.archive.state === 'done'))){   // まだ本番版でないマークがあるときだけ
      guide += `。アーカイブが用意できたら、本番の画質に作り直せます(自動: ${LV.autoArchive === false ? 'オフ' : 'オン'})`;
      if (LV.autoDelete === true) guide += '。本番版に入れ替えたら、録画は消します';   // 録画を自動で消す(P4。設定 live.autoDelete)。驚かないように先に知らせる
    } else if (LV.autoDelete === true && LV.jobsKnown && !LV.jobs.length && !(v.marks || []).length) guide += '。マークが無いまま 1 日たつと、録画は消します';
  }
  liveSet('#rvLiveGuide', guide); $('#rvLiveGuide').hidden = !guide;
  renderLiveArch();
}
/* 終わった録画の帯の「アーカイブで作り直す」(P4)。録画中・状態が分からない間は出さない。文字と属性だけを直す */
function renderLiveArch(){
  const v = S.cur, box = $('#rvArch'); if (!box) return;
  const st = LV.status, ended = !!(v && v.kind === 'live' && LV.vid === v.id && st && !LV.err && !st.active);
  if (box.hidden !== !ended) box.hidden = !ended;
  if (!ended) return;
  const vid = liveVideoId(v);
  const sm = liveArchSummary(LV.jobs, LV.archiveInfo, { videoId: vid, known: LV.jobsKnown, starting: LV.archStarting, msg: LV.archMsg, autoOn: LV.autoArchive !== false });
  const run = $('#rvArchRun'), cancel = $('#rvArchCancel'), msg = $('#rvArchMsg');
  run.hidden = !vid;
  run.disabled = !sm.can;
  const title = sm.can ? '書き出した切り抜きを、アーカイブ(本番の画質)から作り直して、同じ名前のまま入れ替えます(速報版は作業用のフォルダへ移します)' : sm.why;
  if (run.title !== title) run.title = title;
  cancel.hidden = !sm.running || !vid; cancel.disabled = LV.archCancelling;
  liveSet('#rvArchMsg', sm.text);
  msg.classList.toggle('rv-warnline', sm.warn);
  const info = LV.archiveInfo, it = info && info.message ? String(info.message) : '';
  if (msg.title !== it) msg.title = it;
}
/* 帯の「配信後の自動の切り抜き」の 1 行(M7)。開いている録画の分だけ(録画を消したあとも最後の文を残す)。文字と属性だけを直す */
function renderLiveAfter(){
  const el = $('#rvAfterStream'); if (!el) return;
  const v = S.cur, av = liveAfterView(v && v.kind === 'live' && LV.vid === v.id ? LV.archiveInfo : null);
  if (el.hidden !== !av.text) el.hidden = !av.text;
  liveSet('#rvAfterStream', av.text);
  el.classList.toggle('rv-warnline', av.warn);
}
async function startLiveArchive(){
  const v = S.cur; if (!v || v.kind !== 'live' || !v.live || LV.archStarting) return;
  LV.archStarting = true; LV.archMsg = ''; renderLiveArch();
  try {
    const r = await Studio.live.api('api/archive', { body: { recorder: v.live.recorder, recording: v.live.recording } });
    if (S.cur !== v) return;
    if (r && r.ok === false){ LV.archMsg = String(r.message || 'アーカイブで作り直せませんでした'); toast(LV.archMsg, 6000); }
    else toast(r && r.message ? String(r.message) : `${Number(r && r.queued) || 0} 本を本番版に作り直します(アーカイブから取り直して、速報版と入れ替えます)`, 4000, 'ok');
  } catch (e){
    if (S.cur !== v) return;
    LV.archMsg = e.status === 409 ? e.message : 'アーカイブで作り直せませんでした: ' + e.message;   // 409 = 対象が無い・アーカイブがまだ用意できていない(入口の文をそのまま)
    toast(LV.archMsg, e.status === 409 ? 6000 : 0, e.status === 409 ? '' : 'err');
  } finally {
    if (S.cur === v){ LV.archStarting = false; await pollLiveJobs(); renderLiveArch(); liveResume(); }
  }
}
async function cancelLiveArchive(){
  const v = S.cur; if (!v || v.kind !== 'live' || !v.live || LV.archCancelling) return;
  LV.archCancelling = true; renderLiveArch();
  try { await Studio.live.api('api/archive/cancel', { body: { recorder: v.live.recorder, recording: v.live.recording } }); toast('本番版への作り直しを取り消しました(済んでいない分は速報版のままです)', 4000); }
  catch (e){ toast('取り消せませんでした: ' + e.message, 0, 'err'); }
  finally { LV.archCancelling = false; if (S.cur === v){ await pollLiveJobs(); renderLiveArch(); } }
}
async function stopLiveRec(btn){
  const v = S.cur; if (!v || v.kind !== 'live' || !v.live) return;
  UIKit.confirmTwice(btn, async () => {
    btn.disabled = true;
    try {
      await Studio.live.api(liveRest(v, 'stop'), { body: {} });
      if (window.UIKit && UIKit.liveBadge && UIKit.liveBadge.refresh) UIKit.liveBadge.refresh();   // ヘッダーの札もすぐ合わせる
    } catch (e){ toast('録画を止められませんでした: ' + e.message, 0, 'err'); }
    finally { btn.disabled = false; if (S.cur === v) pollLiveStatus(); }
  }, 'もう一度押すと録画を止めます');
}

/* 入口の書き出しの一覧(この録画の分)を読み、欄を差分で直し、済んだ分をスタジオの「書き出し済み」にする */
async function pollLiveJobs(){
  const v = S.cur; if (!v || v.kind !== 'live' || !v.live || !Studio.token) return;
  const seq = ++LV.jobsSeq;
  LV.jobsAt = Date.now();
  let j; try { j = await Studio.live.api('api/exports?recorder=' + enc(v.live.recorder) + '&recording=' + enc(v.live.recording)); } catch { return; }
  if (seq !== LV.jobsSeq || S.cur !== v) return;
  const all = Array.isArray(j && j.exports) ? j.exports : Array.isArray(j && j.jobs) ? j.jobs : [];
  const own = all.filter(x => x && x.studio && x.studio.video === v.id);
  if (LV.jobsKnown) liveJobNotices(own);
  const archWas = LV.jobsKnown && LV.jobs.some(liveArchBusy);
  LV.prevJobs = new Map(own.map(x => [x.id, x.state]));
  LV.jobs = own; LV.jobsKnown = true;
  LV.archiveInfo = j && j.archiveInfo && typeof j.archiveInfo === 'object' ? j.archiveInfo : null;
  renderLiveAfter();
  if (own.some(liveArchBusy)) LV.archMsg = '';   // 始まった: 前に断られた文は消す
  else if (archWas){   // 本番版への作り直しが終わった(この画面を開いている間に): 帯と同じ文を1回知らせる
    const sm = liveArchSummary(own, LV.archiveInfo, { videoId: liveVideoId(v), known: true, autoOn: LV.autoArchive !== false });
    if (sm.text) toast(sm.text, sm.warn ? 0 : 5000, sm.warn ? 'err' : 'ok');
  }
  LV.busy = new Set([...own.filter(x => LIVE_ACTIVE.includes(x.state)).map(x => x.studio.mark), ...LV.queued]);
  renderLiveJobs();
  await liveApplyDone(v);
}
function liveJobNotices(own){
  for (const x of own){
    const p = LV.prevJobs.get(x.id); if (!p || !LIVE_ACTIVE.includes(p) || p === x.state) continue;
    const name = x.label ? `「${x.label}」` : `${fmt(Number(x.studio.start) || 0)} – ${fmt(Number(x.studio.end) || 0)}`;
    if (x.state === 'done') doneToast(`切り抜きを書き出しました(${name})`, 'ok', [typeof x.path === 'string' ? x.path : '']);   // [編集で開く](S-7)
    else if (x.state === 'error') toast(`書き出せませんでした(${name}): ${x.error || x.message || ''}`, 0, 'err');
  }
}
function renderLiveJobs(){
  const v = S.cur; if (!v || v.kind !== 'live') return;
  renderJobRows(liveJobView(v.id, LV.jobs));
  renderExportUI();
  renderLiveRec();   // 帯の案内と「アーカイブで作り直す」(ジョブから決まる)
}
/* 入口の書き出しが済んだマークを「書き出し済み」に(本番版に入れ替わったものは archived: true も = 札「本番版」)。閉じていた間に済んだ分も、開いたときにここで付く */
async function liveApplyDone(v){
  const todo = liveReconcile(v.marks, LV.jobs, LV.applied);
  if (!todo.length) return;
  let n = 0;
  for (const t of todo){
    LV.applied.add(t.key);   // 失敗しても見回りのたびには送らない(知らせて、次にこの録画を開いたときにやり直す)
    const body = { id: v.id, markId: t.markId, path: t.path };
    if (t.archived) body.archived = true;
    try { await Studio.api('/api/live/exported', { body }); n++; }
    catch (e){ toast((t.archived ? '本番版に入れ替えたマークに札を付けられませんでした: ' : '書き出したマークを「書き出し済み」にできませんでした: ') + e.message, 7000, 'err'); }
    if (S.cur !== v) return;
  }
  if (n && S.cur === v) await syncFromServer();
}
/* 帯の「配信者」(字幕の色。docs/spec/friend-intake.md の「配信者の名前 → 見た目」の流れに乗せる = 名前だけを入口へ渡す)。
   名前は今のアーカイブの配信と同じ仕組み(UIKit.streamer.autoFill = 覚えた名前(この録画 → チャンネル)→ チャンネル名から)。直したら UIKit が覚える。
   LV.who = {vid, name, match(色の一覧で1人に決まったか)}。開いている録画の分だけ使う */
function liveWhoName(v){ return LV.who && v && LV.who.vid === v.id ? String(LV.who.name || '').trim().slice(0, 60) : ''; }
function liveWhoLabel(who){
  const name = who && String(who.name || '').trim();
  if (!name) return '配信者: 未設定(字幕は既定の色)';
  return '配信者: ' + name + (who.match === false ? '(色の一覧に無いので既定の色)' : '');
}
function renderLiveWho(){ liveSet('#rvLiveWhoText', liveWhoLabel(LV.who)); }
/* 録画を開いたとき: 欄を自動で埋める(手で直したあとは同じ録画では入れ直さない = UIKit.streamer の約束) */
function liveWhoOpened(v){
  const box = $('#rvLiveWho'), inp = $('#rvLiveWhoIn'); if (!box || !inp) return;
  const can = !!(Studio.token && window.UIKit && UIKit.streamer && UIKit.streamer.autoFill);
  box.hidden = !can; if (box.open) box.open = false;
  LV.who = { vid: v.id, name: '', match: null };
  renderLiveWho();
  if (!can) return;
  if (!inp.__liveWhoBound){
    inp.__liveWhoBound = true;
    const sync = match => { const cur = S.cur; if (!cur || cur.kind !== 'live' || !LV.who || LV.who.vid !== cur.id) return;
      LV.who.name = inp.value.trim(); if (match !== undefined) LV.who.match = match; renderLiveWho(); };
    inp.addEventListener('ui-streamer', e => sync(e.detail ? true : (inp.value.trim() ? false : null)));   // 色の一覧で照らし合わせた結果(UIKit.streamer)
    inp.addEventListener('input', () => sync(undefined));
    inp.addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); inp.blur(); box.open = false; } });   // Enter で決めて閉じる(change で覚える)
  }
  UIKit.streamer.autoFill(inp, { videoId: v.id, channel: v.channel || '' }).then(() => {
    if (S.cur === v && LV.who && LV.who.vid === v.id){ LV.who.name = inp.value.trim(); renderLiveWho(); }
  }, () => {});
}
function liveExportBody(v, m){
  const n = sortedMarks().findIndex(x => x.id === m.id) + 1;
  const after = LIVE_AFTERS.includes(S.settings.liveAfter) ? S.settings.liveAfter : 'check';
  return { recorder: v.live.recorder, recording: v.live.recording, title: v.title || '', url: v.live.url || '',
    after, transcribe: after !== 'none',   // 帯の「書き出したあと」(入口の書き出しがまとめて実行へ渡す。スタジオからは頼まない = 二重にしない)。transcribe は以前の入口の形
    streamer: liveWhoName(v),   // 配信者の名前(字幕の色)。帯の「配信者」= 覚えた名前かチャンネル名から。空 = まとめて実行が決める(たいてい既定の色)
    studio: { video: v.id, mark: m.id, n, label: m.label || '', start: m.start, end: m.end } };
}
/* ライブの録画の書き出し(入口の api/export)。onlyIds が無ければ書き出しの対象(exportTargets)。1件ずつ頼む(順番に並べて、続けて押しても落とさない)。
   opts.auto: 「マークしたらすぐ書き出す」から(うまくいったときは知らせない。マークの知らせが出ているため) */
function startLiveExport(onlyIds, opts){
  opts = opts || {};
  const v = S.cur; if (!v || v.kind !== 'live' || !v.live) return Promise.resolve();
  if (!Studio.token){ toast('ライブの録画の書き出しは、ホーム(start.bat)から開いたときだけ使えます', 0, 'err'); return Promise.resolve(); }
  const targets = (onlyIds ? sortedMarks().filter(c => onlyIds.has(c.id)) : exportTargets()).filter(m => !LV.busy.has(m.id));
  if (!targets.length){ if (!opts.auto) toast('書き出すマークがありません(「採用」にしたマークが書き出されます。書き出しの途中のマークは除きます)'); return Promise.resolve(); }
  for (const m of targets){ LV.queued.add(m.id); LV.busy.add(m.id); }
  if (!opts.auto) LV.starting = true;
  renderExportUI();
  const run = async () => {
    let ok = 0; const errs = [], failed = [];
    try {
      await flushSave();   // スタジオのマークを先に保存する(済んだら /api/live/exported でこのマークを書き出し済みにするため)
      for (const m of targets){
        if (S.cur !== v) break;
        const cur = v.marks.find(x => x.id === m.id); if (!cur) continue;   // 頼む前に消された
        try { await Studio.live.api('api/export', { body: liveExportBody(v, cur) }); ok++; }
        catch (e){ errs.push(e.message); failed.push(m.id); }
      }
    } catch (e){ errs.push(e.message); for (const m of targets) failed.push(m.id); }   // 保存できなかった: どれも頼んでいない
    finally {
      for (const m of targets){ LV.queued.delete(m.id); }
      if (!opts.auto) LV.starting = false;
    }
    if (S.cur !== v) return;
    for (const id of failed) LV.busy.delete(id);   // 頼めなかったマークは、すぐ「書き出す」でやり直せるように
    if (errs.length) toast('書き出しを頼めませんでした: ' + errs[0], 0, 'err');
    else if (ok && !opts.auto) toast(`${ok}件の書き出しを頼みました(録画が届くのを待ってから作ります)`, 4000, 'ok');
    await pollLiveJobs();
    renderExportUI();
    liveResume();
  };
  LV.chain = LV.chain.then(run, run);
  return LV.chain;
}
/* ヘッダーの札の「開く」(UIKit.liveBadge.onOpen): ページを移らずに、その録画をスタジオの ③ で開く(まだ登録していなければ登録する) */
async function openLiveRecording(rec){
  if (!rec || !rec.id) return;
  const hit = () => S.videos.find(x => x.kind === 'live' && liveRecId(x) === rec.id && (!rec.recorder || !x.live || x.live.recorder === rec.recorder));
  let v = hit();
  if (!v){ await refreshList(); v = hit(); }
  let id = v && v.id;
  if (!id){
    try { id = (await Studio.live.register(rec.recorder, rec)).video.id; }   // 登録は1か所(core.js)
    catch (e){ toast('録画を開けませんでした: ' + e.message, 0, 'err'); return; }
  }
  if (S.cur && S.cur.id === id){ Studio.go('review'); return; }
  Studio.review.open(id);
}

/* ---------- マーク操作 ---------- */
function newMark(start, end, live){
  return { id: uid(), start, end, label: '', src: 'manual', score: null, reasons: [], parts: {}, peak: null, live: !!live, status: '', file: '', createdAt: Date.now() };
}
function pushMark(m){
  const v = S.cur;
  const autoExp = liveAutoExportOn(v);   // ライブの録画で「マークしたらすぐ書き出す」: 採用にして保存し、すぐ入口の書き出しへ(線 D の P3)
  if (autoExp) m.status = 'adopted';
  v.marks.push(m); S.seen.add(m.id); S.sel = m.id; S.fold.set(m.id, false);
  markDirty(); renderTimeline(); renderStats(); renderLiveCount();
  if (!inList()) renderList();
  const li = document.querySelector(`.rv-mark-row[data-id="${CSS.escape(m.id)}"]`); if (li) li.scrollIntoView({ block: 'nearest' });
  if (autoExp) startLiveExport(new Set([m.id]), { auto: true });
}
/* サーバーと同じ規則: 0 ≤ start < end、長さ ≤ 60分、有限の数。通常動画では終了を動画の長さに収める。返り値は [start, end] か、エラー文の文字列 */
function checkRange(start, end){
  start = round1(Number(start)); end = round1(Number(end));
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '時刻の形式が正しくありません';
  if (start < 0) start = 0;
  if (!S.live && S.duration > 0 && end > round1(S.duration)) end = round1(S.duration);
  if (end <= start + 0.1) return '終了は開始より後にしてください(配信の長さの範囲内で)';
  if (end - start > MAX_MARK_SEC) return '1本の長さは60分までです';
  return [start, end];
}
function quickMark(slot = 0){
  if (!S.cur) return toast('先に配信を開いてください');
  if (marks().length >= MAX_MARKS) return toast(`1本の配信に登録できるのは${MAX_MARKS}件までです`);
  const center = Math.max(0, S.now - S.settings.lag);
  const span = S.settings.quickSpans[slot] || 30;
  const r = checkRange(center - span, center + span);
  if (typeof r === 'string') return toast(r);
  const [start, end] = r;
  pushMark(newMark(start, end, markLive()));
  toast(`マーク ${fmt(start)} – ${fmt(end)}(前後${spanLabel(span)})`);
}
/* ---------- 一瞬を切り取る(2026-09-28 ユーザー要望): 今の位置の前 2 秒・後 3 秒から始め、始まり・終わりを 0.1 秒刻みで合わせて、
   マーク「一瞬」(採用)を作り、そのマークだけを書き出す。マークとして残すのは、書き出しのあとの自動の文字起こし・「この後を」・
   入口の案件がマークを手がかりに動くため(ユーザー決定)。書き出しの設定(方式・画質・音量)は「書き出しの設定」のとおり ---------- */
const MOMENT_LABEL = '一瞬';
function momentMark(){
  if (!S.cur) return toast('先に配信を開いてください');
  if (marks().length >= MAX_MARKS) return toast(`1本の配信に登録できるのは${MAX_MARKS}件までです`);
  const c = Math.max(0, S.now - (Number(S.settings.lag) || 0));   // 今をマークと同じく、遅れ(lag)を引いた位置
  const b = S.settings.momentBefore, a = S.settings.momentAfter;
  const r = checkRange(c - b, c + a);
  if (typeof r === 'string') return toast(r);
  const mk = newMark(r[0], r[1], markLive());   // ライブ中のマークには、今をマークと同じくライブの印
  mk.label = MOMENT_LABEL; mk.status = 'adopted';
  pushMark(mk);
  toast(`マーク「${MOMENT_LABEL}」${fmt(r[0])} – ${fmt(r[1])}(前${b.toFixed(1)}秒・後${a.toFixed(1)}秒)`, 3000, 'ok');
}
function renderMomentSet(){
  const f = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v.toFixed(1); };
  f('#rvMomBefore', S.settings.momentBefore); f('#rvMomAfter', S.settings.momentAfter);
}
function setMomentSec(key, el){
  const v = Number(el.value);
  if (!Number.isFinite(v)) return renderMomentSet();
  S.settings[key] = Math.min(60, Math.max(0, Math.round(v * 10) / 10));
  if (S.settings.momentBefore + S.settings.momentAfter < 0.2) S.settings[key] = Math.round((0.2 - (key === 'momentBefore' ? S.settings.momentAfter : S.settings.momentBefore)) * 10) / 10;
  touchSettings(); el.value = S.settings[key].toFixed(1);
}
function markIn(){
  if (!S.cur) return toast('先に配信を開いてください');
  const lag = Number($('#rvLag').value) || 0;
  S.draft.start = round1(Math.max(0, S.now - lag));
  if (S.draft.end != null && S.draft.end <= S.draft.start) S.draft.end = null;
  renderDraft();
}
function markOut(){
  if (!S.cur) return toast('先に配信を開いてください');
  const t = round1(S.now);
  if (S.draft.start != null && t <= S.draft.start) return toast('終了は開始より後の位置でマークしてください');
  S.draft.end = t; renderDraft();
}
function addClip(){
  if (!S.cur) return toast('先に配信を開いてください');
  const { start, end } = S.draft;
  if (start == null || end == null) return toast('IN と OUT の両方をマークしてください');
  if (marks().length >= MAX_MARKS) return toast(`1本の配信に登録できるのは${MAX_MARKS}件までです`);
  const r = checkRange(start, end);
  if (typeof r === 'string') return toast(r);
  const m = newMark(r[0], r[1], markLive());
  S.draft = { start: null, end: null }; renderDraft();
  pushMark(m);
  const el = document.querySelector(`.rv-mark-row[data-id="${CSS.escape(m.id)}"] [data-f="label"]`); if (el) el.focus();
}
function setBound(c, w, val){
  val = round1(val);
  if (!Number.isFinite(val) || val < 0){ toast('時刻の形式が正しくありません(例: 1:23.5)'); return false; }
  if (w === 'end' && !S.live && S.duration > 0 && val > round1(S.duration)) val = round1(S.duration); // 動画の長さに収める
  if (w === 'start' && val >= c.end - 0.1){ toast('開始は終了より前にしてください'); return false; }
  if (w === 'end' && val <= c.start + 0.1){ toast('終了は開始より後にしてください'); return false; }
  if (!S.live && S.duration && val > S.duration + 1){ toast('配信の長さを超えています'); return false; }
  const s0 = w === 'start' ? val : c.start, e0 = w === 'end' ? val : c.end;
  if (e0 - s0 > MAX_MARK_SEC){ toast('1本の長さは60分までです'); return false; }
  if (c[w] === val) return true;
  c[w] = val; if (c.status === 'exported'){ c.status = 'adopted'; c.file = ''; c.path = ''; c.archived = false; } // 範囲を変えたら再書き出しできる状態(採用)に戻る(サーバーも同じ)
  markDirty(); return true;
}
function refresh(keyToFocus){
  renderTimeline(); renderStats(); renderList(); renderLiveCount();
  if (keyToFocus){ const el = document.querySelector(`[data-key="${CSS.escape(keyToFocus)}"]`); if (el) el.focus(); }
}
/* 2回押しの確認(戻せない操作だけ)。部品は ui-kit の UIKit.confirmTwice の1つ(気が利く画面へ 段1。実行したらすぐ元に戻る) */
function armDelete(btn, run, text){ UIKit.confirmTwice(btn, run, text || 'もう一度押すと削除'); }
const statusOf = c => c.status || '';
const isFolded = id => (S.fold.has(id) ? S.fold.get(id) : S.settings.foldDefault);
/* 表示するマーク(絞り込み + 並び替え)。前後移動もこの順で動く */
const byScore = (a, b) => (b.score == null ? -1 : b.score) - (a.score == null ? -1 : a.score) || a.start - b.start || (a.id < b.id ? -1 : 1);
/* 並び順(時刻順 / 点数順)だけを適用した全マーク */
function orderedMarks(){ const l = sortedMarks(); return S.settings.sortBy === 'score' ? l.sort(byScore) : l; }
function listMarks(){
  let l = orderedMarks();
  if (S.filter !== 'all') l = l.filter(m => statusOf(m) === S.filter);
  return l;
}
function setStatus(c, st, advance){
  if (statusOf(c) === st) return false;
  c.status = st; if (st !== 'exported') c.file = ''; c.path = ''; c.archived = false;
  markDirty(); refresh(); renderMeta();
  if (advance && S.settings.autoNext && st !== '') goMark(1, true, c);
  return true;
}
function selectMark(c, jump){
  S.sel = c.id; S.fold.set(c.id, false);
  renderTimeline(); renderList();
  const li = document.querySelector(`.rv-mark-row[data-id="${CSS.escape(c.id)}"]`); if (li) li.scrollIntoView({ block: 'nearest' });
  if (jump){ if (S.settings.autoPlay) previewClip(c, true); else seek(c.start); }
}
/* 前/次のマークへ。一覧の並び順(時刻順 / 点数順)どおりに動く(以前は点数順で表示していても時刻順に飛んでいた)。
   onlyCand なら「候補」だけを渡り歩く(採用・不採用の直後に次の候補へ)。from は判定を変えたばかりのマーク(絞り込みで一覧から消えていても、その位置から数える) */
function goMark(dir, onlyCand, from){
  const all = orderedMarks(); if (!all.length) return toast('マークがありません');
  const cur = from || all.find(m => m.id === S.sel) || null;
  const ok = m => onlyCand ? statusOf(m) === '' : (S.filter === 'all' || statusOf(m) === S.filter);
  const idx = cur ? all.findIndex(m => m.id === cur.id) : -1;
  let next = null;
  if (idx < 0) next = dir > 0 ? all.find(ok) : [...all].reverse().find(ok);
  else if (dir > 0) next = all.slice(idx + 1).find(ok);
  else next = all.slice(0, idx).reverse().find(ok);
  if (!next) return toast(dir > 0 ? (onlyCand ? '候補はこれで最後です' : 'これ以上、後のマークはありません') : 'これ以上、前のマークはありません');
  selectMark(next, true);
}
function decideSel(st){
  const c = marks().find(m => m.id === S.sel);
  if (!c) return toast('先にマークを選んでください(行の再生ボタン・行のクリック・前後移動キー)');
  if (!setStatus(c, st, true)) return;
}
/* 候補をすべて採用: 戻せる操作なので確認はしない(気が利く画面へ 段1)。知らせの [元に戻す] で、まだ採用のままのマークだけ候補に戻す */
function bulkAdopt(){
  const cs = marks().filter(m => statusOf(m) === '');
  if (!cs.length) return toast('候補がありません');
  const v = S.cur;
  for (const m of cs) m.status = 'adopted';
  markDirty(); refresh(); renderMeta();
  UIKit.toast(`候補 ${cs.length}件を採用にしました`, { kind: 'ok', ms: 8000, action: { label: '元に戻す', fn: () => {
    if (S.cur !== v) return toast('別の配信を開いているので戻せません', 4000);
    let n = 0;
    for (const m of cs) if (m.status === 'adopted'){ m.status = ''; n++; }
    markDirty(); refresh(); renderMeta(); toast(`${n}件を候補に戻しました`);
  } } });
}
function foldAll(on){ S.settings.foldDefault = on; S.fold = new Map(); touchSettings(); renderList(); }

/* ---------- 動画名の自動設定 ---------- */
function setAutoTitle(v, title){
  title = String(title || '').trim().slice(0, 120);
  if (!v || S.cur !== v || v.title || !title) return;
  v.title = title; markDirty(); renderMeta(); renderVideoSelect();
}
async function fetchAutoTitle(v){
  if (!v || v.kind !== 'youtube' || v.title) return;
  try { const r = await Studio.api('/api/title?v=' + enc(v.id)); setAutoTitle(v, r.title); } catch {}
}
function autoTitleFromPlayer(){
  const v = S.cur; if (!v || v.title || v.kind !== 'youtube') return;
  try { setAutoTitle(v, yt.getVideoData().title); } catch {}
}

/* ---------- 書き出し(サーバーが store から組み立てる。クライアントは id とマークIDだけ送る)---------- */
let expTimer = null;
const EXP_LABEL = { queued: '待機中', running: '処理中', done: '完了', error: '失敗', cancelled: '中止' };
function errHint(msg){
  if (/空か短すぎ|取得|ストリーム|方法1/.test(msg || '')) return 'ライブ終了直後はアーカイブが未完成で失敗しやすくなります。数時間〜半日ほど置いてから「失敗した分だけやり直す」を試してください。';
  return '';
}
function rememberJob(o){ try { if (o) localStorage.setItem('clipstudio:rvjob', JSON.stringify(o)); else localStorage.removeItem('clipstudio:rvjob'); } catch {} }
function failedIds(){
  const v = S.cur, j = S.lastJob;
  if (!v || !j || !S.job || S.job.videoId !== v.id || S.job.running) return new Set();
  const ok = new Set(v.marks.filter(m => m.status !== 'exported').map(m => m.id));
  return new Set(j.items.filter(i => (i.status === 'error' || i.status === 'cancelled') && ok.has(i.id)).map(i => i.id));
}
function exportTargets(){
  const t = S.settings.exportTarget;
  const busy = S.cur && S.cur.kind === 'live' ? LV.busy : null;   // ライブの録画: 入口で書き出しの途中のマークは外す(二重に頼まない)
  return sortedMarks().filter(m => (t === 'adopted' ? m.status === 'adopted' : t === 'pending' ? (m.status === 'adopted' || !m.status) : m.status !== 'rejected') && !(busy && busy.has(m.id)));
}
/* ---------- 書き出したファイルのパス・他のツールへの受け渡し ---------- */
const isAbsPath = p => /^(?:[a-zA-Z]:[\\/]|\\\\|\/)/.test(p);
/* base(絶対パス)に rel("フォルダ/名前.mp4")をつなぐ。Windows のパス(C:\ や \ を含む)なら区切りを \ にそろえる */
function joinPath(base, rel){
  const win = /\\/.test(base) || /^[a-zA-Z]:/.test(base), sep = win ? '\\' : '/';
  return String(base).replace(/[\\/]+$/, '') + sep + String(rel).replace(/^[\\/]+/, '').split(/[\\/]+/).join(sep);
}
/* 書き出した mp4 の絶対パス。サーバーが各ファイルに絶対パス(path / mediaPath)を入れていればそれを使い、
   無ければジョブの outDir(書き出し開始時の出力先)と file(outDir からの相対)から組み立てる。どちらも無ければ ''(リンクを出さない) */
function clipPathOf(j, it){
  const direct = [it.path, it.mediaPath].find(x => typeof x === 'string' && isAbsPath(x));
  if (direct) return direct;
  if (typeof it.file !== 'string' || !it.file) return '';
  if (isAbsPath(it.file)) return it.file;
  return j && typeof j.outDir === 'string' && isAbsPath(j.outDir) ? joinPath(j.outDir, it.file) : '';
}
function handoffHTML(j, it){
  const path = it.status === 'done' ? clipPathOf(j, it) : '';
  if (!path) return '';
  const man = typeof it.manifest === 'string' && it.manifest ? it.manifest : '';
  if (window.UIKit && UIKit.appnav) UIKit.appnav.setLink('transcribe', '?media=' + enc(path));   // 「編集」に今の切り抜きを引き継ぐ(ヘッダーの appnav)
  const tt = editorHref(path);
  return `<div class="rv-ejob-a">${tt ? `<a class="btn small" href="${esc(tt)}" target="_blank" rel="noopener" data-edit-open title="「編集」(文字起こし・カット・Resolve へのパック)で、この切り抜きを開きます(文字起こしは自動では始めません)">編集で開く</a>` : ''}<button type="button" class="btn small ghost" data-act="copy" data-path="${esc(path)}" title="${esc(path)}">パスをコピー</button>${man ? `<span class="pill info" title="${esc(man)}">.clip.json あり</span>` : ''}</div>`;
}
/* 書き出した切り抜きを「編集」で開く URL(書き出しの行のリンクと、書き出し完了の知らせの [編集で開く] で同じ) */
function editorHref(path){ return path ? Studio.toolUrl('transcribe', '/?media=' + enc(path)) : ''; }
/* 「編集」を開く(行のリンク・知らせのボタンで同じ開き方。窓の決まり S-15): 窓(Edge のアプリの窓)で開いているときはホームに頼んで窓で(UIKit.win)、
   ブラウザのタブならいつもの新しいタブで。スタジオの画面はそのまま残す(配信を見ながら隣の窓で字幕を直す流れ。v0.20.2 の音を下げる仕組みもこの形が前提)。
   ホームへのリンク(案件で見る・案件の一覧)は data-ui-portal(ホームが開いていれば前に出す) */
function openEditor(href){
  if (!href) return;
  const w = window.UIKit && window.UIKit.win;
  if (w && Studio.token && w.isApp()){ w.open(href).catch(() => { window.open(href, '_blank', 'noopener'); }); return; }
  window.open(href, '_blank', 'noopener');
}
/* 書き出しが済んだ知らせ(S-7)。paths: 書き出した mp4 の絶対パス(書き出しの順)。最初の1本を [編集で開く](行のリンクと同じ URL・同じ開き方)。
   ボタンのある知らせは 8 秒(読んで押す間)。開けるものが無ければ今までどおりの知らせ */
function doneToast(msg, kind, paths){
  const ok = (paths || []).filter(Boolean), href = ok.length ? editorHref(ok[0]) : '';
  if (!href) return toast(msg, 0, kind);
  return Studio.toast(msg, { kind, ms: 8000, action: { label: ok.length > 1 ? '1本目を編集で開く' : '編集で開く', fn: () => openEditor(href) } });
}
async function copyText(text){
  try { await navigator.clipboard.writeText(text); return true; } catch {}
  try {   // clipboard API が使えないとき(古いブラウザ・権限なし)の予備
    const ta = document.createElement('textarea'); ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select(); const ok = document.execCommand('copy'); ta.remove(); return ok;
  } catch { return false; }
}
function jobDirText(j, st){
  const base = (j && j.outDir) || st.outDir || '';
  return j && j.folder && base ? joinPath(base, j.folder) : base;
}
/* 書き出しの欄の上の案内(ffmpeg・yt-dlp が無い)・画質の欄(YouTube から取るときだけ)・保存先 */
function renderExpTools(v, st, live){
  let msg = '';
  if (st.ffmpeg === false) msg += 'ffmpeg が見つかりません(Windows: winget install Gyan.FFmpeg / Mac: brew install ffmpeg)。入れてから起動し直してください';
  if (v && v.kind === 'youtube' && st.ytdlp === false) msg += (msg ? '\n' : '') + 'yt-dlp が見つかりません(Windows: winget install yt-dlp.yt-dlp)';
  const ts = $('#rvToolStatus'); ts.textContent = msg; ts.hidden = !msg;
  $('#rvHeightBox').hidden = !!(v && (v.kind === 'file' || live));   // 画質は YouTube から取るときだけ(録画は録ったときの画質)
  const j = S.lastJob; $('#rvOutDir').textContent = !live && j && j.folder && S.job && v && S.job.videoId === v.id ? jobDirText(j, st) : (st.outDir || '');
}
/* 「何件を書き出すか」の1文。書き出せないときは、どうすれば書き出せるかを出す。
   t = 書き出す対象のマーク・j / jrun / done = スタジオの書き出し(実行中か・済んだ数)・lact = 入口で書き出しの途中のジョブ(ライブの録画) */
function exportCountText(v, live, t, j, jrun, done, lact){
  const tgtName = { adopted: '採用', pending: '採用と候補', all: '不採用以外' }[S.settings.exportTarget] || '採用';
  if (S.exportAll && !live) return `全部の配信の書き出し: ${S.exportAll.idx}/${S.exportAll.total} 本目` + (S.exportAll.fail ? `(失敗 ${S.exportAll.fail}件)` : '');
  if (jrun) return `書き出し中 ${done}/${j.items.length}件`;
  if (!v) return '';
  if (t.length) return `${tgtName}のマーク ${t.length}件(合計 ${fmt(t.reduce((s, c) => s + (c.end - c.start), 0))})を mp4 にします` + (live && S.live ? '(録画が届くのを待ってから作ります)' : '');
  if (lact.length) return `書き出し中 ${lact.length}件` + (lact.some(x => x.state === 'wait') ? `(録画待ち ${lact.filter(x => x.state === 'wait').length}件)` : '');
  if (v.marks.some(m => !m.status)) return '候補を「採用」にすると、書き出せるようになります';
  return v.marks.length ? '書き出すマークはありません(「採用」にしたマークを書き出します)' : (live ? 'マークを付けると、ここに書き出しの進み具合が出ます' : 'マークを付けて「採用」にすると、書き出せるようになります');
}
/* 「書き出す」を押せるか・押せないときの理由(title)。ライブの録画は入口の書き出しなので、録画中でも書き出せる */
function renderExpRun(live, t, running, noTool){
  const r = $('#rvExpRun');
  if (live){
    r.disabled = LV.starting || !t.length || noTool;
    r.title = noTool ? 'ffmpeg が見つからないため書き出せません' : !t.length ? '書き出す対象のマークがありません(「採用」にしたマークが書き出されます)' : '録画中でも書き出せます(録画が届くのを待ってから作ります)';
  } else {
    r.disabled = running || !t.length || noTool || !!S.live;
    r.title = running ? '書き出しの実行中です(終わるか「中止」を押すと、次を書き出せます)' : noTool ? 'ffmpeg が見つからないため書き出せません' : S.live ? '配信中は書き出せません' : !t.length ? '書き出す対象のマークがありません(「採用」にしたマークが書き出されます)' : '';
  }
}
/* その他の書き出し: 全部の配信の採用・失敗した分だけやり直す・中止・つなげて1本に(どれもライブの録画では使わない) */
function renderExpMore(live, running, noTool){
  { const ok = x => x.kind !== 'live', n = S.videos.filter(ok).reduce((a, x) => a + (Number(x.adopted) || 0), 0), nv = S.videos.filter(x => ok(x) && x.adopted > 0).length, b = $('#rvExpAll');
    b.textContent = `全部の配信の採用を書き出す(${nv}本・${n}件)`; b.disabled = running || !n || !!S.live || noTool || live;
    /* 押せないときは、いつも理由を title に(S-25。以前は押せる理由の説明のまま) */
    b.title = live ? 'ライブの録画を開いている間は使えません(録画の配信は、開いて「書き出す」で書き出します)'
      : running ? '書き出しの実行中は使えません(終わるか「中止」を押してから)'
      : S.live ? '配信中は書き出せません(配信が終わってから)'
      : noTool ? 'ffmpeg が見つからないため書き出せません'
      : !n ? '採用にしたマークがある配信がありません(マークを「採用」にすると使えます。ライブの録画は除きます)'
      : '採用にしたマークがある全部の配信を、順番に書き出します(ライブの録画は除きます)'; }
  { const n = live ? 0 : failedIds().size, b = $('#rvExpRetry'); b.hidden = !n; b.textContent = `失敗した分だけやり直す(${n}件)`; b.disabled = running;
    b.title = running ? '書き出しの実行中は使えません(終わるか「中止」を押してから)' : '失敗・中止したマークだけを、もう一度書き出します'; }
  $('#rvExpCancel').hidden = live || !running;   // ライブの録画は行ごとに取り消す
  { const n = joinIds().length, b = $('#rvJoinRun');   // チェックしたマークをつなげて1本に(2 件から)
    b.hidden = !n; b.textContent = `チェックした ${n} 件をつなげて1本に`;
    b.disabled = running || n < 2 || noTool || !!S.live || live;
    b.title = live ? 'ライブの録画は、つなげて1本にできません(1件ずつ書き出してから「編集」でつないでください)' : n < 2 ? '2 件以上チェックしてください' : S.live ? '配信中は書き出せません' : noTool ? 'ffmpeg が見つからないため書き出せません' : '時刻の順につないで、1本の mp4 にします(つなぎ目はそのまま)'; }
}
function renderExportUI(){
  if (!S.built) return;
  const v = S.cur, st = Studio.state || {};
  const live = !!(v && v.kind === 'live');   // ライブの録画: 書き出しは入口(../live/api/export)。録画中でも書き出せる・つなぐ・全部の配信の書き出しは使わない
  renderExpTools(v, st, live);
  const t = exportTargets();
  $('#rvExpTarget').value = S.settings.exportTarget;
  const running = !!(S.job && S.job.running) || S.starting || !!S.exportAll;
  const j = live ? null : S.lastJob, jrun = !!(j && S.job && S.job.running && j.items.length);
  const done = jrun ? j.items.filter(i => i.status === 'done').length : 0;
  const lact = live ? LV.jobs.filter(x => LIVE_ACTIVE.includes(x.state)) : [];
  const count = exportCountText(v, live, t, j, jrun, done, lact);
  $('#rvExpCount').textContent = count;
  $('#rvExpSum').textContent = (S.exportAll && !live) || jrun || (lact.length && !t.length) ? count : t.length ? `対象 ${t.length}件` : '';
  { const je = $('#rvJumpExp'); if (je) je.textContent = (S.exportAll && !live) || jrun || lact.length ? '実行中' : t.length ? t.length + '件' : ''; }
  { const b = $('#rvExpRun'); if (b) b.textContent = t.length && !jrun && !(S.exportAll && !live) ? `${t.length}件を書き出す` : '書き出す'; }
  { const bar = $('#rvExpBar'); bar.hidden = !jrun;
    if (jrun){ const cur = j.items.find(i => i.status === 'running'); bar.firstElementChild.style.width = Math.round((done + (cur ? cur.progress || 0 : 0)) / j.items.length * 100) + '%'; } }
  const noTool = st.ffmpeg === false;
  renderExpRun(live, t, running, noTool);
  renderExpMore(live, running, noTool);
}
function joinIds(){ return sortedMarks().filter(c => S.join.has(c.id)).sort((a, b) => a.start - b.start).map(c => c.id); }
/* チェックしたマークを時刻の順につないで1本の mp4 に(2026-09-28 ユーザー要望。同じ配信の中だけ・つなぎ目はそのまま)。
   つないだ動画は元の配信の1つの区間ではないので、.clip.json・マークの「書き出し済み」・自動の文字起こしは付けない(「編集で開く」から) */
async function startJoin(){
  if (S.starting || S.exportAll || (S.job && S.job.running)) return;
  const v = S.cur, ids = joinIds();
  if (!v || ids.length < 2) return toast('つなげるマークを2件以上チェックしてください');
  if (S.live) return toast('配信中は書き出せません。配信終了後に実行してください');
  S.starting = true; renderExportUI();
  try {
    await flushSave();
    if (S.cur !== v) throw new Error('配信が切り替わりました。やり直してください');
    const j = await Studio.api('/api/export', { method: 'POST', body: { id: v.id, markIds: ids, combine: true, ...expOpts() } });
    S.job = { id: j.id, videoId: v.id, running: true, combine: true }; rememberJob({ id: j.id, videoId: v.id });
    S.join.clear(); renderList();
    renderJob(j); pollJob();
  } catch (e){ toast(e.message || 'つなぐ書き出しを開始できませんでした', 0, 'err'); }
  finally { S.starting = false; renderExportUI(); }
}
function combinedHTML(j){   // つないだ1本の行(書き出しの一覧の先頭)
  const c = j.combined; if (!c) return '';
  const pct = Math.round((c.progress || 0) * 100), cls = c.status === 'done' ? 'ok' : c.status === 'error' ? 'err' : c.status === 'running' ? 'run' : c.status === 'cancelled' ? 'warn' : 'wait';
  return `<li class="rv-ejob st-${cls}"><div class="rv-ejob-h">
      <span class="rv-ejob-n">つないだ1本(${c.count}件${c.seconds ? '・' + fmt(c.seconds) : ''})</span>
      <span class="pill ${cls}">${esc(c.status === 'queued' ? '部品を切り出し中' : EXP_LABEL[c.status] || c.status)}${c.status === 'running' ? ' ' + pct + '%' : ''}</span></div>
      ${c.status === 'running' ? `<div class="bar rv-ejob-bar"><i style="width:${pct}%"></i></div>` : ''}
      ${c.file ? `<div class="rv-ejob-s mono">${esc(c.file)}</div>` : ''}
      ${handoffHTML(j, { status: c.status, path: c.path, file: c.file })}
      ${loudHTML(c.loudness)}
      ${c.error ? `<div class="rv-ejob-s rv-err">${esc(c.error)}</div>` : ''}</li>`;
}
/* 1件ずつの行を作り、変わった行だけを置き換える(毎秒の状態確認で全部を作り直すと、押した瞬間のボタンが消えてクリックが失われるため) */
function loudHTML(lo){   // ラウドネスをそろえた結果(書き出しの行に出す)
  if (!lo || typeof lo !== 'object') return '';
  if (lo.skipped) return `<div class="rv-ejob-s hint">音量はそろえませんでした: ${esc(lo.skipped)}</div>`;
  const g = Number(lo.gainDb), m = Number(lo.measured), t = Number(lo.target);
  if (!Number.isFinite(g) || !Number.isFinite(m) || !Number.isFinite(t)) return '';
  const reached = Math.abs(m + g - t) < 0.6;
  return `<div class="rv-ejob-s hint">音量: ${m.toFixed(1)} → ${(m + g).toFixed(1)} LUFS(${g >= 0 ? '+' : ''}${g.toFixed(1)} dB${reached ? '' : '。音が割れないよう目標の手前で止めました'})</div>`;
}
function jobItemHTML(j, it, i){
  const pct = Math.round((it.progress || 0) * 100), cls = it.status === 'done' ? 'ok' : it.status === 'error' ? 'err' : it.status === 'running' ? 'run' : it.status === 'cancelled' ? 'warn' : 'wait';
  /* ライブの録画(入口の書き出し。j.live): 状態は入口の言葉(録画待ち・取得中・作り直し中 n%)。行ごとに取り消す・やり直すは「書き出す」から */
  const lv = !!j.live, act = lv && (it.status === 'queued' || it.status === 'running');
  const label = (lv && it.stateLabel) || EXP_LABEL[it.status] || it.status;
  const ar = lv ? it.archive : null;   // 本番版への作り直し(P4。入口のジョブの archive)
  return `<li class="rv-ejob st-${cls}"${lv ? ` data-ljob="${esc(it.jobId || '')}"` : ''}><div class="rv-ejob-h">
      <span class="mono rv-ejob-t">${i + 1}. ${fmt(it.start)} – ${fmt(it.end)}</span><span class="rv-ejob-n">${esc(it.title || '無題')}</span>
      <span class="pill ${cls}">${esc(label)}${it.status === 'running' && (!lv || pct > 0) ? ' ' + pct + '%' : ''}</span>${ar && ar.state === 'done' ? `<span class="rv-chip arch" title="${ARCH_TITLE}">本番版</span>` : ''}${act ? `<button type="button" class="btn small ghost" data-act="lxcancel" data-job="${esc(it.jobId || '')}">取り消す</button>` : ''}</div>
      ${archLineHTML(ar)}
      ${it.status === 'running' && (!lv || pct > 0) ? `<div class="bar rv-ejob-bar"><i style="width:${pct}%"></i></div>` : ''}
      ${act && it.message ? `<div class="rv-ejob-s hint">${esc(it.message)}</div>` : ''}
      ${it.file ? `<div class="rv-ejob-s mono">${esc(it.file)}</div>` : ''}
      ${handoffHTML(j, it)}
      ${loudHTML(it.loudness)}
      ${lv && it.status === 'done' && it.tx ? `<div class="rv-ejob-s hint">${esc(liveTxText(it.tx))}</div>` : ''}
      ${it.warning ? `<div class="rv-ejob-s rv-warnline">${esc(it.warning)}</div>` : ''}
      ${it.error ? `<div class="rv-ejob-s rv-err">${esc(it.error)}${lv ? (it.needsArchive ? '(録画に欠けがあります。帯の「アーカイブで作り直す」で作れます)' : '(マークを採用のままにしてあります。「書き出す」でやり直せます)') : ''}</div>` : ''}</li>`;
}
/* 入口の書き出しが渡したまとめて実行の進み具合(ジョブの tx = {state, label, message, steps})→ 行の1文。
   全自動(段にパックがある)は「文字起こし → パック: 実行中(Resolve パック)」「… : パック済み」。届け先の無い「届ける」の段(飛ばした)は出さない */
function liveTxText(tx){
  if (!tx) return '';
  const steps = (Array.isArray(tx.steps) ? tx.steps : []).filter(x => x && !(x.key === 'deliver' && x.state === 'skip'));
  const pack = steps.find(x => x.key === 'pack');
  let label = String(tx.label || tx.state || '');
  if (tx.state === 'running'){ const cur = steps.find(x => x.state === 'run'); if (cur && cur.label) label += '(' + cur.label + ')'; }
  else if (tx.state === 'done' && pack) label = pack.state === 'done' ? 'パック済み' : pack.state === 'skip' ? '文字起こし済み(パックは作れませんでした)' : label;
  return (pack ? '文字起こし → パック: ' : '文字起こし: ') + label + (tx.state === 'error' && tx.message ? '(' + tx.message + ')' : '');
}
/* 書き出しの行の、本番版への作り直しの1行(済み = 札だけなので無し)。外から来る文字は esc */
function archLineHTML(a){
  if (a && a.packOld) return '<div class="rv-ejob-s rv-warnline">前に作ったパックは速報版のままです。「編集」の 3 パック のタブで作り直してください</div>';   // 入口の archive.packOld(動画の写しを入れるパック)
  if (!a || a.state === 'done') return '';
  if (a.active) return `<div class="rv-ejob-s hint">本番版: ${esc(a.label)}${a.progress > 0 ? ' ' + Math.round(a.progress * 100) + '%' : ''}${a.message ? '(' + esc(a.message) + ')' : ''}</div>`;
  if (a.state === 'error') return `<div class="rv-ejob-s rv-warnline">本番版に作り直せませんでした${a.message ? ': ' + esc(a.message) : ''}(速報版のままです)</div>`;
  if (a.state === 'cancelled') return '<div class="rv-ejob-s hint">本番版への作り直しを取り消しました(速報版のままです)</div>';
  return '';
}
function renderJob(j){
  S.lastJob = j;
  if (S.job) S.job.running = j.state === 'running';
  if (!(S.cur && S.cur.kind === 'live')) renderJobRows(j);   // ライブの録画を開いている間、欄は入口の書き出し(renderLiveJobs)が使う
  renderExportUI();
}
/* 書き出しの一覧(#rvExpList)を描く。スタジオの書き出し(renderJob)と、ライブの録画の入口の書き出し(renderLiveJobs)で共通 */
function renderJobRows(j){
  const ol = $('#rvExpList');
  const rows = j.items.map((it, i) => jobItemHTML(j, it, i));
  if (j.combined) rows.unshift(combinedHTML(j));
  const h = j.live ? '' : j.items.map(i => errHint(i.error)).find(Boolean);
  if (h) rows.push(`<li class="hint rv-ejob-hint">${esc(h)}</li>`);
  if (j.waiting) rows.unshift('<li class="hint rv-ejob-hint">他のツールの重い処理が終わるのを待っています(順番が来たら書き出しを始めます。中止もできます)</li>');
  const prev = S.jobRows || [];
  if (ol.dataset.job !== String(j.id) || prev.length !== rows.length || ol.children.length !== rows.length){
    ol.innerHTML = rows.join(''); ol.dataset.job = String(j.id);
  } else {
    rows.forEach((r, i) => { if (r !== prev[i]){ const t = document.createElement('template'); t.innerHTML = r; ol.children[i].replaceWith(t.content.firstElementChild); } });
  }
  S.jobRows = rows;
}
function stopExpPoll(){ if (expTimer){ clearInterval(expTimer); expTimer = null; } }
function pollJob(){
  stopExpPoll();
  let lastDone = -1, busy = false;
  const tick = async () => {
    if (!S.job || busy) return;
    busy = true;
    try {
      const j = await Studio.api('/api/export?id=' + enc(S.job.id));
      if (!S.job) return;
      renderJob(j);
      const done = j.items.filter(i => i.status === 'done').length;
      const fin = j.state !== 'running';
      if (fin) stopExpPoll();
      if (S.cur && S.cur.id === S.job.videoId && (done !== lastDone || fin)){ lastDone = done; await syncFromServer(); }
      else if (fin) refreshList();
      if (fin){
        rememberJob(null);
        /* 済んだ知らせに [編集で開く](S-7。つないだ1本・書き出した最初の1本。行のリンクと同じ URL) */
        const cdone = j.combined && j.combined.status === 'done', paths = j.state === 'cancelled' ? []
          : j.combined ? (cdone ? [clipPathOf(j, { path: j.combined.path, file: j.combined.file })] : []) : j.items.filter(i => i.status === 'done').map(i => clipPathOf(j, i));
        if (j.combined) doneToast(j.state === 'cancelled' ? 'つなぐ書き出しを中止しました' : cdone ? `つなげて1本にしました(${j.combined.count}件)。「編集で開く」で文字起こしできます` : 'つなげられませんでした: ' + (j.combined.error || ''), j.state === 'cancelled' ? '' : cdone ? 'ok' : 'err', paths);
        else doneToast(j.state === 'cancelled' ? '書き出しを中止しました' : `書き出し完了: ${done}/${j.items.length}件` + (done < j.items.length ? '(失敗あり)' : ''), j.state === 'cancelled' ? '' : done < j.items.length ? 'err' : 'ok', paths);
        if (!j.combined && j.state !== 'cancelled' && typeof maybeAutoTranscribe === 'function'){ const vid = S.job.videoId, doneIds = j.items.filter(i => i.status === 'done').map(i => i.id); if (doneIds.length) maybeAutoTranscribe(vid, doneIds); }
      }
    } catch (e){
      if (e.status === 404){ S.job = null; rememberJob(null); stopExpPoll(); renderExportUI(); }
    } finally { busy = false; }
  };
  expTimer = setInterval(tick, 1000); tick();
}
async function startExport(onlyIds){
  if (S.cur && S.cur.kind === 'live') return startLiveExport(onlyIds);   // ライブの録画は入口の書き出しへ(スタジオの /api/export は録画を読めない。録画中でも書き出せる)
  if (S.starting || S.exportAll || (S.job && S.job.running)) return;
  const v = S.cur;
  if (!v) return toast('先に配信を開いてください');
  if (S.live) return toast('配信中は書き出せません。配信終了後に実行してください');
  const targets = onlyIds ? sortedMarks().filter(c => onlyIds.has(c.id)) : exportTargets();
  if (!targets.length) return toast('書き出すマークがありません(「採用」にしたマークが書き出されます。書き出し対象の選択も確認してください)');
  S.starting = true; renderExportUI();
  try {
    await flushSave(); // サーバーが保存済みのマークから範囲を組み立てるため、先に保存する
    if (S.cur !== v) throw new Error('配信が切り替わりました。書き出す配信を確かめてやり直してください');
    const j = await Studio.api('/api/export', { method: 'POST', body: { id: v.id, markIds: targets.map(c => c.id), ...expOpts() } });
    S.job = { id: j.id, videoId: v.id, running: true }; rememberJob({ id: j.id, videoId: v.id });
    renderJob(j); pollJob();
  } catch (e){ toast(e.message || '書き出しを開始できませんでした', 0, 'err'); }
  finally { S.starting = false; renderExportUI(); }
}
/* 全動画の「採用」マークを、動画ごとに順番に書き出す(この画面を開いている間、動画を切り替えながら進める) */
async function startExportAll(){
  if (S.starting || S.exportAll) return;
  if (S.job && S.job.running) return toast('書き出しの実行中です');
  if (S.live) return toast('配信中は書き出せません。配信終了後に実行してください');
  S.starting = true; renderExportUI();
  let list;
  try {
    await flushSave();
    list = (await Studio.api('/api/videos')).videos.filter(x => x.adopted > 0 && x.kind !== 'live');   // ライブの録画は入口で書き出す(スタジオの書き出しは断る)
  } catch (e){ toast(e.message || '配信の一覧を取得できませんでした'); return; }
  finally { S.starting = false; renderExportUI(); }
  if (!list.length) return toast('採用にしたマークがありません');
  S.exportAll = { idx: 0, total: list.length, fail: 0, cancel: false, done: 0, interrupted: false };
  renderExportUI();
  try {
    allVideos:
    for (const x of list){
      if (S.exportAll.cancel) break;
      S.exportAll.idx++; renderExportUI();
      let v;
      try { v = (await Studio.api('/api/video?id=' + enc(x.id))).video; } catch { S.exportAll.fail++; continue; }
      const ids = v.marks.filter(m => m.status === 'adopted').map(m => m.id);
      if (!ids.length) continue;
      // API の1回50件制限に合わせ、同じ動画のマークも分割する。
      for (let offset = 0; offset < ids.length; offset += 50){
        if (S.exportAll.cancel) break allVideos;
        const chunk = ids.slice(offset, offset + 50);
        let j;
        try { j = await Studio.api('/api/export', { method: 'POST', body: { id: v.id, markIds: chunk, ...expOpts() } }); }
        catch (e){
          toast((v.title || v.id) + ': ' + (e.message || '書き出しを開始できませんでした'));
          // POST の応答を失った場合も開始している可能性がある。続けて依頼しない。
          if (!e.status || e.status === 409){ S.exportAll.interrupted = true; break allVideos; }
          S.exportAll.fail += chunk.length; continue;
        }
        S.job = { id: j.id, videoId: v.id, running: j.state === 'running' };
        rememberJob({ id: j.id, videoId: v.id }); renderJob(j);
        while (j.state === 'running'){
          if (S.exportAll.cancel){
            try { await Studio.api('/api/export/cancel', { method: 'POST', body: { id: j.id } }); } catch {}
          }
          try { j = await Studio.api('/api/export?id=' + enc(j.id)); }
          catch (e){
            S.exportAll.interrupted = true;
            if (e.status === 404){ S.job = null; rememberJob(null); }
            else pollJob(); // 実行中の状態を維持し、このジョブの確認だけを続ける
            break allVideos;
          }
          renderJob(j);
          if (j.state === 'running') await new Promise(r => setTimeout(r, 1000));
        }
        rememberJob(null);
        // typeof で確かめる: test_review.cjs はこの関数を、まとめて実行の定義を含まない範囲だけ切り出して確かめるため
        if (typeof maybeAutoTranscribe === 'function'){ const doneIds = j.items.filter(i => i.status === 'done').map(i => i.id); if (j.state !== 'cancelled' && doneIds.length) maybeAutoTranscribe(v.id, doneIds); }
        S.exportAll.done += j.items.filter(i => i.status === 'done').length;
        S.exportAll.fail += j.items.filter(i => i.status !== 'done').length;
        if (S.cur && S.cur.id === v.id) await syncFromServer();
        if (j.state === 'cancelled'){ S.exportAll.cancel = true; break allVideos; }
      }
    }
  } finally {
    const r = S.exportAll; S.exportAll = null;
    await refreshList(); renderExportUI();
    toast(r.interrupted ? '書き出し状態を確認できないため、一括処理を中断しました。進捗を確認してから再実行してください' : r.cancel ? `全部の配信の書き出しを中止しました(${r.done}件完了)` : `全部の配信の書き出し完了: ${r.done}件` + (r.fail ? `(失敗 ${r.fail}件)` : ''));
  }
}
/* 書き出しの設定(方式・画質・音量)。POST /api/export の body に足す(1本ずつ・つなぐ・全部の配信で同じ) */
function expOpts(){ const s = S.settings; return { precision: s.precision, maxHeight: s.maxHeight, volume: s.exportVolume, loudness: s.exportLoudness || null }; }
async function resumeJob(){
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem('clipstudio:rvjob') || 'null'); } catch {}
  if (!saved || !saved.id) return;
  try {
    const j = await Studio.api('/api/export?id=' + enc(saved.id));
    S.job = { id: saved.id, videoId: saved.videoId, running: j.state === 'running' };
    renderJob(j);
    if (j.state === 'running') pollJob(); else rememberJob(null);
  } catch (e){
    if (e.status === 404) rememberJob(null);
    else {
      S.job = { id: saved.id, videoId: saved.videoId, running: true };
      renderExportUI(); pollJob(); // 通信断だけでは、再読み込み前のジョブを忘れない
    }
  }
}

/* ---------- 描画 ---------- */
function totalDur(){
  const v = S.cur; if (!v) return 60;
  return S.duration || v.duration || (S.series && S.series.n) || Math.max(60, ...v.marks.map(c => c.end), S.now) + 30;
}
const pct = t => Math.min(100, Math.max(0, t / totalDur() * 100));
function renderMeta(){
  const v = S.cur;
  $('#rvMain').hidden = !v; $('#rvEmpty').hidden = !!v;
  for (const id of ['#rvJump', '#rvTheater', '#rvVMenu', '#rvSave']) $(id).hidden = !v;
  renderAutoMenu(v);
  if (!v){
    $('#rvCurLabel').textContent = S.videos.length ? '選んでください' : 'まだありません'; $('#rvCurLabel').classList.add('is-empty'); $('#rvChips').textContent = S.videos.length ? `${S.videos.length}本から探せます` : ''; closeExportDrawer();
    /* 空の状態の次の一手(S-13): 配信があれば「選ぶ・開く」、まだ無ければ「② 解析へ」を主なボタンに */
    const has = !!S.videos.length;
    $('#rvEmptyOpen').className = 'btn' + (has ? ' primary' : ' ghost'); $('#rvEmptyQueue').className = 'btn' + (has ? ' ghost' : ' primary');
    return;
  }
  const has = !!v.title, el = $('#rvCurLabel');
  el.classList.toggle('is-empty', !has);   // 'empty' は ui-kit の「空の状態」の枠と名前がぶつかるので使わない
  el.textContent = has ? v.title : '(名前なし)';
  /* だれの・いつの(同じ題名の配信を見分ける)。ID・ファイル名は title で */
  const auto = v.marks.filter(m => m.src === 'auto').length, exp = v.marks.filter(m => m.status === 'exported').length;
  const row = S.videos.find(x => x.id === v.id), t0 = row ? (row.createdAt || row.updatedAt) : v.createdAt;
  const ch = $('#rvChips');
  ch.innerHTML = `<span class="rv-chip-who">${esc(vWho(v))}</span>${t0 ? `<span class="q-dot">・</span><span>${esc(Studio.ago(t0))}</span>` : ''}${auto ? `<span class="rv-chip auto">自動 ${auto}</span>` : ''}${exp ? `<span class="rv-chip done">書き出し済み ${exp}</span>` : ''}`;
  ch.title = v.kind === 'file' ? '動画ファイル: ' + (v.fileName || v.id) : v.kind === 'live' ? 'ライブの録画: ' + ((v.live && v.live.url) || v.id) : 'YouTube: ' + v.id;
  const t = $('#rvTitle'); if (document.activeElement !== t) t.value = v.title || '';
  $('#rvAnalyze').hidden = v.kind !== 'youtube';   // ライブの録画は解析しない(サーバーも断る)
  /* YouTube で開く: ライブの録画は動画の id が分かるときだけ。時刻は付けない(録画の秒は配信の秒ではない) */
  const ytHref = v.kind === 'youtube' ? 'https://www.youtube.com/watch?v=' + enc(v.id) : liveYtHref(v);
  const yl = $('#rvYtLink'); yl.hidden = !ytHref; if (ytHref) yl.href = ytHref;
  yl.title = v.kind === 'live' ? 'YouTube で配信を開きます(録画の時刻とは合わないので、頭から開きます)' : 'YouTube で、いまの位置から開きます';
}
/* まとめて実行の入口(上の行)。使えないときも隠さず、押せない理由を出す(S-25): ホームから開いていない・ライブの録画(まとめて実行はスタジオの書き出しを使う)。
   配信を開いていないときは、ほかの配信ごとの操作と同じく出さない */
function autoOffReason(v){
  if (!Studio.token) return 'まとめて実行は、ホーム(start.bat)から開いたときだけ使えます';
  if (v && v.kind === 'live') return 'ライブの録画では使えません(書き出したあとの文字起こし・パックは、LIVE の帯の「書き出したあと」で選べます)';
  return '';
}
function renderAutoMenu(v){
  const d = $('#rvAuto'), sm = d && d.querySelector('summary'); if (!sm) return;
  d.hidden = !v;
  const why = autoOffReason(v);
  d.classList.toggle('is-off', !!why);
  /* 押せないときは押しても開かずに理由を知らせる(ui-kit v21 の共通の書き方 UIKit.menuOff。Enter・Space も) */
  if (window.UIKit && UIKit.menuOff) UIKit.menuOff(d, why, '案件の画面と同じ「まとめて実行」を、この配信で始めます');
}
function renderDuration(){
  $('#rvDur').textContent = '/ ' + (S.duration ? fmt(S.duration) : '--');
  $('#rvTlEnd').textContent = fmt(totalDur());
}
function renderDraft(){
  const { start, end } = S.draft;
  const a = $('#rvInVal'), b = $('#rvOutVal');
  a.textContent = start == null ? '--' : fmt(start); a.classList.toggle('is-empty', start == null);
  b.textContent = end == null ? '--' : fmt(end); b.classList.toggle('is-empty', end == null);
  $('#rvDraftDur').textContent = start != null && end != null ? `長さ ${(end - start).toFixed(1)} 秒` : start != null ? '次に OUT を押します' : 'IN と OUT を押すと追加できます';
  const d = $('#rvDraft');
  if (start == null){ d.hidden = true; return; }
  d.hidden = false; d.style.left = pct(start) + '%';
  d.style.width = end == null ? '3px' : Math.max(0.3, pct(end) - pct(start)) + '%';
}
function renderPlayhead(){
  const p = pct(S.now) + '%';
  const a = $('#rvPh'); if (a) a.style.left = p;
  const g = $('#rvGCur'); if (g) g.style.left = p;
}
function renderTimeline(){
  if (!S.cur) return;
  $('#rvSegs').innerHTML = sortedMarks().map(c => {
    const l = pct(c.start), w = Math.max(0.2, pct(c.end) - l);
    return `<button type="button" class="rv-seg ${isAutoLike(c) ? 'auto' : 'man'}${c.status ? ' st-' + esc(c.status) : ''}${S.sel === c.id ? ' sel' : ''}" style="left:${l}%;width:${w}%" data-id="${esc(c.id)}" aria-label="${esc(STATUS_LABEL[c.status || ''] || c.status)} ${esc(c.label || (c.src === 'auto' ? '自動' : '無題'))} ${fmt(c.start)}から${fmt(c.end)}"></button>`;
  }).join('');
  renderDuration(); renderPlayhead(); renderDraft(); renderGraph();
  placeNote();   // 選んだマークが変わった(選ぶ・足す・消すはどれもここを通る)
}

/* 盛り上がりグラフ: series.total の面グラフ + マークの帯。プレイヘッドの動きでは再描画しない(カーソル線だけ動かす)。
   2026-10-04 見やすく: 高さ 150px・時間の目盛りと縦の補助線・帯をマークの状態(候補・採用・不採用・書き出し済み)の色に・選んだマークを強調・
   山に点と縦の線・山の札は横に重ならないよう段を分ける(段の数だけ上を空けて、曲線と札が重ならない)・マウスの位置の時刻。
   形: 背景の SVG(補助線・帯。上から下の目盛りの帯まで)+ 曲線の SVG(札の段の下から)+ HTML(札・点・目盛りの文字。SVG は縦横に伸ばすので、丸や文字は HTML で置く) */
const GW = 1000, GH = 100;
const G_LANE = 21, G_PAD = 5;   // 札の1段の高さ・上の余白(px)。下の目盛りの帯の高さは review.css の --g-axis
const TICK_STEPS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200];
/* 目盛りの間隔: 画面の幅で 70px 以上空く、いちばん細かい間隔 */
function tickStep(dur, w){ return TICK_STEPS.find(st => st / dur * w >= 70) || TICK_STEPS[TICK_STEPS.length - 1]; }
function tickLabel(t){
  const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), sec = Math.floor(t % 60), p2 = n => String(n).padStart(2, '0');
  return h ? `${h}:${p2(m)}:${p2(sec)}` : `${m}:${p2(sec)}`;
}
const PEAK_MAX = 5;
function findPeaks(total){
  const idx = [];
  for (let i = 1; i < total.length - 1; i++) if (total[i] >= total[i - 1] && total[i] >= total[i + 1] && total[i] > 0) idx.push(i);
  if (!idx.length) return [];
  idx.sort((a, b) => total[b] - total[a]);
  const minGap = Math.max(2, Math.round(total.length * 0.03)), picked = [];
  for (const i of idx){
    if (picked.length >= PEAK_MAX) break;
    if (picked.some(p => Math.abs(p - i) < minGap)) continue;
    picked.push(i);
  }
  return picked.sort((a, b) => total[b] - total[a]);   // 高い順(1位から)
}
const PEAK_REASONS = [['audio', '声・笑い'], ['chat', 'チャット急増'], ['comments', 'コメント']];
function peakReason(s, idx, win){
  let best = '', bestScore = -Infinity;
  for (const [k, label] of PEAK_REASONS){
    const arr = s[k]; if (!Array.isArray(arr) || !arr.length) continue;
    const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
    let sum = 0, n = 0;
    for (let i = Math.max(0, idx - win); i <= Math.min(arr.length - 1, idx + win); i++){ sum += arr[i] || 0; n++; }
    const score = (n ? sum / n : 0) - mean;
    if (score > bestScore){ bestScore = score; best = label; }
  }
  return best;
}
function renderGraph(){
  const box = $('#rvGraph'), leg = $('#rvGLegend'), peaksEl = $('#rvGPeaks'), ticksEl = $('#rvGTicks'), v = S.cur, s = S.series;
  const clear = () => { if (peaksEl) peaksEl.innerHTML = ''; if (ticksEl) ticksEl.innerHTML = ''; };
  if (!v){ box.hidden = true; leg.hidden = true; clear(); return; }
  if (!s || !Array.isArray(s.total) || !s.total.length){
    box.hidden = true;
    const hasAuto = v.marks.some(isAutoLike) || !!v.analysis;
    leg.hidden = !hasAuto;
    if (hasAuto) leg.innerHTML = '<span class="hint" title="盛り上がりのグラフは、解析した直後だけ出ます(ホームのサーバーを終了すると消えます)">グラフは解析した直後だけ出ます</span>';
    clear();
    return;
  }
  box.hidden = false; leg.hidden = false;
  const W = box.clientWidth || 800;   // まだ見えていない(幅 0)ときは仮の幅。見えたら ResizeObserver で描き直す
  const dur = totalDur(), step = Number(s.step) > 0 ? Number(s.step) : 1;
  const X = i => Math.min(GW, i * step / dur * GW);
  const Y = (y, mx) => (GH - (y / mx) * (GH - 4)).toFixed(1);   // 上に 4% だけ余白(山の頂上が枠に付かない)
  const line = arr => { const mx = Math.max(1e-9, ...arr); return arr.map((y, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(y, mx)).join(''); };
  const total = s.total, mx = Math.max(1e-9, ...total);
  const area = `M${X(0).toFixed(1)} ${GH}L${total.map((y, i) => X(i).toFixed(1) + ' ' + Y(y, mx)).join('L')}L${X(total.length - 1).toFixed(1)} ${GH}Z`;

  /* 山の札: 位置(x)の順に、前の札と横に重ならない最初の段へ。段の数だけ上を空ける(曲線は札の段の下から描く) */
  const win = Math.max(1, Math.round(total.length * 0.015));
  const peaks = findPeaks(total).map((idx, i) => ({ idx, t: idx * step, rank: i + 1, reason: peakReason(s, idx, win), x: X(idx) / GW * W }));
  let lanesN = 1;
  if (peaksEl){
    peaksEl.innerHTML = peaks.map(p => `<button type="button" class="rv-gpeak${p.rank === 1 ? ' r1' : ''}" data-t="${p.t}" title="${p.rank}位の山${p.reason ? ' ' + esc(p.reason) : ''}(${tickLabel(p.t)}付近。押すと5秒前へ)"><b class="rv-gpk-n">${p.rank}</b>${p.reason ? ' ' + esc(p.reason) : ''}</button>`).join('');
    const btns = [...peaksEl.querySelectorAll('.rv-gpeak')], lanes = [];
    peaks.forEach((p, i) => { p.el = btns[i]; p.w = btns[i].offsetWidth || (p.reason.length * 12 + 26); });
    [...peaks].sort((a, b) => a.x - b.x).forEach(p => {
      p.left = Math.max(2, Math.min(W - p.w - 2, p.x - p.w / 2));
      let k = lanes.findIndex(r => r + 4 <= p.left); if (k < 0){ k = lanes.length; lanes.push(0); }
      lanes[k] = p.left + p.w; p.lane = k;
    });
    lanesN = Math.max(1, lanes.length);
    for (const p of peaks){
      const top = G_PAD + p.lane * G_LANE, x = (p.x / W * 100).toFixed(2) + '%', f = (Number(Y(total[p.idx], mx)) / GH).toFixed(4), r1 = p.rank === 1 ? ' r1' : '';
      p.el.style.left = p.left.toFixed(1) + 'px'; p.el.style.top = top + 'px';
      /* 縦の線(札の下から目盛りの帯まで)と、曲線の上の点(--f = 曲線の SVG の中の縦の位置 0〜1) */
      p.el.insertAdjacentHTML('beforebegin', `<i class="rv-gpk-stem${r1}" style="left:${x};top:${top + 18}px"></i><i class="rv-gpk-dot${r1}" style="left:${x};--f:${f}"></i>`);
    }
  }
  box.style.setProperty('--g-top', (G_PAD + lanesN * G_LANE + 2) + 'px');

  /* 時間の目盛り(縦の補助線と文字)。端の近く(下の 0:00 / 長さの文字と重なる所)は出さない */
  const ts = tickStep(dur, W), ticks = [];
  for (let t = ts; t < dur - ts * 0.35; t += ts) ticks.push(t);
  const grid = ticks.map(t => { const x = (t / dur * GW).toFixed(1); return `<line class="rv-g-grid" x1="${x}" x2="${x}" y1="0" y2="${GH}"/>`; }).join('');
  if (ticksEl) ticksEl.innerHTML = ticks.map(t => `<span class="rv-gtick" style="left:${(t / dur * 100).toFixed(2)}%">${tickLabel(t)}</span>`).join('');

  /* マークの帯: 自動マーク(+ 選んでいる手動のマーク)。色はマークの状態(候補・採用・不採用・書き出し済み)、選んでいるマークは強調 */
  const bands = v.marks.filter(m => isAutoLike(m) || m.id === S.sel).map(m => {
    const x = Math.min(GW, m.start / dur * GW), w = Math.max(2, Math.min(GW, m.end / dur * GW) - x), x1 = x.toFixed(1), x2 = (x + w).toFixed(1);
    const cls = 'st-' + (STATUS_LABEL[m.status || ''] && m.status ? m.status : 'cand') + (m.id === S.sel ? ' sel' : '');
    return `<g class="rv-g-band ${cls}" data-id="${esc(m.id)}"><rect x="${x1}" y="0" width="${w.toFixed(1)}" height="${GH}"/><line x1="${x1}" x2="${x1}" y1="0" y2="${GH}"/><line x1="${x2}" x2="${x2}" y1="0" y2="${GH}"/></g>`;
  }).join('');
  const lines = S.settings.graphLines ? [['audio', 'a'], ['chat', 'c'], ['comments', 'm']].filter(([k]) => Array.isArray(s[k]) && s[k].length).map(([k, c]) => `<path class="rv-g-line ${c}" d="${line(s[k])}"/>`).join('') : '';
  $('#rvGSvg').innerHTML = `<svg class="rv-gbg" viewBox="0 0 ${GW} ${GH}" preserveAspectRatio="none" aria-hidden="true">${grid}${bands}</svg>` +
    `<svg class="rv-gplot" viewBox="0 0 ${GW} ${GH}" preserveAspectRatio="none" role="img" aria-label="盛り上がりグラフ"><path class="rv-g-area" d="${area}"/>${lines}</svg>`;
  leg.innerHTML = `<span class="rv-lg"><i class="rv-sw tot"></i>盛り上がり(合計)</span><span class="rv-lg" title="自動マークの範囲。色はマークの状態"><i class="rv-sw band"></i>候補<i class="rv-sw band ok"></i>採用<i class="rv-sw band ng"></i>不採用</span>` +
    (S.settings.graphLines ? '<span class="rv-lg"><i class="rv-sw a"></i>音量</span><span class="rv-lg"><i class="rv-sw c"></i>チャット</span><span class="rv-lg"><i class="rv-sw m"></i>コメント</span>' : '') +
    `<label class="rv-check"><input type="checkbox" id="rvGLines"${S.settings.graphLines ? ' checked' : ''}>材料ごとの線も表示</label>`;
  renderPlayhead();
}
function reasonTags(c){
  const cls = r => /音量|音声/.test(r) ? 'a' : /チャット/.test(r) ? 'c' : /コメント/.test(r) ? 'm' : '';
  const shown = c.reasons.map(r => `<span class="rv-rtag ${cls(r)}">${esc(r)}</span>`).join('');
  const p = c.parts || {};
  const detail = [['audio', '音量'], ['chat', 'チャット'], ['comments', 'コメント']].filter(([k]) => p[k] != null).map(([k, l]) => `${l} ${p[k]}`).join(' / ');
  return shown ? `<span class="rv-rtags" title="${esc(detail)}">${shown}</span>` : '';
}
function tfieldHTML(c, w, label){
  const k = (a, x) => `data-key="${esc(c.id)}|${a}|${x}"`;
  return `<div class="rv-tfield">
    <div class="rv-trow"><span class="rv-fl rv-tlab">${label}</span><span class="mono" data-f="${w}" data-ui-time="${Number(c[w]) || 0}" data-ui-time-tenths aria-label="${label}時刻" ${k('in', w)}></span>
      <button type="button" class="btn small" data-act="setnow" data-w="${w}" ${k('setnow', w)} title="現在の再生位置にする">現在位置</button></div>
    <div class="rv-trow rv-nudges" role="group" aria-label="${label}を微調整">
      ${[-5, -1, -0.5, 0.5, 1, 5].map(d => `<button type="button" class="btn small" data-act="nudge" data-w="${w}" data-d="${d}" ${k('nudge', w + (d < 0 ? '-' : '+') + Math.abs(d))} aria-label="${label}を${d < 0 ? '' : '+'}${d}秒">${d < 0 ? '−' : '＋'}${Math.abs(d)}</button>`).join('')}
    </div></div>`;
}
function markHTML(c){
  const auto = isAutoLike(c), st = statusOf(c), exp = st === 'exported', sel = S.sel === c.id, fold = isFolded(c.id);
  const sb = (v, label, title) => `<button type="button" class="btn small rv-stb ${v || 'cand'}" data-act="st" data-st="${v}" aria-pressed="${st === v}" title="${title}">${label}</button>`;
  return `<li class="rv-mark-row st-${esc(st || 'cand')}${sel ? ' sel' : ''}${auto ? ' auto' : ''}${fold ? ' folded' : ''}" data-id="${esc(c.id)}">
    <div class="rv-mh">
      <input type="checkbox" class="rv-join" data-act="join"${S.join.has(c.id) ? ' checked' : ''} aria-label="つなげて1本にする" title="つなげて1本にする(書き出しの欄の「つなげて1本に」)">
      <button type="button" class="rv-fold" data-act="fold" aria-expanded="${!fold}" aria-label="${fold ? '開く' : '折りたたむ'}" title="${fold ? '開く' : '折りたたむ'}"><span class="ui-caret${fold ? ' right' : ''}" aria-hidden="true"></span></button>
      <button type="button" class="btn small rv-play" data-act="play" aria-label="この範囲を再生(開始から終了まで)" title="この範囲を再生">${SVG.play}</button>
      <span class="rv-tc mono">${fmt(c.start)} – ${fmt(c.end)}</span><span class="rv-dur mono">${(c.end - c.start).toFixed(1)}s</span>
      ${c.src === 'auto' ? '<span class="rv-chip auto">自動</span>' : ''}${c.score != null ? `<span class="rv-chip score mono" title="自動判定の点数">${Number(c.score).toFixed(1)}点</span>` : ''}
      ${c.live && !(S.cur && S.cur.kind === 'live') ? '<span class="rv-chip live">ライブ</span>' : ''}
      ${exp ? '<span class="rv-chip st exported">書き出し済み</span>' : ''}${exp && c.archived ? `<span class="rv-chip arch" title="${ARCH_TITLE}">本番版</span>` : ''}
      ${fold && c.label ? `<span class="rv-lab-s" title="${esc(c.label)}">${esc(c.label)}</span>` : ''}
      <span class="rv-mact"><span class="rv-stgroup" role="group" aria-label="判定">${sb('adopted', '採用', exp ? '採用に戻す(書き出し済みの印を外して、もう一度書き出せるようにします)' : '採用(書き出し対象)')}${sb('rejected', '不採用', '不採用')}${sb('', '候補', '候補に戻す')}</span>
      ${Studio.token && (st === 'adopted' || exp) && !(S.cur && S.cur.kind === 'live') ? `<details class="ui-pop rv-rowmore"><summary class="btn small ghost icon" aria-label="その他の操作" title="その他の操作"><span class="ui-icon" data-icon="more"></span></summary><div class="ui-pop-body"><button type="button" data-act="auto1"><span>この後を <span class="ui-caret right" aria-hidden="true"></span> ${exp ? '(文字起こし → パック)' : '(書き出し → 文字起こし → パック)'}</span></button><span class="hint rv-autowhoinfo">${esc(autoWhoText())}</span></div></details>` : ''}
      <button type="button" class="btn small ghost rv-del" data-act="delete" title="このマークを削除" aria-label="このマークを削除">${SVG.x}</button></span>
    </div>
    <div class="rv-body"${fold ? ' hidden' : ''}>
      ${auto ? reasonTags(c) : ''}
      <div class="rv-times">${tfieldHTML(c, 'start', '開始')}${tfieldHTML(c, 'end', '終了')}</div>
      <div class="rv-labelrow"><input id="rvl-${esc(c.id)}" data-f="label" maxlength="120" value="${esc(c.label)}" aria-label="ラベル(書き出しのファイル名に使われます)" placeholder="ラベル(ファイル名に使われます) 例: 初見ボスで絶叫"></div>
      ${exp && c.file ? `<div class="rv-file hint">書き出し先: <span class="mono">${esc(c.file)}</span></div>` : ''}
      ${exp && c.file && typeof c.path === 'string' && isAbsPath(c.path) ? handoffHTML(null, { status: 'done', path: c.path }) + txHTML(c) : ''}
    </div>
  </li>`;
}
/* ---------- セリフ(書き出した切り抜きの文字起こしを、元の配信の時刻で)---------- */
function txHTML(c){
  const t = S.tx && S.cur && S.tx.vid === S.cur.id ? S.tx.marks[c.id] : null;
  if (!t) return '';
  const n = Number(t.segments) || 0, pf = Number(t.proofed) || 0;
  const note = t.offsetFrom === 'mark' ? '<div class="hint rv-tx-note">.clip.json が見つからないため、マークの開始に合わせています(高速書き出しの切り抜きは数秒ずれることがあります)</div>' : '';
  const lines = (t.lines || []).map(l => `<li><button type="button" class="rv-tx-line${l.cut ? ' cut' : ''}" data-act="txseek" data-t="${Number(l.start)}" data-e="${Number(l.end)}" title="${l.cut ? '文字起こしで「カット」にした行 ・ ' : ''}この行を再生"><span class="mono rv-tx-tc">${fmt(l.start)}</span>${l.speaker ? `<span class="rv-tx-spk">${esc(l.speaker)}</span>` : ''}<span class="rv-tx-text">${esc(l.text) || '(空の行)'}</span></button></li>`).join('');
  return `<details class="rv-tx ui-disclosure" data-tx="${esc(c.id)}"${S.txOpen.has(c.id) ? ' open' : ''}>
    <summary><b>セリフ</b> <span class="hint">${n}行 ・ 校正 ${pf}/${n}${t.others > 0 ? ' ・ 他に ' + Number(t.others) + ' 件の文字起こし(いちばん新しいものを表示)' : ''}</span></summary>
    ${note}<ol class="rv-tx-lines">${lines}</ol>${t.truncated ? '<div class="hint">長いため、最初の部分だけ表示しています</div>' : ''}
  </details>`;
}
async function loadTranscripts(){
  const v = S.cur; if (!v || !v.marks.some(m => m.status === 'exported' && m.path)){ if (S.tx && (!v || S.tx.vid !== v.id)) S.tx = null; return; }
  const seq = ++S.txSeq;
  let j; try { j = await Studio.api('/api/transcripts?id=' + enc(v.id)); } catch { return; }   // 読めなくても確認・書き出しは続けられる(セリフが出ないだけ)
  if (seq !== S.txSeq || S.cur !== v) return;
  const before = JSON.stringify(S.tx && S.tx.vid === v.id ? S.tx.marks : null);
  S.tx = { vid: v.id, marks: j.marks || {} };
  if (JSON.stringify(S.tx.marks) !== before) renderListKeep();
}
function renderList(){
  const ol = $('#rvList'); if (!ol) return;
  const list = listMarks();
  if (!S.cur || !marks().length){
    ol.innerHTML = `<li class="rv-emptylist empty"><b>まだマークはありません</b>配信を再生し、面白い場面で IN → OUT → 追加(または「今をマーク」)を押すと、ここに出ます。</li>`;
    return;
  }
  if (!list.length){
    ol.innerHTML = `<li class="rv-emptylist empty"><b>「${esc(STATUS_LABEL[S.filter] || S.filter)}」のマークはありません</b>上の「全部」で、すべてのマークを表示できます</li>`;
    return;
  }
  S.rendering = true;
  try { ol.innerHTML = list.map(markHTML).join(''); UIKit.timebox.attachAll(ol); } finally { S.rendering = false; }   // 時刻の欄(時:分:秒.0.1秒。数字だけで入れる。ui-kit v11)
  if (window.UIKit && UIKit.icon) UIKit.icon.fill(ol);   // 行の中の「…」の SVG(動的に描くので、読み込み後の一括の埋め込みには乗らない)
}
function renderStats(){
  const v = S.cur; if (!v){ return; }
  const cnt = { '': 0, adopted: 0, rejected: 0, exported: 0 }; let sum = 0;
  for (const m of v.marks){ cnt[statusOf(m)]++; if (m.status === 'adopted') sum += m.end - m.start; }
  $('#rvStats').textContent = `${v.marks.length}件 ・ 採用 ${cnt.adopted}件(合計 ${fmt(sum)})`;
  { const jm = $('#rvJumpMarks'); if (jm) jm.textContent = String(v.marks.length); }
  for (const b of document.querySelectorAll('#rvFilters [data-filter]')){
    const f = b.dataset.filter, n = f === 'all' ? v.marks.length : cnt[f];
    b.querySelector('.n').textContent = n; b.setAttribute('aria-pressed', String(S.filter === f));
  }
  $('#rvBulkAdopt').disabled = !cnt[''];
  renderExportUI();
}
function renderAll(){
  renderVideoSelect(); renderMeta(); renderDraft();
  if (S.cur){ renderTimeline(); renderStats(); renderList(); renderLiveCount(); }
  else renderExportUI();
  setSaveState('idle');
}
const WIDE = '(min-width:961px)';
function placeQuickBar(){
  const qb = $('#rvQuickbar'), cb = $('#rvClipbox'), lb = $('#rvLiveBar'), anchor = $('#rvMarkDetails'); if (!qb || !cb || !lb || !anchor) return;
  const wide = window.matchMedia(WIDE).matches, side = !!S.settings.theater && wide;
  if (side) cb.prepend(qb); else if (anchor.previousElementSibling !== qb) anchor.before(qb);
  /* LIVE の帯(ライブの録画の状態・停止・「マークしたらすぐ書き出す」・次にすることの案内。YouTube のライブ配信の帯も同じ):
     広い画面(シアター以外)は右の列のマークの一覧の上(プレーヤーの横・右の列は貼り付くのでスクロールしても見える)、それ以外は「今をマーク」の上。
     (2026-10-05 線 D の P3 の通しの確認: 「今をマーク」の下にあると、1440×900 でもスクロールしないと録画の状態・停止が見えなかった) */
  if (wide && !side){ if (cb.previousElementSibling !== lb) cb.before(lb); }
  else { const at = side ? anchor : qb; if (at.previousElementSibling !== lb) at.before(lb); }
}
/* 画面の中の移動(プレーヤー・マーク・書き出し)。広い画面では上の行の右端(書き出しへの入口だけ)、
   狭い画面では上の行の下に置いて、スクロールしても上に残す(ヘッダーの下に貼り付く) */
function placeJump(){
  const j = $('#rvJump'), top = $('#rvTop'); if (!j || !top) return;
  const wide = window.matchMedia(WIDE).matches;
  if (wide && j.parentElement !== top) top.insertBefore(j, $('#rvTheater'));
  else if (!wide && j.parentElement === top) top.after(j);
  j.classList.toggle('is-bar', !wide);
}
/* ---------- 書き出しの欄(ui-drawer)。1680px 以上は映像・マークと横に並ぶ「docked」(裏も操作できる。主な画面は右に空ける)、
   それより狭いときは重ねる「overlay」(閉じるまで畳んでおく) ---------- */
const WIDE_EXPORT = '(min-width:1680px)';   // 1440px では並べるとマークの一覧が細くなりすぎた(2026-09-27。以前は 1280px)
const exportDockActive = () => window.matchMedia(WIDE_EXPORT).matches;
const exportRunning = () => !!(S.job && S.job.running) || !!S.exportAll;
/* 主画面の余白(rv-dock)は、実際に欄が docked で開いているときだけ付ける(× で閉じている間は余白を残さない) */
function updateDockClass(){
  const el = $('#rvExport'), root = $('#rvRoot');
  if (root) root.classList.toggle('rv-dock', exportDockActive() && !!el && !!window.UIKit && UIKit.drawer.isOpen(el));
}
/* opts.focus:false は自動で開くとき(docked)にフォーカスを奪わないため。1680px 以上は docked(modal:false)、それより狭い重ねる表示は modal:true */
function openExportDrawer(opener, opts){
  const el = $('#rvExport'); if (!el || !window.UIKit) return;
  opts = opts || {};
  const wantModal = !exportDockActive();
  if (UIKit.drawer.isOpen(el)){
    if (S.expModal !== wantModal){ UIKit.drawer.close(el); UIKit.drawer.open(el, { modal: wantModal, opener, focus: opts.focus }); S.expModal = wantModal; }
  } else {
    UIKit.drawer.open(el, { modal: wantModal, opener, focus: opts.focus }); S.expModal = wantModal;
  }
  S.expDockClosed = false;
  updateDockClass();
}
/* userClosed: ユーザーが × を押して閉じたか。true のときは、次に配信を開き直すか自分で開くまで、docked でも自動では開き直さない */
function closeExportDrawer(userClosed){
  const el = $('#rvExport'); if (!el || !window.UIKit) return;
  if (UIKit.drawer.isOpen(el)) UIKit.drawer.close(el);
  if (userClosed) S.expDockClosed = true;
  updateDockClass();
}
/* 呼ぶのは「①メディアクエリが変わったとき」と「②配信を開いた・閉じたとき」だけ(採用・不採用・書き出しの進み具合のたびに呼ぶと、
   閉じたばかりの欄が開き直ってフォーカスを奪ったり、書き出し中に欄が閉じたりしていた)。
   1680px 以上: 閉じたと覚えていなければ、いつも見える場所として開いておく(focus:false)。
   それより狭い: 自動で開けていた(docked)ぶんは重ねる表示をやめて畳む。書き出し中は、進み具合を見失わないよう畳まない */
function syncExportDock(){
  const el = $('#rvExport'); if (!el || !window.UIKit) return;
  const wide = exportDockActive();
  if (wide){
    if (S.cur && !S.expDockClosed) openExportDrawer(null, { focus: false }); else updateDockClass();
  } else if (UIKit.drawer.isOpen(el) && !exportRunning()){
    closeExportDrawer();
  } else updateDockClass();
}
function jumpTo(where){
  if (where === 'export'){ openExportDrawer($('#rvJump [data-jump="export"]')); return; }
  const target = { player: '#rvPlayerBox', marks: '#rvClipbox' }[where];
  const el = target && $(target); if (!el || $('#rvMain').hidden) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function applyTheater(){
  const on = !!S.settings.theater;
  $('#rvMain').classList.toggle('theater', on);
  $('#rvRoot').classList.toggle('theater-wide', on);
  placeQuickBar();
  const b = $('#rvTheater'); b.setAttribute('aria-pressed', String(on)); b.querySelector('span').textContent = on ? '通常表示' : 'シアター';
}
function toggleTheater(){ S.settings.theater = !S.settings.theater; applyTheater(); touchSettings(); }

/* ---------- 共通の再生キー(UIKit.keys.playback。全ツール共通の意味にそろえる: IMPLEMENTATION.md 4) ----------
   yt(YouTube IFrame API 風。currentTime 等のプロパティを持たない)を、HTMLMediaElement 風の形に合わせるだけの薄い適合 */
const rvMedia = {
  get currentTime(){ return S.now; }, set currentTime(t){ seek(Number(t) || 0); },
  get duration(){ return S.duration; },
  get paused(){ return !(yt && S.playerState === 1); },
  get playbackRate(){ return S.rate; }, set playbackRate(r){ S.rate = r; if (yt) try { yt.setPlaybackRate(r); } catch {} },
  play(){ if (canPlay()) try { yt.playVideo(); } catch {} },
  pause(){ if (yt) try { yt.pauseVideo(); } catch {} }
};
/* I/O は markIn/markOut を呼ぶ(キー配置で別のキーを割り当てていても、共通キーとしてはこれが優先。「操作の設定」に注記あり)。
   media は yt が無くても常に rvMedia を返す(rvMedia の各操作が yt の有無を自分で見るので、プレーヤーが無い間も S.now は , . ← → で動かせる)。
   再生できない画面(埋め込み不可・通信不調)で Space・L(再生を試みるキー)を押したときだけ、これまでどおり案内を出す */
const handlePlayback = window.UIKit && UIKit.keys ? UIKit.keys.playback({
  media: () => rvMedia, keymap: () => curKeymap(),   // 割り当ては共通(ホームの設定。? の一覧で変えられる。段6)
  onIn: () => markIn(), onOut: () => markOut(),
  onKey: (name, act) => {
    if (!canPlay() && (act === 'playPause' || act === 'play')) noPlayerToast();
    if (act === 'stop' || act === 'play'){ const r = $('#rvRate'); if (r) r.value = String(S.rate); }   // 止める・再生は再生速度を変えるので、速度の選択も合わせる
  }
}) : null;
/* キーの帯(下の細い帯)の中身。③ の場面(配信を開いている間)に合わせて置き換える */
function keybarScene(){
  if (!window.UIKit || !UIKit.keybar) return;
  const km = curKeymap(), t = id => (km[id] ? keyText(km[id]) : ''), row = (k, label) => (k ? { k, l: label } : null);   // 今の割り当てから(固定の文字をなくす。段6)
  UIKit.keybar.set([row(t('playPause'), '再生/停止'), row([t('seekBack'), t('seekFwd')].filter(Boolean).join(' '), '1秒(Shift 5秒)'), row([t('markIn'), t('markOut')].filter(Boolean).join(' / '), '始まり/終わりの印'),
    row(t('adopt'), '採用'), row(t('reject'), '不採用'), row(t('nextMark'), '次のマーク'), { k: '?', l: 'キー操作' }].filter(Boolean));
}

/* ---------- イベント ---------- */
function wire(){
  const list = $('#rvList');
  /* マークを選ぶ(タイムラインと一覧の行の印だけ。一覧は描き直さない) */
  const markSel = id => { S.sel = id; renderTimeline(); list.querySelectorAll('.rv-mark-row').forEach(x => x.classList.toggle('sel', x.dataset.id === id)); };
  list.addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const li = b.closest('.rv-mark-row'); const c = li && marks().find(x => x.id === li.dataset.id); if (!c) return;
    const key = b.dataset.key || '';
    switch (b.dataset.act){
      case 'play': markSel(c.id); previewClip(c); break;
      case 'fold': S.fold.set(c.id, !isFolded(c.id)); renderListKeep(); break;
      case 'join': if (b.checked) S.join.add(c.id); else S.join.delete(c.id); renderExportUI(); break;
      case 'txseek': {   // セリフの行を押したら、その行だけ再生する(元の配信の時刻)
        const t = Number(b.dataset.t), e2 = Number(b.dataset.e);
        if (!Number.isFinite(t)) break;
        if (!canPlay()){ seek(t); noPlayerToast(); break; }
        seek(t); S.previewEnd = Number.isFinite(e2) && e2 > t ? e2 : null; yt.playVideo(); break; }
      case 'st': setStatus(c, b.dataset.st, b.dataset.st === 'adopted' || b.dataset.st === 'rejected'); break;
      case 'auto1': { const pop = b.closest('details.ui-pop'); if (pop) pop.open = false; startAuto('adopted', [c.id]); break; }   // このマークだけ、残りの作業をまとめて(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 3)
      case 'nudge': {
        const w = b.dataset.w;
        if (setBound(c, w, c[w] + Number(b.dataset.d))){ if (yt) seek(c[w]); refresh(key); }
        break; }
      case 'setnow': if (setBound(c, b.dataset.w, S.now)) refresh(key); break;
      case 'delete': armDelete(b, () => {
        S.cur.marks = S.cur.marks.filter(x => x.id !== c.id); S.fold.delete(c.id); if (S.sel === c.id) S.sel = null;
        markDirty(); refresh(); renderMeta(); toast('マークを削除しました');
      }); break;
    }
  });
  list.addEventListener('toggle', e => {   // セリフの開閉を覚える(一覧を描き直しても閉じない)。toggle は泡立たないので capture で受ける
    const d = e.target; if (!d.classList || !d.classList.contains('rv-tx')) return;
    if (d.open) S.txOpen.add(d.dataset.tx); else S.txOpen.delete(d.dataset.tx);
  }, true);
  list.addEventListener('click', e => { // 行のどこかを押したら選択(タイムラインと連動)
    const li = e.target.closest('.rv-mark-row'); if (!li || e.target.closest('input,button,label')) return;
    markSel(li.dataset.id);
  });
  /* B-11: 微調整のボタンは選んだマークにだけ出す。時刻・ラベルの欄に入ったら(Tab でも)そのマークを選ぶ */
  list.addEventListener('focusin', e => {
    const li = e.target.closest('.rv-mark-row'); if (!li || li.classList.contains('sel') || !e.target.closest('input, .ui-time') || e.target.classList.contains('rv-join')) return;   // つなぐのチェックでは選ばない(選び直すと上の行の微調整が畳まれて一覧がずれ、押したつもりが外れる)
    markSel(li.dataset.id);
  });
  list.addEventListener('input', e => {
    if (e.target.dataset.f !== 'label') return;
    const c = marks().find(x => x.id === e.target.closest('.rv-mark-row').dataset.id); if (!c) return;
    c.label = e.target.value; markDirty();
  });
  /* 開始・終了の時刻の欄(UIKit.timebox)を直した: Enter か欄を離れたときに確定(ui-time-commit = 入力欄の change に当たる) */
  list.addEventListener('ui-time-commit', e => {
    if (S.rendering) return; // 再描画で欄が外れるときに出る blur 由来の確定は無視
    const f = e.target.dataset.f;
    const li = e.target.closest('.rv-mark-row'); const c = li && marks().find(x => x.id === li.dataset.id); if (!c) return;
    if (f !== 'start' && f !== 'end') return;
    const t = e.detail.value;
    if (t === null){ toast('時刻を空にはできません(元の時刻に戻しました)'); UIKit.timebox.set(e.target, c[f]); return; }
    if (!setBound(c, f, t)){ UIKit.timebox.set(e.target, c[f]); return; }
    /* 描き直したあとのフォーカス: Enter ならこの欄のまま。欄を離れて確定したときは、移った先(開始 → Tab → 終了 と続けて打てるように。一覧の外なら奪い返さない) */
    const to = e.detail.to, key = to && to.getAttribute ? to.getAttribute('data-key') : null;
    refresh(e.detail.via === 'blur' ? key : c.id + '|in|' + f);
  });
  list.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const f = e.target.dataset && e.target.dataset.f;
    if (f === 'label'){ e.preventDefault(); e.target.blur(); }
  });

  // タイムライン(クリックで移動・ドラッグでスクラブ・区間は選択)と、グラフ上のクリック
  const tl = $('#rvTl'); let drag = null;
  const timeAt = (e, el) => { const r = el.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * totalDur(); };
  function selectSeg(seg){
    const c = marks().find(x => x.id === seg.dataset.id); if (!c) return;
    markSel(c.id);
    const li = list.querySelector(`.rv-mark-row[data-id="${CSS.escape(c.id)}"]`); if (li) li.scrollIntoView({ block: 'nearest' });
  }
  tl.addEventListener('pointerdown', e => {
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    const seg = e.target.closest('.rv-seg');
    drag = { id: e.pointerId, x0: e.clientX, moved: false, seg };
    try { tl.setPointerCapture(e.pointerId); } catch {}
    tl.classList.add('dragging');
    if (!seg) seek(timeAt(e, tl), false);
  });
  tl.addEventListener('pointermove', e => {
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.moved && Math.abs(e.clientX - drag.x0) < 4) return;
    drag.moved = true; seek(timeAt(e, tl), false);
  });
  const end = e => {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag; drag = null; tl.classList.remove('dragging');
    if (e.type === 'pointercancel') return;
    if (d.seg && !d.moved) selectSeg(d.seg); else seek(timeAt(e, tl));
  };
  tl.addEventListener('pointerup', end); tl.addEventListener('pointercancel', end);
  $('#rvGraph').addEventListener('click', e => {
    const p = e.target.closest('.rv-gpeak');   // 山の札: その山の少し前へ(順位と理由。docs/design/edit-tool-design.md 系ではなく IMPLEMENTATION.md 4)
    if (p){ seek(Math.max(0, Number(p.dataset.t) - 5)); return; }
    seek(timeAt(e, $('#rvGraph')));
  });
  /* マウスの位置の時刻(押すとそこへ移る、の手がかり)。山の札の上では出さない */
  const gHover = $('#rvGHover');
  $('#rvGraph').addEventListener('pointermove', e => {
    if (e.pointerType === 'touch' || e.target.closest('.rv-gpeak')){ gHover.hidden = true; return; }
    const r = $('#rvGraph').getBoundingClientRect(), f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    gHover.hidden = false; gHover.style.left = (f * 100).toFixed(2) + '%';
    gHover.classList.toggle('flip', f > 0.9);   // 右の端では文字を線の左へ
    gHover.firstChild.textContent = tickLabel(f * totalDur());
  });
  $('#rvGraph').addEventListener('pointerleave', () => { gHover.hidden = true; });
  /* 幅が変わったら描き直す(目盛りの間隔と札の段は幅で決まる。見えていなかった ③ を開いたときも) */
  if (window.ResizeObserver){
    let gw = 0;
    new ResizeObserver(() => { const w = $('#rvGraph').clientWidth; if (w && Math.abs(w - gw) > 1){ gw = w; renderGraph(); } }).observe($('#rvGraph'));
  }
  $('#rvGLegend').addEventListener('change', e => { if (e.target.id === 'rvGLines'){ S.settings.graphLines = e.target.checked; renderGraph(); touchSettings(); } });

  // 配信の選択・開く・保存
  const pick = $('#rvPick'), plist = $('#rvPickList');
  pick.addEventListener('toggle', () => {
    if (pick.open){ PK.limit = 80; renderPickList(); setTimeout(() => { if (pick.open && !pick.contains(document.activeElement)) $('#rvPickQ').focus(); }, 0); }
    else if (pick.contains(document.activeElement)) $('#rvPickBtn').focus({ preventScroll: true });   // Esc で閉じたとき、隠れた入力欄にフォーカスが残ってキー操作が効かなくならないように
  });
  $('#rvVMenu').addEventListener('toggle', e => { const m = e.currentTarget; if (!m.open && m.contains(document.activeElement)) m.querySelector('summary').focus({ preventScroll: true }); });
  let pqT = null;
  $('#rvPickQ').addEventListener('input', e => { PK.q = e.target.value; PK.limit = 80; clearTimeout(pqT); pqT = setTimeout(renderPickList, 100); });
  $('#rvPickF').addEventListener('change', e => { PK.f = e.target.value; PK.limit = 80; renderPickList(); });
  $('#rvPickSort').addEventListener('change', e => { PK.sort = e.target.value === 'channel' ? 'channel' : 'recent'; renderPickList(); });
  plist.addEventListener('click', e => {
    if (e.target.closest('[data-pick-more]')){ PK.limit += 200; renderPickList(); return; }
    const hb = e.target.closest('[data-hide-vid]');
    if (hb){
      e.stopPropagation();   // 描き直しで押した行が DOM から外れると、ui-kit の「外側のクリックで閉じる」が外側と見なして一覧を閉じるため
      const hv = S.videos.find(x => x.id === hb.dataset.hideVid);
      HIDE.set('videos', [hb.dataset.hideVid], hb.dataset.hideOn === '1', { label: hv ? vLabel(hv) : hb.dataset.hideVid }).catch(() => {});
      return;
    }
    const r = e.target.closest('.rv-prow'); if (!r) return;
    pick.open = false; $('#rvPickBtn').focus({ preventScroll: true });
    if (!S.cur || r.dataset.vid !== S.cur.id) loadVideo(r.dataset.vid);
  });
  /* 一覧の中は ↑ ↓ で移動、探す欄から ↓ で一覧へ */
  pick.addEventListener('keydown', e => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const rows = [...plist.querySelectorAll('.rv-prow')].filter(x => x.offsetParent !== null); if (!rows.length) return;
    const i = rows.indexOf(document.activeElement);
    if (e.target.id === 'rvPickQ' && e.key === 'ArrowDown'){ e.preventDefault(); rows[0].focus(); return; }
    if (i < 0) return;
    e.preventDefault();
    if (e.key === 'ArrowUp' && i === 0) $('#rvPickQ').focus(); else rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))].focus();
  });
  $('#rvEmptyOpen').addEventListener('click', () => openPicker(!S.videos.length));
  /* 空の状態から ① 探す・② 解析へ(S-13)。② は URL の欄へフォーカス */
  $('#rvEmpty').addEventListener('click', e => {
    const b = e.target.closest('[data-go-step]'); if (!b) return;
    Studio.go(b.dataset.goStep);
    const f = b.dataset.goStep === 'queue' ? $('#qUrls') : null; if (f) f.focus();
  });
  $('#rvJump').addEventListener('click', e => { const b = e.target.closest('[data-jump]'); if (b) jumpTo(b.dataset.jump); });
  /* YouTube で開くリンクは、押したときの再生位置から */
  const ytNow = a => { if (S.cur && S.cur.kind === 'youtube') a.href = `https://www.youtube.com/watch?v=${enc(S.cur.id)}${S.now >= 1 ? '&t=' + Math.floor(S.now) + 's' : ''}`; };
  $('#rvNotice').addEventListener('click', e => {
    if (e.target.closest('[data-act="ytretry"]')){ mountPlayer(); return; }
    const a = e.target.closest('a[data-yt-now]'); if (a) ytNow(a);
  });
  $('#rvYtLink').addEventListener('click', e => ytNow(e.currentTarget));
  $('#rvOpenForm').addEventListener('submit', e => { e.preventDefault(); openFromInput(); });
  $('#rvSave').addEventListener('click', () => { if (S.dirty || saveP) save(); });
  $('#rvTitle').addEventListener('input', e => {
    if (!S.cur) return; S.cur.title = e.target.value; markDirty();
    const el = $('#rvCurLabel'); el.classList.toggle('is-empty', !S.cur.title); el.textContent = S.cur.title || '(名前なし)';
  });
  $('#rvTitle').addEventListener('change', () => { renderVideoSelect(); });
  $('#rvTitle').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); $('#rvVMenu').open = false; } });
  $('#rvDelVideo').addEventListener('click', e => armDelete(e.currentTarget, deleteCurrentVideo));
  const runAnalyze = async () => {
    const v = S.cur; if (!v || v.kind !== 'youtube') return;
    if (typeof Studio.enqueue !== 'function') return toast('解析画面がまだ読み込まれていません');
    try { await flushSave(); } catch (e){ toast(e.message); return; }
    Studio.enqueue([{ kind: 'youtube', videoId: v.id, title: v.title || '', channel: v.channel || '' }]);
  };
  $('#rvAnalyze').addEventListener('click', e => {
    if (S.cur && S.cur.marks.length) armDelete(e.currentTarget, runAnalyze, 'もう一度押すと再解析します(手を加えていない自動マークは置き換わります)');
    else runAnalyze();
  });

  // 再生まわり
  $('#rvIn').addEventListener('click', markIn);
  $('#rvOut').addEventListener('click', markOut);
  $('#rvAdd').addEventListener('click', addClip);
  $('#rvToggle').addEventListener('click', togglePlay);
  document.querySelectorAll('#rvRoot [data-seek]').forEach(b => b.addEventListener('click', () => seek(S.now + Number(b.dataset.seek))));
  $('#rvRate').addEventListener('change', e => { S.rate = Number(e.target.value); if (yt) yt.setPlaybackRate(S.rate); });
  $('#rvNow').addEventListener('change', e => {
    const t = parseTime(e.target.value);
    if (Number.isNaN(t)){ toast('時刻の形式が正しくありません(例: 1:23.5 または 5025)'); e.target.value = fmt(S.now); return; }
    seek(t); e.target.value = fmt(S.now);
  });
  $('#rvNow').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); e.target.dispatchEvent(new Event('change')); e.target.blur(); } });
  $('#rvQuickSlots').addEventListener('click', e => { const b = e.target.closest('.rv-qslot > button[data-slot]'); if (b) quickMark(Number(b.dataset.slot)); });
  $('#rvQuickSlots').addEventListener('click', onSpanStep);
  $('#rvMomBtn').addEventListener('click', momentMark);
  $('#rvMomBefore').addEventListener('change', e => setMomentSec('momentBefore', e.target));
  $('#rvMomAfter').addEventListener('change', e => setMomentSec('momentAfter', e.target));
  renderMomentSet();
  /* キー配置は ? の一覧の1か所(2026-10-04。以前は ③ の「操作の設定」にも同じ一覧があった)。組み合わせの選択も一覧の上(index.html の #keyPresetRow) */
  $('#rvKeysOpen').addEventListener('click', () => Studio.openKeyHelp());
  $('#keyPresetRow').hidden = false;
  $('#rvKeyPreset').addEventListener('change', e => {
    const pr = KEY_PRESETS[e.target.value]; if (!pr) return;
    if (KM) KM.setMany(sanitizeKeymap(pr), `キー配置を「${PRESET_NAMES[e.target.value]}」にしました`);
    else { S.settings.keymap = sanitizeKeymap(pr); renderKeyUI(); touchSettings(); }
  });
  $('#rvEdge').addEventListener('click', () => { if (yt && yt.goLive) yt.goLive(); else if (yt && S.duration) seek(S.duration); });   // ライブの録画はライブ端の少し手前へ(終わりちょうどだと読み込みを待ち続ける)
  $('#rvRecStop').addEventListener('click', e => stopLiveRec(e.currentTarget));
  $('#rvArchRun').addEventListener('click', startLiveArchive);
  $('#rvArchCancel').addEventListener('click', cancelLiveArchive);
  Studio.on('liveprefs', d => {   // 設定の引き出しで「自動で本番版に」「録画を消す」を変えた
    if (d && typeof d.autoArchive === 'boolean'){ LV.autoArchive = d.autoArchive; renderLiveRec(); }
    if (d && typeof d.autoDelete === 'boolean'){ LV.autoDelete = d.autoDelete; renderLiveRec(); }
  });
  $('#rvAutoExp').addEventListener('change', e => { S.settings.liveAutoExport = e.target.checked; touchSettings(); renderLiveRec(); });
  $('#rvAfter').addEventListener('change', e => { S.settings.liveAfter = LIVE_AFTERS.includes(e.target.value) ? e.target.value : 'check'; touchSettings(); });
  $('#rvDuck').addEventListener('change', e => { S.settings.liveDuck = ['low', 'mute', 'off'].includes(e.target.value) ? e.target.value : 'low'; applyToPlayer(); touchSettings(); });
  if (window.UIKit && UIKit.sound) UIKit.sound.onChange(() => applyToPlayer());   // ほかの窓の再生が始まった・止まった
  $('#rvShift').addEventListener('click', () => {
    if (!S.cur) return;
    const d = Number($('#rvShiftSec').value);
    if (!Number.isFinite(d) || d === 0) return toast('ずらす秒数を入力してください(例: -12)');
    const targets = marks().filter(c => c.live);
    if (!targets.length) return toast('ライブ中に打ったマークがありません');
    let n = 0;
    for (const c of targets){
      const len = c.end - c.start, ns = Math.max(0, round1(c.start + d)), r = checkRange(ns, ns + len);
      if (typeof r === 'string' || Math.abs((r[1] - r[0]) - len) > 0.15) continue; // 範囲外になるものはずらさない
      c.start = r[0]; c.end = r[1]; n++;
      if (c.status === 'exported'){ c.status = 'adopted'; c.file = ''; c.path = ''; c.archived = false; }
    }
    if (!n) return toast('配信の範囲外になるため、ずらせませんでした');
    markDirty(); refresh(); toast(`${n}件を ${d > 0 ? '+' : ''}${d}秒ずらしました` + (n < targets.length ? `(範囲外の${targets.length - n}件は除く)` : ''));
  });
  $('#rvTheater').addEventListener('click', toggleTheater);
  $('#rvPlayerBox').addEventListener('mouseleave', reclaimFocus);
  $('#rvFilters').addEventListener('click', e => { const b = e.target.closest('[data-filter]'); if (!b) return; S.filter = b.dataset.filter; renderStats(); renderList(); });
  $('#rvFoldAll').addEventListener('click', () => foldAll(true));
  $('#rvUnfoldAll').addEventListener('click', () => foldAll(false));
  $('#rvBulkAdopt').addEventListener('click', bulkAdopt);
  $('#rvExpAll').addEventListener('click', startExportAll);
  $('#rvOutEdit').addEventListener('click', () => Studio.openSettings('setOut'));
  const onCopy = async e => {   // 書き出しの一覧と、書き出し済みのマークの行の「パスをコピー」
    const b = e.target.closest('[data-act="copy"]'); if (!b) return;
    e.stopPropagation();
    const ok = await copyText(b.dataset.path);
    Studio.toast(ok ? 'パスをコピーしました: ' + b.dataset.path : 'コピーできませんでした。パス: ' + b.dataset.path, 0, ok ? 'ok' : 'err');
  };
  $('#rvExpList').addEventListener('click', onCopy);
  $('#rvExpList').addEventListener('click', e => {   // 「編集で開く」: 知らせの [編集で開く] と同じ開き方(openEditor)。Ctrl・Shift・中クリックはブラウザ(と ui-kit)に任せる
    const a = e.target.closest('a[data-edit-open]'); if (!a || e.button !== 0 || e.ctrlKey || e.shiftKey || e.metaKey || e.altKey) return;
    e.preventDefault(); openEditor(a.href);
  });
  $('#rvExpList').addEventListener('click', async e => {   // ライブの録画の書き出し(入口のジョブ)を取り消す
    const b = e.target.closest('[data-act="lxcancel"]'); if (!b || b.disabled || !b.dataset.job) return;
    b.disabled = true;
    try { await Studio.live.api('api/export/cancel', { body: { id: b.dataset.job } }); toast('書き出しを取り消しました(マークは採用のままです)', 3000); }
    catch (er){ toast('取り消せませんでした: ' + er.message, 0, 'err'); b.disabled = false; }
    pollLiveJobs();
  });
  $('#rvList').addEventListener('click', onCopy);
  Studio.on('ports', () => { if (S.lastJob) renderJob(S.lastJob); if (S.cur) renderList(); });   // 他のツールの実際のポートが分かったら、リンクを作り直す
  window.matchMedia(WIDE).addEventListener('change', () => { placeQuickBar(); placeJump(); });
  window.matchMedia(WIDE_EXPORT).addEventListener('change', syncExportDock);
  $('#rvExpClose').addEventListener('click', () => closeExportDrawer(true));
  $('#rvExpMore').addEventListener('click', e => { if (e.target.closest('button[id]')) $('#rvExpMore').open = false; });   // 「…」の中を押したら閉じる

  // 書き出し
  $('#rvExpRun').addEventListener('click', () => startExport());
  $('#rvJoinRun').addEventListener('click', startJoin);
  $('#rvExpRetry').addEventListener('click', () => { const ids = failedIds(); if (ids.size) startExport(ids); });
  $('#rvExpCancel').addEventListener('click', async () => {
    if (S.exportAll) S.exportAll.cancel = true;
    if (!S.job || !S.job.running) return;
    try { await Studio.api('/api/export/cancel', { method: 'POST', body: { id: S.job.id } }); } catch (e){ toast(e.message); }
  });

  // キーボードショートカット(このステップが表示されているときだけ)
  document.addEventListener('keydown', e => {
    if (Studio.step !== 'review' || !S.cur) return;
    if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented || e.isComposing || e.keyCode === 229) return;   // 日本語の変換中は受け取らない
    if (Studio.overlayOpen && Studio.overlayOpen()) return;   // 設定の引き出し・キー一覧を開いている間は、裏の配信を操作しない
    /* 書き出しの欄: 重ねて開いている(1680px 未満)間と、欄の中にフォーカスがある間は、裏の配信を操作しない(B-2。→ で裏の再生位置が動いていた)。
       1680px 以上で横に並べている(docked)ときは、欄の外ではこれまでどおり効く */
    { const ex = $('#rvExport'); if (ex && window.UIKit && UIKit.drawer.isOpen(ex) && (S.expModal || ex.contains(e.target))) return; }
    if (Studio.inMenu && Studio.inMenu(e.target)) return;      // 配信の選択・配信の操作のメニューの中では、そのメニューの操作を優先する
    const tag = e.target.tagName;
    if (Studio.isTyping ? Studio.isTyping(e.target) : (tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable || (tag === 'INPUT' && !['checkbox', 'radio', 'button'].includes(e.target.type)))) return; // 文字入力中はショートカットを無効化(チェックボックス上では有効。スライダーの上ではキーをスライダーに譲る)
    // ボタン・リンク・開閉の見出しの上では、Space / Enter はその部品の操作を優先する(Space で「操作の設定」を開けなかったのを修正)
    const onControl = tag === 'BUTTON' || tag === 'INPUT' || tag === 'SUMMARY' || tag === 'A';
    // 押しっぱなしの Space で再生・停止を連打しないように、繰り返しのキー入力(e.repeat)は無視する(スクロールなどの既定の動きも止める)
    if (e.repeat && (e.key === ' ' || e.key === 'Spacebar')){ e.preventDefault(); return; }
    // 共通の再生キー(全ツール共通。Space・J/K/L・← →(±1秒/Shift ±5秒)・,/.・I/O)を先に。処理したら(true)ここで終わる
    if (handlePlayback && handlePlayback(e)) return;
    const combo = comboOf(e); if (!combo) return;
    const hit = KM ? KM.actionOf(combo) : (ACTION_DEFS.find(([id]) => S.settings.keymap[id] === combo) || [])[0];
    if (hit && !(combo === 'Space' && onControl)){
      e.preventDefault();
      if (e.repeat && !['volUp', 'volDown'].includes(hit)) return; // 押しっぱなしでマークが連続作成されないように
      ACTION_FN[hit](); return;
    }
  });
}

/* ---------- ステップの表示・非表示 ---------- */
async function activate(){
  startPoll();
  keybarScene();
  liveResume();   // ライブの録画の状態の見回り(③ を離れている間は止めている)
  await refreshList();
  if (Studio.step !== 'review') return;
  if (!S.cur && !S.loadSeq){
    if (S.videos.length) await loadVideo(S.videos[0].id); else renderAll();
  } else if (S.cur) syncFromServer();
}
function deactivate(){
  pausePlayback(); stopPoll(); liveStopPoll();   // ③ を離れたら再生を止める(ライブの録画も。録画そのものは裏で続く)
  placeFlush();   // 前回の場所(S-8)をすぐ書く
  if (window.UIKit && UIKit.keybar) UIKit.keybar.clear();
  if (setTimer) saveSettings();
  if (S.dirty || saveTimer) save();
}

/* ---------- 起動 ---------- */
Studio.review = {
  setYtReadyMs(ms){ S.ytReadyMs = ms; },   // テスト用: プレーヤー準備の待ち時間(既定 20 秒)を短くする
  async open(id){
    const p = loadVideo(String(id));   // 先に loadSeq を進める(ステップ表示時の自動読み込みと競合させない)
    Studio.go('review');
    return p;
  },
  refresh: refreshList,
  keymap: KM,   // キーの一覧(? の一覧も同じ部品を出す。core.js)
  /* 書き出しのあと自動で文字起こし(設定の「書き出し」節のスイッチ。settings.js)。値は review の節(サーバー)の autoTx */
  autoTx: () => S.settings.autoTx !== false,
  setAutoTx(on){ S.settings.autoTx = !!on; touchSettings(); }
};
/* ---------- まとめて実行(docs/design/edit-tool-design.md の 12 ⑦(a)。入口の /api/autorun。案件の画面と同じ API・同じ形。入口の中だけ) ---------- */
const AUTO = { t: 0, active: false };
const AUTO_STATE = { queued: ['wait', '順番待ち'], running: ['run', '実行中'], done: ['ok', '完了'], error: ['err', '止まりました'], cancelled: ['wait', '中止'] };
const AUTO_STEP = { wait: '待ち', run: '実行中', done: '済', skip: '飛ばした', warn: '一部', error: '失敗' };
/* 入口の API(/api/...)。① 探す のまとめて実行と同じ core.js の Studio.portalApi */
const portalApi = (path, body) => Studio.portalApi(path, body);
/* ---------- 書き出しのあと自動で文字起こし(入口から開いたときだけ。設定「書き出しのあと自動で文字起こし」既定オン。IMPLEMENTATION.md 4) ----------
   入口の /api/autorun/start を mode:'transcribe' + marks(書き出したものだけ)で呼ぶ。もう書き出し済みのマークは、その段だけ飛ばして続く(home/autorun.py _step_export で確認済み) */
function autoTxEnabled(){ return S.settings.autoTx !== false; }
/* 0.21 までの保存(このブラウザの localStorage の ytt:studio.autoTx)→ true / false / null(無い)。サーバーの設定に autoTx が無いときだけ読む(消さない) */
function autoTxLegacy(){ try { const x = localStorage.getItem('ytt:studio.autoTx'); return x === '0' ? false : x === '1' ? true : null; } catch { return null; } }
async function maybeAutoTranscribe(videoId, markIds){
  if (!Studio.token || !autoTxEnabled() || !markIds || !markIds.length) return;
  try {
    const r = await portalApi('api/autorun/start', { id: videoId, mode: 'transcribe', marks: markIds });
    if (r && r.run && window.UIKit && UIKit.autorun) UIKit.autorun.watch(r.run.id);   // 終わったら知らせる(段4)
    toast('書き出しに続けて、文字起こしを始めました', 4000, 'ok');
    if (S.cur && S.cur.id === videoId) pollAuto();
  } catch (e){
    // 「この配信はすでに実行中・順番待ちです」(同じ配信のまとめて実行が別に動いている)だけを見分ける。
    // 「順番待ちが多すぎます」(容量の上限)は別の理由の失敗なので、ここに含めて info 扱いにしない(以前は同じ正規表現が両方に一致して誤報していた)
    if (/実行中・順番待ちです/.test(e.message || '')) toast('この配信はすでに別のまとめて実行が動いています。終わってから「この後を」でやり直せます', 7000, 'info');
    else toast('文字起こしを自動では始められませんでした: ' + e.message, 7000, 'err');
  }
}
/* まとめて実行(③ のメニュー・マークの行の「この後を」)。見積もり → 始める → 終わったら知らせる、は共通の部品 UIKit.autorun(どの入口も同じ。段4)。
   採用数・上書き・失敗したときはホームの設定(どの入口で変えても同じ) */
/* マークの行の「この後を」: 実行する前に字幕の色(③ のまとめて実行の配信者の欄の名前)を見せる(S-10。以前は閉じたメニューの欄を黙って使っていた) */
function autoWhoText(){ const el = document.getElementById('rvAutoWho'), v = el ? el.value.trim() : ''; return '字幕の色: ' + (v || 'なし(黒い文字)'); }
function fillAutoWho(){
  if (window.UIKit && UIKit.streamer && UIKit.streamer.autoFill && Studio.token && S.cur) UIKit.streamer.autoFill($('#rvAutoWho'), { videoId: S.cur.id, channel: S.cur.channel || '' });
}
async function startAuto(mode, marks){
  if (!S.cur) return;
  const top = Math.min(20, Math.max(1, Math.round(Number($('#rvAutoTop').value) || 3)));
  try {
    if (S.dirty) await flushSave();   // 手で付けたマークを先に保存してから(まとめて実行は保存済みのマークを読む)
    const who = window.UIKit && UIKit.streamer && UIKit.streamer.check ? await UIKit.streamer.check($('#rvAutoWho')) : $('#rvAutoWho').value.trim();
    if (who === null) return;   // 見つからない名前で「やめる」を選んだ(S-20)
    const ar = window.UIKit && UIKit.autorun, st = ar ? ar.state() : null;
    const body = { id: S.cur.id, mode, ...(mode === 'full' ? { top } : {}), streamer: who, ...(marks ? { marks } : {}), overwrite: !!(st && st.overwrite) };   // 空 = 色なし(欄は自動で入る)
    const r = ar ? await ar.start('api/autorun/start', body, { id: body.id, mode, marks: marks || null, top: body.top, overwrite: body.overwrite })
      : await portalApi('api/autorun/start', body);
    if (!r) return;   // やることが無い(見積もり。知らせは部品が出す)
    $('#rvAuto').open = false;
    pollAuto();
  } catch (e){ toast('まとめて実行を始められませんでした: ' + e.message, 7000, 'err'); }
}
async function pollAuto(){
  clearTimeout(AUTO.t);
  const bar = $('#rvAutoBar');
  if (!Studio.token || !S.cur || !bar){ if (bar) bar.hidden = true; return; }
  const vid = S.cur.id;
  let runs;
  try { runs = (await portalApi('api/autorun')).runs || []; } catch { return; }
  if (!S.cur || S.cur.id !== vid) return;
  const r = runs.find(x => x.kind !== 'doc' && x.videoId === vid);   // いちばん新しい実行(一覧は新しい順)
  const active = !!r && (r.state === 'queued' || r.state === 'running');
  if (!r || (!active && !AUTO.active && Date.now() - (r.finished || 0) > 10 * 60 * 1000)){ bar.hidden = true; AUTO.active = false; return; }   // 10分より前に終わったものは出さない
  const cls = r.nothing ? 'info' : (AUTO_STATE[r.state] || ['info'])[0], label = window.UIKit && UIKit.autorun ? UIKit.autorun.runLabel(r) : (AUTO_STATE[r.state] || [0, r.state])[1];   // 状態の言葉は1か所
  const stepLabel = s => (window.UIKit && UIKit.autorun ? UIKit.autorun.stepLabel(s) : AUTO_STEP[s.state] || s.state);   // 状態の言葉は1か所
  const steps = r.steps.map(s => `${esc(s.label)}: ${esc(stepLabel(s))}${s.detail ? '(' + esc(s.detail) + ')' : ''}`).join(' / ');
  bar.innerHTML = `<span><b>まとめて実行</b>(${esc(r.modeLabel)})</span><span class="pill ${cls}">${esc(label)}</span>` +
    (active ? '<button type="button" class="btn small" data-act="autocancel">中止</button>' : '') +
    `<a class="btn small ghost" href="../#cases" data-ui-portal title="ホームの案件の一覧で見ます(ホームがほかの窓で開いていれば、その窓を前に出します)">案件で見る</a><span class="rv-autosteps hint">${steps}${r.error ? ' ・ ' + esc(r.error) : ''}</span>`;
  bar.dataset.run = r.id;
  bar.hidden = false;
  // 終わった: 書き出し済みなどのマークの状態を読み直す。loadVideo だとプレーヤーが再読み込みされ、再生位置が 0:00 に戻ってしまうため、
  // 手元の未保存の編集を保ったまま最新の状態を重ねる syncFromServer(merge)を使う
  if (AUTO.active && !active && !S.dirty) syncFromServer();
  AUTO.active = active;
  if (active) AUTO.t = setTimeout(pollAuto, 3000);
}

let warnShown = false, warnDismissed = false;
function showDataWarning(){
  const w = Studio.state && Studio.state.dataWarning; if (!w || warnDismissed) return;
  $('#rvWarnText').textContent = String(w); $('#rvWarn').hidden = false;
  if (!warnShown){ warnShown = true; toast(String(w), 8000); }
}
Studio.onReady(() => {
  buildDOM(); S.built = true; placeJump();
  if (window.UIKit && UIKit.icon) UIKit.icon.fill($('#paneReview'));   // buildDOM は DOMContentLoaded の一括の埋め込みより後に動くので、ここで埋める
  $('#rvWarnClose').addEventListener('click', () => { warnDismissed = true; $('#rvWarn').hidden = true; });
  if (HIDE){ HIDE.onChange(list => { if (!list || list === 'videos') renderPickList(); }); HIDE.load().then(() => renderPickList(), () => {}); }
  /* まとめて実行はホームから開いたときだけ(12 ⑦(a))。使えないときは押せない理由を出す(renderAutoMenu → UIKit.menuOff が、押したら理由を知らせる。S-25) */
  if (window.UIKit && UIKit.packLoud) UIKit.packLoud.mount($('#rvAutoLoud'));   // パックの音量(編集の設定の1か所。2026-09-29)
  if (window.UIKit && UIKit.autorun && Studio.token){   // まとめて実行の設定の要約と「設定を変える」(どの入口も同じ部品。段4)・採用数はホームの設定
    UIKit.autorun.panel($('#paneReview .rv-autopanel'), { kind: 'video' });
    UIKit.autorun.load().then(st => { $('#rvAutoTop').value = String(st.top); }, () => {});
    $('#rvAutoTop').addEventListener('change', () => { const n = Math.round(Number($('#rvAutoTop').value)); if (n >= 1 && n <= 20 && UIKit.prefs) UIKit.prefs.patch('autorun', { top: n }).catch(() => {}); });
  }
  $('#rvAuto').addEventListener('click', e => { const b = e.target.closest('[data-auto]'); if (b) startAuto(b.dataset.auto); });
  if (Studio.token && window.UIKit && UIKit.streamer) UIKit.streamer.attach($('#rvAutoWho'));   // 配信者の名前(字幕の色)の候補と色の見本
  $('#rvAutoBar').addEventListener('click', async e => {
    if (!e.target.closest('[data-act=autocancel]')) return;
    try { await portalApi('api/autorun/cancel', { runId: $('#rvAutoBar').dataset.run }); } catch (er){ toast(er.message, 5000, 'err'); }
    pollAuto();
  });
  showDataWarning();
  /* ヘッダーの「録画中」の札(UIKit.liveBadge): 「開く」でページを移らずにその録画を ③ で開く・録画中の札が変わったら配信の一覧の「録画中」も合わせる */
  if (window.UIKit && UIKit.liveBadge){
    if (UIKit.liveBadge.onOpen) UIKit.liveBadge.onOpen(rec => { openLiveRecording(rec); });
    if (UIKit.liveBadge.onChange) UIKit.liveBadge.onChange(() => renderPickList());
  }
  if (Studio.live) Studio.live.available().then(i => { const el = $('#rvOpenForm .rv-openlive'); if (el) el.hidden = !i; }, () => {});   // ライブの機能が使えるときだけ「録画を始めて開きます」と添える
  wireSettings(); wire(); renderKeyUI();
  renderAll();
  Studio.on('step', st => { if (st === 'review') activate(); else deactivate(); });
  Studio.on('state', () => { renderExportUI(); showDataWarning(); });
  /* 画面を離れた・戻った(ui-kit の UIKit.life。段階7-2)。別の窓へ移った('blur')ときは保存だけ: 再生を止めない・状態の確認も続ける
     (窓を並べて、見ながら別の窓で作業できるように)。タブを離れた・閉じるときは今までどおり再生も止める */
  const life = window.UIKit && UIKit.life;
  const onLeft = reason => {
    if (setTimer) saveSettings();
    if (S.dirty) save();
    placeFlush();   // 前回の場所(S-8)
    if (reason !== 'blur'){ pausePlayback(); stopPoll(); liveStopPoll(); }
  };
  const onBack = () => {
    if (setFailed && !setLoadErr) saveSettings();   // 離れるときの保存が失敗していたら送り直す(監査 11)
    if (Studio.step === 'review'){ startPoll(); loadTranscripts(); liveResume(); }   // 文字起こしのタブ・窓で直してから戻ったとき
  };
  if (life){ life.onLeave(onLeft); life.onReturn(onBack); }
  else document.addEventListener('visibilitychange', () => { if (document.hidden) onLeft('hidden'); else onBack(); });
  window.addEventListener('beforeunload', e => {
    if (S.dirty || saveP || S.exportAll){ e.preventDefault(); e.returnValue = ''; }
  });
  loadSettings();
  refreshList();
  resumeJob();
});
})();
