/* 切り抜きスタジオ: 設定(右の引き出し: APIキー / 出力先フォルダ(表示) / ② の操作(キー配置とマークをまとめてずらす。中身は review.js が #opsHost に入れる)/ ライブの録画(表示)/ コラボ / 事務所。
   0.25.0(docs/spec/settings.md の 6): 解析・書き出しのあとの文字起こし・確認の進め方・反応の遅れ・ライブ判定・ライブの録画の値・出力先の変更は、設定の画面(入口の /settings)へ。ここには残さない / 事務所の登録)と、ffmpeg・yt-dlp が無いときのお知らせ */
(() => {
'use strict';
const $ = s => document.querySelector(s);
const S = window.Studio;
let regMounted = false;
/* v6: 設定の器そのもの(#uiSettingsDrawer)は ui-kit(UIKit.settings.mount)が作る。ここではツール固有の中身の要素を1つ作って渡すだけ */
const toolEl = document.createElement('div');
toolEl.id = 'settingsBody';
toolEl.innerHTML = '<p class="hint">読み込み中…</p>';

function build(){
  toolEl.innerHTML = `
  <p class="hint set-page"><span>解析・確認の進め方・書き出し・ライブの録画・出力先の変更は、設定の画面(スタジオの節)で変えます。</span>
    <a class="btn small" id="setPageLink" href="../settings#sec-studio">設定の画面を開く</a></p>
  <details class="card set-sec" id="setKey" open><summary><span class="set-title">YouTube Data API キー</span><span class="pill" id="keyState"></span></summary><div class="body">
    <p class="hint">Google Cloud で「YouTube Data API v3」を有効にして作ったAPIキーを入れます(① 探す に必要。コメント欄の時刻の解析にも使います)。キーはこのパソコンの中にだけ保存し、画面には表示しません。</p>
    <details class="q-raw ui-disclosure"><summary>保存する場所</summary><code>作業データの config.json。環境変数 YOUTUBE_API_KEY があれば、そちらが優先されます</code></details>
    <div class="fld"><label class="l" for="keyIn">APIキー</label>
    <input type="password" id="keyIn" placeholder="AIza..." autocomplete="off" spellcheck="false"></div>
    <div class="row set-actions"><button type="button" class="btn small primary" id="keySave">保存</button><button type="button" class="btn small danger" id="keyDel">キーを削除</button></div>
    <p class="msg hint" id="keyMsg" role="status"></p></div></details>
  <details class="card set-sec" id="setOut" open><summary><span class="set-title">出力先フォルダ</span><span class="set-sub path" id="outSub"></span></summary><div class="body">
    <p class="hint">書き出した切り抜き(mp4)の保存先</p>
    <div class="set-path"><span class="path" id="outNow"></span><a class="btn small" id="outSetLink" href="../settings#sec-studio">設定の画面で変える</a></div>
    <p class="hint">空にすると標準(作業データの exports)。処理中は変えられません。次の書き出しから使います。</p></div></details>
  <details class="card set-sec" id="setOps"><summary><span class="set-title">② の操作</span><span class="set-sub" title="キー配置を変える・ライブのマークをまとめてずらす">キー配置・マークをまとめてずらす</span></summary><div class="body" id="opsHost"><p class="hint">読み込み中…</p></div></details>
  <details class="card set-sec" id="setCollab"><summary><span class="set-title">コラボ</span><span class="pill" id="collabBadge" hidden></span><span class="set-sub" title="複数人のコラボ配信をグループにまとめ、採用したマークを転写">複数人のコラボ配信をグループにまとめ、採用したマークを転写</span></summary><div class="body" id="collabHost"></div></details>
  <details class="card set-sec reg" id="setReg"><summary><span class="set-title">事務所の登録</span><span class="set-sub" title="事務所ごとの所属チャンネル(① 探す の検索対象)">事務所ごとの所属チャンネル(① 探す の検索対象)</span></summary><div class="body" id="regHost"></div></details>`;
  $('#keySave').addEventListener('click', () => saveKey($('#keyIn').value.trim(), $('#keySave')));
  /* キーを削除は取り消せない(もう一度貼り付けが要る)ので確認する(見直し M3。中止のような取り消せる操作は確認しない) */
  $('#keyDel').addEventListener('click', async () => {
    const b = $('#keyDel');
    if (S.state && S.state.hasKey){
      const ok = await UIKit.dialog.confirm({ title: 'API キーを削除しますか?', body: '保存してある YouTube Data API キーを消します。① 探す をまた使うには、キーをもう一度貼り付けます。', ok: '削除する', danger: true });
      if (!ok) return;
    }
    saveKey('', b);
  });
  $('#keyIn').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); $('#keySave').click(); } });
  $('#setCollab').addEventListener('toggle', mountCollab);
  $('#setReg').addEventListener('toggle', mountReg);
}

