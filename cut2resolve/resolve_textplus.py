# -*- coding: utf-8 -*-
"""Resolve Free向け Text+ 試験パック。Luaスクリプトを同梱する。"""
import json
import re
import shutil
from pathlib import Path

import srt2resolve as S


SCHEMA = "youtube-tools-resolve-textplus/v1"
TEMPLATE_NAME = "textplus-template.drb"


# 字幕の見た目(ユーザーの指定 2026-09-26。docs/design/edit-tool-design.md の 12 ①。値は Resolve の Text+ のインスペクタの画像
# C:\Users\you11\Desktop\素材 の「基本設定」「シェード1〜3」)。縦・横とも同じ(ユーザー決定)。雛形(.drb)は今のまま、スクリプトが値を入れる。
#   フォント「けいふぉんと」Regular・大きさ 0.14・字間 1.0・行間 1.0・アンカー 縦 1.0(下)/ 横 0.0(中央)
#   シェード 1 = 塗り 黒(優先順位 8)/ 2 = ふち 白・太さ 0.12・ずらす X 0.015 Y −0.02(優先順位 7)/ 5 = ふち 黒・太さ 0.18(優先順位 4)
# けいふぉんと は友人の PC に各自で入れてもらう(規約に再配布の許可が書かれていないので、パックに入れない。ユーザー決定)。
# 無ければ以前の自動選択(Windows に最初から入っている日本語フォント)に切り替え、マーカーを黄色にしてメモに書く。
# 以前の自動選択の理由: フォント名を決め打ちすると外れた(実機で Font Not Found: 「MS ゴシック」+ Semibold / Regular / 標準、「ＭＳ ゴシック」+ 標準)。
# そこで Lua 側で Resolve(Fusion)のフォント一覧を読み、候補のうち実際にあるもの・ある太さを選ぶ。一覧を読めないときは fallback。
# 入力の名前(Size・Thickness2・Offset2 など)は Fusion の Text+ のもの。入れたあと読み直し、違う値になった項目はマーカーのメモに出す
# (名前が実機と違っても気づけるように。色は 0〜1)。
# 優先順位(重ね順)は、実機(Resolve 21.1。2026-09-27)で「Priority1」などが入らなかった(読み直すと値が無い)。そこで
# Resolve の入力の一覧から表示名「Priority」と要素の番号で探す → 候補の名前(Text+ の部品 text.plugin の中の文字列 PriorityBack)の順に試す。
# 見つけた名前はマーカーのメモに「読み替え」と出す(次の版で名前を直すため)。重ね順が入らないと、太い黒ふち(要素5)が白ふちを覆って見た目が崩れる
PRIORITY_LOOKUP = {"names": ["Priority", "優先順位"], "ids": ["PriorityBack%d"]}
TEXT_STYLE = {
    "name": "けいふぉんと・黒い文字・白いふち・黒いふち",
    "fonts": ["けいふぉんと", "Keifont"], "styles": ["Regular"],
    "autoFonts": ["Yu Gothic", "游ゴシック", "Meiryo", "メイリオ", "MS Gothic", "ＭＳ ゴシック", "MS ゴシック",
                  "BIZ UDGothic", "BIZ UDゴシック", "Yu Gothic UI", "Meiryo UI", "MS UI Gothic"],
    "autoStyles": ["Bold", "太字", "Regular", "標準"],     # 前のほどよい。どれも無ければ、その書体にある太さのどれか
    "fallback": ["MS Gothic", "Regular"],
    "text": [["Size", 0.14], ["CharacterSpacing", 1.0], ["LineSpacing", 1.0],
             ["VerticalTopCenterBottom", 1.0], ["HorizontalLeftCenterRight", 0.0]],
    # シェードの要素: 番号・外観(ElementShape 0 = 文字の塗り / 1 = 文字のふち)・太さ・色(赤・緑・青・アルファ)・優先順位・ずらし(X, Y)
    "shading": [
        {"n": 1, "shape": 0, "thickness": None, "rgba": [0.0, 0.0, 0.0, 1.0], "priority": 8, "offset": [0.0, 0.0]},
        {"n": 2, "shape": 1, "thickness": 0.12, "rgba": [1.0, 1.0, 1.0, 1.0], "priority": 7, "offset": [0.015, -0.02]},
        {"n": 5, "shape": 1, "thickness": 0.18, "rgba": [0.0, 0.0, 0.0, 1.0], "priority": 4, "offset": [0.0, 0.0]},
    ],
}
# 簡易版(友人向けの文字起こし簡易版。docs/plan/friend-lite-plan.md)の字幕の見た目: MS ゴシック・話者ごとの文字の色 + 話者ごとのふちの色。
# 横の動画(ふつうの 16:9)に置く前提。シェード 1 = 塗り(既定は黄色。話者ごとの色 cap.fill で変える)/ 2 = ふち(既定は黒。cap.outline で変える)。
# 要素 5(太い黒ふち)は使わないので、雛形に残っていても切る(enabled False)。
# 大きさ 0.08 は仮(実機の Resolve で確かめる。docs/plan/friend-lite-realcheck.md)。
TEXT_STYLE_LITE = {
    "name": "MSゴシック・話者ごとの文字とふちの色(簡易版)",
    "fonts": ["MS Gothic", "ＭＳ ゴシック", "MS ゴシック"], "styles": ["Regular", "標準"],
    "autoFonts": list(TEXT_STYLE["autoFonts"]), "autoStyles": list(TEXT_STYLE["autoStyles"]),
    "fallback": ["MS Gothic", "Regular"],
    "text": [["Size", 0.08], ["CharacterSpacing", 1.0], ["LineSpacing", 1.0],
             ["VerticalTopCenterBottom", 1.0], ["HorizontalLeftCenterRight", 0.0]],
    "shading": [
        {"n": 1, "shape": 0, "thickness": None, "rgba": [1.0, 0.902, 0.0, 1.0], "priority": 8, "offset": [0.0, 0.0]},
        {"n": 2, "shape": 1, "thickness": 0.15, "rgba": [0.0, 0.0, 0.0, 1.0], "priority": 7, "offset": [0.0, 0.0]},
        {"n": 5, "enabled": False},
    ],
}
# 見た目の種類(pack.build_pack の textplus_style)。default = 今までの(けいふぉんと・縦の Shorts)
TEXT_STYLES = {"default": TEXT_STYLE, "lite": TEXT_STYLE_LITE}


