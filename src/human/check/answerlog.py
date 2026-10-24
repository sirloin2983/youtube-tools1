"""「確かめる」の答えの記録(notes:docs/design/v1-check-build.md の 3-1)。

置き場所: 入口の作業データ `app\\check\\`(accuracy-state.json と同じ app の持ち物。バックアップは app を丸ごと写すので足す物は無い)。
  - answers.jsonl: 追記だけ(fsio.append_line)。1 行 = 1 件の JSON。形は 6 通り:
      答え   {id, at, kind, source, card, case, target, guess, answer, ms, applied, held?, page?}
             held = 1 枚遅れで確定する答え(友人へ届けるなど。3-3)。確定するまで実物は変えていない。page = 答えた画面の印(確定はその画面の保留だけ)
      分からない {id, at, unknown: <カードの id>, kind, source, case, target, mark}(画面の [分からない]。そのカードをもう出さないだけ =
             答えではない: 実物・文書・声を覚える材料・評価・目標の件数・今日 n 件のどれにも入れない(effective・by_card・today に出ない)。
             mark = 出したときのカードの中身の印(card_mark)。元の行が変わって印が違えば新しいカードとしてまた出る。Z で戻すと(戻すの行)また出る。
             カードの id を card でなく unknown に持つ = card を答えと見る古い版が読んでも答えに数えない)
      始める {id, at, begin: "undo" | "confirm", of: <答えの id>}(実物を変える前に書く意図。この行の id = 操作の id)
      確定   {id, at, confirm: <答えの id>, op?, applied} か {id, at, confirm, op?, failed: 理由}(held の答えを実物へ反映した / できなかった)
      戻す   {id, at, undo: <答えの id>, op?, reverted}(Z。held のまま戻したときは reverted = {"held": true}・意図を書かない)
      やめる {id, at, abort: <始めるの id>, why}(戻すのを断られた = 実物は変えていない)
    op = 始めるの行の id。始めるの行に、確定・戻す(op が同じ)・やめるのどれも続いていなければ「やりかけ」(pending)=
    実物が変わったかどうか分からない。apply が次の操作の前に同じ操作 id でやり直す(戻すは部品の revert をもう一度 = 戻し済みなら何もしない・
    確定は届いたか分からないので failed にする = 二重に届けない)。やりかけの Z の答えは effective に数えない(評価にも使わない)・
    カードは答えたまま(by_card に残す)。やりかけの確定の答えは held に出さない(もう一度確定しない)。
    回すと(MAX_LOG_BYTES)前の答え・保留・やりかけを忘れる(今のファイルだけを読む。1 日 200 件で 1 年以上先)
  - skip.json: {day: "YYYY-MM-DD", ids: [カードの id]}(その日の間だけ後ろへ回すカード。日が変わったら空と同じ)
読み書きはここだけ(入口 app/check の待ち行列は読むだけ・③ human/check/apply が書く)。標準ライブラリと ytt だけを読む。
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import threading

from ytt import fsio
from ytt.schemas import now_ms   # 今の時刻(ms)の正は ytt/schemas(テストは answerlog.now_ms を差し替える)

DIR_NAME = "check"
ANSWERS = "answers.jsonl"
SKIPS = "skip.json"
MAX_LOG_BYTES = 32 * 1024 * 1024   # これを超えたら answers.jsonl.1 へ 1 世代回す(数えるのは今のファイルだけ)
MAX_SKIPS = 2000                   # その日に後ろへ回すカードの数の上限(古い物から捨てる)
ID_RE = re.compile(r"^a\d{13}-[0-9a-f]{6}\Z")
_cache = fsio.StampCache()
_skip_lock = threading.Lock()


def _check_dir(app_dir):
    return os.path.join(app_dir, DIR_NAME)


def answers_path(app_dir):
    return os.path.join(_check_dir(app_dir), ANSWERS)


def _skips_path(app_dir):
    return os.path.join(_check_dir(app_dir), SKIPS)


def new_id(at=None):
    """答え・確定・戻すの行の id(時刻の順に並ぶ。同じ ms でも重ならないように 6 桁の乱数)"""
    return "a%013d-%s" % (now_ms() if at is None else at, secrets.token_hex(3))


def day_of(at_ms):
    """エポック ms -> この PC の日付(YYYY-MM-DD)。「今日 n 件」と skip の日の区切り"""
    return datetime.date.fromtimestamp(at_ms / 1000.0).isoformat()


def card_mark(card):
    """カードの中身の印(12 桁)= 字幕の文字と流す区間。人が行を直す・時刻が変わると違う印になる([分からない] のカードがまた出る)"""
    media = card.get("media") if isinstance(card.get("media"), dict) else {}

    def sec(v):
        return round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    raw = json.dumps([str(card.get("text") or ""), sec(media.get("start")), sec(media.get("end"))], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def append(app_dir, row):
    """1 行を書き足す(書けなければ OSError)。NaN は書かない"""
    fsio.append_line(answers_path(app_dir), json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", MAX_LOG_BYTES)


def _parse(path):
    rows = []
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_LOG_BYTES + 1024 * 1024)
    except OSError:
        return rows
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue   # 書きかけ・壊れた行は飛ばす(追記だけなので次の行は読める)
        if isinstance(r, dict) and isinstance(r.get("id"), str) and ID_RE.match(r["id"]):
            rows.append(r)
    return rows


def _read_rows(app_dir):
    """answers.jsonl の行(古い順)。無い・読めなければ []。ファイルが変わったときだけ読み直す(返した中身は書き換えない)"""
    got = _cache.get(answers_path(app_dir), _parse)
    return got if got is not None else []


class State:
    """記録を読んだ今の状態。answers = {答えの id: 行}・order = 答えの id(古い順)・undone = {答えの id: 戻した行}・
    confirmed = {答えの id: 確定の行}・by_card = {カードの id: 効いている答えの id}(戻した答えは数えない)・
    pending = {始めるの id: 始めるの行}(やりかけ)・undoing / confirming = {答えの id: やりかけの始めるの行}・
    unknowns = {分からないの id: 行}・unknown = {カードの id: 効いている(戻していない)分からないの行}"""

    def __init__(self, rows):
        self.answers, self.order, self.undone, self.confirmed, self.by_card = {}, [], {}, {}, {}
        self.unknowns, self.unknown = {}, {}
        self.rev = len(rows)
        begun, done = {}, set()
        for r in rows:
            if isinstance(r.get("unknown"), str):
                self.unknowns[r["id"]] = r
            elif isinstance(r.get("undo"), str):
                self.undone[r["undo"]] = r
                done.add(r.get("op"))
            elif isinstance(r.get("confirm"), str):
                self.confirmed[r["confirm"]] = r
                done.add(r.get("op"))
            elif r.get("begin") in ("undo", "confirm") and isinstance(r.get("of"), str):
                begun[r["id"]] = r
            elif isinstance(r.get("abort"), str):
                done.add(r["abort"])
            elif isinstance(r.get("card"), str):
                self.answers[r["id"]] = r
                self.order.append(r["id"])
        # やりかけ = 始めたのに終わりの行が無い(終わりの行が op を持たない古い形でも、同じ答えがもう戻した / 確定したなら終わったと見る)
        self.pending = {k: r for k, r in begun.items() if k not in done
                        and r["of"] not in (self.undone if r["begin"] == "undo" else self.confirmed)}
        self.undoing = {r["of"]: r for r in self.pending.values() if r["begin"] == "undo"}
        self.confirming = {r["of"]: r for r in self.pending.values() if r["begin"] == "confirm"}
        for aid in self.order:
            r = self.answers[aid]
            if aid in self.undone:
                if self.by_card.get(r["card"]) == aid:
                    del self.by_card[r["card"]]
                continue
            self.by_card[r["card"]] = aid
        for uid, r in self.unknowns.items():   # 古い順 = 同じカードは後の行
            if uid not in self.undone:
                self.unknown[r["unknown"]] = r

    def closed(self, card):
        """もう出さないカードか: 効いている答えがある・[分からない] にしてカードの中身の印(mark)が今も同じ"""
        cid = card.get("id")
        if cid in self.by_card:
            return True
        u = self.unknown.get(cid)
        return u is not None and u.get("mark") in (None, card_mark(card))

    def live(self, aid):
        """効いている(戻していない)答えか"""
        return aid in self.answers and aid not in self.undone

    def held(self):
        """確定を待っている答え(held で、戻しても確定してもいない・確定のやりかけでもない)。古い順"""
        return [self.answers[a] for a in self.order
                if self.answers[a].get("held") and self.live(a) and a not in self.confirmed and a not in self.confirming]

    def effective(self):
        """効いている答えの行(古い順)。held で確定に失敗した物・Z のやりかけ(実物はもう戻っているかもしれない)は外す"""
        out = []
        for a in self.order:
            if not self.live(a) or a in self.undoing:
                continue
            c = self.confirmed.get(a)
            if c is not None and c.get("failed"):
                continue
            out.append(self.answers[a])
        return out

    def failed(self):
        """held を確定しようとして失敗した答え(新しい順)"""
        return [dict(self.answers[a], failed=self.confirmed[a].get("failed")) for a in reversed(self.order)
                if self.live(a) and (self.confirmed.get(a) or {}).get("failed")]

    def today(self, at_ms=None):
        d = day_of(now_ms() if at_ms is None else at_ms)
        return sum(1 for r in self.effective() if isinstance(r.get("at"), int) and day_of(r["at"]) == d)


def state(app_dir):
    return State(_read_rows(app_dir))


# ---------------------------------------------------------------- その日の間だけ後ろへ(skip.json)

def read_skips(app_dir, at_ms=None):
    """今日後ろへ回したカードの id(順に)。日が違う・無い・壊れていれば []"""
    d = fsio.read_json_or(_skips_path(app_dir), {}, max_bytes=1024 * 1024, kind=dict)
    if d.get("day") != day_of(now_ms() if at_ms is None else at_ms) or not isinstance(d.get("ids"), list):
        return []
    return [x for x in d["ids"] if isinstance(x, str)]


def add_skip(app_dir, card_id, at_ms=None):
    """今日の分に足す(同じ id は後ろへ付け直す)。-> 今日の一覧。書けなければ OSError"""
    with _skip_lock:
        at = now_ms() if at_ms is None else at_ms
        ids = [x for x in read_skips(app_dir, at) if x != card_id] + [card_id]
        ids = ids[-MAX_SKIPS:]
        os.makedirs(_check_dir(app_dir), exist_ok=True)
        fsio.write_json(_skips_path(app_dir), {"day": day_of(at), "ids": ids}, indent=None)
        return ids
