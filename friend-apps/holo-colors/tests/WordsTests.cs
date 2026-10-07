// マイワード・お気に入り・最近使ったものの中身のテスト(CoreTests.Main から WordsTests.RunAll(Run); で呼ぶ)
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using HoloColors;
using FriendApps;

public static class WordsTests
{
    public static void RunAll(Action<string, Action> run)
    {
        run("マイワード: 追加・編集・削除・並べ替えが残る", Basic);
        run("マイワード: 確かめる(空・長すぎ・名前の既定)と複数行", Validate);
        run("マイワード: 壊れたファイルは取っておく", Corrupt);
        run("マイワード: 開けないファイルは上書きしない", Locked);
        run("マイカラー: MoveTo と Remove(マイワードと同じ道)", ColorsMove);
        run("お気に入り: 切り替え・残る・消したら外れる", Favorites);
        run("最近使ったもの: 順番・重なり・5件・残る", Recent);
        run("設定: お気に入り・最近の壊れた値に耐える", Garbage);
        run("branch: WORD/FAV/RECENT は members.json に書けない・札に WORD", Branch);
        run("検索: マイワードは本文で当たる・色は空", SearchAndColors);
    }

    static void True(bool ok, string msg)
    {
        if (!ok) throw new Exception("失敗: " + msg);
    }

    static void Eq(object expected, object actual, string msg)
    {
        if (!object.Equals(expected, actual))
            throw new Exception("失敗: " + msg + " (期待 " + expected + " / 実際 " + actual + ")");
    }

    static string TempDir()
    {
        string d = Path.Combine(Path.GetTempPath(), "hc-words-" + Guid.NewGuid().ToString("N").Substring(0, 8));
        Directory.CreateDirectory(d);
        return d;
    }

