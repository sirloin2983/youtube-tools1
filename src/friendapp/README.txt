友人の受信箱(src\friendapp。作り直し中の友人のアプリ = F2。v0.89.0 で F2-1・F2-2・v0.93.0 で F2-3 Dropbox の同期・F2-4 起動役・F2-6 動画ファイルとライブ・v0.95.0 で F2-5 初回の準備と ⚙・v0.96.0 から F3 の作り直し = 送る画面の配信の一覧 F3-2・v0.98.0 で F3-1 窓 FriendApp.exe と F3-5 初回の準備・⚙)
=====================================================================

■ これは何
  友人の PC で動かす 2 つ目の玄関です(あなたの PC の玄関は start.bat = src\app\server.py)。
  配信の URL を 1 本貼るか動画ファイルを選んで [送る](配信中・配信前ならライブ = 録画しながら。F2-6)→ 友人の PC で切り抜き・文字起こし・パックまで作る → 受信箱に届く →
  [受け取る](保存先へ移す)か [要らない](ごみ箱へ)を決める、を 1 枚の画面でします。
  今の C# の送るアプリ(friend-apps\request-sender)は F2-7 まで残します(友人は今もそれで依頼を送っています)。
  要件: 資料の plan\f1-friend-requirements.md の A・B。仕様: 資料の docs\spec\friend.md の 11 節。

■ 起こし方
  友人の PC: アプリのフォルダの FriendApp.exe をダブルクリック。exe の窓(WebView2)が開きます(F3-1)。
    窓・止め方・番号・合言葉・窓と画面の境目は friend-apps\launcher\README.txt。exe が <アプリのフォルダ>pp-<版>\(無ければ
    <アプリのフォルダ>\python と \src)の server.py を子(ジョブオブジェクト)で起こし、起動できない版は前の版へ戻します。
    × ・[すべて止めて終了]・時計の横のアイコンの「止める」は、作業中・預かりがあるときだけ確認([裏で続ける] / [止めて閉じる])。
    待っている依頼は残り、次に開くと続きから。
    ログ: datappriendapp\logs\launcher.log(exe)・friendapp.log(Python)
  開発の PC: py -3.10 srcriendapp\server.py [--port 8720] [--no-open]
    exe なしで起こすので、Ctrl+C か [すべて止めて終了] まで動き続けます。窓は Edge のアプリの窓(画面に本物の合言葉を入れる形)。
    見本のデータで画面だけ見るとき: py -3.10 devriend_demo.py(本物の作業データには触りません。--missing で初回の準備の画面)

■ 置き場所(アプリのフォルダ 1 つに全部入る)
  <アプリのフォルダ>\data\          処理の部品の作業データ(モデル・この PC の設定・待ちの記録)
  <アプリのフォルダ>\data\app\friendapp\   受信箱の記録 inbox.json・前回の値 form.json・まとめ動画・ログ
  <アプリのフォルダ>\data\app\outbox\      送り返し(結果の zip と採否 .verdict.json。同期が Dropbox の 送り返し\ へ上げたら消す)
  <アプリのフォルダ>\data\learning\<版>\   学習の束(同期が Dropbox の 学習\ から取る。直近 3 版)
  <アプリのフォルダ>\config.json    Dropbox の鍵(今の送るアプリと同じ物・同じ場所。無ければ同期はしない)
  <アプリのフォルダ>\作業\          作っている案件・パック(決めたら案件ごとごみ箱 = 作業\ごみ箱\<日付>\。3 日で消える)
  受け取るの保存先                  %USERPROFILE%\Videos\受け取ったパック(⚙ で選べる = F2-5)
  前のアプリの部品(%LOCALAPPDATA%\youtube-tools のモデル)は、初めて開いたときに data\ へ写します(ハッシュが合う物だけ・ネットから取り直さない)。
  古い方を消すのは今の送るアプリをやめるとき(F2-7)。それまでは写すだけです。

