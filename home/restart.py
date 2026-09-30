# -*- coding: utf-8 -*-
"""入口を起動し直す(段9 9-3。docs/plan/phase9-ops-stability.md の「9-3」)。

取り込んだツール(スタジオ・編集・cut2resolve)は入口と同じプロセスで動くので、版の赤い帯を直すには入口ごと起動し直す必要がある。
手順(home/launch.py の POST api/ytt/restart-self):
  1. can_restart(): 重い処理・まとめて実行が動いていれば断る(理由の文を返す)
  2. spawn_new_launcher(): 新しい入口を、今の入口とは別のコンソール(見えない)で起動する。引数に --wait-port を付ける
  3. 今の入口は「すべて終了」と同じ後始末(子を止める・取り込みを外す・.runtime を消す)をして終わる
  4. 新しい入口は wait_port_free() で同じポートが空くまで(最大 30 秒)待ってから待ち受ける
  5. 画面(ui-kit の UIKit.restart)は api/ping を数秒ごとに読み、戻ったら再読み込みする

起動のしかた(start.bat と同じ環境):
- start.bat・home/start_hidden.vbs が決めているのは「どの Python か(py -3 → python)」と「作業フォルダ = リポジトリ直下」だけ。
  環境変数は何も足さない。動いている入口の sys.executable は、その選んだ Python の本体(py -3 は本体を起動する)なので、
  ここでは sys.executable を使い、環境変数は今のプロセスのものをそのまま写す(bat を経由しない。bat の Python の選び方は変えない)
- コンソール: 既定は見えないコンソール(CREATE_NO_WINDOW。start_hidden.vbs と同じ「裏で動かす」の形)。
  DETACHED_PROCESS(コンソール無し)にはしない: 入口の子(--no-mount のツール・ffmpeg・認識のワーカー)が
  CREATE_NO_WINDOW を付けずに起動すると、そのたびに黒い画面が開いてしまい、子を止める Ctrl+Break(同じコンソールが要る)も届かない。
  新しいコンソールなので、古い入口の黒い画面が閉じても(start.bat の終わり)新しい入口には閉じる合図が届かない
- 古い入口の待ち受けのソケットは引き継がない(Python のソケットは既定で継承しない + close_fds)。引き継ぐとポートが空かない
"""
import os
import socket
import subprocess
import sys
import time

WAIT_PORT_TIMEOUT = 30.0   # 新しい入口が、古い入口がポートを離すのを待つ最長(秒)。古い入口の後始末は子1つにつき最大 8 秒
WAIT_PORT_POLL = 0.25
BUSY_MESSAGE = "実行中の処理があります%s。終わってから起動し直してください"   # %s = (何が動いているか)
SW_SHOWMINNOACTIVE = 7     # 見えるコンソールで起動するとき: 最小化して、前に出さない(画面の操作を邪魔しない)


def launcher_script(root):
    """<リポジトリ直下>/home/launch.py(start.bat の `py -3 home\\launch.py` と同じもの)"""
    return os.path.join(os.path.abspath(root), "home", "launch.py")


def restart_args(port, only=(), no_mount=False):
    """新しい入口に渡す引数。同じポートが空くのを待ち(--wait-port)、ブラウザは開かない(画面は開いたままで再読み込みする)。
    --only・--no-mount は今の入口と同じにする(起動し直して形が変わらないように)"""
    args = ["--port", str(int(port)), "--wait-port", "--no-open"]
    only = [x for x in (only or ()) if x]
    if only:
        args += ["--only", ",".join(only)]
    if no_mount:
        args.append("--no-mount")
    return args


def launcher_env(base=None):
    """新しい入口の環境変数: 今のプロセスのものを写す(start.bat は何も足さない)。テストの YTT_DATA_DIR・YTT_RUNTIME_DIR もそのまま引き継ぐ"""
    return dict(os.environ if base is None else base)


