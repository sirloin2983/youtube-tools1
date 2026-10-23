// FriendApp.exe のテスト(build.bat が FriendApp.exe を参照して作り、流す)。窓・玄関のプロセス・通信は使わない。失敗が 1 つでもあれば終了コード 1。
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using FriendInbox;

static class Tests
{
    static int failures, passed;

    static int Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        Run("版: 数字の並びで比べる(0.9.0 < 0.10.0)・版でない名前は null", VersionCompare);
        Run("版: 置いてある版は python.exe と server.py が揃った物だけ・新しい順・.tmp は入らない", InstalledOrder);
        Run("版: bad に無い一番新しい版を選ぶ・無ければ app-版なしの形・それも無ければ null", PickRules);
        Run("記録: app-versions.json の読み書き・壊れていたら空・bad の重なりと不正な版は捨てる", RecordRoundTrip);
        Run("記録: 起動できた版が current・その前が previous(bad は previous にしない)", MarkStarted);
        Run("片付け: current から数えて 3 つより古い app-版 だけ消す(新しい物・.tmp は残す)", PruneOld);
        Run("片付け: bad は 3 つに数えない・足りなければ消さない", PruneKeepsThreeGood);
        Run("閉じる: 作業中・預かりがあるときだけ確認・文に数と録画の注意", ConfirmRules);
        Run("窓: タイトルの ●n・アイコンの文(127 文字まで)", TrayAndTitle);
        Run("裏で続ける: 仕事が無くなったら自分で終わる(予約の間は続ける)", AutoExitRules);
        Run("起こし直し: 10 分に 3 回まで・止める途中は起こさない", RestartRules);
        Run("状態: JSON の読み取り(足りない欄は 0)", StateParse);
        Run("Python の出力: 渡した番号の ready だけ読む・読めない行は無視", GatewayLines);
        Run("配色: 画面から来た色を読む・形が違えば null・暗いかは帯の明るさ", ThemeParse);
        Run("アイコンのメニュー: 件数の行・作業なし・読み込み中・決めていない本数", MenuRules);
        Run("更新: 前の形の版も比べる・起動できなければ飛ばす・版のフォルダが 2 つそろえば前の形を消す", LegacyRules);
        Run("更新: [更新する] は作業と預かりが無いときだけ入れ替える・状態の読み取り", UpdateRules);
        Run("更新: exe と DLL を写す(動いている物は *.old に)・次の起動で *.old を消す", SwapRules);
        Run("診断: 名前と形・ユーザー名と合言葉を伏せる・最後の 20 行・3 日で消す・ユーザーの PC では書かない", DiagRules);
        Run("YouTube のログイン: ログインの印・書く cookie を選ぶ・Netscape 形式・入れ替えて書く・小窓のプロファイルを消す(偽の cookie)", YtCookieRules);
        foreach (var d in temps)   // Temp() で作った物を片付ける(失敗しても結果は変えない)
        {
            try { if (Directory.Exists(d)) Directory.Delete(d, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
        Console.WriteLine(failures == 0 ? "OK " + passed + " 件" : "NG " + failures + " 件失敗 / " + passed + " 件成功");
        return failures == 0 ? 0 : 1;
    }

    static void Run(string name, Action a)
    {
        try { a(); passed++; Console.WriteLine("OK   " + name); }
        catch (Exception ex) { failures++; Console.WriteLine("FAIL " + name + "\r\n     " + ex.Message); }
    }

    static void Eq(object want, object got, string what)
    {
        if (!object.Equals(want, got)) throw new Exception(what + ": 期待 " + want + " / 実際 " + got);
    }

    static void True(bool v, string what)
    {
        if (!v) throw new Exception(what);
    }

    static readonly List<string> temps = new List<string>();

    static string Temp()
    {
        string d = Path.Combine(Path.GetTempPath(), "fi-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(d);
        temps.Add(d);
        return d;
    }

    static void Install(string home, string ver)
    {
        string root = ver == null ? home : Path.Combine(home, "app-" + ver);
        Directory.CreateDirectory(Path.Combine(root, "python"));
        Directory.CreateDirectory(Path.Combine(root, "src", "friendapp"));
        File.WriteAllText(Path.Combine(root, "python", "python.exe"), "");
        File.WriteAllText(Path.Combine(root, "src", "friendapp", "server.py"), "");
    }

    static void VersionCompare()
    {
        Eq(-1, Versions.Compare("0.9.0", "0.10.0"), "9 < 10");
        Eq(1, Versions.Compare("1.0.0", "0.99.9"), "1.0.0 > 0.99.9");
        Eq(0, Versions.Compare("0.90", "0.90.0"), "足りない桁は 0");
        True(Versions.Parse("0.90.0.tmp") == null, ".tmp");
        True(Versions.Parse("") == null && Versions.Parse("a.b") == null && Versions.Parse("1..2") == null, "版でない");
    }

    static void InstalledOrder()
    {
        string h = Temp();
        Install(h, "0.9.0"); Install(h, "0.10.0"); Install(h, "0.89.0");
        Directory.CreateDirectory(Path.Combine(h, "app-0.91.0.tmp", "src"));
        Directory.CreateDirectory(Path.Combine(h, "app-0.92.0"));   // 中身が揃っていない
        Eq("0.89.0,0.10.0,0.9.0", string.Join(",", Versions.Installed(h).ToArray()), "新しい順");
    }

    static void PickRules()
    {
        string h = Temp();
        True(Versions.Pick(h, new List<string>()) == null, "何も無い");
        Install(h, null);
        Eq(null, Versions.Pick(h, new List<string>()).Version, "app-版なしの形");
        Install(h, "0.89.0"); Install(h, "0.90.0");
        Eq("0.90.0", Versions.Pick(h, new List<string>()).Version, "一番新しい");
        Eq("0.89.0", Versions.Pick(h, new List<string> { "0.90.0" }).Version, "bad を飛ばす");
        Eq(null, Versions.Pick(h, new List<string> { "0.90.0", "0.89.0" }).Version, "全部 bad なら app-版なしの形");
        Eq(Path.Combine(h, "app-0.90.0", "python", "python.exe"), Versions.Pick(h, new List<string>()).Python, "python の場所");
    }

    static void RecordRoundTrip()
    {
        string h = Temp();
        Eq(0, Versions.Read(h).Bad.Count, "ファイルなし");
        var r = new VersionRecord { Current = "0.90.0", Previous = "0.89.0" };
        r.Bad.Add("0.91.0");
        Versions.Write(h, r);
        Versions.Write(h, r);   // 上書き
        var got = Versions.Read(h);
        Eq("0.90.0", got.Current, "current"); Eq("0.89.0", got.Previous, "previous"); Eq("0.91.0", string.Join(",", got.Bad.ToArray()), "bad");
        True(File.ReadAllText(Path.Combine(h, "app-versions.json")).Contains("\"v\":1"), "v:1");
        File.WriteAllText(Path.Combine(h, "app-versions.json"), "{\"bad\":[\"1.0.0\",\"1.0.0\",\"x\",5]}");
        Eq("1.0.0", string.Join(",", Versions.Read(h).Bad.ToArray()), "重なり・不正を捨てる");
        File.WriteAllText(Path.Combine(h, "app-versions.json"), "{ こわれた");
        Eq("", Versions.Read(h).Current, "壊れていたら空");
    }

    static void MarkStarted()
    {
        var r = new VersionRecord { Current = "0.89.0" };
        Versions.MarkStarted(r, "0.90.0");
        Eq("0.90.0", r.Current, "current"); Eq("0.89.0", r.Previous, "previous");
        Versions.MarkStarted(r, "0.90.0");
        Eq("0.89.0", r.Previous, "同じ版なら変えない");
        var b = new VersionRecord { Current = "0.90.0", Previous = "0.89.0" };
        b.Bad.Add("0.90.0");
        Versions.MarkStarted(b, "0.89.0");   // 0.90.0 は起動できず 0.89.0 で起こし直した
        Eq("0.89.0", b.Current, "戻った版が current"); Eq("", b.Previous, "bad は previous にしない・自分自身も previous にしない");
    }

    static void PruneOld()
    {
        string h = Temp();
        foreach (var v in new[] { "0.87.0", "0.88.0", "0.89.0", "0.90.0", "0.91.0" }) Install(h, v);
        Directory.CreateDirectory(Path.Combine(h, "app-0.86.0.tmp"));
        var gone = Versions.Prune(h, new VersionRecord { Current = "0.90.0", Previous = "0.89.0" }, null);
        Eq("0.87.0", string.Join(",", gone.OrderBy(x => x).ToArray()), "消した物(current から数えて 3 つ = 0.90.0・0.89.0・0.88.0 を残す)");
        True(Directory.Exists(Path.Combine(h, "app-0.91.0")), "新しい未起動の版は残す");
        True(Directory.Exists(Path.Combine(h, "app-0.86.0.tmp")), ".tmp は触らない");
        True(Directory.Exists(Path.Combine(h, "app-0.88.0")) && Directory.Exists(Path.Combine(h, "app-0.89.0")) && Directory.Exists(Path.Combine(h, "app-0.90.0")), "current・previous とその前は残す");
    }

    // bad は残す 3 つに数えない(bad の新しい物は消さず、bad の古い物は消す)
    static void PruneKeepsThreeGood()
    {
        string h = Temp();
        foreach (var v in new[] { "0.85.0", "0.86.0", "0.87.0", "0.88.0", "0.89.0", "0.90.0", "0.91.0", "0.92.0" }) Install(h, v);
        var r = new VersionRecord { Current = "0.89.0", Previous = "" };
        r.Bad.Add("0.92.0"); r.Bad.Add("0.91.0"); r.Bad.Add("0.90.0"); r.Bad.Add("0.86.0");
        Eq("0.87.0", Versions.KeepFloor(h, r), "bad を除いて 0.89.0・0.88.0・0.87.0 の 3 つ目");
        var gone = Versions.Prune(h, r, null);
        Eq("0.85.0,0.86.0", string.Join(",", gone.OrderBy(x => x).ToArray()), "floor より古い物(bad の 0.86.0 も)だけ消す");
        True(Directory.Exists(Path.Combine(h, "app-0.90.0")) && Directory.Exists(Path.Combine(h, "app-0.92.0")), "bad でも floor 以上は残す");
        // 足りないときは最古を floor に(消さない)
        string k = Temp();
        Install(k, "0.88.0"); Install(k, "0.89.0");
        Eq("0.88.0", Versions.KeepFloor(k, new VersionRecord { Current = "0.89.0" }), "2 つしか無ければ最古");
        Eq(0, Versions.Prune(k, new VersionRecord { Current = "0.89.0", Previous = "0.88.0" }, null).Count, "足りなければ何も消さない");
        Eq(null, Versions.KeepFloor(k, new VersionRecord()), "current が無ければ floor なし(何も消さない)");
        // 戻って current が古くなっても、current より新しい版は数えない
        string m = Temp();
        foreach (var v in new[] { "0.86.0", "0.87.0", "0.88.0", "0.89.0", "0.90.0" }) Install(m, v);
        var q = new VersionRecord { Current = "0.88.0", Previous = "" };
        q.Bad.Add("0.90.0"); q.Bad.Add("0.89.0");
        Eq("0.86.0", Versions.KeepFloor(m, q), "current 以下の 3 つ(0.88.0・0.87.0・0.86.0)");
    }

    static HostState S(int making = 0, int rec = 0, int waiting = 0, int reserved = 0, int archive = 0, bool setup = false)
    {
        return new HostState { Making = making, Recording = rec, Waiting = waiting, Reserved = reserved, ArchiveWait = archive, Setup = setup };
    }

    static void ConfirmRules()
    {
        True(!Rules.NeedConfirm(S()), "作業も預かりも無ければ確認なし");
        True(!Rules.NeedConfirm(null), "状態を読めない(Python が止まっている)なら確認なし");
        True(Rules.NeedConfirm(S(making: 1)) && Rules.NeedConfirm(S(rec: 1)) && Rules.NeedConfirm(S(waiting: 1)), "作っている・録画中・待ち");
        True(Rules.NeedConfirm(S(reserved: 1)) && Rules.NeedConfirm(S(archive: 1)) && Rules.NeedConfirm(S(setup: true)), "予約・アーカイブ待ち・準備中");
        Eq(0, S(making: -3).Holdings, "負の数は 0");
        string t = Rules.ConfirmText(S(making: 2, rec: 1, reserved: 1, archive: 3));
        True(t.Contains("作っている物が 2 件") && t.Contains("録画が途中で切れます") && t.Contains("予約が 1 件") && t.Contains("アーカイブ待ちが 3 件"), "数と録画の注意");
        True(t.Contains("閉じると止まります"), "閉じると止まる");
        True(!Rules.ConfirmText(S(making: 1)).Contains("録画"), "録画が無ければ録画の注意なし");
    }

    static void TrayAndTitle()
    {
        Eq("切り抜き依頼", Rules.Title(0), "0 なら数なし");
        Eq("切り抜き依頼 ●3", Rules.Title(3), "●n");
        True(Rules.TrayText(S(making: 2, rec: 1), false).Contains("作っています 2 件・録画中 1 件"), "アイコンの文");
        True(Rules.TrayText(S(), true).Contains("裏で続けています"), "裏で");
        True(Rules.TrayText(null, false).Length > 0, "状態なし");
        True(Rules.TrayText(S(making: 99999, rec: 99999, waiting: 99999, reserved: 99999, archive: 99999, setup: true), true).Length <= 127, "127 文字まで");
    }

    static void AutoExitRules()
    {
        True(Rules.AutoExit(S(), true), "裏で続けていて仕事が無くなれば終わる");
        True(!Rules.AutoExit(S(making: 1), true), "仕事があれば続ける");
        True(!Rules.AutoExit(S(), false), "窓を開いている間は終わらない");
        True(!Rules.AutoExit(null, true), "状態を読めないときは終わらない(起こし直しの途中)");
        True(!Rules.AutoExit(S(reserved: 1), true), "予約を待っている間は終わらない");
    }

    static void RestartRules()
    {
        var recent = new List<DateTime>();
        var now = new DateTime(2026, 10, 17, 12, 0, 0);
        True(Rules.ShouldRestart(recent, now, false), "初めは起こし直す");
        True(!Rules.ShouldRestart(recent, now, true), "止める途中なら起こさない");
        recent.AddRange(new[] { now.AddMinutes(-1), now.AddMinutes(-2), now.AddMinutes(-3) });
        True(!Rules.ShouldRestart(recent, now, false), "10 分に 3 回まで");
        recent.Clear();
        recent.AddRange(new[] { now.AddMinutes(-11), now.AddMinutes(-12), now.AddMinutes(-2) });
        True(Rules.ShouldRestart(recent, now, false), "10 分より前は数えない");
        Eq(1, recent.Count, "古い記録を捨てる");
    }

    static void StateParse()
    {
        var s = HostState.Parse("{\"making\":2,\"recording\":1,\"waiting\":3,\"reserved\":4,\"archiveWait\":5,\"setup\":true,\"undecided\":6,\"awake\":true,\"label\":\"x\"}");
        Eq(2, s.Making, "making"); Eq(1, s.Recording, "rec"); Eq(3, s.Waiting, "waiting"); Eq(4, s.Reserved, "reserved"); Eq(5, s.ArchiveWait, "archive");
        True(s.Setup && s.Awake, "setup・awake"); Eq(6, s.Undecided, "undecided"); Eq("x", s.Label, "label");
        Eq(16, s.Holdings, "作業中と預かりの数");
        var e = HostState.Parse("{}");
        Eq(0, e.Holdings, "欄なしは 0"); True(!e.Awake, "欄なしはスリープを止めない");
    }

    static void GatewayLines()
    {
        var g = new Gateway { Port = 8720 };
        g.OnLine("ひとことの文字");
        g.OnLine("{\"event\":\"x\"}");
        True(!g.Ready, "読めない行・知らない event は無視");
        g.OnLine("{\"event\":\"ready\",\"port\":8721}");
        True(!g.Ready, "渡した番号と違う ready は無視");
        g.OnLine("{\"event\":\"ready\",\"port\":8720,\"pid\":123}");
        True(g.Ready && !g.Bye, "ready");
        g.OnLine("{\"event\":\"bye\"}");
        True(g.Bye, "bye = 止めてと言われて終わる(起こし直さない)");
        int p = Gateway.FreePort();
        True(p > 0 && p < 65536, "空いている番号");
    }

    static void MenuRules()
    {
        Eq("状態を読み込んでいます", Rules.MenuStatus(null), "読めない");
        Eq("作業はありません", Rules.MenuStatus(S()), "作業なし");
        Eq("作っています 2 件・録画中 1 件・予約 1 件", Rules.MenuStatus(S(making: 2, rec: 1, reserved: 1)), "件数");
        Eq("準備しています", Rules.MenuStatus(S(setup: true)), "準備中");
        True(Rules.MenuUndecided(S()) == null && Rules.MenuUndecided(null) == null, "0 なら出さない");
        Eq("まだ決めていない物 4 本", Rules.MenuUndecided(new HostState { Undecided = 4 }), "決めていない本数");
    }

    static void Legacy(string home, string ver)
    {
        Install(home, null);
        Directory.CreateDirectory(Path.Combine(home, "src", "ytt"));
        File.WriteAllText(Path.Combine(home, "src", "ytt", "version.py"), "# x\nVERSION = \"" + ver + "\"\n");
    }

    static void LegacyRules()
    {
        string h = Temp();
        Legacy(h, "0.99.13");
        Install(h, "0.99.12");
        Eq("0.99.13", Versions.LegacyVersion(h), "前の形の版");
        Eq(null, Versions.Pick(h, new List<string>()).Version, "前の形の方が新しい = 前の形(移る最後の 1 回)");
        Eq("0.99.12", Versions.Pick(h, new List<string>(), true).Version, "前の形が起動できなければ版のフォルダ");
        Install(h, "0.99.14");
        Eq("0.99.14", Versions.Pick(h, new List<string>()).Version, "版のフォルダの方が新しい");
        File.WriteAllText(Path.Combine(h, "src", "ytt", "version.py"), "VERSION = \"x\"");
        Eq(null, Versions.LegacyVersion(h), "読めない版");
        // 前の形を消すのは版のフォルダが 2 つそろい、前の形の方が古いときだけ
        string k = Temp();
        Legacy(k, "0.99.11");
        Install(k, "0.99.13");
        var gone = Versions.Prune(k, new VersionRecord { Current = "0.99.13", Previous = "" }, null);
        True(Directory.Exists(Path.Combine(k, "src")), "previous が無ければ前の形は残す(戻る先)");
        Install(k, "0.99.12");
        gone = Versions.Prune(k, new VersionRecord { Current = "0.99.13", Previous = "0.99.12" }, null);
        True(!Directory.Exists(Path.Combine(k, "src")) && !Directory.Exists(Path.Combine(k, "python")), "2 つそろえば前の形を消す");
        string m = Temp();
        Legacy(m, "0.99.20");
        Install(m, "0.99.13"); Install(m, "0.99.12");
        Versions.Prune(m, new VersionRecord { Current = "0.99.13", Previous = "0.99.12" }, null);
        True(Directory.Exists(Path.Combine(m, "src")), "前の形の方が新しければ消さない");
    }

    static void UpdateRules()
    {
        var s = HostState.Parse("{\"update\":\"0.99.14\",\"updateRequested\":true}");
        Eq("0.99.14", s.Update, "版"); True(s.UpdateRequested, "押した");
        True(Rules.ShouldApplyUpdate(s), "作業なし = 入れ替える");
        s.Making = 1;
        True(!Rules.ShouldApplyUpdate(s), "作っている間は待つ");
        True(!Rules.ShouldApplyUpdate(new HostState { Update = "0.99.14", UpdateRequested = true, Reserved = 1 }), "予約の間も待つ");
        True(!Rules.ShouldApplyUpdate(new HostState { Update = "0.99.14" }), "押していない");
        True(!Rules.ShouldApplyUpdate(new HostState { Update = "", UpdateRequested = true }), "新しい版が無い");
        True(!Rules.ShouldApplyUpdate(null), "状態なし");
        Eq("", HostState.Parse("{}").Update, "欄なし");
    }

    static void SwapRules()
    {
        string h = Temp();
        Directory.CreateDirectory(Path.Combine(h, "app-0.99.14"));
        File.WriteAllText(Path.Combine(h, "FriendApp.exe"), "old-exe");
        File.WriteAllText(Path.Combine(h, "WebView2Loader.dll"), "old-dll");
        File.WriteAllText(Path.Combine(h, "app-0.99.14", "FriendApp.exe"), "new-exe");
        File.WriteAllText(Path.Combine(h, "app-0.99.14", "WebView2Loader.dll"), "new-dll");
        Eq(2, Updater.Swap(h, "0.99.14"), "写した数(版のフォルダにある物だけ)");
        Eq("new-exe", File.ReadAllText(Path.Combine(h, "FriendApp.exe")), "exe");
        Eq("old-exe", File.ReadAllText(Path.Combine(h, "FriendApp.exe.old")), "前の exe は .old");
        Eq("new-dll", File.ReadAllText(Path.Combine(h, "WebView2Loader.dll")), "dll");
        Eq(2, Updater.CleanOld(h), ".old を消す");
        True(!File.Exists(Path.Combine(h, "FriendApp.exe.old")), "消えた");
        Eq(0, Updater.Swap(h, "0.99.99"), "版のフォルダに exe が無ければ写さない");
        // 写す途中で落ちた(*.new だけ残った)= 本体は前の版のまま・次の起動の CleanOld が *.new を消す(10-23 の見回り)
        File.WriteAllText(Path.Combine(h, "FriendApp.exe.new"), "half");
        Eq("new-exe", File.ReadAllText(Path.Combine(h, "FriendApp.exe")), "本体はそのまま");
        Updater.CleanOld(h);
        True(!File.Exists(Path.Combine(h, "FriendApp.exe.new")), "*.new を消す");
        // 写せなかった(版のフォルダの DLL を開けない)= 本体は元のまま・*.new も残さない
        Directory.CreateDirectory(Path.Combine(h, "app-0.99.15"));
        File.WriteAllText(Path.Combine(h, "app-0.99.15", "FriendApp.exe"), "v15");
        Directory.CreateDirectory(Path.Combine(h, "WebView2Loader.dll.new"));   // *.new に写せない
        File.WriteAllText(Path.Combine(h, "app-0.99.15", "WebView2Loader.dll"), "dll15");
        bool threw = false;
        try { Updater.Swap(h, "0.99.15"); } catch (Exception) { threw = true; }
        True(threw, "写せなければ例外");
        Eq("new-exe", File.ReadAllText(Path.Combine(h, "FriendApp.exe")), "写せなくても本体は元のまま");
        True(!File.Exists(Path.Combine(h, "FriendApp.exe.new")), "写しかけの *.new を残さない");
    }

    static void DiagRules()
    {
        string tok = new string('a', 48);
        string m = Diag.Mask(@"C:\Users\taro\x と c:/users/taro/y と D:\友人\App\data と C:\Users\hanako\z と taro さん " + tok + " tok=secret12345",
                             @"D:\友人\App", @"C:\Users\taro", "taro", "secret12345");
        foreach (var bad in new[] { "taro", "hanako", tok, "secret12345", "友人" }) True(!m.Contains(bad), "伏せる: " + bad + " / " + m);
        True(m.Contains(@"<app>\data") && m.Contains(@"C:\Users\<user>\z"), "置き換えの形: " + m);
        Eq("ab cd", Diag.Mask("ab cd", null, null, "ab", null), "2 字の名前は伏せない");

        string h = Temp();
        var now = new DateTime(2026, 10, 18, 3, 0, 0, DateTimeKind.Utc);
        var tail = Enumerable.Range(1, 30).Select(i => "line " + i + @" C:\Users\taro\a").ToList();
        string p = Diag.Write(h, "start", "0.99.18", "webview2", "起きませんでした", "detail", tail, new Dictionary<string, object> { { "exitCode", 3 } }, now, tok);
        True(p != null && Diag.NameRx.IsMatch(Path.GetFileName(p)) && Path.GetFileName(p).StartsWith("launcher__diag-"), "名前: " + p);
        Eq(Path.Combine(h, "data", "app", "outbox"), Path.GetDirectoryName(p), "送り返しの箱");
        var d = FriendApps.Json.Parse(File.ReadAllText(p, Encoding.UTF8));
        Eq("start", FriendApps.Json.Str(d, "kind"), "kind");
        Eq("exe", FriendApps.Json.Str(d, "source"), "source");
        Eq(3, FriendApps.Json.Int(d, "exitCode", 0), "extra");
        Eq("0.99.18", FriendApps.Json.Str(FriendApps.Json.Dict(d, "app"), "version"), "版");
        var lines = ((System.Collections.IEnumerable)d["tail"]).Cast<object>().Select(x => x.ToString()).ToList();
        Eq(20, lines.Count, "最後の 20 行");
        Eq(@"line 30 C:\Users\<user>\a", lines[19], "行も伏せる");
        string p2 = Diag.Write(h, "start", null, null, "x", null, null, null, now, null);
        True(p2 != null && p2 != p, "同じミリ秒でも別の名前");
        string old = Path.Combine(h, "data", "app", "outbox", "launcher__diag-" + ((long)(now.AddDays(-3).AddSeconds(-1) - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalMilliseconds).ToString("D13") + ".diag.json");
        File.WriteAllText(old, "{}");
        File.WriteAllText(Path.Combine(h, "data", "app", "outbox", "x__y.verdict.json"), "{}");
        Eq(1, Diag.Prune(Path.Combine(h, "data", "app", "outbox"), now), "3 日より古い物を消す");
        True(File.Exists(Path.Combine(h, "data", "app", "outbox", "x__y.verdict.json")), "診断でない物は残す");
        File.WriteAllText(Path.Combine(h, "data", "app", "prefs.json"), "{\"intake\":{\"folder\":\"D:/Dropbox\"}}");
        Eq(null, Diag.Write(h, "start", null, null, "x", null, null, null, now, null), "ユーザーの PC の作業データでは書かない");
        Directory.Delete(h, true);
    }

    static void YtCookieRules()
    {
        True(YtCookies.LoggedIn(new[] { "YSC", "LOGIN_INFO", "SAPISID" }), "LOGIN_INFO と SAPISID");
        True(YtCookies.LoggedIn(new[] { "LOGIN_INFO", "__Secure-3PAPISID" }), "__Secure-3PAPISID でもよい");
        True(!YtCookies.LoggedIn(new[] { "YSC", "VISITOR_INFO1_LIVE" }), "ログイン前");
        True(!YtCookies.LoggedIn(null), "無い");
        True(YtCookies.IsYouTube("https://www.youtube.com/") && !YtCookies.IsYouTube("http://www.youtube.com/") && !YtCookies.IsYouTube("https://accounts.google.com/x"), "youtube のページ");
        True(YtCookies.IsRobots("https://www.youtube.com/robots.txt") && !YtCookies.IsRobots("https://www.youtube.com/"), "robots.txt");
        var rows = new List<CookieRow> {
            new CookieRow { Domain = ".youtube.com", Name = "SAPISID", Value = "fake-sapisid", Secure = true, Expires = 1900000000 },
            new CookieRow { Domain = ".youtube.com", Name = "SAPISID", Value = "dup", Secure = true, Expires = 1900000000 },
            new CookieRow { Domain = "www.youtube.com", Path = "/", Name = "YSC", Value = "fake-ysc", HttpOnly = true, Secure = true },
            new CookieRow { Domain = ".google.com", Name = "SID", Value = "fake-sid", HttpOnly = true, Expires = 1900000001 },
            new CookieRow { Domain = ".example.com", Name = "X", Value = "other" },
            new CookieRow { Domain = ".notyoutube.com", Name = "X", Value = "other" },
            new CookieRow { Domain = ".youtube.com", Name = "BAD", Value = "a\tb" },
        };
        var picked = YtCookies.Pick(rows);
        Eq(3, picked.Count, "youtube.com・google.com だけ・重ならない・タブの入った物は書かない");
        Eq(".youtube.com\tTRUE\t/\tTRUE\t1900000000\tSAPISID\tfake-sapisid", YtCookies.Line(picked[0]), "ドメインの cookie");
        Eq("#HttpOnly_www.youtube.com\tFALSE\t/\tTRUE\t0\tYSC\tfake-ysc", YtCookies.Line(picked[1]), "ホストだけ・HttpOnly・セッション");
        string text = YtCookies.Text(rows);
        True(text.StartsWith("# Netscape HTTP Cookie File\n"), "頭の行");
        True(!text.Contains("\r") && !text.Contains("other"), "LF・ほかのサイトは入らない");
        string d = Path.Combine(Path.GetTempPath(), "fi-yt-" + Guid.NewGuid().ToString("N"));
        Eq(3, YtCookies.Save(d, rows), "書いた件数");
        Eq(text, File.ReadAllText(YtCookies.CookiesPath(d)), "中身");
        True(YtCookies.CookiesPath(d).EndsWith(Path.Combine("secrets", "youtube-cookies.txt")), "Python の places.cookies_path と同じ所");
        Eq(1, YtCookies.Save(d, rows.Skip(3).Take(1)), "書き直し(入れ替え)");
        Eq(1, File.ReadAllLines(YtCookies.CookiesPath(d)).Count(l => l.Contains("\t")), "前の物は残らない");
        True(!File.Exists(YtCookies.CookiesPath(d) + ".tmp"), "一時のファイルは残らない");
        Directory.CreateDirectory(Path.Combine(YtCookies.ProfileDir(d), "Default"));
        True(YtCookies.DeleteProfile(d) && !Directory.Exists(YtCookies.ProfileDir(d)), "小窓のプロファイルを消す");
        True(YtCookies.DeleteProfile(d), "無くてもよい");
        Directory.Delete(d, true);
    }

    static void ThemeParse()
    {
        var th = Theme.From(FriendApps.Json.Parse("{\"caption\":[20,24,32],\"text\":[230,233,239],\"panel\":[29,33,41],\"accent\":[72,147,230]}"));
        True(th != null, "読める");
        Eq(System.Drawing.Color.FromArgb(20, 24, 32).ToArgb(), th.Caption.ToArgb(), "帯");
        True(th.Dark, "暗い帯");
        Eq(th.Ink.ToArgb(), th.Line.ToArgb(), "線が無ければ文字の色");
        Eq(th.Panel.ToArgb(), th.AccentInk.ToArgb(), "accentInk が無ければ面の色");
        True(!Theme.From(FriendApps.Json.Parse("{\"caption\":[255,255,255],\"text\":[0,0,0]}")).Dark, "明るい帯");
        True(Theme.From(FriendApps.Json.Parse("{\"caption\":[300,0,0],\"text\":[0,0,0]}")) == null, "範囲の外");
        True(Theme.From(FriendApps.Json.Parse("{\"caption\":[1,2],\"text\":[0,0,0]}")) == null, "3 つでない");
        True(Theme.From(FriendApps.Json.Parse("{\"text\":[0,0,0]}")) == null, "帯が無い");
    }
}
