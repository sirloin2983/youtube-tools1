# -*- coding: utf-8 -*-
"""文字起こしの認識エンジンの口(精度改善の計画 段2。docs/plan/transcription-overhaul-plan.md)。

認識ワーカー(tx_worker.py)が読み込むモデルは、ここのエンジンの1つとして作る。
  faster-whisper … 今までのエンジン(CPU / NVIDIA の GPU)。段2-1
  whisper.cpp    … whisper-cli.exe を子プロセスで動かす。AMD の GPU(Vulkan)で large-v3 などを動かす。段2-2
新しいエンジン(Qwen3-ASR など)は、同じ形のクラスをここに足し、ENGINES に登録する。

エンジンの形(Engine):
  device_order(pref, cuda_ok) -> [機器]            処理方式(auto / cuda / cpu)から試す機器の順
  create(name, device, compute_type, log, data_dir) -> エンジン   モデルを読み込む(失敗したら例外)
  transcribe(audio, **kw) -> (行の生成器, 情報)      faster-whisper の WhisperModel.transcribe と同じ形。
      行は属性 start・end・text・words(start・end・word・probability)・avg_logprob・no_speech_prob・compression_ratio、
      情報は language・duration・duration_after_vad。audio は wav のパスか float32 のサンプル(16kHz・モノラル)。kw は faster-whisper の引数の名前
  params() -> [受け付ける引数の名前]                  サーバーは、これに無い引数を渡さない(ed_jobs.filter_kwargs)
  hooks = {"cancelled": 関数, "progress": 関数}        ワーカーが入れる(取り消しと進み具合。faster-whisper は使わない)

このファイルは、サーバー側からも名前・版・準備できているかのために読む。
**ネイティブの部品(faster_whisper・numpy など)は create・transcribe の中で読み込む**(サーバーのプロセスに入れない決まり = tests/test_worker.py が検査)。
取得する実行ファイル・モデルは、URL・大きさ・SHA-256 を固定(計画の 7)。外部コマンドは引数のリストで渡し、shell を使わない。モデルの名前から任意のパスを作らない。
"""
import hashlib
import inspect
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import wave
import zlib

DEFAULT = "faster-whisper"


class EngineError(Exception):
    """エンジンの準備・実行の失敗(理由を画面に出す)。code はサーバーの ApiError の code になる"""

    def __init__(self, code, message, status=500):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class Engine:
    """エンジンの元。id = 記録(recognition.runs の engine)とワーカーへの要求に使う名前、package = 版を読むパッケージ(dist-info)"""
    id = ""
    package = ""

    def __init__(self, name, device, model):
        self.name, self.device, self.model = name, device, model
        self.hooks = {}

    @classmethod
    def device_order(cls, pref, cuda_ok):
        if pref == "cpu":
            return ["cpu"]
        if pref == "cuda":
            return ["cuda"]
        return ["cuda", "cpu"] if cuda_ok else ["cpu"]

    @classmethod
    def create(cls, name, device, compute_type, log=None, data_dir=None, hooks=None):
        """hooks = {"cancelled", "download"(取得の割合)}(モデルを取るエンジンだけが使う)"""
        raise NotImplementedError

    @classmethod
    def valid_model(cls, name):
        return True

    @classmethod
    def ready(cls, data_dir):
        """(使えるか, 使えない理由)。サーバー側から呼ぶ(ネイティブの部品を読まない)"""
        return True, ""

    @classmethod
    def version(cls, data_dir=None):
        return ""

    def transcribe(self, audio, **kw):
        raise NotImplementedError

    def params(self):
        return []

    def _cancelled(self):
        f = self.hooks.get("cancelled")
        return bool(f and f())

    def _progress(self, v):
        f = self.hooks.get("progress")
        if f:
            f(v)


