// 受け取る: PC が「/出力/」に置いたパック(.zip)と失敗の知らせ(.失敗.txt)を一覧にして(まとめ動画 .preview.mp4 はパックに結びつける)、
// 選んだものを取ってくる(1 本ずつ・「すべて受け取る」でまとめて)。受け取った zip は保存先に展開して zip は消す(ExtractZip)。
// Dropbox から消すのは、受け取り終えたパック(大きさと hash を確かめたあと)・「要らない」としたパック・読み終えた失敗の知らせだけ
// (files/delete_v2。鍵に files.content.write。パックの隣のまとめ動画も一緒に消す)。一覧には読みの権限が要る(files.metadata.read・files.content.read)。
// 2.8.0: 組(.group.json = まとめ動画 1 本 + 1 本ずつの zip)を読んで一覧に組の行を出す。組の最後の 1 本を片付けたら .group.json と組のまとめ動画も消す
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using FriendApps;

namespace RequestSender
{
    public class OutputListing
    {
        public List<OutputEntry> Entries = new List<OutputEntry>();
        public bool FolderMissing;   // 「/出力」がまだ無い(= まだ何も届いていない)
    }

    // 「すべて受け取る」の結果(画面がまとめの文を出す材料。Summary は通信しないのでテストできる)
    public class ReceiveAllResult
    {
        public int Total;                                           // 受け取ろうとしたパックの数
        public List<OutputEntry> Done = new List<OutputEntry>();    // 受け取って Dropbox からも消したもの(一覧から外す)
        public List<OutputEntry> Kept = new List<OutputEntry>();    // 受け取ったが Dropbox から消せなかったもの(一覧に残す。次の更新でまた出る)
        public List<string> Failed = new List<string>();            // 受け取れなかった題(そのファイルだけの問題。飛ばして次へ進んだ)
        public List<string> NotExtracted = new List<string>();      // 受け取れたが展開できなかった題(zip のまま保存先にある)
        public bool Canceled;
        public Exception Error;                                     // 通信・鍵・保存先の問題で途中で止めた(言い方は画面が決める)
        public string LastPath;

        public int Received { get { return Done.Count + Kept.Count; } }

        // 全部を受け取り・展開し・Dropbox からも消せた(画面は進み具合を満たして、文を成功の色に)
        public bool Clean
        {
            get { return Error == null && !Canceled && Failed.Count == 0 && Kept.Count == 0 && NotExtracted.Count == 0; }
        }

        // 友人が手を動かす必要のある問題があった(画面は文をエラーの色に。やめた・消せなかっただけなら違う)
        public bool HasProblem
        {
            get { return Error != null || Failed.Count > 0 || NotExtracted.Count > 0; }
        }

        // まとめの文。errorText = Error を画面の言い方にしたもの(Error が無ければ null)
        public string Summary(string errorText)
        {
            string n = Received + " / " + Total + " 本";
            string s;
            if (Canceled) s = "やめました(" + n + "は受け取り済み)。";
            else if (Error != null) s = n + "を受け取ったところで止まりました: " + (errorText ?? Error.Message);
            else if (Failed.Count == 0) s = Total + " 本すべて受け取りました ✓  「フォルダを開く」で見られます。";
            else s = n + "を受け取りました。受け取れなかった " + Failed.Count + " 本: " + string.Join("・", Failed.Take(3)) + (Failed.Count > 3 ? " ほか" : "") +
                     "(「更新」のあと、もう一度「すべて受け取る」を押してください)";
            if (Kept.Count > 0) s += " Dropbox から消せなかった " + Kept.Count + " 本は、次に更新したときにまた出ます。";
            if (NotExtracted.Count > 0) s += " 展開できなかった " + NotExtracted.Count + " 本は zip のまま保存先にあります(右クリック →「すべて展開」)。";
            return s;
        }
    }

