// まとめ動画(2.7.0): 届いたら裏で先に取ってきておき(PreviewQueue)、アプリの小窓で再生する(PreviewForm)。
//   取る順番 … 一覧を調べたときに、まとめ動画のあるパックを一覧の順に並べる。「まとめ動画を見る」を押したものは先頭へ。
//              大きすぎるもの(AutoMaxBytes 超)は押したときだけ。失敗したものは押したときにもう一度。一覧から消えたものは取らない
//   小窓     … Windows にはじめから入っている WPF の MediaElement を ElementHost で埋め込む(.NET Framework 4 に同梱。追加のインストールは要らない)。
//              再生・一時停止・つまみで移動・Space / ← → / Esc。[受け取る] [要らない] [外部のプレイヤーで開く]。
//              再生できない PC(Windows の N エディションで Media Feature Pack が無いなど)は MediaFailed で知らせ、外部のプレイヤーで開ける
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

        // 一覧を調べ直したとき: まとめ動画のあるパックを一覧の順に並べ直す(済み・失敗の印は残す。一覧に無いものは消えた扱い)
        public void Reset(IEnumerable<OutputEntry> entries)
        {
            lock (gate)
            {
                var keep = entries.Where(e => e != null && e.Kind == OutputKind.Pack && e.Preview != null).ToList();
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

    public enum PreviewChoice { None, Receive, Discard }

    // まとめ動画を再生する小窓。閉じたあと Choice を見て、受け取る・要らないを続ける
    public sealed class PreviewForm : Form, IThemed
    {
        readonly ElementHost host = new ElementHost();
        readonly System.Windows.Controls.MediaElement media = new System.Windows.Controls.MediaElement();
        readonly Btn playBtn = new Btn("一時停止", BtnKind.Normal), receiveBtn = new Btn("受け取る", BtnKind.Primary), discardBtn = new Btn("要らない", BtnKind.Normal),
                     externalBtn = new Btn("外部のプレイヤーで開く", BtnKind.Ghost);
        readonly TrackBar seek = new TrackBar();
        readonly Lbl title = new Lbl("", Tone.Text), timeLbl = new Lbl("0:00 / 0:00", Tone.Muted), note = new Lbl("", Tone.Muted);
        readonly Timer tick = new Timer { Interval = 250 };
        readonly string path;
        bool playing, seeking, opened;
        double durationSec;

        public PreviewChoice Choice { get; private set; }
        // 確かめ用(--probe-preview): 開けたか・長さ・いまの位置・失敗の理由
        public bool Opened { get { return opened; } }
        public double Duration { get { return durationSec; } }
        public double PositionSec { get { return opened ? media.Position.TotalSeconds : 0; } }
        public string Error { get; private set; }

        public PreviewForm(string path, string titleText)
        {
            this.path = path;
            Text = "まとめ動画 - " + titleText;
            Font = Theme.Body;
            KeyPreview = true;
            StartPosition = FormStartPosition.CenterParent;
            MinimumSize = new Size(Ui.S(560), Ui.S(420));
            ClientSize = new Size(Ui.S(900), Ui.S(600));
            ShowInTaskbar = false;

            title.Text = titleText;
            title.Font = Theme.Bold;
            title.AutoSize = false;
            title.AutoEllipsis = true;
            note.Font = Theme.Small;
            note.AutoSize = false;
            note.AutoEllipsis = true;
            note.Text = "等速・各クリップの左上に「何本目 / 題」。Space で再生 / 一時停止、← → で 5 秒戻る / 進む、Esc で閉じる";
            timeLbl.Font = Theme.MonoSmall;
            timeLbl.AutoSize = false;
            timeLbl.TextAlign = ContentAlignment.MiddleRight;

            media.LoadedBehavior = System.Windows.Controls.MediaState.Manual;
            media.UnloadedBehavior = System.Windows.Controls.MediaState.Close;
            media.Stretch = System.Windows.Media.Stretch.Uniform;
            media.Volume = 0.8;
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

            receiveBtn.Font = Theme.Big;   // 本体の「受け取る」と同じ(大きさも 150 × 40)
            playBtn.Enabled = false;
            playBtn.Click += (s, e) => TogglePlay();
            receiveBtn.Click += (s, e) => { Choice = PreviewChoice.Receive; Close(); };
            discardBtn.Click += (s, e) => { Choice = PreviewChoice.Discard; Close(); };
            externalBtn.Click += (s, e) => OpenExternal();
            tick.Tick += (s, e) => UpdatePosition();

            Controls.AddRange(new Control[] { title, host, seek, timeLbl, playBtn, receiveBtn, discardBtn, externalBtn, note });
            foreach (var b in new[] { playBtn, discardBtn, externalBtn }) b.FitWidth();
            Resize += (s, e) => LayoutParts();
            HandleCreated += (s, e) => Theme.TitleBar(this);
            Load += (s, e) => { ApplyTheme(); Theme.Apply(this); LayoutParts(); Start(); };
            FormClosing += (s, e) => Stop();
        }

        public void ApplyTheme()
        {
            BackColor = Theme.P.Bg;
            seek.BackColor = Theme.P.Bg;
        }

        void LayoutParts()
        {
            int m = Ui.S(12), w = ClientSize.Width - m * 2, h = ClientSize.Height;
            if (w <= 0) return;
            title.SetBounds(m, m, w, Ui.S(22));
            int foot = Ui.S(126);
            host.SetBounds(m, m + Ui.S(28), w, Math.Max(Ui.S(120), h - m - Ui.S(28) - foot));
            int y = host.Bottom + Ui.S(6);
            timeLbl.SetBounds(m + w - Ui.S(120), y, Ui.S(120), Ui.S(28));
            seek.SetBounds(m, y, w - Ui.S(128), Ui.S(28));
            y += Ui.S(40);
            playBtn.SetBounds(m, y + Ui.S(2), Math.Max(playBtn.Width, Ui.S(110)), Ui.S(36));
            externalBtn.Location = new Point(playBtn.Right + Ui.S(8), y + Ui.S(6));
            discardBtn.Location = new Point(m + w - discardBtn.Width, y + Ui.S(6));
            receiveBtn.SetBounds(discardBtn.Left - Ui.S(8) - Ui.S(150), y, Ui.S(150), Ui.S(40));
            y += Ui.S(48);
            note.SetBounds(m, y, w, Ui.S(20));
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
            if (keyData == Keys.Space && !(ActiveControl is Button)) { TogglePlay(); return true; }
            if (keyData == Keys.Left) { Jump(-5); return true; }
            if (keyData == Keys.Right) { Jump(5); return true; }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { tick.Dispose(); host.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