■ 初回の準備(F3-5。friendapp\setup.py・places.py・toolcheck.py・画面 ui\setup.html。要件 C-5-1・C-1-2)
  表はアプリのフォルダの fetch.json(devuild_friend_zip.py が書く)。無ければ(開発の PC)すぐ済み。
  済むまで /friend/ は準備だけの画面 /friend/setup.html へ(送る欄は出さない)。確認なしで自動で始まり、済んだら自動で送る画面へ。
  段 = 前のアプリの部品を写す(%LOCALAPPDATA%\youtube-tools。ハッシュが合う物だけ。消さない)→ 足りない物を取る(.part に続きから・SHA-256・
  zip slip を断る・https だけ)→ 道具を <アプリのフォルダ>	ools\<名前>\ の直下へ浅く置き直す(0.95.0 の「ffmpeg が見つかりません」の元)→
  全部の道具(ffmpeg・ffprobe・yt-dlp・deno)を 1 回ずつ動かし、文字起こしを 2 秒の音で 1 回動かす → A(Vulkan)で動かなければ自動で
  エンジン C(NVIDIA 用)の部品を取って確かめ直す(C でも駄目なら「文字起こしが動きません」と詳しい文)。
  空きが足りなければ取らずに理由・失敗は「ネットを確かめて [もう一度]」(続きから)。部品の名前と詳しい文は「詳しく」の中だけ。
  済んだこと(版・機器・道具のファイルの印)は datappriendapp\setup.json に残し、次の起動では確かめ直さない(道具が変わったら確かめ直す)。
  前のアプリの片付け: 写して同じと確かめた物があれば 1 回だけ「前のアプリを片付けます(約 n GB 空きます)[片付ける] [あとで]」。
  消すのは目録(old-copy.json)に載った写し済みの物だけ。[あとで] なら ⚙ の「前のアプリ」から。
  準備中は exe がスリープを止め、閉じるときに確かめる(GET /api/friend/state の setup・awake)。
  確かめ: srcriendapp	ests	est_setup.py・test_toolcheck.py・test_settings.py(本物のネット・道具・文字起こしは動かさない)

