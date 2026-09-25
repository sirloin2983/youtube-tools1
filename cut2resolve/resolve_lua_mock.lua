-- テスト用: Resolve の API をまねた最小の偽物(test_pack.py から、生成した Lua の前に読み込む)。
-- 実機の代わりではない。位置の計算・止まり方・「プロジェクトを作らない/設定を変えない」を確かめるためのもの。
MOCK = { settings = {}, mediaFps = 60, forbidden = {}, templateOk = true, mediaOk = true, out = {} }
local function forbid(name) return function() table.insert(MOCK.forbidden, name); error("FORBIDDEN " .. name) end end

local function newItem(start, dur, text)
  local tool = { inputs = {} }
  function tool:SetInput(k, v) self.inputs[k] = v end
  local comp = { GetToolList = function(_, _, kind) return { tool } end }
  local it = { start = start, dur = dur, tool = tool }
  function it:GetStart() return self.start end
  function it:GetEnd() return self.start + self.dur end
  function it:GetDuration() return self.dur end
  function it:GetFusionCompByIndex(i) return comp end
  return it
end

local function newTimeline(name)
  local t = { name = name, tracks = { {}, }, markers = {}, nextFrame = 108000 }
  function t:GetName() return self.name end
  function t:GetStartFrame() return 108000 end
  function t:AddTrack(kind) table.insert(self.tracks, {}); return true end
  function t:AddMarker(f, color, name, note, dur) table.insert(self.markers, {f = f, color = color, name = name, note = note}); return true end
  return t
end

local project = { timelines = {}, current = nil }
local root = { subs = {}, clips = {}, id = "root" }
function root:GetSubFolderList() return self.subs end
function root:GetClipList() return self.clips end
function root:GetUniqueId() return self.id end
local pool = {}
function pool:GetRootFolder() return root end
function pool:SetCurrentFolder(f) return true end
function pool:ImportFolderFromFile(p)
  if not MOCK.templateOk then return false end
  local tclip = { GetName = function() return "Text+" end }
  local f = { id = "tpl" .. #root.subs, clips = { tclip } }
  function f:GetUniqueId() return self.id end
  function f:GetClipList() return self.clips end
  table.insert(root.subs, f)
  return true
end
function pool:ImportMedia(list)
  if not MOCK.mediaOk then return {} end
  MOCK.out.mediaPath = list[1]
  return { { GetName = function() return "media" end, isMedia = true } }
end
function pool:CreateEmptyTimeline(name)
  local t = newTimeline(name); table.insert(project.timelines, t); return t
end
function pool:AppendToTimeline(entries)
  local t = project.current
  local res = {}
  for _, e in ipairs(entries) do
    if e.trackIndex then
      local it = newItem(e.recordFrame, e.endFrame - e.startFrame, nil)
      t.tracks[e.trackIndex] = t.tracks[e.trackIndex] or {}
      table.insert(t.tracks[e.trackIndex], it); table.insert(res, it)
    else
      -- 動画のコマ -> タイムラインのコマ(実機の丸め方は不明。ここでは四捨五入)
      local n = e.endFrame - e.startFrame + 1
      local dur = math.floor(n * (tonumber(MOCK.settings.timelineFrameRate) / MOCK.mediaFps) + 0.5)
      local it = newItem(t.nextFrame, dur, nil)
      t.nextFrame = t.nextFrame + dur
      table.insert(t.tracks[1], it); table.insert(res, it)
    end
  end
  return res
end
function project:GetName() return "mock" end
function project:GetMediaPool() return pool end
function project:GetSetting(k) if k == nil then return MOCK.settings end return MOCK.settings[k] end
project.SetSetting = forbid("SetSetting")
project.SetSettings = forbid("SetSettings")
function project:GetTimelineCount() return #self.timelines end
function project:GetTimelineByIndex(i) return self.timelines[i] end
function project:SetCurrentTimeline(t) self.current = t; return true end
local pm = { saved = 0 }
function pm:GetCurrentProject() return project end
function pm:SaveProject() self.saved = self.saved + 1; return true end
pm.CreateProject = forbid("CreateProject")
pm.LoadProject = forbid("LoadProject")
-- フォント一覧(Fusion の FontManager:GetFontList() をまねる)。MOCK.fonts = nil なら Fusion() が nil を返す
MOCK.fonts = nil
resolve = { GetProjectManager = function() return pm end,
            Fusion = function()
              if MOCK.fonts == nil then return nil end
              return { FontManager = { GetFontList = function() return MOCK.fonts end } }
            end }
MOCK.project = project

function MOCK.dump()
  local lines = {}
  local function p(s) table.insert(lines, s) end
  p("forbidden=" .. table.concat(MOCK.forbidden, ","))
  p("media=" .. tostring(MOCK.out.mediaPath))
  for _, t in ipairs(project.timelines) do
    p("timeline=" .. t.name)
    for ti, tr in ipairs(t.tracks) do
      for _, it in ipairs(tr) do
        local i = it.tool.inputs
        p(string.format("item track=%d start=%d dur=%d text=%s font=%s", ti, it.start, it.dur,
          tostring(i.StyledText), tostring(i.Font)))
        if i.StyledText then
          p(string.format("  style=%s fill=%s,%s,%s outline=%s:%s,%s,%s", tostring(i.Style), tostring(i.Red1), tostring(i.Green1),
            tostring(i.Blue1), tostring(i.Enabled2), tostring(i.Red2), tostring(i.Green2), tostring(i.Blue2)))
        end
      end
    end
    for _, m in ipairs(t.markers) do p("marker=" .. m.color .. "|" .. m.name .. "|" .. tostring(m.note)) end
  end
  print(table.concat(lines, "\n"))
end
