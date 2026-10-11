// この PC で処理するときの進み具合・閉じるときの 3 択・処理する PC の切り替え(F1 の F3a。設計 docs/design/f1-build.md の 2 の F3a・plan/f1-friend-pc.md の決めたこと 3・5)。
//   進み具合: ② の GET /api/flow/status を、動いている物があれば 2 秒・無ければ 15 秒ごとに聞く(rev が前と同じなら描き直さない)。上の帯に 1 行・blocked(空き容量)は赤い文
//   × の 3 択(自分が起こした ② が待ち・実行中・録画中のとき): [終わったら閉じる](既定。最小化してタスクバーのボタンに進み具合・idle になったら自分で終わる)/
//                                                             [今すぐ止めて閉じる](② を止める = 次に開いたとき続きから)/ [やめる]
//   処理する PC: 依頼ごとに「この PC」(既定)/「送り先の人の PC」(今までの Dropbox の道)。この PC で処理できない形(Python が無い)なら切り替えを出さず Dropbox だけ
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using FriendApps;

namespace RequestSender
{
    // ---- ② の GET /api/flow/status の読み(docs/spec/pipeline.md 2.8・2.9。知らない項目は無視)----
    public class FlowRun
    {
        public string Id = "", Title = "", State = "", StateLabel = "", Step = "", Message = "";
        public int StepsDone, StepsTotal;

        public bool Active { get { return State == "queued" || State == "running"; } }

        // 0〜1(待ち = 0・終わった = 1・実行中 = 済んだ段 / 段の数)
        public double Fraction
        {
            get
            {
                if (State == "queued") return 0;
                if (!Active) return 1;
                return StepsTotal > 0 ? Math.Min(1.0, (double)StepsDone / StepsTotal) : 0;
            }
        }
    }

    public class FlowStatus
    {
        static readonly string[] StepDone = { "done", "skip", "warn", "error" };

        public int Queued, Running, Done, Recording, Detecting, Exporting;
        public bool Idle = true;
        public long Rev = -1;                // 無い(古い ②)= -1 = 毎回描く
        public string BlockedReason;         // null = 止めていない。"disk" = 空き容量の下限(f1-build.md 1-2)
        public double FreeGB = -1, MinGB = -1;
        public string GpuName;
        public List<FlowRun> Runs = new List<FlowRun>();

        public bool Live { get { return Recording + Detecting + Exporting > 0; } }

        public static FlowStatus Parse(IDictionary<string, object> d)
        {
            var s = new FlowStatus
            {
                Queued = Json.Int(d, "queued", 0),
                Running = Json.Int(d, "running", 0),
                Done = Json.Int(d, "done", 0),
                Idle = Json.Bool(d, "idle", true),
                Rev = Json.Long(d, "rev", -1),
            };
            var live = Json.Dict(d, "live");
            s.Recording = Json.Int(live, "recording", 0);
            s.Detecting = Json.Int(live, "detecting", 0);
            s.Exporting = Json.Int(live, "exporting", 0);
            var b = Json.Dict(d, "blocked");
            if (b != null)
            {
                s.BlockedReason = Json.Str(b, "reason") ?? "";
                s.FreeGB = Num(b, "freeGB");
                s.MinGB = Num(b, "minGB");
            }
            var gpu = Json.Dict(Json.Dict(d, "machine"), "gpu");
            s.GpuName = Json.Str(gpu, "name");
            foreach (var r in Json.List(d, "runs"))
            {
                var steps = Json.List(r, "steps").ToList();
                s.Runs.Add(new FlowRun
                {
                    Id = Json.Str(r, "id") ?? "",
                    Title = Json.Str(r, "title") ?? "",
                    State = Json.Str(r, "state") ?? "",
                    StateLabel = Json.Str(r, "stateLabel") ?? "",
                    Step = StepText(r, steps),
                    Message = Json.Str(r, "message") ?? "",
                    StepsTotal = steps.Count,
                    StepsDone = steps.Count(x => StepDone.Contains(Json.Str(x, "state") ?? "")),
                });
            }
            return s;
        }

