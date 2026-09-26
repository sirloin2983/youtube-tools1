// 設定の画面・色の追加/編集の画面・呼び出しのキーを受け取る欄・コピーしたときの小さな知らせ
using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Windows.Forms;

namespace HoloColors
{
    // 押したキーの組み合わせをそのまま受け取る欄。フォーカスがある間は、今の呼び出しのキーを外しておく(同じキーを押しても受け取れるように)
    public class HotkeyBox : TextBox
    {
        public int Mods, Key;
        public event Action Captured;

        public HotkeyBox()
        {
            ReadOnly = true;
            BackColor = Color.White;
            ShortcutsEnabled = false;
            TextAlign = HorizontalAlignment.Center;
        }

        public void SetValue(int mods, int key)
        {
            Mods = mods;
            Key = key;
            Text = Hotkey.Format(mods, key);
        }

        protected override bool IsInputKey(Keys keyData)
        {
            return true;   // Tab・矢印・Enter も受け取る
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            // Alt の組み合わせがメニューのキーとして消えないように、ここで受ける
            if ((keyData & Keys.Alt) == Keys.Alt || keyData == Keys.F10)
            {
                var e = new KeyEventArgs(keyData);
                OnKeyDown(e);
                return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            e.Handled = e.SuppressKeyPress = true;
            int mods = 0;
            if (e.Control) mods |= Hotkey.MOD_CONTROL;
            if (e.Alt) mods |= Hotkey.MOD_ALT;
            if (e.Shift) mods |= Hotkey.MOD_SHIFT;
            if (Native.WinKeyDown()) mods |= Hotkey.MOD_WIN;
            int vk = (int)e.KeyCode;
            if (Hotkey.IsModifierKey(vk))
            {
                Text = Hotkey.Format(mods, 0) + " + …";
                return;
            }
            if (e.KeyCode == Keys.Escape && mods == 0 || e.KeyCode == Keys.Tab && mods == 0)
            {
                Text = Hotkey.Format(Mods, Key);
                if (e.KeyCode == Keys.Tab) Parent.SelectNextControl(this, true, true, true, true);
                return;
            }
            Mods = mods;
            Key = vk;
            Text = Hotkey.Format(mods, vk);
            if (Captured != null) Captured();
        }

        protected override void OnKeyUp(KeyEventArgs e)
        {
            e.Handled = true;
            if (Text.EndsWith("…")) Text = Hotkey.Format(Mods, Key);
        }

        protected override void OnKeyPress(KeyPressEventArgs e)
        {
            e.Handled = true;
        }
    }

    public class SettingsForm : Form
    {
        readonly AppController app;
        readonly HotkeyBox hotkey = new HotkeyBox();
        readonly Label hotkeyNote = new Label();
        readonly CheckBox closeAfter = new CheckBox();
        readonly CheckBox includeHash = new CheckBox();
        readonly CheckBox autostart = new CheckBox();
        readonly Label autostartNote = new Label();
        bool loading;

        public SettingsForm(AppController app)
        {
            this.app = app;
            Text = AppInfo.Name + " の設定";
            Font = new Font("Yu Gothic UI", 9f);
            AutoScaleMode = AutoScaleMode.Font;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            ShowInTaskbar = false;
            TopMost = true;
            StartPosition = FormStartPosition.CenterScreen;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Icon = AppIcon.Load(SystemInformation.SmallIconSize);

            var t = new TableLayoutPanel { AutoSize = true, ColumnCount = 2, Padding = new Padding(14), Dock = DockStyle.Fill };
            t.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            t.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));