def popen_kwargs(visible=False):
    """Popen に渡す起動の形(OS ごと)。上の説明の「コンソール」"""
    if os.name == "nt":
        if visible:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = SW_SHOWMINNOACTIVE
            # CREATE_NEW_PROCESS_GROUP は付けない(付けると新しい黒い画面で Ctrl+C が効かなくなる。別のコンソールなので古い入口の合図は届かない)
            return {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": si}
        return {"creationflags": subprocess.CREATE_NO_WINDOW,
                "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    # Mac/Linux: 新しいセッション(端末を閉じた合図・古い入口のプロセスグループへの合図が届かない)。出力は launcher.log にも残る
    return {"start_new_session": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def spawn_new_launcher(root, python=None, args=(), log=None, env=None, visible=False, popen=subprocess.Popen):
    """新しい入口を起動して Popen を返す(待たない)。起動できなければ OSError をそのまま上げる(API は 500 で断り、今の入口は続ける)。
    python: 既定は今の Python(sys.executable)。args: restart_args() の結果。popen: テスト用"""
    python = python or sys.executable
    cmd = [python, launcher_script(root)] + [str(a) for a in args]
    kw = popen_kwargs(visible)
    proc = popen(cmd, cwd=os.path.abspath(root), env=launcher_env(env), close_fds=True, **kw)
    if log:
        log("新しい入口を起動しました(pid %s)。この入口は後始末をして終わります" % getattr(proc, "pid", "?"))
    return proc


def _bind_ok(host, port):
    """そのポートで待ち受けられるか(入口と同じ形で bind してみる。Windows は SO_EXCLUSIVEADDRUSE、ほかは SO_REUSEADDR)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def port_free(port, host="127.0.0.1", timeout=0.3):
    """誰も待ち受けておらず(つなげない)、自分が bind できる。
    つなげないだけでは足りない: 古い入口が閉じる途中(待ち受けを止めてソケットをまだ閉じていない)だと bind に失敗し、
    入口の make_server は次の番号(8701)を選んでしまう(画面は 8700 を待ち続ける)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        if s.connect_ex((host, port)) == 0:
            return False
    except OSError:
        pass
    finally:
        s.close()
    return _bind_ok(host, port)


def wait_port_free(port, timeout=WAIT_PORT_TIMEOUT, host="127.0.0.1", poll=WAIT_PORT_POLL, clock=time.monotonic, sleep=time.sleep):
    """port が空くまで待つ。空いたら True、timeout 秒たっても空かなければ False(呼ぶ側はそのまま起動を続ける = 次の番号になる)"""
    end = clock() + max(0.0, float(timeout))
    while True:
        if port_free(port, host):
            return True
        if clock() >= end:
            return False
        sleep(poll)


def can_restart(status, runs=None, busy_tools=()):
    """起動し直してよいか。よければ None、だめなら画面に出す理由の文。
    status: Supervisor.status()(heavy = ytt_core.jobs.SLOTS.snapshot(): {"limit", "active": [{tool, label, seconds}], "waiting": [...]})
    runs: まとめて実行の実行の一覧(AutoRunner.snapshot()["runs"]。state が queued / running のものがあれば断る)。
          まとめて実行は段と段の間は重い処理の枠を持たないので、heavy だけでは見落とす
    busy_tools: 取り込んだツールのうち busy() が真のものの名前(「すべて終了」の確認と同じ判定。任意)"""
    heavy = (status or {}).get("heavy") or {}
    items = list(heavy.get("active") or []) + list(heavy.get("waiting") or [])
    labels = [str(i.get("label") or i.get("tool") or "") for i in items if isinstance(i, dict)]
    active_runs = [r for r in (runs or []) if isinstance(r, dict) and r.get("state") in ("queued", "running")]
    if active_runs:
        labels.append("まとめて実行 %d 件" % len(active_runs))
    busy = [str(n) for n in (busy_tools or ()) if n]
    labels += busy
    if not items and not active_runs and not busy:
        return None
    shown = [x for x in dict.fromkeys(labels) if x][:3]
    return BUSY_MESSAGE % ("(%s)" % "・".join(shown) if shown else "")
