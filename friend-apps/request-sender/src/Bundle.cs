// この PC で処理するときの依頼の形: friend-defaults.json(送り先の人が配る既定)+ 画面の欄 → 封筒 + 束(F1 の F3a。設計 notes:docs/design/f1-build.md の 1-2・3 の (f1f)、
// 封筒 = src/flow/envelope.py・束 = src/flow/spec.py)。アプリは束の形を知らずに重ねるだけ(検査は ② = 断られたら理由を出す)。
//   - URL は 1 本ごとに封筒 + 束を 1 つ(1 本ごとの切り抜く数・区間はその束の adopt.top・hints.ranges)
//   - 動画ファイルは 1 本ごとに kind file(パスをそのまま渡す = 送らない)・ライブ配信は kind live 1 つ
//   - 今の依頼の JSON の欄の行き先: deliverBatch → 封筒 deliver.batch・1 人目の配信者 → 封筒 legacy.streamer(今の形。RV で正式な欄に)・
//     配信者の行 → 束 hints.people(色は #RRGGBB)と transcribe.diarize(人数)・カット / 映像トラック → pack.cut・pack.videoTracks(依頼が決めた印 run.pinned)・
//     重み(指定したときだけ)→ analyze.wAudio・wChat・wComments(+ pinned weights)・ライブの設定 → adopt(sens・perHour・waitMin・pad・afterStream)と analyze.length
//   - 段の並び(legacy.mode)は今の友人の受付と同じ: URL = request_auto(採用した所だけ書き出す・区間が足りていれば解析しない)・動画 = file_auto。
//     届け先(deliver.dir)は書かない = 届ける段は飛ぶ(パックはこの PC の案件フォルダにできる)
//   - 重ね方は spec.merge と同じ「辞書は鍵ごと・それ以外は置き換え」。エンジン・デバイスは書かない(② がこの PC の設定を重ねる)
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using FriendApps;

namespace RequestSender
{
    // friend-defaults.json: {schema, bundle: {束の節の部分集合}, request: {top, deliverBatch, cut, weights, videoTracks, streamers}}
    public class FriendDefaults
    {
        public const string Schema = "youtube-tools-friend-defaults/v1";
        public const string FileName = "friend-defaults.json";

        public IDictionary<string, object> Bundle = new Dictionary<string, object>();
        public IDictionary<string, object> Request = new Dictionary<string, object>();   // 画面の欄の初めの値(使うのは設定の段)
        public string Problem;   // 読めなかった理由(無いときは null = 既定なし)

        // 無い = 既定なし(束は ② の既定)。壊れている・schema が違う = 既定なしで Problem に理由
        public static FriendDefaults Load(string path)
        {
            if (!File.Exists(path)) return new FriendDefaults();
            var d = Json.ReadFileOrNull(path);
            if (d == null) return new FriendDefaults { Problem = FileName + " が読めません" };
            return From(d);
        }

        public static FriendDefaults From(IDictionary<string, object> d)
        {
            if (Json.Str(d, "schema") != Schema) return new FriendDefaults { Problem = FileName + " の形(schema)が違います: " + (Json.Str(d, "schema") ?? "なし") };
            return new FriendDefaults
            {
                Bundle = BundleMerge.Copy(Json.Dict(d, "bundle")) ?? new Dictionary<string, object>(),
                Request = BundleMerge.Copy(Json.Dict(d, "request")) ?? new Dictionary<string, object>(),
            };
        }
    }

    public static class BundleMerge
    {
        // spec.merge と同じ重ね方: 両方が辞書なら鍵ごと、それ以外は over で置き換え。元の辞書は変えない(新しい辞書)
        public static Dictionary<string, object> Merge(IDictionary<string, object> under, IDictionary<string, object> over)
        {
            var o = Copy(under) ?? new Dictionary<string, object>();
            if (over == null) return o;
            foreach (var kv in over)
            {
                object cur;
                var a = o.TryGetValue(kv.Key, out cur) ? cur as IDictionary<string, object> : null;
                var b = kv.Value as IDictionary<string, object>;
                o[kv.Key] = a != null && b != null ? Merge(a, b) : CopyValue(kv.Value);
            }
            return o;
        }

