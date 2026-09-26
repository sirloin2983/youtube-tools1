// 色の札を並べて描く一覧(グループの見出し + 札の格子)。札の位置は Layout で決め、描くのとクリックの判定で同じものを使う。
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Windows.Forms;

namespace HoloColors
{
    public class PaletteView : ScrollableControl
    {
        public class Tile
        {
            public ColorEntry Entry;
            public Rectangle Rect;   // スクロールしていないときの座標
        }

        class Header
        {
            public string Text;
            public Rectangle Rect;
        }

        public event Action<ColorEntry> EntryActivated;              // 左クリック・Enter
        public event Action<ColorEntry, Point> EntryContextRequested; // 右クリック(画面の座標)

        readonly List<Tile> tiles = new List<Tile>();
        readonly List<Header> headers = new List<Header>();
        List<ColorGroup> groups = new List<ColorGroup>();
        string emptyText = "";
        int selected = -1, hover = -1;
        float scale = 1f;
        readonly ToolTip tip = new ToolTip { InitialDelay = 600, ReshowDelay = 200 };
        Font nameFont, hexFont, headerFont, emptyFont;

        public PaletteView()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint
                | ControlStyles.ResizeRedraw, true);
            // フォーカスは取らない(札をクリックしても検索欄に入力できるまま。キー操作は検索欄から MoveSelection を呼ぶ)
            SetStyle(ControlStyles.Selectable, false);
            AutoScroll = true;
            BackColor = Color.FromArgb(247, 247, 249);
            TabStop = false;
        }

        public IList<Tile> Tiles { get { return tiles; } }

        public ColorEntry SelectedEntry
        {
            get { return selected >= 0 && selected < tiles.Count ? tiles[selected].Entry : null; }
        }

        public int SelectedIndex { get { return selected; } }

        protected override void OnFontChanged(EventArgs e)
        {
            base.OnFontChanged(e);
            MakeFonts();
            Relayout();
        }

        void MakeFonts()
        {
            using (var g = CreateGraphics()) scale = g.DpiX / 96f;
            string family = Font.FontFamily.Name;
            nameFont = new Font(family, 9.5f, FontStyle.Bold);
            hexFont = new Font("Consolas", 9f);
            headerFont = new Font(family, 9f, FontStyle.Bold);
            emptyFont = new Font(family, 10f);
        }

        int S(float v) { return (int)Math.Round(v * scale); }

        // 見せるグループ(中身は絞り込み済み)。keepSelection = 同じ色を選んだままにする
        public void SetGroups(List<ColorGroup> visible, string whenEmpty, bool keepSelection)
        {
            ColorEntry was = keepSelection ? SelectedEntry : null;
            groups = visible;
            emptyText = whenEmpty;
            hover = -1;
            Relayout();
            selected = -1;
            if (was != null) selected = tiles.FindIndex(t => t.Entry == was);
            if (selected < 0 && tiles.Count > 0) selected = 0;
            if (!keepSelection) AutoScrollPosition = Point.Empty;
            Invalidate();
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            if (nameFont != null) Relayout();
        }

        public void Relayout()
        {
            if (nameFont == null) MakeFonts();
            tiles.Clear();
            headers.Clear();
            int pad = S(12), gap = S(8), minW = S(148), tileH = S(46), headH = S(28);
            int width = ClientSize.Width;
            int cols = Math.Max(1, (width - 2 * pad + gap) / (minW + gap));
            int tileW = Math.Max(S(60), (width - 2 * pad - (cols - 1) * gap) / cols);
            int y = S(4);
            foreach (var g in groups)
            {
                if (g.Items.Count == 0) continue;
                headers.Add(new Header { Text = g.Label + "  (" + g.Items.Count + ")", Rect = new Rectangle(pad, y, width - 2 * pad, headH) });
                y += headH;
                for (int i = 0; i < g.Items.Count; i++)
                {
                    int c = i % cols, r = i / cols;
                    tiles.Add(new Tile { Entry = g.Items[i], Rect = new Rectangle(pad + c * (tileW + gap), y + r * (tileH + gap), tileW, tileH) });
                }
                y += ((g.Items.Count + cols - 1) / cols) * (tileH + gap) + S(6);
            }
            // 幅は合わせるので、縦だけスクロール
            AutoScrollMinSize = new Size(0, y + pad);
            Invalidate();
        }

        public int HitTest(Point client)
        {
            var p = new Point(client.X - AutoScrollPosition.X, client.Y - AutoScrollPosition.Y);
            return tiles.FindIndex(t => t.Rect.Contains(p));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.Clear(BackColor);
            if (nameFont == null) MakeFonts();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TranslateTransform(AutoScrollPosition.X, AutoScrollPosition.Y);
            if (tiles.Count == 0)
            {
                TextRenderer.DrawText(g, emptyText, emptyFont, new Rectangle(0, S(40), ClientSize.Width, S(60)), Color.FromArgb(110, 110, 120),
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.WordBreak);
                return;
            }
            foreach (var h in headers)
                TextRenderer.DrawText(g, h.Text, headerFont, new Rectangle(h.Rect.X + S(2), h.Rect.Y + S(8), h.Rect.Width, h.Rect.Height - S(8)),
                    Color.FromArgb(90, 90, 105), TextFormatFlags.Left | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
            for (int i = 0; i < tiles.Count; i++) DrawTile(g, tiles[i], i == selected, i == hover);
        }

        void DrawTile(Graphics g, Tile t, bool isSelected, bool isHover)
        {
            Color bg = HexColor.ToColor(t.Entry.Hex);
            bool dark = HexColor.PrefersDarkText(bg);
            Color fg = dark ? Color.FromArgb(24, 24, 28) : Color.White;
            Rectangle r = t.Rect;
            int radius = S(7);
            using (var path = RoundRect(r, radius))
            using (var brush = new SolidBrush(bg))
            {
                g.FillPath(brush, path);
                // 白に近い色でも札の形が分かるように、縁を少し濃く
                using (var pen = new Pen(Color.FromArgb(40, 0, 0, 0), 1f)) g.DrawPath(pen, path);
            }
            if (isSelected || isHover)
            {
                var ring = Rectangle.Inflate(r, S(3), S(3));
                using (var path = RoundRect(ring, radius + S(3)))
                using (var pen = new Pen(isSelected ? Color.FromArgb(30, 30, 36) : Color.FromArgb(150, 150, 160), isSelected ? S(2) : 1.5f))
                    g.DrawPath(pen, path);
            }
            var text = new Rectangle(r.X + S(10), r.Y + S(4), r.Width - S(16), r.Height / 2);
            TextRenderer.DrawText(g, t.Entry.Name, nameFont, text, fg, TextFormatFlags.Left | TextFormatFlags.Bottom | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
            var hex = new Rectangle(r.X + S(10), r.Y + r.Height / 2 + S(1), r.Width - S(16), r.Height / 2 - S(4));
            TextRenderer.DrawText(g, t.Entry.Hex, hexFont, hex, Color.FromArgb(dark ? 170 : 230, fg), TextFormatFlags.Left | TextFormatFlags.Top | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
        }

        static GraphicsPath RoundRect(Rectangle r, int radius)
        {
            int d = Math.Max(1, Math.Min(radius * 2, Math.Min(r.Width, r.Height)));
            var p = new GraphicsPath();
            p.AddArc(r.X, r.Y, d, d, 180, 90);
            p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        // ---- マウス ----
        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            int h = HitTest(e.Location);
            if (h == hover) return;
            hover = h;
            Cursor = h >= 0 ? Cursors.Hand : Cursors.Default;
            if (h >= 0)
            {
                var en = tiles[h].Entry;
                string group = en.Group == null ? "" : en.Group.Label.Replace("  ", " ");
                string lines = en.Name + (string.IsNullOrEmpty(en.Sub) ? "" : "  /  " + en.Sub) + "\n" + en.Hex + "   " + group
                    + (string.IsNullOrEmpty(en.Note) ? "" : "\n" + en.Note);
                tip.SetToolTip(this, lines);
            }
            else tip.SetToolTip(this, null);
            Invalidate();
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            base.OnMouseLeave(e);
            hover = -1;
            tip.SetToolTip(this, null);
            Invalidate();
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            int h = HitTest(e.Location);
            if (h < 0) return;
            selected = h;
            Invalidate();
            if (e.Button == MouseButtons.Right && EntryContextRequested != null)
                EntryContextRequested(tiles[h].Entry, PointToScreen(e.Location));
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            base.OnMouseUp(e);
            if (e.Button != MouseButtons.Left) return;
            int h = HitTest(e.Location);
            if (h >= 0 && h == selected && EntryActivated != null) EntryActivated(tiles[h].Entry);
        }

        public void ScrollBy(int wheelDelta)
        {
            int y = -AutoScrollPosition.Y - wheelDelta / 120 * S(60);
            AutoScrollPosition = new Point(0, Math.Max(0, y));
            Invalidate();
        }

        // ---- キーボード(検索欄から呼ぶ) ----
        public void MoveSelection(Keys key)
        {
            if (tiles.Count == 0) return;
            if (selected < 0) { selected = 0; EnsureVisible(); return; }
            Rectangle cur = tiles[selected].Rect;
            int next = selected;
            if (key == Keys.Left) next = Math.Max(0, selected - 1);
            else if (key == Keys.Right) next = Math.Min(tiles.Count - 1, selected + 1);
            else if (key == Keys.Down || key == Keys.Up)
            {
                // 上下の段で、横の位置がいちばん近い札へ(グループの境目もまたげる)
                bool down = key == Keys.Down;
                var rows = tiles.Select(t => t.Rect.Y).Where(y => down ? y > cur.Y : y < cur.Y).ToList();
                if (rows.Count > 0)
                {
                    int rowY = down ? rows.Min() : rows.Max();
                    int cx = cur.X + cur.Width / 2;
                    next = Enumerable.Range(0, tiles.Count).Where(i => tiles[i].Rect.Y == rowY)
                        .OrderBy(i => Math.Abs(tiles[i].Rect.X + tiles[i].Rect.Width / 2 - cx)).First();
                }
            }
            else if (key == Keys.Home) next = 0;
            else if (key == Keys.End) next = tiles.Count - 1;
            selected = next;
            EnsureVisible();
        }

        public void EnsureVisible()
        {
            if (selected < 0 || selected >= tiles.Count) return;
            Rectangle r = tiles[selected].Rect;
            int top = -AutoScrollPosition.Y, h = ClientSize.Height;
            // 見出しも見えるように、グループの最初の段なら少し上まで
            int want = top;
            if (r.Y - S(34) < top) want = Math.Max(0, r.Y - S(34));
            else if (r.Bottom + S(10) > top + h) want = r.Bottom + S(10) - h;
            if (want != top) AutoScrollPosition = new Point(0, want);
            Invalidate();
        }

        public void ActivateSelected()
        {
            var e = SelectedEntry;
            if (e != null && EntryActivated != null) EntryActivated(e);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) tip.Dispose();
            base.Dispose(disposing);
        }
    }
}
