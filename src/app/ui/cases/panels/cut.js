/* 案件の画面の「カット・パック」のパネル(#cut。残す区間を決めて、末尾で DaVinci Resolve へ渡すパックを作る)。口の形は cases.js の先頭の説明。RS8 C2c。
   中身は 2 カット(src/app/ui/editor/cut.js = EditCut)とパック(src/app/ui/editor/pack-tab.js = EditPack)。
   ここが持つのは (1) 画面の骨組み(パックの設定の節 #edSetPack も画面の中に置く。「予備」の欄は決定 3-34 で置かない。10-24 画面の見直し: パックは
       様子の帯 #pkStatus → 「パックを作る」→ これから作るパック → 閉じた 1 行 3 つ(パックの設定 #pkSetFold・字幕の見本 #pkLookFold・詳しく #pkMore))、
   (2) cut.js / pack-tab.js に渡す「host」(文書 S・保存・元に戻す・字幕の積み方・話者の色・cut2resolve の口)、
   (3) 殻の口(mount / update / unmount / keys / keybar / leave / back)との橋。
   パネルの中の要素は root.querySelector で引く(document.getElementById・document.querySelector は使わない)。API は ctx.api('transcribe' | 'cut2resolve' | 'home', …) の相対パス。
   cut.js・pack-tab.js は /transcribe/ から読む(同じ入口の中。CSP の script-src 'self')。窓へ付ける keydown は付けず、殻の keydown 1 本から keys(e) で渡す */
