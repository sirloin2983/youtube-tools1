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
        public const string Version = "1.4.0";
    }

    // ---- PC でどこまでやるか(1回の「送る」ごとに選ぶ。動画と URL の両方にかかる。起動したときはいつも auto) ----
    public static class Flow
    {
        public const string Auto = "auto", Check = "check", Manual = "manual";
        public static readonly string[] All = { Auto, Check, Manual };

        public static bool IsValid(string flow)
        {
            return All.Contains(flow);
        }

        public static string Label(string flow)
        {
            switch (flow)
            {
                case Check: return "② 軽く確認(文字起こしまで)";
                case Manual: return "③ 全部人が行う(解析まで)";
                default: return "① 全自動(パックまで作って届ける)";
            }
        }

        public static string Explain(string flow)
        {
            switch (flow)
            {
                case Check: return "PC が文字起こしまで進めます。送り先の人が字幕を直してから仕上げます。";
                case Manual: return "PC は解析までです。送り先の人が切り抜く所から決めます。";
                default: return "PC がパックまで作ります。字幕の校正前のパックが「受け取る」に届きます。";
            }
        }
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

    // 話す人(人数と名前)。count が 0 = 指定しない(JSON にキーを書かない)
    public static class Speakers
    {
        public const int MaxCount = 10, MaxNameLength = 60;

        // 名前: 前後の空白を除く・空は捨てる・60 文字まで・重複なし・人数を超えた分は捨てる
        public static List<string> CleanNames(IEnumerable<string> raw, int count)
        {
            var names = new List<string>();
            if (raw == null) return names;
            foreach (string r in raw)
            {
                if (names.Count >= count) break;
                string n = (r ?? "").Trim();
                if (n.Length == 0) continue;
                if (n.Length > MaxNameLength) n = n.Substring(0, MaxNameLength);
                if (!names.Contains(n)) names.Add(n);
            }
            return names;
        }

        // ,"speakers":{"count":N,"names":[...]} を返す。指定しない(count が 1〜10 の外)なら ""
        public static string JsonPart(int count, IEnumerable<string> rawNames)
        {
            if (count < 1 || count > MaxCount) return "";
            var names = CleanNames(rawNames, count);
            return ",\"speakers\":{\"count\":" + count.ToString(CultureInfo.InvariantCulture) +
                   ",\"names\":[" + string.Join(",", names.Select(n => JsonText.Quote(n, false))) + "]}";
        }
    }

    // Resolve の映像トラックの数(1〜5。V1〜V数 に同じ動画・字幕はその上)。PC がパックを作る ① 全自動のときだけ JSON に書く
    // (②③ はキーを書かない。範囲の外は既定の 1 にする)
    public static class VideoTracks
    {
        public const int Min = 1, Max = 5, Default = 1;

        public static string JsonPart(string flow, int count)
        {
            if (flow != Flow.Auto) return "";
            if (count < Min || count > Max) count = Default;
            return ",\"videoTracks\":" + count.ToString(CultureInfo.InvariantCulture);
        }

        public static string Hint(int count)
        {
            if (count <= 1) return "V1 に動画、V2 に字幕";
            return "V1〜V" + count + " に同じ動画(重ねて加工する用)、V" + (count + 1) + "(いちばん上)に字幕";
        }
    }

    public static class RequestJson
    {
        public static string Video(string id, IList<string> uploadedNames, string streamer, string memo, string flow, DateTimeOffset sentAt)
        {
            return Video(id, uploadedNames, streamer, memo, flow, sentAt, 0, null);
        }

        public static string Url(string id, IList<string> urls, int top, string memo, string flow, DateTimeOffset sentAt)
        {
            return Url(id, urls, top, memo, flow, sentAt, 0, null);
        }

        public static string Video(string id, IList<string> uploadedNames, string streamer, string memo, string flow, DateTimeOffset sentAt, int speakerCount, IEnumerable<string> speakerNames)
        {
            return Video(id, uploadedNames, streamer, memo, flow, sentAt, speakerCount, speakerNames, VideoTracks.Default);
        }

        public static string Url(string id, IList<string> urls, int top, string memo, string flow, DateTimeOffset sentAt, int speakerCount, IEnumerable<string> speakerNames)
        {
            return Url(id, urls, top, memo, flow, sentAt, speakerCount, speakerNames, VideoTracks.Default);
        }

        public static string Video(string id, IList<string> uploadedNames, string streamer, string memo, string flow, DateTimeOffset sentAt, int speakerCount, IEnumerable<string> speakerNames, int videoTracks)
        {
            var sb = new StringBuilder();
            sb.Append("{\"v\":1,\"kind\":\"video\",\"id\":").Append(JsonText.Quote(id, false));
            sb.Append(",\"flow\":").Append(JsonText.Quote(FlowOrDefault(flow), false));
            sb.Append(",\"files\":[").Append(string.Join(",", uploadedNames.Select(n => JsonText.Quote(n, false)))).Append(']');
            sb.Append(",\"streamer\":").Append(JsonText.Quote(streamer ?? "", false));
            sb.Append(",\"memo\":").Append(JsonText.Quote(memo ?? "", false));
            sb.Append(Speakers.JsonPart(speakerCount, speakerNames));
            sb.Append(VideoTracks.JsonPart(FlowOrDefault(flow), videoTracks));
            sb.Append(",\"sentAt\":").Append(JsonText.Quote(JsonText.IsoNow(sentAt), false));
            return sb.Append('}').ToString();
        }

        public static string Url(string id, IList<string> urls, int top, string memo, string flow, DateTimeOffset sentAt, int speakerCount, IEnumerable<string> speakerNames, int videoTracks)
        {
            var sb = new StringBuilder();
            sb.Append("{\"v\":1,\"kind\":\"url\",\"id\":").Append(JsonText.Quote(id, false));
            sb.Append(",\"flow\":").Append(JsonText.Quote(FlowOrDefault(flow), false));
            sb.Append(",\"items\":[").Append(string.Join(",", urls.Select(u =>
                "{\"url\":" + JsonText.Quote(u, false) + ",\"top\":" + top.ToString(CultureInfo.InvariantCulture) + "}"))).Append(']');
            sb.Append(",\"memo\":").Append(JsonText.Quote(memo ?? "", false));
            sb.Append(Speakers.JsonPart(speakerCount, speakerNames));
            sb.Append(VideoTracks.JsonPart(FlowOrDefault(flow), videoTracks));
            sb.Append(",\"sentAt\":").Append(JsonText.Quote(JsonText.IsoNow(sentAt), false));
            return sb.Append('}').ToString();
        }

        // 知らない値は送らない(画面の選択肢の外の値は全自動に寄せる。PC 側も知らない値は断るか既定にする)
        static string FlowOrDefault(string flow)
        {
            return Flow.IsValid(flow) ? flow : Flow.Auto;
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

        // 受け取る: files/list_folder(本文の JSON)・list_folder/continue・files/download(ヘッダーの JSON。ASCII だけにする)
        public static string ListFolder(string path)
        {
            return "{\"path\":" + JsonText.Quote(path, true) + ",\"recursive\":false,\"include_deleted\":false,\"limit\":500}";
        }

        public static string ListContinue(string cursor)
        {
            return "{\"cursor\":" + JsonText.Quote(cursor, true) + "}";
        }

        // files/delete_v2(本文の JSON)。受け取り終えたパック・読み終えた失敗の知らせを Dropbox から消す
        public static string Delete(string path)
        {
            return "{\"path\":" + JsonText.Quote(path, true) + "}";
        }

        public static string Download(string path)
        {
            return "{\"path\":" + JsonText.Quote(path, true) + "}";
        }
    }

    // ---- 受け取る: PC が「/出力/」に置いたもの ----
    //   <依頼の id>__<題>.zip       … DaVinci Resolve のパック(数 GB のことがある)
    //   <依頼の id>__<題>.失敗.txt  … 自動の処理が失敗した理由(UTF-8・BOM つき・短い)
    public enum OutputKind { Pack, Failure }

    public class OutputEntry
    {
        public OutputKind Kind;
        public string Name, PathLower, PathDisplay, Rev, ContentHash, RequestId, Title;
        public long Size;
        public DateTime Modified;   // 地方時(Dropbox の server_modified)

        // 受け取った記録の鍵。同じ名前で置き直されたら rev が変わるので「まだ」に戻る
        public string Key
        {
            get
            {
                string rest = !string.IsNullOrEmpty(Rev) ? Rev : Size.ToString(CultureInfo.InvariantCulture) + "@" + Modified.ToString("s", CultureInfo.InvariantCulture);
                return (PathLower ?? Name ?? "").ToLowerInvariant() + "|" + rest;
            }
        }

        public string ApiPath { get { return !string.IsNullOrEmpty(PathLower) ? PathLower : OutputFolder.Path + "/" + Name; } }
    }

    public static class OutputFolder
    {
        public const string Path = "/出力";
        public const string FailureSuffix = ".失敗.txt";
        public const int FailureTextCap = 64 * 1024;
        static readonly Regex NameRx = new Regex("^([0-9]{8}-[0-9]{6}-[0-9a-f]{6})__(.+)$");

        // list_folder の返事の entries から、パックと失敗の知らせだけ(フォルダ・他のファイル・途中の .part は出さない)
        public static List<OutputEntry> ParseEntries(IDictionary<string, object> response)
        {
            var list = new List<OutputEntry>();
            foreach (var e in Json.List(response, "entries"))
            {
                if (Json.Str(e, ".tag") != "file") continue;
                string name = Json.Str(e, "name") ?? "";
                var entry = FromName(name);
                if (entry == null) continue;
                entry.PathLower = Json.Str(e, "path_lower");
                entry.PathDisplay = Json.Str(e, "path_display");
                entry.Rev = Json.Str(e, "rev");
                entry.ContentHash = Json.Str(e, "content_hash");
                entry.Size = Json.Long(e, "size", 0);
                entry.Modified = ParseTime(Json.Str(e, "server_modified"));
                list.Add(entry);
            }
            return list;
        }

        // 名前だけで種類・依頼の id・題を決める。-> 対象外は null
        public static OutputEntry FromName(string name)
        {
            if (string.IsNullOrEmpty(name)) return null;
            OutputKind kind;
            string stem;
            if (name.EndsWith(FailureSuffix, StringComparison.OrdinalIgnoreCase)) { kind = OutputKind.Failure; stem = name.Substring(0, name.Length - FailureSuffix.Length); }
            else if (name.EndsWith(".zip", StringComparison.OrdinalIgnoreCase)) { kind = OutputKind.Pack; stem = name.Substring(0, name.Length - 4); }
            else return null;
            if (stem.Length == 0) return null;
            var e = new OutputEntry { Kind = kind, Name = name, Title = stem, RequestId = "" };
            var m = NameRx.Match(stem);
            if (m.Success) { e.RequestId = m.Groups[1].Value; e.Title = m.Groups[2].Value; }
            return e;
        }

        // 新しいものが上。同じ時刻なら名前の順
        public static void SortNewestFirst(List<OutputEntry> list)
        {
            list.Sort((a, b) =>
            {
                int c = b.Modified.CompareTo(a.Modified);
                return c != 0 ? c : string.Compare(a.Name, b.Name, StringComparison.Ordinal);
            });
        }

        // "2026-10-01T03:00:00Z" -> 地方時。読めなければ MinValue
        public static DateTime ParseTime(string s)
        {
            DateTime t;
            if (string.IsNullOrEmpty(s)) return DateTime.MinValue;
            if (DateTime.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out t))
                return DateTime.SpecifyKind(t, DateTimeKind.Utc).ToLocalTime();
            return DateTime.MinValue;
        }

        // 失敗の知らせの本文: BOM を取り、長すぎるものは切る
        public static string DecodeFailureText(byte[] data, int length, bool truncated)
        {
            int start = length >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF ? 3 : 0;
            string s = new UTF8Encoding(false, false).GetString(data, start, Math.Max(0, length - start));
            s = s.Replace("\r\n", "\n").Replace('\r', '\n').Trim('\n', ' ', '﻿').Replace("\n", "\r\n");
            if (truncated) s += "\r\n…(長いので途中まで)";
            return s;
        }
    }

    // ---- 受け取った動画の置き場所(Windows で使える名前・重ならない名前) ----
    public static class LocalName
    {
        static readonly string[] Reserved = { "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                                              "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9" };

        public static string Safe(string name)
        {
            var sb = new StringBuilder();
            var bad = System.IO.Path.GetInvalidFileNameChars();
            foreach (char c in name ?? "") sb.Append(c < 0x20 || bad.Contains(c) ? '_' : c);
            string s = sb.ToString().Trim().TrimEnd('.', ' ');
            if (s.Length == 0 || s == "." || s == "..") s = "download";
            string stem = System.IO.Path.GetFileNameWithoutExtension(s);
            if (Reserved.Contains(stem.ToUpperInvariant())) s = "_" + s;
            if (s.Length > 180)
            {
                string ext = System.IO.Path.GetExtension(s);
                if (ext.Length > 20) ext = "";
                s = s.Substring(0, 180 - ext.Length) + ext;
            }
            return s;
        }

        // dir の中の、まだ無い名前(a.zip → a (2).zip …)。.part も無いもの
        public static string Unique(string dir, string safeName)
        {
            string stem = System.IO.Path.GetFileNameWithoutExtension(safeName), ext = System.IO.Path.GetExtension(safeName);
            for (int i = 1; i < 1000; i++)
            {
                string p = System.IO.Path.Combine(dir, i == 1 ? safeName : stem + " (" + i + ")" + ext);
                if (!File.Exists(p) && !File.Exists(p + ".part") && !Directory.Exists(p)) return p;
            }
            throw new IOException("同じ名前のファイルが多すぎます: " + safeName);
        }
    }

    // ---- 手元の記録(%LOCALAPPDATA%\RequestSender\): 受け取ったもの・受け取る場所 ----
    public class LocalState
    {
        const int MaxRecords = 2000;
        readonly string dir;

        public LocalState(string dir)
        {
            this.dir = dir;
        }

        string ReceivedPath { get { return System.IO.Path.Combine(dir, "received.txt"); } }
        string SettingsPath { get { return System.IO.Path.Combine(dir, "settings.json"); } }

        public static string DefaultDownloadDir()
        {
            return System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "切り抜き依頼");
        }

        public HashSet<string> LoadReceived()
        {
            var set = new HashSet<string>(StringComparer.Ordinal);
            try
            {
                if (File.Exists(ReceivedPath))
                    foreach (string line in File.ReadAllLines(ReceivedPath, Encoding.UTF8))
                        if (line.Trim().Length > 0) set.Add(line.Trim());
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            return set;
        }

        public void MarkReceived(OutputEntry e)
        {
            var lines = new List<string>();
            try { if (File.Exists(ReceivedPath)) lines.AddRange(File.ReadAllLines(ReceivedPath, Encoding.UTF8).Where(l => l.Trim().Length > 0)); }
            catch (IOException) { }
            if (lines.Contains(e.Key)) return;
            lines.Add(e.Key);
            if (lines.Count > MaxRecords) lines = lines.Skip(lines.Count - MaxRecords).ToList();
            WriteAtomic(ReceivedPath, string.Join("\r\n", lines) + "\r\n");
        }

        public string LoadDownloadDir()
        {
            try
            {
                if (File.Exists(SettingsPath))
                {
                    string d = (Json.Str(Json.Parse(File.ReadAllText(SettingsPath, Encoding.UTF8)), "downloadDir") ?? "").Trim();
                    if (d.Length > 0 && System.IO.Path.IsPathRooted(d)) return d;
                }
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is FormatException || ex is ArgumentException || ex is InvalidOperationException || ex is UnauthorizedAccessException)) throw;
            }
            return DefaultDownloadDir();
        }

        public void SaveDownloadDir(string path)
        {
            WriteAtomic(SettingsPath, "{\"downloadDir\":" + JsonText.Quote(path, false) + "}\r\n");
        }

        void WriteAtomic(string path, string text)
        {
            Directory.CreateDirectory(dir);
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, text, new UTF8Encoding(false));
            if (File.Exists(path)) File.Delete(path);
            File.Move(tmp, path);
        }
    }

    // ---- Dropbox の content_hash(4MB ずつの SHA-256 をつないで、もう一度 SHA-256)。受け取ったファイルが壊れていないかを確かめる ----
    public static class ContentHash
    {
        public const int BlockSize = 4 * 1024 * 1024;

        public static string Compute(Stream s, Action<long> progress)
        {
            using (var outer = SHA256.Create())
            using (var inner = SHA256.Create())
            {
                var buf = new byte[BlockSize];
                long total = 0;
                while (true)
                {
                    int got = 0;
                    while (got < BlockSize)
                    {
                        int n = s.Read(buf, got, BlockSize - got);
                        if (n <= 0) break;
                        got += n;
                    }
                    if (got == 0) break;
                    byte[] h = inner.ComputeHash(buf, 0, got);
                    outer.TransformBlock(h, 0, h.Length, null, 0);
                    total += got;
                    if (progress != null) progress(total);
                    if (got < BlockSize) break;
                }
                outer.TransformFinalBlock(new byte[0], 0, 0);
                return string.Concat(outer.Hash.Select(b => b.ToString("x2")));
            }
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

        public static bool Bool(IDictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) && v is bool && (bool)v;
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

        public const string NeedNewKeyForReceive = "受け取るには新しい鍵が要ります。送り先の人に config.json を作り直してもらってください";

        // 鍵に権限が足りない(v1.0.0 の鍵は files.content.write だけ)。401 でも鍵を取り直しても直らない
        public static bool IsMissingScope(string body)
        {
            string b = (body ?? "").ToLowerInvariant();
            return b.Contains("missing_scope") || b.Contains("insufficient_scope") || b.Contains("insufficient scope");
        }

        public static bool IsNotFound(int status, string body)
        {
            return status == 409 && (body ?? "").Contains("not_found");
        }

        // 受け取るときの言い方(「送って」ではなく「押して」)
        public static string ForReceive(int status, string body)
        {
            string all = (body ?? "").ToLowerInvariant();
            if (IsMissingScope(body)) return NeedNewKeyForReceive;
            if (all.Contains("invalid_grant") || all.Contains("invalid_access_token") || all.Contains("expired_access_token"))
                return "鍵が使えなくなっています(取り消された可能性があります)。送り先の人に新しい config.json をもらってください。";
            if (all.Contains("invalid_client") || all.Contains("app_key")) return "config.json の appKey が正しくありません。送り先の人に伝えてください。";
            if (IsNotFound(status, body)) return "送り先の Dropbox にもうありません。「更新」を押してください。";
            if (status == 429 || all.Contains("too_many")) return "Dropbox が混んでいます。少し待ってからもう一度押してください。";
            if (status >= 500) return "Dropbox の側で問題が起きています(" + status + ")。少し待ってからもう一度押してください。";
            return FromDropbox(status, body);
        }
    }
}
