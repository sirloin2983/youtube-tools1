"""評価データ(友人用 文字起こし簡易版の「送る用ファイル」)の形式と規則。書き出す側(editor/ed_lite.py)と
受け取る側(dev/eval_import.py)が同じ規則を使うための1か所。標準ライブラリだけ・純粋な関数(ファイルを書くのは呼び出し側)。

設計の正本: .design/friend-transcribe-lite/DESIGN_BRIEF.md の「文字起こしルールと評価データ」「セキュリティ」「エッジケース」。

- 記号の規則: 聞き取れない所は "[?]"、笑い声などは "[笑]"。評価データには残し、Resolve 用の字幕からは取り除く(strip_marks)
- 形式違いの記号(【笑】・(笑)・w など)は bad_marks で見つける。評価ではその行だけを外す(データは消さず、印と理由を残す)
- 整えてしまった疑い(生出力よりフィラーが大きく減った)は tidy_suspect。作業ごと外す。基準は仮(最初のデータを見て調整)
- 絶対パス(PC のユーザー名を含む)は入れない: scrub_paths でファイル名だけにし、find_abs_paths で残っていないか確かめる
- 届いた zip は信用しない: check_zip が展開する前に名前・数・大きさ・種類を確かめ、extract_zip は確かめた名前だけを書く
"""
import json
import os
import re
import stat
import unicodedata
import zipfile

FORMAT = "youtube-tools-eval/v1"   # 送る用 zip の形式の名前(meta.json・final.json・asr_raw.json に入れる)
FORMAT_VERSION = 1
RULES_VERSION = 1                  # 友人に渡す書き方のルールの版(RULES を変えたら上げる。meta.json に残す)
RULES = (
    "言った言葉はすべて書く(「えー」・言い直し・噛みも含む)",
    "聞き取れない所は [?]、笑い声などは [笑] にする",
    "二人が同時に話したら、行を分けて話者ごとに書く",
    "言っていない言葉は足さない",
)
MARK_UNSURE, MARK_LAUGH = "[?]", "[笑]"
MARKS = (MARK_UNSURE, MARK_LAUGH)

# zip の中身(平らに並べる。フォルダは作らない)。edits.jsonl は空でも入れる
FILES = ("audio.flac", "asr_raw.json", "final.json", "edits.jsonl", "meta.json")
MAX_BYTES = {"audio.flac": 1024 * 1024 * 1024, "asr_raw.json": 64 * 1024 * 1024, "final.json": 32 * 1024 * 1024,
             "edits.jsonl": 32 * 1024 * 1024, "meta.json": 1024 * 1024}
MAX_ENTRIES = 16          # 中身の数の上限(想定は5つ。多すぎる zip は中を見ずに断る)
MAX_RATIO = 200           # 展開後 / 圧縮後 の上限(zip 爆弾)。小さなファイル(1MB 未満)は数えない
ZIP_SUFFIX = ".zip"

# 整えてしまった疑い(仮の基準。ブリーフの保留「最初のデータを見て調整」)
TIDY_MIN_RAW_FILLERS = 10   # 生出力のフィラーがこれより少なければ判定しない(短い動画で外しすぎない)
TIDY_MIN_RATIO = 0.4        # 校正後のフィラー / 生出力のフィラー がこれ未満なら疑い
FILLERS = ("えーっと", "えーと", "えっと", "あのー", "あの", "えー", "あー", "うーん", "うん", "んー", "まあ", "なんか", "その")

_BRACKET = re.compile(r"\[[^\[\]\n]{0,12}\]")
_SPACE = re.compile(r"[ \t　]+")
_PUNCT_RUN = re.compile(r"([、。,，.．!！?？…])(?:[ 　]*[、。,，.．])+")
_LEAD_PUNCT = re.compile(r"^[ 　、。,，.．]+")
_BAD = (
    re.compile(r"[【［(（〔<＜《「]\s*(?:笑|わら|ワラ|爆笑|苦笑|\?|？)\s*[】］)）〕>＞》」]"),   # 【笑】 (笑) （？） など(括弧の形が違う)
    re.compile(r"\[\s*(?:？|わら|ワラ|笑い|爆笑|苦笑|不明|聞き取れず|\?\?+)\s*\]"),          # [？] [わら] [不明] など(中身が違う)
    re.compile(r"(?<![A-Za-zＡ-Ｚａ-ｚ])[wｗＷ]{1,}(?![A-Za-zＡ-Ｚａ-ｚ])"),                  # w・ｗｗｗ(英単語の中の w は数えない)
    re.compile(r"(?:^|(?<=[\s、。!！?？]))草+$"),                                            # 文の後ろの「草」(「道草」は数えない)
)


