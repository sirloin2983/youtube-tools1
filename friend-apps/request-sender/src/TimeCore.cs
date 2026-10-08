// 切り抜き依頼 2.0.0 で足した、画面に依らない部品: 時刻の読み書き・時刻の欄の状態・区間・カット・解析の重み・配信の題名・覚える設定。
// 設計: docs/spec/friend-intake.md の 2-10(時刻の欄は「:」を打たせない。時 → 分 → 秒 の順に数字だけで入れる)
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using FriendApps;

namespace RequestSender
{
    // ---- 時刻(秒の整数)と文字 ----
    public static class TimeText
    {
        public const int MaxSeconds = 99 * 3600 + 59 * 60 + 59;
        static readonly Regex ParamRx = new Regex(@"(?:^|[?&#\s])t=([0-9hmsHMS]+)");
        static readonly Regex UnitRx = new Regex(@"^(?:(\d{1,3})h)?(?:(\d{1,4})m)?(?:(\d{1,6})s?)?$", RegexOptions.IgnoreCase);
        static readonly Regex ColonRx = new Regex(@"^(\d{1,3})[:：](\d{1,2})(?:[:：](\d{1,2}))?$");

        public static int Clamp(long sec)
        {
            return (int)Math.Max(0, Math.Min(MaxSeconds, sec));
        }

        // 1:23:45(時は 0 を付けない。10 時間からは2桁)
        public static string Format(int sec)
        {
            sec = Clamp(sec);
            return (sec / 3600).ToString(CultureInfo.InvariantCulture) + ":" + (sec % 3600 / 60).ToString("00", CultureInfo.InvariantCulture) + ":" +
                   (sec % 60).ToString("00", CultureInfo.InvariantCulture);
        }

        // 長さの言い方: 1時間2分3秒 / 1分25秒 / 45秒
        public static string Length(int sec)
        {
            sec = Math.Max(0, sec);
            int h = sec / 3600, m = sec % 3600 / 60, s = sec % 60;
            var sb = new StringBuilder();
            if (h > 0) sb.Append(h).Append("時間");
            if (m > 0) sb.Append(m).Append("分");
            if (s > 0 || sb.Length == 0) sb.Append(s).Append("秒");
            return sb.ToString();
        }

        // 貼り付けた文字から時刻を読む: YouTube の URL の t=5025 / t=1h23m45s、1:23:45、83:45(分:秒)、1h23m45s。
        // 数字だけ(「5025」)は 秒なのか 時分秒なのか決められないので読まない
        public static bool TryParse(string text, out int sec)
        {
            return TryParse(text, true, out sec);
        }

