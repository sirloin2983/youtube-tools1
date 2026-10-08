// 配信のカード(2.0.0): URL・題名・切り抜く数・区間の行(開始〜終了)。区間が切り抜く数に足りない分は PC が自動の見どころで埋める。
// 設計: docs/spec/friend-intake.md の 2-10 の「配信のカード」「切り抜く数と区間」
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using FriendApps;

namespace RequestSender
{
    // ---- 区間の行: 開始 〜 終了・長さ・×。誤りはその場で行の下に出す ----
    public class RangeRow : Pane
    {
        public readonly TimeBox Start = new TimeBox("開始の時刻"), End = new TimeBox("終了の時刻");
        readonly Field startField, endField;
        readonly Lbl lStart = new Lbl("開始", Tone.Muted), lEnd = new Lbl("〜 終了", Tone.Muted), length = new Lbl("長さ —", Tone.Muted), problem = new Lbl("", Tone.Error);
        readonly Btn remove = new Btn("×", BtnKind.Ghost);
        readonly HRow row = new HRow();
        string pasteError;
        bool strict;                    // 送ろうとしたあと: 片方だけ入っている行も誤りとして出す

        public event Action Changed;            // 値・高さが変わった
        public event Action RemoveClicked;
        public event Action Activated;          // この行を触った(「+30秒」などの相手になる)
        public event Action<string> UrlPasted;  // YouTube の URL を貼った(URL の欄が空なら入れる)

        public RangeRow()
        {
            Inherit = true;
            startField = new Field(Start) { Width = Ui.S(100) };
            endField = new Field(End) { Width = Ui.S(100) };
            length.AutoSize = false;
            length.Size = new Size(Ui.S(112), Ui.S(20));
            length.TextAlign = ContentAlignment.MiddleLeft;
            remove.Size = new Size(Ui.S(26), Ui.S(26));
            remove.AccessibleName = "この区間を外す";
            Ui.Tip(remove, "この区間を外す");
            row.Add(lStart, 0).Add(startField, 6).Add(lEnd, 8).Add(endField, 6).Add(length, 10).Add(remove, 4);
            problem.Font = Theme.Small;
            problem.Visible = false;
            Controls.Add(row);
            Controls.Add(problem);
            foreach (var b in new[] { Start, End })
            {
                b.AcceptYouTubeUrl = true;   // 配信の時刻なので、YouTube の位置の URL も貼れる
                b.ValueChanged += () => { pasteError = null; Refresh_(); };
                b.PasteFailed += msg => { pasteError = msg; Refresh_(); };
                b.Pasted += text => { if (UrlPasted != null && YouTubeUrl.ExtractId(text) != null) UrlPasted(text); };
                b.Enter += (s, e) => { if (Activated != null) Activated(); };
            }
            Start.EnterPressed += () => End.Focus();
            remove.Click += (s, e) => { if (RemoveClicked != null) RemoveClicked(); };
            Refresh_();
        }

        public bool IsEmpty { get { return !Start.HasValue && !End.HasValue; } }

        public bool Strict
        {
            get { return strict; }
            set { if (strict != value) { strict = value; Refresh_(); } }
        }

        // いま出す誤り(無ければ null)。片方だけの行は、送ろうとしたあとだけ誤りにする(打っている途中で急かさない)
        public string Problem
        {
            get
            {
                if (!Enabled) return null;   // ③ のときなど、使わない間は誤りを出さない
                if (pasteError != null) return pasteError;
                string p = Ranges.Problem(Start.HasValue, Start.Value, End.HasValue, End.Value);
                if (p != null && !strict && !(Start.HasValue && End.HasValue)) return null;
                return p;
            }
        }

        // 送れる区間か(両方入っていて誤りなし)
        public bool TryGet(out ClipRange r)
        {
            r = new ClipRange(Start.Value, End.Value);
            return Start.HasValue && End.HasValue && Ranges.Problem(true, Start.Value, true, End.Value) == null;
        }