/* ---------- ライブの録画(線 D の P3。ライブの機能が使えるときだけ出す)----------
   0.25.0: 置き場所・画質・自動の作り直し・録画を消す・配信中の候補・自動採用・候補の文字起こし・友人へ届ける、は設定の画面(入口の /settings の
   「リアルタイム切り抜き」の節)へ。ここは今の置き場所と空きの表示だけ(入口の ../live/api/info と録画元の list)。
   設定の画面で変えた値は、引き出しを開いたとき・画面に戻ったときに読み直して ② の帯へ伝える(studio:liveprefs。以前は引き出しの欄で変えたときに送っていた) */
const GB = 1024 * 1024 * 1024;
const fmtBytes = b => (b == null || !Number.isFinite(Number(b)) ? '' : b >= GB ? (b / GB).toFixed(1) + ' GB' : Math.round(b / 1048576) + ' MB');
let liveBuilt = false, liveActive = 0;
function buildLive(){
  if (liveBuilt || !$('#setCollab')) return;
  liveBuilt = true;
  const sec = document.createElement('details');
  sec.className = 'card set-sec'; sec.id = 'setLive'; sec.open = true;
  sec.innerHTML = `<summary><span class="set-title">ライブの録画</span><span class="set-sub" title="配信を録画しながら切り抜くとき">配信を録画しながら切り抜くとき</span></summary><div class="body">
    <p class="hint">① の URL の欄か ② の「開く」に配信中・配信前の URL を入れると、録画を始めて ② で開きます。</p>
    <div class="set-path"><span class="l">録画の置き場所</span><span class="path" id="liveFolderNow"></span></div>
    <p class="hint" id="liveFree"></p>
    <p class="hint" id="liveFolderNote"></p>
    <div class="row set-actions"><a class="btn small" id="liveSetLink" href="../settings#sec-live">設定の画面で変える</a></div>
    <p class="hint">置き場所・画質・配信が終わったあとの自動の作り直し・録画を消す・配信中の候補と自動の採用・候補の文字起こし・友人へ届ける、は設定の画面の「リアルタイム切り抜き」の節にまとめました。</p></div>`;
  $('#setCollab').insertAdjacentElement('beforebegin', sec);
}
/* 今の置き場所・空きを読み直す(引き出しを開いたとき・画面に戻ったとき)。読めないところは空欄のまま(録画は続けられる)。
   読み直したあと、入口の設定 live を ② の帯へ伝える(設定の画面で変えた分) */
let liveSeq = 0;
async function refreshLive(){
  if (!liveBuilt) return;
  const seq = ++liveSeq;   // 開くたびに読み直す: 前の読み直しの遅い答えで、新しい表示を上書きしない
  const info = await S.live.refreshInfo();
  if (seq !== liveSeq) return;
  if (!info){ $('#setLive').hidden = true; return; }
  $('#setLive').hidden = false;
  let free = info.freeBytes, total = info.totalBytes, active = info.active, folder = info.folder || '';
  const rc = (info.recorders || [])[0];
  if ((free == null || active == null) && rc){   // 空き・録画中の数・実際の置き場所は録画元の一覧から(入口の info に無いとき)
    try { const l = await S.live.api('r/' + encodeURIComponent(rc.id) + '/list'); if (free == null){ free = l.freeBytes; total = l.totalBytes; } if (active == null) active = l.active; if (l.folder) folder = l.folder; } catch {}
    if (seq !== liveSeq) return;
  }
  $('#liveFolderNow').textContent = folder || info.defaultFolder || '(標準)';
  liveActive = Number(active) || 0;
  $('#liveFree').textContent = free != null ? `空き ${fmtBytes(free)}${total ? ' / ' + fmtBytes(total) : ''}` : '';
  $('#liveFolderNote').textContent = liveActive ? `録画中(${liveActive}本)は置き場所を変えられません。録画を止めてから設定の画面で変えます。` : '置き場所を変えると、次に始める録画から使います。';
  if (UIKit.prefs.available()){
    try {
      const p = await UIKit.prefs.get(['live']);
      if (seq === liveSeq && p && p.live) document.dispatchEvent(new CustomEvent('studio:liveprefs', { detail: p.live }));
    } catch {}
  }
}
function setupLive(){
  if (!S.live || !S.token) return;
  S.live.available().then(info => { if (!info) return; buildLive(); refreshLive(); }, () => {});
}

function mountReg(){
  if (regMounted || !$('#setReg').open) return;
  const host = $('#regHost');
  if (S.rank && S.rank.mountRegistry){ regMounted = true; S.rank.mountRegistry(host); }
  else host.innerHTML = '<p class="hint">登録の画面を読み込めませんでした(rank.js)。</p>';
}
function mountCollab(){
  if (!$('#setCollab').open) return;
  const host = $('#collabHost');
  if (S.collab && S.collab.mount) S.collab.mount(host);
  else host.innerHTML = '<p class="hint">コラボの画面を読み込めませんでした(collab.js)。</p>';
}

