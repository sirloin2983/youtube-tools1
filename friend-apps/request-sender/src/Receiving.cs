// 受け取る: PC が「/出力/」に置いたパック(.zip)と失敗の知らせ(.失敗.txt)を一覧にして、選んだものを取ってくる(1 本ずつ・「すべて受け取る」でまとめて)。
// 受け取り終えたパック(大きさと hash を確かめたあと)・読み終えた失敗の知らせだけ、Dropbox から消す(files/delete_v2。鍵に files.content.write)
// 一覧には読みの権限が要る(files.metadata.read・files.content.read)
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
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

    public class Receiving
    {
        const int MaxPages = 50;   // 1回 500 件 × 50。止まらない返事への備え
        readonly DropboxClient client, deleter;
        public bool ExtractZip = true;   // 受け取った zip を保存先に展開して zip は消す(settings.json の extractZip。既定オン。2.4.0)

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
            r.Entries = OutputFolder.AttachPreviews(r.Entries);   // まとめ動画は同じ名前のパックに結びつける(一覧には出さない)
            OutputFolder.SortNewestFirst(r.Entries);
            return r;
        }

        // まとめ動画(zip の隣の小さい mp4)を dir へ。前に取ってきた同じものがあればそのまま。-> 置いた場所
        public string DownloadPreview(OutputEntry e, string dir, Action<long, long, string> progress)
        {
            var p = e.Preview;
            if (p == null) throw new InvalidOperationException("まとめ動画がありません");
            Directory.CreateDirectory(dir);
            string final = Path.Combine(dir, LocalName.Safe(p.Name));
            if (File.Exists(final) && p.Size > 0 && new FileInfo(final).Length == p.Size) return final;
            string part = final + ".part";
            bool ok = false;
            try
            {
                client.DownloadFile(p.ApiPath, p.Rev, part, n => progress(n, p.Size, "まとめ動画を取ってきています"));
                if (File.Exists(final)) File.Delete(final);
                File.Move(part, final);
                ok = true;
                return final;
            }
            finally
            {
                if (!ok) TryDelete(part);
            }
        }

        public string FailureText(OutputEntry e)
        {
            bool truncated;
            byte[] data = client.DownloadHead(e.ApiPath, OutputFolder.FailureTextCap, out truncated);
            return OutputFolder.DecodeFailureText(data, data.Length, truncated);
        }

        // パックを dir へ。"<名前>.part" に書いてから名前を変える。-> 置いた場所
        // progress(done, total, 段の名前)
        public string Download(OutputEntry e, string dir, Action<long, long, string> progress)
        {
            Directory.CreateDirectory(dir);
            CheckFreeSpace(dir, ExtractZip ? e.Size * 2 : e.Size);   // 展開するときは zip + 中身の分
            string final = LocalName.Unique(dir, LocalName.Safe(e.Name));
            string part = final + ".part";
            bool ok = false;
            try
            {
                client.DownloadFile(e.ApiPath, e.Rev, part, n => progress(n, e.Size, "受け取っています"));
                long got = new FileInfo(part).Length;
                if (e.Size > 0 && got != e.Size)
                    throw new DropboxException("受け取った大きさが合いません(" + got + " / " + e.Size + " バイト)。もう一度「受け取る」を押してください。", -1, "");
                if (!string.IsNullOrEmpty(e.ContentHash))
                {
                    string h;
                    using (var fs = new FileStream(part, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
                        h = ContentHash.Compute(fs, n => progress(n, got, "壊れていないか確かめています"));
                    if (!string.Equals(h, e.ContentHash, StringComparison.OrdinalIgnoreCase))
                        throw new DropboxException("受け取ったファイルが壊れていました。もう一度「受け取る」を押してください。", -1, "");
                }
                File.Move(part, final);
                ok = true;
                return final;
            }
            finally
            {
                if (!ok) TryDelete(part);
            }
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

        static void TryDeleteDir(string path)
        {
            try { if (Directory.Exists(path)) Directory.Delete(path, true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        // Dropbox の /出力 から消す(パックなら隣のまとめ動画も)。すでに無い(not_found)のは消えているのと同じなので成功とみなす(通信のやり直しの2回目に返る)
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

        // すべて受け取る: packs を順に Download → Delete。progress(何本目(1 から), そのパック, 全体で済んだバイト, 全体のバイト, 段の名前)
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
                long doneBefore = before;
                long size = Math.Max(0, e.Size);
                string path;
                try
                {
                    path = Download(e, dir, (done, total, step) => progress(no, e, doneBefore + Math.Min(done, size), all, step));
                }
                catch (CanceledException) { r.Canceled = true; break; }
                catch (DropboxException ex)
                {
                    if (ex.Status >= 0) { r.Error = ex; break; }
                    r.Failed.Add(e.Title);
                    client.Log("receive all: skip " + e.Name + ": " + ex.Message);
                    before += size;
                    continue;
                }
                catch (IOException ex) { r.Error = ex; break; }
                catch (UnauthorizedAccessException ex) { r.Error = ex; break; }
                string extractError;
                r.LastPath = ExtractOrKeep(path, dir, (done, total, step) => progress(no, e, doneBefore + Math.Min(done, size), all, step), out extractError);
                if (extractError != null) r.NotExtracted.Add(e.Title);
                before += size;
                // 受け取り終えたものは、「やめる」が押されていても消し終える(消さないと次に更新したときにまた出る)
                try { Delete(e); r.Done.Add(e); }
                catch (DropboxException ex)
                {
                    r.Kept.Add(e);
                    client.Log("receive all: delete failed " + e.Name + ": " + ex.Message);
                }
            }
            return r;
        }

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

        static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
