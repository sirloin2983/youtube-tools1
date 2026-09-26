#!/usr/bin/env python3
"""見本のデータで入口と3ツールを動かす(画面の見直し・画面の写真・手での確認用)。本物の作業データには触らない。

    python tools/demo_env.py [--port 8750] [--dir <作業フォルダ>] [--streams 36] [--seed 7]

一時フォルダ(--dir を指定すればそこ)にリポジトリのツールを写し、疑似モード(スタジオ STUDIO_FAKE・文字起こし TRANSCRIBE_BACKEND=fake)で
入口に3つとも取り込んで待ち受ける。Ctrl+C で終わる(一時フォルダは消す。--dir を指定したときは残す)。

見本のデータ(名前はすべて架空):
  - スタジオ: 配信 --streams 本(8人の配信者・解析済み/未解析・マーク(候補・採用・不採用・書き出し済み))
  - 書き出した切り抜き: 短い動画(VP9 + Opus を mp4 に入れたもの。Playwright の chromium でも再生できる)と隣の .clip.json
  - 文字起こし: 切り抜きごと(校正の進み具合・カット済の行・話者がいろいろ)+ 配信まるごとの長いもの・評価用・スタジオと紐づかないもの。
    作った日は約90日に散らす(履歴がたくさんある状態)
  - パック: 一部の切り抜きの隣に <名前>_pack フォルダ(案件の画面の「パック済み」)
  - 案件: 一部に状態・メモ
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "app"))
sys.path.insert(0, REPO)

CHANNELS = ["星見ルナ", "朝霧ソラ", "猫宮こはく", "雷堂ジン", "白銀ユキ", "緋ノ宮かえで", "海月ミオ", "鷹野レン"]
GENRES = [("雑談", ["【雑談】{n}回目の朝活!", "【作業雑談】まったり話そう", "【雑談】最近あったこと全部話す"]),
          ("ゲーム", ["【APEX】ランクでダイヤ目指す", "【マイクラ】拠点づくり #{n}", "【ホラゲー】絶対に叫ばない", "【スト6】初見さん歓迎 ランクマ"]),
          ("歌枠", ["【歌枠】リクエストいっぱい歌う", "【歌枠】アニソン縛り {n}曲"]),
          ("コラボ", ["【コラボ】4人で協力プレイ!", "【凸待ち】誰か来て…"])]
LINES = ["こんばんは、今日も来てくれてありがとう", "えーっと、何の話だっけ", "それでね、昨日コンビニ行ったら", "いやいやいや、待って待って",
         "ここ絶対いけるって!", "あっ、やばいやばいやばい", "え、今の見た?", "ちょっと待ってね、水飲む", "じゃあ次いきましょう",
         "コメントありがとう、読むね", "それは知らなかった", "もう一回やらせて!", "よし、勝った!", "うそでしょ…", "今日はこのへんで終わろうかな",
         "みんなおつかれさまでした", "あのー、えっと", "なんか今日調子いいかも", "これ見てほしいんだけど", "それってどういうこと?"]
SPEAKERS = [{"id": "S1", "name": "本人"}, {"id": "S2", "name": "ゲスト"}]


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_media(dirpath, n=3, sec=40):
    """見本の動画(色と音の違う n 本)。VP9 + Opus を mp4 に入れる(H.264 を再生できない Playwright の chromium でも再生できる)"""
    os.makedirs(dirpath, exist_ok=True)
    out = []
    for i in range(n):
        p = os.path.join(dirpath, "sample%d.mp4" % i)
        if not os.path.exists(p):
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=%d" % sec,
                 "-f", "lavfi", "-i", "sine=frequency=%d:duration=%d" % (220 + 110 * i, sec),
                 "-c:v", "libvpx-vp9", "-b:v", "300k", "-deadline", "realtime", "-cpu-used", "8", "-threads", "1", "-c:a", "libopus", "-shortest", p])
        out.append(p)
    return out


def seed(tmp, rnd, streams, samples):
    from ytt_core import schemas
    studio_home = os.path.join(tmp, "studio-home")
    os.makedirs(studio_home, exist_ok=True)
    txdir = os.path.join(tmp, "transcribe-tool", "transcripts")
    os.makedirs(txdir, exist_ok=True)
    now = time.time()
    videos, cases = {}, {}
    n_tx = 0

    def write_tx(doc):
        nonlocal n_tx
        with open(os.path.join(txdir, doc["id"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        n_tx += 1

    def segments(count, dur, proof_ratio, cut_ratio, two):
        segs, t = [], 0.4
        step = max(1.2, (dur - 1) / max(1, count))
        for i in range(count):
            a, b = round(t, 2), round(min(dur - 0.1, t + step * rnd.uniform(0.6, 0.95)), 2)
            if b <= a:
                break
            s = {"id": "s%d" % (i + 1), "start": a, "end": b, "text": rnd.choice(LINES), "speaker": ("S2" if two and rnd.random() < 0.3 else "S1"),
                 "flag": "!要確認: 聞き取りにくい" if rnd.random() < 0.08 else ""}
            if rnd.random() < proof_ratio:
                s["proofed"] = True
            if rnd.random() < cut_ratio:
                s["cutState"] = "cut"
            segs.append(s)
            t += step
        return segs

    for k in range(streams):
        ch = CHANNELS[k % len(CHANNELS)]
        genre, titles = rnd.choice(GENRES)
        title = rnd.choice(titles).format(n=rnd.randint(2, 180))
        vid = "demo%07d" % k
        age = rnd.uniform(0, 90) * 86400
        created = int((now - age) * 1000)
        dur = rnd.choice([3600, 5400, 7200, 10800])
        analyzed = rnd.random() < 0.8
        marks = []
        exported = 0
        for m in range(rnd.randint(3, 9) if analyzed else rnd.randint(0, 2)):
            s = round(rnd.uniform(60, dur - 120), 1)
            e = round(s + rnd.choice([30, 40, 45, 60]), 1)
            st = rnd.choices(["", "adopted", "rejected", "exported"], [3, 2, 1, 2])[0]
            mk = {"id": "m%d" % m, "start": s, "end": e, "label": rnd.choice(["見どころ", "叫び", "神プレイ", "笑い", "名言", ""]), "status": st,
                  "src": "auto" if analyzed and rnd.random() < 0.7 else "manual"}
            if mk["src"] == "auto":
                mk.update({"score": round(rnd.uniform(2, 9.5), 2), "reasons": ["音量の山", "チャットの量"], "auto0": [s, e]})
            if st == "exported":
                exported += 1
                d = os.path.join(tmp, "exports", "%s_%s" % (ch, vid))
                os.makedirs(d, exist_ok=True)
                clip = os.path.join(d, "%02d_%s.mp4" % (exported, mk["label"] or "切り抜き"))
                shutil.copyfile(samples[(k + m) % len(samples)], clip)
                mk.update({"file": os.path.basename(clip), "path": clip})
                cj = schemas.build_clip(clip, 40.0, {"kind": "youtube", "videoId": vid, "title": title}, (s, s + 40), mk,
                                        {"mode": "precise"}, {"name": "clip-studio", "version": "demo"})
                with open(schemas.clip_path_for(clip), "w", encoding="utf-8") as f:
                    json.dump(cj, f, ensure_ascii=False)
                r = rnd.random()   # この切り抜きの文字起こし: 無い / 未校正 / 校正中 / 校正済み
                if r > 0.15:
                    proof = 0.0 if r < 0.35 else (1.0 if r > 0.75 else rnd.uniform(0.2, 0.8))
                    tcreated = created + int(rnd.uniform(0.2, 5) * 86400000)
                    tid = "%012x" % rnd.getrandbits(48)
                    write_tx({"schema": "transcribe/v1", "id": tid, "title": "%s %s" % (title, mk["label"] or "切り抜き"), "sourcePath": clip,
                              "sourceName": os.path.basename(clip), "start": 0, "end": None, "whole": True, "duration": 40.0, "model": "large-v3",
                              "language": "ja", "speakers": SPEAKERS if genre == "コラボ" else SPEAKERS[:1],
                              "segments": segments(rnd.randint(12, 30), 40.0, proof, 0.15 if proof > 0 else 0.0, genre == "コラボ"),
                              "createdAt": tcreated, "updatedAt": tcreated + int(rnd.uniform(0, 3) * 86400000), "clip": cj})
                    if r > 0.6:   # パックも作った(中身は印だけ。パックの有無は中の cut-plan.json で判定する: ytt_core/txindex.pack_info)
                        pd = os.path.splitext(clip)[0] + "_pack"
                        os.makedirs(pd, exist_ok=True)
                        for n in ("cut-plan.json", "textplus-import.json"):
                            with open(os.path.join(pd, n), "w", encoding="utf-8") as f:
                                f.write("{}")
            marks.append(mk)
        videos[vid] = {"id": vid, "kind": "youtube", "title": title, "channel": ch, "duration": dur, "marks": marks,
                       "analysis": {"at": created, "counts": {"audio": 1}} if analyzed else None, "createdAt": created, "updatedAt": created}
        if exported and rnd.random() < 0.4:
            cases[vid] = {"status": rnd.choice(["working", "posted", "skipped"]), "memo": rnd.choice(["", "サムネ候補あり", "BGM の許諾を確認"]),
                          "statusUpdatedAt": int(now * 1000)}
    # スタジオと紐づかない文字起こし(手元の動画・配信まるごと・評価用)
    for i in range(24):
        tcreated = int((now - rnd.uniform(0, 90) * 86400) * 1000)
        whole = i % 6 == 0
        src = samples[i % len(samples)]
        write_tx({"schema": "transcribe/v1", "id": "%012x" % rnd.getrandbits(48),
                  "title": ("【配信まるごと】" if whole else "") + rnd.choice(["手元の録画 %d" % i, "打ち合わせメモ", "テスト用の音声", "昔の配信アーカイブ"]),
                  "sourcePath": src, "sourceName": os.path.basename(src), "start": 0, "end": None, "whole": True, "duration": 40.0, "model": "large-v3",
                  "language": "ja", "speakers": SPEAKERS[:1], "segments": segments(120 if whole else rnd.randint(8, 25), 40.0, rnd.random() * 0.5, 0, False),
                  "createdAt": tcreated, "updatedAt": tcreated, "evalSet": i % 8 == 3})
    with open(os.path.join(studio_home, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "clip-studio/v1", "groups": {}, "videos": videos}, f, ensure_ascii=False)
    os.makedirs(os.path.join(tmp, "app"), exist_ok=True)
    with open(os.path.join(tmp, "app", "cases.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "youtube-tools-cases/v1", "cases": cases}, f, ensure_ascii=False)
    return studio_home, len(videos), n_tx


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8750)
    ap.add_argument("--dir", default="")
    ap.add_argument("--streams", type=int, default=36)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    tmp = os.path.abspath(a.dir) if a.dir else tempfile.mkdtemp(prefix="ytt-demo-")
    keep = bool(a.dir)
    os.environ.update({"YTT_DATA_DIR": "inplace", "YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime"), "STUDIO_FAKE": "1",
                       "TRANSCRIBE_BACKEND": "fake", "STUDIO_HOME": os.path.join(tmp, "studio-home")})
    import launch as L   # noqa: E402  (環境変数を決めてから読む)
    import mount as M    # noqa: E402
    from test_launch import _copy_tool  # noqa: E402
    fresh = not os.path.isdir(os.path.join(tmp, "clip-studio"))
    os.environ["STUDIO_FAKE_MEDIA"] = os.path.join(tmp, "media", "sample0.mp4")   # 疑似モードの解析・書き出しに使う動画(② 解析も動く)
    for s in L.TOOLS:
        if fresh:
            _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
    if fresh:
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
        samples = make_media(os.path.join(tmp, "media"))
        _, nv, nt = seed(tmp, random.Random(a.seed), a.streams, samples)
        print("見本のデータ: 配信 %d 本・文字起こし %d 件" % (nv, nt), flush=True)
    ports = dict(zip(L.TOOL_IDS, (a.port + 1, a.port + 2, a.port + 3)))
    sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.3, log=lambda m: print(m, flush=True), ports=ports, mounts=tuple(M.MOUNTS))
    srv, port = L.make_server(a.port, sup)
    if srv is None:
        raise SystemExit("ポート %d は使用中です" % a.port)
    sup.attach(srv)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    sup.start_all()
    sup.start_monitor()
    print("READY http://localhost:%d/  (作業フォルダ %s)" % (port, tmp), flush=True)
    try:
        while th.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.closing.set()
        sup.close()
        sup.stop_all()
        sup.unmount_all()
        srv.shutdown()
        srv.server_close()
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