        // 「+30秒」など: 終了 = 開始 + 長さ
        public void SetLength(int seconds)
        {
            if (!Start.HasValue) { pasteError = "先に開始の時刻を入れてください"; Refresh_(); Start.Focus(); return; }
            End.SetValue(Start.Value + seconds);
        }

        public void Clear()
        {
            pasteError = null;
            Start.ClearValue();
            End.ClearValue();
            Refresh_();
        }

        // 誤りのある欄(フォーカスを移す先)
        public Control ProblemControl
        {
            get { return !Start.HasValue ? (Control)Start : End; }
        }

        void Refresh_()
        {
            bool both = Start.HasValue && End.HasValue;
            length.Text = both && End.Value > Start.Value ? "長さ " + TimeText.Length(End.Value - Start.Value) : "長さ —";
            string p = Problem;
            bool startBad = p != null && (!Start.HasValue || pasteError != null && Start.Focused);
            startField.Error = startBad;
            endField.Error = p != null && !startBad;
            problem.Text = p != null ? "⚠ " + p : "";
            problem.Visible = p != null;
            Arrange();
            if (Changed != null) Changed();
        }

        protected override void OnEnabledChanged(EventArgs e)
        {
            base.OnEnabledChanged(e);
            Refresh_();
        }

        void Arrange()
        {
            row.Arrange();
            row.Location = new Point(0, 0);
            int h = row.Height;
            if (problem.Visible)
            {
                problem.Location = new Point(lStart.Width + Ui.S(6), h + Ui.S(1));
                h += Ui.S(20);
            }
            Size = new Size(Math.Max(row.Width, Width), h);
        }
    }

    // ---- 配信のカード ----
    public class StreamCard : Pane
    {
        static readonly int[] QuickSeconds = { 30, 60, 180, 300 };
        static readonly string[] QuickLabels = { "+30秒", "+1分", "+3分", "+5分" };

        public readonly TextBox Url = new TextBox();
        readonly Field urlField;
        readonly Btn remove = new Btn("×", BtnKind.Ghost), addRange = new Btn("+ 区間を足す", BtnKind.Normal);
        readonly Lbl title = new Lbl("", Tone.Muted), lTop = new Lbl("切り抜く数", Tone.Muted), summary = new Lbl("", Tone.Accent), lQuick = new Lbl("終了を開始から", Tone.Muted);
        readonly Stepper top;
        readonly HRow topRow = new HRow(), toolRow = new HRow();
        readonly List<RangeRow> rows = new List<RangeRow>();
        readonly List<Btn> quick = new List<Btn>();
        RangeRow active;
        bool manual, leftUrl, strict;
        string titleId, titleText;
        bool titleFailed;

        public event Action Changed;                  // 要約・高さに関わる変化
        public event Action RemoveClicked;
        public event Action<string> IdChanged;        // 配信の ID が決まった(題名を問い合わせる)
        public event Action<string[]> MoreUrls;       // 何行も貼った: 2行目から後(カードを増やす)

