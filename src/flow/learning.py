# -*- coding: utf-8 -*-
"""② 管理: 学習データを読む側(F1。notes:docs/design/f1-build.md の 2 の F1・3 の (f1c))。app/cli の Learning と learning_dir をここへ移した。

学習データの置き方は 2 つ(machine の learningDir):
- 作業データの置き方(既定。ユーザーの PC): <根>/transcribe/ に settings.json・learn-feedback.json・文書がある。学習のもとの文書があるときだけ
  ③ の learn(app が渡す)で、学習した用語・置換を計算する(文書が無い・③ を読めないときは「学習なし」)
- 学習の束(F1。友人の PC): learningDir に learning.json がある。④ manage/keep/learnpack が作った計算済みの規則 learned-rules.json を読むだけで、
  文書も ③ も読まない。置換辞書・用語(settings.json)・名簿・声・色もその束から読む(apply_places)。版は learning.json の version =
  束の post.learning.version に入れる(stamp)

標準ライブラリと ytt・pipeline だけを読む(③ は呼ぶ側が human_loader で渡す)。入口(server・LocalTools)への配線は仕上げの段。
"""
import os

from pipeline.transcribe import replace as _replace, roster as _roster
from ytt import colors as _colors, datadir as _datadir, docloc as _docloc, fsio as _fsio, workdata as _workdata

from . import diar as _diar, machine as _machine

PACK_FILE = "learning.json"          # 束の目次(版・中身の一覧と sha256)。あれば束の置き方
RULES_FILE = "learned-rules.json"    # 計算済みの規則
SETTINGS_FILE, FEEDBACK_FILE = "settings.json", "learn-feedback.json"
ROSTER_FILE, MEMBERS_FILE, VOICES_DIRNAME = "hololive-roster.json", "members.json", "voices"
MAX_RULES = 5000
PREFS_FILE = "prefs.json"            # ホームの設定(<作業データ>/app。src/app/prefs.py)。作る側の見分けに intake.folder だけ読む
MAKER_SKIP = "学習の束を作る側の PC なので、machine の learningDir(%s)は読みません(今の置き場所のまま)"


def is_pack(ld):
    """ld は学習の束のフォルダか(learning.json がある)"""
    return bool(ld) and os.path.isfile(os.path.join(ld, PACK_FILE))


def pack_version(ld):
    """学習の束の版(読めない・束でなければ空)"""
    d = _fsio.read_json_or(os.path.join(ld, PACK_FILE), None, kind=dict) if ld else None
    v = d.get("version") if d else None
    return v if isinstance(v, str) else ""


def maker_pc(env=None):
    """この PC は学習の束を作る側(ユーザーの PC)か = ホームの設定 <作業データ>/app/prefs.json の intake.folder(依頼の受付のフォルダ)が空でない。
    束は入口が <intake.folder>/学習 に作るので、この設定がある PC だけが作る側。友人の PC は Dropbox を API で読み(友人のアプリ)、② は画面なしで
    受付の設定を持たないので真にならない。文字起こしの文書(transcribe/transcripts)は友人の PC の ② も書くので見分けに使わない
    (前の友人のアプリ = 消した request-sender の Sync.cs の Sync.MakerPc も同じ条件だった。6d-1)"""
    p = os.path.join(_datadir.locate("app", env=env), PREFS_FILE)
    d = _fsio.read_json_or(p, None, kind=dict)
    intake = d.get("intake") if d else None
    folder = intake.get("folder") if isinstance(intake, dict) else None
    return isinstance(folder, str) and bool(folder.strip())


def learning_dir_checked():
    """machine の learningDir から -> (学習データの置き場所か None, 読まなかった理由の 1 行か空)。
    束(learning.json がある)ならそのフォルダ。ただし束を作る側の PC(maker_pc)では束を読まない = None と理由(10-11 に友人のアプリの同期が
    ユーザーの PC で learningDir を自分の束へ向け、入口のプロセスの設定が束の物に差し替わった。6d-1・Q9)。
    既定(作業データの根)なら None(今の置き場所のまま)。それ以外はその下の編集の作業データのフォルダ(作業データの置き方)"""
    ld = _machine.get("learningDir")
    if is_pack(ld):
        if maker_pc():
            return None, MAKER_SKIP % ld
        return os.path.abspath(ld), ""
    return _plain_dir(ld), ""


def learning_dir():
    """machine の learningDir から -> 学習データの置き場所か None(learning_dir_checked の理由を捨てた形。CLI の prepare・LocalTools もここを通る)"""
    return learning_dir_checked()[0]


def _plain_dir(ld):
    """束でない learningDir -> 既定なら None・それ以外は編集の作業データのフォルダ"""
    if os.path.normcase(os.path.normpath(ld)) == os.path.normcase(os.path.normpath(_machine.root())):
        return None
    return _datadir.locate("transcribe", env=dict(os.environ, YTT_DATA_DIR=ld))