(function () {
  'use strict';

  var SCRIPTS = ['transcribe/doc-kit.js', 'transcribe/cut.js', 'transcribe/pack-tab.js'];
  var LOADED_AS = { 'transcribe/doc-kit.js': 'EditDoc', 'transcribe/cut.js': 'EditCut', 'transcribe/pack-tab.js': 'EditPack' };
  var scriptsP = null;
  var D = null;   // window.EditDoc(文書の小さな部品。読み込んだあとに入る)
  function loadScripts() {
    if (window.EditDoc && window.EditCut && window.EditPack) { D = window.EditDoc; return Promise.resolve(); }
    if (scriptsP) return scriptsP;
    scriptsP = SCRIPTS.reduce(function (p, src) {
      return p.then(function () {
        if (window[LOADED_AS[src]]) return null;   // 校正の台(edhost.js)が先に読んだ部品は読み直さない
        return UIKit.loadScript(src);
      });
    }, Promise.resolve()).then(function () { D = window.EditDoc; }, function (e) { scriptsP = null; throw e; });
    return scriptsP;
  }

  /* 2 カットの節(#tabCut)の骨組み。id は cut.js / pack-tab.js が引く名前のまま */
  var TEMPLATE = `
<section id="tabCut">
 <div class="notice tt-cut-off" id="cutOff" hidden role="status"><span id="cutOffMsg"></span><button type="button" class="btn small" id="cutRetry" hidden>もう一度読み込む</button></div>
 <div class="notice err" id="cutDocConflict" hidden role="alert"><b>文字起こしの保存が競合しています。</b>字幕の段の行の時刻は、今は動かせません。別の場所で先に更新された文字起こしを読み直してください。
   <button type="button" class="btn small" id="cutDocConflictGo">文字起こしを読み直す(この画面の未保存の変更は消えます)</button></div>
 <div class="notice err" id="cutConflict" hidden role="alert"><b>別のタブか窓で、先にカットが保存されています。</b>自動保存は止めています。
   <div class="row" style="margin-top:6px"><button type="button" class="btn small" id="cutReload">保存されているカットを読み直す(この画面の未保存の変更は消えます)</button><button type="button" class="btn small danger" id="cutForce">この画面のカットで上書きする</button></div></div>
 <div class="tt-cut-top">
   <div class="card tt-cut-prev">
     <div class="tt-cut-video"><video id="cutPlayer" preload="metadata" playsinline></video><span class="pill info tt-cut-mode-pill" id="cutModePill">カット後の見え方</span><div class="tt-cut-cap tt-cap-look" id="cutCaption" hidden></div></div>
     <div class="tt-cut-ctrl">
       <button type="button" class="btn small icon" id="cutPlay" aria-label="再生・停止" title="再生・停止(Space)"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg></button>
       <span class="tt-cut-time"><b class="mono" id="cutTimeSrc">0:00.00</b> <span class="hint">元</span> <b class="mono tt-acc" id="cutTimeOut">0:00.00</b> <span class="hint">カット後 / <span class="mono" id="cutTotal">0:00.00</span></span></span>
       <div class="ui-seg tt-cut-mode" role="group" aria-label="プレビュー"><button type="button" id="cutModeSrc" aria-pressed="false" title="削る区間も含めて、元の動画のまま再生します">元の動画</button><button type="button" id="cutModeCut" aria-pressed="true" title="削る区間を飛ばして再生します(Resolve に入れたときの見え方)">カット後</button></div>
     </div>
   </div>
   <div class="card tt-cut-subs">
     <div class="tt-cut-subs-head"><b>字幕(文字起こしの行)</b><span class="hint">押すとその位置へ</span></div>
     <div class="tt-cut-subs-list" id="cutSubs" role="list" aria-label="字幕の一覧"></div>
     <p class="hint tt-cut-subs-foot">文字を直すのは <b>校正</b> のタブ</p>
   </div>
 </div>
 <div class="tt-cut-tools" role="toolbar" aria-label="カットの道具">
   <button type="button" class="btn small" id="cutSplit" title="再生位置(赤い線)で、残す区間を2つに分けます(S)"><span class="ui-icon" data-icon="scissors" aria-hidden="true"></span>分割 <kbd>S</kbd></button>
   <button type="button" class="btn small" id="cutDel" title="選んだ残す区間を削る / 選んだ削る区間を戻す(Del)">削る / 戻す <kbd>Del</kbd></button>
   <button type="button" class="btn small" id="cutIO" title="始まりの印から終わりの印までを削ります(H)"><span id="cutIOLabel">I〜O を削る</span> <kbd>H</kbd></button>
   <span class="tt-sep" aria-hidden="true"></span>
   <button type="button" class="btn small ghost" id="cutUndo" title="元に戻す(Ctrl+Z)"><span class="ui-icon" data-icon="undo" aria-hidden="true"></span>元に戻す <kbd>Ctrl+Z</kbd></button>
   <button type="button" class="btn small ghost" id="cutRedo" title="やり直す(Ctrl+Shift+Z)"><span class="ui-icon" data-icon="redo" aria-hidden="true"></span>やり直す</button>
   <span class="tt-sep" aria-hidden="true"></span>
   <span class="hint">たたき台:</span>
   <span class="tt-split" role="group" aria-label="行からのたたき台"><button type="button" class="btn small ghost" id="cutDraftRows" title="文字起こしの行(カット済でない・文字のある行)の時間を残します。端は声の止まる所まで広げます(zip と、まとめて実行で「行から」を選んだときと同じ規則)">行から</button>
   <details class="pop" id="cutRowEdge"><summary class="btn small ghost icon" aria-label="「行から」の設定" title="「行から」の設定(行の端を声の止まる所まで広げる)"><span class="ui-caret" aria-hidden="true"></span></summary><div class="vpop">
     <label class="lag"><input type="checkbox" id="cutEdgeOn" checked>行の端を声の止まる所まで広げる</label>
     <p class="hint">語頭・語尾が切れないように、残す区間の端を無音の所まで広げます(字幕の時刻は変えません)。無音が見つからないときは 前 0.1 秒・<span id="cutEdgePad">後 0.2 秒</span>(後ろの余白は決まった値)。カット済の行は越えません</p>
     <div class="fld"><label for="cutEdgeAfter">終わりを広げる上限(秒)</label><input id="cutEdgeAfter" type="number" value="0.5" min="0" max="2" step="0.05"></div>
     <div class="fld"><label for="cutEdgeBefore">始まりを広げる上限(秒)</label><input id="cutEdgeBefore" type="number" value="0.3" min="0" max="2" step="0.05"></div>
     <p class="hint">この設定は、まとめて実行で「行から」を選んだときにも使います(まとめて実行のカットの決め方はホームの設定)</p>
     <div class="row" style="margin-top:8px"><button type="button" class="btn small primary" id="cutEdgeGo">この設定で「行から」のたたき台にする</button></div></div></details></span>
   <button type="button" class="btn small ghost" id="cutNone" title="カットせずに動画全体を残します(カット済の行の字幕も全部出ます)。「元に戻す」(Ctrl+Z)で戻せます">カットしない</button>
   <details class="pop" id="cutDraftSilence"><summary class="btn small ghost" title="しゃべっていない所(無音)を自動で削ります(cut2resolve で計算)">無音 <span class="ui-caret" aria-hidden="true"></span></summary><div class="vpop">
     <div class="fld"><label for="cutNoise">無音とみなす音量(dB)</label><input id="cutNoise" type="number" value="-35" min="-90" max="0" step="1"><span class="hint">大きくする(-30 など)と、小さな音も無音として削ります</span></div>
     <div class="fld"><label for="cutSilMin">無音の長さ(秒)</label><input id="cutSilMin" type="number" value="0.6" min="0.05" max="60" step="0.05"></div>
     <div class="fld"><label for="cutSilPad">話の前後に残す秒数</label><input id="cutSilPad" type="number" value="0.15" min="0" max="10" step="0.05"></div>
     <div class="row" style="margin-top:8px"><button type="button" class="btn small primary" id="cutDraftSilenceGo">無音を削ったたたき台にする</button></div></div></details>
   <details class="pop" id="cutDraftList"><summary class="btn small ghost" title="残す区間を時刻で書いて貼り付けます(cut2resolve で計算)">時刻リスト <span class="ui-caret" aria-hidden="true"></span></summary><div class="vpop">
     <div class="fld"><label for="cutListText">残す区間(1行に1つ。例: 0:05 0:20)</label><textarea id="cutListText" rows="5" placeholder="0:05 0:20&#10;0:31.5 0:48"></textarea></div>
     <div class="row" style="margin-top:8px"><button type="button" class="btn small primary" id="cutDraftListGo">この区間を残すたたき台にする</button></div></div></details>
   <button type="button" class="btn small ghost" id="cutDraftPlan" hidden>スタジオ</button>
   <span class="tt-grow"></span>
   <label class="lag tt-cut-snap" title="区間の端を、字幕の行の端・無音の境目・再生位置・隣の区間の端に吸い付かせます(Alt を押している間は吸い付かない)"><input type="checkbox" id="cutSnap" checked>吸着</label>
   <button type="button" class="btn small icon" id="cutZoomOut" aria-label="縮める(−)" title="縮める(−・ホイール)">−</button>
   <button type="button" class="btn small icon" id="cutZoomIn" aria-label="広げる(+)" title="広げる(+・ホイール)">＋</button>
   <button type="button" class="btn small" id="cutZoomFit" title="全体を1画面に">全体</button>
 </div>
 <div class="tt-tl-mini" id="tlMini" data-ui-audit-allow="A-25" title="全体(ドラッグで見る範囲を移動・枠の端をドラッグで拡大縮小)"><canvas id="tlMiniWave"></canvas><div class="tt-tl-mini-view" id="tlMiniView"><span class="tt-tl-mini-h l" data-h="l"></span><span class="tt-tl-mini-h r" data-h="r"></span></div></div>
 <div class="card tt-tl" id="cutTL">
   <div class="tt-tl-heads" aria-hidden="true"><span class="r"></span><span>区間</span><span>字幕</span></div>
   <div class="tt-tl-scroll" id="tlScroll" tabindex="0" aria-label="タイムライン(区間を押して選ぶ・端をドラッグ・目盛りを押すとその位置へ。ホイールで拡大縮小・Shift+ホイールで移動)">
     <div class="tt-tl-content" id="tlContent">
       <div class="tt-tl-ruler" id="tlRuler"></div>
       <div class="tt-tl-track tt-tl-v" id="tlVideo"></div>
       <div class="tt-tl-track tt-tl-a" id="tlAudio"><canvas id="tlWave"></canvas></div>
       <div class="tt-tl-track tt-tl-s" id="tlSubs"></div>
       <div class="tt-tl-io" id="tlIO" hidden></div>
       <div class="tt-tl-snap" id="tlSnap" hidden></div>
       <div class="tt-tl-head" id="tlHead"></div>
       <div class="tt-tl-tip" id="tlTip" hidden></div>
     </div>
   </div>
 </div>
 <section class="tt-pack" id="packArea" aria-labelledby="packAreaTitle">
 <h3 class="tt-pack-h" id="packAreaTitle">パック(DaVinci Resolve へ渡す)</h3>
 <div class="notice tt-pk-off" id="pkOff" hidden role="status"></div>
 <p class="card tt-pk-strip" id="pkStatus" role="status"><b>パック</b><span class="hint">前に作った</span><b id="pkStatusMade">–</b><span class="hint">友人へ渡した</span><b id="pkStatusSent">–</b></p>
 <div class="row tt-pk-go"><button type="button" class="btn primary lg" id="pkBuild">パックを作る</button><span class="hint" id="pkBuildHint"></span></div>
 <div class="tt-cp-job" id="pkJob" hidden role="status" aria-live="polite"></div>
 <div class="notice err" id="pkErr" hidden role="alert"></div>
 <div class="tt-pk-grid">
   <div class="tt-pk-col">
     <div class="card tt-pk-card">
       <h3 class="tt-pk-h">これから作るパック</h3>
       <div class="tt-pk-stats">
         <div><b class="mono" id="pkLen">–</b><span>カット後の長さ(元 <span class="mono" id="pkSrcLen"></span>)</span></div>
         <div><b class="mono" id="pkCount">–</b><span>残す区間</span></div>
         <div><b class="mono" id="pkCaps">–</b><span id="pkCapsL">Text+ 字幕</span></div>
       </div>
       <div class="tt-pk-map" id="pkMap" aria-hidden="true"></div>
       <p class="hint tt-pk-p">区間は上の<b>カット</b>のとおり。字幕は文字起こしの行を区間に合わせて詰めます(削った行の字幕は入りません)。</p>
       <p class="hint tt-pk-p" id="pkNoSub" hidden></p>
       <p class="notice info tt-pk-pvstate" id="pkPvState" hidden role="status" aria-live="polite"><span></span><button type="button" class="btn small" id="pkPvRetry" hidden>もう一度</button></p>
       <ul class="notice tt-pk-warn" id="pkWarn" hidden></ul>
     </div>
     <!-- パックの設定(大きさ + 「パックの決まり」)は 1 行に畳む。要約 #pkSummaryText は pack-tab.js が今の値で書く(10-24 画面の見直し 3) -->
     <details class="card ui-disclosure tt-pk-fold" id="pkSetFold"><summary><b>パックの設定</b><span class="hint tt-pk-sumrow"><span class="ui-streamer-sw" id="pkSummarySw" hidden aria-hidden="true"></span><span id="pkSummaryText"></span></span></summary>
       <section id="edSetPack" aria-labelledby="edSetPackT">
         <h3 class="tt-pk-h" id="edSetPackT">パックの決まり</h3>
         <p class="hint" style="margin:0 0 6px">Resolve へ渡すパックは、いつもこの形で作ります(ここの「パックを作る」とホームのまとめて実行・友人の依頼で同じ。画面の大きさだけ設定で選ぶ)。</p>
         <ul class="hint tt-pk-fixed">
           <li>素材とプロジェクトは 30fps</li>
           <li>画面の大きさ: <span id="pkSizeNow">縦 1080×1920</span>(縦か横かは<a href="settings#uiSetGroup-pack-out">設定の「パック」</a>で選ぶ。縦に切り取る作業(クロップ)は Resolve で)</li>
           <li>音量: カットで残す部分だけを測って -14 LUFS にそろえる(YouTube と同じくらい。映像と元の動画はそのまま)</li>
           <li>話者の名前がメンバーと合えば、その話者の字幕をその色に</li>
           <li>行の後の余白 0.2 秒(「行から」のたたき台で、行の終わりに無音が見つからないとき)</li>
         </ul>
         <div class="hint tt-pk-spklist" id="pkSpkList"></div>
         <p class="hint tt-pk-place" id="pkPlace"></p>
         <button type="button" class="btn" id="pkSettingsBtn" hidden>パックの決まり</button>
       </section>
     </details>
     <!-- 字幕の見本も 1 行に畳む(10-24 画面の見直し 4)。要約は字幕の見た目の名前 #pkLookName -->
     <details class="card ui-disclosure tt-pk-fold tt-pk-lookcard" id="pkLookFold"><summary><b>字幕の見本</b><span class="hint" id="pkLookName">けいふぉんと・黒い文字・白いふち・黒いふち</span></summary>
       <p class="hint tt-pk-p" id="pkWhoNote" style="margin:0 0 8px">配信者(字幕の色)は、この文書に覚えている名前(友人の依頼の指定・まとめて実行で選んだ名前)をそのまま使います。</p>
       <div hidden><input id="pkWho" type="text" aria-label="配信者(字幕の色)" data-ui-streamer tabindex="-1"></div>
       <div class="tt-pk-look"><div class="tt-pk-phone" id="pkPhone"><span class="tt-pk-phone-cap tt-cap-look" id="pkPhoneCap"></span></div>
         <div class="tt-pk-looktxt"><div id="pkSamples"></div><p class="hint" id="pkLookNote"></p></div></div>
     </details>
     <details class="card ui-disclosure tt-pk-fold tt-pk-more" id="pkMore"><summary><b>詳しく</b><span class="hint">出力先のフォルダ(空欄なら動画の隣)</span></summary>
       <div class="fld"><label for="pkDir">出力先のフォルダ</label><input id="pkDir" type="text" autocomplete="off" spellcheck="false" title="空欄なら、動画と同じフォルダの「動画名_pack」に作ります">
         <span class="hint">空欄なら動画の隣の「&lt;動画名&gt;_pack」。<b>出力先は覚えません</b>(文書を開くたびに空欄に戻ります。別の案件へ間違って出さないため)。前に作ったパックがあれば、作る前に上書きしてよいか聞きます。</span></div>
     </details>
   </div>
   <div class="tt-pk-col">
     <div class="card tt-pk-card" id="pkLast" hidden>
       <h3 class="tt-pk-h"><span class="pill ok" id="pkLastPill">前回のパック</span> <span class="hint" id="pkLastWhen"></span></h3>
       <p class="mono hint tt-pk-dir" id="pkLastDir"></p>
       <div class="tt-pk-diff" id="pkLastDiff" hidden></div>
       <ul class="hint tt-pk-notes" id="pkLastNotes" hidden aria-label="作ったときの案内"></ul>
       <div id="pkLastFiles"></div>
       <div class="row tt-pk-lastbtns"><button type="button" class="btn small" id="pkOpen">フォルダを開く</button><button type="button" class="btn small" id="pkReadme">Resolve での手順を見る</button><button type="button" class="btn small" id="pkCopy">パスをコピー</button><button type="button" class="btn small" id="pkDeliver" hidden title="パックを zip にして Dropbox の「出力」に置きます。友人のアプリの「受け取る」に出ます">友人へ届ける</button></div>
       <p class="hint" id="pkDeliverMsg" role="status" hidden></p>
       <pre class="tt-cp-readme" id="pkReadmeText" hidden></pre>
     </div>
   </div>
 </div>
 </section>
 <div class="tt-cut-status" id="cutStatus" aria-live="polite"></div>
 <p class="hint tt-cut-keys"><span id="cutKeysText">下の帯にこの欄のキー。校正のキーは校正のタブで。</span><span class="savest" id="cutSaveSt"></span></p>
 <dialog id="cutSplitDlg" aria-labelledby="cutSplitT">
   <form method="dialog">
     <div class="ui-dlg-head"><h2 id="cutSplitT">行を分ける</h2></div>
     <p class="hint" style="margin:0 0 8px">再生位置 <span class="mono" id="cutSplitAt"></span> で2つに分けます。文字の分け目にカーソルを置いて「分ける」(Enter)。文字はここでは直せません</p>
     <input id="cutSplitText" type="text" readonly style="width:100%" aria-label="行の文字(分け目にカーソルを置く)">
     <div class="row" style="justify-content:flex-end;margin-top:10px"><button type="button" class="btn" id="cutSplitCancel">キャンセル</button><button type="submit" class="btn primary" value="ok">分ける</button></div>
   </form>
 </dialog>
</section>`;

  /* ---- host に渡す小さい道具(文書の部品は editor/doc-kit.js の D)---- */
  var enc = encodeURIComponent;
  function toast(msg, ms, kind) { return UIKit.toast(msg, ms && typeof ms === 'object' ? ms : { ms: ms, kind: kind || '' }); }
  var LOCK_KINDS = { diarize: 1, rerun: 1, transcribe: 1 };
  function metaToken() { var m = document.head.querySelector('meta[name="ytt-token"]'); return m ? m.content : ''; }
  var NO_C2R = 'cut2resolve に接続できません(start.bat の黒い画面が閉じていないか確認してください)';

  window.CasesPanels.define('cut', function () {
    var el = null, root = null, ctx = null, alive = false, seq = 0, running = false;
    var CUT = null, PACK = null, h = null;
    var S = null, barItems = [], barKey = '', leaveHooks = [], opSeq = 0;
    var c2rOk = false, docSaveP = null, saveT = 0, cutSyncT = 0, savedSet = {}, wasLocked = false;
    var SPKC = new Map();

    function newState() {
      return { doc: null, docId: null, settings: {}, conflict: false, baseUpdatedAt: null, sibLoaded: false, dirty: false, saving: false, undo: [], forceNext: false };
    }
    var q = function (sel) { return root ? root.querySelector(sel) : null; };

    /* ---- API ---- */
    function hApi(path, opt) {
      var o = opt || {}, tool = /^\/api\/ytt\//.test(path) ? 'home' : 'transcribe';
      return ctx.api(tool, path, { method: o.method, body: o.body, keepalive: o.keepalive });
    }
    function apiUrl(path) { return new URL('transcribe' + path, location.href).href; }
    function c2rBase() { return c2rOk ? 'cut2resolve/' : ''; }
    function c2rApi(path, opt) {
      if (!c2rOk) { var e = new Error('cut2resolve を使えません(ホーム(start.bat)から開いてください)'); e.code = 'unavailable'; return Promise.reject(e); }
      return ctx.api('cut2resolve', path, { body: (opt || {}).body, offline: NO_C2R, fail: function (st) { return 'cut2resolve のエラー(' + st + ')'; } });
    }
    function c2rWait(job, onTick) {
      var fails = 0;
      function step(j) {
        if (j.state !== 'running') {
          if (j.state === 'done') return Promise.resolve(j.result);
          var er = j.error || {}, e = new Error(j.state === 'cancelled' ? '中止しました' : (er.message || '失敗しました'));
          e.code = j.state === 'cancelled' ? 'cancelled' : (er.code || 'failed'); e.data = er;
          return Promise.reject(e);
        }
        return new Promise(function (res) { setTimeout(res, 300); }).then(function () {
          return c2rApi('api/job?id=' + enc(job.id)).then(function (nj) { fails = 0; if (onTick) onTick(nj); return step(nj); },
            function (e) { if (e.code === 'network' && ++fails < 20) return step(j); throw e; });
        });
      }
      return step(job);
    }
    function probeC2r() {
      return ctx.api('cut2resolve', 'api/ping', { timeout: 8000 }).then(function () { c2rOk = true; }, function () { c2rOk = false; });
    }

    /* ---- 設定(送ったキーだけ直す)---- */
    function snapSettings(st) { var o = {}; Object.keys(st).forEach(function (k) { o[k] = JSON.stringify(st[k]); }); return o; }
    function patchSettings(values, label, opt) {
      var o = opt || {}, st = S.settings, old = {};
      Object.keys(values).forEach(function (k) { old[k] = k in st ? { v: st[k] } : null; st[k] = values[k]; });
      return hApi('/api/settings/patch', { body: { values: values } }).then(function () { savedSet = snapSettings(st); return true; }, function (e) {
        if (!o.keep) Object.keys(old).forEach(function (k) { if (old[k]) st[k] = old[k].v; else delete st[k]; });
        toast(label + ': ' + e.message, { kind: 'err', ms: 'ms' in o ? o.ms : 6000, action: o.retry ? { label: 'もう一度', fn: o.retry } : undefined });
        return false;
      });
    }
    function putSettings() {
      var cur = snapSettings(S.settings), patch = {};
      Object.keys(cur).forEach(function (k) { if (cur[k] !== savedSet[k]) patch[k] = S.settings[k]; });
      Object.keys(savedSet).forEach(function (k) { if (!(k in cur)) patch[k] = null; });
      if (!Object.keys(patch).length) return Promise.resolve();
      return hApi('/api/settings', { method: 'PUT', body: { patch: patch } }).then(function () { savedSet = cur; });
    }

    /* ---- 文書の保存(0.7 秒まとめて PUT。baseUpdatedAt で競合を見る)---- */
    function markDirty() {
      S.dirty = true;
      clearTimeout(saveT); saveT = setTimeout(saveDoc, 700);
      clearTimeout(cutSyncT); cutSyncT = setTimeout(function () { if (CUT) CUT.docChanged(); }, 300);
    }
    function saveDoc() {
      clearTimeout(saveT);
      if (docSaveP) return docSaveP;
      if (S.conflict) return Promise.resolve(false);
      if (!S.doc || !S.dirty) return Promise.resolve(true);
      S.saving = true;
      docSaveP = (async function () {
        while (S.doc && S.dirty) {
          S.dirty = false;
          var id = S.docId, d = S.doc;
          var body = { title: d.title, evalSet: d.evalSet === true, speakers: d.speakers, segments: d.segments, baseUpdatedAt: S.baseUpdatedAt };
          try {
            var r = await hApi('/api/transcript?id=' + enc(id), { method: 'PUT', body: body });
            if (S.docId !== id) return false;
            S.baseUpdatedAt = r.updatedAt;
            if (PACK) PACK.changed();
          } catch (e) {
            if (S.docId !== id) return false;
            S.dirty = true;
            if (e.code === 'conflict') {
              S.conflict = true; toast('別の場所で先に文字起こしが更新されています。カットの上の案内から読み直してください', 6000, 'err');
              if (CUT) CUT.refresh();
            } else { toast('文字起こしを保存できませんでした: ' + e.message, 3800, 'err'); clearTimeout(saveT); saveT = setTimeout(saveDoc, 5000); }
            return false;
          }
        }
        return !S.conflict;
      })().finally(function () { S.saving = false; docSaveP = null; });
      return docSaveP;
    }
    function reloadDoc() {
      var id = S.docId;
      return hApi('/api/transcript?id=' + enc(id)).then(function (d) {
        if (!alive || S.docId !== id) return;
        S.doc = d; S.baseUpdatedAt = d.updatedAt || null; S.conflict = false; S.dirty = false; S.undo = [];
        if (CUT) { CUT.docChanged(); CUT.refresh(); }
        if (PACK) PACK.changed();
        toast('保存されている文字起こしを読み直しました', 3000, 'ok');
      }, function (e) { toast('文字起こしを読み直せませんでした: ' + e.message, 5000, 'err'); });
    }

    /* ---- 文書の元に戻す(文書の行 + カットの履歴を、新しい番号の方から)---- */
    var nextOp = function () { return ++opSeq; };
    function pushUndo(sq) {
      S.undo.push({ seq: sq || nextOp(), snap: JSON.stringify({ speakers: S.doc.speakers, segments: S.doc.segments }) });
      if (S.undo.length > 30) S.undo.shift();
    }
    function restoreUndo() {
      var d = JSON.parse(S.undo.pop().snap);
      S.doc.speakers = d.speakers; S.doc.segments = d.segments;
      markDirty(); if (CUT) CUT.docChanged();
    }
    function undoDocIf(sq) {
      if (!S.doc || !sq || !S.undo.length || S.undo[S.undo.length - 1].seq !== sq) return false;
      restoreUndo(); return true;
    }
    function doUndo() {
      if (!S.doc || lockJob()) return;
      var tx = S.undo.length ? S.undo[S.undo.length - 1].seq : 0, ct = CUT && CUT.undoTop ? CUT.undoTop() : 0;
      if (ct && ct >= tx) { CUT.undo(); return; }
      if (S.undo.length) restoreUndo();
    }
    function splitRowAt(i, pos, cut) {
      var segs = S.doc.segments, s = segs[i];
      if (!s || !(pos > 0 && pos < s.text.length)) return false;
      cut = Math.round(cut * 100) / 100;
      pushUndo();
      var left = Object.assign({}, s, { text: s.text.slice(0, pos).trimEnd(), end: cut });
      var right = Object.assign({}, s, { id: D.uid(), text: s.text.slice(pos).trimStart(), start: cut, flag: '' });
      segs.splice(i, 1, left, right);
      markDirty();
      return true;
    }
    function lockJob() {
      if (!S || !S.doc || !ctx) return null;
      var jobs = (ctx.status && ctx.status.jobs) || [];
      for (var i = 0; i < jobs.length; i++) if ((jobs[i].state === 'queued' || jobs[i].state === 'running') && LOCK_KINDS[jobs[i].kind]) return jobs[i];
      return null;
    }
    function rowSig() {
      return S.doc ? S.doc.segments.map(function (g) { return g.start + ',' + g.end + ',' + (g.cutState === 'cut' ? 1 : 0) + ',' + (D.hasText(g) ? 1 : 0) + (g.noSub ? ',n' : ''); }).join(';') : '';
    }

    /* ---- 話者の色(文書の話者の字幕の色 sub → 名前がメンバーと合えばメンバーカラー。照らし合わせは入口の api/ytt/streamer-colors)---- */
    var speakerColorsOn = function () { return !S.settings || S.settings.speakerColors !== false; };
    function lookupSpeakerNames(names) {
      if (!metaToken()) return;
      var want = [];
      names.forEach(function (n) { n = String(n || '').trim(); if (n && !SPKC.has(n) && want.indexOf(n) < 0) want.push(n); });
      if (!want.length) return;
      want.forEach(function (n) { SPKC.set(n, undefined); });
      hApi('/api/ytt/streamer-colors', { body: { names: want } }).then(function (j) {
        want.forEach(function (n) { var m = j && j.matches ? j.matches[n] : null; SPKC.set(n, m && /^#[0-9a-fA-F]{6}$/.test(String(m.hex || '')) ? { name: String(m.name), hex: m.hex } : null); });
        onSpeakerColors();
      }, function () { want.forEach(function (n) { SPKC.delete(n); }); });
    }
    function speakerColorByName(name) {
      name = String(name || '').trim();
      var own = null;
      if (name && S.doc) S.doc.speakers.forEach(function (s) { if (!own && !D.isOtherSp(s) && String(s.name || '').trim() === name && D.subColorOf(s)) own = s; });
      if (own) return { hex: D.subColorOf(own), member: '', pending: false, sub: true };
      if (!name || !metaToken() || !speakerColorsOn()) return { hex: '', member: '', pending: false };
      if (!SPKC.has(name)) lookupSpeakerNames([name]);
      var m = SPKC.get(name);
      return m === undefined ? { hex: '', member: '', pending: true } : m ? { hex: m.hex, member: m.name, pending: false } : { hex: '', member: '', pending: false };
    }
    function speakerColor(spId) {
      var sp = S.doc && S.doc.speakers.filter(function (s) { return s.id === spId; })[0];
      if (!sp) return { hex: '', auto: '', member: '', reason: '' };
      var name = String(sp.name || '').trim(), sub = D.subColorOf(sp);
      if (sub) return { hex: sub, auto: '', member: '', sub: true, reason: '字幕の色を指定しています(' + sub + '。メンバーの色より優先)' };
      if (!metaToken()) return { hex: '', auto: '', member: '', reason: 'ホームから開くと、名前をメンバーと照らし合わせて色を付けます' };
      if (!speakerColorsOn()) return { hex: '', auto: '', member: '', reason: '「話者の名前がメンバーと合えば…」を切っているので、メンバーの色は使いません' };
      var c = speakerColorByName(name);
      if (c.pending) return { hex: '', auto: '', member: '', reason: '' };
      return c.hex ? { hex: c.hex, auto: '', member: c.member, reason: '名簿の「' + c.member + '」と一致(この色で字幕を出します)' } : { hex: '', auto: '', member: '', reason: 'メンバーと合わないので、字幕は配信者の色で出します' };
    }
    function onSpeakerColors() { if (CUT && CUT.refreshCaption) CUT.refreshCaption(); if (PACK) PACK.changed(); }

    /* ---- 作る前の書き出し・保存 ---- */
    async function cpExport(id) {
      var ok = await saveDoc();
      var fail = function (msg, code) { return Object.assign(new Error(msg), { code: code }); };
      if (S.docId !== id) throw fail('別の文字起こしに切り替えました', 'switched');
      if (!ok || S.dirty || S.saving) throw S.conflict ? fail('保存が競合しています。カットの上の案内から読み直してください', 'conflict') : fail('保存が追いついていません', 'saving');
      var r;
      try { r = await hApi('/api/export-file', { body: { id: id, format: 'transcript-v1', baseUpdatedAt: S.baseUpdatedAt } }); }
      catch (e) { if (e.status === 409) e.code = 'saving'; throw e; }
      return r.path;
    }
    function onPacked() {
      if (ctx && ctx.reload) ctx.reload();   // 左の一覧の札・パックの様子の帯(前に作った時刻)を読み直す
    }
    /* パックの様子の帯 #pkStatus(10-24 画面の見直し 1): 前に作った = ④ の clip.pack.updatedAt(txindex.pack_info = パックの記録の builtAt)・
       友人へ渡した = ④ の clip.review(届けた記録 deliveredAt。1 = 時刻の無い古い行・失敗の文 failure・送らなかった理由 notSent)。
       作り終えると onPacked の ctx.reload() → update でここも描き直す */
    function paintStatus() {
      var made = q('#pkStatusMade'), sent = q('#pkStatusSent');
      if (!made || !sent || !ctx) return;
      var cl = (ctx.item && ctx.item.clip) || {}, pk = cl.pack, rv = cl.review || {}, fmt = UIKit.fmt;
      made.textContent = !pk ? 'まだ作っていません' : pk.updatedAt ? fmt.date(pk.updatedAt) : 'あり(時刻は分かりません)';
      made.title = pk && pk.updatedAt ? fmt.ago(pk.updatedAt) : '';
      var bad = !rv.deliveredAt && !!(rv.failure || rv.notSent);
      sent.textContent = rv.deliveredAt ? '1 本' + (rv.deliveredAt > 1 ? '(' + fmt.date(rv.deliveredAt) + ')' : '') : bad ? '0 本(送れなかった)' : '0 本';
      sent.className = bad ? 'tt-pk-bad' : '';
      sent.title = rv.delivered ? String(rv.delivered) : '';
    }

    /* ---- 殻の下の帯・タブの横の説明 ---- */
    function setKeybar(items) {
      var key = JSON.stringify(items);
      if (key === barKey) return;
      barKey = key; barItems = items;
      if (ctx && ctx.refreshKeys) ctx.refreshKeys();
    }
    function toPack() {
      var a = q('#packArea');
      if (!a) return;
      a.scrollIntoView({ block: 'start' });
      var b = q('#pkBuild');
      if (b && !b.disabled) b.focus();
    }

    function makeHost() {
      return {
        root: root, S: S, $: q, esc: UIKit.esc, TOKEN: metaToken(),
        words: { tx: '校正のタブ', txName: '校正', cut: 'カットの欄', cutName: 'カット', conflict: 'カットの上の案内' },   // cut.js・pack-tab.js の案内文の「ほかの欄」の呼び名
        fmtT: D.fmtT, fmtCs: D.fmtCs, toast: toast, api: hApi, apiUrl: apiUrl,
        patchSettings: patchSettings, putSettings: putSettings, setKeybar: setKeybar,
        player: function () { return { currentTime: 0, readyState: 0 }; },   // 校正の欄の動画は無い(カットの動画は #cutPlayer)
        isTextEntry: function (t) { return UIKit.keys.isTyping(t); },
        onLeave: function (fn) { leaveHooks.push(fn); },
        saveDoc: saveDoc, speakerColor: speakerColor, speakerColorByName: speakerColorByName, onSpeakerColors: onSpeakerColors,
        pushUndo: pushUndo, undoDocIf: undoDocIf, doUndo: doUndo, nextOp: nextOp, splitRowAt: splitRowAt,
        rowChanged: function () { if (S.doc) markDirty(); },
        lockJob: lockJob, rowSig: rowSig,
        c2rApi: c2rApi, c2rWait: c2rWait, c2rBase: c2rBase,
        tab: function () { return alive ? 'cut' : ''; },
        modalOpen: function () { return !!document.body.querySelector('dialog[open], .ui-drawer:not([hidden])'); },
        imeKey: function (e) { return e.isComposing || e.keyCode === 229; },
        onCutMarks: function () {},
        onCutSaved: function (r) {
          if (!S.doc) return;
          var set = new Set(r.cutRows || []);
          S.doc.segments.forEach(function (g) { var want = set.has(g.id); if (want !== (g.cutState === 'cut')) { if (want) g.cutState = 'cut'; else delete g.cutState; } });
          if (PACK) PACK.changed();
        },
        onCutState: function () { if (PACK) PACK.changed(); },
        onCutSave: function (text) { if (ctx && ctx.setHint) ctx.setHint(text); },
        keepCutHTML: D.keepCutHTML,
        capStack: function (segs, t, opt) { return D.capStack(segs, t, Object.assign({ speakers: S.doc ? S.doc.speakers : [] }, opt)); },   // 重なる行は上下に積む(校正の映像の上と同じ規則)
        paintCaps: function (box, idxs, segs) { D.paintCaps(box, idxs, segs, function (g) { return speakerColor(g.speaker).hex; }); },
        toTx: function () { location.hash = '#proof'; }, toPack: toPack, docConflictGo: reloadDoc,
        ago: function (ms) { return UIKit.fmt.ago(ms); }, cpExport: cpExport,
        copyPath: function (text) { return UIKit.copy(text, { ok: 'パスをコピーしました', fail: 'コピーできませんでした(パスを選んでコピーしてください)' }); },
        onPacked: onPacked, isOtherSp: D.isOtherSp, subColorOf: D.subColorOf
      };
    }

    /* ---- 開く・閉じる ---- */
    function paintNoDoc() {
      var cl = (ctx.item && ctx.item.clip) || {};
      el.innerHTML = window.CasesPanels.stub(ctx, {
        id: 'cut', title: 'カット・パック: ' + ((ctx.item && ctx.item.label) || ''),
        text: 'この切り抜きはまだ文字起こししていません。文字起こしすると、ここでカットとパックを作れます。',
        facts: [['パック', cl.pack ? (cl.pack.textplus ? 'あり(字幕つき)' : 'あり') : 'まだ']]
      });
    }
    function paintError(e) {
      el.innerHTML = '<div class="empty"><b>カットの欄を開けませんでした</b><span>' + UIKit.esc(e && e.message ? e.message : String(e)) + '</span></div>';
    }
    function start() {
      var my = ++seq, docId = ctx.docId;
      el.innerHTML = '<p class="hint" style="padding:12px">カットの欄を読み込んでいます…</p>';
      running = true;
      loadScripts().then(function () {
        return window.CasesPanels.settled();   // 校正のパネルが閉じるときに送った保存を待ってから文書を読む(RS8 C4。古い文書を読んで 409 にならない)
      }).then(function () {
        if (!alive || my !== seq) return null;
        return Promise.all([hApi('/api/transcript?id=' + enc(docId)), hApi('/api/settings'), probeC2r()]);
      }).then(function (r) {
        if (!r || !alive || my !== seq) return;
        S = newState();
        S.doc = r[0]; S.docId = docId; S.baseUpdatedAt = r[0].updatedAt || null; S.settings = r[1] && typeof r[1] === 'object' ? r[1] : {}; S.sibLoaded = true;
        savedSet = snapSettings(S.settings); leaveHooks = []; barKey = ''; barItems = []; SPKC = new Map(); wasLocked = !!lockJob();
        el.innerHTML = '<div class="cs-cut" id="csCutRoot">' + TEMPLATE + '</div>';
        root = el.firstChild;
        if (UIKit.icon && UIKit.icon.fill) UIKit.icon.fill(root);
        h = makeHost();
        CUT = window.EditCut.create(h);
        h.CUT = CUT;
        PACK = window.EditPack.create(h);
        CUT.load(docId);
        PACK.load(docId);
        CUT.onShown();
        PACK.shown();
        paintStatus();
        if (ctx.refreshKeys) ctx.refreshKeys();
      }).catch(function (e) {
        if (!alive || my !== seq) return;
        running = false;
        paintError(e);
      });
    }
    /* 閉じる: 未保存のカットと文書を先に送り(送る要求は同期に始まる)、見張り・タイマーを止める。DOM は殻が空にする */
    function teardown() {
      seq++;
      var cut = CUT, pack = PACK;
      if (cut) { try { cut.onHidden(); } catch (e) { UIKit.report('カットを閉じられませんでした: ' + (e && e.message), { stack: e && e.stack }); } }
      if (S && S.doc) window.CasesPanels.track(saveDoc());   // 次に開くパネル(校正)はこの保存を待ってから文書を読む
      clearTimeout(cutSyncT);
      if (pack) pack.dispose();
      if (cut) cut.dispose();
      CUT = PACK = h = null; root = null; running = false; leaveHooks = []; barItems = []; barKey = '';
    }

    return {
      id: 'cut',
      mount: function (el0, ctx0) {
        el = el0; ctx = ctx0; alive = true;
        if (!ctx.docId) { paintNoDoc(); return; }
        start();
      },
      update: function (c) {
        var before = ctx && ctx.docId;
        ctx = c;
        if (!alive) return;
        if (c.docId !== before) {   // 左の一覧で別の切り抜きを選んだ
          if (running) teardown();
          if (!c.docId) paintNoDoc(); else start();
          return;
        }
        if (!running || !CUT) { if (!running && c.docId) start(); return; }
        var locked = !!lockJob();
        if (wasLocked && !locked) reloadDoc();   // 話者判別・再認識が終わった = 文書がサーバーで変わった
        else { CUT.refresh(); PACK.changed(); }
        wasLocked = locked;
        paintStatus();
      },
      unmount: function () { alive = false; if (running) teardown(); el = null; },
      keys: function (e) {
        if (!alive || !CUT) return false;
        CUT.onKey(e);
        return e.defaultPrevented;
      },
      keybar: function () { return barItems; },
      leave: function (reason) {
        if (!CUT) return;
        leaveHooks.forEach(function (fn) { try { fn(reason); } catch (e) { /* 保存の失敗は各所で知らせる */ } });
        saveDoc();
        if (reason !== 'blur') CUT.onHidden();   // 隣の窓へ行っただけなら保存だけ。画面を離れたら再生も止める
      },
      back: function (reason) { if (CUT && reason !== 'blur') { CUT.onShown(); PACK.shown(); } }
    };
  });
})();
