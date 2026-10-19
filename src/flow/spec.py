"""① に渡す指定の束(spec)の形・既定値・検査(RS1-6。計画 notes:plan/done/role-restructure.md の 5-4)。

純粋な関数と定数だけ(ファイル・ネットワーク・設定ファイルを読まない。ytt と標準ライブラリだけを import する)。
束は 8 つの節: hints(人の指定)・analyze(解析)・adopt(自動採用)・export(書き出し)・transcribe(認識)・post(後処理)・pack(パック)・run(流れ)。
  merge(指定)    = 既定値(DEFAULTS)に、渡された変えたい所だけを重ねた新しい束(知らない節・鍵は ValueError)
  validate(束)   = 型と範囲の検査(合わなければ理由つきの ValueError)。検査の本体は下の clean_*・top_arg・row_edge_ok など
固定の項目(FIXED)は束の鍵にしない。呼ぶ側(画面・友人の受付・CLI)は、変えたい所だけを渡す。

前半は検査(RS1-6)。autorun は同じ名前で読み直している。
後半の DEFAULTS は既定値(出どころの場所を横に書いた)。
末尾の「束 → 本文」(RS6 b-0)は、段(flow/run.py)が各ツールの API に渡す本文を束から作る純粋な関数:
  export_body(束, 配信, マーク)・tx_opts(束)・pack_output(束)。解析の設定は束の analyze 節をそのまま渡す。
入口(src/app/autorun.py の build_spec)は画面の設定から束を組む = 段は設定ファイルも GET /api/settings も読まない(5-4)。
5-4 の固定(切り出しの精密・画質の上限なし・パックの fps 30)は FIXED の値をいつも使う(RS7-1 S4 = 決定 3-30 Q2。画面だけの値の口は無い)。
学習データの用語集は束に入れない(編集の受付が要求に無ければ自分の設定から読む = human/proof/doc_jobs.validate_job・CLI は flow/tools の Learning)。
"""
import copy
import re

from ytt import marks as _marks, schemas

# ---------- 区間・マーク・採用数・重みの検査 ----------
RANGE_MAX = _marks.MAX_REQUEST_RANGES   # 1本の配信の区間の数(スタジオと同じ = ytt/marks)
# 1 つの区間の長さは上限なし(友人の依頼の要件 C-2-7・C-5-5。人が付けるマークの 60 分の上限は ytt/marks)
PAD_MAX = 3600           # 区間の前後の余白(束の adopt.pad)の上限(秒)
MARGIN_DEFAULT, MARGIN_MAX = _marks.CLIP_MARGIN_DEFAULT, _marks.CLIP_MARGIN_MAX   # 切り抜きの前後の余白(LD-2f。ytt/marks)
RANGE_TIME_MAX = 360000  # 区間の時刻の上限(秒 = 100 時間。これより後は形が違う扱い。友人の受付の検査から)
RANGE_PAD = 2.0          # 区間の前後に足す秒(ぴったり指定すると頭の一言が欠けやすいため。ユーザー決定: 自動で付ける)
CUTS = ("none", "silence")          # 友人が選べるカットの方法(① 全自動のパック)
PACK_CUTS = ("rows",) + CUTS        # 束の pack.cut で選べる方法(rows = 行から = ホームの設定 autorun.cut の選択肢。run.py の _cut_method と同じ)
# 文字起こしのエンジン・モデル・機器(束の transcribe 節・リアルタイム切り抜きの live.auto(M2)・この PC の設定 machine)。editor の tx_engines の id。
# 束から選べるのは whisper.cpp・large-v3・vulkan(cuda)だけ(ユーザー決定「普段よく使っているモデル以外は要らない」)。
# faster-whisper は ① の中の CPU の逃げ道(GPU が実行時に失敗したとき・再認識など)として残るが、束からは選ばない。
TX_ENGINES = ("whisper.cpp",)
TX_MODELS = ("large-v3",)
TX_DEVICES = ("vulkan", "cuda")   # cuda = whisper.cpp の CUDA 版(F1 F0-2。友人の PC の NVIDIA。エンジンは同じ whisper.cpp = implied_engine)
# 旧い値(束・machine.json・保存した設定に書かれていることがある物)。断らずに上の値へ読み替える(read_legacy_tx。merge と machine が使う)
LEGACY_TX_ENGINES = ("faster-whisper", "qwen3-asr", "llama.cpp")
LEGACY_TX_DEVICES = ("auto", "cpu")   # cuda は今の値(旧いエンジンと組で来た cuda = faster-whisper の CUDA だけ vulkan に読む = merge)
LEGACY_TX_MODEL_RE = re.compile(r"^(?!\.)[A-Za-z0-9_.-]{1,60}(/(?!\.)[A-Za-z0-9_.-]{1,60})?\Z")   # 旧いモデルの名前の形(small・kotoba-tech/… など。worker_client.MODEL_RE と同じ形)
TX_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}\Z")             # モデルの名前の形(LLM の後処理のモデル llmModel の検査)
WEIGHT_KEYS = ("wAudio", "wChat", "wComments")   # 解析の重み(スタジオの解析の設定と同じ名前。0〜3)
MAX_MARKS = 50   # マークを選んだ実行で選べる数(スタジオの書き出しの1回の上限と同じ)
DEFAULT_TOP = 3
LIVE_AUTO_CUT = "none"   # M8: 自動の採用の切り抜きのカットの既定 = 区間の全体(区間は検出が静かな所に合わせて絞ってある)


