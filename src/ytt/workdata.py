"""編集の作業データの置き場所と版の「今の値」(役割で組み直す RS3-0A。2026-10-10)。

編集(src/editor の serve)が使う置き場所のパスと版を、モジュールの変数として 1 か所に持つ。どの層からも読める(ytt)。
以前は編集の ed_state(app の層)が持ち、下の層の部品(pipeline/transcribe・human/proof)は txenv の口
(app が登録する「呼ぶたびに ed_state の値を返す関数」)から読んでいた。持ち主を ytt に置けば、移した部品も同じ名前を直に読める。

- 値を入れるのは app と認識ワーカーだけ: 編集の ed_state が読み込みのときに set_root(編集のフォルダ。今までの読み込みの直後の既定と同じ)・
  serve が版(SERVER_VERSION)と起動時の作業データの切り替え(serve.set_data_dir → set_data_dir)・スタジオの data.json の場所(choose_data_dir)。
  認識ワーカー(pipeline/transcribe/worker.py)は自分のプロセスで DATA_DIR を入れる。
- 読む側は `workdata.TX_DIR` のように**呼ぶたびに**読む(`from ytt.workdata import TX_DIR` で写さない)。テストの `S.TX_DIR = …`・
  `mock.patch.object(S, "SETTINGS", …)` は serve の名前の受付(ytt/modfwd.py)がここへ届ける。ed_state に同じ名前を残さない(別名に当たって届かなくなる)。
- 既定は None(入れる前に読むと os.path.join が TypeError = 気づける)。ROOT の既定をリポジトリの src/editor にしない
  (テストは serve.py を一時フォルダに写して動かす。写した先のフォルダが ROOT)。
"""
import os

from . import layout as _layout

ROOT = None             # 編集のフォルダ(serve.py・ed_state.py のある所)。名簿 hololive-roster.json・認識ワーカーの cwd・.venv の基準
DATA_DIR = None         # 作業データ(起動時に serve が datadir で決める。読み込みの直後は環境変数 TRANSCRIBE_DATA_DIR か ROOT = テスト用)
TX_DIR = None           # 文字起こしの文書 <DATA_DIR>/transcripts
TMP_DIR = None          # 一時ファイル <TX_DIR>/.tmp
DATASET_DIR = None      # 校正の成果と音声の保管(将来の学習・声紋登録用)<DATA_DIR>/dataset
EVAL_DIR = None         # 設定の比較(A/B)の結果 <DATA_DIR>/evals
EVAL_BASE = None        # 精度の基準 <DATA_DIR>/eval-baselines.json
SETTINGS = None         # 編集の設定 <DATA_DIR>/settings.json
FEEDBACK = None         # 提案の採用・却下の記録 <DATA_DIR>/learn-feedback.json(設定ファイルとは別にして、画面側の保存と競合させない)
MARKER_DATA = None      # clip-marker の data.json(読むだけ。環境変数 TRANSCRIBE_MARKER_DATA)
STUDIO_DATA = None      # 切り抜きスタジオのマーク data.json(読むだけ。環境変数 TRANSCRIBE_STUDIO_DATA。起動時に serve の choose_data_dir が datadir の規則で入れ直す)
SERVER_VERSION = None   # 編集の版(正は serve.py の SERVER_VERSION。入口がその行を読む。serve が読み込みのときに入れる)


def set_root(root):
    """編集のフォルダ root から既定を入れる(編集の ed_state が読み込みのときに 1 回)。作業データは環境変数 TRANSCRIBE_DATA_DIR か root
    (起動したら serve が set_data_dir で本物の置き場所へ切り替える)。以前の ed_state の読み込みのときの値と同じ"""
    global ROOT, MARKER_DATA, STUDIO_DATA
    ROOT = root
    set_data_dir(os.environ.get("TRANSCRIBE_DATA_DIR") or root)
    MARKER_DATA = os.environ.get("TRANSCRIBE_MARKER_DATA") or os.path.join(os.path.dirname(root), "clip-marker", "data.json")
    STUDIO_DATA = os.environ.get("TRANSCRIBE_STUDIO_DATA") or os.path.join(_layout.tool_dir("studio", os.path.dirname(root)), "data.json")


def set_data_dir(d):
    """作業データの置き場所を d にして、その中のパスを作り直す(d はそのまま使う = 絶対パスにするのは呼ぶ側。
    serve.set_data_dir はログ・ワーカーの記録・環境変数・datadir の登録もする)"""
    global DATA_DIR, TX_DIR, TMP_DIR, DATASET_DIR, EVAL_DIR, EVAL_BASE, SETTINGS, FEEDBACK
    DATA_DIR = d
    TX_DIR = os.path.join(d, "transcripts")
    TMP_DIR = os.path.join(TX_DIR, ".tmp")
    DATASET_DIR = os.path.join(d, "dataset")
    EVAL_DIR = os.path.join(d, "evals")
    EVAL_BASE = os.path.join(d, "eval-baselines.json")
    SETTINGS = os.path.join(d, "settings.json")
    FEEDBACK = os.path.join(d, "learn-feedback.json")
