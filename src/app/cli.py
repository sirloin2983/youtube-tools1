# -*- coding: utf-8 -*-
"""② 管理 + ① 道具で動くコマンド(役割で組み直す RS6 b-S1。決定 3-29・docs/design/rs6-survey-2026-10-10/plan_order_v2.md の b-S1)。

    py -3.10 src/app/cli.py <動画のパス | URL> [--spec spec.json] [--from 段] [--force] [--data-dir D] [--out result.json] [--title T]

- 束(--spec): 変えたい所だけの JSON(無ければ既定)。flow/spec.py の merge → validate に通す。API キーは束に書かない(環境変数 YOUTUBE_API_KEY。書いてあれば断る)。
  作業データを決めたあと、この PC の設定(flow/machine.py。machine.json・環境変数で決めたエンジン・機器・LLM のモデル)を束に重ねる
- 作業データ(--data-dir): 環境変数 YTT_DATA_DIR と同じ意味(<D>/transcribe など)。無ければ普段の作業データ
- 1 つの作業データに ② は 1 つ(flow/placement の .flow.lock):
  - 入口(start.bat の ②)が動いていれば、その入口に頼んで待つ = ② の口 POST /api/flow/submit に封筒 + 束を 1 回(RS7-1 S4。--spec・--force・--from も
    入口でそのまま効く = 入口なしで動かしたときと同じ束)。URL = 解析から(--from analyze か無し)か書き出しから(--from export)・動画ファイル = 文字起こし → パック
    (--from pack = 文字起こし済みの文書でパックだけ。届けない)。submit の無い古い入口(404)には頼まない(起動し直しを促して失敗で終わる)。
    入口の場所は lock の port(無ければ .runtime/portal.json で、同じ作業データの入口だけ)。合言葉は入口の画面の HTML の meta から読む
  - 動いていなければ、動画ファイルは自分で lock を取って ① を直に動かす(flow/tools の LocalTools。③ の人の部品は、学習のもとの文書があるときだけ学習した置換・用語を読むために遅延で読む = 無ければ読まない。RS7-1 F-k)。
    URL は入口が要る(URL の流れは B-3 まで入口に頼む = 一時の形。コマンドの形は最終)
- 動画ファイルは丸ごと 1 本(決定 3-29 の Q2)。文字起こし済みの文書があれば文字起こしは飛ばす(--force で作り直す・--from pack はその文書でパックだけ)
- 結果: Run.public() に、段ごとの成果物と鍵のパス・結果の束のパス(あれば)を足した JSON を標準出力と --out へ。進み具合は標準エラーに 1 行ずつ
- 終わるとき(Ctrl+C・閉じる合図でも)認識ワーカーを止め、lock を返す

終了コード: 0 済み(やることが無かったも)/ 1 実行が失敗・中止 / 2 引数・束の形が違う / 3 URL なのに入口が動いていない /
4 作業データを別の実行が使っている(入口が応答しない)/ 130 Ctrl+C
"""
import argparse
import http.client   # HTTPConnection は属性で引く(テストが差し替えられるように)
import json
import os
import re
import sys
import time
import uuid

