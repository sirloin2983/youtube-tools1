/* 切り抜きスタジオ: 設定パネル(APIキー / 出力先フォルダ / 事務所の登録)と、ffmpeg・yt-dlp が無いときのお知らせ */
(() => {
'use strict';
const $ = s => document.querySelector(s);
const S = window.Studio;
let regMounted = false;

function build(){
  $('#settingsBody').innerHTML = `
  <details class="set-sec" id="setKey"><summary>YouTube Data API キー<span class="sub" id="keyState"></span></summary><div class="body">
    <p class="hint" style="margin:0 0 6px">Google Cloud で「YouTube Data API v3」を有効にして作ったAPIキーを入れます(① 探す に必要。コメント欄の時刻の解析にも使います)。キーはこのパソコンの config.json にだけ保存し、画面には表示しません。環境変数 <code>YOUTUBE_API_KEY</code> があれば、そちらが優先されます。</p>
    <label class="hint" for="keyIn">APIキー</label>
    <input type="password" id="keyIn" placeholder="AIza..." autocomplete="off" spellcheck="false">
    <div class="row" style="margin-top:8px"><button type="button" class="btn small primary" id="keySave">保存</button><button type="button" class="btn small" id="keyDel">キーを削除</button></div>
    <p class="msg hint" id="keyMsg" role="status"></p></div></details>
  <details class="set-sec" id="setOut"><summary>出力先フォルダ<span class="sub path" id="outSub"></span></summary><div class="body">
    <p class="hint" style="margin:0">書き出したクリップの保存先: <span class="path" id="outNow"></span> <button type="button" class="btn small" id="btnOutEdit">変更</button></p>
    <div class="row" id="outEdit" style="margin-top:6px" hidden><label class="hint" for="outIn" style="width:100%">新しい出力先(フルパス)</label>
      <input type="text" id="outIn" style="flex:1;min-width:200px" placeholder="例: D:\\clips  /  /Users/you/Movies/clips(フルパス)" spellcheck="false" autocomplete="off">
      <button type="button" class="btn small primary" id="outSave">保存</button><button type="button" class="btn small" id="outReset">標準に戻す</button></div>
    <p class="msg hint" id="outMsg" role="status"></p></div></details>
  <details class="set-sec reg" id="setReg"><summary>事務所の登録<span class="sub">事務所ごとの所属チャンネル(① 探す の検索対象)</span></summary><div class="body" id="regHost"></div></details>`;
  $('#keySave').addEventListener('click', () => saveKey($('#keyIn').value.trim()));
  $('#keyDel').addEventListener('click', () => saveKey(''));
  $('#btnOutEdit').addEventListener('click', () => {
    const e = $('#outEdit'); e.hidden = !e.hidden;
    if (!e.hidden){ const t = S.state || {}; $('#outIn').value = t.outDir && t.outDir !== t.defaultOutDir ? t.outDir : ''; $('#outIn').focus(); }
  });
  $('#outSave').addEventListener('click', () => saveOut($('#outIn').value.trim()));
  $('#outReset').addEventListener('click', () => saveOut(''));
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
  let ks = '未設定';
  if (t.fake && !t.keySource) ks = '疑似モード(キー不要)';
  else if (t.keySource === 'env') ks = '設定済み(環境変数 YOUTUBE_API_KEY を使用中)';
  else if (t.hasKey) ks = '設定済み';
  $('#keyState').textContent = ks;
  $('#outNow').textContent = t.outDir || ''; $('#outSub').textContent = t.outDir || '';
}

async function saveKey(v){
  const m = $('#keyMsg'); m.textContent = '';
  if (v === '' && !(S.state && S.state.hasKey)){ m.textContent = 'キーは設定されていません'; return; }
  try {
    await S.api('/api/config', { method: 'PUT', body: { apiKey: v } });
    $('#keyIn').value = '';
    await S.refreshState();
    const env = S.state && S.state.keySource === 'env';
    m.textContent = (v ? '保存しました' : '削除しました') + (env ? '(環境変数のキーがあるので、そちらが使われます)' : '');
  } catch (e){ m.textContent = e.message; }
}

async function saveOut(path){
  const m = $('#outMsg'); m.textContent = '';
  try {
    await S.api('/api/outdir', { method: 'PUT', body: { path } });
    await S.refreshState();
    $('#outEdit').hidden = true; m.textContent = (path ? '出力先を変更しました' : '標準に戻しました') + '。次の書き出しから使います';
  } catch (e){ m.textContent = e.message; }   // 400(入力の誤り)・409(実行中は変更不可)はサーバーの日本語メッセージをそのまま表示
}

S.onReady(() => {
  const tn = document.createElement('div'); tn.id = 'toolNotice'; tn.className = 'tool-notice'; tn.hidden = true;
  $('#settingsBox').insertAdjacentElement('beforebegin', tn);
  build(); update();
  S.on('state', update);
  S.openSettings = which => { const b = $('#settingsBox'); b.open = true; const d = which && $('#' + which); if (d) d.open = true; b.scrollIntoView({ block: 'start' }); };
});
})();
