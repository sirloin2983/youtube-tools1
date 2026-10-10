"""API の失敗の形(役割で組み直す RS2-1a。2026-10-10 に編集の ed_state から移した)。

`ApiError(code, message, status=400, extra=None)`: code = 画面・テストが見る理由の短い名前、message = 画面に出す文、
status = HTTP の状態、extra = 応答に足す値(`detail` は「詳しく」の中だけに出す原文)。
編集の部品は今までどおり `ed_state.ApiError` で読める(同じクラスの別名。差し替えない名前なので別名にした)。
認識の部品(pipeline/transcribe)は ed_state(app)を読まずにここを読む。cut2resolve の ApiError は別のクラスのまま。
スタジオの ApiError・Cancelled も RS3-4(2026-10-10)にここへ 1 つにした(スタジオの extra は None だったが、読む側は `e.extra or {}` で読むので {} でも同じ)。

`Cancelled`: 中止(ジョブの cancel が立った)。スタジオの外部コマンドの実行(ytt/procs.run_capture)と編集のジョブの表(ytt/jobs.check_cancel)が上げる。
"""


class ApiError(Exception):
    def __init__(self, code, message, status=400, extra=None):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra or {}


class Cancelled(Exception):
    pass


class ResolveExportError(ValueError):
    """Resolve パックの書き出し(pipeline/pack/resolve_export)の失敗。メッセージは画面に出せる文。
    RS6 a-1(2026-10-10)に resolve_export から移した(③ 人・④ データが ① を読まずに捕まえられるように)"""
