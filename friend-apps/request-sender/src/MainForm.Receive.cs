// 画面のタブ「受け取る」: 「① 全自動」で送った依頼のパック(.zip)と、失敗の知らせ(.失敗.txt)。一覧は Dropbox の「/出力」。
//   受け取る         … 選んだパック 1 本(ダブルクリックでも)。大きさと hash を確かめ、保存先に展開して(settings.json の extractZip が false なら zip のまま)、Dropbox と一覧から消す
//   すべて受け取る   … 届いているパックを古い順に 1 本ずつ同じように(1 つの依頼で何本もできたときに、1 本ずつ押さなくて済むように)
//   やめる           … 取ってきている途中だけ出る。途中のファイルは消し、受け取り終えたものは Dropbox から消し終える
//   まとめ動画を見る … パックの隣のまとめ動画(等速・各クリップに札の確認用)をアプリの小窓で再生する(2.7.0)。一覧を調べたとき(更新・3 分ごと)に
//                     %TEMP%\RequestSender\previews へ裏で先に取ってあるので、すぐ見られる。小窓の [受け取る] [要らない] でそのまま続けられる。受け取った・要らないにしたら写しは消す
//   要らない / 消す  … 1 つのボタン。パックなら記録(<zip>.feedback.json)を受付のフォルダに置いてから受け取らずに Dropbox から消す(まとめ動画も。記録が置けなくても消す。2.6.0)、
//                     失敗の知らせなら読み終えたあとに消す
//   組(2.8.0。2-16)… 「<題> 1-5(5 本)」の行の下に 1 本ずつの行。組の行では [受け取る] = 組の残りを全部・[要らない] = 組の残りを全部・[まとめ動画を見る] = 組のまとめ動画
//                     (小窓の右の一覧でチェックした分だけ受け取り、外した分は要らない)。1 本の行は今までどおり(まとめ動画は組のものを、その本の頭から)。
//                     組の最後の 1 本を片付けたら .group.json と組のまとめ動画も Dropbox から消す
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using FriendApps;

namespace RequestSender
{
    public partial class MainForm
    {
        readonly LocalState state;
        readonly Pane recvPane = new Pane { OnPanel = true, Border = true }, listFrame = new Pane { Border = true };
        readonly SectionHead headRecv = new SectionHead("01", "届いたもの");
        readonly EntryList outList = new EntryList();
        readonly EntryHeader listHeader = new EntryHeader();
        readonly TextBox detail = new TextBox();
        Field detailField;
        readonly Btn refreshBtn = new Btn("更新", BtnKind.Normal), receiveBtn = new Btn("受け取る", BtnKind.Primary), receiveAllBtn = new Btn("すべて受け取る", BtnKind.Normal),
                     cancelRecvBtn = new Btn("やめる", BtnKind.Normal), previewBtn = new Btn("まとめ動画を見る", BtnKind.Normal), deleteBtn = new Btn("消す", BtnKind.Normal),
                     openFolderBtn = new Btn("フォルダを開く", BtnKind.Normal), changeDirBtn = new Btn("変える…", BtnKind.Normal);
        readonly Lbl recvHint = new Lbl("「① 全自動」で送ったものは、できあがるとここに届きます(1 本ずつ・何本かの組で)。「まとめ動画を見る」で中身を先に見て、1 本ずつ「受け取る」(保存先にフォルダとして展開)か「要らない」を決めます。", Tone.Muted);
        readonly Lbl recvStatus = new Lbl("", Tone.Muted), lDir = new Lbl("保存先", Tone.Muted), dirLabel = new Lbl("", Tone.Text);
        readonly Bar recvBar = new Bar();
        readonly Dictionary<string, string> failureTexts = new Dictionary<string, string>();
        List<OutputEntry> entries = new List<OutputEntry>();
        string downloadDir, lastDownloaded;
        bool listedOnce;
        Thread recvWorker;
        volatile bool recvCancel;
        readonly PreviewQueue previewQueue = new PreviewQueue();                         // まとめ動画を裏で取る順番(2.7.0)
        readonly Dictionary<string, string> previewReady = new Dictionary<string, string>();   // 取り終えたまとめ動画(パックの Key → 写しの場所)
        OutputEntry previewWanted;   // 「まとめ動画を見る」を押して、取れるのを待っているもの(パックか組)
        OutputEntry previewFrom;     // そのとき選んでいた行(組の 1 本の行なら、その本の頭から再生する)
        bool prefetchRunning;

        // 裏の処理が終わった知らせを画面が受け取るまで true(スレッドが生きているかでは見ない。終わりの直前に並べた画面の処理と食い違うため)
        bool recvRunning;
        bool recvDownloading;   // 取ってきている途中(受け取る・すべて受け取る・まとめ動画)= 「やめる」を出す
        bool recvAll;           // そのうち「すべて受け取る」の途中
        bool RecvBusy { get { return recvRunning; } }

