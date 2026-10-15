"""「確かめる」の価値のカード(切り抜く価値があるか = 70 点以上か)の反映(notes:docs/design/v1-check-build.md・決定 3-41)。

出どころ 2 つ(カードは src/app/check/sources.py の value_auto・value_cand):
  value:auto  自動で採ってもう作った切り抜き。答え {choice: "send"} = 友人へ届ける / {choice: "drop"} = 要らない(どちらも 1 枚遅れで確定 = defer)
              どちらもホームの「続けて確認」と同じ口(ctx.hook("auto_review") = POST /api/cases/auto と同じ body)を呼ぶ。
              記録(live_feedback.jsonl の deliver / reject)はその口が残す。保留のうち(次のカードに答える・飛ばす・タブを閉じる / 隠すまで)に Z で戻せば何も起きない。
              届けた後・要らないにした後は戻せない(revert なし。要らないはごみ箱フォルダに TRASH_DAYS の間は残る)
  value:cand  まだ切り抜いていない候補。答え {choice: "adopt"} = 採用して書き出しを頼む / {choice: "reject"} = 不採用
              スタジオの PUT /api/video(画面の保存と同じ。put_video が feedback.jsonl の良い / 悪いを残す = eval_marks が読む形)で
              マークの status を adopted / rejected に。採用のあと POST /api/export を頼む(ベストエフォート。待ち・失敗は採用だけで済ませて
              applied.export に理由を残す。頼めたら応答の書き出しのジョブの id を applied.exportJob に)。
              Z = 頼んだ書き出しを POST /api/export/cancel {id: exportJob} で取り消し、GET /api/export で終わっていないことを確かめてから status を元に戻す
              (書き出しが済んだ・status が書き出し済みなら断る。ジョブが見つからない = スタジオを起動し直した = status で確かめる)。もう元の status なら何もしない
              (不採用を戻しても feedback.jsonl の「悪い」は残る = review/store.put_video の決まり。役割 7 で直す)
③ の層なので ① ④ を直に読まない: 案件の操作・スタジオの API は入口が ctx.hooks で渡す。
"""
from . import apply

AUTO_CHOICES = ("send", "drop")
CAND_CHOICES = ("adopt", "reject")
STATUS = {"adopt": "adopted", "reject": "rejected"}
TRIES = 3   # 画面の保存・書き出しとぶつかった(409)ときの読み直しの回数


def _check(choices):
    def check(ans):
        c = ans.get("choice") if isinstance(ans, dict) else None
        if c not in choices:
            raise ValueError("答えは %s のどれかです" % "・".join(choices))
        return {"choice": c}
    return check


def _code(code):
    return code if isinstance(code, int) and 400 <= code <= 599 else 502


def _msg(d, default):
    return str((d or {}).get("message") or default)[:300] if isinstance(d, dict) else default


def _need(target, *keys):
    t = target if isinstance(target, dict) else {}
    out = [t.get(k) for k in keys]
    if not all(isinstance(v, str) and v for v in out):
        raise apply.Refused("カードの指す切り抜きが分かりません", 409, "bad_target")
    return out


# ---------------------------------------------------------------- value:auto

def _auto_apply(ctx, card, ans):
    vid, mid = _need(card.get("target"), "videoId", "markId")
    op = "deliver" if ans["choice"] == "send" else "discard"
    code, d = ctx.hook("auto_review")({"op": op, "id": vid, "markId": mid})
    if code != 200 or not isinstance(d, dict):
        raise apply.Refused(_msg(d, "切り抜きを処理できませんでした"), _code(code), str(d.get("error") or "conflict") if isinstance(d, dict) else "conflict")
    if op == "deliver":
        return {"op": op, "videoId": vid, "markId": mid, "job": d.get("job")}
    return {"op": op, "videoId": vid, "markId": mid, "moved": d.get("moved"), "trash": d.get("trash"), "studio": d.get("studio")}


# ---------------------------------------------------------------- value:cand

def _studio(ctx, method, path, body=None):
    code, d = ctx.hook("studio")(method, path, body)
    if code is None:
        raise apply.Refused("切り抜きスタジオにつながりません: %s" % _msg(d, ""), 502, "studio_down")
    return code, d


