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
    "src/studio/common.py": ("app", "app", "split: 外部プログラムの確認は ytt、疑似の判定の 1 行は eval/fake"),
    "src/studio/serve.py": ("app", "app", "API の配線"),
    "src/studio/handoff.py": ("manage", "manage/cases", "受け渡し"),
    "src/studio/txlink.py": ("manage", "manage/cases", "文字起こしとの紐づけ(読むだけ)"),
    # ---- editor
    "src/editor/ed_jobs.py": ("human", "human/proof", "転送(RS5 で消す)。中身は human/proof/doc_jobs・rerun と pipeline/transcribe"),
    "src/editor/tx_worker.py": ("pipeline", "pipeline/transcribe", "転送(RS5 で消す)。本体は RS2-9 で pipeline/transcribe/worker.py へ(疑似 install_fakes は eval/fake/fake_worker)。古い入口が旧い場所で起動するための runpy だけ"),
    "src/editor/ed_retime.py": ("human", "human/proof", "行の時刻の候補の API の包み(RS2-9 で計算を pipeline/transcribe/retime.py へ切り出した。RS3 で human/proof へ)"),
    "src/editor/ed_speakers.py": ("human", "human/proof", "転送(RS5 で消す)。中身は pipeline/transcribe/diarize(判別の計算)と human/proof/speakers(文書の側・声の登録)"),
    "src/editor/ed_store.py": ("human", "human/proof", "文書 = 上書きの置き場"),
    "src/editor/ed_alt.py": ("human", "human/proof", "2 つ目のエンジンとの食い違い = 校正の補助"),
    "src/editor/ed_ytcap.py": ("human", "human/proof", "YouTube の字幕 = 校正の補助"),
    "src/editor/ed_learn.py": ("human", "human/proof", "split: 辞書と学習は human/proof、精度の測定と基準は eval/drill、修正データと保管は eval/tools"),
    "src/editor/ed_relink.py": ("manage", "manage/cases", "split: 紐づけは manage/cases、評価用フォルダは eval/drill"),
    "src/editor/ed_misc.py": ("manage", "manage/cases", "split: A/B は eval/drill、clip-marker 連携・進行度・受け渡しは manage/cases・app"),
    "src/editor/ed_drill.py": ("eval", "eval/drill", ""),
    "src/editor/ed_evalbatch.py": ("eval", "eval/drill", ""),
    "src/editor/ed_evalaudio.py": ("eval", "eval/drill", "消す(読む側が無い)"),
    "src/editor/resolve_export.py": ("pipeline", "pipeline/pack", "pack を呼んで zip にするだけ"),
    "src/editor/pipeline_io.py": ("manage", "manage/cases", "受け渡し(clip の JSON の読み・紐づけ)。形式そのものは ytt/schemas"),
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
    "src/home/autorun.py": ("pipeline", "pipeline/run", "split: ① の経路は RS1-7 で pipeline/run.py へ。残りは友人・あとから解析・キューと記録(RS3)"),
    "src/home/live.py": ("pipeline", "pipeline/run", "ライブの流れ"),
    "src/home/live_detect.py": ("pipeline", "pipeline/analyze", "配信中の検出"),
    "src/home/live_excite_worker.py": ("pipeline", "pipeline/analyze", ""),
    "src/home/live_align_worker.py": ("pipeline", "pipeline/analyze", "時刻合わせ"),
    "src/home/live_export.py": ("pipeline", "pipeline/export", ""),
    "src/home/live_tx.py": ("pipeline", "pipeline/transcribe", "配信中の文字起こし"),
    "src/home/live_tx_worker.py": ("pipeline", "pipeline/transcribe", ""),
    "src/home/live_archive.py": ("pipeline", "pipeline/run", "配信後の全自動"),
    "src/home/intake.py": ("human", "human/friend", ""),
    "src/home/deliver.py": ("human", "human/friend", ""),
    "src/home/live_requests.py": ("human", "human/friend", ""),
    "src/home/friend_feedback.py": ("human", "human/friend", ""),
    "src/home/cases.py": ("manage", "manage/cases", ""),
    "src/home/backup.py": ("manage", "manage/keep", ""),
    "src/home/cleanup.py": ("manage", "manage/keep", ""),
    "src/home/live_cleanup.py": ("manage", "manage/keep", ""),
    "src/home/health.py": ("manage", "manage/ops", ""),
    "src/home/live_failures.py": ("manage", "manage/ops", ""),
    "src/home/clientlog.py": ("manage", "manage/ops", ""),
    "src/home/live_report.py": ("eval", "eval/tools", "配信ごとの記録(読むのは eval_marks だけ)"),
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
KNOWN_MAX = 50   # RS2-9c で ed_retime の計算を pipeline/transcribe/retime.py へ切り出し、包みだけ human にして (ed_retime, ed_state)・(ed_retime, ed_alt)・(ed_retime, ed_store) が消えた(53 → 50)・ed_fill・ed_llm を pipeline/transcribe/fill.py・llm.py へ移し ed_state の読みを txenv・txbase・backend・ytt に = (ed_fill, ed_state)・(ed_llm, ed_state) が消えた(55 → 53)・RS2-9b で ed_speakers を pipeline/transcribe/diarize と human/proof/speakers に分けた = (ed_speakers → ed_learn・ed_store)が human どうしになり、ed_drill は serve が登録する口(set_context_namer)にして消えた(58 → 55)・RS2-9a で ed_speakers → ed_state が消えた(59 → 58。文書の形の小道具は ytt/schemas・置き場所と外の道具は txenv の口から読む)・RS1-2 で pack → auto_cut が消えた(69 → 68)・RS2-1b で ed_jobs → ed_thumb・ed_misc が消えた(68 → 66)・RS2-8a で ed_jobs → ed_state が消えた(66 → 65。valid_model・pio を txenv の口から読む)・RS2-8b で ed_jobs を human/proof/doc_jobs へ = (ed_jobs → ed_alt・ed_learn・ed_store・ed_ytcap)が human どうしになって消えた(65 → 61。ed_evalbatch・ed_relink は doc_jobs へ付け替え)・RS2-8d で doc_jobs → ed_evalbatch・ed_relink を serve が登録する口(set_hooks)にして消した(61 → 59)
KNOWN = {
    ("src/editor/ed_drill.py", "src/editor/ed_state.py"),
    ("src/editor/ed_evalaudio.py", "src/editor/ed_state.py"),
    ("src/editor/ed_evalaudio.py", "src/editor/serve.py"),
    ("src/editor/ed_evalbatch.py", "src/editor/ed_state.py"),
    ("src/home/accuracy.py", "src/home/prefs.py"),
    ("src/editor/ed_alt.py", "src/editor/ed_state.py"),
    ("src/editor/ed_learn.py", "src/editor/ed_state.py"),
    ("src/editor/ed_store.py", "src/editor/ed_state.py"),
    ("src/editor/ed_ytcap.py", "src/editor/ed_state.py"),
    ("src/home/intake.py", "src/home/prefs.py"),
    ("src/studio/rank.py", "src/studio/common.py"),
    ("src/studio/store.py", "src/studio/common.py"),
    ("src/editor/ed_store.py", "src/editor/ed_drill.py"),
    ("src/editor/ed_alt.py", "src/editor/ed_relink.py"),
    ("src/editor/ed_learn.py", "src/editor/ed_relink.py"),
    ("src/editor/ed_store.py", "src/editor/ed_misc.py"),
    ("src/editor/ed_store.py", "src/editor/ed_relink.py"),
    ("src/editor/ed_store.py", "src/manage/cases/txindex.py"),
    ("src/editor/ed_ytcap.py", "src/editor/ed_relink.py"),
    ("src/home/friend_feedback.py", "src/home/cases.py"),
    ("src/editor/ed_misc.py", "src/editor/ed_state.py"),
    ("src/editor/ed_relink.py", "src/editor/ed_state.py"),
    ("src/home/backup.py", "src/home/prefs.py"),
    ("src/studio/handoff.py", "src/studio/common.py"),
    ("src/studio/txlink.py", "src/studio/common.py"),
    ("src/editor/tx_worker.py", "src/editor/serve.py"),
    ("src/home/autorun.py", "src/home/prefs.py"),
    ("src/studio/analyze.py", "src/studio/common.py"),
    ("src/studio/batch.py", "src/studio/common.py"),
    ("src/pipeline/export/exporter.py", "src/studio/common.py"),
    ("src/home/live.py", "src/home/live_report.py"),
    ("src/home/autorun.py", "src/home/deliver.py"),
    ("src/home/autorun.py", "src/home/friend_feedback.py"),
    ("src/home/live.py", "src/home/deliver.py"),
    ("src/home/live.py", "src/home/intake.py"),
    ("src/home/live.py", "src/home/live_requests.py"),
    ("src/studio/batch.py", "src/studio/store.py"),
    ("src/editor/resolve_export.py", "src/editor/pipeline_io.py"),
    ("src/home/autorun.py", "src/home/cases.py"),
    ("src/home/autorun.py", "src/home/clientlog.py"),
    ("src/home/autorun.py", "src/manage/cases/txindex.py"),
    ("src/home/live.py", "src/home/cases.py"),
    ("src/home/live.py", "src/home/live_cleanup.py"),
    ("src/home/live.py", "src/home/live_failures.py"),
    ("src/home/live_archive.py", "src/home/live_failures.py"),
    ("src/home/live_archive.py", "src/manage/cases/txindex.py"),
    ("src/home/live_detect.py", "src/home/live_failures.py"),
    ("src/home/live_export.py", "src/home/clientlog.py"),
    ("src/home/live_export.py", "src/home/live_failures.py"),
    ("src/pipeline/export/exporter.py", "src/studio/handoff.py"),
}
