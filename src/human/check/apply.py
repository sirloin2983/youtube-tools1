"""「確かめる」の答えを実物へ反映する土台(notes:docs/design/v1-check-build.md の 3-2・3-3)。

カードの種類(kind)と出どころ(source)ごとに「反映の関数」を登録し(register)、入口の口(POST /api/check/answer・/skip・/flush)が呼ぶ:
  answer(ctx, card, body) -> 答えを検査 → この画面の前の保留を先に確定(flush)→ 反映(または保留)→ answers.jsonl に 1 行
  undo(ctx, answer_id)    -> Z。保留のままなら記録の取り消しだけ・反映済みなら登録した revert で逆の操作 → 戻した行
  flush(ctx, page)        -> この画面の保留(1 枚遅れで確定する答え)を全部確定する(次のカードに答えた・飛ばした・タブを閉じた / 隠した)
  skip(ctx, card_id, page) -> この画面の保留を確定してから、そのカードを今日の間だけ後ろへ(skip.json)
登録の形(登録の無い種類の答えは 409 not_ready で断る = 実物を変えずにカードだけ消えることは無い):
  register(kind, source, apply, revert=None, check=None, defer=None)
    check(answer) -> 検査して整えた答え(違えば ValueError = 400)
    apply(ctx, card, answer) -> 何を変えたか(dict。記録の applied に入る・revert に渡る)。断るときは Refused
    revert(ctx, row) -> 何を戻したか(dict)。row = 記録の答えの行(applied は確定の行の物に差し替え済み)。None = 戻せない(Z は 409)。
      **もう戻っている(実物が答える前のまま)なら何も書かずに成功を返す**(やりかけの Z を同じ操作 id でやり直すため。そのとき row["again"] = True。
      数を減らすような二度目で壊れる後始末は、again で実物がもう戻っていたら済んでいると見る)。
      答えのあとに別の値へ直されていたら Refused(changed)
    defer(answer) -> True なら 1 枚遅れで確定する(決定 3-41: [送る] = 友人へ届ける。次のカードに答えた時・飛ばした時・タブを閉じた / 隠した時に apply を呼ぶ)
card は ⑤ eval/check の待ち行列がサーバーの側で組み直した物(画面の送った target は信じない)。反映が使うのは id・kind・source・case・target と、
読みのカードだけ card["_cand"](候補の位置と文字)。保留の確定は記録の行から card を組み直す(_cand は無い)ので、defer にできるのは前の 5 つだけで反映できる種類だけ。
書く順(実物と記録を食い違わせない。部品 H2):
  答え = 反映 → 答えの行。行が書けなければ revert で戻す(戻せなかったら実物だけが変わったまま = 記録の外。編集の画面で直す)
  Z    = 始めるの行 → revert → 戻すの行。戻すの行が書けない・revert が想定外の例外 = やりかけ(answerlog の説明)。
         次の答え・Z・確定・飛ばすの前に同じ操作 id で revert をやり直す(戻し済みなら何もしない)。revert が断ったら(changed など)やめるの行
  確定 = 始めるの行 → apply → 確定の行。確定の行が書けない = やりかけ → 次の操作の前に failed にする(届いたか分からない = もう一度は届けない)
③ の層なので ① を直に読まない・④ manage を読まない: 案件の操作(cases.auto_review など)は入口が ctx.hooks で渡す。
"""
import json
import re
import threading

from ytt import txbase as _txbase
from . import answerlog   # 同じ human/check の兄弟

MAX_ANSWER_BYTES = 4096        # 答え(answer)を JSON にしたときの大きさの上限
MAX_MS = 3600 * 1000           # 答えるまでにかかった時間(ms)の上限(超えたら記録しない)
ORPHAN_MS = 30 * 60 * 1000     # ほかの画面の保留でも、これより古ければ確定する(閉じたときの flush が届かなかった画面の分)
UNSURE_CONFIRM = "確定の途中で止まりました(届いたかどうかは案件の画面で確かめてください)"
_PAGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}\Z")
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


class _Applier:
    def __init__(self, kind, source, apply, revert=None, check=None, defer=None):
        self.kind, self.source, self.apply, self.revert, self.check, self.defer = kind, source, apply, revert, check, defer


def register(kind, source, apply, revert=None, check=None, defer=None):
    """種類と出どころの反映の関数を登録する(同じ組は上書き)。-> 登録した物"""
    if not callable(apply):
        raise TypeError("apply は関数にしてください")
    ap = _Applier(kind, source, apply, revert, check, defer)
    _REG[(kind, source)] = ap
    return ap