            t.Controls.Add(new Label { Text = "呼び出すキー", AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(0, 6, 10, 0) }, 0, 0);
            var hk = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0) };
            hotkey.Width = 190;
            hotkey.Enter += (s, e) => { app.SuspendHotkey(); hotkeyNote.Text = "組み合わせを押してください(Esc でやめる)"; hotkeyNote.ForeColor = Color.FromArgb(80, 80, 92); };
            hotkey.Leave += (s, e) => { app.ResumeHotkey(); ShowHotkeyState(); };
            hotkey.Captured += OnHotkeyCaptured;
            var reset = new Button { Text = "元に戻す", AutoSize = true };
            reset.Click += (s, e) =>
            {
                hotkey.SetValue(Hotkey.DefaultMods, Hotkey.DefaultKey);
                OnHotkeyCaptured();
            };
            hk.Controls.Add(hotkey);
            hk.Controls.Add(reset);
            t.Controls.Add(hk, 1, 0);
            hotkeyNote.AutoSize = true;
            hotkeyNote.MaximumSize = new Size(330, 0);
            hotkeyNote.Margin = new Padding(3, 2, 0, 10);
            t.Controls.Add(hotkeyNote, 1, 1);

            closeAfter.Text = "コピーしたら窓を閉じる";
            closeAfter.AutoSize = true;
            closeAfter.CheckedChanged += (s, e) => { if (!loading) app.SetCloseAfterCopy(closeAfter.Checked); };
            t.Controls.Add(closeAfter, 1, 2);

            includeHash.Text = "先頭に # を付けてコピーする(#FF6699 / FF6699)";
            includeHash.AutoSize = true;
            includeHash.CheckedChanged += (s, e) => { if (!loading) app.SetIncludeHash(includeHash.Checked); };
            t.Controls.Add(includeHash, 1, 3);

            autostart.Text = "Windows にサインインしたら裏で起動しておく";
            autostart.AutoSize = true;
            autostart.Margin = new Padding(3, 10, 3, 0);
            autostart.CheckedChanged += (s, e) => { if (!loading) OnAutostart(); };
            t.Controls.Add(autostart, 1, 4);
            autostartNote.AutoSize = true;
            autostartNote.MaximumSize = new Size(330, 0);
            autostartNote.ForeColor = Color.FromArgb(110, 110, 120);
            autostartNote.Margin = new Padding(20, 0, 0, 8);
            t.Controls.Add(autostartNote, 1, 5);

            var data = new LinkLabel { Text = "作業データのフォルダを開く(自分で足した色・設定)", AutoSize = true, Margin = new Padding(3, 10, 3, 0) };
            data.LinkClicked += (s, e) => OpenFolder(app.Store.Dir);
            t.Controls.Add(data, 1, 6);
            var info = new Label
            {
                Text = "メンバーの色: " + app.PaletteSummary + "\n版 " + AppInfo.Version,
                AutoSize = true,
                ForeColor = Color.FromArgb(110, 110, 120),
                Margin = new Padding(3, 8, 3, 8),
            };
            t.Controls.Add(info, 1, 7);

            var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill, Margin = new Padding(0, 6, 0, 0) };
            var close = new Button { Text = "閉じる", AutoSize = true, DialogResult = DialogResult.OK };
            var quit = new Button { Text = "アプリを終了", AutoSize = true };
            quit.Click += (s, e) => { Close(); app.Quit(); };
            buttons.Controls.Add(close);
            buttons.Controls.Add(quit);
            t.Controls.Add(buttons, 0, 8);
            t.SetColumnSpan(buttons, 2);
            Controls.Add(t);
            AcceptButton = close;
            CancelButton = close;

            loading = true;
            hotkey.SetValue(app.Store.Settings.HotkeyMods, app.Store.Settings.HotkeyKey);
            closeAfter.Checked = app.Store.Settings.CloseAfterCopy;
            includeHash.Checked = app.Store.Settings.IncludeHash;
            autostart.Checked = app.Autostart.Enabled;
            loading = false;
            ShowHotkeyState();
            ShowAutostartState();
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            ActiveControl = closeAfter;   // 開いた直後に呼び出しのキーの欄へ入らないように
        }

        void OnHotkeyCaptured()
        {
            if (!Hotkey.IsValid(hotkey.Mods, hotkey.Key))
            {
                hotkeyNote.Text = "Ctrl・Alt・Win のどれかと一緒に押してください(F1〜F12 などは単独でも可)";
                hotkeyNote.ForeColor = Color.FromArgb(190, 30, 30);
                return;
            }
            string err = app.ChangeHotkey(hotkey.Mods, hotkey.Key);
            if (err != null)
            {
                hotkeyNote.Text = err;
                hotkeyNote.ForeColor = Color.FromArgb(190, 30, 30);
                hotkey.SetValue(app.Store.Settings.HotkeyMods, app.Store.Settings.HotkeyKey);
                return;
            }
            hotkeyNote.Text = "「" + Hotkey.Format(hotkey.Mods, hotkey.Key) + "」にしました";
            hotkeyNote.ForeColor = Color.FromArgb(20, 120, 60);
        }

        void ShowHotkeyState()
        {
            if (app.HotkeyActive)
            {
                hotkeyNote.Text = "どのアプリを使っているときでも、このキーで一覧が開きます";
                hotkeyNote.ForeColor = Color.FromArgb(110, 110, 120);
            }
            else
            {
                hotkeyNote.Text = "このキーは他のアプリが使っていて登録できませんでした。欄を押して別の組み合わせにしてください";
                hotkeyNote.ForeColor = Color.FromArgb(190, 30, 30);
            }
        }

        void OnAutostart()
        {
            try
            {
                app.Autostart.Set(autostart.Checked);
            }
            catch (Exception ex)
            {
                Log.Write("autostart: " + ex);
                MessageBox.Show(this, "設定できませんでした: " + ex.Message, AppInfo.Name, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                loading = true;
                autostart.Checked = app.Autostart.Enabled;
                loading = false;
            }
            ShowAutostartState();
        }

        void ShowAutostartState()
        {
            if (app.Autostart.PointsElsewhere)
                autostartNote.Text = "登録は別の場所の HoloColors.exe を指しています(フォルダを動かしたとき)。いったん外して付け直すと、この exe になります";
            else if (app.Autostart.Enabled)
                autostartNote.Text = "次からは起動の操作は要りません。やめるときはここを外します";
            else
                autostartNote.Text = "外しているときは、使う前に HoloColors.exe をダブルクリックして起動します";
        }

        public static void OpenFolder(string dir)
        {
            try
            {
                Directory.CreateDirectory(dir);
                Process.Start("explorer.exe", "\"" + dir + "\"");
            }
            catch (Exception ex)
            {
                Log.Write("open folder: " + ex);
            }
        }
    }

    public class EditColorForm : Form
    {
        readonly TextBox name = new TextBox();
        readonly TextBox hex = new TextBox();
        readonly Panel preview = new Panel();
        readonly Label error = new Label();
        public string ResultName, ResultHex;

        public EditColorForm(string title, string initialName, string initialHex)
        {
            Text = title;
            Font = new Font("Yu Gothic UI", 9f);
            AutoScaleMode = AutoScaleMode.Font;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            ShowInTaskbar = false;
            TopMost = true;
            StartPosition = FormStartPosition.CenterParent;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;

            var t = new TableLayoutPanel { AutoSize = true, ColumnCount = 3, Padding = new Padding(14), Dock = DockStyle.Fill };
            t.Controls.Add(new Label { Text = "名前", AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(0, 6, 10, 0) }, 0, 0);
            name.Width = 220;
            name.MaxLength = Store.MaxName;
            name.Text = initialName ?? "";
            t.Controls.Add(name, 1, 0);
            t.SetColumnSpan(name, 2);

            t.Controls.Add(new Label { Text = "カラーコード", AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(0, 6, 10, 0) }, 0, 1);
            hex.Width = 110;
            hex.Font = new Font("Consolas", 10f);
            hex.Text = initialHex ?? "";
            hex.TextChanged += (s, e) => UpdatePreview();
            t.Controls.Add(hex, 1, 1);
            var pick = new Button { Text = "色を選ぶ…", AutoSize = true };
            pick.Click += (s, e) => PickColor();
            t.Controls.Add(pick, 2, 1);

            preview.Size = new Size(220, 34);
            preview.Margin = new Padding(3, 8, 3, 4);
            preview.Paint += PaintPreview;
            t.Controls.Add(preview, 1, 2);
            t.SetColumnSpan(preview, 2);

            error.AutoSize = true;
            error.ForeColor = Color.FromArgb(190, 30, 30);
            error.MaximumSize = new Size(320, 0);
            t.Controls.Add(error, 0, 3);
            t.SetColumnSpan(error, 3);

            var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill };
            var cancel = new Button { Text = "キャンセル", AutoSize = true, DialogResult = DialogResult.Cancel };
            var ok = new Button { Text = "保存", AutoSize = true };
            ok.Click += (s, e) => Save();
            buttons.Controls.Add(cancel);
            buttons.Controls.Add(ok);
            t.Controls.Add(buttons, 0, 4);
            t.SetColumnSpan(buttons, 3);
            Controls.Add(t);
            AcceptButton = ok;
            CancelButton = cancel;
            Icon = AppIcon.Load(SystemInformation.SmallIconSize);
        }

        public TextBox NameBox { get { return name; } }
        public TextBox HexBox { get { return hex; } }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            UpdatePreview();
            (name.Text.Length == 0 ? name : hex).Focus();
        }

        void UpdatePreview()
        {
            preview.Invalidate();
        }

        void PaintPreview(object sender, PaintEventArgs e)
        {
            string h;
            var r = new Rectangle(0, 0, preview.Width - 1, preview.Height - 1);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            if (HexColor.TryNormalize(hex.Text, out h))
            {
                Color c = HexColor.ToColor(h);
                using (var b = new SolidBrush(c)) e.Graphics.FillRectangle(b, r);
                TextRenderer.DrawText(e.Graphics, (name.Text.Trim().Length > 0 ? name.Text.Trim() + "  " : "") + h, Font, r,
                    HexColor.PrefersDarkText(c) ? Color.Black : Color.White, TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
            }
            else
            {
                using (var b = new HatchBrush(HatchStyle.BackwardDiagonal, Color.FromArgb(220, 220, 226), Color.White)) e.Graphics.FillRectangle(b, r);
                TextRenderer.DrawText(e.Graphics, "例: #FF6699", Font, r, Color.Gray, TextFormatFlags.VerticalCenter | TextFormatFlags.HorizontalCenter);
            }
            using (var p = new Pen(Color.FromArgb(200, 200, 208))) e.Graphics.DrawRectangle(p, r);
        }

        void PickColor()
        {
            using (var dlg = new ColorDialog { FullOpen = true, AnyColor = true })
            {
                string h;
                if (HexColor.TryNormalize(hex.Text, out h)) dlg.Color = HexColor.ToColor(h);
                if (dlg.ShowDialog(this) == DialogResult.OK) hex.Text = HexColor.FromColor(dlg.Color);
            }
        }

        void Save()
        {
            string h;
            string err = Store.Validate(name.Text, hex.Text, out h);
            if (err != null)
            {
                error.Text = err;
                return;
            }
            ResultName = name.Text.Trim();
            ResultHex = h;
            DialogResult = DialogResult.OK;
        }
    }

    // コピーしたときに、マウスの横へ少しだけ出す知らせ。前面の窓を奪わない(すぐ Ctrl+V できるように)・クリックは下へ通す
    public class Toast : Form
    {
        readonly Timer timer = new Timer { Interval = 1300 };
        string message = "";
        Color swatch;

        public Toast()
        {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            Font = new Font("Yu Gothic UI", 9.5f);
            BackColor = Color.FromArgb(34, 34, 40);
            timer.Tick += (s, e) => { timer.Stop(); Hide(); };
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint, true);
        }

        protected override bool ShowWithoutActivation { get { return true; } }

        protected override CreateParams CreateParams
        {
            get
            {
                var cp = base.CreateParams;
                cp.ExStyle |= Native.WS_EX_TOOLWINDOW | Native.WS_EX_NOACTIVATE | Native.WS_EX_TOPMOST | Native.WS_EX_TRANSPARENT;
                return cp;
            }
        }

        public void Flash(string text, string hex)
        {
            message = text;
            swatch = HexColor.ToColor(hex);
            Size sz = TextRenderer.MeasureText(text, Font);
            int pad = (int)(8 * DeviceDpi / 96f), sw = (int)(16 * DeviceDpi / 96f);
            Size = new Size(sz.Width + sw + pad * 3, Math.Max(sz.Height, sw) + pad * 2);
            Point p = Cursor.Position;
            Rectangle wa = Screen.FromPoint(p).WorkingArea;
            int x = Math.Min(p.X + 16, wa.Right - Width), y = Math.Min(p.Y + 20, wa.Bottom - Height);
            Location = new Point(Math.Max(wa.Left, x), Math.Max(wa.Top, y));
            timer.Stop();
            Show();
            Invalidate();
            timer.Start();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            int pad = (int)(8 * DeviceDpi / 96f), sw = (int)(16 * DeviceDpi / 96f);
            var r = new Rectangle(pad, (Height - sw) / 2, sw, sw);
            using (var b = new SolidBrush(swatch)) e.Graphics.FillRectangle(b, r);
            using (var p = new Pen(Color.FromArgb(120, 255, 255, 255))) e.Graphics.DrawRectangle(p, r);
            TextRenderer.DrawText(e.Graphics, message, Font, new Rectangle(pad * 2 + sw, 0, Width - pad * 2 - sw, Height), Color.White,
                TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.NoPrefix);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) timer.Dispose();
            base.Dispose(disposing);
        }
    }
}