        public StreamCard(int defaultTop)
        {
            Border = true;
            Url.MaxLength = 2048;
            Url.AccessibleName = "配信の URL";
            Url.HandleCreated += (s, e) => Ui.Cue(Url, "ここに YouTube の URL を貼る(Ctrl+V)");
            Url.AllowDrop = true;
            urlField = new Field(Url);
            remove.Size = new Size(Ui.S(26), Ui.S(26));
            remove.AccessibleName = "この配信を外す";
            Ui.Tip(remove, "この配信を外す");
            title.AutoSize = false;
            title.AutoEllipsis = true;
            title.AccentLead = "✓ ";   // 確かめられた題名の ✓ だけアクセントの色
            title.Font = Theme.Small;
            title.Height = Ui.S(18);
            top = new Stepper(Validation.MinTop, Validation.MaxTop, defaultTop, Ui.S(34), "切り抜く数");
            summary.Font = Theme.Small;
            topRow.Add(lTop, 0).Add(top, 8).Add(summary, 12);
            toolRow.Add(addRange, 0).Add(lQuick, 16);
            for (int i = 0; i < QuickSeconds.Length; i++)
            {
                int sec = QuickSeconds[i];
                var b = new Btn(QuickLabels[i], BtnKind.Normal) { Height = Ui.S(26) };
                b.AccessibleName = "終了を開始から " + QuickLabels[i].TrimStart('+');
                b.Click += (s, e) => { var r = active ?? rows.LastOrDefault(); if (r != null) r.SetLength(sec); };
                quick.Add(b);
                toolRow.Add(b, i == 0 ? 6 : 4);
            }
            Controls.AddRange(new Control[] { urlField, remove, title, topRow, toolRow });

            Url.TextChanged += (s, e) => UrlEdited();
            Url.Leave += (s, e) => { leftUrl = true; ShowTitle(); };
            Url.KeyDown += UrlKeyDown;
            Url.DragEnter += (s, e) => e.Effect = e.Data.GetDataPresent(DataFormats.UnicodeText) || e.Data.GetDataPresent(DataFormats.Text) ? DragDropEffects.Copy : DragDropEffects.None;
            Url.DragDrop += (s, e) =>
            {
                string t = (e.Data.GetData(DataFormats.UnicodeText) ?? e.Data.GetData(DataFormats.Text)) as string;
                if (!string.IsNullOrWhiteSpace(t)) SetUrlLines(t);
            };
            remove.Click += (s, e) => { if (RemoveClicked != null) RemoveClicked(); };
            addRange.Click += (s, e) => { var r = AddRow(); Arrange(); Fire(); r.Start.Focus(); };
            top.ValueChanged += () => { UpdateSummary(); Fire(); };
            AddRow();
            UpdateSummary();
            ShowTitle();
            Arrange();
        }

        public string VideoId { get { return YouTubeUrl.ExtractId(Url.Text); } }
        public bool HasUrlText { get { return Url.Text.Trim().Length > 0; } }
        public int TopCount { get { return top.Value; } }
        public IEnumerable<RangeRow> Rows { get { return rows; } }

        // 何も入っていないカード(送るときに数えない)
        public bool IsBlank { get { return !HasUrlText && rows.All(r => r.IsEmpty); } }

        public List<ClipRange> ValidRanges()
        {
            var list = new List<ClipRange>();
            foreach (var r in rows)
            {
                ClipRange c;
                if (r.TryGet(out c)) list.Add(c);
            }
            return list;
        }

        public UrlItem ToItem()
        {
            return new UrlItem { Url = YouTubeUrl.Normalize(VideoId), Top = top.Value, Ranges = manual ? new List<ClipRange>() : ValidRanges() };
        }

        // ③ 全部人が行う: 切り抜く数と区間は使わない(灰色にする。値は残す)
        public void SetManual(bool on)
        {
            manual = on;
            top.Enabled = !on;
            lTop.Enabled = !on;
            foreach (var r in rows) r.Enabled = !on;
            addRange.Enabled = !on && rows.Count < Ranges.MaxCount;
            lQuick.Enabled = !on;
            foreach (var b in quick) b.Enabled = !on;
            UpdateSummary();
        }

        public void SetBusy(bool busy)
        {
            Url.ReadOnly = busy;
            remove.Enabled = !busy;
            top.Enabled = !busy && !manual;
            foreach (var r in rows) r.Enabled = !busy && !manual;
            addRange.Enabled = !busy && !manual && rows.Count < Ranges.MaxCount;
            foreach (var b in quick) b.Enabled = !busy && !manual;
        }

        // 題名の問い合わせの結果(別の ID に変わっていたら捨てる)
        public void SetTitle(string id, string text)
        {
            if (id != VideoId) return;
            titleId = id;
            titleText = text;
            titleFailed = text == null;
            ShowTitle();
        }

