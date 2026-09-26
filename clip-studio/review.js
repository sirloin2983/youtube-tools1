/* 切り抜きスタジオ ③ 確認・書き出し(切り抜きマーカー由来)。
   Studio.review = { open(id), refresh() }。データはすべてサーバー保存(PUT /api/video)。UI設定は /api/settings の settings.review。 */
(() => {
'use strict';
const Studio = window.Studio;
if (!Studio) return;
const esc = Studio.esc;
const $ = s => document.querySelector(s);
const enc = encodeURIComponent;
const pad = n => String(n).padStart(2, '0');
const round1 = x => Math.round(x * 10) / 10;
const uid = () => Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-4);
const toast = (m, ms, kind) => Studio.toast(m, ms, kind);

/* ---------- 時刻ユーティリティ ---------- */
function fmt(t){
  t = Math.max(0, Number(t) || 0);
  const d = Math.round(t * 10), h = Math.floor(d / 36000), m = Math.floor(d % 36000 / 600), s = ((d % 600) / 10).toFixed(1).padStart(4, '0');
  return h ? `${h}:${pad(m)}:${s}` : `${m}:${s}`;
}
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
const ACTION_DEFS = [
  ['markIn', 'IN(開始)'], ['markOut', 'OUT(終了)'], ['addClip', 'マーク追加'], ['quickMark', '今をマーク①'], ['quickMark2', '今をマーク②'], ['quickMark3', '今をマーク③'], ['quickMark4', '今をマーク④'], ['quickMark5', '今をマーク⑤'],
  ['playPause', '再生/停止'], ['back5', '5秒戻る'], ['fwd5', '5秒進む'], ['back1', '1秒戻る'], ['fwd1', '1秒進む'],
  ['volUp', '音量+'], ['volDown', '音量−'], ['mute', 'ミュート'], ['theater', 'シアター'],
  ['prevMark', '前のマークへ'], ['nextMark', '次のマークへ'], ['adopt', '採用'], ['reject', '不採用']
];
const KEY_PRESETS = {
  standard: { markIn: 'i', markOut: 'o', addClip: 'a', quickMark: 'n', quickMark2: '2', quickMark3: '3', quickMark4: '4', quickMark5: '5', playPause: 'k', back5: 'ArrowLeft', fwd5: 'ArrowRight', back1: 'Shift+ArrowLeft', fwd1: 'Shift+ArrowRight', volUp: 'ArrowUp', volDown: 'ArrowDown', mute: 'm', theater: 't', prevMark: '[', nextMark: ']', adopt: 'y', reject: 'u' },
  left: { markIn: 'q', markOut: 'w', addClip: 'e', quickMark: 'r', quickMark2: '2', quickMark3: '3', quickMark4: '4', quickMark5: '5', playPause: 's', back5: 'a', fwd5: 'd', back1: 'z', fwd1: 'c', volUp: 'f', volDown: 'v', mute: 'x', theater: 't', prevMark: 'g', nextMark: 'b', adopt: '1', reject: '6' }
};
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
const DEFAULT_SETTINGS = { volume: 100, muted: false, quickSpans: DEFAULT_QUICK_SPANS, keymap: KEY_PRESETS.standard, lag: 0, liveMode: 'auto', precision: 'accurate', maxHeight: 1080, exportVolume: 75, exportLoudness: -14, theater: false, graphLines: false, autoPlay: true, autoNext: true, exportTarget: 'adopted', sortBy: 'time', foldDefault: false };
function sanitizeSettings(x){
  x = x && typeof x === 'object' ? x : {};
  const n = (v, lo, hi, d) => Number.isFinite(Number(v)) ? Math.min(hi, Math.max(lo, Math.round(Number(v)))) : d;
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
    lag: [0, 2, 3, 5].includes(Number(x.lag)) ? Number(x.lag) : 0
  };
}

