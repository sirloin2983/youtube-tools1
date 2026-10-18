# -*- coding: utf-8 -*-
"""友人の玄関の置き場所(notes:docs/design/friend-history.md の 7 章)。

アプリのフォルダ(home)1 つに全部入る形(7-1。友人が選ぶのは一時保管だけ = ⚙):
    <home>/app-<版>/       版のフォルダ(Python・src・画面の部品。FriendApp.exe が選ぶ)。開発の PC では <home>/src がじかにある
    <home>/tools/          ffmpeg・yt-dlp・Deno・whisper.cpp(初回の取得・zip の中。版をまたぐ)
    <home>/data/           ② の作業データ(YTT_DATA_DIR。モデル・この PC の設定 machine.json・学習データ・待ちの記録)
    <home>/data/app/friendapp/   玄関の記録(受信箱 inbox.json・窓のプロファイル・ログ)
    <home>/data/app/friendapp/secrets/youtube-cookies.txt   YouTube のログインの cookie(FriendApp.exe の LoginForm が書く。秘密 =
                                 Dropbox・診断・送り返し・ログに入れない。yt-dlp には ytt/tools.ytdlp_auth_args が写しで渡す。notes:docs/spec/friend.md の 13-13)
    <home>/data/app/outbox/      送り返し(zip と採否の .verdict.json。同期が Dropbox へ上げる)
    <home>/作業/            一時保管の既定(スタジオの書き出し先 outDir = machine の caseRoot の既定。案件・パック)
home の決め方: 環境変数 YTT_FRIEND_HOME > src の親(親が app-<版> ならもう 1 つ上)。
作業データは YTT_DATA_DIR が決まっていればそれ(テストの inplace も)、無ければ <home>/data。

setup() が、CLI(app/cli.py の use_data_dir・use_studio_data)と同じ順で ② の置き場所を決める(③ の学習の読み込みは渡さない = 学習の束だけ読む)。
"""
import os
import shutil

from flow import learning as _learning, machine as _machine, placement as _placement, studiobook as _studiobook, wire as _wire
from ytt import colors as _colors, datadir as _datadir, fsio as _fsio, layout as _layout, studio_env as _studio_env, tools as _tools

HOME_ENV = "YTT_FRIEND_HOME"
DATA_NAME, CASES_NAME, TOOLS_NAME = "data", "作業", "tools"
FRIEND_DIR = os.path.join("app", "friendapp")
OUTBOX_DIR = os.path.join("app", "outbox")
COOKIES_REL = os.path.join("secrets", "youtube-cookies.txt")   # friend_dir の下(FriendApp.exe の Core.CookiesPath と同じ)
FETCH_NAME = "fetch.json"
KEYS_NAME = "keys.json"
TOOL_EXES = (("YTT_FFMPEG", "ffmpeg.exe"), ("YTT_FFPROBE", "ffprobe.exe"), ("YTT_YTDLP", "yt-dlp.exe"),
             ("YTT_DENO", "deno.exe"), ("YTT_STREAMLINK", "streamlink.exe"))


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


def cookies_path(env=None):
    """YouTube のログインの cookie のファイル(上の説明。無くてもよい)"""
    return os.path.join(friend_dir(env), COOKIES_REL)


def outbox_dir(env=None):
    return os.path.join(data_root(env), OUTBOX_DIR)


def is_maker_data(root):
    """その作業データはユーザーの PC(学習の束を作る側)の物か = <root>/app/prefs.json の intake.folder が空でない(flow/learning.maker_pc と同じ条件)。
    ユーザーの PC で玄関を試しても、本物の作業データに友人の PC 用の物(診断・学習の束の取り込み)を書かないための守り"""
    d = _fsio.read_json_or(os.path.join(root, "app", "prefs.json"), None, kind=dict)
    intake = d.get("intake") if d else None
    folder = intake.get("folder") if isinstance(intake, dict) else None
    return isinstance(folder, str) and bool(folder.strip())


SEARCH_DEPTH = 4   # tools の下を探す深さ(初回の取得で 3 段下に展開される物も見つける。浅く置き直すのは lay_tools_shallow)


def _find_exe(base, exe, depth=SEARCH_DEPTH):
    """base の直下、無ければ depth 段下まで(浅い方・名前順)で最初に見つかった exe のパスか None"""
    level = [base]
    for _ in range(depth + 1):
        nxt = []
        for d in level:
            p = os.path.join(d, exe)
            if os.path.isfile(p):
                return p
            try:
                nxt.extend(sorted((os.path.join(d, n) for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))), key=str.lower))
            except OSError:
                pass
        level = nxt
    return None


