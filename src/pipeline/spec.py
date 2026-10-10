"""① に渡す指定の束(spec)の形・既定値・検査(役割で組み直す RS1-6。計画 plan/role-restructure.md の 5-4)。

純粋な関数と定数だけ(ファイル・ネットワーク・設定ファイルを読まない。ytt と標準ライブラリだけを import する)。
束は 8 つの節: hints(人の指定)・analyze(解析)・adopt(自動採用)・export(書き出し)・transcribe(認識)・post(後処理)・pack(パック)・run(流れ)。
  merge(指定)    = 既定値(DEFAULTS)に、渡された変えたい所だけを重ねた新しい束(知らない節・鍵は ValueError)
  validate(束)   = 型と範囲の検査(合わなければ理由つきの ValueError)。検査の本体は下の clean_*・top_arg・row_edge_ok など
固定の項目(FIXED)は束の鍵にしない。呼ぶ側(画面・友人の受付・CLI)は、変えたい所だけを渡す。

前半は src/home/autorun.py から移した検査(RS1-6。動きは変えていない)。autorun は同じ名前で読み直している。
後半の DEFAULTS は、今のコードにある既定値を写した物(出どころの場所を横に書いた)。今の本物のコードはまだこの表を読まない。
"""
import copy
import re

from ytt import schemas

# ---------- 区間・マーク・採用数・重みの検査(autorun.py から移した) ----------
RANGE_MAX = 10           # 1本の配信の区間の数(スタジオの MAX_REQUEST_RANGES と同じ)
RANGE_MAX_SEC = 3600     # 1つの区間の長さ(スタジオの MAX_MARK_SEC と同じ)
RANGE_PAD = 2.0          # 区間の前後に足す秒(ぴったり指定すると頭の一言が欠けやすいため。2026-10-02 ユーザー決定: 自動で付ける。RS1-7 で autorun.py から)
CUTS = ("none", "silence")          # 友人が選べるカットの方法(① 全自動のパック)
PACK_CUTS = ("rows",) + CUTS        # 束の pack.cut で選べる方法(rows = 行から = ホームの設定 autorun.cut の選択肢。run.py の _cut_method と同じ)
TX_ENGINES = ("faster-whisper", "whisper.cpp", "qwen3-asr", "llama.cpp")   # 文字起こしのエンジンを実行ごとに選ぶとき(リアルタイム切り抜きの live.auto。M2)。editor の tx_engines の id
TX_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}\Z")             # 同じくモデルの名前(src/home/prefs.py の LIVE_MODEL_RE と同じ形)
WEIGHT_KEYS = ("wAudio", "wChat", "wComments")   # 解析の重み(スタジオの解析の設定と同じ名前。0〜3)
MAX_MARKS = 50   # マークを選んだ実行で選べる数(スタジオの書き出しの1回の上限と同じ)
DEFAULT_TOP = 3
LIVE_AUTO_CUT = "none"   # M8: 自動の採用の切り抜きのカットの既定 = 区間の全体(区間は検出が静かな所に合わせて絞ってある)


def num_ok(v):
    """扱ってよい大きさの数か(bool・NaN・無限・1e7 以上は False。時刻の秒・件数・重みの検査用。エポックのミリ秒には使えない)"""
    return schemas.is_num(v) and abs(v) < 1e7


def clean_ranges(v):
    """区間の一覧 [(開始, 終了), …](秒)を確かめる。-> 整えた一覧(None・空 = 区間なし)。形が違えば ValueError"""
    if v in (None, [], ()):
        return []
    if not isinstance(v, (list, tuple)) or len(v) > RANGE_MAX:
        raise ValueError("区間は %d 個までです" % RANGE_MAX)
    out = []
    for r in v:
        if not isinstance(r, (list, tuple)) or len(r) != 2 or not num_ok(r[0]) or not num_ok(r[1]) or not 0 <= r[0] < r[1] or r[1] - r[0] > RANGE_MAX_SEC:
            raise ValueError("区間の指定が正しくありません")
        out.append((round(float(r[0]), 1), round(float(r[1]), 1)))
    return out


def pad_range(s, e, duration=None):
    """友人が入れた区間の前後に余白を足す(0 より前・動画の長さより後には出さない。長さの上限を超えるときは余白を減らす)"""
    pad = min(RANGE_PAD, max(0.0, (RANGE_MAX_SEC - (e - s)) / 2))
    a, b = max(0.0, s - pad), e + pad
    if duration and duration > 0:
        b = min(b, float(duration))
    return [round(a, 1), round(max(b, a + 0.1), 1)]


