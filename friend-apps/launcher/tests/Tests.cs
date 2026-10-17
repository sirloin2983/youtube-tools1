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
        Run("片付け: previous より古い app-版 だけ消す(新しい物・.tmp は残す)", PruneOld);
        Run("閉じる: 作業中・預かりがあるときだけ確認・文に数と録画の注意", ConfirmRules);
        Run("窓: タイトルの ●n・アイコンの文(127 文字まで)", TrayAndTitle);
        Run("裏で続ける: 仕事が無くなったら自分で終わる(予約の間は続ける)", AutoExitRules);
        Run("起こし直し: 10 分に 3 回まで・止める途中は起こさない", RestartRules);
        Run("状態: JSON の読み取り(足りない欄は 0)", StateParse);
        Run("Python の出力: 渡した番号の ready だけ読む・読めない行は無視", GatewayLines);
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

    static string Temp()
    {
        string d = Path.Combine(Path.GetTempPath(), "fi-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(d);
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
        Eq("0.87.0,0.88.0", string.Join(",", gone.OrderBy(x => x).ToArray()), "消した物");
        True(Directory.Exists(Path.Combine(h, "app-0.91.0")), "新しい未起動の版は残す");
        True(Directory.Exists(Path.Combine(h, "app-0.86.0.tmp")), ".tmp は触らない");
        True(Directory.Exists(Path.Combine(h, "app-0.89.0")) && Directory.Exists(Path.Combine(h, "app-0.90.0")), "current・previous は残す");
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
}
