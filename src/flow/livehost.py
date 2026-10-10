# -*- coding: utf-8 -*-
"""ライブの親(host)の口(役割で組み直す RS7-2 G0。docs/design/rs7-survey-2026-10-10/plan_order_v3.md)。

② のライブの子 4 つ(live_detect.Detector・live_tx.LiveTx・live_report.Reporter・live_export.Exporter)は、
親(flow/livesession.py の LiveSession = ライブ係。RS7-2 G2b。入口の src/home/live.py の Live はそれを継ぐ app の殻)を受け取って呼び返す。
ここはその「親に何を求めるか」を typing.Protocol で並べた物(動きは持たない。子は self.host に親を持つ)。
親は 1 つ(LiveSession)なので口も LiveHost の 1 つにまとめた(採用 flow/live_adopt.py の Adopter。RS7-2 G1b も同じ口)。
親とは別の物の口: 友人の依頼の結びつき RequestBook・マークの置き場 MarkBook(実装が 2 つ = live_adopt の StudioMarks・LocalMarks)。

親が持っていなくてもよい物(子が getattr で読み、無ければ飛ばす): _halt・unconfirmed・auto_max・bundles(Detector)、
studio_call・bundles(Exporter)。Archiver(live_archive)・Cleaner(manage/keep/live_cleanup)は関数で受けるのでここには無い
(ただし Archiver は Exporter の host.find を読む)。
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

    def put(self, rc: str, rec: str, ctx: dict) -> dict: ...   # 録画を依頼に結びつける(ライブ係 livesession の begin_request。RS7-2 G2b)

    def prune(self) -> int: ...   # 古い結びつきを消す(ライブ係の見回り)


class MarkBook(Protocol):
    """マークの置き場(RS7-2 G1b。flow/live_adopt.py の StudioMarks = スタジオ・LocalMarks = マークの正本 live_export.MarkStore)"""

    def adopt_mark(self, rc_id: str, rec: str, st: dict, first: float, a: float, b: float, label: str) -> Tuple[str, dict, int]: ...

    def exported(self, job: dict, media: str, archived: bool = False) -> str: ...


class LiveHost(Protocol):
    """ライブの親(flow/livesession.py の LiveSession。入口の Live はそれを継ぐ)。子 4 つと採用が求める物を全部"""
    root: str
    store_dir: str
    logs_dir: str
    log: Callable[[str], None]
    requests: RequestBook
    marks: MarkBook
    detector: "Detector"
    livetx: "LiveTx"
    exporter: "Exporter"
    _halt: threading.Event                         # 入口の終了の途中ならワーカーを起こさない
    unconfirmed: Optional[Callable[[], int]]       # D-13 の未確認の数。None なら休まない
    auto_max: Optional[Callable[[str, str], int]]  # (rc, rec) -> 1 録画の自動の採用の上限(D-13)。None なら live_detect.AUTO_MAX_PER_REC。友人の PC は束の adopt.top
    bundles: Any   # 録画ごとの封筒 + 束(flow/livesession.py の BundleBook。spec(rc, rec)・specs())。無い・束の無い録画は今までの読み方

    def cfg(self) -> dict: ...

    def auto_cfg(self, rc: Optional[str] = None, rec: Optional[str] = None) -> dict: ...   # rc・rec = その録画の束から(無ければホームの設定)

    def enabled(self) -> bool: ...

    def recorders(self, cfg: Optional[dict] = None) -> List[dict]: ...

    def find(self, rid: str) -> Optional[dict]: ...

    def list_recordings(self) -> List[dict]: ...

    def call(self, rc: dict, method: str, path: str, body: Any = None, timeout: float = 3.0) -> Reply: ...

    def request(self, rc: dict, method: str, path: str, body: Any = None, timeout: float = ...) -> Tuple[Any, Any]: ...

    def studio_call(self, method: str, path: str, body: Any = None) -> Reply: ...

    def adopt(self, body: dict, hold: Any = None) -> dict: ...

    def note(self, msg: str) -> None: ...

    def _ids(self, rc_id: str, rec: str) -> dict: ...

    def _rec_status(self, rc: dict, rc_id: str, rec: str) -> Tuple[dict, float]: ...
