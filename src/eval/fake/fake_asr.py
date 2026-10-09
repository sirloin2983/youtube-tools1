"""疑似の文字起こし(環境変数 TRANSCRIBE_BACKEND=fake のテスト・画面の通し確認用。役割で組み直す RS2-2 で編集の ed_jobs から移した)。

実際の音声認識は行わず、決まった形の行を作る。認識の部品(pipeline/transcribe・今は ed_jobs)は疑似を知らず、
`pipeline/transcribe/backend.py` の差し込み口から FakeBackend(FAKE)を呼ぶ。どちらを使うかは app(編集の serve.py)が決める
(`backend.set_selector`。ed_state.backend_name() が "fake" のとき FAKE)。
`transcribe_fake`・`_fake_spans` は今までどおり ed_jobs.名前 / S.名前 でも読める(serve が ed_jobs の転送にこのモジュールを足す)。編集の ed_state.fake_sleep は fake_wait の別名。
本体は呼ぶたびにこのモジュールの名前を読む(`mock.patch.object(ed_jobs, "transcribe_fake", …)` が効く)。
"""
import os
import time

from pipeline.transcribe import backend as _fa_backend
from ytt import jobs as _fa_jobs


def fake_wait():
    """疑似のバックエンド(テスト)の 1 行ごとの待ち(環境変数 TRANSCRIBE_FAKE_DELAY 秒)"""
    time.sleep(float(os.environ.get("TRANSCRIBE_FAKE_DELAY", "0.05")))


def transcribe_fake(job, spec, wav, total):
    """テスト用(環境変数 TRANSCRIBE_BACKEND=fake)。実際の音声認識は行わない。"""
    job["phase"], job["state"], job["device"] = "文字起こし中", "running", "cpu"
    t, i = 0.0, 0
    while t < total:
        _fa_jobs.check_cancel(job)
        e = min(total, t + 4.0)
        i += 1
        yield {"start": t, "end": e, "text": "テスト文%d" % i, "avg_logprob": -1.4 if i % 5 == 0 else -0.3,
               "no_speech_prob": 0.1, "compression_ratio": 1.2}
        job["progress"] = min(0.99, e / total)
        fake_wait()
        t = e


def _fake_spans(name):
    """テスト用: 環境変数 name = "a-b,c-d"(秒)の区間の一覧"""
    out = []
    for part in os.environ.get(name, "").split(","):
        try:
            a, b = (float(x) for x in part.split("-"))
            out.append((a, b))
        except ValueError:
            pass
    return out


def fake_range_lines(job, a, b, loose, share=(0.0, 1.0)):
    """範囲・全体の再認識の疑似: 3 秒ごとに「範囲再認識N」。TRANSCRIBE_FAKE_GAP の区間には出さない(声が重なって 0 文字の所の代わり)。
    loose のときは TRANSCRIBE_FAKE_LOOSE が 1 なら 1.5 秒ごとに「緩い条件N」(無ければ何も出ない)"""
    job["state"], job["device"] = "running", "cpu"
    if loose and os.environ.get("TRANSCRIBE_FAKE_LOOSE") != "1":
        return []
    gaps = [] if loose else _fake_spans("TRANSCRIBE_FAKE_GAP")
    step, label = (1.5, "緩い条件") if loose else (3.0, "範囲再認識")
    lines, t0, k = [], a, 0
    while t0 < b - 0.05:
        _fa_jobs.check_cancel(job)
        e = min(b, t0 + step)
        if not any(min(e, g1) - max(t0, g0) > 0 for g0, g1 in gaps):
            k += 1
            lines.append({"start": t0, "end": e, "raw": "%s%d" % (label, k), "flag": "自信が低い" if k % 2 == 0 and not loose else ""})
        t0 = e
        job["progress"] = share[0] + (share[1] - share[0]) * min(0.95, (t0 - a) / max(1e-6, b - a))
        fake_wait()
    return lines


class FakeBackend(_fa_backend.Backend):
    """疑似の認識(本物の処理 real は呼ばない)"""
    name = "fake"

    def engine_ids(self, spec, real):
        return "fake", ""

    def transcribe(self, job, spec, wav, total, real):
        return transcribe_fake(job, spec, wav, total)   # 呼ぶたびにこのモジュールの名前を読む(テストの差し替え)

    def redo_recognizer(self, job, spec, wav, start, real, finish):
        job["device"] = "cpu"

        def recognize(sub, a, b):   # 行の長さに見合う文字数の文
            txt = "認識し直した文" * max(1, int((b - a) * 2 / 7) + 1)
            lines = finish([{"start": 0.0, "end": b - a, "text": txt, "avg_logprob": -0.2, "no_speech_prob": 0.1, "compression_ratio": 1.2}], sub, a)
            fake_wait()
            return lines
        return recognize

    def range_main(self, job, a, b, share, real):
        return fake_range_lines(job, a, b, False, share)

    def range_loose(self, job, spans, real):
        out = []
        for s0, s1 in spans:
            out += fake_range_lines(job, s0, s1, True)
        return out

    def each_lines(self, job, spec, targets, wav, start, real):
        results = {}
        job["state"], job["phase"], job["device"] = "running", "再認識中", "cpu"
        for n, t in enumerate(targets):
            _fa_jobs.check_cancel(job)
            results[t["id"]] = (t["text"] + "(再)", "自信が低い" if n % 3 == 0 else "")
            job["progress"] = (n + 1) / len(targets)
            fake_wait()
        return results


FAKE = FakeBackend()
