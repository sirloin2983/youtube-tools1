# -*- coding: utf-8 -*-
"""Resolve Free向け Text+ 試験パック。Luaスクリプトを同梱する。"""
import json
import shutil
from pathlib import Path

import srt2resolve as S


SCHEMA = "youtube-tools-resolve-textplus/v1"
TEMPLATE_NAME = "textplus-template.drb"


def build_import_plan(plan, media_file):
    """pack.Plan -> Resolve 内スクリプト専用の、パスを含まない計画JSON。"""
    fps = plan.meta["fps"]
    captions = []
    for i, (start, end, text) in enumerate(plan.cues_out or [], 1):
        captions.append({"id": f"caption-{i:04d}", "startFrame": int(start), "endFrame": int(end), "text": str(text)})
    return {
        "schema": SCHEMA,
        "title": plan.req.name or plan.video.stem,
        "fps": f"{fps[0]}/{fps[1]}",
        "nominalFps": int(S.nominal_rate(fps)),
        "media": {"file": str(media_file).replace("\\", "/"), "name": plan.video.name,
                  "width": int(plan.meta["w"]), "height": int(plan.meta["h"])},
        "cuts": [{"sourceStartFrame": int(start), "sourceEndFrame": int(end)} for start, end in plan.keeps],
        "captions": captions,
        # 削除区間を戻すときのコピー元。カット済みタイムラインとは別に、元動画全体を残す。
        "sourceTimeline": {"startFrame": 0, "endFrame": int(plan.meta["total"])},
    }


