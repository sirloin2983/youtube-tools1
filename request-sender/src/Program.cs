// 起動・右クリックの「送る」のショートカット・記録。
//   RequestSender.exe                 … 画面を開く
//   RequestSender.exe <動画> [<動画>…] … その動画を入れた状態で開く(右クリックの「送る」から)
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

namespace RequestSender
{
    public static class Log
    {
        static string path;

        public static void Init(string dir)
        {
            path = Path.Combine(dir, "request-sender.log");
        }

        // 鍵は書かない(呼ぶ側で渡さない)
        public static void Write(string msg)
        {
            if (path == null) return;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                var fi = new FileInfo(path);
                if (fi.Exists && fi.Length > 256 * 1024) { File.Copy(path, path + ".old", true); File.Delete(path); }
                File.AppendAllText(path, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + msg + "\r\n", new UTF8Encoding(false));
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

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
            Log.Init(DataDir);
            DropboxClient.UseTls12();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.ThreadException += (s, e) => Fatal(e.Exception);
            AppDomain.CurrentDomain.UnhandledException += (s, e) => Fatal(e.ExceptionObject as Exception);
            var form = new MainForm(ExeDir, args.Where(a => !a.StartsWith("--")).ToArray());
            Application.Run(form);
            return 0;
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