/* ---------- 状態 ---------- */
const S = {
  videos: [], cur: null, series: null, sel: null, filter: 'all', fold: new Map(), seen: new Set(),
  now: 0, duration: 0, playerState: -1, playerAlive: false, rate: 1, draft: { start: null, end: null }, previewEnd: null,
  settings: sanitizeSettings({}), live: false, job: null, lastJob: null,
  loadSeq: 0, editSeq: 0, dirty: false, built: false,
  tx: null, txOpen: new Set(), txSeq: 0   // 書き出したマークのセリフ(「編集」の文字起こしのデータ。/api/transcripts)
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
function buildDOM(){
  $('#paneReview').innerHTML = `
<div class="rv-root" id="rvRoot">
  <div class="rv-warn notice" id="rvWarn" hidden><span id="rvWarnText"></span><button type="button" class="btn small" id="rvWarnClose">閉じる</button></div>
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
        </div>
        <div class="rv-picklist" id="rvPickList"></div>
        <form class="rv-open" id="rvOpenForm" autocomplete="off">
          <label class="rv-fl" for="rvOpenIn">一覧に無い配信・動画ファイルを開く(解析せずに手でマークを付けるとき)</label>
          <div class="rv-openrow"><input id="rvOpenIn" type="text" spellcheck="false" placeholder="YouTube の URL・動画 ID、または動画ファイルのフルパス">
          <button class="btn" type="submit" id="rvOpenBtn">開く</button></div>
        </form>
      </div>
    </details>
    <button type="button" class="rv-save" id="rvSave" data-k="idle" role="status" title="マークは自動で保存します。失敗したときはここを押すと保存し直します">準備中</button>
    <span class="rv-topsp"></span>
    <details class="ui-menu rv-auto" id="rvAuto" hidden>
      <summary class="btn small ghost" title="案件の画面と同じ「まとめて実行」を、この配信で始めます"><span>まとめて実行</span></summary>
      <div class="rv-vmenupop rv-autopop">
        <p class="hint">この配信を、入口の案件の画面と同じ順番待ちで自動で進めます。進み具合は上の帯と、入口の案件の画面に出ます。</p>
        <button type="button" class="btn small primary" data-auto="adopted" title="採用したマークを書き出し → 文字起こし → Resolve パック">採用後を全部(書き出し → 文字起こし → パック)</button>
        <button type="button" class="btn small" data-auto="transcribe" title="採用したマークを書き出し → 文字起こし">文字起こしまで(書き出し → 文字起こし)</button>
        <div class="rv-autofull"><button type="button" class="btn small" data-auto="full" title="解析 → 上位を自動で採用 → 書き出し → 文字起こし → パック">解析から全部</button>
          <label class="lag">採用する数 <input id="rvAutoTop" type="number" min="1" max="30" step="1" value="3"></label></div>
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
  </div>
  <nav class="rv-jump" id="rvJump" aria-label="この画面の中の移動">
    <button type="button" class="rv-jumpb rv-jump-n" data-jump="player">プレーヤー</button>
    <button type="button" class="rv-jumpb rv-jump-n" data-jump="marks">マーク <b class="num" id="rvJumpMarks">0</b></button>
    <button type="button" class="rv-jumpb rv-jump-exp" data-jump="export" title="書き出しの欄へ">書き出し <b id="rvJumpExp"></b><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
  </nav>
  <div class="rv-emptybox empty" id="rvEmpty" hidden>
    <b>まだ配信が開かれていません</b>
    <span>② 解析で配信を入れると、終わったものから、ここで自動のマークを確かめられます。解析せずに手でマークを付けるときは、上の「配信」から URL か動画ファイルを開きます。</span>
    <div><button type="button" class="btn" id="rvEmptyOpen">配信を選ぶ・開く</button></div>
  </div>
  <div class="rv-grid" id="rvMain" hidden>
    <section class="rv-stage" id="rvStage" aria-label="プレーヤーとマークの付け方">
      <div class="rv-player" id="rvPlayerBox"><div class="rv-host" id="rvHost"></div><div class="rv-phmsg" id="rvPhMsg" hidden></div></div>
      <div class="rv-notice notice" id="rvNotice" hidden></div>

      <div class="rv-deck">
        <div class="rv-tl" id="rvTl" role="group" aria-label="タイムライン。クリックでその位置へ移動">
          <div id="rvSegs"></div><div class="rv-draft" id="rvDraft" hidden></div><div class="rv-ph" id="rvPh"></div>
        </div>
        <div class="rv-graph" id="rvGraph" hidden><div class="rv-gsvg" id="rvGSvg"></div><div class="rv-gcur" id="rvGCur"></div></div>
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
      </div>

      <div class="rv-quickbar" id="rvQuickbar"><div class="rv-fl">今をマーク <span class="muted">押した位置の前後を、そのままマークにします。− ＋ で前後の長さを切り替え</span></div><div class="rv-qrow" id="rvQuickSlots"></div></div>

      <div class="rv-livebar" id="rvLiveBar" hidden>
        <div class="rv-live-l"><span class="rv-live-badge">LIVE</span>
          <span class="rv-live-k">配信経過</span><span class="mono" id="rvLiveElapsed">--</span>
          <span class="rv-live-k">ライブ端との差</span><span class="mono" id="rvLiveGap">--</span>
          <span class="rv-live-k">ライブ印のマーク</span><span class="mono" id="rvLiveMarks">0件</span></div>
        <div><button class="btn small" id="rvEdge" type="button">ライブ端へ</button></div>
      </div>

      <div class="rv-mark">
        <div class="rv-markcell">
          <button class="rv-markbtn in" id="rvIn" type="button">IN(開始)<kbd data-kbd="markIn">I</kbd></button>
          <div class="rv-val is-empty" id="rvInVal">--</div>
        </div>
        <div class="rv-markcell">
          <button class="rv-markbtn out" id="rvOut" type="button">OUT(終了)<kbd data-kbd="markOut">O</kbd></button>
          <div class="rv-val is-empty" id="rvOutVal">--</div>
        </div>
        <div class="rv-markcell rv-addcell">
          <button class="btn primary" id="rvAdd" type="button">マーク追加<kbd data-kbd="addClip">A</kbd></button>
          <span class="hint" id="rvDraftDur">IN と OUT を押すと追加できます</span>
        </div>
      </div>

      <details class="rv-settings ui-disclosure" id="rvSettings">
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
            <p class="rv-sechint">キーのボタンを押してから、割り当てたいキーを押します。Esc = 取消 / Delete = 割り当て解除。すでに使われているキーを選ぶと、そちらの割り当てが外れます。一覧はヘッダーの「キー操作」(? キー)でも見られます。</p>
            <div class="rv-setrow"><select id="rvKeyPreset" aria-label="キー配置のプリセット"><option value="standard">標準(I O A ・矢印)</option><option value="left">左手だけ(Q W E ・A D)</option><option value="custom" disabled>カスタム</option></select><button class="btn small" id="rvKeyReset" type="button">標準に戻す</button></div>
            <div class="rv-keygrid" id="rvKeyGrid"></div>
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
      </details>
    </section>

    <section class="rv-clips" aria-label="書き出しとマーク">
      <section class="rv-panel" id="rvExport" aria-labelledby="rvExpTitle">
        <div class="rv-exphead"><h2 class="rv-ptitle" id="rvExpTitle">書き出し</h2><span class="rv-exp-sum hint" id="rvExpSum"></span></div>
        <div class="rv-status" id="rvToolStatus"></div>
        <div class="rv-tools"><button class="btn primary" id="rvExpRun" type="button">書き出す</button><button class="btn" id="rvExpAll" type="button" title="採用にしたマークがある全部の配信を、順番に書き出します">全部の配信の採用を書き出す</button><button class="btn danger" id="rvExpCancel" type="button" hidden>中止</button><button class="btn" id="rvExpRetry" type="button" hidden>失敗した分だけやり直す</button></div>
        <p class="hint rv-expcount" id="rvExpCount"></p>
        <div class="bar rv-expbar" id="rvExpBar" hidden><i></i></div>
        <details class="ui-disclosure rv-expset" id="rvExpSet"><summary>書き出しの設定 <span class="muted rv-expsetsum" id="rvExpSetSum"></span></summary>
          <div class="rv-expgrid">
            <div class="rv-fld"><label class="rv-fl" for="rvExpTarget">書き出す対象</label>
              <select id="rvExpTarget"><option value="adopted">採用のみ(おすすめ)</option><option value="pending">採用 + 候補</option><option value="all">不採用以外すべて(書き出し済みも)</option></select></div>
            <div class="rv-fld"><label class="rv-fl" for="rvPrecision">切り出し方式</label>
              <select id="rvPrecision" title="高速は切れ目がキーフレーム(数秒間隔)に寄るため、開始が最大数秒手前にずれます。失敗した場合は自動で精密方式に切り替えます。"><option value="accurate">精密(位置ちょうど・おすすめ)</option><option value="fast">高速(数秒手前から始まることあり)</option></select>
              </div>
            <div class="rv-fld" id="rvHeightBox"><label class="rv-fl" for="rvHeight">最大画質(YouTube)</label>
              <select id="rvHeight"><option value="720">720p</option><option value="1080">1080p</option><option value="1440">1440p</option><option value="2160">2160p</option><option value="0">制限なし</option></select></div>
            <div class="rv-fld"><label class="rv-fl" for="rvExpLoud">音量のそろえ方(<abbr class="ui-term" title="聞こえ方の音量(ラウドネス)の単位。YouTube は再生時に約 -14 LUFS に下げます">LUFS</abbr>)</label>
              <select id="rvExpLoud" title="切り抜きごとにバラバラな聞こえ方の音量(ラウドネス。単位 LUFS)を、書き出すときにそろえます。YouTube は再生時に約 -14 LUFS に下げます"><option value="-14">-14(YouTube の目安・おすすめ)</option><option value="-11">-11(大きめ)</option><option value="-16">-16(控えめ)</option><option value="-18">-18(小さめ)</option><option value="0">そろえない(音量 % で指定)</option></select></div>
            <div class="rv-fld" id="rvExpVolBox"><label class="rv-fl" for="rvExpVol">書き出しの音量(そろえないとき)</label>
              <div class="rv-setrow"><input type="range" id="rvExpVol" min="1" max="200" step="1" value="75" aria-label="書き出しの音量" title="出力ファイルの音量です(100で元の音量のまま)。元の音量だと大きすぎるとのことで、既定は75%にしています"><output id="rvExpVolOut" class="mono" for="rvExpVol">75</output><span class="muted">%</span></div>
            </div>
          </div>
          <p class="hint rv-outline">保存先: <span class="mono" id="rvOutDir"></span> <button type="button" class="btn small ghost" id="rvOutEdit">変更</button></p>
        </details>
        <ol class="rv-explist" id="rvExpList"></ol>
      </section>

      <div class="rv-clipbox" id="rvClipbox">
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
      </div>
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
/* Studio.api を通す(失敗時の e.status / e.code / e.body は Studio.api が付ける。API の置き場所を1か所で決めるため: docs/pipeline.md 5.) */
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
      if (stEdited){ mm.status = l.status || ''; mm.file = ''; mm.path = ''; }
      else if (s.status === 'exported' && (s.start !== l.start || s.end !== l.end)){ mm.status = 'adopted'; mm.file = ''; mm.path = ''; }
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
    if ((!localSt && m.status !== s.status) || m.file !== s.file || (m.path || '') !== (s.path || '')) changed = true;
    m.src = s.src; m.score = s.score; m.reasons = s.reasons; m.parts = s.parts; m.file = s.file; m.path = s.path || '';
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
const vWho = v => (v.kind === 'file' ? '動画ファイル' : (v.channel || '配信者不明'));
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
function pickRowHTML(v){
  const cur = S.cur && S.cur.id === v.id, t = v.createdAt || v.updatedAt;
  const pills = [nz(v.candidates) ? `<span class="pill warn">候補 ${nz(v.candidates)}</span>` : '', nz(v.adopted) ? `<span class="pill ok">採用 ${nz(v.adopted)}</span>` : '',
    nz(v.exported) ? `<span class="pill">書き出し済み ${nz(v.exported)}</span>` : '', !v.analysis && v.kind === 'youtube' ? '<span class="pill wait">解析前</span>' : '', v.groupId ? '<span class="pill info">コラボ</span>' : ''].join('');
  return `<button type="button" class="rv-prow${cur ? ' is-cur' : ''}" data-vid="${esc(v.id)}"${cur ? ' aria-current="true"' : ''} title="${esc(vLabel(v))}">
    <span class="rv-prow-t">${esc(vLabel(v))}</span>
    <span class="rv-prow-m"><span>${esc(vWho(v))}</span>${t ? `<span class="q-dot">・</span><span title="スタジオに追加: ${esc(Studio.date(t))}">${esc(Studio.ago(t))}</span>` : ''}${pills ? `<span class="rv-prow-p">${pills}</span>` : ''}</span></button>`;
}
function renderPickList(){
  const box = $('#rvPickList'); if (!box || !$('#rvPick').open) return;
  const vs = S.videos.map(v0 => (S.cur && S.cur.id === v0.id ? { ...v0, title: S.cur.title } : v0));
  const hit = vs.filter(pickMatch);
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
async function loadVideo(id){
  const seq = ++S.loadSeq;
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
  for (const m of marks()) S.seen.add(m.id);
  S.dirty = false; setSaveState('idle'); S.base = snap(S.cur.marks); S.baseTitle = S.cur.title;
  S.duration = S.cur.duration > 0 ? S.cur.duration : 0;
  $('#rvLiveBar').hidden = true;
  setNow(0);
  mountPlayer();
  renderAll();
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
  const btn = $('#rvOpenBtn'); btn.disabled = true;
  try {
    const r = await Studio.api('/api/videos/open', { method: 'POST', body });
    inp.value = '';
    const pk = $('#rvPick'); if (pk) pk.open = false;
    await loadVideo(r.video.id);
  } catch (e){ toast(e.message); }
  finally { btn.disabled = false; }
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
let yt = null, ytApiP = null, pollTimer = null, playerToken = 0, lastSeekAt = 0, lastApplyAt = 0, pollTick = 0;
function loadYTApi(){
  if (window.YT && window.YT.Player) return Promise.resolve();
  if (ytApiP) return ytApiP;
  ytApiP = new Promise((resolve, reject) => {
    window.onYouTubeIframeAPIReady = () => resolve();
    const s = document.createElement('script');
    s.src = 'https://www.youtube.com/iframe_api';
    s.onerror = () => reject(new Error('load'));
    document.head.appendChild(s);
    setTimeout(() => reject(new Error('timeout')), 12000);
  }).catch(e => { ytApiP = null; throw e; });
  return ytApiP;
}
/* プレーヤーが使えないときの案内(1か所に出したままにする)。YouTube の配信なら、YouTube で開くリンクを添える。
   使えない間は、前後のマークへ移動したときの自動再生で通知を出さない(押すたびに同じ通知が出ていた)。自分で再生を押したときだけ通知する */
function showNotice(t){
  S.playerErr = true;
  const n = $('#rvNotice'), v = S.cur;
  const yt0 = v && v.kind === 'youtube' ? `https://www.youtube.com/watch?v=${enc(v.id)}` : '';
  n.innerHTML = `<b>この画面では再生できません。</b> ${esc(t)}<br><span class="hint">判定・時刻の入力・書き出しは続けられます(マークを移っても自動では再生しません)。</span>${yt0 ? ` <a href="${esc(yt0)}" target="_blank" rel="noopener noreferrer" data-yt-now>YouTube で開く</a>` : ''}`;
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

/* ローカル動画: YT.Player と同じ最小インターフェースを持つ <video> アダプタ(サーバーの /media から Range 再生) */
class LocalPlayer {
  constructor(host, url, ev){
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
  getPlayerState(){ const e = this.el; return e.ended ? 0 : e.paused ? 2 : (e.readyState < 3 ? 3 : 1); }
  getVideoData(){ return { isLive: false }; }
  seekTo(t){ this.el.currentTime = Math.max(0, t); }
  playVideo(){ const r = this.el.play(); if (r && r.catch) r.catch(() => {}); }
  pauseVideo(){ this.el.pause(); }
  setPlaybackRate(r){ this.el.playbackRate = r; }
  setVolume(v){ this.el.volume = Math.min(1, Math.max(0, v / 100)); }
  getVolume(){ return Math.round(this.el.volume * 100); }
  mute(){ this.el.muted = true; }
  unMute(){ this.el.muted = false; }
  isMuted(){ return this.el.muted; }
  destroy(){ try { this.el.pause(); this.el.removeAttribute('src'); this.el.load(); } catch {} this.el.remove(); }
}
function unmountPlayer(){
  playerToken++; stopPoll();
  if (yt){ try { yt.destroy(); } catch {} yt = null; }
  S.playerAlive = false; S.playerErr = false; S.playerState = -1; S.previewEnd = null; hideNotice(); phMsg('');
  const host = $('#rvHost'); if (host) host.innerHTML = '';
}
async function mountPlayer(){
  unmountPlayer();
  const token = playerToken, v = S.cur;
  if (!v) return;
  const host = $('#rvHost');
  const onReady = e => {
    if (token !== playerToken) return;
    S.playerAlive = true; phMsg('');
    const d = e.target.getDuration(); if (d > 0) setDuration(d);
    e.target.setPlaybackRate(S.rate);
    applyToPlayer(); startPoll(); setTimeout(updateLive, 400); setTimeout(autoTitleFromPlayer, 1500);
  };
  const onState = e => {
    if (token !== playerToken) return;
    S.playerState = e.data;
    if (e.data === 1){ autoTitleFromPlayer(); updateLive(); }
    const d = yt && yt.getDuration ? yt.getDuration() : 0; if (d > 0 && d !== S.duration) setDuration(d);
  };
  phMsg('プレーヤーを準備しています…');
  if (v.kind === 'file'){
    yt = new LocalPlayer(host, Studio.url('/media?id=' + enc(v.id)), { onReady, onStateChange: onState, onError: e => { if (token === playerToken) showNotice(ytErrorMessage(e.data)); } });
    return;
  }
  if (location.protocol === 'file:'){ showNotice('file:// で開くとYouTube埋め込みが動きません。サーバーを起動して http://localhost から開いてください。'); return; }
  const mount = document.createElement('div'); host.appendChild(mount);
  try { await loadYTApi(); }
  catch { if (token === playerToken) showNotice('YouTube のプレーヤーを読み込めません(ネットの接続を確かめてください)。'); return; }
  if (token !== playerToken) return;
  yt = new YT.Player(mount, {
    width: '100%', height: '100%', videoId: v.id,
    playerVars: { playsinline: 1, rel: 0, origin: location.origin, hl: 'ja', cc_load_policy: 0 },
    events: { onReady, onStateChange: onState, onError: e => { if (token === playerToken) showNotice(ytErrorMessage(e.data)); } }
  });
}
function startPoll(){
  stopPoll();
  if (!yt || !visible()) return;
  pollTimer = setInterval(() => {
    if (!yt || !yt.getCurrentTime) return;
    if (Date.now() - lastSeekAt < 400) return; // seek直後は古い値が返るので無視
    S.playerState = yt.getPlayerState();
    if (++pollTick % 5 === 0) syncVolumeFromPlayer();
    setNow(yt.getCurrentTime());
    if (pollTick % 10 === 0) updateLive();
    if (S.previewEnd != null && S.now >= S.previewEnd - 0.05){ yt.pauseVideo(); setNow(S.previewEnd); S.previewEnd = null; }
  }, 100);
}
function stopPoll(){ if (pollTimer){ clearInterval(pollTimer); pollTimer = null; } }
function pausePlayback(){
  S.previewEnd = null;
  try { if (yt && yt.pauseVideo && S.playerState === 1) yt.pauseVideo(); } catch {}
}
function setNow(t){
  S.now = t;
  const inp = $('#rvNow'); if (inp && document.activeElement !== inp) inp.value = fmt(t);
  renderPlayhead();
}
function seek(t){
  t = Math.max(0, S.duration ? Math.min(t, S.duration) : t);
  if (yt){ try { yt.seekTo(t, true); } catch {} lastSeekAt = Date.now(); }
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
let setTimer = null;
function touchSettings(){ clearTimeout(setTimer); setTimer = setTimeout(saveSettings, 600); }
async function saveSettings(){
  clearTimeout(setTimer); setTimer = null;
  try {
    // review の節だけを送る(サーバーがロックの中で合わせる。別のタブが別の節を同時に保存しても消し合わない)
    await Studio.api('/api/settings', { method: 'PUT', body: { section: 'review', value: { ...S.settings } } });
  } catch {}
}
async function loadSettings(){
  try {
    const j = await Studio.api('/api/settings');
    S.settings = sanitizeSettings(j && j.settings && j.settings.review);
  } catch { S.settings = sanitizeSettings({}); }
  syncSettingsUI(); applyTheater();
}
function syncSettingsUI(){
  const s = S.settings;
  $('#rvVol').value = s.volume; $('#rvVolOut').textContent = s.volume; $('#rvMute').checked = s.muted;
  renderKeyUI(); $('#rvLag').value = String(s.lag); $('#rvLiveMode').value = s.liveMode;
  $('#rvHeight').value = String(s.maxHeight); $('#rvPrecision').value = s.precision;
  $('#rvExpVol').value = s.exportVolume; $('#rvExpVolOut').textContent = s.exportVolume;
  $('#rvExpLoud').value = String(s.exportLoudness); $('#rvExpVol').disabled = !!s.exportLoudness; $('#rvExpVolBox').classList.toggle('rv-off', !!s.exportLoudness);
  expSetSummary();
  $('#rvAutoPlay').checked = s.autoPlay; $('#rvAutoNext').checked = s.autoNext; $('#rvSort').value = s.sortBy; $('#rvExpTarget').value = s.exportTarget;
}
/* 「書き出しの設定」を閉じていても、いまの設定が分かるように見出しの横に短く出す */
function expSetSummary(){
  const el = $('#rvExpSetSum'); if (!el) return;
  const s = S.settings, v = S.cur;
  const parts = [{ adopted: '採用のみ', pending: '採用 + 候補', all: '不採用以外' }[s.exportTarget] || '', s.precision === 'fast' ? '高速' : '精密'];
  if (!(v && v.kind === 'file')) parts.push(s.maxHeight ? s.maxHeight + 'p まで' : '画質の制限なし');
  parts.push(s.exportLoudness ? s.exportLoudness + ' LUFS' : '音量 ' + s.exportVolume + '%');
  el.textContent = parts.filter(Boolean).join(' ・ ');
}
function applyToPlayer(){
  if (!yt) return;
  lastApplyAt = Date.now();
  try { yt.setVolume(S.settings.volume); if (S.settings.muted) yt.mute(); else yt.unMute(); } catch {}
}
function syncVolumeFromPlayer(){ // プレーヤー側(標準UI)での変更を設定へ反映
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
    if (yt){ yt.setVolume(S.settings.volume); lastApplyAt = Date.now(); }
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
const KEY_LABEL = { ArrowLeft: '←', ArrowRight: '→', ArrowUp: '↑', ArrowDown: '↓', Space: 'Space', Enter: 'Enter', Tab: 'Tab' };
function keyText(combo){
  if (!combo) return '未設定';
  return combo.split('+').map(p => KEY_LABEL[p] || (p.length === 1 ? p.toUpperCase() : p)).join('+');
}
function comboOf(e){
  const k = e.key; if (['Shift', 'Control', 'Alt', 'Meta', 'Dead', 'Process'].includes(k)) return '';
  const one = k.length === 1;
  return ((e.shiftKey && (!one || /[a-z]/i.test(k))) ? 'Shift+' : '') + (k === ' ' ? 'Space' : (one ? k.toLowerCase() : k));
}
const ACTION_FN = {
  markIn: () => markIn(), markOut: () => markOut(), addClip: () => addClip(), quickMark: () => quickMark(0), quickMark2: () => quickMark(1), quickMark3: () => quickMark(2), quickMark4: () => quickMark(3), quickMark5: () => quickMark(4), playPause: () => togglePlay(),
  back5: () => seek(S.now - 5), fwd5: () => seek(S.now + 5), back1: () => seek(S.now - 1), fwd1: () => seek(S.now + 1),
  volUp: () => adjustVolume(5), volDown: () => adjustVolume(-5), mute: () => toggleMute(), theater: () => toggleTheater(),
  prevMark: () => goMark(-1, false), nextMark: () => goMark(1, false), adopt: () => decideSel('adopted'), reject: () => decideSel('rejected')
};
function currentPreset(){
  const km = S.settings.keymap;
  return Object.keys(KEY_PRESETS).find(n => ACTION_DEFS.every(([id]) => (KEY_PRESETS[n][id] || '') === (km[id] || ''))) || 'custom';
}
let capturing = null;
const KEY_GROUPS = [['マークの操作', ['markIn', 'markOut', 'addClip']], ['今をマーク(長さは − ＋ で変更)', ['quickMark', 'quickMark2', 'quickMark3', 'quickMark4', 'quickMark5']], ['再生の操作', ['playPause', 'back5', 'fwd5', 'back1', 'fwd1']], ['判定・移動', ['prevMark', 'nextMark', 'adopt', 'reject']], ['音量・表示', ['volUp', 'volDown', 'mute', 'theater']]];
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
  const km = S.settings.keymap;
  $('#rvQuickSlots').innerHTML = S.settings.quickSpans.map((sp, i) =>
    `<div class="rv-qslot"><button class="btn${i === 0 ? ' soft' : ''}" type="button" data-slot="${i}" title="今の位置の前後${spanLabel(sp)}をマーク"><span class="rv-qn">${i + 1}</span><kbd data-kbd="${i ? 'quickMark' + (i + 1) : 'quickMark'}"></kbd></button>${spanSelHTML(i)}</div>`).join('');
  for (const el of document.querySelectorAll('#rvRoot kbd[data-kbd]')) el.textContent = km[el.dataset.kbd] ? keyText(km[el.dataset.kbd]) : '';
  const g = $('#rvKeyGrid');
  const spanSel = id => { const m = /^quickMark(\d?)$/.exec(id); return m ? spanSelHTML(m[1] ? Number(m[1]) - 1 : 0) : ''; };
  const defs = Object.fromEntries(ACTION_DEFS.map(d => [d[0], d[1]]));
  const row = id => `<div class="rv-keyrow"><span>${esc(defs[id] || id)}</span>${spanSel(id)}<button type="button" class="rv-keybtn${km[id] ? '' : ' none'}" data-id="${id}">${esc(keyText(km[id]))}</button></div>`;
  g.innerHTML = KEY_GROUPS.map(([h, ids]) => `<div class="rv-kgroup"><h4>${esc(h)}</h4>${ids.filter(id => defs[id]).map(row).join('')}</div>`).join('');
  $('#rvKeyPreset').value = currentPreset();
}
function setKey(id, combo){
  const km = { ...S.settings.keymap };
  if (combo){
    for (const [o] of ACTION_DEFS) if (o !== id && km[o] === combo){
      km[o] = ''; toast(`「${ACTION_DEFS.find(a => a[0] === o)[1]}」からこのキーを外しました`);
    }
  }
  km[id] = combo; S.settings.keymap = km; renderKeyUI(); touchSettings();
}
function startCapture(btn){
  stopCapture();
  capturing = { id: btn.dataset.id, btn }; btn.classList.add('cap'); btn.textContent = 'キーを押す…';
}
function stopCapture(){ if (capturing){ capturing = null; renderKeyUI(); } }
window.addEventListener('keydown', e => {
  if (!capturing) return;
  e.preventDefault(); e.stopImmediatePropagation();
  if (e.key === 'Escape') return stopCapture();
  if (e.key === 'Delete' || e.key === 'Backspace'){ const id = capturing.id; capturing = null; return setKey(id, ''); }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const combo = comboOf(e); if (!combo) return;
  const id = capturing.id; capturing = null; setKey(id, combo);
}, true);

/* ---------- ライブ配信 ---------- */
// IFrame APIの仕様上、ライブ中の getDuration() は「配信開始からの経過時間」を返す。
function renderLiveCount(){
  const n = marks().filter(c => c.live).length;
  $('#rvLiveMarks').textContent = n + '件'; $('#rvShiftCount').textContent = n ? `対象 ${n}件` : '対象なし';
}
function updateLive(){
  if (!yt || !S.cur) return;
  const isFile = S.cur.kind === 'file';
  let live = S.settings.liveMode === 'on' && !isFile;
  if (S.settings.liveMode === 'auto'){
    try { live = !isFile && !!(yt.getVideoData && yt.getVideoData().isLive); } catch { live = false; }
  }
  if (live !== S.live){ S.live = live; $('#rvLiveBar').hidden = !live; }
  if (!S.live) return;
  let e = 0; try { e = yt.getDuration(); } catch {}
  if (e > 0 && Math.abs(e - S.duration) >= 1) setDuration(e);
  $('#rvLiveElapsed').textContent = fmt(S.duration);
  const gap = S.duration - S.now;
  $('#rvLiveGap').textContent = (gap >= 0 ? '−' : '+') + Math.round(Math.abs(gap)) + '秒';
}

/* ---------- マーク操作 ---------- */
function newMark(start, end, live){
  return { id: uid(), start, end, label: '', src: 'manual', score: null, reasons: [], parts: {}, peak: null, live: !!live, status: '', file: '', createdAt: Date.now() };
}
function pushMark(m){
  const v = S.cur;
  v.marks.push(m); S.seen.add(m.id); S.sel = m.id; S.fold.set(m.id, false);
  markDirty(); renderTimeline(); renderStats(); renderLiveCount();
  if (!inList()) renderList();
  const li = document.querySelector(`.rv-mark-row[data-id="${CSS.escape(m.id)}"]`); if (li) li.scrollIntoView({ block: 'nearest' });
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
  pushMark(newMark(start, end, S.live));
  toast(`マーク ${fmt(start)} – ${fmt(end)}(前後${spanLabel(span)})`);
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
  const m = newMark(r[0], r[1], S.live);
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
  c[w] = val; if (c.status === 'exported'){ c.status = 'adopted'; c.file = ''; c.path = ''; } // 範囲を変えたら再書き出しできる状態(採用)に戻る(サーバーも同じ)
  markDirty(); return true;
}
function refresh(keyToFocus){
  renderTimeline(); renderStats(); renderList(); renderLiveCount();
  if (keyToFocus){ const el = document.querySelector(`[data-key="${CSS.escape(keyToFocus)}"]`); if (el) el.focus(); }
}
/* 2回押しの確認。以前は実行後も3秒間「確認済み」のままで、続けて押すと同じ操作(再解析の依頼・削除)がもう一度走っていたため、実行したら元に戻す */
function armDelete(btn, run, text){
  if (btn.dataset.armed){
    clearTimeout(Number(btn.dataset.armT)); delete btn.dataset.armed; btn.innerHTML = btn.dataset.label; btn.classList.remove('armed');
    run(); return;
  }
  btn.dataset.label = btn.innerHTML; btn.dataset.armed = '1'; btn.textContent = text || 'もう一度押すと削除'; btn.classList.add('armed');
  btn.dataset.armT = String(setTimeout(() => { if (btn.isConnected && btn.dataset.armed){ delete btn.dataset.armed; btn.innerHTML = btn.dataset.label; btn.classList.remove('armed'); } }, 3000));
}
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
  c.status = st; if (st !== 'exported') c.file = ''; c.path = '';
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
  if (!c) return toast('先にマークを選んでください(▶ 再生・行のクリック・前後移動キー)');
  if (!setStatus(c, st, true)) return;
}
function bulkAdopt(){
  const cs = marks().filter(m => statusOf(m) === '');
  if (!cs.length) return toast('候補がありません');
  for (const m of cs) m.status = 'adopted';
  markDirty(); refresh(); renderMeta(); toast(`候補 ${cs.length}件を採用にしました`);
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
  return sortedMarks().filter(m => t === 'adopted' ? m.status === 'adopted' : t === 'pending' ? (m.status === 'adopted' || !m.status) : m.status !== 'rejected');
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
  const tt = Studio.toolUrl('transcribe', '/?media=' + enc(path));
  return `<div class="rv-ejob-a">${tt ? `<a class="btn small" href="${esc(tt)}" target="_blank" rel="noopener" title="「編集」(文字起こし・カット・Resolve へのパック)で、この切り抜きを開きます(文字起こしは自動では始めません)">編集で開く</a>` : ''}<button type="button" class="btn small ghost" data-act="copy" data-path="${esc(path)}" title="${esc(path)}">パスをコピー</button>${man ? `<span class="pill info" title="${esc(man)}">.clip.json あり</span>` : ''}</div>`;
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
function renderExportUI(){
  if (!S.built) return;
  const v = S.cur, st = Studio.state || {};
  let msg = '';
  if (st.ffmpeg === false) msg += 'ffmpeg が見つかりません(Windows: winget install Gyan.FFmpeg / Mac: brew install ffmpeg)。入れてから起動し直してください';
  if (v && v.kind === 'youtube' && st.ytdlp === false) msg += (msg ? '\n' : '') + 'yt-dlp が見つかりません(Windows: winget install yt-dlp.yt-dlp)';
  const ts = $('#rvToolStatus'); ts.textContent = msg; ts.hidden = !msg;
  $('#rvHeightBox').hidden = !!(v && v.kind === 'file');
  { const j = S.lastJob; $('#rvOutDir').textContent = j && j.folder && S.job && v && S.job.videoId === v.id ? jobDirText(j, st) : (st.outDir || ''); }
  const t = exportTargets(), sum = t.reduce((s, c) => s + (c.end - c.start), 0);
  $('#rvExpTarget').value = S.settings.exportTarget;
  const running = !!(S.job && S.job.running) || S.starting || !!S.exportAll;
  const j = S.lastJob, jrun = !!(j && S.job && S.job.running && j.items.length);
  const done = jrun ? j.items.filter(i => i.status === 'done').length : 0;
  let count;
  const tgtName = { adopted: '採用', pending: '採用と候補', all: '不採用以外' }[S.settings.exportTarget] || '採用';
  if (S.exportAll) count = `全部の配信の書き出し: ${S.exportAll.idx}/${S.exportAll.total} 本目` + (S.exportAll.fail ? `(失敗 ${S.exportAll.fail}件)` : '');
  else if (jrun) count = `書き出し中 ${done}/${j.items.length}件`;
  else if (!v) count = '';
  else if (t.length) count = `${tgtName}のマーク ${t.length}件(合計 ${fmt(sum)})を mp4 にします`;
  else if (v.marks.some(m => !m.status)) count = '候補を「採用」にすると、書き出せるようになります';
  else count = v.marks.length ? '書き出すマークはありません(「採用」にしたマークを書き出します)' : 'マークを付けて「採用」にすると、書き出せるようになります';
  $('#rvExpCount').textContent = count;
  $('#rvExpSum').textContent = S.exportAll || jrun ? count : t.length ? `対象 ${t.length}件` : '';
  { const je = $('#rvJumpExp'); if (je) je.textContent = S.exportAll || jrun ? '実行中' : t.length ? t.length + '件' : ''; }
  { const b = $('#rvExpRun'); if (b) b.textContent = t.length && !jrun && !S.exportAll ? `${t.length}件を書き出す` : '書き出す'; }
  { const bar = $('#rvExpBar'); bar.hidden = !jrun;
    if (jrun){ const cur = j.items.find(i => i.status === 'running'); bar.firstElementChild.style.width = Math.round((done + (cur ? cur.progress || 0 : 0)) / j.items.length * 100) + '%'; } }
  const noTool = st.ffmpeg === false;
  const r = $('#rvExpRun'); r.disabled = running || !t.length || noTool || !!S.live;
  r.title = noTool ? 'ffmpeg が見つからないため書き出せません' : S.live ? '配信中は書き出せません' : !t.length ? '書き出す対象のマークがありません(「採用」にしたマークが書き出されます)' : '';
  { const n = S.videos.reduce((a, x) => a + (Number(x.adopted) || 0), 0), nv = S.videos.filter(x => x.adopted > 0).length, b = $('#rvExpAll'); b.textContent = `全部の配信の採用を書き出す(${nv}本・${n}件)`; b.disabled = running || !n || !!S.live || noTool; }
  { const n = failedIds().size, b = $('#rvExpRetry'); b.hidden = !n; b.textContent = `失敗した分だけやり直す(${n}件)`; b.disabled = running; }
  $('#rvExpCancel').hidden = !running;
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
  return `<li class="rv-ejob st-${cls}"><div class="rv-ejob-h">
      <span class="mono rv-ejob-t">${i + 1}. ${fmt(it.start)} – ${fmt(it.end)}</span><span class="rv-ejob-n">${esc(it.title || '無題')}</span>
      <span class="pill ${cls}">${esc(EXP_LABEL[it.status] || it.status)}${it.status === 'running' ? ' ' + pct + '%' : ''}</span></div>
      ${it.status === 'running' ? `<div class="bar rv-ejob-bar"><i style="width:${pct}%"></i></div>` : ''}
      ${it.file ? `<div class="rv-ejob-s mono">${esc(it.file)}</div>` : ''}
      ${handoffHTML(j, it)}
      ${loudHTML(it.loudness)}
      ${it.warning ? `<div class="rv-ejob-s rv-warnline">${esc(it.warning)}</div>` : ''}
      ${it.error ? `<div class="rv-ejob-s rv-err">${esc(it.error)}</div>` : ''}</li>`;
}
function renderJob(j){
  S.lastJob = j;
  const ol = $('#rvExpList');
  const rows = j.items.map((it, i) => jobItemHTML(j, it, i));
  const h = j.items.map(i => errHint(i.error)).find(Boolean);
  if (h) rows.push(`<li class="hint rv-ejob-hint">${esc(h)}</li>`);
  if (j.waiting) rows.unshift('<li class="hint rv-ejob-hint">他のツールの重い処理が終わるのを待っています(順番が来たら書き出しを始めます。中止もできます)</li>');
  const prev = S.jobRows || [];
  if (ol.dataset.job !== String(j.id) || prev.length !== rows.length || ol.children.length !== rows.length){
    ol.innerHTML = rows.join(''); ol.dataset.job = String(j.id);
  } else {
    rows.forEach((r, i) => { if (r !== prev[i]){ const t = document.createElement('template'); t.innerHTML = r; ol.children[i].replaceWith(t.content.firstElementChild); } });
  }
  S.jobRows = rows;
  if (S.job) S.job.running = j.state === 'running';
  renderExportUI();
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
        toast(j.state === 'cancelled' ? '書き出しを中止しました' : `書き出し完了: ${done}/${j.items.length}件` + (done < j.items.length ? '(失敗あり)' : ''), 0, j.state === 'cancelled' ? '' : done < j.items.length ? 'err' : 'ok');
      }
    } catch (e){
      if (e.status === 404){ S.job = null; rememberJob(null); stopExpPoll(); renderExportUI(); }
    } finally { busy = false; }
  };
  expTimer = setInterval(tick, 1000); tick();
}
async function startExport(onlyIds){
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
    const j = await Studio.api('/api/export', { method: 'POST', body: { id: v.id, markIds: targets.map(c => c.id), precision: S.settings.precision, maxHeight: S.settings.maxHeight, volume: S.settings.exportVolume, loudness: S.settings.exportLoudness || null } });
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
    list = (await Studio.api('/api/videos')).videos.filter(x => x.adopted > 0);
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
        try { j = await Studio.api('/api/export', { method: 'POST', body: { id: v.id, markIds: chunk, precision: S.settings.precision, maxHeight: S.settings.maxHeight, volume: S.settings.exportVolume, loudness: S.settings.exportLoudness || null } }); }
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
  if (!v){ $('#rvCurLabel').textContent = S.videos.length ? '選んでください' : 'まだありません'; $('#rvCurLabel').classList.add('is-empty'); $('#rvChips').textContent = S.videos.length ? `${S.videos.length}本から探せます` : ''; return; }
  const has = !!v.title, el = $('#rvCurLabel');
  el.classList.toggle('is-empty', !has);   // 'empty' は ui-kit の「空の状態」の枠と名前がぶつかるので使わない
  el.textContent = has ? v.title : '(名前なし)';
  /* だれの・いつの(同じ題名の配信を見分ける)。ID・ファイル名は title で */
  const auto = v.marks.filter(m => m.src === 'auto').length, exp = v.marks.filter(m => m.status === 'exported').length;
  const row = S.videos.find(x => x.id === v.id), t0 = row ? (row.createdAt || row.updatedAt) : v.createdAt;
  const ch = $('#rvChips');
  ch.innerHTML = `<span class="rv-chip-who">${esc(vWho(v))}</span>${t0 ? `<span class="q-dot">・</span><span>${esc(Studio.ago(t0))}</span>` : ''}${auto ? `<span class="rv-chip auto">自動 ${auto}</span>` : ''}${exp ? `<span class="rv-chip done">書き出し済み ${exp}</span>` : ''}`;
  ch.title = v.kind === 'file' ? '動画ファイル: ' + (v.fileName || v.id) : 'YouTube: ' + v.id;
  const t = $('#rvTitle'); if (document.activeElement !== t) t.value = v.title || '';
  $('#rvAnalyze').hidden = v.kind !== 'youtube';
  const yl = $('#rvYtLink'); yl.hidden = v.kind !== 'youtube'; if (v.kind === 'youtube') yl.href = 'https://www.youtube.com/watch?v=' + enc(v.id);
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
}

/* 盛り上がりグラフ: series.total の面グラフ + 自動マークの帯。プレイヘッドの動きでは再描画しない(カーソル線だけ動かす) */
const GW = 1000, GH = 40;
function renderGraph(){
  const box = $('#rvGraph'), leg = $('#rvGLegend'), v = S.cur, s = S.series;
  if (!v){ box.hidden = true; leg.hidden = true; return; }
  if (!s || !Array.isArray(s.total) || !s.total.length){
    box.hidden = true;
    const hasAuto = v.marks.some(isAutoLike) || !!v.analysis;
    leg.hidden = !hasAuto;
    if (hasAuto) leg.innerHTML = '<span class="hint" title="盛り上がりのグラフは、解析した直後だけ出ます(入口を終了すると消えます)">グラフは解析した直後だけ出ます</span>';
    return;
  }
  const dur = totalDur(), step = Number(s.step) > 0 ? Number(s.step) : 1;
  const X = i => Math.min(GW, i * step / dur * GW);
  const line = arr => {
    const mx = Math.max(1e-9, ...arr);
    return arr.map((y, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + (GH - 2 - (y / mx) * (GH - 4)).toFixed(1)).join('');
  };
  const total = s.total, mx = Math.max(1e-9, ...total);
  const pts = total.map((y, i) => X(i).toFixed(1) + ' ' + (GH - 1 - (y / mx) * (GH - 4)).toFixed(1));
  const area = `M${X(0).toFixed(1)} ${GH}L${pts.join('L')}L${X(total.length - 1).toFixed(1)} ${GH}Z`;
  const bands = v.marks.filter(isAutoLike).map(m => {
    const x = Math.min(GW, m.start / dur * GW), w = Math.max(2, Math.min(GW, m.end / dur * GW) - x);
    return `<rect class="rv-g-band" x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="${GH}"/>`;
  }).join('');
  const lines = S.settings.graphLines ? [['audio', 'a'], ['chat', 'c'], ['comments', 'm']].filter(([k]) => Array.isArray(s[k]) && s[k].length).map(([k, c]) => `<path class="rv-g-line ${c}" d="${line(s[k])}"/>`).join('') : '';
  $('#rvGSvg').innerHTML = `<svg viewBox="0 0 ${GW} ${GH}" preserveAspectRatio="none" role="img" aria-label="盛り上がりグラフ"><path class="rv-g-area" d="${area}"/>${bands}${lines}</svg>`;
  box.hidden = false; leg.hidden = false;
  leg.innerHTML = `<span class="rv-lg"><i class="rv-sw tot"></i>盛り上がり(合計)</span><span class="rv-lg"><i class="rv-sw band"></i>自動マークの範囲</span>` +
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
    <div class="rv-trow"><span class="rv-fl rv-tlab">${label}</span><input class="mono" data-f="${w}" value="${fmt(c[w])}" aria-label="${label}時刻" autocomplete="off" ${k('in', w)}>
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
      <button type="button" class="rv-fold" data-act="fold" aria-expanded="${!fold}" aria-label="${fold ? '開く' : '折りたたむ'}" title="${fold ? '開く' : '折りたたむ'}">${fold ? '▸' : '▾'}</button>
      <button type="button" class="btn small rv-play" data-act="play" aria-label="この範囲を再生(開始から終了まで)" title="この範囲を再生">${SVG.play}</button>
      <span class="rv-tc mono">${fmt(c.start)} – ${fmt(c.end)}</span><span class="rv-dur mono">${(c.end - c.start).toFixed(1)}s</span>
      ${c.src === 'auto' ? '<span class="rv-chip auto">自動</span>' : ''}${c.score != null ? `<span class="rv-chip score mono" title="自動判定の点数">${Number(c.score).toFixed(1)}点</span>` : ''}
      ${c.live ? '<span class="rv-chip live">ライブ</span>' : ''}
      ${exp ? '<span class="rv-chip st exported">書き出し済み</span>' : ''}
      ${fold && c.label ? `<span class="rv-lab-s" title="${esc(c.label)}">${esc(c.label)}</span>` : ''}
      <span class="rv-mact"><span class="rv-stgroup" role="group" aria-label="判定">${sb('adopted', '採用', exp ? '採用に戻す(書き出し済みの印を外して、もう一度書き出せるようにします)' : '採用(書き出し対象)')}${sb('rejected', '不採用', '不採用')}${sb('', '候補', '候補に戻す')}</span>
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
  return `<details class="rv-tx" data-tx="${esc(c.id)}"${S.txOpen.has(c.id) ? ' open' : ''}>
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
  try { ol.innerHTML = list.map(markHTML).join(''); } finally { S.rendering = false; }
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
  setSaveState(S.cur ? 'idle' : 'idle');
}
const WIDE = '(min-width:961px)';
function placeQuickBar(){
  const qb = $('#rvQuickbar'), cb = $('#rvClipbox'), home = $('#rvLiveBar'); if (!qb || !cb || !home) return;
  const side = !!S.settings.theater && window.matchMedia(WIDE).matches;
  if (side) cb.prepend(qb); else if (qb.parentElement !== home.parentElement) home.before(qb);
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
function jumpTo(where){
  const target = { player: '#rvPlayerBox', marks: '#rvClipbox', export: '#rvExport' }[where];
  const el = target && $(target); if (!el || $('#rvMain').hidden) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (where === 'export'){
    el.classList.remove('rv-flash'); void el.offsetWidth; el.classList.add('rv-flash');
    const b = $('#rvExpRun'); if (b && !b.disabled) setTimeout(() => b.focus({ preventScroll: true }), 350);
  }
}
function applyTheater(){
  const on = !!S.settings.theater;
  $('#rvMain').classList.toggle('theater', on);
  $('#rvRoot').classList.toggle('theater-wide', on);
  placeQuickBar();
  const b = $('#rvTheater'); b.setAttribute('aria-pressed', String(on)); b.querySelector('span').textContent = on ? '通常表示' : 'シアター';
}
function toggleTheater(){ S.settings.theater = !S.settings.theater; applyTheater(); touchSettings(); }

/* ---------- イベント ---------- */
function wire(){
  const list = $('#rvList');
  list.addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const li = b.closest('.rv-mark-row'); const c = li && marks().find(x => x.id === li.dataset.id); if (!c) return;
    const key = b.dataset.key || '';
    switch (b.dataset.act){
      case 'play': S.sel = c.id; renderTimeline(); list.querySelectorAll('.rv-mark-row').forEach(x => x.classList.toggle('sel', x === li)); previewClip(c); break;
      case 'fold': S.fold.set(c.id, !isFolded(c.id)); renderListKeep(); break;
      case 'txseek': {   // セリフの行を押したら、その行だけ再生する(元の配信の時刻)
        const t = Number(b.dataset.t), e2 = Number(b.dataset.e);
        if (!Number.isFinite(t)) break;
        if (!canPlay()){ seek(t); noPlayerToast(); break; }
        seek(t); S.previewEnd = Number.isFinite(e2) && e2 > t ? e2 : null; yt.playVideo(); break; }
      case 'st': setStatus(c, b.dataset.st, b.dataset.st === 'adopted' || b.dataset.st === 'rejected'); break;
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
    S.sel = li.dataset.id; renderTimeline(); list.querySelectorAll('.rv-mark-row').forEach(x => x.classList.toggle('sel', x === li));
  });
  list.addEventListener('input', e => {
    if (e.target.dataset.f !== 'label') return;
    const c = marks().find(x => x.id === e.target.closest('.rv-mark-row').dataset.id); if (!c) return;
    c.label = e.target.value; markDirty();
  });
  list.addEventListener('change', e => {
    if (S.rendering) return; // 再描画で入力欄が外れるときに出る blur 由来の change は無視
    const f = e.target.dataset.f;
    const li = e.target.closest('.rv-mark-row'); const c = li && marks().find(x => x.id === li.dataset.id); if (!c) return;
    if (f !== 'start' && f !== 'end') return;
    const t = parseTime(e.target.value);
    if (Number.isNaN(t)){ toast('時刻の形式が正しくありません(例: 1:23.5)'); e.target.value = fmt(c[f]); return; }
    if (setBound(c, f, t)) refresh(c.id + '|in|' + f); else e.target.value = fmt(c[f]);
  });
  list.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const f = e.target.dataset && e.target.dataset.f;
    if (f === 'start' || f === 'end'){ e.preventDefault(); e.target.dispatchEvent(new Event('change', { bubbles: true })); }
    else if (f === 'label'){ e.preventDefault(); e.target.blur(); }
  });

  // タイムライン(クリックで移動・ドラッグでスクラブ・区間は選択)と、グラフ上のクリック
  const tl = $('#rvTl'); let drag = null;
  const timeAt = (e, el) => { const r = el.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * totalDur(); };
  function selectSeg(seg){
    const c = marks().find(x => x.id === seg.dataset.id); if (!c) return;
    S.sel = c.id; renderTimeline(); list.querySelectorAll('.rv-mark-row').forEach(x => x.classList.toggle('sel', x.dataset.id === c.id));
    const li = list.querySelector(`.rv-mark-row[data-id="${CSS.escape(c.id)}"]`); if (li) li.scrollIntoView({ block: 'nearest' });
  }
  function scrub(t, final){
    t = Math.max(0, S.duration ? Math.min(t, S.duration) : t);
    if (yt){ try { yt.seekTo(t, final); } catch {} lastSeekAt = Date.now(); }
    setNow(t);
  }
  tl.addEventListener('pointerdown', e => {
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    const seg = e.target.closest('.rv-seg');
    drag = { id: e.pointerId, x0: e.clientX, moved: false, seg };
    try { tl.setPointerCapture(e.pointerId); } catch {}
    tl.classList.add('dragging');
    if (!seg) scrub(timeAt(e, tl), false);
  });
  tl.addEventListener('pointermove', e => {
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.moved && Math.abs(e.clientX - drag.x0) < 4) return;
    drag.moved = true; scrub(timeAt(e, tl), false);
  });
  const end = e => {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag; drag = null; tl.classList.remove('dragging');
    if (e.type === 'pointercancel') return;
    if (d.seg && !d.moved) selectSeg(d.seg); else scrub(timeAt(e, tl), true);
  };
  tl.addEventListener('pointerup', end); tl.addEventListener('pointercancel', end);
  $('#rvGraph').addEventListener('click', e => scrub(timeAt(e, $('#rvGraph')), true));
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
  $('#rvJump').addEventListener('click', e => { const b = e.target.closest('[data-jump]'); if (b) jumpTo(b.dataset.jump); });
  /* YouTube で開くリンクは、押したときの再生位置から */
  const ytNow = a => { if (S.cur && S.cur.kind === 'youtube') a.href = `https://www.youtube.com/watch?v=${enc(S.cur.id)}${S.now >= 1 ? '&t=' + Math.floor(S.now) + 's' : ''}`; };
  $('#rvNotice').addEventListener('click', e => { const a = e.target.closest('a[data-yt-now]'); if (a) ytNow(a); });
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
  $('#rvKeyGrid').addEventListener('click', onSpanStep);
  $('#rvKeyGrid').addEventListener('click', e => { const b = e.target.closest('.rv-keybtn'); if (b) startCapture(b); });
  $('#rvKeyPreset').addEventListener('change', e => { const pr = KEY_PRESETS[e.target.value]; if (pr){ S.settings.keymap = sanitizeKeymap(pr); renderKeyUI(); touchSettings(); } });
  $('#rvKeyReset').addEventListener('click', () => { S.settings.keymap = sanitizeKeymap(KEY_PRESETS.standard); renderKeyUI(); touchSettings(); });
  $('#rvEdge').addEventListener('click', () => { if (yt && S.duration) seek(S.duration); });
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
      if (c.status === 'exported'){ c.status = 'adopted'; c.file = ''; c.path = ''; }
    }
    if (!n) return toast('配信の範囲外になるため、ずらせませんでした');
    markDirty(); refresh(); toast(`${n}件を ${d > 0 ? '+' : ''}${d}秒ずらしました` + (n < targets.length ? `(範囲外の${targets.length - n}件は除く)` : ''));
  });
  $('#rvTheater').addEventListener('click', toggleTheater);
  $('#rvPlayerBox').addEventListener('mouseleave', reclaimFocus);
  $('#rvFilters').addEventListener('click', e => { const b = e.target.closest('[data-filter]'); if (!b) return; S.filter = b.dataset.filter; renderStats(); renderList(); });
  $('#rvFoldAll').addEventListener('click', () => foldAll(true));
  $('#rvUnfoldAll').addEventListener('click', () => foldAll(false));
  $('#rvBulkAdopt').addEventListener('click', e => armDelete(e.currentTarget, bulkAdopt, 'もう一度押すと、候補をすべて採用にします'));
  $('#rvExpAll').addEventListener('click', startExportAll);
  $('#rvOutEdit').addEventListener('click', () => Studio.openSettings('setOut'));
  const onCopy = async e => {   // 書き出しの一覧と、書き出し済みのマークの行の「パスをコピー」
    const b = e.target.closest('[data-act="copy"]'); if (!b) return;
    e.stopPropagation();
    const ok = await copyText(b.dataset.path);
    Studio.toast(ok ? 'パスをコピーしました: ' + b.dataset.path : 'コピーできませんでした。パス: ' + b.dataset.path, 0, ok ? 'ok' : 'err');
  };
  $('#rvExpList').addEventListener('click', onCopy);
  $('#rvList').addEventListener('click', onCopy);
  Studio.on('ports', () => { if (S.lastJob) renderJob(S.lastJob); if (S.cur) renderList(); });   // 他のツールの実際のポートが分かったら、リンクを作り直す
  window.matchMedia(WIDE).addEventListener('change', () => { placeQuickBar(); placeJump(); });

  // 書き出し
  $('#rvExpRun').addEventListener('click', () => startExport());
  $('#rvExpRetry').addEventListener('click', () => { const ids = failedIds(); if (ids.size) startExport(ids); });
  $('#rvExpCancel').addEventListener('click', async () => {
    if (S.exportAll) S.exportAll.cancel = true;
    if (!S.job || !S.job.running) return;
    try { await Studio.api('/api/export/cancel', { method: 'POST', body: { id: S.job.id } }); } catch (e){ toast(e.message); }
  });

  // キーボードショートカット(このステップが表示されているときだけ)
  document.addEventListener('keydown', e => {
    if (Studio.step !== 'review' || !S.cur) return;
    if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
    if (Studio.overlayOpen && Studio.overlayOpen()) return;   // 設定の引き出し・キー一覧を開いている間は、裏の配信を操作しない
    if (Studio.inMenu && Studio.inMenu(e.target)) return;      // 配信の選択・配信の操作のメニューの中では、そのメニューの操作を優先する
    const tag = e.target.tagName;
    if (Studio.isTyping ? Studio.isTyping(e.target) : (tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable || (tag === 'INPUT' && !['range', 'checkbox', 'radio', 'button'].includes(e.target.type)))) return; // 文字入力中はショートカットを無効化(スライダー/チェックボックス上では有効)
    // ボタン・リンク・開閉の見出しの上では、Space / Enter はその部品の操作を優先する(Space で「操作の設定」を開けなかったのを修正)
    const onControl = tag === 'BUTTON' || tag === 'INPUT' || tag === 'SUMMARY' || tag === 'A';
    const combo = comboOf(e); if (!combo) return;
    const km = S.settings.keymap;
    const hit = ACTION_DEFS.find(([id]) => km[id] && km[id] === combo);
    if (hit && !(combo === 'Space' && onControl)){
      e.preventDefault();
      if (e.repeat && !['back5', 'fwd5', 'back1', 'fwd1', 'volUp', 'volDown'].includes(hit[0])) return; // 押しっぱなしでマークが連続作成されないように
      ACTION_FN[hit[0]](); return;
    }
    if (e.key === ' ' && !onControl){ e.preventDefault(); if (!e.repeat) togglePlay(); } // Spaceは常に再生/停止の予備キー
  });
}

