# コードレビュー 2026-10-12(2 回目)

状態(2026-10-12): レビュー済み。新規指摘 6 件(P1 2 件・P2 4 件)、修正は未着手。対象 HEAD `4d6a869d`、全体の版 `0.61.0`。開始時の未コミット変更なし。コード・テスト・設定は変更していない。

依頼書 `docs/design/code-review-brief-2026-10-12.md` の 8 節を中心に調べた。7 節の既知の物(前回の 7 件・10-08 の簡潔化レビュー・OPT のメモ・improvements・WORKLOG の未修正事項・友人アプリの暫定要件)は重複報告から外した。

## 範囲と調べ方

まとめ役が `ytt/fsio`・`docloc`・`casefiles`・`flow/casebook`、学習の読み口と保存先、HTTP の検査・取り込み・送り返し zip の展開を確認した。サブエージェント 3 体が次を並列で確認した。全員このチャットと同じモデルを使用した(単純な棚卸しでなく、原因調査と影響判断を伴うため)。途中で利用上限による中断があり、ユーザーの「続行」後に各体を再開して再現と報告を完了した。

- ① 道具: `pipeline/export/exporter.py`・`pipeline/pack/`・`pipeline/analyze/` の時刻・失敗・中止の境界。
- 校正と認識: `human/proof/{store,doc_jobs,rerun,overrides,layers,machpick,speakers}` と `pipeline/transcribe/{recognize,worker,retime,llm}`、関連テスト・編集画面のジョブロック。
- ライブ: `flow/livesession.py`・`live_export`・`live_archive`・`live_detect`・`live_tx`、`pipeline/ingest/{rec_core,recorder}` と関連テスト。

認識エンジン・fill・diarize・LLM の全アルゴリズム、すべての API/画面/子プロセス、層の「精神」の全関数を網羅したものではない。実配信・GPU 認識・本物の Dropbox・稼働中の入口・本物の作業データは使っていない。追加のセキュリティ指摘は確証を得られず、今回の指摘には含めない。

## 指摘

### 1. [P1] 全体再認識の受付後に保存した校正行を、結果の反映で消す

- 位置: `src/human/proof/rerun.py:220–223,255–257,273–284`。受付は `src/human/proof/doc_jobs.py:477–485`。
- 条件: `mode="whole"` の受付時には未校正だった行を、認識・待機中に別タブなどから修正し、`proofed=True` で保存する。その後、全体再認識の結果を反映する。
- 原因: 受付時の `spec["ids"]` を反映時にも固定で使う。`plan_range()` は対象 ID の現在の本文や校正済みの印を確認せず、守る区間から外す。`_apply_range()` は対象行を `rest` から除いて機械の新しい行に差し替える。保存ロックは反映中だけで、認識中に終わった保存を守れない。保存 API 自体は再認識中の保存を断らない。
- 影響: 保存済みの本文と校正済みの印が黙って消え、ジョブは成功する。`primary` でも人の層が `rows=[]` に更新され、再組み立てでは戻らない。バックアップから救済できる可能性はあるが、現行の直しは失われる。
- 再現: 付録 A。実 `save_transcript`・`apply_range`・`commit`・層の差分/組み立てを通し、文書/層の I/O と認識記録をモック。保存後 `s1/human-fixed/proofed=True` が、反映後 `r1/machine-new/proofedなし` になり、結果は `kept=0`、人の層は空。
- 直し方の方針: 反映ロック内で現在の行を再検査する。全体再認識では現在の校正済み行を対象から外し、本文・original・単語の守る対象をそろえる。受付後に変わった未校正の本文/時刻も開始時の版や内容と比べて保護するか競合として断る。`apply_redo()` の `rerun.py:329–332` にある現在の校正済み/旧本文の検査を参考にできる。
- テストの穴: `test_primary_ops.py` は each の校正済み保護を試すが、whole の受付後に校正済みへ変わった行を試していない。前回の確認カード不一致・カット保存とは別の反映経路。

### 2. [P1] 学習用の読み取りが共通の保存先を変え、別スレッドの校正を別データへ保存する

