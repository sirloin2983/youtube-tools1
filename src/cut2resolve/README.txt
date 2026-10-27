cut2resolve(「編集」の部品・API。版は全体で 1 つ = ytt/version.py)
==================================================

切り抜いた動画に「カット」と「字幕」を入れて、DaVinci Resolve(以下 Resolve)で続きを編集できる形(パック)にして渡すツールです。
動画そのものは作り直さず、「どこを残すか」の指示(EDL)と、カット後の時刻に直した字幕(SRT)を作ります。
  EDL … 編集ソフトどうしでカットの位置を受け渡すための、昔からある文字のファイル。Resolve の「読み込み → タイムライン」で読めます。
すべてこのパソコンの中で処理し、動画や字幕を外部に送りません。

■ 準備
  - Python 3(https://www.python.org/downloads/ 。インストール時に「Add python.exe to PATH」にチェック)
  - ffmpeg / ffprobe(文字起こしツール・切り抜きスタジオと同じもの)
  - serve.py(API)はリポジトリのフォルダのまま使う(src の ytt フォルダ(ytt_core)の共通部品を使う)

■ 画面は「編集」にあります
  cut2resolve 自身の画面はありません。同じことは案件の画面(http://localhost:8700/cases)の「カット・パック」のタブでできます。
  入口の中で http://localhost:8700/cut2resolve/ を開くと、統合した旨の案内だけが出ます。
    cut2resolve の機能                              「編集」では
    ① 無音で自動                          2 カット のタブの「たたき台: 無音 ▾」(音量・長さ・前後に残す秒数)
    ② 残す区間(文字起こし・スタジオ)     2 カット のタブの「行から」「スタジオ」(スタジオの残す区間があるときだけ出る)
    ③ 時刻リスト                          2 カット のタブの「たたき台: 時刻リスト ▾」
    試算・カット後の見え方                 2 カット のタブのプレビュー(削った所を飛ばして再生)と、3 パック のタブの「これから作るパック」
    書き出し(Text+ パック)                 3 パック のタブ(置き先の fps・大きさ・出力先・上書きの確認・中止)
  たたき台は区間を決める出発点で、そのあとタイムラインで手で直せます。
  パックを作る部品(pack.py)は src/pipeline/pack/ にあります。パックを作るのは pack.py だけです。
  単独のコマンドはありません(パックを作る道は入口(API)だけ。auto_cut.py・srt2resolve.py は pack.py の部品)。
  このフォルダにあるのは API(serve.py。「編集」とまとめて実行が使う)です。

■ API(serve.py。入口の中の /cut2resolve/api/...)
  - あるのは GET api/ping・api/siblings・api/job?id=(ジョブの状態)と、POST api/plan(試算。ジョブ)・api/build(パックを作る。ジョブ)・
    api/job/cancel・api/open-folder(パックのフォルダだけ)。書き込み系は合言葉(X-YTT-Token)が要る。呼ぶのは「編集」(2 カット・3 パック)と入口の「まとめて実行」
  - ない API(画面のためのもので、使う側が無い): api/state・api/inspect・api/upload・media/<合言葉>(動画の配信)と、
    plan・build の結果の mediaUrl。ない API は 404 を返す
  - 受けない指定(画面のためのもので、送る側が無い): spec.silenceExtra(②③に無音を重ねる)・spec.handles(② の前後の余白)・
    spec.joinGap(近い区間をつなぐ隙間)・spec.advanced の srcStartTc・recStart・reel(開始タイムコード・リール名)・output.fcpxml(補助の FCPXML)・
    output.render・output.crf(粗編集の動画。10-24 に無くした)。送っても黙って無視する(知らない鍵と同じ。400 にしない)。
    API では余白・つなぐ隙間は既定の 0、FCPXML・粗編集の動画は作らない。EDL の開始タイムコードは動画に埋め込まれた値(無ければ 00:00:00:00)・
    タイムラインの先頭 01:00:00:00・リール AX の決まった値。変える道は無い。
    spec.listKind "drop"(時刻リストを削る区間として読む)は、入口のまとめて実行の「カットしない」(listText 空 = 動画全体)が使うので受ける
  - spec.keeps: 残す区間を秒の組 [[開始, 終了], …] でそのまま渡す(「編集」のカット)。余白・最短・つなぎ・無音検出はしない(pack.EDIT_KEEPS)。
    preset と一緒には使えない。0.5 秒より短い区間は注意を出す。上限 5000 区間
  - 文字起こしの行から作るとき(preset "transcript-rows"・mode keep の keepSource "transcript")は、
    区間の端を声の止まる所まで広げる(pack.ROW_EDGE。語頭・語尾が切れないように。終わりは 0.5 秒先・始まりは 0.3 秒前までの無音
    (-35dB・0.15 秒以上)まで。無音が無ければ 前 0.1 秒・後 0.2 秒。カット済の行は越えない)。spec.rowEdge = false で広げない・
    {"after": 秒, "before": 秒} で上限を変える(0〜2 秒)・{"padAfter": 秒}で無音が無いときの「後の余白」を変える(0〜2 秒の数値。真偽・文字・範囲外は 400 bad_value。前の余白 0.1 秒は変えない。
    padAfter が after より大きいときは after も padAfter まで上げる)。{"on": false} でも広げない(padAfter は無視)。keeps・時刻リスト・スタジオの区間には使わない
  - 重なる字幕: Text+ のパックは、カットで詰めたあとの時刻で 0.3 秒以上重なる字幕を別の段に分ける(最大 3 段。計算は resolve_textplus.stack_captions の 1 か所)。
    段 1 = 今までの字幕のトラック、段 2・3 = その上のトラック(映像トラックが N 本なら V(N+1)〜V(N+3))で、縦の位置を上へ 0.2 ずつずらす(LANE_STEP_Y。仮の値 = 実機で見て決める)。
    0.3 秒未満の重なりは、前の字幕の終わりを次の始まりで切る。一度置いた字幕は動かさず、空いているいちばん下の段へ入れる。重なりの無いパックは今までと同じ中身。
    見積もり(summary)に captionLanes・captionsStacked・captionsTrimmed。SRT・EDL は重なったまま。字幕ごとの話者は、字幕を作った行から直接たどる(重なる行でも正しい人の色)
  - 字幕に出さない行: 文字起こしの行の noSub: true は、時間は残す区間に数え、字幕は作らない(pack.row_has_caption)。段分けは noSub を外したあとで数える。見積もりに noSubRows
  - output.speakerStyles: {"話者の名前": {"color": "#RRGGBB" か "RRGGBB"}} = 話者ごとの字幕の見た目(今は色だけ。検査は serve.SPEAKER_STYLE_KEYS の許可の一覧。知らない鍵は捨てる)。
    色の決まり方: 指定の色 → メンバーカラー(speakerColors が真のとき)→ 配信者の色 → 黒。指定は speakerColors が false でも効く。名前は ytt.colors.normalize でそろえて同じときだけ
  - / と /index.html は統合の案内だけを返す(スクリプトなし)
  - パックは最小限: Text+ パックは動画(フォルダの直下)・create_resolve_textplus_project.lua・textplus-template.drb・登録用の .ps1 と .bat だけ。
    手順書(友人へ.txt)は API では書かず、結果の readme(画面の「Resolve での手順を見る」)で返す。
    EDL・カット後の SRT は入れない(output.backup は送っても黙って無視)。
    Text+ の計画の .json(textplus-import.json)は出さない(Lua に埋め込み済み)。
    cut-plan.json はフォルダに置かず、作業データの packs\<ハッシュ>.json(パックを作った記録。%LOCALAPPDATA%\youtube-tools\cut2resolve\packs)に残す。
    「パック済み」「フォルダを開く」はこの記録か、cut-plan.json のあるパックで決める(src/manage/cases/txindex.py)

■ Resolve での読み込み(友人へ.txt にも同じ手順が入ります)
  1. 元動画をメディアプールに入れる
  2. ファイル → 読み込み → タイムライン → EDL を選ぶ(クリップ名で動画と結び付きます)
  3. 字幕: ファイル → 読み込み → 字幕 で SRT を入れ、タイムラインにドラッグ
  ※ 縦動画(Shorts)はタイムラインの解像度を 1080x1920 にしてください。
  Text+ 用パックを選んだ場合は、出力内の「Text+の使い方.txt」に沿って登録し、fps・解像度が合うテストプロジェクトで実行してください。

■ パックの上書き
  出力先にファイルがあるときは止まります(上書きは API の force)。
  上書きのとき、前に写した動画が元の動画と同じ大きさ・更新日時なら、動画のコピーは飛ばします(音量をそろえるときは作り直す。
  音量をかけた写しを飛ばすのは「編集」・まとめて実行(API)のときだけ)。

■ 受け渡しの形式
  notes:docs/spec/pipeline.md を参照。youtube-tools-transcript/v1・youtube-tools-cut-plan/v1 を読みます。

■ 注意
  - 可変フレームレート(VFR)の動画は EDL の時刻がずれることがあります(警告が出ます)。
  - AV1 / H.265 / 10bit の動画は無料版の Resolve で再生できないことがあります。
  - API のサーバーは 127.0.0.1(このパソコン)からだけ使えます。動画は配信しません。
  - ログ: %LOCALAPPDATA%\youtube-tools\cut2resolve\work\serve.log

■ 試算の順番待ちと既定値
  - API の試算(api/plan)は、無音で削る(mode silence・無音を重ねる)試算と、行の端を声の止まる所まで広げる試算のうち、検出結果がまだ覚えてないものだけ、
    他のツールの重い処理の順番(ytt_core.jobs の SLOTS)を待つ(待っている間は「他のツールの処理が終わるのを待っています」。「取り消す」で止められる)。
    検出が要らない試算(時刻リスト・残す区間・検出結果が覚えてある試算)は待たない
  - 一時ファイルの付け替えのやり直し(srt2resolve の _replace_retry)は、ytt_core の fsio と同じ規則(Windows の一時的なロック winerror 5・32・33 だけ 0.1 → 0.2 → 0.4 秒で 4 回まで)
  - 指定を省いたときの値(無音 -35 dB・0.6 秒・0.15 秒、開始タイムコード 01:00:00:00、リール AX)の正は cut2resolve_core の DEFAULT_* と pack.Request の 1 か所

■ 音量をかけた写しも飛ばす(E-15)
  - 「編集」の既定(音量 30%)のように音量をかけて動画を写すとき(音量 %・音量をそろえる。cut2resolve_core.copy_video_gain)も、前と同じ条件なら
    作り直さない。条件 = 元の動画(名前・大きさ・更新日時の秒)・実際にかける量(dB。ffmpeg に渡す小数 2 桁)・書き出しの設定(音声の形式・ビットレート・
    開始タイムコードなど ffmpeg の出力のオプション)。加えて、置き場所の動画が前に写したときのまま(名前・大きさ・更新日時の秒)であること。
    1 つでも違えば作り直す。飛ばしたときは結果の注意に「動画 ○○ は前に同じ音量(-10.5 dB)をかけて写したものと同じ…コピーを飛ばしました。」(info)
  - 記録の置き場所: 作業データの「パックを作った記録」(packs/<フォルダのハッシュ>.json)の鍵 videoCopy(ytt_core.txindex はこの鍵を読まない)。
    パックのフォルダには何も足さない(友人に渡すフォルダを最小限にする・隠しファイルを置かない決まりのため)。
    そのため飛ばすのは記録を書く API(「編集」の 3 パック・入口のまとめて実行)のときだけです。パックのフォルダを動かした・消したときは記録と合わないので作り直す
  - 音量をそろえる(LUFS)ときは、残す区間の音量の測定は毎回する(カットが変わるとかける量が変わるため)。測った量が前と同じ(小数 2 桁)なら写しを飛ばす
  - 判定は cut2resolve_core.same_gain_copy の 1 か所(条件は gain_copy_key・記録は gain_copy_record)

■ 同じ動画はコピーを飛ばす(「気が利く画面へ」段 7 の E-15)
  - パックに動画を入れるとき(Text+ パック)、置き場所に同じ名前の動画があり、大きさと更新日時(秒単位)が
    元の動画と同じなら、コピーを飛ばして前に写したものをそのまま使う。結果の注意(warnings)に「動画 ○○ は前に写したものと同じ…コピーを飛ばしました。」を
    1 行出す(API の warningLevels は info)。違えば上書きでコピーする(写した動画の更新日時は元に合わせる)
  - 理由: 同じ場所にパックを作り直すたびに数 GB の動画を写し直さないため。比べ方は rsync の既定と同じで中身は読まない(読み比べると写し直すのと同じくらいかかる)。
    写した動画は更新日時を元に合わせてあるので、元の動画を作り直した(スタジオで書き出し直した)ときは更新日時が変わり、コピーし直す
  - 音量をそろえる・音量 % のとき(音声を作り直す。cut2resolve_core.copy_video_gain)は対象外で、毎回作り直す(前と同じ条件なら飛ばす。上の「音量をかけた写しも飛ばす」)
  - 動画が同じなら置き換えないので、Resolve などが前のパックの動画を開いたままでも、動画の置き換えで止まらない
    (Windows では開かれているファイルを置き換えられないことがある。Resolve の実機では未確認)
  - 判定は cut2resolve_core.same_copy の 1 か所

■ 素材は 30fps にそろえる
  - Resolve に取り込むスクリプト(Text+ のパックの Lua): 素材が 30fps のとき、開いているプロジェクトの fps が 30 以外でも止めずに置く
    (素材とプロジェクトの fps が違うときの換算をする)。結果の記録 cut2resolve-result.txt が要確認(check)になり、「注意 素材は30fpsですが
    プロジェクトは…fpsです」と出る。大きさ(解像度)が違うときは止める。30fps でない素材(古い 60fps の動画など)の fps の
    違いも止める

■ API で映像トラックの数
  - POST /api/build の output.videoTracks(1〜5。省略 = 1)。友人の依頼の ① 全自動のパックで使う。範囲の外は 400 bad_tracks

■ 映像トラックの数(Text+ のパック)
  - Text+ のパックで、CUT_TextPlus の映像トラックの数を 1〜5 から選べます(pack.build_pack の video_tracks)。
    V1〜V数 に同じカットの動画(重ねて加工する用。V2 から上は映像だけ = 音は A1 の1本)、字幕はいちばん上のトラック(数 + 1)に置く。既定 1 は V1 動画・V2 字幕。
    手順書のトラックの書き方も数に合わせる。結果の記録に字幕のトラック(V3 以上のとき)

■ Text+ の字幕の見た目「lite」(友人用の文字起こし簡易版)
  - Text+ の字幕の見た目に「lite」(MS ゴシック・文字の色とふちの色を話者ごとに変える簡易版)があります(pack.build_pack の textplus_style="lite"・speaker_outlines)。
    大きさ 0.08 は仮(実機で確認)

■ 動画の形式の注意
  - 動画の形式の注意(srt2resolve.codec_warnings。試算・パックの結果の warnings に出る)に、そのほかのコーデックの 10bit(pix_fmt が 10le / 10be で終わる・p010 で始まる)も出す
    (vp9 / av1 / H.265 / H.264 の 10bit・4:2:2・4:4:4 も出す)。ProRes・DNxHD/HR・CineForm などの編集用の形式は 10bit でも Resolve が読めるので出さない
  - 可変フレームレート(VFR)の注意は試算(plan_cut の warnings)に入る。動画に埋め込まれた開始タイムコードの ; 表記の注意も出る

■ ファイル名の注意は EDL を書くときだけ
  - 「動画のファイル名に日本語などが含まれています…」の注意(EDL がファイル名で元動画と結び付くための案内)は、EDL を書くときだけ出す
    (build_pack の結果の warnings)。試算(plan_cut の warnings・API の plan)には出さない
    (Text+ パックで EDL を書かないのに毎回出て、注意に従って名前を変えると文字起こしと動画の結び付きが切れたため)

■ パックの音量(output.loudness・output.volume)
  - API の output.loudness(LUFS: -11 / -14 / -16 / -18。省略・0 = そろえない): カットで残す区間だけ測って、同梱の動画は音声だけ作り直す
    (映像はそのまま)。結果の loudness = {target, measured, gainDb}。測り方・上げる量の決まりはスタジオの書き出しと同じ(ytt_core/loudness.py)
  - API の output.volume(%。1〜200。元 = 100): loudness が無いときだけ、測らずにその量をかける。結果の loudness = {volume, gainDb}

■ 話者ごとの字幕の色
  - 文字起こし(transcript/v1)の話者の名前がメンバーと1人に合えば、その話者の Text+ 字幕だけ文字をその人の色にします
    (合わない話者は配信者の色、空なら黒のまま)。API の output.speakerColors(既定 true。false で使わない)。結果の speakerColors に「話者 → 色」
  - 名前 → 色の規則は ytt_core/colors.py の speaker_colors(配信者の色と同じ照らし合わせ)。Lua は字幕ごとに cap.fill を Text+ の塗りの色に入れる

■ パックの置き方・Text+ の重ね順・配信者の色・作業用フォルダ
  - 動画はパックのフォルダの直下に入れる(1つだけなので分けない = ユーザー)。登録用の ps1・Lua の計画の動画の場所も直下。
    media\<動画> が残っているフォルダで作り直すと「前に作った … が残っています」で知らせる(消さない)
  - 画面・API のパックに手順書(友人へ.txt)を入れない(ユーザー: 要らない)。pack_paths / build_pack の readme_file。
    中身は結果の readme で返し、「編集」の「Resolve での手順を見る」はパックの Lua から作り直す(resolve_textplus.readme_from_script)
  - Text+ の重ね順(優先順位)は、名前で入らないことがある(実機のマーカー: 反映できなかった: Priority1, Priority2, Priority5。太い黒ふちが白ふちの上に描かれる)。
    スクリプトは、名前で入らなければ Resolve の入力の一覧から表示名「Priority」と要素の番号で探し、次に候補の名前(PriorityBack1 など。Text+ の部品の中の文字列)を試す。
    入った名前はメモに「入力の名前を読み替え: …」と出す。それでも入らなければ黄色にし、入力の一覧をパックのフォルダの textplus-inputs.txt に書く
  - 配信者の名前で字幕の色(output.streamer。名前を入れたときだけ): Text+ の文字(塗り)をその人のメンバーカラーにする(白いふち・外側の黒いふちは同じ)。
    名前 → 色は ytt_core/colors.py(ホロカラーの friend-apps/holo-colors/members.json とマイカラーを読むだけ)。見つからない・1人に決まらなければ 400 bad_streamer。
    パックの記録に textColor・streamer。見た目の名前(結果の記録・手順)は「けいふぉんと・〇〇の色の文字(#RRGGBB)・白いふち・黒いふち」
  - 途中のファイルの「作業用」フォルダ(ytt_core と同じ名前 cut2resolve_core.WORK_DIR): 余白つき素材の .edit.json・動画と同じ名前の字幕/文字起こしの候補は
    作業用\ → 動画の隣の順に探す。文字起こしの JSON が 作業用 の中なら、動画は1つ上から探す

■ Text+ 字幕の見た目・2 段・パックの最小限(資料の git:before-1028-cleanup:docs/design/edit-tool-design.md の 12)
  - Text+ 字幕の見た目はユーザーの指定(①): フォント「けいふぉんと」Regular・黒い文字・白いふち(太さ 0.12・少しずらす)・外側の黒いふち(0.18)・大きさ 0.14・
    アンカー 下/中央。スクリプトが値を入れ、最初の字幕で読み直して、入らなかった項目は結果の記録に出す(resolve_textplus.TEXT_STYLE・style_inputs)。
    けいふぉんと はパックに入れない(友人が各自で入れる)。無ければ Windows の日本語フォントを自動で選び、結果の記録を要確認にする
  - Text+ 字幕を2段にする(②): 1段の文字数(縦 8・横 14 前後。output.textplusWrap で変える・0 = 改行しない)で、句読点・助詞のあと・漢字やカタカナの始まりで改行する
    (resolve_textplus.wrap_caption。Text+ は自動で折り返さないため)。SRT・EDL の字幕は改行しない
  - 文字起こしの行から作るカット(preset transcript-rows・keepSource transcript)は、区間の端を声の止まる所まで広げる(pack.ROW_EDGE。
    spec.rowEdge。上の「API」)。keeps・時刻リスト・スタジオの区間には使わない
  - 「フォルダを開く」を許すのは、パックを作った記録のあるフォルダか、cut-plan.json のあるフォルダ(ytt_core/txindex.is_pack_dir)

■ API の keeps と要約
  - API の spec に keeps があります(「編集」のカットのとおりにパックを作る)。「編集」の 3 パック のタブ・入口の「まとめて実行」(カットを決めてある文書)がこれで作ります
  - 作ったパックのフォルダ(cut-plan.json のあるフォルダ)を「フォルダを開く」で開けます(入口を起動し直しても)
  - 試算・パックの要約に keepsSec(残す区間の秒)があり、区間の短さの注意(warn_short)を出します

■ 警告の区別
  - サーバー側の警告(plan/build の warnings)に、対処が要る(warn)かただの案内(info)かの区別 warningLevels がある(warnings 自体は文字列の配列)
  - 「① 無音で自動」で削れる区間が無い(またはごくわずか)ときは「切れる所が見つかりませんでした」の注意を出す(pack.py の warnings)

■ preset "transcript-rows"
  - API の spec に preset "transcript-rows" があります。文字起こしの行だけを残す規則(pack.TRANSCRIPT_ROWS。文字起こしツールの Resolve パッケージと同じ)で
    区間を決める(他の指定は使わない)。入口の「まとめて実行」がこれで Text+ パックを作る。同じ名前のパックがあるときは作らない(上書きしない)

■ 重い処理の同時実行の上限
  - パックの作成は、他のツールの重い処理(スタジオの解析・書き出し、文字起こし)と合わせて同時に 2 つまでです(入口の中で動くとき。
    ytt_core/jobs.py)。順番待ちの間は「他のツールの処理が終わるのを待っています」と出て、中止もできる。上限は環境変数 YTT_MAX_HEAVY_JOBS(1〜8)
  - 入口の「案件」の画面が、切り抜きの隣の <名前>_pack フォルダを見て「パックを作ったか」を表示する(読むだけ)

■ 文字起こしツールの Resolve パッケージとの一本化
  - パックを作るのは pack.py だけ(文字起こしツールの「Resolveパッケージ(zip)」は 10-24 に無くした)。
    文字起こしの行を残すときの規則は pack.TRANSCRIPT_ROWS(行の時間だけ・短い行も残す・1フレームの隙間はつなぐ)。
    同じ入力から同じ中身になることは tests/dev/test_resolve_pack_contract.py が確かめる。詳しくは 資料の git:before-1028-cleanup:docs/design/resolve-pack-unification.md
  - 切り抜きスタジオの前後の余白つき素材(.edit.json)を、動画を入れるパックで使う(上の「3. 書き出し」)
  - 時刻をフレームに直すときの丸めは四捨五入(0.5 は大きい方へ)。Python の round(偶数への丸め)だと、30fps の 0.15 秒(4.5 フレーム)が 4、0.25 秒(7.5 フレーム)が 8 と、
    ちょうど半フレームの時刻が上下ばらばらに丸まって 1 フレームずれることがあるため。文字起こしツールと同じ規則

■ 入口への取り込み
  - 入口(start.bat)の中の /cut2resolve/ で動きます(統合計画の段階3-2。app/mount.py)
  - 画面の部品は相対パスで読み、API・動画の URL は app.js の BASE(画面の場所)を前に付ける
  - 入口の中で動くときは、書き込み系の操作に合言葉(X-YTT-Token。入口が画面に入れる)が要る。CSP は script-src 'self'
  - 入口の中で動いている間に start.bat を押すと、2つ目は立てずに入口の中の画面を開く
  - 入口の「すべて終了」では、動いている書き出しを取り消してから終わる

■ Text+ スクリプトの動き
  - Text+ スクリプトはプロジェクトを作らず、設定も変えない(スクリプトが API で作ったプロジェクトで編集ページの音が割れたため)。
    開いているプロジェクトの fps・解像度が「置き先」と違えば、何もせずに止まる
  - 動画とタイムラインの fps が違っても字幕の位置が合う(60fps の動画を 30fps のタイムラインに置く)。字幕は実際に置かれたクリップの位置から数える
  - 結果を画面に出す: タイムラインに印は置かない(10-23。結果はパックのフォルダの cut2resolve-result.txt と print)、止まる失敗は「C2R_エラー_理由」のタイムライン(スクリプトの出力が見えない環境があるため)
  - 置き先の fps・解像度を選べる(画面・コマンド)。Text+の使い方.txt にプロジェクトの作り方(縦のときは「最短辺をマッチ: 他をクロップ」)を記載
