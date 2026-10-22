"""役割の層と、今のファイルの行き先(役割で組み直す計画 `notes:plan/done/role-restructure.md` の 7 節を機械で読める形にしたもの)。

層(RS6 の決定 3-29。`資料の git:cbe1a64:docs/design/surveys/rs6-survey-2026-10-10/plan_order_v2.md` の 2-3):
    ytt(基盤)/ pipeline(① 道具 = データを加工する)/ flow(② 管理 = ① をいつ・どの順で・どこに置いて・飛ばすか)/
    human(③ 人の操作)/ manage(④ データ)/ eval(⑤ 検証)/ app(入口と画面。全部を使ってよい)
決まり: ③④ は ① を直に読まない(全部 ② を通す)。⑤ は ① を直に読んでよい(本物の作業データへ書くときだけ ②)。
② に変換のコードを書かない(① の別名だけの関数も作らない = test_layering の test_flow_is_not_alias)。
import してよい相手は ALLOWED の表(順位の比較ではない)。
`tests/dev/test_layering.py` がこの表を読み、src/ の .py の import を解いて向きを検査する。
違反は KNOWN に一覧で許す(減らすだけ。新しい違反はテストが落とす)。RS1 以降でファイルを移したら、この表の行き先が実際のフォルダになる。

表の値: (層, 行き先のサブパッケージ, 備考)。"split" が付く物は分割が要るファイル(主の層を書く。関数ごとの行き先は
`資料の git:cbe1a64:docs/design/surveys/role-restructure-map-2026-10-09.md`)。
"""
LAYERS = ["ytt", "pipeline", "flow", "human", "manage", "eval", "app", "friendapp"]

# 層 → import してよい相手の層(自分の層はいつも許す)。app は全部
ALLOWED = {
    "ytt": set(),
    "pipeline": {"ytt"},
    "flow": {"ytt", "pipeline"},
    "human": {"ytt", "flow"},              # ① は直に読まない(② を通す)
    "manage": {"ytt", "flow", "human"},    # ① は直に読まない(② を通す)
    "eval": {"ytt", "pipeline", "flow", "human", "manage"},
    "app": set(LAYERS) - {"friendapp"},
    "friendapp": {"ytt", "pipeline", "flow"},   # 友人の玄関(F2。notes:docs/design/friend-history.md の 7 章)。③④⑤ と入口 app は読まない
}

