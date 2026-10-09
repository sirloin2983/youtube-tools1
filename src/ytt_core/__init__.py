"""旧い名前 ytt_core の転送(役割で組み直す RS1-1。2026-10-09。RS5 で消す)。

中身は src/ytt(基盤)・src/pipeline/analyze/excite.py・src/eval/tools/evaldata.py・src/manage/cases/txindex.py に移した。
`from ytt_core import fsio`・`from ytt_core.excite import CAP` などの旧い import がそのまま動くよう、実体と**同じモジュール**を
sys.modules に「ytt_core.<名前>」で登録する(写しを作らない = jobs.SLOTS などの状態が二重にならない・テストの差し替えが実体に届く)。
読む側は src/ を sys.path に入れておく(今の各ツールの _load_core がそうしている)。dev/layer_map.py の FORWARDERS に載せてある。
"""
import sys

from eval.tools import evaldata
from manage.cases import txindex
from pipeline.analyze import excite
from ytt import (VERSION, colors, datadir, fsio, httpsec, jobs, layout, loudness, names, normalize, pick, recproto, runtime,  # noqa: F401
                 schemas, settings, tools)

for _name, _mod in (("colors", colors), ("datadir", datadir), ("fsio", fsio), ("httpsec", httpsec), ("jobs", jobs), ("layout", layout),
                    ("loudness", loudness), ("names", names), ("normalize", normalize), ("pick", pick), ("recproto", recproto),
                    ("runtime", runtime), ("schemas", schemas), ("settings", settings), ("tools", tools),
                    ("excite", excite), ("evaldata", evaldata), ("txindex", txindex)):
    sys.modules.setdefault(__name__ + "." + _name, _mod)
