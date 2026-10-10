"""サーバー側の認識の本物と疑似の差し込み口(役割で組み直す RS2-2。2026-10-10)。

認識の部品(今は移す前の ed_jobs)は「疑似なら …」の if を持たず、違う所(文字起こしの行・記録のエンジン名・疑わしい所の認識し直し・
範囲と全体の再認識・選んだ行の再認識・全体の再認識の続きの目印。RS2-9 から話者判別の区間と声の特徴も)を `select()` が返す Backend のメソッドで呼ぶ。
本物の処理は呼ぶ側が real に渡す(本物の Backend = REAL はそれをそのまま呼ぶ)。疑似は ④ の `eval/fake/fake_asr.py` の FakeBackend が上書きする。
どちらを使うかは app(編集の serve.py)が set_selector で登録する(呼ぶたびに決める = テストの `S.backend_name` の差し替えが効く)。
この層(pipeline)は eval を読まない。登録が無ければ REAL。
"""


class Backend:
    """本物の認識(faster-whisper・whisper.cpp などのワーカー)。どのメソッドも real(呼ぶ側の本物の処理)を呼ぶだけ"""
    name = "faster-whisper"   # 記録の名前(全体の再認識の続きの目印 whole_key の backend。編集の ed_state.backend_name() と同じ値)

    def engine_ids(self, spec, real):
        """recognition.runs のエンジンと版 -> (id, 版)。real(spec)"""
        return real(spec)

    def transcribe(self, job, spec, wav, total, real):
        """文字起こしのジョブの行(faster-whisper の行と同じ形の辞書)の生成器。real(job, spec, wav, total)"""
        return real(job, spec, wav, total)

    def redo_recognizer(self, job, spec, wav, start, real, finish):
        """疑わしい所の認識し直しの準備(モデルを読む)→ 行ごとに呼ぶ関数 f(sub, a, b) -> 行。real(job, spec, wav, start)。
        finish(raw, sub, shift) = 認識した行を範囲の行に整える(疑似が使う)"""
        return real(job, spec, wav, start)

    def range_main(self, job, a, b, share, real):
        """範囲・全体の再認識の [a, b] の行。real(a, b, share)"""
        return real(a, b, share)

    def range_loose(self, job, spans, real):
        """ほぼ空だった所を緩い条件で認識した行。real(spans)"""
        return real(spans)

    def each_lines(self, job, spec, targets, wav, start, real):
        """選んだ行を 1 行ずつ認識 -> {行の id: (文章, 要確認の理由)}。real(job, spec, targets, wav, start)"""
        return real(job, spec, targets, wav, start)

    def diarize(self, job, spec, wav, total, real):
        """話者判別のジョブの区間 [(開始, 終了, 話者番号)](音声の頭からの秒)。spec = 判別のジョブの指定(numSpeakers・embedding)・
        total = 音声の長さ(秒)。real(job, spec, wav) = 部品の確かめ・モデルの取得・ワーカーでの判別(RS2-9。疑似は eval/fake/fake_asr)"""
        return real(job, spec, wav)

    def embed(self, job, wav, emb, groups, real):
        """声の特徴 -> [長さ 1 の特徴 or None](groups と同じ並び)。groups = [[(開始, 終了)…]](音声の頭からの秒)・emb = 判別モデル。
        real(job, wav, emb, groups) = ワーカー(かワーカーの中)で特徴を取る(RS2-9)"""
        return real(job, wav, emb, groups)


    def alt_rows(self, job, spec, wav, total, real):
        """2つ目のエンジンの候補(human/proof/alt)の行の生成器(faster-whisper の行と同じ形の辞書)。real(job, spec, wav, total) = エンジンの確かめ → 読み込み → 認識
        (RS3-E6。疑似は eval/fake/fake_asr が主の疑似の行に TRANSCRIBE_FAKE_ALT の置き換えをかける)"""
        return real(job, spec, wav, total)


REAL = Backend()
_selector = [lambda: REAL]


def set_selector(fn):
    """使う Backend を決める関数(引数なし。呼ぶたびに呼ぶ)を登録する(app が読み込みのときに)"""
    _selector[0] = fn


def select():
    """今使う Backend"""
    return _selector[0]()
