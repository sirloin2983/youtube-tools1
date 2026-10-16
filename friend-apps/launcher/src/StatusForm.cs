// 状態の窓(窓を閉じたのに仕事が続いているときだけ出す小さな窓)と、タスクバーの縮小版のツールバー [開く] [止める](ITaskbarList3)
using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using FriendApps;

namespace FriendInbox
{
    public sealed class StatusForm : Form
    {
        const int WM_COMMAND = 0x111, THBN_CLICKED = 0x1800, IdOpen = 1, IdStop = 2;
        static readonly int TaskbarCreated = RegisterWindowMessage("TaskbarButtonCreated");
        readonly Action openWindow, stopNow;
        readonly Label text = new Label();
        readonly Button btnOpen = new Button(), btnStop = new Button();
        ITaskbarList3 taskbar;
        IntPtr iconOpen, iconStop;
        int recording;
        bool allowClose;

        public StatusForm(Action openWindow, Action stopNow)
        {
            this.openWindow = openWindow;
            this.stopNow = stopNow;
            Text = "受信箱(裏で動いています)";
            ClientSize = new Size(380, 120);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = true;
            ShowInTaskbar = true;
            StartPosition = FormStartPosition.CenterScreen;
            text.SetBounds(16, 14, 348, 48);
            text.Text = "";
            btnOpen.Text = "窓を開く";
            btnOpen.SetBounds(16, 72, 150, 32);
            btnOpen.Click += delegate { this.openWindow(); };
            btnStop.Text = "今すぐ止めて閉じる";
            btnStop.SetBounds(180, 72, 184, 32);
            btnStop.Click += delegate { this.stopNow(); };
            Controls.AddRange(new Control[] { text, btnOpen, btnStop });
        }

        protected override bool ShowWithoutActivation { get { return true; } }   // 作業中の人の入力を奪わない

        public void AllowClose() { allowClose = true; }

        public void ShowStatus(FriendState st)
        {
            recording = st.Recording;
            text.Text = "窓は閉じていますが、仕事が続いています。\r\n" + st.Label;
            if (!Visible) Show();
        }

        public void HideStatus()
        {
            if (Visible) Hide();
        }

        // ×: 録画中は最小化と同じ・録画が無ければ今すぐ止めて閉じる。確認は出さない
        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!allowClose && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                if (Watch.CloseStopsNow(recording)) stopNow(); else WindowState = FormWindowState.Minimized;
            }
            base.OnFormClosing(e);
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == TaskbarCreated) AddThumbButtons();
            else if (m.Msg == WM_COMMAND && ((int)(m.WParam.ToInt64() >> 16) & 0xFFFF) == THBN_CLICKED)
            {
                int id = (int)(m.WParam.ToInt64() & 0xFFFF);
                if (id == IdOpen) openWindow(); else if (id == IdStop) stopNow();
            }
            base.WndProc(ref m);
        }

        // 縮小版のツールバー。失敗しても状態の窓のボタンがあるので黙って続ける
        void AddThumbButtons()
        {
            try
            {
                if (taskbar == null)
                {
                    taskbar = (ITaskbarList3)new CTaskbarList();
                    taskbar.HrInit();
                    iconOpen = MakeIcon(false);
                    iconStop = MakeIcon(true);
                }
                var b = new ThumbButton[2];
                b[0] = Button(IdOpen, iconOpen, "開く");
                b[1] = Button(IdStop, iconStop, "止める");
                taskbar.ThumbBarAddButtons(Handle, 2, b);
            }
            catch (Exception ex)
            {
                if (!(ex is COMException || ex is InvalidCastException || ex is InvalidOperationException)) throw;
                Log.Write("縮小版のツールバーを付けられませんでした: " + ex.Message);
            }
        }

        static ThumbButton Button(int id, IntPtr icon, string tip)
        {
            return new ThumbButton { dwMask = 2 | 4 | 8, iId = (uint)id, hIcon = icon, szTip = tip, dwFlags = 0 };   // THB_ICON | THB_TOOLTIP | THB_FLAGS
        }

        // 16x16 の絵(開く = 窓の形・止める = 赤い四角)
        static IntPtr MakeIcon(bool stop)
        {
            using (var bmp = new Bitmap(16, 16, System.Drawing.Imaging.PixelFormat.Format32bppArgb))
            using (var g = Graphics.FromImage(bmp))
            {
                g.Clear(Color.Transparent);
                if (stop) g.FillRectangle(Brushes.Firebrick, 3, 3, 10, 10);
                else
                {
                    using (var pen = new Pen(Color.SteelBlue, 2)) g.DrawRectangle(pen, 2, 3, 11, 9);
                    g.FillRectangle(Brushes.SteelBlue, 2, 3, 12, 3);
                }
                return bmp.GetHicon();
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (iconOpen != IntPtr.Zero) DestroyIcon(iconOpen);
            if (iconStop != IntPtr.Zero) DestroyIcon(iconStop);
            iconOpen = iconStop = IntPtr.Zero;
            base.Dispose(disposing);
        }

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        static extern int RegisterWindowMessage(string name);

        [DllImport("user32.dll")]
        static extern bool DestroyIcon(IntPtr h);
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct ThumbButton
    {
        public uint dwMask, iId, iBitmap;
        public IntPtr hIcon;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string szTip;
        public uint dwFlags;
    }

    // ITaskbarList3 のうち ThumbBarAddButtons まで(COM は並びが大事 = ITaskbarList・ITaskbarList2 の分も順に書く)
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
        [PreserveSig] int ThumbBarAddButtons(IntPtr hwnd, uint count, [MarshalAs(UnmanagedType.LPArray)] ThumbButton[] buttons);
    }

    [ComImport, Guid("56FDF344-FD6D-11d0-958A-006097C9A090"), ClassInterface(ClassInterfaceType.None)]
    class CTaskbarList { }
}
