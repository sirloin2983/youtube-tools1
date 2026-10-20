// YouTube のログイン(notes:docs/spec/friend.md の 13-13)。友人の PC の yt-dlp が bot 判定で止められないように、アプリの小窓で
// Google(サブのアカウントを勧める)にログインしてもらい、cookie を yt-dlp が読む Netscape 形式の cookies.txt に書く。C# 5 で書く
// - 小窓の WebView2 は主の窓と別のプロファイル(<friendDir>\ytlogin-webview2)。開く前と閉じたあとに消す = ブラウザ側で cookie を回さない
//   (yt-dlp の wiki の「回されない cookie の取り方」: 私窓でログイン → robots.txt へ → 書き出す → 窓を閉じる)
// - 書く先は <friendDir>\secrets\youtube-cookies.txt(Python の friendapp/places.cookies_path と同じ)。Dropbox・診断・送り返しには入らない。
//   中身(値)はログに出さない(件数だけ)。yt-dlp には Python(ytt/tools.ytdlp_auth_args)が呼ぶたびに写しで渡す
// - 決まり(YtCookies)は画面にも通信にも触らない = tests\friend-apps\launcher\Tests.cs で偽の cookie で確かめる
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using FriendApps;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace FriendInbox
{
    // cookie 1 つ(WebView2 の CoreWebView2Cookie から写した物。テストは偽の値で作る)
    public sealed class CookieRow
    {
        public string Domain = "", Path = "/", Name = "", Value = "";
        public bool Secure, HttpOnly;
        public long Expires;   // UNIX 秒。0 = セッションの cookie
    }

    public static class YtCookies
    {
        public const string LoginUrl = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F";
        public const string RobotsUrl = "https://www.youtube.com/robots.txt";
        public static readonly string[] ReadFrom = { "https://www.youtube.com", "https://www.google.com", "https://accounts.google.com" };
        static readonly string[] Domains = { "youtube.com", "google.com" };

        public static string CookiesPath(string friendDir) { return System.IO.Path.Combine(friendDir, "secrets", "youtube-cookies.txt"); }
        public static string ProfileDir(string friendDir) { return System.IO.Path.Combine(friendDir, "ytlogin-webview2"); }

        // youtube.com のページで、ログインの cookie(LOGIN_INFO と SAPISID の仲間)が揃ったか
        public static bool LoggedIn(IEnumerable<string> names)
        {
            var set = new HashSet<string>(names ?? new string[0]);
            return set.Contains("LOGIN_INFO") && (set.Contains("SAPISID") || set.Contains("__Secure-3PAPISID"));
        }

        public static bool IsYouTube(string uri)
        {
            Uri u;
            return Uri.TryCreate(uri, UriKind.Absolute, out u) && u.Scheme == "https" && u.Host.Equals("www.youtube.com", StringComparison.OrdinalIgnoreCase);
        }

        public static bool IsRobots(string uri)
        {
            Uri u;
            return IsYouTube(uri) && Uri.TryCreate(uri, UriKind.Absolute, out u) && u.AbsolutePath == "/robots.txt";
        }

        // 書く物: youtube.com・google.com(とその下)だけ・名前と値にタブや改行の無い物・同じ (ドメイン, パス, 名前) は 1 つ
        public static List<CookieRow> Pick(IEnumerable<CookieRow> rows)
        {
            var seen = new HashSet<string>();
            var outp = new List<CookieRow>();
            foreach (var r in rows ?? new CookieRow[0])
            {
                if (r == null || string.IsNullOrEmpty(r.Name) || string.IsNullOrEmpty(r.Domain)) continue;
                string d = r.Domain.TrimStart('.').ToLowerInvariant();
                if (!Domains.Any(x => d == x || d.EndsWith("." + x))) continue;
                if (Bad(r.Name) || Bad(r.Value ?? "") || Bad(r.Domain) || Bad(r.Path ?? "/")) continue;
                if (!seen.Add(d + "\t" + (r.Path ?? "/") + "\t" + r.Name)) continue;
                outp.Add(r);
            }
            return outp;
        }

        static bool Bad(string s) { return s.IndexOf('\t') >= 0 || s.IndexOf('\n') >= 0 || s.IndexOf('\r') >= 0; }

        // Netscape 形式の 1 行(HttpOnly は #HttpOnly_ を頭に。yt-dlp はどちらも読む)
        public static string Line(CookieRow r)
        {
            string dom = r.Domain;
            bool sub = dom.StartsWith(".");   // .youtube.com = 下のホストにも送る・www.youtube.com = そのホストだけ(WebView2 の形のまま)
            return (r.HttpOnly ? "#HttpOnly_" : "") + dom + "\t" + (sub ? "TRUE" : "FALSE") + "\t" + (string.IsNullOrEmpty(r.Path) ? "/" : r.Path) + "\t" +
                   (r.Secure ? "TRUE" : "FALSE") + "\t" + Math.Max(0, r.Expires) + "\t" + r.Name + "\t" + (r.Value ?? "");
        }

        public static string Text(IEnumerable<CookieRow> rows)
        {
            var sb = new StringBuilder("# Netscape HTTP Cookie File\n# FriendApp.exe が YouTube のログインから書きました。人に渡さないでください\n\n");
            foreach (var r in Pick(rows)) sb.Append(Line(r)).Append('\n');
            return sb.ToString();
        }

        // 一時のファイルに書いてから入れ替える(Python が読んでいる途中でも半端な物を見せない)-> 書いた件数
        public static int Save(string friendDir, IEnumerable<CookieRow> rows)
        {
            var picked = Pick(rows);
            string path = CookiesPath(friendDir);
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path));
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, Text(picked), new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(tmp, path, null);
            else File.Move(tmp, path);
            return picked.Count;
        }

        // 小窓のプロファイルを消す(開く前・閉じたあと・起動のとき)。使っている途中で消せなければ次の回に
        public static bool DeleteProfile(string friendDir)
        {
            string d = ProfileDir(friendDir);
            if (!Directory.Exists(d)) return true;
            try { Directory.Delete(d, true); return true; }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                return false;
            }
        }

        public static CookieRow From(CoreWebView2Cookie c)
        {
            return new CookieRow { Domain = c.Domain, Path = c.Path, Name = c.Name, Value = c.Value, Secure = c.IsSecure, HttpOnly = c.IsHttpOnly,
                                   Expires = c.IsSession ? 0 : (long)Math.Max(0, (c.Expires.ToUniversalTime() - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds) };
        }
    }

    // ログインの小窓。済めば cookie を書いて自分で閉じる(Ok = true)。× で閉じれば何も書かない
    public sealed class LoginForm : Form
    {
        readonly string friendDir;
        readonly WebView2 view = new WebView2 { Dock = DockStyle.Fill };
        CoreWebView2Environment env;
        bool saving;
        public bool Ok;
        public string Message = "ログインを途中でやめました";

        public LoginForm(string friendDir, Icon icon)
        {
            this.friendDir = friendDir;
            Text = "YouTube にログイン";
            Icon = icon;
            Size = new Size(560, 800);
            MinimumSize = new Size(420, 560);
            StartPosition = FormStartPosition.CenterParent;
            var t = Theme.Current;
            var note = new Label
            {
                Dock = DockStyle.Top, AutoSize = false, Height = 64, Padding = new Padding(12, 8, 12, 6), Font = new Font("Yu Gothic UI", 9.5f),
                Text = "メインではなく、サブの Google アカウントでログインしてください。済むと自動で閉じます。\r\n" +
                       "ログインの情報はこの PC の中だけに置き、外へは出しません。",
                BackColor = t != null ? t.Panel : SystemColors.Control, ForeColor = t != null ? t.Text : SystemColors.ControlText
            };
            Controls.Add(view);
            Controls.Add(note);
            Load += async delegate
            {
                try
                {
                    YtCookies.DeleteProfile(friendDir);   // 前の回の残り(生きたセッション)を使わない
                    env = await CoreWebView2Environment.CreateAsync(null, YtCookies.ProfileDir(friendDir), new CoreWebView2EnvironmentOptions("--disable-features=msSmartScreenProtection"));
                    env.BrowserProcessExited += delegate { ThreadPool.QueueUserWorkItem(delegate { YtCookies.DeleteProfile(friendDir); }); };
                    await view.EnsureCoreWebView2Async(env);
                    if (Theme.Current != null) Theme.Current.ApplyCaption(Handle);
                    var core = view.CoreWebView2;
                    var st = core.Settings;
                    st.AreDevToolsEnabled = false;
                    st.IsStatusBarEnabled = false;
                    st.IsGeneralAutofillEnabled = false;
                    st.IsPasswordAutosaveEnabled = false;
                    if (MainForm.Quiet) core.IsMuted = true;
                    core.NavigationStarting += (s, e) =>
                    {
                        Uri u;
                        if (e.Uri == "about:blank" || (Uri.TryCreate(e.Uri, UriKind.Absolute, out u) && u.Scheme == "https")) return;
                        e.Cancel = true;   // https のほかは開かない
                    };
                    core.NewWindowRequested += (s, e) =>
                    {
                        e.Handled = true;   // ログインの途中の別の窓(説明など)は同じ窓で
                        Uri u;
                        if (Uri.TryCreate(e.Uri, UriKind.Absolute, out u) && u.Scheme == "https") core.Navigate(u.AbsoluteUri);
                    };
                    core.NavigationCompleted += OnCompleted;
                    core.Navigate(YtCookies.LoginUrl);
                }
                catch (Exception ex)
                {
                    Log.Write("ログインの窓を開けませんでした: " + ex.GetType().Name + " " + ex.Message);
                    Message = "ログインの窓を開けませんでした";
                    Close();
                }
            };
        }

        async void OnCompleted(object sender, CoreWebView2NavigationCompletedEventArgs e)
        {
            if (saving || view.CoreWebView2 == null) return;
            var core = view.CoreWebView2;
            string src = core.Source;
            if (!YtCookies.IsYouTube(src)) return;
            try
            {
                var yt = await core.CookieManager.GetCookiesAsync("https://www.youtube.com");
                if (!YtCookies.LoggedIn(yt.Select(c => c.Name))) return;
                if (!YtCookies.IsRobots(src))
                {
                    core.Navigate(YtCookies.RobotsUrl);   // 静かなページへ移ってから書き出す(普通のページは開くたびに cookie を回す)
                    return;
                }
                saving = true;
                var rows = new List<CookieRow>();
                foreach (string url in YtCookies.ReadFrom)
                    foreach (var c in await core.CookieManager.GetCookiesAsync(url)) rows.Add(YtCookies.From(c));
                int n = YtCookies.Save(friendDir, rows);
                Log.Write("YouTube のログイン: cookie を書きました(" + n + " 件)");
                Ok = true;
                Message = "YouTube にログインしました";
                Close();
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException || ex is InvalidOperationException || ex is System.Runtime.InteropServices.COMException)) throw;
                saving = false;
                Log.Write("YouTube のログインを書けませんでした: " + ex.GetType().Name);
                Message = "ログインの情報を書けませんでした。もう一度試してください";
            }
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (keyData == Keys.Escape) { Close(); return true; }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            base.OnFormClosed(e);
            view.Dispose();   // ブラウザの処理が終わると BrowserProcessExited でプロファイルを消す(消せなければ次に開く前・次の起動で)
        }
    }
}
