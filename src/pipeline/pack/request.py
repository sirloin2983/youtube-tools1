"""パックの指定(JSON の spec・output)-> pack.Request と build_pack の引数。指定の読み方の 1 か所

読み手は 3 つ: cut2resolve の API(src/cut2resolve/serve.py。画面から)・② の LocalTools(src/flow/tools.py。入口なしの CLI)・コマンド
(cut2resolve.py)の引数だけは別の形(ファイルを並べて渡す)なので build_request が自前で組む。
エラーは ytt.errors.ApiError(code, message)。画面から来る値を守る厳しさが正で、LocalTools も同じ検査を通る
(動画・文字起こしは絶対パスで実在・拡張子を確かめる / keeps は時刻の順で重ならない / 数は範囲を確かめる)。
パックの出力は変えない(読み方を 1 か所にしただけ)"""
import dataclasses
import os
import urllib.parse
import urllib.request
from pathlib import Path

from ytt import colors as _colors, loudness as _loud
from ytt.errors import ApiError

from . import cut2resolve_core as C
from . import pack
from . import resolve_textplus as TP
from . import srt2resolve as S

MEDIA_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mxf", ".ts", ".mts", ".m2ts", ".flv", ".wmv"}
# 指定を省いたときの値(正は pack.Request の既定と cut2resolve_core の DEFAULT_*。コマンドも同じものを読む)
_REQ = {f.name: f.default for f in dataclasses.fields(pack.Request)}
DEFAULTS = {"noise": _REQ["noise"], "silenceMin": _REQ["silence_min"], "silencePad": _REQ["silence_pad"], "minLen": _REQ["min_len"],
            "recStart": _REQ["rec_start"], "reel": _REQ["reel"]}

# ---------------------------------------------------------------- 入力のパス

LABELS = {"video": "動画", "srt": "字幕(SRT)", "transcript": "文字起こし", "plan": "残す区間(cut-plan)", "out": "出力フォルダ"}
FIELD_EXTS = {"video": MEDIA_EXTS, "srt": S.SUB_EXTS, "transcript": C.JSON_EXTS, "plan": C.JSON_EXTS}


def clean_path(value, field):
    """画面から来たパスを整える。空なら None。Windows の「パスのコピー」の "…"・file:/// の URL も受け付ける。
    相対パスは断る(サーバーの作業フォルダ基準になって、思わぬ場所を指すため)"""
    label = LABELS.get(field, field)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ApiError("bad_path", "%sのパスは文字列で指定してください" % label)
    s = value.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    if s.lower().startswith("file:"):
        u = urllib.parse.urlsplit(s)
        s = urllib.request.url2pathname(u.path)
        if u.netloc and u.netloc.lower() != "localhost":
            s = "//" + u.netloc + s
    if not s:
        return None
    if len(s) > 4000 or "\x00" in s or "\n" in s or "\r" in s:
        raise ApiError("bad_path", "%sのパスが正しくありません" % label)
    if not os.path.isabs(s):
        raise ApiError("bad_path", "%sは、C:\\ から始まる完全なパスで指定してください(エクスプローラーでファイルを右クリック →「パスのコピー」)" % label)
    return os.path.normpath(s)


def input_path(value, field):
    """入力ファイルのパス(存在・拡張子を確かめる)。空なら None"""
    p = clean_path(value, field)
    if p is None:
        return None
    label = LABELS[field]
    ext = os.path.splitext(p)[1].lower()
    if ext not in FIELD_EXTS[field]:
        raise ApiError("bad_ext", "%sの拡張子(%s)は使えません。使えるもの: %s" % (label, ext or "なし", " ".join(sorted(FIELD_EXTS[field]))))
    try:
        ok = os.path.isfile(p)
    except (OSError, ValueError):
        ok = False
    if not ok:
        raise ApiError("not_found", "%sが見つかりません: %s" % (label, p))
    return Path(p)


