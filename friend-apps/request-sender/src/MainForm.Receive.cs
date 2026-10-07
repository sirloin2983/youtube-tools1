// 画面のタブ「受け取る」: 「① 全自動」で送った依頼のパック(.zip)と、失敗の知らせ(.失敗.txt)。一覧は Dropbox の「/出力」。
//   受け取る         … 選んだパック 1 本(ダブルクリックでも)。大きさと hash を確かめ、保存先に展開して(settings.json の extractZip が false なら zip のまま)、Dropbox と一覧から消す
//   すべて受け取る   … 届いているパックを古い順に 1 本ずつ同じように(1 つの依頼で何本もできたときに、1 本ずつ押さなくて済むように)
//   やめる           … 取ってきている途中だけ出る。途中のファイルは消し、受け取り終えたものは Dropbox から消し終える
//   まとめ動画を見る … パックの隣のまとめ動画(等速・各クリップに札の確認用)を %TEMP%\RequestSender\previews に取ってきて、既定のプレイヤーで開く。受け取った・要らないにしたら写しは消す
//   要らない / 消す  … 1 つのボタン。パックなら記録(<zip>.feedback.json)を受付のフォルダに置いてから受け取らずに Dropbox から消す(まとめ動画も。記録が置けなくても消す。2.6.0)、
//                     失敗の知らせなら読み終えたあとに消す
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
        readonly Lbl recvHint = new Lbl("「① 全自動」で送ったものは、できあがるとここに届きます(何本かまとめて 1 つに)。「まとめ動画を見る」で中身を先に見て、「受け取る」(保存先にフォルダとして展開)か「要らない」を決めます。", Tone.Muted);
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
        bool recvDownloading;   // 取ってきている途中(受け取る・すべて受け取る・まとめ動画)= 「やめる」を出す
        bool recvAll;           // そのうち「すべて受け取る」の途中
        bool RecvBusy { get { return recvRunning; } }

        void BuildReceiveLayout()
        {
            refreshBtn.Click += (s, e) => RefreshList();
            recvHint.Font = Theme.Small;
            recvHint.AutoSize = false;

            outList.AccessibleName = "届いたものの一覧";
            outList.Texts = e => new[] { e.Kind == OutputKind.Pack ? "パック" : "失敗", e.Title, e.Kind == OutputKind.Pack ? SizeText(e.Size) : "", When(e.Modified) };
            outList.SelectedIndexChanged += (s, e) => ShowSelected();
            outList.DoubleClick += (s, e) => { if (IsPack(SelectedEntry)) StartDownload(); };
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
            receiveBtn.SetBounds(m, y, Ui.S(150), Ui.S(40));
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

        static bool HasPreview(OutputEntry e)
        {
            return IsPack(e) && e.Preview != null;
        }

        // 「要らない / 消す」を押せるもの: パック(受け取らずに消す)か、理由を読み終えた失敗の知らせ
        bool CanDelete(OutputEntry e)
        {
            return IsPack(e) || (e != null && e.Kind == OutputKind.Failure && failureTexts.ContainsKey(e.Key));
        }

        // 「要らない / 消す」のボタンの文字(確認の窓の題にも使う)
        static string DeleteLabel(OutputEntry e)
        {
            return IsPack(e) ? "要らない" : "消す";
        }

        void UpdateRecvButtons()
        {
            var e = SelectedEntry;
            bool busy = RecvBusy;
            int packs = PackCount;
            refreshBtn.Enabled = !busy;
            changeDirBtn.Enabled = !busy;
            receiveBtn.Enabled = !busy && IsPack(e);
            receiveBtn.Text = busy && recvDownloading && !recvAll ? "受け取っています…" : "受け取る";
            receiveAllBtn.Enabled = !busy && packs > 0;
            receiveAllBtn.Text = busy && recvAll ? "すべて受け取っています…" : packs > 1 ? "すべて受け取る(" + packs + " 本)" : "すべて受け取る";
            receiveAllBtn.FitWidth();
            previewBtn.Enabled = !busy && HasPreview(e);
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
            SetArrived(entries.Count, false);
            int packs = PackCount, fails = entries.Count - packs;
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
                              "大きさ: " + SizeText(e.Size) + "\r\n届いた日時: " + When(e.Modified) + "\r\n" +
                              "まとめ動画: " + (e.Preview != null ? "あり(" + SizeText(e.Preview.Size) + "。「まとめ動画を見る」で中身を確かめられます)" : "なし") + "\r\n\r\n" +
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

        void ShowFailure(OutputEntry e, string reason)
        {
            detail.Text = "自動の処理が失敗しました(" + e.Title + ")。\r\n送り先の人に伝えるか、「② 軽く確認」か「③ 全部人が行う」で送り直してください。\r\n読み終えたら「消す」を押すと、一覧から消えます。\r\n\r\n理由:\r\n" + reason;
        }

        // ---- 受け取る ----
        // 選んだパック 1 本(Receiving.ReceiveOne: 受け取って確かめ → 展開 → Dropbox から消す)
        void StartDownload()
        {
            var e = SelectedEntry;
            if (RecvBusy || !IsPack(e)) return;
            string dir = downloadDir;
            var receiving = BeginFetch("受け取る準備をしています…", false);
            if (receiving == null) return;
            Log.Write("receive: " + e.Name + " size=" + e.Size);
            var show = FileProgress();
            RunRecv(() =>
            {
                var got = receiving.ReceiveOne(e, dir, show);
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
            if (RecvBusy) return;
            var packs = OutputFolder.PacksOldestFirst(entries);
            if (packs.Count == 0) return;
            long total = OutputFolder.TotalSize(packs);
            if (MessageBox.Show(this, "届いているパック " + packs.Count + " 本(合計 " + Mb(total) + ")をすべて受け取ります。\n保存先: " + downloadDir +
                    "\n\n古い順に 1 本ずつ受け取って保存先にフォルダとして展開し、ちゃんと保存できたものから Dropbox と一覧から消えます。途中で「やめる」を押せます。",
                    "すべて受け取る", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
            string dir = downloadDir;
            var receiving = BeginFetch("受け取る準備をしています…(" + packs.Count + " 本)", true);
            if (receiving == null) return;
            Log.Write("receive all: " + packs.Count + " packs, " + total + " bytes");
            var gate = new ProgressGate();
            RunRecv(() =>
            {
                var r = receiving.DownloadAll(packs, dir, (no, e, done, all, step) =>
                {
                    int permille;
                    if (gate.Changed(done, all, no + "|" + step, out permille))
                        ShowRecvProgress(permille, step + "(" + no + " / " + packs.Count + " 本目: " + e.Title + ")… (全体 " + Mb(done) + " / " + Mb(all) + ")");
                });
                Log.Write("receive all: " + r.Received + "/" + r.Total + (r.Canceled ? " canceled" : "") + (r.Error != null ? " stopped: " + r.Error.Message : "") +
                          (r.Failed.Count > 0 ? " skipped " + r.Failed.Count : "") + (r.Kept.Count > 0 ? " not deleted " + r.Kept.Count : ""));
                OnUi(() => FinishDownloadAll(r));
            });
        }

        void FinishDownloadAll(ReceiveAllResult r)
        {
            if (r.LastPath != null) lastDownloaded = r.LastPath;
            foreach (var x in r.Done) Receiving.ForgetPreview(x);
            RemoveEntries(r.Done);
            if (r.Clean) recvBar.Value = 1000;
            SetRecvStatus(r.Summary(r.Error != null ? RecvError(r.Error) : null), r.HasProblem, r.Clean);
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

        // 画面の確認(--tab receive --state receiving): 「すべて受け取る」の途中の見た目(通信しない)
        public void ShowReceivingSample()
        {
            recvRunning = recvDownloading = recvAll = true;
            recvBar.Value = 335;
            SetRecvStatus("受け取っています(2 / 5 本目: 見本の切り抜き_03)… (全体 2.51GB / 7.50GB)", false);
            UpdateRecvButtons();
        }

        // まとめ動画(zip の隣の小さい mp4)を取ってきて、既定のプレイヤーで開く(等速の確認用。受け取る前に中身を見る)
        void StartPreview()
        {
            var e = SelectedEntry;
            if (RecvBusy || !HasPreview(e)) return;
            var receiving = BeginFetch("まとめ動画を取ってきています…", false);
            if (receiving == null) return;
            Log.Write("preview: " + e.Preview.Name + " size=" + e.Preview.Size);
            var show = FileProgress();
            RunRecv(() =>
            {
                string path = receiving.DownloadPreview(e, Receiving.PreviewDir(), show);
                OnUi(() =>
                {
                    recvBar.Value = 1000;
                    try
                    {
                        Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
                        SetRecvStatus("まとめ動画を開きました。要るなら「受け取る」、要らなければ「要らない」を押してください。", false);
                    }
                    catch (Exception ex)
                    {
                        SetRecvStatus("まとめ動画を開けませんでした: " + ex.Message + "(" + path + ")", true);
                    }
                });
            });
        }

        // 失敗の知らせ(読み終えた)か、要らないパック(受け取らずに)を Dropbox から消す
        void StartDelete()
        {
            var e = SelectedEntry;
            if (RecvBusy || !CanDelete(e)) return;
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
                if (pack) { recorded = receiving.Discard(e, DateTimeOffset.Now); Receiving.ForgetPreview(e); }   // 記録を置いてから消す(置けなくても消す。2.6.0)
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
