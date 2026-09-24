/* 切り抜きスタジオ: 設定(右の引き出し: APIキー / 出力先フォルダ / 事務所の登録)と、ffmpeg・yt-dlp が無いときのお知らせ */
(() => {
'use strict';
const $ = s => document.querySelector(s);
const S = window.Studio;
let regMounted = false;

function build(){
  $('#settingsBody').innerHTML = `
  <details class="card set-sec" id="setKey" open><summary><span class="set-title">YouTube Data API キー</span><span class="pill" id="keyState"></span></summary><div class="body">
    <p class="hint">Google Cloud で「YouTube Data API v3」を有効にして作ったAPIキーを入れます(① 探す に必要。コメント欄の時刻の解析にも使います)。キーはこのパソコンの config.json にだけ保存し、画面には表示しません。環境変数 <code>YOUTUBE_API_KEY</code> があれば、そちらが優先されます。</p>
    <div class="fld"><label class="l" for="keyIn">APIキー</label>
    <input type="password" id="keyIn" placeholder="AIza..." autocomplete="off" spellcheck="false"></div>
    <div class="row set-actions"><button type="button" class="btn small primary" id="keySave">保存</button><button type="button" class="btn small danger" id="keyDel">キーを削除</button></div>
    <p class="msg hint" id="keyMsg" role="status"></p></div></details>
  <details class="card set-sec" id="setOut" open><summary><span class="set-title">出力先フォルダ</span><span class="set-sub path" id="outSub"></span></summary><div class="body">
    <p class="hint">書き出したクリップの保存先</p>
    <div class="set-path"><span class="path" id="outNow"></span><button type="button" class="btn small" id="btnOutEdit" aria-expanded="false" aria-controls="outEdit">変更</button></div>
    <div id="outEdit" hidden><div class="fld"><label class="l" for="outIn">新しい出力先(フルパス)</label>
      <input type="text" id="outIn" placeholder="例: D:\\clips  /  /Users/you/Movies/clips(フルパス)" spellcheck="false" autocomplete="off"></div>
      <div class="row set-actions"><button type="button" class="btn small primary" id="outSave">保存</button><button type="button" class="btn small" id="outReset">標準に戻す</button></div></div>
    <p class="msg hint" id="outMsg" role="status"></p></div></details>
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
  $('#setReg').addEventListener('toggle', mountReg);
}

function mountReg(){
  if (regMounted || !$('#setReg').open) return;
  const host = $('#regHost');
  if (S.rank && S.rank.mountRegistry){ regMounted = true; S.rank.mountRegistry(host); }
  else host.innerHTML = '<p class="hint">登録の画面を読み込めませんでした(rank.js)。</p>';
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
  $('#settingsDot').hidden = !!t.hasKey;
  $('#outNow').textContent = t.outDir || ''; $('#outSub').textContent = t.outDir || ''; $('#outSub').title = t.outDir || '';
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

S.onReady(() => {
  const tn = document.createElement('div'); tn.id = 'toolNotice'; tn.className = 'tool-notice'; tn.hidden = true;
  $('#main').insertAdjacentElement('beforebegin', tn);
  build(); update();
  S.on('state', update);
  /* which: 開く節の id(setKey / setOut / setReg)。引き出しの中でその節までスクロールする */
  S.openSettings = which => {
    S.drawer.open();
    const d = which && $('#' + which);
    if (d){ d.open = true; mountReg(); requestAnimationFrame(() => d.scrollIntoView({ block: 'start', behavior: 'smooth' })); }
  };
});
})();