def _lua_quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def importer_script(plan):
    """データを埋め込んだ自己完結Lua。Resolve FreeのI/O制限を避ける。"""
    p = dict(plan)
    p["media"]["absolutePath"] = "__C2R_MEDIA_PATH__"
    p["template"] = {"absolutePath": "__C2R_TEMPLATE_PATH__"}
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
        return str(v)
    data = lua(p)
    return r'''-- cut2resolve Text+ Import (experimental; Resolve Free 21.1 Windows unverified)
local DATA = __C2R_DATA__

local function fail(message)
    print("cut2resolve Text+: " .. tostring(message))
    return false
end

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

local ok, err = pcall(function()
    local resolveApp = resolve
    if not resolveApp and bmd and bmd.scriptapp then resolveApp = bmd.scriptapp("Resolve") end
    if not resolveApp then error("Resolve APIに接続できません") end
    local pm = resolveApp:GetProjectManager()
    if not pm then error("ProjectManagerを取得できません") end
    local project = pm:GetCurrentProject()
    local createdProject = false
    local fpsNum, fpsDen = string.match(DATA.fps, "^(%d+)/(%d+)$")
    local fps = tostring(tonumber(fpsNum) / tonumber(fpsDen))
    if not project then
        local base = "C2R_" .. string.gsub(DATA.title or "cut", "[^%w%-_]", "_")
        local name = base .. "_Lua_" .. tostring(math.random(100000, 999999))
        project = pm:CreateProject(name)
        if not project then error("プロジェクトを作成できません。Resolveを再起動し、再試行してください") end
        createdProject = true
        project:SetSetting("timelineFrameRate", fps)
        project:SetSetting("timelinePlaybackFrameRate", fps)
        project:SetSetting("timelineResolutionWidth", tostring(DATA.media.width))
        project:SetSetting("timelineResolutionHeight", tostring(DATA.media.height))
    else
        local projectFps = tonumber(project:GetSetting("timelineFrameRate"))
        local projectWidth = tonumber(project:GetSetting("timelineResolutionWidth"))
        local projectHeight = tonumber(project:GetSetting("timelineResolutionHeight"))
        if not projectFps or math.abs(projectFps - tonumber(fps)) > 0.001 or
           projectWidth ~= DATA.media.width or projectHeight ~= DATA.media.height then
            error("開いているプロジェクトの設定が素材と違います。素材に合わせた新規テストプロジェクトを開いてから再実行してください")
        end
    end
    local projectName = project:GetName()
    local pool = project:GetMediaPool()
    local root = pool:GetRootFolder()
    if not pool:SetCurrentFolder(root) then error("メディアプールのMasterを選べません") end
    local knownFolders = {}
    for _, folder in ipairs(root:GetSubFolderList()) do
        knownFolders[folder:GetUniqueId()] = true
    end
    if not pool:ImportFolderFromFile(DATA.template.absolutePath) then
        error("Text+雛形を読み込めません: " .. DATA.template.absolutePath)
    end
    local templateFolder = nil
    for _, folder in ipairs(root:GetSubFolderList()) do
        if not knownFolders[folder:GetUniqueId()] then templateFolder = folder; break end
    end
    local templateClips = templateFolder and templateFolder:GetClipList() or {}
    local titleTemplate = templateClips[1]
    if not titleTemplate or titleTemplate:GetName() ~= "Text+" then
        error("Text+雛形の内容を確認できません")
    end
    pool:SetCurrentFolder(root)
    local imported = pool:ImportMedia({DATA.media.absolutePath})
    if not imported or #imported == 0 then error("同梱動画を読み込めません: " .. DATA.media.absolutePath) end
    local clip = imported[1]
    local cutName = uniqueTimelineName(project, "CUT_TextPlus")
    local cutTimeline = pool:CreateEmptyTimeline(cutName)
    if not cutTimeline then error("CUT_TextPlusタイムラインを作成できません") end
    project:SetCurrentTimeline(cutTimeline)
    local entries = {}
    for _, cut in ipairs(DATA.cuts) do
        table.insert(entries, {mediaPoolItem=clip, startFrame=cut.sourceStartFrame,
            endFrame=cut.sourceEndFrame - 1})
    end
    local edits = pool:AppendToTimeline(entries)
    if not edits or #edits ~= #entries then error("カット映像を配置できません") end

    -- InsertFusionTitleIntoTimeline は配置先を指定できない。Media Pool 雛形を V2 へ明示配置する。
    if not cutTimeline:AddTrack("video") then error("字幕用の映像トラックを追加できません") end

    local added, failed = 0, 0
    local baseFrame = tonumber(cutTimeline:GetStartFrame()) or 0
    for _, cap in ipairs(DATA.captions) do
        local duration = cap.endFrame - cap.startFrame
        local recordFrame = baseFrame + cap.startFrame
        local titles = pool:AppendToTimeline({{mediaPoolItem=titleTemplate, startFrame=0,
            endFrame=duration, trackIndex=2, recordFrame=recordFrame}})
        local title = titles and titles[1]
        if title then
            local comp = title:GetFusionCompByIndex(1)
            local tools = comp and comp:GetToolList(false, "TextPlus") or {}
            local tool = nil
            for _, t in pairs(tools) do tool = t; break end
            -- フォント名だけ変えると既定のSemiboldが残り、存在しない組み合わせになる。
            if tool and title:GetStart() == recordFrame and title:GetDuration() == duration then
                tool:SetInput("StyledText", cap.text)
                tool:SetInput("Font", "Noto Sans JP")
                tool:SetInput("Style", "Medium")
                added = added + 1
            else
                failed = failed + 1
            end
        else
            failed = failed + 1
        end
    end

    local sourceName = uniqueTimelineName(project, "SOURCE_WITH_HANDLES")
    local source = pool:CreateEmptyTimeline(sourceName)
    if source then
        project:SetCurrentTimeline(source)
        local whole = DATA.sourceTimeline
        pool:AppendToTimeline({{mediaPoolItem=clip, startFrame=whole.startFrame,
            endFrame=whole.endFrame - 1}})
        project:SetCurrentTimeline(cutTimeline)
    end
    pm:SaveProject()
    print("cut2resolve Text+: project=" .. projectName .. " createdProject=" .. tostring(createdProject) ..
        " timeline=" .. cutName .. " cuts=" .. #edits ..
        " captions=" .. added .. " failed=" .. failed ..
        (source and " recovery=created" or " recovery=failed"))
    if failed > 0 then print("一部のText+生成に失敗しました。字幕数と位置を確認してください") end
end)
if not ok then fail(err) end
'''.replace("__C2R_DATA__", data)


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