        // 実行中の段の名前(step が文字ならそれ・無ければ steps の state run の label)
        static string StepText(IDictionary<string, object> r, List<IDictionary<string, object>> steps)
        {
            string st = Json.Str(r, "step");
            var cur = steps.FirstOrDefault(x => Json.Str(x, "state") == "run");
            string label = cur != null ? Json.Str(cur, "label") : null;
            return label ?? st ?? "";
        }

        static double Num(IDictionary<string, object> d, string key)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v == null) return -1;
            if (v is int) return (int)v;
            if (v is long) return (long)v;
            if (v is decimal) return (double)(decimal)v;
            if (v is double) return (double)v;
            return -1;
        }

        public bool Blocked { get { return BlockedReason != null; } }

        // 全体の進み具合 0〜1(この起動の実行の平均。実行が無ければ 0)
        public double Fraction()
        {
            return Runs.Count == 0 ? 0 : Runs.Sum(r => r.Fraction) / Runs.Count;
        }

        // 上の帯の 1 行
        public string Line()
        {
            var parts = new List<string>();
            if (Blocked)
                return BlockedReason == "disk" && FreeGB >= 0 && MinGB >= 0
                    ? "⚠ 空きが " + Gb(FreeGB) + " GB。" + Gb(MinGB) + " GB を切ったので新しい処理を始めていません"
                    : "⚠ 新しい処理を始めていません(" + BlockedReason + ")";
            var cur = Runs.FirstOrDefault(r => r.State == "running");
            if (cur != null) parts.Add("処理中: " + Validation.Shorten(cur.Title, 24) + (cur.Step.Length > 0 ? "(" + cur.Step + ")" : ""));
            else if (Running > 0) parts.Add("処理中 " + Running + " 本");
            if (Queued > 0) parts.Add("待ち " + Queued + " 本");
            if (Recording > 0) parts.Add("録画中 " + Recording);
            else if (Live) parts.Add("ライブ配信の処理中");
            if (parts.Count == 0) return Done > 0 ? "この PC: 済み " + Done + " 本(待ちなし)" : "この PC: 待ちなし";
            return "この PC: " + string.Join(" ・ ", parts);
        }

        static string Gb(double v)
        {
            return v.ToString(v < 10 ? "0.0" : "0", CultureInfo.InvariantCulture);
        }
    }

    // ---- × を押したとき ----
    public enum CloseAnswer { WhenDone, Now, Cancel }

    public static class CloseChoice
    {
        // 3 択を出すか: 自分が起こした ② があり、待ち・実行中・録画中(idle でない)
        public static bool Needed(bool owned, FlowStatus last)
        {
            return owned && last != null && !last.Idle;
        }

        // 問い合わせの間隔(ミリ秒): 動いている物があれば 2 秒・無ければ 15 秒
        public static int PollMs(FlowStatus last)
        {
            return last != null && !last.Idle ? 2000 : 15000;
        }
    }

    // 3 択の小窓(既定 = [終わったら閉じる]。Esc = やめる)
    public class CloseAsk : Form
    {
        public CloseAnswer Answer = CloseAnswer.Cancel;

        public CloseAsk(FlowStatus s)
        {
            Text = AppInfo.Title;
            Font = Theme.Body;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;
            BackColor = Theme.P.Bg;
            ForeColor = Theme.P.Text;
            int m = Ui.S(16);
            var msg = new Lbl("この PC で処理している途中です(" + (s != null ? s.Line().Replace("この PC: ", "") : "") + ")。\nどうしますか?", Tone.Text);
            msg.Wrap(Ui.S(460));
            msg.Location = new Point(m, m);
            var whenDone = new Btn("終わったら閉じる", BtnKind.Primary);
            var now = new Btn("今すぐ止めて閉じる", BtnKind.Normal);
            var cancel = new Btn("やめる", BtnKind.Normal);
            var note = new Lbl("終わったら閉じる = 窓を小さくしてタスクバーに残し、済んだら自分で閉じます。\n今すぐ止めて閉じる = 次に開いたとき、続きから処理します。", Tone.Muted) { Font = Theme.Small };
            note.Wrap(Ui.S(460));
            int y = msg.Bottom + m;
            whenDone.SetBounds(m, y, Ui.S(170), Ui.S(36));
            now.SetBounds(whenDone.Right + Ui.S(8), y, Ui.S(170), Ui.S(36));
            cancel.SetBounds(now.Right + Ui.S(8), y, Ui.S(100), Ui.S(36));
            note.Location = new Point(m, whenDone.Bottom + Ui.S(10));
            whenDone.Click += (o, e) => Done(CloseAnswer.WhenDone);
            now.Click += (o, e) => Done(CloseAnswer.Now);
            cancel.Click += (o, e) => Done(CloseAnswer.Cancel);
            Controls.AddRange(new Control[] { msg, whenDone, now, cancel, note });
            ClientSize = new Size(Math.Max(cancel.Right, Math.Max(msg.Right, note.Right)) + m, note.Bottom + m);
            AcceptButton = whenDone;
            CancelButton = cancel;
            Theme.Apply(this);
            Shown += (o, e) => whenDone.Focus();
        }

        void Done(CloseAnswer a)
        {
            Answer = a;
            DialogResult = a == CloseAnswer.Cancel ? DialogResult.Cancel : DialogResult.OK;
            Close();
        }

        public static CloseAnswer Ask(IWin32Window owner, FlowStatus s)
        {
            using (var f = new CloseAsk(s))
            {
                f.ShowDialog(owner);
                return f.Answer;
            }
        }
    }

    // ---- タスクバーのボタンの進み具合(ITaskbarList3。使えなければ何もしない)----
    public static class TaskbarProgress
    {
        [ComImport, Guid("ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface ITaskbarList3
        {
            void HrInit();
            void AddTab(IntPtr hwnd);
            void DeleteTab(IntPtr hwnd);
            void ActivateTab(IntPtr hwnd);
            void SetActiveAlt(IntPtr hwnd);
            void MarkFullscreenWindow(IntPtr hwnd, [MarshalAs(UnmanagedType.Bool)] bool fullscreen);
            void SetProgressValue(IntPtr hwnd, ulong completed, ulong total);
            void SetProgressState(IntPtr hwnd, int state);
        }

        [ComImport, Guid("56FDF344-FD6D-11d0-958A-006097C9A090"), ClassInterface(ClassInterfaceType.None)]
        class TaskbarList { }

        const int NoProgress = 0, Indeterminate = 1, Normal = 2, Error = 4;
        static ITaskbarList3 list;
        static bool broken;

        static ITaskbarList3 Get()
        {
            if (list != null || broken) return list;
            try { list = (ITaskbarList3)new TaskbarList(); list.HrInit(); }
            catch (Exception) { broken = true; list = null; }
            return list;
        }

        // fraction: 0〜1・負 = 分からない(流れる帯)・null = 消す。error = 赤
        public static void Set(Form f, double? fraction, bool error)
        {
            if (f == null || !f.IsHandleCreated) return;
            var t = Get();
            if (t == null) return;
            try
            {
                if (fraction == null) { t.SetProgressState(f.Handle, NoProgress); return; }
                if (fraction < 0) { t.SetProgressState(f.Handle, Indeterminate); return; }
                t.SetProgressState(f.Handle, error ? Error : Normal);
                t.SetProgressValue(f.Handle, (ulong)Math.Round(Math.Max(0, Math.Min(1, fraction.Value)) * 1000), 1000);
            }
            catch (Exception) { broken = true; list = null; }
        }
    }

    // ---- 画面の側(MainForm の続き)----
    public partial class MainForm
    {
        enum PcTarget { Self, Remote }

        Backend backend;                    // null = この PC では処理しない(Python・src が無い)= 今までどおり Dropbox だけ
        FriendDefaults friendDefaults = new FriendDefaults();
        FlowStatus flow;                    // 最後に読んだ ② の状態(null = まだ)
        long flowRev = long.MinValue;
        bool flowPolling, closeWhenIdle, reallyClose;
        PcTarget pcTarget = PcTarget.Self;
        readonly System.Windows.Forms.Timer flowTimer = new System.Windows.Forms.Timer();
        readonly Lbl flowLbl = new Lbl("", Tone.Muted);
        readonly HRow pcRow = new HRow();
        readonly Lbl lPc = new Lbl("処理する PC", Tone.Text), pcHint = new Lbl("", Tone.Muted);
        readonly Btn pcSelf = new Btn("この PC", BtnKind.Toggle), pcRemote = new Btn("送り先の人の PC", BtnKind.Toggle);

        bool UseLocal { get { return backend != null && pcTarget == PcTarget.Self; } }

        // 組み立て(コンストラクタから。テスト・画面の確認 Offline では起こさない)
        void InitBackend()
        {
            flowLbl.Font = Theme.Small;
            flowLbl.AutoSize = false;
            flowLbl.AutoEllipsis = true;
            flowLbl.TextAlign = ContentAlignment.MiddleLeft;
            topBar.Controls.Add(flowLbl);
            flowTimer.Tick += (s, e) => PollFlow();
            if (Offline) return;
            var paths = BackendPaths.Locate(exeDir);
            if (paths == null) { Log.Write("backend: python or src not found (Dropbox only)"); return; }
            backend = new Backend(paths, null) { Log = Log.Write };
            friendDefaults = FriendDefaults.Load(Path.Combine(exeDir, FriendDefaults.FileName));
            if (friendDefaults.Problem != null) Log.Write("friend-defaults: " + friendDefaults.Problem);
        }

        // 右の列: 03 の下・メモの上に「処理する PC」(切り替えられないときは出さない)
        void BuildPcRow()
        {
            lPc.AutoSize = false;
            lPc.Size = new Size(Ui.S(112), Ui.S(20));
            lPc.TextAlign = ContentAlignment.MiddleLeft;
            pcSelf.Click += (s, e) => SetPcTarget(PcTarget.Self);
            pcRemote.Click += (s, e) => SetPcTarget(PcTarget.Remote);
            pcSelf.AccessibleName = "この PC で処理する";
            pcRemote.AccessibleName = "送り先の人の PC に Dropbox で頼む";
            pcRow.Add(lPc, 0).Add(pcSelf, 0).Add(pcRemote, 4);
            pcHint.Font = Theme.Small;
            int at = right.IndexOf(lMemo);
            right.Insert(at, pcRow, 14, false);
            right.Insert(at + 1, pcHint, 2, true);
            SetPcTarget(PcTarget.Self);
        }

        void SetPcTarget(PcTarget t)
        {
            if (Busy) return;
            pcTarget = t;
            pcSelf.On = t == PcTarget.Self;
            pcRemote.On = t == PcTarget.Remote;
            UpdatePcHint();
            UpdateAll();
        }

        void UpdatePcHint()
        {
            bool shown = backend != null;
            right.SetShown(pcRow, shown);
            right.SetShown(pcHint, shown);
            if (!shown) { right.Arrange(); return; }
            if (pcTarget == PcTarget.Remote) pcHint.Text = "送り先の人の PC に Dropbox で頼みます(今までの送り方。できあがると「受け取る」に届きます)。";
            else if (flow != null && !flow.Idle) pcHint.Text = "この PC で処理中の依頼があります。急ぐときは「送り先の人の PC」に頼むこともできます。";
            else pcHint.Text = "この PC で文字起こし・パックまで作ります(動画は送りません)。";
            pcHint.Tone = pcTarget == PcTarget.Self && flow != null && !flow.Idle ? Tone.Accent : Tone.Muted;
            right.Arrange();
        }

        // 開いたとき: ② を裏で起こす(前の起動で待っていた依頼もここで続きから流れる)
        void StartBackendAsync()
        {
            if (backend == null || Offline) return;
            SetFlowLine("この PC の処理の部品を起こしています…", Tone.Muted);
            var t = new Thread(() =>
            {
                string error = null;
                try { backend.EnsureStarted(); }
                catch (BackendException ex) { error = ex.Message; }
                OnUi(() =>
                {
                    if (error != null) { SetFlowLine("⚠ " + error, Tone.Error); Log.Write("backend: " + error); return; }
                    SetFlowLine(backend.Owned ? "" : "この PC で動いている処理の入口に頼みます", Tone.Muted);
                    PollFlow();
                });
            }) { IsBackground = true, Name = "backend-start" };
            t.Start();
        }

        void PollFlow()
        {
            if (backend != null && closeWhenIdle && !backend.Running && !IsDisposed)   // 待っている間に ② が終わった(落ちた)= 待つ物が無い
            {
                reallyClose = true;
                Close();
                return;
            }
            if (backend == null || flowPolling || IsDisposed || !backend.Running) { ScheduleFlow(); return; }
            flowPolling = true;
            var t = new Thread(() =>
            {
                FlowStatus s = null;
                try
                {
                    var r = backend.Get("/api/flow/status");
                    if (r.Ok) s = FlowStatus.Parse(r.Body);
                }
                catch (Exception ex) { Log.Write("flow status: " + ex.Message); }
                OnUi(() => { flowPolling = false; if (s != null) ShowFlow(s); ScheduleFlow(); });
            }) { IsBackground = true, Name = "flow-status" };
            t.Start();
        }

        void ScheduleFlow()
        {
            if (IsDisposed || backend == null) return;
            flowTimer.Stop();
            flowTimer.Interval = CloseChoice.PollMs(flow);
            flowTimer.Start();
        }

        void ShowFlow(FlowStatus s)
        {
            bool wasBusy = flow != null && !flow.Idle;
            flow = s;
            if (s.Rev < 0 || s.Rev != flowRev || wasBusy != !s.Idle)
            {
                flowRev = s.Rev;
                bool missing = !s.Blocked && Setup.MissingCount > 0;   // 初回の取得が終わっていない理由(F4b)は、空き容量の止めの次に大事
                SetFlowLine(missing ? "⚠ " + Setup.MissingReason() : s.Line(), s.Blocked || missing ? Tone.Error : Tone.Muted);
                UpdatePcHint();
                TaskbarProgress.Set(this, s.Idle ? (double?)null : s.Fraction(), s.Blocked);
                if (closeWhenIdle) Text = AppInfo.Title + "(処理中 " + (int)Math.Round(s.Fraction() * 100) + "%・済んだら閉じます)";
            }
            LocalOnFlow(s);   // 終わった数が変わったら、この PC のパックを「受け取る」の一覧に読み直す(LocalPacks.cs)
            if (closeWhenIdle && s.Idle)
            {
                Log.Write("backend: idle, closing");
                reallyClose = true;
                Close();
            }
        }

        void SetFlowLine(string text, Tone tone)
        {
            flowLbl.Text = text ?? "";
            flowLbl.Tone = tone;
            tips.SetToolTip(flowLbl, flowLbl.Text);
            LayoutAll();
        }

        // 上の帯: タブの右から配色の札の左まで(出す文があるときは版の表示を隠す)
        void LayoutFlowLine(int top, int m)
        {
            int left = tabRecv.Right + m;
            int right_ = (flowLbl.Text.Length > 0 ? settingsBtn.Left - Ui.S(16) : brand.Left - m);
            if (flowLbl.Text.Length > 0) brand.Visible = false;
            flowLbl.SetBounds(left, 0, Math.Max(0, right_ - left), top);
            flowLbl.Visible = flowLbl.Text.Length > 0 && flowLbl.Width > Ui.S(80);
        }

        // この PC で処理する(裏の糸で ② を起こしてから 1 件ずつ submit)
        void RunSendLocal(SendInput input)
        {
            cancel = false;
            SetBusy(true);
            bar.Value = 0;
            SetStatus("この PC の処理の部品を準備しています…", Tone.Muted);
            Log.Write("send(local): videos=" + input.Videos.Count + " urls=" + input.Items.Count + (input.Live != null ? " live" : ""));
            var sent = new List<string>();
            worker = new Thread(() =>
            {
                string error = null;
                try
                {
                    backend.EnsureStarted();
                    Sending.RunLocal(input, backend, friendDefaults, null, sent, step => OnUi(() => { if (Busy) SetStatus(step, Tone.Muted); }));
                }
                catch (BackendException ex) { error = ex.Message; }
                catch (Exception ex) { error = "思わぬエラーで処理に渡せませんでした: " + ex.Message; Log.Write("error: " + ex); }
                OnUi(() => FinishedLocal(sent, error));
            });
            worker.IsBackground = true;
            worker.Start();
        }

        void FinishedLocal(List<string> sent, string error)
        {
            worker = null;
            SetBusy(false);
            if (error == null)
            {
                Log.Write("send(local): ok " + sent.Count);
                bar.Value = 1000;
                SaveSettings();
                ClearInputs(true, true);
                justSent = true;
                SetStatus("この PC で処理を始めました(" + sent.Count + " 件)。進み具合は上に出ます。パックは案件のフォルダにできます。続けて送ることもできます", Tone.Muted);
                SetPcTarget(PcTarget.Self);   // 処理する PC は依頼ごと(次も既定の「この PC」から)
                PollFlow();
                return;
            }
            Log.Write("send(local): failed: " + error);
            bar.Value = 0;
            string msg = "この PC の処理に渡せませんでした: " + error;
            if (sent.Count > 0) msg += "(" + string.Join("・", sent) + " は受け付けました。残りを送るときは、それらを外してください)";
            else if (pcTarget == PcTarget.Self) msg += "。「送り先の人の PC」に頼むこともできます";
            SetStatus(msg, Tone.Error);
        }

        // × を押したとき: 自分の ② が動いていれば 3 択。-> 閉じるのを止めたか
        bool AskBeforeClose(FormClosingEventArgs e)
        {
            if (reallyClose || e.CloseReason != CloseReason.UserClosing) return false;
            if (!CloseChoice.Needed(backend != null && backend.Owned && backend.Running, flow)) return false;
            var ans = CloseAsk.Ask(this, flow);
            if (ans == CloseAnswer.Cancel) { e.Cancel = true; return true; }
            if (ans == CloseAnswer.WhenDone)
            {
                e.Cancel = true;
                closeWhenIdle = true;
                Log.Write("close: when done");
                WindowState = FormWindowState.Minimized;
                flowRev = long.MinValue;   // タスクバーと題名を描き直す
                PollFlow();
                return true;
            }
            Log.Write("close: now");
            return false;
        }

        // 最小化から戻した = 「終わったら閉じる」をやめる(使い続ける)
        void OnRestoredFromWait()
        {
            if (!closeWhenIdle || WindowState == FormWindowState.Minimized) return;
            closeWhenIdle = false;
            UpdateRecvTab();   // 題名を戻す
            SetStatus("「終わったら閉じる」をやめました(このまま使えます)", Tone.Muted);
        }

        // 閉じる直前: 自分が起こした ② を止める(窓は先に隠す)
        void StopBackend()
        {
            flowTimer.Stop();
            if (backend == null) return;
            try { TaskbarProgress.Set(this, null, false); } catch (Exception) { }
            Hide();
            try { backend.Stop(); }
            catch (Exception ex) { Log.Write("backend stop: " + ex.Message); }
        }
    }
}