class FasterWhisper(Engine):
    """faster-whisper(CTranslate2)。CPU は int8、GPU(CUDA)は compute_type。ダウンロード済みなら手元のファイルだけで読む(計画 段0-4)"""
    id = "faster-whisper"
    package = "faster-whisper"

    @classmethod
    def create(cls, name, device, compute_type, log=None, data_dir=None, hooks=None):
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


# ---------------------------------------------------------------- whisper.cpp(段2-2)
# 実行ファイルは公式の配布に Windows の Vulkan 版が無いので、公式のソースを決まったコミットで取り、この PC で作る(setup/build-whisper-vulkan.bat。
# 2026-10-02 ユーザー決定)。作った物は作業データの bin\whisper.cpp-<版>-vulkan\ に置き、build.json にコミットを記録する(違えば使わない)。
WHISPER_CPP = {"version": "v1.9.4", "commit": "927cfce34f31707e17f2bff35c349632fb9e2c3a", "repo": "https://github.com/ggml-org/whisper.cpp.git"}
_HF = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
WCPP_MODELS = {   # モデルの名前 → ggml のファイル(Hugging Face の ggerganov/whisper.cpp。大きさと SHA-256 は 2026-10-02 に API で確かめた)
    "large-v3": {"file": "ggml-large-v3.bin", "url": _HF + "ggml-large-v3.bin", "size": 3095033483,
                 "sha256": "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"},
    "large-v3-turbo": {"file": "ggml-large-v3-turbo.bin", "url": _HF + "ggml-large-v3-turbo.bin", "size": 1624555275,
                       "sha256": "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"},
}
WCPP_VAD = {"file": "ggml-silero-v6.2.0.bin", "url": "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin", "size": 885098,
            "sha256": "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"}   # 声の検出(Silero v6.2。計画の 3)
WCPP_EXE = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
_GPU_LINE = re.compile(r"whisper_backend_init_gpu: (?:using (.+?) backend|no GPU found)")
_PROGRESS = re.compile(r"progress\s*=\s*(\d+)%")
_VK_DEV = re.compile(r"ggml_vulkan: \d+ = ([^|(]+)")


def wcpp_bin_dir(data_dir):
    return os.path.join(data_dir, "bin", "whisper.cpp-%s-vulkan" % WHISPER_CPP["version"])


def wcpp_model_dir(data_dir):
    return os.path.join(data_dir, "models", "whispercpp")


def fetch_file(spec, folder, log=None, cancelled=None, progress=None):
    """spec(url・size・sha256・file)のファイルを folder に用意してパスを返す。あれば大きさと SHA-256 を確かめるだけ。
    取るときは .part に書き、大きさと SHA-256 が合ったときだけ名前を付ける(違えば消して EngineError)。URL は https の固定のものだけ"""
    path = os.path.join(folder, spec["file"])
    if os.path.isfile(path) and os.path.getsize(path) == spec["size"]:
        if _sha256(path) == spec["sha256"]:
            return path
        if log:
            log.warning("ファイルの中身が違うので取り直します: %s", path)
    if not spec["url"].startswith("https://"):
        raise EngineError("fetch_failed", "取得先が https ではありません")
    import urllib.request
    os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    h, got, last = hashlib.sha256(), 0, 0.0
    if log:
        log.info("取得します: %s(%.1f MB)", spec["url"], spec["size"] / 1e6)
    try:
        with urllib.request.urlopen(spec["url"], timeout=60) as r, open(part, "wb") as f:
            while True:
                if cancelled and cancelled():
                    raise EngineError("cancelled", "中止しました")
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                h.update(b)
                got += len(b)
                if got > spec["size"]:
                    raise EngineError("fetch_failed", "取得したファイルが想定より大きいので使いません: %s" % spec["file"])
                now = time.monotonic()
                if progress and now - last > 0.5:
                    last = now
                    progress(got / spec["size"])
    except EngineError:
        _unlink(part)
        raise
    except OSError as e:
        _unlink(part)
        raise EngineError("fetch_failed", "%s を取得できませんでした: %s(ネットワークを確かめてください)" % (spec["file"], str(e)[:160]))
    if got != spec["size"] or h.hexdigest() != spec["sha256"]:
        _unlink(part)
        raise EngineError("fetch_failed", "取得した %s の中身が想定と違うので使いません(大きさ %d / SHA-256 が一致しない)" % (spec["file"], got))
    os.replace(part, path)
    return path


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _unlink(p):
    try:
        os.unlink(p)
    except OSError:
        pass