    // 何本かをまとめて「要らない」にした結果
    public class DiscardAllResult
    {
        public List<OutputEntry> Done = new List<OutputEntry>();   // 記録を置いて(置けなくても)Dropbox から消したもの
        public int NotRecorded;                                    // そのうち記録を置けなかった数(送り先の人に伝わらない)
        public Exception Error;                                    // 途中で止まった理由(無ければ null)
    }

    // パック 1 本を受け取った結果(受け取り = 大きさと hash の確認までは済んでいる)
    public class ReceiveOneResult
    {
        public string Zip;            // 受け取った zip(展開できたら、もう無い)
        public string Placed;         // 保存先に置いたもの: 展開したフォルダ。展開しない・できなかったときは Zip
        public string ExtractError;   // 展開できなかった理由(展開しない・できたときは null)
        public bool Deleted;          // Dropbox からも消せた(消せなければ次の更新でまた一覧に出る)

        public bool Extracted { get { return Placed != Zip; } }
    }

    public class Receiving
    {
        const int MaxPages = 50;   // 1回 500 件 × 50。止まらない返事への備え
        readonly DropboxClient client, deleter;
        public bool ExtractZip = true;   // 受け取った zip を保存先に展開して zip は消す(settings.json の extractZip。既定オン)

        // まとめ動画を取ってくる場所(受け取るものではないので保存先には置かない)
        public static string PreviewDir()
        {
            return Path.Combine(Path.GetTempPath(), "RequestSender", "previews");
        }

        // deleter = 消すときだけ使う別のつながり(「やめる」で止まらないもの)。無ければ client で消す
        public Receiving(DropboxClient client, DropboxClient deleter = null)
        {
            this.client = client;
            this.deleter = deleter ?? client;
        }

        public OutputListing List()
        {
            var r = new OutputListing();
            IDictionary<string, object> d;
            try
            {
                d = client.Rpc("files/list_folder", DropboxArgs.ListFolder(OutputFolder.Path));
            }
            catch (DropboxException ex)
            {
                if (!ErrorText.IsNotFound(ex.Status, ex.Body)) throw;
                r.FolderMissing = true;
                return r;
            }
            for (int page = 0; ; page++)
            {
                r.Entries.AddRange(OutputFolder.ParseEntries(d));
                string cursor = Json.Str(d, "cursor");
                if (!(Json.Bool(d, "has_more") && !string.IsNullOrEmpty(cursor)) || page >= MaxPages) break;
                d = client.Rpc("files/list_folder/continue", DropboxArgs.ListContinue(cursor));
            }
            foreach (var g in r.Entries.Where(e => e.Kind == OutputKind.Group)) g.Info = ReadGroup(g);
            r.Entries = OutputFolder.Arrange(r.Entries);   // 組(2.8.0)に zip とまとめ動画を結びつけ、まとめ動画は同じ名前のパックに結びつける(一覧には出さない)。新しい順
            return r;
        }

        // 読んだ組の一覧(鍵 = 名前と rev。置き直されたら読み直す)。3 分ごとの確認で同じものを取り直さない
        static readonly Dictionary<string, GroupInfo> groupCache = new Dictionary<string, GroupInfo>();

        // .group.json の中身(64KB まで)。大きすぎる・壊れている・もう無いときは null(その組は出さず、中の zip は 1 本ずつの行になる)。
        // 通信の失敗も null(次の確認で読み直す)。「やめる」・窓を閉じたときは止める
        GroupInfo ReadGroup(OutputEntry g)
        {
            lock (groupCache) { GroupInfo cached; if (groupCache.TryGetValue(g.Key, out cached)) return cached; }
            GroupInfo info = null;
            try
            {
                bool truncated;
                byte[] data = client.DownloadHead(g.ApiPath, OutputFolder.GroupTextCap, out truncated);
                info = truncated ? null : GroupInfo.Parse(data, data.Length);
                if (info == null) client.Log("group: ignored " + g.Name + (truncated ? " (too large)" : " (broken)"));
            }
            catch (DropboxException ex)
            {
                client.Log("group: not read " + g.Name + ": " + ex.Status + " " + ex.Message);
                return null;
            }
            lock (groupCache) groupCache[g.Key] = info;
            return info;
        }

