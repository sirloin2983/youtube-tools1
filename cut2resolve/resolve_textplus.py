# -*- coding: utf-8 -*-
"""Resolve Free向け Text+ 試験パック。Luaスクリプトを同梱する。"""
import json
import re
import shutil
from pathlib import Path

import srt2resolve as S


SCHEMA = "youtube-tools-resolve-textplus/v1"
TEMPLATE_NAME = "textplus-template.drb"


# 字幕の見た目(ユーザーの指定 2026-09-26。docs/edit-tool-design.md の 12 ①。値は Resolve の Text+ のインスペクタの画像
# C:\Users\you11\Desktop\素材 の「基本設定」「シェード1〜3」)。縦・横とも同じ(ユーザー決定)。雛形(.drb)は今のまま、スクリプトが値を入れる。
#   フォント「けいふぉんと」Regular・大きさ 0.14・字間 1.0・行間 1.0・アンカー 縦 1.0(下)/ 横 0.0(中央)
#   シェード 1 = 塗り 黒(優先順位 8)/ 2 = ふち 白・太さ 0.12・ずらす X 0.015 Y −0.02(優先順位 7)/ 5 = ふち 黒・太さ 0.18(優先順位 4)
# けいふぉんと は友人の PC に各自で入れてもらう(規約に再配布の許可が書かれていないので、パックに入れない。ユーザー決定)。
# 無ければ以前の自動選択(Windows に最初から入っている日本語フォント)に切り替え、マーカーを黄色にしてメモに書く。
# 以前の自動選択の理由: フォント名を決め打ちすると外れた(実機で Font Not Found: 「MS ゴシック」+ Semibold / Regular / 標準、「ＭＳ ゴシック」+ 標準)。
# そこで Lua 側で Resolve(Fusion)のフォント一覧を読み、候補のうち実際にあるもの・ある太さを選ぶ。一覧を読めないときは fallback。
# 入力の名前(Size・Thickness2・Offset2 など)は Fusion の Text+ のもの。入れたあと読み直し、違う値になった項目はマーカーのメモに出す
# (名前が実機と違っても気づけるように。色は 0〜1)
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


def style_inputs(style=None):
    """字幕の見た目 → Text+ に入れる [[入力の名前, 値], ...](順番どおりに入れる)。Lua はこれを入れて読み直すだけ(規則はここ1か所)"""
    st = style or TEXT_STYLE
    out = [list(kv) for kv in st["text"]]
    for e in st["shading"]:
        n = e["n"]
        out.append(["Enabled%d" % n, 1])
        out.append(["ElementShape%d" % n, e["shape"]])
        if e.get("thickness") is not None:
            out.append(["Thickness%d" % n, e["thickness"]])
        for k, v in zip(("Red", "Green", "Blue", "Alpha"), e["rgba"]):
            out.append(["%s%d" % (k, n), v])
        out.append(["Priority%d" % n, e["priority"]])
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


def build_import_plan(plan, media_file, target=None):
    """pack.Plan -> Resolve 内スクリプト専用の、パスを含まない計画JSON。
    時刻の単位: cuts・captions の startFrame/endFrame/offset は「動画の」コマ。タイムラインのコマへは Lua 側で換算する"""
    fps = plan.meta["fps"]
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
        "captions": caption_segments(plan.keeps, plan.cues_out),
        # 削除区間を戻すときのコピー元。カット済みタイムラインとは別に、元動画全体を残す。
        "sourceTimeline": {"startFrame": 0, "endFrame": int(plan.meta["total"])},
        "style": _style_data(),
    }


def _lua_quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def _style_data():
    """計画(Lua に埋め込む)の style: フォントの候補と、入れる値の並び"""
    st = json.loads(json.dumps(TEXT_STYLE))
    return {"name": st["name"], "fonts": st["fonts"], "styles": st["styles"], "autoFonts": st["autoFonts"],
            "autoStyles": st["autoStyles"], "fallback": st["fallback"], "inputs": style_inputs(TEXT_STYLE)}


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
    -- 字幕の見た目(DATA.style.inputs = [[入力の名前, 値], ...])。最初の字幕で読み直し、違う値になった入力の名前を残す(実機で名前を確かめるため)
    local styleMiss = nil
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
                for _, kv in ipairs(DATA.style.inputs) do
                    pcall(function() tool:SetInput(kv[1], kv[2]) end)
                end
                if styleMiss == nil then
                    styleMiss = {}
                    for _, kv in ipairs(DATA.style.inputs) do
                        local okGet, v = pcall(function() return tool:GetInput(kv[1]) end)
                        if not okGet or not sameValue(v, kv[2]) then table.insert(styleMiss, kv[1]) end
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
        "・見た目 " .. DATA.style.name .. (styleOk and "" or "(反映できなかった: " .. table.concat(styleMiss, ", ") .. ")") ..
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
$video = Join-Path $packageDir 'media\__VIDEO_NAME__'
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


