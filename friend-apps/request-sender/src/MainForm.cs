// 画面(2.1.0。設計: docs/spec/friend-intake.md の 2-10・docs/spec/friend-intake.md)
//   上の帯: 「送る」「受け取る ●n」・右上に配色の札(A〜D)
//   送る: 左 = 01 送るもの(配信の URL のカード / 動画ファイル)、右 = 02 仕上げ方・03 配信者とメモ(配信者 = 名前のプルダウン + 字幕の色)、下 = 要約・進み具合・「送る」
//   受け取る: MainForm.Receive.cs
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using FriendApps;

namespace RequestSender
{
    public partial class MainForm : Form
    {
        // 通信しない・設定を書かない・右クリックの「送る」を触らない(画面の確認 --screenshot とテスト)
        public static bool Offline;

        const int PollMs = 3 * 60 * 1000;   // 届いたものを確かめる間隔
        const int MaxCards = 10;            // 1回に送れる配信の数(PC 側の上限と同じ)

        readonly string exeDir;
        readonly AppSettings settings;
        readonly TitleLookup titles = new TitleLookup();
        readonly ToolTip tips = new ToolTip();
        readonly System.Windows.Forms.Timer poll = new System.Windows.Forms.Timer();

        // 上の帯とページ
        readonly Pane root = new Pane(), topBar = new Pane { OnPanel = true }, sendPage = new Pane(), recvPage = new Pane();
        readonly Btn tabSend = new Btn("送る", BtnKind.Tab), tabRecv = new Btn("受け取る", BtnKind.Tab);
        readonly Lbl brand = new Lbl("CLIP REQUEST v" + AppInfo.Version, Tone.Muted);
        readonly List<Swatch> swatches = new List<Swatch>();

        // 左: 送るもの
        readonly Pane leftPane = new Pane { OnPanel = true, Border = true };
        readonly SectionHead headWhat = new SectionHead("01", "送るもの");
        readonly Btn modeUrl = new Btn("配信の URL", BtnKind.Toggle), modeVideo = new Btn("動画ファイル", BtnKind.Toggle);
        readonly VStack cardList = new VStack { OnPanel = true };
        readonly List<StreamCard> cards = new List<StreamCard>();
        readonly Btn addCard = new Btn("+ 配信を足す", BtnKind.Normal);
        readonly Lbl helpTime = new Lbl("時刻の入れ方 ― 数字だけ打つ(12345 → 1:23:45)/ ← → で 時・分・秒 を選ぶ / ↑ ↓ で動かす / " +
                                        "YouTube で動画を右クリック →「現在の時刻の動画の URL をコピー」→ 時刻の欄に貼る(Ctrl+V か右クリック)", Tone.Muted);
        readonly Lbl helpMore = new Lbl("10 時間より後の位置は「時」を選んで ↑ か、URL の貼り付けで。区間の前後 2 秒は PC が自動で足します。", Tone.Muted);
        readonly Lbl lTheme = new Lbl("配色", Tone.Muted);
        readonly Pane videoPanel = new Pane { OnPanel = true };
        readonly FileList files = new FileList();
        Field fileField;
        readonly Lbl dropHint = new Lbl("動画のファイルをここへドラッグ(.mp4 .mov .mkv .webm .m4v)\nクリックして選ぶこともできます", Tone.Muted);
        readonly Btn addBtn = new Btn("ファイルを選ぶ…", BtnKind.Normal), removeBtn = new Btn("選んだものを外す", BtnKind.Normal);
        readonly Lbl fileNote = new Lbl("", Tone.Error);
        List<string> memberNames = new List<string>();

        // 右: 仕上げ方・話す人・メモ
        readonly VStack right = new VStack { OnPanel = true, Border = true };
        readonly Radio[] flowRadios = Flow.All.Select(f => new Radio(Flow.Label(f)) { Tag = f }).ToArray();
        readonly Lbl flowExplain = new Lbl("", Tone.Muted);
        readonly Lbl lCut = new Lbl("カット", Tone.Text), lTracks = new Lbl("映像トラックの数", Tone.Text), tracksHint = new Lbl("", Tone.Muted);
        readonly Btn cutNone = new Btn("しない", BtnKind.Toggle), cutSilence = new Btn("無音を削る", BtnKind.Toggle);
        Stepper tracks, speakerCount;
        readonly HRow cutRow = new HRow(), tracksRow = new HRow(), speakerRow = new HRow();
        readonly Check weightsOn = new Check("見どころの重みを指定する(外すと PC の設定のまま)");
        readonly Pane weightsPane = new Pane { Inherit = true };
        readonly Stepper[] weightSteps = new Stepper[3];
        readonly Lbl weightsHint = new Lbl("自動で選ぶ分の、見どころの選び方です。数字が大きいほど重く見ます(1.0 が ふつう・0 は使わない)。", Tone.Muted);
        // 配信者の行(1 行 = 番号 + 名前のプルダウン + 色のカラーコード + 見本と注)
        readonly Pane namesPane = new Pane { Inherit = true };
        readonly ThemedCombo[] speakerNames = new ThemedCombo[Speakers.MaxCount];
        readonly Field[] speakerFields = new Field[Speakers.MaxCount];
        readonly TextBox[] speakerColors = new TextBox[Speakers.MaxCount];
        readonly Field[] colorFields = new Field[Speakers.MaxCount];
        readonly ColorChip[] chips = new ColorChip[Speakers.MaxCount];
        readonly Lbl[] speakerNos = new Lbl[Speakers.MaxCount];
        readonly Lbl speakerHint = new Lbl("配信者を入れると、PC が話者を分けて名前を付けます。色は 6 桁のカラーコード(# なし。例: FF00AA)。空ならメンバーカラー(一覧に無い名前は色なし)です。", Tone.Muted);
        readonly Lbl speakerProblem = new Lbl("", Tone.Error);
        bool speakerStrict;   // 「送る」を押したあとは、誤りを入力のたびに見直す(打っている途中は急かさない)
        readonly Lbl lMemo = new Lbl("メモ(任意。送り先の人が読みます)", Tone.Muted);
        readonly TextBox memo = new TextBox();
        Field memoField;

        // 下の帯
        readonly Pane bottom = new Pane { OnPanel = true };
        readonly Bar bar = new Bar();
        readonly Lbl summary = new Lbl("", Tone.Text), status = new Lbl("", Tone.Muted);
        readonly Btn sendBtn = new Btn("送る", BtnKind.Primary), cancelBtn = new Btn("やめる", BtnKind.Normal);
        readonly LinkLabel sendToLink = new LinkLabel();

        string cut = Cut.None;
        bool showVideo, built, justSent;
        Thread worker;
        volatile bool cancel;
        int arrived;

        public MainForm(string exeDir, string[] initialFiles) : this(exeDir, initialFiles, Program.DataDir ?? Path.Combine(exeDir, "state")) { }