def _nfc(text):
    return unicodedata.normalize("NFC", str(text or ""))


def strip_marks(text):
    """Resolve 用の字幕の文字: [?]・[笑] を取り除き、余分な空白と続いた句読点を詰める。空になったら ""(その行は字幕にしない)。
    行の折り返しは、この結果の文字数で数える(呼び出し側。ブリーフのエッジケース)"""
    s = _nfc(text)
    for m in MARKS:
        s = s.replace(m, " ")
    s = _SPACE.sub(" ", s)
    s = re.sub(r"(?<=[^\x00-\x7f]) | (?=[^\x00-\x7f])", "", s)   # 日本語の文字の隣の空白は消す(記号を抜いた跡)
    s = _PUNCT_RUN.sub(lambda m: m.group(1) if m.group(1) not in "、,，" else _last_punct(m.group(0)), s)
    s = _LEAD_PUNCT.sub("", s).strip()
    return s


def _last_punct(run):
    """「、。」のように続いたら、強い方(文の終わり)を残す"""
    for ch in reversed(run):
        if ch in "。.．!！?？…":
            return ch
    return run.strip()[:1]


def bad_marks(text):
    """形式違いの記号の一覧(見つかった文字列。無ければ [])。正しい [?]・[笑] は数えない"""
    s = _nfc(text)
    found = []
    for b in _BRACKET.findall(s):
        if b not in MARKS:
            found.append(b)
    rest = _BRACKET.sub(" ", s)
    for rx in _BAD:
        for m in rx.finditer(rest if rx is not _BAD[1] else s):
            v = m.group(0)
            if v not in found:
                found.append(v)
    return found


def count_fillers(text):
    """フィラー(えー・あのー など)の数。長いものから数え、数えた所は消して二重に数えない。記号は数えない"""
    s = _nfc(text)
    for m in MARKS:
        s = s.replace(m, " ")
    n = 0
    for f in FILLERS:
        k = s.count(f)
        if k:
            n += k
            s = s.replace(f, " ")
    return n


def tidy_suspect(raw_texts, final_texts):
    """整えてしまった疑い -> (疑いか, 理由の文)。生出力に比べてフィラーが大きく減っていれば疑い(作業ごと外す)"""
    raw = sum(count_fillers(t) for t in raw_texts)
    fin = sum(count_fillers(t) for t in final_texts)
    if raw < TIDY_MIN_RAW_FILLERS:
        return False, ""
    ratio = fin / raw
    if ratio < TIDY_MIN_RATIO:
        return True, "フィラーが生出力の %d 個から %d 個に減っています(%.0f%%。基準 %.0f%%)" % (raw, fin, ratio * 100, TIDY_MIN_RATIO * 100)
    return False, ""


# ---------------------------------------------------------------- パス

_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//|/(?:Users|home|mnt|Volumes|private|tmp|var)/)")
_ABS_ANY = re.compile(r"(?:(?<![A-Za-z])[A-Za-z]:[\\/]|(?<!:)\\\\[^\\/\s]+[\\/]|(?<![A-Za-z0-9_.])/(?:Users|home)/[^/\s]+)")   # 「https://」の s:/ は数えない


def base_name(path):
    """パス -> ファイル名だけ(\\ と / のどちらの区切りでも)"""
    return re.split(r"[\\/]", str(path or ""))[-1]


def scrub_paths(obj, home=None):
    """JSON にする値の中の絶対パスをファイル名だけにした写しを返す(dict・list をたどる)。
    文字列の途中にパスやホームフォルダ(PC のユーザー名)が入っていれば、その部分を消す"""
    home = home if home is not None else os.path.expanduser("~")
    if isinstance(obj, dict):
        return {k: scrub_paths(v, home) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_paths(v, home) for v in obj]
    if isinstance(obj, str):
        s = obj
        if _ABS.match(s):
            return base_name(s)
        if home and len(home) > 3 and home.lower() in s.lower():
            s = re.sub(re.escape(home), "~", s, flags=re.IGNORECASE)
        if _ABS_ANY.search(s):
            s = re.sub(r"(?:(?<![A-Za-z])[A-Za-z]:[\\/]|(?<!:)\\\\)[^\s\"'<>|]*[\\/]", "", s)
            s = re.sub(r"/(?:Users|home)/[^\s\"'<>|]*/", "", s)
        return s
    return obj


