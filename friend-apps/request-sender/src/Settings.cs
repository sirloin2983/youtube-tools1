// 設定の小窓(F1 の F3b。設計 notes:docs/design/f1-build.md の F3b・1-2・3 の (f1m))。
//   YouTube の API キー … 貼った瞬間に videos.list を 1 回呼んで「使えます / 理由」。キーは <作業データ>\app\keys.json だけに置く(束・送り返しに入れない)。
//                         ② へは起こすときの環境変数 YTT_YT_API_KEY で渡す(Backend.StartLocked)= 変えたら次にアプリを開いたときから効く
//   エンジン A(Vulkan)/ C(CUDA) … PUT /api/flow/machine {device}(口は ② の F0-1)。口が無い古い ② は 404 → 「更新が要る」
//   案件の根・空き容量の下限 … 同じ PUT。隠さず欄に出す(決めたこと 7)
//   [説明を開く] … guide.html#設定
// 中身の判断(応答の読み・理由の文・保存の形)は静的な関数にして CoreTests で確かめる。窓は薄い。
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using FriendApps;

namespace RequestSender
{
    // ---- API キーの確かめ: videos.list を 1 回 ----
    public static class YtKeyCheck
    {
        public const string ProbeVideo = "dQw4w9WgXcQ";

        // 貼ったものを整える(前後の空白・改行・引用符を落とす)
        public static string Clean(string s)
        {
            return (s ?? "").Trim().Trim('"', '\'', ' ', '\t', '\r', '\n');
        }

        // キーの形(英数字と - _ で 20〜80 字。② の ytt/apikey.KEY_RE と同じ)
        public static bool LooksLikeKey(string s)
        {
            if (s == null || s.Length < 20 || s.Length > 80) return false;
            foreach (char c in s)
                if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_')) return false;
            return true;
        }

        public static string Url(string key)
        {
            return "https://www.googleapis.com/youtube/v3/videos?part=id&id=" + ProbeVideo + "&key=" + Uri.EscapeDataString(key);
        }

        // 返事 → 使えるか + 文。status 0 = つながらなかった(body に理由)
        public static bool Judge(int status, string body, out string message)
        {
            if (status == 200) { message = "使えます"; return true; }
            if (status == 0) { message = "つながりませんでした(" + (string.IsNullOrEmpty(body) ? "ネットワーク" : body) + ")"; return false; }
            string reason = "", text = "";
            try
            {
                var err = Json.Dict(Json.Parse(body), "error");
                text = Json.Str(err, "message") ?? "";
                foreach (var e in Json.List(err, "errors")) { reason = Json.Str(e, "reason") ?? ""; break; }
                if (reason.Length == 0) reason = Json.Str(err, "status") ?? "";
            }
            catch (Exception ex)
            {
                if (!(ex is FormatException || ex is ArgumentException || ex is InvalidOperationException)) throw;
            }
            string r = reason.ToLowerInvariant();
            if (r == "keyinvalid" || r == "api_key_invalid" || r == "badrequest" || r == "invalid_argument" || text.IndexOf("API key not valid", StringComparison.OrdinalIgnoreCase) >= 0)
                message = "キーが違います(貼り直してください。前後の空白も入らないように)";
            else if (r == "accessnotconfigured" || r == "service_disabled" || text.IndexOf("has not been used", StringComparison.OrdinalIgnoreCase) >= 0)
                message = "このキーのプロジェクトで「YouTube Data API v3」が有効になっていません";
            else if (r == "quotaexceeded" || r == "ratelimitexceeded" || r == "resource_exhausted")
                message = "今日の使える数の上限に達しています(キーは正しい形です。明日また使えます)";
            else if (r == "ipreferer_blocked" || r == "iprefererblocked" || r == "api_key_http_referrer_blocked" || r == "api_key_ip_address_blocked" || r == "api_target_blocked" || r == "forbidden" || r == "permission_denied")
                message = "このキーは使える場所や API が制限されています(「YouTube Data API v3」だけを許可し、場所の制限は外してください)";
            else
                message = "確かめられませんでした(HTTP " + status + (reason.Length > 0 ? ", " + reason : "") + ")";
            return false;
        }

