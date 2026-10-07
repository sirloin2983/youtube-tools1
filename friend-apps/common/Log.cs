// 2 つの友人用アプリ(ホロカラー・切り抜き依頼)で共通の手元の記録。各アプリの build.bat が src と一緒に ../common/*.cs をコンパイルする。
// 1 行ずつ日時をつけて足す。256KB を超えたら .old に回す。書けなくてもアプリは止めない。鍵などの秘密は書かない(呼ぶ側で渡さない)
using System;
using System.IO;
using System.Text;

namespace FriendApps
{
    public static class Log
    {
        static string path;

        // dir = 作業データのフォルダ・fileName = 記録の名前(例: holo-colors.log)
        public static void Init(string dir, string fileName)
        {
            path = Path.Combine(dir, fileName);
        }

        public static void Write(string msg)
        {
            if (path == null) return;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                var fi = new FileInfo(path);
                if (fi.Exists && fi.Length > 256 * 1024) { File.Copy(path, path + ".old", true); File.Delete(path); }
                File.AppendAllText(path, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + msg + "\r\n", new UTF8Encoding(false));
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
