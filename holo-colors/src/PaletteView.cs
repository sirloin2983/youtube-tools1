// 色の札を並べて描く一覧(グループの見出し + 札の格子)。札の位置は Relayout で決め、描くのとクリックの判定で同じものを使う。
// 札の形(v1.4.0。ユーザー決定 2026-09-30「案B」): 上段 = 白地に名前(★・直した色の印)、下段 = その人の色を同じ幅の帯に並べる(帯ごとにコピー)。
// マイワードの札は下段が灰色の帯で、本文の1行目を出す(押すと本文をコピー)。
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
            public ColorGroup Group;   // この札を並べたグループ(お気に入り・最近使ったものの写しは、元のグループと別)
            public Rectangle Rect;     // スクロールしていないときの座標
            public Rectangle Top;      // 上段(名前)
            // 下段の色の帯。Bands[i] = Entry.AllColors[i](0 = 主な色)。1段に入りきらなければ2段・3段に折り返す
            public List<Rectangle> Bands = new List<Rectangle>();
            public int BandRows = 1;
            public Rectangle Star;     // ★(お気に入り)の当たり
        }

        public const int MinBandWidth = 40;   // これより細くなるなら次の段へ折り返す(96 DPI の px。カラーコードの6文字が入る幅)

        class Header
        {
            public string Pill;     // 区分の小さな札(JP・EN など)。マイカラー・卒業などは無し
            public string Name;
            public int Count;
            public string Unit;     // 人 / 色 / 件
            public Rectangle Rect;
        }

        public event Action<ColorEntry> EntryActivated;              // Enter(主な色・ワードの本文)
        public event Action<ColorEntry, int> ColorActivated;         // 札のクリック(AllColors の番号。名前の段は 0。ワードは 0)
        public event Action<ColorEntry, Point> EntryContextRequested; // 右クリック(画面の座標)
        public event Action<ColorEntry> FavoriteToggled;             // ★ のクリック
        public event Action<ColorEntry, int> ItemMoved;              // マイカラー・マイワードをドラッグで動かした(新しい位置)
        public Func<ColorEntry, bool> IsFavorite = e => false;

        readonly List<Tile> tiles = new List<Tile>();
        readonly List<Header> headers = new List<Header>();
        List<ColorGroup> groups = new List<ColorGroup>();
        string emptyText = "";
        int selected = -1, hover = -1, hoverColor;
        int pressedTile = -1, pressedColor;   // 左ボタンを押した札と色(離したときに同じなら、その色をコピー)
        Point pressedAt;
        int dragTile = -1, dropIndex = -1;    // ドラッグ中の札と、落とす位置(同じグループの中の番号)
        float scale = 1f;
        readonly ToolTip tip = new ToolTip { InitialDelay = 600, ReshowDelay = 200 };
        Font nameFont, hexFont, headerFont, emptyFont, pillFont, countFont, wordFont;
        // 選んでいる札の枠を出すか。検索の文字を打ったか、矢印キーを使ったときだけ(開いた直後に先頭だけ枠があると迷うため)
        public bool ShowSelection;
        ColorEntry flashEntry;   // 「コピーしました」を重ねて出している札(閉じない設定のとき)
        int flashColor;
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

        public Tile SelectedTile
        {
            get { return selected >= 0 && selected < tiles.Count ? tiles[selected] : null; }
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
            hexFont = new Font("Consolas", 8.5f);
            headerFont = new Font(family, 10f, FontStyle.Bold);
            emptyFont = new Font(family, 10f);
            pillFont = new Font(family, 7.5f, FontStyle.Bold);
            countFont = new Font(family, 9f);
            wordFont = new Font(family, 8.5f);
        }

        void DisposeFonts()
        {
            foreach (var f in new[] { nameFont, hexFont, headerFont, emptyFont, pillFont, countFont, wordFont })
                if (f != null) f.Dispose();
        }

        int S(float v) { return (int)Math.Round(v * scale); }

        // 見せるグループ(中身は絞り込み済み)。keepSelection = 同じ札を選んだままにする
        public void SetGroups(List<ColorGroup> visible, string whenEmpty, bool keepSelection)
        {
            Tile was = keepSelection ? SelectedTile : null;
            groups = visible;
            emptyText = whenEmpty;
            hover = -1;
            dragTile = -1;
            Relayout();
            selected = -1;
            if (was != null)
            {
                // 同じグループの同じ札を優先(お気に入りの写しと元の札を取り違えない)
                selected = tiles.FindIndex(t => t.Entry == was.Entry && t.Group != null && was.Group != null && t.Group.Id == was.Group.Id);
                if (selected < 0) selected = tiles.FindIndex(t => t.Entry == was.Entry);
            }
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
            int pad = S(12), gap = S(8), minW = S(172), topH = S(28), bandH = S(30), headH = S(28);
            int width = ClientSize.Width;
            int cols = Math.Max(1, (width - 2 * pad + gap) / (minW + gap));
            int tileW = Math.Max(S(60), (width - 2 * pad - (cols - 1) * gap) / cols);
            int perRow = Math.Max(1, tileW / S(MinBandWidth));   // 1段に並べられる帯の数
            int y = S(4);
            foreach (var g in groups)
            {
                if (g.Items.Count == 0) continue;
                headers.Add(new Header
                {
                    Pill = Branches.IsSpecial(g.Branch) || g.Branch == "GRAD" ? null : Branches.Short(g.Branch),
                    Name = g.Name,
                    Count = g.Items.Count,
                    Unit = g.Branch == "MY" ? " 色" : g.Branch == "WORD" ? " 件" : g.Branch == "FAV" || g.Branch == "RECENT" ? "" : " 人",
                    Rect = new Rectangle(pad, y, width - 2 * pad, headH),
                });
                y += headH;
                // 行ごとに、いちばん段の多い札に高さをそろえる(色の多い人は帯を折り返して背が高くなる)
                for (int start = 0; start < g.Items.Count; start += cols)
                {
                    int end = Math.Min(g.Items.Count, start + cols);
                    int rows = 1;
                    for (int i = start; i < end; i++) rows = Math.Max(rows, BandRowsFor(g.Items[i], perRow));
                    int h = topH + rows * bandH;
                    for (int i = start; i < end; i++)
                    {
                        var tile = new Tile { Entry = g.Items[i], Group = g, Rect = new Rectangle(pad + (i - start) * (tileW + gap), y, tileW, h) };
                        PlaceParts(tile, topH, perRow);
                        tiles.Add(tile);
                    }
                    y += h + gap;
                }
                y += S(6);
            }
            // 幅は合わせるので、縦だけスクロール
            AutoScrollMinSize = new Size(0, y + pad);
            Invalidate();
        }

        static int BandRowsFor(ColorEntry e, int perRow)
        {
            if (e.IsWord) return 1;
            int n = Math.Max(1, e.AllColors.Count);
            return (n + perRow - 1) / perRow;
        }

        // 上段(名前・★)と下段の帯の位置を決める。帯は1段に perRow 本まで。多ければ段を増やし、段ごとの本数をそろえる(5色なら 3本 + 2本)。
        // 各段はその段の本数で幅いっぱいに分ける。札の高さは行の中でそろえてあるので、段の高さは下段の高さを段の数で割る
        void PlaceParts(Tile t, int topH, int perRow)
        {
            Rectangle r = t.Rect;
            t.Top = new Rectangle(r.X, r.Y, r.Width, topH);
            int star = S(18);
            t.Star = new Rectangle(r.Right - S(6) - star, r.Y + (topH - star) / 2, star, star);
            t.Bands.Clear();
            var area = new Rectangle(r.X, r.Y + topH, r.Width, r.Height - topH);
            if (t.Entry.IsWord)
            {
                t.BandRows = 1;
                t.Bands.Add(area);   // ワードは1本(本文の1行目)
                return;
            }
            int n = Math.Max(1, t.Entry.AllColors.Count);
            int rows = (n + perRow - 1) / perRow;
            int per = (n + rows - 1) / rows;
            t.BandRows = rows;
            int k = 0;
            for (int row = 0; row < rows; row++)
            {
                int inRow = Math.Min(per, n - k);
                int y0 = area.Y + area.Height * row / rows, y1 = area.Y + area.Height * (row + 1) / rows;
                for (int i = 0; i < inRow; i++, k++)
                {
                    int x0 = area.X + area.Width * i / inRow, x1 = area.X + area.Width * (i + 1) / inRow;
                    t.Bands.Add(new Rectangle(x0, y0, x1 - x0, y1 - y0));
                }
            }
        }

        public int HitTest(Point client)
        {
            var p = new Point(client.X - AutoScrollPosition.X, client.Y - AutoScrollPosition.Y);
            return tiles.FindIndex(t => t.Rect.Contains(p));
        }

        // 札と、その中の色の番号(上段・ワード = 0、帯 = その色の番号)。★ の上なら colorIndex = -2。札の外なら -1
        public int HitTestColor(Point client, out int colorIndex)
        {
            colorIndex = 0;
            int h = HitTest(client);
            if (h < 0) return -1;
            var p = new Point(client.X - AutoScrollPosition.X, client.Y - AutoScrollPosition.Y);
            var t = tiles[h];
            if (Rectangle.Inflate(t.Star, S(2), S(2)).Contains(p)) { colorIndex = -2; return h; }
            if (t.Entry.IsWord) return h;
            for (int i = 0; i < t.Bands.Count; i++)
                if (t.Bands[i].Contains(p)) { colorIndex = i; return h; }
            return h;
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
                    DrawTile(g, tiles[i], off, i == selected && ShowSelection, i == hover ? hoverColor : -1, i == dragTile);
            }
            DrawDropMarker(g, off);
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

        // 閉じない設定でコピーしたとき、押した帯(ワードは札の下段)に少しのあいだ「コピーしました」を重ねる
        public void FlashCopied(ColorEntry e)
        {
            FlashCopied(e, 0);
        }

        public void FlashCopied(ColorEntry e, int colorIndex)
        {
            flashEntry = e;
            flashColor = colorIndex;
            flashTimer.Stop();
            flashTimer.Start();
            Invalidate();
        }

        static Rectangle Off(Rectangle r, Point off)
        {
            r.Offset(off);
            return r;
        }

        // hoverColor = マウスの下の色(-1 = この札の上ではない)
        void DrawTile(Graphics g, Tile tile, Point off, bool isSelected, int hoverColor, bool dragging)
        {
            ColorEntry entry = tile.Entry;
            Rectangle r = Off(tile.Rect, off);
            int radius = S(7);
            bool isHover = hover >= 0 && tiles[hover] == tile;
            using (var path = RoundRect(r, radius))
            {
                // 下段の帯は札の角丸の中に切り抜いて描く
                var oldClip = g.Clip;
                g.SetClip(path, CombineMode.Intersect);
                using (var white = new SolidBrush(Color.White)) g.FillRectangle(white, r);
                DrawBands(g, tile, off, hoverColor);
                g.Clip = oldClip;
                using (var pen = new Pen(Color.FromArgb(dragging ? 90 : 45, 0, 0, 0), 1f)) g.DrawPath(pen, path);
            }
            if (isSelected || isHover)
            {
                var ring = Rectangle.Inflate(r, S(3), S(3));
                using (var path = RoundRect(ring, radius + S(3)))
                using (var pen = new Pen(isSelected ? Color.FromArgb(30, 30, 36) : Color.FromArgb(150, 150, 160), isSelected ? S(2) : 1.5f))
                    g.DrawPath(pen, path);
            }
            // 上段: 名前(直した色の札は「✎」)・★
            Rectangle top = Off(tile.Top, off), star = Off(tile.Star, off);
            bool fav = IsFavorite(entry);
            int right = star.X - S(2);
            string mark = entry.Customized ? "✎ " : "";
            var nameRect = new Rectangle(top.X + S(9), top.Y, Math.Max(0, right - top.X - S(9)), top.Height);
            TextRenderer.DrawText(g, mark + entry.Name, nameFont, nameRect, Color.FromArgb(28, 28, 34),
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
            if (fav || isHover)
            {
                bool onStar = isHover && hoverColor == -2;
                Color sc = fav ? Color.FromArgb(232, 170, 20) : Color.FromArgb(onStar ? 150 : 200, 150, 150, 160);
                TextRenderer.DrawText(g, fav ? "★" : "☆", nameFont, star, sc,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.NoPadding);
            }
        }

        // 下段: 色の帯(カラーコードつき)か、ワードの本文の1行目
        void DrawBands(Graphics g, Tile tile, Point off, int hoverColor)
        {
            ColorEntry entry = tile.Entry;
            const TextFormatFlags C = TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine;
            if (entry.IsWord)
            {
                Rectangle b = Off(tile.Bands[0], off);
                using (var br = new SolidBrush(Color.FromArgb(hoverColor >= 0 ? 232 : 240, hoverColor >= 0 ? 232 : 240, hoverColor >= 0 ? 238 : 244))) g.FillRectangle(br, b);
                string first = FirstLine(entry.Text);
                bool flash = entry == flashEntry;
                TextRenderer.DrawText(g, flash ? "✓ コピーしました" : first, flash ? nameFont : wordFont, Rectangle.Inflate(b, -S(8), 0),
                    flash ? Color.FromArgb(20, 110, 60) : Color.FromArgb(80, 80, 92),
                    TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
                return;
            }
            var colors = entry.AllColors;
            for (int i = 0; i < tile.Bands.Count && i < colors.Count; i++)
            {
                Rectangle b = Off(tile.Bands[i], off);
                Color c = HexColor.ToColor(colors[i].Hex);
                bool dark = HexColor.PrefersDarkText(c);
                Color fg = dark ? Color.FromArgb(24, 24, 28) : Color.White;
                using (var br = new SolidBrush(c)) g.FillRectangle(br, b);
                // 帯どうしの境目(左と上)に細い線
                using (var pen = new Pen(Color.FromArgb(70, 255, 255, 255)))
                {
                    if (b.X > tile.Rect.X + off.X) g.DrawLine(pen, b.X, b.Y, b.X, b.Bottom);
                    if (b.Y > tile.Bands[0].Y + off.Y) g.DrawLine(pen, b.X, b.Y, b.Right, b.Y);
                }
                if (hoverColor == i)
                {
                    var inner = Rectangle.Inflate(b, -S(2), -S(2));
                    using (var pen = new Pen(Color.FromArgb(dark ? 160 : 230, fg), S(2))) g.DrawRectangle(pen, inner);
                }
                string text = entry == flashEntry && flashColor == i ? "✓" : colors[i].Hex.Substring(1);
                // 帯が細くて入らなければ文字は出さない(ツールチップで分かる)
                if (TextRenderer.MeasureText(g, text, hexFont, Size.Empty, C | TextFormatFlags.NoPadding).Width <= b.Width - S(4))
                    TextRenderer.DrawText(g, text, hexFont, b, Color.FromArgb(dark ? 190 : 235, fg), C);
            }
        }

        public static string FirstLine(string text)
        {
            if (string.IsNullOrEmpty(text)) return "";
            foreach (string line in text.Replace("\r\n", "\n").Split('\n'))
                if (line.Trim().Length > 0) return line.Trim();
            return "";
        }

        // ツールチップ: 名前・グループ・全部の色(ラベル付き)・直した色か・メモ。ワードは本文
        public static string TipText(ColorEntry en)
        {
            string group = en.Group == null ? "" : en.Group.Label.Replace("  ", " ");
            var sb = new System.Text.StringBuilder();
            if (en.IsWord)
            {
                string body = en.Text.Length > 400 ? en.Text.Substring(0, 400) + "…" : en.Text;
                sb.Append(en.Name).Append("   ").Append(group).Append('\n').Append(body);
                sb.Append("\n\n押すと本文をコピー");
                return sb.ToString();
            }
            sb.Append(en.Name).Append(string.IsNullOrEmpty(en.Sub) ? "" : "  /  " + en.Sub).Append('\n');
            var colors = en.AllColors;
            if (colors.Count <= 1) sb.Append(en.Hex).Append("   ").Append(group);
            else
            {
                sb.Append(group);
                for (int i = 0; i < colors.Count; i++)
                    sb.Append('\n').Append(i == 0 ? "主な色  " : "ほかの色  ").Append(colors[i].Text);
            }
            if (en.Customized) sb.Append("\n(✎ 自分で直した・足した色。右クリック →「色を直す…」で元に戻せます)");
            if (!string.IsNullOrEmpty(en.Note)) sb.Append('\n').Append(en.Note);
            sb.Append("\n\n帯を押すとその色、名前を押すと主な色をコピー");
            return sb.ToString();
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

        // ---- ドラッグで並べ替え(マイカラー・マイワードの自分のグループの中だけ) ----
        public static bool CanDrag(Tile t)
        {
            return t != null && t.Entry.IsUser && t.Group != null && (t.Group.Branch == "MY" || t.Group.Branch == "WORD");
        }

        // 同じグループの札のうち、マウスの位置にいちばん近い「差し込む場所」(0 〜 Count-1。動かす札の今の位置の考え方で)
        int DropIndexAt(Point contentPoint)
        {
            var src = tiles[dragTile];
            var same = tiles.Where(t => t.Group == src.Group).ToList();
            int best = same.IndexOf(src);
            double bestD = double.MaxValue;
            for (int i = 0; i < same.Count; i++)
            {
                Rectangle r = same[i].Rect;
                double dx = contentPoint.X - (r.X + r.Width / 2.0), dy = contentPoint.Y - (r.Y + r.Height / 2.0);
                double d = dx * dx + dy * dy;
                if (d < bestD) { bestD = d; best = i; }
            }
            return best;
        }

        void DrawDropMarker(Graphics g, Point off)
        {
            if (dragTile < 0 || dropIndex < 0) return;
            var src = tiles[dragTile];
            var same = tiles.Where(t => t.Group == src.Group).ToList();
            int from = same.IndexOf(src);
            if (dropIndex == from || dropIndex >= same.Count) return;
            // 前へ動かすなら落とす札の左、後ろへなら右に線
            Rectangle r = Off(same[dropIndex].Rect, off);
            int x = dropIndex < from ? r.X - S(5) : r.Right + S(4);
            using (var pen = new Pen(Color.FromArgb(40, 110, 230), S(3))) g.DrawLine(pen, x, r.Y, x, r.Bottom);
        }

        // ---- マウス ----
        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (e.Button == MouseButtons.Left && pressedTile >= 0 && CanDrag(tiles[pressedTile]))
            {
                if (dragTile < 0 && (Math.Abs(e.X - pressedAt.X) > S(6) || Math.Abs(e.Y - pressedAt.Y) > S(6)))
                {
                    dragTile = pressedTile;
                    Cursor = Cursors.SizeAll;
                    tip.SetToolTip(this, null);
                }
                if (dragTile >= 0)
                {
                    dropIndex = DropIndexAt(new Point(e.X - AutoScrollPosition.X, e.Y - AutoScrollPosition.Y));
                    Invalidate();
                    return;
                }
            }
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
            int ci = 0;
            int h = client.X < 0 ? -1 : HitTestColor(client, out ci);
            if (h == hover && ci == hoverColor) return;
            bool tileChanged = h != hover;
            hover = h;
            hoverColor = ci;
            Cursor = h >= 0 ? Cursors.Hand : Cursors.Default;
            if (tileChanged)
                tip.SetToolTip(this, h >= 0 ? TipText(tiles[h].Entry) : null);
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
            int ci;
            int h = HitTestColor(e.Location, out ci);
            pressedTile = e.Button == MouseButtons.Left ? h : -1;
            pressedColor = ci;
            pressedAt = e.Location;
            dragTile = -1;
            dropIndex = -1;
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
            if (dragTile >= 0)
            {
                var src = tiles[dragTile];
                var same = tiles.Where(t => t.Group == src.Group).ToList();
                int from = same.IndexOf(src), to = dropIndex;
                dragTile = -1;
                dropIndex = -1;
                pressedTile = -1;
                Cursor = Cursors.Default;
                Invalidate();
                if (to >= 0 && to != from && ItemMoved != null) ItemMoved(src.Entry, to);
                return;
            }
            int ci;
            int h = HitTestColor(e.Location, out ci);
            bool same2 = h >= 0 && h == selected && h == pressedTile && ci == pressedColor;
            pressedTile = -1;
            if (!same2) return;
            if (ci == -2) { if (FavoriteToggled != null) FavoriteToggled(tiles[h].Entry); return; }
            if (ColorActivated != null) ColorActivated(tiles[h].Entry, ci);
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

        // 並べ替えたあと、動かした札を選び直す(Alt+矢印で続けて動かせるように)
        public void SelectEntryIn(ColorEntry e, string groupBranch)
        {
            int i = tiles.FindIndex(t => t.Entry == e && t.Group != null && t.Group.Branch == groupBranch);
            if (i < 0) return;
            selected = i;
            ShowSelection = true;
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
