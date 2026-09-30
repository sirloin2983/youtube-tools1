// Dropbox の API でアプリのフォルダへアップロードする(HttpWebRequest。標準の .NET Framework だけ)。
//   鍵: config.json の appKey + refreshToken(PKCE で得たもの。secret は使わない)→ /oauth2/token で短い期間の access token を得る
//   150MB 以下は files/upload、それより大きいものは upload_session/start → append_v2 → finish(8MB ずつ・失敗した塊だけやり直す)
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;

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
        const int Retries = 4;

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
            var d = Call("files/upload", DropboxArgs.Commit(dropboxPath), data, 0, data.Length, null);
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
                    var d = Call("files/upload", DropboxArgs.Commit(dropboxPath), buf, 0, buf.Length, progress);
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
                        var d = Call("files/upload_session/start", DropboxArgs.SessionStart(), buf, 0, buf.Length, p);
                        sessionId = Json.Str(d, "session_id");
                        if (string.IsNullOrEmpty(sessionId)) throw new DropboxException("upload_session/start の返事に session_id がありません", 0, "");
                    }
                    else
                    {
                        try
                        {
                            Call("files/upload_session/append_v2", DropboxArgs.Append(sessionId, c.Offset), buf, 0, buf.Length, p);
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
                var fin = Call("files/upload_session/finish", DropboxArgs.Finish(sessionId, size, dropboxPath), new byte[0], 0, 0, null);
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

        // content.dropboxapi.com への1回の呼び出し。通信の失敗・429・5xx は少し待ってやり直す。401 は鍵を取り直して1回だけやり直す
        IDictionary<string, object> Call(string endpoint, string argJson, byte[] data, int offset, int length, Action<long> progress)
        {
            if (accessToken == null) RefreshAccessToken();
            bool refreshed = false;
            for (int attempt = 1; ; attempt++)
            {
                if (IsCanceled()) throw new CanceledException();
                try
                {
                    string text = Send(endpoint, argJson, data, offset, length, progress);
                    return text.Trim().Length == 0 || text.Trim() == "null" ? new Dictionary<string, object>() : Json.Parse(text);
                }
                catch (DropboxException ex)
                {
                    if (ex.Status == 401 && !refreshed)
                    {
                        refreshed = true;
                        RefreshAccessToken();
                        continue;
                    }
                    bool retry = ex.Status == 0 || ex.Status == 429 || ex.Status >= 500;
                    if (!retry || attempt >= Retries) throw;
                    Log(endpoint + " failed (" + ex.Status + "), retry " + attempt);
                    Wait(attempt);
                }
            }
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

        string Send(string endpoint, string argJson, byte[] data, int offset, int length, Action<long> progress)
        {
            var req = (HttpWebRequest)WebRequest.Create(ContentBase + endpoint);
            req.Method = "POST";
            req.Headers["Authorization"] = "Bearer " + accessToken;
            req.Headers["Dropbox-API-Arg"] = argJson;
            req.ContentType = "application/octet-stream";
            req.ContentLength = length;
            req.AllowWriteStreamBuffering = false;
            req.SendChunked = false;
            req.Timeout = 10 * 60 * 1000;
            req.ReadWriteTimeout = 5 * 60 * 1000;
            try
            {
                using (var s = req.GetRequestStream())
                {
                    const int step = 256 * 1024;
                    for (int pos = 0; pos < length; pos += step)
                    {
                        if (IsCanceled()) { req.Abort(); throw new CanceledException(); }
                        int n = Math.Min(step, length - pos);
                        s.Write(data, offset + pos, n);
                        if (progress != null) progress(pos + n);
                    }
                }
            }
            catch (WebException ex)
            {
                throw Wrap(ex);
            }
            catch (IOException ex)
            {
                throw new DropboxException("通信が切れました: " + ex.Message, 0, "");
            }
            return ReadResponse(req);
        }

        static string ReadResponse(HttpWebRequest req)
        {
            try
            {
                using (var resp = (HttpWebResponse)req.GetResponse())
                using (var r = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    return r.ReadToEnd();
            }
            catch (WebException ex)
            {
                throw Wrap(ex);
            }
            catch (IOException ex)
            {
                throw new DropboxException("通信が切れました: " + ex.Message, 0, "");
            }
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