        public static Dictionary<string, object> Copy(IDictionary<string, object> d)
        {
            if (d == null) return null;
            var o = new Dictionary<string, object>();
            foreach (var kv in d) o[kv.Key] = CopyValue(kv.Value);
            return o;
        }

        static object CopyValue(object v)
        {
            var d = v as IDictionary<string, object>;
            if (d != null) return Copy(d);
            if (v is string || v == null) return v;
            var list = v as IEnumerable;
            if (list != null) return list.Cast<object>().Select(CopyValue).ToList();
            return v;
        }
    }

    // ② に送る 1 件(封筒 + 束)と、画面に出す名前
    public class FlowRequest
    {
        public Dictionary<string, object> Envelope, Spec;
        public string Label = "";

        public Dictionary<string, object> Body()
        {
            return new Dictionary<string, object> { { "envelope", Envelope }, { "spec", Spec } };
        }
    }

    public static class FlowBundle
    {
        public const int TitleMax = 120, PeopleNameMax = 40;   // flow/envelope.py の TITLE_MAX・flow/spec.py の名前の長さ
        public const string UrlMode = "request_auto", FileMode = "file_auto";

        // 封筒の id = 実行の id にもなる 10 桁の 16 進(flow/run.py の RUN_ID_RE)
        public static string NewId()
        {
            var b = new byte[5];
            using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(b);
            return string.Concat(b.Select(x => x.ToString("x2")));
        }

        // 送る内容 → 封筒 + 束の並び。requestId = この「送る」1 回の依頼の id(RequestId の形)。learningVersion = 手元の学習の束の版(無ければ null)
        public static List<FlowRequest> Build(SendInput input, FriendDefaults defaults, string requestId, string learningVersion, Func<string> newId, DateTimeOffset now)
        {
            defaults = defaults ?? new FriendDefaults();
            newId = newId ?? NewId;
            var list = new List<FlowRequest>();
            long at = (now.UtcDateTime - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).Ticks / TimeSpan.TicksPerMillisecond;
            if (input.Live != null)
            {
                var over = Common(input, learningVersion);
                var s = input.Live.Settings.Clean();
                Section(over, "adopt")["sens"] = s.Sens;
                Section(over, "adopt")["perHour"] = s.PerHour;
                Section(over, "adopt")["waitMin"] = s.WaitMin;
                Section(over, "adopt")["pad"] = (double)s.Pad;
                Section(over, "adopt")["afterStream"] = s.AfterStream;
                Section(over, "analyze")["length"] = s.Length;
                var env = Envelope(newId(), "live", new Dictionary<string, object> { { "url", input.Live.Url } }, input, requestId, at, null);
                list.Add(new FlowRequest { Envelope = env, Spec = BundleMerge.Merge(defaults.Bundle, over), Label = "ライブ配信" });
                return list;
            }
            foreach (var it in input.Items)
            {
                var over = Common(input, learningVersion);
                Section(over, "adopt")["top"] = it.EffectiveTop(Flow.Auto);
                Section(over, "hints")["ranges"] = it.Ranges.Take(Ranges.MaxCount).Select(r => (object)new List<object> { r.Start, r.End }).ToList();
                if (input.Weights != null && input.Weights.Enabled)
                {
                    var an = Section(over, "analyze");
                    an["wAudio"] = Weights.Clean(input.Weights.Audio);
                    an["wChat"] = Weights.Clean(input.Weights.Chat);
                    an["wComments"] = Weights.Clean(input.Weights.Comments);
                    ((List<object>)Section(over, "run")["pinned"]).Add("weights");
                }
                Section(over, "run")["repack"] = true;   // 送り直しは今回のカット・映像トラックで作り直す(今の友人の受付の overwrite と同じ)
                var env = Envelope(newId(), "url", new Dictionary<string, object> { { "url", it.Url } }, input, requestId, at, UrlMode);
                list.Add(new FlowRequest { Envelope = env, Spec = BundleMerge.Merge(defaults.Bundle, over), Label = "配信 " + (YouTubeUrl.ExtractId(it.Url) ?? it.Url) });
            }
            foreach (string v in input.Videos)
            {
                var over = Common(input, learningVersion);
                string name = Path.GetFileName(v);
                var inp = new Dictionary<string, object> { { "path", Path.GetFullPath(v) }, { "title", Cut_(name, TitleMax) } };
                var env = Envelope(newId(), "file", inp, input, requestId, at, FileMode);
                list.Add(new FlowRequest { Envelope = env, Spec = BundleMerge.Merge(defaults.Bundle, over), Label = "動画 " + name });
            }
            return list;
        }

