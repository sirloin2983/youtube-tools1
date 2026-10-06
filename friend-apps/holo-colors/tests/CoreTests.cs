// ホロカラーのテスト(build.bat が HoloColors.exe を参照して作り、流す)。失敗が1つでもあれば終了コード 1。
//   build\HoloColorsTests.exe      (build\members.json も確かめる)
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;
using HoloColors;

static class CoreTests
{
    static int failures, passed;

    [STAThread]
    static int Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        Run("hex: 書き方の違いをそろえる", HexNormalize);
        Run("hex: 文字の色(黒か白か)", Contrast);
        Run("検索: かな・全角・空白をそろえる", Fold);
        Run("検索: 名前・ローマ字・カラーコード・グループで当たる", Matches);
        Run("キー: 組み合わせの判定と表示", HotkeyRules);
        Run("JSON: 字下げして読み直せる", JsonPretty);
        Run("作業データ: 置き場所", DataDir);
        Run("作業データ: マイカラーの追加・編集・並べ替え・削除が残る", StoreColors);
        Run("作業データ: 設定が残る・おかしな値は既定に戻す", StoreSettings);
        Run("作業データ: 壊れたファイルは取っておいて初めから", StoreCorrupt);
        Run("作業データ: 開けなかったファイルは上書きしない・保存の失敗は元に戻す", StoreLocked);
        Run("作業データ: メンバーの色を直す・元に戻す・知らない id は残す(member-colors.json)", StoreMemberColors);
        Run("作業データ: 直した色のファイルが壊れている・開けない・保存の失敗", StoreMemberColorsBroken);
        Run("members.json: 同梱のデータが正しい形", BundledMembers);
        Run("members.json: おかしなデータは読まない", BadMembers);
        Run("members.json: 1人に複数の色(colors)・古い形・壊れた色は飛ばす・2つ目の色で検索", MultiColors);
        Run("自動起動: 登録・外す・別の場所を指す", AutostartRegistry);
        Run("一覧: 札の並び・クリックの判定・キーでの移動", PaletteLayout);
        Run("一覧: スクロールしても札と文字が一緒に動く", PaletteScrollDrawing);
        Run("一覧: 札の色の帯(等分・折り返し・クリックの判定・★・ワード・ドラッグで並べ替え)", PaletteBands);
        Run("起動: 作業データの場所ごとに1つ", InstanceKey);
        WordsTests.RunAll(Run);
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
        string d = Path.Combine(Path.GetTempPath(), "holo-colors-test-" + Guid.NewGuid().ToString("N").Substring(0, 8));
        Directory.CreateDirectory(d);
        return d;
    }

    // ---- 色 ----
    static void HexNormalize()
    {
        string h;
        True(HexColor.TryNormalize("#ff6699", out h) && h == "#FF6699", "小文字");
        True(HexColor.TryNormalize("FF6699", out h) && h == "#FF6699", "# なし");
        True(HexColor.TryNormalize("  #f69 ", out h) && h == "#FF6699", "3桁・前後の空白");
        True(HexColor.TryNormalize("＃ＦＦ６６９９", out h) && h == "#FF6699", "全角");
        True(HexColor.TryNormalize("# 00a0e9", out h) && h == "#00A0E9", "# のあとの空白");
        foreach (string bad in new[] { null, "", "#", "#12345", "#1234567", "#GG0000", "red", "rgb(1,2,3)", "#FF 66 99" })
            True(!HexColor.TryNormalize(bad, out h), "読めないはず: " + bad);
        Eq("FF6699", HexColor.Format("#ff6699", false), "# なしでコピー");
        Eq("#FF6699", HexColor.Format("ff6699", true), "# ありでコピー");
        Eq("#0A0B0C", HexColor.FromColor(Color.FromArgb(10, 11, 12)), "色から");
        Eq(Color.FromArgb(255, 102, 153).ToArgb(), HexColor.ToColor("#FF6699").ToArgb(), "色へ");
    }

    static void Contrast()
    {
        True(HexColor.PrefersDarkText(Color.White), "白には黒い文字");
        True(HexColor.PrefersDarkText(HexColor.ToColor("#FFD700")), "黄色には黒い文字");
        True(!HexColor.PrefersDarkText(Color.Black), "黒には白い文字");
        True(!HexColor.PrefersDarkText(HexColor.ToColor("#1E3A8A")), "濃い青には白い文字");
        True(!HexColor.PrefersDarkText(HexColor.ToColor("#266AFF")), "鮮やかな青には白い文字");
        True(HexColor.PrefersDarkText(HexColor.ToColor("#49E0F4")), "明るい水色には黒い文字");
    }

    // ---- 検索 ----
    static void Fold()
    {
        Eq("ぺこら", SearchText.Fold("ペコラ"), "カタカナ");
        Eq("usadapekora", SearchText.Fold("Usada Pekora"), "空白と大文字");
        Eq("abc123", SearchText.Fold("ＡＢＣ１２３"), "全角");
        Eq("猫又おかゆ", SearchText.Fold("猫又おかゆ"), "漢字はそのまま");
        Eq("がうるぐら", SearchText.Fold("がうる・ぐら"), "中黒");
    }

    static ColorEntry Entry(string name, string sub, string hex, string group)
    {
        var g = new ColorGroup { Id = "g", Branch = "JP", Name = group };
        var e = new ColorEntry { Id = "x", Name = name, Sub = sub, Hex = hex, Note = "", Group = g };
        e.SearchKey = SearchText.SearchKey(e);
        return e;
    }

    static void Matches()
    {
        var e = Entry("兎田ぺこら", "Usada Pekora", "#6FB7FF", "3期生");
        foreach (string q in new[] { "", "  ", "ぺこ", "ペコ", "ﾍﾟｺ", "pekora", "PEKO", "usada peko", "兎田", "#6fb7", "6FB7FF", "3期", "jp" })
            True(SearchText.Matches(e, q), "当たるはず: [" + q + "]");
        foreach (string q in new[] { "みこ", "miko", "#FF0000", "pekora miko", "4期" })
            True(!SearchText.Matches(e, q), "当たらないはず: [" + q + "]");
    }

    // ---- キー ----
    static void HotkeyRules()
    {
        True(Hotkey.IsValid(Hotkey.MOD_CONTROL | Hotkey.MOD_ALT, (int)Keys.H), "Ctrl+Alt+H");
        True(Hotkey.IsValid(Hotkey.MOD_WIN | Hotkey.MOD_SHIFT, (int)Keys.C), "Win+Shift+C");
        True(!Hotkey.IsValid(0, (int)Keys.F9), "F9 単独は不可(ほかのアプリの F キーを奪う)");
        True(Hotkey.IsValid(Hotkey.MOD_CONTROL | Hotkey.MOD_ALT, (int)Keys.F9), "Ctrl+Alt+F9");
        True(!Hotkey.IsValid(Hotkey.MOD_ALT, (int)Keys.F4), "Alt+F4 は不可");
        True(!Hotkey.IsValid(Hotkey.MOD_ALT, (int)Keys.Tab), "Alt+Tab は不可");
        True(!Hotkey.IsValid(Hotkey.MOD_CONTROL, (int)Keys.V), "Ctrl+V は不可");
        True(!Hotkey.IsValid(Hotkey.MOD_CONTROL | Hotkey.MOD_SHIFT, (int)Keys.Escape), "Ctrl+Shift+Esc は不可");
        True(Hotkey.IsValid(Hotkey.MOD_CONTROL | Hotkey.MOD_SHIFT, (int)Keys.V), "Ctrl+Shift+V は可");
        True(Hotkey.Problem(Hotkey.MOD_CONTROL, (int)Keys.C).Contains("Ctrl + C"), "断る理由に組み合わせを出す");
        True(!Hotkey.IsValid(Hotkey.MOD_SHIFT, (int)Keys.H), "Shift+H は打てなくなるので不可");
        True(!Hotkey.IsValid(0, (int)Keys.H), "H 単独は不可");
        True(!Hotkey.IsValid(Hotkey.MOD_CONTROL, (int)Keys.ControlKey), "修飾キーだけは不可");
        True(!Hotkey.IsValid(Hotkey.MOD_CONTROL | 0x100, (int)Keys.H), "知らない修飾は不可");
        Eq("Ctrl + Alt + H", Hotkey.Format(Hotkey.MOD_CONTROL | Hotkey.MOD_ALT, (int)Keys.H), "表示");
        Eq("Ctrl + Shift + Win + F12", Hotkey.Format(Hotkey.MOD_CONTROL | Hotkey.MOD_SHIFT | Hotkey.MOD_WIN, (int)Keys.F12), "表示の順番");
        Eq("Alt + 1", Hotkey.Format(Hotkey.MOD_ALT, (int)Keys.D1), "数字");
        // Keys の ToString() に任せている名前(PageDown は別名の "Next" になるので、決めた名前で出す)
        Eq("PageDown|PageUp|Enter|Space|Delete|Home", string.Join("|", new[] { Keys.PageDown, Keys.PageUp, Keys.Return, Keys.Space, Keys.Delete, Keys.Home }.Select(k => Hotkey.KeyName((int)k))), "名前の付いたキー");
    }

    static void JsonPretty()
    {
        var o = new Dictionary<string, object> { { "a", 1 }, { "b", new object[] { "x\"y", "日本語", true } }, { "c", new Dictionary<string, object>() }, { "d", new object[0] } };
        string s = Json.Pretty(o);
        True(s.Contains("\n  \"a\": 1"), "字下げ: " + s);
        var back = Json.Parse(s);
        Eq(1, Json.Int(back, "a", 0), "数");
        var list = (object[])back["b"];
        Eq("x\"y", (string)list[0], "引用符の入った文字");
        Eq("日本語", (string)list[1], "日本語");
    }

    // ---- 作業データ ----
    static void DataDir()
    {
        Eq(Path.Combine(@"C:\app", "data"), Files.DataDir(@"C:\app", "InPlace", @"C:\L"), "inplace");
        Eq(Path.Combine(@"C:\x", "holo-colors"), Files.DataDir(@"C:\app", @"C:\x", @"C:\L"), "YTT_DATA_DIR");
        Eq(Path.Combine(@"C:\L", "youtube-tools", "holo-colors"), Files.DataDir(@"C:\app", null, @"C:\L"), "既定");
        Eq(Path.Combine(@"C:\L", "youtube-tools", "holo-colors"), Files.DataDir(@"C:\app", "  ", @"C:\L"), "空は既定");
    }

    static void StoreColors()
    {
        string dir = TempDir();
        try
        {
            var s = new Store(dir);
            s.Load();
            Eq(0, s.Mine.Items.Count, "初めは空");
            var a = s.Add("  自分の赤 ", "#f00");
            var b = s.Add("青", "0000ff");
            s.Add("緑", "#00FF00");
            Eq("自分の赤", a.Name, "名前の前後の空白を除く");
            Eq("#FF0000", a.Hex, "カラーコードをそろえる");
            True(a.IsUser && a.Group == s.Mine, "マイカラーの印");
            True(SearchText.Matches(a, "自分"), "足した色も検索できる");
            s.Update(b, "濃い青", "#00008B");
            True(s.Move(b, -1), "前へ");
            True(!s.Move(b, -1), "先頭より前へは動かない");

            var s2 = new Store(dir);
            s2.Load();
            Eq("濃い青,自分の赤,緑", string.Join(",", s2.Mine.Items.Select(x => x.Name)), "読み直しても同じ順番");
            Eq("#00008B", s2.Mine.Items[0].Hex, "編集が残る");
            s2.Remove(s2.Mine.Items[1]);
            var s3 = new Store(dir);
            s3.Load();
            Eq("濃い青,緑", string.Join(",", s3.Mine.Items.Select(x => x.Name)), "削除が残る");

            string hex;
            True(Store.Validate("", "#FFFFFF", out hex) != null, "名前が空は不可");
            True(Store.Validate(new string('あ', Store.MaxName + 1), "#FFFFFF", out hex) != null, "長すぎる名前は不可");
            True(Store.Validate("白", "#FFFFF", out hex) != null, "5桁は不可");
            try { s3.Add("白", "white"); throw new Exception("読めない色が足せてしまった"); }
            catch (ArgumentException) { }
            Eq(2, s3.Mine.Items.Count, "失敗した追加は残らない");
            True(Directory.GetFiles(dir, "*.part").Length == 0, "一時ファイルが残っていない");
        }
        finally { Directory.Delete(dir, true); }
    }

    static void StoreSettings()
    {
        string dir = TempDir();
        try
        {
            var s = new Store(dir);
            s.Load();
            True(s.Settings.CloseAfterCopy && s.Settings.IncludeHash, "既定: コピーしたら閉じる・# あり");
            Eq(Hotkey.DefaultMods, s.Settings.HotkeyMods, "既定のキー");
            s.Settings.CloseAfterCopy = false;
            s.Settings.IncludeHash = false;
            s.Settings.HotkeyMods = Hotkey.MOD_WIN | Hotkey.MOD_SHIFT;
            s.Settings.HotkeyKey = (int)Keys.C;
            s.Settings.Filter = "EN";
            s.Settings.WindowWidth = 700;
            s.SaveSettings();
            var s2 = new Store(dir);
            s2.Load();
            True(!s2.Settings.CloseAfterCopy && !s2.Settings.IncludeHash, "チェックが残る");
            Eq(Hotkey.MOD_WIN | Hotkey.MOD_SHIFT, s2.Settings.HotkeyMods, "キーが残る");
            Eq((int)Keys.C, s2.Settings.HotkeyKey, "キーが残る");
            Eq("EN", s2.Settings.Filter, "絞り込みが残る");
            Eq(700, s2.Settings.WindowWidth, "大きさが残る");

            File.WriteAllText(s.SettingsPath, "{\"hotkeyModifiers\": 4, \"hotkeyKey\": 72, \"filter\": \"XX\", \"windowWidth\": -5, \"closeAfterCopy\": \"yes\"}");
            var s3 = new Store(dir);
            s3.Load();
            Eq(Hotkey.DefaultMods, s3.Settings.HotkeyMods, "使えないキー(Shift+H)は既定へ");
            Eq("ALL", s3.Settings.Filter, "知らない絞り込みは「すべて」");
            Eq(0, s3.Settings.WindowWidth, "負の大きさは既定");
            True(s3.Settings.CloseAfterCopy, "型の違う値は既定");
        }
        finally { Directory.Delete(dir, true); }
    }

    static void StoreCorrupt()
    {
        string dir = TempDir();
        try
        {
            var s = new Store(dir);
            s.Load();
            s.Add("赤", "#FF0000");
            File.WriteAllText(s.ColorsPath, "{ \"colors\": [ {\"name\": \"途中で");
            var s2 = new Store(dir);
            s2.Load();
            Eq(0, s2.Mine.Items.Count, "壊れていれば空で始める");
            Eq(1, s2.Warnings.Count, "知らせる");
            Eq(1, Directory.GetFiles(dir, "my-colors.json.corrupt-*").Length, "元のファイルは取っておく");
            // 名前や色の欠けた項目だけを飛ばす
            File.WriteAllText(s.ColorsPath, "{\"colors\": [{\"name\": \"\", \"hex\": \"#FFFFFF\"}, {\"name\": \"良い\", \"hex\": \"#abc\"}, {\"name\": \"悪い\", \"hex\": \"xyz\"}, 5]}");
            var s3 = new Store(dir);
            s3.Load();
            Eq("良い", string.Join(",", s3.Mine.Items.Select(x => x.Name)), "読める項目だけ");
            Eq("#AABBCC", s3.Mine.Items[0].Hex, "3桁を6桁に");
        }
        finally { Directory.Delete(dir, true); }
    }

    static void StoreLocked()
    {
        string dir = TempDir();
        try
        {
            var s = new Store(dir);
            s.Load();
            s.Add("赤", "#FF0000");
            s.Settings.HotkeyKey = (int)Keys.J;
            s.SaveSettings();
            string before = File.ReadAllText(s.ColorsPath);

            // ほかのソフトがつかんでいる間に起動した → 初めの状態で始めても、元のファイルは上書きしない
            var s2 = new Store(dir);
            using (new FileStream(s.ColorsPath, FileMode.Open, FileAccess.Read, FileShare.None))
                s2.Load();
            Eq(0, s2.Mine.Items.Count, "読めなかった");
            True(s2.Warnings.Count == 1 && s2.Warnings[0].Contains("保存を止め"), "知らせる");
            try { s2.Add("青", "#0000FF"); throw new Exception("保存できてしまった"); }
            catch (IOException) { }
            Eq(0, s2.Mine.Items.Count, "保存できなかった追加は残らない");
            Eq(before, File.ReadAllText(s.ColorsPath), "元のマイカラーはそのまま");
            s2.SaveSettings();   // 設定は読めているので保存できる
            Eq((int)Keys.J, new Func<int>(() => { var x = new Store(dir); x.Load(); return x.Settings.HotkeyKey; })(), "設定はそのまま");

            // 保存の途中で失敗したら、削除も元に戻す
            var s3 = new Store(dir);
            s3.Load();
            var red = s3.Mine.Items[0];
            using (new FileStream(s.ColorsPath, FileMode.Open, FileAccess.Read, FileShare.None))
            {
                try { s3.Remove(red); throw new Exception("保存できてしまった"); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
            Eq(1, s3.Mine.Items.Count, "保存できなかった削除は元に戻す");
        }
        finally { Directory.Delete(dir, true); }
    }

    // メンバー2人の members.json(1人は2色)を書いて読む
    static Palette SamplePalette(string dir)
    {
        string f = Path.Combine(dir, "members.json");
        File.WriteAllText(f, "{\"version\": 2, \"groups\": [{\"id\": \"g\", \"branch\": \"JP\", \"name\": \"x\", \"members\": ["
            + "{\"id\": \"miko\", \"name\": \"さくらみこ\", \"en\": \"Sakura Miko\", \"hex\": \"#FF8FDF\", \"colors\": [{\"hex\": \"#FF8FDF\", \"label\": \"ホロジュール\"}, {\"hex\": \"#FE4B74\", \"label\": \"公式サイト\"}]},"
            + "{\"id\": \"pekora\", \"name\": \"兎田ぺこら\", \"en\": \"Usada Pekora\", \"hex\": \"#7EC2FE\"}"
            + "]}]}");
        return Palette.Load(f);
    }

    static void StoreMemberColors()
    {
        string dir = TempDir(), apps = TempDir();
        try
        {
            var s = new Store(dir);
            s.Load();
            var p = SamplePalette(apps);
            s.ApplyMemberColors(p.Members);
            var miko = p.Members.First(x => x.MemberId == "miko");
            True(!miko.Customized && miko.Hex == "#FF8FDF", "直していなければ members.json の色");

            // 主な色を入れ替えて、新しい色を足す
            s.SetMemberColors(miko, new[] { new ColorOption("#fe4b74", " 公式サイト "), new ColorOption("#FF8FDF", "ホロジュール"), new ColorOption("#123456", "自分用") });
            True(miko.Customized, "直した印");
            Eq("#FE4B74", miko.Hex, "主な色が変わる");
            Eq("#FE4B74,#FF8FDF,#123456", string.Join(",", miko.Colors.Select(c => c.Hex)), "直した色の並び");
            Eq("公式サイト", miko.Colors[0].Label, "ラベルの前後の空白を除く");
            True(SearchText.Matches(miko, "#1234") && SearchText.Matches(miko, "自分用"), "直した色でも検索できる");

            // 起動し直しても残る・members.json を読み直しても残る
            var s2 = new Store(dir);
            s2.Load();
            var p2 = SamplePalette(apps);
            s2.ApplyMemberColors(p2.Members);
            var miko2 = p2.Members.First(x => x.MemberId == "miko");
            True(miko2.Customized && miko2.Hex == "#FE4B74", "起動し直しても直した色");
            True(!p2.Members.First(x => x.MemberId == "pekora").Customized, "直していない人はそのまま");

            // members.json に無い id は使わないが、消さずに残す
            string text = File.ReadAllText(s2.MemberColorsPath).Replace("\"members\": {", "\"members\": {\"gone-member\": {\"colors\": [{\"hex\": \"#000001\", \"label\": \"\"}]}, ");
            File.WriteAllText(s2.MemberColorsPath, text);
            var s3 = new Store(dir);
            s3.Load();
            Eq(0, s3.Warnings.Count, "書き足したファイルが読める: " + string.Join(" / ", s3.Warnings));
            True(s3.MemberColors.ContainsKey("gone-member"), "知らない id も読む");
            var p3 = SamplePalette(apps);
            s3.ApplyMemberColors(p3.Members);
            var miko3 = p3.Members.First(x => x.MemberId == "miko");
            s3.ResetMemberColors(miko3);
            True(!miko3.Customized && miko3.Hex == "#FF8FDF" && miko3.Colors.Count == 2, "元に戻す = members.json の色");
            var s4 = new Store(dir);
            s4.Load();
            True(!s4.MemberColors.ContainsKey("miko"), "元に戻した人はファイルから消える");
            True(s4.MemberColors.ContainsKey("gone-member"), "知らない id は保存しても消えない");

            // members.json と同じ色にしたら「元に戻す」と同じ
            s4.ApplyMemberColors(p3.Members);
            s4.SetMemberColors(miko3, new[] { new ColorOption("#FF8FDF", "ホロジュール"), new ColorOption("#FE4B74", "公式サイト") });
            True(!miko3.Customized && !s4.MemberColors.ContainsKey("miko"), "元と同じ色は直していない扱い");

            // 最低1色・形の違う色は断る(直した色はそのまま)
            s4.SetMemberColors(miko3, new[] { new ColorOption("#010101", "") });
            foreach (var bad in new[] { new ColorOption[0], new[] { new ColorOption("red", "") } })
            {
                try { s4.SetMemberColors(miko3, bad); throw new Exception("おかしな色が保存できてしまった"); }
                catch (ArgumentException) { }
            }
            Eq("#010101", miko3.Hex, "断ったときは直した色のまま");
            var pekora = p3.Members.First(x => x.MemberId == "pekora");
            var mine = s4.Add("マイ", "#FFFFFF");
            try { s4.SetMemberColors(mine, new[] { new ColorOption("#000000", "") }); throw new Exception("マイカラーを直せてしまった"); }
            catch (ArgumentException) { }
            s4.SetMemberColors(pekora, new[] { new ColorOption("#7EC2FE", ""), new ColorOption("#FFFFFF", "白") });
            True(pekora.Customized && pekora.Colors.Count == 2, "1色の人に2色目を足せる");
            True(Directory.GetFiles(dir, "*.part").Length == 0, "一時ファイルが残っていない");
        }
        finally { Directory.Delete(dir, true); Directory.Delete(apps, true); }
    }

    static void StoreMemberColorsBroken()
    {
        string dir = TempDir(), apps = TempDir();
        try
        {
            var s = new Store(dir);
            s.Load();
            var p = SamplePalette(apps);
            s.ApplyMemberColors(p.Members);
            var miko = p.Members.First(x => x.MemberId == "miko");
            s.SetMemberColors(miko, new[] { new ColorOption("#111111", "") });
            string before = File.ReadAllText(s.MemberColorsPath);

            // 壊れたファイル: 取っておいて、直していない状態で始める(落ちない)
            File.WriteAllText(s.MemberColorsPath, "{\"members\": {\"miko\": ");
            var s2 = new Store(dir);
            s2.Load();
            Eq(0, s2.MemberColors.Count, "壊れていれば直した色なし");
            True(s2.Warnings.Count == 1 && s2.Warnings[0].Contains("member-colors.json"), "知らせる");
            Eq(1, Directory.GetFiles(dir, "member-colors.json.corrupt-*").Length, "元のファイルは取っておく");

            // 形の違う項目だけ飛ばす
            File.WriteAllText(s.MemberColorsPath, "{\"members\": {\"miko\": {\"colors\": [{\"hex\": \"xyz\"}, {\"hex\": \"#abc\"}]}, \"pekora\": {\"colors\": []}, \"x\": 5, \"y\": {\"colors\": \"#FFFFFF\"}}}");
            var s3 = new Store(dir);
            s3.Load();
            Eq("miko", string.Join(",", s3.MemberColors.Keys), "読める項目だけ");
            Eq("#AABBCC", s3.MemberColors["miko"][0].Hex, "読める色だけ");

            // 開けなかったときは上書きしない
            File.WriteAllText(s.MemberColorsPath, before);
            var s4 = new Store(dir);
            using (new FileStream(s.MemberColorsPath, FileMode.Open, FileAccess.Read, FileShare.None))
                s4.Load();
            True(s4.Warnings.Any(w => w.Contains("保存を止め")), "開けないと知らせる");
            var p4 = SamplePalette(apps);
            s4.ApplyMemberColors(p4.Members);
            var miko4 = p4.Members.First(x => x.MemberId == "miko");
            try { s4.SetMemberColors(miko4, new[] { new ColorOption("#222222", "") }); throw new Exception("保存できてしまった"); }
            catch (IOException) { }
            True(!miko4.Customized && miko4.Hex == "#FF8FDF", "保存できなかった色は反映しない");
            Eq(before, File.ReadAllText(s.MemberColorsPath), "元のファイルはそのまま");

            // 保存の途中で失敗したら、元に戻す
            var s5 = new Store(dir);
            s5.Load();
            var p5 = SamplePalette(apps);
            s5.ApplyMemberColors(p5.Members);
            var miko5 = p5.Members.First(x => x.MemberId == "miko");
            using (new FileStream(s.MemberColorsPath, FileMode.Open, FileAccess.Read, FileShare.None))
            {
                try { s5.SetMemberColors(miko5, new[] { new ColorOption("#333333", "") }); throw new Exception("保存できてしまった"); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
                try { s5.ResetMemberColors(miko5); throw new Exception("保存できてしまった"); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
            True(miko5.Customized && miko5.Hex == "#111111" && s5.MemberColors["miko"][0].Hex == "#111111", "保存できなかったときは前の直した色のまま");
        }
        finally { Directory.Delete(dir, true); Directory.Delete(apps, true); }
    }

    // ---- 同梱のデータ ----
    static void BundledMembers()
    {
        string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "members.json");
        True(File.Exists(path), "members.json が無い: " + path);
        var p = Palette.Load(path);
        True(p.Groups.Count > 0, "グループが無い");
        True(p.Updated.Length == 10, "updated(YYYY-MM-DD)が無い");
        var names = new HashSet<string>();
        foreach (var g in p.Groups)
        {
            True(g.Items.Count > 0, "空のグループ: " + g.Name);
            True(!string.IsNullOrWhiteSpace(g.Name), "グループの名前が空");
            foreach (var e in g.Items)
            {
                True(!string.IsNullOrWhiteSpace(e.Sub), "ローマ字・英語名が無い: " + e.Name);
                True(names.Add(g.Branch + "/" + e.Name), "同じ人が同じ所に2回: " + e.Name);
                True(e.Hex.Length == 7 && e.Hex[0] == '#', "カラーコード: " + e.Name);
            }
        }
        foreach (string b in new[] { "JP", "DEV_IS", "EN", "ID", "GRAD" })
            True(p.Groups.Any(g => g.Branch == b), "このグループが無い: " + b);

        // version 2 の形: 全員に colors があり、先頭が hex(主な色)と同じ・メンバーの id は全体で一意(直した色のキー)・ラベルは 12 文字まで
        var root = Json.Parse(File.ReadAllText(path, Encoding.UTF8));
        Eq(2, Json.Int(root, "version", 0), "version");
        var memberIds = new HashSet<string>();
        foreach (var g in Json.List(root, "groups"))
            foreach (var m in Json.List(g, "members"))
            {
                string id = Json.Str(m, "id"), name = Json.Str(m, "name");
                True(!string.IsNullOrEmpty(id) && memberIds.Add(id), "メンバーの id が無いか重なっている: " + name + " / " + id);
                var colors = Json.List(m, "colors").ToList();
                True(colors.Count >= 1, "colors が無い: " + name);
                string h0, hx;
                True(HexColor.TryNormalize(Json.Str(colors[0], "hex"), out h0) && HexColor.TryNormalize(Json.Str(m, "hex"), out hx) && h0 == hx,
                    "colors の先頭と hex が違う: " + name);
                foreach (var c in colors)
                {
                    string h;
                    True(HexColor.TryNormalize(Json.Str(c, "hex"), out h), "色のカラーコード: " + name);
                    True((Json.Str(c, "label") ?? "").Length <= ColorOption.MaxLabel, "ラベルが長い: " + name + " / " + Json.Str(c, "label"));
                    string conf = Json.Str(c, "confidence");
                    True(conf == "high" || conf == "medium" || conf == "low", "確かさ(confidence)が無い: " + name + " " + h);
                }
            }
    }

    static void BadMembers()
    {
        string dir = TempDir();
        try
        {
            string f = Path.Combine(dir, "m.json");
            var cases = new[]
            {
                "{\"groups\": [{\"id\": \"a\", \"branch\": \"JP\", \"name\": \"x\", \"members\": [{\"name\": \"A\", \"hex\": \"#12345\"}]}]}",
                "{\"groups\": [{\"id\": \"a\", \"branch\": \"XX\", \"name\": \"x\", \"members\": []}]}",
                "{\"groups\": [{\"id\": \"a\", \"branch\": \"MY\", \"name\": \"x\", \"members\": []}]}",
                "{\"groups\": [{\"id\": \"a\", \"branch\": \"JP\", \"name\": \"x\", \"members\": [{\"id\": \"p\", \"name\": \"A\", \"hex\": \"#111111\"}, {\"id\": \"p\", \"name\": \"B\", \"hex\": \"#222222\"}]}]}",
                "[1, 2]",
                "{",
            };
            foreach (string c in cases)
            {
                File.WriteAllText(f, c);
                try
                {
                    Palette.Load(f);
                    throw new Exception("読めてしまった: " + c);
                }
                catch (FormatException) { }
                catch (ArgumentException) { }
            }
        }
        finally { Directory.Delete(dir, true); }
    }

    static void MultiColors()
    {
        string dir = TempDir();
        try
        {
            string f = Path.Combine(dir, "m.json");
            File.WriteAllText(f, "{\"groups\": [{\"id\": \"a\", \"branch\": \"JP\", \"name\": \"x\", \"members\": ["
                + "{\"id\": \"p\", \"name\": \"古い形\", \"en\": \"Old\", \"hex\": \"#111111\"},"
                + "{\"id\": \"q\", \"name\": \"二色\", \"en\": \"Two\", \"hex\": \"#ff0000\", \"colors\": [{\"hex\": \"#FF0000\", \"label\": \"ホロジュール\"}, {\"hex\": \"#00AAFF\", \"label\": \"ペンライト: 水色\"}, {\"hex\": \"xyz\"}, 5, {\"hex\": \"#00aaff\"}]},"
                + "{\"id\": \"r\", \"name\": \"順番違い\", \"en\": \"Order\", \"hex\": \"#222222\", \"colors\": [{\"hex\": \"#333333\", \"label\": \"とても長いラベルの名前ですよね\"}, {\"hex\": \"#222222\", \"label\": \"主\"}]},"
                + "{\"id\": \"s\", \"name\": \"主が無い\", \"en\": \"NoMain\", \"hex\": \"#444444\", \"colors\": [{\"hex\": \"#555555\"}]}"
                + "]}]}");
            var p = Palette.Load(f);
            var items = p.Groups[0].Items;
            Eq(4, items.Count, "4人");
            Eq(1, items[0].Colors.Count, "colors が無い古い形は hex の1色");
            Eq("#111111", items[0].Colors[0].Hex, "古い形の色");
            Eq("p", items[0].MemberId, "メンバーの id");
            Eq("a/p", items[0].Id, "札の id はグループ付き(今までどおり)");
            var two = items[1];
            Eq("#FF0000,#00AAFF", string.Join(",", two.Colors.Select(c => c.Hex)), "壊れた色と同じ色の重なりは飛ばす");
            Eq("ペンライト: 水色", two.Colors[1].Label, "ラベル");
            Eq("#FF0000", two.Hex, "主な色は hex");
            True(SearchText.Matches(two, "#00aa"), "2つ目の色のカラーコードで当たる");
            True(SearchText.Matches(two, "ペンライト"), "ラベルで当たる");
            True(!SearchText.Matches(items[0], "#00aa"), "ほかの人には当たらない");
            Eq("#222222,#333333", string.Join(",", items[2].Colors.Select(c => c.Hex)), "hex と同じ色を先頭へ");
            Eq(ColorOption.MaxLabel, items[2].Colors[1].Label.Length, "長いラベルは切る");
            Eq("#444444,#555555", string.Join(",", items[3].Colors.Select(c => c.Hex)), "hex が colors に無ければ先頭に足す");
            Eq(2, two.OriginalColors.Count, "元の色を取っておく");

            List<ColorOption> ok;
            True(ColorOption.Validate(new[] { new ColorOption("#abc", " ラベル "), new ColorOption("#AABBCC", "x") }, out ok) == null && ok.Count == 1 && ok[0].Label == "ラベル",
                "Validate: そろえる・同じ色は1つ");
            True(ColorOption.Validate(new ColorOption[0], out ok) != null, "Validate: 空は不可");
            True(ColorOption.Validate(new[] { new ColorOption("red", "") }, out ok) != null, "Validate: 読めない色は不可");
            True(ColorOption.Validate(new[] { new ColorOption("#FFFFFF", new string('あ', ColorOption.MaxLabel + 1)) }, out ok) != null, "Validate: 長いラベルは不可");
        }
        finally { Directory.Delete(dir, true); }
    }

    // ---- 自動起動(本物の Run には触らず、テスト用のキーで) ----
    static void AutostartRegistry()
    {
        string key = @"Software\YTT-HoloColors-Test-" + Guid.NewGuid().ToString("N").Substring(0, 8);
        try
        {
            var a = new Autostart(key, @"C:\tools\HoloColors.exe", null);
            True(!a.Enabled, "初めは無い");
            a.Set(true);
            Eq("\"C:\\tools\\HoloColors.exe\" --hidden", a.Current(), "登録の中身");
            True(a.Enabled && !a.PointsElsewhere, "登録した");
            var moved = new Autostart(key, @"D:\new\HoloColors.exe", null);
            True(moved.Enabled && moved.PointsElsewhere, "別の場所の exe を指していると分かる");
            moved.Set(true);
            True(!moved.PointsElsewhere, "付け直すとこの exe");
            moved.Set(false);
            True(!moved.Enabled, "外した");
            moved.Set(false);   // 2回外してもエラーにしない
        }
        finally { Registry.CurrentUser.DeleteSubKeyTree(key, false); }
    }

    // ---- 一覧 ----
    static void PaletteLayout()
    {
        using (var v = new PaletteView())
        {
            v.Font = new Font("Yu Gothic UI", 9f);
            v.Size = new Size(640, 400);
            var g1 = new ColorGroup { Id = "a", Branch = "JP", Name = "A" };
            var g2 = new ColorGroup { Id = "b", Branch = "EN", Name = "B" };
            for (int i = 0; i < 3; i++) g1.Items.Add(new ColorEntry { Id = "a" + i, Name = "a" + i, Hex = "#FF0000", Group = g1 });
            for (int i = 0; i < 9; i++) g2.Items.Add(new ColorEntry { Id = "b" + i, Name = "b" + i, Hex = "#00FF00", Group = g2 });
            v.SetGroups(new List<ColorGroup> { g1, g2 }, "なし", false);
            Eq(12, v.Tiles.Count, "札の数");
            Eq(0, v.SelectedIndex, "初めは先頭を選ぶ");
            int cols = v.Tiles.Count(t => t.Rect.Y == v.Tiles[3].Rect.Y);
            True(cols >= 2, "2列以上に並ぶ: " + cols);
            True(v.Tiles[3].Rect.Y > v.Tiles[0].Rect.Bottom, "次のグループは下の段から");
            True(v.Tiles.All(t => t.Rect.Right <= v.ClientSize.Width), "横にはみ出さない");
            Rectangle r = v.Tiles[4].Rect;
            Eq(4, v.HitTest(new Point(r.X + r.Width / 2, r.Y + r.Height / 2)), "札の上のクリック");
            Eq(-1, v.HitTest(new Point(1, 1)), "札の外");

            True(!v.ShowSelection, "開いた直後は選択の枠を出さない");
            v.MoveSelection(Keys.Right);
            True(v.ShowSelection, "最初の矢印で枠を出す");
            Eq(0, v.SelectedIndex, "最初の矢印は枠を出すだけで動かない");
            v.MoveSelection(Keys.Right);
            Eq(1, v.SelectedIndex, "→");
            v.MoveSelection(Keys.Down);
            True(v.Tiles[v.SelectedIndex].Rect.Y > v.Tiles[1].Rect.Y && v.SelectedEntry.Group == g2, "↓で次のグループの段へ");
            v.MoveSelection(Keys.Up);
            Eq(v.Tiles[1].Rect.Y, v.Tiles[v.SelectedIndex].Rect.Y, "↑で戻る");
            v.MoveSelection(Keys.End);
            Eq(11, v.SelectedIndex, "End");
            v.MoveSelection(Keys.Right);
            Eq(11, v.SelectedIndex, "最後より先へは動かない");

            ColorEntry got = null;
            v.EntryActivated += e => got = e;
            v.ActivateSelected();
            Eq("b8", got == null ? null : got.Name, "Enter で選んでいる色");

            var sel = v.SelectedEntry;
            v.SetGroups(new List<ColorGroup> { g2 }, "なし", true);
            True(v.SelectedEntry == sel, "並べ直しても同じ色を選んだまま");
            v.SetGroups(new List<ColorGroup>(), "なし", false);
            Eq(0, v.Tiles.Count, "空");
            Eq(null, v.SelectedEntry, "空なら何も選ばない");
        }
    }

    // スクロールした絵は、スクロールしていない絵を上へずらしたものと同じはず(文字だけ元の位置に残る、を防ぐ)
    static void PaletteScrollDrawing()
    {
        using (var form = new Form { StartPosition = FormStartPosition.Manual, Location = new Point(-20000, -20000), ShowInTaskbar = false, Size = new Size(640, 420) })
        {
            var v = new PaletteView { Dock = DockStyle.Fill, Font = new Font("Yu Gothic UI", 9f) };
            form.Controls.Add(v);
            var g = new ColorGroup { Id = "a", Branch = "JP", Name = "A" };
            for (int i = 0; i < 40; i++)
            {
                var en = new ColorEntry { Id = "a" + i, Name = "名前" + i, Hex = i % 2 == 0 ? "#1E3A8A" : "#FFE066", Group = g };
                // 3つに1つは色が2つ以上(小さな四角も一緒に動くか)。5つに1つは直した色の印
                if (i % 3 == 0) en.SetColors(new List<ColorOption> { new ColorOption(en.Hex, ""), new ColorOption("#FF0000", "a"), new ColorOption("#00C000", "b") });
                en.Customized = i % 5 == 0;
                g.Items.Add(en);
            }
            form.Show();
            v.SetGroups(new List<ColorGroup> { g }, "なし", false);
            Application.DoEvents();
            int w = v.ClientSize.Width, h = v.ClientSize.Height;
            True(v.AutoScrollMinSize.Height > h + 100, "スクロールできるだけの高さ");

            Bitmap top = Render(v);
            const int d = 57;   // 段の間隔の倍数にならないずれ
            v.AutoScrollPosition = new Point(0, d);
            Application.DoEvents();
            Eq(-d, v.AutoScrollPosition.Y, "スクロールした");
            Bitmap scrolled = Render(v);
            int diff = 0;
            for (int y = 0; y < h - d; y += 1)
                for (int x = 0; x < w; x += 2)
                    if (scrolled.GetPixel(x, y) != top.GetPixel(x, y + d)) diff++;
            top.Dispose();
            scrolled.Dispose();
            Eq(0, diff, "スクロールした絵と、ずらした絵の違う点の数");

            // スクロールしたあとのクリックの判定も、見えている札と同じ
            var tile = v.Tiles[7];
            var p = new Point(tile.Rect.X + 20, tile.Rect.Y + 20 - d);
            Eq(7, v.HitTest(p), "スクロールしたあとのクリック");
        }
    }

    // 札の形(v1.4.0 案B): 上段 = 名前・★、下段 = 色の帯(色の数で等分。1段に入らなければ折り返す)
    static void PaletteBands()
    {
        using (var form = new Form { StartPosition = FormStartPosition.Manual, Location = new Point(-20000, -20000), ShowInTaskbar = false, Size = new Size(760, 460) })
        {
            var v = new PaletteView { Dock = DockStyle.Fill, Font = new Font("Yu Gothic UI", 9f) };
            form.Controls.Add(v);
            var g = new ColorGroup { Id = "a", Branch = "JP", Name = "A" };
            var one = new ColorEntry { Id = "a/1", Name = "一色", Hex = "#123456", Group = g };
            var two = new ColorEntry { Id = "a/2", Name = "二色", Hex = "#FF0000", Group = g };
            two.SetColors(new List<ColorOption> { new ColorOption("#FF0000", "主"), new ColorOption("#00AAFF", "水色") });
            var many = new ColorEntry { Id = "a/3", Name = "六色", Hex = "#FFFFFF", Group = g };
            many.SetColors(new[] { "#FFFFFF", "#111111", "#222222", "#333333", "#444444", "#555555" }.Select(h => new ColorOption(h, "")).ToList());
            g.Items.AddRange(new[] { one, two, many });
            for (int i = 0; i < 12; i++) g.Items.Add(new ColorEntry { Id = "x" + i, Name = "x" + i, Hex = "#808080", Group = g });
            var words = new ColorGroup { Id = "word", Branch = "WORD", Name = "マイワード" };
            var w1 = new ColorEntry { Id = "word/1", Name = "あいさつ", Text = "こんにちは\n二行目", IsUser = true, Group = words, Sub = "", Note = "" };
            words.Items.Add(w1);
            var mine = new ColorGroup { Id = "my", Branch = "MY", Name = "マイカラー" };
            for (int i = 0; i < 3; i++) mine.Items.Add(new ColorEntry { Id = "my/" + i, Name = "m" + i, Hex = "#33AA55", IsUser = true, Group = mine });
            var fav = new ColorGroup { Id = "fav", Branch = "FAV", Name = "お気に入り" };
            fav.Items.Add(mine.Items[0]);
            form.Show();
            v.SetGroups(new List<ColorGroup> { g, words, mine, fav }, "なし", false);
            Application.DoEvents();

            PaletteView.Tile tOne = v.Tiles[0], tTwo = v.Tiles[1], tMany = v.Tiles[2];
            Eq(1, tOne.Bands.Count, "1色の札は帯が1本");
            Eq(tOne.Rect.Width, tOne.Bands[0].Width, "1本の帯は幅いっぱい");
            Eq(2, tTwo.Bands.Count, "2色の札は帯が2本");
            True(Math.Abs(tTwo.Bands[0].Width - tTwo.Bands[1].Width) <= 1, "帯は等分");
            Eq(6, tMany.Bands.Count, "6色の札は帯が6本(+n にまとめない)");
            True(tMany.BandRows >= 2, "入りきらなければ折り返す: " + tMany.BandRows + " 段");
            Eq(tOne.Rect.Height, tMany.Rect.Height, "同じ行の札は高さをそろえる");
            var nextRow = v.Tiles.First(t => t.Rect.Y > tMany.Rect.Y && t.Group == g);
            True(nextRow.Rect.Height < tMany.Rect.Height, "折り返しの無い行は低いまま");
            foreach (var t in v.Tiles)
                foreach (var b in t.Bands)
                    True(t.Rect.Contains(b) && b.Y >= t.Top.Bottom, "帯は札の中の下段: " + t.Entry.Name);
            True(!tMany.Bands[0].IntersectsWith(tMany.Bands[1]) && !tMany.Bands[0].IntersectsWith(tMany.Bands[tMany.Bands.Count - 1]), "帯は重ならない");

            int ci;
            Rectangle b1 = tTwo.Bands[1];
            Eq(1, v.HitTestColor(new Point(b1.X + b1.Width / 2, b1.Y + b1.Height / 2), out ci), "帯の上は同じ札");
            Eq(1, ci, "帯はその色(2つ目)");
            Eq(1, v.HitTestColor(new Point(tTwo.Top.X + 12, tTwo.Top.Y + tTwo.Top.Height / 2), out ci), "名前の段");
            Eq(0, ci, "名前の段は主な色");
            Rectangle b6 = tMany.Bands[5];
            v.HitTestColor(new Point(b6.X + b6.Width / 2, b6.Y + b6.Height / 2), out ci);
            Eq(5, ci, "2段目の最後の帯は6番目の色");
            Rectangle st = tTwo.Star;
            v.HitTestColor(new Point(st.X + st.Width / 2, st.Y + st.Height / 2), out ci);
            Eq(-2, ci, "★ の上");

            // スクロールしても帯の当たりは一緒に動く
            v.AutoScrollPosition = new Point(0, 30);
            Application.DoEvents();
            int dy = -v.AutoScrollPosition.Y;
            True(dy > 0, "スクロールした");
            v.HitTestColor(new Point(b1.X + b1.Width / 2, b1.Y + b1.Height / 2 - dy), out ci);
            Eq(1, ci, "スクロールしたあとの帯");
            v.AutoScrollPosition = Point.Empty;
            Application.DoEvents();

            // クリック: 帯 → その色、名前の段 → 主な色、★ → お気に入り、ワード → 本文(0)
            var got = new List<string>();
            v.EntryActivated += e => got.Add(e.Name + ":enter");
            v.ColorActivated += (e, i) => got.Add(e.Name + ":" + i);
            v.FavoriteToggled += e => got.Add(e.Name + ":fav");
            var moved = new List<string>();
            v.ItemMoved += (e, target) => moved.Add(e.Name + "->" + target.Name);
            var md = typeof(Control).GetMethod("OnMouseDown", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            var mm = typeof(Control).GetMethod("OnMouseMove", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            var mu = typeof(Control).GetMethod("OnMouseUp", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            Func<Point, Point> scr = p => new Point(p.X + v.AutoScrollPosition.X, p.Y + v.AutoScrollPosition.Y);
            Action<Point> click = p0 =>
            {
                var p = scr(p0);
                var a = new MouseEventArgs(MouseButtons.Left, 1, p.X, p.Y, 0);
                md.Invoke(v, new object[] { a });
                mu.Invoke(v, new object[] { a });
            };
            click(new Point(b1.X + b1.Width / 2, b1.Y + b1.Height / 2));
            click(new Point(tTwo.Top.X + 12, tTwo.Top.Y + tTwo.Top.Height / 2));
            click(new Point(st.X + st.Width / 2, st.Y + st.Height / 2));
            var tw = v.Tiles.First(t => t.Entry == w1);
            Eq(1, tw.Bands.Count, "ワードの札は帯1本");
            click(new Point(tw.Bands[0].X + 20, tw.Bands[0].Y + 5));
            Eq("二色:1,二色:0,二色:fav,あいさつ:0", string.Join(",", got), "帯・名前・★・ワード");
            got.Clear();
            var down = new MouseEventArgs(MouseButtons.Left, 1, b1.X + b1.Width / 2, b1.Y + b1.Height / 2, 0);
            var up = new MouseEventArgs(MouseButtons.Left, 1, tTwo.Top.X + 12, tTwo.Top.Y + 8, 0);
            md.Invoke(v, new object[] { down });
            mu.Invoke(v, new object[] { up });
            Eq(0, got.Count, "帯で押して名前で離したらコピーしない");

            // ドラッグ: マイカラーの1つ目を3つ目の位置へ。お気に入りの写しはドラッグできない
            var myTiles = v.Tiles.Where(t => t.Group == mine).ToList();
            True(PaletteView.CanDrag(myTiles[0]), "マイカラーはドラッグできる");
            True(!PaletteView.CanDrag(v.Tiles.First(t => t.Group == fav)), "お気に入りの写しはドラッグできない");
            True(!PaletteView.CanDrag(tTwo), "メンバーの札はドラッグできない");
            Point from = scr(new Point(myTiles[0].Rect.X + 20, myTiles[0].Top.Y + 8)), to = scr(new Point(myTiles[2].Rect.X + myTiles[2].Rect.Width / 2, myTiles[2].Rect.Y + myTiles[2].Rect.Height / 2));
            md.Invoke(v, new object[] { new MouseEventArgs(MouseButtons.Left, 1, from.X, from.Y, 0) });
            mm.Invoke(v, new object[] { new MouseEventArgs(MouseButtons.Left, 0, from.X + 20, from.Y, 0) });
            mm.Invoke(v, new object[] { new MouseEventArgs(MouseButtons.Left, 0, to.X, to.Y, 0) });
            mu.Invoke(v, new object[] { new MouseEventArgs(MouseButtons.Left, 1, to.X, to.Y, 0) });
            Eq("m0->m2", string.Join(",", moved), "ドラッグで並べ替え(落とした先の項目で渡す)");
            Eq(0, got.Count, "ドラッグしたときはコピーしない");

            string tipText = PaletteView.TipText(two);
            True(tipText.Contains("#00AAFF(水色)") && tipText.Contains("#FF0000(主)"), "ツールチップに全部の色とラベル: " + tipText);
            True(PaletteView.TipText(one).Contains("#123456") && !PaletteView.TipText(one).Contains("ほかの色"), "1色の人のツールチップ");
            True(PaletteView.TipText(w1).Contains("二行目"), "ワードのツールチップは本文");
            Eq("こんにちは", PaletteView.FirstLine("\n  こんにちは \n二行目"), "本文の1行目");
        }
    }

    static Bitmap Render(Control c)
    {
        var bmp = new Bitmap(c.Width, c.Height);
        c.DrawToBitmap(bmp, new Rectangle(Point.Empty, c.Size));
        return bmp;
    }

    static void InstanceKey()
    {
        Eq(Instance.Key(@"C:\Data\X"), Instance.Key(@"c:\data\x\"), "大文字小文字・最後の \\ は同じ場所");
        True(Instance.Key(@"C:\Data\X") != Instance.Key(@"C:\Data\Y"), "別の場所は別");
    }
}
