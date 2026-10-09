// 切り抜き依頼(RequestSender)の画面に依らない部品: URL の読み取り・依頼の id・依頼の JSON・Dropbox のヘッダーの JSON・
// 大きな動画の分け方・設定(config.json)・メンバーの一覧・「/出力」の名前の読み取り・手元の記録(settings.json)。テスト(tests\CoreTests.cs)はここを確かめる。
// 設計: docs/spec/friend-intake.md の 4・5・7
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using FriendApps;

namespace RequestSender
{
    public static class AppInfo
    {
        public const string Title = "切り抜き依頼";
        public const string Version = "2.9.0";
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

    public static class Validation
    {
        public const int MinTop = 1, MaxTop = 10, DefaultTop = 3;
        public static readonly string[] VideoExts = { ".mp4", ".mov", ".mkv", ".webm", ".m4v" };

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

    // 配信者(人数と、1 人ずつの名前 + 字幕の色)。人数が 0 = 指定しない(JSON にキーを書かない)
    public static class Speakers
    {
        public const int MaxCount = 10, MaxNameLength = 60;

        // 字幕の色 = # なしの 16 進 6 桁
        public const int ColorLength = 6;

        // 色の欄に打つ・貼ったものを整える: 前後の空白と先頭の # を除く・16 進以外の文字は捨てる・大文字・6 文字まで
        // (貼り付けた「#ff00aa」→「FF00AA」。打っている途中でも使う = 途中の長さのまま返す)
        public static string CleanColor(string raw)
        {
            var sb = new StringBuilder();
            foreach (char c in (raw ?? "").Trim().TrimStart('#'))
            {
                if (sb.Length >= ColorLength) break;
                if (c >= '0' && c <= '9' || c >= 'a' && c <= 'f' || c >= 'A' && c <= 'F') sb.Append(char.ToUpperInvariant(c));
            }
            return sb.ToString();
        }

        // 厳しく読む: 前後の空白と先頭の # 1つだけ許し、あとは 16 進のちょうど 6 桁。-> 大文字の "RRGGBB"。違えば null
        public static string ParseColor(string raw)
        {
            string s = (raw ?? "").Trim();
            if (s.StartsWith("#")) s = s.Substring(1);
            if (s.Length != ColorLength) return null;
            foreach (char c in s) if (!(c >= '0' && c <= '9' || c >= 'a' && c <= 'f' || c >= 'A' && c <= 'F')) return null;
            return s.ToUpperInvariant();
        }

        // 色の欄に何か入っているか(# と空白だけなら空とみなす)
        public static bool HasColorText(string raw)
        {
            return (raw ?? "").Trim().TrimStart('#').Length > 0;
        }

        // 送る前の検査: 色だけ入れて名前が空・色が 6 桁そろっていない行を、行の順に返す(人数の外の行は見ない)。1行につき1つ
        public static List<SpeakerProblem> Problems(SpeakerSet set)
        {
            var list = new List<SpeakerProblem>();
            if (set == null || set.Count < 1) return list;
            for (int i = 0; i < set.Count && i < set.Rows.Count; i++)
            {
                var r = set.Rows[i];
                if (r == null || !HasColorText(r.Color)) continue;
                if (((r.Name ?? "").Trim()).Length == 0)
                    list.Add(new SpeakerProblem { Index = i, OnColor = false, Message = "名前も入れてください(色だけでは、だれの色か決まりません)" });
                else if (ParseColor(r.Color) == null)
                    list.Add(new SpeakerProblem { Index = i, OnColor = true, Message = "色は 16 進の 6 桁で入れてください(0〜9 と A〜F。例: FF00AA)" });
            }
            return list;
        }

        // 人数の範囲の中で、名前のある行だけ(入力の順)。名前は整える・同じ名前は先の行にまとめる(先の行に色が無ければ後の行の色を使う)。色は 6 桁そろったものだけ
        public static List<SpeakerRow> CleanRows(SpeakerSet set)
        {
            var rows = new List<SpeakerRow>();
            if (set == null || set.Count < 1) return rows;
            for (int i = 0; i < set.Count && i < set.Rows.Count; i++)
            {
                var r = set.Rows[i];
                if (r == null) continue;
                string name = (r.Name ?? "").Trim();
                if (name.Length == 0) continue;
                if (name.Length > MaxNameLength) name = name.Substring(0, MaxNameLength);
                string color = ParseColor(r.Color) ?? "";
                var same = rows.FirstOrDefault(x => x.Name == name);
                if (same == null) rows.Add(new SpeakerRow(name, color));
                else if (same.Color.Length == 0) same.Color = color;
            }
            return rows;
        }