        // 実際の 1 回(裏の糸で呼ぶ)。-> ok・文
        public static bool Check(string key, out string message)
        {
            return Check(key, Fetch, out message);
        }

        public static bool Check(string key, Func<string, KeyValuePair<int, string>> fetch, out string message)
        {
            if (!LooksLikeKey(key)) { message = "キーの形が違います(英数字と - _ だけの 30〜40 字ほどです)"; return false; }
            var r = fetch(Url(key));
            return Judge(r.Key, r.Value, out message);
        }

        static KeyValuePair<int, string> Fetch(string url)
        {
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = req.ReadWriteTimeout = 10000;
                req.UserAgent = "RequestSender";
                HttpWebResponse resp;
                try { resp = (HttpWebResponse)req.GetResponse(); }
                catch (WebException ex)
                {
                    resp = ex.Response as HttpWebResponse;
                    if (resp == null) return new KeyValuePair<int, string>(0, ex.Status.ToString());
                }
                using (resp)
                using (var rd = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    return new KeyValuePair<int, string>((int)resp.StatusCode, rd.ReadToEnd());
            }
            catch (Exception ex)
            {
                if (!(ex is WebException || ex is IOException || ex is InvalidOperationException || ex is NotSupportedException)) throw;
                return new KeyValuePair<int, string>(0, ex.GetType().Name);
            }
        }
    }

    // ---- キーの置き場所 <作業データ>\app\keys.json({"youtubeApiKey": "..."}。ほかの項目は消さない) ----
    public static class KeyStore
    {
        public const string Field = "youtubeApiKey";

        public static string PathFor(string dataRoot)
        {
            return Path.Combine(dataRoot, "app", "keys.json");
        }

        // キー(無い・壊れていれば "")
        public static string Load(string dataRoot)
        {
            if (string.IsNullOrEmpty(dataRoot)) return "";
            var d = Json.ReadFileOrNull(PathFor(dataRoot));
            return YtKeyCheck.Clean(Json.Str(d, Field));
        }

