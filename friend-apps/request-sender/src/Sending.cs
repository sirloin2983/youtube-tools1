// 1回の「送る」: 動画と URL が両方あれば依頼を2つに分ける(id も2つ)。動画 → 最後に依頼の JSON の順(JSON が届いた = そろった、の合図)。
// ライブ配信の依頼(2.8.0)は 1 件 1 本だけで送る(動画・ほかの配信の URL と一緒には送らない)
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
        public List<UrlItem> Items = new List<UrlItem>();   // 配信ごとの URL(正規化済み)・切り抜く数・区間
        public string Memo = "";
        public SpeakerSet People = new SpeakerSet();     // 配信者(2.1.0: 話す人と同じもの)。数(0 = 指定しない)と、その人数分の名前・字幕の色。1 人目の名前が "streamer" にも入る
        public string Flow = RequestSender.Flow.Auto;   // PC でどこまでやるか(動画と URL の両方にかかる)
        public int VideoTracks = RequestSender.VideoTracks.Default;   // Resolve の映像トラックの数(① 全自動のときだけ送る)
        public string Cut = RequestSender.Cut.None;                   // カット(① 全自動のときだけ送る)
        public Weights Weights = new Weights();                       // 解析の重み(指定したときだけ・URL の依頼だけ)
        public int DeliverBatch = RequestSender.DeliverBatch.Default; // 届け方(① 全自動の url・video の依頼だけ送る。2.8.0)
        public LiveRequest Live;                                      // ライブ配信の依頼(2.8.0。null = なし)
    }

    // ライブ配信の依頼: 配信の URL 1 本(正規化済み)と友人のベータの設定
    public class LiveRequest
    {
        public string Url = "";
        public LiveSettings Settings = new LiveSettings();
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
            if (input.Live != null)
            {
                if (YouTubeUrl.ExtractId(input.Live.Url) == null) errs.Add("ライブ配信の URL が YouTube の形ではありません(watch?v=… / youtu.be/… / live/… の形)。");
                if (input.Videos.Count > 0 || input.Items.Count > 0) errs.Add(LiveAloneMessage);
            }
            else if (input.Videos.Count == 0 && input.Items.Count == 0) errs.Add("動画か配信の URL を入れてください。");
            foreach (var it in input.Items)
            {
                if (!Validation.TopInRange(it.Top)) errs.Add("切り抜く数は " + Validation.MinTop + "〜" + Validation.MaxTop + " にしてください。");
                if (it.Ranges.Count > Ranges.MaxCount) errs.Add("1本の配信の区間は " + Ranges.MaxCount + " 個までにしてください。");
                foreach (var r in it.Ranges)
                {
                    string p = Ranges.Problem(true, r.Start, true, r.End);
                    if (p != null) errs.Add(TimeText.Format(r.Start) + "〜" + TimeText.Format(r.End) + ": " + p);
                }
            }
            if (!RequestSender.Cut.IsValid(input.Cut)) errs.Add("カットの方法を選んでください。");
            foreach (string v in input.Videos)
            {
                if (!Validation.IsVideoFile(v)) errs.Add("動画ではないファイルです: " + Path.GetFileName(v));
                else if (!File.Exists(v)) errs.Add("ファイルが見つかりません: " + v);
                else if (new FileInfo(v).Length == 0) errs.Add("空のファイルです: " + Path.GetFileName(v));
            }
            foreach (var p in Speakers.Problems(input.People)) errs.Add("配信者 " + (p.Index + 1) + ": " + p.Message);
            if ((input.Memo ?? "").Length > 2000) errs.Add("メモは 2000 文字までにしてください。");
            if (!RequestSender.Flow.IsValid(input.Flow)) errs.Add("PC でどこまでやるかを選んでください。");
            return errs;
        }

        public const string LiveAloneMessage = "ライブ配信の依頼は 1 件だけで送ります。配信の URL・動画ファイルの欄を空にしてから送ってください(それらを送るなら、ライブ配信の URL を消してください)。";

        public void Run(SendInput input)
        {
            long total = input.Videos.Sum(v => new FileInfo(v).Length);
            var prog = new SendProgress { Total = Math.Max(1, total) };
            DateTimeOffset now = DateTimeOffset.Now;

            if (input.Live != null)
            {
                string id = RequestId.New(now.LocalDateTime);
                prog.Step = "ライブ配信の依頼を送っています";
                Progress(prog);
                string json = RequestJson.Live(id, input.Live.Url, input.Memo, DateTimeOffset.Now, input.People, input.VideoTracks, input.Cut, input.Live.Settings);
                client.UploadBytes(new UTF8Encoding(false).GetBytes(json), RequestId.RequestPath(id));
                Sent.Add("ライブ配信");
                Progress(new SendProgress { Done = prog.Total, Total = prog.Total, Step = "送りました" });
                return;
            }

            string urlId = null;
            if (input.Items.Count > 0)
            {
                string id = urlId = RequestId.New(now.LocalDateTime);
                prog.Step = "配信の URL を送っています";
                Progress(prog);
                string json = RequestJson.Url(id, input.Items, input.Memo, input.Flow, DateTimeOffset.Now, input.People, input.VideoTracks, input.Cut, input.Weights, input.DeliverBatch);
                client.UploadBytes(new UTF8Encoding(false).GetBytes(json), RequestId.RequestPath(id));
                Sent.Add("配信の URL(" + input.Items.Count + " 本)");
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
                string json = RequestJson.Video(id, names, input.Memo, input.Flow, DateTimeOffset.Now, input.People, input.VideoTracks, input.Cut, input.DeliverBatch);
                client.UploadBytes(new UTF8Encoding(false).GetBytes(json), RequestId.RequestPath(id));
                Sent.Add("動画(" + input.Videos.Count + " 本)");
            }
            Progress(new SendProgress { Done = prog.Total, Total = prog.Total, Step = "送りました" });
        }
    }
}