        public MainForm(string exeDir, string[] initialFiles, string dataDir)
        {
            this.exeDir = exeDir;
            state = new LocalState(dataDir);
            settings = state.LoadSettings();
            titles.Offline = Offline;
            Theme.Set(settings.Theme);
            cut = settings.Cut;

            Text = AppInfo.Title;
            Font = Theme.Body;
            AutoScaleMode = AutoScaleMode.None;
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(Ui.S(900), Ui.S(660));
            ClientSize = settings.WindowWidth > 0 ? new Size(settings.WindowWidth, settings.WindowHeight) : new Size(Ui.S(1000), Ui.S(700));
            AllowDrop = true;

            root.Dock = DockStyle.Fill;
            Controls.Add(root);
            BuildTopBar();
            BuildSendPage();
            BuildReceiveLayout();
            root.Controls.AddRange(new Control[] { topBar, sendPage, recvPage });
            LoadMembers();
            AddCard(null);
            AddFiles(initialFiles, false);
            built = true;
            ShowPage(true);
            ShowLeft(files.Items.Count > 0);
            UpdateFlow();
            UpdateAll();
            ApplyTheme();
            LayoutAll();

            Theme.Changed += ApplyTheme;
            Resize += (s, e) => LayoutAll();
            DragEnter += OnDragEnter;
            DragDrop += OnDragDrop;
            Shown += (s, e) =>
            {
                ApplyTheme();
                LayoutAll();
                if (files.Items.Count == 0) cards[0].FocusUrl();   // 開いたら、すぐ URL を貼れる
                if (Offline) return;
                LoadConfig(text => SetStatus(text, Tone.Error));
                Program.MaybeAskSendTo(this);
                UpdateSendToLink();
                poll.Interval = PollMs;
                poll.Tick += (s2, e2) => PollArrivals();
                poll.Start();
                PollArrivals();
            };
            FormClosing += OnClosing;
            Disposed += (s, e) => { Theme.Changed -= ApplyTheme; poll.Dispose(); tips.Dispose(); };
        }

        // ---------------------------------------------------------------- 組み立て
        void BuildTopBar()
        {
            tabSend.Height = tabRecv.Height = Ui.S(40);
            tabSend.Font = tabRecv.Font = Theme.Bold;
            tabSend.Width = Ui.S(76);
            tabSend.Click += (s, e) => ShowPage(true);
            tabRecv.Click += (s, e) => ShowPage(false);
            brand.Font = Theme.MonoSmall;
            lTheme.Font = Theme.Small;
            topBar.Controls.AddRange(new Control[] { tabSend, tabRecv, brand, lTheme });
            foreach (var p in Theme.All)
            {
                var sw = new Swatch(p);
                string name = p.Name;
                sw.Click += (s, e) => { Theme.Set(name); settings.Theme = name; SaveSettings(); };
                tips.SetToolTip(sw, "配色 " + p.Name + ": " + p.Label);
                swatches.Add(sw);
                topBar.Controls.Add(sw);
            }
            UpdateRecvTab();
        }

        void BuildSendPage()
        {
            BuildLeftPane();
            BuildFlowSection();
            BuildSpeakerSection();
            BuildBottomBand();
            sendPage.Controls.AddRange(new Control[] { leftPane, right, bottom });
            SetCut(cut);
            UpdateWeights();
            UpdateSpeakerView();
        }

        // 左: 01 送るもの(配信の URL のカード / 動画ファイル)
        void BuildLeftPane()
        {
            modeUrl.Click += (s, e) => ShowLeft(false);
            modeVideo.Click += (s, e) => ShowLeft(true);
            cardList.Add(addCard, 10, false);
            helpTime.Font = helpMore.Font = Theme.Small;
            addCard.Click += (s, e) => { var c = AddCard(null); ArrangeCards(); c.FocusUrl(); cardList.ScrollControlIntoView(c); };

            files.SelectionMode = SelectionMode.MultiExtended;
            files.AllowDrop = true;
            files.DragEnter += OnDragEnter;
            files.DragDrop += OnDragDrop;
            files.KeyDown += (s, e) => { if (e.KeyCode == Keys.Delete) RemoveSelected(); };
            files.SelectedIndexChanged += (s, e) => UpdateFileView();
            files.AccessibleName = "送る動画";
            fileField = new Field(files);
            fileField.AllowDrop = true;
            fileField.DragEnter += OnDragEnter;
            fileField.DragDrop += OnDragDrop;
            dropHint.AutoSize = false;
            dropHint.TextAlign = ContentAlignment.MiddleCenter;
            dropHint.AllowDrop = true;
            dropHint.DragEnter += OnDragEnter;
            dropHint.DragDrop += OnDragDrop;
            dropHint.Click += (s, e) => PickFiles();
            dropHint.Cursor = Cursors.Hand;
            fileField.Controls.Add(dropHint);
            dropHint.BringToFront();
            addBtn.Click += (s, e) => PickFiles();
            removeBtn.Click += (s, e) => RemoveSelected();
            fileNote.Font = Theme.Small;
            fileNote.AutoSize = false;
            fileNote.AutoEllipsis = true;
            videoPanel.Controls.AddRange(new Control[] { fileField, addBtn, removeBtn, fileNote });
            leftPane.Controls.AddRange(new Control[] { headWhat, modeUrl, modeVideo, cardList, videoPanel, helpTime, helpMore });
        }

        // 右: 02 仕上げ方(どこまでやるか・カット・映像トラックの数・見どころの重み)
        void BuildFlowSection()
        {
            right.Add(new SectionHead("02", "仕上げ方"), 0, true);
            for (int i = 0; i < flowRadios.Length; i++)
            {
                var r = flowRadios[i];
                r.CheckedChanged += (s, e) => { if (((Radio)s).Checked) { UpdateFlow(); UpdateAll(); } };
                right.Add(r, i == 0 ? 8 : 2, false);
            }
            flowRadios[0].Checked = true;   // 起動したときはいつも ①(覚えない)
            flowExplain.Font = Theme.Small;
            right.Add(flowExplain, 4, true);

            cutNone.Click += (s, e) => SetCut(Cut.None);
            cutSilence.Click += (s, e) => SetCut(Cut.Silence);
            cutNone.AccessibleName = "カットしない";
            cutSilence.AccessibleName = "無音の所を削る";
            lCut.AutoSize = lTracks.AutoSize = false;
            lCut.Size = lTracks.Size = new Size(Ui.S(112), Ui.S(20));
            lCut.TextAlign = lTracks.TextAlign = ContentAlignment.MiddleLeft;
            cutRow.Add(lCut, 0).Add(cutNone, 0).Add(cutSilence, 4);
            right.Add(cutRow, 10, false);
            tracks = new Stepper(VideoTracks.Min, VideoTracks.Max, settings.VideoTracks, Ui.S(34), "映像トラックの数");
            tracks.ValueChanged += () => { tracksHint.Text = VideoTracks.Hint(tracks.Value); right.Arrange(); UpdateAll(); };
            tracksRow.Add(lTracks, 0).Add(tracks, 0);
            right.Add(tracksRow, 6, false);
            tracksHint.Font = Theme.Small;
            tracksHint.Text = VideoTracks.Hint(tracks.Value);
            right.Add(tracksHint, 2, true);

            weightsOn.Checked = settings.Weights.Enabled;
            weightsOn.CheckedChanged += (s, e) => { UpdateWeights(); UpdateAll(); };
            right.Add(weightsOn, 10, false);
            string[] wNames = { "音声", "チャット", "コメント" };
            double[] wValues = { settings.Weights.Audio, settings.Weights.Chat, settings.Weights.Comments };
            for (int i = 0; i < 3; i++)
            {
                var l = new Lbl(wNames[i], Tone.Muted) { Font = Theme.Small, Location = new Point(Ui.S(104) * i, 0) };
                var st = new Stepper(0, 30, (int)Math.Round(Weights.Clean(wValues[i]) * 10), Ui.S(40), wNames[i] + "の重み");
                st.Format = v => (v / 10.0).ToString("0.0");
                st.Show_();
                st.Location = new Point(Ui.S(104) * i, Ui.S(18));
                weightSteps[i] = st;
                weightsPane.Controls.Add(l);
                weightsPane.Controls.Add(st);
            }
            weightsPane.Size = new Size(Ui.S(304), Ui.S(46));
            right.Add(weightsPane, 4, false);
            weightsHint.Font = Theme.Small;
            right.Add(weightsHint, 4, true);
        }

