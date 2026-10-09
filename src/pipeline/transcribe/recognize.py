# -*- coding: utf-8 -*-
"""① 音声の認識: 動画から音声を取り出す(extract_audio)・声の検出が捨てすぎたら緩めてやり直す(transcribe_vad_fallback)・文字起こしの行(transcribe_real)・
文字起こしのジョブの「取り出し → 認識 → 整えた行」(transcribe_rows。RS2-8e)・
選んだ行の 1 行ずつの認識(recognize_chunk・ChunkModel)・範囲の認識と行の整え方(range_lines_real・finish_range_lines・RangeRecognizer)・
全体の再認識の区間分けと続きから(whole_parts・whole_key・read_resume・write_resume・drop_resume・whole_lines)。

役割で組み直す RS2-7(2026-10-10)に編集の ed_jobs から移した(中身は同じ)。標準ライブラリ・ytt・同じパッケージの兄弟(backend・postproc・roster・tx_engines・
txbase・txenv・worker_client・records)だけを読む。ffmpeg・置き場所(TX_DIR)は呼ぶたびに txenv の口から。
行の頭の「名前:」を外す決まり(fill の B)は ① から fill を読まず、app(編集の serve.py)が set_head_stripper で登録した関数を呼ぶたびに使う
(ed_jobs.head_stripper。spec -> None(外さない)か 文字 -> (本文, 足す印) の関数)。
差し替えられる名前(extract_audio・WHOLE_PART_SEC・RangeRecognizer.main など)と読み手は同じこのモジュール。テストの S.extract_audio = …・
mock.patch.object(S.RangeRecognizer, "main", …) は serve の名前の受付と ed_jobs の転送(ytt/modfwd)でここに届く。
ジョブの本体(run_job・run_retranscribe・run_redo)と文書への反映(apply_range・plan_range・fit_lines・_ov など)は文書の側(human/proof の doc_jobs・rerun)。
run_job は transcribe_rows が返す行を受け取って、別の読み(fill)・LLM(llm)・置換辞書と学習した置換・文書の書き込みをする(計算 = ① / 文書への書き込み = ② の第 1 歩)。
"""
import hashlib
import json
import os
import subprocess
import time

from ytt import errors as _errors, fsio as _fsio, jobs as _heavy, schemas as _yschemas, tools as _tools
from . import backend as _backend, postproc, records, roster as _roster, tx_engines, txbase as _txbase, txenv as _txenv, worker_client

_head_stripper = []


def set_head_stripper(fn):
    """行の頭の「名前:」を外す決まりを登録する(app が読み込みのときに)。fn(spec) -> None(外さない)か split(文字) -> (本文, 足す印 か None)"""
    _head_stripper[:] = [fn]


def _stripper(spec):
    if not _head_stripper:
        raise RuntimeError("recognize の行の頭の名前を外す決まりが登録されていません(編集の serve.py が set_head_stripper で登録する)")
    return _head_stripper[0](spec)


def extract_audio(job, spec, wav):
    ff = _txenv.find_ffmpeg()
    if not ff:
        raise _errors.ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file"]
    if spec["start"] > 0:
        cmd += ["-ss", "%.3f" % spec["start"]]
    cmd += ["-i", spec["sourcePath"]]
    if spec["end"]:
        cmd += ["-t", "%.3f" % (spec["end"] - spec["start"])]
    cmd += ["-vn"]
    if spec.get("boost"):  # 小さい声を持ち上げる(低域のこもりを削り、音量のばらつきをならす)
        cmd += ["-af", "highpass=f=70,dynaudnorm=f=200:g=15:m=15"]
    cmd += ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace")
    job["proc"] = p
    try:
        err = p.stderr.read()
        p.wait()
    finally:
        job["proc"] = None
        _tools.kill_quiet(p)
        p.stderr.close()   # 読み終えたパイプを閉じる(閉じないと GC まで残る)
    _heavy.check_cancel(job)
    if p.returncode != 0 or not os.path.isfile(wav) or os.path.getsize(wav) < 1000:
        tail = " / ".join([l.strip() for l in (err or "").splitlines() if l.strip()][-2:])
        raise _errors.ApiError("extract_failed", "音声を取り出せませんでした。音声の無い動画か、壊れたファイルの可能性があります。別の動画を選んでください", 400,
                                {"detail": tail[:300]})   # ffmpeg の原文(パスを含む)は「詳しく」だけ(2 周目 N2)


