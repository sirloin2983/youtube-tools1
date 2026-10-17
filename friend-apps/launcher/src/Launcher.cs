// FriendApp.exe の起こし方: 窓 1 枚(MainForm = WebView2)を持ち、Python(src\friendapp\server.py)を子としてジョブオブジェクトで起こす。C# 5 で書く
//   notes:plan/f1-friend-requirements.md の C-1-1・C-1-3・C-5-3。窓と画面の境目は friend-apps/launcher/README.txt
//   - 1 つだけ起動(アプリのフォルダごとの名前つき Mutex)。2 つ目は 1 つ目の窓を前に出して終わる
//   - 番号はその都度空いている物を選んで --port で渡す(Python はずらさない)。録画の部品の番号も選んで YTT_FRIEND_REC_PORT で渡す
//   - 合言葉は exe が作って YTT_FRIEND_TOKEN で渡し、WebView2 が要求ごとに X-YTT-Token を足す(画面の meta に頼らない)
//   - ジョブオブジェクト(閉じたら全部止める)= exe が落ちても Python と孫(ffmpeg・whisper.cpp・録画の部品)が残らない
// 手元の記録: <home>\data\app\friendapp\logs\launcher.log(../common/Log.cs。数百 KB で切る)
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using FriendApps;

namespace FriendInbox
{
    // 閉じたら中の処理を全部止めるジョブ(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE。BREAKAWAY_OK は付けない = 孫も外へ出られない)
    public sealed class Job : IDisposable
    {
        IntPtr handle;

        public Job()
        {
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new Win32Exception();
            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = 0x2000;
            int len = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            if (!SetInformationJobObject(handle, 9, ref info, (uint)len)) throw new Win32Exception();
        }

        public void Add(Process p)
        {
            if (!AssignProcessToJobObject(handle, p.Handle)) throw new Win32Exception();
        }

        public void Kill()
        {
            if (handle != IntPtr.Zero) TerminateJobObject(handle, 1);
        }

        public void Dispose()
        {
            if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct IO_COUNTERS
        {
            public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount, ReadTransferCount, WriteTransferCount, OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr CreateJobObject(IntPtr attrs, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint len);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool TerminateJobObject(IntPtr job, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr h);
    }

    // 起こした Python 1 つ
    public sealed class Gateway
    {
        public const int LockBusyExit = 4;   // 同じ作業データを別の処理が使っている(版のせいではない)
        public const int PortBusyExit = 5;   // 渡した番号を使えなかった(別の番号で起こし直す)
        public Process Proc;
        public int Port, RecPort;
        public bool Ready, Bye;   // Bye = Python が「止めてと言われて終わる」と言った(起こし直さない)
        public int ExitCode = -1;
        readonly ManualResetEvent readyEvt = new ManualResetEvent(false), exitEvt = new ManualResetEvent(false);

        public bool Alive
        {
            get { try { return Proc != null && !Proc.HasExited; } catch (InvalidOperationException) { return false; } }
        }

        // 標準出力の 1 行 JSON {"event":"ready","port":…} / {"event":"bye"}
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
            if (ev == "ready" && Json.Int(j, "port", 0) == Port) { Ready = true; readyEvt.Set(); }
            else if (ev == "bye") Bye = true;
        }

        // 空いている番号(127.0.0.1 で 0 番を開いて OS に選ばせ、すぐ閉じる)
        public static int FreePort()
        {
            var l = new TcpListener(IPAddress.Loopback, 0);
            l.Start();
            try { return ((IPEndPoint)l.LocalEndpoint).Port; }
            finally { l.Stop(); }
        }

        // Python を起こして ready を waitSec 秒待つ。tokenInPage = WebView2 が無く Edge の窓で開く(画面の meta に本物の合言葉を入れる)
        public static Gateway Start(Layout l, string home, string token, string rollback, bool tokenInPage, Job job, int waitSec, Action<string> log)
        {
            var g = new Gateway { Port = FreePort(), RecPort = FreePort() };
            if (g.RecPort == g.Port) g.RecPort = FreePort();
            var psi = new ProcessStartInfo(l.Python, "-X utf8 \"" + l.Script + "\" --port " + g.Port + " --no-open")
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8, WorkingDirectory = home
            };
            var env = psi.EnvironmentVariables;
            env["YTT_FRIEND_HOME"] = home;
            env["YTT_FRIEND_TOKEN"] = token;
            env["YTT_FRIEND_LAUNCHER"] = "1";   // 更新を受けるのは exe から動いているときだけ(friendapp/sync.py)
            env["YTT_FRIEND_HOST"] = tokenInPage ? "edge" : "webview2";
            env["YTT_FRIEND_REC_PORT"] = g.RecPort.ToString();
            if (rollback != null) env["YTT_FRIEND_ROLLBACK"] = rollback; else env.Remove("YTT_FRIEND_ROLLBACK");
            g.Proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            g.Proc.OutputDataReceived += (s, e) => { if (e.Data != null) { log("Python: " + e.Data); g.OnLine(e.Data); } };
            g.Proc.ErrorDataReceived += (s, e) => { if (e.Data != null) log("Python(エラー): " + e.Data); };
            g.Proc.Exited += (s, e) => g.exitEvt.Set();
            log("起こします: " + (l.Version ?? "(app-版なしの形)") + " " + l.Script + " 番号 " + g.Port + "・録画 " + g.RecPort);
            g.Proc.Start();
            try { job.Add(g.Proc); }
            catch (Win32Exception ex) { log("ジョブに入れられませんでした(閉じるときは止める口で止めます): " + ex.Message); }
            g.Proc.BeginOutputReadLine();
            g.Proc.BeginErrorReadLine();
            int w = WaitHandle.WaitAny(new WaitHandle[] { g.readyEvt, g.exitEvt }, waitSec * 1000);
            if (w == 1)
            {
                g.Proc.WaitForExit();   // 標準出力を読み切ってから
                g.ExitCode = g.Proc.ExitCode;
            }
            else if (w == WaitHandle.WaitTimeout) log("ready が " + waitSec + " 秒来ませんでした");
            if (g.Ready && !g.Alive) g.Ready = false;
            return g;
        }