- 位置: `src/flow/learning.py:113–119,125,138`。保存先をその都度読む側は `src/human/proof/store.py:30–54,562–576`、`src/ytt/docloc.py:53–55,132–136`。
- 条件: `machine.learningDir` が既定以外の「文書を持つ作業データ」(learning.json の束ではない)を指す。そこに元と同じ ID/版の文書のコピーがあり、学習の用語/置換を読む間に別スレッドがその文書を保存する。学習の読み口は保存ロックを取らない。
- 原因: `_scoped()` が読み取りのためにプロセス共通の `workdata.TX_DIR` を一時的に変更する。`docloc`・保存・履歴などの利用者もその変数を読むため、別スレッドの読み書きまで学習先へ向く。`finally` の復元は、その間に誤った場所へ保存した内容を戻さない。同じ ID/版のコピーなら通常の `baseUpdatedAt` の競合検査も通る。
- 影響: 保存 API は成功を返すのに、元の文書を開き直すと人の直しが無い。学習用のコピーが書き換わる。索引が無い文書で再現し、新しく生成する文書も別の根に置かれ得る。
- 再現: 付録 B。2 つの一時的な根に同じ文書がある形をメモリ I/O で作り、実 `_scoped` の内部を Event で待たせて実 `save_transcript` を呼ぶ。`save returned=human edit`、`main reopened=before`、`learning copy=human edit`。層のモードは off で再現し、層によらない保存先の問題として確認した。
- 直し方の方針: 読む根を学習関数/文書の読み手へ引数で渡し、共通の `TX_DIR` を変えない。読み手同士だけのロックでは保存側を守れない。二つの根を Event で交差させるテストで保存先を確認する。
- テストの穴: `test_learning.py` は束・文書なしを中心に試し、文書がある別の根と通常保存の交差を試していない。前回の「同期が稼働中に届かない」とは別で、起動時に学習先を正常に配線していても起きる。

### 3. [P2] 文書のある別の学習先を使うと、辞書の版の読み口が循環する

- 位置: `src/flow/learning.py:127–132`、`src/human/proof/doc_jobs.py:281–286`。配線は `src/app/server.py:1434–1446`、実際の呼び出しは `src/pipeline/transcribe/records.py:109–124`。
- 条件: 起動時に既定以外の文書を持つ `learningDir` を指定し、learning.json の束が無い。入口が `doc_jobs.set_learning(lr)` を済ませ、`autoLearned=True` で辞書の版を作る。
- 原因: `Learning.dict_learned()` が human_loader の `doc_jobs.dict_learned()` へ戻り、その関数は登録済みの同じ `Learning.dict_learned()` へ委譲する。`Learning → doc_jobs → Learning` の循環に終了条件がない。`records.dict_version` は `RecursionError` を捕捉しない。
- 影響: 認識の記録/辞書の版を作る処理が `RecursionError` で止まり、通常の文字起こし処理を失敗させる。束を使う場合・文書が無い場合・既定の根ではこの経路を通らない。
- 再現: 付録 C。実 Learning と doc_jobs を入口と同じように配線し、文書の存在確認だけモック。実 `records.dict_version({"autoLearned": True})` が `RecursionError` になる。学習 JSON の同期や設定保存の失敗は不要。
- 直し方の方針: 文書から読む枝では、委譲を含まない `learn.dict_learned_text()` などの生の読み口を呼ぶ。入口と同じ配線で、文書あり/束なしの辞書の版が有限時間で返る unittest を加える。
- テストの穴: 付録 B と同じ文書ありの枝が未検証。前回の学習同期未反映とは異なる循環呼び出し。

### 4. [P2] 連続録画中は空き容量を再検査せず、1 GB の停止条件を通過する