        void BuildReceiveLayout()
        {
            refreshBtn.Click += (s, e) => RefreshList();
            recvHint.Font = Theme.Small;
            recvHint.AutoSize = false;

            outList.AccessibleName = "届いたものの一覧";
            outList.Texts = e => new[] { KindText(e), RowTitle(e), e.Kind == OutputKind.Failure ? "" : SizeText(RowSize(e)), When(e.Modified) };
            outList.SelectedIndexChanged += (s, e) => ShowSelected();
            outList.DoubleClick += (s, e) => { if (IsPack(SelectedEntry) || IsGroup(SelectedEntry)) StartDownload(); };
            listHeader.List = outList;
            listFrame.Controls.Add(listHeader);
            listFrame.Controls.Add(outList);

            detail.Multiline = true;
            detail.ReadOnly = true;
            detail.ScrollBars = ScrollBars.Vertical;
            detail.AccessibleName = "選んだものの説明";
            detailField = new Field(detail);

            dirLabel.AutoSize = false;
            dirLabel.AutoEllipsis = true;
            dirLabel.TextAlign = ContentAlignment.MiddleLeft;
            changeDirBtn.Click += (s, e) => ChangeDir();
            receiveBtn.Font = Theme.Big;
            receiveBtn.Click += (s, e) => StartDownload();
            receiveAllBtn.AccessibleName = "すべて受け取る";
            receiveAllBtn.Click += (s, e) => StartDownloadAll();
            cancelRecvBtn.Visible = false;
            cancelRecvBtn.Click += (s, e) => CancelReceive();
            previewBtn.AccessibleName = "まとめ動画を見る";
            previewBtn.Click += (s, e) => StartPreview();
            openFolderBtn.Click += (s, e) => OpenFolder();
            deleteBtn.Click += (s, e) => StartDelete();
            recvStatus.AutoSize = false;
            recvStatus.AutoEllipsis = true;

            recvPane.Controls.AddRange(new Control[] { headRecv, refreshBtn, recvHint, listFrame, detailField, lDir, dirLabel, changeDirBtn,
                                                       receiveBtn, receiveAllBtn, cancelRecvBtn, previewBtn, openFolderBtn, deleteBtn, recvBar, recvStatus });
            recvPage.Controls.Add(recvPane);

            downloadDir = state.LoadDownloadDir();
            dirLabel.Text = downloadDir;
            UpdateRecvButtons();
        }

        void LayoutReceive()
        {
            int m = Ui.S(12), w = recvPage.Width - m * 2, h = recvPage.Height - m * 2;
            if (w <= 0 || h <= 0) return;
            recvPane.SetBounds(m, m, w, h);
            int iw = w - m * 2;
            headRecv.SetBounds(m, m, iw - refreshBtn.Width - m, Ui.S(20));
            refreshBtn.Location = new Point(w - m - refreshBtn.Width, m - Ui.S(4));
            recvHint.SetBounds(m, m + Ui.S(28), iw, Ui.S(18));
            int top = m + Ui.S(54), foot = Ui.S(104), rest = Math.Max(Ui.S(120), h - top - foot - m);
            int listH = rest * 55 / 100;
            listFrame.SetBounds(m, top, iw, listH);
            listHeader.SetBounds(1, 1, iw - 2, Ui.S(24));
            outList.SetBounds(1, 1 + Ui.S(24), iw - 2, listH - 2 - Ui.S(24));
            detailField.SetBounds(m, top + listH + Ui.S(8), iw, rest - listH - Ui.S(8));
            int y = top + rest + Ui.S(10);
            lDir.Location = new Point(m, y + Ui.S(5));
            changeDirBtn.Location = new Point(w - m - changeDirBtn.Width, y);
            dirLabel.SetBounds(lDir.Right + Ui.S(8), y, changeDirBtn.Left - lDir.Right - Ui.S(16), Ui.S(28));
            y += Ui.S(38);
            receiveBtn.SetBounds(m, y, Math.Max(Ui.S(150), TextRenderer.MeasureText(receiveBtn.Text, receiveBtn.Font).Width + Ui.S(24)), Ui.S(40));   // 組の「受け取る(5 本)」は広げる
            receiveAllBtn.SetBounds(receiveBtn.Right + Ui.S(8), y, receiveAllBtn.Width, Ui.S(40));
            int x = receiveAllBtn.Right + Ui.S(8);
            cancelRecvBtn.Location = new Point(x, y + Ui.S(6));
            if (cancelRecvBtn.Visible) x = cancelRecvBtn.Right + Ui.S(8);
            previewBtn.Location = new Point(x, y + Ui.S(6));
            openFolderBtn.Location = new Point(previewBtn.Right + Ui.S(6), y + Ui.S(6));
            deleteBtn.Location = new Point(openFolderBtn.Right + Ui.S(6), y + Ui.S(6));
            recvStatus.SetBounds(deleteBtn.Right + Ui.S(14), y + Ui.S(10), Math.Max(Ui.S(60), w - m - deleteBtn.Right - Ui.S(14)), Ui.S(20));
            y += Ui.S(48);
            recvBar.SetBounds(m, y, iw, Ui.S(3));
            listHeader.Invalidate();
            outList.Invalidate();
        }

        void ThemeReceive()
        {
            listHeader.Invalidate();
        }

        OutputEntry SelectedEntry
        {
            get { return outList.SelectedItem as OutputEntry; }
        }

        int PackCount
        {
            get { return entries.Count(IsPack); }
        }

        static bool IsPack(OutputEntry e)
        {
            return e != null && e.Kind == OutputKind.Pack;
        }

        static bool IsGroup(OutputEntry e)
        {
            return e != null && e.Kind == OutputKind.Group;
        }

        // その行で見るまとめ動画の持ち主: 組の行 = 組 / 組の 1 本の行 = 組(組にまとめ動画が無ければ、その本の隣のもの)/ 1 本のパック = そのパック。無ければ null
        static OutputEntry PreviewOwner(OutputEntry e)
        {
            if (e == null) return null;
            if (IsGroup(e)) return e.Preview != null ? e : null;
            if (!IsPack(e)) return null;
            if (e.Parent != null && e.Parent.Preview != null) return e.Parent;
            return e.Preview != null ? e : null;
        }

        static bool HasPreview(OutputEntry e)
        {
            return PreviewOwner(e) != null;
        }

        // 組の残り(n の順)
        static List<OutputEntry> GroupPacks(OutputEntry g)
        {
            return g.Members.ToList();
        }

        static string KindText(OutputEntry e)
        {
            return e.Kind == OutputKind.Group ? "組" : e.Kind == OutputKind.Pack ? "パック" : "失敗";
        }

        // 一覧の題: 組 =「<題> 1-5(5 本)」/ 組の 1 本 =「  ├ 1. 題」(最後の本は └)/ ほか = 題
        static string RowTitle(OutputEntry e)
        {
            if (IsGroup(e)) return OutputFolder.GroupLabel(e);
            if (e.Parent == null || e.Slot == null) return e.Title;
            bool last = e.Parent.Members.Count > 0 && e.Parent.Members[e.Parent.Members.Count - 1] == e;
            return "  " + (last ? "└ " : "├ ") + e.Slot.N + ". " + e.Title;
        }

