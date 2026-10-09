# -*- coding: utf-8 -*-
"""テスト用の「配信中のような HLS」(本物の YouTube には繋がない)。

- make_source(): ffmpeg の lavfi(testsrc2 + sine)で、1 秒ごとのセグメントの HLS(H.264 + AAC の TS)を作る
- LiveServer: 手元の 127.0.0.1 の HTTP サーバーで、時間がたつほどセグメントを増やして出す(配信中のふり)。
  down = True の間は 503(切断)。end = True で全部出し終えたら #EXT-X-ENDLIST(配信が終わった)
録画の部品は --source direct(HLS の URL を直接 ffmpeg に渡す)でこれを録る。
"""
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FFMPEG = os.environ.get("YTT_FFMPEG") or "ffmpeg"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def make_source(folder, seconds=30, seg=1):
    """folder に src_000.ts … と src.m3u8 を作る -> [(名前, 長さ)]"""
    os.makedirs(folder, exist_ok=True)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
           "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", str(30 * seg), "-keyint_min", str(30 * seg),
           "-sc_threshold", "0", "-c:a", "aac", "-b:a", "64k", "-f", "hls", "-hls_time", str(seg), "-hls_list_size", "0",
           "-hls_segment_filename", os.path.join(folder, "src_%03d.ts"), os.path.join(folder, "src.m3u8")]
    subprocess.run(cmd, check=True, creationflags=NO_WINDOW)
    out, dur = [], None
    with open(os.path.join(folder, "src.m3u8"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#EXTINF:"):
                dur = float(line[8:].split(",")[0])
            elif line and not line.startswith("#"):
                out.append((line, dur))
    return out


class LiveServer:
    def __init__(self, folder, segs, start=3, rate=1.0):
        """start: 最初から見えているセグメントの数。rate: 1 秒あたりに増える数"""
        self.folder, self.segs, self.start_n, self.rate = folder, segs, start, rate
        self.t0 = time.time()
        self.down = False
        self.end = True
        self.hits = 0
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                owner.hits += 1
                if owner.down:
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path.startswith("/live.m3u8"):
                    body = owner.playlist().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                name = self.path.lstrip("/")
                if re.match(r"^src_\d{3}\.ts$", name) and os.path.isfile(os.path.join(owner.folder, name)):
                    with open(os.path.join(owner.folder, name), "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp2t")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d/live.m3u8" % self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def visible(self):
        return min(len(self.segs), self.start_n + int((time.time() - self.t0) * self.rate))

    def playlist(self):
        n = self.visible()
        target = max(1, int(max(d for _, d in self.segs) + 0.999))
        out = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:%d" % target, "#EXT-X-MEDIA-SEQUENCE:0"]
        for name, d in self.segs[:n]:
            out += ["#EXTINF:%.6f," % d, name]
        if self.end and n >= len(self.segs):
            out.append("#EXT-X-ENDLIST")
        return "\n".join(out) + "\n"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