        // 送る前の検査: 誤りがあれば、その欄を返す(フォーカスを移す先)。無ければ null
        public Control Validate_(HashSet<string> seenIds)
        {
            strict = true;
            leftUrl = true;
            foreach (var r in rows) r.Strict = !manual;
            ShowTitle();
            string id = VideoId;
            if (id == null) return Url;
            if (!seenIds.Add(id))
            {
                title.Tone = Tone.Error;
                title.Text = "同じ配信が上にあります。区間は1つのカードにまとめてください";
                return Url;
            }
            if (!manual)
                foreach (var r in rows) if (r.Problem != null) return r.ProblemControl;
            return null;
        }

        void Fire()
        {
            if (Changed != null) Changed();
        }

        RangeRow AddRow()
        {
            var r = new RangeRow();
            r.Strict = strict && !manual;
            r.Changed += () => { TopFollowsRanges(); UpdateSummary(); Arrange(); Fire(); };
            r.Activated += () => active = r;
            r.RemoveClicked += () => RemoveRow(r);
            r.UrlPasted += text => { if (!HasUrlText) { string id = YouTubeUrl.ExtractId(text); if (id != null) Url.Text = YouTubeUrl.Normalize(id); } };
            rows.Add(r);
            Controls.Add(r);
            Theme.Apply(r);
            addRange.Enabled = !manual && rows.Count < Ranges.MaxCount;
            active = r;
            return r;
        }

        void RemoveRow(RangeRow r)
        {
            if (rows.Count <= 1) { r.Clear(); r.Start.Focus(); return; }   // 最後の1行は消さずに空にする(入れる場所を残す)
            int i = rows.IndexOf(r);
            rows.Remove(r);
            Controls.Remove(r);
            r.Dispose();
            if (active == r) active = null;
            addRange.Enabled = !manual && rows.Count < Ranges.MaxCount;
            UpdateSummary();
            Arrange();
            Fire();
            rows[Math.Min(i, rows.Count - 1)].Start.Focus();
        }

        // 区間が切り抜く数を超えたら、数を合わせる
        void TopFollowsRanges()
        {
            int n = ValidRanges().Count;
            if (n > top.Value) top.Value = Math.Min(n, Validation.MaxTop);
        }

        void UpdateSummary()
        {
            if (manual) { summary.Tone = Tone.Muted; summary.Text = "③ は送り先の人が切り抜く所を決めます(数と区間は使いません)"; }
            else
            {
                int n = ValidRanges().Count, auto = Math.Max(0, top.Value - n);
                summary.Tone = Tone.Accent;
                summary.Text = n == 0 ? "自動で " + auto + " 個(見どころを PC が選びます)" : "指定 " + n + " + 自動 " + auto + (auto == 0 ? "(指定した所だけ)" : "");
            }
            topRow.Arrange();
        }

        void UrlEdited()
        {
            string id = VideoId;
            if (id != titleId) { titleId = null; titleText = null; titleFailed = false; }
            // t= つきの URL: 最初の空いている区間の開始に、その時刻を入れる
            int sec;
            if (id != null && TimeText.TryParse(Url.Text, out sec))
            {
                var r = rows.FirstOrDefault(x => x.IsEmpty);
                if (r != null && !manual) r.Start.SetValue(sec);
            }
            ShowTitle();
            if (id != null && titleId == null && IdChanged != null) IdChanged(id);
            Fire();
        }

