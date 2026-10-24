友人のアプリの窓 FriendApp.exe(friend-apps\launcher。要件は資料の plan\f1-friend-requirements.md の C-1・C-5-3・C-5-4)
=====================================================================

■ これは何
  友人の PC で開くアプリの窓そのものです。C# の exe が WebView2(Edge と同じ表示エンジン)で画面を出し、
  処理の本体の Python(src\friendapp\server.py)を子として起こします。画面(HTML)は Python が配ります。

■ 作り方
  friend-apps\launcher\build.bat(.NET Framework 4 の C# コンパイラ・テストも流す)。
  WebView2 の DLL 3 つ(Microsoft.Web.WebView2.Core.dll・WinForms.dll・WebView2Loader.dll)は dev\fetch_webview2.py が
  NuGet の公式パッケージから取る(版と SHA-256 を固定)。lib\ と build\ は git に入れない。
  dev\build_friend_zip.py が exe と DLL を zip の直下に置く。

■ exe がすること
  - 1 つだけ起動: アプリのフォルダごとの名前つき Mutex。2 つ目は 1 つ目の窓を前に出して終わる(別の場所の同じアプリは止めない)
  - Python を子でジョブオブジェクトに入れて起こす(閉じたら全部止める = exe が落ちても Python と孫の ffmpeg・whisper.cpp・録画の部品が残らない)
  - 版のフォルダ app-<版> を選ぶ・起動できなければ前の版へ戻す(app-versions.json)
  - Python が途中で落ちたら起こし直して画面を読み込み直す(10 分に 3 回まで。Python が {"event":"bye"} と言って終わったときは窓も閉じる)
  - × ・画面の [すべて止めて終了]・時計の横のアイコンの「止める」: 状態を取り直してから、作業中・預かりがあるときだけ確認
    ([裏で続ける](初めから選んだ状態)/ [止めて閉じる]。確認の窓の × と Esc は何もしない)。無ければすぐ止める。
    裏で続けた作業が全部終わったら自分で終わる
  - 時計の横のアイコン: 押すと窓・右クリックで「開く」「止める」・マウスを乗せると「作っています 2 件・録画中 1 件」
  - スリープ止め: Python が awake と言う間だけ SetThreadExecutionState(PC のスリープだけ止める。画面は消えてよい)
  - ●n: まだ決めていない本数を窓のタイトルとタスクバーの重ねる絵に
  - 窓の大きさを覚える(data\app\friendapp\window.json。初めは 1280×800 で真ん中)
  - 外へのリンク(YouTube など)は既定のブラウザ・同じ画面の [?] は小さな説明の窓
  - ⚙ の [YouTube にログイン]: 別のプロファイルの小窓(src\YtLogin.cs の LoginForm)で Google にログイン → robots.txt へ移して cookie を
    data\app\friendapp\secrets\youtube-cookies.txt に書いて閉じる・プロファイルは消す(notes:docs/spec/friend.md の 13-13。中身はログに出さない)
  - WebView2 の本体が無い PC: Edge のアプリの窓で開く逃げ道(このときだけ画面に本物の合言葉を入れる。止めるのはアイコンから)

■ 更新(8 章・A-15。新しい版の入れ方と前の版へ戻す)
  - 取る: Python の同期(src\friendapp\sync.py の 5)が Dropbox の /更新/latest.json を見て、今より新しければ取り、
    大きさと SHA-256 を確かめて <アプリのフォルダ>\app-<版>\ に入れる(src・python と FriendApp.exe・WebView2 の DLL・fetch.json・members.json)。
    latest.json の light(FriendApp-<版>-light.zip = src と直下の物だけ・python と tools なし)があれば先にそれを取り、python は今動いている版から
    manifest の SHA-256 を確かめて写す(1 つでも無い・違えば同じ回で file の全部入りを取る)。light が無い・形が変なら file だけ。
    置く順は light → 全部入り → latest.json → versions.json → 古い zip を消す。file は全部入りのまま(前の形の友人のアプリは light を無視して file を取る)
    Dropbox の /更新/ に残す数: 全部入り 3 版(約 70 MB ずつ)・light 10 版(約 3 MB ずつ)= 約 240 MB(-first.zip は触らない)。versions.json = 作る側の版の台帳
    (新しい順 20 版・zip が消えた版は file/light が null)。友人のアプリは読まない。取る前に空き(320 MB + 作業データが同じドライブなら diskMinGB)を見て、
    足りなければ取らずに次の回へ(診断 update:space)
  - 知らせる: 画面の帯の 1 行(src\friendapp\ui\update.js。画面は帯に <div data-fr-update></div> を置くだけ)に「新しい版 n があります [更新する]」。
    重要な直しを待っている間は「大事な直しが届きました。今の処理が終わったら更新します [今すぐ]」・24 時間入れ替えられなければ「更新が溜まっています [今すぐ更新]」
  - いつ入れ替えるか・確かめ・戻すかは玄関(src\friendapp\upgrade.py)が決め、GET /api/friend/state の swap・verify・rollback で伝える
    (形の正は資料 plan\友人の不具合の自動対応-1025.md の「更新(友人側)」)。exe は swap があればそれに従い(無い前の玄関は作業と預かりが無いときだけ)、
    verify が ok になった版を app-versions.json の good(確かに動いた版。片付けで消さない)にし、rollback {to, why} か確かめの途中で Python が落ちたら
    戻す先より新しい版を全部 bad にして戻す先の exe と DLL を写し、開き直す。起動できなかった・戻したは launcher__fail-<13 桁>.fail.json を
    Dropbox の /診断/ へ直に上げる(config.json の鍵。だめなら送り返しの箱 = 次に起きた Python の同期が上げる)
  - 入れ替える: [更新する] → 作業と預かりが無ければすぐ・あれば終わってから、exe が Python を止め、app-<版>\ の FriendApp.exe と DLL を写し
    (動いている exe と DLL は *.old に名前を変えてから。次の起動で消す)、閉じて新しい exe を起こす
  - 版のフォルダ: 一番新しい版を選ぶ(前の形 <アプリのフォルダ>\src・python も src\ytt\version.py の版で比べる)。1 回起動できた版を current・その前を
    previous にし、current 以下で bad でない版を新しい順に 3 つ(Versions.Keep)残して、それより古い app-<版> を消す(bad の新しい版は残す)。
    友人の PC は 1 版約 200 MB = 常時 3 つで約 600 MB・新しい版を入れた直後は最大約 800 MB。前の形は版のフォルダが 2 つそろったら消す。
    起動できない版は bad にして前の版で起こし直す(新しい方から順に何版でも。起きなかった版は YTT_FRIEND_ROLLBACK に "72,71" の形で渡し、診断 start に bad と installed)

■ 窓と画面の境目
  - 画面の URL: http://127.0.0.1:<番号>/friend/(送る・受け取る)。初回の準備が済むまでは /friend/setup.html(準備だけの画面)へ 302
  - 番号: exe がその都度空いている物を選んで --port で渡す(Python は他の番号へずらさない。使えなければ終了コード 5 → exe が選び直す)。
    録画の部品の番号も exe が選んで YTT_FRIEND_REC_PORT で渡す(ユーザーの入口の 8730 と取り合わない)
  - 合言葉: exe が作って YTT_FRIEND_TOKEN で渡し、WebView2 が同じオリジンへの全部の要求に X-YTT-Token を足す。
    画面の meta ytt-token は中身 host の置き物(ui-kit の UIKit.http がそのまま動く)。画面のコードは UIKit.http で呼び、合言葉を扱わない。
  - 画面 → exe(src\friendapp\ui\host.js の FriendHost):
      FriendHost.isApp            exe の窓の中か
      FriendHost.quit()           [すべて止めて終了](exe が確認する。窓の外は確認なしで /api/shutdown)
      FriendHost.sendFiles(files, cb)   落とした動画ファイル。exe が本物のパスを読んで POST /api/friend/files {paths} を送り、答えを cb(err, json) へ
                                  (画面からパスを送らない決まり)
  - exe → Python(合言葉つき): GET /api/friend/state を 2 秒ごと
      {making, recording, waiting, reserved, archiveWait, setup, undecided, awake, busy, label}
      作業中・預かり = making + recording + waiting + reserved + archiveWait + (setup ? 1 : 0)。数の出どころは server.py の FriendApp.state() と holdings()
    止めるとき POST /api/shutdown(10 秒待って、終わらなければジョブごと)
  - 環境変数(exe → Python): YTT_FRIEND_HOME・YTT_FRIEND_TOKEN・YTT_FRIEND_HOST(webview2 / edge)・YTT_FRIEND_REC_PORT・YTT_FRIEND_LAUNCHER=1(更新を受ける)・
    YTT_FRIEND_ROLLBACK(前の版へ戻したとき。起きなかった版を新しい方から ,で区切る)
  - 開発の PC で確かめるときだけ(どちらも音を出さない = WebView2 の音を消す・Edge の逃げ道は --mute-audio・止まったときの窓と音も出さない): YTT_FRIEND_SHOTS=<フォルダ>(画面の外で起こし関所の写真を撮って終わる)・YTT_FRIEND_NOACTIVATE=1(最小化で出し前に出さない)・YTT_FRIEND_DEVTOOLS=1・
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<番号>(Playwright の connect_over_cdp で画面を調べる)

■ 記録
  data\app\friendapp\logs\launcher.log(exe)・friendapp.log(Python)
  診断: 起動・起こし直し・更新の失敗・合言葉の違い・思わぬ例外を data\app\outbox\launcher__diag-<ミリ秒>.diag.json に(src\Core.cs の Diag。
  ユーザー名を含むパスと合言葉は伏せる・3 日で消す・YTT_FRIEND_DIAG=0 で書かない)。Python の同期が Dropbox の 診断\ へ上げる(notes:docs/spec/friend.md の 13-11)

■ 確かめ
  build.bat の中のテスト(tests\friend-apps\launcher\Tests.cs = 版の選び方・閉じるときの判断・アイコンの文・起こし直しの回数・状態の読み取り)。
  窓そのもの(合言葉の付け足し・起こし直しで読み込み直す・止める・exe を強制で止めると Python も止まる)は、この PC で
  本物の exe を起こして確かめた(手順は作業の記録 docs/worklog/2026-10-12週.md)。