def clean_weights(v):
    """解析の重み {"wAudio", "wChat", "wComments"}(0〜3)-> 小数1桁に整えたもの か None(指定なし・形が違う)"""
    if not isinstance(v, dict) or not all(num_ok(v.get(k)) and 0 <= v[k] <= 3 for k in WEIGHT_KEYS):
        return None
    return {k: round(float(v[k]), 1) for k in WEIGHT_KEYS}


def top_arg(top):
    """採用する数(未指定は DEFAULT_TOP)。1〜30 でなければ ValueError"""
    if top in (None, ""):
        return DEFAULT_TOP
    if not isinstance(top, int) or isinstance(top, bool) or not (1 <= top <= 30):
        raise ValueError("採用する数は1〜30です")
    return top


def marks_arg(marks):
    """スタジオのマークの行から: このマークだけ進める(-> 重ならない id の組 / None = 配信の全部)"""
    if marks in (None, []):
        return None
    if not isinstance(marks, list) or len(marks) > MAX_MARKS or not all(
            isinstance(m, str) and 1 <= len(m) <= 40 and all(c.isascii() and (c.isalnum() or c in "-_") for c in m) for m in marks):
        raise ValueError("マークの指定が正しくありません")
    return tuple(dict.fromkeys(marks))


def row_edge_ok(v):
    """「行から」の設定の形(cut2resolve の pack.row_edge_from と同じ決まり: 真偽か {on?, after?, before?}(0〜2 秒))"""
    if isinstance(v, bool):
        return True
    if not isinstance(v, dict) or ("on" in v and not isinstance(v["on"], bool)):
        return False
    for k in ("after", "before"):
        x = v.get(k)
        if x not in (None, "") and (isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 2.0):
            return False
    return True


# ---------- 束の形 ----------
SECTIONS = ("hints", "analyze", "adopt", "export", "transcribe", "post", "pack", "run")
RUN_FROM = ("analyze", "adopt", "export", "transcribe", "pack")   # run.from に書ける段(run.py の MODE_STEPS の段の名前)

# 束の鍵にしない固定の項目(5-4。ユーザー決定 2026-10-09 夜)。今の設定の画面から消す物。呼ぶ側は変えられない
FIXED = {
    "fps": 30,                # 素材とパックは 30fps にそろえる(run.py の _pack_one。2026-10-04 Q1)
    "precise": True,          # 切り出しは精密(run.py の _export_body の precision "accurate")
    "maxHeight": 0,           # 画質は最大 = 上限なし(書き出しの maxHeight 0 = 上限なし。スタジオの exporter._max_height)。録画の live.quality も最大
    "upto": "pack",           # 常にパックまで作る(段を途中で止める upto は無い)
    "on_fail": "next",        # 1 本が失敗しても続ける(失敗は結果に理由つきで残す。run.py の Run.on_fail の既定 next)
}

