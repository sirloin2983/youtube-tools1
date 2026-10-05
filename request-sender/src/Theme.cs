// 配色とフォント(2.0.0)。4つの配色(A ネオンシアン / B シンセウェーブ / C ターミナルグリーン / D アイスライト)を窓の右上で切り替える。
// 色・フォント・大きさの倍率はここだけに置く。設計: .design/request-sender-overhaul/DESIGN_BRIEF.md
using System;
using System.Drawing;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace RequestSender
{
    public class Palette
    {
        public string Name, Label;
        public Color Bg, Panel, Line, Text, Muted, Accent, OnAccent, Error;
        public bool Dark;

        public Palette(string name, string label, bool dark, string bg, string panel, string line, string text, string muted, string accent, string onAccent, string error)
        {
            Name = name; Label = label; Dark = dark;
            Bg = Hex(bg); Panel = Hex(panel); Line = Hex(line); Text = Hex(text); Muted = Hex(muted); Accent = Hex(accent); OnAccent = Hex(onAccent); Error = Hex(error);
        }

        static Color Hex(string s)
        {
            return ColorTranslator.FromHtml(s);
        }
    }

    // 配色に合わせて色を付け直す部品(Theme.Apply が呼ぶ)
    public interface IThemed
    {
        void ApplyTheme();
    }

    public static class Theme
    {
        public static readonly Palette[] All =
        {
            new Palette("A", "ネオンシアン", true, "#0A0E14", "#111824", "#22304A", "#DCE7F5", "#7C8BA1", "#19D3F3", "#04222A", "#FF4D8D"),
            new Palette("B", "シンセウェーブ", true, "#0D0A17", "#161129", "#30245A", "#ECE6FF", "#9288B8", "#FF3DA5", "#2A0418", "#FF8A3D"),
            new Palette("C", "ターミナルグリーン", true, "#060B08", "#0C1510", "#1E3527", "#D7F5E1", "#6E8F7B", "#3DFF8B", "#032611", "#FFC14D"),
            new Palette("D", "アイスライト", false, "#EEF2F8", "#FFFFFF", "#C3CFE2", "#0E1726", "#5B6B84", "#1F5BFF", "#FFFFFF", "#D6336C"),
        };

        public static Palette P = All[0];
        public static event Action Changed;

        public static void Set(string name)
        {
            var p = All.FirstOrDefault(x => x.Name == name) ?? All[0];
            if (p == P) return;
            P = p;
            if (Changed != null) Changed();
        }

        // ---- フォント(本文 Yu Gothic UI・数字と番号は Consolas。無ければ Windows が近いものに替える) ----
        public static readonly Font Body = new Font("Yu Gothic UI", 9.75f);
        public static readonly Font Bold = new Font("Yu Gothic UI", 9.75f, FontStyle.Bold);
        public static readonly Font Small = new Font("Yu Gothic UI", 9f);
        public static readonly Font Big = new Font("Yu Gothic UI", 11.5f, FontStyle.Bold);
        public static readonly Font Mono = new Font("Consolas", 11.5f);
        public static readonly Font MonoSmall = new Font("Consolas", 9f);

        // 2つの色を混ぜる(t = b の割合)
        public static Color Mix(Color a, Color b, double t)
        {
            return Color.FromArgb((int)Math.Round(a.R + (b.R - a.R) * t), (int)Math.Round(a.G + (b.G - a.G) * t), (int)Math.Round(a.B + (b.B - a.B) * t));
        }

        // 木の全部に色を付け直す。IThemed は自分で、ほかの入力の部品は地と文字の色だけ
        public static void Apply(Control root)
        {
            var t = root as IThemed;
            if (t != null) t.ApplyTheme();
            foreach (Control c in root.Controls) Apply(c);
            if (root.IsHandleCreated) DarkScroll(root);
            root.Invalidate();
        }

        // ---- Windows の暗い見た目(タイトルバー・スクロールバー)。古い Windows では何も起きない(失敗は無視) ----
        [DllImport("dwmapi.dll")]
        static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

        [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)]
        static extern int SetWindowTheme(IntPtr hwnd, string app, string idList);

        public static void TitleBar(Form f)
        {
            if (!f.IsHandleCreated) return;
            try
            {
                int on = P.Dark ? 1 : 0;
                if (DwmSetWindowAttribute(f.Handle, 20, ref on, 4) != 0) DwmSetWindowAttribute(f.Handle, 19, ref on, 4);
            }
            catch (Exception) { }
        }

        // スクロールバーを持つ部品(一覧・複数行の欄・スクロールするパネル)だけ
        public static void DarkScroll(Control c)
        {
            if (!(c is ListBox || c is ScrollableControl || (c is TextBox && ((TextBox)c).Multiline))) return;
            DarkScroll(c.Handle);
        }

        // ハンドルだけ分かる窓(プルダウンの一覧)用
        public static void DarkScroll(IntPtr hwnd)
        {
            if (hwnd == IntPtr.Zero) return;
            try { SetWindowTheme(hwnd, P.Dark ? "DarkMode_Explorer" : "Explorer", null); }
            catch (Exception) { }
        }
    }

    // 大きさの倍率(システムの DPI。96 = 100%)。自分で置く・描く部品の px はここを通す
    public static class Ui
    {
        static float scale;

        public static float Scale
        {
            get
            {
                if (scale <= 0)
                {
                    try { using (var g = Graphics.FromHwnd(IntPtr.Zero)) scale = g.DpiX / 96f; }
                    catch (Exception) { scale = 1f; }
                }
                return scale;
            }
        }

        public static int S(int px)
        {
            return (int)Math.Round(px * Scale);
        }

        // 空の入力欄に薄く出す案内(1行の欄だけ。打ち始めると消える)
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        static extern IntPtr SendMessage(IntPtr hwnd, int msg, IntPtr wparam, string lparam);

        public static void Cue(TextBox box, string text)
        {
            try { SendMessage(box.Handle, 0x1501 /* EM_SETCUEBANNER */, (IntPtr)1, text); }
            catch (Exception) { }
        }

        // 小さな説明(ツールチップ)。× などの記号だけのボタンに付ける
        static readonly ToolTip tips = new ToolTip();

        public static void Tip(Control c, string text)
        {
            tips.SetToolTip(c, text);
        }
    }
}