/* ---------- ステップの表示・非表示 ---------- */
async function activate(){
  startPoll();
  await refreshList();
  if (Studio.step !== 'review') return;
  if (!S.cur && !S.loadSeq){
    if (S.videos.length) await loadVideo(S.videos[0].id); else renderAll();
  } else if (S.cur) syncFromServer();
}
function deactivate(){
  pausePlayback(); stopPoll();
  if (setTimer) saveSettings();
  if (S.dirty || saveTimer) save();
}

/* ---------- 起動 ---------- */
/* キー操作の一覧(ヘッダーの「キー」・? キー)に出す内容。[見出し, [[キーの表記, 説明], ...]] の配列 */
function keyHelp(){
  const km = S.settings.keymap, defs = Object.fromEntries(ACTION_DEFS.map(d => [d[0], d[1]]));
  const row = id => { let label = defs[id] || id; const m = /^quickMark(\d?)$/.exec(id); if (m){ const i = m[1] ? Number(m[1]) - 1 : 0; label += `(前後${spanLabel(S.settings.quickSpans[i])})`; } return [km[id] ? keyText(km[id]) : '', label]; };
  const groups = KEY_GROUPS.map(([h, ids]) => [h, ids.filter(id => defs[id]).map(row)]);
  groups.push(['その他', [['Space', '再生 / 停止(予備。ボタンの上ではボタンが優先)'], ['Enter', '時刻の欄: 確定して移動 / ラベル: 確定']]]);
  return groups;
}
Studio.review = {
  async open(id){
    const p = loadVideo(String(id));   // 先に loadSeq を進める(ステップ表示時の自動読み込みと競合させない)
    Studio.go('review');
    return p;
  },
  refresh: refreshList,
  keyHelp
};
/* ---------- まとめて実行(docs/edit-tool-design.md の 12 ⑦(a)。入口の /api/autorun。案件の画面と同じ API・同じ形。入口の中だけ) ---------- */
const AUTO = { t: 0, active: false };
const AUTO_STATE = { queued: ['wait', '順番待ち'], running: ['run', '実行中'], done: ['ok', '完了'], error: ['err', '止まりました'], cancelled: ['wait', '中止'] };
const AUTO_STEP = { wait: '待ち', run: '実行中', done: '済', skip: '飛ばした', warn: '一部', error: '失敗' };
/* 入口の API(/api/...)。画面は入口の /studio/ の下にあるので、画面の場所から1つ上(絶対パスを書かない) */
async function portalApi(path, body){
  const init = { cache: 'no-store', method: body === undefined ? 'GET' : 'POST' };
  if (body !== undefined){ init.headers = { 'Content-Type': 'application/json', 'X-YTT-Token': Studio.token }; init.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(new URL('../' + path, location.href).href, init); } catch { throw new Error('入口に接続できません(入口の黒い画面が閉じていないか確かめてください)'); }
  let j = {};
  try { j = await r.json(); } catch {}
  if (!r.ok){ const er = new Error(j.message || ('エラー(HTTP ' + r.status + ')')); er.code = j.error; er.status = r.status; throw er; }
  return j;
}
async function startAuto(mode){
  if (!S.cur) return;
  const top = Math.min(30, Math.max(1, Math.round(Number($('#rvAutoTop').value) || 3)));
  try {
    if (S.dirty) await flushSave();   // 手で付けたマークを先に保存してから(まとめて実行は保存済みのマークを読む)
    await portalApi('api/autorun/start', { id: S.cur.id, mode, ...(mode === 'full' ? { top } : {}) });
    $('#rvAuto').open = false;
    toast('まとめて実行を始めました(入口の案件の画面と同じ順番待ち)', 5000, 'ok');
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
  const [cls, label] = AUTO_STATE[r.state] || ['info', r.state];
  const steps = r.steps.map(s => `${esc(s.label)}: ${esc(AUTO_STEP[s.state] || s.state)}${s.detail ? '(' + esc(s.detail) + ')' : ''}`).join(' / ');
  bar.innerHTML = `<span><b>まとめて実行</b>(${esc(r.modeLabel)})</span><span class="pill ${cls}">${esc(label)}</span>` +
    (active ? '<button type="button" class="btn small" data-act="autocancel">中止</button>' : '') +
    `<a class="btn small ghost" href="../cases.html" target="_blank" rel="noopener">案件で見る</a><span class="rv-autosteps hint">${steps}${r.error ? ' ・ ' + esc(r.error) : ''}</span>`;
  bar.dataset.run = r.id;
  bar.hidden = false;
  if (AUTO.active && !active && !S.dirty) loadVideo(vid);   // 終わった: 書き出し済みなどのマークの状態を読み直す
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
  $('#rvWarnClose').addEventListener('click', () => { warnDismissed = true; $('#rvWarn').hidden = true; });
  $('#rvAuto').hidden = !Studio.token;   // まとめて実行は入口から開いたときだけ(12 ⑦(a))
  $('#rvAuto').addEventListener('click', e => { const b = e.target.closest('[data-auto]'); if (b) startAuto(b.dataset.auto); });
  $('#rvAutoBar').addEventListener('click', async e => {
    if (!e.target.closest('[data-act=autocancel]')) return;
    try { await portalApi('api/autorun/cancel', { runId: $('#rvAutoBar').dataset.run }); } catch (er){ toast(er.message, 5000, 'err'); }
    pollAuto();
  });
  showDataWarning();
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
    if (reason !== 'blur'){ pausePlayback(); stopPoll(); }
  };
  const onBack = () => { if (Studio.step === 'review'){ startPoll(); loadTranscripts(); } };   // 文字起こしのタブ・窓で直してから戻ったとき
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
