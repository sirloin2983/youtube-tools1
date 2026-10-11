// この PC で処理する ② + ①(Python の入口 src/app/server.py --headless)を子プロセスとして起こし・つなぎ・止める(F1 の F3a。設計 docs/design/f1-build.md の 1-2・3 の (f1i)(f1j))。
//   起こし方: <app>\python\python.exe <app>\src\app\server.py --headless --port 0 --parent-pid <このアプリの pid>
//             標準出力の最初の 1 行 {"event":"ready","port","token","pid"} でポートと合言葉を受ける。標準エラーは <作業データ>\app\logs\headless-stderr.log へ
//             終了コード 3 = もう入口が動いている → その入口(作業データの根の .flow.lock のポート・合言葉は画面の HTML の meta)に頼む(止めない)
//   止め方:   POST /api/shutdown(待ちは ② が残す = 次の起動で続きから)→ 終わらなければ標準入力を閉じる(② の EOF の見張り)→ 5 秒待って kill
//   口:       POST /api/flow/submit {envelope, spec} / GET /api/flow/status(合言葉 X-YTT-Token。127.0.0.1 だけ・プロキシを通さない)
// Python・src が見つからない(今までの zip の形)ときは Locate が null = アプリは今までどおり Dropbox の道だけで動く。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using FriendApps;

namespace RequestSender
{
    // アプリのフォルダからの相対(配布の形 = f1-build.md の 3 (f1i)): python\python.exe・src\app\server.py・tools\*
    public class BackendPaths
    {
        public string Python, Src, Tools;

        public string Server { get { return Path.Combine(Src, "app", "server.py"); } }

        // 両方そろっていれば場所を返す。どちらか無ければ null(= この PC では処理しない。Dropbox の道だけ)
        public static BackendPaths Locate(string appDir)
        {
            if (string.IsNullOrEmpty(appDir)) return null;
            var p = new BackendPaths
            {
                Python = Path.Combine(appDir, "python", "python.exe"),
                Src = Path.Combine(appDir, "src"),
                Tools = Path.Combine(appDir, "tools"),
            };
            return File.Exists(p.Python) && File.Exists(p.Server) ? p : null;
        }
    }

    // ② の HTTP の返事(Status = HTTP の番号・0 = つながらなかった)
    public class FlowReply
    {
        public int Status;
        public IDictionary<string, object> Body = new Dictionary<string, object>();
        public string Error;   // つながらなかったときの理由

        public bool Ok { get { return Status == 200; } }
        public string Code { get { return Json.Str(Body, "error") ?? ""; } }
        public string Message { get { return Json.Str(Body, "message") ?? Error ?? ("HTTP " + Status); } }
    }

    // ② に頼む口(テストは偽物を渡す)
    public interface IFlowClient
    {
        FlowReply Get(string path);
        FlowReply Post(string path, object body);
    }

    public class BackendException : Exception
    {
        public BackendException(string message) : base(message) { }
    }

    public class Backend : IFlowClient
    {
        public const int ExitRunning = 3;              // server.py の EXIT_RUNNING(もう入口が動いている)
        public const string ReadyEvent = "ready";      // server.py の HEADLESS_READY
        public const string LockName = ".flow.lock";   // flow/placement.py の LOCK_NAME
        public const long StderrMax = 4L * 1024 * 1024; // 標準エラーの記録はこれを超えたら頭から書き直す
        static readonly Regex TokenRx = new Regex("<meta\\s+name=\"ytt-token\"\\s+content=\"([A-Za-z0-9_-]{1,200})\"\\s*/?>");

        readonly BackendPaths paths;
        readonly string dataRoot;
        readonly object gate = new object();        // 状態(ポート・合言葉・子)を読み書きする間だけ
        readonly object startGate = new object();   // 起こす・止めるを 1 つずつ(ready を待つ間も状態は読める = 画面を固めない)
        Process proc;
        StreamWriter errLog;
        public int ReadyTimeoutMs = 180 * 1000;   // 初めての起動は部品の取り込みに時間がかかる
        public int ShutdownWaitMs = 15 * 1000, StdinWaitMs = 5 * 1000;
        public bool UseParentPid = true;          // --parent-pid(F0-1 が ② に作る口。古い ② には渡せない)
        public Action<string> Log = s => { };

        public int Port { get; private set; }
        public string Token { get; private set; }
        public bool Owned { get; private set; }    // 自分が起こした ②(閉じるときに止める)。false = ほかの入口に頼んでいる
        public bool Ready { get { return Port > 0 && Token != null; } }
        public string LastProblem { get; private set; }

