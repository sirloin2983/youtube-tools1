// 初回の取得と更新(F1 の F4b。設計 docs/design/f1-build.md の F4b・(f1g)(f1h)(f1i))。
//   初回の取得: zip に入っている fetch.json(dev/build_friend_zip.py が書く。モデル・llama.cpp・ffmpeg・yt-dlp・Deno)の各物を、進み具合つきで取る。
//     続きから(.part に書く)・大きさと SHA-256 を確かめる・違えば消してやり直す・失敗した物だけ次の回にやり直す。置き場所は fetch.json の base(data = ② の作業データの根 / app = アプリのフォルダ)+ dest
//     足りない物があれば、起動時に小窓で [取ってくる](Setup.OfferFetch。MainForm の Shown から 1 回)
//   更新: Dropbox の /更新/RequestSender-<版>.zip を取り(DownloadUpdate)、Setup.StartUpdate(zip) が <app>\new\ に展開 → update.cmd を書いて起動して自分を終える。
//     update.cmd は自分が終わるのを待ち → robocopy /E で入れ替え(config.json・keys.json・settings.json は /XF で触らない。作業データとモデルはアプリのフォルダの外 = 触らない)→ アプリを起こし直す
// 通信は https の固定の URL と Dropbox だけ。tar.bz2 は .NET 4 に展開が無いので、アプリに同梱の Python の tarfile で展開する(python\python.exe)。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using FriendApps;

namespace RequestSender
{
    // ---- fetch.json の 1 行 ----
    public class FetchItem
    {
        public string Name = "", File = "", Url = "", Sha256 = "", Base = "data", Dest = "", Unzip, Top = "", Member = "";
        public long Size = -1;       // 分かっていないときは -1(maxBytes で守る)
        public long MaxBytes;
        public List<string> Parts = new List<string>();

        // 取るファイルの名前(tar.bz2-member は File が取り出したあとの名前なので、取るのは URL の最後の名前)
        public string ArchiveName
        {
            get
            {
                if (Unzip == "tar.bz2-member")
                {
                    string n = Url.Substring(Url.LastIndexOf('/') + 1);
                    int q = n.IndexOfAny(new[] { '?', '#' });
                    return q >= 0 ? n.Substring(0, q) : n;
                }
                return File;
            }
        }

        // 大きさの見込み(上限)。進み具合の分母と、これを超えたら中止
        public long Expect { get { return Size > 0 ? Size : MaxBytes; } }

        public string Folder(string dataRoot, string appDir)
        {
            return Path.Combine(Base == "app" ? appDir : dataRoot, Dest.Replace('/', Path.DirectorySeparatorChar));
        }

        public string MarkerPath(string folder) { return Path.Combine(folder, ".fetched-" + File); }

        // 取り終えているか(起動のたびに見るので軽く: 大きさ・あるかどうかだけ。SHA-256 は取ったときに確かめた)
        public bool IsDone(string dataRoot, string appDir)
        {
            string folder = Folder(dataRoot, appDir);
            try
            {
                switch (Unzip)
                {
                    case null:
                        var fi = new FileInfo(Path.Combine(folder, File));
                        return fi.Exists && (Size > 0 ? fi.Length == Size : fi.Length > 0 && fi.Length <= MaxBytes);
                    case "zip":
                        string mark = MarkerPath(folder);
                        return System.IO.File.Exists(mark) && System.IO.File.ReadAllText(mark).Trim() == Sha256;
                    case "tar.bz2":
                        return Parts.Count > 0 && Parts.All(p => System.IO.File.Exists(Path.Combine(folder, Top, p.Replace('/', Path.DirectorySeparatorChar))));
                    case "tar.bz2-member":
                        var mi = new FileInfo(Path.Combine(folder, File));
                        return mi.Exists && mi.Length > 0 && mi.Length <= MaxBytes;
                }
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            return false;
        }
    }

    public class FetchPlan
    {
        public string Version = "";
        public List<FetchItem> Items = new List<FetchItem>();
        static readonly Regex Sha = new Regex("^[0-9a-f]{64}$");

        public static FetchPlan Load(string appDir)
        {
            var d = Json.ReadFileOrNull(Path.Combine(appDir, "fetch.json"));
            return d == null ? null : Parse(d);
        }

