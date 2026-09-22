"""run_analyze の通し試験(疑似モード: 合成音声 + 合成チャット)。 実行: python3 e2e_analyze.py
音声のイベントの LAG 秒後にチャットが増える配信を作り、遅れが自動推定され、候補のピークが音声側の時刻に合うことを確かめる。"""
import json, math, os, random, shutil, struct, sys, tempfile, wave
os.environ["STUDIO_FAKE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze, common

DUR, LAG = 1500, 14
EVENTS = [200, 420, 640, 860, 1080, 1300]
tmp = tempfile.mkdtemp()
common.set_home(tmp)
rnd = random.Random(3)
# 音声: 小さな雑音 + イベントで大きな音(笑い声のような高い周波数を含む)
sr = 8000
frames = bytearray()
for t in range(DUR):
    burst = any(e <= t < e + 5 for e in EVENTS)
    for i in range(sr):
        v = rnd.gauss(0, 500 if not burst else 9000) + (6000 * math.sin(2 * math.pi * 2500 * i / sr) if burst else 0)
        frames += struct.pack("<h", max(-32768, min(32767, int(v))))
wav = os.path.join(tmp, "a.wav")
with wave.open(wav, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(bytes(frames))
# チャット
chat = os.path.join(tmp, "chat.jsonl")
with open(chat, "w", encoding="utf-8") as f:
    for t in range(DUR):
        n = 2 + (25 if any(e + LAG <= t < e + LAG + 8 for e in EVENTS) else 0) + rnd.randint(0, 2)
        for k in range(n):
            f.write(json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": str(t * 1000 + k * 10), "actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {"message": {"runs": [{"text": "草" if k % 3 == 0 else "はい"}]}}}}}]}}) + "\n")
os.environ["STUDIO_FAKE_MEDIA"] = wav
os.environ["STUDIO_FAKE_CHAT"] = chat
src = {"kind": "youtube", "videoId": "abcdefghijk", "name": "x"}

def run(**kw):
    spec = analyze.make_spec(src, analyze.validate_settings(dict({"useComments": False, "count": 6, "length": 60, "sensitivity": "normal", "noCache": True}, **kw)))
    job = analyze.new_job(spec)
    analyze.run_analyze(job)
    assert job["state"] == "done", (job["state"], job["error"])
    return job["result"]

ok = True
r = run()
lagw = [w for w in r["warnings"] if "自動推定" in w]
print("警告:", r["warnings"])
est = r["spec"]["lag"]
print("使われた遅れ:", est, "(正解 %d)" % LAG)
peaks = sorted(c["peak"] for c in r["candidates"])
print("ピーク:", peaks, " イベント:", EVENTS)
ok &= bool(lagw) and abs(est - LAG) <= 2
ok &= all(any(abs(p - e) <= 12 for e in EVENTS) for p in peaks) and len(peaks) >= 5
r2 = run(lagAuto=False, lag=8)
print("自動推定オフ: 遅れ =", r2["spec"]["lag"], "/ 警告に自動推定なし =", not any("自動推定" in w for w in r2["warnings"]))
ok &= r2["spec"]["lag"] == 8 and not any("自動推定しました" in w for w in r2["warnings"])
ok &= r2["spec"]["lagAuto"] is False
# 付加情報・コメント・保存データ(archive)
meta = os.path.join(tmp, "meta.json")
json.dump({"title": "【歌枠】朝まで歌う", "channel": "Ch", "categories": ["Music"], "tags": ["歌"], "view_count": 100, "duration": DUR,
           "heatmap": [{"start_time": 0, "end_time": 100, "value": 1.0}], "chapters": [{"start_time": 0, "end_time": 60, "title": "開始"}]}, open(meta, "w", encoding="utf-8"), ensure_ascii=False)
com = os.path.join(tmp, "comments.json")
json.dump([{"text": "3:40 ここ最高", "likes": 5}, {"text": "0:10 a\n5:00 b\n10:00 c", "likes": 1}], open(com, "w", encoding="utf-8"), ensure_ascii=False)
os.environ["STUDIO_FAKE_META"], os.environ["STUDIO_FAKE_COMMENTS"] = meta, com
r3 = run(useComments=True, typePreset=True)
print("警告:", r3["warnings"])
print("配信タイプ:", r3["type"], " counts:", r3["counts"])
ok &= r3["type"] == "歌枠" and any("歌枠" in w and "音声×0.6" in w for w in r3["warnings"])
ok &= r3["counts"]["meta"] is True and r3["counts"]["heatmap"] == 1
ar = analyze.load_archive("abcdefghijk")
ok &= ar is not None and ar["meta"]["chapters"] == [[0.0, 60.0, "開始"]] and ar["type"] == "歌枠"
ok &= len(ar["full"]) == len(ar["band"]) == ar["n"] and ar["chat"] is not None and len(ar["chat"]["uniq"]) == ar["n"]
ok &= ar["stamps"] is not None and len(ar["stamps"]) == 4 and ar["stamps"][0][3].startswith("3:40")
ok &= len(ar["runs"]) == 3 and ar["runs"][-1]["spec"]["typePreset"] is True and len(ar["runs"][-1]["candidates"]) >= 5   # 解析3回分の履歴
print("archive: n=%d runs=%d stamps=%d" % (ar["n"], len(ar["runs"]), len(ar["stamps"])))
r4 = run(useComments=True, typePreset=True, typeOverride="ゲーム")   # 手動でタイプを指定
ok &= r4["type"] == "ゲーム" and not any("配信タイプ" in w for w in r4["warnings"])   # ゲームは倍率なし → 注意書きなし
r5 = run(typePreset=False)
ok &= not any("配信タイプ" in w for w in r5["warnings"]) and r5["type"] == "歌枠"     # オフでも、タイプは記録する
# 付加情報が取れなくても解析は成功し、注意書きが出る
os.environ["STUDIO_FAKE_META"] = os.path.join(tmp, "none.json")
r6 = run()
ok &= any("付加情報" in w for w in r6["warnings"]) and r6["type"] is None
print("結果:", "OK" if ok else "NG")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if ok else 1)
