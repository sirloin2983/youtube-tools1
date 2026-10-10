"""疑似の文字起こし(環境変数 TRANSCRIBE_BACKEND=fake のテスト・画面の通し確認用。役割で組み直す RS2-2 で編集の ed_jobs から移した)。

実際の音声認識は行わず、決まった形の行を作る。認識の部品(pipeline/transcribe・今は ed_jobs)は疑似を知らず、
`pipeline/transcribe/backend.py` の差し込み口から FakeBackend(FAKE)を呼ぶ。どちらを使うかは app(編集の serve.py)が決める
(`backend.set_selector`。ed_state.backend_name() が "fake" のとき FAKE)。
`transcribe_fake`・`_fake_spans` は今までどおり ed_jobs.名前 / S.名前 でも読める(serve が ed_jobs の転送にこのモジュールを足す)。編集の ed_state.fake_sleep は fake_wait の別名。
本体は呼ぶたびにこのモジュールの名前を読む(`mock.patch.object(ed_jobs, "transcribe_fake", …)` が効く)。
RS2-9 に、話者判別と声の特徴の疑似 diarize_fake・embed_fake を編集の ed_speakers から移した(S.diarize_fake・S.embed_fake は serve の受付、ed_speakers.名前 は殻の転送で読める。
認識ワーカーの worker-fake もこの 2 つを使う = 偽物どうしが食い違わない)。
"""
import os
import time

from pipeline.transcribe import backend as _fa_backend
from pipeline.transcribe import diarize as _fa_diarize   # 長さ 1 にする _unit(embed_fake。RS2-9)
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


def _alt_fake(job, spec, wav, total):
    """2つ目のエンジンの候補の疑似の認識(human/proof/alt。RS3-E6 に ed_alt から)。主の疑似と同じ行に、TRANSCRIBE_FAKE_ALT = "誤=>正,…" の置き換えをかける(テスト用)"""
    pairs = []
    for part in os.environ.get("TRANSCRIBE_FAKE_ALT", "").split(","):
        if "=>" in part:
            a, b = part.split("=>", 1)
            if a:
                pairs.append((a, b))
    for s in transcribe_fake(job, spec, wav, total):   # 呼ぶたびにこのモジュールの名前を読む(テストの差し替え)
        t = s["text"]
        for a, b in pairs:
            t = t.replace(a, b)
        yield dict(s, text=t)


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


def diarize_fake(job, total, num, threshold=None):
    """話者判別の疑似: 10秒ごとに話者が入れ替わる(行の途中で切り替わる場面も作る)。
    threshold(判別の設定を変えて測るとき)が 1.0 以上で人数が自動なら、全部を 1 人にまとめる(本物も、しきい値を上げるとまとまる)。渡さなければ以前と同じ"""
    n, t, k, turns = (num or (1 if threshold is not None and threshold >= 1.0 else 2)), 0.0, 0, []
    while t < total:
        _fa_jobs.check_cancel(job)
        e = min(total, t + 10.0)
        turns.append((t, e, k % n))
        job["progress"] = min(0.99, e / total)
        fake_wait()
        t, k = e, k + 1
    return turns


def embed_fake(groups):
    """声の特徴の疑似: 偽の話者判別(diarize_fake: 10秒ごとに入れ替わる)と同じ区切りの番号ごとに、向きの違う特徴(長さ 1)"""
    out = []
    for g in groups:
        votes = {}
        for a, b in g:
            k = int(((a + b) / 2.0) // 10) % 2   # diarize_fake の既定(2人)と同じ入れ替わり
            votes[k] = votes.get(k, 0.0) + (b - a)
        if not votes:
            out.append(None)
            continue
        v = [0.1] * 8
        v[max(votes, key=votes.get)] = 1.0
        out.append(_fa_diarize._unit(v))   # 長さ 1 に(本物の声の特徴と同じ形)
    return out


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

    def diarize(self, job, spec, wav, total, real):
        job["state"], job["phase"] = "running", "話者を判別中"
        return diarize_fake(job, total, spec["numSpeakers"])   # 呼ぶたびにこのモジュールの名前を読む(テストの差し替え)

    def embed(self, job, wav, emb, groups, real):
        return embed_fake(groups)

    def alt_rows(self, job, spec, wav, total, real):
        return _alt_fake(job, spec, wav, total)


FAKE = FakeBackend()
