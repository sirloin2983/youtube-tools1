// まとめ動画(2.7.0): 届いたら裏で先に取ってきておき(PreviewQueue)、アプリの小窓で再生する(PreviewForm)。
//   取る順番 … 一覧を調べたときに、まとめ動画のあるパックと組(2.8.0。組ごとに 1 本)を一覧の順に並べる。「まとめ動画を見る」を押したものは先頭へ。
//              大きすぎるもの(AutoMaxBytes 超)は押したときだけ。失敗したものは押したときにもう一度。一覧から消えたものは取らない
//   小窓     … Windows にはじめから入っている WPF の MediaElement を ElementHost で埋め込む(.NET Framework 4 に同梱。追加のインストールは要らない)。
//              再生・一時停止・つまみで移動・Space / ← → / Esc。[受け取る] [要らない] [外部のプレイヤーで開く]。
//              再生できない PC(Windows の N エディションで Media Feature Pack が無いなど)は MediaFailed で知らせ、外部のプレイヤーで開ける
//   組の小窓 … (2.8.0。2-16)右に 1 本ずつの一覧(チェック = 受け取る・題を押すとその本へ飛ぶ・再生中の本を明るく)。
//              下の [チェックした n 本を受け取る(残り m 本は要らない)] で一度に決める(確かめの窓は呼んだ側が出す)。[閉じる] は何もしない
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using System.Windows.Forms.Integration;
using FriendApps;

namespace RequestSender
{
    // まとめ動画を裏で取る順番(スレッドをまたいで使うので中は lock)。鍵はパックの Key
    public sealed class PreviewQueue
    {
        public const long AutoMaxBytes = 300L * 1024 * 1024;   // これより大きいまとめ動画は自動では取らない(押したときだけ)

        readonly object gate = new object();
        readonly List<OutputEntry> order = new List<OutputEntry>();
        readonly HashSet<string> done = new HashSet<string>(), failed = new HashSet<string>(), gone = new HashSet<string>(), wanted = new HashSet<string>(), known = new HashSet<string>();   // known = これまで並べた鍵(取り出したあとに一覧から消えても気づけるように)

        static string KeyOf(OutputEntry e) { return e.Key; }

        // 一覧を調べ直したとき: まとめ動画のあるパックと組を一覧の順に並べ直す(済み・失敗の印は残す。一覧に無いものは消えた扱い)
        public void Reset(IEnumerable<OutputEntry> entries)
        {
            lock (gate)
            {
                var keep = entries.Where(e => e != null && (e.Kind == OutputKind.Pack || e.Kind == OutputKind.Group) && e.Preview != null).ToList();
                var keys = new HashSet<string>(keep.Select(KeyOf));
                foreach (var k in known) if (!keys.Contains(k)) gone.Add(k);
                foreach (var k in keys) { gone.Remove(k); known.Add(k); }
                order.Clear();
                order.AddRange(keep);
            }
        }

        // 「まとめ動画を見る」: 先頭へ。大きくても・前に失敗していても取る
        public void Prioritize(OutputEntry e)
        {
            lock (gate)
            {
                string k = KeyOf(e);
                order.RemoveAll(x => KeyOf(x) == k);
                order.Insert(0, e);
                failed.Remove(k);
                gone.Remove(k);
                wanted.Add(k);
                known.Add(k);
            }
        }

        // 次に取るもの(無ければ null)。取り出したものは並びから外す
        public OutputEntry Next()
        {
            lock (gate)
            {
                while (order.Count > 0)
                {
                    var e = order[0];
                    order.RemoveAt(0);
                    string k = KeyOf(e);
                    if (done.Contains(k) || failed.Contains(k) || gone.Contains(k)) continue;
                    if (e.Preview.Size > AutoMaxBytes && !wanted.Contains(k)) continue;
                    return e;
                }
                return null;
            }
        }

