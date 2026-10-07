// Dropbox の API でアプリのフォルダへアップロードする・「/出力/」から受け取る(HttpWebRequest。標準の .NET Framework だけ)。
//   鍵: config.json の appKey + refreshToken(PKCE で得たもの。secret は使わない)→ /oauth2/token で短い期間の access token を得る
//   150MB 以下は files/upload、それより大きいものは upload_session/start → append_v2 → finish(8MB ずつ・失敗した塊だけやり直す)
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using FriendApps;

namespace RequestSender
{
    public class DropboxException : Exception
    {
        public int Status;
        public string Body;

        public DropboxException(string message, int status, string body) : base(message)
        {
            Status = status;
            Body = body;
        }
    }

    public class CanceledException : Exception
    {
        public CanceledException() : base("やめました") { }
    }

    public class DropboxClient
    {
        const string TokenUrl = "https://api.dropboxapi.com/oauth2/token";
        const string ContentBase = "https://content.dropboxapi.com/2/";
        const string RpcBase = "https://api.dropboxapi.com/2/";
        const int Retries = 4;
        const int DownloadRetries = 6;   // 数 GB のパックは途中で切れることがある。続きから取るので多めに

        readonly Config config;
        string accessToken;
        public Func<bool> IsCanceled = () => false;
        public Action<string> Log = s => { };

        public DropboxClient(Config config)
        {
            this.config = config;
        }

        public static void UseTls12()
        {
            // .NET Framework 4.x の既定は古い TLS のことがある。Dropbox は TLS 1.2 以上だけなので明示する(3072 = Tls12)
            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;
            ServicePointManager.Expect100Continue = false;
        }

        // ---- 鍵 ----
        public void RefreshAccessToken()
        {
            string form = "grant_type=refresh_token&refresh_token=" + Uri.EscapeDataString(config.RefreshToken) +
                          "&client_id=" + Uri.EscapeDataString(config.AppKey);
            byte[] body = Encoding.ASCII.GetBytes(form);
            var req = (HttpWebRequest)WebRequest.Create(TokenUrl);
            req.Method = "POST";
            req.ContentType = "application/x-www-form-urlencoded";
            req.ContentLength = body.Length;
            req.Timeout = 60000;
            using (var s = req.GetRequestStream()) s.Write(body, 0, body.Length);
            string text = ReadResponse(req);
            var d = Json.Parse(text);
            accessToken = Json.Str(d, "access_token");
            if (string.IsNullOrEmpty(accessToken)) throw new DropboxException("鍵の返事に access_token がありません", 0, "");
        }

        // ---- アップロード ----
        // -> Dropbox に置かれた実際の名前(autorename で変わることがある)
        public string UploadBytes(byte[] data, string dropboxPath)
        {
            var d = Call("files/upload", DropboxArgs.Commit(dropboxPath), data, null);
            return NameOf(d, dropboxPath);
        }