        // 右: 03 配信者・メモ(配信者の数と行・メモ)
        void BuildSpeakerSection()
        {
            right.Add(new SectionHead("03", "配信者・メモ"), 14, true);
            speakerCount = new Stepper(0, Speakers.MaxCount, 0, Ui.S(84), "配信者の数");
            speakerCount.Format = v => v == 0 ? "指定しない" : v + " 人";
            speakerCount.Show_();
            speakerCount.ValueChanged += () => { UpdateSpeakerView(); RecheckSpeakers(); right.Arrange(); UpdateAll(); };
            var lSp = new Lbl("配信者の数", Tone.Text) { AutoSize = false, Size = new Size(Ui.S(112), Ui.S(20)), TextAlign = ContentAlignment.MiddleLeft };
            speakerRow.Add(lSp, 0).Add(speakerCount, 0);
            right.Add(speakerRow, 8, false);
            for (int i = 0; i < speakerNames.Length; i++)
            {
                int row = i;
                var name = new ThemedCombo { MaxLength = Speakers.MaxNameLength, AccessibleName = "配信者 " + (i + 1) + " の名前" };
                name.TextChanged += (s, e) => SpeakerEdited(row);
                var color = new TextBox { MaxLength = 40, CharacterCasing = CharacterCasing.Upper, AccessibleName = "配信者 " + (i + 1) + " の字幕の色(カラーコード 6 桁・# なし)" };
                color.KeyPress += (s, e) => { if (!char.IsControl(e.KeyChar) && !Uri.IsHexDigit(e.KeyChar)) e.Handled = true; };   // 打てるのは 16 進の文字だけ
                color.TextChanged += (s, e) => ColorEdited(row);
                color.HandleCreated += (s, e) => Ui.Cue(color, "RRGGBB");
                speakerNames[i] = name;
                speakerColors[i] = color;
                speakerFields[i] = new Field(name);
                colorFields[i] = new Field(color);
                color.Font = Theme.Mono;
                chips[i] = new ColorChip();
                speakerNos[i] = new Lbl((i + 1) + ".", Tone.Muted) { Font = Theme.MonoSmall };
                namesPane.Controls.Add(speakerNos[i]);
                namesPane.Controls.Add(speakerFields[i]);
                namesPane.Controls.Add(colorFields[i]);
                namesPane.Controls.Add(chips[i]);
            }
            right.Add(namesPane, 6, true);
            namesPane.AutoScroll = true;
            right.Shrink = namesPane;
            right.ShrinkMin = SpeakerRowsHeight(2) + Ui.S(18);   // 2 行と 3 行目の半分(続きがあると分かる)
            right.ShrinkSlack = Ui.S(15);                         // 行の半分より小さいはみ出しでは縮めない
            namesPane.Resize += (s, e) => { if (built) UpdateSpeakerView(); };
            speakerProblem.Font = Theme.Small;
            right.Add(speakerProblem, 4, true);
            right.SetShown(speakerProblem, false);
            speakerHint.Font = Theme.Small;
            right.Add(speakerHint, 4, true);
            lMemo.Font = Theme.Small;
            right.Add(lMemo, 10, false);
            memo.Multiline = true;
            memo.ScrollBars = ScrollBars.Vertical;
            memo.AcceptsReturn = true;
            memo.MaxLength = 2000;
            memo.AccessibleName = "メモ";
            memoField = new Field(memo);
            right.Add(memoField, 4, true);
            right.Fill = memoField;
        }

        // 下の帯: 要約・進み具合・「送る」
        void BuildBottomBand()
        {
            summary.AutoSize = status.AutoSize = false;
            summary.AutoEllipsis = status.AutoEllipsis = true;
            status.Font = Theme.Small;
            sendBtn.Font = Theme.Big;
            sendBtn.Click += (s, e) => StartSend();
            tips.SetToolTip(sendBtn, "Ctrl+Enter でも送れます");
            cancelBtn.Click += (s, e) => { cancel = true; SetStatus("やめています…", Tone.Muted); };
            cancelBtn.Visible = false;
            sendToLink.AutoSize = true;
            sendToLink.Font = Theme.Small;
            sendToLink.Text = "動画の右クリックの「送る」にも出す";
            sendToLink.Visible = false;
            sendToLink.LinkClicked += (s, e) =>
            {
                if (Program.CreateSendTo(this)) SetStatus("右クリック →「送る」→「切り抜き依頼」で送れるようになりました。", Tone.Muted);
                UpdateSendToLink();
            };
            bottom.Controls.AddRange(new Control[] { bar, summary, status, sendToLink, cancelBtn, sendBtn });
        }

        // ---------------------------------------------------------------- 並べる
        void LayoutAll()
        {
            if (!built || WindowState == FormWindowState.Minimized) return;
            int w = root.ClientSize.Width, h = root.ClientSize.Height, top = Ui.S(40), m = Ui.S(12);
            topBar.SetBounds(0, 0, w, top);
            tabSend.Location = new Point(m, 0);
            tabRecv.Location = new Point(tabSend.Right + Ui.S(4), 0);
            int x = w - m;
            for (int i = swatches.Count - 1; i >= 0; i--)
            {
                x -= swatches[i].Width;
                swatches[i].Location = new Point(x, (top - swatches[i].Height) / 2);
                x -= Ui.S(4);
            }
            lTheme.Location = new Point(x - Ui.S(2) - lTheme.Width, (top - lTheme.Height) / 2);
            x = lTheme.Left;
            brand.Location = new Point(x - Ui.S(16) - brand.Width, (top - brand.Height) / 2);
            brand.Visible = brand.Left > tabRecv.Right + m;

            int ph = h - top;
            sendPage.SetBounds(0, top, w, ph);
            recvPage.SetBounds(0, top, w, ph);

            int bottomH = Ui.S(64), rightW = Ui.S(340), bodyH = ph - bottomH - m * 2;
            leftPane.SetBounds(m, m, w - rightW - m * 3, bodyH);
            right.SetBounds(w - rightW - m, m, rightW, bodyH);
            bottom.SetBounds(0, ph - bottomH, w, bottomH);

            headWhat.SetBounds(m, m, leftPane.Width - m * 2, Ui.S(20));
            modeUrl.Location = new Point(m, Ui.S(40));
            modeVideo.Location = new Point(modeUrl.Right + Ui.S(4), Ui.S(40));
            var body = new Rectangle(1, Ui.S(76), leftPane.Width - 2, leftPane.Height - Ui.S(76) - 1);
            videoPanel.Bounds = body;
            // 配信の URL の側は、下に時刻の入れ方を固定で出す(カードが増えても隠れない)
            helpMore.Wrap(leftPane.Width - m * 2);
            helpMore.Location = new Point(m, leftPane.Height - helpMore.Height - Ui.S(8));
            helpTime.Wrap(leftPane.Width - m * 2);
            helpTime.Location = new Point(m, helpMore.Top - helpTime.Height - Ui.S(2));
            cardList.Bounds = new Rectangle(body.X, body.Y, body.Width, helpTime.Top - Ui.S(6) - body.Y);
            ArrangeCards();
            LayoutVideo();
            right.Arrange();
            UpdateSpeakerView();
            right.Arrange();

            bar.SetBounds(0, 0, w, Ui.S(3));
            sendBtn.SetBounds(w - m - Ui.S(150), Ui.S(14), Ui.S(150), Ui.S(40));
            cancelBtn.SetBounds(sendBtn.Left - Ui.S(8) - Ui.S(84), Ui.S(20), Ui.S(84), Ui.S(28));
            int textW = (cancelBtn.Visible ? cancelBtn.Left : sendBtn.Left) - m * 2 - Ui.S(4);
            summary.SetBounds(Ui.S(16), status.Text.Length > 0 ? Ui.S(12) : Ui.S(22), textW, Ui.S(20));   // 知らせが無い間は、要約を帯の中央に
            status.SetBounds(Ui.S(16), Ui.S(34), textW - (sendToLink.Visible ? sendToLink.Width + m : 0), Ui.S(20));
            sendToLink.Location = new Point(Ui.S(16) + textW - sendToLink.Width, Ui.S(35));
            LayoutReceive();
        }