SRC =os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/app -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from flow import envelope as _envelope, keys as _keys, machine as _machine, placement as _flow_placement, run as _run, spec as _spec, tools as _tools, wire as _wire  # noqa: E402
from pipeline.transcribe import roster as _roster, worker_client as _worker_client  # noqa: E402
from ytt import datadir as _datadir, docloc as _docloc, fsio as _fsio, layout as _layout, runtime as _runtime, schemas as _schemas  # noqa: E402
from ytt import tools as _ytools, workdata as _workdata, yturl as _yturl  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NO_PORTAL, EXIT_BUSY, EXIT_INTERRUPT = 0, 1, 2, 3, 4, 130
PORTAL_APP = "ytt-launcher"     # 入口の /api/ping の app(src/home/launch.py の APP_ID)
POLL = 2.0                      # 入口に頼んだ仕事を見に行く間隔(秒)
RUN_LOST = 15                   # 入口の一覧から頼んだ実行がこの回数続けて見えなければ失敗にする
DETAIL_EVERY = 10.0             # 実行中の段の細かい進み具合を標準エラーに出す間隔(秒)
TOKEN_RE = re.compile(rb'<meta\s+name="ytt-token"\s+content="([A-Za-z0-9_-]{1,200})"\s*/?>')
PAGE_MAX, BODY_MAX, TIMEOUT = 2 * 1024 * 1024, 16 * 1024 * 1024, 30
SECRET_RE = re.compile(r"api[_-]?key|token|secret|password", re.I)   # 束に書いてはいけない鍵の名前
FILE_FROM = (None, "analyze", "adopt", "export", "transcribe", "pack")   # 動画ファイル: pack より前は全部「文字起こしから」(解析・採用・書き出しは無い)
URL_FROM = {None: "start-new", "analyze": "start-new", "export": "adopted"}   # URL: 封筒の legacy.mode(入口のまとめて実行の形)
END_STATES = ("done", "error", "cancelled")


class UsageError(Exception):
    """引数・束の形が違う(終了コード 2。文は利用者に見せる)"""


class PortalError(Exception):
    """入口につながらない・断られた(文は利用者に見せる)"""


def _placement():
    """② の置き場所の持ち主(flow/placement。.flow.lock と結果の束)。呼ぶたびに読む(テストが差し替える)"""
    from flow import placement
    return placement


# ---------------------------------------------------------------- 引数と束
def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="cli.py", description="動画ファイルか YouTube の URL から、文字起こし → Resolve のパックまで")
    ap.add_argument("input", help="動画ファイルのパスか YouTube の URL")
    ap.add_argument("--spec", help="指定の束(JSON。変えたい所だけ)。無ければ既定")
    ap.add_argument("--from", dest="from_", choices=_spec.RUN_FROM, help="この段から(束の run.from より先)")
    ap.add_argument("--force", action="store_true", help="済んでいても作り直す(文字起こし・パック)")
    ap.add_argument("--data-dir", help="作業データの根(環境変数 YTT_DATA_DIR と同じ意味)")
    ap.add_argument("--out", help="結果の JSON をこのファイルにも書く")
    ap.add_argument("--title", default="", help="題名(無ければファイル名・配信の題名)")
    return ap.parse_args(argv)


def _secret_keys(obj, path=""):
    """束の中の API キーらしい鍵の名前(節.項目)の並び"""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            name = "%s.%s" % (path, k) if path else str(k)
            if SECRET_RE.search(str(k)):
                found.append(name)
            found += _secret_keys(v, name)
    elif isinstance(obj, list):
        for v in obj:
            found += _secret_keys(v, path)
    return found


def load_spec(path, from_=None, force=False):
    """束のファイル → 検査した束(--from・--force を run 節に重ねる)。形が違えば UsageError"""
    given = {}
    if path:
        try:
            with open(path, encoding="utf-8-sig") as f:
                given = json.load(f)
        except OSError as e:
            raise UsageError("束のファイルを読めません: %s" % _ytools.why(e))
        except ValueError as e:
            raise UsageError("束のファイルが JSON ではありません: %s" % e)
    bad = _secret_keys(given)
    if bad:
        raise UsageError("API キーは束に書かないでください(環境変数 YOUTUBE_API_KEY で渡します): %s" % "・".join(bad))
    try:
        bundle = _spec.merge(given)
        if from_:
            bundle["run"]["from"] = from_
        if force:
            bundle["run"]["force"] = True
        return _spec.validate(bundle)
    except ValueError as e:
        raise UsageError("束の形が違います: %s" % e)