        public Backend(BackendPaths paths, string dataRoot)
        {
            this.paths = paths;
            this.dataRoot = dataRoot ?? DefaultDataRoot();
        }

        public string DataRoot { get { return dataRoot; } }

        // ② の作業データの根(ytt/datadir.py の data_root と同じ規則: YTT_DATA_DIR > %LOCALAPPDATA%\youtube-tools)
        public static string DefaultDataRoot()
        {
            string d = (Environment.GetEnvironmentVariable("YTT_DATA_DIR") ?? "").Trim();
            if (d.Length > 0 && !d.Equals("inplace", StringComparison.OrdinalIgnoreCase)) return Path.GetFullPath(d);
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "youtube-tools");
        }

        // 起動の引数(テストが形を確かめる)
        public static string Arguments(string serverPy, int parentPid, bool useParentPid)
        {
            return Quote(serverPy) + " --headless --port 0" + (useParentPid ? " --parent-pid " + parentPid : "");
        }

        static string Quote(string s)
        {
            return "\"" + (s ?? "").Replace("\"", "\\\"") + "\"";
        }

        // ready の 1 行 → (port, token)。違う行・壊れた行は false
        public static bool ParseReady(string line, out int port, out string token)
        {
            port = 0;
            token = null;
            if (string.IsNullOrWhiteSpace(line) || !line.TrimStart().StartsWith("{")) return false;
            IDictionary<string, object> d;
            try { d = Json.Parse(line); }
            catch (Exception) { return false; }
            if (Json.Str(d, "event") != ReadyEvent) return false;
            port = Json.Int(d, "port", 0);
            token = Json.Str(d, "token");
            return port > 0 && port < 65536 && !string.IsNullOrEmpty(token);
        }

        // .flow.lock の持ち主のポート(無い・壊れている・ポートなし = 0)
        public static int LockPort(string lockPath)
        {
            var d = Json.ReadFileOrNull(lockPath);
            int p = Json.Int(d, "port", 0);
            return p > 0 && p < 65536 ? p : 0;
        }

        // 画面の HTML の <meta name="ytt-token"> から合言葉(CLI と同じ受け取り方)。無ければ null
        public static string TokenFromPage(string html)
        {
            var m = TokenRx.Match(html ?? "");
            return m.Success ? m.Groups[1].Value : null;
        }

        // ---------------------------------------------------------------- 起こす
        // まだなら起こして ready を待つ(何度呼んでもよい)。起こせなければ理由つきの BackendException
        public void EnsureStarted()
        {
            lock (startGate)
            {
                if (Running) return;
                lock (gate) { Port = 0; Token = null; }
                try { StartLocked(); LastProblem = null; }
                catch (BackendException ex) { LastProblem = ex.Message; throw; }
            }
        }

        void StartLocked()
        {
            var psi = new ProcessStartInfo(paths.Python, Arguments(paths.Server, Process.GetCurrentProcess().Id, UseParentPid))
            {
                UseShellExecute = false,
                CreateNoWindow = true,   // 黒い窓を出さない
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = new UTF8Encoding(false),
                StandardErrorEncoding = new UTF8Encoding(false),
                WorkingDirectory = paths.Src,
            };
            foreach (var kv in ChildEnv(paths, Environment.GetEnvironmentVariable("PATH"))) psi.EnvironmentVariables[kv.Key] = kv.Value;
            if (!string.IsNullOrEmpty(dataRoot)) psi.EnvironmentVariables["YTT_DATA_DIR"] = dataRoot;
            OpenErrLog();
            var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
            p.ErrorDataReceived += (s, e) => WriteErr(e.Data);
            try { p.Start(); }
            catch (Exception ex) { throw new BackendException("処理の部品(Python)を起動できませんでした: " + ex.Message); }
            p.BeginErrorReadLine();
            Log("backend: started pid " + p.Id);

            // 標準出力の ready の 1 行を、裏の糸で読む(読み終えたあとも読み捨て続ける = ② の書き込みが詰まらない)
            int port = 0;
            string token = null;
            var got = new ManualResetEvent(false);
            var reader = new Thread(() =>
            {
                try
                {
                    string line;
                    while ((line = p.StandardOutput.ReadLine()) != null)
                    {
                        int pp; string tt;
                        if (token == null && ParseReady(line, out pp, out tt)) { port = pp; token = tt; got.Set(); }
                    }
                }
                catch (Exception) { }
                got.Set();
            }) { IsBackground = true, Name = "backend-stdout" };
            reader.Start();
            var sw = Stopwatch.StartNew();
            while (!got.WaitOne(200))
            {
                if (sw.ElapsedMilliseconds > ReadyTimeoutMs)
                {
                    KillQuietly(p);
                    throw new BackendException("処理の部品が準備できませんでした(" + ReadyTimeoutMs / 1000 + " 秒待ちました)。記録: " + ErrLogPath());
                }
            }
            if (token != null)
            {
                lock (gate) { proc = p; Port = port; Token = token; Owned = true; }
                Log("backend: ready port " + port);
                return;
            }
            p.WaitForExit(5000);
            int code = p.HasExited ? p.ExitCode : -1;
            if (code == ExitRunning) { AttachExisting(); return; }
            throw new BackendException("処理の部品が途中で終わりました(終了コード " + code + ")。記録: " + ErrLogPath());
        }