# ---------- 声の検出(VAD)が捨てすぎたときのやり直し(docs/design/whole-retranscribe-design.md の 4-2) ----------
# 声が重なる所・BGM のある所を、Silero VAD が「声ではない」と判断して全部捨て、モデルに何も渡らないことがある(2026-09-28。40 秒が 0 文字)。
# 残った割合が VAD_MIN_KEEP 未満か、文字が 1 つも出なかったら、「弱め」→「なし」の順に緩めてやり直す
VAD_MIN_KEEP = 0.2
VAD_LADDER = {"normal": ("normal", "weak", "off"), "weak": ("weak", "off"), "off": ("off",)}
VAD_NAMES = {"normal": "標準", "weak": "弱め", "off": "なし"}


def seg_to_dict(s, shift=0.0):
    """認識の1行(faster-whisper の行・ワーカーの代理)→ 辞書(秒は shift を足す)"""
    ws = [w for w in (getattr(s, "words", None) or []) if getattr(w, "start", None) is not None and getattr(w, "end", None) is not None]
    words = [(float(w.start) + shift, float(w.end) + shift, str(w.word)) for w in ws]
    probs = [_prob(getattr(w, "probability", None)) for w in ws]   # words と同じ並びの確信度(3つ組は変えない。生出力 <id>.asr.json 用)
    return {"start": float(s.start) + shift, "end": float(s.end) + shift, "text": (s.text or "").strip(), "avg_logprob": getattr(s, "avg_logprob", None),
            "no_speech_prob": getattr(s, "no_speech_prob", None), "compression_ratio": getattr(s, "compression_ratio", None), "words": words,
            "wordProbs": probs}


