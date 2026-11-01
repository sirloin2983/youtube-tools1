# -*- coding: utf-8 -*-
"""文字起こしの本物の通しの下ごしらえ(テストではない)。

- make_voice(): Windows の音声合成で声の見本の wav(16kHz・モノラル)をファイルに書く(音は鳴らさない)。
  日本語の 3 文(1.5 秒と 2.5 秒の間)。3 文目は ffmpeg で声を低くした別の話者。日本語の声が無ければ None
- モデルの場所は読むだけ: faster-whisper は Hugging Face のキャッシュ、whisper.cpp・話者判別は編集の作業データ(ENGINE_HOME)。
  無ければ None を返し、通しのテストは skipUnless で飛ばす(取りに行かせない)
- fetch_read_only()・no_download(): 取得の口の差し替え(同じプロセスの中だけに効く。認識ワーカーの子プロセスには届かない)
"""
import glob
import os
import shutil
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FFMPEG = os.environ.get("YTT_FFMPEG") or shutil.which("ffmpeg")
LINES = ("こんにちは。", "今日は配信に来てくれてありがとう。", "それではゲームを始めます。")
_PS = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$ja = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo } | Where-Object { $_.Culture.Name -eq 'ja-JP' }) | Select-Object -First 1
if (-not $ja) { exit 3 }
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.StartVoice($ja); $p.AppendText($env:V_L0); $p.AppendBreak([TimeSpan]::FromSeconds(1.5)); $p.AppendText($env:V_L1); $p.EndVoice()
$s.SetOutputToWaveFile($env:V_A, $fmt); $s.Speak($p)
$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.StartVoice($ja); $p.AppendText($env:V_L2); $p.EndVoice()
$s.SetOutputToWaveFile($env:V_B, $fmt); $s.Speak($p)
$s.Dispose()
'''
LEAD = 1.0           # 頭の無音(秒。範囲の開始を足す確かめに使う)
GAP = 2.5            # 2 文目と 3 文目の間の無音(秒)
LOW = 0.72           # 3 文目の声の高さ(元の何倍)


def make_voice(path):
    """path に声の見本の wav を書く -> path(作れなければ None)"""
    if os.name != "nt" or not FFMPEG:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a, b = path + ".a.wav", path + ".b.wav"
    env = dict(os.environ, V_A=a, V_B=b, **{"V_L%d" % i: t for i, t in enumerate(LINES)})
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], env=env, capture_output=True, timeout=60,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        if p.returncode != 0 or not (os.path.isfile(a) and os.path.isfile(b)):
            return None
        mix = ("[1]asetrate=%d,aresample=16000,atempo=%.4f[low];[2]asplit=2[s1][s2];[s1]atrim=0:%s,asetpts=N/SR/TB[lead];"
               "[s2]atrim=0:%s,asetpts=N/SR/TB[gap];[lead][0][gap][low]concat=n=4:v=0:a=1" % (int(16000 * LOW), 1 / LOW, LEAD, GAP))
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", a, "-i", b, "-f", "lavfi", "-t", str(LEAD + GAP), "-i", "anullsrc=r=16000:cl=mono",
                        "-filter_complex", mix, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", path],
                       check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        for x in (a, b):
            if os.path.exists(x):
                os.unlink(x)
    return path if os.path.isfile(path) and os.path.getsize(path) > 16000 else None


def to_media(wav, out, *args):
    """ffmpeg で wav を out に(既定は AAC。args で書き方を変える)-> out"""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", wav] + (list(args) or ["-c:a", "aac", "-b:a", "96k"]) + [out]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, creationflags=NO_WINDOW)
    return out


def engine_home():
    """編集の作業データ(whisper.cpp・話者判別のモデルの置き場所)。TRANSCRIBE_ENGINE_DIR があればそれ"""
    d = os.environ.get("TRANSCRIBE_ENGINE_DIR")
    if d:
        return d
    base = os.environ.get("LOCALAPPDATA")
    return os.path.join(base, "youtube-tools", "transcribe") if base else None


def faster_whisper_small():
    """faster-whisper の small が手元にあれば True(部品とキャッシュのモデル)"""
    import importlib.util
    if importlib.util.find_spec("faster_whisper") is None:
        return False
    hub = os.environ.get("HF_HUB_CACHE") or os.path.join(os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface"), "hub")
    return bool(glob.glob(os.path.join(hub, "models--Systran--faster-whisper-small", "snapshots", "*", "model.bin")))


def whisper_cpp_large():
    """whisper.cpp(Vulkan 版)と large-v3 のモデルが手元にあれば作業データのフォルダ、無ければ None(大きさだけ見る)"""
    home = engine_home()
    if not home:
        return None
    from pipeline.transcribe import tx_engines as te
    exe = os.path.join(te.wcpp_bin_dir(home, "vulkan"), te.WCPP_EXE)
    model = os.path.join(te.wcpp_model_dir(home), te.WCPP_MODELS["large-v3"]["file"])
    ok = os.path.isfile(exe) and os.path.isfile(model) and os.path.getsize(model) == te.WCPP_MODELS["large-v3"]["size"]
    return home if ok else None


def haas_speechcpp():
    """speech.cpp(手元の直しの版)と Haas の GGUF・silero の GGUF が手元にあれば作業データのフォルダ、無ければ None(大きさだけ見る)"""
    home = engine_home()
    if not home:
        return None
    from pipeline.transcribe import tx_engines as te
    from ytt import txbase
    gg = te.haas_gguf_dir(home)
    ok = os.path.isfile(txbase.speech_exe(home)) and all(os.path.isfile(os.path.join(gg, m["file"])) and os.path.getsize(os.path.join(gg, m["file"])) == m["size"]
                                                       for m in (te.HAAS_GGUF_MODELS["haas-ja-v1.0"], te.SILERO_GGUF))
    return home if ok else None


def fetch_read_only(spec, folder, *a, **kw):
    """tx_engines.fetch_file の代わり: 手元にあればそのパス(中身の SHA-256 は読み直さない)。無ければ取りに行かずに失敗"""
    p = os.path.join(folder, spec["file"])
    if os.path.isfile(p) and os.path.getsize(p) == spec["size"]:
        return p
    raise AssertionError("モデルを取りに行こうとした: %s" % p)


def no_download(*a, **kw):
    """diarize._download_verified の代わり: 呼ばれたら失敗"""
    raise AssertionError("話者判別のモデルを取りに行こうとした")


def diar_models():
    """話者判別のモデル(Nemotron・声の名前付け)と speech.cpp が手元にあればモデルのパスの組、無ければ None"""
    home = engine_home()
    if not home:
        return None
    from pipeline.transcribe import diarize
    from ytt import txbase
    paths = [os.path.join(home, "models", "diar", item["file"]) for item in (diarize.DIAR_NEMO, diarize.DIAR_EMBS[diarize.VOICE_EMB])]   # 声の名前付けのモデルも(10-22)
    ok = os.path.isfile(txbase.speech_exe(home)) and all(os.path.isfile(p) and os.path.getsize(p) > 1000 for p in paths)
    return paths if ok else None


def copy_diar(data_dir):
    """判別のモデルを一時の作業データの models/diar へ、判別の speech.cpp を bin へ写す(元は読むだけ。認識ワーカーは一時の作業データを見る)"""
    from ytt import txbase
    dst = os.path.join(data_dir, "models", "diar")
    os.makedirs(dst, exist_ok=True)
    for p in diar_models() or ():
        shutil.copyfile(p, os.path.join(dst, os.path.basename(p)))
    if not os.path.isdir(txbase.speech_bin_dir(data_dir)):
        shutil.copytree(txbase.speech_bin_dir(engine_home()), txbase.speech_bin_dir(data_dir))
    return dst
