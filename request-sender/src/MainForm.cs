// 画面: 動画(ドラッグ)/ 配信者 / 配信の URL と切り抜く数 / メモ / 「送る」/ 進み具合と「送りました ✓」
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;

namespace RequestSender
{
    public class MainForm : Form
    {
        const string NoStreamer = "(選ばない)";

        readonly string exeDir;
        readonly ListBox files = new ListBox();
        readonly Button addBtn = new Button(), removeBtn = new Button(), sendBtn = new Button();
        readonly ComboBox streamer = new ComboBox();
        readonly TextBox urls = new TextBox(), memo = new TextBox();
        readonly NumericUpDown top = new NumericUpDown();
        readonly ProgressBar bar = new ProgressBar();
        readonly Label status = new Label(), dropHint = new Label();
        readonly LinkLabel sendToLink = new LinkLabel();
        Thread worker;
        volatile bool cancel;

        public MainForm(string exeDir, string[] initialFiles)
        {
            this.exeDir = exeDir;
            Text = AppInfo.Title;
            Font = new Font("Yu Gothic UI", 10f);
            AutoScaleMode = AutoScaleMode.Font;
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(520, 600);
            ClientSize = new Size(560, 660);
            AllowDrop = true;
            BuildLayout();
            LoadMembers();
            AddFiles(initialFiles, false);
            DragEnter += OnDragEnter;
            DragDrop += OnDragDrop;
            Shown += (s, e) =>
            {
                CheckConfig();
                Program.MaybeAskSendTo(this);
                UpdateSendToLink();
            };
            FormClosing += OnClosing;
        }

        void BuildLayout()
        {
            var t = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(12), ColumnCount = 1, AutoSize = false };
            t.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

            t.Controls.Add(Heading("① 動画を送る(ここへドラッグ。いくつでも)"));
            files.Dock = DockStyle.Fill;
            files.SelectionMode = SelectionMode.MultiExtended;
            files.AllowDrop = true;
            files.HorizontalScrollbar = true;
            files.DragEnter += OnDragEnter;
            files.DragDrop += OnDragDrop;
            files.KeyDown += (s, e) => { if (e.KeyCode == Keys.Delete) RemoveSelected(); };
            var filePanel = new Panel { Dock = DockStyle.Fill, Height = 110 };
            dropHint.Text = "動画のファイルをここへドラッグ(.mp4 .mov .mkv .webm .m4v)";
            dropHint.ForeColor = SystemColors.GrayText;
            dropHint.BackColor = SystemColors.Window;
            dropHint.TextAlign = ContentAlignment.MiddleCenter;
            dropHint.Dock = DockStyle.Fill;
            dropHint.AllowDrop = true;
            dropHint.BorderStyle = BorderStyle.FixedSingle;
            dropHint.DragEnter += OnDragEnter;
            dropHint.DragDrop += OnDragDrop;
            dropHint.Click += (s, e) => PickFiles();
            filePanel.Controls.Add(dropHint);
            filePanel.Controls.Add(files);
            t.Controls.Add(filePanel);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            t.RowStyles.Add(new RowStyle(SizeType.Percent, 40));

            var fileBtns = Flow();
            addBtn.Text = "ファイルを選ぶ…";
            addBtn.AutoSize = true;
            addBtn.Click += (s, e) => PickFiles();
            removeBtn.Text = "選んだものを外す";
            removeBtn.AutoSize = true;
            removeBtn.Click += (s, e) => RemoveSelected();
            fileBtns.Controls.AddRange(new Control[] { addBtn, removeBtn });
            t.Controls.Add(fileBtns);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            var sRow = Flow();
            var sLabel = new Label { Text = "配信者(任意。字幕の色に使う):", AutoSize = true, Margin = new Padding(3, 7, 3, 0) };
            streamer.DropDownStyle = ComboBoxStyle.DropDownList;
            streamer.Width = 200;
            streamer.MaxDropDownItems = 20;
            sRow.Controls.AddRange(new Control[] { sLabel, streamer });
            t.Controls.Add(sRow);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            t.Controls.Add(Heading("② 配信を切り抜いてもらう(YouTube の URL。1行に1本)"));
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            urls.Multiline = true;
            urls.ScrollBars = ScrollBars.Vertical;
            urls.AcceptsReturn = true;
            urls.WordWrap = false;
            urls.Dock = DockStyle.Fill;
            urls.AllowDrop = true;
            urls.DragEnter += OnDragEnter;
            urls.DragDrop += OnDragDrop;
            t.Controls.Add(urls);
            t.RowStyles.Add(new RowStyle(SizeType.Percent, 30));

