// 配色に合わせて自分で描く部品(2.0.0)。Windows 標準の灰色の部品をそのまま混ぜないために、ボタン・チェック・ラジオ・数の − / +・
// 入力の枠・進み具合の棒・動画の一覧をここで作る。色は Theme.P、大きさは Ui.S。
using System;
using System.Drawing;
using System.IO;
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
            TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, ToneColor(), flags);
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

    // ---- 数の − / +(切り抜く数・映像トラックの数・話す人の数・重み) ----
    public class Stepper : Pane
    {
        readonly Btn minus = new Btn("−", BtnKind.Normal), plus = new Btn("+", BtnKind.Normal);
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
            minus.Click += (s, e) => Value = value - 1;
            plus.Click += (s, e) => Value = value + 1;
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

        // 下限を変える(区間の数より小さくできないように)
        public void SetMinimum(int min)
        {
            Minimum = Math.Min(min, Maximum);
            Value = Math.Max(value, Minimum);
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
            else Inner.SetBounds(px, Math.Max(1, (Height - Inner.Height) / 2), Width - px * 2, Inner.Height);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            BorderColor = error ? Theme.P.Error : Inner != null && Inner.ContainsFocus ? Theme.P.Accent : (Color?)null;
            base.OnPaint(e);
        }
    }

    // ---- 進み具合の棒(0〜1000) ----
    public class Bar : Control, IThemed
    {
        int value;

        public Bar()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            SetStyle(ControlStyles.Selectable, false);
            Height = Ui.S(4);
        }

        public int Value
        {
            get { return value; }
            set { int v = Math.Max(0, Math.Min(1000, value)); if (v != this.value) { this.value = v; Invalidate(); } }
        }

        public void ApplyTheme() { Invalidate(); }

        protected override void OnPaint(PaintEventArgs e)
        {
            using (var b = new SolidBrush(Theme.P.Line)) e.Graphics.FillRectangle(b, ClientRectangle);
            if (value > 0) using (var b = new SolidBrush(Theme.P.Accent)) e.Graphics.FillRectangle(b, 0, 0, (int)((long)Width * value / 1000), Height);
        }
    }

    // ---- 見出し「01 送るもの」: 左にアクセントの線・番号は等幅 ----
    public class SectionHead : Control, IThemed
    {
        readonly string no, title;

        public SectionHead(string no, string title)
        {
            this.no = no; this.title = title;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            SetStyle(ControlStyles.Selectable, false);
            Height = Ui.S(20);
            AccessibleRole = AccessibleRole.StaticText;
            AccessibleName = title;
        }

        public void ApplyTheme() { Invalidate(); }

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

    // ---- 動画の一覧(選んだ行はアクセントを混ぜた地) ----
    public class FileList : ListBox, IThemed
    {
        public FileList()
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

        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            var p = Theme.P;
            bool sel = (e.State & DrawItemState.Selected) != 0;
            using (var b = new SolidBrush(sel ? Theme.Mix(p.Bg, p.Accent, 0.25) : p.Bg)) e.Graphics.FillRectangle(b, e.Bounds);
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
        readonly System.Collections.Generic.List<Control> items = new System.Collections.Generic.List<Control>();
        readonly System.Collections.Generic.Dictionary<Control, int> gaps = new System.Collections.Generic.Dictionary<Control, int>();
        readonly System.Collections.Generic.HashSet<Control> hidden = new System.Collections.Generic.HashSet<Control>();

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

        public void SetShown(Control c, bool shown)
        {
            if (shown) hidden.Remove(c); else hidden.Add(c);
            c.Visible = shown;
            Arrange();
        }

        // 並べ直す(中の部品の幅・文字が変わったら呼ぶ)
        public void Arrange()
        {
            int x = 0, h = Ui.S(28);
            foreach (var c in items) if (!hidden.Contains(c)) h = Math.Max(h, c.Height);
            foreach (var c in items)
            {
                if (hidden.Contains(c)) continue;
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

        readonly System.Collections.Generic.List<Item> items = new System.Collections.Generic.List<Item>();
        bool arranging;

        public int Pad = Ui.S(12);
        public Control Fill;            // 残りの高さを取る部品(1つだけ)
        public int FillMin = Ui.S(56);

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
            SuspendLayout();
            try
            {
                for (int pass = 0; pass < 2; pass++)   // スクロールバーが出て幅が変わったら、もう一度
                {
                    int w = Math.Max(Ui.S(120), ClientSize.Width - Pad * 2), total = Pad;
                    foreach (var it in items)
                    {
                        if (!it.Shown) continue;
                        var l = it.C as Lbl;
                        if (it.Stretch && l != null) l.Wrap(w);
                        else if (it.Stretch) it.C.Width = w;
                        var row = it.C as HRow;
                        if (row != null) row.Arrange();
                        if (it.C != Fill) total += it.Gap + it.C.Height;
                    }
                    if (Fill != null) { var f = items.Find(i => i.C == Fill); Fill.Height = Math.Max(FillMin, ClientSize.Height - total - (f != null ? f.Gap : 0) - Pad); }
                    int y = Pad;
                    Point o = AutoScrollPosition;
                    foreach (var it in items)
                    {
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
                arranging = false;
            }
        }

        protected override void OnClientSizeChanged(EventArgs e)
        {
            base.OnClientSizeChanged(e);
            Arrange();
        }
    }
    // ---- 届いたものの一覧(受け取る): 種類・題・大きさ・届いた日時。見出しは EntryHeader が描く ----
    //   標準の一覧(ListView)は、暗い配色でスクロールバーか列の線が標準の見た目になるので使わない
    public class EntryList : ListBox, IThemed
    {
        public Func<OutputEntry, string[]> Texts = e => new[] { "", e.Title, "", "" };

        public EntryList()
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
            bool sel = (e.State & DrawItemState.Selected) != 0;
            using (var b = new SolidBrush(sel ? Theme.Mix(p.Bg, p.Accent, 0.25) : p.Bg)) e.Graphics.FillRectangle(b, e.Bounds);
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

    public class EntryHeader : Control, IThemed
    {
        static readonly string[] Titles = { "種類", "題", "大きさ", "届いた日時" };
        public EntryList List;

        public EntryHeader()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            SetStyle(ControlStyles.Selectable, false);
        }

        public void ApplyTheme() { Invalidate(); }

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
}
