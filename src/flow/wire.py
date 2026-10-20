# -*- coding: utf-8 -*-
"""② 管理の層 flow: 文字起こしの配線(ジョブの種類の登録・ジョブの表の設定・本物と疑似の選び方・① の口の登録)。RS6 a-5b(決定 3-29)。登録は 1 つの install にまとまっている。

install は ① と ② だけを読む。③ の関数(doc_jobs.run_job・speakers.run_diarize など)と ⑤ の物(疑似の本体・疑似の認識ワーカー)は引数で受け取る
(flow は ③⑤ を import できない)。引数を省いた種類は登録しない・省いた口は何もしない既定のまま = ③ なしでも呼べる(あとで CLI が使う)。
二度呼んでも壊れない(登録は上書き)。ジョブの種類ごとの順序・同時に入れない組・やり直せるかはこの表が正(入口の検査 validate_* の tid_busy と
登録の add_job の両方が ジョブの表 flow/jobs.EXCLUSIVE を使う)。

差し込みの口はここ(① ← ② の 3 つ)と編集の serve.py の install の直後(③ ← ④⑤ の 2 つ)だけ。一覧は serve.py のその所(OPT-H1)。
③ が登録の口を持つ物(speakers.set_context_namer + check_context_namer)は ② から呼べない(② は ③ を読めない)ので serve が呼ぶ。
本体は呼ぶ側が lambda で渡す(呼ぶたびに読む = S.run_job = … のテストの差し替えが効く)。
"""
import os

from ytt import workdata as _workdata
from . import jobs as _jobs, tx as _tx
from pipeline.transcribe import backend as _backend, models as _models, records as _records, worker_client as _worker_client
from ytt import layout as _layout
from pipeline.transcribe import roster as _roster

ROSTER_FILE = "hololive-roster.json"   # 名簿のファイルの名前(置き場所は編集のフォルダ。持ち主は ① roster.ROSTER)

# 同じ文字起こしに同時に入れない組み合わせ(exclusive)。入口の検査と登録で見る組は同じ。
# 表は対称(a が b を断るなら b も a を断る)= 再認識・疑わしい所も声を覚えるの最中は断る(声を覚える途中で行の時刻が変わると、覚える区間がずれる)。
# ほかの種類(alt・thumb)は同じ種類どうしだけ(thumb は文書を読むだけ = ほかと同時でよい)。test_voices.TestExclusive が対称を確かめる。
# 優先度は数値が小さいほど先(話者判別 0 = 待っている文字起こしを追い越す・alt 2 = 普通の文字起こしより後。D1-b)。
# retry = [やり直す] で同じ指定のまま入れ直せる(文書を書き換える処理は、文書の画面のボタンから始め直す)
DOC_LOCK = ("diarize", "retranscribe", "voice-learn")
JOB_KINDS = {
    "transcribe": dict(retry=True),
    "diarize": dict(priority=0, exclusive=DOC_LOCK, has_tid=True),
    "voice-learn": dict(exclusive=DOC_LOCK, has_tid=True),
    "retranscribe": dict(exclusive=DOC_LOCK, has_tid=True),
    "normalize": dict(has_tid=True),   # 動画を選び直したあとの 30fps の作り直し(Q1)
    "alt": dict(priority=2, exclusive=("alt",), has_tid=True),   # 2つ目のエンジンで聞いて <id>.alt.json に(文書は書き換えない。D1-b)
    "thumb": dict(exclusive=("thumb",), has_tid=True),   # サムネの案を 1 枚に(文書は読むだけ。P5)
}


