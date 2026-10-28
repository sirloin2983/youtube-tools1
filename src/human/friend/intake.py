"""友人からの依頼の受付(notes:docs/spec/friend.md)。

友人のアプリ(src/friendapp/)が Dropbox に送った依頼を、Dropbox が同期したフォルダで見張り、
まとめて実行(入口の src/app/autorun.py。読み込まない = 入口が runner= で渡す)に入れて ① 全自動(パックまで作って 出力/ へ届ける)で流す。
ホームの起動と一緒に動き、「すべて終了」で止まる。

届くもの(依頼は見張るフォルダの直下だけ。受付済み/・失敗/・出力/ などの下のフォルダは見ない。送り返し/ だけは returns.scan が見る):
  <id>.request.json   友人のプログラムが最後に送る依頼(kind video = 同じ id の動画を文字起こし → パック / url = 配信を解析 → 上位 N 個 → 書き出し →
                      文字起こし → パック / live = ライブ配信)
  <id>__<名前>.mp4 など 友人のプログラムが送った動画(JSON の files に名前がある)
  送り返し/            友人の PC の結果の zip と採否(returns。F1 の F2)
  ほかのファイル(手で置いた動画・URL の .txt など)は受け付けない: 失敗/ へ移し、理由「友人のアプリから送ってください」を添える
  (② 軽く確認 = 文字起こしまでの道は 10-19 に消した。JSON の来ない友人のプログラムの動画も WAIT_FILES 秒たったら同じ扱い)

決まり:
- 同期の途中を読まない: 大きさと更新時刻が SETTLE 秒以上変わらないファイルだけ。友人のプログラムの動画は JSON がそろってから
- 受け付けた元のファイルは 受付済み/YYYY-MM-DD/ へ、断ったものは 失敗/ へ移し「<名前>.理由.txt」を添える(消さない)
- 動画は依頼のフォルダへコピーしてから文字起こしする(書き出し先があれば <書き出し先>/依頼/<日付>_<題>_<id6>/ = 案件、無ければ作業データの
  app/intake/<日付>/<依頼 id>/。_request_dir。Dropbox の「オンラインのみ」や片付けで元が消えても、文書の元のパスが切れない)
  コピーを 30fps(H.264・AAC)にそろえるのは受付ではなく、まとめて実行の最初の段 normalize(② flow/run.py の _step_normalize。submit_file の normalize=True = 封筒の input.normalize)。
  受付は錠の中で短い仕事(大きさ・ffprobe・コピー・案件・submit_file)だけをする = 重い処理の枠 SLOTS を待たない(opt-human 9a-1: 枠を待つ間、
  ライブ配信の依頼・送り返しの見回りが丸ごと止まっていた)
- 同じ動画・同じ配信も断らない(ユーザー: 送り直せるように。配信は解析・切り抜き・文字起こしを使い回す。受け付けた配信は intake-state.json に覚えるだけ)
- 友人が時刻で指定した区間(items[].ranges)・カット(cut)は、形を確かめてまとめて実行へ渡す(notes:docs/spec/friend.md の 2-6)。
  解析の重み(weights)は 10-23 に友人のアプリから消した = 古い友人のアプリから来ても読まない(いつも既定の重み)
- 受付のフォルダ(ホームの設定 intake.folder)と 出力/ の読み方は configured_folder・out_dir_of の 1 か所(入口は Intake.folder()・out_dir() を使う)
- 1 日の件数の上限は無い(件数では断らない・次の日に回さない。今日の件数は画面に出すだけ)
- URL は YouTube の配信・動画だけ。11 文字の ID を取り出し、それだけを yt-dlp に渡す(任意の URL を渡さない)
- 動画は拡張子と ffprobe で形を確かめてから(他人が作ったファイルを ffmpeg で読むこと自体が攻撃の入口になり得るため)
"""
import datetime
import json
import os
import re
import shutil
import threading
import time
import uuid

from flow import order as _order, placement
from flow.deliver import BAD_NAME_CHARS, OUT_DIR   # ファイル名に使えない文字・出力\ の名前(届ける側 ② と同じ 1 か所。ds1)
from flow import spec as _spec   # 区間・重みの理由つきの検査(まとめて実行と同じ。opt-human 9b-2)
from ytt import colors, fsio, names as ytt_names, normalize, schemas, studio_env, textutil, tools, yturl
from . import live_requests  # noqa: E402  (ライブ配信の依頼の設定の検査と一覧の文。結びつきは入口が live_begin= で渡す Live.submit_request が書く。2-15)
from . import bugs  # noqa: E402  (友人の不具合の書き出し 診断\ の *.state.json を仕分けて、要対応なら AI を起こす。10-25)
from . import pubqueue  # noqa: E402  (友人の zip を配る待ちの列と 3 時間ごとの配る回。10-25)
from . import upwatch  # noqa: E402  (友人のアプリの更新の見張り: 配った版・友人の今の版・起動できなかった の知らせ。10-25)
from . import notify  # noqa: E402  (友人の知らせ(見張り・不具合・AI の結果)をまとめ役のセッションへ 1 通にまとめて届ける。10-25)
from . import returns  # noqa: E402  (友人の送り返し 送り返し\ の zip と採否を app/friend-returns へ並べる。F1 の F2)

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
REQ_SUFFIX = ".request.json"
DONE_DIR, FAIL_DIR = "受付済み", "失敗"   # 出力\(OUT_DIR = ① 全自動のパック。友人のアプリの「受け取る」が読む)は届ける側 ② flow/deliver の 1 か所
FLOW_LABELS = {"auto": "① 全自動"}   # 友人の依頼は常に ①
MANUAL_REASON = "友人のアプリから送ってください(手で置いたファイルは受け付けません)"   # 依頼の JSON の無いファイル(手で置いた動画・.txt など)を断る理由
OLD_FLOWS = ("auto", "check", "manual")   # 依頼の flow の値(友人の依頼は全部 ① に読み替え、auto 以外の元の値は記録の flowOrig に残すだけ)
REQ_KINDS = ("video", "url", "live")   # 依頼の種類(live = ライブ配信。2-15)
NOTE_LABELS = ("配信者", "ライブ配信")   # 受け付けた・断ったの数に入れない知らせの行
REQ_DIRS_MAX = 64   # 依頼 id -> 置き場所の覚えの数(古い物から忘れる。速さのためだけ = 忘れても placement.find_request_dir で同じフォルダを引く)
REQ_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
APP_FILE_RE = re.compile(r"^(\d{8}-\d{6}-[0-9a-f]{6})__(.+)$")   # 友人のプログラムが送った動画の名前
TEXT_MAX = 64 * 1024
MAX_URLS = 10            # 1つの依頼に書ける配信の数(① 探す から一度に入れられる数と同じ)
SETTLE = 20.0            # 大きさと更新時刻がこの秒数変わらなければ、同期が終わったとみなす
INTERVAL = 30.0          # 見る間隔
WATCH = True             # スイッチ: 見る間隔の間もフォルダの直下と 送り返し\ の名前・大きさ・更新時刻を WATCH_SEC ごとに比べ、変わったらすぐ見る・
                         # 落ち着くのを待っている物があれば落ち着く時刻に見る・依頼の JSON は REQ_SETTLE 秒で落ち着いたとみなす(False = 前の通り)
