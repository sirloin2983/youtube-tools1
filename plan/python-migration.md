# Python 3.10 → 3.12 の移行(計画 O1 = 提案 P21 の下調べ)

状態: **下調べ済み・移行はまだ**(2026-10-08。ユーザー「任せる」。急がない = 配信の無い静かな日に 1 晩で。計画 `plan/data.js` の O1 の状態はこの文書に合わせる)

- 経緯: `plan/proposals-2026-10.md` の P21。Python 3.10 は 2026-10 に EOL。yt-dlp が「3.10 を EOL のあと程なく非対応に」と予告(Changelog 2026.07.04・issue #16916)
- 調べ方: サブエージェント(Sonnet)が PC の状態・固定の版の wheel・コードの 3.10 固定を確認(何も入れていない。`pip install --dry-run` だけ)

## 1. 分かったこと
- **yt-dlp は winget の exe(自己完結。同梱の Python 3.10.11)なので、3.10 の終了の影響を受けない**。pip 版ではない。issue #16917 で exe の同梱を 3.14 に上げる予定(Windows 10 以降が必須 → この PC は 11)。録画の streamlink は 3.10 の pip(`sys.executable -m streamlink`)= 新しい Python にも入れる
- PC には **3.12.10 が既に入っている**(pip だけの空。MSIX の写しの外 = 本物)。`py -3` は 3.12 を選ぶので、`push.bat` と `setup/cleanup_legacy_data.bat` は既に 3.12 で動いている(標準ライブラリだけなので無害)
- 固定の版(faster-whisper 1.2.1・ctranslate2 4.8.2・onnxruntime 1.23.2・numpy 2.2.6・sherpa-onnx 1.13.8・streamlink 8.6.1・playwright 1.63.0)は**すべて 3.12 の wheel がある**。`py -3.12 -m pip install --dry-run --only-binary=:all:` が 3 本の requirements で通った。3.13 も全部ある。3.14 は numpy・onnxruntime に無い
- 固定していない依存が変わる: **av 17.1.0 → 19.0.1**(faster-whisper の依存。19 は 3.12 以上限定)・pycryptodome 3.23 → 3.24・hf-xet・filelock。挙動を同じに保つなら `av==17.1.0` を固定
- torch・pyannote・funasr は入っていない(話者判別・SenseVoice・Qwen3-ASR は sherpa-onnx / llama.cpp 経由)
- コード: `imp`・`distutils`・`pkg_resources`・`asyncio`・古い unittest の別名・`datetime.utcnow` の使用は 0 件。警告だけ: `tarfile.extractall` に filter なし(`src/editor/tx_engines.py:648,960`)・`shutil.rmtree(onerror=)`(`src/recorder/rec_core.py:866`・`setup/build_whisper_vulkan.py:87`)。`os.path.realpath` が 26 か所(3.12 で Windows の挙動が少し変わった。両辺を同じ関数で比べるので影響は小さい見込み。D:・E: で 1 回確認)
- 3.10 を選ぶ所: `start.bat:7-8,21`・`src/home/start_hidden.vbs:11-13`・`setup/install*.bat` の 5-6,15・`setup/build-whisper-vulkan.bat:7-8`・`setup/bootstrap.bat`(winget `Python.Python.3.10`)。文書: `AGENTS.md`・`README.txt:40-42`・各 README/AGENTS・テストの先頭の実行例 約 40 本
- 3.11 ではなく **3.12 を勧める**: 既に入っている・固定の版を 1 つも変えずに移れる・EOL が 2028-10(3.11 は 2027-10)・numpy 2.5 と av 19 は 3.12 以上限定で 3.11 は先に置いていかれる。python.org の Windows installer は 3.12.10 が最後(次の移行は 2028 年ごろに 3.13/3.14)

## 2. 手順(1 晩)
1. AI: `setup/requirements.txt` に `av==17.1.0`(必要なら `pycryptodome==3.23.0`)。`install*.bat`・`build-whisper-vulkan.bat`・`bootstrap.bat` を 3.12 優先・3.10 は予備に。**`start.bat` と `start_hidden.vbs` は「`py -3.12 -c "import faster_whisper"` が通れば 3.12、だめなら 3.10」**にして、入れ忘れでも壊れない形に
2. ユーザー(10〜15 分): 自分の cmd で `py -3.12 -m pip install -r setup\requirements.txt -r setup\requirements-diarize.txt -r setup\requirements-dev.txt`(約 170MB)。**AI のシェルから pip を打たない**(MSIX の写しに入って start.bat から見えない)
3. AI(1.5〜2 時間): 全 unittest・node のテスト・e2e を 1 本ずつ・`dev/lint.py`・`ui_audit.py all --demo`。本物の部品を通す確認を手で 4 点: ① faster-whisper で 1 本文字起こし ② 話者判別(sherpa-onnx。`dev/eval_speakers.py`)③ SenseVoice の後処理と Qwen3-ASR ④ 録画(streamlink。`test_recorder.py:396` は streamlink が無いと skip = 通過ではない)
4. 切り替えと文書: `py -3.10` → `py -3.12`(AGENTS.md の動作環境・README・各 AGENTS・テストの実行例)。WORKLOG・`plan/data.js` の O1 を済みに。1 コミット
- 戻し方: 3.10 は消さず 1 週間ほど併存。戻すときはそのコミットを revert するだけ。作業データ(JSON・モデル)は Python の版に依らない

## 3. リスク
1. 固定していない依存の差(av 19・pycryptodome 3.24)→ `av==17.1.0` を固定。録画の AES 復号は本物の配信で 1 回確認
2. ネイティブ部品(ctranslate2・onnxruntime・sherpa-onnx)の読み込み(以前の CPU で稀に落ちた記録)→ 2 の 4 点で確認
3. `realpath` の挙動差(D:・E: ドライブ)
4. 空の 3.12 があり `py -3` が 3.12 を選ぶ → 1 の「import が通れば」の判定で守る