        void ShowTitle()
        {
            string id = VideoId;
            urlField.Error = false;
            if (!HasUrlText)
            {
                bool need = strict && !rows.All(r => r.IsEmpty);
                title.Tone = need ? Tone.Error : Tone.Muted;
                title.Text = need ? "配信の URL を入れてください" : "貼ると、ここに配信の題名が出ます(何行かまとめて貼ると、配信が増えます)";
                urlField.Error = need;
            }
            else if (id == null)
            {
                title.Tone = leftUrl ? Tone.Error : Tone.Muted;
                title.Text = leftUrl ? "YouTube の配信・動画の URL ではありません(watch?v=… / youtu.be/… / live/… の形)" : "";
                urlField.Error = leftUrl;
            }
            else if (titleId == id && titleText != null) { title.Tone = Tone.Text; title.Text = "✓ " + titleText; }
            else if (titleId == id && titleFailed) { title.Tone = Tone.Muted; title.Text = "題名を確かめられませんでした(このまま送れます)"; }
            else { title.Tone = Tone.Muted; title.Text = "配信を確かめています…"; }
        }

        // Ctrl+V: 何行もあるときは1行目をここに、残りはカードを増やす
        void UrlKeyDown(object sender, KeyEventArgs e)
        {
            if (!(e.Control && e.KeyCode == Keys.V) || Url.ReadOnly) return;
            string text;
            try { text = Clipboard.ContainsText() ? Clipboard.GetText() : ""; }
            catch (Exception) { return; }
            if (text.IndexOf('\n') < 0 && text.IndexOf('\r') < 0) return;   // 1行なら標準の貼り付け
            e.Handled = e.SuppressKeyPress = true;
            SetUrlLines(text);
        }

        public void SetUrlLines(string text)
        {
            var lines = (text ?? "").Replace("\r\n", "\n").Replace('\r', '\n').Split('\n').Select(l => l.Trim()).Where(l => l.Length > 0).ToArray();
            if (lines.Length == 0) return;
            Url.Text = lines[0];
            Url.SelectionStart = Url.Text.Length;
            leftUrl = true;
            ShowTitle();
            if (lines.Length > 1 && MoreUrls != null) MoreUrls(lines.Skip(1).ToArray());
        }

        public void FocusUrl()
        {
            Url.Focus();
        }

        // 見本(--screenshot --sample)
        public void Sample(string url, string titleShown, int topValue, params int[] startEnd)
        {
            Url.Text = url;
            SetTitle(VideoId, titleShown);
            top.Value = topValue;
            for (int i = 0; i + 1 < startEnd.Length; i += 2)
            {
                var r = i == 0 ? rows[0] : AddRow();
                r.Start.SetValue(startEnd[i]);
                r.End.SetValue(startEnd[i + 1]);
            }
            Arrange();
        }

        // 中を並べて、高さを決める(幅は親が決める)
        public void Arrange()
        {
            int pad = Ui.S(10), w = Math.Max(Ui.S(200), Width - pad * 2), y = pad, tab = 0;
            // Tab の順は見た目の順: URL → × → 切り抜く数 → 区間の行 → 「区間を足す」と「+30秒」など
            urlField.TabIndex = tab++;
            remove.TabIndex = tab++;
            topRow.TabIndex = tab++;
            foreach (var r in rows) r.TabIndex = tab++;
            toolRow.TabIndex = tab++;
            urlField.SetBounds(pad, y, w - Ui.S(30), Ui.S(28));
            remove.Location = new Point(pad + w - Ui.S(26), y + Ui.S(1));
            y += Ui.S(30);
            title.SetBounds(pad, y, w, Ui.S(18));
            y += Ui.S(22);
            topRow.Arrange();
            topRow.Location = new Point(pad, y);
            y += topRow.Height + Ui.S(6);
            foreach (var r in rows)
            {
                r.Location = new Point(pad, y);
                y += r.Height + Ui.S(4);
            }
            toolRow.Arrange();
            toolRow.Location = new Point(pad, y + Ui.S(2));
            y += toolRow.Height + Ui.S(2) + pad;
            if (Height != y) Height = y;
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            if (urlField != null) Arrange();
        }
    }