# 既定値(今のコードにある値を写した物。出どころは行の横)。API キーは束に入れない(環境変数か鍵のファイル)
DEFAULTS = {
    "hints": {
        "ranges": [],         # 必ず切り抜く区間 [[開始秒, 終了秒], …]。無し = なし(autorun.py の clean_ranges(None))
        "people": [],         # 出る人 [{name, color?}](先頭 = 話者の分からない行の字幕の色にする人)か {count}。無し = ① が推定する
    },
    "analyze": {              # スタジオの解析の設定(src/studio/analyze.py の validate_settings 90-96 行)
        "useAudio": True, "useChat": True, "useComments": True,
        "wAudio": 1.0, "wChat": 1.0, "wComments": 0.7,
        "sensitivity": "normal",
        "count": 8,           # 候補の本数
        "length": 45,         # 切り抜きの長さ(秒)
        "preRatio": 0.65,     # 山の位置(src/pipeline/analyze/excite.py の PRE_RATIO_DEFAULT)
        "headSec": 180,       # 冒頭の減点をかける秒(analyze.py の HEAD_SEC_DEFAULT。0 で無効)
        "lagAuto": True,      # チャットの遅れ: 自動
        "lag": 8,             # 同: 固定(秒)
        "chatTimeout": 20,    # 同: チャットを待つ(秒)
    },
    "adopt": {                # 自動採用
        "top": DEFAULT_TOP,   # 採用する上限の本数(autorun.py の DEFAULT_TOP)
        "pad": 2.0,           # 区間の前後に足す秒(上の RANGE_PAD)
        "perHour": 6,         # ライブの 1 時間の候補の枠(src/home/prefs.py の DEFAULTS live.detect.perHour)
        "waitMin": 5,         # ライブの候補を最初に見てから採用まで待つ分(同 live.autoAdopt.waitMin)
    },
    "export": {               # 書き出し(run.py の _export_body。exporter.py の DEFAULT_EXPORT_VOLUME)
        "loudness": -14,      # 聞こえ方をそろえる目標(LUFS)。None = そろえない(volume を使う)
        "volume": 75,         # そろえないときの音量(%)
    },
    "transcribe": {           # 認識(重い。src/human/proof/doc_jobs.py の validate_job(文字起こしの要求)・pipeline/transcribe/tx_engines.py の DEFAULT)
        "engine": "faster-whisper", "model": "small", "language": "ja",
        "quality": "best",    # best か fast(fast は beam 1)
        "device": "auto", "vadMode": "weak", "boost": False,
        "diarize": None,      # 話者判別の人数のヒント(1〜10)。None = しない(src/home/intake.py の parse_speakers の範囲)
    },
    "post": {                 # 後処理(軽い。doc_jobs.py の validate_job と SUBTITLE_DEFAULT・各 auto は validate_job の pref() の既定)
        "wordSplit": True, "stripPunct": True,
        "orientation": "vertical",
        "maxChars": {"vertical": 16, "horizontal": 28},
        "splitChars": 24,
        "autoDict": True, "autoGloss": True, "autoContext": False, "autoLearned": False,
        "autoRedo": False, "redoLarge": True,
        "autoFill": True, "stripNames": True, "autoLlm": True,
        "diarSmooth": False,  # 試験中・既定オフ(src/ytt/settings.py の SETTINGS_PATCH_KEYS の説明)
        "learning": {"dir": None, "version": None},   # 学習データの場所と版(中身は入れない)。新しい項目で、今のコードに対応する設定は無い
    },
    "pack": {                 # パック(run.py の _pack_settings・_cut_method・src/cut2resolve/cut2resolve_core.py の DEFAULT_*)
        "size": "1080x1920",
        "loudness": 0,        # パックの音量をそろえる目標(LUFS)。0 = そろえない(volume で決める)
        "volume": 30,         # loudness が 0 のときの音量(%)
        "backup": False, "render": False, "speakerColors": True,
        "wrapChars": {"vertical": 8, "horizontal": 14},   # 字幕 1 段の文字数(src/human/proof/doc_jobs.py の SUBTITLE_DEFAULT)
        "rowEdge": True,      # 行から作るときの端の広げ方。True = 既定・False = 広げない・{on?, after?, before?}
        "cut": LIVE_AUTO_CUT,                              # カットの方法 rows・none・silence(run.py の _cut_method の既定 none)
        "cutSilence": {"noise": -35.0, "min": 0.6, "pad": 0.15},   # 無音で削る値(cut2resolve_core.py の DEFAULT_NOISE_DB・SILENCE_MIN・SILENCE_PAD)
        "videoTracks": 1,     # Text+ の映像トラックの数(1〜5。src/home/intake.py の VIDEO_TRACKS_DEFAULT・MAX)
    },
    "run": {
        "from": None,         # どの段からやり直すか(RUN_FROM)。None = 頭から
        "force": False,       # 同じ鍵でも作り直す
    },
}


def merge(spec):
    """既定値(DEFAULTS)に spec(変えたい所だけの dict。None・{} = 何も変えない)を重ねた新しい束を返す。
    辞書の値(maxChars・wrapChars・cutSilence・learning)は鍵ごとに重ね、それ以外(一覧・数・文字・None)は置き換える。
    知らない節・鍵は ValueError(綴りの間違いで黙って既定になるのを防ぐ)。値の検査はしない(validate)"""
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise ValueError("指定の束は {節: {項目: 値}} の形にしてください")
    out = copy.deepcopy(DEFAULTS)
    for sec, given in spec.items():
        if sec not in out:
            raise ValueError("知らない節です: %s(使えるのは %s)" % (sec, "・".join(SECTIONS)))
        if not isinstance(given, dict):
            raise ValueError("%s は {項目: 値} の形にしてください" % sec)
        _overlay(out[sec], given, sec)
    return out