        // 1 人目の名前(1 人目の行が空なら "")。依頼の "streamer" に入れる
        public static string StreamerName(SpeakerSet set)
        {
            if (set == null || set.Count < 1 || set.Rows.Count < 1 || set.Rows[0] == null) return "";
            string n = (set.Rows[0].Name ?? "").Trim();
            return n.Length > MaxNameLength ? n.Substring(0, MaxNameLength) : n;
        }

        // ,"speakers":{"count":3,"names":["A","B"],"people":[{"name":"A","style":{"color":"FF00AA"}},{"name":"B"}]}
        // 人数が 0(1〜10 の外)ならキーごと書かない。names は古い PC のために今までどおり。people は名前のある行だけ・style は色を入れた行だけ。
        // 名前のある行が無ければ people は書かない。あとで字幕の見た目(フォントなど)を足すときは style に鍵を足す
        public static string JsonPart(SpeakerSet set)
        {
            if (set == null || set.Count < 1 || set.Count > MaxCount) return "";
            var rows = CleanRows(set);
            var sb = new StringBuilder(",\"speakers\":{\"count\":");
            sb.Append(set.Count.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"names\":[").Append(string.Join(",", rows.Select(r => JsonText.Quote(r.Name, false)))).Append(']');
            if (rows.Count > 0)
                sb.Append(",\"people\":[").Append(string.Join(",", rows.Select(r =>
                    "{\"name\":" + JsonText.Quote(r.Name, false) + (r.Color.Length > 0 ? ",\"style\":{\"color\":" + JsonText.Quote(r.Color, false) + "}" : "") + "}"))).Append(']');
            return sb.Append('}').ToString();
        }
    }

    // 画面の 1 行(配信者 1 人分): 名前と字幕の色(# なしの 16 進 6 桁・空 = 指定しない)
    public class SpeakerRow
    {
        public string Name = "", Color = "";

        public SpeakerRow() { }

        public SpeakerRow(string name, string color)
        {
            Name = name ?? "";
            Color = color ?? "";
        }
    }

    // 「配信者の数」と、その人数分の行(0 = 指定しない)
    public class SpeakerSet
    {
        public int Count;
        public List<SpeakerRow> Rows = new List<SpeakerRow>();
    }

    // 送る前の検査で見つけた誤り(Index = 何行目か・0 始まり。OnColor = 色の欄の誤り / false = 名前の欄の誤り)
    public class SpeakerProblem
    {
        public int Index;
        public bool OnColor;
        public string Message = "";
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

    // 届け方(2.8.0。docs/spec/friend-intake.md の 2-16): 1 = 1 本ずつ / n = n 本の組(まとめ動画 1 本 + 1 本ずつの zip)。
    // ① 全自動の依頼(url・video・ライブ配信)だけ JSON に書く(②③ はパックを届けない)。1〜10 の外は書かない(= PC の設定 intake.deliverBatch)。
    // ライブ配信の依頼(2.9.0)も書く: PC は依頼ごとに n 本たまったら組で届け、録画が終わったら残りを届ける。配信後のアーカイブからの追加は別の組になる
    public static class DeliverBatch
    {
        public const int Min = 1, Max = 10, Default = 1;

        public static bool InRange(int n)
        {
            return n >= Min && n <= Max;
        }

        public static string JsonPart(string flow, int n)
        {
            if (flow != Flow.Auto || !InRange(n)) return "";
            return ",\"deliverBatch\":" + n.ToString(CultureInfo.InvariantCulture);
        }

        public static string Label(int n)
        {
            return n <= 1 ? "1 本ずつ" : n + " 本ごと";
        }

        // ① 全自動の説明(届け方で変わる。「02 仕上げ方」の下の文)
        public static string Hint(int n)
        {
            if (n <= 1) return "PC がパックまで作ります。字幕の校正前のパックが、できた順に 1 本ずつ「受け取る」に届きます。";
            return "PC がパックまで作ります。" + n + " 本の組で「受け取る」に届き、まとめ動画を見て 1 本ずつ選べます。";
        }