    // ---- ライブ配信の依頼(2.8.0。docs/spec/friend-intake.md の 2-15): 配信中か配信前の URL 1 本 + 友人のベータの設定。----
    //   URL と題名の出し方は配信のカードと同じ(oEmbed)。設定は 1 行ずつ短い説明つき。値は呼んだ側が settings.json に覚える
    public class LiveCard : VStack
    {
        public readonly TextBox Url = new TextBox();
        readonly Field urlField;
        readonly Lbl lUrl = new Lbl("ライブ配信の URL(1 本)", Tone.Text), title = new Lbl("", Tone.Muted),
                     explain = new Lbl("配信中か配信前の YouTube の URL を貼ります。送り先の PC が配信を録画しながら見どころを見つけ、切り抜けしだい 1 本ずつ" +
                                       "「受け取る」に届けます(① 全自動のパック)。もう終わった配信なら、ふつうの ① 全自動の依頼になります。", Tone.Muted),
                     head = new Lbl("ライブ配信の設定(ベータ。試しながら変えてください)", Tone.Text);
        readonly Btn sensHigh = new Btn("高", BtnKind.Toggle), sensNormal = new Btn("普通", BtnKind.Toggle), sensLow = new Btn("低", BtnKind.Toggle);
        readonly Stepper perHour, length, waitMin, pad;
        readonly Check afterStream = new Check("配信が終わったあと、アーカイブからも追加する");
        string sens = LiveSettings.Normal;
        bool leftUrl, strict, titleFailed;
        string titleId, titleText;

        public event Action Changed;              // URL・設定が変わった(要約・仕上げ方の見直し)
        public event Action<string> IdChanged;    // 配信の ID が決まった(題名を問い合わせる)

        public LiveCard()
        {
            OnPanel = true;
            Url.MaxLength = 2048;
            Url.AccessibleName = "ライブ配信の URL";
            Url.HandleCreated += (s, e) => Ui.Cue(Url, "ここに配信中か配信前の YouTube の URL を貼る(Ctrl+V)");
            urlField = new Field(Url);
            title.AccentLead = "✓ ";
            title.Font = explain.Font = Theme.Small;
            head.Font = Theme.Bold;
            lUrl.Font = Theme.Bold;
            Add(lUrl, 0, false);
            Add(urlField, 6, true);
            Add(title, 4, true);
            Add(explain, 6, true);
            Add(head, 12, false);

            foreach (var b in new[] { sensHigh, sensNormal, sensLow }) b.Width = Math.Max(b.Width, Ui.S(52));
            sensHigh.Click += (s, e) => SetSens(LiveSettings.High);
            sensNormal.Click += (s, e) => SetSens(LiveSettings.Normal);
            sensLow.Click += (s, e) => SetSens(LiveSettings.Low);
            sensHigh.AccessibleName = "感度 高"; sensNormal.AccessibleName = "感度 普通"; sensLow.AccessibleName = "感度 低";
            AddSetting("感度", new HRow().Add(sensHigh, 0).Add(sensNormal, 4).Add(sensLow, 4), "盛り上がりをどれだけ拾うか。高いほど候補が増えます(外れも増えます)");
            perHour = NewStepper(LiveSettings.MinPerHour, LiveSettings.MaxPerHour, LiveSettings.DefaultPerHour, "1 時間の本数", v => v + " 本");
            AddSetting("1 時間の本数", perHour, "1 時間の配信から切り抜く候補の上限です");
            length = NewStepper(LiveSettings.MinLength, LiveSettings.MaxLength, LiveSettings.DefaultLength, "切り抜きの長さ", v => v + " 秒");
            AddSetting("切り抜きの長さ", length, "1 本の長さ(秒)。盛り上がった所を中心に切ります");
            waitMin = NewStepper(LiveSettings.MinWait, LiveSettings.MaxWait, LiveSettings.DefaultWait, "自動で採用するまでの待ち", v => v + " 分");
            AddSetting("自動で採用するまでの待ち", waitMin, "候補が出てから、送り先の PC が自動で切り抜くまでの時間。長いほど送り先の人が見て外せます");
            pad = NewStepper(LiveSettings.MinPad, LiveSettings.MaxPad, LiveSettings.DefaultPad, "前後の余白", v => v + " 秒");
            AddSetting("前後の余白", pad, "切り抜きの前後に足す秒数(頭の一言が欠けないように)");
            afterStream.Checked = true;
            afterStream.CheckedChanged += (s, e) => Fire();
            Add(afterStream, 8, false);
            Add(new Lbl("配信が終わったら、アーカイブを見直して、配信中に見逃した所も切り抜いて届けます", Tone.Muted) { Font = Theme.Small }, 0, true);

            Url.TextChanged += (s, e) => UrlEdited();
            Url.Leave += (s, e) => { leftUrl = true; ShowTitle(); };
            Url.KeyDown += (s, e) =>
            {
                if (!(e.Control && e.KeyCode == Keys.V) || Url.ReadOnly) return;   // 何行も貼ったときは 1 行目だけ(ライブ配信の依頼は 1 本)
                string text;
                try { text = Clipboard.ContainsText() ? Clipboard.GetText() : ""; }
                catch (Exception) { return; }
                if (text.IndexOf('\n') < 0 && text.IndexOf('\r') < 0) return;
                e.Handled = e.SuppressKeyPress = true;
                SetUrl(text);
            };
            SetSens(sens);
            ShowTitle();
        }

