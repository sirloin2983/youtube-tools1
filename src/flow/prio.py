# -*- coding: utf-8 -*-
"""② 管理の層 flow: 処理の優先度の表(PRIO。決定 3-49・notes:plan/opt-series.md の 11)。

それまでばらばらだった 4 つ(まとめて実行の待ち行列は入れた順だけ・重い処理の枠 ytt.jobs.SLOTS は来た順だけ・
文字起こしの種類の数字 flow/jobs.JOB_PRIORITY・子プロセスの OS の優先度)を、この 1 つの表から決める:

  録画中のライブ(live) > 友人の依頼(friend) > 自分の配信のまとめて実行(batch) > 後回しの仕事(later。空いているときだけ)

- 待ち行列(flow/runqueue.Queue): 次に始める実行を、この順(同じなら入れた順)で選ぶ。動いている実行は止めない
- ジョブの器(flow/jobs.Table): 待ちを この順 → 種類の数字(JOB_PRIORITY。話者判別 0・文字起こし 1・別の読み 2)→ 入れた順 で選ぶ。
  後回しの仕事は空いているとき(idle)だけ選ぶ。枠を取るときの rank・idle_only もここから
- 重い処理の枠(ytt.jobs.SLOTS): 待ちを rank の小さい順に。idle_only = ほかの処理が動いておらず・待っておらず・idle のときだけ
- OS の優先度(os): 器が Ctl.os_priority に入れる(ytt/procs.run_capture が子プロセスに使う)。None = 呼ぶ所の既定のまま
  (重い子プロセスは「通常より下」・録画の部品は「通常より上」= ① の物)。後回しの仕事だけ「アイドル」
- idle(後回しの仕事を始めてよいか): まとめて実行の待ち・実行中が無く、録画中の録画が無い(watch で SLOTS に入れる)

級の決め方: 実行(Run)は of_run(組の溜めつき = ライブの受け渡し → live・友人の依頼の id つき → friend・ほか → batch)。
ジョブの記録は of_spec(spec の "prio" が表の名前ならそれ・評価用の一括(evalBatch)→ later・ほか → batch)。
録画中のライブの書き出し・配信中の文字起こしは live、受付の 30fps の作り直しは friend を自分で渡す(slot_kw)。
import してよいのは標準ライブラリと ytt だけ(jobs・runqueue が読むので、同じ flow のほかの物を読まない)。
"""
from ytt import jobs as _slots

TABLE = {   # 名前 -> rank(小さいほど先)・人の言葉・空いているときだけか・OS の優先度(None = 呼ぶ所の既定)
    "live": {"rank": 0, "label": "録画中のライブ", "idleOnly": False, "os": None},
    "friend": {"rank": 1, "label": "友人の依頼", "idleOnly": False, "os": None},
    "batch": {"rank": 2, "label": "自分の配信のまとめて実行", "idleOnly": False, "os": None},
    "later": {"rank": 3, "label": "後回しの仕事(空いているときだけ)", "idleOnly": True, "os": "idle"},
}
NAMES = tuple(sorted(TABLE, key=lambda k: TABLE[k]["rank"]))
DEFAULT = "batch"
assert TABLE[DEFAULT]["rank"] == _slots.DEFAULT_RANK   # rank を渡さない枠の待ちは「自分の配信のまとめて実行」と同じ順


def name_ok(v):
    return isinstance(v, str) and v in TABLE


def rank(name):
    return TABLE[name if name_ok(name) else DEFAULT]["rank"]


def idle_only(name):
    return TABLE[name if name_ok(name) else DEFAULT]["idleOnly"]


def os_priority(name):
    return TABLE[name if name_ok(name) else DEFAULT]["os"]


def label(name):
    return TABLE[name if name_ok(name) else DEFAULT]["label"]


def slot_kw(name):
    """SLOTS.slot・acquire に足す引数 {rank, idle_only}"""
    return {"rank": rank(name), "idle_only": idle_only(name)}


def of_run(run):
    """まとめて実行の実行(flow/run.Run)の級: 組の溜め(pool)つき = ライブの受け渡し → live・友人の依頼の id(request_id)つき → friend・ほか → batch"""
    if getattr(run, "pool", None):
        return "live"
    if getattr(run, "request_id", None):
        return "friend"
    return DEFAULT


def of_spec(spec):
    """ジョブの記録の spec の級: "prio" が表の名前ならそれ・評価用の一括(evalBatch)→ later・ほか → batch"""
    if not isinstance(spec, dict):
        return DEFAULT
    if name_ok(spec.get("prio")):
        return spec["prio"]
    if spec.get("evalBatch"):
        return "later"
    return DEFAULT


def watch(queue, slots=None):
    """重い処理の枠(既定 ytt.jobs.SLOTS)に「後回しの仕事を始めてよいか」を入れる = queue.idle_for_later(入口が待ち行列を作ったときに 1 回)"""
    (slots or _slots.SLOTS).set_idle_check(queue.idle_for_later)


def idle_now(slots=None):
    """後回しの仕事を今始めてよいか(枠の中に動いている・待っているほかの処理が無く、watch の答えが真)"""
    return (slots or _slots.SLOTS).idle_now()