def _unregister(kind, source):
    _REG.pop((kind, source), None)


def _registered(kind=None, source=None):
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


def _page(v):
    """画面の印(answer・skip・flush の page)。無い・形が違えば None(= どの画面の保留も確定する。前の画面と同じ)"""
    return v if isinstance(v, str) and _PAGE_RE.match(v) else None


def _fail_text(e):
    """記録の failed・why に残す文(Refused は画面の文・ほかは例外の文か名前。300 字まで)"""
    return (getattr(e, "message", None) or str(e) or e.__class__.__name__)[:300]


def _line(**kw):
    at = answerlog.now_ms()
    return dict({"id": answerlog.new_id(at), "at": at}, **kw)


def _mine(row, page, now):
    """この画面(page)が確定してよい保留か: page を渡さない・同じ画面・印の無い古い行・ほかの画面でも ORPHAN_MS より古い"""
    p = row.get("page")
    return page is None or p is None or p == page or not isinstance(row.get("at"), int) or now - row["at"] > ORPHAN_MS


def _confirm_locked(ctx, row):
    """保留 1 つを確定する(始めるの行 → apply → 確定の行)。-> {answer, card, applied | failed}。
    始めるの行・確定の行が書けなければ OSError(確定の行だけ書けなければやりかけ = 次の操作の前に failed にする)"""
    begin = _line(begin="confirm", of=row["id"])
    answerlog.append(ctx.app_dir, begin)
    ap = _REG.get((row.get("kind"), row.get("source")))
    try:
        if ap is None:
            raise Refused("この種類の答えを反映する部品がありません", 409, "not_ready")
        applied = ap.apply(ctx, _card_of_row(row), row.get("answer")) or {}
        line = _line(confirm=row["id"], op=begin["id"], applied=applied)
    except Exception as e:   # 想定外の例外も failed に(1 つの保留が以後の答え・飛ばす・確定を全部止めない = 6b-2。同じ保留は何度も試さない)
        if not isinstance(e, (Refused, ValueError, OSError)):
            _txbase.log.warning("確かめる: 保留の確定で想定外の失敗 %s %s", e.__class__.__name__, str(e)[:200])
        line = _line(confirm=row["id"], op=begin["id"], failed=_fail_text(e))
    answerlog.append(ctx.app_dir, line)
    out = {"answer": row["id"], "card": row.get("card")}
    out.update({"failed": line["failed"]} if "failed" in line else {"applied": line["applied"]})
    return out


def _flush_locked(ctx, st, page=None):
    """この画面の保留を全部確定する(_lock を持って呼ぶ)。-> [{answer, card, applied | failed}](画面は next の failed で 1 行出す)"""
    now = answerlog.now_ms()
    return [_confirm_locked(ctx, row) for row in st.held() if _mine(row, page, now)]


def _undo_locked(ctx, st, row, op_id=None):
    """答え row を戻す(_lock を持って呼ぶ)。op_id = やりかけの Z をやり直すときの始めるの行の id。-> 戻すの行の reverted"""
    aid = row["id"]
    conf = st.confirmed.get(aid)
    if op_id is None and row.get("held") and aid not in st.confirming and (conf is None or conf.get("failed")):
        reverted = {"held": True}   # まだ実物に反映していない(届けていない)= 記録の取り消しだけ
        answerlog.append(ctx.app_dir, _line(undo=aid, reverted=reverted))
        return reverted
    ap = _REG.get((row.get("kind"), row.get("source")))
    if ap is None or ap.revert is None:
        if op_id is not None:
            answerlog.append(ctx.app_dir, _line(abort=op_id, why="この答えは戻せません"))
        raise Refused("この答えは戻せません", 409, "cannot_undo")
    again = op_id is not None
    if op_id is None:   # 実物を変える前に意図を書く(書けなければ何も変えずに OSError)
        op_id = _line(begin="undo", of=aid)
        answerlog.append(ctx.app_dir, op_id)
        op_id = op_id["id"]
    try:
        reverted = ap.revert(ctx, dict(row, applied=conf.get("applied") if conf else row.get("applied"), again=again)) or {}
    except Refused as e:   # 断った = 実物は変えていない。やめるの行が書けなくても、やり直しでまた断るだけ
        try:
            answerlog.append(ctx.app_dir, _line(abort=op_id, why=_fail_text(e)))
        except OSError:
            pass
        raise
    answerlog.append(ctx.app_dir, _line(undo=aid, op=op_id, reverted=reverted))   # 書けなければやりかけのまま OSError(次の操作の前にやり直す)
    return reverted