        Stepper NewStepper(int min, int max, int start, string name, Func<int, string> format)
        {
            var st = new Stepper(min, max, start, Ui.S(64), name) { Format = format };
            st.Show_();
            st.ValueChanged += Fire;
            return st;
        }

        // 1 行(名前 | 部品)と、その下の短い説明
        void AddSetting(string name, Control part, string hint)
        {
            var l = new Lbl(name, Tone.Text) { AutoSize = false, Size = new Size(Ui.S(176), Ui.S(20)), TextAlign = ContentAlignment.MiddleLeft };
            Add(new HRow().Add(l, 0).Add(part, 0), 8, false);
            Add(new Lbl(hint, Tone.Muted) { Font = Theme.Small }, 2, true);
        }

        public string VideoId { get { return YouTubeUrl.ExtractId(Url.Text); } }
        public bool HasUrlText { get { return Url.Text.Trim().Length > 0; } }

        public LiveSettings Settings
        {
            get { return new LiveSettings { Sens = sens, PerHour = perHour.Value, Length = length.Value, WaitMin = waitMin.Value, Pad = pad.Value, AfterStream = afterStream.Checked }.Clean(); }
            set
            {
                var c = (value ?? new LiveSettings()).Clean();
                SetSens(c.Sens);
                perHour.Value = c.PerHour;
                length.Value = c.Length;
                waitMin.Value = c.WaitMin;
                pad.Value = c.Pad;
                afterStream.Checked = c.AfterStream;
            }
        }

        void SetSens(string value)
        {
            sens = LiveSettings.SensAll.Contains(value) ? value : LiveSettings.Normal;
            sensHigh.On = sens == LiveSettings.High;
            sensNormal.On = sens == LiveSettings.Normal;
            sensLow.On = sens == LiveSettings.Low;
            Fire();
        }

        void Fire()
        {
            if (Changed != null) Changed();
        }

        public void SetTitle(string id, string text)
        {
            if (id != VideoId) return;
            titleId = id;
            titleText = text;
            titleFailed = text == null;
            ShowTitle();
        }

        // 送る前の検査: URL が YouTube の形でなければ URL の欄を返す(無ければ null)
        public Control Validate_()
        {
            strict = true;
            leftUrl = true;
            ShowTitle();
            return VideoId == null ? Url : null;
        }

        public void SetUrl(string text)
        {
            var first = (text ?? "").Replace("\r\n", "\n").Replace('\r', '\n').Split('\n').Select(l => l.Trim()).FirstOrDefault(l => l.Length > 0);
            if (first == null) return;
            Url.Text = first;
            Url.SelectionStart = Url.Text.Length;
            leftUrl = true;
            ShowTitle();
        }

