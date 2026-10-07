/* 切り抜きスタジオ: 設定(右の引き出し: APIキー / 出力先フォルダ / 書き出し / ③ の操作(中身は review.js が #opsHost に入れる)/ コラボ / 事務所の登録)と、ffmpeg・yt-dlp が無いときのお知らせ */
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
  <details class="card set-sec" id="setKey" open><summary><span class="set-title">YouTube Data API キー</span><span class="pill" id="keyState"></span></summary><div class="body">
    <p class="hint">Google Cloud で「YouTube Data API v3」を有効にして作ったAPIキーを入れます(① 探す に必要。コメント欄の時刻の解析にも使います)。キーはこのパソコンの中にだけ保存し、画面には表示しません。</p>
    <details class="q-raw ui-disclosure"><summary>保存する場所</summary><code>作業データの config.json。環境変数 YOUTUBE_API_KEY があれば、そちらが優先されます</code></details>
    <div class="fld"><label class="l" for="keyIn">APIキー</label>
    <input type="password" id="keyIn" placeholder="AIza..." autocomplete="off" spellcheck="false"></div>
    <div class="row set-actions"><button type="button" class="btn small primary" id="keySave">保存</button><button type="button" class="btn small danger" id="keyDel">キーを削除</button></div>
    <p class="msg hint" id="keyMsg" role="status"></p></div></details>
  <details class="card set-sec" id="setOut" open><summary><span class="set-title">出力先フォルダ</span><span class="set-sub path" id="outSub"></span></summary><div class="body">
    <p class="hint">書き出した切り抜き(mp4)の保存先</p>
    <div class="set-path"><span class="path" id="outNow"></span><button type="button" class="btn small" id="btnOutEdit" aria-expanded="false" aria-controls="outEdit">変更</button></div>
    <div id="outEdit" hidden><div class="fld"><label class="l" for="outIn">新しい出力先(フルパス)</label>
      <input type="text" id="outIn" placeholder="例: D:\\clips  /  /Users/you/Movies/clips(フルパス)" spellcheck="false" autocomplete="off"></div>
      <div class="row set-actions"><button type="button" class="btn small primary" id="outSave">保存</button><button type="button" class="btn small" id="outReset">標準に戻す</button></div></div>
    <p class="msg hint" id="outMsg" role="status"></p></div></details>
  <details class="card set-sec" id="setExport" open><summary><span class="set-title">書き出し</span><span class="set-sub" title="書き出したあとの自動化">書き出したあとの自動化</span></summary><div class="body">
    ${S.token ? `<label class="rv-check" for="setAutoTx"><input type="checkbox" class="ui-switch" id="setAutoTx">書き出しのあと自動で文字起こしを始める</label>
    <p class="hint">③ の書き出しが終わった切り抜きを、ホームの「まとめて実行」と同じ仕組みで自動的に文字起こしします(すでに実行中の配信は、あとでマークの行の「この後を」からやり直せます)。この設定はスタジオに保存します(窓とブラウザのどちらで開いても同じ)。</p>`
    : '<p class="hint">ホーム(start.bat)から開いているときだけ使えます。</p>'}
  </div></details>
  <details class="card set-sec" id="setOps"><summary><span class="set-title">③ の操作</span><span class="set-sub" title="音量・確認の進め方・マークの付け方・キー配置・ライブ配信">音量・確認の進め方・マークの付け方・キー配置・ライブ配信</span></summary><div class="body" id="opsHost"><p class="hint">読み込み中…</p></div></details>
  <details class="card set-sec" id="setCollab"><summary><span class="set-title">コラボ</span><span class="pill" id="collabBadge" hidden></span><span class="set-sub" title="複数人のコラボ配信をグループにまとめ、採用したマークを転写">複数人のコラボ配信をグループにまとめ、採用したマークを転写</span></summary><div class="body" id="collabHost"></div></details>
  <details class="card set-sec reg" id="setReg"><summary><span class="set-title">事務所の登録</span><span class="set-sub" title="事務所ごとの所属チャンネル(① 探す の検索対象)">事務所ごとの所属チャンネル(① 探す の検索対象)</span></summary><div class="body" id="regHost"></div></details>`;
  $('#keySave').addEventListener('click', () => saveKey($('#keyIn').value.trim(), $('#keySave')));
  /* キーを削除は取り消せない(もう一度貼り付けが要る)ので確認する(見直し M3。中止のような取り消せる操作は確認しない) */
  $('#keyDel').addEventListener('click', async () => {
    const b = $('#keyDel');
    if (S.state && S.state.hasKey && window.UIKit && UIKit.dialog){
      const ok = await UIKit.dialog.confirm({ title: 'API キーを削除しますか?', body: '保存してある YouTube Data API キーを消します。① 探す をまた使うには、キーをもう一度貼り付けます。', ok: '削除する', danger: true });
      if (!ok) return;
    }
    saveKey('', b);
  });
  $('#keyIn').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); $('#keySave').click(); } });
  $('#btnOutEdit').addEventListener('click', () => {
    const e = $('#outEdit'); e.hidden = !e.hidden; $('#btnOutEdit').setAttribute('aria-expanded', String(!e.hidden));
    if (!e.hidden){ const t = S.state || {}; $('#outIn').value = t.outDir && t.outDir !== t.defaultOutDir ? t.outDir : ''; $('#outIn').focus(); }
  });
  $('#outIn').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); $('#outSave').click(); } });
  $('#outSave').addEventListener('click', () => saveOut($('#outIn').value.trim(), $('#outSave')));
  $('#outReset').addEventListener('click', () => saveOut('', $('#outReset')));
  /* 書き出しのあと自動で文字起こし: 値は ③ の設定(サーバーの /api/settings の review.autoTx。0.22.0 でこのブラウザの localStorage から移した)。
     読み込みと保存は review.js(読み込めたら、このスイッチも合わせる)。ここは押したときに渡すだけ */
  if (S.token){
    const cb = $('#setAutoTx');
    cb.checked = !(S.review && S.review.autoTx) || S.review.autoTx();
    cb.addEventListener('change', () => { if (S.review && S.review.setAutoTx) S.review.setAutoTx(cb.checked); });
  }
  $('#setCollab').addEventListener('toggle', mountCollab);
  $('#setReg').addEventListener('toggle', mountReg);
}

/* ---------- ライブの録画(線 D の P3。ライブの機能が使えるときだけ出す)----------
   置き場所・画質はホームの設定の節 live(UIKit.prefs。入口の録画の部品が読む)。置き場所の今の値と空きは入口の ../live/api/info(と録画元の list) */
const GB = 1024 * 1024 * 1024;
const fmtBytes = b => (b == null || !Number.isFinite(Number(b)) ? '' : b >= GB ? (b / GB).toFixed(1) + ' GB' : Math.round(b / 1048576) + ' MB');
const LIVE_QUALITY = [['best', 'いちばん良い画質'], ['1080p', '1080p(おすすめ)'], ['720p', '720p(容量を抑える)']];
let liveBuilt = false, liveActive = 0;
function buildLive(){
  if (liveBuilt || !$('#setCollab')) return;
  liveBuilt = true;
  const sec = document.createElement('details');
  sec.className = 'card set-sec'; sec.id = 'setLive'; sec.open = true;
  sec.innerHTML = `<summary><span class="set-title">ライブの録画</span><span class="set-sub" title="配信を録画しながら切り抜くとき">配信を録画しながら切り抜くとき</span></summary><div class="body">
    <p class="hint">② の URL 欄か ③ の「開く」に配信中・配信前の URL を入れると、録画を始めて ③ で開きます。</p>
    <div class="set-path"><span class="l">録画の置き場所</span><span class="path" id="liveFolderNow"></span></div>
    <p class="hint" id="liveFree"></p>
    <div class="fld"><label class="l" for="liveFolderIn">新しい置き場所(フルパス。空にすると標準)</label>
      <input type="text" id="liveFolderIn" spellcheck="false" autocomplete="off"></div>
    <div class="row set-actions"><button type="button" class="btn small primary" id="liveFolderSave">置き場所を保存</button></div>
    <p class="hint" id="liveFolderNote">録画中は変えられません(録画を止めてから変えます)。変えると、次に始める録画から使います。</p>
    <div class="fld"><label class="l" for="liveQuality">画質</label>
      <select id="liveQuality">${LIVE_QUALITY.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>
      <span class="hint">次に始める録画から使います</span></div>
    <label class="rv-check" for="liveAutoArch"><input type="checkbox" class="ui-switch" id="liveAutoArch" checked>配信が終わったら、自動で本番版に作り直す</label>
    <p class="hint">アーカイブが用意できてから作り直します(翌日になることもあります)。書き出した切り抜きを、同じ名前のまま本番の画質に入れ替えます。③ の帯の「アーカイブで作り直す」でも始められます。</p>
    <label class="rv-check" for="liveAutoDel"><input type="checkbox" class="ui-switch" id="liveAutoDel">本番版に入れ替えたら録画を消す(マークが無い録画は 1 日で消す)</label>
    <p class="hint">録画は 1 時間で 3〜4GB 使います。マークと本番版の切り抜きはそのまま使えます。入れ替えで作業用のフォルダへ移した速報版は、7 日たったら消します。</p>
    <p class="msg hint" id="liveMsg" role="status"></p></div>`;
  $('#setCollab').insertAdjacentElement('beforebegin', sec);
  $('#liveFolderIn').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); $('#liveFolderSave').click(); } });
  $('#liveFolderSave').addEventListener('click', () => busy($('#liveFolderSave'), async () => {
    const m = $('#liveMsg'), f = $('#liveFolderIn').value.trim();
    if (liveActive){ m.textContent = '録画中は置き場所を変えられません。録画を止めてから変えてください'; return; }
    m.textContent = '保存しています…';
    try {
      await UIKit.prefs.patch('live', { folder: f });
      m.textContent = f ? '置き場所を保存しました。次に始める録画から使います' : '標準の置き場所に戻しました';
      $('#liveFolderIn').value = '';
      setTimeout(refreshLive, 1500);   // 録画の部品に伝わってから読み直す
    } catch (e){ m.textContent = '保存できませんでした: ' + e.message; }
  }));
  $('#liveQuality').addEventListener('change', e => {
    const q = LIVE_QUALITY.some(([v]) => v === e.target.value) ? e.target.value : '1080p';
    UIKit.prefs.patch('live', { quality: q }).then(() => { $('#liveMsg').textContent = '画質を ' + q + ' にしました(次に始める録画から)'; }, () => {});   // 失敗の知らせは UIKit.prefs が出す
  });
  /* オン・オフの設定(ホームの設定の節 live。入口が読む)。保存できたら ③ の帯の案内にも伝える(studio:liveprefs)。失敗の知らせは UIKit.prefs が出す */
  const liveSwitch = (id, key, onText, offText) => $(id).addEventListener('change', e => {
    const on = e.target.checked;
    UIKit.prefs.patch('live', { [key]: on }).then(() => {
      $('#liveMsg').textContent = on ? onText : offText;
      document.dispatchEvent(new CustomEvent('studio:liveprefs', { detail: { [key]: on } }));
    }, () => {});
  });
  /* 本番版への自動の作り直し(線 D の P4。live.autoArchive。既定オン)。帯の案内は「自動: オン/オフ」 */
  liveSwitch('#liveAutoArch', 'autoArchive', '配信が終わったら、自動で本番版に作り直します', '自動の作り直しをやめました(③ の帯の「アーカイブで作り直す」で始められます)');
  /* 録画を自動で消す(線 D の P4。live.autoDelete)。帯の案内は「入れ替えたら録画は消します」 */
  liveSwitch('#liveAutoDel', 'autoDelete', '本番版に入れ替えたら、録画を消します(マークが無い録画は 1 日で消します)', '録画を自動では消しません(録画の置き場所の空きに気をつけてください)');
}
/* 今の置き場所・空き・画質を読み直す(引き出しを開いたとき)。読めないところは空欄のまま(録画は続けられる) */
let liveSeq = 0;
async function refreshLive(){
  if (!liveBuilt) return;
  const seq = ++liveSeq;   // 開くたびに読み直す: 前の読み直しの遅い答えで、新しい表示を上書きしない
  const info = await S.live.refreshInfo();
  if (seq !== liveSeq) return;
  if (!info){ $('#setLive').hidden = true; return; }
  $('#setLive').hidden = false;
  $('#liveFolderIn').placeholder = info.defaultFolder ? '標準: ' + info.defaultFolder : '例: D:\\recordings';
  let free = info.freeBytes, total = info.totalBytes, active = info.active, folder = info.folder || '';
  const rc = (info.recorders || [])[0];
  if ((free == null || active == null) && rc){   // 空き・録画中の数・実際の置き場所は録画元の一覧から(入口の info に無いとき)
    try { const l = await S.live.api('r/' + encodeURIComponent(rc.id) + '/list'); if (free == null){ free = l.freeBytes; total = l.totalBytes; } if (active == null) active = l.active; if (l.folder) folder = l.folder; } catch {}
    if (seq !== liveSeq) return;
  }
  /* 置き場所は全部そろってから1回で出す(以前は先に標準の置き場所を出してから録画元の答えで差し替えていて、読み直しの間だけ違う場所に見えた) */
  $('#liveFolderNow').textContent = folder || info.defaultFolder || '(標準)';
  liveActive = Number(active) || 0;
  $('#liveFree').textContent = free != null ? `空き ${fmtBytes(free)}${total ? ' / ' + fmtBytes(total) : ''}` : '';
  $('#liveFolderIn').disabled = $('#liveFolderSave').disabled = !!liveActive;
  $('#liveFolderNote').textContent = liveActive ? `録画中(${liveActive}本)は置き場所を変えられません。録画を止めてから変えます。` : '録画中は変えられません(録画を止めてから変えます)。変えると、次に始める録画から使います。';
  if (window.UIKit && UIKit.prefs && UIKit.prefs.available()){
    try {
      const p = await UIKit.prefs.get(['live']), l = (p && p.live) || {}, q = l.quality;
      $('#liveQuality').value = LIVE_QUALITY.some(([v]) => v === q) ? q : '1080p';
      $('#liveAutoArch').checked = l.autoArchive !== false;   // 既定オン
      $('#liveAutoDel').checked = l.autoDelete === true;     // 入口と同じく true のときだけ(既定は home/prefs.py)
    } catch {}
  } else $('#liveAutoArch').disabled = $('#liveAutoDel').disabled = true;
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
  $('#btnSettings').title = t.hasKey ? '設定(APIキー・出力先フォルダ・③ の操作・コラボ・事務所の登録)' : '設定(API キーが未設定です。① 探す に必要)';
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

function saveOut(path, btn){
  return busy(btn, async () => {
    const m = $('#outMsg'); m.textContent = '';
    try {
      await S.api('/api/outdir', { method: 'PUT', body: { path } });
      await S.refreshState();
      $('#outEdit').hidden = true; $('#btnOutEdit').setAttribute('aria-expanded', 'false');
      m.textContent = (path ? '出力先を変更しました' : '標準に戻しました') + '。次の書き出しから使います';
    } catch (e){ m.textContent = e.message; }   // 400(入力の誤り)・409(実行中は変更不可)はサーバーの日本語メッセージをそのまま表示
  });
}

/* 状態の取得(/api/ping・/api/state)が失敗しても ⚙ がずっと働かない、ということがないよう、器(引き出し)は
   S.onReady を待たずに今すぐ作る。toolEl はいったん「読み込み中…」のまま渡し、中身(build/update。S.state が要る)は
   state が読めてから onReady で差し替える */
if (window.UIKit && UIKit.settings) UIKit.settings.mount({ tool: toolEl, title: '設定', version: 'v' + S.version });
else document.body.appendChild(toolEl);   // 保険(通常は起きない): UIKit が無くても壊さない
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
  S.on('state', update);
  /* which: 開く節の id(setKey / setOut / setExport / setOps / setCollab / setReg)。引き出しの中でその節までスクロールする */
  S.openSettings = which => {
    S.drawer.open();
    const d = which && $('#' + which);
    if (d){ d.open = true; mountReg(); mountCollab(); requestAnimationFrame(() => d.scrollIntoView({ block: 'start', behavior: 'smooth' })); }
  };
});
})();