def _ascii_path(p):
    """whisper-cli は引数を(応答ファイルで)UTF-8 のまま受け取り、Windows ではファイルを ANSI で開くので、ASCII でないパスは開けない。
    ASCII でなければ短い名前(8.3)にする。できなければ EngineError"""
    p = os.path.abspath(p)
    try:
        p.encode("ascii")
        return p
    except UnicodeEncodeError:
        pass
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
        if 0 < n < 1024:
            try:
                buf.value.encode("ascii")
                return buf.value
            except UnicodeEncodeError:
                pass
    raise EngineError("bad_path", "whisper.cpp は英数字以外を含む場所のファイルを開けません: %s" % p[-120:], 400)


class WhisperCpp(Engine):
    """whisper.cpp(whisper-cli を子プロセスで)。機器は vulkan(AMD などの GPU)か cpu。GPU を頼んだのに Vulkan で動かなければ、黙って CPU にせず止める(計画 段2-2)"""
    id = "whisper.cpp"
    package = ""
    PARAMS = ["beam_size", "condition_on_previous_text", "initial_prompt", "language", "no_speech_threshold", "temperature",
              "vad_filter", "vad_parameters", "word_timestamps"]   # hotwords・chunk_length は無い(渡されても使わない)
    COMMAND = None   # テスト用: [python, 偽の whisper-cli] に差し替える

    @classmethod
    def device_order(cls, pref, cuda_ok):
        return ["cpu"] if pref == "cpu" else ["vulkan"]   # 自動でも GPU が使えないときは CPU にしない(理由を出して止める)

    @classmethod
    def valid_model(cls, name):
        return name in WCPP_MODELS

    @classmethod
    def manifest(cls, data_dir):
        try:
            with open(os.path.join(wcpp_bin_dir(data_dir), "build.json"), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None

    @classmethod
    def ready(cls, data_dir):
        if cls.COMMAND:
            return True, ""
        exe = os.path.join(wcpp_bin_dir(data_dir), WCPP_EXE)
        if not os.path.isfile(exe):
            return False, "whisper.cpp がまだ作られていません(setup\\build-whisper-vulkan.bat を実行してください)"
        m = cls.manifest(data_dir)
        if not m or m.get("commit") != WHISPER_CPP["commit"]:
            return False, "whisper.cpp の版が想定と違います(setup\\build-whisper-vulkan.bat で作り直してください)"
        return True, ""

    @classmethod
    def version(cls, data_dir=None):
        return WHISPER_CPP["version"]

    @classmethod
    def create(cls, name, device, compute_type, log=None, data_dir=None, hooks=None):
        spec = WCPP_MODELS.get(name)
        if spec is None:
            raise EngineError("bad_model", "whisper.cpp で使えないモデルです: %s(使えるのは %s)" % (str(name)[:40], "・".join(WCPP_MODELS)), 400)
        ok, why = cls.ready(data_dir)
        if not ok:
            raise EngineError("engine_missing", why, 400)
        hooks = hooks or {}
        mdir = wcpp_model_dir(data_dir)
        model = fetch_file(spec, mdir, log, hooks.get("cancelled"), hooks.get("download"))
        vad = fetch_file(WCPP_VAD, mdir, log, hooks.get("cancelled"))
        cmd = list(cls.COMMAND) if cls.COMMAND else [os.path.join(wcpp_bin_dir(data_dir), WCPP_EXE)]
        e = cls(name, device, {"cmd": cmd, "model": model, "vad": vad})
        e.gpu_name = ""
        return e

    def params(self):
        return list(self.PARAMS)

    def args(self, wav, out_base, kw):
        """whisper-cli の引数(応答ファイルの行)。kw は faster-whisper の引数の名前(ed_jobs.whisper_kwargs が作る)"""
        a = ["-m", _ascii_path(self.model["model"]), "-f", _ascii_path(wav), "-ojf", "-of", _ascii_path(out_base), "-pp",
             "-t", str(max(1, min(8, (os.cpu_count() or 4) // 2))), "-l", str(kw.get("language") or "auto"), "-bs", str(int(kw.get("beam_size") or 5))]
        if kw.get("condition_on_previous_text") is False:
            a += ["-mc", "0"]   # 前の文を文脈にしない(faster-whisper と同じ)
        if self.device == "cpu":
            a += ["-ng"]
        if kw.get("temperature") == 0.0:
            a += ["-tp", "0", "-nf"]   # 温度のやり直しをしない(精度を比べる道具の --temp0)
        if kw.get("no_speech_threshold") is not None:
            a += ["-nth", "%g" % float(kw["no_speech_threshold"])]
        prompt = re.sub(r"[\r\n]+", " ", str(kw.get("initial_prompt") or "")).strip()
        if prompt:
            a += ["--prompt", prompt]
        if kw.get("vad_filter"):
            vp = kw.get("vad_parameters") or {}
            a += ["--vad", "-vm", _ascii_path(self.model["vad"])]
            if vp.get("threshold") is not None:
                a += ["-vt", "%g" % float(vp["threshold"])]
            if vp.get("min_silence_duration_ms") is not None:
                a += ["-vsd", str(int(vp["min_silence_duration_ms"]))]
            if vp.get("speech_pad_ms") is not None:
                a += ["-vp", str(int(vp["speech_pad_ms"]))]
        return a

    def transcribe(self, audio, **kw):
        work = tempfile.mkdtemp(prefix="wcpp-")
        try:
            if isinstance(audio, str):
                wav = audio
            else:   # 範囲の音声(float32 のサンプル)は一時の wav にする
                wav = os.path.join(work, "in.wav")
                _write_wav(wav, audio)
            duration = _wav_seconds(wav)
            out_base = os.path.join(work, "out")
            rsp = os.path.join(work, "args.txt")
            with open(rsp, "w", encoding="utf-8", newline="\n") as f:   # 引数は応答ファイル(UTF-8)で渡す: コマンド行は Windows の文字コードで読まれ、日本語のヒントが化けるため
                f.write("\n".join(self.args(wav, out_base, kw)) + "\n")
            log = self._run(self.model["cmd"] + ["@" + _ascii_path(rsp)])
            self._check_gpu(log)
            try:
                with open(out_base + ".json", "rb") as f:
                    data = json.loads(f.read().decode("utf-8", errors="replace"), strict=False)
            except (OSError, ValueError) as e:
                raise EngineError("engine_failed", "whisper.cpp の結果を読めませんでした: %s" % str(e)[:160])
            segs = parse_json(data)
            info = types.SimpleNamespace(language=(data.get("result") or {}).get("language") or kw.get("language"),
                                         duration=duration, duration_after_vad=None)   # whisper.cpp は声の検出のあとの長さを返さない
            return iter(segs), info
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _run(self, cmd):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
        lines = []

        def read():
            for raw in p.stderr:
                s = raw.decode("utf-8", errors="replace").rstrip()
                lines.append(s)
                if len(lines) > 400:
                    del lines[:100]
                m = _PROGRESS.search(s)
                if m:
                    self._progress(min(0.99, int(m.group(1)) / 100.0))
        t = threading.Thread(target=read, daemon=True)
        t.start()
        while p.poll() is None:
            if self._cancelled():
                p.kill()
                p.wait(10)
                t.join(5)
                p.stderr.close()
                raise EngineError("cancelled", "中止しました")
            time.sleep(0.2)
        t.join(10)
        p.stderr.close()
        if p.returncode != 0:
            tail = " / ".join(x for x in lines[-6:] if x)
            raise EngineError("engine_failed", "whisper.cpp が失敗しました(終了コード %s): %s" % (p.returncode, tail[-300:]))
        return lines

    def _check_gpu(self, log):
        """GPU(Vulkan)を頼んだのに使っていなければ止める(黙って CPU で動いた結果を「GPU」として残さない)"""
        used = None
        for s in log:
            m = _GPU_LINE.search(s)
            if m:
                used = m.group(1) or ""
            d = _VK_DEV.search(s)
            if d:
                self.gpu_name = d.group(1).strip()
        if self.device == "vulkan" and not (used and "vulkan" in used.lower()):
            raise EngineError("gpu_failed", "GPU(Vulkan)を使えませんでした(%s)。GPU のドライバを確かめるか、処理方式を「CPU」にしてください"
                              % ("GPU が見つからない" if used is not None else "GPU の初期化の記録が無い"))


def parse_json(data):
    """whisper-cli の -ojf の結果 → faster-whisper と同じ属性の行の一覧。単語 = 文字のトークン(特別なトークン [_…] は除く)。
    avg_logprob はトークンの確率の対数の平均(faster-whisper の値と同じ尺度の近い値)、compression_ratio は文字列の zlib の圧縮率(faster-whisper と同じ式)"""
    out = []
    for seg in data.get("transcription") or []:
        if not isinstance(seg, dict):
            continue
        off = seg.get("offsets") or {}
        a, b = _ms(off.get("from")), _ms(off.get("to"))
        if a is None or b is None:
            continue
        text = str(seg.get("text") or "")
        words, lps = [], []
        for tok in seg.get("tokens") or []:
            t = str((tok or {}).get("text") or "")
            if not t or t.startswith("[_") or "�" in t:
                continue
            p = tok.get("p")
            p = float(p) if isinstance(p, (int, float)) else None
            if p is not None:
                lps.append(math.log(max(p, 1e-6)))
            to = tok.get("offsets") or {}
            w0, w1 = _ms(to.get("from")), _ms(to.get("to"))
            if w0 is not None and w1 is not None:
                words.append(types.SimpleNamespace(start=w0, end=max(w0, w1), word=t, probability=p))
        raw = text.strip().encode("utf-8")
        out.append(types.SimpleNamespace(start=a, end=max(a, b), text=text, words=words,
                                         avg_logprob=(sum(lps) / len(lps)) if lps else None, no_speech_prob=None,
                                         compression_ratio=(len(raw) / len(zlib.compress(raw))) if raw else None))
    return out


def _ms(v):
    return float(v) / 1000.0 if isinstance(v, (int, float)) else None


def _wav_seconds(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (OSError, wave.Error, EOFError):
        return None


def _write_wav(path, samples):
    """float32(-1〜1)のサンプル → 16kHz・モノラル・16bit の wav(numpy は呼ぶ側の配列のメソッドだけ使う)"""
    import array
    try:
        ints = (samples.clip(-1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    except AttributeError:   # numpy でない一覧(テスト)
        ints = array.array("h", [int(max(-1.0, min(1.0, x)) * 32767) for x in samples]).tobytes()
        if sys.byteorder != "little":
            a = array.array("h")
            a.frombytes(ints)
            a.byteswap()
            ints = a.tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(ints)


ENGINES = {FasterWhisper.id: FasterWhisper, WhisperCpp.id: WhisperCpp}


def get(engine_id):
    """エンジンのクラス。知らない名前は ValueError(要求の名前からクラス・パスを作らない = 一覧にあるものだけ)"""
    cls = ENGINES.get(str(engine_id or DEFAULT))
    if cls is None:
        raise ValueError("知らない認識エンジンです: %s" % str(engine_id)[:40])
    return cls


def valid(engine_id):
    return str(engine_id or DEFAULT) in ENGINES
