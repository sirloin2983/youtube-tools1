/* 案件の画面の「カット・パック」のパネル(#cut。残す区間を決めて、末尾で DaVinci Resolve へ渡すパックを作る)。口の形は cases.js の先頭の説明。RS8 C2c。
   中身は編集の 2 カット(src/editor/cut.js = EditCut)とパック(src/editor/pack-tab.js = EditPack)をそのまま使う(動きを二重に持たない。古い編集の画面は C4 まで残る)。
   ここが持つのは (1) 画面の骨組み(編集の index.html の 2 カットの節を移した。パックの設定の節 #edSetPack も画面の中に置く = 古い画面は ⚙ の引き出し。「予備」の欄は決定 3-34 で置かない)、
   (2) 編集の app-*.js が cut.js / pack-tab.js に渡している「host」(文書 S・保存・元に戻す・字幕の積み方・話者の色・cut2resolve の口)の、このパネル用の小さい版、
   (3) 殻の口(mount / update / unmount / keys / keybar / leave / back)との橋。
   パネルの中の要素は root.querySelector で引く(document.getElementById・document.querySelector は使わない)。API は ctx.api('transcribe' | 'cut2resolve' | 'home', …) の相対パス。
   cut.js・pack-tab.js は /transcribe/ から読む(同じ入口の中。CSP の script-src 'self')。窓へ付ける keydown は付けず(h.ownKeys)、殻の keydown 1 本から keys(e) で渡す */
