// ホロカラーの中身(画面と Windows に依存しない部分)。tests\CoreTests.cs で確かめる。
// C# 5(Windows に最初から入っている csc)で書く: $"" ・ ?. ・ => のメンバー ・ nameof は使えない。
using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace HoloColors
{
    public static class AppInfo
    {
        public const string Name = "ホロカラー";
        public const string Version = "1.1.0";
        public const string ToolId = "holo-colors";
        public const string MembersFile = "members.json";
    }

    public class ColorEntry
    {
        public string Id;
        public string Name;       // 表示名(日本語)
        public string Sub;        // ローマ字・英語名
        public string Hex;        // #RRGGBB
        public string Note;       // 卒業日など
        public ColorGroup Group;
        public bool IsUser;
        public string SearchKey;  // SearchText.SearchKey で作る
    }

    public class ColorGroup
    {
        public string Id;
        public string Branch;     // MY / JP / DEV_IS / EN / ID / GRAD
        public string Name;
        public List<ColorEntry> Items = new List<ColorEntry>();

        public string Label
        {
            get { return Branch == "MY" || Branch == "GRAD" ? Name : Branches.Short(Branch) + "  " + Name; }
        }
    }

    public static class Branches
    {
        // 上の絞り込みの札の順番
        public static readonly string[] Filters = { "ALL", "MY", "JP", "DEV_IS", "EN", "ID", "GRAD" };

        public static string Short(string b)
        {
            switch (b)
            {
                case "ALL": return "すべて";
                case "MY": return "マイカラー";
                case "GRAD": return "卒業";
                default: return b;
            }
        }

        public static bool IsKnown(string b)
        {
            return Array.IndexOf(Filters, b) > 0;
        }
    }

    // ---- 色 ----
    public static class HexColor
    {
        // "#ff6699"・"FF6699"・"#f69"・全角の "＃ＦＦ６６９９" を "#FF6699" にする。読めなければ false
        public static bool TryNormalize(string s, out string hex)
        {
            hex = null;
            if (s == null) return false;
            s = s.Normalize(NormalizationForm.FormKC).Trim();
            if (s.StartsWith("#")) s = s.Substring(1).Trim();
            if (s.Length == 3 && IsHex(s))
                s = new string(new[] { s[0], s[0], s[1], s[1], s[2], s[2] });
            if (s.Length != 6 || !IsHex(s)) return false;
            hex = "#" + s.ToUpperInvariant();
            return true;
        }

        static bool IsHex(string s)
        {
            foreach (char c in s)
                if (!Uri.IsHexDigit(c)) return false;
            return true;
        }

        public static Color ToColor(string hex)
        {
            string h;
            if (!TryNormalize(hex, out h)) return Color.Gray;
            int v = int.Parse(h.Substring(1), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
            return Color.FromArgb((v >> 16) & 255, (v >> 8) & 255, v & 255);
        }

        public static string FromColor(Color c)
        {
            return string.Format(CultureInfo.InvariantCulture, "#{0:X2}{1:X2}{2:X2}", c.R, c.G, c.B);
        }

        // コピーする文字(# を付けるかは設定)
        public static string Format(string hex, bool withHash)
        {
            string h;
            if (!TryNormalize(hex, out h)) return hex;
            return withHash ? h : h.Substring(1);
        }

        // 色の上に載せる文字を黒にするか(false なら白)。YIQ の明るさで決める。
        // WCAG のコントラスト比だと、鮮やかな青やピンク(#266AFF など)で黒が選ばれて読みにくいので、見た目に近いこちらにした
        public static bool PrefersDarkText(Color bg)
        {
            return (bg.R * 299 + bg.G * 587 + bg.B * 114) / 1000 >= 150;
        }
    }

    // ---- 検索 ----
    public static class SearchText
    {
        // 全角/半角・大文字/小文字・カタカナ/ひらがなをそろえ、空白と区切りの記号を除く
        public static string Fold(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = s.Normalize(NormalizationForm.FormKC).ToLowerInvariant();
            var sb = new StringBuilder(s.Length);
            foreach (char c in s)
            {
                if (char.IsWhiteSpace(c) || c == '・' || c == '･' || c == '.' || c == '_' || c == '-') continue;
                if (c >= 'ァ' && c <= 'ヶ') sb.Append((char)(c - 0x60));
                else sb.Append(c);
            }
            return sb.ToString();
        }

        public static string SearchKey(ColorEntry e)
        {
            string g = e.Group == null ? "" : e.Group.Name + "|" + e.Group.Branch;
            return string.Join("|", new[] { Fold(e.Name), Fold(e.Sub), Fold(g), Fold(e.Note), e.Hex == null ? "" : e.Hex.ToLowerInvariant() });
        }

        // 空白で区切った語がすべて含まれていれば当たり
        public static bool Matches(ColorEntry e, string query)
        {
            if (string.IsNullOrWhiteSpace(query)) return true;
            string key = e.SearchKey ?? SearchKey(e);
            foreach (string word in query.Normalize(NormalizationForm.FormKC).Split((char[])null, StringSplitOptions.RemoveEmptyEntries))
            {
                string w = word.StartsWith("#") ? "#" + Fold(word.Substring(1)) : Fold(word);
                if (w.Length == 0) continue;
                if (key.IndexOf(w, StringComparison.Ordinal) < 0) return false;
            }
            return true;
        }
    }

    // ---- 呼び出しのキー ----
    public static class Hotkey
    {
        public const int MOD_ALT = 0x1, MOD_CONTROL = 0x2, MOD_SHIFT = 0x4, MOD_WIN = 0x8;
        public const int DefaultMods = MOD_CONTROL | MOD_ALT;
        public const int DefaultKey = (int)Keys.H;

        public static bool IsModifierKey(int vk)
        {
            Keys k = (Keys)vk;
            return k == Keys.ShiftKey || k == Keys.ControlKey || k == Keys.Menu || k == Keys.LWin || k == Keys.RWin
                || k == Keys.LShiftKey || k == Keys.RShiftKey || k == Keys.LControlKey || k == Keys.RControlKey
                || k == Keys.LMenu || k == Keys.RMenu;
        }

        static bool IsFunctionKey(int vk)
        {
            return vk >= (int)Keys.F1 && vk <= (int)Keys.F24;
        }

        // 使えない理由(null なら使える)。呼び出しのキーはどのアプリより先に取るので、
        // Ctrl・Alt・Win のどれかを必ず付け(F キー単独や Shift + 文字だと、ふつうの操作や入力を奪う)、
        // Windows やアプリでいつも使う組み合わせ(Alt+F4・Ctrl+V など)も断る
        public static string Problem(int mods, int vk)
        {
            if (vk <= 0 || vk > 254 || IsModifierKey(vk) || (mods & ~(MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_WIN)) != 0)
                return "この組み合わせは使えません";
            if ((mods & (MOD_CONTROL | MOD_ALT | MOD_WIN)) == 0)
                return "Ctrl・Alt・Win のどれかと一緒に押してください";
            Keys k = (Keys)vk;
            bool ctrlOnly = mods == MOD_CONTROL, altOnly = mods == MOD_ALT;
            if (altOnly && (k == Keys.F4 || k == Keys.Tab || k == Keys.Space || k == Keys.Escape || k == Keys.Return))
                return "「" + Format(mods, vk) + "」は Windows が使う組み合わせです(窓を閉じる・切り替えるなど)";
            if ((mods & MOD_CONTROL) != 0 && k == Keys.Escape)
                return "「" + Format(mods, vk) + "」は Windows が使う組み合わせです(スタート・タスク マネージャー)";
            if (mods == (MOD_CONTROL | MOD_ALT) && k == Keys.Delete)
                return "「" + Format(mods, vk) + "」は Windows が使う組み合わせです";
            if (ctrlOnly && (k == Keys.A || k == Keys.C || k == Keys.V || k == Keys.X || k == Keys.Z || k == Keys.Y || k == Keys.S
                || k == Keys.F || k == Keys.P || k == Keys.N || k == Keys.O || k == Keys.W || k == Keys.T || k == Keys.Tab || k == Keys.F4))
                return "「" + Format(mods, vk) + "」はほかのアプリでいつも使う組み合わせ(コピー・貼り付け・保存など)です";
            return null;
        }

        public static bool IsValid(int mods, int vk)
        {
            return Problem(mods, vk) == null;
        }

        public static string KeyName(int vk)
        {
            Keys k = (Keys)vk;
            if (k >= Keys.A && k <= Keys.Z) return ((char)vk).ToString();
            if (k >= Keys.D0 && k <= Keys.D9) return ((char)vk).ToString();
            if (k >= Keys.NumPad0 && k <= Keys.NumPad9) return "テンキー" + (vk - (int)Keys.NumPad0);
            if (IsFunctionKey(vk)) return "F" + (vk - (int)Keys.F1 + 1);
            switch (k)
            {
                case Keys.Space: return "Space";
                case Keys.Return: return "Enter";
                case Keys.Tab: return "Tab";
                case Keys.Insert: return "Insert";
                case Keys.Delete: return "Delete";
                case Keys.Home: return "Home";
                case Keys.End: return "End";
                case Keys.PageUp: return "PageUp";
                case Keys.PageDown: return "PageDown";
                case Keys.Up: return "↑";
                case Keys.Down: return "↓";
                case Keys.Left: return "←";
                case Keys.Right: return "→";
                case Keys.Pause: return "Pause";
                case Keys.Oemcomma: return ",";
                case Keys.OemPeriod: return ".";
                case Keys.OemMinus: return "-";
                case Keys.Oemplus: return ";";
                case Keys.OemQuestion: return "/";
                case Keys.Oem1: return ":";
                case Keys.Oem3: return "@";
                case Keys.Oem4: return "[";
                case Keys.Oem5: return "\\";
                case Keys.Oem6: return "]";
                case Keys.Oem7: return "^";
                case Keys.Oem102: return "\\";
            }
            return k.ToString();
        }

        public static string Format(int mods, int vk)
        {
            var parts = new List<string>();
            if ((mods & MOD_CONTROL) != 0) parts.Add("Ctrl");
            if ((mods & MOD_ALT) != 0) parts.Add("Alt");
            if ((mods & MOD_SHIFT) != 0) parts.Add("Shift");
            if ((mods & MOD_WIN) != 0) parts.Add("Win");
            if (vk > 0 && !IsModifierKey(vk)) parts.Add(KeyName(vk));
            return string.Join(" + ", parts);
        }
    }

    // ---- JSON(JavaScriptSerializer の Dictionary を安全に読む) ----
    public static class Json
    {
        public static JavaScriptSerializer Serializer()
        {
            var s = new JavaScriptSerializer();
            s.MaxJsonLength = 16 * 1024 * 1024;
            return s;
        }

        public static IDictionary<string, object> Parse(string text)
        {
            var o = Serializer().DeserializeObject(text) as IDictionary<string, object>;
            if (o == null) throw new FormatException("JSON の一番外側が { } ではありません");
            return o;
        }

        public static string Str(IDictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) && v is string ? (string)v : null;
        }

        public static bool Bool(IDictionary<string, object> d, string key, bool dflt)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) && v is bool ? (bool)v : dflt;
        }

        public static int Int(IDictionary<string, object> d, string key, int dflt)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v == null) return dflt;
            if (v is int) return (int)v;
            if (v is long) return (long)v > int.MaxValue || (long)v < int.MinValue ? dflt : (int)(long)v;
            if (v is decimal) return (int)Math.Round((decimal)v);
            return dflt;
        }

        public static IEnumerable<IDictionary<string, object>> List(IDictionary<string, object> d, string key)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v)) yield break;
            var list = v as IEnumerable;
            if (list == null || v is string) yield break;
            foreach (object o in list)
            {
                var item = o as IDictionary<string, object>;
                if (item != null) yield return item;
            }
        }

        // 人が開いても読めるように字下げする(JavaScriptSerializer は1行で書くため)
        public static string Pretty(object value)
        {
            string s = Serializer().Serialize(value);
            var sb = new StringBuilder();
            int depth = 0;
            bool inStr = false;
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                if (inStr)
                {
                    sb.Append(c);
                    if (c == '\\' && i + 1 < s.Length) sb.Append(s[++i]);
                    else if (c == '"') inStr = false;
                    continue;
                }
                switch (c)
                {
                    case '"': inStr = true; sb.Append(c); break;
                    case '{':
                    case '[':
                        sb.Append(c);
                        if (i + 1 < s.Length && (s[i + 1] == '}' || s[i + 1] == ']')) { sb.Append(s[++i]); break; }
                        depth++; NewLine(sb, depth); break;
                    case '}':
                    case ']': depth--; NewLine(sb, depth); sb.Append(c); break;
                    case ',': sb.Append(c); NewLine(sb, depth); break;
                    case ':': sb.Append(": "); break;
                    default: sb.Append(c); break;
                }
            }
            return sb.Append('\n').ToString();
        }

        static void NewLine(StringBuilder sb, int depth)
        {
            sb.Append('\n').Append(' ', depth * 2);
        }
    }

    // ---- ファイル ----
    public static class Files
    {
        // 一時ファイルに書いてから置き換える(書きかけのファイルを残さない)
        public static void WriteAtomic(string path, string text)
        {
            string dir = Path.GetDirectoryName(Path.GetFullPath(path));
            Directory.CreateDirectory(dir);
            string tmp = Path.Combine(dir, "." + Path.GetFileName(path) + "." + Guid.NewGuid().ToString("N").Substring(0, 8) + ".part");
            try
            {
                File.WriteAllText(tmp, text, new UTF8Encoding(false));
                for (int attempt = 0; ; attempt++)
                {
                    try
                    {
                        if (File.Exists(path)) File.Replace(tmp, path, null, true);
                        else File.Move(tmp, path);
                        return;
                    }
                    catch (IOException)
                    {
                        // ウイルス対策・同期ソフトが一瞬つかんでいるときだけ、少し待ってやり直す
                        if (attempt >= 3) throw;
                        System.Threading.Thread.Sleep(100 << attempt);
                    }
                    catch (UnauthorizedAccessException)
                    {
                        if (attempt >= 3) throw;
                        System.Threading.Thread.Sleep(100 << attempt);
                    }
                }
            }
            finally
            {
                try { if (File.Exists(tmp)) File.Delete(tmp); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            }
        }

        // 読めない JSON は消さずに名前を変えて取っておく(手で直せるように)。戻り値は取っておいた先
        public static string SetAside(string path)
        {
            string dst = path + ".corrupt-" + DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
            try { File.Move(path, dst); return dst; }
            catch (IOException) { return null; }
            catch (UnauthorizedAccessException) { return null; }
        }

        // 作業データの置き場所(youtube-tools の約束 = ytt_core/datadir.py と同じ)
        //   既定 … %LOCALAPPDATA%\youtube-tools\holo-colors
        //   YTT_DATA_DIR があれば <YTT_DATA_DIR>\holo-colors、inplace なら exe のフォルダの data
        public static string DataDir(string exeDir, string ytDataDir, string localAppData)
        {
            string d = (ytDataDir ?? "").Trim();
            if (d.Length > 0)
                return d.Equals("inplace", StringComparison.OrdinalIgnoreCase)
                    ? Path.Combine(exeDir, "data")
                    : Path.Combine(Path.GetFullPath(d), AppInfo.ToolId);
            if (string.IsNullOrEmpty(localAppData))
                localAppData = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "Local");
            return Path.Combine(localAppData, "youtube-tools", AppInfo.ToolId);
        }
    }

    // ---- メンバーの色(exe の横の members.json。読むだけ) ----
    public class Palette
    {
        public List<ColorGroup> Groups = new List<ColorGroup>();
        public string Updated = "";

        public static Palette Load(string path)
        {
            var p = new Palette();
            var root = Json.Parse(File.ReadAllText(path, Encoding.UTF8));
            p.Updated = Json.Str(root, "updated") ?? "";
            var ids = new HashSet<string>();
            foreach (var g in Json.List(root, "groups"))
            {
                var group = new ColorGroup
                {
                    Id = Json.Str(g, "id") ?? ("group" + p.Groups.Count),
                    Branch = Json.Str(g, "branch") ?? "JP",
                    Name = Json.Str(g, "name") ?? "",
                };
                if (!Branches.IsKnown(group.Branch) || group.Branch == "MY")
                    throw new FormatException("知らない branch です: " + group.Branch);
                foreach (var m in Json.List(g, "members"))
                {
                    string hex;
                    string name = Json.Str(m, "name");
                    if (string.IsNullOrWhiteSpace(name) || !HexColor.TryNormalize(Json.Str(m, "hex"), out hex))
                        throw new FormatException("名前かカラーコードが読めません: " + (name ?? "(名前なし)") + " / " + Json.Str(m, "hex"));
                    var e = new ColorEntry
                    {
                        Id = group.Id + "/" + (Json.Str(m, "id") ?? name),
                        Name = name.Trim(),
                        Sub = Json.Str(m, "en") ?? "",
                        Hex = hex,
                        Note = Json.Str(m, "note") ?? "",
                        Group = group,
                    };
                    if (!ids.Add(e.Id)) throw new FormatException("id が重なっています: " + e.Id);
                    e.SearchKey = SearchText.SearchKey(e);
                    group.Items.Add(e);
                }
                p.Groups.Add(group);
            }
            return p;
        }
    }

    // ---- 設定(settings.json) ----
    public class Settings
    {
        public int HotkeyMods = Hotkey.DefaultMods;
        public int HotkeyKey = Hotkey.DefaultKey;
        public bool CloseAfterCopy = true;
        public bool IncludeHash = true;
        public int WindowWidth;    // 0 = 既定の大きさ
        public int WindowHeight;
        public string Filter = "ALL";
        public bool Welcomed;      // 初めての起動の案内を出したか
        public bool AlwaysOnTop;   // 一覧をいつも一番手前に(既定は外す。キーで呼んだときは外していても前に出る)

        public IDictionary<string, object> ToJson()
        {
            return new Dictionary<string, object>
            {
                { "version", 1 },
                { "hotkeyModifiers", HotkeyMods },
                { "hotkeyKey", HotkeyKey },
                { "closeAfterCopy", CloseAfterCopy },
                { "includeHash", IncludeHash },
                { "windowWidth", WindowWidth },
                { "windowHeight", WindowHeight },
                { "filter", Filter },
                { "welcomed", Welcomed },
                { "alwaysOnTop", AlwaysOnTop },
            };
        }

        public static Settings FromJson(IDictionary<string, object> d)
        {
            var s = new Settings();
            s.HotkeyMods = Json.Int(d, "hotkeyModifiers", s.HotkeyMods);
            s.HotkeyKey = Json.Int(d, "hotkeyKey", s.HotkeyKey);
            if (!Hotkey.IsValid(s.HotkeyMods, s.HotkeyKey)) { s.HotkeyMods = Hotkey.DefaultMods; s.HotkeyKey = Hotkey.DefaultKey; }
            s.CloseAfterCopy = Json.Bool(d, "closeAfterCopy", s.CloseAfterCopy);
            s.IncludeHash = Json.Bool(d, "includeHash", s.IncludeHash);
            s.WindowWidth = Math.Max(0, Math.Min(8000, Json.Int(d, "windowWidth", 0)));
            s.WindowHeight = Math.Max(0, Math.Min(8000, Json.Int(d, "windowHeight", 0)));
            string f = Json.Str(d, "filter");
            s.Filter = f != null && Array.IndexOf(Branches.Filters, f) >= 0 ? f : "ALL";
            s.Welcomed = Json.Bool(d, "welcomed", false);
            s.AlwaysOnTop = Json.Bool(d, "alwaysOnTop", false);
            return s;
        }
    }

    // ---- 作業データ(設定と、自分で足した色) ----
    public class Store
    {
        public const int MaxName = 40;
        public readonly string Dir;
        public Settings Settings = new Settings();
        public readonly ColorGroup Mine = new ColorGroup { Id = "my", Branch = "MY", Name = "マイカラー" };
        public readonly List<string> Warnings = new List<string>();
        // 読めなかった(ほかのソフトがつかんでいた・権限が無い)ファイルは、上書きして消さないように保存を止める
        bool settingsLocked, colorsLocked;

        public Store(string dir)
        {
            Dir = dir;
        }

        public string SettingsPath { get { return Path.Combine(Dir, "settings.json"); } }
        public string ColorsPath { get { return Path.Combine(Dir, "my-colors.json"); } }

        public void Load()
        {
            Settings = new Settings();
            Mine.Items.Clear();
            var s = ReadJson(SettingsPath, out settingsLocked);
            if (s != null) Settings = Settings.FromJson(s);
            var c = ReadJson(ColorsPath, out colorsLocked);
            foreach (var m in Json.List(c, "colors"))
            {
                string hex, name = (Json.Str(m, "name") ?? "").Trim();
                if (name.Length == 0 || !HexColor.TryNormalize(Json.Str(m, "hex"), out hex)) continue;
                string id = Json.Str(m, "id");
                if (string.IsNullOrEmpty(id) || Mine.Items.Any(x => x.Id == id)) id = NewId();
                Mine.Items.Add(MakeEntry(id, name, hex));
            }
        }

        // 読めないときは null。locked = ファイルはあるが開けなかった・取っておけなかった(このときは保存しない)
        IDictionary<string, object> ReadJson(string path, out bool locked)
        {
            locked = false;
            if (!File.Exists(path)) return null;
            string text = null;
            for (int attempt = 0; ; attempt++)
            {
                try
                {
                    text = File.ReadAllText(path, Encoding.UTF8);
                    break;
                }
                catch (Exception ex)
                {
                    if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                    // ウイルス対策・同期ソフトが一瞬つかんでいることがあるので、少し待って読み直す
                    if (attempt < 3) { System.Threading.Thread.Sleep(150 << attempt); continue; }
                    locked = true;
                    Warnings.Add(Path.GetFileName(path) + " を開けませんでした(" + ex.Message + ")。消さないように、このファイルへの保存を止めています。アプリを起動し直してください");
                    return null;
                }
            }
            try
            {
                return Json.Parse(text);
            }
            catch (Exception ex)
            {
                if (!(ex is ArgumentException || ex is FormatException || ex is InvalidOperationException)) throw;
                string aside = Files.SetAside(path);
                if (aside == null)
                {
                    locked = true;
                    Warnings.Add(Path.GetFileName(path) + " が壊れていて、取っておくこともできませんでした。消さないように、このファイルへの保存を止めています");
                    return null;
                }
                Warnings.Add(Path.GetFileName(path) + " が読めなかったので、初めの状態で始めました(元のファイルは " + Path.GetFileName(aside) + " に残しました)");
                return null;
            }
        }

        public void SaveSettings()
        {
            if (settingsLocked) throw new IOException("settings.json が開けなかったので、上書きしないように保存を止めています");
            Files.WriteAtomic(SettingsPath, Json.Pretty(Settings.ToJson()));
        }

        public void SaveColors()
        {
            if (colorsLocked) throw new IOException("my-colors.json が開けなかったので、上書きしないように保存を止めています");
            var list = Mine.Items.Select(e => (object)new Dictionary<string, object> { { "id", e.Id }, { "name", e.Name }, { "hex", e.Hex } }).ToList();
            Files.WriteAtomic(ColorsPath, Json.Pretty(new Dictionary<string, object> { { "version", 1 }, { "colors", list } }));
        }

        static string NewId()
        {
            return "my/" + Guid.NewGuid().ToString("N").Substring(0, 12);
        }

        ColorEntry MakeEntry(string id, string name, string hex)
        {
            var e = new ColorEntry { Id = id, Name = name, Sub = "", Hex = hex, Note = "", Group = Mine, IsUser = true };
            e.SearchKey = SearchText.SearchKey(e);
            return e;
        }

        // 名前とカラーコードを確かめる。問題があれば理由を返す(null なら良い)
        public static string Validate(string name, string hexText, out string hex)
        {
            hex = null;
            name = (name ?? "").Trim();
            if (name.Length == 0) return "名前を入れてください";
            if (name.Length > MaxName) return "名前は " + MaxName + " 文字までです";
            if (!HexColor.TryNormalize(hexText, out hex)) return "カラーコードは #FF6699 のような 6 桁の 16 進数で入れてください";
            return null;
        }

        public ColorEntry Add(string name, string hexText)
        {
            string hex;
            string err = Validate(name, hexText, out hex);
            if (err != null) throw new ArgumentException(err);
            var e = MakeEntry(NewId(), name.Trim(), hex);
            Mine.Items.Add(e);
            try { SaveColors(); }
            catch { Mine.Items.Remove(e); throw; }   // 保存できなければ、画面にも残さない
            return e;
        }

        public void Update(ColorEntry e, string name, string hexText)
        {
            string hex;
            string err = Validate(name, hexText, out hex);
            if (err != null) throw new ArgumentException(err);
            string oldName = e.Name, oldHex = e.Hex;
            e.Name = name.Trim();
            e.Hex = hex;
            e.SearchKey = SearchText.SearchKey(e);
            try { SaveColors(); }
            catch
            {
                e.Name = oldName;
                e.Hex = oldHex;
                e.SearchKey = SearchText.SearchKey(e);
                throw;
            }
        }

        public void Remove(ColorEntry e)
        {
            int i = Mine.Items.IndexOf(e);
            if (i < 0) return;
            Mine.Items.RemoveAt(i);
            try { SaveColors(); }
            catch { Mine.Items.Insert(i, e); throw; }
        }

        public bool Move(ColorEntry e, int delta)
        {
            int i = Mine.Items.IndexOf(e), j = i + delta;
            if (i < 0 || j < 0 || j >= Mine.Items.Count) return false;
            Mine.Items.RemoveAt(i);
            Mine.Items.Insert(j, e);
            try { SaveColors(); }
            catch
            {
                Mine.Items.RemoveAt(j);
                Mine.Items.Insert(i, e);
                throw;
            }
            return true;
        }
    }
}
