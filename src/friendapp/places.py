# -*- coding: utf-8 -*-
"""友人の玄関の置き場所(F2-1。notes:plan/f1-friend-requirements.md の 7 章・A-15・A-16)。

アプリのフォルダ(home)1 つに全部入る形(7-1。友人が選ぶのは一時保管だけ = F2-5 の ⚙):
    <home>/app-<版>/       版のフォルダ(Python・src・画面の部品。F2-4 の起動役が選ぶ)。F2-2 の仮の渡し方では <home>/src がじかにある
    <home>/tools/          ffmpeg・yt-dlp・Deno・whisper.cpp(初回の取得・zip の中。版をまたぐ)
    <home>/data/           ② の作業データ(YTT_DATA_DIR。モデル・この PC の設定 machine.json・学習データ・待ちの記録)
    <home>/data/app/friendapp/   玄関の記録(受信箱 inbox.json・窓のプロファイル・ログ)
    <home>/data/app/outbox/      送り返し(zip と採否の .verdict.json。F2-3 の同期が Dropbox へ上げる)
    <home>/作業/            一時保管の既定(スタジオの書き出し先 outDir = machine の caseRoot の既定。案件・パック)
home の決め方: 環境変数 YTT_FRIEND_HOME > src の親(親が app-<版> ならもう 1 つ上)。
作業データは YTT_DATA_DIR が決まっていればそれ(テストの inplace も)、無ければ <home>/data。

setup() が、CLI(app/cli.py の use_data_dir・use_studio_data)と同じ順で ② の置き場所を決める(③ の学習の読み込みは渡さない = 学習の束だけ読む)。
"""
import os
import shutil

from flow import learning as _learning, machine as _machine, placement as _placement, studiobook as _studiobook, wire as _wire
from ytt import datadir as _datadir, fsio as _fsio, layout as _layout, studio_env as _studio_env

HOME_ENV = "YTT_FRIEND_HOME"
DATA_NAME, CASES_NAME, TOOLS_NAME = "data", "作業", "tools"
FRIEND_DIR = os.path.join("app", "friendapp")
OUTBOX_DIR = os.path.join("app", "outbox")
FETCH_NAME = "fetch.json"
KEYS_NAME = "keys.json"
TOOL_EXES = (("YTT_FFMPEG", "ffmpeg.exe"), ("YTT_FFPROBE", "ffprobe.exe"), ("YTT_YTDLP", "yt-dlp.exe"),
             ("YTT_DENO", "deno.exe"), ("YTT_STREAMLINK", "streamlink.exe"))   # 送るアプリ(Backend.ChildEnv)と同じ名前
OLD_DATA_NAME = "youtube-tools"   # 前のアプリの作業データ %LOCALAPPDATA%/youtube-tools(A-16 で写して消す元)


def home(env=None):
    """アプリのフォルダ(上の説明)"""
    env = os.environ if env is None else env
    h = (env.get(HOME_ENV) or "").strip()
    if h:
        return os.path.abspath(h)
    up = os.path.dirname(_layout.src_root())
    if os.path.basename(up).lower().startswith("app-"):
        up = os.path.dirname(up)
    return up


def data_root(env=None):
    """② の作業データの根(YTT_DATA_DIR が無ければ <home>/data。inplace なら layout の規則 = src)"""
    env = os.environ if env is None else env
    if (env.get("YTT_DATA_DIR") or "").strip():
        return _machine.root(env)
    return os.path.join(home(env), DATA_NAME)


def friend_dir(env=None):
    return os.path.join(data_root(env), FRIEND_DIR)


def outbox_dir(env=None):
    return os.path.join(data_root(env), OUTBOX_DIR)


def old_data_root(env=None):
    """前のアプリの作業データ(%LOCALAPPDATA%/youtube-tools)か None(場所が分からない・今の作業データと同じ)"""
    env = os.environ if env is None else env
    la = (env.get("LOCALAPPDATA") or "").strip()
    if not la:
        return None
    old = os.path.join(la, OLD_DATA_NAME)
    if os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(data_root(env))) or is_maker_data(old):
        return None
    return old


def is_maker_data(root):
    """その作業データはユーザーの PC(学習の束を作る側)の物か = <root>/app/prefs.json の intake.folder が空でない(flow/learning.maker_pc と同じ条件)。
    ユーザーの PC で玄関を試しても、本物の作業データのモデルを写して消さないための守り"""
    d = _fsio.read_json_or(os.path.join(root, "app", "prefs.json"), None, kind=dict)
    intake = d.get("intake") if d else None
    folder = intake.get("folder") if isinstance(intake, dict) else None
    return isinstance(folder, str) and bool(folder.strip())


