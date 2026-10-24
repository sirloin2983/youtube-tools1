友人のアプリ FriendApp(src\friendapp)
=====================================================================

■ これは何
  友人の PC で動かす 2 つ目の玄関です(あなたの PC の玄関は start.bat = src\app\server.py)。
  配信の URL を 1 本貼るか動画ファイルを選んで [送る](配信中・配信前ならライブ = 録画しながら)→ 友人の PC で切り抜き・文字起こし・パックまで作る → 受信箱に届く →
  1 本ずつ見て [受け取る](保存先へ移す)か [見送る](アプリのごみ箱へ)を決める、を 1 枚の画面でします。
  要件: 資料の plan\f1-friend-requirements.md の A・B・C。仕様: 資料の docs\spec\friend.md の 11 節。

■ 起こし方
  友人の PC: アプリのフォルダの FriendApp.exe をダブルクリック。exe の窓(WebView2)が開きます。
    窓・止め方・番号・合言葉・窓と画面の境目は friend-apps\launcher\README.txt。exe が <アプリのフォルダ>\app-<版>\(無ければ
    <アプリのフォルダ>\python と \src)の server.py を子(ジョブオブジェクト)で起こし、起動できない版は前の版へ戻します。
    × ・[すべて止めて終了]・時計の横のアイコンの「止める」は、作業中・預かりがあるときだけ確認([裏で続ける] / [止めて閉じる])。
    待っている依頼は残り、次に開くと続きから。
    ログ: data\app\friendapp\logs\launcher.log(exe)・friendapp.log(Python)
  開発の PC: py -3.12 src\friendapp\server.py [--port 8720] [--no-open]
    exe なしで起こすので、Ctrl+C か [すべて止めて終了] まで動き続けます。窓は Edge のアプリの窓(画面に本物の合言葉を入れる形)。
    見本のデータで画面だけ見るとき: py -3.12 dev\friend_demo.py(本物の作業データには触りません。--missing で初回の準備の画面)

■ 置き場所(アプリのフォルダ 1 つに全部入る)
  <アプリのフォルダ>\data\          処理の部品の作業データ(モデル・この PC の設定・待ちの記録)
  <アプリのフォルダ>\data\app\friendapp\   受信箱の記録 inbox.json・前回の値 form.json・確認用の動画 previews\・ログ
  <アプリのフォルダ>\data\app\outbox\      送り返し(結果の zip と判断の記録 .verdict.json。同期が Dropbox の 送り返し\ へ上げたら消す)
  <アプリのフォルダ>\data\learning\<版>\   学習の束(同期が Dropbox の 学習\ から取る。直近 3 版)
  <アプリのフォルダ>\config.json    Dropbox の鍵(無ければ同期はしない)
  <アプリのフォルダ>\作業\          作っている案件・パック(決めたら案件ごとごみ箱 = 作業\ごみ箱\<日付>\。3 日で消える)
  受け取るの保存先                  %USERPROFILE%\Videos\受け取ったパック(⚙ で選べる)

■ 初回の準備(friendapp\setup.py・places.py・toolcheck.py・画面 ui\setup.html。要件 C-5-1)
  表はアプリのフォルダの fetch.json(dev\build_friend_zip.py が書く)。無ければ(開発の PC)すぐ済み。
  済むまで /friend/ は準備だけの画面 /friend/setup.html へ(送る欄は出さない)。確認なしで自動で始まり、済んだら自動で送る画面へ。
  段 = 足りない物を取る(.part に続きから・SHA-256・zip slip を断る・https だけ)→ 道具を <アプリのフォルダ>\tools\<名前>\ の直下へ浅く置き直す →
  全部の道具(ffmpeg・ffprobe・yt-dlp・deno)を 1 回ずつ動かし、文字起こしを 2 秒の音で 1 回動かす → A(Vulkan)で動かなければ自動で
  エンジン C(NVIDIA 用)の部品を取って確かめ直す(C でも駄目なら「文字起こしが動きません」と詳しい文)。
  空きが足りなければ取らずに理由・失敗は「ネットを確かめて [もう一度]」(続きから)。部品の名前と詳しい文は「詳しく」の中だけ。
  済んだこと(版・機器・道具のファイルの印)は data\app\friendapp\setup.json に残し、次の起動では確かめ直さない(道具が変わったら確かめ直す)。
  準備中は exe がスリープを止め、閉じるときに確かめる(GET /api/friend/state の setup・awake)。
  確かめ: tests\friendapp\test_setup.py・test_toolcheck.py・test_settings.py(本物のネット・道具・文字起こしは動かさない)