WATCH_SEC = 2.0          # 比べる間隔(名前の一覧を読むだけ = 軽い)
REQ_SETTLE = 5.0         # 依頼の JSON(数 KB。Dropbox のアプリは書き終えてから置く)が落ち着いたとみなす秒
WAIT_FILES = 3600.0      # JSON があるのに動画がそろわないとき、断るまで待つ秒数
KEEP_REQUESTS = 50       # 画面に出す最近の依頼の数
STATE_FILE = "intake-state.json"
# OS・同期のアプリが勝手に置くファイル(依頼ではない)。断って 失敗\ へ移すと、すぐまた作られて「断った」が毎回増えるので、見ない
OS_FILES = ("desktop.ini", "thumbs.db", "ehthumbs.db", ".ds_store", "icon\r", ".dropbox", ".dropbox.attr")
_HIDDEN = 0x2 | 0x4   # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
STATE_LABELS = {"off": "オフ", "watching": "見張り中", "error": "止まっています"}
REQ_LABELS = {"accepted": "受け付けた", "rejected": "断った"}
DAILY_KEEP_DAYS = 7   # 日ごとの数(受け付けた件数・友人の「要らない」の本数)を残す日数


def configured_folder(prefs, defaults=None):
    """ホームの設定の受付のフォルダ(intake.folder。オンかオフかは見ない)。決まっていない・設定が読めなければ ""。
    受付・手で届ける・ライブの自動の届け先・自動の片付け・学習の束が同じ読み方をする 1 か所"""
    try:
        cfg = prefs.get(["intake"])["intake"] or {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        cfg = defaults or {}
    folder = cfg.get("folder") if isinstance(cfg, dict) else ""
    return folder if isinstance(folder, str) else ""


def out_dir_of(folder):
    """受付のフォルダの 出力\\(友人のアプリの「受け取る」が読む)。folder が空なら None"""
    return os.path.join(folder, OUT_DIR) if folder else None


def submit_urls(runner, items, request_id=None, deliver_dir=None, speakers=None, video_tracks=None, cut=None, streamer=None):
    """友人からの依頼(配信の URL)を、配信ごとに ② の口 submit へ(RV A1。欄 → 封筒 + 束の差分は flow/order.py)。いつも ① 全自動 = パックまで・送り直しは作り直す。
    items = [{"id": 配信 ID, "top": 1〜30, "title", "channel", "ranges"?, "duration"?}]。
    ranges = 時刻で指定した区間 [(開始, 終了)](top に足りない分は自動で埋める)。cut = カットの方法。
    streamer = 照らし合わせ済みの配信者の名前か None(None・空ならチャンネル名などから自動)。
    -> {"runs": [受けた実行の public], "skipped": [{"id", "title", "reason"}]}(断った理由 = 形が違う・同じ配信が待ち・実行中・待ちが多すぎる など)"""
    runs, skipped = [], []
    for it in items:
        it = it if isinstance(it, dict) else {}
        vid, top = it.get("id"), it.get("top")
        title, channel = str(it.get("title") or "").strip()[:120], str(it.get("channel") or "").strip()[:100]
        try:
            ranges = _spec.clean_ranges(it.get("ranges"))
            if not (isinstance(vid, str) and yturl.VID_RE.match(vid)) or not _spec.key_ok("adopt", "top", top):   # 本数の範囲は束の検査と同じ(spec.top_arg)
                raise ValueError("配信の指定が正しくありません")
            env, diff = _order.order("url", video_id=vid, title=title or vid, fresh={"title": title, "channel": channel}, duration=it.get("duration"),
                                     upto="pack", top=top, ranges=ranges, cut=cut, video_tracks=video_tracks, speakers=speakers,
                                     repack=True, streamer=streamer or None, request_id=request_id, deliver_dir=deliver_dir)
            runs.append(runner.submit(env, diff))   # ① の送り直しは、前のパックがあっても今回の設定(カット・映像トラック)で作り直して届ける(repack)
        except ValueError as e:
            skipped.append({"id": str(vid or "")[:40], "title": title, "reason": str(e)})
    return {"runs": runs, "skipped": skipped}


def submit_file(runner, path, title="", streamer=None, request_id=None, deliver_dir=None, speakers=None, video_tracks=None, cut=None,
                normalize=True):
    """友人が切り抜いた動画の依頼(作業データへの写し)を ② の口 submit へ(RV A1)-> 実行の public。いつも ① 全自動 = パックまで。
    normalize = 最初の段で写しを 30fps に置き換える(写しだけに使う)。形が違えば ValueError"""
    env, diff = _order.order("file", path=path, title=str(title or os.path.basename(str(path or ""))), normalize=normalize is True,
                             upto="pack", streamer=streamer or None, request_id=request_id,
                             deliver_dir=deliver_dir, speakers=speakers, video_tracks=video_tracks, cut=cut)
    return runner.submit(env, diff)


def youtube_id(url):
    """YouTube の配信・動画の URL -> 11 文字の ID(ほかは None)。watch?v= / youtu.be/ / live/ / shorts/ / embed/。
    読み方は ytt/yturl.parse_video_id の strict(素の ID は受けない・/watch は完全一致)"""
    return yturl.parse_video_id(url, strict=True)


def parse_lines(text, default_top):
    """URL の行(依頼の JSON の items を「URL 数」の行にした物)->([{"id", "top", "line"}], [{"line", "reason"}])。1行に「URL [数]」。空の行・# の行は無視"""
    ok, bad = [], []
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        vid = youtube_id(parts[0])
        top = default_top
        if len(parts) >= 2 and re.fullmatch(r"\d+", parts[1]):
            top = int(parts[1])
            rest = parts[2:]
        else:
            rest = parts[1:]
        if not vid:
            bad.append({"line": line[:200], "reason": "YouTube の配信・動画の URL ではありません"})
        elif top < 1:   # 上限なし(10-20。友人が指定した数をそのまま)
            bad.append({"line": line[:200], "reason": "切り抜く数は 1 以上にしてください"})
        elif rest and not rest[0].startswith("#"):
            bad.append({"line": line[:200], "reason": "URL と数のあとに余計な文字があります(メモは # のあとに書いてください)"})
        else:
            ok.append({"id": vid, "top": top, "line": line[:200]})
    return ok, bad


def decode_text(raw):
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _accepted(items):
    """一覧の行に、知らせ(NOTE_LABELS)以外で受け付けたものがあるか"""
    return any(i["state"] == "accepted" and i.get("label") not in NOTE_LABELS for i in items)


def probe_video(path):
    """ffprobe で動画の形を確かめる -> {"ok", "duration" (秒 か None), "reason"}。ok = 音声がある(文字起こしに要る)。
    調べ方は ytt.normalize.probe(30fps の判定と同じ ffprobe の呼び方。YTT_FFPROBE も見る)"""
    fp = tools.find_tool("ffprobe")
    if not fp:
        return {"ok": False, "duration": None, "reason": "ffprobe が見つからないので、動画を確かめられません"}
    info = normalize.probe(path, ffprobe=fp)
    if info is None or not info["has_audio"]:   # 読めない(壊れている・時間切れ)・音声が無い
        return {"ok": False, "duration": None, "reason": "音声のある動画として読めませんでした"}
    return {"ok": True, "duration": info["duration"], "reason": ""}


def youtube_info(vid):
    """yt-dlp で配信の長さ・状態・題名・チャンネルを調べる(ダウンロードしない)。-> dict か None(調べられない)。
    配信の前(予約)は形式が無いので yt-dlp がエラーで終わる(「This live event will begin in …」)→ --ignore-no-formats-error で live_status is_upcoming を
    出させる(呼び方は ytt/tools.ytdlp_print_cmd = flow/livesession.py の probe_live と同じ)。古い yt-dlp はそれでもエラーで返すので、その文があれば is_upcoming とみなす。"""
    if studio_env.fake():   # 疑似の旗の持ち主(STUDIO_FAKE=1。RS5-D)
        return {"duration": 600.0, "live": "not_live", "title": "疑似タイトル(%s)" % vid, "channel": ""}
    yd = tools.find_tool("yt-dlp")
    if not yd or not yturl.VID_RE.match(vid or ""):
        return None
    try:
        r = tools.run(tools.ytdlp_print_cmd(yd, yturl.watch_url(vid), "%(duration)s\t%(live_status)s\t%(channel)s\t%(title)s"), timeout=90, err_tail=40)
    except OSError:
        return None
    if r.why == "timeout":
        return None
    if r.code != 0:
        err = r.err.decode("utf-8", "replace")
        if "will begin" in err or "Premieres in" in err:   # 古い yt-dlp は配信の前をエラーで返す(題・チャンネルは分からない)
            return {"duration": None, "live": "is_upcoming", "channel": "", "title": ""}
        return None
    parts = (r.out.decode("utf-8", "replace").strip().splitlines() or [""])[-1].split("\t")
    if len(parts) < 4:
        return None
    try:
        dur = float(parts[0])
    except ValueError:
        dur = None
    return {"duration": dur, "live": parts[1], "channel": parts[2][:100] if parts[2] != "NA" else "", "title": parts[3][:120] if parts[3] != "NA" else ""}


def _is_os_file(name, path=None):
    """依頼として扱わないファイル: OS・同期のアプリが置くもの・隠しファイル・システムのファイル(Windows の属性)"""
    if name.lower() in OS_FILES:
        return True
    if path and os.name == "nt":
        try:
            return bool(getattr(os.stat(path), "st_file_attributes", 0) & _HIDDEN)
        except OSError:
            return False
    return False


CUT_LABELS = {"none": "カットしない", "silence": "無音で削る"}   # 受付の記録の文(カットの検査は ② flow/order.cut_arg = spec.CUTS)


_hms = schemas.fmt_hms


def parse_ranges(v):
    """依頼の区間 [{"start": 秒, "end": 秒}, …]-> ([(開始, 終了)], [断った理由])。受付の口(アプリの形を読むだけ)。
    検査は ② flow/spec.check_ranges(0 ≤ 開始 < 終了・個数の上限は flow/spec の RANGE_MAX = ytt/marks の値・1 つの長さの上限なし = 要件 C-2-7・C-5-5・小数 1 桁に丸めて長さ 0 は断る。
    形が違うものだけ断る = ほかは進める。まとめて実行の clean_ranges と同じ検査。opt-human 9b-2)"""
    if v is None:
        return [], []
    if not isinstance(v, list):
        return [], ["区間の形が正しくありません"]
    return _spec.check_ranges([(r.get("start"), r.get("end")) if isinstance(r, dict) else None for r in v[:50]])


def _safe_name(name):
    """JSON に書かれたファイル名がフォルダの直下の名前か(区切り・..・ドライブを含まない)"""
    return (isinstance(name, str) and 0 < len(name) <= 240 and name not in (".", "..") and not any(c in name for c in '/\\:*?"<>|')
            and not any(ord(c) < 32 for c in name))


def _streamer(name):
    """配信者の名前 -> (照らし合わせた名前 か None, 知らせ)"""
    s = str(name or "").strip()
    if not s:
        return None, ""
    try:
        who, _hex = colors.resolve(s)
        return who, ""
    except ValueError:
        return None, "配信者「%s」がメンバーと合わないので、字幕の色なしで進めます" % s[:60]


class Intake:
    def __init__(self, prefs, runner, data_dir, log=None, clock=None, probe=None, info=None, interval=INTERVAL, settle=SETTLE,
                 feedback=None, live_begin=None, defaults=None, flush=None):
        """prefs: src/app/prefs.py の Prefs(節 intake)。defaults: 設定が読めないときに使う節の既定(入口が prefs.DEFAULTS["intake"] を渡す。
        prefs を読み込まない = app の部品に依存しない。None = 空 = オフ扱い)。runner: まとめて実行を返す関数(AutoRunner)。data_dir: ホームの作業データ(app)。
        probe・info: 動画・配信を調べる関数(テストで差し替える)。30fps にそろえるのはまとめて実行の段 normalize(opt-human 9a-1)。
        feedback: 送り返しの判断(.verdict.json の bad・unknown)で届けたパックを片付ける関数 -> {"ok", "summary"/"reason"}(入口が friend_feedback.apply を渡す。
        returns.scan へ渡すだけ。None = 片付けない)。
        live_begin(url, ctx): ライブ配信の依頼で録画を始めて結びつける関数 -> {"recorder", "recording", "existing"}(入口が Live.submit_request を渡す。
        だめなら ValueError か live_export.LiveError。None = ライブ配信の依頼を断る)。
        flush(): 見回りの終わりに呼ぶ = 届けられなかった自動の分の送り直し(D-SEND 2-6。入口がまとめて実行の flush_pools を渡す。
        受付のフォルダがあるときだけ・受付がオフでも呼ぶ。None = 呼ばない)"""
        self.prefs, self.runner, self.data_dir = prefs, runner, data_dir
        self.defaults = defaults
        self.feedback = feedback
        self.flush = flush
        self.live_begin = live_begin
        self.log = log or (lambda msg: None)
        self.clock = clock or time.time
        self.probe = probe or probe_video
        self.info = info or youtube_info
        self.interval, self.settle = interval, settle
        self.state_path = os.path.join(data_dir, STATE_FILE)
        self.lock = threading.Lock()        # 見る処理(scan)を1つずつ
        self.wake = threading.Event()
        self.closed = False
        self.thread = None
        self._req_dirs = {}                 # 依頼 id -> (動画の置き場所, 案件か)。同じ依頼の動画を 1 つのフォルダに集める(REQ_DIRS_MAX 件まで)
        self._seen_size = {}                # パス -> (大きさ, 更新時刻, 最初に今の形で見た時刻)
        self.state = "off"
        self.message = ""
        self.last_scan = None
        self.st = self._load_state()

    # ------------------------------------------------------------ 覚えておく中身
    def _load_state(self):
        try:
            d = fsio.read_json_file(self.state_path, 2 * 1024 * 1024)
        except (OSError, ValueError):
            d = None
        d = d if isinstance(d, dict) else {}
        # daily = 日ごとの受け付けた件数(10-19 までの videos = 受け付けた配信の覚えは、依頼済みの確かめと一緒に消した = 読み捨て)
        return {"daily":d.get("daily") if isinstance(d.get("daily"), dict) else {},
                # desktop.ini などを断った記録は外す
                "requests": [r for r in d.get("requests") or [] if isinstance(r, dict) and not _is_os_file(str(r.get("title") or ""))][:KEEP_REQUESTS]}

    def _save_state(self):
        since = (datetime.date.fromisoformat(self._today()) - datetime.timedelta(days=DAILY_KEEP_DAYS)).isoformat()
        self.st["daily"] = {day: v for day, v in self.st["daily"].items() if day >= since}
        try:
            fsio.atomic_write(self.state_path, json.dumps(dict(self.st, v=1), ensure_ascii=False).encode("utf-8"))
        except OSError as e:
            self.log("依頼の受付: 記録を書けませんでした(%s)" % tools.why(e))

    def _today(self):
        return datetime.datetime.fromtimestamp(self.clock()).date().isoformat()

    # ------------------------------------------------------------ 動かす・止める
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="intake", daemon=True)
            self.thread.start()

    def close(self):
        self.closed = True
        self.wake.set()

    def _loop(self):
        while not self.closed:
            try:
                self.scan()
            except Exception as e:   # 想定外でも見張りは続ける(次の回でやり直す)
                # 画面には「何が起きたか + どうするか」だけ。例外の名前・原文はログへ(UI の見直し M9)
                self.state, self.message = "error", "依頼を読めませんでした(依頼のファイルの形が違うか、読み取りで問題が起きました)。次の確認でもう一度試します。続くときは、詳しくの「ログ」を見てください"
                self.log("依頼の受付: 内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]))
            # 見る間隔: 設定の interval(段9 9-4。ホームの「依頼の受付」で変える)。テストで interval を渡したときはそれ
            self._wait_next(self.interval if self.interval != INTERVAL else float(self._cfg().get("interval") or INTERVAL))
            self.wake.clear()

    def _wait_next(self, interval):
        """次に見るまで待つ: interval 秒・wake・(WATCH のとき)フォルダの変化か、落ち着くのを待っている物の落ち着く時刻の早いほう"""
        if not WATCH:
            self.wake.wait(interval)
            return
        due = self._settle_due()
        left = min(interval, due) if due is not None else interval
        end = time.monotonic() + left
        sig = self._signature()
        while not self.closed:
            rest = end - time.monotonic()
            if rest <= 0 or self.wake.wait(min(WATCH_SEC, rest)):
                return
            if self._signature() != sig:
                return

    def _settle_due(self):
        """落ち着くのを待っている物が落ち着くまでの秒(一番早い物。無ければ None)"""
        now, dues = self.clock(), []
        for p, (_size, mtime, seen) in list(self._seen_size.items()):
            need = self._settle_of(p)
            due = max(seen + need, mtime + need) - now
            if due > -1:   # もう落ち着いた物(動画の JSON 待ちなど)は数えない = 見る間隔のまま
                dues.append(max(due, 0) + 0.5)
        return min(dues) if dues else None

    def _settle_of(self, p):
        return min(self.settle, REQ_SETTLE) if WATCH and p.endswith(REQ_SUFFIX) else self.settle

    def _signature(self):
        """フォルダの直下と 送り返し\\ の名前の集まり(読めなければ None)。大きさの変化(同期の途中)は見ない = 落ち着く時刻で見る"""
        folder = self.folder()
        if not folder or fsio.is_network_path(folder):
            return None
        out = []
        for d in (folder, os.path.join(folder, returns.IN_DIR)):
            try:
                out += [(d, n) for n in os.listdir(d)]
            except OSError:
                continue
        return frozenset(out)

    def snapshot(self):
        cfg = self._cfg()
        # 見る処理が長い(大きな動画のコピー・yt-dlp の問い合わせ)ときに画面の表示を止めないよう、ロックは短く待つだけ(取れなくても読むだけなので安全)
        got = self.lock.acquire(timeout=0.3)
        try:
            folder = cfg.get("folder") if isinstance(cfg.get("folder"), str) else ""
            return dict(cfg, state=self.state, stateLabel=STATE_LABELS[self.state], message=self.message,
                        outDir=out_dir_of(folder),   # 届け先 = 受付のフォルダの 出力(画面の「友人へ自動で送る」が封筒の deliver.dir に入れる。D-SEND・RV A1)
                        lastScan=int(self.last_scan * 1000) if self.last_scan else None,
                        today=int(self.st["daily"].get(self._today(), 0)),
                        requests=[dict(r) for r in list(self.st["requests"])],
                        notices=self._notices())   # 友人の [作る人に知らせる](送り返しの .notice.json。F3-6・C-2-16)
        finally:
            if got:
                self.lock.release()

    def _notices(self):
        """ホームの「依頼の受付」に出す友人からの知らせ(returns.recent_notices。読めなければ空)"""
        try:
            return returns.recent_notices(self.data_dir, self.clock())
        except OSError:
            return []

    def _cfg(self):
        try:
            return dict(self.prefs.get(["intake"])["intake"])
        except (OSError, ValueError, KeyError):
            return dict(self.defaults or {})

    def folder(self):
        """受付のフォルダ(ホームの設定 intake.folder。オフでも返す)。決まっていなければ ""。入口の手で届ける・自動の片付け・学習の束が使う"""
        return configured_folder(self.prefs, self.defaults)

    def out_dir(self):
        """受付のフォルダの 出力\\(友人のアプリの「受け取る」が読む)。フォルダが決まっていなければ None"""
        return out_dir_of(self.folder())

    # ------------------------------------------------------------ 見る
    def scan(self):
        try:
            self._scan()
        finally:
            self._after_scan()

    def _after_scan(self):
        """見回りの終わり: 届けられなかった自動の分を送り直す(flush。受付のフォルダがあるときだけ。失敗しても見回りは止めない)"""
        if self.flush is None:
            return
        folder = self.folder()
        if not folder or fsio.is_network_path(folder) or not os.path.isdir(folder):
            return
        try:
            self.flush()
        except Exception as e:   # noqa: BLE001  (送り直せなくても次の見回りでまた試す)
            self.log("依頼の受付: 自動で届ける分の送り直しでエラー: %s %s" % (e.__class__.__name__, str(e)[:160]))

    def _scan(self):
        with self.lock:
            cfg = self._cfg()
            self.last_scan = self.clock()
            if not cfg.get("enabled"):
                self.state, self.message = "off", "オフです(設定でオンにすると、フォルダを見張ります)"
                return
            folder = cfg.get("folder") or ""
            if not folder:
                self.state, self.message = "error", "見張るフォルダが決まっていません(設定で Dropbox のフォルダを指定してください)"
                return
            if fsio.is_network_path(folder) or not os.path.isdir(folder):
                self.state, self.message = "error", "見張るフォルダが見つかりません: %s" % folder
                return
            self.state, self.message = "watching", ""
            try:
                names = sorted(os.listdir(folder))
            except OSError as e:
                self.state, self.message = "error", "フォルダを読めませんでした(%s)" % tools.why(e)
                return
            files = {}
            for n in names:
                p = os.path.join(folder, n)
                if (n.startswith((".", "~")) or n.lower().endswith((".tmp", ".part", ".crdownload", ".download", ".partial")) or _is_os_file(n, p)
                        or not os.path.isfile(p)):
                    continue
                files[n] = p
            ready = {n: p for n, p in files.items() if self._settled(p)}
            self._seen_size = {p: v for p, v in self._seen_size.items() if p in files.values()}
            items = sorted(ready.items(), key=lambda kv: os.path.getmtime(kv[1]) if os.path.exists(kv[1]) else 0)
            claimed = set()
            for n, p in items:   # 友人のプログラムの依頼を先に(その動画を手で送ったものと取り違えない)
                if n.endswith(REQ_SUFFIX):
                    claimed |= self._handle_request_json(folder, n, p, files, ready, cfg)
            for n, p in items:
                if n in claimed or n.endswith(REQ_SUFFIX) or not os.path.exists(p):
                    continue
                m = APP_FILE_RE.match(n)
                if m and (m.group(1) + REQ_SUFFIX) in files:
                    continue   # JSON はあるが、まだそろっていない(同期の途中)
                if m and self.clock() - os.path.getmtime(p) < WAIT_FILES:
                    continue   # 友人のプログラムの動画で、JSON がまだ届いていない
                # 依頼の JSON の無いファイル(手で置いた動画・.txt・JSON が来ないまま WAIT_FILES たった友人の動画)は受け付けない
                self._record(folder, "video", "manual", n, [n], "", [], [{"label": n, "state": "rejected", "reason": MANUAL_REASON}])
            returns.scan(folder, self.data_dir, self.clock, self.log, feedback=self.feedback)   # 送り返し\(友人の PC の ② の結果と採否。F1 の F2。失敗しても見回りは止めない)
            bugs.scan(folder, self.data_dir, self.clock, self.log)   # 診断\ の不具合の書き出し(失敗しても見回りは止めない)
            upwatch.scan(folder, self.data_dir, self.clock, self.log)   # 更新の見張り(失敗しても見回りは止めない)
            notify.tick(self.data_dir, self.clock, self.log)   # 上の 2 つが書いた知らせをまとめ役へ(失敗しても見回りは止めない)
            pubqueue.tick(self.data_dir, bugs.repo_root(), self.clock, self.log)   # まとめて配る回(区切りを越えて最初の見回りで 1 回)
            self._stop_taken(bugs.friend_first(self.data_dir, self.clock, self.log))   # 引き継いだ依頼に友人の物が先に届いた = こちらは届けない

    def _stop_taken(self, rids):
        """引き継いだ依頼 rids のこちらの実行を取り消す(友人の PC の物が先に届いた。もう終わった実行・取り消せない受け手は飛ばす)"""
        for rec in self.st.get("requests") or []:
            if rec.get("requestId") in rids:
                for run_id in rec.get("runIds") or []:
                    try:
                        self.runner.cancel(run_id)
                    except (AttributeError, ValueError) as e:   # 受け手に取り消しが無い・もう無い実行
                        self.log("引き継いだ依頼の実行 %s を止められませんでした: %s" % (run_id, e))

    def _settled(self, p):
        try:
            s = os.stat(p)
        except OSError:
            return False
        now = self.clock()
        cur = (s.st_size, s.st_mtime)
        prev = self._seen_size.get(p)
        if prev is None or prev[:2] != cur:
            self._seen_size[p] = cur + (now,)
            return False
        need = self._settle_of(p)
        return now - prev[2] >= need and now - s.st_mtime >= need

    def _count(self, n=1):
        """今日の件数を足す(画面の「今日 n 件」に出すだけ。受け付けるかどうかには使わない)"""
        t = self._today()
        self.st["daily"][t] = int(self.st["daily"].get(t, 0)) + n

    # ------------------------------------------------------------ 依頼の種類ごと
    def _read_text(self, p):
        if os.path.getsize(p) > TEXT_MAX:
            raise ValueError("ファイルが大きすぎます(%d KB まで)" % (TEXT_MAX // 1024))
        with open(p, "rb") as f:
            return decode_text(f.read(TEXT_MAX + 1))

    def _handle_request_json(self, folder, n, p, files, ready, cfg):
        """友人のプログラムの依頼。-> この依頼が使ったファイルの名前の集まり"""
        rid = n[:-len(REQ_SUFFIX)]
        try:
            d = json.loads(self._read_text(p))
        except (ValueError, OSError) as e:
            self._record(folder, "url", "app", n, [n], "", [], [{"label": n, "state": "rejected", "reason": "依頼の形が読めません(%s)" % str(e)[:80]}])
            return {n}
        if not isinstance(d, dict) or d.get("v") != 1 or d.get("kind") not in REQ_KINDS or not REQ_ID_RE.match(rid):
            self._record(folder, "url", "app", n, [n], "", [], [{"label": n, "state": "rejected", "reason": "依頼の形が正しくありません"}], rid=rid)
            return {n}
        taken = bugs.guard(folder, self.data_dir, rid, self.clock)   # 引き継いだ依頼の 2 通目・もう届いた物は断る(届け元を 1 つに。10-25)
        if taken:
            self._record(folder, "video" if d["kind"] == "video" else "url", "app", n, [n], "", [], [{"label": n, "state": "rejected", "reason": taken}], rid=rid)
            return {n}
        flow = "auto"   # 友人の依頼は全部 ① 全自動(flow が check・manual・無しでも断らず ① として扱う)
        flow_orig = d.get("flow") if d.get("flow") in OLD_FLOWS else ""   # 元の値は受付の記録に残す(後で分かるように)
        # 話す人(無ければ話者分離しない)・映像トラックの数 1〜5(既定 1)・カットの方法(無ければホームの設定)。検査は ② flow/order(束と同じ範囲)
        speakers = _order.speakers_arg(d.get("speakers"))
        tracks = _order.video_tracks_arg(d.get("videoTracks"))
        cut = _order.cut_arg(d.get("cut"))
        if d["kind"] == "live":   # ライブ配信(2-15): 配信中・配信前なら録画を始めて結びつける。終わっていれば ① 全自動
            self._handle_live_request(folder, n, d, rid, cfg, speakers, tracks, cut)
            return {n}
        if d["kind"] == "url":
            raw = [it for it in (d.get("items") if isinstance(d.get("items"), list) else [])[:MAX_URLS] if isinstance(it, dict)]
            lines = "\n".join("%s %s" % (str(it.get("url") or "")[:300], it.get("top", cfg["top"])) for it in raw)
            # 時刻で指定した区間(配信の ID ごと)
            ranges = {youtube_id(str(it.get("url") or "")[:300]): parse_ranges(it.get("ranges")) for it in raw}
            who, note = _streamer(d.get("streamer"))   # URL の依頼の 1 人目の名前。無い・合わない = チャンネル名から
            self._process_urls(folder, n, [n], lines, cfg, "app", rid, speakers, tracks, ranges=ranges, cut=cut,
                               streamer=who, streamer_note=note, flow_orig=flow_orig)
            return {n}
        names = d.get("files") if isinstance(d.get("files"), list) else []
        names = [x for x in names if _safe_name(x)][:20]
        if not names:
            self._record(folder, "video", "app", n, [n], "", [], [{"label": n, "state": "rejected", "reason": "動画の名前が書かれていません"}], flow, rid=rid)
            return {n}
        missing = [x for x in names if x not in ready]
        if missing:
            if self.clock() - os.path.getmtime(p) > WAIT_FILES:
                self._record(folder, "video", "app", names[0], [n] + [x for x in names if x in files], d.get("streamer") or "", [],
                             [{"label": x, "state": "rejected", "reason": "動画が届きませんでした(送り直してください)"} for x in missing], flow, rid=rid)
            return {n} | set(names)
        who, note = _streamer(d.get("streamer"))
        results, runs = [], []
        for x in names:
            label = APP_FILE_RE.match(x).group(2) if APP_FILE_RE.match(x) else x
            res = self._accept_video(files[x], label, who, cfg, rid, folder, speakers, tracks, cut)
            results.append(dict(res, label=label))
            runs += [res["runId"]] if res.get("runId") else []
        if note:
            results.append({"label": "配信者", "state": "accepted", "reason": note})
        self._record(folder, "video", "app", results[0]["label"], [n] + names, who or "", runs, results, flow, speakers, rid=rid, tracks=tracks, cut=cut, flow_orig=flow_orig)
        return {n} | set(names)

    def _handle_live_request(self, folder, n, d, rid, cfg, speakers, tracks, cut):
        """ライブ配信の依頼(notes:docs/spec/friend.md の 2-15。kind live・url 1 本・live = 友人の設定)。
        配信中・配信前: 録画を始めて依頼に結びつける(live_begin = 入口の Live.submit_request)。以後はその録画の候補の検出・自動の採用・書き出し → パック → 届ける が
        友人の設定で動く。もう終わっていれば kind url の ① 全自動と同じ(切り抜く数はホームの既定。届けるのは 1 本ずつ)"""
        url = str(d.get("url") or "")[:300]
        vid = youtube_id(url)
        settings = live_requests.clean_settings(d.get("live"))
        who, note = _streamer(d.get("streamer"))
        how = "1 本ずつ"
        moved = [n]
        if not vid:
            self._record(folder, "live", "app", n, moved, who or "", [], [{"label": url or n, "state": "rejected", "reason": "YouTube の配信の URL ではありません"}], "auto",
                         speakers, rid=rid, tracks=tracks, cut=cut)
            return
        info = self.info(vid) or {}
        title = info.get("title") or "https://www.youtube.com/watch?v=" + vid
        label = "%s(ライブ配信)" % title
        if info.get("live") == "post_live":   # 終わった直後(YouTube がアーカイブを用意している): 録画もアーカイブの切り抜きもまだできない(kind url と同じく断る。理由はライブ配信の言い方で)
            self._record(folder, "live", "app", title, moved, who or "", [],
                         [{"label": label, "state": "rejected", "reason": "配信は終わったところで、アーカイブがまだ見られません(見られるようになってから、もう一度送ってください)"}],
                         "auto", speakers, rid=rid, tracks=tracks, cut=cut)
            return
        ended = bool(info) and info.get("live") not in ("is_live", "is_upcoming")   # 状態が分かって、終わっている
        # 状態を確かめられなかった(info が空 = yt-dlp が無い・失敗・時間切れ)ときは、ここで諦めずに録画を試す(Live.begin が自分でもう一度調べる。
        # 配信前・配信中なら録画が始まる)。録画も始められなければ、今までどおりアーカイブから ① 全自動(終わった配信ならそれで切り抜ける)。
        def archive(why):   # アーカイブから ① 全自動(今までの流れ)
            self._process_urls(folder, n, moved, "%s %d" % (yturl.watch_url(vid), int(cfg["top"])), cfg, "app", rid, speakers, tracks,
                               ranges={}, cut=cut, streamer=who, streamer_note=note,
                               notes=[{"label": "ライブ配信", "state": "accepted", "reason": why + "、アーカイブから ① 全自動で切り抜きます(%s届けます)" % how}])
        if ended or (not info and self.live_begin is None):
            return archive("配信は終わっていたので" if ended else "配信の状態を確かめられなかったので")
        ctx = {"rid": rid, "deliverDir": os.path.join(folder, OUT_DIR), "url": "https://www.youtube.com/watch?v=" + vid, "title": title, "streamer": who or "",
               "speakers": speakers, "videoTracks": tracks, "cut": cut, "settings": settings}
        rec_ref = None   # 結びつけた録画 {recorder, recording}(ホームの「友人の依頼」の行からライブの画面へ移る鍵。10-24)
        if self.live_begin is None:
            res = {"label": label, "state": "rejected", "reason": "この PC ではライブ配信の依頼を受け付けられません(リアルタイム切り抜きが使えません)"}
        else:
            try:
                out = self.live_begin(ctx["url"], ctx) or {}
                got = out.get("recording")
                got = got.get("id") if isinstance(got, dict) else got   # 入口の begin_request は録画の id・ほかの口は録画の要約
                if isinstance(out.get("recorder"), str) and isinstance(got, str) and got:
                    rec_ref = {"recorder": out["recorder"], "recording": got}
                res = {"label": label, "state": "accepted",
                       "reason": "録画を%s(切り抜きは%s届けます)" % ("始めました" if not out.get("existing") else "しています(前から録画中)", how)}
            except Exception as e:   # noqa: BLE001  (録画元が動いていない・オフ・URL の形など。理由を友人に返す)
                msg = str(e)[:160]   # Live.begin の LiveError はもう「録画を始められませんでした: …」で始まる(二重にしない)
                if not info:   # 状態を確かめられず、録画も始められない(配信が終わっていた・録画元が動いていないなど)→ アーカイブから ① 全自動(今までの流れ)
                    return archive("配信の状態を確かめられず、録画も始められなかったので(%s)" % msg)
                res = {"label": label, "state": "rejected", "reason": msg if msg.startswith("録画を始められませんでした") else "録画を始められませんでした: " + msg}
        items = [res, {"label": "ライブ配信", "state": "accepted", "reason": live_requests.settings_label(settings)}]
        if note:
            items.append({"label": "配信者", "state": "accepted", "reason": note})
        if res["state"] == "accepted":
            self._count()
        self._record(folder, "live", "app", title, moved, who or "", [], items, "auto", speakers, rid=rid, tracks=tracks, cut=cut, live=rec_ref)

    def _process_urls(self, folder, title, moved, text, cfg, source, rid, speakers=None, tracks=None, ranges=None, cut=None,
                      streamer=None, streamer_note="", notes=None, flow_orig=""):
        """依頼の URL の行(text = parse_lines の形)を ① 全自動で流す。
        ranges = {配信の ID: (区間の一覧, 断った理由)}(友人が時刻で指定した区間)。同じ配信を前に受け付けていても断らない(解析などは使い回す)。
        streamer = 照らし合わせ済みの配信者の名前か None(None = まとめて実行がチャンネル名などから決める)・streamer_note = 合わなかったときの知らせ。
        notes = 一覧に添える知らせの行(NOTE_LABELS の label。数には入れない)"""
        ok, bad = parse_lines(text, int(cfg["top"]))
        results = [{"label": b["line"], "state": "rejected", "reason": b["reason"]} for b in bad]
        todo, seen, known = [], set(), []
        for it in ok[:MAX_URLS]:
            rs, rbad = (ranges or {}).get(it["id"]) or ([], [])
            it["top"] = _order.request_top(it["top"], rs)   # 区間を選んだら区間の数だけ(自動では埋めない。友人のアプリと同じ 1 か所)
            how = "区間 %d 個" % len(rs) if rs else "%d 個" % it["top"]
            label = "https://www.youtube.com/watch?v=%s(%s)" % (it["id"], how)
            results += [{"label": label, "state": "rejected", "reason": r} for r in rbad]
            if it["id"] in seen:
                results.append({"label": label, "state": "rejected", "reason": "同じ配信が2回書かれています(1回だけ受け付けました)"})
                continue
            info = self.info(it["id"]) or {}
            if info.get("title"):   # 題名が分かれば、断った理由の行も URL ではなく題名で出す(一覧で読めるように)
                label = "%s(%s)" % (info["title"], how)
                known.append(info["title"])
            if info.get("live") in ("is_live", "is_upcoming", "post_live"):
                results.append({"label": label, "state": "rejected", "reason": "配信中・配信前の配信です(終わって見られるようになってから送ってください)"})
                continue
            if info.get("duration") and info["duration"] > float(cfg["maxHours"]) * 3600:
                results.append({"label": label, "state": "rejected", "reason": "配信が長すぎます(%.1f 時間。上限 %s 時間)" % (info["duration"] / 3600, cfg["maxHours"])})
                continue
            if rs and info.get("duration"):   # 配信の長さの外の区間: 終わりで切る。長さより後から始まるものは断る
                late = [(s, e) for s, e in rs if s >= info["duration"]]
                results += [{"label": label, "state": "rejected", "reason": "区間 %s〜%s: 配信の長さ(%s)より後です" % (_hms(s), _hms(e), _hms(info["duration"]))} for s, e in late]
                rs = [(s, min(e, info["duration"])) for s, e in rs if s < info["duration"]]
                it["top"] -= len(late)   # 断った区間の分は、自動で埋めない
                if it["top"] <= 0:
                    continue   # 指定した区間が全部だめ(自動の分も無い): この配信は流さない
            seen.add(it["id"])
            todo.append(dict(it, title=info.get("title") or "", channel=info.get("channel") or "", label=label, checked=bool(info), ranges=rs,
                             duration=info.get("duration")))
        for it in ok[MAX_URLS:]:
            results.append({"label": it["line"], "state": "rejected", "reason": "1つの依頼に書けるのは %d 本までです" % MAX_URLS})
        runs = []
        if todo:
            try:
                out = submit_urls(self.runner(), [{k: it[k] for k in ("id", "top", "title", "channel", "ranges", "duration")} for it in todo], request_id=rid,
                                  deliver_dir=os.path.join(folder, OUT_DIR), speakers=speakers,
                                  video_tracks=tracks, cut=cut, streamer=streamer)
            except ValueError as e:
                out = {"runs": [], "skipped": [{"id": it["id"], "reason": str(e)} for it in todo]}
            by_vid = {r["videoId"]: r for r in out.get("runs") or []}
            skip = {s.get("id"): s.get("reason") for s in out.get("skipped") or []}
            for it in todo:
                r = by_vid.get(it["id"])
                if r:
                    runs.append(r["id"])
                    self._count()
                    note = "" if it["checked"] else "配信の長さを確かめられませんでした(そのまま進めます)"
                    results.append({"label": (it["title"] or it["label"]), "state": "accepted", "reason": note, "runId": r["id"]})
                else:
                    results.append({"label": it["label"], "state": "rejected", "reason": skip.get(it["id"]) or "まとめて実行に入れられませんでした"})
        if not results:
            results.append({"label": title, "state": "rejected", "reason": "URL が書かれていません"})
        first = next((r["label"] for r in results if r["state"] == "accepted"), known[0] if known else title)   # 受け付けた配信 → 題名の分かった配信 → ファイル名
        n_ranges = sum(len(it["ranges"]) for it in todo)
        if streamer_note:   # 動画の依頼と同じ形の知らせ(受け付けた・断ったの数には入れない)
            results.append({"label": "配信者", "state": "accepted", "reason": streamer_note})
        if notes and _accepted(results):   # 受け付けたときだけ(断ったのに「切り抜きます」と出さない)
            results.extend(notes)
        self._record(folder, "url", source, first, moved, streamer or "", runs, results, "auto", speakers, rid=rid, tracks=tracks, cut=cut, flow_orig=flow_orig,
                     ranges_label="区間: %s" % "・".join(["%s〜%s" % (_hms(s), _hms(e)) for it in todo for s, e in it["ranges"]][:3]) +
                     (" ほか %d" % (n_ranges - 3) if n_ranges > 3 else "") if n_ranges else "")

    def _accept_video(self, p, label, who, cfg, rid, folder=None, speakers=None, tracks=None, cut=None):
        """1本の動画を確かめて、作業データへコピーし、① 全自動(文字起こし → パック)に入れる。-> {"state", "reason", "runId"?}。
        前に受け付けた動画と同じでも断らない(映像トラックの数などを変えて送り直せるように。ユーザー)"""
        ext = os.path.splitext(p)[1].lower()
        if ext not in VIDEO_EXT:
            return {"state": "rejected", "reason": "受け付けない種類のファイルです"}
        try:
            size = os.path.getsize(p)
            if size > float(cfg["maxGB"]) * 1024 ** 3:
                return {"state": "rejected", "reason": "動画が大きすぎます(%.1f GB。上限 %s GB)" % (size / 1024 ** 3, cfg["maxGB"])}
        except OSError as e:
            return {"state": "rejected", "reason": "動画を読めませんでした(%s)" % tools.why(e)}
        pr = self.probe(p)
        if not pr.get("ok"):
            return {"state": "rejected", "reason": pr.get("reason") or "動画として読めませんでした"}
        if pr.get("duration") and pr["duration"] > float(cfg["maxHours"]) * 3600:
            return {"state": "rejected", "reason": "動画が長すぎます(%.1f 時間。上限 %s 時間)" % (pr["duration"] / 3600, cfg["maxHours"])}
        day = self._today()
        dest_dir, in_case = self._request_dir(rid, label, day)
        base = BAD_NAME_CHARS.sub("_", label)[:150] or ("video" + ext)
        if not base.lower().endswith(ext):
            base += ext
        base = ytt_names.trim_units(os.path.splitext(base)[0], max(20, ytt_names.MAX_PATH_UNITS - ytt_names.path_units(dest_dir) - len(ext) - 24)) + ext   # パスの長さの枠
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, base)
            if os.path.exists(dest):
                dest = os.path.join(dest_dir, "%s-%s%s" % (os.path.splitext(base)[0], uuid.uuid4().hex[:6], ext))
            tmp = dest + ".copying"
            shutil.copyfile(p, tmp)
            os.replace(tmp, dest)
        except OSError as e:
            return {"state": "rejected", "reason": "作業データへコピーできませんでした(%s)" % tools.why(e)}
        if in_case:   # 依頼のフォルダを案件にする(文書を最初から 作業用 へ置けるように。無ければ作るだけ)
            placement.ensure_case({"kind": "file", "path": dest}, channel=who or "", root=dest_dir, request_id=rid or "")
        try:   # 30fps にそろえるのは実行の最初の段(submit_file の既定 normalize=True。写しを置き換える = 元の動画は触らない。失敗しても写しのまま続く)
            run = submit_file(self.runner(), dest, title=os.path.splitext(label)[0], streamer=who, request_id=rid,
                              deliver_dir=os.path.join(folder, OUT_DIR) if folder else None, speakers=speakers,
                              video_tracks=tracks, cut=cut)
        except ValueError as e:
            try:
                os.remove(dest)
            except OSError:
                pass
            return {"state": "rejected", "reason": "文字起こしに入れられませんでした(%s)" % e}
        self._count()
        return {"state": "accepted", "reason": "", "runId": run["id"]}

    def _request_dir(self, rid, label, day):
        """依頼 1 件の動画の置き場所 -> (フォルダ, 案件か)。書き出し先が設定されていて固定ディスクなら <書き出し先>/依頼/<日付>_<題>_<id6>/
        (案件にする。placement.request_root)、そうでなければ今までの作業データ app/intake/<日付>/<依頼 id>/。同じ依頼の 2 本目以降は 1 本目と同じフォルダ。
        rid は友人のアプリの依頼 id(REQ_ID_RE。受付が確かめ済み)。前からある app/intake/<日付>/ 直下の動画・手で置いた動画の m<乱数> のフォルダは動かさない(片付けが読む)"""
        if rid in self._req_dirs:   # 覚えは速さのため(起こし直したあとも placement.request_folder が同じフォルダを引く)
            return self._req_dirs[rid]
        got = placement.request_folder(rid, os.path.splitext(label)[0], day, fallback=os.path.join(self.data_dir, "intake", day, rid))
        if len(self._req_dirs) >= REQ_DIRS_MAX:
            self._req_dirs.pop(next(iter(self._req_dirs)))
        self._req_dirs[rid] = got
        return got

    # ------------------------------------------------------------ 後始末と記録
    def _record(self, folder, kind, source, title, moved, streamer, runs, items, flow="", speakers=None, rid=None, tracks=None, cut=None,
                ranges_label="", flow_orig="", live=None):
        """受付の記録(最近の依頼)に 1 件。flow は依頼の流れが分かるときだけ渡す(空 = 行に「① 全自動」などを出さない。依頼の形が読めないときなど)。
        rid = 友人のアプリの依頼の id(requestId に残す)・live = ライブの依頼で結びつけた録画 {recorder, recording}(ホームの行の鍵。10-24)"""
        accepted = _accepted(items)
        state = "accepted" if accepted else "rejected"
        reason = "" if accepted else next((i["reason"] for i in items if i["state"] == "rejected"), "")
        rec = {"id": uuid.uuid4().hex[:10], "kind": kind, "source": source, "title": str(title)[:200], "streamer": streamer or "",
               "received": int(self.clock() * 1000), "state": state, "stateLabel": REQ_LABELS[state], "reason": reason,
               "flow": flow, "flowLabel": FLOW_LABELS.get(flow, ""),
               **({"flowOrig": flow_orig} if flow_orig and flow_orig != flow else {}),   # ①以外の flow を ① に読み替えたとき
               "speakersLabel": ("配信者: %d人" % speakers["count"] + ("(%s)" % "・".join(speakers["names"]) if speakers["names"] else "") +
                                 ("・色の指定 %d人" % len(speakers["styles"]) if speakers.get("styles") else "")) if speakers else "",
               "tracksLabel": "映像トラック: %d本" % tracks if tracks else "",
               "rangesLabel": ranges_label, "cutLabel": "カット: %s" % CUT_LABELS[cut] if cut in CUT_LABELS else "",
               "runIds": runs, "items": [{k: i.get(k, "") for k in ("label", "state", "reason")} for i in items][:30],
               **({"requestId": rid} if isinstance(rid, str) and rid else {}), **({"live": dict(live)} if isinstance(live, dict) else {})}
        self.st["requests"] = ([rec] + self.st["requests"])[:KEEP_REQUESTS]
        self._move(folder, moved, state, items)
        self._notify_rejected(folder, rid, rec["title"], items)
        self._save_state()
        self.log("依頼の受付: %s %s(%s)" % (REQ_LABELS[state], textutil.one_line(rec["title"]), textutil.one_line(reason or "%d 件" % len(runs))))   # 友人の文は 1 行に(ログの行を偽れないように)

    def _notify_rejected(self, folder, rid, title, items):
        """友人のアプリの依頼で、受け付けなかった物があれば 出力/<依頼 id>__<題>.失敗.txt に理由を置く(アプリの「受け取る」に出る。段9 9-4)。
        処理が始まってから止まったときは ② flow/delivery.py の _deliver_failure が同じ形で置く"""
        bad = [i for i in items if i["state"] == "rejected"]
        if not bad or not rid or not REQ_ID_RE.match(str(rid)):
            return
        whole = not _accepted(items)
        name = BAD_NAME_CHARS.sub("_", "%s__%s" % (rid, title or "依頼"))[:180] + ".失敗.txt"
        text = ("依頼を受け付けられませんでした。" if whole else "依頼の一部を受け付けられませんでした(ほかは処理します)。") + "\r\n" + \
            "\r\n".join("%s: %s" % (i["label"], i.get("reason") or "受け付けられませんでした") for i in bad)
        try:
            out = os.path.join(folder, OUT_DIR)
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, name), "w", encoding="utf-8-sig", newline="") as f:
                f.write(text + "\r\n")
        except OSError as e:
            self.log("依頼の受付: 断った理由を 出力 に置けませんでした(%s)" % tools.why(e))

    def _move(self, folder, names, state, items):
        """元のファイルを 受付済み\\日付\\ か 失敗\\ へ(消さない)。断ったものには理由の .txt を添える"""
        sub = os.path.join(folder, DONE_DIR, self._today()) if state == "accepted" else os.path.join(folder, FAIL_DIR)
        try:
            os.makedirs(sub, exist_ok=True)
        except OSError:
            return
        for n in names:
            src = os.path.join(folder, n)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(sub, n)
            if os.path.exists(dst):
                stem, ext = os.path.splitext(n)
                dst = os.path.join(sub, "%s-%s%s" % (stem, uuid.uuid4().hex[:6], ext))
            try:
                fsio.replace_retry(src, dst)
            except OSError as e:
                self.log("依頼の受付: %s を移せませんでした(%s)" % (n, tools.why(e)))
            self._seen_size.pop(src, None)
        bad = [i for i in items if i["state"] == "rejected" or i.get("reason")]
        if bad and names:
            text = "\r\n".join("%s: %s%s" % (i["label"], REQ_LABELS.get(i["state"], i["state"]), "(%s)" % i["reason"] if i.get("reason") else "") for i in items)
            try:
                with open(os.path.join(sub, os.path.splitext(names[0])[0] + ".理由.txt"), "w", encoding="utf-8-sig", newline="") as f:
                    f.write(text + "\r\n")
            except OSError:
                pass