        // もう入口が動いている(終了コード 3): その入口に頼む。止めるのはその入口の持ち主(アプリは止めない)
        void AttachExisting()
        {
            int port = LockPort(Path.Combine(dataRoot, LockName));
            if (port == 0) throw new BackendException("この PC でほかの処理の入口が動いていますが、つなぐ先が分かりませんでした。少し待ってからやり直してください");
            var page = Send("GET", port, "/", null, null, 8000, 2 * 1024 * 1024, true);
            string token = page.Status == 200 ? TokenFromPage(Json.Str(page.Body, "html")) : null;
            if (token == null) throw new BackendException("この PC で動いている処理の入口(ポート " + port + ")に合言葉をもらえませんでした");
            lock (gate) { proc = null; Port = port; Token = token; Owned = false; }
            Log("backend: attached to running portal port " + port);
        }

        // 子の環境変数: 文字コード・PATH に tools\ とその下のフォルダ・見つけた実行ファイルの場所(f1-build.md 1-2)
        public static Dictionary<string, string> ChildEnv(BackendPaths p, string path)
        {
            var env = new Dictionary<string, string> { { "PYTHONIOENCODING", "utf-8" }, { "PYTHONUTF8", "1" } };
            var dirs = new List<string>();
            if (p.Tools != null && Directory.Exists(p.Tools))
            {
                dirs.Add(p.Tools);
                try { dirs.AddRange(Directory.GetDirectories(p.Tools).OrderBy(x => x, StringComparer.OrdinalIgnoreCase)); }
                catch (Exception) { }
                var exes = new[] { new[] { "YTT_FFMPEG", "ffmpeg.exe" }, new[] { "YTT_FFPROBE", "ffprobe.exe" }, new[] { "YTT_YTDLP", "yt-dlp.exe" },
                                   new[] { "YTT_DENO", "deno.exe" }, new[] { "YTT_STREAMLINK", "streamlink.exe" } };
                foreach (var x in exes)
                {
                    string found = FindIn(p.Tools, x[1]);
                    if (found != null) env[x[0]] = found;
                }
            }
            if (dirs.Count > 0) env["PATH"] = string.Join(";", dirs) + (string.IsNullOrEmpty(path) ? "" : ";" + path);
            return env;
        }

