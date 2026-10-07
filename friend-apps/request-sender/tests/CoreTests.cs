// 切り抜き依頼のテスト(build.bat が RequestSender.exe を参照して作り、流す)。通信はしない。失敗が1つでもあれば終了コード 1。
//   build\RequestSenderTests.exe
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using RequestSender;
using FriendApps;

static class CoreTests
{
    static int failures, passed;

    [STAThread]
    static int Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        MainForm.Offline = true;   // テストは通信しない(配信の題名の問い合わせ・届いたものの確認)・設定を書かない
        Run("URL: watch?v= / youtu.be / live / shorts から id を取り出して正規化する", UrlForms);
        Run("URL: YouTube ではない・形が違うものは断る", UrlRejects);
        Run("検査: 拡張子・切り抜く数の範囲・空の依頼・空のファイル", Checks);
        Run("id: 形(yyyyMMdd-HHmmss-6 桁の16進)と置き場所", Ids);
        Run("JSON: 動画の依頼(エスケープ・実際の名前・日本語はそのまま)", VideoJson);
        Run("JSON: URL の依頼", UrlJson);
        Run("JSON: 話す人(speakers)", SpeakersJson);
        Run("配信者の色: 打った・貼ったものを 6 桁の大文字に整える・誤りの検査", SpeakerColorRules);
        Run("JSON: 配信者(speakers.people の name と style.color・streamer は 1 人目・URL にも)", SpeakerPeopleJson);
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
        Run("受け取る: すべて受け取る(パックだけを古い順・合計・同じ依頼の数・まとめの文)", ReceiveAll);
        Run("受け取る: zip の展開(パックのフォルダを保存先の直下に・同じ名前は (2)・zip は消す・外へ出る名前は断る)", ExtractZips);
        Run("消す: delete_v2 の引数(日本語の path も ASCII)", DeleteArgs);
        Run("画面: 作れる(開かない)・引数の動画だけ入る", FormBuilds);
        Run("画面: 時刻の欄にキーを送る(数字・← →・↑ ↓・BackSpace・Delete。「:」は入らない)", TimeBoxKeys);
        Run("画面: 配信のカード(t= つきの URL・+1分・③ では区間を送らない・誤りの欄・何行も貼る)", StreamCards);
        Run("画面: 見本を入れると、下の帯の要約に 指定 + 自動 が出る", FormSummary);
        Run("画面: 配信者の行(色の整え方・見本と注・色だけで名前が空は送る前に止める)", FormSpeakers);
        Run("画面: − / + は押しっぱなしで続けて動く(押したときに 1 回・キーは 1 回ずつ・端で止まる)", RepeatButtons);
        Run("画面: 確かめた題名の ✓ だけアクセントの色(残りの文字は同じ描き方)", TitleMark);
        Run("画面: Ctrl+Enter で送る(送るの画面だけ)", CtrlEnter);
        Run("画面: 配信者が多いときは行の欄の中でスクロールして、メモを下に隠さない", ManySpeakers);
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

    // 配信者 1 人(名前だけ)
    static SpeakerSet One(string name)
    {
        return new SpeakerSet { Count = 1, Rows = new List<SpeakerRow> { new SpeakerRow(name, "") } };
    }

    // 切り抜く数だけを指定した配信(区間なし)
    static List<UrlItem> Items(int top, params string[] urls)
    {
        return urls.Select(u => new UrlItem { Url = u, Top = top }).ToList();
    }

    static void VideoJson()
    {
        string id = "20261001-120000-abcdef";
        string json = RequestJson.Video(id, new[] { id + "__にぇの叫び.mp4", id + "__b (1).mp4" }, "1行目\n\"引用\" \\ タブ\tおわり", Flow.Check, T, One("さくらみこ"), 1, Cut.None);
        Eq("{\"v\":1,\"kind\":\"video\",\"id\":\"20261001-120000-abcdef\",\"flow\":\"check\",\"files\":[\"20261001-120000-abcdef__にぇの叫び.mp4\",\"20261001-120000-abcdef__b (1).mp4\"]," +
           "\"streamer\":\"さくらみこ\",\"memo\":\"1行目\\n\\\"引用\\\" \\\\ タブ\\tおわり\"," +
           "\"speakers\":{\"count\":1,\"names\":[\"さくらみこ\"],\"people\":[{\"name\":\"さくらみこ\"}]},\"sentAt\":\"2026-10-01T12:00:00+09:00\"}", json, "形");
        var d = Json.Parse(json);   // 読み直せる
        Eq("1行目\n\"引用\" \\ タブ\tおわり", Json.Str(d, "memo"), "メモを読み直す");
        Eq("", Json.Str(Json.Parse(RequestJson.Video(id, new string[0], null, Flow.Auto, T, null, 1, Cut.None)), "streamer"), "配信者なしは空");
        string ctrl = RequestJson.Video(id, new string[0], "a\u0001b\u2028c", Flow.Manual, T, null, 1, Cut.None);
        True(ctrl.Contains("a\\u0001b\\u2028c"), "制御文字: " + ctrl);
    }

    static void SpeakersJson()
    {
        string id = "20261001-120000-abcdef";
        string longName = new string('あ', 70);
        var rows = new[] { " さくらみこ ", "", "さくらみこ", "ホシマチスイセイ", longName, "4人目" }.Select(n => new SpeakerRow(n, "")).ToList();
        var five = new SpeakerSet { Count = 5, Rows = rows };   // 人数 5 = 先頭の 5 行まで(6 行目は捨てる)
        foreach (string json in new[] { RequestJson.Video(id, new[] { "a.mp4" }, "", Flow.Auto, T, five, 1, Cut.None), RequestJson.Url(id, Items(3, Norm), "", Flow.Auto, T, five, 1, Cut.None, null) })
        {
            var sp = Json.Dict(Json.Parse(json), "speakers");
            True(sp != null && Json.Long(sp, "count", -1) == 5, "speakers.count: " + json);
            var list = (System.Collections.IEnumerable)sp["names"];
            var got = list.Cast<object>().Select(o => (string)o).ToList();
            Eq("さくらみこ|ホシマチスイセイ|" + new string('あ', 60), string.Join("|", got), "名前: 空・重複を除く・60 文字・人数まで");
        }
        True(!RequestJson.Video(id, new[] { "a.mp4" }, "", Flow.Auto, T, null, 1, Cut.None).Contains("speakers"), "指定しないときは書かない(動画)");
        True(!RequestJson.Url(id, Items(3, Norm), "", Flow.Auto, T, new SpeakerSet { Count = 0, Rows = rows }, 1, Cut.None, null).Contains("speakers"), "指定しないときは書かない(URL)");
    }

