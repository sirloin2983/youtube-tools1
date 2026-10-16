// Dropbox との同期 3 つ(F1 の F3c。notes:docs/design/f1-build.md の 2 の F3c・3 の (f1c)(f1d)(f1e)(f1h))。起動時と 10 分ごと。
//   学習の束   … /学習/latest.json の版が新しければ /学習/<版>/ の learning.json の各ファイルを sha256 を確かめて <data>\learning\<版>\ へ。
//                終わったら ② の machine の learningDir を向ける(PUT /api/flow/machine。② が動いていなければ記録だけ = 次の回で向ける)。直近 3 版を残す
//   送り返し   … ② の GET /api/flow/outbox の zip(と outbox の verdict.json)を /送り返し/ へ上げ、上がったら POST /api/flow/outbox/done(失敗は次の回で再送)
//   更新の確認 … /更新/latest.json の版がこのアプリより新しければ帯に「更新する」。入れ替えは F4b の Setup が行う(ここは知らせるだけ。呼ぶ口 = Sync.UpdateHandler)
// Dropbox への口は ISyncIo にして、テストは偽物を渡す。Dropbox.cs は呼ぶだけ(直さない)。C# 5。
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using FriendApps;

namespace RequestSender
{
    // ---- Dropbox のパス(アプリのフォルダの直下。(f1e)) ----
    public static class SyncPaths
    {
        public const string Learning = "/学習", Returns = "/送り返し", Updates = "/更新";
        public const string LatestFile = "latest.json", PackFile = "learning.json";
        public const int KeepVersions = 3;
        public static readonly Regex VersionDir = new Regex(@"^\d{8}-\d{6}-[0-9a-f]{8}$");
        public static readonly Regex ZipName = new Regex(@"^[0-9A-Za-z_-]{1,64}__[0-9A-Za-z_-]{1,64}\.zip$");
        public static readonly Regex VerdictName = new Regex(@"^[0-9A-Za-z_-]{1,64}__[^\\/:*?""<>|]{1,100}\.verdict\.json$");

        public static string LearningLatest { get { return Learning + "/" + LatestFile; } }
        public static string UpdateLatest { get { return Updates + "/" + LatestFile; } }
        public static string LearningFile(string version, string rel) { return Learning + "/" + version + "/" + rel; }
        public static string ReturnFile(string name) { return Returns + "/" + name; }
    }

    // Dropbox への口(小さい読み・取る・上げる)。読み・取るは無いとき null / false
    public interface ISyncIo
    {
        byte[] ReadSmall(string path);                 // null = 無い
        bool Download(string path, string localPath);  // false = 無い
        void Upload(string localPath, string path);
        void PutBytes(byte[] data, string path);       // 同じ名前を置き換えて上げる(/設定/届け方.json)
    }

    public class DropboxSyncIo : ISyncIo
    {
        readonly DropboxClient client;
        public DropboxSyncIo(DropboxClient client) { this.client = client; }

        static bool Missing(DropboxException ex) { return ex.Status == 409 && (ex.Body ?? "").Contains("not_found"); }

        public byte[] ReadSmall(string path)
        {
            try { bool cut; return client.DownloadHead(path, 1024 * 1024, out cut); }
            catch (DropboxException ex) { if (Missing(ex)) return null; throw; }
        }

        public bool Download(string path, string localPath)
        {
            try { client.DownloadFile(path, null, localPath, null); return true; }
            catch (DropboxException ex) { if (Missing(ex)) return false; throw; }
        }

        public void Upload(string localPath, string path)
        {
            client.UploadFile(localPath, path, null);
        }

        public void PutBytes(byte[] data, string path)
        {
            client.UploadBytes(data, path, true);
        }
    }

    public class UpdateInfo
    {
        public string Version, File, Sha256, Notes;
        public long Size;
    }

    public class SyncResult
    {
        public string LearningVersion;    // 取った(または既にあった)最新の版。null = 変わらず
        public bool LearningApplied;      // machine の learningDir を向けた
        public bool LearningSkipped;      // 束を作る側の PC なので取らず・向けなかった(Sync.MakerPc)
        public int Uploaded, UploadFailed;
        public int DeliverBatchUploaded;  // 届け方の知らせを上げた値(0 = 上げなかった)
        public UpdateInfo Update;         // 自分より新しい版があるとき
        public List<string> Problems = new List<string>();
    }