        static long RowSize(OutputEntry e)
        {
            return IsGroup(e) ? OutputFolder.TotalSize(e.Members) : e.Size;
        }

        // 「要らない / 消す」を押せるもの: パック・組(受け取らずに消す)か、理由を読み終えた失敗の知らせ
        bool CanDelete(OutputEntry e)
        {
            return IsPack(e) || IsGroup(e) || (e != null && e.Kind == OutputKind.Failure && failureTexts.ContainsKey(e.Key));
        }

        // 「要らない / 消す」のボタンの文字(確認の窓の題にも使う)
        static string DeleteLabel(OutputEntry e)
        {
            if (IsGroup(e)) return "要らない(" + e.Members.Count + " 本)";
            return IsPack(e) ? "要らない" : "消す";
        }

        void UpdateRecvButtons()
        {
            var e = SelectedEntry;
            bool busy = RecvBusy;
            int packs = PackCount;
            refreshBtn.Enabled = !busy;
            changeDirBtn.Enabled = !busy;
            receiveBtn.Enabled = !busy && (IsPack(e) || IsGroup(e));
            receiveBtn.Text = busy && recvDownloading && !recvAll ? "受け取っています…" : IsGroup(e) ? "受け取る(" + e.Members.Count + " 本)" : "受け取る";
            receiveBtn.AccessibleName = IsGroup(e) ? "この組の残り " + e.Members.Count + " 本を受け取る" : "受け取る";
            receiveAllBtn.Enabled = !busy && packs > 0;
            receiveAllBtn.Text = busy && recvAll ? "すべて受け取っています…" : packs > 1 ? "すべて受け取る(" + packs + " 本)" : "すべて受け取る";
            receiveAllBtn.FitWidth();
            previewBtn.Enabled = HasPreview(e);   // 受け取りの途中でも見られる(まとめ動画は別に取る)
            deleteBtn.Text = DeleteLabel(e);
            deleteBtn.FitWidth();
            deleteBtn.Enabled = !busy && CanDelete(e);
            cancelRecvBtn.Visible = busy && recvDownloading;
            cancelRecvBtn.Enabled = !recvCancel;
            LayoutReceive();   // 「やめる」の出し入れ・「すべて受け取る(n 本)」と「要らない / 消す」の幅で、右のボタンの位置が変わる
        }

        // ---- 一覧 ----
        // 受け取るための鍵(config.json)。読めなければ下の段に理由を出して null
        Config RecvConfig()
        {
            return LoadConfig(text => SetRecvStatus(text, true));
        }

        void RefreshList()
        {
            if (RecvBusy) return;
            Config config = RecvConfig();
            if (config == null) return;
            listedOnce = true;
            SetRecvStatus("届いたものを調べています…", false);
            var client = NewClient(config);
            RunRecv(() =>
            {
                var listing = new Receiving(client).List();
                OnUi(() => ShowEntries(listing));
            });
        }

        // テストと画面の確認でも使う(通信しない)
        public void ShowEntries(OutputListing listing)
        {
            entries = listing.Entries;
            outList.BeginUpdate();
            outList.Items.Clear();
            foreach (var e in entries) outList.Items.Add(e);
            outList.EndUpdate();
            listHeader.Invalidate();
            detail.Text = "";
            SetArrived(OutputFolder.CountItems(entries), false);
            int packs = PackCount, groups = entries.Count(IsGroup), fails = OutputFolder.CountItems(entries) - packs;
            if (entries.Count == 0) SetRecvStatus("まだ届いたものはありません", false);
            else
            {
                string what = (packs > 0 ? "パック " + packs + " 本" + (groups > 0 ? "(組 " + groups + ")" : "") : "") + (packs > 0 && fails > 0 ? "・" : "") + (fails > 0 ? "失敗の知らせ " + fails + " 件" : "");
                string how = packs > 1 ? "「すべて受け取る」でまとめて受け取れます。" : packs == 1 ? "選んで「受け取る」を押してください。" : "選ぶと理由が出ます。";
                SetRecvStatus(what + "があります。" + how, false);
                outList.SelectedIndex = 0;
            }
            UpdateRecvButtons();
            QueuePreviews(entries);
        }

        void ShowSelected()
        {
            UpdateRecvButtons();
            var e = SelectedEntry;
            if (e == null) { detail.Text = ""; return; }
            if (IsGroup(e)) { detail.Text = GroupDetail(e); return; }
            if (e.Kind == OutputKind.Pack)
            {
                int same = OutputFolder.CountSameRequest(entries, e);
                var owner = PreviewOwner(e);
                string inGroup = e.Parent != null && e.Slot != null
                    ? "組: " + OutputFolder.GroupLabel(e.Parent) + " の " + e.Slot.N + " 本目" + (owner == e.Parent && e.Slot.HasStart ? "(まとめ動画の " + PreviewForm.Clock(e.Slot.PreviewStart) + " から)" : "") + "\r\n" : "";
                detail.Text = "題: " + e.Title + "\r\n" + inGroup +
                              (e.RequestId.Length > 0 ? "依頼: " + e.RequestId + (same > 1 ? "(この依頼のパックは、届いている中に " + same + " 本)" : "") + "\r\n" : "") +
                              "大きさ: " + SizeText(e.Size) + (e.Slot != null && e.Slot.Duration > 0 ? "(切り抜きの長さ " + PreviewForm.Clock(e.Slot.Duration) + ")" : "") +
                              "\r\n届いた日時: " + When(e.Modified) + "\r\n" +
                              "まとめ動画: " + (owner != null ? PreviewText(owner) : "なし") + "\r\n\r\n" +
                              "DaVinci Resolve のパック(字幕は校正の前)です。「受け取る」を押すと保存先にフォルダとして展開し(zip は消します)、確かめたあと Dropbox と一覧から消えます。" +
                              "要らなければ「要らない」で、受け取らずに Dropbox から消せます(要らなかったことは送り先の人に伝わります)。";
                return;
            }
            string text;
            if (failureTexts.TryGetValue(e.Key, out text)) { ShowFailure(e, text); return; }
            if (RecvBusy) { detail.Text = "自動の処理が失敗しました。理由は、いまの処理が終わってから読みます。"; return; }
            Config config = RecvConfig();
            if (config == null) return;
            detail.Text = "自動の処理が失敗しました。理由を読んでいます…";
            var client = NewClient(config);
            RunRecv(() =>
            {
                string reason = new Receiving(client).FailureText(e);
                OnUi(() =>
                {
                    failureTexts[e.Key] = reason;
                    if (SelectedEntry == e) ShowFailure(e, reason);
                    UpdateRecvButtons();
                });
            });
        }