        public void MarkDone(OutputEntry e) { lock (gate) { done.Add(KeyOf(e)); wanted.Remove(KeyOf(e)); } }
        public void MarkFailed(OutputEntry e) { lock (gate) { failed.Add(KeyOf(e)); wanted.Remove(KeyOf(e)); } }
        public void MarkGone(OutputEntry e) { lock (gate) { gone.Add(KeyOf(e)); order.RemoveAll(x => KeyOf(x) == KeyOf(e)); } }
        public bool HasPending()
        {
            lock (gate)
            {
                return order.Any(e => !done.Contains(KeyOf(e)) && !failed.Contains(KeyOf(e)) && !gone.Contains(KeyOf(e)) &&
                                      (e.Preview.Size <= AutoMaxBytes || wanted.Contains(KeyOf(e))));
            }
        }

        public bool IsGone(OutputEntry e) { lock (gate) { return gone.Contains(KeyOf(e)); } }
        public bool IsDone(OutputEntry e) { lock (gate) { return done.Contains(KeyOf(e)); } }
    }

    // Decide = 組の小窓で [チェックした n 本を受け取る(残り m 本は要らない)] を押した(Items の Checked を見る)
    public enum PreviewChoice { None, Receive, Discard, Decide }

    // 組の小窓の 1 本(n・題・まとめ動画の中で始まる秒(負 = 分からない。飛べない)・長さ・受け取るか)。Tag = 呼んだ側のもの(パックの行)
    public sealed class PreviewItem
    {
        public int No;
        public string Title = "";
        public double Start, Duration;
        public bool Checked = true;
        public object Tag;

        public string Text { get { return No + ". " + Title; } }
        public string LengthText { get { return Duration > 0 ? PreviewForm.Clock(Duration) : ""; } }
    }

    // 組の小窓の 1 行: 左の四角 = チェック(受け取る)・残り = その本へ飛ぶ。再生中の本は地を明るく・左にアクセントの線。
    // キー: Space = チェック・Enter = 飛ぶ・↑ ↓ = 前後の行へ
    public sealed class ClipRow : PaintedControl
    {
        public readonly PreviewItem Item;
        bool playing, hover;

        public event Action Toggled, JumpTo;

        public ClipRow(PreviewItem item)
        {
            Item = item;
            SetStyle(ControlStyles.Selectable, true);
            TabStop = true;
            Font = Theme.Body;
            Height = Ui.S(30);
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.CheckButton;
            Name_();
        }

        public bool Playing
        {
            get { return playing; }
            set { if (playing != value) { playing = value; Invalidate(); } }
        }

        int BoxRight { get { return Ui.S(32); } }

        void Name_()
        {
            AccessibleName = Item.Text + (Item.LengthText.Length > 0 ? "(" + Item.LengthText + ")" : "") + (Item.Checked ? " 受け取る" : " 要らない");
        }

        public void Toggle()
        {
            Item.Checked = !Item.Checked;
            Name_();
            Invalidate();
            if (Toggled != null) Toggled();
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left) return;
            Focus();
            if (e.X < BoxRight) Toggle();
            else if (JumpTo != null) JumpTo();
        }

