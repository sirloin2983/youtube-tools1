// 画面のタブ「受け取る」: 「① 全自動」で送った依頼のパック(.zip)と、失敗の知らせ(.失敗.txt)。
// 一覧は Dropbox の「/出力」。受け取り終えたパック(確かめたあと)と、読み終えて「消す」を押した失敗の知らせは Dropbox から消え、一覧にも出なくなる
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
        readonly Pane recvPane = new Pane { OnPanel = true, Border = true }, listFrame = new Pane { Border = true };
        readonly SectionHead headRecv = new SectionHead("01", "届いたもの");
        readonly ListView outList = new ListView();
        readonly TextBox detail = new TextBox();
        Field detailField;
        readonly Btn refreshBtn = new Btn("更新", BtnKind.Normal), receiveBtn = new Btn("受け取る", BtnKind.Primary), deleteBtn = new Btn("消す", BtnKind.Normal),
                     openFolderBtn = new Btn("フォルダを開く", BtnKind.Normal), changeDirBtn = new Btn("変える…", BtnKind.Normal);
        readonly Lbl recvHint = new Lbl("「① 全自動」で送ったものは、できあがるとここに届きます。できた順に1本ずつ届き、受け取ると一覧から消えます。", Tone.Muted);
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
        bool RecvBusy { get { return recvRunning; } }

        void BuildReceiveLayout()
        {
            refreshBtn.Click += (s, e) => RefreshList();
            recvHint.Font = Theme.Small;
            recvHint.AutoSize = false;

            outList.View = View.Details;
            outList.FullRowSelect = true;
            outList.MultiSelect = false;
            outList.HideSelection = false;
            outList.BorderStyle = BorderStyle.None;
            outList.HeaderStyle = ColumnHeaderStyle.Nonclickable;
            outList.Font = Theme.Body;
            outList.AccessibleName = "届いたものの一覧";
            outList.Columns.Add("種類", Ui.S(70));
            outList.Columns.Add("題", Ui.S(220));
            outList.Columns.Add("大きさ", Ui.S(90), HorizontalAlignment.Right);
            outList.Columns.Add("届いた日時", Ui.S(140));
            outList.SelectedIndexChanged += (s, e) => ShowSelected();
            outList.DoubleClick += (s, e) => { var x = SelectedEntry; if (x != null && x.Kind == OutputKind.Pack) StartDownload(); };
            outList.Resize += (s, e) => FitColumns();
            // 見出しと行を配色に合わせて自分で描く(標準の白い見出し・青い選択を出さない)
            outList.OwnerDraw = true;
            outList.DrawColumnHeader += (s, e) =>
            {
                var p = Theme.P;
                using (var b = new SolidBrush(p.Panel)) e.Graphics.FillRectangle(b, e.Bounds);
                using (var pen = new Pen(p.Line)) e.Graphics.DrawLine(pen, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);
                var r = Rectangle.Inflate(e.Bounds, -Ui.S(6), 0);
                TextRenderer.DrawText(e.Graphics, e.Header.Text, Theme.Small, r, p.Muted,
                    TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix | (e.Header.TextAlign == HorizontalAlignment.Right ? TextFormatFlags.Right : TextFormatFlags.Left));
            };
            outList.DrawItem += (s, e) => { };
            outList.DrawSubItem += (s, e) =>
            {
                var p = Theme.P;
                var entry = e.Item.Tag as OutputEntry;
                using (var b = new SolidBrush(e.Item.Selected ? Theme.Mix(p.Bg, p.Accent, 0.25) : p.Bg)) e.Graphics.FillRectangle(b, e.Bounds);
                Color fg = e.ColumnIndex == 0 && entry != null && entry.Kind == OutputKind.Failure ? p.Error : e.ColumnIndex >= 2 ? p.Muted : p.Text;
                var r = Rectangle.Inflate(e.Bounds, -Ui.S(6), 0);
                TextRenderer.DrawText(e.Graphics, e.SubItem.Text, outList.Font, r, fg,
                    TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis |
                    (e.Header.TextAlign == HorizontalAlignment.Right ? TextFormatFlags.Right : TextFormatFlags.Left));
            };
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
            openFolderBtn.Click += (s, e) => OpenFolder();
            deleteBtn.Click += (s, e) => StartDeleteFailure();
            recvStatus.AutoSize = false;
            recvStatus.AutoEllipsis = true;

            recvPane.Controls.AddRange(new Control[] { headRecv, refreshBtn, recvHint, listFrame, detailField, lDir, dirLabel, changeDirBtn,
                                                       receiveBtn, openFolderBtn, deleteBtn, recvBar, recvStatus });
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
            int top = m + Ui.S(54), foot = Ui.S(128), rest = Math.Max(Ui.S(120), h - top - foot - m);
            int listH = rest * 55 / 100;
            listFrame.SetBounds(m, top, iw, listH);
            outList.SetBounds(1, 1, iw - 2, listH - 2);
            detailField.SetBounds(m, top + listH + Ui.S(8), iw, rest - listH - Ui.S(8));
            int y = top + rest + Ui.S(10);
            lDir.Location = new Point(m, y + Ui.S(5));
            changeDirBtn.Location = new Point(w - m - changeDirBtn.Width, y);
            dirLabel.SetBounds(lDir.Right + Ui.S(8), y, changeDirBtn.Left - lDir.Right - Ui.S(16), Ui.S(28));
            y += Ui.S(38);
            receiveBtn.SetBounds(m, y, Ui.S(150), Ui.S(40));
            openFolderBtn.Location = new Point(receiveBtn.Right + Ui.S(8), y + Ui.S(6));
            deleteBtn.Location = new Point(openFolderBtn.Right + Ui.S(6), y + Ui.S(6));
            recvStatus.SetBounds(deleteBtn.Right + Ui.S(14), y + Ui.S(10), Math.Max(Ui.S(60), w - m - deleteBtn.Right - Ui.S(14)), Ui.S(20));
            y += Ui.S(48);
            recvBar.SetBounds(m, y, iw, Ui.S(3));
            FitColumns();
        }

        // 一覧は標準の部品なので、地と文字の色をここで合わせる
        void ThemeReceive()
        {
            outList.BackColor = Theme.P.Bg;
            outList.ForeColor = Theme.P.Text;
            outList.Invalidate();
        }

        void FitColumns()
        {
            if (outList.Columns.Count < 4) return;
            int fixedW = outList.Columns[0].Width + outList.Columns[2].Width + outList.Columns[3].Width;
            int w = outList.ClientSize.Width - fixedW;   // 見出しの右に標準の白い余りを残さない
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
            deleteBtn.Enabled = !busy && e != null && e.Kind == OutputKind.Failure && failureTexts.ContainsKey(e.Key);
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
                OnUi(() => ShowEntries(listing));
            });
        }

        // テストと画面の確認でも使う(通信しない)
        public void ShowEntries(OutputListing listing)
        {
            entries = listing.Entries;
            outList.BeginUpdate();
            outList.Items.Clear();
            foreach (var e in entries)
            {
                var item = new ListViewItem(new[] { e.Kind == OutputKind.Pack ? "パック" : "失敗", e.Title, e.Kind == OutputKind.Pack ? SizeText(e.Size) : "", When(e.Modified) });
                item.Tag = e;
                outList.Items.Add(item);
            }
            outList.EndUpdate();
            FitColumns();
            detail.Text = "";
            SetArrived(entries.Count, false);
            if (entries.Count == 0) SetRecvStatus("まだ届いたものはありません", false);
            else
            {
                SetRecvStatus(entries.Count + " 件あります。選んで「受け取る」を押してください。", false);
                outList.Items[0].Selected = true;
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
                detail.Text = "題: " + e.Title + "\r\n" +
                              (e.RequestId.Length > 0 ? "依頼: " + e.RequestId + "\r\n" : "") +
                              "大きさ: " + SizeText(e.Size) + "\r\n届いた日時: " + When(e.Modified) + "\r\n\r\n" +
                              "DaVinci Resolve のパック(字幕は校正の前)です。「受け取る」を押すと保存先に保存し、確かめたあと Dropbox と一覧から消えます。";
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
                    OnUi(() => { if (RecvBusy) { recvBar.Value = permille; SetRecvStatus(step + "… (" + Mb(done) + " / " + Mb(total) + ")", false); } });
                });
                Log.Write("receive: ok " + path);
                // 大きさと hash を確かめて名前を変えたあと(Download が例外なく返った)だけ、Dropbox から消す
                bool deleted = true;
                try { new Receiving(client).Delete(e); }
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

        // 読み終えた失敗の知らせを Dropbox から消す
        void StartDeleteFailure()
        {
            var e = SelectedEntry;
            if (RecvBusy || e == null || e.Kind != OutputKind.Failure || !failureTexts.ContainsKey(e.Key)) return;
            if (MessageBox.Show(this, "この失敗の知らせを消します。よろしいですか?\n(" + e.Title + ")", "消す",
                    MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
            Config config;
            try { config = Config.Load(Path.Combine(exeDir, "config.json")); }
            catch (Exception ex) { SetRecvStatus(ConfigProblem(ex), true); return; }
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
            entries.Remove(e);
            failureTexts.Remove(e.Key);
            foreach (ListViewItem it in outList.Items.Cast<ListViewItem>().ToList())
                if (it.Tag == e) outList.Items.Remove(it);
            SetArrived(entries.Count, false);
            detail.Text = "";
            if (outList.Items.Count > 0) outList.Items[0].Selected = true;
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