        // 組の行の説明: 題・依頼・残りの本数と大きさ・まとめ動画・1 本ずつの一覧・ボタンの意味
        string GroupDetail(OutputEntry g)
        {
            var lines = g.Members.Select(m => "  " + m.Slot.N + ". " + m.Title + "(" + (m.Slot.Duration > 0 ? PreviewForm.Clock(m.Slot.Duration) + "・" : "") + SizeText(m.Size) + ")");
            return "組: " + OutputFolder.GroupLabel(g) + "\r\n" +
                   (g.RequestId.Length > 0 ? "依頼: " + g.RequestId + "\r\n" : "") +
                   "大きさ: 合計 " + SizeText(OutputFolder.TotalSize(g.Members)) + "\r\n届いた日時: " + When(g.Modified) + "\r\n" +
                   "まとめ動画: " + PreviewText(g) + "\r\n\r\n" + string.Join("\r\n", lines) + "\r\n\r\n" +
                   "この組は 1 本ずつ選べます。「まとめ動画を見る」で全部を続けて見て、窓の右の一覧でチェックした本だけ受け取れます(外した本は「要らない」)。\r\n" +
                   "この行の「受け取る」= この組の残りを全部受け取る / 「要らない」= この組の残りを全部要らない。1 本ずつ決めるなら、下の行を選んでください。";
        }

        void ShowFailure(OutputEntry e, string reason)
        {
            detail.Text = "自動の処理が失敗しました(" + e.Title + ")。\r\n送り先の人に伝えるか、「② 軽く確認」か「③ 全部人が行う」で送り直してください。\r\n読み終えたら「消す」を押すと、一覧から消えます。\r\n\r\n理由:\r\n" + reason;
        }

        // ---- 受け取る ----
        // 選んだパック 1 本(Receiving.ReceiveOne: 受け取って確かめ → 展開 → Dropbox から消す)
        void StartDownload()
        {
            var e = SelectedEntry;
            if (RecvBusy) return;
            if (IsGroup(e)) { StartDownloadMany(GroupPacks(e), "この組の残り(" + OutputFolder.GroupLabel(e) + ")", "組を受け取る", false); return; }   // 組の行 = 組の残りを全部
            if (!IsPack(e)) return;
            string dir = downloadDir;
            var receiving = BeginFetch("受け取る準備をしています…", false);
            if (receiving == null) return;
            Log.Write("receive: " + e.Name + " size=" + e.Size);
            var show = FileProgress();
            RunRecv(() =>
            {
                var got = receiving.ReceiveOne(e, dir, show);
                if (got.Deleted) receiving.FinishGroups(new[] { e });   // 組の最後の 1 本なら .group.json と組のまとめ動画も消す
                OnUi(() => ShowReceived(e, got));
            });
        }

        void ShowReceived(OutputEntry e, ReceiveOneResult got)
        {
            lastDownloaded = got.Placed;
            recvBar.Value = 1000;
            if (!got.Deleted)
            {
                SetRecvStatus("受け取りましたが、Dropbox から消せませんでした(次に更新したときにまた出ます)\n" + Path.GetFileName(got.Placed), true);
                ShowSelected();
                return;
            }
            Receiving.ForgetPreview(e);   // 見終えたまとめ動画の写しは要らない
            RemoveEntry(e);
            if (got.ExtractError != null)
                SetRecvStatus("受け取りましたが、展開できませんでした(" + got.ExtractError + ")。zip はそのまま保存先にあります(右クリック →「すべて展開」)。", true);
            else
                SetRecvStatus("受け取りました ✓  " + Path.GetFileName(got.Placed) + (got.Extracted ? "(展開済み)" : "") + "\n「フォルダを開く」で見られます。", false, true);
        }

        // 届いているパックを古い順にまとめて受け取る(Receiving.DownloadAll。1 本ずつ ReceiveOne と同じように)
        void StartDownloadAll()
        {
            StartDownloadMany(OutputFolder.PacksOldestFirst(entries), "届いているパック", "すべて受け取る", true);
        }

