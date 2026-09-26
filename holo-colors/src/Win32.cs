// Windows の API(呼び出しのキー・前面の窓・起動時の常駐)
using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

namespace HoloColors
{
    public static class Native
    {
        public const int WM_HOTKEY = 0x0312;
        public const int MOD_NOREPEAT = 0x4000;
        public const int WS_EX_TOOLWINDOW = 0x80, WS_EX_TOPMOST = 0x8, WS_EX_NOACTIVATE = 0x08000000, WS_EX_TRANSPARENT = 0x20;
        public const int EM_SETCUEBANNER = 0x1501;
        public static readonly IntPtr HWND_BROADCAST = new IntPtr(0xffff);
        public const int ASFW_ANY = -1;

        [DllImport("user32.dll", SetLastError = true)]
        public static extern bool RegisterHotKey(IntPtr hWnd, int id, int fsModifiers, int vk);

        [DllImport("user32.dll")]
        public static extern bool UnregisterHotKey(IntPtr hWnd, int id);

        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern bool IsWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern bool AllowSetForegroundWindow(int dwProcessId);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern int RegisterWindowMessage(string lpString);

        [DllImport("user32.dll")]
        public static extern bool PostMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, string lParam);

        [DllImport("user32.dll")]
        public static extern short GetKeyState(int nVirtKey);

        [DllImport("user32.dll")]
        public static extern IntPtr GetAncestor(IntPtr hwnd, int flags);

        public static bool WinKeyDown()
        {
            return (GetKeyState((int)Keys.LWin) & 0x8000) != 0 || (GetKeyState((int)Keys.RWin) & 0x8000) != 0;
        }

        public static void SetCueBanner(TextBox box, string text)
        {
            SendMessage(box.Handle, EM_SETCUEBANNER, new IntPtr(1), text);
        }
    }

    // 呼び出しのキーと、2つ目の起動からの「開いて」「終わって」を受ける見えない窓。
    // フォームの窓は作り直されることがある(そのとき登録が消える)ので、専用の窓で受ける。
    public class MessageWindow : NativeWindow, IDisposable
    {
        const int HotkeyId = 0x4843;   // "HC"
        public event Action<IntPtr> HotkeyPressed;   // 押されたときに前面だった窓
        public event Action ShowRequested;
        public event Action QuitRequested;
        readonly int showMsg, quitMsg;
        bool registered;
        public int Mods { get; private set; }
        public int Key { get; private set; }

        public MessageWindow(string instanceKey)
        {
            showMsg = Native.RegisterWindowMessage("YTT.HoloColors.Show." + instanceKey);
            quitMsg = Native.RegisterWindowMessage("YTT.HoloColors.Quit." + instanceKey);
            // 親の無い見えない窓(メッセージ専用の窓は HWND_BROADCAST を受けられないので使わない)
            CreateHandle(new CreateParams { Caption = "HoloColors.Messages", ExStyle = Native.WS_EX_TOOLWINDOW });
        }

        public bool Registered { get { return registered; } }

        // 成功したら true。失敗したら(他のアプリが使っている)登録なしのまま
        public bool Register(int mods, int vk)
        {
            Unregister();
            Mods = mods;
            Key = vk;
            registered = Native.RegisterHotKey(Handle, HotkeyId, mods | Native.MOD_NOREPEAT, vk);
            return registered;
        }

        public void Unregister()
        {
            if (registered) Native.UnregisterHotKey(Handle, HotkeyId);
            registered = false;
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == Native.WM_HOTKEY && m.WParam.ToInt32() == HotkeyId)
            {
                IntPtr fg = Native.GetForegroundWindow();
                if (HotkeyPressed != null) HotkeyPressed(fg);
                return;
            }
            if (m.Msg == showMsg && showMsg != 0)
            {
                if (ShowRequested != null) ShowRequested();
                return;
            }
            if (m.Msg == quitMsg && quitMsg != 0)
            {
                if (QuitRequested != null) QuitRequested();
                return;
            }
            base.WndProc(ref m);
        }

        public static void Broadcast(string instanceKey, bool quit)
        {
            int msg = Native.RegisterWindowMessage((quit ? "YTT.HoloColors.Quit." : "YTT.HoloColors.Show.") + instanceKey);
            Native.AllowSetForegroundWindow(Native.ASFW_ANY);   // 動いているほうが前面に出られるように
            Native.PostMessage(Native.HWND_BROADCAST, msg, IntPtr.Zero, IntPtr.Zero);
        }

        public void Dispose()
        {
            Unregister();
            DestroyHandle();
        }
    }

    // Windows にサインインしたときに裏で起動する(HKCU の Run。自分のユーザーだけ・管理者の権限は要らない)
    public class Autostart
    {
        public const string DefaultKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        public const string ValueName = "YouTubeTools.HoloColors";
        readonly string keyPath;
        readonly string command;

        public Autostart(string keyPath, string exePath, string extraArgs)
        {
            this.keyPath = keyPath;
            command = "\"" + exePath + "\" --hidden" + (string.IsNullOrEmpty(extraArgs) ? "" : " " + extraArgs);
        }

        public string Command { get { return command; } }

        public string Current()
        {
            using (var k = Registry.CurrentUser.OpenSubKey(keyPath, false))
                return k == null ? null : k.GetValue(ValueName) as string;
        }

        public bool Enabled { get { return Current() != null; } }

        // 登録はあるが、別の場所の exe を指している(フォルダを動かした)
        public bool PointsElsewhere
        {
            get
            {
                string c = Current();
                return c != null && !string.Equals(c, command, StringComparison.OrdinalIgnoreCase);
            }
        }

        public void Set(bool on)
        {
            using (var k = Registry.CurrentUser.CreateSubKey(keyPath))
            {
                if (on) k.SetValue(ValueName, command, RegistryValueKind.String);
                else if (k.GetValue(ValueName) != null) k.DeleteValue(ValueName, false);
            }
        }
    }

    public static class AppIcon
    {
        // exe に埋め込んだ app.ico から、欲しい大きさのものを選ぶ
        public static Icon Load(Size size)
        {
            using (Stream s = typeof(AppIcon).Assembly.GetManifestResourceStream("HoloColors.app.ico"))
                return s == null ? (Icon)SystemIcons.Application.Clone() : new Icon(s, size);
        }
    }

    public static class Instance
    {
        // 作業データの場所ごとに1つだけ動かす(テストは別の場所で動かすので、普段のものとぶつからない)
        public static string Key(string dataDir)
        {
            using (var sha = SHA1.Create())
            {
                byte[] h = sha.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(dataDir).TrimEnd('\\').ToLowerInvariant()));
                return BitConverter.ToString(h, 0, 6).Replace("-", "");
            }
        }
    }
}
