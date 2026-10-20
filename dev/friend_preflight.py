# -*- coding: utf-8 -*-
"""友人に配る zip を、配る前にこの PC で「友人の PC と同じ状態」にして通しで試す(配る前の検査。notes:docs/spec/friend.md の 13-11)。

今までの「合言葉が違います」「ffmpeg が見つかりません」「確認用の動画が見られない」「依頼が届かない」は、どれも配ってから友人の PC で見つかった。
開発の PC には Python・ffmpeg・PATH・作業データ・リポジトリがそろっていて、zip に足りない物があっても気づけないため。

    py -3.12 dev/friend_preflight.py [--zip Z] [--update-zip U] [--work W] [--keep] [--skip-update] [--break ffmpeg] [--timeout-min 25]

--zip が無ければ dev/build_friend_zip.py の build で今のコードから作る(キャッシュの物だけ = --no-fetch と同じ)。
--update-zip は 10 の更新に使う全部入りの zip(既定は --zip と同じ物)。前の形の zip(--zip)から今の build(--update-zip)へ上がる確かめに使う。
流れ(1 つでも落ちたら不合格。結果は <work>/report.json と 1 行ずつの OK / FAIL):
  1. 展開: zip を一時フォルダの FriendApp\\ に展開し、manifest.json の SHA-256 と直下の物を確かめる(sitecustomize.py が入っていないことも)
  2. 友人の PC の形: 環境変数は最小(PATH は Windows の System32 だけ = 開発の Python・ffmpeg・git は見えない)・USERPROFILE・LOCALAPPDATA・
     APPDATA・TEMP は一時フォルダの中・YTT_* は渡さない。Dropbox は一時フォルダ(dev/friend_preflight_shim.py。本物の Dropbox へは書かない)・
     ネットは断る(取得は表の URL だけこの PC のキャッシュから返す)。展開した写しの python に通信の差し替え(sitecustomize.py)を置くだけで、アプリのコードは変えない
  3. 部品: 道具(ffmpeg・yt-dlp・deno)は本物と同じ取得の流れ(偽の取得元から)。重いモデル(約 11GB)は開発の PC の作業データから
     リンク(できなければ写し)で data\\ に置く = 「取り終えた」形(モデルの取得そのものは test_setup.py と道具の取得で同じ口を通る)
  4. 本物の FriendApp.exe を画面の外・消音(YTT_FRIEND_SHOTS)で起こし、WebView2 に Playwright でつなぐ(--remote-debugging-port)
  5. 合言葉: 画面から合言葉なしで口が通る(exe が足す)・meta は置き物 host・外から合言葉なしでは 403
  6. 初回の準備: 道具の取得 → 浅く置く → 全部の道具と文字起こしを動かす → 済み(tools\\<名前>\\ の直下に exe)
  6b. YouTube のログイン: 本物の Google は開かず、exe が書くのと同じ所に偽の cookie を置く → ⚙ が「ログインしています」・[ログイン] が押せる・
     同梱の Python が yt-dlp へ写しを --cookies で渡す → ログアウトで消える。最後に偽の値が Dropbox・送り返し・ログに無いこと
  7. 依頼: 小さな動画(同梱の ffmpeg で作る。名前の頭に【配信者】)を本物のドロップ(CDP の drop)で 2 回落とし 1 本だけ入る → [送る] → ② が処理 → 届いた
  7b. URL の依頼・区間 5 つ: 疑似モード(STUDIO_FAKE。YouTube の代わりに手元の 80 秒の動画を切る)で区間 5 つを送り、受け取る画面に 5 本そろう
     (どれも確認用の動画つき・頼んだ区間を含む長さ)。同梱の yt-dlp.exe は隣の yt-dlp.conf でネットへ出られなくする(呼ばれないはずの守り)
  8. 届く物: この PC で作った確認用の動画(h264・yuv420p・高さ 480 以下)が受け取る画面の <video> で再生できる。
     ユーザーの PC が届ける形(flow/deliver.deliver_one = 1 本ずつの zip・.preview.mp4・.meta.json)を偽の Dropbox の /出力/ に置き、同期で取り込まれて再生できる
  9. 判断: 受け取る(保存先へ移る)・見送る → .verdict.json(v 2)が /送り返し/ に上がる
 10. 更新: 版を上げた全部入りの zip と軽い zip(-light。python/・tools/ なし)と light 付きの latest.json を偽の /更新/ に置き → 取って app-<版>\\ へ
     (軽い更新に応じる版は light だけを取り python/ を今の python から写す・前の形の版は全部入りを取る)→ [更新する] → exe が入れ替えて新しい版で開き直す(--skip-update で飛ばす)
 11. 片付け: [すべて止めて終了] と同じ /api/shutdown → exe と子・孫(Python・ffmpeg・whisper.cpp・WebView2)が残らない。合格なら一時フォルダを消す(--keep で残す)
--break ffmpeg は検査が効くかの確かめ用: 展開した写しの fetch.json から ffmpeg の行を消す(= ffmpeg を取れない zip と同じ)。初回の準備で落ちるのが正しい。
音は出さない(exe は YTT_FRIEND_SHOTS で WebView2 を消音・<video> は muted)・窓は画面の外・子プロセスは黒い窓を出さない・止めるのは自分が起こした PID だけ。
終了コード 0 合格 / 1 不合格 / 2 引数・前提が無い(Playwright・キャッシュ・モデル)
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

DEV = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DEV)
SRC = os.path.join(REPO, "src")
for _p in (SRC, DEV):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import _common  # noqa: E402
import build_friend_zip as bfz  # noqa: E402
from ytt import datadir, tools as _ytools  # noqa: E402

SHIM_SRC = os.path.join(DEV, "friend_preflight_shim.py")
SHIM_ENV = "YTT_PREFLIGHT_SHIM"
REPORT = "report.json"
EXIT_WAIT_S = 30   # [すべて止めて終了] のあと子・孫が消えるまでの待ち(shutdown)
PREVIEW_WAIT_S = 90   # 届いてから確認用の動画ができるまでの待ち(check_local_delivery)
WORK_MAX = 60   # 一時フォルダのパスの長さの上限(下の run)
ROOT_FILES = (bfz.LAUNCHER_EXE,) + bfz.LAUNCHER_DLLS + ("fetch.json", "manifest.json", "members.json")
TOOL_EXES = ("ffmpeg/ffmpeg.exe", "ffmpeg/ffprobe.exe", "yt-dlp/yt-dlp.exe", "deno/deno.exe")   # 浅く置いた道具(friendapp/places.lay_tools_shallow)
STREAMER = "星街すいせい"   # 名簿 members.json にいる名前(ファイル名の頭の【】から配信者を推す)
DBX_DIRS = ("出力", "送り返し", "更新", "学習", "診断")
CHILD_FLAGS = _ytools.no_window_flags()
TASKKILL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
PS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


class Preflight(Exception):
    """前提が無い(終了コード 2)"""


class Report:
    """確かめた物の一覧(1 行ずつ出し、最後に report.json)"""

    def __init__(self, path):
        self.path, self.rows, self.t0 = path, [], time.time()

    def check(self, key, ok, detail=""):
        self.rows.append({"key": key, "ok": bool(ok), "detail": str(detail)[:2000], "sec": round(time.time() - self.t0, 1)})
        print("%s %s%s" % ("OK  " if ok else "FAIL", key, (" … " + str(detail)[:300]) if detail else ""), flush=True)
        return bool(ok)

    def info(self, key, detail):
        self.rows.append({"key": key, "ok": None, "detail": str(detail)[:2000], "sec": round(time.time() - self.t0, 1)})
        print("    %s … %s" % (key, str(detail)[:300]), flush=True)

    @property
    def failed(self):
        return [r for r in self.rows if r["ok"] is False]

    def write(self, extra=None):
        doc = {"ok": not self.failed, "rows": self.rows}
        doc.update(extra or {})
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def link_or_copy(src, dst):
    """重いモデルはリンク(同じドライブなら一瞬・場所を取らない)。できなければ写す"""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


# ---------------------------------------------------------------- 1〜3 展開・友人の PC の形・部品
def unpack(zip_path, app, rep):
    """zip を app に展開し、manifest の SHA-256・直下の物・差し替えの物が無いことを確かめる"""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    rep.check("zip に通信の差し替え(sitecustomize.py)が入っていない", not any(n.lower().endswith("sitecustomize.py") for n in names))
    bfz.unzip_into(zip_path, app)
    miss = [n for n in ROOT_FILES if not os.path.isfile(os.path.join(app, n))]
    rep.check("zip の直下に exe・WebView2 の DLL・fetch.json・manifest.json・members.json がある", not miss, ", ".join(miss))
    rep.check("zip に埋め込みの Python と src がある", os.path.isfile(os.path.join(app, "python", "python.exe")) and
              os.path.isfile(os.path.join(app, "src", "friendapp", "server.py")))
    with open(os.path.join(app, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    bad = [rel for rel, sha in (man.get("files") or {}).items()
           if not os.path.isfile(os.path.join(app, *rel.split("/"))) or bfz.sha256_file(os.path.join(app, *rel.split("/"))) != sha]
    rep.check("manifest.json の全部のファイル(%d)の SHA-256 が合う" % len(man.get("files") or {}), not bad, ", ".join(bad[:10]))
    with open(os.path.join(app, "fetch.json"), encoding="utf-8") as f:
        return man, json.load(f)


def break_fetch(app, what):
    """--break: fetch.json から what の行を消す(検査が効くかの確かめ用)"""
    p = os.path.join(app, "fetch.json")
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    doc["items"] = [i for i in doc["items"] if i.get("name") != what]
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def place_models(fetch, app, dev_root, rep):
    """base data の行(モデル・llama.cpp)を開発の PC の作業データから data\\ へ(取り終えた形 = setup.is_done が見る置き方)"""
    data = os.path.join(app, "data")
    for it in fetch["items"]:
        if it.get("base") != "data":
            continue
        dest = it["dest"].split("/")
        src_dir, dst_dir = os.path.join(dev_root, *dest), os.path.join(data, *dest)
        if it.get("unzip") == "zip":   # 展開した物 + 目印 .fetched-<file>
            src, dst = src_dir, dst_dir
        elif it.get("unzip") == "tar.bz2":
            src, dst = os.path.join(src_dir, it["top"]), os.path.join(dst_dir, it["top"])
        else:
            src, dst = os.path.join(src_dir, it["file"]), os.path.join(dst_dir, it["file"])
        if not os.path.exists(src):
            raise Preflight("開発の PC の作業データに %s がありません(%s)。編集の画面などで一度取ってから流してください" % (it["name"], src))
        if os.path.isdir(src):
            shutil.copytree(src, dst, copy_function=link_or_copy, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            link_or_copy(src, dst)
    rep.info("モデルを置いた", "開発の PC の作業データから(リンク): %s" % ", ".join(i["name"] for i in fetch["items"] if i.get("base") == "data"))


def mirror_map(fetch, cache, rep):
    """base app の行(道具)の URL -> キャッシュのファイル(取得の流れは本物と同じ)。表の SHA-256 とキャッシュが違えば前提が無い"""
    out = {}
    for it in fetch["items"]:
        if it.get("base") != "app":
            continue
        p = os.path.join(cache, "tools", it["file"])
        if not os.path.isfile(p):
            raise Preflight("キャッシュに %s がありません(py -3.12 dev/build_friend_zip.py --out <一時> で一度取ってから)" % p)
        if bfz.sha256_file(p) != it["sha256"]:
            raise Preflight("キャッシュの %s が fetch.json の SHA-256 と違います" % it["file"])
        out[it["url"]] = p
    rep.info("偽の取得元", ", ".join(sorted(os.path.basename(p) for p in out.values())))
    return out


def lay_shim(app, work, mirror):
    """展開した写しの python に通信の差し替えを置き、設定の JSON を書く -> 設定のパス"""
    site = os.path.join(app, "python", "Lib", "site-packages")
    shutil.copy2(SHIM_SRC, os.path.join(site, "sitecustomize.py"))
    conf = os.path.join(work, "shim.json")
    with open(conf, "w", encoding="utf-8") as f:
        json.dump({"mirror": mirror, "dropbox": os.path.join(work, "dropbox"), "log": os.path.join(work, "net.log")}, f, ensure_ascii=False, indent=1)
    return conf


def friend_env(work, cdp_port, shim_conf):
    """友人の PC と同じくらい何も無い環境変数(開発の PATH・YTT_*・Python の変数を渡さない)"""
    win = os.environ.get("SystemRoot", r"C:\Windows")
    prof = os.path.join(work, "home")
    local, roaming = os.path.join(prof, "AppData", "Local"), os.path.join(prof, "AppData", "Roaming")
    temp = os.path.join(local, "Temp")
    for d in (local, roaming, temp, os.path.join(prof, "Videos"), os.path.join(prof, "Desktop")):
        os.makedirs(d, exist_ok=True)
    keep = ("SystemDrive", "OS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "NUMBER_OF_PROCESSORS",
            "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "CommonProgramFiles", "CommonProgramFiles(x86)", "CommonProgramW6432",
            "ALLUSERSPROFILE", "PUBLIC", "COMPUTERNAME", "USERDOMAIN", "DriverData")
    env = {k: os.environ[k] for k in keep if os.environ.get(k)}
    drive, rest = os.path.splitdrive(prof)
    env.update({
        "SystemRoot": win, "windir": win, "ComSpec": os.path.join(win, "System32", "cmd.exe"),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC",
        "PATH": ";".join([os.path.join(win, "System32"), win, os.path.join(win, "System32", "Wbem"), os.path.join(win, "System32", "WindowsPowerShell", "v1.0")]),
        "USERNAME": "friend", "USERPROFILE": prof, "HOMEDRIVE": drive, "HOMEPATH": rest, "APPDATA": roaming, "LOCALAPPDATA": local, "TEMP": temp, "TMP": temp,
        "YTT_FRIEND_SHOTS": os.path.join(work, "shots"),            # 画面の外・前に出さない・消音(MainForm.Quiet)
        "YTT_FRIEND_SHOT_STEPS": os.path.join(work, "steps.json"),   # 手順 = 長く待つだけ(写真は撮らない。つないで調べる間、窓を開けておく)
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=%d" % cdp_port,
        SHIM_ENV: shim_conf,
        "STUDIO_FAKE": "1", "STUDIO_FAKE_MEDIA": fake_media(work),   # URL の依頼(区間 5 つ)は YouTube の代わりにこの動画を切る(7b。動画ファイルの依頼には効かない)
    })
    return env


def fake_media(work):
    return os.path.join(work, "home", "Videos", "疑似の配信.mp4")


def make_work(work, zip_path, args, rep):  # lint: long 置き場所を作る一続き(展開 → 壊す → 鍵 → モデル → 取得元 → 差し替え)
    """一時フォルダの形を作る -> {app, dropbox, man, fetch, shim}"""
    app = os.path.join(work, "FriendApp")
    os.makedirs(app)
    for d in DBX_DIRS:
        os.makedirs(os.path.join(work, "dropbox", d))
    os.makedirs(os.path.join(work, "shots"))
    with open(os.path.join(work, "steps.json"), "w", encoding="utf-8") as f:
        json.dump([{"wait": int(args.timeout_min * 60 * 1000) + 600000}], f)
    man, fetch = unpack(zip_path, app, rep)
    if args.break_item:
        break_fetch(app, args.break_item)
        fetch = {"items": [i for i in fetch["items"] if i.get("name") != args.break_item]}
        rep.info("わざと壊した", "fetch.json から %s の行を消した(検査が効くかの確かめ)" % args.break_item)
    with open(os.path.join(app, "config.json"), "w", encoding="utf-8") as f:   # 偽の Dropbox の鍵(--first --with-key と同じ置き場所)
        json.dump({"appKey": "preflight", "refreshToken": "preflight"}, f)
    place_models(fetch, app, datadir.data_root(), rep)
    mirror = mirror_map(fetch, args.cache, rep)
    shim = lay_shim(app, work, mirror)
    return {"app": app, "dropbox": os.path.join(work, "dropbox"), "man": man, "fetch": fetch, "shim": shim, "mirror": mirror}


# ---------------------------------------------------------------- 4 exe と画面
class Window:
    """本物の FriendApp.exe と、その WebView2 へのつなぎ(Playwright の connect_over_cdp)"""

    def __init__(self, app, env, cdp_port):
        self.app, self.env, self.cdp_port = app, env, cdp_port
        self.proc = None
        self.pw = self.browser = self.page = None
        self.seen = {}   # exe の子孫の PID -> (名前, 作った時刻)(最後に残っていないかを見る)

    def start(self):
        exe = os.path.join(self.app, bfz.LAUNCHER_EXE)
        self.proc = subprocess.Popen([exe], cwd=self.app, env=self.env, creationflags=CHILD_FLAGS,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def connect(self, timeout=120):
        from playwright.sync_api import sync_playwright
        if self.pw is None:
            self.pw = sync_playwright().start()
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                self.browser = self.pw.chromium.connect_over_cdp("http://127.0.0.1:%d" % self.cdp_port, timeout=5000)
                for ctx in self.browser.contexts:
                    for pg in ctx.pages:
                        if pg.url.startswith("http://127.0.0.1:"):
                            self.page = pg
                            return pg
                self.browser.close()
            except Exception as e:   # noqa: BLE001  (WebView2 が起きるまで・画面を読み込むまで)
                last = e
            time.sleep(1)
        raise RuntimeError("WebView2 につなげません(%s)" % (last.__class__.__name__ if last else "画面がありません"))

    def port(self):
        m = re.match(r"http://127\.0\.0\.1:(\d+)/", self.page.url)
        return int(m.group(1)) if m else None

    def eval(self, js, arg=None, tries=20):
        """画面で JS を流す(画面の移り変わりの途中なら少し待ってやり直す)"""
        last = None
        for _ in range(tries):
            try:
                return self.page.evaluate(js, arg)
            except Exception as e:   # noqa: BLE001  (Execution context was destroyed など)
                last = e
                time.sleep(0.5)
        raise RuntimeError("画面で JS を流せません: %s" % str(last)[:200])

    def api(self, method, path, body=None):
        """画面から口を呼ぶ(合言葉は画面に無い = WebView2 が足す物だけ)-> (status, json)"""
        js = """async ([m, p, b]) => {
          const o = {method: m, headers: {}};
          if (b !== null) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(b); }
          const r = await fetch(p, o); let j = null; try { j = await r.json(); } catch (e) {}
          return [r.status, j]; }"""
        st, j = self.eval(js, [method, path, body])
        return st, j

    def watch_tree(self):
        """exe の子孫を覚える(最後に残っていないかを見るため)"""
        root = self.proc.pid if self.proc else None
        if root is None:
            return
        procs = list_processes()
        # 子 = 親より後に作られた物だけ(終わった子の PID をほかのアプリ(Discord など)が使い回すと、その子まで数えてしまうため。時刻は同じ PC の ISO の文字)
        born = {p["ProcessId"]: str(p.get("CreationDate") or "") for p in procs}
        kids = {root}
        grew = True
        while grew:
            grew = False
            for p in procs:
                if p["ParentProcessId"] in kids and p["ProcessId"] not in kids and born[p["ProcessId"]] >= born.get(p["ParentProcessId"], ""):
                    kids.add(p["ProcessId"])
                    grew = True
        for p in procs:
            if p["ProcessId"] in kids:
                self.seen[p["ProcessId"]] = (p["Name"], p["CreationDate"])

    def close(self):
        try:
            if self.browser is not None:
                self.browser.close()
        except Exception:   # noqa: BLE001  (止まった窓へのつなぎは閉じられなくてよい)
            pass
        try:
            if self.pw is not None:
                self.pw.stop()
        except Exception:   # noqa: BLE001
            pass
        self.browser = self.page = None
        self.pw = None


def list_processes():
    """動いているプロセスの一覧(読むだけ)[{ProcessId, ParentProcessId, Name, CreationDate}]"""
    cmd = [PS, "-NoProfile", "-NonInteractive", "-Command",
           "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,@{n='CreationDate';e={$_.CreationDate.ToString('o')}} | ConvertTo-Json -Compress"]
    r = subprocess.run(cmd, capture_output=True, creationflags=CHILD_FLAGS, timeout=60)
    try:
        d = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
    except ValueError:
        return []
    return d if isinstance(d, list) else [d]


def wait_for(fn, timeout, every=2.0):
    """fn() が真の値を返すまで待つ -> その値か None"""
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


# ---------------------------------------------------------------- 5〜6 合言葉・初回の準備
def check_token(w, rep):
    port = w.port()
    rep.check("exe が番号を選んで画面を開いた", port is not None, w.page.url)
    meta = w.eval("() => { const m = document.querySelector('meta[name=ytt-token]'); return m ? m.content : null; }")
    rep.check("画面の meta ytt-token は置き物 host(本物の合言葉は画面に無い)", meta == "host", meta)
    st, _j = w.api("GET", "/api/friend/state")
    rep.check("画面から合言葉なしで GET /api/friend/state が通る(exe が合言葉を足している)", st == 200, st)
    st2, _j = w.api("POST", "/api/friend/notice-seen", {})
    rep.check("画面から合言葉なしで書き込みの口(POST notice-seen)が通る", st2 == 200, st2)
    import urllib.request
    import urllib.error
    req = urllib.request.Request("http://127.0.0.1:%d/api/friend/state" % port, headers={"Host": "127.0.0.1:%d" % port})
    try:
        code = urllib.request.urlopen(req, timeout=10).status
    except urllib.error.HTTPError as e:
        code = e.code
    rep.check("外から合言葉なしでは断られる(403)", code == 403, code)
    return port


def check_setup(w, app, rep, timeout):
    last = {}

    def done():
        st, j = w.api("GET", "/api/friend/setup")
        if st == 200 and isinstance(j, dict) and isinstance(j.get("setup"), dict):   # {ok, setup: Setup.view(), done}
            last.update(j["setup"])
            return last.get("state") in ("done", "failed", "need-space")
        return False
    w.watch_tree()
    wait_for(done, timeout, every=3)
    w.watch_tree()
    ok = rep.check("初回の準備が済む", last.get("state") == "done",
                   "%s %s %s" % (last.get("state"), last.get("message"), json.dumps(last.get("error") or [d for d in last.get("detail") or [] if d.get("state") == "failed"], ensure_ascii=False)[:600]))
    miss = [t for t in TOOL_EXES if not os.path.isfile(os.path.join(app, "tools", *t.split("/")))]
    rep.check("道具が tools\\<名前>\\ の直下にある(ffmpeg・ffprobe・yt-dlp・deno)", not miss, ", ".join(miss))
    rec = os.path.join(app, "data", "app", "friendapp", "setup.json")
    try:
        with open(rec, encoding="utf-8") as f:
            checked = json.load(f).get("checked")
    except (OSError, ValueError):
        checked = None
    rep.check("道具と文字起こしを動かして確かめた印(setup.json の checked)", bool(checked), json.dumps(checked, ensure_ascii=False)[:300])
    if ok:
        page_ok = wait_for(lambda: "/friend/" in w.page.url and "setup" not in w.page.url, 60, every=1)
        st, j = w.api("GET", "/api/friend/setup")
        vis = w.eval("() => [document.visibilityState, document.hasFocus()]")
        rep.check("準備が済んだら送る画面へ移る", bool(page_ok), "%s done=%s 見え方=%s" % (w.page.url, (j or {}).get("done"), vis))
    return ok


# ---------------------------------------------------------------- 6b YouTube のログイン(偽の cookie。notes:docs/spec/friend.md の 13-13)
FAKE_COOKIE = "preflight-fake-cookie-value"   # 検査の偽の値(最後に Dropbox・送り返し・ログへ漏れていないかを探す)
LOGIN_JS = """async () => {
  document.getElementById('btnSettings').click();
  for (let i = 0; i < 40 && !document.getElementById('fsYtH'); i++) await new Promise(r => setTimeout(r, 150));
  await new Promise(r => setTimeout(r, 600));
  const h = document.getElementById('fsYtH'); if (!h) return null;
  const sec = h.parentElement, b = sec.querySelector('button');
  const out = {text: sec.querySelector('p').textContent, enabled: !!b && !b.disabled, isApp: !!(window.FriendHost && FriendHost.isApp)};
  const d = document.getElementById('settingsDrawer'); if (d && window.UIKit) UIKit.drawer.close(d);
  return out; }"""


def check_login(w, app, rep):
    """ログインの小窓(本物の Google)は開かない。exe が書くのと同じ所に偽の cookie を置き、⚙ の状態・yt-dlp へ渡す写し・ログアウトを確かめる"""
    path = os.path.join(app, "data", "app", "friendapp", "secrets", "youtube-cookies.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\t%s\n" % FAKE_COOKIE)
    st, j = w.api("GET", "/api/friend/settings")
    y = ((j or {}).get("settings") or {}).get("ytLogin") or {}
    rep.check("YouTube のログイン: cookie を置くと ⚙ が「ログインしています」", st == 200 and y.get("state") == "ok", y)
    rep.check("YouTube のログイン: ⚙ の口に cookie の中身が出ない", FAKE_COOKIE not in json.dumps(j or {}))
    v = w.eval(LOGIN_JS) or {}
    rep.check("YouTube のログイン: ⚙ の節が出て、アプリの窓の中なので [ログイン] が押せる", v.get("enabled") and v.get("isApp") and "ログインしています" in (v.get("text") or ""), v)
    py = next(iter(sorted(glob.glob(os.path.join(app, "app-*", "python", "python.exe")) + glob.glob(os.path.join(app, "python", "python.exe")))), None)
    if py:
        code = "from ytt import tools as t; import json; print(json.dumps(t.ytdlp_auth_args()))"
        env = dict(w.env, YTT_YTDLP_COOKIES=path, PYTHONPATH=os.path.join(os.path.dirname(os.path.dirname(py)), "src"))
        r = subprocess.run([py, "-c", code], capture_output=True, env=env, creationflags=CHILD_FLAGS, timeout=60)
        try:
            args = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except (ValueError, IndexError):
            args = []
        ok = len(args) == 2 and args[0] == "--cookies" and os.path.isfile(args[1]) and os.path.dirname(args[1]) == os.path.join(os.path.dirname(path), "run")
        rep.check("YouTube のログイン: yt-dlp には呼ぶたびの写しを --cookies で渡す(同梱の Python で)", ok, args or r.stderr.decode("utf-8", "replace")[-300:])
    else:
        rep.info("YouTube のログイン: yt-dlp へ渡す口", "同梱の Python が見つからない")
    st, j = w.api("POST", "/api/friend/settings", {"ytLogout": True})
    y = ((j or {}).get("settings") or {}).get("ytLogin") or {}
    rep.check("YouTube のログイン: ログアウトで cookie と写しを消す", st == 200 and y.get("state") == "none" and not os.path.exists(path)
              and not (os.path.isdir(os.path.join(os.path.dirname(path), "run")) and os.listdir(os.path.join(os.path.dirname(path), "run"))),
              (j or {}).get("message"))


def check_secret_leak(work, rep):
    """偽の cookie の値が、Dropbox(診断・送り返し)・アプリのログに入っていない"""
    hits = []
    for top in (os.path.join(work, "dropbox"), os.path.join(work, "FriendApp", "data", "app", "outbox"), os.path.join(work, "FriendApp", "data", "app", "friendapp", "logs")):
        for root, _dirs, files in os.walk(top):
            for n in files:
                p = os.path.join(root, n)
                try:
                    if os.path.getsize(p) > 50 * 1024 ** 2:
                        continue
                    with open(p, "rb") as f:
                        if FAKE_COOKIE.encode("ascii") in f.read():
                            hits.append(os.path.relpath(p, work))
                except OSError:
                    pass
    rep.check("YouTube のログインの cookie が Dropbox・送り返し・ログに入っていない", not hits, ", ".join(hits))


# ---------------------------------------------------------------- 7 依頼(ドロップ → 送る → 作る)
def make_video(app, path, sec=12):
    """同梱の ffmpeg で小さな動画(音つき・話し声は無い)。開発の ffmpeg は使わない"""
    ff = os.path.join(app, "tools", "ffmpeg", "ffmpeg.exe")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=%d" % sec,
           "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % sec, "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", path]
    subprocess.run(cmd, check=True, creationflags=CHILD_FLAGS, capture_output=True, timeout=120)


def drop_file(w, path, target="#dropZone"):
    """本物のドロップ(CDP の Input.dispatchDragEvent = OS から落としたのと同じ File が画面に届く)"""
    box = w.eval("(s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }", target)
    if not box:
        raise RuntimeError("落とす所 %s が見えません" % target)
    cdp = w.page.context.new_cdp_session(w.page)
    data = {"items": [], "files": [path], "dragOperationsMask": 1}
    for kind in ("dragEnter", "dragOver", "drop"):
        cdp.send("Input.dispatchDragEvent", {"type": kind, "x": box[0], "y": box[1], "data": data})
    cdp.detach()


def file_rows(w):
    return w.eval("() => Array.from(document.querySelectorAll('#fileList li')).map(li => li.textContent)")


def send_request(w, media, rep, timeout):  # lint: long 送るの一続き(落とす 2 回 → 送る → 届くまで待つ)
    """動画を 2 回落として 1 本だけ入る → [送る] → 届いた行 -> 行"""
    drop_file(w, media)
    rows1 = wait_for(lambda: [r for r in file_rows(w) if "読み込んで" not in r] or None, 30, every=0.5) or []
    drop_file(w, media, "#dropMore")
    time.sleep(2)
    rows2 = file_rows(w)
    rep.check("本物のドロップで動画が送る欄に入る(exe がパスを読む)", len(rows1) == 1, rows1)
    rep.check("同じ動画を 2 回落としても 1 本のまま(ドロップで二重にならない)", len(rows2) == 1, rows2)
    rep.check("ファイル名の頭の【】から配信者を推す", any(STREAMER in r for r in rows2), rows2)
    if len(rows2) != 1:
        return None
    w.eval("() => document.getElementById('btnSend').click()")
    inbox = {}

    def sent():
        st, j = w.api("GET", "/api/friend/inbox")
        rows = (j or {}).get("rows") or []
        if rows:
            inbox["row"] = rows[0]
        return bool(rows)
    rep.check("[送る] で受信箱に行ができる", wait_for(sent, 30, every=1), (inbox.get("row") or {}).get("state"))
    if not inbox.get("row"):
        return None
    rid = inbox["row"]["id"]

    def finished():
        w.watch_tree()
        st, j = w.api("GET", "/api/friend/inbox")
        r = next((x for x in (j or {}).get("rows") or [] if x.get("id") == rid), None)
        if r:
            inbox["row"] = r
        return r is not None and r.get("state") in ("arrived", "failed", "done")
    wait_for(finished, timeout, every=5)
    r = inbox["row"]
    rep.check("② が処理して届いた(この PC で作る)", r.get("state") == "arrived", "%s %s" % (r.get("state"), r.get("error") or r.get("note") or ""))
    return r


# ---------------------------------------------------------------- 7b URL の依頼・区間 5 つ(疑似モード = YouTube の代わりに手元の動画)
RANGES = [[5, 11], [20, 26], [35, 41], [50, 56], [65, 71]]   # 5 本(友人が 5 本頼んで 1 本しか来ない、が無いこと)
FAKE_VID = "pfFiveClip1"


def block_ytdlp_net(app):
    """同梱の yt-dlp.exe がネットへ出ない守り(疑似モードでは呼ばれないはず。呼ばれてもつながらない)= 隣の yt-dlp.conf(yt-dlp の置き場所の設定)"""
    d = os.path.join(app, "tools", "yt-dlp")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "yt-dlp.conf"), "w", encoding="utf-8") as f:
        f.write("--proxy http://127.0.0.1:9\n--socket-timeout 5\n")


def send_five(w, app, work, rep, timeout):
    """区間 5 つの URL の依頼を送る → ② が作る → 受け取る画面に 5 本そろう -> 行か None"""
    make_video(app, fake_media(work), sec=80)
    st, j = w.api("POST", "/api/friend/send", {"url": "https://www.youtube.com/watch?v=" + FAKE_VID, "ranges": RANGES, "streamer": STREAMER,
                                                "people": [], "videoTracks": 1, "title": "区間 5 つの検査", "channel": STREAMER})
    row = (j or {}).get("row") or {}
    if not rep.check("区間 5 つの URL の依頼を送れる", st == 200 and row.get("id"), j):
        return None
    rid, got = row["id"], {}

    def finished():
        w.watch_tree()
        st, j = w.api("GET", "/api/friend/inbox")
        r = next((x for x in (j or {}).get("rows") or [] if x.get("id") == rid), None)
        if r:
            got["row"] = r
        return r is not None and r.get("state") in ("arrived", "failed", "done")
    wait_for(finished, timeout, every=5)
    r = got.get("row") or {}
    rep.check("区間 5 つ: ② が処理して届いた", r.get("state") == "arrived", "%s %s" % (r.get("state"), r.get("error") or ""))
    mine = lambda: [it for it in receive_items(w) if it.get("id") == rid]
    items = wait_for(lambda: (lambda x: x if len(x) == len(RANGES) and all(it.get("preview") for it in x) else None)(mine()), 180, every=4) or mine()
    rep.check("区間 5 つ: 受け取る画面に 5 本そろう(1 本ずつ・確認用の動画つき)", len(items) == len(RANGES) and all(it.get("preview") for it in items),
              [(it.get("num"), it.get("seconds"), it.get("preview")) for it in items])
    secs = sorted(round(it.get("seconds") or 0) for it in items)   # パックの素材 = 区間(前後 2 秒)+ 余白 10 秒 + 編集の前後 10 秒(元の動画の端で短くなる)
    rep.check("区間 5 つ: どれも頼んだ区間を含む長さ(6〜50 秒)", secs and all(6 <= s <= 50 for s in secs), secs)
    return r


# ---------------------------------------------------------------- 8 届く物・再生
def probe(app, path):
    """同梱の ffprobe で 1 本目の映像と音 -> {vcodec, pix, h, acodec}"""
    fp = os.path.join(app, "tools", "ffmpeg", "ffprobe.exe")
    r = subprocess.run([fp, "-v", "error", "-show_entries", "stream=codec_type,codec_name,pix_fmt,height", "-of", "json", path],
                       capture_output=True, creationflags=CHILD_FLAGS, timeout=60)
    d = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    v = next((s for s in d.get("streams") or [] if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams") or [] if s.get("codec_type") == "audio"), {})
    return {"vcodec": v.get("codec_name"), "pix": v.get("pix_fmt"), "h": v.get("height"), "acodec": a.get("codec_name")}


PLAY_JS = """async (src) => {
  const v = document.createElement('video'); v.muted = true; v.preload = 'auto'; v.src = src;
  v.style.position = 'fixed'; v.style.left = '-2000px'; document.body.appendChild(v);
  const r = await new Promise(res => {
    const t = setTimeout(() => res({ok: false, why: 'timeout', rs: v.readyState, err: v.error && v.error.code}), 25000);
    v.addEventListener('error', () => { clearTimeout(t); res({ok: false, why: 'error', err: v.error && v.error.code}); });
    v.addEventListener('timeupdate', () => { if (v.currentTime > 0.4) { clearTimeout(t); res({ok: true, w: v.videoWidth, h: v.videoHeight, dur: v.duration}); } });
    v.play().catch(e => {});
  });
  v.pause(); v.remove(); return r; }"""


def receive_items(w):
    st, j = w.api("GET", "/api/friend/receive")
    return [it for s in (j or {}).get("sections") or [] for it in s.get("items") or []]


def check_play(w, it, label, rep):
    src = "api/friend/media?id=%s&name=%s" % (_q(it["id"]), _q(it["name"]))   # 受け取る画面(receive.js)と同じ URL
    got = w.eval(PLAY_JS, src)
    return rep.check("%s: 受け取る画面の <video> で再生できる" % label, got.get("ok") and got.get("w"), got)


def _q(s):
    import urllib.parse
    return urllib.parse.quote(str(s), safe="")


def check_local_delivery(w, app, row, rep):
    """この PC で作った物: 確認用の動画の形と再生 -> 受け取る画面の 1 本(無ければ None)"""
    items = [it for it in receive_items(w) if it.get("id") == row["id"]]
    rep.check("受け取る画面にこの PC で作った物が出る", bool(items), len(items))
    if not items:
        return None
    # 確認用の動画は届いたあとに裏の糸が作る(友人の PC でも画面は届いた直後から見える)ので、できるまで待つ(重い PC では数十秒かかる)
    it = wait_for(lambda: next((x for x in receive_items(w) if x.get("id") == row["id"] and x.get("preview")), None), PREVIEW_WAIT_S, every=1.0) or items[0]
    rep.check("確認用の動画がある", it.get("preview"), it)
    pk = next((p for p in row.get("packs") or [] if p.get("name") == it["name"]), {})
    prev = _inbox_pack(app, row["id"], it["name"]).get("preview")
    if prev and os.path.isfile(prev):
        pr = probe(app, prev)
        rep.check("確認用の動画は再生できる形(h264・yuv420p・高さ 480 以下)", pr["vcodec"] == "h264" and pr["pix"] == "yuv420p" and (pr["h"] or 9999) <= 480, pr)
    else:
        rep.check("確認用の動画のファイルがある", False, prev or pk)
    check_play(w, it, "この PC で作った物", rep)
    return it


def _inbox_pack(app, rid, name):
    """受信箱の正(inbox.json)のパック 1 つ(dir・preview はパス = 画面には出さない物)"""
    with open(os.path.join(app, "data", "app", "friendapp", "inbox.json"), encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc.get("rows") if isinstance(doc, dict) else doc
    r = next((x for x in rows or [] if x.get("id") == rid), {})
    return next((p for p in r.get("packs") or [] if p.get("name") == name), {})


def deliver_from_user_pc(work, pack_copy, title, rep):
    """ユーザーの PC が届ける形(② flow/deliver.deliver_one = 1 本ずつ)を偽の Dropbox の /出力/ に。開発の PC のコード = ユーザーの PC の役"""
    from flow import deliver as _deliver
    out = os.path.join(work, "dropbox", "出力")
    rid = _deliver.request_id(time.time())
    z = _deliver.deliver_one(pack_copy, out, _deliver.delivery_name(rid, title), origin="auto")
    meta, prev = _deliver.meta_path_for(z), _deliver.preview_path_for(z)
    ok_meta = False
    try:
        with open(meta, encoding="utf-8") as f:
            m = json.load(f)
        ok_meta = m.get("v") == 1 and m.get("kind") == "clip" and m.get("zip") == os.path.basename(z)
    except (OSError, ValueError):
        m = None
    rep.check("ユーザーの PC が届ける形: 1 本ずつの zip・.preview.mp4・.meta.json が /出力/ に並ぶ", os.path.isfile(z) and os.path.isfile(prev) and ok_meta,
              "%s %s" % (os.path.basename(z), json.dumps(m, ensure_ascii=False)[:200] if m else meta))
    return rid


# ---------------------------------------------------------------- 9 判断・10 更新
def returns(work):
    d = os.path.join(work, "dropbox", "送り返し")
    out = []
    for n in sorted(os.listdir(d)):
        if n.endswith(".verdict.json"):
            try:
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                out.append({"name": n, "bad": True})
    return out


def check_diag(work, rep):
    """診断の記録(notes:docs/spec/friend.md の 13-11): 依頼の分(kind run)が /診断/ に上がり、ユーザー名を含まない。
    診断の仕組みの無い zip(0.99.20 より前)は情報だけ"""
    d = os.path.join(work, "dropbox", "診断")
    got = wait_for(lambda: [n for n in os.listdir(d) if n.endswith(".diag.json")] if os.path.isdir(d) else None, 200, every=4) or []
    if not got and not os.path.isfile(os.path.join(work, "FriendApp", "src", "friendapp", "diag.py")):
        rep.info("診断の記録", "この zip には診断の仕組みが無い(friendapp/diag.py)")
        return
    docs = []
    for n in got:
        with open(os.path.join(d, n), encoding="utf-8") as f:
            docs.append(f.read())
    kinds = sorted({(json.loads(t).get("kind") or "") for t in docs})
    rep.check("診断の記録 .diag.json(依頼の分 run)が /診断/ に上がる", "run" in kinds, kinds)
    user = os.path.basename(os.path.expanduser("~")).lower()
    leak = [n for n, t in zip(got, docs) if len(user) >= 3 and user in t.lower()]
    rep.check("診断の記録にこの PC のユーザー名が入っていない", not leak, ", ".join(leak))


def bump(ver):
    a, b, c = (int(x) for x in ver.split("."))
    return "%d.%d.%d" % (a, b, c + 1)


def make_update(zip_path, work, new_ver):
    """版を上げた全部入りの zip と軽い zip(src/ytt/version.py だけ書き換え・差し替えの sitecustomize.py を足す = 入れ替えた後も偽の通信のまま。
    軽い方は manifest の files が同じで python/・tools/ を入れない)と light 付きの latest.json を偽の /更新/ へ"""
    folder = os.path.join(work, "dropbox", "更新")
    name, lname = "%s-%s.zip" % (bfz.ZIP_PREFIX, new_ver), "%s-%s-light.zip" % (bfz.ZIP_PREFIX, new_ver)
    shim_rel = "python/Lib/site-packages/sitecustomize.py"
    with open(SHIM_SRC, "rb") as f:
        shim = f.read()
    with zipfile.ZipFile(zip_path) as zi, zipfile.ZipFile(os.path.join(folder, name), "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zo, \
            zipfile.ZipFile(os.path.join(folder, lname), "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zl:
        man = json.loads(zi.read("manifest.json").decode("utf-8"))
        for info in zi.infolist():
            if info.filename == "manifest.json":
                continue
            data = zi.read(info.filename)
            if info.filename == "src/ytt/version.py":
                data = re.sub(rb'^VERSION\s*=\s*"[^"]+"', ('VERSION = "%s"' % new_ver).encode("ascii"), data, count=1, flags=re.M)
                man["files"][info.filename] = hashlib.sha256(data).hexdigest()
            zo.writestr(info, data)
            if not info.filename.startswith(bfz.LIGHT_SKIP):
                zl.writestr(info.filename, data)   # info は共有しない(書くと中の位置が変わる)
        zo.writestr(shim_rel, shim)
        man["files"][shim_rel] = hashlib.sha256(shim).hexdigest()
        man["version"] = new_ver
        zo.writestr("manifest.json", json.dumps(man, ensure_ascii=False, indent=1))   # 友人のアプリは manifest の SHA-256 で更新の中身を確かめる
        man["light"] = True
        zl.writestr("manifest.json", json.dumps(man, ensure_ascii=False, indent=1))
    latest = {"version": new_ver, "file": name, "size": os.path.getsize(os.path.join(folder, name)), "sha256": bfz.sha256_file(os.path.join(folder, name)),
              "notes": "配る前の検査", "light": {"file": lname, "size": os.path.getsize(os.path.join(folder, lname)), "sha256": bfz.sha256_file(os.path.join(folder, lname))}}
    with open(os.path.join(folder, "latest.json"), "w", encoding="utf-8") as f:   # zip 2 つのあと
        json.dump(latest, f, ensure_ascii=False)


def update_downloads(work):
    """偽の Dropbox から取った /更新/ の zip の名前(通信の差し替えの記録 net.log から)"""
    out = []
    try:
        with open(os.path.join(work, "net.log"), encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                path = d.get("path") or ""
                if d.get("endpoint") == "files/download" and path.startswith("/更新/") and path.endswith(".zip"):
                    out.append(path.rsplit("/", 1)[1])
    except OSError:
        pass
    return out


def check_update(w, app, work, zip_path, old_ver, rep, timeout):  # lint: long 更新の一続き(置く → 取る → 入れ替える → 新しい版で開く)
    new_ver = bump(old_ver)
    make_update(zip_path, work, new_ver)
    with open(os.path.join(app, "src", "friendapp", "sync.py"), encoding="utf-8") as f:
        knows_light = "-light.zip" in f.read()   # 前の形の友人のアプリ(軽い更新を知らない)は light を無視して全部入りを取る
    w.api("POST", "/api/friend/undo", {"items": []})   # 同期を起こす(押したあとの口 = SYNC_KICK)

    def avail():
        st, j = w.api("GET", "/api/friend/update")
        return j if (j or {}).get("available") and (j or {}).get("version") == new_ver else None
    got = wait_for(avail, timeout, every=3)
    rep.check("偽の /更新/ の新しい版 %s を取って app-%s\\ に入れる" % (new_ver, new_ver),
              got and os.path.isfile(os.path.join(app, "app-" + new_ver, "src", "ytt", "version.py")), got)
    if not got:
        return False
    grabbed = update_downloads(work)
    want = "%s-%s%s.zip" % (bfz.ZIP_PREFIX, new_ver, "-light" if knows_light else "")
    rep.check("取ったのは %s だけ" % want, grabbed == [want], grabbed)
    rep.check("app-%s\\python\\python.exe がある(軽い更新は今の python から写す)" % new_ver, os.path.isfile(os.path.join(app, "app-" + new_ver, "python", "python.exe")))
    old_pid = w.proc.pid
    st, j = w.api("POST", "/api/friend/update/apply", {})
    rep.check("[更新する] が受け付けられる", st == 200, j)
    w.watch_tree()
    w.close()
    try:
        w.proc.wait(timeout=90)
        ended = True
    except subprocess.TimeoutExpired:
        ended = False
    rep.check("古い exe が終わる(入れ替えのため)", ended)
    if not ended:
        return False

    def new_page():
        try:
            pg = w.connect(timeout=10)
        except RuntimeError:
            return None
        try:
            v = pg.evaluate("() => { const m = document.querySelector('meta[name=ytt-version]'); return m ? m.content : null; }")
        except Exception:   # noqa: BLE001  (読み込みの途中)
            v = None
        if v == new_ver:
            return v
        w.close()
        return None
    v = wait_for(new_page, 120, every=2)
    rep.check("新しい exe が新しい版 %s で開き直す" % new_ver, v == new_ver, v)
    pids = [p for p in list_processes() if p["Name"].lower() == bfz.LAUNCHER_EXE.lower() and p["ParentProcessId"] == old_pid]   # 古い exe が起こした物だけ
    w.proc = _Adopted(pids[0]["ProcessId"]) if len(pids) == 1 else w.proc
    try:
        with open(os.path.join(app, "app-versions.json"), encoding="utf-8") as f:
            cur = json.load(f).get("current")
    except (OSError, ValueError):
        cur = None
    rep.check("app-versions.json の current が新しい版", cur == new_ver, cur)
    return v == new_ver


class _Adopted:
    """入れ替えで exe が自分で起こした新しい exe(PID だけ持つ。止めるのは PID で)"""

    def __init__(self, pid):
        self.pid = pid

    def wait(self, timeout=None):
        end = time.time() + (timeout or 0)
        while True:
            if not any(p["ProcessId"] == self.pid for p in list_processes()):
                return 0
            if time.time() >= end:
                raise subprocess.TimeoutExpired("FriendApp.exe", timeout)
            time.sleep(1)


# ---------------------------------------------------------------- 11 片付け
def shutdown(w, rep):
    """[すべて止めて終了] と同じ止め方 → exe と子孫が残らないか。残った物は自分の PID だけ止める"""
    w.watch_tree()
    try:
        if w.page is not None:
            w.api("POST", "/api/shutdown", {})
    except RuntimeError:
        pass
    w.close()
    try:
        w.proc.wait(timeout=60)
        ended = True
    except subprocess.TimeoutExpired:
        ended = False
    rep.check("/api/shutdown で exe が終わる", ended)

    def remaining():   # WebView2 の子は exe が終わったあとも少し遅れて終わる(重い PC では数秒〜十数秒)ので、残りが無くなるまで待つ
        alive = {(p["ProcessId"], p["CreationDate"]) for p in list_processes()}
        return [(pid, name) for pid, (name, cd) in w.seen.items() if (pid, cd) in alive]
    wait_for(lambda: not remaining(), EXIT_WAIT_S, every=1.0)
    left = remaining()
    rep.check("止めたあと子・孫のプロセスが残らない(見た %d 個)" % len(w.seen), not left, ", ".join("%s(%d)" % (name, pid) for pid, name in left))
    for pid, _name in left:
        subprocess.run([TASKKILL, "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=CHILD_FLAGS)   # 自分が起こした exe の子孫だけ・PID で


# ---------------------------------------------------------------- 全体
def run(args):  # lint: long 検査の一本の流れ(上の説明の 1〜11 の順)
    work = os.path.abspath(args.work or tempfile.mkdtemp(prefix="ytt-pf-"))
    if len(work) > WORK_MAX:   # zip の中の深い名前(python の部品)が 260 文字を超えて展開できない = 友人のアプリのフォルダも浅い所の前提
        raise Preflight("一時フォルダのパスが長すぎます(%d 文字。%d 文字まで): %s" % (len(work), WORK_MAX, work))
    os.makedirs(work, exist_ok=True)
    rep = Report(os.path.join(work, REPORT))
    w = None
    try:
        zip_path = args.zip or build_zip(work, args)
        rep.info("zip", zip_path)
        lay = make_work(work, zip_path, args, rep)
        app = lay["app"]
        cdp = free_port()
        w = Window(app, friend_env(work, cdp, lay["shim"]), cdp)
        w.start()
        w.connect()
        w.watch_tree()
        check_token(w, rep)
        if not check_setup(w, app, rep, args.timeout_min * 60 * 0.4):
            return rep
        check_login(w, app, rep)
        block_ytdlp_net(app)
        send_five(w, app, work, rep, args.timeout_min * 60 * 0.4)
        media_dir = os.path.join(work, "home", "Videos")
        media = os.path.join(media_dir, "【%s】配る前の検査.mp4" % STREAMER)
        make_video(app, media)
        row = send_request(w, media, rep, args.timeout_min * 60 * 0.5)
        if not row or row.get("state") != "arrived":
            return rep
        it = check_local_delivery(w, app, row, rep)
        if it is None:
            return rep
        pack = _inbox_pack(app, row["id"], it["name"])
        pack_copy = os.path.join(work, "userpc", os.path.basename(pack.get("dir") or "pack"))
        shutil.copytree(pack["dir"], pack_copy)
        auto_rid = deliver_from_user_pc(work, pack_copy, it.get("title") or "検査", rep)
        st, j = w.api("POST", "/api/friend/decide", {"items": [{"id": it["id"], "name": it["name"]}], "verdict": "keep"})
        rep.check("[受け取る] が通る", st == 200, j if st != 200 else "")
        save = os.path.join(work, "home", "Videos", "受け取ったパック")
        rep.check("受け取った物が保存先(%USERPROFILE%\\Videos\\受け取ったパック)に入る",
                  wait_for(lambda: os.path.isdir(save) and any(os.scandir(save)), 20, every=1))
        auto = wait_for(lambda: [x for x in receive_items(w) if x.get("auto")] or None, 240, every=4)
        rep.check("/出力/ の 1 本が同期で受け取る画面に入る(依頼なし)", bool(auto), auto_rid)
        if auto:
            check_play(w, auto[0], "Dropbox から届いた物", rep)
            st, j = w.api("POST", "/api/friend/decide", {"items": [{"id": auto[0]["id"], "name": auto[0]["name"]}], "verdict": "skip"})
            rep.check("[見送る] が通る", st == 200, j if st != 200 else "")
        vds = wait_for(lambda: (lambda v: v if len(v) >= (2 if auto else 1) else None)(returns(work)), 240, every=4) or returns(work)
        judges = sorted(v.get("judge") or "" for v in vds)
        rep.check("判断の記録 .verdict.json(v 2)が /送り返し/ に上がる(受け取る = good・見送る = unknown)",
                  all(v.get("v") == 2 for v in vds) and "good" in judges and (not auto or "unknown" in judges), judges)
        check_diag(work, rep)
        check_secret_leak(work, rep)
        if not args.skip_update:
            check_update(w, app, work, args.update_zip or zip_path, lay["man"]["version"], rep, 240)
        return rep
    except Preflight:
        raise
    except Exception as e:   # noqa: BLE001  (途中で落ちた = 不合格として残す)
        import traceback
        rep.check("検査が最後まで流れる", False, "%s: %s\n%s" % (e.__class__.__name__, e, traceback.format_exc()[-1500:]))
        return rep
    finally:
        if w is not None and w.proc is not None:
            shutdown(w, rep)
        net_summary(work, rep)
        rep.write({"work": work})


def net_summary(work, rep):
    """通信の差し替えの記録: 取得元から返した物・断った先(ネットへ出ようとした所)"""
    p = os.path.join(work, "net.log")
    if not os.path.isfile(p):
        rep.check("展開した写しの python が通信の差し替えを読んだ", False, "net.log が無い")
        return
    kinds, blocked = {}, set()
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            kinds[d.get("kind")] = kinds.get(d.get("kind"), 0) + 1
            if d.get("kind") == "blocked":
                blocked.add(re.sub(r"[?#].*$", "", d.get("url") or "")[:120])
    rep.check("展開した写しの python が通信の差し替えを読んだ", kinds.get("installed"), kinds)
    if blocked:
        rep.info("断ったネットの先(友人の PC では出る通信)", ", ".join(sorted(blocked)[:12]))


def build_zip(work, args):
    """今のコードから zip を作る(キャッシュの物だけ)"""
    out = os.path.join(work, "zip")
    got = bfz.build(out, args.cache, bfz.default_wcpp(), fetch=False)
    return got["zip"]


def main(argv=None):
    _common.console_utf8()
    ap = argparse.ArgumentParser(prog="friend_preflight.py", description="友人に配る zip を、配る前に友人の PC と同じ状態で通しで試す")
    ap.add_argument("--zip", default="", help="試す zip(無ければ今のコードから作る)")
    ap.add_argument("--update-zip", default="", help="更新に使う全部入りの zip(既定は --zip と同じ物。前の形の --zip から今の build へ上がる確かめ)")
    ap.add_argument("--work", default="", help="一時フォルダ(既定は新しく作る。合格なら消す)")
    ap.add_argument("--keep", action="store_true", help="合格でも一時フォルダを残す")
    ap.add_argument("--skip-update", action="store_true", help="更新の入れ替えを試さない")
    ap.add_argument("--break", dest="break_item", default="", choices=("", "ffmpeg"), help="検査が効くかの確かめ: fetch.json からその行を消す")
    ap.add_argument("--cache", default="", help="build_friend_zip のキャッシュ(既定と同じ)")
    ap.add_argument("--timeout-min", type=float, default=25.0, help="全体の待ちの目安(分)")
    a = ap.parse_args(argv)
    a.cache = a.cache or bfz.default_cache()
    for z in (a.zip, a.update_zip):
        if z and not os.path.isfile(z):
            ap.error("zip がありません: %s" % z)
    try:
        import playwright  # noqa: F401  (WebView2 につなぐ)
    except ImportError:
        print("[前提] Playwright がありません(setup/requirements-dev.txt)")
        return 2
    try:
        rep = run(a)
    except (Preflight, bfz.BuildError) as e:
        print("[前提] %s" % e)
        return 2
    work = os.path.dirname(rep.path)
    if rep.failed:
        print("不合格: %d 件(記録 %s。一時フォルダは残しました)" % (len(rep.failed), rep.path))
        return 1
    print("合格(%d 件・%.0f 秒)" % (len([r for r in rep.rows if r["ok"]]), time.time() - rep.t0))
    if not a.keep and not a.work:
        shutil.rmtree(work, ignore_errors=True)
    return 0


def preflight_zip(zip_path, keep=False):
    """build_friend_zip.py --publish から: 作った zip を検査する -> 合格か"""
    rc = main(["--zip", zip_path] + (["--keep"] if keep else []))
    return rc == 0


if __name__ == "__main__":
    sys.exit(main())