# ---------------------------------------------------------------- 画面の指定 → pack.Request

def _num(v, what, lo, hi, default=None, integer=False):
    if v is None or v == "":
        if default is None:
            raise ApiError("bad_value", "%sを入れてください" % what)
        return default
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            raise ApiError("bad_value", "%sは数値で入れてください" % what)
    if C.num(v) is None:   # 真偽値・数でない・NaN・無限大
        raise ApiError("bad_value", "%sは数値で入れてください" % what)
    if not lo <= v <= hi:
        raise ApiError("bad_value", "%sは %g〜%g で入れてください" % (what, lo, hi))
    return int(v) if integer else float(v)


def _str(v, what, maxlen=200):
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > maxlen:
        raise ApiError("bad_value", "%sが正しくありません" % what)
    return v.strip()


def request_from_spec(spec):
    """画面の指定(JSON)→ pack.Request。モード: silence(① 無音で自動カット)/ keep(② 残す区間)/ list(③ 時刻リスト)
    どのモードでも、文字起こしがあれば「カット済」の行を削る(dropCutRows。既定 true)を重ねられる。
    0.23.0 で、消した画面のための指定(silenceExtra = ②③に無音を重ねる・handles = ②の前後の余白・joinGap = つなぐ隙間)は受けない
    (送っても黙って無視する = 知らない鍵と同じ。余白・つなぐ隙間はコマンドの cut2resolve.py に残る)。
    listKind "drop"(③の削る区間)は、入口のまとめて実行の「カットしない」(listText "" = 動画全体)が使うので残す"""
    if not isinstance(spec, dict):
        raise ApiError("bad_request", "指定の形が正しくありません")
    video = input_path(spec.get("video"), "video")
    if video is None:
        raise ApiError("no_video", "動画のパスを入れてください")
    sub = input_path(spec.get("srt"), "srt")
    tr = input_path(spec.get("transcript"), "transcript")
    plan = input_path(spec.get("plan"), "plan")
    if spec.get("keeps") is not None and spec.get("preset") not in (None, ""):
        raise ApiError("bad_value", "keeps と preset は一緒に使えません")
    if spec.get("preset") == "transcript-rows":
        # 文字起こしの行だけを残す(文字起こしツールの Resolve パッケージ・入口のまとめて実行と同じ規則 pack.TRANSCRIPT_ROWS。他の指定は使わない)
        if tr is None:
            raise ApiError("no_transcript", "文字起こしのファイルを入れてください")
        return pack.Request(video=video, transcript=tr, **dict(pack.TRANSCRIPT_ROWS, row_edge=row_edge_from_spec(spec)))
    if spec.get("preset") not in (None, ""):
        raise ApiError("bad_value", "preset が正しくありません")
    if spec.get("keeps") is not None:
        # 「編集」ツールのタイムラインの残す区間(秒)のとおりに作る(pack.EDIT_KEEPS)。字幕は文字起こし(か SRT)の行を区間に合わせて付ける
        return pack.Request(video=video, sub=sub, transcript=tr, keep_pairs=keeps_from_spec(spec.get("keeps")),
                            **pack.EDIT_KEEPS, **advanced_from_spec(spec))
    mode = spec.get("mode") or "silence"
    if mode not in ("silence", "keep", "list"):
        raise ApiError("bad_value", "カットの決め方が正しくありません")
    sil = spec.get("silence") if isinstance(spec.get("silence"), dict) else {}
    noise = _num(sil.get("noise"), "無音とみなす音量", -90, 0, DEFAULTS["noise"])
    smin = _num(sil.get("min"), "無音の長さ", 0.05, 60, DEFAULTS["silenceMin"])
    spad = _num(sil.get("pad"), "話の前後に残す秒数", 0, 10, DEFAULTS["silencePad"])
    base, keep_pairs, drop_pairs = "all", None, []
    if mode == "keep":
        src = spec.get("keepSource") or ("plan" if plan else "transcript")
        if src == "plan":
            if plan is None:
                raise ApiError("no_plan", "残す区間(cut-plan)のファイルを入れてください")
            base = "plan"
        elif src == "transcript":
            if tr is None:
                raise ApiError("no_transcript", "文字起こしのファイルを入れてください")
            base = "rows"
        else:
            raise ApiError("bad_value", "残す区間の元が正しくありません")
    elif mode == "list":
        text = spec.get("listText") or ""
        if not isinstance(text, str) or len(text) > 1_000_000:
            raise ApiError("bad_value", "時刻リストが長すぎます")
        try:
            pairs = C.parse_cut_list(text)
        except C.ToolError as e:
            raise ApiError("bad_list", "時刻リスト: %s" % e)
        if spec.get("listKind") == "drop":
            drop_pairs = pairs
        else:
            if not pairs:
                raise ApiError("bad_list", "残す区間を1行以上書いてください(例: 0:05 0:20)")
            base, keep_pairs = "list", pairs
    return pack.Request(
        video=video, sub=sub, transcript=tr, plan=plan, base=base, keep_pairs=keep_pairs, drop_pairs=drop_pairs,
        silence=mode == "silence", noise=noise, silence_min=smin, silence_pad=spad,
        drop_cut_rows=spec.get("dropCutRows") is not False,
        min_len=_num(spec.get("minLen"), "最短の長さ", 0, 3600, DEFAULTS["minLen"]),
        row_edge=row_edge_from_spec(spec) if base == "rows" else None, **advanced_from_spec(spec))