# 今のパス(リポジトリ直下から。区切りは /)→ (層, 行き先, 備考)
FILES = {
    # ---- ytt(基盤)は DIRS で読む
    "src/ytt/docloc.py": ("ytt", "ytt", "文字起こしの文書の置き場所を引く口(RS8 B2-1a。索引 transcripts/<id>.loc.json が無ければ workdata.TX_DIR。標準ライブラリと ytt だけ)"),
    "src/ytt/ytcookies.py": ("ytt", "ytt", "yt-dlp が書き戻した cookie の写しを元へ戻す・ログインと切れの記録(10-21。値は読まない・ネットも子プロセスも無し。tools.ytdlp_auth_args が呼ぶ)"),
    "src/ytt/autorestart.py": ("ytt", "ytt", "自動の起動し直し・入れ替えを今やるかの判定(時計と fsio だけ。app/server と friendapp/server の両方が使う。10-21 に manage/ops から移した)"),
    "src/friendapp/ytdlp_update.py": ("friendapp", "friendapp", "友人の PC の tools/yt-dlp.exe を 1 日 1 回新しくする(10-21。公式の版を SHA-256 で確かめて取り替え。作る人の PC では動かない)"),
    "src/ytt/casefiles.py": ("ytt", "ytt", "案件の 候補.json・採用.json の読む側(RS8 B3-4a。形・パスの相対 ⇔ 絶対・読み read(cached)・重ね merge・ロック。flow/casebook から下ろした。ytt/studiodata が data.json の行の case から読むため。書く側は flow/casebook)"),
    "src/ytt/gpuinfo.py": ("ytt", "ytt", "この PC の GPU の名前と VRAM(F1 F0-2。nvidia-smi → レジストリ → CIM。窓を出さない子プロセス・結果を覚える。flow/machine の llmModel の既定と ② の状態が読む)"),
    "src/ytt/marks.py": ("ytt", "ytt", "マークの純粋な語彙(RS8 B3-2。検査・整形 build_mark・読み込み load_marks・同じ区間 same/near・手を入れたか touched。human/review/store から下ろした。ファイルにもロックにも触らない)"),
    "src/pipeline/analyze/adopt.py": ("pipeline", "pipeline/analyze", "採用の規則 F-5 の純粋な関数(RS8 B3-2 の G1a。human/review/store の Store.adopt_marks から出した。入力 = マークの一覧・区間・上限 → 出力 = 採る印をつけた一覧)"),
    "src/flow/adopt.py": ("flow", "flow", "② 採用の口(RS8 B3-2 の G1a。③ の Store.adopt_marks が ① pipeline/analyze/adopt を直に読まずに済む動詞。② が足すこと = kind live を通さない・配信の長さ・ApiError 400)"),
    "src/manage/cases/outdirs.py": ("manage", "manage/cases", "書き出し先を変えたあとの案件の繋ぎ直し・「調子」の置き場所の数(RS8 B3-8 の残り。入口の起動のときと、コマンド --relink。ytt・flow/casebook・flow/studiobook・flow/placement を読む)"),
    "src/human/proof/layers.py": ("human", "human/proof", "文書を機械の層 + 人の層から組み立てる純粋な関数(RS8 O2-1。compose・diff・案 A の印・話者の対応表。ファイルを触らない。ytt だけを読む)"),
    "src/human/proof/machpick.py": ("human", "human/proof", "3 択の口(RS8 O2-4。機械の結果が変わった人の行の 前の機械・今の機械・人の直しと、自分の直しのまま / 今の機械にする。層が正のときだけ)"),
    "src/flow/packjobs.py": ("flow", "flow", "パックのジョブの器(OPT2 J3。cut2resolve/serve の Job・AppState のジョブを移した。同時 1 本・履歴 20・糸・SLOTS(build は必ず・plan は heavy() のとき)・Task を作って fn(task)・掲示板の頭 pk。pipeline の cut2resolve_core と ytt を読む)"),
    "src/flow/casebook.py": ("flow", "flow", "案件の候補と採用のファイル(RS8 B3-3。作業用/候補.json = ① の機械の候補・作業用/採用.json = ③ の人の採用。分ける split・重ねる merge・案件の引き方 case_of・読み書きとパスごとのロック。ytt だけを読む。保存の経路に入れるのは B3-4)"),
    "src/flow/export.py": ("flow", "flow", "② 書き出しの器(OPT2 の J2。ExportJobs = ① pipeline/export/exporter.run を 1 本ずつ動かすジョブの表・同時 1 本 409・履歴 20・枠 SLOTS・_out_lock の下で登録・取り消し・掲示板の頭 ex。default() でプロセスに 1 つ。ytt・① export を読む)"),
    "src/flow/studiobook.py": ("flow", "flow", "スタジオなしの配信の台帳と URL の段の動詞(RS8 の「URL も CLI で」。StudioBook = data.json + 案件の 候補.json・採用.json をスタジオの Store と同じ形で・LocalStudio = flow/tools の LocalTools が任せる配信の読み・解析・採用・書き出し。ytt・flow(batch・casebook・adopt・keys・export)・① pipeline/analyze・export を読む。③ は読まない)"),
    # ---- V1 確かめる(V0。notes:docs/design/v1-check-build.md)。⑤ が待ち行列を数えて並べ(読むだけ)、③ が答えを記録して反映する(入口の /api/check/*)
    "src/app/check/lineup.py": ("app", "app/check", "確かめるの待ち行列の並びと数え方(純粋。名前は標準の queue と重ねない。カードの id・種類の並び・n の検査)"),
    "src/eval/check/goals.py": ("eval", "eval/check", "カードの種類 → 入口の条件 GOALS の対応と、答えの数え方(accuracy.goals_of の extra。human/check/answerlog を読む)"),
    "src/app/check/sources.py": ("app", "app/check", "カードの出どころの登録と V0 の 5 つ(value:auto・value:cand・read:fill・voice:diar・time:row。読むだけ。評価用はここ 1 か所で外す。manage/cases を読む)"),
    "src/app/check/deck.py": ("app", "app/check", "GET /api/check/next の組み立てと、答える前にカードを引き直す find(sources + lineup + goals + 答えの記録)"),
    "src/human/check/answerlog.py": ("human", "human/check", "確かめるの答えの記録 app/check/answers.jsonl(答え・確定・戻す)と skip.json の読み書き(ytt だけを読む)"),
    "src/app/check/read_sources.py": ("app", "app/check", "読みのカードの出どころ read:alt(V2b。2 つ目のエンジンの食い違いを 1 行 1 枚に。読むだけ。human/proof の alt_diffs・learn を読む)"),
    "src/human/check/read.py": ("human", "human/check", "読みのカードの反映(V2b。fill・alt・yt の 1 / 2 / 打つ。文書は store.commit(why=check:read)・採否は learn-feedback。行を校正済みにしない・時刻に触れない)"),
    "src/human/check/timerow.py": ("human", "human/check", "時刻のカードの反映(行の start / end を ← → で動かした量だけ変える・動かさなければ記録だけ・Z で戻す。store.commit why='check:time')"),
    "src/human/check/value.py": ("human", "human/check", "価値のカード(value:auto = 届ける・要らない(auto_review の口)/ value:cand = 採用 + 書き出しを頼む・不採用(studio の口))の反映の登録(V2a)"),
    "src/human/check/apply.py":("human", "human/check", "答えを実物へ反映する土台(種類と出どころごとの register・1 枚遅れの保留と flush・Z の undo・skip。④ の操作は入口が hooks で渡す)"),
    "src/human/check/voice.py": ("human", "human/check", "誰の声のカード(V2c)の答えの形・選択肢と予想・文書の行への反映(commit why check:voice)と Z・声の覚え直し(1 人 30 秒で voice-learn。human/proof・flow/diar・flow/jobs を読む)"),
    # ---- pipeline/ingest は DIRS で読む
    "src/pipeline/analyze/fetch.py": ("pipeline", "pipeline/analyze", "解析の材料を取ってくる仕事(音声のダウンロード・チャットの取得と先読み・コメント欄・付加情報)とそのキャッシュの掃除(OPT2。analyze.py から分けた)"),
    "src/pipeline/pack/request.py": ("pipeline", "pipeline/pack", "パックの指定(spec・output)-> pack.Request と build_pack の引数の 1 か所(OPT2。cut2resolve の API と flow/tools の LocalTools が呼ぶ。検査は API の厳しさ)"),
    # ---- pipeline/pack(pack・resolve_textplus・cut2resolve_core・srt2resolve・auto_cut)は DIRS で読む
    "src/cut2resolve/serve.py": ("app", "app", "API の配線"),
    # ---- studio: analyze・batch・store・feedback・rank・txlink は層のフォルダ(DIRS で読む)。serve・startup = app
    "src/studio/startup.py": ("app", "app", "起動の小物(src を sys.path に足す・環境チェック・古いログの改名)。RS5-B で common.py の殻を消して残りをここへ"),
    "src/studio/serve.py": ("app", "app", "API の配線"),
    # ---- editor
    # ---- ed_drill・ed_evalbatch は eval/drill の drill・evalbatch(殻なし。決定 3-25 #7。DIRS で読む)
    # ---- resolve_export は pipeline/pack(受け渡しの JSON と SRT の組み立て build_* も一緒)・handoff_io は manage/cases(.clip.json の動画・動画の隣への保存)。どちらも DIRS で読む
    "src/editor/ed_media.py": ("app", "app", "動画の配信"),
    "src/editor/ed_thumb.py": ("app", "app", "サムネの配信"),
    "src/editor/thumb_ideas.py": ("human", "human/cut", "サムネの案(P5)"),
    "src/editor/ed_state.py": ("app", "app", "split: 設定は ytt/settings、backend_name は eval/fake の登録"),
    "src/editor/serve.py": ("app", "app", "API の配線"),
    # ---- 入口の部品(src/app)
    "src/app/mount.py": ("app", "app", ""),
    "src/app/prefs.py": ("app", "app", "設定の既定値と検査(ytt/settings に寄せる)"),
    "src/app/autorun.py": ("app", "app", "計画 7 節は pipeline/run だったが app に残す(RS3-0B・仮決め #4。AutoRunner は受付と、Runner・Queue の hook を案件・設定で埋める合成の役(待ち行列と糸は RS7-1 S5 で flow/runqueue.py へ)。① の経路は RS1-7 で pipeline/run.py へ済み。友人の届け約 275 行は RS3-3 で Delivery(mixin)へ出して継ぐ。ds1 で ② flow/delivery.py へ = ③ の受付・送り返しは _friend_batch・_returned_request で渡す)"),
    "src/app/live.py": ("app", "app", "計画 7 節は pipeline/run だったが app に残す(RS3-0B・仮決め #4。Live は録画元・中継・友人・片付け・見回り _tick を束ねる玄関 = 合成の役。葉の live_* だけ層へ移す = RS3-1)"),
    # ---- ライブの葉は層のフォルダ(DIRS で読む): live_export → pipeline/export・live_detect と live_excite_worker → pipeline/analyze・
    #      live_archive と live_align_worker → pipeline/ingest(計画は pipeline/run だが run.py がファイルなので)・live_tx と live_tx_worker → pipeline/transcribe・
    #      live_failures → pipeline(計画は manage/ops。RS3-0B・仮決め #5)・live_report → pipeline(計画は eval/tools。決定 3-25 の c)・live_cleanup → manage/keep。
    # ---- 案件と友人の部品は層のフォルダ(DIRS で読む): cases → manage/cases(丸ごと。決定 3-25 の d)・intake・deliver・live_requests・
    #      friend_feedback → human/friend。AutoRunner の友人へ届ける段と組の溜めは flow/delivery.py の Delivery(mixin。autorun は app に残る。ds1 で ② へ)
    # ---- 精度の自動測定 accuracy と測る道具(dev/eval_*.py 13 本・_evalcommon)は eval/drill・eval/tools にある(DIRS で読む)
    # ---- flow(② 管理)は DIRS で読む。RS7-1 で足した物も明示しておく
    "src/flow/machine.py": ("flow", "flow", "この PC の設定(machine.json・環境変数・既定。束に重ねる overlay。RS7-1 S1)"),
    "src/flow/learning.py": ("flow", "flow", "学習データを読む側(F1。学習の束 learning.json があれば計算済みの規則 learned-rules.json だけで文書も ③ も読まない = 友人の PC。"
                             "束の置き場所を使う側へ入れる apply_places・束の版を束に入れる stamp。ytt・pipeline を読む。③ は文書があるときだけ遅延 import)"),
    "src/manage/keep/learnpack.py": ("manage", "manage/keep", "学習の束を作る側(F1。置換辞書・用語・学習した置換・計算済みの規則・名簿・色・名簿にある人の声 -> 同期フォルダの 学習/<版>/ + learning.json + latest.json。直近 3 版を残す。③ の learn.export_rules を読む)"),
    "src/flow/envelope.py": ("flow", "flow", "依頼の封筒(RS7-1 S3。何を入れたか・どの依頼か・届け方 = 処理の中身でない物。中身は束 flow/spec.py)"),
    "src/flow/runqueue.py": ("flow", "flow", "② の待ち行列と実行の糸(RS7-1 S5。submit(封筒, 束)・status・cancel・snapshot・history・estimate・待ちの記録と終わった実行の記録。"
                          "Runner を継ぎ、入口の AutoRunner が受付と hook だけを足して継ぐ)"),
    "src/flow/board.py": ("flow", "flow", "② のジョブの掲示板(RS8 の ② の口 S1。Job の形・id の頭・kind / state の語彙・upsert・引く形の register・rev・直近の履歴・案件ごとの絞り込み・"
                          "cancel / retry の振り分け・親子の印。入口の GET /api/flow/status の jobs・cases・rev。notes:docs/spec/pipeline.md 2.9)"),
    "src/flow/livehost.py": ("flow", "flow", "ライブの親の口(RS7-2 G0。typing.Protocol だけ。Detector・LiveTx・Reporter・Exporter・Adopter が親に求める物 = LiveHost 1 つ。flow/livesession の LiveSession が満たす)"),
    "src/flow/live_adopt.py": ("flow", "flow", "ライブの採用 = マーク + 書き出し(M1。RS7-2 G1b。Live.adopt の本体。マークの置き場 StudioMarks(スタジオ)・LocalMarks(マークの正本。スタジオなし))"),
    "src/flow/livesession.py": ("flow", "flow", "ライブ係(RS7-2 G2b。Live から app でない部分 = 録画元のクライアント・録画を始める・受付 submit(封筒 kind live + 束 → live/bundles.json)・"
                                "見回り・子プロセス・調子・採用の口。入口の app/live.py の Live はこれを継ぐ app の殻)"),
    # ---- analytics → manage/ops/analytics(別件。中身は変えない)
    "src/manage/ops/analytics/__init__.py": ("manage", "manage/ops/analytics", ""),
    "src/manage/ops/analytics/bridge.py": ("manage", "manage/ops/analytics", ""),
    "src/manage/ops/analytics/calc.py": ("manage", "manage/ops/analytics", ""),
    "src/manage/ops/analytics/data.py": ("manage", "manage/ops/analytics", ""),
    "src/manage/ops/analytics/render.py": ("manage", "manage/ops/analytics", ""),
    "src/manage/ops/analytics/service.py": ("manage", "manage/ops/analytics", ""),
    "src/manage/ops/analytics/timeutil.py": ("manage", "manage/ops/analytics", ""),
}