def classify_input(text):
    """入力 -> ("file", 絶対パス) か ("url", 動画 ID)。どちらでもなければ UsageError"""
    p = os.path.abspath(str(text).strip().strip('"'))
    if os.path.isfile(p):
        if os.path.splitext(p)[1].lower() not in _ytools.MEDIA_TYPES:
            raise UsageError("動画・音声ファイルではないようです(対応: %s)" % " ".join(sorted(_ytools.MEDIA_TYPES)))
        return "file", p
    vid = _yturl.parse_video_id(text)
    if vid:
        return "url", vid
    if "://" in str(text):
        raise UsageError("YouTube の URL の形ではありません")
    raise UsageError("動画ファイルが見つかりません: %s" % p)


def check_from(kind, bundle):
    frm = bundle["run"]["from"]
    if kind == "url" and frm not in URL_FROM:
        raise UsageError("URL のときの --from は analyze か export です(入口のまとめて実行の形)")
    if kind == "file" and frm not in FILE_FROM:
        raise UsageError("動画ファイルのときの --from は transcribe か pack です")


# ---------------------------------------------------------------- 作業データ
def use_data_dir(data_dir=None):
    """作業データの置き場所を決めて ytt/workdata と名簿の場所に入れる(移しはしない = datadir.locate)。-> 作業データの根(inplace なら None)。
    --data-dir は YTT_DATA_DIR と同じ意味(ツールごとの指定 TRANSCRIBE_DATA_DIR・STUDIO_HOME は外す = 指定した根の下だけを使う)"""
    if data_dir:
        os.environ["YTT_DATA_DIR"] = os.path.abspath(data_dir)
        for name in _datadir.ENV_OVERRIDE.values():
            os.environ.pop(name, None)
    editor = _layout.tool_dir("transcribe")
    _workdata.set_root(editor)
    _workdata.set_data_dir(os.path.abspath(_datadir.locate("transcribe")))
    _roster.ROSTER = os.path.join(editor, "hololive-roster.json")
    if not os.environ.get("TRANSCRIBE_STUDIO_DATA"):   # 配信の文脈はこの作業データのスタジオの data.json(無ければ文脈なし。リポジトリの中の src/studio は読まない。RS7-1 F-k)
        _workdata.STUDIO_DATA = _flow_placement.studio_data()
    ld = learning_dir()
    if ld:   # 学習データが別の場所のとき: 置換辞書(settings.json)と採用の記録はそこから読む
        _workdata.SETTINGS = os.path.join(ld, "settings.json")
        _workdata.FEEDBACK = os.path.join(ld, "learn-feedback.json")
    return _datadir.data_root()


def learning_dir():
    """machine の learningDir が既定(作業データの根)と違うときの、その下の編集の作業データのフォルダ。既定なら None(今の置き場所のまま)"""
    ld = _machine.get("learningDir")
    if os.path.normcase(os.path.normpath(ld)) == os.path.normcase(os.path.normpath(_machine.root())):
        return None
    return _datadir.locate("transcribe", env=dict(os.environ, YTT_DATA_DIR=ld))


class Learning:
    """LocalTools に貸す学習データの読み手(入口の経路で編集が読むのと同じ物 = ③ の learn。用語は doc_jobs.glossary_of と同じ learn.auto_glossary、
    学習済みの置換は doc_jobs.learned_finder)。置き場所が既定と違うとき(machine の learningDir)は、読む間だけ文書の置き場所 TX_DIR をそちらへ向ける。
    ③ は友人の PC の ② + ① には無いことがあるので、学習のもとになる文書が 1 つも無いとき・③ を読めないときは読まずに「学習なし」にする(遅延 import)"""

    def __init__(self, ld=None):
        self.ld = ld

    def _tx_dir(self):
        return _docloc.tx_root(self.ld)

    def _human(self):
        """(learn, doc_jobs) か None(学習のもとの文書が無い・③ を読めない)"""
        try:
            if not _docloc.iter_tids(self.ld):
                return None
            from human.proof import doc_jobs, learn
        except (OSError, TypeError, ImportError):
            return None
        return learn, doc_jobs

    def _scoped(self, fn):
        keep = _workdata.TX_DIR
        _workdata.TX_DIR = self._tx_dir()
        try:
            return fn()
        finally:
            _workdata.TX_DIR = keep

    def glossary(self, terms):
        h = self._human()
        return self._scoped(lambda: h[0].auto_glossary(terms)) if h else []

    def dict_learned(self):
        """辞書の版(records.dict_version)の learned の元の文字(学習の記録が変われば作り直す鍵になる)。学習なしは空"""
        h = self._human()
        return self._scoped(h[1].dict_learned) if h else ""

    def learned(self):
        h = self._human()
        return self._scoped(lambda: h[1].learned_finder(h[0].learn_rules(), h[0].load_feedback())) if h else None


