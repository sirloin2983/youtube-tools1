// 切り抜き依頼(RequestSender)の画面に依らない部品: URL の読み取り・依頼の id・依頼の JSON・Dropbox のヘッダーの JSON・
// 大きな動画の分け方・設定(config.json)・メンバーの一覧。テスト(tests\CoreTests.cs)はここを確かめる。
// 設計: docs/design/friend-intake.md の 4・5・7
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace RequestSender
{
    public static class AppInfo
    {
        public const string Title = "切り抜き依頼";
        public const string Version = "1.0.0";
    }

    // ---- 配信の URL ----
    public static class YouTubeUrl
    {
        static readonly Regex IdRx = new Regex("^[A-Za-z0-9_-]{11}$");
        static readonly string[] Hosts = { "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com" };

        public static string Normalize(string id)
        {
            return "https://www.youtube.com/watch?v=" + id;
        }

        // watch?v= / youtu.be/ / /live/ / /shorts/ の形から 11 文字の id を取り出す。それ以外は null(任意の URL を先へ渡さない)
        public static string ExtractId(string text)
        {
            if (text == null) return null;
            string s = text.Trim();
            if (s.Length == 0 || s.Length > 2048) return null;
            if (!Regex.IsMatch(s, "^https?://", RegexOptions.IgnoreCase)) s = "https://" + s;
            Uri u;
            if (!Uri.TryCreate(s, UriKind.Absolute, out u)) return null;
            if (u.Scheme != "https" && u.Scheme != "http") return null;
            if (!string.IsNullOrEmpty(u.UserInfo) || !u.IsDefaultPort) return null;
            string host = u.Host.ToLowerInvariant();
            string[] seg = u.AbsolutePath.Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries);
            string id = null;
            if (host == "youtu.be" || host == "www.youtu.be")
            {
                if (seg.Length >= 1) id = seg[0];
            }
            else if (Hosts.Contains(host))
            {
                if (seg.Length == 1 && seg[0] == "watch") id = QueryValue(u.Query, "v");
                else if (seg.Length >= 2 && (seg[0] == "live" || seg[0] == "shorts")) id = seg[1];
            }
            return id != null && IdRx.IsMatch(id) ? id : null;
        }

        static string QueryValue(string query, string key)
        {
            if (string.IsNullOrEmpty(query)) return null;
            foreach (string part in query.TrimStart('?').Split('&'))
            {
                int eq = part.IndexOf('=');
                if (eq > 0 && part.Substring(0, eq) == key) return Uri.UnescapeDataString(part.Substring(eq + 1));
            }
            return null;
        }
    }

    public class UrlParseResult
    {
        public List<string> Urls = new List<string>();   // 正規化したもの(重ねない)
        public List<string> Errors = new List<string>(); // 「3 行目: 〜」
    }

    public static class Validation
    {
        public const int MinTop = 1, MaxTop = 10, DefaultTop = 3;
        public static readonly string[] VideoExts = { ".mp4", ".mov", ".mkv", ".webm", ".m4v" };

        // 1行に1本。空の行は飛ばす。同じ配信は1つにまとめる
        public static UrlParseResult ParseUrlLines(string text)
        {
            var r = new UrlParseResult();
            var seen = new HashSet<string>();
            string[] lines = (text ?? "").Replace("\r\n", "\n").Replace('\r', '\n').Split('\n');
            for (int i = 0; i < lines.Length; i++)
            {
                string line = lines[i].Trim();
                if (line.Length == 0) continue;
                string id = YouTubeUrl.ExtractId(line);
                if (id == null)
                {
                    r.Errors.Add((i + 1) + " 行目: YouTube の配信・動画の URL ではありません(" + Shorten(line, 40) + ")");
                    continue;
                }
                if (seen.Add(id)) r.Urls.Add(YouTubeUrl.Normalize(id));
            }
            return r;
        }

        public static bool IsVideoFile(string path)
        {
            string ext = (Path.GetExtension(path ?? "") ?? "").ToLowerInvariant();
            return VideoExts.Contains(ext);
        }

        public static bool TopInRange(int n)
        {
            return n >= MinTop && n <= MaxTop;
        }

        public static string Shorten(string s, int max)
        {
            return s.Length <= max ? s : s.Substring(0, max) + "…";
        }
    }

    // ---- 依頼の id と JSON ----
    public static class RequestId
    {
        static readonly Regex Rx = new Regex("^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$");

        public static string New(DateTime local)
        {
            var b = new byte[3];
            using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(b);
            return Make(local, b);
        }

        public static string Make(DateTime local, byte[] random3)
        {
            return local.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + "-" +
                   random3[0].ToString("x2") + random3[1].ToString("x2") + random3[2].ToString("x2");
        }

        public static bool IsValid(string id)
        {
            return id != null && Rx.IsMatch(id);
        }

        // Dropbox の置き場所(アプリのフォルダの直下)
        public static string VideoPath(string id, string originalFileName)
        {
            return "/" + id + "__" + originalFileName;
        }

        public static string RequestPath(string id)
        {
            return "/" + id + ".request.json";
        }
    }

    public static class JsonText
    {
        // JSON の文字列(引用符つき)。asciiOnly のときは 0x7F と ASCII 以外を \uXXXX にする(Dropbox-API-Arg のヘッダーに必要)
        public static string Quote(string s, bool asciiOnly)
        {
            var sb = new StringBuilder("\"");
            foreach (char c in s ?? "")
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20 || (asciiOnly && c >= 0x7F) || c == (char)0x2028 || c == (char)0x2029)
                            sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }

        public static string IsoNow(DateTimeOffset t)
        {
            return t.ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture);
        }
    }

    public static class RequestJson
    {
        public static string Video(string id, IList<string> uploadedNames, string streamer, string memo, DateTimeOffset sentAt)
        {
            var sb = new StringBuilder();
            sb.Append("{\"v\":1,\"kind\":\"video\",\"id\":").Append(JsonText.Quote(id, false));
            sb.Append(",\"files\":[").Append(string.Join(",", uploadedNames.Select(n => JsonText.Quote(n, false)))).Append(']');
            sb.Append(",\"streamer\":").Append(JsonText.Quote(streamer ?? "", false));
            sb.Append(",\"memo\":").Append(JsonText.Quote(memo ?? "", false));
            sb.Append(",\"sentAt\":").Append(JsonText.Quote(JsonText.IsoNow(sentAt), false));
            return sb.Append('}').ToString();
        }

        public static string Url(string id, IList<string> urls, int top, string memo, DateTimeOffset sentAt)
        {
            var sb = new StringBuilder();
            sb.Append("{\"v\":1,\"kind\":\"url\",\"id\":").Append(JsonText.Quote(id, false));
            sb.Append(",\"items\":[").Append(string.Join(",", urls.Select(u =>
                "{\"url\":" + JsonText.Quote(u, false) + ",\"top\":" + top.ToString(CultureInfo.InvariantCulture) + "}"))).Append(']');
            sb.Append(",\"memo\":").Append(JsonText.Quote(memo ?? "", false));
            sb.Append(",\"sentAt\":").Append(JsonText.Quote(JsonText.IsoNow(sentAt), false));
            return sb.Append('}').ToString();
        }
    }

    // ---- Dropbox の API の引数 ----
    public static class DropboxArgs
    {
        public static string Commit(string path)
        {
            return "{\"path\":" + JsonText.Quote(path, true) + ",\"mode\":\"add\",\"autorename\":true,\"mute\":false}";
        }

        public static string SessionStart()
        {
            return "{\"close\":false}";
        }

        public static string Append(string sessionId, long offset)
        {
            return "{\"cursor\":" + Cursor(sessionId, offset) + ",\"close\":false}";
        }

        public static string Finish(string sessionId, long offset, string path)
        {
            return "{\"cursor\":" + Cursor(sessionId, offset) + ",\"commit\":" + Commit(path) + "}";
        }

        static string Cursor(string sessionId, long offset)
        {
            return "{\"session_id\":" + JsonText.Quote(sessionId, true) + ",\"offset\":" + offset.ToString(CultureInfo.InvariantCulture) + "}";
        }
    }

    public struct Chunk
    {
        public long Offset;
        public int Length;
        public Chunk(long offset, int length) { Offset = offset; Length = length; }
    }

    // 150MB 以下は files/upload で1回。それより大きいものは 8MB ずつ(start に最初の塊・append_v2 に残り・finish は空で閉じる)
    public static class ChunkPlan
    {
        public const long SingleLimit = 150L * 1024 * 1024;
        public const int ChunkSize = 8 * 1024 * 1024;

        public static bool UseSession(long size)
        {
            return size > SingleLimit;
        }

        public static List<Chunk> Plan(long size, int chunkSize)
        {
            if (chunkSize <= 0) throw new ArgumentException("chunkSize");
            var list = new List<Chunk>();
            for (long off = 0; off < size; off += chunkSize)
                list.Add(new Chunk(off, (int)Math.Min(chunkSize, size - off)));
            return list;
        }
    }

    // ---- JSON を読む(設定・メンバー・Dropbox の返事) ----
    public static class Json
    {
        public static IDictionary<string, object> Parse(string text)
        {
            var s = new JavaScriptSerializer();
            s.MaxJsonLength = 16 * 1024 * 1024;
            var o = s.DeserializeObject(text) as IDictionary<string, object>;
            if (o == null) throw new FormatException("JSON の一番外側が { } ではありません");
            return o;
        }

        public static string Str(IDictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) && v is string ? (string)v : null;
        }

        public static IDictionary<string, object> Dict(IDictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) ? v as IDictionary<string, object> : null;
        }

        public static long Long(IDictionary<string, object> d, string key, long dflt)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v == null) return dflt;
            if (v is int) return (int)v;
            if (v is long) return (long)v;
            if (v is decimal) return (long)(decimal)v;
            return dflt;
        }

        public static IEnumerable<IDictionary<string, object>> List(IDictionary<string, object> d, string key)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v)) yield break;
            var list = v as IEnumerable;
            if (list == null || v is string) yield break;
            foreach (object o in list)
            {
                var item = o as IDictionary<string, object>;
                if (item != null) yield return item;
            }
        }
    }

    public class Config
    {
        public string AppKey, RefreshToken;

        // 無い・壊れている・足りないときは FormatException / FileNotFoundException(画面は日本語で伝える)
        public static Config Load(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("config.json が見つかりません", path);
            var d = Json.Parse(File.ReadAllText(path, Encoding.UTF8));
            var c = new Config { AppKey = (Json.Str(d, "appKey") ?? "").Trim(), RefreshToken = (Json.Str(d, "refreshToken") ?? "").Trim() };
            if (c.AppKey.Length == 0 || c.RefreshToken.Length == 0) throw new FormatException("config.json に appKey と refreshToken がありません");
            return c;
        }
    }

    public static class Members
    {
        // holo-colors の members.json(groups[].members[].name)から名前だけ。無い・読めないときは空
        public static List<string> LoadNames(string path)
        {
            var names = new List<string>();
            try
            {
                if (!File.Exists(path)) return names;
                var root = Json.Parse(File.ReadAllText(path, Encoding.UTF8));
                foreach (var g in Json.List(root, "groups"))
                    foreach (var m in Json.List(g, "members"))
                    {
                        string n = (Json.Str(m, "name") ?? "").Trim();
                        if (n.Length > 0 && !names.Contains(n)) names.Add(n);
                    }
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is FormatException || ex is ArgumentException || ex is InvalidOperationException || ex is UnauthorizedAccessException)) throw;
                names.Clear();
            }
            return names;
        }
    }

    // ---- Dropbox のエラーを日本語に ----
    public static class ErrorText
    {
        public static string FromDropbox(int status, string body)
        {
            string summary = "";
            string error = "";
            try
            {
                var d = Json.Parse(body ?? "");
                summary = Json.Str(d, "error_summary") ?? "";
                error = Json.Str(d, "error") ?? "";
            }
            catch (Exception) { }
            string all = (summary + " " + error + " " + (body ?? "")).ToLowerInvariant();
            if (all.Contains("insufficient_space")) return "送り先の Dropbox の空きが足りません。送り先の人に伝えてください。";
            if (all.Contains("invalid_grant") || all.Contains("invalid_access_token") || all.Contains("expired_access_token"))
                return "送るための鍵が使えなくなっています(取り消された可能性があります)。送り先の人に新しい config.json をもらってください。";
            if (all.Contains("invalid_client") || all.Contains("app_key")) return "config.json の appKey が正しくありません。送り先の人に伝えてください。";
            if (all.Contains("missing_scope")) return "鍵に書き込みの権限がありません。送り先の人に伝えてください(files.content.write)。";
            if (all.Contains("disallowed_name") || all.Contains("malformed_path")) return "この名前のファイルは送れません。ファイルの名前を変えてから送ってください。";
            if (status == 429 || all.Contains("too_many")) return "Dropbox が混んでいます。少し待ってからもう一度送ってください。";
            if (status >= 500) return "Dropbox の側で問題が起きています(" + status + ")。少し待ってからもう一度送ってください。";
            string s = summary.Length > 0 ? summary : error;
            return "Dropbox からエラーが返りました(" + status + (s.Length > 0 ? ": " + Validation.Shorten(s, 80) : "") + ")";
        }
    }
}