def apply_places(ld):
    """学習データの場所を使う側(ytt/workdata・名簿・覚えた声・色)に入れる。ld は learning_dir() の値。None = 何もしない。
    束: 置換辞書・用語 settings.json・採用の記録・名簿・声・色をその束から(束に無い物は今のまま)。
    作業データの置き方: 置換辞書と採用の記録だけ"""
    if not ld:
        return
    if is_pack(ld):
        _workdata.SETTINGS = os.path.join(ld, SETTINGS_FILE)
        _workdata.FEEDBACK = os.path.join(ld, FEEDBACK_FILE)
        roster = os.path.join(ld, ROSTER_FILE)
        if os.path.isfile(roster):
            _roster.ROSTER = roster
        _diar.VOICES_DIR = os.path.join(ld, VOICES_DIRNAME)   # 覚えた声は束にある人だけ(無ければ声なし)
        members = os.path.join(ld, MEMBERS_FILE)
        if os.path.isfile(members) and not os.environ.get(_colors.MEMBERS_ENV):
            os.environ[_colors.MEMBERS_ENV] = members
        return
    _workdata.SETTINGS = os.path.join(ld, SETTINGS_FILE)
    _workdata.FEEDBACK = os.path.join(ld, FEEDBACK_FILE)


def _read_rules(ld):
    d = _fsio.read_json_or(os.path.join(ld, RULES_FILE), None, kind=dict)
    d = d or {}
    high = [(str(x.get("wrong")), str(x.get("right"))) for x in (d.get("high") if isinstance(d.get("high"), list) else [])[:MAX_RULES]
            if isinstance(x, dict) and isinstance(x.get("wrong"), str) and x.get("wrong") and isinstance(x.get("right"), str)]
    gl = [g for g in (d.get("glossary") if isinstance(d.get("glossary"), list) else [])[:MAX_RULES] if isinstance(g, str)]
    dl = d.get("dictLearned")
    return {"high": high, "glossary": gl, "dictLearned": dl if isinstance(dl, str) else ""}


class Learning:
    """LocalTools に貸す学習データの読み手。
    束(ld に learning.json)のときは計算済みの規則を読むだけ(③ は読まない)。
    作業データの置き方のときは入口の経路で編集が読むのと同じ物 = ③ の learn(用語は doc_jobs.glossary_of と同じ learn.auto_glossary、学習済みの置換は
    doc_jobs.learned_finder)。置き場所が既定と違うとき(machine の learningDir)は、読む間だけ文書の置き場所 TX_DIR をそちらへ向ける。
    ③ は友人の PC の ② + ① には無いことがあるので、学習のもとになる文書が 1 つも無いとき・③ を読めないときは読まずに「学習なし」にする。
    ② は ③ を読まない(層の向き)ので、③ の読み込み human_loader() -> (learn, doc_jobs) は呼ぶ側(app)が渡す(無ければ学習なし)"""

    def __init__(self, ld=None, human_loader=None):
        self.ld, self.human_loader = ld, human_loader
        self.pack = _read_rules(ld) if is_pack(ld) else None

    @property
    def version(self):
        """束の版(束でなければ空 = 束の post.learning.version を変えない)"""
        return pack_version(self.ld) if self.pack is not None else ""

    def _tx_dir(self):
        return _docloc.tx_root(self.ld)

    def _human(self):
        """(learn, doc_jobs) か None(学習のもとの文書が無い・③ を読めない)"""
        if self.human_loader is None:
            return None
        try:
            if not _docloc.iter_tids(self.ld):
                return None
            return self.human_loader()
        except (OSError, TypeError, ImportError):
            return None

    def _scoped(self, fn):
        keep = _workdata.TX_DIR
        _workdata.TX_DIR = self._tx_dir()
        try:
            return fn()
        finally:
            _workdata.TX_DIR = keep

    def glossary(self, terms):
        if self.pack is not None:
            return _replace.pick_glossary(terms, self.pack["glossary"])
        h = self._human()
        return self._scoped(lambda: h[0].auto_glossary(terms)) if h else []

    def dict_learned(self):
        """辞書の版(records.dict_version)の learned の元の文字(学習の記録が変われば作り直す鍵になる)。学習なしは空"""
        if self.pack is not None:
            return self.pack["dictLearned"]
        h = self._human()
        return self._scoped(h[1].dict_learned) if h else ""

    def learned(self):
        if self.pack is not None:
            return _replace.fixed_finder(self.pack["high"])
        h = self._human()
        return self._scoped(lambda: h[1].learned_finder(h[0].learn_rules(), h[0].load_feedback())) if h else None


def stamp(bundle, learning):
    """束(検査済み)の post.learning.version に、学習の束の版を入れた写しを返す(束でないとき・束に版が既にあるときはそのまま = 入口の経路と同じ鍵)。
    学習が変われば後処理の鍵が変わって、文字起こしの後処理だけ作り直される(flow/keys.post_inputs)"""
    v = getattr(learning, "version", "") or ""
    post = bundle.get("post") if isinstance(bundle, dict) else None
    if not v or not isinstance(post, dict) or (post.get("learning") or {}).get("version"):
        return bundle
    out = dict(bundle, post=dict(post, learning=dict(post.get("learning") or {}, version=v)))
    return out