        public void Clear()
        {
            strict = leftUrl = false;
            Url.Text = "";
            ShowTitle();
        }

        public void FocusUrl()
        {
            Url.Focus();
        }

        public void SetBusy(bool busy)
        {
            Url.ReadOnly = busy;
            foreach (Control c in new Control[] { sensHigh, sensNormal, sensLow, perHour, length, waitMin, pad, afterStream }) c.Enabled = !busy;
        }

        void UrlEdited()
        {
            string id = VideoId;
            if (id != titleId) { titleId = null; titleText = null; titleFailed = false; }
            ShowTitle();
            if (id != null && titleId == null && IdChanged != null) IdChanged(id);
            Fire();
        }

        void ShowTitle()
        {
            string id = VideoId;
            urlField.Error = false;
            if (!HasUrlText) { title.Tone = Tone.Muted; title.Text = "貼ると、ここに配信の題名が出ます"; }
            else if (id == null)
            {
                title.Tone = leftUrl || strict ? Tone.Error : Tone.Muted;
                title.Text = leftUrl || strict ? "YouTube の配信の URL ではありません(watch?v=… / youtu.be/… / live/… の形)" : "";
                urlField.Error = leftUrl || strict;
            }
            else if (titleId == id && titleText != null) { title.Tone = Tone.Text; title.Text = "✓ " + titleText; }
            else if (titleId == id && titleFailed) { title.Tone = Tone.Muted; title.Text = "題名を確かめられませんでした(このまま送れます)"; }
            else { title.Tone = Tone.Muted; title.Text = "配信を確かめています…"; }
            Arrange();
        }

        // 見本(--screenshot --tab live)
        public void Sample(string url, string titleShown)
        {
            Url.Text = url;
            SetTitle(VideoId, titleShown);
        }
    }

    // ---- 配信の題名を裏で確かめる(YouTube の oEmbed)。同じ ID は1回だけ。失敗しても送れる ----
    public class TitleLookup
    {
        readonly Dictionary<string, string> done = new Dictionary<string, string>();   // id -> 題名(確かめられなかったら null)
        readonly HashSet<string> pending = new HashSet<string>();
        readonly object gate = new object();

        public bool Offline;            // 通信しない(テスト・画面の確認)

        // 結果は裏のスレッドから呼ぶ(呼ばれた側で画面のスレッドへ渡す)
        public void Request(string id, Action<string, string> result)
        {
            string url = OEmbed.Url(id);
            if (url == null || Offline) return;
            lock (gate)
            {
                if (done.ContainsKey(id)) { string t = done[id]; ThreadPool.QueueUserWorkItem(_ => result(id, t)); return; }
                if (!pending.Add(id)) return;
            }
            ThreadPool.QueueUserWorkItem(_ =>
            {
                string title = null;
                try { title = OEmbed.ParseTitle(Fetch(url)); }
                catch (Exception ex) { Log.Write("title: " + ex.GetType().Name); }
                lock (gate) { pending.Remove(id); done[id] = title; }
                result(id, title);
            });
        }

        static string Fetch(string url)
        {
            var req = (HttpWebRequest)WebRequest.Create(url);
            req.Method = "GET";
            req.Timeout = OEmbed.TimeoutMs;
            req.ReadWriteTimeout = OEmbed.TimeoutMs;
            req.AllowAutoRedirect = false;
            req.UserAgent = "RequestSender/" + AppInfo.Version;
            using (var res = (HttpWebResponse)req.GetResponse())
            using (var s = res.GetResponseStream())
            using (var ms = new MemoryStream())
            {
                var buf = new byte[8192];
                int n;
                while ((n = s.Read(buf, 0, buf.Length)) > 0)
                {
                    ms.Write(buf, 0, n);
                    if (ms.Length > OEmbed.MaxBytes) throw new IOException("too large");
                }
                return new UTF8Encoding(false).GetString(ms.ToArray());
            }
        }
    }
}