        // まとめ動画(zip の隣の小さい mp4)を dir へ。前に取ってきた同じものがあればそのまま。-> 置いた場所
        public string DownloadPreview(OutputEntry e, string dir, Action<long, long, string> progress)
        {
            var p = e.Preview;
            if (p == null) throw new InvalidOperationException("まとめ動画がありません");
            Directory.CreateDirectory(dir);
            string final = Path.Combine(dir, LocalName.Safe(p.Name));
            if (File.Exists(final) && p.Size > 0 && new FileInfo(final).Length == p.Size) return final;
            FetchViaPart(p, final, n => progress(n, p.Size, "まとめ動画を取ってきています"), null);
            return final;
        }

        public string FailureText(OutputEntry e)
        {
            bool truncated;
            byte[] data = client.DownloadHead(e.ApiPath, OutputFolder.FailureTextCap, out truncated);
            return OutputFolder.DecodeFailureText(data, data.Length, truncated);
        }

        // パックを dir へ(大きさと hash を確かめてから、重ならない名前で置く)。-> 置いた zip。progress(done, total, 段の名前)
        public string Download(OutputEntry e, string dir, Action<long, long, string> progress)
        {
            Directory.CreateDirectory(dir);
            CheckFreeSpace(dir, ExtractZip ? e.Size * 2 : e.Size);   // 展開するときは zip + 中身の分
            string final = LocalName.Unique(dir, LocalName.Safe(e.Name));
            FetchViaPart(e, final, n => progress(n, e.Size, "受け取っています"), part => Verify(e, part, progress));
            return final;
        }

        // src を "<final>.part" に書き、check(part) が通ったら final に名前を変える(final があれば置き換える)。
        // 途中で止まった・check が断ったときは .part を消す
        void FetchViaPart(OutputEntry src, string final, Action<long> progress, Action<string> check)
        {
            string part = final + ".part";
            bool ok = false;
            try
            {
                client.DownloadFile(src.ApiPath, src.Rev, part, progress);
                if (check != null) check(part);
                if (File.Exists(final)) File.Delete(final);
                File.Move(part, final);
                ok = true;
            }
            finally
            {
                if (!ok) TryDelete(part);
            }
        }