def tool_env(tools_dir, env=None):
    """<home>/tools の道具を ② に教える環境変数(PATH の頭に足す・YTT_FFMPEG など。見つかった物だけ)-> 足した {名前: 値}"""
    env = os.environ if env is None else env
    if not os.path.isdir(tools_dir):
        return {}
    dirs = [tools_dir] + sorted((os.path.join(tools_dir, n) for n in os.listdir(tools_dir) if os.path.isdir(os.path.join(tools_dir, n))), key=str.lower)
    out = {}
    for name, exe in TOOL_EXES:
        if env.get(name):
            continue
        for d in dirs:
            p = os.path.join(d, exe)
            if os.path.isfile(p):
                out[name] = p
                break
    out["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
    env.update(out)
    return out


def lay_whisper(tools_dir, tx_data, log=None):
    """zip の tools/whisper.cpp-<版>-<種類>/ を作業データの transcribe/bin/ へ写す(① が読む場所。build.json が同じなら写さない)。-> 写したフォルダの数"""
    if not os.path.isdir(tools_dir):
        return 0
    n = 0
    for name in os.listdir(tools_dir):
        src = os.path.join(tools_dir, name)
        if not (name.startswith("whisper.cpp-") and os.path.isfile(os.path.join(src, "build.json"))):
            continue
        dest = os.path.join(tx_data, "bin", name)
        try:
            with open(os.path.join(src, "build.json"), "rb") as a:
                want = a.read()
            with open(os.path.join(dest, "build.json"), "rb") as b:
                if b.read() == want:
                    continue
        except OSError:
            pass
        shutil.copytree(src, dest, dirs_exist_ok=True)
        n += 1
        if log:
            log("whisper.cpp を作業データへ写しました: %s" % name)
    return n


def api_key_env(roots, env=None):
    """YouTube の API キー(送るアプリの <作業データ>/app/keys.json の youtubeApiKey。roots の順に最初の物)を環境変数 YTT_YT_API_KEY に
    (ytt/apikey が読む。束・ログ・送り返しには入れない = 10-3 の (f1m))。-> 入れたか。無くても動く(コメントを使わないだけ)"""
    env = os.environ if env is None else env
    if env.get("YTT_YT_API_KEY"):
        return False
    for root in roots:
        if not root:
            continue
        d = _fsio.read_json_or(os.path.join(root, "app", KEYS_NAME), None, kind=dict)
        key = d.get("youtubeApiKey") if d else None
        if isinstance(key, str) and key.strip():
            env["YTT_YT_API_KEY"] = key.strip()
            return True
    return False


def setup(env=None, log=None):
    """② の置き場所を決める(何度呼んでもよい)。-> {"home", "data", "friend", "outbox", "cases", "studio"(スタジオなしの台帳)}"""
    env = os.environ if env is None else env
    h = home(env)
    if not (env.get("YTT_DATA_DIR") or "").strip():
        env["YTT_DATA_DIR"] = os.path.join(h, DATA_NAME)
    for name in _datadir.ENV_OVERRIDE.values():   # 指定した根の下だけを使う(CLI の --data-dir と同じ)
        env.pop(name, None)
    tool_env(os.path.join(h, TOOLS_NAME), env)
    root = data_root(env)
    tx = _datadir.locate("transcribe")
    _wire.setup_places(data_dir=tx, studio_data=None if env.get("TRANSCRIBE_STUDIO_DATA") else _placement.studio_data())
    _learning.apply_places(_learning.learning_dir())
    lay_whisper(os.path.join(h, TOOLS_NAME), tx, log)
    api_key_env([root, old_data_root(env)], env)
    studio_home = os.path.abspath(_datadir.locate("studio"))
    _studio_env.set_home(studio_home)
    _studio_env.load_out_dir()
    cases = os.path.join(h, CASES_NAME)
    if not os.path.isfile(_studio_env.p("settings.json")):   # 一時保管の既定(7 章)= 書き出し先(machine の caseRoot の既定もこれ)。選んだ値は変えない
        os.makedirs(cases, exist_ok=True)
        _studio_env.set_out_dir(cases, busy=lambda: False)
    _datadir.register("studio", studio_home)
    book = _studiobook.StudioBook(_studio_env.p(_placement.STUDIO_DATA_NAME))
    for d in (friend_dir(env), outbox_dir(env)):
        os.makedirs(d, exist_ok=True)
    return {"home": h, "data": root, "friend": friend_dir(env), "outbox": outbox_dir(env), "cases": _machine.get("caseRoot") or _studio_env.get_out_dir(),
            "studio": book, "fetch": os.path.join(h, FETCH_NAME)}