    static void SpeakerColorRules()
    {
        Eq("FF00AA", Speakers.CleanColor("ff00aa"), "小文字は大文字に");
        Eq("FF00AA", Speakers.CleanColor("#ff00aa"), "貼り付けた # は外す");
        Eq("FF00AA", Speakers.CleanColor("  #Ff00aA \r\n"), "前後の空白も外す");
        Eq("FF00AA", Speakers.CleanColor("ff00aa12"), "6 文字まで");
        Eq("12AB", Speakers.CleanColor("12xyAB"), "16 進でない文字は捨てる(途中の長さのまま返す)");
        Eq("", Speakers.CleanColor(null), "null");
        Eq("", Speakers.CleanColor("#"), "# だけ");
        Eq("0A0E14", Speakers.ParseColor("0a0e14"), "6 桁なら大文字で返す");
        Eq("FF00AA", Speakers.ParseColor(" #FF00AA "), "# と空白は許す");
        foreach (string ng in new[] { null, "", "FF00A", "FF00AAB", "GG00AA", "FF 00AA", "##FF00AA", "#FF00A" }) Eq(null, Speakers.ParseColor(ng), "色ではない: " + ng);
        True(!Speakers.HasColorText("") && !Speakers.HasColorText("  ") && !Speakers.HasColorText("#") && Speakers.HasColorText("1") && Speakers.HasColorText("#x"), "色の欄に入っているか");

        Func<int, SpeakerRow[], SpeakerSet> set = (n, rows) => new SpeakerSet { Count = n, Rows = rows.ToList() };
        Eq(0, Speakers.Problems(set(3, new[] { new SpeakerRow("A", ""), new SpeakerRow("B", "FF00AA"), new SpeakerRow("", "") })).Count, "色なし・6 桁・名前も色も空は誤りではない");
        var p = Speakers.Problems(set(3, new[] { new SpeakerRow("A", "FF00AA"), new SpeakerRow("", "FF00AA"), new SpeakerRow("  ", "#") }));
        Eq(1, p.Count, "色だけで名前が空は誤り(# だけは色が空)");
        True(p[0].Index == 1 && !p[0].OnColor && p[0].Message.Contains("名前"), "名前の欄へ・理由: " + p[0].Message);
        p = Speakers.Problems(set(3, new[] { new SpeakerRow("A", "FF00A"), new SpeakerRow("B", "GG00AA"), new SpeakerRow("C", "ff00aa") }));
        Eq(2, p.Count, "6 桁でない・16 進でないは誤り(小文字の 6 桁は直せるので誤りではない)");
        True(p[0].Index == 0 && p[0].OnColor && p[0].Message.Contains("6 桁") && p[1].Index == 1 && p[1].OnColor, "色の欄へ");
        Eq(0, Speakers.Problems(set(1, new[] { new SpeakerRow("A", ""), new SpeakerRow("", "zz") })).Count, "人数の外の行は見ない");
        Eq(0, Speakers.Problems(set(0, new[] { new SpeakerRow("", "zz") })).Count, "人数 0 は何も見ない");
        Eq(0, Speakers.Problems(null).Count, "null");

        // 送る前の検査(Sending.Check)にも入る
        var input = new SendInput { Items = new List<UrlItem> { new UrlItem { Url = Norm } }, People = set(2, new[] { new SpeakerRow("A", ""), new SpeakerRow("", "FF00AA") }) };
        True(Sending.Check(input).Any(x => x.StartsWith("配信者 2:") && x.Contains("名前")), "色だけで名前が空は送らない");
        input.People.Rows[1].Name = "B";
        Eq(0, Sending.Check(input).Count, "名前を入れれば送れる");
    }