            var topRow = Flow();
            top.Minimum = Validation.MinTop;
            top.Maximum = Validation.MaxTop;
            top.Value = Validation.DefaultTop;
            top.Width = 60;
            topRow.Controls.Add(new Label { Text = "1本の配信から切り抜く数:", AutoSize = true, Margin = new Padding(3, 7, 3, 0) });
            topRow.Controls.Add(top);
            topRow.Controls.Add(new Label { Text = "(" + Validation.MinTop + "〜" + Validation.MaxTop + ")", AutoSize = true, Margin = new Padding(3, 7, 3, 0), ForeColor = SystemColors.GrayText });
            t.Controls.Add(topRow);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            t.Controls.Add(Heading("メモ(任意。送り先の人が読みます)"));
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            memo.Multiline = true;
            memo.ScrollBars = ScrollBars.Vertical;
            memo.AcceptsReturn = true;
            memo.MaxLength = 2000;
            memo.Dock = DockStyle.Fill;
            t.Controls.Add(memo);
            t.RowStyles.Add(new RowStyle(SizeType.Percent, 30));

            sendBtn.Text = "送る";
            sendBtn.Font = new Font(Font.FontFamily, 12f, FontStyle.Bold);
            sendBtn.Dock = DockStyle.Fill;
            sendBtn.Height = 44;
            sendBtn.Margin = new Padding(3, 10, 3, 6);
            sendBtn.Click += (s, e) => StartSend();
            t.Controls.Add(sendBtn);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            bar.Dock = DockStyle.Fill;
            bar.Height = 18;
            bar.Maximum = 1000;
            t.Controls.Add(bar);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            status.AutoSize = true;
            status.MaximumSize = new Size(520, 0);
            status.Margin = new Padding(3, 6, 3, 6);
            t.Controls.Add(status);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            sendToLink.AutoSize = true;
            sendToLink.Text = "動画の右クリックの「送る」にも出す";
            sendToLink.LinkClicked += (s, e) =>
            {
                if (Program.CreateSendTo(this)) SetStatus("右クリック →「送る」→「切り抜き依頼」で送れるようになりました。", false);
                UpdateSendToLink();
            };
            t.Controls.Add(sendToLink);
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            Controls.Add(t);
            Resize += (s, e) => status.MaximumSize = new Size(Math.Max(200, ClientSize.Width - 40), 0);
            UpdateFileView();
        }

        static Label Heading(string text)
        {
            return new Label { Text = text, AutoSize = true, Font = new Font("Yu Gothic UI", 10f, FontStyle.Bold), Margin = new Padding(3, 10, 3, 4) };
        }