        // 形が壊れていれば FormatException(作る側の不具合。危ない dest・https でない URL・SHA-256 の形違いは受け付けない)
        public static FetchPlan Parse(IDictionary<string, object> d)
        {
            var p = new FetchPlan { Version = Json.Str(d, "version") ?? "" };
            foreach (var o in Json.List(d, "items"))
            {
                var it = new FetchItem
                {
                    Name = Json.Str(o, "name") ?? "", File = Json.Str(o, "file") ?? "", Url = Json.Str(o, "url") ?? "",
                    Sha256 = (Json.Str(o, "sha256") ?? "").ToLowerInvariant(), Base = Json.Str(o, "base") ?? "", Dest = Json.Str(o, "dest") ?? "",
                    Unzip = Json.Str(o, "unzip"), Top = Json.Str(o, "top") ?? "", Member = Json.Str(o, "member") ?? "",
                    Size = Json.Long(o, "size", -1), MaxBytes = Json.Long(o, "maxBytes", 0),
                };
                object parts;
                var list = o.TryGetValue("parts", out parts) ? parts as System.Collections.IEnumerable : null;
                if (list != null && !(parts is string)) foreach (object x in list) if (x is string) it.Parts.Add((string)x);
                string bad = Problem(it);
                if (bad != null) throw new FormatException("fetch.json の " + (it.Name.Length > 0 ? it.Name : "?") + ": " + bad);
                p.Items.Add(it);
            }
            return p;
        }

        static string Problem(FetchItem it)
        {
            if (it.Name.Length == 0) return "name がありません";
            if (it.File.Length == 0 || it.File.IndexOfAny(new[] { '/', '\\', ':' }) >= 0 || it.File == "." || it.File == "..") return "file の名前が不正です";
            if (!it.Url.StartsWith("https://", StringComparison.Ordinal)) return "url が https ではありません";
            if (!Sha.IsMatch(it.Sha256)) return "sha256 の形が違います";
            if (it.Base != "data" && it.Base != "app") return "base は data か app";
            if (!SafeRelative(it.Dest)) return "dest が不正です";
            if (it.Size <= 0 && it.MaxBytes <= 0) return "size も maxBytes もありません";
            if (it.Unzip != null && it.Unzip != "zip" && it.Unzip != "tar.bz2" && it.Unzip != "tar.bz2-member") return "unzip を知りません: " + it.Unzip;
            if (it.Unzip == "tar.bz2" && (!SafeRelative(it.Top) || it.Top.Length == 0 || it.Parts.Count == 0 || !it.Parts.All(SafeRelative))) return "top・parts が不正です";
            if (it.Unzip == "tar.bz2-member" && (it.Member.Length == 0 || it.MaxBytes <= 0)) return "member・maxBytes がありません";
            return null;
        }

        // アプリ・作業データの根の中だけを指す相対パスか(絶対パス・ドライブ・.. は不可)
        public static bool SafeRelative(string p)
        {
            if (p == null) return false;
            string n = p.Replace('\\', '/');
            if (n.Length == 0) return true;
            if (n.StartsWith("/", StringComparison.Ordinal) || n.IndexOf(':') >= 0) return false;
            return !n.Split('/').Any(s => s == ".." || s.Length == 0);
        }

        public List<FetchItem> Missing(string dataRoot, string appDir)
        {
            return Items.Where(i => !i.IsDone(dataRoot, appDir)).ToList();
        }
    }

    // ---- 取る道具(テストは偽物を渡す) ----
    public interface IDownloader
    {
        // url を partPath へ。あればその続きから。expect を超えたら IOException。progress(ここまでのバイト数)
        void Get(string url, string partPath, long expect, Action<long> progress, Func<bool> canceled);
    }

    public interface ITarTool
    {
        void ExtractAll(string archive, string destDir, string top);
        void ExtractMember(string archive, string member, string outFile, long maxBytes);
    }

    public class HttpDownloader : IDownloader
    {
        public const int Retries = 6;
        public int RetryWaitMs = 2000;
        public Action<string> Log = s => { };

        public void Get(string url, string partPath, long expect, Action<long> progress, Func<bool> canceled)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(partPath));
            for (int attempt = 1; ; attempt++)
            {
                try { Once(url, partPath, expect, progress, canceled); return; }
                catch (CanceledException) { throw; }
                catch (Exception ex)
                {
                    if (!(ex is WebException || ex is IOException)) throw;
                    if (attempt >= Retries) throw new IOException("通信が続きませんでした: " + ex.Message, ex);
                    Log("fetch retry " + attempt + ": " + ex.Message);
                    for (int w = 0; w < RetryWaitMs; w += 100)
                    {
                        if (canceled != null && canceled()) throw new CanceledException();
                        Thread.Sleep(100);
                    }
                }
            }
        }