    public static class Sync
    {
        // F4b の Setup が入れ替えを行う口(あれば帯の「更新する」から呼ばれる。無ければ知らせるだけ)
        public static Action<UpdateInfo> UpdateHandler;

        // ---- 純粋な部分(テスト) ----
        // "0.58.0" と "0.59.1" の比較。数字でない部分は 0。-1 / 0 / 1
        public static int CompareVersion(string a, string b)
        {
            var pa = Parts(a); var pb = Parts(b);
            for (int i = 0; i < Math.Max(pa.Length, pb.Length); i++)
            {
                int x = i < pa.Length ? pa[i] : 0, y = i < pb.Length ? pb[i] : 0;
                if (x != y) return x < y ? -1 : 1;
            }
            return 0;
        }

        static int[] Parts(string v)
        {
            return (v ?? "").Trim().Split('.').Select(s => { int n; return int.TryParse(s, out n) ? n : 0; }).ToArray();
        }

        // 束の中のパスとして安全か(.. ・絶対パス・ドライブ・バックスラッシュは断る)
        public static bool SafeRel(string rel)
        {
            if (string.IsNullOrEmpty(rel) || rel.Length > 200 || rel.IndexOf('\\') >= 0 || rel.IndexOf(':') >= 0 || rel.StartsWith("/")) return false;
            return rel.Split('/').All(p => p.Length > 0 && p != "." && p != "..");
        }

        public static string Sha256Hex(string path)
        {
            using (var fs = File.OpenRead(path))
            using (var h = SHA256.Create())
                return string.Concat(h.ComputeHash(fs).Select(b => b.ToString("x2")));
        }

        // 版のフォルダ名の一覧から、残す keep 版を除いた「消す物」(新しい順に並べた後ろ)
        public static List<string> ToPrune(IEnumerable<string> names, int keep)
        {
            return names.Where(n => SyncPaths.VersionDir.IsMatch(n)).OrderByDescending(n => n, StringComparer.Ordinal).Skip(keep).ToList();
        }

        public static string LearningRoot(string dataRoot) { return Path.Combine(dataRoot, "learning"); }

        // 学習の束を作る側の PC(ユーザーの PC)か = <dataRoot>\app\prefs.json の intake.folder(依頼の受付のフォルダ)が空でない。
        // 束はその PC の入口が <intake.folder>\学習 に作る。友人の PC の ② は画面なしで受付の設定を持たないので真にならない(② flow/learning.maker_pc と同じ条件。6d-1)
        public static bool MakerPc(string dataRoot)
        {
            if (string.IsNullOrEmpty(dataRoot)) return false;
            string f = Json.Str(Json.Dict(Json.ReadFileOrNull(Path.Combine(dataRoot, "app", "prefs.json")), "intake"), "folder");
            return f != null && f.Trim().Length > 0;
        }

