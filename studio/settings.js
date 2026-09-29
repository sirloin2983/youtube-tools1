/* 切り抜きスタジオ: 設定(右の引き出し: APIキー / 出力先フォルダ / 事務所の登録)と、ffmpeg・yt-dlp が無いときのお知らせ */
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
    <p class="hint">Google Cloud で「YouTube Data API v3」を有効にして作ったAPIキーを入れます(① 探す に必要。コメント欄の時刻の解析にも使います)。キーはこのパソコンの config.json にだけ保存し、画面には表示しません。環境変数 <code>YOUTUBE_API_KEY</code> があれば、そちらが優先されます。</p>
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
  <details class="card set-sec" id="setExport" open><summary><span class="set-title">書き出し</span><span class="set-sub">書き出したあとの自動化</span></summary><div class="body">
    ${S.token ? `<label class="rv-check" for="setAutoTx"><input type="checkbox" class="ui-switch" id="setAutoTx">書き出しのあと自動で文字起こしを始める</label>
    <p class="hint">③ の書き出しが終わった切り抜きを、ホームの「まとめて実行」と同じ仕組みで自動的に文字起こしします(すでに実行中の配信は、あとで「この後を ▸」からやり直せます)。</p>`
    : '<p class="hint">ホーム(start.bat)から開いているときだけ使えます。</p>'}
  </div></details>
  <details class="card set-sec" id="setCollab"><summary><span class="set-title">コラボ</span><span class="pill" id="collabBadge" hidden></span><span class="set-sub">複数人のコラボ配信をグループにまとめ、採用したマークを転写</span></summary><div class="body" id="collabHost"></div></details>
  <details class="card set-sec reg" id="setReg"><summary><span class="set-title">事務所の登録</span><span class="set-sub">事務所ごとの所属チャンネル(① 探す の検索対象)</span></summary><div class="body" id="regHost"></div></details>`;
  $('#keySave').addEventListener('click', () => saveKey($('#keyIn').value.trim(), $('#keySave')));
  $('#keyDel').addEventListener('click', () => saveKey('', $('#keyDel')));
  $('#keyIn').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); $('#keySave').click(); } });
  $('#btnOutEdit').addEventListener('click', () => {
    const e = $('#outEdit'); e.hidden = !e.hidden; $('#btnOutEdit').setAttribute('aria-expanded', String(!e.hidden));
    if (!e.hidden){ const t = S.state || {}; $('#outIn').value = t.outDir && t.outDir !== t.defaultOutDir ? t.outDir : ''; $('#outIn').focus(); }
  });
  $('#outIn').addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); $('#outSave').click(); } });
  $('#outSave').addEventListener('click', () => saveOut($('#outIn').value.trim(), $('#outSave')));
  $('#outReset').addEventListener('click', () => saveOut('', $('#outReset')));
  if (S.token){
    const cb = $('#setAutoTx');
    let on = true; try { on = localStorage.getItem('ytt:studio.autoTx') !== '0'; } catch {}
    cb.checked = on;
    cb.addEventListener('change', () => { try { localStorage.setItem('ytt:studio.autoTx', cb.checked ? '1' : '0'); } catch {} });
  }
  $('#setCollab').addEventListener('toggle', mountCollab);
  $('#setReg').addEventListener('toggle', mountReg);
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
  $('#btnSettings').title = t.hasKey ? '設定(APIキー・出力先フォルダ・事務所の登録)' : '設定(API キーが未設定です。① 探す に必要)';
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
  if (d.el && d.el.id === 'uiSettingsDrawer'){ const b = $('#btnSettings'); if (b) b.setAttribute('aria-expanded', String(!!d.open)); }
});

S.onReady(() => {
  const tn = document.createElement('div'); tn.id = 'toolNotice'; tn.className = 'tool-notice'; tn.hidden = true;
  $('#main').insertAdjacentElement('beforebegin', tn);
  // toolEl はすでに文書につながっている(上の mount)。build() は document.querySelector で中の部品を探すので、ここで中身を作る
  build(); update();
  S.on('state', update);
  /* which: 開く節の id(setKey / setOut / setExport / setCollab / setReg)。引き出しの中でその節までスクロールする */
  S.openSettings = which => {
    S.drawer.open();
    const d = which && $('#' + which);
    if (d){ d.open = true; mountReg(); mountCollab(); requestAnimationFrame(() => d.scrollIntoView({ block: 'start', behavior: 'smooth' })); }
  };
});
})();
