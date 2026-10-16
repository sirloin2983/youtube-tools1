// この PC の ② が作ったパックを「受け取る」の一覧に出す(F1 の F6b。設計 notes:docs/design/f1-build.md の F3a・F2 の採否・notes:plan/f1-friend-pc.md の決めたこと 6・11)。
//   一覧の元: ② の GET /api/flow/history(終わった実行の記録。1 行 = Run.public() = packs(作った物 + 鍵で飛ばした前からある物)・requestId・title・finished)。
//             パックはこの PC の案件フォルダにもうある = 取ってこない。フォルダが無くなった物・採否を決めた物は出さない
//   受け取る = 開く(エクスプローラーでフォルダ)/ 要らない(フォルダは消さない)/ 動画にした は、Dropbox の feedback.json ではなく
//             <作業データ>\app\outbox\<requestId>__<パック名>.verdict.json {v:1, verdict, requestId, zip, title, at(ミリ秒)} に書く。
//             Sync.SendReturns がそこから Dropbox の /送り返し/ へ上げて outbox\済み\ へ移す(名前の形は SyncPaths.VerdictName・ユーザーの PC の
//             src/human/friend/returns.py の VERDICT_RE と同じ)。outbox か 済み に同じ名前があれば「決めた」= 一覧に出さない
//   まとめ動画: 案件にあれば(<パック>.preview.mp4 か フォルダの中の *.preview.mp4)小窓で再生。無ければパックの切り抜きの動画(直下でいちばん大きい・_roughcut は除く)
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using FriendApps;

namespace RequestSender
{
    public static class LocalPacks
    {
        public const string VerdictSuffix = ".verdict.json", DoneDir = "済み", PackSuffix = "_pack", PreviewSuffix = ".preview.mp4";
        public const int HistoryLimit = 200, PackNameMax = 100;
        public static readonly string[] Verdicts = { "keep", "reject", "made_video" };
        static readonly Regex RequestIdRx = new Regex("^[0-9A-Za-z_-]{1,64}$");
        static readonly string[] ClipExt = { ".mp4", ".mov", ".mkv", ".webm", ".m4v" };

        public static string OutboxDir(string dataRoot) { return Path.Combine(dataRoot, "app", "outbox"); }

        public static string HistoryPath { get { return "/api/flow/history?limit=" + HistoryLimit; } }

        // 送り返しの名前に入れるパック名(フォルダの名前。使えない文字は _・長さは PackNameMax まで)
        public static string PackName(string packDir)
        {
            string n = Path.GetFileName((packDir ?? "").TrimEnd('\\', '/')) ?? "";
            var sb = new StringBuilder();
            foreach (char c in n) sb.Append(c < 0x20 || "\\/:*?\"<>|".IndexOf(c) >= 0 ? '_' : c);
            n = sb.ToString().Trim();
            return n.Length > PackNameMax ? n.Substring(0, PackNameMax).Trim() : n;
        }

        // 題(<題>_pack の <題>)
        public static string Title(string packName)
        {
            return packName.EndsWith(PackSuffix, StringComparison.Ordinal) && packName.Length > PackSuffix.Length ? packName.Substring(0, packName.Length - PackSuffix.Length) : packName;
        }

        // 送り返しの依頼の id: 実行の requestId(形が合えば)か、無ければ実行の id
        public static string RequestIdOf(string requestId, string runId)
        {
            if (requestId != null && RequestIdRx.IsMatch(requestId)) return requestId;
            return runId != null && RequestIdRx.IsMatch(runId) ? runId : "local";
        }

        public static string VerdictFileName(string requestId, string packName)
        {
            return requestId + "__" + packName + VerdictSuffix;
        }

        // origin = 出どころ request|auto(D-SEND 2-7。分かるときだけ書く。この PC の ② が作ったパックは分からない)
        public static string VerdictJson(string verdict, string requestId, string packName, string title, long atMs, string origin = "")
        {
            if (Array.IndexOf(Verdicts, verdict) < 0) throw new ArgumentException("verdict: " + verdict);
            return "{\"v\":1,\"verdict\":" + JsonText.Quote(verdict, false) + ",\"requestId\":" + JsonText.Quote(requestId ?? "", false) +
                   ",\"zip\":" + JsonText.Quote(packName ?? "", false) + ",\"title\":" + JsonText.Quote(title ?? "", false) +
                   OriginKind.JsonPart(origin) + ",\"at\":" + atMs.ToString(CultureInfo.InvariantCulture) + "}";
        }

        public static long NowMs(DateTimeOffset now)
        {
            return now.ToUnixTimeMilliseconds();
        }