        // ---- 学習の束 ----
        // latest.json の版が新しければ取る。-> 最新の版(取った・既にあった)。Dropbox に無ければ null。完全に取れなければ例外
        public static string FetchLearning(ISyncIo io, string learnRoot, Action<string> log)
        {
            var raw = io.ReadSmall(SyncPaths.LearningLatest);
            if (raw == null) return null;
            string version = Json.Str(Json.Parse(Encoding.UTF8.GetString(raw)), "version") ?? "";
            if (!SyncPaths.VersionDir.IsMatch(version)) throw new InvalidDataException("学習の latest.json の版の形が違います: " + version);
            string final = Path.Combine(learnRoot, version);
            if (File.Exists(Path.Combine(final, SyncPaths.PackFile))) return version;   // 取り済み(learning.json は最後に置く = あれば完成)

            Directory.CreateDirectory(learnRoot);
            string tmp = Path.Combine(learnRoot, version + ".part");
            if (Directory.Exists(tmp)) Directory.Delete(tmp, true);
            Directory.CreateDirectory(tmp);
            try
            {
                string packLocal = Path.Combine(tmp, SyncPaths.PackFile);
                if (!io.Download(SyncPaths.LearningFile(version, SyncPaths.PackFile), packLocal))
                    throw new InvalidDataException("学習の束 " + version + " の learning.json が Dropbox にありません(同期の途中かもしれません)");
                var pack = Json.ReadFileOrNull(packLocal);
                foreach (var f in Json.List(pack, "files"))
                {
                    string rel = Json.Str(f, "path") ?? "", sha = (Json.Str(f, "sha256") ?? "").ToLowerInvariant();
                    long size = Json.Long(f, "size", -1);
                    if (!SafeRel(rel)) throw new InvalidDataException("学習の束のファイル名が安全ではありません: " + rel);
                    string local = Path.Combine(tmp, rel.Replace('/', Path.DirectorySeparatorChar));
                    Directory.CreateDirectory(Path.GetDirectoryName(local));
                    if (!io.Download(SyncPaths.LearningFile(version, rel), local))
                        throw new InvalidDataException("学習の束のファイルが Dropbox にありません: " + rel);
                    if ((size >= 0 && new FileInfo(local).Length != size) || Sha256Hex(local) != sha)
                        throw new InvalidDataException("学習の束のファイルが壊れています(hash が合いません): " + rel);
                    log("learning: got " + rel);
                }
                Directory.Move(tmp, final);
            }
            catch
            {
                try { if (Directory.Exists(tmp)) Directory.Delete(tmp, true); } catch (Exception) { }
                throw;
            }
            Prune(learnRoot, log);
            return version;
        }

        static void Prune(string learnRoot, Action<string> log)
        {
            try
            {
                var names = Directory.GetDirectories(learnRoot).Select(Path.GetFileName);
                foreach (var old in ToPrune(names, SyncPaths.KeepVersions))
                {
                    try { Directory.Delete(Path.Combine(learnRoot, old), true); log("learning: pruned " + old); }
                    catch (Exception ex) { log("learning: prune failed " + old + ": " + ex.Message); }
                }
            }
            catch (Exception ex) { log("learning: prune " + ex.Message); }
        }

        // 向け先の記録 <learnRoot>\current.json {version, applied}。② が動いていない回は applied false のまま残し、次の回で向ける
        public static bool ApplyLearning(string learnRoot, string version, Func<string, object, FlowReply> put, Action<string> log)
        {
            string rec = Path.Combine(learnRoot, "current.json");
            var cur = Json.ReadFileOrNull(rec);
            bool already = cur != null && Json.Str(cur, "version") == version && Json.Bool(cur, "applied");
            if (already) return true;
            bool ok = false;
            if (put != null)
            {
                var r = put("/api/flow/machine", new Dictionary<string, object> { { "learningDir", Path.Combine(learnRoot, version) } });
                ok = r != null && r.Ok;
                if (!ok) log("learning: machine put failed: " + (r == null ? "-" : r.Message));
            }
            File.WriteAllText(rec, Json.Pretty(new Dictionary<string, object> { { "version", version }, { "applied", ok } }), new UTF8Encoding(false));
            return ok;
        }