def _overlay(base, given, path):
    for k, v in given.items():
        if k not in base:
            raise ValueError("知らない項目です: %s.%s" % (path, k))
        if isinstance(base[k], dict):
            if not isinstance(v, dict):
                raise ValueError("%s.%s は {項目: 値} の形にしてください" % (path, k))
            _overlay(base[k], v, path + "." + k)
        else:
            base[k] = copy.deepcopy(v)


# ---------- 値の検査 ----------
def _is_bool(v):
    return isinstance(v, bool)


def _num_in(lo, hi):
    return lambda v: schemas.is_num(v) and lo <= v <= hi


def _int_in(lo, hi):
    return lambda v: type(v) is int and lo <= v <= hi


def _one_of(*vals):
    return lambda v: not isinstance(v, bool) and any(v == x and type(v) is type(x) for x in vals)


def _or_none(pred):
    return lambda v: v is None or pred(v)


def _str_or_none(v):
    return v is None or isinstance(v, str)


def _dict_of(**preds):
    """鍵と値の検査が決まっている辞書(鍵は過不足なし)"""
    return lambda v: isinstance(v, dict) and set(v) == set(preds) and all(p(v[k]) for k, p in preds.items())


def _ranges_ok(v):
    if not isinstance(v, (list, tuple)):
        return False
    try:
        clean_ranges(v)
    except ValueError:
        return False
    return True


