"""誰の声の材料を全メンバーぶんそろえる(10-25。ユーザー「誰の声を全部やったが本当に数人しかいなかった。全メンバー揃えてほしい」)。

手元の 学習用データ(評価用のフォルダの隣・<学習用データ>\\<名前>\\*.mov = 友人の仕上げたショート)を、入口の手が空いているときに
1 本ずつ「編集」の文字起こしに頼む。できた文書(元の動画 = その .mov)は、誰の声のカード(app/check/voice_solo)の材料になる:
  見立て = フォルダの名前の人(名簿のメンバーの名前のフォルダだけ。題名と動画のフォルダの名前で solo_person が見分ける)・1 本から PER_DOC 行。
  ほかの種類のカード(読み・時刻・声ですか など)には出さない(View.docs が外す = sources.voice_material)。
  .mov は読むだけ(動かさない・書かない。片付けも 学習用データ の下は移さない = manage/keep/cleanup の KEEP_FOLDERS)。
頼む順: まだ頼んだ数の少ない人から 1 本ずつ回る(全員に早く材料が入る)。頼んだ物は <app>/check/voice-material.json に覚え、2 度は頼まない。
手が空いているか = 入口の重い処理の順番・まとめて実行・編集の文字起こしのジョブが無い(入口の _accuracy_busy と同じ)・新しい版が出ていない
(出ていれば頼むのを休んで、入口の自動の起動し直しに合間を空ける)。ファイルの名前に「評価用」がある物(評価用データの写し)は頼まない。スイッチ ENABLED。
"""
import os
import time

from flow import voicematerial as _vm
from ytt import fsio, settings as _settings

ENABLED = True
LEARN_NAME = _vm.SHORT_DIR_NAME
STATE_NAME = "voice-material.json"
EXTS = (".mov", ".mp4", ".mkv", ".webm", ".m4v")
EVERY = 60          # 見回りの間隔(秒)。1 回に 1 本だけ頼む


def learn_dirs():
    """評価用のフォルダの隣の 学習用データ(あるもの)"""
    out = []
    for d in _settings.eval_dirs():
        p = os.path.join(os.path.dirname(os.path.normpath(d)), LEARN_NAME)
        if os.path.isdir(p) and not fsio.is_network_path(p):
            out.append(os.path.abspath(p))
    return list(dict.fromkeys(out))


FETCH_DIR_NAME = "voice-fetch"   # YouTube から取った誰の声の材料の音(app/check/voicefetch.DIR_NAME)


def eval_like(path):
    """評価用データの写し(ファイルの名前に「評価用」。学習用データに混ざっている)か = 声の材料にしない(評価の答えを学習に混ぜない。10-25)"""
    return "評価用" in os.path.basename(str(path or ""))


def in_learn_dir(path):
    """動画のパスが 学習用データ か、YouTube から取った誰の声の材料(voicefetch)の下か(パスの名前で見るだけ)= 誰の声のカードだけに使う文書"""
    return _vm.is_short(path) or FETCH_DIR_NAME in os.path.normpath(str(path or "")).split(os.sep)[:-1]


def targets(dirs=None):
    """[(名簿の名前, 動画のパス)]。名簿のメンバーの名前のフォルダの直下の動画だけ"""
    out = []
    for root in (learn_dirs() if dirs is None else dirs):
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            who = _vm.member(n)
            d = os.path.join(root, n)
            if not who or not os.path.isdir(d):
                continue
            try:
                files = sorted(os.listdir(d))
            except OSError:
                continue
            out += [(who, os.path.join(d, f)) for f in files if f.lower().endswith(EXTS) and not eval_like(f) and os.path.isfile(os.path.join(d, f))]
    return out


def _state_path(app_dir):
    return os.path.join(app_dir, "check", STATE_NAME)


def pick(items, state):
    """次に頼む 1 本 (名前, パス) か None: まだ頼んでいない物のうち、頼んだ数の少ない人から"""
    done = {}
    for v in state.values():
        if isinstance(v, dict) and v.get("who"):
            done[v["who"]] = done.get(v["who"], 0) + 1
    todo = [(who, p) for who, p in items if os.path.normcase(p) not in state]
    if not todo:
        return None
    return min(todo, key=lambda x: (done.get(x[0], 0), x[0], x[1]))


def tick(app_dir, start_job, busy, log, dirs=None, now=None):
    """手が空いていれば 1 本頼む。start_job(要求) -> ジョブ id(失敗は例外)。busy() -> 理由か None。-> 頼んだパスか None"""
    if not ENABLED or busy():
        return None
    path = _state_path(app_dir)
    state = fsio.read_json_or(path, {}, kind=dict)
    got = pick(targets(dirs), state)
    if got is None:
        return None
    who, src = got
    rec = {"who": who, "at": int((time.time() if now is None else now) * 1000)}
    try:
        rec["job"] = start_job({"sourcePath": src, "autoLlm": False})
    except Exception as e:   # noqa: BLE001  (頼めなかった物は理由を覚えて飛ばす = 次の 1 本へ)
        rec["error"] = "%s: %s" % (e.__class__.__name__, str(e)[:200])
    state[os.path.normcase(src)] = rec
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsio.write_json(path, state, indent=None)
    left = sum(1 for _w, p in targets(dirs) if os.path.normcase(p) not in state)
    log("誰の声の材料: %s の %s を文字起こしに頼みました(残り %d 本)%s" % (who, os.path.basename(src), left, "" if "job" in rec else " — 頼めませんでした " + rec["error"]))
    return src