        void ArrangeCards()
        {
            foreach (var c in cards) c.Arrange();
            cardList.Arrange();
        }

        void LayoutVideo()
        {
            int m = Ui.S(12), w = videoPanel.Width - m * 2, h = videoPanel.Height;
            int below = Ui.S(70);
            fileField.SetBounds(m, 0, w, Math.Max(Ui.S(80), h - below - m));
            dropHint.SetBounds(1, 1, fileField.Width - 2, fileField.Height - 2);
            int y = fileField.Bottom + Ui.S(8);
            addBtn.Location = new Point(m, y);
            removeBtn.Location = new Point(addBtn.Right + Ui.S(6), y);
            y += Ui.S(32);
            fileNote.SetBounds(m, y, w, Ui.S(18));
        }

        // 配信者の行: 選んだ人数の分だけ、1 行ずつ縦に並べる(番号 | 名前 | 色 | 見本と注)。名前は残りの幅いっぱい。
        // 行の入れ物の高さは右の列が決める(入りきらないとき、2 行半までに縮めれば入るなら縮めて、入れ物の中でスクロール。VStack.Shrink)
        const string NoteMember = "メンバーカラー", NoteNone = "色なし";
        const int SpeakerRowPx = 30, SpeakerFieldPx = 26;   // 1 行の高さ・欄の高さ(行の間は 4)

        // n 行ぶんの高さ(最後の行の下の隙間は含めない)
        static int SpeakerRowsHeight(int n)
        {
            return n > 0 ? n * Ui.S(SpeakerRowPx) - (Ui.S(SpeakerRowPx) - Ui.S(SpeakerFieldPx)) : 0;
        }

        void UpdateSpeakerView()
        {
            int n = speakerCount.Value, rowH = Ui.S(SpeakerRowPx), fieldH = Ui.S(SpeakerFieldPx), gap = Ui.S(4);
            int natural = SpeakerRowsHeight(n);
            namesPane.AutoScrollMinSize = new Size(0, natural);
            // 幅は行の入れ物の幅。右の列が入れ物を縮めたとき(中でスクロールする)は、縦のスクロールバーの分を除く(横のスクロールバーを出さない)
            bool scrolls = n > 0 && namesPane.Height > 0 && namesPane.Height < natural;
            int cw = Math.Max(Ui.S(240), (namesPane.Width > 0 ? namesPane.Width - (scrolls ? SystemInformation.VerticalScrollBarWidth : 0) : right.ClientSize.Width - right.Pad * 2));
            int noW = Ui.S(22);
            int colorW = TextRenderer.MeasureText("FFFFFF", Theme.Mono, Size.Empty, TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix).Width + Ui.S(18);
            int noteW = Math.Max(TextRenderer.MeasureText(NoteMember, Theme.Small, Size.Empty, TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix).Width,
                                 TextRenderer.MeasureText(NoteNone, Theme.Small, Size.Empty, TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix).Width);
            int chipW = ColorChip.BoxSize + Ui.S(6) + noteW + Ui.S(2);
            int nameW = Math.Max(Ui.S(90), cw - noW - colorW - chipW - gap * 2);
            chipW = Math.Min(chipW, Math.Max(ColorChip.BoxSize, cw - noW - nameW - colorW - gap * 2));   // 狭いときは注を「…」で切る(横にはみ出さない)
            int top = namesPane.AutoScrollPosition.Y;   // 中でスクロールしているときの位置
            for (int i = 0; i < speakerNames.Length; i++)
            {
                bool on = i < n;
                speakerNos[i].Visible = speakerFields[i].Visible = colorFields[i].Visible = chips[i].Visible = on;
                if (!on) continue;
                int y = top + i * rowH;
                speakerNos[i].Location = new Point(0, y + Ui.S(6));
                speakerFields[i].SetBounds(noW, y, nameW, fieldH);
                colorFields[i].SetBounds(noW + nameW + gap, y, colorW, fieldH);
                chips[i].SetBounds(noW + nameW + gap + colorW + gap, y, chipW, fieldH);
            }
            namesPane.PerformLayout();   // 行を並べ直したあとでスクロールバーを決め直す(大きさが変わった直後の、前の幅での横のスクロールバーを残さない)
            right.SetShown(namesPane, n > 0);
        }

        // 1 行の見本と注を直す(名前か色が変わったとき)。6 桁そろったときだけ色を出す。
        // 色が空 → 名前がメンバーの一覧にあれば「メンバーカラー」・無ければ「色なし」(名前も空なら何も出さない)
        void UpdateSpeakerRow(int i)
        {
            string name = speakerNames[i].Text.Trim(), colorText = speakerColors[i].Text;
            string hex = Speakers.ParseColor(colorText);
            chips[i].Swatch = hex != null ? (Color?)ColorTranslator.FromHtml("#" + hex) : null;
            string note = "", tip = null;
            if (!Speakers.HasColorText(colorText) && name.Length > 0)
            {
                bool member = memberNames.Contains(name);
                note = member ? NoteMember : NoteNone;
                tip = member ? "色が空なので、字幕はこの人のメンバーカラーになります" : "一覧に無い名前で色が空なので、字幕は色なしになります(色を入れるとその色になります)";
            }
            chips[i].SetNote(note, note == NoteMember);
            Ui.Tip(chips[i], tip ?? "");
        }

        void SpeakerEdited(int i)
        {
            UpdateSpeakerRow(i);
            RecheckSpeakers();
        }

        bool fixingColor;

        // 色の欄: 貼った「#ff00aa」や前後の空白は「FF00AA」に直す(打てるのは 16 進の文字だけ・6 文字まで)
        void ColorEdited(int i)
        {
            if (fixingColor) return;
            var t = speakerColors[i];
            string clean = Speakers.CleanColor(t.Text);
            if (clean != t.Text)
            {
                fixingColor = true;
                try { t.Text = clean; t.SelectionStart = clean.Length; }
                finally { fixingColor = false; }
            }
            SpeakerEdited(i);
        }