        static FlowLayoutPanel Flow()
        {
            return new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true, Margin = new Padding(0) };
        }

        void LoadMembers()
        {
            streamer.Items.Add(NoStreamer);
            foreach (string n in Members.LoadNames(Path.Combine(exeDir, "members.json"))) streamer.Items.Add(n);
            streamer.SelectedIndex = 0;
            streamer.Enabled = streamer.Items.Count > 1;
        }

        void CheckConfig()
        {
            try
            {
                Config.Load(Path.Combine(exeDir, "config.json"));
            }
            catch (Exception ex)
            {
                SetStatus(ConfigProblem(ex), true);
            }
        }

        static string ConfigProblem(Exception ex)
        {
            if (ex is FileNotFoundException) return "config.json(送るための鍵)が見つかりません。RequestSender.exe と同じフォルダに置いてください。";
            return "config.json が読めません。送り先の人にもう一度もらってください。(" + ex.Message + ")";
        }

        void UpdateSendToLink()
        {
            sendToLink.Visible = !SendToShortcut.Exists();
        }

        // ---- 動画の出し入れ ----
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
            if (paths != null) { AddFiles(paths, true); return; }
            // ブラウザのアドレスをドラッグしたとき: URL の欄に足す
            string text = (e.Data.GetData(DataFormats.UnicodeText) ?? e.Data.GetData(DataFormats.Text)) as string;
            if (!string.IsNullOrWhiteSpace(text))
            {
                string cur = urls.Text.TrimEnd();
                urls.Text = (cur.Length > 0 ? cur + "\r\n" : "") + text.Trim() + "\r\n";
                urls.SelectionStart = urls.Text.Length;
            }
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
            UpdateFileView();
            if (skipped.Count > 0)
                SetStatus("動画ではないので入れませんでした(" + string.Join(" / ", Validation.VideoExts) + " だけ): " +
                          string.Join("、", skipped.Take(5)) + (skipped.Count > 5 ? " ほか " + (skipped.Count - 5) + " 個" : ""), true);
            else if (fromUser) SetStatus("", false);
        }

        void RemoveSelected()
        {
            if (Busy) return;
            foreach (var item in files.SelectedItems.Cast<object>().ToList()) files.Items.Remove(item);
            UpdateFileView();
        }

        void UpdateFileView()
        {
            dropHint.Visible = files.Items.Count == 0;   // 重ねず、どちらか一方だけ出す
            files.Visible = files.Items.Count > 0;
            removeBtn.Enabled = files.Items.Count > 0 && !Busy;
        }

        // ---- 送る ----
        bool Busy { get { return worker != null && worker.IsAlive; } }

        void StartSend()
        {
            if (Busy) return;
            var parsed = Validation.ParseUrlLines(urls.Text);
            var input = new SendInput
            {
                Videos = files.Items.Cast<string>().ToList(),
                Urls = parsed.Urls,
                Top = (int)top.Value,
                Streamer = streamer.SelectedIndex > 0 ? (string)streamer.SelectedItem : "",
                Memo = memo.Text.Trim(),
            };
            var errs = new List<string>(parsed.Errors);
            errs.AddRange(Sending.Check(input));
            if (errs.Count > 0)
            {
                SetStatus(string.Join("\n", errs.Take(8)) + (errs.Count > 8 ? "\nほか " + (errs.Count - 8) + " 件" : ""), true);
                return;
            }
            Config config;
            try { config = Config.Load(Path.Combine(exeDir, "config.json")); }
            catch (Exception ex) { SetStatus(ConfigProblem(ex), true); return; }

            cancel = false;
            SetBusy(true);
            bar.Value = 0;
            SetStatus("送る準備をしています…", false);
            Log.Write("send: videos=" + input.Videos.Count + " urls=" + input.Urls.Count);
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
                Ui(() => ShowProgress(input, p, permille));
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
                Ui(() => Finished(input, sending.Sent, error));
            });
            worker.IsBackground = true;
            worker.Start();
        }

        void ShowProgress(SendInput input, SendProgress p, int permille)
        {
            if (!Busy) return;
            bar.Value = permille;
            string size = input.Videos.Count > 0 ? "(" + Mb(p.Done) + " / " + Mb(p.Total) + ")" : "";
            SetStatus(p.Step + "… " + size, false);
        }

        void Finished(SendInput input, List<string> sent, string error)
        {
            SetBusy(false);
            if (error == null)
            {
                Log.Write("send: ok");
                bar.Value = 1000;
                SetStatus("送りました ✓", false, true);
                files.Items.Clear();
                urls.Clear();
                memo.Clear();
                streamer.SelectedIndex = 0;
                UpdateFileView();
                return;
            }
            Log.Write("send: failed: " + error);
            string msg = "送れませんでした: " + error;
            if (sent.Count > 0)
            {
                msg += "\n(" + string.Join("・", sent) + " は送れています。残りだけもう一度送ってください)";
                if (sent.Any(x => x.StartsWith("配信"))) urls.Clear();
            }
            SetStatus(msg, true);
        }

        void SetBusy(bool busy)
        {
            sendBtn.Enabled = !busy;
            sendBtn.Text = busy ? "送っています…" : "送る";
            addBtn.Enabled = !busy;
            removeBtn.Enabled = !busy && files.Items.Count > 0;
            urls.ReadOnly = busy;
            memo.ReadOnly = busy;
            streamer.Enabled = !busy && streamer.Items.Count > 1;
            top.Enabled = !busy;
            UseWaitCursor = false;
        }

        void SetStatus(string text, bool error, bool success = false)
        {
            status.Text = text;
            status.ForeColor = error ? Color.Firebrick : success ? Color.ForestGreen : SystemColors.ControlText;
            status.Font = success ? new Font(Font.FontFamily, 12f, FontStyle.Bold) : Font;
        }

        void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (!Busy) return;
            var ans = MessageBox.Show(this, "送っている途中です。やめて閉じますか?", AppInfo.Title, MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (ans != DialogResult.Yes) { e.Cancel = true; return; }
            cancel = true;
            Log.Write("send: canceled by closing");
        }

        void Ui(Action a)
        {
            if (IsDisposed) return;
            try { BeginInvoke(a); }
            catch (InvalidOperationException) { }
        }

        static string Mb(long bytes)
        {
            return bytes >= 1024L * 1024 * 1024 ? (bytes / (1024.0 * 1024 * 1024)).ToString("0.00") + "GB" : (bytes / (1024.0 * 1024)).ToString("0") + "MB";
        }
    }
}