        // ---- 送り返し ----
        // ② の outbox の zip(と verdict.json)を上げ、上がったら done。-> 上げた数。失敗した物は残る(次の回で再送)
        public static int SendReturns(ISyncIo io, IFlowClient flow, string outboxDir, Action<string> log, out int failed)
        {
            int ok = 0; failed = 0;
            var list = flow.Get("/api/flow/outbox");
            if (!list.Ok) { log("outbox: " + list.Message); return 0; }
            foreach (var f in Json.List(list.Body, "files"))
            {
                string id = Json.Str(f, "id") ?? "";
                if (!SyncPaths.ZipName.IsMatch(id)) continue;
                string local = Path.Combine(outboxDir, id);
                if (!File.Exists(local)) continue;
                try
                {
                    io.Upload(local, SyncPaths.ReturnFile(id));
                    var d = flow.Post("/api/flow/outbox/done", new Dictionary<string, object> { { "id", id } });
                    if (!d.Ok) log("outbox: done failed " + id + ": " + d.Message);   // 上がっている。次の回でもう一度上げて done する
                    ok++;
                }
                catch (CanceledException) { throw; }
                catch (Exception ex) { failed++; log("outbox: upload failed " + id + ": " + ex.Message); }
            }
            // 採否(アプリが outbox に直に書く <requestId>__<pack>.verdict.json)。上げたら 済み/ へ
            try
            {
                if (Directory.Exists(outboxDir))
                    foreach (var p in Directory.GetFiles(outboxDir, "*.verdict.json"))
                    {
                        string name = Path.GetFileName(p);
                        if (!SyncPaths.VerdictName.IsMatch(name)) continue;
                        try
                        {
                            io.Upload(p, SyncPaths.ReturnFile(name));
                            string done = Path.Combine(outboxDir, "済み");
                            Directory.CreateDirectory(done);
                            string to = Path.Combine(done, name);
                            if (File.Exists(to)) File.Delete(to);
                            File.Move(p, to);
                            ok++;
                        }
                        catch (CanceledException) { throw; }
                        catch (Exception ex) { failed++; log("outbox: verdict upload failed " + name + ": " + ex.Message); }
                    }
            }
            catch (IOException ex) { log("outbox: " + ex.Message); }
            return ok;
        }

        // ---- 更新の確認 ----
        // /更新/latest.json {version, file, size, sha256, notes} が current より新しければ返す
        public static UpdateInfo CheckUpdate(ISyncIo io, string current)
        {
            var raw = io.ReadSmall(SyncPaths.UpdateLatest);
            if (raw == null) return null;
            var d = Json.Parse(Encoding.UTF8.GetString(raw));
            string v = Json.Str(d, "version") ?? "";
            if (v.Length == 0 || CompareVersion(v, current) <= 0) return null;
            return new UpdateInfo { Version = v, File = Json.Str(d, "file"), Sha256 = Json.Str(d, "sha256"), Notes = Json.Str(d, "notes"), Size = Json.Long(d, "size", 0) };
        }

        // ---- 届け方の知らせ(D-SEND 2-4) ----
        // 値が前回上げたものと違うとき(まだ上げていないときも)/設定/届け方.json を置き換えて上げる。失敗は例外のまま返す(呼んだ側が覚えない = 次の回で上げ直す)。-> 上げた値(上げなかったら 0)
        public static int UploadDeliverPrefs(ISyncIo io, int batch, int lastUploaded, DateTimeOffset now)
        {
            if (!DeliverPrefs.NeedsUpload(batch, lastUploaded)) return 0;
            io.PutBytes(new UTF8Encoding(false).GetBytes(DeliverPrefs.Json(batch, now)), DeliverPrefs.Path);
            return batch;
        }

        // 画面の「届け方」の今の値と前回上げた値。saved は上げられたときに呼ぶ(前回上げた値を settings に覚える)
        public class DeliverSync
        {
            public int Batch, LastUploaded;
            public Action<int> Saved;
        }

        // 4 つを順に(1 つの失敗でほかを止めない)
        public static SyncResult RunAll(ISyncIo io, IFlowClient flow, Func<string, object, FlowReply> put, string dataRoot, string currentVersion, Action<string> log, DeliverSync deliver = null)
        {
            var r = new SyncResult();
            if (deliver != null)
                try
                {
                    int up = UploadDeliverPrefs(io, deliver.Batch, deliver.LastUploaded, DateTimeOffset.Now);
                    if (up > 0) { r.DeliverBatchUploaded = up; if (deliver.Saved != null) deliver.Saved(up); log("deliver prefs: uploaded " + up); }
                }
                catch (CanceledException) { throw; }
                catch (Exception ex) { r.Problems.Add("届け方: " + ex.Message); log("deliver prefs: " + ex.Message); }   // 覚えない = 次の回で上げ直す
            string learnRoot = LearningRoot(dataRoot);
            if (MakerPc(dataRoot)) { r.LearningSkipped = true; log("learning: maker PC (intake.folder is set), not fetched or applied"); }   // 自分の束を自分の ② に向けない(二重の守りの片方)
            else try
            {
                string v = FetchLearning(io, learnRoot, log);
                if (v != null) { r.LearningVersion = v; r.LearningApplied = ApplyLearning(learnRoot, v, put, log); }
            }
            catch (CanceledException) { throw; }
            catch (Exception ex) { r.Problems.Add("学習: " + ex.Message); log("learning: " + ex.Message); }
            if (flow != null)
                try
                {
                    int failed;
                    r.Uploaded = SendReturns(io, flow, LocalPacks.OutboxDir(dataRoot), log, out failed);   // この PC のパックの採否も同じ所(LocalPacks.cs)
                    r.UploadFailed = failed;
                }
                catch (CanceledException) { throw; }
                catch (Exception ex) { r.Problems.Add("送り返し: " + ex.Message); log("outbox: " + ex.Message); }
            try { r.Update = CheckUpdate(io, currentVersion); }
            catch (CanceledException) { throw; }
            catch (Exception ex) { r.Problems.Add("更新: " + ex.Message); log("update: " + ex.Message); }
            return r;
        }
    }