        protected override bool IsInputKey(Keys keyData)
        {
            return keyData == Keys.Up || keyData == Keys.Down || keyData == Keys.Enter || keyData == Keys.Space || base.IsInputKey(keyData);
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            base.OnKeyDown(e);
            if (e.KeyCode == Keys.Space) { Toggle(); e.Handled = true; }
            else if (e.KeyCode == Keys.Enter) { if (JumpTo != null) JumpTo(); e.Handled = true; }
            else if ((e.KeyCode == Keys.Up || e.KeyCode == Keys.Down) && Parent != null) { Parent.SelectNextControl(this, e.KeyCode == Keys.Down, true, false, false); e.Handled = true; }
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            var p = Theme.P;
            var g = e.Graphics;
            Color surface = Parent != null ? Parent.BackColor : p.Panel;
            Color bg = playing ? Theme.Mix(surface, p.Accent, 0.22) : hover ? Theme.Mix(surface, p.Accent, 0.08) : surface;
            using (var b = new SolidBrush(bg)) g.FillRectangle(b, ClientRectangle);
            if (playing) using (var b = new SolidBrush(p.Accent)) g.FillRectangle(b, 0, 0, Ui.S(3), Height);
            int box = Ui.S(14), bx = Ui.S(10), by = (Height - box) / 2;
            var r = new Rectangle(bx, by, box, box);
            using (var b = new SolidBrush(p.Bg)) g.FillRectangle(b, r);
            using (var pen = new Pen(Item.Checked ? p.Accent : p.Muted)) g.DrawRectangle(pen, r);
            if (Item.Checked)
            {
                int q = Ui.S(3);
                using (var b = new SolidBrush(p.Accent)) g.FillRectangle(b, r.X + q, r.Y + q, box - 2 * q + 1, box - 2 * q + 1);
            }
            var flags = TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding;
            string len = Item.LengthText;
            int lenW = len.Length > 0 ? TextRenderer.MeasureText(g, len, Theme.MonoSmall, Size.Empty, flags).Width + Ui.S(10) : 0;
            var tr = new Rectangle(BoxRight, 0, Math.Max(0, Width - BoxRight - lenW - Ui.S(4)), Height);
            TextRenderer.DrawText(g, Item.Text, Font, tr, Item.Checked ? p.Text : p.Muted, flags);
            if (lenW > 0) TextRenderer.DrawText(g, len, Theme.MonoSmall, new Rectangle(Width - lenW, 0, lenW - Ui.S(6), Height), p.Muted, flags | TextFormatFlags.Right);
            if (Focused && ShowFocusCues) using (var pen = new Pen(Theme.Mix(surface, p.Accent, 0.6))) g.DrawRectangle(pen, 1, 1, Width - 3, Height - 3);
        }
    }

    // まとめ動画を再生する小窓。閉じたあと Choice を見て、受け取る・要らないを続ける
    public sealed class PreviewForm : Form, IThemed
    {
        readonly ElementHost host = new ElementHost();
        readonly System.Windows.Controls.MediaElement media = new System.Windows.Controls.MediaElement();
        readonly Btn playBtn = new Btn("一時停止", BtnKind.Normal), receiveBtn = new Btn("受け取る", BtnKind.Primary), discardBtn = new Btn("要らない", BtnKind.Normal),
                     externalBtn = new Btn("外部のプレイヤーで開く", BtnKind.Ghost);
        readonly TrackBar seek = new TrackBar();
        // 音量のつまみ(2.8.1。10-09 ユーザー決定: はじめ 30%)。値は PreviewVolume.Current(本体が settings.json の previewVolume に覚える = 次も同じ)
        readonly TrackBar vol = new TrackBar();
        readonly Lbl volLbl = new Lbl("音量", Tone.Muted), volPct = new Lbl("", Tone.Muted);
        readonly Lbl title = new Lbl("", Tone.Text), timeLbl = new Lbl("0:00 / 0:00", Tone.Muted), note = new Lbl("", Tone.Muted);
        readonly Timer tick = new Timer { Interval = 250 };
        readonly string path;
        bool playing, seeking, opened;
        double durationSec, startSec;
        // 組の小窓(2.8.0): 右の 1 本ずつの一覧と、下の [チェックした n 本を受け取る(残り m 本は要らない)] [閉じる]
        readonly List<PreviewItem> items;
        readonly List<ClipRow> rows = new List<ClipRow>();
        readonly Pane listPane = new Pane { OnPanel = true, Border = true }, rowsPane = new Pane { OnPanel = true };
        readonly Lbl listHead = new Lbl("1 本ずつ(チェック = 受け取る)", Tone.Text), listHint = new Lbl("題を押すと、その本の頭へ飛びます。外した本は「要らない」になります。", Tone.Muted);
        readonly Btn decideBtn = new Btn("", BtnKind.Primary), closeBtn = new Btn("閉じる", BtnKind.Normal);

        public PreviewChoice Choice { get; private set; }
        // 確かめ用(--probe-preview): 開けたか・長さ・いまの位置・失敗の理由
        public bool Opened { get { return opened; } }
        public double Duration { get { return durationSec; } }
        public double PositionSec { get { return opened ? media.Position.TotalSeconds : 0; } }
        public string Error { get; private set; }
        public bool IsGroup { get { return items != null; } }
        public List<PreviewItem> Items { get { return items; } }   // 組の 1 本ずつ(閉じたあと Checked を見る)

        public PreviewForm(string path, string titleText) : this(path, titleText, null, 0) { }

        // items があれば組の小窓(1 本ずつの一覧つき)。start = はじめに再生する位置(秒。その本の previewStart)
        public PreviewForm(string path, string titleText, IList<PreviewItem> groupItems, double start)
        {
            this.path = path;
            items = groupItems != null && groupItems.Count > 0 ? groupItems.ToList() : null;
            startSec = Math.Max(0, start);
            Text = "まとめ動画 - " + titleText;
            Font = Theme.Body;
            KeyPreview = true;
            StartPosition = FormStartPosition.CenterParent;
            MinimumSize = new Size(Ui.S(IsGroup ? 820 : 560), Ui.S(420));
            ClientSize = new Size(Ui.S(IsGroup ? 1120 : 900), Ui.S(IsGroup ? 640 : 600));
            ShowInTaskbar = false;

            title.Text = titleText;
            title.Font = Theme.Bold;
            title.AutoSize = false;
            title.AutoEllipsis = true;
            note.Font = Theme.Small;
            note.AutoSize = false;
            note.AutoEllipsis = true;
            note.Text = "等速・各クリップの左上に「何本目 / 題」。Space で再生 / 一時停止、← → で 5 秒戻る / 進む、↑ ↓ で音量、Esc で閉じる";
            timeLbl.Font = Theme.MonoSmall;
            timeLbl.AutoSize = false;
            timeLbl.TextAlign = ContentAlignment.MiddleRight;

            media.LoadedBehavior = System.Windows.Controls.MediaState.Manual;
            media.UnloadedBehavior = System.Windows.Controls.MediaState.Close;
            media.Stretch = System.Windows.Media.Stretch.Uniform;
            SetVolume(PreviewVolume.Current);   // 2.8.1: はじめ 30%(それまでは 0.8 固定)。つまみを動かした値は閉じるまで保ち、本体が settings.json に覚える
            media.MediaOpened += (s, e) => OnOpened();
            media.MediaFailed += (s, e) => OnFailed(e.ErrorException);
            media.MediaEnded += (s, e) => { SetPlaying(false); };
            var grid = new System.Windows.Controls.Grid { Background = System.Windows.Media.Brushes.Black };
            grid.Children.Add(media);
            host.Child = grid;
            host.BackColor = Color.Black;

            seek.Minimum = 0;
            seek.Maximum = 1000;
            seek.TickStyle = TickStyle.None;
            seek.AutoSize = false;   // 自動の高さ(約 45px)だと下のボタンに重なる
            seek.TabStop = false;
            seek.Enabled = false;
            seek.MouseDown += (s, e) => seeking = true;
            seek.MouseUp += (s, e) => { seeking = false; SeekToBar(); };
            seek.Scroll += (s, e) => { if (!seeking) SeekToBar(); else ShowTime(seek.Value / 1000.0 * durationSec); };
            seek.AccessibleName = "再生する位置";

            vol.Minimum = 0;
            vol.Maximum = 100;
            vol.TickStyle = TickStyle.None;
            vol.AutoSize = false;
            vol.TabStop = false;
            vol.SmallChange = 5;
            vol.LargeChange = 10;
            vol.Value = (int)Math.Round(PreviewVolume.Clamp(PreviewVolume.Current) * 100);
            vol.ValueChanged += (s, e) => SetVolume(vol.Value / 100.0);   // マウス・ホイール・キーのどれでも(Scroll はキーで来ないことがある)
            vol.AccessibleName = "音量";
            volLbl.Font = Theme.Small;
            volLbl.AutoSize = false;
            volLbl.TextAlign = ContentAlignment.MiddleRight;
            volPct.Font = Theme.MonoSmall;
            volPct.AutoSize = false;
            volPct.TextAlign = ContentAlignment.MiddleLeft;

            receiveBtn.Font = Theme.Big;   // 本体の「受け取る」と同じ(大きさも 150 × 40)
            playBtn.Enabled = false;
            playBtn.Click += (s, e) => TogglePlay();
            receiveBtn.Click += (s, e) => { Choice = PreviewChoice.Receive; Close(); };
            discardBtn.Click += (s, e) => { Choice = PreviewChoice.Discard; Close(); };
            externalBtn.Click += (s, e) => OpenExternal();
            tick.Tick += (s, e) => UpdatePosition();

            Controls.AddRange(new Control[] { title, host, seek, volLbl, vol, volPct, timeLbl, playBtn, receiveBtn, discardBtn, externalBtn, note });
            foreach (var b in new[] { playBtn, discardBtn, externalBtn }) b.FitWidth();
            if (IsGroup) BuildList();
            Resize += (s, e) => LayoutParts();
            HandleCreated += (s, e) => Theme.TitleBar(this);
            Load += (s, e) => { ApplyTheme(); Theme.Apply(this); LayoutParts(); Start(); };
            FormClosing += (s, e) => Stop();
        }

        public void ApplyTheme()
        {
            BackColor = Theme.P.Bg;
            seek.BackColor = Theme.P.Bg;
            vol.BackColor = Theme.P.Bg;
        }

        // 組の小窓: 右の一覧(行は n の順)と、下の決めるボタン。1 本だけの小窓の [受け取る] [要らない] は出さない
        void BuildList()
        {
            listHead.Font = Theme.Bold;
            listHint.Font = Theme.Small;
            listHint.AutoSize = false;
            rowsPane.AutoScroll = true;
            foreach (var it in items)
            {
                var row = new ClipRow(it);
                var item = it;
                row.Toggled += UpdateDecide;
                row.JumpTo += () => JumpToItem(item);
                rows.Add(row);
                rowsPane.Controls.Add(row);
            }
            listPane.Controls.AddRange(new Control[] { listHead, rowsPane, listHint });
            receiveBtn.Visible = discardBtn.Visible = false;
            decideBtn.Font = Theme.Bold;
            decideBtn.Click += (s, e) => { Choice = PreviewChoice.Decide; Close(); };
            closeBtn.Click += (s, e) => Close();
            Controls.AddRange(new Control[] { listPane, decideBtn, closeBtn });
            note.Text = "等速・各クリップの左上に「何本目 / 題」。右の一覧の題を押すとその本へ。Space で再生 / 一時停止(一覧ではチェック)、← → で 5 秒、↑ ↓ で音量、Esc で閉じる";
            UpdateDecide();
        }

        // 決めるボタンの文字(テストからも使う): チェックした n 本を受け取る(残り m 本は要らない)。全部チェック・全部外したときは短く
        public static string DecideLabel(int receive, int discard)
        {
            if (receive == 0) return discard + " 本とも要らない";
            if (discard == 0) return "チェックした " + receive + " 本を受け取る";
            return "チェックした " + receive + " 本を受け取る(残り " + discard + " 本は要らない)";
        }

        void UpdateDecide()
        {
            int n = items.Count(i => i.Checked);
            decideBtn.Text = DecideLabel(n, items.Count - n);
            decideBtn.FitWidth();
            decideBtn.AccessibleName = decideBtn.Text;
            LayoutParts();
        }

        void LayoutParts()
        {
            int m = Ui.S(12), w = ClientSize.Width - m * 2, h = ClientSize.Height;
            if (w <= 0) return;
            int listW = IsGroup ? Math.Min(Ui.S(320), w / 3) : 0, videoW = IsGroup ? w - listW - m : w;
            title.SetBounds(m, m, w, Ui.S(22));
            int foot = Ui.S(126);
            host.SetBounds(m, m + Ui.S(28), videoW, Math.Max(Ui.S(120), h - m - Ui.S(28) - foot));
            int y = host.Bottom + Ui.S(6);
            // つまみの行: [位置のつまみ ……][音量 ▭▭▭ 30%][0:00 / 0:00]。音量は時刻の左に固定の幅(狭い窓では位置のつまみが縮む)
            int gap = Ui.S(8), volLblW = Ui.S(34), volW = Ui.S(96), volPctW = Ui.S(40);
            timeLbl.SetBounds(m + videoW - Ui.S(120), y, Ui.S(120), Ui.S(28));
            int vx = timeLbl.Left - gap - volPctW - volW - volLblW;
            volLbl.SetBounds(vx, y, volLblW, Ui.S(28));
            vol.SetBounds(vx + volLblW, y, volW, Ui.S(28));
            volPct.SetBounds(vx + volLblW + volW, y, volPctW, Ui.S(28));
            seek.SetBounds(m, y, Math.Max(Ui.S(80), vx - gap - m), Ui.S(28));
            y += Ui.S(40);
            playBtn.SetBounds(m, y + Ui.S(2), Math.Max(playBtn.Width, Ui.S(110)), Ui.S(36));
            externalBtn.Location = new Point(playBtn.Right + Ui.S(8), y + Ui.S(6));
            discardBtn.Location = new Point(m + w - discardBtn.Width, y + Ui.S(6));
            receiveBtn.SetBounds(discardBtn.Left - Ui.S(8) - Ui.S(150), y, Ui.S(150), Ui.S(40));
            if (IsGroup)
            {
                closeBtn.Location = new Point(m + w - closeBtn.Width, y + Ui.S(6));
                decideBtn.SetBounds(closeBtn.Left - Ui.S(8) - decideBtn.Width, y, decideBtn.Width, Ui.S(40));
                LayoutList(m + videoW + m, m + Ui.S(28), listW, host.Bottom - m - Ui.S(28) + seek.Height + Ui.S(6));
            }
            y += Ui.S(48);
            note.SetBounds(m, y, w, Ui.S(20));
        }

        void LayoutList(int x, int y, int w, int h)
        {
            listPane.SetBounds(x, y, w, h);
            int p = Ui.S(10), iw = w - p * 2;
            listHead.Location = new Point(p, p);
            listHint.SetBounds(p, 0, iw, 0);
            listHint.Wrap(iw);
            listHint.Top = h - p - listHint.Height;
            int top = listHead.Bottom + Ui.S(8);
            rowsPane.SetBounds(1, top, w - 2, Math.Max(Ui.S(60), listHint.Top - Ui.S(6) - top));
            int rowW = rowsPane.ClientSize.Width - (rows.Count * Ui.S(30) > rowsPane.ClientSize.Height ? SystemInformation.VerticalScrollBarWidth : 0);
            for (int i = 0; i < rows.Count; i++) rows[i].SetBounds(0, rowsPane.AutoScrollPosition.Y + i * Ui.S(30), rowW, Ui.S(30));
        }

        void JumpToItem(PreviewItem it)
        {
            if (it.Start < 0) return;                        // 位置が分からない本(PC が長さを測れなかった)
            if (!opened) { startSec = it.Start; return; }   // 開く前なら、開いたらそこから
            media.Position = TimeSpan.FromSeconds(Math.Min(it.Start, Math.Max(0, durationSec - 0.1)));
            if (!playing) TogglePlay();
            UpdatePosition();
        }

        // 再生中の本(始まりがいまの位置より前の、いちばん後の本)を明るくする
        void MarkPlaying(double t)
        {
            if (!IsGroup) return;
            int now = -1;
            for (int i = 0; i < items.Count; i++) if (items[i].Start >= 0 && items[i].Start <= t + 0.05) now = i;
            for (int i = 0; i < rows.Count; i++) rows[i].Playing = i == now;
        }

        void Start()
        {
            try
            {
                media.Source = new Uri(path, UriKind.Absolute);
                media.Play();
                SetPlaying(true);
                tick.Start();
            }
            catch (Exception ex) { OnFailed(ex); }
        }

        void Stop()
        {
            tick.Stop();
            try { media.Stop(); media.Close(); media.Source = null; }   // ファイルを手放す(受け取った・要らないにしたあとに写しを消すため)
            catch (Exception ex) { Log.Write("preview stop: " + ex.Message); }
        }

        void OnOpened()
        {
            opened = true;
            durationSec = media.NaturalDuration.HasTimeSpan ? media.NaturalDuration.TimeSpan.TotalSeconds : 0;
            seek.Enabled = durationSec > 0;
            playBtn.Enabled = true;
            if (startSec > 0 && durationSec > 0) media.Position = TimeSpan.FromSeconds(Math.Min(startSec, Math.Max(0, durationSec - 0.1)));   // 組の 1 本の行から開いた: その本の頭から
            UpdatePosition();
        }

        void OnFailed(Exception ex)
        {
            Log.Write("preview play: " + (ex != null ? ex.Message : "failed"));
            Error = ex != null ? ex.Message : "failed";
            tick.Stop();
            SetPlaying(false);
            playBtn.Enabled = seek.Enabled = false;
            note.Tone = Tone.Error;
            note.Text = "この PC ではアプリの中で再生できませんでした。「外部のプレイヤーで開く」で見られます。" + (ex != null ? "(" + ex.Message + ")" : "");
            externalBtn.Focus();
        }

        void TogglePlay()
        {
            if (!opened) return;
            if (playing) media.Pause();
            else
            {
                if (durationSec > 0 && media.Position.TotalSeconds >= durationSec - 0.2) media.Position = TimeSpan.Zero;   // 終わりまで見たら頭から
                media.Play();
            }
            SetPlaying(!playing);
        }

        void SetPlaying(bool on)
        {
            playing = on;
            playBtn.Text = on ? "一時停止" : "再生";
        }

        void SeekToBar()
        {
            if (!opened || durationSec <= 0) return;
            media.Position = TimeSpan.FromSeconds(seek.Value / 1000.0 * durationSec);
            UpdatePosition();
        }

        // 音量(0〜1)を再生の部品・つまみの右の「30%」・アプリ全体の今の値(PreviewVolume.Current。本体が閉じたあとに覚える)にそろえる
        void SetVolume(double v)
        {
            v = PreviewVolume.Clamp(v);
            PreviewVolume.Current = v;
            try { media.Volume = v; }
            catch (Exception ex) { Log.Write("preview volume: " + ex.Message); }
            volPct.Text = PreviewVolume.Percent(v) + "%";
        }

        public int VolumePercent { get { return PreviewVolume.Percent(PreviewVolume.Current); } }   // 確かめ用(--probe-preview)

        void Jump(double sec)
        {
            if (!opened || durationSec <= 0) return;
            double t = Math.Max(0, Math.Min(durationSec, media.Position.TotalSeconds + sec));
            media.Position = TimeSpan.FromSeconds(t);
            UpdatePosition();
        }

        void UpdatePosition()
        {
            if (!opened) return;
            double t = media.Position.TotalSeconds;
            if (!seeking && durationSec > 0) seek.Value = (int)Math.Max(0, Math.Min(1000, t / durationSec * 1000));
            ShowTime(t);
            MarkPlaying(t);
        }

        void ShowTime(double t)
        {
            timeLbl.Text = Clock(t) + " / " + Clock(durationSec);
        }

        public static string Clock(double sec)
        {
            int s = (int)Math.Max(0, Math.Floor(sec));
            return s >= 3600 ? (s / 3600) + ":" + (s / 60 % 60).ToString("00") + ":" + (s % 60).ToString("00") : (s / 60) + ":" + (s % 60).ToString("00");
        }

        void OpenExternal()
        {
            try
            {
                if (playing) TogglePlay();
                Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                note.Tone = Tone.Error;
                note.Text = "外部のプレイヤーで開けませんでした: " + ex.Message;
            }
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (keyData == Keys.Escape) { Close(); return true; }
            if (keyData == Keys.Space && !(ActiveControl is ButtonBase) && !(ActiveControl is ClipRow)) { TogglePlay(); return true; }   // ボタン・一覧の行では押す・チェック
            if (keyData == Keys.Left) { Jump(-5); return true; }
            if (keyData == Keys.Right) { Jump(5); return true; }
            if ((keyData == Keys.Up || keyData == Keys.Down) && !(ActiveControl is ClipRow))   // 一覧の行では上下の移動(ClipRow.OnKeyDown)
            {
                vol.Value = Math.Max(vol.Minimum, Math.Min(vol.Maximum, vol.Value + (keyData == Keys.Up ? 5 : -5)));   // ValueChanged → SetVolume
                return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { tick.Dispose(); host.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