        // progress(この回で送り終えたバイト数)
        public string UploadFile(string localPath, string dropboxPath, Action<long> progress)
        {
            long size = new FileInfo(localPath).Length;
            using (var fs = new FileStream(localPath, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (!ChunkPlan.UseSession(size))
                {
                    var buf = ReadExactly(fs, 0, (int)size);
                    var d = Call("files/upload", DropboxArgs.Commit(dropboxPath), buf, progress);
                    return NameOf(d, dropboxPath);
                }
                var chunks = ChunkPlan.Plan(size, ChunkPlan.ChunkSize);
                string sessionId = null;
                long done = 0;
                for (int i = 0; i < chunks.Count; i++)
                {
                    var c = chunks[i];
                    byte[] buf = ReadExactly(fs, c.Offset, c.Length);
                    long before = done;
                    Action<long> p = n => { if (progress != null) progress(before + n); };
                    if (i == 0)
                    {
                        var d = Call("files/upload_session/start", DropboxArgs.SessionStart(), buf, p);
                        sessionId = Json.Str(d, "session_id");
                        if (string.IsNullOrEmpty(sessionId)) throw new DropboxException("upload_session/start の返事に session_id がありません", 0, "");
                    }
                    else
                    {
                        try
                        {
                            Call("files/upload_session/append_v2", DropboxArgs.Append(sessionId, c.Offset), buf, p);
                        }
                        catch (DropboxException ex)
                        {
                            // やり直しの前の回が実は届いていた: Dropbox が正しい位置を返す。この塊の終わりと同じならそのまま先へ
                            long correct = CorrectOffset(ex.Body);
                            if (correct != c.Offset + c.Length) throw;
                            Log("append: already received up to " + correct);
                        }
                    }
                    done += c.Length;
                    if (progress != null) progress(done);
                }
                var fin = Call("files/upload_session/finish", DropboxArgs.Finish(sessionId, size, dropboxPath), new byte[0], null);
                return NameOf(fin, dropboxPath);
            }
        }

        static long CorrectOffset(string body)
        {
            try
            {
                var d = Json.Parse(body ?? "");
                var err = Json.Dict(d, "error");
                var inc = Json.Dict(err, "incorrect_offset") ?? err;
                return Json.Long(inc, "correct_offset", -1);
            }
            catch (Exception) { return -1; }
        }

        static string NameOf(IDictionary<string, object> d, string fallbackPath)
        {
            string n = Json.Str(d, "name");
            if (!string.IsNullOrEmpty(n)) return n;
            return fallbackPath.TrimStart('/');
        }

        static byte[] ReadExactly(FileStream fs, long offset, int length)
        {
            var buf = new byte[length];
            fs.Seek(offset, SeekOrigin.Begin);
            int got = 0;
            while (got < length)
            {
                int n = fs.Read(buf, got, length - got);
                if (n <= 0) throw new IOException("ファイルを最後まで読めませんでした(送る途中で変わった可能性があります)");
                got += n;
            }
            return buf;
        }

        // content.dropboxapi.com への1回の呼び出し(アップロード)
        IDictionary<string, object> Call(string endpoint, string argJson, byte[] data, Action<long> progress)
        {
            return WithRetry(endpoint, Retries, () => ParseOrEmpty(Send(endpoint, argJson, data, progress)));
        }

        static IDictionary<string, object> ParseOrEmpty(string text)
        {
            return text.Trim().Length == 0 || text.Trim() == "null" ? new Dictionary<string, object>() : Json.Parse(text);
        }

        // 通信の失敗・429・5xx は少し待ってやり直す。401 は鍵を取り直して1回だけやり直す(権限が足りない 401 は取り直しても同じなのでそのまま返す)。
        // Status が負の DropboxException は、このプログラムが見つけた問題(やり直さない)
        T WithRetry<T>(string endpoint, int attempts, Func<T> once)
        {
            if (accessToken == null) RefreshAccessToken();
            bool refreshed = false;
            for (int attempt = 1; ; attempt++)
            {
                if (IsCanceled()) throw new CanceledException();
                try
                {
                    return once();
                }
                catch (DropboxException ex)
                {
                    if (ex.Status == 401 && !refreshed && !ErrorText.IsMissingScope(ex.Body))
                    {
                        refreshed = true;
                        RefreshAccessToken();
                        continue;
                    }
                    bool retry = ex.Status == 0 || ex.Status == 429 || ex.Status >= 500;
                    if (!retry || attempt >= attempts) throw;
                    Log(endpoint + " failed (" + ex.Status + "), retry " + attempt);
                    Wait(attempt);
                }
            }
        }

        // ---- 受け取る ----
        // api.dropboxapi.com の RPC(本文が JSON)
        public IDictionary<string, object> Rpc(string endpoint, string bodyJson)
        {
            return WithRetry(endpoint, Retries, () => ParseOrEmpty(SendRpc(endpoint, bodyJson)));
        }

        string SendRpc(string endpoint, string bodyJson)
        {
            byte[] body = new UTF8Encoding(false).GetBytes(bodyJson);
            var req = NewPost(RpcBase + endpoint);
            req.ContentType = "application/json";
            req.ContentLength = body.Length;
            req.Timeout = 60000;
            req.ReadWriteTimeout = 60000;
            Net(() => { using (var s = req.GetRequestStream()) s.Write(body, 0, body.Length); });
            return ReadResponse(req);
        }

        // access token つきの POST(本文・ヘッダーの続きは呼ぶ側で足す)
        HttpWebRequest NewPost(string url)
        {
            var req = (HttpWebRequest)WebRequest.Create(url);
            req.Method = "POST";
            req.Headers["Authorization"] = "Bearer " + accessToken;
            return req;
        }

        // 通信の失敗を DropboxException にする(返事が来た失敗は中身も読む。通信が切れたものは Status 0 = やり直せる)
        static T Net<T>(Func<T> action)
        {
            try { return action(); }
            catch (WebException ex) { throw Wrap(ex); }
            catch (IOException ex) { throw Lost(ex); }
        }

        static void Net(Action action)
        {
            Net<bool>(() => { action(); return true; });
        }

        static DropboxException Lost(Exception ex)
        {
            return new DropboxException("通信が切れました: " + ex.Message, 0, "");
        }

        // 小さなファイル(失敗の知らせ)を先頭から cap バイトまで。-> 読んだ長さ。truncated は cap を超えていたか
        public byte[] DownloadHead(string path, int cap, out bool truncated)
        {
            bool cut = false;
            byte[] result = WithRetry("files/download", Retries, () =>
            {
                var req = DownloadRequest(path, 0);
                using (var resp = GetResponse(req))
                using (var s = resp.GetResponseStream())
                {
                    var buf = new byte[cap + 1];
                    int got = 0;
                    try
                    {
                        while (got < buf.Length)
                        {
                            int n = s.Read(buf, got, buf.Length - got);
                            if (n <= 0) break;
                            got += n;
                        }
                    }
                    catch (IOException ex) { throw Lost(ex); }
                    cut = got > cap;
                    if (cut) { req.Abort(); got = cap; }
                    var data = new byte[got];
                    Array.Copy(buf, data, got);
                    return data;
                }
            });
            truncated = cut;
            return result;
        }

        // 大きなファイルを partPath へ。通信が切れたら、そこまでの続きから(Range)やり直す。
        // expectRev があれば、やり直しの間に中身が置き換わっていないかを Dropbox-API-Result の rev で確かめる
        // progress(ここまでに書いたバイト数)
        public void DownloadFile(string path, string expectRev, string partPath, Action<long> progress)
        {
            if (File.Exists(partPath)) File.Delete(partPath);
            WithRetry("files/download", DownloadRetries, () =>
            {
                long have = File.Exists(partPath) ? new FileInfo(partPath).Length : 0;
                var req = DownloadRequest(path, have);
                using (var resp = GetResponse(req))
                {
                    string rev = RevOf(resp.Headers["Dropbox-API-Result"]);
                    if (!string.IsNullOrEmpty(expectRev) && !string.IsNullOrEmpty(rev) && rev != expectRev)
                    {
                        req.Abort();
                        throw new DropboxException("受け取っている間に、送り先で作り直されました。「更新」を押してから、もう一度「受け取る」を押してください。", -1, "");
                    }
                    bool resume = have > 0 && resp.StatusCode == HttpStatusCode.PartialContent;
                    if (!resume) have = 0;
                    if (have > 0) Log("download: resume from " + have);
                    using (var s = resp.GetResponseStream())
                    using (var fs = new FileStream(partPath, resume ? FileMode.Append : FileMode.Create, FileAccess.Write, FileShare.None))
                    {
                        var buf = new byte[256 * 1024];
                        long done = have;
                        if (progress != null) progress(done);
                        while (true)
                        {
                            if (IsCanceled()) { req.Abort(); throw new CanceledException(); }
                            int n;
                            try { n = s.Read(buf, 0, buf.Length); }
                            catch (IOException ex) { throw Lost(ex); }
                            catch (WebException ex) { throw Lost(ex); }
                            if (n <= 0) break;
                            fs.Write(buf, 0, n);
                            done += n;
                            if (progress != null) progress(done);
                        }
                    }
                }
                return true;
            });
        }

        HttpWebRequest DownloadRequest(string path, long from)
        {
            var req = NewPost(ContentBase + "files/download");
            req.Headers["Dropbox-API-Arg"] = DropboxArgs.Download(path);
            req.ContentLength = 0;   // 本文は無い(Content-Type も付けない。Dropbox の例と同じ)
            req.Timeout = 2 * 60 * 1000;
            req.ReadWriteTimeout = 5 * 60 * 1000;
            if (from > 0) req.AddRange(from);
            return req;
        }

        static HttpWebResponse GetResponse(HttpWebRequest req)
        {
            return Net(() => (HttpWebResponse)req.GetResponse());
        }

        static string RevOf(string resultHeader)
        {
            if (string.IsNullOrEmpty(resultHeader)) return null;
            try { return Json.Str(Json.Parse(resultHeader), "rev"); }
            catch (Exception) { return null; }
        }

        void Wait(int attempt)
        {
            int ms = 2000 * attempt * attempt;
            for (int t = 0; t < ms; t += 200)
            {
                if (IsCanceled()) throw new CanceledException();
                Thread.Sleep(200);
            }
        }

        string Send(string endpoint, string argJson, byte[] data, Action<long> progress)
        {
            var req = NewPost(ContentBase + endpoint);
            req.Headers["Dropbox-API-Arg"] = argJson;
            req.ContentType = "application/octet-stream";
            req.ContentLength = data.Length;
            req.AllowWriteStreamBuffering = false;
            req.SendChunked = false;
            req.Timeout = 10 * 60 * 1000;
            req.ReadWriteTimeout = 5 * 60 * 1000;
            Net(() =>
            {
                using (var s = req.GetRequestStream())
                {
                    const int step = 256 * 1024;
                    for (int pos = 0; pos < data.Length; pos += step)
                    {
                        if (IsCanceled()) { req.Abort(); throw new CanceledException(); }
                        int n = Math.Min(step, data.Length - pos);
                        s.Write(data, pos, n);
                        if (progress != null) progress(pos + n);
                    }
                }
            });
            return ReadResponse(req);
        }

        static string ReadResponse(HttpWebRequest req)
        {
            return Net(() =>
            {
                using (var resp = (HttpWebResponse)req.GetResponse())
                using (var r = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    return r.ReadToEnd();
            });
        }

        static DropboxException Wrap(WebException ex)
        {
            var resp = ex.Response as HttpWebResponse;
            if (resp == null)
                return new DropboxException("インターネットにつながりません。つながっているか確かめて、もう一度送ってください。(" + ex.Status + ")", 0, "");
            string body = "";
            try
            {
                using (var r = new StreamReader(resp.GetResponseStream(), Encoding.UTF8)) body = r.ReadToEnd();
            }
            catch (Exception) { }
            int status = (int)resp.StatusCode;
            resp.Close();
            return new DropboxException(ErrorText.FromDropbox(status, body), status, body);
        }
    }
}