        // tools\ の直下とその下 2 段まで(ffmpeg の zip は bin\ の下に入る)
        static string FindIn(string dir, string name)
        {
            try
            {
                string direct = Path.Combine(dir, name);
                if (File.Exists(direct)) return direct;
                foreach (string sub in Directory.GetDirectories(dir).OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
                {
                    if (File.Exists(Path.Combine(sub, name))) return Path.Combine(sub, name);
                    foreach (string sub2 in Directory.GetDirectories(sub).OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
                        if (File.Exists(Path.Combine(sub2, name))) return Path.Combine(sub2, name);
                }
            }
            catch (Exception) { }
            return null;
        }

        string ErrLogPath()
        {
            return Path.Combine(dataRoot, "app", "logs", "headless-stderr.log");
        }

        void OpenErrLog()
        {
            CloseErrLog();
            try
            {
                string path = ErrLogPath();
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                bool fresh = File.Exists(path) && new FileInfo(path).Length > StderrMax;
                // 共有して開く(もう動いている入口に頼む 2 つ目の起動とも同じファイルに書ける)
                var fs = new FileStream(path, fresh ? FileMode.Create : FileMode.Append, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete);
                errLog = new StreamWriter(fs, new UTF8Encoding(false)) { AutoFlush = true };
                errLog.WriteLine("---- " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " start");
            }
            catch (Exception ex) { errLog = null; Log("backend: stderr log: " + ex.Message); }
        }

        void WriteErr(string line)
        {
            if (line == null) return;
            var w = errLog;
            if (w == null) return;
            try { lock (w) w.WriteLine(line); }
            catch (Exception) { }
        }

        void CloseErrLog()
        {
            var w = errLog;
            errLog = null;
            if (w == null) return;
            try { lock (w) w.Dispose(); }
            catch (Exception) { }
        }

        // ---------------------------------------------------------------- 止める
        // 自分が起こした ② だけ止める(ほかの入口に頼んでいたときは離れるだけ)。-> 止まったか(起こしていなければ true)
        public bool Stop()
        {
            Process p;
            lock (startGate)
            lock (gate)
            {
                p = Owned ? proc : null;
                proc = null;
                bool hadToken = Token != null;
                int port = Port;
                string token = Token;
                Port = 0;
                Token = null;
                Owned = false;
                if (p == null) return true;
                if (p.HasExited) { CloseErrLog(); return true; }
                if (hadToken)
                {
                    var r = Send("POST", port, "/api/shutdown", new Dictionary<string, object>(), token, 5000, 64 * 1024, false);
                    Log("backend: shutdown " + r.Status);
                }
            }
            bool done = p.WaitForExit(ShutdownWaitMs);
            if (!done)
            {
                try { p.StandardInput.Close(); }   // ② の標準入力の EOF の見張り(F0-1)
                catch (Exception) { }
                done = p.WaitForExit(StdinWaitMs);
            }
            if (!done) { Log("backend: kill"); KillQuietly(p); }
            CloseErrLog();
            return done;
        }

        static void KillQuietly(Process p)
        {
            try { if (!p.HasExited) p.Kill(); p.WaitForExit(3000); }
            catch (Exception) { }
        }

        public bool Running
        {
            get
            {
                lock (gate) return Ready && (!Owned || (proc != null && !proc.HasExited));
            }
        }

        // ---------------------------------------------------------------- HTTP
        public FlowReply Get(string path)
        {
            return Call("GET", path, null, 5000);
        }

        public FlowReply Post(string path, object body)
        {
            return Call("POST", path, body, 30000);
        }

        FlowReply Call(string method, string path, object body, int timeoutMs)
        {
            int port;
            string token;
            lock (gate) { port = Port; token = Token; }
            if (port == 0) return new FlowReply { Error = "処理の部品が動いていません" };
            return Send(method, port, path, body, token, timeoutMs, 16 * 1024 * 1024, false);
        }

        // 127.0.0.1 へ。asHtml = 本文を JSON として読まず Body["html"] に入れる
        static FlowReply Send(string method, int port, string path, object body, string token, int timeoutMs, int limit, bool asHtml)
        {
            var reply = new FlowReply();
            try
            {
                var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + path);
                req.Method = method;
                req.Proxy = null;   // プロキシを通さない
                req.Timeout = req.ReadWriteTimeout = timeoutMs;
                req.Accept = asHtml ? "text/html" : "application/json";
                req.KeepAlive = false;
                if (token != null && method != "GET") req.Headers["X-YTT-Token"] = token;
                if (body != null)
                {
                    var ser = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
                    byte[] data = new UTF8Encoding(false).GetBytes(ser.Serialize(body));
                    req.ContentType = "application/json";
                    req.ContentLength = data.Length;
                    using (var s = req.GetRequestStream()) s.Write(data, 0, data.Length);
                }
                HttpWebResponse resp;
                try { resp = (HttpWebResponse)req.GetResponse(); }
                catch (WebException ex)
                {
                    resp = ex.Response as HttpWebResponse;
                    if (resp == null) throw;
                }
                using (resp)
                {
                    reply.Status = (int)resp.StatusCode;
                    string text = ReadLimited(resp.GetResponseStream(), limit);
                    if (asHtml) reply.Body = new Dictionary<string, object> { { "html", text } };
                    else if (text.Trim().Length > 0)
                    {
                        try { reply.Body = Json.Parse(text); }
                        catch (Exception) { reply.Body = new Dictionary<string, object>(); }
                    }
                }
            }
            catch (Exception ex)
            {
                if (!(ex is WebException || ex is IOException || ex is InvalidOperationException || ex is NotSupportedException)) throw;
                reply.Status = 0;
                reply.Error = "処理の部品につながりませんでした(" + ex.GetType().Name + ")";
            }
            return reply;
        }

        static string ReadLimited(Stream s, int limit)
        {
            using (var ms = new MemoryStream())
            {
                var buf = new byte[64 * 1024];
                int n;
                while ((n = s.Read(buf, 0, buf.Length)) > 0)
                {
                    ms.Write(buf, 0, n);
                    if (ms.Length > limit) throw new IOException("返事が大きすぎます");
                }
                return new UTF8Encoding(false).GetString(ms.ToArray());
            }
        }
    }
}