def row_edge_from_spec(spec):
    """spec.rowEdge(文字起こしの行から作るときに、区間の端を声の止まる所まで広げる。省略 = 既定 pack.ROW_EDGE・false = 広げない・
    {"after", "before"} = 上限の秒)-> pack.RowEdge か None"""
    try:
        return pack.row_edge_from(spec.get("rowEdge"))
    except C.ToolError as e:
        raise ApiError("bad_value", str(e))


def advanced_from_spec(spec):
    """「詳しい設定」(fps・フレーム数・タイムコード・リール名・EDL のタイトル)-> pack.Request の引数"""
    adv = spec.get("advanced") if isinstance(spec.get("advanced"), dict) else {}
    frames = adv.get("frames")
    return {"fps": _str(adv.get("fps"), "フレームレート", 20) or None,
            "frames": None if frames in (None, "") else _num(frames, "フレーム数", 1, 10**9, integer=True),
            "src_start_tc": _str(adv.get("srcStartTc"), "元動画の開始タイムコード", 20) or None,
            "rec_start": _str(adv.get("recStart"), "タイムラインの開始タイムコード", 20) or DEFAULTS["recStart"],
            "reel": _str(adv.get("reel"), "リール名", 40) or DEFAULTS["reel"], "name": _str(adv.get("name"), "EDL のタイトル", 200) or None}


def keeps_from_spec(v):
    """spec.keeps = [[開始秒, 終了秒], ...] の検査: 1〜5000 区間・有限の数・0 ≤ 開始 < 終了・時刻の順で重ならない。
    動画の長さを超える分は plan_cut(cut_list_to_keeps)が切って注意を出す"""
    if not isinstance(v, list) or not 1 <= len(v) <= pack.MAX_KEEPS:
        raise ApiError("bad_keeps", "残す区間(keeps)は 1〜%d 個にしてください" % pack.MAX_KEEPS)
    out, prev = [], 0.0
    for x in v:
        if not isinstance(x, list) or len(x) != 2:
            raise ApiError("bad_keeps", "残す区間は [開始秒, 終了秒] の形にしてください")
        if any(C.num(t) is None for t in x):
            raise ApiError("bad_keeps", "残す区間の時刻は数で指定してください")
        a, b = float(x[0]), float(x[1])
        if not 0 <= a < b <= 24 * 3600:
            raise ApiError("bad_keeps", "残す区間の時刻が正しくありません(0 ≤ 開始 < 終了)")
        if a < prev:
            raise ApiError("bad_keeps", "残す区間は時刻の順に、重ならないように並べてください")
        out.append((a, b))
        prev = b
    return out