        // 受け取ったパックの大きさと content_hash を一覧の値と比べる。合わなければ DropboxException(Status -1 = そのファイルだけの問題)
        static void Verify(OutputEntry e, string part, Action<long, long, string> progress)
        {
            long got = new FileInfo(part).Length;
            if (e.Size > 0 && got != e.Size)
                throw new DropboxException("受け取った大きさが合いません(" + got + " / " + e.Size + " バイト)。もう一度「受け取る」を押してください。", -1, "");
            if (string.IsNullOrEmpty(e.ContentHash)) return;
            string h;
            using (var fs = new FileStream(part, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
                h = ContentHash.Compute(fs, n => progress(n, got, "壊れていないか確かめています"));
            if (!string.Equals(h, e.ContentHash, StringComparison.OrdinalIgnoreCase))
                throw new DropboxException("受け取ったファイルが壊れていました。もう一度「受け取る」を押してください。", -1, "");
        }

        // パック 1 本を受け取る: Download → 展開(ExtractZip のとき)→ Dropbox から消す(隣のまとめ動画も)。
        // 受け取り(大きさと hash の確認)で失敗したら例外。そのあとの展開・消すの失敗は例外にせず結果に書く(受け取りは済んでいるため)。
        // 消すのは deleter なので、「やめる」が押されていても消し終える(消さないと次に更新したときにまた出て、二度受け取ることになる)
        public ReceiveOneResult ReceiveOne(OutputEntry e, string dir, Action<long, long, string> progress)
        {
            var r = new ReceiveOneResult();
            r.Zip = Download(e, dir, progress);
            client.Log("receive: ok " + r.Zip);
            r.Placed = ExtractOrKeep(r.Zip, dir, progress, out r.ExtractError);
            try
            {
                Delete(e);
                r.Deleted = true;
            }
            catch (Exception ex)
            {
                client.Log("receive: delete failed " + e.Name + ": " + ex.Message);
            }
            return r;
        }

        // すべて受け取る: packs を順に ReceiveOne。progress(何本目(1 から), そのパック, 全体で済んだバイト, 全体のバイト, 段の名前)
        // そのファイルだけの問題(大きさが合わない・壊れていた・作り直された = Status が負)は飛ばして次へ。
        // 通信・鍵・保存先(空き)の問題は止める(次も同じ理由で失敗し、やり直しの待ちが積み上がるだけ)。やめたらそこまで
        public ReceiveAllResult DownloadAll(List<OutputEntry> packs, string dir, Action<int, OutputEntry, long, long, string> progress)
        {
            var r = new ReceiveAllResult { Total = packs.Count };
            long all = OutputFolder.TotalSize(packs), before = 0;
            for (int i = 0; i < packs.Count; i++)
            {
                var e = packs[i];
                int no = i + 1;
                long size = Math.Max(0, e.Size), start = before;
                before += size;   // 飛ばしたものも済んだ分に数える(全体の進み具合が戻らないように)
                ReceiveOneResult got;
                try
                {
                    got = ReceiveOne(e, dir, (done, total, step) => progress(no, e, start + Math.Min(done, size), all, step));
                }
                catch (CanceledException) { r.Canceled = true; break; }
                catch (DropboxException ex)
                {
                    if (ex.Status >= 0) { r.Error = ex; break; }
                    r.Failed.Add(e.Title);
                    client.Log("receive all: skip " + e.Name + ": " + ex.Message);
                    continue;
                }
                catch (IOException ex) { r.Error = ex; break; }
                catch (UnauthorizedAccessException ex) { r.Error = ex; break; }
                r.LastPath = got.Placed;
                if (got.ExtractError != null) r.NotExtracted.Add(e.Title);
                (got.Deleted ? r.Done : r.Kept).Add(e);
            }
            return r;
        }

        // 受け取った zip を展開する(ExtractZip のとき)。展開できなければ zip をそのまま残して error に理由。-> 置いたフォルダ(展開しない・できないときは zip)
        public string ExtractOrKeep(string zipPath, string dir, Action<long, long, string> progress, out string error)
        {
            error = null;
            if (!ExtractZip) return zipPath;
            try
            {
                return Extract(zipPath, dir, (done, total) => progress(done, total, "展開しています"));
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is UnauthorizedAccessException || ex is InvalidDataException || ex is NotSupportedException)) throw;
                error = ex.Message;
                client.Log("extract failed " + zipPath + ": " + ex.GetType().Name + ": " + ex.Message);
                return zipPath;
            }
        }