        // 何本かを順に受け取る(すべて受け取る・組の行の「受け取る」)。押すと本数と合計の大きさの確認を 1 回出す。all = 「すべて受け取る」のボタンから
        void StartDownloadMany(List<OutputEntry> packs, string what, string caption, bool all)
        {
            if (RecvBusy || packs.Count == 0) return;
            long total = OutputFolder.TotalSize(packs);
            if (MessageBox.Show(this, what + " " + packs.Count + " 本(合計 " + Mb(total) + ")をすべて受け取ります。\n保存先: " + downloadDir +
                    "\n\n古い順に 1 本ずつ受け取って保存先にフォルダとして展開し、ちゃんと保存できたものから Dropbox と一覧から消えます。途中で「やめる」を押せます。",
                    caption, MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
            RunDecision(packs, new List<OutputEntry>(), all);
        }

        // 受け取るものと要らないものを一度に片付ける(すべて受け取る・組の「受け取る」・組の小窓の「チェックした n 本を受け取る(残りは要らない)」)。
        // 要らない分を先に(記録を置いてから消す。すぐ終わる)、それから受け取る分を古い順に。組の最後の 1 本まで片付けたら .group.json と組のまとめ動画も消す
        void RunDecision(List<OutputEntry> receive, List<OutputEntry> discard, bool all)
        {
            string dir = downloadDir;
            var receiving = BeginFetch(receive.Count > 0 ? "受け取る準備をしています…(" + receive.Count + " 本)" : "消しています…", all);
            if (receiving == null) return;
            if (receive.Count == 0) recvDownloading = false;   // 要らないだけ(取ってくるものは無い)
            Log.Write("decide: receive " + receive.Count + " (" + OutputFolder.TotalSize(receive) + " bytes), discard " + discard.Count);
            var gate = new ProgressGate();
            RunRecv(() =>
            {
                var d = receiving.DiscardAll(discard, DateTimeOffset.Now);
                var r = new ReceiveAllResult { Total = receive.Count };
                if (d.Error == null && receive.Count > 0)
                    r = receiving.DownloadAll(receive, dir, (no, e, done, whole, step) =>
                    {
                        int permille;
                        if (gate.Changed(done, whole, no + "|" + step, out permille))
                            ShowRecvProgress(permille, step + "(" + no + " / " + receive.Count + " 本目: " + e.Title + ")… (全体 " + Mb(done) + " / " + Mb(whole) + ")");
                    });
                Log.Write("decide: discarded " + d.Done.Count + (d.Error != null ? " stopped: " + d.Error.Message : "") + ", received " + r.Received + "/" + r.Total +
                          (r.Canceled ? " canceled" : "") + (r.Error != null ? " stopped: " + r.Error.Message : "") +
                          (r.Failed.Count > 0 ? " skipped " + r.Failed.Count : "") + (r.Kept.Count > 0 ? " not deleted " + r.Kept.Count : ""));
                receiving.FinishGroups(d.Done.Concat(r.Done));
                OnUi(() => FinishDecision(r, d, discard.Count));
            });
        }

        void FinishDecision(ReceiveAllResult r, DiscardAllResult d, int discardWanted)
        {
            if (r.LastPath != null) lastDownloaded = r.LastPath;
            foreach (var x in r.Done) Receiving.ForgetPreview(x);
            RemoveEntries(d.Done.Concat(r.Done));
            string gone = discardWanted == 0 ? "" : d.Done.Count == discardWanted ? "要らない " + d.Done.Count + " 本を消しました" + (d.NotRecorded > 0 ? "(" + d.NotRecorded + " 本は送り先の人への記録が送れず、伝わりません)" : "") + "。"
                        : "要らない " + discardWanted + " 本のうち " + d.Done.Count + " 本を消したところで止まりました: " + RecvError(d.Error) + " ";
            bool clean = d.Error == null && d.NotRecorded == 0 && (r.Total == 0 || r.Clean);
            if (clean) recvBar.Value = 1000;
            if (r.Total == 0) { SetRecvStatus(gone.Length > 0 ? gone : "", d.Error != null || d.NotRecorded > 0, clean); return; }
            if (d.Error != null) { SetRecvStatus(gone + "受け取りはしていません。", true); return; }
            SetRecvStatus(gone + r.Summary(r.Error != null ? RecvError(r.Error) : null), r.HasProblem || d.NotRecorded > 0, clean);
        }

        // 取ってくる処理(受け取る・すべて受け取る・まとめ動画)の始め: 鍵を読み、「やめる」を出す印を立て、下の文を出す。鍵が読めなければ null
        Receiving BeginFetch(string status, bool all)
        {
            Config config = RecvConfig();
            if (config == null) return null;
            recvCancel = false;
            recvDownloading = true;
            recvAll = all;
            recvBar.Value = 0;
            SetRecvStatus(status, false);
            return NewReceiving(config);
        }

        // 1 つのファイルの進み具合を「<段>… (済んだ / 全体)」で出す(受け取る・まとめ動画)
        Action<long, long, string> FileProgress()
        {
            var gate = new ProgressGate();
            return (done, total, step) =>
            {
                int permille;
                if (gate.Changed(done, total, step, out permille)) ShowRecvProgress(permille, step + "… (" + Mb(done) + " / " + Mb(total) + ")");
            };
        }

        // 進み具合を下の棒と文に出す(裏のスレッドから呼ぶ。処理が終わったあとに届いたものは出さない)
        void ShowRecvProgress(int permille, string text)
        {
            OnUi(() => { if (RecvBusy) { recvBar.Value = permille; SetRecvStatus(text, false); } });
        }

        // 裏のスレッドから細かく呼ばれる進み具合を間引く: 千分率か key(段の名前など)が前と変わったときだけ true
        sealed class ProgressGate
        {
            int lastPermille = -1;
            string lastKey;

            public bool Changed(long done, long total, string key, out int permille)
            {
                permille = (int)Math.Max(0, Math.Min(1000, done * 1000 / Math.Max(1, total)));
                if (permille == lastPermille && key == lastKey) return false;
                lastPermille = permille;
                lastKey = key;
                return true;
            }
        }

        // 受け取りを途中でやめる(いま受け取っている途中のファイルは消す。受け取り終えたものはそのまま)
        void CancelReceive()
        {
            if (!RecvBusy || recvCancel) return;
            recvCancel = true;
            cancelRecvBtn.Enabled = false;
            SetRecvStatus("やめています…(途中のファイルは消します)", false);
            Log.Write("receive: cancel requested");
        }

        // 画面の確認(--tab receive --select <行>)・テスト: 一覧の行を選ぶ
        public void SelectEntry(int index)
        {
            if (index >= 0 && index < outList.Items.Count) outList.SelectedIndex = index;
        }

        // 画面の確認(--tab receive --state receiving): 「すべて受け取る」の途中の見た目(通信しない)
        public void ShowReceivingSample()
        {
            recvRunning = recvDownloading = recvAll = true;
            recvBar.Value = 335;
            SetRecvStatus("受け取っています(2 / 5 本目: 見本の切り抜き_03)… (全体 2.51GB / 7.50GB)", false);
            UpdateRecvButtons();
        }

        // ---- まとめ動画(2.7.0): 届いたら裏で先に取ってきておき、押したらアプリの小窓ですぐ再生する(src/Preview.cs) ----
        // 一覧を調べたとき(更新・3 分ごとの確認)に並べ直して、裏で 1 本ずつ取る
        void QueuePreviews(IEnumerable<OutputEntry> listed)
        {
            previewQueue.Reset(listed);
            EnsurePrefetch(false);
        }

        // 裏で取る処理が止まっていて、取るものがあれば動かす。loud = 鍵が読めないときに下の段に出す(押したとき)
        void EnsurePrefetch(bool loud)
        {
            if (prefetchRunning || Offline || IsDisposed || !previewQueue.HasPending()) return;
            Config config = LoadConfig(text => { if (loud) SetRecvStatus(text, true); });
            if (config == null) return;
            var receiving = new Receiving(new DropboxClient(config) { IsCanceled = () => IsDisposed, Log = Log.Write });
            prefetchRunning = true;
            var t = new Thread(() => PrefetchLoop(receiving)) { IsBackground = true };
            t.Start();
        }

        void PrefetchLoop(Receiving receiving)
        {
            string dir = Receiving.PreviewDir();
            while (!IsDisposed)
            {
                var e = previewQueue.Next();
                if (e == null) break;
                var gate = new ProgressGate();
                try
                {
                    Log.Write("preview prefetch: " + e.Preview.Name + " size=" + e.Preview.Size);
                    string path = receiving.DownloadPreview(e, dir, (done, total, step) =>
                    {
                        int permille;
                        if (gate.Changed(done, total, step, out permille)) OnUi(() => ShowPreviewProgress(e, permille, done, total));
                    });
                    previewQueue.MarkDone(e);
                    OnUi(() => PreviewReady(e, path));
                }
                catch (Exception ex)
                {
                    Log.Write("preview prefetch failed: " + e.Preview.Name + ": " + ex.GetType().Name + ": " + ex.Message);
                    previewQueue.MarkFailed(e);
                    OnUi(() => PreviewFailed(e, ex));
                }
            }
            OnUi(() => { prefetchRunning = false; EnsurePrefetch(false); });   // 終わる間際に押されたものがあれば、もう一度
        }

        // 押して待っているまとめ動画の進み具合だけ下の段に出す(受け取りの途中はそちらを優先)
        void ShowPreviewProgress(OutputEntry e, int permille, long done, long total)
        {
            if (previewWanted == null || previewWanted.Key != e.Key || RecvBusy) return;
            recvBar.Value = permille;
            SetRecvStatus("まとめ動画を取ってきています… (" + Mb(done) + " / " + Mb(total) + ")", false);
        }

        void PreviewReady(OutputEntry e, string path)
        {
            if (previewQueue.IsGone(e)) { Receiving.ForgetPreview(e); return; }   // 取っている間に受け取った・要らないにした
            previewReady[e.Key] = path;
            var s = SelectedEntry;
            if (s != null && s.Key == e.Key && !RecvBusy) ShowSelected();
            if (previewWanted == null || previewWanted.Key != e.Key) return;
            previewWanted = null;
            if (!RecvBusy) recvBar.Value = 1000;
            var from = previewFrom != null && entries.Contains(previewFrom) ? previewFrom : entries.FirstOrDefault(x => x.Key == e.Key) ?? e;
            previewFrom = null;
            OpenPreview(from, path);
        }

        void PreviewFailed(OutputEntry e, Exception ex)
        {
            if (previewWanted == null || previewWanted.Key != e.Key) return;   // 自動で取っていたものは黙る(押したときにもう一度取る)
            previewWanted = null;
            SetRecvStatus("まとめ動画を取ってこられませんでした: " + RecvError(ex), true);
        }

        // 一覧の状態に合わせた「まとめ動画: 」の説明
        string PreviewText(OutputEntry e)
        {
            if (e.Preview == null) return "なし";
            string size = SizeText(e.Preview.Size);
            if (previewReady.ContainsKey(e.Key)) return "あり(" + size + "。取ってあります。「まとめ動画を見る」ですぐ再生できます)";
            if (e.Preview.Size > PreviewQueue.AutoMaxBytes) return "あり(" + size + "。大きいので「まとめ動画を見る」を押したときに取ってきます)";
            return "あり(" + size + "。裏で取ってきています。「まとめ動画を見る」で再生できます)";
        }

        // 「まとめ動画を見る」: 取ってあればすぐ小窓で。まだなら先頭に回して、取れたら開く。組の行・組の 1 本の行は組のまとめ動画
        void StartPreview()
        {
            var sel = SelectedEntry;
            var e = PreviewOwner(sel);
            if (e == null) return;
            string path;
            if (previewReady.TryGetValue(e.Key, out path) && File.Exists(path)) { OpenPreview(sel, path); return; }
            previewReady.Remove(e.Key);
            previewWanted = e;
            previewFrom = sel;
            previewQueue.Prioritize(e);
            if (!RecvBusy) { recvBar.Value = 0; SetRecvStatus("まとめ動画を取ってきています…", false); }
            EnsurePrefetch(true);
        }

        // 小窓で再生し、閉じたあと [受け取る] [要らない] を続ける。小窓が作れない PC では既定のプレイヤーで開く。
        // e = 選んでいた行。組(の行・1 本の行)なら組の小窓(1 本ずつの一覧つき。1 本の行からなら、その本の頭から)
        void OpenPreview(OutputEntry e, string path)
        {
            var owner = PreviewOwner(e) ?? e;
            if (IsGroup(owner)) { OpenGroupPreview(owner, e, path); return; }
            PreviewChoice choice;
            try { choice = ShowPlayer(path, e.Title, null, 0); }
            catch (Exception ex) { OpenExternally(path, ex); return; }
            bool listed = entries.Contains(e);
            if (choice == PreviewChoice.None || !listed)
            {
                if (listed) SetRecvStatus("要るなら「受け取る」、要らなければ「要らない」を押してください。", false);
                return;
            }
            if (RecvBusy) { SetRecvStatus("いまの処理が終わってから、もう一度押してください。", true); return; }
            outList.SelectedItem = e;
            if (choice == PreviewChoice.Receive) StartDownload();
            else StartDelete();   // 確かめの窓が出る(受け取らずに消すのは戻せないため)
        }

        // 組の小窓(2.8.0): 右の一覧でチェックした本を受け取り、外した本を要らないにする(確かめの窓に本数と題を出してから)
        void OpenGroupPreview(OutputEntry g, OutputEntry from, string path)
        {
            var items = GroupPacks(g).Select(m => new PreviewItem { No = m.Slot.N, Title = m.Title, Start = m.Slot.PreviewStart, Duration = m.Slot.Duration, Tag = m }).ToList();
            double start = from != null && from.Parent == g && from.Slot != null && from.Slot.HasStart ? from.Slot.PreviewStart : 0;
            PreviewChoice choice;
            try { choice = ShowPlayer(path, OutputFolder.GroupLabel(g), items, start); }
            catch (Exception ex) { OpenExternally(path, ex); return; }
            bool listed = entries.Contains(g);
            if (choice != PreviewChoice.Decide || !listed)
            {
                if (listed) SetRecvStatus("組の行の「受け取る」で全部、1 本ずつの行で 1 本ずつ「受け取る」「要らない」を選べます。", false);
                return;
            }
            if (RecvBusy) { SetRecvStatus("いまの処理が終わってから、もう一度押してください。", true); return; }
            var receive = items.Where(i => i.Checked).Select(i => (OutputEntry)i.Tag).Where(entries.Contains).ToList();
            var discard = items.Where(i => !i.Checked).Select(i => (OutputEntry)i.Tag).Where(entries.Contains).ToList();
            if (receive.Count + discard.Count == 0) return;
            if (MessageBox.Show(this, DecisionText(receive, discard), "組を片付ける", MessageBoxButtons.OKCancel, MessageBoxIcon.Question,
                    discard.Count > 0 ? MessageBoxDefaultButton.Button2 : MessageBoxDefaultButton.Button1) != DialogResult.OK) return;
            RunDecision(receive, discard, false);
        }

        // 確かめの窓の文: 受け取る n 本・要らない m 本(題の一覧)
        string DecisionText(List<OutputEntry> receive, List<OutputEntry> discard)
        {
            Func<List<OutputEntry>, string> lines = list => string.Join("\n", list.Take(10).Select(m => "  " + (m.Slot != null ? m.Slot.N + ". " : "") + m.Title)) +
                                                           (list.Count > 10 ? "\n  ほか " + (list.Count - 10) + " 本" : "");
            string text = "";
            if (receive.Count > 0) text += "受け取る " + receive.Count + " 本(合計 " + Mb(OutputFolder.TotalSize(receive)) + "):\n" + lines(receive) + "\n\n";
            if (discard.Count > 0) text += "要らない " + discard.Count + " 本(送り先の Dropbox から消え、もう受け取れません。要らなかったことは送り先の人に伝わります):\n" + lines(discard) + "\n\n";
            if (receive.Count > 0) text += "受け取る分は古い順に、保存先(" + downloadDir + ")へフォルダとして展開します。";
            return text + (receive.Count > 0 ? "\n" : "") + "よろしいですか?";
        }

        // 小窓が作れない PC: 既定のプレイヤーで開く
        void OpenExternally(string path, Exception why)
        {
            Log.Write("preview window: " + why);
            try
            {
                Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
                SetRecvStatus("まとめ動画を既定のプレイヤーで開きました。要るなら「受け取る」、要らなければ「要らない」を押してください。", false);
            }
            catch (Exception ex2) { SetRecvStatus("まとめ動画を開けませんでした: " + ex2.Message + "(" + path + ")", true); }
        }

        // WPF の部品を使うのはここだけ(読み込めないときは呼んだ側の catch で既定のプレイヤーへ)。items があれば組の小窓(閉じたあと Checked を見る)
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
        PreviewChoice ShowPlayer(string path, string title, List<PreviewItem> items, double start)
        {
            using (var f = new PreviewForm(path, title, items, start))
            {
                f.ShowDialog(this);
                return f.Choice;
            }
        }

        // 失敗の知らせ(読み終えた)か、要らないパック(受け取らずに)を Dropbox から消す
        void StartDelete()
        {
            var e = SelectedEntry;
            if (RecvBusy || !CanDelete(e)) return;
            if (IsGroup(e))   // 組の行 = 組の残りを全部要らない(1 本ずつ記録を置いてから消し、最後に .group.json と組のまとめ動画も消す)
            {
                var all = GroupPacks(e);
                if (MessageBox.Show(this, "この組(" + OutputFolder.GroupLabel(e) + ")の残りを全部、受け取らずに消します。\n\n" + DecisionText(new List<OutputEntry>(), all),
                        "要らない", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
                RunDecision(new List<OutputEntry>(), all, false);
                return;
            }
            bool pack = IsPack(e);
            string ask = pack ? "このパックを受け取らずに消します(送り先の Dropbox から消え、もう受け取れません。要らなかったことは送り先の人に伝わります)。よろしいですか?\n(" + e.Title + ")"
                              : "この失敗の知らせを消します。よろしいですか?\n(" + e.Title + ")";
            if (MessageBox.Show(this, ask, DeleteLabel(e),
                    MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
            Config config = RecvConfig();
            if (config == null) return;
            recvCancel = false;
            SetRecvStatus("消しています…", false);
            Log.Write((pack ? "discard: " : "delete note: ") + e.Name);
            var receiving = NewReceiving(config);
            RunRecv(() =>
            {
                bool recorded = true;
                if (pack)   // 記録を置いてから消す(置けなくても消す。2.6.0)。組の最後の 1 本なら .group.json と組のまとめ動画も消す(2.8.0)
                {
                    recorded = receiving.Discard(e, DateTimeOffset.Now);
                    Receiving.ForgetPreview(e);
                    receiving.FinishGroups(new[] { e });
                }
                else receiving.Delete(e);
                OnUi(() =>
                {
                    RemoveEntry(e);
                    SetRecvStatus(!pack ? "消しました" : recorded ? "消しました(受け取りませんでした。送り先の人に伝わります)"
                                  : "消しました(受け取りませんでした。送り先の人への記録は送れなかったので、伝わりません)", !pack ? false : !recorded);
                });
            });
        }

        // 一覧から外す(Dropbox から消したあと)。先頭を選び直す
        void RemoveEntry(OutputEntry e)
        {
            RemoveEntries(new[] { e });
        }

        void RemoveEntries(IEnumerable<OutputEntry> gone)
        {
            var list = gone.ToList();
            // 組の残りから外す。1 本も残らなくなった組の行も外す(Dropbox の .group.json と組のまとめ動画は、裏の処理が FinishGroups で消した)
            foreach (var e in list.ToList())
            {
                var g = e.Parent;
                if (g == null || !g.Members.Remove(e) || g.Members.Count > 0 || list.Contains(g)) continue;
                list.Add(g);
            }
            outList.BeginUpdate();
            foreach (var e in list)
            {
                entries.Remove(e);
                failureTexts.Remove(e.Key);
                previewQueue.MarkGone(e);
                previewReady.Remove(e.Key);
                outList.Items.Remove(e);
            }
            outList.EndUpdate();
            outList.Invalidate();   // 組の行の「残り n 本」・最後の本の └ を描き直す
            SetArrived(OutputFolder.CountItems(entries), false);
            detail.Text = "";
            if (outList.Items.Count > 0) outList.SelectedIndex = 0;
            UpdateRecvButtons();
        }

        // 受け取りの処理を1つだけ裏で動かす。終わったら(失敗も)ボタンを戻す
        void RunRecv(Action work)
        {
            recvWorker = new Thread(() =>
            {
                string error = null;
                try { work(); }
                catch (Exception ex) { error = RecvError(ex); }
                OnUi(() =>
                {
                    recvRunning = false;
                    recvDownloading = false;
                    recvAll = false;
                    if (error != null) { SetRecvStatus(error, true); if (detail.Text.EndsWith("…")) detail.Text = ""; }
                    UpdateRecvButtons();
                    // 一覧を出した直後に選ばれていた失敗の知らせは、ここで理由を読む
                    var s = SelectedEntry;
                    if (error == null && s != null && s.Kind == OutputKind.Failure && !failureTexts.ContainsKey(s.Key)) ShowSelected();
                });
            });
            recvRunning = true;
            recvWorker.IsBackground = true;
            recvWorker.Start();
            UpdateRecvButtons();
        }

        static string RecvError(Exception ex)
        {
            if (ex is CanceledException) return "やめました。";
            var d = ex as DropboxException;
            if (d != null)
            {
                Log.Write("receive dropbox " + d.Status + ": " + d.Message + " " + d.Body);
                if (d.Status < 0) return d.Message;
                if (d.Status == 0) return "インターネットにつながらないか、通信が切れました。つながっているか確かめて、もう一度押してください。";
                return ErrorText.ForReceive(d.Status, d.Body);
            }
            Log.Write("receive error: " + ex);
            if (ex is IOException || ex is UnauthorizedAccessException) return "保存できませんでした: " + ex.Message;
            return "思わぬエラーで受け取れませんでした: " + ex.Message;
        }

        DropboxClient NewClient(Config config)
        {
            return new DropboxClient(config) { IsCanceled = () => recvCancel, Log = Log.Write };
        }

        // 受け取り終えたパックを Dropbox から消すためのつながり。「やめる」では止めない(消さないと次の更新でまた出て、二度受け取ることになる)。窓を閉じたら止める
        DropboxClient NewDeleter(Config config)
        {
            return new DropboxClient(config) { IsCanceled = () => IsDisposed, Log = Log.Write };
        }

        Receiving NewReceiving(Config config)
        {
            return new Receiving(NewClient(config), NewDeleter(config)) { ExtractZip = state.LoadExtractZip() };
        }

        void ChangeDir()
        {
            if (RecvBusy) return;
            using (var d = new FolderBrowserDialog())
            {
                d.Description = "受け取ったパックを保存するフォルダを選んでください";
                d.ShowNewFolderButton = true;
                if (Directory.Exists(downloadDir)) d.SelectedPath = downloadDir;
                if (d.ShowDialog(this) != DialogResult.OK || string.IsNullOrEmpty(d.SelectedPath)) return;
                downloadDir = d.SelectedPath;
            }
            dirLabel.Text = downloadDir;
            try { state.SaveDownloadDir(downloadDir); }
            catch (Exception ex) { Log.Write("settings: " + ex.Message); }
        }

        void OpenFolder()
        {
            try
            {
                if (lastDownloaded != null && Directory.Exists(lastDownloaded))   // 展開したパックのフォルダ(動画・字幕・Resolve 用のファイルが並ぶ)
                {
                    Process.Start("explorer.exe", "\"" + lastDownloaded + "\"");
                    return;
                }
                if (lastDownloaded != null && File.Exists(lastDownloaded))
                {
                    Process.Start("explorer.exe", "/select,\"" + lastDownloaded + "\"");
                    return;
                }
                Directory.CreateDirectory(downloadDir);
                Process.Start("explorer.exe", "\"" + downloadDir + "\"");
            }
            catch (Exception ex)
            {
                SetRecvStatus("フォルダを開けませんでした: " + ex.Message, true);
            }
        }

        void SetRecvStatus(string text, bool error, bool success = false)
        {
            recvStatus.Tone = error ? Tone.Error : success ? Tone.Accent : Tone.Muted;
            recvStatus.Font = success ? Theme.Bold : Theme.Body;
            recvStatus.Text = (text ?? "").Replace("\r", "").Replace("\n", " ");
            tips.SetToolTip(recvStatus, recvStatus.Text);
        }

        static string SizeText(long bytes)
        {
            if (bytes < 1024 * 1024) return Math.Max(1, (bytes + 1023) / 1024) + "KB";
            return Mb(bytes);
        }

        static string When(DateTime t)
        {
            return t == DateTime.MinValue ? "" : t.ToString("yyyy/MM/dd HH:mm");
        }
    }
}
