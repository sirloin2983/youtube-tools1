"""覚えた声を 1 行ずつ外してまとめ直す道具(human/proof/voicerebuild。10-25)。本物の作業データの登録簿を書き換える(前の版は .bak-<時刻> に写す)。

  py -3.12 dev/voice_rebuild.py --name 白上フブキ --exclude 095774f3ccb7#s92
  py -3.12 dev/voice_rebuild.py --name 白銀ノエル --exclude 7ccb3f25de7f#s7 --dry-run

声を覚えるジョブと同時に動かさない: 覚え直しの一時止め(human/check/voice.RELEARN_PAUSED)の間に流す(止まっていなければ断る)。
入口が動いていても、文書は読むだけ・登録簿は登録簿のロック(同じプロセスの中だけ)の外 = 覚えるジョブが動いていないことが前提。
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="voice_rebuild.py", description="覚えた声を 1 行ずつ外してまとめ直す")
    ap.add_argument("--name", required=True, help="登録簿の名前")
    ap.add_argument("--exclude", action="append", default=[], help="外す行(文書#行。いくつでも)")
    ap.add_argument("--dry-run", action="store_true", help="書かずに、今の登録簿の learnedFrom と外す行だけを見る")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    from ytt import workdata
    from flow import wire, diar
    wire.setup_places()
    workdata.set_data_dir(os.path.join(os.environ["LOCALAPPDATA"], "youtube-tools", "transcribe"))
    from human.check import voice
    from human.proof import voicerebuild
    emb = diar.learn_embedding(diar.default_embedding())
    v = diar.load_voices(emb).get(a.name)
    if not isinstance(v, dict):
        print("登録簿にいません:", a.name)
        return 1
    rows = ["%s#%s" % (x.get("doc"), r) for x in v.get("learnedFrom") or () if isinstance(x, dict) for r in x.get("rows") or ()]
    print("%s: %.1f 秒・learnedFrom %d 文書・行の控え %d 行" % (a.name, float(v.get("sec") or 0), len(v.get("learnedFrom") or ()), len(rows)))
    for x in a.exclude:
        print("  外す:", x, "(learnedFrom にある)" if x in rows else "(learnedFrom の行の控えに無い = 文書の決まりの行として外す)")
    if a.dry_run:
        return 0
    if not voice.RELEARN_PAUSED:
        print("覚え直しの一時止め(RELEARN_PAUSED)が外れているので流しません(覚えるジョブとぶつかる)")
        return 1
    got = voicerebuild.rebuild(emb, a.name, a.exclude, log=print)
    print("済み:", got["rows"], "行・", got["sec"], "秒・前の版", got["backup"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