        void Once(string url, string partPath, long expect, Action<long> progress, Func<bool> canceled)
        {
            long have = System.IO.File.Exists(partPath) ? new FileInfo(partPath).Length : 0;
            if (have > expect) { System.IO.File.Delete(partPath); have = 0; }
            var req = (HttpWebRequest)WebRequest.Create(url);
            req.UserAgent = "RequestSender/" + AppInfo.Version;
            req.Timeout = 60 * 1000;
            req.ReadWriteTimeout = 60 * 1000;
            req.AllowAutoRedirect = true;
            if (have > 0) req.AddRange(have);
            HttpWebResponse resp;
            try { resp = (HttpWebResponse)req.GetResponse(); }
            catch (WebException ex)
            {
                var r = ex.Response as HttpWebResponse;
                if (r != null && r.StatusCode == HttpStatusCode.RequestedRangeNotSatisfiable) { r.Close(); System.IO.File.Delete(partPath); have = 0; throw new IOException("続きが取れなかったので最初から取り直します"); }
                throw;
            }
            using (resp)
            {
                bool resume = have > 0 && resp.StatusCode == HttpStatusCode.PartialContent;
                if (!resume) have = 0;
                using (var s = resp.GetResponseStream())
                using (var fs = new FileStream(partPath, resume ? FileMode.Append : FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    var buf = new byte[256 * 1024];
                    long done = have;
                    if (progress != null) progress(done);
                    int n;
                    while ((n = s.Read(buf, 0, buf.Length)) > 0)
                    {
                        if (canceled != null && canceled()) { req.Abort(); throw new CanceledException(); }
                        done += n;
                        if (done > expect) { req.Abort(); throw new InvalidDataException("想定より大きいファイルなので止めました"); }
                        fs.Write(buf, 0, n);
                        if (progress != null) progress(done);
                    }
                }
            }
        }
    }

    // アプリに同梱の Python(python\python.exe)の tarfile で tar.bz2 を展開する。名前が外へ出る・リンク・想定外の形は断る
    public class PythonTar : ITarTool
    {
        readonly string python;
        public Action<string> Log = s => { };

        public PythonTar(string pythonExe) { python = pythonExe; }

        public const string Script =
            "import sys, os, tarfile, shutil\n" +
            "def safe(n):\n" +
            "    p = n.replace(chr(92), '/')\n" +
            "    return not (p.startswith('/') or ':' in p or '..' in p.split('/'))\n" +
            "mode, arc, dest = sys.argv[1], sys.argv[2], sys.argv[3]\n" +
            "with tarfile.open(arc, 'r:bz2') as t:\n" +
            "    if mode == 'all':\n" +
            "        top = sys.argv[4]\n" +
            "        ms = t.getmembers()\n" +
            "        for m in ms:\n" +
            "            n = m.name[2:] if m.name.startswith('./') else m.name\n" +
            "            if not safe(n) or not (m.isfile() or m.isdir()) or not (n == top or n.startswith(top + '/')):\n" +
            "                sys.exit('unsafe member: ' + m.name)\n" +
            "        os.makedirs(dest, exist_ok=True)\n" +
            "        t.extractall(dest, members=ms)\n" +
            "    else:\n" +
            "        member, mx = sys.argv[4], int(sys.argv[5])\n" +
            "        m = t.getmember(member)\n" +
            "        if not m.isfile() or m.size > mx:\n" +
            "            sys.exit('unexpected member')\n" +
            "        os.makedirs(os.path.dirname(dest), exist_ok=True)\n" +
            "        part = dest + '.part'\n" +
            "        with t.extractfile(m) as s, open(part, 'wb') as o:\n" +
            "            shutil.copyfileobj(s, o)\n" +
            "        os.replace(part, dest)\n";

        public void ExtractAll(string archive, string destDir, string top)
        {
            Run("all", archive, destDir, top);
        }

        public void ExtractMember(string archive, string member, string outFile, long maxBytes)
        {
            Run("member", archive, outFile, member, maxBytes.ToString());
        }