def _set_status(ctx, vid, mid, status, only_from=None):
    """スタジオのマーク mid の status を変える(baseRev つき。ぶつかったら読み直して TRIES 回まで)。-> 変える前の status。
    only_from(集合)を渡すと、今の status がその中にないときは Refused(書き出し済みを戻さない)"""
    from urllib.parse import quote
    for _ in range(TRIES):
        code, d = _studio(ctx, "GET", "/api/video?id=" + quote(vid))
        if code == 404:
            raise apply.Refused("その配信はもうスタジオにありません", 409, "gone")
        if code != 200 or not isinstance(d, dict):
            raise apply.Refused(_msg(d, "スタジオが断りました(HTTP %s)" % code), _code(code), "studio_bad")
        v = d.get("video") or {}
        marks = [m for m in v.get("marks") or () if isinstance(m, dict)]
        hit = next((m for m in marks if m.get("id") == mid), None)
        if hit is None:
            raise apply.Refused("そのマークはもうありません", 409, "gone")
        prev = hit.get("status") or ""
        if prev == status:   # もうその status(やりかけの Z のやり直しを含む)= 書かない
            return prev
        if only_from is not None and prev not in only_from:
            raise apply.Refused("そのマークは今「%s」なので戻せません" % (prev or "候補"), 409, "changed")
        code, d = _studio(ctx, "PUT", "/api/video", {"id": vid, "marks": [dict(m, status=status) if m is hit else m for m in marks], "baseRev": v.get("rev")})
        if code == 409:   # 画面の保存・書き出しとぶつかった
            continue
        if code != 200:
            raise apply.Refused(_msg(d, "スタジオが断りました(HTTP %s)" % code), _code(code), "studio_bad")
        return prev
    raise apply.Refused("スタジオの配信が続けて書き換えられています(少し待ってもう一度)", 409, "busy")


def _cand_apply(ctx, card, ans):
    vid, mid = _need(card.get("target"), "videoId", "markId")
    prev = _set_status(ctx, vid, mid, STATUS[ans["choice"]])
    out = {"videoId": vid, "markId": mid, "before": prev, "status": STATUS[ans["choice"]]}
    if ans["choice"] == "adopt" and prev not in ("adopted", "exported"):
        try:   # 書き出しは別の呼び出し(スタジオは 1 度に 1 本 = 待ちなら採用だけで済ませる)
            code, d = ctx.hook("studio")("POST", "/api/export", {"id": vid, "markIds": [mid]})
            out["export"] = "started" if code == 200 else _msg(d, "HTTP %s" % code)
            if code == 200 and isinstance(d, dict) and isinstance(d.get("id"), str):
                out["exportJob"] = d["id"]   # Z で取り消すのは書き出しのジョブ(動画の id ではない。6e-1)
        except apply.Refused as e:
            out["export"] = e.message
    return out


def _cancel_export(ctx, jid):
    """頼んだ書き出しを取り消す。取り消せない(もう済んだ・止められない)なら Refused。ジョブが無い(スタジオを起動し直した)なら status に任せる"""
    from urllib.parse import quote
    if not isinstance(jid, str) or not jid:
        raise apply.Refused("頼んだ書き出しを特定できないので戻せません(スタジオの画面で確かめてください)", 409, "cannot_undo")
    code, d = _studio(ctx, "POST", "/api/export/cancel", {"id": jid})
    if code == 404:
        return
    if code != 200:
        raise apply.Refused(_msg(d, "書き出しを取り消せませんでした(HTTP %s)" % code), _code(code), "export_busy")
    code, d = _studio(ctx, "GET", "/api/export?id=" + quote(jid))
    if code == 200 and isinstance(d, dict) and d.get("state") == "done":
        raise apply.Refused("書き出しがもう済んだので戻せません(スタジオの画面で直してください)", 409, "changed")


def _cand_revert(ctx, row):
    ap = row.get("applied") or {}
    vid, mid = ap.get("videoId"), ap.get("markId")
    if not (isinstance(vid, str) and isinstance(mid, str)):
        raise apply.Refused("この答えは戻せません", 409, "cannot_undo")
    if ap.get("export") == "started":   # 頼んだ書き出しを止めてから戻す(書き出し済みになっていれば _set_status も断る)
        _cancel_export(ctx, ap.get("exportJob"))
    back = ap.get("before") if ap.get("before") in ("", "adopted", "rejected") else ""
    _set_status(ctx, vid, mid, back, only_from=(STATUS[(row.get("answer") or {}).get("choice")],) if (row.get("answer") or {}).get("choice") in STATUS else None)
    return {"videoId": vid, "markId": mid, "status": back}


apply.register("value", "auto", _auto_apply, None, check=_check(AUTO_CHOICES), defer=lambda a: True)   # 届ける・要らないはどちらも戻せない = 1 枚遅れで確定して Z を効かせる
apply.register("value", "cand", _cand_apply, _cand_revert, check=_check(CAND_CHOICES))
