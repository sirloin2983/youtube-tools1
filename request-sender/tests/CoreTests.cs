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
        Run("JSON: 話す人(speakers)", SpeakersJson);
        Run("JSON: 映像トラックの数(① 全自動のときだけ・1〜5・範囲の外は 1)", VideoTracksJson);
        Run("JSON: 送った時刻は時差つきの ISO 8601", SentAt);
        Run("時刻: 書式・長さの言い方・貼り付けの読み取り(t= / 1:23:45 / 83:45)", TimeTexts);
        Run("時刻の欄: 時 → 分 → 秒 の順に数字で入る・←→・↑↓・BackSpace・Delete", TimeEdits);
        Run("区間: 誤りの文・JSON(③ は書かない)・切り抜く数は区間の数以上", RangeRules);
        Run("JSON: 配信ごとの区間・カット(① だけ)・重み(指定したときだけ)", RequestJson2);
        Run("題名: oEmbed の問い合わせ先と返事の読み取り", OEmbeds);
        Run("設定: 覚える値の読み書き・保存先を消さない・壊れた値は既定", SettingsRoundTrip);
        Run("Dropbox-API-Arg: ASCII 以外と 0x7F を \\uXXXX にする", ApiArgEscape);
        Run("分け方: 150MB 以下は1回・超えたら 8MB ずつ", Chunks);
        Run("config.json: 読める・無い・足りない", ConfigLoad);
        Run("members.json: 名前の一覧・壊れていたら空", MembersLoad);
        Run("エラー: Dropbox の返事を日本語に", Errors);
        Run("どこまで: 3つの値・既定は auto・知らない値は送らない", Flows);
        Run("受け取る: 一覧の返事からパックと失敗の知らせだけ・新しい順", OutputEntries);
        Run("消す: delete_v2 の引数(日本語の path も ASCII)", DeleteArgs);
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
        var u = new SendInput { Items = new List<UrlItem> { new UrlItem { Url = Norm, Top = 11 } } };
        True(Sending.Check(u).Any(x => x.Contains("切り抜く数")), "数の範囲");
        u.Items[0].Top = 10;
        Eq(0, Sending.Check(u).Count, "URL だけで送れる");
        u.Items[0].Ranges.Add(new ClipRange(100, 90));
        True(Sending.Check(u).Any(x => x.Contains("終了が開始より前")), "区間の誤りは送る前に止める");
        u.Items[0].Ranges[0] = new ClipRange(100, 190);
        u.Cut = "bogus";
        True(Sending.Check(u).Any(x => x.Contains("カット")), "知らないカットは送らない");
        u.Cut = Cut.Silence;
        Eq(0, Sending.Check(u).Count, "区間とカットつきで送れる");

        string dir = TempDir();
        try
        {
            string empty = Path.Combine(dir, "empty.mp4");
            File.WriteAllBytes(empty, new byte[0]);
            string good = Path.Combine(dir, "良い動画.mp4");
            File.WriteAllBytes(good, new byte[] { 1, 2, 3 });
            string txt = Path.Combine(dir, "memo.txt");
            File.WriteAllText(txt, "x");
            var v = new SendInput { Videos = new List<string> { empty, good, txt, Path.Combine(dir, "none.mp4") } };
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
        string json = RequestJson.Video(id, new[] { id + "__にぇの叫び.mp4", id + "__b (1).mp4" }, "さくらみこ", "1行目\n\"引用\" \\ タブ\tおわり", Flow.Check, T);
        Eq("{\"v\":1,\"kind\":\"video\",\"id\":\"20261001-120000-abcdef\",\"flow\":\"check\",\"files\":[\"20261001-120000-abcdef__にぇの叫び.mp4\",\"20261001-120000-abcdef__b (1).mp4\"]," +
           "\"streamer\":\"さくらみこ\",\"memo\":\"1行目\\n\\\"引用\\\" \\\\ タブ\\tおわり\",\"sentAt\":\"2026-10-01T12:00:00+09:00\"}", json, "形");
        var d = Json.Parse(json);   // 読み直せる
        Eq("1行目\n\"引用\" \\ タブ\tおわり", Json.Str(d, "memo"), "メモを読み直す");
        Eq("", Json.Str(Json.Parse(RequestJson.Video(id, new string[0], null, null, Flow.Auto, T)), "streamer"), "配信者なしは空");
        string ctrl = RequestJson.Video(id, new string[0], "", "a\u0001b\u2028c", Flow.Manual, T);
        True(ctrl.Contains("a\\u0001b\\u2028c"), "制御文字: " + ctrl);
    }

    static void SpeakersJson()
    {
        string id = "20261001-120000-abcdef";
        string longName = new string('あ', 70);
        var names = new[] { " さくらみこ ", "", "さくらみこ", "ホシマチスイセイ", longName, "4人目" };
        foreach (string json in new[] { RequestJson.Video(id, new[] { "a.mp4" }, "", "", Flow.Auto, T, 3, names), RequestJson.Url(id, new[] { Norm }, 3, "", Flow.Auto, T, 3, names) })
        {
            var sp = Json.Dict(Json.Parse(json), "speakers");
            True(sp != null && Json.Long(sp, "count", -1) == 3, "speakers.count: " + json);
            var list = (System.Collections.IEnumerable)sp["names"];
            var got = list.Cast<object>().Select(o => (string)o).ToList();
            Eq("さくらみこ|ホシマチスイセイ|" + new string('あ', 60), string.Join("|", got), "名前: 空・重複を除く・60 文字・人数まで");
        }
        True(!RequestJson.Video(id, new[] { "a.mp4" }, "", "", Flow.Auto, T).Contains("speakers"), "指定しないときは書かない(動画)");
        True(!RequestJson.Url(id, new[] { Norm }, 3, "", Flow.Auto, T, 0, names).Contains("speakers"), "指定しないときは書かない(URL)");
    }

    static void VideoTracksJson()
    {
        string id = "20261001-120000-abcdef";
        Eq(3L, Json.Long(Json.Parse(RequestJson.Url(id, new[] { Norm }, 3, "", Flow.Auto, T, 0, null, 3)), "videoTracks", -1), "URL・①・3");
        Eq(5L, Json.Long(Json.Parse(RequestJson.Video(id, new[] { "a.mp4" }, "", "", Flow.Auto, T, 0, null, 5)), "videoTracks", -1), "動画・①・5");
        Eq(1L, Json.Long(Json.Parse(RequestJson.Video(id, new[] { "a.mp4" }, "", "", Flow.Auto, T, 0, null, 1)), "videoTracks", -1), "1 も書く");
        True(!RequestJson.Video(id, new[] { "a.mp4" }, "", "", Flow.Check, T, 0, null, 3).Contains("videoTracks"), "② は書かない");
        True(!RequestJson.Url(id, new[] { Norm }, 3, "", Flow.Manual, T, 0, null, 3).Contains("videoTracks"), "③ は書かない");
        Eq(1L, Json.Long(Json.Parse(RequestJson.Url(id, new[] { Norm }, 3, "", Flow.Auto, T, 0, null, 6)), "videoTracks", -1), "範囲の外は 1");
        Eq(1L, Json.Long(Json.Parse(RequestJson.Url(id, new[] { Norm }, 3, "", Flow.Auto, T)), "videoTracks", -1), "前の形の呼び出しは既定の 1");
        Eq("V1〜V3 に同じ動画(重ねて加工する用)、V4(いちばん上)に字幕", VideoTracks.Hint(3), "案内");
        Eq("V1 に動画、V2 に字幕", VideoTracks.Hint(1), "案内(1)");
    }

    static void UrlJson()
    {
        string id = "20261001-120000-000001";
        string json = RequestJson.Url(id, new[] { Norm, "https://www.youtube.com/watch?v=AAAAAAAAAAA" }, 5, "", Flow.Manual, T);
        Eq("{\"v\":1,\"kind\":\"url\",\"id\":\"20261001-120000-000001\",\"flow\":\"manual\",\"items\":[{\"url\":\"https://www.youtube.com/watch?v=dQw4w9WgXcQ\",\"top\":5}," +
           "{\"url\":\"https://www.youtube.com/watch?v=AAAAAAAAAAA\",\"top\":5}],\"memo\":\"\",\"sentAt\":\"2026-10-01T12:00:00+09:00\"}", json, "形");
        Json.Parse(json);
    }

    static void TimeTexts()
    {
        Eq("0:00:00", TimeText.Format(0), "0");
        Eq("1:23:45", TimeText.Format(5025), "時は 0 を付けない");
        Eq("12:03:04", TimeText.Format(12 * 3600 + 184), "10 時間からは2桁");
        Eq("99:59:59", TimeText.Format(int.MaxValue), "上限で止める");
        Eq("45秒", TimeText.Length(45), "秒だけ");
        Eq("1分25秒", TimeText.Length(85), "分と秒");
        Eq("1時間", TimeText.Length(3600), "ちょうど");
        Eq("0秒", TimeText.Length(0), "0");
        var ok = new Dictionary<string, int>
        {
            { "https://youtu.be/dQw4w9WgXcQ?t=5025", 5025 }, { "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5025s", 5025 },
            { "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1h23m45s", 5025 }, { "https://youtu.be/dQw4w9WgXcQ?si=abc&t=90", 90 },
            { "1:23:45", 5025 }, { " 83:45 ", 5025 }, { "1：23：45", 5025 }, { "1h23m45s", 5025 }, { "2m", 120 }, { "t=75", 75 },
        };
        foreach (var kv in ok)
        {
            int sec;
            True(TimeText.TryParse(kv.Key, out sec), "読める: " + kv.Key);
            Eq(kv.Value, sec, kv.Key);
        }
        foreach (string ng in new[] { "", null, "5025", "abc", "https://youtu.be/dQw4w9WgXcQ", "1:2:3:4", "t=abc", "999:00:00", "1.5" })
        {
            int sec;
            True(!TimeText.TryParse(ng, out sec), "読まない: " + ng);
        }
    }

    static void TimeEdits()
    {
        var e = new TimeEdit();
        True(!e.HasValue, "はじめは空");
        Eq("0:00:00", e.Text, "空でも形は出す");
        e.Focus();
        foreach (char c in "12345") e.Digit(c - '0');
        Eq("1:23:45", e.Text, "12345 → 1:23:45(時 1 桁 → 分 2 桁 → 秒 2 桁)");
        True(e.HasValue && e.Segment == TimeEdit.Second, "打ち終えたら秒にいる");
        e.Digit(0); e.Digit(7);
        Eq("1:23:07", e.Text, "秒は続けて打つと打ち直し");

        e = new TimeEdit();
        e.Focus();
        foreach (char c in "02345") e.Digit(c - '0');
        Eq("0:23:45", e.Text, "1時間より前は 0 から");

        e = new TimeEdit();
        e.Focus();
        e.Digit(0); e.Digit(7); e.Digit(8);
        Eq("0:07:08", e.Text, "分・秒で 6〜9 を最初に打ったら1桁で次へ");

        e.Left();
        Eq(TimeEdit.Minute, e.Segment, "← で分へ");
        e.Digit(3); e.Digit(0);
        Eq("0:30:08", e.Text, "選んだ所だけ打ち直す");
        Eq(TimeEdit.Second, e.Segment, "2桁で次へ");
        e.Left(); e.Left(); e.Left();
        Eq(TimeEdit.Hour, e.Segment, "← は時で止まる");
        e.Right(); e.Right(); e.Right();
        Eq(TimeEdit.Second, e.Segment, "→ は秒で止まる");

        e.Set(59);
        e.Select(TimeEdit.Second);
        e.Step(1, false);
        Eq("0:01:00", e.Text, "↑ で繰り上がり");
        e.Step(-1, false);
        Eq("0:00:59", e.Text, "↓ で繰り下がり");
        e.Select(TimeEdit.Minute);
        e.Step(1, true);
        Eq("0:10:59", e.Text, "Shift+↑ は ±10(分を選んでいれば 10 分)");
        e.Step(-1, true); e.Step(-1, true);
        Eq("0:00:00", e.Text, "0 より前には行かない");
        e.Select(TimeEdit.Hour);
        for (int i = 0; i < 11; i++) e.Step(1, false);
        Eq("11:00:00", e.Text, "10 時間より後は 時 を選んで ↑");

        e.Set(5025);
        e.Select(TimeEdit.Second);
        e.Backspace();
        Eq("1:23:00", e.Text, "BackSpace は選んだ所を 0 に");
        e.Backspace();
        Eq(TimeEdit.Minute, e.Segment, "もう 0 なら左へ");
        e.Clear();
        True(!e.HasValue && e.Value == 0 && e.Segment == TimeEdit.Hour, "Delete で空に");

        e.Set(5025);
        int start, len;
        e.Select(TimeEdit.Hour); e.SegmentRange(out start, out len);
        Eq("0+1", start + "+" + len, "時の範囲");
        e.Select(TimeEdit.Minute); e.SegmentRange(out start, out len);
        Eq("2+2", start + "+" + len, "分の範囲");
        e.Select(TimeEdit.Second); e.SegmentRange(out start, out len);
        Eq("5+2", start + "+" + len, "秒の範囲");
        Eq(TimeEdit.Hour, TimeEdit.SegmentAt("1:23:45", 0), "クリック: 時");
        Eq(TimeEdit.Minute, TimeEdit.SegmentAt("1:23:45", 3), "クリック: 分");
        Eq(TimeEdit.Second, TimeEdit.SegmentAt("1:23:45", 7), "クリック: 秒");
    }

    static void RangeRules()
    {
        Eq(null, Ranges.Problem(false, 0, false, 0), "空の行は誤りではない");
        True(Ranges.Problem(true, 10, false, 0).Contains("終了の時刻"), "終了が無い");
        True(Ranges.Problem(false, 0, true, 10).Contains("開始の時刻"), "開始が無い");
        True(Ranges.Problem(true, 10, true, 10).Contains("終了が開始より前"), "同じ時刻");
        True(Ranges.Problem(true, 0, true, 3601).Contains("60 分"), "長すぎる");
        Eq(null, Ranges.Problem(true, 0, true, 3600), "ちょうど 60 分はよい");
        var rs = new List<ClipRange> { new ClipRange(5025, 5110), new ClipRange(60, 90) };
        Eq(",\"ranges\":[{\"start\":5025,\"end\":5110},{\"start\":60,\"end\":90}]", Ranges.JsonPart(Flow.Auto, rs), "①");
        Eq(Ranges.JsonPart(Flow.Auto, rs), Ranges.JsonPart(Flow.Check, rs), "② も同じ");
        Eq("", Ranges.JsonPart(Flow.Manual, rs), "③ は書かない");
        Eq("", Ranges.JsonPart(Flow.Auto, new List<ClipRange>()), "区間なし");
        var it = new UrlItem { Url = Norm, Top = 1, Ranges = rs };
        Eq(2, it.EffectiveTop(Flow.Auto), "切り抜く数は区間の数以上");
        Eq(0, it.AutoCount, "自動 0");
        Eq(1, it.EffectiveTop(Flow.Manual), "③ は区間を数えない");
        it.Top = 5;
        Eq(3, it.AutoCount, "指定 2 + 自動 3");
    }

    static void RequestJson2()
    {
        string id = "20261001-120000-000001";
        var items = new List<UrlItem>
        {
            new UrlItem { Url = Norm, Top = 3, Ranges = new List<ClipRange> { new ClipRange(5025, 5110) } },
            new UrlItem { Url = "https://www.youtube.com/watch?v=AAAAAAAAAAA", Top = 2 },
        };
        var w = new Weights { Enabled = true, Audio = 1.5, Chat = 0.04, Comments = 9 };
        string json = RequestJson.Url(id, items, "メモ", Flow.Auto, T, 0, null, 2, Cut.Silence, w);
        Eq("{\"v\":1,\"kind\":\"url\",\"id\":\"20261001-120000-000001\",\"flow\":\"auto\",\"items\":[" +
           "{\"url\":\"https://www.youtube.com/watch?v=dQw4w9WgXcQ\",\"top\":3,\"ranges\":[{\"start\":5025,\"end\":5110}]}," +
           "{\"url\":\"https://www.youtube.com/watch?v=AAAAAAAAAAA\",\"top\":2}],\"memo\":\"メモ\",\"videoTracks\":2,\"cut\":\"silence\"," +
           "\"weights\":{\"audio\":1.5,\"chat\":0.0,\"comments\":3.0},\"sentAt\":\"2026-10-01T12:00:00+09:00\"}", json, "① の形(順番も)");
        Json.Parse(json);

        string check = RequestJson.Url(id, items, "", Flow.Check, T, 0, null, 2, Cut.Silence, new Weights());
        True(check.Contains("\"ranges\"") && !check.Contains("\"cut\"") && !check.Contains("\"videoTracks\"") && !check.Contains("\"weights\""), "② は区間だけ(カット・トラック・指定しない重みは書かない): " + check);
        string manual = RequestJson.Url(id, items, "", Flow.Manual, T, 0, null, 2, Cut.Silence, w);
        True(!manual.Contains("\"ranges\"") && !manual.Contains("\"cut\"") && manual.Contains("\"weights\""), "③ は区間を書かない・重みは書く(解析に使う): " + manual);
        True(RequestJson.Url(id, items, "", Flow.Auto, T, 0, null, 1, "bogus", null).Contains("\"cut\":\"none\""), "知らないカットは none");

        string video = RequestJson.Video(id, new[] { "a.mp4" }, "", "", Flow.Auto, T, 0, null, 1, Cut.Silence);
        True(video.Contains("\"videoTracks\":1,\"cut\":\"silence\",\"sentAt\""), "動画の依頼にもカット(トラックの後): " + video);
        True(!RequestJson.Video(id, new[] { "a.mp4" }, "", "", Flow.Check, T, 0, null, 1, Cut.Silence).Contains("\"cut\""), "動画の ② はカットを書かない");
        True(!RequestJson.Video(id, new[] { "a.mp4" }, "", "", Flow.Auto, T, 0, null, 1).Contains("\"cut\""), "1.4.0 までの呼び方はそのまま");
    }

    static void OEmbeds()
    {
        Eq("https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DdQw4w9WgXcQ&format=json", OEmbed.Url("dQw4w9WgXcQ"), "問い合わせ先");
        foreach (string ng in new[] { null, "", "short", "dQw4w9WgXcQ&x=1", "../../etc/pw", "dQw4w9WgXc Q" }) Eq(null, OEmbed.Url(ng), "ID の形でなければ問い合わせない: " + ng);
        Eq("【雑談】題名", OEmbed.ParseTitle("{\"title\":\" 【雑談】題名\\n \",\"author_name\":\"x\"}"), "題名(制御文字と前後の空白を除く)");
        Eq(OEmbed.MaxTitle + 1, OEmbed.ParseTitle("{\"title\":\"" + new string('あ', 200) + "\"}").Length, "長い題名は切る");
        foreach (string ng in new[] { null, "", "Not Found", "[]", "{}", "{\"title\":5}", "{\"title\":\"  \"}" }) Eq(null, OEmbed.ParseTitle(ng), "題名なし: " + ng);
    }

    static void SettingsRoundTrip()
    {
        string dir = TempDir();
        try
        {
            var st = new LocalState(dir);
            var s = st.LoadSettings();
            True(s.Cut == Cut.None && s.VideoTracks == 1 && s.Top == 3 && !s.Weights.Enabled && s.Theme == "A" && s.WindowWidth == 0, "無いときは既定");
            st.SaveDownloadDir(@"D:\受け取る");
            s.Cut = Cut.Silence; s.VideoTracks = 4; s.Top = 7; s.Theme = "C"; s.WindowWidth = 1200; s.WindowHeight = 800;
            s.Weights.Enabled = true; s.Weights.Audio = 1.5; s.Weights.Chat = 0.5; s.Weights.Comments = 2.0;
            st.SaveSettings(s);
            Eq(@"D:\受け取る", st.LoadDownloadDir(), "設定を書いても保存先は残る");
            var r = new LocalState(dir).LoadSettings();
            True(r.Cut == Cut.Silence && r.VideoTracks == 4 && r.Top == 7 && r.Theme == "C" && r.WindowWidth == 1200 && r.WindowHeight == 800, "読み直せる");
            True(r.Weights.Enabled && r.Weights.Audio == 1.5 && r.Weights.Chat == 0.5 && r.Weights.Comments == 2.0, "重みも");
            st.SaveDownloadDir(@"E:\x");
            Eq(Cut.Silence, st.LoadSettings().Cut, "保存先を書いても設定は残る");

            File.WriteAllText(Path.Combine(dir, "settings.json"), "{\"cut\":\"x\",\"videoTracks\":9,\"top\":0,\"theme\":\"Z\",\"weights\":{\"audio\":99,\"chat\":\"a\"},\"windowWidth\":5}", new UTF8Encoding(false));
            var b = st.LoadSettings();
            True(b.Cut == Cut.None && b.VideoTracks == 1 && b.Top == 3 && b.Theme == "A" && b.WindowWidth == 0, "形が違う値は既定");
            True(b.Weights.Audio == 3.0 && b.Weights.Chat == 1.0 && !b.Weights.Enabled, "重みは範囲に収める");
            File.WriteAllText(Path.Combine(dir, "settings.json"), "こわれた", new UTF8Encoding(false));
            Eq(Cut.None, st.LoadSettings().Cut, "壊れていても動く");
        }
        finally { Directory.Delete(dir, true); }
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
                var list = FindAll(f).OfType<FileList>().Single();
                Eq(1, list.Items.Count, "入った動画");
                True(FindAll(f).OfType<System.Windows.Forms.Label>().Any(l => l.Text.Contains("動画ではない")), "入れなかった理由が出る");
            }
        }
        finally { Directory.Delete(dir, true); }
    }

    static void DeleteArgs()
    {
        string a = DropboxArgs.Delete("/出力/x\"y.zip");
        Eq("{\"path\":\"/\\u51fa\\u529b/x\\\"y.zip\"}", a, "delete_v2");
        Eq("/出力/x\"y.zip", Json.Str(Json.Parse(a), "path"), "戻せる");
    }

    static void Flows()
    {
        Eq(3, Flow.All.Length, "3つ");
        True(Flow.IsValid("auto") && Flow.IsValid("check") && Flow.IsValid("manual"), "3つとも通る");
        True(!Flow.IsValid("Auto") && !Flow.IsValid("") && !Flow.IsValid(null) && !Flow.IsValid("pack"), "他は通らない");
        Eq(Flow.Auto, new SendInput().Flow, "SendInput の既定");
        True(Flow.Label(Flow.Auto).StartsWith("①") && Flow.Label(Flow.Check).StartsWith("②") && Flow.Label(Flow.Manual).StartsWith("③"), "表示の名前");
        True(Flow.Explain(Flow.Auto).Contains("受け取る") && Flow.Explain(Flow.Check).Contains("字幕を直して") && Flow.Explain(Flow.Manual).Contains("切り抜く所から"), "説明");
        var u = new SendInput { Items = new List<UrlItem> { new UrlItem { Url = Norm } }, Flow = "bogus" };
        True(Sending.Check(u).Any(x => x.Contains("どこまで")), "知らない値は送る前に止める");
        string id = "20261001-120000-abcdef";
        Eq("auto", Json.Str(Json.Parse(RequestJson.Url(id, new[] { Norm }, 3, "", "bogus", T)), "flow"), "JSON には知らない値を書かない");
        foreach (string f in Flow.All)
        {
            Eq(f, Json.Str(Json.Parse(RequestJson.Url(id, new[] { Norm }, 3, "", f, T)), "flow"), "URL の依頼: " + f);
            Eq(f, Json.Str(Json.Parse(RequestJson.Video(id, new[] { "a.mp4" }, "", "", f, T)), "flow"), "動画の依頼: " + f);
        }
        // 前からのキーはそのまま
        var d = Json.Parse(RequestJson.Video(id, new[] { "a.mp4" }, "さくらみこ", "m", Flow.Check, T));
        foreach (string k in new[] { "v", "kind", "id", "files", "streamer", "memo", "sentAt", "flow" }) True(d.ContainsKey(k), "動画の依頼のキー: " + k);
        d = Json.Parse(RequestJson.Url(id, new[] { Norm }, 3, "m", Flow.Check, T));
        foreach (string k in new[] { "v", "kind", "id", "items", "memo", "sentAt", "flow" }) True(d.ContainsKey(k), "URL の依頼のキー: " + k);
    }

    static void OutputEntries()
    {
        string body = "{\"entries\":[" +
            "{\".tag\":\"file\",\"name\":\"20261001-120000-abcdef__みこの配信.zip\",\"path_lower\":\"/出力/20261001-120000-abcdef__みこの配信.zip\",\"path_display\":\"/出力/20261001-120000-abcdef__みこの配信.zip\",\"rev\":\"015f\",\"size\":5368709120,\"server_modified\":\"2026-10-01T03:00:00Z\",\"content_hash\":\"ab\"}," +
            "{\".tag\":\"file\",\"name\":\"20261002-080000-000001__ぺこら.失敗.txt\",\"path_lower\":\"/出力/20261002-080000-000001__ぺこら.失敗.txt\",\"rev\":\"0160\",\"size\":120,\"server_modified\":\"2026-10-02T00:00:00Z\"}," +
            "{\".tag\":\"folder\",\"name\":\"sub\",\"path_lower\":\"/出力/sub\"}," +
            "{\".tag\":\"file\",\"name\":\"memo.txt\",\"size\":1,\"server_modified\":\"2026-10-03T00:00:00Z\"}," +
            "{\".tag\":\"file\",\"name\":\"x.zip.part\",\"size\":1,\"server_modified\":\"2026-10-03T00:00:00Z\"}," +
            "{\".tag\":\"file\",\"name\":\"手で置いた.ZIP\",\"size\":10,\"server_modified\":\"2026-09-30T00:00:00Z\"}" +
            "],\"cursor\":\"c\",\"has_more\":false}";
        var d = Json.Parse(body);
        var list = OutputFolder.ParseEntries(d);
        Eq(3, list.Count, "パック2つと失敗1つ(フォルダ・他のファイル・.part は出さない)");
        OutputFolder.SortNewestFirst(list);
        Eq(OutputKind.Failure, list[0].Kind, "新しい順: 失敗が先");
        Eq("ぺこら", list[0].Title, "失敗の題");
        Eq("20261002-080000-000001", list[0].RequestId, "失敗の依頼の id");
        var pack = list[1];
        Eq(OutputKind.Pack, pack.Kind, "パック");
        Eq("みこの配信", pack.Title, "題");
        Eq("20261001-120000-abcdef", pack.RequestId, "依頼の id");
        Eq(5368709120L, pack.Size, "5GB でも long");
        Eq("015f", pack.Rev, "rev");
        Eq("ab", pack.ContentHash, "content_hash");
        Eq(new DateTime(2026, 10, 1, 3, 0, 0, DateTimeKind.Utc).ToLocalTime(), pack.Modified, "時刻は地方時");
        Eq("/出力/20261001-120000-abcdef__みこの配信.zip", pack.ApiPath, "API に渡す場所");
        Eq("手で置いた", list[2].Title, "id の無い名前は名前がそのまま題");
        Eq("", list[2].RequestId, "id なし");
        Eq("/出力/手で置いた.ZIP", list[2].ApiPath, "path_lower が無いときの場所");
        True(Json.Bool(Json.Parse("{\"has_more\":true}"), "has_more") && !Json.Bool(d, "has_more") && !Json.Bool(d, "none"), "has_more");
        Eq(null, OutputFolder.FromName(".zip"), "名前が空");
        Eq(null, OutputFolder.FromName("a.失敗.txt.bak"), "違う拡張子");
        True(pack.Key != list[0].Key, "記録の鍵は別々");
        var again = OutputFolder.ParseEntries(d).First(x => x.Kind == OutputKind.Pack && x.RequestId.Length > 0);
        Eq(pack.Key, again.Key, "同じものは同じ鍵");
        again.Rev = "0999";
        True(pack.Key != again.Key, "置き直されたら(rev が変わったら)別のもの");
        Eq(DateTime.MinValue, OutputFolder.ParseTime("x"), "読めない時刻");
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