- 位置: `src/pipeline/ingest/rec_core.py:465–472,568–592`。
- 条件: 録画開始時には 1 GB 以上空いているが、切断せず続く配信の録画中に空きが 1 GB 未満になる。
- 原因: 空き容量の検査は `_run()` のセッション開始前だけ。`_run_session()` の継続ループに検査がなく、外側へ戻るのは主に切断/終了のとき。
- 影響: README と recorder/AGENTS の「空きが 1 GB を切ったら止める」が連続配信では働かない。満杯まで書き続け、録画や同じドライブの別の作業の保存失敗につながる。実際にディスクを満杯にはしていない。
- 再現: 付録 D。実 Recording に対してプロセス・セグメント数・容量・待ちをモック。2 GB で開始後 512 MB に減らすと `folder_state` は 1 回しか呼ばれず、512 MB のままセグメント取得と `recording` が継続。最後は試験側の明示停止で `stopped` になる。
- 直し方の方針: セッション内でも一定間隔で空きを検査する。下限到達を通常の切断と区別し、子を終了して容量不足で完了させ、再接続しない。
- テストの穴: 開始前の容量検査はあるが、連続録画中に下限を割るケースが無い。既知の F1 保存先/容量測定の問題や、容量検査の重複整理とは異なる。

### 5. [P2] 同時開始の字幕を最終コマの外へ動かし、Text+ パックの作成が止まる

- 位置: `src/pipeline/pack/resolve_textplus.py:219–221,309–310`。
- 条件: 4 件以上の字幕が同じコマに始まり、最大 3 段の溢れを後ろへずらす余地が残す区間末尾にない。30fps の `[0,300)` の最後に 4 件の `[299,300)` など。
- 原因: `stack_captions()` は区間の端を知らず、3 段が埋まると次の字幕を 1 コマ以上後ろへずらす。その結果 `[300,301)` が作られ、`caption_segments()` が所属する区間を見つけられない。
- 影響: 入力字幕はすべて正常な区間内なのに `ValueError` でパック作成が止まる。中間のカット末尾では次の残す区間へ字幕が移る可能性もある(今回の確定再現は動画末尾)。
- 再現: 付録 E。純粋な関数と SimpleNamespace だけで、4 件目が `[300,301)` になり、`ValueError 字幕 4 がどの残す区間にも入りません(開始 300 コマ)`。
- 直し方の方針: 段を割り当てる際に元の区間番号と端を保ち、時刻変更をその区間内へ収める。収まらないときの扱いも決める。動画/各カット末尾と同時開始を組み合わせて検査する。
- テストの穴: `TestCaptionLanes.test_same_start_never_loses_a_caption` は溢れを試すが、区間端との接続を試していない。既存 10 件が成功しても再現は失敗する。前回 7 件や簡潔化の指摘とは異なる①の時刻計算。

### 6. [P2] Text+ 再作成が失敗すると、既存パックが新しい動画と古い字幕の混在になる

- 位置: `src/pipeline/pack/pack.py:752–756,764–769`。
- 条件: 既存パックを `force=True` で作り直して同梱動画も更新し、動画の公開後に Lua・登録スクリプト・雛形の作成が失敗する(持続する共有違反/書き込み不可など)。
- 原因: 動画を完成名へ置き換えて `staged` から外したあとに `TP.write_files()` を呼ぶ。後者が失敗しても `finally` は残る一時ファイルだけを消し、先に更新した動画や EDL/SRT/計画を戻さない。各ファイルが原子的でもパック一式の世代はそろわない。
- 影響: 作成は失敗を返すが、前に成功したパックも保持されない。古い Lua のカット/字幕を新しい動画に適用すると不一致が生じる。
- 再現: 付録 F。一時フォルダで完成済みパックを作り、動画と区間を変え、Text+ 書き込みだけ PermissionError にする。Lua は前と同じ(終了コマ 300)、今回の区間は 150、動画は新内容へ置き換わっている。sandbox の正常な rename の制約はコピー+unlink のモックで切り離した。
- 直し方の方針: Lua/雛形を含む全成果物を別の一時フォルダで完成させてから公開する。既存更新は世代ごとの入れ替えか退避/ロールバックで前の完成品を保持する。途中の書き込み/置き換え失敗で世代が混ざらない検査を加える。
- テストの穴: 単一ファイルの staged 成功/失敗の検査だけでは、動画公開後の Text+ 失敗を守れない。前回の idle/送り返し zip は②の終了判定で、今回の①の公開順とは別。

## 検証と限界