def hex_rgba(hex_):
    """'#RRGGBB' -> [r, g, b, 1.0](0〜1)。形が違えば None"""
    h = str(hex_ or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return [round(int(h[i:i + 2], 16) / 255.0, 4) for i in (0, 2, 4)] + [1.0]
    except ValueError:
        return None


def text_style(color=None, kind="default"):
    """字幕の見た目。color: {"hex": "#RRGGBB", "who": 配信者の名前}(配信者の名前を入れたとき。docs/archive/followup-2026-09-27.md の 4)なら
    文字(塗りの要素)をその色にする。白いふち・外側の黒いふちは同じ。無ければ TEXT_STYLE のまま(黒い文字)。
    名前 → 色の照らし合わせは ytt_core/colors.py(呼び出し側。ここは受け取った色を入れるだけ)"""
    if kind not in TEXT_STYLES:
        raise ValueError("Text+ の字幕の見た目は %s のどれかにしてください: %r" % (" / ".join(TEXT_STYLES), kind))
    st = json.loads(json.dumps(TEXT_STYLES[kind]))
    if color and color.get("hex"):
        h = str(color["hex"]).lstrip("#")
        rgb = [round(int(h[i:i + 2], 16) / 255.0, 4) for i in (0, 2, 4)]
        fill = next(e for e in st["shading"] if e["shape"] == 0)
        fill["rgba"] = rgb + [1.0]
        who = str(color.get("who") or "").strip()
        st["name"] = st["name"].replace("黒い文字", "%s色の文字(#%s)" % (who + "の" if who else "", h.upper()))
    return st


def style_inputs(style=None):
    """字幕の見た目 → Text+ に入れる [[入力の名前, 値], ...](順番どおりに入れる)。Lua はこれを入れて読み直すだけ(規則はここ1か所)"""
    st = style or TEXT_STYLE
    out = [list(kv) for kv in st["text"]]
    for e in st["shading"]:
        n = e["n"]
        if e.get("enabled") is False:   # 使わない要素(雛形に残っていても切る)。入れるのは Enabled だけ
            out.append(["Enabled%d" % n, 0])
            continue
        out.append(["Enabled%d" % n, 1])
        out.append(["ElementShape%d" % n, e["shape"]])
        if e.get("thickness") is not None:
            out.append(["Thickness%d" % n, e["thickness"]])
        for k, v in zip(("Red", "Green", "Blue", "Alpha"), e["rgba"]):
            out.append(["%s%d" % (k, n), v])
        # 3つ目: 名前で入らなかったときの探し方(表示名と要素の番号・候補の名前)。Lua の「読み替え」
        out.append(["Priority%d" % n, e["priority"], {"names": list(PRIORITY_LOOKUP["names"]), "n": n,
                                                      "ids": [x % n for x in PRIORITY_LOOKUP["ids"]]}])
        out.append(["Offset%d" % n, list(e["offset"])])
    return out
DEFAULT_TARGET = {"fps": 30, "width": 1080, "height": 1920}   # 本番: 30fps・縦(Shorts)。画面外も残して位置を変えられる設定で使う
TARGET_FPS = (24, 25, 30, 50, 60)


def parse_target(fps=None, size=None):
    """Text+ を置くタイムライン(=友人が手で作るプロジェクト)の fps・解像度。既定は 30fps・1080x1920。
    size は "1080x1920" の形。スクリプトはこの値とプロジェクトが一致するか確かめるだけで、設定は変えない。"""
    t = dict(DEFAULT_TARGET)
    if fps not in (None, ""):
        try:
            f = int(str(fps).strip())
        except ValueError:
            raise ValueError(f"Text+ の fps は {', '.join(map(str, TARGET_FPS))} のどれかにしてください: {fps!r}")
        if f not in TARGET_FPS:
            raise ValueError(f"Text+ の fps は {', '.join(map(str, TARGET_FPS))} のどれかにしてください: {fps!r}")
        t["fps"] = f
    if size not in (None, ""):
        m = re.fullmatch(r"\s*(\d{3,5})\s*[xX×]\s*(\d{3,5})\s*", str(size))
        if not m:
            raise ValueError(f"Text+ の解像度は 1080x1920 の形で書いてください: {size!r}")
        w, h = int(m.group(1)), int(m.group(2))
        if w % 2 or h % 2 or not (16 <= w <= 8192 and 16 <= h <= 8192):
            raise ValueError(f"Text+ の解像度が不正です: {size!r}")
        t["width"], t["height"] = w, h
    return t


def caption_segments(keeps, cues_out):
    """カット後の字幕(動画のコマ数で数えた時刻)を、「何番目の残す区間の、先頭から何コマ目か」に直す。
    Resolve ではタイムラインの fps が動画と違う(60fps の動画を 30fps のタイムラインに置く)ことがあるため、
    字幕はタイムラインの絶対位置ではなく、実際に置かれたクリップの位置からの相対で置く。
    字幕は remap_cues で区間ごとに分割済みなので、1つの字幕は必ず1つの区間に収まる"""
    spans, rec = [], 0
    for ks, ke in keeps:
        spans.append((rec, rec + (ke - ks)))
        rec += ke - ks
    out = []
    for i, (start, end, text) in enumerate(cues_out or [], 1):
        seg = next((k for k, (a, b) in enumerate(spans) if a <= start < b), None)
        if seg is None:
            raise ValueError(f"字幕 {i} がどの残す区間にも入りません(開始 {start} コマ)")
        a, b = spans[seg]
        out.append({"id": f"caption-{i:04d}", "startFrame": int(start), "endFrame": int(end), "text": str(text),
                    "segment": seg + 1, "offsetStart": int(start - a), "offsetEnd": int(min(end, b) - a)})
    return out


# 字幕の改行(2段。docs/design/edit-tool-design.md の 12 ②。ユーザー決定 2026-09-26: 縦 8・横 14 文字前後で改行)。
# Text+ は自動で折り返さない(大きさ 0.14 だと縦の画面の1段に 7〜8 文字ほど)ので、字幕の文字に改行を入れる
WRAP_DEFAULT = {"vertical": 8, "horizontal": 14}
WRAP_SLACK = 2                        # 1段の文字数を 2 文字まで超えるのは許す(変な所で切らない)
_NO_LINE_START = set("、。,.!?！？ーっゃゅょぁぃぅぇぉッャュョァィゥェォ」』)）〕]")   # 行の頭に来ない文字(禁則)
_BREAK_AFTER = set("、。,.!?！？ 　")
_PARTICLES = set("はがをにでともへ")   # ひらがなの並びでは、助詞のあとで改行すると読みやすい


def _char_kind(ch):
    o = ord(ch)
    if 0x30A1 <= o <= 0x30FA or ch in "ー・":
        return "K"
    if 0x4E00 <= o <= 0x9FFF or ch in "々〆":
        return "H"
    if ch.isascii() and ch.isalnum() or 0xFF10 <= o <= 0xFF19 or 0xFF21 <= o <= 0xFF3A or 0xFF41 <= o <= 0xFF5A:
        return "A"
    if 0x3041 <= o <= 0x3096:
        return "h"
    return ""


def default_wrap(target=None):
    t = dict(target or DEFAULT_TARGET)
    return WRAP_DEFAULT["vertical" if t["height"] > t["width"] else "horizontal"]


def wrap_caption(text, per_line):
    """字幕の文字を、1段 per_line 文字前後で改行する(ふつうは2段。長ければ3段以上)。per_line + 2 文字までは改行しない。
    改行する所は、理想の位置(均等に分けた所)の近くで: 句読点・空白のあと > 助詞(は・が・を…)のあと・漢字/カタカナ/英数字が始まる所。
    カタカナ・漢字・英数字の並びの途中と、行の頭に来ない文字(、。ー・小さい ゃ など)の前は避ける。per_line が 0 なら改行しない"""
    t = str(text or "").strip()
    if not per_line or per_line <= 0 or "\n" in t or len(t) <= per_line + WRAP_SLACK:
        return t
    n = -(-len(t) // (per_line + WRAP_SLACK))   # 段の数
    cuts, start = [], 0
    for k in range(1, n):
        ideal = round(len(t) * k / n)
        best, bp = None, None
        for pos in range(max(start + 1, ideal - 3), min(len(t) - 1, ideal + 3) + 1):
            a, b = t[pos - 1], t[pos]
            score = -abs(pos - ideal) * 0.3
            if a in _BREAK_AFTER:
                score += 2
            elif _char_kind(b) in ("H", "K", "A") and _char_kind(a) != _char_kind(b):   # 漢字・カタカナ・英数字が始まる所(送りがなの前では切らない)
                score += 1
            elif a in _PARTICLES and b not in _NO_LINE_START and not (a == "で" and b in "すし"):   # 「です」「でした」は切らない
                score += 1.2
            if _char_kind(a) and _char_kind(a) == _char_kind(b) and _char_kind(a) != "h":
                score -= 2                     # 語の途中
            if b in _NO_LINE_START:
                score -= 3
            if best is None or score > best:
                best, bp = score, pos
        if bp is None:
            break
        cuts.append(bp)
        start = bp
    lines, prev = [], 0
    for c in cuts + [len(t)]:
        lines.append(t[prev:c].strip())
        prev = c
    return "\n".join(x for x in lines if x)


def build_import_plan(plan, media_file, target=None, wrap=None, color=None, fills=None, outlines=None, style="default"):
    """pack.Plan -> Resolve 内スクリプト専用の、パスを含まない計画JSON。
    fills: 字幕ごとの文字の色 [[r,g,b,a] | None, ...](字幕の並びと同じ。A-2: 話者ごとの色)。None の字幕は style のまま
    outlines: 字幕ごとのふちの色(fills と同じ形。簡易版: 話者ごとのふちの色)。style: 見た目の種類(TEXT_STYLES のキー)
    時刻の単位: cuts・captions の startFrame/endFrame/offset は「動画の」コマ。タイムラインのコマへは Lua 側で換算する。
    wrap: 字幕の1段の文字数(None = 置き先の向きの既定 WRAP_DEFAULT、0 = 改行しない)"""
    fps = plan.meta["fps"]
    per_line = default_wrap(target) if wrap is None else int(wrap)
    caps = caption_segments(plan.keeps, plan.cues_out)
    for c in caps:
        c["text"] = wrap_caption(c["text"], per_line)
    for c, f in zip(caps, fills or []):
        if f:
            c["fill"] = [float(x) for x in f][:4]
    for c, f in zip(caps, outlines or []):
        if f:
            c["outline"] = [float(x) for x in f][:4]
    return {
        "schema": SCHEMA,
        "title": plan.req.name or plan.video.stem,
        "fps": f"{fps[0]}/{fps[1]}",
        "nominalFps": int(S.nominal_rate(fps)),
        "mediaFps": fps[0] / fps[1],
        "target": dict(target or DEFAULT_TARGET),
        "media": {"file": str(media_file).replace("\\", "/"), "name": plan.video.name,
                  "width": int(plan.meta["w"]), "height": int(plan.meta["h"])},
        "cuts": [{"sourceStartFrame": int(start), "sourceEndFrame": int(end)} for start, end in plan.keeps],
        "captions": caps,
        "captionWrap": per_line,
        # 削除区間を戻すときのコピー元。カット済みタイムラインとは別に、元動画全体を残す。
        "sourceTimeline": {"startFrame": 0, "endFrame": int(plan.meta["total"])},
        "style": _style_data(color, style, outlines=bool(outlines)),
    }


def _lua_quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def _style_data(color=None, kind="default", outlines=False):
    """計画(Lua に埋め込む)の style: フォントの候補と、入れる値の並び(color: 文字の色。text_style)。
    outlineN(字幕ごとのふちの色 cap.outline を入れる先の要素の番号)は、簡易版か outlines=True のときだけ入れる
    (既定の見た目の計画は今までと同じ中身のまま)"""
    st = text_style(color, kind)
    d = {"name": st["name"], "fonts": st["fonts"], "styles": st["styles"], "autoFonts": st["autoFonts"],
            "autoStyles": st["autoStyles"], "fallback": st["fallback"], "inputs": style_inputs(st),
            "fillN": next(e["n"] for e in st["shading"] if e.get("shape") == 0)}   # 文字の塗りの要素の番号(字幕ごとの色 cap.fill を入れる先)
    if kind != "default" or outlines:
        d["outlineN"] = next(e["n"] for e in st["shading"] if e.get("enabled") is not False and e.get("shape") == 1)
    return d


def importer_script(plan):
    """データを埋め込んだ自己完結Lua。Resolve FreeのI/O制限を避ける。
    決まり: プロジェクトは作らない・設定は変えない(API で作ったプロジェクトで編集ページの音が割れた。WORKLOG 2026-09-25)。
    結果は print が見えない環境があるため、タイムライン名とマーカーで画面に出す"""
    p = json.loads(json.dumps(plan))
    p["media"]["absolutePath"] = "__C2R_MEDIA_PATH__"
    p["template"] = {"absolutePath": "__C2R_TEMPLATE_PATH__"}
    p.setdefault("target", dict(DEFAULT_TARGET))
    p.setdefault("style", _style_data())
    if "mediaFps" not in p:
        n, d = p["fps"].split("/")
        p["mediaFps"] = int(n) / int(d)
    # JSONの配列・オブジェクトはLuaのテーブル構文と互換でないため、生成時にLuaリテラルへ変換。
    def lua(v):
        if isinstance(v, dict):
            return "{" + ",".join("[" + _lua_quote(k) + "]=" + lua(x) for k, x in v.items()) + "}"
        if isinstance(v, list):
            return "{" + ",".join(lua(x) for x in v) + "}"
        if isinstance(v, str):
            return _lua_quote(v)
        if v is True:
            return "true"
        if v is False:
            return "false"
        if v is None:
            return "nil"
        if isinstance(v, float):
            return repr(v)
        return str(v)
    data = lua(p)
    return LUA_TEMPLATE.replace("__C2R_DATA__", data)


LUA_TEMPLATE = r'''-- cut2resolve Text+ Import (v0.4.0; Resolve Free 21.1 Windows)
-- 開いているプロジェクトに、カット済みタイムライン CUT_TextPlus(V1 映像・A1 音声・V2 Text+)と
-- 元動画全体の SOURCE_WITH_HANDLES を追加する。プロジェクトは作らない・設定は変えない。
local DATA = __C2R_DATA__

local function uniqueTimelineName(project, base)
    local used = {}
    for i = 1, project:GetTimelineCount() do
        local timeline = project:GetTimelineByIndex(i)
        if timeline then used[timeline:GetName()] = true end
    end
    if not used[base] then return base end
    local suffix = 2
    while used[base .. "_" .. suffix] do suffix = suffix + 1 end
    return base .. "_" .. suffix
end

local function round(x) return math.floor(x + 0.5) end

-- 失敗を画面に出す(print が見えない環境向け): 空のタイムライン「C2R_エラー_…」を作る。設定は変えない
local SHORT = {
    SETTINGS = "プロジェクトのfps・解像度が違う",
    TEMPLATE = "Text+雛形を読めない",
    MEDIA = "動画を読めない_パックを移したら登録し直す",
    PLACE = "カットを置けない",
}
local ctx = {}
local function showError(code)
    if not (ctx.project and ctx.pool) then return end
    pcall(function()
        ctx.pool:SetCurrentFolder(ctx.pool:GetRootFolder())
        local t = ctx.pool:CreateEmptyTimeline(uniqueTimelineName(ctx.project, "C2R_エラー_" .. (SHORT[code] or "失敗")))
        if t then ctx.project:SetCurrentTimeline(t) end
    end)
end

local ok, err = pcall(function()
    local resolveApp = resolve
    if not resolveApp and bmd and bmd.scriptapp then resolveApp = bmd.scriptapp("Resolve") end
    if not resolveApp then error("NOAPI|Resolve APIに接続できません") end
    local pm = resolveApp:GetProjectManager()
    local project = pm and pm:GetCurrentProject()
    if not project then error("NOPROJECT|プロジェクトを開いてから実行してください") end
    local pool = project:GetMediaPool()
    ctx.project, ctx.pool = project, pool

    -- 0) 字幕のフォント: 指定のフォント(けいふぉんと)が Resolve(Fusion)のフォント一覧にあればそれ。
    --    無ければ、自動の候補(Windows の日本語フォント)のうち実際にある書体と太さ。一覧を読めなければ fallback
    local fontName, fontStyle, fontHow = DATA.style.fallback[1], DATA.style.fallback[2], "フォントの一覧を読めない"
    local fontOk = false   -- 指定のフォントを使えたか(使えなければマーカーを黄色にする)
    local okList, fontList = pcall(function()
        local fu = resolveApp:Fusion()
        local fm = fu and fu.FontManager
        return fm and fm:GetFontList()
    end)
    local function pickFrom(fams, prefer)
        for _, fam in ipairs(fams) do
            local styles = fontList[fam]
            if type(styles) == "table" then
                local pick = nil
                for _, sty in ipairs(prefer) do
                    if styles[sty] ~= nil then pick = sty; break end
                end
                if not pick then
                    local keys = {}
                    for sty, _ in pairs(styles) do table.insert(keys, tostring(sty)) end
                    table.sort(keys)
                    pick = keys[1]
                end
                if pick then return fam, pick end
            end
        end
        return nil, nil
    end
    if okList and type(fontList) == "table" and next(fontList) ~= nil then
        local fam, sty = pickFrom(DATA.style.fonts, DATA.style.styles)
        if fam then
            fontName, fontStyle, fontHow, fontOk = fam, sty, "指定のフォント", true
        else
            fam, sty = pickFrom(DATA.style.autoFonts, DATA.style.autoStyles)
            if fam then
                fontName, fontStyle, fontHow = fam, sty, DATA.style.fonts[1] .. " が無いので自動で選択。入れると次から使えます"
            else
                fontHow = "一覧に候補なし"
            end
        end
        if fontHow == "一覧に候補なし" then   -- 次に直すための手がかり: 日本語らしい書体名を少しだけメモに残す
            local seen = {}
            for fam, _ in pairs(fontList) do
                local f = tostring(fam)
                if (f:find("Goth") or f:find("Mei") or f:find("\227")) and #seen < 6 then table.insert(seen, f) end
            end
            table.sort(seen)
            fontHow = fontHow .. "(例: " .. table.concat(seen, " / ") .. ")"
        end
    end

    -- 1) 設定の確認だけ(変えない)
    local T = DATA.target
    local tfps = tonumber(project:GetSetting("timelineFrameRate"))
    local tw = tonumber(project:GetSetting("timelineResolutionWidth"))
    local th = tonumber(project:GetSetting("timelineResolutionHeight"))
    if not tfps or math.abs(tfps - T.fps) > 0.01 or tw ~= T.width or th ~= T.height then
        error("SETTINGS|" .. T.fps .. "fps・" .. T.width .. "x" .. T.height .. " のプロジェクトで実行してください(今は " ..
            tostring(tfps) .. "fps・" .. tostring(tw) .. "x" .. tostring(th) .. ")")
    end
    local ratio = tfps / DATA.mediaFps   -- 動画のコマ -> タイムラインのコマ(60fps の動画を 30fps に置くと 0.5)

    -- 2) Text+ 雛形(ビン)と動画の読み込み
    local root = pool:GetRootFolder()
    if not pool:SetCurrentFolder(root) then error("PLACE|メディアプールのMasterを選べません") end
    local knownFolders = {}
    for _, folder in ipairs(root:GetSubFolderList()) do knownFolders[folder:GetUniqueId()] = true end
    if not pool:ImportFolderFromFile(DATA.template.absolutePath) then
        error("TEMPLATE|Text+雛形を読み込めません: " .. DATA.template.absolutePath)
    end
    local templateFolder = nil
    for _, folder in ipairs(root:GetSubFolderList()) do
        if not knownFolders[folder:GetUniqueId()] then templateFolder = folder; break end
    end
    local templateClips = templateFolder and templateFolder:GetClipList() or {}
    local titleTemplate = templateClips[1]
    if not titleTemplate or titleTemplate:GetName() ~= "Text+" then error("TEMPLATE|Text+雛形の内容を確認できません") end
    pool:SetCurrentFolder(root)
    local imported = pool:ImportMedia({DATA.media.absolutePath})
    if not imported or #imported == 0 then error("MEDIA|同梱動画を読み込めません: " .. DATA.media.absolutePath) end
    local clip = imported[1]

    -- 3) カット(V1/A1)。startFrame/endFrame は動画のコマ
    local cutName = uniqueTimelineName(project, "CUT_TextPlus")
    local cutTimeline = pool:CreateEmptyTimeline(cutName)
    if not cutTimeline then error("PLACE|CUT_TextPlusタイムラインを作成できません") end
    project:SetCurrentTimeline(cutTimeline)
    local entries = {}
    for _, cut in ipairs(DATA.cuts) do
        table.insert(entries, {mediaPoolItem=clip, startFrame=cut.sourceStartFrame, endFrame=cut.sourceEndFrame - 1})
    end
    local edits = pool:AppendToTimeline(entries)
    if not edits or #edits ~= #entries then error("PLACE|カット映像を配置できません") end
    local lengthOff = 0   -- 置かれた長さが計算(動画のコマ x 換算)と1コマより大きくずれた区間の数
    for i, item in ipairs(edits) do
        local expected = (DATA.cuts[i].sourceEndFrame - DATA.cuts[i].sourceStartFrame) * ratio
        if math.abs(item:GetDuration() - expected) > 1 then lengthOff = lengthOff + 1 end
    end

    -- 4) Text+(V2)。置かれたクリップの位置 + 区間の先頭からのコマ(換算後)
    -- Resolve の「Fusion タイトルを挿入」API は配置先を指定できない(V1 に入った)。雛形を V2 へ明示配置する。
    if not cutTimeline:AddTrack("video") then error("PLACE|字幕用の映像トラックを追加できません") end
    local added, failed = 0, 0
    -- 字幕の見た目(DATA.style.inputs = [[入力の名前, 値, 探し方?], ...])。最初の字幕で1つずつ入れて読み直す。
    -- 入らなかった入力は、探し方(kv[3])があれば この Resolve の入力の一覧から表示名(names)と要素の番号(n)で探す → 候補の名前(ids)の順に試し、
    -- 入った名前を以後の字幕でも使う(styleUse。メモに「読み替え」)。それでも入らない入力はメモに出して黄色にし、
    -- 入力の一覧をパックのフォルダの textplus-inputs.txt に書く(次に名前を直す手がかり)
    local styleMiss, styleUse, styleRenamed, styleDump = nil, {}, {}, nil
    local function sameValue(a, b)
        if type(b) == "table" then
            if type(a) ~= "table" then return false end
            for i = 1, #b do
                local x = tonumber(a[i] or (i == 1 and a.X) or (i == 2 and a.Y) or nil)
                if x == nil or math.abs(x - b[i]) > 0.0001 then return false end
            end
            return true
        end
        local x = tonumber(a)
        return x ~= nil and math.abs(x - b) <= 0.0001
    end
    local function trySet(tool, name, value)
        pcall(function() tool:SetInput(name, value) end)
        local okGet, v = pcall(function() return tool:GetInput(name) end)
        return okGet and sameValue(v, value)
    end
    local function inputList(tool)   -- -> {{id, name}, ...}(読めなければ空)
        local list = {}
        local ok, l = pcall(function() return tool:GetInputList() end)
        if ok and type(l) == "table" then
            for _, inp in pairs(l) do
                local okA, a = pcall(function() return inp:GetAttrs() end)
                if okA and type(a) == "table" and a.INPS_ID then
                    table.insert(list, {id = tostring(a.INPS_ID), name = tostring(a.INPS_Name or "")})
                end
            end
        end
        table.sort(list, function(x, y) return x.id < y.id end)
        return list
    end
    local function findByName(list, look)
        local suffix = tostring(look.n or "")
        for _, x in ipairs(list) do
            for _, nm in ipairs(look.names or {}) do
                if x.name == nm and (suffix == "" or string.sub(x.id, -#suffix) == suffix) then return x.id end
            end
        end
        return nil
    end
    local function dumpInputs(list)   -- パックのフォルダ(動画の隣)に入力の一覧を書く。書けなければ nil
        local dir = string.match(tostring(DATA.media.absolutePath or ""), "^(.*)[/\\][^/\\]+$")
        if not dir or #list == 0 or not io or not io.open then return nil end
        local ok, f = pcall(io.open, dir .. "\\textplus-inputs.txt", "w")
        if not ok or not f then return nil end
        f:write("Text+ の入力の一覧(cut2resolve が見た目を入れられなかったときに書く。送り主に渡してください)\n入力の名前\t表示名\n")
        for _, x in ipairs(list) do f:write(x.id .. "\t" .. x.name .. "\n") end
        f:close()
        return "textplus-inputs.txt"
    end
    local function applyStyle(tool)
        if styleMiss ~= nil then   -- 2つ目からは、最初に決めた名前で入れる
            for _, kv in ipairs(DATA.style.inputs) do
                local name = styleUse[kv[1]] or kv[1]
                pcall(function() tool:SetInput(name, kv[2]) end)
            end
            return
        end
        styleMiss = {}
        local list = nil
        for _, kv in ipairs(DATA.style.inputs) do
            if not trySet(tool, kv[1], kv[2]) then
                local found, look = nil, kv[3]
                if type(look) == "table" then
                    list = list or inputList(tool)
                    local id = findByName(list, look)
                    if id and id ~= kv[1] and trySet(tool, id, kv[2]) then found = id end
                    if not found then
                        for _, id2 in ipairs(look.ids or {}) do
                            if trySet(tool, id2, kv[2]) then found = id2; break end
                        end
                    end
                end
                if found then
                    styleUse[kv[1]] = found
                    table.insert(styleRenamed, kv[1] .. "→" .. found)
                else
                    table.insert(styleMiss, kv[1])
                end
            end
        end
        if #styleMiss > 0 then styleDump = dumpInputs(list or inputList(tool)) end
    end
    for _, cap in ipairs(DATA.captions) do
        local item = edits[cap.segment]
        local recordFrame, duration = nil, 0
        if item then
            local segStart, segEnd = item:GetStart(), item:GetEnd()
            recordFrame = segStart + round(cap.offsetStart * ratio)
            local stop = math.min(segStart + round(cap.offsetEnd * ratio), segEnd)
            duration = stop - recordFrame
        end
        local title = nil
        if recordFrame and duration >= 1 then
            local titles = pool:AppendToTimeline({{mediaPoolItem=titleTemplate, startFrame=0,
                endFrame=duration, trackIndex=2, recordFrame=recordFrame}})
            title = titles and titles[1]
        end
        if title then
            local comp = title:GetFusionCompByIndex(1)
            local tools = comp and comp:GetToolList(false, "TextPlus") or {}
            local tool = nil
            for _, t in pairs(tools) do tool = t; break end
            -- フォント名だけ変えると既定のSemiboldが残り、存在しない組み合わせになる。太さも必ず指定する。
            if tool and title:GetStart() == recordFrame and title:GetDuration() == duration then
                tool:SetInput("StyledText", cap.text)
                tool:SetInput("Font", fontName)
                tool:SetInput("Style", fontStyle)
                applyStyle(tool)
                if cap.fill then   -- 話者ごとの色(A-2): この字幕だけ文字の塗りを変える(名前は最初の字幕で決めた読み替えに従う)
                    local n = tostring(DATA.style.fillN or 1)
                    for i, k in ipairs({"Red", "Green", "Blue", "Alpha"}) do
                        local name = styleUse[k .. n] or (k .. n)
                        pcall(function() tool:SetInput(name, cap.fill[i]) end)
                    end
                end
                if cap.outline and DATA.style.outlineN then   -- 話者ごとのふちの色(簡易版): この字幕だけふちの色を変える(読み替えは文字の色と同じ)
                    local n = tostring(DATA.style.outlineN)
                    for i, k in ipairs({"Red", "Green", "Blue", "Alpha"}) do
                        local name = styleUse[k .. n] or (k .. n)
                        pcall(function() tool:SetInput(name, cap.outline[i]) end)
                    end
                end
                added = added + 1
            else
                failed = failed + 1
            end
        else
            failed = failed + 1
        end
    end

    -- 5) 削除部分を戻すための元動画全体
    local sourceName = uniqueTimelineName(project, "SOURCE_WITH_HANDLES")
    local source = pool:CreateEmptyTimeline(sourceName)
    if source then
        project:SetCurrentTimeline(source)
        pool:AppendToTimeline({{mediaPoolItem=clip, startFrame=DATA.sourceTimeline.startFrame,
            endFrame=DATA.sourceTimeline.endFrame - 1}})
        project:SetCurrentTimeline(cutTimeline)
    end

    -- 6) 結果を画面に出す: CUT_TextPlus の先頭のマーカー(緑 = 問題なし / 黄 = 一部失敗)
    -- 入力スケーリングの値は参考としてメモに出すだけ。実機で、画面は「最短辺をマッチ: 他をクロップ」(画面の外も見えた)なのに
    -- GetSetting は scaleToFit を返したので(2026-09-25)、この値で警告すると正しい設定でも黄色になってしまう
    local scaling = tostring(project:GetSetting("timelineInputResMismatchBehavior"))
    local styleOk = (styleMiss == nil or #styleMiss == 0)
    local good = (failed == 0 and lengthOff == 0 and source ~= nil and fontOk and styleOk)
    local title = (failed == 0 and lengthOff == 0 and source ~= nil) and (good and "cut2resolve 完了" or "cut2resolve 完了(要確認)") or "cut2resolve 一部失敗"
    local note = "字幕 " .. added .. "/" .. #DATA.captions .. "・カット " .. #edits .. "/" .. #DATA.cuts ..
        "・長さのずれ " .. lengthOff .. "・字体 " .. fontName .. " " .. fontStyle .. "(" .. fontHow .. ")" ..
        "・見た目 " .. DATA.style.name .. (styleOk and "" or "(反映できなかった: " .. table.concat(styleMiss, ", ") ..
            (styleDump and "。入力の一覧: " .. styleDump or "") .. ")") ..
        (#styleRenamed > 0 and "・入力の名前を読み替え: " .. table.concat(styleRenamed, ", ") or "") ..
        "・復旧用 " .. (source and "あり" or "作れず") ..
        "・" .. tfps .. "fps " .. tw .. "x" .. th .. "・拡大設定(参考) " .. scaling
    pcall(function()
        cutTimeline:AddMarker(0, good and "Green" or "Yellow", title, note, 1)
    end)
    pm:SaveProject()
    print("cut2resolve Text+: " .. note)
end)
if not ok then
    local msg = tostring(err)
    local code = string.match(msg, "([A-Z]+)|")
    print("cut2resolve Text+: " .. msg)
    showError(code)
end
'''


def installer_script(video_name):
    """ユーザーが明示実行したときだけ、Lua1個をResolveのユーザースクリプトへ登録する。"""
    script = r'''$ErrorActionPreference = 'Stop'
$packageDir = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$source = Join-Path $packageDir 'create_resolve_textplus_project.lua'
$video = Join-Path $packageDir '__VIDEO_NAME__'
$template = Join-Path $packageDir 'textplus-template.drb'
$destinationDir = Join-Path $env:APPDATA 'Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit'
$destination = Join-Path $destinationDir 'cut2resolve TextPlus Import Lua.lua'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Luaスクリプトがありません: $source" }
if (-not (Test-Path -LiteralPath $video -PathType Leaf)) { throw "同梱動画がありません: $video" }
if (-not (Test-Path -LiteralPath $template -PathType Leaf)) { throw "Text+雛形がありません: $template" }
if (Test-Path -LiteralPath $destination -PathType Leaf) {
    $oldContent = [IO.File]::ReadAllText($destination, [Text.Encoding]::UTF8)
    if (-not $oldContent.StartsWith('-- cut2resolve Text+ Import')) {
        throw "同名の別スクリプトがあるため上書きしません: $destination"
    }
}
$luaPath = $video.Replace('\', '\\').Replace('"', '\"')
$templatePath = $template.Replace('\', '\\').Replace('"', '\"')
$content = [IO.File]::ReadAllText($source, [Text.Encoding]::UTF8).Replace('__C2R_MEDIA_PATH__', $luaPath).Replace('__C2R_TEMPLATE_PATH__', $templatePath)
if ($content.Contains('__C2R_MEDIA_PATH__') -or $content.Contains('__C2R_TEMPLATE_PATH__')) { throw 'パスの埋め込みに失敗しました' }
New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
[IO.File]::WriteAllText($destination, $content, [Text.UTF8Encoding]::new($false))
Write-Host "Resolveのユーザースクリプトに登録しました: $destination"
Write-Host 'Resolveを再起動して Workspace > Scripts > Edit > cut2resolve TextPlus Import Lua を実行してください。'
'''
    return script.replace("__VIDEO_NAME__", video_name.replace("'", "''"))


def launcher_script():
    return ('@echo off\r\n'
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_resolve_textplus_script.ps1"\r\n'
            'pause\r\n')


README_NAME = "友人へ.txt"                    # Text+ パックの手順書(コマンドで作るときだけ書く。画面・API は画面の「手順を見る」で出す)
EDL_README_NAME = "予備_EDLで開く手順.txt"     # スクリプトが使えないときの予備(字幕は字幕トラックになる)


def instructions(video_name, target=None, meta=None, n_captions=None, n_cuts=None, backup=True, look=None):
    """Text+ パックの手順書(コマンドのパックの 友人へ.txt・画面の「手順を見る」)。簡潔に、ただし手順と注意は省かない"""
    t = dict(target or DEFAULT_TARGET)
    vertical = t["height"] > t["width"]
    info = []
    if meta:
        f = meta["fps"][0] / meta["fps"][1]
        info.append(f"動画: {video_name}({meta['w']}x{meta['h']}・{f:g}fps。元のまま、再圧縮していません)")
    else:
        info.append(f"動画: {video_name}")
    if n_captions is not None and n_cuts is not None:
        info.append(f"字幕 {n_captions} 件・残す区間 {n_cuts} か所")
    size = f"{t['width']} x {t['height']}"
    scale_step = ("""   c. 左の「画像スケーリング」→「入力スケーリング」→「解像度が一致しないファイル」:
      「最短辺をマッチ: 他をクロップ」
      (横の動画が縦の画面いっぱいに拡大され、左右は画面の外に残ります。下の「出力スケーリング」は触らない)
""" if vertical else "")
    pos_tip = ("""・映す位置を変える: V1 のクリップを選び、インスペクタ →「変形」→「位置 X」。
  画面の外に残っている部分を映せます。途中で位置を変えるときは、キーフレームを打ちます。
""" if vertical else "")
    backup_note = (f"・{EDL_README_NAME} はスクリプトが使えないときの予備です(字幕は Text+ ではなく字幕トラックになり、手順も別です)\n"
                   if backup else "・スクリプトが使えないときは、送り主に「予備も入れて」と頼んでください(EDL と字幕のファイルで開く方法があります)\n")
    scale_trouble = ("""・上下に黒い帯がある / 位置 X を動かしても画面の外が出ない
    → 手順 1-c の設定が「黒帯を挿入」のまま。「最短辺をマッチ: 他をクロップ」にして保存(置いたクリップにもそのまま反映)
""" if vertical else "")
    return f"""Resolve での手順: Text+ 字幕つきの編集パック
===========================================

Resolve の中でスクリプトを実行すると、カット済みのタイムラインと、1つずつ編集できる Text+ 字幕ができます。
{chr(10).join(info)}


■ 必要なもの
・DaVinci Resolve(無料版で可。21.1 で確認)・Windows
・字幕のフォント「けいふぉんと」(Do-Font の無料フォント)を、先に Windows に入れておいてください
  (「けいふぉんと」で検索して配布元から入手 → keifont.ttf を右クリック →「インストール」→ Resolve を起動し直す)。
  このパックには入っていません。入っていないときは Windows の日本語フォント(游ゴシック・メイリオなど)で作り、
  先頭のマーカーが黄色になります
・字幕の見た目: {look or TEXT_STYLE["name"]}(スクリプトが入れます)


■ 1. 最初に1回だけ: 編集用のプロジェクトを作る
   スクリプトはプロジェクトを作りません・設定も変えません。必ず画面から作ってください。
   a. Resolve のプロジェクトマネージャーで「新規プロジェクト」を作って開く
   b. 右下の歯車(プロジェクト設定)→「マスター設定」:
      ・タイムライン解像度: {size}(一覧に無ければ「カスタム」で入力)
      ・タイムラインフレームレート: {t["fps"]}
{scale_step}   d. 「保存」。もう一度プロジェクト設定を開いて、設定が残っているか確認する
   ※ フレームレートは、タイムラインを1本でも作ると変えられなくなります。先に設定してください。
   ※ 2回目からは、このプロジェクトをそのまま使えます(パックごとに新しいタイムラインが増えます)。


■ 2. パックを受け取るたび
   a. このフォルダを、この後動かさない場所に置く(zip なら先に展開)
   b. Resolve を終了する
   c. 「ResolveにText+スクリプトを登録.bat」をダブルクリック →「登録しました」を確認して閉じる
      ・Resolve のスクリプト置き場(%APPDATA%\\Blackmagic Design\\...\\Scripts\\Edit)に Lua ファイルを1つ置くだけです。
        前のパックの分は上書きされます。ほかのファイルやプロジェクトは変更しません。
      ・「Windows によって PC が保護されました」と出たら「詳細情報」→「実行」
   d. Resolve を起動し、1 で作ったプロジェクトを開く
   e. メニューの「ワークスペース」→「スクリプト」→「cut2resolve TextPlus Import Lua」
   f. 10〜20 秒ほど待ってから触る
      (直後は Resolve が裏で準備中で、削除などはできても、インスペクタの数値を変えても反映されないことがあります)


■ 3. できるもの
・CUT_TextPlus … 編集用。V1 映像・A1 音声・V2 Text+ 字幕。
    先頭のマーカー: 緑「cut2resolve 完了」= 問題なし / 黄 = 要確認(マーカーをダブルクリックするとメモに理由)
・SOURCE_WITH_HANDLES … 元動画の全体。削った部分を戻したいときに使う
・C2R_エラー_〜 … 失敗(理由は名前に書いてあります。空のタイムラインなので消してかまいません)
・同じプロジェクトでもう一度実行すると、名前の末尾に _2 などを付けて追加します(上書きしません)


■ 4. 編集のしかた
{pos_tip}・字幕の文字を直す: V2 の Text+ を選び、インスペクタ →「タイトル」で直す。長さ・位置はタイムライン上で調整
・字幕の見た目をそろえる: 1つを整えたら、右クリック →「コピー」、ほかの Text+ を選んで右クリック →「属性をペースト」
・削った部分を戻す: SOURCE_WITH_HANDLES で範囲を選び、映像と音声をまとめてコピー → CUT_TextPlus の戻す位置に貼り付け。
  貼り付けた後は、つなぎ目と音のずれを確認
・書き出し: デリバーページで、プロジェクトと同じ {size}・{t["fps"]}fps のまま書き出す


■ 5. 困ったとき
・メニューに「cut2resolve TextPlus Import Lua」が無い
    → Resolve を起動したまま bat を実行した。Resolve を終了して起動し直す(だめなら 2-b からやり直す)
・「C2R_エラー_プロジェクトのfps・解像度が違う」
    → 開いているプロジェクトが {t["fps"]}fps・{size} ではない。1 の設定を確認(フレームレートを変えられないときは新しいプロジェクトを作る)
{scale_trouble}・「C2R_エラー_動画を読めない_パックを移したら登録し直す」
    → パックのフォルダを移した・名前を変えた。今の場所で bat をもう一度実行し、Resolve を起動し直す
・「C2R_エラー_Text+雛形を読めない」→ textplus-template.drb が無い。パックを受け取り直す
・実行してもタイムラインが1本も増えない → プロジェクトが開いていない。プロジェクトを開いてから実行
・マーカーが黄色で、メモに「けいふぉんと が無いので自動で選択」→ けいふぉんと を入れて Resolve を起動し直し、もう一度スクリプトを実行
・マーカーのメモに「反映できなかった: …」→ その見た目の項目がこの Resolve では入れられませんでした。送り主に、メモの文と
    パックのフォルダにできた textplus-inputs.txt(入力の一覧)を渡してください
・字幕が四角(□)や別の字体になる、「Font Not Found」と出る → Text+ を選び、インスペクタで日本語のフォント
    (けいふぉんと・ＭＳ ゴシックなど)と太さを選び直す。1つ直したら「属性をペースト」でほかの字幕にも反映できます
・動画が赤く表示される(オフライン)→ メディアプールで動画を右クリック →「選択したクリップを再リンク」→ このパックのフォルダ
・音がプツプツする・割れる → 送り主に連絡(どのタイムラインで、いつから、を書いて)。
    書き出した動画では問題が出ないこともあるので、書き出して確認するのも手です


■ 注意
・動画({video_name})の名前を変えない。パックのフォルダを動かしたら、2-b〜c をやり直す
{backup_note}"""


def write_files(paths, plan, out_dir, target=None, backup=True, wrap=None, color=None, fills=None, outlines=None, style="default"):
    """Text+固有ファイルを書き、kind -> Path を返す。target: Text+ を置くプロジェクトの fps・解像度(既定 30fps・1080x1920)。
    計画(区間・字幕・動画)は Lua に埋め込む(2026-09-26 まで別に書いていた textplus-import.json は出さない。読み直すのは read_script_plan)。
    backup: 予備(EDL と手順書)を入れたか(手順書の注意の書き方が変わる)"""
    target = dict(target or DEFAULT_TARGET)
    import_plan = build_import_plan(plan, paths["video"].relative_to(out_dir), target, wrap, color, fills, outlines, style)
    script = importer_script(import_plan)
    S.write_text_atomic(paths["textplus_script"], script, encoding="utf-8", newline="\n")
    # Windows PowerShell 5.1はBOMなしUTF-8をANSIとして読むため、日本語文字列内のバイトを引用符扱いすることがある。
    S.write_text_atomic(paths["textplus_install"], installer_script(paths["video"].name), encoding="utf-8-sig", newline="\r\n")
    S.write_text_atomic(paths["textplus_launcher"], launcher_script(), encoding="utf-8-sig", newline="")
    if "textplus_readme" in paths:   # コマンドのときだけ(画面・API は書かない。pack.pack_paths の readme_file)
        S.write_text_atomic(paths["textplus_readme"], readme_text(plan, target, backup, color, style), encoding="utf-8-sig", newline="\n")
    template_source = Path(__file__).with_name(TEMPLATE_NAME)
    if not S.same_path(template_source, paths["textplus_template"]):
        shutil.copyfile(template_source, paths["textplus_template"])
    return {key: paths[key] for key in ("textplus_script", "textplus_install", "textplus_launcher", "textplus_readme", "textplus_template")
            if key in paths}


def readme_text(plan, target=None, backup=True, color=None, style="default"):
    """pack.Plan -> Text+ パックの手順書の中身(書くとき・画面に出すとき共通)"""
    return instructions(plan.video.name, target, plan.meta, len(plan.cues_out or []), len(plan.keeps), backup, text_style(color, style)["name"])


def readme_from_script(text, backup=True):
    """パックの Lua(importer_script が書いたもの)から手順書の中身を作り直す(手順書のファイルが無いパックの「手順を見る」)"""
    d = read_script_plan(text)
    num, den = (int(x) for x in str(d["fps"]).split("/"))
    meta = {"w": d["media"]["width"], "h": d["media"]["height"], "fps": (num, den)}
    return instructions(d["media"]["name"], d.get("target"), meta, len(d.get("captions") or []), len(d.get("cuts") or []), backup,
                        (d.get("style") or {}).get("name"))


def read_script_plan(text):
    """パックの Lua(importer_script が書いたもの)に埋め込んだ計画を読み直す(区間・字幕・動画。テスト・調べもの用)。
    以前の textplus-import.json と同じ形(media.absolutePath などは Lua の置き換え用の印のまま)。読めなければ ValueError"""
    head = "local DATA = "
    i = text.find(head)
    if i < 0:
        raise ValueError("cut2resolve の Text+ スクリプトではありません")
    dec = json.JSONDecoder()
    pos = i + len(head)

    def value(k):
        c = text[k]
        if c == "{":
            k += 1
            if text[k] == "}":
                return {}, k + 1
            if text[k] == "[":
                out = {}
                while True:
                    key, k = dec.raw_decode(text, k + 1)
                    if text[k:k + 2] != "]=":
                        raise ValueError("Lua の表が読めません")
                    out[key], k = value(k + 2)
                    if text[k] == "}":
                        return out, k + 1
                    if text[k] != ",":
                        raise ValueError("Lua の表が読めません")
                    k += 1
            out = []
            while True:
                v, k = value(k)
                out.append(v)
                if text[k] == "}":
                    return out, k + 1
                if text[k] != ",":
                    raise ValueError("Lua の表が読めません")
                k += 1
        for word, v in (("true", True), ("false", False), ("nil", None)):
            if text.startswith(word, k):
                return v, k + len(word)
        return dec.raw_decode(text, k)
    data, _ = value(pos)
    return data