        // allowUrl = YouTube の URL(t=)も読む。時刻の欄をほかの画面で使い回すときは false(URL は要る欄だけ)
        public static bool TryParse(string text, bool allowUrl, out int sec)
        {
            sec = 0;
            string s = (text ?? "").Trim();
            if (s.Length == 0 || s.Length > 2048) return false;
            var m = ParamRx.Match(s);
            if (m.Success) return allowUrl && Units(m.Groups[1].Value, true, out sec);
            if (s.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || s.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) return false;
            m = ColonRx.Match(s);
            if (m.Success)
            {
                long a = long.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture), b = long.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture);
                long total = m.Groups[3].Success ? a * 3600 + b * 60 + long.Parse(m.Groups[3].Value, CultureInfo.InvariantCulture) : a * 60 + b;
                if (total > MaxSeconds) return false;
                sec = (int)total;
                return true;
            }
            return Units(s, false, out sec);
        }

        // "5025" / "1h23m45s" / "83m" の形。bareSeconds = 数字だけを秒として読む(URL の t= のときだけ)
        static bool Units(string v, bool bareSeconds, out int sec)
        {
            sec = 0;
            if (v.Length == 0) return false;
            bool digitsOnly = v.All(c => c >= '0' && c <= '9');
            if (digitsOnly && !bareSeconds) return false;
            var m = UnitRx.Match(v);
            if (!m.Success) return false;
            long total = Num(m.Groups[1]) * 3600 + Num(m.Groups[2]) * 60 + Num(m.Groups[3]);
            if (total > MaxSeconds) return false;
            sec = (int)total;
            return true;
        }

        static long Num(Group g)
        {
            return g.Success && g.Value.Length > 0 ? long.Parse(g.Value, CultureInfo.InvariantCulture) : 0;
        }
    }

    // ---- 時刻の欄の状態(TimeBox が持つ。キー → 新しい状態。画面の部品に依らないのでテストできる) ----
    //   欄は1つ。時・分・秒 のどれか1つが選ばれている(反転)。数字は選んだ所に入り、時(1桁)→ 分(2桁)→ 秒(2桁)と進む
    public class TimeEdit
    {
        public const int Hour = 0, Minute = 1, Second = 2;
        static readonly int[] Unit = { 3600, 60, 1 };

        public int Value;            // 秒
        public bool HasValue;        // 入っていない間は 0:00:00 を薄く出す
        public int Segment;          // 選ばれている所(Hour / Minute / Second)
        bool half;                   // 分・秒の1桁目だけ打った所(次の数字が2桁目)

        public string Text { get { return TimeText.Format(Value); } }

        // 欄に入った: 時から打ち始める
        public void Focus()
        {
            Segment = Hour;
            half = false;
        }

        public void Select(int segment)
        {
            Segment = Math.Max(Hour, Math.Min(Second, segment));
            half = false;
        }

        public void Left() { Select(Segment - 1); }
        public void Right() { Select(Segment + 1); }

        int Part(int segment)
        {
            return segment == Hour ? Value / 3600 : segment == Minute ? Value % 3600 / 60 : Value % 60;
        }

        void SetPart(int segment, int v)
        {
            int h = Part(Hour), m = Part(Minute), s = Part(Second);
            if (segment == Hour) h = v; else if (segment == Minute) m = v; else s = v;
            Value = TimeText.Clamp((long)h * 3600 + m * 60 + s);
        }

        // 数字: 時は1桁で次へ。分・秒は2桁で次へ(最初が 6〜9 なら1桁とみなして次へ)。秒の後は秒にとどまる
        public void Digit(int d)
        {
            if (d < 0 || d > 9) return;
            HasValue = true;
            if (Segment == Hour)
            {
                SetPart(Hour, d);
                Segment = Minute;
                half = false;
            }
            else if (!half)
            {
                SetPart(Segment, d);
                if (d >= 6) Advance(); else half = true;
            }
            else
            {
                SetPart(Segment, Part(Segment) * 10 + d);
                Advance();
            }
        }

        void Advance()
        {
            half = false;
            if (Segment < Second) Segment++;
        }

        // ↑↓: 選んだ単位で ±1(big = ±10)。繰り上がり・繰り下がりあり。0 より前には行かない
        public void Step(int direction, bool big)
        {
            HasValue = true;
            half = false;
            Value = TimeText.Clamp((long)Value + (long)direction * Unit[Segment] * (big ? 10 : 1));
        }

        // BackSpace: 選んだ所を 0 に。もう 0 なら左へ
        public void Backspace()
        {
            if (Part(Segment) == 0 && !half) Left();
            else SetPart(Segment, 0);
            half = false;
        }

        // Delete: 欄を空に
        public void Clear()
        {
            Value = 0;
            HasValue = false;
            Focus();
        }

        public void Set(int sec)
        {
            Value = TimeText.Clamp(sec);
            HasValue = true;
            half = false;
        }

        // 選んだ所の、Text の中の位置(反転させる範囲)
        public void SegmentRange(out int start, out int length)
        {
            string t = Text;
            int a = t.IndexOf(':'), b = t.LastIndexOf(':');
            if (Segment == Hour) { start = 0; length = a; }
            else if (Segment == Minute) { start = a + 1; length = b - a - 1; }
            else { start = b + 1; length = t.Length - b - 1; }
        }

        // クリックした文字の位置 → 時・分・秒
        public static int SegmentAt(string text, int charIndex)
        {
            int a = (text ?? "").IndexOf(':'), b = (text ?? "").LastIndexOf(':');
            return charIndex <= a ? Hour : charIndex <= b ? Minute : Second;
        }
    }

    // ---- 区間(開始〜終了。秒。前後の余白は PC が付けるので、ここは友人が入れた値のまま) ----
    public struct ClipRange
    {
        public int Start, End;
        public ClipRange(int start, int end) { Start = start; End = end; }
    }

    public static class Ranges
    {
        public const int MaxCount = 10, MaxLength = 3600;

        // 区間の行の誤り(その場で欄の下に出す)。問題なければ null。両方とも空の行は「入れていない」= 問題なし(送らない)
        public static string Problem(bool hasStart, int start, bool hasEnd, int end)
        {
            if (!hasStart && !hasEnd) return null;
            if (!hasEnd) return "終了の時刻を入れてください(「+30秒」などのボタンでも入ります)";
            if (!hasStart) return "開始の時刻を入れてください";
            if (end <= start) return "終了が開始より前です。終了の時刻を直してください";
            if (end - start > MaxLength) return "1つの区間は 60 分までです。終了を早めるか、区間を分けてください";
            return null;
        }

        // ,"ranges":[{"start":5025,"end":5110}] を返す。③(manual)・区間なしは ""
        public static string JsonPart(string flow, IList<ClipRange> ranges)
        {
            if (flow == Flow.Manual || ranges == null || ranges.Count == 0) return "";
            return ",\"ranges\":[" + string.Join(",", ranges.Take(MaxCount).Select(r =>
                "{\"start\":" + r.Start.ToString(CultureInfo.InvariantCulture) + ",\"end\":" + r.End.ToString(CultureInfo.InvariantCulture) + "}")) + "]";
        }
    }

    // 配信1本ぶんの依頼: URL・切り抜く数(合計)・区間。区間が切り抜く数に足りない分は PC が自動の見どころで埋める
    public class UrlItem
    {
        public string Url;                                  // 正規化済み
        public int Top = Validation.DefaultTop;
        public List<ClipRange> Ranges = new List<ClipRange>();

        // 送る切り抜く数: 1〜10 に収め、区間の数より小さくしない
        public int EffectiveTop(string flow)
        {
            int n = Math.Max(Validation.MinTop, Math.Min(Validation.MaxTop, Top));
            return flow == Flow.Manual ? n : Math.Max(n, Math.Min(Ranges.Count, Validation.MaxTop));
        }

        // 「指定 1 + 自動 2」の数
        public int AutoCount { get { return Math.Max(0, EffectiveTop(Flow.Auto) - Ranges.Count); } }
    }

    // ---- カット(① 全自動のパックの作り方)。none = カットしない(はじめの値)/ silence = 無音の所を削る ----
    public static class Cut
    {
        public const string None = "none", Silence = "silence";

        public static bool IsValid(string cut)
        {
            return cut == None || cut == Silence;
        }

        public static string Label(string cut)
        {
            return cut == Silence ? "無音を削る" : "カットしない";
        }

        // ,"cut":"none" を返す。①(auto)のときだけ
        public static string JsonPart(string flow, string cut)
        {
            if (flow != Flow.Auto) return "";
            return ",\"cut\":" + JsonText.Quote(IsValid(cut) ? cut : None, false);
        }
    }

    // ---- 解析の重み(見どころを自動で選ぶときの、音声・チャット・コメントの重み。0.0〜3.0・0.1 刻み) ----
    public class Weights
    {
        public const double Min = 0.0, Max = 3.0, Step = 0.1, DefaultAudio = 1.0, DefaultChat = 1.0, DefaultComments = 0.7;

        public bool Enabled;                                 // 「重みを指定する」。外れていれば PC の設定のまま(JSON に書かない)
        public double Audio = DefaultAudio, Chat = DefaultChat, Comments = DefaultComments;

        public static double Clean(double v)
        {
            if (double.IsNaN(v) || double.IsInfinity(v)) return 1.0;
            return Math.Round(Math.Max(Min, Math.Min(Max, v)), 1);
        }

        static string Num(double v)
        {
            return Clean(v).ToString("0.0", CultureInfo.InvariantCulture);
        }

        // ,"weights":{"audio":1.0,"chat":1.0,"comments":0.7} を返す。指定しないなら ""
        public string JsonPart()
        {
            if (!Enabled) return "";
            return ",\"weights\":{\"audio\":" + Num(Audio) + ",\"chat\":" + Num(Chat) + ",\"comments\":" + Num(Comments) + "}";
        }
    }

    // ---- ライブ配信の依頼の、友人のベータの設定(2.8.0。docs/spec/friend-intake.md の 2-15。依頼の JSON の "live")----
    //   sens = 感度 high|normal|low・perHour = 1 時間の候補の枠 1〜30・length = 切り抜きの長さ 10〜120 秒・waitMin = 自動で採用するまでの分 1〜60・
    //   pad = 前後の余白 0〜5 秒・afterStream = 配信後にアーカイブからも追加する。範囲の外・無い値は既定(PC の受付も同じ規則)
    public class LiveSettings
    {
        public const string High = "high", Normal = "normal", Low = "low";
        public static readonly string[] SensAll = { High, Normal, Low };
        public const int MinPerHour = 1, MaxPerHour = 30, DefaultPerHour = 6;
        public const int MinLength = 10, MaxLength = 120, DefaultLength = 45;
        public const int MinWait = 1, MaxWait = 60, DefaultWait = 5;
        public const int MinPad = 0, MaxPad = 5, DefaultPad = 2;

        public string Sens = Normal;
        public int PerHour = DefaultPerHour, Length = DefaultLength, WaitMin = DefaultWait, Pad = DefaultPad;
        public bool AfterStream = true;

        public static string SensLabel(string sens)
        {
            return sens == High ? "高" : sens == Low ? "低" : "普通";
        }

        // 範囲の外は既定にした写し
        public LiveSettings Clean()
        {
            return new LiveSettings
            {
                Sens = SensAll.Contains(Sens) ? Sens : Normal,
                PerHour = Pick(PerHour, MinPerHour, MaxPerHour, DefaultPerHour),
                Length = Pick(Length, MinLength, MaxLength, DefaultLength),
                WaitMin = Pick(WaitMin, MinWait, MaxWait, DefaultWait),
                Pad = Pick(Pad, MinPad, MaxPad, DefaultPad),
                AfterStream = AfterStream,
            };
        }

        static int Pick(long v, int min, int max, int dflt)
        {
            return v >= min && v <= max ? (int)v : dflt;
        }

        // ,"live":{"sens":"normal","perHour":6,"length":45,"waitMin":5,"pad":2,"afterStream":true}(鍵の順も約束)
        public string JsonPart()
        {
            var c = Clean();
            var inv = CultureInfo.InvariantCulture;
            return ",\"live\":{\"sens\":" + JsonText.Quote(c.Sens, false) + ",\"perHour\":" + c.PerHour.ToString(inv) + ",\"length\":" + c.Length.ToString(inv) +
                   ",\"waitMin\":" + c.WaitMin.ToString(inv) + ",\"pad\":" + c.Pad.ToString(inv) + ",\"afterStream\":" + (c.AfterStream ? "true" : "false") + "}";
        }

        // 下の帯の要約: 感度 普通・1 時間 6 本・45 秒・待ち 5 分・余白 2 秒・配信後も追加
        public string Summary()
        {
            var c = Clean();
            return "感度 " + SensLabel(c.Sens) + " ・ 1 時間 " + c.PerHour + " 本 ・ " + c.Length + " 秒 ・ 待ち " + c.WaitMin + " 分 ・ 余白 " + c.Pad + " 秒 ・ 配信後の追加 " + (c.AfterStream ? "あり" : "なし");
        }

        // settings.json の "live" から(無い・形が違う値は既定)
        public static LiveSettings From(IDictionary<string, object> d)
        {
            var s = new LiveSettings();
            if (d == null) return s;
            string sens = Json.Str(d, "sens");
            if (SensAll.Contains(sens)) s.Sens = sens;
            s.PerHour = Pick(Json.Long(d, "perHour", DefaultPerHour), MinPerHour, MaxPerHour, DefaultPerHour);
            s.Length = Pick(Json.Long(d, "length", DefaultLength), MinLength, MaxLength, DefaultLength);
            s.WaitMin = Pick(Json.Long(d, "waitMin", DefaultWait), MinWait, MaxWait, DefaultWait);
            s.Pad = Pick(Json.Long(d, "pad", DefaultPad), MinPad, MaxPad, DefaultPad);
            s.AfterStream = Json.Bool(d, "afterStream", true);
            return s;
        }

        public Dictionary<string, object> ToDict()
        {
            var c = Clean();
            return new Dictionary<string, object>
            {
                { "sens", c.Sens }, { "perHour", c.PerHour }, { "length", c.Length }, { "waitMin", c.WaitMin }, { "pad", c.Pad }, { "afterStream", c.AfterStream },
            };
        }
    }

    // ---- 配信の題名(YouTube の oEmbed。貼り間違いに気づくため。ID だけを渡し、友人が入れた文字はそのまま使わない) ----
    public static class OEmbed
    {
        public const int MaxBytes = 64 * 1024, TimeoutMs = 8000, MaxTitle = 80;
        static readonly Regex IdRx = new Regex("^[A-Za-z0-9_-]{11}$");

        // 問い合わせ先。ID の形でなければ null
        public static string Url(string videoId)
        {
            if (videoId == null || !IdRx.IsMatch(videoId)) return null;
            return "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D" + videoId + "&format=json";
        }

        // 返事の JSON から題名(制御文字を除く・80 文字まで)。無い・読めないときは null
        public static string ParseTitle(string json)
        {
            try
            {
                string t = Json.Str(Json.Parse(json ?? ""), "title");
                if (t == null) return null;
                var sb = new StringBuilder();
                foreach (char c in t) if (c >= 0x20 && c != 0x7F) sb.Append(c);
                t = sb.ToString().Trim();
                if (t.Length == 0) return null;
                return t.Length > MaxTitle ? t.Substring(0, MaxTitle) + "…" : t;
            }
            catch (Exception ex)
            {
                if (!(ex is FormatException || ex is ArgumentException || ex is InvalidOperationException)) throw;
                return null;
            }
        }
    }

    // ---- 覚える設定(settings.json)。仕上げ方・URL・区間・話す人・メモは覚えない ----
    // まとめ動画の音量(2.8.1。10-09 ユーザー決定: はじめ 30%)。小窓(Preview.cs)がつまみで変え、本体が settings.json の previewVolume に覚える。
    // WPF を使う小窓の型に本体から触らない(読み込めない PC で本体まで落とさない)ために、値はここに置く
    public static class PreviewVolume
    {
        public const double Default = 0.3;
        public static double Current = Default;

        public static double Clamp(double v) { return double.IsNaN(v) || v < 0 || v > 1 ? Default : v; }   // 範囲の外・壊れた値は既定
        public static int Percent(double v) { return (int)Math.Round(Clamp(v) * 100); }
    }

    public class AppSettings
    {
        public static readonly string[] Themes = { "A", "B", "C", "D" };
        public double PreviewVolume = RequestSender.PreviewVolume.Default;   // まとめ動画の音量 0〜1(2.8.1)

        public string Cut = RequestSender.Cut.None;
        public int VideoTracks = RequestSender.VideoTracks.Default;
        public int Top = Validation.DefaultTop;
        public Weights Weights = new Weights();
        public string Theme = "A";
        public int WindowWidth, WindowHeight;                // 0 = はじめの大きさ
        public int DeliverBatch = RequestSender.DeliverBatch.Default;   // 届け方(2.8.0。1 = 1 本ずつ / n = n 本ごと)
        public LiveSettings Live = new LiveSettings();                  // ライブ配信の依頼の設定(2.8.0。最後に使った値)

        // 読んだ辞書から(無い・形が違う値は既定)
        public static AppSettings From(IDictionary<string, object> d)
        {
            var s = new AppSettings();
            if (d == null) return s;
            string cut = Json.Str(d, "cut");
            if (RequestSender.Cut.IsValid(cut)) s.Cut = cut;
            long tracks = Json.Long(d, "videoTracks", s.VideoTracks);
            if (tracks >= RequestSender.VideoTracks.Min && tracks <= RequestSender.VideoTracks.Max) s.VideoTracks = (int)tracks;
            long top = Json.Long(d, "top", s.Top);
            if (top >= Validation.MinTop && top <= Validation.MaxTop) s.Top = (int)top;
            var w = Json.Dict(d, "weights");
            if (w != null)
            {
                s.Weights.Enabled = Json.Bool(w, "enabled");
                s.Weights.Audio = Weights.Clean(Number(w, "audio", Weights.DefaultAudio));
                s.Weights.Chat = Weights.Clean(Number(w, "chat", Weights.DefaultChat));
                s.Weights.Comments = Weights.Clean(Number(w, "comments", Weights.DefaultComments));
            }
            string theme = Json.Str(d, "theme");
            if (Themes.Contains(theme)) s.Theme = theme;
            long ww = Json.Long(d, "windowWidth", 0), wh = Json.Long(d, "windowHeight", 0);
            if (ww >= 400 && ww <= 10000 && wh >= 300 && wh <= 10000) { s.WindowWidth = (int)ww; s.WindowHeight = (int)wh; }
            long batch = Json.Long(d, "deliverBatch", s.DeliverBatch);
            if (batch >= RequestSender.DeliverBatch.Min && batch <= RequestSender.DeliverBatch.Max) s.DeliverBatch = (int)batch;
            s.Live = LiveSettings.From(Json.Dict(d, "live"));
            s.PreviewVolume = RequestSender.PreviewVolume.Clamp(Number(d, "previewVolume", RequestSender.PreviewVolume.Default));
            return s;
        }

        // 辞書へ書く(ほかのキー = downloadDir などはそのまま残す)
        public void Into(IDictionary<string, object> d)
        {
            d["cut"] = RequestSender.Cut.IsValid(Cut) ? Cut : RequestSender.Cut.None;
            d["videoTracks"] = VideoTracks;
            d["top"] = Top;
            d["weights"] = new Dictionary<string, object>
            {
                { "enabled", Weights.Enabled }, { "audio", Weights.Clean(Weights.Audio) }, { "chat", Weights.Clean(Weights.Chat) }, { "comments", Weights.Clean(Weights.Comments) },
            };
            d["theme"] = Themes.Contains(Theme) ? Theme : "A";
            d["windowWidth"] = WindowWidth;
            d["windowHeight"] = WindowHeight;
            d["deliverBatch"] = RequestSender.DeliverBatch.InRange(DeliverBatch) ? DeliverBatch : RequestSender.DeliverBatch.Default;
            d["live"] = (Live ?? new LiveSettings()).ToDict();
            d["previewVolume"] = RequestSender.PreviewVolume.Clamp(PreviewVolume);
        }

        static double Number(IDictionary<string, object> d, string key, double dflt)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v == null) return dflt;
            if (v is int) return (int)v;
            if (v is long) return (long)v;
            if (v is decimal) return (double)(decimal)v;
            if (v is double) return (double)v;
            return dflt;
        }
    }
}
