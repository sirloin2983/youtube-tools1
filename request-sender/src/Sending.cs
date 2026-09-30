// 1回の「送る」: 動画と URL が両方あれば依頼を2つに分ける(id も2つ)。動画 → 最後に依頼の JSON の順(JSON が届いた = そろった、の合図)
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace RequestSender
{
    public class SendInput
    {
        public List<string> Videos = new List<string>();
        public List<string> Urls = new List<string>();   // 正規化済み
        public int Top = Validation.DefaultTop;
        public string Streamer = "", Memo = "";
    }

    public class SendProgress
    {
        public long Done, Total;
        public string Step;
    }

    public class Sending
    {
        readonly DropboxClient client;
        public Action<SendProgress> Progress = p => { };
        public List<string> Sent = new List<string>();   // 送り終えた依頼(「URL の依頼」など。途中で失敗したときの説明に使う)

        public Sending(DropboxClient client)
        {
            this.client = client;
        }

        // 送る前に確かめる。-> 問題の一覧(空なら送れる)
        public static List<string> Check(SendInput input)
        {
            var errs = new List<string>();
            if (input.Videos.Count == 0 && input.Urls.Count == 0) errs.Add("動画か配信の URL を入れてください。");
            if (input.Urls.Count > 0 && !Validation.TopInRange(input.Top))
                errs.Add("切り抜く数は " + Validation.MinTop + "〜" + Validation.MaxTop + " にしてください。");
            foreach (string v in input.Videos)
            {
                if (!Validation.IsVideoFile(v)) errs.Add("動画ではないファイルです: " + Path.GetFileName(v));
                else if (!File.Exists(v)) errs.Add("ファイルが見つかりません: " + v);
                else if (new FileInfo(v).Length == 0) errs.Add("空のファイルです: " + Path.GetFileName(v));
            }
            if ((input.Memo ?? "").Length > 2000) errs.Add("メモは 2000 文字までにしてください。");
            return errs;
        }

        public void Run(SendInput input)
        {
            long total = input.Videos.Sum(v => new FileInfo(v).Length);
            var prog = new SendProgress { Total = Math.Max(1, total) };
            DateTimeOffset now = DateTimeOffset.Now;

            string urlId = null;
            if (input.Urls.Count > 0)
            {
                string id = urlId = RequestId.New(now.LocalDateTime);
                prog.Step = "配信の URL を送っています";
                Progress(prog);
                string json = RequestJson.Url(id, input.Urls, input.Top, input.Memo, DateTimeOffset.Now);
                client.UploadBytes(new UTF8Encoding(false).GetBytes(json), RequestId.RequestPath(id));
                Sent.Add("配信の URL(" + input.Urls.Count + " 本)");
            }

            if (input.Videos.Count > 0)
            {
                string id = RequestId.New(now.LocalDateTime);
                while (id == urlId) id = RequestId.New(now.LocalDateTime);   // 同じ秒でも乱数で分かれるが、念のため
                var names = new List<string>();
                long base_ = 0;
                for (int i = 0; i < input.Videos.Count; i++)
                {
                    string v = input.Videos[i];
                    string file = Path.GetFileName(v);
                    prog.Step = "動画を送っています(" + (i + 1) + " / " + input.Videos.Count + "): " + file;
                    long b = base_;
                    Progress(new SendProgress { Done = b, Total = prog.Total, Step = prog.Step });
                    string actual = client.UploadFile(v, RequestId.VideoPath(id, file), n =>
                        Progress(new SendProgress { Done = b + n, Total = prog.Total, Step = prog.Step }));
                    names.Add(actual);
                    base_ += new FileInfo(v).Length;
                }
                prog.Step = "依頼を送っています";
                Progress(new SendProgress { Done = total, Total = prog.Total, Step = prog.Step });
                string json = RequestJson.Video(id, names, input.Streamer, input.Memo, DateTimeOffset.Now);
                client.UploadBytes(new UTF8Encoding(false).GetBytes(json), RequestId.RequestPath(id));
                Sent.Add("動画(" + input.Videos.Count + " 本)");
            }
            Progress(new SendProgress { Done = prog.Total, Total = prog.Total, Step = "送りました" });
        }
    }
}