        // どの依頼にも入る束の差分: 配信者・カット・映像トラック・学習の版
        static Dictionary<string, object> Common(SendInput input, string learningVersion)
        {
            var over = new Dictionary<string, object>();
            var people = People(input.People);
            if (people != null) Section(over, "hints")["people"] = people;
            if (input.People != null && input.People.Count >= 1 && input.People.Count <= Speakers.MaxCount)
                Section(over, "transcribe")["diarize"] = input.People.Count;
            var pack = Section(over, "pack");
            pack["cut"] = RequestSender.Cut.IsValid(input.Cut) ? input.Cut : RequestSender.Cut.None;
            pack["videoTracks"] = input.VideoTracks >= VideoTracks.Min && input.VideoTracks <= VideoTracks.Max ? input.VideoTracks : VideoTracks.Default;
            Section(over, "run")["pinned"] = new List<object> { "cut", "videoTracks" };   // 友人が選んだ値(ライブの自動の採用の既定より強い・1 でも要求に書く)
            if (!string.IsNullOrEmpty(learningVersion))
                Section(over, "post")["learning"] = new Dictionary<string, object> { { "version", learningVersion } };
            return over;
        }

        // 配信者の行 → hints.people([{name, color?}]。名前のある行だけ・40 字まで・同じ名前は 1 つ)。名前が 1 つも無く人数だけなら {count}。0 人 = null
        public static object People(SpeakerSet set)
        {
            if (set == null || set.Count < 1 || set.Count > Speakers.MaxCount) return null;
            var rows = new List<object>();
            var seen = new HashSet<string>();
            foreach (var r in Speakers.CleanRows(set))
            {
                string name = r.Name.Length > PeopleNameMax ? r.Name.Substring(0, PeopleNameMax).Trim() : r.Name;
                if (name.Length == 0 || !seen.Add(name)) continue;
                var p = new Dictionary<string, object> { { "name", name } };
                if (r.Color.Length == Speakers.ColorLength) p["color"] = "#" + r.Color;
                rows.Add(p);
            }
            if (rows.Count > 0) return rows;
            return new Dictionary<string, object> { { "count", set.Count } };
        }

        static Dictionary<string, object> Envelope(string id, string kind, Dictionary<string, object> inp, SendInput input, string requestId, long at, string mode)
        {
            var env = new Dictionary<string, object> { { "id", id }, { "kind", kind }, { "input", inp } };
            if (!string.IsNullOrEmpty(requestId)) env["requestId"] = requestId;
            if (DeliverBatch.InRange(input.DeliverBatch)) env["deliver"] = new Dictionary<string, object> { { "batch", input.DeliverBatch } };
            env["createdAt"] = at;
            var legacy = new Dictionary<string, object>();
            if (mode != null) legacy["mode"] = mode;
            string streamer = Speakers.StreamerName(input.People);
            if (streamer.Length > 0) legacy["streamer"] = Cut_(streamer, TitleMax);   // 無ければ書かない = ② が束の hints.people の先頭から決める
            if (legacy.Count > 0) env["legacy"] = legacy;
            return env;
        }

        static Dictionary<string, object> Section(Dictionary<string, object> b, string name)
        {
            object cur;
            if (b.TryGetValue(name, out cur) && cur is Dictionary<string, object>) return (Dictionary<string, object>)cur;
            var d = new Dictionary<string, object>();
            b[name] = d;
            return d;
        }

        static string Cut_(string s, int max)
        {
            s = s ?? "";
            return s.Length > max ? s.Substring(0, max) : s;
        }
    }

    // ② の返事 → 画面の文(submit の断り)
    public static class FlowErrors
    {
        public static string Submit(FlowReply r)
        {
            if (r.Status == 0) return r.Error ?? "処理の部品につながりませんでした";
            string code = r.Code, msg = r.Message;
            if (code == "spec_version" || code == "bad_spec" || (code == "bad_request" && (msg.Contains("知らない項目") || msg.Contains("知らない束の版"))))
                return "このアプリと処理の部品の版が合いません。アプリを更新してください(" + msg + ")";
            return "受け付けられませんでした: " + msg;
        }
    }
}