        // zip を dir の中に展開して、展開できたら zip を消す。-> 置いたフォルダ。progress(済んだバイト, 全体のバイト)
        // zip の中身が 1 つのフォルダ(PC が作るパックは <題>_pack の 1 つ)なら、そのフォルダを dir の直下に置く(同じ名前があれば「(2)」)。
        // そうでなければ zip の名前のフォルダに入れる。「<名前>.extracting」に書いてから名前を変える(途中で止まったら消して zip を残す)。
        // 中の名前が外へ出るもの(..・ドライブ名・使えない文字)は断る(zip は Dropbox 経由 = 鍵を知る人なら置けるため)
        public static string Extract(string zipPath, string dir, Action<long, long> progress)
        {
            string target;
            using (var zip = ZipFile.OpenRead(zipPath))
            {
                string top = CommonTopFolder(zip.Entries);
                target = LocalName.Unique(dir, LocalName.Safe(top ?? Path.GetFileNameWithoutExtension(zipPath)));
                string temp = target + ".extracting";
                if (Directory.Exists(temp)) Directory.Delete(temp, true);
                long total = 0, done = 0;
                foreach (var e in zip.Entries) total += Math.Max(0, e.Length);
                bool ok = false;
                try
                {
                    Directory.CreateDirectory(temp);
                    foreach (var e in zip.Entries)
                    {
                        string rel = Relative(e.FullName, top);
                        if (rel.Length == 0) continue;   // 先頭のフォルダそのもの
                        string path = SafeJoin(temp, rel);
                        if (e.FullName.EndsWith("/") || e.FullName.EndsWith("\\")) { Directory.CreateDirectory(path); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                        using (var src = e.Open())
                        using (var dst = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1 << 20))
                        {
                            var buf = new byte[1 << 20];
                            int n;
                            while ((n = src.Read(buf, 0, buf.Length)) > 0)
                            {
                                dst.Write(buf, 0, n);
                                done += n;
                                if (progress != null) progress(done, total);
                            }
                        }
                    }
                    Directory.Move(temp, target);
                    ok = true;
                }
                finally
                {
                    if (!ok) TryDeleteDir(temp);
                }
                if (progress != null) progress(total, total);
            }
            TryDelete(zipPath);   // 消せなくても展開は済んでいる(フォルダの隣に zip が残るだけ)
            return target;
        }

        // 全部の名前が同じ先頭のフォルダの中にあれば、その名前(直下にファイルがある・先頭が 2 つ以上なら null)
        static string CommonTopFolder(IEnumerable<ZipArchiveEntry> entries)
        {
            string top = null;
            foreach (var e in entries)
            {
                string n = e.FullName.Replace('\\', '/').TrimStart('/');
                if (n.Length == 0) continue;
                int i = n.IndexOf('/');
                if (i <= 0) return null;
                string first = n.Substring(0, i);
                if (top == null) top = first;
                else if (!string.Equals(top, first, StringComparison.Ordinal)) return null;
            }
            return top;
        }

        static string Relative(string fullName, string top)
        {
            string n = fullName.Replace('\\', '/').TrimStart('/');
            if (top != null) n = n.Substring(Math.Min(n.Length, top.Length + 1));
            return n.Trim('/');
        }