        public void Kill()
        {
            if (!Alive) return;
            try { Proc.Kill(); Proc.WaitForExit(5000); }
            catch (Exception ex)
            {
                if (!(ex is Win32Exception || ex is InvalidOperationException)) throw;
            }
        }
    }

    // Python への問い合わせ(127.0.0.1 だけ・合言葉つき)
    public static class Http
    {
        public static string Call(string method, int port, string path, string token, int timeoutMs, string body = null)
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
                req.Headers["Origin"] = "http://127.0.0.1:" + port;
                byte[] b = Encoding.UTF8.GetBytes(body ?? "{}");
                req.ContentLength = b.Length;
                using (var s = req.GetRequestStream()) s.Write(b, 0, b.Length);
            }
            using (var res = (HttpWebResponse)req.GetResponse())
            using (var rd = new StreamReader(res.GetResponseStream(), Encoding.UTF8))
                return rd.ReadToEnd();
        }

        // 失敗の答え(4xx)の中身も返す(画面へそのまま渡す)。つながらなければ null
        public static string CallKeepError(string method, int port, string path, string token, int timeoutMs, string body, out int status)
        {
            status = 0;
            try
            {
                string s = Call(method, port, path, token, timeoutMs, body);
                status = 200;
                return s;
            }
            catch (WebException ex)
            {
                var res = ex.Response as HttpWebResponse;
                if (res == null) return null;
                status = (int)res.StatusCode;
                using (var rd = new StreamReader(res.GetResponseStream(), Encoding.UTF8)) return rd.ReadToEnd();
            }
        }
    }

    // Python を起こし・起こし直し・止める係(窓とは別。MainForm が持つ)
    public sealed class Backend
    {
        const int ReadySeconds = 90, StopWaitMs = 10000;
        readonly string home;
        readonly bool tokenInPage;
        readonly Job job = new Job();
        public readonly string Token = NewToken();
        public Gateway Gw;
        public string RolledFrom;
        public volatile bool Stopping;
        readonly List<DateTime> restarts = new List<DateTime>();

        public Backend(string home, bool tokenInPage)
        {
            this.home = home;
            this.tokenInPage = tokenInPage;
        }

        public int Port { get { var g = Gw; return g != null ? g.Port : 0; } }

        static string NewToken()
        {
            var b = new byte[24];
            using (var r = new RNGCryptoServiceProvider()) r.GetBytes(b);
            return BitConverter.ToString(b).Replace("-", "").ToLowerInvariant();
        }

        // 版を選んで起こす(起動できない版は bad に足して前の版へ)。起こせなければ理由の文を返す(null = 起きた)
        public string StartFirst()
        {
            var rec = Versions.Read(home);
            Layout used;
            bool skipLegacy = false;
            while (true)
            {
                used = Versions.Pick(home, rec.Bad, skipLegacy);
                if (used == null) return "起動できる版がありません(python と src が見つかりません)";
                var g = StartOn(used, RolledFrom);
                if (g == null) return "受信箱を起動できませんでした(番号を 3 回選び直しても使えませんでした)";
                if (g.Ready) { Gw = g; break; }
                g.Kill();
                if (g.ExitCode == Gateway.LockBusyExit) return "ほかの処理が同じ作業データを使っています。閉じてから開き直してください";
                if (used.Version == null)   // 前の形が起動できない: 版のフォルダがあればそちらで(無ければ止める)
                {
                    if (skipLegacy || Versions.Pick(home, rec.Bad, true) == null) return "起動できませんでした(終了コード " + g.ExitCode + ")";
                    Log.Write("前の形(src・python)を起動できませんでした(終了コード " + g.ExitCode + ")。版のフォルダで起こし直します");
                    skipLegacy = true;
                    continue;
                }
                Log.Write("版 " + used.Version + " を起動できませんでした(終了コード " + g.ExitCode + ")。前の版で起こし直します");
                rec.Bad.Add(used.Version);
                RolledFrom = used.Version;
                SaveQuietly(rec);
            }
            if (used.Version != null)
            {
                Versions.MarkStarted(rec, used.Version);
                SaveQuietly(rec);
                try { Versions.Prune(home, rec, Log.Write); } catch (Exception ex) { Log.Write("古い版の片付けに失敗: " + ex.Message); }
            }
            return null;
        }

        // 番号が取られていたら(終了コード 5)別の番号で 3 回まで
        Gateway StartOn(Layout l, string rollback)
        {
            for (int i = 0; i < 3; i++)
            {
                var g = Gateway.Start(l, home, Token, rollback, tokenInPage, job, ReadySeconds, Log.Write);
                if (g.ExitCode != Gateway.PortBusyExit) return g;
                Log.Write("番号 " + g.Port + " を使えなかったので選び直します");
            }
            return null;
        }

        // 動いている途中で Python が終わった: 10 分に 3 回まで起こし直す(番号は選び直す)。-> 起こせたか
        public bool Restart()
        {
            if (!Rules.ShouldRestart(restarts, DateTime.Now, Stopping)) return false;
            restarts.Add(DateTime.Now);
            var l = Versions.Pick(home, Versions.Read(home).Bad);
            if (l == null) return false;
            var g = StartOn(l, null);
            if (g == null || !g.Ready) { if (g != null) g.Kill(); return false; }
            Gw = g;
            Log.Write("Python を起こし直しました(番号 " + g.Port + ")");
            return true;
        }

        public HostState State()
        {
            var g = Gw;
            if (g == null || !g.Alive) return null;
            try { return HostState.Parse(Http.Call("GET", g.Port, "/api/friend/state", Token, 3000)); }
            catch (Exception ex)
            {
                if (!(ex is WebException || ex is IOException || ex is FormatException || ex is ArgumentException || ex is InvalidOperationException)) throw;
                return null;
            }
        }

        // 確認なしで止める: shutdown → 10 秒待つ → 終わらなければジョブごと
        public void Stop()
        {
            Stopping = true;
            var g = Gw;
            if (g != null && g.Alive)
            {
                try { Http.Call("POST", g.Port, "/api/shutdown", Token, 3000); }
                catch (Exception ex)
                {
                    if (!(ex is WebException || ex is IOException || ex is InvalidOperationException)) throw;
                    Log.Write("shutdown を送れませんでした: " + ex.Message);
                }
                if (!g.Proc.WaitForExit(StopWaitMs)) Log.Write("10 秒たっても終わらないので、ジョブごと止めます");
            }
            job.Kill();
            job.Dispose();
        }

        void SaveQuietly(VersionRecord rec)
        {
            try { Versions.Write(home, rec); }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                Log.Write("app-versions.json を書けませんでした: " + ex.Message);
            }
        }
    }

    static class Program
    {
        // アプリのフォルダごとの名前(別の場所の同じアプリを黙って止めない = C-0)
        static string InstanceName(string home)
        {
            using (var sha = SHA1.Create())
            {
                var h = sha.ComputeHash(Encoding.UTF8.GetBytes(home.ToLowerInvariant()));
                return "Local\\YttFriendApp-" + BitConverter.ToString(h, 0, 8).Replace("-", "");
            }
        }

        static int Restart(string home)
        {
            try
            {
                Thread.Sleep(1500);   // 前の窓の WebView2 の処理が終わるのを少し待つ(同じ置き場所を新しい窓が使う)
                Process.Start(new ProcessStartInfo(Path.Combine(home, "FriendApp.exe")) { UseShellExecute = false, WorkingDirectory = home });
                Log.Write("新しい版で開き直しました");
            }
            catch (Exception ex)
            {
                if (!(ex is Win32Exception || ex is InvalidOperationException || ex is FileNotFoundException)) throw;
                Log.Write("新しい版で開き直せませんでした: " + ex.Message);
            }
            return 0;
        }

        public static void Fail(string msg)
        {
            Log.Write(msg);
            if (Environment.GetEnvironmentVariable("YTT_FRIEND_NOACTIVATE") == "1" || Environment.GetEnvironmentVariable("YTT_FRIEND_SHOTS") != null) return;   // 確かめ・写真のとき: 窓と音を出さない(記録だけ。MainForm の型を読まない)
            MessageBox.Show(msg + "\r\n(記録: data\\app\\friendapp\\logs\\launcher.log)", Rules.AppTitle, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        // [更新する] で入れ替えたあと、Mutex を放してから新しい exe を起こす(放す前に起こすと「2 つ目」で終わってしまう)
        public static volatile bool RestartAfterExit;

        [STAThread]
        static int Main()
        {
            string home = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
            Log.Init(Path.Combine(home, "data", "app", "friendapp", "logs"), "launcher.log");
            string self = Process.GetCurrentProcess().MainModule.FileName;
            string main = Path.Combine(home, "FriendApp.exe");
            if (Updater.IsHandoffName(self) && File.Exists(main))   // 前のアプリの名前で起こされた(移る最後の 1 回の写し・前のショートカット)= 新しいアプリを起こして終わる
            {
                Log.Write("RequestSender.exe として起こされたので FriendApp.exe を起こします");
                Process.Start(new ProcessStartInfo(main) { UseShellExecute = false, WorkingDirectory = home });
                return 0;
            }
            string name = InstanceName(home);
            bool created;
            using (var mutex = new Mutex(true, name, out created))
            using (var show = new EventWaitHandle(false, EventResetMode.AutoReset, name + "-show"))
            {
                if (!created)   // 2 つ目: 1 つ目の窓を前に出して終わる
                {
                    show.Set();
                    return 0;
                }
                try
                {
                    int cleaned = Updater.CleanOld(home);   // 前の [更新する] で残った *.old
                    if (cleaned > 0) Log.Write("前の版の exe と部品を片付けました(" + cleaned + " 個)");
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    bool webview = MainForm.WebViewAvailable();
                    if (!webview) Log.Write("WebView2 の部品がないので、Edge の窓で開きます");
                    var be = new Backend(home, !webview);
                    string err = be.StartFirst();
                    if (err != null) { Fail(err); be.Stop(); return 1; }
                    using (var form = new MainForm(home, be, webview, show)) Application.Run(form);
                }
                finally
                {
                    mutex.ReleaseMutex();
                }
            }
            if (RestartAfterExit) Restart(home);   // Mutex を閉じたあと(using の外)
            return 0;
        }
    }
}