def num_ok(v):
    """扱ってよい大きさの数か(bool・NaN・無限・1e7 以上は False。時刻の秒・件数・重みの検査用。エポックのミリ秒には使えない)"""
    return schemas.is_num(v) and abs(v) < 1e7


def _hms(sec):
    sec = int(sec)
    return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def check_range(r):
    """区間 1 つ (開始, 終了)(秒)を確かめる(理由つきの検査。opt-human 9b-2)。-> (小数 1 桁に丸めた (開始, 終了) か None, 断った理由)。
    時刻は 0〜RANGE_TIME_MAX 秒・開始 < 終了(長さの上限なし = 要件 C-2-7・C-5-5)。丸めたあと長さ 0 になる区間(0.01〜0.04 など)も断る。
    友人の受付(③ human/friend/intake.parse_ranges)と束の検査 clean_ranges が同じこれを使う"""
    s, e = r if isinstance(r, (list, tuple)) and len(r) == 2 else (None, None)
    if not all(num_ok(x) and 0 <= x <= RANGE_TIME_MAX for x in (s, e)):
        return None, "区間の形が正しくありません"
    a, b = round(float(s), 1), round(float(e), 1)
    if e <= s:
        return None, "区間 %s〜%s: 終了が開始より前です" % (_hms(s), _hms(e))
    if b <= a:
        return None, "区間 %s〜%s: 短すぎます(0.1 秒より長くしてください)" % (_hms(s), _hms(e))
    return (a, b), ""


def check_ranges(v):
    """区間の一覧 [(開始, 終了), …] -> ([丸めた (開始, 終了)], [断った理由])。形の違う区間だけ断る(ほかは進める。友人の依頼の受付の決まり)。
    RANGE_MAX 個まで(超えた分は理由つきで断る)・同じ区間は 1 つだけ。一覧でなければ全体を断る"""
    if v in (None, [], ()):
        return [], []
    if not isinstance(v, (list, tuple)):
        return [], ["区間の形が正しくありません"]
    ok, bad = [], []
    for r in v:
        got, why = check_range(r)
        if got is None:
            bad.append(why)
        elif len(ok) >= RANGE_MAX:
            bad.append("区間 %s〜%s: 1本の配信の区間は %d 個までです" % (_hms(got[0]), _hms(got[1]), RANGE_MAX))
        elif got not in ok:
            ok.append(got)
    return ok, bad


def clean_ranges(v):
    """区間の一覧 [(開始, 終了), …](秒)を確かめる。-> 整えた一覧(None・空 = 区間なし)。形が違えば ValueError。
    1 つずつの検査は check_range(丸めたあと長さ 0 の区間も断る)。こちらは 1 つでも合わなければ全体を断る(束・まとめて実行の受付)"""
    if v in (None, [], ()):
        return []
    if not isinstance(v, (list, tuple)) or len(v) > RANGE_MAX:
        raise ValueError("区間は %d 個までです" % RANGE_MAX)
    out = []
    for r in v:
        got, _why = check_range(r)
        if got is None:
            raise ValueError("区間の指定が正しくありません")
        out.append(got)
    return out


def pad_range(s, e, duration=None, pad=RANGE_PAD):
    """友人が入れた区間の前後に余白 pad 秒(束の adopt.pad)を足す(0 より前・動画の長さより後には出さない。区間の長さの上限は無い)"""
    a, b = max(0.0, s - pad), e + pad
    if duration and duration > 0:
        b = min(b, float(duration))
    return [round(a, 1), round(max(b, a + 0.1), 1)]