def install(*, bodies=None, tool=None, log=None, tmp_dir=None, max_queue=None, mark=None, no_retry=None,
            backend_name=None, fake_backend=None, fake_worker_module=None, dict_learned=None):
    """文字起こしの配線を入れる(読み込みのときに 1 回。何度呼んでもよい)。省いた引数は既定のまま。
    bodies = {種類: run(job)}(JOB_KINDS にある種類だけ登録する。呼ぶたびに読む lambda を渡す)・
    tool・log・tmp_dir()・max_queue()・mark(info)・no_retry() = ジョブの表の設定(flow/jobs.configure。省けば既定)・
    backend_name() と fake_backend = 本物と疑似の選び方(backend_name() が "fake" のとき fake_backend。呼ぶたびに決める。fake_backend を省けば本物のまま)・
    fake_worker_module = 疑似の認識ワーカーの部品の名前(worker-fake のときワーカーに読ませる)・
    dict_learned() = 辞書の版の材料の学習の記録を並べた文字(③ の学習。省けば空)"""
    for kind, run in (bodies or {}).items():
        _jobs.register(kind, run, **JOB_KINDS[kind])   # JOB_KINDS に無い種類は KeyError = 登録の取りこぼしを黙らせない
    conf = {"tool": tool, "log": log, "tmp_dir": tmp_dir, "max_queue": max_queue, "mark": mark, "no_retry": no_retry}
    # ジョブの終わりごとにモデルの使用を記録し、待機列が空いたらモデルを手放す(① の worker_client。呼ぶたびに読む)
    _jobs.configure(after=lambda: _models.models_touched(), idle=lambda: _worker_client.release_idle_models(),
                    **{k: v for k, v in conf.items() if v is not None})
    if fake_backend is not None:
        _backend.set_selector(lambda: fake_backend if (backend_name() if backend_name else "") == "fake" else _backend.REAL)
    # 辞書の版(records.dict_version)の材料: 置換辞書の組は ② flow/tx(設定の辞書と名簿)・学習の記録は ③ から。呼ぶたびに読む(S.dict_pairs の差し替えが効く)
    _records.set_dict_inputs(pairs=lambda spec: _tx.dict_pairs(spec), learned=dict_learned or (lambda: ""))
    # 認識ワーカーの記録のパス(set_data_dir が記録を入れ直す)・worker-fake のときワーカーに読ませる疑似の部品の名前
    if _workdata.DATA_DIR:   # 作業データの場所が決まる前(CLI など)は None のまま = worker_client が DATA_DIR の worker.log を使う
        _worker_client.WORKER_LOG = os.path.join(_workdata.DATA_DIR, "worker.log")
    if fake_worker_module:
        _worker_client.FAKES_MODULE = fake_worker_module


def setup_places(*, root=None, data_dir=None, studio_data=None, roster=None):
    """作業データの置き場所・スタジオの data.json・名簿のファイルを、持ち主(ytt/workdata・① roster.ROSTER)へ明示して入れる(OPT-E2 1c-1)。
    編集の ed_state の読み込み・友人の玄関(friendapp/places)・⑤ の道具(setup_headless)が同じこれを呼ぶ(読み込みの副作用に頼らない)。
    root = 編集のフォルダ(既定 layout の transcribe。ytt/workdata の ROOT と MARKER_DATA・名簿の置き場所)・
    data_dir = 作業データ(省けば set_root の既定 = 環境変数 TRANSCRIBE_DATA_DIR か root)・studio_data = スタジオの data.json(省けば set_root の既定)・
    roster = 名簿の JSON(省けば <root>/hololive-roster.json)。サーバーの記録・環境変数・datadir の登録はしない(それは編集の serve.set_data_dir)"""
    root = root or _layout.tool_dir("transcribe")
    _workdata.set_root(root)
    if data_dir:
        _workdata.set_data_dir(os.path.abspath(data_dir))
    if studio_data:
        _workdata.STUDIO_DATA = studio_data
    _roster.ROSTER = roster or os.path.join(root, ROSTER_FILE)


def setup_headless(*, data_dir, studio_data=None, roster=None, in_process=False, **install_kw):
    """入口(編集の serve)を読まずに、①② の認識・判別の部品をこのプロセスで使う準備(⑤ の道具。OPT-E2 1c-1。設計原則のレビューの指摘 4)。
    要る物を全部ここで明示して渡す: setup_places(置き場所)→ install(install_kw = 本物と疑似の選び方・疑似のワーカーの部品・辞書の版の材料)→
    in_process なら認識・判別をこのプロセスの中で(① worker_client.IN_WORKER。GPU の部品の場所はワーカーの起動と同じ = models.setup_cuda_paths)。
    環境変数は書き換えない(認識ワーカーへは worker_client が作業データの場所を渡す)。何度呼んでもよい"""
    setup_places(data_dir=data_dir, studio_data=studio_data, roster=roster)
    install(**install_kw)
    if in_process:
        _worker_client.IN_WORKER = True
        _models.setup_cuda_paths()
