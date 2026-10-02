// 時刻の欄(2.0.0)。欄は1つ・「:」は打たない。時・分・秒 のどれかが反転していて、数字は 時(1桁)→ 分(2桁)→ 秒(2桁)の順に入る。
// ←→ で場所を選ぶ(クリックでも)・↑↓ で選んだ単位を ±1(Shift で ±10)・BackSpace で 0・Delete で空・Ctrl+V で YouTube の位置の URL か 1:23:45。
// 状態の動きは TimeEdit(TimeCore.cs。テストあり)。ここはキーを渡して、文字と選択範囲を映すだけ
using System;
using System.Drawing;
using System.Windows.Forms;

namespace RequestSender
{
    public class TimeBox : TextBox, IThemed
    {
        readonly TimeEdit edit = new TimeEdit();

        public event Action ValueChanged;            // 値が変わった(入った・消えた)
        public event Action<string> Pasted;          // 貼り付けた文字(時刻として読めたとき。URL の欄を埋めるのに使う)
        public event Action<string> PasteFailed;     // 読めなかった理由
        public event Action EnterPressed;            // Enter(次の欄へ)

        public TimeBox(string name)
        {
            BorderStyle = BorderStyle.None;
            ReadOnly = true;                         // 文字は自分で作る(キーは OnKeyDown で受ける)
            ShortcutsEnabled = false;
            ContextMenuStrip = new ContextMenuStrip();   // 標準の右クリックのメニュー(貼り付けなど)で形を壊さない
            ImeMode = ImeMode.Disable;
            TextAlign = HorizontalAlignment.Center;
            Font = Theme.Mono;
            Width = Ui.S(84);
            AccessibleName = name;
            Cursor = Cursors.Default;
            Render();
        }

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

        // 文字・色・反転を今の状態に合わせる
        void Render()
        {
            string t = edit.Text;
            if (Text != t) Text = t;
            BackColor = Theme.P.Bg;
            ForeColor = edit.HasValue ? Theme.P.Text : Theme.P.Muted;
            if (Focused)
            {
                int start, len;
                edit.SegmentRange(out start, out len);
                Select(start, len);
            }
        }

        protected override void OnEnter(EventArgs e)
        {
            base.OnEnter(e);
            edit.Focus();
            BeginInvoke((Action)Render);   // クリックで入ったときは、標準のカーソルの移動のあとに反転させる
        }

        protected override void OnLeave(EventArgs e)
        {
            base.OnLeave(e);
            Select(0, 0);
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            base.OnMouseUp(e);
            if (e.Button != MouseButtons.Left) { Render(); return; }
            if (edit.HasValue) edit.Select(TimeEdit.SegmentAt(Text, GetCharIndexFromPosition(e.Location) + (NearRightHalf(e.Location) ? 1 : 0)));
            else edit.Focus();
            Render();
        }

        // 文字の右半分をクリックしたか(「:」の右隣を選べるように、文字の境目で丸める)
        bool NearRightHalf(Point pt)
        {
            int i = GetCharIndexFromPosition(pt);
            if (i < 0 || i >= Text.Length) return false;
            Point a = GetPositionFromCharIndex(i);
            int w = TextRenderer.MeasureText("0", Font, Size.Empty, TextFormatFlags.NoPadding).Width;
            return Text[i] == ':' && pt.X > a.X + w / 2;
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