README_NAME = "友人へ.txt"                    # Text+ パックでは、友人が最初に読むのはこの手順書
EDL_README_NAME = "予備_EDLで開く手順.txt"     # スクリプトが使えないときの予備(字幕は字幕トラックになる)


def instructions(video_name, target=None, meta=None, n_captions=None, n_cuts=None, backup=True):
    """友人向けの手順書(Text+ パックの 友人へ.txt)。簡潔に、ただし手順と注意は省かない"""
    t = dict(target or DEFAULT_TARGET)
    vertical = t["height"] > t["width"]
    info = []
    if meta:
        f = meta["fps"][0] / meta["fps"][1]
        info.append(f"動画: media/{video_name}({meta['w']}x{meta['h']}・{f:g}fps。元のまま、再圧縮していません)")
    else:
        info.append(f"動画: media/{video_name}")
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
    return f"""友人へ: Text+ 字幕つきの編集パック
====================================

Resolve の中でスクリプトを実行すると、カット済みのタイムラインと、1つずつ編集できる Text+ 字幕ができます。
{chr(10).join(info)}


■ 必要なもの
・DaVinci Resolve(無料版で可。21.1 で確認)・Windows
・字幕のフォント「けいふぉんと」(Do-Font の無料フォント)を、先に Windows に入れておいてください
  (「けいふぉんと」で検索して配布元から入手 → keifont.ttf を右クリック →「インストール」→ Resolve を起動し直す)。
  このパックには入っていません。入っていないときは Windows の日本語フォント(游ゴシック・メイリオなど)で作り、
  先頭のマーカーが黄色になります
・字幕の見た目: 黒い文字 + 白いふち + 外側の黒いふち(スクリプトが入れます)


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
・マーカーのメモに「反映できなかった: …」→ その見た目の項目がこの Resolve では入れられませんでした。送り主に、メモの文を伝えてください
・字幕が四角(□)や別の字体になる、「Font Not Found」と出る → Text+ を選び、インスペクタで日本語のフォント
    (けいふぉんと・ＭＳ ゴシックなど)と太さを選び直す。1つ直したら「属性をペースト」でほかの字幕にも反映できます
・動画が赤く表示される(オフライン)→ メディアプールで動画を右クリック →「選択したクリップを再リンク」→ このパックの media フォルダ
・音がプツプツする・割れる → 送り主に連絡(どのタイムラインで、いつから、を書いて)。
    書き出した動画では問題が出ないこともあるので、書き出して確認するのも手です


■ 注意
・media の中の動画の名前を変えない。パックのフォルダを動かしたら、2-b〜c をやり直す
{backup_note}"""


def write_files(paths, plan, out_dir, target=None, backup=True):
    """Text+固有ファイルを書き、kind -> Path を返す。target: Text+ を置くプロジェクトの fps・解像度(既定 30fps・1080x1920)。
    計画(区間・字幕・動画)は Lua に埋め込む(2026-09-26 まで別に書いていた textplus-import.json は出さない。読み直すのは read_script_plan)。
    backup: 予備(EDL と手順書)を入れたか(手順書の注意の書き方が変わる)"""
    target = dict(target or DEFAULT_TARGET)
    import_plan = build_import_plan(plan, paths["video"].relative_to(out_dir), target)
    script = importer_script(import_plan)
    S.write_text_atomic(paths["textplus_script"], script, encoding="utf-8", newline="\n")
    # Windows PowerShell 5.1はBOMなしUTF-8をANSIとして読むため、日本語文字列内のバイトを引用符扱いすることがある。
    S.write_text_atomic(paths["textplus_install"], installer_script(paths["video"].name), encoding="utf-8-sig", newline="\r\n")
    S.write_text_atomic(paths["textplus_launcher"], launcher_script(), encoding="utf-8-sig", newline="")
    S.write_text_atomic(paths["textplus_readme"],
                        instructions(plan.video.name, target, plan.meta, len(plan.cues_out or []), len(plan.keeps), backup),
                        encoding="utf-8-sig", newline="\n")
    template_source = Path(__file__).with_name(TEMPLATE_NAME)
    if not S.same_path(template_source, paths["textplus_template"]):
        shutil.copyfile(template_source, paths["textplus_template"])
    return {key: paths[key] for key in ("textplus_script", "textplus_install", "textplus_launcher", "textplus_readme", "textplus_template")}


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
