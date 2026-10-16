// 起動役 FriendInbox.exe の決まり(版の選び方・版の記録・見回りの判断)。画面にも通信にも触らない = tests\Tests.cs で確かめる。C# 5 で書く
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

        // 一番新しい版(bad に無い物)。無ければ移るまでの形(<home>\python・<home>\src)。それも無ければ null
        public static Layout Pick(string home, ICollection<string> bad)
        {
            foreach (var v in Installed(home))
                if (!bad.Contains(v)) return LayoutOf(home, v);
            var legacy = LayoutOf(home, null);
            return Complete(legacy) ? legacy : null;
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
            return gone;
        }
    }

    // GET /api/friend/state の中身
    public sealed class FriendState
    {
        public double WindowAgo;
        public bool Busy;
        public int Recording, Making, Waiting;
        public string Label = "";

        // 秒は小数(JavaScriptSerializer は decimal・int・long で返す)。無い・型が違うときは 0 = 窓は開いている扱い(誤って止めない)
        static double Number(IDictionary<string, object> d, string key)
        {
            object v;
            return d.TryGetValue(key, out v) && (v is decimal || v is int || v is long || v is double) ? Convert.ToDouble(v) : 0;
        }

        public static FriendState Parse(string text)
        {
            var j = Json.Parse(text);
            return new FriendState
            {
                WindowAgo = Number(j, "windowAgo"), Busy = Json.Bool(j, "busy", false), Recording = Json.Int(j, "recording", 0),
                Making = Json.Int(j, "making", 0), Waiting = Json.Int(j, "waiting", 0), Label = Json.Str(j, "label") ?? ""
            };
        }
    }

    public enum Step { None, Shutdown, ShowStatus, HideStatus }

    public static class Watch
    {
        public const double WindowClosedAfter = 20;   // 窓の問い合わせがこの秒数なければ窓が閉じたとみる

        // 見回り 1 回の判断: 窓が戻れば状態の窓を隠す・閉じていて仕事が無ければ止めて終わる・仕事があれば状態の窓を出す
        public static Step Decide(FriendState s, bool statusShown)
        {
            if (s.WindowAgo < WindowClosedAfter) return statusShown ? Step.HideStatus : Step.None;
            if (!s.Busy) return Step.Shutdown;
            return statusShown ? Step.None : Step.ShowStatus;
        }

        // 状態の窓の ×: 録画中は最小化と同じ・無ければ今すぐ止めて閉じる(確認は出さない)
        public static bool CloseStopsNow(int recording)
        {
            return recording <= 0;
        }
    }
}
