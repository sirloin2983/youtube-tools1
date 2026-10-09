"""認識の部品が使う置き場所と外の道具の一時的な口(役割で組み直す RS2-2。2026-10-10。**RS3 で ytt/settings に置き換えて消す**)。

認識の部品(pipeline/transcribe。今は移す前の ed_jobs)は、作業データのパス・名簿のファイル・ffmpeg・ワーカーの Python・GPU の有無などを
編集の ed_state(app の層)から直に読まず、ここから読む。値を持つのは app(編集の serve.py)で、読み込みのときに
「呼ぶたびに ed_state の今の値を返す関数」を register で登録する(作業データの切り替え set_data_dir・テストの `S.TX_DIR = …`・
`mock.patch.object(S, "check_source", …)` がそのまま効く)。

    txenv.register(TX_DIR=lambda: ed_state.TX_DIR, check_source=lambda: ed_state.check_source)
    txenv.get("TX_DIR") / txenv.TX_DIR          # 呼んだときの値
    txenv.check_source(path)                    # 関数を返す鍵は、そのまま呼べる
    txenv.check()                               # KEYS のうち登録されていない鍵があれば RuntimeError
"""
KEYS = ("DATA_DIR", "TX_DIR", "TMP_DIR", "ROOT", "ROSTER", "SERVER_VERSION",
        "find_ffmpeg", "worker_python", "worker_fake", "gpu_ready", "has_faster_whisper", "media_duration", "check_source")
_providers = {}


def register(**providers):
    """鍵 → 引数なしの関数(呼ぶたびに今の値を返す)。知らない鍵・関数でない値は TypeError"""
    bad = sorted(k for k in providers if k not in KEYS)
    if bad:
        raise TypeError("txenv に知らない鍵: %s" % ", ".join(bad))
    for k, fn in providers.items():
        if not callable(fn):
            raise TypeError("txenv の %s は関数で渡す(呼ぶたびに今の値を返す)" % k)
    _providers.update(providers)


def get(name):
    """鍵の今の値。登録されていなければ RuntimeError(app の登録より先に読んだ・登録し忘れ)"""
    try:
        fn = _providers[name]
    except KeyError:
        raise RuntimeError("txenv の %s が登録されていません(編集の serve.py が読み込みのときに登録する)" % name) from None
    return fn()


def check(names=KEYS):
    """names のうち登録されていない鍵があれば RuntimeError(app が登録のあとで呼ぶ)"""
    missing = [k for k in names if k not in _providers]
    if missing:
        raise RuntimeError("txenv に登録されていない鍵: %s" % ", ".join(missing))


def __getattr__(name):   # PEP 562: txenv.TX_DIR・txenv.check_source(path) の形で読む
    if name in KEYS:
        return get(name)
    raise AttributeError("txenv に %s はありません" % name)
