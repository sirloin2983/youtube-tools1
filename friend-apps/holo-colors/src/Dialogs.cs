// 設定の画面・色の追加/編集の画面・呼び出しのキーを受け取る欄・コピーしたときの小さな知らせ
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace HoloColors
{
    // 画面で共通に使うフォント・アイコン・大きさ(開くたびに作って捨てないように1つを使い回す)。
    // DPI はシステムの値(app.manifest で dpiAware = システムに合わせる)。Control.DeviceDpi は .NET 4.7 からなので使わない
    public static class Ui
    {
        public static readonly Font Normal = new Font("Yu Gothic UI", 9f);
        public static readonly Font Search = new Font("Yu Gothic UI", 11f);
        public static readonly Font Mono = new Font("Consolas", 10f);
        public static readonly Font Toast = new Font("Yu Gothic UI", 9.5f);
        public static readonly float Scale = SystemScale();
        public static readonly Color Muted = Color.FromArgb(110, 110, 120), Error = Color.FromArgb(190, 30, 30), Ok = Color.FromArgb(20, 120, 60);
        // 1行の文字(左寄せ・縦は中央・はみ出したら … にする)
        public const TextFormatFlags LeftText = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine;
        static Icon small;

        static float SystemScale()
        {
            using (var g = Graphics.FromHwnd(IntPtr.Zero)) return g.DpiX / 96f;
        }

        // 96 DPI での大きさ → この画面での大きさ
        public static int Px(int v)
        {
            return (int)Math.Round(v * Scale);
        }

        public static Size Px(int w, int h)
        {
            return new Size(Px(w), Px(h));
        }

        public static Icon SmallIcon
        {
            get { return small ?? (small = AppIcon.Load(SystemInformation.SmallIconSize)); }
        }

        // 設定・入力の画面の共通の形(大きさは中身に合わせる・タスクバーには出さない)
        public static void StyleDialog(Form f, FormStartPosition start)
        {
            f.Font = Normal;
            f.AutoScaleMode = AutoScaleMode.None;   // 大きさは Px で DPI に合わせる
            f.FormBorderStyle = FormBorderStyle.FixedDialog;
            f.MaximizeBox = f.MinimizeBox = false;
            f.ShowInTaskbar = false;
            f.StartPosition = start;
            f.AutoSize = true;
            f.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            f.Icon = SmallIcon;
        }

        public static Button Btn(string text)
        {
            return new Button { Text = text, AutoSize = true };
        }

        // 入力欄の左の名札
        public static Label FieldLabel(string text, AnchorStyles anchor, int right)
        {
            return new Label { Text = text, AutoSize = true, Anchor = anchor, Margin = new Padding(0, 6, right, 0) };
        }

        // 欄の下の知らせ(色は Muted / Error など。maxWidth は 96 DPI の px で、超えたら折り返す)
        public static Label Note(Color color, int maxWidth)
        {
            return new Label { AutoSize = true, ForeColor = color, MaximumSize = new Size(Px(maxWidth), 0) };
        }

        // 下の段の右寄せのボタン(先に足したものが右端)
        public static FlowLayoutPanel ButtonRow(Padding margin, params Control[] buttons)
        {
            var row = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill, Margin = margin };
            row.Controls.AddRange(buttons);
            return row;
        }

        // 色の画面で選んで、カラーコードの欄に入れる
        public static void PickColor(IWin32Window owner, TextBox hexBox)
        {
            using (var dlg = new ColorDialog { FullOpen = true, AnyColor = true })
            {
                string h;
                if (HexColor.TryNormalize(hexBox.Text, out h)) dlg.Color = HexColor.ToColor(h);
                if (dlg.ShowDialog(owner) == DialogResult.OK) hexBox.Text = HexColor.FromColor(dlg.Color);
            }
        }
    }

    // 押したキーの組み合わせをそのまま受け取る欄。フォーカスがある間は、今の呼び出しのキーを外しておく(同じキーを押しても受け取れるように)
    public class HotkeyBox : TextBox
    {
        public int Mods, Key;
        public event Action Captured;
        public event Action<string> Rejected;   // 使えない組み合わせを押した(理由)。欄の表示は今のキーのまま

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
            // キーボードだけでも欄から出られるように: Tab / Shift+Tab / Enter で移る、Esc は入力をやめる(もう一度で閉じる)
            if ((e.KeyCode == Keys.Tab && (mods == 0 || mods == Hotkey.MOD_SHIFT)) || (e.KeyCode == Keys.Return && mods == 0))
            {
                Text = Hotkey.Format(Mods, Key);
                Parent.SelectNextControl(this, mods != Hotkey.MOD_SHIFT, true, true, true);
                return;
            }
            if (e.KeyCode == Keys.Escape && mods == 0)
            {
                if (Text == Hotkey.Format(Mods, Key)) { var f = FindForm(); if (f != null) f.Close(); }
                else Text = Hotkey.Format(Mods, Key);
                return;
            }
            string problem = Hotkey.Problem(mods, vk);
            if (problem != null)
            {
                Text = Hotkey.Format(Mods, Key);
                if (Rejected != null) Rejected(problem);
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
        readonly Label hotkeyNote = Ui.Note(Ui.Muted, 380);
        readonly CheckBox closeAfter = new CheckBox();
        readonly CheckBox includeHash = new CheckBox();
        readonly CheckBox onTop = new CheckBox();
        readonly CheckBox autostart = new CheckBox();
        readonly Label autostartNote = Ui.Note(Ui.Muted, 380);
        readonly LinkLabel fixAutostart = new LinkLabel();
        bool loading;

        public SettingsForm(AppController app)
        {
            this.app = app;
            Text = AppInfo.Name + " の設定";
            Ui.StyleDialog(this, FormStartPosition.CenterScreen);

            var t = new TableLayoutPanel { AutoSize = true, ColumnCount = 2, Padding = new Padding(14), Dock = DockStyle.Fill };
            t.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            t.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));

            t.Controls.Add(Ui.FieldLabel("呼び出すキー", AnchorStyles.Left, 10), 0, 0);
            var hk = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0) };
            hotkey.Width = Ui.Px(200);
            hotkey.Enter += (s, e) => { app.SuspendHotkey(); SetHotkeyNote("使いたい組み合わせを押してください(Esc でやめる)", Color.FromArgb(80, 80, 92)); };
            hotkey.Leave += (s, e) => { app.ResumeHotkey(); ShowHotkeyState(); };
            hotkey.Captured += OnHotkeyCaptured;
            hotkey.Rejected += msg => SetHotkeyNote(msg + "。別の組み合わせを押してください", Ui.Error);
            var reset = Ui.Btn("元に戻す");
            reset.Click += (s, e) =>
            {
                hotkey.SetValue(Hotkey.DefaultMods, Hotkey.DefaultKey);
                OnHotkeyCaptured();
            };
            hk.Controls.Add(hotkey);
            hk.Controls.Add(reset);
            t.Controls.Add(hk, 1, 0);
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

            onTop.Text = "一覧をいつも一番手前に表示する(外すと、ほかのアプリを押せば後ろへ回る)";
            onTop.AutoSize = true;
            onTop.CheckedChanged += (s, e) => { if (!loading) app.SetAlwaysOnTop(onTop.Checked); };
            t.Controls.Add(onTop, 1, 4);

            autostart.Text = "Windows にサインインしたら裏で起動しておく";
            autostart.AutoSize = true;
            autostart.Margin = new Padding(3, 10, 3, 0);
            autostart.CheckedChanged += (s, e) => { if (!loading) SetAutostart(autostart.Checked); };
            t.Controls.Add(autostart, 1, 5);
            autostartNote.Margin = new Padding(20, 0, 0, 8);
            t.Controls.Add(autostartNote, 1, 6);
            fixAutostart.Text = "この HoloColors.exe に付け直す";
            fixAutostart.AutoSize = true;
            fixAutostart.Margin = new Padding(20, 0, 0, 8);
            fixAutostart.LinkClicked += (s, e) => { autostart.Checked = true; SetAutostart(true); };
            t.Controls.Add(fixAutostart, 1, 7);

            var data = new LinkLabel { Text = "作業データのフォルダを開く(自分で足した色・設定)", AutoSize = true, Margin = new Padding(3, 10, 3, 0) };
            data.LinkClicked += (s, e) => OpenFolder(app.Store.Dir);
            t.Controls.Add(data, 1, 8);
            var info = new Label
            {
                Text = "メンバーの色: " + app.PaletteSummary + "\n版 " + AppInfo.Version,
                AutoSize = true,
                ForeColor = Ui.Muted,
                Margin = new Padding(3, 8, 3, 8),
            };
            t.Controls.Add(info, 1, 9);

            var close = Ui.Btn("閉じる");
            close.DialogResult = DialogResult.OK;
            var quit = Ui.Btn("アプリを終了");
            quit.Click += (s, e) => { Close(); app.Quit(); };
            var buttons = Ui.ButtonRow(new Padding(0, 6, 0, 0), close, quit);
            t.Controls.Add(buttons, 0, 10);
            t.SetColumnSpan(buttons, 2);
            Controls.Add(t);
            AcceptButton = close;
            CancelButton = close;

            loading = true;
            hotkey.SetValue(app.Store.Settings.HotkeyMods, app.Store.Settings.HotkeyKey);
            closeAfter.Checked = app.Store.Settings.CloseAfterCopy;
            includeHash.Checked = app.Store.Settings.IncludeHash;
            onTop.Checked = app.Store.Settings.AlwaysOnTop;
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

        // 欄にフォーカスがあるまま他のアプリへ移ったり、スタートメニューが開いたりしても、呼び出しのキーを外したままにしない
        protected override void OnActivated(EventArgs e)
        {
            base.OnActivated(e);
            if (hotkey.Focused) app.SuspendHotkey();
        }

        protected override void OnDeactivate(EventArgs e)
        {
            base.OnDeactivate(e);
            app.ResumeHotkey();
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            app.ResumeHotkey();
            base.OnFormClosed(e);
        }

        void SetHotkeyNote(string text, Color color)
        {
            hotkeyNote.Text = text;
            hotkeyNote.ForeColor = color;
        }

        void OnHotkeyCaptured()
        {
            string err = Hotkey.Problem(hotkey.Mods, hotkey.Key) ?? app.ChangeHotkey(hotkey.Mods, hotkey.Key);
            if (err != null)
            {
                SetHotkeyNote(err, Ui.Error);
                hotkey.SetValue(app.Store.Settings.HotkeyMods, app.Store.Settings.HotkeyKey);
                return;
            }
            SetHotkeyNote("「" + Hotkey.Format(hotkey.Mods, hotkey.Key) + "」にしました", Ui.Ok);
        }

        void ShowHotkeyState()
        {
            if (app.HotkeyActive) SetHotkeyNote("どのアプリを使っているときでも、このキーで一覧が開きます", Ui.Muted);
            else SetHotkeyNote("このキーは他のアプリが使っていて登録できませんでした。欄を押して別の組み合わせにしてください", Ui.Error);
        }

        void SetAutostart(bool on)
        {
            try
            {
                app.Autostart.Set(on);
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
            fixAutostart.Visible = false;
            if (app.RunningFromTemp)
            {
                // zip を開いたまま起動した exe は一時フォルダにあり、あとで消える
                autostart.Enabled = false;
                autostartNote.Text = "zip の中から直接起動しているので使えません。zip を右クリック →「すべて展開」したフォルダの HoloColors.exe から起動してください";
            }
            else if (app.Autostart.PointsElsewhere)
            {
                autostartNote.Text = "登録は別の場所の HoloColors.exe を指しています(フォルダを動かしたとき)";
                fixAutostart.Visible = true;
            }
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
        readonly Label error = Ui.Note(Ui.Error, 340);
        public string ResultName, ResultHex;

        public EditColorForm(string title, string initialName, string initialHex)
        {
            Text = title;
            Ui.StyleDialog(this, FormStartPosition.CenterParent);

            var t = new TableLayoutPanel { AutoSize = true, ColumnCount = 3, Padding = new Padding(14), Dock = DockStyle.Fill };
            t.Controls.Add(Ui.FieldLabel("名前", AnchorStyles.Left, 10), 0, 0);
            name.Width = Ui.Px(240);
            name.TextChanged += (s, e) => preview.Invalidate();
            name.MaxLength = Store.MaxName;
            name.Text = initialName ?? "";
            t.Controls.Add(name, 1, 0);
            t.SetColumnSpan(name, 2);

            t.Controls.Add(Ui.FieldLabel("カラーコード", AnchorStyles.Left, 10), 0, 1);
            hex.Width = Ui.Px(120);
            hex.Font = Ui.Mono;
            hex.Text = initialHex ?? "";
            hex.TextChanged += (s, e) => preview.Invalidate();
            t.Controls.Add(hex, 1, 1);
            var pick = Ui.Btn("色を選ぶ…");
            pick.Click += (s, e) => Ui.PickColor(this, hex);
            t.Controls.Add(pick, 2, 1);

            preview.Size = Ui.Px(240, 34);
            preview.Margin = new Padding(3, 8, 3, 4);
            preview.Paint += PaintPreview;
            t.Controls.Add(preview, 1, 2);
            t.SetColumnSpan(preview, 2);

            t.Controls.Add(error, 0, 3);
            t.SetColumnSpan(error, 3);

            var cancel = Ui.Btn("キャンセル");
            cancel.DialogResult = DialogResult.Cancel;
            var ok = Ui.Btn("保存");
            ok.Click += (s, e) => Save();
            var buttons = Ui.ButtonRow(new Padding(3), cancel, ok);
            t.Controls.Add(buttons, 0, 4);
            t.SetColumnSpan(buttons, 3);
            Controls.Add(t);
            AcceptButton = ok;
            CancelButton = cancel;
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            preview.Invalidate();
            (name.Text.Length == 0 ? name : hex).Focus();
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

    // メンバーの色を直す画面(右クリック →「色を直す…」)。色の一覧(いちばん上が主な色)・追加・変更・削除・上へ(主にする)・元の色に戻す。
    // 直した色は作業データの member-colors.json に置く(members.json を新しくしても消えない)
    public class MemberColorsForm : Form
    {
        readonly ColorEntry entry;
        readonly List<ColorOption> colors;
        readonly ListBox list = new ListBox();
        readonly TextBox hex = new TextBox();
        readonly TextBox label = new TextBox();
        readonly Button up = Ui.Btn("上へ(主にする)"), down = Ui.Btn("下へ"), remove = Ui.Btn("削除"), add = Ui.Btn("＋ 足す"), change = Ui.Btn("選んだ色を変える");
        readonly Label error = Ui.Note(Ui.Error, 420);
        public List<ColorOption> Result;
        public bool ResetToOriginal;

        public MemberColorsForm(ColorEntry e)
        {
            entry = e;
            colors = ColorOption.CloneAll(e.AllColors);
            Text = "色を直す: " + e.Name;
            Ui.StyleDialog(this, FormStartPosition.CenterParent);

            var t = new TableLayoutPanel { AutoSize = true, ColumnCount = 2, Padding = new Padding(14), Dock = DockStyle.Fill };
            var head = new Label
            {
                Text = "いちばん上が主な色です(札を押したとき・Enter でコピーする色。同じ PC の「編集」の字幕の色にもなります)。\n"
                    + "2つ目からは、札の右下の小さな四角と右クリックのメニューでコピーできます。",
                AutoSize = true,
                MaximumSize = new Size(Ui.Px(420), 0),
                Margin = new Padding(3, 0, 3, 8),
            };
            t.Controls.Add(head, 0, 0);
            t.SetColumnSpan(head, 2);

            list.DrawMode = DrawMode.OwnerDrawFixed;
            list.ItemHeight = Ui.Px(26);
            list.Size = Ui.Px(300, 26 * 5 + 4);
            list.IntegralHeight = false;
            list.DrawItem += DrawItem;
            list.SelectedIndexChanged += (s, ev) => OnSelected();
            t.Controls.Add(list, 0, 1);
            var side = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.TopDown, WrapContents = false, Margin = new Padding(6, 0, 0, 0) };
            foreach (var b in new[] { up, down, remove })
            {
                b.MinimumSize = new Size(Ui.Px(110), 0);
                side.Controls.Add(b);
            }
            up.Click += (s, ev) => MoveColor(-1);
            down.Click += (s, ev) => MoveColor(1);
            remove.Click += (s, ev) => RemoveColor();
            t.Controls.Add(side, 1, 1);

            var edit = new TableLayoutPanel { AutoSize = true, ColumnCount = 4, Margin = new Padding(0, 8, 0, 0) };
            edit.Controls.Add(Ui.FieldLabel("カラーコード", AnchorStyles.Left, 6), 0, 0);
            hex.Width = Ui.Px(110);
            hex.Font = Ui.Mono;
            edit.Controls.Add(hex, 1, 0);
            var pick = Ui.Btn("色を選ぶ…");
            pick.Click += (s, ev) => Ui.PickColor(this, hex);
            edit.Controls.Add(pick, 2, 0);
            edit.Controls.Add(Ui.FieldLabel("ラベル", AnchorStyles.Left, 6), 0, 1);
            label.Width = Ui.Px(160);
            label.MaxLength = ColorOption.MaxLabel;
            edit.Controls.Add(label, 1, 1);
            edit.SetColumnSpan(label, 2);
            var editButtons = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0) };
            add.Click += (s, ev) => AddColor();
            change.Click += (s, ev) => ChangeColor();
            editButtons.Controls.Add(add);
            editButtons.Controls.Add(change);
            edit.Controls.Add(editButtons, 1, 2);
            edit.SetColumnSpan(editButtons, 3);
            t.Controls.Add(edit, 0, 2);
            t.SetColumnSpan(edit, 2);

            t.Controls.Add(error, 0, 3);
            t.SetColumnSpan(error, 2);

            var cancel = Ui.Btn("キャンセル");
            cancel.DialogResult = DialogResult.Cancel;
            var ok = Ui.Btn("保存");
            ok.Click += (s, ev) => Save();
            var reset = Ui.Btn("元の色に戻す");
            reset.Enabled = e.Customized;
            reset.Click += (s, ev) =>
            {
                ResetToOriginal = true;
                DialogResult = DialogResult.OK;
            };
            var buttons = Ui.ButtonRow(new Padding(0, 8, 0, 0), cancel, ok, reset);
            t.Controls.Add(buttons, 0, 4);
            t.SetColumnSpan(buttons, 2);
            Controls.Add(t);
            AcceptButton = ok;
            CancelButton = cancel;
            Fill(0);
        }

        void Fill(int select)
        {
            list.BeginUpdate();
            list.Items.Clear();
            foreach (var c in colors) list.Items.Add(c.Text);
            list.EndUpdate();
            if (colors.Count > 0) list.SelectedIndex = Math.Max(0, Math.Min(colors.Count - 1, select));
            OnSelected();
        }

        void OnSelected()
        {
            int i = list.SelectedIndex;
            up.Enabled = i > 0;
            down.Enabled = i >= 0 && i < colors.Count - 1;
            remove.Enabled = i >= 0 && colors.Count > 1;   // 最低1色は残す(ぜんぶ消すなら「元の色に戻す」)
            change.Enabled = i >= 0;
            if (i >= 0)
            {
                hex.Text = colors[i].Hex;
                label.Text = colors[i].Label;
            }
            error.Text = "";
        }

        void DrawItem(object sender, DrawItemEventArgs e)
        {
            e.DrawBackground();
            if (e.Index < 0 || e.Index >= colors.Count) return;
            var c = colors[e.Index];
            int sw = Ui.Px(18);
            var r = new Rectangle(e.Bounds.X + Ui.Px(4), e.Bounds.Y + (e.Bounds.Height - sw) / 2, sw, sw);
            using (var b = new SolidBrush(HexColor.ToColor(c.Hex))) e.Graphics.FillRectangle(b, r);
            using (var p = new Pen(Color.FromArgb(90, 0, 0, 0))) e.Graphics.DrawRectangle(p, r);
            string text = c.Hex + "   " + c.Label + (e.Index == 0 ? "   (主な色)" : "");
            TextRenderer.DrawText(e.Graphics, text, Font, new Rectangle(r.Right + Ui.Px(8), e.Bounds.Y, e.Bounds.Right - r.Right - Ui.Px(8), e.Bounds.Height), e.ForeColor, Ui.LeftText);
            e.DrawFocusRectangle();
        }

        // 欄の色とラベル。読めなければ理由を出して null
        ColorOption ReadFields()
        {
            string h;
            if (!HexColor.TryNormalize(hex.Text, out h))
            {
                error.Text = "カラーコードは #FF6699 のような 6 桁の 16 進数で入れてください";
                return null;
            }
            return new ColorOption(h, label.Text.Trim());
        }

        void AddColor()
        {
            var c = ReadFields();
            if (c == null) return;
            if (colors.Any(x => x.Hex == c.Hex)) { error.Text = c.Hex + " はもう入っています"; return; }
            colors.Add(c);
            Fill(colors.Count - 1);
        }

        void ChangeColor()
        {
            int i = list.SelectedIndex;
            var c = ReadFields();
            if (c == null || i < 0) return;
            if (colors.Where((x, j) => j != i).Any(x => x.Hex == c.Hex)) { error.Text = c.Hex + " はもう入っています"; return; }
            colors[i] = c;
            Fill(i);
        }

        void MoveColor(int delta)
        {
            int i = list.SelectedIndex, j = i + delta;
            if (i < 0 || j < 0 || j >= colors.Count) return;
            var c = colors[i];
            colors.RemoveAt(i);
            colors.Insert(j, c);
            Fill(j);
        }

        void RemoveColor()
        {
            int i = list.SelectedIndex;
            if (i < 0 || colors.Count <= 1) return;
            colors.RemoveAt(i);
            Fill(Math.Min(i, colors.Count - 1));
        }

        void Save()
        {
            List<ColorOption> ok;
            string err = ColorOption.Validate(colors, out ok);
            if (err != null) { error.Text = err; return; }
            Result = ok;
            ResetToOriginal = entry.OriginalColors != null && Store.SameColors(ok, entry.OriginalColors);
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
            Font = Ui.Toast;
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
            int pad = Ui.Px(8), sw = Ui.Px(16);
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
            int pad = Ui.Px(8), sw = Ui.Px(16);
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

    // マイワードの追加・編集。表示名(札に出す短い名前。空なら本文の1行目)と本文(複数行可。押すとこれをコピー)
    public class EditWordForm : Form
    {
        readonly TextBox name = new TextBox();
        readonly TextBox body = new TextBox();
        readonly Label error = Ui.Note(Ui.Error, 440);
        readonly Label count = new Label();
        public string ResultName, ResultText;

        public EditWordForm(string title, string initialName, string initialText)
        {
            Text = title;
            Ui.StyleDialog(this, FormStartPosition.CenterParent);
            KeyPreview = true;

            var t = new TableLayoutPanel { AutoSize = true, ColumnCount = 2, Padding = new Padding(14), Dock = DockStyle.Fill };
            t.Controls.Add(Ui.FieldLabel("表示名", AnchorStyles.Left, 10), 0, 0);
            name.Width = Ui.Px(360);
            name.MaxLength = Store.MaxName;
            name.Text = initialName ?? "";
            t.Controls.Add(name, 1, 0);
            t.Controls.Add(new Label { Text = "札に出す短い名前です。空なら本文の1行目を使います", AutoSize = true, ForeColor = Ui.Muted, Margin = new Padding(3, 2, 0, 8) }, 1, 1);

            t.Controls.Add(Ui.FieldLabel("本文", AnchorStyles.Left | AnchorStyles.Top, 10), 0, 2);
            body.Multiline = true;
            body.AcceptsReturn = true;
            body.AcceptsTab = false;
            body.ScrollBars = ScrollBars.Vertical;
            body.WordWrap = true;
            body.Size = Ui.Px(360, 150);
            body.MaxLength = Store.MaxWordText;
            body.Text = (initialText ?? "").Replace("\r\n", "\n").Replace("\n", "\r\n");
            body.TextChanged += (s, e) => UpdateCount();
            t.Controls.Add(body, 1, 2);
            count.AutoSize = true;
            count.ForeColor = Ui.Muted;
            count.Margin = new Padding(3, 2, 0, 4);
            t.Controls.Add(count, 1, 3);

            t.Controls.Add(error, 0, 4);
            t.SetColumnSpan(error, 2);

            var cancel = Ui.Btn("キャンセル");
            cancel.DialogResult = DialogResult.Cancel;
            var ok = Ui.Btn("保存(Ctrl+Enter)");
            ok.Click += (s, e) => Save();
            var buttons = Ui.ButtonRow(new Padding(3), cancel, ok);
            t.Controls.Add(buttons, 0, 5);
            t.SetColumnSpan(buttons, 2);
            Controls.Add(t);
            // 本文の Enter は改行なので、既定のボタン(Enter)は付けない。保存は Ctrl+Enter
            CancelButton = cancel;
            UpdateCount();
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            (body.Text.Length == 0 ? body : name).Focus();
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (keyData == (Keys.Control | Keys.Return))
            {
                Save();
                return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        void UpdateCount()
        {
            int lines = body.Text.Length == 0 ? 0 : body.Text.Replace("\r\n", "\n").Split('\n').Length;
            count.Text = body.Text.Replace("\r\n", "\n").Length + " 文字・" + lines + " 行(" + Store.MaxWordText + " 文字まで)";
        }

        void Save()
        {
            string clean;
            string err = Store.ValidateWord(name.Text, body.Text, out clean);
            if (err != null)
            {
                error.Text = err;
                return;
            }
            ResultName = clean;
            ResultText = body.Text.Replace("\r\n", "\n");
            DialogResult = DialogResult.OK;
        }
    }
}
