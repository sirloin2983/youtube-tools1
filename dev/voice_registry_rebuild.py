"""声の登録簿を「確かめる」の答えから作り直す道具(11-03 情報をまとめる所の 1。本体は src/human/check/voicebook.py)。
  py -3.12 dev/voice_registry_rebuild.py            空回し: 作った登録簿と今の登録簿の差を出すだけ(何も書かない。足りない特徴は音から取る)
  py -3.12 dev/voice_registry_rebuild.py --apply    書く(音が無く特徴の取れない材料は入れない = 11-03 ユーザー「元の音がないものは全部消していい」。前の登録簿は .bak-<時刻> に写す)
  py -3.12 dev/voice_registry_rebuild.py --apply --strict   今の登録簿の材料が 1 つでも消えるなら書かない
  py -3.12 dev/voice_registry_rebuild.py --unknown  分からないにしたカードの一覧(unknown-voice.jsonl)を答えから作り直す
入口が動いている間の --apply は、入口のジョブ voice-rebuild と同じ登録簿を書くので、入口を止めてから流す(ふだんは入口の見回りが作り直す)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.stdout.reconfigure(encoding="utf-8")

from ytt import workdata  # noqa: E402
from flow import wire, diar as _diar  # noqa: E402
from pipeline.transcribe import tx_engines, worker_client  # noqa: E402
from human.check import voicebook  # noqa: E402

wire.setup_places()
workdata.set_data_dir(os.path.join(os.environ["LOCALAPPDATA"], "youtube-tools", "transcribe"))
tx_engines.ENGINE_DIR = workdata.DATA_DIR   # 声の特徴のモデルは作業データの models(入口と同じ)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--unknown", action="store_true")
    ap.add_argument("--json", help="差をこの JSON に書く")
    a = ap.parse_args()
    app_dir = os.path.join(os.path.dirname(workdata.DATA_DIR), "app")
    if a.unknown:
        from app.check import voice_unknown
        print("分からないの一覧を作り直しました: %d 件" % voice_unknown.write_index(app_dir))
        return
    worker_client.IN_WORKER = True   # 声の特徴をこのプロセスで取る(ワーカーの中と同じ道)
    emb = _diar.learn_embedding("")
    cur = _diar.load_voices(emb)
    if a.apply:
        res = voicebook.rebuild(app_dir, emb, log=print, strict=a.strict)
    else:
        res = voicebook.build(app_dir, emb, voices=cur)
    d = voicebook.diff(cur, res["voices"])
    gone = voicebook.lost(app_dir, cur, res["voices"])
    for x in d:
        if x["before"] != x["after"] or (x["cos"] or 0) < 0.999:
            print("%-14s 前 %s 行 %s 秒 → 後 %s 行 %s 秒  近さ %s" % (x["name"], x["before"]["rows"], x["before"]["sec"], x["after"]["rows"], x["after"]["sec"], x["cos"]))
    print("人 %d → %d・新しく取った特徴 %d・取れない材料 %d・今の登録簿から消える材料 %d・触らない人 %s"
          % (len(cur), len(res["voices"]), res["added"], len(res["missing"]), len(gone), res["kept"]))
    for it in res["missing"][:20]:
        print("  取れない:", it["name"], it["doc"], it["row"], it["answer"])
    if a.json:
        json.dump({"diff": d, "missing": res["missing"], "lost": gone}, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