    // ---- 画面への配線(起動 5 秒後と 10 分ごと。帯 1 行) ----
    public partial class MainForm
    {
        const int SyncFirstMs = 5000, SyncEveryMs = 10 * 60 * 1000;
        readonly System.Windows.Forms.Timer syncTimer = new System.Windows.Forms.Timer();
        readonly Lbl updateLbl = new Lbl("", Tone.Accent);
        UpdateInfo updateInfo;
        int syncRunning;

        void BuildSyncRow()
        {
            if (Offline) return;
            Sync.UpdateHandler = OfferUpdate;   // 帯の「更新する」→ 確かめの小窓 → Setup.DownloadUpdate → Setup.StartUpdate(F6b)
            updateLbl.Font = Theme.Small;
            updateLbl.Cursor = System.Windows.Forms.Cursors.Hand;
            updateLbl.Visible = false;
            updateLbl.Click += (s, e) =>
            {
                if (updateInfo != null && Sync.UpdateHandler != null) Sync.UpdateHandler(updateInfo);
            };
            int at = int.MaxValue;   // 右の列の終わり
            right.Insert(at, updateLbl, 6, true);
            syncTimer.Interval = SyncFirstMs;
            syncTimer.Tick += (s, e) => { syncTimer.Interval = SyncEveryMs; StartSync(); };
            syncTimer.Start();
            Disposed += (s, e) => syncTimer.Dispose();
            // 「届け方」を変えたら少し待って(押し続けている間は待つ)知らせを上げる。起動時に前回と違えば最初の同期(5 秒後)が上げる(D-SEND 2-4)
            deliverPrefsTimer.Interval = 2000;
            deliverPrefsTimer.Tick += (s, e) => { deliverPrefsTimer.Stop(); StartSync(); };
            Disposed += (s, e) => deliverPrefsTimer.Dispose();
        }

        readonly System.Windows.Forms.Timer deliverPrefsTimer = new System.Windows.Forms.Timer();

        // 届け方の値が変わった(MainForm.cs の deliver.ValueChanged から)。前回上げた値と同じなら何もしない。同期が動いていたら次の回(10 分後)に回る
        void OnDeliverBatchChanged()
        {
            if (Offline || !built || !DeliverPrefs.NeedsUpload(deliver.Value, state.LoadDeliverBatchUploaded())) return;
            deliverPrefsTimer.Stop();
            deliverPrefsTimer.Start();
        }

        void StartSync()
        {
            if (Interlocked.CompareExchange(ref syncRunning, 1, 0) != 0) return;
            var config = LoadConfig(null);
            if (config == null) { syncRunning = 0; return; }   // 鍵が無い = 同期しない(送る側のメッセージが別に出る)
            var b = backend;
            int batch = deliver != null ? deliver.Value : 0;   // 画面の値は画面のスレッドで読む
            var t = new Thread(() =>
            {
                try
                {
                    var io = new DropboxSyncIo(new DropboxClient(config) { IsCanceled = () => IsDisposed, Log = Log.Write });
                    bool up = b != null && b.Ready;
                    string root = b != null ? b.DataRoot : Backend.DefaultDataRoot();
                    var r = Sync.RunAll(io, up ? b : null, up ? (Func<string, object, FlowReply>)b.Put : null, root, AppInfo.Version, Log.Write,
                        new Sync.DeliverSync { Batch = batch, LastUploaded = state.LoadDeliverBatchUploaded(), Saved = n => state.SaveDeliverBatchUploaded(n) });
                    OnUi(() => ShowUpdate(r.Update));
                }
                catch (CanceledException) { }
                catch (Exception ex) { Log.Write("sync: " + ex.Message); }
                finally { syncRunning = 0; }
            }) { IsBackground = true, Name = "sync" };
            t.Start();
        }

