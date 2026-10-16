// 起動役 FriendInbox.exe の本体: 玄関(Python の src\friendapp\server.py)を版を選んで起こし、見回り、止める。C# 5 で書く
//   FriendInbox.exe   … 玄関を起こす。もう動いていれば玄関が窓を開き直すだけ(自分は終わる)。窓が閉じて仕事も無ければ止めて終わる
// 手元の記録: <home>\data\app\friendapp\logs\launcher.log(../common/Log.cs。数百 KB で切る)
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using FriendApps;

namespace FriendInbox
{
    // 起こした玄関 1 つ
    public sealed class Gateway
    {
        public const int LockBusyExit = 4;   // 同じ作業データを別の処理が使っている(版のせいではない)
        public Process Proc;
        public int Port;
        public bool Ready, Already;
        public int ExitCode = -1;
        readonly ManualResetEvent readyEvt = new ManualResetEvent(false), exitEvt = new ManualResetEvent(false);

        public bool Alive
        {
            get { try { return Proc != null && !Proc.HasExited; } catch (InvalidOperationException) { return false; } }
        }

        // 標準出力の 1 行 JSON {"event":"ready","port":…} / {"event":"already","port":…}
        public void OnLine(string line)
        {
            IDictionary<string, object> j;
            try { j = Json.Parse(line); }
            catch (Exception ex)
            {
                if (!(ex is FormatException || ex is ArgumentException || ex is InvalidOperationException)) throw;
                return;
            }
            string ev = Json.Str(j, "event");
            if (ev == "ready") { Port = Json.Int(j, "port", 0); Ready = Port > 0; if (Ready) readyEvt.Set(); }
            else if (ev == "already") { Port = Json.Int(j, "port", 0); Already = true; }
        }

        // 玄関を起こして ready を waitSec 秒待つ。結果は Ready(動いている)・Already(もう動いていた)・それ以外は起動できない(ExitCode)
        public static Gateway Start(Layout l, string home, string token, string rollback, int waitSec, Action<string> log)
        {
            var g = new Gateway();
            var psi = new ProcessStartInfo(l.Python, "-X utf8 \"" + l.Script + "\"")
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8, WorkingDirectory = home
            };
            psi.EnvironmentVariables["YTT_FRIEND_HOME"] = home;
            psi.EnvironmentVariables["YTT_FRIEND_TOKEN"] = token;
            psi.EnvironmentVariables["YTT_FRIEND_LAUNCHER"] = "1";
            if (rollback != null) psi.EnvironmentVariables["YTT_FRIEND_ROLLBACK"] = rollback; else psi.EnvironmentVariables.Remove("YTT_FRIEND_ROLLBACK");
            g.Proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            g.Proc.OutputDataReceived += (s, e) => { if (e.Data != null) { log("玄関: " + e.Data); g.OnLine(e.Data); } };
            g.Proc.ErrorDataReceived += (s, e) => { if (e.Data != null) log("玄関(エラー): " + e.Data); };
            g.Proc.Exited += (s, e) => g.exitEvt.Set();
            log("起こします: " + (l.Version ?? "(app-版なしの形)") + " " + l.Script);
            g.Proc.Start();
            g.Proc.BeginOutputReadLine();
            g.Proc.BeginErrorReadLine();
            int w = WaitHandle.WaitAny(new WaitHandle[] { g.readyEvt, g.exitEvt }, waitSec * 1000);
            if (w == 1)
            {
                g.Proc.WaitForExit();   // 標準出力を読み切ってから(already の行を取りこぼさない)
                g.ExitCode = g.Proc.ExitCode;
            }
            else if (w == WaitHandle.WaitTimeout) log("ready が " + waitSec + " 秒来ませんでした");
            if (g.Ready && !g.Alive) g.Ready = false;
            return g;
        }