def speaker_color_map(plan):
    """文字起こしの話者の名前 -> メンバーカラー(A-2)。名前が1人に決まる話者だけ(規則は ytt/colors.py の lookup)。
    -> ({名前: "#RRGGBB"}, [{"speaker", "name", "hex"}](画面に見せる))"""
    return _colors.speaker_colors(n for _s, _e, n in (plan.speaker_spans or []))


# 話者ごとの字幕の見た目の指定(output.speakerStyles = {話者の名前: {鍵: 値}}。docs/spec/friend-intake.md の 6)。
# 検査は鍵ごとの許可の一覧: 知っている鍵だけ受け、形の違う値・知らない鍵はその項目だけ黙って捨てる(新しい送るアプリが古い PC に
# 知らない鍵を送っても、色までは効く)。フォント・大きさなどを足すときは、ここに 鍵: 検査の関数(正しければ整えた値・違えば None)を足す
def _style_color(v):
    """"#RRGGBB" / "RRGGBB"(16 進 6 桁だけ)-> "#RRGGBB"(大文字)。違えば None"""
    return _colors.norm_hex(v) if isinstance(v, str) and len(v) <= 16 else None


SPEAKER_STYLE_KEYS = {"color": _style_color}
SPEAKER_STYLES_MAX = 50   # 人数の上限(超えた分は使わない)
SPEAKER_NAME_MAX = 60     # 名前の長さの上限(ytt.colors.NAME_MAX・cut2resolve_core.read_transcript と同じ)


def speaker_styles_from(v):
    """output.speakerStyles の検査 -> {名前: {鍵: 整えた値}}。全体の形が違えば {}(無かったことにする)。
    名前は前後の空白を除いて 1〜60 文字、50 人まで。鍵が 1 つも残らない人は除く"""
    if not isinstance(v, dict):
        return {}
    out = {}
    for name, style in v.items():
        if len(out) >= SPEAKER_STYLES_MAX:
            break
        n = name.strip() if isinstance(name, str) else ""
        if not n or len(n) > SPEAKER_NAME_MAX or not isinstance(style, dict) or n in out:
            continue
        st = {}
        for key, check in SPEAKER_STYLE_KEYS.items():
            if key in style:
                val = check(style[key])
                if val is not None:
                    st[key] = val
        if st:
            out[n] = st
    return out


def apply_speaker_styles(plan, styles, color_map, shown):
    """話者ごとの指定の色(speakerStyles)を、メンバーカラーの対応(speaker_color_map)より優先して重ねる。
    名前の照らし合わせ: 文字起こしの話者の名前と指定の名前を ytt.colors.normalize(全角・半角・かな・空白など)でそろえて同じなら合う
    (部分一致はしない。指定は人が選んだ名前なので、別の人に色が付かないように)。
    -> (pack.build_pack の speaker_colors {文字起こしの話者の名前: "#RRGGBB"}, 画面に見せる一覧 [{"speaker", "name", "hex", "from"?}])"""
    want = {}
    for name, st in styles.items():
        key = _colors.normalize(name)
        if key and st.get("color") and key not in want:   # 同じ名前になる指定が 2 つあれば先のもの
            want[key] = st["color"]
    if not want:
        return color_map, shown
    color_map, shown = dict(color_map), list(shown)
    for n in sorted({n for _s, _e, n in (plan.speaker_spans or []) if n}):
        hex_ = want.get(_colors.normalize(n))
        if hex_:
            color_map[n] = hex_
            shown = [x for x in shown if x.get("speaker") != n] + [{"speaker": n, "name": n, "hex": hex_, "from": "speakerStyles"}]
    return color_map, shown


