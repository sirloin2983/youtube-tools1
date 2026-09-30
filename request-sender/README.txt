==========================================================
  切り抜き依頼(RequestSender) v1.0.0
==========================================================
切り抜いてほしい配信の URL や、切り抜いた動画を「送る」ボタンで送るだけのアプリです。
送り先は、このアプリを渡してくれた人の Dropbox です(あなたの Dropbox のアカウントやお金は要りません)。
インストールは要りません(Windows 10 / 11 にはじめから入っている .NET Framework で動きます)。

【はじめに(最初に1回)】
  1. 受け取った RequestSender.zip を右クリック →「すべて展開」。できた RequestSender フォルダを、消さない場所(例: ドキュメント)に置く
     (RequestSender.exe・config.json・members.json は、同じフォルダに入れたままにしてください)
  2. RequestSender.exe をダブルクリック
     「Windows によって PC が保護されました」と出たら「詳細情報」→「実行」
     (インターネットで受け取った、署名の無いアプリに出る確認です。最初の1回だけ)
  3. 「右クリックの『送る』でも送れるようにしますか?」と聞かれます。「はい」にすると、
     動画のファイルを右クリック →「送る」→「切り抜き依頼」で、その動画を入れた状態で開きます
     (Windows 11 は右クリック →「その他のオプションを確認」の中の「送る」)

【使い方】
  ■ 切り抜いた動画を送る
    - 動画のファイル(.mp4 .mov .mkv .webm .m4v)を「① 動画を送る」の欄へドラッグ(いくつでも)。「ファイルを選ぶ…」でもよい
    - 「配信者」を選ぶと、字幕がその人の色になります(選ばなくてもよい)
    - 「送る」を押す。大きな動画は時間がかかります。下の棒が右まで進んで「送りました ✓」と出たら終わり
  ■ 配信を切り抜いてもらう
    - YouTube の配信・動画の URL を「② 配信を切り抜いてもらう」の欄に貼る(1行に1本。何本でも)
      使える形: https://www.youtube.com/watch?v=… / https://youtu.be/… / …/live/… / …/shorts/…
    - 「1本の配信から切り抜く数」(1〜10。はじめは 3)を決めて「送る」
  ■ 両方いっぺんに入れて送っても大丈夫です(中で2つの依頼に分けて送ります)
  ■ メモ: 送り先の人へのひとこと(自動の処理には使いません)

  - 送っている途中で窓を閉じると、送るのをやめます(もう一度送り直してください)
  - 送り先の人から返事は来ません。「送りました ✓」が出れば届いています

【うまくいかないとき】
  - 「config.json が見つかりません」: RequestSender.exe と同じフォルダに config.json があるか確かめる
  - 「鍵が使えなくなっています」: 送り先の人に新しい config.json をもらって、今のものと入れ替える
  - 「インターネットにつながりません」: つながっているか確かめて、もう一度「送る」
  - 「Dropbox の空きが足りません」: 送り先の人に伝えてください
  - 途中で失敗したときは、送れたものが画面に出ます。残りだけもう一度送ってください
  - 記録: %LOCALAPPDATA%\RequestSender\request-sender.log(困ったらこのファイルを送り先の人に見せる。鍵は書いていません)

【config.json について(大事)】
  config.json は、送り先の Dropbox の「このアプリ専用のフォルダ」にだけファイルを置ける鍵です。
  他の人に渡したり、ネットに上げたりしないでください。なくしたり漏れたりしたら、送り先の人に伝えてください(鍵を無効にして作り直します)。

【やめるとき】
  RequestSender フォルダを消すだけです。右クリックの「送る」に出したときは、
  エクスプローラーのアドレス欄に shell:sendto と入れて開き、「切り抜き依頼」を消してください。


==========================================================
  ここから下は、アプリを渡す人(PC で受け取る人)向け
==========================================================
友人の PC → Dropbox の API → 自分の Dropbox の「アプリ」フォルダ → 同期 → PC のホームが見て自動で文字起こし、という流れです。
設計: docs/design/friend-intake.md

【鍵を作る(最初に1回)】
  1. https://www.dropbox.com/developers/apps →「Create app」
     - Choose an API: Scoped access
     - Choose the type of access: App folder(アプリ専用のフォルダだけ。Dropbox の他のファイルは読めない・書けない)
     - Name: 例「切り抜き依頼」(この名前がフォルダの名前になる。Dropbox 全体で重ならない名前が必要)
  2. できたアプリの「Permissions」タブで files.content.write だけにチェック →「Submit」
     (読みは要らない。権限を変えたら、鍵は作り直す)
  3. 「Settings」タブの App key を控える。App secret は使わない(PKCE という方式なので secret なしで鍵を作れる)
  4. リポジトリ直下で:  python dev\dropbox_auth.py <App key>
     表示された URL をブラウザで開いて「許可」→ 出てきたコードを貼る → request-sender\config.json ができる
     (鍵の値は画面に出しません。config.json は .gitignore と push.bat の検査でコミットされないようにしてある)
  5. request-sender\build.bat → dist\RequestSender.zip(exe・README.txt・members.json・config.json)を友人に渡す
     zip には鍵が入っているので、人に見られない方法で渡す

【届く場所】
  自分の Dropbox の「アプリ\<アプリの名前>\」(英語の Dropbox では「Apps\<アプリの名前>\」)。
  PC のホームがこのフォルダを見張る(Dropbox のデスクトップアプリで同期しておく)。
  - 動画: <id>__<元の名前>.mp4 など(名前がぶつかると Dropbox が「 (1)」などを付ける。依頼の JSON の files には実際の名前が入る)
  - 依頼: <id>.request.json(いつも最後に送る。これが届いた = そろった、の合図)
    id は yyyyMMdd-HHmmss-<16進 6 桁>。形:
      {"v":1,"kind":"video","id":"…","files":["…__名前.mp4"],"streamer":"さくらみこ","memo":"…","sentAt":"2026-10-01T12:00:00+09:00"}
      {"v":1,"kind":"url","id":"…","items":[{"url":"https://www.youtube.com/watch?v=xxxxxxxxxxx","top":3}],"memo":"…","sentAt":"…"}
    動画と URL を一度に送ると、依頼は2つ(id も2つ)になる

【鍵を無効にする(漏れた・友人に使わせるのをやめる)】
  https://www.dropbox.com/account/connected_apps でアプリの接続を切る(Disconnect)。
  またはアプリの設定(developers/apps)でアプリごと消す。新しく渡すときは「鍵を作る」の 4〜5 をやり直す。

【開発】
  - C# 5・WinForms。Windows に入っている .NET Framework 4 の csc で作る(ホロカラーと同じ形。build.bat)
  - src\Core.cs(URL の読み取り・id・JSON・分け方)/ Dropbox.cs(API)/ Sending.cs(1回の送信)/ MainForm.cs(画面)/ Program.cs(起動・「送る」のショートカット)
  - テスト: build.bat が tests\CoreTests.cs を作って流す(通信はしない)
  - メンバーの一覧は holo-colors\members.json を写す(build.bat)

【変更の記録】
  v1.0.0(2026-09-30)初版