■ ⚙ 設定(F2-5・F3-5。friendapp\settings.py・画面 ui\settings.js。主の画面は settings.js を読み #btnSettings を置くだけ)
  受け取るの保存先   data\app\friendapp\save-dir.json(無ければ %USERPROFILE%\Videos\受け取ったパック)。変えても今ある物は移さない
  一時保管           スタジオの書き出し先と machine.json の caseRoot をそろえて変える。7-3 = 選び直しても移さない(新しい物から新しい場所)。空き容量はこのドライブで測る
  文字起こしのエンジン A Vulkan / C CUDA = machine.json の device(vulkan / cuda)。次の処理から。C にして部品が足りなければすぐ取り始める
  YouTube の API キー data\app\keys.json の youtubeApiKey。貼ると videos.list を 1 回呼んで確かめ、使えるときだけ保存(すぐ効く = 環境変数 YTT_YT_API_KEY)。
                     画面へはキーを返さず「入っています / まだ入っていません」だけ。消すと "" を書く(前のアプリの keys.json のキーへ戻らない)
  空き容量の下限     machine.json の diskMinGB(GB。録画中のライブ係にもすぐ効く)
  カットの既定       data\app\friendapp\form.json の cut(しない / 無音を削る。初めは「しない」= A-8)。送る欄には出さず、送るときの束(pack.cut)と
                     ユーザーの PC への依頼の cut に入る(「しない」は束に入れない = 今までの束のまま)。送った値は行に残る([もう一度送る] も同じ)
  フォルダは [選ぶ] で玄関が Windows のフォルダを選ぶ窓を開く(画面からパスを打たせない。FriendApp.pick_folder = テストと見本は偽物)。[既定に戻す] もある
  処理する PC       form.json の pc(この PC で処理する / 依頼する。依頼するは Dropbox の鍵があるときだけ = C-2-19)
  解析の重み         form.json の useWeights・weights(wAudio・wChat・wComments 0〜3。指定しなければユーザーの PC の設定の値)
  ライブの切り抜き   form.json の live(感度・待ち・余白。範囲は friendapp\live.py)
  前のアプリ         写し済みの古い部品が残っていれば [片付ける]

■ 配信の一覧(F3-2。friendapp\streams.py・画面は ui\send-list.js。要件 C-2-2〜C-2-5)
  画面の [送る] の左。API キー無し: 名簿 members.json(friend-apps\holo-colors。JP と DEV_IS で channel のある人)の各チャンネルの RSS を 5 分おき・同時 4 本で読み、
  初めて見た動画とライブ中・予定・終わったばかりの物だけ動画のページを 1 回読んで、ライブ中・予定の時刻・長さ・ショート・プレミア・メンバー限定を確かめる
  (出さない = プレミア公開・投稿動画・ショート・メンバー限定。読む前は「確かめ中」)。画面が開いている間はライブの可能性がある物を 90 秒おき。
  段 = ライブ中・これから / 今日 / 昨日(前日の 0 時から。予定は今から 12 時間と今日の 24 時の遅いほうまで)。YouTube に断られたら(429・403)10 分待つ。
  覚えた一覧は data\app\friendapp\streams.json(開いた瞬間は前回の一覧)。各カードの右上の印 = 同じ配信の一番新しい依頼の行の状態。
  名簿のチャンネル ID の確かめ: py -3.10 dev\members_channels.py check

■ 説明と [?](F2-5。9-3)
  説明は src\friendapp\ui\guide.html(/friend/guide.html)。[?] は 5 か所(送る欄・行を開いた所・⚙・初回の準備・[すべて止めて終了] の横)で、
  節(#send・#receive・#settings・#setup・#close)を新しい窓で開く

■ Dropbox の同期(F2-3。friendapp\sync.py・部品は friendapp\dropbox.py)
  玄関の裏の糸で、起動の直後・3 分ごと・画面で送る / 決めた直後に 1 回ずつ回ります。鍵はアプリのフォルダの config.json
  (appKey + refreshToken。今の送るアプリと同じ)。無ければ何もせず、画面に小さく「Dropbox の鍵がありません」と出します。
  鍵・access token はログ・画面・送り返しに出しません。Dropbox の名前は全部検査してから使い、手元のファイルの名前には入れません。
  1 回でする事(1 つが失敗してもほかは進める。失敗は次の回にもう一度):
  - ユーザーの PC に頼む: 「詳しく」の処理する PC を「ユーザーの PC」にして送ると(前回の値を覚える・[送る] が「送る(ユーザーの PC へ)」に)、
    依頼の JSON(今の送るアプリの URL の依頼と同じ形)を Dropbox の直下に上げます。行の札「ユーザーの PC」。
    直下から消えたら「ユーザーの PC で作っています」。1 時間残っていれば「受付を待っています(n 時間)」と [この PC でやり直す]
    (直下の依頼を消してから、同じ欄でこの PC で作る)。結果は 出力\ から同じ行に届きます
  - 出力\ の取り込み: 組(.group.json + まとめ動画 + 1 本ずつの zip)・1 本(zip + .preview.mp4・.meta.json)・.失敗.txt を受信箱へ。
    依頼の id が受信箱の行と合えばその行・合わなければ新しい行(自動で届いた物は札「依頼なし」)。まとめ動画は先に取ってきます。
    zip は [受け取る] のときだけ取り(大きさと Dropbox の hash を確かめ)、保存先へ展開します(外へ出る名前の zip は断る)。
    [要らない] は取りません。組の全部を決めたら 出力\ の zip・まとめ動画・組の一覧・印を消します。3 日決めなければ自動で要らない
  - 送り返し: data\app\outbox の zip と .verdict.json を 送り返し\ へ(上げたら消す・3 日上げられなければ消す)
  - 届け方: 送る欄の届け方を変えたら 設定\届け方.json を置き換え(ユーザーの PC が自動で届ける組の本数)
  - 学習の束: 学習\latest.json が新しければ取り、sha256 を確かめて data\learning\<版>\ へ・この PC の設定の learningDir を向ける
    (ユーザーの PC の作業データ = app\prefs.json に intake.folder がある所では取らない)
  - 更新: 起動役から動いているとき(YTT_FRIEND_LAUNCHER=1)だけ、更新\latest.json が今の版より新しければ zip を取り SHA-256 を確かめ、
    src\ と python\ を <アプリのフォルダ>\app-<版>.tmp\ に展開 → そろっていれば app-<版>\ へ。受信箱に「新しい版 x を入れました(次に開いたときから)」
  確かめ: 同期のログは data\app\friendapp\logs\friendapp.log(「同期の …」の行)。テストは src\friendapp\tests\test_sync.py・test_dropbox.py(本物の Dropbox にはつながない)

■ 動画ファイル(F2-6。friendapp\api.py)
  送る欄の [動画ファイルを選ぶ] で、玄関が Windows のファイルを選ぶ窓を開きます(画面からパスは打たせない。選んだパスは玄関が覚えて id で受ける)。
  題 = ファイル名・配信者は名前の頭の【名前】が名簿に合えば推して「(自動)」(A-7 の仮)。区間・本数・重みは出しません(動画 1 本 = パック 1 本)。
  この PC: 一時保管の <作業>\依頼\<日付>_<題>_<id6>\ へ写してから(行に「動画を写しています(n%)」。元の動画は読むだけ)② へ(30fps にそろえるのは写しだけ)。
    [もう一度送る] は写しが残っていれば写しを使います。写している途中で閉じた行は、次に開いたとき失敗の行(写し直す)
  ユーザーの PC: 同期が動画を Dropbox の直下へ <依頼 id>__<元の名前> で上げてから(行に「Dropbox へ動画を上げています(n%)」)、
    <依頼 id>.request.json(kind video。今の送るアプリと同じ鍵)。[この PC でやり直す] は上げた動画も消します

■ ライブ(F2-6。friendapp\live.py・live_session.py)
  URL を貼ると、題と別に配信中・配信前かを調べ(yt-dlp で数秒)、そうなら送る欄の下に 6 つの設定(感度・1 時間の枠・長さ 10〜180 秒(仮)・待ち・余白・
  配信後の追加)を出します(前回の値を覚える = form.json の live)。本数は「録画 1 本で自動で切る上限」。ボタンは [録画を頼む]。
  この PC: 玄関の中の ② のライブ係(live_session.FriendLive。録画の部品 src\pipeline\ingest\recorder.py を起こす)が録画を始め、
    依頼と録画の結びつきを data\app\live\requests.json(受信箱の行の id)に。見どころを自動で採用 → 書き出し → 切り抜きごとに ② の実行(パックまで)。
    行は「録画中」→ 切り抜きが届け方の n 本たまるごとに組(録画中でも開いて決められる)→ 録画が終わって作る物が無くなったら残りを 1 組・「届いた」。
    配信後の追加がオンなら、アーカイブからの分は別の組(配信後)。[録画を止める] で録画だけ止める(ここまでの分は届く)
    録画の置き場所は <作業>\ライブの録画(終わって 3 日で消す。配信後の追加が済んでから)
    [すべて止めて終了]・起動役の [止める] は録画中でも録画の部品まで止めます。次に開いたとき配信中なら、同じ録画の続きとして録り直します
    (止めていた間は録れていない。配信後の追加がオンなら、その分もアーカイブから補う = A-13)
  ユーザーの PC: <依頼 id>.request.json(kind live・live の 6 つ)を上げる。結果は 出力\ から同じ行に届きます
  確かめ: src\friendapp\tests\test_live.py(録画の部品・yt-dlp・ネットは偽物)

■ 友人に渡す物の作り方(F2-2 の確かめ用)
  1. friend-apps\request-sender\build.bat(今の送るアプリ)と friend-apps\launcher\build.bat(窓 FriendApp.exe と WebView2 の DLL)。どちらも zip の直下に入る
  2. py -3.10 dev\build_friend_zip.py
     → Dropbox の 更新\ に RequestSender-<版>.zip(今の送るアプリの「更新する」で友人の PC へ届く。直下に FriendApp.exe が入る)
     初めて渡すときは --first --with-key(friend-apps\request-sender\dist\ にでき、手で渡す)
  3. 友人の PC で、今のアプリの [更新する] を押すか、zip をアプリのフォルダに展開する

■ 友人の PC での確かめ(1.0.0 の条件 = URL の依頼 1 本が友人の PC で処理されて届く)
  1. アプリのフォルダの FriendApp.exe をダブルクリック → 窓が開く(初回は準備だけの画面で前の部品を写し・取り・確かめる。済むと送る画面へ)
  2. 配信の URL を貼る → 題と「配信者: 〇〇(自動)」が出る → 区間を 1 つ入れて(短い方が早い)[送る]
  3. 行が「送った」→「作っている(書き出し・文字起こし・パックの途中)」→「届いた」に変わる
  4. [開く] でまとめ動画とパックの一覧 → 1 本 [受け取る](保存先に <題>_pack ができる)・ほかを [要らない]
  5. 全部決めると行が消える。data\app\outbox\ に .verdict.json ができている
  うまくいかないとき: data\app\friendapp\logs\friendapp.log と、行の「失敗」の理由を送ってもらう