# 層ごとのフォルダ。フォルダ名 → 層。ここにある物は FILES に書かなくてよい
DIRS = {"src/ytt": "ytt", "src/pipeline": "pipeline", "src/flow": "flow", "src/human": "human", "src/manage": "manage", "src/eval": "eval", "src/app": "app", "src/friendapp": "friendapp"}

def layer_of(relpath):
    """リポジトリ直下からのパス(区切り /)→ 層の名前。知らないファイルは None"""
    if relpath in FILES:
        return FILES[relpath][0]
    for d, layer in DIRS.items():
        if relpath.startswith(d + "/"):
            return layer
    return None


def allowed(src_layer, dst_layer):
    """src の層が dst の層を import してよいか(ALLOWED の表)"""
    return src_layer == dst_layer or dst_layer in ALLOWED[src_layer]


# 今ある向きの違反(RS0 の時点。減らすだけ。新しい違反はテストが落とす)。形: (import する側, される側)。
# ファイルを移したときは同じ組のままパスだけ付け替えてよい(件数は増やさない。KNOWN_MAX が上限)
KNOWN_MAX = 0   # 違反なし(新しい違反はテストが落とす)
# 違反なし(RS6 a-5b で 0。③④ は ① を直に読まない。② の flow と ytt を通す)
KNOWN = set()