        // ライブ配信の説明(2.9.0。「02 仕上げ方」の下の文)
        public static string LiveHint(int n)
        {
            if (n <= 1) return "ライブ配信の依頼は ① 全自動だけです。切り抜けしだい、1 本ずつ「受け取る」に届きます。";
            return "ライブ配信の依頼は ① 全自動だけです。切り抜きが " + n + " 本たまるごとに組で「受け取る」に届き、録画が終わると残りが届きます(配信後のアーカイブから足した分は別の組)。";
        }
    }

    // 依頼の JSON(キーの順番も受け取る側の約束)。配信者は SpeakerSet(名前 + 字幕の色)。flow の知らない値は ① に寄せる。
    // deliverBatch(2.8.0・届け方。ライブ配信は 2.9.0 から)は ① のときだけ・1〜10 のときだけ、sentAt の直前に書く(0 = 書かない = PC の設定)
    public static class RequestJson
    {
        // 動画の依頼。"streamer" は 1 人目の名前(無ければ空文字)。speakers には names と people(名前と style.color)が入る。cut は ① のときだけ書く
        public static string Video(string id, IList<string> uploadedNames, string memo, string flow, DateTimeOffset sentAt, SpeakerSet speakers, int videoTracks, string cut, int deliverBatch = 0)
        {
            string f = FlowOrDefault(flow);
            var sb = new StringBuilder();
            sb.Append("{\"v\":1,\"kind\":\"video\",\"id\":").Append(JsonText.Quote(id, false));
            sb.Append(",\"flow\":").Append(JsonText.Quote(f, false));
            sb.Append(",\"files\":[").Append(string.Join(",", uploadedNames.Select(n => JsonText.Quote(n, false)))).Append(']');
            sb.Append(",\"streamer\":").Append(JsonText.Quote(Speakers.StreamerName(speakers), false));
            sb.Append(",\"memo\":").Append(JsonText.Quote(memo ?? "", false));
            sb.Append(Speakers.JsonPart(speakers));
            sb.Append(VideoTracks.JsonPart(f, videoTracks));
            sb.Append(Cut.JsonPart(f, cut));
            sb.Append(DeliverBatch.JsonPart(f, deliverBatch));
            return Finish(sb, sentAt);
        }

        // URL の依頼。配信ごとの切り抜く数と区間・カット(① のときだけ)・解析の重み(指定したときだけ)。
        // 1 人目の名前があれば "streamer" も書く(items の後・memo の前。無ければ書かない)
        public static string Url(string id, IList<UrlItem> items, string memo, string flow, DateTimeOffset sentAt, SpeakerSet speakers, int videoTracks, string cut, Weights weights, int deliverBatch = 0)
        {
            string f = FlowOrDefault(flow);
            string streamer = Speakers.StreamerName(speakers);
            var sb = new StringBuilder();
            sb.Append("{\"v\":1,\"kind\":\"url\",\"id\":").Append(JsonText.Quote(id, false));
            sb.Append(",\"flow\":").Append(JsonText.Quote(f, false));
            sb.Append(",\"items\":[").Append(string.Join(",", items.Select(u =>
                "{\"url\":" + JsonText.Quote(u.Url, false) + ",\"top\":" + u.EffectiveTop(f).ToString(CultureInfo.InvariantCulture) + Ranges.JsonPart(f, u.Ranges) + "}"))).Append(']');
            if (streamer.Length > 0) sb.Append(",\"streamer\":").Append(JsonText.Quote(streamer, false));
            sb.Append(",\"memo\":").Append(JsonText.Quote(memo ?? "", false));
            sb.Append(Speakers.JsonPart(speakers));
            sb.Append(VideoTracks.JsonPart(f, videoTracks));
            sb.Append(Cut.JsonPart(f, cut));
            if (weights != null) sb.Append(weights.JsonPart());
            sb.Append(DeliverBatch.JsonPart(f, deliverBatch));
            return Finish(sb, sentAt);
        }