def find_abs_paths(obj, where=""):
    """値の中に残っている絶対パスらしい文字列の一覧 [(場所, 文字列)](書き出しの最後の確認と、取り込みの検査)"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += find_abs_paths(v, "%s.%s" % (where, k) if where else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += find_abs_paths(v, "%s[%d]" % (where, i))
    elif isinstance(obj, str) and _ABS_ANY.search(obj):
        out.append((where, obj[:200]))
    return out


# ---------------------------------------------------------------- 名前

def safe_part(text, limit=40):
    """ファイル名の一部に使える文字だけ(Windows で使えない文字・制御文字・前後の点と空白を除く)。空なら "unknown" """
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "", _nfc(text)).strip(" .")
    s = re.sub(r"\s+", "_", s)[:limit]
    return s or "unknown"


def zip_name(date, streamer, work_id):
    """送る用 zip の名前: 日付_配信者_作業ID.zip(作業ID で二重の送付を見分ける)"""
    return "%s_%s_%s%s" % (safe_part(date, 10), safe_part(streamer), safe_part(work_id, 32), ZIP_SUFFIX)


WORK_ID = re.compile(r"^[0-9a-f]{12}$")


def work_id_of(name):
    """zip の名前 -> 作業ID(形が違えば None)"""
    m = re.match(r"^.+_([0-9a-f]{12})\.zip$", base_name(name), re.IGNORECASE)
    return m.group(1).lower() if m else None


def safe_url(url):
    """元の動画の URL(任意)。http・https で空白の無いものだけ・500 文字まで。違えば "" """
    u = str(url or "").strip()
    if len(u) > 500 or not re.match(r"^https?://[^\s<>\"']+$", u):
        return ""
    return u


# ---------------------------------------------------------------- 作業の記録(edits.jsonl)

OPS = ("split", "merge", "time", "confirm", "unconfirm", "speaker", "text", "add", "delete", "undo", "redo")
_OP_STR = {"row": 24, "with": 24, "edge": 8, "how": 16, "speaker": 24}
_OP_NUM = ("t", "start", "end", "at", "from", "to", "playedSec")


def sanitize_op(o):
    """画面から来た1件の操作 -> 保存する形(決まったキー・型・長さだけ)。形が違えば None。文字そのものは残さない(text は長さだけ)"""
    if not isinstance(o, dict) or o.get("op") not in OPS:
        return None
    out = {"op": o["op"]}
    for k, n in _OP_STR.items():
        v = o.get(k)
        if isinstance(v, str) and v:
            out[k] = re.sub(r"[^\w\-.]", "", v)[:n]
    for k in _OP_NUM:
        v = o.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e13:
            out[k] = round(float(v), 3)
    if isinstance(o.get("played"), bool):
        out["played"] = o["played"]   # 確定する前にその行を再生したか(聞かずに確定は弾かず、記録だけ)
    if isinstance(o.get("len"), int) and not isinstance(o.get("len"), bool):
        out["len"] = max(0, min(o["len"], 100000))
    return out


# ---------------------------------------------------------------- final.json・判定

def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def raw_links(row, raw_segments):
    """校正後の行 -> 時刻が重なる生出力の行の番号(生出力との対応)"""
    a, b = float(row["start"]), float(row["end"])
    return [i for i, r in enumerate(raw_segments) if overlap(a, b, float(r.get("start", 0)), float(r.get("end", 0))) > 0
            or (a == b and float(r.get("start", 0)) <= a <= float(r.get("end", 0)))]


def check_rows(rows):
    """行ごとの判定 -> [{"id", "use", "reasons": [...]}]。確認済みでない行・形式違いの記号の行は外す(データは消さない)"""
    out = []
    for r in rows:
        if not isinstance(r, dict):   # 形の違う行は飛ばす(届いた zip の中身は信用しない)
            continue
        why = []
        if not r.get("checked"):
            why.append("未確認")
        bad = bad_marks(r.get("text", ""))
        if bad:
            why.append("記号の形式違い: " + " ".join(bad[:5]))
        if not str(r.get("text") or "").strip():
            why.append("空の行")
        out.append({"id": str(r.get("id", "")), "use": not why, "reasons": why})
    return out


def judge(final, asr_raw, edits=()):
    """取り込みの判定(書き出し時の知らせにも使う)。-> {"format", "rulesVersion", "work": {"use", "reasons"}, "rows": [...],
    "notes": {"confirmedWithoutListening": 再生せずに確定した数, "badMarkRows": 形式違いの行の数, "unchecked": 未確認の行の数}}"""
    rows = [r for r in final.get("rows") or [] if isinstance(r, dict)]
    rcheck = check_rows(rows)
    raw_texts = [str(s.get("text") or "") if isinstance(s, dict) else "" for s in asr_raw.get("segments") or []]
    checked = [r for r in rows if r.get("checked")]
    # 整えた疑いは、確認済みの行が重なる生出力の範囲だけで比べる(途中までの作業で、未校正の部分を数えない)
    used = sorted({i for r in checked for i in (r.get("raw") if isinstance(r.get("raw"), list) else []) if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(raw_texts)})
    sus, why = tidy_suspect([raw_texts[i] for i in used], [r.get("text", "") for r in checked])
    work_reasons = [why] if sus else []
    if not checked:
        work_reasons.append("確認済みの行がありません")
    blind = sum(1 for e in edits or () if isinstance(e, dict) and e.get("op") == "confirm" and e.get("played") is False)
    return {"format": FORMAT, "rulesVersion": RULES_VERSION, "work": {"use": not work_reasons, "reasons": work_reasons}, "rows": rcheck,
            "notes": {"confirmedWithoutListening": blind, "badMarkRows": sum(1 for c in rcheck if any(x.startswith("記号") for x in c["reasons"])),
                      "unchecked": sum(1 for r in rows if not r.get("checked"))}}


# ---------------------------------------------------------------- 届いた zip の検証

class BundleError(Exception):
    pass


def _is_symlink(info):
    return stat.S_ISLNK(info.external_attr >> 16)


def check_zip(path):
    """届いた zip を展開する前に確かめる -> (確かめた ZipInfo の dict {名前: info}, 問題の一覧)。問題が1つでもあれば展開しない。
    見るもの: zip として読めるか・数・名前(FILES のどれかで平ら。../・絶対パス・\\・フォルダ・重複は断る)・暗号化・リンク・大きさ・圧縮率"""
    problems, ok = [], {}
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        return {}, ["zip として読めません: %s" % e]
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            return {}, ["中身が多すぎます(%d 個。上限 %d)" % (len(infos), MAX_ENTRIES)]
        for info in infos:
            name = info.filename
            parts = re.split(r"[\\/]", name)
            if "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in parts:
                problems.append("危ない名前: %r" % name[:120])
                continue
            if name.endswith("/") or info.is_dir():
                problems.append("フォルダは入れない決まりです: %r" % name[:120])
                continue
            if name not in FILES:
                problems.append("想定外のファイル: %r" % name[:120])
                continue
            if name in ok:
                problems.append("同じ名前が2つあります: %s" % name)
                continue
            if info.flag_bits & 0x1:
                problems.append("暗号化されています: %s" % name)
                continue
            if _is_symlink(info):
                problems.append("リンクは受け付けません: %s" % name)
                continue
            if info.file_size > MAX_BYTES[name]:
                problems.append("%s が大きすぎます(%d バイト)" % (name, info.file_size))
                continue
            if info.file_size >= 1024 * 1024 and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                problems.append("%s の圧縮率が異常です" % name)
                continue
            ok[name] = info
        for need in FILES:
            if need not in ok and not any(need in p for p in problems):
                problems.append("%s がありません" % need)
    return ok, problems


def extract_zip(path, dest):
    """check_zip で問題が無いときだけ、確かめた名前を dest の直下に書く(書いた大きさも上限で止める)。-> 書いたパスの一覧。
    問題があれば BundleError(何も書かない)"""
    ok, problems = check_zip(path)
    if problems:
        raise BundleError("; ".join(problems))
    os.makedirs(dest, exist_ok=True)
    out = []
    with zipfile.ZipFile(path) as zf:
        for name, info in ok.items():
            target = os.path.join(dest, name)
            if os.path.dirname(os.path.abspath(target)) != os.path.abspath(dest):   # 念のため(名前は FILES のどれかなので起きない)
                raise BundleError("危ない名前: %r" % name)
            left = MAX_BYTES[name]
            with zf.open(info) as src, open(target + ".part", "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    left -= len(chunk)
                    if left < 0:
                        raise BundleError("%s が宣言より大きい" % name)
                    dst.write(chunk)
            os.replace(target + ".part", target)
            out.append(target)
    return out


def read_json_bytes(data, what):
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise BundleError("%s を JSON として読めません: %s" % (what, e))
    if not isinstance(obj, dict):
        raise BundleError("%s の形が違います" % what)
    return obj


def read_edits(data):
    """edits.jsonl の中身 -> 操作の一覧(読めない行は飛ばす。sanitize_op を通す)"""
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = sanitize_op(json.loads(line))
        except ValueError:
            continue
        if o:
            out.append(o)
    return out
