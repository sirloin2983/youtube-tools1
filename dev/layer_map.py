"""役割の層と、今のファイルの行き先(役割で組み直す計画 `plan/role-restructure.md` の 7 節を機械で読める形にしたもの。RS0。RS6 a-0 で 5 つの層に)。

層(RS6 の決定 3-29。`docs/design/rs6-survey-2026-10-10/plan_order_v2.md` の 2-3):
    ytt(基盤)/ pipeline(① 道具 = データを加工する)/ flow(② 管理 = ① をいつ・どの順で・どこに置いて・飛ばすか)/
    human(③ 人の操作)/ manage(④ データ)/ eval(⑤ 検証)/ app(入口と画面。全部を使ってよい)
決まり: ③④ は ① を直に読まない(全部 ② を通す)。⑤ は ① を直に読んでよい(本物の作業データへ書くときだけ ②)。
② に変換のコードを書かない(① の別名だけの関数も作らない = test_layering の test_flow_is_not_alias)。
import してよい相手は ALLOWED の表(順位の比較ではない)。
`dev/tests/test_layering.py` がこの表を読み、src/ の .py の import を解いて向きを検査する。
違反は KNOWN に一覧で許す(減らすだけ。新しい違反はテストが落とす)。RS1 以降でファイルを移したら、この表の行き先が実際のフォルダになる。

表の値: (層, 行き先のサブパッケージ, 備考)。"split" が付く物は分割が要るファイル(主の層を書く。関数ごとの行き先は
`docs/design/role-restructure-map-2026-10-09.md`)。
"""
LAYERS = ["ytt", "pipeline", "flow", "human", "manage", "eval", "app"]

# 層 → import してよい相手の層(自分の層はいつも許す)。app は全部
ALLOWED = {
    "ytt": set(),
    "pipeline": {"ytt"},
    "flow": {"ytt", "pipeline"},
    "human": {"ytt", "flow"},              # ① は直に読まない(② を通す)
    "manage": {"ytt", "flow", "human"},    # ① は直に読まない(② を通す)
    "eval": {"ytt", "pipeline", "flow", "human", "manage"},
    "app": set(LAYERS),
}