def check_weights(v):
    """解析の重み {"wAudio", "wChat", "wComments"}(0〜3)を確かめる(理由つきの検査。opt-human 9b-2)。
    -> (小数1桁に整えたもの か None, 断った理由)。友人の受付(③ intake.parse_weights)と clean_weights が同じこれを使う"""
    if not isinstance(v, dict):
        return None, "解析の重みの形が正しくありません"
    miss = [k for k in WEIGHT_KEYS if not (num_ok(v.get(k)) and 0 <= v[k] <= 3)]
    if miss:
        return None, "解析の重みは 0〜3 の数です(%s)" % "・".join(miss)
    return {k: round(float(v[k]), 1) for k in WEIGHT_KEYS}, ""


def clean_weights(v):
    """解析の重み {"wAudio", "wChat", "wComments"}(0〜3)-> 小数1桁に整えたもの か None(指定なし・形が違う)。検査は check_weights"""
    return check_weights(v)[0]


TOP_MAX = 30   # 採用する数の上限(束の adopt.top。受付の submit_urls・束の検査 _top_ok もこの top_arg を通す)
REQUEST_TOP_MAX = 10   # 友人の依頼の 1 配信の本数の上限(友人のアプリが書く数・受付の URL の行。束の上限 TOP_MAX より狭い。friendapp/sync・human/friend/intake が読む)


def top_arg(top):
    """採用する数(未指定は DEFAULT_TOP)。1〜TOP_MAX でなければ ValueError"""
    if top in (None, ""):
        return DEFAULT_TOP
    if not isinstance(top, int) or isinstance(top, bool) or not (1 <= top <= TOP_MAX):
        raise ValueError("採用する数は1〜%dです" % TOP_MAX)
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
RUN_UPTO = ("transcribe", "pack")   # run.upto = どこまで作るか(transcribe = 文字起こしまで・pack = パックまで。RV A2)。配信の URL は pack だけ(transcribe は動画ファイル = ② の口・CLI の --spec だけ。10-19)
ON_FAIL = ("next", "stop")          # run.onFail = 1 本が失敗したとき(next = 残りを続ける・stop = そこで止める。RV A2)
# run.requested に書ける項目(依頼が決めた項目。RV A2): weights = analyze の重み 3 つ(解析済みでも重みが違えば解析し直す)・
# cut = pack.cut(リアルタイム切り抜きの自動の採用の既定より強い)・videoTracks = pack.videoTracks(1 でも要求に書く)・
# engine・model = transcribe の engine・model(機器から決まるエンジンと同じでも要求に書く)
RUN_REQUESTED = ("weights", "cut", "videoTracks", "engine", "model")
STREAMER_MAX = 120   # hints.streamer の長さ(封筒の題と同じ)

# 束の鍵にしない固定の項目(5-4。ユーザー決定)。設定の画面には出さない。呼ぶ側は変えられない
FIXED = {
    "fps": 30,                # 素材とパックは 30fps にそろえる(run.py の _pack_one。Q1)
    "precise": True,          # 切り出しは精密(run.py の _export_body の precision "accurate")
    "maxHeight": 0,           # 画質は最大 = 上限なし(書き出しの maxHeight 0 = 上限なし。スタジオの exporter._max_height)。録画の live.quality も最大
}

