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
        Run("members.json: 同梱のデータが正しい形", BundledMembers);
        Run("members.json: おかしなデータは読まない", BadMembers);
        Run("自動起動: 登録・外す・別の場所を指す", AutostartRegistry);
        Run("一覧: 札の並び・クリックの判定・キーでの移動", PaletteLayout);
        Run("一覧: スクロールしても札と文字が一緒に動く", PaletteScrollDrawing);
        Run("起動: 作業データの場所ごとに1つ", InstanceKey);
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
                g.Items.Add(new ColorEntry { Id = "a" + i, Name = "名前" + i, Hex = i % 2 == 0 ? "#1E3A8A" : "#FFE066", Group = g });
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
