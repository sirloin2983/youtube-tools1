"""認識の部品が共有する小さな物: 記録(ロガー)・決まった値(文字・言語・長さの上限)・要確認の印の文と幻覚の決まり文句・ジョブの注意。

役割で組み直す RS2-1a(2026-10-10)に編集の ed_state(app の層)から移した。ed_jobs の中身を pipeline/transcribe へ移したとき、
移した先が ed_state を読まずに済むように。ed_state には同じ物の別名を残している(どれも差し替え・付け直しをしない名前 =
テストも本体も `S.名前 = …` をしていないことを確かめてから移した)。差し替える名前(置き場所のパス・ffmpeg など)は移さない(RS3-0A から持ち主は ytt/workdata・ytt/tools・worker_client。それまでは txenv の口)。
RS2-9 で足した物: 比べるときの文字の寄せ方 alt_fold(ed_alt から)・環境変数のスイッチ env_off(ed_state から)。
"""
import logging
import os
import re
import unicodedata

log = logging.getLogger("tx")   # 編集の記録(serve.log)。ed_state.setup_logging がこの logger に書き先を付ける(名前で同じ物)

MAX_TEXT = 2000   # 1 行の文字の上限
MAX_SPAN_SEC = 6 * 3600   # 1 回の文字起こし・全体の再認識の長さの上限(秒)
LANGS = ["ja", "en", "ko", "zh", "auto"]

HALLUC = ("ご視聴ありがとうございました", "チャンネル登録", "字幕", "Thanks for watching", "Subtitles by", "ご清聴ありがとうございました")
# よくある誤認識の文(S-3。2026-09-29 に足した分): 配信者が本当に言うこともある文なので、**行のほとんどがその文のとき**だけ印を付ける
# (上の HALLUC は以前からの決まりのまま = 文の一部に含まれれば印)。Whisper が無音・BGM から出しやすい動画の締めの決まり文句と、音楽の表記
HALLUC_LINE = ("ご視聴いただきありがとうございました", "ご視聴いただきありがとうございます", "ご覧いただきありがとうございました",
               "最後までご視聴", "高評価よろしくお願いします", "高評価お願いします", "高評価とチャンネル登録", "グッドボタン",
               "次回もお楽しみに", "次の動画でお会いしましょう", "次回の動画でお会いしましょう", "また次回お会いしましょう",
               "今日の動画はここまで", "今回の動画はここまで", "Thank you for watching", "Please subscribe", "Amara.org")
HALLUC_LINE_REST = 3    # 決まり文句を除いた残りがこの文字数以下なら「行のほとんどがその文」
MUSIC_ONLY = re.compile(r"^[\s♪♫♬～~〜・.。、]*([(（\[［【]\s*(音楽|拍手|BGM|ＢＧＭ)\s*[)）\]］】])?[\s♪♫♬～~〜・.。、]*$")
LEAK_FLAG = "ヒントの語だけ(プロンプトの漏れ出しの可能性)"
LEAK_MAX_SEC = 3.0      # 短い区間で、認識のヒントに渡した語だけが出た行(声が無い所でヒントを書き写すことがある。S-3)
REP_MIN = 5             # 行の中で同じ語(2〜10 文字)がこの回数以上続いたら「繰り返しの可能性」(笑い・叫びの 1 文字の繰り返しは除く)
REP_RE = re.compile(r"(.{2,10}?)\1{%d,}" % (REP_MIN - 1))

MIXED_FLAG = "声が混ざっている可能性"   # 話者判別の要確認の印
WEAK_FLAG = "話者が不確か"
NONE_FLAG = "話者を判別できなかった"
SPK_FLAGS = (MIXED_FLAG, WEAK_FLAG, NONE_FLAG)   # 話者の印(行の flag のうち文字の印と分ける。選んだ行の再認識は残し、判別は付け直す。RS2-8a に ed_jobs から移した)


def char_class(ch):
    """文字の種類。K=カタカナ(ー・を含む) / H=漢字 / A=英数字。それ以外(ひらがな・記号・空白)は空。単語の切れ目の判定に使う
    (行を分ける postproc._cut_words と、学習の語の境目 ed_learn。RS2-4b に ed_learn._cc から移した)"""
    o = ord(ch)
    if 0x30A1 <= o <= 0x30FA or ch in "ー・ヽヾ":
        return "K"
    if 0x4E00 <= o <= 0x9FFF or ch in "々〆":
        return "H"
    if (ch.isascii() and ch.isalnum()) or 0xFF10 <= o <= 0xFF19 or 0xFF21 <= o <= 0xFF3A or 0xFF41 <= o <= 0xFF5A:
        return "A"
    return ""


ALT_DROP_CHARS = "ー〜～~"   # alt_fold で無視する字(伸ばし。表記だけの違いにしない)


def alt_fold(ch):
    """比べるときだけの寄せ方: NFKC・小文字・カタカナ → ひらがな・伸ばしと記号と空白は捨てる(文字でも数字でもないもの)。
    2 つ目のエンジンの食い違い(ed_alt)・YouTube の字幕(ed_ytcap)・行の時刻の候補(ed_retime)・dev/eval_alt が同じ寄せ方を使う
    (RS2-9 に ed_alt から移した。ed_alt には別名がある)"""
    out = []
    for c in unicodedata.normalize("NFKC", ch).lower():
        o = ord(c)
        if 0x30A1 <= o <= 0x30F6:
            c = chr(o - 0x60)
        if c in ALT_DROP_CHARS or unicodedata.category(c)[0] not in "LN":
            continue
        out.append(c)
    return "".join(out)


def add_warning(job, msg):
    """ジョブの注意(画面の知らせ)を 1 つ足す。新しい list に付け直す(/api/jobs が JSON にしている最中の list を書き換えない)"""
    job["warnings"] = list(job.get("warnings") or []) + [msg]


def env_off(name):
    """環境変数 name が「止める」の値(off・0・no・false。大文字小文字と前後の空白は問わない)か(裏の処理を止めるスイッチ。
    RS2-9 に編集の ed_state から移した。ed_state には別名がある)"""
    return os.environ.get(name, "").strip().lower() in ("off", "0", "no", "false")
