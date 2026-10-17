# -*- coding: utf-8 -*-
"""友人のアプリの「送った物」の行に出す、失敗の言葉と進み具合を作る部品(F3-3。notes:plan/f1-friend-requirements.md の C-2-15・C-2-16)。純粋な関数だけ(ファイルもネットも触らない。時計は引数で受ける)。

- classify(text, kind) = ② や同期が出した失敗の文を、友人の言葉(次にすること 1 つ)と再試行の可否に直す。表 CODES は上から順に当てる
- stage(steps, kind, ranged) = ② の実行の段を友人の 5 段(動画を取得・見どころを探す・切り抜き・文字起こし・仕上げ)に読み替えて、今の段を返す
- eta(stats, kind, ranged, label, elapsed) = 残り時間の見積もり(記録は玄関が持つ。ここは読むだけ)。record(stats, label, seconds) = 記録の写しに 1 つ足す
- slow(...) = 1 つの段で 10 分進みが無いか。text(...) = 画面に出す 1 行

画面と玄関は別の部品が作る。ここは形だけを決める(段の名前・戻り値の形は C-2-15・C-2-16 の通り)。
"""
import math
import re

DETAIL_MAX = 500                    # 元の文を残す字数
SLOW_SEC = 600                      # 1 つの段で進みが無いまま経った秒(10 分)
ETA_SHORT_MSG = "あと 1 分ほど"

STAGES_URL = ("動画を取得", "見どころを探す", "切り抜き", "文字起こし", "仕上げ")
STAGES_FILE = ("動画を取得", "文字起こし", "仕上げ")
# ② の段の鍵 -> 友人の段の名前(normalize = 写して 30fps にそろえる = 動画を取得)
FRIEND_OF = {"normalize": "動画を取得", "analyze": "見どころを探す", "adopt": "見どころを探す", "export": "切り抜き",
             "transcribe": "文字起こし", "diarize": "文字起こし", "pack": "仕上げ", "analyze_later": "仕上げ", "deliver": "仕上げ"}
FETCH_WORDS = ("取得", "ダウンロード", "取って", "download")   # detail にこの語があれば 見どころ・切り抜き は 動画を取得 の段
RANGE_MSG_FILE_SKIP = "rangeOver"   # 動画ファイルでは出さない code

FILE_UNAVAILABLE = "動画ファイルが見つかりません。もう一度選んで送ってください"
UNKNOWN_MSG = "うまくいきませんでした。[もう一度送る] を押してください"

# 失敗の言葉の表(上から順に当てる)。(code, 当てる文の字句, message, retry)。字句は小文字にして照らす
CODES = (
    ("members", ("メンバー限定", "members only", "Join this channel"),
     "メンバー限定の配信は切り抜けません。別の配信を選んでください", False),
    ("unavailable", ("非公開", "削除", "Private video", "Video unavailable", "This live event will begin", "まだ公開"),
     "この配信は今見られません(非公開か削除された可能性があります)。見られるようになってから [もう一度送る] を押してください", False),
    ("noArchive", ("アーカイブが出ませんでした", "アーカイブがまだ", "no archive"),
     "アーカイブが出ませんでした。配信者がアーカイブを残さなかった可能性があります", False),
    ("rangeOver", ("長さを超え", "配信の長さ", "区間が長すぎ", "out of range"),
     "区間が配信の長さを超えています。区間を直して送り直してください", False),
    ("disk", ("空き容量", "空きが足りません", "No space left", "disk full", "ENOSPC", "WinError 112"),
     "パソコンの空きが足りません。いらないファイルを消してから [もう一度送る] を押してください", True),
    ("net", ("ネット", "接続", "つながらな", "timed out", "timeout", "URLError", "ConnectionError", "HTTP Error 5",
             "getaddrinfo", "WinError 10060", "WinError 10061", "WinError 11001", "SSL"),
     "ネットにつながりませんでした。ネットを確かめてから [もう一度送る] を押してください", True),
    ("transcribe", ("文字起こし", "whisper", "認識", "Vulkan", "CUDA", "transcribe"),
     "文字起こしが動きませんでした。パソコンを起動し直してから [もう一度送る] を押してください", False),
    ("dropbox", ("Dropbox", "鍵", "refresh token", "invalid_grant", "expired_access_token"),
     "Dropbox とのやり取りに失敗しました。少し待ってから [もう一度送る] を押してください", True),
    ("noHighlights", ("見どころが見つか", "切り抜く所が見つか", "パックができませんでした", "候補が 0", "no highlight"),
     "切り抜く所が見つかりませんでした。区間を指定して送り直してください", False),
    ("cancelled", ("止めました", "取り消し", "cancelled", "canceled"),
     "取り消しました", False),
)


def classify(text, kind="url"):
    """失敗の文 -> {code, message, retry, detail}。kind が file なら unavailable の言い換えと rangeOver を外す。当たらなければ unknown"""
    raw = "" if text is None else str(text)
    low = raw.lower()
    detail = raw[:DETAIL_MAX]
    for code, pats, message, retry in CODES:
        if code == RANGE_MSG_FILE_SKIP and kind == "file":
            continue
        if not any(p.lower() in low for p in pats):
            continue
        if code == "unavailable" and kind == "file":
            message = FILE_UNAVAILABLE
            retry = False
        return {"code": code, "message": message, "retry": retry, "detail": detail}
    return {"code": "unknown", "message": UNKNOWN_MSG, "retry": True, "detail": detail}