def tool_env(tools_dir, env=None):
    """<home>/tools の道具を ② に教える環境変数(PATH の頭に足す・YTT_FFMPEG など。見つかった物だけ。4 段下まで探す)-> 足した {名前: 値}。
    すでに入っている値は、そのファイルがあるうちは変えない(無くなっていれば = 浅く置き直したあとなどは見つけ直す)"""
    env = os.environ if env is None else env
    if not os.path.isdir(tools_dir):
        return {}
    dirs = [tools_dir] + sorted((os.path.join(tools_dir, n) for n in os.listdir(tools_dir) if os.path.isdir(os.path.join(tools_dir, n))), key=str.lower)
    out = {}
    for name, exe in TOOL_EXES:
        if env.get(name) and os.path.isfile(env[name]):
            continue
        p = _find_exe(tools_dir, exe)
        if p:
            out[name] = p
            if os.path.dirname(p) not in dirs:
                dirs.append(os.path.dirname(p))
    out["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
    env.update(out)
    return out


def lay_tools_shallow(tools_dir, log=None):
    """初回の取得で展開した道具(tools/<名前>/ffmpeg-9.0.2.../bin/ffmpeg.exe のように深い所)を tools/<名前>/ の直下(1 段)へ置き直す。
    exe のあるフォルダの直下のファイルを全部移し、空になった深いフォルダは消す(取り終えた目印 .fetched-* は tools/<名前>/ にあるので取り直さない)。
    whisper.cpp-* には触らない。-> 移したファイルの数。何度呼んでもよい(すでに直下にあれば何もしない)"""
    if not os.path.isdir(tools_dir):
        return 0
    moved = 0
    say = log or (lambda msg: None)
    for sub in sorted(n for n in os.listdir(tools_dir) if os.path.isdir(os.path.join(tools_dir, n)) and not n.startswith("whisper.cpp-")):
        base = os.path.join(tools_dir, sub)
        for _name, exe in TOOL_EXES:
            if os.path.isfile(os.path.join(base, exe)):
                continue
            p = _find_exe(base, exe)
            if not p:
                continue
            src_dir = os.path.dirname(p)
            for n in os.listdir(src_dir):
                s = os.path.join(src_dir, n)
                if os.path.isfile(s):
                    os.replace(s, os.path.join(base, n))
                    moved += 1
            first = os.path.relpath(src_dir, base).split(os.sep)[0]   # base の直下の、exe を含んでいた枝
            shutil.rmtree(os.path.join(base, first), ignore_errors=True)
            say("道具を浅く置きました: %s" % os.path.join(sub, exe))
    return moved


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


def api_key_env(root, env=None):
    """YouTube の API キー(<作業データ>/app/keys.json の youtubeApiKey。⚙ で入れる)を環境変数 YTT_YT_API_KEY に
    (ytt/apikey が読む。束・ログ・送り返しには入れない = 10-3 の (f1m))。-> 入れたか。無くても動く(コメントを使わないだけ)"""
    env = os.environ if env is None else env
    if env.get("YTT_YT_API_KEY"):
        return False
    d = _fsio.read_json_or(os.path.join(root, "app", KEYS_NAME), None, kind=dict)
    key = d.get("youtubeApiKey") if d else None
    if isinstance(key, str) and key.strip():
        env["YTT_YT_API_KEY"] = key.strip()
        return True
    return False


def members_env(h, env=None):
    """zip の直下の members.json(配信者の名簿。dev/build_friend_zip.py が home 直下に入れる)を環境変数 YTT_HOLO_MEMBERS に
    (ytt/colors が読む。開発の PC は friend-apps/holo-colors/ のまま = 直下に無ければ何もしない)-> 入れたか"""
    env = os.environ if env is None else env
    p = os.path.join(h, "members.json")
    if (env.get(_colors.MEMBERS_ENV) or "").strip() or not os.path.isfile(p):
        return False
    env[_colors.MEMBERS_ENV] = p
    return True


def setup(env=None, log=None):
    """② の置き場所を決める(何度呼んでもよい)。-> {"home", "data", "friend", "outbox", "cases", "studio"(スタジオなしの台帳)}"""
    env = os.environ if env is None else env
    h = home(env)
    if not (env.get("YTT_DATA_DIR") or "").strip():
        env["YTT_DATA_DIR"] = os.path.join(h, DATA_NAME)
    for name in _datadir.ENV_OVERRIDE.values():   # 指定した根の下だけを使う(CLI の --data-dir と同じ)
        env.pop(name, None)
    lay_tools_shallow(os.path.join(h, TOOLS_NAME))   # 深く展開された道具を直下へ
    tool_env(os.path.join(h, TOOLS_NAME), env)
    members_env(h, env)
    root = data_root(env)
    tx = _datadir.locate("transcribe")
    _wire.setup_places(data_dir=tx, studio_data=None if env.get("TRANSCRIBE_STUDIO_DATA") else _placement.studio_data())
    _learning.apply_places(_learning.learning_dir())
    lay_whisper(os.path.join(h, TOOLS_NAME), tx, log)
    api_key_env(root, env)
    env[_tools.COOKIES_ENV] = cookies_path(env)   # ログインしていなければファイルが無い = yt-dlp に何も足さない(ログインはアプリを起こしたままでよい)
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
