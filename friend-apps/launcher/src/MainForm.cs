// FriendApp.exe の窓 1 枚: WebView2 で Python の画面を出し、時計の横のアイコン・× と止める確認・スリープ止め・●n を持つ。C# 5 で書く
//   notes:plan/f1-friend-requirements.md の C-1-1・C-3-9・C-5-3・C-5-4。窓と画面の境目は friend-apps/launcher/README.txt
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using FriendApps;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace FriendInbox
{
    public sealed class MainForm : Form
    {
        const int PollMs = 2000;
        const uint ES_CONTINUOUS = 0x80000000, ES_SYSTEM_REQUIRED = 0x00000001;
        static readonly int TaskbarCreated = RegisterWindowMessage("TaskbarButtonCreated");
        readonly string home, friendDir;
        readonly Backend be;
        readonly bool webview;
        readonly EventWaitHandle showEvt;
        readonly NotifyIcon tray = new NotifyIcon();
        readonly Icon appIcon;
        WebView2 view;
        CoreWebView2Environment env;
        string origin = "";
        HostState last;
        bool background, quitting, awake, confirmOpen;
        int undecided = -1;
        ITaskbarList3 taskbar;
        IntPtr overlay = IntPtr.Zero;

        public MainForm(string home, Backend be, bool webview, EventWaitHandle showEvt)
        {
            this.home = home;
            this.be = be;
            this.webview = webview;
            this.showEvt = showEvt;
            friendDir = Path.Combine(home, "data", "app", "friendapp");
            appIcon = MakeAppIcon();
            Icon = appIcon;
            Text = Rules.AppTitle;
            MinimumSize = new Size(720, 480);
            RestoreBounds_();
            if (ShotDir != null)   // 写真を撮るとき: 画面の外に 1280×800 で出す(人の画面を取らない・タスクバーにも出さない)
            {
                StartPosition = FormStartPosition.Manual;
                Bounds = new Rectangle(SystemInformation.VirtualScreen.Right + 200, 0, 1280, 800);
                ShowInTaskbar = false;
            }
            else if (NoActivate) WindowState = FormWindowState.Minimized;   // 開発の PC の確かめ(テストで人の画面を取らない)
            tray.Icon = appIcon;
            tray.Text = Rules.TrayText(null, false);
            tray.Visible = true;
            tray.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) ShowFront(); };
            var menu = new ContextMenuStrip();
            menu.Items.Add("開く", null, delegate { ShowFront(); });
            menu.Items.Add("止める", null, delegate { RequestQuit(); });
            tray.ContextMenuStrip = menu;
            if (webview)
            {
                view = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.White };
                Controls.Add(view);
            }
            else
            {
                CreateHandle();   // 窓は出さない(SetVisibleCore)ので、見回りの糸の BeginInvoke 用にハンドルだけ先に作る
                OpenEdge();
            }
        }

        bool threads;

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            if (threads) return;
            threads = true;
            new Thread(Watch) { IsBackground = true, Name = "friend-watch" }.Start();
            new Thread(WaitShow) { IsBackground = true, Name = "friend-show" }.Start();
        }

        // WebView2 の部品と本体(Edge WebView2 Runtime)が使えるか。DLL が無い PC では型を読む所で落ちるので、別の関数に分けて受け止める
        public static bool WebViewAvailable()
        {
            try { return ProbeWebView(); }
            catch (Exception ex)
            {
                if (!(ex is FileNotFoundException || ex is DllNotFoundException || ex is BadImageFormatException || ex is TypeLoadException ||
                      ex is WebView2RuntimeNotFoundException || ex is COMException)) throw;
                Log.Write("WebView2 を使えません: " + ex.GetType().Name + " " + ex.Message);
                return false;
            }
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        static bool ProbeWebView()
        {
            return !string.IsNullOrEmpty(CoreWebView2Environment.GetAvailableBrowserVersionString());
        }

        // 開発の PC で確かめるときだけ: 最小化で出し、前に出さない(YTT_FRIEND_NOACTIVATE=1)
        // 写真を撮るときだけ: YTT_FRIEND_SHOTS=<フォルダ>(画面の外で起こし、場面ごとに PNG を書いて終わる = 関所で人に見せる用)
        public static readonly string ShotDir = Environment.GetEnvironmentVariable("YTT_FRIEND_SHOTS");
        static readonly bool NoActivate = Environment.GetEnvironmentVariable("YTT_FRIEND_NOACTIVATE") == "1" || ShotDir != null;

        protected override bool ShowWithoutActivation { get { return NoActivate; } }

        protected override void SetVisibleCore(bool value)
        {
            // Edge の窓で開くとき(逃げ道)は、この窓は出さずアイコンだけ
            base.SetVisibleCore(webview ? value : false);
        }

        protected override async void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            if (!webview) return;
            try
            {
                string udf = Path.Combine(friendDir, "webview2");
                env = await CoreWebView2Environment.CreateAsync(null, udf, new CoreWebView2EnvironmentOptions(ShotDir != null ? "--disable-features=msSmartScreenProtection,CalculateNativeWinOcclusion" : "--disable-features=msSmartScreenProtection"));
                await view.EnsureCoreWebView2Async(env);
            }
            catch (Exception ex)
            {
                Program.Fail("画面の部品(WebView2)を起こせませんでした: " + ex.Message);
                StopAll();
                return;
            }
            var core = view.CoreWebView2;
            var st = core.Settings;
            st.AreDevToolsEnabled = Environment.GetEnvironmentVariable("YTT_FRIEND_DEVTOOLS") == "1";
            st.IsStatusBarEnabled = false;
            st.IsGeneralAutofillEnabled = false;
            st.IsPasswordAutosaveEnabled = false;
            st.AreDefaultScriptDialogsEnabled = true;
            core.WebResourceRequested += OnRequest;
            core.NavigationStarting += OnNavigating;
            core.NewWindowRequested += OnNewWindow;
            core.WebMessageReceived += OnMessage;
            core.ProcessFailed += (s, a) => { Log.Write("画面の処理が落ちました: " + a.ProcessFailedKind); BeginInvoke((Action)Reload); };
            if (ShotDir != null)
            {
                bool started = false;
                core.NavigationCompleted += async (s, a) => { if (started) return; started = true; await TakeShots(); };
            }
            Reload();
        }

        // ---- 関所の写真(YTT_FRIEND_SHOTS)。窓は画面の外・前に出さない
        [DllImport("user32.dll")]
        static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);

        [StructLayout(LayoutKind.Sequential)]
        struct RECT { public int Left, Top, Right, Bottom; }

        [DllImport("user32.dll")]
        static extern bool GetWindowRect(IntPtr hwnd, out RECT r);

        [DllImport("dwmapi.dll")]
        static extern int DwmGetWindowAttribute(IntPtr hwnd, int attr, out RECT r, int size);

        static void Capture(Control c, string name)
        {
            using (var bmp = new Bitmap(c.Width, c.Height))
            {
                using (var g = Graphics.FromImage(bmp))
                {
                    IntPtr hdc = g.GetHdc();
                    PrintWindow(c.Handle, hdc, 2);   // PW_RENDERFULLCONTENT(WebView2 の中身も)
                    g.ReleaseHdc(hdc);
                }
                var crop = new Rectangle(Point.Empty, bmp.Size);
                RECT win, vis;
                if (GetWindowRect(c.Handle, out win) && DwmGetWindowAttribute(c.Handle, 9, out vis, Marshal.SizeOf(typeof(RECT))) == 0)   // DWMWA_EXTENDED_FRAME_BOUNDS
                    crop = Rectangle.Intersect(crop, new Rectangle(vis.Left - win.Left, vis.Top - win.Top, vis.Right - vis.Left, vis.Bottom - vis.Top));
                using (var cut = bmp.Clone(crop, bmp.PixelFormat)) cut.Save(Path.Combine(ShotDir, name), System.Drawing.Imaging.ImageFormat.Png);
            }
        }

        async Task TakeShots()
        {
            try
            {
                Directory.CreateDirectory(ShotDir);
                await Task.Delay(3000);
                Capture(this, "f1-start.png");
                using (var big = new Bitmap(appIcon.ToBitmap(), 128, 128)) big.Save(Path.Combine(ShotDir, "f2-tray-icon.png"), System.Drawing.Imaging.ImageFormat.Png);
                var menu = tray.ContextMenuStrip;
                menu.CreateControl();
                menu.PerformLayout();
                using (var mb = new Bitmap(Math.Max(1, menu.PreferredSize.Width), Math.Max(1, menu.PreferredSize.Height)))
                {
                    menu.Size = menu.PreferredSize;
                    menu.DrawToBitmap(mb, new Rectangle(Point.Empty, mb.Size));
                    mb.Save(Path.Combine(ShotDir, "f3-tray-menu.png"), System.Drawing.Imaging.ImageFormat.Png);
                }
                var work = new HostState { Making = 2, Recording = 1, Waiting = 1, Reserved = 1, ArchiveWait = 1 };
                var setupOnly = new HostState { Setup = true };
                File.WriteAllText(Path.Combine(ShotDir, "f-texts.txt"),
                    "アイコンに乗せたとき(作業中):\r\n" + Rules.TrayText(work, false) + "\r\n\r\nアイコンに乗せたとき(裏で続けている・作業なし):\r\n" +
                    Rules.TrayText(new HostState(), true) + "\r\n\r\n窓のタイトル(●n = 3):\r\n" + Rules.Title(3) + "\r\n", new UTF8Encoding(true));
                await ShotConfirm(work, "f4-confirm-working.png");
                await ShotConfirm(setupOnly, "f5-confirm-setup.png");
                await view.CoreWebView2.ExecuteScriptAsync("var b=document.getElementById('btnSettings'); if(b) b.click();");
                await Task.Delay(1500);
                Capture(this, "f6-settings.png");
                Log.Write("関所の写真を書きました: " + ShotDir);
            }
            catch (Exception ex)
            {
                Log.Write("関所の写真に失敗: " + ex);
            }
            StopAll();
        }

        async Task ShotConfirm(HostState st, string name)
        {
            using (var dlg = new ConfirmForm(Rules.ConfirmText(st), appIcon) { StartPosition = FormStartPosition.Manual, Location = new Point(SystemInformation.VirtualScreen.Right + 200, 900) })
            {
                dlg.Show();
                await Task.Delay(500);
                Capture(dlg, name);
                dlg.Close();
            }
        }

        // 今の番号の画面を読み込み直す(Python を起こし直したとき・初めて)。合言葉を足す範囲もその番号に付け替える
        void Reload()
        {
            if (!webview || view == null || view.CoreWebView2 == null) return;
            var core = view.CoreWebView2;
            string next = "http://127.0.0.1:" + be.Port;
            if (next != origin)
            {
                if (origin.Length > 0) core.RemoveWebResourceRequestedFilter(origin + "/*", CoreWebView2WebResourceContext.All);
                origin = next;
                core.AddWebResourceRequestedFilter(origin + "/*", CoreWebView2WebResourceContext.All);
            }
            core.Navigate(origin + "/friend/");
        }

        // 同じオリジンへの要求すべてに合言葉を足す(画面の JS は合言葉を知らない = 古い画面の「合言葉が違います」を根から無くす)
        void OnRequest(object sender, CoreWebView2WebResourceRequestedEventArgs e)
        {
            if (e.Request.Uri.StartsWith(origin + "/", StringComparison.OrdinalIgnoreCase)) e.Request.Headers.SetHeader("X-YTT-Token", be.Token);
        }

        bool SameOrigin(string uri)
        {
            return origin.Length > 0 && (uri == origin || uri.StartsWith(origin + "/", StringComparison.OrdinalIgnoreCase));
        }

        // 窓の中で開くのは自分の画面だけ。外(YouTube など)は既定のブラウザへ
        void OnNavigating(object sender, CoreWebView2NavigationStartingEventArgs e)
        {
            if (SameOrigin(e.Uri) || e.Uri == "about:blank") return;
            e.Cancel = true;
            OpenExternal(e.Uri);
        }

        void OnNewWindow(object sender, CoreWebView2NewWindowRequestedEventArgs e)
        {
            e.Handled = true;
            if (SameOrigin(e.Uri)) new HelpForm(env, e.Uri, origin, appIcon).Show(this);
            else OpenExternal(e.Uri);
        }

        public static void OpenExternal(string uri)
        {
            Uri u;
            if (!Uri.TryCreate(uri, UriKind.Absolute, out u) || (u.Scheme != "https" && u.Scheme != "http")) return;
            try { Process.Start(new ProcessStartInfo(u.AbsoluteUri) { UseShellExecute = true }); }
            catch (Exception ex)
            {
                if (!(ex is System.ComponentModel.Win32Exception || ex is InvalidOperationException)) throw;
                Log.Write("ブラウザで開けませんでした: " + ex.Message);
            }
        }

        // 画面からの呼び出し(host.js の FriendHost): {type:"quit"} / {type:"files", id}(落とした動画ファイル = 本物のパスは exe だけが読める)
        void OnMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            if (!SameOrigin(e.Source)) return;
            IDictionary<string, object> j;
            try { j = Json.Parse(e.WebMessageAsJson); }
            catch (Exception ex)
            {
                if (!(ex is FormatException || ex is ArgumentException || ex is InvalidOperationException)) throw;
                return;
            }
            string type = Json.Str(j, "type");
            if (type == "quit") RequestQuit();
            else if (type == "files") SendFiles(Json.Int(j, "id", 0), e);
        }

        void SendFiles(int id, CoreWebView2WebMessageReceivedEventArgs e)
        {
            var paths = new List<string>();
            var objs = e.AdditionalObjects;
            if (objs != null)
                foreach (object o in objs)
                {
                    var f = o as CoreWebView2File;
                    if (f != null && !string.IsNullOrEmpty(f.Path) && paths.Count < 50) paths.Add(f.Path);
                }
            var sb = new StringBuilder("{\"paths\":[");
            for (int i = 0; i < paths.Count; i++) sb.Append(i > 0 ? "," : "").Append(Quote(paths[i]));
            string body = sb.Append("]}").ToString();
            int port = be.Port;
            ThreadPool.QueueUserWorkItem(delegate
            {
                int status;
                string res = Http.CallKeepError("POST", port, "/api/friend/files", be.Token, 30000, body, out status);
                string json = res != null && res.TrimStart().StartsWith("{") ? res : "null";
                string reply = "{\"type\":\"files\",\"id\":" + id + ",\"status\":" + status + ",\"body\":" + json + "}";
                Ui(() => { if (view != null && view.CoreWebView2 != null) view.CoreWebView2.PostWebMessageAsJson(reply); });
            });
        }

        static string Quote(string s)
        {
            var sb = new StringBuilder("\"");
            foreach (char c in s)
            {
                if (c == '"' || c == '\\') sb.Append('\\').Append(c);
                else if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                else sb.Append(c);
            }
            return sb.Append('"').ToString();
        }

        // 見回り(2 秒ごと): 状態を読む・Python が先に終わったら起こし直して画面を読み込み直す
        void Watch()
        {
            while (!quitting)
            {
                var g = be.Gw;
                if (g != null && !g.Alive && !be.Stopping)
                {
                    try { g.Proc.WaitForExit(); } catch (InvalidOperationException) { }   // 標準出力を読み切ってから bye を見る
                    if (g.Bye)
                    {
                        Log.Write("Python が止めてと言われて終わったので、窓も閉じます");
                        Ui(StopAll);
                        return;
                    }
                    Log.Write("Python が先に終わりました(終了コード " + SafeExit(g) + ")");
                    if (be.Restart()) Ui(Reload);
                    else { Ui(() => { Program.Fail("処理の部品が止まりました。アプリを開き直してください"); StopAll(); }); return; }
                }
                var st = be.State();
                Ui(() => Apply(st));
                Thread.Sleep(PollMs);
            }
        }

        static string SafeExit(Gateway g)
        {
            try { return g.Proc.ExitCode.ToString(); } catch (InvalidOperationException) { return "?"; }
        }

        void WaitShow()
        {
            while (!quitting)
            {
                if (showEvt.WaitOne(1000)) Ui(ShowFront);
            }
        }

        void Ui(Action a)
        {
            try { if (IsHandleCreated && !IsDisposed) BeginInvoke(a); }
            catch (InvalidOperationException) { }   // 窓がもう無い(終わるところ)
        }

        void Apply(HostState st)
        {
            if (quitting) return;
            if (st != null) last = st;
            tray.Text = Rules.TrayText(st ?? last, background);
            bool want = st != null && st.Awake;
            if (want != awake)
            {
                awake = want;
                SetThreadExecutionState(want ? ES_CONTINUOUS | ES_SYSTEM_REQUIRED : ES_CONTINUOUS);   // 止めるのは PC のスリープだけ(画面は消えてよい)
                Log.Write(want ? "作業があるので PC のスリープを止めます" : "スリープ止めをやめます");
            }
            int n = st != null ? st.Undecided : undecided;
            if (n != undecided) { undecided = n; Text = Rules.Title(n); SetBadge(n); }
            if (Rules.AutoExit(st, background) && !confirmOpen) { Log.Write("裏で続けていた作業が全部終わったので閉じます"); StopAll(); }
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!quitting && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                RequestQuit();
            }
            base.OnFormClosing(e);
        }

        // ×・[すべて止めて終了]・アイコンの「止める」: 状態を取り直してから(古い状態で決めない)、作業中・預かりがあるときだけ確認
        void RequestQuit()
        {
            if (quitting || confirmOpen) return;
            confirmOpen = true;
            ThreadPool.QueueUserWorkItem(delegate
            {
                var st = be.State();
                Ui(() =>
                {
                    try
                    {
                        if (!Rules.NeedConfirm(st)) { StopAll(); return; }
                        if (!background) ShowFront();
                        bool keep;
                        using (var dlg = new ConfirmForm(Rules.ConfirmText(st), appIcon))
                        {
                            var r = dlg.ShowDialog(Visible ? (IWin32Window)this : null);
                            if (r == DialogResult.Cancel) return;   // 窓の × と Esc = 何もしない
                            keep = r == DialogResult.Retry;
                        }
                        if (keep) GoBackground(); else StopAll();
                    }
                    finally { confirmOpen = false; }
                });
            });
        }

        void GoBackground()
        {
            SaveBounds();
            background = true;
            Hide();
            tray.Text = Rules.TrayText(last, true);
            Log.Write("窓を閉じて裏で続けます");
        }

        void ShowFront()
        {
            if (quitting) return;
            if (!webview) { OpenEdge(); return; }
            background = false;
            if (!Visible) Show();
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Activate();
            BringToFront();
        }

        // 全部止めて閉じる(待っている依頼は残り、次に開くと続きから)
        void StopAll()
        {
            if (quitting) return;
            quitting = true;
            SaveBounds();
            if (Visible) Hide();
            ThreadPool.QueueUserWorkItem(delegate
            {
                be.Stop();
                Ui(() =>
                {
                    tray.Visible = false;
                    SetThreadExecutionState(ES_CONTINUOUS);
                    Close();
                });
            });
        }

        // ---- Edge の窓で開く逃げ道(WebView2 が無い PC)
        void OpenEdge()
        {
            string url = "http://127.0.0.1:" + be.Port + "/friend/";
            string edge = FindEdge();
            try
            {
                if (edge != null)
                {
                    string prof = Path.Combine(friendDir, "edge-profile");
                    Process.Start(new ProcessStartInfo(edge, "--app=" + url + " --user-data-dir=\"" + prof + "\" --no-first-run") { UseShellExecute = false });
                }
                else Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                if (!(ex is System.ComponentModel.Win32Exception || ex is InvalidOperationException)) throw;
                Log.Write("Edge の窓を開けませんでした: " + ex.Message);
            }
        }

        static string FindEdge()
        {
            foreach (var root in new[] { Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles) })
            {
                string p = Path.Combine(root, "Microsoft", "Edge", "Application", "msedge.exe");
                if (File.Exists(p)) return p;
            }
            return null;
        }

        // ---- 窓の大きさを覚える(初めは 1280×800 くらいで真ん中 = C-2-20)
        string BoundsPath { get { return Path.Combine(friendDir, "window.json"); } }

        void RestoreBounds_()
        {
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(1280, 800);
            var j = Json.ReadFileOrNull(BoundsPath);
            if (j == null) return;
            var r = new Rectangle(Json.Int(j, "x", 0), Json.Int(j, "y", 0), Json.Int(j, "w", 1280), Json.Int(j, "h", 800));
            if (r.Width < 720 || r.Height < 480) return;
            foreach (var s in Screen.AllScreens)
                if (s.WorkingArea.IntersectsWith(new Rectangle(r.X + 40, r.Y + 10, 200, 40)))   // 見えない所(外したモニター)には出さない
                {
                    StartPosition = FormStartPosition.Manual;
                    Bounds = r;
                    if (Json.Bool(j, "max", false)) WindowState = FormWindowState.Maximized;
                    return;
                }
        }

        void SaveBounds()
        {
            if (!webview) return;
            try
            {
                var r = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                Directory.CreateDirectory(friendDir);
                File.WriteAllText(BoundsPath, "{\"x\":" + r.X + ",\"y\":" + r.Y + ",\"w\":" + r.Width + ",\"h\":" + r.Height + ",\"max\":" +
                                  (WindowState == FormWindowState.Maximized ? "true" : "false") + "}", new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException)) throw;
            }
        }

        // ---- タスクバーの数(●n。ITaskbarList3 の重ねる絵)
        protected override void WndProc(ref Message m)
        {
            if (m.Msg == TaskbarCreated)
            {
                taskbar = null;
                int n = undecided;
                undecided = -1;
                if (n >= 0) { undecided = n; SetBadge(n); }
            }
            base.WndProc(ref m);
        }

        void SetBadge(int n)
        {
            try
            {
                if (taskbar == null) { taskbar = (ITaskbarList3)new CTaskbarList(); taskbar.HrInit(); }
                IntPtr old = overlay;
                overlay = n > 0 ? MakeBadge(n) : IntPtr.Zero;
                taskbar.SetOverlayIcon(Handle, overlay, n > 0 ? "まだ決めていない物 " + n + " 本" : null);
                if (old != IntPtr.Zero) DestroyIcon(old);
            }
            catch (Exception ex)
            {
                if (!(ex is COMException || ex is InvalidCastException || ex is InvalidOperationException)) throw;
            }
        }

        static IntPtr MakeBadge(int n)
        {
            using (var bmp = new Bitmap(16, 16, System.Drawing.Imaging.PixelFormat.Format32bppArgb))
            using (var g = Graphics.FromImage(bmp))
            using (var f = new Font("Segoe UI", n > 9 ? 6.5f : 8f, FontStyle.Bold, GraphicsUnit.Point))
            {
                g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                g.Clear(Color.Transparent);
                g.FillEllipse(Brushes.Firebrick, 0, 0, 15, 15);
                var fmt = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
                g.DrawString(n > 99 ? "99" : n.ToString(), f, Brushes.White, new RectangleF(0, 0, 16, 16), fmt);
                return bmp.GetHicon();
            }
        }

        // アプリの絵(青い角丸に白い三角。アイコンの部品を持たないので描く)
        static Icon MakeAppIcon()
        {
            using (var bmp = new Bitmap(32, 32, System.Drawing.Imaging.PixelFormat.Format32bppArgb))
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                using (var path = new System.Drawing.Drawing2D.GraphicsPath())
                {
                    path.AddArc(2, 5, 8, 8, 180, 90); path.AddArc(22, 5, 8, 8, 270, 90);
                    path.AddArc(22, 19, 8, 8, 0, 90); path.AddArc(2, 19, 8, 8, 90, 90);
                    path.CloseFigure();
                    using (var b = new SolidBrush(Color.FromArgb(37, 99, 199))) g.FillPath(b, path);
                }
                g.FillPolygon(Brushes.White, new[] { new Point(13, 10), new Point(22, 16), new Point(13, 22) });
                return Icon.FromHandle(bmp.GetHicon());
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { tray.Dispose(); if (view != null) view.Dispose(); }
            if (overlay != IntPtr.Zero) { DestroyIcon(overlay); overlay = IntPtr.Zero; }
            base.Dispose(disposing);
        }

        [DllImport("kernel32.dll")]
        static extern uint SetThreadExecutionState(uint flags);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        static extern int RegisterWindowMessage(string name);
        [DllImport("user32.dll")]
        static extern bool DestroyIcon(IntPtr h);
    }

    // 同じオリジンの説明([?])を出す小さな窓。外へのリンクは既定のブラウザ
    public sealed class HelpForm : Form
    {
        readonly WebView2 view = new WebView2 { Dock = DockStyle.Fill };
        readonly string origin;

        public HelpForm(CoreWebView2Environment env, string uri, string origin, Icon icon)
        {
            this.origin = origin;
            Text = Rules.AppTitle + " の説明";
            Icon = icon;
            Size = new Size(820, 760);
            StartPosition = FormStartPosition.CenterParent;
            Controls.Add(view);
            Load += async delegate
            {
                try
                {
                    await view.EnsureCoreWebView2Async(env);
                    view.CoreWebView2.Settings.AreDevToolsEnabled = false;
                    view.CoreWebView2.NavigationStarting += (s, e) =>
                    {
                        if (e.Uri.StartsWith(this.origin + "/", StringComparison.OrdinalIgnoreCase)) return;
                        e.Cancel = true;
                        MainForm.OpenExternal(e.Uri);
                    };
                    view.CoreWebView2.NewWindowRequested += (s, e) => { e.Handled = true; MainForm.OpenExternal(e.Uri); };
                    view.CoreWebView2.DocumentTitleChanged += delegate { Text = view.CoreWebView2.DocumentTitle; };
                    view.CoreWebView2.Navigate(uri);
                }
                catch (Exception ex)
                {
                    Log.Write("説明の窓を開けませんでした: " + ex.Message);
                    Close();
                }
            };
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (keyData == Keys.Escape) { Close(); return true; }
            return base.ProcessCmdKey(ref msg, keyData);
        }
    }

    // 止めるときの確認(作業中・預かりがあるときだけ)。[裏で続ける](初めから選んだ状態)= Retry / [止めて閉じる] = Abort / ×・Esc = Cancel(何もしない)
    public sealed class ConfirmForm : Form
    {
        protected override bool ShowWithoutActivation { get { return MainForm.ShotDir != null; } }   // 写真を撮るときは前に出さない

        public ConfirmForm(string text, Icon icon)
        {
            Text = Rules.AppTitle;
            Icon = icon;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;
            Font = new Font("Yu Gothic UI", 10f);
            AutoScaleMode = AutoScaleMode.Dpi;
            var msg = new Label { Text = text, AutoSize = true, MaximumSize = new Size(480, 0), Location = new Point(20, 18) };
            var keep = new Button { Text = "裏で続ける", DialogResult = DialogResult.Retry, AutoSize = true, MinimumSize = new Size(140, 36) };
            var stop = new Button { Text = "止めて閉じる", DialogResult = DialogResult.Abort, AutoSize = true, MinimumSize = new Size(140, 36) };
            Controls.Add(msg);
            Controls.Add(keep);
            Controls.Add(stop);
            Size text_ = msg.GetPreferredSize(new Size(480, 0));
            int w = Math.Max(text_.Width, keep.PreferredSize.Width + stop.PreferredSize.Width + 12) + 40;
            int y = 18 + text_.Height + 20;
            stop.Location = new Point(w - 20 - stop.PreferredSize.Width, y);
            keep.Location = new Point(stop.Left - 12 - keep.PreferredSize.Width, y);
            ClientSize = new Size(w, y + Math.Max(keep.PreferredSize.Height, 36) + 18);
            AcceptButton = keep;
            CancelButton = null;
            Shown += delegate { keep.Focus(); };
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (keyData == Keys.Escape) { DialogResult = DialogResult.Cancel; return true; }
            return base.ProcessCmdKey(ref msg, keyData);
        }
    }

    // ITaskbarList3 のうち SetOverlayIcon まで(COM は並びが大事 = ITaskbarList・ITaskbarList2 の分も順に書く)
    [ComImport, Guid("ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ITaskbarList3
    {
        [PreserveSig] int HrInit();
        [PreserveSig] int AddTab(IntPtr hwnd);
        [PreserveSig] int DeleteTab(IntPtr hwnd);
        [PreserveSig] int ActivateTab(IntPtr hwnd);
        [PreserveSig] int SetActiveAlt(IntPtr hwnd);
        [PreserveSig] int MarkFullscreenWindow(IntPtr hwnd, [MarshalAs(UnmanagedType.Bool)] bool fullscreen);
        [PreserveSig] int SetProgressValue(IntPtr hwnd, ulong completed, ulong total);
        [PreserveSig] int SetProgressState(IntPtr hwnd, int flags);
        [PreserveSig] int RegisterTab(IntPtr hwndTab, IntPtr hwndMdi);
        [PreserveSig] int UnregisterTab(IntPtr hwndTab);
        [PreserveSig] int SetTabOrder(IntPtr hwndTab, IntPtr hwndInsertBefore);
        [PreserveSig] int SetTabActive(IntPtr hwndTab, IntPtr hwndMdi, uint reserved);
        [PreserveSig] int ThumbBarAddButtons(IntPtr hwnd, uint count, IntPtr buttons);
        [PreserveSig] int ThumbBarUpdateButtons(IntPtr hwnd, uint count, IntPtr buttons);
        [PreserveSig] int ThumbBarSetImageList(IntPtr hwnd, IntPtr himl);
        [PreserveSig] int SetOverlayIcon(IntPtr hwnd, IntPtr hIcon, [MarshalAs(UnmanagedType.LPWStr)] string description);
    }

    [ComImport, Guid("56FDF344-FD6D-11d0-958A-006097C9A090"), ClassInterface(ClassInterfaceType.None)]
    class CTaskbarList { }
}
