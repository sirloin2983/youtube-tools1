// 画面のタブ「受け取る」: 「① 全自動」で送った依頼のパック(.zip)と、失敗の知らせ(.失敗.txt)。
// 一覧は Dropbox の「/出力」。受け取り終えたパック(確かめたあと)と、読み終えて「消す」を押した失敗の知らせは Dropbox から消え、一覧にも出なくなる。
// 「すべて受け取る」= 届いているパックを古い順に 1 本ずつ(1 つの依頼で何本もできたときに、1 本ずつ押さなくて済むように。2026-10-07)。「やめる」で途中で止められる
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
                     cancelRecvBtn = new Btn("やめる", BtnKind.Normal), deleteBtn = new Btn("消す", BtnKind.Normal),
                     openFolderBtn = new Btn("フォルダを開く", BtnKind.Normal), changeDirBtn = new Btn("変える…", BtnKind.Normal);
        readonly Lbl recvHint = new Lbl("「① 全自動」で送ったものは、できあがるとここに届きます(1 つの依頼で何本もできることがあります)。「すべて受け取る」でまとめて受け取れます。受け取ったものは一覧から消えます。", Tone.Muted);
        readonly Lbl recvStatus = new Lbl("", Tone.Muted), lDir = new Lbl("保存先", Tone.Muted), dirLabel = new Lbl("", Tone.Text);
        readonly Bar recvBar = new Bar();
        readonly Dictionary<string, string> failureTexts = new Dictionary<string, string>();
        List<OutputEntry> entries = new List<OutputEntry>();
        string downloadDir, lastDownloaded;
        bool listedOnce;
        Thread recvWorker;
        volatile bool recvCancel;

        // 裏の処理が終わった知らせを画面が受け取るまで true(スレッドが生きているかでは見ない。終わりの直前に並べた画面の処理と食い違うため)
        bool recvRunning;
        bool recvAll;   // 「すべて受け取る」の途中
        bool RecvBusy { get { return recvRunning; } }

        void BuildReceiveLayout()
        {
            refreshBtn.Click += (s, e) => RefreshList();
            recvHint.Font = Theme.Small;
            recvHint.AutoSize = false;

            outList.AccessibleName = "届いたものの一覧";
            outList.Texts = e => new[] { e.Kind == OutputKind.Pack ? "パック" : "失敗", e.Title, e.Kind == OutputKind.Pack ? SizeText(e.Size) : "", When(e.Modified) };
            outList.SelectedIndexChanged += (s, e) => ShowSelected();
            outList.DoubleClick += (s, e) => { var x = SelectedEntry; if (x != null && x.Kind == OutputKind.Pack) StartDownload(); };
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
            openFolderBtn.Click += (s, e) => OpenFolder();
            deleteBtn.Click += (s, e) => StartDeleteFailure();
            recvStatus.AutoSize = false;
            recvStatus.AutoEllipsis = true;

            recvPane.Controls.AddRange(new Control[] { headRecv, refreshBtn, recvHint, listFrame, detailField, lDir, dirLabel, changeDirBtn,
                                                       receiveBtn, receiveAllBtn, cancelRecvBtn, openFolderBtn, deleteBtn, recvBar, recvStatus });
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
            receiveBtn.SetBounds(m, y, Ui.S(150), Ui.S(40));
            receiveAllBtn.SetBounds(receiveBtn.Right + Ui.S(8), y, receiveAllBtn.Width, Ui.S(40));
            int x = receiveAllBtn.Right + Ui.S(8);
            cancelRecvBtn.Location = new Point(x, y + Ui.S(6));
            if (cancelRecvBtn.Visible) x = cancelRecvBtn.Right + Ui.S(8);
            openFolderBtn.Location = new Point(x, y + Ui.S(6));
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

        void UpdateRecvButtons()
        {
            var e = SelectedEntry;
            bool busy = RecvBusy;
            int packs = entries.Count(x => x.Kind == OutputKind.Pack);
            refreshBtn.Enabled = !busy;
            changeDirBtn.Enabled = !busy;
            receiveBtn.Enabled = !busy && e != null && e.Kind == OutputKind.Pack;
            deleteBtn.Enabled = !busy && e != null && e.Kind == OutputKind.Failure && failureTexts.ContainsKey(e.Key);
            receiveBtn.Text = busy && recvDownloading && !recvAll ? "受け取っています…" : "受け取る";
            receiveAllBtn.Enabled = !busy && packs > 0;
            receiveAllBtn.Text = busy && recvAll ? "すべて受け取っています…" : packs > 1 ? "すべて受け取る(" + packs + " 本)" : "すべて受け取る";
            receiveAllBtn.FitWidth();
            cancelRecvBtn.Visible = busy && recvDownloading;
            cancelRecvBtn.Enabled = !recvCancel;
            LayoutReceive();   // 「やめる」の出し入れ・「すべて受け取る(n 本)」の幅で、右のボタンの位置が変わる
        }

        bool recvDownloading;

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
            SetArrived(entries.Count, false);
            int packs = entries.Count(x => x.Kind == OutputKind.Pack), fails = entries.Count - packs;
            if (entries.Count == 0) SetRecvStatus("まだ届いたものはありません", false);
            else
            {
                string what = (packs > 0 ? "パック " + packs + " 本" : "") + (packs > 0 && fails > 0 ? "・" : "") + (fails > 0 ? "失敗の知らせ " + fails + " 件" : "");
                string how = packs > 1 ? "「すべて受け取る」でまとめて受け取れます。" : packs == 1 ? "選んで「受け取る」を押してください。" : "選ぶと理由が出ます。";
                SetRecvStatus(what + "があります。" + how, false);
                outList.SelectedIndex = 0;
            }
            UpdateRecvButtons();
        }

        void ShowSelected()
        {
            UpdateRecvButtons();
            var e = SelectedEntry;
            if (e == null) { detail.Text = ""; return; }
            if (e.Kind == OutputKind.Pack)
            {
                int same = OutputFolder.CountSameRequest(entries, e);
                detail.Text = "題: " + e.Title + "\r\n" +
                              (e.RequestId.Length > 0 ? "依頼: " + e.RequestId + (same > 1 ? "(この依頼のパックは、届いている中に " + same + " 本)" : "") + "\r\n" : "") +
                              "大きさ: " + SizeText(e.Size) + "\r\n届いた日時: " + When(e.Modified) + "\r\n\r\n" +
                              "DaVinci Resolve のパック(字幕は校正の前)です。「受け取る」を押すと保存先に保存し、確かめたあと Dropbox と一覧から消えます。";
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

        void ShowFailure(OutputEntry e, string reason)
        {
            detail.Text = "自動の処理が失敗しました(" + e.Title + ")。\r\n送り先の人に伝えるか、「② 軽く確認」か「③ 全部人が行う」で送り直してください。\r\n読み終えたら「消す」を押すと、一覧から消えます。\r\n\r\n理由:\r\n" + reason;
        }

        // ---- 受け取る ----
        void StartDownload()
        {
            var e = SelectedEntry;
            if (RecvBusy || e == null || e.Kind != OutputKind.Pack) return;
            Config config = RecvConfig();
            if (config == null) return;
            string dir = downloadDir;
            recvCancel = false;
            recvDownloading = true;
            recvBar.Value = 0;
            SetRecvStatus("受け取る準備をしています…", false);
            Log.Write("receive: " + e.Name + " size=" + e.Size);
            var client = NewClient(config);
            var receiving = new Receiving(client, NewDeleter(config));
            int lastPermille = -1;
            string lastStep = null;
            RunRecv(() =>
            {
                string path = receiving.Download(e, dir, (done, total, step) =>
                {
                    int permille = (int)Math.Max(0, Math.Min(1000, done * 1000 / Math.Max(1, total)));
                    if (permille == lastPermille && step == lastStep) return;
                    lastPermille = permille;
                    lastStep = step;
                    OnUi(() => { if (RecvBusy) { recvBar.Value = permille; SetRecvStatus(step + "… (" + Mb(done) + " / " + Mb(total) + ")", false); } });
                });
                Log.Write("receive: ok " + path);
                // 大きさと hash を確かめて名前を変えたあと(Download が例外なく返った)だけ、Dropbox から消す
                bool deleted = true;
                try { receiving.Delete(e); }
                catch (Exception ex)
                {
                    deleted = false;
                    Log.Write("receive: delete failed " + e.Name + ": " + ex.Message);
                }
                OnUi(() =>
                {
                    lastDownloaded = path;
                    recvBar.Value = 1000;
                    if (deleted)
                    {
                        RemoveEntry(e);
                        SetRecvStatus("受け取りました ✓  " + Path.GetFileName(path) + "\n「フォルダを開く」で見られます。", false, true);
                    }
                    else
                    {
                        SetRecvStatus("受け取りましたが、Dropbox から消せませんでした(次に更新したときにまた出ます)\n" + Path.GetFileName(path), true);
                        ShowSelected();
                    }
                });
            });
            UpdateRecvButtons();
        }

        // 届いているパックを古い順にまとめて受け取る(1 本ずつ受け取って確かめ、確かめ終えたものから Dropbox と一覧から消す)
        void StartDownloadAll()
        {
            if (RecvBusy) return;
            var packs = OutputFolder.PacksOldestFirst(entries);
            if (packs.Count == 0) return;
            long total = OutputFolder.TotalSize(packs);
            if (MessageBox.Show(this, "届いているパック " + packs.Count + " 本(合計 " + Mb(total) + ")をすべて受け取ります。\n保存先: " + downloadDir +
                    "\n\n古い順に 1 本ずつ受け取り、ちゃんと保存できたものから Dropbox と一覧から消えます。途中で「やめる」を押せます。",
                    "すべて受け取る", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
            Config config = RecvConfig();
            if (config == null) return;
            string dir = downloadDir;
            recvCancel = false;
            recvDownloading = recvAll = true;
            recvBar.Value = 0;
            SetRecvStatus("受け取る準備をしています…(" + packs.Count + " 本)", false);
            Log.Write("receive all: " + packs.Count + " packs, " + total + " bytes");
            var receiving = new Receiving(NewClient(config), NewDeleter(config));
            int lastPermille = -1, lastNo = 0;
            string lastStep = null;
            RunRecv(() =>
            {
                var r = receiving.DownloadAll(packs, dir, (no, e, done, all, step) =>
                {
                    int permille = (int)Math.Max(0, Math.Min(1000, done * 1000 / Math.Max(1, all)));
                    if (permille == lastPermille && no == lastNo && step == lastStep) return;
                    lastPermille = permille;
                    lastNo = no;
                    lastStep = step;
                    string text = step + "(" + no + " / " + packs.Count + " 本目: " + e.Title + ")… (全体 " + Mb(done) + " / " + Mb(all) + ")";
                    OnUi(() => { if (RecvBusy) { recvBar.Value = permille; SetRecvStatus(text, false); } });
                });
                Log.Write("receive all: " + r.Received + "/" + r.Total + (r.Canceled ? " canceled" : "") + (r.Error != null ? " stopped: " + r.Error.Message : "") +
                          (r.Failed.Count > 0 ? " skipped " + r.Failed.Count : "") + (r.Kept.Count > 0 ? " not deleted " + r.Kept.Count : ""));
                OnUi(() => FinishDownloadAll(r));
            });
        }

        void FinishDownloadAll(ReceiveAllResult r)
        {
            if (r.LastPath != null) lastDownloaded = r.LastPath;
            RemoveEntries(r.Done);
            bool clean = r.Error == null && !r.Canceled && r.Failed.Count == 0 && r.Kept.Count == 0;
            if (clean) recvBar.Value = 1000;
            SetRecvStatus(r.Summary(r.Error != null ? RecvError(r.Error) : null), r.Error != null || r.Failed.Count > 0, clean);
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

        // 画面の確認(--tab receive --state receiving): 「すべて受け取る」の途中の見た目(通信しない)
        public void ShowReceivingSample()
        {
            recvRunning = recvDownloading = recvAll = true;
            recvBar.Value = 335;
            SetRecvStatus("受け取っています(2 / 5 本目: 見本の切り抜き_03)… (全体 2.51GB / 7.50GB)", false);
            UpdateRecvButtons();
        }

        // 読み終えた失敗の知らせを Dropbox から消す
        void StartDeleteFailure()
        {
            var e = SelectedEntry;
            if (RecvBusy || e == null || e.Kind != OutputKind.Failure || !failureTexts.ContainsKey(e.Key)) return;
            if (MessageBox.Show(this, "この失敗の知らせを消します。よろしいですか?\n(" + e.Title + ")", "消す",
                    MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
            Config config = RecvConfig();
            if (config == null) return;
            recvCancel = false;
            SetRecvStatus("消しています…", false);
            var client = NewClient(config);
            RunRecv(() =>
            {
                new Receiving(client).Delete(e);
                OnUi(() =>
                {
                    RemoveEntry(e);
                    SetRecvStatus("消しました", false);
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
            outList.BeginUpdate();
            foreach (var e in gone.ToList())
            {
                entries.Remove(e);
                failureTexts.Remove(e.Key);
                outList.Items.Remove(e);
            }
            outList.EndUpdate();
            SetArrived(entries.Count, false);
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