# 既定値(今のコードにある値を写した物。出どころは行の横)。API キーは束に入れない(環境変数か鍵のファイル)
DEFAULTS = {
    "hints": {
        "ranges": [],         # 必ず切り抜く区間 [[開始秒, 終了秒], …]。無し = なし(autorun.py の clean_ranges(None))
        "people": [],         # 出る人 [{name, color?}](先頭 = 話者の分からない行の字幕の色にする人)か {count}。無し = ① が推定する。
                              # ② の口 submit は、配信者(下の streamer)が無ければ先頭の名前を配信者(字幕の色)にする(RS7-1 S4。flow/runqueue.py)
        "streamer": None,     # 字幕の色にする配信者(照らし合わせた名前)。None = 自動(出る人の先頭 → 覚えた名前 → チャンネル名)・"" = 色なし(RV A2)
    },
    "analyze": {              # スタジオの解析の設定(src/pipeline/analyze/analyze.py の validate_settings 90-96 行)
        "useAudio": True, "useChat": True, "useComments": True,
        "wAudio": 1.0, "wChat": 1.0, "wComments": 0.7,
        "sensitivity": "normal",
        "count": 8,           # 候補の本数
        "length": 45,         # 切り抜きの長さ(秒。区間が場面ごとの形 = excite.SHAPE_DEFAULT のときは、場面が取れないときの長さ)
        "preRatio": 0.65,     # 山の位置(src/pipeline/analyze/excite.py の PRE_RATIO_DEFAULT)
        "headSec": 180,       # 冒頭の減点をかける秒(analyze.py の HEAD_SEC_DEFAULT。0 で無効)
        "lagAuto": True,      # チャットの遅れ: 自動
        "lag": 8,             # 同: 固定(秒)
        "chatTimeout": 20,    # 同: チャットを待つ(秒)
    },
    "adopt": {                # 自動採用
        "top": DEFAULT_TOP,   # 採用する上限の本数(autorun.py の DEFAULT_TOP)
        "pad": 2.0,           # 区間の前後に足す秒(上の RANGE_PAD)
        "perHour": 6,         # ライブの 1 時間の候補の枠(src/app/prefs.py の DEFAULTS live.detect.perHour)
        "waitMin": 5,         # ライブの候補を最初に見てから採用まで待つ分(同 live.autoAdopt.waitMin)
        "sens": "normal",     # ライブの検出の感度 high|normal|low(human/friend/live_requests.py の SETTINGS_DEFAULT sens)
        "afterStream": True,  # ライブ: 配信が終わったあとにアーカイブから全自動で流すか(同 SETTINGS_DEFAULT afterStream)
    },
    "export": {               # 書き出し(run.py の _export_body。exporter.py の DEFAULT_EXPORT_VOLUME)
        "loudness": -14,      # 聞こえ方をそろえる目標(LUFS)。None = そろえない(volume を使う)
        "volume": 75,         # そろえないときの音量(%)
        "margin": MARGIN_DEFAULT,   # 切り抜きの動画の前後に足す余白(秒。LD-2f。マークの区間は変えない = パックの段が話の切れ目で両端を決める。0 = 足さない = スイッチ)
    },
    "transcribe": {           # 認識(重い。src/human/proof/doc_jobs.py の validate_job(文字起こしの要求))。GPU の whisper.cpp + large-v3
        "engine": "whisper.cpp", "model": "large-v3", "language": "ja",
        "quality": "best",    # best か fast(fast は beam 1)
        "device": "vulkan", "vadMode": "weak", "boost": False,
        "diarize": None,      # 話者判別の人数のヒント(1〜10)。None = しない(友人の依頼の人数 = flow/order.speakers_arg も同じ範囲)
    },
    "post": {                 # 後処理(軽い。doc_jobs.py の validate_job と SUBTITLE_DEFAULT・各 auto は validate_job の pref() の既定)
        "wordSplit": True, "stripPunct": True,
        "orientation": "vertical",
        "maxChars": {"vertical": 16, "horizontal": 28},
        "splitChars": 24,
        "autoDict": True, "autoGloss": True, "autoContext": False, "autoLearned": False,
        "autoFill": True, "stripNames": True, "autoLlm": True,
        "llmModel": "qwen3-8b",   # LLM の後処理のモデル(src/pipeline/transcribe/llm.py の LLM_MODEL。この PC の設定 flow/machine.py が重ねる。RS7-1 S1)
        "diarSmooth": False,  # 試験中・既定オフ(src/ytt/settings.py の SETTINGS_PATCH_KEYS の説明)
        "learning": {"version": ""},   # 学習データの版(中身も場所も束に入れない。場所は機械の設定 machine。決定 3-30 Q3)。"" = 指定なし。違えば後処理の鍵が変わる
    },
    "pack": {                 # パック(run.py の _pack_settings・_cut_method・src/pipeline/pack/cut2resolve_core.py の DEFAULT_*)
        "size": "1080x1920",
        "loudness": 0,        # パックの音量をそろえる目標(LUFS)。0 = そろえない(volume で決める)
        "volume": 30,         # loudness が 0 のときの音量(%)
        "render": False, "speakerColors": True,
        "wrapChars": {"vertical": 8, "horizontal": 14},   # 字幕 1 段の文字数(src/human/proof/doc_jobs.py の SUBTITLE_DEFAULT)
        "rowEdge": True,      # 行から作るときの端の広げ方。True = 既定・False = 広げない・{on?, after?, before?}
        "snapEdges": True,    # 切り抜きの両端を話の切れ目へ詰める(LD-2c = src/pipeline/analyze/breaks.py。スイッチ。「編集」でカットを決めた文書には効かない)
        "cut": LIVE_AUTO_CUT,                              # カットの方法 rows・none・silence(run.py の _cut_method の既定 none)
        "cutSilence": {"noise": -35.0, "min": 0.6, "pad": 0.15},   # 無音で削る値(cut2resolve_core.py の DEFAULT_NOISE_DB・SILENCE_MIN・SILENCE_PAD)
        "videoTracks": 1,     # Text+ の映像トラックの数(1〜5。友人の依頼の数は flow/order.video_tracks_arg がここで確かめる)
    },
    "run": {
        "from": None,         # どの段からやり直すか(RUN_FROM)。None = 頭から
        "force": False,       # 同じ鍵でも作り直す
        "repack": False,      # パックがあれば作り直す(文字起こしは作り直さない。Run の欄 overwrite。RS7-1 S3)
        "upto": "pack",       # どこまで作るか(RUN_UPTO。transcribe = 文字起こしまで。from と組で段の並び = flow/run.py の steps_of)
        "onFail": "next",     # 1 本が失敗したとき(ON_FAIL。入口はホームの設定 autorun.onFail)
        "requested": [],      # 依頼が決めた項目(RUN_REQUESTED。画面の既定・自動の決め方より強い。旧い鍵 run.pinned も読む = RENAMED_KEYS。
                              # 「依頼が決めた重みなら解析し直す・ライブの自動の採用の既定より強い・1 でも要求に書く」の印)
    },
}