def _labels(kind, ranged):
    """その依頼の友人の段の名前(順)。ranged なら 見どころを探す を外す"""
    names = STAGES_FILE if kind == "file" else STAGES_URL
    if ranged:
        names = tuple(x for x in names if x != "見どころを探す")
    return names


def _friend_label(key, detail):
    """② の段の鍵 + detail -> 友人の段の名前(知らない鍵は None)"""
    lab = FRIEND_OF.get(key)
    if lab is None:
        return None
    if lab in ("見どころを探す", "切り抜き") and any(w in detail.lower() for w in FETCH_WORDS):
        return "動画を取得"
    return lab


def _stage_detail(label, detail):
    """文字起こしの進み: "3/5" -> "3/5 本"・"42%" -> "42%"・ほかは ""（C-2-15）"""
    if label != "文字起こし":
        return ""
    d = (detail or "").strip()
    m = re.match(r"^(\d+)\s*/\s*(\d+)$", d)
    if m:
        return "%s/%s 本" % (m.group(1), m.group(2))
    if re.match(r"^\d+(\.\d+)?%$", d):
        return d
    return ""


def _merge_state(states):
    """同じ友人の段が続いたときの状態(動いている > 失敗 > 待ち > 済み)"""
    for want in ("run", "error", "wait"):
        if want in states:
            return want
    return "done"


def stage(steps, kind="url", ranged=False):
    """② の段の一覧 -> 今の段 {index, total, label, detail} か None(全部済み・段が無い)。
    段は友人の名前に読み替え、同じ名前が続くときは 1 段にまとめる。ranged なら 見どころを探す を数えない"""
    allowed = _labels(kind, ranged)
    seq = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        detail = str(s.get("detail") or "")
        label = _friend_label(s.get("key"), detail)
        if label is None or label not in allowed:
            continue
        state = s.get("state")
        if seq and seq[-1]["label"] == label:
            seq[-1]["states"].append(state)
            seq[-1]["detail"] = detail or seq[-1]["detail"]
        else:
            seq.append({"label": label, "states": [state], "detail": detail})
    if not seq:
        return None
    cur = None
    for want in ("run", "error", "wait"):   # 今動いている段 > 失敗 > 次の待ち(済んだ段の次)
        for i, x in enumerate(seq):
            if _merge_state(x["states"]) == want:
                cur = i
                break
        if cur is not None:
            break
    if cur is None:
        return None
    x = seq[cur]
    return {"index": cur + 1, "total": len(seq), "label": x["label"], "detail": _stage_detail(x["label"], x["detail"])}


def _avg(stats, label):
    """記録の平均(秒)か None(記録が無い)"""
    xs = [v for v in ((stats or {}).get(label) or []) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not xs:
        return None
    return sum(xs) / float(len(xs))


def eta(stats, kind, ranged, current_label, elapsed_in_stage_sec):
    """残り時間(秒)。今の段の平均 − 今の段で経った秒(0 未満は 0)+ 後ろの段の平均の合計。必要な記録が 1 つでも無ければ None"""
    names = _labels(kind, ranged)
    if current_label not in names:
        return None
    i = names.index(current_label)
    cur = _avg(stats, current_label)
    if cur is None:
        return None
    elapsed = max(0.0, float(elapsed_in_stage_sec or 0))
    rest = 0.0
    for lab in names[i + 1:]:
        a = _avg(stats, lab)
        if a is None:
            return None
        rest += a
    return int(round(max(0.0, cur - elapsed) + rest))


def record(stats, label, seconds):
    """記録の写し(元は変えない)にその段の秒を先頭に足す。段ごとに新しい順 5 個まで"""
    out = {k: list(v) for k, v in (stats or {}).items()}
    out[label] = ([seconds] + out.get(label, []))[:5]
    return out


def slow(stage_started_ms, last_change_ms, now_ms):
    """1 つの段で 10 分(600 秒)進み(detail の変化)が無ければ真。段の始まりと最後の変化の遅いほうから数える"""
    since = max(stage_started_ms, last_change_ms)
    return now_ms - since >= SLOW_SEC * 1000


def _eta_text(sec):
    """残り秒 -> 「あと 1 分ほど」「あと約 12 分」「あと約 1 時間 20 分」"""
    if sec < 60:
        return ETA_SHORT_MSG
    if sec < 3600:
        return "あと約 %d 分" % max(1, sec // 60)
    h, m = sec // 3600, (sec % 3600) // 60
    if m == 0:
        return "あと約 %d 時間" % h
    return "あと約 %d 時間 %d 分" % (h, m)


def text(stage_dict, eta_sec, slow_flag, queue_pos=None, blocked=None):
    """画面に出す 1 行。待ち(queue_pos) > 空き不足(blocked = {freeGB, minGB}) > 動いている段の順"""
    if queue_pos is not None:
        if queue_pos == 1:
            return "順番を待っています(次に始まります)"
        return "順番を待っています(%s 番目)" % queue_pos
    if blocked is not None:
        need = int(math.ceil(blocked["minGB"] - blocked["freeGB"]))
        return "パソコンの空きが少ないので待っています(あと %d GB 空けると始まります)" % max(1, need)
    if stage_dict is None:
        return ""
    out = "%d/%d %s" % (stage_dict["index"], stage_dict["total"], stage_dict["label"])
    if stage_dict.get("detail"):
        out += "・" + stage_dict["detail"]
    if eta_sec is not None:
        out += "・" + _eta_text(eta_sec)
    if slow_flag:
        out += "・時間がかかっています"
    return out