def _read_doc(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def find_doc(source_path):
    """この動画の文書のうち行のある新しい物(LocalTools の一覧と同じ形)か None。作業データの文書を読むだけ"""
    want, best = os.path.normcase(os.path.abspath(source_path)), None
    for tid in _docloc.iter_tids():
        d = _read_doc(_docloc.doc_file(tid, ".json"))
        if not d or os.path.normcase(os.path.abspath(str(d.get("sourcePath") or "."))) != want or not d.get("segments"):
            continue
        row = {"id": tid, "title": d.get("title") or tid, "sourcePath": d.get("sourcePath"), "updatedAt": d.get("updatedAt") or 0,
               "count": len(d["segments"]), "segments": d["segments"]}
        if best is None or row["updatedAt"] > best["updatedAt"]:
            best = row
    return best


# ---------------------------------------------------------------- 進み具合(標準エラー)
class Progress:
    def __init__(self, err=None):
        self.err = err or sys.stderr
        self.seen = {}

    def line(self, msg):
        print(msg, file=self.err, flush=True)

    def steps(self, steps, prefix=""):
        """段の状態が変わったとき(と実行中の細かい進み具合を DETAIL_EVERY 秒ごとに)1 行ずつ"""
        now = time.monotonic()
        for s in steps or []:
            key, state, detail = prefix + str(s.get("key")), s.get("state"), str(s.get("detail") or "")
            label = s.get("label") or _run.STEP_LABELS.get(s.get("key"), s.get("key"))
            old = self.seen.get(key)
            if old and old[0] == state and (state != "run" or old[1] == detail or now - old[2] < DETAIL_EVERY):
                continue
            if state == "wait" and not old:
                self.seen[key] = (state, detail, now)
                continue
            self.seen[key] = (state, detail, now)
            word = _run.STEP_STATE_LABELS.get(state, state)
            self.line("[%s] %s%s" % (label, word, ": " + detail if detail else ""))


# ---------------------------------------------------------------- 入口(②)に頼む
class Portal:
    """動いている入口の HTTP(127.0.0.1 だけ。合言葉は入口の画面の HTML の meta から = ブラウザと同じ受け取り方)"""

    def __init__(self, port, timeout=TIMEOUT):
        self.port, self.timeout, self._token = port, timeout, None

    def _send(self, method, path, body=None, token=None, limit=BODY_MAX):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        headers = {"Host": "127.0.0.1:%d" % self.port, "Accept": "application/json"}
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-YTT-Token"] = token
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read(limit)
        except (OSError, http.client.HTTPException) as e:
            raise PortalError("入口につながりませんでした(%s)" % e.__class__.__name__)
        finally:
            conn.close()

    def token(self):
        if self._token is None:
            st, raw = self._send("GET", "/", limit=PAGE_MAX)
            m = TOKEN_RE.search(raw) if st == 200 else None
            if not m:
                raise PortalError("入口の合言葉を読めませんでした(入口の版が古いかもしれません)")
            self._token = m.group(1).decode("ascii")
        return self._token

    def call(self, method, path, body=None):
        """-> (HTTP の番号, JSON の辞書)"""
        st, raw = self._send(method, path, body, None if method == "GET" else self.token())
        try:
            obj = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            obj = {}
        return st, obj if isinstance(obj, dict) else {}

    def ok(self, method, path, body=None):
        st, obj = self.call(method, path, body)
        if st != 200:
            raise PortalError("入口に断られました: %s" % (obj.get("message") or "HTTP %d" % st))
        return obj


def portal_at(port):
    """そのポートの入口(/api/ping が入口)か None"""
    if not _runtime.valid_port(port) or _runtime.ping_app(port, 1.0) != PORTAL_APP:
        return None
    return Portal(port)


def _same_root(a, b):
    norm = lambda p: os.path.normcase(os.path.abspath(p)) if p else None
    return norm(a) == norm(b)


def runtime_portal(root):
    """lock を持たない入口(.flow.lock より前の版)を .runtime/portal.json から探す。同じ作業データの入口だけ(/api/status の dataDir)"""
    info = _runtime.read_runtime(_runtime.runtime_dir(_layout.tool_dir("app")), "portal")
    p = portal_at(info["port"]) if info else None
    if p is None:
        return None
    try:
        st, obj = p.call("GET", "/api/status")
    except PortalError:
        return None
    return p if st == 200 and _same_root(obj.get("dataDir"), root) else None


def _wait_portal_run(portal, rid, prog):
    """入口のまとめて実行 1 つが終わるまで待つ -> その public。Ctrl+C なら入口の実行も取り消して上げる"""
    lost = 0
    try:
        while True:
            runs = portal.ok("GET", "/api/autorun").get("runs") or []
            r = next((x for x in runs if isinstance(x, dict) and x.get("id") == rid), None)
            if r is None:
                lost += 1
                if lost >= RUN_LOST:
                    raise PortalError("入口の実行が見つからなくなりました(入口を起動し直したかもしれません)")
            else:
                lost = 0
                prog.steps(r.get("steps"))
                if r.get("state") in END_STATES:
                    return r
            time.sleep(POLL)
    except KeyboardInterrupt:
        prog.line("取り消しています(入口の実行も止めます)")
        try:
            portal.call("POST", "/api/autorun/cancel", {"runId": rid})
        except PortalError:
            pass
        raise


def envelope_for(kind, target, title):
    """入口に頼む封筒(flow/envelope.py の形。id は実行の id にもなる 10 桁の 16 進)。何を作るかは束(run.from = どこから)"""
    eid = uuid.uuid4().hex[:10]
    title = str(title or "")[:_envelope.TITLE_MAX]
    if kind == "url":
        return {"id": eid, "kind": "url", "input": {"videoId": target, "title": title, "fresh": {"title": title, "channel": ""}}, "legacy": {"mode": "full"}}
    return {"id": eid, "kind": "file", "input": {"path": target, "title": title or os.path.basename(target)[:_envelope.TITLE_MAX]},
            "legacy": {"mode": "file_auto"}}


def _url_envelope(env, bundle):
    """URL の封筒を束の run.from に合わせる(書き出しから = 採用後を全部・まだスタジオに無い配信の印 fresh は付けない)"""
    if URL_FROM[bundle["run"]["from"]] != "start-new":
        env = dict(env, input={k: v for k, v in env["input"].items() if k != "fresh"}, legacy={"mode": URL_FROM[bundle["run"]["from"]]})
    return env


def delegate(portal, kind, target, bundle, title, prog):
    """入口に頼んで待つ -> (結果の辞書, 終了コード)。② の口 submit に封筒 + 束を 1 回(RS7-1 S4)。submit の無い古い入口(404)は PortalError"""
    prog.line("入口(ポート %d)が動いているので、入口に頼みます" % portal.port)
    env = envelope_for(kind, target, title)
    if kind == "url":
        env = _url_envelope(env, bundle)
    st, res = portal.call("POST", "/api/flow/submit", {"envelope": env, "spec": bundle})
    if st == 404:
        raise PortalError("入口の版が古く、コマンドからの依頼を受けられません(入口を「すべて終了」→ start.bat で起動し直してください)")
    if st != 200:
        raise PortalError("入口に断られました: %s" % (res.get("message") or "HTTP %d" % st))
    rid = (res.get("run") or {}).get("id") if isinstance(res.get("run"), dict) else None
    if not rid:
        raise PortalError("入口が実行を受け付けませんでした(応答に実行の id がありません)")
    return _portal_result(_wait_portal_run(portal, rid, prog))


def _portal_result(pub):
    """入口の実行の public -> (結果の辞書, 終了コード)"""
    packs = pub.get("packs")   # 入口の実行が作ったパック(RS7-1 S3 の Run.public)
    out = dict(pub, via="portal", packs=packs if isinstance(packs, list) else [])
    return out, EXIT_OK if pub.get("state") == "done" else EXIT_FAIL


# ---------------------------------------------------------------- 入口なし(② + ① を自分で)
class CliRunner(_run.Runner):
    """素の Runner + 進み具合を標準エラーへ・文字起こし済みの文書(find_doc)を一覧に足す。人の部品(③)は読まない"""

    def __init__(self, prog, extra=(), learning=None):
        super().__init__(None, poll=0.5, tools=_tools.LocalTools(learning=learning or Learning(learning_dir())))
        self.prog, self.extra = prog, list(extra)

    def _checkpoint(self, run):
        self.prog.steps(run.steps)

    def _docs(self):
        mine = self.tools.docs()
        return mine + [d for d in self.extra if d["id"] not in {x["id"] for x in mine}]


def _write_result(pl, run, prog):
    """結果の束(flow/placement.write_result。<案件>/作業用/runs/<実行id>.json)-> パスか None。書けなくても実行は失敗にしない"""
    fn = getattr(pl, "write_result", None)
    if fn is None:
        return None
    try:
        return fn(run)
    except Exception as e:   # 結果の束は付け足し(書けないことで成果物の報告を失わない)
        prog.line("※ 結果の束を書けませんでした: %s" % e)
        return None


def run_local(target, bundle, title, root, prog):
    """lock を取り、① を直に動かす(動画ファイル → 文字起こし → パック)-> (結果の辞書, 終了コード)"""
    pl = _placement()
    try:
        handle = pl.acquire(data_root=root)
    except pl.LockBusy as e:
        return _busy(getattr(e, "info", None) or (e.args[0] if e.args else None), prog)
    force, frm = bundle["run"]["force"], bundle["run"]["from"]
    run, code = None, EXIT_FAIL
    try:
        learning = Learning(learning_dir())
        _wire.install(tool="cli", tmp_dir=lambda: _workdata.TMP_DIR, dict_learned=learning.dict_learned)   # 辞書の版の学習の記録は ③ があれば Learning から
        doc = find_doc(target) if (frm == "pack" or not force) else None
        if frm == "pack" and not doc:
            return _failed("この動画の文字起こしの文書がありません(--from pack をやめて文字起こしから)", prog), EXIT_FAIL
        runner = CliRunner(prog, [doc] if doc else (), learning)
        if doc:   # 文字起こし済み: 文書 → パック(文字起こしの段は飛ばす)
            run = _run.Run(None, title or doc["title"], _run.DOC_MODE, None, doc_id=doc["id"], overwrite=force)
        else:
            run = _run.Run(None, title or os.path.basename(target), "file_auto", None, source_path=target, overwrite=force)
            run.steps = [s for s in run.steps if s["key"] != "deliver"]   # 届ける先は無い(友人の受付の段)
        run.state, run.message = "running", "実行中"
        try:
            _run.run(None, run, spec=bundle, hooks=runner)
            run.state, code = "done", EXIT_OK
        except _run.StepError as e:
            run.state, run.error = "error", str(e)
        except (_run.Cancelled, KeyboardInterrupt):
            run.state, run.error, code = "cancelled", "中止しました", EXIT_INTERRUPT
        run.finished = time.time()
        run.message = run.error or _run.RUN_STATE_LABELS["nothing" if run.nothing else "done"]
        prog.steps(run.steps)
        result = _write_result(pl, run, prog)
        return dict(run.public(), via="local", resultFile=result), code   # public に packs・newDocs・文書単位の docs も入る(RS7-1 S3)
    finally:
        _worker_client.WORKER.close()   # 認識ワーカー(別プロセス)を残さない
        pl.release(handle)


def _failed(msg, prog):
    prog.line("エラー: " + msg)
    return {"state": "error", "error": msg}


def _busy(info, prog):
    info = info if isinstance(info, dict) else {}
    return _failed("作業データを別の実行(pid %s)が使っています。終わるのを待つか、--data-dir で別の作業データを指定してください" % info.get("pid", "?"), prog), EXIT_BUSY


# ---------------------------------------------------------------- 成果物と鍵
def artifacts(out):
    """結果に足す: 段ごとの成果物のパスと鍵のパス(あるものだけ)"""
    docs, keys = [], []
    for tid in out.get("docs") or []:
        if not _schemas.TID_RE.match(str(tid)):
            continue
        path = _docloc.doc_file(tid, ".json")
        docs.append(path)
        keys += [_keys.doc_key_path(tid, st) for st in _docloc.DOC_KEY_STAGES]
        src = (_read_doc(path) or {}).get("sourcePath")
        if isinstance(src, str) and src:
            keys.append(_keys.media_key_path(src))
    keys += [_keys.pack_key_path(p) for p in out.get("packs") or []]
    return {"docs": [p for p in docs if os.path.isfile(p)], "packs": [p for p in out.get("packs") or [] if os.path.isdir(p)],
            "keys": [k for k in dict.fromkeys(keys) if os.path.isfile(k)]}


def emit(result, out_path, stdout):
    text = json.dumps(result, ensure_ascii=False, indent=1)
    print(text, file=stdout, flush=True)
    if out_path:
        _fsio.write_json(os.path.abspath(out_path), result, indent=1)


# ---------------------------------------------------------------- 入口
def dispatch(kind, target, bundle, title, root, prog):
    """入口が動いていれば頼む・無ければ自分で(URL は入口が要る)-> (結果, 終了コード)"""
    pl = _placement()
    info = pl.lock_info(data_root=root)
    if info:
        portal = portal_at(info.get("port")) if info.get("port") else None
        if portal is None:
            if info.get("port"):
                return _failed("入口(pid %s・ポート %s)が応答しません。少し待ってからやり直してください" % (info.get("pid"), info.get("port")), prog), EXIT_BUSY
            return _busy(info, prog)
    else:
        portal = runtime_portal(root)
    if portal is not None:
        return delegate(portal, kind, target, bundle, title, prog)
    if kind == "url":
        return _failed("入口(start.bat)を起動してください(URL の流れは今は入口が要ります)", prog), EXIT_NO_PORTAL
    return run_local(target, bundle, title, root, prog)


def _interrupt(signum, frame):
    raise KeyboardInterrupt()


def main(argv=None, stdout=None, stderr=None):
    _runtime.safe_stdio()
    stdout, prog = stdout or sys.stdout, Progress(stderr)
    args = parse_args(argv)
    try:
        kind, target = classify_input(args.input)
        bundle = load_spec(args.spec, args.from_, args.force)
        check_from(kind, bundle)
    except UsageError as e:
        prog.line("エラー: %s" % e)
        return EXIT_USAGE
    root = use_data_dir(args.data_dir)
    bundle = _machine.overlay(bundle)   # この PC の設定(作業データの根の machine.json・環境変数)を重ねる(無ければ束はそのまま。RS7-1 S1)
    _runtime.install_stop_signals(_interrupt)   # 黒い画面を閉じた・Ctrl+Break でも後始末をしてから終わる
    try:
        result, code = dispatch(kind, target, bundle, args.title, root, prog)
    except PortalError as e:
        result, code = _failed(str(e), prog), EXIT_FAIL
    except KeyboardInterrupt:
        result, code = {"state": "cancelled", "error": "中止しました"}, EXIT_INTERRUPT
    result = dict(result, input={"kind": kind, "target": target}, dataRoot=root, artifacts=artifacts(result))
    emit(result, args.out, stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
