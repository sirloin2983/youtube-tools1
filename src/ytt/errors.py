"""API の失敗の形(役割で組み直す RS2-1a。2026-10-10 に編集の ed_state から移した)。

`ApiError(code, message, status=400, extra=None)`: code = 画面・テストが見る理由の短い名前、message = 画面に出す文、
status = HTTP の状態、extra = 応答に足す値(`detail` は「詳しく」の中だけに出す原文)。
編集の部品は今までどおり `ed_state.ApiError` で読める(同じクラスの別名。差し替えない名前なので別名にした)。
認識の部品(pipeline/transcribe)は ed_state(app)を読まずにここを読む。スタジオ・cut2resolve の ApiError は別のクラスのまま。
"""


class ApiError(Exception):
    def __init__(self, code, message, status=400, extra=None):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra or {}