# 今のパス(リポジトリ直下から。区切りは /)→ (層, 行き先, 備考)
FILES = {
    # ---- ytt_core → ytt(基盤)は RS1-1 で移した(DIRS で読む)。残るのは旧い名前の転送だけ(FORWARDERS)
    # ---- recorder → pipeline/ingest は RS1-3 で移した(DIRS で読む)。残るのは旧い場所の起動用の転送だけ
    # ---- cut2resolve → pipeline/pack は RS1-2 で移した(pack・resolve_textplus・cut2resolve_core・cut2resolve(CLI)・srt2resolve・auto_cut。DIRS で読む)
    "src/cut2resolve/serve.py": ("app", "app", "API の配線"),
    # ---- studio: analyze・batch・store(+ 新しい feedback)・rank(+ seed.json)・txlink は RS3-5 で層へ移した(DIRS で読む)。残るのは serve・startup・handoff = app
    "src/studio/startup.py": ("app", "app", "起動の小物(src を sys.path に足す・環境チェック・古いログの改名)。RS5-B で common.py の殻を消して残りをここへ"),
    "src/studio/serve.py": ("app", "app", "API の配線"),
    "src/studio/handoff.py": ("app", "app", "実行中のポートの共有(.runtime・/api/siblings)だけが残る。RS3-5 で .clip.json の組み立てと書き込みを pipeline/export/manifest.py へ割った"),
    # ---- editor
    # ---- ed_drill・ed_evalbatch は RS4-2 で eval/drill の drill・evalbatch へ移した(殻なし。決定 3-25 #7。DIRS で読む)
    # ---- resolve_export は RS3-E5b で pipeline/pack へ(受け渡しの JSON と SRT の組み立て build_* も一緒)・pipeline_io は manage/cases へ(読み・保存・.runtime)。どちらも DIRS で読む = 旧い場所の転送は無い
    "src/editor/ed_media.py": ("app", "app", "動画の配信"),
    "src/editor/ed_thumb.py": ("app", "app", "サムネの配信"),
    "src/editor/thumb_ideas.py": ("human", "human/cut", "サムネの案(P5)"),
    "src/editor/ed_state.py": ("app", "app", "split: 設定は ytt/settings、backend_name は eval/fake の登録"),
    "src/editor/serve.py": ("app", "app", "名前の受付と API の配線"),
    # ---- home
    "src/home/launch.py": ("app", "app", ""),
    "src/home/mount.py": ("app", "app", ""),
    "src/home/appwindow.py": ("app", "app", ""),
    "src/home/prefs.py": ("app", "app", "設定の既定値と検査(ytt/settings に寄せる)"),
    "src/home/autorun.py": ("app", "app", "計画 7 節は pipeline/run だったが app に残す(RS3-0B・仮決め #4。AutoRunner は Runner の hook を案件・設定で埋める合成の役。① の経路は RS1-7 で pipeline/run.py へ済み。友人の届け約 275 行は RS3-3 で human/friend/delivery.py の Delivery(mixin)へ出して継ぐ)"),
    "src/home/live.py": ("app", "app", "計画 7 節は pipeline/run だったが app に残す(RS3-0B・仮決め #4。Live は録画元・中継・友人・片付け・見回り _tick を束ねる玄関 = 合成の役。葉の live_* だけ層へ移す = RS3-1)"),
    # ---- ライブの葉は RS3-1 で移した(DIRS で読む): live_export → pipeline/export・live_detect と live_excite_worker → pipeline/analyze・
    #      live_archive と live_align_worker → pipeline/ingest(計画は pipeline/run だが run.py がファイルなので)・live_tx と live_tx_worker → pipeline/transcribe・
    #      live_failures → pipeline(計画は manage/ops。RS3-0B・仮決め #5)・live_report → pipeline(計画は eval/tools。決定 3-25 の c)・live_cleanup → manage/keep。
    #      旧い場所の起動用の転送は RS5-G で消した
    # ---- 案件と友人の部品は RS3-3 で移した(DIRS で読む): cases → manage/cases(丸ごと。決定 3-25 の d)・intake・deliver・live_requests・
    #      friend_feedback → human/friend。AutoRunner の友人へ届ける段と組の溜めは human/friend/delivery.py の Delivery(mixin。autorun は app に残る)
    # ---- 精度の自動測定 accuracy と測る道具(dev/eval_*.py 13 本・_evalcommon)は RS4-4 で eval/drill・eval/tools へ移した(DIRS で読む)。旧い dev/eval_*.py の転送は RS5-G で消した(dev/ は test_layering の外)
    # ---- analytics → manage/ops/analytics(別件。中身は変えない)
    "src/analytics/__init__.py": ("manage", "manage/ops/analytics", ""),
    "src/analytics/bridge.py": ("manage", "manage/ops/analytics", ""),
    "src/analytics/calc.py": ("manage", "manage/ops/analytics", ""),
    "src/analytics/data.py": ("manage", "manage/ops/analytics", ""),
    "src/analytics/render.py": ("manage", "manage/ops/analytics", ""),
    "src/analytics/service.py": ("manage", "manage/ops/analytics", ""),
    "src/analytics/timeutil.py": ("manage", "manage/ops/analytics", ""),
}

# 新しいフォルダ(RS1 以降に移した先)。フォルダ名 → 層。ここにある物は FILES に書かなくてよい
DIRS = {"src/ytt": "ytt", "src/pipeline": "pipeline", "src/flow": "flow", "src/human": "human", "src/manage": "manage", "src/eval": "eval", "src/app": "app"}