■ ⚙ 設定(friendapp\settings.py・画面 ui\settings.js。主の画面は settings.js を読み #btnSettings を置くだけ)
  受け取るの保存先   data\app\friendapp\save-dir.json(無ければ %USERPROFILE%\Videos\受け取ったパック)。変えても今ある物は移さない
  一時保管           スタジオの書き出し先と machine.json の caseRoot をそろえて変える。7-3 = 選び直しても移さない(新しい物から新しい場所)。空き容量はこのドライブで測る
  文字起こしのエンジン A Vulkan / C CUDA = machine.json の device(vulkan / cuda)。見せるだけ。初回の準備・起動のたびに自動で選ぶ
                     (NVIDIA の GPU があり C の部品が取れていれば C。部品が無ければ取って確かめる・駄目なら A のまま。環境変数 YTT_FRIEND_ENGINE=A で A に固定)
  YouTube の API キー data\app\keys.json の youtubeApiKey。貼ると videos.list を 1 回呼んで確かめ、使えるときだけ保存(すぐ効く = 環境変数 YTT_YT_API_KEY)。
                     画面へはキーを返さず「入っています / まだ入っていません」だけ。消すと "" を書く
  空き容量の下限     machine.json の diskMinGB(GB。録画中のライブ係にもすぐ効く)
  カットの既定       data\app\friendapp\form.json の cut(しない / 無音を削る。初めは「しない」= A-8)。送る欄には出さず、送るときの束(pack.cut)と
                     ユーザーの PC への依頼の cut に入る(「しない」は束に入れない)。送った値は行に残る([もう一度送る] も同じ)
  フォルダは [選ぶ] で玄関が Windows のフォルダを選ぶ窓を開く(画面からパスを打たせない。FriendApp.pick_folder = テストと見本は偽物)。[既定に戻す] もある
  処理する PC       form.json の pc(この PC で処理する / 依頼する。依頼するは Dropbox の鍵があるときだけ = C-2-19)
  ライブの切り抜き   form.json の live(感度・待ち・余白。範囲は friendapp\live.py)
  YouTube のログイン  exe の小窓でログインした cookie(data\app\friendapp\secrets\)。[ログアウト] で消す
  フォルダの整理     friendapp\tidy.py(新しい版で起動できたあとの 1 回と ⚙。消すのはアプリのごみ箱へ・3 日で消える)

■ 配信の一覧(friendapp\streams.py・画面は ui\send-list.js。要件 C-2-2〜C-2-5)
  画面の [送る] の左。API キー無し: 名簿 members.json(friend-apps\holo-colors。JP と DEV_IS で channel のある人)の各チャンネルの RSS を 5 分おき・同時 4 本で読み、
  初めて見た動画とライブ中・予定・終わったばかりの物だけ動画のページを 1 回読んで、ライブ中・予定の時刻・長さ・ショート・プレミア・メンバー限定を確かめる
  (出さない = プレミア公開・投稿動画・ショート・メンバー限定。読む前は「確かめ中」)。画面が開いている間はライブの可能性がある物を 90 秒おき。
  段 = ライブ中・これから / 今日 / 昨日(前日の 0 時から。予定は今から 12 時間と今日の 24 時の遅いほうまで)。YouTube に断られたら(429・403)10 分待つ。
  覚えた一覧は data\app\friendapp\streams.json(開いた瞬間は前回の一覧)。各カードの右上の印 = 同じ配信の一番新しい依頼の行の状態。
  名簿のチャンネル ID の確かめ: py -3.12 dev\members_channels.py check

■ 送る欄と送った物(friendapp\api.py・progress.py・画面 ui\send-form.js・sent.js。要件 C-2-6〜C-2-19)
  送る欄 = 一覧のカードか URL(どこでも Ctrl+V)か動画ファイル(落とす・[ファイルを選ぶ]・20 本まで)。区間は 5 つまで(数字だけで打つ・ホイール・
  [−5][−1][+1][+5]・始まりから [+30秒][+1分][+3分]・Enter で次の欄)・区間が無いときだけ本数(1 以上・上限なし・初め 5・前回の値)・配信者の札(名簿・[+ 人])・映像トラック。
  ライブ中・予定は [録画を頼む] / [予約する](1 時間の枠・長さ・配信後の追加。感度・待ち・余白は ⚙)・終わったばかりはアーカイブ待ち(api.tick が 5 分おきに
  配信を調べ、出たら作り始める・1 日出なければ失敗)。処理する PC・重み・カットは ⚙ の値(form.json)。Esc で閉じる(入れかけも消える)。
  落とした動画: exe の窓は FriendHost.sendFiles → POST /api/friend/files {paths}。窓の外は中身を PUT /api/friend/upload(一時保管の 受け取った動画\。1 日で片付け)
  送った物 = 進み具合(段の何番目・残り時間 = 前の依頼の段ごとの秒 inbox.json の stats・順番・空き不足・時間がかかっています)と [取り消す](どの行にも)。
  失敗は 2 段(友人の言葉で次にすること・詳しい文と [コピー])。直る見込みのある物(ネット・Dropbox・空き・分からない)は 3 分おきに 3 回まで自動でやり直す。
  同じ失敗が 2 回目なら [作る人に知らせる] = 送り返しへ <依頼 id>__notice-<at>.notice.json(ログの末尾つき。資料の docs\spec\friend.md の 12-4)

■ 受け取る(friendapp\inbox.py の receive_view・decide・undo・sweep・画面 ui\receive.js。要件 C-3)
  パックは 1 本ずつ届き、1 本ずつ決めます。配信ごとの段(最後に届いた時刻の新しい順・段の中は #番号順 = 配信ごとの通し番号。
  2 回目の依頼は続き・見送って消えた番号も使い回さない = inbox.json の nums)。
  カードを押すと再生画面(1 本ずつの 480p の確認用の動画 = この PC は engine が clip_preview で作る・Dropbox の物は .preview.mp4)。決めると自動で次。
  [受け取る] = <保存先>\<配信の日付>_<配信者>_<題 40 文字>_#番号 へ(保存先の直下に平らに置く。配信ごとのフォルダは作らない。0.99.169 までの物は前の形のまま) / [見送る] / 届かなくてよかった(つまらない・切り方が変)= アプリのごみ箱へ(3 日は [戻す])。
  チェックでまとめて決める帯。判断の記録は送り返しへ <依頼 id>__<パック名>~<at>.verdict.json の v2(good / unknown / bad + reason / retract。12-2)。
  3 日決めない物は自動で見送る(すぐ消す・「3 日たった n 本を片付けました」)。案件のフォルダは最後に決めてから 3 日で片付ける。●n は窓のタイトルと exe の state にも

■ 説明と [?]
  説明は src\friendapp\ui\guide.html(/friend/guide.html)。[?] は 5 か所(送る欄・行を開いた所・⚙・初回の準備・[すべて止めて終了] の横)で、
  節(#send・#receive・#settings・#setup・#close)を新しい窓で開く

■ Dropbox の同期(friendapp\sync.py・部品は friendapp\dropbox.py)
  玄関の裏の糸で、起動の直後・3 分ごと・画面で送る / 決めた直後に 1 回ずつ回ります。鍵はアプリのフォルダの config.json
  (appKey + refreshToken)。無ければ何もせず、画面に小さく「Dropbox の鍵がありません」と出します。
  鍵・access token はログ・画面・送り返しに出しません。Dropbox の名前は全部検査してから使い、手元のファイルの名前には入れません。
  1 回でする事(1 つが失敗してもほかは進める。失敗は次の回にもう一度):
  - ユーザーの PC に頼む: ⚙ の処理する PC を「依頼する」にして送ると、依頼の JSON(<依頼 id>.request.json。形は sync.request_doc)を
    Dropbox の直下に上げます。行の札「ユーザーの PC」。直下から消えたら「ユーザーの PC で作っています」。
    1 時間残っていれば「受付を待っています(n 時間)」と [この PC でやり直す](直下の依頼を消してから、同じ欄でこの PC で作る)。
    結果は 出力\ から同じ行に届きます
  - 出力\ の取り込み: パックは 1 本ずつ(zip + 同じ名前の .preview.mp4 と .meta.json)・.失敗.txt を受信箱へ。
    作る側は 確認用の動画 → .meta.json → zip の順に置くので、zip は .meta.json か .preview.mp4 が見えたらすぐ取り込みます
    (どちらも無い zip は 10 分待ってから出どころ「依頼」として取り込む)。
    依頼の id が受信箱の行と合えばその行・合わなければ新しい行(自動で届いた物は札「依頼なし」)。確認用の動画は先に取ってきます。
    zip は [受け取る] のときだけ取り(大きさと Dropbox の hash を確かめ)、保存先へ展開します(外へ出る名前の zip は断る)。
    [見送る] は取りません。決めたら 出力\ の zip・確認用の動画・.meta.json を消します(見送った物は戻せる 3 日のあと)。3 日決めなければ自動で見送る
  - 送り返し: data\app\outbox の zip と .verdict.json を 送り返し\ へ(上げたら消す・3 日上げられなければ消す)
  - 学習の束: 学習\latest.json が新しければ取り、sha256 を確かめて data\learning\<版>\ へ・この PC の設定の learningDir を向ける
    (ユーザーの PC の作業データ = app\prefs.json に intake.folder がある所では取らない)
  - 更新: FriendApp.exe から動いているとき(YTT_FRIEND_LAUNCHER=1)だけ、更新\latest.json が今の版より新しければ FriendApp-<版>.zip を取り SHA-256 を確かめ、
    src\ と python\ を <アプリのフォルダ>\app-<版>.tmp\ に展開 → そろっていれば app-<版>\ へ。画面の帯に「新しい版 n があります [更新する]」
  確かめ: 同期のログは data\app\friendapp\logs\friendapp.log(「同期の …」の行)。テストは tests\friendapp\test_sync.py・test_dropbox.py(本物の Dropbox にはつながない)

■ 診断の記録(friendapp\diag.py。exe の分は friend-apps\launcher\src\Core.cs の Diag。notes:docs/spec/friend.md の 13-11)
  依頼 1 件ごと(段ごとの始めと終わりと秒・文字起こしの装置と実時間比・外の道具の終了コードと失敗の最後の数行)と、失敗のとき
  (② の前・確認用の動画・同期・初回の準備・② を起こせない・前の版へ戻した・合言葉の違い・思わぬ例外)に、版・Windows の版・GPU の名前と一緒に
  data\app\outbox\<依頼 id か app>__diag-<ミリ秒>.diag.json へ書き、同期が Dropbox の 診断\ へ上げる。
  ユーザー名を含むパス・合言葉・鍵・API キー・動画の中身は入れない(伏せる)。3 日で消す(友人の側は箱と Dropbox・ユーザーの PC は読む道具が)。
  止めるのは環境変数 YTT_FRIEND_DIAG=0。ユーザーの PC の作業データでは書かない。
  読む(ユーザーの PC): py -3.12 -X utf8 dev\friend_diag.py [-n 10] [--errors] [--id <依頼 id>] [--json]
  確かめ: tests\friendapp\test_diag.py・tests\dev\test_friend_diag.py

■ 動画ファイル(friendapp\api.py)
  送る欄の [動画ファイルを選ぶ] で、玄関が Windows のファイルを選ぶ窓を開きます(画面からパスは打たせない。選んだパスは玄関が覚えて id で受ける)。
  題 = ファイル名・配信者は名前の頭の【名前】が名簿に合えば推して「(自動)」(A-7 の仮)。区間・本数・重みは出しません(動画 1 本 = パック 1 本)。
  この PC: 一時保管の <作業>\依頼\<日付>_<題>_<id6>\ へ写してから(行に「動画を写しています(n%)」。元の動画は読むだけ)② へ(30fps にそろえるのは写しだけ)。
    [もう一度送る] は写しが残っていれば写しを使います。写している途中で閉じた行は、次に開いたとき失敗の行(写し直す)
  ユーザーの PC: 同期が動画を Dropbox の直下へ <依頼 id>__<元の名前> で上げてから(行に「Dropbox へ動画を上げています(n%)」)、
    <依頼 id>.request.json(kind video)。[この PC でやり直す] は上げた動画も消します

■ ライブ(friendapp\live.py・live_session.py)
  URL を貼ると、題と別に配信中・配信前かを調べ(yt-dlp で数秒)、そうなら送る欄に [録画を頼む] / [予約する] と 1 時間の枠・長さ・配信後の追加を出します
  (前回の値を覚える = form.json の live。感度・待ち・余白は ⚙)。
  この PC: 玄関の中の ② のライブ係(live_session.FriendLive。録画の部品 src\pipeline\ingest\recorder.py を起こす)が録画を始め、
    依頼と録画の結びつきを data\app\live\requests.json(受信箱の行の id)に。見どころを自動で採用 → 書き出し → 切り抜きごとに ② の実行(パックまで)。
    行は「録画中」→ 切り抜きができるたびに 1 本ずつ届く(録画中でも開いて決められる)→ 録画が終わって作る物が無くなったら「届いた」。
    配信後の追加がオンなら、アーカイブからの分は札「配信後」。[録画を止める] で録画だけ止める(ここまでの分は届く)
    録画の置き場所は <作業>\ライブの録画(10-24 から作る人の PC と同じ決まり: アーカイブ化を確かめた録画だけ消す。非公開と分かった配信と、終わって 24 時間たってもアーカイブにならない配信は、1 本の mp4 につないで「非公開の録画」に残す)
    [すべて止めて終了]・FriendApp.exe の [止める] は録画中でも録画の部品まで止めます。次に開いたとき配信中なら、同じ録画の続きとして録り直します
    (止めていた間は録れていない。配信後の追加がオンなら、その分もアーカイブから補う = A-13)
  ユーザーの PC: <依頼 id>.request.json(kind live・live の設定)を上げる。結果は 出力\ から同じ行に届きます
  確かめ: tests\friendapp\test_live.py(録画の部品・yt-dlp・ネットは偽物)

■ 友人に渡す物の作り方
  1. friend-apps\launcher\build.bat(窓 FriendApp.exe と WebView2 の DLL。zip の直下に入る。build_friend_zip.py が古ければ自分で流す)
  2. py -3.12 dev\build_friend_zip.py
     → --publish で Dropbox の 更新\ に FriendApp-<版>.zip + latest.json(FriendApp の [更新する] で友人の PC へ届く)。zip の直下に members.json(friend-apps\holo-colors の名簿の写し)も入る
     初めて渡すときは --first --with-key(friend-apps\launcher\dist\ にでき、手で渡す。鍵は friend-apps\launcher\config.json = git の外・dev\dropbox_auth.py が作る)
  3. 友人の PC で、FriendApp の [更新する] を押すか、zip をアプリのフォルダに展開する

■ 友人の PC での確かめ(URL の依頼 1 本が友人の PC で処理されて届く)
  1. アプリのフォルダの FriendApp.exe をダブルクリック → 窓が開く(初回は準備だけの画面で部品を取り・確かめる。済むと送る画面へ)
  2. 配信の URL を貼る → 題と「配信者: 〇〇(自動)」が出る → 区間を 1 つ入れて(短い方が早い)[送る]
  3. 行が「送った」→「作っている(書き出し・文字起こし・パックの途中)」→「届いた」に変わる
  4. 受け取るの画面でカードを押す → 確認用の動画を見て [受け取る](保存先の直下に <日付>_<配信者>_<題>_#番号 ができる)・ほかは [見送る]
  5. 全部決めると行が消える。data\app\outbox\ に .verdict.json ができている
  うまくいかないとき: data\app\friendapp\logs\friendapp.log と、行の「失敗」の理由を送ってもらう