def merge(spec):
    """既定値(DEFAULTS)に spec(変えたい所だけの dict。None・{} = 何も変えない)を重ねた新しい束を返す。
    辞書の値(maxChars・wrapChars・cutSilence・learning)は鍵ごとに重ね、それ以外(一覧・数・文字・None)は置き換える。
    知らない節・鍵は ValueError(綴りの間違いで黙って既定になるのを防ぐ)。値の検査はしない(validate)。
    旧い値は断らずに読み替える: transcribe の engine・model・device の旧い値は read_legacy_tx・使わない項目(RETIRED_KEYS)は捨てる"""
    return _merge_into(copy.deepcopy(DEFAULTS), spec)


def merge_onto(base, spec):
    """土台の束 base(検査済みの束 = 受付の build_spec など)に spec(変えたい所だけ)を重ねた新しい束(RV A1。② の口 submit の土台)。
    重ね方は merge と同じ。ただし run.requested は足し合わせ・run.force・run.repack はどちらかが真なら真(依頼が決めた印を土台が消さない =
    ライブの録画の束 + 書き出したあとの欄。Run の欄から写した差分の重ね方 _with_asked と同じ)。値の検査はしない(validate)"""
    out = _merge_into(copy.deepcopy(base), spec)
    if isinstance(spec, dict) and isinstance(spec.get("run"), dict):
        b, r = base.get("run") or {}, out["run"]
        r["requested"] = list(dict.fromkeys(list(b.get("requested") or []) + list(r.get("requested") or [])))
        for k in ("force", "repack"):
            r[k] = b.get(k) is True or r.get(k) is True
    return out


def _merge_into(out, spec):
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise ValueError("指定の束は {節: {項目: 値}} の形にしてください")
    for sec, given in spec.items():
        if sec not in out:
            raise ValueError("知らない節です: %s(使えるのは %s)" % (sec, "・".join(SECTIONS)))
        if not isinstance(given, dict):
            raise ValueError("%s は {項目: 値} の形にしてください" % sec)
        if sec == "transcribe" and given.get("engine") in LEGACY_TX_ENGINES and given.get("device") == "cuda":
            given = dict(given, device=TX_DEVICES[0])   # 旧いエンジンと組の cuda = faster-whisper の CUDA(whisper.cpp の CUDA 版ではない)
        given = {k: read_legacy_tx(k, v) if sec == "transcribe" else v for k, v in given.items() if k not in RETIRED_KEYS.get(sec, ())}
        for old, new in RENAMED_KEYS.get(sec, {}).items():   # 改名した鍵(旧い束・待ちの記録・録画の束)は今の名前で読む。両方あれば今の名前
            if old in given:
                v = given.pop(old)
                given.setdefault(new, v)
        _overlay(out[sec], given, sec)
    return out


RENAMED_KEYS = {"run": {"pinned": "requested"}}   # 改名した鍵(run.pinned → run.requested)。旧い名前は merge が今の名前に読み替える
# 使わない項目(kotoba のときの redoLarge・autoRedo・パックの予備 pack.backup = 決定 3-34)。旧い束・待ちの記録・保存した要求にあれば黙って捨てる
RETIRED_KEYS = {"post": ("redoLarge", "autoRedo"), "pack": ("backup",)}