        // ライブ配信の依頼(2.8.0。docs/spec/friend-intake.md の 2-15): 配信の URL 1 本(正規化済み)・flow は auto 固定・友人のベータの設定 live。
        // 鍵の順: v kind id flow url streamer memo [speakers] videoTracks cut live sentAt。streamer は 1 人目の名前(無ければ空文字)。届け方 deliverBatch は live の後・sentAt の直前(2.9.0。1〜10 のときだけ。0 や範囲の外は書かない = PC の設定)
        public static string Live(string id, string url, string memo, DateTimeOffset sentAt, SpeakerSet speakers, int videoTracks, string cut, LiveSettings live, int deliverBatch = 0)
        {
            var sb = new StringBuilder();
            sb.Append("{\"v\":1,\"kind\":\"live\",\"id\":").Append(JsonText.Quote(id, false));
            sb.Append(",\"flow\":").Append(JsonText.Quote(Flow.Auto, false));
            sb.Append(",\"url\":").Append(JsonText.Quote(url, false));
            sb.Append(",\"streamer\":").Append(JsonText.Quote(Speakers.StreamerName(speakers), false));
            sb.Append(",\"memo\":").Append(JsonText.Quote(memo ?? "", false));
            sb.Append(Speakers.JsonPart(speakers));
            sb.Append(VideoTracks.JsonPart(Flow.Auto, videoTracks));
            sb.Append(Cut.JsonPart(Flow.Auto, cut));
            sb.Append((live ?? new LiveSettings()).JsonPart());
            sb.Append(DeliverBatch.JsonPart(Flow.Auto, deliverBatch));
            return Finish(sb, sentAt);
        }

        static string Finish(StringBuilder sb, DateTimeOffset sentAt)
        {
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
    // ---- 「要らない」の記録(2.6.0): 受け取らずに消したパックを PC に知らせる。受付のフォルダの直下に <zip の名前(.zip 抜き)>.feedback.json(PC の受付が読む) ----
    public static class FeedbackJson
    {
        public const string Suffix = ".feedback.json";

        public static string PathFor(OutputEntry e)
        {
            string stem = e.Name.EndsWith(".zip", StringComparison.OrdinalIgnoreCase) ? e.Name.Substring(0, e.Name.Length - 4) : e.Name;
            return "/" + stem + Suffix;
        }

        public static string Reject(OutputEntry e, DateTimeOffset now)
        {
            return "{\"v\":1,\"kind\":\"feedback\",\"verdict\":\"reject\",\"zip\":" + JsonText.Quote(e.Name, false) +
                   ",\"requestId\":" + JsonText.Quote(e.RequestId ?? "", false) + ",\"title\":" + JsonText.Quote(e.Title ?? "", false) +
                   ",\"sentAt\":" + JsonText.Quote(now.ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture), false) + "}";
        }
    }

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
    //   <依頼の id>__<題>.zip             … DaVinci Resolve のパック(数 GB のことがある。PC が n 本をまとめると「<題> 1-5.zip」で、中に <題>_pack が並ぶ)
    //   <依頼の id>__<題>.失敗.txt        … 自動の処理が失敗した理由(UTF-8・BOM つき・短い)
    //   <zip の名前>.preview.mp4          … zip の隣のまとめ動画(n 本をつなげた等速の確認用。小さい。同じ名前の zip に結びつけ、一覧には出さない)
    //   <依頼の id>__<題> 1-5.group.json  … 組(2.8.0。2-16): まとめ動画 1 本 + 1 本ずつの zip の一覧。中身を読んで zip とまとめ動画を組に結びつける
    public enum OutputKind { Pack, Failure, Preview, Group }

    public class OutputEntry
    {
        public OutputKind Kind;
        public string Name, PathLower, Rev, ContentHash, RequestId, Title;
        public long Size;
        public DateTime Modified;   // 地方時(Dropbox の server_modified)
        public OutputEntry Preview;  // パックの隣のまとめ動画(無ければ null)。組なら組のまとめ動画
        public GroupInfo Info;       // (組)読んだ .group.json の中身(読めない・壊れていれば null = 一覧に出さない)
        public List<OutputEntry> Members = new List<OutputEntry>();   // (組)いま届いている 1 本ずつの zip(n の順。受け取った・要らないにしたものは外す)
        public OutputEntry Parent;   // (パック)属する組(無ければ null)
        public GroupPack Slot;       // (パック)組の中での n・まとめ動画の中で始まる秒・長さ

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
        public const string PackSuffix = ".zip";
        public const string FailureSuffix = ".失敗.txt";
        public const string PreviewSuffix = ".preview.mp4";
        public const string GroupSuffix = ".group.json";
        public const int FailureTextCap = 64 * 1024;
        public const int GroupTextCap = 64 * 1024;   // .group.json はこれより大きければ読まない(組を出さない)
        static readonly Regex NameRx = new Regex("^([0-9]{8}-[0-9]{6}-[0-9a-f]{6})__(.+)$");
        static readonly OutputKind[] Kinds = { OutputKind.Failure, OutputKind.Preview, OutputKind.Group, OutputKind.Pack };

