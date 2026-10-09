# -*- coding: utf-8 -*-
"""文字起こしの認識エンジンの口(精度改善の計画 段2。plan/line-b-transcription.md(付録))。

認識ワーカー(worker.py)が読み込むモデルは、ここのエンジンの1つとして作る。
  faster-whisper … 今までのエンジン(CPU / NVIDIA の GPU)。段2-1
  whisper.cpp    … whisper-cli.exe を子プロセスで動かす。AMD の GPU(Vulkan)で large-v3 などを動かす。段2-2
  qwen3-asr      … Qwen3-ASR 0.6B を sherpa-onnx の CPU で動かす(時刻は区切りの中の目安)。段2-3
  llama.cpp      … Qwen3-ASR 1.7B を llama-server(Vulkan)で動かす(同じ区切り方)。段2-3
新しいエンジンは、同じ形のクラスをここに足し、ENGINES に登録する。

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

try:
    from ytt import fsio as _fsio, tools as _tools   # 共通部品(標準ライブラリだけ。serve.py の _load_core が先に見つけてある)
except ImportError:   # このファイルだけを読み込んだとき(tests/test_worker.py の子プロセスなど): ツールの 1 つ上(src/)の共通部品
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from ytt import fsio as _fsio, tools as _tools

DEFAULT = "faster-whisper"
ENGINE_DIR = None   # エンジンの実行ファイル・モデルの置き場所(既定 = 作業データ)。RS2-4a(2026-10-10)に編集の ed_jobs から移した


def engine_home():
    """エンジンの実行ファイル・モデルの置き場所: ENGINE_DIR → 環境変数 TRANSCRIBE_ENGINE_DIR → 作業データ(txenv の DATA_DIR。呼ぶたびに読む)。
    精度を測る道具は serve の DATA_DIR を一時フォルダにするので、本物の作業データを環境変数で渡す(認識ワーカーにも届く)"""
    d = ENGINE_DIR or os.environ.get("TRANSCRIBE_ENGINE_DIR")
    if d:
        return d
    from . import txenv   # このファイルだけを読み込んだとき(パッケージの外)も、先頭の読み込みは止めない
    return txenv.DATA_DIR


def engine_of(spec):
    """指定(spec)の認識エンジンの名前(無ければ既定 = faster-whisper)"""
    return str(spec.get("engine") or DEFAULT)


def env_num(name, default, lo=1, hi=64, cast=int):
    """環境変数 name の数(cast で読む)を lo〜hi に収めて返す。無い・空・読めなければ default(収めない)。
    サーバー側(ed_jobs・ed_speakers)とワーカーの両方が使う(標準ライブラリだけ)"""
    try:
        return max(lo, min(hi, cast(str(os.environ.get(name) or default).strip())))
    except ValueError:
        return default


def is_16k_mono(w):
    """開いた wav(wave.open)が、認識・判別に渡す形(16kHz・モノラル・16bit = ed_jobs.extract_audio が作るもの)か"""
    return w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == 16000


def half_cpu():
    """CPU で動かす認識(whisper.cpp の -t・sherpa-onnx の認識器)のスレッド数: CPU の半分(1〜8)"""
    return max(1, min(8, (os.cpu_count() or 4) // 2))


class EngineError(Exception):
    """エンジンの準備・実行の失敗(理由を画面に出す)。code はサーバーの ApiError の code になる"""

    def __init__(self, code, message, status=500):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class Engine:
    """エンジンの元。id = 記録(recognition.runs の engine)とワーカーへの要求に使う名前、package = 版を読むパッケージ(dist-info)"""
    id = ""
    package = ""
    light = False   # True = 小さいモデル(SenseVoice)。ed_jobs._load_model_local が、別のモデルを読むときも手放さない(主のモデルと一緒に持つ)

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
            m = WhisperModel(name, device=device, compute_type=compute_type, local_files_only=True, **cls.thread_kw(device))
        except MemoryError:
            raise
        except Exception as e:   # 手元に無い(初回)・手元だけでは読めない → 今までどおりネットワークから取る
            if log:
                log.info("手元のファイルだけではモデルを読めないので、ネットワークから取ります: %s(%s)", name, str(e)[:120])
            m = WhisperModel(name, device=device, compute_type=compute_type, **cls.thread_kw(device))
        return cls(name, device, m)

    @staticmethod
    def thread_kw(device):
        """CPU のときのスレッド数。ライブラリの既定は 4。2026-10-04 に測った(small・3.5 分の音声)ら 4 → 8 で 9% 速く、16 は 5% しか伸びず結果の文字が変わったので、
        既定は 8(この PC の P コアの数)。環境変数 TRANSCRIBE_CPU_THREADS で変えられる(0 = ライブラリの既定)。git の履歴(679ff01 以前)の docs/plan/stability-review-2026-10.md の S2"""
        if device != "cpu":
            return {}
        n = env_num("TRANSCRIBE_CPU_THREADS", min(8, os.cpu_count() or 4), lo=0)
        return {"cpu_threads": n} if n > 0 else {}

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
# ↑ whisper.cpp 自身の声の検出(--vad。TRANSCRIBE_WCPP_VAD=1)は 0.65.0(2026-10-09)で消した = 編集はもう取得しない。
#   定数は入口の home/live_tx_worker.py が名前を参照しているので残す(fetch_file の固定の形の例としても test_whispercpp が確かめる)
WCPP_EXE = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
_GPU_LINE = re.compile(r"whisper_backend_init_gpu: (?:using (.+?) backend|no GPU found)")
_PROGRESS = re.compile(r"progress\s*=\s*(\d+)%")
_VK_DEV = re.compile(r"ggml_vulkan: \d+ = ([^|(]+)")


def wcpp_env():
    """whisper-cli の環境変数。RX 7800 XT(AMD のドライバ)では行列コア(KHR_coopmat)の経路で、最初の GPU の計算のときに
    何も出さずに落ちる(終了コード 0xC0000409。2026-10-02 に PC で再現。切ると 40 秒の音声が 6.8 秒で通る)ので、既定で切る。
    環境変数で GGML_VK_DISABLE_COOPMAT を指定していればそれに従う(ドライバが直ったら 0 で試せる)"""
    env = dict(os.environ)
    env.setdefault("GGML_VK_DISABLE_COOPMAT", "1")
    return env


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
        _fsio.unlink_quiet(part)
        raise
    except OSError as e:
        _fsio.unlink_quiet(part)
        raise EngineError("fetch_failed", "%s を取得できませんでした: %s(ネットワークを確かめてください)" % (spec["file"], str(e)[:160]))
    if got != spec["size"] or h.hexdigest() != spec["sha256"]:
        _fsio.unlink_quiet(part)
        raise EngineError("fetch_failed", "取得した %s の中身が想定と違うので使いません(大きさ %d / SHA-256 が一致しない)" % (spec["file"], got))
    _fsio.replace_retry(part, path)
    return path


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


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
              "vad_filter", "vad_parameters", "word_timestamps"]   # hotwords・chunk_length は無い(渡されても使わない)。vad_* は受け取るだけ(0.65.0 から使わない)
    COMMAND = None   # テスト用: [python, 偽の whisper-cli] に差し替える

    @classmethod
    def device_order(cls, pref, cuda_ok):
        return ["cpu"] if pref == "cpu" else ["vulkan"]   # 自動でも GPU が使えないときは CPU にしない(理由を出して止める)

    @classmethod
    def valid_model(cls, name):
        return name in WCPP_MODELS

    @classmethod
    def manifest(cls, data_dir):
        return _fsio.read_json_or(os.path.join(wcpp_bin_dir(data_dir), "build.json"), None, kind=dict)

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
        cmd = list(cls.COMMAND) if cls.COMMAND else [os.path.join(wcpp_bin_dir(data_dir), WCPP_EXE)]
        e = cls(name, device, {"cmd": cmd, "model": model})
        e.gpu_name = ""
        return e

    def params(self):
        return list(self.PARAMS)

    @staticmethod
    def flash_attn():
        """フラッシュアテンション(whisper-cli v1.9.4 の既定はオン)を使うか。既定は使わない(-nfa): RX 7800 XT の Vulkan でオンにすると、
        配信の音声で行の時刻が 1 秒単位に丸まり(5.0–6.0, 6.0–7.0 …。行の境界の 29% が整数秒 → 切ると 12%)、同じ文字の繰り返しの行と
        音声の長さより後ろの行が出た(40 秒の評価用で 53 行 → 22 行)。ショート 2 本の CER も 9.3% → 4.9%。代わりに 2 割ほど遅い(2026-10-04 に測った)。
        ドライバが直ったら環境変数 TRANSCRIBE_WCPP_FA=1 で試せる"""
        return os.environ.get("TRANSCRIBE_WCPP_FA") == "1"

    def args(self, wav, out_base, kw):
        """whisper-cli の引数(応答ファイルの行)。kw は faster-whisper の引数の名前(ed_jobs.whisper_kwargs が作る)。
        vad_filter・vad_parameters は使わない(whisper.cpp 自身の声の検出 --vad は、声の所をつないで認識するので評価用の音声で文字が大きく抜けた
        = CER 36% → 80%。2026-10-02。測るときだけの TRANSCRIBE_WCPP_VAD=1 は 0.65.0 で消した)。音声の全体を認識する"""
        a = ["-m", _ascii_path(self.model["model"]), "-f", _ascii_path(wav), "-ojf", "-of", _ascii_path(out_base), "-pp",
             "-t", str(half_cpu()), "-l", str(kw.get("language") or "auto"), "-bs", str(int(kw.get("beam_size") or 5))]
        if kw.get("condition_on_previous_text") is False:
            a += ["-mc", "0"]   # 前の文を文脈にしない(faster-whisper と同じ)。注意: whisper.cpp は -mc 0 だと --prompt(用語集のヒント)も使わない(10-08 の測定。ヒントで精度は上がらなかったので -mc 0 のまま。画面の #glossDev で案内)
        if not self.flash_attn():
            a += ["-nfa"]
        if self.device == "cpu":
            a += ["-ng"]
        if kw.get("temperature") == 0.0:
            a += ["-tp", "0", "-nf"]   # 温度のやり直しをしない(精度を比べる道具の --temp0)
        if kw.get("no_speech_threshold") is not None:
            a += ["-nth", "%g" % float(kw["no_speech_threshold"])]
        prompt = re.sub(r"[\r\n]+", " ", str(kw.get("initial_prompt") or "")).strip()
        if prompt:
            a += ["--prompt", prompt]
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
            # duration_after_vad = None(声の検出をしない = 分からない。サーバーの「捨てすぎたら緩める」は見ない)。
            # Silero の声の区間の外の行を捨てる TRANSCRIBE_WCPP_SPEECH_FILTER=1 は 0.65.0 で消した(評価用 18 本で 27.0% → 33.8% に悪化)
            info = types.SimpleNamespace(language=(data.get("result") or {}).get("language") or kw.get("language"),
                                         duration=duration, duration_after_vad=None)
            return iter(segs), info
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _run(self, cmd):
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_tools.no_window_flags(), env=wcpp_env())
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
        """GPU(Vulkan)を頼んだのに使っていなければ止める(黙って CPU で動いた結果を「GPU」として残さない)。
        声の検出(--vad)のモデルは CPU で動き、そのときも「no GPU found」の行が出るので、認識のモデルの「using … backend」を探す
        (編集は 0.65.0 から --vad を渡さないが、ほかの版の whisper-cli や入口の live_tx_worker の出力でも同じ見方でよいので残す)"""
        used = None
        for s in log:
            m = _GPU_LINE.search(s)
            if m and (used is None or m.group(1)):
                used = m.group(1) or used or ""
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
    """float32(-1〜1)のサンプル → 16kHz・モノラル・16bit の wav(path はファイルのパスか書ける入れ物。numpy は呼ぶ側の配列のメソッドだけ使う)"""
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


# ---------------------------------------------------------------- Qwen3-ASR(段2-3)
# 公開の比較で日本語に強い Qwen3-ASR を、入っている sherpa-onnx(1.13.8)の CPU で動かす(新しい依存は足さない)。
# モデルは sherpa-onnx の公式の配布(0.6B・int8)を URL・大きさ・SHA-256 固定で取る(計画の 7)。1.7B は sherpa の形式の配布が無い。
# 時刻を出さないモデルなので、音の小さい所で 12〜28 秒の区切りにして区切りごとに認識し、文の区切りで行にする(行の時刻は区切りの中で字数に比例させた目安)。
QWEN3_MODELS = {   # 2026-10-02 に GitHub の API で大きさと SHA-256 を確かめた
    "qwen3-asr-0.6b": {"dir": "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25", "file": "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25.tar.bz2",
                       "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25.tar.bz2",
                       "size": 878702423, "sha256": "393f8a14e2f5fb96746aaab342997a40641001fbd5bf9592a080a8329178ee96",
                       "parts": ("conv_frontend.onnx", "encoder.int8.onnx", "decoder.int8.onnx", "tokenizer/vocab.json", "tokenizer/merges.txt")},
}
Q3_FRAME = 0.05                 # 音の大きさを見る1コマ(秒)
Q3_MIN, Q3_MAX = 12.0, 28.0     # 区切りの長さ(秒)。28 秒を超えると 1 回の出力の上限(トークン)に近づく
Q3_SILENT = 0.003               # 区切りの中の最大の音の大きさ(RMS)がこれ未満なら認識しない(約 -50 dBFS。無音で文を作らせない)
Q3_SENT = re.compile(r"(?<=[。！？!?])")
Q3_TOKENS_PER_SEC, Q3_TOKENS_MIN = 12, 32   # 1 回の出力の上限(区切りの秒 × これ。日本語の早口で 1 秒 8〜10 字)。繰り返しが止まらないとき長く続けない
Q3_REPEAT_KEEP = 4              # 同じ並び(1〜10 字)が続くとき、残す回数(「OKOKOKOK」は人の行にもあるので 0 にはしない)
Q3_LANG = {"ja": "Japanese", "en": "English", "zh": "Chinese", "ko": "Korean"}   # Qwen3-ASR の言語の名前。自動判定に任せると日本語の区切りが中国語になった
_Q3_SPECIAL = re.compile(r"<\|")   # 特別なトークン(<|endoftext|> など)から先は捨てる(用語のヒントを区切りごとに渡すと、その先に関係ない英文が続いた)


def q3_model_dir(data_dir):
    return os.path.join(data_dir, "models", "qwen3asr")


def q3_chunks(rms, frame=Q3_FRAME, lo=Q3_MIN, hi=Q3_MAX):
    """音の大きさの並び(1コマ = frame 秒)→ 区切り [(始めのコマ, 終わりのコマ)]。残りが hi 秒以下ならそこまで、
    それより長ければ lo〜hi 秒の間で、前後 0.3 秒をならした音のいちばん小さい所で切る(声の途中で切りにくくする)"""
    n = len(rms)
    a_lo, a_hi, w = int(round(lo / frame)), int(round(hi / frame)), max(1, int(round(0.15 / frame)))
    out, s = [], 0
    while s < n:
        if n - s <= a_hi:
            out.append((s, n))
            break
        best, cut = None, s + a_hi
        for i in range(s + a_lo, s + a_hi + 1):
            seg = rms[max(0, i - w):i + w + 1]
            v = sum(seg) / len(seg)
            if best is None or v < best:
                best, cut = v, i
        out.append((s, cut))
        s = cut
    return out


def q3_rows(text, a, b, max_chars=16, voiced=None):
    """区切り(a〜b 秒)の文章 → 行 [(始め, 終わり, 文)]。文の終わり(。？！)で分け、max_chars の 2 倍を超える文は「、」でも分ける。
    時刻は目安(モデルが時刻を出さないため): voiced(a からの1コマ = Q3_FRAME 秒ごとに、声がありそうか)があれば、
    声のあるコマの数を字数に比例させて割り振る(間の静かな所に行をかけない)。無ければ a〜b を字数に比例させる"""
    text = q3_squash(_Q3_SPECIAL.split(str(text or ""), 1)[0].strip())
    parts = []
    for sent in (x.strip() for x in Q3_SENT.split(text)):
        if not sent:
            continue
        if len(sent) <= max_chars * 2:
            parts.append(sent)
            continue
        cur = ""
        for piece in re.split(r"(?<=[、,])", sent):
            if cur and len(cur) + len(piece) > max_chars * 2:
                parts.append(cur)
                cur = ""
            cur += piece
        if cur:
            parts.append(cur)
    total = sum(len(p) for p in parts)
    if not total:
        return []
    on = [i for i, v in enumerate(voiced or []) if v]
    out, k = [], 0
    for p in parts:
        k0, k = k, k + len(p)
        if on:   # この行の字の範囲 → 声のあるコマの範囲(少なくとも1コマ)
            i0 = min(len(on) - 1, int(len(on) * k0 / total))
            i1 = max(i0, min(len(on) - 1, int(math.ceil(len(on) * k / total)) - 1))
            t0, t1 = a + on[i0] * Q3_FRAME, a + (on[i1] + 1) * Q3_FRAME
        else:
            t0, t1 = a + (b - a) * k0 / total, a + (b - a) * k / total
        out.append((round(t0, 3), round(min(b, t1), 3), p))
    return out


def q3_squash(text, keep=Q3_REPEAT_KEEP):
    """同じ並び(1〜10 字)が keep 回を超えて続く所を keep 回にする(「过来，来过来，来…」のような止まらない繰り返し)"""
    for n in range(1, 11):
        text = re.sub(r"(.{%d})\1{%d,}" % (n, keep), lambda m: m.group(1) * keep, text, flags=re.S)
    return text


def q3_floor(rms):
    """声がありそうなコマの下限: 区切りの中の静かな側(下から 20%)の音の大きさの 2 倍か、最大の 5% の大きいほう(BGM が鳴り続ける配信でも、話していない所を分ける)"""
    v = sorted(rms)
    if not v:
        return 0.0
    return max(v[int(len(v) * 0.2)] * 2.0, v[-1] * 0.05)


def _safe_extract(tar_path, folder, top):
    """tar.bz2 を folder に展開する。中身は top の下の普通のファイル・フォルダだけ(絶対パス・..・リンクがあれば展開しない)"""
    import tarfile
    root = os.path.realpath(folder)
    with tarfile.open(tar_path, "r:bz2") as t:
        members = t.getmembers()
        for m in members:
            name = m.name.replace("\\", "/")
            dest = os.path.realpath(os.path.join(root, name))
            if (not (m.isfile() or m.isdir()) or name.startswith("/") or ".." in name.split("/")
                    or not (name == top or name.startswith(top + "/")) or not dest.startswith(root + os.sep)):
                raise EngineError("fetch_failed", "モデルの圧縮ファイルの中身が想定と違うので使いません: %s" % name[:80])
        t.extractall(root, members=members)


def _read_16k(audio, what):
    """wav のパス(16kHz・モノラル・16bit)か float32 のサンプル → numpy の float32。認識ワーカーの中だけで呼ぶ"""
    import numpy as np
    if isinstance(audio, str):
        with wave.open(audio, "rb") as w:
            if not is_16k_mono(w):
                raise EngineError("engine_failed", "%s に渡す音声の形が想定と違います(16kHz・モノラル・16bit)" % what)
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return np.asarray(audio, dtype=np.float32)


def _frame_rms(x):
    """float32 のサンプル → Q3_FRAME 秒の 1 コマごとの音の大きさ(RMS)の並び(最後の半端なコマも 1 コマ)。認識ワーカーの中だけで呼ぶ(numpy)"""
    import numpy as np
    f = int(16000 * Q3_FRAME)
    nf = len(x) // f + (1 if len(x) % f else 0)
    return [float(np.sqrt(np.mean(np.square(x[i * f:(i + 1) * f])))) if len(x[i * f:(i + 1) * f]) else 0.0 for i in range(nf)]


def _ensure_tar_model(spec, folder, log, hooks):
    """sherpa-onnx の公式の tar.bz2 のモデル(spec = dir・parts・url・size・sha256)を folder に用意して、そのフォルダを返す。
    parts がそろっていれば何もしない。無ければ取得(fetch_file)→ 展開(_safe_extract)→ 圧縮ファイルを消す → そろったか確かめる"""
    mdir = os.path.join(folder, spec["dir"])
    if not all(os.path.isfile(os.path.join(mdir, p)) for p in spec["parts"]):
        tar = fetch_file(spec, folder, log, hooks.get("cancelled"), hooks.get("download"))
        _safe_extract(tar, folder, spec["dir"])
        _fsio.unlink_quiet(tar)
        if not all(os.path.isfile(os.path.join(mdir, p)) for p in spec["parts"]):
            raise EngineError("fetch_failed", "モデルのファイルがそろいませんでした: %s" % spec["dir"])
    return mdir


def _need_sherpa(setup):
    """sherpa-onnx が入っていなければ EngineError(setup = 入れ方の案内の .bat の名前)"""
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        raise EngineError("engine_missing", "sherpa-onnx が入っていません(setup\\%s を実行してください)" % setup, 400)


class _Qwen3Chunked(Engine):
    """時刻を出さない(または区切りごとに読む)エンジンの共通部分(Qwen3-ASR の 2 つと SenseVoice): 音の小さい所で区切り(q3_chunks)、
    無音の区切りは読まず、区切りの中の行は _chunk_rows で作る(Qwen3 = _decode の文章 → q3_rows / SenseVoice = トークンの時刻 → sv_rows)。
    自信の度合いを出さないので avg_logprob は無い。温度は 0 相当(faster-whisper の温度のやり直しは使わない)"""
    PARAMS = ["hotwords", "language", "vad_filter", "vad_parameters", "word_timestamps"]   # language は区切りごとに指定・vad と単語の時刻は受け取るだけ
    DEFAULT_MODEL = ""
    WHAT = "Qwen3-ASR"

    def params(self):
        return list(self.PARAMS)

    def _decode(self, samples, lang, hot, max_tokens):
        raise NotImplementedError

    def _setup(self, kw):
        """区切りを読む前に 1 回 -> (情報の language, 区切りごとに _chunk_rows へ渡すもの)。Qwen3 = 言語の名前とヒントの語"""
        hot = ",".join(t.strip() for t in str(kw.get("hotwords") or "").split(",") if t.strip())
        return kw.get("language") or "ja", (Q3_LANG.get(str(kw.get("language") or ""), ""), hot)

    def _chunk_rows(self, x, c0, c1, rms, ctx):
        """区切り [c0, c1)(コマ)の行 [(始め, 終わり, 文字)](音声の頭からの秒)。Qwen3: 文章にして、声のあるコマに字数を比例させて割り振る"""
        f = int(16000 * Q3_FRAME)
        lang, hot = ctx
        text = self._decode(x[c0 * f:c1 * f], lang, hot, max(Q3_TOKENS_MIN, int((c1 - c0) * Q3_FRAME * Q3_TOKENS_PER_SEC)))
        floor = q3_floor(rms[c0:c1])
        return q3_rows(text, c0 * Q3_FRAME, c1 * Q3_FRAME, voiced=[v > floor for v in rms[c0:c1]])

    def transcribe(self, audio, **kw):
        x = _read_16k(audio, self.WHAT)
        rms = _frame_rms(x)
        chunks = q3_chunks(rms)
        language, ctx = self._setup(kw)
        info = types.SimpleNamespace(language=language, duration=len(x) / 16000.0, duration_after_vad=None)

        def gen():
            for n, (c0, c1) in enumerate(chunks):
                if self._cancelled():
                    raise EngineError("cancelled", "中止しました")
                self._progress(min(0.99, n / max(1, len(chunks))))
                if max(rms[c0:c1] or [0.0]) < Q3_SILENT:
                    continue
                for t0, t1, line in self._chunk_rows(x, c0, c1, rms, ctx):
                    raw = line.encode("utf-8")
                    yield types.SimpleNamespace(start=t0, end=t1, text=line, words=[], avg_logprob=None, no_speech_prob=None,
                                                compression_ratio=len(raw) / len(zlib.compress(raw)))
        return gen(), info


class Qwen3Asr(_Qwen3Chunked):
    """Qwen3-ASR 0.6B(sherpa-onnx・CPU)。用語のヒント(hotwords)は認識器を作るときに渡す(区切りごとに渡すと崩れた)"""
    id = "qwen3-asr"
    package = "sherpa-onnx"
    DEFAULT_MODEL = "qwen3-asr-0.6b"

    @classmethod
    def device_order(cls, pref, cuda_ok):
        return ["cpu"]   # AMD の GPU は onnxruntime の対象外(sherpa-onnx の provider は cpu / cuda)

    @classmethod
    def valid_model(cls, name):
        return name in QWEN3_MODELS

    @classmethod
    def create(cls, name, device, compute_type, log=None, data_dir=None, hooks=None):
        spec = QWEN3_MODELS.get(name)
        if spec is None:
            raise EngineError("bad_model", "Qwen3-ASR で使えないモデルです: %s(使えるのは %s)" % (str(name)[:40], "・".join(QWEN3_MODELS)), 400)
        _need_sherpa("install.bat")
        mdir = _ensure_tar_model(spec, q3_model_dir(data_dir), log, hooks or {})
        e = cls(name, device, {"dir": mdir, "rec": {}})
        try:
            e._recognizer("")   # 読み込めるかをここで確かめる
        except RuntimeError as ex:   # 同じファイルでもまれに読み込みが失敗した(2026-10-02)ので1回だけやり直す。CPU を替えたあと(10-04)も、
            # 一時的な失敗(ファイルのロック・ドライバ)への備えとして残す。本物の失敗は2回目でそのまま出る
            if log:
                log.warning("Qwen3-ASR の読み込みをやり直します: %s", str(ex)[:160])
            e.model["rec"].clear()
            e._recognizer("")
        return e

    def _recognizer(self, hotwords):
        rec = self.model["rec"]
        if hotwords not in rec:
            import sherpa_onnx
            rec.clear()   # ヒントの違う認識器は1つだけ持つ(メモリを積み上げない)
            d = self.model["dir"]
            rec[hotwords] = sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
                conv_frontend=os.path.join(d, "conv_frontend.onnx"), encoder=os.path.join(d, "encoder.int8.onnx"),
                decoder=os.path.join(d, "decoder.int8.onnx"), tokenizer=os.path.join(d, "tokenizer"),
                num_threads=half_cpu(), max_new_tokens=512, max_total_len=1536, hotwords=hotwords)
        return rec[hotwords]

    def _decode(self, samples, lang, hot, max_tokens):
        rec = self._recognizer(hot)
        s = rec.create_stream()
        if lang:
            s.set_option("language", lang)   # 「language Japanese」をモデルへの指示に入れる(sherpa-onnx の Qwen3-ASR の実装)
        s.set_option("max_new_tokens", str(max_tokens))
        s.accept_waveform(16000, samples)
        rec.decode_stream(s)
        return s.result.text


# ---- llama.cpp(Vulkan)で Qwen3-ASR 1.7B(段2-3。2026-10-02)
# 実行ファイルは公式の配布(win-vulkan-x64 の zip)を URL・大きさ・SHA-256 固定で取る(2026-10-02 ユーザー決定「llama.cpp は取得してよい」)。
# llama-server を 127.0.0.1 のあいているポートで1つ起動し、区切りごとに音声を送る(コマンドを毎回起動すると、そのたびにモデルを読む)。
# server には毎回作る合言葉(--api-key)を付ける(付けないと同じ PC のブラウザのページから呼べる = llama.cpp は CORS をすべて許す)。
# 認識ワーカーが落ちても server が残らないよう、Windows ではジョブオブジェクト(閉じたら中のプロセスを終わらせる)に入れる。
LLAMA_CPP = {"version": "b11326", "file": "llama-b11326-bin-win-vulkan-x64.zip", "size": 33208182,
             "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11326/llama-b11326-bin-win-vulkan-x64.zip",
             "sha256": "fcea764f150fa7e6a915376628a1639042d4fb12ea52190cb3a7ce84c0ac166e"}
_GGUF = "https://huggingface.co/ggml-org/Qwen3-ASR-1.7B-GGUF/resolve/main/"
LLAMA_MODELS = {   # 2026-10-02 に Hugging Face の API で大きさと SHA-256 を確かめた
    "qwen3-asr-1.7b": {"model": {"file": "Qwen3-ASR-1.7B-Q8_0.gguf", "url": _GGUF + "Qwen3-ASR-1.7B-Q8_0.gguf", "size": 2165034944,
                                 "sha256": "58e22d0532d4eacaf034cfac17a6fed159f37c41390c710186783be439d1fc57"},
                       "mmproj": {"file": "mmproj-Qwen3-ASR-1.7B-Q8_0.gguf", "url": _GGUF + "mmproj-Qwen3-ASR-1.7B-Q8_0.gguf", "size": 355709344,
                                  "sha256": "46c1d533af3f354ceb37ce855dbceff7da7fa7cf1e6a523df3b13440bd164c0d"}},
}
LLAMA_EXE = "llama-server.exe" if os.name == "nt" else "llama-server"
# 文字の LLM(提案 P18 の LLM の後処理 = ed_llm。2026-10-09 に Hugging Face の API で大きさと SHA-256 を確かめた・Apache-2.0)。
# 同じ llama-server を mmproj なしで起動する(tx_engines.LlamaText)。置き場所は作業データの models/llm-gguf/(Qwen3-ASR の qwen3asr-gguf にそろえた)
LLAMA_TEXT_MODELS = {
    "qwen3-8b": {"model": {"file": "Qwen3-8B-Q4_K_M.gguf", "size": 5027783488, "sha256": "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
                           "url": "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/7c41481f57cb95916b40956ab2f0b139b296d974/Qwen3-8B-Q4_K_M.gguf"}},
}
# ---------- SenseVoice(sherpa-onnx・CPU)。文字の少ない行を別の読みで埋める 2 つ目のエンジン(ed_fill。10-08 の実験ループの A・D。編集 0.60.0) ----------
# モデルは sherpa-onnx の公式の配布(SenseVoice-small int8・2024-07-17)を URL・大きさ・SHA-256 固定で取る(2026-10-08 に確かめた。2025-09-09 の版は sherpa-onnx 1.13.8 で壊れた出力)。
# ライセンス: FunASR MODEL_LICENSE(商用可・出典とモデル名の表示)。トークンごとの時刻が出るので、SV_GAP 秒以上の間・文末・SV_MAX_CHARS で行にする(終わりは目安)
SENSE_VOICE_MODELS = {
    "sense-voice-small": {"dir": "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17", "file": "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2",
                          "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2",
                          "size": 163002883, "sha256": "7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e", "parts": ("model.int8.onnx", "tokens.txt")},
}
SV_GAP, SV_MAX_CHARS = 1.0, 40     # トークンの時刻で行に分ける: この秒以上の間・1 行の最大文字数
SV_LANGS = ("ja", "en", "zh", "ko", "yue", "auto")


def sv_model_dir(data_dir):
    return os.path.join(data_dir, "models", "sensevoice")


def sv_rows(tokens, stamps, a, b, gap=SV_GAP, max_chars=SV_MAX_CHARS):
    """SenseVoice のトークンと時刻(区切りの頭からの秒)→ [(始め, 終わり, 文字)](区切り [a, b] の中の絶対の秒)。
    特別なトークン(<|ja|> など)は捨て、gap 秒以上の間・max_chars・文末(。？！)で行を分ける。終わりはトークンの時刻 + 0.2 秒(+0.3 の余白。b を超えない)"""
    rows, cur, cs, ce = [], "", None, None
    for tk, t in zip(tokens, stamps):
        tk = str(tk).replace("▁", " ")
        if tk.startswith("<|"):
            continue
        if cur and (t - ce > gap or len(cur) >= max_chars or cur[-1] in "。？！?!"):
            rows.append((cs, ce, cur))
            cur, cs = "", None
        if cs is None:
            cs = t
        cur += tk
        ce = t + 0.2
    if cur:
        rows.append((cs, ce, cur))
    out = []
    for s0, e0, line in rows:
        line = q3_squash(line.strip())
        if line:
            out.append((a + s0, min(b, a + e0 + 0.3), line))
    return out


class SenseVoice(_Qwen3Chunked):
    """SenseVoice-small(sherpa-onnx・CPU・int8)。文字の少ない行の窓・名簿の呼び名の確かめに使う 2 つ目のエンジン(ed_fill)。小さいので主のモデルと一緒に持つ(light)。
    区切り方は Qwen3 と同じ(_Qwen3Chunked)。区切りの中の行はトークンの時刻で作る(_chunk_rows。時刻が無ければ Qwen3 と同じ割り振り)。
    FAKE_TEXT(テスト用)が文字列なら、音声を読まずにその文字を 1 行にして返す(空なら行なし。認識ワーカーの疑似 eval/fake/fake_worker が環境変数 TRANSCRIBE_FAKE_FILL から入れる)"""
    id = "sense-voice"
    package = "sherpa-onnx"
    light = True
    PARAMS = ["language", "vad_filter", "vad_parameters", "word_timestamps"]   # language 以外は受け取るだけ
    DEFAULT_MODEL = "sense-voice-small"
    WHAT = "SenseVoice"
    FAKE_TEXT = None

    @classmethod
    def device_order(cls, pref, cuda_ok):
        return ["cpu"]   # onnxruntime の CPU(AMD の GPU は対象外)

    @classmethod
    def valid_model(cls, name):
        return name in SENSE_VOICE_MODELS

    @classmethod
    def create(cls, name, device, compute_type, log=None, data_dir=None, hooks=None):
        spec = SENSE_VOICE_MODELS.get(name)
        if spec is None:
            raise EngineError("bad_model", "SenseVoice で使えないモデルです: %s(使えるのは %s)" % (str(name)[:40], "・".join(SENSE_VOICE_MODELS)), 400)
        if cls.FAKE_TEXT is not None:
            return cls(name, "cpu", {"fake": cls.FAKE_TEXT})
        _need_sherpa("install-diarize.bat")
        e = cls(name, "cpu", {"dir": _ensure_tar_model(spec, sv_model_dir(data_dir), log, hooks or {}), "rec": {}})
        e._recognizer("ja")   # 読み込めるかをここで確かめる
        return e

    def _recognizer(self, lang):
        """言語ごとの認識器(1 つだけ持つ)"""
        rec = self.model["rec"]
        if lang not in rec:
            import sherpa_onnx
            rec.clear()
            d = self.model["dir"]
            rec[lang] = sherpa_onnx.OfflineRecognizer.from_sense_voice(model=os.path.join(d, "model.int8.onnx"), tokens=os.path.join(d, "tokens.txt"),
                                                                       num_threads=half_cpu(), language=lang, use_itn=False)
        return rec[lang]

    @staticmethod
    def _lang(kw):
        lang = str(kw.get("language") or "ja")
        return lang if lang in SV_LANGS else "auto"

    def transcribe(self, audio, **kw):
        if "fake" in self.model:
            return self._fake(audio, self._lang(kw))
        return super().transcribe(audio, **kw)

    def _setup(self, kw):
        """言語ごとの認識器(区切りを読む前に 1 回作る)"""
        lang = self._lang(kw)
        return lang, self._recognizer(lang)

    def _chunk_rows(self, x, c0, c1, rms, rec):
        f = int(16000 * Q3_FRAME)
        st = rec.create_stream()
        st.accept_waveform(16000, x[c0 * f:c1 * f])
        rec.decode_stream(st)
        r = st.result
        a0, b0 = c0 * Q3_FRAME, c1 * Q3_FRAME
        toks, ts = list(getattr(r, "tokens", None) or []), list(getattr(r, "timestamps", None) or [])
        if toks and len(ts) == len(toks):
            return sv_rows(toks, ts, a0, b0)
        floor = q3_floor(rms[c0:c1])   # 時刻が無ければ Qwen3 と同じ割り振り(声のあるコマに字数を比例)
        return q3_rows(q3_squash(str(r.text or "")), a0, b0, voiced=[v > floor for v in rms[c0:c1]])

    def _fake(self, audio, lang):
        """テスト用(FAKE_TEXT): 音声の長さ全体に 1 行(空なら行なし)"""
        dur = _wav_seconds(audio) if isinstance(audio, str) else len(audio) / 16000.0
        info = types.SimpleNamespace(language=lang, duration=dur, duration_after_vad=None)
        text = self.model["fake"]
        segs = [types.SimpleNamespace(start=0.0, end=dur, text=text, words=[], avg_logprob=None, no_speech_prob=None, compression_ratio=1.0)] if text else []
        return iter(segs), info


# 24 にすると、当時の PC(13900KF)では起動の途中でよく落ちた(2026-10-02)。GPU に載せるので CPU のスレッドはほぼ効かず、既定は 8 のまま。
# CPU を替えたので(10-04)環境変数 TRANSCRIBE_LLAMA_THREADS で変えられるようにした
LLAMA_THREADS = env_num("TRANSCRIBE_LLAMA_THREADS", 8)
LLAMA_START_SEC = 180    # 起動(モデルの読み込み)を待つ上限
_ASR_TEXT = "<asr_text>"


def llama_bin_dir(data_dir):
    return os.path.join(data_dir, "bin", "llama.cpp-%s-vulkan" % LLAMA_CPP["version"])


def _safe_unzip(zip_path, folder):
    """zip を folder に展開する(絶対パス・.. を含む名前があれば展開しない)"""
    import zipfile
    root = os.path.realpath(folder)
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            name = n.replace("\\", "/")
            dest = os.path.realpath(os.path.join(root, name))
            if name.startswith("/") or ".." in name.split("/") or ":" in name or not (dest == root or dest.startswith(root + os.sep)):
                raise EngineError("fetch_failed", "llama.cpp の圧縮ファイルの中身が想定と違うので使いません: %s" % name[:80])
        z.extractall(root)


def q3_parse(content):
    """llama-server の答え「language Japanese<asr_text>文章」→ (言語, 文章)。<asr_text> が無ければ全体を文章とみる"""
    c = str(content or "")
    if _ASR_TEXT in c:
        head, text = c.rsplit(_ASR_TEXT, 1)
        m = re.search(r"language\s+(\S+)\s*$", head.strip())
        return (m.group(1) if m else ""), text.strip()
    return "", c.strip()


def _wav_bytes(samples):
    import io as _io
    buf = _io.BytesIO()
    _write_wav(buf, samples)
    return buf.getvalue()


class LlamaQwen3(_Qwen3Chunked):
    """Qwen3-ASR 1.7B を llama.cpp(llama-server・Vulkan)で。機器は vulkan(AMD などの GPU)か cpu。
    用語のヒントは system の文(Qwen3-ASR の文脈)に入れる。言語は答えの頭「language Japanese<asr_text>」を先に書いておく"""
    id = "llama.cpp"
    package = ""
    DEFAULT_MODEL = "qwen3-asr-1.7b"
    WHAT = "llama.cpp"
    COMMAND = None   # テスト用: 偽の server に差し替える
    MODELS = LLAMA_MODELS          # モデルの表(子クラス LlamaText は文字の LLM の表)
    MODEL_SUBDIR = "qwen3asr-gguf"  # 作業データの models/ の下の置き場所

    @classmethod
    def device_order(cls, pref, cuda_ok):
        return ["cpu"] if pref == "cpu" else ["vulkan"]

    @classmethod
    def valid_model(cls, name):
        return name in cls.MODELS

    @classmethod
    def version(cls, data_dir=None):
        return LLAMA_CPP["version"]

    @classmethod
    def create(cls, name, device, compute_type, log=None, data_dir=None, hooks=None):
        spec = cls.MODELS.get(name)
        if spec is None:
            raise EngineError("bad_model", "llama.cpp で使えないモデルです: %s(使えるのは %s)" % (str(name)[:40], "・".join(cls.MODELS)), 400)
        hooks = hooks or {}
        bdir = llama_bin_dir(data_dir)
        if not cls.COMMAND and not os.path.isfile(os.path.join(bdir, LLAMA_EXE)):
            z = fetch_file(LLAMA_CPP, os.path.dirname(bdir), log, hooks.get("cancelled"))
            os.makedirs(bdir, exist_ok=True)
            _safe_unzip(z, bdir)
            _fsio.unlink_quiet(z)
        mdir = os.path.join(data_dir, "models", cls.MODEL_SUBDIR)
        model = fetch_file(spec["model"], mdir, log, hooks.get("cancelled"), hooks.get("download"))
        mmproj = fetch_file(spec["mmproj"], mdir, log, hooks.get("cancelled")) if "mmproj" in spec else None   # 文字の LLM は音声の部品(mmproj)なし
        e = cls(name, device, {"cmd": list(cls.COMMAND) if cls.COMMAND else [os.path.join(bdir, LLAMA_EXE)], "model": model, "mmproj": mmproj})
        e.proc = e.job = e.errlog = None
        e.gpu_name = ""
        try:
            e._start(hooks.get("cancelled"))
        except EngineError as ex:   # 起動の途中でまれに落ちた(2026-10-02。当時の CPU)ので1回だけやり直す。一時的な失敗(GPU のドライバ)への備えとして残す
            if ex.code in ("cancelled", "gpu_failed"):
                raise
            if log:
                log.warning("llama-server の起動をやり直します: %s", ex.message[:160])
            e._start(hooks.get("cancelled"))
        return e

    def _start(self, cancelled=None):
        import secrets
        import socket
        import urllib.request
        self.close()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.key = secrets.token_hex(16)
        args = ["-m", self.model["model"]] + (["--mmproj", self.model["mmproj"]] if self.model.get("mmproj") else []) + [
                "--host", "127.0.0.1", "--port", str(self.port),
                "--api-key", self.key, "--no-webui", "-c", "4096", "-np", "1", "-t", str(LLAMA_THREADS), "-tb", str(LLAMA_THREADS),
                "-ngl", "0" if self.device == "cpu" else "99", "-lv", "4"]   # -lv 4: GPU に載ったかの行(offloaded n/m layers to GPU)を記録に出す
        self.errlog = tempfile.NamedTemporaryFile(prefix="llama-server-", suffix=".log", delete=False)
        env = wcpp_env()   # GGML_VK_DISABLE_COOPMAT=1(whisper.cpp と同じ ggml の Vulkan。RX 7800 XT で行列コアの経路が落ちる)
        if self.device == "cpu":
            env["GGML_VK_VISIBLE_DEVICES"] = ""
        self.proc = subprocess.Popen(self.model["cmd"] + args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.errlog,
                                     creationflags=_tools.no_window_flags(), env=env)
        self.job = _tools.KillJob()   # ワーカーが落ちても server が残らない(閉じたら中を終わらせるジョブ。close() で閉じる)
        self.job.add(self.proc)
        t0 = time.monotonic()
        while True:
            if cancelled and cancelled():
                self.close()
                raise EngineError("cancelled", "中止しました")
            rc = self.proc.poll()
            if rc is not None:
                tail = self._log_tail()
                self.close()
                raise EngineError("engine_failed", "llama-server が起動の途中で止まりました(終了コード %s): %s" % (rc, tail))
            try:
                req = urllib.request.Request("http://127.0.0.1:%d/health" % self.port, headers={"Authorization": "Bearer " + self.key})
                with urllib.request.urlopen(req, timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() - t0 > LLAMA_START_SEC:
                self.close()
                raise EngineError("engine_failed", "llama-server の起動が %d 秒で終わりませんでした" % LLAMA_START_SEC)
            time.sleep(0.3)
        self._check_gpu()

    def _log_text(self):
        try:
            with open(self.errlog.name, "rb") as f:
                return f.read().decode("utf-8", errors="replace")
        except (OSError, AttributeError):
            return ""

    def _log_tail(self, n=6):
        lines = [re.sub(r"\x1b\[[0-9;]*m", "", x) for x in self._log_text().splitlines() if x.strip()]   # 色の制御文字を除く
        return " / ".join(lines[-n:])[-300:]

    def _check_gpu(self):
        """GPU を頼んだのに Vulkan に載っていなければ止める(黙って CPU で動いた結果を「GPU」として残さない)"""
        if self.device != "vulkan":
            return
        log = self._log_text()
        m = re.search(r"Vulkan\d+ \(([^)]+)\)", log) or re.search(r"Vulkan\d+: ([^(\r\n]+)", log)
        if m:
            self.gpu_name = m.group(1).strip()
        if not re.search(r"offloaded [1-9]\d*/\d+ layers to GPU", log):
            self.close()
            raise EngineError("gpu_failed", "GPU(Vulkan)を使えませんでした。GPU のドライバを確かめるか、処理方式を「CPU」にしてください")

    def close(self):
        p = getattr(self, "proc", None)
        if p is not None and p.poll() is None:
            p.kill()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                pass
        self.proc = None
        j = getattr(self, "job", None)
        if j is not None:
            j.close()
        self.job = None
        el = getattr(self, "errlog", None)
        if el is not None:
            try:
                el.close()
                os.unlink(el.name)
            except OSError:
                pass
        self.errlog = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _retry(self, fn):
        """fn() を呼ぶ。server が落ちていたら(この PC では長い測定の途中で落ちた。2026-10-02)起動し直して1回だけやり直す"""
        try:
            return fn()
        except EngineError as e:
            if e.code != "server_down":
                raise
            self._start(self.hooks.get("cancelled"))
            try:
                return fn()
            except EngineError as e2:
                if e2.code == "server_down":
                    raise EngineError("engine_failed", e2.message)
                raise

    def _decode(self, samples, lang, hot, max_tokens):
        """区切り1つを認識する(server が落ちていたら 1 回だけ起動し直す)"""
        return self._retry(lambda: self._ask(samples, lang, hot, max_tokens))

    def _chat(self, payload):
        """/v1/chat/completions に payload を送る -> 答えの文字(content)。毎回の合言葉を付ける"""
        import urllib.error
        import urllib.request
        if self.proc is None or self.proc.poll() is not None:
            raise EngineError("server_down", "llama-server が止まっています: %s" % self._log_tail())
        req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % self.port, json.dumps(payload).encode("utf-8"),
                                     {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise EngineError("engine_failed", "llama-server が失敗しました(%s): %s" % (e.code, e.read()[:200].decode("utf-8", errors="replace")))
        except OSError as e:
            code = "server_down" if self.proc is None or self.proc.poll() is not None or isinstance(e, ConnectionError) else "engine_failed"
            raise EngineError(code, "llama-server に届きませんでした: %s / %s" % (str(e)[:120], self._log_tail()))
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    def _ask(self, samples, lang, hot, max_tokens):
        import base64
        msgs = []
        if hot:
            msgs.append({"role": "system", "content": hot.replace(",", "、")})
        msgs.append({"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": base64.b64encode(_wav_bytes(samples)).decode("ascii"), "format": "wav"}}]})
        if lang:
            msgs.append({"role": "assistant", "content": "language %s%s" % (lang, _ASR_TEXT)})   # 言語を先に書いておく(自動の判定で中国語にならないように)
        return q3_parse(self._chat({"messages": msgs, "temperature": 0, "max_tokens": int(max_tokens), "cache_prompt": False}))[1]


class LlamaText(LlamaQwen3):
    """文字の LLM(Qwen3-8B Q4_K_M)を同じ llama-server(Vulkan)で。LLM の後処理(提案 P18 = ed_llm)が complete() で聞く。音声は認識しない。
    主の認識のモデルと一緒に持つ(light)= 認識のたびに読み直さない(VRAM 16GB に large-v3 と合わせて約 8GB)。使わなければ認識ワーカーのアイドル終了で手放す。
    FAKE_REPLY(テスト用)が文字列なら、server を起動せずにその文字を答える(認識ワーカーの疑似 eval/fake/fake_worker が環境変数 TRANSCRIBE_FAKE_LLM から入れる)"""
    id = "llama-text"
    DEFAULT_MODEL = "qwen3-8b"
    WHAT = "llama.cpp(文字の LLM)"
    MODELS = LLAMA_TEXT_MODELS
    MODEL_SUBDIR = "llm-gguf"
    PARAMS = []
    light = True
    FAKE_REPLY = None

    @classmethod
    def create(cls, name, device, compute_type, log=None, data_dir=None, hooks=None):
        if cls.FAKE_REPLY is not None:
            if name not in cls.MODELS:
                raise EngineError("bad_model", "文字の LLM で使えないモデルです: %s" % str(name)[:40], 400)
            e = cls(name, device, {"fake": cls.FAKE_REPLY})
            e.proc = e.job = e.errlog = None
            return e
        return super().create(name, device, compute_type, log, data_dir, hooks)

    def transcribe(self, audio, **kw):
        raise EngineError("bad_engine", "文字の LLM は音声を認識しません", 400)

    def complete(self, messages, max_tokens=400):
        """chat の messages -> 答えの文字(温度 0・思考オフ。server が落ちていたら 1 回だけ起動し直す)"""
        if "fake" in self.model:
            return self.model["fake"]
        payload = {"messages": messages, "temperature": 0, "max_tokens": int(max_tokens), "cache_prompt": False,
                   "chat_template_kwargs": {"enable_thinking": False}}
        return self._retry(lambda: self._chat(payload))


ENGINES = {FasterWhisper.id: FasterWhisper, WhisperCpp.id: WhisperCpp, Qwen3Asr.id: Qwen3Asr, LlamaQwen3.id: LlamaQwen3, SenseVoice.id: SenseVoice,
           LlamaText.id: LlamaText}


def get(engine_id):
    """エンジンのクラス。知らない名前は ValueError(要求の名前からクラス・パスを作らない = 一覧にあるものだけ)"""
    cls = ENGINES.get(str(engine_id or DEFAULT))
    if cls is None:
        raise ValueError("知らない認識エンジンです: %s" % str(engine_id)[:40])
    return cls


def valid(engine_id):
    return str(engine_id or DEFAULT) in ENGINES
