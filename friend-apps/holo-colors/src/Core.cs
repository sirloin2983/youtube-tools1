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
        public const string Version = "1.4.1";
        public const string ToolId = "holo-colors";
        public const string MembersFile = "members.json";
    }

    // 1人の色の1つ(members.json の colors の1項目)。Label は画面に出す短い名前(空でもよい)
    public class ColorOption
    {
        public const int MaxLabel = 12;
        public string Hex;
        public string Label;

        public ColorOption(string hex, string label)
        {
            Hex = hex;
            Label = label ?? "";
        }

        public ColorOption Clone()
        {
            return new ColorOption(Hex, Label);
        }

        // 画面の表示「#RRGGBB(ラベル)」
        public string Text
        {
            get { return Label.Length > 0 ? Hex + "(" + Label + ")" : Hex; }
        }

        public static List<ColorOption> CloneAll(IEnumerable<ColorOption> list)
        {
            return list.Select(c => c.Clone()).ToList();
        }

        // 色の並びを確かめてそろえる(カラーコードの形・ラベルの長さ・同じ色の重なりは1つに)。問題があれば理由を返す(null なら良い)
        public static string Validate(IEnumerable<ColorOption> input, out List<ColorOption> result)
        {
            result = new List<ColorOption>();
            foreach (var c in input ?? new ColorOption[0])
            {
                if (c == null) continue;
                string hex;
                if (!HexColor.TryNormalize(c.Hex, out hex)) return "カラーコードは #FF6699 のような 6 桁の 16 進数で入れてください: " + c.Hex;
                string label = (c.Label ?? "").Trim();
                if (label.Length > MaxLabel) return "ラベルは " + MaxLabel + " 文字までです: " + label;
                if (result.Any(x => x.Hex == hex)) continue;
                result.Add(new ColorOption(hex, label));
            }
            if (result.Count == 0) return "色を1つ以上入れてください";
            return null;
        }
    }

    public class ColorEntry
    {
        public string Id;
        public string MemberId;   // members.json のメンバーの id(全体で一意。直した色のキー)。マイカラーは null
        public string Name;       // 表示名(日本語)
        public string Sub;        // ローマ字・英語名
        public string Hex;        // #RRGGBB。主な色 = Colors[0].Hex。マイワードは null
        public string Text;       // マイワードの本文(改行は "\n")。色の項目は null
        public string Note;       // 卒業日など
        public ColorGroup Group;
        public bool IsUser;
        public string SearchKey;  // SearchText.SearchKey で作る
        public List<ColorOption> Colors = new List<ColorOption>();   // 先頭が主な色。空なら Hex の1色(AllColors)
        public List<ColorOption> OriginalColors;                     // members.json のままの色(直した色を戻すとき)。マイカラーは null
        public bool Customized;   // 作業データの member-colors.json で直した色を使っている

        public bool IsWord { get { return Text != null; } }

        // 色を入れ替える(Hex は先頭の色)
        public void SetColors(List<ColorOption> colors)
        {
            Colors = ColorOption.CloneAll(colors);
            if (Colors.Count > 0) Hex = Colors[0].Hex;
            SearchKey = SearchText.SearchKey(this);
        }

        // 色の一覧(Colors が空の作り方でも Hex の1色)
        public List<ColorOption> AllColors
        {
            get
            {
                if (IsWord || (Hex == null && (Colors == null || Colors.Count == 0))) return new List<ColorOption>();
                return Colors != null && Colors.Count > 0 ? Colors : new List<ColorOption> { new ColorOption(Hex, "") };
            }
        }
    }

    public class ColorGroup
    {
        public string Id;
        public string Branch;     // MY / WORD / JP / DEV_IS / EN / ID / GRAD(FAV / RECENT は画面が作る一覧)
        public string Name;
        public List<ColorEntry> Items = new List<ColorEntry>();

        public string Label
        {
            get { return Branches.IsSpecial(Branch) || Branch == "GRAD" ? Name : Branches.Short(Branch) + "  " + Name; }
        }
    }

    public static class Branches
    {
        // 上の絞り込みの札の順番
        public static readonly string[] Filters = { "ALL", "MY", "WORD", "JP", "DEV_IS", "EN", "ID", "GRAD" };

        public static string Short(string b)
        {
            switch (b)
            {
                case "ALL": return "すべて";
                case "MY": return "マイカラー";
                case "WORD": return "マイワード";
                case "FAV": return "お気に入り";
                case "RECENT": return "最近使ったもの";
                case "GRAD": return "卒業";
                default: return b;
            }
        }

        // 一覧の絞り込みではなく、自分の側で持つ・画面が作る一覧(members.json には書けない)
        public static bool IsSpecial(string b)
        {
            return b == "MY" || b == "WORD" || b == "FAV" || b == "RECENT";
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
            var parts = new List<string> { Fold(e.Name), Fold(e.Sub), Fold(g), Fold(e.Note), e.Hex == null ? "" : e.Hex.ToLowerInvariant() };
            if (e.Text != null) parts.Add(Fold(e.Text));   // マイワードは本文でも当たる
            // 2つ目以降の色のカラーコードとラベルでも当たる
            if (e.Colors != null)
                foreach (var c in e.Colors)
                {
                    if (c.Hex != null && c.Hex != e.Hex) parts.Add(c.Hex.ToLowerInvariant());
                    if (!string.IsNullOrEmpty(c.Label)) parts.Add(Fold(c.Label));
                }
            return string.Join("|", parts);
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

        public static IDictionary<string, object> Dict(IDictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) ? v as IDictionary<string, object> : null;
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

        // 作業データの置き場所(youtube-tools の約束 = src/ytt_core/datadir.py と同じ)
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
                if (!Branches.IsKnown(group.Branch) || Branches.IsSpecial(group.Branch))
                    throw new FormatException("知らない branch です: " + group.Branch);
                foreach (var m in Json.List(g, "members"))
                {
                    string hex;
                    string name = Json.Str(m, "name");
                    if (string.IsNullOrWhiteSpace(name) || !HexColor.TryNormalize(Json.Str(m, "hex"), out hex))
                        throw new FormatException("名前かカラーコードが読めません: " + (name ?? "(名前なし)") + " / " + Json.Str(m, "hex"));
                    string memberId = Json.Str(m, "id") ?? name;
                    var e = new ColorEntry
                    {
                        Id = group.Id + "/" + memberId,
                        MemberId = memberId,
                        Name = name.Trim(),
                        Sub = Json.Str(m, "en") ?? "",
                        Hex = hex,
                        Note = Json.Str(m, "note") ?? "",
                        Group = group,
                    };
                    if (!ids.Add(e.Id)) throw new FormatException("id が重なっています: " + e.Id);
                    e.Colors = ReadColors(m, hex);
                    e.OriginalColors = ColorOption.CloneAll(e.Colors);
                    e.SearchKey = SearchText.SearchKey(e);
                    group.Items.Add(e);
                }
                p.Groups.Add(group);
            }
            return p;
        }

        // members.json の colors(version 2)。主な色は hex(1.2.1 までの exe と字幕の色も hex を使う)なので、必ず先頭に置く。
        // 壊れた項目(カラーコードが読めない)は飛ばす。colors が無い古い形は hex の1色
        public static List<ColorOption> ReadColors(IDictionary<string, object> m, string mainHex)
        {
            var list = new List<ColorOption>();
            foreach (var c in Json.List(m, "colors"))
            {
                string h;
                if (!HexColor.TryNormalize(Json.Str(c, "hex"), out h) || list.Any(x => x.Hex == h)) continue;
                string label = (Json.Str(c, "label") ?? "").Trim();
                if (label.Length > ColorOption.MaxLabel) label = label.Substring(0, ColorOption.MaxLabel);
                list.Add(new ColorOption(h, label));
            }
            int i = list.FindIndex(x => x.Hex == mainHex);
            if (i > 0)
            {
                var main = list[i];
                list.RemoveAt(i);
                list.Insert(0, main);
            }
            else if (i < 0) list.Insert(0, new ColorOption(mainHex, ""));
            return list;
        }

        public IEnumerable<ColorEntry> Members
        {
            get { return Groups.SelectMany(g => g.Items); }
        }
    }

    // 最近使ったもの1件(項目の id と、コピーした色の番号)
    public class RecentItem
    {
        public string Id;
        public int ColorIndex;
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
        public const int MaxFavorites = 300, MaxRecent = 5, MaxColorIndex = 20;
        public List<string> Favorites = new List<string>();      // お気に入りの項目の id(足した順)
        public List<RecentItem> Recent = new List<RecentItem>(); // 最近使ったもの(新しい順)

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
                { "favorites", Favorites.Cast<object>().ToList() },
                { "recent", Recent.Select(r => (object)new Dictionary<string, object> { { "id", r.Id }, { "color", r.ColorIndex } }).ToList() },
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
            object fv;
            if (d != null && d.TryGetValue("favorites", out fv) && fv is IEnumerable && !(fv is string) && !(fv is IDictionary<string, object>))
                foreach (object o in (IEnumerable)fv)
                {
                    string id = o as string;
                    if (string.IsNullOrEmpty(id) || s.Favorites.Contains(id)) continue;
                    if (s.Favorites.Count >= MaxFavorites) break;
                    s.Favorites.Add(id);
                }
            foreach (var r in Json.List(d, "recent"))
            {
                string id = Json.Str(r, "id");
                if (string.IsNullOrEmpty(id) || s.Recent.Any(x => x.Id == id)) continue;
                if (s.Recent.Count >= MaxRecent) break;
                s.Recent.Add(new RecentItem { Id = id, ColorIndex = Math.Max(0, Math.Min(MaxColorIndex, Json.Int(r, "color", 0))) });
            }
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
        // メンバーの色を直したもの(member-colors.json)。キーはメンバーの id(グループを入れない。卒業でグループが変わっても残る)。
        // members.json に無い id も消さずに持っておく(使わない。members.json を戻したときのため)
        public readonly Dictionary<string, List<ColorOption>> MemberColors = new Dictionary<string, List<ColorOption>>();
        // 読めなかった(ほかのソフトがつかんでいた・権限が無い)ファイルは、上書きして消さないように保存を止める
        bool settingsLocked, colorsLocked, memberColorsLocked, wordsLocked;
        public const int MaxWordText = 4000;
        public readonly ColorGroup Words = new ColorGroup { Id = "word", Branch = "WORD", Name = "マイワード" };

        public Store(string dir)
        {
            Dir = dir;
        }

        public string SettingsPath { get { return Path.Combine(Dir, "settings.json"); } }
        public string ColorsPath { get { return Path.Combine(Dir, "my-colors.json"); } }
        public string WordsPath { get { return Path.Combine(Dir, "my-words.json"); } }
        public string MemberColorsPath { get { return Path.Combine(Dir, "member-colors.json"); } }

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
            Words.Items.Clear();
            var w = ReadJson(WordsPath, out wordsLocked);
            foreach (var m in Json.List(w, "words"))
            {
                string text = (Json.Str(m, "text") ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
                if (text.Trim().Length == 0) continue;
                string name = (Json.Str(m, "name") ?? "").Trim();
                if (name.Length == 0) name = DefaultWordName(text);
                if (name.Length > MaxName) name = name.Substring(0, MaxName);
                string id = Json.Str(m, "id");
                if (string.IsNullOrEmpty(id) || Words.Items.Any(x => x.Id == id)) id = NewWordId();
                Words.Items.Add(MakeWord(id, name, text));
            }
            MemberColors.Clear();
            var mc = Json.Dict(ReadJson(MemberColorsPath, out memberColorsLocked), "members");
            if (mc != null)
                foreach (var kv in mc)
                {
                    // 形の違う項目は飛ばす(色の読めない1つだけなら、その色を捨てて残りを使う)
                    var list = new List<ColorOption>();
                    foreach (var o in Json.List(kv.Value as IDictionary<string, object>, "colors"))
                    {
                        string h;
                        if (HexColor.TryNormalize(Json.Str(o, "hex"), out h)) list.Add(new ColorOption(h, Json.Str(o, "label") ?? ""));
                    }
                    List<ColorOption> ok;
                    var cleaned = list.Select(x => new ColorOption(x.Hex, x.Label.Trim().Length > ColorOption.MaxLabel ? x.Label.Trim().Substring(0, ColorOption.MaxLabel) : x.Label)).ToList();
                    if (kv.Key.Length > 0 && ColorOption.Validate(cleaned, out ok) == null) MemberColors[kv.Key] = ok;
                }
        }

        // 直した色を一覧のメンバーに反映する(members.json を読んだあと・直したあと)。直していない人は members.json の色
        public void ApplyMemberColors(IEnumerable<ColorEntry> members)
        {
            foreach (var e in members)
            {
                if (e.IsUser || e.MemberId == null || e.OriginalColors == null) continue;
                List<ColorOption> fixedColors;
                if (MemberColors.TryGetValue(e.MemberId, out fixedColors))
                {
                    e.SetColors(fixedColors);
                    e.Customized = true;
                }
                else
                {
                    e.SetColors(e.OriginalColors);
                    e.Customized = false;
                }
            }
        }

        // メンバーの色を直す(先頭が主な色)。members.json の色と同じなら「元に戻す」と同じ。保存できなければ元に戻して投げる
        public void SetMemberColors(ColorEntry e, IEnumerable<ColorOption> colors)
        {
            if (e == null || e.IsUser || string.IsNullOrEmpty(e.MemberId) || e.OriginalColors == null)
                throw new ArgumentException("メンバーの色だけ直せます");
            List<ColorOption> ok;
            string err = ColorOption.Validate(colors, out ok);
            if (err != null) throw new ArgumentException(err);
            if (SameColors(ok, e.OriginalColors)) { ResetMemberColors(e); return; }
            List<ColorOption> before;
            bool had = MemberColors.TryGetValue(e.MemberId, out before);
            MemberColors[e.MemberId] = ok;
            try { SaveMemberColors(); }
            catch
            {
                if (had) MemberColors[e.MemberId] = before; else MemberColors.Remove(e.MemberId);
                throw;
            }
            ApplyMemberColors(new[] { e });
        }

        public void ResetMemberColors(ColorEntry e)
        {
            if (e == null || string.IsNullOrEmpty(e.MemberId)) return;
            List<ColorOption> before;
            if (MemberColors.TryGetValue(e.MemberId, out before))
            {
                MemberColors.Remove(e.MemberId);
                try { SaveMemberColors(); }
                catch
                {
                    MemberColors[e.MemberId] = before;
                    throw;
                }
            }
            ApplyMemberColors(new[] { e });
        }

        public static bool SameColors(IList<ColorOption> a, IList<ColorOption> b)
        {
            if (a == null || b == null || a.Count != b.Count) return false;
            for (int i = 0; i < a.Count; i++)
                if (a[i].Hex != b[i].Hex || (a[i].Label ?? "") != (b[i].Label ?? "")) return false;
            return true;
        }

        public void SaveMemberColors()
        {
            if (memberColorsLocked) throw new IOException("member-colors.json が開けなかったので、上書きしないように保存を止めています");
            var members = new Dictionary<string, object>();
            foreach (var kv in MemberColors)
                members[kv.Key] = new Dictionary<string, object>
                {
                    { "colors", kv.Value.Select(x => (object)new Dictionary<string, object> { { "hex", x.Hex }, { "label", x.Label } }).ToList() },
                };
            Files.WriteAtomic(MemberColorsPath, Json.Pretty(new Dictionary<string, object> { { "version", 1 }, { "members", members } }));
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

        public void SaveWords()
        {
            if (wordsLocked) throw new IOException("my-words.json が開けなかったので、上書きしないように保存を止めています");
            var list = Words.Items.Select(e => (object)new Dictionary<string, object> { { "id", e.Id }, { "name", e.Name }, { "text", e.Text } }).ToList();
            Files.WriteAtomic(WordsPath, Json.Pretty(new Dictionary<string, object> { { "version", 1 }, { "words", list } }));
        }

        static string NewWordId()
        {
            return "word/" + Guid.NewGuid().ToString("N").Substring(0, 12);
        }

        static string DefaultWordName(string text)
        {
            foreach (string line in text.Replace("\r\n", "\n").Replace("\r", "\n").Split('\n'))
            {
                string t = line.Trim();
                if (t.Length > 0) return t.Length > MaxName ? t.Substring(0, MaxName) : t;
            }
            return "";
        }

        ColorEntry MakeWord(string id, string name, string text)
        {
            var e = new ColorEntry { Id = id, Name = name, Sub = "", Hex = null, Note = "", Text = text, Group = Words, IsUser = true };
            e.SearchKey = SearchText.SearchKey(e);
            return e;
        }

        // マイワードの名前と本文を確かめる。問題があれば理由を返す(null なら良い)。名前が空なら本文の最初の行
        public static string ValidateWord(string name, string text, out string cleanName)
        {
            cleanName = null;
            string t = (text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
            if (t.Trim().Length == 0) return "本文を入れてください";
            if (t.Length > MaxWordText) return "本文は " + MaxWordText + " 文字までです(いまは " + t.Length + " 文字)";
            name = (name ?? "").Trim();
            if (name.Length > MaxName) return "名前は " + MaxName + " 文字までです";
            if (name.Length == 0) name = DefaultWordName(t);
            cleanName = name;
            return null;
        }

        // クリップボードに入れる形(Windows の改行)
        public static string ClipboardText(string text)
        {
            return (text ?? "").Replace("\r\n", "\n").Replace("\r", "\n").Replace("\n", "\r\n");
        }

        public ColorEntry AddWord(string name, string text)
        {
            string clean;
            string err = ValidateWord(name, text, out clean);
            if (err != null) throw new ArgumentException(err);
            var e = MakeWord(NewWordId(), clean, text.Replace("\r\n", "\n").Replace("\r", "\n"));
            Words.Items.Add(e);
            try { SaveWords(); }
            catch { Words.Items.Remove(e); throw; }
            return e;
        }

        public void UpdateWord(ColorEntry e, string name, string text)
        {
            if (e == null || !e.IsWord) throw new ArgumentException("マイワードではありません");
            string clean;
            string err = ValidateWord(name, text, out clean);
            if (err != null) throw new ArgumentException(err);
            string oldName = e.Name, oldText = e.Text;
            e.Name = clean;
            e.Text = text.Replace("\r\n", "\n").Replace("\r", "\n");
            e.SearchKey = SearchText.SearchKey(e);
            try { SaveWords(); }
            catch
            {
                e.Name = oldName;
                e.Text = oldText;
                e.SearchKey = SearchText.SearchKey(e);
                throw;
            }
        }

        public void RemoveWord(ColorEntry e)
        {
            Remove(e);
        }

        ColorGroup OwnGroup(ColorEntry e)
        {
            if (e == null) return null;
            if (e.Group == Mine) return Mine;
            if (e.Group == Words) return Words;
            return null;
        }

        void SaveGroup(ColorGroup g)
        {
            if (g == Words) SaveWords(); else SaveColors();
        }

        // ---- お気に入り・最近使ったもの(settings.json) ----
        public bool IsFavorite(ColorEntry e)
        {
            return e != null && e.Id != null && Settings.Favorites.Contains(e.Id);
        }

        // 新しい状態(true = お気に入り)を返す。保存できなければ元に戻して投げる
        public bool ToggleFavorite(ColorEntry e)
        {
            if (e == null || e.Id == null) throw new ArgumentException("項目がありません");
            var before = new List<string>(Settings.Favorites);
            bool now;
            if (Settings.Favorites.Contains(e.Id)) { Settings.Favorites.Remove(e.Id); now = false; }
            else
            {
                if (Settings.Favorites.Count >= Settings.MaxFavorites) throw new ArgumentException("お気に入りは " + Settings.MaxFavorites + " 件までです");
                Settings.Favorites.Add(e.Id);
                now = true;
            }
            try { SaveSettings(); }
            catch { Settings.Favorites = before; throw; }
            return now;
        }

        public void NoteRecent(ColorEntry e, int colorIndex)
        {
            if (e == null || e.Id == null) return;
            Settings.Recent.RemoveAll(r => r.Id == e.Id);
            Settings.Recent.Insert(0, new RecentItem { Id = e.Id, ColorIndex = Math.Max(0, Math.Min(Settings.MaxColorIndex, colorIndex)) });
            if (Settings.Recent.Count > Settings.MaxRecent) Settings.Recent.RemoveRange(Settings.MaxRecent, Settings.Recent.Count - Settings.MaxRecent);
            SaveSettings();
        }

        // 消した項目をお気に入り・最近使ったものからも外す
        public void Forget(ColorEntry e)
        {
            if (e == null || e.Id == null) return;
            int a = Settings.Favorites.RemoveAll(x => x == e.Id);
            int b = Settings.Recent.RemoveAll(r => r.Id == e.Id);
            if (a + b > 0) SaveSettings();
        }

        // id の並びを項目にする(順番はそのまま・知らない id は飛ばす)
        public List<ColorEntry> ResolveIds(IEnumerable<string> ids, IEnumerable<ColorEntry> all)
        {
            var map = new Dictionary<string, ColorEntry>();
            foreach (var e in all)
                if (e != null && e.Id != null && !map.ContainsKey(e.Id)) map[e.Id] = e;
            var list = new List<ColorEntry>();
            foreach (string id in ids)
            {
                ColorEntry e;
                if (id != null && map.TryGetValue(id, out e)) list.Add(e);
            }
            return list;
        }

        static string NewId()
        {
            return "my/" + Guid.NewGuid().ToString("N").Substring(0, 12);
        }

        ColorEntry MakeEntry(string id, string name, string hex)
        {
            var e = new ColorEntry { Id = id, Name = name, Sub = "", Hex = hex, Note = "", Group = Mine, IsUser = true };
            e.SetColors(new List<ColorOption> { new ColorOption(hex, "") });   // マイカラーは1色
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
            e.SetColors(new List<ColorOption> { new ColorOption(hex, "") });
            try { SaveColors(); }
            catch
            {
                e.Name = oldName;
                e.SetColors(new List<ColorOption> { new ColorOption(oldHex, "") });
                throw;
            }
        }

        // マイカラー・マイワードのどちらも消せる。保存できなければ元に戻して投げる
        public void Remove(ColorEntry e)
        {
            var g = OwnGroup(e);
            if (g == null) return;
            int i = g.Items.IndexOf(e);
            if (i < 0) return;
            g.Items.RemoveAt(i);
            try { SaveGroup(g); }
            catch { g.Items.Insert(i, e); throw; }
            Forget(e);
        }

        public bool Move(ColorEntry e, int delta)
        {
            var g = OwnGroup(e);
            if (g == null) return false;
            int i = g.Items.IndexOf(e);
            return i >= 0 && i + delta >= 0 && i + delta < g.Items.Count && MoveTo(e, i + delta);
        }

        // target(同じグループの項目)が今いる位置へ(ドラッグで落とした先)。画面の札の番号は検索で隠れた分だけずれるので、項目で受けてここで番号にする
        public bool MoveToEntry(ColorEntry e, ColorEntry target)
        {
            var g = OwnGroup(e);
            if (g == null || target == null || OwnGroup(target) != g) return false;
            int j = g.Items.IndexOf(target);
            return j >= 0 && MoveTo(e, j);
        }

        // 同じグループの中で index の位置へ(範囲の外は端に寄せる)。動かなければ false
        public bool MoveTo(ColorEntry e, int index)
        {
            var g = OwnGroup(e);
            if (g == null || g.Items.Count == 0) return false;
            int i = g.Items.IndexOf(e);
            if (i < 0) return false;
            int j = Math.Max(0, Math.Min(g.Items.Count - 1, index));
            if (i == j) return false;
            g.Items.RemoveAt(i);
            g.Items.Insert(j, e);
            try { SaveGroup(g); }
            catch
            {
                g.Items.RemoveAt(j);
                g.Items.Insert(i, e);
                throw;
            }
            return true;
        }
    }
}