        // 種類ごとの名前の終わり
        static string SuffixOf(OutputKind kind)
        {
            switch (kind)
            {
                case OutputKind.Failure: return FailureSuffix;
                case OutputKind.Preview: return PreviewSuffix;
                case OutputKind.Group: return GroupSuffix;
                default: return PackSuffix;
            }
        }

        // 名前から種類の終わりを除いたもの(まとめ動画とパックはこれが同じなら組)
        static string StemOf(OutputEntry e)
        {
            return e.Name.Substring(0, e.Name.Length - SuffixOf(e.Kind).Length);
        }

        // list_folder の返事の entries から、パック・失敗の知らせ・まとめ動画・組の一覧だけ(フォルダ・他のファイル・途中の .part は出さない)
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
            foreach (var kind in Kinds)
            {
                string suffix = SuffixOf(kind);
                if (!name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)) continue;
                string stem = name.Substring(0, name.Length - suffix.Length);
                if (stem.Length == 0) return null;
                var e = new OutputEntry { Kind = kind, Name = name, Title = stem, RequestId = "" };
                var m = NameRx.Match(stem);
                if (m.Success) { e.RequestId = m.Groups[1].Value; e.Title = m.Groups[2].Value; }
                return e;
            }
            return null;
        }

        // まとめ動画(<zip の名前>.preview.mp4)を同じ名前のパックに結びつけ、一覧からは外す。
        // 相手のいないまとめ動画は出さない(zip がまだ同期されていない = PC は zip より先に置く / zip を消したあと消し損ねた)。消しもしない
        public static List<OutputEntry> AttachPreviews(List<OutputEntry> list)
        {
            var packs = new Dictionary<string, OutputEntry>(StringComparer.OrdinalIgnoreCase);
            foreach (var e in list) if (e.Kind == OutputKind.Pack) packs[StemOf(e)] = e;
            var rest = new List<OutputEntry>();
            foreach (var e in list)
            {
                if (e.Kind != OutputKind.Preview) { rest.Add(e); continue; }
                OutputEntry p;
                if (packs.TryGetValue(StemOf(e), out p)) p.Preview = e;
            }
            return rest;
        }

        // 一覧の並び(2.8.0): 組(.group.json。Info を読んであるもの)に、名前の一致する zip とまとめ動画を結びつけ、
        // 組の行のすぐ下にその組の 1 本ずつの行(n の順)を並べる。ほかの行(組に入らない zip・失敗の知らせ)と組の行は新しい順。
        //   - 組の中の zip が 1 本も届いていない組は出さない(.group.json は消さない = 同期の途中かもしれない)。Info の無い組(読めない・壊れている)も出さない
        //   - 組のまとめ動画は組に付ける(一覧には出さない)。組に入らない zip には今までどおり同じ名前のまとめ動画(AttachPreviews)
        //   - 結びつけるのは一覧にある名前どうしだけ(.group.json に書かれた名前で Dropbox の場所を作らない)
        public static List<OutputEntry> Arrange(List<OutputEntry> raw)
        {
            var packs = new Dictionary<string, OutputEntry>(StringComparer.OrdinalIgnoreCase);
            var previews = new Dictionary<string, OutputEntry>(StringComparer.OrdinalIgnoreCase);
            foreach (var e in raw)
            {
                e.Parent = null;
                e.Slot = null;
                if (e.Kind == OutputKind.Pack) packs[e.Name] = e;
                else if (e.Kind == OutputKind.Preview) previews[e.Name] = e;
            }
            var groups = new List<OutputEntry>();
            var usedPreviews = new HashSet<OutputEntry>();
            foreach (var g in raw.Where(x => x.Kind == OutputKind.Group))
            {
                g.Members = new List<OutputEntry>();
                g.Preview = null;
                if (g.Info == null) continue;
                foreach (var slot in g.Info.Packs)
                {
                    OutputEntry p;
                    if (!packs.TryGetValue(slot.Zip, out p) || p.Parent != null) continue;   // 2 つの組に同じ zip が書かれていたら先の組
                    p.Parent = g;
                    p.Slot = slot;
                    g.Members.Add(p);
                }
                if (g.Members.Count == 0) continue;
                OutputEntry pv;
                if (g.Info.Preview.Length > 0 && previews.TryGetValue(g.Info.Preview, out pv) && usedPreviews.Add(pv)) g.Preview = pv;
                groups.Add(g);
            }
            var rest = AttachPreviews(raw.Where(x => x.Kind != OutputKind.Group && !usedPreviews.Contains(x)).ToList());
            var top = groups.Concat(rest.Where(x => x.Parent == null)).ToList();
            SortNewestFirst(top);
            var list = new List<OutputEntry>();
            foreach (var t in top)
            {
                list.Add(t);
                if (t.Kind == OutputKind.Group) list.AddRange(t.Members);
            }
            return list;
        }

