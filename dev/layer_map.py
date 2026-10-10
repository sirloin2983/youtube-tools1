"""役割の層と、今のファイルの行き先(役割で組み直す計画 `plan/role-restructure.md` の 7 節を機械で読める形にしたもの。RS0)。

層(import してよい向きの順。小さい番号の層は大きい番号の層を import しない。app は全部を使ってよい):
    ytt(基盤)← pipeline(① 自動の流れ)← human(② 人の操作)← manage(③ データの管理)← eval(④ テストと検証)/ app(入口と画面)
`dev/tests/test_layering.py` がこの表を読み、src/ の .py の import を解いて向きを検査する。
違反は KNOWN に一覧で許す(減らすだけ。新しい違反はテストが落とす)。RS1 以降でファイルを移したら、この表の行き先が実際のフォルダになる。

表の値: (層, 行き先のサブパッケージ, 備考)。"split" が付く物は分割が要るファイル(主の層を書く。関数ごとの行き先は
`docs/design/role-restructure-map-2026-10-09.md`)。
"""
LAYERS = ["ytt", "pipeline", "human", "manage", "eval", "app"]
RANK = {name: i for i, name in enumerate(LAYERS)}

# 今のパス(リポジトリ直下から。区切りは /)→ (層, 行き先, 備考)
FILES = {
    # ---- ytt_core → ytt(基盤)は RS1-1 で移した(DIRS で読む)。残るのは旧い名前の転送だけ(FORWARDERS)
    "src/ytt_core/__init__.py": ("ytt", "ytt", "転送(RS5 で消す)"),
    # ---- recorder → pipeline/ingest は RS1-3 で移した(DIRS で読む)。残るのは旧い場所の起動用の転送だけ
    "src/recorder/recorder.py": ("pipeline", "pipeline/ingest", "転送(RS5 で消す)"),
    # ---- cut2resolve → pipeline/pack は RS1-2 で移した(pack・resolve_textplus・cut2resolve_core・cut2resolve(CLI)・srt2resolve・auto_cut。DIRS で読む)
    "src/cut2resolve/cut2resolve.py": ("app", "app", "転送(RS5 で消す)。cut2resolve.bat 用に pipeline/pack/cut2resolve.py を動かすだけ"),
    "src/cut2resolve/serve.py": ("app", "app", "API の配線"),
    # ---- studio
    "src/studio/analyze.py": ("pipeline", "pipeline/analyze", "split: feedback.jsonl の書き手は human/review"),
    "src/studio/batch.py": ("pipeline", "pipeline/run", "解析の順番待ち"),
    "src/studio/store.py": ("human", "human/review", "split: 候補のデータ(①)は pipeline/analyze、手動マーク・採用・コラボ(②)は human/review"),
    "src/studio/rank.py": ("human", "human/find", "YouTube Data API の検索と事務所の登録"),
    "src/studio/common.py": ("app", "app", "転送(RS5 で消す)。RS3-4 に中身を ytt(procs・studio_env・mediainfo・apikey・textutil・errors)と pipeline/ingest/sources へ。残るのは読み込みと serve の起動の小物(環境チェック)"),
    "src/studio/serve.py": ("app", "app", "API の配線"),
    "src/studio/handoff.py": ("manage", "manage/cases", "受け渡し"),
    "src/studio/txlink.py": ("manage", "manage/cases", "文字起こしとの紐づけ(読むだけ)"),
    # ---- editor
    "src/editor/ed_jobs.py": ("human", "human/proof", "転送(RS5 で消す)。中身は human/proof/doc_jobs・rerun と pipeline/transcribe"),
    "src/editor/tx_worker.py": ("pipeline", "pipeline/transcribe", "転送(RS5 で消す)。本体は RS2-9 で pipeline/transcribe/worker.py へ(疑似 install_fakes は eval/fake/fake_worker)。古い入口が旧い場所で起動するための runpy だけ"),
    "src/editor/ed_retime.py": ("human", "human/proof", "行の時刻の候補の API の包み(RS2-9 で計算を pipeline/transcribe/retime.py へ切り出した。RS3 で human/proof へ)"),
    "src/editor/ed_speakers.py": ("human", "human/proof", "転送(RS5 で消す)。中身は pipeline/transcribe/diarize(判別の計算)と human/proof/speakers(文書の側・声の登録)"),
    "src/editor/ed_store.py": ("human", "human/proof", "転送(RS5 で消す)。中身は human/proof/store(文書 = 上書きの置き場)と manage/cases/doclist(一覧とパックの有無。serve が _add_moved で足す)"),
    "src/editor/ed_alt.py": ("human", "human/proof", "2 つ目のエンジンとの食い違い = 校正の補助"),
    "src/editor/ed_ytcap.py": ("human", "human/proof", "YouTube の字幕 = 校正の補助"),
    "src/editor/ed_learn.py": ("human", "human/proof", "転送(RS5 で消す)。中身は pipeline/transcribe/replace(置換辞書)・human/proof/learn(学習と提案)・eval/drill/metrics(精度と基準。serve が _add_moved で足す)"),
    "src/editor/ed_relink.py": ("manage", "manage/cases", "split: 紐づけは manage/cases、評価用フォルダは eval/drill"),
    "src/editor/ed_misc.py": ("manage", "manage/cases", "split: A/B は eval/drill、clip-marker 連携・進行度・受け渡しは manage/cases・app"),
    "src/editor/ed_drill.py": ("eval", "eval/drill", ""),
    "src/editor/ed_evalbatch.py": ("eval", "eval/drill", ""),
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
    "src/home/restart.py": ("manage", "manage/ops", ""),
    "src/home/autorun.py": ("app", "app", "計画 7 節は pipeline/run だったが app に残す(RS3-0B・仮決め #4。AutoRunner は Runner の hook を案件・設定・友人の届けで埋める合成の役。① の経路は RS1-7 で pipeline/run.py へ済み。友人の届け約 275 行だけ human/friend の mixin へ出す = RS3-3)"),
    "src/home/live.py": ("app", "app", "計画 7 節は pipeline/run だったが app に残す(RS3-0B・仮決め #4。Live は録画元・中継・友人・片付け・見回り _tick を束ねる玄関 = 合成の役。葉の live_* だけ層へ移す = RS3-1)"),
    # ---- ライブの葉は RS3-1 で移した(DIRS で読む): live_export → pipeline/export・live_detect と live_excite_worker → pipeline/analyze・
    #      live_archive と live_align_worker → pipeline/ingest(計画は pipeline/run だが run.py がファイルなので)・live_tx と live_tx_worker → pipeline/transcribe・
    #      live_failures → pipeline(計画は manage/ops。RS3-0B・仮決め #5)・live_report → pipeline(計画は eval/tools。決定 3-25 の c)・live_cleanup → manage/keep。
    #      残るのは子プロセスのワーカーの旧い場所の起動用の転送だけ(起動中の古い入口が旧いパスで子を起こすため)
    "src/home/live_excite_worker.py": ("pipeline", "pipeline/analyze", "転送(RS5 で消す)。本体は RS3-1 で pipeline/analyze/live_excite_worker.py へ。古い入口が旧い場所で起動するための runpy だけ"),
    "src/home/live_align_worker.py": ("pipeline", "pipeline/ingest", "転送(RS5 で消す)。本体は RS3-1 で pipeline/ingest/live_align_worker.py へ。古い入口が旧い場所で起動するための runpy だけ"),
    "src/home/live_tx_worker.py": ("pipeline", "pipeline/transcribe", "転送(RS5 で消す)。本体は RS3-1 で pipeline/transcribe/live_tx_worker.py へ。古い入口が旧い場所で起動するための runpy だけ"),
    "src/home/intake.py": ("human", "human/friend", ""),
    "src/home/deliver.py": ("human", "human/friend", ""),
    "src/home/live_requests.py": ("human", "human/friend", ""),
    "src/home/friend_feedback.py": ("human", "human/friend", ""),
    "src/home/cases.py": ("manage", "manage/cases", ""),
    "src/home/backup.py": ("manage", "manage/keep", ""),
    "src/home/cleanup.py": ("manage", "manage/keep", ""),
    "src/home/health.py": ("manage", "manage/ops", ""),
    "src/home/clientlog.py": ("manage", "manage/ops", ""),
    "src/home/accuracy.py": ("eval", "eval/drill", "精度の自動測定"),
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
DIRS = {"src/ytt": "ytt", "src/pipeline": "pipeline", "src/human": "human", "src/manage": "manage", "src/eval": "eval", "src/app": "app"}

# 旧い名前の転送(移したあとも旧い名前の import を動かすためだけのファイル。RS5 で消す = これが空になったら転送の片付けは済み)。
# 転送のファイル → {旧い名前の中の名前: 実体のパス, "*": 表に無い名前の実体のパスの型}。test_layering は転送を import する側としては
# 検査せず、転送に落ちた import を実体へ付け替えて向きを見る(転送のせいで違反が「直った」と見えないように)
FORWARDERS = {
    "src/ytt_core/__init__.py": {"excite": "src/pipeline/analyze/excite.py", "evaldata": "src/eval/tools/evaldata.py",
                                 "txindex": "src/manage/cases/txindex.py", "*": "src/ytt/{name}.py"},   # RS1-1
}


def layer_of(relpath):
    """リポジトリ直下からのパス(区切り /)→ 層の名前。知らないファイルは None"""
    if relpath in FILES:
        return FILES[relpath][0]
    for d, layer in DIRS.items():
        if relpath.startswith(d + "/"):
            return layer
    return None


def allowed(src_layer, dst_layer):
    """src の層が dst の層を import してよいか"""
    if src_layer == "app":
        return True
    return RANK[dst_layer] <= RANK[src_layer]


# 今ある向きの違反(RS0 の時点。減らすだけ。新しい違反はテストが落とす)。形: (import する側, される側)。
# ファイルを移したときは同じ組のままパスだけ付け替えてよい(件数は増やさない。KNOWN_MAX が上限)
KNOWN_MAX = 7   # RS3-E5b: 受け渡しの JSON と SRT の組み立て build_* を pipeline_io から resolve_export へ移し、resolve_export を pipeline/pack・pipeline_io を manage/cases へ = (resolve_export → pipeline_io)が消えた(8 → 7)・RS3-4: スタジオの common.py を ytt(procs・studio_env・mediainfo・apikey・textutil・errors)と pipeline/ingest/sources に分け、読み手を持ち主へ付け替えた = (rank・store・handoff・txlink・analyze・batch・exporter → studio/common)の 7 組が消えた(15 → 8。common.py は転送の殻)・RS3-E5a: ed_store を human/proof/store(文書)と manage/cases/doclist(一覧とパックの有無・前回のパックの手順)に分け、ed_state の読みを ytt と txbase の持ち主に・評価ドリルの要約は ed_drill.drill_docs が自前で作る = (ed_store → ed_state・ed_drill・txindex)が消えた(18 → 15)・RS3-E5c: ed_learn の残りを pipeline/transcribe/replace・human/proof/learn・eval/drill/metrics に分けて ed_state の読みを ytt に = (ed_learn → ed_state)が消えた(19 → 18。殻 ed_learn は ytt・pipeline・human だけを読む)・編集 0.68.0(段 D): 評価用の音声 ed_evalaudio を消した = (ed_evalaudio → ed_state・serve)が消えた(21 → 19)・RS3-1: 評価用のフォルダの判定(eval_dirs・in_eval_dir・eval_name_guard)を ytt/settings へ、別のドライブへ移す move_file を ytt/fsio へ = (ed_alt・ed_store・ed_ytcap → ed_relink)が消えた(24 → 21)・RS3-1: 編集の設定の読み書きと鍵の検査を ytt/settings へ(evalDirs の検査は ed_relink が register_patch_key で登録)= (ed_learn → ed_relink)が消えた(25 → 24)・RS3-0A のあと: ed_store が使っていない import ed_misc を消した(26 → 25)・RS3-0B: now_ms を ytt/schemas へ出し studio の batch が store を読まない(27 → 26)・RS3-0B: 実行の記録の読み(read_runs_log など)を pipeline/runlog.py へ出し live_failures が autorun を読まない(28 → 27)・RS3-0B: clientlog.append_line を ytt/fsio へ出し live_export が clientlog を読まない(29 → 28)・RS3-0B: live_archive がパックの有無を聞く関数(pack_info=)を Live から受け txindex を読まない(30 → 29)・RS3-0B: accuracy・backup・intake が設定の既定を引数(defaults=)で受け prefs を読まない・friend_feedback が片付ける関数(discard=)を受け cases を読まない = 4 組が消えた(34 → 30)・RS3-0B で層の表の 3 行を直した = live.py・autorun.py を app に・live_failures を pipeline に(仮決め #4・#5)。live → cases・deliver・intake・live_cleanup・live_failures・live_report・live_requests・autorun → cases・clientlog・deliver・friend_feedback・prefs・txindex・live_archive・live_detect・live_export → live_failures の 16 組が消え、live_failures → autorun が 1 組増えた(49 → 34)・RS2-9d で認識ワーカーを pipeline/transcribe/worker.py へ移して serve を読まない形にした = (tx_worker → serve)が消えた(50 → 49。旧い editor/tx_worker.py は runpy の転送だけ)・RS2-9c で ed_retime の計算を pipeline/transcribe/retime.py へ切り出し、包みだけ human にして (ed_retime, ed_state)・(ed_retime, ed_alt)・(ed_retime, ed_store) が消えた(53 → 50)・ed_fill・ed_llm を pipeline/transcribe/fill.py・llm.py へ移し ed_state の読みを txenv・txbase・backend・ytt に = (ed_fill, ed_state)・(ed_llm, ed_state) が消えた(55 → 53)・RS2-9b で ed_speakers を pipeline/transcribe/diarize と human/proof/speakers に分けた = (ed_speakers → ed_learn・ed_store)が human どうしになり、ed_drill は serve が登録する口(set_context_namer)にして消えた(58 → 55)・RS2-9a で ed_speakers → ed_state が消えた(59 → 58。文書の形の小道具は ytt/schemas・置き場所と外の道具は txenv の口から読む)・RS1-2 で pack → auto_cut が消えた(69 → 68)・RS2-1b で ed_jobs → ed_thumb・ed_misc が消えた(68 → 66)・RS2-8a で ed_jobs → ed_state が消えた(66 → 65。valid_model・pio を txenv の口から読む)・RS2-8b で ed_jobs を human/proof/doc_jobs へ = (ed_jobs → ed_alt・ed_learn・ed_store・ed_ytcap)が human どうしになって消えた(65 → 61。ed_evalbatch・ed_relink は doc_jobs へ付け替え)・RS2-8d で doc_jobs → ed_evalbatch・ed_relink を serve が登録する口(set_hooks)にして消した(61 → 59)
KNOWN = {
    ("src/editor/ed_drill.py", "src/editor/ed_state.py"),
    ("src/editor/ed_evalbatch.py", "src/editor/ed_state.py"),
    ("src/editor/ed_alt.py", "src/editor/ed_state.py"),
    ("src/editor/ed_ytcap.py", "src/editor/ed_state.py"),
    ("src/editor/ed_misc.py", "src/editor/ed_state.py"),
    ("src/editor/ed_relink.py", "src/editor/ed_state.py"),
    ("src/pipeline/export/exporter.py", "src/studio/handoff.py"),
}
