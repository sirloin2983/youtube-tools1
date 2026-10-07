// 受け取る: PC が「/出力/」に置いたパック(.zip)と失敗の知らせ(.失敗.txt)を一覧にして、選んだものを取ってくる。
// 受け取り終えたパック(大きさと hash を確かめたあと)・読み終えた失敗の知らせだけ、Dropbox から消す(files/delete_v2。鍵に files.content.write)
// 一覧には読みの権限が要る(files.metadata.read・files.content.read)
using System;
using System.Collections.Generic;
using System.IO;
using FriendApps;

namespace RequestSender
{
    public class OutputListing
    {
        public List<OutputEntry> Entries = new List<OutputEntry>();
        public bool FolderMissing;   // 「/出力」がまだ無い(= まだ何も届いていない)
    }

    public class Receiving
    {
        const int MaxPages = 50;   // 1回 500 件 × 50。止まらない返事への備え
        readonly DropboxClient client;

        public Receiving(DropboxClient client)
        {
            this.client = client;
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
            OutputFolder.SortNewestFirst(r.Entries);
            return r;
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
            CheckFreeSpace(dir, e.Size);
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

        // Dropbox の /出力 から消す。すでに無い(not_found)のは消えているのと同じなので成功とみなす(通信のやり直しの2回目に返る)
        public void Delete(OutputEntry e)
        {
            try
            {
                client.Rpc("files/delete_v2", DropboxArgs.Delete(e.ApiPath));
            }
            catch (DropboxException ex)
            {
                if (!ErrorText.IsNotFound(ex.Status, ex.Body)) throw;
            }
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