        // 届いているものの数(タブの ●n・窓の題名): パックと失敗の知らせ(組の行は数えない。その中の 1 本ずつを数える)
        public static int CountItems(IEnumerable<OutputEntry> entries)
        {
            return entries.Count(e => e != null && e.Kind != OutputKind.Group);
        }

        // 組の行の題: 「<題> 1-5(5 本)」。受け取った・要らないにしたものがあれば「(残り 3 / 5 本)」
        public static string GroupLabel(OutputEntry g)
        {
            if (g == null) return "";
            string title = g.Info != null && g.Info.Title.Length > 0 ? g.Info.Title : g.Title;
            string range = g.Info != null && g.Info.Range.Length > 0 ? " " + g.Info.Range : "";
            int all = g.Info != null ? g.Info.Packs.Count : g.Members.Count, left = g.Members.Count;
            return title + range + "(" + (left < all ? "残り " + left + " / " + all : left.ToString(CultureInfo.InvariantCulture)) + " 本)";
        }

        // 片付けた(受け取って Dropbox から消した・要らないにした)パックのうち、組の残りが全部そろったもの = 組の最後の 1 本まで片付けた組。
        // 呼んだ側は .group.json と組のまとめ動画を Dropbox から消す(組の途中なら消さない)
        public static List<OutputEntry> GroupsDone(IEnumerable<OutputEntry> handled)
        {
            var set = new HashSet<OutputEntry>(handled.Where(e => e != null));
            return set.Where(e => e.Parent != null).Select(e => e.Parent).Distinct()
                      .Where(g => g.Members.All(set.Contains)).ToList();
        }

        // 新しいものが上(一覧の順)
        public static void SortNewestFirst(List<OutputEntry> list)
        {
            list.Sort((a, b) => CompareTime(a, b, true));
        }

        // 「すべて受け取る」の順: パックだけを古い順(1 つの依頼で何本もできたパックは、できた順に並ぶ)。失敗の知らせは含めない
        public static List<OutputEntry> PacksOldestFirst(IEnumerable<OutputEntry> entries)
        {
            var packs = entries.Where(e => e.Kind == OutputKind.Pack).ToList();
            packs.Sort((a, b) => CompareTime(a, b, false));
            return packs;
        }

        // 時刻の順(newestFirst なら新しいものが先)。同じ時刻なら、どちらの向きでも名前の順
        static int CompareTime(OutputEntry a, OutputEntry b, bool newestFirst)
        {
            int c = newestFirst ? b.Modified.CompareTo(a.Modified) : a.Modified.CompareTo(b.Modified);
            return c != 0 ? c : string.Compare(a.Name, b.Name, StringComparison.Ordinal);
        }

        // 合計の大きさ(分からないもの = 負の値は 0 として足す)
        public static long TotalSize(IEnumerable<OutputEntry> entries)
        {
            long total = 0;
            foreach (var e in entries) total += Math.Max(0, e.Size);
            return total;
        }