(function () {
  'use strict';

  var SCRIPTS = ['transcribe/cut.js', 'transcribe/pack-tab.js'];
  var scriptsP = null;
  function loadScripts() {
    if (window.EditCut && window.EditPack) return Promise.resolve();
    if (scriptsP) return scriptsP;
    scriptsP = SCRIPTS.reduce(function (p, src) {
      return p.then(function () {
        return new Promise(function (resolve, reject) {
          var s = document.createElement('script');
          s.src = src;
          s.onload = function () { resolve(); };
          s.onerror = function () { scriptsP = null; reject(new Error(src + ' を読み込めませんでした')); };
          document.head.appendChild(s);
        });
      });
    }, Promise.resolve());
    return scriptsP;
  }

  /* 編集の index.html の 2 カットの節(#tabCut)を移した骨組み。id は cut.js / pack-tab.js が引く名前のまま */
  var TEMPLATE = `
<section id="tabCut">
 <div class="notice tt-cut-off" id="cutOff" hidden role="status"><span id="cutOffMsg"></span><button type="button" class="btn small" id="cutRelink" hidden>動画を選び直す</button><button type="button" class="btn small" id="cutRetry" hidden>もう一度読み込む</button></div>
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
     <p class="hint">語頭・語尾が切れないように、残す区間の端を無音の所まで広げます(字幕の時刻は変えません)。無音が見つからないときは 前 0.1 秒・<span id="cutEdgePad">後 0.2 秒</span>(後ろの余白は下の「パックの設定」で変えられます)。カット済の行は越えません</p>
     <div class="fld"><label for="cutEdgeAfter">終わりを広げる上限(秒)</label><input id="cutEdgeAfter" type="number" value="0.5" min="0" max="2" step="0.05"></div>
     <div class="fld"><label for="cutEdgeBefore">始まりを広げる上限(秒)</label><input id="cutEdgeBefore" type="number" value="0.3" min="0" max="2" step="0.05"></div>
     <p class="hint">この設定は、zip と、まとめて実行で「行から」を選んだときにも使います(まとめて実行のカットの決め方はホームの設定)</p>
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
 <div class="tt-pk-grid">
   <div class="tt-pk-col">
     <div class="card tt-pk-card">
       <h3 class="tt-pk-h">前回の設定</h3>
       <p class="hint tt-pk-sumrow"><span class="ui-streamer-sw" id="pkSummarySw" hidden aria-hidden="true"></span><span id="pkSummaryText"></span></p>
       <p class="hint tt-pk-place" id="pkPlace"></p>
       <div class="row" style="margin-top:8px"><button type="button" class="btn" id="pkSettingsBtn" title="下の「パックの設定」へ移ります(大きさ・音量・字幕の色・行の後の余白)"><span class="ui-icon" data-icon="gear" aria-hidden="true"></span> 設定を変える</button></div>
     </div>
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
       <p class="hint tt-pk-p" id="pkRead" hidden></p>
       <p class="notice info tt-pk-pvstate" id="pkPvState" hidden role="status" aria-live="polite"><span></span><button type="button" class="btn small" id="pkPvRetry" hidden>もう一度</button></p>
       <ul class="notice tt-pk-warn" id="pkWarn" hidden></ul>
       <div class="row tt-pk-go"><button type="button" class="btn primary lg" id="pkBuild">パックを作る</button><span class="hint" id="pkBuildHint"></span></div>
       <div class="tt-cp-job" id="pkJob" hidden role="status" aria-live="polite"></div>
       <div class="notice err" id="pkErr" hidden role="alert"></div>
       <details class="ui-disclosure tt-pk-more" id="pkMore"><summary>詳しく(出力先・タイムコード・zip)</summary>
         <div class="fld"><label for="pkDir">出力先のフォルダ</label><input id="pkDir" type="text" autocomplete="off" spellcheck="false" title="空欄なら、動画と同じフォルダの「動画名_pack」に作ります">
           <span class="hint">空欄なら動画の隣の「&lt;動画名&gt;_pack」。<b>出力先は覚えません</b>(文書を開くたびに空欄に戻ります。別の案件へ間違って出さないため)。前に作ったパックがあれば、作る前に上書きしてよいか聞きます。</span></div>
         <div class="fld"><label for="pkSrcTc">元の動画の開始タイムコード</label><input id="pkSrcTc" type="text" placeholder="空欄なら動画から読む(ふつうは 00:00:00:00)" autocomplete="off" spellcheck="false"><span class="hint" id="pkSrcTcHint" hidden>ドロップフレーム表記(;)はノンドロップとして扱います</span></div>
         <div class="fld"><label for="pkRecTc">タイムラインの開始タイムコード</label><input id="pkRecTc" type="text" placeholder="01:00:00:00" autocomplete="off" spellcheck="false"><span class="hint" id="pkRecTcHint" hidden>ドロップフレーム表記(;)はノンドロップとして扱います</span></div>
         <div class="fld"><label for="pkReel">リール名(EDL)</label><input id="pkReel" type="text" placeholder="AX" maxlength="40" autocomplete="off" spellcheck="false"></div>
         <div class="fld"><span class="l">zip でダウンロード(人に送るとき)</span>
           <div class="row"><button type="button" class="btn small" id="pkZip">zip でダウンロード</button></div>
           <span class="notice tt-pk-zipwarn" id="pkZipWarn" hidden></span>
           <span class="hint"><span id="pkZipNote"></span>1つの zip にしてダウンロードします。ホームから開いていなくても使えます。</span></div>
         <div class="fld"><span class="l">残す区間だけを作業用フォルダに保存</span>
           <div class="row"><button type="button" class="btn small" data-beside="cut-plan-v1" title="残す区間を、動画のフォルダの「作業用」に「動画名.cut-plan.json」で保存します(cut2resolve でカットに使えます)">残す区間(.cut-plan.json)を保存</button></div>
           <div class="tt-handoff" id="cpPlanOut" hidden role="status"></div></div>
       </details>
     </div>
     <section class="card tt-pk-card" id="edSetPack" aria-labelledby="edSetPackT">
       <h3 class="tt-pk-h" id="edSetPackT">パックの設定</h3>
       <p class="hint" style="margin:0 0 6px">Resolve へ渡すパックの決まり。変えるとすぐ保存し、ここの「パックを作る」とホームのまとめて実行の両方に効きます。字幕の 1 段の文字数・字幕の向きは、ホームの設定の編集の節にあります。</p>
       <div class="tt-pk-row" id="pkFpsFixedRow"><span class="tt-pk-l"><abbr class="ui-term" title="1秒あたりのコマ数。素材は 30fps にそろえてあるので、Resolve のプロジェクトも 30fps で作ります">フレームレート</abbr></span>
         <span id="pkFpsFixed">素材とプロジェクトは 30fps</span></div>
       <div class="tt-pk-row"><span class="tt-pk-l">画面の大きさ</span>
         <div class="ui-seg" id="pkSize" role="group" aria-label="画面の大きさ"><button type="button" data-v="1080x1920">縦 1080×1920</button><button type="button" data-v="1920x1080">横 1920×1080</button></div></div>
       <p class="hint tt-pk-p">字幕の位置・大きさをこれに合わせます。縦に切り取る作業(クロップ)は Resolve で行います。</p>
       <div class="tt-pk-row"><label class="tt-pk-l" for="pkLoud">音量のそろえ方(<abbr class="ui-term" title="聞こえ方の音量(ラウドネス)の単位。YouTube は再生時に約 -14 LUFS に下げます">LUFS</abbr>)</label>
         <select id="pkLoud" title="カットで残す部分だけを測って、パックに入れる動画の音量をそろえます(映像はそのまま)"><option value="-14">-14 LUFS(YouTube と同じくらい・おすすめ)</option><option value="-11">-11 LUFS(大きめ)</option><option value="-16">-16 LUFS(少し小さめ)</option><option value="-18">-18 LUFS(小さめ)</option><option value="0">音量を % で決める</option></select>
         <span id="pkVolBox" hidden><input id="pkVol" type="number" min="1" max="200" step="5" style="width:4.5em" aria-label="音量(%。元の音量 = 100)" title="元の音量を 100 としたときの大きさ(%)。小さくするなら 100 より下">%</span></div>
       <p class="hint tt-pk-p">LUFS = 聞こえ方の大きさ(数字が小さいほど小さい音)。カットで残す部分だけを測って、パックに入れる動画の音声をその大きさにそろえます。単位が分かりにくいときは「音量を % で決める」(元の音量 = 100%)。映像はそのまま・元の動画は書き換えません。</p>
       <label class="tt-pk-item"><input type="checkbox" id="pkRender"><span><b>粗編集の動画(mp4)</b><span class="hint">カットだけした確認用の動画。時間と容量がかかります</span></span></label>
       <label class="lag tt-pk-spk" title="話者の名前がメンバーと1人に合えば、その話者の字幕だけ文字をその人の色にします。合わない話者は配信者の色(無ければ黒)のままです">
         <input type="checkbox" class="ui-switch" id="pkSpk" checked>話者の名前がメンバーと合えば、その話者の字幕をその色に</label>
       <div class="hint tt-pk-spklist" id="pkSpkList"></div>
       <div class="fld" style="margin-top:10px"><label for="pkPadAfter">行の後の余白(秒)</label><input id="pkPadAfter" type="number" min="0" max="2" step="0.05" value="0.2" style="width:5em" title="語尾が切れるときに延ばします。「行から」のたたき台で、行の終わりに無音が見つからないときの決まった余白(既定 0.2 秒)">
         <span class="hint">語尾が切れるときに延ばします(既定 0.2 秒)。「行から」のたたき台・zip と、まとめて実行で「行から」を選んだときに効きます。前の余白 0.1 秒は変わりません</span>
         <span class="hint" id="pkPadAfterNote"></span></div>
     </section>
   </div>
   <div class="tt-pk-col">
     <div class="card tt-pk-card tt-pk-lookcard">
       <h3 class="tt-pk-h">字幕の見本</h3>
       <div class="tt-pk-sub">字幕の見た目(<span id="pkLookName">けいふぉんと・黒い文字・白いふち・黒いふち</span>)</div>
       <p class="hint tt-pk-p" id="pkWhoNote" style="margin:0 0 8px">配信者(字幕の色)は、この文書に覚えている名前(友人の依頼の指定・まとめて実行で選んだ名前)をそのまま使います。</p>
       <div hidden><input id="pkWho" type="text" aria-label="配信者(字幕の色)" data-ui-streamer tabindex="-1"></div>
       <div class="tt-pk-look"><div class="tt-pk-phone" id="pkPhone"><span class="tt-pk-phone-cap tt-cap-look" id="pkPhoneCap"></span></div>
         <div class="tt-pk-looktxt"><div id="pkSamples"></div><p class="hint" id="pkLookNote"></p></div></div>
     </div>
     <div class="card tt-pk-card" id="pkLast" hidden>
       <h3 class="tt-pk-h"><span class="pill ok" id="pkLastPill">前回のパック</span> <span class="hint" id="pkLastWhen"></span></h3>
       <p class="mono hint tt-pk-dir" id="pkLastDir"></p>
       <div class="tt-pk-diff" id="pkLastDiff" hidden></div>
       <ul class="hint tt-pk-notes" id="pkLastNotes" hidden aria-label="作ったときの案内"></ul>
       <div id="pkLastFiles"></div>
       <div class="row tt-pk-lastbtns"><button type="button" class="btn small" id="pkOpen">フォルダを開く</button><button type="button" class="btn small" id="pkReadme">Resolve での手順を見る</button><button type="button" class="btn small" id="pkCopy">パスをコピー</button><button type="button" class="btn small" id="pkDeliver" hidden title="パックを zip にして Dropbox の「出力」に置きます。友人の送るアプリの「受け取る」に出ます">友人へ届ける</button></div>
       <p class="hint" id="pkDeliverMsg" role="status" hidden></p>
       <pre class="tt-cp-readme" id="pkReadmeText" hidden></pre>
     </div>
     <div class="card tt-pk-card" id="thCard" hidden>
       <h3 class="tt-pk-h">サムネの案(参照)</h3>
       <p class="hint tt-pk-p">音の大きい瞬間・場面の切り替わり・字幕から時刻を 6 つ選び、型の違う縦長の案を 1 枚に並べます。完成品ではなく、サムネを作るときの参照です。動画のフォルダの「作業用」に保存します(友人へ届けるパックには入りません)。</p>
       <div class="row tt-th-row"><label for="thCrop">切り取り</label>
         <select id="thCrop"><option value="alt">中央と右下を交互</option><option value="center">全部中央(アバターが中央の配信)</option><option value="right">全部右下</option></select>
         <button type="button" class="btn" id="thGo">サムネの案を作る</button></div>
       <p class="hint" id="thMsg" role="status" aria-live="polite"></p>
       <a id="thLink" hidden target="_blank" rel="noopener" title="大きく見る(新しいタブ)"><img id="thImg" class="tt-th-img" alt="サムネの案 6 つ(番号・型・時刻つき)"></a>
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

  /* ---- host に渡す小さい道具(編集の app-core / app-rows と同じ見え方・同じ規則のうち、このパネルが使う分だけ)---- */
  var enc = encodeURIComponent;
  function fmtT(t, ms) {
    t = Math.max(0, Number(t) || 0);
    var h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
    var ss = ms ? s.toFixed(1).padStart(4, '0') : String(Math.floor(s)).padStart(2, '0');
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + ss : m + ':' + ss;
  }
  function fmtCs(t) {
    t = Math.max(0, Number(t) || 0);
    var cs = Math.round(t * 100), h = Math.floor(cs / 360000), m = Math.floor(cs % 360000 / 6000), sec = (cs % 6000) / 100;
    return (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + sec.toFixed(2).padStart(5, '0');
  }
  function toast(msg, ms, kind) { return UIKit.toast(msg, ms && typeof ms === 'object' ? ms : { ms: ms, kind: kind || '' }); }
  var hasText = function (g) { return !!String(g && g.text || '').trim(); };
  var uid = function () { return 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); };
  var CAP_SCAN = 40, CAP_OVERLAP_MIN = 0.3, CAP_MAX_STACK = 3, LOCK_KINDS = { diarize: 1, rerun: 1, transcribe: 1 };
  var subColorOf = function (sp) { var c = sp && sp.sub && typeof sp.sub === 'object' ? String(sp.sub.color || '') : ''; return /^#[0-9a-fA-F]{6}$/.test(c) ? c.toUpperCase() : ''; };
  var isOtherSp = function (sp) { return !!sp && sp.id === 'other'; };
  function segIndexAt(segs, t) {
    var lo = 0, hi = segs.length - 1, ans = -1;
    while (lo <= hi) { var m = (lo + hi) >> 1; if (segs[m].start <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans;
  }
  function download(blob, name) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 30000);
  }
  function metaToken() { var m = document.head.querySelector('meta[name="ytt-token"]'); return m ? m.content : ''; }
  function keepCutHTML(cut, act, dis) {
    var a = act || ['keep', 'cut'], d = dis || '';
    return '<span class="tt-kc" role="group" aria-label="この行を残すかカットするか"><button type="button" data-act="' + a[0] + '" aria-pressed="' + (cut ? 'false' : 'true') + '" title="この行を残す"' + d + '>残す</button>' +
      '<button type="button" data-act="' + a[1] + '" aria-pressed="' + (cut ? 'true' : 'false') + '" title="' + UIKit.esc('この行をカット済にする(Resolve の仮編集から外します。元の素材は残るので、あとで「残す」に戻せます)') + '"' + d + '>カット</button></span>';
  }
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
    function apiBlob(path, body) { return ctx.api('transcribe', path, { body: body, raw: true, timeout: 300000 }); }
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
      var right = Object.assign({}, s, { id: uid(), text: s.text.slice(pos).trimStart(), start: cut, flag: '' });
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
      return S.doc ? S.doc.segments.map(function (g) { return g.start + ',' + g.end + ',' + (g.cutState === 'cut' ? 1 : 0) + ',' + (hasText(g) ? 1 : 0) + (g.noSub ? ',n' : ''); }).join(';') : '';
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
      if (name && S.doc) S.doc.speakers.forEach(function (s) { if (!own && !isOtherSp(s) && String(s.name || '').trim() === name && subColorOf(s)) own = s; });
      if (own) return { hex: subColorOf(own), member: '', pending: false, sub: true };
      if (!name || !metaToken() || !speakerColorsOn()) return { hex: '', member: '', pending: false };
      if (!SPKC.has(name)) lookupSpeakerNames([name]);
      var m = SPKC.get(name);
      return m === undefined ? { hex: '', member: '', pending: true } : m ? { hex: m.hex, member: m.name, pending: false } : { hex: '', member: '', pending: false };
    }
    function speakerColor(spId) {
      var sp = S.doc && S.doc.speakers.filter(function (s) { return s.id === spId; })[0];
      if (!sp) return { hex: '', auto: '', member: '', reason: '' };
      var name = String(sp.name || '').trim(), sub = subColorOf(sp);
      if (sub) return { hex: sub, auto: '', member: '', sub: true, reason: '字幕の色を指定しています(' + sub + '。メンバーの色より優先)' };
      if (!metaToken()) return { hex: '', auto: '', member: '', reason: 'ホームから開くと、名前をメンバーと照らし合わせて色を付けます' };
      if (!speakerColorsOn()) return { hex: '', auto: '', member: '', reason: '「話者の名前がメンバーと合えば…」を切っているので、メンバーの色は使いません' };
      var c = speakerColorByName(name);
      if (c.pending) return { hex: '', auto: '', member: '', reason: '' };
      return c.hex ? { hex: c.hex, auto: '', member: c.member, reason: '名簿の「' + c.member + '」と一致(この色で字幕を出します)' } : { hex: '', auto: '', member: '', reason: 'メンバーと合わないので、字幕は配信者の色で出します' };
    }
    function onSpeakerColors() { if (CUT && CUT.refreshCaption) CUT.refreshCaption(); if (PACK) PACK.changed(); }

    /* ---- プレビューの字幕(重なる行は上下に積む。1 文字起こし と同じ規則)---- */
    function capStack(segs, t, opt) {
      var o = opt || {}, ok = function (i) { return hasText(segs[i]) && !segs[i].noSub && !(o.skip && o.skip(i)); };
      var last = segIndexAt(segs, t), on = [];
      for (var i = last; i >= 0 && i > last - CAP_SCAN; i--) if (t < segs[i].end && ok(i)) on.push(i);
      var top = on.length ? on[0] : -1;
      if (top < 0) return [];
      var spIdx = function (id) { var k = S.doc ? S.doc.speakers.findIndex(function (s) { return s.id === id; }) : -1; return k < 0 ? 99 : k; };
      var overlap = function (a, b) { return Math.min(a.end, b.end) - Math.max(a.start, b.start); };
      var out = on.filter(function (x) { return x !== top && overlap(segs[x], segs[top]) >= CAP_OVERLAP_MIN; }).concat([top])
        .sort(function (a, b) { return segs[a].start - segs[b].start || spIdx(segs[a].speaker) - spIdx(segs[b].speaker) || a - b; });
      return out.length > CAP_MAX_STACK ? out.slice(0, CAP_MAX_STACK - 1).concat(out.slice(-1)) : out;
    }
    function paintCaps(box, idxs, segs) {
      var items = idxs.map(function (i) { return { text: String(segs[i].text || '').trim(), hex: segs[i].speaker ? speakerColor(segs[i].speaker).hex : '' }; }).filter(function (x) { return x.text; });
      var key = JSON.stringify(items);
      if (box.dataset.capKey === key) return;
      box.dataset.capKey = key;
      box.hidden = !items.length;
      if (items.length <= 1) {
        var x = items[0];
        box.textContent = x ? x.text : '';
        if (x && x.hex) box.style.setProperty('--tt-cap-color', x.hex); else box.style.removeProperty('--tt-cap-color');
        return;
      }
      box.style.removeProperty('--tt-cap-color');
      box.innerHTML = items.slice().reverse().map(function (it) {
        return '<span class="tt-cap-line"' + (/^#[0-9a-fA-F]{6}$/.test(it.hex) ? ' style="--tt-cap-color:' + it.hex + '"' : '') + '>' + UIKit.esc(it.text) + '</span>';
      }).join('');
    }

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
    async function savedAll() {
      if ((await saveDoc()) && !(CUT && !(await CUT.flush()))) return true;
      toast('保存が追いついていません。少し待ってから、もう一度押してください', 5000, 'err');
      return false;
    }
    function onPacked() {
      if (ctx && ctx.reload) ctx.reload();   // 左の一覧の札(パック済み)を読み直す
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
        root: root, S: S, $: q, esc: UIKit.esc, ownKeys: true, TOKEN: metaToken(),
        words: { tx: '校正のタブ', txName: '校正', cut: 'カットの欄', cutName: 'カット', conflict: 'カットの上の案内' },   // cut.js・pack-tab.js の案内文の「ほかの欄」の呼び名
        fmtT: fmtT, fmtCs: fmtCs, toast: toast, api: hApi, apiUrl: apiUrl, apiBlob: apiBlob,
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
        keymap: function () { return null; }, menuHasKeys: function () { return false; },
        modalOpen: function () { return !!document.body.querySelector('dialog[open], .ui-drawer:not([hidden])'); },
        imeKey: function (e) { return e.isComposing || e.keyCode === 229; },
        relink: null,   // 動画の選び直しは今の編集の画面(C4 で校正の欄へ)
        onCutMarks: function () {},
        onCutSaved: function (r) {
          if (!S.doc) return;
          var set = new Set(r.cutRows || []);
          S.doc.segments.forEach(function (g) { var want = set.has(g.id); if (want !== (g.cutState === 'cut')) { if (want) g.cutState = 'cut'; else delete g.cutState; } });
          if (PACK) PACK.changed();
        },
        onCutState: function () { if (PACK) PACK.changed(); },
        onCutSave: function (text) { if (ctx && ctx.setHint) ctx.setHint(text); },
        capStack: capStack, paintCaps: paintCaps, keepCutHTML: keepCutHTML,
        toTx: function () { location.hash = '#proof'; }, toPack: toPack, docConflictGo: reloadDoc,
        download: download, safeName: function (t, fb) { return String(t || '').replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_').trim().slice(0, 80) || fb || 'transcript'; },
        ago: function (ms) { return UIKit.fmt.ago(ms); }, cpExport: cpExport,
        copyPath: function (text) { return UIKit.copy(text, { ok: 'パスをコピーしました', fail: 'コピーできませんでした(パスを選んでコピーしてください)' }); },
        savedAll: savedAll, onPacked: onPacked, isOtherSp: isOtherSp, subColorOf: subColorOf
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
