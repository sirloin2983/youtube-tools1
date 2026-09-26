// 起動・常駐(通知領域のアイコン・呼び出しのキー)・コピー。窓どうしのやりとりは AppController に集める。
//   HoloColors.exe                 … 起動して一覧を出す(すでに動いていれば、そちらの一覧を出す)
//   HoloColors.exe --hidden        … 通知領域にだけ出す(サインイン時の自動起動)
//   HoloColors.exe --quit          … 動いているものを終わらせる(build.bat が exe を作り直す前に使う)
//   --data-dir <フォルダ>           … 作業データの場所(テスト用)。--autostart-key <HKCU の下のキー>(テスト用)
//   --screenshot <png>             … 一覧を開いて画像に保存して終わる(見た目の確認用)
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace HoloColors
{
    public static class Log
    {
        static string path;

        public static void Init(string dir)
        {
            path = Path.Combine(dir, "holo-colors.log");
        }

        public static void Write(string msg)
        {
            if (path == null) return;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                var fi = new FileInfo(path);
                if (fi.Exists && fi.Length > 256 * 1024) File.Copy(path, path + ".old", true);
                if (fi.Exists && fi.Length > 256 * 1024) File.Delete(path);
                File.AppendAllText(path, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + msg + "\r\n", new UTF8Encoding(false));
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    public class Options
    {
        public bool Hidden, Quit;
        public string DataDir, AutostartKey, Screenshot;

        public static Options Parse(string[] args)
        {
            var o = new Options();
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                string next = i + 1 < args.Length ? args[i + 1] : null;
                if (a == "--hidden") o.Hidden = true;
                else if (a == "--quit") o.Quit = true;
                else if (a == "--data-dir" && next != null) { o.DataDir = next; i++; }
                else if (a == "--autostart-key" && next != null) { o.AutostartKey = next; i++; }
                else if (a == "--screenshot" && next != null) { o.Screenshot = next; i++; }
            }
            return o;
        }
    }

    public static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            var opt = Options.Parse(args);
            string exeDir = Path.GetDirectoryName(Application.ExecutablePath);
            string dataDir = opt.DataDir != null ? Path.GetFullPath(opt.DataDir)
                : Files.DataDir(exeDir, Environment.GetEnvironmentVariable("YTT_DATA_DIR"), Environment.GetEnvironmentVariable("LOCALAPPDATA"));
            Log.Init(dataDir);
            string key = Instance.Key(dataDir);

            if (opt.Quit)
            {
                MessageWindow.Broadcast(key, true);
                return 0;
            }

            bool first;
            using (var mutex = new Mutex(true, @"Local\YTT.HoloColors." + key, out first))
            {
                if (!first)
                {
                    // もう動いている: そちらの一覧を出してもらって、こちらは終わる
                    if (!opt.Hidden) MessageWindow.Broadcast(key, false);
                    return 0;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.ThreadException += (s, e) => Fatal(e.Exception, false);
                AppDomain.CurrentDomain.UnhandledException += (s, e) => Fatal(e.ExceptionObject as Exception, true);
                Log.Write("start " + AppInfo.Version + " data=" + dataDir);
                using (var ctx = new AppController(opt, exeDir, dataDir, key))
                    Application.Run(ctx);
                Log.Write("exit");
                GC.KeepAlive(mutex);
            }
            return 0;
        }

        static void Fatal(Exception ex, bool terminating)
        {
            Log.Write("error: " + ex);
            try
            {
                MessageBox.Show("思わぬエラーが起きました" + (terminating ? "。アプリを終了します" : "") + "\n\n" + (ex == null ? "" : ex.Message),
                    AppInfo.Name, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            catch (Exception) { }
        }
    }

    public class AppController : ApplicationContext
    {
        public readonly Store Store;
        public Autostart Autostart;
        public Palette Palette = new Palette();
        public bool Quitting;
        readonly Options opt;
        readonly MessageWindow messages;
        readonly NotifyIcon tray = new NotifyIcon();
        readonly MainForm main;
        readonly Toast toast = new Toast();
        IntPtr previous = IntPtr.Zero;   // 一覧を出す前に前面だった窓(閉じたら戻す)
        Form modal;                      // 開いている設定・追加の画面
        bool suspended;
        string paletteError;

        public AppController(Options opt, string exeDir, string dataDir, string key)
        {
            this.opt = opt;
            Store = new Store(dataDir);
            Store.Load();
            Autostart = new Autostart(opt.AutostartKey ?? Autostart.DefaultKey, Application.ExecutablePath,
                opt.DataDir != null ? "--data-dir \"" + dataDir + "\"" : null);
            string membersPath = Path.Combine(exeDir, AppInfo.MembersFile);
            try
            {
                Palette = Palette.Load(membersPath);
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is FormatException || ex is ArgumentException || ex is InvalidOperationException || ex is UnauthorizedAccessException)) throw;
                paletteError = AppInfo.MembersFile + " が読めません(" + ex.Message + ")。HoloColors.exe と同じフォルダに置いてください";
                Log.Write("members: " + ex);
            }

            main = new MainForm(this);
            // 窓を先に作っておく(見せるまで作らないと、最初にキーを押したときの表示が遅れる。中の部品も仮の窓ではなくこの窓に作られる)
            IntPtr created = main.Handle;
            main.ApplySettings(Store.Settings);
            main.SetFilter(Store.Settings.Filter, false);
            if (Store.Settings.WindowWidth > 0 && Store.Settings.WindowHeight > 0)
                main.Size = new Size(Store.Settings.WindowWidth, Store.Settings.WindowHeight);
            else
                main.Size = ScaleSize(new Size(600, 560));

            messages = new MessageWindow(key);
            messages.HotkeyPressed += OnHotkey;
            messages.ShowRequested += () => ShowMain(IntPtr.Zero);
            messages.QuitRequested += Quit;
            RegisterHotkey();

            tray.Icon = AppIcon.Load(SystemInformation.SmallIconSize);
            var menu = new ContextMenuStrip();
            menu.Items.Add("一覧を開く", null, (s, e) => ShowMain(IntPtr.Zero));
            menu.Items.Add("設定…", null, (s, e) => OpenSettings(null));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("終了", null, (s, e) => Quit());
            menu.Items[0].Font = new Font(menu.Items[0].Font, FontStyle.Bold);
            tray.ContextMenuStrip = menu;
            tray.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) ToggleFromTray(); };
            UpdateTrayText();
            tray.Visible = true;

            foreach (string w in Store.Warnings) Log.Write("warning: " + w);
            if (paletteError != null) main.SetStatus(paletteError, true);
            else if (Store.Warnings.Count > 0) main.SetStatus(Store.Warnings[0], true);

            if (opt.Screenshot != null)
            {
                ShowMain(IntPtr.Zero);
                var t = new System.Windows.Forms.Timer { Interval = 700 };
                t.Tick += (s, e) => { t.Stop(); SaveScreenshot(opt.Screenshot); Quit(); };
                t.Start();
                return;
            }
            if (!opt.Hidden) ShowMain(IntPtr.Zero);
            if (!messages.Registered)
                tray.ShowBalloonTip(8000, AppInfo.Name, HotkeyText + " は他のアプリが使っていて登録できませんでした。通知領域のアイコンを右クリック →「設定」で別のキーにしてください", ToolTipIcon.Warning);
            else if (!Store.Settings.Welcomed)
            {
                tray.ShowBalloonTip(8000, AppInfo.Name + " を起動しました", "画面右下の通知領域にいます。どのアプリからでも " + HotkeyText + " で一覧が開きます", ToolTipIcon.Info);
                Store.Settings.Welcomed = true;
                SaveSettings();
            }
        }

        Size ScaleSize(Size s)
        {
            float k = main.DeviceDpi / 96f;
            return new Size((int)(s.Width * k), (int)(s.Height * k));
        }

        public string HotkeyText { get { return Hotkey.Format(Store.Settings.HotkeyMods, Store.Settings.HotkeyKey); } }
        public bool HotkeyActive { get { return messages.Registered; } }

        public string PaletteSummary
        {
            get
            {
                if (paletteError != null) return "読めませんでした";
                int n = Palette.Groups.Sum(g => g.Items.Count);
                return n + " 人" + (Palette.Updated.Length > 0 ? "(" + Palette.Updated + " 時点)" : "");
            }
        }

        public IEnumerable<ColorGroup> AllGroups()
        {
            yield return Store.Mine;
            foreach (var g in Palette.Groups) yield return g;
        }

        // ---- 呼び出しのキー ----
        void RegisterHotkey()
        {
            if (!messages.Register(Store.Settings.HotkeyMods, Store.Settings.HotkeyKey))
                Log.Write("hotkey register failed: " + HotkeyText + " (" + Marshal.GetLastWin32Error() + ")");
            UpdateTrayText();
        }

        // 設定の画面から。登録できなければ理由を返し、前のキーに戻す
        public string ChangeHotkey(int mods, int vk)
        {
            int oldMods = Store.Settings.HotkeyMods, oldKey = Store.Settings.HotkeyKey;
            if (messages.Register(mods, vk))
            {
                Store.Settings.HotkeyMods = mods;
                Store.Settings.HotkeyKey = vk;
                SaveSettings();
                if (suspended) messages.Unregister();   // 欄にフォーカスがある間は外したまま(ResumeHotkey で付け直す)
                UpdateTrayText();
                return null;
            }
            if (!suspended) messages.Register(oldMods, oldKey);
            return "「" + Hotkey.Format(mods, vk) + "」は他のアプリ(または Windows)が使っていて登録できません。別の組み合わせにしてください";
        }

        public void SuspendHotkey()
        {
            suspended = true;
            messages.Unregister();
        }

        public void ResumeHotkey()
        {
            suspended = false;
            RegisterHotkey();
        }

        void UpdateTrayText()
        {
            string t = AppInfo.Name + (messages != null && messages.Registered ? "(" + HotkeyText + " で開く)" : "(キーが未登録)");
            tray.Text = t.Length > 63 ? t.Substring(0, 63) : t;
        }

        void OnHotkey(IntPtr foreground)
        {
            if (modal != null && modal.Visible)
            {
                modal.Activate();
                return;
            }
            if (main.Visible && foreground == main.Handle)
            {
                HideMain(true);
                return;
            }
            ShowMain(foreground);
        }

        void ToggleFromTray()
        {
            if (main.Visible) HideMain(false);
            else ShowMain(IntPtr.Zero);
        }

        bool IsOurs(IntPtr h)
        {
            if (h == IntPtr.Zero) return false;
            if (h == main.Handle || h == toast.Handle) return true;
            return modal != null && modal.IsHandleCreated && h == modal.Handle;
        }

        public void ShowMain(IntPtr foreground)
        {
            if (modal != null && modal.Visible) { modal.Activate(); return; }
            if (!IsOurs(foreground)) previous = foreground;
            if (!main.Visible)
            {
                main.ResetView();
                PlaceNearCursor();
                main.Show();
            }
            if (main.WindowState == FormWindowState.Minimized) main.WindowState = FormWindowState.Normal;
            main.Activate();
            Native.SetForegroundWindow(main.Handle);
            main.SearchBox.Focus();
        }

        void PlaceNearCursor()
        {
            Point p = Cursor.Position;
            Rectangle wa = Screen.FromPoint(p).WorkingArea;
            Size s = main.Size;
            s = new Size(Math.Min(s.Width, wa.Width), Math.Min(s.Height, wa.Height));
            main.Size = s;
            int x = p.X - s.Width / 2, y = p.Y - (int)(40 * main.DeviceDpi / 96f);
            x = Math.Max(wa.Left, Math.Min(x, wa.Right - s.Width));
            y = Math.Max(wa.Top, Math.Min(y, wa.Bottom - s.Height));
            main.Location = new Point(x, y);
        }

        // 隠す。restoreFocus = 呼び出す前の窓を前面へ戻す(すぐ貼り付けられるように)
        public void HideMain(bool restoreFocus)
        {
            if (!main.Visible) return;
            bool wasActive = Native.GetForegroundWindow() == main.Handle;
            main.Hide();
            if (restoreFocus && wasActive && previous != IntPtr.Zero && Native.IsWindow(previous) && Native.IsWindowVisible(previous))
                Native.SetForegroundWindow(previous);
        }

        // ---- コピー ----
        public string CopyText(ColorEntry e)
        {
            return HexColor.Format(e.Hex, Store.Settings.IncludeHash);
        }

        public void Copy(ColorEntry e)
        {
            string text = CopyText(e);
            try
            {
                // 他のアプリがクリップボードを開いていると失敗するので、何度か待ってやり直す
                Clipboard.SetDataObject(text, true, 10, 50);
            }
            catch (ExternalException ex)
            {
                Log.Write("clipboard: " + ex);
                main.SetStatus("コピーできませんでした(他のアプリがクリップボードを使っています)。もう一度押してください", true);
                return;
            }
            main.SetStatus("コピーしました: " + text + "  " + e.Name, false);
            if (Store.Settings.CloseAfterCopy && main.Visible)
            {
                HideMain(true);
                toast.Flash(text + " をコピーしました(" + e.Name + ")", e.Hex);
            }
        }

        // ---- 設定 ----
        public void SetCloseAfterCopy(bool on)
        {
            Store.Settings.CloseAfterCopy = on;
            main.ApplySettings(Store.Settings);
            SaveSettings();
        }

        public void SetIncludeHash(bool on)
        {
            Store.Settings.IncludeHash = on;
            SaveSettings();
        }

        public void SetFilter(string f)
        {
            Store.Settings.Filter = f;
            SaveSettings();
        }

        public void RememberSize(Size s)
        {
            if (main.WindowState != FormWindowState.Normal) return;
            Store.Settings.WindowWidth = s.Width;
            Store.Settings.WindowHeight = s.Height;
            SaveSettings();
        }

        void SaveSettings()
        {
            try
            {
                Store.SaveSettings();
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
                Log.Write("save settings: " + ex);
                main.SetStatus("設定を保存できませんでした: " + ex.Message, true);
            }
        }

        public void OpenSettings(IWin32Window owner)
        {
            if (modal != null && modal.Visible) { modal.Activate(); return; }
            using (var f = new SettingsForm(this))
            {
                modal = f;
                try { f.ShowDialog(owner); }
                finally { modal = null; }
            }
            if (!Quitting && main.Visible) main.Activate();
        }

        // ---- マイカラー ----
        public void AddColor(IWin32Window owner, ColorEntry basedOn)
        {
            string name = basedOn == null ? "" : basedOn.Name;
            string hex = basedOn == null ? "" : basedOn.Hex;
            string r1, r2;
            if (!EditDialog("色を追加", name, hex, owner, out r1, out r2)) return;
            ColorEntry added;
            try { added = Store.Add(r1, r2); }
            catch (Exception ex) { SaveFailed(ex); return; }
            // 足した色が見えるように: 「すべて」「マイカラー」以外なら「マイカラー」へ、検索は空に
            if (main.Filter != "ALL" && main.Filter != "MY") main.SetFilter("MY", true);
            main.SearchBox.Text = "";
            main.Refill(false);
            main.SetStatus("マイカラーに追加しました: " + added.Name + "  " + added.Hex, false);
        }

        public void EditColor(IWin32Window owner, ColorEntry e)
        {
            string r1, r2;
            if (!EditDialog("色を編集", e.Name, e.Hex, owner, out r1, out r2)) return;
            try { Store.Update(e, r1, r2); }
            catch (Exception ex) { SaveFailed(ex); return; }
            main.Refill(true);
            main.SetStatus("保存しました: " + e.Name + "  " + e.Hex, false);
        }

        public void RemoveColor(IWin32Window owner, ColorEntry e)
        {
            if (MessageBox.Show(owner, "「" + e.Name + "」(" + e.Hex + ")をマイカラーから消しますか?", AppInfo.Name,
                    MessageBoxButtons.OKCancel, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.OK) return;
            try { Store.Remove(e); }
            catch (Exception ex) { SaveFailed(ex); return; }
            main.Refill(false);
            main.SetStatus("消しました: " + e.Name, false);
        }

        public void MoveColor(ColorEntry e, int delta)
        {
            try { Store.Move(e, delta); }
            catch (Exception ex) { SaveFailed(ex); return; }
            main.Refill(true);
        }

        void SaveFailed(Exception ex)
        {
            Log.Write("save colors: " + ex);
            main.SetStatus("保存できませんでした: " + ex.Message, true);
        }

        bool EditDialog(string title, string name, string hex, IWin32Window owner, out string rName, out string rHex)
        {
            rName = rHex = null;
            if (modal != null && modal.Visible) { modal.Activate(); return false; }
            using (var f = new EditColorForm(title, name, hex))
            {
                modal = f;
                try
                {
                    if (f.ShowDialog(owner) != DialogResult.OK) return false;
                }
                finally { modal = null; }
                rName = f.ResultName;
                rHex = f.ResultHex;
                return true;
            }
        }

        // ---- 終わる ----
        public void Quit()
        {
            if (Quitting) return;
            Quitting = true;
            if (modal != null) modal.Close();
            tray.Visible = false;
            messages.Unregister();
            main.Close();
            ExitThread();
        }

        // 見た目の確認用。.png なら一覧だけ、フォルダなら主な画面をまとめて保存する(作業データは --data-dir の使い捨ての場所で)
        void SaveScreenshot(string target)
        {
            try
            {
                if (target.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
                {
                    Shot(main, target);
                    return;
                }
                Directory.CreateDirectory(target);
                Shot(main, Path.Combine(target, "main.png"));
                main.SearchBox.Text = "ぺこ";
                Shot(main, Path.Combine(target, "search.png"));
                main.SearchBox.Text = "";
                main.SetFilter("GRAD", false);
                Shot(main, Path.Combine(target, "graduated.png"));
                main.SetFilter("MY", false);
                Shot(main, Path.Combine(target, "my-empty.png"));
                main.SetFilter("ALL", false);
                using (var f = new SettingsForm(this))
                {
                    f.Show();
                    Shot(f, Path.Combine(target, "settings.png"));
                    f.Close();
                }
                using (var f = new EditColorForm("色を追加", "自分の赤", "#E53935"))
                {
                    f.Show();
                    Shot(f, Path.Combine(target, "edit.png"));
                    f.Close();
                }
                toast.Flash("#7EC2FE をコピーしました(兎田ぺこら)", "#7EC2FE");
                Shot(toast, Path.Combine(target, "toast.png"));
            }
            catch (Exception ex)
            {
                Log.Write("screenshot: " + ex);
            }
        }

        static void Shot(Control c, string path)
        {
            Application.DoEvents();
            c.Refresh();
            using (var bmp = new Bitmap(c.Width, c.Height))
            {
                c.DrawToBitmap(bmp, new Rectangle(Point.Empty, c.Size));
                bmp.Save(path, ImageFormat.Png);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                tray.Visible = false;
                tray.Dispose();
                messages.Dispose();
                toast.Dispose();
                main.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