def read_legacy_tx(field, value):
    """transcribe 節の engine・model・device の旧い値を今の値に読み替える。
    エンジン faster-whisper・qwen3-asr・llama.cpp → whisper.cpp / 機器 auto・cpu → vulkan(cuda は今の値)/ large-v3 でないモデルの名前(small・kotoba など)→ large-v3。
    それ以外(今の値・形の違う値)はそのまま返す(検査は validate)。machine.check も同じ決まりで読む"""
    if field == "engine" and isinstance(value, str) and value in LEGACY_TX_ENGINES:
        return TX_ENGINES[0]
    if field == "device" and isinstance(value, str) and value in LEGACY_TX_DEVICES:
        return TX_DEVICES[0]
    if field == "model" and isinstance(value, str) and value not in TX_MODELS and LEGACY_TX_MODEL_RE.match(value):
        return TX_MODELS[0]
    return value


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


def _version_ok(v):
    return isinstance(v, str) and len(v) <= 80


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
    if len(v) > 10:
        return False
    names = []
    for p in v:
        if not isinstance(p, dict) or not set(p) <= {"name", "color"}:
            return False
        names.append(str(p.get("name")).strip())
        if not isinstance(p.get("name"), str) or not 1 <= len(p["name"].strip()) <= 40:
            return False
        if "color" in p and p["color"] is not None and not (isinstance(p["color"], str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", p["color"])):
            return False
    return len(set(names)) == len(names)


def _pins_ok(v):
    return isinstance(v, list) and all(isinstance(x, str) and x in RUN_REQUESTED for x in v) and len(set(v)) == len(v)


def _streamer_ok(v):
    return v is None or (isinstance(v, str) and len(v) <= STREAMER_MAX)


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
_WRAP_ORIENT = {"vertical": _int_in(0, 40), "horizontal": _int_in(0, 40)}   # 0 = 改行しない(cut2resolve の textplusWrap と同じ範囲)

# 節 -> 項目 -> (検査, 直し方の言い方)。範囲は検査の元になったコードの値(出どころは DEFAULTS の横の注)
SCHEMA = {
    "hints": {"ranges": (_ranges_ok, "区間の一覧 [[開始秒, 終了秒], …](%d 個まで・時刻は 0〜%d 秒・長さの上限なし)" % (RANGE_MAX, RANGE_TIME_MAX)),
              "people": (_people_ok, "[{name, color?}] の並びか {count: 1〜10}"),
              "streamer": (_streamer_ok, "null か %d 字までの名前(空 = 色なし)" % STREAMER_MAX)},
    "analyze": {"useAudio": (_is_bool, "true か false"), "useChat": (_is_bool, "true か false"), "useComments": (_is_bool, "true か false"),
                "wAudio": (_weight_ok, "0〜3 の数"), "wChat": (_weight_ok, "0〜3 の数"), "wComments": (_weight_ok, "0〜3 の数"),
                "sensitivity": (_one_of("high", "normal", "low"), "high・normal・low のどれか"),
                "count": (_int_in(1, 30), "1〜30 の整数"), "length": (_num_in(10, 300), "10〜300 の数(秒)"),
                "preRatio": (_num_in(0.3, 0.9), "0.3〜0.9 の数"), "headSec": (_num_in(0, 600), "0〜600 の数(秒)"),
                "lagAuto": (_is_bool, "true か false"), "lag": (_num_in(0, 30), "0〜30 の数(秒)"),
                "chatTimeout": (_int_in(1, 120), "1〜120 の整数(秒)")},
    "adopt": {"top": (_top_ok, "1〜30 の整数"), "pad": (_num_in(0, PAD_MAX), "0〜%d の数(秒)" % PAD_MAX),
              "perHour": (_int_in(1, 30), "1〜30 の整数"), "waitMin": (_int_in(1, 60), "1〜60 の整数(分)"),
              "sens": (_one_of("high", "normal", "low"), "high・normal・low のどれか"), "afterStream": (_is_bool, "true か false")},
    "export": {"loudness": (_or_none(_one_of(*_LUFS)), "null か %s のどれか" % "・".join(map(str, _LUFS))),
               "volume": (_int_in(1, 200), "1〜200 の整数(%)"),
               "margin": (_num_in(0, MARGIN_MAX), "0〜%d の数(秒)" % MARGIN_MAX)},
    "transcribe": {"engine": (_one_of(*TX_ENGINES), "%s のどれか" % "・".join(TX_ENGINES)),
                   "model": (_one_of(*TX_MODELS), "%s のどれか" % "・".join(TX_MODELS)),
                   "language": (_one_of("ja", "en", "ko", "zh", "auto"), "ja・en・ko・zh・auto のどれか"),
                   "quality": (_one_of("best", "fast"), "best か fast"),
                   "device": (_one_of(*TX_DEVICES), "%s のどれか" % "・".join(TX_DEVICES)),
                   "vadMode": (_one_of("weak", "normal", "off"), "weak・normal・off のどれか"),
                   "boost": (_is_bool, "true か false"),
                   "diarize": (_or_none(_int_in(1, 10)), "null か 1〜10 の整数(人数)")},
    "post": {"wordSplit": (_is_bool, "true か false"), "stripPunct": (_is_bool, "true か false"),
             "orientation": (_one_of("vertical", "horizontal"), "vertical か horizontal"),
             "maxChars": (_dict_of(**_CHARS_ORIENT), "{vertical, horizontal}(どちらも 4〜80 の整数)"),
             "splitChars": (_int_in(8, 80), "8〜80 の整数"),
             "autoDict": (_is_bool, "true か false"), "autoGloss": (_is_bool, "true か false"), "autoContext": (_is_bool, "true か false"),
             "autoLearned": (_is_bool, "true か false"),
             "autoFill": (_is_bool, "true か false"), "stripNames": (_is_bool, "true か false"), "autoLlm": (_is_bool, "true か false"),
             "llmModel": (_model_ok, "英数字と . _ - の 60 字までの名前"),
             "diarSmooth": (_is_bool, "true か false"),
             "learning": (_dict_of(version=_version_ok), "{version}(80 字までの文字。空 = 指定なし)")},
    "pack": {"size": (_one_of("1080x1920", "1920x1080"), "1080x1920 か 1920x1080"),
             "loudness": (_one_of(0, *_LUFS), "0 か %s のどれか" % "・".join(map(str, _LUFS))),
             "volume": (_int_in(1, 200), "1〜200 の整数(%)"),
             "render": (_is_bool, "true か false"), "speakerColors": (_is_bool, "true か false"),
             "wrapChars": (_dict_of(**_WRAP_ORIENT), "{vertical, horizontal}(どちらも 0〜40 の整数。0 = 改行しない)"),
             "rowEdge": (row_edge_ok, "true か false か {on?, after?, before?}(0〜2 秒)"),
             "snapEdges": (_is_bool, "true か false"),
             "cut": (_one_of(*PACK_CUTS), "%s のどれか" % "・".join(PACK_CUTS)),
             "cutSilence": (_dict_of(noise=_num_in(-90, 0), min=_num_in(0.05, 60), pad=_num_in(0, 10)),
                            "{noise: -90〜0, min: 0.05〜60, pad: 0〜10}"),
             "videoTracks": (_int_in(1, 5), "1〜5 の整数")},
    "run": {"from": (_or_none(_one_of(*RUN_FROM)), "null か %s のどれか" % "・".join(RUN_FROM)),
            "force": (_is_bool, "true か false"), "repack": (_is_bool, "true か false"),
            "upto": (_one_of(*RUN_UPTO), "%s のどれか" % "・".join(RUN_UPTO)),
            "onFail": (_one_of(*ON_FAIL), "%s のどれか" % "・".join(ON_FAIL)),
            "requested": (_pins_ok, "%s の並び(重ならない)" % "・".join(RUN_REQUESTED))},
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


def key_ok(sec, key, value):
    """束の 1 項目の値が検査に合うか(辞書の項目は既定に重ねてから見る = {"vertical": 9} だけでもよい)。
    入口が画面の設定から束を組むとき、合わない値を既定に戻すのに使う(src/app/autorun.py の spec_from_settings)"""
    try:
        merged = merge({sec: {key: value}})[sec][key]
    except ValueError:
        return False
    return SCHEMA[sec][key][0](merged)


# ---------- 束 → 各ツールの API の本文(RS6 b-0) ----------
# 5-4 の固定の 3 つ(切り出しの精密・画質の上限・パックの fps)は FIXED の値(RS7-1 S4 = 決定 3-30 Q2)
TX_TRANSCRIBE_KEYS = ("model", "language", "quality", "device", "vadMode", "boost")   # 文字起こしの要求に渡す transcribe 節の項目
TX_POST_KEYS = ("autoDict", "wordSplit", "stripPunct", "autoGloss", "autoLearned",
                "autoFill", "stripNames", "autoLlm", "autoContext", "splitChars", "diarSmooth")   # 同じく post 節(編集の画面から始めるときと同じ。後ろの 6 つは RS7-1 S2 で足した = 要求にあれば受付が settings.json でなく要求を使う)


def hint_ranges(bundle, duration=None, pad=None):
    """束の hints.ranges -> 余白(adopt.pad。pad で上書き)を足した区間 [[開始, 終了], …](秒。動画の長さの外は落とす)。
    読む側(run.py)が使う純粋な関数。区間が無ければ []"""
    p = bundle["adopt"]["pad"] if pad is None else pad
    out = []
    for s, e in clean_ranges(bundle["hints"]["ranges"]):
        if duration and duration > 0 and s >= duration:
            continue
        out.append(pad_range(s, e, duration, p))
    return out


def hint_people(bundle):
    """束の hints.people -> {"people": [{name, color}, …](名前を整えた順)・"count": 人数か None(指定なし)}。
    {count} で来たときは people は []。[{name}…] で来たときは count = 人数"""
    v = bundle["hints"]["people"]
    if isinstance(v, dict):
        return {"people": [], "count": v["count"]}
    people = [{"name": p["name"].strip(), "color": p.get("color")} for p in v]
    return {"people": people, "count": len(people) or None}


def implied_engine(device):
    """機器から決まるエンジン(文字起こしの要求にエンジンを書かないとき。vulkan なら whisper.cpp = worker_client.req_engine と同じ決まり)。
    束の機器は vulkan か cuda(F1 F0-2。旧い auto・cpu は vulkan に読み替える)で、どちらも whisper.cpp(cuda は CUDA 版)"""
    del device   # 引数は呼ぶ側(machine・autorun・live_tx)の形のまま残す
    return TX_ENGINES[0]


def export_body(bundle, video_id, ids):
    """スタジオの書き出しの要求(POST /api/export)の本文。音量は束の export 節・精密と画質の上限は固定(FIXED = 精密・上限なし)"""
    ex = bundle["export"]
    body = {"id": video_id, "markIds": list(ids), "precision": "accurate" if FIXED["precise"] else "fast",
            "maxHeight": FIXED["maxHeight"], "volume": ex["volume"], "loudness": ex["loudness"]}
    margin = export_margin(bundle)
    if margin:   # 余白(LD-2f)は 0 でないときだけ書く(0 = 今までと同じ本文)
        body["margin"] = margin
    return body


def export_margin(bundle):
    """束の export.margin(切り抜きの前後の余白の秒。LD-2f)。無い・形が違う(余白を足す前の束)なら 0 = 今までどおり"""
    ex = bundle.get("export") if isinstance(bundle, dict) else None
    v = ex.get("margin") if isinstance(ex, dict) else None
    return float(v) if schemas.is_num(v) and 0 < v <= MARGIN_MAX else 0.0


def tx_opts(bundle):
    """「編集」の文字起こしの要求(POST /api/transcribe)の設定の部分(動画のパスは段が足す)。
    エンジンは、機器から決まるエンジンと違うときだけ書く(入口の束は機器から決めるので書かない = 編集の画面から始めるときと同じ本文)。
    LLM の後処理のモデル llmModel も既定と違うときだけ書く。用語集は書かない(学習データ = 編集の受付が自分の設定から読む。RS7-1 S4)"""
    t, p = bundle["transcribe"], bundle["post"]
    out = {k: t[k] for k in TX_TRANSCRIBE_KEYS}
    out.update({k: p[k] for k in TX_POST_KEYS})
    if t["engine"] != implied_engine(t["device"]):
        out["engine"] = t["engine"]
    if p["learning"]["version"]:
        out["learningVersion"] = p["learning"]["version"]   # 空(既定)のときは書かない = 鍵も今と同じ
    if p.get("llmModel", DEFAULTS["post"]["llmModel"]) != DEFAULTS["post"]["llmModel"]:   # LLM のモデルも既定と違うときだけ(既定の本文は今と同じ。RS7-1 S1)
        out["llmModel"] = p["llmModel"]
    return out


def pack_output(bundle):
    """パックの要求(cut2resolve の POST /api/build)の作り方 -> (行から作るときの端の広げ方 rowEdge, output に足す物, 無音で削る値 cutSilence)。
    1 段の文字数は大きさの向きに合わせる。音量は loudness(LUFS)が 0 なら volume(% が 100 なら書かない)。粗編集の動画・映像トラックは既定と違うときだけ書く。
    fps は固定の 30(FIXED。素材は 30fps にそろえる)"""
    p = bundle["pack"]
    size = p["size"]
    out = {"textplusWrap": p["wrapChars"]["horizontal" if size == "1920x1080" else "vertical"], "textplusSize": size,
           "textplusFps": str(FIXED["fps"])}
    if p["render"]:
        out["render"] = True
    out["speakerColors"] = p["speakerColors"]
    if p["loudness"]:
        out["loudness"] = p["loudness"]
    elif p["volume"] != 100:
        out["volume"] = p["volume"]
    if p["videoTracks"] != 1:
        out["videoTracks"] = p["videoTracks"]
    return copy.deepcopy(p["rowEdge"]), out, dict(p["cutSilence"])
