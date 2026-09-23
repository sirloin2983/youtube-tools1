"""ブラウザ動作確認用サーバー。生成動画・専用の一時データだけを使う。

    python e2e_review.py [port]

表示される data.json を読み取り専用にすると保存失敗を再現できる。
終了は Ctrl+C。一時データは終了時に削除する。
"""
import os
import subprocess
import sys
import tempfile
from http.server import ThreadingHTTPServer

import common
import serve


def main():
    ffmpeg = common.find_tool("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg が必要です(STUDIO_FFMPEG でも指定できます)")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8895
    with tempfile.TemporaryDirectory(prefix="clip-studio-review-") as home:
        media = os.path.join(home, "sample.mp4")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=15:duration=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=30", "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", media], check=True)
        store, _ = serve.init(home)
        for vid, title in (("fqa00000001", "テスト動画 A"), ("fqa00000002", "テスト動画 B")):
            store.ensure({"kind": "file", "videoId": vid, "name": "sample.mp4", "path": media}, title)
            store.put_video(vid, title, [{"id": "m1", "start": 2, "end": 7, "label": "確認用", "status": "adopted"}])
        serve.PORT = port
        serve.ALLOWED_HOSTS = {"localhost:%d" % port, "127.0.0.1:%d" % port}
        print("Preview: http://localhost:%d/" % port, flush=True)
        print("Fixture: " + home, flush=True)
        with ThreadingHTTPServer(("127.0.0.1", port), serve.Handler) as server:
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