        void Run(string mode, params string[] args)
        {
            if (!System.IO.File.Exists(python)) throw new IOException("同梱の Python が見つかりません: " + python);
            string dir = Path.Combine(Path.GetTempPath(), "request-sender-tar-" + Guid.NewGuid().ToString("N").Substring(0, 8));
            Directory.CreateDirectory(dir);
            try
            {
                string script = Path.Combine(dir, "untar.py");
                System.IO.File.WriteAllText(script, Script, new UTF8Encoding(false));
                var sb = new StringBuilder(Quote(script) + " " + mode);
                foreach (string a in args) sb.Append(' ').Append(Quote(a));
                var psi = new ProcessStartInfo(python, "-I " + sb)
                {
                    UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true, RedirectStandardOutput = true,
                    WorkingDirectory = dir,
                };
                using (var p = Process.Start(psi))
                {
                    string err = p.StandardError.ReadToEnd();
                    p.StandardOutput.ReadToEnd();
                    p.WaitForExit();
                    if (p.ExitCode != 0)
                    {
                        Log("untar failed: " + err);
                        throw new IOException("展開できませんでした: " + (err.Length > 200 ? err.Substring(err.Length - 200) : err).Trim());
                    }
                }
            }
            finally
            {
                try { Directory.Delete(dir, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            }
        }

        // Windows の引数 1 つ(末尾の \ は " を打ち消さないよう 2 つに)
        public static string Quote(string s)
        {
            return "\"" + Regex.Replace(s, @"(\\+)$", "$1$1").Replace("\"", "\\\"") + "\"";
        }
    }

    // ---- 取得の進み具合・結果 ----
    public class FetchProgress
    {
        public int Index, Count;
        public string Name = "", Phase = "";
        public long ItemDone, ItemTotal, OverallDone, OverallTotal;
        public double Fraction { get { return OverallTotal > 0 ? Math.Min(1.0, (double)OverallDone / OverallTotal) : 0; } }
    }

    public class FetchResult
    {
        public List<string> Done = new List<string>();
        public List<KeyValuePair<string, string>> Failed = new List<KeyValuePair<string, string>>();   // 名前, 理由
        public bool Canceled;
        public bool Ok { get { return Failed.Count == 0 && !Canceled; } }
    }

    public class Fetcher
    {
        readonly IDownloader http;
        readonly ITarTool tar;
        readonly string dataRoot, appDir;
        public Action<string> Log = s => { };
        public Action<FetchProgress> Progress = p => { };
        public Func<bool> Canceled = () => false;

        public Fetcher(IDownloader http, ITarTool tar, string dataRoot, string appDir)
        {
            this.http = http; this.tar = tar; this.dataRoot = dataRoot; this.appDir = appDir;
        }

        // items を 1 つずつ。1 つ失敗しても次へ進む(失敗した物は Failed。次の回に足りない物としてまた出る)
        public FetchResult Run(IList<FetchItem> items)
        {
            var res = new FetchResult();
            long total = items.Sum(i => i.Expect), before = 0;
            for (int idx = 0; idx < items.Count; idx++)
            {
                var it = items[idx];
                var pr = new FetchProgress { Index = idx + 1, Count = items.Count, Name = it.Name, ItemTotal = it.Expect, OverallTotal = total };
                Action<long, string> report = (done, phase) =>
                {
                    pr.ItemDone = done; pr.Phase = phase; pr.OverallDone = before + Math.Min(done, it.Expect);
                    Progress(pr);
                };
                try
                {
                    FetchOne(it, report);
                    res.Done.Add(it.Name);
                }
                catch (CanceledException) { res.Canceled = true; return res; }
                catch (Exception ex)
                {
                    if (!(ex is IOException || ex is UnauthorizedAccessException || ex is InvalidDataException || ex is WebException)) throw;
                    Log("fetch failed " + it.Name + ": " + ex.Message);
                    res.Failed.Add(new KeyValuePair<string, string>(it.Name, ex.Message));
                }
                report(it.Expect, "済み");
                before += it.Expect;
            }
            return res;
        }

        void FetchOne(FetchItem it, Action<long, string> report)
        {
            string folder = it.Folder(dataRoot, appDir);
            Directory.CreateDirectory(folder);
            string archive = Path.Combine(folder, it.ArchiveName), part = archive + ".part";
            string why0;
            if (System.IO.File.Exists(archive) && !Verify(it, archive, out why0))
            {
                Log("fetch: " + it.ArchiveName + " の中身が違うので取り直します");
                System.IO.File.Delete(archive);
            }
            if (!System.IO.File.Exists(archive))
            {
                bool ok = false;
                for (int attempt = 1; attempt <= 2 && !ok; attempt++)
                {
                    http.Get(it.Url, part, it.Expect, n => report(n, "取っています"), Canceled);
                    report(it.Expect, "確かめています");
                    string why;
                    if (Verify(it, part, out why)) ok = true;
                    else
                    {
                        System.IO.File.Delete(part);   // 違う物は続きから取らず、最初から
                        if (attempt == 2) throw new InvalidDataException(it.Name + " の中身が想定と違います(" + why + ")");
                    }
                }
                System.IO.File.Move(part, archive);
            }
            if (it.Unzip == null) return;
            report(it.Expect, "展開しています");
            if (Canceled()) throw new CanceledException();
            if (it.Unzip == "zip")
            {
                ZipUtil.ExtractSafe(archive, folder);
                System.IO.File.WriteAllText(it.MarkerPath(folder), it.Sha256);
            }
            else if (it.Unzip == "tar.bz2")
            {
                tar.ExtractAll(archive, folder, it.Top);
                if (!it.IsDone(dataRoot, appDir)) throw new InvalidDataException(it.Name + " のファイルがそろいませんでした");
            }
            else
            {
                tar.ExtractMember(archive, it.Member, Path.Combine(folder, it.File), it.MaxBytes);
            }
            System.IO.File.Delete(archive);
        }

        // 大きさ(分かっていれば一致・無ければ上限以下)と SHA-256
        public static bool Verify(FetchItem it, string path, out string why)
        {
            long len = new FileInfo(path).Length;
            if (it.Size > 0 ? len != it.Size : (len == 0 || len > it.MaxBytes)) { why = "大きさが違います"; return false; }
            if (Hash.Sha256File(path) != it.Sha256) { why = "SHA-256 が合いません"; return false; }
            why = "";
            return true;
        }
    }

    public static class Hash
    {
        public static string Sha256File(string path)
        {
            using (var sha = SHA256.Create())
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
            {
                var h = sha.ComputeHash(fs);
                var sb = new StringBuilder(64);
                foreach (byte b in h) sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }
    }

    public static class ZipUtil
    {
        // zip を dir に展開(名前が dir の外へ出る物・絶対パス・ドライブ名は断る = InvalidDataException。同じ名前は上書き)
        public static void ExtractSafe(string zipPath, string dir)
        {
            string root = Path.GetFullPath(dir).TrimEnd('\\', '/') + Path.DirectorySeparatorChar;
            using (var zip = ZipFile.OpenRead(zipPath))
            {
                var plan = new List<KeyValuePair<ZipArchiveEntry, string>>();
                foreach (var e in zip.Entries)
                {
                    string n = e.FullName.Replace('\\', '/');
                    if (n.Length == 0) continue;
                    if (n.StartsWith("/", StringComparison.Ordinal) || n.IndexOf(':') >= 0 || n.Split('/').Any(s => s == "..")) throw new InvalidDataException("zip の中の名前が危ないので使いません: " + Short(n));
                    string full = Path.GetFullPath(Path.Combine(dir, n.Replace('/', Path.DirectorySeparatorChar)));
                    if (!full.StartsWith(root, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("zip の中の名前が危ないので使いません: " + Short(n));
                    plan.Add(new KeyValuePair<ZipArchiveEntry, string>(e, full));   // 全部の名前を確かめてから書く
                }
                foreach (var kv in plan)
                {
                    if (kv.Key.FullName.EndsWith("/", StringComparison.Ordinal) || kv.Key.FullName.EndsWith("\\", StringComparison.Ordinal)) { Directory.CreateDirectory(kv.Value); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(kv.Value));
                    using (var src = kv.Key.Open())
                    using (var dst = new FileStream(kv.Value, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20))
                        src.CopyTo(dst, 1 << 20);
                }
            }
        }

        static string Short(string s) { return s.Length > 80 ? s.Substring(0, 80) : s; }
    }

    // ---- 更新(zip を new\ に展開 → update.cmd) ----
    public static class Setup
    {
        public const string UpdateDir = "/更新";   // Dropbox の置き場所(dev/build_friend_zip.py の出力先。(f1h))
        public static readonly string[] KeepFiles = { "config.json", "keys.json", "settings.json" };   // 更新で触らない(robocopy /XF)
        public static readonly Regex UpdateFile = new Regex(@"^RequestSender-\d+\.\d+\.\d+\.zip$");
        public static volatile bool Updating;
        public static Action ExitHook = () => Application.Exit();   // StartUpdate が自分を終えるのに呼ぶ(テストは差し替える)
        public static int MissingCount { get; private set; }       // 起動時に足りなかった物の数(0 = そろっている・取っていない)

        public static string Mb(long bytes)
        {
            return bytes >= 1024L * 1024 * 1024 ? (bytes / (1024.0 * 1024 * 1024)).ToString("0.0") + " GB" : Math.Max(1, bytes / (1024 * 1024)) + " MB";
        }

        // Dropbox の /更新/<file> を取って大きさ・SHA-256 を確かめる。-> <app>\update-download\<file>
        public static string DownloadUpdate(DropboxClient dbx, string file, long size, string sha256, string appDir, Action<long> progress)
        {
            if (file == null || !UpdateFile.IsMatch(file)) throw new InvalidDataException("更新の zip の名前が想定と違います: " + file);
            string dir = Path.Combine(appDir, "update-download");
            Directory.CreateDirectory(dir);
            string part = Path.Combine(dir, file + ".part"), zip = Path.Combine(dir, file);
            dbx.DownloadFile(UpdateDir + "/" + file, null, part, progress);
            var fi = new FileInfo(part);
            if ((size > 0 && fi.Length != size) || Hash.Sha256File(part) != (sha256 ?? "").ToLowerInvariant())
            {
                fi.Delete();
                throw new InvalidDataException("取った更新の zip が想定と違います(大きさか SHA-256 が合いません)。もう一度試してください");
            }
            if (System.IO.File.Exists(zip)) System.IO.File.Delete(zip);
            System.IO.File.Move(part, zip);
            return zip;
        }

        // zip を <app>\new\ に展開し、manifest.json があれば全ファイルの SHA-256 を確かめ、update.cmd を書く。-> update.cmd のパス。失敗したら new\ を消して例外
        public static string PrepareUpdate(string zipPath, string appDir, int waitPid, bool restart = true)
        {
            string stage = Path.Combine(appDir, "new");
            DeleteDir(stage);
            try
            {
                ZipUtil.ExtractSafe(zipPath, stage);
                string src = SourceDir(stage);
                VerifyManifest(src);
                if (!System.IO.File.Exists(Path.Combine(src, "RequestSender.exe"))) throw new InvalidDataException("更新の zip に RequestSender.exe がありません");
                string cmd = Path.Combine(appDir, "update.cmd");
                System.IO.File.WriteAllText(cmd, UpdateCmd(appDir, src, waitPid, restart), CmdEncoding());
                return cmd;
            }
            catch (Exception)
            {
                DeleteDir(stage);
                throw;
            }
        }

        // zip の根に直に入っている形が正。1 つのフォルダに包まれていたら(RequestSender.zip と同じ形)その中
        static string SourceDir(string stage)
        {
            if (System.IO.File.Exists(Path.Combine(stage, "manifest.json")) || System.IO.File.Exists(Path.Combine(stage, "RequestSender.exe"))) return stage;
            var dirs = Directory.GetDirectories(stage);
            if (dirs.Length == 1 && Directory.GetFiles(stage).Length == 0) return dirs[0];
            return stage;
        }

        static void VerifyManifest(string src)
        {
            var m = Json.ReadFileOrNull(Path.Combine(src, "manifest.json"));
            if (m == null) return;   // 手で作った zip(manifest なし)はそのまま
            var files = Json.Dict(m, "files");
            if (files == null) return;
            foreach (var kv in files)
            {
                string want = kv.Value as string;
                if (want == null || !FetchPlan.SafeRelative(kv.Key)) throw new InvalidDataException("manifest.json の形が違います");
                string p = Path.Combine(src, kv.Key.Replace('/', Path.DirectorySeparatorChar));
                if (!System.IO.File.Exists(p) || Hash.Sha256File(p) != want.ToLowerInvariant()) throw new InvalidDataException("更新の zip の中身が manifest.json と違います: " + kv.Key);
            }
        }

        static Encoding CmdEncoding()
        {
            try { return Encoding.GetEncoding(System.Globalization.CultureInfo.CurrentCulture.TextInfo.OEMCodePage); }
            catch (ArgumentException) { return Encoding.Default; }
            catch (NotSupportedException) { return Encoding.Default; }
        }

        // 終わるのを待つ(最大 2 分。待ちきれなければ何も入れ替えない)→ robocopy /E(config.json などは /XF で触らない。0〜7 は成功)→ new\ を消す → アプリを起こし直す → 自分を消す
        public static string UpdateCmd(string appDir, string srcDir, int waitPid, bool restart)
        {
            string app = appDir.TrimEnd('\\'), src = srcDir.TrimEnd('\\');
            var sb = new StringBuilder();
            sb.Append("@echo off\r\n");
            sb.Append("set \"APP=").Append(app).Append("\"\r\n");
            sb.Append("set \"SRC=").Append(src).Append("\"\r\n");
            sb.Append("set \"PID=").Append(waitPid).Append("\"\r\n");
            sb.Append("set /a N=0\r\n");
            sb.Append(":wait\r\n");
            sb.Append("tasklist /FI \"PID eq %PID%\" 2>nul | find \"%PID%\" >nul\r\n");
            sb.Append("if errorlevel 1 goto go\r\n");
            sb.Append("set /a N+=1\r\n");
            sb.Append("if %N% GEQ 120 exit /b 1\r\n");
            sb.Append("ping -n 2 127.0.0.1 >nul\r\n");   // timeout は窓なしだと入力の都合で失敗するので ping で 1 秒待つ
            sb.Append("goto wait\r\n");
            sb.Append(":go\r\n");
            sb.Append("robocopy \"%SRC%\" \"%APP%\" /E /XF ").Append(string.Join(" ", KeepFiles)).Append(" /R:10 /W:2 /NFL /NDL /NJH /NJS /NP >nul\r\n");
            sb.Append("if errorlevel 8 exit /b 1\r\n");
            sb.Append("rmdir /s /q \"%APP%\\new\"\r\n");
            sb.Append("rmdir /s /q \"%APP%\\update-download\" 2>nul\r\n");
            if (restart) sb.Append("if exist \"%APP%\\RequestSender.exe\" start \"\" \"%APP%\\RequestSender.exe\"\r\n");
            sb.Append("(goto) 2>nul & del \"%~f0\"\r\n");
            return sb.ToString();
        }

        // 「更新する」の口(Sync.cs が、DownloadUpdate で取った zip を渡して呼ぶ)。new\ に展開 → update.cmd を窓なしで起動 → 自分を終える。
        // 失敗したら例外(何も入れ替えていない)。-> true(起動した = ExitHook を呼んだ)
        public static bool StartUpdate(string zipPath)
        {
            string appDir = Program.ExeDir;
            if (string.IsNullOrEmpty(appDir)) throw new InvalidOperationException("アプリのフォルダが分かりません");
            string cmd = PrepareUpdate(zipPath, appDir, Process.GetCurrentProcess().Id);
            var psi = new ProcessStartInfo("cmd.exe", "/c \"\"" + cmd + "\"\"")
            {
                UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = appDir,
            };
            Process.Start(psi);
            Log.Write("update: started " + cmd + " for " + Path.GetFileName(zipPath));
            Updating = true;
            ExitHook();
            return true;
        }

        static void DeleteDir(string d)
        {
            try { if (Directory.Exists(d)) Directory.Delete(d, true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        // ---- 起動時の確認(MainForm の Shown から 1 回) ----
        // fetch.json があり、足りない物があれば小窓を出す。無ければ何もしない。窓を閉じたあとも足りなければ MissingCount に残る
        public static void OfferFetch(IWin32Window owner, string appDir)
        {
            FetchPlan plan;
            try { plan = FetchPlan.Load(appDir); }
            catch (FormatException ex) { Log.Write("fetch.json: " + ex.Message); return; }
            if (plan == null) return;
            string dataRoot = Backend.DefaultDataRoot();
            var missing = plan.Missing(dataRoot, appDir);
            MissingCount = missing.Count;
            if (missing.Count == 0) return;
            using (var dlg = new FetchDialog(plan, dataRoot, appDir)) dlg.ShowDialog(owner);
            MissingCount = plan.Missing(dataRoot, appDir).Count;
        }

        public static string MissingReason()
        {
            return MissingCount > 0 ? "初回の準備が終わっていません(足りない部品 " + MissingCount + " 個)。アプリを開き直して「取ってくる」を押してください" : "";
        }
    }

    // 初回の取得の小窓: 何を・どれだけ取るかを見せて [取ってくる]。進み具合・失敗した物・[やり直す]
    public class FetchDialog : Form
    {
        readonly FetchPlan plan;
        readonly string dataRoot, appDir;
        readonly Label head = new Label(), detail = new Label();
        readonly ProgressBar bar = new ProgressBar();
        readonly Button go = new Button(), later = new Button();
        volatile bool cancel, running;
        Thread worker;

        public FetchDialog(FetchPlan plan, string dataRoot, string appDir)
        {
            this.plan = plan; this.dataRoot = dataRoot; this.appDir = appDir;
            Text = AppInfo.Title + " - 初回の準備";
            Font = Theme.Body;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            StartPosition = FormStartPosition.CenterParent;
            ClientSize = new Size(Ui.S(520), Ui.S(190));
            head.SetBounds(Ui.S(16), Ui.S(14), Ui.S(488), Ui.S(52));
            detail.SetBounds(Ui.S(16), Ui.S(72), Ui.S(488), Ui.S(40));
            bar.SetBounds(Ui.S(16), Ui.S(114), Ui.S(488), Ui.S(18));
            go.Text = "取ってくる";
            later.Text = "あとで";
            go.SetBounds(Ui.S(300), Ui.S(146), Ui.S(100), Ui.S(30));
            later.SetBounds(Ui.S(408), Ui.S(146), Ui.S(96), Ui.S(30));
            Controls.AddRange(new Control[] { head, detail, bar, go, later });
            AcceptButton = go;
            go.Click += (s, e) => Start();
            later.Click += (s, e) => { if (running) { cancel = true; later.Enabled = false; } else Close(); };
            FormClosing += (s, e) => { if (running) { cancel = true; e.Cancel = true; later.Enabled = false; } };
            ShowSummary();
        }

        void ShowSummary()
        {
            var miss = plan.Missing(dataRoot, appDir);
            long total = miss.Sum(i => i.Expect);
            head.Text = "文字起こしなどに使う部品を、初めに取ってきます(" + miss.Count + " 個・約 " + Setup.Mb(total) + ")。\r\n取り終わるまでは、この PC での処理はできません。";
            detail.Text = string.Join("、", miss.Take(6).Select(i => i.Name)) + (miss.Count > 6 ? " ほか" : "");
            bar.Value = 0;
        }

        void Start()
        {
            if (running) return;
            running = true; cancel = false;
            go.Enabled = false;
            later.Text = "やめる";
            var items = plan.Missing(dataRoot, appDir);
            worker = new Thread(() =>
            {
                var f = new Fetcher(new HttpDownloader { Log = Log.Write }, new PythonTar(Path.Combine(appDir, "python", "python.exe")) { Log = Log.Write }, dataRoot, appDir);
                f.Log = Log.Write;
                f.Canceled = () => cancel;
                f.Progress = p => OnUi(() => ShowProgress(p));
                FetchResult res;
                try { res = f.Run(items); }
                catch (Exception ex)
                {
                    Log.Write("fetch crashed: " + ex);
                    res = new FetchResult();
                    res.Failed.Add(new KeyValuePair<string, string>("取得", ex.Message));
                }
                OnUi(() => Finished(res));
            });
            worker.IsBackground = true;
            worker.Start();
        }

        void ShowProgress(FetchProgress p)
        {
            head.Text = "取っています(" + p.Index + " / " + p.Count + ")  " + p.Name;
            detail.Text = p.Phase + (p.ItemTotal > 0 && p.Phase == "取っています" ? "  " + Setup.Mb(p.ItemDone) + " / " + Setup.Mb(p.ItemTotal) : "");
            bar.Value = (int)Math.Round(p.Fraction * 100);
        }

        void Finished(FetchResult res)
        {
            running = false;
            later.Text = "あとで";
            later.Enabled = true;
            if (res.Ok)
            {
                head.Text = "取り終わりました。";
                detail.Text = "";
                bar.Value = 100;
                DialogResult = DialogResult.OK;
                return;
            }
            go.Enabled = true;
            go.Text = "やり直す";
            if (res.Canceled) { head.Text = "止めました。取れた分は残っています(続きからやり直せます)。"; detail.Text = ""; return; }
            head.Text = "取れなかった物があります(" + res.Failed.Count + " 個)。ネットワークを確かめて、やり直してください。";
            detail.Text = string.Join("\r\n", res.Failed.Take(2).Select(kv => kv.Key + ": " + kv.Value));
        }

        void OnUi(Action a)
        {
            if (IsDisposed || !IsHandleCreated) return;
            try { BeginInvoke(a); }
            catch (InvalidOperationException) { }
        }
    }
}
