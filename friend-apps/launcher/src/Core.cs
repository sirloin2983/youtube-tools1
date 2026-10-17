// FriendApp.exe の決まり(版の選び方・版の記録・閉じるときの判断)。画面にも通信にも触らない = tests\Tests.cs で確かめる。C# 5 で書く
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using FriendApps;

namespace FriendInbox
{
    // 玄関(Python)を起こす場所。Version が null のときは移るまでの形(<home>\python・<home>\src)
    public sealed class Layout
    {
        public string Version, Python, Script;
    }

    // <home>\app-versions.json = {"v":1, "current":"0.90.0", "previous":"0.89.0", "bad":["…"]}。書くのは起動役だけ(玄関は読むだけ)
    public sealed class VersionRecord
    {
        public string Current = "", Previous = "";
        public List<string> Bad = new List<string>();
    }

    public static class Versions
    {
        public const string Prefix = "app-";
        public const string RecordName = "app-versions.json";

        // "0.90.1" -> {0, 90, 1}。数字と . だけで 1〜4 個でなければ null(app-0.90.0.tmp などは版ではない)
        public static int[] Parse(string v)
        {
            if (string.IsNullOrEmpty(v)) return null;
            var parts = v.Split('.');
            if (parts.Length < 1 || parts.Length > 4) return null;
            var n = new int[parts.Length];
            for (int i = 0; i < parts.Length; i++)
            {
                if (parts[i].Length == 0 || parts[i].Length > 6 || !parts[i].All(c => c >= '0' && c <= '9')) return null;
                n[i] = int.Parse(parts[i]);
            }
            return n;
        }

        // 数字の並びで比べる(0.9.0 < 0.10.0)。足りない桁は 0
        public static int Compare(string a, string b)
        {
            var x = Parse(a) ?? new int[0];
            var y = Parse(b) ?? new int[0];
            for (int i = 0; i < Math.Max(x.Length, y.Length); i++)
            {
                int p = i < x.Length ? x[i] : 0, q = i < y.Length ? y[i] : 0;
                if (p != q) return p < q ? -1 : 1;
            }
            return 0;
        }

        public static Layout LayoutOf(string home, string version)
        {
            string root = version == null ? home : Path.Combine(home, Prefix + version);
            return new Layout { Version = version, Python = Path.Combine(root, "python", "python.exe"), Script = Path.Combine(root, "src", "friendapp", "server.py") };
        }

        static bool Complete(Layout l)
        {
            return File.Exists(l.Python) && File.Exists(l.Script);
        }

        // 置いてある版(app-<版>\ に python.exe と server.py が揃っている物)。新しい順。展開途中の app-<版>.tmp は入らない
        public static List<string> Installed(string home)
        {
            var list = new List<string>();
            if (!Directory.Exists(home)) return list;
            foreach (var d in Directory.GetDirectories(home, Prefix + "*"))
            {
                string name = Path.GetFileName(d).Substring(Prefix.Length);
                if (Parse(name) != null && Complete(LayoutOf(home, name))) list.Add(name);
            }
            list.Sort((a, b) => Compare(b, a));
            return list;
        }

        // 前の形(<home>\src)の版(src\ytt\version.py の VERSION = "…")。読めなければ null
        public static string LegacyVersion(string home)
        {
            try
            {
                string p = Path.Combine(home, "src", "ytt", "version.py");
                if (!File.Exists(p)) return null;
                var m = System.Text.RegularExpressions.Regex.Match(File.ReadAllText(p, Encoding.UTF8), "^VERSION\\s*=\\s*\"([0-9.]+)\"", System.Text.RegularExpressions.RegexOptions.Multiline);
                return m.Success && Parse(m.Groups[1].Value) != null ? m.Groups[1].Value : null;
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                return null;
            }
        }

