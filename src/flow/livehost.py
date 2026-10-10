# -*- coding: utf-8 -*-
"""ライブの親(host)の口(役割で組み直す RS7-2 G0。docs/design/rs7-survey-2026-10-10/plan_order_v3.md)。

② のライブの子 4 つ(live_detect.Detector・live_tx.LiveTx・live_report.Reporter・live_export.Exporter)は、
親(今は app の src/home/live.py の Live。G2b で flow/livesession.py へ抜き出す)を受け取って呼び返す。
ここはその「親に何を求めるか」を typing.Protocol で並べた物(動きは持たない。子は self.host に親を持つ)。
子ごとに要る分を小さく分けた: DetectHost・TxHost・ReportHost・ExportHost。全部をまとめた物が LiveHost(Live が満たす)。

採用(flow/live_adopt.py の Adopter。RS7-2 G1b)が親に求める物は AdoptHost(マークの置き場 marks = MarkBook も)。

親が持っていなくてもよい物(子が getattr で読み、無ければ飛ばす)は OPTIONAL に並べた:
  Detector: _halt(入口の終了の途中ならワーカーを起こさない)・unconfirmed(D-13 の未確認の数。None なら休まない)・
            auto_max(D-13 の 1 録画の自動の採用の上限。None なら AUTO_MAX_PER_REC)
  Exporter: studio_call(スタジオのマークを「書き出し済み」にする。無ければ黙って飛ばす)
Archiver(live_archive)・Cleaner(manage/keep/live_cleanup)は関数で受けるのでここには無い
(ただし Archiver は Exporter の host.find を読む = ExportHost の find)。
"""
import threading
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Protocol, Tuple

if TYPE_CHECKING:   # 型の名前だけ(実行時に子を読まない = 子がこのファイルを読んでも輪にならない)
    from .live_detect import Detector
    from .live_export import Exporter
    from .live_tx import LiveTx

Reply = Tuple[Optional[int], Any]   # (HTTP の番号か None, JSON)


class RequestBook(Protocol):
    """友人のライブ配信の依頼と録画の結びつき(human/friend/live_requests.Store。flow は human を読めないので形だけ)"""

    def get(self, rc: str, rec: str) -> Optional[dict]: ...

    def all(self) -> Dict[str, dict]: ...


class ExportHost(Protocol):
    """Exporter(マークと書き出し)が親に求める物 = 録画元の一覧と要求"""

    def find(self, rid: str) -> Optional[dict]: ...

    def recorders(self, cfg: Optional[dict] = None) -> List[dict]: ...

    def call(self, rc: dict, method: str, path: str, body: Any = None, timeout: float = 3.0) -> Reply: ...

    def request(self, rc: dict, method: str, path: str, body: Any = None, timeout: float = ...) -> Tuple[Any, Any]: ...


class TxHost(Protocol):
    """LiveTx(配信中の候補の文字起こし)が親に求める物"""
    root: str
    detector: "Detector"
    exporter: "Exporter"

    def cfg(self) -> dict: ...

    def enabled(self) -> bool: ...

    def find(self, rid: str) -> Optional[dict]: ...

    def list_recordings(self) -> List[dict]: ...


class ReportHost(Protocol):
    """Reporter(配信ごとの結果の記録)が親に求める物"""
    store_dir: str
    log: Callable[[str], None]
    requests: RequestBook
    detector: "Detector"
    livetx: "LiveTx"
    exporter: "Exporter"

    def enabled(self) -> bool: ...

    def list_recordings(self) -> List[dict]: ...

    def note(self, msg: str) -> None: ...


class DetectHost(Protocol):
    """Detector(盛り上がりの検出と自動の採用)が親に求める物"""
    root: str
    store_dir: str
    logs_dir: str
    log: Callable[[str], None]
    requests: RequestBook
    livetx: "LiveTx"
    exporter: "Exporter"

    def cfg(self) -> dict: ...

    def enabled(self) -> bool: ...

    def recorders(self, cfg: Optional[dict] = None) -> List[dict]: ...

    def list_recordings(self) -> List[dict]: ...

    def studio_call(self, method: str, path: str, body: Any = None) -> Reply: ...

    def adopt(self, body: dict, hold: Any = None) -> dict: ...

    def note(self, msg: str) -> None: ...

    def _ids(self, rc_id: str, rec: str) -> dict: ...


class MarkBook(Protocol):
    """マークの置き場(RS7-2 G1b。flow/live_adopt.py の StudioMarks = スタジオ・LocalMarks = マークの正本 live_export.MarkStore)"""

    def adopt_mark(self, rc_id: str, rec: str, st: dict, first: float, a: float, b: float, label: str) -> Tuple[str, dict, int]: ...

    def exported(self, job: dict, media: str, archived: bool = False) -> str: ...


class AdoptHost(Protocol):
    """Adopter(flow/live_adopt.py。採用 = マーク + 書き出し)が親に求める物"""
    log: Callable[[str], None]
    requests: RequestBook
    exporter: "Exporter"
    marks: MarkBook

    def auto_cfg(self) -> dict: ...

    def _ids(self, rc_id: str, rec: str) -> dict: ...

    def _rec_status(self, rc: dict, rc_id: str, rec: str) -> Tuple[dict, float]: ...


class LiveHost(DetectHost, TxHost, ReportHost, ExportHost, AdoptHost, Protocol):
    """4 つの子と採用の親(Live・G2b の livesession)。OPTIONAL の物も持つ"""
    _halt: threading.Event
    unconfirmed: Optional[Callable[[], int]]
    auto_max: Optional[Callable[[str, str], int]]


# auto_max(rc, rec) -> 1 録画の自動の採用の上限(D-13。RS7-2 G1b)。None・無し = live_detect.AUTO_MAX_PER_REC(ユーザーの PC)。友人の PC は束の adopt.top
OPTIONAL = {"Detector": ("_halt", "unconfirmed", "auto_max"), "Exporter": ("studio_call",)}


def names(proto) -> List[str]:
    """Protocol が並べた属性・メソッドの名前(継いだ分も。テストと調べもの用)"""
    out = set()
    for c in proto.__mro__:
        if c in (object, Protocol) or not getattr(c, "_is_protocol", False):
            continue
        out.update(getattr(c, "__annotations__", {}))
        out.update(k for k, v in vars(c).items() if callable(v) and not (k.startswith("__") and k.endswith("__")))
    out.discard("_is_protocol")
    return sorted(out)