def _resume_locked(ctx, st):
    """やりかけ(始めるの行だけがある Z・確定)を同じ操作 id で終わらせる(_lock を持って呼ぶ)。-> 今の State。
    書けない・想定外の例外はやりかけのまま次へ(今の操作は止めない)"""
    if not st.pending:
        return st
    for op_id, it in list(st.pending.items()):
        row = st.answers.get(it["of"])
        try:
            if row is None:
                answerlog.append(ctx.app_dir, _line(abort=op_id, why="答えの行がありません"))
            elif it["begin"] == "undo":
                _undo_locked(ctx, st, row, op_id)
            else:
                answerlog.append(ctx.app_dir, _line(confirm=row["id"], op=op_id, failed=UNSURE_CONFIRM))
        except Refused:
            pass   # やめるの行を書いた(答えは効いたまま)
        except Exception as e:
            _txbase.log.warning("確かめる: やりかけの操作をやり直せませんでした %s %s", e.__class__.__name__, str(e)[:200])
    return answerlog.state(ctx.app_dir)


def flush(ctx, page=None):
    """この画面(page)の保留を確定する(POST /api/check/flush。タブを閉じた / 隠したとき)。-> {ok, flushed}"""
    with _lock:
        st = _resume_locked(ctx, answerlog.state(ctx.app_dir))
        return {"ok": True, "flushed": _flush_locked(ctx, st, _page(page))}


def answer(ctx, card, body):
    """カード card に答える。body = {answer, ms?, guess?, page?}。-> {ok, answer: 答えの id, card, applied, held, flushed}。断るときは Refused"""
    body = body if isinstance(body, dict) else {}
    ans, ms = _check_body(body)
    page = _page(body.get("page"))
    kind, source = card.get("kind"), card.get("source")
    with _lock:
        st = _resume_locked(ctx, answerlog.state(ctx.app_dir))
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
        flushed = _flush_locked(ctx, st, page)   # この画面の前の保留を先に確定(1 枚遅れ。3-3)
        held = bool(ap.defer and ap.defer(ans))
        at = answerlog.now_ms()
        applied = {} if held else (ap.apply(ctx, card, ans) or {})
        row = {"id": answerlog.new_id(at), "at": at, "kind": kind, "source": source, "card": card["id"], "case": card.get("case"),
               "target": card.get("target") or {}, "guess": card.get("guess"), "answer": ans, "ms": ms, "applied": applied}
        if held:
            row["held"] = True
            if page:
                row["page"] = page
        try:
            answerlog.append(ctx.app_dir, row)
        except OSError:
            if not held and ap.revert is not None:   # 記録できない答えは実物にも残さない(Z で戻せなくなるため)
                try:
                    ap.revert(ctx, row)
                except Exception as e:
                    _txbase.log.warning("確かめる: 記録できなかった答えを戻せませんでした %s %s", e.__class__.__name__, str(e)[:200])
            raise
        return {"ok": True, "answer": row["id"], "card": card["id"], "applied": applied, "held": held, "flushed": flushed}


def undo(ctx, answer_id):
    """Z。答え answer_id を戻す。-> {ok, answer, card, reverted}。無い = 404・もう戻した / 戻せない = 409。
    その答えの Z がやりかけなら、同じ操作 id でやり直す(戻し済みなら記録だけ書く)"""
    if not isinstance(answer_id, str) or not answerlog.ID_RE.match(answer_id):
        raise Refused("戻す答えの指定(undo)が正しくありません", 400, "bad_request")
    with _lock:
        st = answerlog.state(ctx.app_dir)
        row = st.answers.get(answer_id)
        if row is None:
            raise Refused("その答えはありません", 404, "not_found")
        again = st.undoing.get(answer_id)
        if again is not None:
            reverted = _undo_locked(ctx, st, row, again["id"])
            return {"ok": True, "answer": answer_id, "card": row.get("card"), "reverted": reverted}
        st = _resume_locked(ctx, st)
        if answer_id in st.undone:
            raise Refused("その答えはもう戻しました", 409, "undone")
        reverted = _undo_locked(ctx, st, row)
        return {"ok": True, "answer": answer_id, "card": row.get("card"), "reverted": reverted}


def skip(ctx, card_id, page=None):
    """カードを今日の間だけ後ろへ(この画面の保留は先に確定)。-> {ok, flushed}"""
    with _lock:
        st = _resume_locked(ctx, answerlog.state(ctx.app_dir))
        flushed = _flush_locked(ctx, st, _page(page))
        answerlog.add_skip(ctx.app_dir, card_id)
        return {"ok": True, "flushed": flushed}