        // 同じ依頼(id)のパックが、いま届いている中に何本あるか(自分を含む。id の無いものは 0)
        public static int CountSameRequest(IEnumerable<OutputEntry> entries, OutputEntry e)
        {
            if (string.IsNullOrEmpty(e.RequestId)) return 0;
            return entries.Count(x => x.Kind == OutputKind.Pack && x.RequestId == e.RequestId);
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

    // ---- 組の一覧(.group.json。2.8.0。docs/spec/friend-intake.md の 2-16)----
    //   {"v":1,"title":"<題>","range":"1-5","preview":"<組のまとめ動画の名前>","packs":[{"n":1,"zip":"<zip の名前>","title":"<パックの題>","previewStart":0.0,"duration":48.2}, …],"sentAt":"…"}
    //   鍵を知る人なら置けるので、形と名前を確かめる(zip・preview は区切り文字の無い名前だけ・数は範囲に収める・題は制御文字を除いて短く)。
    //   名前は一覧にあるものと照らすだけに使い、Dropbox の場所は一覧の値を使う
    public class GroupPack
    {
        public int N;
        public string Zip = "", Title = "";
        public double PreviewStart, Duration;   // 秒(まとめ動画の中でこの本が始まる位置・この本の長さ)。PreviewStart < 0 = 分からない(PC が null を書いた)・Duration 0 = 分からない

        public bool HasStart { get { return PreviewStart >= 0; } }
    }

    public class GroupInfo
    {
        public const int MaxPacks = 100, MaxTitle = 200;
        public const double MaxSeconds = 48 * 3600;
        public string Title = "", Range = "", Preview = "";
        public List<GroupPack> Packs = new List<GroupPack>();   // n の順

        // UTF-8(BOM があれば除く)の中身から。形が違う・壊れている・使える本が 1 つも無いときは null(組を出さない)
        public static GroupInfo Parse(byte[] data, int length)
        {
            if (data == null || length <= 0 || length > data.Length) return null;
            int start = length >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF ? 3 : 0;
            IDictionary<string, object> d;
            try
            {
                d = Json.Parse(new UTF8Encoding(false, true).GetString(data, start, length - start));
            }
            catch (Exception ex)
            {
                if (!(ex is FormatException || ex is ArgumentException || ex is InvalidOperationException || ex is DecoderFallbackException)) throw;
                return null;
            }
            if (Json.Long(d, "v", 0) != 1) return null;
            var g = new GroupInfo { Title = CleanText(Json.Str(d, "title")), Range = CleanText(Json.Str(d, "range")), Preview = PlainName(Json.Str(d, "preview"), OutputFolder.PreviewSuffix) };
            if (g.Range.Length > 20) g.Range = "";
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var p in Json.List(d, "packs"))
            {
                string zip = PlainName(Json.Str(p, "zip"), OutputFolder.PackSuffix);
                if (zip.Length == 0 || !seen.Add(zip)) continue;
                long n = Json.Long(p, "n", 0);
                g.Packs.Add(new GroupPack
                {
                    N = n >= 1 && n <= 1000 ? (int)n : g.Packs.Count + 1,
                    Zip = zip,
                    Title = CleanText(Json.Str(p, "title")),
                    PreviewStart = Seconds(p, "previewStart", -1),
                    Duration = Seconds(p, "duration", 0),
                });
                if (g.Packs.Count >= MaxPacks) break;
            }
            if (g.Packs.Count == 0) return null;
            g.Packs.Sort((a, b) => a.N != b.N ? a.N.CompareTo(b.N) : string.Compare(a.Zip, b.Zip, StringComparison.Ordinal));
            return g;
        }

        // 区切り文字・制御文字の無い、suffix で終わる名前(違えば "")
        static string PlainName(string s, string suffix)
        {
            s = s ?? "";
            if (s.Length <= suffix.Length || s.Length > 255 || !s.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)) return "";
            if (s.IndexOfAny(new[] { '/', '\\', ':' }) >= 0 || s.Any(c => c < 0x20 || c == 0x7F) || s.Trim() != s || s.StartsWith(".")) return "";
            return s;
        }

        static string CleanText(string s)
        {
            var sb = new StringBuilder();
            foreach (char c in s ?? "") if (c >= 0x20 && c != 0x7F && c != (char)0x2028 && c != (char)0x2029) sb.Append(c);
            string t = sb.ToString().Trim();
            return t.Length > MaxTitle ? t.Substring(0, MaxTitle) + "…" : t;
        }

        // 秒(小数あり)。無い・null(PC が長さを測れなかった)・数でない・負・大きすぎる値は unknown
        static double Seconds(IDictionary<string, object> d, string key, double unknown)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v == null) return unknown;
            if (!(v is int || v is long || v is decimal || v is double)) return unknown;
            double x = v is int ? (int)v : v is long ? (long)v : v is decimal ? (double)(decimal)v : (double)v;
            return double.IsNaN(x) || x < 0 || x > MaxSeconds ? unknown : x;
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

