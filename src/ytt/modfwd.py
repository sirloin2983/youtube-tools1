"""モジュールの名前の転送(役割で組み直す間の転送の仕組み。2026-10-10 の RS2-0)。

`install(globals(), owners)` を呼んだモジュールは、自分に無い名前を owners(モジュールの並び)の持ち主から読み、
`mod.名前 = …`・`del mod.名前`(テストの差し替え・unittest.mock の patch.object)もその持ち主へ回す。
自分が持っている名前は自分が先(転送しない)。owners の前のモジュールが勝つ。
使う所: 編集の serve.py の名前の受付(分けた部品の名前を serve の名前で使う)と、中身を移したあとの ed_jobs.py(RS5 で消す)。

持ち主の表は呼んだ時点の各モジュールの名前で作る(mock が一度消してから戻すときも持ち主が分かるように)。
あとから持ち主に増えた名前は並びの順に探し直す。
"""
import sys
import types


def owner_table(owners):
    """名前 → 持ち主のモジュール(前のモジュールが勝つ)。__ で始まる名前は入れない"""
    table = {}
    for m in reversed(tuple(owners)):
        table.update({k: m for k in m.__dict__ if not k.startswith("__")})
    return table


def duplicates(owners):
    """2 つ以上の持ち主にある名前(モジュールそのものと __ で始まる名前は除く)→ 持ち主の名前の並び。
    重なると前の持ち主が黙って勝ち、差し替えが本体に届かなくなるので、テストで 0 件を確かめる"""
    seen = {}
    for m in owners:
        for k, v in m.__dict__.items():
            if not k.startswith("__") and not isinstance(v, types.ModuleType):
                seen.setdefault(k, []).append(m.__name__)
    return {k: v for k, v in seen.items() if len(v) > 1}


def install(namespace, owners, label=None):
    """namespace(呼んだモジュールの globals())に PEP 562 の __getattr__ を置き、登録して読み込まれたモジュールなら
    書き込み・削除も転送するクラスに差し替える。戻り値は名前 → 持ち主を探す関数(無ければ None)"""
    owners = tuple(owners)
    table = owner_table(owners)
    label = label or namespace.get("__name__", "?")

    def find(name):
        m = table.get(name)
        if m is not None:
            return m
        for m in owners:
            if name in m.__dict__:
                return m
        return None

    def __getattr__(name):   # PEP 562。sys.modules に登録せずに読み込んだときも働く
        m = find(name)
        if m is None:
            raise AttributeError("%s に %s はありません" % (label, name))
        return getattr(m, name)

    namespace["__getattr__"] = __getattr__
    me = sys.modules.get(namespace.get("__name__"))
    if me is not None and me.__dict__ is namespace:   # 普通の import・入口の取り込み。契約テストのように登録しない読み込みは読むだけ
        me.__class__ = _forwarding_class(getattr(type(me), "_modfwd_base", type(me)), find)   # 2 回目は元の型から作り直す(重ねない)
    return find


def _forwarding_class(base, find):
    class _Forwarding(base):
        _modfwd_base = base

        def __setattr__(self, name, value):
            m = None if name in self.__dict__ else find(name)
            if m is None:
                super().__setattr__(name, value)
            else:
                setattr(m, name, value)

        def __delattr__(self, name):   # unittest.mock の patch.object は戻すときに「消す → 無ければ元の値を入れ直す」ので、消すのも持ち主へ
            m = None if name in self.__dict__ else find(name)
            if m is None:
                super().__delattr__(name)
            else:
                delattr(m, name)

    return _Forwarding
