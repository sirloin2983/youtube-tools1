/* app-tpl.js — 「編集」の画面の HTML(window.EditProofTpl)。「校正」の欄(tx)・ダイアログ(dialogs)・題名の行(docbar)・⚙ の編集の節(settings)。
   案件の画面(src/app/ui/cases/edhost.js)が T.tx・T.docbar・T.settings・T.dialogs を自分の欄へ入れて校正のパネルを組み立てる。
   中身の id・class・構造は app-*.js・cut.js・e2e が id で引くので変えない。 */
(function () {
  'use strict';
  var T = window.EditProofTpl = window.EditProofTpl || {};
  T.tx = `   <div class="tt-tabpanel" id="tabTx" role="tabpanel" aria-labelledby="edtab-tx" data-edpanel="tx">
   <div class="tx-grid">
    <section class="tx-list" aria-label="行の一覧">
     <!-- 行の一覧の上の道具(検索・絞り込み・件数。notes:docs/spec/ui.md 4.)と、主なキー操作の手がかり。広い画面では一覧の上に固定する -->
     <div class="tt-listhead" id="listHead">
      <div class="ui-listbar tt-rowbar" role="search">
        <input type="search" id="q" placeholder="行を検索(該当する行だけ表示)" aria-label="行を検索" autocomplete="off">
        <select id="flagKind" aria-label="表示する行の絞り込み" title="表示する行の絞り込み"><option value="">すべての行</option><option value="unproofed">未校正の行だけ</option><option value="proofed">校正済みの行だけ</option><option value="any">要確認すべて</option><option value="text">文字の要確認だけ</option><option value="spk">話者の要確認だけ</option><option value="sug">修正の提案がある行だけ</option><option value="cut">カット済の行だけ</option></select>
        <!-- 「次の未校正」・「…」・件数は1つの箱に入れ、折り返すときは3つ一緒に次の行へ(「…」だけが落ちない) -->
        <span class="tt-rb-end">
        <button type="button" class="btn small" id="btnNextUn" title="次の未校正の行へ移動します(Shift+↓。前へは Shift+↑)">次の未校正 <kbd class="ui-kbd">Shift</kbd><kbd class="ui-kbd">↓</kbd></button>
        <!-- 話者・まとめて直す・書き出し・以前の版は、同じ操作の置き場をほかに残さずここへ1つにまとめる -->
        <details class="ui-pop" id="jumpMenu"><summary class="btn ghost small icon" id="btnSpk" aria-label="話者・文字をまとめて直す・書き出し・以前の版" title="話者・文字をまとめて直す・書き出し・以前の版"><span class="ui-icon" data-icon="more" aria-hidden="true"></span></summary><div class="ui-pop-body" data-align="left">
          <button type="button" data-jump="spDetails">話者(自動判別・名前)</button>
          <button type="button" data-jump="fixDetails">文字をまとめて直す(置換・再認識)</button>
          <button type="button" data-jump="exDetails">書き出し(字幕・テキスト)</button>
          <button type="button" data-jump="hiDetails">以前の版に戻す</button></div></details>
        <span class="pill warn tt-read-count" id="readCount" hidden title="字幕として読みにくい行(1 秒あたりの文字が多い・表示が短い)の数。絞り込みの「読みにくい行だけ」で、その行だけを出せます(知らせるだけ。校正済みにはできます)"></span>
        <span class="ui-count" id="qCount" aria-live="polite"></span>
        </span>
      </div>
      <!-- 主なキー操作の手がかり(閉じたら覚える。全部は「キー操作」)。画面の下の帯(UIKit.keybar)にも同じ場面のキーを出す -->
      <div class="tt-keyhint" id="keyHint" hidden>
        <span class="tt-kh-l">キー:</span>
        <span id="keyHintItems" style="display:contents"></span>   <!-- 割り当てのとおりに renderKeyUI() が描く -->
        <span class="tt-kh-end"><button type="button" class="btn ghost small" id="keyHintAll">すべて <kbd>?</kbd></button><button type="button" class="btn ghost small icon" id="keyHintClose" aria-label="キー操作の手がかりを閉じる" title="閉じる(「キー操作」の一覧からまた出せます)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></span>
      </div>
     </div>
      <div id="segs"></div>
    </section>
    <aside class="tx-stage" aria-label="映像と道具">
    <div class="pbox">
      <div class="tt-docmeta"><label class="lag" title="精度を測るためだけに取っておく文字起こし。辞書・提案・用語の自動追加・追加学習に使わず、再認識もできません。校正を始める前に決めてください"><input type="checkbox" id="evalSet">評価用にする(学習・辞書に使わない)</label></div>
      <div id="docClip" class="tt-clip" hidden></div>
      <div id="evalBanner" class="notice" hidden><b>評価用の文字起こしです。</b>辞書・提案・追加学習の元にはなりません。再認識はできません。一括置換と提案の採用は使えません(正解が機械で書き換わってしまうため)。</div>
      <!-- 評価用の文書の「確かめ済み」(動画を全部聞いて直した印 evalReviewed。定点に数えるのはこれだけ)。app-learn.js の renderEvalReview -->
      <div class="tt-evrev" id="evrBox" hidden><span class="pill" id="evrPill"></span><span class="hint" id="evrText"></span>
        <button type="button" class="btn small" id="evrMark" title="編集中の内容を保存してから、この動画を「全部聞いて確かめた」にします(残りの行も校正済みに)">全部聞いて直したので済みにする</button>
        <button type="button" class="btn small ghost" id="evrUndo" hidden>取り消す</button>
        <button type="button" class="btn small ghost" id="evrRedo">この動画を作り直す(今の設定で)</button></div>
      <div id="conflictBar" class="notice" hidden role="alert"><b>別の場所で先に更新されています。</b>別のタブ・再認識・話者判別などで、保存済みの内容がこの画面の読み込み時と変わっています。自動保存は止めています。
        <div class="row"><button type="button" class="btn small" id="cfReload">保存済みの内容を読み込み直す(この画面の未保存の変更は消えます)</button><button type="button" class="btn small danger" id="cfForce">この画面の内容で上書きする</button></div></div>
      <!-- 映像と再生の道具。1列の画面(狭い画面)では、ここだけを画面の上に固定する(一覧に早く届くように) -->
      <div class="tt-player">
        <div class="tt-vbox">   <!-- 映像と、映像の上に重ねる字幕だけの箱(字幕の位置の基準。下の再生の道具を含めない) -->
          <video id="player" controls preload="metadata" playsinline></video>
          <!-- 映像の上に今の行を字幕として重ねる。止まっているときは選んだ行、再生中は再生位置の行。装飾扱い(同じ情報は一覧から読める) -->
          <div class="tt-caption tt-cap-look" id="playerCaption" aria-hidden="true" hidden></div>
        </div>
        <p class="hint" id="playerMsg" hidden><span id="playerMsgText"></span><button type="button" class="btn small" id="playerRelink" hidden>動画を選び直す</button></p>
        <div class="tools tools-play" role="group" aria-label="再生">
          <label class="lag" title="再生の速さ">速さ <select id="rate" class="mini"><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="1.75">1.75×</option><option value="2">2×</option></select></label>
        </div>
      </div>
      <div id="diarBanner" class="notice" hidden></div>
      <div class="tt-edit">
        <div class="tools" role="group" aria-label="編集">
          <button type="button" class="btn small" id="btnAddAt" title="いま再生している位置に、空の行を足します(認識で抜けたセリフを書き足すとき)。選んだ行の前後に足すときは、行の下の「＋前に行」「＋後に行」か N">＋再生位置に行</button>
          <button type="button" class="btn small" id="btnUndo" disabled title="戻すものがありません">元に戻す</button>
          <details class="pop l" id="moreTools"><summary class="btn small" title="選んだ行・全行を、まとめて校正済み・カット済にします">まとめて <span class="ui-caret" aria-hidden="true"></span></summary><div class="vpop">
            <div class="row"><button type="button" class="btn small" id="btnProofSel" disabled title="行の左端のチェックで行を選ぶと押せます">選択行を校正済みに</button></div>
            <div class="row" style="margin-top:6px"><button type="button" class="btn small" id="btnProofAll" title="聞いて確認した文字起こしだけ押してください(確認していない行が混じると、精度の測定と学習が狂います)">全行を校正済みに</button></div>
            <div class="row" style="margin-top:6px"><button type="button" class="btn small" id="btnSugHigh" hidden title="確度が高い提案だけを、まとめて採用します(元に戻せます)"></button></div>
            <div class="row tt-bulkcut"><button type="button" class="btn small" id="cutSelected" disabled title="行の左端のチェックで行を選ぶと押せます">選んだ行をカット済に</button><button type="button" class="btn small" id="keepSelected" disabled title="行の左端のチェックで行を選ぶと押せます">選んだ行を残す</button></div>
            <div class="row" style="margin-top:6px"><button type="button" class="btn small" id="rtSelected" disabled title="行の左端のチェックで行を選ぶと押せます" data-title="選んだ行(校正済みは外す)の開始・終了を、認識のときの言葉(単語)の時刻に合わせます。候補のある行だけ・件数を確かめてから。元に戻す 1 回で戻せます">選んだ行の時刻を言葉に合わせる</button></div>
            <span class="hint" id="cpSelHint">行の左端のチェックで選んだ行を、まとめて変えます</span></div></details>
        </div>
        <div class="tools tools2">
          <span class="hint" id="sessStat"></span>
        </div>
        <div class="terms" id="terms" hidden></div>
        <!-- 進み具合の帯のクリックはマウスの便利(キーでは S / W・↓ / ↑ で行を移動できる) --><div class="stripbox" id="stripBox" data-ui-audit-allow="A-25" title="全体の進み具合。クリックでその位置へ移動します"><canvas id="strip"></canvas><i id="stripHead"></i></div>
        <p class="tt-strip-legend" id="stripLegend"><span><i class="ok" aria-hidden="true"></i>校正済み</span><span><i class="warn" aria-hidden="true"></i>要確認</span><span><i class="off" aria-hidden="true"></i>未校正</span></p>   <!-- 色だけで伝えない(凡例を文字で) -->
      </div>
    </div>

    <details class="card tt-tool tt-lockable" id="spDetails"><summary>話者 <span class="hint">自動判別・名前・割り当て</span></summary>
      <!-- 評価用で話者の無い行があるとき:候補(覚えた声 → メンバーのフォルダ → 配信の文脈)から1人選んで全行に(既存の 1人指定 = 話者判別の「1人」)。app-jobs.js の renderSpAll -->
      <div class="fld" id="spAllBox" hidden><span class="l">全行をこの人に(評価用)</span>
        <div class="row"><select id="spAllName" aria-label="全行に付ける話者" style="width:auto;max-width:300px"></select>
          <input id="spAllNew" type="text" maxlength="30" placeholder="名前(例: さくらみこ)" aria-label="全行に付ける話者の名前" hidden style="width:12em">
          <button type="button" class="btn small" id="spAllGo">全行をこの人に</button></div>
        <span class="hint" id="spAllHint"></span></div>
      <div class="fld"><span class="l">話者の自動判別</span>
        <div id="diarSetup"></div>
        <div class="row"><label class="lag">人数 <select id="diarNum" style="width:auto"><option value="0">自動</option><option value="1">1人(判別せず全部の行を1人に)</option><option value="2">2人</option><option value="3">3人</option><option value="4">4人</option><option value="5">5人</option><option value="6">6人</option><option value="7">7人</option><option value="8">8人</option></select></label><span class="hint tt-diarnum-why" id="diarNumWhy" title="人数は文書ごとに覚えます(選んでいない文書は、その文書の話者の数)"></span>
          <label class="lag">判別モデル <select id="diarEmb" style="width:auto;max-width:280px"></select></label>
          <button type="button" class="btn small primary" id="diarGo">話者を自動で判別</button></div>
        <label class="lag"><input type="checkbox" class="ui-switch" id="diarSmooth">短い 1 行だけ別の人になるのをならす(試験中)</label>
        <span class="hint">2人の対談なら「2人」を指定してください(「自動」だと、1人を複数に分けたり、逆にまとめたりしやすくなります)。「判別モデル」は声の特徴を見分ける部分です。日本語の音声でどれが合うかは、同じ範囲で切り替えて比べてください。すでに割り当てた話者は置き換わります(「ゲーム音声など」の行・字幕に出さない行・「声が重なる」のメモを付けた話者のある行は変えません)。判別中は編集できません。</span></div>
      <div class="fld"><span class="l">名前の変更・手動での割り当て</span>
        <div id="spList"></div>
        <div class="row" style="margin-top:6px"><button type="button" class="btn small" id="spAdd">話者を追加</button>
          <label class="lag">選択した行の話者 <select id="spBulk" style="width:auto"></select></label><button type="button" class="btn small" id="spApply">適用</button>
          <label class="lag"><input type="checkbox" id="selAll">全行を選択</label><span class="hint" id="selCount"></span></div>
        <span class="hint">「聞く」で、その人の発言を順に再生できます(誰かを確かめて、名前を付けてください)。間違った行は、行の話者欄か、行の左端のチェックで複数行を選んで直せます。「要確認: 声が混ざっている可能性」は、1つの行に複数人の声が入っている行です(分割して直せます)。</span></div>
      <div class="fld"><span class="l">声を覚える(次から名前を自動で付ける)</span>
        <label class="lag"><input type="checkbox" class="ui-switch" id="diarRecog" checked>話者を判別したら、覚えている声と比べて名前を付ける</label>
        <div class="row" style="margin-top:6px"><button type="button" class="btn small" id="voiceLearn">この文書の話者の声を覚える</button><span class="hint" id="voiceLearnHint"></span></div>
        <details class="ui-disclosure" id="voiceBox" style="margin-top:6px"><summary>覚えている声 <span class="hint" id="voiceCount"></span></summary><div id="voiceList"></div></details>
        <span class="hint">名前を付けた話者(「話者1」のような仮の名前は除く)の、1秒以上の行の声を覚えます。同じ人をもう一度覚えると、前の声と混ぜて精度が上がります。
          判別モデルごとに別に覚えます。似ている度合いが足りないとき・2人の声が近いときは名前を付けません(「話者n」のまま)。
          声の特徴はこの PC の作業データ(voices フォルダ)にだけ保存します。人に渡すフォルダやパックには入りません。</span></div>
    </details>

    <details class="card tt-tool tt-lockable" id="fixDetails"><summary>文字をまとめて直す <span class="hint">置換・再認識・別のエンジン</span></summary>
      <div class="fld"><span class="l">一括置換</span>
        <div class="row"><input id="repFrom" type="text" placeholder="置換前" style="flex:1;min-width:120px"><span>→</span><input id="repTo" type="text" placeholder="置換後" style="flex:1;min-width:120px"><button type="button" class="btn small" id="repGo">すべて置換</button></div>
        <label for="repDict" class="hint" style="margin-top:6px">置換辞書(1行に「誤=>正」。保存され、どの文字起こしにも使えます。|誤|=>正 と縦棒で挟むと、カタカナ・漢字・英数字の並びの途中には当てません)</label>
        <textarea id="repDict" rows="3" placeholder="例:&#10;ふぶき=>フブキ"></textarea>
        <div class="row"><button type="button" class="btn small" id="repDictGo">辞書を全体に適用</button><span class="hint" id="repMsg"></span></div></div>
      <div class="fld"><span class="l">再認識(文字の間違いを、別のモデルで直す)</span>
        <div class="row"><label class="lag">モデル <select id="rtModel" style="width:auto;max-width:300px"></select></label>
          <label class="lag">対象 <select id="rtTarget" style="width:auto"><option value="text">文字の要確認の行</option><option value="flagged">疑わしい行(文字が少ない = 抜けの可能性)</option><option value="sel">選択した行</option><option value="all">すべての行</option><option value="range">選択した行の最初〜最後を、まとめて(間の行も含む)</option><option value="whole">動画全体(直した行は残す)</option></select></label>
          <button type="button" class="btn small primary" id="rtGo">再認識</button><span class="hint" id="rtHint"></span></div>
        <span class="hint">認識の失敗が多い行を、重いモデル(large-v3 など)で認識し直します。対象の行の音声だけを処理します(CPU では、行数に応じて時間がかかります)。BGM が大きい・声が重なった行は、直らないこともあります。直した行は残り、機械の結果が変わった行には印「機械の結果が変わりました」を付けてお知らせします。直していない行は新しい文字になります(直前の状態は「以前の版に戻す」に残ります)。判別中・再認識中は編集できません。</span></div>
      <div class="fld"><span class="l">別のエンジンの候補(試験中)</span>
        <div class="row"><label class="lag keep">エンジン <select id="altEngine" style="width:auto;max-width:300px"></select></label>
          <button type="button" class="btn small" id="altGo">別のエンジンでも聞く</button></div>
        <span class="hint" id="altMsg"></span>
        <span class="hint">同じ音声を別のエンジンでも認識し、今の文字と食い違う所の行に「別」の候補を出します(採用・却下は行の候補で)。文字は自動では書き換えません。
          聞いている間も編集できます。評価用の文字起こしには出しません。</span></div>
    </details>

    <details class="card tt-tool" id="exDetails"><summary>書き出し <span class="hint">字幕・テキスト・次のツールへ</span></summary>
      <div class="fld"><span class="l">ダウンロード</span>
        <div class="row">
          <label class="lag">時刻の基準 <select id="exBase" style="width:auto"><option value="rel">範囲の開始を0秒にする(切り抜き用)</option><option value="abs">元動画の時刻のまま</option></select></label>
          <label class="lag">折り返し <select id="exWrap" style="width:auto"><option value="0">しない</option><option value="12">12文字</option><option value="16">16文字</option><option value="20">20文字</option><option value="24">24文字</option><option value="32">32文字</option></select></label></div>
        <div class="row" style="margin-top:6px"><label class="lag"><input type="checkbox" id="exSpk">話者名を付ける</label>
          <label class="lag"><input type="checkbox" id="exSel">選択した行だけ</label><label class="lag"><input type="checkbox" id="exTs">テキストに時刻を付ける</label></div>
        <div class="row tt-exbtns" style="margin-top:8px"><button type="button" class="btn small" data-ex="srt">SRT</button><button type="button" class="btn small" data-ex="vtt">VTT</button><button type="button" class="btn small" data-ex="txt">テキスト</button><button type="button" class="btn small" data-ex="json">JSON</button></div>
        <p class="hint tt-nosub-count" id="exNoSub" hidden></p>
        <span class="hint">「範囲の開始を0秒」は、切り抜き動画に字幕を付けるときの設定です。「高速」で書き出した動画は開始が数秒手前にずれるため、字幕もずれます。</span></div>
      <div class="fld" id="handoffBox"><span class="l">作業用フォルダに保存(次のツールへ渡す)</span>
        <div class="tt-exbtns"><button type="button" class="btn small" data-beside="transcript-v1" title="校正した文字起こし(話者・校正済み・カット済の印つき)を、動画のフォルダの「作業用」に「動画名.transcript.json」で保存します。cut2resolve はこれを読みます">文字起こし(.transcript.json)</button><button type="button" class="btn small" data-beside="srt" title="字幕を、動画と同じフォルダに「動画名.srt」で保存します(プレーヤーが自動で読む名前)">字幕(.srt)</button></div>
        <div id="handoffOut" class="tt-handoff" hidden role="status"></div>
        <span class="hint">ダウンロードフォルダではなく、元の動画のフォルダの中の「作業用」フォルダに保存します(出力先に途中のファイルを並べないため)。先に自動保存が終わるのを待ってから書き出します。字幕は「元動画の時刻のまま」で、カット済の行も含みます(折り返し・話者名は上の設定を使います)。同じ名前のファイルがあるときは、このツールが前に書いたものだけ上書きし、それ以外は「(2)」を付けた別名にします(字幕は常に別名)。</span></div>
    </details>

    <details class="card tt-tool tt-lockable" id="hiDetails"><summary>以前の版に戻す <span class="hint">自動バックアップ</span></summary>
      <span class="hint" style="display:block;margin-top:8px">保存内容を、10分ごと、および再認識・話者判別の直前に自動で残します(1本あたり最新30世代)。間違えて直したり消したりしたときは、ここから戻せます(戻す前の状態も残ります)。まだ一度も編集していない文字起こしには、以前の版はありません。</span>
      <div class="row" style="margin-top:8px"><button type="button" class="btn small" id="hiRefresh">以前の版を読み込む</button></div><div id="hiList"></div>
    </details>
    <p class="hint" id="docInfo"></p>
    </aside>
   </div>
   </div>`;
  T.dialogs = `<dialog id="keys" aria-labelledby="keysT">
  <div class="ui-dlg-head"><h2 id="keysT">キー操作の一覧</h2><form method="dialog"><button class="btn ghost small icon" aria-label="閉じる" title="閉じる(Esc・?)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></form></div>
  <div class="ui-dlg-body">
  <div id="keysList"></div>   <!-- キーの一覧 = キー配置(UIKit.keymap)。キーを変える場所はここだけ(設定の歯車には開くボタンだけ) -->
  <p class="tt-flow" id="keysFlow"></p>   <!-- 基本の流れ(今の割り当てから renderKeyUI() が書く) -->
  <p class="hint" style="margin:8px 0 0">キーのない操作: 選んだ行の下に出るボタンで、時刻の微調整(開始 −/＋・終了 −/＋。幅は右上の「設定」の「再生・行の操作」)・時刻を再生位置に・行の追加(前/後)・分割・結合・削除。行の右の「残す/カット済」で、Resolve の仮編集に残すかを決めます(まとめては「まとめて」のメニュー。区間を細かく決めるのは 2 カット のタブ)。2 カット のタブでは、ホイールで拡大縮小(マウスの位置が中心)・Shift+ホイールで横に移動。区間の端のドラッグ中は Alt で吸い付きません。字幕の段の行を押して選ぶと、端のつまみのドラッグ(または Q / W で端を選んで , . で1コマ)で行の時刻を直せ(前後の行は越えない。残す行を外へ広げると残す区間も広がる)、「再生位置でこの行を分ける」で行を分けられます。</p>
  <label class="lag" style="margin-top:10px"><input type="checkbox" id="keyHintOn">行の一覧の上に、主なキー操作の手がかりを出す</label>
  </div>
</dialog>
<dialog id="relinkDlg" aria-labelledby="rlT">
  <div class="ui-dlg-head"><h2 id="rlT">動画を選び直す</h2><form method="dialog"><button class="btn ghost small icon" aria-label="閉じる" title="閉じる(Esc)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></form></div>
  <div class="ui-dlg-body">
    <p style="margin:0">動画を移した・名前を変えたときに、この文書が使う動画を新しい場所に付け替えます。行・校正・話者・カットはそのまま残ります。</p>
    <div class="fld"><label class="l" for="rlOld">元のパス(見つかりません)</label>
      <div class="tt-rl-old"><input type="text" id="rlOld" class="mono" readonly><button type="button" class="btn small" id="rlCopy">コピー</button></div></div>
    <div class="fld"><label class="l" for="rlPath">新しいパス</label>
      <div class="tt-rl-old"><input type="text" id="rlPath" class="mono" spellcheck="false" autocomplete="off" placeholder="例: D:\\動画\\配信.mp4"><button type="button" class="btn small" id="rlBrowse" title="パソコンのファイルを選ぶ窓を開きます(選ぶと、すぐに確かめます)">参照…</button></div></div>
    <p class="hint" style="margin:4px 0 0">「参照…」で動画を選ぶか、エクスプローラーで動画を Shift+右クリック →「パスとしてコピー」で取ったパスを貼り付けます(前後の " はそのままでかまいません)。このパソコンのドライブの動画を選べます(ネットワーク上のファイルは選べません)</p>
    <div class="row" style="margin-top:8px"><button type="button" class="btn" id="rlCheck">確かめる</button></div>
    <div class="tt-rl-res" id="rlResult" hidden role="status"></div>
    <label class="lag" id="rlAcceptRow" hidden style="margin-top:8px"><input type="checkbox" id="rlAccept">長さが違うのを分かったうえで付け替える</label>
    <p class="hint" style="margin:10px 0 0">前の状態は、付け替えたあとも「以前の版に戻す」で戻せます。</p>
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button type="button" class="btn" id="rlCancel">やめる</button><button type="button" class="btn primary" id="rlGo" disabled>付け替える</button></div>
  </div>
</dialog>`;
  T.docbar = `   <!-- 題名の行(どのタブにも出す): 題名・配信者・長さ・元の配信の位置と、校正の進み具合・残す区間とカット後の長さ -->
   <div class="tt-docbar" id="docBar">
     <input id="docTitle" type="text" maxlength="120" aria-label="タイトル" title="タイトル(押して直せます)">
     <span class="tt-docbar-meta hint" id="docMeta"></span>
     <span class="tt-docbar-pills" id="docPills"><span class="pill ok" id="pillProof" hidden title="校正済み = 聞いて確認して、この行の文字が正しいと判断した行。精度の測定と、将来の追加学習の正解データになります"></span><span class="pill warn" id="pillCut" hidden></span><span class="pill" id="pillAuto" hidden></span></span>
     <!-- まとめて実行(今の文書。入口の ② の口 /api/flow/submit。入口から開いたときだけ使える。開いていないときは押せない理由を出す) -->
     <details class="ui-menu tt-docauto" id="docAuto">
       <summary class="btn small ghost" title="この文書の残りの作業(文字起こし → パック)を、ホームの「まとめて実行」の順番待ちで進めます"><span>まとめて実行</span></summary>
       <div class="ui-menu-pop tt-docauto-pop">
         <p class="hint">この文書の残りを自動で進めます(行が無ければ文字起こし → パック)。カットの決め方などは下の要約のとおりです。
           進み具合はここに出ます。</p>
         <label class="lag" title="名前を入れると、パックの字幕の文字をその人のメンバーカラーにします(空なら黒い文字)">配信者(字幕の色)
           <input id="docAutoWho" type="text" size="14" placeholder="例: さくらみこ" data-ui-streamer></label>
         <label class="lag"><input type="checkbox" id="docAutoOverwrite">パックがあれば作り直す(上書き)</label>
         <div id="docAutoPanel"></div>
         <label class="lag" title="パックに入れる動画の音量を、カットで残す部分だけ測ってそろえます(パックのタブと同じ設定。どこで変えても同じ値)" hidden>パックの音量 <select id="docAutoLoud" data-ui-packloud></select></label>
         <div class="row"><button type="button" class="btn small primary" id="docAutoGo" title="この文書の残りを、ホームの順番待ちで最後まで進めます">まとめて実行</button></div>
       </div>
     </details>
   </div>`;
  T.settings = `<!-- ⚙ 設定の引き出し(UIKit.settings.mount)のツールの節。画面の色は全体の節にあり、ここには無い -->
<section id="edSettings" hidden>
  <h3>編集</h3>
  <div class="fld"><label for="vFs">文字の大きさ(行の文字)</label><select id="vFs"><option value="13">小</option><option value="15">標準</option><option value="17">大</option><option value="20">特大</option></select></div>
  <div class="fld tt-set-hinted"><label for="vVid">動画の大きさ</label><select id="vVid" title="「音声だけ」は映像を隠して音声だけを聞きます"><option value="l">大</option><option value="m">中</option><option value="s">小</option><option value="a">音声だけ</option></select><span class="hint">「音声だけ」は映像を隠して音声だけを聞きます。</span></div>
  <label class="lag" style="margin-top:10px"><input type="checkbox" id="vDense">行の間隔を詰める(たくさん見える)</label>
  <div class="fld"><label for="vBrk">休憩のお知らせ(操作している時間で数えます)</label><select id="vBrk"><option value="0">なし</option><option value="30">30分ごと</option><option value="45">45分ごと</option><option value="60">60分ごと</option></select></div>
  <label class="lag" style="margin-top:10px" id="autoNextLbl" title="Shift+Space・Shift+↓/↑ で行を移動したとき、その行を自動で再生します(その行の終わりで止まります)。聞いて確認する流れが、左手だけで回ります"><input type="checkbox" id="autoNext">移動したら自動で再生</label>
  <h4 class="tt-set-sub">再生・行の操作</h4>
  <div class="col tt-set-col">
    <label class="lag" title="再生している行が画面の外に出たら、画面をずらして見えるようにします"><input type="checkbox" id="follow" checked>再生に追従</label>
    <label class="lag" title="オフ(標準): 青い太枠は、あなたが選んだ行(↓/↑ / クリック)にだけ付きます。再生中の行は、薄い色と左端の線で示すだけです。オンにすると、太枠も再生に合わせて動きます"><input type="checkbox" id="frameFollow">太枠も再生に合わせる</label>
    <label class="lag" title="行の「開始 −/＋」「終了 −/＋」ボタンで動かす幅"><span>時刻の微調整の幅</span> <select id="adjStep" class="mini"><option value="0.05">0.05秒</option><option value="0.1" selected>0.1秒</option><option value="0.25">0.25秒</option><option value="0.5">0.5秒</option><option value="1">1秒</option></select></label>
  </div>
  <p class="hint" style="margin:8px 0 0">この設定は、このブラウザだけに保存されます。</p>
  <h3 style="margin-top:18px">評価用のフォルダ</h3>
  <p class="hint" style="margin:0 0 6px">この中(下のフォルダも)の動画は、評価用(精度を測るためだけ。学習・辞書に使わない)として文字起こしし、評価用の印は外せません。
    「整理」は動画の名前を「フォルダ名_番号_済 / 未 / 未文字起こし」にそろえ、文書を新しい名前に付け替えます(ホームの起動時にも自動で行います)。済 = 文字のある行がすべて校正済み。
    直下の「評価用_仮置き」の動画は名前を変えず、全行に話者が付いて全行が校正済みになったら、話した時間が最も長いメンバーのフォルダへ移します(整理のときと、ほかの文書へ移ったとき)。</p>
  <div class="fld"><label for="evDirs">フォルダ(1行に1つ・10個まで)</label><textarea id="evDirs" rows="2" class="mono" spellcheck="false" autocomplete="off" placeholder="例: E:\\動画\\評価用データ"></textarea></div>
  <div class="row" style="margin-top:6px;gap:6px"><button type="button" class="btn small" id="evSave">保存</button><button type="button" class="btn small" id="evRun" title="名前をそろえて、文書を付け替えます(処理中の動画・開いている動画は飛ばします)">今すぐ整理</button></div>
  <p class="hint" id="evNote" style="margin:6px 0 0" role="status"></p>
  <h3 style="margin-top:18px">キー配置</h3>
  <p class="hint" style="margin:0 0 6px">キーを変えるのは、キー操作の一覧(?)の中です。</p>
  <button type="button" class="btn small" id="setKeysOpen">キー配置を変える(?)</button>
</section>`;
  var me = document.currentScript;
  if (me && me.dataset.slot && T[me.dataset.slot]) {
    me.insertAdjacentHTML('afterend', T[me.dataset.slot]);
    me.parentNode.removeChild(me);
  }
})();
