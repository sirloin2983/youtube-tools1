"""「確かめる」の答えを実物へ反映する土台(V1 の V0。docs/design/v1-check-build.md の 3-2・3-3)。

カードの種類(kind)と出どころ(source)ごとに「反映の関数」を登録し(register)、入口の口(POST /api/check/answer・/skip・/flush)が呼ぶ:
  answer(ctx, card, body) -> 答えを検査 → 前の保留を先に確定(flush)→ 反映(または保留)→ answers.jsonl に 1 行
  undo(ctx, answer_id)    -> Z。保留のままなら記録の取り消しだけ・反映済みなら登録した revert で逆の操作 → 戻した行
  flush(ctx)              -> 保留(1 枚遅れで確定する答え)を全部確定する(次のカードに答えた・飛ばした・画面を離れた)
  skip(ctx, card_id)      -> 保留を確定してから、そのカードを今日の間だけ後ろへ(skip.json)
登録の形(V2 の 4 本が足す。V0 では何も登録しない = 登録の無い種類の答えは 409 not_ready で断る = 実物を変えずにカードだけ消えることは無い):
  register(kind, source, apply, revert=None, check=None, defer=None)
    check(answer) -> 検査して整えた答え(違えば ValueError = 400)
    apply(ctx, card, answer) -> 何を変えたか(dict。記録の applied に入る・revert に渡る)。断るときは Refused
    revert(ctx, row) -> 何を戻したか(dict)。row = 記録の答えの行(applied は確定の行の物に差し替え済み)。None = 戻せない(Z は 409)
    defer(answer) -> True なら 1 枚遅れで確定する(決定 3-41: [送る] = 友人へ届ける。次のカードに答えた時・離れた時に apply を呼ぶ)
card は ⑤ eval/check の待ち行列がサーバーの側で組み直した物(画面の送った target は信じない)。反映に使うのは id・kind・source・case・target だけ
(保留の確定は記録の行から card を組み直すので、それ以外の欄に頼らない)。
③ の層なので ① を直に読まない・④ manage を読まない: 案件の操作(cases.auto_review など)は入口が ctx.hooks で渡す。
"""
import json
import threading

from . import answerlog   # 同じ human/check の兄弟

MAX_ANSWER_BYTES = 4096        # 答え(answer)を JSON にしたときの大きさの上限
MAX_MS = 3600 * 1000           # 答えるまでにかかった時間(ms)の上限(超えたら記録しない)
_REG = {}
_lock = threading.RLock()      # 答え・戻す・確定・飛ばすを 1 つずつ(同じカードに二重に答えない・保留の確定を二重にしない)


class Refused(Exception):
    """断った理由(code = HTTP の番号・error = 短い名前・message = 画面の文)"""

    def __init__(self, message, code=409, error="conflict"):
        super().__init__(message)
        self.code, self.error, self.message = code, error, message


class Context:
    """反映に要る物。app_dir = 入口の作業データ(app。記録の置き場所)・root = ツールの親のフォルダ(src)・env = 置き場所の環境変数(テスト)・
    hooks = 入口が渡す関数(③ が読めない層の操作。例 auto_review(body) -> (番号, JSON)・studio(method, path, body) -> (番号, JSON))"""

    def __init__(self, app_dir, root=None, env=None, hooks=None, **extra):
        self.app_dir, self.root, self.env = app_dir, root, env
        self.hooks = dict(hooks or {})
        for k, v in extra.items():
            setattr(self, k, v)

    def hook(self, name):
        fn = self.hooks.get(name)
        if fn is None:
            raise Refused("この操作は今の入口では使えません(%s)" % name, 503, "unavailable")
        return fn


class Applier:
    def __init__(self, kind, source, apply, revert=None, check=None, defer=None):
        self.kind, self.source, self.apply, self.revert, self.check, self.defer = kind, source, apply, revert, check, defer


def register(kind, source, apply, revert=None, check=None, defer=None):
    """種類と出どころの反映の関数を登録する(同じ組は上書き)。-> Applier"""
    if not callable(apply):
        raise TypeError("apply は関数にしてください")
    ap = Applier(kind, source, apply, revert, check, defer)
    _REG[(kind, source)] = ap
    return ap


def unregister(kind, source):
    _REG.pop((kind, source), None)


def registered(kind=None, source=None):
    """登録した組 [(kind, source)]。kind・source を渡すとその組があるかを真偽で"""
    if kind is not None:
        return (kind, source) in _REG
    return sorted(_REG)


