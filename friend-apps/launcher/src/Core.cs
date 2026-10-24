// FriendApp.exe の決まり(版の選び方・版の記録・閉じるときの判断)。画面にも通信にも触らない = tests\friend-apps\launcher\Tests.cs で確かめる。C# 5 で書く
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

    // <home>\app-versions.json = {"v":1, "current":"0.90.0", "previous":"0.89.0", "good":"0.89.0", "bad":["…"]}。書くのは起動役だけ(玄関は読むだけ)。
    // good = 確かに動いた版(玄関の確かめ verify が ok と言った版。戻す先・片付けで消さない)。前の exe は good を知らない(読み飛ばし、書くと消える = 戻す先は previous)
    public sealed class VersionRecord
    {
        public string Current = "", Previous = "", Good = "";
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

        // 一番新しい版(bad に無い物)。前の形(版のフォルダの無い <home>\python・<home>\src)も版として比べる。
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
            r.Good = Parse(Json.Str(j, "good")) != null ? Json.Str(j, "good") : "";
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
            string text = "{\"v\":1,\"current\":" + Q(r.Current) + ",\"previous\":" + Q(r.Previous) + ",\"good\":" + Q(r.Good) + ",\"bad\":[" + string.Join(",", r.Bad.Select(Q).ToArray()) + "]}";
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

        // 戻す先(玄関が頼んだ to。null なら確かに動いた版 good・無ければ previous)。置いてあって今の版と違う物だけ。戻せなければ null と理由
        public static string RollbackTarget(string home, VersionRecord r, string current, string to, out string why)
        {
            string t = !string.IsNullOrEmpty(to) ? to : (!string.IsNullOrEmpty(r.Good) ? r.Good : r.Previous);
            why = "";
            if (string.IsNullOrEmpty(t) || Parse(t) == null) { why = "戻す先の確かに動いた版がありません"; return null; }
            if (t == current) { why = "もう版 " + t + " で動いています"; return null; }
            if (!Installed(home).Contains(t)) { why = "戻す先の版 " + t + " が残っていません"; return null; }
            return t;
        }

        // 戻す: 戻す先より新しい置いてある版を全部 bad にする(次の起動で Pick が戻す先を選ぶ。間に置いたまま確かめていない版も飛ばす)。戻す先は bad から外す
        public static void ApplyRollback(string home, VersionRecord r, string target)
        {
            r.Bad.Remove(target);
            foreach (var v in Installed(home))
                if (Compare(v, target) > 0 && !r.Bad.Contains(v)) r.Bad.Add(v);
        }

        // 残す版の数(current から古い方へ数える)。src/friendapp/tidy.py の KEEP_VERSIONS と同じ値にする
        public const int Keep = 3;

        // 残す一番古い版(floor)= Installed のうち current 以下で bad に無い物を新しい順に並べた Keep 番目(足りなければ最古)。無ければ null
        public static string KeepFloor(string home, VersionRecord r)
        {
            if (string.IsNullOrEmpty(r.Current)) return null;
            string floor = null;
            int n = 0;
            foreach (var v in Installed(home))
            {
                if (Compare(v, r.Current) > 0 || r.Bad.Contains(v)) continue;
                floor = v;
                if (++n >= Keep) break;
            }
            return floor;
        }

        // floor より古い app-<版>\ を消す(8-2。bad も floor 未満なら消す)。新しいけれどまだ起動していない物・bad の新しい物は触らない。消した名前を返す
        public static List<string> Prune(string home, VersionRecord r, Action<string> log)
        {
            var gone = new List<string>();
            string floor = KeepFloor(home, r);
            if (string.IsNullOrEmpty(floor)) return gone;
            foreach (var d in Directory.GetDirectories(home, Prefix + "*"))
            {
                string name = Path.GetFileName(d).Substring(Prefix.Length);
                if (Parse(name) == null || Compare(name, floor) >= 0 || name == r.Current || name == r.Previous || name == r.Good) continue;
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
    // 動いている exe と DLL は名前なら変えられる = *.old にしてから写す・次の起動で *.old を消す。exe と DLL が版のフォルダに無ければ写さない(Python だけ新しい版)。
    // 写すのは先に *.new へ全部写し切ってから、名前の付け替え 2 回(本体 → *.old・*.new → 本体)だけにする(10-23 の見回り: 写す途中で電源が落ちると exe が無い・欠けたまま起動できなかった)
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
                var ready = new List<string>();
                foreach (var f in Files)   // 1. 全部を *.new へ(ここで落ちても本体はそのまま)
                {
                    string src = Path.Combine(from, f), tmp = Path.Combine(home, f) + ".new";
                    if (!File.Exists(src)) continue;
                    File.Copy(src, tmp, true);
                    ready.Add(f);
                }
                foreach (var f in ready)   // 2. 名前の付け替えだけ
                {
                    string dst = Path.Combine(home, f), old = dst + ".old", tmp = dst + ".new";
                    if (File.Exists(old)) File.Delete(old);
                    if (File.Exists(dst)) File.Move(dst, old);
                    done.Add(f);
                    File.Move(tmp, dst);
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
                foreach (var f in Files)   // 写しかけの *.new を残さない
                {
                    try { string tmp = Path.Combine(home, f) + ".new"; if (File.Exists(tmp)) File.Delete(tmp); }
                    catch (Exception ex3) { if (!(ex3 is IOException || ex3 is UnauthorizedAccessException)) throw; }
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
                string old = Path.Combine(home, f + ".old"), tmp = Path.Combine(home, f + ".new");
                try { if (File.Exists(old)) { File.Delete(old); n++; } }
                catch (Exception ex) { if (!(ex is IOException || ex is UnauthorizedAccessException)) throw; }
                try { if (File.Exists(tmp)) File.Delete(tmp); }   // 写す途中で落ちた残り(本体は前の版のまま)
                catch (Exception ex) { if (!(ex is IOException || ex is UnauthorizedAccessException)) throw; }
            }
            return n;
        }
    }

    // GET /api/friend/state の中身(窓と画面の境目。notes:plan/f1-friend-requirements.md の C-5-3・C-5-4)
    public sealed class HostState
    {
        public int Making, Recording, Waiting, Reserved, ArchiveWait, Undecided;
        public bool Setup, Awake, UpdateRequested;
        public string Label = "", Update = "";
        // 玄関が決める欄(前の玄関は書かない = 欄が無ければ前の決まり): swap = 今入れ替えてよい・verify = 新しい版の確かめ(pending / ok / fail)・
        // rollback = 今戻す {to: 版か null(確かに動いた版), why}
        public bool HasSwap, Swap, HasRollback;
        public string Verify = "", RollbackTo, RollbackWhy = "";

        public static HostState Parse(string text)
        {
            var j = Json.Parse(text);
            var rb = Json.Dict(j, "rollback");
            return new HostState
            {
                HasSwap = j.ContainsKey("swap"), Swap = Json.Bool(j, "swap", false), Verify = Json.Str(j, "verify") ?? "",
                HasRollback = rb != null, RollbackTo = rb != null ? Json.Str(rb, "to") : null, RollbackWhy = rb != null ? (Json.Str(rb, "why") ?? "") : "",
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

    // 窓の決まり(画面にも通信にも触らない = tests\friend-apps\launcher\Tests.cs で確かめる)
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

        // 入れ替えを頼まれ、新しい版がある。いつ入れ替えるかは玄関の swap(重要な直し・[今すぐ] は作業があっても入れ替える。録画中は待つ)。
        // swap の無い前の玄関は、作業も預かりも無いときだけ
        public static bool ShouldApplyUpdate(HostState s)
        {
            if (s == null || !s.UpdateRequested || Versions.Parse(s.Update) == null) return false;
            return s.HasSwap ? s.Swap : s.Holdings == 0;
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

    // 診断の記録(notes:docs/spec/friend.md の 13-11。Python の src/friendapp/diag.py と同じ形 v 1・source exe)。
    // 起動・起こし直し・更新の失敗・合言葉の違い・思わぬ例外を <home>\data\app\outbox\launcher__diag-<ミリ秒 13 桁>.diag.json に書く。
    // 上げるのは Python の同期(Dropbox の /診断/。Python が起きなかった回の物は次に起きたとき)。ユーザー名を含むパス・合言葉は伏せる。
    // 3 日より古い物は書くたびに消す。書けなくても止めない。YTT_FRIEND_DIAG=0・ユーザーの PC の作業データ(prefs.json の intake.folder)では書かない
    public static class Diag
    {
        public const int KeepDays = 3, TailLines = 20, SummaryMax = 300, DetailMax = 4000;
        public static readonly System.Text.RegularExpressions.Regex NameRx = new System.Text.RegularExpressions.Regex(@"^[0-9A-Za-z_-]{1,64}__diag-(\d{13})\.diag\.json$");
        static readonly System.Text.RegularExpressions.Regex UsersRx = new System.Text.RegularExpressions.Regex(
            @"([A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+)[^\\/""'<>|\r\n\t]+", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        static readonly System.Text.RegularExpressions.Regex HexToken = new System.Text.RegularExpressions.Regex(@"\b[0-9a-f]{48}\b");
        static readonly object gate = new object();

        // 実行中の値(Program と Backend が入れる)。Note はこれを使う
        public static string Home, AppVersion, Token, Host;

        public static string Box(string home) { return Path.Combine(home, "data", "app", "outbox"); }

        static string ReplaceNoCase(string s, string find, string rep)
        {
            if (string.IsNullOrEmpty(find)) return s;
            return System.Text.RegularExpressions.Regex.Replace(s, System.Text.RegularExpressions.Regex.Escape(find), rep.Replace("$", "$$"),
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        }

        // 文から伏せる: 合言葉 -> <secret>・48 桁の 16 進 -> <token>・アプリのフォルダ -> <app>・%USERPROFILE% と C:\Users\<名前> -> <user>・ユーザー名(3 字以上)-> <user>
        public static string Mask(string s, string home, string profile, string user, string token)
        {
            if (string.IsNullOrEmpty(s)) return "";
            if (!string.IsNullOrEmpty(token) && token.Length >= 8) s = s.Replace(token, "<secret>");
            s = HexToken.Replace(s, "<token>");
            if (!string.IsNullOrEmpty(home)) { s = ReplaceNoCase(s, home, "<app>"); s = ReplaceNoCase(s, home.Replace('\\', '/'), "<app>"); }
            if (!string.IsNullOrEmpty(profile) && profile.Length > 3) { s = ReplaceNoCase(s, profile, "<user>"); s = ReplaceNoCase(s, profile.Replace('\\', '/'), "<user>"); }
            s = UsersRx.Replace(s, "$1<user>");
            if (!string.IsNullOrEmpty(user) && user.Trim().Length >= 3)
                s = System.Text.RegularExpressions.Regex.Replace(s, "(?<![0-9A-Za-z])" + System.Text.RegularExpressions.Regex.Escape(user.Trim()) + "(?![0-9A-Za-z])", "<user>",
                    System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            return s;
        }

        // Windows の版(例: Windows 11 10.0.26100。app.manifest で Windows 10 以降と言っているので本当の番号が読める)
        public static string WindowsText()
        {
            var v = Environment.OSVersion.Version;
            return "Windows " + (v.Major == 10 && v.Build >= 22000 ? "11" : v.Major.ToString()) + " " + v.Major + "." + v.Minor + "." + v.Build;
        }

        public static bool Off(string home)
        {
            string sw = (Environment.GetEnvironmentVariable("YTT_FRIEND_DIAG") ?? "").Trim().ToLowerInvariant();
            if (sw == "0" || sw == "off" || sw == "false" || sw == "no") return true;
            try
            {
                var p = Json.ReadFileOrNull(Path.Combine(home, "data", "app", "prefs.json"));
                var intake = p != null ? Json.Dict(p, "intake") : null;
                return intake != null && !string.IsNullOrEmpty((Json.Str(intake, "folder") ?? "").Trim());
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException || ex is FormatException || ex is ArgumentException || ex is InvalidOperationException)) throw;
                return false;
            }
        }

        static long Ms(DateTime utc) { return (long)(utc - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalMilliseconds; }

        // 1 つ書く -> パスか null(書かない・書けない)。extra はそのまま足す(呼ぶ側で伏せた物だけ)
        public static string Write(string home, string kind, string version, string host, string summary, string detail, IEnumerable<string> tail,
                                   IDictionary<string, object> extra, DateTime utcNow, string token)
        {
            if (string.IsNullOrEmpty(home) || Off(home)) return null;
            string profile = Environment.GetEnvironmentVariable("USERPROFILE"), user = Environment.UserName;
            Func<string, string> m = x => Mask(x, home, profile, user, token);
            try
            {
                long at = Ms(utcNow);
                var doc = new Dictionary<string, object>
                {
                    { "v", 1 }, { "kind", kind }, { "source", "exe" }, { "at", at }, { "requestId", null },
                    { "app", new Dictionary<string, object> { { "version", version ?? "?" }, { "host", host ?? "" } } },
                    { "pc", new Dictionary<string, object> { { "windows", WindowsText() }, { "gpu", null }, { "device", null } } },
                };
                string sum = m(summary);
                doc["summary"] = sum.Length > SummaryMax ? sum.Substring(0, SummaryMax) : sum;
                if (!string.IsNullOrEmpty(detail)) { string d = m(detail); doc["detail"] = d.Length > DetailMax ? d.Substring(0, DetailMax) : d; }
                if (tail != null)
                {
                    var lines = tail.Select(x => { string t = m(x); return t.Length > 300 ? t.Substring(0, 300) : t; }).ToList();
                    doc["tail"] = lines.Skip(Math.Max(0, lines.Count - TailLines)).ToList();
                }
                if (extra != null) foreach (var kv in extra) doc[kv.Key] = kv.Value;
                string box = Box(home);
                lock (gate)
                {
                    Directory.CreateDirectory(box);
                    string path;
                    while (true)
                    {
                        path = Path.Combine(box, "launcher__diag-" + at.ToString("D13") + ".diag.json");
                        if (!File.Exists(path)) break;
                        at++;
                    }
                    doc["at"] = at;
                    string tmp = path + ".tmp";
                    File.WriteAllText(tmp, Json.Pretty(doc), new UTF8Encoding(false));
                    File.Move(tmp, path);
                    Prune(box, utcNow);
                    return path;
                }
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException || ex is InvalidOperationException || ex is ArgumentException)) throw;
                return null;
            }
        }

        // 実行中の値で書く(Home が無ければ何もしない)
        public static string Note(string kind, string summary, string detail = null, IEnumerable<string> tail = null, IDictionary<string, object> extra = null)
        {
            string p = Write(Home, kind, AppVersion, Host, summary, detail, tail, extra, DateTime.UtcNow, Token);
            if (p != null) Log.Write("診断を書きました: " + Path.GetFileName(p));
            return p;
        }

        // 箱の 3 日より古い診断を消す(診断の名前の物だけ)-> 消した数
        public static int Prune(string box, DateTime utcNow)
        {
            int n = 0;
            if (!Directory.Exists(box)) return 0;
            long now = Ms(utcNow);
            foreach (string f in Directory.GetFiles(box))
            {
                var mm = NameRx.Match(Path.GetFileName(f));
                if (!mm.Success || now - long.Parse(mm.Groups[1].Value) < KeepDays * 86400000L) continue;
                try { File.Delete(f); n++; }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
            return n;
        }
    }

    // 「起動できなかった」「前の版へ戻した」の小さなファイル(形の正は notes:plan/友人の不具合の自動対応-1025.md の「更新」)。
    // launcher__fail-<ミリ秒 13 桁>.fail.json = {v:1, kind:"launch_fail"|"rollback", at, from, to, why}(版・時刻・理由だけ)。
    // Python が起きなくても届くよう、exe が Dropbox へ直に上げる(Launcher.cs の DropboxDirect)。上げられなければ送り返しの箱へ(次に起きた Python の同期が上げる)
    public static class FailFile
    {
        public const int WhyMax = 300;
        public static readonly System.Text.RegularExpressions.Regex NameRx = new System.Text.RegularExpressions.Regex(@"^[0-9A-Za-z_-]{1,64}__fail-(\d{13})\.fail\.json$");

        public static long Ms(DateTime utc) { return (long)(utc - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalMilliseconds; }

        public static string Name(long at) { return "launcher__fail-" + at.ToString("D13") + ".fail.json"; }

        // 中身(why は伏せて 300 字まで)
        public static string Text(string kind, long at, string from, string to, string why, string home)
        {
            string w = Diag.Mask(why ?? "", home, Environment.GetEnvironmentVariable("USERPROFILE"), Environment.UserName, Diag.Token);
            if (w.Length > WhyMax) w = w.Substring(0, WhyMax);
            var doc = new Dictionary<string, object>
            {
                { "v", 1 }, { "kind", kind }, { "at", at }, { "from", string.IsNullOrEmpty(from) ? null : from }, { "to", string.IsNullOrEmpty(to) ? null : to }, { "why", w }
            };
            return Json.Pretty(doc);
        }

        // 送り返しの箱へ書く -> パスか null(スイッチ・書けない)
        public static string WriteOutbox(string home, string name, string text)
        {
            if (string.IsNullOrEmpty(home) || Diag.Off(home)) return null;
            try
            {
                string box = Diag.Box(home);
                Directory.CreateDirectory(box);
                string path = Path.Combine(box, name), tmp = path + ".tmp";
                File.WriteAllText(tmp, text, new UTF8Encoding(false));
                if (File.Exists(path)) File.Delete(path);
                File.Move(tmp, path);
                return path;
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                return null;
            }
        }
    }
}