- Python 3.10.11。`py -3.10` の環境依存を避け、インストール済みの `Python310/python.exe` を直接使用。
- `dev/lint.py`: 合計 0 件。
- `dev.tests.test_layering`・`src.ytt.tests.test_docloc`・`src.ytt.tests.test_ytt_core.TestFsio`・`src.flow.tests.test_casebook`・`src.flow.tests.test_learning`: 105 件 OK。
- `src.pipeline.pack.tests.test_pack.TestCaptionLanes`: 10 件 OK。合計 115 件。新しいテストファイルは作っていない。
- 最初の 105 件は sandbox の一時領域で rename/replace が WinError 5 になり、3 failures/36 errors。同じ検査を許可された通常権限で実行すると全部成功したため、製品の指摘には数えない。
- 再現 A〜F は一時データまたはメモリ I/O/プロセスのモックで実行。イベントの待ちは処理順を固定するため。実 GPU・実 ffmpeg/配信・Resolve の Lua 実行・ブラウザ操作・e2e は未実施。
- 調べた基盤/HTTP/zip に追加の確定指摘はない。安全性の保証ではない。つなぐ書き出しの音量失敗時の残骸・解析の中止境界は再現を確定できず見送った。

## 付録: 再現コード

リポジトリ直下で、各ブロックを別々の Python 3.10 プロセスへ渡す。すべて標準ライブラリとリポジトリの部品だけを使う。本物の作業データへの書き込み・サーバーの起動は行わない。

### A. 全体再認識中の校正保存

```python
import copy, os, sys
from contextlib import ExitStack
from unittest.mock import patch
os.environ["YTT_DATA_DIR"] = "inplace"
os.environ["TRANSCRIBE_LAYERS"] = "primary"
sys.path.insert(0, os.path.abspath("src"))
from human.proof import store, rerun
from ytt import schemas as ys

tid = "0123456789ab"
docs, layers = {}, {}
def read_layer(t, suffix, schema):
    return copy.deepcopy(layers.get((t, suffix)))
def write_layers(t, why, sh):
    layers[(t, ys.HUM_SUFFIX)] = copy.deepcopy(sh["hum"])
    if sh["writeMach"]:
        layers[(t, ys.MACH_SUFFIX)] = copy.deepcopy(sh["mach"])
def write_doc(t, doc, folder=None):
    docs[t] = copy.deepcopy(doc)
doc = {"schema": "transcribe/v1", "id": tid, "title": "t",
       "sourcePath": "video.mp4", "start": 0, "end": 5,
       "speakers": [], "updatedAt": 1,
       "segments": [{"id": "s1", "start": 0., "end": 5.,
                     "text": "machine-old", "speaker": "", "flag": ""}],
       "original": [{"start": 0., "end": 5., "text": "machine-old"}]}
patches = [
    (store, "tx_path", lambda t: "mock.json"),
    (store, "_read_layer", read_layer),
    (store, "_shadow_write", write_layers),
    (store, "write_doc", write_doc),
    (store, "_load_doc", lambda p: copy.deepcopy(docs.get(tid))),
    (store, "read_transcript", lambda t: copy.deepcopy(docs[t])),
    (store, "apply_edit_cuts", lambda *a: None),
    (store, "backup_doc", lambda *a: None),
    (store, "snapshot", lambda *a: None),
    (store._settings, "in_eval_dir", lambda *a: False),
    (store._overrides, "save_after", lambda *a: True),
    (rerun._flowtx, "dict_pairs", lambda *a: []),
    (rerun._flowtx, "rerun_base", lambda *a: {"kind": "whole"}),
    (rerun, "replace_words", lambda *a: None),
]
with ExitStack() as stack:
    for owner, name, replacement in patches:
        stack.enter_context(patch.object(owner, name, replacement))
    store.commit(tid, doc, why="whole")
    spec = {"tid": tid, "range": [0., 5.], "ids": ["s1"],
            "model": "large-v3", "mode": "whole", "autoDict": False}
    human = store.read_transcript(tid)
    human["segments"][0].update(text="human-fixed", proofed=True)
    store.save_transcript(tid, dict(human, baseUpdatedAt=human["updatedAt"]))
    print("BEFORE", docs[tid]["segments"])
    print("RESULT", rerun.apply_range(spec, [
        {"start": 0., "end": 5., "raw": "machine-new", "flag": ""}]))
    print("AFTER", docs[tid]["segments"])
    print("HUM", layers[(tid, ys.HUM_SUFFIX)]["rows"])
```