    static void SpeakerPeopleJson()
    {
        string id = "20261001-120000-abcdef";
        Func<int, SpeakerRow[], SpeakerSet> set = (n, rows) => new SpeakerSet { Count = n, Rows = rows.ToList() };
        var three = set(3, new[] { new SpeakerRow(" A ", "ff00aa"), new SpeakerRow("B", ""), new SpeakerRow("", "") });

        // 動画: streamer は 1 人目・speakers に names(今までどおり)と people
        string v = RequestJson.Video(id, new[] { "a.mp4" }, "m", Flow.Auto, T, three, 1, Cut.None);
        Eq("{\"v\":1,\"kind\":\"video\",\"id\":\"20261001-120000-abcdef\",\"flow\":\"auto\",\"files\":[\"a.mp4\"],\"streamer\":\"A\",\"memo\":\"m\"," +
           "\"speakers\":{\"count\":3,\"names\":[\"A\",\"B\"],\"people\":[{\"name\":\"A\",\"style\":{\"color\":\"FF00AA\"}},{\"name\":\"B\"}]}," +
           "\"videoTracks\":1,\"cut\":\"none\",\"sentAt\":\"2026-10-01T12:00:00+09:00\"}", v, "動画の形(順番も)");
        var sp = Json.Dict(Json.Parse(v), "speakers");
        var people = Json.List(sp, "people").ToList();
        Eq(2, people.Count, "people は名前のある行だけ");
        Eq("A", Json.Str(people[0], "name"), "入力の順");
        Eq("FF00AA", Json.Str(Json.Dict(people[0], "style"), "color"), "色は # なしの大文字 6 桁");
        True(!people[1].ContainsKey("style"), "色を入れていない行は style ごと書かない");

        // URL: 1 人目の名前があれば streamer(items の後・memo の前)
        var items = new List<UrlItem> { new UrlItem { Url = Norm, Top = 3 } };
        string u = RequestJson.Url(id, items, "m", Flow.Auto, T, three, 1, Cut.None, null);
        True(u.Contains("\"top\":3}],\"streamer\":\"A\",\"memo\":\"m\",\"speakers\":{\"count\":3,"), "URL にも streamer: " + u);
        Eq("A", Json.Str(Json.Parse(u), "streamer"), "URL の streamer を読み直す");
        Eq(2, Json.List(Json.Dict(Json.Parse(u), "speakers"), "people").Count(), "URL の people");

        // 1 人目が空: streamer は URL では書かない・動画では今までどおり空文字(2 人目以降の名前は繰り上げない)
        var second = set(2, new[] { new SpeakerRow("", ""), new SpeakerRow("B", "19D3F3") });
        string u2 = RequestJson.Url(id, items, "", Flow.Auto, T, second, 1, Cut.None, null);
        True(!u2.Contains("streamer"), "1 人目が空なら URL に streamer は無い: " + u2);
        Eq("", Json.Str(Json.Parse(RequestJson.Video(id, new[] { "a.mp4" }, "", Flow.Auto, T, second, 1, Cut.None)), "streamer"), "動画は空文字");
        Eq("B", Json.Str(Json.List(Json.Dict(Json.Parse(u2), "speakers"), "people").Single(), "name"), "people は名前のある行だけ");

        // 人数 0: speakers のキーごと書かない(名前や色が残っていても)。streamer も URL には無い
        var zero = set(0, new[] { new SpeakerRow("A", "FF00AA") });
        True(!RequestJson.Url(id, items, "", Flow.Auto, T, zero, 1, Cut.None, null).Contains("speakers"), "人数 0(URL)");
        string vz = RequestJson.Video(id, new[] { "a.mp4" }, "", Flow.Auto, T, zero, 1, Cut.None);
        True(!vz.Contains("speakers") && vz.Contains("\"streamer\":\"\""), "人数 0(動画): " + vz);
        True(!RequestJson.Url(id, items, "", Flow.Auto, T, null, 1, Cut.None, null).Contains("speakers"), "null");

        // 名前のある行が無い: people は書かない(count と names だけ)
        string none = RequestJson.Url(id, items, "", Flow.Auto, T, set(2, new[] { new SpeakerRow("", ""), new SpeakerRow(" ", "") }), 1, Cut.None, null);
        True(none.Contains("\"speakers\":{\"count\":2,\"names\":[]}") && !none.Contains("people"), "名前なしで人数だけ: " + none);

        // 6 桁でない色は書かない(画面が止めるが、JSON は不正な色を出さない)・同じ名前は先の行にまとめる(先の行に色が無ければ後の行の色)
        var odd = set(3, new[] { new SpeakerRow("A", "xyz"), new SpeakerRow("A", "FF00AA"), new SpeakerRow("B", "FF00A") });
        var oddPeople = Json.List(Json.Dict(Json.Parse(RequestJson.Url(id, items, "", Flow.Auto, T, odd, 1, Cut.None, null)), "speakers"), "people").ToList();
        True(oddPeople.Count == 2 && Json.Str(Json.Dict(oddPeople[0], "style"), "color") == "FF00AA" && !oddPeople[1].ContainsKey("style"), "不正な色は捨てる・同じ名前はまとめる");
        string longName = new string('あ', 70);
        var longSet = set(1, new[] { new SpeakerRow(longName, "") });
        Eq(new string('あ', 60), Json.Str(Json.List(Json.Dict(Json.Parse(RequestJson.Url(id, items, "", Flow.Auto, T, longSet, 1, Cut.None, null)), "speakers"), "people").Single(), "name"), "名前は 60 文字まで");
        Eq(new string('あ', 60), Json.Str(Json.Parse(RequestJson.Url(id, items, "", Flow.Auto, T, longSet, 1, Cut.None, null)), "streamer"), "streamer も 60 文字まで");

        // 今までの形のキーはそのまま(古い PC が読むもの)。色を入れても streamer・names・count は変わらない
        var d = Json.Parse(v);
        foreach (string k in new[] { "v", "kind", "id", "files", "streamer", "memo", "sentAt", "flow", "speakers", "videoTracks", "cut" }) True(d.ContainsKey(k), "動画のキー: " + k);
        True(Json.Long(sp, "count", -1) == 3 && sp.ContainsKey("names"), "count と names");
    }

    static void VideoTracksJson()
    {
        string id = "20261001-120000-abcdef";
        Func<string, int, string> url = (flow, tracks) => RequestJson.Url(id, Items(3, Norm), "", flow, T, null, tracks, Cut.None, null);
        Func<string, int, string> video = (flow, tracks) => RequestJson.Video(id, new[] { "a.mp4" }, "", flow, T, null, tracks, Cut.None);
        Eq(3L, Json.Long(Json.Parse(url(Flow.Auto, 3)), "videoTracks", -1), "URL・①・3");
        Eq(5L, Json.Long(Json.Parse(video(Flow.Auto, 5)), "videoTracks", -1), "動画・①・5");
        Eq(1L, Json.Long(Json.Parse(video(Flow.Auto, 1)), "videoTracks", -1), "1 も書く");
        True(!video(Flow.Check, 3).Contains("videoTracks"), "② は書かない");
        True(!url(Flow.Manual, 3).Contains("videoTracks"), "③ は書かない");
        Eq(1L, Json.Long(Json.Parse(url(Flow.Auto, 6)), "videoTracks", -1), "範囲の外は 1");
        Eq("V1〜V3 に同じ動画(重ねて加工する用)、V4(いちばん上)に字幕", VideoTracks.Hint(3), "案内");
        Eq("V1 に動画、V2 に字幕", VideoTracks.Hint(1), "案内(1)");
    }

