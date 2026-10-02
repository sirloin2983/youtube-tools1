// 時刻の欄(2.0.0)。欄は1つ・「:」は打たない。時・分・秒 のどれかが反転していて、数字は 時(1桁)→ 分(2桁)→ 秒(2桁)の順に入る。
// ←→ で場所を選ぶ(クリックでも)・↑↓ で選んだ単位を ±1(Shift で ±10)・BackSpace で 0・Delete で空・Ctrl+V で YouTube の位置の URL か 1:23:45。
// 状態の動きは TimeEdit(TimeCore.cs。テストあり)。ここはキーを渡して、文字と反転を描くだけ。
// 標準の入力欄(TextBox)を使わないのは、選んだ所の反転を配色のアクセントで描くため(標準の欄は Windows の青になる)と、文字を打ち込めないようにするため
using System;
using System.Drawing;
using System.Windows.Forms;

namespace RequestSender
{
    public class TimeBox : Control, IThemed
    {
        readonly TimeEdit edit = new TimeEdit();

        public event Action ValueChanged;            // 値が変わった(入った・消えた)
        public event Action<string> Pasted;          // 貼り付けた文字(時刻として読めたとき。URL の欄を埋めるのに使う)
        public event Action<string> PasteFailed;     // 読めなかった理由
        public event Action EnterPressed;            // Enter(次の欄へ)

        public TimeBox(string name)
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
            TabStop = true;
            ImeMode = ImeMode.Disable;               // 日本語入力が数字のキーを取らないように
            Font = Theme.Mono;
            Size = new Size(Ui.S(84), TextRenderer.MeasureText("0", Theme.Mono).Height + 2);
            AccessibleName = name;
            AccessibleRole = AccessibleRole.Text;
            Cursor = Cursors.IBeam;
            Render();
        }

        public bool ShowAsFocused;                   // 画面の確認(--state focus): 窓が前に無くても、選んだ所の反転を描く

        bool Lit { get { return (Focused || ShowAsFocused) && Enabled; } }

        // 画面の確認用: 時・分・秒 を選ぶ(0 = 時)
        public void SelectSegment(int segment) { edit.Select(segment); Invalidate(); }

        public bool HasValue { get { return edit.HasValue; } }
        public int Value { get { return edit.Value; } }

        public void SetValue(int sec)
        {
            edit.Set(sec);
            Render();
            Fire();
        }

        public void ClearValue()
        {
            bool had = edit.HasValue;
            edit.Clear();
            Render();
            if (had) Fire();
        }

        public void ApplyTheme()
        {
            Render();
        }

        void Fire()
        {
            if (ValueChanged != null) ValueChanged();
        }

        void Render()
        {
            string t = edit.Text;
            if (Text != t) Text = t;
            AccessibleDescription = edit.HasValue ? t : "未入力";
            BackColor = Theme.P.Bg;
            Invalidate();
        }

        // 文字の並びの左端と、1文字の幅(等幅のフォント)
        void Metrics(out int x0, out int cw)
        {
            cw = TextRenderer.MeasureText("00", Font, Size.Empty, TextFormatFlags.NoPadding).Width / 2;
            x0 = (Width - cw * Text.Length) / 2;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var p = Theme.P;
            var g = e.Graphics;
            using (var b = new SolidBrush(p.Bg)) g.FillRectangle(b, ClientRectangle);
            string t = Text;
            int x0, cw, start, len;
            Metrics(out x0, out cw);
            edit.SegmentRange(out start, out len);
            Color fg = !Enabled ? Theme.Mix(p.Muted, p.Bg, 0.45) : edit.HasValue ? p.Text : p.Muted;
            var flags = TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.VerticalCenter | TextFormatFlags.HorizontalCenter;
            if (Lit)   // 選んでいる所(時・分・秒)をアクセントで反転
                using (var b = new SolidBrush(p.Accent)) g.FillRectangle(b, x0 + start * cw - 1, 1, len * cw + 2, Height - 2);
            for (int i = 0; i < t.Length; i++)
            {
                bool sel = Lit && i >= start && i < start + len;
                TextRenderer.DrawText(g, t[i].ToString(), Font, new Rectangle(x0 + i * cw, 0, cw, Height), sel ? p.OnAccent : fg, flags);
            }
        }

        protected override void OnEnter(EventArgs e)
        {
            base.OnEnter(e);
            edit.Focus();   // 欄に入ったら、時から打ち始める
            Invalidate();
        }

        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left) return;
            if (!Focused) Focus();
            int x0, cw;
            Metrics(out x0, out cw);
            // 入っていない欄は時から。入っていれば、クリックした所(時・分・秒)を選ぶ
            if (edit.HasValue) edit.Select(TimeEdit.SegmentAt(Text, Math.Max(0, Math.Min(Text.Length - 1, (e.X - x0) / Math.Max(1, cw)))));
            else edit.Focus();
            Invalidate();
        }

        protected override bool IsInputKey(Keys keyData)
        {
            Keys k = keyData & Keys.KeyCode;
            if (k == Keys.Left || k == Keys.Right || k == Keys.Up || k == Keys.Down) return true;
            return base.IsInputKey(keyData);
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            base.OnKeyDown(e);
            if (e.Handled) return;
            int before = edit.Value;
            bool hadValue = edit.HasValue, handled = true;
            Keys k = e.KeyCode;
            if (e.Control && k == Keys.V || e.Shift && k == Keys.Insert) Paste_();
            else if (e.Control && k == Keys.C) { try { Clipboard.SetText(Text); } catch (Exception) { } }
            else if (e.Control || e.Alt) handled = false;
            else if (k >= Keys.D0 && k <= Keys.D9 && !e.Shift) edit.Digit(k - Keys.D0);
            else if (k >= Keys.NumPad0 && k <= Keys.NumPad9) edit.Digit(k - Keys.NumPad0);
            else if (k == Keys.Left) edit.Left();
            else if (k == Keys.Right) edit.Right();
            else if (k == Keys.Up) edit.Step(1, e.Shift);
            else if (k == Keys.Down) edit.Step(-1, e.Shift);
            else if (k == Keys.Back) edit.Backspace();
            else if (k == Keys.Delete) edit.Clear();
            else if (k == Keys.Enter) { if (EnterPressed != null) EnterPressed(); }
            else handled = false;
            if (!handled) return;
            e.Handled = e.SuppressKeyPress = true;
            Render();
            if (before != edit.Value || hadValue != edit.HasValue) Fire();
        }

        void Paste_()
        {
            string text;
            try { text = Clipboard.ContainsText() ? Clipboard.GetText() : ""; }
            catch (Exception) { text = ""; }
            int sec;
            if (TimeText.TryParse(text, out sec))
            {
                edit.Set(sec);
                if (Pasted != null) Pasted(text);
            }
            else if (PasteFailed != null)
                PasteFailed("時刻として読めませんでした。YouTube の「現在の時刻の動画の URL をコピー」か、1:23:45 の形を貼ってください");
        }
    }
}