### B. 学習読み取りと保存先の交差

```python
import copy, json, os, sys, tempfile, threading
from unittest.mock import patch
sys.path.insert(0, os.path.abspath("src"))
os.environ["YTT_DATA_DIR"] = "inplace"
os.environ["TRANSCRIBE_LAYERS"] = "off"
from ytt import workdata, docloc
from flow import learning
from human.proof import store, learn, doc_jobs

with tempfile.TemporaryDirectory() as td:
    ld = os.path.join(td, "learn")
    main = os.path.join(td, "main", "transcripts")
    os.makedirs(os.path.join(ld, "transcripts")); os.makedirs(main)
    tid = "012345abcdef"
    mp = os.path.join(main, tid + ".json")
    lp = os.path.join(ld, "transcripts", tid + ".json")
    doc = {"id": tid, "title": "test", "updatedAt": 100, "speakers": [],
           "segments": [{"id": "s1", "start": 0, "end": 1,
                         "text": "before", "speaker": ""}]}
    mem = {mp: copy.deepcopy(doc), lp: copy.deepcopy(doc)}
    old = workdata.TX_DIR
    workdata.TX_DIR = main
    entered, release = threading.Event(), threading.Event()
    def pause(*a, **k):
        entered.set(); assert release.wait(10); return []
    def write(p, data, **k):
        mem[p] = json.loads(data)
    try:
        lr = learning.Learning(ld, human_loader=lambda: (learn, doc_jobs))
        with patch.object(docloc, "iter_tids", return_value=[tid]), \
             patch.object(learn, "auto_glossary", side_effect=pause), \
             patch.object(os.path, "isfile", side_effect=lambda p: p in mem), \
             patch.object(store, "_load_doc", side_effect=lambda p: copy.deepcopy(mem.get(p))), \
             patch.object(store._fsio, "atomic_write", side_effect=write), \
             patch.object(store, "snapshot"), patch.object(store, "effort_rows"), \
             patch.object(store, "apply_edit_cuts"), patch.object(store._overrides, "save_after"):
            displayed = store.read_transcript(tid)
            displayed["baseUpdatedAt"] = 100
            displayed["segments"][0]["text"] = "human edit"
            t = threading.Thread(target=lambda: lr.glossary([]))
            t.start(); assert entered.wait(5)
            try:
                saved = store.save_transcript(tid, displayed)
            finally:
                release.set(); t.join(5)
            print("save returned =", saved["segments"][0]["text"])
            print("main reopened =", store.read_transcript(tid)["segments"][0]["text"])
            print("learning copy =", mem[lp]["segments"][0]["text"])
    finally:
        workdata.TX_DIR = old
```

### C. 学習の辞書の版の循環

```python
import os, sys, tempfile
from unittest.mock import patch
sys.path.insert(0, os.path.abspath("src"))
os.environ["YTT_DATA_DIR"] = "inplace"
from flow import learning
from ytt import docloc
from human.proof import doc_jobs, learn
from pipeline.transcribe import records
with tempfile.TemporaryDirectory() as ld:
    os.makedirs(os.path.join(ld, "transcripts"))
    lr = learning.Learning(ld, human_loader=lambda: (learn, doc_jobs))
    doc_jobs.set_learning(lr)
    records.set_dict_inputs(pairs=lambda spec: [], learned=doc_jobs.dict_learned)
    try:
        with patch.object(docloc, "iter_tids", return_value=["012345abcdef"]):
            try:
                records.dict_version({"autoLearned": True})
            except RecursionError:
                print("dict_version = RecursionError")
    finally:
        doc_jobs.set_learning(None)
```

### D. 連続録画中の空き容量