        // 子の ffmpeg なども含めて強制で終わらせる
        public void Kill()
        {
            if (!Alive) return;
            try
            {
                var p = Process.Start(new ProcessStartInfo("taskkill", "/T /F /PID " + Proc.Id) { UseShellExecute = false, CreateNoWindow = true });
                p.WaitForExit(10000);
            }
            catch (Exception ex)
            {
                if (!(ex is System.ComponentModel.Win32Exception || ex is InvalidOperationException)) throw;
            }
        }
    }

    // 玄関への問い合わせ(127.0.0.1 だけ・合言葉つき)
    public static class Http
    {
        public static string Call(string method, int port, string path, string token, int timeoutMs)
        {
            var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + path);
            req.Method = method;
            req.Proxy = null;
            req.KeepAlive = false;
            req.Timeout = timeoutMs;
            req.ReadWriteTimeout = timeoutMs;
            req.Headers["X-YTT-Token"] = token;
            if (method == "POST")
            {
                req.ContentType = "application/json";
                byte[] body = Encoding.UTF8.GetBytes("{}");
                req.ContentLength = body.Length;
                using (var s = req.GetRequestStream()) s.Write(body, 0, body.Length);
            }
            using (var res = (HttpWebResponse)req.GetResponse())
            using (var rd = new StreamReader(res.GetResponseStream(), Encoding.UTF8))
                return rd.ReadToEnd();
        }
    }

    // 玄関の見回り(2 秒ごと)と止める。画面は StatusForm
    public sealed class Supervisor : ApplicationContext
    {
        const int PollMs = 2000, StopWaitMs = 10000;
        readonly Gateway gw;
        readonly string token;
        readonly StatusForm form;
        int stopping;
        volatile bool shown;
        volatile int recording;

        public Supervisor(Gateway gw, string token)
        {
            this.gw = gw;
            this.token = token;
            form = new StatusForm(OpenWindow, StopNow);
            IntPtr h = form.Handle;   // 見回りの糸から BeginInvoke できるよう、ハンドルだけ先に作る(窓は出さない)
            new Thread(Loop) { IsBackground = true, Name = "friend-watch" }.Start();
        }

        void Loop()
        {
            int fails = 0;
            while (stopping == 0)
            {
                if (!gw.Alive) { Log.Write("玄関が先に終わったので、起動役も終わります"); Quit(); return; }
                try
                {
                    var st = FriendState.Parse(Http.Call("GET", gw.Port, "/api/friend/state", token, 3000));
                    fails = 0;
                    recording = st.Recording;
                    var step = Watch.Decide(st, shown);
                    if (step == Step.Shutdown) { Log.Write("窓が閉じていて仕事も無いので止めます"); StopNow(); return; }
                    if (step == Step.ShowStatus) shown = true;
                    if (step == Step.HideStatus) shown = false;
                    Ui(() => { if (shown) form.ShowStatus(st); else form.HideStatus(); });
                }
                catch (Exception ex)
                {
                    if (!(ex is WebException || ex is IOException || ex is FormatException || ex is ArgumentException || ex is InvalidOperationException)) throw;
                    if (++fails <= 3) Log.Write("見回りに失敗: " + ex.Message);
                }
                gw.Proc.WaitForExit(PollMs);   // 玄関が終わればすぐ戻る
            }
        }

        void Ui(Action a)
        {
            try { form.BeginInvoke(a); }
            catch (InvalidOperationException) { }   // 窓がもう無い(終わるところ)
        }

        void OpenWindow()
        {
            ThreadPool.QueueUserWorkItem(delegate
            {
                try { Http.Call("POST", gw.Port, "/api/friend/window", token, 5000); }
                catch (Exception ex)
                {
                    if (!(ex is WebException || ex is IOException || ex is InvalidOperationException)) throw;
                    Log.Write("窓を開けませんでした: " + ex.Message);
                }
            });
        }

        // 確認なしで今すぐ止める: shutdown → 10 秒待つ → 終わらなければ taskkill /T /F。そのあと自分も終わる
        void StopNow()
        {
            if (Interlocked.Exchange(ref stopping, 1) != 0) return;
            ThreadPool.QueueUserWorkItem(delegate
            {
                try { Http.Call("POST", gw.Port, "/api/shutdown", token, 3000); }
                catch (Exception ex)
                {
                    if (!(ex is WebException || ex is IOException || ex is InvalidOperationException)) throw;
                    Log.Write("shutdown を送れませんでした: " + ex.Message);
                }
                if (!gw.Proc.WaitForExit(StopWaitMs))
                {
                    Log.Write("10 秒たっても終わらないので強制で止めます");
                    gw.Kill();
                }
                Quit();
            });
        }

        void Quit()
        {
            Ui(() => { form.AllowClose(); form.Close(); ExitThread(); });
        }
    }

    static class Program
    {
        const string MutexName = "Local\\YttFriendInbox";
        const int ReadySeconds = 90;

        [STAThread]
        static int Main()
        {
            string home = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
            Log.Init(Path.Combine(home, "data", "app", "friendapp", "logs"), "launcher.log");
            bool created;
            using (var mutex = new Mutex(true, MutexName, out created))
            {
                try
                {
                    return created ? RunFirst(home) : RunSecond(home);
                }
                finally
                {
                    if (created) mutex.ReleaseMutex();
                }
            }
        }

        static string NewToken()
        {
            var b = new byte[24];
            using (var r = new RNGCryptoServiceProvider()) r.GetBytes(b);
            return BitConverter.ToString(b).Replace("-", "").ToLowerInvariant();
        }

        static void Fail(string msg)
        {
            Log.Write(msg);
            MessageBox.Show(msg + "\r\n(記録: data\\app\\friendapp\\logs\\launcher.log)", "受信箱", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        // 2 つ目: 玄関を起こすだけ(玄関が「もう動いている」で窓を開き直して終わる)
        static int RunSecond(string home)
        {
            var layout = Versions.Pick(home, Versions.Read(home).Bad);
            if (layout == null) { Fail("アプリの部品(python と src)が見つかりません"); return 1; }
            var g = Gateway.Start(layout, home, NewToken(), null, 30, Log.Write);
            if (g.Ready) { Log.Write("2 つ目の起動役が玄関を起こしてしまったので止めます"); g.Kill(); return 1; }
            return 0;
        }

        static int RunFirst(string home)
        {
            var rec = Versions.Read(home);
            string token = NewToken(), rolledFrom = null;
            Gateway gw;
            Layout used;
            while (true)
            {
                used = Versions.Pick(home, rec.Bad);
                if (used == null) { Fail("起動できる版がありません(python と src が見つかりません)"); return 1; }
                gw = Gateway.Start(used, home, token, rolledFrom, ReadySeconds, Log.Write);
                if (gw.Ready || gw.Already) break;
                gw.Kill();
                if (gw.ExitCode == Gateway.LockBusyExit) { Fail("ほかの処理が同じ作業データを使っています。閉じてから開き直してください"); return 1; }
                if (used.Version == null) { Fail("受信箱を起動できませんでした"); return 1; }
                Log.Write("版 " + used.Version + " を起動できませんでした(終了コード " + gw.ExitCode + ")。前の版で起こし直します");
                rec.Bad.Add(used.Version);
                rolledFrom = used.Version;
                SaveQuietly(home, rec);
            }
            if (gw.Already) return 0;
            if (used.Version != null)
            {
                Versions.MarkStarted(rec, used.Version);
                SaveQuietly(home, rec);
                try { Versions.Prune(home, rec, Log.Write); } catch (Exception ex) { Log.Write("古い版の片付けに失敗: " + ex.Message); }
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new Supervisor(gw, token));
            return 0;
        }

        static void SaveQuietly(string home, VersionRecord rec)
        {
            try { Versions.Write(home, rec); }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                Log.Write("app-versions.json を書けませんでした: " + ex.Message);
            }
        }
    }
}
