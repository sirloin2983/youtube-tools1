// 画面のタブ「受け取る」: 「① 全自動」で送った依頼のパック(.zip)と、失敗の知らせ(.失敗.txt)。
// 一覧は Dropbox の「/出力」を読むだけ(消さない)。受け取ったものは %LOCALAPPDATA%\RequestSender\received.txt に覚える
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;

namespace RequestSender
{
    public partial class MainForm
    {
        readonly LocalState state;
        readonly ListView outList = new ListView();
        readonly TextBox detail = new TextBox();
        readonly Button refreshBtn = new Button(), receiveBtn = new Button(), openFolderBtn = new Button(), changeDirBtn = new Button();
        readonly Label recvStatus = new Label(), dirLabel = new Label();
        readonly ProgressBar recvBar = new ProgressBar();
        readonly Dictionary<string, string> failureTexts = new Dictionary<string, string>();
        List<OutputEntry> entries = new List<OutputEntry>();
        HashSet<string> received = new HashSet<string>();
        string downloadDir, lastDownloaded;
        bool listedOnce;
        Thread recvWorker;
        volatile bool recvCancel;

        // 裏の処理が終わった知らせを画面が受け取るまで true(スレッドが生きているかでは見ない。終わりの直前に並べた画面の処理と食い違うため)
        bool recvRunning;
        bool RecvBusy { get { return recvRunning; } }

        void BuildReceiveLayout()
        {
            var t = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(12), ColumnCount = 1 };
            t.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

            var head = FlowRow();
            refreshBtn.Text = "更新";
            refreshBtn.AutoSize = true;
            refreshBtn.Click += (s, e) => RefreshList();
            head.Controls.Add(refreshBtn);
            head.Controls.Add(new Label
            {
                Text = "「① 全自動」で送ったものは、できあがるとここに届きます。",
                AutoSize = true, Margin = new Padding(6, 7, 3, 0), ForeColor = Color.DimGray,
            });
            t.Controls.Add(head);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            outList.View = View.Details;
            outList.FullRowSelect = true;
            outList.MultiSelect = false;
            outList.HideSelection = false;
            outList.Dock = DockStyle.Fill;
            outList.Columns.Add("種類", 64);
            outList.Columns.Add("題", 220);
            outList.Columns.Add("大きさ", 80, HorizontalAlignment.Right);
            outList.Columns.Add("届いた日時", 118);
            outList.Columns.Add("", 90);
            outList.SelectedIndexChanged += (s, e) => ShowSelected();
            outList.DoubleClick += (s, e) => { var x = SelectedEntry; if (x != null && x.Kind == OutputKind.Pack) StartDownload(); };
            outList.Resize += (s, e) => FitColumns();
            t.Controls.Add(outList);
            t.RowStyles.Add(new RowStyle(SizeType.Percent, 60));

            detail.Multiline = true;
            detail.ReadOnly = true;
            detail.ScrollBars = ScrollBars.Vertical;
            detail.Dock = DockStyle.Fill;
            detail.BackColor = SystemColors.Window;
            t.Controls.Add(detail);
            t.RowStyles.Add(new RowStyle(SizeType.Percent, 40));

            var dirRow = new TableLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, ColumnCount = 3, Margin = new Padding(0, 6, 0, 0) };
            dirRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            dirRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            dirRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            dirRow.Controls.Add(new Label { Text = "保存先:", AutoSize = true, Margin = new Padding(3, 7, 3, 0) }, 0, 0);
            dirLabel.AutoSize = false;
            dirLabel.AutoEllipsis = true;
            dirLabel.Dock = DockStyle.Fill;
            dirLabel.TextAlign = ContentAlignment.MiddleLeft;
            dirRow.Controls.Add(dirLabel, 1, 0);
            changeDirBtn.Text = "変える…";
            changeDirBtn.AutoSize = true;
            changeDirBtn.Click += (s, e) => ChangeDir();
            dirRow.Controls.Add(changeDirBtn, 2, 0);
            t.Controls.Add(dirRow);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            var btns = FlowRow();
            receiveBtn.Text = "受け取る";
            receiveBtn.Font = new Font(Font.FontFamily, 12f, FontStyle.Bold);
            receiveBtn.Size = new Size(160, 44);
            receiveBtn.Margin = new Padding(3, 8, 3, 6);
            receiveBtn.Click += (s, e) => StartDownload();
            openFolderBtn.Text = "フォルダを開く";
            openFolderBtn.AutoSize = true;
            openFolderBtn.Margin = new Padding(8, 16, 3, 6);
            openFolderBtn.Click += (s, e) => OpenFolder();
            btns.Controls.AddRange(new Control[] { receiveBtn, openFolderBtn });
            t.Controls.Add(btns);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            recvBar.Dock = DockStyle.Fill;
            recvBar.Height = 18;
            recvBar.Maximum = 1000;
            t.Controls.Add(recvBar);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            recvStatus.AutoSize = true;
            recvStatus.MaximumSize = new Size(520, 0);
            recvStatus.Margin = new Padding(3, 6, 3, 6);
            t.Controls.Add(recvStatus);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            recvPage.Controls.Add(t);
            Resize += (s, e) => recvStatus.MaximumSize = new Size(Math.Max(200, ClientSize.Width - 50), 0);