        bool updating;

        // 「更新する」: 送る・受け取る・この PC の処理の途中なら「終わってから」(帯の文だけ)。でなければ確かめの小窓 1 つ → 取る → 入れ替え(アプリは閉じて開き直す)
        void OfferUpdate(UpdateInfo u)
        {
            if (u == null || updating || IsDisposed) return;
            string why = UpdateBlocker(Busy, RecvBusy, flow);
            if (why != null) { updateLbl.Text = why; return; }
            string notes = string.IsNullOrWhiteSpace(u.Notes) ? "" : "\n\n" + Validation.Shorten(u.Notes.Trim(), 300);
            if (System.Windows.Forms.MessageBox.Show(this, "新しい版 " + u.Version + "(" + Setup.Mb(u.Size) + ")に更新します。" + notes +
                    "\n\n取ってきたらアプリを閉じて入れ替え、自動で開き直します。この PC の処理の部品も止めます(待っていた依頼は次に開いたとき続きから)。よろしいですか?",
                    "更新する", System.Windows.Forms.MessageBoxButtons.OKCancel, System.Windows.Forms.MessageBoxIcon.Question) != System.Windows.Forms.DialogResult.OK) return;
            var config = LoadConfig(text => updateLbl.Text = text);
            if (config == null) return;
            updating = true;
            updateLbl.Text = "更新を取ってきています…";
            string appDir = exeDir;
            var t = new Thread(() =>
            {
                string zip = null, error = null;
                long shownMb = -1;
                try
                {
                    var dbx = new DropboxClient(config) { IsCanceled = () => IsDisposed, Log = Log.Write };
                    zip = Setup.DownloadUpdate(dbx, u.File, u.Size, u.Sha256, appDir, n =>
                    {
                        long mb = n / (1024 * 1024);
                        if (mb == shownMb) return;
                        shownMb = mb;
                        OnUi(() => updateLbl.Text = "更新を取ってきています… " + Setup.Mb(n) + " / " + Setup.Mb(u.Size));
                    });
                }
                catch (CanceledException) { return; }
                catch (Exception ex) { error = ex.Message; Log.Write("update: download " + ex); }
                OnUi(() =>
                {
                    if (error == null)
                        try { updateLbl.Text = "入れ替えています…"; Setup.StartUpdate(zip); return; }
                        catch (Exception ex) { error = ex.Message; Log.Write("update: start " + ex); }
                    updating = false;
                    updateLbl.Text = "更新できませんでした: " + error + "(ここを押すと、もう一度試します)";
                });
            }) { IsBackground = true, Name = "update" };
            t.Start();
        }

        // 更新を止める理由(null = 更新してよい)。テストする
        public static string UpdateBlocker(bool sending, bool receiving, FlowStatus flow)
        {
            if (sending) return "送っている途中です。終わってから、ここを押して更新してください";
            if (receiving) return "受け取っている途中です。終わってから、ここを押して更新してください";
            if (flow != null && !flow.Idle) return "この PC で処理している途中です。終わってから、ここを押して更新してください";
            return null;
        }

        void ShowUpdate(UpdateInfo u)
        {
            if (updating) return;   // 取っている途中の帯の文を消さない
            updateInfo = u;
            updateLbl.Text = u == null ? "" : "新しい版 " + u.Version + " があります。" + (Sync.UpdateHandler != null ? "ここを押して更新する" : "更新は送り先の人に伝えてください");
            updateLbl.Visible = u != null;
        }
    }
}