        // 画面の行 → 依頼に入れるもの(人数の範囲の行だけ)
        SpeakerSet CurrentSpeakers()
        {
            int n = speakerCount.Value;
            var set = new SpeakerSet { Count = n };
            for (int i = 0; i < n; i++) set.Rows.Add(new SpeakerRow(speakerNames[i].Text, speakerColors[i].Text));
            return set;
        }

        // 送る前の検査: 誤りのある欄に枠の色を付けて理由を出す。-> 最初の誤りの欄(無ければ null)
        Control ValidateSpeakers()
        {
            speakerStrict = true;
            return ShowSpeakerProblems();
        }

        void RecheckSpeakers()
        {
            if (speakerStrict) ShowSpeakerProblems();
        }

        Control ShowSpeakerProblems()
        {
            var problems = Speakers.Problems(CurrentSpeakers());
            for (int i = 0; i < speakerNames.Length; i++)
            {
                speakerFields[i].Error = problems.Any(p => p.Index == i && !p.OnColor);
                colorFields[i].Error = problems.Any(p => p.Index == i && p.OnColor);
            }
            speakerProblem.Text = string.Join(" / ", problems.Take(3).Select(p => "配信者 " + (p.Index + 1) + ": " + p.Message)) + (problems.Count > 3 ? " ほか " + (problems.Count - 3) + " 件" : "");
            right.SetShown(speakerProblem, problems.Count > 0);
            right.Arrange();
            if (problems.Count == 0) return null;
            var first = problems[0];
            return first.OnColor ? (Control)speakerColors[first.Index] : speakerNames[first.Index];
        }

        // ---------------------------------------------------------------- 配色
        void ApplyTheme()
        {
            BackColor = Theme.P.Bg;
            ForeColor = Theme.P.Text;
            Theme.Apply(root);
            sendToLink.LinkColor = sendToLink.ActiveLinkColor = Theme.P.Accent;
            sendToLink.BackColor = Theme.P.Panel;
            ThemeReceive();
            Theme.TitleBar(this);
            Invalidate(true);
        }

        // ---------------------------------------------------------------- ページと左の切り替え
        public void ShowPage(bool send)
        {
            sendPage.Visible = send;
            recvPage.Visible = !send;
            tabSend.On = send;
            tabRecv.On = !send;
            if (!send && !Offline && (!listedOnce || arrived != entries.Count)) RefreshList();
        }

        void ShowLeft(bool video)
        {
            showVideo = video;
            cardList.Visible = helpTime.Visible = helpMore.Visible = !video;
            videoPanel.Visible = video;
            modeUrl.On = !video;
            modeVideo.On = video;
            if (!video) ArrangeCards();
        }

        void UpdateModeButtons()
        {
            int n = cards.Count(c => !c.IsBlank);
            modeUrl.Text = n > 0 ? "配信の URL(" + n + ")" : "配信の URL";
            modeVideo.Text = files.Items.Count > 0 ? "動画ファイル(" + files.Items.Count + ")" : "動画ファイル";
            modeUrl.FitWidth();
            modeVideo.FitWidth();
            modeVideo.Location = new Point(modeUrl.Right + Ui.S(4), modeVideo.Top);
        }

        // ---------------------------------------------------------------- 配信のカード
        StreamCard AddCard(string url)
        {
            var c = new StreamCard(cards.Count > 0 ? cards[cards.Count - 1].TopCount : settings.Top);
            c.Changed += () => { cardList.Arrange(); UpdateAll(); };
            c.RemoveClicked += () => RemoveCard(c);
            c.IdChanged += id => titles.Request(id, (i, t) => OnUi(() => { foreach (var x in cards) x.SetTitle(i, t); }));
            c.MoreUrls += lines =>
            {
                foreach (string line in lines.Take(Math.Max(0, MaxCards - cards.Count))) AddCard(line);
                ArrangeCards();
                UpdateAll();
            };
            cards.Add(c);
            cardList.Insert(cardList.IndexOf(addCard), c, cards.Count == 1 ? 0 : 8, true);
            Theme.Apply(c);
            c.SetManual(SelectedFlow == Flow.Manual);
            if (!string.IsNullOrEmpty(url)) c.SetUrlLines(url);
            addCard.Enabled = cards.Count < MaxCards;
            return c;
        }

        void RemoveCard(StreamCard c)
        {
            if (Busy) return;
            cards.Remove(c);
            cardList.Remove(c);
            c.Dispose();
            if (cards.Count == 0) AddCard(null);
            addCard.Enabled = cards.Count < MaxCards;
            ArrangeCards();
            UpdateAll();
        }

        // ---------------------------------------------------------------- 仕上げ方
        string SelectedFlow
        {
            get
            {
                var r = flowRadios.FirstOrDefault(x => x.Checked);
                return r != null ? (string)r.Tag : Flow.Auto;
            }
        }

        void UpdateFlow()
        {
            string f = SelectedFlow;
            flowExplain.Text = Flow.Explain(f);
            bool auto = f == Flow.Auto;   // ②③ はパックを PC で作らないので、カットとトラックは使わない
            cutRow.Enabled = tracksRow.Enabled = tracksHint.Enabled = auto;
            foreach (var c in cards) c.SetManual(f == Flow.Manual);
            right.Arrange();
        }

        void SetCut(string value)
        {
            cut = Cut.IsValid(value) ? value : Cut.None;
            cutNone.On = cut == Cut.None;
            cutSilence.On = cut == Cut.Silence;
            UpdateAll();
        }

        // 重みの欄は「指定する」を入れたときだけ出す(使わない人の画面を増やさない)
        void UpdateWeights()
        {
            foreach (var s in weightSteps) if (s != null) s.Enabled = weightsOn.Checked && weightsOn.Enabled;
            right.SetShown(weightsPane, weightsOn.Checked);
            right.SetShown(weightsHint, weightsOn.Checked);
            right.Arrange();
        }

        Weights CurrentWeights()
        {
            return new Weights { Enabled = weightsOn.Checked, Audio = weightSteps[0].Value / 10.0, Chat = weightSteps[1].Value / 10.0, Comments = weightSteps[2].Value / 10.0 };
        }

        // ---------------------------------------------------------------- 要約(下の帯にいつも出す)
        void UpdateAll()
        {
            if (!built) return;
            UpdateModeButtons();
            string f = SelectedFlow;
            var live = cards.Where(c => !c.IsBlank).ToList();
            var parts = new List<string>();
            if (live.Count > 0)
            {
                int ranges = live.Sum(c => c.ValidRanges().Count), auto = live.Sum(c => Math.Max(0, c.TopCount - c.ValidRanges().Count));
                parts.Add("配信 " + live.Count + " 本" + (f == Flow.Manual ? "" : "(指定 " + ranges + " + 自動 " + auto + ")"));
            }
            if (files.Items.Count > 0) parts.Add("動画 " + files.Items.Count + " 本");
            if (parts.Count == 0)
            {
                summary.Font = justSent ? Theme.Bold : Theme.Body;
                summary.Tone = justSent ? Tone.Accent : Tone.Muted;
                summary.Text = justSent ? "送りました ✓" : "送るものを入れてください(配信の URL か、動画のファイル)";
                return;
            }
            justSent = false;
            summary.Font = Theme.Body;
            parts.Add(Flow.Label(f).Split('(')[0]);
            if (f == Flow.Auto) { parts.Add(Cut.Label(cut)); parts.Add("トラック " + tracks.Value); }
            if (speakerCount.Value > 0) parts.Add("配信者 " + speakerCount.Value + " 人");
            summary.Tone = Tone.Text;
            summary.Text = string.Join(" ・ ", parts);
        }

