// 切り抜き依頼 2.0.0 で足した、画面に依らない部品: 時刻の読み書き・時刻の欄の状態・区間・カット・解析の重み・配信の題名・覚える設定。
// 設計: .design/request-sender-overhaul/DESIGN_BRIEF.md(時刻の欄は「:」を打たせない。時 → 分 → 秒 の順に数字だけで入れる)
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

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
    public class AppSettings
    {
        public static readonly string[] Themes = { "A", "B", "C", "D" };

        public string Cut = RequestSender.Cut.None;
        public int VideoTracks = RequestSender.VideoTracks.Default;
        public int Top = Validation.DefaultTop;
        public Weights Weights = new Weights();
        public string Theme = "A";
        public int WindowWidth, WindowHeight;                // 0 = はじめの大きさ

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