```python
import os, sys, tempfile
from unittest.mock import Mock, patch
sys.path.insert(0, os.path.abspath("src"))
from pipeline.ingest import rec_core as R
with tempfile.TemporaryDirectory() as td:
    mgr = Mock(source="direct", ffmpeg="mock", hls_time=4, poll=0,
               idle_end=600, wait_start=21600)
    mgr.backoff = (0,)
    rec = R.Recording(mgr, "20261012-120000-test", td,
                      {"state": "waiting", "url": "http://127.0.0.1/mock", "sessions": []})
    rec.save = Mock()
    rec._popen = Mock(return_value=Mock(
        poll=Mock(return_value=None), stdin=None, returncode=None))
    rec._kill_procs = Mock(); rec._too_fast = Mock(return_value=False)
    disk = {"freeBytes": 2 * R.MIN_FREE, "message": ""}
    seen, n = [], [0]
    def count(_):
        n[0] += 1
        seen.append((n[0], disk["freeBytes"], rec.meta["state"]))
        if n[0] == 4:
            rec._stop.set()
        return n[0]
    def sleep(_):
        disk["freeBytes"] = R.MIN_FREE // 2
    rec._count = count
    with patch.object(R, "folder_state", side_effect=lambda _: dict(disk)) as check, \
         patch.object(R.time, "sleep", side_effect=sleep):
        rec._run()
    print("folder_state calls:", check.call_count)
    print("observations:", seen)
    print("final state:", rec.meta["state"])
```

### E. 最終コマの字幕の段の溢れ

```python
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path("src").resolve()))
from pipeline.pack import resolve_textplus as TP
p = SimpleNamespace(meta={"fps": (30, 1), "w": 1920, "h": 1080, "total": 300},
                    req=SimpleNamespace(name="demo"), video=Path("demo.mp4"),
                    keeps=[(0, 300)],
                    cues_out=[(299, 300, t) for t in ("a", "b", "c", "d")])
print(TP.stack_captions(p.cues_out, (30, 1))["cues"])
try:
    TP.build_import_plan(p, "demo.mp4")
except ValueError as e:
    print(type(e).__name__, str(e))
```

### F. 動画公開後に Text+ を書けない再作成

```python
import os, sys, tempfile, shutil, dataclasses
from pathlib import Path
from unittest.mock import patch
os.environ["YTT_DATA_DIR"] = "inplace"
sys.path.insert(0, str(Path("src").resolve()))
from pipeline.pack import pack, resolve_textplus as TP, srt2resolve as S
from ytt import fsio
with tempfile.TemporaryDirectory() as td:
    d = Path(td); src = d / "source.mp4"; sub = d / "a.srt"
    src.write_bytes(b"original-video")
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\na\n", encoding="utf8")
    meta = {"fps": (30, 1), "w": 1920, "h": 1080, "total": 300,
            "frames_source": "mock", "codec": "h264", "pix_fmt": "yuv420p",
            "audio": None, "warnings": [], "duration": 10, "start_tc": None}
    req = pack.Request(src, sub=sub, min_len=0)
    with patch.object(S, "probe", return_value=meta):
        plan = pack.plan_cut(req)
    def write(path, text, encoding="utf-8", newline="\n"):
        Path(path).write_text(text, encoding=encoding)
    def replace(src, dst):
        shutil.copyfile(src, dst); Path(src).unlink()
    opts = dict(textplus=True, force=True, backup=False, plan_file=False, readme_file=False)
    with patch.object(S, "write_text_atomic", side_effect=write), \
         patch.object(fsio, "replace_retry", side_effect=replace):
        out = d / "pack"
        pack.build_pack(plan, out, **opts)
        lua = out / "create_resolve_textplus_project.lua"
        old_script = lua.read_text(encoding="utf8")
        src.write_bytes(b"changed-video-with-different-size")
        newer = dataclasses.replace(plan, keeps=[(0, 150)])
        with patch.object(TP, "write_files", side_effect=PermissionError("mock: Text+ script is locked")):
            try:
                pack.build_pack(newer, out, **opts)
            except PermissionError as e:
                print("rebuild:", type(e).__name__, str(e))
        print("old script retained:", lua.read_text(encoding="utf8") == old_script)
        print("script sourceEndFrame:", TP.read_script_plan(old_script)["cuts"][0]["sourceEndFrame"])
        print("requested sourceEndFrame:", newer.keeps[0][1])
        print("new video already committed:", (out / "source.mp4").read_bytes() == src.read_bytes())
```
