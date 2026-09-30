// 色の一覧の窓。呼び出しのキーで出し、コピーしたら(設定しだいで)隠して、呼び出す前の窓へ戻る。
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace HoloColors
{
    public class MainForm : Form
    {
        readonly AppController app;
        readonly TextBox search = new TextBox();
        readonly FlowLayoutPanel chips = new FlowLayoutPanel();
        readonly PaletteView view = new PaletteView();
        readonly Panel status = new Panel();   // 色の見本 + 文字(Paint で描く。Text にも入れる = テストが読む)
        readonly CheckBox closeAfter = new CheckBox();
        readonly Button addButton = new Button();
        readonly Button settingsButton = new Button();
        readonly ContextMenuStrip menu = new ContextMenuStrip();
        readonly Dictionary<string, RadioButton> chipByFilter = new Dictionary<string, RadioButton>();
        string filter = "ALL";
        bool loading;
        string statusHex;          // コピーした色(見本を出す)。null ならヒントか知らせだけ
        bool statusError, statusHint = true;
        Font statusFont, statusBold;

        public MainForm(AppController app)
        {
            this.app = app;
            Text = AppInfo.Name;
            Font = Ui.Normal;
            AutoScaleMode = AutoScaleMode.None;   // 大きさは Ui.Px で DPI に合わせる
            // タスクバーに出すふつうの窓(v1.2.0)。閉じる = 最小化なので、タスクバーにピン止めしたアイコンに起動中の印が付く
            FormBorderStyle = FormBorderStyle.Sizable;
            ShowInTaskbar = true;
            MaximizeBox = false;
            // いつも一番手前にはしない(閉じない設定のとき、ほかのアプリの上に残り続けるため)。設定で選べる
            StartPosition = FormStartPosition.Manual;
            KeyPreview = true;
            BackColor = Color.FromArgb(247, 247, 249);
            MinimumSize = Ui.Px(380, 320);   // 下の段のボタンが切れない幅
            Icon = Ui.SmallIcon;

            // 上: 検索欄と絞り込みの札
            var top = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1, Padding = new Padding(10, 10, 10, 2), BackColor = Color.White };
            search.Dock = DockStyle.Fill;
            search.Font = Ui.Search;
            search.Margin = new Padding(0, 0, 0, 6);
            search.TextChanged += (s, e) => Refill(false);
            search.KeyDown += SearchKeyDown;
            search.MouseWheel += (s, e) => view.ScrollBy(e.Delta);
            top.Controls.Add(search);
            chips.Dock = DockStyle.Fill;
            chips.AutoSize = true;
            chips.WrapContents = true;
            chips.Margin = new Padding(0);
            foreach (string f in Branches.Filters) chips.Controls.Add(MakeChip(f));
            top.Controls.Add(chips);

            // 下: いまの様子・コピーしたら閉じる・追加・設定
            var bottom = new TableLayoutPanel { Dock = DockStyle.Bottom, AutoSize = true, ColumnCount = 4, Padding = new Padding(10, 6, 10, 8), BackColor = Color.White };
            bottom.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            bottom.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            bottom.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            bottom.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            status.Dock = DockStyle.Fill;
            status.Height = Ui.Px(24);
            status.Margin = new Padding(0, 0, 0, 4);
            status.Paint += PaintStatus;
            statusFont = Font;
            statusBold = new Font(Font, FontStyle.Bold);
            closeAfter.Text = "コピーしたら閉じる";
            closeAfter.AutoSize = true;
            closeAfter.Anchor = AnchorStyles.Left;
            closeAfter.Margin = new Padding(0, 5, 8, 3);
            closeAfter.CheckedChanged += (s, e) => { if (!loading) app.SetCloseAfterCopy(closeAfter.Checked); };
            // 「＋ 追加」→ 色を追加 / ワードを追加
            addButton.Text = "＋ 追加";
            addButton.AutoSize = true;
            addButton.Click += (s, e) =>
            {
                var m = new ContextMenuStrip();
                m.Items.Add("色を追加…(マイカラー)", null, (s2, e2) => app.AddColor(this, null));
                m.Items.Add("ワードを追加…(マイワード)", null, (s2, e2) => app.AddWord(this));
                m.Show(addButton, new Point(0, addButton.Height));
            };
            settingsButton.Text = "設定";
            settingsButton.AutoSize = true;
            settingsButton.Click += (s, e) => app.OpenSettings(this);
            // 1段目: 知らせ(横いっぱい。長い名前やヒントが切れないように)、2段目: コピーしたら閉じる・追加・設定
            bottom.Controls.Add(status, 0, 0);
            bottom.SetColumnSpan(status, 4);
            bottom.Controls.Add(closeAfter, 0, 1);
            bottom.Controls.Add(addButton, 2, 1);
            bottom.Controls.Add(settingsButton, 3, 1);

            view.Dock = DockStyle.Fill;
            view.Font = Font;
            view.EntryActivated += en => app.Copy(en);
            view.ColorActivated += (en, i) => app.Copy(en, i);
            view.EntryContextRequested += ShowEntryMenu;
            view.FavoriteToggled += en => app.ToggleFavorite(en);
            view.ItemMoved += (en, to) => app.MoveItemTo(en, to);
            view.IsFavorite = en => app.Store.IsFavorite(en);

            Controls.Add(view);
            Controls.Add(top);
            Controls.Add(bottom);
            var line1 = new Panel { Dock = DockStyle.Top, Height = 1, BackColor = Color.FromArgb(225, 225, 232) };
            var line2 = new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = Color.FromArgb(225, 225, 232) };
            Controls.Add(line1);
            Controls.Add(line2);
            line1.BringToFront();
            view.BringToFront();
        }

        public PaletteView View { get { return view; } }
        public TextBox SearchBox { get { return search; } }
        public string Filter { get { return filter; } }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            Native.SetCueBanner(search, "名前・ローマ字・カラーコードで検索(↑↓で選んで Enter でコピー)");
        }

        RadioButton MakeChip(string f)
        {
            var rb = new RadioButton
            {
                Text = Branches.Short(f),
                Appearance = Appearance.Button,
                AutoSize = true,
                FlatStyle = FlatStyle.Flat,
                Margin = new Padding(0, 0, 4, 4),
                Padding = new Padding(4, 0, 4, 0),
                TabStop = false,
                Tag = f,
                UseMnemonic = false,
            };
            rb.FlatAppearance.BorderColor = Color.FromArgb(210, 210, 218);
            rb.FlatAppearance.CheckedBackColor = Color.FromArgb(40, 40, 48);
            // 選んである札をもう一度押したとき(CheckedChanged が来ない)も、検索欄へ戻す
            rb.Click += (s, e) => search.Focus();
            rb.CheckedChanged += (s, e) =>
            {
                rb.ForeColor = rb.Checked ? Color.White : Color.FromArgb(40, 40, 48);
                rb.BackColor = rb.Checked ? Color.FromArgb(40, 40, 48) : Color.White;
                if (rb.Checked && !loading)
                {
                    SetFilter(f, true);
                    search.Focus();   // 札を押したあとも、そのまま文字を打てば検索できるように
                }
            };
            rb.ForeColor = Color.FromArgb(40, 40, 48);
            rb.BackColor = Color.White;
            chipByFilter[f] = rb;
            return rb;
        }

        public void SetFilter(string f, bool save)
        {
            if (Array.IndexOf(Branches.Filters, f) < 0) f = "ALL";
            filter = f;
            loading = true;
            chipByFilter[f].Checked = true;
            loading = false;
            if (save) app.SetFilter(f);
            Refill(false);
        }

        // 絞り込みと検索のとおりに並べ直す
        public void Refill(bool keepSelection)
        {
            string q = search.Text;
            view.ShowSelection = q.Trim().Length > 0;
            var visible = new List<ColorGroup>();
            // 「すべて」で検索していないときは、お気に入りと最近使ったものを一番上に(写し。元のグループにもそのまま残る)
            if (filter == "ALL" && string.IsNullOrWhiteSpace(q))
            {
                var all = app.AllGroups().SelectMany(g => g.Items).ToList();
                var fav = new ColorGroup { Id = "fav", Branch = "FAV", Name = Branches.Short("FAV") };
                fav.Items.AddRange(app.Store.ResolveIds(app.Store.Settings.Favorites, all));
                if (fav.Items.Count > 0) visible.Add(fav);
                var recent = new ColorGroup { Id = "recent", Branch = "RECENT", Name = Branches.Short("RECENT") };
                recent.Items.AddRange(app.Store.ResolveIds(app.Store.Settings.Recent.Select(r => r.Id), all));
                if (recent.Items.Count > 0) visible.Add(recent);
            }
            foreach (var g in app.AllGroups())
            {
                if (filter != "ALL" && g.Branch != filter) continue;
                var copy = new ColorGroup { Id = g.Id, Branch = g.Branch, Name = g.Name };
                copy.Items.AddRange(g.Items.Where(x => SearchText.Matches(x, q)));
                if (copy.Items.Count > 0) visible.Add(copy);
            }
            string empty = !string.IsNullOrWhiteSpace(q) ? "「" + q.Trim() + "」は見つかりません"
                : filter == "MY" ? "まだ色がありません。\n下の「＋ 追加」→「色を追加」から足せます"
                : filter == "WORD" ? "まだワードがありません。\nよく使う言葉や文を「＋ 追加」→「ワードを追加」で登録すると、押すだけでコピーできます"
                : "色がありません";
            view.SetGroups(visible, empty, keepSelection);
        }

        public void ApplySettings(Settings s)
        {
            loading = true;
            closeAfter.Checked = s.CloseAfterCopy;
            loading = false;
            TopMost = s.AlwaysOnTop;
            if (statusHint) ShowHint();
        }

        // 下の段の知らせ。hex を渡すと色の見本を付ける
        public void SetStatus(string text, bool error)
        {
            SetStatus(text, error, null);
        }

        public void SetStatus(string text, bool error, string hex)
        {
            statusHint = false;
            statusError = error;
            statusHex = hex;
            status.Text = text;
            status.Invalidate();
        }

        // 何も起きていないときの操作のヒント(薄い字)
        public void ShowHint()
        {
            string problem = app.TakeProblem();
            if (problem != null)
            {
                SetStatus(problem, true);
                return;
            }
            statusHint = true;
            statusError = false;
            statusHex = null;
            string key = app.HotkeyText.Replace(" + ", "+");
            status.Text = app.FirstRun
                ? "Esc で閉じるとタスクバーで待機し、" + key + " でまた開きます(× は終了)"
                : key + " で開閉 ・ 右クリックでメニュー";
            status.Invalidate();
        }

        void PaintStatus(object sender, PaintEventArgs e)
        {
            var g = e.Graphics;
            float k = Ui.Scale;
            int x = 0, h = status.ClientSize.Height;
            if (statusHex != null)
            {
                int sw = (int)(14 * k);
                var r = new Rectangle(0, (h - sw) / 2, sw, sw);
                using (var b = new SolidBrush(HexColor.ToColor(statusHex))) g.FillRectangle(b, r);
                using (var p = new Pen(Color.FromArgb(60, 0, 0, 0))) g.DrawRectangle(p, r);
                x = sw + (int)(6 * k);
            }
            Color c = statusError ? Color.FromArgb(190, 30, 30) : statusHint ? Color.FromArgb(135, 135, 148) : Color.FromArgb(30, 30, 40);
            TextRenderer.DrawText(g, status.Text, statusHex != null ? statusBold : statusFont, new Rectangle(x, 0, status.ClientSize.Width - x, h), c,
                TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine);
        }

        // 呼び出されたとき: 検索を空にして一番上から
        public void ResetView()
        {
            ShowHint();
            search.Text = "";
            Refill(false);
            view.AutoScrollPosition = Point.Empty;
        }

        void SearchKeyDown(object sender, KeyEventArgs e)
        {
            // Alt + 矢印: 選んでいるマイカラー・マイワードを前後へ動かす(ドラッグと同じ)
            if (e.Alt && (e.KeyCode == Keys.Up || e.KeyCode == Keys.Down || e.KeyCode == Keys.Left || e.KeyCode == Keys.Right))
            {
                var t = view.SelectedTile;
                if (t != null && PaletteView.CanDrag(t))
                    app.MoveColor(t.Entry, e.KeyCode == Keys.Up || e.KeyCode == Keys.Left ? -1 : 1);
                e.Handled = e.SuppressKeyPress = true;
                return;
            }
            switch (e.KeyCode)
            {
                case Keys.Down:
                case Keys.Up:
                    view.MoveSelection(e.KeyCode);
                    e.Handled = e.SuppressKeyPress = true;
                    break;
                case Keys.Left:
                case Keys.Right:
                    // 検索欄が空なら札を動かす(文字があるときは文字のカーソル)
                    if (search.TextLength == 0) { view.MoveSelection(e.KeyCode); e.Handled = e.SuppressKeyPress = true; }
                    break;
                case Keys.PageDown:
                case Keys.PageUp:
                    view.ScrollBy(e.KeyCode == Keys.PageDown ? -360 : 360);
                    e.Handled = e.SuppressKeyPress = true;
                    break;
                case Keys.Return:
                    view.ActivateSelected();
                    e.Handled = e.SuppressKeyPress = true;
                    break;
            }
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (keyData == Keys.Escape)
            {
                // 検索の文字があれば、まず消す(もう一度 Esc で閉じる)
                if (search.TextLength > 0)
                {
                    search.Text = "";
                    search.Focus();
                }
                else app.HideMain(true);
                return true;
            }
            if (keyData == (Keys.Control | Keys.F) || keyData == (Keys.Control | Keys.L))
            {
                search.Focus();
                search.SelectAll();
                return true;
            }
            // 矢印と Enter で札を動かすのは検索欄にいるとき(SearchKeyDown)。下のボタンに Tab で移ったときの Enter はボタンのまま
            return base.ProcessCmdKey(ref msg, keyData);
        }

        void ShowEntryMenu(ColorEntry en, Point screen)
        {
            menu.Items.Clear();
            if (en.IsWord)
            {
                menu.Items.Add("コピー(本文)", null, (s, e) => app.Copy(en, 0));
                AddFavoriteItem(en);
                menu.Items.Add(new ToolStripSeparator());
                menu.Items.Add("編集…", null, (s, e) => app.EditWord(this, en));
                AddMoveItems(en, app.Store.Words.Items);
                menu.Items.Add(new ToolStripSeparator());
                menu.Items.Add("削除", null, (s, e) => app.RemoveWord(this, en));
                menu.Show(screen);
                return;
            }
            // 色ごとの「コピー」(2色以上ある人は、札の小さな四角と同じ色をここからも)
            var colors = en.AllColors;
            for (int i = 0; i < colors.Count; i++)
            {
                int index = i;
                string label = colors.Count > 1 && colors[i].Label.Length > 0 ? "(" + colors[i].Label + ")" : "";
                var item = menu.Items.Add("コピー  " + app.CopyText(colors[i].Hex) + label, null, (s, e) => app.Copy(en, index));
                if (colors.Count > 1) item.Image = Swatch(colors[i].Hex);
            }
            AddFavoriteItem(en);
            if (en.IsUser)
            {
                menu.Items.Add(new ToolStripSeparator());
                menu.Items.Add("編集…", null, (s, e) => app.EditColor(this, en));
                AddMoveItems(en, app.Store.Mine.Items);
                menu.Items.Add(new ToolStripSeparator());
                menu.Items.Add("削除", null, (s, e) => app.RemoveColor(this, en));
            }
            else
            {
                menu.Items.Add(new ToolStripSeparator());
                menu.Items.Add("この人に色を追加…", null, (s, e) => app.AddColorToMember(this, en));
                menu.Items.Add(en.Customized ? "色を直す…(直した色を使っています)" : "色を直す…(並べ替え・消す・元に戻す)", null, (s, e) => app.EditMemberColors(this, en));
                menu.Items.Add("この色をもとにマイカラーへ追加…", null, (s, e) => app.AddColor(this, en));
            }
            menu.Show(screen);
        }

        void AddFavoriteItem(ColorEntry en)
        {
            bool fav = app.Store.IsFavorite(en);
            menu.Items.Add(fav ? "★ お気に入りから外す" : "☆ お気に入りに入れる", null, (s, e) => app.ToggleFavorite(en));
        }

        void AddMoveItems(ColorEntry en, List<ColorEntry> list)
        {
            var up = menu.Items.Add("前へ(Alt+↑)", null, (s, e) => app.MoveColor(en, -1));
            var down = menu.Items.Add("後ろへ(Alt+↓)", null, (s, e) => app.MoveColor(en, 1));
            int i = list.IndexOf(en);
            up.Enabled = i > 0;
            down.Enabled = i >= 0 && i < list.Count - 1;
        }

        // メニューの項目の横の色の見本
        static Bitmap Swatch(string hex)
        {
            int n = Ui.Px(14);
            var bmp = new Bitmap(n, n);
            using (var g = Graphics.FromImage(bmp))
            using (var b = new SolidBrush(HexColor.ToColor(hex)))
            using (var p = new Pen(Color.FromArgb(90, 0, 0, 0)))
            {
                g.FillRectangle(b, 0, 0, n - 1, n - 1);
                g.DrawRectangle(p, 0, 0, n - 1, n - 1);
            }
            return bmp;
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            // × ・ Alt+F4 ・タスクバーの「ウィンドウを閉じる」はアプリの終了(v1.2.1。ユーザーの指摘: × で終了しない)。
            // Esc とコピー後に閉じるのは最小化のまま(HideMain。タスクバーに残して、キーでまた開ける)。
            // 窓だけ破棄されて通知領域にアプリが残ると、キーを押すたびにエラーになるので、窓を閉じるときは必ずアプリごと終わる
            if (!app.Quitting)
            {
                if (e.CloseReason == CloseReason.WindowsShutDown || e.CloseReason == CloseReason.TaskManagerClosing)
                {
                    app.QuitAfterClose();   // 閉じるのは止めない(Windows の終了を妨げない)
                }
                else
                {
                    // 閉じている最中に Quit(中で main.Close を呼ぶ)を呼ぶと入れ子になるので、いったん止めてから終わる
                    e.Cancel = true;
                    BeginInvoke(new Action(app.Quit));
                    return;
                }
            }
            base.OnFormClosing(e);
        }

        protected override void OnActivated(EventArgs e)
        {
            base.OnActivated(e);
            // 設定・追加の画面から戻ったときも、すぐ検索できるように(WinForms が前のボタンへフォーカスを戻したあとで)
            BeginInvoke(new Action(() => { if (Visible && !search.Focused) search.Focus(); }));
        }

        protected override void OnResizeEnd(EventArgs e)
        {
            base.OnResizeEnd(e);
            app.RememberSize(Size);
        }
    }
}