    static void Cleanup(string dir)
    {
        try { Directory.Delete(dir, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    static Store Reload(string dir)
    {
        var s = new Store(dir);
        s.Load();
        return s;
    }

    static void Basic()
    {
        string dir = TempDir();
        try
        {
            var s = Reload(dir);
            var a = s.AddWord("あいさつ", "こんにちは");
            var b = s.AddWord("", "二行目の名前\nつづき");
            var c = s.AddWord("三つ目", "3");
            True(a.IsWord && a.Hex == null && a.IsUser && a.Group == s.Words && a.Colors.Count == 0, "マイワードの形");
            True(a.Id.StartsWith("word/") && a.Id.Length == 5 + 12, "id の形");
            Eq("二行目の名前", b.Name, "名前が空なら最初の行");
            var r = Reload(dir);
            Eq(3, r.Words.Items.Count, "再読み込みで3件");
            Eq("あいさつ", r.Words.Items[0].Name, "順番");
            Eq("二行目の名前\nつづき", r.Words.Items[1].Text, "複数行が残る");
            Eq(a.Id, r.Words.Items[0].Id, "id が残る");
            True(File.ReadAllText(s.WordsPath, Encoding.UTF8).Contains("\"version\": 1"), "version");

            s.UpdateWord(a, "新しい名前", "新しい本文");
            r = Reload(dir);
            Eq("新しい名前", r.Words.Items[0].Name, "編集が残る");
            Eq("新しい本文", r.Words.Items[0].Text, "編集が残る");

            True(s.Move(c, -1), "Move");
            Eq(c.Id, Reload(dir).Words.Items[1].Id, "Move が残る");
            True(!s.Move(a, -1), "先頭は上がらない");
            True(s.MoveTo(c, 0), "MoveTo");
            Eq(c.Id, Reload(dir).Words.Items[0].Id, "MoveTo が残る");
            True(!s.MoveTo(c, -5), "先頭にいるので動かない");
            True(s.MoveTo(c, 99), "端に寄せる");
            Eq(c.Id, Reload(dir).Words.Items[2].Id, "末尾へ");

            s.Remove(b);
            r = Reload(dir);
            Eq(2, r.Words.Items.Count, "削除が残る");
            True(r.Words.Items.All(x => x.Id != b.Id), "消えた");
            try { s.UpdateWord(a, "x", "   "); throw new Exception("失敗: 空の本文で例外にならない"); }
            catch (ArgumentException) { }
            Eq("新しい本文", a.Text, "失敗した編集は反映しない");

            // ドラッグの落とし先(項目)はマイワードでも同じ道。別のグループの項目へは動かない
            True(s.MoveToEntry(a, c), "マイワードの MoveToEntry");          // a, c → c, a
            Eq(a.Id, Reload(dir).Words.Items[1].Id, "落とした先(末尾)の位置へ・残る");
            var color = s.Add("色", "#123456");
            True(!s.MoveToEntry(a, color), "マイワードをマイカラーの位置へは動かない");
            True(!s.MoveToEntry(color, a), "マイカラーをマイワードの位置へは動かない");
        }
        finally { Cleanup(dir); }
    }

    static void Validate()
    {
        string n;
        True(Store.ValidateWord("a", "", out n) != null, "空の本文");
        True(Store.ValidateWord("a", " \r\n\t ", out n) != null, "空白だけ");
        True(Store.ValidateWord("a", null, out n) != null, "null");
        True(Store.ValidateWord("a", new string('あ', Store.MaxWordText + 1), out n) != null, "長すぎ");
        True(Store.ValidateWord("a", new string('あ', Store.MaxWordText), out n) == null, "ちょうど");
        // 改行は \n として数える(\r\n が 2 文字にならない)
        True(Store.ValidateWord("a", string.Join("\r\n", Enumerable.Repeat("x", 2000)), out n) == null, "CRLF は1文字で数える");
        True(Store.ValidateWord(new string('名', Store.MaxName + 1), "x", out n) != null, "名前が長い");
        Eq(null, Store.ValidateWord("  ", "\n\n  最初の行  \n2行目", out n), "名前が空でも通る");
        Eq("最初の行", n, "名前 = 最初の空でない行");
        Eq(null, Store.ValidateWord("", new string('あ', 100), out n), "長い1行");
        Eq(Store.MaxName, n.Length, "名前は切る");
        Eq(null, Store.ValidateWord("  名  ", "x", out n), "名前は前後の空白を除く");
        Eq("名", n, "trim");

        Eq("a\r\nb\r\nc", Store.ClipboardText("a\nb\r\nc"), "ClipboardText");
        string dir = TempDir();
        try
        {
            var s = Reload(dir);
            var e = s.AddWord("複数行", "1行目\r\n2行目\r\n\r\n4行目");
            Eq("1行目\n2行目\n\n4行目", e.Text, "内部は \\n");
            Eq("1行目\r\n2行目\r\n\r\n4行目", Store.ClipboardText(Reload(dir).Words.Items[0].Text), "往復して CRLF に戻る");
        }
        finally { Cleanup(dir); }
    }

    static void Corrupt()
    {
        string dir = TempDir();
        try
        {
            File.WriteAllText(Path.Combine(dir, "my-words.json"), "{ こわれた", new UTF8Encoding(false));
            var s = Reload(dir);
            Eq(0, s.Words.Items.Count, "空で始まる");
            True(s.Warnings.Any(w => w.Contains("my-words.json")), "警告が出る");
            True(Directory.GetFiles(dir, "my-words.json.corrupt-*").Length == 1, "元のファイルを取っておく");
            s.AddWord("新しい", "本文");
            Eq(1, Reload(dir).Words.Items.Count, "そのあとは保存できる");
        }
        finally { Cleanup(dir); }
    }

    static void Locked()
    {
        string dir = TempDir();
        try
        {
            var first = Reload(dir);
            first.AddWord("元", "元の本文");
            string path = first.WordsPath;
            string before = File.ReadAllText(path, Encoding.UTF8);
            Store s;
            using (new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None))
            {
                s = Reload(dir);   // 開けない(数百 ms 待って諦める)
            }
            True(s.Warnings.Any(w => w.Contains("my-words.json")), "警告が出る");
            Eq(0, s.Words.Items.Count, "読めていない");
            bool threw = false;
            try { s.AddWord("上書き", "だめ"); } catch (IOException) { threw = true; }
            True(threw, "追加は IOException");
            Eq(0, s.Words.Items.Count, "巻き戻す");
            Eq(before, File.ReadAllText(path, Encoding.UTF8), "ファイルは上書きされない");
            // 別の Store でロックせずに読んだ項目を持ち、保存だけ止まる場合の巻き戻し(編集)
            var ok = Reload(dir);
            var e = ok.Words.Items[0];
            var w2 = new Store(dir);
            using (new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None)) { w2.Load(); }
            var inject = new ColorEntry { Id = "word/zzz", Name = "n", Text = "t", Group = w2.Words, IsUser = true };
            w2.Words.Items.Add(inject);
            threw = false;
            try { w2.UpdateWord(inject, "変更", "変更本文"); } catch (IOException) { threw = true; }
            True(threw, "編集も IOException");
            Eq("n", inject.Name, "編集を巻き戻す");
            Eq("t", inject.Text, "本文も巻き戻す");
            threw = false;
            try { w2.Remove(inject); } catch (IOException) { threw = true; }
            True(threw && w2.Words.Items.Contains(inject), "削除も巻き戻す");
            Eq("元の本文", e.Text, "ほかの Store には影響しない");
        }
        finally { Cleanup(dir); }
    }

    static void ColorsMove()
    {
        string dir = TempDir();
        try
        {
            var s = Reload(dir);
            var a = s.Add("あ", "#111111");
            var b = s.Add("い", "#222222");
            var c = s.Add("う", "#333333");
            True(s.MoveTo(c, 0), "MoveTo");
            Eq(c.Id, Reload(dir).Mine.Items[0].Id, "マイカラーの MoveTo が残る");
            True(!s.MoveTo(c, 0), "動かない");
            True(s.Move(c, 1), "Move");
            True(!s.Move(a, 5), "範囲の外は動かない");
            Eq(c.Id, Reload(dir).Mine.Items[1].Id, "Move が残る");
            Eq(0, Reload(dir).Words.Items.Count, "マイワードのファイルには触れない");

            // ドラッグの落とし先を項目で渡す(検索で一部が隠れていても Store の番号で動く)。並びは あ, う, い
            var d = s.Add("え", "#444444");                    // あ, う, い, え
            True(s.MoveToEntry(a, c), "あ を う の位置へ");    // う, あ, い, え
            Eq("う,あ,い,え", string.Join(",", Reload(dir).Mine.Items.Select(x => x.Name)), "落とした先の項目の位置に入る");
            True(s.MoveToEntry(a, d), "あ を末尾の え の位置へ");
            Eq("う,い,え,あ", string.Join(",", Reload(dir).Mine.Items.Select(x => x.Name)), "後ろへ動かすと落とした先の後ろ");
            True(!s.MoveToEntry(a, a), "同じ項目なら動かない");
            s.Remove(d);
            s.Remove(b);
            var r = Reload(dir);
            Eq(2, r.Mine.Items.Count, "削除が残る");
            True(!File.Exists(s.WordsPath), "my-words.json は作らない");
        }
        finally { Cleanup(dir); }
    }

    static void Favorites()
    {
        string dir = TempDir();
        try
        {
            var s = Reload(dir);
            var w = s.AddWord("ことば", "本文");
            var c = s.Add("色", "#123456");
            True(!s.IsFavorite(w), "最初は違う");
            True(s.ToggleFavorite(w), "入る");
            True(s.ToggleFavorite(c), "入る");
            True(s.IsFavorite(w), "入っている");
            var r = Reload(dir);
            True(r.IsFavorite(r.Words.Items[0]) && r.IsFavorite(r.Mine.Items[0]), "再読み込みで残る");
            Eq(w.Id, r.Settings.Favorites[0], "足した順");
            True(!s.ToggleFavorite(w), "外す");
            Eq(1, Reload(dir).Settings.Favorites.Count, "外したのが残る");
            s.ToggleFavorite(w);
            s.NoteRecent(w, 2);
            s.Remove(w);
            r = Reload(dir);
            True(!r.Settings.Favorites.Contains(w.Id), "消したらお気に入りから外れる");
            True(r.Settings.Recent.All(x => x.Id != w.Id), "最近からも外れる");
            Eq(1, r.Settings.Favorites.Count, "色のお気に入りは残る");
            s.Remove(c);
            Eq(0, Reload(dir).Settings.Favorites.Count, "色を消してもお気に入りから外れる");

            // 保存できないときは巻き戻して投げる
            var xw = s.AddWord("x", "x");
            using (new FileStream(s.SettingsPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None))
            {
                bool threw = false;
                try { s.ToggleFavorite(xw); } catch (IOException) { threw = true; } catch (UnauthorizedAccessException) { threw = true; }
                True(threw, "保存できなければ投げる");
                True(!s.IsFavorite(xw), "巻き戻す");
            }

            // ResolveIds
            var all = new List<ColorEntry> { xw };
            var res = s.ResolveIds(new[] { "nothing", xw.Id, xw.Id }, all);
            Eq(2, res.Count, "知らない id は飛ばす");
        }
        finally { Cleanup(dir); }
    }

    static void Recent()
    {
        string dir = TempDir();
        try
        {
            var s = Reload(dir);
            var list = new List<ColorEntry>();
            for (int i = 0; i < 7; i++) list.Add(s.AddWord("w" + i, "t" + i));
            for (int i = 0; i < 7; i++) s.NoteRecent(list[i], i);
            Eq(5, s.Settings.Recent.Count, "最大5件");
            Eq(list[6].Id, s.Settings.Recent[0].Id, "新しい順");
            Eq(list[2].Id, s.Settings.Recent[4].Id, "古いものから落ちる");
            s.NoteRecent(list[4], 3);   // 途中のものを前へ・色の番号は新しい方
            Eq(list[4].Id, s.Settings.Recent[0].Id, "前へ移る");
            Eq(3, s.Settings.Recent[0].ColorIndex, "色の番号");
            Eq(5, s.Settings.Recent.Count, "重ならない");
            Eq(1, s.Settings.Recent.Count(x => x.Id == list[4].Id), "1件だけ");
            s.NoteRecent(list[0], 99);
            Eq(Settings.MaxColorIndex, s.Settings.Recent[0].ColorIndex, "番号は範囲に収める");
            var r = Reload(dir);
            Eq(5, r.Settings.Recent.Count, "残る");
            Eq(list[0].Id, r.Settings.Recent[0].Id, "順番が残る");
            Eq(list[4].Id, r.Settings.Recent[1].Id, "順番が残る");
            Eq(3, r.Settings.Recent[1].ColorIndex, "番号が残る");
        }
        finally { Cleanup(dir); }
    }

    static void Garbage()
    {
        var d = Json.Parse("{\"favorites\": \"abc\", \"recent\": 5}");
        var s = Settings.FromJson(d);
        Eq(0, s.Favorites.Count, "favorites が文字列");
        Eq(0, s.Recent.Count, "recent が数");
        s = Settings.FromJson(Json.Parse("{\"favorites\": {\"a\": 1}, \"recent\": {\"id\": \"x\"}}"));
        Eq(0, s.Favorites.Count, "オブジェクト");
        Eq(0, s.Recent.Count, "オブジェクト");
        s = Settings.FromJson(Json.Parse("{}"));
        Eq(0, s.Favorites.Count + s.Recent.Count, "キー無し");
        s = Settings.FromJson(Json.Parse("{\"favorites\": [\"a\", 1, null, \"\", \"a\", \"b\", [\"z\"], true], "
            + "\"recent\": [\"str\", {\"id\": 3}, {\"color\": 2}, {\"id\": \"p\", \"color\": -4}, {\"id\": \"q\", \"color\": 999}, "
            + "{\"id\": \"p\", \"color\": 1}, {\"id\": \"r\", \"color\": \"x\"}]}"));
        Eq("a,b", string.Join(",", s.Favorites), "favorites の不正・重なりを落とす");
        Eq("p,q,r", string.Join(",", s.Recent.Select(x => x.Id)), "recent の不正・重なりを落とす");
        Eq(0, s.Recent[0].ColorIndex, "負は 0");
        Eq(Settings.MaxColorIndex, s.Recent[1].ColorIndex, "大きすぎは上限");
        Eq(0, s.Recent[2].ColorIndex, "型違いは 0");
        var many = new List<object>();
        for (int i = 0; i < 400; i++) many.Add("id" + i);
        var big = new Dictionary<string, object> { { "favorites", many } };
        Eq(Settings.MaxFavorites, Settings.FromJson(big).Favorites.Count, "300 件まで");
        var rec = new List<object>();
        for (int i = 0; i < 9; i++) rec.Add(new Dictionary<string, object> { { "id", "r" + i }, { "color", 0 } });
        Eq(Settings.MaxRecent, Settings.FromJson(new Dictionary<string, object> { { "recent", rec } }).Recent.Count, "5 件まで");
        // JSON 往復
        var t = new Settings();
        t.Favorites.Add("my/abc");
        t.Recent.Add(new RecentItem { Id = "my/abc", ColorIndex = 2 });
        var back = Settings.FromJson(Json.Parse(Json.Pretty(t.ToJson())));
        Eq("my/abc", back.Favorites[0], "往復");
        Eq(2, back.Recent[0].ColorIndex, "往復");
    }

    static void Branch()
    {
        string dir = TempDir();
        try
        {
            foreach (string b in new[] { "WORD", "FAV", "RECENT", "MY" })
            {
                string path = Path.Combine(dir, "m-" + b + ".json");
                File.WriteAllText(path, "{\"groups\": [{\"id\": \"g\", \"branch\": \"" + b + "\", \"name\": \"x\", \"members\": [{\"name\": \"a\", \"hex\": \"#FF0000\"}]}]}", new UTF8Encoding(false));
                bool threw = false;
                try { Palette.Load(path); } catch (FormatException) { threw = true; }
                True(threw, b + " は members.json に書けない");
            }
            True(Array.IndexOf(Branches.Filters, "WORD") > 0, "札に WORD");
            Eq("マイワード", Branches.Short("WORD"), "Short WORD");
            Eq("お気に入り", Branches.Short("FAV"), "Short FAV");
            Eq("最近使ったもの", Branches.Short("RECENT"), "Short RECENT");
            True(Branches.IsSpecial("MY") && Branches.IsSpecial("WORD") && Branches.IsSpecial("FAV") && Branches.IsSpecial("RECENT"), "IsSpecial");
            True(!Branches.IsSpecial("JP") && !Branches.IsSpecial("GRAD") && !Branches.IsSpecial("ALL"), "IsSpecial でない");
            True(Branches.IsKnown("JP") && !Branches.IsKnown("ALL"), "IsKnown");
            foreach (string b in new[] { "MY", "WORD", "FAV", "RECENT", "GRAD" })
                Eq("名前", new ColorGroup { Branch = b, Name = "名前" }.Label, "Label は名前だけ: " + b);
            True(new ColorGroup { Branch = "JP", Name = "名前" }.Label.StartsWith("JP"), "メンバーの Label は branch 付き");
        }
        finally { Cleanup(dir); }
    }

    static void SearchAndColors()
    {
        string dir = TempDir();
        try
        {
            var s = Reload(dir);
            var w = s.AddWord("あいさつ", "みなさん こんにちは! ホロライブです");
            True(SearchText.Matches(w, "ホロライブ"), "本文で当たる");
            True(SearchText.Matches(w, "こんにちは"), "本文で当たる");
            True(SearchText.Matches(w, "あいさつ"), "名前でも当たる");
            True(!SearchText.Matches(w, "さようなら"), "外れる");
            Eq(0, w.AllColors.Count, "AllColors は空");
            s.UpdateWord(w, "あいさつ", "さようなら");
            True(SearchText.Matches(Reload(dir).Words.Items[0], "さようなら"), "編集後の本文で当たる");
            True(!SearchText.Matches(w, "ホロライブ"), "古い本文では外れる");
            var c = s.Add("色", "#ABCDEF");
            Eq(1, c.AllColors.Count, "色は1色");
            True(!c.IsWord, "色は IsWord でない");
            var bare = new ColorEntry { Text = "x" };
            bare.SetColors(new List<ColorOption>());   // 例外にならない
            Eq(0, bare.AllColors.Count, "空の色");
        }
        finally { Cleanup(dir); }
    }
}
