# -*- coding: utf-8 -*-
"""旧い名前 ed_jobs.名前 の転送だけの殻(役割で組み直す RS2。2026-10-10。**RS5 で消す**)。

中身は human/proof/doc_jobs(文字起こしのジョブの本体・文書づくり・受付。RS2-8b に ここから移した)・human/proof/rerun(再認識の本体と反映。RS2-8c)と
pipeline/transcribe(認識・後処理・記録・ワーカー・名簿・エンジン)・ytt/jobs(ジョブの表・待機列・取り消し)。
ed_jobs.名前 の読み・書き・削除(テストの差し替え・unittest.mock の patch.object)を、下の _MOVED の持ち主へ回す(ytt/modfwd.py)。
新しい名前はここに書かない(持ち主の部品に書き、読む側は持ち主を `モジュール.名前` で呼ぶたびに読む)。
この殻が持つ名前は _MOVED・_moved_owner・_add_moved だけ(移した名前を from … import で別名にしない = 差し替えが別名に当たって本体に効かなくなる)。
"""
from ytt import jobs as _heavy, modfwd as _modfwd  # noqa: E402
from pipeline.transcribe import roster as _roster, tx_engines  # noqa: E402
from pipeline.transcribe import postproc, records, worker_client, recognize  # noqa: E402
from pipeline.transcribe import txbase as _txbase  # noqa: E402
from human.proof import doc_jobs, rerun  # noqa: E402

# 移した先のモジュール(移すたびに足す。serve.py の _ED_MODULES にも ed_jobs より前に足す)。前の持ち主が勝つ(名前が重ならないことは test_names が確かめる)
_MOVED = (_heavy,)   # ytt/jobs = ジョブの表・待機列・ワーカー・取り消し(RS2-1b)
_MOVED += (_roster, tx_engines)   # 名簿の prompt_terms・エンジンの engine_of・engine_home・ENGINE_DIR(RS2-4a)・配信ごとの文脈 stream_context・用語の区切り split_terms(RS2-8a)
_MOVED += (postproc,)   # 行の後処理と要確認の印(RS2-4b。END_TRIM・JOIN_GAP・expand_segments の差し替えもここへ届く)
_MOVED += (records,)   # 認識の記録・辞書の版・生出力・単語の時刻(RS2-5。dict_version の差し替えもここへ届く)
_MOVED += (worker_client,)   # 認識ワーカー・モデル・エンジンの確かめ・wav の形(RS2-6。IN_WORKER・WORKER_*・load_model・check_engine の差し替えもここへ届く)
_MOVED += (recognize,)   # 音声の取り出し・認識・範囲の行・全体の再認識の続きから(RS2-7。extract_audio・WHOLE_PART_SEC・RangeRecognizer.main の差し替えもここへ届く)
_MOVED += (_txbase,)   # 話者の印 SPK_FLAGS(RS2-8a)。serve の受付には並べない(ed_state の別名と重なる。S.SPK_FLAGS は ed_state の別名で同じ物。test_names が確かめる)
_MOVED += (doc_jobs,)   # 文字起こしのジョブの本体・文書づくり・受付(RS2-8b。run_job・validate_job・public_job の差し替えもここへ届く)
_MOVED += (rerun,)   # 再認識と疑わしい所の認識し直しの本体・反映・記録(RS2-8c。apply_range・record_rerun・MAX_RERUNS の差し替えもここへ届く)
_moved_owner = _modfwd.install(globals(), _MOVED, "ed_jobs")


def _add_moved(mod):
    """ed_jobs が読まない層の持ち主(④ の疑似 eval/fake/fake_asr の transcribe_fake・_fake_spans)を転送に足す。呼ぶのは app(serve)だけ
    (ed_jobs から eval を import しない = 層の向きを守る。RS2-2)"""
    global _MOVED, _moved_owner
    if mod not in _MOVED:
        _MOVED += (mod,)
        _moved_owner = _modfwd.install(globals(), _MOVED, "ed_jobs")