def _prob(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if f == f else None


def vad_kept(info, mode):
    """(声の検出のあとに残った割合, 捨てた秒)。声の検出をかけていない・分からないときは (None, 0.0)"""
    d, k = getattr(info, "duration", None), getattr(info, "duration_after_vad", None)
    if mode == "off" or not isinstance(d, (int, float)) or not isinstance(k, (int, float)) or d <= 0:
        return None, 0.0
    return max(0.0, min(1.0, k / d)), round(max(0.0, d - k), 2)


def vad_note(vad):
    """やり直したときに画面に出す文(やり直していなければ '')"""
    if not vad or not vad.get("retries"):
        return ""
    steps = "→".join([VAD_NAMES.get(r["mode"], r["mode"]) for r in vad["retries"]] + [VAD_NAMES.get(vad["used"], vad["used"])])
    return "声の検出で大部分が「声ではない」と判断されたので、検出を緩めて認識しました(声の検出: %s)" % steps


def transcribe_vad_fallback(job, model, audio, spec, on_seg=None):
    """声の検出を spec["vadMode"] から始め、捨てすぎ・文字が 0 なら緩めてやり直す。-> (行の辞書の一覧, 声の検出の記録)。
    記録 = {"requested", "used", "removedSec"(使った設定で捨てた秒), "retries": [{"mode", "kept", "removedSec", "why": "kept"|"empty"}]}。
    よくある誤認識の文(HALLUC)しか出なかったときも「文字が 0」とみなす(2026-09-28 白上フブキ03: 標準で 22 秒捨て、残りから「ご視聴ありがとうございました」だけ)"""
    mode0 = spec.get("vadMode", "weak")
    ladder = VAD_LADDER.get(mode0, (mode0,))
    retries, terms = [], _roster.prompt_terms(spec)
    for i, mode in enumerate(ladder):
        last = i == len(ladder) - 1
        kw = worker_client.filter_kwargs(model, worker_client.whisper_kwargs(dict(spec, vadMode=mode)))
        segs, info = model.transcribe(audio, **kw)
        kept, removed = vad_kept(info, mode)
        if kept is not None and kept < VAD_MIN_KEEP and not last:
            close = getattr(segs, "close", None)
            if close:
                close()   # 行は読まない(ほとんど捨てた結果なので)
            retries.append({"mode": mode, "kept": round(kept, 3), "removedSec": removed, "why": "kept"})
            _txbase.log.info("声の検出が %.0f%% を捨てたので、緩めてやり直します(%s)", (1 - kept) * 100, mode)
            continue
        raw = []
        for s in segs:
            _heavy.check_cancel(job)
            raw.append(seg_to_dict(s))
            if on_seg:
                on_seg(raw[-1], len(raw))   # この回(やり直しごと)の行の数
        if not any(r["text"] and not postproc.stock_phrase(r["text"]) and not _roster.leak_only(r["text"], terms) for r in raw) and not last:
            # 「ご視聴ありがとうございました」だけ・ヒントの語だけ = 文字が 0 と同じ
            retries.append({"mode": mode, "kept": None if kept is None else round(kept, 3), "removedSec": removed, "why": "empty"})
            _txbase.log.info("文字が出なかったので、声の検出を緩めてやり直します(%s)", mode)
            continue
        return raw, {"requested": mode0, "used": mode, "removedSec": removed, "retries": retries}
    return [], {"requested": mode0, "used": ladder[-1], "removedSec": 0.0, "retries": retries}


def transcribe_real(job, spec, wav, total):
    model, device = worker_client.load_model(spec["model"], job, spec.get("device", "auto"), engine=tx_engines.engine_of(spec))
    job["device"] = device
    _heavy.check_cancel(job)
    job["phase"], job["state"] = "文字起こし中", "running"
    use = [model]

    def progress(r, n):
        job["progress"] = min(0.99, r["end"] / total) if total else 0.0
        job["segments"] = n   # 処理状況の「n 行」(行は最後まで読んでから流すので、ここで数える)

    def reload():
        use[0] = worker_client.load_model(spec["model"], job, force_cpu=True)[0]

    # やり直しに備えて、行は最後まで読んでから流す(やり直す前の行を文書に入れないため)
    raw, vad = worker_client.cpu_fallback(job, device, spec.get("device"), lambda: transcribe_vad_fallback(job, use[0], wav, spec, progress), reload, worker_client.GPU_FAILED_SETUP_MSG)
    job["vad"] = vad
    for x in raw:
        yield x


def _transcribe_checked(job, spec, wav, total):
    """run_job の本物の認識: エンジンを確かめてから transcribe_real(行の生成器)。RS2-8e に doc_jobs から移した"""
    worker_client.check_engine(spec)
    job["state"] = "loading"
    return transcribe_real(job, spec, wav, total)


def transcribe_rows(job, spec, wav):
    """文字起こしのジョブ(run_job)の ① の部分: 音声を取り出し(状態 extracting)→ 長さ → 本物か疑似の認識(backend.select。loading → running)→
    生出力を控えながら行を整える(postproc.expand_segments = 分け直し・長さの外を捨てる・繰り返し・行をつなぐ・句読点)。
    -> {"rows": 整えた行, "raw": 生出力(<id>.asr.json の segments), "total": 取り出した音声の長さ(秒。分からなければ範囲の長さか 0), "t_rec": 認識を始めた time.monotonic()}。
    名前は全部モジュール名つきで呼ぶたびに読む(S.extract_audio・backend の選び方・S.transcribe_fake・S.expand_segments の差し替えが届く)。RS2-8e に doc_jobs の run_job から移した(中身は同じ)"""
    job["state"], job["phase"] = "extracting", "音声を取り出し中"
    extract_audio(job, spec, wav)
    total = _txenv.media_duration(wav) or (spec["end"] - spec["start"] if spec["end"] else 0)
    t_rec = time.monotonic()   # 認識にかかった時間(モデルの読み込みを含む)。recognition.runs に残す
    gen = _backend.select().transcribe(job, spec, wav, total, _transcribe_checked)
    raw = []   # 生出力(<id>.asr.json)
    gen = records.capture_raw(gen, raw, spec["start"])
    rows = list(postproc.expand_segments(gen, spec, total))
    return {"rows": rows, "raw": raw, "total": total, "t_rec": t_rec}


AUDIO_MARGIN = 3.0   # 取り出す範囲の前後の余裕(秒)。音量補正(dynaudnorm)の窓が数秒あるので、端で音が変わらないよう広めに


def audio_span(targets, doc_start, doc_end, pad=0.3):
    """再認識・比較で取り出す音声の範囲(元の動画の秒)。対象の行の最初〜最後(+余裕)だけにする。
    以前は文書の範囲全体(最大6時間)を毎回取り出していて、1行の再認識でも数十秒と、1〜2GB のメモリを使っていた。"""
    a = max(doc_start, min(float(t["start"]) for t in targets) - pad - AUDIO_MARGIN)
    b = max(float(t["end"]) for t in targets) + pad + AUDIO_MARGIN
    if doc_end:
        b = min(doc_end, b)
    return round(a, 3), round(max(b, a + 0.5), 3)


def recognize_chunk(model, kw, chunk, seg, sep, terms=()):
    """短い範囲を認識して (文章, 要確認の理由) を返す。何も認識できなければ None。"""
    if len(chunk) < 1600:
        return None
    segs, _info = model.transcribe(chunk, **kw)
    parts, lp, ns, cr = [], [], [], []
    for x in segs:
        t = (x.text or "").strip()
        if t:
            parts.append(t)
            for lst, key in ((lp, "avg_logprob"), (ns, "no_speech_prob"), (cr, "compression_ratio")):
                v = getattr(x, key, None)
                if v is not None:
                    lst.append(v)
    text = sep.join(parts)
    if not text:
        return None
    agg = {"text": text, "start": seg["start"], "end": seg["end"], "avg_logprob": min(lp) if lp else None,
           "no_speech_prob": max(ns) if ns else None, "compression_ratio": max(cr) if cr else None}
    return text, postproc.make_flags(agg, [], kw.get("language"), terms)


class ChunkModel:
    """選んだ行を 1 行ずつ認識するモデル(再認識の each・設定の比較 ed_misc.run_abtest)。kw_spec = whisper_kwargs に渡す指定。
    自動のとき、最初の行で GPU が実行時に失敗(CUDA のライブラリ不足など)したら、CPU で読み直してやり直す"""

    def __init__(self, job, name, pref, kw_spec, engine=tx_engines.DEFAULT):
        self.job, self.name, self.pref, self.kw_spec = job, name, pref, kw_spec
        self._use(*worker_client.load_model(name, job, pref, engine=engine))

    def _use(self, model, device):
        self.model, self.device = model, device
        self.job["device"] = device
        self.kw = worker_client.filter_kwargs(model, worker_client.whisper_kwargs(self.kw_spec))

    def recognize(self, chunk, row, sep, terms, first=False):
        """recognize_chunk と同じ (文章, 要確認の理由) か None。CPU に切り替えるのは最初の行(first)だけ。
        取り消し・理由のある失敗(ApiError)はそのまま上げる(0.65.1。それまでは GPU 固定で最初の行の途中に取り消すと gpu_failed になっていた = ユーザー「なおす」)"""
        return worker_client.cpu_fallback(self.job, self.device, self.pref, lambda: recognize_chunk(self.model, self.kw, chunk, row, sep, terms),
                            lambda: self._use(*worker_client.load_model(self.name, self.job, force_cpu=True)), retry=first)


def range_lines_real(job, model, kw, audio, spec, offset):
    """範囲の音声をひとまとまりで認識し、単語の時刻で整えた行の一覧を返す。"""
    a, b = spec["range"]
    lo, hi = max(0.0, a - offset - 0.3), b - offset + 0.3
    chunk = audio[int(lo * 16000):int(hi * 16000)]
    if len(chunk) < 1600:
        return []
    segs, _info = model.transcribe(chunk, **kw)
    raw = []
    for s in segs:
        _heavy.check_cancel(job)
        raw.append(seg_to_dict(s))
        job["progress"] = min(0.95, 0.1 + float(s.end) / max(1e-6, hi - lo))
    return finish_range_lines(raw, spec, lo + offset, join=False)   # 疑わしい所の認識し直し: 文字を比べるだけで時刻を使わない(続いている行をつながない)


def finish_range_lines(raw, spec, shift, join=True):
    """認識した行(チャンク内の秒)を、絶対の秒にして、範囲 [a,b] の内側に収め、要確認の印を付ける。
    join = 続いている行をつなぐか(expand_segments の join。範囲・全体の再認識は行の時刻を使うのでつなぐ・疑わしい所の認識し直しはつながない)"""
    a, b = spec["range"]
    out, prev, terms = [], [], _roster.prompt_terms(spec)
    split = _stripper(spec)   # 行の頭の「名前:」(0.67.0。決まりは app が登録した ed_jobs.head_stripper = fill の B)
    for s in postproc.expand_segments(raw, spec, join=join):
        note = None
        if split is not None:
            s["text"], note = split(s["text"])
        if not s["text"]:
            continue
        st, en = max(a, s["start"] + shift), min(b, s["end"] + shift)
        if en - st < 0.05:
            continue
        flag = postproc.make_flags({**s, "start": st, "end": en}, prev, spec["language"], terms)
        if note:
            flag = "、".join(x for x in (note, flag) if x)[:100]
        prev.append(s["text"])
        out.append({"start": st, "end": en, "raw": s["text"], "flag": flag, "words": postproc.row_words(s, shift), "lp": s.get("avg_logprob"), "conf": postproc.machine_conf(s)})
    return out


class RangeRecognizer:
    """範囲・全体の再認識の認識の部分(本物のモデル / 疑似)。音声は run_retranscribe が取り出した wav(先頭 = 元の動画の offset 秒)。
    main(a, b): 範囲をひとまとまりで認識(声の検出が捨てすぎたら緩めてやり直す。4-2 の 1)
    loose(spans): ほぼ空だった所だけ、声の検出なし・捨てる判定なしで認識(4-2 の 3。よくある誤認識の文は捨てる)"""

    def __init__(self, job, spec, wav, offset):
        self.job, self.spec, self.wav, self.offset = job, spec, wav, offset
        self.model = self.audio = None
        self.vad = None

    def _load(self):
        if self.model is not None:
            return
        worker_client.check_engine(self.spec)
        self.job["state"] = "loading"
        self.model, device = worker_client.load_model(self.spec["model"], self.job, self.spec["device"], engine=tx_engines.engine_of(self.spec))
        self.job["device"] = device
        self.audio = worker_client.read_wav_f32(self.wav)
        self.job["state"] = "running"

    def _chunk(self, a, b, pad):
        lo, hi = max(0.0, a - self.offset - pad), b - self.offset + pad
        return self.audio[int(lo * 16000):int(hi * 16000)], lo

    def main(self, a, b, share=(0.0, 1.0)):
        """[a, b](元の動画の秒)を認識した行。行は [a, b] の内側に収める(全体を区間に分けたとき、隣の区間と重ならない)。
        share = 進み具合のうち、この区間が受け持つ割合(全体を区間に分けたとき)。本物と疑似は backend の差し込み口(呼ぶたびに選ぶ)"""
        return _backend.select().range_main(self.job, a, b, share, self._main_real)

    def _main_real(self, a, b, share):
        self._load()
        chunk, lo = self._chunk(a, b, 0.3)
        if len(chunk) < 1600:
            return []
        total = max(1e-6, b - a + 0.6)
        s0, s1 = share

        def progress(r, _n):
            self.job["progress"] = s0 + (s1 - s0) * min(0.9, 0.05 + r["end"] / total * 0.85)

        def reload():
            self.model = worker_client.load_model(self.spec["model"], self.job, force_cpu=True)[0]
        raw, self.vad = worker_client.cpu_fallback(self.job, self.job.get("device"), self.spec["device"],
                                     lambda: transcribe_vad_fallback(self.job, self.model, chunk, self.spec, progress), reload)
        return finish_range_lines(raw, dict(self.spec, range=[a, b]), lo + self.offset)

    def loose(self, spans):
        if not spans:
            return []
        self.job["phase"] = "文字が出なかった所を、条件を緩めて認識中"
        return _backend.select().range_loose(self.job, spans, self._loose_real)

    def _loose_real(self, spans):
        out = []
        self._load()
        kw = worker_client.filter_kwargs(self.model, dict(worker_client.whisper_kwargs(dict(self.spec, vadMode="off")), no_speech_threshold=None))
        for n, (s0, s1) in enumerate(spans):
            _heavy.check_cancel(self.job)
            chunk, lo = self._chunk(s0, s1, 0.0)
            if len(chunk) < 1600:
                continue
            segs, _info = self.model.transcribe(chunk, **kw)
            raw = []
            for x in segs:
                _heavy.check_cancel(self.job)
                raw.append(seg_to_dict(x))
            lines = finish_range_lines(raw, dict(self.spec, range=[s0, s1]), lo + self.offset)
            out += [x for x in lines if "よくある誤認識の文" not in str(x.get("flag") or "") and _txbase.LEAK_FLAG not in str(x.get("flag") or "")]   # 無音から出やすい幻覚・ヒントの書き写しは入れない(元の行が残る)
            self.job["progress"] = min(0.99, 0.9 + 0.09 * (n + 1) / len(spans))
        return out


# ---------- 全体の再認識を区間ごとに保存して、続きから(計画の 9 の S-1) ----------
# 全体の再認識は最大 6 時間。途中で落ちる・中止すると、それまでの認識が全部むだになっていた。
# 長い動画は WHOLE_PART_SEC ごとの区間に分けて1つずつ認識し、終わった区間の行を transcripts/.resume/<id>.whole.json に書く。
# 同じ文書・同じ設定・同じ動画でもう一度始めたら、書いてある区間は認識せずに使う。全部終わって文書に反映したら消す。
# 短い動画(WHOLE_PART_SEC の 1.5 倍まで)は今までどおり1回で認識する(分けない = 結果は変わらない・書かない)
WHOLE_PART_SEC = 600
WHOLE_SPLIT_WINDOW = 90      # 区切りは、目安の前後この秒の中で、行の無いすき間の真ん中(話している途中で切らない)
RESUME_KEEP_SEC = 7 * 86400  # 使われなかった続きの記録は、この秒数で消す
RESUME_VERSION = 1
MAX_RESUME_BYTES = 64 * 1024 * 1024   # 続きの記録を読む大きさの上限(6 時間分の行と単語。生出力 asr.json と同じ上限)


def whole_parts(doc, a, b, part=None):
    """[a, b] を、目安 part 秒ごとの区間 [[p0, p1], …] に分ける。区切りは、今の文書の行(どれでも)の無いすき間を選ぶ。無ければ目安の所"""
    part = float(part or WHOLE_PART_SEC)
    if b - a <= part * 1.5:
        return [[a, b]]
    rows = _yschemas.union_spans([(float(g["start"]), float(g["end"])) for g in doc.get("segments") or []
                        if isinstance(g, dict) and isinstance(g.get("start"), (int, float)) and isinstance(g.get("end"), (int, float))])
    gaps = [(rows[i][1], rows[i + 1][0]) for i in range(len(rows) - 1)]
    out, t = [], a
    while b - t > part * 1.5:
        target = t + part
        lo, hi = max(t + part / 2, target - WHOLE_SPLIT_WINDOW), target + WHOLE_SPLIT_WINDOW
        best = None
        for g0, g1 in gaps:
            x0, x1 = max(g0, lo), min(g1, hi)
            if x1 > x0 and (best is None or x1 - x0 > best[1] - best[0]):
                best = (x0, x1)
        cut = round((best[0] + best[1]) / 2 if best else target, 3)
        out.append([t, cut])
        t = cut
    out.append([t, b])
    return out


def resume_path(tid):
    return os.path.join(_txenv.TX_DIR, ".resume", tid + ".whole.json")


def whole_key(spec, doc):
    """続きを使ってよいかの目印: 文書・範囲・行を作る設定・ヒントの語・エンジンとモデル・元の動画(大きさと更新日時)が同じ"""
    try:
        st = os.stat(str(doc.get("sourcePath") or ""))
        src = [st.st_size, int(st.st_mtime)]
    except OSError:
        src = None
    k = {"v": RESUME_VERSION, "tid": spec["tid"], "range": spec["range"], "engine": spec.get("engine") or tx_engines.DEFAULT, "model": spec["model"],
         "backend": _backend.select().name, "language": spec["language"], "beam": spec["beam"], "vadMode": spec["vadMode"], "boost": bool(spec.get("boost")),
         "wordSplit": bool(spec.get("wordSplit")), "splitChars": spec.get("splitChars"), "stripPunct": spec.get("stripPunct", True) is not False,
         "terms": _roster.prompt_terms(spec), "source": src, "part": WHOLE_PART_SEC}
    return hashlib.sha256(json.dumps(k, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def read_resume(tid, key):
    """続きの記録 {"parts", "done": {番号: {"lines", "vad"}}}。無い・目印が違う・壊れている・大きすぎるときは None"""
    d = _fsio.read_json_or(resume_path(tid), None, MAX_RESUME_BYTES, dict)
    if d is None or d.get("key") != key or not isinstance(d.get("parts"), list) or not isinstance(d.get("done"), dict):
        return None
    return d


def write_resume(tid, d):
    path = resume_path(tid)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    _fsio.atomic_write(path, json.dumps(dict(d, at=int(time.time() * 1000)), ensure_ascii=False).encode("utf-8"), fsync_required=True)
    now = time.time()
    for n in os.listdir(folder):   # 使われなかった古い続きの記録を消す
        q = os.path.join(folder, n)
        try:
            if n.endswith(".whole.json") and q != path and now - os.path.getmtime(q) > RESUME_KEEP_SEC:
                os.unlink(q)
        except OSError:
            pass


def drop_resume(tid):
    _fsio.unlink_quiet(resume_path(tid))


def whole_lines(job, spec, doc, rec):
    """全体の再認識の認識の部分。長ければ区間に分けて1つずつ認識し、終わった区間を書いておく(続きから再開できる)。-> 行の一覧。
    rec.vad には、声の検出をやり直した区間があればその記録を入れる(画面の知らせ)"""
    a, b = spec["range"]
    key = whole_key(spec, doc)
    cp = read_resume(spec["tid"], key)
    parts = cp["parts"] if cp else whole_parts(doc, a, b)
    done = cp["done"] if cp else {}
    n = len(parts)
    reused = sum(1 for i in range(n) if str(i) in done)
    if reused:
        job["resumed"] = [reused, n]
        _txbase.add_warning(job, "前回の途中から続けました(%d 区間のうち %d 区間は前回の認識を使いました)" % (n, reused))
        _txbase.log.info("全体の再認識を前回の途中から続けます: %s %d/%d 区間", spec["tid"], reused, n)
    lines, vads = [], []
    for i, (p0, p1) in enumerate(parts):
        _heavy.check_cancel(job)
        if str(i) in done:
            lines += done[str(i)].get("lines") or []
            vads.append(done[str(i)].get("vad"))
            continue
        job["phase"] = "全体を認識中(%d / %d 区間)" % (i + 1, n) if n > 1 else "全体を認識中"
        got = rec.main(p0, p1, (i / n, (i + 1) / n))
        _heavy.check_cancel(job)   # 途中で止めた区間は書かない(行が欠けている)
        lines += got
        vads.append(rec.vad)
        if n > 1:
            done[str(i)] = {"lines": got, "vad": rec.vad}
            try:
                write_resume(spec["tid"], {"v": RESUME_VERSION, "key": key, "parts": parts, "done": done})
            except (OSError, TypeError, ValueError) as e:   # 書けなくても認識は続ける(続きから再開できないだけ)
                _txbase.log.warning("全体の再認識の続きの記録を書けませんでした: %s %s", spec["tid"], e)
    rec.vad = next((v for v in vads if v and v.get("retries")), None) or (vads[-1] if vads else None)
    return lines
