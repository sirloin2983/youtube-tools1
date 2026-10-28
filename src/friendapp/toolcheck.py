# -*- coding: utf-8 -*-
"""友人の PC の初回の準備の最後の「道具を動かして確かめる」(F3-5。notes:plan/done/f1-friend-requirements.md の C-5-2・C-0)。

取った ffmpeg・ffprobe・yt-dlp・deno は -version / --version を 1 回ずつ(窓を出さない・時間切れあり)、
文字起こし(whisper.cpp)は ffmpeg で作った 2 秒ほどの短い音を 1 回動かす(① の WhisperCpp をそのまま使う = 機器が合わなければ止まる)。
どれが駄目かは「詳しく」用の行 {name, label, ok, text} で返す(1 つ駄目でも残りは確かめる)。
外へ作用する口(子プロセスの実行・文字起こし)は引数で差し替えられる(テストは偽物)。

済んだことは setup.json の checked に signature(道具のファイルの大きさと更新時刻)と一緒に残し、次の起動では確かめ直さない
(道具のファイルが変わったら signature が変わる = 確かめ直す)。
"""
import os
import re

from ytt import tools as _tools

TIMEOUT = 60            # -version の時間切れ(秒。1 ファイルの yt-dlp.exe の初回は展開とウイルス対策の検査で遅い PC だと 20 秒を超えうる)
WAV_TIMEOUT = 30        # 短い音を作る
TOOL_CHECKS = (("ffmpeg", "YTT_FFMPEG", "-version", "動画の道具 ffmpeg"), ("ffprobe", "YTT_FFPROBE", "-version", "動画の道具 ffprobe"),
               ("yt-dlp", "YTT_YTDLP", "--version", "配信を取る道具 yt-dlp"), ("deno", "YTT_DENO", "--version", "配信を取る道具の部品 Deno"))
WHISPER_LABEL = "文字起こし(whisper.cpp)"
MODEL = "large-v3"
VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def run_cmd(cmd, timeout):
    """子プロセスを 1 回(窓なし・時間切れで止める)-> (終了コード, 出力の文字, 止めた理由か None)。起動できなければ OSError"""
    r = _tools.run(cmd, timeout=timeout)
    text = (r.out or b"").decode("utf-8", "replace").strip() or (r.err or b"").decode("utf-8", "replace").strip()
    return r.code, text, r.why


def _row(name, label, ok, text):
    return {"name": name, "label": label, "ok": bool(ok), "text": str(text)[:300]}


def check_tool(name, label, path, arg, run=run_cmd, timeout=TIMEOUT):
    """道具 1 つ -> 行。見つからない・起動できない・時間切れ・終了コードが 0 でないは駄目"""
    if not path or not os.path.isfile(path):
        return _row(name, label, False, "見つかりません")
    try:
        code, text, why = run([path, arg], timeout)
    except OSError as e:
        return _row(name, label, False, "起動できません(%s)" % _tools.why(e))
    if why == "timeout":
        return _row(name, label, False, "答えが返りません(%d 秒で止めました)" % timeout)
    if code != 0:
        return _row(name, label, False, "動きません(終了コード %s)%s" % (code, (": " + text.splitlines()[0][:120]) if text else ""))
    m = VERSION_RE.search(text or "")
    return _row(name, label, True, "動きました" + ("(%s)" % m.group(0) if m else ""))


def check_tools(env, run=run_cmd, timeout=TIMEOUT):
    """ffmpeg・ffprobe・yt-dlp・deno を 1 回ずつ(env = 環境変数の名前 -> パス)-> [行]"""
    return [check_tool(n, label, env.get(var), arg, run, timeout) for n, var, arg, label in TOOL_CHECKS]


def make_wav(ffmpeg, out, run=run_cmd, timeout=WAV_TIMEOUT):
    """ffmpeg で 2 秒ほどの短い音(16kHz・モノ)を作る -> 作れたか"""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-ar", "16000", "-ac", "1", out]
    try:
        code, _text, why = run(cmd, timeout)
    except OSError:
        return False
    return code == 0 and not why and os.path.isfile(out) and os.path.getsize(out) > 0


def whisper_run(device, data_root, wav):
    """① の whisper.cpp で短い音を 1 回(結果は見ない = 動いたかだけ。機器に合わなければ EngineError)"""
    from pipeline.transcribe import tx_engines as _tx
    eng = _tx.WhisperCpp.create(MODEL, device, None, data_dir=os.path.join(data_root, "transcribe"))
    segs, _info = eng.transcribe(wav, language="ja", beam_size=1)
    list(segs)


def check_whisper(device, data_root, ffmpeg, work_dir, run=run_cmd, transcribe=whisper_run):
    """文字起こしを短い音で 1 回 -> 行(name は whisper)。device = vulkan(A)・cuda(C)"""
    name = "whisper"
    wav = os.path.join(work_dir, "toolcheck.wav")
    os.makedirs(work_dir, exist_ok=True)
    try:
        if not make_wav(ffmpeg, wav, run):
            return _row(name, WHISPER_LABEL, False, "確かめる音を作れませんでした(ffmpeg が動きません)")
        try:
            transcribe(device, data_root, wav)
        except Exception as e:   # noqa: BLE001  (EngineError・部品が無い・落ちた。理由は詳しくに出す)
            msg = (e.__class__.__name__ + " " + str(getattr(e, "message", "") or e))[:240].strip()   # 例外の名前も「詳しく」に残す
            return _row(name, WHISPER_LABEL, False, "動きません(%s)" % msg)
        return _row(name, WHISPER_LABEL, True, "動きました(%s)" % ("C = CUDA" if device == "cuda" else "A = Vulkan"))
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def signature(files):
    """道具のファイルの印(パス・大きさ・更新時刻。無い物は除く)。変われば確かめ直す"""
    out = []
    for p in sorted(set(f for f in files if f)):
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append([os.path.normcase(os.path.abspath(p)), st.st_size, st.st_mtime_ns])
    return out


def failed(rows):
    return [r for r in rows if not r["ok"]]