        // 一番新しい版(bad に無い物)。前の形(<home>\python・<home>\src)も版として比べる(前のアプリの [更新する] で前の形に新しい版が入る = 移る最後の 1 回)。
        // skipLegacy = 前の形が起動できなかった。どれも無ければ null
        public static Layout Pick(string home, ICollection<string> bad, bool skipLegacy = false)
        {
            var legacy = LayoutOf(home, null);
            bool legOk = !skipLegacy && Complete(legacy);
            string lv = legOk ? LegacyVersion(home) : null;
            foreach (var v in Installed(home))
                if (!bad.Contains(v)) return lv != null && Compare(lv, v) > 0 ? legacy : LayoutOf(home, v);
            return legOk ? legacy : null;
        }

        public static VersionRecord Read(string home)
        {
            var r = new VersionRecord();
            var j = Json.ReadFileOrNull(Path.Combine(home, RecordName));
            if (j == null) return r;
            r.Current = Json.Str(j, "current") ?? "";
            r.Previous = Json.Str(j, "previous") ?? "";
            var bad = j.ContainsKey("bad") ? j["bad"] as System.Collections.IEnumerable : null;
            if (bad != null)
                foreach (var o in bad)
                {
                    var s = o as string;
                    if (s != null && Parse(s) != null && !r.Bad.Contains(s)) r.Bad.Add(s);
                }
            return r;
        }

