"""「確かめる」の価値のカード(切り抜く価値があるか = 70 点以上か)の反映(notes:docs/design/v1-check-build.md・決定 3-41)。

出どころ 2 つ(カードは src/app/check/sources.py の value_auto・value_cand):
  value:auto  自動でできた切り抜きの品質の確認(送った物も送らなかった物も・2-8)。答え {choice: "good"} = 良い /
              {choice: "bad", reason?: AUTO_REASONS のどれか} = 悪い(理由は任意の札)/ {choice: "unknown"} = 不明(どちらとも言えない。理由なし =
              quality_unknown)。**記録だけ**(答えの行 = answers.jsonl に残す)。
              案件の操作(auto_review・届ける・要らない)は呼ばない = 送るかには効かせない(1-2)。すぐ記録・1 枚遅れはしない。
              Z は答えの記録の取り消し(revert は何も実物を変えない)
  value:cand  まだ切り抜いていない候補。答え {choice: "adopt"} = 採用して書き出しを頼む / {choice: "reject"} = 不採用
              スタジオの PUT /api/video(画面の保存と同じ。put_video が feedback.jsonl の良い / 悪いを残す = eval_marks が読む形)で
              マークの status を adopted / rejected に。採用のあと POST /api/export を頼む(ベストエフォート。待ち・失敗は採用だけで済ませて
              applied.export に理由を残す。頼めたら応答の書き出しのジョブの id を applied.exportJob に)。
              Z = 頼んだ書き出しを POST /api/export/cancel {id: exportJob} で取り消し、GET /api/export で終わっていないことを確かめてから status を元に戻す
              (書き出しが済んだ・status が書き出し済みなら断る。ジョブが見つからない = スタジオを起動し直した = status で確かめる)。もう元の status なら何もしない
              (不採用を戻しても feedback.jsonl の「悪い」は残る = review/store.put_video の決まり。役割 7 で直す)
③ の層なので ① ④ を直に読まない: 案件の操作・スタジオの API は入口が ctx.hooks で渡す。
"""
import secrets

from . import _doc, apply   # 同じ human/check の兄弟(register・Refused・答えの検査)
from .. import judgments as _judgments   # 同じ human の兄弟(人の判断の記録。③ の中の書き手)

AUTO_CHOICES = ("good", "bad", "unknown")   # unknown = 不明(記録だけ・理由は無い)
# 悪いときの理由の札(カードの reasons の候補。画面の文は src/app/check/sources.py が出す)。札は 1 つまで・任意
AUTO_REASONS = {"boring": "場面がつまらない", "long": "長すぎる", "short": "短すぎる", "edge": "端がずれている",
                "subtitle": "字幕がおかしい", "audio": "音が悪い", "other_person": "別の人が主役"}
CAND_CHOICES = ("adopt", "reject")
STATUS = {"adopt": "adopted", "reject": "rejected"}
TRIES = 3   # 画面の保存・書き出しとぶつかった(409)ときの読み直しの回数


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


# ---------------------------------------------------------------- value:auto(記録だけ)

def _auto_check(ans):
    """答えを検査して整える。理由は悪いのときだけ・札の中から(良いに付いた理由は捨てる)"""
    c = ans.get("choice") if isinstance(ans, dict) else None
    if c not in AUTO_CHOICES:
        raise ValueError("答えは %s のどれかです" % "・".join(AUTO_CHOICES))
    out = {"choice": c}
    if c == "bad" and ans.get("reason") is not None:
        r = ans.get("reason")
        if r not in AUTO_REASONS:
            raise ValueError("理由は札のどれかにしてください")
        out["reason"] = r
    return out


def _auto_apply(ctx, card, ans):
    """良い / 悪い + 理由 / 不明を judgments に 1 行足す(who self・quality_good / quality_bad / quality_unknown・via check)。
    答えの id は apply の後で決まる(apply.answer が作る)ので、key は乱数の印 ans:<token>。applied に judgment(行の id)と jkey を残し Z で retract する"""
    vid, mid = _need(card.get("target"), "videoId", "markId")
    key = "ans:" + secrets.token_hex(8)
    what = {"good": "quality_good", "bad": "quality_bad", "unknown": "quality_unknown"}[ans["choice"]]
    row = _judgments.record(ctx.app_dir, who="self", what=what, reason=ans.get("reason"), videoId=vid, markId=mid,
                            origin="auto", via="check", key=key)   # 出どころは auto(カードに request・live の印は無い)
    return dict({"videoId": vid, "markId": mid, "judgment": row["id"], "jkey": key}, **ans)


def _auto_revert(ctx, row):
    """判断の行を retract する(of = その行の id・key = 原本の key + ":retract"。書いてあれば何もしない = やり直しで二重にしない)。実物は変えない"""
    ap = row.get("applied") or {}
    jid, jkey = ap.get("judgment"), ap.get("jkey")
    if not (isinstance(jid, str) and isinstance(jkey, str)):
        return {}   # 判断の行を持たない答え(書き手より前の行)
    hit = {"id": jid, "key": jkey, "videoId": ap["videoId"], "markId": ap["markId"], "origin": "auto"}
    return {"judgment": jid} if _judgments.retract(ctx.app_dir, hit, "self", "check") else {}


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


apply.register("value", "auto", _auto_apply, _auto_revert, check=_auto_check)   # 記録だけ = すぐ確定・Z は記録の取り消し(defer なし)
apply.register("value", "cand", _cand_apply, _cand_revert, check=_doc.choice(CAND_CHOICES, label="答え"))
