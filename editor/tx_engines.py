# -*- coding: utf-8 -*-
"""文字起こしの認識エンジンの口(精度改善の計画 段2-1。docs/plan/transcription-overhaul-plan.md)。

認識ワーカー(tx_worker.py)が読み込むモデルは、ここのエンジンの1つとして作る。今は faster-whisper だけ。
whisper.cpp(Vulkan)・Qwen3-ASR は、同じ形のクラスをここに足し、ENGINES に登録する(段2-2・2-3)。

エンジンの形(Engine):
  create(name, device, compute_type) -> エンジン   モデルを読み込む(失敗したら例外。機器の選び直しは ed_jobs._load_model_local が行う)
  transcribe(audio, **kw) -> (行の生成器, 情報)      faster-whisper の WhisperModel.transcribe と同じ形。
      行は属性 start・end・text・words(start・end・word・probability)・avg_logprob・no_speech_prob・compression_ratio、
      情報は language・duration・duration_after_vad。audio は wav のパスか float32 のサンプル(16kHz・モノラル)
  params() -> [受け付ける引数の名前]                  サーバーは、これに無い引数を渡さない(ed_jobs.filter_kwargs)

このファイルは、サーバー側からも名前と版のために読む。**ネイティブの部品(faster_whisper・numpy など)は create の中で読み込む**
(ファイルの先頭で import しない。サーバーのプロセスに入れない決まり = tests/test_worker.py が検査)。
"""
import inspect

DEFAULT = "faster-whisper"


class Engine:
    """エンジンの元。id = 記録(recognition.runs の engine)とワーカーへの要求に使う名前、package = 版を読むパッケージ(dist-info)"""
    id = ""
    package = ""

    def __init__(self, name, device, model):
        self.name, self.device, self.model = name, device, model

    @classmethod
    def create(cls, name, device, compute_type):
        raise NotImplementedError

    def transcribe(self, audio, **kw):
        raise NotImplementedError

    def params(self):
        return []


class FasterWhisper(Engine):
    """faster-whisper(CTranslate2)。CPU は int8、GPU(CUDA)は compute_type。ダウンロード済みなら手元のファイルだけで読む(計画 段0-4)"""
    id = "faster-whisper"
    package = "faster-whisper"

    @classmethod
    def create(cls, name, device, compute_type, log=None):
        from faster_whisper import WhisperModel
        try:
            m = WhisperModel(name, device=device, compute_type=compute_type, local_files_only=True)
        except MemoryError:
            raise
        except Exception as e:   # 手元に無い(初回)・手元だけでは読めない → 今までどおりネットワークから取る
            if log:
                log.info("手元のファイルだけではモデルを読めないので、ネットワークから取ります: %s(%s)", name, str(e)[:120])
            m = WhisperModel(name, device=device, compute_type=compute_type)
        return cls(name, device, m)

    def transcribe(self, audio, **kw):
        return self.model.transcribe(audio, **kw)   # 引数・結果はそのまま(エンジンの口を作る前と1文字も変わらない)

    def params(self):
        try:
            return sorted(inspect.signature(self.model.transcribe).parameters)
        except (TypeError, ValueError):
            return []


ENGINES = {FasterWhisper.id: FasterWhisper}


def get(engine_id):
    """エンジンのクラス。知らない名前は ValueError(要求の名前からクラス・パスを作らない = 一覧にあるものだけ)"""
    cls = ENGINES.get(str(engine_id or DEFAULT))
    if cls is None:
        raise ValueError("知らない認識エンジンです: %s" % str(engine_id)[:40])
    return cls


def valid(engine_id):
    return str(engine_id or DEFAULT) in ENGINES