# 旧い名前の転送(移したあとも旧い名前の import を動かすためだけのファイル。RS5-G で消して空になった = 今は転送は無い。仕組みはテスト用に残す)。
# 転送のファイル → {旧い名前の中の名前: 実体のパス, "*": 表に無い名前の実体のパスの型}。test_layering は転送を import する側としては
# 検査せず、転送に落ちた import を実体へ付け替えて向きを見る(転送のせいで違反が「直った」と見えないように)
FORWARDERS = {}


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
KNOWN_MAX = 25   # RS6 a-5a: パックの口 flow/pack と取り込みの口 flow/ingest を足し、check_live・LIVE_NO_ANALYZE を ytt/yturl へ・prune_cache を ytt/fsio へ下ろした(6 組が消えた。31 → 25)・RS6 a-4: 話者の部品 human/proof/speakers の判別の半分(判別のジョブの段取り・割り当てと判別の記録・声の特徴と照合・覚えた声の置き場所)を ② flow/diar へ = speakers → backend・diarize・fill・recognize・worker_client の 5 組が消えた(36 → 31)・RS6 a-2: 段取りを flow へ移した(run・live_* など。③④ → flow は許される向きなので 42 → 36)・RS6 a-1: 語彙を ytt へ下ろした(txbase → ytt/txbase・sources の URL の形 → ytt/yturl・ResolveExportError → ytt/errors・_ids_ok → ytt/schemas.ids_ok・置換辞書の読み方 → ytt/dictfmt。human → pipeline 43 → 34・manage → pipeline 11 → 8。54 → 42)・RS6 a-0: 層を 5 つにして human・manage → pipeline を許さない表(ALLOWED)にした = 今の ③④ → ① を一覧に入れた(0 → 54。human → pipeline 43・manage → pipeline 11。段 a-1〜a-5 で減らして a-5 で 0)・RS4-2: ed_drill・ed_evalbatch を eval/drill の drill・evalbatch へ殻なしで移し、ed_state の読みを ytt(errors・fsio・jobs・schemas)・txbase・human/proof(doc_jobs・rerun・speakers・store)・pipeline/transcribe(diarize・roster)の持ち主に。作り直しの口と見回りの裏のスレッドは serve が登録・起動する = (ed_drill・ed_evalbatch → ed_state)が消えた(2 → 0。違反なし)・RS3-E7: ed_relink を manage/cases/relink と eval/drill/folders に、ed_misc を manage/cases/handoff_io・human/proof/batch・progress に分け(runtime_path_dir は app の ed_state へ)、ed_state の読みを ytt と txbase の持ち主に = (ed_relink・ed_misc → ed_state)が消えた(4 → 2。殻は manage・human だけを読み、folders は serve が _add_moved で足す)・RS3-5: スタジオの handoff.py を割り、exporter が読む .clip.json の部分を pipeline/export/manifest.py へ = (exporter → handoff)が消えた(5 → 4)・RS3-E6: ed_alt・ed_ytcap・ed_retime を human/proof の alt・ytcap・retime へ移し(殻は転送だけ)、ed_state の読みを ytt・txbase・store に、疑似かどうかは backend.select().name・疑似の行は Backend.alt_rows(本体は eval/fake/fake_asr)に = (ed_alt・ed_ytcap → ed_state)が消えた(7 → 5)・RS4-4: dev/eval_* と accuracy を eval/tools・eval/drill へ移した(件数は変わらず。測る道具は ytt・pipeline・manage・eval だけを読み、editor の serve はパスで読み込むので数えに出ない)・RS3-5: スタジオの handoff.py を割り、exporter が読む .clip.json の部分を pipeline/export/manifest.py へ = (exporter → handoff)が消えた(5 → 4)・RS3-E6: ed_alt・ed_ytcap・ed_retime を human/proof の alt・ytcap・retime へ移し(殻は転送だけ)、ed_state の読みを ytt・txbase・store に、疑似かどうかは backend.select().name・疑似の行は Backend.alt_rows(本体は eval/fake/fake_asr)に = (ed_alt・ed_ytcap → ed_state)が消えた(7 → 5)・RS3-E5b: 受け渡しの JSON と SRT の組み立て build_* を pipeline_io から resolve_export へ移し、resolve_export を pipeline/pack・pipeline_io を manage/cases へ = (resolve_export → pipeline_io)が消えた(8 → 7)・RS3-4: スタジオの common.py を ytt(procs・studio_env・mediainfo・apikey・textutil・errors)と pipeline/ingest/sources に分け、読み手を持ち主へ付け替えた = (rank・store・handoff・txlink・analyze・batch・exporter → studio/common)の 7 組が消えた(15 → 8。common.py は転送の殻)・RS3-E5a: ed_store を human/proof/store(文書)と manage/cases/doclist(一覧とパックの有無・前回のパックの手順)に分け、ed_state の読みを ytt と txbase の持ち主に・評価ドリルの要約は ed_drill.drill_docs が自前で作る = (ed_store → ed_state・ed_drill・txindex)が消えた(18 → 15)・RS3-E5c: ed_learn の残りを pipeline/transcribe/replace・human/proof/learn・eval/drill/metrics に分けて ed_state の読みを ytt に = (ed_learn → ed_state)が消えた(19 → 18。殻 ed_learn は ytt・pipeline・human だけを読む)・編集 0.68.0(段 D): 評価用の音声 ed_evalaudio を消した = (ed_evalaudio → ed_state・serve)が消えた(21 → 19)・RS3-1: 評価用のフォルダの判定(eval_dirs・in_eval_dir・eval_name_guard)を ytt/settings へ、別のドライブへ移す move_file を ytt/fsio へ = (ed_alt・ed_store・ed_ytcap → ed_relink)が消えた(24 → 21)・RS3-1: 編集の設定の読み書きと鍵の検査を ytt/settings へ(evalDirs の検査は ed_relink が register_patch_key で登録)= (ed_learn → ed_relink)が消えた(25 → 24)・RS3-0A のあと: ed_store が使っていない import ed_misc を消した(26 → 25)・RS3-0B: now_ms を ytt/schemas へ出し studio の batch が store を読まない(27 → 26)・RS3-0B: 実行の記録の読み(read_runs_log など)を pipeline/runlog.py へ出し live_failures が autorun を読まない(28 → 27)・RS3-0B: clientlog.append_line を ytt/fsio へ出し live_export が clientlog を読まない(29 → 28)・RS3-0B: live_archive がパックの有無を聞く関数(pack_info=)を Live から受け txindex を読まない(30 → 29)・RS3-0B: accuracy・backup・intake が設定の既定を引数(defaults=)で受け prefs を読まない・friend_feedback が片付ける関数(discard=)を受け cases を読まない = 4 組が消えた(34 → 30)・RS3-0B で層の表の 3 行を直した = live.py・autorun.py を app に・live_failures を pipeline に(仮決め #4・#5)。live → cases・deliver・intake・live_cleanup・live_failures・live_report・live_requests・autorun → cases・clientlog・deliver・friend_feedback・prefs・txindex・live_archive・live_detect・live_export → live_failures の 16 組が消え、live_failures → autorun が 1 組増えた(49 → 34)・RS2-9d で認識ワーカーを pipeline/transcribe/worker.py へ移して serve を読まない形にした = (tx_worker → serve)が消えた(50 → 49。旧い editor/tx_worker.py は runpy の転送だけ)・RS2-9c で ed_retime の計算を pipeline/transcribe/retime.py へ切り出し、包みだけ human にして (ed_retime, ed_state)・(ed_retime, ed_alt)・(ed_retime, ed_store) が消えた(53 → 50)・ed_fill・ed_llm を pipeline/transcribe/fill.py・llm.py へ移し ed_state の読みを txenv・txbase・backend・ytt に = (ed_fill, ed_state)・(ed_llm, ed_state) が消えた(55 → 53)・RS2-9b で ed_speakers を pipeline/transcribe/diarize と human/proof/speakers に分けた = (ed_speakers → ed_learn・ed_store)が human どうしになり、ed_drill は serve が登録する口(set_context_namer)にして消えた(58 → 55)・RS2-9a で ed_speakers → ed_state が消えた(59 → 58。文書の形の小道具は ytt/schemas・置き場所と外の道具は txenv の口から読む)・RS1-2 で pack → auto_cut が消えた(69 → 68)・RS2-1b で ed_jobs → ed_thumb・ed_misc が消えた(68 → 66)・RS2-8a で ed_jobs → ed_state が消えた(66 → 65。valid_model・pio を txenv の口から読む)・RS2-8b で ed_jobs を human/proof/doc_jobs へ = (ed_jobs → ed_alt・ed_learn・ed_store・ed_ytcap)が human どうしになって消えた(65 → 61。ed_evalbatch・ed_relink は doc_jobs へ付け替え)・RS2-8d で doc_jobs → ed_evalbatch・ed_relink を serve が登録する口(set_hooks)にして消した(61 → 59)
KNOWN = {
    # human -> pipeline: 28(RS6 a-0 で 43。③④ は ① を直に読まない。② の flow を通す形へ RS6 a-1〜a-5 で付け替える)
    ("src/human/proof/alt.py", "src/pipeline/transcribe/backend.py"),
    ("src/human/proof/alt.py", "src/pipeline/transcribe/postproc.py"),
    ("src/human/proof/alt.py", "src/pipeline/transcribe/recognize.py"),
    ("src/human/proof/alt.py", "src/pipeline/transcribe/records.py"),
    ("src/human/proof/alt.py", "src/pipeline/transcribe/tx_engines.py"),
    ("src/human/proof/alt.py", "src/pipeline/transcribe/worker_client.py"),
    ("src/human/proof/doc_jobs.py", "src/pipeline/transcribe/fill.py"),
    ("src/human/proof/doc_jobs.py", "src/pipeline/transcribe/llm.py"),
    ("src/human/proof/doc_jobs.py", "src/pipeline/transcribe/postproc.py"),
    ("src/human/proof/doc_jobs.py", "src/pipeline/transcribe/recognize.py"),
    ("src/human/proof/doc_jobs.py", "src/pipeline/transcribe/records.py"),
    ("src/human/proof/doc_jobs.py", "src/pipeline/transcribe/replace.py"),
    ("src/human/proof/doc_jobs.py", "src/pipeline/transcribe/roster.py"),
    ("src/human/proof/doc_jobs.py", "src/pipeline/transcribe/worker_client.py"),
    ("src/human/proof/learn.py", "src/pipeline/transcribe/roster.py"),
    ("src/human/proof/rerun.py", "src/pipeline/transcribe/backend.py"),
    ("src/human/proof/rerun.py", "src/pipeline/transcribe/postproc.py"),
    ("src/human/proof/rerun.py", "src/pipeline/transcribe/recognize.py"),
    ("src/human/proof/rerun.py", "src/pipeline/transcribe/records.py"),
    ("src/human/proof/rerun.py", "src/pipeline/transcribe/replace.py"),
    ("src/human/proof/rerun.py", "src/pipeline/transcribe/roster.py"),
    ("src/human/proof/rerun.py", "src/pipeline/transcribe/tx_engines.py"),
    ("src/human/proof/rerun.py", "src/pipeline/transcribe/worker_client.py"),
    ("src/human/proof/retime.py", "src/pipeline/transcribe/records.py"),
    ("src/human/proof/retime.py", "src/pipeline/transcribe/retime.py"),
    # manage -> pipeline: 0(RS6 a-5a で resolve_export の読みを flow/pack に付け替えた)
}