    static void UrlJson()
    {
        string id = "20261001-120000-000001";
        string json = RequestJson.Url(id, Items(5, Norm, "https://www.youtube.com/watch?v=AAAAAAAAAAA"), "", Flow.Manual, T, null, 1, Cut.None, null);
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
        // YouTube の URL は、要る欄だけ(allowUrl)。ほかの画面で使い回すときは時刻の形だけ読む
        int plain;
        True(TimeText.TryParse("1:23:45", false, out plain) && plain == 5025 && TimeText.TryParse("1h2m3s", false, out plain) && plain == 3723, "URL なしでも時刻の形は読む");
        True(!TimeText.TryParse("https://youtu.be/dQw4w9WgXcQ?t=5025", false, out plain) && !TimeText.TryParse("t=75", false, out plain) &&
             !TimeText.TryParse("https://example.com/1h2m3s", false, out plain), "URL なしのときは YouTube の URL を読まない");
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
        string json = RequestJson.Url(id, items, "メモ", Flow.Auto, T, null, 2, Cut.Silence, w);
        Eq("{\"v\":1,\"kind\":\"url\",\"id\":\"20261001-120000-000001\",\"flow\":\"auto\",\"items\":[" +
           "{\"url\":\"https://www.youtube.com/watch?v=dQw4w9WgXcQ\",\"top\":3,\"ranges\":[{\"start\":5025,\"end\":5110}]}," +
           "{\"url\":\"https://www.youtube.com/watch?v=AAAAAAAAAAA\",\"top\":2}],\"memo\":\"メモ\",\"videoTracks\":2,\"cut\":\"silence\"," +
           "\"weights\":{\"audio\":1.5,\"chat\":0.0,\"comments\":3.0},\"sentAt\":\"2026-10-01T12:00:00+09:00\"}", json, "① の形(順番も)");
        Json.Parse(json);

        string check = RequestJson.Url(id, items, "", Flow.Check, T, null, 2, Cut.Silence, new Weights());
        True(check.Contains("\"ranges\"") && !check.Contains("\"cut\"") && !check.Contains("\"videoTracks\"") && !check.Contains("\"weights\""), "② は区間だけ(カット・トラック・指定しない重みは書かない): " + check);
        string manual = RequestJson.Url(id, items, "", Flow.Manual, T, null, 2, Cut.Silence, w);
        True(!manual.Contains("\"ranges\"") && !manual.Contains("\"cut\"") && manual.Contains("\"weights\""), "③ は区間を書かない・重みは書く(解析に使う): " + manual);
        True(RequestJson.Url(id, items, "", Flow.Auto, T, null, 1, "bogus", null).Contains("\"cut\":\"none\""), "知らないカットは none");

        string video = RequestJson.Video(id, new[] { "a.mp4" }, "", Flow.Auto, T, null, 1, Cut.Silence);
        True(video.Contains("\"videoTracks\":1,\"cut\":\"silence\",\"sentAt\""), "動画の依頼にもカット(トラックの後): " + video);
        True(!RequestJson.Video(id, new[] { "a.mp4" }, "", Flow.Check, T, null, 1, Cut.Silence).Contains("\"cut\""), "動画の ② はカットを書かない");
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
                var all = FindAll(f).OfType<Btn>().Single(b => b.AccessibleName == "すべて受け取る");
                True(!all.Enabled && all.Text == "すべて受け取る", "届いたものが無ければ「すべて受け取る」は押せない: " + all.Text);
                True(FindAll(f).OfType<Btn>().Any(b => b.Text == "やめる" && !b.Visible), "「やめる」は受け取っている間だけ出す");
                var sample = Program_SampleListing();
                f.ShowEntries(sample);
                Eq("すべて受け取る(2 本)", all.Text, "届いているパックの数を出す");
                True(all.Enabled, "パックがあれば押せる");
            }
        }
        finally { Directory.Delete(dir, true); }
    }

    static void Key(System.Windows.Forms.Control c, System.Windows.Forms.Keys k)
    {
        typeof(System.Windows.Forms.Control).GetMethod("OnKeyDown", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)
            .Invoke(c, new object[] { new System.Windows.Forms.KeyEventArgs(k) });
    }

    static void TimeBoxKeys()
    {
        using (var tb = new TimeBox("開始の時刻"))
        {
            var K = typeof(System.Windows.Forms.Keys);
            int changed = 0;
            tb.ValueChanged += () => changed++;
            True(!tb.HasValue && tb.Text == "0:00:00", "はじめは空(形だけ出す)");
            True(!tb.AcceptYouTubeUrl, "YouTube の URL の貼り付けは、指定した欄だけ(既定はオフ)");
            foreach (var k in new[] { System.Windows.Forms.Keys.D1, System.Windows.Forms.Keys.NumPad2, System.Windows.Forms.Keys.D3, System.Windows.Forms.Keys.D4, System.Windows.Forms.Keys.D5 }) Key(tb, k);
            Eq("1:23:45", tb.Text, "数字だけで入る(テンキーも)");
            True(tb.HasValue && tb.Value == 5025 && changed > 0, "値と知らせ");
            Key(tb, System.Windows.Forms.Keys.OemSemicolon);
            Key(tb, System.Windows.Forms.Keys.A);
            Eq("1:23:45", tb.Text, "「:」や文字は入らない");
            Key(tb, System.Windows.Forms.Keys.Left);
            Key(tb, System.Windows.Forms.Keys.Up);
            Eq("1:24:45", tb.Text, "← で分を選んで ↑");
            Key(tb, System.Windows.Forms.Keys.Down | System.Windows.Forms.Keys.Shift);
            Eq("1:14:45", tb.Text, "Shift+↓ は 10 ずつ");
            Key(tb, System.Windows.Forms.Keys.Back);
            Eq("1:00:45", tb.Text, "BackSpace は選んだ所を 0 に");
            Key(tb, System.Windows.Forms.Keys.D3); Key(tb, System.Windows.Forms.Keys.D0);
            Eq("1:30:45", tb.Text, "選んだ所だけ打ち直す");
            Key(tb, System.Windows.Forms.Keys.Delete);
            True(!tb.HasValue && tb.Text == "0:00:00", "Delete で空に");
            tb.SetValue(36000 + 62);
            Eq("10:01:02", tb.Text, "10 時間より後");
            True(K != null && !(((object)tb) is System.Windows.Forms.TextBoxBase), "標準の入力欄ではない(打ち込み・貼り付けで形が壊れない)");
        }
    }

    static void StreamCards()
    {
        using (var c = new StreamCard(3))
        {
            True(c.IsBlank && c.VideoId == null, "はじめは空");
            string[] more = null;
            c.MoreUrls += lines => more = lines;
            c.SetUrlLines("https://youtu.be/dQw4w9WgXcQ?t=5025\r\n\r\nhttps://youtu.be/AAAAAAAAAAA\nhttps://example.com/x");
            Eq("dQw4w9WgXcQ", c.VideoId, "1行目がこのカードに入る");
            Eq(2, more == null ? 0 : more.Length, "残りの行はカードを増やす(空の行は飛ばす)");
            var row = c.Rows.First();
            True(row.Start.AcceptYouTubeUrl && row.End.AcceptYouTubeUrl, "配信の区間の欄は YouTube の URL も貼れる");
            True(row.Start.HasValue && row.Start.Value == 5025 && !row.End.HasValue, "t= つきの URL: 最初の区間の開始に入る");
            Eq(0, c.ToItem().Ranges.Count, "終了が無い区間は送らない");
            row.SetLength(60);
            var item = c.ToItem();
            Eq(Norm, item.Url, "URL は正規化して送る");
            True(item.Ranges.Count == 1 && item.Ranges[0].Start == 5025 && item.Ranges[0].End == 5085 && item.Top == 3 && item.AutoCount == 2, "+1分 → 指定 1 + 自動 2");
            Eq(null, c.Validate_(new HashSet<string>()), "誤りなし");
            True(c.Validate_(new HashSet<string> { "dQw4w9WgXcQ" }) == c.Url, "同じ配信が上にあれば URL の欄へ");

            row.End.SetValue(5000);
            True(row.Problem != null && row.Problem.Contains("終了が開始より前") && c.Validate_(new HashSet<string>()) == row.End, "終了 ≤ 開始は、その場で誤り・送るときは終了の欄へ");
            Eq(0, c.ToItem().Ranges.Count, "誤りの区間は送らない");
            row.End.SetValue(5100);
            c.SetManual(true);
            Eq(0, c.ToItem().Ranges.Count, "③ では区間を送らない");
            Eq(null, c.Validate_(new HashSet<string>()), "③ では区間を確かめない");
            c.SetManual(false);
            Eq(1, c.ToItem().Ranges.Count, "①② に戻すと値は残っている");
        }
        using (var c = new StreamCard(1))
        {
            var row = c.Rows.First();
            row.Start.SetValue(10);
            True(row.Problem == null, "打っている途中(終了がまだ)は急かさない");
            c.SetUrlLines("https://example.com/watch?v=dQw4w9WgXcQ");
            True(c.Validate_(new HashSet<string>()) == c.Url, "YouTube でない URL は URL の欄へ");
            c.Url.Text = "https://youtu.be/dQw4w9WgXcQ";
            True(c.Validate_(new HashSet<string>()) == row.End && row.Problem.Contains("終了の時刻"), "送るときは、終了の無い区間を誤りにする");
        }
    }

    static void FormSpeakers()
    {
        string dir = TempDir();
        try
        {
            File.WriteAllText(Path.Combine(dir, "members.json"), "{\"groups\":[{\"members\":[{\"name\":\"さくらみこ\"},{\"name\":\"兎田ぺこら\"}]}]}", Encoding.UTF8);
            using (var f = new MainForm(dir, new string[0]))
            {
                var combos = FindAll(f).OfType<ThemedCombo>().ToList();
                var colors = FindAll(f).OfType<System.Windows.Forms.TextBox>().Where(t => t.AccessibleName != null && t.AccessibleName.Contains("字幕の色")).ToList();
                var chips = FindAll(f).OfType<ColorChip>().ToList();
                Eq(Speakers.MaxCount, combos.Count, "名前のプルダウンは 10 人ぶん");
                Eq(Speakers.MaxCount, colors.Count, "色の欄も 10 人ぶん");
                True(combos.All(c => c.DropDownStyle == System.Windows.Forms.ComboBoxStyle.DropDown && c.Items.Count == 2 && c.MaxLength == Speakers.MaxNameLength), "一覧から選べて・打てる(一覧は members.json・名前は 60 文字まで)");
                True(colors.All(t => t.CharacterCasing == System.Windows.Forms.CharacterCasing.Upper), "色は大文字で入る");
                var count = FindAll(f).OfType<Stepper>().Single(s => s.Minimum == 0 && s.Maximum == Speakers.MaxCount);
                True(FindAll(f).OfType<SectionHead>().Any(h => h.AccessibleName == "配信者・メモ"), "見出しは「配信者・メモ」");
                True(!FindAll(f).OfType<Lbl>().Any(l => l.Text.Contains("配信者(任意)")), "動画の側の 1 つだけの「配信者」の欄は無い");

                // 色の欄: 貼った #ff00aa や空白は直る・見本は 6 桁そろったときだけ
                count.Value = 3;
                colors[0].Text = "#ff00aa ";
                Eq("FF00AA", colors[0].Text, "貼った # と空白は外して大文字に");
                True(chips[0].Swatch.HasValue && chips[0].Swatch.Value.ToArgb() == System.Drawing.Color.FromArgb(0xFF, 0x00, 0xAA).ToArgb(), "6 桁そろったら見本に色が出る");
                colors[0].Text = "FF0";
                True(!chips[0].Swatch.HasValue, "途中は枠だけ");
                colors[0].Text = "";
                Eq("", chips[0].Note, "名前も空なら注は出ない");

                // 注: 色が空で名前がメンバー → メンバーカラー / 一覧に無い名前 → 色なし / 色を入れたら注は消える
                combos[0].Text = "さくらみこ";
                Eq("メンバーカラー", chips[0].Note, "メンバーの名前");
                combos[0].Text = "どこかのゲスト";
                Eq("色なし", chips[0].Note, "一覧に無い名前");
                colors[0].Text = "19d3f3";
                Eq("", chips[0].Note, "色を入れたら注は出ない");
                True(chips[0].Swatch.HasValue, "見本は出る");

                // 送る前に止める: 色だけで名前が空・6 桁でない
                combos[0].Text = "";
                colors[0].Text = "";
                combos[1].Text = "ゲストの人";
                colors[1].Text = "1234";
                colors[2].Text = "ff00aa";   // 名前が空
                f.ApplyState("");
                var texts0 = FindAll(f).OfType<Lbl>().Where(l => l.Visible).Select(l => l.Text).ToList();
                True(!texts0.Any(t => t.Contains("直す所") || t.Contains("名前も入れて")), "送る前は急かさない");
                f.ApplyState("speakers");   // 見本の状態(4 人・色だけで名前が空・色が 2 桁)で「送る」を押す = 止まる
                var texts = FindAll(f).OfType<Lbl>().Select(l => l.Text).ToList();
                True(texts.Any(t => t.Contains("配信者 3: 名前も入れて") && t.Contains("配信者 4: 色は 16 進の 6 桁")), "理由が出る: " + string.Join(" | ", texts.Where(t => t.Contains("配信者"))));
                True(texts.Any(t => t.Contains("直す所があります")), "下の帯にも出る");
                var errors = FindAll(f).OfType<Field>().Where(x => x.Error).ToList();
                Eq(2, errors.Count, "枠の色が変わるのは、名前が空の欄と、色の欄の 2 つ");
                // 直せば、その場で消える
                combos[2].Text = "三人目";
                colors[3].Text = "123456";
                Eq(0, FindAll(f).OfType<Field>().Count(x => x.Error), "直したら枠は戻る");
                True(!FindAll(f).OfType<Lbl>().Any(l => l.Visible && l.Text.Contains("配信者 3: 名前も入れて")), "理由も消える");
            }
        }
        finally { Directory.Delete(dir, true); }
    }

    // 押しっぱなしの代わり(左のボタンが押されたまま・マウスがボタンの上かを差し替える)
    class HeldBtn : RepeatBtn
    {
        public bool HeldNow = true, Over = true;
        public HeldBtn() : base("+") { }
        protected override bool Held { get { return HeldNow; } }
        protected override bool PointerOver { get { return Over; } }
    }

    static object Call(object target, Type type, string method, params object[] args)
    {
        return type.GetMethod(method, System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance).Invoke(target, args);
    }

    static System.Windows.Forms.MouseEventArgs LeftButton()
    {
        return new System.Windows.Forms.MouseEventArgs(System.Windows.Forms.MouseButtons.Left, 1, 5, 5, 0);
    }

    static void RepeatButtons()
    {
        using (var b = new HeldBtn())
        {
            int n = 0;
            b.Step += () => n++;
            Call(b, typeof(System.Windows.Forms.Control), "OnMouseDown", LeftButton());
            Eq(1, n, "押したときに 1 回");
            Call(b, typeof(RepeatBtn), "Repeat");
            Call(b, typeof(RepeatBtn), "Repeat");
            Eq(3, n, "押し続けると続けて動く");
            b.Over = false;
            Call(b, typeof(RepeatBtn), "Repeat");
            Eq(3, n, "ボタンの外へずらしている間は止まる");
            b.Over = true;
            Call(b, typeof(RepeatBtn), "Repeat");
            Eq(4, n, "戻せば続く");
            Call(b, typeof(System.Windows.Forms.Control), "OnClick", EventArgs.Empty);
            Eq(4, n, "マウスで押した分は、離したときの Click では数えない");
            Call(b, typeof(System.Windows.Forms.Control), "OnMouseUp", LeftButton());
            b.HeldNow = false;
            Call(b, typeof(RepeatBtn), "Repeat");
            Eq(4, n, "離したら止まる");
            Call(b, typeof(System.Windows.Forms.Control), "OnClick", EventArgs.Empty);
            Eq(5, n, "キー(Space・Enter)は 1 回ずつ");
            True(RepeatBtn.FirstDelayMs >= 300 && RepeatBtn.RepeatMs > 0 && RepeatBtn.RepeatMs < RepeatBtn.FirstDelayMs, "続けて動くまで少し待つ");
        }
        using (var st = new Stepper(0, 3, 2, 30, "テスト"))
        {
            var buttons = st.Controls.OfType<RepeatBtn>().ToList();
            Eq(2, buttons.Count, "− と + は押しっぱなしで動くボタン");
            var plus = buttons[1];
            Call(plus, typeof(System.Windows.Forms.Control), "OnMouseDown", LeftButton());
            Eq(3, st.Value, "+ を押したとき");
            True(!plus.Enabled, "上限で + は使えなくなる(続けて動かない)");
            Call(buttons[0], typeof(System.Windows.Forms.Control), "OnClick", EventArgs.Empty);
            Eq(2, st.Value, "− をキーで");
        }
    }

    static void TitleMark()
    {
        using (var panel = new System.Windows.Forms.Panel { BackColor = Theme.P.Panel, Size = new System.Drawing.Size(Ui.S(300), Ui.S(24)) })
        {
            var title = new Lbl("✓ 【雑談】見本の配信の題名", Tone.Text) { AutoSize = false, AutoEllipsis = true, Font = Theme.Small, Bounds = new System.Drawing.Rectangle(0, 0, Ui.S(300), Ui.S(18)) };
            panel.Controls.Add(title);
            Func<System.Drawing.Bitmap> shot = () =>
            {
                var bmp = new System.Drawing.Bitmap(panel.Width, panel.Height);
                panel.DrawToBitmap(bmp, new System.Drawing.Rectangle(0, 0, panel.Width, panel.Height));
                return bmp;
            };
            using (var plain = shot())
            {
                title.AccentLead = "✓ ";
                using (var marked = shot())
                {
                    int lead = System.Windows.Forms.TextRenderer.MeasureText("✓ ", Theme.Small).Width;
                    int diff = 0, outside = 0;
                    for (int y = 0; y < plain.Height; y++)
                        for (int x = 0; x < plain.Width; x++)
                            if (plain.GetPixel(x, y) != marked.GetPixel(x, y)) { diff++; if (x >= lead) outside++; }
                    True(diff > 0, "✓ の色が変わる");
                    Eq(0, outside, "✓ のほかの文字は 1 回で描いたときと同じ");
                }
            }
        }
        using (var card = new StreamCard(3))
        {
            card.Sample(Norm, "見本の題名", 3);
            True(FindAll(card).OfType<Lbl>().Any(l => l.AccentLead == "✓ " && l.Text == "✓ 見本の題名"), "配信のカードの題名に ✓");
        }
    }

    static void CtrlEnter()
    {
        string dir = TempDir();
        try
        {
            using (var f = new MainForm(dir, new string[0]))
            {
                Func<System.Windows.Forms.Keys, bool> press = k => (bool)Call(f, typeof(System.Windows.Forms.Form), "ProcessCmdKey", new System.Windows.Forms.Message(), k);
                var ctrlEnter = System.Windows.Forms.Keys.Control | System.Windows.Forms.Keys.Enter;
                var count = FindAll(f).OfType<Stepper>().Single(s => s.Minimum == 0 && s.Maximum == Speakers.MaxCount);
                count.Value = 1;
                FindAll(f).OfType<System.Windows.Forms.TextBox>().First(t => t.AccessibleName != null && t.AccessibleName.Contains("字幕の色")).Text = "ff00aa";   // 名前が空で色だけ = 誤り
                Func<bool> stopped = () => FindAll(f).OfType<Lbl>().Any(l => l.Text.Contains("直す所があります"));
                f.ShowPage(false);
                True(!press(ctrlEnter) && !stopped(), "受け取るの画面では何もしない");
                f.ShowPage(true);
                True(!press(System.Windows.Forms.Keys.Enter) && !stopped(), "Enter だけでは送らない");
                True(press(ctrlEnter), "送るの画面では Ctrl+Enter を使う(メモの欄でも改行にしない)");
                True(stopped(), "「送る」と同じ検査が動く");
            }
        }
        finally { Directory.Delete(dir, true); }
    }

    static void ManySpeakers()
    {
        string dir = TempDir();
        try
        {
            using (var f = new MainForm(dir, new string[0], Path.Combine(dir, "state")))
            {
                f.StartPosition = System.Windows.Forms.FormStartPosition.Manual;
                f.Location = new System.Drawing.Point(-32000, -32000);
                f.ShowInTaskbar = false;
                f.ClientSize = new System.Drawing.Size(Ui.S(1000), Ui.S(700));
                f.Show();
                var flags = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
                var names = (System.Windows.Forms.Panel)typeof(MainForm).GetField("namesPane", flags).GetValue(f);
                var right = (VStack)typeof(MainForm).GetField("right", flags).GetValue(f);
                var memo = (Field)typeof(MainForm).GetField("memoField", flags).GetValue(f);
                var count = FindAll(f).OfType<Stepper>().Single(s => s.Minimum == 0 && s.Maximum == Speakers.MaxCount);
                count.Value = 2;
                System.Windows.Forms.Application.DoEvents();
                Eq(names.AutoScrollMinSize.Height, names.Height, "2 人: 行はそのまま");
                count.Value = Speakers.MaxCount;
                System.Windows.Forms.Application.DoEvents();
                True(names.Height < names.AutoScrollMinSize.Height && names.Height >= right.ShrinkMin, "10 人: 行の欄を縮めて中でスクロール(" + names.Height + " / " + names.AutoScrollMinSize.Height + ")");
                True(memo.Bottom <= right.ClientSize.Height && memo.Height >= right.FillMin && !right.VerticalScroll.Visible, "メモは右の列の中に見えている(列はスクロールしない)");
                True(!names.HorizontalScroll.Visible && names.Controls.Cast<System.Windows.Forms.Control>().Where(c => c.Visible).All(c => c.Right <= names.ClientSize.Width), "横にははみ出さない");
                FindAll(f).OfType<Check>().Single(c => c.Text.StartsWith("見どころの重み")).Checked = true;
                System.Windows.Forms.Application.DoEvents();
                True(names.Height == names.AutoScrollMinSize.Height && right.VerticalScroll.Visible, "縮めても入りきらない(重みも出した)ときは縮めず、今までどおり列ごとスクロール(二重のスクロールにしない)");
                FindAll(f).OfType<Check>().Single(c => c.Text.StartsWith("見どころの重み")).Checked = false;
                System.Windows.Forms.Application.DoEvents();
                True(names.Height < names.AutoScrollMinSize.Height, "重みを閉じれば、また縮める");
                f.ClientSize = new System.Drawing.Size(Ui.S(1000), Ui.S(1000));
                System.Windows.Forms.Application.DoEvents();
                Eq(names.AutoScrollMinSize.Height, names.Height, "窓を大きくすれば全部の行が出る");
                f.Hide();
            }
        }
        finally { Directory.Delete(dir, true); }
    }

    static void FormSummary()
    {
        string dir = TempDir();
        try
        {
            using (var f = new MainForm(dir, new string[0]))
            {
                f.ApplySample();
                var texts = FindAll(f).OfType<Lbl>().Select(l => l.Text).ToList();
                True(texts.Any(t => t.StartsWith("配信 2 本(指定 2 + 自動 3)") && t.Contains("① 全自動") && t.Contains("カットしない") && t.Contains("トラック 1") && t.Contains("配信者 2 人")),
                     "下の帯の要約: " + string.Join(" | ", texts.Where(t => t.StartsWith("配信"))));
                True(texts.Any(t => t.Contains("終了が開始より前")), "誤りの区間の理由が出る");
                Eq(2, FindAll(f).OfType<StreamCard>().Count(), "配信のカード");
                True(f.Text.Contains("1 件届いています"), "届いた数を窓の題名に: " + f.Text);
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
        Eq("auto", Json.Str(Json.Parse(RequestJson.Url(id, Items(3, Norm), "", "bogus", T, null, 1, Cut.None, null)), "flow"), "JSON には知らない値を書かない");
        foreach (string f in Flow.All)
        {
            Eq(f, Json.Str(Json.Parse(RequestJson.Url(id, Items(3, Norm), "", f, T, null, 1, Cut.None, null)), "flow"), "URL の依頼: " + f);
            Eq(f, Json.Str(Json.Parse(RequestJson.Video(id, new[] { "a.mp4" }, "", f, T, null, 1, Cut.None)), "flow"), "動画の依頼: " + f);
        }
        // 前からのキーはそのまま
        var d = Json.Parse(RequestJson.Video(id, new[] { "a.mp4" }, "m", Flow.Check, T, One("さくらみこ"), 1, Cut.None));
        foreach (string k in new[] { "v", "kind", "id", "files", "streamer", "memo", "sentAt", "flow" }) True(d.ContainsKey(k), "動画の依頼のキー: " + k);
        d = Json.Parse(RequestJson.Url(id, Items(3, Norm), "m", Flow.Check, T, null, 1, Cut.None, null));
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

    // 画面の確認(--tab receive --sample)と同じ見本: パック 2 本(同じ依頼)+ 失敗 1 件
    static OutputListing Program_SampleListing()
    {
        var l = new OutputListing();
        var a = OutputFolder.FromName("20261002-120000-0a1b2c__A.zip"); a.Size = 10; a.Modified = new DateTime(2026, 10, 2, 13, 0, 0); a.PathLower = "/出力/a.zip"; a.Rev = "1";
        var f = OutputFolder.FromName("20261002-110000-0d4e5f__F.失敗.txt"); f.Size = 1; f.Modified = new DateTime(2026, 10, 2, 11, 0, 0); f.PathLower = "/出力/f.txt"; f.Rev = "2";
        var b = OutputFolder.FromName("20261002-120000-0a1b2c__B.zip"); b.Size = 20; b.Modified = new DateTime(2026, 10, 2, 12, 0, 0); b.PathLower = "/出力/b.zip"; b.Rev = "3";
        l.Entries.Add(a); l.Entries.Add(f); l.Entries.Add(b);
        return l;
    }

    static void ReceiveAll()
    {
        var all = Program_SampleListing().Entries;
        var a = all[0];
        var c = OutputFolder.FromName("20261001-090000-ffffff__C.zip"); c.Size = -1; c.Modified = new DateTime(2026, 10, 2, 12, 0, 0);
        all.Add(c);
        OutputFolder.SortNewestFirst(all);
        var packs = OutputFolder.PacksOldestFirst(all);
        Eq(3, packs.Count, "失敗の知らせは含めない");
        Eq("C", packs[0].Title, "古い順(同じ時刻は名前の順)");
        Eq("B", packs[1].Title, "古い順 2");
        Eq("A", packs[2].Title, "古い順 3(新しいものが最後)");
        Eq(30L, OutputFolder.TotalSize(packs), "合計(大きさの分からないものは 0)");
        Eq(2, OutputFolder.CountSameRequest(all, a), "同じ依頼のパックの数(自分を含む)");
        Eq(1, OutputFolder.CountSameRequest(all, c), "1 本だけの依頼");
        var h = OutputFolder.FromName("手で置いた.zip");
        Eq(0, OutputFolder.CountSameRequest(new[] { h, h }, h), "id の無いものは数えない");

        var r = new ReceiveAllResult { Total = 3 };
        r.Done.Add(a); r.Done.Add(c); r.Done.Add(packs[1]);
        True(r.Summary(null).StartsWith("3 本すべて受け取りました ✓"), "全部: " + r.Summary(null));
        r = new ReceiveAllResult { Total = 3 };
        r.Done.Add(a); r.Failed.Add("B"); r.Failed.Add("C");
        string s = r.Summary(null);
        True(s.StartsWith("1 / 3 本を受け取りました。受け取れなかった 2 本: B・C") && s.Contains("もう一度「すべて受け取る」"), "飛ばしたものの題: " + s);
        r = new ReceiveAllResult { Total = 3 };
        r.Done.Add(a); r.Kept.Add(c); r.Canceled = true;
        s = r.Summary(null);
        True(s.StartsWith("やめました(2 / 3 本は受け取り済み)") && s.Contains("消せなかった 1 本"), "やめた + 消せなかった: " + s);
        r = new ReceiveAllResult { Total = 3, Error = new Exception("x") };
        s = r.Summary("通信が切れました");
        Eq("0 / 3 本を受け取ったところで止まりました: 通信が切れました", s, "止まった");
        Eq(0, r.Received, "受け取った数");
        r.Failed.AddRange(new[] { "1", "2", "3", "4" });
        r.Error = null;
        True(r.Summary(null).Contains("1・2・3 ほか"), "題は 3 つまで: " + r.Summary(null));
    }

    // zip を作る。"名前" か "名前=中身"。名前の末尾が / ならフォルダ
    static void MakeZip(string path, params string[] entries)
    {
        using (var fs = new FileStream(path, FileMode.Create))
        using (var z = new ZipArchive(fs, ZipArchiveMode.Create))
            foreach (string spec in entries)
            {
                int eq = spec.IndexOf('=');
                string name = eq >= 0 ? spec.Substring(0, eq) : spec, body = eq >= 0 ? spec.Substring(eq + 1) : "";
                var e = z.CreateEntry(name);
                if (!name.EndsWith("/")) using (var w = new StreamWriter(e.Open(), new UTF8Encoding(false))) w.Write(body);
            }
    }

    static void ExtractZips()
    {
        string dir = TempDir();
        try
        {
            string zip = Path.Combine(dir, "20261002-120000-0a1b2c__みこの配信.zip");
            MakeZip(zip, "みこの配信_pack/", "みこの配信_pack/みこの配信.mp4=VIDEO", "みこの配信_pack/sub/", "みこの配信_pack/sub/a.srt=1", "みこの配信_pack/友人へ.txt=読んで");
            long last = -1, lastTotal = -1;
            string got = Receiving.Extract(zip, dir, (d, t) => { last = d; lastTotal = t; });
            Eq(Path.Combine(dir, "みこの配信_pack"), got, "パックのフォルダを保存先の直下に");
            Eq("VIDEO", File.ReadAllText(Path.Combine(got, "みこの配信.mp4")), "中身");
            Eq("1", File.ReadAllText(Path.Combine(got, "sub", "a.srt")), "下のフォルダ");
            Eq("読んで", File.ReadAllText(Path.Combine(got, "友人へ.txt")), "日本語の名前");
            True(!File.Exists(zip), "展開できたら zip は消す");
            True(last == lastTotal && lastTotal > 0, "進み具合は最後に 済んだ = 全体: " + last + " / " + lastTotal);
            True(!Directory.Exists(got + ".extracting"), "途中のフォルダは残さない");

            MakeZip(zip, "みこの配信_pack/x.txt=2");
            Eq(Path.Combine(dir, "みこの配信_pack (2)"), Receiving.Extract(zip, dir, null), "同じ名前があれば (2)");

            string flat = Path.Combine(dir, "手で置いた.zip");
            MakeZip(flat, "a.txt=a", "b/c.txt=c");
            string gotFlat = Receiving.Extract(flat, dir, null);
            Eq(Path.Combine(dir, "手で置いた"), gotFlat, "直下にファイルがあれば zip の名前のフォルダ");
            Eq("c", File.ReadAllText(Path.Combine(gotFlat, "b", "c.txt")), "中のフォルダ");

            string two = Path.Combine(dir, "two.zip");
            MakeZip(two, "p/a.txt=a", "q/b.txt=b");
            Eq(Path.Combine(dir, "two"), Receiving.Extract(two, dir, null), "先頭のフォルダが 2 つなら zip の名前");

            string evil = Path.Combine(dir, "evil.zip");
            MakeZip(evil, "p/ok.txt=1", "p/../../evil.txt=x");
            bool refused = false;
            try { Receiving.Extract(evil, dir, null); }
            catch (InvalidDataException) { refused = true; }
            True(refused, "外へ出る名前は断る");
            True(File.Exists(evil) && !Directory.Exists(Path.Combine(dir, "p")) && !Directory.Exists(Path.Combine(dir, "p.extracting")) &&
                 !File.Exists(Path.Combine(Path.GetDirectoryName(dir), "evil.txt")), "断ったら zip は残し、途中のフォルダは消し、外には何も書かない");
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
