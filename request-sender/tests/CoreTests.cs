// 切り抜き依頼のテスト(build.bat が RequestSender.exe を参照して作り、流す)。通信はしない。失敗が1つでもあれば終了コード 1。
//   build\RequestSenderTests.exe
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using RequestSender;

static class CoreTests
{
    static int failures, passed;

    [STAThread]
    static int Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        Run("URL: watch?v= / youtu.be / live / shorts から id を取り出して正規化する", UrlForms);
        Run("URL: YouTube ではない・形が違うものは断る", UrlRejects);
        Run("URL: 複数行・空の行・重なり・おかしな行の行番号", UrlLines);
        Run("検査: 拡張子・切り抜く数の範囲・空の依頼・空のファイル", Checks);
        Run("id: 形(yyyyMMdd-HHmmss-6 桁の16進)と置き場所", Ids);
        Run("JSON: 動画の依頼(エスケープ・実際の名前・日本語はそのまま)", VideoJson);
        Run("JSON: URL の依頼", UrlJson);
        Run("JSON: 送った時刻は時差つきの ISO 8601", SentAt);
        Run("Dropbox-API-Arg: ASCII 以外と 0x7F を \\uXXXX にする", ApiArgEscape);
        Run("分け方: 150MB 以下は1回・超えたら 8MB ずつ", Chunks);
        Run("config.json: 読める・無い・足りない", ConfigLoad);
        Run("members.json: 名前の一覧・壊れていたら空", MembersLoad);
        Run("エラー: Dropbox の返事を日本語に", Errors);
        Run("画面: 作れる(開かない)・引数の動画だけ入る", FormBuilds);
        Console.WriteLine();
        Console.WriteLine(failures == 0 ? "OK: " + passed + " 件" : "失敗: " + failures + " 件(成功 " + passed + " 件)");
        return failures == 0 ? 0 : 1;
    }

    static void Run(string name, Action test)
    {
        try
        {
            test();
            passed++;
            Console.WriteLine("ok    " + name);
        }
        catch (Exception ex)
        {
            failures++;
            Console.WriteLine("FAIL  " + name + "\n      " + ex.GetType().Name + ": " + ex.Message);
        }
    }

    static void Eq<T>(T expected, T actual, string what)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
            throw new Exception(what + ": 期待 <" + expected + "> 実際 <" + actual + ">");
    }

    static void True(bool cond, string what)
    {
        if (!cond) throw new Exception(what);
    }

    static string TempDir()
    {
        string d = Path.Combine(Path.GetTempPath(), "request-sender-test-" + Guid.NewGuid().ToString("N").Substring(0, 8));
        Directory.CreateDirectory(d);
        return d;
    }

    const string Id = "dQw4w9WgXcQ";
    const string Norm = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";

    static void UrlForms()
    {
        foreach (string u in new[] {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=dQw4w9WgXcQ&t=120s",
            "https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
            "http://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?si=abcdef&t=10",
            "youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/live/dQw4w9WgXcQ",
            "https://www.youtube.com/live/dQw4w9WgXcQ?si=xyz",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "  https://WWW.YouTube.com/watch?v=dQw4w9WgXcQ  ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ#t=5",
        })
            Eq(Id, YouTubeUrl.ExtractId(u), u);
        Eq(Norm, YouTubeUrl.Normalize(Id), "正規化");
        Eq("a-_B0c1D2e3", YouTubeUrl.ExtractId("https://youtu.be/a-_B0c1D2e3"), "- と _ を含む id");
    }

    static void UrlRejects()
    {
        foreach (string u in new[] {
            "", "   ", "dQw4w9WgXcQ", "https://example.com/watch?v=dQw4w9WgXcQ", "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
            "https://evil.example/?u=https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=short",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQX", "https://www.youtube.com/channel/UCabcdefghijk",
            "https://www.youtube.com/@name", "https://www.youtube.com/playlist?list=PL123", "ftp://youtu.be/dQw4w9WgXcQ",
            "javascript:alert(1)", "file:///C:/x.mp4", "https://user@youtu.be/dQw4w9WgXcQ", "https://youtu.be:8080/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgX%22Q", "https://www.youtube.com/embed/dQw4w9WgXcQ",
        })
            Eq(null, YouTubeUrl.ExtractId(u), "断る: " + u);
        Eq(null, YouTubeUrl.ExtractId(null), "null");
    }

    static void UrlLines()
    {
        var r = Validation.ParseUrlLines("https://youtu.be/dQw4w9WgXcQ\r\n\r\n  \nhttps://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://example.com/x\nhttps://www.youtube.com/live/AAAAAAAAAAA\r\n");
        Eq(2, r.Urls.Count, "URL の数(重なりは1つ)");
        Eq(Norm, r.Urls[0], "1本目");
        Eq("https://www.youtube.com/watch?v=AAAAAAAAAAA", r.Urls[1], "2本目");
        Eq(1, r.Errors.Count, "おかしな行");
        True(r.Errors[0].StartsWith("5 行目"), "行番号: " + r.Errors[0]);
        Eq(0, Validation.ParseUrlLines("").Urls.Count, "空");
        Eq(0, Validation.ParseUrlLines(null).Errors.Count, "null");
    }

    static void Checks()
    {
        foreach (string ok in new[] { "a.mp4", "B.MOV", "c.mkv", "d.webm", "e.M4V", @"C:\動画\にぇ.mp4" }) True(Validation.IsVideoFile(ok), "動画: " + ok);
        foreach (string ng in new[] { "a.txt", "a.mp4.exe", "a", "a.avi", "", null }) True(!Validation.IsVideoFile(ng), "動画ではない: " + ng);
        True(Validation.TopInRange(1) && Validation.TopInRange(10) && Validation.TopInRange(3), "範囲の中");
        True(!Validation.TopInRange(0) && !Validation.TopInRange(11) && !Validation.TopInRange(-1), "範囲の外");

        True(Sending.Check(new SendInput()).Count == 1, "何も入っていない");
        var u = new SendInput { Urls = new List<string> { Norm }, Top = 11 };
        True(Sending.Check(u).Any(x => x.Contains("切り抜く数")), "数の範囲");
        u.Top = 10;
        Eq(0, Sending.Check(u).Count, "URL だけで送れる");

        string dir = TempDir();
        try
        {
            string empty = Path.Combine(dir, "empty.mp4");
            File.WriteAllBytes(empty, new byte[0]);
            string good = Path.Combine(dir, "良い動画.mp4");
            File.WriteAllBytes(good, new byte[] { 1, 2, 3 });
            string txt = Path.Combine(dir, "memo.txt");
            File.WriteAllText(txt, "x");
            var v = new SendInput { Videos = new List<string> { empty, good, txt, Path.Combine(dir, "none.mp4") }, Top = 99 };
            var errs = Sending.Check(v);
            Eq(3, errs.Count, "空・動画でない・無い(URL が無いときは数を見ない): " + string.Join(" / ", errs));
            v.Videos = new List<string> { good };
            Eq(0, Sending.Check(v).Count, "動画だけで送れる");
            v.Memo = new string('あ', 2001);
            Eq(1, Sending.Check(v).Count, "メモが長すぎる");
        }
        finally { Directory.Delete(dir, true); }
    }

    static void Ids()
    {
        string id = RequestId.Make(new DateTime(2026, 10, 1, 9, 5, 7), new byte[] { 0x0a, 0xff, 0x3c });
        Eq("20261001-090507-0aff3c", id, "形");
        True(RequestId.IsValid(id), "検査が通る");
        for (int i = 0; i < 50; i++)
        {
            string n = RequestId.New(DateTime.Now);
            True(Regex.IsMatch(n, "^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$"), "乱数の id: " + n);
        }
        True(!RequestId.IsValid("20261001-090507-0AFF3C") && !RequestId.IsValid("x"), "大文字・違う形は通らない");
        Eq("/" + id + "__にぇの叫び.mp4", RequestId.VideoPath(id, "にぇの叫び.mp4"), "動画の置き場所");
        Eq("/" + id + ".request.json", RequestId.RequestPath(id), "依頼の置き場所");
    }

    static readonly DateTimeOffset T = new DateTimeOffset(2026, 10, 1, 12, 0, 0, TimeSpan.FromHours(9));

    static void VideoJson()
    {
        string id = "20261001-120000-abcdef";
        string json = RequestJson.Video(id, new[] { id + "__にぇの叫び.mp4", id + "__b (1).mp4" }, "さくらみこ", "1行目\n\"引用\" \\ タブ\tおわり", T);
        Eq("{\"v\":1,\"kind\":\"video\",\"id\":\"20261001-120000-abcdef\",\"files\":[\"20261001-120000-abcdef__にぇの叫び.mp4\",\"20261001-120000-abcdef__b (1).mp4\"]," +
           "\"streamer\":\"さくらみこ\",\"memo\":\"1行目\\n\\\"引用\\\" \\\\ タブ\\tおわり\",\"sentAt\":\"2026-10-01T12:00:00+09:00\"}", json, "形");
        var d = Json.Parse(json);   // 読み直せる
        Eq("1行目\n\"引用\" \\ タブ\tおわり", Json.Str(d, "memo"), "メモを読み直す");
        Eq("", Json.Str(Json.Parse(RequestJson.Video(id, new string[0], null, null, T)), "streamer"), "配信者なしは空");
        string ctrl = RequestJson.Video(id, new string[0], "", "a\u0001b\u2028c", T);
        True(ctrl.Contains("a\\u0001b\\u2028c"), "制御文字: " + ctrl);
    }

    static void UrlJson()
    {
        string id = "20261001-120000-000001";
        string json = RequestJson.Url(id, new[] { Norm, "https://www.youtube.com/watch?v=AAAAAAAAAAA" }, 5, "", T);
        Eq("{\"v\":1,\"kind\":\"url\",\"id\":\"20261001-120000-000001\",\"items\":[{\"url\":\"https://www.youtube.com/watch?v=dQw4w9WgXcQ\",\"top\":5}," +
           "{\"url\":\"https://www.youtube.com/watch?v=AAAAAAAAAAA\",\"top\":5}],\"memo\":\"\",\"sentAt\":\"2026-10-01T12:00:00+09:00\"}", json, "形");
        Json.Parse(json);
    }

    static void SentAt()
    {
        Eq("2026-10-01T12:00:00+09:00", JsonText.IsoNow(T), "+09:00");
        Eq("2026-10-01T03:00:00+00:00", JsonText.IsoNow(T.ToUniversalTime()), "UTC");
        Eq("2026-10-01T12:00:00-05:30", JsonText.IsoNow(new DateTimeOffset(2026, 10, 1, 12, 0, 0, TimeSpan.FromMinutes(-330))), "負の時差");
    }

    static void ApiArgEscape()
    {
        string arg = DropboxArgs.Commit("/20261001-120000-abcdef__にぇの叫び \"x\".mp4");
        Eq("{\"path\":\"/20261001-120000-abcdef__\\u306b\\u3047\\u306e\\u53eb\\u3073 \\\"x\\\".mp4\",\"mode\":\"add\",\"autorename\":true,\"mute\":false}", arg, "commit");
        True(arg.All(c => c >= 0x20 && c < 0x7F), "ヘッダーは ASCII だけ");
        Eq("\"a\\u007fb\\u00e9\"", JsonText.Quote("a\u007fb\u00e9", true), "0x7F とラテン文字");
        Eq("\"\\ud83d\\ude00\"", JsonText.Quote("\U0001F600", true), "絵文字はサロゲートの組");
        var d = Json.Parse(arg);
        Eq("/20261001-120000-abcdef__にぇの叫び \"x\".mp4", Json.Str(d, "path"), "読み直せる");
        Eq("{\"cursor\":{\"session_id\":\"S1\",\"offset\":8388608},\"close\":false}", DropboxArgs.Append("S1", 8388608), "append_v2");
        Eq("{\"cursor\":{\"session_id\":\"S1\",\"offset\":200000000},\"commit\":{\"path\":\"/a.mp4\",\"mode\":\"add\",\"autorename\":true,\"mute\":false}}",
           DropboxArgs.Finish("S1", 200000000, "/a.mp4"), "finish");
        Eq("{\"close\":false}", DropboxArgs.SessionStart(), "start");
    }

    static void Chunks()
    {
        const long MB = 1024 * 1024;
        True(!ChunkPlan.UseSession(0) && !ChunkPlan.UseSession(150 * MB), "150MB ちょうどまでは1回");
        True(ChunkPlan.UseSession(150 * MB + 1), "150MB を超えたら分ける");
        Eq(8 * (int)MB, ChunkPlan.ChunkSize, "8MB");

        long size = 150 * MB + 1;
        var plan = ChunkPlan.Plan(size, ChunkPlan.ChunkSize);
        Eq(19, plan.Count, "塊の数(18 × 8MB + 6MB + 1)");
        Eq(0L, plan[0].Offset, "最初");
        Eq((int)(6 * MB + 1), plan[18].Length, "最後の塊");
        long sum = 0;
        for (int i = 0; i < plan.Count; i++)
        {
            Eq(sum, plan[i].Offset, "つながっている " + i);
            sum += plan[i].Length;
        }
        Eq(size, sum, "合計");

        long big = 20L * 1024 * MB;   // 20GB でも int を超えない
        var bp = ChunkPlan.Plan(big, ChunkPlan.ChunkSize);
        Eq(2560, bp.Count, "20GB");
        Eq(big - 8 * MB, bp[bp.Count - 1].Offset, "20GB の最後の位置");
        Eq(1, ChunkPlan.Plan(3, 8).Count, "小さい");
        Eq(2, ChunkPlan.Plan(16, 8).Count, "ちょうど割り切れる");
        Eq(0, ChunkPlan.Plan(0, 8).Count, "0 バイト");
    }

    static void ConfigLoad()
    {
        string dir = TempDir();
        try
        {
            string p = Path.Combine(dir, "config.json");
            try { Config.Load(p); throw new Exception("無いのに読めた"); }
            catch (FileNotFoundException) { }
            File.WriteAllText(p, "{\"appKey\": \" key1 \", \"refreshToken\": \"tok\"}", new UTF8Encoding(true));
            var c = Config.Load(p);
            Eq("key1", c.AppKey, "appKey(前後の空白は取る・BOM つきでも読む)");
            Eq("tok", c.RefreshToken, "refreshToken");
            File.WriteAllText(p, "{\"appKey\": \"key1\"}");
            try { Config.Load(p); throw new Exception("足りないのに読めた"); }
            catch (FormatException) { }
            File.WriteAllText(p, "[1,2]");
            try { Config.Load(p); throw new Exception("形が違うのに読めた"); }
            catch (FormatException) { }
        }
        finally { Directory.Delete(dir, true); }
    }

    static void MembersLoad()
    {
        string dir = TempDir();
        try
        {
            string p = Path.Combine(dir, "members.json");
            Eq(0, Members.LoadNames(p).Count, "無い");
            File.WriteAllText(p, "{\"groups\":[{\"members\":[{\"name\":\"さくらみこ\"},{\"name\":\" \"},{\"name\":\"兎田ぺこら\"}]},{\"members\":[{\"name\":\"さくらみこ\"}]}]}", Encoding.UTF8);
            var names = Members.LoadNames(p);
            Eq(2, names.Count, "重ねない・空の名前は飛ばす");
            Eq("さくらみこ", names[0], "並びはそのまま");
            File.WriteAllText(p, "{壊れた");
            Eq(0, Members.LoadNames(p).Count, "壊れている");
            string bundled = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "members.json");
            if (File.Exists(bundled)) True(Members.LoadNames(bundled).Count > 50, "同梱の members.json が読める");
        }
        finally { Directory.Delete(dir, true); }
    }

    static void FormBuilds()
    {
        string dir = TempDir();
        try
        {
            string v = Path.Combine(dir, "a.mp4");
            File.WriteAllBytes(v, new byte[] { 1 });
            using (var f = new MainForm(dir, new[] { v, Path.Combine(dir, "x.txt"), dir }))
            {
                var list = FindAll(f).OfType<System.Windows.Forms.ListBox>().Single();
                Eq(1, list.Items.Count, "入った動画");
                True(FindAll(f).OfType<System.Windows.Forms.Label>().Any(l => l.Text.Contains("動画ではない")), "入れなかった理由が出る");
            }
        }
        finally { Directory.Delete(dir, true); }
    }

    static IEnumerable<System.Windows.Forms.Control> FindAll(System.Windows.Forms.Control c)
    {
        foreach (System.Windows.Forms.Control x in c.Controls)
        {
            yield return x;
            foreach (var y in FindAll(x)) yield return y;
        }
    }

    static void Errors()
    {
        True(ErrorText.FromDropbox(409, "{\"error_summary\": \"path/insufficient_space/..\", \"error\": {\".tag\": \"path\"}}").Contains("空き"), "空きが無い");
        True(ErrorText.FromDropbox(400, "{\"error\": \"invalid_grant\", \"error_description\": \"refresh token is invalid or revoked\"}").Contains("鍵"), "鍵が取り消された");
        True(ErrorText.FromDropbox(401, "{\"error_summary\": \"expired_access_token/\"}").Contains("鍵"), "期限切れ");
        True(ErrorText.FromDropbox(429, "").Contains("混んで"), "429");
        True(ErrorText.FromDropbox(503, "<html>").Contains("503"), "5xx");
        True(ErrorText.FromDropbox(409, "{\"error_summary\": \"path/disallowed_name/\"}").Contains("名前"), "名前");
        True(ErrorText.FromDropbox(418, "{\"error_summary\": \"something/else/\"}").Contains("something/else"), "その他は要約を出す");
    }
}