        static string Q(string s)
        {
            return "\"" + (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
        }

        public static void Write(string home, VersionRecord r)
        {
            string text = "{\"v\":1,\"current\":" + Q(r.Current) + ",\"previous\":" + Q(r.Previous) + ",\"bad\":[" + string.Join(",", r.Bad.Select(Q).ToArray()) + "]}";
            string path = Path.Combine(home, RecordName), tmp = path + ".tmp";
            File.WriteAllText(tmp, text, new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(tmp, path, null); else File.Move(tmp, path);
        }

        // 起動できた版 v を current に、その前の current を previous に(bad の版は previous にしない)
        public static void MarkStarted(VersionRecord r, string v)
        {
            if (r.Current == v) return;
            if (!string.IsNullOrEmpty(r.Current) && !r.Bad.Contains(r.Current)) r.Previous = r.Current;
            r.Current = v;
            if (r.Previous == v) r.Previous = "";
        }

        // current・previous より古い app-<版>\ を消す(8-2)。新しいけれどまだ起動していない物・bad の新しい物は触らない。消した名前を返す
        public static List<string> Prune(string home, VersionRecord r, Action<string> log)
        {
            var gone = new List<string>();
            string floor = !string.IsNullOrEmpty(r.Previous) ? r.Previous : r.Current;
            if (string.IsNullOrEmpty(floor)) return gone;
            foreach (var d in Directory.GetDirectories(home, Prefix + "*"))
            {
                string name = Path.GetFileName(d).Substring(Prefix.Length);
                if (Parse(name) == null || Compare(name, floor) >= 0 || name == r.Current || name == r.Previous) continue;
                try { Directory.Delete(d, true); gone.Add(name); }
                catch (Exception ex)
                {
                    if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                    if (log != null) log("古い版を消せませんでした: " + name + " " + ex.Message);
                }
            }
            // 前の形(<home>\src・<home>\python)は、版のフォルダが 2 つ(current・previous)そろい、前の形の方が古ければ消す(戻る先は previous がある)
            string lv = LegacyVersion(home);
            if (!string.IsNullOrEmpty(r.Current) && !string.IsNullOrEmpty(r.Previous) && Directory.Exists(Path.Combine(home, Prefix + r.Current)) &&
                Directory.Exists(Path.Combine(home, Prefix + r.Previous)) && (lv == null || Compare(lv, r.Previous) <= 0))
            {
                foreach (var d in new[] { "src", "python" })
                {
                    string p = Path.Combine(home, d);
                    if (!Directory.Exists(p)) continue;
                    try { Directory.Delete(p, true); gone.Add("(前の形の " + d + ")"); }
                    catch (Exception ex)
                    {
                        if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                        if (log != null) log("前の形の " + d + " を消せませんでした: " + ex.Message);
                    }
                }
            }
            return gone;
        }
    }

    // 更新の入れ替え(画面の [更新する] → 作業と預かりが無くなったら): app-<版>\ の FriendApp.exe と DLL をアプリのフォルダへ写す。
    // 動いている exe と DLL は名前なら変えられる = *.old にしてから写す・次の起動で *.old を消す。exe と DLL が版のフォルダに無ければ写さない(Python だけ新しい版)
    public static class Updater
    {
        public static readonly string[] Files = { "FriendApp.exe", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll" };

        // -> 写した数。途中で失敗したら写した物を戻して例外
        public static int Swap(string home, string version)
        {
            string from = Path.Combine(home, Versions.Prefix + version);
            var done = new List<string>();
            try
            {
                foreach (var f in Files)
                {
                    string src = Path.Combine(from, f), dst = Path.Combine(home, f), old = dst + ".old";
                    if (!File.Exists(src)) continue;
                    if (File.Exists(old)) File.Delete(old);
                    if (File.Exists(dst)) File.Move(dst, old);
                    done.Add(f);
                    File.Copy(src, dst);
                }
                return done.Count;
            }
            catch (Exception)
            {
                foreach (var f in done)   // 戻す: 写しかけを消して *.old を元の名前へ
                {
                    string dst = Path.Combine(home, f), old = dst + ".old";
                    try { if (File.Exists(old)) { if (File.Exists(dst)) File.Delete(dst); File.Move(old, dst); } }
                    catch (Exception ex2) { if (!(ex2 is IOException || ex2 is UnauthorizedAccessException)) throw; }
                }
                throw;
            }
        }

        // 前の入れ替えで残った *.old を消す(動いていなければ消せる。消せなければ次の回)
        public static int CleanOld(string home)
        {
            int n = 0;
            foreach (var f in Files)
            {
                string old = Path.Combine(home, f + ".old");
                try { if (File.Exists(old)) { File.Delete(old); n++; } }
                catch (Exception ex) { if (!(ex is IOException || ex is UnauthorizedAccessException)) throw; }
            }
            return n;
        }

        // 前のアプリの名前(RequestSender.exe)で起こされたか = 前のアプリの [更新する] が FriendApp.exe の写しを RequestSender.exe として置いた(移る最後の 1 回)
        public static bool IsHandoffName(string exePath)
        {
            return string.Equals(Path.GetFileName(exePath), "RequestSender.exe", StringComparison.OrdinalIgnoreCase);
        }
    }

    // GET /api/friend/state の中身(窓と画面の境目。notes:plan/f1-friend-requirements.md の C-5-3・C-5-4)
    public sealed class HostState
    {
        public int Making, Recording, Waiting, Reserved, ArchiveWait, Undecided;
        public bool Setup, Awake, UpdateRequested;
        public string Label = "", Update = "";

        public static HostState Parse(string text)
        {
            var j = Json.Parse(text);
            return new HostState
            {
                Making = Json.Int(j, "making", 0), Recording = Json.Int(j, "recording", 0), Waiting = Json.Int(j, "waiting", 0),
                Reserved = Json.Int(j, "reserved", 0), ArchiveWait = Json.Int(j, "archiveWait", 0), Undecided = Json.Int(j, "undecided", 0),
                Setup = Json.Bool(j, "setup", false), Awake = Json.Bool(j, "awake", false), Label = Json.Str(j, "label") ?? "",
                Update = Json.Str(j, "update") ?? "", UpdateRequested = Json.Bool(j, "updateRequested", false)
            };
        }

        // 作業中と預かりの数(0 なら閉じてもすぐ止めてよい)
        public int Holdings
        {
            get { return Math.Max(0, Making) + Math.Max(0, Recording) + Math.Max(0, Waiting) + Math.Max(0, Reserved) + Math.Max(0, ArchiveWait) + (Setup ? 1 : 0); }
        }
    }

    // 窓の決まり(画面にも通信にも触らない = tests\Tests.cs で確かめる)
    public static class Rules
    {
        public const string AppTitle = "切り抜き依頼";

        // 閉じるとき(×・[すべて止めて終了]・アイコンの「止める」)に確認を出すか。状態を読めない(Python が止まっている)ときは出さない
        public static bool NeedConfirm(HostState s)
        {
            return s != null && s.Holdings > 0;
        }

        // 確認の窓の文(作っている数・録画中なら「録画が途中で切れます」・予約とアーカイブ待ちの数・「閉じると止まります」)
        public static string ConfirmText(HostState s)
        {
            var lines = new List<string>();
            if (s.Setup) lines.Add("初回の準備をしています(止めても、次に開くと続きから取ります)");
            if (s.Making > 0) lines.Add("作っている物が " + s.Making + " 件あります");
            if (s.Waiting > 0) lines.Add("順番を待っている物が " + s.Waiting + " 件あります");
            if (s.Recording > 0) lines.Add("録画中が " + s.Recording + " 件あります。止めると録画が途中で切れます");
            if (s.Reserved > 0) lines.Add("予約が " + s.Reserved + " 件あります");
            if (s.ArchiveWait > 0) lines.Add("アーカイブ待ちが " + s.ArchiveWait + " 件あります");
            lines.Add("");
            lines.Add("閉じると止まります。裏で続けると、終わったら自分で閉じます。");
            lines.Add("(止めても作っている途中の物は消えず、次に開いたときに続きから作ります)");
            return string.Join("\r\n", lines.ToArray());
        }

        // 時計の横のアイコンの文(Windows の上限 127 文字)
        public static string TrayText(HostState s, bool background)
        {
            var parts = new List<string>();
            if (s != null)
            {
                if (s.Setup) parts.Add("準備しています");
                if (s.Making > 0) parts.Add("作っています " + s.Making + " 件");
                if (s.Recording > 0) parts.Add("録画中 " + s.Recording + " 件");
                if (s.Waiting > 0) parts.Add("待ち " + s.Waiting + " 件");
                if (s.Reserved + s.ArchiveWait > 0) parts.Add("予約・アーカイブ待ち " + (s.Reserved + s.ArchiveWait) + " 件");
            }
            string t = AppTitle + (background ? "(裏で続けています)" : "") + (parts.Count > 0 ? "\n" + string.Join("・", parts.ToArray()) : "");
            return t.Length > 127 ? t.Substring(0, 127) : t;
        }

        // 時計の横のアイコンのメニューの頭の行(今の作業の件数。読めないときは「読み込み中」)
        public static string MenuStatus(HostState s)
        {
            if (s == null) return "状態を読み込んでいます";
            var parts = new List<string>();
            if (s.Setup) parts.Add("準備しています");
            if (s.Making > 0) parts.Add("作っています " + s.Making + " 件");
            if (s.Recording > 0) parts.Add("録画中 " + s.Recording + " 件");
            if (s.Waiting > 0) parts.Add("待ち " + s.Waiting + " 件");
            if (s.Reserved > 0) parts.Add("予約 " + s.Reserved + " 件");
            if (s.ArchiveWait > 0) parts.Add("アーカイブ待ち " + s.ArchiveWait + " 件");
            return parts.Count > 0 ? string.Join("・", parts.ToArray()) : "作業はありません";
        }

        // メニューの「受け取る」の行(まだ決めていない本数)。0 なら null = 出さない
        public static string MenuUndecided(HostState s)
        {
            return s != null && s.Undecided > 0 ? "まだ決めていない物 " + s.Undecided + " 本" : null;
        }

        // 窓のタイトル(まだ決めていない本数 ●n。0 なら出さない = C-3-9)
        public static string Title(int undecided)
        {
            return undecided > 0 ? AppTitle + " ●" + undecided : AppTitle;
        }

        // [更新する] を押され、新しい版があり、作業も預かりも無い = 入れ替えてよい
        public static bool ShouldApplyUpdate(HostState s)
        {
            return s != null && s.UpdateRequested && Versions.Parse(s.Update) != null && s.Holdings == 0;
        }

        // 裏で続けている間に仕事が無くなったら自分で終わる
        public static bool AutoExit(HostState s, bool background)
        {
            return background && s != null && s.Holdings == 0;
        }

        // Python が先に終わったときに起こし直すか(10 分のうち 3 回まで。止める途中なら起こさない)
        public static bool ShouldRestart(List<DateTime> recent, DateTime now, bool stopping)
        {
            if (stopping) return false;
            recent.RemoveAll(t => (now - t).TotalMinutes > 10);
            return recent.Count < 3;
        }
    }
}