def _people_ok(v):
    """出る人: [{name, color?}](名前は 1〜40 字の文字・color は #RRGGBB)か {count: 1〜10}"""
    if isinstance(v, dict):
        return set(v) == {"count"} and _int_in(1, 10)(v["count"])
    if not isinstance(v, list):
        return False
    for p in v:
        if not isinstance(p, dict) or not set(p) <= {"name", "color"}:
            return False
        if not isinstance(p.get("name"), str) or not 1 <= len(p["name"].strip()) <= 40:
            return False
        if "color" in p and p["color"] is not None and not (isinstance(p["color"], str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", p["color"])):
            return False
    return True


def _weight_ok(v):
    """重み 1 つ(clean_weights と同じ 0〜3)"""
    return clean_weights(dict.fromkeys(WEIGHT_KEYS, v)) is not None


def _top_ok(v):
    if v in (None, ""):
        return False
    try:
        top_arg(v)
    except ValueError:
        return False
    return True


def _model_ok(v):
    return isinstance(v, str) and TX_MODEL_RE.match(v) is not None


_LUFS = (-11, -14, -16, -18)   # 聞こえ方をそろえる目標(スタジオの書き出し・編集の設定と同じ)
_CHARS_ORIENT = {"vertical": _int_in(4, 80), "horizontal": _int_in(4, 80)}
_WRAP_ORIENT = {"vertical": _int_in(2, 40), "horizontal": _int_in(2, 40)}

# 節 -> 項目 -> (検査, 直し方の言い方)。範囲は検査の元になったコードの値(出どころは DEFAULTS の横の注)
SCHEMA = {
    "hints": {"ranges": (_ranges_ok, "区間の一覧 [[開始秒, 終了秒], …](%d 個まで・1 つ %d 秒まで)" % (RANGE_MAX, RANGE_MAX_SEC)),
              "people": (_people_ok, "[{name, color?}] の並びか {count: 1〜10}")},
    "analyze": {"useAudio": (_is_bool, "true か false"), "useChat": (_is_bool, "true か false"), "useComments": (_is_bool, "true か false"),
                "wAudio": (_weight_ok, "0〜3 の数"), "wChat": (_weight_ok, "0〜3 の数"), "wComments": (_weight_ok, "0〜3 の数"),
                "sensitivity": (_one_of("high", "normal", "low"), "high・normal・low のどれか"),
                "count": (_int_in(1, 30), "1〜30 の整数"), "length": (_num_in(10, 120), "10〜120 の数(秒)"),
                "preRatio": (_num_in(0.3, 0.9), "0.3〜0.9 の数"), "headSec": (_num_in(0, 600), "0〜600 の数(秒)"),
                "lagAuto": (_is_bool, "true か false"), "lag": (_num_in(0, 30), "0〜30 の数(秒)"),
                "chatTimeout": (_int_in(1, 120), "1〜120 の整数(秒)")},
    "adopt": {"top": (_top_ok, "1〜30 の整数"), "pad": (_num_in(0, RANGE_MAX_SEC), "0〜%d の数(秒)" % RANGE_MAX_SEC),
              "perHour": (_int_in(1, 30), "1〜30 の整数"), "waitMin": (_int_in(1, 60), "1〜60 の整数(分)")},
    "export": {"loudness": (_or_none(_one_of(*_LUFS)), "null か %s のどれか" % "・".join(map(str, _LUFS))),
               "volume": (_int_in(1, 200), "1〜200 の整数(%)")},
    "transcribe": {"engine": (_one_of(*TX_ENGINES), "%s のどれか" % "・".join(TX_ENGINES)),
                   "model": (_model_ok, "英数字と . _ - の 60 字までの名前"),
                   "language": (_one_of("ja", "en", "ko", "zh", "auto"), "ja・en・ko・zh・auto のどれか"),
                   "quality": (_one_of("best", "fast"), "best か fast"),
                   "device": (_one_of("auto", "cuda", "cpu", "vulkan"), "auto・cuda・cpu・vulkan のどれか"),
                   "vadMode": (_one_of("weak", "normal", "off"), "weak・normal・off のどれか"),
                   "boost": (_is_bool, "true か false"),
                   "diarize": (_or_none(_int_in(1, 10)), "null か 1〜10 の整数(人数)")},
    "post": {"wordSplit": (_is_bool, "true か false"), "stripPunct": (_is_bool, "true か false"),
             "orientation": (_one_of("vertical", "horizontal"), "vertical か horizontal"),
             "maxChars": (_dict_of(**_CHARS_ORIENT), "{vertical, horizontal}(どちらも 4〜80 の整数)"),
             "splitChars": (_int_in(8, 80), "8〜80 の整数"),
             "autoDict": (_is_bool, "true か false"), "autoGloss": (_is_bool, "true か false"), "autoContext": (_is_bool, "true か false"),
             "autoLearned": (_is_bool, "true か false"), "autoRedo": (_is_bool, "true か false"), "redoLarge": (_is_bool, "true か false"),
             "autoFill": (_is_bool, "true か false"), "stripNames": (_is_bool, "true か false"), "autoLlm": (_is_bool, "true か false"),
             "diarSmooth": (_is_bool, "true か false"),
             "learning": (_dict_of(dir=_str_or_none, version=_str_or_none), "{dir, version}(どちらも文字か null)")},
    "pack": {"size": (_one_of("1080x1920", "1920x1080"), "1080x1920 か 1920x1080"),
             "loudness": (_one_of(0, *_LUFS), "0 か %s のどれか" % "・".join(map(str, _LUFS))),
             "volume": (_int_in(1, 200), "1〜200 の整数(%)"),
             "backup": (_is_bool, "true か false"), "render": (_is_bool, "true か false"), "speakerColors": (_is_bool, "true か false"),
             "wrapChars": (_dict_of(**_WRAP_ORIENT), "{vertical, horizontal}(どちらも 2〜40 の整数)"),
             "rowEdge": (row_edge_ok, "true か false か {on?, after?, before?}(0〜2 秒)"),
             "cut": (_one_of(*PACK_CUTS), "%s のどれか" % "・".join(PACK_CUTS)),
             "cutSilence": (_dict_of(noise=_num_in(-90, 0), min=_num_in(0.05, 60), pad=_num_in(0, 10)),
                            "{noise: -90〜0, min: 0.05〜60, pad: 0〜10}"),
             "videoTracks": (_int_in(1, 5), "1〜5 の整数")},
    "run": {"from": (_or_none(_one_of(*RUN_FROM)), "null か %s のどれか" % "・".join(RUN_FROM)),
            "force": (_is_bool, "true か false")},
}


def validate(bundle):
    """束の型と範囲を確かめる。合わなければ、どの項目をどうするかを書いた ValueError。通れば同じ束を返す(merge の結果をそのまま渡せる)。
    節・項目は過不足なし(足りない所は merge で既定を足す。知らない所は綴りの間違い)"""
    if not isinstance(bundle, dict):
        raise ValueError("指定の束は {節: {項目: 値}} の形にしてください")
    for sec in bundle:
        if sec not in SCHEMA:
            raise ValueError("知らない節です: %s" % sec)
    for sec, items in SCHEMA.items():
        given = bundle.get(sec)
        if not isinstance(given, dict):
            raise ValueError("%s の節がありません(merge で既定を足してください)" % sec)
        for k in given:
            if k not in items:
                raise ValueError("知らない項目です: %s.%s" % (sec, k))
        for k, (pred, what) in items.items():
            if k not in given:
                raise ValueError("%s.%s がありません(merge で既定を足してください)" % (sec, k))
            if not pred(given[k]):
                raise ValueError("%s.%s は %s にしてください" % (sec, k, what))
    return bundle