        // ---------------------------------------------------------------- 設定(覚える)
        void LoadMembers()
        {
            memberNames = Members.LoadNames(Path.Combine(exeDir, "members.json"));
            for (int i = 0; i < speakerNames.Length; i++)
            {
                speakerNames[i].SetNames(memberNames);   // 一覧から選べる・打つと絞られる・一覧に無い名前も打てる
                UpdateSpeakerRow(i);
            }
        }

        void SaveSettings()
        {
            if (Offline || !built) return;
            try
            {
                settings.Cut = cut;
                settings.VideoTracks = tracks.Value;
                if (cards.Count > 0) settings.Top = cards[0].TopCount;
                settings.Weights = CurrentWeights();
                settings.Theme = Theme.P.Name;
                if (WindowState == FormWindowState.Normal) { settings.WindowWidth = ClientSize.Width; settings.WindowHeight = ClientSize.Height; }
                state.SaveSettings(settings);
            }
            catch (Exception ex) { Log.Write("settings: " + ex.Message); }
        }

        // 送る・受け取るための鍵(config.json)。読めなければ理由を onError に渡して null(onError が null なら黙って null)
        Config LoadConfig(Action<string> onError)
        {
            try
            {
                return Config.Load(Path.Combine(exeDir, "config.json"));
            }
            catch (Exception ex)
            {
                if (onError != null) onError(ConfigProblem(ex));
                return null;
            }
        }

        static string ConfigProblem(Exception ex)
        {
            if (ex is FileNotFoundException) return "config.json(送るための鍵)が見つかりません。RequestSender.exe と同じフォルダに置いてください。";
            return "config.json が読めません。送り先の人にもう一度もらってください。(" + ex.Message + ")";
        }

        void UpdateSendToLink()
        {
            sendToLink.Visible = !Offline && !SendToShortcut.Exists();
            LayoutAll();
        }

        // ---------------------------------------------------------------- 動画の出し入れ
        void OnDragEnter(object sender, DragEventArgs e)
        {
            if (Busy) { e.Effect = DragDropEffects.None; return; }
            if (e.Data.GetDataPresent(DataFormats.FileDrop)) e.Effect = DragDropEffects.Copy;
            else if (e.Data.GetDataPresent(DataFormats.UnicodeText) || e.Data.GetDataPresent(DataFormats.Text)) e.Effect = DragDropEffects.Copy;
            else e.Effect = DragDropEffects.None;
        }

        void OnDragDrop(object sender, DragEventArgs e)
        {
            if (Busy) return;
            var paths = e.Data.GetData(DataFormats.FileDrop) as string[];
            if (paths != null) { ShowPage(true); ShowLeft(true); AddFiles(paths, true); return; }
            // ブラウザのアドレスをドラッグしたとき: 空いているカード(無ければ新しいカード)に入れる
            string text = (e.Data.GetData(DataFormats.UnicodeText) ?? e.Data.GetData(DataFormats.Text)) as string;
            if (string.IsNullOrWhiteSpace(text)) return;
            ShowPage(true);
            ShowLeft(false);
            var c = cards.FirstOrDefault(x => !x.HasUrlText) ?? (cards.Count < MaxCards ? AddCard(null) : null);
            if (c == null) return;
            c.SetUrlLines(text);
            ArrangeCards();
            UpdateAll();
        }

        void PickFiles()
        {
            if (Busy) return;
            using (var d = new OpenFileDialog())
            {
                d.Title = "送る動画を選ぶ";
                d.Multiselect = true;
                d.Filter = "動画|" + string.Join(";", Validation.VideoExts.Select(x => "*" + x)) + "|すべてのファイル|*.*";
                if (d.ShowDialog(this) == DialogResult.OK) AddFiles(d.FileNames, true);
            }
        }

        void AddFiles(IEnumerable<string> paths, bool fromUser)
        {
            var skipped = new List<string>();
            foreach (string p in paths)
            {
                string full;
                try { full = Path.GetFullPath(p); }
                catch (Exception) { skipped.Add(p); continue; }
                if (Directory.Exists(full) || !File.Exists(full) || !Validation.IsVideoFile(full)) { skipped.Add(Path.GetFileName(full)); continue; }
                if (!files.Items.Cast<string>().Any(x => string.Equals(x, full, StringComparison.OrdinalIgnoreCase))) files.Items.Add(full);
            }
            fileNote.Text = skipped.Count == 0 ? "" :
                "動画ではないので入れませんでした(" + string.Join(" / ", Validation.VideoExts) + " だけ): " +
                string.Join("、", skipped.Take(5)) + (skipped.Count > 5 ? " ほか " + (skipped.Count - 5) + " 個" : "");
            UpdateFileView();
            UpdateAll();
        }

        void RemoveSelected()
        {
            if (Busy) return;
            foreach (var item in files.SelectedItems.Cast<object>().ToList()) files.Items.Remove(item);
            UpdateFileView();
            UpdateAll();
        }

        void UpdateFileView()
        {
            dropHint.Visible = files.Items.Count == 0;   // 重ねず、どちらか一方だけ出す
            files.Visible = files.Items.Count > 0;
            removeBtn.Enabled = files.SelectedItems.Count > 0 && !Busy;
        }

        // ---------------------------------------------------------------- 送る
        bool fakeBusy;   // 画面の確認(--state busy)
        bool Busy { get { return fakeBusy || (worker != null && worker.IsAlive); } }

