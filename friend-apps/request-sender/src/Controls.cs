// 配色に合わせて自分で描く部品(2.0.0)。Windows 標準の灰色の部品をそのまま混ぜないために、ボタン・チェック・ラジオ・数の − / +・
// 入力の枠・進み具合の棒・動画の一覧をここで作る。色は Theme.P、大きさは Ui.S。
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace RequestSender
{
    public enum Tone { Text, Muted, Accent, Error }

    // ---- パネル: 地(Bg)かパネル(Panel)の色。枠は 1px ----
    public class Pane : Panel, IThemed
    {
        public bool OnPanel;            // true = パネルの色 / false = 地の色
        public bool Border;
        public Color? BorderColor;      // 枠の色を変える(誤り・フォーカス)。null = 線の色

        public Pane()
        {
            DoubleBuffered = true;
            ResizeRedraw = true;
            Margin = Padding.Empty;
            ApplyTheme();
        }

        public bool Inherit;            // 親と同じ地の色にする(行をまとめるだけのパネル)

        public virtual void ApplyTheme()
        {
            BackColor = Inherit && Parent != null ? Parent.BackColor : OnPanel ? Theme.P.Panel : Theme.P.Bg;
            ForeColor = Theme.P.Text;
        }

        protected override void OnParentChanged(EventArgs e)
        {
            base.OnParentChanged(e);
            if (Inherit) ApplyTheme();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            if (!Border) return;
            using (var pen = new Pen(BorderColor ?? Theme.P.Line)) e.Graphics.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        }
    }

    // ---- 文字: 色は役割(Tone)で決める。使えないときも自分の色で薄く描く(標準の灰色の浮き彫りにしない) ----
    public class Lbl : Label, IThemed
    {
        Tone tone;

        public Lbl()
        {
            AutoSize = true;
            UseMnemonic = false;
            BackColor = Color.Transparent;
            Font = Theme.Body;
            Margin = Padding.Empty;
        }

        public Lbl(string text, Tone tone) : this()
        {
            Text = text;
            this.tone = tone;
        }

        public Tone Tone
        {
            get { return tone; }
            set { tone = value; Invalidate(); }
        }

        // 文字がこの印で始まるとき、印だけアクセントの色で描く(例: 配信の題名の「✓ 」。左寄せの文字だけ)
        public string AccentLead;

        public void ApplyTheme()
        {
            Invalidate();
        }

        // 幅を決めて、折り返した高さに合わせる
        public void Wrap(int width)
        {
            AutoSize = false;
            var sz = TextRenderer.MeasureText(Text.Length > 0 ? Text : " ", Font, new Size(width, 0), TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix);
            Size = new Size(width, sz.Height + 2);
        }

        Color ToneColor()
        {
            var p = Theme.P;
            Color c = tone == Tone.Muted ? p.Muted : tone == Tone.Accent ? p.Accent : tone == Tone.Error ? p.Error : p.Text;
            return Enabled ? c : Theme.Mix(p.Muted, Parent != null ? Parent.BackColor : p.Bg, 0.45);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var flags = TextFormatFlags.NoPrefix | TextFormatFlags.WordBreak | TextFormatFlags.NoPadding;
            var a = TextAlign;
            if (a == ContentAlignment.MiddleLeft || a == ContentAlignment.MiddleCenter || a == ContentAlignment.MiddleRight) flags |= TextFormatFlags.VerticalCenter;
            if (a == ContentAlignment.MiddleCenter || a == ContentAlignment.TopCenter) flags |= TextFormatFlags.HorizontalCenter;
            if (a == ContentAlignment.MiddleRight || a == ContentAlignment.TopRight) flags |= TextFormatFlags.Right;
            if (AutoEllipsis) flags = (flags & ~TextFormatFlags.WordBreak) | TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine;
            int lead = LeadWidth(e.Graphics, flags);
            if (lead <= 0)
            {
                TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, ToneColor(), flags);
                return;
            }
            // 同じ位置に 2 回描いて、印の所と残りで色を分ける(残りの文字の位置は 1 回で描いたときと同じ)
            flags |= TextFormatFlags.PreserveGraphicsClipping;
            var mark = new Rectangle(0, 0, lead, Height);
            var saved = e.Graphics.Save();
            e.Graphics.SetClip(mark, System.Drawing.Drawing2D.CombineMode.Exclude);
            TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, ToneColor(), flags);
            e.Graphics.Restore(saved);
            saved = e.Graphics.Save();
            e.Graphics.SetClip(mark, System.Drawing.Drawing2D.CombineMode.Intersect);
            TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, Theme.P.Accent, flags);
            e.Graphics.Restore(saved);
        }

        // 印の幅(印が無い・使えない・左寄せでないときは 0)。印のあとの空白の半分まで含める
        int LeadWidth(Graphics g, TextFormatFlags flags)
        {
            if (string.IsNullOrEmpty(AccentLead) || !Enabled || !Text.StartsWith(AccentLead, StringComparison.Ordinal)) return 0;
            if ((flags & (TextFormatFlags.HorizontalCenter | TextFormatFlags.Right)) != 0) return 0;
            var one = flags & ~(TextFormatFlags.WordBreak | TextFormatFlags.EndEllipsis);
            string mark = AccentLead.TrimEnd();
            int w = TextRenderer.MeasureText(g, mark, Font, Size.Empty, one).Width;
            int all = TextRenderer.MeasureText(g, AccentLead, Font, Size.Empty, one).Width;
            return (w + Math.Max(w, all)) / 2;
        }
    }

    // ---- ボタン ----
    //   Normal = 枠だけ / Primary = アクセントの塗り(「送る」だけ)/ Toggle = 選ばれたら塗り(2択・切り替え)/ Ghost = 枠なし(×)/ Tab = 上の帯
    public enum BtnKind { Normal, Primary, Toggle, Ghost, Tab }

    public class Btn : Button, IThemed
    {
        public BtnKind Kind;
        bool on, hover, down;

        public Btn()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            FlatStyle = FlatStyle.Flat;
            UseMnemonic = false;
            Font = Theme.Body;
            Height = Ui.S(28);
            Margin = Padding.Empty;
        }

        public Btn(string text, BtnKind kind) : this()
        {
            Text = text;
            Kind = kind;
            FitWidth();
        }

        public void FitWidth()
        {
            Width = TextRenderer.MeasureText(Text, Font, Size.Empty, TextFormatFlags.NoPrefix).Width + Ui.S(16);
        }

        // 選ばれている(Toggle・Tab)
        public bool On
        {
            get { return on; }
            set { if (on != value) { on = value; Invalidate(); } }
        }

        public void ApplyTheme()
        {
            Invalidate();
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = down = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { down = true; Invalidate(); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { down = false; Invalidate(); base.OnMouseUp(e); }
        protected override void OnEnabledChanged(EventArgs e) { hover = down = false; Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

        protected Color Surface { get { return Parent != null ? Parent.BackColor : Theme.P.Bg; } }

        protected override void OnPaint(PaintEventArgs e)
        {
            var p = Theme.P;
            var g = e.Graphics;
            Color surface = Surface, bg, fg, border;
            bool filled = Kind == BtnKind.Primary || (Kind == BtnKind.Toggle && on);
            bool focus = Focused && ShowFocusCues;
            if (!Enabled)
            {
                bg = filled ? Theme.Mix(surface, p.Accent, 0.28) : surface;
                fg = filled ? Theme.Mix(p.OnAccent, bg, 0.35) : Theme.Mix(p.Muted, surface, 0.5);
                border = filled ? bg : Theme.Mix(p.Line, surface, 0.4);
            }
            else if (filled)
            {
                bg = down ? Theme.Mix(p.Accent, p.Bg, 0.25) : hover ? Theme.Mix(p.Accent, p.Text, 0.18) : p.Accent;
                fg = p.OnAccent;
                border = bg;
            }
            else
            {
                bg = down ? Theme.Mix(surface, p.Accent, 0.22) : hover ? Theme.Mix(surface, p.Accent, 0.1) : surface;
                fg = Kind == BtnKind.Ghost || (Kind == BtnKind.Tab && !on) ? (hover ? p.Text : p.Muted) : p.Text;
                border = hover || focus ? p.Accent : p.Line;
            }
            using (var b = new SolidBrush(bg)) g.FillRectangle(b, ClientRectangle);
            if (Kind == BtnKind.Tab)
            {
                if (on) using (var b = new SolidBrush(p.Accent)) g.FillRectangle(b, 0, Height - Ui.S(2), Width, Ui.S(2));
                if (focus) using (var pen = new Pen(p.Accent)) g.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
            }
            else if (Kind != BtnKind.Ghost || hover || focus)
            {
                using (var pen = new Pen(border)) g.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
                if (filled && focus) using (var pen = new Pen(p.OnAccent)) g.DrawRectangle(pen, 2, 2, Width - 5, Height - 5);
            }
            var flags = TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine;
            int dot = Kind == BtnKind.Tab ? Text.IndexOf('●') : -1;
            if (dot < 0) { TextRenderer.DrawText(g, Text, Font, ClientRectangle, fg, flags); return; }
            // 「受け取る ●2」: 届いた数はアクセントの色で
            string head = Text.Substring(0, dot), tail = Text.Substring(dot);
            var left = TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.NoPadding;
            int wh = TextRenderer.MeasureText(g, head, Font, Size.Empty, left).Width, wt = TextRenderer.MeasureText(g, tail, Font, Size.Empty, left).Width;
            int x = (Width - wh - wt) / 2;
            TextRenderer.DrawText(g, head, Font, new Rectangle(x, 0, wh, Height), fg, left);
            TextRenderer.DrawText(g, tail, Font, new Rectangle(x + wh, 0, wt + 2, Height), Enabled ? p.Accent : fg, left);
        }
    }

    // 配色の札(窓の右上)。左半分 = 地、右半分 = アクセント。今の配色は文字の色の枠
    public class Swatch : Btn
    {
        public readonly Palette Palette;

        public Swatch(Palette palette)
        {
            Palette = palette;
            Kind = BtnKind.Ghost;
            Size = new Size(Ui.S(22), Ui.S(22));
            AccessibleName = "配色 " + palette.Name + " " + palette.Label;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            using (var b = new SolidBrush(Surface)) g.FillRectangle(b, ClientRectangle);
            int m = Ui.S(3);
            var r = new Rectangle(m, m, Width - 2 * m, Height - 2 * m);
            using (var b = new SolidBrush(Palette.Bg)) g.FillRectangle(b, r);
            using (var b = new SolidBrush(Palette.Accent)) g.FillRectangle(b, r.X + r.Width / 2, r.Y, r.Width - r.Width / 2, r.Height);
            bool current = Theme.P == Palette;
            using (var pen = new Pen(current ? Theme.P.Text : Theme.P.Line)) g.DrawRectangle(pen, r.X, r.Y, r.Width - 1, r.Height - 1);
            if (current || (Focused && ShowFocusCues)) using (var pen = new Pen(current ? Theme.P.Text : Theme.P.Accent)) g.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        }
    }

    // ---- チェックとラジオ(四角 / 丸を自分で描く) ----
    static class MarkPaint
    {
        public static void Fit(ButtonBase c)
        {
            c.AutoSize = false;
            var sz = TextRenderer.MeasureText(c.Text, c.Font, Size.Empty, TextFormatFlags.NoPrefix);
            c.Size = new Size(Ui.S(16) + Ui.S(8) + sz.Width + Ui.S(4), Math.Max(Ui.S(22), sz.Height + 2));
        }

        public static void Paint(ButtonBase c, Graphics g, bool isChecked, bool round)
        {
            var p = Theme.P;
            Color surface = c.Parent != null ? c.Parent.BackColor : p.Bg;
            using (var b = new SolidBrush(surface)) g.FillRectangle(b, c.ClientRectangle);
            int box = Ui.S(14), y = (c.Height - box) / 2;
            var r = new Rectangle(1, y, box, box);
            Color line = !c.Enabled ? Theme.Mix(p.Line, surface, 0.3) : isChecked || c.Focused ? p.Accent : p.Muted;
            Color mark = c.Enabled ? p.Accent : Theme.Mix(p.Muted, surface, 0.5);
            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            using (var b = new SolidBrush(p.Bg))
            using (var pen = new Pen(line))
            {
                if (round) { g.FillEllipse(b, r); g.DrawEllipse(pen, r); }
                else { g.FillRectangle(b, r); g.DrawRectangle(pen, r); }
            }
            if (isChecked)
            {
                int q = Ui.S(4);
                using (var b = new SolidBrush(mark))
                {
                    if (round) g.FillEllipse(b, r.X + q, r.Y + q, box - 2 * q + 1, box - 2 * q + 1);
                    else g.FillRectangle(b, r.X + q - 1, r.Y + q - 1, box - 2 * q + 3, box - 2 * q + 3);
                }
            }
            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.Default;
            Color fg = c.Enabled ? p.Text : Theme.Mix(p.Muted, surface, 0.45);
            var tr = new Rectangle(box + Ui.S(8), 0, c.Width - box - Ui.S(8), c.Height);
            TextRenderer.DrawText(g, c.Text, c.Font, tr, fg, TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
            if (c.Focused) using (var pen = new Pen(Theme.Mix(surface, p.Accent, 0.5))) g.DrawRectangle(pen, tr.X - 2, 1, Math.Min(tr.Width, TextRenderer.MeasureText(c.Text, c.Font).Width) + 1, c.Height - 3);
        }
    }

    public class Check : CheckBox, IThemed
    {
        public Check(string text)
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            UseMnemonic = false;
            Font = Theme.Body;
            Text = text;
            Margin = Padding.Empty;
            MarkPaint.Fit(this);
        }

        public void ApplyTheme() { Invalidate(); }
        protected override void OnPaint(PaintEventArgs e) { MarkPaint.Paint(this, e.Graphics, Checked, false); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
    }

    public class Radio : RadioButton, IThemed
    {
        public Radio(string text)
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            UseMnemonic = false;
            Font = Theme.Body;
            Text = text;
            Margin = Padding.Empty;
            MarkPaint.Fit(this);
        }

        public void ApplyTheme() { Invalidate(); }
        protected override void OnPaint(PaintEventArgs e) { MarkPaint.Paint(this, e.Graphics, Checked, true); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
    }

    // ---- 押しっぱなしで続けて動くボタン(数の − / +) ----
    //   マウス: 押したときに 1 回、FirstDelayMs 押し続けたら RepeatMs ごとに Step。ボタンの外へずらしている間は止まる(戻せば続く)
    //   キー(Space・Enter)・読み上げの操作: 1 回ずつ(Click)
    public class RepeatBtn : Btn
    {
        public const int FirstDelayMs = 400, RepeatMs = 70;
        readonly Timer timer = new Timer();
        bool fromMouse;   // マウスで押した分は押したときに数えた(離したときの Click では数えない)

        public event Action Step;

        public RepeatBtn(string text) : base(text, BtnKind.Normal)
        {
            timer.Tick += (s, e) => Repeat();
        }

        // 左のボタンが押されたままか・マウスがボタンの上か(テストでは差し替える)
        protected virtual bool Held { get { return (MouseButtons & MouseButtons.Left) != 0; } }
        protected virtual bool PointerOver { get { return ClientRectangle.Contains(PointToClient(MousePosition)); } }

        void Fire()
        {
            if (Step != null) Step();
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left || !Enabled) return;
            fromMouse = true;
            Fire();
            timer.Interval = FirstDelayMs;
            if (Enabled) timer.Start();   // 端まで来て使えなくなったら続けない
        }

        void Repeat()
        {
            timer.Interval = RepeatMs;
            if (!Enabled || !Held) { timer.Stop(); return; }
            if (PointerOver) Fire();
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            timer.Stop();
            base.OnMouseUp(e);   // ここで Click が来る
            fromMouse = false;
        }

        protected override void OnClick(EventArgs e)
        {
            if (!fromMouse) Fire();
            base.OnClick(e);
        }

        protected override void OnEnabledChanged(EventArgs e)
        {
            timer.Stop();
            if (!Enabled) fromMouse = false;
            base.OnEnabledChanged(e);
        }

        protected override void OnMouseCaptureChanged(EventArgs e)
        {
            timer.Stop();
            base.OnMouseCaptureChanged(e);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) timer.Dispose();
            base.Dispose(disposing);
        }
    }

    // ---- 数の − / +(切り抜く数・映像トラックの数・話す人の数・重み)。押しっぱなしで続けて動く ----
    public class Stepper : Pane
    {
        readonly RepeatBtn minus = new RepeatBtn("−"), plus = new RepeatBtn("+");
        readonly Lbl label = new Lbl();
        int value;

        public int Minimum, Maximum;
        public Func<int, string> Format = v => v.ToString();
        public event Action ValueChanged;

        public Stepper(int min, int max, int start, int valueWidth, string name)
        {
            Minimum = min; Maximum = max; value = Math.Max(min, Math.Min(max, start));
            Inherit = true;
            int h = Ui.S(26);
            minus.Size = plus.Size = new Size(h, h);
            minus.Font = plus.Font = Theme.Mono;
            minus.AccessibleName = name + "を減らす";
            plus.AccessibleName = name + "を増やす";
            label.AutoSize = false;
            label.Font = Theme.Mono;
            label.TextAlign = ContentAlignment.MiddleCenter;
            label.Size = new Size(valueWidth, h);
            label.AccessibleName = name;
            minus.Location = new Point(0, 0);
            label.Location = new Point(h, 0);
            plus.Location = new Point(h + valueWidth, 0);
            Size = new Size(h * 2 + valueWidth, h);
            Controls.AddRange(new Control[] { minus, label, plus });
            minus.Step += () => Value = value - 1;
            plus.Step += () => Value = value + 1;
            Show_();
        }

        public int Value
        {
            get { return value; }
            set
            {
                int v = Math.Max(Minimum, Math.Min(Maximum, value));
                if (v == this.value) { Show_(); return; }
                this.value = v;
                Show_();
                if (ValueChanged != null) ValueChanged();
            }
        }

        // 値は変えずに見た目だけ直す
        public void Show_()
        {
            label.Text = Format(value);
            minus.Enabled = Enabled && value > Minimum;
            plus.Enabled = Enabled && value < Maximum;
        }

        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Show_(); }
    }

    // ---- 入力の枠: 中に枠なしの欄を置く。フォーカスでアクセント、誤りで誤りの色 ----
    public class Field : Pane
    {
        public readonly Control Inner;
        bool error;

        public Field(Control inner)
        {
            Inner = inner;
            Border = true;
            Height = Ui.S(28);
            var tb = inner as TextBox;
            if (tb != null) { tb.BorderStyle = BorderStyle.None; if (!(inner is TimeBox)) tb.Font = Theme.Body; }
            Controls.Add(inner);
            inner.GotFocus += (s, e) => Invalidate();
            inner.LostFocus += (s, e) => Invalidate();
            Click += (s, e) => inner.Focus();
            ApplyTheme();
        }

        public bool Error
        {
            get { return error; }
            set { if (error != value) { error = value; Invalidate(); } }
        }

        public override void ApplyTheme()
        {
            BackColor = Theme.P.Bg;
            if (Inner == null) return;
            Inner.BackColor = Theme.P.Bg;
            if (!(Inner is IThemed)) Inner.ForeColor = Theme.P.Text;
        }

        protected override void OnLayout(LayoutEventArgs e)
        {
            base.OnLayout(e);
            if (Inner == null) return;
            int px = Ui.S(6);
            var tb = Inner as TextBox;
            if ((tb != null && tb.Multiline) || Inner is ListBox) Inner.SetBounds(px, Ui.S(4), Width - px * 2, Height - Ui.S(8));
            else if (Inner is ThemedCombo) Inner.SetBounds(1, Math.Max(1, (Height - Inner.Height) / 2), Width - 2, Inner.Height);   // プルダウンは自分で枠の内側いっぱいに描く
            else Inner.SetBounds(px, Math.Max(1, (Height - Inner.Height) / 2), Width - px * 2, Inner.Height);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            BorderColor = error ? Theme.P.Error : Inner != null && Inner.ContainsFocus ? Theme.P.Accent : (Color?)null;
            base.OnPaint(e);
        }
    }

    // ---- 名前のプルダウン(ComboBox の DropDown = 一覧から選べる・一覧に無い名前も打てる。打つと候補が絞られる) ----
    //   標準の灰色のボタンが暗い配色で浮かないよう、ボタンと枠は標準の描画のあとに配色の色で塗り直す(欄の中の文字は標準の入力欄のまま)。
    //   一覧は自分で描く(選んだ行はアクセントを混ぜた地)。Field の中に置く
    public class ThemedCombo : ComboBox, IThemed
    {
        [StructLayout(LayoutKind.Sequential)]
        struct RECT { public int Left, Top, Right, Bottom; }

        [StructLayout(LayoutKind.Sequential)]
        struct COMBOBOXINFO
        {
            public int cbSize;
            public RECT rcItem, rcButton;
            public int stateButton;
            public IntPtr hwndCombo, hwndItem, hwndList;
        }

        [DllImport("user32.dll")]
        static extern bool GetComboBoxInfo(IntPtr hwnd, ref COMBOBOXINFO info);

        [DllImport("user32.dll")]
        static extern IntPtr SendMessage(IntPtr hwnd, int msg, IntPtr wparam, IntPtr lparam);

        [DllImport("gdi32.dll")]
        static extern IntPtr CreateSolidBrush(int colorref);

        [DllImport("gdi32.dll")]
        static extern bool DeleteObject(IntPtr obj);

        [DllImport("gdi32.dll")]
        static extern int SetTextColor(IntPtr hdc, int colorref);

        [DllImport("gdi32.dll")]
        static extern int SetBkColor(IntPtr hdc, int colorref);

        const int WM_PAINT = 0x000F, WM_MOUSEWHEEL = 0x020A, WM_CTLCOLORSTATIC = 0x0138;
        bool hover;
        IntPtr disabledBrush;    // 使えないとき(送っている間)の入力の部分の地。標準の灰色にしない
        Color disabledBrushColor;

        public ThemedCombo()
        {
            DropDownStyle = ComboBoxStyle.DropDown;
            FlatStyle = FlatStyle.Flat;
            DrawMode = DrawMode.OwnerDrawFixed;
            ItemHeight = Ui.S(22);
            IntegralHeight = false;
            MaxDropDownItems = 10;
            Font = Theme.Body;
            Margin = Padding.Empty;
            AutoCompleteMode = AutoCompleteMode.SuggestAppend;
            AutoCompleteSource = AutoCompleteSource.ListItems;
            ApplyTheme();
        }

        // 一覧を入れる(一覧の幅は、いちばん長い名前に合わせる)
        public void SetNames(IEnumerable<string> names)
        {
            Items.Clear();
            int w = Ui.S(200);
            foreach (string n in names)
            {
                Items.Add(n);
                w = Math.Max(w, TextRenderer.MeasureText(n, Font, Size.Empty, TextFormatFlags.NoPrefix).Width + Ui.S(28));
            }
            DropDownWidth = w;
        }

        public void ApplyTheme()
        {
            BackColor = Theme.P.Bg;
            ForeColor = Theme.P.Text;
            Invalidate();
        }

        bool Info(out COMBOBOXINFO info)
        {
            info = new COMBOBOXINFO();
            info.cbSize = Marshal.SizeOf(info);
            try { return IsHandleCreated && GetComboBoxInfo(Handle, ref info); }
            catch (Exception) { return false; }
        }

        protected override void WndProc(ref Message m)
        {
            // ホイールは、一覧を開いているとき以外は名前を変えず、まわり(右の欄のスクロール)へ渡す
            if (m.Msg == WM_MOUSEWHEEL && !DroppedDown && Parent != null && Parent.IsHandleCreated)
            {
                SendMessage(Parent.Handle, m.Msg, m.WParam, m.LParam);
                m.Result = IntPtr.Zero;
                return;
            }
            if (m.Msg == WM_CTLCOLORSTATIC)
            {
                var p = Theme.P;
                if (disabledBrush == IntPtr.Zero || disabledBrushColor != p.Bg)
                {
                    if (disabledBrush != IntPtr.Zero) DeleteObject(disabledBrush);
                    disabledBrush = CreateSolidBrush(ColorTranslator.ToWin32(p.Bg));
                    disabledBrushColor = p.Bg;
                }
                SetTextColor(m.WParam, ColorTranslator.ToWin32(Theme.Mix(p.Muted, p.Bg, 0.45)));
                SetBkColor(m.WParam, ColorTranslator.ToWin32(p.Bg));
                m.Result = disabledBrush;
                return;
            }
            base.WndProc(ref m);
            if (m.Msg == WM_PAINT) Overpaint();
        }

        protected override void Dispose(bool disposing)
        {
            if (disabledBrush != IntPtr.Zero) { DeleteObject(disabledBrush); disabledBrush = IntPtr.Zero; }
            base.Dispose(disposing);
        }

        // 欄の中(入力の部分)以外 = 枠・ボタンを、配色の色で塗り直す
        void Overpaint()
        {
            COMBOBOXINFO info;
            if (!Info(out info)) return;
            try
            {
                var p = Theme.P;
                var item = Rectangle.FromLTRB(info.rcItem.Left, info.rcItem.Top, info.rcItem.Right, info.rcItem.Bottom);
                var btn = Rectangle.FromLTRB(info.rcButton.Left, info.rcButton.Top, info.rcButton.Right, info.rcButton.Bottom);
                if (btn.Width <= 0) btn = new Rectangle(Width - SystemInformation.VerticalScrollBarWidth, 0, SystemInformation.VerticalScrollBarWidth, Height);
                using (var g = Graphics.FromHwnd(Handle))
                {
                    g.SetClip(item, System.Drawing.Drawing2D.CombineMode.Exclude);
                    using (var b = new SolidBrush(p.Bg)) g.FillRectangle(b, ClientRectangle);
                    g.ResetClip();
                    bool active = Enabled && (hover || DroppedDown || ContainsFocus);
                    using (var pen = new Pen(Theme.Mix(p.Line, p.Bg, 0.4))) g.DrawLine(pen, btn.Left, 3, btn.Left, Height - 4);
                    Color arrow = !Enabled ? Theme.Mix(p.Muted, p.Bg, 0.5) : active ? p.Accent : p.Muted;
                    int cx = btn.Left + btn.Width / 2, cy = btn.Top + btn.Height / 2, hw = Ui.S(4);
                    g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                    using (var b = new SolidBrush(arrow))
                        g.FillPolygon(b, new[] { new Point(cx - hw, cy - hw / 2), new Point(cx + hw, cy - hw / 2), new Point(cx, cy + hw - hw / 2) });
                }
            }
            catch (Exception) { }
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        // 開いた一覧のスクロールバーも配色に合わせる(名前が多いので出る)
        protected override void OnDropDown(EventArgs e)
        {
            base.OnDropDown(e);
            COMBOBOXINFO info;
            if (Info(out info)) Theme.DarkScroll(info.hwndList);
        }

        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            Theme.FillRow(e);
            if (e.Index < 0 || e.Index >= Items.Count) return;
            TextRenderer.DrawText(e.Graphics, Convert.ToString(Items[e.Index]), Font, new Rectangle(e.Bounds.X + Ui.S(6), e.Bounds.Y, e.Bounds.Width - Ui.S(8), e.Bounds.Height), Theme.P.Text,
                TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }
    }

    // ---- 全部を自分で描く部品の土台(ちらつかない・フォーカスは取らない・配色が変わったら描き直す) ----
    public abstract class PaintedControl : Control, IThemed
    {
        protected PaintedControl()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            SetStyle(ControlStyles.Selectable, false);
        }

        public virtual void ApplyTheme()
        {
            Invalidate();
        }
    }

    // ---- 色の見本(小さな四角)と、その横の小さな注。色が 6 桁そろったときだけ塗る(空・途中は枠だけ) ----
    public class ColorChip : PaintedControl
    {
        Color? swatch;
        string note = "";
        bool noteAccent;

        public ColorChip()
        {
            Font = Theme.Small;
            Margin = Padding.Empty;
        }

        public Color? Swatch
        {
            get { return swatch; }
            set { if (swatch != value) { swatch = value; Invalidate(); } }
        }

        // 注(例: メンバーカラー / 色なし)。accent = アクセントの色(メンバーカラーのとき)
        public void SetNote(string text, bool accent)
        {
            text = text ?? "";
            if (note == text && noteAccent == accent) return;
            note = text;
            noteAccent = accent;
            Invalidate();
        }

        public string Note { get { return note; } }

        public static int BoxSize { get { return Ui.S(18); } }

        protected override void OnPaint(PaintEventArgs e)
        {
            var p = Theme.P;
            var g = e.Graphics;
            using (var b = new SolidBrush(Parent != null ? Parent.BackColor : p.Bg)) g.FillRectangle(b, ClientRectangle);
            int box = BoxSize, y = (Height - box) / 2;
            var r = new Rectangle(0, y, box, box);
            if (swatch.HasValue) using (var b = new SolidBrush(swatch.Value)) g.FillRectangle(b, r);
            using (var pen = new Pen(swatch.HasValue ? p.Muted : p.Line)) g.DrawRectangle(pen, r.X, r.Y, r.Width - 1, r.Height - 1);
            if (note.Length == 0) return;
            int x = box + Ui.S(6);
            TextRenderer.DrawText(g, note, Font, new Rectangle(x, 0, Math.Max(0, Width - x), Height), noteAccent ? p.Accent : p.Muted,
                TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
        }
    }

    // ---- 進み具合の棒(0〜1000) ----
    public class Bar : PaintedControl
    {
        int value;

        public Bar()
        {
            Height = Ui.S(4);
        }

        public int Value
        {
            get { return value; }
            set { int v = Math.Max(0, Math.Min(1000, value)); if (v != this.value) { this.value = v; Invalidate(); } }
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            using (var b = new SolidBrush(Theme.P.Line)) e.Graphics.FillRectangle(b, ClientRectangle);
            if (value > 0) using (var b = new SolidBrush(Theme.P.Accent)) e.Graphics.FillRectangle(b, 0, 0, (int)((long)Width * value / 1000), Height);
        }
    }

    // ---- 見出し「01 送るもの」: 左にアクセントの線・番号は等幅 ----
    public class SectionHead : PaintedControl
    {
        readonly string no, title;

        public SectionHead(string no, string title)
        {
            this.no = no; this.title = title;
            Height = Ui.S(20);
            AccessibleRole = AccessibleRole.StaticText;
            AccessibleName = title;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var p = Theme.P;
            var g = e.Graphics;
            using (var b = new SolidBrush(Parent != null ? Parent.BackColor : p.Bg)) g.FillRectangle(b, ClientRectangle);
            using (var b = new SolidBrush(p.Accent)) g.FillRectangle(b, 0, Ui.S(2), Ui.S(2), Height - Ui.S(4));
            var flags = TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.NoPadding;
            int x = Ui.S(10);
            TextRenderer.DrawText(g, no, Theme.MonoSmall, new Rectangle(x, 0, Width, Height), p.Accent, flags);
            x += TextRenderer.MeasureText(g, no, Theme.MonoSmall, Size.Empty, flags).Width + Ui.S(8);
            TextRenderer.DrawText(g, title, Theme.Bold, new Rectangle(x, 0, Width - x, Height), p.Text, flags);
        }
    }

    // ---- 配色に合わせて行を自分で描く一覧(標準の一覧は暗い配色でスクロールバーなどが標準の見た目になる) ----
    public abstract class ThemedList : ListBox, IThemed
    {
        protected ThemedList()
        {
            DrawMode = DrawMode.OwnerDrawFixed;
            BorderStyle = BorderStyle.None;
            IntegralHeight = false;
            ItemHeight = Ui.S(24);
            Font = Theme.Body;
            ApplyTheme();
        }

        public void ApplyTheme()
        {
            BackColor = Theme.P.Bg;
            ForeColor = Theme.P.Text;
            Invalidate();
        }
    }

    // ---- 動画の一覧(選んだ行はアクセントを混ぜた地) ----
    public class FileList : ThemedList
    {
        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            var p = Theme.P;
            Theme.FillRow(e);
            if (e.Index < 0 || e.Index >= Items.Count) return;
            string path = Items[e.Index] as string ?? "";
            string name = Path.GetFileName(path), dir = Path.GetDirectoryName(path) ?? "";
            var flags = TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis;
            int nameW = Math.Min(e.Bounds.Width - Ui.S(8), TextRenderer.MeasureText(e.Graphics, name, Font, Size.Empty, TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine).Width + Ui.S(8));
            TextRenderer.DrawText(e.Graphics, name, Font, new Rectangle(e.Bounds.X + Ui.S(4), e.Bounds.Y, nameW, e.Bounds.Height), p.Text, flags);
            int rest = e.Bounds.Width - nameW - Ui.S(12);
            if (rest > Ui.S(60))
                TextRenderer.DrawText(e.Graphics, dir, Theme.Small, new Rectangle(e.Bounds.X + Ui.S(8) + nameW, e.Bounds.Y, rest, e.Bounds.Height), p.Muted, flags | TextFormatFlags.PathEllipsis);
        }
    }
    // ---- 横に並べる行(左から順に・縦は中央)。地の色は親と同じ ----
    public class HRow : Pane
    {
        readonly List<Control> items = new List<Control>();
        readonly Dictionary<Control, int> gaps = new Dictionary<Control, int>();

        public HRow()
        {
            Inherit = true;
            Height = Ui.S(28);
        }

        public HRow Add(Control c, int gap)
        {
            items.Add(c);
            gaps[c] = Ui.S(gap);
            Controls.Add(c);
            Arrange();
            return this;
        }

        // 並べ直す(中の部品の幅・文字が変わったら呼ぶ)
        public void Arrange()
        {
            int x = 0, h = Ui.S(28);
            foreach (var c in items) h = Math.Max(h, c.Height);
            foreach (var c in items)
            {
                x += gaps[c];
                c.Location = new Point(x, (h - c.Height) / 2);
                x += c.Width;
            }
            Size = new Size(x, h);
        }
    }

    // ---- 縦に積むパネル(はみ出したら中だけスクロール)。幅いっぱいにする部品・折り返す文・残りの高さを取る部品を指定できる ----
    public class VStack : Pane
    {
        class Item
        {
            public Control C;
            public int Gap;
            public bool Stretch, Shown = true;
        }

        readonly List<Item> items = new List<Item>();
        bool arranging;

        public int Pad = Ui.S(12);
        public Control Fill;            // 残りの高さを取る部品(1つだけ)
        public int FillMin = Ui.S(44);
        // 入りきらないときに縮める部品(1つだけ。Fill より上)。縮めないときの高さは中身の AutoScrollMinSize.Height。
        // Fill が FillMin を割るとき、ShrinkMin 以上に縮めれば入りきるなら縮めて、中でスクロールさせる(右の列の配信者の行が多いとき、メモを下に隠さない)。
        // 縮めても入りきらないとき・はみ出しが ShrinkSlack より小さいときは縮めない(今までどおり列ごとスクロール。二重のスクロール・数 px のスクロールにしない)
        public ScrollableControl Shrink;
        public int ShrinkMin, ShrinkSlack;

        public VStack()
        {
            AutoScroll = true;
        }

        public T Add<T>(T c, int gap, bool stretch) where T : Control
        {
            items.Add(new Item { C = c, Gap = Ui.S(gap), Stretch = stretch });
            Controls.Add(c);
            return c;
        }

        public void Insert(int index, Control c, int gap, bool stretch)
        {
            items.Insert(Math.Max(0, Math.Min(items.Count, index)), new Item { C = c, Gap = Ui.S(gap), Stretch = stretch });
            Controls.Add(c);
        }

        public void Remove(Control c)
        {
            items.RemoveAll(i => i.C == c);
            Controls.Remove(c);
        }

        public int IndexOf(Control c)
        {
            return items.FindIndex(i => i.C == c);
        }

        public void SetShown(Control c, bool shown)
        {
            var it = items.Find(i => i.C == c);
            if (it == null) return;
            it.Shown = shown;
            c.Visible = shown;
        }

        public void Arrange()
        {
            if (arranging) return;
            arranging = true;
            try
            {
                // 並べたあとでスクロールバーを決め直し、それで中の大きさが変わったら(前の幅での横のスクロールバーが消えたなど)もう一度だけ並べる
                for (int round = 0; round < 2; round++)
                {
                    Size used = ArrangePasses();
                    PerformLayout();
                    if (ClientSize == used) break;
                }
            }
            finally
            {
                arranging = false;
            }
        }

        // 並べる(スクロールバーが出て幅が変わったら、もう一度)。-> 最後に使った中の大きさ
        Size ArrangePasses()
        {
            Size used = ClientSize;
            SuspendLayout();
            try
            {
                for (int pass = 0; pass < 2; pass++)   // スクロールバーが出て幅が変わったら、もう一度
                {
                    used = ClientSize;
                    int w = Math.Max(Ui.S(120), ClientSize.Width - Pad * 2), total = Pad;
                    foreach (var it in items)
                    {
                        if (!it.Shown)
                        {
                            // 隠した文も、幅は欄に合わせておく(長いまま残ると、隠れていても横のスクロールバーが出る)
                            var hl = it.C as Lbl;
                            if (hl != null && it.Stretch) hl.Wrap(w);
                            continue;
                        }
                        var l = it.C as Lbl;
                        if (it.Stretch && l != null) l.Wrap(w);
                        else if (it.Stretch) it.C.Width = w;
                        var row = it.C as HRow;
                        if (row != null) row.Arrange();
                        if (it.C != Fill) total += it.Gap + (it.C == Shrink ? Shrink.AutoScrollMinSize.Height : it.C.Height);
                    }
                    int fillGap = 0;
                    if (Fill != null) { var f = items.Find(i => i.C == Fill); fillGap = f != null ? f.Gap : 0; }
                    if (Shrink != null && items.Exists(i => i.C == Shrink && i.Shown))
                    {
                        int natural = Shrink.AutoScrollMinSize.Height, h = natural;
                        int over = Fill != null ? total + fillGap + FillMin + Pad - ClientSize.Height : 0;
                        if (over > 0 && over >= ShrinkSlack && natural - over >= ShrinkMin) h = natural - over;
                        Shrink.Height = h;
                        total -= natural - h;
                    }
                    if (Fill != null) Fill.Height = Math.Max(FillMin, ClientSize.Height - total - fillGap - Pad);
                    int y = Pad, tab = 0;
                    Point o = AutoScrollPosition;
                    foreach (var it in items)
                    {
                        it.C.TabIndex = tab++;
                        if (!it.Shown) continue;
                        y += it.Gap;
                        it.C.Location = new Point(Pad + o.X, y + o.Y);
                        y += it.C.Height;
                    }
                    int before = ClientSize.Width;
                    AutoScrollMinSize = new Size(0, y + Pad);
                    if (ClientSize.Width == before) break;
                }
            }
            finally
            {
                ResumeLayout();
            }
            return used;
        }

        protected override void OnClientSizeChanged(EventArgs e)
        {
            base.OnClientSizeChanged(e);
            Arrange();
        }
    }
    // ---- 届いたものの一覧(受け取る): 種類・題・大きさ・届いた日時。見出しは EntryHeader が描く ----
    //   標準の一覧(ListView)は、暗い配色でスクロールバーか列の線が標準の見た目になるので使わない
    public class EntryList : ThemedList
    {
        public Func<OutputEntry, string[]> Texts = e => new[] { "", e.Title, "", "" };

        // 列の位置(種類 | 題 | 大きさ(右寄せ)| 届いた日時)。幅は一覧の中身の幅
        public static Rectangle[] Columns(int width, int y, int height)
        {
            int pad = Ui.S(8), kind = Ui.S(64), size = Ui.S(84), when = Ui.S(136);
            int title = Math.Max(Ui.S(60), width - kind - size - when - pad * 2);
            return new[]
            {
                new Rectangle(pad, y, kind, height), new Rectangle(pad + kind, y, title, height),
                new Rectangle(pad + kind + title, y, size - Ui.S(12), height), new Rectangle(pad + kind + title + size, y, when, height),
            };
        }

        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            var p = Theme.P;
            Theme.FillRow(e);
            if (e.Index < 0 || e.Index >= Items.Count) return;
            var entry = Items[e.Index] as OutputEntry;
            if (entry == null) return;
            string[] t = Texts(entry);
            var cols = Columns(ClientSize.Width, e.Bounds.Y, e.Bounds.Height);
            var flags = TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding;
            TextRenderer.DrawText(e.Graphics, t[0], Font, cols[0], entry.Kind == OutputKind.Failure ? p.Error : p.Text, flags);
            TextRenderer.DrawText(e.Graphics, t[1], Font, cols[1], p.Text, flags);
            TextRenderer.DrawText(e.Graphics, t[2], Font, cols[2], p.Muted, flags | TextFormatFlags.Right);
            TextRenderer.DrawText(e.Graphics, t[3], Font, cols[3], p.Muted, flags);
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            Invalidate();
        }
    }

    public class EntryHeader : PaintedControl
    {
        static readonly string[] Titles = { "種類", "題", "大きさ", "届いた日時" };
        public EntryList List;

        protected override void OnPaint(PaintEventArgs e)
        {
            var p = Theme.P;
            using (var b = new SolidBrush(p.Panel)) e.Graphics.FillRectangle(b, ClientRectangle);
            using (var pen = new Pen(p.Line)) e.Graphics.DrawLine(pen, 0, Height - 1, Width, Height - 1);
            var cols = EntryList.Columns(List != null ? List.ClientSize.Width : Width, 0, Height);
            var flags = TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.NoPadding;
            for (int i = 0; i < cols.Length; i++)
                TextRenderer.DrawText(e.Graphics, Titles[i], Theme.Small, cols[i], p.Muted, i == 2 ? flags | TextFormatFlags.Right : flags);
        }
    }
    // ---- 右クリックのメニュー(配色に合わせる。時刻の欄の「貼り付け」など、マウスだけでも使えるように) ----
    public class ThemedMenu : ContextMenuStrip
    {
        class Colors : ProfessionalColorTable
        {
            public override Color MenuBorder { get { return Theme.P.Line; } }
            public override Color ToolStripDropDownBackground { get { return Theme.P.Panel; } }
            public override Color MenuItemSelected { get { return Theme.Mix(Theme.P.Panel, Theme.P.Accent, 0.25); } }
            public override Color MenuItemBorder { get { return Theme.P.Accent; } }
            public override Color ImageMarginGradientBegin { get { return Theme.P.Panel; } }
            public override Color ImageMarginGradientMiddle { get { return Theme.P.Panel; } }
            public override Color ImageMarginGradientEnd { get { return Theme.P.Panel; } }
            public override Color SeparatorDark { get { return Theme.P.Line; } }
            public override Color SeparatorLight { get { return Theme.P.Line; } }
        }

        public ThemedMenu()
        {
            Renderer = new ToolStripProfessionalRenderer(new Colors()) { RoundedEdges = false };
            ShowImageMargin = false;
            Font = Theme.Body;
            Opening += (s, e) =>
            {
                BackColor = Theme.P.Panel;
                foreach (ToolStripItem it in Items) it.ForeColor = it.Enabled ? Theme.P.Text : Theme.P.Muted;
            };
        }

        public ToolStripMenuItem Add(string text, Action run)
        {
            var it = new ToolStripMenuItem(text);
            it.Click += (s, e) => run();
            Items.Add(it);
            return it;
        }
    }
}
