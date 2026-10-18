# コードの地図: friend-apps・chrome-ext(C# のアプリ・拡張)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## chrome-ext/yt-studio-time/

- **main.js** (185 行) — YouTube Studio のコンテンツ一覧(動画・ショート・ライブ配信)の「日付」の欄に、公開(投稿)した時刻を足す。

## friend-apps/common/

- **Json.cs** (136 行) — 2 つの友人用アプリ(ホロカラー・切り抜き依頼)で共通の JSON の読み書き。各アプリの build.bat が src と一緒に ../common/*.cs をコンパイルする。
  - 名前: `class Json` :12・`Serializer` :14・`Parse` :21・`ReadFileOrNull` :29・`Str` :42・`Bool` :48・`Int` :55・`Long` :66・`Dict` :76・`List` :82・`Pretty` :96・`NewLine` :130
- **Log.cs** (34 行) — 2 つの友人用アプリ(ホロカラー・切り抜き依頼)で共通の手元の記録。各アプリの build.bat が src と一緒に ../common/*.cs をコンパイルする。
  - 名前: `class Log` :9・`Init` :14・`Write` :19

## friend-apps/holo-colors/

- **make_icon.py** (96 行) — ホロカラーのアイコン(src/app.ico)を作る。絵を変えたいときだけ流す(ビルドには要らない。できた app.ico をコミットする)。
  - 名前: `coverage` :13・`inside_round_rect` :33・`pixels` :41・`bmp_entry` :60・`png_entry` :69・`build_ico` :80

## friend-apps/holo-colors/src/

- **Core.cs** (1025 行) — ホロカラーの中身(画面と Windows に依存しない部分)。tests\CoreTests.cs で確かめる。
  - 名前: `class AppInfo` :16・`class ColorOption` :25・`Clone` :37・`CloneAll` :48・`ReadList` :54・`Validate` :69・`class ColorEntry` :87・`SetColors` :106・`class ColorGroup` :124・`class Branches` :137・`Short` :142・`IsSpecial` :157・ほか 59
- **Dialogs.cs** (842 行) — 設定の画面・色の追加/編集の画面・呼び出しのキーを受け取る欄・コピーしたときの小さな知らせ
  - 名前: `class Ui` :16・`SystemScale` :28・`Px` :34・`Px` :39・`StyleDialog` :50・`Btn` :63・`FieldLabel` :69・`Note` :75・`ButtonRow` :81・`PickColor` :89・`class HotkeyBox` :101・`SetValue` :115・ほか 21
- **MainForm.cs** (435 行) — 色の一覧の窓。呼び出しのキーで出し、コピーしたら(設定しだいで)隠して、呼び出す前の窓へ戻る。
  - 名前: `class MainForm` :10・`OnHandleCreated` :122・`SetFilter` :162・`Refill` :174・`ApplySettings` :204・`SetStatus` :214・`ShowHint` :224・`ResetView` :260・`ProcessCmdKey` :303・`Swatch` :385・`OnFormClosing` :399・`OnActivated` :421・ほか 1
- **PaletteView.cs** (698 行) — 色の札を並べて描く一覧(グループの見出し + 札の格子)。札の位置は Relayout で決め、描くのとクリックの判定で同じものを使う。
  - 名前: `class PaletteView` :13・`class Tile` :15・`class Header` :29・`OnFontChanged` :89・`SetGroups` :119・`OnResize` :139・`Relayout` :145・`BandRowsFor` :190・`HitTest` :242・`HitTestColor` :249・`OnPaint` :263・`FlashCopied` :326・ほか 17
- **Program.cs** (818 行) — 起動・常駐(通知領域のアイコン・呼び出しのキー)・コピー。窓どうしのやりとりは AppController に集める。
  - 名前: `class Options` :20・`Parse` :25・`class Program` :42・`Main` :45・`Fatal` :82・`class AppController` :94・`TakeProblem` :210・`IsUnder` :220・`AllGroups` :243・`ChangeHotkey` :259・`SuspendHotkey` :276・`ResumeHotkey` :283・ほか 26
- **Win32.cs** (283 行) — Windows の API(呼び出しのキー・前面の窓・起動時の常駐)
  - 名前: `class Native` :13・`RegisterHotKey` :23・`UnregisterHotKey` :26・`GetForegroundWindow` :29・`SetForegroundWindow` :32・`IsWindow` :35・`IsWindowVisible` :38・`AllowSetForegroundWindow` :41・`RegisterWindowMessage` :44・`PostMessage` :47・`SendMessage` :50・`GetKeyState` :53・ほか 28

## friend-apps/launcher/src/

- **Core.cs** (503 行) — FriendApp.exe の決まり(版の選び方・版の記録・閉じるときの判断)。画面にも通信にも触らない = tests\Tests.cs で確かめる。C# 5 で書く
  - 名前: `class Layout` :12・`class VersionRecord` :18・`class Versions` :24・`Parse` :30・`Compare` :45・`LayoutOf` :57・`Complete` :63・`Installed` :69・`LegacyVersion` :83・`Pick` :101・`Read` :111・`Q` :128・ほか 29
- **Launcher.cs** (480 行) — FriendApp.exe の起こし方: 窓 1 枚(MainForm = WebView2)を持ち、Python(src\friendapp\server.py)を子としてジョブオブジェクトで起こす。C# 5 で書く
  - 名前: `class Job` :26・`Add` :40・`Kill` :45・`Dispose` :50・`class JOBOBJECT_BASIC_LIMIT_INFORMATION` :56・`class IO_COUNTERS` :67・`class JOBOBJECT_EXTENDED_LIMIT_INFORMATION` :73・`CreateJobObject` :81・`SetInformationJobObject` :83・`AssignProcessToJobObject` :85・`TerminateJobObject` :87・`CloseHandle` :89・ほか 21
- **MainForm.cs** (915 行) — FriendApp.exe の窓 1 枚: WebView2 で Python の画面を出し、時計の横のアイコン・× と止める確認・スリープ止め・●n を持つ。C# 5 で書く
  - 名前: `class MainForm` :20・`OnHandleCreated` :97・`WebViewAvailable` :107・`ProbeWebView` :120・`SetVisibleCore` :134・`OnLoad` :140・`PrintWindow` :179・`class RECT` :182・`GetWindowRect` :185・`DwmGetWindowAttribute` :188・`Capture` :190・`TakeStepShots` :212・ほか 26

## テスト

- chrome-ext/yt-studio-time/tests/e2e_fake_studio.py — YouTube Studio 投稿時刻(Chrome 拡張)の通しの確認。
- friend-apps/holo-colors/tests/CoreTests.cs — ホロカラーのテスト(build.bat が HoloColors.exe を参照して作り、流す)。失敗が1つでもあれば終了コード 1。
- friend-apps/holo-colors/tests/WordsTests.cs — マイワード・お気に入り・最近使ったものの中身のテスト(CoreTests.Main から WordsTests.RunAll(Run); で呼ぶ)
- friend-apps/holo-colors/tests/e2e_holo_colors.py — ホロカラーの通しの確認(Windows だけ)。本物のキー入力とクリックで exe を動かす。
- friend-apps/launcher/tests/Tests.cs — FriendApp.exe のテスト(build.bat が FriendApp.exe を参照して作り、流す)。窓・玄関のプロセス・通信は使わない。失敗が 1 つでもあれば終了コード 1。