def output_from_spec(o, video):
    """出力の指定(JSON)→ build_pack の引数のもと。0.23.0 で、消した画面のための fcpxml(補助の FCPXML)・crf(粗編集の画質)は受けない
    (送っても黙って無視する。FCPXML は作らない・粗編集は既定の画質 C.DEFAULT_CRF。どちらもコマンドの cut2resolve.py に残る)"""
    o = o if isinstance(o, dict) else {}
    out = clean_path(o.get("dir"), "out")
    textplus = bool(o.get("textplus"))
    copy_video, _ = pack.normalize_outputs(o.get("copyVideo"), False, textplus)
    try:
        target = TP.parse_target(o.get("textplusFps"), o.get("textplusSize"))
    except ValueError as e:
        raise ApiError("bad_textplus", str(e))
    # 配信者の名前 → Text+ の文字の色(メンバーカラー。手で入れたときだけ。照らし合わせは ytt/colors.py の1か所。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)
    try:
        who, hex_ = _colors.resolve(o.get("streamer") if isinstance(o.get("streamer"), str) else "")
    except ValueError as e:
        raise ApiError("bad_streamer", str(e))
    try:   # 聞こえ方の音量をそろえる目標(LUFS。残す区間だけ測って同梱の動画の音声をそろえる。2026-09-29)。省略・0 = そろえない
        loud = _loud.check_target(o.get("loudness"))
        vol = None if loud is not None else _loud.check_volume(o.get("volume"))   # LUFS でそろえないときの音量(%。元 = 100)
    except ValueError as e:
        raise ApiError("bad_loudness", str(e))
    try:   # 映像トラックの数(友人の依頼の ① 全自動で選ぶ。2026-10-02)。省略 = 1(今までどおり V1 動画・V2 字幕)
        tracks = 1 if o.get("videoTracks") in (None, "") else TP.video_tracks_value(o.get("videoTracks"))
    except ValueError as e:
        raise ApiError("bad_tracks", str(e))
    return {"videoTracks": tracks, "textplusColor": {"hex": hex_, "who": who} if hex_ else None,
            "dir": Path(out) if out else pack.default_out_dir(video), "render": bool(o.get("render")),
            "copyVideo": copy_video,
            "textplus": textplus, "textplusTarget": target, "force": o.get("force") is True,
            # 話者の名前がメンバーと合えば、その話者の字幕をその色に(A-2。既定はオン。false で配信者の色 / 黒のまま)
            "speakerColors": o.get("speakerColors") is not False,
            # 話者ごとの字幕の見た目の指定(今は色だけ)。speakerColors より優先(speakerColors が false でも効く)。形が違えば無かったことにする
            "speakerStyles": speaker_styles_from(o.get("speakerStyles")),
            "backup": o.get("backup") is True,   # Text+ パックに予備(EDL・予備の手順書・SRT)も入れる(既定は入れない = 最小限。④)
            # Text+ 字幕の1段の文字数(2段にする。省略 = 置き先の向きの既定・0 = 改行しない。②)
            "textplusWrap": None if o.get("textplusWrap") in (None, "") else _num(o.get("textplusWrap"), "字幕の1段の文字数", 0, 40, integer=True),
            "loudness": loud, "volume": vol}


def speaker_colors_for(plan, out):
    """字幕の話者の色 -> (build_pack の speaker_colors 用の {話者の名前: "#RRGGBB"}, 画面に見せる一覧)。決まり方:
    話者ごとの指定(speakerStyles)→ メンバーカラー(speakerColors が真)→ 配信者の色(textplusColor)→ 黒。out は output_from_spec の戻り"""
    if not out["textplus"]:
        return {}, []
    spk_map, spk_shown = speaker_color_map(plan) if out["speakerColors"] else ({}, [])
    if out["speakerStyles"]:
        spk_map, spk_shown = apply_speaker_styles(plan, out["speakerStyles"], spk_map, spk_shown)
    return spk_map, spk_shown
