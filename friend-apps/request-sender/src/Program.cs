// 起動・右クリックの「送る」のショートカット(手元の記録は ../common/Log.cs)。
//   RequestSender.exe                 … 画面を開く
//   RequestSender.exe <動画> [<動画>…] … その動画を入れた状態で開く(右クリックの「送る」から)
//   RequestSender.exe --screenshot <png> [--theme A|B|C|D] [--tab send|video|receive] [--sample] [--size 900x620]
//   RequestSender.exe --probe-preview <mp4> <out.txt>   … まとめ動画の小窓で再生が進むかを確かめて out に書く(画面の外。2.7.0)
//                                      [--state manual|weights|many|speakers|strict|busy|done|focus|receiving(受け取るのタブ: すべて受け取るの途中)]
//                                      … 窓を画像に保存して終わる(見た目の確認用。通信しない・設定を書かない・「送る」のショートカットを触らない)
//                                        環境変数 REQUEST_SENDER_SHOT_MANY=1 で「受け取る」の見本を 15 件に
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
using FriendApps;

namespace RequestSender
{
    public static class SendToShortcut
    {
        public const string Name = "切り抜き依頼.lnk";

        public static string LinkPath()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.SendTo), Name);
        }

        public static bool Exists()
        {
            try { return File.Exists(LinkPath()); }
            catch (Exception) { return false; }
        }

        // WScript.Shell(Windows に入っている COM)でショートカットを作る。exe を動かしたときも作り直せば新しい場所を指す
        public static void Create(string exePath)
        {
            Type t = Type.GetTypeFromProgID("WScript.Shell");
            if (t == null) throw new InvalidOperationException("WScript.Shell が使えません");
            object shell = Activator.CreateInstance(t);
            try
            {
                object lnk = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { LinkPath() });
                Type lt = lnk.GetType();
                lt.InvokeMember("TargetPath", BindingFlags.SetProperty, null, lnk, new object[] { exePath });
                lt.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, lnk, new object[] { Path.GetDirectoryName(exePath) });
                lt.InvokeMember("Description", BindingFlags.SetProperty, null, lnk, new object[] { "動画を切り抜き依頼で送る" });
                lt.InvokeMember("Save", BindingFlags.InvokeMethod, null, lnk, null);
                System.Runtime.InteropServices.Marshal.FinalReleaseComObject(lnk);
            }
            finally
            {
                System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
            }
        }
    }

    static class Program
    {
        public static string ExeDir, ExePath, DataDir;

        [STAThread]
        static int Main(string[] args)
        {
            ExePath = Assembly.GetExecutingAssembly().Location;
            ExeDir = Path.GetDirectoryName(ExePath);
            DataDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RequestSender");
            Log.Init(DataDir, "request-sender.log");
            DropboxClient.UseTls12();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.ThreadException += (s, e) => Fatal(e.Exception);
            AppDomain.CurrentDomain.UnhandledException += (s, e) => Fatal(e.ExceptionObject as Exception);
            int shot = Array.IndexOf(args, "--screenshot");
            if (shot >= 0 && shot + 1 < args.Length) return Screenshot(args, args[shot + 1]);
            int probe = Array.IndexOf(args, "--probe-preview");
            if (probe >= 0 && probe + 2 < args.Length) return ProbePreview(args[probe + 1], args[probe + 2]);
            var form = new MainForm(ExeDir, args.Where(a => !a.StartsWith("--")).ToArray());
            Application.Run(form);
            return 0;
        }

        static string Option(string[] args, string name, string dflt)
        {
            int i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : dflt;
        }

        // 見た目の確認: 窓を画面の外に出して、中身を画像に保存して終わる
        static int Screenshot(string[] args, string png)
        {
            try
            {
                MainForm.Offline = true;
                string data = Path.Combine(Path.GetTempPath(), "RequestSender-shot-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                string tab = Option(args, "--tab", "send"), stateName = Option(args, "--state", "");
                bool sample = Array.IndexOf(args, "--sample") >= 0;
                Theme.Set(Option(args, "--theme", "A"));
                using (var form = new MainForm(ExeDir, new string[0], data))
                {
                    form.StartPosition = FormStartPosition.Manual;
                    form.Location = new System.Drawing.Point(-32000, -32000);
                    form.ShowInTaskbar = false;
                    Theme.Set(Option(args, "--theme", "A"));
                    string[] size = Option(args, "--size", "").Split('x');
                    int sw, sh;
                    if (size.Length == 2 && int.TryParse(size[0], out sw) && int.TryParse(size[1], out sh)) form.ClientSize = new System.Drawing.Size(Ui.S(sw), Ui.S(sh));
                    form.Show();
                    if (sample) form.ApplySample();
                    form.ApplyState(stateName);
                    if (tab == "video") form.ShowVideoSample();
                    if (tab == "receive")
                    {
                        form.ShowPage(false);
                        if (sample) form.ShowEntries(SampleListing());
                        if (stateName == "receiving") form.ShowReceivingSample();
                    }
                    Application.DoEvents();
                    form.RenderTo(png);
                    form.Hide();
                }
                try { if (Directory.Exists(data)) Directory.Delete(data, true); } catch (IOException) { }
                return 0;
            }
            catch (Exception ex)
            {
                Log.Write("screenshot: " + ex);
                return 1;
            }
        }

        // 確かめ用: まとめ動画の小窓を画面の外で開き、再生が進むかを out に書いて終わる(--probe-preview <mp4> <out.txt>)
        static int ProbePreview(string mp4, string outTxt)
        {
            string result;
            try
            {
                using (var f = new PreviewForm(Path.GetFullPath(mp4), "確かめ"))
                {
                    f.StartPosition = FormStartPosition.Manual;
                    string png = Environment.GetEnvironmentVariable("REQUEST_SENDER_PROBE_PNG");   // 見た目も撮る(画面に 2 秒出る)
                    f.Location = string.IsNullOrEmpty(png) ? new System.Drawing.Point(-32000, -32000) : new System.Drawing.Point(40, 40);
                    f.TopMost = !string.IsNullOrEmpty(png);
                    f.Show();
                    var sw = System.Diagnostics.Stopwatch.StartNew();
                    while (sw.ElapsedMilliseconds < 10000 && !f.Opened && f.Error == null) { Application.DoEvents(); System.Threading.Thread.Sleep(20); }
                    double p0 = f.PositionSec;
                    sw.Restart();
                    while (sw.ElapsedMilliseconds < 2000) { Application.DoEvents(); System.Threading.Thread.Sleep(20); }
                    if (!string.IsNullOrEmpty(png))
                        using (var bmp = new System.Drawing.Bitmap(f.Width, f.Height))
                        {
                            using (var g = System.Drawing.Graphics.FromImage(bmp)) g.CopyFromScreen(f.Location, System.Drawing.Point.Empty, f.Size);
                            bmp.Save(png, System.Drawing.Imaging.ImageFormat.Png);
                        }
                    result = "opened=" + f.Opened + " duration=" + f.Duration.ToString("0.0") + " pos0=" + p0.ToString("0.00") + " pos1=" + f.PositionSec.ToString("0.00") + " error=" + (f.Error ?? "");
                    f.Close();
                }
            }
            catch (Exception ex) { result = "exception=" + ex.GetType().Name + ": " + ex.Message; }
            File.WriteAllText(outTxt, result, new UTF8Encoding(false));
            return result.StartsWith("opened=True") ? 0 : 1;
        }

        // 「受け取る」の見本: n 本まとめたパック(まとめ動画つき)と失敗の知らせ。
        // 環境変数 REQUEST_SENDER_SHOT_MANY=1 なら 1 本ずつのパックを 13 本足す(一覧が長いときの見た目)
        static OutputListing SampleListing()
        {
            var l = new OutputListing();
            var a = OutputFolder.FromName("20261002-120000-0a1b2c__【雑談】見本の配信 1-5.zip");
            a.Size = 1536L * 1024 * 1024; a.Modified = new DateTime(2026, 10, 2, 13, 5, 0); a.PathLower = "/出力/a.zip"; a.Rev = "1";
            a.Preview = OutputFolder.FromName("20261002-120000-0a1b2c__【雑談】見本の配信 1-5.preview.mp4");
            a.Preview.Size = 18L * 1024 * 1024; a.Preview.PathLower = "/出力/a.preview.mp4"; a.Preview.Rev = "1p";
            var b = OutputFolder.FromName("20261002-110000-0d4e5f__もう1本の見本.失敗.txt");
            b.Size = 300; b.Modified = new DateTime(2026, 10, 2, 11, 40, 0); b.PathLower = "/出力/b.txt"; b.Rev = "2";
            l.Entries.Add(a);
            l.Entries.Add(b);
            if (Environment.GetEnvironmentVariable("REQUEST_SENDER_SHOT_MANY") != "1") return l;
            for (int i = 2; i <= 14; i++)
            {
                var c = OutputFolder.FromName("20261002-1000" + i.ToString("00") + "-0a1b2c__見本の切り抜き_" + i.ToString("00") + ".zip");
                c.Size = 700L * 1024 * 1024; c.Modified = new DateTime(2026, 10, 2, 10, i, 0); c.PathLower = "/出力/c" + i + ".zip"; c.Rev = "c" + i;
                l.Entries.Add(c);
            }
            return l;
        }

        static void Fatal(Exception ex)
        {
            Log.Write("error: " + ex);
            MessageBox.Show("思わぬエラーが起きました。\n\n" + (ex != null ? ex.Message : "") + "\n\n記録: " + Path.Combine(DataDir, "request-sender.log"),
                AppInfo.Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }

        // 最初の起動で1回だけ聞く(答えを覚える)。作ってあれば、exe の場所が変わっていても指し直す
        public static void MaybeAskSendTo(IWin32Window owner)
        {
            string marker = Path.Combine(DataDir, "sendto-asked.txt");
            try
            {
                if (SendToShortcut.Exists()) { SendToShortcut.Create(ExePath); return; }
                if (File.Exists(marker)) return;
                Directory.CreateDirectory(DataDir);
                File.WriteAllText(marker, DateTime.Now.ToString("s"), new UTF8Encoding(false));
            }
            catch (Exception ex) { Log.Write("sendto: " + ex.Message); return; }
            var ans = MessageBox.Show(owner,
                "動画を右クリック →「送る」→「切り抜き依頼」でも送れるようにしますか?\n(あとから画面の下のリンクでも設定できます)",
                AppInfo.Title, MessageBoxButtons.YesNo, MessageBoxIcon.Question);
            if (ans == DialogResult.Yes) CreateSendTo(owner);
        }

        public static bool CreateSendTo(IWin32Window owner)
        {
            try
            {
                SendToShortcut.Create(ExePath);
                return true;
            }
            catch (Exception ex)
            {
                Log.Write("sendto create: " + ex);
                MessageBox.Show(owner, "右クリックの「送る」に出せませんでした: " + ex.Message, AppInfo.Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return false;
            }
        }
    }
}