        // 採否を決めたか(outbox か 済み に同じ名前の verdict.json がある)
        public static bool Decided(string outboxDir, string requestId, string packName)
        {
            string n = VerdictFileName(requestId, packName);
            return File.Exists(Path.Combine(outboxDir, n)) || File.Exists(Path.Combine(outboxDir, DoneDir, n));
        }

        // outbox に書く(一時の名前に書いてから置き換え = Sync が書きかけを上げない)。-> 書いたパス
        public static string WriteVerdict(string outboxDir, OutputEntry e, string verdict, DateTimeOffset now)
        {
            Directory.CreateDirectory(outboxDir);
            string path = Path.Combine(outboxDir, VerdictFileName(e.RequestId, e.Name));
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, VerdictJson(verdict, e.RequestId, e.Name, e.Title, NowMs(now), e.Origin), new UTF8Encoding(false));
            if (File.Exists(path)) File.Delete(path);
            File.Move(tmp, path);
            return path;
        }

        // history の返事 → 一覧の行(新しい順・同じフォルダは 1 つ)。exists = フォルダがあるか / decided(requestId, パック名) / sizeOf・previewOf はフォルダから(null = 0・なし)
        public static List<OutputEntry> FromHistory(IDictionary<string, object> history, Func<string, bool> exists, Func<string, string, bool> decided,
                                                    Func<string, long> sizeOf, Func<string, string> previewOf)
        {
            var list = new List<OutputEntry>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var r in Json.List(history, "runs"))
            {
                string runId = Json.Str(r, "id") ?? "", rid = RequestIdOf(Json.Str(r, "requestId"), runId);
                long finished = Json.Long(r, "finished", 0);
                foreach (string raw in Strings(r, "packs"))
                {
                    string dir;
                    try { dir = Path.GetFullPath(raw); }
                    catch (Exception) { continue; }
                    dir = dir.TrimEnd('\\');
                    string name = PackName(dir);
                    if (name.Length == 0 || !seen.Add(dir) || !exists(dir) || decided(rid, name)) continue;
                    list.Add(new OutputEntry
                    {
                        Kind = OutputKind.Pack, Local = true, Name = name, PathLower = "local:" + dir.ToLowerInvariant(), Rev = runId,
                        RequestId = rid, RunId = runId, Title = Title(name), LocalPath = dir,
                        Size = sizeOf != null ? sizeOf(dir) : 0, LocalPreview = previewOf != null ? previewOf(dir) : null,
                        Modified = finished > 0 ? DateTimeOffset.FromUnixTimeMilliseconds(finished).LocalDateTime : DateTime.MinValue,
                    });
                }
            }
            return list;
        }

        static IEnumerable<string> Strings(IDictionary<string, object> d, string key)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v is string) yield break;
            var list = v as IEnumerable;
            if (list == null) yield break;
            foreach (object o in list)
            {
                var s = o as string;
                if (!string.IsNullOrWhiteSpace(s)) yield return s;
            }
        }

        // ---- ファイルの側(画面が使う。テストは一時フォルダで)----
        public static long DirSize(string dir)
        {
            try { return new DirectoryInfo(dir).EnumerateFiles("*", SearchOption.AllDirectories).Sum(f => f.Length); }
            catch (Exception) { return 0; }
        }

        // まとめ動画: <パック>.preview.mp4(隣)→ フォルダの中の *.preview.mp4 → 切り抜きの動画(直下でいちばん大きい・_roughcut は除く)。無ければ null
        public static string FindPreview(string dir)
        {
            try
            {
                string beside = dir.TrimEnd('\\') + PreviewSuffix;
                if (File.Exists(beside)) return beside;
                string inside = Directory.GetFiles(dir, "*" + PreviewSuffix).OrderBy(x => x, StringComparer.OrdinalIgnoreCase).FirstOrDefault();
                if (inside != null) return inside;
                return new DirectoryInfo(dir).GetFiles()
                    .Where(f => ClipExt.Contains(f.Extension.ToLowerInvariant()) && !Path.GetFileNameWithoutExtension(f.Name).EndsWith("_roughcut", StringComparison.OrdinalIgnoreCase))
                    .OrderByDescending(f => f.Length).Select(f => f.FullName).FirstOrDefault();
            }
            catch (Exception) { return null; }
        }

        public static List<OutputEntry> Read(IDictionary<string, object> history, string outboxDir)
        {
            return FromHistory(history, Directory.Exists, (rid, name) => Decided(outboxDir, rid, name), DirSize, FindPreview);
        }
    }

    // ---- 画面の側(受け取るの一覧に混ぜる)----
    public partial class MainForm
    {
        List<OutputEntry> dropboxEntries = new List<OutputEntry>(), localEntries = new List<OutputEntry>();
        bool localRefreshing;
        int localDoneSeen = -1;

        static bool IsLocal(OutputEntry e)
        {
            return e != null && e.Local;
        }

        string LocalOutbox { get { return LocalPacks.OutboxDir(backend != null ? backend.DataRoot : Backend.DefaultDataRoot()); } }

        // ② の終わった実行の記録からこの PC のパックを読み直す(裏の糸)。② が動いていなければ何もしない
        void RefreshLocal()
        {
            if (Offline || backend == null || !backend.Running || localRefreshing || IsDisposed) return;
            localRefreshing = true;
            var b = backend;
            string outbox = LocalOutbox;
            var t = new Thread(() =>
            {
                List<OutputEntry> got = null;
                try
                {
                    var r = b.Get(LocalPacks.HistoryPath);
                    if (r.Ok) got = LocalPacks.Read(r.Body, outbox);
                    else Log.Write("local packs: " + r.Message);
                }
                catch (Exception ex) { Log.Write("local packs: " + ex.GetType().Name + ": " + ex.Message); }
                OnUi(() => { localRefreshing = false; if (got != null) ShowLocal(got); });
            }) { IsBackground = true, Name = "local-packs" };
            t.Start();
        }

        // ② の状態で、終わった数が変わったら読み直す(ShowFlow から)
        void LocalOnFlow(FlowStatus s)
        {
            if (s == null || s.Done == localDoneSeen) return;
            localDoneSeen = s.Done;
            RefreshLocal();
        }

        // テストでも使う(通信しない)
        public void ShowLocal(List<OutputEntry> list)
        {
            if (RecvBusy) return;   // 受け取りの途中は一覧を組み直さない(次の読み直しで出る)
            var keep = SelectedEntry;
            localEntries = list ?? new List<OutputEntry>();
            RebuildEntries(false);
            if (keep != null)
            {
                var again = entries.FirstOrDefault(x => x.Key == keep.Key);
                if (again != null) outList.SelectedItem = again;
            }
        }

        string LocalDetail(OutputEntry e)
        {
            return "この PC で作ったパックです(Dropbox は通りません)。\r\n題: " + e.Title + "\r\n" +
                   (e.RequestId.Length > 0 ? "依頼: " + e.RequestId + "\r\n" : "") +
                   "場所: " + e.LocalPath + "\r\n大きさ: " + SizeText(e.Size) + "\r\nできた日時: " + When(e.Modified) + "\r\n" +
                   "まとめ動画: " + (e.LocalPreview != null ? Path.GetFileName(e.LocalPreview) + "(「まとめ動画を見る」で再生)" : "なし") + "\r\n\r\n" +
                   "「開く」でフォルダを開きます(受け取った印になります)。要らなければ「要らない」で一覧から外します(フォルダは消しません)。" +
                   "決めたことは送り先の人に伝わります。";
        }

        // 受け取る = 開く(keep を書いて一覧から外す)
        void OpenLocal(OutputEntry e)
        {
            if (!Directory.Exists(e.LocalPath)) { SetRecvStatus("フォルダが見つかりません(動かした・消した?): " + e.LocalPath, true); RemoveEntry(e); return; }
            try { Process.Start("explorer.exe", "\"" + e.LocalPath + "\""); }
            catch (Exception ex) { SetRecvStatus("フォルダを開けませんでした: " + ex.Message, true); return; }
            lastDownloaded = e.LocalPath;
            bool ok = DecideLocal(e, "keep");
            RemoveEntry(e);
            SetRecvStatus("開きました ✓  " + e.Name + (ok ? "" : "(受け取った印は書けませんでした)"), !ok, ok);
        }

        void DiscardLocal(OutputEntry e)
        {
            if (MessageBox.Show(this, "このパックを一覧から外します(要らなかったことは送り先の人に伝わります。フォルダは消しません)。よろしいですか?\n(" + e.Title + ")",
                    "要らない", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
            bool ok = DecideLocal(e, "reject");
            RemoveEntry(e);
            SetRecvStatus(ok ? "一覧から外しました(フォルダは " + e.LocalPath + " に残っています)" : "一覧から外しました(送り先の人への記録は書けませんでした)", !ok);
        }

        void MadeVideoLocal(OutputEntry e)
        {
            bool ok = DecideLocal(e, "made_video");
            if (ok) RemoveEntry(e);
            SetRecvStatus(ok ? "動画にしたことを送り先の人に知らせます(次の同期で送ります)" : "知らせを書けませんでした。もう一度押してください", !ok);
        }

        bool DecideLocal(OutputEntry e, string verdict)
        {
            try
            {
                string p = LocalPacks.WriteVerdict(LocalOutbox, e, verdict, DateTimeOffset.Now);
                Log.Write("local verdict: " + verdict + " " + Path.GetFileName(p));
                return true;
            }
            catch (Exception ex)
            {
                Log.Write("local verdict failed: " + ex.GetType().Name + ": " + ex.Message);
                return false;
            }
        }
    }
}
