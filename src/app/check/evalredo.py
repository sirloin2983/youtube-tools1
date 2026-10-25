"""評価用にした文書を、評価用の決まり(用語集・置換辞書・学習を使わない)で 1 本ずつ作り直す(10-25 ユーザー「学習用の一部を評価用に・Fable と相談してバランスよく」)。

学習用データのショートを評価用にした文書は、もとの文字起こしが用語集・置換辞書込みなので、そのままでは評価を汚す。
<app>/check/eval-redo.json の {"tids": [...]} を、入口の見回りが手の空いたときに 1 本ずつ「編集」の POST /api/eval-batch/redo-one
(evalbatch.eval_batch_redo_one = 同じ文書 id のまま今の設定で作り直す。前の機械の出力は recognition.runs の evalRedo に残る)へ頼む。
評価用の印が付き、評価用のフォルダの中へ取り込まれた(入口の起動時の整理)文書だけ。頼んだ・断られた物は一覧から外し、結果は "done" に残す。
"""
import os
import time

from ytt import fsio, settings as _settings

NAME = "eval-redo.json"


def tick(app_dir, read_doc, call, busy, log, now=None):
    """1 回分 -> 頼んだ文書の id か None。read_doc(tid) -> 文書か None・call(path, body) -> 応答(失敗は例外)"""
    p = os.path.join(app_dir, "check", NAME)
    st = fsio.read_json_or(p, {}, kind=dict)
    todo = [t for t in st.get("tids") or () if isinstance(t, str)]
    if not todo or busy():
        return None
    for tid in todo:
        doc = read_doc(tid)
        if not doc or doc.get("evalSet") is not True or not _settings.in_eval_dir(doc.get("sourcePath")):
            continue   # まだ評価用のフォルダへ取り込まれていない = 起動時の整理を待つ
        st["tids"] = [t for t in todo if t != tid]
        try:
            call("/api/eval-batch/redo-one", {"id": tid, "baseUpdatedAt": doc.get("updatedAt")})
            res = "頼んだ"
        except Exception as e:   # noqa: BLE001  (断られた = 理由を残して外す)
            res = "断られた: %s" % str(e)[:160]
        st.setdefault("done", {})[tid] = {"at": int(time.time() if now is None else now), "result": res}
        fsio.write_json(p, st, indent=None)
        log("評価用の作り直し: %s を%s(残り %d 本)" % (tid, res, len(st["tids"])))
        return tid
    return None