function update(){
  const t = S.state || {}, miss = [];
  if (!t.ffmpeg) miss.push('<b>ffmpeg</b> が見つかりません。Windows: <code>winget install Gyan.FFmpeg</code> / Mac: <code>brew install ffmpeg</code>(入れたらこのツールを起動し直す)');
  if (!t.ytdlp) miss.push('<b>yt-dlp</b> が見つかりません(YouTubeの解析・書き出しに必要)。Windows: <code>winget install yt-dlp.yt-dlp</code> / Mac: <code>brew install yt-dlp</code>。手元のファイルだけなら不要です');
  const tn = $('#toolNotice');
  tn.innerHTML = miss.length ? `<div class="notice" role="alert"><b>準備が必要です</b><br>${miss.join('<br>')}<br><span class="hint">詳しくは README を見てください。</span></div>` : '';
  tn.hidden = !miss.length;
  let ks = '未設定', kc = 'warn';
  if (t.fake && !t.keySource){ ks = '疑似モード(キー不要)'; kc = 'info'; }
  else if (t.keySource === 'env'){ ks = '設定済み(環境変数)'; kc = 'ok'; }
  else if (t.hasKey){ ks = '設定済み'; kc = 'ok'; }
  const k = $('#keyState'); k.textContent = ks; k.className = 'pill ' + kc;
  k.title = t.keySource === 'env' ? '環境変数 YOUTUBE_API_KEY を使用中' : '';
  /* 設定の「!」は「やることがある」印(API キーが未設定)。タブの件数(残っている作業の数)とは形も色も分けている */
  $('#settingsDot').hidden = !!t.hasKey; $('#settingsDotText').hidden = !!t.hasKey;
  $('#btnSettings').title = t.hasKey ? '設定(APIキー・出力先・ライブの録画・キー配置・コラボ・事務所の登録。ほかは設定の画面)' : '設定(API キーが未設定です。① 探す に必要)';
  /* 見出しの横は、長いときにフォルダの末尾が見えるように先頭を省く(CSS の direction:rtl。記号の並びが崩れないよう前後に LRM) */
  $('#outNow').textContent = t.outDir || ''; $('#outSub').textContent = t.outDir ? '\u200e' + t.outDir + '\u200e' : ''; $('#outSub').title = t.outDir || '';
}

/* ボタンを押している間は無効にして、二重に送らない */
async function busy(btn, fn){
  if (btn.disabled) return;
  btn.disabled = true;
  try { await fn(); } finally { btn.disabled = false; }
}
function saveKey(v, btn){
  return busy(btn, async () => {
    const m = $('#keyMsg'); m.textContent = '';
    // 以前は空欄のまま「保存」を押すと、保存済みのキーが消えていた(空文字 = 削除の API のため)。削除は「キーを削除」だけで行う
    if (btn.id === 'keySave' && !v){ m.textContent = 'キーを入力してください'; return; }
    if (btn.id === 'keyDel' && !(S.state && S.state.hasKey)){ m.textContent = 'キーは設定されていません'; return; }
    try {
      await S.api('/api/config', { method: 'PUT', body: { apiKey: v } });
      $('#keyIn').value = '';
      await S.refreshState();
      const env = S.state && S.state.keySource === 'env';
      m.textContent = (v ? '保存しました' : '削除しました') + (env ? '(環境変数のキーがあるので、そちらが使われます)' : '');
      S.toast(v ? 'APIキーを保存しました' : 'APIキーを削除しました', 3000, 'ok');
    } catch (e){ m.textContent = e.message; }
  });
}


/* 状態の取得(/api/ping・/api/state)が失敗しても ⚙ がずっと働かない、ということがないよう、器(引き出し)は
   S.onReady を待たずに今すぐ作る。toolEl はいったん「読み込み中…」のまま渡し、中身(build/update。S.state が要る)は
   state が読めてから onReady で差し替える */
UIKit.settings.mount({ tool: toolEl, title: '設定', version: 'v' + S.version });
/* #btnSettings の aria-expanded を、引き出しの開閉(ui-kit の 'ui-drawer' イベント)に合わせる */
document.addEventListener('ui-drawer', e => {
  const d = e.detail || {};
  if (d.el && d.el.id === 'uiSettingsDrawer'){
    const b = $('#btnSettings'); if (b) b.setAttribute('aria-expanded', String(!!d.open));
    if (d.open && S.ready){ if (liveBuilt) refreshLive(); else setupLive(); }   // ライブの録画: 開くたびに置き場所・空きを読み直す(オンにされたばかりなら節を作る)
  }
});

S.onReady(() => {
  const tn = document.createElement('div'); tn.id = 'toolNotice'; tn.className = 'tool-notice'; tn.hidden = true;
  $('#main').insertAdjacentElement('beforebegin', tn);
  // toolEl はすでに文書につながっている(上の mount)。build() は document.querySelector で中の部品を探すので、ここで中身を作る
  build(); update();
  setupLive();
  UIKit.life.onReturn(() => { if (liveBuilt) refreshLive(); });   // 設定の画面で変えて戻ってきたら、置き場所と live の設定を読み直す(0.25.0)
  S.on('state', update);
  /* which: 開く節の id(setKey / setOut / setOps / setLive / setCollab / setReg)。引き出しの中でその節までスクロールする */
  S.openSettings = which => {
    S.drawer.open();
    const d = which && $('#' + which);
    if (d){ d.open = true; mountReg(); mountCollab(); requestAnimationFrame(() => d.scrollIntoView({ block: 'start', behavior: 'smooth' })); }
  };
});
})();
