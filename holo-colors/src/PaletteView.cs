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
            public string Pill;     // 区分の小さな札(JP・EN など)。マイカラー・卒業は無し
            public string Name;
            public int Count;
            public string Unit;     // 人 / 色
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
        Font nameFont, hexFont, headerFont, emptyFont, pillFont, countFont;
        // 選んでいる札の枠を出すか。検索の文字を打ったか、矢印キーを使ったときだけ(開いた直後に先頭だけ枠があると迷うため)
        public bool ShowSelection;
        ColorEntry flashEntry;   // 「コピーしました」を重ねて出している札(閉じない設定のとき)
        readonly Timer flashTimer = new Timer { Interval = 1100 };

        public PaletteView()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint
                | ControlStyles.ResizeRedraw, true);
            // フォーカスは取らない(札をクリックしても検索欄に入力できるまま。キー操作は検索欄から MoveSelection を呼ぶ)
            SetStyle(ControlStyles.Selectable, false);
            AutoScroll = true;
            BackColor = Color.FromArgb(247, 247, 249);
            TabStop = false;
            flashTimer.Tick += (s, e) => { flashTimer.Stop(); flashEntry = null; Invalidate(); };
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
            DisposeFonts();
            string family = Font.FontFamily.Name;
            nameFont = new Font(family, 9.5f, FontStyle.Bold);
            hexFont = new Font("Consolas", 9f);
            headerFont = new Font(family, 10f, FontStyle.Bold);
            emptyFont = new Font(family, 10f);
            pillFont = new Font(family, 7.5f, FontStyle.Bold);
            countFont = new Font(family, 9f);
        }

        void DisposeFonts()
        {
            foreach (var f in new[] { nameFont, hexFont, headerFont, emptyFont, pillFont, countFont })
                if (f != null) f.Dispose();
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
                bool pill = g.Branch != "MY" && g.Branch != "GRAD";
                headers.Add(new Header { Pill = pill ? Branches.Short(g.Branch) : null, Name = g.Name, Count = g.Items.Count, Unit = g.Branch == "MY" ? " 色" : " 人", Rect = new Rectangle(pad, y, width - 2 * pad, headH) });
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
            // スクロールの分は座標を自分でずらす。Graphics.TranslateTransform は TextRenderer(文字)に効かず、
            // 文字だけ元の位置に描かれてしまう(2026-09-27 に見つかった不具合)
            Point off = AutoScrollPosition;
            if (tiles.Count == 0)
            {
                TextRenderer.DrawText(g, emptyText, emptyFont, new Rectangle(0, S(40), ClientSize.Width, S(60)), Color.FromArgb(110, 110, 120),
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.WordBreak);
                return;
            }
            foreach (var h in headers)
            {
                var r = h.Rect;
                r.Offset(off);
                if (r.IntersectsWith(e.ClipRectangle)) DrawHeader(g, h, r);
            }
            for (int i = 0; i < tiles.Count; i++)
            {
                Rectangle r = tiles[i].Rect;
                r.Offset(off);
                // 見えていない札は描かない(選択の枠の分だけ広めに判定)
                if (Rectangle.Inflate(r, S(4), S(4)).IntersectsWith(e.ClipRectangle))
                    DrawTile(g, tiles[i].Entry, r, i == selected && ShowSelection, i == hover);
            }
        }

        // 見出し: [JP] 0期生 5人 ────  (r は画面の座標)
        void DrawHeader(Graphics g, Header h, Rectangle r)
        {
            const TextFormatFlags F = TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.NoPadding;
            var band = new Rectangle(r.X, r.Y + S(6), r.Width, r.Height - S(6));
            int x = band.X;
            if (h.Pill != null)
            {
                Size ps = TextRenderer.MeasureText(g, h.Pill, pillFont, Size.Empty, F);
                var pr = new Rectangle(x, band.Y + (band.Height - S(16)) / 2, ps.Width + S(10), S(16));
                using (var path = RoundRect(pr, S(8)))
                using (var b = new SolidBrush(Color.FromArgb(228, 228, 236))) g.FillPath(b, path);
                TextRenderer.DrawText(g, h.Pill, pillFont, pr, Color.FromArgb(70, 70, 86), F | TextFormatFlags.HorizontalCenter);
                x = pr.Right + S(6);
            }
            Size ns = TextRenderer.MeasureText(g, h.Name, headerFont, Size.Empty, F);
            TextRenderer.DrawText(g, h.Name, headerFont, new Rectangle(x, band.Y, Math.Max(0, band.Right - x), band.Height), Color.FromArgb(40, 40, 52), F | TextFormatFlags.EndEllipsis);
            x += ns.Width + S(6);
            string count = h.Count + h.Unit;
            Size cs = TextRenderer.MeasureText(g, count, countFont, Size.Empty, F);
            if (x + cs.Width < band.Right)
            {
                TextRenderer.DrawText(g, count, countFont, new Rectangle(x, band.Y, cs.Width + S(2), band.Height), Color.FromArgb(140, 140, 152), F);
                x += cs.Width + S(10);
            }
            if (x < band.Right)
                using (var pen = new Pen(Color.FromArgb(222, 222, 230)))
                    g.DrawLine(pen, x, band.Y + band.Height / 2, band.Right, band.Y + band.Height / 2);
        }

        // 閉じない設定でコピーしたとき、押した札に少しのあいだ「コピーしました」を重ねる
        public void FlashCopied(ColorEntry e)
        {
            flashEntry = e;
            flashTimer.Stop();
            flashTimer.Start();
            Invalidate();
        }

        // r は画面(スクロール済み)の座標
        void DrawTile(Graphics g, ColorEntry entry, Rectangle r, bool isSelected, bool isHover)
        {
            Color bg = HexColor.ToColor(entry.Hex);
            bool dark = HexColor.PrefersDarkText(bg);
            Color fg = dark ? Color.FromArgb(24, 24, 28) : Color.White;
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
            if (entry == flashEntry)
            {
                // 札の色はそのまま、名前の代わりに「コピーしました」
                TextRenderer.DrawText(g, "✓ コピーしました", nameFont, r, fg,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
                return;
            }
            var text = new Rectangle(r.X + S(10), r.Y + S(4), r.Width - S(16), r.Height / 2);
            TextRenderer.DrawText(g, entry.Name, nameFont, text, fg, TextFormatFlags.Left | TextFormatFlags.Bottom | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
            var hex = new Rectangle(r.X + S(10), r.Y + r.Height / 2 + S(1), r.Width - S(16), r.Height / 2 - S(4));
            TextRenderer.DrawText(g, entry.Hex, hexFont, hex, Color.FromArgb(dark ? 170 : 230, fg), TextFormatFlags.Left | TextFormatFlags.Top | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
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
            UpdateHover(e.Location);
        }

        // スクロールしたあとも、マウスの下の札に枠を合わせる(マウスを動かさなくても札は動くため)
        void UpdateHoverAtCursor()
        {
            if (!IsHandleCreated) return;
            Point p = PointToClient(Cursor.Position);
            UpdateHover(ClientRectangle.Contains(p) ? p : new Point(-1, -1));
        }

        protected override void OnScroll(ScrollEventArgs se)
        {
            base.OnScroll(se);
            UpdateHoverAtCursor();
        }

        protected override void OnMouseWheel(MouseEventArgs e)
        {
            base.OnMouseWheel(e);
            UpdateHoverAtCursor();
        }

        void UpdateHover(Point client)
        {
            int h = client.X < 0 ? -1 : HitTest(client);
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
            // 1目盛り(120)で 60px。タッチパッドは 120 より細かく来るので、割り算は最後に
            int y = -AutoScrollPosition.Y - wheelDelta * S(60) / 120;
            AutoScrollPosition = new Point(0, Math.Max(0, y));
            UpdateHoverAtCursor();
            Invalidate();
        }

        // ---- キーボード(検索欄から呼ぶ) ----
        public void MoveSelection(Keys key)
        {
            if (tiles.Count == 0) return;
            if (!ShowSelection)
            {
                // 初めての矢印は、いま選んでいる札に枠を出すだけ
                ShowSelection = true;
                if (selected < 0) selected = 0;
                EnsureVisible();
                return;
            }
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
            if (disposing)
            {
                tip.Dispose();
                flashTimer.Dispose();
                DisposeFonts();
            }
            base.Dispose(disposing);
        }
    }
}