            downloadDir = state.LoadDownloadDir();
            received = state.LoadReceived();
            dirLabel.Text = downloadDir;
            UpdateRecvButtons();
        }

        void FitColumns()
        {
            int fixedW = outList.Columns[0].Width + outList.Columns[2].Width + outList.Columns[3].Width + outList.Columns[4].Width;
            int w = outList.ClientSize.Width - fixedW - 4;
            if (w > 80) outList.Columns[1].Width = w;
        }

        OutputEntry SelectedEntry
        {
            get { return outList.SelectedItems.Count == 1 ? outList.SelectedItems[0].Tag as OutputEntry : null; }
        }

        void UpdateRecvButtons()
        {
            var e = SelectedEntry;
            bool busy = RecvBusy;
            refreshBtn.Enabled = !busy;
            changeDirBtn.Enabled = !busy;
            receiveBtn.Enabled = !busy && e != null && e.Kind == OutputKind.Pack;
            receiveBtn.Text = busy && recvDownloading ? "受け取っています…" : "受け取る";
        }

        bool recvDownloading;

        // ---- 一覧 ----
        void RefreshList()
        {
            if (RecvBusy) return;
            Config config;
            try { config = Config.Load(Path.Combine(exeDir, "config.json")); }
            catch (Exception ex) { SetRecvStatus(ConfigProblem(ex), true); return; }
            listedOnce = true;
            SetRecvStatus("届いたものを調べています…", false);
            var client = NewClient(config);
            RunRecv(() =>
            {
                var listing = new Receiving(client).List();
                Ui(() => ShowEntries(listing));
            });
        }

        // テストと画面の確認でも使う(通信しない)
        public void ShowEntries(OutputListing listing)
        {
            entries = listing.Entries;
            received = state.LoadReceived();
            outList.BeginUpdate();
            outList.Items.Clear();
            foreach (var e in entries)
            {
                var item = new ListViewItem(new[] { e.Kind == OutputKind.Pack ? "パック" : "失敗", e.Title, e.Kind == OutputKind.Pack ? SizeText(e.Size) : "", When(e.Modified), "" });
                item.Tag = e;
                if (e.Kind == OutputKind.Failure) item.ForeColor = Color.Firebrick;
                outList.Items.Add(item);
                UpdateRow(item);
            }
            outList.EndUpdate();
            FitColumns();
            detail.Text = "";
            if (entries.Count == 0) SetRecvStatus("まだ届いたものはありません", false);
            else
            {
                int fresh = entries.Count(x => x.Kind == OutputKind.Pack && !received.Contains(x.Key));
                SetRecvStatus(entries.Count + " 件あります" + (fresh > 0 ? "(まだ受け取っていないパック " + fresh + " 件)" : "") + "。選んで「受け取る」を押してください。", false);
                outList.Items[0].Selected = true;
            }
            UpdateRecvButtons();
        }

        void UpdateRow(ListViewItem item)
        {
            var e = (OutputEntry)item.Tag;
            bool done = received.Contains(e.Key);
            item.SubItems[4].Text = e.Kind == OutputKind.Pack ? (done ? "受け取り済み" : "まだ") : (done ? "読んだ" : "まだ読んでいない");
            item.Font = done ? outList.Font : new Font(outList.Font, FontStyle.Bold);
        }

        void ShowSelected()
        {
            UpdateRecvButtons();
            var e = SelectedEntry;
            if (e == null) { detail.Text = ""; return; }
            if (e.Kind == OutputKind.Pack)
            {
                detail.Text = "題: " + e.Title + "\r\n" +
                              (e.RequestId.Length > 0 ? "依頼: " + e.RequestId + "\r\n" : "") +
                              "大きさ: " + SizeText(e.Size) + "\r\n届いた日時: " + When(e.Modified) + "\r\n\r\n" +
                              "DaVinci Resolve のパック(字幕は校正の前)です。" +
                              (received.Contains(e.Key) ? "受け取り済みです(もう一度受け取ることもできます)。" : "「受け取る」を押すと保存先に保存します。");
                return;
            }
            string text;
            if (failureTexts.TryGetValue(e.Key, out text)) { ShowFailure(e, text); return; }
            if (RecvBusy) { detail.Text = "自動の処理が失敗しました。理由は、いまの処理が終わってから読みます。"; return; }
            Config config;
            try { config = Config.Load(Path.Combine(exeDir, "config.json")); }
            catch (Exception ex) { SetRecvStatus(ConfigProblem(ex), true); return; }
            detail.Text = "自動の処理が失敗しました。理由を読んでいます…";
            var client = NewClient(config);
            RunRecv(() =>
            {
                string reason = new Receiving(client).FailureText(e);
                Ui(() =>
                {
                    failureTexts[e.Key] = reason;
                    state.MarkReceived(e);
                    received.Add(e.Key);
                    foreach (ListViewItem it in outList.Items) if (it.Tag == e) UpdateRow(it);
                    if (SelectedEntry == e) ShowFailure(e, reason);
                });
            });
        }

        void ShowFailure(OutputEntry e, string reason)
        {
            detail.Text = "自動の処理が失敗しました(" + e.Title + ")。\r\n送り先の人に伝えるか、「② 軽く確認」か「③ 全部人が行う」で送り直してください。\r\n\r\n理由:\r\n" + reason;
        }

        // ---- 受け取る ----
        void StartDownload()
        {
            var e = SelectedEntry;
            if (RecvBusy || e == null || e.Kind != OutputKind.Pack) return;
            Config config;
            try { config = Config.Load(Path.Combine(exeDir, "config.json")); }
            catch (Exception ex) { SetRecvStatus(ConfigProblem(ex), true); return; }
            string dir = downloadDir;
            recvCancel = false;
            recvDownloading = true;
            recvBar.Value = 0;
            SetRecvStatus("受け取る準備をしています…", false);
            Log.Write("receive: " + e.Name + " size=" + e.Size);
            var client = NewClient(config);
            int lastPermille = -1;
            string lastStep = null;
            RunRecv(() =>
            {
                string path = new Receiving(client).Download(e, dir, (done, total, step) =>
                {
                    int permille = (int)Math.Max(0, Math.Min(1000, done * 1000 / Math.Max(1, total)));
                    if (permille == lastPermille && step == lastStep) return;
                    lastPermille = permille;
                    lastStep = step;
                    Ui(() => { if (RecvBusy) { recvBar.Value = permille; SetRecvStatus(step + "… (" + Mb(done) + " / " + Mb(total) + ")", false); } });
                });
                Log.Write("receive: ok " + path);
                Ui(() =>
                {
                    state.MarkReceived(e);
                    received.Add(e.Key);
                    foreach (ListViewItem it in outList.Items) if (it.Tag == e) UpdateRow(it);
                    lastDownloaded = path;
                    recvBar.Value = 1000;
                    SetRecvStatus("受け取りました ✓  " + Path.GetFileName(path) + "\n「フォルダを開く」で見られます。", false, true);
                    ShowSelected();
                });
            });
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
                Ui(() =>
                {
                    recvRunning = false;
                    recvDownloading = false;
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
            recvStatus.Text = text;
            recvStatus.ForeColor = error ? Color.Firebrick : success ? Color.ForestGreen : SystemColors.ControlText;
            recvStatus.Font = success ? new Font(Font.FontFamily, 11f, FontStyle.Bold) : Font;
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
