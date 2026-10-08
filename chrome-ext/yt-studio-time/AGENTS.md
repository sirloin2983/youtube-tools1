# chrome-ext/yt-studio-time — YouTube Studio の一覧に投稿時刻を足す Chrome 拡張(AI 向けの覚え書き)

ユーザー向けの使い方(入れ方・更新・外し方・友人への渡し方)は `README.txt`。ここは作りとテストと注意。

## ファイル
- `manifest.json`: Manifest V3。`content_scripts` 1 つ(`matches` = `https://studio.youtube.com/*`・`run_at: document_start`・`world: MAIN`)。`permissions`・`host_permissions` は無し。版は `version`(README の見出しと同時に上げる)
- `main.js`: 全部ここ。前半は純粋な関数(`harvest`・`choose`・`fmtTime`・`fmtFull`・`tooltip`・`videoIdFromHref`)で node から `require` できる(`module.exports`)。後半が画面(fetch/XHR/attachShadow の包み・MutationObserver・`decorate`)
- `tests/test_main.cjs`: 純粋な部分(node --test)。`tests/e2e_fake_studio.py`: 偽の Studio のページに拡張を入れて通し(Playwright + Edge)
- `build.bat`: node のテスト → `dist/yt-studio-time/`(manifest・main.js・README)→ `dist/YtStudioTime.zip`。友人に渡す zip。`dist/` と `*.zip` は .gitignore

## 仕組み(なぜこの作りか)
- Studio はコンテンツ一覧を内部 API `POST /youtubei/v1/creator/list_creator_videos` から受け取る。応答の各動画に `timePublishedSeconds`(公開)・`timeCreatedSeconds`(アップロード)が入っている(文字列の秒)が、画面は日付だけを出す
- `world: MAIN`(ページと同じ世界)で `window.fetch` と `XMLHttpRequest.prototype.open` を包み、URL が `API_RE` に当たる応答を `harvest` で読んで `times`(videoId → 秒)に控える。`harvest` は入れ子の位置に頼らず「`videoId` と時刻の鍵を持つオブジェクト」を再帰で拾う(Studio が応答の形を少し変えても耐える)
- 行 `ytcp-video-row` のリンク `a[href*="/video/"]` から videoId、`.tablecell-date` の中で日付の形(`DATE_RE`)の文字を直接持つ要素の直後に `span.ytt-pub-time`(HH:MM。`title` に秒までの公開・アップロード)を足す。欄の文字が「アップロード日」ならアップロードの時刻(`choose`)
- 行は Polymer が使い回す(ページ送りで同じ要素の中身だけ変わる)ので、`data-key` = `videoId:秒` で足し直しの要否を見る。Studio の部品が shadow DOM でも拾えるよう `Element.prototype.attachShadow` を包んで shadow root を `roots` に覚え、MutationObserver で見張る。応答を通らずに出た行は `row.video`・`row.__data` からも拾う
- 使わなかった案: YouTube Data API(鍵と 1 日の上限)・動画ごとの視聴ページを読む(30 行で 30 回の通信)。鍵の管理が要らず通信が増えない代わりに、Studio の内部の作り(API の鍵の名前・行の class)が変わると壊れる。壊れたときの調べ方は README の「出ないとき」(`localStorage.yttStudioTimeDebug = '1'` で `[ytt-pub-time]` の記録・`__yttStudioTime.times`)

## 本物の Studio で確かめた仮定(2026-10-09 にユーザーが本物の Studio で「動いた」と確認 = 計画の U9。約 3 時間の配信で確かめた)
下の 3 つは本物の画面で成り立っていた(どの代用の道で拾えたかまでは見ていない)。Studio が作りを変えて出なくなったら、まずここを疑う
- 応答の鍵が `timePublishedSeconds`・`timeCreatedSeconds`(別名の候補は `PUBLISHED_KEYS`・`CREATED_KEYS`)
- 日付の欄が `.tablecell-date`(無ければ `DATE_RE` の文字を持つ要素の親で代用)
- Studio の CSP(Trusted Types を含む)に引っかからない: `innerHTML` は使わず `textContent`・`createElement`・`style.cssText` だけ

## テスト(リポジトリ直下から)
- `node --test chrome-ext/yt-studio-time/tests/test_main.cjs`(node は PATH に無ければ Playwright 同梱 `<playwright>/driver/node.exe`)
- `PYTHONIOENCODING=utf-8 py -3.10 chrome-ext/yt-studio-time/tests/e2e_fake_studio.py`(1 本ずつ)。拡張を入れられるブラウザが要る: Edge を `executable_path` で(headless でも入る)。本物の Chrome は 137 以降 `--load-extension` を無視する。Playwright 同梱の `chrome-win64/chrome.exe` は AI のシェル(デスクトップアプリ)からは spawn UNKNOWN で起動できない(ユーザーのシェルからは動くかもしれない)
- `chrome-ext\yt-studio-time\build.bat`(node のテスト + zip)
- 本物の Studio の画面は手で(README の「入れ方」)。AI は Studio にログインできない。ユーザーが許せば Claude in Chrome で本物の画面の DOM と応答を調べられる

## 配布
- 友人へは `build.bat` の `dist/YtStudioTime.zip`(developer mode で「パッケージ化されていない拡張機能を読み込む」)。自動更新は無い: 直したら zip を作り直して渡し、友人がフォルダの中身を置き換えて「更新」
- Chrome ウェブストア(限定公開 = リンクを知る人だけ)に出せば友人は普通にインストールでき自動更新も効くが、開発者登録(有料・1 回)と審査(数日)が要る。やるならユーザー決定(2026-10-08 時点では未)
- `.crx` を直接渡す方法は Chrome がストア外の crx を拒むので使わない