        // dir の中の、まだ無い名前(a.zip → a (2).zip …)。同じ名前のファイル・フォルダ・.part の無いもの(受け取った zip にも、展開したフォルダにも使う)
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

    // ---- 手元の記録(%LOCALAPPDATA%\RequestSender\settings.json): 受け取る場所と覚える設定 ----
    public class LocalState
    {
        readonly string dir;

        public LocalState(string dir)
        {
            this.dir = dir;
        }

        string SettingsPath { get { return System.IO.Path.Combine(dir, "settings.json"); } }

        public static string DefaultDownloadDir()
        {
            return System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "切り抜き依頼");
        }

        // settings.json の中身(無い・壊れていれば空)。キー: downloadDir と AppSettings のもの
        public IDictionary<string, object> LoadSettingsDict()
        {
            return Json.ReadFileOrNull(SettingsPath) ?? new Dictionary<string, object>();
        }

        // 読んで・直して・書く(ほかのキーを消さない。保存先と覚える設定が同じファイルにあるため)
        public void UpdateSettings(Action<IDictionary<string, object>> change)
        {
            var d = LoadSettingsDict();
            change(d);
            WriteAtomic(SettingsPath, new JavaScriptSerializer().Serialize(d) + "\r\n");
        }

        public AppSettings LoadSettings()
        {
            return AppSettings.From(LoadSettingsDict());
        }

        public void SaveSettings(AppSettings settings)
        {
            UpdateSettings(settings.Into);
        }

        public string LoadDownloadDir()
        {
            string d = (Json.Str(LoadSettingsDict(), "downloadDir") ?? "").Trim();
            return d.Length > 0 && System.IO.Path.IsPathRooted(d) ? d : DefaultDownloadDir();
        }

        public void SaveDownloadDir(string path)
        {
            UpdateSettings(d => d["downloadDir"] = path);
        }

        // 受け取った zip を保存先に展開するか(settings.json の "extractZip"。無ければ展開する)。画面のスイッチは無い(zip のままにしたい人だけ false を書く)
        public bool LoadExtractZip()
        {
            return Json.Bool(LoadSettingsDict(), "extractZip", true);
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
            foreach (var g in Json.List(Json.ReadFileOrNull(path), "groups"))
                foreach (var m in Json.List(g, "members"))
                {
                    string n = (Json.Str(m, "name") ?? "").Trim();
                    if (n.Length > 0 && !names.Contains(n)) names.Add(n);
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
            if (IsRevokedKey(all)) return "送るための鍵が使えなくなっています(取り消された可能性があります)。送り先の人に新しい config.json をもらってください。";
            if (IsBadAppKey(all)) return "config.json の appKey が正しくありません。送り先の人に伝えてください。";
            if (all.Contains("missing_scope")) return "鍵に書き込みの権限がありません。送り先の人に伝えてください(files.content.write)。";
            if (all.Contains("disallowed_name") || all.Contains("malformed_path")) return "この名前のファイルは送れません。ファイルの名前を変えてから送ってください。";
            if (status == 429 || all.Contains("too_many")) return "Dropbox が混んでいます。少し待ってからもう一度送ってください。";
            if (status >= 500) return "Dropbox の側で問題が起きています(" + status + ")。少し待ってからもう一度送ってください。";
            string s = summary.Length > 0 ? summary : error;
            return "Dropbox からエラーが返りました(" + status + (s.Length > 0 ? ": " + Validation.Shorten(s, 80) : "") + ")";
        }

        // all = 小文字にした返事
        static bool IsRevokedKey(string all)
        {
            return all.Contains("invalid_grant") || all.Contains("invalid_access_token") || all.Contains("expired_access_token");
        }

        static bool IsBadAppKey(string all)
        {
            return all.Contains("invalid_client") || all.Contains("app_key");
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
            if (IsRevokedKey(all)) return "鍵が使えなくなっています(取り消された可能性があります)。送り先の人に新しい config.json をもらってください。";
            if (IsBadAppKey(all)) return "config.json の appKey が正しくありません。送り先の人に伝えてください。";
            if (IsNotFound(status, body)) return "送り先の Dropbox にもうありません。「更新」を押してください。";
            if (status == 429 || all.Contains("too_many")) return "Dropbox が混んでいます。少し待ってからもう一度押してください。";
            if (status >= 500) return "Dropbox の側で問題が起きています(" + status + ")。少し待ってからもう一度押してください。";
            return FromDropbox(status, body);
        }
    }
}
