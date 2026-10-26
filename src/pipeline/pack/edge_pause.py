"""切り抜きの両端を「話の間」へ寄せる(10-23。決定 3-153。notes:plan/heatmap-study.md の「切り抜きの端を話の間へ」)。
パックの土台の両端(文字起こしの切れ目で寄せた後)を、前後 REACH 秒の中で音が声より QUIET_DB 以上静かな所が MIN_GAP 秒以上続く「間」へ寄せる。
終わりは言い終わり(端より後ろの間)を優先し、始まりは話し始めの前(端より前の間)を優先する。間の中の位置は声の側から PAD 秒。
文字起こしの行は時刻がずれる・語を拾い損ねる = 行だけでは端が秒の区切りのまま声の途中で切れていた(ツールの終わりの 41% が声の途中・友人は 10%)。

決まり: 音は 20 ms ごとの音量(dB)だけを見る(標準ライブラリ)。声の大きさ = 区間の中の 20 ms の音量の上から 3 割の位置(話が多い区間で声の中央の近く)。
間が見つからない端は動かさない。区間の外(動画の外)へは出ない。スイッチ: ON = False で寄せない。印: 注意の 1 行と計画の edgePause
10-26(まとめ役・研究 C:/dev/overlap-research の edge_recheck。確かな端 144): 静かさの線 QUIET_DB 15 → 10 dB・外へ広げる向きだけ寄せる(OUTWARD_ONLY。
始まりは前へ・終わりは後ろへだけ。内へ詰める寄せは友人の端から遠ざかった = 欠けを減らす方)。前の形は QUIET_DB_OLD と OUTWARD_ONLY = False。測り直し 11-09
"""
import array
import math
import subprocess

from ytt import tools as _tools

from . import srt2resolve as S

ON = True
REACH = 2.5      # 端の前後に探す秒(研究の 75 区間で 1.5 → 2.5 秒: 声の途中で切る 始まり 20 → 16%・終わり 19 → 13%)
QUIET_DB = 10.0  # 声の大きさよりこれだけ静かなら「間」(10-26 に 15 → 10。研究の確かな端で 近づく 384 → 440 回)
QUIET_DB_OLD = 15.0   # 前の値(戻すとき)
OUTWARD_ONLY = True   # 外へ広げる向きだけ寄せる(始まりは前へ・終わりは後ろへ。False で前の形 = 内へ詰める向きも寄せる)
MIN_GAP = 0.15   # 間の最短(秒)
PAD = 0.05       # 間の中の位置: 声の側の端からこれだけ(友人の終わりの余白の中央 0.04 秒)
HOP = 0.02       # 音量を測る幅(秒)
SR = 16000


def levels(video, start, end, timeout=120):
    """動画の [start, end) 秒の最初の音声トラック -> 20 ms ごとの音量(dB)の並び。読めなければ None"""
    cmd = [S.tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", "%.3f" % max(0.0, start),
           "-t", "%.3f" % max(0.1, end - start), "-i", S.arg_path(video), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, creationflags=_tools.no_window_flags(priority="low"))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    pcm = array.array("h")
    pcm.frombytes(r.stdout[:len(r.stdout) // 2 * 2])
    step = int(SR * HOP)
    out = []
    for i in range(0, len(pcm) - step + 1, step):
        ms = sum(v * v for v in pcm[i:i + step]) / step
        out.append(10 * math.log10(ms / (32768.0 ** 2) + 1e-12))
    return out


def voice_level(db):
    """声の大きさの目安: 上から 3 割の位置の音量"""
    s = sorted(db)
    return s[int(len(s) * 0.7)] if s else -60.0


def pauses(db, t0, lv, quiet_db=QUIET_DB, min_gap=MIN_GAP):
    """音量の並び db(t0 秒から 20 ms ごと)の中の間 [(始まり, 終わり)](秒)= lv より quiet_db 以上静かな所が min_gap 秒以上続く所"""
    out, s = [], None
    for k, v in enumerate(list(db) + [0.0]):
        quiet = k < len(db) and v < lv - quiet_db
        if quiet and s is None:
            s = k
        elif not quiet and s is not None:
            if (k - s) * HOP >= min_gap:
                out.append((t0 + s * HOP, t0 + k * HOP))
            s = None
    return out


def snap_end(t, ps):
    """終わり t -> 寄せた時刻(間が無ければ t)。t を含むか後ろの間を優先(言い終わり)・無ければ前の間"""
    near = [p for p in ps if p[1] >= t - REACH and p[0] <= t + REACH]
    after = [p for p in near if p[1] > t]
    p = min(after, key=lambda p: p[0]) if after else (max(near, key=lambda p: p[1]) if near else None)
    if p is None:
        return t
    out = min(p[1], p[0] + PAD)   # 間の中にあっても言い終わりの直後へ(無音を残さない = 友人の終わりの余白 中央 0.04 秒)
    return max(t, out) if OUTWARD_ONLY else out   # 外へ(後ろへ)広げる向きだけ


def snap_start(t, ps):
    """始まり t -> 寄せた時刻。t を含むか前の間を優先(話し始めの前)・無ければ後ろの間"""
    near = [p for p in ps if p[1] >= t - REACH and p[0] <= t + REACH]
    before = [p for p in near if p[0] < t]
    p = max(before, key=lambda p: p[1]) if before else (min(near, key=lambda p: p[0]) if near else None)
    if p is None:
        return t
    out = max(p[0], p[1] - PAD)   # 間の中にあっても話し始めの直前へ
    return min(t, out) if OUTWARD_ONLY else out   # 外へ(前へ)広げる向きだけ


def snap(video, a, b, dur):
    """区間 [a, b](秒)の両端を話の間へ(動画の範囲 0〜dur の中で)-> (a2, b2, info)。info = {"in": 動いた秒, "out": 動いた秒} か None(音が読めない・スイッチ)"""
    if not ON or b - a <= 2 * REACH:
        return a, b, None
    x0, x1 = max(0.0, a - REACH - HOP), min(dur, b + REACH + HOP)
    db = levels(video, x0, x1)
    if not db:
        return a, b, None
    t_at = lambda t: max(0, min(len(db), int(round((t - x0) / HOP))))
    lv = voice_level(db[t_at(a):t_at(b)])
    ps = pauses(db, x0, lv)
    a2 = max(0.0, snap_start(a, [p for p in ps if p[1] <= a + REACH + HOP]))
    b2 = min(dur, snap_end(b, [p for p in ps if p[0] >= b - REACH - HOP]))
    if b2 - a2 < (b - a) * 0.5:
        return a, b, None
    return a2, b2, {"in": round(a2 - a, 2), "out": round(b2 - b, 2)}