        // Ctrl+Enter = 「送る」(送るの画面で、送っている途中でないとき。どの欄からでも。メモの欄でも改行にしない)
        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (keyData == (Keys.Control | Keys.Enter) && tabSend.On)
            {
                if (sendBtn.Enabled) StartSend();
                return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        void StartSend()
        {
            if (Busy) return;
            var input = CollectInput();
            if (input == null || Offline) return;   // 画面の確認・テストでは送らない
            Config config = LoadConfig(text => SetStatus(text, Tone.Error));
            if (config == null) return;
            RunSend(input, config);
        }

        // 画面の入力を送る内容にまとめる。誤りがあれば欄に理由を出して null
        SendInput CollectInput()
        {
            string flow = SelectedFlow;
            var seen = new HashSet<string>();
            var items = new List<UrlItem>();
            Control bad = null;
            foreach (var c in cards)
            {
                if (c.IsBlank) continue;
                var b = c.Validate_(seen);
                if (b == null) items.Add(c.ToItem());
                else if (bad == null) bad = b;
            }
            ArrangeCards();
            Control badSpeaker = ValidateSpeakers();   // 色だけで名前が空・色が 6 桁でない行
            if (bad != null || badSpeaker != null)
            {
                // 誤りのある欄へ移す(理由はその欄の下に出ている)。配信の URL の誤りを先に
                if (bad != null)
                {
                    ShowLeft(false);
                    cardList.ScrollControlIntoView(bad);
                    bad.Select();
                }
                else
                {
                    namesPane.ScrollControlIntoView(badSpeaker);   // 行が多いときは行の入れ物の中も
                    right.ScrollControlIntoView(badSpeaker);
                    badSpeaker.Select();
                }
                SetStatus("⚠ 直す所があります(枠の色が変わった欄の下に理由があります)。直してから、もう一度「送る」を押してください。", Tone.Error);
                return null;
            }
            var input = new SendInput
            {
                Videos = files.Items.Cast<string>().ToList(),
                Items = items,
                Memo = memo.Text.Trim(),
                People = CurrentSpeakers(),
                Flow = flow,
                VideoTracks = tracks.Value,
                Cut = cut,
                Weights = CurrentWeights(),
            };
            var errs = Sending.Check(input);
            if (errs.Count > 0)
            {
                SetStatus(string.Join(" / ", errs.Take(3)) + (errs.Count > 3 ? " ほか " + (errs.Count - 3) + " 件" : ""), Tone.Error);
                if (input.Videos.Count == 0 && input.Items.Count == 0) { ShowLeft(false); cards[0].FocusUrl(); }
                return null;
            }
            return input;
        }

        // 裏のスレッドで送る(進み具合は画面のスレッドへ渡す)
        void RunSend(SendInput input, Config config)
        {
            cancel = false;
            SetBusy(true);
            bar.Value = 0;
            SetStatus("送る準備をしています…", Tone.Muted);
            Log.Write("send: videos=" + input.Videos.Count + " urls=" + input.Items.Count + " ranges=" + input.Items.Sum(i => i.Ranges.Count) + " flow=" + input.Flow);
            var client = new DropboxClient(config) { IsCanceled = () => cancel, Log = Log.Write };
            var sending = new Sending(client);
            int lastPermille = -1;
            string lastStep = null;
            sending.Progress = p =>
            {
                // 256KB ごとに呼ばれるので、表示が変わるときだけ画面へ渡す
                int permille = (int)Math.Max(0, Math.Min(1000, p.Done * 1000 / Math.Max(1, p.Total)));
                if (permille == lastPermille && p.Step == lastStep) return;
                lastPermille = permille;
                lastStep = p.Step;
                OnUi(() => ShowProgress(input, p, permille));
            };
            worker = new Thread(() =>
            {
                string error = null;
                try { sending.Run(input); }
                catch (CanceledException) { error = "やめました。"; }
                catch (DropboxException ex) { error = ex.Message; Log.Write("dropbox " + ex.Status + ": " + ex.Body); }
                catch (IOException ex) { error = "ファイルを読めませんでした: " + ex.Message; Log.Write("io: " + ex); }
                catch (UnauthorizedAccessException ex) { error = "ファイルを読めませんでした: " + ex.Message; Log.Write("io: " + ex); }
                catch (Exception ex) { error = "思わぬエラーで送れませんでした: " + ex.Message; Log.Write("error: " + ex); }
                OnUi(() => Finished(input, sending.Sent, error));
            });
            worker.IsBackground = true;
            worker.Start();
        }

        void ShowProgress(SendInput input, SendProgress p, int permille)
        {
            if (!Busy) return;
            bar.Value = permille;
            string size = input.Videos.Count > 0 ? "(" + Mb(p.Done) + " / " + Mb(p.Total) + ")" : "";
            SetStatus(p.Step + "… " + size, Tone.Muted);
        }

        void Finished(SendInput input, List<string> sent, string error)
        {
            worker = null;
            SetBusy(false);
            if (error == null)
            {
                Log.Write("send: ok");
                bar.Value = 1000;
                SaveSettings();
                ShowSent(input.Flow == Flow.Auto);
                return;
            }
            Log.Write("send: failed: " + error);
            bar.Value = 0;
            string msg = "送れませんでした: " + error;
            if (sent.Count > 0)
            {
                msg += "(" + string.Join("・", sent) + " は送れています。残りだけもう一度送ってください)";
                if (sent.Any(x => x.StartsWith("配信"))) ClearInputs(true, false);
            }
            SetStatus(msg, Tone.Error);
        }

        // 送り終えた: 入れたものを空にして、下の帯に「送りました ✓」を大きく出す(次に何か入れるまで)
        void ShowSent(bool auto)
        {
            ClearInputs(true, true);
            justSent = true;
            SetStatus(auto ? "できあがると「受け取る」に届きます(時間がかかります)。続けて送ることもできます" : "続けて送ることもできます", Tone.Muted);
            UpdateAll();
        }

        // 送ったものを空にする(覚える設定はそのまま)
        void ClearInputs(bool urls, bool rest)
        {
            if (urls)
            {
                settings.Top = cards.Count > 0 ? cards[0].TopCount : settings.Top;
                foreach (var c in cards.ToList()) { cardList.Remove(c); c.Dispose(); }
                cards.Clear();
                AddCard(null);
            }
            if (rest)
            {
                files.Items.Clear();
                fileNote.Text = "";
                memo.Clear();
                speakerCount.Value = 0;
                foreach (var c in speakerNames) c.Text = "";
                foreach (var c in speakerColors) c.Text = "";
                speakerStrict = false;
                ShowSpeakerProblems();
                UpdateFileView();
            }
            ArrangeCards();
            UpdateAll();
        }

        void SetBusy(bool busy)
        {
            if (Offline) fakeBusy = busy;
            sendBtn.Enabled = !busy;
            sendBtn.Text = busy ? "送っています…" : "送る";
            cancelBtn.Visible = busy;
            cancelBtn.Enabled = true;
            addBtn.Enabled = !busy;
            removeBtn.Enabled = !busy && files.SelectedItems.Count > 0;
            addCard.Enabled = !busy && cards.Count < MaxCards;
            foreach (var c in cards) c.SetBusy(busy);
            memo.ReadOnly = busy;
            foreach (var c in speakerNames) c.Enabled = !busy;   // プルダウンには ReadOnly が無い
            foreach (var c in speakerColors) c.ReadOnly = busy;
            speakerCount.Enabled = tracks.Enabled = !busy;
            cutNone.Enabled = cutSilence.Enabled = weightsOn.Enabled = !busy;
            foreach (var r in flowRadios) r.Enabled = !busy;
            if (!busy) { UpdateFlow(); UpdateWeights(); }
            else foreach (var s in weightSteps) s.Enabled = false;
            LayoutAll();
        }

        void SetStatus(string text, Tone tone)
        {
            status.Tone = tone;
            status.Text = (text ?? "").Replace("\r", "").Replace("\n", " ");
            tips.SetToolTip(status, status.Text);
            if (built) summary.Top = status.Text.Length > 0 ? Ui.S(12) : Ui.S(22);
        }

        // ---------------------------------------------------------------- 届いた知らせ(邪魔をしない: 窓を出さない・前に出さない・音を出さない)
        [StructLayout(LayoutKind.Sequential)]
        struct FLASHWINFO
        {
            public uint cbSize;
            public IntPtr hwnd;
            public uint dwFlags, uCount, dwTimeout;
        }

        [DllImport("user32.dll")]
        static extern bool FlashWindowEx(ref FLASHWINFO info);

        bool polling;

        void PollArrivals()
        {
            if (Offline || polling || Busy || RecvBusy || IsDisposed) return;
            Config config = LoadConfig(null);
            if (config == null) return;
            polling = true;
            var client = new DropboxClient(config) { IsCanceled = () => IsDisposed, Log = Log.Write };
            var t = new Thread(() =>
            {
                int count = -1;
                List<OutputEntry> listed = null;
                try { listed = new Receiving(client).List().Entries; count = listed.Count; }
                catch (Exception ex) { Log.Write("poll: " + ex.GetType().Name + ": " + ex.Message); }
                OnUi(() => { polling = false; if (count >= 0) { SetArrived(count, true); QueuePreviews(listed); } });   // 届いたまとめ動画は裏で先に取る(2.7.0)
            });
            t.IsBackground = true;
            t.Start();
        }

        // 届いている数を、タブ・窓の題名に出す。増えたとき、窓が前に無ければタスクバーのボタンを 3 回光らせる
        void SetArrived(int count, bool fromPoll)
        {
            bool more = count > arrived;
            arrived = count;
            UpdateRecvTab();
            LayoutAll();
            if (!fromPoll || !more || Form.ActiveForm == this || !IsHandleCreated) return;
            try
            {
                var fi = new FLASHWINFO { hwnd = Handle, dwFlags = 2 /* FLASHW_TRAY */, uCount = 3, dwTimeout = 0 };
                fi.cbSize = (uint)Marshal.SizeOf(fi);
                FlashWindowEx(ref fi);
            }
            catch (Exception) { }
        }

        void UpdateRecvTab()
        {
            tabRecv.Text = arrived > 0 ? "受け取る ●" + arrived : "受け取る";
            tabRecv.Width = TextRenderer.MeasureText(tabRecv.Text, tabRecv.Font).Width + Ui.S(28);
            tabRecv.AccessibleName = arrived > 0 ? "受け取る(" + arrived + " 件届いています)" : "受け取る";
            Text = arrived > 0 ? AppInfo.Title + "(" + arrived + " 件届いています)" : AppInfo.Title;
        }

        // ---------------------------------------------------------------- 閉じる・ほか
        void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (Busy || RecvBusy)
            {
                string what = Busy ? "送っている途中です。やめて閉じますか?" : "受け取っている途中です。やめて閉じますか?(途中のファイルは消します)";
                var ans = MessageBox.Show(this, what, AppInfo.Title, MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
                if (ans != DialogResult.Yes) { e.Cancel = true; return; }
                cancel = true;
                recvCancel = true;
                Log.Write("canceled by closing");
                // 受け取りの途中なら .part を消し終えるまで少し待つ(バックグラウンドのスレッドなので、待ちきれなくても閉じる)
                if (recvWorker != null) recvWorker.Join(3000);
            }
            poll.Stop();
            SaveSettings();
        }

        void OnUi(Action a)
        {
            if (IsDisposed || !IsHandleCreated) return;
            try { BeginInvoke(a); }
            catch (InvalidOperationException) { }
        }

        static string Mb(long bytes)
        {
            return bytes >= 1024L * 1024 * 1024 ? (bytes / (1024.0 * 1024 * 1024)).ToString("0.00") + "GB" : (bytes / (1024.0 * 1024)).ToString("0") + "MB";
        }

        // ---------------------------------------------------------------- 画面の確認(--screenshot)
        // 見本の中身を入れる(配信2本: 題名つき・区間2つ / 終了が開始より前の誤り、配信者 2 人)
        public void ApplySample()
        {
            cards[0].Sample("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "【雑談】見本の配信の題名(ここに YouTube の題名が出ます)", 3, 5025, 5110, 7260, 7335);
            var c = AddCard(null);
            c.Sample("https://youtu.be/AAAAAAAAAAA", "【ゲーム】もう1本の見本", 2, 600, 540);
            speakerCount.Value = 2;
            speakerNames[0].Text = memberNames.Count > 0 ? memberNames[0] : "配信者 A";
            speakerNames[1].Text = "ゲストの人";
            speakerColors[1].Text = "19D3F3";
            memo.Text = "2本目は後半の所をお願いします";
            SetArrived(1, false);
            ArrangeCards();
            UpdateAll();
        }

        // 窓の中身を画像に保存する
        // 見本の状態(--state): ③ を選んだ・重みを指定して配信者 10 人・配信者 8 人・配信者の欄の誤り・送ろうとして誤りが出た・送っている途中・送り終えた
        public void ApplyState(string name)
        {
            if (name == "manual") flowRadios[2].Checked = true;
            else if (name == "many")
            {
                speakerCount.Value = 8;
                for (int i = 0; i < 8; i++) speakerNames[i].Text = i < memberNames.Count ? memberNames[i] : "配信者 " + (i + 1);
            }
            else if (name == "weights")
            {
                weightsOn.Checked = true;
                speakerCount.Value = Speakers.MaxCount;
                for (int i = 0; i < 4; i++) speakerNames[i].Text = i < memberNames.Count ? memberNames[i] : "配信者 " + (i + 1);
                speakerColors[3].Text = "FF3DA5";
            }
            else if (name == "speakers")
            {
                speakerCount.Value = 4;
                speakerNames[0].Text = memberNames.Count > 0 ? memberNames[0] : "配信者 A";
                speakerNames[1].Text = "ゲストの人";
                speakerColors[1].Text = "19D3F3";
                speakerColors[2].Text = "ff00aa";   // 名前が空で色だけ = 誤り
                speakerNames[3].Text = "もう1人";
                speakerColors[3].Text = "12";       // 6 桁でない = 誤り
                StartSend();
            }
            else if (name == "strict") StartSend();
            else if (name == "focus") { var t = cards[0].Rows.First().End; t.ShowAsFocused = true; t.SelectSegment(TimeEdit.Minute); }
            else if (name == "busy")
            {
                SetBusy(true);
                bar.Value = 420;
                SetStatus("動画を送っています(1 / 2): にぇの叫び.mp4… (512MB / 1.21GB)", Tone.Muted);
            }
            else if (name == "done")
            {
                bar.Value = 1000;
                ShowSent(true);
            }
            LayoutAll();
            UpdateAll();
        }

        // 見本: 動画ファイルの側(--tab video)
        public void ShowVideoSample()
        {
            foreach (string n in new[] { @"C:\動画\切り抜き\にぇの叫び.mp4", @"C:\動画\切り抜き\雑談のいいところ_02.mp4" }) files.Items.Add(n);
            speakerCount.Value = 1;
            speakerNames[0].Text = memberNames.Count > 1 ? memberNames[1] : "";
            fileNote.Text = "動画ではないので入れませんでした(.mp4 / .mov / .mkv / .webm / .m4v だけ): メモ.txt";
            UpdateFileView();
            ShowLeft(true);
            UpdateAll();
        }

        [DllImport("user32.dll")]
        static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);

        public void RenderTo(string path)
        {
            LayoutAll();
            ApplyTheme();
            Application.DoEvents();
            // まず窓ごと(タイトルバー・スクロールバーが実際の見た目で写る)。だめなら中身だけ
            using (var bmp = new Bitmap(Width, Height))
            {
                bool ok = false;
                using (var g = Graphics.FromImage(bmp))
                {
                    IntPtr hdc = g.GetHdc();
                    try { ok = PrintWindow(Handle, hdc, 2 /* PW_RENDERFULLCONTENT */); }
                    catch (Exception) { ok = false; }
                    finally { g.ReleaseHdc(hdc); }
                }
                if (ok && bmp.GetPixel(bmp.Width / 2, bmp.Height / 2).A != 0 && bmp.GetPixel(bmp.Width / 2, bmp.Height - Ui.S(30)).ToArgb() != Color.Black.ToArgb())
                {
                    bmp.Save(path, ImageFormat.Png);
                    return;
                }
            }
            using (var bmp = new Bitmap(root.Width, root.Height))
            {
                root.DrawToBitmap(bmp, new Rectangle(Point.Empty, root.Size));
                bmp.Save(path, ImageFormat.Png);
            }
        }
    }
}
