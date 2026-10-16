// 起動役のテスト(build.bat が FriendInbox.exe を参照して作り、流す)。窓・玄関のプロセス・通信は使わない。失敗が 1 つでもあれば終了コード 1。
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
        Run("見回り: 窓が戻れば隠す・閉じて仕事なしなら止める・仕事ありなら状態の窓", WatchRules);
        Run("状態: JSON の読み取り(小数の秒・足りない欄は窓が開いている扱い)", StateParse);
        Run("状態の窓の ×: 録画中は止めない・録画が無ければ止める", CloseRule);
        Run("玄関の出力: ready・already の行を読む・読めない行は無視", GatewayLines);
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

    static FriendState S(double ago, bool busy, int rec = 0)
    {
        return new FriendState { WindowAgo = ago, Busy = busy, Recording = rec };
    }

    static void WatchRules()
    {
        Eq(Step.None, Watch.Decide(S(3, true), false), "窓が開いている");
        Eq(Step.None, Watch.Decide(S(19.9, false), false), "20 秒未満はまだ開いている");
        Eq(Step.HideStatus, Watch.Decide(S(2, true), true), "窓が戻れば状態の窓を隠す");
        Eq(Step.Shutdown, Watch.Decide(S(20, false), false), "窓が閉じて仕事なし");
        Eq(Step.Shutdown, Watch.Decide(S(60, false), true), "状態の窓を出していても仕事が無くなれば止める");
        Eq(Step.ShowStatus, Watch.Decide(S(25, true), false), "窓が閉じて仕事あり");
        Eq(Step.None, Watch.Decide(S(25, true), true), "出し済みなら何もしない");
    }

    static void StateParse()
    {
        var s = FriendState.Parse("{\"windowAgo\": 21.5, \"busy\": true, \"recording\": 1, \"making\": 2, \"waiting\": 3, \"label\": \"録画中 1 本\"}");
        Eq(21.5, s.WindowAgo, "秒"); True(s.Busy, "busy"); Eq(1, s.Recording, "rec"); Eq(2, s.Making, "making"); Eq(3, s.Waiting, "waiting"); Eq("録画中 1 本", s.Label, "label");
        var e = FriendState.Parse("{\"busy\": true}");
        Eq(0.0, e.WindowAgo, "欄なしは窓が開いている扱い");
        Eq(Step.None, Watch.Decide(e, false), "誤って止めない");
        Eq(7.0, FriendState.Parse("{\"windowAgo\": 7}").WindowAgo, "整数の秒");
    }

    static void CloseRule()
    {
        True(!Watch.CloseStopsNow(1), "録画中は止めない(最小化)");
        True(Watch.CloseStopsNow(0), "録画が無ければ止める");
    }

    static void GatewayLines()
    {
        var g = new Gateway();
        g.OnLine("ひとことの文字");
        g.OnLine("{\"event\":\"x\"}");
        True(!g.Ready && !g.Already, "読めない行・知らない event は無視");
        g.OnLine("{\"event\":\"already\",\"port\":8721}");
        True(g.Already && g.Port == 8721, "already");
        var r = new Gateway();
        r.OnLine("{\"event\":\"ready\",\"port\":8720,\"pid\":123}");
        True(r.Ready && r.Port == 8720, "ready");
    }
}
