// 2 つの友人用アプリ(ホロカラー・切り抜き依頼)で共通の JSON の読み書き。各アプリの build.bat が src と一緒に ../common/*.cs をコンパイルする。
// JavaScriptSerializer の Dictionary を、型を確かめながら読む(無い・型が違うときは既定の値)。C# 5 で書く(アプリと同じ)
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;

namespace FriendApps
{
    public static class Json
    {
        static JavaScriptSerializer Serializer()
        {
            var s = new JavaScriptSerializer();
            s.MaxJsonLength = 16 * 1024 * 1024;
            return s;
        }

        public static IDictionary<string, object> Parse(string text)
        {
            var o = Serializer().DeserializeObject(text) as IDictionary<string, object>;
            if (o == null) throw new FormatException("JSON の一番外側が { } ではありません");
            return o;
        }

        // ファイルの JSON。無い・開けない・壊れているときは null(呼ぶ側は空として扱う)
        public static IDictionary<string, object> ReadFileOrNull(string path)
        {
            try
            {
                return File.Exists(path) ? Parse(File.ReadAllText(path, Encoding.UTF8)) : null;
            }
            catch (Exception ex)
            {
                if (!(ex is IOException || ex is FormatException || ex is ArgumentException || ex is InvalidOperationException || ex is UnauthorizedAccessException)) throw;
                return null;
            }
        }

        public static string Str(IDictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) && v is string ? (string)v : null;
        }

        public static bool Bool(IDictionary<string, object> d, string key, bool dflt = false)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) && v is bool ? (bool)v : dflt;
        }

        // 小数は四捨五入。int に収まらないときは既定の値
        public static int Int(IDictionary<string, object> d, string key, int dflt)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v == null) return dflt;
            if (v is int) return (int)v;
            if (v is long) return (long)v > int.MaxValue || (long)v < int.MinValue ? dflt : (int)(long)v;
            if (v is decimal) return (int)Math.Round((decimal)v);
            return dflt;
        }

        // 大きさ・位置など(5GB のファイルも入る)。小数は切り捨て
        public static long Long(IDictionary<string, object> d, string key, long dflt)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v) || v == null) return dflt;
            if (v is int) return (int)v;
            if (v is long) return (long)v;
            if (v is decimal) return (long)(decimal)v;
            return dflt;
        }

        public static IDictionary<string, object> Dict(IDictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) ? v as IDictionary<string, object> : null;
        }

        public static IEnumerable<IDictionary<string, object>> List(IDictionary<string, object> d, string key)
        {
            object v;
            if (d == null || !d.TryGetValue(key, out v)) yield break;
            var list = v as IEnumerable;
            if (list == null || v is string) yield break;
            foreach (object o in list)
            {
                var item = o as IDictionary<string, object>;
                if (item != null) yield return item;
            }
        }

        // 人が開いても読めるように字下げする(JavaScriptSerializer は1行で書くため)
        public static string Pretty(object value)
        {
            string s = Serializer().Serialize(value);
            var sb = new StringBuilder();
            int depth = 0;
            bool inStr = false;
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                if (inStr)
                {
                    sb.Append(c);
                    if (c == '\\' && i + 1 < s.Length) sb.Append(s[++i]);
                    else if (c == '"') inStr = false;
                    continue;
                }
                switch (c)
                {
                    case '"': inStr = true; sb.Append(c); break;
                    case '{':
                    case '[':
                        sb.Append(c);
                        if (i + 1 < s.Length && (s[i + 1] == '}' || s[i + 1] == ']')) { sb.Append(s[++i]); break; }
                        depth++; NewLine(sb, depth); break;
                    case '}':
                    case ']': depth--; NewLine(sb, depth); sb.Append(c); break;
                    case ',': sb.Append(c); NewLine(sb, depth); break;
                    case ':': sb.Append(": "); break;
                    default: sb.Append(c); break;
                }
            }
            return sb.Append('\n').ToString();
        }

        static void NewLine(StringBuilder sb, int depth)
        {
            sb.Append('\n').Append(' ', depth * 2);
        }
    }
}
