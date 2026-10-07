YouTube Studio 投稿時刻(Chrome 拡張) v0.1.0

YouTube Studio(studio.youtube.com)のコンテンツ一覧(動画・ショート・ライブ配信)の「日付」の欄に、
公開(投稿)した時刻を「2026/10/05 14:03」のように足します。欄の小さな文字が「アップロード日」の行は
アップロードした時刻です。時刻の上にマウスを置くと、秒までの公開・アップロードの日時が出ます。
時刻はこの PC の時間帯(日本なら JST)です。外部との通信はありません(自分のブラウザの中だけで動きます)。

■ 入れ方(ストアには出さない。自分の Chrome に直接読み込む)
1. Chrome で chrome://extensions を開く
2. 右上の「デベロッパー モード」をオン
3. 「パッケージ化されていない拡張機能を読み込む」→ このフォルダ(C:\dev\youtube-tools\chrome-ext\yt-studio-time)を選ぶ
4. YouTube Studio のコンテンツの画面を再読み込みする
main.js を直したら、chrome://extensions の拡張の「更新」(丸い矢印)→ Studio を再読み込み。

■ 仕組み(なぜこの作りか)
- Studio は一覧を内部の API(youtubei/v1/creator/list_creator_videos)から受け取っていて、応答には各動画の
  timePublishedSeconds(公開した時刻)・timeCreatedSeconds(アップロードした時刻)が入っています。画面には日付しか出ません
- 拡張はページと同じ世界(manifest の world: MAIN)で動き、fetch と XMLHttpRequest を包んでその応答を控え、
  一覧の行(ytcp-video-row)のリンク /video/<id>/ の id と突き合わせて時刻を書き足します。行が追加・使い回しされるのは
  MutationObserver で見ます(Studio の部品が shadow DOM を使っていても拾えるよう、attachShadow も包んでいます)
- YouTube Data API(鍵が要る・1 日の上限がある)や、動画ごとの視聴ページを読む方法(1 行ごとに 1 回の通信)は使っていません。
  鍵の管理が要らず、通信が増えないためです。代わりに Studio の内部の作りが変わると動かなくなることがあります(下の「動かないとき」)
- 権限(permissions)は要りません。studio.youtube.com の画面に差し込むだけです

■ 動かないとき
1. Studio の画面で F12 → Console に次を入れて再読み込み: localStorage.yttStudioTimeDebug = '1'
2. [ytt-pub-time] で始まる行を見る
   - 「応答から N 本」が出ない → 内部 API の URL か呼び方が変わった(main.js の API_RE・fetch/XHR の包み)
   - 「時刻が無い」 → 応答の中の鍵の名前が変わった(PUBLISHED_KEYS・CREATED_KEYS)。__yttStudioTime.times で控えを見られる
   - 「日付の欄が見つからない」 → 行の作りが変わった(dateCellOf の .tablecell-date)
3. その行(と、Network の list_creator_videos の応答の最初の 1 本分)を AI に渡せば直せます

■ テスト
  node --test chrome-ext/yt-studio-time/tests/test_main.cjs   (純粋な部分。node は Playwright 同梱の driver/node.exe でよい)
  py -3.10 chrome-ext/yt-studio-time/tests/e2e_fake_studio.py   (偽の Studio のページに拡張を入れて通しで。PYTHONIOENCODING=utf-8)
    通しは Edge(Windows に最初から入っている)で流す。本物の Chrome は 137 以降 --load-extension を受け付けないため
本物の Studio の作り(API の鍵の名前・行の class)が変わったことは上では分からない。本物の画面での確認は手で(上の「入れ方」)。

■ 変更の記録
v0.1.0 (2026-10-08) 最初の版。日付の欄に時刻(HH:MM)・マウスで秒までの日時