        // 書く(空なら項目を消す)。ほかの項目は残す・途中で切れないよう一時ファイル経由
        public static void Save(string dataRoot, string key)
        {
            string path = PathFor(dataRoot);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var d = new Dictionary<string, object>(Json.ReadFileOrNull(path) ?? new Dictionary<string, object>());
            if (string.IsNullOrEmpty(key)) d.Remove(Field); else d[Field] = key;
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, new JavaScriptSerializer().Serialize(d) + "\r\n", new UTF8Encoding(false));
            if (File.Exists(path)) File.Delete(path);
            File.Move(tmp, path);
        }
    }

    // ---- この PC の設定(② の GET/PUT /api/flow/machine) ----
    public class MachineView
    {
        public string Device = "", CaseRoot = "", GpuName = "";
        public double DiskMinGB = -1, VramGB = -1;

        // 返事は平ら、または machine / values の下のどちらでも読む(口の形は F0-1)
        public static MachineView Parse(IDictionary<string, object> body)
        {
            var d = Json.Dict(body, "machine") ?? Json.Dict(body, "values") ?? body;
            var v = new MachineView { Device = Json.Str(d, "device") ?? "", CaseRoot = Json.Str(d, "caseRoot") ?? "", DiskMinGB = Num(d, "diskMinGB") };
            var gpu = Json.Dict(d, "gpu") ?? Json.Dict(body, "gpu");
            if (gpu != null) { v.GpuName = Json.Str(gpu, "name") ?? ""; v.VramGB = Num(gpu, "vramGB"); }
            return v;
        }

        static double Num(IDictionary<string, object> d, string key)
        {
            object o;
            if (d == null || !d.TryGetValue(key, out o) || o == null) return -1;
            try { return Convert.ToDouble(o, CultureInfo.InvariantCulture); }
            catch (Exception ex) { if (!(ex is FormatException || ex is InvalidCastException || ex is OverflowException)) throw; return -1; }
        }

        public string GpuText
        {
            get
            {
                if (GpuName.Length == 0) return "GPU: 調べられていません";
                return "GPU: " + GpuName + (VramGB > 0 ? "(" + VramGB.ToString("0.#", CultureInfo.InvariantCulture) + " GB)" : "");
            }
        }
    }

    public static class MachineApi
    {
        public const string Path = "/api/flow/machine";
        public const double DiskMax = 100000;   // ② の machine.DISK_MAX_GB

        // 画面の A / C → ② の device
        public static string DeviceOf(char engine)
        {
            return engine == 'C' ? "cuda" : "vulkan";
        }

        public static char EngineOf(string device)
        {
            return string.Equals(device, "cuda", StringComparison.OrdinalIgnoreCase) ? 'C' : 'A';
        }

        // 空き容量の欄 → 数。読めない・範囲の外は null(理由は message)
        public static double? ParseDisk(string text, out string message)
        {
            message = null;
            string t = (text ?? "").Trim();
            double v;
            if (!double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out v) && !double.TryParse(t, NumberStyles.Float, CultureInfo.CurrentCulture, out v))
            { message = "空き容量の下限は数(GB)で入れてください"; return null; }
            if (v < 0 || v > DiskMax) { message = "空き容量の下限は 0〜" + (long)DiskMax + " GB にしてください"; return null; }
            return v;
        }

        // PUT の本文(指定した項目だけ)
        public static Dictionary<string, object> Body(string device, string caseRoot, double? diskMinGB)
        {
            var b = new Dictionary<string, object>();
            if (device != null) b["device"] = device;
            if (caseRoot != null) b["caseRoot"] = caseRoot;
            if (diskMinGB.HasValue) b["diskMinGB"] = diskMinGB.Value;
            return b;
        }

        // PUT / GET の返事 → 失敗の文(成功なら null)。口が無い古い ② の 404 は「更新が要る」
        public static string Problem(FlowReply r)
        {
            if (r.Status >= 200 && r.Status < 300) return null;
            if (r.Status == 404 || r.Status == 405) return "処理の部品が古く、この設定に対応していません。アプリを更新してください";
            if (r.Status == 400) return "受け付けられませんでした: " + r.Message;
            if (r.Status == 0) return r.Error ?? "処理の部品につながりませんでした";
            return "変えられませんでした(HTTP " + r.Status + ")";
        }
    }

    // ---- 設定の小窓 ----
    public sealed class SettingsForm : Form, IThemed
    {
        readonly Backend backend;
        readonly string dataRoot, guidePath;
        readonly Lbl head = new Lbl("設定", Tone.Text), lKey = new Lbl("YouTube の API キー", Tone.Text), keyHint = new Lbl("", Tone.Muted), keyResult = new Lbl("", Tone.Muted),
                     lEngine = new Lbl("文字起こしのエンジン", Tone.Text), gpuLbl = new Lbl("", Tone.Muted), engineHint = new Lbl("", Tone.Muted), engineResult = new Lbl("", Tone.Muted),
                     lRoot = new Lbl("案件の保存先", Tone.Text), lDisk = new Lbl("空き容量の下限", Tone.Text), gb = new Lbl("GB(下回ると新しい処理を始めません)", Tone.Muted),
                     machineResult = new Lbl("", Tone.Muted);
        readonly TextBox keyBox = new TextBox(), rootBox = new TextBox(), diskBox = new TextBox();
        Field keyField, rootField, diskField;
        readonly Btn keyClear = new Btn("消す", BtnKind.Normal), engA = new Btn("A  Vulkan(どの GPU でも)", BtnKind.Toggle), engC = new Btn("C  CUDA(NVIDIA)", BtnKind.Toggle),
                     saveBtn = new Btn("保存", BtnKind.Primary), guideBtn = new Btn("説明を開く", BtnKind.Ghost), closeBtn = new Btn("閉じる", BtnKind.Normal);
        string lastChecked = "";
        int checkSeq;

        public SettingsForm(Backend backend, string dataRoot, string exeDir)
        {
            this.backend = backend;
            this.dataRoot = dataRoot ?? Backend.DefaultDataRoot();
            guidePath = Path.Combine(exeDir ?? "", "guide.html");
            Text = "設定";
            Font = Theme.Body;
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            ShowInTaskbar = false;
            KeyPreview = true;
            ClientSize = new Size(Ui.S(660), Ui.S(600));

            head.Font = Theme.Bold;
            keyHint.Text = "貼ると、その場で使えるか確かめます。このキーはこの PC の中だけに置き、送りません。変えたら、次にアプリを開いたときから効きます。";
            keyBox.AccessibleName = "YouTube の API キー";
            keyField = new Field(keyBox);
            keyBox.TextChanged += (s, e) => OnKeyChanged();
            keyClear.Click += (s, e) => { keyBox.Text = ""; };
            lastChecked = KeyStore.Load(this.dataRoot);
            keyBox.Text = lastChecked;
            keyResult.Text = lastChecked.Length > 0 ? "保存してあるキーです" : "まだ入っていません(無くても動きますが、配信の探し方に使います)";

            engA.AccessibleName = "エンジン A Vulkan";
            engC.AccessibleName = "エンジン C CUDA";
            engA.Click += (s, e) => PickEngine('A');
            engC.Click += (s, e) => PickEngine('C');
            engineHint.Text = "A は GPU の種類を問いません。C は NVIDIA の GPU でより速くなります(切り替えたとき、必要な部品を取ります)。";

            rootBox.AccessibleName = "案件の保存先";
            diskBox.AccessibleName = "空き容量の下限 GB";
            rootField = new Field(rootBox);
            diskField = new Field(diskBox);
            saveBtn.Click += (s, e) => SaveMachine();
            guideBtn.Click += (s, e) => OpenGuide();
            closeBtn.Click += (s, e) => Close();

            foreach (var l in new[] { keyHint, engineHint, gpuLbl, gb, keyResult, engineResult, machineResult }) l.Font = Theme.Small;
            foreach (var l in new[] { keyHint, engineHint, keyResult, engineResult, machineResult }) { l.AutoSize = false; }
            Controls.AddRange(new Control[] { head, lKey, keyField, keyClear, keyHint, keyResult, lEngine, gpuLbl, engA, engC, engineHint, engineResult,
                                              lRoot, rootField, lDisk, diskField, gb, saveBtn, machineResult, guideBtn, closeBtn });
            Resize += (s, e) => LayoutParts();
            HandleCreated += (s, e) => Theme.TitleBar(this);
            Load += (s, e) => { ApplyTheme(); Theme.Apply(this); LayoutParts(); LoadMachine(); };
            KeyDown += (s, e) => { if (e.KeyCode == Keys.Escape) Close(); };
            LayoutParts();
            SetEngine('A');
            SetMachineEnabled(backend != null && backend.Ready);
        }

        public void ApplyTheme()
        {
            BackColor = Theme.P.Bg;
        }

        void LayoutParts()
        {
            int m = Ui.S(20), w = ClientSize.Width - m * 2, y = m;
            head.Location = new Point(m, y);
            y += Ui.S(34);
            lKey.Location = new Point(m, y);
            y += Ui.S(24);
            keyClear.FitWidth();
            keyClear.Location = new Point(m + w - keyClear.Width, y);
            keyField.SetBounds(m, y, w - keyClear.Width - Ui.S(8), Ui.S(28));
            y += Ui.S(34);
            keyResult.SetBounds(m, y, w, Ui.S(20));
            y += Ui.S(22);
            keyHint.SetBounds(m, y, w, Ui.S(36));
            y += Ui.S(52);

            lEngine.Location = new Point(m, y);
            gpuLbl.Location = new Point(m + lEngine.Width + Ui.S(12), y + Ui.S(2));
            y += Ui.S(26);
            engA.Height = engC.Height = Ui.S(32);
            engA.Width = Ui.S(230);
            engC.Width = Ui.S(190);
            engA.Location = new Point(m, y);
            engC.Location = new Point(m + engA.Width + Ui.S(8), y);
            y += Ui.S(38);
            engineResult.SetBounds(m, y, w, Ui.S(20));
            y += Ui.S(22);
            engineHint.SetBounds(m, y, w, Ui.S(36));
            y += Ui.S(56);

            lRoot.Location = new Point(m, y);
            y += Ui.S(24);
            rootField.SetBounds(m, y, w, Ui.S(28));
            y += Ui.S(40);
            lDisk.Location = new Point(m, y + Ui.S(4));
            diskField.SetBounds(m + Ui.S(130), y, Ui.S(100), Ui.S(28));
            gb.Location = new Point(diskField.Right + Ui.S(8), y + Ui.S(5));
            y += Ui.S(44);
            saveBtn.SetBounds(m, y, Ui.S(100), Ui.S(32));
            machineResult.SetBounds(saveBtn.Right + Ui.S(12), y + Ui.S(6), w - saveBtn.Width - Ui.S(12), Ui.S(20));

            closeBtn.FitWidth();
            closeBtn.Location = new Point(m + w - closeBtn.Width, ClientSize.Height - m - closeBtn.Height);
            guideBtn.FitWidth();
            guideBtn.Location = new Point(closeBtn.Left - Ui.S(8) - guideBtn.Width, closeBtn.Top);
        }

        // ---- API キー ----
        void OnKeyChanged()
        {
            string key = YtKeyCheck.Clean(keyBox.Text);
            if (key == lastChecked) return;
            if (key.Length == 0)
            {
                lastChecked = "";
                checkSeq++;
                try { KeyStore.Save(dataRoot, ""); keyResult.Text = "消しました"; keyResult.Tone = Tone.Muted; }
                catch (Exception ex) { ShowIoError(keyResult, ex); }
                return;
            }
            if (!YtKeyCheck.LooksLikeKey(key))
            {
                checkSeq++;
                keyResult.Text = key.Length < 20 ? "貼ると確かめます…" : "キーの形が違います";
                keyResult.Tone = key.Length < 20 ? Tone.Muted : Tone.Error;
                return;
            }
            lastChecked = key;
            int seq = ++checkSeq;
            keyResult.Text = "確かめています…";
            keyResult.Tone = Tone.Muted;
            var t = new Thread(() =>
            {
                string msg;
                bool ok = YtKeyCheck.Check(key, out msg);
                Ui2(() =>
                {
                    if (seq != checkSeq) return;   // 貼り直された
                    if (ok)
                    {
                        try { KeyStore.Save(dataRoot, key); msg += "(保存しました)"; }
                        catch (Exception ex) { ShowIoError(keyResult, ex); return; }
                    }
                    keyResult.Text = (ok ? "✓ " : "✗ ") + msg;
                    keyResult.Tone = ok ? Tone.Accent : Tone.Error;
                });
            });
            t.IsBackground = true;
            t.Start();
        }

        static void ShowIoError(Lbl l, Exception ex)
        {
            if (!(ex is IOException || ex is UnauthorizedAccessException)) throw ex;
            l.Text = "保存できませんでした: " + ex.Message;
            l.Tone = Tone.Error;
        }

        void Ui2(Action a)
        {
            if (IsDisposed || !IsHandleCreated) return;
            try { BeginInvoke(a); }
            catch (InvalidOperationException) { }
        }

        // ---- エンジン・案件の保存先・空き容量 ----
        void SetEngine(char e)
        {
            engA.On = e == 'A';
            engC.On = e == 'C';
        }

        void SetMachineEnabled(bool on)
        {
            engA.Enabled = engC.Enabled = saveBtn.Enabled = on;
            rootBox.Enabled = diskBox.Enabled = on;
            if (!on) machineResult.Text = "処理の部品が動いていないので、ここは今は変えられません(アプリを開き直すと動きます)";
        }

        void LoadMachine()
        {
            if (backend == null || !backend.Ready) return;
            var t = new Thread(() =>
            {
                var r = backend.Get(MachineApi.Path);
                var st = backend.Get("/api/flow/status");
                Ui2(() =>
                {
                    string problem = MachineApi.Problem(r);
                    if (problem != null) { machineResult.Text = problem; machineResult.Tone = Tone.Error; SetMachineEnabled(false); machineResult.Text = problem; return; }
                    var v = MachineView.Parse(r.Body);
                    if (v.GpuName.Length == 0 && st.Status == 200) v = Merge(v, MachineView.Parse(st.Body));
                    SetEngine(MachineApi.EngineOf(v.Device));
                    rootBox.Text = v.CaseRoot;
                    diskBox.Text = v.DiskMinGB >= 0 ? v.DiskMinGB.ToString("0.#", CultureInfo.InvariantCulture) : "";
                    gpuLbl.Text = v.GpuText;
                });
            });
            t.IsBackground = true;
            t.Start();
        }

        static MachineView Merge(MachineView a, MachineView fromStatus)
        {
            a.GpuName = fromStatus.GpuName;
            a.VramGB = fromStatus.VramGB;
            return a;
        }

        void PickEngine(char e)
        {
            var old = engC.On ? 'C' : 'A';
            SetEngine(e);
            Put(MachineApi.Body(MachineApi.DeviceOf(e), null, null), engineResult, e == 'C' ? "C(CUDA)にしました。次の処理から使います" : "A(Vulkan)にしました。次の処理から使います", () => SetEngine(old));
        }

        void SaveMachine()
        {
            string msg;
            double? disk = MachineApi.ParseDisk(diskBox.Text, out msg);
            if (disk == null) { machineResult.Text = msg; machineResult.Tone = Tone.Error; return; }
            string root = rootBox.Text.Trim();
            if (root.Length == 0) { machineResult.Text = "案件の保存先を入れてください"; machineResult.Tone = Tone.Error; return; }
            Put(MachineApi.Body(null, root, disk), machineResult, "保存しました", null);
        }

        void Put(Dictionary<string, object> body, Lbl result, string okText, Action undo)
        {
            result.Text = "変えています…";
            result.Tone = Tone.Muted;
            var t = new Thread(() =>
            {
                var r = backend.Put(MachineApi.Path, body);
                Ui2(() =>
                {
                    string problem = MachineApi.Problem(r);
                    if (problem != null) { result.Text = problem; result.Tone = Tone.Error; if (undo != null) undo(); return; }
                    result.Text = okText;
                    result.Tone = Tone.Accent;
                });
            });
            t.IsBackground = true;
            t.Start();
        }

        // ---- 説明 ----
        public static string GuideUrl(string guidePath)
        {
            return new Uri(guidePath).AbsoluteUri + "#" + Uri.EscapeDataString("設定");
        }

        void OpenGuide()
        {
            if (!File.Exists(guidePath)) { MessageBox.Show(this, "説明のページ(guide.html)が見つかりません。アプリを更新してください。", "説明", MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
            try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(GuideUrl(guidePath)) { UseShellExecute = true }); }
            catch (Exception ex)
            {
                if (!(ex is System.ComponentModel.Win32Exception || ex is InvalidOperationException)) throw;
                MessageBox.Show(this, "開けませんでした: " + ex.Message, "説明", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        }

        // テスト用
        public string KeyText { get { return keyBox.Text; } set { keyBox.Text = value; } }
        public bool EngineAOn { get { return engA.On; } }
        public bool MachineEnabled { get { return saveBtn.Enabled; } }
    }

    // ---- MainForm への配線: 上の帯の [設定] ボタン 1 つ ----
    public partial class MainForm
    {
        readonly Btn settingsBtn = new Btn("設定", BtnKind.Ghost);

        void InitSettingsButton()
        {
            settingsBtn.AccessibleName = "設定を開く";
            settingsBtn.Click += (s, e) => OpenSettings();
            topBar.Controls.Add(settingsBtn);
        }

        void OpenSettings()
        {
            using (var f = new SettingsForm(backend, backend != null ? backend.DataRoot : null, exeDir)) f.ShowDialog(this);
        }
    }
}