def instructions(video_name):
    return f'''Text+ 用パックの使い方（実験版）
========================

このパックには、同梱動画 media/{video_name}、Text+雛形、通常の EDL・SRT・cut-plan.json と、
Resolve プロジェクトへ個別編集できる Text+ を置くスクリプトが入っています。

1. DaVinci Resolve を終了します。
2. 「ResolveにText+スクリプトを登録.bat」をダブルクリックし、登録完了の表示を確認します。
   この操作は %APPDATA% の Scripts/Edit に専用Luaファイル1個を登録します。
   移動後は再度実行してください。既存プロジェクトは変更しません。
3. Resolve を起動し、Workspace → Scripts → Edit →
   「cut2resolve TextPlus Import Lua」を実行します。
4. プロジェクトを開いている場合はその中に新しいタイムラインを追加します。開いていない場合は新規プロジェクトを作ります。
   CUT_TextPlus が編集用で、映像はV1、Text+字幕は上のV2に置かれます。
   SOURCE_WITH_HANDLES が削除区間を戻すための元素材タイムラインです。
   同じプロジェクトで再実行すると、既存タイムラインを上書きせず末尾に番号を付けて追加します。
   開いているプロジェクトのfps・解像度が素材と違う場合は、変更を加えず停止します。
削除部分を追加したいときは SOURCE_WITH_HANDLES で該当区間を映像・音声まとめてコピーし、
CUT_TextPlus の戻したい位置へ貼り付けてください。追加後は境界と音声同期を確認します。

素材がオフラインになったら、メディアプールで素材を右クリック →
「選択したクリップを再リンク」を選び、このパックの media フォルダを指定します。
パックを別フォルダへ移した後は、もう一度 1〜3 を実行してください。

これはLuaを使う試験方式です。Free 21.1 Windowsでの最終パックの動作確認はまだ必要です。
登録項目が出ない、エラーになる、Text+が作られない場合は画面とエラー文を記録してください。
EDL・SRT・cut-plan.jsonは常に復旧用として残ります。
フォント本体は含みません。Text+ のフォントは相手のPCにも同じものを別途用意してください。
日本語表示のため、生成するText+には「Noto Sans JP / Medium」を指定します。相手のPCにない場合は同じフォントを用意するか、Resolveで別の日本語フォントと対応する太さを選んでください。
音が割れる場合は、まず同じプロジェクトの CUT_TextPlus と SOURCE_WITH_HANDLES の両方で同じ箇所を再生し、結果を比較してください。
'''


def write_files(paths, plan, out_dir):
    """Text+固有ファイルを書き、kind -> Path を返す。"""
    import_plan = build_import_plan(plan, paths["video"].relative_to(out_dir))
    S.write_text_atomic(paths["textplus_plan"], json.dumps(import_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    script = importer_script(build_import_plan(plan, paths["video"].relative_to(out_dir)))
    S.write_text_atomic(paths["textplus_script"], script, encoding="utf-8", newline="\n")
    # Windows PowerShell 5.1はBOMなしUTF-8をANSIとして読むため、日本語文字列内のバイトを引用符扱いすることがある。
    S.write_text_atomic(paths["textplus_install"], installer_script(paths["video"].name), encoding="utf-8-sig", newline="\r\n")
    S.write_text_atomic(paths["textplus_launcher"], launcher_script(), encoding="utf-8-sig", newline="")
    S.write_text_atomic(paths["textplus_readme"], instructions(plan.video.name), encoding="utf-8-sig", newline="\n")
    template_source = Path(__file__).with_name(TEMPLATE_NAME)
    if not S.same_path(template_source, paths["textplus_template"]):
        shutil.copyfile(template_source, paths["textplus_template"])
    return {key: paths[key] for key in ("textplus_plan", "textplus_script", "textplus_install", "textplus_launcher", "textplus_readme", "textplus_template")}