def _check_body(body):
    answer = body.get("answer")
    if answer is None:
        raise Refused("答え(answer)がありません", 400, "bad_request")
    try:
        size = len(json.dumps(answer, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise Refused("答え(answer)の形が正しくありません", 400, "bad_request")
    if size > MAX_ANSWER_BYTES:
        raise Refused("答え(answer)が大きすぎます", 413, "size")
    ms = body.get("ms")
    ms = int(ms) if isinstance(ms, (int, float)) and not isinstance(ms, bool) and 0 <= ms <= MAX_MS else None
    return answer, ms


def _card_of_row(row):
    return {"id": row.get("card"), "kind": row.get("kind"), "source": row.get("source"), "case": row.get("case"), "target": row.get("target") or {}}


def _flush_locked(ctx, st):
    """保留を全部確定する(_lock を持って呼ぶ)。-> [{answer, card, applied | failed}]"""
    out = []
    for row in st.held():
        ap = _REG.get((row.get("kind"), row.get("source")))
        at = answerlog.now_ms()
        try:
            if ap is None:
                raise Refused("この種類の答えを反映する部品がありません", 409, "not_ready")
            applied = ap.apply(ctx, _card_of_row(row), row.get("answer")) or {}
            line = {"id": answerlog.new_id(at), "at": at, "confirm": row["id"], "applied": applied}
            out.append({"answer": row["id"], "card": row.get("card"), "applied": applied})
        except (Refused, ValueError, OSError) as e:   # 失敗は記録して次へ(同じ保留を何度も試さない。画面は next の failed で 1 行出す)
            why = getattr(e, "message", None) or str(e) or e.__class__.__name__
            line = {"id": answerlog.new_id(at), "at": at, "confirm": row["id"], "failed": why[:300]}
            out.append({"answer": row["id"], "card": row.get("card"), "failed": line["failed"]})
        answerlog.append(ctx.app_dir, line)
    return out


def flush(ctx):
    """保留を確定する(POST /api/check/flush。画面を離れたとき)。-> {ok, flushed}"""
    with _lock:
        return {"ok": True, "flushed": _flush_locked(ctx, answerlog.state(ctx.app_dir))}


def answer(ctx, card, body):
    """カード card に答える。body = {answer, ms?, guess?}。-> {ok, answer: 答えの id, applied, held, flushed}。断るときは Refused"""
    body = body if isinstance(body, dict) else {}
    ans, ms = _check_body(body)
    kind, source = card.get("kind"), card.get("source")
    with _lock:
        st = answerlog.state(ctx.app_dir)
        if card["id"] in st.by_card:
            raise Refused("このカードにはもう答えています(Z で戻してから答え直してください)", 409, "answered")
        ap = _REG.get((kind, source))
        if ap is None:
            raise Refused("この種類のカードの答えはまだ受け付けていません", 409, "not_ready")
        if ap.check is not None:
            try:
                ans = ap.check(ans)
            except ValueError as e:
                raise Refused(str(e) or "答えが正しくありません", 400, "bad_request")
        flushed = _flush_locked(ctx, st)   # 前の保留を先に確定(1 枚遅れ。3-3)
        held = bool(ap.defer and ap.defer(ans))
        at = answerlog.now_ms()
        applied = {} if held else (ap.apply(ctx, card, ans) or {})
        row = {"id": answerlog.new_id(at), "at": at, "kind": kind, "source": source, "card": card["id"], "case": card.get("case"),
               "target": card.get("target") or {}, "guess": card.get("guess"), "answer": ans, "ms": ms, "applied": applied}
        if held:
            row["held"] = True
        try:
            answerlog.append(ctx.app_dir, row)
        except OSError:
            if not held and ap.revert is not None:   # 記録できない答えは実物にも残さない(Z で戻せなくなるため)
                try:
                    ap.revert(ctx, row)
                except Exception:
                    pass
            raise
        return {"ok": True, "answer": row["id"], "card": card["id"], "applied": applied, "held": held, "flushed": flushed}


def undo(ctx, answer_id):
    """Z。答え answer_id を戻す。-> {ok, answer, card, reverted}。無い = 404・もう戻した / 戻せない = 409"""
    if not isinstance(answer_id, str) or not answerlog.ID_RE.match(answer_id):
        raise Refused("戻す答えの指定(undo)が正しくありません", 400, "bad_request")
    with _lock:
        st = answerlog.state(ctx.app_dir)
        row = st.answers.get(answer_id)
        if row is None:
            raise Refused("その答えはありません", 404, "not_found")
        if answer_id in st.undone:
            raise Refused("その答えはもう戻しました", 409, "undone")
        conf = st.confirmed.get(answer_id)
        if row.get("held") and (conf is None or conf.get("failed")):
            reverted = {"held": True}   # まだ実物に反映していない(届けていない)= 記録の取り消しだけ
        else:
            ap = _REG.get((row.get("kind"), row.get("source")))
            if ap is None or ap.revert is None:
                raise Refused("この答えは戻せません", 409, "cannot_undo")
            reverted = ap.revert(ctx, dict(row, applied=conf.get("applied") if conf else row.get("applied"))) or {}
        at = answerlog.now_ms()
        answerlog.append(ctx.app_dir, {"id": answerlog.new_id(at), "at": at, "undo": answer_id, "reverted": reverted})
        return {"ok": True, "answer": answer_id, "card": row.get("card"), "reverted": reverted}


def skip(ctx, card_id):
    """カードを今日の間だけ後ろへ(保留は先に確定)。-> {ok, flushed}"""
    with _lock:
        flushed = _flush_locked(ctx, answerlog.state(ctx.app_dir))
        answerlog.add_skip(ctx.app_dir, card_id)
        return {"ok": True, "flushed": flushed}