        // rel を root の中の場所にする。..・絶対パス・ドライブ名・使えない文字は断る
        static string SafeJoin(string root, string rel)
        {
            foreach (string seg in rel.Split('/'))
                if (seg == ".." || seg == "." || seg.Length == 0 || seg.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                    throw new InvalidDataException("zip の中に使えない名前があります: " + rel);
            string full = Path.GetFullPath(Path.Combine(root, rel.Replace('/', Path.DirectorySeparatorChar)));
            string rootFull = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!full.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("zip の中に外へ出る名前があります: " + rel);
            return full;
        }

        // Dropbox の /出力 から消す(パックなら隣のまとめ動画も)。すでに無い(not_found)のは消えているのと同じなので成功とみなす(通信のやり直しの2回目に返る)
        // 受け取らずに消す(「要らない」。2.6.0): 先に記録(<zip>.feedback.json)を受付のフォルダに置き(PC が読んで、切り抜きを片付け・スタジオのマークを不採用に = 誤検出の記録)、
        // それから zip とまとめ動画を消す。記録が置けなくても消す(2026-10-08 ユーザー決定)。-> 記録を置けたか
        public bool Discard(OutputEntry e, DateTimeOffset now)
        {
            bool recorded = true;
            try
            {
                client.UploadBytes(new UTF8Encoding(false).GetBytes(FeedbackJson.Reject(e, now)), FeedbackJson.PathFor(e));
            }
            catch (DropboxException ex)
            {
                recorded = false;
                client.Log("discard: feedback not placed " + e.Name + ": " + ex.Message);
            }
            Delete(e);
            return recorded;
        }

        // 何本かをまとめて「要らない」にする(組の行の「要らない」・まとめ動画の小窓の「残りは要らない」。2.8.0)。1 本ずつ Discard と同じ(記録を置いてから消す)。
        // 通信・鍵の問題・やめたときはそこで止める(Error)。Done = 消したもの(一覧から外す)
        public DiscardAllResult DiscardAll(IEnumerable<OutputEntry> packs, DateTimeOffset now)
        {
            var r = new DiscardAllResult();
            foreach (var e in packs)
            {
                try
                {
                    if (!Discard(e, now)) r.NotRecorded++;
                }
                catch (Exception ex)
                {
                    if (!(ex is DropboxException || ex is CanceledException)) throw;
                    r.Error = ex;
                    break;
                }
                ForgetPreview(e);
                r.Done.Add(e);
            }
            return r;
        }

        // 組の最後の 1 本まで片付けたら(handled = 受け取って Dropbox から消した・要らないにしたもの)、.group.json と組のまとめ動画を Dropbox から消し、写しも消す。
        // 組の途中なら消さない。消せなくても止めない(組に 1 本も残らない .group.json は一覧に出ない)。-> 消した組
        public List<OutputEntry> FinishGroups(IEnumerable<OutputEntry> handled)
        {
            var done = OutputFolder.GroupsDone(handled);
            foreach (var g in done)
            {
                try
                {
                    DeletePath(g.ApiPath);
                    if (g.Preview != null) DeletePath(g.Preview.ApiPath);
                    client.Log("group: finished " + g.Name);
                }
                catch (Exception ex)
                {
                    client.Log("group: not deleted " + g.Name + ": " + ex.GetType().Name + ": " + ex.Message);
                }
                ForgetPreview(g);
            }
            return done;
        }

        // 取ってきたまとめ動画の写し(PreviewDir の中)を消す。受け取った・要らないにしたあとは要らない(2026-10-08 ユーザー決定)。組なら組のまとめ動画
        public static void ForgetPreview(OutputEntry e)
        {
            if (e != null && e.Preview != null) TryDelete(Path.Combine(PreviewDir(), LocalName.Safe(e.Preview.Name)));
        }

        public void Delete(OutputEntry e)
        {
            DeletePath(e.ApiPath);
            if (e.Preview != null) DeletePath(e.Preview.ApiPath);
        }

        void DeletePath(string apiPath)
        {
            try
            {
                deleter.Rpc("files/delete_v2", DropboxArgs.Delete(apiPath));
            }
            catch (DropboxException ex)
            {
                if (!ErrorText.IsNotFound(ex.Status, ex.Body)) throw;
            }
        }

        // 保存先に size バイトと少しの余裕が無ければ IOException(受け取り始める前に。ネットワークの場所・測れない場所は測らない)
        static void CheckFreeSpace(string dir, long size)
        {
            try
            {
                var root = Path.GetPathRoot(Path.GetFullPath(dir));
                if (string.IsNullOrEmpty(root) || root.StartsWith(@"\\")) return;   // ネットワークの場所は測らない
                long free = new DriveInfo(root).AvailableFreeSpace;
                if (free < size + 64L * 1024 * 1024)
                    throw new IOException("保存先(" + root + ")の空きが足りません。あと " + ((size - free) / (1024 * 1024) + 64) + "MB ほど空けるか、保存先を変えてください。");
            }
            catch (ArgumentException) { }
        }

        // 途中のファイル・フォルダの片付け(消せなくても止めない)
        static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        static void TryDeleteDir(string path)
        {
            try { if (Directory.Exists(path)) Directory.Delete(path, true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
